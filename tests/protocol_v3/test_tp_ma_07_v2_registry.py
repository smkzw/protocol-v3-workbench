"""Task 3R.1: TP-MA-07 v2 candidate registry and explicit legacy mapping.

Source-bound tests only. The DOCX source stays read-only; the legacy module is
parsed with AST and never imported. Candidate artifacts carry no current
designation; promotion belongs to Codex plus an independent fresh reviewer.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py"
DEFAULT_OUT = ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
EXPECTED_SHA = "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
ARTIFACT_NAMES = ("template.json", "node_tree.json", "v1_to_v2_mapping.json")

DISPOSITIONS = {
    "mapped_to_v2",
    "split",
    "merged",
    "retired",
    "nonapplicable_phase1",
}
REVERSE_DISPOSITIONS = {"from_v1", "new_in_v2", "mixed"}


def module():
    spec = importlib.util.spec_from_file_location(
        "extract_tp_ma_07_v2_registry", SCRIPT_PATH
    )
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture(scope="session")
def regenerated(tmp_path_factory):
    out = tmp_path_factory.mktemp("tp_ma_07_v2_regen")
    module().build_all(out)
    return out


@pytest.fixture(scope="session")
def docs(regenerated):
    return {
        name: json.loads((regenerated / name).read_text(encoding="utf-8"))
        for name in ARTIFACT_NAMES
    }


# ---------------------------------------------------------------------------
# Source gate and determinism
# ---------------------------------------------------------------------------


def test_source_hash_gate_rejects_modified_source(tmp_path):
    m = module()
    fake = tmp_path / "not_the_source.docx"
    fake.write_bytes(b"definitely not a docx")
    with pytest.raises(m.RegistrySourceError, match="hash mismatch"):
        m.verify_source_hash(fake)


def test_source_hash_constant_matches_authorized_docx():
    assert module().verify_source_hash(module().SOURCE_DOCX_PATH) == EXPECTED_SHA


def test_regeneration_is_byte_identical(tmp_path):
    m = module()
    first, second = tmp_path / "a", tmp_path / "b"
    m.build_all(first)
    m.build_all(second)
    for name in ARTIFACT_NAMES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_committed_artifacts_match_source_bound_regeneration(regenerated):
    for name in ARTIFACT_NAMES:
        committed = (DEFAULT_OUT / name).read_bytes()
        assert committed, name
        assert hashlib.sha256(committed).hexdigest(), name
        assert committed == (regenerated / name).read_bytes(), name


def test_candidate_outputs_carry_no_volatile_fields(regenerated):
    for name in ARTIFACT_NAMES:
        raw = (regenerated / name).read_text(encoding="utf-8")
        for token in ("created_at", "timestamp", "/tmp", "/var/folders"):
            assert token not in raw, (name, token)


# ---------------------------------------------------------------------------
# Authoritative counts and terminology
# ---------------------------------------------------------------------------


def test_template_declares_candidate_status_and_promotion_gate(docs):
    template = docs["template.json"]
    assert template["template_id"] == "tp_ma_07_v2"
    assert template["candidate_status"] == "candidate_not_current"
    assert template["promotion_requirements"]
    assert template["source"]["sha256"] == EXPECTED_SHA


def test_authoritative_counts_match_preflight_metrics(docs):
    counts = docs["template.json"]["authoritative_counts"]
    assert counts["direct_body_paragraphs"] == 940
    assert counts["heading_style_nodes"] == 135
    assert counts["heading_style_leaves"] == 106
    assert counts["outlined_nodes"] == 139
    assert counts["outlined_leaves"] == 109
    assert counts["top_level_tables"] == 17
    assert counts["recursive_tables"] == 18
    assert counts["sections"] == 8
    assert counts["tracked_changes"] == 0


def test_terminology_counts_use_explicit_scopes(docs):
    terminology = docs["template.json"]["terminology"]
    assert terminology["试验参与者"]["direct_body_paragraphs"] == 218
    assert terminology["试验参与者"]["top_level_tables"] == 22
    assert terminology["试验参与者"]["all_document_text"] == 240
    assert terminology["受试者"]["all_document_text"] == 0


def test_new_registry_text_contains_no_obsolete_term(docs):
    tree = docs["node_tree.json"]
    mapping = docs["v1_to_v2_mapping.json"]
    for node in tree["outlined_tree"]["nodes"]:
        assert "受试者" not in node["title_zh"]
    for entry in mapping["reverse_mapping"]:
        assert "受试者" not in entry["rationale"]
    raw = json.dumps(tree, ensure_ascii=False)
    assert "试验参与者招募与保留" in raw
    assert "可疑非预期严重不良反应" in raw


# ---------------------------------------------------------------------------
# Node tree invariants
# ---------------------------------------------------------------------------


def test_node_ids_unique_and_parent_links_resolve(docs):
    tree = docs["node_tree.json"]["outlined_tree"]["nodes"]
    ids = [node["id"] for node in tree]
    assert len(ids) == len(set(ids))
    known = set(ids) | {""}
    for node in tree:
        assert node["parent_id"] in known, node["id"]
    by_id = {node["id"]: node for node in tree}
    for node in tree:
        parent = by_id.get(node["parent_id"])
        if parent is not None:
            assert parent["order"] < node["order"], node["id"]


def test_heading_style_tree_is_subset_with_exact_counts(docs):
    data = docs["node_tree.json"]
    heading = data["heading_style_tree"]["nodes"]
    outlined = data["outlined_tree"]["nodes"]
    assert len(heading) == 135
    assert len(outlined) == 139
    heading_ids = {node["id"] for node in heading}
    outlined_ids = {node["id"] for node in outlined}
    assert heading_ids <= outlined_ids
    extras = outlined_ids - heading_ids
    assert extras == {"v2_n_front_5", "v2_n_16_x1", "v2_n_16_x2", "v2_n_16_x3"}


def test_normal_outlined_captions_preserved_with_locators(docs):
    tree = docs["node_tree.json"]["outlined_tree"]["nodes"]
    by_id = {node["id"]: node for node in tree}
    for node_id, expect in (
        ("v2_n_front_5", "缩略语表"),
        ("v2_n_16_x1", "附录 1"),
        ("v2_n_16_x2", "附录 2"),
        ("v2_n_16_x3", "附录 3"),
    ):
        node = by_id[node_id]
        assert not node["in_heading_style_tree"]
        assert node["title_zh"].startswith(expect)
        assert "body_child_index" in node


def test_unheaded_content_and_semantic_objects_recorded(docs):
    tree = docs["node_tree.json"]
    by_id = {node["id"]: node for node in tree["outlined_tree"]["nodes"]}
    pharmacology = by_id["v2_n_2_2_2_1"]["content_paragraph_indexes"]
    assert pharmacology, "药效学研究下未标题内容（毒理/药代/一般药理）必须可见"
    findings = {finding["id"]: finding for finding in tree["semantic_findings"]}
    assert "estimand_fifth_attribute_tail_content" in findings
    assert findings["estimand_fifth_attribute_tail_content"]["body_child_indexes"]
    assert "unheaded_preclinical_content" in findings
    assert findings["unheaded_preclinical_content"]["body_child_indexes"]
    assert findings["example_labeled_content"]["body_child_indexes"]
    front = tree["front_block"]
    assert front["body_child_index_range"] == [0, 44]
    assert front["content_paragraph_indexes"]


def test_blank_outlined_exclusions_keep_locators(docs):
    excluded = docs["node_tree.json"]["excluded_blank_outlined"]
    assert len(excluded) == 4
    assert all("body_child_index" in item for item in excluded)


def test_tables_and_sections_carry_owner_and_locator(docs):
    tree = docs["node_tree.json"]
    tables = tree["tables"]
    assert len(tables) == 17
    assert sum(item["nested_table_count"] for item in tables) == 1
    owners = {item["owner_node_id"] for item in tables}
    outlined_ids = {node["id"] for node in tree["outlined_tree"]["nodes"]}
    assert owners <= outlined_ids
    synopsis_table = [t for t in tables if t["nested_table_count"] == 1]
    assert synopsis_table[0]["owner_node_id"] == "v2_n_1_1"
    sections = tree["sections"]
    assert len(sections) == 8
    assert sections[-1]["holder"] == "body-final"


def test_bookmark_and_field_inventories_recorded(docs):
    tree = docs["node_tree.json"]
    assert tree["bookmark_inventory"]["total"] == 314
    assert tree["bookmark_inventory"]["toc_anchored"] == 264
    fields = tree["field_inventory"]
    assert fields["TOC"] == 2
    assert fields["PAGEREF"] == 134
    assert fields["HYPERLINK"] == 136


# ---------------------------------------------------------------------------
# Legacy inventory via AST (no import of the legacy module)
# ---------------------------------------------------------------------------


def test_legacy_inventory_matches_actual_module_identity(docs):
    inventory = docs["v1_to_v2_mapping.json"]["legacy_inventory"]
    assert inventory["chapter_row_count"] == 124
    assert inventory["chapter_row_leaves"] == 103
    assert inventory["node_count"] == 130
    assert inventory["leaf_count"] == 109
    assert inventory["front_node_count"] == 6
    assert inventory["phase1_leaf_count"] == 7


def test_legacy_ids_remain_literal(docs):
    mapping = docs["v1_to_v2_mapping.json"]
    nodes = mapping["legacy_inventory"]["nodes"]
    assert all(node["node_id"].startswith("cms_") for node in nodes)
    by_semantic = {node["semantic_node_id"]: node for node in nodes}
    assert by_semantic["document_control.front_matter"]["node_id"] == "cms_front_matter"
    assert by_semantic["synopsis.summary"]["node_id"] == "cms_synopsis_summary"
    assert by_semantic["appendices.project_specific"]["title_zh"] == "项目特异附录"


# ---------------------------------------------------------------------------
# Two-way explicit mapping
# ---------------------------------------------------------------------------


def test_every_legacy_leaf_has_explicit_disposition(docs):
    mapping = docs["v1_to_v2_mapping.json"]
    forward = {entry["semantic_node_id"]: entry for entry in mapping["forward_mapping"]}
    leaves = [node for node in mapping["legacy_inventory"]["nodes"] if node["is_leaf"]]
    assert len(leaves) == 109
    for node in leaves:
        entry = forward[node["semantic_node_id"]]
        assert entry["disposition"] in DISPOSITIONS, node["semantic_node_id"]
        if entry["disposition"] in {"retired", "nonapplicable_phase1"}:
            assert entry["rationale"].strip(), node["semantic_node_id"]
        if entry["disposition"] in {"mapped_to_v2", "split", "merged"}:
            assert entry["target_v2_node_ids"], node["semantic_node_id"]


def test_phase1_leaves_retain_historical_identity(docs):
    mapping = docs["v1_to_v2_mapping.json"]
    forward = {entry["semantic_node_id"]: entry for entry in mapping["forward_mapping"]}
    phase1 = [
        (node["semantic_node_id"], forward[node["semantic_node_id"]])
        for node in mapping["legacy_inventory"]["nodes"]
        if node["is_leaf"]
        and forward[node["semantic_node_id"]]["disposition"] == "nonapplicable_phase1"
    ]
    assert len(phase1) == 7
    for semantic_id, entry in phase1:
        assert entry["phase1_identity_retained"] is True
        assert entry["node_id"].startswith("cms_")
        assert "Ⅰ期" in entry["rationale"] or "phase:1" in entry["conditional_rules"]


def test_every_v2_leaf_has_reverse_disposition(docs):
    tree = docs["node_tree.json"]
    mapping = docs["v1_to_v2_mapping.json"]
    reverse = {entry["v2_node_id"]: entry for entry in mapping["reverse_mapping"]}
    leaves = [node for node in tree["outlined_tree"]["nodes"] if node["is_leaf"]]
    assert len(leaves) == 109
    legacy_ids = {
        node["semantic_node_id"] for node in mapping["legacy_inventory"]["nodes"]
    }
    heading_leaf_ids = {
        node["id"] for node in tree["heading_style_tree"]["nodes"] if node["is_leaf_heading"]
    }
    for node_id in heading_leaf_ids | {node["id"] for node in leaves}:
        entry = reverse[node_id]
        assert entry["disposition"] in REVERSE_DISPOSITIONS, node_id
        assert entry["rationale"].strip(), node_id
        for semantic_id in entry.get("from_v1_semantic_ids", []):
            assert semantic_id in legacy_ids, (node_id, semantic_id)
        if entry["disposition"] == "new_in_v2":
            assert not entry.get("from_v1_semantic_ids")


def test_mapping_targets_exist_in_node_tree(docs):
    tree = docs["node_tree.json"]
    mapping = docs["v1_to_v2_mapping.json"]
    ids = {node["id"] for node in tree["outlined_tree"]["nodes"]} | {"v2_front_block"}
    for entry in mapping["forward_mapping"]:
        for target in entry["target_v2_node_ids"]:
            assert target in ids, (entry["semantic_node_id"], target)


# ---------------------------------------------------------------------------
# Conditional registrations and projection reconciliation
# ---------------------------------------------------------------------------


def test_financial_disclosure_conditional_default_not_applicable_with_reason(docs):
    conditional = docs["template.json"]["conditional_registrations"]
    financial = conditional["financial_disclosure"]
    assert financial["default"] == "not_applicable"
    assert financial["reason"].strip()
    assert financial["source_basis"].strip()


def test_management_structure_declares_joint_carrying(docs):
    conditional = docs["template.json"]["conditional_registrations"]
    management = conditional["management_structure"]
    assert len(management["carrying_v2_node_ids"]) >= 2
    assert management["declaration"].strip()
    ids = set(management["carrying_v2_node_ids"])
    assert {"v2_n_14_2", "v2_n_14_3", "v2_n_14_4"} <= ids


def test_projection_evidence_is_source_bound(docs):
    mapping = docs["v1_to_v2_mapping.json"]
    reconciliation = mapping["projection_reconciliation"]
    entries = reconciliation["leaves"]
    by_semantic = {entry["semantic_node_id"]: entry for entry in entries}
    explicit = [
        entry for entry in entries if entry["projection_status"] == "explicit_projection"
    ]
    assert explicit
    for entry in explicit:
        assert entry["evidence"], entry["semantic_node_id"]
        for item in entry["evidence"]:
            location = item["location"]
            assert location.startswith(
                "services/api/app/medical_writing_protocol_template.py:"
            )
            line = int(location.rsplit(":", 1)[1])
            assert 1 <= line <= 4000
    expected = module().count_explicit_projection_leaves()
    assert len(explicit) == expected
    assert by_semantic["synopsis.summary"]["projection_status"] == "explicit_projection"
    assert by_semantic["study_design.overall"]["projection_status"] == "explicit_projection"
    assert reconciliation["historical_claim"]


def test_candidate_findings_exclude_unverified_claims(docs):
    template = docs["template.json"]
    findings = {finding["id"]: finding for finding in template["candidate_findings"]}
    assert "projection_claim_76_not_accepted" in findings
    claim = findings["projection_claim_76_not_accepted"]
    assert claim["status"] == "unverified_candidate_finding"
    mapping = docs["v1_to_v2_mapping.json"]
    ambiguous = [
        entry
        for entry in mapping["forward_mapping"]
        if entry.get("confidence") == "partial"
    ]
    assert ambiguous
    for entry in ambiguous:
        assert entry.get("ambiguity_note", "").strip(), entry["semantic_node_id"]


def test_no_implemented_contracts_claim(regenerated):
    raw = (regenerated / "template.json").read_text(encoding="utf-8")
    assert "106 contracts implemented" not in raw
    assert "全部实现" not in raw


# ---------------------------------------------------------------------------
# Follow-up repair: content-resolved partial mappings and retained conditionals
# ---------------------------------------------------------------------------

RESOLUTION_STATUSES = {
    "source_carried",
    "partially_carried",
    "awaiting_3r3_contract",
    "unresolved",
}


def forward_by_semantic(docs):
    return {
        entry["semantic_node_id"]: entry
        for entry in docs["v1_to_v2_mapping.json"]["forward_mapping"]
    }


def reverse_by_id(docs):
    return {
        entry["v2_node_id"]: entry
        for entry in docs["v1_to_v2_mapping.json"]["reverse_mapping"]
    }


def test_every_partial_mapping_has_content_resolution(docs):
    forward = forward_by_semantic(docs)
    partials = {
        semantic
        for semantic, entry in forward.items()
        if entry["confidence"] == "partial"
    }
    assert partials, "expected the partial-confidence population to stay non-empty"
    for semantic in partials:
        resolution = forward[semantic].get("source_resolution")
        assert resolution, semantic
        assert resolution["status"] in RESOLUTION_STATUSES, semantic
        assert resolution["targets"], semantic
        for slice_entry in resolution["targets"]:
            assert slice_entry["status"] in RESOLUTION_STATUSES, semantic
            assert slice_entry["note"].strip(), semantic


def test_source_resolution_locators_are_body_child_indexes(docs):
    forward = forward_by_semantic(docs)
    for semantic, entry in forward.items():
        resolution = entry.get("source_resolution")
        if not resolution:
            continue
        for slice_entry in resolution["targets"]:
            for locator in slice_entry["evidence_body_child_indexes"]:
                assert 0 <= locator < 999, (semantic, locator)
        if resolution["status"] == "source_carried":
            assert any(
                slice_entry["evidence_body_child_indexes"]
                for slice_entry in resolution["targets"]
            ), semantic


def test_pregnancy_testing_is_distinct_from_pregnancy_event_reporting(docs):
    resolution = forward_by_semantic(docs)["procedures_assessments.pregnancy"][
        "source_resolution"
    ]
    carried = " ".join(
        slice_entry["note"]
        for slice_entry in resolution["targets"]
        if slice_entry["status"] == "source_carried"
    )
    awaiting = " ".join(
        slice_entry["note"]
        for slice_entry in resolution["targets"]
        if slice_entry["status"] == "awaiting_3r3_contract"
    )
    assert "避孕" in carried and "妊娠报告" in carried
    assert "妊娠检测" in awaiting
    assert resolution["status"] == "partially_carried"


def test_own_product_clinical_evidence_is_not_same_class_evidence(docs):
    resolution = forward_by_semantic(docs)["background.product.clinical"][
        "source_resolution"
    ]
    notes = json.dumps(resolution, ensure_ascii=False)
    assert "本药" in notes and "同类" in notes
    locators = [
        locator
        for slice_entry in resolution["targets"]
        for locator in slice_entry["evidence_body_child_indexes"]
    ]
    assert 299 in locators


def test_sample_handling_is_distinct_from_future_use_consent(docs):
    forward = forward_by_semantic(docs)
    specimen = forward["procedures_assessments.specimen"]
    assert specimen["target_v2_node_ids"] == ["v2_n_9_2"]
    resolution = specimen["source_resolution"]
    notes = json.dumps(resolution, ensure_ascii=False)
    assert "未来使用" in notes and "574" in notes
    reverse = reverse_by_id(docs)
    assert reverse["v2_n_12_7"]["disposition"] == "new_in_v2"
    assert "未来使用" in reverse["v2_n_12_7"]["rationale"]
    assert "procedures_assessments.specimen" in reverse["v2_n_9_2"]["from_v1_semantic_ids"]


def test_appendix_examples_do_not_define_all_project_instruments(docs):
    resolution = forward_by_semantic(docs)["appendices.instruments"][
        "source_resolution"
    ]
    assert resolution["status"] == "awaiting_3r3_contract"
    notes = json.dumps(resolution, ensure_ascii=False)
    assert "示例" in notes
    locators = [
        locator
        for slice_entry in resolution["targets"]
        for locator in slice_entry["evidence_body_child_indexes"]
    ]
    assert 974 in locators and 978 in locators


def test_overdose_error_is_explicitly_awaiting_contract(docs):
    entry = forward_by_semantic(docs)["intervention.overdose_error"]
    assert entry["source_resolution"]["status"] == "awaiting_3r3_contract"


def test_no_retired_dispositions_remain(docs):
    forward = forward_by_semantic(docs)
    used = {entry["disposition"] for entry in forward.values()}
    assert "retired" not in used


def test_retained_conditional_obligations_carry_rules_and_carriers(docs):
    mapping = docs["v1_to_v2_mapping.json"]
    block = mapping["retained_conditional_obligations"]
    by_semantic = {entry["semantic_node_id"]: entry for entry in block}
    expected = {
        "study_design.pk_pd_sampling",
        "procedures_assessments.unscheduled",
        "procedures_assessments.immunogenicity",
        "procedures_assessments.biomarker",
        "statistics.pk",
        "statistics.pd",
        "statistics.er",
        "appendices.contraception",
        "appendices.safety_reporting",
        "appendices.project_specific",
    }
    assert set(by_semantic) == expected
    forward = forward_by_semantic(docs)
    for semantic, entry in by_semantic.items():
        assert entry["carrier_v2_node_ids"] == forward[semantic]["target_v2_node_ids"]
        assert entry["carrier_v2_node_ids"], semantic
        assert entry["carrying_status"] == "retained_conditional_awaiting_3r3_contract"
        assert entry["conditional_source"] in {
            "row_rules",
            "conditional_prefixes",
            "required_in_legacy",
        }
        legacy_entry = forward[semantic]
        assert legacy_entry["conditional_rules"] == entry["original_applicability_rules"]


def test_mapping_conventions_documented(docs):
    conventions = docs["v1_to_v2_mapping.json"]["mapping_conventions"]
    assert conventions["forward_container_reverse_descendant"].strip()
    assert conventions["source_vs_additional_content"].strip()
    assert conventions["retained_conditional"].strip()


def test_m11_anchor_policy_and_provenance(docs):
    mapping = docs["v1_to_v2_mapping.json"]
    policy = mapping["m11_anchor_policy"]
    assert "legacy" in policy["policy"]
    tree = docs["node_tree.json"]
    new_in_v2_ids = {
        entry["v2_node_id"]
        for entry in mapping["reverse_mapping"]
        if entry["disposition"] == "new_in_v2"
    }
    assert policy["unverified_new_anchor_requirement_v2_node_ids"] == sorted(new_in_v2_ids)
    for entry in mapping["forward_mapping"]:
        assert entry["anchor_provenance"] in {
            "legacy_frozen_3_1_chapter_row",
            "none_in_legacy",
        }, entry["semantic_node_id"]
        if entry["anchor_provenance"] == "legacy_frozen_3_1_chapter_row":
            assert entry["m11_coverage_anchors"]
    assert "3R.3" in policy["policy"]


def test_section_metadata_binds_header_footer_and_page_numbering(docs):
    sections = docs["node_tree.json"]["sections"]
    with_refs = [
        section
        for section in sections
        if section["header_reference"] or section["footer_reference"]
    ]
    assert with_refs, "sections must record header/footer reference binding"
    first = with_refs[0]
    for binding in first["header_reference"] + first["footer_reference"]:
        assert binding["part"].startswith("word/")
    assert all("pg_num_type" in section for section in sections)


def test_style_properties_exposed_for_word_contract(docs):
    styles = docs["node_tree.json"]["style_properties"]
    chapter = styles["68"]
    assert chapter["name"] == "标题 1 1."
    assert chapter["outline_resolved"] == 0
    assert chapter["numbering"]["num_id"] == 1, "chapter style must bind list numbering"
    assert styles["2"]["outline"] == 0
    assert "font" in chapter and "based_on" in chapter


def test_nonclinical_mapping_is_partial_with_unheaded_note(docs):
    entry = forward_by_semantic(docs)["background.product.nonclinical"]
    assert entry["confidence"] == "partial"
    assert "毒理" in entry["ambiguity_note"]


def test_no_false_codex_reviewed_label():
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "Codex-reviewed" not in script
    assert "semantic judgment, pending Codex review" in script
