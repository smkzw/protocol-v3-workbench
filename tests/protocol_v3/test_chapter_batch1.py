"""Task3R.3 batch1 tests: source-bound chapter contracts, skills and fixtures.

Batch1 covers exactly twelve carriers of the accepted TP-MA-07 v2 candidate
registry: the unheaded cover block, ``v2_n_front_1``..``v2_n_front_8`` and
``v2_n_1_1``..``v2_n_1_3``.  The authored per-node contract/skill JSON files
are the single source of contract truth; ``batch1.json`` carries only the
closed fact/claim vocabularies, coverage roles and the executable fixture
payloads, and the assembly CLI joins them into an accepted
``ChapterRegistryDocument`` shape.

Red-first contract: these tests assert batch-scoped source obligations and
were observed failing before the artifacts existed.  Repair round
(20260908): identity facts reuse the existing ``framing.*`` bindings with a
structured independent version date; contacts are unconditional for
sponsor/investigator only with service parties staying conditional; diagram
allocation ratio is conditional on actual randomization with the example SVG
bound example-only; the 17 summary-row selectors are preserved as projected
cells and drug registration classification is never treated as a registry
record; the glossary requires real entry content beyond column headers;
independently required claims get separate evidence-floor groups; participant
terminology uses 试验参与者.  A passing partial lint never represents full
acceptance; medical and native-Word checks stay explicitly deferred.
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
    REPO_ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch1.json"
)
ASSEMBLY_SCRIPT = REPO_ROOT / "scripts/qc/protocol_v3/assemble_chapter_registry.py"

TEMPLATE_ID = "tp_ma_07_v2"
TEMPLATE_SHA256 = (
    "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
)
SVG_ASSET_SHA256 = (
    "c08dc55324b92ed45e283335c1e28a7955993cd42f687c0ca1395c4730c0372c"
)

EXPECTED_CARRIERS = {
    "v2_front_block": "cover",
    "v2_n_front_1": "heading_leaf",
    "v2_n_front_2": "heading_leaf",
    "v2_n_front_3": "heading_leaf",
    "v2_n_front_4": "heading_leaf",
    "v2_n_front_5": "outline_only_leaf",
    "v2_n_front_6": "heading_leaf",
    "v2_n_front_7": "heading_leaf",
    "v2_n_front_8": "heading_leaf",
    "v2_n_1_1": "heading_leaf",
    "v2_n_1_2": "heading_leaf",
    "v2_n_1_3": "heading_leaf",
}

#: The missing-genuine-obligation family chosen per node (the other missing
#: variant stays absent for that node).
MISSING_FAMILY = {
    "v2_front_block": "missing_control",
    "v2_n_front_1": "missing_control",
    "v2_n_front_2": "missing_control",
    "v2_n_front_3": "missing_control",
    "v2_n_front_4": "missing_control",
    "v2_n_front_5": "missing_claim",
    "v2_n_front_6": "missing_control",
    "v2_n_front_7": "missing_control",
    "v2_n_front_8": "missing_claim",
    "v2_n_1_1": "missing_claim",
    "v2_n_1_2": "missing_control",
    "v2_n_1_3": "missing_control",
}

#: The content-spec negative each node's batch must exercise, and the exact
#: deterministic error code that proves it failed for its named reason.
NAMED_NEGATIVES = {
    "v2_front_block": ("missing_control", "missing_required_fact"),
    "v2_n_front_1": ("wrong_source", "wrong_source_role"),
    "v2_n_front_2": ("missing_control", "missing_required_fact"),
    "v2_n_front_3": ("wrong_source", "wrong_source_role"),
    "v2_n_front_4": ("missing_control", "missing_required_cell"),
    "v2_n_front_5": ("missing_claim", "missing_required_claim"),
    "v2_n_front_6": ("wrong_source", "wrong_source_role"),
    "v2_n_front_7": ("missing_control", "missing_structural_object"),
    "v2_n_front_8": ("missing_claim", "missing_required_claim"),
    "v2_n_1_1": ("wrong_source", "wrong_source_role"),
    "v2_n_1_2": ("wrong_source", "wrong_source_role"),
    "v2_n_1_3": ("missing_control", "missing_required_cell"),
}

#: Nodes whose NAMED negative is wrong_source; their missing-family fixture
#: still must fail for its own intended reason (fresh-review D4), not merely
#: generically.
MISSING_FAMILY_CODES = {
    "v2_n_front_1": "missing_required_fact",
    "v2_n_front_3": "missing_required_fact",
    "v2_n_front_6": "missing_required_fact",
    "v2_n_1_1": "missing_required_claim",
    "v2_n_1_2": "missing_required_fact",
}

#: Contracts that declare stable table-cell selectors (cell-level obligations).
CELL_OBLIGATION_CONTRACTS = {
    "v2_n_front_1": (
        "version:cell:version_no",
        "version:cell:version_date",
        "version:cell:change_summary",
        "version:cell:change_rationale",
    ),
    "v2_n_front_4": (
        "contact:cell:sponsor.role",
        "contact:cell:sponsor.address",
        "contact:cell:investigator.role",
        "contact:cell:investigator.address",
    ),
    "v2_n_front_5": (
        "glossary:header:abbreviation",
        "glossary:header:full_name",
        "glossary:header:chinese_meaning",
        "glossary:entry:1.abbreviation",
        "glossary:entry:1.full_name",
        "glossary:entry:1.chinese_meaning",
    ),
    "v2_n_1_1": (
        "synopsis:cell:protocol_id",
        "synopsis:cell:title",
        "synopsis:cell:version_date",
        "synopsis:cell:study_phase",
        "synopsis:cell:registration_classification",
        "synopsis:cell:sponsor",
        "synopsis:cell:principal_investigator",
        "synopsis:cell:trial_institutions",
        "synopsis:cell:objective_estimand_endpoint",
        "synopsis:cell:design",
        "synopsis:cell:population_eligibility",
        "synopsis:cell:drug",
        "synopsis:cell:interventions",
        "synopsis:cell:sample_size",
        "synopsis:cell:statistical_methods",
        "synopsis:cell:overall_duration",
        "synopsis:cell:participation_duration",
    ),
    "v2_n_1_3": (
        "soa:header:visit_window",
        "soa:cell:assessment_identity",
        "soa:cell:footnote_binding",
        "soa:cell:early_exit",
        "soa:cell:safety_followup",
    ),
}

#: Focused repair-round fixtures added on top of the preserved original 48.
NEW_FIXTURE_IDS = (
    "fixture:batch1:v2-n-front-4:positive-no-service",
    "fixture:batch1:v2-n-front-5:missing-control-empty-entry",
    "fixture:batch1:v2-n-1-2:positive-randomized",
    "fixture:batch1:v2-n-1-2:positive-single-arm",
)


def _load_assembly_module():
    spec = importlib.util.spec_from_file_location(
        "assemble_chapter_registry", ASSEMBLY_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _error_codes(result) -> set[str]:
    return {finding.code for finding in result.findings if finding.severity == "error"}


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
    # Superset, not equality: later batches author into the same directories;
    # the selected-batch exactly-12 guarantee is asserted by the assembly tests below.
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


def test_all_twelve_carriers_present_with_derived_coverage_roles(registry_document):
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
        if role == "cover":
            assert node_id not in heading_leaves and node_id not in outline_leaves
        elif role == "outline_only_leaf":
            assert node_id not in heading_leaves and node_id in outline_leaves
        else:
            assert node_id in heading_leaves and node_id in outline_leaves


def test_table_cell_obligations_are_declared_and_exercised(registry_document):
    contracts = {
        entry.node_id: entry.contract for entry in registry_document.chapters
    }
    for node_id, expected_cells in CELL_OBLIGATION_CONTRACTS.items():
        declared: set[str] = set()
        for obligation in contracts[node_id].substantive_content.structural_object_obligations:
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
    # The cell-level missing_control fixtures actually blank required cells.
    for node_id in ("v2_n_front_4", "v2_n_1_3"):
        fixture = next(
            f
            for f in registry_document.fixtures
            if f.chapter_contract_id == f"contract:{node_id.replace('_', '-')}:v2"
            and f.fixture_kind == "missing_control"
            and f.fixture_id.endswith(":missing-control")
        )
        result = check_fixture(registry_document, fixture)
        assert "missing_required_cell" in _error_codes(result), node_id


# ---------------------------------------------------------------------------
# The original 48 fixture slots are preserved through the 20260911 ID rename
# (underscore -> hyphen slug normalization, 1:1, zero slots lost); the repair
# additions are explicit. Fresh-review ruling: ACCEPT_RENAME conditioned on
# this mapping assertion against the pre-repair snapshot.
# ---------------------------------------------------------------------------


def test_original_forty_eight_ids_preserved_and_new_fixtures_explicit(
    registry_document,
):
    ids = {fixture.fixture_id for fixture in registry_document.fixtures}

    pre_repair = json.loads(
        (
            REPO_ROOT
            / "runs/mw_protocol_v3_3r3_batch1_20260906/assembled_batch1_registry.json"
        ).read_text(encoding="utf-8")
    )
    pre_repair_ids = {f["fixture_id"] for f in pre_repair["fixtures"]}
    assert len(pre_repair_ids) == 48

    def _denormalize(fixture_id: str) -> str:
        prefix, batch, slug, family = fixture_id.split(":")
        return f"{prefix}:{batch}:{slug.replace('-', '_')}:{family}"

    mapped = {_denormalize(fixture_id) for fixture_id in ids}
    # Exact 1:1 rename: every original slot survives, nothing extra masquerades.
    assert {nid for nid in mapped if nid in pre_repair_ids} == pre_repair_ids

    for stem in EXPECTED_CARRIERS:
        slug = stem.replace("_", "-")
        original_four = {
            f"fixture:batch1:{slug}:positive",
            f"fixture:batch1:{slug}:{MISSING_FAMILY[stem].replace('_', '-')}",
            f"fixture:batch1:{slug}:wrong-source",
            "fixture:batch1:%s:skeleton" % slug,
        }
        assert original_four <= ids, stem
    assert set(NEW_FIXTURE_IDS) <= ids
    assert len(ids) == 48 + len(NEW_FIXTURE_IDS)


def test_every_fixture_exercises_its_named_defect(registry_document):
    by_node: dict[str, dict[str, list]] = {}
    for fixture in registry_document.fixtures:
        node_id = next(
            entry.node_id
            for entry in registry_document.chapters
            if entry.contract.chapter_contract_id == fixture.chapter_contract_id
        )
        by_node.setdefault(node_id, {}).setdefault(fixture.fixture_kind, []).append(
            fixture
        )
    assert set(by_node) == set(EXPECTED_CARRIERS)
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
        assert named.passed is False
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


def test_forbidden_and_conditional_obligations_are_substantive(registry_document):
    """Every contract carries positive obligations plus real forbidden/optional
    and (where declared) conditional semantics; no title-plus-one-fact shells."""
    for entry in registry_document.chapters:
        substantive = entry.contract.substantive_content
        required_facts = [
            f for f in substantive.fact_requirements if f.obligation.value == "required"
        ]
        required_claims = [
            c for c in substantive.claim_requirements if c.obligation.value == "required"
        ]
        forbidden = [
            f for f in substantive.fact_requirements if f.obligation.value == "forbidden"
        ] + [c for c in substantive.claim_requirements if c.obligation.value == "forbidden"]
        assert required_facts or required_claims, entry.node_id
        assert forbidden, entry.node_id
        assert substantive.skeleton_risk_rules
        assert entry.contract.positive_qc_rules
        assert entry.contract.ctq_items


# ---------------------------------------------------------------------------
# Repair-round source obligations (20260908 counterexample root causes).
# ---------------------------------------------------------------------------


def test_identity_facts_reuse_existing_framing_bindings():
    """Cover and summary bind framing.protocol_id; no separate editable
    protocol id; version and date stay structured and independent."""
    for stem in ("v2_front_block", "v2_n_1_1"):
        contract = ChapterContractV2.model_validate(
            json.loads((CONTRACTS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        )
        required = {
            f.fact_path
            for f in contract.substantive_content.fact_requirements
            if f.obligation.value == "required"
        }
        assert "framing.protocol_id" in required, stem
        assert "framing.version" in required and "document_control.version_date" in required
        if stem == "v2_n_1_1":
            assert "framing.document_title" in required
            assert "framing.study_phase" in required
    identity_files = [
        file
        for path in (CONTRACTS_DIR, SKILLS_DIR)
        for file in path.glob("*.json")
    ] + [BATCH_PATH]
    for file in identity_files:
        text = file.read_text(encoding="utf-8")
        assert '"document_control.protocol_id"' not in text, file.name
        assert '"synopsis.protocol_id"' not in text, file.name
        assert '"synopsis.title"' not in text, file.name


def test_contacts_are_unconditional_only_for_sponsor_and_investigator():
    contract = ChapterContractV2.model_validate(
        json.loads((CONTRACTS_DIR / "v2_n_front_4.json").read_text(encoding="utf-8"))
    )
    substantive = contract.substantive_content
    obligations = substantive.structural_object_obligations
    unconditional_cells = {c for o in obligations for c in o.required_object_cells}
    assert unconditional_cells == {
        "contact:cell:sponsor.role",
        "contact:cell:sponsor.address",
        "contact:cell:investigator.role",
        "contact:cell:investigator.address",
    }
    assert min(o.minimum_occurrences for o in obligations) == 2
    rule = next(
        r
        for r in contract.conditional_applicability_rules
        if "contact.service_parties_applicable" in r.triggering_fact_paths
    )
    assert "contact.service_parties" in rule.required_when_active_fact_paths
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "服务方" in qc_text and "N/A" in qc_text


def test_allocation_ratio_is_conditional_and_single_arm_passes(registry_document):
    contract = next(
        e.contract
        for e in registry_document.chapters
        if e.node_id == "v2_n_1_2"
    )
    obligations = {
        f.fact_path: f.obligation.value
        for f in contract.substantive_content.fact_requirements
    }
    assert obligations["diagram.allocation_ratio"] == "optional"
    rule = next(
        r
        for r in contract.conditional_applicability_rules
        if r.conditional_applicability_rule_id == "applicability:n-1-2:allocation"
    )
    assert rule.triggering_fact_paths == ("diagram.randomized",)
    assert rule.required_when_active_fact_paths == ("diagram.allocation_ratio",)
    for suffix in ("positive-single-arm", "positive"):
        fixture = next(
            f
            for f in registry_document.fixtures
            if f.fixture_id == f"fixture:batch1:v2-n-1-2:{suffix}"
        )
        assert check_fixture(registry_document, fixture).passed
        assert all(
            f.fact_path != "diagram.randomized" for f in fixture.content.facts
        )
    randomized = next(
        f
        for f in registry_document.fixtures
        if f.fixture_id == "fixture:batch1:v2-n-1-2:positive-randomized"
    )
    paths = {f.fact_path for f in randomized.content.facts}
    assert {"diagram.randomized", "diagram.allocation_ratio"} <= paths
    assert check_fixture(registry_document, randomized).passed
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "source[246]" in qc_text and "省略" in qc_text
    assert "记录在案的适用性处置" in qc_text


def test_diagram_skill_provenance_binds_example_asset_and_guards():
    skill = json.loads(
        (SKILLS_DIR / "v2_n_1_2.json").read_text(encoding="utf-8")
    )
    provenance = "\n".join(skill["provenance_requirements"])
    assert SVG_ASSET_SHA256 in provenance
    assert "示例" in provenance  # example-only status, not project data
    contract = ChapterContractV2.model_validate(
        json.loads((CONTRACTS_DIR / "v2_n_1_2.json").read_text(encoding="utf-8"))
    )
    forbidden = {
        f.fact_path
        for f in contract.substantive_content.fact_requirements
        if f.obligation.value == "forbidden"
    }
    assert "diagram.source_example_values" in forbidden
    assert "diagram.template_example_timeline" in forbidden


def test_summary_preserves_17_rows_and_never_treats_classification_as_registry():
    contract = ChapterContractV2.model_validate(
        json.loads((CONTRACTS_DIR / "v2_n_1_1.json").read_text(encoding="utf-8"))
    )
    for obligation in contract.registry_consistency_obligations:
        assert "synopsis.registration_classification" not in (
            obligation.eligibility_fact_paths
        )
    reg = next(
        f
        for f in contract.substantive_content.fact_requirements
        if f.fact_path == "synopsis.registration_classification"
    )
    assert reg.obligation.value == "required"
    qc_text = " ".join(q.rule for q in contract.positive_qc_rules)
    assert "药物注册申请分类" in qc_text
    assert "不得虚构或断言已登记" in qc_text


def test_glossary_requires_entry_content_beyond_headers(registry_document):
    contract = next(
        e.contract
        for e in registry_document.chapters
        if e.node_id == "v2_n_front_5"
    )
    cells = {
        c
        for o in contract.substantive_content.structural_object_obligations
        for c in o.required_object_cells
    }
    assert any(not c.startswith("glossary:header:") for c in cells)
    empty_entry = next(
        f
        for f in registry_document.fixtures
        if f.fixture_id == "fixture:batch1:v2-n-front-5:missing-control-empty-entry"
    )
    result = check_fixture(registry_document, empty_entry)
    assert result.passed is False
    assert "missing_required_cell" in _error_codes(result)


def test_independently_required_claims_have_separate_evidence_groups():
    expected_groups = {
        "v2_front_block": [{"document_control_identity"}, {"confidentiality_binding"}],
        "v2_n_1_1": [{"synopsis_fact_row"}, {"study_objective"}, {"estimand_linkage"}],
        "v2_n_1_2": [{"design_description"}, {"diagram_transition"}],
    }
    for stem, wanted in expected_groups.items():
        contract = ChapterContractV2.model_validate(
            json.loads((CONTRACTS_DIR / f"{stem}.json").read_text(encoding="utf-8"))
        )
        admissions = [
            set(g.admission_claim_types)
            for g in contract.substantive_content.evidence_source_requirements
        ]
        assert admissions == wanted, stem


def test_participant_terminology_across_batch_files():
    # Terminology scope only; the no-second-protocol-identity guarantee lives in
    # test_identity_facts_reuse_existing_framing_bindings (covers the same files).
    for path in list(CONTRACTS_DIR.glob("*.json")) + list(SKILLS_DIR.glob("*.json")) + [
        BATCH_PATH,
    ]:
        assert "受试者" not in path.read_text(encoding="utf-8"), path.name


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
    }
    assert report.coverage.covered_carrier_count == 12
    assert "v2_n_3_1_1" in report.coverage.missing_node_ids
    # Every present fixture validated inside the lint, none misrepresented.
    assert len(report.fixture_results) == len(registry_document.fixtures)


def test_full_lint_fails_on_remaining_coverage(registry_document):
    report = lint_registry(REAL_TEMPLATE_DIR, registry_document, require_complete=True)
    assert report.mode == "full"
    assert report.status == "incomplete"
    missing = [f for f in report.errors() if f.code == "missing_coverage"]
    assert report.coverage.expected_carrier_count == 111  # 110 leaf union + cover
    assert len(missing) == report.coverage.expected_carrier_count - 12
    missing_ids = {f.node_id for f in missing}
    assert not missing_ids & set(EXPECTED_CARRIERS)
    assert "v2_n_3_1_1" in missing_ids and "v2_n_16_x1" in missing_ids


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
        timeout=120,
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

    registry_file = tmp_path / "batch1_registry.json"
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
        timeout=120,
    )
    assert lint_result.returncode == 0, lint_result.stdout + lint_result.stderr
    assert "mode: partial" in lint_result.stdout
    assert "INCOMPLETE" in lint_result.stdout
    assert "PASS" in lint_result.stdout  # exercised fixtures reported
