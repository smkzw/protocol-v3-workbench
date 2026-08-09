from __future__ import annotations

import pytest

from services.api.app.medical_writing_revision_prompts import (
    MEDICAL_WRITING_REVISION_CANDIDATE_COUNT,
    MEDICAL_WRITING_REVISION_PROMPT_VERSION,
    REVISION_INTENT_PROFILES,
    revision_intent_profile,
    revision_task_context,
)


def test_revision_intent_profiles_are_distinct_and_production_bounded():
    assert MEDICAL_WRITING_REVISION_PROMPT_VERSION == "medical_writing_revision_v1_4"
    assert MEDICAL_WRITING_REVISION_CANDIDATE_COUNT == 4
    assert set(REVISION_INTENT_PROFILES) == {
        "medical_writing_revision",
        "regulatory_tone",
        "consistency_check",
        "evidence_gap",
    }
    assert (
        len({profile.directional_goal for profile in REVISION_INTENT_PROFILES.values()})
        == 4
    )
    for profile in REVISION_INTENT_PROFILES.values():
        assert 3 <= len(profile.candidate_blueprints) <= 5
        assert len(profile.candidate_blueprints) == profile.candidate_count
        assert len(profile.preservation_rules) >= 4
        assert "allowed_sources" in " ".join(profile.preservation_rules)


def test_revision_candidate_prompt_separates_corpus_roles_and_prevents_overfit():
    context = revision_task_context("medical_writing_revision")
    rules = "".join(context["preservation_rules"])

    for role in (
        "structure_template",
        "regulatory_fixed_wording",
        "indication_specific_wording",
        "project_fact_reference",
    ):
        assert role in rules
    assert "同疾病领域或相近研究设计仅用于结构参照" in rules
    assert "至少两个独立文档、两个申办方" in rules
    assert "单一来源、单一申办方或少样本" in rules
    assert "不得多数表决、折中取值或静默选择" in rules


def test_revision_task_context_merges_table_identity_without_losing_intent_contract():
    context = revision_task_context(
        "consistency_check",
        {"context_type": "working_copy_table_cell", "cell_id": "cell_001"},
    )
    assert context["revision_intent"] == "consistency_check"
    assert context["candidate_count"] == 3
    assert "逐字原文保留" in "".join(context["preservation_rules"])
    assert "proposal_text不得重复" in "".join(context["preservation_rules"])
    assert context["context_type"] == "working_copy_table_cell"
    assert context["cell_id"] == "cell_001"


def test_evidence_gap_without_external_evidence_cannot_imply_support_exists():
    context = revision_task_context("evidence_gap")
    rules = "".join(context["preservation_rules"])
    assert "allowed_sources只有当前目标原文" in rules
    assert "设计依据见方案详述" in rules
    assert "证据缺口只写入rationale和uncertainties" in rules


def test_unknown_revision_intent_fails_closed():
    with pytest.raises(ValueError, match="unsupported medical-writing revision intent"):
        revision_intent_profile("compress")
