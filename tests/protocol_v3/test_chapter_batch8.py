"""3R.3 batch8 tests: quality, references and appendix carriers (final batch).

Batch8 covers exactly the twelve carriers of sections 14 (质量保证与质量控制),
15 (参考文献) and 16 (附录) of the accepted TP-MA-07 v2 candidate registry:
seven section-14 heading leaves, the section-15 heading leaf, the heading-only
appendix container ``v2_n_16`` and its three outline-only appendix leaves
``v2_n_16_x1`` / ``v2_n_16_x2`` / ``v2_n_16_x3``.  The authored per-node
contract/skill JSON files are the single source of contract truth;
``batch8.json`` carries only the closed fact/claim vocabularies, coverage roles
and the executable fixture payloads; the assembly CLI joins them into an
accepted ``ChapterRegistryDocument`` shape.

Red-first contract: these tests were observed failing before the artifacts
existed.  They encode the batch8 content spec
(reviews/mw_protocol_v3_3r3_batch8_content_spec_20260906.md) obligations the
batch exists to satisfy:

* CtQ/risk management keeps actual critical factors, associated risks,
  proportionate controls, responsibility and review linkage; a generic slogan
  or placeholder plan name never satisfies it;
* sponsor / monitor / investigator responsibilities match the actual
  arrangement and never infer completed training or signed acceptance, and
  monitoring never promises unexamined universal source verification;
* audit/inspection and deviations stay distinct processes with records, impact
  assessment, communication and real important/general/urgent-hazard
  definitions; a local TP-MA-15 title is declared provenance-pending, not
  integrated content;
* safety oversight states its actual body type, composition, roles,
  information and review arrangements; independent DSMB, sponsor-involved SMC
  and endpoint IRC are not interchangeable and no charter/membership is
  fabricated;
* references are generated from actually used sources with complete
  bibliographic metadata and resolvable citations; template example references
  are not a study bibliography and no in-text citation is left without target;
* the appendix container aggregates actual applicable attachments while the
  outlined leaves keep their own coverage; ECOG/NYHA are conditional on actual
  assessments (no automatic inclusion); laboratory/destruction provider
  identities are genuinely applicable project facts, never template example
  rows or blank/invented cells.

A passing partial lint never represents full acceptance; medical judgment and
native-Word checks stay explicitly deferred.  Coverage truth is always the
template ``node_tree.json``; file presence in shared directories is asserted as
a superset only, and other batches' files never affect the batch-scoped tests.
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
BATCH_PATH = REPO_ROOT / "tests/fixtures/protocol_v3/chapter_content_v2/batch8.json"
ALL_BATCH_PATHS = [
    REPO_ROOT / f"tests/fixtures/protocol_v3/chapter_content_v2/batch{index}.json"
    for index in range(1, 9)
]
ASSEMBLY_SCRIPT = REPO_ROOT / "scripts/qc/protocol_v3/assemble_chapter_registry.py"
TEMPLATE_ID = "tp_ma_07_v2"
TEMPLATE_SHA256 = "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"

#: Sections 14–16 carriers with their derived coverage roles (node_tree truth).
EXPECTED_CARRIERS = {
    "v2_n_14_1": "heading_leaf",
    "v2_n_14_2": "heading_leaf",
    "v2_n_14_3": "heading_leaf",
    "v2_n_14_4": "heading_leaf",
    "v2_n_14_5": "heading_leaf",
    "v2_n_14_6": "heading_leaf",
    "v2_n_14_7": "heading_leaf",
    "v2_n_15": "heading_leaf",
    "v2_n_16": "heading_only_aggregation",
    "v2_n_16_x1": "outline_only_leaf",
    "v2_n_16_x2": "outline_only_leaf",
    "v2_n_16_x3": "outline_only_leaf",
}

#: Exact source body-child window each carrier is bound to.  The first value is
#: the heading's own body_child_index, the last is the final content paragraph.
SOURCE_WINDOWS = {
    "v2_n_14_1": (884, 885),
    "v2_n_14_2": (886, 891),
    "v2_n_14_3": (892, 900),
    "v2_n_14_4": (901, 909),
    "v2_n_14_5": (910, 911),
    "v2_n_14_6": (912, 915),
    "v2_n_14_7": (916, 921),
    "v2_n_15": (926, 969),
    "v2_n_16": (970, 972),
    "v2_n_16_x3": (981, 995),
}

#: Caption-only appendix leaves: heading body_child_index -> owned table index.
APPENDIX_TABLE_NODES = {
    "v2_n_16_x1": (973, 974, "附录 1 ECOG体力评分"),
    "v2_n_16_x2": (977, 978, "附录 2 纽约心脏学会（NYHA）心功能分级"),
}

TITLES = {
    "v2_n_14_1": "质量源于设计与风险管理",
    "v2_n_14_2": "对申办者的要求",
    "v2_n_14_3": "申办者或其代表委派的监查员职责",
    "v2_n_14_4": "对研究者的要求",
    "v2_n_14_5": "稽查和视察",
    "v2_n_14_6": "方案偏离",
    "v2_n_14_7": "安全性监督",
    "v2_n_15": "参考文献",
    "v2_n_16": "附录",
    "v2_n_16_x1": "附录 1 ECOG体力评分",
    "v2_n_16_x2": "附录 2 纽约心脏学会（NYHA）心功能分级",
    "v2_n_16_x3": "附录 3 中心实验室信息和样本销毁公司信息",
}

#: The missing-genuine-obligation family chosen per node.
MISSING_FAMILY = {
    "v2_n_14_1": "missing_control",
    "v2_n_14_2": "missing_control",
    "v2_n_14_3": "missing_control",
    "v2_n_14_4": "missing_control",
    "v2_n_14_5": "missing_control",
    "v2_n_14_6": "missing_control",
    "v2_n_14_7": "missing_control",
    "v2_n_15": "missing_claim",
    "v2_n_16": "missing_claim",
    "v2_n_16_x1": "missing_control",
    "v2_n_16_x2": "missing_control",
    "v2_n_16_x3": "missing_control",
}

#: The content-spec negative each node's batch must exercise, and the exact
#: deterministic error code that proves it failed for its named reason.
NAMED_NEGATIVES = {
    "v2_n_14_1": ("generic-ctq-slogan", "forbidden_claim_present"),
    "v2_n_14_2": ("inferred-completed-training", "forbidden_claim_present"),
    "v2_n_14_3": ("universal-source-verification-promise", "forbidden_claim_present"),
    "v2_n_14_4": ("inferred-completed-training", "forbidden_claim_present"),
    "v2_n_14_5": ("tp-ma-15-title-as-integrated-content", "forbidden_claim_present"),
    "v2_n_14_6": ("urgent-hazard-blanket-waiver", "forbidden_claim_present"),
    "v2_n_14_7": ("incompatible-committee-roles", "forbidden_claim_present"),
    "v2_n_15": ("template-example-bibliography", "forbidden_claim_present"),
    "v2_n_16": ("placeholder-appendix-included", "forbidden_claim_present"),
    "v2_n_16_x1": ("ecog-appendix-without-assessment", "forbidden_claim_present"),
    "v2_n_16_x2": ("nyha-appendix-unverified-version", "forbidden_claim_present"),
    "v2_n_16_x3": ("template-example-supplier", "forbidden_fact_present"),
}

#: Additional source-specific negatives the content spec names explicitly,
#: each keyed ``<node>:<suffix>`` with the exact codes it must fail for.
SOURCE_SPECIFIC_NEGATIVES = {
    "v2_n_14_1:placeholder-plan-name": ("forbidden_fact_present",),
    "v2_n_14_2:inferred-signed-acceptance": ("forbidden_claim_present",),
    "v2_n_14_3:copied-company-name": ("forbidden_fact_present",),
    "v2_n_14_3:inferred-completed-training": ("forbidden_claim_present",),
    "v2_n_14_4:inferred-signed-acceptance": ("forbidden_claim_present",),
    "v2_n_14_5:audit-inspection-conflated": ("forbidden_claim_present",),
    "v2_n_14_6:important-deviation-undefined": ("missing_required_fact",),
    "v2_n_14_7:fabricated-membership-and-approval": ("forbidden_claim_present",),
    "v2_n_15:in-text-citation-without-target": ("forbidden_claim_present",),
    "v2_n_16:container-replaces-outline-leaves": ("forbidden_claim_present",),
    "v2_n_16_x1:ecog-appendix-unverified-version": ("forbidden_claim_present",),
    "v2_n_16_x2:nyha-appendix-without-assessment": ("forbidden_claim_present",),
    "v2_n_16_x3:blank-provider-fields": ("missing_required_fact",),
    "v2_n_16_x3:invented-provider-content": ("forbidden_claim_present",),
}

#: Fresh-review D1/D2 (batch8): formerly-unexercised forbidden obligations now
#: proven by extending their near-neighbour negatives; expected codes added here.
EXTENDED_NEGATIVE_EXTRA_CODES = {
    "v2_n_15:template-example-bibliography": ("forbidden_fact_present",),
    "v2_n_14_7:incompatible-committee-roles": (),  # extra claim exercised, code already forbidden_claim_present
    "v2_n_16_x1:ecog-appendix-without-assessment": ("forbidden_fact_present",),
    "v2_n_16_x2:nyha-appendix-without-assessment": ("forbidden_fact_present",),
    "v2_n_16_x3:template-example-supplier": (),
}

#: Positive fixtures whose forbidden-material failure is their named reason.
ALLOWED_FORBIDDEN_FIXTURE_IDS = {
    f"fixture:batch8:{node_id.replace('_', '-')}:{suffix}"
    for node_id, (suffix, code) in NAMED_NEGATIVES.items()
    if code.startswith("forbidden")
} | {
    f"fixture:batch8:{key.split(':', 1)[0].replace('_', '-')}:{key.split(':', 1)[1]}"
    for key, codes in SOURCE_SPECIFIC_NEGATIVES.items()
    if any(code.startswith("forbidden") for code in codes)
}

#: Conditional rules exercised by the active positive fixture of each node.
CONDITIONAL_POSITIVE_EXPECTATIONS = {
    "v2_n_14_1": (
        "quality.risk_management_plan_applicable",
        ("quality.risk_management_plan_identity", "quality.plan_review_cadence"),
    ),
    "v2_n_14_3": (
        "quality.remote_monitoring_applicable",
        ("quality.remote_monitoring_records",),
    ),
    "v2_n_14_7": (
        "quality.oversight_charter_applicable",
        ("quality.oversight_charter_version", "quality.oversight_charter_approval_record"),
    ),
    "v2_n_15": (
        "references.foreign_sources_present",
        ("references.foreign_format_style",),
    ),
}

#: Appendix leaves whose conditional rules carry when-active obligations.
CONDITIONAL_APPENDIX_NODES = {
    "v2_n_16_x1": (
        "appendix.ecog_assessment_applicable",
        (
            "appendix.ecog_version",
            "appendix.ecog_source_reference",
            "appendix.ecog_scale_reproduced",
        ),
        "appendix.ecog_version_and_contents_verified",
    ),
    "v2_n_16_x2": (
        "appendix.nyha_assessment_applicable",
        (
            "appendix.nyha_version",
            "appendix.nyha_source_reference",
            "appendix.nyha_classification_reproduced",
        ),
        "appendix.nyha_version_and_contents_verified",
    ),
}

#: New batch8 fact roots that require an explicit ownership declaration.
OWNED_FACT_ROOTS = ("quality.", "references.", "appendix.")

#: Independently required appendix sources that must keep separate evidence
#: floors (ANY-of inside one group, never merged into one floor).
SEPARATE_EVIDENCE_GROUPS = {
    "v2_n_15": [
        {"study_bibliography_from_used_sources"},
        {"citations_resolvable"},
    ],
    "v2_n_16_x3": [
        {"appendix.laboratory_identity_and_roles"},
        {"appendix.destruction_provider_identity_and_roles"},
    ],
}


def _load_assembly_module():
    spec = importlib.util.spec_from_file_location(
        "assemble_chapter_registry", ASSEMBLY_SCRIPT
    )
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


def _fact_obligations(contract: ChapterContractV2) -> dict[str, str]:
    return {
        item.fact_path: item.obligation.value
        for item in contract.substantive_content.fact_requirements
    }


def _claim_obligations(contract: ChapterContractV2) -> dict[str, str]:
    return {
        item.claim_type: item.obligation.value
        for item in contract.substantive_content.claim_requirements
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


def _facts_of(fixture) -> dict[str, str]:
    return {
        fact.fact_path: fact.value or ""
        for fact in fixture.content.facts
        if fact.value is not None
    }


@pytest.fixture(scope="module")
def registry_payload() -> dict:
    module = _load_assembly_module()
    return module.assemble_registry(CONTRACTS_DIR, SKILLS_DIR, BATCH_PATH)


@pytest.fixture(scope="module")
def registry_document(registry_payload):
    return load_chapter_registry(registry_payload)


# ---------------------------------------------------------------------------
# Identity: authored contracts, skills and the derived template coverage.
# ---------------------------------------------------------------------------


def test_contract_and_skill_files_have_exact_batch_identities():
    assert set(EXPECTED_CARRIERS) <= {p.stem for p in CONTRACTS_DIR.glob("*.json")}
    assert set(EXPECTED_CARRIERS) <= {p.stem for p in SKILLS_DIR.glob("*.json")}
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
        assert skill["template_id"] == TEMPLATE_ID
        assert skill["template_sha256"] == TEMPLATE_SHA256
        assert "provider" not in skill and "model" not in skill
        assert skill["input_schema_ref"] == (
            "app.protocol_workflow.registries.chapters:ChapterSkillInput"
        )
        assert skill["output_schema_ref"] == (
            "app.protocol_workflow.registries.chapters:ChapterSkillOutput"
        )


def test_exact_twelve_carriers_and_derived_roles(registry_document):
    node_tree = json.loads(
        (REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8")
    )
    heading_leaves = {
        node["id"]
        for node in node_tree["heading_style_tree"]["nodes"]
        if node.get("is_leaf_heading")
    }
    outline_leaves = {
        node["id"]
        for node in node_tree["outlined_tree"]["nodes"]
        if node.get("is_leaf")
    }
    entries = {entry.node_id: entry for entry in registry_document.chapters}
    assert set(entries) == set(EXPECTED_CARRIERS)
    for node_id, role in EXPECTED_CARRIERS.items():
        assert entries[node_id].coverage_role == role, node_id
    for node_id in EXPECTED_CARRIERS:
        if node_id == "v2_n_16":
            assert node_id in heading_leaves and node_id not in outline_leaves
        elif node_id.startswith("v2_n_16_x"):
            assert node_id not in heading_leaves and node_id in outline_leaves
        else:
            assert node_id in heading_leaves and node_id in outline_leaves


def test_source_windows_titles_styles_and_bookmarks_come_from_node_tree():
    node_tree = json.loads(
        (REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8")
    )
    nodes = {node["id"]: node for node in node_tree["outlined_tree"]["nodes"]}
    for node_id, (first, last) in SOURCE_WINDOWS.items():
        node = nodes[node_id]
        assert node["title_zh"] == TITLES[node_id]
        assert node["body_child_index"] == first
        assert node["content_paragraph_indexes"]
        assert node["content_paragraph_indexes"][0] == first + 1
        assert max(node["content_paragraph_indexes"]) == last
        contract = _contract(node_id)
        if node["style_id"] is not None:
            assert contract.word_rules.required_styles == (node["style_id"],)
        else:
            assert contract.word_rules.required_styles == ()
        assert contract.word_rules.required_bookmarks == tuple(node["bookmarks"])


def test_appendix_leaf_identity_and_conditional_tables_come_from_node_tree():
    """x1/x2 are caption leaves with SEQ fields and owned tables; x3 has no
    heading style of its own, so its Word obligation is its bookmarks."""
    node_tree = json.loads(
        (REAL_TEMPLATE_DIR / "node_tree.json").read_text(encoding="utf-8")
    )
    outlined = {node["id"]: node for node in node_tree["outlined_tree"]["nodes"]}
    tables = {table["body_child_index"]: table for table in node_tree["tables"]}
    for node_id, (first, table_index, caption) in APPENDIX_TABLE_NODES.items():
        node = outlined[node_id]
        assert node["title_zh"] == TITLES[node_id]
        assert node["body_child_index"] == first
        assert node["content_paragraph_indexes"] == []
        assert node["field_kinds"] == ["SEQ"]
        table = tables[table_index]
        assert table["owner_node_id"] == node_id
        assert table["caption"] == caption
        contract = _contract(node_id)
        assert contract.word_rules.required_styles == (node["style_id"],)
        assert contract.word_rules.required_bookmarks == tuple(node["bookmarks"])
        rule = next(iter(contract.conditional_applicability_rules))
        assert "table" in {
            item.value for item in rule.required_when_active_structural_objects
        }
    x3 = outlined["v2_n_16_x3"]
    assert x3["style_id"] is None
    contract = _contract("v2_n_16_x3")
    assert contract.word_rules.required_styles == ()
    assert contract.word_rules.required_bookmarks == tuple(x3["bookmarks"])
    assert contract.word_rules.required_bookmarks


def test_substantive_contracts_have_positive_forbidden_and_evidence_obligations(
    registry_document,
):
    for entry in registry_document.chapters:
        substantive = entry.contract.substantive_content
        required = [
            item
            for item in substantive.fact_requirements
            if item.obligation.value == "required"
        ] + [
            item
            for item in substantive.claim_requirements
            if item.obligation.value == "required"
        ]
        forbidden = [
            item
            for item in substantive.fact_requirements
            if item.obligation.value == "forbidden"
        ] + [
            item
            for item in substantive.claim_requirements
            if item.obligation.value == "forbidden"
        ]
        assert required, entry.node_id
        assert forbidden, entry.node_id
        assert substantive.evidence_source_requirements, entry.node_id
        assert substantive.skeleton_risk_rules, entry.node_id
        assert entry.contract.positive_qc_rules, entry.node_id
        assert entry.contract.ctq_items, entry.node_id
        for group in substantive.evidence_source_requirements:
            assert group.require_context_window is True, entry.node_id
            assert group.minimum_quality_score >= 0.9, entry.node_id
            assert group.allowed_locator_kinds, entry.node_id
            assert group.source_roles, entry.node_id


# ---------------------------------------------------------------------------
# Section 14 semantics: CtQ, responsibilities, audit/deviations, oversight.
# ---------------------------------------------------------------------------


def test_quality_risk_management_is_anchored_not_a_slogan():
    contract = _contract("v2_n_14_1")
    facts = _fact_obligations(contract)
    assert {
        "quality.critical_to_quality_factors",
        "quality.associated_risks",
        "quality.proportionate_controls",
        "quality.control_responsibility",
        "quality.decision_and_data_review_linkage",
    } <= set(facts)
    assert "quality.template_example_plan_name" in facts
    assert facts["quality.template_example_plan_name"] == "forbidden"
    claims = _claim_obligations(contract)
    assert claims["quality.ctq_risk_control_chain"] == "required"
    assert claims["ctq_generic_slogan_without_anchors"] == "forbidden"
    assert contract.ctq_items
    anchorable = set(facts) | {
        path
        for rule in contract.conditional_applicability_rules
        for path in (*rule.triggering_fact_paths, *rule.required_when_active_fact_paths)
    }
    for item in contract.ctq_items:
        assert item.linked_fact_paths or item.linked_claim_types
        assert set(item.linked_fact_paths) <= anchorable
        assert item.linked_claim_types
    rule = next(
        rule
        for rule in contract.conditional_applicability_rules
        if rule.conditional_applicability_rule_id == "applicability:n-14-1:risk-plan"
    )
    assert rule.triggering_fact_paths == ("quality.risk_management_plan_applicable",)
    assert "quality.risk_management_plan_identity" in rule.required_when_active_fact_paths
    assert facts["quality.risk_management_plan_applicable"] == "optional"
    qc_text = " ".join(rule.rule for rule in contract.positive_qc_rules)
    assert "口号" in qc_text and "锚点" in qc_text


def test_sponsor_monitor_investigator_responsibilities_stay_separate():
    sponsor = _contract("v2_n_14_2")
    monitor = _contract("v2_n_14_3")
    investigator = _contract("v2_n_14_4")
    assert {
        "quality.sponsor_conduct_responsibility",
        "quality.sponsor_oversight_and_delegation",
        "quality.sponsor_quality_system",
        "quality.sponsor_training_obligation_statement",
    } <= set(_fact_obligations(sponsor))
    assert {
        "sponsor_responsibility_matches_actual_arrangement",
    } <= set(_claim_obligations(sponsor))
    assert _claim_obligations(sponsor)["sponsor_training_inferred_complete"] == "forbidden"
    assert (
        _claim_obligations(sponsor)["sponsor_protocol_acceptance_inferred_signed"]
        == "forbidden"
    )
    assert {
        "quality.monitoring_scope_and_extent",
        "quality.monitoring_proportionate_approach",
        "quality.monitoring_methods",
        "quality.monitoring_findings_and_followup",
        "quality.monitoring_records",
    } <= set(_fact_obligations(monitor))
    assert (
        _claim_obligations(monitor)["universal_100_percent_source_verification_promised"]
        == "forbidden"
    )
    assert _fact_obligations(monitor)["quality.copied_template_company_name"] == "forbidden"
    assert {
        "quality.investigator_conduct_and_delegation",
        "quality.investigator_supervision",
        "quality.investigator_protocol_compliance",
        "quality.investigator_records",
    } <= set(_fact_obligations(investigator))
    assert (
        _claim_obligations(investigator)["investigator_training_inferred_complete"]
        == "forbidden"
    )
    # The three responsibility carriers keep disjoint fact ownership: a
    # sponsor-duty path never doubles as a monitor or investigator duty.
    sponsor_paths = set(_fact_obligations(sponsor))
    monitor_paths = set(_fact_obligations(monitor))
    investigator_paths = set(_fact_obligations(investigator))
    assert not sponsor_paths & monitor_paths
    assert not sponsor_paths & investigator_paths
    assert not monitor_paths & investigator_paths
    monitor_qc = " ".join(rule.rule for rule in monitor.positive_qc_rules)
    assert "比例" in monitor_qc or "相称" in monitor_qc
    assert "全覆盖" in monitor_qc


def test_audit_and_deviation_processes_are_distinct_with_provenance_pending():
    audit = _contract("v2_n_14_5")
    deviation = _contract("v2_n_14_6")
    assert {
        "quality.audit_program",
        "quality.audit_inspection_distinction",
        "quality.audit_records",
        "quality.inspection_access_and_notification",
    } <= set(_fact_obligations(audit))
    assert _claim_obligations(audit)["audit_inspection_processes_distinct"] == "required"
    assert (
        _claim_obligations(audit)["local_tp_ma_15_title_equals_integrated_content"]
        == "forbidden"
    )
    assert {
        "quality.deviation_process",
        "quality.deviation_records",
        "quality.deviation_impact_assessment",
        "quality.deviation_communication",
        "quality.important_deviation_definition",
        "quality.general_deviation_definition",
        "quality.urgent_hazard_exception_definition",
    } <= set(_fact_obligations(deviation))
    assert (
        _claim_obligations(deviation)["important_general_deviation_distinction"]
        == "required"
    )
    assert (
        _claim_obligations(deviation)["urgent_hazard_exception_blanket_waiver"]
        == "forbidden"
    )
    for contract in (audit, deviation):
        declaration = " ".join(
            contract.substantive_content.project_specific_elements
        )
        assert "TP-MA-15" in declaration
        assert "待验证" in declaration
        assert "provenance pending" in declaration


def test_safety_oversight_roles_are_not_interchangeable():
    contract = _contract("v2_n_14_7")
    facts = _fact_obligations(contract)
    assert {
        "quality.safety_oversight_body_type",
        "quality.safety_oversight_composition",
        "quality.safety_oversight_roles",
        "quality.safety_oversight_information_flow",
        "quality.safety_oversight_review_arrangement",
        "quality.safety_escalation_path",
    } <= set(facts)
    claims = _claim_obligations(contract)
    assert claims["safety_oversight_actual_arrangement"] == "required"
    assert claims["oversight_body_type_and_role_stated"] == "required"
    assert set(claims) >= {
        "dsmb_smc_irc_interchangeable",
        "fabricated_committee_membership",
        "fabricated_approved_charter",
        "semiannual_cadence_as_universal_rule",
    }
    for forbidden in (
        "dsmb_smc_irc_interchangeable",
        "fabricated_committee_membership",
        "fabricated_approved_charter",
        "semiannual_cadence_as_universal_rule",
    ):
        assert claims[forbidden] == "forbidden"
    rule = next(
        rule
        for rule in contract.conditional_applicability_rules
        if rule.conditional_applicability_rule_id
        == "applicability:n-14-7:oversight-charter"
    )
    assert rule.triggering_fact_paths == ("quality.oversight_charter_applicable",)
    assert rule.required_when_active_fact_paths == ("quality.oversight_charter_status",)
    approved = next(r for r in contract.conditional_applicability_rules
                    if r.conditional_applicability_rule_id == "applicability:n-14-7:charter-approved")
    assert approved.triggering_fact_paths == (
        "quality.oversight_charter_applicable", "quality.oversight_charter_status",
    )
    assert "quality.oversight_charter_approval_record" in approved.required_when_active_fact_paths
    draft = next(r for r in contract.conditional_applicability_rules
                 if r.conditional_applicability_rule_id == "applicability:n-14-7:charter-draft")
    assert "quality.oversight_charter_approval_record" not in draft.required_when_active_fact_paths
    assert facts["quality.oversight_charter_applicable"] == "optional"


# ---------------------------------------------------------------------------
# Section 15: references generated from actually used sources.
# ---------------------------------------------------------------------------


def test_references_are_generated_from_actually_used_sources():
    contract = _contract("v2_n_15")
    facts = _fact_obligations(contract)
    assert {
        "references.used_source_register",
        "references.bibliographic_metadata",
        "references.citation_style",
        "references.in_text_citation_targets",
    } <= set(facts)
    assert facts["references.template_example_reference_list"] == "forbidden"
    claims = _claim_obligations(contract)
    assert claims["study_bibliography_from_used_sources"] == "required"
    assert claims["citations_resolvable"] == "required"
    for forbidden in (
        "template_example_bibliography_used_as_study_bibliography",
        "in_text_citation_without_target",
        "unused_reference_listed",
    ):
        assert claims[forbidden] == "forbidden"
    rule = next(
        rule
        for rule in contract.conditional_applicability_rules
        if rule.conditional_applicability_rule_id == "applicability:n-15:foreign-style"
    )
    assert rule.triggering_fact_paths == ("references.foreign_sources_present",)
    assert facts["references.foreign_sources_present"] == "optional"
    qc_text = " ".join(rule.rule for rule in contract.positive_qc_rules)
    assert "实际使用" in qc_text
    assert "示例" in qc_text


def test_independently_required_sources_keep_separate_evidence_groups():
    for node_id, expected in SEPARATE_EVIDENCE_GROUPS.items():
        contract = _contract(node_id)
        admissions = [
            set(group.admission_claim_types)
            for group in contract.substantive_content.evidence_source_requirements
        ]
        assert admissions == expected, node_id


# ---------------------------------------------------------------------------
# Section 16: appendix container, conditional score appendices, providers.
# ---------------------------------------------------------------------------


def test_appendix_container_preserves_outline_leaf_obligations():
    container = _contract("v2_n_16")
    facts = _fact_obligations(container)
    assert {
        "appendix.applicable_attachment_index",
        "appendix.inclusion_decision_basis",
        "appendix.container_aggregation_scope",
    } <= set(facts)
    claims = _claim_obligations(container)
    assert claims["appendix_aggregates_actual_applicable_attachments"] == "required"
    assert claims["container_preserves_outlined_leaf_obligations"] == "required"
    assert (
        claims["appendix_placeholder_or_template_example_included_as_final"]
        == "forbidden"
    )
    assert claims["container_replaces_outlined_leaf_obligations"] == "forbidden"
    # The heading-only container and the three outline leaves are separate
    # carriers with their own contracts; the container never consumes them.
    for leaf in ("v2_n_16_x1", "v2_n_16_x2", "v2_n_16_x3"):
        assert _contract(leaf).semantic_node_id == leaf
    container_paths = set(facts)
    leaf_paths = set(_fact_obligations(_contract("v2_n_16_x1"))) | set(
        _fact_obligations(_contract("v2_n_16_x2"))
    ) | set(_fact_obligations(_contract("v2_n_16_x3")))
    assert not container_paths & leaf_paths


def test_score_appendices_are_conditional_on_actual_assessments():
    for node_id, (trigger, when_active, active_claim) in (
        CONDITIONAL_APPENDIX_NODES.items()
    ):
        contract = _contract(node_id)
        facts = _fact_obligations(contract)
        assert facts[trigger] == "optional"
        for path in when_active:
            assert facts[path] == "optional"
        assert _claim_obligations(contract)[active_claim] == "allowed"
        rule = next(
            rule
            for rule in contract.conditional_applicability_rules
            if rule.conditional_applicability_rule_id
            == f"applicability:{node_id.replace('_', '-')}:assessment"
        )
        assert rule.triggering_fact_paths == (trigger,)
        assert set(rule.required_when_active_fact_paths) == set(when_active)
        assert active_claim in rule.required_when_active_claim_types
        assert "table" in {
            item.value for item in rule.required_when_active_structural_objects
        }
        claims = _claim_obligations(contract)
        assert any(
            claim.endswith("_appendix_without_actual_assessment")
            and obligation == "forbidden"
            for claim, obligation in claims.items()
        ), node_id


def test_laboratory_and_destruction_provider_identity_is_actual():
    contract = _contract("v2_n_16_x3")
    facts = _fact_obligations(contract)
    assert {
        "appendix.laboratory_name",
        "appendix.laboratory_identifying_details",
        "appendix.laboratory_roles_and_scope",
        "appendix.destruction_provider_name",
        "appendix.destruction_provider_identifying_details",
        "appendix.destruction_provider_roles",
    } <= set(facts)
    assert facts["appendix.template_example_supplier_row"] == "forbidden"
    claims = _claim_obligations(contract)
    assert claims["appendix.laboratory_identity_and_roles"] == "required"
    assert claims["appendix.destruction_provider_identity_and_roles"] == "required"
    assert (
        claims["template_example_lab_or_destruction_company_as_project_supplier"]
        == "forbidden"
    )
    assert claims["blank_or_invented_supplier_content"] == "forbidden"


# ---------------------------------------------------------------------------
# Accumulated precedents: conditional declarations, ownership, vocabulary.
# ---------------------------------------------------------------------------


def test_conditional_rules_reference_only_declared_fact_paths():
    for node_id in EXPECTED_CARRIERS:
        contract = _contract(node_id)
        declared = set(_fact_obligations(contract))
        for rule in contract.conditional_applicability_rules:
            referenced = set(rule.triggering_fact_paths) | set(
                rule.required_when_active_fact_paths
            )
            assert referenced <= declared, (node_id, rule.conditional_applicability_rule_id)


def test_new_fact_roots_carry_ownership_declarations():
    for node_id in EXPECTED_CARRIERS:
        contract = _contract(node_id)
        elements = contract.substantive_content.project_specific_elements
        used_roots = {
            root
            for root in OWNED_FACT_ROOTS
            if any(item.fact_path.startswith(root) for item in
                   contract.substantive_content.fact_requirements)
        }
        assert used_roots, node_id
        for root in used_roots:
            assert any(
                root in element
                and "共享事实命名空间" in element
                and "StudyDefinition" in element
                and "第二可编辑存储" in element
                for element in elements
            ), (node_id, root)


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


def test_batch8_terminology_is_participant_safe():
    paths = [BATCH_PATH]
    paths.extend(CONTRACTS_DIR / f"{node_id}.json" for node_id in EXPECTED_CARRIERS)
    paths.extend(SKILLS_DIR / f"{node_id}.json" for node_id in EXPECTED_CARRIERS)
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "试验参与者" in text, path.name
        assert "受试者" not in text, path.name


# ---------------------------------------------------------------------------
# Fixtures: families, named defects, synthetic markers, bare booleans.
# ---------------------------------------------------------------------------


def test_fixture_families_and_named_defects(registry_document):
    by_node = _fixtures_by_node(registry_document)
    assert set(by_node) == set(EXPECTED_CARRIERS)
    total = 0
    for node_id, kinds in by_node.items():
        assert {"positive", "wrong_source", "skeleton"} <= set(kinds), node_id
        assert kinds.get("missing_claim") or kinds.get("missing_control"), node_id
        for fixture in kinds["positive"]:
            result = check_fixture(registry_document, fixture)
            assert result.passed is True, fixture.fixture_id
            assert not _error_codes(result), fixture.fixture_id
            assert result.deferred_qc_obligations
        suffix, expected_code = NAMED_NEGATIVES[node_id]
        named = check_fixture(registry_document, _fixture(registry_document, node_id, suffix))
        assert named.passed is False, node_id
        assert expected_code in _error_codes(named), (node_id, _error_codes(named))
        wrong = check_fixture(registry_document, kinds["wrong_source"][0])
        assert "wrong_source_role" in _error_codes(wrong), node_id
        skeleton = check_fixture(registry_document, kinds["skeleton"][0])
        assert "skeleton_content" in _error_codes(skeleton), node_id
        for fixture_group in kinds.values():
            for fixture in fixture_group:
                if fixture.fixture_kind == "positive":
                    continue
                assert check_fixture(registry_document, fixture).passed is False, (
                    node_id,
                    fixture.fixture_id,
                )
        total += sum(len(group) for group in kinds.values())
    assert total >= 48
    assert total == len(registry_document.fixtures)


def test_source_specific_negatives_fail_for_their_named_reason(registry_document):
    for key, expected_codes in SOURCE_SPECIFIC_NEGATIVES.items():
        node_id, suffix = key.split(":", 1)
        fixture = _fixture(registry_document, node_id, suffix)
        result = check_fixture(registry_document, fixture)
        assert result.passed is False, key
        assert set(expected_codes) <= _error_codes(result), (key, _error_codes(result))
    # Fresh-review D1: extended negatives prove their newly carried forbidden
    # obligations in addition to their original named reason.
    for key, extra_codes in EXTENDED_NEGATIVE_EXTRA_CODES.items():
        if not extra_codes:
            continue
        node_id, suffix = key.split(":", 1)
        result = check_fixture(registry_document, _fixture(registry_document, node_id, suffix))
        assert set(extra_codes) <= _error_codes(result), (key, _error_codes(result))


def test_negative_fixtures_carry_no_forbidden_material_outside_named_exceptions(
    registry_document,
):
    forbidden_codes = {"forbidden_fact_present", "forbidden_claim_present"}
    for fixture in registry_document.fixtures:
        if fixture.fixture_kind == "positive":
            continue
        result = check_fixture(registry_document, fixture)
        assert result.passed is False, fixture.fixture_id
        if fixture.fixture_id in ALLOWED_FORBIDDEN_FIXTURE_IDS:
            assert _error_codes(result) & forbidden_codes, fixture.fixture_id
            continue
        assert not (_error_codes(result) & forbidden_codes), fixture.fixture_id


def test_synthetic_markers_and_bare_boolean_triggers(registry_document):
    for node_id in EXPECTED_CARRIERS:
        for path in (
            CONTRACTS_DIR / f"{node_id}.json",
            SKILLS_DIR / f"{node_id}.json",
        ):
            text = path.read_text(encoding="utf-8")
            assert "合成" in text or "示例" in text, path.name
    for fixture in registry_document.fixtures:
        for fact in fixture.content.facts:
            if fact.fact_path.endswith("_applicable") and fact.value is not None:
                assert fact.value in {"true", "false"}, (fixture.fixture_id, fact.value)
        for fact in fixture.content.facts:
            if fact.value is not None and fact.value not in {"true", "false"}:
                assert "合成" in fact.value, (fixture.fixture_id, fact.fact_path)
        for claim in fixture.content.claims:
            if claim.statement is not None:
                assert "合成" in claim.statement, (fixture.fixture_id, claim.claim_type)


def test_fixture_ids_follow_the_batch8_convention(registry_document):
    ids = {fixture.fixture_id for fixture in registry_document.fixtures}
    for node_id in EXPECTED_CARRIERS:
        slug = node_id.replace("_", "-")
        assert f"fixture:batch8:{slug}:positive" in ids, node_id
        assert f"fixture:batch8:{slug}:wrong-source" in ids, node_id
        assert f"fixture:batch8:{slug}:skeleton" in ids, node_id
        missing = MISSING_FAMILY[node_id].replace("_", "-")
        assert f"fixture:batch8:{slug}:{missing}" in ids, node_id
        suffix, _ = NAMED_NEGATIVES[node_id]
        assert f"fixture:batch8:{slug}:{suffix}" in ids, node_id
    assert all(identifier.startswith("fixture:batch8:") for identifier in ids)


def test_positive_fixtures_exercise_conditional_paths(registry_document):
    for node_id, (trigger, when_active) in CONDITIONAL_POSITIVE_EXPECTATIONS.items():
        fixture = _fixture(registry_document, node_id, "positive")
        facts = _facts_of(fixture)
        assert facts[trigger] == "true", node_id
        for path in when_active:
            assert facts.get(path, "").strip(), (node_id, path)
    for node_id, (trigger, when_active, active_claim) in (
        CONDITIONAL_APPENDIX_NODES.items()
    ):
        active = _fixture(registry_document, node_id, "positive")
        active_facts = _facts_of(active)
        assert active_facts[trigger] == "true", node_id
        for path in when_active:
            assert active_facts.get(path, "").strip(), (node_id, path)
        assert active_claim in {
            claim.claim_type
            for claim in active.content.claims
            if (claim.statement or "").strip()
        }
        assert any(
            obj.object_kind.value == "table" and obj.is_material()
            for obj in active.content.objects
        ), node_id
        inactive = _fixture(registry_document, node_id, "conditional-inactive")
        assert inactive.fixture_kind == "positive"
        result = check_fixture(registry_document, inactive)
        assert result.passed is True, node_id
        inactive_facts = _facts_of(inactive)
        assert inactive_facts[trigger] == "false", node_id
        for path in when_active:
            assert not inactive_facts.get(path, "").strip(), (node_id, path)
        assert not any(obj.object_kind.value == "table" for obj in inactive.content.objects)


def test_checker_ignores_supplied_verdicts(registry_document):
    """Deterministic checking never consults self-reported verdicts."""
    fixture = _fixture(registry_document, "v2_n_15", "positive")
    assert fixture.supplied_passed is False
    result = check_fixture(registry_document, fixture)
    assert result.passed is True
    assert result.ignored_supplied_verdict is True


# ---------------------------------------------------------------------------
# Lint: partial batch is clean but incomplete; all eight batches complete.
# ---------------------------------------------------------------------------


def test_partial_lint_is_clean_but_incomplete(registry_document):
    report = lint_registry(REAL_TEMPLATE_DIR, registry_document, require_complete=False)
    assert report.mode == "partial"
    assert report.status == "incomplete"
    assert report.errors() == ()
    codes = {finding.code for finding in report.findings}
    assert "partial_mode_not_full_acceptance" in codes
    assert report.coverage.covered_carrier_count == 12
    assert "v2_n_1_1" in report.coverage.missing_node_ids
    assert "v2_n_14_1" not in report.coverage.missing_node_ids
    assert len(report.fixture_results) == len(registry_document.fixtures)


def test_all_eight_batches_leave_no_missing_coverage_of_111():
    """Final-batch integration check: assembling every accepted batch slice
    leaves zero missing carriers out of the 111 expected by the template."""
    module = _load_assembly_module()
    payload = module.assemble_registries(CONTRACTS_DIR, SKILLS_DIR, ALL_BATCH_PATHS)
    document = load_chapter_registry(payload)
    assert len(document.chapters) == 111
    report = lint_registry(REAL_TEMPLATE_DIR, document, require_complete=True)
    assert report.mode == "full"
    assert report.coverage.expected_carrier_count == 111
    assert report.coverage.covered_carrier_count == 111
    assert report.coverage.missing_node_ids == ()
    assert report.errors() == ()
    assert report.status == "complete"


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
    registry_file = tmp_path / "batch8_registry.json"
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
