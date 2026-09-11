"""Task3R.3 batch6 tests: source-bound statistical chapter contracts."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.protocol_workflow.registries.chapters import check_fixture, lint_registry, load_chapter_registry
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
CONTRACTS_DIR = TEMPLATE_DIR / "chapter_contracts"
SKILLS_DIR = TEMPLATE_DIR / "chapter_skills"
BATCH_PATH = ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch6.json"
ASSEMBLY_SCRIPT = ROOT / "scripts/qc/protocol_v3/assemble_chapter_registry.py"
TEMPLATE_ID = "tp_ma_07_v2"
TEMPLATE_SHA256 = "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"

EXPECTED_CARRIERS = {
    "v2_n_11_1": "heading_leaf",
    "v2_n_11_2": "heading_leaf",
    "v2_n_11_3": "heading_leaf",
    "v2_n_11_4_1": "heading_leaf",
    "v2_n_11_4_2": "heading_leaf",
    "v2_n_11_4_3_1": "heading_leaf",
    "v2_n_11_4_3_2": "heading_leaf",
    "v2_n_11_4_4": "heading_leaf",
    "v2_n_11_4_5": "heading_leaf",
    "v2_n_11_4_6": "heading_leaf",
    "v2_n_11_4_7": "heading_leaf",
    "v2_n_11_4_8": "heading_leaf",
    "v2_n_11_4_9": "heading_leaf",
}

REQUIRED_FACTS = {
    "v2_n_11_1": {"picos.primary_endpoint", "framing.structured_design.hypothesis", "statistics.sample_size.test_model", "statistics.sample_size.sidedness", "statistics.sample_size.alpha", "statistics.sample_size.power", "statistics.sample_size.assumptions", "statistics.sample_size.assumption_evidence", "framing.structured_design.allocation_ratio", "statistics.sample_size.attrition", "statistics.sample_size.method", "statistics.sample_size.software_version", "statistics.sample_size.reproducible_result"},
    "v2_n_11_2": {"statistics.analysis_sets.randomized", "statistics.analysis_sets.treated", "statistics.analysis_sets.available_assessments", "statistics.analysis_sets.inclusion_rules", "statistics.analysis_sets.grouping_rules", "statistics.analysis_sets.handling_rules", "statistics.analysis_sets.rescue_treated_handling"},
    "v2_n_11_3": {"statistics.descriptive.variable_types", "statistics.descriptive.summary_conventions", "statistics.descriptive.missing_denominator_rules", "statistics.descriptive.missing_outcome_handling", "statistics.descriptive.intercurrent_event_distinction", "statistics.sap.status", "statistics.sap.timing", "statistics.sap.revision_linkage", "statistics.sap.analysis_unblinding_alignment"},
    "v2_n_11_4_1": {"statistics.demographics.baseline_variables", "statistics.demographics.variable_types", "statistics.demographics.summary_methods", "statistics.demographics.data_definition"},
    "v2_n_11_4_2": {"statistics.adherence.definition", "statistics.adherence.denominator", "statistics.adherence.measurement_method", "statistics.concomitant_treatment.definition", "statistics.concomitant_treatment.timing", "statistics.adherence.data_definition"},
    "v2_n_11_4_3_1": {"estimand.primary.population", "estimand.primary.variable", "estimand.primary.treatment_condition", "estimand.primary.intercurrent_events", "estimand.primary.ice_strategy", "statistics.primary_analysis.method", "statistics.primary_analysis.analysis_set", "statistics.primary_analysis.missing_data", "statistics.primary_analysis.effect_measure", "statistics.primary_analysis.estimand_linkage"},
    "v2_n_11_4_3_2": {"statistics.sensitivity_analysis.method", "statistics.sensitivity_analysis.assumption", "statistics.sensitivity_analysis.estimand_alignment", "statistics.sensitivity_analysis.missing_data_handling", "statistics.sensitivity_analysis.result_interpretation"},
    "v2_n_11_4_4": {"statistics.secondary_analysis.endpoint_definitions", "statistics.secondary_analysis.methods", "statistics.secondary_analysis.data_definition", "statistics.secondary_analysis.analysis_set", "statistics.secondary_analysis.missing_data"},
    "v2_n_11_4_5": {"statistics.safety_analysis.endpoints", "statistics.safety_analysis.population", "statistics.safety_analysis.observation_period", "statistics.safety_analysis.summary_methods", "statistics.safety_analysis.data_definition"},
    "v2_n_11_4_6": {"statistics.exploratory_analysis.endpoints", "statistics.exploratory_analysis.methods", "statistics.exploratory_analysis.data_definition", "statistics.pk_pd_er.pk_applicable", "statistics.pk_pd_er.pd_applicable", "statistics.pk_pd_er.er_applicable", "statistics.pk_pd_er.endpoint_linkage", "statistics.pk_pd_er.sampling_schedule", "statistics.pk_pd_er.model_assumptions"},
    "v2_n_11_4_7": {"statistics.subgroup_analysis.factors", "statistics.subgroup_analysis.methods", "statistics.subgroup_analysis.interaction_or_heterogeneity", "statistics.subgroup_analysis.data_definition", "statistics.subgroup_analysis.interpretation"},
    "v2_n_11_4_8": {"statistics.multiplicity.confirmatory_family", "statistics.multiplicity.ordering", "statistics.multiplicity.alpha_allocation", "statistics.multiplicity.dependencies", "statistics.multiplicity.procedure", "statistics.multiplicity.applicability_disposition"},
    "v2_n_11_4_9": {"statistics.interim.applicable", "statistics.interim.timing", "statistics.interim.information_fraction", "statistics.interim.purpose", "statistics.interim.rules", "statistics.interim.decision_responsibility", "statistics.interim.final_analysis_impact", "statistics.interim.efficacy_alpha_spending", "statistics.interim.safety_review_alpha_separation", "statistics.interim.idmc_responsibilities", "statistics.interim.endpoint_irc_responsibilities", "statistics.interim.canonical_reference"},
}

SOURCE_WINDOWS = {
    "v2_n_11_1": (761, 772), "v2_n_11_2": (773, 777), "v2_n_11_3": (778, 781),
    "v2_n_11_4_1": (784, 784), "v2_n_11_4_2": (786, 786), "v2_n_11_4_3_1": (789, 789),
    "v2_n_11_4_3_2": (790, 790), "v2_n_11_4_4": (793, 794), "v2_n_11_4_5": (795, 796),
    "v2_n_11_4_6": (797, 798), "v2_n_11_4_7": (799, 800), "v2_n_11_4_8": (802, 803),
    "v2_n_11_4_9": (805, 806),
}

SOURCE_SPECIFIC = {
    "v2_n_11_1#wrong-assumed-effect": ("wrong-assumed-effect", "forbidden_fact_present"),
    "v2_n_11_1#n-without-reproducible-inputs": ("n-without-reproducible-inputs", "missing_required_fact"),
    "v2_n_11_1#missing-sidedness": ("missing-sidedness", "missing_required_fact"),
    "v2_n_11_1#missing-allocation": ("missing-allocation", "missing_required_fact"),
    "v2_n_11_2": ("mislabeled-analysis-set", "forbidden_claim_present"),
    "v2_n_11_4_3_2": ("placeholder-sensitivity-table", "forbidden_claim_present"),
    "v2_n_11_4_3_1": ("rescue-estimand-inconsistent", "forbidden_claim_present"),
    "v2_n_11_4_8": ("named-method-without-family", "missing_required_fact"),
    "v2_n_11_4_9": ("interim-timing-alpha-mismatch", "missing_required_fact"),
}


def _source_specific_entries():
    # Keys carry a "#suffix" disambiguator when one node owns several
    # source-specific negatives; all nine are asserted (fresh-review D3).
    for key, (suffix, code) in SOURCE_SPECIFIC.items():
        yield key.split("#")[0], suffix, code


def _assembly_module():
    spec = importlib.util.spec_from_file_location("assemble_chapter_registry", ASSEMBLY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def document():
    payload = _assembly_module().assemble_registry(CONTRACTS_DIR, SKILLS_DIR, BATCH_PATH)
    return load_chapter_registry(payload)


def _entry(document, node_id):
    return next(entry for entry in document.chapters if entry.node_id == node_id)


def _fixture(document, node_id, suffix):
    contract_id = f"contract:{node_id.replace('_', '-')}:v2"
    return next(f for f in document.fixtures if f.chapter_contract_id == contract_id and f.fixture_id.endswith(f":{suffix}"))


def _codes(result):
    return {finding.code for finding in result.findings if finding.severity == "error"}


def test_batch_scope_is_exactly_thirteen_carriers(document):
    assert {entry.node_id: entry.coverage_role for entry in document.chapters} == EXPECTED_CARRIERS
    assert all(entry.node_id not in {"v2_n_11", "v2_n_11_4", "v2_n_11_4_3"} for entry in document.chapters)
    assert len(document.fixtures) >= 52


def test_contracts_preserve_source_identity_and_windows(document):
    node_tree = json.loads((TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8"))
    heading = {node["id"]: node for node in node_tree["heading_style_tree"]["nodes"]}
    for node_id, (first, last) in SOURCE_WINDOWS.items():
        source = heading[node_id]
        contract = _entry(document, node_id).contract
        assert contract.template_id == TEMPLATE_ID
        assert contract.template_sha256 == TEMPLATE_SHA256
        assert source["body_child_index"] == first
        indexes = source["content_paragraph_indexes"]
        if indexes:
            assert indexes[0] == first + 1
            assert max(indexes) == last
        else:
            assert last == first
        assert str(source["style_id"]) in contract.word_rules.required_styles
        assert set(source["bookmarks"]) <= set(contract.word_rules.required_bookmarks)


def test_each_contract_declares_typed_source_obligations(document):
    for node_id, expected in REQUIRED_FACTS.items():
        contract = _entry(document, node_id).contract
        required = {item.fact_path for item in contract.substantive_content.fact_requirements if item.obligation.value == "required"}
        assert expected <= required, node_id
        assert contract.substantive_content.evidence_source_requirements
        assert contract.substantive_content.project_specific_elements
        assert contract.substantive_content.skeleton_risk_rules
        assert contract.positive_qc_rules
        assert contract.ctq_items
        assert any(item.obligation.value == "forbidden" for item in contract.substantive_content.claim_requirements)
        for group in contract.substantive_content.evidence_source_requirements:
            assert group.require_context_window is True
            assert group.minimum_quality_score >= 0.9


def test_statistics_semantic_separation_and_inheritance(document):
    n11_1 = _entry(document, "v2_n_11_1").contract.substantive_content
    paths = {item.fact_path for item in n11_1.fact_requirements}
    assert "estimand.primary.variable" not in paths
    sets = _entry(document, "v2_n_11_2").contract.substantive_content
    set_paths = {item.fact_path for item in sets.fact_requirements}
    assert {"statistics.analysis_sets.randomized", "statistics.analysis_sets.treated", "statistics.analysis_sets.available_assessments"} <= set_paths
    assert "statistics.analysis_sets.rescue_treated_handling" in set_paths
    er = _entry(document, "v2_n_11_4_6").contract
    text = " ".join(er.substantive_content.project_specific_elements + tuple(rule.rationale for rule in er.conditional_applicability_rules))
    assert "PK" in text and "PD" in text and "暴露-效应" in text
    assert "确证" in " ".join(er.substantive_content.project_specific_elements + tuple(rule.rationale for rule in er.conditional_applicability_rules))
    assert "主要或次要分析" in text and "不得仅改称探索性" in text


def test_multiplicity_and_interim_are_bound_to_actual_design(document):
    multiplicity = _entry(document, "v2_n_11_4_8").contract.substantive_content
    mp = {item.fact_path for item in multiplicity.fact_requirements if item.obligation.value == "required"}
    assert {"statistics.multiplicity.confirmatory_family", "statistics.multiplicity.ordering", "statistics.multiplicity.alpha_allocation", "statistics.multiplicity.dependencies"} <= mp
    interim = _entry(document, "v2_n_11_4_9").contract
    ip = {item.fact_path for item in interim.substantive_content.fact_requirements if item.obligation.value == "required"}
    assert {item.fact_path: item.obligation.value for item in interim.substantive_content.fact_requirements}.get("statistics.interim.final_analysis_impact") == "required"
    assert any("efficacy" in item.fact_path for item in interim.substantive_content.fact_requirements)
    assert any("IDMC" in item.rationale or "IRC" in item.rationale for item in interim.substantive_content.fact_requirements)


def test_fixture_families_and_named_negatives(document):
    by_node = {}
    for fixture in document.fixtures:
        node_id = next(entry.node_id for entry in document.chapters if entry.contract.chapter_contract_id == fixture.chapter_contract_id)
        by_node.setdefault(node_id, {}).setdefault(fixture.fixture_kind, []).append(fixture)
    assert set(by_node) == set(EXPECTED_CARRIERS)
    for node_id, families in by_node.items():
        assert {"positive", "wrong_source", "skeleton"} <= set(families)
        assert families.get("missing_claim") or families.get("missing_control")
        assert all(check_fixture(document, fixture).passed for fixture in families["positive"])
        assert all(not check_fixture(document, fixture).passed for kind, items in families.items() if kind != "positive" for fixture in items)
        for fixture in families["wrong_source"]:
            assert "wrong_source_role" in _codes(check_fixture(document, fixture)), fixture.fixture_id
        for fixture in families["skeleton"]:
            assert "skeleton_content" in _codes(check_fixture(document, fixture)), fixture.fixture_id
    for node_id, suffix, code in _source_specific_entries():
        result = check_fixture(document, _fixture(document, node_id, suffix))
        assert not result.passed
        assert code in _codes(result), (node_id, suffix, _codes(result))


def test_partial_lint_is_clean_and_reports_incomplete(document):
    report = lint_registry(TEMPLATE_DIR, document, require_complete=False)
    assert report.mode == "partial"
    assert report.status == "incomplete"
    assert report.errors() == ()
    assert report.coverage.covered_carrier_count == 13
    assert not set(EXPECTED_CARRIERS) & set(report.coverage.missing_node_ids)
    assert "partial_mode_not_full_acceptance" in {finding.code for finding in report.findings}


def _cli_env():
    return {"PATH": "/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin", "HOME": os.environ.get("HOME", "/tmp"), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1", "PYTHONPATH": "tests/protocol_v3:services/api:packages:.", "TMPDIR": os.environ.get("TMPDIR", "/tmp")}


def test_assembly_cli_is_stdout_only(tmp_path):
    result = subprocess.run([sys.executable, str(ASSEMBLY_SCRIPT), "--contracts-dir", str(CONTRACTS_DIR), "--skills-dir", str(SKILLS_DIR), "--batch", str(BATCH_PATH)], cwd=str(ROOT), env=_cli_env(), capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["chapters"]) == 13
