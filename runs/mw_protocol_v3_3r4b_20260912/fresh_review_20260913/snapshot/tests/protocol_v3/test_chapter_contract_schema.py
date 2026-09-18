"""Task3R.2 red-first schema tests for the explicit versioned chapter contract v2.

The v1 ``ChapterContract`` / ``SubstantiveContentContract`` classes must stay
byte-compatible: the pinned serialization and material hashes below were
captured before any v2 implementation and must never change.  The v2 types are
additive, explicitly versioned, and composed of typed value contracts (no
dictionaries or free-text checklists).
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts.protocol_v3 import (
    ChapterContract,
    ChapterContractV2,
    ChapterLockSnapshot,
    ClaimRequirement,
    CriticalToQualityItem,
    ConditionalApplicabilityRule,
    DependencyRepairPolicy,
    EvidenceSourceRequirement,
    FactRequirement,
    NodeExecutionContract,
    PatientParticipationObligation,
    PositiveQcRule,
    RegistryConsistencyObligation,
    RepairStep,
    SemanticDocumentRevision,
    StructuralObjectObligation,
    SubstantiveContentContract,
    SubstantiveContentContractV2,
    WordFormattingRules,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64

# ---------------------------------------------------------------------------
# v1 pins (captured before v2 implementation; these must never move).
# ---------------------------------------------------------------------------

CHAPTER_CONTRACT_V1_PIN_JSON = '{"schema_version":"mw_protocol_v3_contract_v1","canonical_state":"frozen","chapter_contract_id":"contract:objectives:v1","semantic_node_id":"node:study-objectives","contract_version":"1.0.0","template_id":"template:tp-ma-07","template_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","chapter_skill_id":"skill:chapter:objectives","chapter_skill_version":"1.0.0","required_fact_paths":["picos.outcome.primary"],"required_admission_claim_types":[],"required_source_roles":["competitor_full_protocol"],"required_claim_types":["primary_objective"],"required_structural_objects":["paragraph"],"positive_qc_rules":["主要目的必须与主要终点形成一一映射"],"word_block_schema":"paragraph-list-v1","dependency_ids":["contract:background:v1"]}'

SUBSTANTIVE_CONTENT_CONTRACT_V1_PIN_JSON = '{"schema_version":"mw_protocol_v3_contract_v1","canonical_state":"frozen","substantive_content_contract_id":"content:objectives:v1","chapter_contract_id":"contract:objectives:v1","required_claim_types":["primary_objective"],"required_fact_paths":["picos.outcome.primary"],"minimum_source_roles":["competitor_full_protocol"],"required_admission_claim_types":["study_objective"],"project_specific_elements":["UC301 主要终点定义"],"required_structural_objects":["paragraph"],"required_object_cells":["soa:visit:week12"],"skeleton_risk_rules":["只有标题或通用模板句即失败"]}'

CHAPTER_CONTRACT_V1_MATERIAL_SHA256 = "f34ab58cbc2c5cbb911ad880c78be460da95f0a722d7f6e90301b82d42244f52"
SUBSTANTIVE_CONTENT_CONTRACT_V1_MATERIAL_SHA256 = "5f9619dc40a0ec1cb3e90bde3f5cd2feb4cbb659cf6865eeea791a76a54831f0"
SEMANTIC_DOCUMENT_REVISION_V1_MATERIAL_SHA256 = "b42241126ecb1c748243419bda061e5cd1e77d76317f742055411e84b1825e9f"
SEMANTIC_DOCUMENT_REVISION_V1_COMPACT_MATERIAL_SHA256 = "857cbc1ed44d1d8e30f0d9b2cc3b525bc9a1adcb5c5da1c22859ab181e937052"
CHAPTER_LOCK_SNAPSHOT_V1_MATERIAL_SHA256 = "1a1a0ee92f96915cdd91e4d1320c76818b468e53518aa0aa845699d5e815c03d"
CHAPTER_LOCK_SNAPSHOT_V1_COMPACT_MATERIAL_SHA256 = "6faffaf679652705ab5c21df247fef885493d08158df215374b2b790492e2d69"
NODE_EXECUTION_CONTRACT_V1_MATERIAL_SHA256 = "6126c9a83369b7e73b1f6815059a8c5807873b756ca112257b37e605d696ac21"
NODE_EXECUTION_CONTRACT_V1_COMPACT_MATERIAL_SHA256 = "abac96f1c115fcf2bb487a115eebde024a0c76c5b8ab427dac062be3cae093e8"


def _chapter_contract_v1():
    return ChapterContract(
        chapter_contract_id="contract:objectives:v1",
        semantic_node_id="node:study-objectives",
        contract_version="1.0.0",
        template_id="template:tp-ma-07",
        template_sha256=SHA_A,
        chapter_skill_id="skill:chapter:objectives",
        chapter_skill_version="1.0.0",
        required_fact_paths=("picos.outcome.primary",),
        required_claim_types=("primary_objective",),
        required_source_roles=("competitor_full_protocol",),
        required_structural_objects=("paragraph",),
        positive_qc_rules=("主要目的必须与主要终点形成一一映射",),
        word_block_schema="paragraph-list-v1",
        dependency_ids=("contract:background:v1",),
    )


def _substantive_content_contract_v1():
    return SubstantiveContentContract(
        substantive_content_contract_id="content:objectives:v1",
        chapter_contract_id="contract:objectives:v1",
        required_claim_types=("primary_objective",),
        required_fact_paths=("picos.outcome.primary",),
        minimum_source_roles=("competitor_full_protocol",),
        required_admission_claim_types=("study_objective",),
        project_specific_elements=("UC301 主要终点定义",),
        required_structural_objects=("paragraph",),
        required_object_cells=("soa:visit:week12",),
        skeleton_risk_rules=("只有标题或通用模板句即失败",),
    )


# ---------------------------------------------------------------------------
# v2 typed entry builders.
# ---------------------------------------------------------------------------


def _fact_requirements():
    return (
        FactRequirement(
            fact_path="picos.outcome.primary",
            obligation="required",
            rationale="研究目的必须回链到已确认的主要终点事实。",
        ),
        FactRequirement(
            fact_path="picos.population.sex",
            obligation="optional",
            rationale="仅在人群包含育龄女性时引用。",
        ),
        FactRequirement(
            fact_path="picos.intervention.dose_legacy",
            obligation="forbidden",
            rationale="已被新版剂量事实取代，禁止引用。",
        ),
    )


def _claim_requirements():
    return (
        ClaimRequirement(
            claim_type="primary_objective",
            obligation="required",
            rationale="研究目的章必须声明主要目的。",
        ),
        ClaimRequirement(
            claim_type="exploratory_comparison",
            obligation="allowed",
            rationale="允许探索性对比，但不作要求。",
        ),
        ClaimRequirement(
            claim_type="superiority_claim",
            obligation="qualified",
            qualifying_conditions=("仅在主要终点显著且与已采信竞品证据一致时",),
            rationale="优效表述必须满足限定条件。",
        ),
        ClaimRequirement(
            claim_type="marketing_claim",
            obligation="forbidden",
            rationale="协议正文禁止营销性表述。",
        ),
    )


def _evidence_requirement(**overrides):
    payload = {
        "source_roles": ("competitor_full_protocol", "regulatory_or_guideline"),
        "admission_claim_types": ("study_objective",),
        "allowed_locator_kinds": ("body", "table"),
        "require_context_window": True,
        "minimum_quality_score": 0.85,
    }
    payload.update(overrides)
    return EvidenceSourceRequirement(**payload)


def _structural_object_obligations():
    return (
        StructuralObjectObligation(
            object_kind="paragraph",
            minimum_occurrences=2,
            project_specific_specification="研究目的段必须逐条映射 UC301 的主要与次要目的。",
        ),
        StructuralObjectObligation(
            object_kind="schedule_of_activities",
            minimum_occurrences=1,
            project_specific_specification="SOA 必须呈现 UC301 12周给药访视行。",
        ),
    )


def _word_rules():
    return WordFormattingRules(
        word_formatting_rules_id="word:rules:objectives",
        required_styles=("Heading 2", "List Paragraph"),
        forbidden_styles=("Heading 1",),
        required_bookmarks=("bm_primary_endpoint",),
        required_cross_references=("soa_table_1",),
    )


def _conditional_rule():
    return ConditionalApplicabilityRule(
        conditional_applicability_rule_id="applicability:pregnancy",
        triggering_fact_paths=("picos.population.sex",),
        condition="已确认人群包含育龄女性",
        rationale="妊娠相关义务仅在人群包含育龄女性时生效。",
        required_when_active_fact_paths=("picos.risk.pregnancy_contraception",),
        required_when_active_structural_objects=("paragraph",),
    )


def _repair_policy(**overrides):
    payload = {
        "dependency_repair_policy_id": "repair:objectives:policy",
        "dependency_ids": ("contract:background:v1",),
        "downstream_impact": "上游背景章修订后，研究目的章的事实引用与表述必须同步修订。",
        "repair_owner": "ai",
        "max_repair_attempts": 3,
        "repair_steps": (
            RepairStep(
                repair_step_id="repair:step:recheck",
                sequence=1,
                action="重读上游修订差异并重算受影响的事实引用。",
                owner="ai",
            ),
            RepairStep(
                repair_step_id="repair:step:escalate",
                sequence=2,
                action="有界修复失败后升级给医学撰写人确认。",
                owner="user",
            ),
        ),
    }
    payload.update(overrides)
    return DependencyRepairPolicy(**payload)


def _qc_rule():
    return PositiveQcRule(
        positive_qc_rule_id="qc:objectives:mapping",
        rule="主要目的与主要终点一一映射，并给出事实路径回链。",
    )


def _ctq_item():
    return CriticalToQualityItem(
        ctq_item_id="ctq:objectives:mapping",
        question="主要目的是否与主要终点一一映射？",
        linked_fact_paths=("picos.outcome.primary",),
        linked_claim_types=("primary_objective",),
        positive_qc_rule_ids=("qc:objectives:mapping",),
        risk_if_unmet="目的与终点脱节会导致研究目的章整体不可用。",
    )


def _participation_obligation(**overrides):
    payload = {
        "patient_participation_obligation_id": "participation:uc301:001",
        "decision_record_id": "decision:record:participation:001",
        "decision_record_sha256": SHA_B,
        "participation_status": "non_participation_with_reason",
        "ai_prepared_reason": "AI 依据用户已批准的参与决策整理原因，仅作产品追溯。",
    }
    payload.update(overrides)
    return PatientParticipationObligation(**payload)


def _registry_obligation(**overrides):
    payload = {
        "registry_consistency_obligation_id": "registry:uc301:ctgov",
        "registry_name": "ClinicalTrials.gov",
        "eligibility_fact_paths": ("eligibility.age.min", "eligibility.inclusion.ecog"),
        "consistency_rules": ("入选排除标准必须与注册表登记字段逐条一致。",),
    }
    payload.update(overrides)
    return RegistryConsistencyObligation(**payload)


def _content_contract_v2(**overrides):
    payload = {
        "substantive_content_contract_id": "content:objectives:v2",
        "chapter_contract_id": "contract:objectives:v2",
        "fact_requirements": _fact_requirements(),
        "claim_requirements": _claim_requirements(),
        "evidence_source_requirements": (_evidence_requirement(),),
        "structural_object_obligations": _structural_object_obligations(),
        "project_specific_elements": ("UC301 主要终点定义", "12周给药访视窗口"),
        "skeleton_risk_rules": ("只有标题或通用模板句即失败",),
    }
    payload.update(overrides)
    return SubstantiveContentContractV2(**payload)


def _chapter_contract_v2(**overrides):
    payload = {
        "chapter_contract_id": "contract:objectives:v2",
        "semantic_node_id": "node:study-objectives",
        "contract_version": "2.0.0",
        "template_id": "template:tp-ma-07",
        "template_sha256": SHA_A,
        "chapter_skill_id": "skill:chapter:objectives",
        "chapter_skill_version": "2.0.0",
        "word_rules": _word_rules(),
        "positive_qc_rules": (_qc_rule(),),
        "conditional_applicability_rules": (_conditional_rule(),),
        "dependency_ids": ("contract:background:v1",),
        "dependency_repair_policy": _repair_policy(),
        "ctq_items": (_ctq_item(),),
        "patient_participation_obligations": (_participation_obligation(),),
        "registry_consistency_obligations": (_registry_obligation(),),
        "substantive_content": _content_contract_v2(),
    }
    payload.update(overrides)
    return ChapterContractV2(**payload)


def _assert_roundtrip(model):
    payload = model.model_dump(mode="json")
    restored = type(model).model_validate(json.loads(json.dumps(payload)))
    assert restored == model
    first_field = next(iter(type(model).model_fields))
    with pytest.raises(ValidationError, match="frozen"):
        setattr(model, first_field, None)


# ---------------------------------------------------------------------------
# v1 pins.
# ---------------------------------------------------------------------------


def test_v1_chapter_and_substantive_serialization_and_hashes_unchanged():
    chapter = _chapter_contract_v1()
    content = _substantive_content_contract_v1()
    assert chapter.model_dump_json() == CHAPTER_CONTRACT_V1_PIN_JSON
    assert content.model_dump_json() == SUBSTANTIVE_CONTENT_CONTRACT_V1_PIN_JSON
    assert chapter.material_sha256() == CHAPTER_CONTRACT_V1_MATERIAL_SHA256
    assert content.material_sha256() == SUBSTANTIVE_CONTENT_CONTRACT_V1_MATERIAL_SHA256
    # v1 types must not gain v2 fields or serialized defaults.
    for v2_field in (
        "word_rules",
        "conditional_applicability_rules",
        "dependency_repair_policy",
        "ctq_items",
        "patient_participation_obligations",
        "registry_consistency_obligations",
        "positive_qc_rule_entries",
    ):
        assert v2_field not in ChapterContract.model_fields
        assert v2_field not in SubstantiveContentContract.model_fields


def test_v1_dependency_bound_models_hashes_unchanged():
    from packages.contracts.workbench_contracts.protocol_v3 import SemanticBlock

    now = datetime(2026, 9, 6, 2, 0, tzinfo=timezone.utc)

    def _sha(text):
        return sha256(text.encode("utf-8")).hexdigest()

    block = SemanticBlock(
        semantic_block_id="block:introduction:001",
        semantic_node_id="node:introduction",
        chapter_contract_id="contract:introduction:v1",
        substantive_content_contract_id="content:introduction:v1",
        block_kind="paragraph",
        content="本研究拟评价研究药物 A 用于目标人群的有效性与安全性。",
        fact_paths=("picos.population.indication",),
        claim_evidence_link_ids=("link:introduction:001",),
        medical_admission_unit_ids=("admission:introduction:001",),
        content_sha256=SHA_B,
    )
    document = SemanticDocumentRevision(
        semantic_document_revision_id="document:uc301:001",
        project_id="project:uc301",
        revision=1,
        study_definition_id="study:def:uc301",
        study_definition_sha256=SHA_A,
        applicability_snapshot_id="applicability:uc301:v1",
        applicability_snapshot_sha256=SHA_B,
        semantic_blocks=(block,),
        chapter_contract_hashes=(_sha("contract:objectives:v1"),),
        updated_at=now,
    )
    lock = ChapterLockSnapshot(
        chapter_lock_snapshot_id="lock:objectives:001",
        semantic_node_id="node:study-objectives",
        semantic_document_revision_id="document:uc301:001",
        semantic_document_sha256=SHA_C,
        upstream_artifact_hashes=(SHA_A, SHA_B),
        accepted_semantic_block_hashes=(_sha("block:introduction:001"),),
        locked_by_actor_id="user:medical-writer",
        locked_at=now,
    )
    execution = NodeExecutionContract(
        node_execution_contract_id="execution:contract:001",
        skill_definition_id="skill:chapter:objectives",
        role="chapter_writer",
        harness="zcode",
        provider="zcode",
        model="GLM-5.3-Flash",
        reasoning_effort="high",
        same_session_recovery=True,
        timeout_seconds=600,
        fallback_policy_id="policy:fallback:001",
        prompt_sha256=SHA_D,
        input_schema_ref="schemas/chapter-input-v1.json",
        output_schema_ref="schemas/chapter-output-v1.json",
        allowed_tools=("read", "grep"),
        allowed_paths=("runs/",),
        permission_policy_id="policy:permission:001",
        input_artifact_hashes=(SHA_A,),
        sensitivity_tier="confidential",
        allowed_providers=("zcode",),
        allowed_regions=("cn-north-1",),
        redaction_policy_id="policy:redaction:001",
        retention_policy_id="policy:retention:001",
        logical_call_id="call:chapter:001",
        idempotency_key="call:chapter:001@input-a",
    )
    assert document.material_sha256() == SEMANTIC_DOCUMENT_REVISION_V1_MATERIAL_SHA256
    assert (
        document.compact_dependencies().material_sha256()
        == SEMANTIC_DOCUMENT_REVISION_V1_COMPACT_MATERIAL_SHA256
    )
    assert lock.material_sha256() == CHAPTER_LOCK_SNAPSHOT_V1_MATERIAL_SHA256
    assert (
        lock.compact_dependencies().material_sha256()
        == CHAPTER_LOCK_SNAPSHOT_V1_COMPACT_MATERIAL_SHA256
    )
    assert execution.material_sha256() == NODE_EXECUTION_CONTRACT_V1_MATERIAL_SHA256
    assert (
        execution.compact_dependencies().material_sha256()
        == NODE_EXECUTION_CONTRACT_V1_COMPACT_MATERIAL_SHA256
    )


# ---------------------------------------------------------------------------
# v2 typed obligations.
# ---------------------------------------------------------------------------


def test_v2_contracts_are_explicitly_versioned_and_strict():
    chapter = _chapter_contract_v2()
    content = _content_contract_v2()
    assert chapter.schema_version == "mw_protocol_v3_contract_v2"
    assert content.schema_version == "mw_protocol_v3_contract_v2"
    for model in (chapter, content):
        schema = model.model_json_schema()
        assert schema["additionalProperties"] is False
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _chapter_contract_v2(required_fact_paths=("picos.outcome.primary",))


def test_v2_fact_and_claim_requirements_roundtrip_and_reject_contradictions():
    content = _content_contract_v2()
    assert [item.obligation.value for item in content.fact_requirements] == [
        "required",
        "optional",
        "forbidden",
    ]
    assert [item.obligation.value for item in content.claim_requirements] == [
        "required",
        "allowed",
        "qualified",
        "forbidden",
    ]
    _assert_roundtrip(content)

    # Same fact path under two obligations is a contradiction, not a merge.
    with pytest.raises(ValidationError, match="conflicting fact obligations"):
        _content_contract_v2(
            fact_requirements=_fact_requirements()
            + (
                FactRequirement(
                    fact_path="picos.outcome.primary",
                    obligation="forbidden",
                    rationale="与 required 冲突。",
                ),
            )
        )
    # Same claim type under two obligations is a contradiction.
    with pytest.raises(ValidationError, match="conflicting claim obligations"):
        _content_contract_v2(
            claim_requirements=_claim_requirements()
            + (
                ClaimRequirement(
                    claim_type="primary_objective",
                    obligation="forbidden",
                    rationale="与 required 冲突。",
                ),
            )
        )
    # A qualified claim without qualifying conditions is not checkable.
    with pytest.raises(ValidationError, match="qualifying conditions"):
        _content_contract_v2(
            claim_requirements=(
                ClaimRequirement(
                    claim_type="superiority_claim",
                    obligation="qualified",
                    rationale="缺少限定条件。",
                ),
            )
        )
    # A forbidden claim type must not sneak back in as an admission type.
    with pytest.raises(ValidationError, match="forbidden claim"):
        _content_contract_v2(
            evidence_source_requirements=(
                EvidenceSourceRequirement(
                    source_roles=("competitor_full_protocol",),
                    admission_claim_types=("marketing_claim",),
                    allowed_locator_kinds=("body",),
                    require_context_window=True,
                    minimum_quality_score=0.5,
                ),
            )
        )


def test_v2_rejects_vacuous_and_generic_object_only_content():
    with pytest.raises(ValidationError, match="vacuous"):
        _content_contract_v2(
            fact_requirements=(),
            claim_requirements=(),
            evidence_source_requirements=(),
            structural_object_obligations=(),
            project_specific_elements=(),
        )
    # Bare object presence without any project-specific anchoring is vacuous.
    with pytest.raises(ValidationError, match="object-only"):
        _content_contract_v2(
            fact_requirements=(),
            claim_requirements=(),
            evidence_source_requirements=(),
            project_specific_elements=(),
        )
    # Object-only content anchored by project-specific elements is valid.
    object_only = _content_contract_v2(
        fact_requirements=(),
        claim_requirements=(),
        evidence_source_requirements=(),
        project_specific_elements=("UC301 访视窗对照表",),
    )
    _assert_roundtrip(object_only)
    with pytest.raises(ValidationError, match="skeleton_risk_rules"):
        SubstantiveContentContractV2(
            substantive_content_contract_id="content:x:v2",
            chapter_contract_id="contract:objectives:v2",
            claim_requirements=_claim_requirements()[:1],
        )
    with pytest.raises(ValidationError, match="minimum_occurrences"):
        _content_contract_v2(
            structural_object_obligations=(
                StructuralObjectObligation(
                    object_kind="table",
                    minimum_occurrences=0,
                    project_specific_specification="零次出现没有意义。",
                ),
            )
        )


def test_v2_metadata_control_content_needs_no_fabricated_medical_evidence():
    """A control/metadata chapter binds template provenance, not invented claims."""

    control_content = _content_contract_v2(
        substantive_content_contract_id="content:control-page:v2",
        chapter_contract_id="contract:control-page:v2",
        fact_requirements=(),
        claim_requirements=(),
        evidence_source_requirements=(),
        structural_object_obligations=(
            StructuralObjectObligation(
                object_kind="table",
                minimum_occurrences=1,
                project_specific_specification="对照表逐行列出模板控制项与 UC301 落点。",
            ),
        ),
        project_specific_elements=("模板控制 provenance：template:tp-ma-07",),
    )
    control = _chapter_contract_v2(
        chapter_contract_id="contract:control-page:v2",
        semantic_node_id="node:control-page",
        substantive_content=control_content,
        positive_qc_rules=(
            PositiveQcRule(
                positive_qc_rule_id="qc:control:version",
                rule="对照表版本号与模板控制 provenance 一致。",
            ),
        ),
        conditional_applicability_rules=(),
        dependency_ids=(),
        dependency_repair_policy=None,
        ctq_items=(),
        patient_participation_obligations=(),
        registry_consistency_obligations=(),
    )
    assert control.template_sha256 == SHA_A
    assert control_content.evidence_source_requirements == ()
    assert control_content.claim_requirements == ()
    _assert_roundtrip(control)
    _assert_roundtrip(control_content)


def test_v2_evidence_source_requirements_are_typed():
    evidence = _evidence_requirement()
    assert evidence.allowed_locator_kinds[0].value == "body"
    assert evidence.minimum_quality_score == 0.85
    with pytest.raises(ValidationError, match="chapter-admissible"):
        EvidenceSourceRequirement(
            source_roles=("competitor_full_protocol",),
            admission_claim_types=("study_objective",),
            allowed_locator_kinds=("page",),
            require_context_window=True,
            minimum_quality_score=0.5,
        )
    with pytest.raises(ValidationError):
        _evidence_requirement(minimum_quality_score=1.5)
    with pytest.raises(ValidationError):
        EvidenceSourceRequirement(
            source_roles=(),
            admission_claim_types=("study_objective",),
            allowed_locator_kinds=("body",),
            require_context_window=False,
            minimum_quality_score=0.5,
        )


def test_v2_word_rules_reject_vacuous_or_contradictory_formatting():
    rules = _word_rules()
    assert rules.required_styles == ("Heading 2", "List Paragraph")
    with pytest.raises(ValidationError, match="vacuous"):
        WordFormattingRules(word_formatting_rules_id="word:rules:empty")
    with pytest.raises(ValidationError, match="conflicting styles"):
        WordFormattingRules(
            word_formatting_rules_id="word:rules:conflict",
            required_styles=("Heading 2",),
            forbidden_styles=("Heading 2",),
        )


def test_v2_conditional_applicability_requires_when_active_obligations():
    rule = _conditional_rule()
    assert rule.triggering_fact_paths == ("picos.population.sex",)
    with pytest.raises(ValidationError, match="vacuous"):
        ConditionalApplicabilityRule(
            conditional_applicability_rule_id="applicability:empty",
            triggering_fact_paths=("picos.population.sex",),
            condition="人群包含育龄女性",
            rationale="没有任何条件义务。",
        )
    with pytest.raises(ValidationError, match="duplicate IDs"):
        ConditionalApplicabilityRule(
            conditional_applicability_rule_id="applicability:dup",
            triggering_fact_paths=("picos.population.sex", "picos.population.sex"),
            condition="人群包含育龄女性",
            rationale="触发路径重复。",
            required_when_active_fact_paths=("picos.risk.pregnancy",),
        )


def test_v2_dependency_repair_policy_is_bounded_and_declared():
    policy = _repair_policy()
    assert policy.max_repair_attempts == 3
    assert policy.repair_owner.value == "ai"
    with pytest.raises(ValidationError):
        _repair_policy(max_repair_attempts=0)
    with pytest.raises(ValidationError):
        _repair_policy(max_repair_attempts=6)
    with pytest.raises(ValidationError, match="duplicate"):
        _repair_policy(
            repair_steps=(
                RepairStep(repair_step_id="repair:step:a", sequence=1, action="A", owner="ai"),
                RepairStep(repair_step_id="repair:step:b", sequence=1, action="B", owner="ai"),
            )
        )
    # The policy may only reference dependencies declared on the chapter contract.
    with pytest.raises(ValidationError, match="undeclared dependency"):
        _chapter_contract_v2(dependency_ids=())


def test_v2_ctq_items_anchor_to_facts_or_claims_and_known_qc_rules():
    item = _ctq_item()
    assert item.positive_qc_rule_ids == ("qc:objectives:mapping",)
    with pytest.raises(ValidationError, match="anchor"):
        CriticalToQualityItem(
            ctq_item_id="ctq:unanchored",
            question="这个 CtQ 项没有锚定任何事实或声明。",
            risk_if_unmet="不可核查。",
        )
    with pytest.raises(ValidationError, match="unknown positive QC rule"):
        _chapter_contract_v2(
            ctq_items=(
                CriticalToQualityItem(
                    ctq_item_id="ctq:dangling",
                    question="主要目的是否与主要终点一一映射？",
                    linked_claim_types=("primary_objective",),
                    positive_qc_rule_ids=("qc:does:not.exist",),
                    risk_if_unmet="引用了不存在的 QC 规则。",
                ),
            )
        )


def test_v2_patient_participation_ties_decision_record_without_arbitrary_length():
    obligation = _participation_obligation()
    assert obligation.participation_status.value == "non_participation_with_reason"
    assert obligation.decision_record_id == "decision:record:participation:001"
    _assert_roundtrip(obligation)
    with pytest.raises(ValidationError):
        _participation_obligation(ai_prepared_reason="   ")
    # The AI-prepared reason carries no arbitrary maximum length.
    long_reason = _participation_obligation(ai_prepared_reason="依据已批准决策整理原因。" * 2000)
    assert len(long_reason.ai_prepared_reason) > 10000
    with pytest.raises(ValidationError, match="duplicate IDs"):
        _chapter_contract_v2(
            patient_participation_obligations=(
                _participation_obligation(),
                _participation_obligation(
                    patient_participation_obligation_id="participation:uc301:001",
                    decision_record_id="decision:record:participation:002",
                ),
            )
        )


def test_v2_registry_consistency_and_positive_qc_are_required_obligations():
    registry = _registry_obligation()
    assert registry.registry_name == "ClinicalTrials.gov"
    with pytest.raises(ValidationError):
        RegistryConsistencyObligation(
            registry_consistency_obligation_id="registry:uc301:empty",
            registry_name="NMPA",
            eligibility_fact_paths=(),
            consistency_rules=("入选标准一致。",),
        )
    with pytest.raises(ValidationError):
        _registry_obligation(consistency_rules=())
    # Positive QC is mandatory on every chapter contract v2.
    with pytest.raises(ValidationError):
        _chapter_contract_v2(positive_qc_rules=())
    with pytest.raises(ValidationError, match="duplicate IDs"):
        _chapter_contract_v2(positive_qc_rules=(_qc_rule(), _qc_rule()))


def test_v2_full_contract_roundtrip_and_material_hash_tracks_content():
    chapter = _chapter_contract_v2()
    content = _content_contract_v2()
    _assert_roundtrip(chapter)
    _assert_roundtrip(content)
    assert chapter.canonical_state.value == "frozen"
    with pytest.raises(ValidationError, match="frozen before execution"):
        _chapter_contract_v2(canonical_state="proposed")

    metadata_only_change = _chapter_contract_v2(canonical_state="quarantined")
    assert chapter.material_sha256() == metadata_only_change.material_sha256()
    content_change = _chapter_contract_v2(
        dependency_ids=("contract:methods:v1",),
        dependency_repair_policy=_repair_policy(
            dependency_repair_policy_id="repair:objectives:policy",
            dependency_ids=("contract:methods:v1",),
        ),
    )
    assert chapter.material_sha256() != content_change.material_sha256()
