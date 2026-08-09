from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.medical_writing_document import (
    MedicalWritingDocumentService,
    _serialize_source_block,
    _SourceBlock,
)
from services.api.app.medical_writing_manifest import (
    DEFAULT_WRITING_PACKAGES,
    D001_PROTOCOL_DOCX,
    MY008_PNH_3_01_PROTOCOL_DOCX,
    RUX_PROTOCOL_DOCX,
)
from services.api.app.protocol_text_extractor import (
    ProtocolTable,
    ProtocolTableCell,
    parse_protocol_docx,
)


class MedicalWritingTableSerializationTests(unittest.TestCase):
    def test_table_serialization_preserves_stable_structure_and_merge_metadata(self):
        parent = ProtocolTableCell(
            row_index=0,
            cell_index=0,
            text="合并起始",
            source_locator="docx:table:4:row:0:cell:0",
            cell_id="ptcell_parent",
            grid_column_index=0,
            column_span=2,
            row_span=2,
            vertical_merge="restart",
            style_role="header",
        )
        continuation = ProtocolTableCell(
            row_index=1,
            cell_index=0,
            text="续接正文",
            source_locator="docx:table:4:row:1:cell:0",
            cell_id="ptcell_continuation",
            grid_column_index=0,
            vertical_merge="continue",
            hidden=True,
            merge_parent_cell_id=parent.cell_id,
            merge_parent_source_locator=parent.source_locator,
            merge_parent_row_index=0,
            merge_parent_cell_index=0,
            merge_parent_grid_column_index=0,
        )
        table = ProtocolTable(
            table_index=4,
            rows=[[parent], [continuation]],
            source_locator="docx:table:4",
            table_id="ptbl_source_4",
            schema_version="structured_table_v1",
            header_row_count=1,
            column_count=2,
        )

        payload = _serialize_source_block(
            "mwsec_test",
            _SourceBlock(kind="table", body_order=7, table=table),
            0,
        )

        self.assertEqual("ptbl_source_4", payload["table_id"])
        self.assertEqual("structured_table_v1", payload["schema_version"])
        self.assertEqual(1, payload["header_row_count"])
        self.assertEqual(2, payload["column_count"])
        serialized_parent = payload["rows"][0][0]
        serialized_continuation = payload["rows"][1][0]
        self.assertEqual("ptcell_parent", serialized_parent["cell_id"])
        self.assertEqual(2, serialized_parent["row_span"])
        self.assertEqual(2, serialized_parent["column_span"])
        self.assertEqual(0, serialized_parent["grid_column_index"])
        self.assertEqual("header", serialized_parent["style_role"])
        self.assertTrue(serialized_continuation["hidden"])
        self.assertEqual("ptcell_parent", serialized_continuation["merge_parent_cell_id"])
        self.assertEqual(parent.source_locator, serialized_continuation["merge_parent_source_locator"])
        self.assertEqual(0, serialized_continuation["merge_parent_row_index"])
        self.assertEqual(0, serialized_continuation["merge_parent_cell_index"])
        self.assertEqual(0, serialized_continuation["merge_parent_grid_column_index"])
        self.assertEqual("续接正文", serialized_continuation["text"])


@unittest.skipUnless(
    RUX_PROTOCOL_DOCX.exists() and D001_PROTOCOL_DOCX.exists() and MY008_PNH_3_01_PROTOCOL_DOCX.exists(),
    "real protocol DOCX fixtures are unavailable",
)
class MedicalWritingDocumentSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = MedicalWritingDocumentService()
        cls.client = TestClient(app)

    def test_three_real_protocols_create_distinct_document_sessions_from_original_docx(self):
        rux = self.service.document_session("proj_rux_03_002")
        d001 = self.service.document_session("proj_d001")
        pnh = self.service.document_session("proj_my008_pnh_3_01")

        self.assertEqual("proj_rux_03_002", rux.project_id)
        self.assertEqual("proj_d001", d001.project_id)
        self.assertEqual("proj_my008_pnh_3_01", pnh.project_id)
        self.assertEqual("RUX-03-002", rux.protocol_id)
        self.assertEqual("D001-02-002", d001.protocol_id)
        self.assertEqual("MY008211A-PNH-3-01", pnh.protocol_id)
        self.assertEqual("V1.1", pnh.version)
        self.assertNotEqual(rux.document_id, d001.document_id)
        self.assertEqual(3, len({rux.document_id, d001.document_id, pnh.document_id}))
        self.assertRegex(rux.document_id, r"^mwdoc_proj_rux_03_002_[0-9a-f]{16}$")
        self.assertRegex(d001.document_id, r"^mwdoc_proj_d001_[0-9a-f]{16}$")
        self.assertRegex(pnh.document_id, r"^mwdoc_proj_my008_pnh_3_01_[0-9a-f]{16}$")
        self.assertGreaterEqual(len(rux.sections), 50)
        self.assertGreaterEqual(len(d001.sections), 50)
        self.assertGreaterEqual(len(pnh.sections), 50)
        self.assertTrue(all(section.document_id == rux.document_id for section in rux.sections))
        self.assertTrue(all(section.document_id == d001.document_id for section in d001.sections))
        self.assertTrue(
            all(
                re.match(r"^mwsec_[a-z0-9_]+_[0-9a-f]{12}_[0-9a-f]{12}$", section.section_id)
                for section in rux.sections + d001.sections + pnh.sections
            )
        )
        self.assertFalse(any(section.content_blocks for section in rux.sections))
        self.assertFalse(any(section.content_blocks for section in d001.sections))
        self.assertTrue(all(section.evidence_coverage == 0.0 for section in rux.sections))
        self.assertTrue(all(section.evidence_coverage == 0.0 for section in d001.sections))
        self.assertNotIn(
            "passed",
            {gate["status"] for gate in rux.quality_gates if "traceability" in gate["gate_id"]},
        )
        serialized_gates = json.dumps(rux.quality_gates, ensure_ascii=False)
        self.assertNotIn("待医学批准", serialized_gates)
        self.assertNotIn('"label": "医学批准"', serialized_gates)
        self.assertIn("章节确认与版本冻结", serialized_gates)
        self.assertIn("当前医学经理确认后纳入工作副本", serialized_gates)

    def test_real_protocol_major_headings_follow_word_outline_parentage(self):
        rux = self.service.document_session("proj_rux_03_002")
        d001 = self.service.document_session("proj_d001")

        rux_by_heading = _unique_sections_by_heading(rux.sections)
        for heading in (
            "简介",
            "治疗依据",
            "疾病背景",
            "试验目的",
            "研究计划",
            "受试者入选标准",
            "受试者排除标准",
            "统计分析",
            "参考文献",
        ):
            self.assertIn(heading, rux_by_heading)
        self.assertIsNone(rux_by_heading["简介"].parent_id)
        self.assertEqual(rux_by_heading["简介"].section_id, rux_by_heading["治疗依据"].parent_id)
        self.assertEqual(rux_by_heading["治疗依据"].section_id, rux_by_heading["疾病背景"].parent_id)

        d001_by_heading = _unique_sections_by_heading(d001.sections)
        for heading in (
            "方案摘要",
            "概要",
            "研究目的与终点",
            "研究设计",
            "研究人群",
            "研究治疗",
            "试验用药品",
            "研究评估和程序",
            "安全性评估",
            "参考文献",
        ):
            self.assertIn(heading, d001_by_heading)
        self.assertIsNone(d001_by_heading["方案摘要"].parent_id)
        self.assertEqual(d001_by_heading["方案摘要"].section_id, d001_by_heading["概要"].parent_id)
        self.assertEqual(d001_by_heading["研究治疗"].section_id, d001_by_heading["试验用药品"].parent_id)

    def test_real_protocol_schedule_sections_receive_shared_editor_semantics(self):
        cases = (
            ("proj_rux_03_002", "试验流程表"),
            ("proj_d001", "研究流程表"),
            ("proj_my008_pnh_3_01", "表1 研究流程表"),
        )
        for project_id, heading in cases:
            with self.subTest(project_id=project_id):
                document = self.service.document_session(project_id)
                section = next(item for item in document.sections if item.heading == heading)
                self.assertEqual("1.3", section.ich_m11_anchor)
                self.assertEqual("m11_1_3", section.template_node_id)
                self.assertEqual(
                    ["schedule_of_activities_editor"],
                    section.interaction_types,
                )

    def test_real_protocol_front_matter_synopsis_and_body_tables_have_stable_roles(self):
        synopsis_cases = (
            ("proj_rux_03_002", "概要", "docx:table:1"),
            ("proj_d001", "概要", "docx:table:4"),
            ("proj_my008_pnh_3_01", "方案摘要", "docx:table:13"),
        )
        for project_id, heading, locator in synopsis_cases:
            with self.subTest(project_id=project_id, heading=heading):
                document = self.service.document_session(project_id)
                section = next(item for item in document.sections if item.heading == heading)
                self.assertEqual("1.1", section.ich_m11_anchor)
                self.assertEqual("m11_1_1", section.template_node_id)
                self.assertEqual("protocol_synopsis", section.node_kind)
                self.assertIn("synopsis_editor", section.interaction_types)
                content = self.service.section(project_id, section.section_id)
                table = next(
                    item
                    for item in content.content_blocks
                    if item.get("source_locator") == locator
                )
                self.assertEqual(
                    "protocol_synopsis",
                    table["structured_table"]["role"],
                )

        for project_id in ("proj_rux_03_002", "proj_d001", "proj_my008_pnh_3_01"):
            with self.subTest(project_id=project_id, section="front_matter"):
                document = self.service.document_session(project_id)
                section = next(item for item in document.sections if item.node_kind == "front_matter")
                self.assertEqual(["front_matter_editor"], section.interaction_types)
                content = self.service.section(project_id, section.section_id)
                tables = [item for item in content.content_blocks if item.get("block_type") == "table"]
                self.assertTrue(tables)
                self.assertTrue(
                    all(
                        item["structured_table"]["role"] in {"layout", "document_control"}
                        for item in tables
                    )
                )
                self.assertTrue(
                    any(item["structured_table"]["role"] == "layout" for item in tables)
                )

        rux = self.service.document_session("proj_rux_03_002")
        soa = next(item for item in rux.sections if item.heading == "试验流程表")
        soa_content = self.service.section("proj_rux_03_002", soa.section_id)
        soa_table = next(item for item in soa_content.content_blocks if item.get("block_type") == "table")
        self.assertEqual("body_content", soa_table["structured_table"]["role"])

        pnh = self.service.document_session("proj_my008_pnh_3_01")
        pnh_front = next(item for item in pnh.sections if item.node_kind == "front_matter")
        pnh_front_content = self.service.section("proj_my008_pnh_3_01", pnh_front.section_id)
        roles_by_title = {
            item.get("title"): item["structured_table"]["role"]
            for item in pnh_front_content.content_blocks
            if item.get("block_type") == "table" and item.get("title")
        }
        self.assertEqual("document_control", roles_by_title["方案修订记录"])
        self.assertEqual("document_control", roles_by_title["缩略语表"])

    def test_section_content_contains_original_text_and_source_locators(self):
        for project_id in ("proj_rux_03_002", "proj_d001", "proj_my008_pnh_3_01"):
            with self.subTest(project_id=project_id):
                session = self.service.document_session(project_id)
                target = next(
                    section
                    for section in session.sections
                    if self.service.section(project_id, section.section_id).content_blocks
                )
                section = self.service.section(project_id, target.section_id)

                self.assertEqual(target.section_id, section.section_id)
                self.assertTrue(any(block.get("text", "").strip() for block in section.content_blocks))
                self.assertTrue(
                    all(
                        str(block.get("source_locator", "")).startswith(("docx:paragraph:", "docx:table:"))
                        for block in section.content_blocks
                    )
                )
                self.assertEqual(
                    sorted(block["body_order"] for block in section.content_blocks),
                    [block["body_order"] for block in section.content_blocks],
                )
                text_blocks = [
                    block
                    for block in section.content_blocks
                    if block.get("block_type") != "table"
                ]
                self.assertTrue(text_blocks)
                self.assertTrue(all(block.get("rich_text") for block in text_blocks))
                self.assertTrue(
                    all(
                        _rich_text_plain_text(block["rich_text"]) == block["text"]
                        for block in text_blocks
                    )
                )
                serialized = json.dumps(section.model_dump(mode="json"), ensure_ascii=False)
                self.assertNotIn("/Users/", serialized)
                self.assertNotIn("尚未建立可编辑章节", serialized)
                self.assertNotIn("MG-K10", serialized)

    def test_real_protocol_tables_remain_in_section_body_order_with_cell_provenance(self):
        cases = (
            ("proj_rux_03_002", "概要", "docx:table:1"),
            ("proj_d001", "概要", "docx:table:4"),
        )
        for project_id, heading, expected_table_locator in cases:
            with self.subTest(project_id=project_id):
                session = self.service.document_session(project_id)
                summary = _unique_sections_by_heading(session.sections)[heading]
                section = self.service.section(project_id, summary.section_id)
                table = next(
                    block
                    for block in section.content_blocks
                    if block["block_type"] == "table"
                    and block["source_locator"] == expected_table_locator
                )
                self.assertFalse(table["editable"])
                self.assertTrue(table["rows"])
                self.assertTrue(table["rows"][0])
                self.assertTrue(
                    table["rows"][0][0]["source_locator"].startswith(expected_table_locator)
                )
                heading_block = section.content_blocks[0]
                self.assertEqual("heading", heading_block["block_type"])
                self.assertLess(heading_block["body_order"], table["body_order"])

    def test_document_session_preserves_every_source_table_including_preamble(self):
        cases = (
            ("proj_rux_03_002", RUX_PROTOCOL_DOCX),
            ("proj_d001", D001_PROTOCOL_DOCX),
            ("proj_my008_pnh_3_01", MY008_PNH_3_01_PROTOCOL_DOCX),
        )
        for project_id, source_path in cases:
            with self.subTest(project_id=project_id):
                parsed = parse_protocol_docx(source_path.name, source_path.read_bytes())
                document = self.service.document_for_revision(project_id)
                rendered_locators = [
                    block["source_locator"]
                    for section in document.sections
                    for block in section.content_blocks
                    if block.get("block_type") == "table"
                ]
                self.assertEqual(
                    [table.source_locator for table in parsed.tables],
                    rendered_locators,
                )
                preamble = document.sections[0]
                self.assertEqual("文档封面与前置内容", preamble.heading)
                self.assertTrue(
                    any(
                        block.get("block_type") == "table"
                        for block in preamble.content_blocks
                    )
                )

    def test_table_captions_and_notes_are_structured_without_duplicate_paragraph_blocks(self):
        for project_id in ("proj_rux_03_002", "proj_d001", "proj_my008_pnh_3_01"):
            with self.subTest(project_id=project_id):
                document = self.service.document_for_revision(project_id)
                all_blocks = [
                    block
                    for section in document.sections
                    for block in section.content_blocks
                ]
                table_blocks = [
                    block for block in all_blocks if block.get("block_type") == "table"
                ]
                self.assertTrue(table_blocks)
                for block in table_blocks:
                    structure = block.get("structured_table")
                    self.assertIsInstance(structure, dict)
                    self.assertIn("notes", structure)
                    caption = block.get("table_caption")
                    if caption and caption["review_status"] == "confirmed":
                        self.assertFalse(
                            any(
                                candidate.get("block_type") != "table"
                                and candidate.get("source_locator") == caption["source_locator"]
                                for candidate in all_blocks
                            )
                        )
                    metadata_by_id = {
                        item["note_id"]: item
                        for item in structure.get("source_note_metadata", [])
                    }
                    for note in structure.get("notes", []):
                        self.assertTrue(note["target_ids"])
                        metadata = metadata_by_id[note["note_id"]]
                        if (
                            metadata["source_kind"].startswith("post_table")
                            and metadata["review_status"] == "confirmed"
                        ):
                            self.assertFalse(
                                any(
                                    candidate.get("block_type") != "table"
                                    and candidate.get("source_locator") == metadata["source_locator"]
                                    for candidate in all_blocks
                                )
                            )

    def test_document_and_section_ids_are_content_stable_and_version_sensitive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            copied_protocol = Path(temp_dir) / RUX_PROTOCOL_DOCX.name
            copied_protocol.write_bytes(RUX_PROTOCOL_DOCX.read_bytes())
            config = replace(DEFAULT_WRITING_PACKAGES[0], protocol_path=copied_protocol)
            first = MedicalWritingDocumentService([config]).document_session("proj_rux_03_002")
            os.utime(copied_protocol, (1_700_000_000, 1_700_000_000))
            second = MedicalWritingDocumentService([config]).document_session("proj_rux_03_002")
            copied_protocol.write_bytes(copied_protocol.read_bytes() + b"\n")
            changed = MedicalWritingDocumentService([config]).document_session("proj_rux_03_002")

        self.assertEqual(first.document_id, second.document_id)
        self.assertEqual(
            [section.section_id for section in first.sections],
            [section.section_id for section in second.sections],
        )
        self.assertNotEqual(first.document_id, changed.document_id)
        self.assertNotEqual(
            [section.section_id for section in first.sections],
            [section.section_id for section in changed.sections],
        )

    def test_document_session_endpoints_are_canonical_and_do_not_expose_paths(self):
        session_response = self.client.get(
            "/api/projects/rux_03_002_monitoring_raw/medical-writing/document-session"
        )
        self.assertEqual(200, session_response.status_code, session_response.text)
        session = session_response.json()
        self.assertEqual("proj_rux_03_002", session["project_id"])
        section_id = session["sections"][0]["section_id"]

        section_response = self.client.get(
            f"/api/projects/rux_03_002_monitoring_raw/medical-writing/document-session/sections/{section_id}"
        )
        self.assertEqual(200, section_response.status_code, section_response.text)
        section_payload = section_response.json()
        self.assertEqual(section_id, section_payload["section_id"])
        self.assertNotIn("lazy_text_candidates", section_payload)
        combined = session_response.text + section_response.text
        self.assertNotIn("/Users/", combined)
        self.assertNotIn("server_path", combined)


def _unique_sections_by_heading(sections):
    result = {}
    for section in sections:
        result.setdefault(section.heading, section)
    return result


def _rich_text_plain_text(node):
    if node.get("type") == "text":
        return node.get("text", "")
    if node.get("type") == "hardBreak":
        return "\n"
    return "".join(_rich_text_plain_text(child) for child in node.get("content", []))


if __name__ == "__main__":
    unittest.main()
