from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha1
from typing import Any, Dict, Iterable, List, Optional, Tuple

from packages.contracts.workbench_contracts import (
    AuditEvent,
    DataBatch,
    FieldMappingCandidate,
    ListingDiffSummary,
    MonitoringIntakeRequest,
    MonitoringIntakeResult,
    RiskCase,
    RiskSeverity,
    RiskStatus,
    RuleRunSummary,
)

from .demo_repository import DemoRepository


FIELD_ALIASES = {
    "SUBJID": "subject_id",
    "USUBJID": "subject_id",
    "SUBJECT_ID": "subject_id",
    "SITEID": "site_id",
    "SITE_ID": "site_id",
    "CENTER": "site_id",
    "VISIT": "visit",
    "VISITNUM": "visit_number",
    "RANDDTC": "randomization_date",
    "AETERM": "ae_term",
    "AEDECOD": "ae_term",
    "AESTDTC": "ae_start_date",
    "AEENDTC": "ae_end_date",
    "AESEV": "ae_severity",
    "AESER": "sae_flag",
    "MHDECOD": "mh_term",
    "MHTERM": "mh_term",
    "MHSTDTC": "mh_start_date",
    "CMTRT": "conmed_name",
    "CMSTDTC": "conmed_start_date",
    "CMENDTC": "conmed_end_date",
    "CMINDC": "conmed_indication",
    "LBTEST": "lab_test",
    "LBORRES": "lab_value",
    "LBSTRESN": "lab_value_numeric",
    "LBSTRESU": "lab_unit",
    "LBNRIND": "lab_normality",
    "LBTOXGR": "lab_toxicity_grade",
    "QSTEST": "efficacy_test",
    "QSSTRESN": "efficacy_value",
    "QSDTC": "assessment_date",
    "PDTERM": "pd_term",
    "DVTERM": "pd_term",
    "QUERYID": "query_id",
    "QUERY_STATUS": "query_status",
    "CHANGE_FLAG": "change_flag",
}

FIELDS_REQUIRING_CONFIRMATION = {
    "AESI_FLAG": "safety_interest_flag",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalized_key(value: str) -> str:
    return value.strip().upper().replace(" ", "_")


def value_as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def contains_any(value: str, needles: Iterable[str]) -> bool:
    lower = value.lower()
    return any(needle.lower() in lower for needle in needles)


class MonitoringIntakeService:
    def __init__(self, repo: DemoRepository):
        self.repo = repo
        self._sessions: Dict[str, MonitoringIntakeResult] = {}

    def submit(self, project_id: str, request: MonitoringIntakeRequest) -> MonitoringIntakeResult:
        self.repo.project(project_id)
        sheets = request.sheets or self.demo_listing_payload()
        field_mappings = self._infer_field_mappings(sheets, request.mapping_confirmations)
        normalized_rows = self._normalize_rows(sheets, field_mappings)
        session_hash = sha1(
            f"{project_id}|{request.batch_label}|{request.extract_date}|{len(normalized_rows)}|{utc_now().isoformat()}".encode(
                "utf-8"
            )
        ).hexdigest()[:10]
        session_id = f"intake_{session_hash}"
        batch_id = self._next_batch_id(project_id)
        diff = self._diff_summary(project_id, batch_id, request.previous_batch_id, normalized_rows)
        batch = DataBatch(
            batch_id=batch_id,
            project_id=project_id,
            batch_label=request.batch_label,
            extract_date=request.extract_date,
            uploaded_by=request.uploaded_by,
            status="rules_run",
            source_file_ids=[f"session:{session_id}"],
            previous_batch_id=diff.previous_batch_id,
            mapping_profile_id="default_edc_listing_mapping_v0_2",
            row_count=sum(diff.sheet_row_counts.values()),
            subject_count=diff.subject_count,
            site_count=diff.site_count,
            created_at=utc_now(),
        )
        generated_risks = self._run_rules(project_id, batch_id, normalized_rows)
        blocked_by_mapping = any(item.status == "requires_confirmation" for item in field_mappings)
        mapping_status = "requires_confirmation" if blocked_by_mapping else "confirmed"
        rule_run = RuleRunSummary(
            total_rules=4,
            generated_risk_count=len(generated_risks),
            generated_query_count=sum(1 for risk in generated_risks if "query" in risk.recommended_action.lower()),
            blocked_by_mapping=blocked_by_mapping,
            messages=self._rule_messages(blocked_by_mapping, generated_risks),
        )
        audit_preview = [
            AuditEvent(
                audit_id=f"audit_{session_id}_upload",
                project_id=project_id,
                actor=request.uploaded_by,
                action="monitoring_listing_intake_submitted",
                target_type="data_batch",
                target_id=batch_id,
                detail={
                    "session_id": session_id,
                    "sheet_row_counts": diff.sheet_row_counts,
                    "mapping_status": mapping_status,
                },
                created_at=utc_now(),
            ),
            AuditEvent(
                audit_id=f"audit_{session_id}_rules",
                project_id=project_id,
                actor="system",
                action="monitoring_rule_engine_run",
                target_type="monitoring_intake",
                target_id=session_id,
                detail={
                    "generated_risk_count": len(generated_risks),
                    "generated_risk_ids": [risk.risk_id for risk in generated_risks],
                },
                created_at=utc_now(),
            ),
        ]
        result = MonitoringIntakeResult(
            session_id=session_id,
            project_id=project_id,
            mapping_status=mapping_status,
            batch=batch,
            field_mappings=field_mappings,
            diff_summary=diff,
            generated_risks=generated_risks,
            rule_run=rule_run,
            audit_preview=audit_preview,
        )
        self._sessions[session_id] = result
        self.repo.record_monitoring_intake(result)
        return result

    def session(self, session_id: str) -> MonitoringIntakeResult:
        return self._sessions[session_id]

    def demo_listing_payload(self) -> List[Dict[str, Any]]:
        return [
            {
                "sheet_name": "CM",
                "rows": [
                    {
                        "SUBJID": "10008",
                        "SITEID": "10",
                        "VISIT": "SCR",
                        "RANDDTC": "2026-07-06",
                        "CMTRT": "氯雷他定",
                        "CMSTDTC": "2026-06-30",
                        "CMENDTC": "2026-07-05",
                        "CMINDC": "鼻痒、喷嚏",
                        "CHANGE_FLAG": "new",
                    },
                    {
                        "SUBJID": "06021",
                        "SITEID": "06",
                        "VISIT": "W2",
                        "CMTRT": "人工泪液",
                        "CMSTDTC": "2026-07-18",
                        "CMENDTC": "",
                        "CMINDC": "眼痒",
                        "CHANGE_FLAG": "changed",
                    },
                ],
            },
            {
                "sheet_name": "MH",
                "rows": [
                    {
                        "SUBJID": "06021",
                        "SITEID": "06",
                        "VISIT": "SCR",
                        "MHTERM": "过敏性结膜炎史",
                        "MHSTDTC": "2024-05",
                        "CHANGE_FLAG": "new",
                    }
                ],
            },
            {
                "sheet_name": "AE",
                "rows": [
                    {
                        "SUBJID": "10008",
                        "SITEID": "10",
                        "VISIT": "W1",
                        "AETERM": "头痛",
                        "AESTDTC": "2026-07-13",
                        "AESEV": "轻度",
                        "AESER": "N",
                        "AESI_FLAG": "N",
                        "CHANGE_FLAG": "new",
                    }
                ],
            },
            {
                "sheet_name": "LB",
                "rows": [
                    {
                        "SUBJID": "10021",
                        "SITEID": "18",
                        "VISIT": "W2",
                        "LBTEST": "ALT",
                        "LBSTRESN": "165",
                        "LBSTRESU": "U/L",
                        "LBNRIND": "HIGH",
                        "LBTOXGR": "2",
                        "CHANGE_FLAG": "new",
                    }
                ],
            },
            {
                "sheet_name": "QS",
                "rows": [
                    {
                        "SUBJID": "10045",
                        "SITEID": "03",
                        "VISIT": "W4",
                        "QSTEST": "rTNSS",
                        "QSSTRESN": "8.1",
                        "QSDTC": "2026-07-27",
                        "CHANGE_FLAG": "changed",
                    }
                ],
            },
        ]

    def _next_batch_id(self, project_id: str) -> str:
        max_number = 0
        for batch in self.repo.batches(project_id):
            suffix = batch.batch_id.rsplit("_", 1)[-1]
            if suffix.isdigit():
                max_number = max(max_number, int(suffix))
        return f"batch_{max_number + 1:03d}"

    def _infer_field_mappings(
        self,
        sheets: List[Any],
        confirmations: Dict[str, str],
    ) -> List[FieldMappingCandidate]:
        seen: set[Tuple[str, str]] = set()
        mappings: List[FieldMappingCandidate] = []
        for sheet in sheets:
            sheet_name, rows = self._sheet_parts(sheet)
            for row in rows:
                for raw_field in row.keys():
                    source_field = str(raw_field)
                    key = normalized_key(source_field)
                    marker = (sheet_name, source_field)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    if source_field in confirmations:
                        mappings.append(
                            FieldMappingCandidate(
                                sheet_name=sheet_name,
                                source_field=source_field,
                                standard_field=confirmations[source_field],
                                confidence=1.0,
                                status="confirmed",
                                note="用户已确认映射。",
                            )
                        )
                    elif key in confirmations:
                        mappings.append(
                            FieldMappingCandidate(
                                sheet_name=sheet_name,
                                source_field=source_field,
                                standard_field=confirmations[key],
                                confidence=1.0,
                                status="confirmed",
                                note="用户已确认映射。",
                            )
                        )
                    elif key in FIELDS_REQUIRING_CONFIRMATION:
                        mappings.append(
                            FieldMappingCandidate(
                                sheet_name=sheet_name,
                                source_field=source_field,
                                standard_field=FIELDS_REQUIRING_CONFIRMATION[key],
                                confidence=0.72,
                                status="requires_confirmation",
                                note="新增/漂移字段，运行正式规则前需医学和数据共同确认。",
                            )
                        )
                    elif key in FIELD_ALIASES:
                        mappings.append(
                            FieldMappingCandidate(
                                sheet_name=sheet_name,
                                source_field=source_field,
                                standard_field=FIELD_ALIASES[key],
                                confidence=0.96,
                                status="auto_mapped",
                            )
                        )
                    else:
                        mappings.append(
                            FieldMappingCandidate(
                                sheet_name=sheet_name,
                                source_field=source_field,
                                standard_field="unmapped",
                                confidence=0.0,
                                status="unmapped",
                                note="暂不参与本轮医学规则。",
                            )
                        )
        return mappings

    def _normalize_rows(
        self,
        sheets: List[Any],
        mappings: List[FieldMappingCandidate],
    ) -> List[Dict[str, Any]]:
        mapping_index = {(item.sheet_name, item.source_field): item.standard_field for item in mappings}
        normalized: List[Dict[str, Any]] = []
        for sheet in sheets:
            sheet_name, rows = self._sheet_parts(sheet)
            for row_number, row in enumerate(rows, start=1):
                normalized_row: Dict[str, Any] = {"sheet_name": sheet_name, "source_row": row_number}
                for source_field, value in row.items():
                    standard_field = mapping_index.get((sheet_name, str(source_field)))
                    if standard_field and standard_field != "unmapped":
                        normalized_row[standard_field] = value
                    normalized_row[f"raw__{source_field}"] = value
                normalized.append(normalized_row)
        return normalized

    def _diff_summary(
        self,
        project_id: str,
        batch_id: str,
        previous_batch_id: Optional[str],
        rows: List[Dict[str, Any]],
    ) -> ListingDiffSummary:
        previous = previous_batch_id
        if previous is None:
            batches = self.repo.batches(project_id)
            previous = batches[-1].batch_id if batches else None
        subjects = sorted({value_as_text(row.get("subject_id")) for row in rows if value_as_text(row.get("subject_id"))})
        sites = sorted({value_as_text(row.get("site_id")) for row in rows if value_as_text(row.get("site_id"))})
        sheet_counts: Dict[str, int] = {}
        changed_subjects = set()
        for row in rows:
            sheet_counts[row["sheet_name"]] = sheet_counts.get(row["sheet_name"], 0) + 1
            if value_as_text(row.get("change_flag")).lower() in {"changed", "updated", "改值"}:
                changed_subjects.add(value_as_text(row.get("subject_id")))
        return ListingDiffSummary(
            previous_batch_id=previous,
            new_batch_id=batch_id,
            added_row_count=sum(1 for row in rows if value_as_text(row.get("change_flag")).lower() in {"new", "新增", ""}),
            changed_row_count=sum(1 for row in rows if value_as_text(row.get("change_flag")).lower() in {"changed", "updated", "改值"}),
            removed_row_count=0,
            subject_count=len(subjects),
            site_count=len(sites),
            sheet_row_counts=sheet_counts,
            new_subject_ids=subjects,
            changed_subject_ids=sorted(item for item in changed_subjects if item),
        )

    def _run_rules(self, project_id: str, batch_id: str, rows: List[Dict[str, Any]]) -> List[RiskCase]:
        risks: List[RiskCase] = []
        rows_by_subject: Dict[str, List[Dict[str, Any]]] = {}
        for row in rows:
            subject_id = value_as_text(row.get("subject_id"))
            if subject_id:
                rows_by_subject.setdefault(subject_id, []).append(row)

        for subject_id, subject_rows in sorted(rows_by_subject.items()):
            site_id = next((value_as_text(row.get("site_id")) for row in subject_rows if value_as_text(row.get("site_id"))), None)
            if self._has_washout_risk(subject_rows):
                risks.append(
                    self._risk(
                        project_id,
                        batch_id,
                        subject_id,
                        site_id,
                        "禁用药/洗脱违规",
                        RiskSeverity.HIGH,
                        f"{subject_id} 随机前抗组胺药洗脱不足",
                        "CM listing 显示氯雷他定末次用药距离随机不足4天。",
                        "发起 query，核对 CM 末次用药日期、PD 登记和是否影响主要疗效解释。",
                        "KRI-CM-WASHOUT",
                    )
                )
            if self._has_eye_mh_without_ae(subject_rows):
                risks.append(
                    self._risk(
                        project_id,
                        batch_id,
                        subject_id,
                        site_id,
                        "AE/MH漏报",
                        RiskSeverity.MEDIUM,
                        f"{subject_id} 眼部症状与 AE/MH 记录不一致",
                        "MH/CM 提示眼部症状或过敏性结膜炎史，但 AE listing 未见对应眼部事件。",
                        "请中心确认眼部症状是否应作为 AE 记录，并补充研究者医学判断。",
                        "KRI-AE-MH-EYE",
                    )
                )
            for lab_row in subject_rows:
                if self._is_lab_abnormal_without_explanation(lab_row):
                    risks.append(
                        self._risk(
                            project_id,
                            batch_id,
                            subject_id,
                            site_id,
                            "实验室异常未解释",
                            RiskSeverity.MEDIUM,
                            f"{subject_id} {value_as_text(lab_row.get('lab_test'))} 升高 Grade {value_as_text(lab_row.get('lab_toxicity_grade'))} 未见医学解释",
                            "LB listing 存在 CTCAE 分级或高于参考范围的实验室异常，当前数据包未见对应 AE/医学解释。",
                            "复核实验室复测、AE 记录、合并用药和研究者说明，必要时发起 query。",
                            "QTL-LB-UNEXPLAINED",
                        )
                    )
            if self._has_efficacy_deviation(subject_rows):
                risks.append(
                    self._risk(
                        project_id,
                        batch_id,
                        subject_id,
                        site_id,
                        "疗效偏离",
                        RiskSeverity.MEDIUM,
                        f"{subject_id} rTNSS 连续恶化或异常偏高",
                        "QS listing 显示治疗期关键访视 rTNSS 仍明显偏高或较前次恶化。",
                        "结合合并用药、依从性、访视窗口和 rescue medication 解释疗效趋势。",
                        "KRI-QS-EFFICACY-DEVIATION",
                    )
                )
        return risks

    def _risk(
        self,
        project_id: str,
        batch_id: str,
        subject_id: str,
        site_id: Optional[str],
        risk_type: str,
        severity: RiskSeverity,
        title: str,
        rationale: str,
        action: str,
        rule_id: str,
    ) -> RiskCase:
        risk_hash = sha1(f"{batch_id}|{subject_id}|{rule_id}".encode("utf-8")).hexdigest()[:8]
        return RiskCase(
            risk_id=f"risk_{risk_hash}",
            project_id=project_id,
            module="medical_monitoring",
            risk_type=risk_type,
            title=title,
            subject_id=subject_id,
            site_id=site_id,
            severity=severity,
            status=RiskStatus.ACTION_REQUIRED if severity == RiskSeverity.HIGH else RiskStatus.IN_REVIEW,
            source_batch_id=batch_id,
            rule_id=rule_id,
            rationale=rationale,
            recommended_action=action,
            created_at=utc_now(),
        )

    def _rule_messages(self, blocked_by_mapping: bool, risks: List[RiskCase]) -> List[str]:
        messages = []
        if blocked_by_mapping:
            messages.append("存在需确认字段映射；本轮结果可用于预览，正式冻结前需确认映射。")
        if risks:
            messages.append(f"已生成 {len(risks)} 条医学风险，建议先处理高风险和需 query 项。")
        else:
            messages.append("未生成新医学风险。")
        return messages

    def _has_washout_risk(self, rows: List[Dict[str, Any]]) -> bool:
        for row in rows:
            name = value_as_text(row.get("conmed_name"))
            if contains_any(name, ["氯雷他定", "loratadine", "抗组胺"]):
                randomization = value_as_text(row.get("randomization_date"))
                end_date = value_as_text(row.get("conmed_end_date"))
                if not randomization or not end_date:
                    return True
                randomization_date = parse_date_prefix(randomization)
                medication_end_date = parse_date_prefix(end_date)
                if randomization_date is None or medication_end_date is None:
                    return True
                washout_start = randomization_date - timedelta(days=4)
                if medication_end_date >= washout_start:
                    return True
        return False

    def _has_eye_mh_without_ae(self, rows: List[Dict[str, Any]]) -> bool:
        has_eye_context = any(
            contains_any(
                " ".join(
                    [
                        value_as_text(row.get("mh_term")),
                        value_as_text(row.get("conmed_indication")),
                        value_as_text(row.get("conmed_name")),
                    ]
                ),
                ["眼", "结膜", "ocular", "conjunct"],
            )
            for row in rows
        )
        has_eye_ae = any(contains_any(value_as_text(row.get("ae_term")), ["眼", "结膜", "ocular", "conjunct"]) for row in rows)
        return has_eye_context and not has_eye_ae

    def _is_lab_abnormal_without_explanation(self, row: Dict[str, Any]) -> bool:
        if row.get("sheet_name") != "LB":
            return False
        normality = value_as_text(row.get("lab_normality")).upper()
        grade = value_as_text(row.get("lab_toxicity_grade"))
        if grade:
            try:
                return int(float(grade)) >= 2
            except ValueError:
                return False
        return normality in {"HIGH", "LOW", "ABNORMAL"}

    def _has_efficacy_deviation(self, rows: List[Dict[str, Any]]) -> bool:
        for row in rows:
            if row.get("sheet_name") != "QS":
                continue
            test = value_as_text(row.get("efficacy_test"))
            if not contains_any(test, ["rTNSS", "TNSS"]):
                continue
            try:
                return float(value_as_text(row.get("efficacy_value"))) >= 8.0
            except ValueError:
                continue
        return False

    def _sheet_parts(self, sheet: Any) -> Tuple[str, List[Dict[str, Any]]]:
        if isinstance(sheet, dict):
            return str(sheet.get("sheet_name", "LISTING")), list(sheet.get("rows", []))
        return sheet.sheet_name, sheet.rows


def parse_date_prefix(value: str) -> Optional[date]:
    text = value_as_text(value)
    if len(text) < 10:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None
