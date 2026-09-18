"""Task3R.3 batch4 tests: source-bound chapter contracts for chapters 6–8.

Batch4 covers exactly the sixteen leaf carriers of sections 6（研究干预）、
7（研究程序和评估的访视期） and 8（中止/退出/失访） of the accepted TP-MA-07
v2 candidate registry: ``v2_n_6_1_1`` .. ``v2_n_8_3``.  The authored per-node
contract/skill JSON files are the single source of contract truth;
``batch4.json`` carries only the closed fact/claim vocabularies, coverage
roles and the executable fixture payloads, and the assembly CLI joins them
into an accepted ``ChapterRegistryDocument`` shape.

Red-first contract: these tests assert batch-scoped source obligations and
were observed failing before the artifacts existed.  They encode the batch4
content spec (reviews/mw_protocol_v3_3r3_batch4_content_spec_20260906.md)
obligations the batch exists to satisfy:

* every actual intervention/comparator is bound to typed route/regimen/dose
  facts and template example values stay example-only;
* dose holds, reductions, restarts, permanent discontinuation and missed doses
  each carry product-specific triggers instead of a copied grade threshold;
* storage/handling/accountability carry real units and conditions;
* adherence measurement declares its evidence source, so the denominator
  cannot be silently omitted;
* permitted/prohibited/rescue treatments keep timing, records and
  endpoint/estimand implications, and rescue must agree with the estimand;
* individual temporary hold, permanent treatment discontinuation, withdrawal
  from participation and trial-level suspension/termination stay separately
  typed (the source mixes them under one heading at 496–511);
* continued assessments after discontinuation, existing-data treatment and
  replacement policy are scenario-specific;
* withdrawal reasons may be requested but are never compulsory;
* lost-to-follow-up needs project-specific contact attempts, records and
  classification, and a missed visit alone is never sufficient.

A passing partial lint never represents full acceptance; medical judgment and
native-Word checks stay explicitly deferred.  Coverage truth is always the
template ``node_tree.json``; file presence in shared directories is asserted
as a superset only, and other batches' files never affect these tests.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.protocol_workflow.registries.chapters import (
    check_fixture,
    lint_registry,
    load_chapter_registry,
)
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_TEMPLATE_DIR = REPO_ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
CONTRACTS_DIR = REAL_TEMPLATE_DIR / "chapter_contracts"
SKILLS_DIR = REAL_TEMPLATE_DIR / "chapter_skills"
BATCH_PATH = (
    REPO_ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch4.json"
)
ASSEMBLY_SCRIPT = REPO_ROOT / "scripts/qc/protocol_v3/assemble_chapter_registry.py"

TEMPLATE_ID = "tp_ma_07_v2"
TEMPLATE_SHA256 = (
    "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
)

#: Sections 6–8 carriers with their derived coverage roles.
EXPECTED_CARRIERS = {
    "v2_n_6_1_1": "heading_leaf",
    "v2_n_6_1_2": "heading_leaf",
    "v2_n_6_2_1": "heading_leaf",
    "v2_n_6_2_2": "heading_leaf",
    "v2_n_6_2_3": "heading_leaf",
    "v2_n_6_2_4": "heading_leaf",
    "v2_n_6_3": "heading_leaf",
    "v2_n_6_4_1": "heading_leaf",
    "v2_n_6_4_2": "heading_leaf",
    "v2_n_6_4_3": "heading_leaf",
    "v2_n_7_1": "heading_leaf",
    "v2_n_7_2": "heading_leaf",
    "v2_n_7_3": "heading_leaf",
    "v2_n_8_1": "heading_leaf",
    "v2_n_8_2": "heading_leaf",
    "v2_n_8_3": "heading_leaf",
}

#: The missing-genuine-obligation family chosen per node (the other missing
#: variant stays absent for that node), and the fixture family suffix used.
MISSING_FAMILY = {
    "v2_n_6_1_1": "missing_control",
    "v2_n_6_1_2": "missing_control",
    "v2_n_6_2_1": "missing_control",
    "v2_n_6_2_2": "missing_control",
    "v2_n_6_2_3": "missing_control",
    "v2_n_6_2_4": "missing_claim",
    "v2_n_6_3": "missing_control",
    "v2_n_6_4_1": "missing_control",
    "v2_n_6_4_2": "missing_claim",
    "v2_n_6_4_3": "missing_control",
    "v2_n_7_1": "missing_control",
    "v2_n_7_2": "missing_control",
    "v2_n_7_3": "missing_claim",
    "v2_n_8_1": "missing_control",
    "v2_n_8_2": "missing_control",
    "v2_n_8_3": "missing_control",
}

#: The content-spec negative each node's batch must exercise, and the exact
#: deterministic error code that proves it failed for its named reason.
NAMED_NEGATIVES = {
    "v2_n_6_1_1": ("missing_control", "missing_required_fact"),
    "v2_n_6_1_2": ("missing_control", "missing_required_fact"),
    "v2_n_6_2_1": ("missing_control", "missing_required_fact"),
    "v2_n_6_2_2": ("missing_control", "missing_required_cell"),
    "v2_n_6_2_3": ("missing_control", "missing_required_cell"),
    "v2_n_6_2_4": ("missing_claim", "missing_required_claim"),
    "v2_n_6_3": ("missing_control", "missing_required_fact"),
    "v2_n_6_4_1": ("missing_control", "missing_required_fact"),
    "v2_n_6_4_2": ("missing_claim", "missing_required_claim"),
    "v2_n_6_4_3": ("wrong_source", "wrong_source_role"),
    "v2_n_7_1": ("missing_control", "missing_required_fact"),
    "v2_n_7_2": ("missing_control", "missing_required_fact"),
    "v2_n_7_3": ("missing_claim", "missing_required_claim"),
    "v2_n_8_1": ("missing_control", "missing_required_cell"),
    "v2_n_8_2": ("wrong_source", "wrong_source_role"),
    "v2_n_8_3": ("missing_control", "missing_required_fact"),
}

#: Nodes whose NAMED negative is not the missing family; their missing-family
#: fixture still must fail for its own intended reason.
MISSING_FAMILY_CODES = {
    "v2_n_6_2_4": "missing_required_claim",
    "v2_n_6_4_2": "missing_required_claim",
    "v2_n_6_4_3": "missing_required_fact",
    "v2_n_7_3": "missing_required_claim",
    "v2_n_8_2": "missing_required_fact",
}

#: Table contracts that declare stable required cell selectors; every positive
#: fixture must carry non-blank values for each declared cell.
CELL_OBLIGATION_CONTRACTS = {
    "v2_n_6_1_1": (
        "intervention:cell:drug_identity",
        "intervention:cell:formulation_strength",
        "intervention:cell:source_authority",
    ),
    "v2_n_6_1_2": (
        "intervention:cell:route",
        "intervention:cell:dose",
        "intervention:cell:interval",
        "intervention:cell:duration",
    ),
    "v2_n_6_2_1": (
        "intervention:cell:receipt_identity",
        "intervention:cell:accountability_record",
        "intervention:cell:destruction_record",
    ),
    "v2_n_6_2_2": (
        "intervention:cell:packaging",
        "intervention:cell:label_binding",
    ),
    "v2_n_6_2_3": (
        "intervention:cell:storage_condition",
        "intervention:cell:storage_unit",
    ),
    "v2_n_6_4_1": ("intervention:cell:prohibited_item",),
    "v2_n_6_4_2": ("intervention:cell:allowed_item",),
    "v2_n_6_4_3": ("intervention:cell:rescue_plan",),
    "v2_n_8_1": (
        "discontinuation:cell:individual_trigger",
        "discontinuation:cell:trial_trigger",
        "discontinuation:cell:trial_decision_authority",
    ),
    "v2_n_8_3": ("followup:cell:contact_attempt_log",),
}

#: Source-specific negatives required by the content spec's 夹具义务 section,
#: each proving one named failure reason rather than a generic one.
SOURCE_SPECIFIC_NEGATIVES = {
    "v2_n_6_1_2": "conflicting-drug-facts",
    "v2_n_6_2_2": "copied-grade-threshold",
    "v2_n_6_2_3": "empty-storage-condition",
    "v2_n_6_3": "adherence-denominator-omitted",
    "v2_n_6_4_3": "rescue-estimand-inconsistent",
    "v2_n_8_2": "followup-silent-last-dose",
    "v2_n_8_1": "individual-equals-trial-stop",
    "v2_n_7_3": "invented-approval-receipt",
}

#: Intended failure codes per source-specific negative (fresh-review D2): a
#: regression that flips the failure reason must break the test, not pass it.
SOURCE_NEGATIVE_EXPECTED_CODES = {
    "v2_n_6_1_2:conflicting-drug-facts": ("forbidden_fact_present", "missing_required_fact"),
    "v2_n_6_2_2:copied-grade-threshold": ("missing_required_claim",),
    "v2_n_6_2_3:empty-storage-condition": ("missing_required_cell",),
    "v2_n_6_3:adherence-denominator-omitted": ("missing_required_fact",),
    "v2_n_6_4_3:rescue-estimand-inconsistent": ("missing_required_claim", "missing_required_fact"),
    "v2_n_8_2:followup-silent-last-dose": ("missing_required_fact",),
    "v2_n_8_1:individual-equals-trial-stop": ("missing_required_cell",),
    "v2_n_7_3:invented-approval-receipt": ("forbidden_claim_present", "missing_required_claim"),
}

#: Exact source body-child window each carrier is bound to (zero-based
#: body-child indexes, matching the template node_tree extraction).
SOURCE_WINDOWS = {
    "v2_n_6_1_1": (423, 426),
    "v2_n_6_1_2": (427, 432),
    "v2_n_6_2_1": (435, 439),
    "v2_n_6_2_2": (440, 461),
    "v2_n_6_2_3": (462, 463),
    "v2_n_6_2_4": (464, 465),
    "v2_n_6_3": (466, 469),
    "v2_n_6_4_1": (476, 477),
    "v2_n_6_4_2": (478, 480),
    "v2_n_6_4_3": (481, 483),
    "v2_n_7_1": (485, 486),
    "v2_n_7_2": (488, 489),
    "v2_n_7_3": (491, 493),
    "v2_n_8_1": (499, 511),
    "v2_n_8_2": (512, 537),
    "v2_n_8_3": (538, 546),
}

FORBIDDEN_BATCH4_TERM = "受试者"


def _load_assembly_module():
    spec = importlib.util.spec_from_file_location(
        "assemble_chapter_registry", ASSEMBLY_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _error_codes(result) -> set[str]:
    return {finding.code for finding in result.findings if finding.severity == "error"}


def _contract(node_id: str) -> ChapterContractV2:
    return ChapterContractV2.model_validate(
        json.loads((CONTRACTS_DIR / f"{node_id}.json").read_text(encoding="utf-8"))
    )


def _required_facts(contract: ChapterContractV2) -> set[str]:
    return {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "required"
    }


def _required_claims(contract: ChapterContractV2) -> set[str]:
    return {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "required"
    }


def _fixtures_by_node(document) -> dict[str, dict[str, list]]:
    by_node: dict[str, dict[str, list]] = {}
    for fixture in document.fixtures:
        node_id = next(
            entry.node_id
            for entry in document.chapters
            if entry.contract.chapter_contract_id == fixture.chapter_contract_id
        )
        by_node.setdefault(node_id, {}).setdefault(fixture.fixture_kind, []).append(
            fixture
        )
    return by_node


def _fixture(document, node_id: str, suffix: str):
    contract_id = f"contract:{node_id.replace('_', '-')}:v2"
    return next(
        fixture
        for fixture in document.fixtures
        if fixture.chapter_contract_id == contract_id
        and fixture.fixture_id.endswith(f":{suffix}")
    )


@pytest.fixture(scope="module")
def registry_payload() -> dict:
    module = _load_assembly_module()
    return module.assemble_registry(CONTRACTS_DIR, SKILLS_DIR, BATCH_PATH)


@pytest.fixture(scope="module")
def registry_document(registry_payload):
    return load_chapter_registry(registry_payload)


# ---------------------------------------------------------------------------
# Authored file identity: contracts and skills on the accepted template.
# ---------------------------------------------------------------------------


def test_contract_and_skill_files_exist_with_exact_identities():
    # Superset, not equality: other batches author into the same directories
    # concurrently; the selected-batch exactly-16 guarantee is asserted by the
    # assembly tests below.
    assert set(EXPECTED_CARRIERS) <= {p.stem for p in CONTRACTS_DIR.glob("*.json")}
    assert set(EXPECTED_CARRIERS) <= {p.stem for p in SKILLS_DIR.glob("*.json")}
    for stem in EXPECTED_CARRIERS:
        contract = ChapterContractV2.model_validate(
            json.loads((CONTRACTS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        )
        assert contract.semantic_node_id == stem
        assert contract.chapter_contract_id == f"contract:{stem.replace('_', '-')}:v2"
        assert contract.template_id == TEMPLATE_ID
        assert contract.template_sha256 == TEMPLATE_SHA256
        assert contract.canonical_state.value == "frozen"
        skill = json.loads((SKILLS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        assert skill["node_id"] == stem
        assert skill["chapter_contract_id"] == contract.chapter_contract_id
        assert skill["skill_id"] == contract.chapter_skill_id
        assert skill["skill_version"] == contract.chapter_skill_version
        assert skill["template_id"] == TEMPLATE_ID
        assert skill["template_sha256"] == TEMPLATE_SHA256
        # Skill prompts are node-specific content instructions, not transport.
        assert "provider" not in skill and "model" not in skill
        assert skill["input_schema_ref"] == (
            "app.protocol_workflow.registries.chapters:ChapterSkillInput"
        )
        assert skill["output_schema_ref"] == (
            "app.protocol_workflow.registries.chapters:ChapterSkillOutput"
        )


def test_all_sixteen_carriers_present_with_derived_coverage_roles(registry_document):
    node_tree = json.loads(
        (REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8")
    )
    heading_leaves = {
        n["id"]
        for n in node_tree["heading_style_tree"]["nodes"]
        if n.get("is_leaf_heading")
    }
    outline_leaves = {
        n["id"] for n in node_tree["outlined_tree"]["nodes"] if n.get("is_leaf")
    }
    entries = {entry.node_id: entry for entry in registry_document.chapters}
    assert set(entries) == set(EXPECTED_CARRIERS)
    for node_id, role in EXPECTED_CARRIERS.items():
        assert entries[node_id].coverage_role == role, node_id
        assert node_id in heading_leaves and node_id in outline_leaves, node_id


def test_contracts_bind_the_exact_source_body_child_windows():
    """Every carrier is derived from the template extraction window it claims;
    binding is checked against node_tree.json, never invented offsets."""
    node_tree = json.loads(
        (REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8")
    )
    heading = {n["id"]: n for n in node_tree["heading_style_tree"]["nodes"]}
    for node_id, (first, last) in SOURCE_WINDOWS.items():
        node = heading[node_id]
        assert node["body_child_index"] == first, node_id
        indexes = node["content_paragraph_indexes"]
        assert indexes and indexes[0] == first + 1, node_id
        assert max(indexes) == last, node_id
        assert last > first


def test_table_cell_obligations_are_declared_and_exercised(registry_document):
    contracts = {entry.node_id: entry.contract for entry in registry_document.chapters}
    for node_id, expected_cells in CELL_OBLIGATION_CONTRACTS.items():
        declared: set[str] = set()
        for obligation in contracts[
            node_id
        ].substantive_content.structural_object_obligations:
            declared.update(obligation.required_object_cells)
        assert declared == set(expected_cells), node_id
    # Every positive fixture carries non-blank values for all declared cells.
    for fixture in registry_document.fixtures:
        if fixture.fixture_kind != "positive":
            continue
        node_id = next(
            entry.node_id
            for entry in registry_document.chapters
            if entry.contract.chapter_contract_id == fixture.chapter_contract_id
        )
        if node_id not in CELL_OBLIGATION_CONTRACTS:
            continue
        supplied = {
            cell.cell_id: cell
            for obj in fixture.content.objects
            for cell in obj.cells
        }
        for cell_id in CELL_OBLIGATION_CONTRACTS[node_id]:
            assert (supplied[cell_id].value or "").strip(), (node_id, cell_id)


# ---------------------------------------------------------------------------
# Fixture families: four per node minimum, all sixteen nodes, every negative
# failing for its named reason.
# ---------------------------------------------------------------------------


def test_every_fixture_exercises_its_named_defect(registry_document):
    by_node = _fixtures_by_node(registry_document)
    assert set(by_node) == set(EXPECTED_CARRIERS)
    total = 0
    for node_id, kinds in by_node.items():
        expected_kind, expected_code = NAMED_NEGATIVES[node_id]
        # Every positive must pass; no negative may pass.
        for fixture in kinds.get("positive", []):
            result = check_fixture(registry_document, fixture)
            assert result.passed is True, (node_id, fixture.fixture_id)
            assert not _error_codes(result)
            # A deterministic pass never claims medical/QC judgment happened.
            assert result.deferred_qc_obligations
        named = check_fixture(
            registry_document,
            next(
                f
                for f in kinds[expected_kind]
                if f.fixture_id.endswith(expected_kind.replace("_", "-"))
            ),
        )
        assert named.passed is False, node_id
        assert expected_code in _error_codes(named), node_id
        if node_id in MISSING_FAMILY_CODES:
            missing = check_fixture(
                registry_document, kinds[MISSING_FAMILY[node_id]][0]
            )
            assert missing.passed is False, node_id
            assert MISSING_FAMILY_CODES[node_id] in _error_codes(missing), node_id
        wrong = check_fixture(registry_document, kinds["wrong_source"][0])
        assert "wrong_source_role" in _error_codes(wrong), node_id
        skeleton = check_fixture(registry_document, kinds["skeleton"][0])
        assert "skeleton_content" in _error_codes(skeleton), node_id
        for kind, fixtures in kinds.items():
            if kind == "positive":
                continue
            for fixture in fixtures:
                result = check_fixture(registry_document, fixture)
                assert result.passed is False, (node_id, fixture.fixture_id)
        # Spec-required families plus the source-specific negatives.
        assert {"positive", "wrong_source", "skeleton"} <= set(kinds), node_id
        assert kinds.get("missing_claim") or kinds.get("missing_control"), node_id
        total += sum(len(items) for items in kinds.values())
    # 16 nodes x at least 4 families; the spec's source-specific negatives
    # push the authored total above the four-per-node floor.
    assert total >= 64
    assert total == len(registry_document.fixtures)


def test_source_specific_negatives_fail_for_their_named_reason(registry_document):
    """The content spec's 夹具义务 list: each required negative exists and its
    deterministic failure is the reason it exists for, not an identity error."""
    by_node = _fixtures_by_node(registry_document)
    for node_id, suffix in SOURCE_SPECIFIC_NEGATIVES.items():
        fixture = _fixture(registry_document, node_id, suffix)
        result = check_fixture(registry_document, fixture)
        assert result.passed is False, (node_id, suffix)
        codes = _error_codes(result)
        expected = SOURCE_NEGATIVE_EXPECTED_CODES[f"{node_id}:{suffix}"]
        assert set(expected) <= set(codes), (node_id, suffix, codes, expected)
        assert fixture.fixture_id in {
            item.fixture_id for item in by_node[node_id][fixture.fixture_kind]
        }


def test_conflicting_dose_facts_and_copied_thresholds_are_rejected(registry_document):
    """Conflicting dose/regimen facts across sections and copied grade
    thresholds without support are explicit negative material."""
    conflict = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_6_1_2", "conflicting-drug-facts"),
    )
    assert conflict.passed is False
    assert "missing_required_fact" in _error_codes(conflict)
    # The conflicting value may only appear as an undeclared/forbidden payload,
    # never as an admitted project fact.
    contract = _contract("v2_n_6_1_2")
    forbidden = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    assert "intervention.template_example_hold_threshold" in forbidden
    threshold = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_6_2_2", "copied-grade-threshold"),
    )
    assert threshold.passed is False
    assert "missing_required_claim" in _error_codes(threshold)


def test_negative_fixtures_carry_no_identity_or_clinical_errors(registry_document):
    """Spec: separate structural checks from medical judgment.  A negative
    fixture must fail because of empty/unsupported content, never because it
    accidentally supplies a forbidden claim or a wrong identity.  The only
    exceptions are the two fixtures whose named defect *is* forbidden material:
    a conflicting template example fact and an invented approval/consent
    receipt."""
    allowed_forbidden = {
        "fixture:batch4:v2-n-6-1-2:conflicting-drug-facts",
        "fixture:batch4:v2-n-7-3:invented-approval-receipt",
    }
    forbidden_codes = {"forbidden_fact_present", "forbidden_claim_present"}
    for fixture in registry_document.fixtures:
        if fixture.fixture_kind == "positive":
            continue
        result = check_fixture(registry_document, fixture)
        assert result.passed is False, fixture.fixture_id
        if fixture.fixture_id in allowed_forbidden:
            assert _error_codes(result) & forbidden_codes, fixture.fixture_id
            continue
        assert not (_error_codes(result) & forbidden_codes), fixture.fixture_id


def test_synthetic_examples_are_conspicuous_and_booleans_bare(registry_document):
    """Batch1 D5 convention: boolean trigger facts are bare true/false and
    synthetic fixture values are visibly marked, never presented as project
    facts or approval receipts."""
    for node_id in EXPECTED_CARRIERS:
        for path in (
            CONTRACTS_DIR / f"{node_id}.json",
            SKILLS_DIR / f"{node_id}.json",
        ):
            text = path.read_text(encoding="utf-8")
            assert "合成" in text or "示例" in text, path.name
    for fixture in registry_document.fixtures:
        for fact in fixture.content.facts:
            if fact.fact_path.endswith("_applicable"):
                assert fact.value in {"true", "false"}, (fixture.fixture_id, fact.value)


def test_fixture_ids_follow_the_batch_hyphen_convention(registry_document):
    ids = {fixture.fixture_id for fixture in registry_document.fixtures}
    for node_id in EXPECTED_CARRIERS:
        slug = node_id.replace("_", "-")
        assert f"fixture:batch4:{slug}:positive" in ids, node_id
        assert f"fixture:batch4:{slug}:wrong-source" in ids, node_id
        assert f"fixture:batch4:{slug}:skeleton" in ids, node_id
        assert (
            f"fixture:batch4:{slug}:{MISSING_FAMILY[node_id].replace('_', '-')}" in ids
        ), node_id
    assert all(identifier.startswith("fixture:batch4:") for identifier in ids)


def test_forbidden_and_conditional_obligations_are_substantive(registry_document):
    """Every contract carries positive obligations plus real forbidden and
    (where declared) conditional semantics; no title-plus-one-fact shells."""
    for entry in registry_document.chapters:
        substantive = entry.contract.substantive_content
        required_facts = [
            f for f in substantive.fact_requirements if f.obligation.value == "required"
        ]
        required_claims = [
            c
            for c in substantive.claim_requirements
            if c.obligation.value == "required"
        ]
        forbidden = [
            f
            for f in substantive.fact_requirements
            if f.obligation.value == "forbidden"
        ] + [
            c
            for c in substantive.claim_requirements
            if c.obligation.value == "forbidden"
        ]
        assert required_facts or required_claims, entry.node_id
        assert forbidden, entry.node_id
        assert substantive.skeleton_risk_rules
        assert entry.contract.positive_qc_rules
        assert entry.contract.ctq_items
        assert substantive.evidence_source_requirements, entry.node_id


# ---------------------------------------------------------------------------
# Chapter 6: intervention and related procedures.
# ---------------------------------------------------------------------------


def test_intervention_identity_facts_are_typed_and_example_values_forbidden():
    contract = _contract("v2_n_6_1_1")
    required = _required_facts(contract)
    assert {
        "intervention.product_identity",
        "intervention.formulation",
        "intervention.exposure_dose",
        "intervention.route_of_administration",
    } <= required
    forbidden = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    assert "intervention.template_example_dose" in forbidden
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "示例" in qc_text and "不得作为项目事实" in qc_text


def test_dose_hold_restart_and_discontinuation_keep_product_specific_triggers():
    """Source 432 is an example grade-2 hold / grade-1 restart rule, not a
    universal rule; each action needs product-specific triggers."""
    contract = _contract("v2_n_6_1_2")
    required = _required_facts(contract)
    assert {
        "intervention.dose_hold_criteria",
        "intervention.dose_reduction_rules",
        "intervention.restart_criteria",
        "intervention.permanent_discontinuation_criteria",
        "intervention.missed_dose_instructions",
        "intervention.administration_instructions",
        "intervention.dose_escalation_or_dlt_logic",
    } <= required
    obligations = {
        item.fact_path: item.obligation.value
        for item in contract.substantive_content.fact_requirements
    }
    assert obligations["intervention.dose_modification_required"] == "optional"
    rule = next(
        r
        for r in contract.conditional_applicability_rules
        if r.conditional_applicability_rule_id == "applicability:n-6-1-2:dose-modification"
    )
    assert rule.triggering_fact_paths == ("intervention.dose_modification_required",)
    assert rule.required_when_active_fact_paths == ("intervention.dose_modification_features",)
    hold = next(r for r in contract.conditional_applicability_rules
                if r.conditional_applicability_rule_id == "applicability:n-6-1-2:hold")
    assert hold.required_when_active_fact_paths == ("intervention.dose_hold_criteria",)
    assert "intervention.dose_modification_features" in hold.triggering_fact_paths
    forbidden = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    assert "intervention.template_example_hold_threshold" in forbidden
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "示例" in qc_text and "各自动作" in qc_text


def test_storage_handling_and_accountability_carry_real_units():
    receipt = _contract("v2_n_6_2_1")
    assert {
        "intervention.receipt_and_inventory",
        "intervention.accountability_records",
        "intervention.dispensing_and_return",
        "intervention.destruction_authorization",
        "intervention.responsible_party",
    } <= _required_facts(receipt)
    packaging = _contract("v2_n_6_2_2")
    assert {"intervention.packaging_and_labeling"} <= _required_facts(packaging)
    label_rule = next(
        r
        for r in packaging.conditional_applicability_rules
        if "intervention.label_text" in r.required_when_active_fact_paths
    )
    assert label_rule.triggering_fact_paths == ("intervention.regulatory_labeling_check",)
    storage = _contract("v2_n_6_2_3")
    assert {
        "intervention.storage_conditions",
        "intervention.stability_handling",
        "intervention.storage_conditions.unit",
    } <= _required_facts(storage)
    qc_text = " ".join(q.rule for q in storage.positive_qc_rules)
    assert "空单位" in qc_text and "单位" in qc_text


def test_adherence_measurement_keeps_its_denominator_and_evidence_source():
    """Source 466–469: the 80–120% interval is an example, not an
    unconditional normal range; the chosen measure needs real records."""
    contract = _contract("v2_n_6_3")
    required = _required_facts(contract)
    assert {
        "intervention.adherence_measure",
        "intervention.adherence_denominator",
        "intervention.adherence_evidence_source",
        "intervention.planned_hold_tracking",
    } <= required
    forbidden = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    assert "intervention.template_example_interval" in forbidden
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "分母" in qc_text


def test_prohibited_allowed_and_rescue_treatments_stay_separated():
    prohibited = _contract("v2_n_6_4_1")
    assert {
        "intervention.prohibited_treatments",
        "intervention.prohibited_window",
    } <= _required_facts(prohibited)
    allowed = _contract("v2_n_6_4_2")
    required = _required_facts(allowed)
    assert {
        "intervention.allowed_treatments",
        "intervention.allowed_timing",
        "intervention.background_therapy_rules",
    } <= required
    assert "intervention.background_therapy_applicable" in {
        item.fact_path
        for item in allowed.substantive_content.fact_requirements
        if item.obligation.value == "optional"
    }
    forbidden = {
        item.fact_path
        for item in allowed.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    assert "intervention.template_example_concomitant_drug" in forbidden
    qc_text = " ".join(q.rule for q in allowed.positive_qc_rules)
    assert "禁止" in qc_text and "允许" in qc_text


def test_rescue_strategy_must_agree_with_the_estimand():
    contract = _contract("v2_n_6_4_3")
    required = _required_facts(contract)
    assert {
        "intervention.rescue_permitted",
        "intervention.rescue_timing",
        "intervention.rescue_records",
        "intervention.rescue_estimand_linkage",
        "intervention.rescue_followup_handling",
    } <= required
    forbidden_claims = {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "forbidden"
    }
    assert {
        "rescue_estimand_inconsistency",
        "unqualified_rescue_outcome_claim",
    } <= forbidden_claims
    assert "rescue_estimand_alignment" in _required_claims(contract)
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "估计目标" in qc_text and "非劣" in qc_text


# ---------------------------------------------------------------------------
# Chapter 7: visits and procedures.
# ---------------------------------------------------------------------------


def test_visit_phase_facts_agree_with_schedule_and_safety_period():
    screening = _contract("v2_n_7_1")
    assert {
        "procedure.screening_period_definition",
        "procedure.baseline_assessments",
        "procedure.screening_reassessment_rules",
    } <= _required_facts(screening)
    treatment = _contract("v2_n_7_2")
    required = _required_facts(treatment)
    assert {
        "procedure.treatment_period_definition",
        "procedure.dosing_start_rules",
        "procedure.treatment_visit_procedures",
        "procedure.blinded_treatment_handling",
        "procedure.randomization_day_rules",
    } <= required
    assert "procedure.randomized_on_day1" in {
        item.fact_path
        for item in treatment.substantive_content.fact_requirements
        if item.obligation.value == "optional"
    }
    rule = next(
        r
        for r in treatment.conditional_applicability_rules
        if r.conditional_applicability_rule_id == "applicability:n-7-2:randomization"
    )
    assert rule.triggering_fact_paths == ("procedure.randomized_on_day1",)
    forbidden = {
        item.fact_path
        for item in treatment.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    assert "procedure.template_example_visit_schedule" in forbidden


def test_followup_carrier_requires_window_units_and_phone_visits():
    contract = _contract("v2_n_7_3")
    required = _required_facts(contract)
    assert {
        "procedure.followup_period_definition",
        "procedure.followup_visit_windows",
        "procedure.phone_visit_linkage",
    } <= required
    assert "procedure.followup_unscheduled_and_phone_visits" in {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "optional"
    }
    rule = next(
        r
        for r in contract.conditional_applicability_rules
        if r.conditional_applicability_rule_id
        == "applicability:n-7-3:unscheduled-contact"
    )
    assert rule.triggering_fact_paths == (
        "procedure.followup_unscheduled_and_phone_visits",
    )
    assert set(rule.required_when_active_fact_paths) == {
        "procedure.contact_visit_date",
        "procedure.contact_visit_modality",
        "procedure.contact_visit_reason",
        "procedure.contact_visit_assessments",
    }
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "电话" in qc_text and "实际访视" in qc_text
    assert "单位" in qc_text and "参考事件" in qc_text


# ---------------------------------------------------------------------------
# Chapter 8: distinct cessation concepts.
# ---------------------------------------------------------------------------


def test_individual_and_trial_level_cessation_stay_separately_typed():
    """Source 496–511 mixes individual discontinuation and whole-trial
    suspension/termination; the contract must not replicate that conflation."""
    contract = _contract("v2_n_8_1")
    required = _required_facts(contract)
    assert "discontinuation.individual_hold_criteria" in required
    assert any(
        path.startswith("discontinuation.permanent_stop") for path in required
    )
    assert {
        "discontinuation.personal_hold",
        "discontinuation.permanent_stop_criteria.participant",
        "discontinuation.trial_suspension_criteria",
        "discontinuation.trial_termination_criteria",
        "discontinuation.trial_stop_decision_logic",
        "discontinuation.trial_stop_decision_authority",
        "discontinuation.trial_stop_post_decision",
        "discontinuation.safety_assessment_coherence",
    } <= required
    forbidden_claims = {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "forbidden"
    }
    assert {
        "individual_equals_trial_stop",
        "single_pivotal_trial_stop_rule",
    } <= forbidden_claims
    assert "trial_level_stop_criteria" in {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "required"
    }
    # The two levels stay separately typed: trial-level facts are declared on
    # the trial-level node, and the participant node declares its own facts.
    participant = _required_facts(_contract("v2_n_8_2"))
    assert not participant & {
        path
        for path in required
        if path.startswith("discontinuation.trial_")
    }
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "个体" in qc_text and "整体" in qc_text
    assert "疗效结论" in qc_text and "决策链" in qc_text


def test_discontinuation_does_not_end_followup_or_erase_data():
    contract = _contract("v2_n_8_2")
    required = _required_facts(contract)
    assert {
        "discontinuation.continued_assessment_scope",
        "discontinuation.continued_data_types",
        "discontinuation.time_limits",
        "discontinuation.existing_data_handling",
        "discontinuation.withdrawal_reason_recording",
        "discontinuation.withdrawal_scenarios",
        "discontinuation.followup_after_withdrawal",
        "discontinuation.data_retention_after_withdrawal",
        "discontinuation.replacement_policy",
        "discontinuation.disposition_schedule_integration",
    } <= required
    forbidden_claims = {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "forbidden"
    }
    assert {
        "withdrawal_reason_compulsory",
        "followup_terminates_at_last_dose",
        "silent_erase_prior_data",
        "treatment_stop_equals_consent_withdrawal",
    } <= forbidden_claims
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "不得设为强制" in qc_text
    assert "不得静默终止" in qc_text
    assert "不得删除" in qc_text
    # The replacement policy is declared and bound to the design analysis.
    assert "discontinuation.replacement_policy" in {
        item.linked_fact_paths[0]
        for item in contract.ctq_items
        if item.linked_fact_paths
    }


def test_lost_to_followup_needs_project_specific_attempts_and_classification():
    contract = _contract("v2_n_8_3")
    required = _required_facts(contract)
    assert {
        "lost_to_followup.contact_attempt_procedure",
        "lost_to_followup.participant_contact_restrictions",
        "lost_to_followup.attempt_records",
        "lost_to_followup.review_and_classification",
        "lost_to_followup.role_and_approvals",
        "lost_to_followup.consent_and_outcome_distinction",
    } <= required
    forbidden_claims = {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "forbidden"
    }
    assert {
        "missed_visit_equals_lost_to_followup",
        "unreached_equals_consent_withdrawal",
    } <= forbidden_claims
    # The "more than three calls" example may only appear as an example path,
    # never as a universal minimum.
    forbidden_facts = {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }
    assert "lost_to_followup.template_example_three_calls" in forbidden_facts
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "示例" in qc_text and "最低次数" in qc_text
    assert "单次漏访" in qc_text


# ---------------------------------------------------------------------------
# Evidence floors, terminology and the closed vocabulary.
# ---------------------------------------------------------------------------


def test_independently_required_claims_have_separate_evidence_groups():
    expected_groups = {
        "v2_n_6_1_1": [{"intervention_description"}],
        "v2_n_6_1_2": [{"dose_regimen_description"}],
        "v2_n_6_3": [{"adherence_strategy"}],
        "v2_n_6_4_3": [{"rescue_plan"}, {"rescue_estimand_alignment"}],
        "v2_n_8_2": [{"withdrawal_handling"}],
        "v2_n_8_3": [{"lost_to_followup_determination"}],
    }
    for node_id, wanted in expected_groups.items():
        contract = _contract(node_id)
        admissions = [
            set(group.admission_claim_types)
            for group in contract.substantive_content.evidence_source_requirements
        ]
        assert admissions == wanted, node_id
        for group in contract.substantive_content.evidence_source_requirements:
            assert group.require_context_window is True, node_id
            assert group.minimum_quality_score >= 0.9, node_id


def test_every_contract_declares_context_window_and_quality_floor(registry_document):
    for entry in registry_document.chapters:
        groups = entry.contract.substantive_content.evidence_source_requirements
        assert groups, entry.node_id
        for group in groups:
            assert group.require_context_window is True, entry.node_id
            assert group.minimum_quality_score >= 0.9, entry.node_id
            assert group.allowed_locator_kinds, entry.node_id
            assert group.source_roles, entry.node_id


def test_closed_vocabularies_cover_every_declared_path_and_claim(
    registry_document,
):
    fact_vocabulary = set(registry_document.fact_vocabulary)
    claim_vocabulary = set(registry_document.claim_vocabulary)
    used_facts: set[str] = set()
    used_claims: set[str] = set()
    for entry in registry_document.chapters:
        contract = entry.contract
        substantive = contract.substantive_content
        used_facts.update(item.fact_path for item in substantive.fact_requirements)
        used_claims.update(
            item.claim_type for item in substantive.claim_requirements
        )
        for rule in contract.conditional_applicability_rules:
            used_facts.update(rule.triggering_fact_paths)
            used_facts.update(rule.required_when_active_fact_paths)
            used_claims.update(rule.required_when_active_claim_types)
        for group in substantive.evidence_source_requirements:
            used_claims.update(group.admission_claim_types)
        for item in contract.ctq_items:
            used_facts.update(item.linked_fact_paths)
            used_claims.update(item.linked_claim_types)
    assert used_facts <= fact_vocabulary
    assert used_claims <= claim_vocabulary


def test_participant_terminology_across_batch4_files():
    for path in (
        [BATCH_PATH]
        + [
            CONTRACTS_DIR / f"{node_id}.json"
            for node_id in EXPECTED_CARRIERS
        ]
        + [SKILLS_DIR / f"{node_id}.json" for node_id in EXPECTED_CARRIERS]
    ):
        text = path.read_text(encoding="utf-8")
        assert FORBIDDEN_BATCH4_TERM not in text, path.name
        assert "试验参与者" in text, path.name


# ---------------------------------------------------------------------------
# Lint: partial batch is clean but incomplete; full mode fails on the rest.
# ---------------------------------------------------------------------------


def test_partial_lint_is_clean_but_never_complete(registry_document):
    report = lint_registry(REAL_TEMPLATE_DIR, registry_document, require_complete=False)
    assert report.mode == "partial"
    assert report.status == "incomplete"
    assert report.errors() == ()
    codes = {f.code for f in report.findings}
    assert "partial_mode_not_full_acceptance" in codes
    assert not codes & {
        "unknown_fact_path",
        "unknown_claim_type",
        "conditional_forbidden_conflict",
        "dangling_ctq_anchor",
        "coverage_role_mismatch",
        "unexpected_carrier",
        "skill_not_bound",
        "fixture_expectation_mismatch",
        "dangling_dependency",
    }
    assert report.coverage.covered_carrier_count == 16
    # Batch scope only: other batches' carriers must show up as missing and
    # their files must not leak into this slice.
    for node_id in ("v2_n_1_1", "v2_n_3_1_1", "v2_n_16_x1"):
        assert node_id in report.coverage.missing_node_ids, node_id
    assert len(report.fixture_results) == len(registry_document.fixtures)


def test_full_lint_fails_on_remaining_coverage(registry_document):
    report = lint_registry(REAL_TEMPLATE_DIR, registry_document, require_complete=True)
    assert report.mode == "full"
    assert report.status == "incomplete"
    missing = [f for f in report.errors() if f.code == "missing_coverage"]
    assert report.coverage.expected_carrier_count == 111  # 110 leaf union + cover
    assert len(missing) == report.coverage.expected_carrier_count - 16
    missing_ids = {f.node_id for f in missing}
    assert not missing_ids & set(EXPECTED_CARRIERS)
    assert {"v2_n_1_1", "v2_n_3_1_1", "v2_n_16_x1"} <= missing_ids


# ---------------------------------------------------------------------------
# Assembly CLI: read-only, stdout-only, and its output drives the lint CLI.
# ---------------------------------------------------------------------------


def _cli_env() -> dict:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "tests/protocol_v3:services/api:packages:.",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }


def test_assembly_cli_stdout_only_readonly_and_lint_cli_roundtrip(tmp_path):
    inputs = [CONTRACTS_DIR, SKILLS_DIR, BATCH_PATH.parent]
    before = {
        path: sorted((p.name, p.stat().st_size) for p in path.iterdir())
        for path in inputs
    }
    result = subprocess.run(
        [
            sys.executable,
            str(ASSEMBLY_SCRIPT),
            "--contracts-dir",
            str(CONTRACTS_DIR),
            "--skills-dir",
            str(SKILLS_DIR),
            "--batch",
            str(BATCH_PATH),
        ],
        cwd=str(REPO_ROOT),
        env=_cli_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    document = load_chapter_registry(payload)
    assert [entry.node_id for entry in document.chapters] == sorted(EXPECTED_CARRIERS)
    after = {
        path: sorted((p.name, p.stat().st_size) for p in path.iterdir())
        for path in inputs
    }
    assert before == after  # assembly performs no writes anywhere

    registry_file = tmp_path / "batch4_registry.json"
    registry_file.write_text(result.stdout, encoding="utf-8")
    lint_result = subprocess.run(
        [
            sys.executable,
            "scripts/qc/protocol_v3/lint_chapter_registry.py",
            "--registry",
            str(registry_file),
            "--template-dir",
            str(REAL_TEMPLATE_DIR),
            "--partial",
            "--check-fixtures",
        ],
        cwd=str(REPO_ROOT),
        env=_cli_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert lint_result.returncode == 0, lint_result.stdout + lint_result.stderr
    assert "mode: partial" in lint_result.stdout
    assert "INCOMPLETE" in lint_result.stdout
    assert "PASS" in lint_result.stdout  # exercised fixtures reported
