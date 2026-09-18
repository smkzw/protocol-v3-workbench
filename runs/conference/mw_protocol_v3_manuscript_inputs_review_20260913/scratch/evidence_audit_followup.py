"""Follow-up read-only probes: phase conflict visibility, heading roles, API."""
from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import zipfile
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
from test_chapter_fact_binding import confirmed_study
from test_writing_reference_docx import build_docx, paragraph_xml
from packages.contracts.workbench_contracts.protocol_v3 import SourceArtifact


def phase_conflict_when_inner_resolved():
    print("=== phase conflict after inner rules resolved ===")
    template = load_current_template(REAL_TEMPLATE_DIR)
    facts = {
        "framing.study_phase": "Ⅱ期",
        "framing.structured_design.phase": "Ⅲ期",
        "statistics.interim.applicable": False,
        "framing.structured_design.features": {"stratification": False, "substudy": False},
        "appendix.ecog_assessment_applicable": False,
        "appendix.ecog_applicability_decision_record": "synthetic exclusion",
        "appendix.nyha_assessment_applicable": False,
        "appendix.nyha_applicability_decision_record": "synthetic exclusion",
    }
    plan = plan_manuscript_chapters(template, confirmed_study(facts))
    for node in ("v2_n_1_1", "v2_n_4_1"):
        item = next(i for i in plan["chapters"] if i["node_id"] == node)
        print(node, item["status"], item.get("errors"))


def heading_roles():
    print("=== heading classification ===")
    cases = {
        "style2_only": '<w:p><w:pPr><w:pStyle w:val="2"/></w:pPr><w:r><w:t>数字样式标题</w:t></w:r></w:p>',
        "heading1_name": paragraph_xml("英文样式标题", style="Heading1"),
        "cn_name": paragraph_xml("中文样式标题", style="标题1"),
        "local_outline": '<w:p><w:pPr><w:pStyle w:val="2"/><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>本地大纲标题</w:t></w:r></w:p>',
    }
    # styles.xml heading id 2 with outline, paragraph only has style 2
    styles = (
        '<?xml version="1.0"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:styleId="2"><w:name w:val="heading 1"/>'
        '<w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style></w:styles>'
    )
    body = cases["style2_only"] + paragraph_xml("正文句")
    raw = build_docx(body)
    buf = io.BytesIO(raw)
    with zipfile.ZipFile(buf, "a") as zf:
        zf.writestr("word/styles.xml", styles)
    styled = buf.getvalue()
    for name, xml in cases.items():
        parsed = parse_docx(build_docx(xml + paragraph_xml("正文句")))
        print(name, [(b.role, b.text) for b in parsed.blocks])
    parsed_styles = parse_docx(styled)
    print("styles_xml_id2", [(b.role, b.text) for b in parsed_styles.blocks])
    source = SourceArtifact(
        source_artifact_id="source:heading",
        logical_source_key="reference",
        content_sha256=hashlib.sha256(styled).hexdigest(),
        source_role="company_style_only",
        source_version="1",
        jurisdiction="CN",
        mime_type="application/docx",
        captured_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    bundle = prepare_chapter_source_material(((source, parsed_styles),), extracted_at=source.captured_at)
    print("styles_xml_evidence", [u.body for u in bundle.evidence])


def header_footnote():
    print("=== header/footnote stories ===")
    payload = build_docx(paragraph_xml("正文句"))
    buf = io.BytesIO(payload)
    with zipfile.ZipFile(buf, "a") as zf:
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
    parsed = parse_docx(header_payload)
    source = SourceArtifact(
        source_artifact_id="source:audit2",
        logical_source_key="reference",
        content_sha256=hashlib.sha256(header_payload).hexdigest(),
        source_role="company_style_only",
        source_version="1",
        jurisdiction="CN",
        mime_type="application/docx",
        captured_at=datetime(2026, 9, 13, tzinfo=timezone.utc),
    )
    bundle = prepare_chapter_source_material(((source, parsed),), extracted_at=source.captured_at)
    bodies = [u.body for u in bundle.evidence]
    print("roles", sorted({b.role for b in parsed.blocks}))
    print("stories", parsed.story_parts)
    print("header_in_parse", any("页眉机密" in b.text for b in parsed.blocks))
    print("footnote_in_parse", any("脚注原文毫克" in b.text for b in parsed.blocks))
    print("header_in_evidence", any("页眉机密" in b for b in bodies))
    print("footnote_in_evidence", any("脚注原文毫克" in b for b in bodies))
    print("body_in_evidence", bodies)


def proposed_api():
    print("=== proposed study API ===")
    import pytest
    from test_mounted_api_integration import PROJECT, _admitted_client
    from test_semantic_document_reducer import _study_definition
    from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory

    with tempfile.TemporaryDirectory() as tmp:
        mp = pytest.MonkeyPatch()
        try:
            client, db = _admitted_client(Path(tmp), mp)
            factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(db)})
            study = _study_definition(
                project_id=PROJECT, canonical_state="proposed", facts={"framing.study_phase": "Ⅱ期"}
            )
            with factory() as uow:
                uow.study_definition_cas_repository.save_with_expected_revision(PROJECT, study, 0)
                uow.commit()
            path = (
                f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/"
                f"{study.study_definition_id}/manuscript-plan"
            )
            r = client.get(path)
            print("status", r.status_code)
            print("body", r.text[:600])
        finally:
            mp.undo()


if __name__ == "__main__":
    phase_conflict_when_inner_resolved()
    heading_roles()
    header_footnote()
    proposed_api()
