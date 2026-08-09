from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from packages.contracts.workbench_contracts import (
    EligibilityActionItem,
    EligibilityAuditSummary,
    EligibilityAvailableAction,
    EligibilityCandidate,
    EligibilityCandidateStatus,
    EligibilityEvidence,
    EligibilityOverallConclusion,
    EligibilityPoolSummary,
    EligibilityProjectStats,
    EligibilityReviewDataset,
    EligibilityReviewPhase,
    EligibilityRuleDefinition,
    EligibilityRuleReview,
    EligibilityRuleType,
    EligibilityRuleVerdict,
    EligibilitySubjectPhaseReview,
    EligibilitySubjectRow,
    EligibilityTaskEntry,
    RiskSeverity,
)


DEFAULT_ENROLLMENT_PROJECTS_DIR = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/enrollment-review-app/projects"
)

PROJECT_CODE_ALIASES = {
    "proj_mgk10_sar_demo": "MG-K10-SAR-III",
    "MG-K10-SAR-DEMO": "MG-K10-SAR-III",
}

RULE_HEADING_RE = re.compile(r"^####\s+((?:IN|EX)-\d{2}[A-Za-z0-9_.-]*)\s+(.+?)\s*$", re.MULTILINE)
RULE_ID_RE = re.compile(r"^(?:IN|EX)-\d{2}[A-Za-z0-9_.-]*$")

VERDICT_LABELS = {
    "pass": "通过",
    "pass_verify": "通过（需验证）",
    "fail": "不通过",
    "insufficient": "证据不足",
    "investigator": "需研究者判定",
    "na": "不适用",
    "needs_evidence": "需补证",
    "not_reviewed": "未审核",
    "parse_error": "解析失败",
}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _as_datetime_from_mtime(path: Path) -> datetime:
    if path.exists():
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _as_display_time(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _safe_enum(value: str, enum_cls, fallback: str):
    normalized = str(value or "").strip() or fallback
    try:
        return enum_cls(normalized)
    except ValueError:
        return enum_cls(fallback)


def _phase_bundle_path(subject_dir: Path, phase_id: str) -> Path:
    if not phase_id or phase_id == "full":
        return subject_dir / "evidence_bundle.md"
    return subject_dir / f"evidence_bundle_{phase_id}.md"


def _phase_llm_dir(subject_dir: Path, phase_id: str) -> Path:
    if not phase_id or phase_id == "full":
        return subject_dir / "llm"
    return subject_dir / "llm" / phase_id


def _split_md_table_row(line: str) -> List[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", stripped)]


def _is_separator_row(line: str) -> bool:
    return bool(re.match(r"^\|\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?$", line.strip()))


def _map_rule_type(value: str, rule_id: str) -> EligibilityRuleType:
    if "入选" in value or str(rule_id).startswith("IN-"):
        return EligibilityRuleType.INCLUSION
    return EligibilityRuleType.EXCLUSION


def _map_verdict(value: str) -> str:
    text = re.sub(r"\s+", "", value or "")
    lower = text.lower()
    if any(marker in text for marker in ("通过（需验证", "通过需验证", "需溯源验证", "后续阶段复核", "后续阶段待复核")):
        return "pass_verify"
    if "❌" in text or "不通过" in text or "fail" in lower:
        return "fail"
    if "证据不足" in text or "insufficient" in lower:
        return "insufficient"
    if "需研究者" in text or "investigator" in lower:
        return "investigator"
    if "不适用" in text or text in {"—", "-", "－", "na"}:
        return "na"
    if "✅" in text or "通过" in text or "pass" in lower:
        return "pass"
    if "parse_error" in lower:
        return "parse_error"
    if "not_reviewed" in lower:
        return "not_reviewed"
    return "insufficient"


def _parse_overall_verdict(text: str) -> str:
    match = re.search(
        r"判定结果[：:]\s*(?:\*\*)?\s*(pass|fail|insufficient|investigator|needs_evidence|可入组|不可入组|证据不足|需研究者判定|需研究者|待补证)",
        text or "",
        re.IGNORECASE,
    )
    if match:
        value = match.group(1).strip().lower()
        if value in {"pass", "可入组"}:
            return "pass"
        if value in {"fail", "不可入组"}:
            return "fail"
        if value in {"insufficient", "证据不足"}:
            return "insufficient"
        if value in {"investigator", "需研究者判定", "需研究者"}:
            return "investigator"
        return "needs_evidence"
    if "❌" in text or "不可入组" in text or "明确不符合项" in text:
        return "fail"
    if "证据不足" in text:
        return "insufficient"
    if "需研究者" in text:
        return "investigator"
    if "✅" in text or "可入组" in text:
        return "pass"
    return ""


def _parse_summary(text: str) -> str:
    match = re.search(r"##\s*审核结论\s*(.*?)(?:\n---|\n##\s*逐条审核结果|\Z)", text or "", re.S)
    section = match.group(1).strip() if match else ""
    lines = []
    for raw in section.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.match(r"^\*\*[✅❌⚠️🟡—].*?\*\*$", line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _verification_type(verdict: str, reasoning: str) -> str:
    if verdict != "pass_verify":
        return ""
    text = reasoning or ""
    if "后续阶段" in text or "基线" in text or "D1" in text or "随机前" in text:
        return "future_phase"
    if "溯源" in text or "既往源" in text or "源文件" in text:
        return "source_traceability"
    return "other"


def _severity_for_verdict(verdict: str) -> RiskSeverity:
    if verdict == "fail":
        return RiskSeverity.HIGH
    if verdict in {"insufficient", "investigator"}:
        return RiskSeverity.MEDIUM
    return RiskSeverity.LOW


def _priority_for_overall(verdict: str) -> RiskSeverity:
    if verdict == "fail":
        return RiskSeverity.HIGH
    if verdict in {"insufficient", "investigator", "needs_evidence"}:
        return RiskSeverity.MEDIUM
    return RiskSeverity.LOW


class EnrollmentReviewAdapter:
    """Read-only adapter over the original enrollment-review-app project store."""

    def __init__(self, projects_dir: Optional[Path] = None):
        configured = os.environ.get("ENROLLMENT_REVIEW_PROJECTS_DIR", "")
        self.projects_dir = Path(configured) if configured else (projects_dir or DEFAULT_ENROLLMENT_PROJECTS_DIR)

    def resolve_project_code(self, project_id: str) -> str:
        requested = str(project_id or "").strip()
        code = PROJECT_CODE_ALIASES.get(requested, requested)
        if (self.projects_dir / code).exists():
            return code
        raise KeyError(project_id)

    def eligibility_dataset(
        self,
        project_id: str,
        subject_id: Optional[str] = None,
        phase_id: Optional[str] = None,
    ) -> EligibilityReviewDataset:
        code = self.resolve_project_code(project_id)
        project_dir = self.projects_dir / code
        config = _read_json(project_dir / "config.json", {})
        rules = self._criteria_rules(project_dir)
        phases = self._review_phases(project_dir)
        default_phase_id = self._default_phase_id(phases)
        selected_phase_id = phase_id or default_phase_id
        subject_rows = self._subject_rows(project_dir, code, phases)
        selected_subject_id = subject_id or self._default_subject_id(subject_rows)
        selected_candidate = (
            self._candidate(project_dir, code, config, phases, rules, selected_subject_id, selected_phase_id)
            if selected_subject_id
            else None
        )
        summary = self._summary(subject_rows, selected_candidate)
        stats = self._project_stats(subject_rows, rules)
        audit_summary = self._audit_summary(project_dir)

        return EligibilityReviewDataset(
            project_id=project_id,
            source_project_code=code,
            source_path=str(project_dir),
            protocol_id=str(config.get("protocol_id") or ""),
            protocol_version=str(config.get("protocol_version") or ""),
            study_stage=str(config.get("study_stage") or ""),
            active_phase_id=selected_phase_id,
            task_entry=EligibilityTaskEntry(
                source_project_code=code,
                default_phase_id=default_phase_id,
                selected_subject_id=selected_subject_id,
                selected_phase_id=selected_phase_id,
                source_project_path=str(project_dir),
            ),
            project_stats=stats,
            review_phases=phases,
            subject_rows=subject_rows,
            criteria_rules=rules,
            criteria_rule_ids=[rule.rule_id for rule in rules],
            generated_at=datetime.now(timezone.utc),
            summary=summary,
            candidates=[selected_candidate] if selected_candidate else [],
            selected_candidate=selected_candidate,
            audit_summary=audit_summary,
            available_actions=self._available_actions(code, selected_subject_id, selected_phase_id, selected_candidate),
        )

    def _criteria_rules(self, project_dir: Path) -> List[EligibilityRuleDefinition]:
        rules_path = project_dir / "criteria_rules.md"
        text = _read_text(rules_path)
        matches = list(RULE_HEADING_RE.finditer(text))
        rules: List[EligibilityRuleDefinition] = []
        for index, match in enumerate(matches):
            rule_id = match.group(1).strip()
            label = match.group(2).strip()
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            criterion_text = text[match.end():next_start].strip()
            rules.append(
                EligibilityRuleDefinition(
                    rule_id=rule_id,
                    rule_type=_map_rule_type("", rule_id),
                    rule_label=label,
                    criterion_text=criterion_text,
                    source_path=str(rules_path),
                )
            )
        return rules

    def _review_phases(self, project_dir: Path) -> List[EligibilityReviewPhase]:
        workflow = _read_json(project_dir / "review_phases.json", {})
        phases = workflow.get("review_phases") or []
        return [
            EligibilityReviewPhase(
                phase_id=str(item.get("phase_id") or "full"),
                name=str(item.get("name") or item.get("phase_id") or "全量审核"),
                stage=str(item.get("stage") or ""),
                study_stage=str(item.get("study_stage") or workflow.get("study_stage") or ""),
                visit=str(item.get("visit") or ""),
                study_week=str(item.get("study_week") or ""),
                day_window=str(item.get("day_window") or ""),
                description=str(item.get("description") or ""),
                required_items=[str(value) for value in item.get("required_items") or []],
                included_document_phases=[str(value) for value in item.get("included_document_phases") or []],
            )
            for item in phases
        ] or [EligibilityReviewPhase(phase_id="full", name="全量审核")]

    def _default_phase_id(self, phases: List[EligibilityReviewPhase]) -> str:
        non_full = [phase.phase_id for phase in phases if phase.phase_id != "full"]
        return non_full[-1] if non_full else phases[0].phase_id if phases else "full"

    def _default_subject_id(self, rows: List[EligibilitySubjectRow]) -> str:
        for row in rows:
            if row.report_exists:
                return row.subject_id
        return rows[0].subject_id if rows else ""

    def _subject_rows(
        self,
        project_dir: Path,
        code: str,
        phases: List[EligibilityReviewPhase],
    ) -> List[EligibilitySubjectRow]:
        subjects_dir = project_dir / "subjects"
        rows: List[EligibilitySubjectRow] = []
        if not subjects_dir.exists():
            return rows
        for subject_dir in sorted(path for path in subjects_dir.iterdir() if path.is_dir()):
            info = _read_json(subject_dir / "info.json", {})
            if not info:
                continue
            phase_reviews = {
                phase.phase_id: self._subject_phase_review(subject_dir, phase)
                for phase in phases
            }
            rows.append(
                EligibilitySubjectRow(
                    subject_id=str(info.get("subject_id") or subject_dir.name),
                    project_code=code,
                    center_code=str(info.get("center_code") or ""),
                    center_name=str(info.get("center_name") or ""),
                    status=str(info.get("status") or ""),
                    overall_verdict=str(info.get("overall_verdict") or ""),
                    doc_count=int(info.get("doc_count") or 0),
                    last_updated=str(info.get("last_updated") or ""),
                    icf_date=str(info.get("icf_date") or ""),
                    first_dosing_date=str(info.get("first_dosing_date") or ""),
                    birth_date=str(info.get("birth_date") or ""),
                    phase_reviews=phase_reviews,
                    evidence_bundle_exists=any(item.evidence_bundle_exists for item in phase_reviews.values()),
                    report_exists=any(item.has_report for item in phase_reviews.values()),
                    can_open_report=any(item.has_report for item in phase_reviews.values()),
                )
            )
        return rows

    def _subject_phase_review(self, subject_dir: Path, phase: EligibilityReviewPhase) -> EligibilitySubjectPhaseReview:
        report_dir = _phase_llm_dir(subject_dir, phase.phase_id)
        report_path = report_dir / "review_report.md"
        raw_path = report_dir / "review_raw.md"
        bundle_path = _phase_bundle_path(subject_dir, phase.phase_id)
        parse_path = report_path if report_path.exists() else raw_path if raw_path.exists() else None
        status = "not_reviewed"
        verdict = ""
        summary = ""
        updated_at = ""
        if parse_path:
            text = _read_text(parse_path)
            verdict = _parse_overall_verdict(text)
            summary = _parse_summary(text)
            status = "reviewed" if verdict else "parse_error"
            updated_at = _as_display_time(parse_path)
        return EligibilitySubjectPhaseReview(
            phase_id=phase.phase_id,
            name=phase.name,
            visit=phase.visit,
            day_window=phase.day_window,
            status=status,
            verdict=verdict,
            summary=summary,
            has_report=report_path.exists(),
            has_raw_response=raw_path.exists(),
            evidence_bundle_exists=bundle_path.exists(),
            report_path=str(report_path) if report_path.exists() else "",
            raw_response_path=str(raw_path) if raw_path.exists() else "",
            evidence_bundle_path=str(bundle_path) if bundle_path.exists() else "",
            updated_at=updated_at,
        )

    def _candidate(
        self,
        project_dir: Path,
        code: str,
        config: Dict[str, Any],
        phases: List[EligibilityReviewPhase],
        rules: List[EligibilityRuleDefinition],
        subject_id: str,
        phase_id: str,
    ) -> EligibilityCandidate:
        subject_dir = project_dir / "subjects" / subject_id
        info = _read_json(subject_dir / "info.json", {})
        phase_by_id = {phase.phase_id: phase for phase in phases}
        active_phase = phase_by_id.get(phase_id) or phases[-1]
        phase_reviews = [
            self._subject_phase_review(subject_dir, phase).model_dump(mode="json")
            for phase in phases
        ]
        rule_reviews = self._rule_reviews(subject_dir, active_phase, rules)
        missing_items = [item for rule in rule_reviews for item in rule.missing_information]
        medical_items = [item for rule in rule_reviews for item in rule.medical_confirmation]
        overall = str(info.get("overall_verdict") or "")
        phase_verdict = next((item.get("verdict") for item in phase_reviews if item.get("phase_id") == active_phase.phase_id), "")
        conclusion = overall or str(phase_verdict or "not_reviewed")
        key_findings = [
            f"{rule.rule_id} {rule.verdict_label}"
            for rule in rule_reviews
            if rule.verdict.value in {"fail", "insufficient", "investigator", "pass_verify"}
        ][:8]
        return EligibilityCandidate(
            candidate_id=f"{code}:{subject_id}",
            project_id=code,
            subject_id=subject_id,
            site_id=str(info.get("center_code") or ""),
            screening_number=subject_id,
            source_system="enrollment-review-app",
            source_project_code=code,
            source_path=str(subject_dir),
            study_stage=str(config.get("study_stage") or ""),
            active_phase_id=active_phase.phase_id,
            active_phase_label=active_phase.name,
            document_count=int(info.get("doc_count") or 0),
            phase_reviews=phase_reviews,
            status=_safe_enum(str(info.get("status") or ""), EligibilityCandidateStatus, "pending"),
            overall_conclusion=_safe_enum(conclusion, EligibilityOverallConclusion, "not_reviewed"),
            overall_rationale=phase_verdict or overall or "not_reviewed",
            review_priority=_priority_for_overall(conclusion),
            screening_visit_date=str(info.get("screening_date") or ""),
            key_findings=key_findings,
            rule_reviews=rule_reviews,
            missing_information=missing_items,
            medical_confirmation_items=medical_items,
        )

    def _rule_reviews(
        self,
        subject_dir: Path,
        phase: EligibilityReviewPhase,
        rules: List[EligibilityRuleDefinition],
    ) -> List[EligibilityRuleReview]:
        report_dir = _phase_llm_dir(subject_dir, phase.phase_id)
        report_path = report_dir / "review_report.md"
        raw_path = report_dir / "review_raw.md"
        parse_path = report_path if report_path.exists() else raw_path if raw_path.exists() else None
        if not parse_path:
            return []
        text = _read_text(parse_path)
        rules_by_id = {rule.rule_id: rule for rule in rules}
        reviewed_at = _as_datetime_from_mtime(parse_path)
        rows = self._parse_rule_table(text)
        results: List[EligibilityRuleReview] = []
        for row in rows:
            rule_id = row["rule_id"]
            definition = rules_by_id.get(rule_id)
            rule_type = definition.rule_type if definition else _map_rule_type(row.get("rule_type", ""), rule_id)
            verdict_value = row["verdict"]
            reasoning = row.get("reasoning", "")
            evidence = [
                EligibilityEvidence(
                    evidence_id=f"{subject_dir.name}_{phase.phase_id}_{rule_id}_report",
                    rule_id=rule_id,
                    source_type="review_report",
                    source_title=parse_path.name,
                    source_domain=phase.phase_id,
                    source_record_id=f"{subject_dir.name}:{phase.phase_id}:{rule_id}:review_report",
                    field_path=f"rule_results.{rule_id}",
                    quote=reasoning,
                    normalized_value=verdict_value,
                    collected_at=reviewed_at,
                )
            ]
            missing_items = []
            medical_items = []
            if verdict_value in {"insufficient", "needs_evidence"}:
                missing_items.append(self._action_item(subject_dir.name, phase.phase_id, rule_id, "missing_information", reasoning))
            if verdict_value == "investigator":
                medical_items.append(self._action_item(subject_dir.name, phase.phase_id, rule_id, "medical_confirmation", reasoning))
            results.append(
                EligibilityRuleReview(
                    rule_id=rule_id,
                    rule_type=rule_type,
                    rule_label=row.get("rule_label") or (definition.rule_label if definition else ""),
                    criterion_text=definition.criterion_text if definition else "",
                    verdict=_safe_enum(verdict_value, EligibilityRuleVerdict, "insufficient"),
                    verdict_label=VERDICT_LABELS.get(verdict_value, verdict_value),
                    severity=_severity_for_verdict(verdict_value),
                    rationale=reasoning,
                    evidence=evidence,
                    missing_information=missing_items,
                    medical_confirmation=medical_items,
                    reviewed_by="enrollment-review-app",
                    reviewed_at=reviewed_at,
                    source_phase_id=phase.phase_id,
                    source_phase_label=phase.name,
                    source_report_path=str(report_path) if report_path.exists() else "",
                    source_raw_path=str(raw_path) if raw_path.exists() else "",
                    verification_type=_verification_type(verdict_value, reasoning),
                )
            )
        return results

    def _parse_rule_table(self, text: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        in_table = False
        for line in (text or "").splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                if in_table:
                    break
                continue
            cells = _split_md_table_row(stripped)
            if len(cells) < 4:
                continue
            if "规则ID" in cells[0]:
                in_table = True
                continue
            if _is_separator_row(stripped) or not in_table:
                continue
            rule_id = cells[0].strip()
            if not RULE_ID_RE.match(rule_id):
                continue
            rows.append(
                {
                    "rule_id": rule_id,
                    "rule_label": cells[1].strip() if len(cells) > 1 else "",
                    "rule_type": cells[2].strip() if len(cells) > 2 else "",
                    "verdict": _map_verdict(cells[3].strip() if len(cells) > 3 else ""),
                    "reasoning": cells[4].strip() if len(cells) > 4 else "",
                }
            )
        return rows

    def _action_item(
        self,
        subject_id: str,
        phase_id: str,
        rule_id: str,
        item_type: str,
        detail: str,
    ) -> EligibilityActionItem:
        is_missing = item_type == "missing_information"
        return EligibilityActionItem(
            item_id=f"{subject_id}_{phase_id}_{rule_id}_{item_type}",
            rule_id=rule_id,
            item_type=item_type,
            severity=RiskSeverity.MEDIUM,
            title=f"{rule_id} {'需补充资料' if is_missing else '需医学确认'}",
            detail=detail,
            recommended_action="补充中心源文件/报告后复核。" if is_missing else "提交医学经理或研究者确认后再关闭。",
        )

    def _summary(
        self,
        rows: List[EligibilitySubjectRow],
        selected_candidate: Optional[EligibilityCandidate],
    ) -> EligibilityPoolSummary:
        status_counts = Counter(row.status or "unknown" for row in rows)
        verdict_counts = Counter(row.overall_verdict or "not_reviewed" for row in rows)
        rules_with_findings = []
        open_missing = 0
        open_medical = 0
        if selected_candidate:
            rules_with_findings = [
                rule.rule_id
                for rule in selected_candidate.rule_reviews
                if rule.verdict.value in {"fail", "insufficient", "investigator"}
            ]
            open_missing = len(selected_candidate.missing_information)
            open_medical = len(selected_candidate.medical_confirmation_items)
        return EligibilityPoolSummary(
            total_candidates=len(rows),
            counts_by_status=dict(status_counts),
            counts_by_overall_conclusion=dict(verdict_counts),
            rules_with_findings=rules_with_findings,
            open_missing_information_count=open_missing,
            open_medical_confirmation_count=open_medical,
        )

    def _project_stats(
        self,
        rows: List[EligibilitySubjectRow],
        rules: List[EligibilityRuleDefinition],
    ) -> EligibilityProjectStats:
        phase_status_counts = Counter(
            review.status
            for row in rows
            for review in row.phase_reviews.values()
        )
        return EligibilityProjectStats(
            total_subjects=len(rows),
            counts_by_status=dict(Counter(row.status or "unknown" for row in rows)),
            counts_by_overall_verdict=dict(Counter(row.overall_verdict or "not_reviewed" for row in rows)),
            counts_by_phase_status=dict(phase_status_counts),
            subjects_with_reports=sum(1 for row in rows if row.report_exists),
            subjects_with_evidence_bundles=sum(1 for row in rows if row.evidence_bundle_exists),
            criteria_rule_count=len(rules),
        )

    def _audit_summary(self, project_dir: Path) -> EligibilityAuditSummary:
        ledger = project_dir / "audit_ledger.jsonl"
        events: List[Dict[str, Any]] = []
        if ledger.exists():
            for line in ledger.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return EligibilityAuditSummary(
            audit_ledger_path=str(ledger) if ledger.exists() else "",
            event_count=len(events),
            recent_events=[_sanitize_audit_event(event) for event in events[-10:]],
        )

    def _available_actions(
        self,
        code: str,
        subject_id: str,
        phase_id: str,
        selected_candidate: Optional[EligibilityCandidate],
    ) -> List[EligibilityAvailableAction]:
        actions = [
            EligibilityAvailableAction(
                action_id="open_original_project",
                label="打开原入排项目",
                target_type="project",
                target_id=code,
                metadata={"source_system": "enrollment-review-app"},
            )
        ]
        if subject_id:
            actions.append(
                EligibilityAvailableAction(
                    action_id="open_subject_folder",
                    label="查看受试者源文件夹",
                    target_type="subject",
                    target_id=subject_id,
                    metadata={"phase_id": phase_id},
                )
            )
        if selected_candidate and selected_candidate.rule_reviews:
            actions.append(
                EligibilityAvailableAction(
                    action_id="review_selected_phase_report",
                    label="查看当前时点审核报告",
                    target_type="phase_review",
                    target_id=f"{subject_id}:{phase_id}",
                    metadata={"rule_count": len(selected_candidate.rule_reviews)},
                )
            )
        return actions


def _sanitize_audit_event(value):
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered == "path" or lowered == "run_log" or lowered.endswith("_path"):
                continue
            clean[key] = _sanitize_audit_event(item)
        return clean
    if isinstance(value, list):
        return [_sanitize_audit_event(item) for item in value]
    if isinstance(value, str) and "/Users/" in value:
        return "[本地路径已隐藏]"
    return value
