from __future__ import annotations

import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha1
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple

from packages.contracts.workbench_contracts import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
)
from packages.contracts.workbench_contracts.models import (
    SubjectDomainAvailability,
    SubjectDomainAvailabilityStatus,
    SubjectMonitoringDrilldown,
    SubjectOverview,
    SubjectTimelineEvent,
    SubjectTimelineEventDatePrecision,
    SubjectTimelineEventSubtype,
    SubjectTimelineEventType,
    SubjectTrendDirection,
    SubjectTrendDomain,
    SubjectTrendMetric,
    SubjectTrendPoint,
    SubjectVisitAnchor,
)

from .listing_file_parser import parse_listing_file
from .monitoring_source_revision import (
    public_monitoring_source_revision,
    read_monitoring_source,
)
from .monitoring_source_fragment import resolve_listing_fragment, resolve_protocol_fragment
from .protocol_text_extractor import ProtocolTextDocument, parse_protocol_docx


MY009_PROJECT_ID = "proj_my009_uc"
MY009_BATCH_ID = "my009_uc_listing_20260408"
DEFAULT_LISTING_LABEL = "MY009-UC-MM-Listing"
CM_SHEETS = ("CM", "CM1")
STUDY_DRUG_SHEETS = ("DA", "EX", "EX2", "EX3")
LAB_SHEETS = ("LB1", "LB2", "LB4", "LB5", "LB15")

SAFETY_METRICS = {
    ("LB1", "WBC"): ("wbc", "白细胞计数"),
    ("LB1", "Hb"): ("hemoglobin", "血红蛋白"),
    ("LB1", "PLT"): ("platelet", "血小板计数"),
    ("LB1", "NEU"): ("anc", "中性粒细胞绝对值"),
    ("LB2", "ALT"): ("alt", "丙氨酸氨基转移酶（ALT）"),
    ("LB2", "AST"): ("ast", "天门冬氨酸氨基转移酶（AST）"),
    ("LB2", "GGT"): ("ggt", "γ-谷氨酰转肽酶（GGT）"),
    ("LB2", "ALP"): ("alp", "碱性磷酸酶（ALP）"),
    ("LB2", "TBIL"): ("tbil", "总胆红素（TBIL）"),
    ("LB2", "Cr"): ("creatinine", "肌酐"),
    ("LB2", "FBG"): ("fasting_glucose", "空腹血糖"),
    ("LB15", "ESR"): ("esr", "红细胞沉降率（ESR）"),
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _site_id(value: Any) -> str:
    raw = _text(value)
    return raw.zfill(2) if raw.isdigit() else raw


def _float(value: Any) -> Optional[float]:
    raw = _text(value).replace("＞", "").replace("＜", "").replace(">", "").replace("<", "")
    if raw in {"", ".", "NA", "N/A"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _score(value: Any) -> Optional[float]:
    match = re.match(r"\s*(-?\d+(?:\.\d+)?)", _text(value))
    return float(match.group(1)) if match else None


def _parse_date(value: Any) -> Optional[date]:
    raw = _text(value)
    match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _partial_date(value: Any) -> Tuple[Optional[str], SubjectTimelineEventDatePrecision]:
    raw = _text(value).replace("/", "-").replace(".", "-")
    day_match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})", raw)
    if day_match:
        try:
            parsed = date(
                int(day_match.group("year")),
                int(day_match.group("month")),
                int(day_match.group("day")),
            )
        except ValueError:
            return None, SubjectTimelineEventDatePrecision.UNKNOWN
        return parsed.isoformat(), SubjectTimelineEventDatePrecision.DAY
    month_match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{1,2})(?:-|$)", raw)
    if month_match and month_match.group("month") not in {"UK", "UNK"}:
        month = int(month_match.group("month"))
        if 1 <= month <= 12:
            return f"{month_match.group('year')}-{month:02d}", SubjectTimelineEventDatePrecision.MONTH
    year_match = re.match(r"^(?P<year>\d{4})", raw)
    if year_match:
        return year_match.group("year"), SubjectTimelineEventDatePrecision.YEAR
    return None, SubjectTimelineEventDatePrecision.UNKNOWN


def _partial_date_bounds(
    value: Any,
) -> Tuple[
    Optional[str],
    SubjectTimelineEventDatePrecision,
    Optional[str],
    Optional[str],
    str,
]:
    raw = _text(value)
    parsed, precision = _partial_date(raw)
    if parsed is None:
        return None, precision, None, None, "missing" if not raw else "unparsed"
    if precision == SubjectTimelineEventDatePrecision.DAY:
        return parsed, precision, parsed, parsed, "parsed"
    if precision == SubjectTimelineEventDatePrecision.MONTH:
        year, month = map(int, parsed.split("-"))
        return (
            parsed,
            precision,
            f"{year:04d}-{month:02d}-01",
            f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}",
            "partial",
        )
    if precision == SubjectTimelineEventDatePrecision.YEAR:
        return parsed, precision, f"{parsed}-01-01", f"{parsed}-12-31", "partial"
    return parsed, precision, None, None, "unparsed"


def _reference_bound(value: Any) -> Optional[float]:
    match = re.search(r"-?\d+(?:\.\d+)?", _text(value))
    return float(match.group(0)) if match else None


class My009MonitoringService:
    """Real-source MY009 monitoring adapter derived from the original listing and protocol."""

    def __init__(
        self,
        listing_path: Path,
        protocol_path: Path,
        listing_label: str = DEFAULT_LISTING_LABEL,
        source_batch_id: str = MY009_BATCH_ID,
    ):
        self.listing_path = Path(listing_path)
        self.protocol_path = Path(protocol_path)
        self.listing_label = listing_label.strip() or DEFAULT_LISTING_LABEL
        if "/" in self.listing_label or "\\" in self.listing_label:
            raise ValueError("listing_label must be a public business label, not a path")
        self.source_batch_id = source_batch_id.strip() or MY009_BATCH_ID
        if "/" in self.source_batch_id or "\\" in self.source_batch_id:
            raise ValueError("source_batch_id must be a public business identifier, not a path")
        self._sheets: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._sheets_revision: Optional[str] = None
        self._subject_rows: Optional[Dict[str, Dict[str, List[Tuple[int, Dict[str, str]]]]]] = None
        self._document: Optional[ProtocolTextDocument] = None
        self._document_revision: Optional[str] = None
        self._sheets_lock = Lock()
        self._subject_rows_lock = Lock()
        self._document_lock = Lock()

    def subject_ids(self) -> List[str]:
        ids = {_text(row.get("USUBJID") or row.get("SUBJID")) for _, row in self._rows("DS")}
        return sorted(item for item in ids if item)

    def site_ids(self) -> List[str]:
        return sorted({item["site"] for item in self.subject_catalog(MY009_PROJECT_ID)["subjects"]})

    def listing_row_count(self) -> int:
        return sum(len(rows) for rows in self._sheets_by_name().values())

    def protocol_rule_registry(self) -> Dict[str, List[Dict[str, Any]]]:
        candidates = {
            "efficacy": [
                ("MY009-UC-EFFICACY-ENDPOINTS-001", "docx:table:7:row:29"),
            ],
            "concomitant_medication": [
                ("MY009-UC-CONMED-PROHIBITED-001", "docx:table:7:row:30"),
            ],
            "lab_review": [
                ("MY009-UC-LAB-CS-REVIEW-001", "docx:paragraph:1351"),
            ],
            "study_drug": [
                ("MY009-UC-IP-AE-ACTION-001", "docx:paragraph:1499"),
                ("MY009-UC-IP-ADHERENCE-001", "docx:paragraph:1609"),
            ],
        }
        registry: Dict[str, List[Dict[str, Any]]] = {}
        for group, rules in candidates.items():
            resolved = []
            for rule_id, locator in rules:
                source_text = self._resolve_protocol_locator(locator)
                if not source_text:
                    continue
                resolved.append(
                    {
                        "rule_id": rule_id,
                        "source_locator": locator,
                        "source_text": source_text,
                        "resolved": True,
                    }
                )
            registry[group] = resolved
        return registry

    def subject_catalog(self, project_id: str) -> Dict[str, Any]:
        self._assert_project(project_id)
        dm_rows = {self._subject_id(row): (row_index, row) for row_index, row in self._rows("DM") if self._subject_id(row)}
        subjects: List[Dict[str, Any]] = []
        for subject_id in self.subject_ids():
            source_sheet, row_index, row = self._subject_identity(subject_id, dm_rows)
            sv_row = next((item for _, item in self._rows("SV", subject_id)), {})
            site_id = _site_id(row.get("SITEID") or sv_row.get("SITEID")) or "-"
            site_name = _text(row.get("SITE") or sv_row.get("SITE"))
            status = self._subject_status(subject_id)
            profile = " | ".join(item for item in [f"中心 {site_id}", site_name, status] if item)
            subjects.append(
                {
                    "id": subject_id,
                    "site": site_id,
                    "site_name": site_name,
                    "status": status,
                    "screening_number": subject_id,
                    "profile": profile,
                    "source_locator": self._source_locator(source_sheet, row_index),
                }
            )
        subjects.sort(key=lambda item: (str(item["site"]).zfill(3), str(item["id"])))
        return {
            "project_id": project_id,
            "source_batch_id": self.source_batch_id,
            "source_revision": self.source_revision(),
            "generated_at": utc_now().isoformat(),
            "subject_count": len(subjects),
            "subjects": subjects,
        }

    def evaluate_subject_risks(self, project_id: str, subject_id: str) -> List[RiskCase]:
        self._assert_subject(project_id, subject_id)
        risks: List[RiskCase] = []
        registry = self.protocol_rule_registry()
        adherence_rule = self._rule_by_id(registry, "MY009-UC-IP-ADHERENCE-001")
        if adherence_rule:
            for sheet_name in ("EX2", "EX3"):
                for row_index, row in self._rows(sheet_name, subject_id):
                    description = _text(row.get("EX2DESC") or row.get("EX3DESC"))
                    if re.search(r"漏服|多服|未服用|只服用一次|药物不够|暂停", description):
                        start_date = _text(row.get(f"{sheet_name}STDAT"))
                        end_date = _text(row.get(f"{sheet_name}ENDAT"))
                        line = _text(row.get("LINE"))
                        description_key = sha1(
                            re.sub(r"\s+", "", description).encode("utf-8")
                        ).hexdigest()[:10]
                        episode_key = "|".join(
                            [sheet_name, start_date, end_date, line, description_key]
                        )
                        period = (
                            f"{start_date}~{end_date}"
                            if start_date and end_date
                            else start_date or end_date or sheet_name
                        )
                        risks.append(
                            self._risk(
                                project_id,
                                subject_id,
                                "study_drug_adherence_review",
                                "study_treatment_adherence",
                                sheet_name,
                                f"{subject_id} {period} 试验药物服用记录需核对",
                                adherence_rule["rule_id"],
                                [
                                    self._source_locator(sheet_name, row_index),
                                    adherence_rule["source_locator"],
                                ],
                                "原始试验药物记录含漏服、多服、未服用或非计划服用描述；这是确定性文本触发的复核观察项，不等同于方案偏离结论。",
                                "核对原始用药记录、依从性计算、AE和方案偏离记录，形成处置建议，由当前医学用户确认或修订。",
                                RiskSeverity.HIGH,
                                aggregation_scope="episode",
                                episode_key=episode_key,
                            )
                        )

        lab_rule = self._rule_by_id(registry, "MY009-UC-LAB-CS-REVIEW-001")
        if lab_rule:
            refs = []
            for sheet_name in LAB_SHEETS:
                for row_index, row in self._rows(sheet_name, subject_id):
                    if _text(row.get("LBSIG")) == "异常有临床意义":
                        refs.append(self._source_locator(sheet_name, row_index))
            if refs:
                risks.append(
                    self._risk(
                        project_id,
                        subject_id,
                        "clinically_significant_lab_review",
                        "laboratory_abnormality",
                        "LB",
                        f"{subject_id} 临床意义实验室异常需核对AE/复测",
                        lab_rule["rule_id"],
                        refs[:10] + [lab_rule["source_locator"]],
                        "listing 中存在研究者标记为异常有临床意义的实验室结果；系统未自动推断CTCAE等级或AE漏报结论。",
                        "核对异常持续时间、复测、AE记录、伴随疾病和研究者解释后再作医学判断。",
                        RiskSeverity.HIGH,
                    )
                )
        return risks

    def subject_monitoring(self, project_id: str, subject_id: str) -> SubjectMonitoringDrilldown:
        self._assert_subject(project_id, subject_id)
        baseline = self._baseline_date(subject_id)
        timeline: List[SubjectTimelineEvent] = []
        timeline.extend(self._visit_events(project_id, subject_id, baseline))
        timeline.extend(self._medical_history_events(project_id, subject_id, baseline))
        timeline.extend(self._ae_events(project_id, subject_id, baseline))
        timeline.extend(self._cm_events(project_id, subject_id, baseline))
        timeline.extend(self._study_drug_events(project_id, subject_id, baseline))
        timeline.extend(self._lab_events(project_id, subject_id, baseline))
        timeline.extend(self._efficacy_events(project_id, subject_id, baseline))
        risk_ids_by_locator: Dict[str, set[str]] = {}
        for risk in self.evaluate_subject_risks(project_id, subject_id):
            for locator in risk.evidence_span_ids:
                risk_ids_by_locator.setdefault(locator, set()).add(risk.risk_instance_id)
        timeline = [
            event.model_copy(
                update={
                    "related_risk_ids": sorted(
                        set(event.related_risk_ids) | risk_ids_by_locator.get(event.source_locator, set())
                    )
                }
            )
            for event in timeline
        ]
        timeline.sort(key=lambda item: (item.event_date or "9999-99-99", item.event_type.value, item.source_record_id))
        efficacy_trends = self._link_trend_risks(
            self._efficacy_metrics(subject_id, baseline), risk_ids_by_locator
        )
        safety_trends = self._link_trend_risks(
            self._safety_metrics(subject_id, baseline), risk_ids_by_locator
        )
        return SubjectMonitoringDrilldown(
            project_id=project_id,
            subject_id=subject_id,
            source_revision=self.source_revision(),
            generated_at=utc_now(),
            subject=self._subject_overview(project_id, subject_id, baseline),
            visit_anchors=self._visit_anchors(subject_id, baseline),
            timeline=timeline,
            efficacy_trends=efficacy_trends,
            safety_trends=safety_trends,
            domain_availability=self._domain_availability(subject_id),
            risk_prompts=[],
            review_focus=[
                "CM/CM1仅作为非试验用合并用药；DA/EX/EX2/EX3独立进入试验药物变更链路。",
                "QS趋势按原始字段展示；疗效应答、缓解等派生结论仍需医学核对方案定义和字段映射。",
                "风险项均为待医学复核观察项，不自动形成对中心Query或正式结论。",
            ],
        )

    def _link_trend_risks(
        self,
        metrics: List[SubjectTrendMetric],
        risk_ids_by_locator: Dict[str, set[str]],
    ) -> List[SubjectTrendMetric]:
        linked: List[SubjectTrendMetric] = []
        for metric in metrics:
            points = [
                point.model_copy(
                    update={
                        "related_risk_ids": sorted(
                            set(point.related_risk_ids)
                            | risk_ids_by_locator.get(point.source_locator, set())
                        )
                    }
                )
                for point in metric.points
            ]
            linked.append(metric.model_copy(update={"points": points}))
        return linked

    def _sheets_by_name(self) -> Dict[str, List[Dict[str, str]]]:
        snapshot = read_monitoring_source(self.listing_path)
        if self._sheets is None or self._sheets_revision != snapshot.cache_key:
            with self._sheets_lock:
                snapshot = read_monitoring_source(self.listing_path)
                if self._sheets is None or self._sheets_revision != snapshot.cache_key:
                    parsed = parse_listing_file(self.listing_path.name, snapshot.content)
                    self._sheets = {sheet.sheet_name: sheet.rows for sheet in parsed}
                    self._sheets_revision = snapshot.cache_key
                    self._subject_rows = None
        return self._sheets

    def _subject_rows_by_id(self) -> Dict[str, Dict[str, List[Tuple[int, Dict[str, str]]]]]:
        sheets = self._sheets_by_name()
        if self._subject_rows is None:
            with self._subject_rows_lock:
                if self._subject_rows is None:
                    index: Dict[str, Dict[str, List[Tuple[int, Dict[str, str]]]]] = defaultdict(lambda: defaultdict(list))
                    for sheet_name, rows in sheets.items():
                        for row_index, row in enumerate(rows, start=1):
                            subject_id = self._subject_id(row)
                            if subject_id:
                                index[subject_id][sheet_name].append((row_index, row))
                    self._subject_rows = {subject_id: dict(subject_sheets) for subject_id, subject_sheets in index.items()}
        return self._subject_rows

    def _doc(self) -> ProtocolTextDocument:
        snapshot = read_monitoring_source(self.protocol_path)
        if self._document is None or self._document_revision != snapshot.cache_key:
            with self._document_lock:
                snapshot = read_monitoring_source(self.protocol_path)
                if self._document is None or self._document_revision != snapshot.cache_key:
                    self._document = parse_protocol_docx(self.protocol_path, snapshot.content)
                    self._document_revision = snapshot.cache_key
        return self._document

    def source_revision(self) -> str:
        listing_snapshot = read_monitoring_source(self.listing_path)
        protocol_snapshot = read_monitoring_source(self.protocol_path)
        return public_monitoring_source_revision(
            listing_snapshot,
            protocol_snapshot,
            self.source_batch_id,
        )

    def resolve_source_fragment(self, locator: str) -> Dict[str, Any]:
        if locator.startswith("docx:"):
            return resolve_protocol_fragment(self._doc(), locator)
        if locator.startswith("listing:"):
            return resolve_listing_fragment(
                self.listing_label,
                self._sheets_by_name(),
                locator,
            )
        raise ValueError("unsupported monitoring source locator")

    def risk_profile_revision(self) -> str:
        return "my009-protocol-v3.0-rules-v1"

    def risk_engine_version(self) -> str:
        return "my009-monitoring-risk-v0.9"

    def risk_resolution_complete(self) -> bool:
        # This adapter currently binds one manually exported listing plus protocol.
        return False

    def _rows(self, sheet_name: str, subject_id: str | None = None) -> List[Tuple[int, Dict[str, str]]]:
        if subject_id is not None:
            return list(self._subject_rows_by_id().get(subject_id, {}).get(sheet_name, []))
        return [(index, row) for index, row in enumerate(self._sheets_by_name().get(sheet_name, []), start=1)]

    def _resolve_protocol_locator(self, locator: str) -> str:
        paragraph = re.fullmatch(r"docx:paragraph:(\d+)", locator)
        if paragraph:
            target = int(paragraph.group(1))
            for item in self._doc().paragraphs:
                if item.paragraph_index == target and item.source_locator == locator:
                    return item.text.strip()
            return ""
        table = re.fullmatch(r"docx:table:(\d+):row:(\d+)", locator)
        if table:
            table_index, row_index = map(int, table.groups())
            if table_index >= len(self._doc().tables):
                return ""
            rows = self._doc().tables[table_index].rows
            if row_index >= len(rows):
                return ""
            return "；".join(_text(cell.text).replace("\n", "；") for cell in rows[row_index] if _text(cell.text))
        return ""

    def _rule_by_id(self, registry: Dict[str, List[Dict[str, Any]]], rule_id: str) -> Optional[Dict[str, Any]]:
        return next((rule for rules in registry.values() for rule in rules if rule["rule_id"] == rule_id), None)

    def _subject_id(self, row: Dict[str, Any]) -> str:
        return _text(row.get("USUBJID") or row.get("SUBJID"))

    def _subject_identity(
        self,
        subject_id: str,
        dm_rows: Optional[Dict[str, Tuple[int, Dict[str, str]]]] = None,
    ) -> Tuple[str, int, Dict[str, str]]:
        if dm_rows and subject_id in dm_rows:
            row_index, row = dm_rows[subject_id]
            return "DM", row_index, row
        for sheet_name in ("DS", "SV"):
            rows = self._rows(sheet_name, subject_id)
            if rows:
                row_index, row = rows[0]
                return sheet_name, row_index, row
        raise KeyError(f"MY009 subject has no DS/SV identity row: {subject_id}")

    def _source_locator(self, sheet_name: str, row_index: int) -> str:
        return f"listing:{self.listing_label}:sheet:{sheet_name}:row:{row_index}"

    def _subject_status(self, subject_id: str) -> str:
        for sheet_name in ("DS3", "DS2", "DM", "SV"):
            rows = self._rows(sheet_name, subject_id)
            if rows:
                row = rows[-1][1]
                return _text(row.get("DS3REA") or row.get("DS2REA") or row.get("STATUS")) or "状态未记录"
        return "状态未记录"

    def _baseline_date(self, subject_id: str) -> Optional[date]:
        for _, row in self._rows("DS1", subject_id):
            value = _parse_date(row.get("DS1DAT"))
            if value:
                return value
        visits = [(self._visit_code(row), _parse_date(row.get("VISDAT"))) for _, row in self._rows("SV", subject_id)]
        d1 = next((value for code, value in visits if code == "D1" and value), None)
        if d1:
            return d1
        return None

    def _screening_date(self, subject_id: str, baseline: Optional[date]) -> Optional[date]:
        dates = [_parse_date(row.get("VISDAT")) for _, row in self._rows("SV", subject_id)]
        return min((item for item in dates if item), default=baseline)

    def _visit_code(self, row: Dict[str, Any]) -> str:
        visit = _text(row.get("VISIT"))
        if "筛选" in visit:
            return "SCR"
        if "研究结束" in visit:
            return "EOS"
        match = re.search(r"\((D-?\d+)\)", visit, re.I)
        if match:
            return match.group(1).upper()
        return _text(row.get("__STUDYEVENTOID")) or "UNS"

    def _visit_label(self, row: Dict[str, Any]) -> str:
        return _text(row.get("VISIT")) or "未标注访视"

    def _planned_study_day(self, visit_code: str, visit_label: str) -> Optional[int]:
        match = re.fullmatch(r"D(?P<day>-?\d+)", visit_code)
        if match:
            return int(match.group("day"))
        label_match = re.search(r"\(D(?P<day>-?\d+)\)", visit_label, re.I)
        return int(label_match.group("day")) if label_match else None

    def _study_day(self, value: Optional[date], baseline: Optional[date]) -> Optional[int]:
        if value is None or baseline is None:
            return None
        delta = (value - baseline).days
        return delta + 1 if delta >= 0 else delta

    def _event_date(
        self,
        row: Dict[str, Any],
        fields: Iterable[str],
        fallback: Optional[date] = None,
    ) -> Optional[date]:
        for field in fields:
            value = _parse_date(row.get(field))
            if value:
                return value
        return fallback

    def _event(
        self,
        project_id: str,
        subject_id: str,
        event_type: SubjectTimelineEventType,
        event_date: Optional[date],
        baseline: Optional[date],
        source_domain: str,
        row_index: int,
        row: Dict[str, Any],
        title: str,
        detail: str,
        result_value: str | None = None,
        interpretation: str = "",
        event_subtype: SubjectTimelineEventSubtype = SubjectTimelineEventSubtype.OTHER,
        event_end_date: Optional[date] = None,
        ongoing: bool = False,
        date_precision: SubjectTimelineEventDatePrecision = SubjectTimelineEventDatePrecision.DAY,
        event_date_text: Optional[str] = None,
        event_end_date_text: Optional[str] = None,
        original_event_date: Optional[str] = None,
        original_event_end_date: Optional[str] = None,
        is_planned: Optional[bool] = None,
        is_unscheduled: bool = False,
        severity: str = "",
        relationship: str = "",
        outcome: str = "",
    ) -> SubjectTimelineEvent:
        locator = self._source_locator(source_domain, row_index)
        event_hash = sha1(f"{project_id}|{subject_id}|{event_type.value}|{locator}|{title}".encode("utf-8")).hexdigest()[:12]
        normalized_event_date = event_date_text or (event_date.isoformat() if event_date else None)
        normalized_event_end_date = event_end_date_text or (event_end_date.isoformat() if event_end_date else None)
        raw_event_date = original_event_date or normalized_event_date or ""
        raw_event_end_date = original_event_end_date or normalized_event_end_date or ""
        _, _, earliest, latest, parse_status = _partial_date_bounds(raw_event_date)
        return SubjectTimelineEvent(
            event_id=f"my009_event_{event_hash}",
            project_id=project_id,
            subject_id=subject_id,
            event_type=event_type,
            event_subtype=event_subtype,
            event_date=normalized_event_date,
            event_end_date=normalized_event_end_date,
            raw_event_date=raw_event_date,
            raw_event_end_date=raw_event_end_date,
            earliest_possible_date=earliest,
            latest_possible_date=latest,
            date_parse_status=parse_status,
            study_day=self._study_day(event_date, baseline),
            end_study_day=self._study_day(event_end_date, baseline),
            ongoing=ongoing,
            date_precision=(
                date_precision
                if normalized_event_date
                else SubjectTimelineEventDatePrecision.UNKNOWN
            ),
            is_planned=is_planned,
            is_unscheduled=is_unscheduled,
            visit_code=self._visit_code(row),
            visit_label=self._visit_label(row),
            source_domain=source_domain,
            source_record_id=f"{source_domain}:{row_index}",
            source_locator=locator,
            title=title,
            detail=detail,
            result_value=result_value,
            severity=severity,
            relationship=relationship,
            outcome=outcome,
            clinical_interpretation=interpretation,
        )

    def _visit_anchors(
        self,
        subject_id: str,
        baseline: Optional[date],
    ) -> List[SubjectVisitAnchor]:
        anchors: List[SubjectVisitAnchor] = []
        for row_index, row in self._rows("SV", subject_id):
            if _text(row.get("SVYN")).startswith("否"):
                continue
            actual_date = _parse_date(row.get("VISDAT"))
            visit_code = self._visit_code(row)
            visit_label = self._visit_label(row)
            planned_day = self._planned_study_day(visit_code, visit_label)
            actual_day = self._study_day(actual_date, baseline)
            is_unscheduled = visit_code == "UNS" or "计划外" in visit_label
            anchors.append(
                SubjectVisitAnchor(
                    anchor_id=f"my009_visit_{subject_id}_{row_index}",
                    visit_code=visit_code,
                    visit_label=visit_label,
                    planned_study_day=planned_day,
                    actual_date=actual_date.isoformat() if actual_date else None,
                    actual_study_day=actual_day,
                    is_unscheduled=is_unscheduled,
                    deviation_days=(
                        actual_day - planned_day
                        if actual_day is not None and planned_day is not None and not is_unscheduled
                        else None
                    ),
                    source_domain="SV",
                    source_record_id=f"SV:{row_index}",
                    source_locator=self._source_locator("SV", row_index),
                )
            )
        return sorted(
            anchors,
            key=lambda item: (
                item.actual_date or "9999-99-99",
                item.actual_study_day if item.actual_study_day is not None else 10**9,
                item.anchor_id,
            ),
        )

    def _domain_availability(self, subject_id: str) -> List[SubjectDomainAvailability]:
        domains = [
            ("SV", "访视", ("SV",)),
            ("MH", "病史", ("MH", "MH1")),
            ("AE", "不良事件", ("AE",)),
            ("CM", "合并用药（非试验用药）", CM_SHEETS),
            ("IP", "试验药物", STUDY_DRUG_SHEETS),
            ("LAB", "实验室检查", LAB_SHEETS),
            ("EFFICACY", "疗效评估", ("QS",)),
        ]
        results = []
        for domain, label, sheets in domains:
            available = any(self._rows(sheet_name, subject_id) for sheet_name in sheets)
            results.append(
                SubjectDomainAvailability(
                    domain=domain,
                    label=label,
                    status=(
                        SubjectDomainAvailabilityStatus.AVAILABLE
                        if available
                        else SubjectDomainAvailabilityStatus.ABSENT
                    ),
                    detail=(
                        "原始 listing 中存在该受试者记录。"
                        if available
                        else "原始 listing 中未发现该受试者记录。"
                    ),
                )
            )
        return results

    def _visit_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("SV", subject_id):
            event_date = _parse_date(row.get("VISDAT"))
            if not event_date or _text(row.get("SVYN")).startswith("否"):
                continue
            is_unscheduled = self._visit_code(row) == "UNS" or "计划外" in self._visit_label(row)
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.VISIT,
                    event_date,
                    baseline,
                    "SV",
                    row_index,
                    row,
                    self._visit_label(row),
                    "原始访视日期记录",
                    event_subtype=(
                        SubjectTimelineEventSubtype.UNSCHEDULED_VISIT
                        if is_unscheduled
                        else SubjectTimelineEventSubtype.PLANNED_VISIT
                    ),
                    is_planned=not is_unscheduled,
                    is_unscheduled=is_unscheduled,
                )
            )
        return events

    def _medical_history_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for sheet_name in ("MH", "MH1"):
            for row_index, row in self._rows(sheet_name, subject_id):
                term = _text(row.get("MH1TERM"))
                if sheet_name == "MH":
                    term = "溃疡性结肠炎病史" if _text(row.get("MHDAT")) else ""
                if not term:
                    continue
                original_date = _text(row.get("MH1STDAT") or row.get("MHDAT"))
                original_end_date = _text(row.get("MH1ENDAT"))
                normalized_date, precision = _partial_date(original_date)
                normalized_end_date, _ = _partial_date(original_end_date)
                parsed_date = _parse_date(normalized_date)
                parsed_end_date = _parse_date(normalized_end_date)
                detail_parts = ["原始listing登记的既往/现病史"]
                if original_date:
                    detail_parts.append(f"原始起始日期：{original_date}")
                else:
                    detail_parts.append("原始起始日期未提供")
                if _text(row.get("MHRANG")):
                    detail_parts.append(f"疾病范围：{_text(row.get('MHRANG'))}")
                events.append(
                    self._event(
                        project_id,
                        subject_id,
                        SubjectTimelineEventType.MEDICAL_HISTORY,
                        parsed_date,
                        baseline,
                        sheet_name,
                        row_index,
                        row,
                        term,
                        "；".join(detail_parts),
                        event_subtype=SubjectTimelineEventSubtype.HISTORY_CONDITION,
                        event_end_date=parsed_end_date,
                        ongoing=_text(row.get("MH1ONGO")) == "是",
                        date_precision=precision,
                        event_date_text=normalized_date,
                        event_end_date_text=normalized_end_date,
                        original_event_date=original_date,
                        original_event_end_date=original_end_date,
                    )
                )
        return events

    def _ae_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("AE", subject_id):
            term = _text(row.get("AETERM"))
            if not term or _text(row.get("AEYN")) == "否":
                continue
            event_date = self._event_date(row, ("AESTDAT",))
            end_date = self._event_date(row, ("AEENDAT",))
            detail = "；".join(item for item in [f"严重程度：{_text(row.get('AESEV'))}" if _text(row.get("AESEV")) else "", f"相关性：{_text(row.get('AEREL'))}" if _text(row.get("AEREL")) else "", f"转归：{_text(row.get('AEOUT'))}" if _text(row.get("AEOUT")) else ""] if item)
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.ADVERSE_EVENT,
                    event_date,
                    baseline,
                    "AE",
                    row_index,
                    row,
                    term,
                    detail or "原始AE记录",
                    event_subtype=SubjectTimelineEventSubtype.ADVERSE_EVENT,
                    event_end_date=end_date,
                    ongoing=not bool(end_date) and _text(row.get("AEOUT")) not in {"已恢复/已痊愈", "死亡"},
                    severity=_text(row.get("AESEV")),
                    relationship=_text(row.get("AEREL")),
                    outcome=_text(row.get("AEOUT")),
                )
            )
        return events

    def _cm_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for sheet_name in CM_SHEETS:
            prefix = "CM1" if sheet_name == "CM1" else "CM"
            for row_index, row in self._rows(sheet_name, subject_id):
                term = _text(row.get(f"{prefix}TRT"))
                if not term or _text(row.get(f"{prefix}YN")) == "否":
                    continue
                event_date = self._event_date(row, (f"{prefix}STDAT",))
                end_date = self._event_date(row, (f"{prefix}ENDAT",))
                dose = " ".join(item for item in [_text(row.get(f"{prefix}DOSE")), _text(row.get(f"{prefix}DOSU")), _text(row.get(f"{prefix}FRQ") or row.get("CMDOSFRQ"))] if item)
                indication = _text(row.get(f"{prefix}INDC1"))
                detail = "；".join(item for item in ["非试验用合并用药", f"剂量/频次：{dose}" if dose else "", f"适应症：{indication}" if indication else ""] if item)
                events.append(
                    self._event(
                        project_id,
                        subject_id,
                        SubjectTimelineEventType.CONCOMITANT_MEDICATION,
                        event_date,
                        baseline,
                        sheet_name,
                        row_index,
                        row,
                        term,
                        detail,
                        event_subtype=SubjectTimelineEventSubtype.NON_STUDY_MEDICATION,
                        event_end_date=end_date,
                        ongoing=_text(row.get(f"{prefix}ONGO")) == "是",
                    )
                )
        return events

    def _study_drug_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for sheet_name in STUDY_DRUG_SHEETS:
            for row_index, row in self._rows(sheet_name, subject_id):
                if sheet_name == "DA":
                    if _text(row.get("DAYN")).startswith("否"):
                        continue
                    title = "试验药物发药"
                    detail = f"发药编号：{_text(row.get('DANO'))}" if _text(row.get("DANO")) else "原始发药记录"
                    event_date = self._event_date(row, ("DADAT",))
                    event_type = SubjectTimelineEventType.STUDY_DRUG_DISPENSING
                    event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_DISPENSING
                    end_date = None
                elif sheet_name == "EX":
                    if _text(row.get("EXYN")).startswith("否"):
                        continue
                    title = "试验药物访视日给药"
                    detail = "；".join(item for item in [f"频次：{_text(row.get('EXFRQ'))}" if _text(row.get("EXFRQ")) else "", f"时间：{_text(row.get('EXTIM'))}" if _text(row.get("EXTIM")) else ""] if item)
                    event_date = self._event_date(row, ("EXDAT",))
                    event_type = SubjectTimelineEventType.STUDY_DRUG_ADMINISTRATION
                    event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_ADMINISTRATION
                    end_date = None
                else:
                    prefix = sheet_name
                    if _text(row.get(f"{prefix}YN")).startswith("否"):
                        continue
                    description = _text(row.get(f"{prefix}DESC"))
                    adjustment_text = " ".join(
                        item
                        for item in [
                            _text(row.get(f"{prefix}ADJ")),
                            _text(row.get(f"{prefix}ADJ__2")),
                            description,
                        ]
                        if item
                    )
                    if re.search(r"永久停药|永久停止|终止用药", adjustment_text):
                        event_type = SubjectTimelineEventType.DOSE_ADJUSTMENT
                        event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_PERMANENT_DISCONTINUATION
                        title = "试验药物永久停药"
                    elif re.search(r"恢复|重新用药", adjustment_text):
                        event_type = SubjectTimelineEventType.DOSE_ADJUSTMENT
                        event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_RESUMPTION
                        title = "试验药物恢复"
                    elif re.search(r"暂停|中断", adjustment_text):
                        event_type = SubjectTimelineEventType.DOSE_ADJUSTMENT
                        event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_INTERRUPTION
                        title = "试验药物暂停"
                    elif re.search(r"减量|降低剂量", adjustment_text):
                        event_type = SubjectTimelineEventType.DOSE_ADJUSTMENT
                        event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_DOSE_REDUCTION
                        title = "试验药物减量"
                    elif re.search(r"加量|增加剂量", adjustment_text):
                        event_type = SubjectTimelineEventType.DOSE_ADJUSTMENT
                        event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_DOSE_INCREASE
                        title = "试验药物加量"
                    else:
                        event_type = SubjectTimelineEventType.STUDY_DRUG_ADHERENCE
                        event_subtype = SubjectTimelineEventSubtype.STUDY_DRUG_ADHERENCE
                        title = (
                            "导入期试验药物依从性"
                            if sheet_name == "EX2"
                            else "服药观察期试验药物依从性"
                        )
                    dose = " ".join(item for item in [_text(row.get(f"{prefix}DOSE")), _text(row.get(f"{prefix}DOSE1")), _text(row.get(f"{prefix}FRQ"))] if item)
                    detail = "；".join(item for item in [f"剂量/频次：{dose}" if dose else "", description] if item) or "原始试验药物记录"
                    event_date = self._event_date(row, (f"{prefix}STDAT",))
                    end_date = self._event_date(row, (f"{prefix}ENDAT",))
                events.append(
                    self._event(
                        project_id,
                        subject_id,
                        event_type,
                        event_date,
                        baseline,
                        sheet_name,
                        row_index,
                        row,
                        title,
                        detail,
                        event_subtype=event_subtype,
                        event_end_date=end_date,
                        ongoing=bool(sheet_name in {"EX2", "EX3"} and event_date and not end_date),
                    )
                )
        return events

    def _lab_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for sheet_name in LAB_SHEETS:
            for row_index, row in self._rows(sheet_name, subject_id):
                significance = _text(row.get("LBSIG"))
                if not significance.startswith("异常"):
                    continue
                test = _text(row.get("LBTEST"))
                result = _text(row.get("LBORRES"))
                if not test or not result:
                    continue
                event_date = self._event_date(row, ("LBDAT",))
                unit = _text(row.get("LBORRESU"))
                reference = f"{_text(row.get('LBORNRLO'))} ~ {_text(row.get('LBORNRHI'))}".strip(" ~")
                detail = "；".join(item for item in [significance, f"参考范围：{reference}" if reference else "", _text(row.get("LBCOM"))] if item)
                events.append(
                    self._event(
                        project_id,
                        subject_id,
                        SubjectTimelineEventType.LAB,
                        event_date,
                        baseline,
                        sheet_name,
                        row_index,
                        row,
                        f"{test} {result}{unit}",
                        detail,
                        result,
                        significance,
                        event_subtype=SubjectTimelineEventSubtype.LAB_RESULT,
                    )
                )
        return events

    def _efficacy_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("QS", subject_id):
            value = _float(row.get("QSCAL"))
            if value is None:
                continue
            event_date = self._event_date(row, ("QSDAT1", "QSDAT"))
            detail = "；".join(item for item in [_text(row.get("SF")), _text(row.get("RB")), _text(row.get("QSTEST2"))] if item)
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.EFFICACY_SCORE,
                    event_date,
                    baseline,
                    "QS",
                    row_index,
                    row,
                    f"部分Mayo评分 {value:g}",
                    detail,
                    f"{value:g}",
                    "原始listing计算值，待医学核对字段映射",
                    event_subtype=SubjectTimelineEventSubtype.EFFICACY_ASSESSMENT,
                )
            )
        return events

    def _efficacy_metrics(self, subject_id: str, baseline: Optional[date]) -> List[SubjectTrendMetric]:
        specs = [
            ("partial_mayo", "部分Mayo评分", "QSCAL"),
            ("stool_frequency", "Mayo排便次数子评分", "SF"),
            ("rectal_bleeding", "Mayo直肠出血子评分", "RB"),
        ]
        metrics = []
        for metric_key, label, field in specs:
            points = []
            for row_index, row in self._rows("QS", subject_id):
                value = _float(row.get(field)) if field == "QSCAL" else _score(row.get(field))
                event_date = self._event_date(row, ("QSDAT1", "QSDAT"))
                if value is None or event_date is None:
                    continue
                points.append(self._trend_point(metric_key, "QS", row_index, row, event_date, baseline, value, note="原始listing字段；派生疗效结论待医学核对"))
            if points:
                metrics.append(self._metric(metric_key, label, SubjectTrendDomain.EFFICACY, SubjectTrendDirection.LOWER_IS_BETTER, points))
        return metrics

    def _safety_metrics(self, subject_id: str, baseline: Optional[date]) -> List[SubjectTrendMetric]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for (sheet_name, test_code), (metric_key, label) in SAFETY_METRICS.items():
            points = []
            unit = ""
            for row_index, row in self._rows(sheet_name, subject_id):
                if _text(row.get("LBTESTCD")) != test_code:
                    continue
                value = _float(row.get("LBORRESN"))
                if value is None:
                    value = _float(row.get("LBORRES"))
                if value is None:
                    continue
                unit = unit or _text(row.get("LBORRESU"))
                event_date = self._event_date(row, ("LBDAT",))
                if event_date is None:
                    continue
                points.append(
                    self._trend_point(
                        metric_key,
                        sheet_name,
                        row_index,
                        row,
                        event_date,
                        baseline,
                        value,
                        reference_low=_reference_bound(row.get("LBORNRLO")),
                        reference_high=_reference_bound(row.get("LBORNRHI")),
                        risk_flag=_text(row.get("LBSIG")) == "异常有临床意义",
                        note=_text(row.get("LBSIG")),
                    )
                )
            if points:
                grouped[metric_key] = {"label": label, "unit": unit, "points": points}
        return [
            self._metric(key, value["label"], SubjectTrendDomain.SAFETY, SubjectTrendDirection.STABLE_RANGE, value["points"], value["unit"])
            for key, value in grouped.items()
        ]

    def _trend_point(
        self,
        metric_key: str,
        source_domain: str,
        row_index: int,
        row: Dict[str, Any],
        event_date: date,
        baseline: Optional[date],
        value: float,
        *,
        reference_low: float | None = None,
        reference_high: float | None = None,
        risk_flag: bool = False,
        note: str = "",
    ) -> SubjectTrendPoint:
        locator = self._source_locator(source_domain, row_index)
        normality = "not_applicable"
        if reference_low is not None or reference_high is not None:
            normality = "normal"
            if reference_low is not None and value < reference_low:
                normality = "low"
                risk_flag = True
            if reference_high is not None and value > reference_high:
                normality = "high"
                risk_flag = True
        point_hash = sha1(f"{metric_key}|{locator}|{value}".encode("utf-8")).hexdigest()[:12]
        return SubjectTrendPoint(
            point_id=f"my009_point_{point_hash}",
            visit_code=self._visit_code(row),
            visit_label=self._visit_label(row),
            assessment_date=event_date.isoformat(),
            study_day=self._study_day(event_date, baseline),
            value=value,
            original_value=_text(row.get("LBORRES")) or f"{value:g}",
            standardized_value=_float(row.get("LBSTRESN")),
            unit=_text(row.get("LBORRESU")),
            reference_low=reference_low,
            reference_high=reference_high,
            reference_range_text=_text(row.get("LBSTNRC")) or " ~ ".join(
                item
                for item in [_text(row.get("LBORNRLO")), _text(row.get("LBORNRHI"))]
                if item
            ),
            reference_range_source=_text(row.get("LBNAME")) or "原始listing",
            normality=normality,
            abnormal_direction=normality if normality in {"high", "low"} else "",
            clinical_significance=_text(row.get("LBSIG")),
            assessment_sequence=(
                int(_text(row.get("LINE")))
                if _text(row.get("LINE")).isdigit() and int(_text(row.get("LINE"))) > 0
                else None
            ),
            is_unscheduled=self._visit_code(row) == "UNS" or "计划外" in self._visit_label(row),
            risk_flag=risk_flag,
            source_domain=source_domain,
            source_record_id=f"{source_domain}:{row_index}",
            source_locator=locator,
            note=note,
        )

    def _metric(
        self,
        metric_key: str,
        label: str,
        domain: SubjectTrendDomain,
        direction: SubjectTrendDirection,
        points: List[SubjectTrendPoint],
        unit: str = "",
    ) -> SubjectTrendMetric:
        points.sort(key=lambda item: (item.assessment_date, item.source_record_id))
        baseline_point = next((point for point in points if point.visit_code == "D1"), None)
        hydrated = [
            point.model_copy(
                update={
                    "baseline_value": baseline_point.value if baseline_point else None,
                    "is_baseline": point.point_id == baseline_point.point_id if baseline_point else False,
                    "baseline_rule": "方案定义的D1给药前评估值；缺失时不使用筛选期值替代。",
                    "baseline_source_locator": baseline_point.source_locator if baseline_point else "",
                    "change_from_baseline": (
                        point.value - baseline_point.value if baseline_point else None
                    ),
                    "percent_change_from_baseline": (
                        (point.value - baseline_point.value) / baseline_point.value * 100
                        if baseline_point and baseline_point.value != 0
                        else None
                    ),
                }
            )
            for point in points
        ]
        return SubjectTrendMetric(
            metric_key=metric_key,
            metric_label=label,
            domain=domain,
            unit=unit,
            direction=direction,
            points=hydrated,
        )

    def _subject_overview(self, project_id: str, subject_id: str, baseline: Optional[date]) -> SubjectOverview:
        dm_rows = self._rows("DM", subject_id)
        dm = dm_rows[0][1] if dm_rows else {}
        _, _, identity = self._subject_identity(subject_id)
        sv_identity = next((row for _, row in self._rows("SV", subject_id)), {})
        ds1 = self._rows("DS1", subject_id)
        randomization_number = _text(ds1[0][1].get("DS1NUM")) if ds1 else None
        visits = [(row, _parse_date(row.get("VISDAT"))) for _, row in self._rows("SV", subject_id)]
        dated_visits = [(row, value) for row, value in visits if value]
        latest_row, latest_date = max(dated_visits, key=lambda item: item[1])
        first_dose = min(
            (value for _, row in self._rows("EX", subject_id) for value in [_parse_date(row.get("EXDAT"))] if value),
            default=None,
        )
        return SubjectOverview(
            project_id=project_id,
            subject_id=subject_id,
            site_id=_site_id(dm.get("SITEID") or identity.get("SITEID") or sv_identity.get("SITEID")) or "-",
            screening_number=subject_id,
            randomization_number=randomization_number,
            treatment_arm="待解盲",
            enrollment_status=self._subject_status(subject_id),
            first_dose_date=first_dose.isoformat() if first_dose else None,
            baseline_visit_date=baseline.isoformat() if baseline else None,
            latest_visit_code=self._visit_code(latest_row),
            latest_visit_label=self._visit_label(latest_row),
            latest_visit_date=latest_date.isoformat(),
            sex=_text(dm.get("SEX")) or None,
            age_years=_float(dm.get("AGE")),
            blinded=True,
            treatment_arm_masked=True,
            key_medical_context=[
                item
                for item in [
                    f"性别：{_text(dm.get('SEX'))}" if _text(dm.get("SEX")) else "",
                    f"年龄：{_text(dm.get('AGE'))}" if _text(dm.get("AGE")) else "",
                    "随机分组信息保持盲态",
                ]
                if item
            ],
        )

    def _risk(
        self,
        project_id: str,
        subject_id: str,
        risk_type: str,
        primary_category: str,
        source_domain: str,
        title: str,
        rule_id: str,
        evidence_span_ids: List[str],
        rationale: str,
        recommended_action: str,
        severity: RiskSeverity,
        *,
        aggregation_scope: str = "rule_scope",
        episode_key: str = "",
    ) -> RiskCase:
        source_revision = self.source_revision()
        rule_profile_revision = self.risk_profile_revision()
        engine_version = self.risk_engine_version()
        identity_parts = [project_id, "subject", subject_id, rule_id]
        if aggregation_scope == "episode":
            identity_parts.append(episode_key)
        stable_hash = sha1("|".join(identity_parts).encode("utf-8")).hexdigest()[:16]
        instance_hash = sha1(
            (
                f"{stable_hash}|{self.source_batch_id}|{source_revision}|"
                f"{rule_profile_revision}|{engine_version}|{'|'.join(evidence_span_ids)}"
            ).encode("utf-8")
        ).hexdigest()[:16]
        risk_hash = sha1(f"{project_id}|{subject_id}|{rule_id}|{'|'.join(evidence_span_ids)}".encode("utf-8")).hexdigest()[:12]
        return RiskCase(
            risk_id=f"my009_risk_{risk_hash}",
            risk_key=f"riskkey_{stable_hash}",
            risk_instance_id=f"riskinst_{instance_hash}",
            project_id=project_id,
            module="medical_monitoring",
            risk_type=risk_type,
            primary_category=primary_category,
            tags=sorted(
                {
                    "cfdi",
                    f"source_domain:{source_domain.strip().lower()}",
                    *(
                        ("potential_pd", "study_treatment_record")
                        if primary_category == "study_treatment_adherence"
                        else ("safety_pv",)
                    ),
                }
            ),
            title=title,
            subject_id=subject_id,
            site_id=self._site_id(subject_id),
            scope_type="subject",
            scope_id=subject_id,
            aggregation_scope=aggregation_scope,
            episode_key=episode_key,
            severity=severity,
            inspection_priority="high" if severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL} else "medium",
            action_priority="medical_review_required",
            status=RiskStatus.ACTION_REQUIRED,
            source_batch_id=self.source_batch_id,
            source_revision=source_revision,
            rule_profile_revision=rule_profile_revision,
            engine_version=engine_version,
            batch_delta="unclassified",
            rule_id=rule_id,
            evidence_span_ids=evidence_span_ids,
            rationale=rationale,
            recommended_action=recommended_action,
            created_at=utc_now(),
        )

    def _site_id(self, subject_id: str) -> str:
        for sheet_name in ("DM", "SV"):
            rows = self._rows(sheet_name, subject_id)
            if rows:
                return _site_id(rows[0][1].get("SITEID"))
        return ""

    def _assert_project(self, project_id: str) -> None:
        if project_id != MY009_PROJECT_ID:
            raise KeyError(f"MY009 adapter cannot serve project: {project_id}")

    def _assert_subject(self, project_id: str, subject_id: str) -> None:
        self._assert_project(project_id)
        if subject_id not in self._subject_rows_by_id():
            raise KeyError(f"MY009 subject not found: {subject_id}")
