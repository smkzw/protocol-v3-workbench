from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.api.app.ai_gateway import AiPromptEnvelope
from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidateStatus,
    content_sha256,
)
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_ai_service import (
    MonitoringAiRuntimeBinding,
    MonitoringAiService,
)
from services.api.app.monitoring_mapping_activation import (
    MonitoringMappingActivationService,
    MonitoringMappingCapabilitySnapshot,
)
from services.api.app.monitoring_protocol_rule_repository import (
    MonitoringProtocolRuleRepository,
)
from services.api.app.monitoring_protocol_rule_service import (
    MonitoringProtocolRuleService,
)
from services.api.app.monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringService,
)
from services.api.app.monitoring_rule_lifecycle_service import (
    MonitoringRuleLifecycleService,
)
from services.api.app.monitoring_rule_template_recommendation_router import (
    RuleTemplateRecommendationDecisionRequest,
    RuleTemplateRecommendationStartRequest,
    create_monitoring_rule_template_recommendation_router,
)
from services.api.app.monitoring_rule_template_recommendation_service import (
    MonitoringRuleTemplateRecommendationError,
    MonitoringRuleTemplateRecommendationService,
)
from tests.test_monitoring_mapping_activation import (
    NOW,
    PROJECT_ID,
    _seed_confirmed_mapping,
)
from tests.test_monitoring_rule_authoring_service import (
    FakeSourceRegistry,
    _accepted_candidate,
)


class RuleTemplateProvider:
    provider_name = "test-product-ai"
    model_name = "test-product-model"
    expected_response_model = "test-product-model"
    response_model = "test-product-model"
    transport_name = "openai_compatible"

    def __init__(self, *, always_invalid: bool = False):
        self.always_invalid = always_invalid
        self.run_count = 0
        self.envelopes: list[AiPromptEnvelope] = []

    def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
        self.run_count += 1
        self.envelopes.append(envelope)
        input_payload = envelope.payload.get("input_payload")
        if input_payload is None:
            input_payload = envelope.payload["original_task"]["input_payload"]
        context = input_payload["rule_template_context"]
        revision_sha256 = envelope.payload.get("input_revision_sha256")
        if revision_sha256 is None:
            revision_sha256 = envelope.payload["original_task"][
                "input_revision_sha256"
            ]
        evidence_ids = [
            context["fact_evidence_id"],
            context["mapping_evidence_id"],
        ]
        if self.always_invalid:
            template: dict[str, Any] = {
                "template_version": "monitoring_rule_template_v2",
                "rule_family": "ae_mh_missing_review",
            }
        else:
            available = {
                (item["domain"], item["source_field"]): item
                for item in context["available_closed_roles"]
            }
            assert ("AE", "AETERM") in available
            assert ("AE", "AESTDTC") in available
            template = {
                "template_version": "monitoring_rule_template_v2",
                "rule_family": "ae_mh_missing_review",
                "rule_key": "safety.ae_start_date_completeness",
                "executor": "field_predicate",
                "required_domains": ["AE"],
                "listing_mapping": {
                    "fields": {
                        "ae_verbatim_term": {
                            "field": "AETERM",
                            "domain": "AE",
                        },
                        "ae_start_date": {
                            "field": "AESTDTC",
                            "domain": "AE",
                        },
                    }
                },
                "preconditions": {
                    "exists": {"field_role": "ae_verbatim_term"}
                },
                "trigger_expression": {
                    "missing": {"field_role": "ae_start_date"}
                },
                "exclusions": {
                    "missing": {"field_role": "ae_verbatim_term"}
                },
                "title": "AE开始日期完整性核对",
                "severity": "high",
                "evidence_template": (
                    "{ae_verbatim_term}缺少开始日期{ae_start_date}，"
                    "需医学复核原始记录。"
                ),
            }
        return {
            "schema_version": "monitoring_ai_v1",
            "task_id": envelope.task_id,
            "task_type": "rule_template_recommendation",
            "input_revision_sha256": revision_sha256,
            "candidates": [
                {
                    "candidate_type": "deterministic_rule_template",
                    "title": "AE开始日期缺失核对建议",
                    "text": "按已确认方案事实核对AE开始日期完整性。",
                    "structured_payload": {
                        "fact_type": "safety_assessment",
                        "rule_family": "ae_mh_missing_review",
                        "rationale": "方案要求安全性事件信息完整记录。",
                        "tradeoffs": ["聚焦AE记录内的日期完整性。"],
                        "deterministic_template": template,
                        "evidence_ids": evidence_ids,
                    },
                    "claims": [
                        {
                            "claim_id": "claim-rule-template-1",
                            "kind": "recommendation",
                            "text": "建议使用确定性字段条件识别待复核记录。",
                            "confidence": 0.9,
                            "uncertainty": "仅覆盖当前已激活字段映射可执行范围。",
                            "user_action": "选择后形成已确认规则模板。",
                            "evidence_ids": evidence_ids,
                        }
                    ],
                }
            ],
        }


@pytest.mark.parametrize(
    "build",
    (
        lambda value: RuleTemplateRecommendationStartRequest(
            expected_fact_state_version=value
        ),
        lambda value: RuleTemplateRecommendationDecisionRequest(
            decision=MonitoringAiCandidateStatus.REJECTED,
            expected_input_revision_sha256="a" * 64,
            expected_fact_state_version=value,
        ),
    ),
)
@pytest.mark.parametrize("value", (True, False, "1", "0"))
def test_rule_template_recommendation_cas_rejects_bool_like_values(
    build,
    value,
) -> None:
    with pytest.raises(ValidationError):
        build(value)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("mapping_content_sha256", f" {'a' * 64}"),
        ("capability_manifest_sha256", "A" * 64),
        ("effective_capabilities_sha256", 123),
    ),
)
def test_replay_identity_preserves_raw_mapping_hash_bytes(
    field: str,
    value: object,
) -> None:
    hash_values: dict[str, object] = {
        "mapping_content_sha256": "a" * 64,
        "capability_manifest_sha256": "b" * 64,
        "effective_capabilities_sha256": "c" * 64,
    }
    hash_values[field] = value
    identity = MonitoringRuleTemplateRecommendationService._immutable_identity(
        mapping_revision=" mapping-v1 ",
        **hash_values,
        candidate_id=" candidate-001 ",
    )

    assert identity[field] == (value if isinstance(value, str) else "")
    assert identity["mapping_revision"] == "mapping-v1"
    assert identity["recommendation_candidate_id"] == "candidate-001"


class MappingRepositoryView:
    def __init__(self, repository, mapping_revision: str):
        revision = repository.get_revision(PROJECT_ID, mapping_revision)
        fields = []
        for field in revision.fields:
            role = {
                "AETERM": "ae_term",
                "AESTDTC": "ae_start_date",
            }[field.source_field]
            fields.append(field.model_copy(update={"recommended_role": role}))
        self.revision = revision.model_copy(update={"fields": tuple(fields)})

    def get_revision(self, project_id: str, mapping_revision: str):
        assert project_id == PROJECT_ID
        assert mapping_revision == self.revision.mapping_revision
        return self.revision


def _setup(
    tmp_path: Path,
    *,
    fact_type: str = "safety_assessment",
    always_invalid: bool = False,
    block_ae_capability: bool = False,
):
    mapping_repository, mapping_revision = _seed_confirmed_mapping(tmp_path)
    activation_service = MonitoringMappingActivationService(
        mapping_repository,
        clock=lambda: NOW,
    )
    active = activation_service.activate_confirmed_revision(
        PROJECT_ID,
        mapping_revision,
        expected_project_version=0,
        activated_by="medical-manager",
        activation_reason="测试规则模板建议。",
        idempotency_key="activate-rule-template-test",
    ).state
    mapping_view = MappingRepositoryView(
        mapping_repository,
        mapping_revision,
    )
    active = replace(
        active,
        mapping_content_sha256=content_sha256(
            mapping_view.revision.model_dump(mode="json")
        ),
    )
    if block_ae_capability:
        capability_states = tuple(
            (
                MonitoringMappingCapabilitySnapshot(
                    capability_id=item.capability_id,
                    state="blocked_by_quality",
                    blocking_finding_group_ids=("test-blocker",),
                    limitation_codes=("missing_ae_role",),
                )
                if item.capability_id
                in {
                    "ae_mh_reconciliation",
                    "lab_ctcae_rules",
                    "standard_coding_rules",
                }
                else item
            )
            for item in active.capability_states
        )
        active = replace(
            active,
            activation_disposition="activate_restricted",
            capability_states=capability_states,
        )

    class ActivationView:
        def get_active_mapping(self, project_id: str):
            assert project_id == PROJECT_ID
            return active

    effective_activation = ActivationView()

    rule_repository = MonitoringProtocolRuleRepository(tmp_path / "rules.sqlite3")
    rule_repository.bind_gold_case_authority(lambda _case, _rule: None)
    ai_repository = MonitoringAiRepository(tmp_path / "ai.sqlite3")
    registry = FakeSourceRegistry()
    authoring = MonitoringRuleAuthoringService(
        repository=rule_repository,
        lifecycle_service=MonitoringRuleLifecycleService(rule_repository),
        protocol_rule_service=MonitoringProtocolRuleService(rule_repository),
        ai_repository=ai_repository,
        source_registry=registry,
    )
    version, _ = authoring.register_protocol_version(
        project_id=PROJECT_ID,
        source_entry_id="source-protocol",
        protocol_code="PROTO-001",
        version_label="V1.0",
        version_date="2026-07-01",
        applicability_status="project_effective_confirmed",
        operational_effective_from="2026-07-01",
    )
    protocol_candidate = _accepted_candidate(ai_repository)
    fact, _ = authoring.adopt_ai_candidate(
        project_id=PROJECT_ID,
        protocol_version_id=version.protocol_version_id,
        candidate_id=protocol_candidate.candidate_id,
        fact_key=f"{fact_type}.test",
        proposed_fact_type=fact_type,
        adoption_context={
            "protocol_version_id": version.protocol_version_id,
            "source_entry_id": version.source_entry_id,
            "source_content_sha256": version.content_sha256,
            "source_revision": "mpr_test",
            "candidate_snapshot_sha256": content_sha256(
                protocol_candidate.model_dump(mode="json")
            ),
            "adoption_basis": "medical_manager_explicit_selection",
        },
    )
    provider = RuleTemplateProvider(always_invalid=always_invalid)
    ai_service = MonitoringAiService(
        ai_repository,
        runtime_resolver=lambda: MonitoringAiRuntimeBinding(
            profile_id="independent-ai-test",
            provider=provider.provider_name,
            model=provider.model_name,
            env={
                "WORKBENCH_AI_PROVIDER": provider.provider_name,
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
                "WORKBENCH_AI_API_KEY": "test-key",
                "WORKBENCH_AI_MODEL": provider.model_name,
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": provider.model_name,
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            },
        ),
        provider_factory=lambda _env: provider,
    )
    service = MonitoringRuleTemplateRecommendationService(
        protocol_repository=rule_repository,
        mapping_repository=mapping_view,
        mapping_activation_service=effective_activation,
        ai_repository=ai_repository,
        ai_service=ai_service,
        rule_authoring_service=authoring,
    )
    return service, ai_service, ai_repository, rule_repository, registry, fact, provider


def test_precompiled_candidate_can_be_selected_idempotently_without_publication(
    tmp_path: Path,
) -> None:
    service, ai_service, ai_repo, rules, _registry, fact, provider = _setup(
        tmp_path
    )
    queued = service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert queued["status"] == "queued"
    run = ai_service.run_next("rule-template-worker")
    assert run.processed is True and run.job.status.value == "completed"
    assert provider.envelopes[0].task_type.value == "protocol_rule_extraction"
    assert provider.envelopes[0].payload["task_contract"]
    assert provider.envelopes[0].payload["candidate_types"] == [
        "deterministic_rule_template"
    ]
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert status["status"] == "candidate_review"
    candidate = status["candidates"][0]
    assert {
        (item["role"], item["domain"], item["field"])
        for item in candidate["mapping_fields"]
    } == {
        ("ae_verbatim_term", "AE", "AETERM"),
        ("ae_start_date", "AE", "AESTDTC"),
    }
    assert "provider" not in str(status).lower()
    first = service.decide(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        candidate_id=candidate["candidate_id"],
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        expected_input_revision_sha256=status["input_revision_sha256"],
        expected_fact_state_version=fact.state_version,
        actor="medical_manager",
        reason="选择该确定性核对逻辑。",
    )
    second = service.decide(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        candidate_id=candidate["candidate_id"],
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        expected_input_revision_sha256=status["input_revision_sha256"],
        expected_fact_state_version=fact.state_version,
        actor="medical_manager",
        reason="同一请求重试。",
    )
    assert first["status"] == "rule_template_selected"
    assert second["decision_reused"] is True
    assert first["compiled_rule"]["rule_family"] == "ae_mh_missing_review"
    assert rules.list_rule_packs(PROJECT_ID) == ()

    rule = first["compiled_rule"]
    assert rule["status"] == "confirmed"
    snapshot = provider.envelopes[0].payload["input_payload"][
        "rule_template_context"
    ]["mapping_snapshot"]
    assert rule["mapping_revision"] == snapshot["mapping_revision"]
    assert rule["mapping_content_sha256"] == snapshot["mapping_content_sha256"]
    assert (
        rule["capability_manifest_sha256"]
        == snapshot["capability_manifest_sha256"]
    )
    assert (
        rule["effective_capabilities_sha256"]
        == snapshot["effective_capabilities_sha256"]
    )
    assert rule["recommendation_candidate_id"] == candidate["candidate_id"]

    replayed = second["compiled_rule"]
    assert replayed == rule
    assert replayed["status"] == "confirmed"
    assert replayed["rule_revision_id"] == rule["rule_revision_id"]

    stored_candidate = next(
        item
        for item in ai_repo.candidates(PROJECT_ID, run.job.job_id)
        if item.candidate_id == candidate["candidate_id"]
    )
    assert (
        "immutable_identity"
        not in stored_candidate.structured_payload["deterministic_template"]
    )


def test_candidate_decision_requires_exact_input_revision_hash_bytes(
    tmp_path: Path,
) -> None:
    service, ai_service, _ai_repo, _rules, _registry, fact, _provider = _setup(
        tmp_path
    )
    service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    ai_service.run_next("rule-template-worker")
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    canonical = status["input_revision_sha256"]
    uppercase = next(
        (canonical.replace(letter, letter.upper(), 1) for letter in "abcdef" if letter in canonical),
        None,
    )
    assert uppercase is not None
    for malformed in (f" {canonical}", uppercase):
        with pytest.raises(
            MonitoringRuleTemplateRecommendationError,
            match="事实、方案或字段映射已变化",
        ) as raised:
            service.decide(
                project_id=PROJECT_ID,
                fact_revision_id=fact.fact_revision_id,
                candidate_id=status["candidates"][0]["candidate_id"],
                decision=MonitoringAiCandidateStatus.REJECTED,
                expected_input_revision_sha256=malformed,
                expected_fact_state_version=fact.state_version,
                actor="medical_manager",
                reason="拒绝非规范化摘要测试。",
            )
        assert raised.value.code == "monitoring_rule_template_input_stale"
        assert raised.value.http_status == 409


def test_accepted_recommendation_enters_shadow_without_second_rule_approval(
    tmp_path: Path,
) -> None:
    service, ai_service, _ai_repo, rules, _registry, fact, _provider = _setup(
        tmp_path
    )
    queued = service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert queued["status"] == "queued"
    run = ai_service.run_next("rule-template-worker")
    assert run.processed is True and run.job.status.value == "completed"
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    candidate = status["candidates"][0]
    decision = service.decide(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        candidate_id=candidate["candidate_id"],
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        expected_input_revision_sha256=status["input_revision_sha256"],
        expected_fact_state_version=fact.state_version,
        actor="medical_manager",
        reason="选择该确定性核对逻辑。",
    )
    confirmed_fact = decision["confirmed_fact"]
    draft = service.rule_authoring_service.create_draft(
        project_id=PROJECT_ID,
        protocol_version_id=confirmed_fact["protocol_version_id"],
        fact_revision_ids=[confirmed_fact["fact_revision_id"]],
        created_by="medical_manager",
    )
    _, draft_rules = rules.rule_pack(draft.rule_pack_id)
    assert draft_rules[0].status == "confirmed"
    assert draft_rules[0].rule_revision_id == (
        decision["compiled_rule"]["rule_revision_id"]
    )
    assert draft_rules[0].mapping_revision == (
        decision["compiled_rule"]["mapping_revision"]
    )

    shadow = MonitoringRuleLifecycleService(rules).start_shadow(
        draft.rule_pack_id,
        started_by="medical_manager",
    )
    assert shadow.status == "shadow"


@pytest.mark.parametrize(
    ("fact_type", "reason_code"),
    [
        ("study_treatment_regimen", "no_safe_deterministic_family"),
    ],
)
def test_unsupported_fact_is_manual_review_without_ai_job(
    tmp_path: Path,
    fact_type: str,
    reason_code: str,
) -> None:
    service, _ai_service, ai_repo, _rules, _registry, fact, _provider = _setup(
        tmp_path,
        fact_type=fact_type,
    )
    result = service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert result["status"] == "manual_review"
    assert result["reason_code"] == reason_code
    assert ai_repo.list_jobs(
        PROJECT_ID,
        task_type="rule_template_recommendation",
    ) == ()


def test_blocked_mapping_capability_fails_closed_without_ai_job(
    tmp_path: Path,
) -> None:
    service, _ai_service, ai_repo, _rules, _registry, fact, _provider = _setup(
        tmp_path,
        block_ae_capability=True,
    )
    result = service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert result["status"] == "manual_review"
    assert result["reason_code"] == "mapping_capability_blocked"
    assert ai_repo.list_jobs(
        PROJECT_ID,
        task_type="rule_template_recommendation",
    ) == ()


def test_candidate_decision_handles_transition_to_manual_review_without_type_error(
    tmp_path: Path,
) -> None:
    service, ai_service, _ai_repo, _rules, _registry, fact, _provider = _setup(
        tmp_path
    )
    service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    ai_service.run_next("rule-template-worker")
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    active = service.mapping_activation_service.get_active_mapping(PROJECT_ID)
    capability_states = tuple(
        (
            MonitoringMappingCapabilitySnapshot(
                capability_id=item.capability_id,
                state="blocked_by_quality",
                blocking_finding_group_ids=("late-quality-blocker",),
                limitation_codes=("mapping_quality_changed",),
            )
            if item.capability_id
            in {
                "ae_mh_reconciliation",
                "lab_ctcae_rules",
                "standard_coding_rules",
            }
            else item
        )
        for item in active.capability_states
    )
    transitioned = replace(
        active,
        activation_disposition="activate_restricted",
        capability_states=capability_states,
    )

    class ManualTransitionActivation:
        def get_active_mapping(self, project_id: str):
            assert project_id == PROJECT_ID
            return transitioned

    service.mapping_activation_service = ManualTransitionActivation()
    with pytest.raises(
        MonitoringRuleTemplateRecommendationError,
        match="补充或确认字段映射",
    ) as raised:
        service.decide(
            project_id=PROJECT_ID,
            fact_revision_id=fact.fact_revision_id,
            candidate_id=status["candidates"][0]["candidate_id"],
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            expected_input_revision_sha256=status["input_revision_sha256"],
            expected_fact_state_version=fact.state_version,
            actor="medical_manager",
            reason="能力状态变化后的选择。",
        )
    assert raised.value.code == "monitoring_rule_template_no_longer_available"
    assert raised.value.http_status == 409


def test_invalid_dsl_still_fails_after_one_controlled_repair(
    tmp_path: Path,
) -> None:
    service, ai_service, ai_repo, _rules, _registry, fact, provider = _setup(
        tmp_path,
        always_invalid=True,
    )
    queued = service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    result = ai_service.run_next("invalid-rule-template-worker")
    assert result.job.status.value == "failed"
    assert result.job.failure_code == "invalid_ai_output"
    assert provider.run_count == 2
    assert ai_repo.candidates(PROJECT_ID, result.job.job_id) == ()
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    assert status["status"] == "failed"
    assert status["candidates"] == []
    assert status["input_revision_sha256"] == queued["input_revision_sha256"]


def test_source_drift_and_opposite_decision_fail_closed(tmp_path: Path) -> None:
    service, ai_service, _ai_repo, _rules, registry, fact, _provider = _setup(
        tmp_path
    )
    service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    ai_service.run_next("rule-template-worker")
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    candidate_id = status["candidates"][0]["candidate_id"]
    accepted = service.decide(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        expected_input_revision_sha256=status["input_revision_sha256"],
        expected_fact_state_version=fact.state_version,
        actor="medical_manager",
        reason="选择。",
    )
    assert accepted["status"] == "rule_template_selected"
    with pytest.raises(
        MonitoringRuleTemplateRecommendationError,
        match="不能改为驳回",
    ):
        service.decide(
            project_id=PROJECT_ID,
            fact_revision_id=fact.fact_revision_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.REJECTED,
            expected_input_revision_sha256=status["input_revision_sha256"],
            expected_fact_state_version=fact.state_version,
            actor="medical_manager",
            reason="反向决定。",
        )

    registry.entries[PROJECT_ID][0].content_hash = "f" * 64
    with pytest.raises(
        MonitoringRuleTemplateRecommendationError,
        match="来源已变化",
    ):
        service.decide(
            project_id=PROJECT_ID,
            fact_revision_id=fact.fact_revision_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            expected_input_revision_sha256=status["input_revision_sha256"],
            expected_fact_state_version=fact.state_version,
            actor="medical_manager",
            reason="来源漂移后的重试。",
        )


def test_mapping_content_drift_fails_closed_before_candidate_visibility(
    tmp_path: Path,
) -> None:
    service, _ai_service, _ai_repo, _rules, _registry, fact, _provider = _setup(
        tmp_path
    )
    active = service.mapping_activation_service.get_active_mapping(PROJECT_ID)

    class DriftedActivation:
        def get_active_mapping(self, project_id: str):
            assert project_id == PROJECT_ID
            return replace(
                active,
                mapping_content_sha256="e" * 64,
            )

    service.mapping_activation_service = DriftedActivation()
    with pytest.raises(
        MonitoringRuleTemplateRecommendationError,
        match="不可变版本不一致",
    ):
        service.start(
            project_id=PROJECT_ID,
            fact_revision_id=fact.fact_revision_id,
            expected_fact_state_version=fact.state_version,
        )


def test_rejected_candidate_is_idempotent_and_cannot_be_accepted_later(
    tmp_path: Path,
) -> None:
    service, ai_service, _ai_repo, _rules, _registry, fact, _provider = _setup(
        tmp_path
    )
    service.start(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    ai_service.run_next("rule-template-worker")
    status = service.status(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        expected_fact_state_version=fact.state_version,
    )
    candidate_id = status["candidates"][0]["candidate_id"]
    first = service.decide(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.REJECTED,
        expected_input_revision_sha256=status["input_revision_sha256"],
        expected_fact_state_version=fact.state_version,
        actor="medical_manager",
        reason="不采用该规则模板。",
    )
    second = service.decide(
        project_id=PROJECT_ID,
        fact_revision_id=fact.fact_revision_id,
        candidate_id=candidate_id,
        decision=MonitoringAiCandidateStatus.REJECTED,
        expected_input_revision_sha256=status["input_revision_sha256"],
        expected_fact_state_version=fact.state_version,
        actor="medical_manager",
        reason="同一驳回请求重试。",
    )
    assert first["status"] == "user_rejected"
    assert second["decision_reused"] is True
    with pytest.raises(
        MonitoringRuleTemplateRecommendationError,
        match="相反决定",
    ):
        service.decide(
            project_id=PROJECT_ID,
            fact_revision_id=fact.fact_revision_id,
            candidate_id=candidate_id,
            decision=MonitoringAiCandidateStatus.ACCEPTED,
            expected_input_revision_sha256=status["input_revision_sha256"],
            expected_fact_state_version=fact.state_version,
            actor="medical_manager",
            reason="反向选择。",
        )


def test_api_returns_user_state_without_ai_runtime_internals(tmp_path: Path) -> None:
    service, ai_service, _ai_repo, _rules, _registry, fact, _provider = _setup(
        tmp_path
    )
    app = FastAPI()
    app.include_router(
        create_monitoring_rule_template_recommendation_router(
            service=service,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    base = (
        f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
        f"rule-template-recommendations/facts/{fact.fact_revision_id}"
    )
    started = client.post(
        f"{base}/start",
        json={"expected_fact_state_version": fact.state_version},
    )
    assert started.status_code == 202
    ai_service.run_next("api-rule-template-worker")
    status = client.get(
        f"{base}/status",
        params={"expected_fact_state_version": fact.state_version},
    )
    assert status.status_code == 200
    serialized = str(status.json()).lower()
    assert "provider" not in serialized
    assert "prompt" not in serialized
    assert "job_id" not in serialized
