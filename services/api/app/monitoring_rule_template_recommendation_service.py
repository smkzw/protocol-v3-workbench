from __future__ import annotations

from typing import Any, Callable, Mapping

from .monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    candidate_confidence_summary,
    content_sha256,
)
from .monitoring_ai_repository import (
    MonitoringAiRepository,
    MonitoringAiRepositoryError,
    MonitoringAiStateConflictError,
)
from .monitoring_ai_service import MonitoringAiService
from .monitoring_capability_guard import (
    MonitoringCapabilityContractError,
    require_monitoring_capability_snapshot,
    required_capabilities_for_rule_family,
)
from .monitoring_mapping_activation import MonitoringMappingActivationService
from .monitoring_mapping_draft_repository import MonitoringMappingDraftRepository
from .monitoring_mapping_semantic_quality import (
    resolve_closed_monitoring_role_concept,
)
from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
    MonitoringProtocolStateConflictError,
)
from .monitoring_protocol_rules import (
    RULE_FAMILY_ALLOWED_DATA_DOMAINS,
    MonitoringRuleDefinition,
    ProtocolFact,
)
from .monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringError,
    MonitoringRuleAuthoringService,
)
from .monitoring_rule_templates import (
    TEMPLATE_PAYLOAD_KEY,
    template_rule_families_for_fact_type,
)


RULE_TEMPLATE_RECOMMENDATION_CONTRACT_VERSION = (
    "monitoring_rule_template_recommendation_v1"
)
RULE_TEMPLATE_RECOMMENDATION_BUSINESS_PREFIX = "rule-template-recommendation:"


class MonitoringRuleTemplateRecommendationError(ValueError):
    def __init__(self, code: str, message: str, *, http_status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class MonitoringRuleTemplateRecommendationService:
    """User-confirmed protocol fact to precompiled deterministic suggestions."""

    def __init__(
        self,
        *,
        protocol_repository: MonitoringProtocolRuleRepository,
        mapping_repository: MonitoringMappingDraftRepository,
        mapping_activation_service: MonitoringMappingActivationService,
        ai_repository: MonitoringAiRepository,
        ai_service: MonitoringAiService,
        rule_authoring_service: MonitoringRuleAuthoringService,
        worker_wake: Callable[[], Any] = lambda: None,
    ):
        self.protocol_repository = protocol_repository
        self.mapping_repository = mapping_repository
        self.mapping_activation_service = mapping_activation_service
        self.ai_repository = ai_repository
        self.ai_service = ai_service
        self.rule_authoring_service = rule_authoring_service
        self.worker_wake = worker_wake

    def start(
        self,
        *,
        project_id: str,
        fact_revision_id: str,
        expected_fact_state_version: int,
    ) -> dict[str, Any]:
        prepared = self._prepare(
            project_id=project_id,
            fact_revision_id=fact_revision_id,
            expected_fact_state_version=expected_fact_state_version,
        )
        if prepared["manual_review"]:
            return self._manual_review_payload(prepared)
        job = self.ai_service.submit_task(
            project_id=project_id,
            task_type=MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION,
            input_revision=prepared["input_revision"],
            input_payload=prepared["input_payload"],
            business_key=prepared["business_key"],
            max_attempts=2,
        )
        self.worker_wake()
        return self._status_payload(prepared, job)

    def status(
        self,
        *,
        project_id: str,
        fact_revision_id: str,
        expected_fact_state_version: int,
    ) -> dict[str, Any]:
        prepared = self._prepare(
            project_id=project_id,
            fact_revision_id=fact_revision_id,
            expected_fact_state_version=expected_fact_state_version,
        )
        if prepared["manual_review"]:
            return self._manual_review_payload(prepared)
        matches = self._matching_jobs(prepared)
        if not matches:
            return {
                **self._public_context(prepared),
                "status": "ready",
                "candidates": [],
            }
        return self._status_payload(prepared, matches[-1])

    def decide(
        self,
        *,
        project_id: str,
        fact_revision_id: str,
        candidate_id: str,
        decision: MonitoringAiCandidateStatus,
        expected_input_revision_sha256: str,
        expected_fact_state_version: int,
        actor: str,
        reason: str,
    ) -> dict[str, Any]:
        if decision not in {
            MonitoringAiCandidateStatus.ACCEPTED,
            MonitoringAiCandidateStatus.REJECTED,
        }:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_decision_invalid",
                "规则模板建议只能选择或驳回。",
            )
        try:
            job = self.ai_repository.job_for_candidate(project_id, candidate_id)
            candidates = self.ai_repository.candidates(project_id, job.job_id)
        except MonitoringAiRepositoryError as exc:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_candidate_not_found",
                "当前项目未找到该规则模板建议。",
                http_status=404,
            ) from exc
        candidate = next(
            (item for item in candidates if item.candidate_id == candidate_id),
            None,
        )
        if (
            candidate is None
            or job.task_type
            != MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION
            or job.status != MonitoringAiJobStatus.COMPLETED
        ):
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_candidate_unavailable",
                "该规则模板建议尚不可选择。",
                http_status=409,
            )
        # The request carries a persisted identity digest.  Preserve its raw
        # bytes at this boundary so padded/uppercase forms cannot be silently
        # rewritten into the canonical job identity.
        expected_revision = (
            expected_input_revision_sha256
            if isinstance(expected_input_revision_sha256, str)
            else ""
        )
        if (
            expected_revision != job.input_revision_sha256
            or job.input_revision.fact_revision.split(":v", 1)[0]
            != fact_revision_id
        ):
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_input_stale",
                "事实、方案或字段映射已变化，请刷新建议后重试。",
                http_status=409,
            )

        confidence_summary = candidate_confidence_summary(candidate)
        if (
            decision == MonitoringAiCandidateStatus.ACCEPTED
            and candidate.status == MonitoringAiCandidateStatus.PROPOSED
            and confidence_summary["requires_additional_evidence"]
            and not str(reason or "").strip()
        ):
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_low_confidence_confirmation_required",
                "该规则模板建议低于工作台置信度阈值；接受前请补充来源核对、数据缺口或医学确认理由。",
                http_status=422,
            )

        replay = self._confirmed_replay(
            project_id=project_id,
            fact_revision_id=fact_revision_id,
            candidate=candidate,
            job=job,
        )
        if replay is not None:
            fact, rule = replay
            if decision != MonitoringAiCandidateStatus.ACCEPTED:
                raise MonitoringRuleTemplateRecommendationError(
                    "monitoring_rule_template_opposite_decision",
                    "该规则模板已被选择，不能改为驳回。",
                    http_status=409,
                )
            return self._decision_payload(
                candidate=candidate,
                fact=fact,
                rule=rule,
                decision_reused=True,
            )

        prepared = self._prepare(
            project_id=project_id,
            fact_revision_id=fact_revision_id,
            expected_fact_state_version=expected_fact_state_version,
        )
        if prepared["manual_review"]:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_no_longer_available",
                prepared["manual_message"],
                http_status=409,
            )
        if prepared["input_revision"].revision_sha256 != job.input_revision_sha256:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_input_stale",
                "事实、方案或字段映射已变化，请重新生成建议。",
                http_status=409,
            )
        try:
            decided, decision_reused = (
                self.ai_repository.decide_candidate_idempotent_exclusive(
                    project_id,
                    candidate_id,
                    decision=decision,
                    actor=actor,
                    reason=reason,
                    current_input_revision_sha256=job.input_revision_sha256,
                )
            )
        except MonitoringAiStateConflictError as exc:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_decision_conflict",
                "该组建议已有其他选择或相反决定，请刷新后查看。",
                http_status=409,
            ) from exc
        if decision == MonitoringAiCandidateStatus.REJECTED:
            return {
                "status": "user_rejected",
                "candidate": self._public_candidate(decided, prepared["fact"]),
                "decision_reused": decision_reused,
                "confirmed_fact": None,
                "compiled_rule": None,
            }
        activation = prepared["activation"]
        deterministic_template = dict(
            decided.structured_payload["deterministic_template"]
        )
        deterministic_template["immutable_identity"] = self._immutable_identity(
            mapping_revision=activation.mapping_revision,
            mapping_content_sha256=activation.mapping_content_sha256,
            capability_manifest_sha256=activation.capability_manifest_sha256,
            effective_capabilities_sha256=(
                activation.effective_capabilities_sha256
            ),
            candidate_id=candidate_id,
        )
        try:
            fact, rule = self.rule_authoring_service.confirm_fact_and_compile(
                project_id=project_id,
                fact_revision_id=fact_revision_id,
                expected_state_version=expected_fact_state_version,
                fact_type=prepared["fact"].fact_type,
                deterministic_template=deterministic_template,
                confirmed_by=actor,
                title=prepared["fact"].title,
                applicability=prepared["fact"].applicability,
            )
        except (MonitoringRuleAuthoringError, MonitoringProtocolStateConflictError) as exc:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_adoption_conflict",
                "规则模板选择已记录，但事实状态发生并发变化；请刷新后重试同一选择。",
                http_status=409,
            ) from exc
        return self._decision_payload(
            candidate=decided,
            fact=fact,
            rule=rule,
            decision_reused=decision_reused,
        )

    def current_input_revision_sha256(self, job: MonitoringAiJob) -> str:
        if job.task_type != MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION:
            return ""
        try:
            payload = self.ai_repository.input_payload(job.project_id, job.job_id)
            context = payload["rule_template_context"]
            prepared = self._prepare(
                project_id=job.project_id,
                fact_revision_id=str(context["fact_snapshot"]["fact_revision_id"]),
                expected_fact_state_version=int(
                    context["fact_snapshot"]["state_version"]
                ),
            )
        except Exception:
            return ""
        if prepared["manual_review"]:
            return ""
        if content_sha256(prepared["input_payload"]) != job.input_payload_sha256:
            return ""
        return prepared["input_revision"].revision_sha256

    def _prepare(
        self,
        *,
        project_id: str,
        fact_revision_id: str,
        expected_fact_state_version: int,
    ) -> dict[str, Any]:
        try:
            fact, version = (
                self.rule_authoring_service.require_user_confirmed_fact_draft(
                    project_id=project_id,
                    fact_revision_id=fact_revision_id,
                )
            )
        except MonitoringRuleAuthoringError as exc:
            raise MonitoringRuleTemplateRecommendationError(
                exc.code,
                exc.message,
                http_status=exc.http_status,
            ) from exc
        if fact.state_version != int(expected_fact_state_version):
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_fact_stale",
                "方案事实已被其他操作更新，请刷新后重试。",
                http_status=409,
            )
        try:
            activation = self.mapping_activation_service.get_active_mapping(
                project_id
            )
            mapping_revision = self.mapping_repository.get_revision(
                project_id,
                activation.mapping_revision,
            )
        except Exception as exc:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_mapping_unavailable",
                "当前项目没有可用于确定性规则的已激活字段映射。",
                http_status=409,
            ) from exc
        if (
            mapping_revision.project_id != project_id
            or content_sha256(mapping_revision.model_dump(mode="json"))
            != activation.mapping_content_sha256
        ):
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_mapping_drift",
                "已激活字段映射与不可变版本不一致，请重新确认字段映射。",
                http_status=409,
            )

        all_families = template_rule_families_for_fact_type(fact.fact_type)
        available_families: list[str] = []
        blocked_capabilities: set[str] = set()
        for family in all_families:
            try:
                for capability_id in required_capabilities_for_rule_family(family):
                    require_monitoring_capability_snapshot(
                        [
                            item.to_dict()
                            for item in activation.capability_states
                        ],
                        capability_id,
                    )
            except MonitoringCapabilityContractError as exc:
                blocked_capabilities.add(exc.capability_id or family)
                continue
            available_families.append(family)
        manual_reason = ""
        manual_message = ""
        if not all_families:
            manual_reason = "no_safe_deterministic_family"
            manual_message = (
                "该方案事实当前没有安全的确定性规则族，请保留人工审阅；"
                "系统不会强行生成规则。"
            )
        elif not available_families:
            manual_reason = "mapping_capability_blocked"
            manual_message = (
                "当前字段映射未开放该事实所需能力，请先补充或确认字段映射。"
            )

        allowed_domains = {
            domain
            for family in available_families
            for domain in RULE_FAMILY_ALLOWED_DATA_DOMAINS[family]
        }
        closed_roles: list[dict[str, Any]] = []
        for field in mapping_revision.fields:
            concept = resolve_closed_monitoring_role_concept(
                field.recommended_role
            )
            if (
                concept is None
                or field.field_kind.value == "unmapped"
                or field.domain.upper() not in allowed_domains
            ):
                continue
            closed_roles.append(
                {
                    "domain": field.domain.upper(),
                    "source_field": field.source_field,
                    "role_concept_id": concept.role_concept_id,
                    "rule_role": concept.role_concept_id.replace(".", "_"),
                    "recommended_role": field.recommended_role,
                    "field_kind": field.field_kind.value,
                    "value_constraints": field.value_constraints,
                    "source_locator": (
                        f"listing:{activation.source_input_sha256}:"
                        f"mapping:{activation.mapping_revision}:"
                        f"sheet:{field.domain}:header:field:{field.source_field}"
                    ),
                }
            )
        closed_roles.sort(
            key=lambda item: (
                item["domain"],
                item["role_concept_id"],
                item["source_field"],
            )
        )
        if available_families and not closed_roles:
            manual_reason = "mapping_roles_unavailable"
            manual_message = (
                "当前已激活映射没有该规则族可引用的闭合字段角色，请补充字段映射。"
            )

        fact_evidence_id = "fact_" + content_sha256(
            {
                "fact_revision_id": fact.fact_revision_id,
                "source_text_sha256": fact.source_text_sha256,
            }
        )[:28]
        mapping_evidence_id = "mapping_" + content_sha256(
            {
                "mapping_revision": activation.mapping_revision,
                "mapping_content_sha256": activation.mapping_content_sha256,
            }
        )[:28]
        mapping_source_entry_id = (
            f"mapping-revision:{activation.mapping_revision}"
        )
        input_revision = MonitoringAiInputRevision(
            project_id=project_id,
            fact_revision=f"{fact.fact_revision_id}:v{fact.state_version}",
            mapping_revision=activation.mapping_revision,
            protocol_version=version.protocol_version_id,
            sources=(
                MonitoringAiSourceBinding(
                    source_entry_id=version.source_entry_id,
                    source_content_sha256=version.content_sha256,
                ),
                MonitoringAiSourceBinding(
                    source_entry_id=mapping_source_entry_id,
                    source_content_sha256=activation.mapping_content_sha256,
                ),
            ),
        )
        fact_snapshot = {
            "fact_revision_id": fact.fact_revision_id,
            "state_version": fact.state_version,
            "project_id": fact.project_id,
            "protocol_version_id": fact.protocol_version_id,
            "fact_key": fact.fact_key,
            "fact_type": fact.fact_type,
            "title": fact.title,
            "source_entry_id": fact.source_entry_id,
            "source_locator": fact.source_locator,
            "source_text": fact.source_text,
            "source_text_sha256": fact.source_text_sha256,
            "applicability": fact.applicability,
        }
        mapping_snapshot = {
            "mapping_revision": activation.mapping_revision,
            "mapping_content_sha256": activation.mapping_content_sha256,
            "source_batch_id": activation.source_batch_id,
            "source_input_sha256": activation.source_input_sha256,
            "activation_disposition": activation.activation_disposition,
            "capability_manifest_sha256": activation.capability_manifest_sha256,
            "effective_capabilities_sha256": (
                activation.effective_capabilities_sha256
            ),
            "capability_states": [
                item.to_dict() for item in activation.capability_states
            ],
        }
        input_payload = {
            "rule_template_context": {
                "contract_version": RULE_TEMPLATE_RECOMMENDATION_CONTRACT_VERSION,
                "fact_snapshot": fact_snapshot,
                "mapping_snapshot": mapping_snapshot,
                "allowed_fact_types": [fact.fact_type],
                "allowed_rule_families": available_families,
                "available_closed_roles": closed_roles,
                "fact_evidence_id": fact_evidence_id,
                "mapping_evidence_id": mapping_evidence_id,
                "blocked_capabilities": sorted(blocked_capabilities),
            },
            "evidence_packet": [
                {
                    "evidence_id": fact_evidence_id,
                    "source_entry_id": version.source_entry_id,
                    "source_content_sha256": version.content_sha256,
                    "locator": fact.source_locator,
                    "quote": fact.source_text,
                    "raw_fields": {
                        "evidence_kind": "user_confirmed_protocol_fact",
                        "fact_type": fact.fact_type,
                    },
                },
                {
                    "evidence_id": mapping_evidence_id,
                    "source_entry_id": mapping_source_entry_id,
                    "source_content_sha256": activation.mapping_content_sha256,
                    "locator": (
                        f"mapping://{activation.mapping_revision}/"
                        "available-closed-roles"
                    ),
                    "quote": "",
                    "raw_fields": {
                        "evidence_kind": "active_immutable_mapping",
                        "available_closed_roles": closed_roles,
                        "capability_snapshot": mapping_snapshot,
                    },
                },
            ],
        }
        identity = content_sha256(
            {
                "fact_revision": input_revision.fact_revision,
                "mapping_revision": input_revision.mapping_revision,
                "protocol_version": input_revision.protocol_version,
                "input_payload": input_payload,
            }
        )
        return {
            "project_id": project_id,
            "fact": fact,
            "version": version,
            "activation": activation,
            "input_revision": input_revision,
            "input_payload": input_payload,
            "business_key": (
                f"{RULE_TEMPLATE_RECOMMENDATION_BUSINESS_PREFIX}"
                f"{fact.fact_revision_id}:{identity[:24]}"
            ),
            "manual_review": bool(manual_reason),
            "manual_reason": manual_reason,
            "manual_message": manual_message,
        }

    def _matching_jobs(self, prepared: Mapping[str, Any]) -> list[MonitoringAiJob]:
        return [
            job
            for job in self.ai_repository.list_jobs(
                prepared["project_id"],
                task_type=MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION.value,
                business_key_prefix=(
                    f"{RULE_TEMPLATE_RECOMMENDATION_BUSINESS_PREFIX}"
                    f"{prepared['fact'].fact_revision_id}:"
                ),
            )
            if job.input_revision_sha256
            == prepared["input_revision"].revision_sha256
            and job.input_payload_sha256
            == content_sha256(prepared["input_payload"])
        ]

    def _status_payload(
        self,
        prepared: Mapping[str, Any],
        job: MonitoringAiJob,
    ) -> dict[str, Any]:
        candidates = (
            self.ai_repository.candidates(job.project_id, job.job_id)
            if job.status == MonitoringAiJobStatus.COMPLETED
            else ()
        )
        status = job.status.value
        if job.status == MonitoringAiJobStatus.COMPLETED:
            status = (
                "candidate_review"
                if any(
                    item.status == MonitoringAiCandidateStatus.PROPOSED
                    for item in candidates
                )
                else "reviewed"
            )
        return {
            **self._public_context(prepared),
            "status": status,
            "failure": (
                {
                    "code": "generation_failed",
                    "message": (
                        "独立AI未能生成通过确定性预编译的建议，"
                        "请检查事实或字段映射后重试。"
                    ),
                }
                if job.status
                in {
                    MonitoringAiJobStatus.FAILED,
                    MonitoringAiJobStatus.BLOCKED,
                    MonitoringAiJobStatus.STALE_INPUT,
                }
                else None
            ),
            "candidates": [
                self._public_candidate(item, prepared["fact"])
                for item in candidates
            ],
        }

    @staticmethod
    def _public_context(prepared: Mapping[str, Any]) -> dict[str, Any]:
        fact = prepared["fact"]
        return {
            "project_id": prepared["project_id"],
            "fact": {
                "fact_revision_id": fact.fact_revision_id,
                "state_version": fact.state_version,
                "fact_type": fact.fact_type,
                "title": fact.title,
                "source_text": fact.source_text,
                "source_locator": fact.source_locator,
            },
            "mapping": {
                "revision": prepared["activation"].mapping_revision,
                "activation_disposition": (
                    prepared["activation"].activation_disposition
                ),
            },
            "input_revision_sha256": (
                prepared["input_revision"].revision_sha256
            ),
        }

    def _manual_review_payload(self, prepared: Mapping[str, Any]) -> dict[str, Any]:
        return {
            **self._public_context(prepared),
            "status": "manual_review",
            "reason_code": prepared["manual_reason"],
            "message": prepared["manual_message"],
            "candidates": [],
        }

    @staticmethod
    def _public_candidate(
        candidate: MonitoringAiCandidate,
        fact: ProtocolFact,
    ) -> dict[str, Any]:
        template = candidate.structured_payload["deterministic_template"]
        mapping_fields = template["listing_mapping"]["fields"]
        return {
            "candidate_id": candidate.candidate_id,
            "status": candidate.status.value,
            "title": candidate.title,
            "summary": candidate.text,
            "rationale": candidate.structured_payload["rationale"],
            "tradeoffs": candidate.structured_payload["tradeoffs"],
            "rule_family": candidate.structured_payload["rule_family"],
            "required_domains": template["required_domains"],
            "executor": template["executor"],
            "severity": template["severity"],
            "mapping_fields": [
                {
                    "role": role,
                    "domain": binding["domain"],
                    "field": binding["field"],
                }
                for role, binding in mapping_fields.items()
            ],
            "source": {
                "text": fact.source_text,
                "locator": fact.source_locator,
            },
            "confidence_summary": candidate_confidence_summary(candidate),
        }

    def _confirmed_replay(
        self,
        *,
        project_id: str,
        fact_revision_id: str,
        candidate: MonitoringAiCandidate,
        job: MonitoringAiJob,
    ) -> tuple[ProtocolFact, MonitoringRuleDefinition] | None:
        context = self.ai_repository.input_payload(
            project_id,
            job.job_id,
        )["rule_template_context"]
        protocol_version_id = str(
            context["fact_snapshot"]["protocol_version_id"]
        )
        expected_template = candidate.structured_payload["deterministic_template"]
        mapping_snapshot = context.get("mapping_snapshot")
        if not isinstance(mapping_snapshot, Mapping):
            mapping_snapshot = {}
        template_with_identity = dict(expected_template)
        template_with_identity["immutable_identity"] = self._immutable_identity(
            mapping_revision=mapping_snapshot.get("mapping_revision"),
            mapping_content_sha256=mapping_snapshot.get("mapping_content_sha256"),
            capability_manifest_sha256=(
                mapping_snapshot.get("capability_manifest_sha256")
            ),
            effective_capabilities_sha256=(
                mapping_snapshot.get("effective_capabilities_sha256")
            ),
            candidate_id=candidate.candidate_id,
        )
        expected_templates = (expected_template, template_with_identity)
        for fact in self.protocol_repository.facts_for_version(
            protocol_version_id
        ):
            if (
                fact.project_id == project_id
                and fact.supersedes_fact_revision_id == fact_revision_id
                and fact.status == "medically_confirmed"
                and fact.normalized_payload.get(TEMPLATE_PAYLOAD_KEY)
                in expected_templates
            ):
                self._validate_replay_sources(project_id, context, job)
                return fact, self.rule_authoring_service._compile_fact_rule(fact)
        return None

    @staticmethod
    def _immutable_identity(
        *,
        mapping_revision: Any,
        mapping_content_sha256: Any,
        capability_manifest_sha256: Any,
        effective_capabilities_sha256: Any,
        candidate_id: Any,
    ) -> dict[str, str]:
        return {
            "mapping_revision": str(mapping_revision or "").strip(),
            "mapping_content_sha256": (
                mapping_content_sha256
                if isinstance(mapping_content_sha256, str)
                else ""
            ),
            "capability_manifest_sha256": (
                capability_manifest_sha256
                if isinstance(capability_manifest_sha256, str)
                else ""
            ),
            "effective_capabilities_sha256": (
                effective_capabilities_sha256
                if isinstance(effective_capabilities_sha256, str)
                else ""
            ),
            "recommendation_candidate_id": str(candidate_id or "").strip(),
        }

    def _validate_replay_sources(
        self,
        project_id: str,
        context: Mapping[str, Any],
        job: MonitoringAiJob,
    ) -> None:
        fact_snapshot = context["fact_snapshot"]
        try:
            original_fact, validated_version = (
                self.rule_authoring_service.require_user_confirmed_fact_draft(
                    project_id=project_id,
                    fact_revision_id=str(fact_snapshot["fact_revision_id"]),
                    allow_superseded=True,
                )
            )
            version = self.protocol_repository.protocol_version(
                str(fact_snapshot["protocol_version_id"])
            )
            activation = self.mapping_activation_service.get_active_mapping(
                project_id
            )
        except Exception as exc:
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_source_drift",
                "方案或字段映射来源已变化，不能重放该选择。",
                http_status=409,
            ) from exc
        mapping_snapshot = context["mapping_snapshot"]
        source_bindings = {
            item.source_entry_id: item.source_content_sha256
            for item in job.input_revision.sources
        }
        if (
            original_fact.fact_revision_id
            != str(fact_snapshot["fact_revision_id"])
            or validated_version.protocol_version_id
            != str(fact_snapshot["protocol_version_id"])
            or version.project_id != project_id
            or version.source_entry_id != fact_snapshot["source_entry_id"]
            or version.content_sha256
            != source_bindings.get(version.source_entry_id)
            or activation.mapping_revision
            != mapping_snapshot["mapping_revision"]
            or activation.mapping_content_sha256
            != mapping_snapshot["mapping_content_sha256"]
            or activation.effective_capabilities_sha256
            != mapping_snapshot["effective_capabilities_sha256"]
        ):
            raise MonitoringRuleTemplateRecommendationError(
                "monitoring_rule_template_source_drift",
                "方案或字段映射来源已变化，不能重放该选择。",
                http_status=409,
            )

    @staticmethod
    def _decision_payload(
        *,
        candidate: MonitoringAiCandidate,
        fact: ProtocolFact,
        rule: MonitoringRuleDefinition,
        decision_reused: bool,
    ) -> dict[str, Any]:
        return {
            "status": "rule_template_selected",
            "candidate_id": candidate.candidate_id,
            "decision_reused": decision_reused,
            "confirmed_fact": fact.public_dict(),
            "compiled_rule": rule.public_dict(),
            "next_action": {
                "code": "create_rule_pack_draft",
                "message": (
                    "规则模板已由当前用户选择并完成确定性编译；"
                    "尚未创建规则包、开始影子验证或发布。"
                ),
            },
        }
