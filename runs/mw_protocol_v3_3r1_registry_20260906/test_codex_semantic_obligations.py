"""Independent source-obligation probes; not a rendered Word acceptance."""
import importlib.util
from copy import deepcopy
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "registry_probe", ROOT / "scripts/qc/protocol_v3/extract_tp_ma_07_v2_registry.py"
)
REGISTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REGISTRY)


def test_safety_committee_is_not_efficacy_irc():
    targets = REGISTRY.LEGACY_MAPPING["study_design.safety_committee"]["target_v2_node_ids"]
    assert "v2_n_14_7" in targets
    assert "v2_n_9_4" not in targets


def test_conditional_content_is_not_retired_for_missing_heading():
    for semantic in (
        "study_design.pk_pd_sampling", "procedures_assessments.unscheduled",
        "procedures_assessments.immunogenicity", "procedures_assessments.biomarker",
        "statistics.pk", "statistics.pd", "statistics.er",
        "appendices.contraception", "appendices.safety_reporting",
        "appendices.project_specific",
    ):
        entry = REGISTRY.LEGACY_MAPPING[semantic]
        assert entry["disposition"] != "retired", semantic
        assert entry["target_v2_node_ids"], semantic


def test_missing_compensation_facts_do_not_waive_section_obligation():
    entry = REGISTRY.CONDITIONAL_REGISTRATIONS["ethics_compensation_insurance"]
    assert entry["default"] == "required"
    assert "保持占位" not in entry["reason"]


def test_word_inventory_includes_footer_page_fields():
    structure = REGISTRY.extract_docx_structure(REGISTRY.SOURCE_DOCX_PATH)
    parts = structure.get("part_field_inventory", {})
    footer = parts.get("word/footer1.xml", {})
    assert footer.get("PAGE", 0) > 0
    assert footer.get("NUMPAGES", 0) > 0


def test_direct_leaf_edges_are_bidirectional():
    for semantic, entry in REGISTRY.LEGACY_MAPPING.items():
        for target in entry["target_v2_node_ids"]:
            if target in REGISTRY.REVERSE_MAPPING:
                assert semantic in REGISTRY.REVERSE_MAPPING[target]["from_v1_semantic_ids"], (semantic, target)


def test_generic_immunology_does_not_prove_immunogenicity_contract():
    resolution = REGISTRY.SOURCE_RESOLUTIONS["procedures_assessments.immunogenicity"]
    assert resolution["status"] in {"partially_carried", "awaiting_3r3_contract"}


def test_resolution_locators_have_exact_content_owners():
    structure = REGISTRY.extract_docx_structure(REGISTRY.SOURCE_DOCX_PATH)
    mapping = REGISTRY.build_mapping(structure, REGISTRY.extract_legacy_inventory())
    owners = {i: n["id"] for n in structure["nodes"] for i in [n["body_child_index"], *n["content_paragraph_indexes"]]}
    owners.update({t["body_child_index"]: t["owner_node_id"] for t in structure["top_level_tables"]})
    owners.update({i: REGISTRY.FRONT_BLOCK_ID for i in structure["front_block"]["content_paragraph_indexes"]})
    for entry in mapping["forward_mapping"]:
        for part in entry.get("source_resolution", {}).get("targets", []):
            indexes = part["evidence_body_child_indexes"]
            assert part.get("actual_owner_v2_node_ids") == [owners[i] for i in indexes]


def test_missing_reverse_edge_is_rejected(monkeypatch):
    reverse = deepcopy(REGISTRY.REVERSE_MAPPING)
    reverse["v2_n_9_3"]["from_v1_semantic_ids"].remove("study_design.pk_pd_sampling")
    monkeypatch.setattr(REGISTRY, "REVERSE_MAPPING", reverse)
    with pytest.raises(REGISTRY.RegistrySourceError, match="reverse mapping missing"):
        REGISTRY.build_mapping(REGISTRY.extract_docx_structure(REGISTRY.SOURCE_DOCX_PATH), REGISTRY.extract_legacy_inventory())


def test_valid_index_in_wrong_carrier_is_rejected(monkeypatch):
    resolutions = deepcopy(REGISTRY.SOURCE_RESOLUTIONS)
    resolutions["procedures_assessments.specimen"]["targets"][0]["evidence_body_child_indexes"] = [41]
    monkeypatch.setattr(REGISTRY, "SOURCE_RESOLUTIONS", resolutions)
    with pytest.raises(REGISTRY.RegistrySourceError, match="outside carrier"):
        REGISTRY.build_mapping(REGISTRY.extract_docx_structure(REGISTRY.SOURCE_DOCX_PATH), REGISTRY.extract_legacy_inventory())
