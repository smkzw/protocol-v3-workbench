from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
import re
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from .monitoring_protocol_rules import (
    INITIAL_RELEASE_RULE_FAMILIES,
    MonitoringProtocolRuleError,
    MonitoringRuleDefinition,
    ProtocolFact,
    ProtocolSourceVersion,
    RulePackImpact,
    RuleDiagnosticCase,
    RuleFamilyCoverageSnapshot,
    RuleGoldStandardCase,
    RuleReReviewTask,
    RuleRevisionCoverageSnapshot,
    RuleRiskBinding,
    RuleShadowCaseResult,
    RuleShadowDiagnosticResult,
    RuleShadowRun,
    build_re_review_tasks,
    compare_rule_packs,
    diagnostic_case_set_content_sha256,
    gold_case_set_content_sha256,
)
from .protocol_text_extractor import ProtocolTextDocument


@dataclass(frozen=True)
class ProtocolAmendmentChange:
    source_locator: str
    section: str
    before_text: str
    after_text: str
    reason: str
    subject_impact: str

    def public_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RuleEvaluationResult:
    rule_key: str
    rule_revision_id: str
    matched: bool
    preconditions_met: bool
    excluded: bool
    missing_required_domains: tuple[str, ...]
    evidence: dict[str, Any]
    evidence_summary: str
    protocol_source: dict[str, str]

    def public_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["missing_required_domains"] = list(self.missing_required_domains)
        return value


class RuleEvaluationNotSupported(MonitoringProtocolRuleError):
    pass


@dataclass(frozen=True)
class RuleShadowValidationRun(RuleShadowRun):
    case_source: str = "repository_registered"
    trusted_for_release: bool = True
    release_gate_eligible: bool = True
    persisted: bool = True
    trust_boundary: str = (
        "Only repository-registered gold cases are eligible for release evidence."
    )
    repository_support_required: bool = False


class MonitoringProtocolRuleService:
    def __init__(
        self,
        repository: MonitoringProtocolRuleRepository,
        *,
        risk_binding_validator: Optional[
            Callable[[RuleRiskBinding], bool]
        ] = None,
    ):
        self.repository = repository
        self._risk_binding_validator = risk_binding_validator

    def compare_packs(
        self,
        previous_rule_pack_id: str,
        current_rule_pack_id: str,
    ) -> RulePackImpact:
        previous_pack, previous_rules = self.repository.rule_pack(
            previous_rule_pack_id
        )
        current_pack, current_rules = self.repository.rule_pack(
            current_rule_pack_id
        )
        return compare_rule_packs(
            previous_pack,
            previous_rules,
            current_pack,
            current_rules,
        )

    def schedule_re_reviews(
        self,
        *,
        previous_rule_pack_id: str,
        current_rule_pack_id: str,
        risk_bindings: Iterable[RuleRiskBinding],
    ) -> tuple[RuleReReviewTask, ...]:
        previous_pack, previous_rules = self.repository.rule_pack(
            previous_rule_pack_id
        )
        current_pack, current_rules = self.repository.rule_pack(
            current_rule_pack_id
        )
        if previous_pack.project_id != current_pack.project_id:
            raise MonitoringProtocolRuleError(
                "rule packs from different projects cannot be compared"
            )
        previous_by_key = {rule.rule_key: rule for rule in previous_rules}
        trusted_bindings = tuple(risk_bindings)
        if trusted_bindings and self._risk_binding_validator is None:
            raise MonitoringProtocolRuleError(
                "risk binding validator is not configured"
            )
        for binding in trusted_bindings:
            if binding.project_id != previous_pack.project_id:
                raise MonitoringProtocolRuleError(
                    "risk binding belongs to another project"
                )
            previous_rule = previous_by_key.get(binding.rule_key)
            if previous_rule is None:
                raise MonitoringProtocolRuleError(
                    "risk binding rule is not present in the previous rule pack"
                )
            if (
                binding.evaluated_rule_revision_id
                != previous_rule.rule_revision_id
            ):
                raise MonitoringProtocolRuleError(
                    "risk binding rule revision is not present in the previous rule pack"
                )
            if not self._risk_binding_validator(binding):
                raise MonitoringProtocolRuleError(
                    "risk binding is not present in the trusted risk repository"
                )
        impact = compare_rule_packs(
            previous_pack,
            previous_rules,
            current_pack,
            current_rules,
        )
        tasks = build_re_review_tasks(
            impact,
            current_rules,
            trusted_bindings,
        )
        return self.repository.store_re_review_tasks(tasks)

    def evaluate_record(
        self,
        rule: MonitoringRuleDefinition,
        record: Mapping[str, Any],
        *,
        observed_domains: Iterable[str],
        previous_record: Optional[Mapping[str, Any]] = None,
        related_records: Optional[Mapping[str, Sequence[Mapping[str, Any]]]] = None,
        allow_non_enabled: bool = False,
        validation_mode: str = "production",
    ) -> RuleEvaluationResult:
        _validate_rule_execution_status(
            rule,
            allow_non_enabled=allow_non_enabled,
            validation_mode=validation_mode,
        )
        if rule.executor not in {"field_predicate", "cross_record", "temporal"}:
            raise RuleEvaluationNotSupported(
                f"rule executor requires medical review: {rule.executor}"
            )
        domains = {str(item).strip().upper() for item in observed_domains}
        supplied_related_records = related_records or {}
        related_domain_keys = {
            str(key).strip().upper()
            for key in supplied_related_records
            if str(key).strip()
        }
        normalized_related_records = {
            str(key).strip().upper(): [dict(item) for item in value]
            for key, value in supplied_related_records.items()
            if str(key).strip()
        }
        missing_domains = tuple(
            sorted(set(rule.required_domains) - domains)
        )
        if missing_domains:
            evidence = _structured_record_evidence(
                rule,
                record=dict(record),
                previous_record=dict(previous_record or {}),
                related_records=normalized_related_records,
                observed_domains=domains,
                related_domain_keys=related_domain_keys,
            )
            missing_evidence = _current_record_missing_evidence(record)
            evidence.update(
                {
                    "evidence_ready": not missing_evidence,
                    "missing_evidence": missing_evidence,
                    "evaluation_state": "indeterminate",
                    "diagnostic_code": "missing_required_domains",
                    "medical_review_candidate_only": True,
                }
            )
            return RuleEvaluationResult(
                rule_key=rule.rule_key,
                rule_revision_id=rule.rule_revision_id,
                matched=False,
                preconditions_met=False,
                excluded=False,
                missing_required_domains=missing_domains,
                evidence=evidence,
                evidence_summary=(
                    "关键数据域缺失，未执行规则："
                    + "、".join(missing_domains)
                ),
                protocol_source=_protocol_source(rule),
            )
        context = {
            "record": dict(record),
            "previous_record": dict(previous_record or {}),
            "related_records": normalized_related_records,
            "related_domain_keys": related_domain_keys,
            "observed_domains": domains,
        }
        _, precondition_trace = _evaluate_predicate_with_trace(
            rule.preconditions,
            context,
        )
        precondition_state = _predicate_trace_state(precondition_trace)
        preconditions_met = precondition_state == "true"
        if preconditions_met:
            _, exclusion_trace = _evaluate_predicate_with_trace(
                rule.exclusions,
                context,
            )
        else:
            exclusion_trace = {
                "operator": "not_evaluated",
                "result": False,
                "state": "indeterminate",
                "reason": "preconditions_not_met",
            }
        exclusion_state = _predicate_trace_state(exclusion_trace)
        excluded = exclusion_state == "true"
        if preconditions_met and exclusion_state == "false":
            _, trigger_trace = _evaluate_predicate_with_trace(
                rule.trigger_expression,
                context,
            )
        else:
            trigger_trace = {
                "operator": "not_evaluated",
                "result": False,
                "state": "indeterminate",
                "reason": (
                    "excluded"
                    if excluded
                    else (
                        "exclusion_indeterminate"
                        if exclusion_state == "indeterminate"
                        else "preconditions_not_met"
                    )
                ),
            }
        trigger_state = _predicate_trace_state(trigger_trace)
        predicate_matched = (
            precondition_state == "true"
            and exclusion_state == "false"
            and trigger_state == "true"
        )
        evaluation_state = _overall_evaluation_state(
            precondition_state=precondition_state,
            exclusion_state=exclusion_state,
            trigger_state=trigger_state,
        )
        evidence_fields = sorted(
            _predicate_fields(rule.preconditions)
            | _predicate_fields(rule.trigger_expression)
            | _predicate_fields(rule.exclusions)
        )
        evidence_fields_values = {
            field_name: _field_value(context["record"], field_name)
            for field_name in evidence_fields
            if _field_value(context["record"], field_name) not in (None, "")
        }
        evidence = {
            **evidence_fields_values,
            **_structured_record_evidence(
                rule,
                record=context["record"],
                previous_record=context["previous_record"],
                related_records=context["related_records"],
                observed_domains=domains,
                related_domain_keys=related_domain_keys,
            ),
            "predicate_trace": {
                "preconditions": precondition_trace,
                "exclusions": exclusion_trace,
                "trigger": trigger_trace,
            },
        }
        missing_evidence = _evaluation_missing_evidence(
            context=context,
            precondition_trace=precondition_trace,
            exclusion_trace=exclusion_trace,
            trigger_trace=trigger_trace,
        )
        evidence_ready = not missing_evidence
        matched = predicate_matched and evidence_ready
        if predicate_matched and not evidence_ready:
            evaluation_state = "indeterminate"
        diagnostic_code = ""
        if evaluation_state == "indeterminate":
            diagnostic_code = (
                "missing_source_evidence"
                if missing_evidence
                else "indeterminate_predicate"
            )
        evidence.update(
            {
                "evidence_ready": evidence_ready,
                "missing_evidence": missing_evidence,
                "evaluation_state": evaluation_state,
                "diagnostic_code": diagnostic_code,
                "predicate_matched_before_evidence_gate": predicate_matched,
                "medical_review_candidate_only": True,
                "evidence_gate": {
                    "passed": evidence_ready,
                    "required_for_match": True,
                    "missing_evidence": missing_evidence,
                },
            }
        )
        if matched:
            summary = _render_evidence_template(
                rule.evidence_template,
                context["record"],
            )
        elif predicate_matched and not evidence_ready:
            summary = (
                "规则条件满足，但原始证据定位不完整，"
                "已按关闭原则阻止形成医学复核候选。"
            )
        elif evaluation_state == "indeterminate":
            summary = (
                "关键输入缺失、无效或搜索范围不完整，"
                "规则结果不确定，未形成医学复核候选。"
            )
        else:
            summary = "当前记录未满足该规则的确定性触发条件。"
        return RuleEvaluationResult(
            rule_key=rule.rule_key,
            rule_revision_id=rule.rule_revision_id,
            matched=matched,
            preconditions_met=preconditions_met,
            excluded=excluded,
            missing_required_domains=(),
            evidence=evidence,
            evidence_summary=summary,
            protocol_source=_protocol_source(rule),
        )

    def current_rule_pack(
        self,
        project_id: str,
        *,
        as_of: str,
    ) -> dict[str, Any]:
        pack, rules = self.repository.current_published_pack(
            project_id,
            as_of=as_of,
        )
        return {
            "pack": pack.public_dict(),
            "rules": [rule.public_dict() for rule in rules],
        }

    def run_shadow_validation(
        self,
        *,
        rule_pack_id: str,
        batch_id: str,
        cases: Sequence[RuleGoldStandardCase] | None = None,
        diagnostic_cases: Sequence[RuleDiagnosticCase] | None = None,
    ) -> RuleShadowValidationRun:
        external_cases = cases is not None or diagnostic_cases is not None
        if external_cases:
            selected_cases = tuple(cases or ())
            selected_diagnostic_cases = tuple(diagnostic_cases or ())
            rule_coverages: Sequence[RuleRevisionCoverageSnapshot] = ()
            family_coverages: Sequence[RuleFamilyCoverageSnapshot] = ()
        else:
            (
                selected_cases,
                selected_diagnostic_cases,
                rule_coverages,
                family_coverages,
            ) = self.repository.shadow_case_sets(rule_pack_id)
        run = self._build_shadow_run(
            rule_pack_id=rule_pack_id,
            batch_id=batch_id,
            selected_cases=selected_cases,
            selected_diagnostic_cases=selected_diagnostic_cases,
            rule_coverages=rule_coverages,
            family_coverages=family_coverages,
            external_cases=external_cases,
        )
        if external_cases:
            return _shadow_validation_run_with_trust(
                run,
                case_source="external_development",
                trusted_for_release=False,
                release_gate_eligible=False,
                persisted=False,
                trust_boundary=(
                    "Externally supplied cases are untrusted development inputs "
                    "and cannot be used as release-gate evidence."
                ),
                repository_support_required=True,
            )
        stored = self.repository.store_shadow_run(run)
        return self.trusted_shadow_run_view(stored)

    @staticmethod
    def trusted_shadow_run_view(run: RuleShadowRun) -> RuleShadowValidationRun:
        return _shadow_validation_run_with_trust(
            run,
            case_source="repository_registered",
            trusted_for_release=True,
            release_gate_eligible=_p7c_release_gate_eligible(run),
            persisted=True,
            trust_boundary=(
                "Only repository-registered gold cases are eligible for "
                "release evidence."
            ),
            repository_support_required=False,
        )

    def compute_repository_shadow_run(
        self,
        *,
        rule_pack_id: str,
        batch_id: str,
        additional_gold_cases: Sequence[RuleGoldStandardCase] = (),
        additional_diagnostic_cases: Sequence[RuleDiagnosticCase] = (),
    ) -> RuleShadowRun:
        """Compute the trusted shadow run as if the additional cases were
        already repository-registered.

        Pure read plus in-memory evaluation over the merged case set:
        nothing is persisted. The atomic confirmation commit stores the
        promoted cases and this exact run in a single transaction.
        """
        existing_gold, existing_diagnostic, _rule_cov, _family_cov = (
            self.repository.shadow_case_sets(rule_pack_id)
        )
        merged_gold = tuple(
            sorted(
                (*existing_gold, *additional_gold_cases),
                key=lambda item: item.case_id,
            )
        )
        merged_diagnostic = tuple(
            sorted(
                (*existing_diagnostic, *additional_diagnostic_cases),
                key=lambda item: item.case_id,
            )
        )
        rule_coverages, family_coverages = (
            self.repository.shadow_coverage_snapshots_for_cases(
                rule_pack_id, merged_gold, merged_diagnostic
            )
        )
        return self._build_shadow_run(
            rule_pack_id=rule_pack_id,
            batch_id=batch_id,
            selected_cases=merged_gold,
            selected_diagnostic_cases=merged_diagnostic,
            rule_coverages=rule_coverages,
            family_coverages=family_coverages,
            external_cases=False,
        )

    def _build_shadow_run(
        self,
        *,
        rule_pack_id: str,
        batch_id: str,
        selected_cases: Sequence[RuleGoldStandardCase],
        selected_diagnostic_cases: Sequence[RuleDiagnosticCase],
        rule_coverages: Sequence[RuleRevisionCoverageSnapshot],
        family_coverages: Sequence[RuleFamilyCoverageSnapshot],
        external_cases: bool,
    ) -> RuleShadowRun:
        pack, rules = self.repository.rule_pack(rule_pack_id)
        rule_by_key = {rule.rule_key: rule for rule in rules}
        if not selected_cases:
            raise MonitoringProtocolRuleError(
                "shadow validation requires gold standard cases"
            )
        foreign_case_ids = sorted(
            case.case_id
            for case in selected_cases
            if case.project_id != pack.project_id
        )
        if foreign_case_ids:
            raise MonitoringProtocolRuleError(
                "gold standard cases belong to another project: "
                f"{foreign_case_ids}"
            )
        unknown_rules = sorted(
            {
                case.rule_key
                for case in selected_cases
                if case.rule_key not in rule_by_key
            }
        )
        if unknown_rules:
            raise MonitoringProtocolRuleError(
                f"gold standard cases reference rules outside the pack: {unknown_rules}"
            )
        wrong_revision_case_ids = sorted(
            case.case_id
            for case in selected_cases
            if case.rule_revision_id
            != rule_by_key[case.rule_key].rule_revision_id
        )
        if wrong_revision_case_ids:
            raise MonitoringProtocolRuleError(
                "gold standard cases reference a different rule revision: "
                f"{wrong_revision_case_ids}"
            )
        foreign_diagnostic_case_ids = sorted(
            case.case_id
            for case in selected_diagnostic_cases
            if case.project_id != pack.project_id
        )
        if foreign_diagnostic_case_ids:
            raise MonitoringProtocolRuleError(
                "diagnostic cases belong to another project: "
                f"{foreign_diagnostic_case_ids}"
            )
        unknown_diagnostic_rules = sorted(
            {
                case.rule_key
                for case in selected_diagnostic_cases
                if case.rule_key not in rule_by_key
            }
        )
        if unknown_diagnostic_rules:
            raise MonitoringProtocolRuleError(
                "diagnostic cases reference rules outside the pack: "
                f"{unknown_diagnostic_rules}"
            )
        wrong_diagnostic_revision_ids = sorted(
            case.case_id
            for case in selected_diagnostic_cases
            if case.rule_revision_id
            != rule_by_key[case.rule_key].rule_revision_id
        )
        if wrong_diagnostic_revision_ids:
            raise MonitoringProtocolRuleError(
                "diagnostic cases reference a different rule revision: "
                f"{wrong_diagnostic_revision_ids}"
            )
        non_executable_rules = sorted(
            rule.rule_key
            for rule in rules
            if rule.status not in {"enabled", "confirmed"}
        )
        if non_executable_rules:
            raise MonitoringProtocolRuleError(
                "shadow validation permits only enabled or confirmed rules; "
                f"non-executable rules: {non_executable_rules}"
            )
        results: list[RuleShadowCaseResult] = []
        for case in selected_cases:
            case_record = dict(case.input_record)
            if (
                not _record_source_locators(case_record)
                and case.evidence_locators
            ):
                case_record["evidence_span_ids"] = list(
                    case.evidence_locators
                )
            evaluation = self.evaluate_record(
                rule_by_key[case.rule_key],
                case_record,
                observed_domains=case.observed_domains,
                previous_record=case.previous_record,
                related_records=case.related_records,
                allow_non_enabled=True,
                validation_mode="shadow",
            )
            evaluation_state = str(
                evaluation.evidence.get("evaluation_state") or ""
            ).strip().lower()
            determinate_case = evaluation_state in {"true", "false"}
            release_eligible_case = (
                not external_cases
                and evaluation.evidence.get("evidence_ready") is True
                and determinate_case
            )
            trust_note = (
                "trust=repository_registered; release_gate_eligible="
                f"{str(release_eligible_case).lower()}"
                if not external_cases
                else (
                    "trust=untrusted_external; release_gate_eligible=false; "
                    "repository_registration_required_for_release=true"
                )
            )
            results.append(
                RuleShadowCaseResult(
                    case_id=case.case_id,
                    rule_key=case.rule_key,
                    rule_revision_id=case.rule_revision_id,
                    expected_match=case.expected_match,
                    actual_match=evaluation.matched,
                    passed=(
                        evaluation.matched == case.expected_match
                        and determinate_case
                        and (
                            evaluation.evidence.get("evidence_ready") is True
                            if not external_cases
                            else True
                        )
                    ),
                    evidence_summary=(
                        f"[{trust_note}] {evaluation.evidence_summary}"
                    ),
                )
            )
        diagnostic_results: list[RuleShadowDiagnosticResult] = []
        for case in selected_diagnostic_cases:
            case_record = dict(case.input_record)
            if (
                not _record_source_locators(case_record)
                and case.evidence_locators
            ):
                case_record["evidence_span_ids"] = list(
                    case.evidence_locators
                )
            evaluation = self.evaluate_record(
                rule_by_key[case.rule_key],
                case_record,
                observed_domains=case.observed_domains,
                previous_record=case.previous_record,
                related_records=case.related_records,
                allow_non_enabled=True,
                validation_mode="shadow",
            )
            actual_state = str(
                evaluation.evidence.get("evaluation_state") or ""
            ).strip().lower()
            actual_code = str(
                evaluation.evidence.get("diagnostic_code") or ""
            ).strip().lower()
            passed = (
                actual_state == "indeterminate"
                and actual_code == case.expected_diagnostic_code
            )
            diagnostic_results.append(
                RuleShadowDiagnosticResult(
                    case_id=case.case_id,
                    rule_key=case.rule_key,
                    rule_revision_id=case.rule_revision_id,
                    expected_diagnostic_category=(
                        case.expected_diagnostic_category
                    ),
                    expected_diagnostic_code=(
                        case.expected_diagnostic_code
                    ),
                    actual_state=actual_state,
                    actual_diagnostic_code=actual_code,
                    passed=passed,
                    evidence_summary=evaluation.evidence_summary,
                )
            )
        run = RuleShadowRun.create(
            project_id=pack.project_id,
            rule_pack_id=pack.rule_pack_id,
            batch_id=batch_id,
            results=results,
            case_set_content_sha256=gold_case_set_content_sha256(
                selected_cases
            ),
            diagnostic_results=diagnostic_results,
            diagnostic_case_set_sha256=(
                diagnostic_case_set_content_sha256(
                    selected_diagnostic_cases
                )
            ),
            rule_coverages=rule_coverages,
            family_coverages=family_coverages,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return run


def extract_protocol_amendment_changes(
    document: ProtocolTextDocument,
) -> tuple[ProtocolAmendmentChange, ...]:
    candidates: list[tuple[int, Any, dict[str, int]]] = []
    for table in document.tables:
        if not table.rows:
            continue
        headers = [
            _normalized_cell_text(cell.text)
            for cell in table.rows[0]
        ]
        indexes = _amendment_header_indexes(headers)
        if {"before", "after"}.issubset(indexes):
            candidates.append((len(table.rows), table, indexes))
    if not candidates:
        raise MonitoringProtocolRuleError(
            "protocol amendment comparison table was not found"
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, table, indexes = candidates[0]
    changes: list[ProtocolAmendmentChange] = []
    for row_index, row in enumerate(table.rows[1:], start=1):
        values = [_normalized_cell_text(cell.text) for cell in row]
        before = _cell_at(values, indexes.get("before"))
        after = _cell_at(values, indexes.get("after"))
        if not before and not after:
            continue
        changes.append(
            ProtocolAmendmentChange(
                source_locator=f"docx:table:{table.table_index}:row:{row_index}",
                section=_cell_at(values, indexes.get("section")),
                before_text=before,
                after_text=after,
                reason=_cell_at(values, indexes.get("reason")),
                subject_impact=_cell_at(values, indexes.get("impact")),
            )
        )
    if not changes:
        raise MonitoringProtocolRuleError(
            "protocol amendment table contains no comparison rows"
        )
    return tuple(changes)


def protocol_version_from_registered_source(
    *,
    project_id: str,
    protocol_code: str,
    version_label: str,
    version_date: str,
    registration: Any,
    applicability_status: str = "version_date_only",
    operational_effective_from: str = "",
    operational_effective_to: str = "",
    predecessor_version_id: str = "",
    amendment_source_entry_id: str = "",
) -> ProtocolSourceVersion:
    entry = registration.entry
    if entry.project_id != project_id:
        raise MonitoringProtocolRuleError(
            "registered protocol source belongs to another project"
        )
    return ProtocolSourceVersion.create(
        project_id=project_id,
        protocol_code=protocol_code,
        version_label=version_label,
        version_date=version_date,
        source_entry_id=entry.entry_id,
        source_title=entry.public_title,
        content_sha256=entry.content_hash,
        applicability_status=applicability_status,
        operational_effective_from=operational_effective_from,
        operational_effective_to=operational_effective_to,
        predecessor_version_id=predecessor_version_id,
        amendment_source_entry_id=amendment_source_entry_id,
    )


def confirmed_fact_from_amendment_change(
    *,
    version: ProtocolSourceVersion,
    amendment_source_entry_id: str,
    change: ProtocolAmendmentChange,
    fact_key: str,
    fact_type: str,
    title: str,
    normalized_payload: Mapping[str, Any],
    applicability: Mapping[str, Any] | None = None,
    supersedes_fact_revision_id: str = "",
) -> ProtocolFact:
    if not change.after_text:
        raise MonitoringProtocolRuleError(
            "confirmed amendment fact requires non-empty revised text"
        )
    return ProtocolFact.create(
        project_id=version.project_id,
        protocol_version_id=version.protocol_version_id,
        fact_key=fact_key,
        fact_type=fact_type,
        status="medically_confirmed",
        title=title,
        normalized_payload=normalized_payload,
        source_entry_id=amendment_source_entry_id,
        source_locator=change.source_locator,
        source_text=change.after_text,
        applicability=applicability,
        supersedes_fact_revision_id=supersedes_fact_revision_id,
    )


def _validate_rule_execution_status(
    rule: MonitoringRuleDefinition,
    *,
    allow_non_enabled: bool,
    validation_mode: str,
) -> None:
    normalized_mode = str(validation_mode or "").strip().lower()
    if normalized_mode not in {"production", "shadow"}:
        raise MonitoringProtocolRuleError(
            "validation_mode must be 'production' or 'shadow'"
        )
    if allow_non_enabled and normalized_mode != "shadow":
        raise MonitoringProtocolRuleError(
            "allow_non_enabled is permitted only in shadow validation mode"
        )
    if rule.status == "enabled":
        return
    if (
        rule.status == "confirmed"
        and allow_non_enabled
        and normalized_mode == "shadow"
    ):
        return
    if rule.status == "candidate":
        raise MonitoringProtocolRuleError(
            "candidate rules cannot be executed"
        )
    raise MonitoringProtocolRuleError(
        "rule evaluation requires status=enabled; "
        "only confirmed rules may run in explicit shadow validation mode"
    )


def _shadow_validation_run_with_trust(
    run: RuleShadowRun,
    *,
    case_source: str,
    trusted_for_release: bool,
    release_gate_eligible: bool,
    persisted: bool,
    trust_boundary: str,
    repository_support_required: bool,
) -> RuleShadowValidationRun:
    return RuleShadowValidationRun(
        shadow_run_id=run.shadow_run_id,
        project_id=run.project_id,
        rule_pack_id=run.rule_pack_id,
        batch_id=run.batch_id,
        status=run.status,
        case_count=run.case_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        results=run.results,
        case_set_content_sha256=run.case_set_content_sha256,
        completed_at=run.completed_at,
        diagnostic_case_count=run.diagnostic_case_count,
        diagnostic_passed_count=run.diagnostic_passed_count,
        diagnostic_failed_count=run.diagnostic_failed_count,
        diagnostic_results=run.diagnostic_results,
        diagnostic_case_set_content_sha256=(
            run.diagnostic_case_set_content_sha256
        ),
        diagnostic_results_content_sha256=(
            run.diagnostic_results_content_sha256
        ),
        rule_coverages=run.rule_coverages,
        family_coverages=run.family_coverages,
        coverage_content_sha256=run.coverage_content_sha256,
        case_source=case_source,
        trusted_for_release=trusted_for_release,
        release_gate_eligible=release_gate_eligible,
        persisted=persisted,
        trust_boundary=trust_boundary,
        repository_support_required=repository_support_required,
    )


def _p7c_release_gate_eligible(run: RuleShadowRun) -> bool:
    if (
        not run.rule_coverages
        or not all(result.passed for result in run.results)
        or not all(result.passed for result in run.diagnostic_results)
    ):
        return False
    if any(
        coverage.positive_count < 1
        or coverage.negative_count < 1
        or coverage.boundary_count < 1
        or coverage.diagnostic_indeterminate_count < 1
        or len(coverage.authoritative_projects) < 1
        for coverage in run.rule_coverages
    ):
        return False
    family_projects = {
        coverage.rule_family: coverage.authoritative_projects
        for coverage in run.family_coverages
    }
    return all(
        coverage.rule_family not in INITIAL_RELEASE_RULE_FAMILIES
        or len(family_projects.get(coverage.rule_family, ())) >= 2
        for coverage in run.rule_coverages
    )


def _amendment_header_indexes(headers: Sequence[str]) -> dict[str, int]:
    aliases = {
        "section": ("修订后章节", "章节", "页码"),
        "before": ("修改前", "修订前"),
        "after": ("修改后", "修订后"),
        "reason": ("修改原因", "修订原因"),
        "impact": ("对受试者安全性", "临床获益", "受试者影响"),
    }
    output: dict[str, int] = {}
    for key, tokens in aliases.items():
        for token in tokens:
            match = next(
                (
                    index
                    for index, header in enumerate(headers)
                    if token in header
                ),
                None,
            )
            if match is not None:
                output[key] = match
                break
    return output


def _normalized_cell_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cell_at(values: Sequence[str], index: Optional[int]) -> str:
    if index is None or index >= len(values):
        return ""
    return values[index]


def _protocol_source(rule: MonitoringRuleDefinition) -> dict[str, str]:
    return {
        "source_entry_id": rule.source_entry_id,
        "source_locator": rule.source_locator,
        "source_text": rule.source_text,
        "primary_summary": f"方案原文：{rule.source_text}",
    }


def _structured_record_evidence(
    rule: MonitoringRuleDefinition,
    *,
    record: Mapping[str, Any],
    previous_record: Mapping[str, Any],
    related_records: Mapping[str, Sequence[Mapping[str, Any]]],
    observed_domains: Iterable[str],
    related_domain_keys: Iterable[str],
) -> dict[str, Any]:
    observed_domain_set = {
        str(item).strip().upper()
        for item in observed_domains
        if str(item).strip()
    }
    supplied_domain_set = {
        str(item).strip().upper()
        for item in related_domain_keys
        if str(item).strip()
    }
    related = {
        domain: [
            _record_evidence(item)
            for item in records
        ]
        for domain, records in sorted(related_records.items())
    }
    missing_queries = _missing_record_queries(
        (
            rule.preconditions,
            rule.trigger_expression,
            rule.exclusions,
        ),
        related_records,
        record,
        observed_domains=observed_domain_set,
        related_domain_keys=supplied_domain_set,
    )
    current_subject = _first_field_value(
        record,
        ("SUBJID", "USUBJID", "subject_id", "受试者编号"),
    )
    return {
        "current_record": _record_evidence(record),
        "previous_record": (
            _record_evidence(previous_record)
            if previous_record
            else None
        ),
        "related_records": related,
        "missing_record_queries": missing_queries,
        "search_scope": {
            "subject_id": current_subject,
            "observed_domains": sorted(observed_domain_set),
            "supplied_related_domains": sorted(supplied_domain_set),
            "complete_related_domains": sorted(
                observed_domain_set & supplied_domain_set
            ),
            "related_record_counts": {
                domain: len(records)
                for domain, records in sorted(related_records.items())
            },
            "scope_basis": "supplied_subject_related_records",
        },
    }


def _record_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    raw = dict(record)
    return {
        "raw_data": raw,
        "source_locators": _record_source_locators(raw),
    }


def _record_source_locators(record: Mapping[str, Any]) -> list[Any]:
    locators: list[Any] = []
    for key in (
        "source_locator",
        "__source_locator__",
        "SOURCE_LOCATOR",
        "locator",
        "evidence_span_ids",
    ):
        value = _field_value(record, key)
        if value in (None, "", [], {}):
            continue
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if item not in locators:
                locators.append(item)
    return locators


def _missing_record_queries(
    expressions: Iterable[Mapping[str, Any]],
    related_records: Mapping[str, Sequence[Mapping[str, Any]]],
    current_record: Optional[Mapping[str, Any]] = None,
    *,
    observed_domains: Iterable[str] = (),
    related_domain_keys: Iterable[str] = (),
) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    observed_domain_set = {
        str(item).strip().upper()
        for item in observed_domains
        if str(item).strip()
    }
    supplied_domain_set = {
        str(item).strip().upper()
        for item in related_domain_keys
        if str(item).strip()
    }
    for expression in expressions:
        for operand in _predicate_operands(
            expression,
            "no_corresponding_record",
        ):
            domain = str(operand.get("domain", "")).strip().upper()
            field_name = str(operand.get("field", "")).strip()
            expected = operand.get("value")
            _, trace = _evaluate_no_corresponding_record(
                operand,
                {
                    "record": current_record or {},
                    "related_records": related_records,
                    "related_domain_keys": supplied_domain_set,
                    "observed_domains": observed_domain_set,
                },
            )
            if "field" in operand:
                queries.append(
                    {
                        "domain": domain,
                        "match_field": field_name,
                        "expected_value": expected,
                        "searched_record_count": trace[
                            "searched_record_count"
                        ],
                        "matching_record_count": trace[
                            "matching_record_count"
                        ],
                        "missing": trace["state"] == "true",
                        "searched_source_locators": trace[
                            "searched_source_locators"
                        ],
                    }
                )
                continue
            query = {
                "domain": domain,
                "match_field": field_name,
                "expected_value": expected,
                "state": trace["state"],
                "missing": trace["state"] == "true",
                "query_ready": trace["query_ready"],
                "search_domain_complete": trace["search_domain_complete"],
                "domain_observed": trace["domain_observed"],
                "domain_supplied": trace["domain_supplied"],
                "searched_record_count": trace["searched_record_count"],
                "matching_record_count": trace["matching_record_count"],
                "indeterminate_record_count": trace[
                    "indeterminate_record_count"
                ],
                "searched_source_locators": trace[
                    "searched_source_locators"
                ],
                "matching_source_locators": trace[
                    "matching_source_locators"
                ],
                "missing_current_fields": trace["missing_current_fields"],
                "invalid_current_fields": trace["invalid_current_fields"],
                "row_evaluations": trace["row_evaluations"],
                "unmatched_reasons": trace["unmatched_reasons"],
                "search_set_locator": trace["search_set_locator"],
            }
            if "match" in operand or "date_window" in operand:
                query["matching_conditions"] = (
                    _related_matching_conditions(
                        operand,
                        current_record or {},
                    )
                )
            queries.append(query)
    return queries


def _predicate_operands(
    expression: Mapping[str, Any],
    target_operator: str,
) -> list[Mapping[str, Any]]:
    operator, operand = next(iter(expression.items()))
    if operator in {"all", "any"}:
        return [
            match
            for item in operand
            for match in _predicate_operands(item, target_operator)
        ]
    if operator == "not":
        return _predicate_operands(operand, target_operator)
    if operator == target_operator:
        return [operand]
    return []


def _first_field_value(
    record: Mapping[str, Any],
    field_names: Sequence[str],
) -> Any:
    for field_name in field_names:
        value = _field_value(record, field_name)
        if value not in (None, ""):
            return value
    return ""


def _evaluate_predicate(
    expression: Mapping[str, Any],
    context: Mapping[str, Any],
) -> bool:
    return _evaluate_predicate_with_trace(expression, context)[0]


def _evaluate_predicate_with_trace(
    expression: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    operator, operand = next(iter(expression.items()))
    if operator == "all":
        children = [
            _evaluate_predicate_with_trace(item, context)
            for item in operand
        ]
        child_states = [
            _predicate_trace_state(trace)
            for _, trace in children
        ]
        state = (
            "false"
            if "false" in child_states
            else (
                "indeterminate"
                if "indeterminate" in child_states
                else "true"
            )
        )
        result = state == "true"
        return result, {
            "operator": operator,
            "result": result,
            "state": state,
            "unmatched_reason": (
                ""
                if state == "true"
                else (
                    "child_indeterminate"
                    if state == "indeterminate"
                    else "one_or_more_children_false"
                )
            ),
            "children": [trace for _, trace in children],
        }
    if operator == "any":
        children = [
            _evaluate_predicate_with_trace(item, context)
            for item in operand
        ]
        child_states = [
            _predicate_trace_state(trace)
            for _, trace in children
        ]
        state = (
            "true"
            if "true" in child_states
            else (
                "indeterminate"
                if "indeterminate" in child_states
                else "false"
            )
        )
        result = state == "true"
        return result, {
            "operator": operator,
            "result": result,
            "state": state,
            "unmatched_reason": (
                ""
                if state == "true"
                else (
                    "child_indeterminate"
                    if state == "indeterminate"
                    else "no_child_true"
                )
            ),
            "children": [trace for _, trace in children],
        }
    if operator == "not":
        _, child_trace = _evaluate_predicate_with_trace(
            operand,
            context,
        )
        child_state = _predicate_trace_state(child_trace)
        state = {
            "true": "false",
            "false": "true",
            "indeterminate": "indeterminate",
        }[child_state]
        result = state == "true"
        return result, {
            "operator": operator,
            "result": result,
            "state": state,
            "indeterminate": state == "indeterminate",
            "unmatched_reason": (
                ""
                if state == "true"
                else (
                    "child_indeterminate"
                    if state == "indeterminate"
                    else "negated_child_true"
                )
            ),
            "children": [child_trace],
        }
    record = context["record"]
    if operator == "no_corresponding_record":
        return _evaluate_no_corresponding_record(operand, context)
    field_name = str(operand.get("field", "")).strip()
    current = _field_value(record, field_name)
    if operator == "exists":
        result = current not in (None, "")
        return result, _field_trace(
            operator,
            result,
            field_name,
            current,
            state=_bool_state(result),
        )
    if operator == "missing":
        result = current in (None, "")
        return result, _field_trace(
            operator,
            result,
            field_name,
            current,
            state=_bool_state(result),
        )
    if operator == "changed":
        previous = _field_value(context["previous_record"], field_name)
        if _missing_value(current) or _missing_value(previous):
            trace = _field_trace(
                operator,
                False,
                field_name,
                current,
                state="indeterminate",
            )
            trace.update(
                {
                    "previous_value": previous,
                    "calculation_status": (
                        "missing_previous_value"
                        if _missing_value(previous)
                        else "missing_current_value"
                    ),
                    "unmatched_reason": "comparison_input_missing",
                }
            )
            return False, trace
        result = current != previous
        trace = _field_trace(
            operator,
            result,
            field_name,
            current,
            state=_bool_state(result),
        )
        trace["previous_value"] = previous
        return result, trace
    expected = operand.get("value")
    if operator in {"eq", "ne", "in", "not_in"}:
        if _missing_value(current):
            return False, _indeterminate_comparison_trace(
                operator,
                field_name,
                current,
                expected,
                "missing_field_value",
            )
        if _non_finite_value(current) or _non_finite_value(expected):
            return False, _indeterminate_comparison_trace(
                operator,
                field_name,
                current,
                expected,
                "non_finite_operand",
            )
        if operator in {"eq", "ne"} and _missing_value(expected):
            return False, _indeterminate_comparison_trace(
                operator,
                field_name,
                current,
                expected,
                "missing_expected_value",
            )
        if operator in {"in", "not_in"} and not isinstance(expected, list):
            return False, _indeterminate_comparison_trace(
                operator,
                field_name,
                current,
                expected,
                "invalid_expected_collection",
            )
        if operator == "eq":
            result = current == expected
        elif operator == "ne":
            result = current != expected
        elif operator == "in":
            result = current in expected
        else:
            result = current not in expected
        return result, _comparison_trace(
            operator,
            result,
            field_name,
            current,
            expected,
            state=_bool_state(result),
        )
    if operator == "regex":
        if _missing_value(current):
            return False, _indeterminate_comparison_trace(
                operator,
                field_name,
                current,
                expected,
                "missing_field_value",
            )
        try:
            result = bool(
                re.search(
                    str(expected),
                    str(current),
                    flags=re.IGNORECASE,
                )
            )
        except re.error:
            return False, _indeterminate_comparison_trace(
                operator,
                field_name,
                current,
                expected,
                "invalid_regex",
            )
        return result, _comparison_trace(
            operator,
            result,
            field_name,
            current,
            expected,
            state=_bool_state(result),
        )
    if operator in {"gt", "gte", "lt", "lte"}:
        left = _number(current)
        right = _number(expected)
        if left is None or right is None:
            return False, {
                **_comparison_trace(
                    operator,
                    False,
                    field_name,
                    current,
                    expected,
                    state="indeterminate",
                ),
                "calculation_status": "non_numeric_operand",
                "unmatched_reason": "numeric_comparison_indeterminate",
            }
        result = {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
        }[operator]
        return result, {
            **_comparison_trace(
                operator,
                result,
                field_name,
                current,
                expected,
                state=_bool_state(result),
            ),
            "computed_left": left,
            "computed_right": right,
            "calculation_status": "calculated",
        }
    if operator == "date_compare":
        other_field = str(operand.get("other_field", "")).strip()
        relation = str(operand.get("relation", "")).strip()
        left_date = _date_value(current)
        right_value = _field_value(record, other_field)
        right_date = _date_value(right_value)
        if left_date is None or right_date is None:
            return False, {
                "operator": operator,
                "result": False,
                "state": "indeterminate",
                "field": field_name,
                "field_value": current,
                "other_field": other_field,
                "other_field_value": right_value,
                "relation": relation,
                "computed_delta_days": None,
                "calculation_status": "invalid_date_operand",
                "unmatched_reason": "date_comparison_indeterminate",
            }
        delta_days = (left_date - right_date).days
        result = {
            "before": delta_days < 0,
            "before_or_equal": delta_days <= 0,
            "same": delta_days == 0,
            "after_or_equal": delta_days >= 0,
            "after": delta_days > 0,
        }[relation]
        return result, {
            "operator": operator,
            "result": result,
            "state": _bool_state(result),
            "field": field_name,
            "field_value": current,
            "other_field": other_field,
            "other_field_value": right_value,
            "relation": relation,
            "computed_delta_days": delta_days,
            "calculation_status": "calculated",
            "unmatched_reason": (
                "" if result else "date_relation_not_met"
            ),
        }
    if operator == "date_delta_days":
        other_field = str(operand.get("other_field", "")).strip()
        days = _number(operand.get("value"))
        if not other_field or days is None:
            return False, {
                "operator": operator,
                "result": False,
                "state": "indeterminate",
                "calculation_status": "invalid_configuration",
                "unmatched_reason": "date_calculation_indeterminate",
            }
        left_date = _date_value(current)
        right_value = _field_value(record, other_field)
        right_date = _date_value(right_value)
        if left_date is None or right_date is None:
            return False, {
                "operator": operator,
                "result": False,
                "state": "indeterminate",
                "field": field_name,
                "field_value": current,
                "other_field": other_field,
                "other_field_value": right_value,
                "computed_absolute_delta_days": None,
                "threshold_days": days,
                "calculation_status": "invalid_date_operand",
                "unmatched_reason": "date_calculation_indeterminate",
            }
        delta = abs((left_date - right_date).days)
        result = delta > days
        return result, {
            "operator": operator,
            "result": result,
            "state": _bool_state(result),
            "field": field_name,
            "field_value": current,
            "other_field": other_field,
            "other_field_value": right_value,
            "computed_absolute_delta_days": delta,
            "threshold_days": days,
            "calculation_status": "calculated",
            "unmatched_reason": (
                "" if result else "date_delta_threshold_not_met"
            ),
        }
    if operator == "date_delta_range":
        other_field = str(operand.get("other_field", "")).strip()
        left_date = _date_value(current)
        right_value = _field_value(record, other_field)
        right_date = _date_value(right_value)
        minimum = _number(operand.get("min_days")) if "min_days" in operand else None
        maximum = _number(operand.get("max_days")) if "max_days" in operand else None
        if (
            left_date is None
            or right_date is None
            or ("min_days" in operand and minimum is None)
            or ("max_days" in operand and maximum is None)
        ):
            return False, {
                "operator": operator,
                "result": False,
                "state": "indeterminate",
                "field": field_name,
                "field_value": current,
                "other_field": other_field,
                "other_field_value": right_value,
                "computed_delta_days": None,
                "accepted_range": {
                    "min_days": minimum,
                    "max_days": maximum,
                },
                "calculation_status": "invalid_date_operand",
                "unmatched_reason": "date_calculation_indeterminate",
            }
        delta = (left_date - right_date).days
        result = (
            (minimum is None or delta >= minimum)
            and (maximum is None or delta <= maximum)
        )
        return result, {
            "operator": operator,
            "result": result,
            "state": _bool_state(result),
            "field": field_name,
            "field_value": current,
            "other_field": other_field,
            "other_field_value": right_value,
            "computed_delta_days": delta,
            "accepted_range": {
                "min_days": minimum,
                "max_days": maximum,
            },
            "calculation_status": "calculated",
            "unmatched_reason": (
                "" if result else "date_delta_outside_range"
            ),
        }
    if operator == "ratio_range":
        numerator_field = str(operand.get("numerator_field", "")).strip()
        denominator_field = str(operand.get("denominator_field", "")).strip()
        numerator_value = _field_value(record, numerator_field)
        denominator_value = _field_value(record, denominator_field)
        numerator = _number(numerator_value)
        denominator = _number(denominator_value)
        multiplier = _number(operand.get("multiplier"))
        minimum = _number(operand.get("min_value"))
        maximum = _number(operand.get("max_value"))
        calculated = (
            numerator is not None
            and denominator is not None
            and denominator != 0
            and multiplier is not None
            and minimum is not None
            and maximum is not None
        )
        ratio: Optional[float] = None
        if calculated:
            ratio = numerator / denominator * multiplier
            if not math.isfinite(ratio):
                calculated = False
                ratio = None
        result = ratio is not None and minimum <= ratio <= maximum
        calculation_status = "calculated"
        if not calculated:
            calculation_status = (
                "invalid_or_zero_denominator"
                if denominator is None or denominator == 0
                else "invalid_ratio_operand"
            )
        return result, {
            "operator": operator,
            "result": result,
            "state": (
                _bool_state(result)
                if calculated
                else "indeterminate"
            ),
            "numerator_field": numerator_field,
            "numerator_value": numerator_value,
            "denominator_field": denominator_field,
            "denominator_value": denominator_value,
            "multiplier": multiplier,
            "computed_ratio": ratio,
            "accepted_range": {
                "min_value": minimum,
                "max_value": maximum,
            },
            "calculation_status": calculation_status,
            "unmatched_reason": (
                (
                    "" if result else "ratio_outside_range"
                )
                if calculated
                else "ratio_calculation_indeterminate"
            ),
        }
    raise RuleEvaluationNotSupported(f"unsupported predicate operator: {operator}")


def _field_trace(
    operator: str,
    result: bool,
    field_name: str,
    value: Any,
    *,
    state: str,
) -> dict[str, Any]:
    return {
        "operator": operator,
        "result": result,
        "state": state,
        "field": field_name,
        "field_value": value,
        "unmatched_reason": (
            ""
            if state == "true"
            else (
                "predicate_indeterminate"
                if state == "indeterminate"
                else "predicate_false"
            )
        ),
    }


def _predicate_trace_is_indeterminate(trace: Mapping[str, Any]) -> bool:
    return _predicate_trace_state(trace) == "indeterminate"


def _predicate_trace_state(trace: Mapping[str, Any]) -> str:
    state = str(trace.get("state", "")).strip().lower()
    if state in {"true", "false", "indeterminate"}:
        return state
    if trace.get("query_ready") is False:
        return "indeterminate"
    status = str(trace.get("calculation_status", ""))
    if status and status != "calculated":
        return "indeterminate"
    return _bool_state(trace.get("result") is True)


def _bool_state(result: bool) -> str:
    return "true" if result else "false"


def _missing_value(value: Any) -> bool:
    return value in (None, "")


def _non_finite_value(value: Any) -> bool:
    if isinstance(value, bool) or isinstance(value, (list, tuple, dict)):
        return False
    if isinstance(value, (int, float)):
        return not math.isfinite(float(value))
    text = str(value).strip().lower()
    return text in {
        "nan",
        "+nan",
        "-nan",
        "inf",
        "+inf",
        "-inf",
        "infinity",
        "+infinity",
        "-infinity",
    }


def _comparison_trace(
    operator: str,
    result: bool,
    field_name: str,
    value: Any,
    expected: Any,
    *,
    state: str,
) -> dict[str, Any]:
    return {
        **_field_trace(
            operator,
            result,
            field_name,
            value,
            state=state,
        ),
        "expected_value": expected,
    }


def _indeterminate_comparison_trace(
    operator: str,
    field_name: str,
    value: Any,
    expected: Any,
    reason: str,
) -> dict[str, Any]:
    return {
        **_comparison_trace(
            operator,
            False,
            field_name,
            value,
            expected,
            state="indeterminate",
        ),
        "calculation_status": reason,
        "unmatched_reason": reason,
    }


def _overall_evaluation_state(
    *,
    precondition_state: str,
    exclusion_state: str,
    trigger_state: str,
) -> str:
    if precondition_state == "false" or exclusion_state == "true":
        return "false"
    if (
        precondition_state == "indeterminate"
        or exclusion_state == "indeterminate"
        or trigger_state == "indeterminate"
    ):
        return "indeterminate"
    return trigger_state


def _evaluate_no_corresponding_record(
    operand: Mapping[str, Any],
    context: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    record = context["record"]
    domain = str(operand.get("domain", "")).strip().upper()
    related_records = context.get("related_records", {})
    related = list(related_records.get(domain, ()))
    supplied_domains = {
        str(item).strip().upper()
        for item in context.get(
            "related_domain_keys",
            related_records.keys(),
        )
        if str(item).strip()
    }
    observed_domains = {
        str(item).strip().upper()
        for item in context.get("observed_domains", ())
        if str(item).strip()
    }
    domain_supplied = domain in supplied_domains
    domain_observed = domain in observed_domains
    search_domain_complete = domain_supplied and domain_observed
    missing_query_inputs = _missing_related_query_inputs(
        operand,
        record,
    )
    invalid_query_inputs = _invalid_related_query_inputs(
        operand,
        record,
    )
    query_ready = (
        search_domain_complete
        and not missing_query_inputs
        and not invalid_query_inputs
    )
    row_traces: list[dict[str, Any]] = []
    matching: list[Mapping[str, Any]] = []
    indeterminate_count = 0
    if query_ready:
        for row_index, item in enumerate(related):
            is_match, row_trace = _related_record_matches(
                item,
                record,
                operand,
            )
            row_trace["row_index"] = row_index
            row_traces.append(row_trace)
            row_state = _predicate_trace_state(row_trace)
            if is_match:
                matching.append(item)
            elif row_state == "indeterminate":
                indeterminate_count += 1
    if not query_ready:
        state = "indeterminate"
    elif matching:
        state = "false"
    elif indeterminate_count:
        state = "indeterminate"
    else:
        state = "true"
    result = state == "true"
    unmatched_reasons = [
        {
            "row_index": trace["row_index"],
            "state": trace["state"],
            "reasons": trace.get("unmatched_reasons", []),
        }
        for trace in row_traces
        if trace["state"] != "true"
    ]
    current_locators = _record_source_locators(record)
    return result, {
        "operator": "no_corresponding_record",
        "result": result,
        "state": state,
        "domain": domain,
        "query_ready": query_ready,
        "search_domain_complete": search_domain_complete,
        "domain_observed": domain_observed,
        "domain_supplied": domain_supplied,
        "missing_current_fields": missing_query_inputs,
        "invalid_current_fields": invalid_query_inputs,
        "matching_conditions": _related_matching_conditions(
            operand,
            record,
        ),
        "searched_record_count": len(related),
        "matching_record_count": len(matching),
        "indeterminate_record_count": indeterminate_count,
        "matching_source_locators": [
            locator
            for item in matching
            for locator in _record_source_locators(item)
        ],
        "searched_source_locators": [
            locator
            for item in related
            for locator in _record_source_locators(item)
        ],
        "row_evaluations": row_traces,
        "unmatched_reasons": unmatched_reasons,
        "search_set_locator": {
            "domain": domain,
            "current_record_source_locators": current_locators,
            "matching_conditions": _related_matching_conditions(
                operand,
                record,
            ),
        },
    }


def _related_record_matches(
    related_record: Mapping[str, Any],
    current_record: Mapping[str, Any],
    operand: Mapping[str, Any],
) -> tuple[bool, dict[str, Any]]:
    legacy_field = str(operand.get("field", "")).strip()
    if legacy_field:
        conditions = [
            {
                "related_field": legacy_field,
                "value": operand.get("value"),
                "operator": "eq",
            }
        ]
    else:
        conditions = list(operand.get("match", ()))
    condition_results: list[dict[str, Any]] = []
    for condition in conditions:
        related_field = str(condition.get("related_field", "")).strip()
        operator = str(condition.get("operator", "eq")).strip()
        actual = _field_value(related_record, related_field)
        current_field = str(condition.get("current_field", "")).strip()
        expected = (
            _field_value(current_record, current_field)
            if current_field
            else condition.get("value")
        )
        state, unmatched_reason = _safe_related_comparison(
            operator,
            actual,
            expected,
        )
        matched = state == "true"
        condition_results.append(
            {
                "related_field": related_field,
                "related_value": actual,
                "operator": operator,
                "current_field": current_field,
                "expected_value": expected,
                "matched": matched,
                "state": state,
                "calculation_status": (
                    "evaluated"
                    if state != "indeterminate"
                    else unmatched_reason
                ),
                "unmatched_reason": unmatched_reason,
            }
        )
    date_trace: Optional[dict[str, Any]] = None
    date_window = operand.get("date_window")
    if isinstance(date_window, Mapping):
        related_field = str(
            date_window.get("related_date_field", "")
        ).strip()
        current_field = str(
            date_window.get("current_date_field", "")
        ).strip()
        related_value = _field_value(related_record, related_field)
        current_value = _field_value(current_record, current_field)
        related_date = _date_value(related_value)
        current_date = _date_value(current_value)
        delta = (
            (related_date - current_date).days
            if related_date is not None and current_date is not None
            else None
        )
        minimum = (
            _number(date_window.get("min_days"))
            if "min_days" in date_window
            else None
        )
        maximum = (
            _number(date_window.get("max_days"))
            if "max_days" in date_window
            else None
        )
        date_ready = (
            delta is not None
            and (
                "min_days" not in date_window
                or minimum is not None
            )
            and (
                "max_days" not in date_window
                or maximum is not None
            )
        )
        date_match = (
            date_ready
            and (minimum is None or delta >= minimum)
            and (maximum is None or delta <= maximum)
        )
        date_state = (
            _bool_state(bool(date_match))
            if date_ready
            else "indeterminate"
        )
        date_trace = {
            "related_date_field": related_field,
            "related_date_value": related_value,
            "current_date_field": current_field,
            "current_date_value": current_value,
            "computed_delta_days": delta,
            "accepted_range": {
                "min_days": minimum,
                "max_days": maximum,
            },
            "matched": bool(date_match),
            "state": date_state,
            "calculation_status": (
                "calculated"
                if date_ready
                else "invalid_date_operand"
            ),
            "unmatched_reason": (
                ""
                if date_match
                else (
                    "outside_date_window"
                    if date_ready
                    else "date_window_indeterminate"
                )
            ),
        }
    component_states = [
        item["state"] for item in condition_results
    ]
    if date_trace is not None:
        component_states.append(date_trace["state"])
    state = (
        "false"
        if "false" in component_states
        else (
            "indeterminate"
            if "indeterminate" in component_states
            else "true"
        )
    )
    matched = state == "true"
    unmatched_reasons = [
        item["unmatched_reason"]
        for item in condition_results
        if item["unmatched_reason"]
    ]
    if date_trace and date_trace["unmatched_reason"]:
        unmatched_reasons.append(date_trace["unmatched_reason"])
    return matched, {
        "operator": "related_record_match",
        "result": matched,
        "state": state,
        "matched": matched,
        "conditions": condition_results,
        "date_window": date_trace,
        "source_locators": _record_source_locators(related_record),
        "unmatched_reasons": unmatched_reasons,
    }


def _missing_related_query_inputs(
    operand: Mapping[str, Any],
    current_record: Mapping[str, Any],
) -> list[str]:
    required: list[str] = []
    for condition in operand.get("match", ()):
        current_field = str(condition.get("current_field", "")).strip()
        if current_field and current_field not in required:
            required.append(current_field)
    date_window = operand.get("date_window")
    if isinstance(date_window, Mapping):
        current_date_field = str(
            date_window.get("current_date_field", "")
        ).strip()
        if current_date_field and current_date_field not in required:
            required.append(current_date_field)
    return [
        field_name
        for field_name in required
        if _field_value(current_record, field_name) in (None, "")
    ]


def _invalid_related_query_inputs(
    operand: Mapping[str, Any],
    current_record: Mapping[str, Any],
) -> list[str]:
    invalid: list[str] = []
    date_window = operand.get("date_window")
    if isinstance(date_window, Mapping):
        current_date_field = str(
            date_window.get("current_date_field", "")
        ).strip()
        current_value = _field_value(
            current_record,
            current_date_field,
        )
        if (
            current_date_field
            and current_value not in (None, "")
            and _date_value(current_value) is None
        ):
            invalid.append(current_date_field)
    return invalid


def _safe_related_comparison(
    operator: str,
    actual: Any,
    expected: Any,
) -> tuple[str, str]:
    if operator == "exists":
        result = actual not in (None, "")
        return _bool_state(result), "" if result else "related_value_missing"
    if operator == "missing":
        result = actual in (None, "")
        return _bool_state(result), "" if result else "related_value_present"
    if _missing_value(actual) or (
        operator not in {"exists", "missing"}
        and _missing_value(expected)
    ):
        return "indeterminate", "comparison_input_missing"
    if _non_finite_value(actual) or _non_finite_value(expected):
        return "indeterminate", "non_finite_operand"
    if operator == "eq":
        result = actual == expected
        return _bool_state(result), "" if result else "values_not_equal"
    if operator == "ne":
        result = actual != expected
        return _bool_state(result), "" if result else "values_equal"
    if operator == "in":
        if not isinstance(expected, list):
            return "indeterminate", "invalid_expected_collection"
        result = actual in expected
        return _bool_state(result), "" if result else "value_not_in_collection"
    if operator == "not_in":
        if not isinstance(expected, list):
            return "indeterminate", "invalid_expected_collection"
        result = actual not in expected
        return _bool_state(result), "" if result else "value_in_collection"
    if operator == "regex":
        try:
            result = bool(
                re.search(
                    str(expected),
                    str(actual),
                    flags=re.IGNORECASE,
                )
            )
        except re.error:
            return "indeterminate", "invalid_regex"
        return _bool_state(result), "" if result else "regex_not_matched"
    return "indeterminate", "unsupported_related_operator"


def _current_record_missing_evidence(
    record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if _record_source_locators(record):
        return []
    return [
        {
            "kind": "current_record_locator",
            "reason": "missing_stable_locator",
        }
    ]


def _evaluation_missing_evidence(
    *,
    context: Mapping[str, Any],
    precondition_trace: Mapping[str, Any],
    exclusion_trace: Mapping[str, Any],
    trigger_trace: Mapping[str, Any],
) -> list[dict[str, Any]]:
    missing = _current_record_missing_evidence(context["record"])
    trace_requirements = (
        (precondition_trace, _predicate_trace_state(precondition_trace)),
        (exclusion_trace, _predicate_trace_state(exclusion_trace)),
        (trigger_trace, _predicate_trace_state(trigger_trace)),
    )
    for trace, required_state in trace_requirements:
        if trace.get("operator") == "not_evaluated":
            continue
        _collect_trace_missing_evidence(
            trace,
            required_state=required_state,
            context=context,
            missing=missing,
        )
    unique: list[dict[str, Any]] = []
    for item in missing:
        if item not in unique:
            unique.append(item)
    return unique


def _collect_trace_missing_evidence(
    trace: Mapping[str, Any],
    *,
    required_state: str,
    context: Mapping[str, Any],
    missing: list[dict[str, Any]],
) -> None:
    operator = str(trace.get("operator", ""))
    children = [
        child
        for child in trace.get("children", ())
        if isinstance(child, Mapping)
    ]
    if operator == "all":
        selected = (
            children
            if required_state == "true"
            else [
                child
                for child in children
                if _predicate_trace_state(child) == required_state
            ]
        )
        for child in selected:
            _collect_trace_missing_evidence(
                child,
                required_state=_predicate_trace_state(child),
                context=context,
                missing=missing,
            )
        return
    if operator == "any":
        selected = (
            children
            if required_state == "false"
            else [
                child
                for child in children
                if _predicate_trace_state(child) == required_state
            ]
        )
        for child in selected:
            _collect_trace_missing_evidence(
                child,
                required_state=_predicate_trace_state(child),
                context=context,
                missing=missing,
            )
        return
    if operator == "not":
        for child in children:
            _collect_trace_missing_evidence(
                child,
                required_state=_predicate_trace_state(child),
                context=context,
                missing=missing,
            )
        return
    if operator == "changed":
        previous_record = context.get("previous_record", {})
        if not _record_source_locators(previous_record):
            missing.append(
                {
                    "kind": "previous_record_locator",
                    "field": trace.get("field", ""),
                    "reason": "missing_stable_locator",
                }
            )
        return
    if operator != "no_corresponding_record":
        return
    domain = str(trace.get("domain", ""))
    row_traces = [
        row
        for row in trace.get("row_evaluations", ())
        if isinstance(row, Mapping)
    ]
    if required_state == "true":
        required_rows = row_traces
    elif required_state == "false":
        required_rows = [
            row
            for row in row_traces
            if _predicate_trace_state(row) == "true"
        ]
    else:
        required_rows = [
            row
            for row in row_traces
            if _predicate_trace_state(row) == "indeterminate"
        ]
    for row in required_rows:
        if row.get("source_locators"):
            continue
        missing.append(
            {
                "kind": "related_record_locator",
                "domain": domain,
                "row_index": row.get("row_index"),
                "reason": "missing_stable_locator",
            }
        )
    search_set_locator = trace.get("search_set_locator", {})
    if (
        required_state == "true"
        and (
            not isinstance(search_set_locator, Mapping)
            or not search_set_locator.get(
                "current_record_source_locators"
            )
        )
    ):
        missing.append(
            {
                "kind": "related_search_set_locator",
                "domain": domain,
                "reason": "missing_stable_search_anchor",
            }
        )


def _related_matching_conditions(
    operand: Mapping[str, Any],
    current_record: Mapping[str, Any],
) -> dict[str, Any]:
    legacy_field = str(operand.get("field", "")).strip()
    if legacy_field:
        matches = [
            {
                "related_field": legacy_field,
                "operator": "eq",
                "expected_value": operand.get("value"),
            }
        ]
    else:
        matches = []
        for condition in operand.get("match", ()):
            current_field = str(condition.get("current_field", "")).strip()
            matches.append(
                {
                    "related_field": condition.get("related_field"),
                    "operator": condition.get("operator", "eq"),
                    "current_field": current_field,
                    "expected_value": (
                        _field_value(current_record, current_field)
                        if current_field
                        else condition.get("value")
                    ),
                }
            )
    return {
        "match": matches,
        "date_window": dict(operand.get("date_window", {})),
    }


def _field_value(record: Mapping[str, Any], field_name: str) -> Any:
    if field_name in record:
        return record[field_name]
    upper = field_name.upper()
    for key, value in record.items():
        if str(key).upper() == upper:
            return value
    return None


def _number(value: Any) -> Optional[float]:
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _date_value(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(
            text[:-1] + "+00:00"
            if text.endswith("Z")
            else text
        )
    except ValueError:
        return None
    return datetime(parsed.year, parsed.month, parsed.day)


def _predicate_fields(expression: Mapping[str, Any]) -> set[str]:
    operator, operand = next(iter(expression.items()))
    if operator in {"all", "any"}:
        return set().union(*(_predicate_fields(item) for item in operand))
    if operator == "not":
        return _predicate_fields(operand)
    fields = {
        str(operand.get(key, "")).strip()
        for key in (
            "field",
            "numerator_field",
            "denominator_field",
        )
    }
    other = str(operand.get("other_field", "")).strip()
    if other:
        fields.add(other)
    for condition in operand.get("match", ()):
        current_field = str(condition.get("current_field", "")).strip()
        if current_field:
            fields.add(current_field)
    date_window = operand.get("date_window")
    if isinstance(date_window, Mapping):
        current_date_field = str(
            date_window.get("current_date_field", "")
        ).strip()
        if current_date_field:
            fields.add(current_date_field)
    return {item for item in fields if item}


class _SafeFormatValues(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "-"


def _render_evidence_template(
    template: str,
    record: Mapping[str, Any],
) -> str:
    values = _SafeFormatValues(
        {
            str(key): value
            for key, value in record.items()
        }
    )
    try:
        return template.format_map(values)
    except (ValueError, KeyError):
        return template
