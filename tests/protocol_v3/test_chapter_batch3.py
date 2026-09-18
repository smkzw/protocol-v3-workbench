"""Task3R.3 batch3 source-bound chapter contracts and fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.protocol_workflow.registries.chapters import (
    CHAPTER_SKILL_INPUT_SCHEMA_REF,
    CHAPTER_SKILL_OUTPUT_SCHEMA_REF,
    check_fixture,
    lint_registry,
    load_chapter_registry,
)
from scripts.qc.protocol_v3.assemble_chapter_registry import assemble_registry


ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
CONTRACT_DIR = TEMPLATE_DIR / "chapter_contracts"
SKILL_DIR = TEMPLATE_DIR / "chapter_skills"
BATCH_PATH = ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch3.json"
TEMPLATE_SHA256 = "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"

NODE_IDS = (
    "v2_n_4_1",
    "v2_n_4_2",
    "v2_n_4_3",
    "v2_n_4_4",
    "v2_n_4_5",
    "v2_n_5_1",
    "v2_n_5_2",
    "v2_n_5_3",
    "v2_n_5_4",
    "v2_n_5_5",
)

SOURCE_METADATA = {
    "v2_n_4_1": (341, ("_Toc132623334",), (342, 353)),
    "v2_n_4_2": (354, ("_Toc132623335",), (355, 355)),
    "v2_n_4_3": (356, ("_Toc132623336",), (357, 357)),
    "v2_n_4_4": (358, ("_Toc132623337",), (359, 362)),
    "v2_n_4_5": (363, ("_Toc132623338",), (364, 369)),
    "v2_n_5_1": (380, ("_Toc132623340",), (381, 393)),
    "v2_n_5_2": (394, ("_Toc132623341",), (395, 407)),
    "v2_n_5_3": (408, ("_Toc132623342",), (409, 409)),
    "v2_n_5_4": (410, ("_Toc132623343",), (411, 414)),
    "v2_n_5_5": (415, ("_Toc9900001",), (416, 418)),
}

REQUIRED_EXISTING_FACTS = {
    "v2_n_4_1": "framing.structured_design",
    "v2_n_4_2": "framing.structured_design",
    "v2_n_4_3": "framing.structured_design",
    "v2_n_4_4": "picos.study_epochs",
    "v2_n_4_5": "framing.structured_design",
    "v2_n_5_1": "framing.population_intent",
    "v2_n_5_2": "picos.exclusion_modules",
    "v2_n_5_3": "picos.inclusion_modules",
    "v2_n_5_4": "picos.inclusion_modules",
    "v2_n_5_5": "picos.population_summary",
}

SOURCE_SPECIFIC_FIXTURES = {
    "fixture:batch3:v2-n-4-1:wrong-comparator-ratio",
    "fixture:batch3:v2-n-4-5:stale-numbered-reference",
    "fixture:batch3:v2-n-4-3:dose-other-regimen",
    "fixture:batch3:v2-n-4-4:end-of-treatment-as-follow-up",
    "fixture:batch3:v2-n-5-1:threshold-contradiction",
    "fixture:batch3:v2-n-5-3:copied-contraception-duration",
    "fixture:batch3:v2-n-5-4:nonspecific-per-protocol",
    "fixture:batch3:v2-n-5-5:phantom-completed-approval",
}
# Fresh-review D1: the stale numbered cross-reference lives at source paragraph 364,
# which is v2_n_4_5 content (node_tree body_child 363, content 364-369); the negative
# was rebound from v2_n_4_2 accordingly.


def _assembled():
    return assemble_registry(CONTRACT_DIR, SKILL_DIR, BATCH_PATH)


def _document():
    return load_chapter_registry(_assembled())


def _fixture_map():
    return {fixture.fixture_id: fixture for fixture in _document().fixtures}


def test_batch3_assembles_exactly_ten_source_carriers():
    payload = _assembled()
    batch = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
    assert [entry["node_id"] for entry in payload["chapters"]] == sorted(NODE_IDS)
    assert set(batch["coverage_roles"]) == set(NODE_IDS)
    assert len(batch["coverage_roles"]) == 10
    assert payload["template_id"] == "tp_ma_07_v2"
    assert payload["template_sha256"] == TEMPLATE_SHA256
    assert all(entry["coverage_role"] == "heading_leaf" for entry in payload["chapters"])


def _contract_id_for(node_id):
    return f"contract:{node_id.replace('_', '-')}:v2"


def test_batch3_contracts_and_skills_preserve_source_identity():
    payload = _assembled()
    for entry in payload["chapters"]:
        node_id = entry["node_id"]
        body_index, bookmarks, paragraph_range = SOURCE_METADATA[node_id]
        contract = entry["contract"]
        skill = entry["skills"][0]
        assert contract["semantic_node_id"] == node_id
        assert contract["template_sha256"] == TEMPLATE_SHA256
        assert contract["canonical_state"] == "frozen"
        assert contract["word_rules"]["required_styles"] == ["3", "1"]
        assert contract["word_rules"]["required_bookmarks"] == list(bookmarks)
        assert skill["node_id"] == node_id
        assert skill["template_sha256"] == TEMPLATE_SHA256
        assert skill["input_schema_ref"] == CHAPTER_SKILL_INPUT_SCHEMA_REF
        assert skill["output_schema_ref"] == CHAPTER_SKILL_OUTPUT_SCHEMA_REF
        provenance = "\n".join(skill["provenance_requirements"])
        assert f"body-child {body_index}" in provenance
        assert str(paragraph_range[0]) in provenance
        assert str(paragraph_range[1]) in provenance
        assert "style ID 3" in provenance
        assert "not provider" in provenance.lower() or "供应商" in provenance


def test_contracts_reuse_shared_fact_paths_and_declare_typed_detail():
    payload = _assembled()
    for entry in payload["chapters"]:
        node_id = entry["node_id"]
        facts = {
            item["fact_path"]: item
            for item in entry["contract"]["substantive_content"]["fact_requirements"]
        }
        assert REQUIRED_EXISTING_FACTS[node_id] in facts
        assert all("typed" in item["rationale"] or "结构化" in item["rationale"] for item in facts.values())
        assert entry["contract"]["substantive_content"]["project_specific_elements"]
        assert entry["contract"]["substantive_content"]["skeleton_risk_rules"]

    inclusion = next(e for e in payload["chapters"] if e["node_id"] == "v2_n_5_1")["contract"]
    exclusion = next(e for e in payload["chapters"] if e["node_id"] == "v2_n_5_2")["contract"]
    inclusion_paths = {item["fact_path"] for item in inclusion["substantive_content"]["fact_requirements"]}
    exclusion_paths = {item["fact_path"] for item in exclusion["substantive_content"]["fact_requirements"]}
    assert "picos.inclusion_modules" in inclusion_paths
    assert "picos.exclusion_modules" in exclusion_paths
    assert any("all-applicable" in element for element in inclusion["substantive_content"]["project_specific_elements"])
    assert any("any-applicable" in element for element in exclusion["substantive_content"]["project_specific_elements"])
    assert not inclusion_paths & exclusion_paths - {
        "framing.population_intent", "picos.population_summary",
        "picos.risk.pregnancy_contraception",
    }


def test_parent_population_framing_is_carried_by_inclusion_and_referenced_by_exclusion():
    payload = _assembled()
    by_id = {entry["node_id"]: entry["contract"] for entry in payload["chapters"]}
    inclusion = by_id["v2_n_5_1"]["substantive_content"]
    exclusion = by_id["v2_n_5_2"]["substantive_content"]
    inclusion_elements = " ".join(inclusion["project_specific_elements"])
    exclusion_elements = " ".join(exclusion["project_specific_elements"])
    assert "v2_n_5" in inclusion_elements
    assert "v2_n_5" in exclusion_elements
    assert any("framing" in element for element in inclusion["project_specific_elements"])
    assert any("reference" in element.lower() or "引用" in element for element in exclusion["project_specific_elements"])
    assert "population.framing" not in {
        item["fact_path"]
        for item in inclusion["fact_requirements"] + exclusion["fact_requirements"]
    }

@pytest.mark.parametrize("node_id", NODE_IDS)
def test_each_carrier_has_four_exercised_fixture_families(node_id):
    fixtures = _fixture_map()
    kinds = {
        fixture.fixture_kind
        for fixture in fixtures.values()
        if fixture.chapter_contract_id == _contract_id_for(node_id)
    }
    assert "positive" in kinds
    assert "wrong_source" in kinds
    assert "skeleton" in kinds
    assert kinds & {"missing_claim", "missing_control"}


def test_source_specific_negative_fixtures_are_material_and_fail_for_expected_family():
    fixtures = _fixture_map()
    assert SOURCE_SPECIFIC_FIXTURES <= set(fixtures)
    document = _document()
    for fixture_id in SOURCE_SPECIFIC_FIXTURES:
        fixture = fixtures[fixture_id]
        result = check_fixture(document, fixture)
        assert result.passed is False, fixture_id
        assert result.error_codes(), fixture_id
        assert fixture.supplied_qc_verdict is not None
        assert fixture.supplied_qc_verdict.startswith("negative_reason:")
        assert "合成" in " ".join(
            [
                *(fact.value or "" for fact in fixture.content.facts),
                *(claim.statement or "" for claim in fixture.content.claims),
                *(e.locator for e in fixture.content.evidence),
            ]
        )


def test_population_predicates_are_typed_and_not_inverse_duplicates():
    payload = _assembled()
    by_id = {entry["node_id"]: entry["contract"] for entry in payload["chapters"]}
    inclusion = by_id["v2_n_5_1"]["substantive_content"]
    exclusion = by_id["v2_n_5_2"]["substantive_content"]
    for substantive in (inclusion, exclusion):
        paths = {item["fact_path"] for item in substantive["fact_requirements"]}
        assert any(path.endswith(".logic") for path in paths)
        assert any(path.endswith(".parameters") for path in paths)
        assert any(path.endswith(".windows") for path in paths)
        assert any(path.endswith(".exceptions") for path in paths)
    assert any("all-applicable" in item for item in by_id["v2_n_5_1"]["substantive_content"]["project_specific_elements"])
    assert any(item["claim_type"] == "inclusion_predicate" and item["obligation"] == "required" for item in by_id["v2_n_5_1"]["substantive_content"]["claim_requirements"])
    assert any("any-applicable" in item for item in by_id["v2_n_5_2"]["substantive_content"]["project_specific_elements"])
    assert any(item["claim_type"] == "exclusion_predicate" and item["obligation"] == "required" for item in by_id["v2_n_5_2"]["substantive_content"]["claim_requirements"])


def test_design_high_risk_choices_are_decisions_not_defaults():
    payload = _assembled()
    by_id = {entry["node_id"]: entry["contract"] for entry in payload["chapters"]}
    for node_id in ("v2_n_4_1", "v2_n_4_2", "v2_n_4_3", "v2_n_4_5"):
        contract_text = json.dumps(by_id[node_id], ensure_ascii=False)
        assert "human" in contract_text.lower() or "人工" in contract_text
        assert "default" in contract_text.lower() or "默认" in contract_text
    assert "1:1" not in json.dumps(by_id["v2_n_4_1"], ensure_ascii=False)
    assert "IWRS" not in json.dumps(by_id["v2_n_4_5"], ensure_ascii=False)
    assert "per statistics section 9" not in json.dumps(by_id["v2_n_4_2"], ensure_ascii=False).lower()


def test_completion_and_overall_end_are_distinct_and_screening_is_distinct():
    payload = _assembled()
    by_id = {entry["node_id"]: entry["contract"] for entry in payload["chapters"]}
    end_paths = {
        item["fact_path"]
        for item in by_id["v2_n_4_4"]["substantive_content"]["fact_requirements"]
    }
    screen_paths = {
        item["fact_path"]
        for item in by_id["v2_n_5_4"]["substantive_content"]["fact_requirements"]
    }
    assert any("completion" in path for path in end_paths)
    assert any("overall" in path or "study_end" in path for path in end_paths)
    assert any("screen_failure" in path for path in screen_paths)
    assert any("rescreen" in path for path in screen_paths)
    contract_text = json.dumps(by_id["v2_n_5_4"], ensure_ascii=False).lower()
    assert "未随机化" in contract_text
    assert "筛选失败" in contract_text


def test_partial_lint_is_incomplete_and_full_lint_reports_missing_coverage():
    document = _document()
    partial = lint_registry(TEMPLATE_DIR, document, require_complete=False)
    assert partial.mode == "partial"
    assert partial.status == "incomplete"
    assert "partial_mode_not_full_acceptance" in {finding.code for finding in partial.findings}
    assert not partial.errors()
    assert partial.coverage.covered_carrier_count == 10
    assert partial.coverage.expected_carrier_count == 111

    full = lint_registry(TEMPLATE_DIR, document, require_complete=True)
    assert full.mode == "full"
    assert full.status == "incomplete"
    assert set(NODE_IDS).isdisjoint(full.coverage.missing_node_ids)
    assert len(full.coverage.missing_node_ids) == 101
    assert "missing_coverage" in {finding.code for finding in full.errors()}


def test_fixture_checker_ignores_supplied_truth_flags():
    document = _document()
    positive = next(f for f in document.fixtures if f.fixture_kind == "positive")
    result = check_fixture(document, positive)
    assert result.passed is True
    assert result.ignored_supplied_verdict is True
    assert any(item == "medical_and_qc_judgment_not_executed" for item in result.deferred_qc_obligations)
