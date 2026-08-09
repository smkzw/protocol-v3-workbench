from __future__ import annotations

import re
from datetime import date, datetime, timezone
from hashlib import sha1
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from packages.contracts.workbench_contracts import RiskCase, RiskSeverity, RiskStatus
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


LBCHEM_SHEET = "LBCHEM--实验室检查-血生化"
LBHEMA_SHEET = "LBHEMA--实验室检查-血常规"
BSA_SHEET = "BSA--受累体表面积（BSA）"
IGA_SHEET = "IGA--研究者整体评分（IGA）"
EASI_SHEET = "EASI--湿疹面积及严重程度指数评分（EASI）"
SCORAD_SHEET = "SR--特应性皮炎评分（SCORAD）-最后分值"
ECB_SHEET = "ECB--研究药物给药-医嘱用药"
CM_SHEET = "CM--既往及合并用药治疗"
AE_SHEET = "AE--不良事件"
SUBJ_SHEET = "SUBJ--受试者页"
SV_SHEET = "SV--访视日期"
RUX_BATCH_ID = "rux_03_002_listing_20250612"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _float(value: Any) -> Optional[float]:
    text = _text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_date(value: Any) -> Optional[date]:
    text = _text(value)
    if len(text) < 10:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


class RuxMonitoringService:
    """RUX-03-002 real-source monitoring derivation service.

    This service is intentionally additive. It does not mutate original files and
    does not reuse the SAR/demo monitoring rule engine as if it were RUX-ready.
    """

    def __init__(
        self,
        listing_path: Path,
        protocol_path: Path,
        source_batch_id: str = RUX_BATCH_ID,
    ):
        self.listing_path = Path(listing_path)
        self.protocol_path = Path(protocol_path)
        self.source_batch_id = source_batch_id.strip() or RUX_BATCH_ID
        if "/" in self.source_batch_id or "\\" in self.source_batch_id:
            raise ValueError("source_batch_id must be a public business identifier, not a path")
        self._sheets: Optional[Dict[str, List[Dict[str, str]]]] = None
        self._sheets_revision: Optional[str] = None
        self._document: Optional[ProtocolTextDocument] = None
        self._document_revision: Optional[str] = None
        self._sheets_lock = Lock()
        self._document_lock = Lock()

    def protocol_rule_registry(self) -> Dict[str, List[Dict[str, str]]]:
        table4 = self._doc().tables[4]
        table7 = self._doc().tables[7]
        return {
            "table4": [
                {
                    "rule_id": "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT",
                    "source_locator": "docx:table:4:row:2",
                    "trigger": self._table_row_first_cell(table4.table_index, 2),
                    "action": self._table_row_action(table4.table_index, 2),
                },
                {
                    "rule_id": "RUX-LAB-ANC-LT1_5-INTERRUPT",
                    "source_locator": "docx:table:4:row:4",
                    "trigger": self._table_row_first_cell(table4.table_index, 4),
                    "action": self._table_row_action(table4.table_index, 4),
                },
                {
                    "rule_id": "RUX-LAB-OTHER-GRADE3-INTERRUPT",
                    "source_locator": "docx:table:4:row:6",
                    "trigger": self._table_row_first_cell(table4.table_index, 6),
                    "action": self._table_row_action(table4.table_index, 6),
                },
                {
                    "rule_id": "RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE",
                    "source_locator": "docx:table:4:row:7",
                    "trigger": self._table_row_first_cell(table4.table_index, 7),
                    "action": self._table_row_action(table4.table_index, 7),
                },
            ],
            "table7": [
                {
                    "rule_id": "RUX-ICE-ALLOWED-CONMED-TREATMENT-POLICY",
                    "source_locator": "docx:table:7:row:1",
                    "trigger": self._table_row_first_cell(table7.table_index, 1),
                    "action": self._table_row_action(table7.table_index, 1),
                },
                {
                    "rule_id": "RUX-ICE-PROHIBITED-CONMED-NONRESPONSE",
                    "source_locator": "docx:table:7:row:2",
                    "trigger": self._table_row_first_cell(table7.table_index, 2),
                    "action": self._table_row_action(table7.table_index, 2),
                },
                {
                    "rule_id": "RUX-ICE-POOR-EFFICACY-DISCONTINUATION-NONRESPONSE",
                    "source_locator": "docx:table:7:row:3",
                    "trigger": self._table_row_first_cell(table7.table_index, 3),
                    "action": self._table_row_action(table7.table_index, 3),
                },
                {
                    "rule_id": "RUX-ICE-NON_EFFICACY-DISCONTINUATION-MI",
                    "source_locator": "docx:table:7:row:4",
                    "trigger": self._table_row_first_cell(table7.table_index, 4),
                    "action": self._table_row_action(table7.table_index, 4),
                },
            ],
        }

    def evaluate_subject_risks(self, project_id: str, subject_id: str) -> List[RiskCase]:
        risks: List[RiskCase] = []
        risks.extend(self._lab_risks(project_id, subject_id))
        risks.extend(self._bsa_risks(project_id, subject_id))
        return risks

    def subject_ids(self) -> List[str]:
        return sorted(
            {_text(row.get("SUBJID")) for _, row in self._rows(SUBJ_SHEET) if _text(row.get("SUBJID"))}
        )

    def subject_catalog(self, project_id: str) -> Dict[str, Any]:
        subjects: List[Dict[str, Any]] = []
        for row_index, row in self._rows(SUBJ_SHEET):
            subject_id = _text(row.get("SUBJID"))
            if not subject_id:
                continue
            site_id = _text(row.get("SITEID")) or "-"
            site_name = _text(row.get("SITENM"))
            status = _text(row.get("SUBJSTA")) or "状态未记录"
            screening_number = _text(row.get("SCRNUM"))
            profile_parts = [f"中心 {site_id}"]
            if site_name:
                profile_parts.append(site_name)
            if screening_number:
                profile_parts.append(f"筛选号 {screening_number}")
            profile_parts.append(status)
            subjects.append(
                {
                    "id": subject_id,
                    "site": site_id,
                    "site_name": site_name,
                    "status": status,
                    "screening_number": screening_number,
                    "profile": " | ".join(profile_parts),
                    "source_locator": self._source_locator(SUBJ_SHEET, row_index),
                }
            )

        subjects.sort(key=lambda item: (str(item["site"]), str(item["id"])))
        return {
            "project_id": project_id,
            "source_batch_id": self.source_batch_id,
            "source_revision": self.source_revision(),
            "generated_at": utc_now().isoformat(),
            "subject_count": len(subjects),
            "subjects": subjects,
        }

    def site_ids(self) -> List[str]:
        return sorted(
            {_text(row.get("SITEID")) for _, row in self._rows(SUBJ_SHEET) if _text(row.get("SITEID"))}
        )

    def listing_row_count(self) -> int:
        return sum(len(rows) for rows in self._sheets_by_name().values())

    def subject_monitoring(self, project_id: str, subject_id: str) -> SubjectMonitoringDrilldown:
        baseline = self._baseline_date(subject_id)
        timeline = self._visit_events(project_id, subject_id, baseline)
        timeline.extend(self._anc_lab_events(project_id, subject_id, baseline))
        timeline.extend(self._chem_lab_events(project_id, subject_id, baseline))
        timeline.extend(self._bsa_efficacy_events(project_id, subject_id, baseline))
        timeline.extend(self._ae_events(project_id, subject_id, baseline))
        timeline.extend(self._cm_events(project_id, subject_id, baseline))
        timeline.extend(self._ecb_events(project_id, subject_id, baseline))
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
        timeline.sort(key=lambda item: (item.event_date or "9999-99-99", item.source_record_id))

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
                "ANC降低与AE、给药暂停/重启需连续复核。",
                "CM仅指非试验用合并用药；试验药物暂停、恢复和剂量调整必须走独立试验药物变更链路。",
                "所有事件均需保留 listing row locator；AI解释不能替代原始证据。",
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
        return self._sheets

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
                self.listing_path.name,
                self._sheets_by_name(),
                locator,
            )
        raise ValueError("unsupported monitoring source locator")

    def risk_profile_revision(self) -> str:
        return "rux-protocol-v1.3-rules-v1"

    def risk_engine_version(self) -> str:
        return "rux-monitoring-risk-v0.5"

    def risk_resolution_complete(self) -> bool:
        # This adapter currently binds one manually exported listing plus protocol.
        return False

    def _table_row_first_cell(self, table_index: int, row_index: int) -> str:
        row = self._doc().tables[table_index].rows[row_index]
        return row[0].text if row else ""

    def _table_row_action(self, table_index: int, row_index: int) -> str:
        row = self._doc().tables[table_index].rows[row_index]
        if len(row) <= 1:
            return ""
        return "；".join(_text(cell.text).replace("\n", "；") for cell in row[1:] if _text(cell.text))

    def _rows(self, sheet_name: str, subject_id: str | None = None) -> List[Tuple[int, Dict[str, str]]]:
        rows = self._sheets_by_name().get(sheet_name, [])
        indexed = [(index + 1, row) for index, row in enumerate(rows)]
        if subject_id is None:
            return indexed
        return [(index, row) for index, row in indexed if _text(row.get("SUBJID")) == subject_id]

    def _source_locator(self, sheet_name: str, row_index: int) -> str:
        return f"listing:{self.listing_path.name}:sheet:{sheet_name}:row:{row_index}"

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
        severity: RiskSeverity = RiskSeverity.HIGH,
        safety_pv_flag: bool = False,
    ) -> RiskCase:
        source_revision = self.source_revision()
        rule_profile_revision = self.risk_profile_revision()
        engine_version = self.risk_engine_version()
        stable_hash = sha1(f"{project_id}|subject|{subject_id}|{rule_id}".encode("utf-8")).hexdigest()[:16]
        instance_hash = sha1(
            (
                f"{stable_hash}|{self.source_batch_id}|{source_revision}|"
                f"{rule_profile_revision}|{engine_version}|{'|'.join(evidence_span_ids)}"
            ).encode("utf-8")
        ).hexdigest()[:16]
        risk_hash = sha1(f"{project_id}|{subject_id}|{rule_id}|{'|'.join(evidence_span_ids)}".encode("utf-8")).hexdigest()[:10]
        return RiskCase(
            risk_id=f"rux_risk_{risk_hash}",
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
                    *(("safety_pv",) if safety_pv_flag else ()),
                }
            ),
            title=title,
            subject_id=subject_id,
            site_id=self._site_id(subject_id),
            scope_type="subject",
            scope_id=subject_id,
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

    def _lab_risks(self, project_id: str, subject_id: str) -> List[RiskCase]:
        risks: List[RiskCase] = []
        alt_gt3_refs: List[str] = []
        alt_gt5_refs: List[str] = []
        for row_index, row in self._rows(LBCHEM_SHEET, subject_id):
            test = _text(row.get("LBTEST"))
            value = _float(row.get("LBORRES"))
            uln = _float(row.get("LBORNRHI"))
            if not value or not uln or uln <= 0:
                continue
            if "丙氨酸氨基转移酶" not in test and "ALT" not in test and "AST" not in test:
                continue
            ratio = value / uln
            locator = self._source_locator(LBCHEM_SHEET, row_index)
            if ratio > 3:
                alt_gt3_refs.append(locator)
            if ratio > 5:
                alt_gt5_refs.append(locator)
        if alt_gt3_refs:
            risks.append(
                self._risk(
                    project_id,
                    subject_id,
                    "实验室安全 / 肝功能中断规则",
                    "laboratory_abnormality",
                    "LB",
                    f"{subject_id} ALT/AST >3xULN，需中断用药复核",
                    "RUX-LAB-ALT-AST-GT3ULN-INTERRUPT",
                    [*alt_gt3_refs, "docx:table:4:row:2"],
                    "RUX listing 显示 ALT/AST 超过 3xULN，方案表4要求尽可能48小时内复测并中断研究药物。",
                    "核对复测、AE记录、给药调整和研究者说明；医学确认后决定是否可恢复。",
                    safety_pv_flag=True,
                )
            )
        if alt_gt5_refs:
            risks.append(
                self._risk(
                    project_id,
                    subject_id,
                    "实验室安全 / 肝功能停药规则",
                    "laboratory_abnormality",
                    "LB",
                    f"{subject_id} ALT/AST >5xULN，需停药复核",
                    "RUX-LAB-AST-ALT-GT5ULN-DISCONTINUE",
                    [*alt_gt5_refs, "docx:table:4:row:7"],
                    "RUX listing 显示 ALT/AST 超过 5xULN，方案表4要求确认异常后停用研究药物。",
                    "核对复测结果、AE记录、DSEOT/ECB给药状态；医学确认是否已按方案停药。",
                    safety_pv_flag=True,
                )
            )

        anc_refs = []
        for row_index, row in self._rows(LBHEMA_SHEET, subject_id):
            test = _text(row.get("LBTEST"))
            value = _float(row.get("LBORRES"))
            if value is None:
                continue
            if "中性粒细胞计数" in test and value < 1.5:
                anc_refs.append(self._source_locator(LBHEMA_SHEET, row_index))
        if anc_refs:
            risks.append(
                self._risk(
                    project_id,
                    subject_id,
                    "实验室安全 / ANC中断规则",
                    "laboratory_abnormality",
                    "LB",
                    f"{subject_id} ANC <1.5x10^9/L，需中断用药复核",
                    "RUX-LAB-ANC-LT1_5-INTERRUPT",
                    [*anc_refs, "docx:table:4:row:4"],
                    "RUX listing 显示中性粒细胞计数低于 1.5x10^9/L，方案表4要求尽可能48小时内复测并中断研究药物。",
                    "核对血常规复测、AE条目和ECB暂停/重启记录；医学确认是否闭环。",
                    safety_pv_flag=True,
                )
            )
        return risks

    def _bsa_risks(self, project_id: str, subject_id: str) -> List[RiskCase]:
        refs = []
        for row_index, row in self._rows(BSA_SHEET, subject_id):
            value = _float(row.get("BSARESS"))
            if value is not None and value > 20:
                refs.append(self._source_locator(BSA_SHEET, row_index))
        if not refs:
            return []
        return [
            self._risk(
                project_id,
                subject_id,
                "BSA治疗面积 >20% 停药复核",
                "other_medical_review",
                "FA",
                f"{subject_id} 治疗期BSA超过20%，需停药/计划外访视复核",
                "RUX-BSA-TOTAL-GT20-STOP-REVIEW",
                [*refs, "docx:paragraph:748", "docx:paragraph:883"],
                "RUX BSA listing 显示治疗期总BSA超过20%，方案要求必须停止使用研究药物。",
                "请医学确认疾病BSA与治疗总面积解释是否一致，并核对UNS/ECB/DSEOT记录。",
            )
        ]

    def _subject_overview(self, project_id: str, subject_id: str, baseline: Optional[date]) -> SubjectOverview:
        subject_row = next((row for _, row in self._rows(SUBJ_SHEET, subject_id)), {})
        visits = self._rows(SV_SHEET, subject_id)
        latest_visit = visits[-1][1] if visits else {}
        return SubjectOverview(
            project_id=project_id,
            subject_id=subject_id,
            site_id=_text(subject_row.get("SITEID")) or self._site_id(subject_id) or "",
            screening_number=_text(subject_row.get("SCRNUM")) or subject_id,
            randomization_number=None,
            treatment_arm="待解盲",
            enrollment_status=_text(subject_row.get("SUBJSTA")) or "unknown",
            first_dose_date=baseline.isoformat() if baseline else None,
            baseline_visit_date=baseline.isoformat() if baseline else None,
            latest_visit_code=_text(latest_visit.get("VISTOID")) or "",
            latest_visit_label=_text(latest_visit.get("VISIT")) or "",
            latest_visit_date=_text(latest_visit.get("SVDAT")) or "",
            blinded=True,
            treatment_arm_masked=True,
            key_medical_context=["RUX真实listing派生", "医学解释需独立AI/人工确认"],
        )

    def _visit_anchors(self, subject_id: str, baseline: Optional[date]) -> List[SubjectVisitAnchor]:
        anchors: List[SubjectVisitAnchor] = []
        for row_index, row in self._rows(SV_SHEET, subject_id):
            actual_date = _parse_date(row.get("SVDAT"))
            visit_code = _text(row.get("VISTOID")) or "UNS"
            visit_label = _text(row.get("VISIT")) or visit_code
            planned_day = self._planned_study_day(visit_code, visit_label)
            actual_day = self._study_day(actual_date.isoformat(), baseline) if actual_date else None
            before_days, after_days = self._visit_window(visit_label)
            is_unscheduled = visit_code == "UNS" or "计划外" in visit_label
            anchors.append(
                SubjectVisitAnchor(
                    anchor_id=f"rux_visit_{subject_id}_{row_index}",
                    visit_code=visit_code,
                    visit_label=visit_label,
                    planned_study_day=planned_day,
                    window_before_days=before_days,
                    window_after_days=after_days,
                    actual_date=actual_date.isoformat() if actual_date else None,
                    actual_study_day=actual_day,
                    is_unscheduled=is_unscheduled,
                    deviation_days=(
                        actual_day - planned_day
                        if actual_day is not None and planned_day is not None and not is_unscheduled
                        else None
                    ),
                    source_domain="SV",
                    source_record_id=f"{SV_SHEET}:row:{row_index}",
                    source_locator=self._source_locator(SV_SHEET, row_index),
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
            ("SV", "访视", (SV_SHEET,)),
            ("AE", "不良事件", (AE_SHEET,)),
            ("CM", "合并用药（非试验用药）", (CM_SHEET,)),
            ("IP", "试验药物", (ECB_SHEET,)),
            ("LAB", "实验室检查", (LBHEMA_SHEET, LBCHEM_SHEET)),
            ("EFFICACY", "疗效评估", (BSA_SHEET, IGA_SHEET, EASI_SHEET, SCORAD_SHEET)),
        ]
        return [
            SubjectDomainAvailability(
                domain=domain,
                label=label,
                status=(
                    SubjectDomainAvailabilityStatus.AVAILABLE
                    if any(self._rows(sheet_name, subject_id) for sheet_name in sheets)
                    else SubjectDomainAvailabilityStatus.ABSENT
                ),
                detail=(
                    "原始 listing 中存在该受试者记录。"
                    if any(self._rows(sheet_name, subject_id) for sheet_name in sheets)
                    else "原始 listing 中未发现该受试者记录。"
                ),
            )
            for domain, label, sheets in domains
        ]

    def _visit_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events: List[SubjectTimelineEvent] = []
        for row_index, row in self._rows(SV_SHEET, subject_id):
            event_date = _text(row.get("SVDAT"))
            if not event_date:
                continue
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.VISIT,
                    event_date,
                    baseline,
                    _text(row.get("VISTOID")),
                    _text(row.get("VISIT")),
                    "SV",
                    row_index,
                    SV_SHEET,
                    f"{_text(row.get('VISIT'))}访视",
                    "访视日期来自RUX SV listing。",
                    event_subtype=(
                        SubjectTimelineEventSubtype.UNSCHEDULED_VISIT
                        if _text(row.get("VISTOID")) == "UNS" or "计划外" in _text(row.get("VISIT"))
                        else SubjectTimelineEventSubtype.PLANNED_VISIT
                    ),
                    is_planned=not (
                        _text(row.get("VISTOID")) == "UNS" or "计划外" in _text(row.get("VISIT"))
                    ),
                    is_unscheduled=(
                        _text(row.get("VISTOID")) == "UNS" or "计划外" in _text(row.get("VISIT"))
                    ),
                )
            )
        return events

    def _anc_lab_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows(LBHEMA_SHEET, subject_id):
            if "中性粒细胞计数" not in _text(row.get("LBTEST")):
                continue
            value = _float(row.get("LBORRES"))
            if value is None or value >= 1.5:
                continue
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.LAB,
                    _text(row.get("LBDAT")),
                    baseline,
                    _text(row.get("VISTOID")),
                    _text(row.get("VISIT")),
                    "LBHEMA",
                    row_index,
                    LBHEMA_SHEET,
                    f"ANC {value:g} *10^9/L",
                    _text(row.get("LBDESC")) or "ANC低于方案中断阈值。",
                    result_value=f"{value:g} {_text(row.get('LBORRESU'))}",
                    clinical_interpretation="需按方案表4核对复测、AE和用药调整。",
                    event_subtype=SubjectTimelineEventSubtype.LAB_RESULT,
                )
            )
        return events

    def _chem_lab_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows(LBCHEM_SHEET, subject_id):
            test_name = _text(row.get("LBTEST"))
            if not any(name in test_name for name in ["丙氨酸氨基转移酶", "天门冬氨酸氨基转移酶"]):
                continue
            value = _float(row.get("LBORRES"))
            if value is None or not self._lab_risk_flag(row, value):
                continue
            short_name = "ALT" if "丙氨酸" in test_name else "AST"
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.LAB,
                    _text(row.get("LBDAT")),
                    baseline,
                    _text(row.get("VISTOID")),
                    _text(row.get("VISIT")),
                    "LBCHEM",
                    row_index,
                    LBCHEM_SHEET,
                    f"{short_name} {value:g} {_text(row.get('LBORRESU'))}",
                    _text(row.get("LBCLSIGN")) or "肝功能异常需医学复核。",
                    result_value=f"{value:g} {_text(row.get('LBORRESU'))}",
                    clinical_interpretation="需按方案表4核对复测、给药调整和停药标准。",
                    event_subtype=SubjectTimelineEventSubtype.LAB_RESULT,
                )
            )
        return events

    def _bsa_efficacy_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        seen_dates = set()
        for row_index, row in self._rows(BSA_SHEET, subject_id):
            value = _float(row.get("BSARESS"))
            event_date = _text(row.get("BSADAT"))
            if value is None or value <= 20 or not event_date:
                continue
            key = (_text(row.get("VISTOID")), event_date)
            if key in seen_dates:
                continue
            seen_dates.add(key)
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.EFFICACY_SCORE,
                    event_date,
                    baseline,
                    _text(row.get("VISTOID")),
                    _text(row.get("VISIT")),
                    "BSA",
                    row_index,
                    BSA_SHEET,
                    f"BSA {value:g}%",
                    "治疗期总BSA超过20%，需核对停药/计划外访视处置。",
                    result_value=f"{value:g}%",
                    clinical_interpretation="BSA超过方案关注阈值，需与DSEOT/UNS/给药记录闭环复核。",
                    event_subtype=SubjectTimelineEventSubtype.EFFICACY_ASSESSMENT,
                )
            )
        return events

    def _ae_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows(AE_SHEET, subject_id):
            term = _text(row.get("AETERM"))
            if not term:
                continue
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.ADVERSE_EVENT,
                    _text(row.get("AESTDAT")),
                    baseline,
                    _text(row.get("VISTOID")),
                    _text(row.get("VISIT")),
                    "AE",
                    row_index,
                    AE_SHEET,
                    term,
                    f"{_text(row.get('AETOXGRH'))}；{_text(row.get('AEACN'))}".strip("；"),
                    clinical_interpretation="AE记录需与实验室异常和给药调整闭环复核。",
                    event_subtype=SubjectTimelineEventSubtype.ADVERSE_EVENT,
                    event_end_date=_text(row.get("AEENDAT")) or None,
                    ongoing=_text(row.get("AEONGO")) == "是",
                    severity=_text(row.get("AETOXGRH")),
                    relationship=_text(row.get("AEREL")),
                    outcome=_text(row.get("AEOUT")),
                )
            )
        return events

    def _cm_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows(CM_SHEET, subject_id):
            medication = _text(row.get("CMTRT"))
            if _text(row.get("CMYN")) != "是" or not medication:
                continue
            prohibited = _text(row.get("CMPROHYN")) == "是"
            start_date = _text(row.get("CMSTDAT"))
            end_date = _text(row.get("CMENDAT"))
            ongoing = _text(row.get("CMONGO"))
            reason = _text(row.get("CMINDC"))
            detail_parts = [
                "非试验用药",
                f"治疗原因：{reason}" if reason else "",
                f"研究期间使用：{_text(row.get('CMPERYN'))}" if _text(row.get("CMPERYN")) else "",
                f"禁止合并用药：{_text(row.get('CMPROHYN'))}" if _text(row.get("CMPROHYN")) else "",
                f"{start_date or '未知开始'}~{end_date or ('持续' if ongoing == '是' else '未知结束')}",
            ]
            clinical_note = (
                "命中禁用合并用药标记，需与方案、PD和疗效估计策略闭环复核。"
                if prohibited
                else "研究期间非试验用合并用药，需与方案允许用药范围和疗效评估策略复核。"
            )
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.CONCOMITANT_MEDICATION,
                    start_date or end_date,
                    baseline,
                    _text(row.get("VISTOID")),
                    _text(row.get("VISIT")),
                    "CM",
                    row_index,
                    CM_SHEET,
                    medication,
                    "；".join(part for part in detail_parts if part),
                    clinical_interpretation=clinical_note,
                    event_subtype=SubjectTimelineEventSubtype.NON_STUDY_MEDICATION,
                    event_end_date=end_date or None,
                    ongoing=ongoing == "是",
                )
            )
        return events

    def _ecb_events(self, project_id: str, subject_id: str, baseline: Optional[date]) -> List[SubjectTimelineEvent]:
        events = []
        for row_index, row in self._rows(ECB_SHEET, subject_id):
            action = _text(row.get("ECBADTYP"))
            if action not in {"暂停用药", "重新用药"}:
                continue
            events.append(
                self._event(
                    project_id,
                    subject_id,
                    SubjectTimelineEventType.DOSE_ADJUSTMENT,
                    _text(row.get("ECBSTDAT")),
                    baseline,
                    _text(row.get("VISTOID")),
                    _text(row.get("VISIT")),
                    "ECB",
                    row_index,
                    ECB_SHEET,
                    f"{action}：{_text(row.get('ECBADRAE'))}",
                    f"{_text(row.get('ECBADREA'))}；{_text(row.get('ECBSTDAT'))}~{_text(row.get('ECBENDAT'))}".strip("；"),
                    clinical_interpretation="给药调整需与AE和实验室异常日期链路复核。",
                    event_subtype=(
                        SubjectTimelineEventSubtype.STUDY_DRUG_INTERRUPTION
                        if action == "暂停用药"
                        else SubjectTimelineEventSubtype.STUDY_DRUG_RESUMPTION
                    ),
                    event_end_date=_text(row.get("ECBENDAT")) or None,
                    ongoing=_text(row.get("ECBONGO")) == "是",
                )
            )
        return events

    def _event(
        self,
        project_id: str,
        subject_id: str,
        event_type: SubjectTimelineEventType,
        event_date: str,
        baseline: Optional[date],
        visit_code: str,
        visit_label: str,
        source_domain: str,
        row_index: int,
        sheet_name: str,
        title: str,
        detail: str,
        result_value: Optional[str] = None,
        clinical_interpretation: str = "",
        event_subtype: SubjectTimelineEventSubtype = SubjectTimelineEventSubtype.OTHER,
        event_end_date: Optional[str] = None,
        ongoing: bool = False,
        is_planned: Optional[bool] = None,
        is_unscheduled: bool = False,
        severity: str = "",
        relationship: str = "",
        outcome: str = "",
    ) -> SubjectTimelineEvent:
        locator = self._source_locator(sheet_name, row_index)
        event_hash = sha1(f"{subject_id}|{source_domain}|{row_index}|{title}".encode("utf-8")).hexdigest()[:10]
        return SubjectTimelineEvent(
            event_id=f"rux_event_{event_hash}",
            project_id=project_id,
            subject_id=subject_id,
            event_type=event_type,
            event_subtype=event_subtype,
            event_date=event_date or None,
            event_end_date=event_end_date,
            study_day=self._study_day(event_date, baseline),
            end_study_day=self._study_day(event_end_date, baseline) if event_end_date else None,
            ongoing=ongoing,
            date_precision=(
                SubjectTimelineEventDatePrecision.DAY
                if _parse_date(event_date)
                else SubjectTimelineEventDatePrecision.UNKNOWN
            ),
            is_planned=is_planned,
            is_unscheduled=is_unscheduled,
            visit_code=visit_code or None,
            visit_label=visit_label,
            source_domain=source_domain,
            source_record_id=f"{sheet_name}:row:{row_index}",
            source_locator=locator,
            title=title,
            detail=detail,
            result_value=result_value,
            severity=severity,
            relationship=relationship,
            outcome=outcome,
            clinical_interpretation=clinical_interpretation,
        )

    def _anc_metric(self, subject_id: str, baseline: Optional[date]) -> SubjectTrendMetric:
        return self._lab_metric(
            subject_id,
            baseline,
            sheet_name=LBHEMA_SHEET,
            metric_key="anc",
            metric_label="中性粒细胞计数",
            test_contains="中性粒细胞计数",
            source_domain="LBHEMA",
            risk_low=1.5,
        )

    def _safety_metrics(self, subject_id: str, baseline: Optional[date]) -> List[SubjectTrendMetric]:
        metrics = [
            self._anc_metric(subject_id, baseline),
            self._lab_metric(
                subject_id,
                baseline,
                sheet_name=LBCHEM_SHEET,
                metric_key="alt",
                metric_label="ALT",
                test_contains="丙氨酸氨基转移酶",
                source_domain="LBCHEM",
            ),
            self._lab_metric(
                subject_id,
                baseline,
                sheet_name=LBCHEM_SHEET,
                metric_key="ast",
                metric_label="AST",
                test_contains="天门冬氨酸氨基转移酶",
                source_domain="LBCHEM",
            ),
        ]
        return [metric for metric in metrics if metric.points]

    def _lab_metric(
        self,
        subject_id: str,
        baseline: Optional[date],
        sheet_name: str,
        metric_key: str,
        metric_label: str,
        test_contains: str,
        source_domain: str,
        risk_low: Optional[float] = None,
    ) -> SubjectTrendMetric:
        raw_points = []
        for row_index, row in self._rows(LBHEMA_SHEET, subject_id):
            if sheet_name != LBHEMA_SHEET:
                break
            if test_contains not in _text(row.get("LBTEST")):
                continue
            raw_points.append((row_index, row))
        if sheet_name != LBHEMA_SHEET:
            raw_points = [
                (row_index, row)
                for row_index, row in self._rows(sheet_name, subject_id)
                if test_contains in _text(row.get("LBTEST"))
            ]

        points = self._trend_points_from_rows(
            subject_id,
            baseline,
            raw_points,
            metric_key=metric_key,
            date_key="LBDAT",
            value_getter=lambda row: _float(row.get("LBORRES")),
            source_domain=source_domain,
            sheet_name=sheet_name,
            value_note_getter=lambda row: _text(row.get("LBCLSIGN")) or _text(row.get("LBDESC")),
            reference_low_getter=lambda row: _float(row.get("LBORNRLO")),
            reference_high_getter=lambda row: _float(row.get("LBORNRHI")),
            risk_getter=lambda row, value: self._lab_risk_flag(row, value, risk_low),
            normality_getter=lambda row, value: self._lab_normality(row, value, risk_low),
        )
        unit = next((_text(row.get("LBORRESU")) for _, row in raw_points if _text(row.get("LBORRESU"))), "")
        return SubjectTrendMetric(
            metric_key=metric_key,
            metric_label=metric_label,
            domain=SubjectTrendDomain.SAFETY,
            unit=unit,
            direction=SubjectTrendDirection.STABLE_RANGE,
            points=points,
        )

    def _efficacy_metrics(self, subject_id: str, baseline: Optional[date]) -> List[SubjectTrendMetric]:
        metrics = [
            self._simple_efficacy_metric(
                subject_id,
                baseline,
                sheet_name=BSA_SHEET,
                metric_key="bsa_total",
                metric_label="BSA总受累体表面积",
                date_key="BSADAT",
                value_getter=lambda row: _float(row.get("BSARESS")),
                unit="%",
            ),
            self._simple_efficacy_metric(
                subject_id,
                baseline,
                sheet_name=IGA_SHEET,
                metric_key="iga",
                metric_label="IGA评分",
                date_key="IGADAT",
                value_getter=lambda row: self._score_prefix(row.get("IGASCORE")),
                unit="分",
            ),
            self._simple_efficacy_metric(
                subject_id,
                baseline,
                sheet_name=EASI_SHEET,
                metric_key="easi_total",
                metric_label="EASI总分",
                date_key="EASIDAT",
                value_getter=lambda row: _float(row.get("EASISCOS")),
                unit="分",
            ),
            self._simple_efficacy_metric(
                subject_id,
                baseline,
                sheet_name=SCORAD_SHEET,
                metric_key="scorad_total",
                metric_label="SCORAD总分",
                date_key="SRDAT",
                value_getter=lambda row: _float(row.get("SRSCORE")),
                unit="分",
            ),
        ]
        return [metric for metric in metrics if metric.points]

    def _simple_efficacy_metric(
        self,
        subject_id: str,
        baseline: Optional[date],
        sheet_name: str,
        metric_key: str,
        metric_label: str,
        date_key: str,
        value_getter,
        unit: str,
    ) -> SubjectTrendMetric:
        rows = self._rows(sheet_name, subject_id)
        if sheet_name in {BSA_SHEET, EASI_SHEET}:
            rows = self._coalesce_visit_level_total_rows(
                rows,
                sheet_name=sheet_name,
                date_key=date_key,
                value_getter=value_getter,
            )
        points = self._trend_points_from_rows(
            subject_id,
            baseline,
            rows,
            metric_key=metric_key,
            date_key=date_key,
            value_getter=value_getter,
            source_domain=sheet_name.split("--", 1)[0],
            sheet_name=sheet_name,
            value_note_getter=lambda row: _text(row.get("IGASCORE")) if sheet_name == IGA_SHEET else "",
        )
        return SubjectTrendMetric(
            metric_key=metric_key,
            metric_label=metric_label,
            domain=SubjectTrendDomain.EFFICACY,
            unit=unit,
            direction=SubjectTrendDirection.LOWER_IS_BETTER,
            points=points,
        )

    def _coalesce_visit_level_total_rows(
        self,
        rows: List[Tuple[int, Dict[str, str]]],
        *,
        sheet_name: str,
        date_key: str,
        value_getter,
    ) -> List[Tuple[int, Dict[str, Any]]]:
        """Project one visit-level total per stable form event.

        RUX BSA and EASI exports repeat the visit-level total on each body-region
        subrecord. RECREP identifies those component rows; it is not a distinct
        total assessment. Conflicting dates or totals fail open as separate
        points so source disagreement is never hidden.
        """

        identity_fields = ("SUBJID", "VISTOID", "VISTREP", "FORMOID", "FORMREP")
        grouped: Dict[Tuple[str, ...], List[Tuple[int, Dict[str, str]]]] = {}
        for row_index, row in rows:
            identity = tuple(_text(row.get(field)) for field in identity_fields)
            grouped.setdefault(identity, []).append((row_index, row))

        projected: List[Tuple[int, Dict[str, Any]]] = []
        for identity, components in grouped.items():
            dates = {_text(row.get(date_key)) for _, row in components if _text(row.get(date_key))}
            values = {
                value
                for _, row in components
                if (value := value_getter(row)) is not None
            }
            if len(components) == 1 or len(dates) != 1 or len(values) != 1:
                projected.extend(components)
                continue

            canonical_index, canonical_row = next(
                (
                    (row_index, row)
                    for row_index, row in components
                    if _text(row.get(date_key)) and value_getter(row) is not None
                ),
                components[0],
            )
            event_row: Dict[str, Any] = dict(canonical_row)
            event_row["__source_component_row_indices__"] = [
                row_index for row_index, _ in components
            ]
            event_row["__source_record_id__"] = (
                f"{sheet_name}:"
                + "|".join(
                    f"{field}:{value or '-'}"
                    for field, value in zip(identity_fields, identity)
                )
            )
            projected.append((canonical_index, event_row))
        return projected

    def _trend_points_from_rows(
        self,
        subject_id: str,
        baseline: Optional[date],
        rows: List[Tuple[int, Dict[str, Any]]],
        metric_key: str,
        date_key: str,
        value_getter,
        source_domain: str,
        sheet_name: str,
        value_note_getter=None,
        reference_low_getter=None,
        reference_high_getter=None,
        risk_getter=None,
        normality_getter=None,
    ) -> List[SubjectTrendPoint]:
        raw_points: List[Tuple[int, Dict[str, Any], float]] = []
        for row_index, row in rows:
            value = value_getter(row)
            assessment_date = _text(row.get(date_key))
            visit_code = _text(row.get("VISTOID"))
            if value is None or not assessment_date:
                continue
            raw_points.append((row_index, row, value))

        ordered = sorted(
            raw_points,
            key=lambda item: (_parse_date(item[1].get(date_key)) or date.max, _text(item[1].get("VISTOID")), item[0]),
        )
        baseline_value = next((value for _, row, value in ordered if _text(row.get("VISTOID")) == "D1"), None)
        baseline_locator = next(
            (
                self._source_locator(sheet_name, row_index)
                for row_index, row, _ in ordered
                if _text(row.get("VISTOID")) == "D1"
            ),
            "",
        )

        points = []
        for sequence, (row_index, row, value) in enumerate(ordered, start=1):
            ref_low = reference_low_getter(row) if reference_low_getter else None
            ref_high = reference_high_getter(row) if reference_high_getter else None
            risk_flag = risk_getter(row, value) if risk_getter else False
            normality = normality_getter(row, value) if normality_getter else "not_applicable"
            source_component_indices = row.get("__source_component_row_indices__") or [row_index]
            source_component_locators = [
                self._source_locator(sheet_name, component_index)
                for component_index in source_component_indices
            ]
            source_record_id = row.get("__source_record_id__") or f"{sheet_name}:row:{row_index}"
            point_id = f"rux_{metric_key}_{subject_id}_{row_index}"
            if row.get("__source_record_id__"):
                event_hash = sha1(f"{metric_key}|{source_record_id}".encode("utf-8")).hexdigest()[:12]
                point_id = f"rux_{metric_key}_{event_hash}"
            point_note = value_note_getter(row) if value_note_getter else ""
            if len(source_component_locators) > 1:
                projection_note = (
                    f"同一表单事件的{len(source_component_locators)}个部位子记录共享访视级总值；"
                    "趋势按稳定表单事件投影一次。"
                )
                point_note = "；".join(part for part in [point_note, projection_note] if part)
            points.append(
                SubjectTrendPoint(
                    point_id=point_id,
                    visit_code=_text(row.get("VISTOID")) or "",
                    visit_label=_text(row.get("VISIT")),
                    assessment_date=_text(row.get(date_key)),
                    study_day=self._study_day(_text(row.get(date_key)), baseline),
                    value=value,
                    original_value=_text(row.get("LBORRES")) or f"{value:g}",
                    standardized_value=_float(row.get("LBSTRES")),
                    unit=_text(row.get("LBORRESU")),
                    baseline_value=baseline_value,
                    is_baseline=_text(row.get("VISTOID")) == "D1",
                    baseline_rule="方案定义的D1给药前评估值；缺失时不使用筛选期值替代。",
                    baseline_source_locator=baseline_locator,
                    change_from_baseline=round(value - baseline_value, 4) if baseline_value is not None else None,
                    percent_change_from_baseline=(
                        round((value - baseline_value) / baseline_value * 100, 4)
                        if baseline_value not in (None, 0)
                        else None
                    ),
                    reference_low=ref_low,
                    reference_high=ref_high,
                    reference_range_text="~".join(
                        part for part in [_text(row.get("LBORNRLO")), _text(row.get("LBORNRHI"))] if part
                    ),
                    reference_range_source=_text(row.get("LBNAM")) or "原始listing",
                    normality=normality,
                    abnormal_direction=normality if normality in {"high", "low"} else "",
                    clinical_significance=_text(row.get("LBCLSIGN")),
                    assessment_sequence=sequence,
                    is_unscheduled=_text(row.get("VISTOID")) == "UNS" or "计划外" in _text(row.get("VISIT")),
                    risk_flag=bool(risk_flag),
                    source_domain=source_domain,
                    source_record_id=source_record_id,
                    source_locator=self._source_locator(sheet_name, row_index),
                    source_component_locators=source_component_locators,
                    note=point_note,
                )
            )
        return points

    def _score_prefix(self, value: Any) -> Optional[float]:
        text = _text(value)
        match = re.match(r"(?P<score>\d+(?:\.\d+)?)\s*分", text)
        if not match:
            return _float(text)
        return float(match.group("score"))

    def _lab_risk_flag(self, row: Dict[str, str], value: float, risk_low: Optional[float] = None) -> bool:
        if risk_low is not None and value < risk_low:
            return True
        ref_low = _float(row.get("LBORNRLO"))
        ref_high = _float(row.get("LBORNRHI"))
        if ref_low is not None and value < ref_low:
            return True
        if ref_high is not None and value > ref_high:
            return True
        return _text(row.get("LBNRIND")) not in ("", "0", "正常")

    def _lab_normality(self, row: Dict[str, str], value: float, risk_low: Optional[float] = None) -> str:
        if risk_low is not None and value < risk_low:
            return "low"
        ref_low = _float(row.get("LBORNRLO"))
        ref_high = _float(row.get("LBORNRHI"))
        if ref_low is not None and value < ref_low:
            return "low"
        if ref_high is not None and value > ref_high:
            return "high"
        if _text(row.get("LBNRIND")) in ("", "0"):
            return "normal"
        return _text(row.get("LBCLSIGN")) or _text(row.get("LBNRIND")) or "not_applicable"

    def _baseline_date(self, subject_id: str) -> Optional[date]:
        for _, row in self._rows(SV_SHEET, subject_id):
            if "基线" in _text(row.get("VISIT")) or _text(row.get("VISTOID")) == "D1":
                parsed = _parse_date(row.get("SVDAT"))
                if parsed:
                    return parsed
        return None

    def _study_day(self, value: str, baseline: Optional[date]) -> Optional[int]:
        event_date = _parse_date(value)
        if event_date is None or baseline is None:
            return None
        delta = (event_date - baseline).days
        return delta + 1 if delta >= 0 else delta

    def _planned_study_day(self, visit_code: str, visit_label: str) -> Optional[int]:
        match = re.fullmatch(r"D(?P<day>\d+)", visit_code)
        if match:
            return int(match.group("day"))
        label_match = re.search(r"\bD(?P<day>\d+)\b", visit_label)
        return int(label_match.group("day")) if label_match else None

    def _visit_window(self, visit_label: str) -> Tuple[Optional[int], Optional[int]]:
        symmetric = re.search(r"±\s*(?P<days>\d+)\s*天", visit_label)
        if symmetric:
            days = int(symmetric.group("days"))
            return days, days
        positive = re.search(r"\+\s*(?P<days>\d+)\s*天", visit_label)
        if positive:
            return 0, int(positive.group("days"))
        return None, None

    def _site_id(self, subject_id: str) -> Optional[str]:
        for _, row in self._rows(SUBJ_SHEET, subject_id):
            return _text(row.get("SITEID")) or None
        return None
