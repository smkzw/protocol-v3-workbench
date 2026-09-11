"""3R.3 batch7 tests for data-management and ethics chapter carriers.

These tests are batch-scoped: they validate only the thirteen chapter 12/13
leaf carriers, their source anchors, substantive obligations, manifests, and
executable fixtures. Native Word, clinical, legal, and approval judgments
remain deferred.
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
BATCH_PATH = REPO_ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch7.json"
ASSEMBLY_SCRIPT = REPO_ROOT / "scripts/qc/protocol_v3/assemble_chapter_registry.py"
TEMPLATE_ID = "tp_ma_07_v2"
TEMPLATE_SHA256 = "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"

EXPECTED_CARRIERS = {
    "v2_n_12_1": "heading_leaf",
    "v2_n_12_2": "heading_leaf",
    "v2_n_12_3": "heading_leaf",
    "v2_n_12_4": "heading_leaf",
    "v2_n_12_5": "heading_leaf",
    "v2_n_12_6": "heading_leaf",
    "v2_n_12_7": "heading_leaf",
    "v2_n_12_8": "heading_leaf",
    "v2_n_12_9": "heading_leaf",
    "v2_n_13_1": "heading_leaf",
    "v2_n_13_2": "heading_leaf",
    "v2_n_13_3": "heading_leaf",
    "v2_n_13_4": "heading_leaf",
}

SOURCE_WINDOWS = {
    "v2_n_12_1": (812, 813),
    "v2_n_12_2": (814, 816),
    "v2_n_12_3": (817, 819),
    "v2_n_12_4": (820, 821),
    "v2_n_12_5": (822, 825),
    "v2_n_12_6": (826, 828),
    "v2_n_12_7": (829, 836),
    "v2_n_12_8": (837, 842),
    "v2_n_12_9": (843, 849),
    "v2_n_13_1": (852, 853),
    "v2_n_13_2": (854, 856),
    "v2_n_13_3": (862, 879),
    "v2_n_13_4": (880, 881),
}

TITLES = {
    "v2_n_12_1": "数据收集和管理职责",
    "v2_n_12_2": "数据采集与方式",
    "v2_n_12_3": "数据清理与质疑解决",
    "v2_n_12_4": "数据的修改和审核",
    "v2_n_12_5": "数据锁定及导出",
    "v2_n_12_6": "数据治理与计算机化系统",
    "v2_n_12_7": "储备样本和数据的未来使用",
    "v2_n_12_8": "研究记录的保存",
    "v2_n_12_9": "研究发表和数据共享政策",
    "v2_n_13_1": "伦理规范",
    "v2_n_13_2": "知情同意",
    "v2_n_13_3": "保密和隐私",
    "v2_n_13_4": "试验参与者的补偿、赔偿与保险",
}

MISSING_FAMILY = {
    "v2_n_12_1": "missing_control",
    "v2_n_12_2": "missing_control",
    "v2_n_12_3": "missing_control",
    "v2_n_12_4": "missing_control",
    "v2_n_12_5": "missing_control",
    "v2_n_12_6": "missing_control",
    "v2_n_12_7": "missing_claim",
    "v2_n_12_8": "missing_control",
    "v2_n_12_9": "missing_claim",
    "v2_n_13_1": "missing_control",
    "v2_n_13_2": "missing_claim",
    "v2_n_13_3": "missing_control",
    "v2_n_13_4": "missing_control",
}

NAMED_NEGATIVES = {
    "v2_n_12_1": ("copied-company-name", "forbidden_fact_present"),
    "v2_n_12_2": ("missing-control", "missing_required_fact"),
    "v2_n_12_3": ("missing-control", "missing_required_fact"),
    "v2_n_12_4": ("missing-control", "missing_required_fact"),
    "v2_n_12_5": ("missing-control", "missing_required_fact"),
    "v2_n_12_6": ("missing-control", "missing_required_fact"),
    "v2_n_12_7": ("study-data-conflated-with-future-use", "missing_required_claim"),
    "v2_n_12_8": ("blank-custody-period", "missing_required_fact"),
    "v2_n_12_9": ("nonexistent-repository", "forbidden_claim_present"),
    "v2_n_13_1": ("unsigned-plan-claimed-approved", "forbidden_claim_present"),
    "v2_n_13_2": ("future-use-from-ordinary-consent", "forbidden_claim_present"),
    "v2_n_13_3": ("missing-control", "missing_required_fact"),
    "v2_n_13_4": ("missing-compensation-arrangement", "missing_required_fact"),
}

SOURCE_SPECIFIC_IDS = {
    "v2_n_12_1": "copied-company-name",
    "v2_n_12_7": "study-data-conflated-with-future-use",
    "v2_n_12_8": "blank-custody-period",
    "v2_n_12_9": "nonexistent-repository",
    "v2_n_13_1": "unsigned-plan-claimed-approved",
    "v2_n_13_2": "future-use-from-ordinary-consent",
    "v2_n_13_4": "missing-compensation-arrangement",
}


def _load_assembly_module():
    spec = importlib.util.spec_from_file_location("assemble_chapter_registry", ASSEMBLY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _error_codes(result) -> set[str]:
    return {finding.code for finding in result.findings if finding.severity == "error"}


def _contract(node_id: str) -> ChapterContractV2:
    return ChapterContractV2.model_validate(
        json.loads((CONTRACTS_DIR / f"{node_id}.json").read_text(encoding="utf-8"))
    )


def _fixtures_by_node(document):
    by_node: dict[str, dict[str, list]] = {}
    for fixture in document.fixtures:
        node_id = next(
            entry.node_id
            for entry in document.chapters
            if entry.contract.chapter_contract_id == fixture.chapter_contract_id
        )
        by_node.setdefault(node_id, {}).setdefault(fixture.fixture_kind, []).append(fixture)
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


def test_contract_and_skill_files_have_exact_batch_identities():
    assert set(EXPECTED_CARRIERS) <= {path.stem for path in CONTRACTS_DIR.glob("*.json")}
    assert set(EXPECTED_CARRIERS) <= {path.stem for path in SKILLS_DIR.glob("*.json")}
    for node_id in EXPECTED_CARRIERS:
        contract = _contract(node_id)
        assert contract.semantic_node_id == node_id
        assert contract.chapter_contract_id == f"contract:{node_id.replace('_', '-')}:v2"
        assert contract.template_id == TEMPLATE_ID
        assert contract.template_sha256 == TEMPLATE_SHA256
        assert contract.canonical_state.value == "frozen"
        skill = json.loads((SKILLS_DIR / f"{node_id}.json").read_text(encoding="utf-8"))
        assert skill["node_id"] == node_id
        assert skill["chapter_contract_id"] == contract.chapter_contract_id
        assert skill["skill_id"] == contract.chapter_skill_id
        assert skill["skill_version"] == contract.chapter_skill_version
        assert "provider" not in skill and "model" not in skill


def test_exact_thirteen_leaf_carriers_and_derived_roles(registry_document):
    node_tree = json.loads((REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8"))
    heading_leaves = {
        node["id"] for node in node_tree["heading_style_tree"]["nodes"] if node.get("is_leaf_heading")
    }
    outline_leaves = {
        node["id"] for node in node_tree["outlined_tree"]["nodes"] if node.get("is_leaf")
    }
    entries = {entry.node_id: entry for entry in registry_document.chapters}
    assert set(entries) == set(EXPECTED_CARRIERS)
    for node_id, role in EXPECTED_CARRIERS.items():
        assert entries[node_id].coverage_role == role
        assert node_id in heading_leaves and node_id in outline_leaves


def test_source_windows_titles_styles_and_bookmarks_come_from_node_tree():
    node_tree = json.loads((REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8"))
    heading = {node["id"]: node for node in node_tree["heading_style_tree"]["nodes"]}
    for node_id, (first, last) in SOURCE_WINDOWS.items():
        node = heading[node_id]
        assert node["title_zh"] == TITLES[node_id]
        assert node["body_child_index"] == first
        assert node["content_paragraph_indexes"]
        assert node["content_paragraph_indexes"][0] == first + 1
        assert max(node["content_paragraph_indexes"]) == last
        contract = _contract(node_id)
        assert contract.word_rules.required_styles == (node["style_id"],)
        assert contract.word_rules.required_bookmarks == tuple(node["bookmarks"])


def test_substantive_contracts_have_positive_forbidden_and_evidence_obligations(
    registry_document,
):
    for entry in registry_document.chapters:
        substantive = entry.contract.substantive_content
        required = [
            item for item in substantive.fact_requirements
            if item.obligation.value == "required"
        ] + [
            item for item in substantive.claim_requirements
            if item.obligation.value == "required"
        ]
        forbidden = [
            item for item in substantive.fact_requirements
            if item.obligation.value == "forbidden"
        ] + [
            item for item in substantive.claim_requirements
            if item.obligation.value == "forbidden"
        ]
        assert required, entry.node_id
        assert forbidden, entry.node_id
        assert substantive.evidence_source_requirements, entry.node_id
        assert substantive.skeleton_risk_rules, entry.node_id
        assert entry.contract.positive_qc_rules, entry.node_id
        assert entry.contract.ctq_items, entry.node_id
        for group in substantive.evidence_source_requirements:
            assert group.require_context_window is True
            assert group.minimum_quality_score >= 0.9


def test_data_and_ethics_semantics_are_separately_typed():
    facts = {
        node_id: {
            item.fact_path: item.obligation.value
            for item in _contract(node_id).substantive_content.fact_requirements
        }
        for node_id in EXPECTED_CARRIERS
    }
    claims = {
        node_id: {
            item.claim_type: item.obligation.value
            for item in _contract(node_id).substantive_content.claim_requirements
        }
        for node_id in EXPECTED_CARRIERS
    }
    assert {
        "data_management.direct_ecrf_source",
        "data_management.copied_source_record",
    } <= set(facts["v2_n_12_2"])
    assert {
        "future_use.purpose",
        "future_use.location",
        "future_use.duration",
        "future_use.genetic_testing",
        "future_use.consent",
        "future_use.review_plan",
    } <= set(facts["v2_n_12_7"])
    assert "future_use_permission_from_ordinary_consent" in claims["v2_n_13_2"]
    assert claims["v2_n_13_2"]["future_use_permission_from_ordinary_consent"] == "forbidden"
    assert {
        "retention.trigger",
        "retention.duration",
        "retention.custody",
        "retention.disposition",
    } <= set(facts["v2_n_12_8"])
    assert {
        "consent.procedure",
        "consent.version",
        "consent.responsible_role",
        "consent.before_relevant_procedure",
        "consent.capacity_or_representative",
        "consent.witness_if_applicable",
        "consent.new_information_handling",
    } <= set(facts["v2_n_13_2"])
    assert {
        "confidentiality.data_coding",
        "confidentiality.sample_coding",
        "confidentiality.recipients",
        "confidentiality.access_control",
        "confidentiality.transfer_arrangements",
    } <= set(facts["v2_n_13_3"])
    assert "compensation.arrangement" in facts["v2_n_13_4"]


def test_table_cells_are_declared_and_positive_fixtures_supply_them(registry_document):
    for fixture in registry_document.fixtures:
        if fixture.fixture_kind != "positive":
            continue
        node_id = next(
            entry.node_id
            for entry in registry_document.chapters
            if entry.contract.chapter_contract_id == fixture.chapter_contract_id
        )
        expected_cells = {
            cell_id
            for obligation in next(
                entry.contract for entry in registry_document.chapters if entry.node_id == node_id
            ).substantive_content.structural_object_obligations
            for cell_id in obligation.required_object_cells
        }
        supplied = {
            cell.cell_id: cell
            for obj in fixture.content.objects
            for cell in obj.cells
        }
        assert expected_cells <= set(supplied)
        assert all((supplied[cell_id].value or "").strip() for cell_id in expected_cells)


def test_fixture_families_and_named_defects(registry_document):
    by_node = _fixtures_by_node(registry_document)
    assert set(by_node) == set(EXPECTED_CARRIERS)
    total = 0
    for node_id, kinds in by_node.items():
        assert {"positive", "wrong_source", "skeleton"} <= set(kinds)
        assert kinds.get("missing_claim") or kinds.get("missing_control")
        for fixture in kinds["positive"]:
            result = check_fixture(registry_document, fixture)
            assert result.passed is True, fixture.fixture_id
            assert result.deferred_qc_obligations
        suffix, expected_code = NAMED_NEGATIVES[node_id]
        named = check_fixture(registry_document, _fixture(registry_document, node_id, suffix))
        assert named.passed is False
        assert expected_code in _error_codes(named), (node_id, _error_codes(named))
        wrong = check_fixture(registry_document, kinds["wrong_source"][0])
        assert "wrong_source_role" in _error_codes(wrong)
        skeleton = check_fixture(registry_document, kinds["skeleton"][0])
        assert "skeleton_content" in _error_codes(skeleton)
        for fixture_group in kinds.values():
            for fixture in fixture_group:
                if fixture.fixture_kind != "positive":
                    assert check_fixture(registry_document, fixture).passed is False
        total += sum(len(group) for group in kinds.values())
    assert total >= 52
    assert total == len(registry_document.fixtures)


def test_source_specific_negative_ids_are_exercised(registry_document):
    for node_id, suffix in SOURCE_SPECIFIC_IDS.items():
        fixture = _fixture(registry_document, node_id, suffix)
        result = check_fixture(registry_document, fixture)
        assert result.passed is False
        assert NAMED_NEGATIVES[node_id][1] in _error_codes(result)


def test_closed_vocabularies_cover_declared_contract_paths(registry_document):
    fact_vocabulary = set(registry_document.fact_vocabulary)
    claim_vocabulary = set(registry_document.claim_vocabulary)
    used_facts: set[str] = set()
    used_claims: set[str] = set()
    for entry in registry_document.chapters:
        substantive = entry.contract.substantive_content
        used_facts.update(item.fact_path for item in substantive.fact_requirements)
        used_claims.update(item.claim_type for item in substantive.claim_requirements)
        for rule in entry.contract.conditional_applicability_rules:
            used_facts.update(rule.triggering_fact_paths)
            used_facts.update(rule.required_when_active_fact_paths)
            used_claims.update(rule.required_when_active_claim_types)
        for group in substantive.evidence_source_requirements:
            used_claims.update(group.admission_claim_types)
        for item in entry.contract.ctq_items:
            used_facts.update(item.linked_fact_paths)
            used_claims.update(item.linked_claim_types)
    assert used_facts <= fact_vocabulary
    assert used_claims <= claim_vocabulary


def test_batch7_terminology_is_participant_safe():
    paths = [BATCH_PATH]
    paths.extend(CONTRACTS_DIR / f"{node_id}.json" for node_id in EXPECTED_CARRIERS)
    paths.extend(SKILLS_DIR / f"{node_id}.json" for node_id in EXPECTED_CARRIERS)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "试验参与者" in text, path.name
        assert "受试者" not in text, path.name


def test_partial_lint_is_clean_but_incomplete(registry_document):
    report = lint_registry(REAL_TEMPLATE_DIR, registry_document, require_complete=False)
    assert report.mode == "partial"
    assert report.status == "incomplete"
    assert report.errors() == ()
    assert "partial_mode_not_full_acceptance" in {finding.code for finding in report.findings}
    assert report.coverage.covered_carrier_count == 13
    assert len(report.fixture_results) == len(registry_document.fixtures)


def test_full_lint_reports_only_remaining_coverage(registry_document):
    report = lint_registry(REAL_TEMPLATE_DIR, registry_document, require_complete=True)
    assert report.mode == "full"
    assert report.status == "incomplete"
    missing_ids = {
        finding.node_id for finding in report.errors() if finding.code == "missing_coverage"
    }
    assert report.coverage.expected_carrier_count == 111
    assert not missing_ids & set(EXPECTED_CARRIERS)
    assert {"v2_n_1_1", "v2_n_3_1_1", "v2_n_16_x1"} <= missing_ids


def _cli_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "LANG": "en_US.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": "tests/protocol_v3:services/api:packages:.",
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }


def test_assembly_and_partial_lint_cli_roundtrip(tmp_path):
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
    registry_file = tmp_path / "batch7_registry.json"
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
    assert "PASS" in lint_result.stdout
