from __future__ import annotations

import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, datetime, timezone
from hashlib import sha1
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional, Tuple

from packages.contracts.workbench_contracts import RiskCase
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
from .monitoring_source_fragment import resolve_listing_fragment, resolve_protocol_fragment
from .monitoring_source_revision import (
    public_monitoring_source_revision,
    read_monitoring_source,
)
from .protocol_text_extractor import ProtocolTextDocument, parse_protocol_docx


MGK10_SAR_PROJECT_ID = "proj_mgk10_sar_real"
MGK10_SAR_BATCH_ID = "mgk10_sar_listing_20260120"
MGK10_SAR_LISTING_LABEL = "MG-K10-SAR-Listing"
STUDY_DRUG_SHEETS = ("EX",)
BACKGROUND_TREATMENT_SHEETS = ("EX1", "EX2", "EX4", "EX5", "EX7")
LAB_SHEETS = ("LB_HEM", "LB_CHEM")
EFFICACY_SHEETS = ("RES1", "RES2", "RES4", "RES5", "RES7", "RES_1", "RES_2", "RES_4", "RES_5", "RES_7", "RQL")

LAB_METRICS = {
    "K10-WBC": ("wbc", "白细胞计数"),
    "K10-NEUT": ("anc", "中性粒细胞计数"),
    "K10-HGB": ("hemoglobin", "血红蛋白"),
    "K10-PLT": ("platelet", "血小板计数"),
    "K10-ALT": ("alt", "丙氨酸转氨酶（ALT）"),
    "K10-AST": ("ast", "天门冬氨酸转氨酶（AST）"),
}

EFFICACY_METRICS = {
    "RTNSSNUM": ("rtnss", "反映性鼻部症状总评分（rTNSS）"),
    "RTOSSNUM": ("rtoss", "反映性眼部症状总评分（rTOSS）"),
    "ITNSSNUM": ("itnss", "瞬时鼻部症状总评分（iTNSS）"),
    "ITOSSNUM": ("itoss", "瞬时眼部症状总评分（iTOSS）"),
    "SCTNUM": ("rqlq", "鼻结膜炎生活质量问卷总评分（RQLQ）"),
}


def _efficacy_fields_for_sheet(sheet: str) -> Tuple[str, ...]:
    if sheet == "RQL":
        return ("SCTNUM",)
    if sheet.startswith("RES_"):
        return ("ITNSSNUM", "ITOSSNUM")
    if sheet.startswith("RES"):
        return ("RTNSSNUM", "RTOSSNUM")
    return ()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _float(value: Any) -> Optional[float]:
    raw = _text(value).replace("＞", "").replace("＜", "").replace(">", "").replace("<", "")
    if raw in {"", ".", "NA", "N/A", "UK", "UNK"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", raw)
    return float(match.group(0)) if match else None


def _date(value: Any) -> Optional[date]:
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
    parsed = _date(raw)
    if parsed:
        return parsed.isoformat(), SubjectTimelineEventDatePrecision.DAY
    month_match = re.match(r"^(\d{4})-(\d{1,2})(?:-|$)", raw)
    if month_match:
        month = int(month_match.group(2))
        if 1 <= month <= 12:
            return f"{month_match.group(1)}-{month:02d}", SubjectTimelineEventDatePrecision.MONTH
    year_match = re.match(r"^(\d{4})", raw)
    if year_match:
        return year_match.group(1), SubjectTimelineEventDatePrecision.YEAR
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


class Mgk10SarMonitoringService:
    """Real-source MG-K10-SAR adapter used to prove cross-project monitoring semantics."""

    def __init__(
        self,
        listing_path: Path,
        protocol_path: Path,
        *,
        listing_label: str = MGK10_SAR_LISTING_LABEL,
        source_batch_id: str = MGK10_SAR_BATCH_ID,
    ):
        self.listing_path = Path(listing_path)
        self.protocol_path = Path(protocol_path)
        self.listing_label = listing_label.strip() or MGK10_SAR_LISTING_LABEL
        self.source_batch_id = source_batch_id.strip() or MGK10_SAR_BATCH_ID
        if any(marker in self.listing_label for marker in ("/", "\\")):
            raise ValueError("listing_label must be a public label, not a path")
        if any(marker in self.source_batch_id for marker in ("/", "\\")):
            raise ValueError("source_batch_id must be a public identifier, not a path")
        self._sheets: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._sheets_revision: Optional[str] = None
        self._subject_rows: Optional[Dict[str, Dict[str, List[Tuple[int, Dict[str, str]]]]]] = None
        self._subject_rows_revision: Optional[str] = None
        self._document: Optional[ProtocolTextDocument] = None
        self._document_revision: Optional[str] = None
        self._sheets_lock = Lock()
        self._subject_rows_lock = Lock()
        self._document_lock = Lock()

    def subject_ids(self) -> List[str]:
        return sorted({_text(row.get("SUBJID")) for _, row in self._rows("DM") if _text(row.get("SUBJID"))})

    def site_ids(self) -> List[str]:
        return sorted({_text(row.get("SITEID")) for _, row in self._rows("DM") if _text(row.get("SITEID"))})

    def listing_row_count(self) -> int:
        return sum(len(rows) for rows in self._sheets_by_name().values())

    def subject_catalog(self, project_id: str) -> Dict[str, Any]:
        self._assert_project(project_id)
        subjects = []
        for row_index, row in self._rows("DM"):
            subject_id = _text(row.get("SUBJID"))
            if not subject_id:
                continue
            site_id = _text(row.get("SITEID")) or "-"
            status = _text(row.get("SUBJSTA")) or "状态未记录"
            subjects.append(
                {
                    "id": subject_id,
                    "site": site_id,
                    "site_name": _text(row.get("SITENM")),
                    "status": status,
                    "profile": f"中心 {site_id} | {status}",
                    "source_locator": self._locator("DM", row_index),
                }
            )
        subjects.sort(key=lambda item: (item["site"], item["id"]))
        return {
            "project_id": project_id,
            "source_batch_id": self.source_batch_id,
            "source_revision": self.source_revision(),
            "generated_at": utc_now().isoformat(),
            "subject_count": len(subjects),
            "subjects": subjects,
        }

    def subject_monitoring(self, project_id: str, subject_id: str) -> SubjectMonitoringDrilldown:
        self._assert_project(project_id)
        if subject_id not in self.subject_ids():
            raise KeyError(f"MG-K10-SAR subject not found: {subject_id}")
        baseline = self._baseline_date(subject_id)
        visits = self._visit_anchors(subject_id, baseline)
        timeline = self._visit_events(project_id, subject_id, baseline)
        timeline.extend(self._history_events(project_id, subject_id, baseline))
        timeline.extend(self._ae_events(project_id, subject_id, baseline))
        timeline.extend(self._cm_events(project_id, subject_id, baseline))
        timeline.extend(self._study_drug_events(project_id, subject_id, baseline))
        timeline.extend(self._background_treatment_events(project_id, subject_id, baseline))
        timeline.extend(self._non_drug_treatment_events(project_id, subject_id, baseline))
        timeline.extend(self._abnormal_lab_events(project_id, subject_id, baseline))
        timeline.extend(self._unscheduled_assessment_events(project_id, subject_id, baseline))
        timeline.extend(self._efficacy_events(project_id, subject_id, baseline))
        timeline.sort(key=lambda item: (item.event_date or "9999-99-99", item.source_domain, item.source_record_id))
        return SubjectMonitoringDrilldown(
            project_id=project_id,
            subject_id=subject_id,
            source_revision=self.source_revision(),
            generated_at=utc_now(),
            subject=self._subject_overview(project_id, subject_id, baseline),
            visit_anchors=visits,
            timeline=timeline,
            efficacy_trends=self._efficacy_trends(subject_id, baseline),
            safety_trends=self._safety_trends(subject_id, baseline),
            domain_availability=self._domain_availability(subject_id),
            risk_prompts=[],
            review_focus=[
                "按真实访视日期查看 AE、MH、非试验用药、试验药物和疗效/安全性变化。",
                "计划外访视、日内重复测量和每条记录自身参考范围均保持独立。",
                "双盲研究仅显示待解盲，不推断治疗组。",
            ],
        )

    def evaluate_subject_risks(self, project_id: str, subject_id: str) -> List[RiskCase]:
        self._assert_project(project_id)
        if subject_id not in self.subject_ids():
            raise KeyError(f"MG-K10-SAR subject not found: {subject_id}")
        return []

    def protocol_rule_registry(self) -> Dict[str, List[Dict[str, Any]]]:
        return {}

    def risk_profile_revision(self) -> str:
        return "mgk10-sar-protocol-v2.1-semantic-profile-v1"

    def risk_engine_version(self) -> str:
        return "mgk10-sar-monitoring-risk-not-enabled"

    def risk_resolution_complete(self) -> bool:
        return False

    def source_revision(self) -> str:
        return public_monitoring_source_revision(
            read_monitoring_source(self.listing_path),
            read_monitoring_source(self.protocol_path),
            self.source_batch_id,
        )

    def resolve_source_fragment(self, locator: str) -> Dict[str, Any]:
        if locator.startswith("listing:"):
            return resolve_listing_fragment(self.listing_label, self._sheets_by_name(), locator)
        if locator.startswith("docx:"):
            return resolve_protocol_fragment(self._doc(), locator)
        raise ValueError("unsupported monitoring source locator")

    def _assert_project(self, project_id: str) -> None:
        if project_id != MGK10_SAR_PROJECT_ID:
            raise ValueError(f"unsupported MG-K10-SAR project: {project_id}")

    def _sheets_by_name(self) -> Dict[str, List[Dict[str, str]]]:
        snapshot = read_monitoring_source(self.listing_path)
        if self._sheets is None or self._sheets_revision != snapshot.cache_key:
            with self._sheets_lock:
                snapshot = read_monitoring_source(self.listing_path)
                if self._sheets is None or self._sheets_revision != snapshot.cache_key:
                    parsed = parse_listing_file(self.listing_path.name, snapshot.content)
                    self._sheets = {sheet.sheet_name: sheet.rows for sheet in parsed}
                    self._sheets_revision = snapshot.cache_key
        return self._sheets

    def _subject_rows_by_sheet(self) -> Dict[str, Dict[str, List[Tuple[int, Dict[str, str]]]]]:
        self._sheets_by_name()
        if self._subject_rows is None or self._subject_rows_revision != self._sheets_revision:
            with self._subject_rows_lock:
                if self._subject_rows is None or self._subject_rows_revision != self._sheets_revision:
                    indexed: Dict[str, Dict[str, List[Tuple[int, Dict[str, str]]]]] = defaultdict(
                        lambda: defaultdict(list)
                    )
                    for sheet_name, rows in self._sheets_by_name().items():
                        for row_index, row in enumerate(rows, start=1):
                            subject_id = _text(row.get("SUBJID"))
                            if subject_id:
                                indexed[sheet_name][subject_id].append((row_index, row))
                    self._subject_rows = {
                        sheet: dict(subjects) for sheet, subjects in indexed.items()
                    }
                    self._subject_rows_revision = self._sheets_revision
        return self._subject_rows

    def _rows(self, sheet_name: str, subject_id: Optional[str] = None) -> List[Tuple[int, Dict[str, str]]]:
        if subject_id is None:
            return [(index, row) for index, row in enumerate(self._sheets_by_name().get(sheet_name, []), start=1)]
        return list(self._subject_rows_by_sheet().get(sheet_name, {}).get(subject_id, []))

    def _doc(self) -> ProtocolTextDocument:
        snapshot = read_monitoring_source(self.protocol_path)
        if self._document is None or self._document_revision != snapshot.cache_key:
            with self._document_lock:
                snapshot = read_monitoring_source(self.protocol_path)
                if self._document is None or self._document_revision != snapshot.cache_key:
                    self._document = parse_protocol_docx(self.protocol_path, snapshot.content)
                    self._document_revision = snapshot.cache_key
        return self._document

    def _locator(self, sheet: str, row_index: int) -> str:
        return f"listing:{self.listing_label}:sheet:{sheet}:row:{row_index}"

    def _baseline_date(self, subject_id: str) -> Optional[date]:
        for _, row in self._rows("SV", subject_id):
            if self._visit_code(_text(row.get("VISIT"))) == "V2D1":
                return _date(row.get("VISDAT"))
        return None

    @staticmethod
    def _study_day(event_date: Optional[date], baseline: Optional[date]) -> Optional[int]:
        if event_date is None or baseline is None:
            return None
        delta = (event_date - baseline).days
        return delta + 1 if delta >= 0 else delta

    @staticmethod
    def _visit_code(label: str) -> str:
        visit_match = re.search(r"V(\d+)", label)
        day_range = re.search(r"D(-?\d+)\s*[~～]\s*D?(-?\d+)", label)
        day_match = re.search(r"D(-?\d+)", label)
        if visit_match and day_range:
            return f"V{visit_match.group(1)}D{day_range.group(1)}~D{day_range.group(2)}"
        if visit_match and day_match:
            return f"V{visit_match.group(1)}D{day_match.group(1)}"
        if "提前退出" in label:
            return "ET"
        if "计划外" in label:
            return "UNS"
        return label or "VISIT"

    @staticmethod
    def _planned_day(label: str) -> Optional[int]:
        match = re.search(r"D(-?\d+)", label)
        return int(match.group(1)) if match else None

    @staticmethod
    def _visit_window(label: str) -> Tuple[Optional[int], Optional[int]]:
        match = re.search(r"±\s*(\d+)\s*d", label, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            return value, value
        range_match = re.search(r"D(-?\d+)\s*[~～]\s*D?(-?\d+)", label)
        if range_match:
            return 0, abs(int(range_match.group(2)) - int(range_match.group(1)))
        return None, None

    def _visit_anchors(self, subject_id: str, baseline: Optional[date]) -> List[SubjectVisitAnchor]:
        anchors = []
        for row_index, row in self._rows("SV", subject_id):
            actual = _date(row.get("VISDAT"))
            label = _text(row.get("VISIT"))
            planned_day = self._planned_day(label)
            before, after = self._visit_window(label)
            actual_day = self._study_day(actual, baseline)
            anchors.append(
                SubjectVisitAnchor(
                    anchor_id=f"mgk10_visit_{subject_id}_{row_index}",
                    visit_code=self._visit_code(label),
                    visit_label=label,
                    planned_study_day=planned_day,
                    window_before_days=before,
                    window_after_days=after,
                    actual_date=actual.isoformat() if actual else None,
                    actual_study_day=actual_day,
                    is_unscheduled="提前退出" in label,
                    deviation_days=(
                        actual_day - planned_day
                        if actual_day is not None and planned_day is not None
                        else None
                    ),
                    source_domain="SV",
                    source_record_id=f"SV:{row_index}",
                    source_locator=self._locator("SV", row_index),
                )
            )
        for row_index, row in self._rows("UNS", subject_id):
            actual = _date(row.get("UNSDAT"))
            anchors.append(
                SubjectVisitAnchor(
                    anchor_id=f"mgk10_uns_{subject_id}_{row_index}",
                    visit_code="UNS",
                    visit_label="计划外访视",
                    actual_date=actual.isoformat() if actual else None,
                    actual_study_day=self._study_day(actual, baseline),
                    is_unscheduled=True,
                    source_domain="UNS",
                    source_record_id=f"UNS:{row_index}",
                    source_locator=self._locator("UNS", row_index),
                )
            )
        return sorted(anchors, key=lambda item: (item.actual_date or "9999-99-99", item.anchor_id))

    def _subject_overview(self, project_id: str, subject_id: str, baseline: Optional[date]) -> SubjectOverview:
        dm_index, dm = self._rows("DM", subject_id)[0]
        visits = self._visit_anchors(subject_id, baseline)
        dated = [item for item in visits if item.actual_date]
        latest = dated[-1] if dated else None
        first_dose = min(
            (
                parsed
                for sheet in STUDY_DRUG_SHEETS
                for _, row in self._rows(sheet, subject_id)
                for parsed in [_date(row.get("EXDAT") or row.get("EXDAT1"))]
                if parsed
            ),
            default=None,
        )
        history_count = sum(
            1 for _, row in self._rows("MH", subject_id) if _text(row.get("MHYN")) == "是"
        )
        ae_count = sum(
            1 for _, row in self._rows("AE", subject_id) if _text(row.get("AEYN")) == "是"
        )
        return SubjectOverview(
            project_id=project_id,
            subject_id=subject_id,
            site_id=_text(dm.get("SITEID")) or "-",
            screening_number=subject_id,
            randomization_number=self._randomization_number(subject_id),
            treatment_arm="待解盲",
            enrollment_status=_text(dm.get("SUBJSTA")) or "状态未记录",
            first_dose_date=first_dose.isoformat() if first_dose else None,
            baseline_visit_date=baseline.isoformat() if baseline else None,
            latest_visit_code=latest.visit_code if latest else "",
            latest_visit_label=latest.visit_label if latest else "",
            latest_visit_date=latest.actual_date if latest else "",
            sex=_text(dm.get("SEX")) or None,
            age_years=_float(dm.get("AGE")),
            blinded=True,
            treatment_arm_masked=True,
            key_medical_context=[
                f"病史 {history_count} 条",
                f"AE {ae_count} 条",
                f"原始来源：{self.listing_label}",
            ],
        )

    def _randomization_number(self, subject_id: str) -> Optional[str]:
        for _, row in self._rows("RAN", subject_id):
            if _text(row.get("RANYN")) == "是" and _text(row.get("RANNUM")):
                return _text(row.get("RANNUM"))
        return None

    def _event(
        self,
        *,
        project_id: str,
        subject_id: str,
        sheet: str,
        row_index: int,
        event_type: SubjectTimelineEventType,
        event_subtype: SubjectTimelineEventSubtype,
        event_date: Optional[str],
        date_precision: SubjectTimelineEventDatePrecision,
        baseline: Optional[date],
        title: str,
        detail: str,
        end_date: Optional[str] = None,
        ongoing: bool = False,
        severity: str = "",
        relationship: str = "",
        outcome: str = "",
        visit_label: str = "",
        result_value: Optional[str] = None,
        is_unscheduled: bool = False,
        clinical_interpretation: str = "",
        raw_event_date: str = "",
        raw_event_end_date: str = "",
    ) -> SubjectTimelineEvent:
        exact_date = _date(event_date)
        exact_end = _date(end_date)
        _, _, earliest, latest, parse_status = _partial_date_bounds(raw_event_date or event_date)
        locator = self._locator(sheet, row_index)
        digest = sha1(f"{project_id}|{subject_id}|{locator}|{event_type.value}".encode()).hexdigest()[:14]
        return SubjectTimelineEvent(
            event_id=f"mgk10_event_{digest}",
            project_id=project_id,
            subject_id=subject_id,
            event_type=event_type,
            event_subtype=event_subtype,
            event_date=event_date,
            event_end_date=end_date,
            raw_event_date=raw_event_date or event_date or "",
            raw_event_end_date=raw_event_end_date or end_date or "",
            earliest_possible_date=earliest,
            latest_possible_date=latest,
            date_parse_status=parse_status,
            study_day=self._study_day(exact_date, baseline),
            end_study_day=self._study_day(exact_end, baseline),
            ongoing=ongoing,
            date_precision=date_precision,
            is_planned=False if is_unscheduled else None,
            is_unscheduled=is_unscheduled,
            visit_code=self._visit_code(visit_label) if visit_label else None,
            visit_label=visit_label,
            source_domain=sheet,
            source_record_id=f"{sheet}:{row_index}",
            source_locator=locator,
            title=title or "原始记录",
            detail=detail,
            result_value=result_value,
            severity=severity,
            relationship=relationship,
            outcome=outcome,
            clinical_interpretation=clinical_interpretation,
        )

    def _visit_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for anchor in self._visit_anchors(subject_id, baseline):
            events.append(
                self._event(
                    project_id=project_id,
                    subject_id=subject_id,
                    sheet=anchor.source_domain,
                    row_index=int(anchor.source_record_id.split(":")[-1]),
                    event_type=SubjectTimelineEventType.VISIT,
                    event_subtype=(
                        SubjectTimelineEventSubtype.UNSCHEDULED_VISIT
                        if anchor.is_unscheduled
                        else SubjectTimelineEventSubtype.PLANNED_VISIT
                    ),
                    event_date=anchor.actual_date,
                    date_precision=SubjectTimelineEventDatePrecision.DAY,
                    baseline=baseline,
                    title=anchor.visit_code,
                    detail=anchor.visit_label,
                    visit_label=anchor.visit_label,
                    is_unscheduled=anchor.is_unscheduled,
                )
            )
        return events

    def _history_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("MH", subject_id):
            if _text(row.get("MHYN")) != "是":
                continue
            start, precision = _partial_date(row.get("MHSTDAT"))
            end, _ = _partial_date(row.get("MHENDAT"))
            events.append(
                self._event(
                    project_id=project_id,
                    subject_id=subject_id,
                    sheet="MH",
                    row_index=row_index,
                    event_type=SubjectTimelineEventType.MEDICAL_HISTORY,
                    event_subtype=SubjectTimelineEventSubtype.HISTORY_CONDITION,
                    event_date=start,
                    date_precision=precision,
                    baseline=baseline,
                    title=_text(row.get("MHTERM")),
                    detail="病史；按原始起止日期展示",
                    end_date=end,
                    ongoing=_text(row.get("MHONGO")) == "是",
                    visit_label=_text(row.get("VISIT")),
                    raw_event_date=_text(row.get("MHSTDAT")),
                    raw_event_end_date=_text(row.get("MHENDAT")),
                )
            )
        return events

    def _ae_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("AE", subject_id):
            if _text(row.get("AEYN")) != "是":
                continue
            start, precision = _partial_date(row.get("AESTDAT"))
            end, _ = _partial_date(row.get("AEENDAT"))
            events.append(
                self._event(
                    project_id=project_id,
                    subject_id=subject_id,
                    sheet="AE",
                    row_index=row_index,
                    event_type=SubjectTimelineEventType.ADVERSE_EVENT,
                    event_subtype=SubjectTimelineEventSubtype.ADVERSE_EVENT,
                    event_date=start,
                    date_precision=precision,
                    baseline=baseline,
                    title=_text(row.get("AETERM")),
                    detail="；".join(
                        item
                        for item in [
                            f"严重程度 {_text(row.get('AESEV'))}",
                            f"与试验药物关系 {_text(row.get('AEREL'))}",
                            f"采取措施 {_text(row.get('AEACN'))}",
                        ]
                        if not item.endswith(" ")
                    ),
                    end_date=end,
                    ongoing=end is None,
                    severity=_text(row.get("AESEV")),
                    relationship=_text(row.get("AEREL")),
                    outcome=_text(row.get("AEOUT")),
                    visit_label=_text(row.get("VISIT")),
                    raw_event_date=_text(row.get("AESTDAT")),
                    raw_event_end_date=_text(row.get("AEENDAT")),
                )
            )
        return events

    def _cm_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("CM", subject_id):
            if _text(row.get("CMYN")) != "是":
                continue
            start, precision = _partial_date(row.get("CMSTDAT"))
            end, _ = _partial_date(row.get("CMENDAT"))
            dose = " ".join(
                item
                for item in [
                    _text(row.get("CMDOSE")),
                    _text(row.get("CMDOSU") or row.get("CMDOSUO")),
                    _text(row.get("CMDOSFRQ")),
                    _text(row.get("CMROUTE")),
                ]
                if item
            )
            events.append(
                self._event(
                    project_id=project_id,
                    subject_id=subject_id,
                    sheet="CM",
                    row_index=row_index,
                    event_type=SubjectTimelineEventType.CONCOMITANT_MEDICATION,
                    event_subtype=SubjectTimelineEventSubtype.NON_STUDY_MEDICATION,
                    event_date=start,
                    date_precision=precision,
                    baseline=baseline,
                    title=_text(row.get("CMTRT")),
                    detail=f"非试验用药；适应证 {_text(row.get('CMINDC'))}；{dose}".strip("；"),
                    end_date=end,
                    ongoing=_text(row.get("CMONGO")) == "是",
                    visit_label=_text(row.get("VISIT")),
                    raw_event_date=_text(row.get("CMSTDAT")),
                    raw_event_end_date=_text(row.get("CMENDAT")),
                )
            )
        return events

    def _study_drug_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for sheet in STUDY_DRUG_SHEETS:
            for row_index, row in self._rows(sheet, subject_id):
                date_value = row.get("EXDAT")
                event_date, precision = _partial_date(date_value)
                if not event_date:
                    continue
                administered = _text(row.get("EXYN"))
                dose = _text(row.get("EXDOSE") or row.get("EXDOSEO"))
                events.append(
                    self._event(
                        project_id=project_id,
                        subject_id=subject_id,
                        sheet=sheet,
                        row_index=row_index,
                        event_type=SubjectTimelineEventType.STUDY_DRUG_ADMINISTRATION,
                        event_subtype=SubjectTimelineEventSubtype.STUDY_DRUG_ADMINISTRATION,
                        event_date=event_date,
                        date_precision=precision,
                        baseline=baseline,
                        title="盲态试验药物/安慰剂给药",
                        detail=f"{_text(row.get('VISIT'))}；是否给药 {administered or '未记录'}；体积 {dose or '未记录'}；不推断治疗组",
                        visit_label=_text(row.get("VISIT")),
                        result_value=dose or administered,
                        raw_event_date=_text(date_value),
                    )
                )
        return events

    def _background_treatment_events(
        self,
        project_id: str,
        subject_id: str,
        baseline: Optional[date],
    ) -> List[SubjectTimelineEvent]:
        events = []
        for sheet in BACKGROUND_TREATMENT_SHEETS:
            for row_index, row in self._rows(sheet, subject_id):
                administered = _text(row.get("EXYN1"))
                if administered == "不适用":
                    continue
                raw_date = _text(row.get("EXDAT1"))
                event_date, precision = _partial_date(raw_date)
                if not event_date:
                    continue
                timepoint = _text(
                    row.get("EXTPT1")
                    or row.get("EXTPT2")
                    or row.get("EXTPT4")
                    or row.get("EXTPT5")
                    or row.get("EXTPT7")
                )
                dose = _text(row.get("EXDOSE1") or row.get("EXDOSEO1"))
                events.append(
                    self._event(
                        project_id=project_id,
                        subject_id=subject_id,
                        sheet=sheet,
                        row_index=row_index,
                        event_type=SubjectTimelineEventType.BACKGROUND_TREATMENT,
                        event_subtype=SubjectTimelineEventSubtype.PROTOCOL_BACKGROUND_TREATMENT,
                        event_date=event_date,
                        date_precision=precision,
                        baseline=baseline,
                        title="方案规定背景治疗",
                        detail=f"糠酸莫米松鼻喷雾剂；{timepoint or _text(row.get('VISIT'))}；是否用药 {administered or '未记录'}；剂量 {dose or '未记录'}",
                        visit_label=_text(row.get("VISIT")),
                        result_value=dose or administered,
                        raw_event_date=raw_date,
                    )
                )
        return events

    def _non_drug_treatment_events(
        self,
        project_id: str,
        subject_id: str,
        baseline: Optional[date],
    ) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("PR", subject_id):
            if _text(row.get("PRYN")) != "是":
                continue
            start, precision = _partial_date(row.get("PRSTDAT"))
            end, _ = _partial_date(row.get("PRENDAT"))
            events.append(
                self._event(
                    project_id=project_id,
                    subject_id=subject_id,
                    sheet="PR",
                    row_index=row_index,
                    event_type=SubjectTimelineEventType.NON_DRUG_TREATMENT,
                    event_subtype=SubjectTimelineEventSubtype.NON_DRUG_TREATMENT,
                    event_date=start,
                    date_precision=precision,
                    baseline=baseline,
                    title=_text(row.get("PRTRT")),
                    detail=f"非药物治疗；适应证 {_text(row.get('PRINDC'))}",
                    end_date=end,
                    ongoing=_text(row.get("PRONGO")) == "是",
                    visit_label=_text(row.get("VISIT")),
                    raw_event_date=_text(row.get("PRSTDAT")),
                    raw_event_end_date=_text(row.get("PRENDAT")),
                )
            )
        return events

    def _abnormal_lab_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for sheet in LAB_SHEETS:
            for row_index, row in self._rows(sheet, subject_id):
                assessment = _text(row.get("临床评估"))
                if "异常" not in assessment:
                    continue
                event_date, precision = _partial_date(row.get("LBDAT"))
                result = _text(row.get("结果"))
                unit = _text(row.get("单位"))
                low = _text(row.get("下限"))
                high = _text(row.get("上限"))
                events.append(
                    self._event(
                        project_id=project_id,
                        subject_id=subject_id,
                        sheet=sheet,
                        row_index=row_index,
                        event_type=SubjectTimelineEventType.LAB,
                        event_subtype=SubjectTimelineEventSubtype.LAB_RESULT,
                        event_date=event_date,
                        date_precision=precision,
                        baseline=baseline,
                        title=_text(row.get("实验室指标名称")),
                        detail=f"{result}{f' {unit}' if unit else ''}，参考范围 [{low}, {high}]，{assessment}",
                        visit_label=_text(row.get("VISIT")),
                        result_value=f"{result}{unit}",
                        clinical_interpretation=assessment,
                        raw_event_date=_text(row.get("LBDAT")),
                    )
                )
        return events

    def _unscheduled_assessment_events(
        self,
        project_id: str,
        subject_id: str,
        baseline: Optional[date],
    ) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows("USV", subject_id):
            event_date, precision = _partial_date(row.get("USVDAT"))
            if not event_date:
                continue
            test_name = _text(row.get("USVTEST")) or "计划外检查"
            result = _text(row.get("USVORRES"))
            unit = _text(row.get("USVORESU"))
            low = _text(row.get("USVORNRL"))
            high = _text(row.get("USVORNRH"))
            assessment = _text(row.get("USVCLSIG"))
            attribution = _text(row.get("USVABCS"))
            linked_record = _text(row.get("USVMHNO")) or _text(row.get("USVAENO"))
            other_attribution = _text(row.get("USVABCSO"))
            reference = ""
            if low or high:
                reference = f"参考范围 [{low or '-'}, {high or '-'}]"
            interpretation = "；".join(
                item
                for item in [assessment, attribution, linked_record, other_attribution]
                if item
            )
            detail = "，".join(
                item
                for item in [
                    f"{result}{f' {unit}' if unit else ''}" if result else "结果未记录",
                    reference,
                    interpretation,
                ]
                if item
            )
            events.append(
                self._event(
                    project_id=project_id,
                    subject_id=subject_id,
                    sheet="USV",
                    row_index=row_index,
                    event_type=SubjectTimelineEventType.LAB,
                    event_subtype=SubjectTimelineEventSubtype.LAB_RESULT,
                    event_date=event_date,
                    date_precision=precision,
                    baseline=baseline,
                    title=f"计划外检查：{test_name}",
                    detail=detail,
                    visit_label=_text(row.get("VISIT")) or "计划外访视",
                    result_value=f"{result}{f' {unit}' if unit else ''}".strip(),
                    is_unscheduled=True,
                    clinical_interpretation=interpretation,
                    raw_event_date=_text(row.get("USVDAT")),
                )
            )
        return events

    def _efficacy_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for sheet in EFFICACY_SHEETS:
            for row_index, row in self._rows(sheet, subject_id):
                date_key = "RQLDAT" if sheet == "RQL" else "RESDAT"
                event_date, precision = _partial_date(row.get(date_key))
                if not event_date:
                    continue
                available = [
                    (field, spec, _float(row.get(field)))
                    for field in _efficacy_fields_for_sheet(sheet)
                    for spec in [EFFICACY_METRICS[field]]
                    if _float(row.get(field)) is not None
                ]
                if not available:
                    continue
                result_text = "；".join(
                    f"{label} {value:g}分"
                    for _, (_, label), value in available
                )
                events.append(
                    self._event(
                        project_id=project_id,
                        subject_id=subject_id,
                        sheet=sheet,
                        row_index=row_index,
                        event_type=SubjectTimelineEventType.EFFICACY_SCORE,
                        event_subtype=SubjectTimelineEventSubtype.EFFICACY_ASSESSMENT,
                        event_date=event_date,
                        date_precision=precision,
                        baseline=baseline,
                        title="疗效量表评估",
                        detail=f"{_text(row.get('VISIT'))}；{result_text}",
                        visit_label=_text(row.get("VISIT")),
                        result_value=result_text,
                        raw_event_date=_text(row.get(date_key)),
                    )
                )
        return events

    def _efficacy_trends(self, subject_id: str, baseline: Optional[date]) -> List[SubjectTrendMetric]:
        grouped: Dict[str, List[Tuple[str, str, str, int, Dict[str, str], str, float]]] = defaultdict(list)
        for sheet in EFFICACY_SHEETS:
            for row_index, row in self._rows(sheet, subject_id):
                date_key = "RQLDAT" if sheet == "RQL" else "RESDAT"
                assessed = _date(row.get(date_key))
                if not assessed:
                    continue
                assessment_time = _text(row.get("RESTIM"))
                for field in _efficacy_fields_for_sheet(sheet):
                    metric_key, _ = EFFICACY_METRICS[field]
                    value = _float(row.get(field))
                    if value is not None:
                        grouped[metric_key].append(
                            (assessed.isoformat(), assessment_time, sheet, row_index, row, field, value)
                        )
        metrics = []
        for field, (metric_key, label) in EFFICACY_METRICS.items():
            rows = sorted(grouped.get(metric_key, []), key=lambda item: (item[0], item[1], item[3]))
            if not rows:
                continue
            expected_count = 7 if metric_key in {"rtnss", "rtoss"} else 4 if metric_key in {"itnss", "itoss"} else 1
            pre_count = expected_count - 1
            pre_rows = [item for item in rows if baseline is not None and _date(item[0]) < baseline]
            d1_rows = [item for item in rows if baseline is not None and _date(item[0]) == baseline]
            baseline_rows = (
                [*pre_rows[-pre_count:], *d1_rows[:1]]
                if expected_count > 1
                else d1_rows[:1]
            )
            observed_count = len(baseline_rows)
            missing_count = max(expected_count - observed_count, 0)
            baseline_value = (
                sum(item[6] for item in baseline_rows) / observed_count
                if baseline_rows and missing_count <= 1
                else None
            )
            baseline_locators = [self._locator(item[2], item[3]) for item in baseline_rows]
            baseline_locator = baseline_locators[0] if baseline_locators else ""
            if expected_count == 7:
                baseline_rule = "导入期最后6个时间点与D1首个时间点的均值；最多允许缺失1个，不填补"
            elif expected_count == 4:
                baseline_rule = "导入期最后3个时间点与D1首个时间点的均值；最多允许缺失1个，不填补"
            else:
                baseline_rule = "V2（D1）首个可用记录"
            if baseline_value is None:
                baseline_rule = f"{baseline_rule}；有效组成点不足，未生成基线"
            points = []
            for sequence, (
                assessment_date,
                assessment_time,
                sheet,
                row_index,
                row,
                source_field,
                value,
            ) in enumerate(rows, start=1):
                visit_label = _text(row.get("VISIT"))
                locator = self._locator(sheet, row_index)
                change = value - baseline_value if baseline_value is not None else None
                points.append(
                    SubjectTrendPoint(
                        point_id=f"mgk10_{metric_key}_{subject_id}_{sheet}_{row_index}",
                        visit_code=self._visit_code(visit_label),
                        visit_label=visit_label,
                        assessment_date=assessment_date,
                        study_day=self._study_day(_date(assessment_date), baseline),
                        value=value,
                        original_value=_text(row.get(source_field)),
                        standardized_value=value,
                        baseline_value=baseline_value,
                        is_baseline=locator in baseline_locators,
                        baseline_rule=baseline_rule,
                        baseline_source_locator=baseline_locator,
                        baseline_component_source_locators=baseline_locators,
                        baseline_expected_count=expected_count,
                        baseline_observed_count=observed_count,
                        baseline_missing_count=missing_count,
                        change_from_baseline=change,
                        percent_change_from_baseline=(
                            change / baseline_value * 100
                            if change is not None and baseline_value not in {None, 0}
                            else None
                        ),
                        assessment_sequence=sequence,
                        source_domain=sheet,
                        source_record_id=f"{sheet}:{row_index}",
                        source_locator=locator,
                        note=f"原始字段 {source_field}" + (f"；时间 {assessment_time}" if assessment_time else ""),
                    )
                )
            metrics.append(
                SubjectTrendMetric(
                    metric_key=metric_key,
                    metric_label=label,
                    domain=SubjectTrendDomain.EFFICACY,
                    unit="分",
                    direction=SubjectTrendDirection.LOWER_IS_BETTER,
                    points=points,
                )
            )
        return metrics

    def _safety_trends(self, subject_id: str, baseline: Optional[date]) -> List[SubjectTrendMetric]:
        grouped: Dict[str, List[Tuple[str, str, int, Dict[str, str], float]]] = defaultdict(list)
        for sheet in LAB_SHEETS:
            for row_index, row in self._rows(sheet, subject_id):
                code = _text(row.get("实验室指标编号")).upper()
                assessed = _date(row.get("LBDAT"))
                value = _float(row.get("结果"))
                if not code or not assessed or value is None:
                    continue
                grouped[code].append((assessed.isoformat(), sheet, row_index, row, value))
        candidates = []
        for code, raw_rows in grouped.items():
            rows = sorted(raw_rows, key=lambda item: (item[0], item[2]))
            metric_key, configured_label = LAB_METRICS.get(
                code,
                (
                    f"lab_{re.sub(r'[^a-z0-9]+', '_', code.lower()).strip('_')}",
                    "",
                ),
            )
            label = configured_label or _text(rows[0][3].get("实验室指标名称")) or code
            baseline_row = next(
                (
                    item
                    for item in rows
                    if self._visit_code(_text(item[3].get("VISIT"))) == "V2D1"
                ),
                None,
            )
            baseline_value = baseline_row[4] if baseline_row else None
            baseline_locator = self._locator(baseline_row[1], baseline_row[2]) if baseline_row else ""
            points = []
            abnormal_count = 0
            clinically_significant_count = 0
            for sequence, (assessment_date, sheet, row_index, row, value) in enumerate(rows, start=1):
                visit_label = _text(row.get("VISIT"))
                locator = self._locator(sheet, row_index)
                low = _float(row.get("下限"))
                high = _float(row.get("上限"))
                assessment = _text(row.get("临床评估"))
                abnormal = "异常" in assessment or (low is not None and value < low) or (high is not None and value > high)
                abnormal_count += int(abnormal)
                clinically_significant_count += int("异常有临床意义" in assessment)
                direction = "low" if low is not None and value < low else "high" if high is not None and value > high else ""
                change = value - baseline_value if baseline_value is not None else None
                points.append(
                    SubjectTrendPoint(
                        point_id=f"mgk10_{metric_key}_{subject_id}_{sheet}_{row_index}",
                        visit_code=self._visit_code(visit_label),
                        visit_label=visit_label,
                        assessment_date=assessment_date,
                        study_day=self._study_day(_date(assessment_date), baseline),
                        value=value,
                        original_value=_text(row.get("结果")),
                        standardized_value=value,
                        unit=_text(row.get("单位")),
                        baseline_value=baseline_value,
                        is_baseline=locator == baseline_locator,
                        baseline_rule="V2（D1）同指标首条记录" if baseline_row else "未发现 D1 基线，不替代",
                        baseline_source_locator=baseline_locator,
                        change_from_baseline=change,
                        percent_change_from_baseline=(
                            change / baseline_value * 100
                            if change is not None and baseline_value not in {None, 0}
                            else None
                        ),
                        reference_low=low,
                        reference_high=high,
                        reference_range_text=f"[{_text(row.get('下限'))}, {_text(row.get('上限'))}] {_text(row.get('单位'))}".strip(),
                        reference_range_source=_text(row.get("实验室范围名称")),
                        normality="abnormal" if abnormal else "normal",
                        abnormal_direction=direction,
                        clinical_significance=assessment,
                        assessment_sequence=sequence,
                        is_unscheduled="计划外" in visit_label,
                        risk_flag=abnormal,
                        source_domain=sheet,
                        source_record_id=f"{sheet}:{row_index}",
                        source_locator=locator,
                        note=_text(row.get("备注")),
                    )
                )
            candidates.append(
                (
                    SubjectTrendMetric(
                        metric_key=metric_key,
                        metric_label=label,
                        domain=SubjectTrendDomain.SAFETY,
                        unit=_text(rows[0][3].get("单位")),
                        direction=SubjectTrendDirection.STABLE_RANGE,
                        points=points,
                    ),
                    code in LAB_METRICS,
                    abnormal_count,
                    clinically_significant_count,
                )
            )

        core_codes = {code for code in LAB_METRICS if code in grouped}
        selected_codes = set(core_codes)
        ranked_abnormal_extras = sorted(
            (
                item
                for item in candidates
                if not item[1] and item[2] > 0
            ),
            key=lambda item: (-item[3], -item[2], -len(item[0].points), item[0].metric_label),
        )
        remaining_slots = max(10 - len(selected_codes), 0)
        selected_metric_keys = {
            metric.metric_key
            for metric, _, _, _ in candidates
            if metric.metric_key in {LAB_METRICS[code][0] for code in selected_codes}
        }
        selected_metric_keys.update(item[0].metric_key for item in ranked_abnormal_extras[:remaining_slots])
        selected = [
            item
            for item in candidates
            if item[0].metric_key in selected_metric_keys
        ]
        selected.sort(
            key=lambda item: (
                -item[3],
                -item[2],
                not item[1],
                item[0].metric_label,
            )
        )
        return [item[0] for item in selected]

    def _domain_availability(self, subject_id: str) -> List[SubjectDomainAvailability]:
        definitions: Iterable[Tuple[str, str, Tuple[str, ...]]] = (
            ("visit", "访视", ("SV", "UNS")),
            ("adverse_event", "AE", ("AE",)),
            ("medical_history", "病史", ("MH",)),
            ("concomitant_medication", "非试验用药", ("CM",)),
            ("study_drug", "试验药物", STUDY_DRUG_SHEETS),
            ("background_treatment", "方案背景治疗", BACKGROUND_TREATMENT_SHEETS),
            ("non_drug_treatment", "非药物治疗", ("PR",)),
            ("laboratory", "实验室检查", (*LAB_SHEETS, "USV")),
            ("efficacy", "疗效评估", EFFICACY_SHEETS),
        )
        availability = []
        for domain, label, sheets in definitions:
            first = next(
                (
                    (sheet, rows[0][0])
                    for sheet in sheets
                    for rows in [self._rows(sheet, subject_id)]
                    if rows
                ),
                None,
            )
            availability.append(
                SubjectDomainAvailability(
                    domain=domain,
                    label=label,
                    status=(
                        SubjectDomainAvailabilityStatus.AVAILABLE
                        if first
                        else SubjectDomainAvailabilityStatus.ABSENT
                    ),
                    detail="原始 listing 中存在记录" if first else "原始 listing 中未发现该受试者记录",
                    source_locator=self._locator(first[0], first[1]) if first else "",
                )
            )
        return availability
