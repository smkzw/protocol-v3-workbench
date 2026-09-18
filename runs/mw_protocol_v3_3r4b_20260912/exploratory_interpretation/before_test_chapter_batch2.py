"""Task3R.3 batch2 (sections 2-3) source-obligation tests.

Scope: the sixteen authored heading-leaf carriers of the approved TP-MA-07 v2.0
source (background, objectives/endpoints, estimands) plus their dedicated
chapter skills, the closed batch vocabulary and the executable fixture slice.

These tests are offline and deterministic.  They exercise the existing shared
infrastructure only (``assemble_chapter_registry`` / ``load_chapter_registry`` /
``lint_registry`` / ``check_fixture``); they do not modify core, schema,
assembler, linter or any batch1 artifact.  Clinical authoring, admitted
provenance resolution and medical QC judgment remain deferred and are never
claimed here.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.protocol_workflow.registries.chapters import (
    CHAPTER_SKILL_INPUT_SCHEMA_REF,
    CHAPTER_SKILL_OUTPUT_SCHEMA_REF,
    ChapterSkillManifest,
    check_fixture,
    lint_registry,
)
from packages.contracts.workbench_contracts.protocol_v3 import (
    ChapterContractV2,
    EvidenceSourceRequirement,
)
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = (
    REPO_ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
)
CONTRACTS_DIR = TEMPLATE_DIR / "chapter_contracts"
SKILLS_DIR = TEMPLATE_DIR / "chapter_skills"
BATCH2_PATH = (
    REPO_ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch2.json"
)

TEMPLATE_ID = "tp_ma_07_v2"
#: Frozen source sha256 of the approved TP-MA-07 v2.0 DOCX.
TEMPLATE_SHA256 = (
    "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
)

BATCH2_NODE_IDS = (
    "v2_n_2_1",
    "v2_n_2_2_1",
    "v2_n_2_2_2_1",
    "v2_n_2_2_3",
    "v2_n_2_3",
    "v2_n_3_1_1",
    "v2_n_3_1_2_1",
    "v2_n_3_1_2_2",
    "v2_n_3_1_2_3",
    "v2_n_3_1_2_4",
    "v2_n_3_2_1",
    "v2_n_3_2_2",
    "v2_n_3_3_1",
    "v2_n_3_3_2",
    "v2_n_3_4_1",
    "v2_n_3_4_2",
)

#: Source obligations expected from each authored carrier.  This table is the
#: authored contract under test: facts/claims that the source makes mandatory,
#: forbidden claim classes, the independent evidence groups (each group accepts
#: ANY ONE conforming claim) and the required structural objects/cells.
EXPECTED_OBLIGATIONS: dict[str, dict] = {
    "v2_n_2_1": {
        "required_facts": (
            "framing.indication",
            "background.clinical_problem",
            "background.standard_of_care",
            "background.unmet_need",
            "background.rationale_uncertainty",
        ),
        "required_claims": ("study_rationale",),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("regulatory_or_guideline",), ("disease_background_summary",)),
            (("project_primary",), ("study_rationale",)),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_2_2_1": {
        "required_facts": (
            "framing.investigational_product",
            "framing.product_profile",
            "background.product.structure_applicability",
            "background.product.mechanism",
            "background.product.authority_identity",
        ),
        "required_claims": ("product_identity", "mechanism_statement"),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("project_primary",), ("product_identity",)),
            (("project_primary",), ("mechanism_statement",)),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_2_2_2_1": {
        "required_facts": (
            "nonclinical.pharmacodynamics",
            "nonclinical.pharmacokinetics",
            "nonclinical.toxicology",
            "nonclinical.general_pharmacology",
            "background.clinical_pharmacology_context",
        ),
        "required_claims": (
            "nonclinical_pd_evidence",
            "nonclinical_pk_evidence",
            "nonclinical_toxicology_evidence",
            "nonclinical_general_pharmacology_evidence",
        ),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("project_primary",), ("nonclinical_pd_evidence",)),
            (("project_primary",), ("nonclinical_pk_evidence",)),
            (("project_primary",), ("nonclinical_toxicology_evidence",)),
            (
                ("project_primary",),
                ("nonclinical_general_pharmacology_evidence",),
            ),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_2_2_3": {
        "required_facts": (
            "picos.comparator_summary",
            "background.own_product.clinical_evidence",
            "background.own_product.clinical_study_context",
        ),
        "required_claims": (
            "competitor_evidence_summary",
            "own_product_clinical_evidence",
        ),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("competitor_full_protocol",), ("competitor_evidence_summary",)),
            (("project_primary",), ("own_product_clinical_evidence",)),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_2_3": {
        "required_facts": (
            "background.risk.known_risks",
            "background.risk.potential_risks",
            "background.risk.anticipated_benefit",
            "background.risk.uncertainty",
            "background.risk.mitigation",
            "background.risk.benefit_risk_assessment",
        ),
        "required_claims": ("risk_benefit_assessment", "risk_benefit_framework"),
        "forbidden_claims": ("compensation_as_benefit",),
        "evidence_groups": (
            (("project_primary",), ("risk_benefit_assessment",)),
            (("regulatory_or_guideline",), ("risk_benefit_framework",)),
        ),
        "object_kinds": ("paragraph", "table"),
        "required_cells": (
            "risk:cell:known",
            "risk:cell:potential",
            "risk:cell:anticipated_benefit",
            "risk:cell:assessment",
        ),
    },
    "v2_n_3_1_1": {
        "required_facts": (
            "picos.primary_objectives",
            "picos.primary_clinical_question",
            "picos.primary_comparison",
            "picos.primary_endpoint",
        ),
        "required_claims": ("study_objective", "primary_endpoint_definition"),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("project_primary",), ("study_objective",)),
            (("project_primary",), ("primary_endpoint_definition",)),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_3_1_2_1": {
        "required_facts": (
            "estimand.primary.population",
            "estimand.primary.analysis_set_distinction",
        ),
        "required_claims": ("estimand_population_attribute",),
        "forbidden_claims": ("analysis_set_equivalence",),
        "evidence_groups": (
            (("project_primary",), ("estimand_population_attribute",)),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_3_1_2_2": {
        "required_facts": (
            "estimand.primary.variable",
            "estimand.primary.variable_measurement",
            "estimand.primary.variable_aggregation",
            "estimand.primary.variable_timepoint_window",
        ),
        "required_claims": ("estimand_variable_attribute",),
        "forbidden_claims": ("label_only_variable",),
        "evidence_groups": (
            (("project_primary",), ("estimand_variable_attribute",)),
        ),
        "object_kinds": ("table",),
        "required_cells": (
            "variable:cell:measurement",
            "variable:cell:aggregation",
            "variable:cell:timepoint",
        ),
    },
    "v2_n_3_1_2_3": {
        "required_facts": (
            "estimand.primary.treatment_condition",
            "estimand.primary.background_treatment",
            "estimand.primary.rescue_treatment_handling",
            "estimand.primary.treatment_effect_label_clarification",
        ),
        "required_claims": ("estimand_treatment_condition_attribute",),
        "forbidden_claims": ("treatment_effect_label_only",),
        "evidence_groups": (
            (("project_primary",), ("estimand_treatment_condition_attribute",)),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_3_1_2_4": {
        "required_facts": (
            "estimand.primary.intercurrent_events",
            "estimand.primary.ice_strategy",
            "estimand.primary.ice_rationale",
            "estimand.primary.population_summary_measure",
        ),
        "required_claims": (
            "estimand_ice_attribute",
            "estimand_population_summary_attribute",
        ),
        "forbidden_claims": ("ice_shell_placeholder",),
        "evidence_groups": (
            (("project_primary",), ("estimand_ice_attribute",)),
            (("project_primary",), ("estimand_population_summary_attribute",)),
        ),
        "object_kinds": ("paragraph", "table"),
        "required_cells": (
            "estimand:ice:cell:event",
            "estimand:ice:cell:definition",
            "estimand:ice:cell:strategy",
            "estimand:ice:cell:rationale",
        ),
    },
    "v2_n_3_2_1": {
        "required_facts": (
            "picos.secondary_objectives",
            "picos.secondary_objective_endpoint_map",
            "picos.secondary_multiplicity_intent",
        ),
        "required_claims": ("secondary_objective",),
        "forbidden_claims": ("numbered_placeholder_objective",),
        "evidence_groups": ((("project_primary",), ("secondary_objective",)),),
        "object_kinds": ("table",),
        "required_cells": (
            "secondary:cell:objective",
            "secondary:cell:endpoint",
        ),
    },
    "v2_n_3_2_2": {
        "required_facts": (
            "picos.key_secondary_endpoints",
            "picos.other_secondary_endpoints",
            "picos.secondary_endpoint_definitions",
        ),
        "required_claims": ("secondary_endpoint_definition",),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("project_primary",), ("secondary_endpoint_definition",)),
        ),
        "object_kinds": ("table",),
        "required_cells": (
            "secondary:cell:endpoint:definition",
            "secondary:cell:endpoint:timepoint",
        ),
    },
    "v2_n_3_3_1": {
        "required_facts": (
            "safety.safety_objectives",
            "picos.safety_endpoints",
            "safety.observation_period",
            "safety.injection_reaction_applicability",
        ),
        "required_claims": ("safety_objective",),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": ((("project_primary",), ("safety_objective",)),),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_3_3_2": {
        "required_facts": (
            "safety.endpoint_definitions",
            "safety.observation_period",
            "picos.aesi_definitions",
        ),
        "required_claims": ("safety_endpoint_definition",),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("project_primary",), ("safety_endpoint_definition",)),
        ),
        "object_kinds": ("table",),
        "required_cells": (
            "safety:cell:endpoint",
            "safety:cell:observation_period",
        ),
    },
    "v2_n_3_4_1": {
        "required_facts": (
            "picos.exploratory_objectives",
            "exploratory.disposition",
        ),
        "required_claims": ("exploratory_objective", "exploratory_disposition"),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("project_primary",), ("exploratory_objective",)),
            (("project_primary",), ("exploratory_disposition",)),
        ),
        "object_kinds": ("paragraph",),
        "required_cells": (),
    },
    "v2_n_3_4_2": {
        "required_facts": (
            "picos.exploratory_endpoints",
            "exploratory.endpoint_disposition",
        ),
        "required_claims": (
            "exploratory_endpoint",
            "exploratory_endpoint_disposition",
        ),
        "forbidden_claims": ("marketing_claim",),
        "evidence_groups": (
            (("project_primary",), ("exploratory_endpoint",)),
            (("project_primary",), ("exploratory_endpoint_disposition",)),
        ),
        "object_kinds": ("table",),
        "required_cells": (
            "exploratory:cell:endpoint",
            "exploratory:cell:analysis_intent",
        ),
    },
}

#: Fixture families that must be exercised for every one of the sixteen nodes.
REQUIRED_FAMILIES = (
    {"positive"},
    {"missing_claim", "missing_control"},
    {"wrong_source"},
    {"skeleton"},
)

#: Source-specific negatives and the reason each must fail for.
SOURCE_SPECIFIC_NEGATIVES: dict[str, tuple[str, ...]] = {
    "fixture:batch2:v2-n-2-2-3:competitor-as-own-clinical": (
        "wrong_source_role",
        "unsatisfied_evidence_requirement",
    ),
    "fixture:batch2:v2-n-2-2-3:missing-own-clinical-evidence-group": (
        "unsatisfied_evidence_requirement",
    ),
    "fixture:batch2:v2-n-2-2-2-1:missing-general-pharmacology-group": (
        "unsatisfied_evidence_requirement",
    ),
    "fixture:batch2:v2-n-3-1-2-4:empty-ice-entries": ("missing_required_cell",),
    "fixture:batch2:v2-n-3-1-2-4:missing-population-summary-measure": (
        "missing_required_fact",
    ),
    "fixture:batch2:v2-n-3-1-2-4:summary-measure-method-name-only": (
        "missing_required_fact",
    ),
    "fixture:batch2:v2-n-2-2-1:missing-mechanism-evidence-group": (
        "unsatisfied_evidence_requirement",
    ),
}

#: Negatives that must fail because a forbidden claim class was actually written.
FORBIDDEN_CLAIM_NEGATIVES = (
    "fixture:batch2:v2-n-3-1-2-1:analysis-set-equivalence-forbidden",
    "fixture:batch2:v2-n-3-1-2-2:label-only-variable-forbidden",
    "fixture:batch2:v2-n-3-1-2-3:treatment-effect-label-only-forbidden",
    "fixture:batch2:v2-n-3-1-2-4:ice-shell-placeholder-forbidden",
    "fixture:batch2:v2-n-3-2-1:numbered-placeholder-objective-forbidden",
    "fixture:batch2:v2-n-2-3:compensation-as-benefit-forbidden",
)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _batch_document() -> dict:
    assert BATCH2_PATH.is_file(), f"missing authored batch document: {BATCH2_PATH}"
    return json.loads(BATCH2_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def batch2_document():
    return assemble_registry(CONTRACTS_DIR, SKILLS_DIR, BATCH2_PATH)


@pytest.fixture(scope="module")
def batch2_registry(batch2_document):
    from app.protocol_workflow.registries.chapters import load_chapter_registry

    return load_chapter_registry(batch2_document)


@pytest.fixture(scope="module")
def node_tree() -> dict:
    return json.loads((TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8"))


def _entry(batch2_registry, node_id: str):
    for entry in batch2_registry.chapters:
        if entry.node_id == node_id:
            return entry
    raise AssertionError(f"no batch2 carrier for {node_id}")


def _contract(batch2_registry, node_id: str) -> ChapterContractV2:
    return _entry(batch2_registry, node_id).contract


def _fixture_index(batch2_registry) -> dict:
    return {fixture.fixture_id: fixture for fixture in batch2_registry.fixtures}


def _error_codes(result) -> set[str]:
    return {finding.code for finding in result.findings if finding.severity == "error"}


def _error_locations(result, code: str) -> tuple[str, ...]:
    return tuple(
        finding.location
        for finding in result.findings
        if finding.severity == "error" and finding.code == code
    )


def _leaf_union(node_tree: dict) -> set[str]:
    heading = {
        node["id"]
        for node in node_tree["heading_style_tree"]["nodes"]
        if node.get("is_leaf_heading")
    }
    outline = {
        node["id"] for node in node_tree["outlined_tree"]["nodes"] if node.get("is_leaf")
    }
    return heading | outline


# ---------------------------------------------------------------------------
# Batch scope and vocabulary.
# ---------------------------------------------------------------------------


def test_batch_document_declares_exactly_the_sixteen_batch_scope():
    batch = _batch_document()
    assert batch["schema_version"] == "protocol-v3-chapter-batch.v1"
    assert batch["template_id"] == TEMPLATE_ID
    assert batch["template_sha256"] == TEMPLATE_SHA256
    assert tuple(batch["coverage_roles"]) == BATCH2_NODE_IDS
    assert all(
        role == "heading_leaf" for role in batch["coverage_roles"].values()
    )
    # Batch-scope only: the sibling batch1 carriers are not re-declared here.
    assert "v2_n_1_1" not in batch["coverage_roles"]
    assert "v2_front_block" not in batch["coverage_roles"]


def test_closed_vocabularies_cover_every_used_path_and_claim(
    batch2_registry, batch2_document
):
    fact_vocabulary = set(batch2_registry.fact_vocabulary)
    claim_vocabulary = set(batch2_registry.claim_vocabulary)
    assert len(fact_vocabulary) == len(batch2_registry.fact_vocabulary)
    assert len(claim_vocabulary) == len(batch2_registry.claim_vocabulary)

    used_facts: set[str] = set()
    used_claims: set[str] = set()
    for entry in batch2_registry.chapters:
        contract = entry.contract
        substantive = contract.substantive_content
        used_facts |= {
            item.fact_path for item in substantive.fact_requirements
        }
        used_claims |= {item.claim_type for item in substantive.claim_requirements}
        used_claims |= {
            claim
            for group in substantive.evidence_source_requirements
            for claim in group.admission_claim_types
        }
        for rule in contract.conditional_applicability_rules:
            used_facts |= set(rule.triggering_fact_paths)
            used_facts |= set(rule.required_when_active_fact_paths)
            used_claims |= set(rule.required_when_active_claim_types)
    assert used_facts <= fact_vocabulary
    assert used_claims <= claim_vocabulary

    # The estimator summary measure is a distinct estimand path; the legacy
    # population-description path keeps its own meaning and is never required.
    assert "estimand.primary.population_summary_measure" in fact_vocabulary
    assert "picos.population_summary" in fact_vocabulary
    assert "estimand.primary.population_summary_measure" != "picos.population_summary"
    for entry in batch2_registry.chapters:
        for item in entry.contract.substantive_content.fact_requirements:
            if item.fact_path == "picos.population_summary":
                assert item.obligation.value != "required"
    # Template example wording is never promoted to a project requirement.
    assert not [path for path in used_facts if "template_example" in path]
    assert batch2_document["fact_vocabulary"] == sorted(set(batch2_document["fact_vocabulary"]))


def test_assembled_registry_contains_only_the_sixteen_leaf_carriers(batch2_registry):
    assert [entry.node_id for entry in batch2_registry.chapters] == list(
        BATCH2_NODE_IDS
    )
    assert all(
        entry.coverage_role == "heading_leaf" for entry in batch2_registry.chapters
    )
    assert len({entry.contract.chapter_contract_id for entry in batch2_registry.chapters}) == 16
    for entry in batch2_registry.chapters:
        assert entry.contract.semantic_node_id == entry.node_id
        assert entry.contract.template_id == TEMPLATE_ID
        assert entry.contract.template_sha256 == TEMPLATE_SHA256
        skill_ids = {skill.skill_id for skill in entry.skills}
        assert entry.contract.chapter_skill_id in skill_ids
        for skill in entry.skills:
            assert isinstance(skill, ChapterSkillManifest)
            assert skill.node_id == entry.node_id
            assert skill.chapter_contract_id == entry.contract.chapter_contract_id
            assert skill.template_sha256 == TEMPLATE_SHA256
            assert skill.input_schema_ref == CHAPTER_SKILL_INPUT_SCHEMA_REF
            assert skill.output_schema_ref == CHAPTER_SKILL_OUTPUT_SCHEMA_REF


def test_batch_scope_is_not_directory_scoped(tmp_path, batch2_document):
    """Extra/future files in the shared directories must not change the slice."""

    contracts = tmp_path / "chapter_contracts"
    skills = tmp_path / "chapter_skills"
    contracts.mkdir()
    skills.mkdir()
    for node_id in BATCH2_NODE_IDS:
        shutil.copy(CONTRACTS_DIR / f"{node_id}.json", contracts / f"{node_id}.json")
        shutil.copy(SKILLS_DIR / f"{node_id}.json", skills / f"{node_id}.json")
    # A future batch carrier (invalid on purpose: it must never be parsed).
    (contracts / "v2_n_4_1.json").write_text("{ not json", encoding="utf-8")
    (skills / "v2_n_4_1.json").write_text("{ not json", encoding="utf-8")

    payload = assemble_registry(contracts, skills, BATCH2_PATH)
    assert [entry["node_id"] for entry in payload["chapters"]] == list(
        BATCH2_NODE_IDS
    )


# ---------------------------------------------------------------------------
# Source identity preservation (node/bookmark/style IDs and template hash).
# ---------------------------------------------------------------------------


def test_source_identity_is_preserved_from_the_accepted_node_tree(
    batch2_registry, node_tree
):
    heading = {node["id"]: node for node in node_tree["heading_style_tree"]["nodes"]}
    assert set(BATCH2_NODE_IDS) <= set(heading)
    for node_id in BATCH2_NODE_IDS:
        source_node = heading[node_id]
        assert source_node["is_leaf_heading"] is True
        contract = _contract(batch2_registry, node_id)
        assert contract.template_sha256 == TEMPLATE_SHA256
        word_rules = contract.word_rules
        assert source_node["style_id"] in word_rules.required_styles
        if source_node["bookmarks"]:
            assert set(source_node["bookmarks"]) <= set(word_rules.required_bookmarks)
        assert not (set(word_rules.required_styles) & set(word_rules.forbidden_styles))


def test_no_fifth_heading_is_invented_for_the_summary_measure(batch2_registry):
    declaring = [
        entry.node_id
        for entry in batch2_registry.chapters
        for item in entry.contract.substantive_content.fact_requirements
        if item.fact_path == "estimand.primary.population_summary_measure"
    ]
    assert declaring == ["v2_n_3_1_2_4"]
    assert set(declaring) <= set(BATCH2_NODE_IDS)
    # The carrier carries the ICE obligation and the summary measure together.
    contract = _contract(batch2_registry, "v2_n_3_1_2_4")
    required = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "required"
    }
    assert "estimand.primary.population_summary_measure" in required
    assert "estimand.primary.intercurrent_events" in required


# ---------------------------------------------------------------------------
# Per-node source obligations.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("node_id", sorted(EXPECTED_OBLIGATIONS))
def test_node_source_obligations_are_declared(batch2_registry, node_id):
    expected = EXPECTED_OBLIGATIONS[node_id]
    contract = _contract(batch2_registry, node_id)
    substantive = contract.substantive_content

    required_facts = {
        item.fact_path
        for item in substantive.fact_requirements
        if item.obligation.value == "required"
    }
    assert set(expected["required_facts"]) <= required_facts

    declared_claims = {
        item.claim_type: item.obligation.value
        for item in substantive.claim_requirements
    }
    for claim in expected["required_claims"]:
        assert declared_claims.get(claim) == "required"
    for claim in expected["forbidden_claims"]:
        assert declared_claims.get(claim) == "forbidden"

    groups = substantive.evidence_source_requirements
    assert len(groups) == len(expected["evidence_groups"])
    for group, (roles, admissions) in zip(groups, expected["evidence_groups"]):
        assert isinstance(group, EvidenceSourceRequirement)
        assert tuple(item.value for item in group.source_roles) == roles
        assert tuple(group.admission_claim_types) == admissions

    object_kinds = tuple(
        item.object_kind.value for item in substantive.structural_object_obligations
    )
    assert object_kinds == expected["object_kinds"]
    required_cells = {
        cell
        for item in substantive.structural_object_obligations
        for cell in item.required_object_cells
    }
    assert required_cells == set(expected["required_cells"])

    assert contract.positive_qc_rules
    assert substantive.skeleton_risk_rules
    assert substantive.project_specific_elements


def test_estimand_attributes_are_four_headings_plus_the_summary_measure(
    batch2_registry,
):
    attribute_facts = {
        "v2_n_3_1_2_1": "estimand.primary.population",
        "v2_n_3_1_2_2": "estimand.primary.variable",
        "v2_n_3_1_2_3": "estimand.primary.treatment_condition",
        "v2_n_3_1_2_4": "estimand.primary.intercurrent_events",
    }
    for node_id, fact_path in attribute_facts.items():
        contract = _contract(batch2_registry, node_id)
        required = {
            item.fact_path
            for item in contract.substantive_content.fact_requirements
            if item.obligation.value == "required"
        }
        assert fact_path in required
    # Four attribute headings exist; the summary measure rides inside the ICE
    # carrier as a separate obligation rather than as a fabricated fifth leaf.
    assert len(attribute_facts) == 4
    summary_contract = _contract(batch2_registry, "v2_n_3_1_2_4")
    summary_rule_ids = {
        rule.positive_qc_rule_id
        for rule in summary_contract.positive_qc_rules
    }
    assert summary_rule_ids
    assert any(
        "population_summary_measure" in item
        or "汇总" in item
        for item in summary_contract.substantive_content.project_specific_elements
    )


def test_population_attribute_keeps_target_population_distinct_from_analysis_sets(
    batch2_registry,
):
    contract = _contract(batch2_registry, "v2_n_3_1_2_1")
    facts = {
        item.fact_path: (item.obligation.value, item.rationale)
        for item in contract.substantive_content.fact_requirements
    }
    assert facts["estimand.primary.analysis_set_distinction"][0] == "required"
    # Population description keeps its own fact path and is optional here.
    assert facts["picos.population_summary"][0] == "optional"


def test_variable_attribute_requires_measurement_aggregation_and_timepoint(
    batch2_registry,
):
    contract = _contract(batch2_registry, "v2_n_3_1_2_2")
    required = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "required"
    }
    assert {
        "estimand.primary.variable_measurement",
        "estimand.primary.variable_aggregation",
        "estimand.primary.variable_timepoint_window",
    } <= required
    declared = {
        item.claim_type: item.obligation.value
        for item in contract.substantive_content.claim_requirements
    }
    assert declared["label_only_variable"] == "forbidden"


def test_treatment_condition_attribute_clarifies_the_source_effect_label(
    batch2_registry,
):
    contract = _contract(batch2_registry, "v2_n_3_1_2_3")
    required = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "required"
    }
    assert "estimand.primary.treatment_effect_label_clarification" in required
    assert "estimand.primary.background_treatment" in required
    assert contract.conditional_applicability_rules


def test_ice_carrier_cross_checks_summary_and_strategy(batch2_registry):
    contract = _contract(batch2_registry, "v2_n_3_1_2_4")
    rules = {
        rule.conditional_applicability_rule_id: rule
        for rule in contract.conditional_applicability_rules
    }
    assert rules, "the summary/ICE carrier must keep its conditional cross-check"
    combined = {
        path
        for rule in contract.conditional_applicability_rules
        for path in rule.required_when_active_fact_paths
    }
    assert "estimand.primary.ice_strategy_crosscheck" in combined
    # The source's REF field on this leaf points at the ICE table caption.
    assert "表 1 伴发事件及处理策略" in contract.word_rules.required_cross_references


def test_competitor_evidence_cannot_admit_own_product_clinical_claims(
    batch2_registry,
):
    contract = _contract(batch2_registry, "v2_n_2_2_3")
    groups = contract.substantive_content.evidence_source_requirements
    assert len(groups) >= 2
    own_groups = [
        group
        for group in groups
        if "own_product_clinical_evidence" in group.admission_claim_types
    ]
    competitor_groups = [
        group
        for group in groups
        if "competitor_evidence_summary" in group.admission_claim_types
    ]
    assert len(own_groups) == 1
    assert len(competitor_groups) == 1
    assert "competitor_full_protocol" not in {
        role.value for role in own_groups[0].source_roles
    }
    assert "project_primary" not in {
        role.value for role in competitor_groups[0].source_roles
    }
    assert own_groups[0] is not competitor_groups[0]


def test_unheaded_preclinical_and_mechanism_obligations_are_preserved(
    batch2_registry,
):
    preclinical = _contract(batch2_registry, "v2_n_2_2_2_1")
    substantive = preclinical.substantive_content
    claims = [item.claim_type for item in substantive.claim_requirements if item.obligation.value == "required"]
    assert len(claims) == 4
    admission_sets = [
        group.admission_claim_types for group in substantive.evidence_source_requirements
    ]
    assert len(admission_sets) == 4
    assert len({value for group in admission_sets for value in group}) == 4
    # One pharmacodynamics paragraph cannot discharge all four obligations.
    paragraph = [
        item
        for item in substantive.structural_object_obligations
        if item.object_kind.value == "paragraph"
    ]
    assert paragraph and paragraph[0].minimum_occurrences >= 4

    product = _contract(batch2_registry, "v2_n_2_2_1")
    mechanism = [
        item
        for item in product.substantive_content.fact_requirements
        if item.fact_path == "background.product.mechanism"
    ]
    assert mechanism and mechanism[0].obligation.value == "required"
    declarations = " ".join(product.substantive_content.project_specific_elements)
    assert "继承" in declarations and "@284" in declarations


def test_risk_benefit_keeps_compensation_and_source_wording_bounded(
    batch2_registry,
):
    contract = _contract(batch2_registry, "v2_n_2_3")
    declared = {
        item.claim_type: item.obligation.value
        for item in contract.substantive_content.claim_requirements
    }
    assert declared["compensation_as_benefit"] == "forbidden"
    rules = " ".join(rule.rule for rule in contract.positive_qc_rules)
    assert "@306" in rules
    elements = " ".join(contract.substantive_content.project_specific_elements)
    assert "补偿" in elements


def test_primary_objective_does_not_promote_the_source_rescue_example(
    batch2_registry,
):
    contract = _contract(batch2_registry, "v2_n_3_1_1")
    substantive = contract.substantive_content
    facts = {
        item.fact_path: item.obligation.value for item in substantive.fact_requirements
    }
    assert facts["design.rescue_treatment_planned"] == "optional"
    assert facts["design.discontinuation_rescue_strategy"] == "optional"
    qualified = {
        item.claim_type: item
        for item in substantive.claim_requirements
        if item.obligation.value == "qualified"
    }
    assert "rescue_strategy_statement" in qualified
    assert qualified["rescue_strategy_statement"].qualifying_conditions
    rules = contract.conditional_applicability_rules
    assert len(rules) == 1
    assert "design.discontinuation_rescue_strategy" in rules[0].required_when_active_fact_paths


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


def test_fixture_families_and_conspicuous_synthetic_conventions(batch2_registry):
    fixtures = batch2_registry.fixtures
    assert len(fixtures) >= 64
    by_contract: dict[str, set[str]] = {
        entry.contract.chapter_contract_id: set() for entry in batch2_registry.chapters
    }
    for fixture in fixtures:
        by_contract[fixture.chapter_contract_id].add(fixture.fixture_kind)
        assert fixture.fixture_id.startswith("fixture:batch2:")
        assert fixture.supplied_passed is None
        assert fixture.supplied_qc_verdict is None
    for contract_id, kinds in by_contract.items():
        for family in REQUIRED_FAMILIES:
            assert kinds & family, f"{contract_id} misses family {sorted(family)}"
    assert len(fixtures) == len({fixture.fixture_id for fixture in fixtures})


def test_positive_fixtures_pass_and_negatives_fail_for_their_reason(
    batch2_registry,
):
    results = {}
    for fixture in batch2_registry.fixtures:
        result = check_fixture(batch2_registry, fixture)
        results[fixture.fixture_id] = result
        if fixture.fixture_kind == "positive":
            assert result.passed is True, (fixture.fixture_id, _error_codes(result))
        else:
            assert result.passed is False, fixture.fixture_id
    # Supplied self-verdicts are never trusted and never fabricated.
    assert all(
        not result.ignored_supplied_verdict for result in results.values()
    )
    # Deterministic passes stay explicitly short of medical judgment.
    positives = [
        result
        for fixture_id, result in results.items()
        if fixture_id.endswith(":positive")
    ]
    assert positives
    for result in positives:
        assert any(
            "medical_and_qc_judgment_not_executed" in item
            for item in result.deferred_qc_obligations
        )


def test_source_specific_negatives_target_their_own_reason(batch2_registry):
    fixtures = _fixture_index(batch2_registry)
    for fixture_id, expected_codes in SOURCE_SPECIFIC_NEGATIVES.items():
        assert fixture_id in fixtures, fixture_id
        result = check_fixture(batch2_registry, fixtures[fixture_id])
        assert result.passed is False
        assert set(expected_codes) <= _error_codes(result), (
            fixture_id,
            _error_codes(result),
        )

    # Competitor evidence supplied as own-product clinical evidence must fail as
    # a source-role violation, not as an undeclared claim.
    result = check_fixture(
        batch2_registry,
        fixtures["fixture:batch2:v2-n-2-2-3:competitor-as-own-clinical"],
    )
    codes = _error_codes(result)
    assert "wrong_source_role" in codes
    assert "inadmissible_claim" not in codes
    assert any(
        "own_product_clinical_evidence" in finding.message
        for finding in result.findings
        if finding.code == "wrong_source_role"
    )

    # The general-pharmacology group is the independent group that fails.
    result = check_fixture(
        batch2_registry,
        fixtures["fixture:batch2:v2-n-2-2-2-1:missing-general-pharmacology-group"],
    )
    assert any(
        "evidence_source_requirements[3]" in location
        for location in _error_locations(result, "unsatisfied_evidence_requirement")
    )

    # A method name alone cannot discharge the population-summary obligation.
    for fixture_id in (
        "fixture:batch2:v2-n-3-1-2-4:missing-population-summary-measure",
        "fixture:batch2:v2-n-3-1-2-4:summary-measure-method-name-only",
    ):
        result = check_fixture(batch2_registry, fixtures[fixture_id])
        locations = _error_locations(result, "missing_required_fact")
        assert any(
            "estimand.primary.population_summary_measure" in location
            for location in locations
        ), (fixture_id, locations)
    method_fixture = fixtures[
        "fixture:batch2:v2-n-3-1-2-4:summary-measure-method-name-only"
    ]
    summary_claim = [
        claim
        for claim in method_fixture.content.claims
        if claim.claim_type == "estimand_population_summary_attribute"
    ]
    assert summary_claim and (summary_claim[0].statement or "").strip()

    # Empty ICE rows fail as missing material cells, not as identity errors.
    result = check_fixture(
        batch2_registry, fixtures["fixture:batch2:v2-n-3-1-2-4:empty-ice-entries"]
    )
    assert "missing_required_cell" in _error_codes(result)


def test_forbidden_claim_negatives_are_exercised(batch2_registry):
    fixtures = _fixture_index(batch2_registry)
    for fixture_id in FORBIDDEN_CLAIM_NEGATIVES:
        assert fixture_id in fixtures, fixture_id
        result = check_fixture(batch2_registry, fixtures[fixture_id])
        assert "forbidden_claim_present" in _error_codes(result), fixture_id
        assert result.passed is False


def test_blank_obligation_keys_do_not_satisfy_required_content(batch2_registry):
    """Key presence with blank values is still a missing obligation."""

    blanked = None
    for fixture in batch2_registry.fixtures:
        if fixture.fixture_id == "fixture:batch2:v2-n-2-1:missing-control":
            blanked = fixture
    assert blanked is not None
    assert blanked.content.facts, "the negative keeps its heading/fact keys"
    assert all(not (fact.value or "").strip() for fact in blanked.content.facts)
    result = check_fixture(batch2_registry, blanked)
    assert "missing_required_fact" in _error_codes(result)
    assert result.passed is False


# ---------------------------------------------------------------------------
# Partial lint: clean batch, complete expected missing coverage.
# ---------------------------------------------------------------------------


def test_partial_lint_is_clean_and_enumerates_full_missing_coverage(
    batch2_registry, node_tree
):
    report = lint_registry(TEMPLATE_DIR, batch2_registry, require_complete=False)
    assert report.mode == "partial"
    assert report.status == "incomplete"
    assert report.errors() == (), [f.code for f in report.errors()]

    leaf_union = _leaf_union(node_tree)
    mapping = json.loads(
        (TEMPLATE_DIR / "v1_to_v2_mapping.json").read_text(encoding="utf-8")
    )
    cover_ids = {
        node
        for row in mapping["forward_mapping"]
        if row.get("semantic_node_id") == "document_control.front_matter"
        for node in row["target_v2_node_ids"]
    }
    assert len(cover_ids) == 1
    expected_carriers = leaf_union | cover_ids

    assert report.coverage.leaf_union_count == len(leaf_union)
    assert report.coverage.expected_carrier_count == len(leaf_union) + 1
    assert report.coverage.covered_carrier_count == 16
    assert report.coverage.missing_node_ids == tuple(
        sorted(expected_carriers - set(BATCH2_NODE_IDS))
    )
    assert not (set(report.coverage.missing_node_ids) & set(BATCH2_NODE_IDS))
    assert report.coverage.unexpected_node_ids == ()
    assert "partial_mode_not_full_acceptance" in {
        finding.code for finding in report.findings
    }
    assert "fixture_expectation_mismatch" not in {
        finding.code for finding in report.findings
    }
    assert len(report.fixture_results) == len(batch2_registry.fixtures)
    assert [result.subject_id for result in report.fixture_results] == [
        fixture.fixture_id for fixture in batch2_registry.fixtures
    ]


def test_partial_lint_reports_missing_fixture_families_as_info_only_for_other_nodes(
    batch2_registry,
):
    """Batch-scope: only the sixteen batch2 carriers may draw fixture findings."""

    report = lint_registry(TEMPLATE_DIR, batch2_registry, require_complete=False)
    fixture_findings = [
        finding
        for finding in report.findings
        if finding.code == "missing_fixture"
    ]
    assert fixture_findings == []
    node_ids = {finding.node_id for finding in report.findings if finding.node_id}
    assert node_ids <= set(BATCH2_NODE_IDS)
