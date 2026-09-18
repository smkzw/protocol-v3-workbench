"""Task3R.3 batch5 tests: source-bound contracts for chapters 9–10.

Batch5 covers exactly the nineteen leaf carriers of section 9（研究评估与流程）
and section 10（不良事件和严重不良事件） of the accepted TP-MA-07 v2 candidate
registry: ``v2_n_9_1`` .. ``v2_n_9_4`` and ``v2_n_10_1_1`` .. ``v2_n_10_6``.
The parents ``v2_n_9``, ``v2_n_10``, ``v2_n_10_1``, ``v2_n_10_2`` and
``v2_n_10_3`` are NOT carriers: their body obligations are inherited into the
appropriate leaves with declared-addition markers, never dropped and never
turned into fabricated extra leaves.  The authored per-node contract/skill JSON
files are the single source of contract truth; ``batch5.json`` carries only the
closed fact/claim vocabularies, coverage roles and the executable fixture
payloads, and the assembly CLI joins them into an accepted
``ChapterRegistryDocument`` shape.

Red-first contract: these tests assert batch-scoped source obligations and were
observed failing before the artifacts existed.  They encode the batch5 content
spec (reviews/mw_protocol_v3_3r3_batch5_content_spec_20260906.md, sections 9–10
plus the parent-body inheritance rule from the coverage reconciliation) that the
batch exists to satisfy:

* efficacy endpoints stay traceable to the confirmed objectives and estimand
  (batch2 bindings are referenced, never duplicated into editable stores);
* assessment procedures carry units, reference ranges, windows, repeat rules
  and specimen handling, with the template laboratory panel example-only;
* PK/PD/E-R and immunogenicity stay separate conditional analyses with their
  own linked endpoints, samples, timing and analysis requirements;
* the IRC stays conditional, is not a safety committee and RECIST 1.1 stays an
  example rather than a universal adjudication method;
* AE definition, collection interval, TEAE derivation, severity, seriousness,
  causality, expectedness, recording and follow-up stay distinct typed facts;
* the severity scale version is project-bound (the template CTCAE example is
  example-only) and severity never substitutes for seriousness;
* the approved five-category causality terminology is preserved and a
  statistical ADR grouping never becomes the expedited reporting algorithm;
* investigator SAE reporting and sponsor SUSAR reporting keep separate
  recipients, objects and clocks, with no single clock copied into both;
* pregnancy stays neither automatic SAE nor automatic total withdrawal, with
  testing, prevention, exposure reporting, partner consent, outcomes and
  abnormal-outcome reporting as distinct obligations;
* parent chapter/area framing is carried by declared leaf inheritance.

A passing partial lint never represents full acceptance; medical judgment and
native-Word checks stay explicitly deferred.  Coverage truth is always the
template ``node_tree.json``; file presence in shared directories is asserted as
a superset only, and other batches' files never affect these tests.
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
    REPO_ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch5.json"
)
ASSEMBLY_SCRIPT = REPO_ROOT / "scripts/qc/protocol_v3/assemble_chapter_registry.py"

TEMPLATE_ID = "tp_ma_07_v2"
TEMPLATE_SHA256 = (
    "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
)
BATCH_SLUG = "fixture:batch5"

#: Sections 9–10 leaf carriers with their derived coverage roles.
EXPECTED_CARRIERS = {
    "v2_n_9_1": "heading_leaf",
    "v2_n_9_2": "heading_leaf",
    "v2_n_9_3": "heading_leaf",
    "v2_n_9_4": "heading_leaf",
    "v2_n_10_1_1": "heading_leaf",
    "v2_n_10_1_2": "heading_leaf",
    "v2_n_10_1_3": "heading_leaf",
    "v2_n_10_1_4": "heading_leaf",
    "v2_n_10_1_5": "heading_leaf",
    "v2_n_10_1_6": "heading_leaf",
    "v2_n_10_2_1": "heading_leaf",
    "v2_n_10_2_2": "heading_leaf",
    "v2_n_10_2_3": "heading_leaf",
    "v2_n_10_3_1": "heading_leaf",
    "v2_n_10_3_2": "heading_leaf",
    "v2_n_10_3_3": "heading_leaf",
    "v2_n_10_4": "heading_leaf",
    "v2_n_10_5": "heading_leaf",
    "v2_n_10_6": "heading_leaf",
}

#: The five parent nodes whose body/area obligations must be inherited into a
#: leaf carrier instead of becoming carriers themselves.
PARENT_NODES = ("v2_n_9", "v2_n_10", "v2_n_10_1", "v2_n_10_2", "v2_n_10_3")

#: The missing-genuine-obligation family chosen per node (the other missing
#: variant stays absent for that node).
MISSING_FAMILY = {
    "v2_n_9_1": "missing_claim",
    "v2_n_9_2": "missing_control",
    "v2_n_9_3": "missing_claim",
    "v2_n_9_4": "missing_claim",
    "v2_n_10_1_1": "missing_control",
    "v2_n_10_1_2": "missing_control",
    "v2_n_10_1_3": "missing_claim",
    "v2_n_10_1_4": "missing_control",
    "v2_n_10_1_5": "missing_control",
    "v2_n_10_1_6": "missing_claim",
    "v2_n_10_2_1": "missing_control",
    "v2_n_10_2_2": "missing_control",
    "v2_n_10_2_3": "missing_control",
    "v2_n_10_3_1": "missing_claim",
    "v2_n_10_3_2": "missing_control",
    "v2_n_10_3_3": "missing_control",
    "v2_n_10_4": "missing_control",
    "v2_n_10_5": "missing_control",
    "v2_n_10_6": "missing_control",
}

#: The named negative each node's canonical fixture exercises, and the exact
#: deterministic error code that proves it failed for its named reason.
NAMED_NEGATIVES = {
    "v2_n_9_1": ("missing_claim", "missing_required_claim"),
    "v2_n_9_2": ("missing_control", "missing_required_fact"),
    "v2_n_9_3": ("missing_claim", "missing_required_claim"),
    "v2_n_9_4": ("missing_claim", "missing_required_claim"),
    "v2_n_10_1_1": ("missing_control", "missing_required_fact"),
    "v2_n_10_1_2": ("missing_control", "missing_required_fact"),
    "v2_n_10_1_3": ("missing_claim", "missing_required_claim"),
    "v2_n_10_1_4": ("missing_control", "missing_required_fact"),
    "v2_n_10_1_5": ("missing_control", "missing_required_fact"),
    "v2_n_10_1_6": ("missing_claim", "missing_required_claim"),
    "v2_n_10_2_1": ("missing_control", "missing_required_fact"),
    "v2_n_10_2_2": ("missing_control", "missing_required_fact"),
    "v2_n_10_2_3": ("missing_control", "missing_required_fact"),
    "v2_n_10_3_1": ("missing_claim", "missing_required_claim"),
    "v2_n_10_3_2": ("wrong_source", "wrong_source_role"),
    "v2_n_10_3_3": ("missing_control", "missing_required_fact"),
    "v2_n_10_4": ("missing_control", "missing_required_fact"),
    "v2_n_10_5": ("missing_control", "missing_required_fact"),
    "v2_n_10_6": ("missing_control", "missing_required_fact"),
}

#: Nodes whose NAMED negative is not the missing family; their canonical
#: missing-family fixture must still fail for its own intended reason.
MISSING_FAMILY_CODES = {
    "v2_n_10_3_2": "missing_required_fact",
}

#: Source-specific negatives required by the batch5 content spec: each fixture
#: proves one named failure reason, never a generic identity error.
SOURCE_SPECIFIC_NEGATIVES = {
    "v2_n_9_1": (
        ("endpoint-not-traceable", "missing_required_fact"),
        ("instrument-version-missing", "missing_required_fact"),
    ),
    "v2_n_9_2": (
        ("lab-value-without-units", "missing_required_cell"),
        ("blanket-restriction-no-rationale", "forbidden_claim_present"),
        ("specimen-volume-or-purpose-missing", "missing_required_fact"),
        ("comparator-evidence-for-own-safety", "wrong_source_role"),
        ("empty-monitoring-schedule", "missing_structural_object"),
    ),
    "v2_n_9_3": (
        ("pk-endpoint-unlinked", "missing_required_fact"),
        ("population-pk-schedule-missing", "missing_required_fact"),
    ),
    "v2_n_9_4": (("irc-conflated-with-safety-committee", "forbidden_claim_present"),),
    "v2_n_10_1_1": (
        ("copied-oncology-exception", "forbidden_fact_present"),
        ("parent-safety-framing-dropped", "missing_required_fact"),
    ),
    "v2_n_10_1_2": (
        ("ctcae-version-from-template", "forbidden_fact_present"),
        ("severity-seriousness-conflated", "forbidden_claim_present"),
        ("wrong-scale-version", "missing_required_fact"),
        ("empty-severity-table", "missing_required_cell"),
    ),
    "v2_n_10_1_3": (
        ("causality-collapsed-binary", "forbidden_claim_present"),
        ("adr-mapping-reused-for-expedited", "forbidden_claim_present"),
    ),
    "v2_n_10_1_4": (
        ("ae-collection-equals-teaee", "forbidden_claim_present"),
        ("template-period-cutoffs-copied", "forbidden_fact_present"),
    ),
    "v2_n_10_1_5": (("report-time-by-convenience", "forbidden_claim_present"),),
    "v2_n_10_1_6": (("label-only-event-record", "forbidden_claim_present"),),
    "v2_n_10_2_1": (
        ("sae-from-severity-alone", "forbidden_claim_present"),
        ("empty-seriousness-criteria-table", "missing_required_cell"),
    ),
    "v2_n_10_2_2": (("signed-form-delays-report", "forbidden_fact_present"),),
    "v2_n_10_2_3": (),
    "v2_n_10_3_1": (("susr-equals-sae", "forbidden_claim_present"),),
    "v2_n_10_3_2": (
        ("reporting-clock-copied", "forbidden_claim_present"),
        ("adr-mapping-reused-for-expedited-reporting", "forbidden_claim_present"),
    ),
    "v2_n_10_3_3": (("causality-disagreement-dismissed", "forbidden_claim_present"),),
    "v2_n_10_4": (("invented-clinical-receipt", "forbidden_claim_present"),),
    "v2_n_10_5": (("aesi-from-template-list", "forbidden_fact_present"),),
    "v2_n_10_6": (
        ("pregnancy-auto-sae", "forbidden_claim_present"),
        ("pregnancy-auto-withdrawal", "forbidden_claim_present"),
    ),
}

#: Conditional-branch positives that exercise the nodes whose obligations are
#: conditional on project facts (IRC / oncology progression / immunogenicity).
CONDITIONAL_BRANCH_POSITIVES = (
    "fixture:batch5:v2-n-9-3:positive-immunogenicity",
    "fixture:batch5:v2-n-9-4:positive-applicable",
    "fixture:batch5:v2-n-10-1-1:positive-oncology-progression",
)

#: Table contracts that declare stable required cell selectors; every positive
#: fixture must carry non-blank values for each declared cell.
CELL_OBLIGATION_CONTRACTS = {
    "v2_n_9_1": (
        "efficacy:cell:objective",
        "efficacy:cell:endpoint",
        "efficacy:cell:estimand",
    ),
    "v2_n_9_2": (
        "safety:cell:parameter",
        "safety:cell:unit",
        "safety:cell:reference_range",
        "safety:cell:window",
    ),
    "v2_n_10_1_2": (
        "ae:cell:grade",
        "ae:cell:severity_definition",
        "ae:cell:scale_version",
    ),
    "v2_n_10_1_3": (
        "causality:cell:level",
        "causality:cell:definition",
        "causality:cell:basis",
    ),
    "v2_n_10_2_1": (
        "sae:cell:criterion",
        "sae:cell:definition",
        "sae:cell:version_binding",
    ),
    "v2_n_10_3_2": (
        "susar:cell:recipient",
        "susar:cell:clock",
        "susar:cell:information_source",
    ),
    "v2_n_10_5": (
        "aesi:cell:event",
        "aesi:cell:threshold",
        "aesi:cell:monitoring_action",
    ),
    "v2_n_10_6": (
        "pregnancy:cell:test",
        "pregnancy:cell:timing",
        "pregnancy:cell:population",
    ),
}

#: Individually required claims must get their own evidence floor groups
#: (ANY-of inside one group; every group carries a context window + quality
#: floor).  Single-group nodes are not listed here but are still asserted to
#: declare a context window and quality floor everywhere.
EVIDENCE_GROUP_ADMISSIONS = {
    "v2_n_9_1": [{"efficacy_endpoint_definition"}, {"endpoint_objective_estimand_traceability"}],
    "v2_n_9_2": [{"safety_assessment_plan"}, {"specimen_handling_statement"}],
    "v2_n_9_3": [{"population_pk_analysis"}, {"exposure_response_analysis"}],
    "v2_n_10_1_1": [{"ae_definition"}, {"teaee_derivation"}],
    "v2_n_10_1_2": [{"ae_severity_grading"}, {"severity_scale_standard"}],
    "v2_n_10_1_3": [
        {"causality_five_level_assessment"},
        {"causality_reportability_algorithm"},
    ],
    "v2_n_10_2_1": [{"sae_definition"}, {"sae_seriousness_criteria_statement"}],
    "v2_n_10_2_2": [{"investigator_sae_reporting"}, {"investigator_reporting_standard"}],
    "v2_n_10_3_1": [{"susar_definition"}, {"susar_reportability_criteria"}],
    "v2_n_10_3_2": [{"sponsor_expedited_reporting"}, {"sponsor_reporting_standard"}],
    "v2_n_10_5": [{"aesi_definition"}, {"aesi_reporting_plan"}],
}

#: Exact source body-child window each carrier is bound to (zero-based
#: body-child indexes, matching the template node_tree extraction).
SOURCE_WINDOWS = {
    "v2_n_9_1": (549, 563),
    "v2_n_9_2": (565, 581),
    "v2_n_9_3": (583, 585),
    "v2_n_9_4": (586, 589),
    "v2_n_10_1_1": (596, 599),
    "v2_n_10_1_2": (601, 607),
    "v2_n_10_1_3": (608, 649),
    "v2_n_10_1_4": (650, 661),
    "v2_n_10_1_5": (663, 700),
    "v2_n_10_1_6": (702, 704),
    "v2_n_10_2_1": (708, 710),
    "v2_n_10_2_2": (712, 716),
    "v2_n_10_2_3": (717, 718),
    "v2_n_10_3_1": (721, 722),
    "v2_n_10_3_2": (723, 729),
    "v2_n_10_3_3": (730, 731),
    "v2_n_10_4": (732, 738),
    "v2_n_10_5": (739, 747),
    "v2_n_10_6": (748, 751),
}

#: Parent-body inheritance carriers: node id -> the parent node whose body or
#: area text is inherited, plus the fact path that carries it.
INHERITED_PARENT_BODY = {
    "v2_n_9_1": ("v2_n_9", "evaluation.framework_scope"),
    "v2_n_10_1_1": ("v2_n_10", "ae.chapter_scope_framing"),
    "v2_n_10_3_1": ("v2_n_10_3", "susar.chapter_area_framing"),
}

FORBIDDEN_BATCH5_TERM = "受试者"


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


def _optional_facts(contract: ChapterContractV2) -> set[str]:
    return {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "optional"
    }


def _forbidden_facts(contract: ChapterContractV2) -> set[str]:
    return {
        item.fact_path
        for item in contract.substantive_content.fact_requirements
        if item.obligation.value == "forbidden"
    }


def _required_claims(contract: ChapterContractV2) -> set[str]:
    return {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "required"
    }


def _forbidden_claims(contract: ChapterContractV2) -> set[str]:
    return {
        item.claim_type
        for item in contract.substantive_content.claim_requirements
        if item.obligation.value == "forbidden"
    }


def _qc_text(contract: ChapterContractV2) -> str:
    return " ".join(rule.rule for rule in contract.positive_qc_rules)


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
    matches = [
        fixture
        for fixture in document.fixtures
        if fixture.chapter_contract_id == contract_id
        and fixture.fixture_id.endswith(f":{suffix}")
    ]
    assert len(matches) == 1, (node_id, suffix, [f.fixture_id for f in matches])
    return matches[0]


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
    # concurrently; the selected-batch exactly-19 guarantee is asserted by the
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
        assert contract.chapter_skill_version == contract.contract_version
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
        # Provenance binds the accepted template identity and the exact source
        # window this carrier is derived from.
        first, last = SOURCE_WINDOWS[stem]
        provenance = "\n".join(skill["provenance_requirements"])
        assert TEMPLATE_SHA256 in provenance, stem
        assert str(first) in provenance and str(last) in provenance, stem
        assert "batch5" in provenance, stem


def test_all_nineteen_carriers_present_with_derived_coverage_roles(registry_document):
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
    # No fabricated extra leaves and no parent carrier: the body obligations of
    # the parents are inherited into leaves, not authored as new carriers.
    assert not set(PARENT_NODES) & set(entries)
    for node_id, role in EXPECTED_CARRIERS.items():
        assert entries[node_id].coverage_role == role, node_id
        assert node_id in heading_leaves and node_id in outline_leaves, node_id


def test_contracts_bind_the_exact_source_body_child_windows():
    """Every carrier is derived from the template extraction window it claims;
    binding is checked against node_tree.json, never invented offsets.

    ``v2_n_10_1_4`` is the one batch5 carrier whose first content paragraph is
    two body children after its heading: body child 651 belongs to no node and
    no table (a non-content element excluded by the accepted extraction), so
    the window start stays the heading index at 650."""
    node_tree = json.loads(
        (REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8")
    )
    heading = {n["id"]: n for n in node_tree["heading_style_tree"]["nodes"]}
    claimed_body_children = set()
    for node in node_tree["heading_style_tree"]["nodes"]:
        claimed_body_children.add(node["body_child_index"])
        claimed_body_children.update(node.get("content_paragraph_indexes") or [])
    for table in node_tree.get("tables") or []:
        claimed_body_children.add(table["body_child_index"])
    assert 651 not in claimed_body_children
    for node_id, (first, last) in SOURCE_WINDOWS.items():
        node = heading[node_id]
        assert node["body_child_index"] == first, node_id
        indexes = node["content_paragraph_indexes"]
        assert indexes and max(indexes) == last, node_id
        assert last > first
        gap = min(indexes) - first
        if node_id == "v2_n_10_1_4":
            assert gap == 2, node_id
        else:
            assert gap == 1, node_id


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
# Fixture families: four per node minimum, all nineteen nodes, every negative
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
        named = _fixture(
            registry_document, node_id, expected_kind.replace("_", "-")
        )
        named_result = check_fixture(registry_document, named)
        assert named_result.passed is False, node_id
        assert expected_code in _error_codes(named_result), node_id
        if node_id in MISSING_FAMILY_CODES:
            missing = _fixture(
                registry_document,
                node_id,
                MISSING_FAMILY[node_id].replace("_", "-"),
            )
            missing_result = check_fixture(registry_document, missing)
            assert missing_result.passed is False, node_id
            assert MISSING_FAMILY_CODES[node_id] in _error_codes(missing_result), node_id
        wrong = _fixture(registry_document, node_id, "wrong-source")
        assert "wrong_source_role" in _error_codes(
            check_fixture(registry_document, wrong)
        ), node_id
        skeleton = _fixture(registry_document, node_id, "skeleton")
        assert "skeleton_content" in _error_codes(
            check_fixture(registry_document, skeleton)
        ), node_id
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
    # 19 nodes x at least 4 families; the spec's source-specific negatives push
    # the authored total above the four-per-node floor of 76.
    assert total >= 76
    assert total == len(registry_document.fixtures)


def test_source_specific_negatives_fail_for_their_named_reason(registry_document):
    """Each spec-required negative exists and its deterministic failure is the
    reason it exists for, not an unrelated identity error."""
    for node_id, pairs in SOURCE_SPECIFIC_NEGATIVES.items():
        for suffix, expected_code in pairs:
            fixture = _fixture(registry_document, node_id, suffix)
            result = check_fixture(registry_document, fixture)
            assert result.passed is False, (node_id, suffix)
            assert expected_code in _error_codes(result), (node_id, suffix)
            assert fixture.fixture_kind != "positive", (node_id, suffix)


def test_conditional_branch_positives_pass(registry_document):
    """IRC / oncology-progression / immunogenicity obligations are conditional:
    the active branch is exercised by a positive fixture, never asserted as
    universally present."""
    ids = {fixture.fixture_id for fixture in registry_document.fixtures}
    assert set(CONDITIONAL_BRANCH_POSITIVES) <= ids
    for fixture_id in CONDITIONAL_BRANCH_POSITIVES:
        fixture = next(f for f in registry_document.fixtures if f.fixture_id == fixture_id)
        result = check_fixture(registry_document, fixture)
        assert result.passed is True, fixture_id
        assert not _error_codes(result)


def test_negative_fixtures_carry_no_identity_or_clinical_errors(registry_document):
    """A negative fixture must fail because of empty/unsupported/forbidden
    material it is named for, never because it accidentally supplies an
    unrelated identity error.  The only exception is the set of fixtures whose
    named defect *is* forbidden material (a copied template example, a
    collapsed taxonomy, an invented receipt)."""
    allowed_forbidden = {
        f"{BATCH_SLUG}:{node_id.replace('_', '-')}:{suffix}"
        for node_id, pairs in SOURCE_SPECIFIC_NEGATIVES.items()
        for suffix, code in pairs
        if code.startswith("forbidden")
    }
    assert allowed_forbidden
    forbidden_codes = {"forbidden_fact_present", "forbidden_claim_present"}
    for fixture in registry_document.fixtures:
        if fixture.fixture_kind == "positive":
            continue
        result = check_fixture(registry_document, fixture)
        assert result.passed is False, fixture.fixture_id
        if fixture.fixture_id in allowed_forbidden:
            # The named defect is forbidden material; the fixture must fail for
            # that reason (plus the omitted obligation it also carries) and must
            # not trip an unrelated source/identity error.
            codes = _error_codes(result)
            assert codes & forbidden_codes, fixture.fixture_id
            assert codes <= forbidden_codes | {
                "missing_required_fact",
                "missing_required_claim",
                "missing_structural_object",
                "missing_required_cell",
            }, (fixture.fixture_id, sorted(codes))
            continue
        assert not (_error_codes(result) & forbidden_codes), fixture.fixture_id


def test_synthetic_examples_are_conspicuous_and_booleans_bare(registry_document):
    """Boolean trigger facts are bare true/false; synthetic fixture values are
    visibly marked and never presented as project facts or approvals."""
    for node_id in EXPECTED_CARRIERS:
        for path in (
            CONTRACTS_DIR / f"{node_id}.json",
            SKILLS_DIR / f"{node_id}.json",
        ):
            text = path.read_text(encoding="utf-8")
            assert "合成" in text or "示例" in text, path.name
    for fixture in registry_document.fixtures:
        for fact in fixture.content.facts:
            if fact.fact_path.endswith("_applicable") or fact.fact_path.endswith(
                ".applicable"
            ):
                assert fact.value in {"true", "false"}, (
                    fixture.fixture_id,
                    fact.fact_path,
                    fact.value,
                )
            else:
                assert "【合成夹具】" in (fact.value or ""), (
                    fixture.fixture_id,
                    fact.fact_path,
                )
    for fixture in registry_document.fixtures:
        for evidence in fixture.content.evidence:
            assert "合成" in evidence.locator, fixture.fixture_id


def test_fixture_ids_follow_the_batch_hyphen_convention(registry_document):
    ids = {fixture.fixture_id for fixture in registry_document.fixtures}
    for node_id in EXPECTED_CARRIERS:
        slug = node_id.replace("_", "-")
        assert f"{BATCH_SLUG}:{slug}:positive" in ids, node_id
        assert f"{BATCH_SLUG}:{slug}:wrong-source" in ids, node_id
        assert f"{BATCH_SLUG}:{slug}:skeleton" in ids, node_id
        assert (
            f"{BATCH_SLUG}:{slug}:{MISSING_FAMILY[node_id].replace('_', '-')}" in ids
        ), node_id
    assert all(identifier.startswith(f"{BATCH_SLUG}:") for identifier in ids)


def test_forbidden_and_conditional_obligations_are_substantive(registry_document):
    """Every contract carries positive obligations plus real forbidden and
    (where declared) conditional semantics; no title-plus-one-fact shells."""
    for entry in registry_document.chapters:
        substantive = entry.contract.substantive_content
        required_facts = [
            f for f in substantive.fact_requirements if f.obligation.value == "required"
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
        assert required_facts, entry.node_id
        assert forbidden, entry.node_id
        assert substantive.skeleton_risk_rules
        assert entry.contract.positive_qc_rules
        assert entry.contract.ctq_items
        assert substantive.evidence_source_requirements, entry.node_id
        assert substantive.project_specific_elements, entry.node_id


def test_closed_vocabularies_cover_every_declared_path_and_claim(registry_document):
    fact_vocabulary = set(registry_document.fact_vocabulary)
    claim_vocabulary = set(registry_document.claim_vocabulary)
    used_facts: set[str] = set()
    used_claims: set[str] = set()
    for entry in registry_document.chapters:
        contract = entry.contract
        substantive = contract.substantive_content
        used_facts.update(item.fact_path for item in substantive.fact_requirements)
        used_claims.update(item.claim_type for item in substantive.claim_requirements)
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


def test_every_contract_declares_context_window_and_quality_floor(registry_document):
    for entry in registry_document.chapters:
        groups = entry.contract.substantive_content.evidence_source_requirements
        assert groups, entry.node_id
        for group in groups:
            assert group.require_context_window is True, entry.node_id
            assert group.minimum_quality_score >= 0.9, entry.node_id
            assert group.allowed_locator_kinds, entry.node_id
            assert group.source_roles, entry.node_id


def test_independently_required_claims_have_separate_evidence_groups():
    for node_id, wanted in EVIDENCE_GROUP_ADMISSIONS.items():
        contract = _contract(node_id)
        admissions = [
            set(group.admission_claim_types)
            for group in contract.substantive_content.evidence_source_requirements
        ]
        assert admissions == wanted, node_id
        # Each admitted claim is a declared required claim of the same contract.
        required = _required_claims(contract)
        for group in wanted:
            assert group <= required, node_id


def test_participant_terminology_across_batch5_files():
    for path in (
        [BATCH_PATH]
        + [CONTRACTS_DIR / f"{node_id}.json" for node_id in EXPECTED_CARRIERS]
        + [SKILLS_DIR / f"{node_id}.json" for node_id in EXPECTED_CARRIERS]
    ):
        text = path.read_text(encoding="utf-8")
        assert FORBIDDEN_BATCH5_TERM not in text, path.name
        assert "试验参与者" in text, path.name


# ---------------------------------------------------------------------------
# Chapter 9: assessment obligations.
# ---------------------------------------------------------------------------


def test_efficacy_endpoints_trace_to_objectives_and_estimand(registry_document):
    contract = _contract("v2_n_9_1")
    required = _required_facts(contract)
    # Batch2's confirmed objective/endpoint bindings are referenced, not
    # duplicated into a second editable store.
    assert {"picos.primary_endpoint", "picos.primary_objectives"} <= required
    assert {
        "efficacy.primary_endpoint_measurement",
        "efficacy.primary_estimand_link",
        "efficacy.assessment_instrument_or_scale",
        "efficacy.evaluator_role_and_training",
        "efficacy.assessment_timing_reference",
    } <= required
    assert {
        "efficacy_endpoint_definition",
        "endpoint_objective_estimand_traceability",
    } <= _required_claims(contract)
    assert "untraceable_endpoint" in _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "估计目标" in qc_text and "不得" in qc_text and "SoA" in qc_text
    untraceable = check_fixture(
        registry_document, _fixture(registry_document, "v2_n_9_1", "endpoint-not-traceable")
    )
    assert "missing_required_fact" in _error_codes(untraceable)
    missing_scale = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_9_1", "instrument-version-missing"),
    )
    assert "missing_required_fact" in _error_codes(missing_scale)


def test_assessment_procedures_carry_units_windows_and_repeat_rules(registry_document):
    contract = _contract("v2_n_9_2")
    required = _required_facts(contract)
    assert {
        "safety.monitoring_assessments",
        "safety.lab_panel_definition",
        "safety.lab_units_and_reference_ranges",
        "safety.assessment_windows",
        "safety.repeat_confirmation_rules",
        "safety.monitoring_schedule",
    } <= required
    assert "safety.template_example_lab_panel" in _forbidden_facts(contract)
    qc_text = _qc_text(contract)
    assert "单位" in qc_text and "参考范围" in qc_text and "SoA" in qc_text
    no_units = check_fixture(
        registry_document, _fixture(registry_document, "v2_n_9_2", "lab-value-without-units")
    )
    assert "missing_required_cell" in _error_codes(no_units)
    empty_schedule = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_9_2", "empty-monitoring-schedule"),
    )
    assert "missing_structural_object" in _error_codes(empty_schedule)


def test_restrictions_are_typed_with_design_rationale_not_blanket(registry_document):
    contract = _contract("v2_n_9_2")
    assert "safety.assessment_restrictions" in _required_facts(contract)
    assert "blanket_restriction_without_rationale" in _forbidden_claims(contract)
    assert "依据" in _qc_text(contract)
    blanket = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_9_2", "blanket-restriction-no-rationale"),
    )
    assert "forbidden_claim_present" in _error_codes(blanket)


def test_specimens_special_assays_and_comparator_evidence_are_bounded(registry_document):
    contract = _contract("v2_n_9_2")
    required = _required_facts(contract)
    assert {
        "safety.specimen_types_and_handling",
        "safety.special_assay_purposes",
        "safety.future_use_specimen_distinction",
    } <= required
    assert "comparator_evidence_equals_own_product" in _forbidden_claims(contract)
    assert "竞品" in _qc_text(contract)
    specimen_gap = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_9_2", "specimen-volume-or-purpose-missing"),
    )
    assert "missing_required_fact" in _error_codes(specimen_gap)
    comparator = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_9_2", "comparator-evidence-for-own-safety"),
    )
    codes = _error_codes(comparator)
    assert "wrong_source_role" in codes
    assert "forbidden_claim_present" not in codes


def test_pk_pd_exposure_response_and_immunogenicity_stay_separate(registry_document):
    contract = _contract("v2_n_9_3")
    required = _required_facts(contract)
    # Batch2 exploratory paths are reused where the meaning matches.
    assert {"exploratory.population_pk", "exploratory.exposure_response"} <= required
    assert {
        "pk.pd_analysis_requirements",
        "pk.linked_endpoints",
        "pk.sampling_schedule",
    } <= required
    assert "exploratory.immunogenicity" in _optional_facts(contract)
    assert "exploratory.immunogenicity_applicable" in _required_facts(contract)
    assert "pk_pd_endpoint_unlinked" in _forbidden_claims(contract)
    rule = next(
        r
        for r in contract.conditional_applicability_rules
        if r.conditional_applicability_rule_id == "applicability:n-9-3:immunogenicity"
    )
    assert rule.triggering_fact_paths == ("exploratory.immunogenicity_applicable",)
    assert "exploratory.immunogenicity" in rule.required_when_active_fact_paths
    assert "immunogenicity_strategy" in rule.required_when_active_claim_types
    qc_text = _qc_text(contract)
    assert "免疫原性" in qc_text and "独立" in qc_text
    unlinked = check_fixture(
        registry_document, _fixture(registry_document, "v2_n_9_3", "pk-endpoint-unlinked")
    )
    assert "missing_required_fact" in _error_codes(unlinked)
    no_schedule = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_9_3", "population-pk-schedule-missing"),
    )
    assert "missing_required_fact" in _error_codes(no_schedule)


def test_irc_is_conditional_and_not_a_safety_committee(registry_document):
    contract = _contract("v2_n_9_4")
    assert "irc.applicable" in _required_facts(contract)
    rule = next(
        r
        for r in contract.conditional_applicability_rules
        if r.conditional_applicability_rule_id == "applicability:n-9-4:irc"
    )
    assert rule.triggering_fact_paths == ("irc.applicable",)
    assert {
        "irc.charter_and_independence",
        "irc.review_scope_endpoints",
        "irc.adjudication_method_and_instrument",
        "irc.roles_and_conflict_management",
    } <= set(rule.required_when_active_fact_paths)
    assert "irc.template_example_adjudication" in _forbidden_facts(contract)
    assert {
        "irc_equals_safety_committee",
        "recist_universal_method",
    } <= _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "条件" in qc_text and "安全性" in qc_text and "RECIST" in qc_text
    conflated = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_9_4", "irc-conflated-with-safety-committee"),
    )
    assert "forbidden_claim_present" in _error_codes(conflated)
    active = next(
        f
        for f in registry_document.fixtures
        if f.fixture_id == "fixture:batch5:v2-n-9-4:positive-applicable"
    )
    values = {fact.fact_path: fact.value for fact in active.content.facts}
    assert values.get("irc.applicable") == "true"
    assert {
        "irc.charter_and_independence",
        "irc.review_scope_endpoints",
        "irc.adjudication_method_and_instrument",
        "irc.roles_and_conflict_management",
    } <= set(values)


# ---------------------------------------------------------------------------
# Chapter 10: AE/SAE/SUSAR taxonomy, causality, reporting and pregnancy.
# ---------------------------------------------------------------------------


def test_ae_sae_teae_taxonomy_fields_are_distinct_typed_facts(registry_document):
    definition = _contract("v2_n_10_1_1")
    assert {
        "ae.definition",
        "ae.temporal_window_definition",
        "ae.teaee_derivation",
        "ae.pre_existing_condition_handling",
        "ae.ae_term_binding",
    } <= _required_facts(definition)
    assert {"ae_definition", "teaee_derivation"} <= _required_claims(definition)
    assert "ae_equals_teaee" in _forbidden_claims(definition)
    severity = _contract("v2_n_10_1_2")
    assert {
        "ae.severity_scale_version",
        "ae.severity_grading_definition",
        "ae.severity_seriousness_distinctness",
    } <= _required_facts(severity)
    serious = _contract("v2_n_10_2_1")
    assert {
        "sae.definition",
        "sae.seriousness_criteria",
        "sae.seriousness_criteria_version_binding",
        "sae.severity_seriousness_distinctness",
    } <= _required_facts(serious)
    assert {
        "seriousness_equals_severity",
        "sae_classified_from_severity",
    } <= _forbidden_claims(serious)
    # Severity never substitutes for seriousness: the AE definition node does
    # not declare the seriousness criteria fact, and the SAE node does not
    # declare the severity scale fact.
    assert "sae.seriousness_criteria" not in _required_facts(definition)
    assert "ae.severity_scale_version" not in _required_facts(serious)


def test_ctcae_version_is_project_bound_and_template_example_forbidden(registry_document):
    contract = _contract("v2_n_10_1_2")
    assert "ae.severity_scale_version" in _required_facts(contract)
    assert "ae.template_example_ctcae_version" in _forbidden_facts(contract)
    assert "severity_equals_seriousness" in _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "CTCAE" in qc_text and "项目" in qc_text and "不得" in qc_text
    positive = _fixture(registry_document, "v2_n_10_1_2", "positive")
    values = {fact.fact_path: fact.value for fact in positive.content.facts}
    assert "项目已确认绑定" in (values.get("ae.severity_scale_version") or "")
    assert "ae.template_example_ctcae_version" not in values
    hardcoded = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_2", "ctcae-version-from-template"),
    )
    assert "forbidden_fact_present" in _error_codes(hardcoded)
    collapsed = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_2", "severity-seriousness-conflated"),
    )
    assert "forbidden_claim_present" in _error_codes(collapsed)
    unbound = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_2", "wrong-scale-version"),
    )
    assert "missing_required_fact" in _error_codes(unbound)


def test_five_level_causality_preserved_and_reportability_kept_separate(registry_document):
    contract = _contract("v2_n_10_1_3")
    required = _required_facts(contract)
    assert {
        "causality.five_level_terminology",
        "causality.judgment_method",
        "causality.reportability_algorithm",
        "causality.current_authority_basis",
    } <= required
    assert {
        "causality_collapsed_to_binary",
        "adr_mapping_equals_expedited_reporting",
    } <= _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "五分法" in qc_text and "不得" in qc_text and "草案" in qc_text
    binary = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_3", "causality-collapsed-binary"),
    )
    assert "forbidden_claim_present" in _error_codes(binary)
    adr = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_3", "adr-mapping-reused-for-expedited"),
    )
    assert "forbidden_claim_present" in _error_codes(adr)
    # The five-category table cells are exercised with the five levels present.
    positive = _fixture(registry_document, "v2_n_10_1_3", "positive")
    text = " ".join(
        (cell.value or "")
        for obj in positive.content.objects
        for cell in obj.cells
    ) + " ".join(fact.value or "" for fact in positive.content.facts)
    for level in ("肯定有关", "很可能有关", "可能有关", "可能无关", "肯定无关"):
        assert level in text, level


def test_ae_collection_is_not_teaee_classification(registry_document):
    contract = _contract("v2_n_10_1_4")
    assert {
        "ae.collection_period_definition",
        "ae.collection_period_start_reference",
        "ae.consent_history_distinction",
        "ae.collection_stop_reference",
        "ae.ae_collection_not_teaee_classification",
    } <= _required_facts(contract)
    assert "ae.template_example_period_cutoffs" in _forbidden_facts(contract)
    assert "ae_collection_equals_teaee_classification" in _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "收集" in qc_text and "示例" in qc_text
    merged = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_4", "ae-collection-equals-teaee"),
    )
    assert "forbidden_claim_present" in _error_codes(merged)
    copied = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_4", "template-period-cutoffs-copied"),
    )
    assert "forbidden_fact_present" in _error_codes(copied)


def test_ae_recording_keeps_separate_event_times(registry_document):
    contract = _contract("v2_n_10_1_5")
    assert {
        "ae.recording_requirements",
        "ae.separate_times",
        "ae.report_time_selection_rule",
        "ae.terminology_boundary",
    } <= _required_facts(contract)
    assert "ae.template_example_report_time" in _forbidden_facts(contract)
    assert "ae_date_selected_for_convenience" in _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "获知" in qc_text and "报告时间" in qc_text
    convenience = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_5", "report-time-by-convenience"),
    )
    assert "forbidden_claim_present" in _error_codes(convenience)


def test_ae_followup_needs_real_scope_and_ongoing_event_handling(registry_document):
    contract = _contract("v2_n_10_1_6")
    assert {
        "ae.followup_scope",
        "ae.followup_duration_or_end",
        "ae.ongoing_event_handling",
    } <= _required_facts(contract)
    assert "label_only_event_record" in _forbidden_claims(contract)
    assert "标签" in _qc_text(contract)
    label_only = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_6", "label-only-event-record"),
    )
    assert "forbidden_claim_present" in _error_codes(label_only)


def test_sae_seriousness_is_separate_from_severity_and_from_definition(registry_document):
    contract = _contract("v2_n_10_2_1")
    assert {
        "sae.definition",
        "sae.seriousness_criteria",
        "sae.seriousness_criteria_version_binding",
    } <= _required_facts(contract)
    assert {
        "sae_definition",
        "sae_seriousness_criteria_statement",
    } <= _required_claims(contract)
    qc_text = _qc_text(contract)
    assert "严重性" in qc_text and "严重程度" in qc_text
    from_severity = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_2_1", "sae-from-severity-alone"),
    )
    assert "forbidden_claim_present" in _error_codes(from_severity)


def test_investigator_sae_reporting_clock_is_its_own_object(registry_document):
    contract = _contract("v2_n_10_2_2")
    required = _required_facts(contract)
    assert {
        "sae_reporting.investigator_recipient",
        "sae_reporting.investigator_clock",
        "sae_reporting.first_awareness_reference",
        "sae_reporting.investigator_record",
    } <= required
    assert not {path for path in required if path.startswith("susar_reporting.")}
    assert "sae_reporting.template_example_signed_form_day_zero" in _forbidden_facts(
        contract
    )
    assert {
        "signed_form_delays_reporting",
        "single_clock_for_all_reporters",
    } <= _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "首次获知" in qc_text and "签署" in qc_text
    signed = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_2_2", "signed-form-delays-report"),
    )
    assert "forbidden_fact_present" in _error_codes(signed)
    # The investigator clock object is distinct from the sponsor clock object:
    # they are declared on different nodes with different fact paths.
    sponsor = _contract("v2_n_10_3_2")
    assert "susar_reporting.sponsor_clock" in _required_facts(sponsor)
    assert "sae_reporting.investigator_clock" not in _required_facts(sponsor)
    investigator_value = {
        fact.fact_path: fact.value
        for fact in _fixture(registry_document, "v2_n_10_2_2", "positive").content.facts
    }["sae_reporting.investigator_clock"]
    sponsor_value = {
        fact.fact_path: fact.value
        for fact in _fixture(registry_document, "v2_n_10_3_2", "positive").content.facts
    }["susar_reporting.sponsor_clock"]
    assert investigator_value != sponsor_value


def test_sae_followup_declares_new_information_reporting(registry_document):
    contract = _contract("v2_n_10_2_3")
    assert {
        "sae_followup.scope",
        "sae_followup.new_information_reporting",
        "sae_followup.outcome_documentation",
    } <= _required_facts(contract)
    assert "新信息" in _qc_text(contract)


def test_susr_is_not_sae_and_expectedness_is_typed(registry_document):
    contract = _contract("v2_n_10_3_1")
    assert {
        "susar.definition",
        "susar.expectedness_reference",
        "susar.reportability_criteria",
    } <= _required_facts(contract)
    assert {
        "susar_equals_sae",
        "expectedness_equals_causality",
    } <= _forbidden_claims(contract)
    assert "可疑" in _qc_text(contract)
    equal = check_fixture(
        registry_document, _fixture(registry_document, "v2_n_10_3_1", "susr-equals-sae")
    )
    assert "forbidden_claim_present" in _error_codes(equal)


def test_sponsor_expedited_reporting_clocks_are_separate(registry_document):
    contract = _contract("v2_n_10_3_2")
    required = _required_facts(contract)
    assert {
        "susar_reporting.sponsor_recipient",
        "susar_reporting.sponsor_clock",
        "susar_reporting.sponsor_followup_clock",
        "susar_reporting.authority_and_ethics_communications",
        "susar_reporting.awareness_reference",
    } <= required
    assert not {path for path in required if path.startswith("sae_reporting.")}
    assert "susar_reporting.template_example_signed_report_day_zero" in _forbidden_facts(
        contract
    )
    assert {
        "investigator_clock_reused_for_sponsor",
        "adr_mapping_used_for_expedited_reporting",
    } <= _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "申办者" in qc_text and "研究者" in qc_text
    copied = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_3_2", "reporting-clock-copied"),
    )
    assert "forbidden_claim_present" in _error_codes(copied)
    adr = check_fixture(
        registry_document,
        _fixture(
            registry_document, "v2_n_10_3_2", "adr-mapping-reused-for-expedited-reporting"
        ),
    )
    assert "forbidden_claim_present" in _error_codes(adr)


def test_rapid_report_followup_retains_causality_disagreement(registry_document):
    contract = _contract("v2_n_10_3_3")
    assert {
        "susar_followup.new_information_clock",
        "susar_followup.recipients",
        "susar_followup.documentation",
        "susar_followup.causality_disagreement_retention",
    } <= _required_facts(contract)
    assert "sponsor_dismisses_investigator_causality" in _forbidden_claims(contract)
    assert "分歧" in _qc_text(contract)
    dismissed = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_3_3", "causality-disagreement-dismissed"),
    )
    assert "forbidden_claim_present" in _error_codes(dismissed)


def test_other_serious_safety_information_and_no_invented_receipts(registry_document):
    contract = _contract("v2_n_10_4")
    assert {
        "other_ssi.signal_definition",
        "other_ssi.reporting_criteria",
        "other_ssi.recipient_and_clock",
        "other_ssi.review_responsibility",
    } <= _required_facts(contract)
    assert "fabricated_approval" in _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "信号" in qc_text and "编造" in qc_text
    invented = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_4", "invented-clinical-receipt"),
    )
    assert "forbidden_claim_present" in _error_codes(invented)


def test_aesi_selection_is_product_specific_not_template_list(registry_document):
    contract = _contract("v2_n_10_5")
    assert {
        "aesi.definition",
        "picos.aesi_definitions",
        "aesi.thresholds",
        "aesi.monitoring_and_reporting",
    } <= _required_facts(contract)
    assert "aesi.template_example_list" in _forbidden_facts(contract)
    assert "aesi_list_from_template_example" in _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "阈值" in qc_text and "示例" in qc_text
    template_list = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_5", "aesi-from-template-list"),
    )
    assert "forbidden_fact_present" in _error_codes(template_list)


def test_pregnancy_is_not_auto_sae_nor_auto_withdrawal(registry_document):
    contract = _contract("v2_n_10_6")
    assert {
        "pregnancy.testing_requirements",
        "pregnancy.prevention_requirements",
        "pregnancy.exposure_reporting",
        "pregnancy.partner_consent",
        "pregnancy.outcome_followup",
        "pregnancy.abnormal_outcome_reporting",
        "pregnancy.withdrawal_arrangement",
        "pregnancy.continued_collection_arrangement",
    } <= _required_facts(contract)
    assert "pregnancy.template_example_periods" in _forbidden_facts(contract)
    assert {
        "pregnancy_equals_sae",
        "pregnancy_forces_total_withdrawal",
        "pregnancy_stops_all_followup",
    } <= _forbidden_claims(contract)
    qc_text = _qc_text(contract)
    assert "不自动" in qc_text and "退出" in qc_text
    # Withdrawal handling stays consistent with batch4's discontinuation
    # semantics instead of inventing a second rule set.
    assert "discontinuation.continued_assessment_scope" in _optional_facts(contract)
    auto_sae = check_fixture(
        registry_document, _fixture(registry_document, "v2_n_10_6", "pregnancy-auto-sae")
    )
    assert "forbidden_claim_present" in _error_codes(auto_sae)
    auto_withdrawal = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_6", "pregnancy-auto-withdrawal"),
    )
    assert "forbidden_claim_present" in _error_codes(auto_withdrawal)


# ---------------------------------------------------------------------------
# Parent-body inheritance and cross-batch bindings.
# ---------------------------------------------------------------------------


def test_parent_body_obligations_are_inherited_with_declared_markers(registry_document):
    """The parent chapters/areas are not carriers; their framing obligations are
    carried by named leaves with an honest declared-addition marker.  All five
    parents are accounted for: three inherit real body/area text, two are
    heading-only parents whose area obligations are declared onto their leaves."""
    for node_id, (parent_id, fact_path) in INHERITED_PARENT_BODY.items():
        contract = _contract(node_id)
        assert fact_path in _required_facts(contract), (node_id, fact_path)
        requirement = next(
            item
            for item in contract.substantive_content.fact_requirements
            if item.fact_path == fact_path
        )
        assert "继承声明" in requirement.rationale, node_id
        assert parent_id in requirement.rationale, node_id
        elements = " ".join(contract.substantive_content.project_specific_elements)
        assert "继承声明" in elements and parent_id in elements, node_id
    # The two heading-only parents have no body paragraphs of their own; their
    # area obligations are declared onto the leaf range instead of being
    # silently dropped.
    for parent_id, carrier_id in (
        ("v2_n_10_1", "v2_n_10_1_1"),
        ("v2_n_10_2", "v2_n_10_2_1"),
    ):
        elements = " ".join(
            _contract(carrier_id).substantive_content.project_specific_elements
        )
        assert "继承声明" in elements and parent_id in elements, parent_id
    # No contract claims a nonexistent leaf identity.
    for entry in registry_document.chapters:
        assert entry.contract.semantic_node_id == entry.node_id
        assert entry.node_id not in PARENT_NODES
    dropped = check_fixture(
        registry_document,
        _fixture(registry_document, "v2_n_10_1_1", "parent-safety-framing-dropped"),
    )
    assert "missing_required_fact" in _error_codes(dropped)


def test_cross_batch_bindings_reuse_existing_fact_paths(registry_document):
    """Batch2/batch4 fact bindings are referenced where the meaning matches;
    no second editable store is created for the same meaning."""
    expected_reuse = {
        "v2_n_9_1": {
            "picos.primary_objectives",
            "picos.primary_endpoint",
        },
        "v2_n_9_3": {
            "exploratory.population_pk",
            "exploratory.exposure_response",
            "exploratory.immunogenicity",
        },
        "v2_n_10_5": {"picos.aesi_definitions"},
        "v2_n_10_6": {"discontinuation.continued_assessment_scope"},
    }
    for node_id, paths in expected_reuse.items():
        contract = _contract(node_id)
        declared = {
            item.fact_path for item in contract.substantive_content.fact_requirements
        }
        assert paths <= declared, node_id
        assert not paths & _forbidden_facts(contract), node_id
        assert paths <= set(registry_document.fact_vocabulary), node_id


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
        "missing_coverage",
    }
    assert report.coverage.covered_carrier_count == 19
    # Batch scope only: other batches' carriers must show up as missing and
    # their files must not leak into this slice.
    for node_id in ("v2_n_1_1", "v2_n_3_1_1", "v2_n_8_2", "v2_n_16_x1"):
        assert node_id in report.coverage.missing_node_ids, node_id
    assert len(report.fixture_results) == len(registry_document.fixtures)


def test_full_lint_fails_on_remaining_coverage(registry_document):
    report = lint_registry(REAL_TEMPLATE_DIR, registry_document, require_complete=True)
    assert report.mode == "full"
    assert report.status == "incomplete"
    missing = [f for f in report.errors() if f.code == "missing_coverage"]
    assert report.coverage.expected_carrier_count == 111  # 110 leaf union + cover
    assert len(missing) == report.coverage.expected_carrier_count - 19
    missing_ids = {f.node_id for f in missing}
    assert not missing_ids & set(EXPECTED_CARRIERS)
    assert {"v2_n_1_1", "v2_n_3_1_1", "v2_n_8_2", "v2_n_16_x1"} <= missing_ids


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

    registry_file = tmp_path / "batch5_registry.json"
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
