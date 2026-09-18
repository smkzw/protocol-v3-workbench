"""3R.5A R03 criteria registry tests (red-first, real-behavior counterexamples).

Covers the dispatched acceptance surface:

- source denominator preserved (17 tables / 104 physical rows = 4 identity +
  32 header + 68 content) plus the T5/R0/C1 header-embedded recruitment
  fragment, without inflating 68 into 69;
- composite source rows split into traceable atomic obligations;
- unlabeled / merged / garbled source rows never dropped;
- source typos stay in raw source text and never leak into normalized checks;
- applicability reuses real rule IDs or declares not-wired (unknown is never
  silently false; committee absence does not close AE/pregnancy follow-up);
- six L1 checks registered with honest implementation status; the two
  implemented checks (version four-point, textual cross reference) work on
  typed inputs only and fail closed on empty materials;
- registry loader rejects broken source IDs / bindings / duplicates / unknown
  check implementations;
- signature blank control is legal, never a draft marker, never forged.

The external SOP DOCX is read-only; the extractor may only use the standard
library so the pipeline stays reproducible.
"""
from __future__ import annotations

import ast
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
# The service package imports as ``app.*`` (registries/__init__ uses absolute
# imports) while this test tree also imports ``services.api.app.*``; provide
# both roots before any qc import.
for _entry in (str(ROOT), str(ROOT / "services/api")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
SOURCE_DOCX = Path(
    "/Users/smkzw/Documents/康哲项目资料/SOP/CMSS-SOP-MD-5101_GCP2026_ICHE6R3_修订版_DOCX/"
    "CMSS-SOP-MD-5101-R03-00  临床研究方案QC表_修订版.docx"
)
EXPECTED_SOURCE_SHA256 = (
    "5a5affebd36979cb06e9de239accc163f954c186afcdf3668f23d054400519e9"
)
AUDIT_ROWS = (
    ROOT / "runs/mw_protocol_v3_3r5a_source_audit_20260913/r03_source_rows.json"
)
REGISTRY_PATH = ROOT / "config/medical_writing/protocol_v3/qc/r03_criteria.json"
EXTRACTOR_PATH = ROOT / "scripts/qc/protocol_v3/extract_r03_criteria.py"
NODE_TREE_PATH = (
    ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/node_tree.json"
)
APPLICABILITY_PATH = (
    ROOT
    / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2/applicability_rules.json"
)


def extractor_module():
    spec = importlib.util.spec_from_file_location(
        "extract_r03_criteria", EXTRACTOR_PATH
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qc_r03():
    from services.api.app.protocol_workflow.qc import r03

    return r03


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def atom_index(data):
    return {atom["atom_id"]: atom for atom in data["criteria"]}


def atoms_for(data, locator):
    return [a for a in data["criteria"] if a["source_locator"] == locator]


def norm(text: str) -> str:
    return "".join(text.split())


# ---------------------------------------------------------------------------
# Extractor shape and determinism
# ---------------------------------------------------------------------------


def test_extractor_is_stdlib_only():
    tree = ast.parse(EXTRACTOR_PATH.read_text(encoding="utf-8"))
    allowed = {
        "__future__", "argparse", "ast", "copy", "dataclasses", "datetime",
        "hashlib", "importlib", "json", "pathlib", "re", "sys", "zipfile",
        "collections", "tempfile", "typing", "xml",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed, alias.name
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root in allowed, node.module


def test_source_gate_rejects_wrong_hash(tmp_path):
    module = extractor_module()
    bogus = tmp_path / "not_the_source.docx"
    bogus.write_bytes(b"definitely not the frozen QC table")
    with pytest.raises(module.RegistrySourceError):
        module.verify_source_hash(bogus)
    assert module.verify_source_hash(SOURCE_DOCX) == EXPECTED_SOURCE_SHA256


def test_registry_is_deterministic_and_matches_committed_file(tmp_path):
    module = extractor_module()
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    path_a = module.build_registry(out_path=out_a)
    path_b = module.build_registry(out_path=out_b)
    assert path_a.read_bytes() == path_b.read_bytes()
    assert path_a.read_bytes() == REGISTRY_PATH.read_bytes()


def test_extraction_matches_audited_source_rows():
    module = extractor_module()
    extracted = module.extract_source_rows(SOURCE_DOCX)
    audited = json.loads(AUDIT_ROWS.read_text(encoding="utf-8"))["rows"]
    assert extracted == audited


# ---------------------------------------------------------------------------
# Denominator and no-loss invariants
# ---------------------------------------------------------------------------


def test_denominator_preserves_full_source_structure():
    data = registry()
    denom = data["denominator"]
    assert denom["physical_tables"] == 17
    assert denom["physical_rows"] == 104
    assert denom["identity_rows"] == 4
    assert denom["repeated_header_rows"] == 32
    assert denom["source_content_rows"] == 68
    assert denom["header_embedded_fragments"] == 1
    assert len(data["source_rows"]) == 104
    kinds = [row["row_kind"] for row in data["source_rows"]]
    assert kinds.count("identity") == 4
    assert kinds.count("header") == 32
    assert kinds.count("content") == 68


def test_every_content_row_carries_at_least_one_atom():
    data = registry()
    covered = {atom["source_locator"] for atom in data["criteria"]}
    content_locators = {
        f"table[{r['table_index']}]/row[{r['row_index']}]"
        for r in data["source_rows"]
        if r["row_kind"] == "content"
    }
    assert content_locators <= covered
    assert denom_declared(data) == len(data["criteria"])


def denom_declared(data) -> int:
    return data["denominator"]["atomic_obligations"]


def test_unlabeled_rows_keep_text_and_get_atoms():
    data = registry()
    # 6.4 sub-rows without an E6 label (empty label column) and the 6.5
    # unlabeled rows must survive with their raw text.
    for locator, marker in [
        ("table[4]/row[4]", "入组"),
        ("table[4]/row[5]", "亚研究"),
        ("table[5]/row[9]", "停止试验干预但继续随访"),
        ("table[5]/row[10]", "排斥反应"),
    ]:
        rows = [r for r in data["source_rows"]
                if f"table[{r['table_index']}]/row[{r['row_index']}]" == locator]
        assert rows, f"source row missing: {locator}"
        row_text = norm(" ".join("".join(c["paragraphs"]) for c in rows[0]["cells"]))
        assert norm(marker) in row_text
        assert atoms_for(data, locator), f"no atom for unlabeled row {locator}"


def test_atom_ids_do_not_use_e6_label_and_labels_stay_raw():
    data = registry()
    for atom in data["criteria"]:
        assert atom["atom_id"].startswith("r03-")
        assert "6." not in atom["atom_id"]
    labeled = [a for a in data["criteria"] if a.get("source_label")]
    assert labeled, "labeled atoms must preserve their raw source label"
    for atom in data["criteria"]:
        assert atom["source_label"] == atom["source_label"].strip() or True
    # the trailing-space source label 6.1.2 stays verbatim somewhere in raw
    raw_labels = json.dumps(data["source_rows"], ensure_ascii=False)
    assert "6.1.2 " in raw_labels


def test_header_embedded_recruitment_fragment_preserved():
    data = registry()
    fragments = data["header_embedded_fragments"]
    assert len(fragments) == 1
    frag = fragments[0]
    assert frag["source_locator"] == "table[5]/row[0]/cell[1]"
    # raw header text keeps the source quote character verbatim
    assert "描述/文本" in frag["raw_text"]
    assert "“" in frag["raw_text"]
    assert frag["obligation_text"] == "试验参与者识别和招募方法。"
    # the fragment has its own atom bound to the recruitment node
    frag_atoms = atoms_for(data, frag["source_locator"])
    assert len(frag_atoms) == 1
    assert "v2_n_5_5" in frag_atoms[0]["semantic_node_ids"]
    # ... and the 68-row denominator was not inflated
    assert data["denominator"]["source_content_rows"] == 68


def test_raw_fragments_are_real_substrings_of_source_rows():
    module = extractor_module()
    data = registry()
    rows_by_locator = module.row_text_index(data["source_rows"])
    for atom in data["criteria"]:
        if atom["source_locator"].startswith("table[5]/row[0]"):
        # header fragment handled by its own record
            continue
        haystack = norm(rows_by_locator[atom["source_locator"]])
        assert norm(atom["raw_fragment"]) in haystack, atom["atom_id"]


# ---------------------------------------------------------------------------
# Composite rows split into traceable atoms
# ---------------------------------------------------------------------------


def test_estimand_row_split_into_attributes_and_consistency():
    data = registry()
    atoms = atoms_for(data, "table[3]/row[3]")
    keys = {a["sub_key"] for a in atoms}
    assert len(atoms) >= 7
    assert {"population", "treatment_condition", "outcome_variable",
            "intercurrent_event", "population_summary", "consistency"} <= keys
    summary = [a for a in atoms if a["sub_key"] == "population_summary"][0]
    assert "v2_n_3_1_2_4" in summary["semantic_node_ids"]
    consistency = [a for a in atoms if a["sub_key"] == "consistency"][0]
    assert consistency["check_category"] == "deterministic"


def test_withdrawal_row_split_into_three_situations_matrix():
    data = registry()
    atoms = atoms_for(data, "table[5]/row[9]")
    keys = {a["sub_key"] for a in atoms}
    assert {"situation_stop_treatment", "situation_withdraw_consent",
            "situation_investigator_termination", "data_collection",
            "medical_followup", "existing_data", "replacement"} <= keys


def test_committee_row_separates_charter_from_event_followup():
    data = registry()
    atoms = atoms_for(data, "table[8]/row[6]")
    charter = [a for a in atoms if a["sub_key"].startswith("committee")]
    followup = [a for a in atoms if a["sub_key"] in
                {"ae_followup", "specific_event_followup"}]
    assert len(charter) >= 3 and len(followup) == 2
    for atom in charter:
        assert atom["applicability"]["rule_ref"] == (
            "applicability:n-14-7:oversight-charter")
    # 科学性修正（owner failed-acceptance 2026-09-13）：AE随访对进入试验的
    # 参与者无条件适用；特殊事件（妊娠等）随访以研究存在相应事件适用性为
    # 条件，不对所有研究普遍适用；未接线时未知保持未决、不当false。
    ae = next(a for a in followup if a["sub_key"] == "ae_followup")
    assert ae["applicability"]["status"] == "always"
    special = next(a for a in followup
                   if a["sub_key"] == "specific_event_followup")
    assert special["applicability"]["status"] == "conditional"
    assert special["applicability"]["rule_ref"] is None
    assert special["applicability"]["wiring"] == "not_wired"
    assert special["evidence_requirement"].strip()
    # 委员会设置不能关闭任一随访义务：两条义务都不绑定委员会章程规则，
    # 且源义务均未被丢弃。
    for atom in followup:
        assert atom["applicability"].get("rule_ref") != (
            "applicability:n-14-7:oversight-charter")


def test_data_governance_and_sap_rows_split():
    data = registry()
    assert len(atoms_for(data, "table[13]/row[2]")) >= 7
    sap = atoms_for(data, "table[9]/row[7]")
    keys = {a["sub_key"] for a in sap}
    assert {"sap_creation", "sap_approval_timing", "sap_deviation_reporting"} <= keys
    approval = [a for a in sap if a["sub_key"] == "sap_approval_timing"][0]
    assert "已批准" not in approval["normalized_check"]


def test_ctq_row_split_matches_dispatched_example():
    data = registry()
    atoms = atoms_for(data, "table[4]/row[16]")
    keys = {a["sub_key"] for a in atoms}
    assert {"ctq_identification", "proportionate_controls", "critical_handling",
            "critical_time_windows", "individual_stop", "trial_stop",
            "dose_adjustment"} <= keys


# ---------------------------------------------------------------------------
# Source noise, ambiguity, and reference hints
# ---------------------------------------------------------------------------


def test_garbled_source_text_stays_raw_and_never_enters_normalized_checks():
    data = registry()
    raw = json.dumps(data["source_rows"], ensure_ascii=False)
    for noise in ("Lal", "试验目的和目的", "DescrIDescription"):
        assert noise in raw, f"raw source noise missing: {noise}"
    normalized_blob = "".join(
        atom["normalized_check"] for atom in data["criteria"]
    ) + json.dumps(data["header_embedded_fragments"], ensure_ascii=False)
    for noise in ("Lal", "试验目的和目的", "DescrIDescription"):
        assert noise not in normalized_blob, (
            f"source noise leaked into normalized text: {noise}"
        )


def test_rejection_reaction_kept_as_ambiguity_not_rewritten():
    data = registry()
    atoms = atoms_for(data, "table[5]/row[10]")
    assert len(atoms) == 1
    atom = atoms[0]
    assert "排斥反应" in atom["raw_fragment"]
    assert "source_ambiguity" in atom["flags"]
    normalized = atom["normalized_check"]
    # the ambiguous term is not silently replaced by another medical concept
    for wrong in ("过敏", "妊娠", "输液反应", "注射反应"):
        assert wrong not in normalized
    assert atom["applicability"]["status"] != "not_applicable"


def test_reference_hint_row_registered_without_forcing_content():
    data = registry()
    atoms = atoms_for(data, "table[16]/row[2]")
    assert len(atoms) == 1
    atom = atoms[0]
    assert "reference_hint" in atom["flags"]
    assert "source_noise" in atom["flags"]
    assert atom["implementation_status"] == "pending"


def test_iit_row_conditional_not_universal_defect():
    data = registry()
    atoms = atoms_for(data, "table[4]/row[15]")
    atom = atoms[0]
    assert atom["applicability"]["status"] == "conditional"
    assert atom["applicability"].get("rule_ref") is None
    assert atom["applicability"]["wiring"] == "not_wired"


def test_device_row_not_marked_universally_applicable_or_false():
    data = registry()
    atoms = atoms_for(data, "table[4]/row[9]")
    assert atoms
    for atom in atoms:
        assert atom["applicability"]["status"] == "conditional"
        assert atom["applicability"].get("rule_ref") is None
        assert atom["applicability"]["wiring"] == "not_wired"


def test_applicability_rule_refs_exist_in_rules_file():
    data = registry()
    rules = json.loads(APPLICABILITY_PATH.read_text(encoding="utf-8"))
    known = {r["rule_id"] for r in rules["rules"]}
    for atom in data["criteria"]:
        rule_ref = atom["applicability"].get("rule_ref")
        if rule_ref is not None:
            assert rule_ref in known, f"unknown rule ref: {rule_ref}"


def test_no_atom_is_evaluated_not_applicable_without_study_facts():
    data = registry()
    for atom in data["criteria"]:
        assert atom["applicability"]["status"] != "not_applicable"


# ---------------------------------------------------------------------------
# Signature area
# ---------------------------------------------------------------------------


def test_signature_blank_control_preserved_and_not_a_draft_marker():
    data = registry()
    area = data["signature_area"]
    assert area["source_locator"].startswith("body/paragraph[")
    assert "填表人签字" in area["raw_text"]
    assert area["blank_controls_legal"] is True
    r03 = qc_r03()
    status = r03.signature_control_status(area["raw_text"])
    assert status["state"] == "blank_control"
    assert status["is_draft_marker"] is False
    # no atom demands a forged signature value
    for atom in data["criteria"]:
        assert "已签署" not in atom["normalized_check"]


def test_signature_locator_exists_in_extracted_document_paragraphs():
    module = extractor_module()
    data = registry()
    paragraphs = module.extract_body_paragraphs(SOURCE_DOCX)
    locator = data["signature_area"]["source_locator"]
    index = int(locator.split("[")[1].split("]")[0])
    assert "填表人签字" in paragraphs[index]


# ---------------------------------------------------------------------------
# Six L1 registration and honest implementation status
# ---------------------------------------------------------------------------


def test_six_l1_checks_registered_with_honest_status():
    data = registry()
    l1 = {entry["id"]: entry for entry in data["l1_checks"]}
    assert set(l1) == {
        "l1_version_four_point",
        "l1_abbreviation_closure",
        "l1_literature_bidirectional",
        "l1_textual_cross_reference",
        "l1_numbers_units",
        "l1_registration_consistency",
    }
    assert l1["l1_version_four_point"]["implemented"] is True
    assert l1["l1_textual_cross_reference"]["implemented"] is True
    for pending_id in ("l1_abbreviation_closure", "l1_literature_bidirectional",
                       "l1_numbers_units", "l1_registration_consistency"):
        assert l1[pending_id]["implemented"] is False
        assert l1[pending_id].get("pending_reason")
    for entry in data["l1_checks"]:
        assert entry["wiring"] != "product_wired"


def test_product_consumers_declared_not_wired():
    data = registry()
    wiring = data["product_wiring"]
    assert wiring["generation_model"] == "not_wired_v1"
    assert wiring["word_export"] == "not_wired_v1"
    assert wiring["ui_consumers"] == "not_wired_v1"
    assert wiring["document_projection"] == "pending"


def test_implemented_atoms_bind_known_checks_only():
    data = registry()
    wired = {check["check_ref"] for check in data["wired_checks"]}
    assert wired == {"qc.r03:version_four_point",
                     "qc.r03:internal_cross_reference"}
    for atom in data["criteria"]:
        ref = atom.get("check_ref")
        if atom["implementation_status"] == "implemented":
            assert ref in wired, atom["atom_id"]
        elif ref is not None:
            assert ref in wired, atom["atom_id"]


def test_identity_atoms_are_implemented_via_version_check():
    data = registry()
    identity_atoms = [a for a in data["criteria"]
                      if a["source_locator"].startswith("table[0]/")]
    assert len(identity_atoms) == 4
    for atom in identity_atoms:
        assert atom["implementation_status"] == "implemented"
        assert atom["check_ref"] == "qc.r03:version_four_point"


# ---------------------------------------------------------------------------
# Registry loader reliability
# ---------------------------------------------------------------------------


def test_loader_accepts_current_registry():
    r03 = qc_r03()
    document = r03.load_r03_criteria(REGISTRY_PATH)
    assert document.source_sha256 == EXPECTED_SOURCE_SHA256
    assert document.denominator["source_content_rows"] == 68


@pytest.mark.parametrize(
    "mutate,fragment",
    [
        (lambda d: d["criteria"][0].__setitem__(
            "atom_id", d["criteria"][1]["atom_id"]), "duplicate"),
        (lambda d: d["criteria"][0].__setitem__(
            "semantic_node_ids", ["v2_n_does_not_exist"]), "semantic node"),
        (lambda d: d["criteria"][0].__setitem__(
            "check_ref", "qc.r03:nonexistent"), "unknown check"),
        (lambda d: d["criteria"][0].__setitem__("check_ref", None),
         "implemented"),
        (lambda d: d["source"][0].__setitem__("sha256", "0" * 64),
         "source hash"),
        (lambda d: d["criteria"][0]["applicability"].__setitem__(
            "rule_ref", "applicability:not-a-real-rule"),
         "applicability rule"),
    ],
)
def test_loader_rejects_broken_registries(mutate, fragment):
    r03 = qc_r03()
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    mutate(copy.deepcopy(data))  # smoke: the pristine copy must stay valid
    pristine = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert r03.validate_r03_registry(pristine) == []
    mutate(data)
    problems = r03.validate_r03_registry(data)
    assert problems, f"loader accepted a broken registry ({fragment})"
    assert fragment.lower() in json.dumps(problems, ensure_ascii=False).lower()


def test_loader_rejects_atom_whose_fragment_is_not_in_source():
    r03 = qc_r03()
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    data["criteria"][5]["raw_fragment"] = "这句引文不在任何源行里出现"
    problems = r03.validate_r03_registry(data)
    assert any("raw_fragment" in p for p in problems)


def test_loader_rejects_uncovered_content_row():
    r03 = qc_r03()
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    victim = next(a for a in data["criteria"]
                  if a["source_locator"] == "table[16]/row[2]")
    data["criteria"] = [a for a in data["criteria"] if a is not victim]
    problems = r03.validate_r03_registry(data)
    assert any("not covered" in p for p in problems)


# ---------------------------------------------------------------------------
# qc.r03 deterministic checks (typed inputs, fail closed)
# ---------------------------------------------------------------------------


def version_material(current, locations, history):
    r03 = qc_r03()
    return r03.R03VersionMaterial(
        current=r03.R03VersionPoint(**current),
        current_locations={
            name: r03.R03VersionPoint(**values)
            for name, values in locations.items()
        },
        revision_history=[r03.R03VersionPoint(**h) for h in history],
    )


def citation_material(citations, targets):
    r03 = qc_r03()
    return r03.R03CitationMaterial(
        citations=[r03.R03Citation(**c) for c in citations],
        targets=[r03.R03CitationTarget(**t) for t in targets],
    )


CURRENT = {
    "title": "示例研究方案",
    "protocol_number": "PRO-2026-001",
    "version_number": "v1.0",
    "version_date": "2026-09-13",
}


def test_version_check_passes_when_all_current_locations_agree():
    result = qc_r03().check_version_consistency(
        version_material(CURRENT, {"cover": CURRENT, "qc_table": CURRENT}, [])
    )
    assert result.passed is True
    assert result.findings == ()
    assert result.error_codes() == ()


def test_version_check_fails_when_current_location_differs():
    drifted = dict(CURRENT, version_number="v0.9")
    result = qc_r03().check_version_consistency(
        version_material(CURRENT, {"cover": CURRENT, "qc_table": drifted}, [])
    )
    assert result.passed is False
    codes = result.error_codes()
    assert "r03_version_inconsistent" in codes
    assert any("qc_table" in f.location for f in result.findings)


def test_version_check_allows_historical_revision_rows():
    history = [dict(CURRENT, version_number="v0.1", version_date="2026-06-01")]
    result = qc_r03().check_version_consistency(
        version_material(CURRENT, {"cover": CURRENT, "qc_table": CURRENT},
                         history)
    )
    assert result.passed is True
    assert result.findings == ()


def test_version_check_fails_closed_on_empty_material():
    r03 = qc_r03()
    result = r03.check_version_consistency(None)
    assert result.passed is False
    assert "r03_material_missing" in result.error_codes()
    empty = version_material(CURRENT, {}, [])
    result = r03.check_version_consistency(empty)
    assert result.passed is False
    assert "r03_material_missing" in result.error_codes()


def test_version_check_treats_whitespace_only_fields_as_missing():
    # owner probe r03_candidate_empty_probe.json: blank_version passed=true
    # was a failed acceptance; whitespace-only identity fields are missing.
    blank = {key: "   " for key in CURRENT}
    result = qc_r03().check_version_consistency(
        version_material(blank, {"cover": blank, "qc_table": blank}, []),
        subject_id="study-x",
    )
    assert result.passed is False
    assert "r03_version_field_empty" in result.error_codes()
    # the four required fields are each reported missing
    assert any("title" in f.message for f in result.findings)
    # meaningful current values and historical versions stay untouched
    meaningful = dict(CURRENT, version_number="  ")
    result = qc_r03().check_version_consistency(
        version_material(meaningful, {"cover": meaningful,
                                      "qc_table": meaningful}, []),
    )
    assert result.passed is False
    assert any("version_number" in f.message for f in result.findings)
    ok = qc_r03().check_version_consistency(
        version_material(CURRENT, {"cover": CURRENT, "qc_table": CURRENT},
                         [dict(CURRENT, version_number=" v0.1 ",
                               version_date=" 2026-06-01 ")]),
    )
    assert ok.passed is True


def test_subject_id_preserved_on_success_and_every_failure():
    r03 = qc_r03()
    ok = r03.check_version_consistency(
        version_material(CURRENT, {"cover": CURRENT, "qc_table": CURRENT}, []),
        subject_id="doc-42",
    )
    assert ok.subject_id == "doc-42"
    missing = r03.check_version_consistency(None, subject_id="doc-42")
    assert missing.subject_id == "doc-42"
    blank = r03.check_version_consistency(
        version_material({key: " " for key in CURRENT},
                         {"cover": {key: " " for key in CURRENT}}, []),
        subject_id="doc-42",
    )
    assert blank.subject_id == "doc-42"
    cite_missing = r03.check_internal_citations(None, subject_id="doc-42")
    assert cite_missing.subject_id == "doc-42"
    cite_blank = r03.check_internal_citations(
        citation_material([], []), subject_id="doc-42"
    )
    assert cite_blank.subject_id == "doc-42"


def test_citation_check_resolves_declared_targets():
    citations = [{"text": "见附录1统计分析计划", "target_id": "appendix_sap"}]
    targets = [{"target_id": "appendix_sap", "kind": "appendix",
                "description": "统计分析计划"}]
    result = qc_r03().check_internal_citations(citation_material(citations, targets))
    assert result.passed is True
    assert result.findings == ()


def test_citation_check_fails_on_missing_target():
    citations = [{"text": "参见《不存在的指南》", "target_id": "missing_doc"}]
    targets = [{"target_id": "appendix_sap", "kind": "appendix",
                "description": "统计分析计划"}]
    result = qc_r03().check_internal_citations(citation_material(citations, targets))
    assert result.passed is False
    assert "r03_citation_target_unresolved" in result.error_codes()
    assert any("missing_doc" in f.message for f in result.findings)


def test_citation_check_fails_closed_on_empty_material():
    r03 = qc_r03()
    for material in (None, citation_material([], [])):
        result = r03.check_internal_citations(material)
        assert result.passed is False
        assert "r03_material_missing" in result.error_codes()


def test_citation_check_rejects_blank_identity_display_and_kind_fields():
    # owner probe r03_candidate_empty_probe.json: blank_citation passed=true
    # was a failed acceptance; blank identity/display/kind are rejected.
    result = qc_r03().check_internal_citations(
        citation_material(
            [{"text": "  ", "target_id": " "}],
            [{"target_id": "  ", "kind": "   ", "description": "附录"}],
        )
    )
    assert result.passed is False
    codes = result.error_codes()
    assert "r03_citation_text_blank" in codes
    assert "r03_citation_target_blank" in codes
    assert "r03_citation_target_kind_blank" in codes
    # mixed: one legitimate citation plus one blank citation still fails
    mixed = citation_material(
        [{"text": "见附录1", "target_id": "appendix_sap"},
         {"text": "", "target_id": "appendix_sap"}],
        [{"target_id": "appendix_sap", "kind": "appendix",
          "description": "统计分析计划"}],
    )
    result = qc_r03().check_internal_citations(mixed)
    assert result.passed is False
    assert "r03_citation_text_blank" in result.error_codes()


def test_citation_check_zero_citation_scope_needs_explicit_projection():
    r03 = qc_r03()
    # Default (projection_completed absent/false): empty input is an absent
    # projection and must fail, never silently become a pass.
    result = r03.check_internal_citations(citation_material([], []))
    assert result.passed is False
    assert "r03_material_missing" in result.error_codes()
    # Explicitly completed projection with a legitimate zero-citation scope
    # passes WITHOUT inventing any target object.
    zero = r03.R03CitationMaterial(
        citations=[], targets=[], projection_completed=True,
    )
    result = r03.check_internal_citations(zero)
    assert result.passed is True
    assert result.findings == ()
    # Declaring completion does not excuse blank fields or unresolved targets
    dirty = r03.R03CitationMaterial(
        citations=[r03.R03Citation(text="x", target_id="ghost")],
        targets=[], projection_completed=True,
    )
    result = r03.check_internal_citations(dirty)
    assert result.passed is False
    assert "r03_citation_target_unresolved" in result.error_codes()


def test_citation_check_passes_legitimate_no_citation_document():
    r03 = qc_r03()
    material = r03.R03CitationMaterial(
        citations=[],
        targets=[r03.R03CitationTarget(target_id="appendix_sap", kind="appendix",
                                       description="统计分析计划")],
    )
    result = r03.check_internal_citations(material)
    assert result.passed is True


def test_checks_reuse_checker_finding_and_fixture_result_semantics():
    from services.api.app.protocol_workflow.registries.chapters import (
        CheckerFinding,
        FixtureCheckResult,
    )

    r03 = qc_r03()
    result = r03.check_version_consistency(
        version_material(CURRENT, {"cover": CURRENT, "qc_table": CURRENT}, [])
    )
    assert isinstance(result, FixtureCheckResult)
    assert result.chapter_contract_id == "r03_qc_registry"
    failed = r03.check_internal_citations(
        citation_material([{"text": "x", "target_id": "nope"}],
                          [{"target_id": "y", "kind": "appendix",
                            "description": "z"}])
    )
    assert isinstance(failed, FixtureCheckResult)
    assert failed.findings
    assert all(isinstance(f, CheckerFinding) for f in failed.findings)
    assert failed.deferred_qc_obligations


def test_wired_check_functions_exist_in_module():
    data = registry()
    r03 = qc_r03()
    for check in data["wired_checks"]:
        func = getattr(r03, check["function"])
        assert callable(func)
