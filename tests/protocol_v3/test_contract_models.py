from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    ApplicabilityEntry,
    ApplicabilitySnapshot,
    CanonicalState,
    ChapterContract,
    ChapterLockSnapshot,
    ClaimEvidenceLink,
    DecisionRecord,
    DomainEvent,
    EvidenceUnit,
    ExecutionReservation,
    MedicalAdmissionUnit,
    NodeExecutionContract,
    NormalizedResearchSeed,
    ProjectionArtifact,
    RecommendationOption,
    ResearchSeed,
    SemanticBlock,
    SemanticDocumentRevision,
    SkillDefinition,
    SourceAcquisitionPlan,
    SourceArtifact,
    StudyDefinitionV3,
    SubmissionEvidencePackage,
    SubstantiveContentContract,
    WorkflowRun,
    assert_canonical_state_transition,
)


NOW = datetime(2026, 8, 10, 10, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 8, 10, 10, 30, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


CORE_MODELS = (
    ResearchSeed,
    NormalizedResearchSeed,
    SourceAcquisitionPlan,
    SourceArtifact,
    EvidenceUnit,
    MedicalAdmissionUnit,
    ClaimEvidenceLink,
    RecommendationOption,
    DecisionRecord,
    StudyDefinitionV3,
    ApplicabilitySnapshot,
    ChapterContract,
    SubstantiveContentContract,
    SemanticBlock,
    SemanticDocumentRevision,
    ChapterLockSnapshot,
    SkillDefinition,
    NodeExecutionContract,
    ExecutionReservation,
    WorkflowRun,
    DomainEvent,
    ProjectionArtifact,
    SubmissionEvidencePackage,
)


def _research_seed(**overrides):
    payload = {
        "research_seed_id": "seed:uc301",
        "research_drug_raw": "研究药物 A",
        "dosage_form_and_route_raw": "口服片剂，每日一次",
        "anticipated_dose_raw": "10 mg 或 20 mg",
        "target_or_mechanism_raw": "选择性靶点 X 抑制剂",
        "indication_raw": "中重度活动性溃疡性结肠炎",
        "clinical_phase_raw": "III期",
        "populations_raw": ("成人",),
        "comparator_raw": "安慰剂",
        "created_at": NOW,
    }
    payload.update(overrides)
    return ResearchSeed(**payload)


def _study_definition(**overrides):
    payload = {
        "study_definition_id": "study:def:uc301",
        "project_id": "project:uc301",
        "revision": 1,
        "normalized_seed_id": "seed:uc301:normalized",
        "normalized_seed_sha256": SHA_A,
        "facts": {
            "picos.population.indication": "中重度活动性溃疡性结肠炎",
            "picos.intervention.dose": "10 mg 或 20 mg，每日一次",
        },
        "decision_record_ids": ("decision:dose",),
        "updated_at": NOW,
    }
    payload.update(overrides)
    return StudyDefinitionV3(**payload)


def _workflow_run(**overrides):
    payload = {
        "workflow_run_id": "run:uc301:001",
        "graph_version": "protocol-v3.1",
        "graph_sha256": SHA_A,
        "contract_schema_version": "mw_protocol_v3_contract_v1",
        "template_version": "tp-ma-07-v1",
        "template_sha256": SHA_B,
        "skill_definition_ids": ("skill:coordinator:v1",),
        "skill_definition_hashes": (SHA_C,),
        "source_revision_hashes": (SHA_D,),
        "study_definition_id": "study:def:uc301",
        "study_definition_sha256": SHA_A,
        "status": "running",
        "display_progress": 0.25,
        "journey_counter": 3,
        "created_at": NOW,
        "updated_at": NOW,
    }
    payload.update(overrides)
    return WorkflowRun(**payload)


def _semantic_block(**overrides):
    payload = {
        "semantic_block_id": "block:introduction:001",
        "semantic_node_id": "node:introduction",
        "chapter_contract_id": "contract:introduction:v1",
        "substantive_content_contract_id": "content:introduction:v1",
        "block_kind": "paragraph",
        "content": "本研究拟评价研究药物 A 用于目标人群的有效性与安全性。",
        "fact_paths": ("picos.population.indication",),
        "claim_evidence_link_ids": ("link:introduction:001",),
        "medical_admission_unit_ids": ("admission:introduction:001",),
        "content_sha256": SHA_A,
    }
    payload.update(overrides)
    return SemanticBlock(**payload)


def test_all_minimum_contracts_are_strict_versioned_and_have_stable_identity():
    for model in CORE_MODELS:
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False, model.__name__
        assert "schema_version" in model.model_fields, model.__name__
        assert any(name.endswith("_id") for name in model.model_fields), model.__name__


def test_research_seed_preserves_raw_input_and_rejects_extra_or_naive_time():
    seed = _research_seed()
    assert seed.research_drug_raw == "研究药物 A"
    assert seed.schema_version == "mw_protocol_v3_contract_v1"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        _research_seed(backend_status="ok")
    with pytest.raises(ValidationError, match="explicit timezone"):
        _research_seed(created_at=datetime(2026, 8, 10, 10, 0))
    with pytest.raises(ValidationError):
        _research_seed(research_seed_id="UC 301")


def test_canonical_state_machine_accepts_only_forward_declared_edges():
    happy_path = (
        CanonicalState.RAW,
        CanonicalState.NORMALIZED,
        CanonicalState.PROPOSED,
        CanonicalState.CONFIRMED,
        CanonicalState.FROZEN,
        CanonicalState.SUPERSEDED,
    )
    for current, target in zip(happy_path, happy_path[1:]):
        assert assert_canonical_state_transition(current, target) is target

    assert (
        assert_canonical_state_transition("confirmed", "quarantined")
        is CanonicalState.QUARANTINED
    )
    for current, target in (
        ("confirmed", "proposed"),
        ("frozen", "confirmed"),
        ("raw", "raw"),
        ("superseded", "frozen"),
        ("quarantined", "normalized"),
    ):
        with pytest.raises(ValueError, match="illegal canonical state transition"):
            assert_canonical_state_transition(current, target)


def test_source_artifact_requires_complete_immutable_identity_and_valid_sha():
    original = SourceArtifact(
        source_artifact_id="artifact:guideline:001",
        logical_source_key="NMPA/UC-guideline/current",
        content_sha256=SHA_A,
        source_role="regulatory_or_guideline",
        source_version="2026版",
        jurisdiction="中国",
        mime_type="application/pdf",
        captured_at=NOW,
    )
    assert original.parent_artifact_id is None

    base = original.model_dump(
        exclude={
            "schema_version",
            "derivation_kind",
            "parent_artifact_id",
            "parent_content_sha256",
        }
    )
    for partial_parent_identity in (
        {"parent_artifact_id": "artifact:guideline:source"},
        {"parent_content_sha256": SHA_B},
    ):
        with pytest.raises(ValidationError, match="both ID and hash"):
            SourceArtifact(**base, **partial_parent_identity)
        with pytest.raises(ValidationError, match="both ID and hash"):
            SourceArtifact(
                **base,
                derivation_kind="translation",
                **partial_parent_identity,
            )
    derived = SourceArtifact(
        **{**base, "source_artifact_id": "artifact:guideline:translation"},
        derivation_kind="translation",
        parent_artifact_id="artifact:guideline:001",
        parent_content_sha256=SHA_A,
    )
    assert derived.parent_artifact_id == original.source_artifact_id
    with pytest.raises(ValidationError):
        original.model_copy(update={"content_sha256": "A" * 64}).model_validate(
            {**original.model_dump(), "content_sha256": "A" * 64}
        )


def test_unknown_evidence_class_fails_closed():
    with pytest.raises(ValidationError):
        RecommendationOption(
            recommendation_option_id="option:dose:001",
            decision_key="decision:dose",
            label="10 mg，每日一次",
            rationale="与最相关竞品方案和现有暴露资料一致。",
            evidence_class="model_confidence",
            uncertainty="研究药物人体暴露数据仍有限。",
            downstream_impact="影响治疗组、样本量和访视安排。",
            is_default=True,
        )


def test_decision_record_requires_unique_options_selected_membership_and_cas():
    base = {
        "decision_record_id": "decision:record:dose:001",
        "decision_key": "decision:dose",
        "snapshot_sha256": SHA_A,
        "expected_state_revision": 2,
        "state_revision": 3,
        "option_ids": ("option:dose:001", "option:dose:002"),
        "selected_option_id": "option:dose:001",
        "actor_type": "user",
        "actor_id": "user:medical-writer",
        "reason": "接受 AI 推荐的默认剂量设计。",
        "decided_at": NOW,
    }
    assert DecisionRecord(**base).state_revision == 3

    with pytest.raises(ValidationError, match="duplicate IDs"):
        DecisionRecord(**{**base, "option_ids": ("option:dose:001",) * 2})
    with pytest.raises(ValidationError, match="selected_option_id"):
        DecisionRecord(**{**base, "selected_option_id": "option:dose:003"})
    with pytest.raises(ValidationError, match="CAS revision"):
        DecisionRecord(**{**base, "state_revision": 4})


def test_source_plan_preserves_three_denominators_and_version_discipline():
    base = {
        "source_acquisition_plan_id": "source-plan:uc301:v1",
        "normalized_seed_id": "seed:uc301:normalized",
        "normalized_seed_sha256": SHA_A,
        "source_categories": (
            "project_or_investigator_brochure",
            "regulatory",
            "guideline_or_consensus",
            "trial_registry",
            "competitor_protocol",
            "endpoint_or_instrument",
            "peer_reviewed",
            "company_template_or_corpus",
        ),
        "registries_and_sites": ("ClinicalTrials.gov", "NMPA"),
        "query_families": ("适应症+靶点", "适应症+机制+分期"),
        "jurisdiction": "中国",
        "search_start_date": date(2016, 1, 1),
        "search_end_date": date(2026, 8, 10),
        "inclusion_rules": ("与目标人群、机制或设计问题相关",),
        "exclusion_rules": ("无法核验来源身份",),
        "version_rules": ("监管与指南优先采用现行最新版",),
        "completeness_rules": ("有公开链接的竞品方案须完整下载并可解析",),
        "required_discovery_denominator": 8,
        "researched_competitor_denominator": 12,
        "linked_protocol_denominator": 7,
        "created_at": NOW,
    }
    plan = SourceAcquisitionPlan(**base)
    assert plan.linked_protocol_denominator == 7

    with pytest.raises(ValidationError, match="cannot exceed"):
        SourceAcquisitionPlan(**{**base, "linked_protocol_denominator": 13})
    with pytest.raises(ValidationError, match="duplicate IDs"):
        SourceAcquisitionPlan(
            **{**base, "query_families": ("适应症+靶点", "适应症+靶点")}
        )


def test_medical_admission_requires_resolvable_locator_and_unique_bindings():
    base = {
        "medical_admission_unit_id": "admission:objective:001",
        "evidence_unit_ids": ("evidence:objective:001",),
        "claim_type": "study_objective",
        "fact_paths": ("picos.outcome.primary",),
        "source_roles": ("competitor_full_protocol",),
        "relation": "supports",
        "locator_kind": "body",
        "locator": "docx:paragraph:141",
        "context_window": "前后各两个完整段落",
        "quality_score": 0.93,
        "semantic_node_ids": ("node:study-objectives",),
        "chapter_contract_ids": ("contract:study-objectives:v1",),
        "source_content_sha256": SHA_A,
        "admitted_at": NOW,
    }
    assert MedicalAdmissionUnit(**base).quality_score == 0.93

    with pytest.raises(ValidationError):
        MedicalAdmissionUnit(**{**base, "locator_kind": "page"})
    with pytest.raises(ValidationError, match="duplicate IDs"):
        MedicalAdmissionUnit(
            **{**base, "evidence_unit_ids": ("evidence:objective:001",) * 2}
        )


def test_chapter_and_substantive_contracts_reject_vacuous_rules():
    chapter_base = {
        "chapter_contract_id": "contract:objectives:v1",
        "semantic_node_id": "node:study-objectives",
        "contract_version": "1.0.0",
        "template_id": "template:tp-ma-07",
        "template_sha256": SHA_A,
        "chapter_skill_id": "skill:chapter:objectives",
        "chapter_skill_version": "1.0.0",
        "positive_qc_rules": ("主要目的必须与主要终点形成一一映射",),
        "word_block_schema": "paragraph-list-v1",
    }
    with pytest.raises(ValidationError, match="vacuous"):
        ChapterContract(**chapter_base)
    assert ChapterContract(
        **chapter_base,
        required_fact_paths=("picos.outcome.primary",),
        required_claim_types=("primary_objective",),
    ).canonical_state is CanonicalState.FROZEN

    substantive_base = {
        "substantive_content_contract_id": "content:objectives:v1",
        "chapter_contract_id": "contract:objectives:v1",
        "skeleton_risk_rules": ("只有标题或通用模板句即失败",),
    }
    with pytest.raises(ValidationError, match="vacuous"):
        SubstantiveContentContract(**substantive_base)
    assert SubstantiveContentContract(
        **substantive_base,
        required_claim_types=("primary_objective",),
        required_fact_paths=("picos.outcome.primary",),
    ).required_claim_types == ("primary_objective",)


def test_applicability_snapshot_rejects_duplicate_semantic_nodes():
    entry = ApplicabilityEntry(
        applicability_entry_id="applicability:node:001",
        semantic_node_id="node:pregnancy",
        status="conditional",
        reason="是否纳入育龄女性取决于已确认人群与风险控制事实。",
        triggering_fact_paths=("picos.population.sex",),
        rule_id="rule:pregnancy:001",
    )
    base = {
        "applicability_snapshot_id": "applicability:uc301:v1",
        "study_definition_id": "study:def:uc301",
        "study_definition_sha256": SHA_A,
        "ruleset_id": "ruleset:tp-ma-07",
        "ruleset_version": "1.0.0",
        "ruleset_sha256": SHA_B,
        "entries": (entry,),
        "created_at": NOW,
    }
    assert ApplicabilitySnapshot(**base).entries[0].status.value == "conditional"
    duplicate = entry.model_copy(
        update={"applicability_entry_id": "applicability:node:002"}
    )
    with pytest.raises(ValidationError, match="semantic_node_ids"):
        ApplicabilitySnapshot(**{**base, "entries": (entry, duplicate)})


def test_material_hash_ignores_runtime_progress_time_and_journey_counter():
    first = _workflow_run()
    display_only_change = _workflow_run(
        display_progress=0.91,
        journey_counter=29,
        updated_at=LATER,
    )
    material_change = _workflow_run(source_revision_hashes=(SHA_A,))

    assert first.material_sha256() == display_only_change.material_sha256()
    assert first.material_sha256() != material_change.material_sha256()


def test_material_hash_uses_content_not_revision_or_lifecycle_state():
    first = _study_definition()
    same_content_new_revision = _study_definition(
        revision=2,
        previous_revision_sha256=SHA_B,
        updated_at=LATER,
        canonical_state="confirmed",
    )
    changed_fact = _study_definition(
        facts={
            "picos.population.indication": "中重度活动性溃疡性结肠炎",
            "picos.intervention.dose": "20 mg，每日一次",
        }
    )
    assert first.material_sha256() == same_content_new_revision.material_sha256()
    assert first.material_sha256() != changed_fact.material_sha256()


def test_semantic_revision_rejects_duplicate_block_identity():
    block = _semantic_block()
    base = {
        "semantic_document_revision_id": "document:uc301:001",
        "project_id": "project:uc301",
        "revision": 1,
        "study_definition_id": "study:def:uc301",
        "study_definition_sha256": SHA_A,
        "applicability_snapshot_id": "applicability:uc301:v1",
        "applicability_snapshot_sha256": SHA_B,
        "semantic_blocks": (block,),
        "chapter_contract_hashes": (SHA_C,),
        "updated_at": NOW,
    }
    assert SemanticDocumentRevision(**base).revision == 1
    with pytest.raises(ValidationError, match="semantic_block_ids"):
        SemanticDocumentRevision(**{**base, "semantic_blocks": (block, block)})


def test_execution_reservation_terminal_result_is_explainable_and_closed():
    base = {
        "execution_reservation_id": "reservation:call:001",
        "node_execution_contract_id": "execution:contract:001",
        "logical_call_id": "call:chapter:001",
        "idempotency_key": "call:chapter:001@input-a",
        "input_sha256": SHA_A,
        "attempt": 1,
        "transport_attempts": 1,
        "provider_session_id": "provider-session-001",
        "reserved_at": NOW,
        "updated_at": LATER,
    }
    completed = ExecutionReservation(
        **base,
        status="completed",
        terminal_state="completed",
        output_sha256=SHA_B,
    )
    assert completed.output_sha256 == SHA_B

    with pytest.raises(ValidationError, match="require an error"):
        ExecutionReservation(
            **base,
            status="unknown_outcome",
            terminal_state="unknown_outcome",
        )
    with pytest.raises(ValidationError, match="must match"):
        ExecutionReservation(
            **base,
            status="failed",
            terminal_state="completed",
            error_code="error:model:timeout",
        )
    with pytest.raises(ValidationError, match="non-terminal"):
        ExecutionReservation(**base, status="running", output_sha256=SHA_B)


def test_projection_requires_complete_word_receipt_identity():
    base = {
        "projection_artifact_id": "projection:docx:001",
        "projection_kind": "docx",
        "workflow_run_id": "run:uc301:001",
        "study_definition_id": "study:def:uc301",
        "study_definition_sha256": SHA_A,
        "semantic_document_revision_id": "document:uc301:001",
        "semantic_document_sha256": SHA_B,
        "content_sha256": SHA_C,
        "created_at": NOW,
    }
    with pytest.raises(ValidationError, match="require a Word receipt"):
        ProjectionArtifact(**base)
    with pytest.raises(ValidationError, match="must be complete"):
        ProjectionArtifact(**base, word_receipt_id="word-receipt:001")
    assert ProjectionArtifact(
        **base,
        word_receipt_id="word-receipt:001",
        word_receipt_sha256=SHA_D,
    ).projection_kind.value == "docx"


def test_contracts_are_immutable_after_validation():
    seed = _research_seed()
    with pytest.raises(ValidationError, match="frozen"):
        seed.indication_raw = "另一适应症"
