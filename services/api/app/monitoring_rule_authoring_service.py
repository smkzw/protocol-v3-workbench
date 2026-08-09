from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Any, Iterable, Mapping, Sequence

from .monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiJobStatus,
    MonitoringAiTaskType,
)
from .monitoring_ai_repository import MonitoringAiRepository
from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRecordNotFound,
    MonitoringProtocolRuleRepository,
    MonitoringProtocolStateConflictError,
)
from .monitoring_protocol_rule_service import MonitoringProtocolRuleService
from .monitoring_protocol_rules import (
    PROTOCOL_FACT_TYPES,
    MonitoringRuleDefinition,
    MonitoringRulePack,
    ProtocolApplicabilityAssignment,
    ProtocolApplicabilityResolution,
    ProtocolFact,
    ProtocolSourceVersion,
    RuleDiagnosticCase,
    RuleGoldStandardCase,
    ShadowSampleMedicalConfirmation,
)
from .monitoring_rule_lifecycle_service import MonitoringRuleLifecycleService
from .monitoring_rule_templates import (
    TEMPLATE_PAYLOAD_KEY,
    compile_monitoring_rule_template,
)


class MonitoringRuleAuthoringError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _exact_sha256_pair(left: Any, right: Any) -> bool:
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and re.fullmatch(r"[0-9a-f]{64}", left) is not None
        and re.fullmatch(r"[0-9a-f]{64}", right) is not None
        and left == right
    )


@dataclass(frozen=True)
class ShadowConfirmationOutcome:
    """Result of one confirm-shadow act.

    `confirmation` is the immutable medical confirmation record when the act
    promoted a provisional sample set; it is None for the legacy path that
    confirms a preregistered trusted shadow run directly.
    """

    pack: MonitoringRulePack
    confirmation: ShadowSampleMedicalConfirmation | None
    shadow_run_id: str


class MonitoringRuleAuthoringService:
    """Strict product boundary from accepted AI clauses to published rules."""

    def __init__(
        self,
        *,
        repository: MonitoringProtocolRuleRepository,
        lifecycle_service: MonitoringRuleLifecycleService,
        protocol_rule_service: MonitoringProtocolRuleService,
        ai_repository: MonitoringAiRepository,
        source_registry: Any,
    ):
        self.repository = repository
        self.lifecycle_service = lifecycle_service
        self.protocol_rule_service = protocol_rule_service
        self.ai_repository = ai_repository
        self.source_registry = source_registry
        self._shadow_sample_service: Any = None

    def set_shadow_sample_service(self, service: Any) -> None:
        """Late-bind the provisional shadow sample service exactly once."""
        if (
            self._shadow_sample_service is not None
            and self._shadow_sample_service is not service
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_shadow_sample_service_conflict",
                "自动影子验证服务已绑定，不能重复配置。",
                http_status=409,
            )
        self._shadow_sample_service = service

    def register_protocol_version(
        self,
        *,
        project_id: str,
        source_entry_id: str,
        protocol_code: str,
        version_label: str,
        version_date: str,
        applicability_status: str,
        operational_effective_from: str,
        operational_effective_to: str = "",
        predecessor_version_id: str = "",
        amendment_source_entry_id: str = "",
    ) -> tuple[ProtocolSourceVersion, bool]:
        entry = self._usable_source(
            project_id,
            source_entry_id,
            source_kind="protocol_docx",
        )
        version = ProtocolSourceVersion.create(
            project_id=project_id,
            protocol_code=protocol_code,
            version_label=version_label,
            version_date=version_date,
            source_entry_id=entry.entry_id,
            source_title=entry.public_title,
            content_sha256=entry.content_hash,
            status="confirmed",
            applicability_status=applicability_status,
            operational_effective_from=operational_effective_from,
            operational_effective_to=operational_effective_to,
            predecessor_version_id=predecessor_version_id,
            amendment_source_entry_id=amendment_source_entry_id,
        )
        existed = any(
            item.protocol_version_id == version.protocol_version_id
            for item in self.repository.list_protocol_versions(project_id)
        )
        stored = self.repository.register_protocol_version(version)
        return stored, existed

    def create_applicability_assignment(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        centre_id: str,
        operational_effective_from: str,
        operational_effective_to: str,
        evidence_text: str,
        evidence_source_entry_id: str,
        evidence_locator: str,
        created_by: str,
        subject_id: str = "",
    ) -> tuple[ProtocolApplicabilityAssignment, bool]:
        self._protocol_version(project_id, protocol_version_id)
        evidence_entry = self._usable_monitoring_source(
            project_id,
            evidence_source_entry_id,
        )
        assignment = ProtocolApplicabilityAssignment.create(
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            centre_id=centre_id,
            subject_id=subject_id,
            operational_effective_from=operational_effective_from,
            operational_effective_to=operational_effective_to,
            evidence_text=evidence_text,
            evidence_source_content_sha256=evidence_entry.content_hash,
            evidence_source_entry_id=evidence_source_entry_id,
            evidence_locator=evidence_locator,
            created_by=created_by,
        )
        existed = any(
            item.assignment_id == assignment.assignment_id
            for item in self.repository.list_applicability_assignments(
                project_id,
                protocol_version_id=protocol_version_id,
            )
        )
        return (
            self.repository.create_applicability_assignment(assignment),
            existed,
        )

    def confirm_applicability_assignment(
        self,
        *,
        project_id: str,
        assignment_id: str,
        expected_state_version: int,
        confirmed_by: str,
    ) -> ProtocolApplicabilityAssignment:
        self.repository.applicability_assignment(project_id, assignment_id)
        return self.repository.transition_applicability_assignment(
            project_id,
            assignment_id,
            expected_state_version=expected_state_version,
            status="confirmed",
            actor=confirmed_by,
        )

    def retire_applicability_assignment(
        self,
        *,
        project_id: str,
        assignment_id: str,
        expected_state_version: int,
        retired_by: str,
    ) -> ProtocolApplicabilityAssignment:
        self.repository.applicability_assignment(project_id, assignment_id)
        return self.repository.transition_applicability_assignment(
            project_id,
            assignment_id,
            expected_state_version=expected_state_version,
            status="retired",
            actor=retired_by,
        )

    def resolve_applicability(
        self,
        *,
        project_id: str,
        centre_id: str,
        event_date: str,
        subject_id: str = "",
    ) -> ProtocolApplicabilityResolution:
        return self.repository.resolve_protocol_applicability(
            project_id,
            centre_id=centre_id,
            subject_id=subject_id,
            event_date=event_date,
        )

    def adopt_ai_candidate(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        candidate_id: str,
        fact_key: str,
        proposed_fact_type: str,
        title: str = "",
        applicability: Mapping[str, Any] | None = None,
        adoption_context: Mapping[str, Any] | None = None,
    ) -> tuple[ProtocolFact, bool]:
        version = self._protocol_version(project_id, protocol_version_id)
        candidate = self._accepted_protocol_candidate(project_id, candidate_id)
        evidence = self._candidate_protocol_evidence(candidate, version)
        fact_payload = self._candidate_fact_payload(
            candidate,
            adoption_context=adoption_context,
        )
        existing = self._fact_for_ai_candidate(
            protocol_version_id,
            candidate.candidate_id,
        )
        if existing is not None:
            if existing.status != "ai_candidate":
                raise MonitoringRuleAuthoringError(
                    "monitoring_ai_candidate_lineage_closed",
                    "该 AI 条款候选已经完成确认或由后续修订替代。",
                    http_status=409,
                )
            if (
                existing.fact_key != fact_key
                or existing.fact_type != proposed_fact_type
            ):
                raise MonitoringRuleAuthoringError(
                    "monitoring_ai_candidate_already_adopted",
                    "该 AI 条款候选已按另一事实键或事实类型采纳。",
                    http_status=409,
                )
            if (
                existing.source_entry_id != evidence.source_entry_id
                or existing.source_locator != evidence.locator
                or existing.source_text != evidence.quote.strip()
                or (
                    adoption_context is not None
                    and existing.normalized_payload.get("adoption_context")
                    != fact_payload["adoption_context"]
                )
            ):
                corrected = ProtocolFact.create(
                    project_id=project_id,
                    protocol_version_id=protocol_version_id,
                    fact_key=fact_key,
                    fact_type=proposed_fact_type,
                    status="ai_candidate",
                    title=title.strip() or existing.title or candidate.title,
                    normalized_payload=fact_payload,
                    source_entry_id=evidence.source_entry_id,
                    source_locator=evidence.locator,
                    source_text=evidence.quote.strip(),
                    applicability=applicability or existing.applicability,
                    supersedes_fact_revision_id=existing.fact_revision_id,
                )
                stored = self.repository.store_fact(corrected)
                self.repository.transition_fact_status(
                    existing.fact_revision_id,
                    expected_state_version=existing.state_version,
                    status="superseded",
                    actor="system_source_lineage_correction",
                )
                return stored, False
            return existing, True

        if proposed_fact_type not in PROTOCOL_FACT_TYPES:
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_type_invalid",
                "所选方案事实类型不受当前规则 DSL 支持。",
            )
        fact = ProtocolFact.create(
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            fact_key=fact_key,
            fact_type=proposed_fact_type,
            status="ai_candidate",
            title=title.strip() or candidate.title,
            normalized_payload=fact_payload,
            source_entry_id=evidence.source_entry_id,
            source_locator=evidence.locator,
            source_text=evidence.quote.strip(),
            applicability=applicability or {},
        )
        return self.repository.store_fact(fact), False

    @staticmethod
    def _compile_fact_rule(fact: ProtocolFact) -> MonitoringRuleDefinition:
        rule = compile_monitoring_rule_template(fact)
        template = fact.normalized_payload.get(TEMPLATE_PAYLOAD_KEY)
        if (
            isinstance(template, Mapping)
            and isinstance(template.get("immutable_identity"), Mapping)
            and rule.mapping_revision
        ):
            return replace(rule, status="confirmed")
        return rule

    @staticmethod
    def _candidate_fact_payload(
        candidate: MonitoringAiCandidate,
        *,
        adoption_context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ai_candidate": candidate.model_dump(mode="json"),
        }
        if adoption_context is not None:
            payload["adoption_context"] = dict(adoption_context)
        return payload

    def confirm_fact_and_compile(
        self,
        *,
        project_id: str,
        fact_revision_id: str,
        expected_state_version: int,
        fact_type: str,
        deterministic_template: Mapping[str, Any],
        confirmed_by: str,
        title: str = "",
        applicability: Mapping[str, Any] | None = None,
    ) -> tuple[ProtocolFact, MonitoringRuleDefinition]:
        candidate_fact = self._fact(project_id, fact_revision_id)
        if candidate_fact.state_version != int(expected_state_version):
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_state_stale",
                "方案事实已被其他操作更新，请刷新后重试。",
                http_status=409,
            )
        if candidate_fact.status != "ai_candidate":
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_not_ai_candidate",
                "仅 AI 条款候选事实可以进入本确认动作。",
                http_status=409,
            )
        candidate_payload = candidate_fact.normalized_payload.get("ai_candidate")
        if not isinstance(candidate_payload, Mapping):
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_candidate_lineage_missing",
                "该事实缺少可追溯的 AI 候选来源。",
                http_status=409,
            )
        candidate_id = str(candidate_payload.get("candidate_id") or "").strip()
        self._accepted_protocol_candidate(project_id, candidate_id)
        if fact_type not in PROTOCOL_FACT_TYPES:
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_type_invalid",
                "所选方案事实类型不受当前规则 DSL 支持。",
            )
        immutable_identity = deterministic_template.get("immutable_identity")
        if (
            not isinstance(immutable_identity, Mapping)
            or any(
                not str(immutable_identity.get(name) or "").strip()
                for name in (
                    "mapping_revision",
                    "mapping_content_sha256",
                    "capability_manifest_sha256",
                    "effective_capabilities_sha256",
                )
            )
        ):
            # Fail closed: the legacy confirm path must not admit a
            # no-identity candidate into release; the recommendation
            # adoption chain is where the medical decision happens.
            raise MonitoringRuleAuthoringError(
                "monitoring_rule_identity_required",
                "规则模板缺少可追溯的字段映射身份，请通过规则建议链确认。",
                http_status=409,
            )

        confirmed_revision = ProtocolFact.create(
            project_id=project_id,
            protocol_version_id=candidate_fact.protocol_version_id,
            fact_key=candidate_fact.fact_key,
            fact_type=fact_type,
            status="ai_candidate",
            title=title.strip() or candidate_fact.title,
            normalized_payload={
                "ai_candidate": dict(candidate_payload),
                TEMPLATE_PAYLOAD_KEY: dict(deterministic_template),
            },
            source_entry_id=candidate_fact.source_entry_id,
            source_locator=candidate_fact.source_locator,
            source_text=candidate_fact.source_text,
            applicability=applicability or candidate_fact.applicability,
            supersedes_fact_revision_id=candidate_fact.fact_revision_id,
        )
        preflight = replace(
            confirmed_revision,
            status="medically_confirmed",
            state_version=2,
        )
        compile_monitoring_rule_template(preflight)

        stored = self.repository.store_fact(confirmed_revision)
        if stored.status == "ai_candidate":
            stored = self.repository.transition_fact_status(
                stored.fact_revision_id,
                expected_state_version=stored.state_version,
                status="medically_confirmed",
                actor=confirmed_by,
            )
        if stored.status != "medically_confirmed":
            raise MonitoringRuleAuthoringError(
                "monitoring_confirmed_fact_conflict",
                "确认后的方案事实处于不可用状态。",
                http_status=409,
            )
        rule = self._compile_fact_rule(stored)
        try:
            self.repository.transition_fact_status(
                candidate_fact.fact_revision_id,
                expected_state_version=expected_state_version,
                status="superseded",
                actor=confirmed_by,
            )
        except MonitoringProtocolStateConflictError:
            # Do not leave a second usable fact when the source candidate lost CAS.
            try:
                self.repository.transition_fact_status(
                    stored.fact_revision_id,
                    expected_state_version=stored.state_version,
                    status="superseded",
                    actor="system_cas_rollback",
                )
            except Exception:
                pass
            raise
        return stored, rule

    def require_user_confirmed_fact_draft(
        self,
        *,
        project_id: str,
        fact_revision_id: str,
        allow_superseded: bool = False,
    ) -> tuple[ProtocolFact, ProtocolSourceVersion]:
        """Resolve an accepted protocol-clause fact draft and its frozen source."""

        fact = self._fact(project_id, fact_revision_id)
        allowed_statuses = (
            {"ai_candidate", "superseded"}
            if allow_superseded
            else {"ai_candidate"}
        )
        if fact.status not in allowed_statuses:
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_not_user_confirmed_draft",
                "当前方案事实已进入后续状态，不能重新生成规则模板建议。",
                http_status=409,
            )
        candidate_payload = fact.normalized_payload.get("ai_candidate")
        adoption_context = fact.normalized_payload.get("adoption_context")
        if not isinstance(candidate_payload, Mapping) or not isinstance(
            adoption_context,
            Mapping,
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_candidate_lineage_missing",
                "该方案事实缺少已接受候选与来源快照，不能生成规则模板建议。",
                http_status=409,
            )
        candidate_id = str(candidate_payload.get("candidate_id") or "").strip()
        candidate = self._accepted_protocol_candidate(project_id, candidate_id)
        version = self._protocol_version(project_id, fact.protocol_version_id)
        evidence = self._candidate_protocol_evidence(candidate, version)
        source_entry = self._usable_source(
            project_id,
            version.source_entry_id,
            source_kind="protocol_docx",
        )
        expected_identity = {
            "protocol_version_id": version.protocol_version_id,
            "source_entry_id": version.source_entry_id,
            "source_content_sha256": version.content_sha256,
        }
        actual_identity = {
            key: str(adoption_context.get(key) or "").strip()
            for key in expected_identity
        }
        if (
            actual_identity != expected_identity
            or source_entry.content_hash != version.content_sha256
            or fact.source_entry_id != evidence.source_entry_id
            or fact.source_locator != evidence.locator
            or fact.source_text != evidence.quote.strip()
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_source_drift",
                "方案版本、候选原文或事实来源已变化，请重新确认方案条款。",
                http_status=409,
            )
        return fact, version

    def create_draft(
        self,
        *,
        project_id: str,
        protocol_version_id: str,
        fact_revision_ids: Sequence[str],
        created_by: str,
        retrospective_policy: str = "open_risks_only",
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        self._protocol_version(project_id, protocol_version_id)
        unique_ids = tuple(dict.fromkeys(str(item).strip() for item in fact_revision_ids))
        if not unique_ids or any(not item for item in unique_ids):
            raise MonitoringRuleAuthoringError(
                "monitoring_confirmed_facts_required",
                "创建规则包草稿前至少需要一条已确认方案事实。",
            )
        if len(unique_ids) != len(fact_revision_ids):
            raise MonitoringRuleAuthoringError(
                "monitoring_duplicate_fact_revision",
                "规则包草稿不能重复引用同一方案事实。",
            )
        rules = tuple(
            self._compile_fact_rule(
                self._confirmed_fact(
                    project_id,
                    protocol_version_id,
                    fact_revision_id,
                )
            )
            for fact_revision_id in unique_ids
        )
        return self.lifecycle_service.create_draft_from_confirmed_facts(
            project_id=project_id,
            protocol_version_id=protocol_version_id,
            rules=rules,
            created_by=created_by,
            retrospective_policy=retrospective_policy,
            expected_pack_revision=expected_pack_revision,
        )

    def confirm_rule(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        rule_revision_id: str,
        expected_state_version: int,
        confirmed_by: str,
    ) -> MonitoringRuleDefinition:
        pack, rules = self._rule_pack(project_id, rule_pack_id, status="draft")
        rule = next(
            (item for item in rules if item.rule_revision_id == rule_revision_id),
            None,
        )
        if rule is None:
            raise MonitoringRuleAuthoringError(
                "monitoring_rule_not_found",
                "当前规则包中未找到该规则。",
                http_status=404,
            )
        return self.lifecycle_service.confirm_rule(
            rule.rule_revision_id,
            expected_state_version=expected_state_version,
            confirmed_by=confirmed_by,
        )

    def start_shadow(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        started_by: str,
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        self._rule_pack(project_id, rule_pack_id, status="draft")
        return self.lifecycle_service.start_shadow(
            rule_pack_id,
            started_by=started_by,
            expected_pack_revision=expected_pack_revision,
        )

    def register_gold_case(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        rule_revision_id: str,
        source_entry_id: str,
        source_revision: str,
        batch_revision: str,
        case_label: str,
        input_record: Mapping[str, Any],
        observed_domains: Iterable[str],
        expected_match: bool,
        medical_rationale: str,
        coverage_labels: Iterable[str] | None = None,
        previous_record: Mapping[str, Any] | None = None,
        related_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        evidence_locators: Iterable[str] = (),
        source_row_bindings: Iterable[Mapping[str, Any]] = (),
    ) -> RuleGoldStandardCase:
        _, rules = self._rule_pack(project_id, rule_pack_id, status="shadow")
        rule = next(
            (item for item in rules if item.rule_revision_id == rule_revision_id),
            None,
        )
        if rule is None:
            raise MonitoringRuleAuthoringError(
                "monitoring_rule_not_found",
                "当前影子规则包中未找到该规则。",
                http_status=404,
            )
        entry = self._usable_source(
            project_id,
            source_entry_id,
            source_kind="edc_data_listing",
        )
        case = RuleGoldStandardCase.create(
            project_id=project_id,
            rule_key=rule.rule_key,
            rule_revision_id=rule.rule_revision_id,
            source_entry_id=entry.entry_id,
            source_content_sha256=entry.content_hash,
            source_revision=source_revision,
            batch_revision=batch_revision,
            case_label=case_label,
            input_record=input_record,
            previous_record=previous_record or {},
            related_records=related_records or {},
            observed_domains=observed_domains,
            expected_match=expected_match,
            coverage_labels=coverage_labels,
            medical_rationale=medical_rationale,
            evidence_locators=evidence_locators,
            source_row_bindings=source_row_bindings,
        )
        return self.repository.store_gold_cases((case,))[0]

    def register_diagnostic_case(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        rule_revision_id: str,
        source_entry_id: str,
        source_revision: str,
        batch_revision: str,
        case_label: str,
        input_record: Mapping[str, Any],
        observed_domains: Iterable[str],
        expected_diagnostic_category: str,
        expected_diagnostic_code: str,
        medical_rationale: str,
        previous_record: Mapping[str, Any] | None = None,
        related_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        evidence_locators: Iterable[str] = (),
        source_row_bindings: Iterable[Mapping[str, Any]] = (),
    ) -> RuleDiagnosticCase:
        _, rules = self._rule_pack(project_id, rule_pack_id, status="shadow")
        rule = next(
            (
                item
                for item in rules
                if item.rule_revision_id == rule_revision_id
            ),
            None,
        )
        if rule is None:
            raise MonitoringRuleAuthoringError(
                "monitoring_rule_not_found",
                "当前影子规则包中未找到该规则。",
                http_status=404,
            )
        entry = self._usable_source(
            project_id,
            source_entry_id,
            source_kind="edc_data_listing",
        )
        case = RuleDiagnosticCase.create(
            project_id=project_id,
            rule_key=rule.rule_key,
            rule_revision_id=rule.rule_revision_id,
            source_entry_id=entry.entry_id,
            source_content_sha256=entry.content_hash,
            source_revision=source_revision,
            batch_revision=batch_revision,
            case_label=case_label,
            input_record=input_record,
            previous_record=previous_record or {},
            related_records=related_records or {},
            observed_domains=observed_domains,
            expected_diagnostic_category=expected_diagnostic_category,
            expected_diagnostic_code=expected_diagnostic_code,
            medical_rationale=medical_rationale,
            evidence_locators=evidence_locators,
            source_row_bindings=source_row_bindings,
        )
        return self.repository.store_diagnostic_cases((case,))[0]

    def run_shadow(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        batch_id: str,
    ):
        self._rule_pack(project_id, rule_pack_id, status="shadow")
        return self.protocol_rule_service.run_shadow_validation(
            rule_pack_id=rule_pack_id,
            batch_id=batch_id,
        )

    def confirm_shadow(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        shadow_run_id: str | None = None,
        sample_set_id: str | None = None,
        confirmed_by: str,
        expected_pack_revision: int | None = None,
    ) -> ShadowConfirmationOutcome:
        if bool(str(shadow_run_id or "").strip()) == bool(
            str(sample_set_id or "").strip()
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_shadow_confirmation_target_invalid",
                "确认影子验证必须且只能提供可信影子运行"
                "或待确认影子样本集之一。",
                http_status=409,
            )
        if str(shadow_run_id or "").strip():
            self._rule_pack(project_id, rule_pack_id, status="shadow")
            pack = self.lifecycle_service.confirm_shadow(
                rule_pack_id,
                shadow_run_id=str(shadow_run_id or "").strip(),
                confirmed_by=confirmed_by,
                expected_pack_revision=expected_pack_revision,
            )
            return ShadowConfirmationOutcome(
                pack=pack,
                confirmation=None,
                shadow_run_id=str(shadow_run_id or "").strip(),
            )
        service = self._shadow_sample_service
        if service is None:
            raise MonitoringRuleAuthoringError(
                "monitoring_shadow_samples_unavailable",
                "自动影子验证服务尚未接入。",
                http_status=503,
            )
        existing = self.repository.shadow_sample_confirmation(
            project_id,
            rule_pack_id,
        )
        if (
            existing is not None
            and existing.sample_set_id != str(sample_set_id or "").strip()
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_shadow_confirmation_conflict",
                "该规则包已确认另一影子样本集，不能重复确认。",
                http_status=409,
            )
        try:
            self._rule_pack(project_id, rule_pack_id, status="shadow")
        except MonitoringRuleAuthoringError as exc:
            if (
                existing is None
                or exc.code != "monitoring_rule_pack_stage_conflict"
            ):
                raise
            # Idempotent replay of the exact confirmation act that already
            # advanced this pack to the confirmed stage.
            pack, _rules = self._rule_pack(
                project_id,
                rule_pack_id,
                status="confirmed",
            )
            return ShadowConfirmationOutcome(
                pack=pack,
                confirmation=existing,
                shadow_run_id=existing.trusted_shadow_run_id,
            )
        confirmation, run = service.confirm_samples(
            project_id=project_id,
            rule_pack_id=rule_pack_id,
            sample_set_id=str(sample_set_id or "").strip(),
            actor=confirmed_by,
            expected_pack_revision=expected_pack_revision,
        )
        pack = self.lifecycle_service.confirm_shadow(
            rule_pack_id,
            shadow_run_id=run.shadow_run_id,
            confirmed_by=confirmed_by,
            expected_pack_revision=expected_pack_revision,
        )
        return ShadowConfirmationOutcome(
            pack=pack,
            confirmation=confirmation,
            shadow_run_id=run.shadow_run_id,
        )

    def publish(
        self,
        *,
        project_id: str,
        rule_pack_id: str,
        published_by: str,
        expected_pack_revision: int | None = None,
    ) -> MonitoringRulePack:
        self._rule_pack(project_id, rule_pack_id, status="confirmed")
        return self.lifecycle_service.publish(
            rule_pack_id,
            published_by=published_by,
            expected_pack_revision=expected_pack_revision,
        )

    def _protocol_version(
        self,
        project_id: str,
        protocol_version_id: str,
    ) -> ProtocolSourceVersion:
        try:
            version = self.repository.protocol_version(protocol_version_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise MonitoringRuleAuthoringError(
                "monitoring_protocol_version_not_found",
                "当前项目未找到该方案版本。",
                http_status=404,
            ) from exc
        if version.project_id != project_id:
            raise MonitoringRuleAuthoringError(
                "monitoring_protocol_version_not_found",
                "当前项目未找到该方案版本。",
                http_status=404,
            )
        return version

    def _fact(self, project_id: str, fact_revision_id: str) -> ProtocolFact:
        for version in self.repository.list_protocol_versions(project_id):
            for fact in self.repository.facts_for_version(version.protocol_version_id):
                if fact.fact_revision_id == fact_revision_id:
                    return fact
        raise MonitoringRuleAuthoringError(
            "monitoring_protocol_fact_not_found",
            "当前项目未找到该方案事实。",
            http_status=404,
        )

    def _confirmed_fact(
        self,
        project_id: str,
        protocol_version_id: str,
        fact_revision_id: str,
    ) -> ProtocolFact:
        fact = self._fact(project_id, fact_revision_id)
        if fact.protocol_version_id != protocol_version_id:
            raise MonitoringRuleAuthoringError(
                "monitoring_protocol_fact_not_found",
                "当前方案版本未找到该方案事实。",
                http_status=404,
            )
        if fact.status != "medically_confirmed":
            raise MonitoringRuleAuthoringError(
                "monitoring_fact_not_confirmed",
                "规则草稿只能使用医学经理已确认的方案事实。",
                http_status=409,
            )
        return fact

    def _fact_for_ai_candidate(
        self,
        protocol_version_id: str,
        candidate_id: str,
    ) -> ProtocolFact | None:
        matches = []
        for fact in self.repository.facts_for_version(protocol_version_id):
            payload = fact.normalized_payload.get("ai_candidate")
            if isinstance(payload, Mapping) and payload.get("candidate_id") == candidate_id:
                matches.append(fact)
        active = [item for item in matches if item.status != "superseded"]
        if len(active) > 1:
            raise MonitoringRuleAuthoringError(
                "monitoring_ai_candidate_lineage_conflict",
                "该 AI 条款候选存在多个活动事实修订。",
                http_status=409,
            )
        return active[0] if active else (matches[-1] if matches else None)

    def _accepted_protocol_candidate(
        self,
        project_id: str,
        candidate_id: str,
    ) -> MonitoringAiCandidate:
        if not candidate_id:
            raise MonitoringRuleAuthoringError(
                "monitoring_ai_candidate_required",
                "请选择已接受的方案条款候选。",
            )
        try:
            job = self.ai_repository.job_for_candidate(project_id, candidate_id)
            candidates = self.ai_repository.candidates(project_id, job.job_id)
        except ValueError as exc:
            raise MonitoringRuleAuthoringError(
                "monitoring_ai_candidate_not_found",
                "当前项目未找到该 AI 条款候选。",
                http_status=404,
            ) from exc
        candidate = next(
            (item for item in candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate is None:
            raise MonitoringRuleAuthoringError(
                "monitoring_ai_candidate_not_found",
                "当前项目未找到该 AI 条款候选。",
                http_status=404,
            )
        if (
            job.status != MonitoringAiJobStatus.COMPLETED
            or job.task_type != MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
            or candidate.task_type
            != MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING
            or candidate.status != MonitoringAiCandidateStatus.ACCEPTED
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_ai_candidate_not_accepted",
                "仅已接受且已完成的方案条款结构化候选可以采纳。",
                http_status=409,
            )
        return candidate

    @staticmethod
    def _candidate_protocol_evidence(
        candidate: MonitoringAiCandidate,
        version: ProtocolSourceVersion,
    ):
        structured_ids = candidate.structured_payload.get("evidence_ids")
        authorized_ids = (
            tuple(
                str(evidence_id).strip()
                for evidence_id in structured_ids
                if str(evidence_id).strip()
            )
            if isinstance(structured_ids, (list, tuple))
            else ()
        )
        if not authorized_ids:
            authorized_ids = tuple(
                evidence_id
                for claim in candidate.claims
                for evidence_id in claim.evidence_ids
            )
        evidence_by_id = {
            item.evidence_id: item
            for item in candidate.evidence
        }
        matches = [
            evidence_by_id[evidence_id]
            for evidence_id in dict.fromkeys(authorized_ids)
            if evidence_id in evidence_by_id
            for item in (evidence_by_id[evidence_id],)
            if item.source_entry_id == version.source_entry_id
            and item.source_content_sha256 == version.content_sha256
            and item.quote.strip()
            and item.locator.strip()
        ]
        if not matches:
            raise MonitoringRuleAuthoringError(
                "monitoring_candidate_original_quote_missing",
                "候选未绑定该方案版本的原文摘录与定位，不能创建方案事实。",
                http_status=409,
            )
        return matches[0]

    def _rule_pack(
        self,
        project_id: str,
        rule_pack_id: str,
        *,
        status: str,
    ) -> tuple[MonitoringRulePack, tuple[MonitoringRuleDefinition, ...]]:
        try:
            pack, rules = self.repository.rule_pack(rule_pack_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise MonitoringRuleAuthoringError(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
                http_status=404,
            ) from exc
        if pack.project_id != project_id:
            raise MonitoringRuleAuthoringError(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
                http_status=404,
            )
        if pack.status != status:
            raise MonitoringRuleAuthoringError(
                "monitoring_rule_pack_stage_conflict",
                f"当前规则包状态不允许此操作：{pack.status}。",
                http_status=409,
            )
        return pack, rules

    def _usable_source(
        self,
        project_id: str,
        source_entry_id: str,
        *,
        source_kind: str,
    ):
        entries = [
            item
            for item in self.source_registry.list_entries(project_id)
            if item.entry_id == source_entry_id
        ]
        if len(entries) != 1:
            raise MonitoringRuleAuthoringError(
                "monitoring_source_not_found",
                "当前项目未找到该来源文件。",
                http_status=404,
            )
        entry = entries[0]
        if entry.module != "medical_monitoring" or entry.source_kind != source_kind:
            raise MonitoringRuleAuthoringError(
                "monitoring_source_role_mismatch",
                "所选文件类型与当前医学监查操作不匹配。",
                http_status=409,
            )
        if entry.parser_status != "parsed":
            raise MonitoringRuleAuthoringError(
                "monitoring_source_not_readable",
                "所选文件尚未完成基本内容解析。",
                http_status=409,
            )
        validation = self.source_registry.current_content_validation(
            project_id,
            source_entry_id,
        )
        if (
            validation is None
            or validation.technical_status != "ready"
            or validation.use_status
            not in {"allowed", "confirmed_after_warning"}
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_source_validation_unusable",
                "所选文件尚未通过基本信息与内容校验，或提示尚未确认。",
                http_status=409,
            )
        if not _exact_sha256_pair(validation.file_sha256, entry.content_hash):
            raise MonitoringRuleAuthoringError(
                "monitoring_source_validation_stale",
                "文件内容已变化，请重新执行基本信息与内容校验。",
                http_status=409,
            )
        return entry

    def _usable_monitoring_source(
        self,
        project_id: str,
        source_entry_id: str,
    ):
        entries = [
            item
            for item in self.source_registry.list_entries(project_id)
            if item.entry_id == source_entry_id
        ]
        if len(entries) != 1:
            raise MonitoringRuleAuthoringError(
                "monitoring_source_not_found",
                "当前项目未找到该适用性依据文件。",
                http_status=404,
            )
        entry = entries[0]
        if entry.module != "medical_monitoring" or entry.parser_status != "parsed":
            raise MonitoringRuleAuthoringError(
                "monitoring_applicability_evidence_unusable",
                "适用性依据必须是已解析的医学监查来源。",
                http_status=409,
            )
        validation = self.source_registry.current_content_validation(
            project_id,
            source_entry_id,
        )
        if (
            validation is None
            or validation.technical_status != "ready"
            or validation.use_status
            not in {"allowed", "confirmed_after_warning"}
            or not _exact_sha256_pair(
                validation.file_sha256,
                entry.content_hash,
            )
        ):
            raise MonitoringRuleAuthoringError(
                "monitoring_applicability_evidence_unusable",
                "适用性依据尚未通过当前内容校验。",
                http_status=409,
            )
        return entry
