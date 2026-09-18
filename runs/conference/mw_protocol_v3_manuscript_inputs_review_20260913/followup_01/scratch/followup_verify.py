"""Read-only followup_01 verification of owner A/B repairs."""
from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path[:0] = [
    str(ROOT / "services/api"),
    str(ROOT),
    str(ROOT / "tests"),
    str(ROOT / "tests/protocol_v3"),
    str(ROOT / "tests/protocol_v3/integration"),
]

from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from app.protocol_workflow.registries.template_runtime import load_current_template
from app.protocol_workflow.agent3.manuscript_plan import (
    manuscript_preparation_view, plan_manuscript_chapters,
)
from app.protocol_workflow.agent3.source_material import prepare_chapter_source_material
from app.protocol_workflow.agent1.docx_parse import PARSER_VERSION, parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from test_chapter_fact_binding import confirmed_study
from test_writing_reference_docx import build_docx, paragraph_xml
from packages.contracts.workbench_contracts.protocol_v3 import CanonicalState, SourceArtifact


def banner(title):
    print(f"\n=== {title} ===")


def required_vs_inactive():
    banner("required facts vs conditional_fact_paths")
    template = load_current_template(REAL_TEMPLATE_DIR)
    rules = {r.rule_id: r for r in template.rules_catalog.rules}
    overlap_chapters = []
    unconditional_missing_candidates = []
    for entry in template.registry.chapters:
        required = {item.fact_path for item in entry.contract.substantive_content.fact_requirements
                    if item.obligation.value == "required"}
        conditional = set()
        for rule in entry.contract.conditional_applicability_rules:
            declaration = rules.get(rule.conditional_applicability_rule_id)
            if declaration:
                conditional.update(declaration.conditional_fact_paths)
        overlap = sorted(required & conditional)
        if overlap:
            overlap_chapters.append((entry.node_id, overlap))
        if entry.node_id == "v2_n_4_1":
            print("v2_n_4_1 required", sorted(required))
            print("v2_n_4_1 conditional_fact_paths", sorted(conditional))
            print("v2_n_4_1 unconditional_required", sorted(required - conditional))
    print("chapters_with_required_and_conditional_overlap", overlap_chapters[:12], "count", len(overlap_chapters))
    return template


def phase_and_hidden_binding_errors(template):
    banner("A: alias visible; other raw-contract errors swallowed")
    base = {
        "framing.study_phase": "Ⅱ期",
        "framing.structured_design.phase": "Ⅲ期",
    }
    plan = plan_manuscript_chapters(template, confirmed_study(base))
    for node in ("v2_n_1_1", "v2_n_4_1"):
        item = next(i for i in plan["chapters"] if i["node_id"] == node)
        print(node, item["status"], item["errors"])
    # Unconditional required hole on design, no alias.
    hole = confirmed_study({"study.synthetic": True})
    plan_hole = plan_manuscript_chapters(template, hole)
    design = next(i for i in plan_hole["chapters"] if i["node_id"] == "v2_n_4_1")
    print("design_unresolved_only", design["status"], design["errors"])
    print("design_has_missing_code", any(e.get("code") == "missing_required_fact" for e in design["errors"]))
    # Type mismatch on a required json-incompatible? use NaN via Python if study allows.
    # Use a non-json typed required fact if present; otherwise object member invalid.
    # framing.structured_design is json so skip; inject alias + a path that sorts first
    # with a value that fails _json (NaN).
    bad = dict(base)
    bad["framing.structured_design"] = float("nan")
    try:
        plan_bad = plan_manuscript_chapters(template, confirmed_study(bad))
        item = next(i for i in plan_bad["chapters"] if i["node_id"] == "v2_n_4_1")
        print("design_nan_structured", item["status"], item["errors"])
        print("design_nan_has_alias", any(e.get("code") == "fact_alias_conflict" for e in item["errors"]))
        print("design_nan_has_type", any(e.get("code") == "fact_type_mismatch" for e in item["errors"]))
    except Exception as exc:
        print("design_nan_exception", type(exc).__name__, str(exc)[:240])

    # After inner rules resolved to not_applicable, missing unconditional still via bind_applicable.
    resolved_inner = {
        "framing.study_phase": "Ⅱ期",
        "statistics.interim.applicable": False,
        "framing.structured_design.features": {"stratification": False, "substudy": False},
    }
    plan_r = plan_manuscript_chapters(template, confirmed_study(resolved_inner))
    design_r = next(i for i in plan_r["chapters"] if i["node_id"] == "v2_n_4_1")
    print("design_inner_false_no_alias", design_r["status"], design_r["errors"][:3])


def proposed_view(template):
    banner("proposed view vs strict plan")
    study = confirmed_study({
        "appendix.ecog_assessment_applicable": False,
        "appendix.ecog_applicability_decision_record": "synthetic exclusion",
        "framing.study_phase": "Ⅱ期",
    }).model_copy(update={"canonical_state": CanonicalState.PROPOSED})
    view = manuscript_preparation_view(template, study)
    print("view_len", len(view["chapters"]), "order0", view["chapters"][0]["node_id"])
    print("snapshot", view["applicability_snapshot"])
    print("all_ready", view["all_applicable_inputs_ready"])
    print("statuses", {item["status"] for item in view["chapters"]})
    print("applicability", {item["applicability"] for item in view["chapters"]})
    print("errors", {tuple(e["code"] for e in item["errors"]) for item in view["chapters"]})
    print("any_not_applicable", any(i["status"] == "not_applicable" for i in view["chapters"]))
    print("any_facts_ready", any(i["status"] == "facts_ready" for i in view["chapters"]))
    try:
        plan_manuscript_chapters(template, study)
        print("strict_plan", "UNEXPECTED_SUCCESS")
    except ValueError as exc:
        print("strict_plan_error", str(exc))
    frozen = study.model_copy(update={"canonical_state": CanonicalState.FROZEN})
    try:
        frozen_plan = manuscript_preparation_view(template, frozen)
        print("frozen_uses_strict", frozen_plan["applicability_snapshot"] is not None,
              frozen_plan["chapters"][next(i for i,c in enumerate(frozen_plan["chapters"]) if c["node_id"]=="v2_n_16_x1")]["status"]
              if False else next(c["status"] for c in frozen_plan["chapters"] if c["node_id"]=="v2_n_16_x1"))
    except Exception as exc:
        print("frozen_view", type(exc).__name__, str(exc)[:200])


def heading_v1_v2():
    banner("B: v1 vs v2 heading classification")
    payload = build_docx(
        paragraph_xml("数字样式标题", style="2")
        + paragraph_xml("继承样式标题", style="custom")
        + paragraph_xml("可引用正文")
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(payload)) as original, zipfile.ZipFile(buf, "w") as archive:
        for name in original.namelist():
            archive.writestr(name, original.read(name))
        archive.writestr(
            "word/styles.xml",
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 1"/>'
            "<w:pPr><w:outlineLvl w:val=\"0\"/></w:pPr></w:style>"
            '<w:style w:type="paragraph" w:styleId="custom"><w:basedOn w:val="2"/></w:style></w:styles>',
        )
    payload = buf.getvalue()
    v1 = parse_docx(payload, parser_version="protocol-docx-xml.v1")
    v2 = parse_docx(payload)
    print("default_version", PARSER_VERSION, v2.parser_version)
    print("v1_roles", [b.role for b in v1.blocks], "version", v1.parser_version)
    print("v2_roles", [b.role for b in v2.blocks], "version", v2.parser_version)
    try:
        parse_docx(payload, parser_version="protocol-docx-xml.v0")
        print("unsupported", "UNEXPECTED")
    except ValueError as exc:
        print("unsupported", str(exc))
    source = SourceArtifact(
        source_artifact_id="source:heading",
        logical_source_key="reference",
        content_sha256=hashlib.sha256(payload).hexdigest(),
        source_role="company_style_only",
        source_version="1",
        jurisdiction="CN",
        mime_type="application/docx",
        captured_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    bundle_v2 = prepare_chapter_source_material(((source, v2),), extracted_at=source.captured_at)
    bundle_v1 = prepare_chapter_source_material(((source, v1),), extracted_at=source.captured_at)
    print("v2_evidence", [u.body for u in bundle_v2.evidence])
    print("v2_parse_heading_text", bundle_v2.to_payload()["sources"][0]["parse"]["blocks"][0]["text"],
          bundle_v2.to_payload()["sources"][0]["parse"]["blocks"][0]["role"])
    print("v1_evidence_includes_heading", any("数字样式标题" in u.body for u in bundle_v1.evidence))
    seed_v1 = prepare_seed_request("合成", ((source, v1),))
    print("seed_v1_parser", seed_v1.to_payload()["sources"][0]["parser_version"])
    print("seed_v1_heading_unit_role", next(u["role"] for u in seed_v1.to_payload()["sources"][0]["units"] if u["text"] == "数字样式标题"))
    # tracked changes still body + diagnostic
    tracked = parse_docx(build_docx('<w:ins>' + paragraph_xml("修订中的内容") + "</w:ins>"))
    print("tracked_roles", [b.role for b in tracked.blocks], [d.code for d in tracked.diagnostics])
    return payload, source, v1, seed_v1


def pinned_history(payload, source, v1, seed_v1):
    banner("pinned reader: original projection then current material")
    from test_source_identity_product import service, adopt
    from app.protocol_workflow.agent3.pinned_sources import read_pinned_chapter_sources
    from test_template_fact_adoption import _dump

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        svc = service(tmp)
        first = adopt(svc, payload)
        # Rebind seed to adopted identity
        seed = prepare_seed_request("合成", ((first.source.source, parse_docx(payload, parser_version="protocol-docx-xml.v1")),))
        before = seed.payload_json
        adopt(svc, build_docx(paragraph_xml("后继版本")), source_version="2")
        db_before = _dump(tmp / "product.db")
        bundle = read_pinned_chapter_sources(svc, "project-1", seed, extracted_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
        print("seed_unchanged", seed.payload_json == before)
        print("db_unchanged", _dump(tmp / "product.db") == db_before)
        print("bundle_parser", bundle.to_payload()["sources"][0]["parse"]["parser_version"])
        print("bundle_heading_role", bundle.to_payload()["sources"][0]["parse"]["blocks"][0]["role"])
        print("bundle_heading_in_parse", bundle.to_payload()["sources"][0]["parse"]["blocks"][0]["text"])
        print("bundle_evidence", [u.body for u in bundle.evidence])
        print("not_successor", all("后继版本" not in u.body for u in bundle.evidence))


def proposed_api():
    banner("proposed API 111")
    import pytest
    from test_mounted_api_integration import PROJECT, _admitted_client
    from test_semantic_document_reducer import _study_definition
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
    from test_template_fact_adoption import _dump

    with tempfile.TemporaryDirectory() as tmp:
        mp = pytest.MonkeyPatch()
        try:
            client, db = _admitted_client(Path(tmp), mp)
            factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(db)})
            for state in ("proposed", "confirmed"):
                study = _study_definition(
                    project_id=PROJECT, canonical_state=state,
                    facts={"framing.study_phase": "Ⅱ期", "appendix.ecog_assessment_applicable": False},
                )
                with factory() as uow:
                    # new study id each time; confirmed uses different object
                    uow.study_definition_cas_repository.save_with_expected_revision(PROJECT, study, 0)
                    uow.commit()
                path = (
                    f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/"
                    f"{study.study_definition_id}/manuscript-plan"
                )
                before = _dump(db)
                r = client.get(path)
                plan = r.json()
                print(state, "status", r.status_code, "n", len(plan.get("chapters", [])),
                      "snapshot_none", plan.get("applicability_snapshot") is None,
                      "ready", plan.get("all_applicable_inputs_ready"),
                      "db_same", _dump(db) == before)
                if state == "proposed":
                    print("proposed_all_unresolved", all(
                        i["status"] == "needs_information" and i["applicability"] == "unresolved"
                        and i["errors"] == [{"code": "study_not_confirmed"}] for i in plan["chapters"]))
                    print("proposed_excluded", any(i["status"] == "not_applicable" for i in plan["chapters"]))
                else:
                    print("confirmed_ecog", next(i["status"] for i in plan["chapters"] if i["node_id"] == "v2_n_16_x1"))
        finally:
            mp.undo()


if __name__ == "__main__":
    template = required_vs_inactive()
    phase_and_hidden_binding_errors(template)
    proposed_view(template)
    payload, source, v1, seed_v1 = heading_v1_v2()
    pinned_history(payload, source, v1, seed_v1)
    proposed_api()
