"""Read-only scratch audit for manuscript-plan/source-material evidence bounds."""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [
    str(ROOT / "services/api"),
    str(ROOT),
    str(ROOT / "tests"),
    str(ROOT / "tests/protocol_v3"),
    str(ROOT / "tests/protocol_v3/integration"),
]

from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from app.protocol_workflow.registries.template_runtime import load_current_template
from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
from app.protocol_workflow.agent3.source_material import prepare_chapter_source_material
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import _units
from test_chapter_fact_binding import confirmed_study
from test_writing_reference_docx import build_docx, paragraph_xml, table_xml
from packages.contracts.workbench_contracts.protocol_v3 import CanonicalState, SourceArtifact
import hashlib


def section(title):
    print(f"\n=== {title} ===")


def tree_and_order():
    section("tree vs contracts vs order")
    tree = json.loads((REAL_TEMPLATE_DIR / "node_tree.json").read_text())
    template = load_current_template(REAL_TEMPLATE_DIR)
    heading = {n["id"]: n["body_child_index"] for n in tree["heading_style_tree"]["nodes"]}
    outlined = {n["id"]: n["body_child_index"] for n in tree["outlined_tree"]["nodes"]}
    contracts = {p.stem for p in (REAL_TEMPLATE_DIR / "chapter_contracts").glob("*.json")}
    print("contracts", len(contracts))
    print("registry_chapters", len(template.registry.chapters))
    print("chapter_order", len(template.chapter_order))
    print("heading_nodes", len(heading), "outlined_nodes", len(outlined))
    print("heading_only", sorted(set(heading) - set(outlined)))
    print("outlined_only", sorted(set(outlined) - set(heading)))
    conflicts = {
        nid: (heading[nid], outlined[nid])
        for nid in set(heading) & set(outlined)
        if heading[nid] != outlined[nid]
    }
    print("position_conflicts", conflicts)
    missing_from_trees = sorted(contracts - set(heading) - set(outlined) - {"v2_front_block"})
    extra_tree_without_contract = sorted((set(heading) | set(outlined)) - contracts)
    print("contracts_missing_from_trees", missing_from_trees)
    print("tree_nodes_without_contract_count", len(extra_tree_without_contract))
    print("tree_nodes_without_contract_sample", extra_tree_without_contract[:20])
    positions = {**heading, **outlined, "v2_front_block": tree["front_block"]["body_child_index_range"][0]}
    used = [positions[nid] for nid in template.chapter_order]
    dup_idx = [idx for idx, n in Counter(used).items() if n > 1]
    print("duplicate_body_child_index_in_order", dup_idx)
    print("order_first_last", template.chapter_order[0], template.chapter_order[-1])
    print("front_block_range", tree["front_block"]["body_child_index_range"])
    print("node_tree.candidate_status", tree.get("candidate_status"))
    print("monotonic", all(used[i] <= used[i + 1] for i in range(len(used) - 1)))


def presence_and_unknown():
    section("unknown vs excluded")
    template = load_current_template(REAL_TEMPLATE_DIR)
    presence = [r.rule_id for r in template.rules_catalog.rules if r.affects_chapter_presence]
    print("presence_rules", presence)
    study = confirmed_study({"study.synthetic": True})
    plan = plan_manuscript_chapters(template, study)
    statuses = Counter(item["status"] for item in plan["chapters"])
    print("statuses_sparse_confirmed", dict(statuses))
    print("all_ready", plan["all_applicable_inputs_ready"], "scope", plan["scope"])
    print("template_pin_keys", sorted(plan["template"]))
    excluded = [item["node_id"] for item in plan["chapters"] if item["status"] == "not_applicable"]
    unknown = [item["node_id"] for item in plan["chapters"] if item["status"] == "needs_information"]
    print("excluded_count", len(excluded), "unknown_count", len(unknown))
    print("excluded_ids", excluded)
    ecog = next(item for item in plan["chapters"] if item["node_id"] == "v2_n_16_x1")
    print("ecog_unknown", ecog["status"], ecog["errors"][:1])
    closed = confirmed_study(
        {
            "appendix.ecog_assessment_applicable": False,
            "appendix.ecog_applicability_decision_record": "synthetic exclusion",
            "appendix.nyha_assessment_applicable": False,
            "appendix.nyha_applicability_decision_record": "synthetic exclusion",
        }
    )
    plan2 = plan_manuscript_chapters(template, closed)
    print(
        "closed_ecog",
        next(i for i in plan2["chapters"] if i["node_id"] == "v2_n_16_x1")["status"],
        "closed_nyha",
        next(i for i in plan2["chapters"] if i["node_id"] == "v2_n_16_x2")["status"],
    )
    proposed = confirmed_study({"appendix.ecog_assessment_applicable": False}).model_copy(
        update={"canonical_state": CanonicalState.PROPOSED}
    )
    try:
        plan_manuscript_chapters(template, proposed)
        print("proposed_plan", "UNEXPECTED_SUCCESS")
    except ValueError as exc:
        print("proposed_plan_error", str(exc))


def phase_plan_level():
    section("phase homology at plan level")
    from app.protocol_workflow.registries.fact_bindings import FactBindingError, bind_chapter_input, affected_chapter_fact_paths

    template = load_current_template(REAL_TEMPLATE_DIR)
    bindings = {b.fact_path: b for b in template.fact_catalog.bindings}
    for path in ("framing.study_phase", "framing.structured_design.phase"):
        b = bindings[path]
        print(path, "canonical", b.canonical_path, "legacy", list(b.legacy_canonical_paths))
    print(
        "affected_from_study_phase",
        affected_chapter_fact_paths(template.fact_catalog.bindings, ("framing.study_phase",)),
    )
    print(
        "affected_from_legacy",
        affected_chapter_fact_paths(template.fact_catalog.bindings, ("framing.structured_design.phase",)),
    )
    facts = {
        "framing.study_phase": "Ⅱ期",
        "framing.structured_design.phase": "Ⅲ期",
        "statistics.interim.applicable": False,
        "appendix.ecog_assessment_applicable": False,
        "appendix.ecog_applicability_decision_record": "synthetic exclusion",
        "appendix.nyha_assessment_applicable": False,
        "appendix.nyha_applicability_decision_record": "synthetic exclusion",
    }
    plan = plan_manuscript_chapters(template, confirmed_study(facts))
    for node in ("v2_n_1_1", "v2_n_4_1"):
        item = next(i for i in plan["chapters"] if i["node_id"] == node)
        print(node, item["status"], item.get("errors"))
    # legacy-only should not write a duplicate canonical key
    contract = next(e.contract for e in template.registry.chapters if e.node_id == "v2_n_1_1")
    required = [
        bindings[r.fact_path].canonical_path
        for r in contract.substantive_content.fact_requirements
        if r.obligation.value == "required" and r.fact_path not in {"framing.study_phase", "framing.structured_design.phase"}
    ]
    # Keep this probe focused on conflict visibility, not full facts_ready.


def docx_roles():
    section("docx roles stories diagnostics evidence")
    toc = '<w:p><w:fldSimple w:instr="TOC"><w:r><w:t>表1 合成剂量 12</w:t></w:r></w:fldSimple></w:p>'
    heading = '<w:p><w:pPr><w:pStyle w:val="2"/></w:pPr><w:r><w:t>合成标题</w:t></w:r></w:p>'
    ins = '<w:p><w:ins w:author="x"><w:r><w:t>插入句</w:t></w:r></w:ins><w:r><w:t>保留句</w:t></w:r></w:p>'
    deleted = '<w:p><w:del w:author="x"><w:r><w:delText>删除句</w:delText></w:r></w:del><w:r><w:t>现行句</w:t></w:r></w:p>'
    biblio = (
        '<w:sdt><w:sdtPr><w:tag w:val="EndNote.ReferenceList"/></w:sdtPr>'
        '<w:sdtContent><w:p><w:r><w:t>参考文献条目</w:t></w:r></w:p></w:sdtContent></w:sdt>'
    )
    payload = build_docx(
        toc
        + heading
        + paragraph_xml("完整原文最后一句")
        + ins
        + deleted
        + table_xml([["合成项目", "合成值"]]).replace("<w:tc>", "<w:tc><w:tcPr><w:gridSpan w:val=\"2\"/></w:tcPr>", 1)
        + biblio
    )
    parsed = parse_docx(payload)
    print("story_parts", parsed.story_parts)
    print("status", parsed.status, "page_count", parsed.physical_page_count)
    print("roles", [(b.role, b.kind, b.text[:20]) for b in parsed.blocks])
    print("diagnostics", [(d.code, d.locator) for d in parsed.diagnostics])
    source = SourceArtifact(
        source_artifact_id="source:audit",
        logical_source_key="reference",
        content_sha256=hashlib.sha256(payload).hexdigest(),
        source_role="company_style_only",
        source_version="1",
        jurisdiction="CN",
        mime_type="application/docx",
        captured_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    bundle = prepare_chapter_source_material(((source, parsed),), extracted_at=source.captured_at)
    payload_json = bundle.to_payload()
    bodies = [u["body"] for u in payload_json["evidence"]]
    print("evidence_bodies", bodies)
    print("toc_in_evidence", any("表1 合成剂量" in b for b in bodies))
    print("heading_in_evidence", any("合成标题" in b for b in bodies))
    print("biblio_in_evidence", any("参考文献条目" in b for b in bodies))
    print("inserted_in_evidence", any("插入句" in b for b in bodies))
    print("deleted_in_evidence", any("删除句" in b for b in bodies))
    print("current_in_evidence", any("现行句" in b for b in bodies))
    print("medical_admission", payload_json["medical_admission"])
    print("quality_basis", payload_json["quality_score_basis"])
    print("parse_has_diagnostics", bool(payload_json["sources"][0]["parse"]["diagnostics"]))
    print("parse_has_stories", payload_json["sources"][0]["parse"]["story_parts"])
    print("evidence_states", {u["canonical_state"] for u in payload_json["evidence"]})
    print("evidence_scores", {u["quality_score"] for u in payload_json["evidence"]})
    later = prepare_chapter_source_material(
        ((source, parsed),), extracted_at=datetime(2026, 9, 14, tzinfo=timezone.utc)
    )
    print("same_ids_new_time", [u.evidence_unit_id for u in bundle.evidence] == [u.evidence_unit_id for u in later.evidence])
    print("same_bundle_hash_new_time", bundle.input_sha256 == later.input_sha256)

    # header story
    from zipfile import ZipFile
    from io import BytesIO
    import xml.etree.ElementTree as ET

    buf = BytesIO(payload)
    with ZipFile(buf, "a") as zf:
        zf.writestr(
            "word/header1.xml",
            '<?xml version="1.0"?><w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:p><w:r><w:t>页眉机密</w:t></w:r></w:p></w:hdr>",
        )
        zf.writestr(
            "word/footnotes.xml",
            '<?xml version="1.0"?><w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:footnote w:id="1"><w:p><w:r><w:t>脚注原文毫克</w:t></w:r></w:p></w:footnote></w:footnotes>',
        )
    header_payload = buf.getvalue()
    parsed2 = parse_docx(header_payload)
    source2 = replace(source, content_sha256=hashlib.sha256(header_payload).hexdigest(), source_artifact_id="source:audit2")
    bundle2 = prepare_chapter_source_material(((source2, parsed2),), extracted_at=source.captured_at)
    bodies2 = [u.body for u in bundle2.evidence]
    print("header_roles", sorted({b.role for b in parsed2.blocks}))
    print("header_in_evidence", any("页眉机密" in b for b in bodies2))
    print("footnote_in_evidence", any("脚注原文毫克" in b for b in bodies2))
    print("header_in_parse", any("页眉机密" in b.text for b in parsed2.blocks))
    print("footnote_in_parse", any("脚注原文毫克" in b.text for b in parsed2.blocks))
    print("story_parts2", parsed2.story_parts)


def proposed_api():
    section("proposed study manuscript-plan API")
    import pytest
    from pathlib import Path as P
    from test_mounted_api_integration import _admitted_client, PROJECT
    from test_semantic_document_reducer import _study_definition
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory

    with tempfile.TemporaryDirectory() as tmp:
        mp = pytest.MonkeyPatch()
        try:
            client, db = _admitted_client(P(tmp), mp)
            factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(db)})
            study = _study_definition(project_id=PROJECT, canonical_state="proposed", facts={"framing.study_phase": "Ⅱ期"})
            with factory() as uow:
                uow.study_definition_cas_repository.save_with_expected_revision(PROJECT, study, 0)
                uow.commit()
            path = f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/{study.study_definition_id}/manuscript-plan"
            r = client.get(path)
            print("proposed_status", r.status_code)
            print("proposed_body", r.text[:500])
        finally:
            mp.undo()


def alias_projection_gap():
    section("resolved_input_contract legacy-only phase")
    from app.protocol_workflow.registries.applicability import bind_applicable_chapter

    template = load_current_template(REAL_TEMPLATE_DIR)
    entry = next(e for e in template.registry.chapters if e.node_id == "v2_n_4_1")
    study = confirmed_study({"framing.structured_design.phase": "Ⅱ期", "study.synthetic": True})
    try:
        effective, bound = bind_applicable_chapter(
            study, entry.contract, template.fact_catalog.bindings, rules=template.rules_catalog.rules
        )
        print("legacy_only_design_status", "bound", bound.resolved_facts.get("framing.structured_design.phase"))
    except Exception as exc:
        print("legacy_only_design_error", type(exc).__name__, getattr(exc, "code", None), str(exc)[:300])


if __name__ == "__main__":
    tree_and_order()
    presence_and_unknown()
    phase_plan_level()
    alias_projection_gap()
    docx_roles()
    proposed_api()
