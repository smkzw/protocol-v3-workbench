from __future__ import annotations

import base64
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.protocol_text_extractor import parse_protocol_docx  # noqa: E402


MGK10_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/MG-K10/SAR/4. Protocol/MG-K10-SAR-001_临床研究方案_ V2.1_20250919_clean版 .docx"
)
RUX_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
D001_PROTOCOL = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx"
)
PNH_PROTOCOL = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/3-01（MM外包）/方案/V1.1方案/"
    "（缺含研究者签字页方案）MY008211A-PNH-3-01-V1.1-通用版-2024.11.24-clean/研究方案/"
    "MY008211A-PNH-3-01_研究方案_V1.1_2025.1.7clean.docx"
)


class ProtocolTextExtractorTests(unittest.TestCase):
    def test_parse_protocol_docx_extracts_raw_paragraphs_tables_and_spans(self):
        content = _build_docx(
            title="CMS-D001 银屑病临床研究方案",
            paragraphs=[
                "CMS-D001 银屑病2、3期临床方案 v1.0",
                "方案编号：CMS-D001",
            ],
            table_rows=[
                ["字段", "原文"],
                ["研究题目", "评价 CMS-D001 的有效性和安全性"],
            ],
        )

        document = parse_protocol_docx("CMS-D001 protocol.docx", content)

        self.assertEqual("CMS-D001 银屑病临床研究方案", document.title)
        self.assertEqual("CMS-D001 protocol.docx", document.filename)
        self.assertGreaterEqual(len(document.paragraphs), 6)
        self.assertEqual(0, document.paragraphs[0].paragraph_index)
        self.assertEqual("docx:paragraph:0", document.paragraphs[0].source_locator)
        self.assertIn("方案编号：CMS-D001", [paragraph.text for paragraph in document.paragraphs])
        self.assertEqual(1, len(document.tables))
        self.assertEqual("研究题目", document.tables[0].rows[1][0].text)
        self.assertEqual("评价 CMS-D001 的有效性和安全性", document.tables[0].rows[1][1].text)
        self.assertTrue(any(span.kind == "table_cell" and span.table_index == 0 for span in document.spans))
        self.assertFalse(hasattr(document, "eligibility_rules"))
        self.assertFalse(hasattr(document, "medical_findings"))

    def test_parse_protocol_docx_preserves_inherited_heading_and_numbering_structure(self):
        content = _build_structured_docx()

        document = parse_protocol_docx("structured-protocol.docx", content)

        heading = next(paragraph for paragraph in document.paragraphs if paragraph.text == "研究人群")
        self.assertEqual("Heading2", heading.style_id)
        self.assertEqual("heading 2", heading.style_name)
        self.assertEqual("42", heading.num_id)
        self.assertEqual(1, heading.ilvl)
        self.assertEqual(1, heading.outline_level)
        self.assertEqual("decimal", heading.numbering_format)
        self.assertEqual("%1.%2", heading.numbering_level_text)
        self.assertEqual(1, heading.body_order)
        self.assertFalse(heading.is_in_table)

        table = document.tables[0]
        self.assertEqual(3, table.body_order)
        self.assertEqual("docx:table:0", table.source_locator)
        table_paragraph = next(
            paragraph for paragraph in document.paragraphs if paragraph.text == "主要终点"
        )
        self.assertTrue(table_paragraph.is_in_table)
        self.assertEqual(table.body_order, table_paragraph.body_order)
        self.assertEqual(0, table_paragraph.table_index)
        self.assertEqual(table.body_order, next(span for span in document.spans if span.text == "主要终点").body_order)
        self.assertEqual(64, len(document.source_hash))

    def test_parse_protocol_docx_preserves_word_run_and_paragraph_formatting(self):
        body_xml = (
            '<w:p><w:pPr><w:pStyle w:val="ProtocolBody"/>'
            '<w:jc w:val="both"/><w:spacing w:before="120" w:after="60" w:line="360"/>'
            '<w:ind w:firstLineChars="200"/></w:pPr>'
            '<w:r><w:rPr><w:b/><w:color w:val="C00000"/></w:rPr><w:t>主要</w:t></w:r>'
            '<w:r><w:t>终点 </w:t></w:r>'
            '<w:r><w:rPr><w:u w:val="single"/><w:highlight w:val="yellow"/></w:rPr><w:t>A</w:t></w:r>'
            '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>2</w:t></w:r>'
            '</w:p>'
        )
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:style w:type="paragraph" w:styleId="ProtocolBody">'
            '<w:name w:val="Protocol Body"/><w:rPr><w:rFonts w:eastAsia="宋体" w:ascii="Arial"/>'
            '<w:sz w:val="21"/></w:rPr></w:style></w:styles>'
        )

        document = parse_protocol_docx(
            "formatted-protocol.docx",
            _build_docx_with_body_xml(
                title="格式化研究方案",
                body_xml=body_xml,
                styles_xml=styles_xml,
            ),
        )

        paragraph = document.paragraphs[0]
        self.assertEqual("主要终点 A2", paragraph.text)
        self.assertEqual("paragraph", paragraph.rich_text["type"])
        self.assertEqual(
            {
                "textAlign": "justify",
                "spacingBeforePt": 6.0,
                "spacingAfterPt": 3.0,
                "lineHeight": 1.5,
                "firstLineIndentChars": 2.0,
                "stylePreset": "body",
            },
            paragraph.rich_text["attrs"],
        )
        content = paragraph.rich_text["content"]
        self.assertEqual(["主要", "终点 ", "A", "2"], [node["text"] for node in content])
        self.assertEqual(
            ["bold", "textStyle"],
            [mark["type"] for mark in content[0]["marks"]],
        )
        self.assertEqual(
            {"fontFamily": "宋体", "fontSize": "10.5pt", "color": "#C00000"},
            content[0]["marks"][1]["attrs"],
        )
        self.assertEqual(
            ["underline", "textStyle", "highlight"],
            [mark["type"] for mark in content[2]["marks"]],
        )
        self.assertEqual("superscript", content[3]["marks"][0]["type"])

    def test_parse_protocol_docx_preserves_plain_table_grid_and_stable_ids(self):
        content = _build_docx_with_table_xml(
            title="普通表",
            table_xml=(
                "<w:tbl>"
                "<w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>"
                f"<w:tr><w:trPr><w:tblHeader/></w:trPr>{_cell_xml('字段')}{_cell_xml('原文')}</w:tr>"
                f"<w:tr>{_cell_xml('研究题目')}{_cell_xml('评价有效性和安全性')}</w:tr>"
                "</w:tbl>"
            ),
        )

        first = parse_protocol_docx("plain-table.docx", content)
        second = parse_protocol_docx("plain-table.docx", content)
        table = first.tables[0]

        self.assertEqual("structured_table_v1", table.schema_version)
        self.assertEqual(2, table.column_count)
        self.assertEqual(1, table.header_row_count)
        self.assertEqual(table.table_id, second.tables[0].table_id)
        self.assertTrue(table.table_id.startswith("ptbl_"))
        self.assertEqual(
            [cell.cell_id for row in table.rows for cell in row],
            [cell.cell_id for row in second.tables[0].rows for cell in row],
        )
        self.assertEqual([0, 1], [cell.grid_column_index for cell in table.rows[0]])
        self.assertEqual(["header", "header"], [cell.style_role for cell in table.rows[0]])
        self.assertEqual(["body", "body"], [cell.style_role for cell in table.rows[1]])
        self.assertEqual("docx:table:0:row:1:cell:0", table.rows[1][0].source_locator)
        self.assertEqual(0, table.rows[1][0].cell_index)

    def test_parse_protocol_docx_preserves_horizontal_grid_span(self):
        content = _build_docx_with_table_xml(
            title="横向合并表",
            table_xml=(
                "<w:tbl>"
                "<w:tblGrid><w:gridCol/><w:gridCol/><w:gridCol/></w:tblGrid>"
                f"<w:tr>{_cell_xml('合并标题', grid_span=2)}{_cell_xml('第三列')}</w:tr>"
                f"<w:tr>{_cell_xml('A')}{_cell_xml('B')}{_cell_xml('C')}</w:tr>"
                "</w:tbl>"
            ),
        )

        table = parse_protocol_docx("horizontal-merge.docx", content).tables[0]

        self.assertEqual(3, table.column_count)
        self.assertEqual(2, table.rows[0][0].column_span)
        self.assertEqual(0, table.rows[0][0].grid_column_index)
        self.assertEqual(2, table.rows[0][1].grid_column_index)
        self.assertFalse(table.rows[0][0].hidden)
        self.assertEqual("none", table.rows[0][0].vertical_merge)

    def test_parse_protocol_docx_preserves_vertical_merge_parent_and_continuation_text(self):
        content = _build_docx_with_table_xml(
            title="纵向合并表",
            table_xml=(
                "<w:tbl>"
                "<w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>"
                f"<w:tr>{_cell_xml('合并起始', vertical_merge='restart')}{_cell_xml('R1')}</w:tr>"
                f"<w:tr>{_cell_xml('续接正文', vertical_merge='continue')}{_cell_xml('R2')}</w:tr>"
                f"<w:tr>{_cell_xml('', vertical_merge='continue')}{_cell_xml('R3')}</w:tr>"
                "</w:tbl>"
            ),
        )

        document = parse_protocol_docx("vertical-merge.docx", content)
        table = document.tables[0]
        parent = table.rows[0][0]
        first_continuation = table.rows[1][0]
        second_continuation = table.rows[2][0]

        self.assertEqual("restart", parent.vertical_merge)
        self.assertEqual(3, parent.row_span)
        self.assertFalse(parent.hidden)
        for continuation in (first_continuation, second_continuation):
            self.assertEqual("continue", continuation.vertical_merge)
            self.assertTrue(continuation.hidden)
            self.assertEqual(parent.cell_id, continuation.merge_parent_cell_id)
            self.assertEqual(parent.source_locator, continuation.merge_parent_source_locator)
            self.assertEqual(0, continuation.merge_parent_row_index)
            self.assertEqual(0, continuation.merge_parent_cell_index)
            self.assertEqual(0, continuation.merge_parent_grid_column_index)
        self.assertEqual("续接正文", first_continuation.text)
        self.assertIn("续接正文", [paragraph.text for paragraph in document.paragraphs])
        self.assertIn("续接正文", [span.text for span in document.spans])

    def test_parse_protocol_docx_associates_caption_notes_and_superscript_marker_without_consuming_body(self):
        content = _build_docx_with_body_xml(
            title="表题和表注",
            body_xml=(
                f"{_paragraph_xml('实验室检查见下表。')}"
                f"{_paragraph_xml('表 3 实验室检查', style_id='Caption')}"
                "<w:tbl><w:tblGrid><w:gridCol/><w:gridCol/></w:tblGrid>"
                f"<w:tr>{_cell_xml('项目')}{_cell_xml('访视')}</w:tr>"
                f"<w:tr>{_cell_xml('血常规', superscript='a')}{_cell_xml('筛选期')}</w:tr>"
                "</w:tbl>"
                f"{_paragraph_xml('a 根据新出现的安全性数据，可增加检测。')}"
                f"{_paragraph_xml('注：具体指标名称以中心实验室为准。')}"
                f"{_paragraph_xml('后续普通正文，不属于表注。')}"
            ),
            styles_xml=_caption_styles_xml(),
        )

        first = parse_protocol_docx("caption-notes.docx", content)
        second = parse_protocol_docx("renamed-caption-notes.docx", content)
        table = first.tables[0]

        self.assertIsNotNone(table.caption)
        self.assertEqual("表 3 实验室检查", table.caption.text)
        self.assertEqual("confirmed", table.caption.review_status)
        self.assertEqual("docx:paragraph:1", table.caption.source_locator)
        marker_note = next(note for note in table.notes if note.marker == "a")
        self.assertEqual("根据新出现的安全性数据，可增加检测。", marker_note.text)
        self.assertEqual("cell", marker_note.target_scope)
        self.assertEqual(table.rows[1][0].cell_id, marker_note.target_cell_id)
        self.assertEqual(1, marker_note.target_row_index)
        self.assertIn(":run:", marker_note.marker_source_locator)
        self.assertEqual("confirmed", marker_note.review_status)
        table_note = next(note for note in table.notes if note.marker == "注")
        self.assertEqual("table", table_note.target_scope)
        self.assertEqual("具体指标名称以中心实验室为准。", table_note.text)
        self.assertEqual(
            [note.note_id for note in table.notes],
            [note.note_id for note in second.tables[0].notes],
        )
        self.assertIn("实验室检查见下表。", [paragraph.text for paragraph in first.paragraphs])
        self.assertIn("后续普通正文，不属于表注。", [paragraph.text for paragraph in first.paragraphs])
        self.assertNotIn("后续普通正文，不属于表注。", [note.text for note in table.notes])

    def test_parse_protocol_docx_keeps_unmatched_superscript_as_pending_review(self):
        content = _build_docx_with_body_xml(
            title="未匹配表注",
            body_xml=(
                f"{_paragraph_xml('该表用于说明研究流程。')}"
                "<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid>"
                f"<w:tr>{_cell_xml('访视', superscript='b')}</w:tr>"
                "</w:tbl>"
                f"{_paragraph_xml('这是普通正文。')}"
            ),
        )

        table = parse_protocol_docx("pending-note.docx", content).tables[0]

        self.assertIsNone(table.caption)
        self.assertEqual(1, len(table.notes))
        note = table.notes[0]
        self.assertEqual("b", note.marker)
        self.assertEqual("", note.text)
        self.assertEqual("cell", note.target_scope)
        self.assertEqual("pending_human_review", note.review_status)
        self.assertIn("未找到可确定关联的表下注释", note.association_reason)

    def test_parse_protocol_docx_resolves_word_footnote_reference_in_table_cell(self):
        content = _build_docx_with_body_xml(
            title="Word脚注",
            body_xml=(
                "<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid>"
                "<w:tr><w:tc><w:p><w:r><w:t>检测项目</w:t></w:r>"
                '<w:r><w:rPr><w:rStyle w:val="FootnoteReference"/></w:rPr>'
                '<w:footnoteReference w:id="5"/></w:r></w:p></w:tc></w:tr>'
                "</w:tbl>"
            ),
            footnotes_xml=(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:footnote w:id="5"><w:p><w:r><w:t>由中心实验室完成。</w:t></w:r></w:p>'
                '<w:p><w:r><w:t>必要时允许复测。</w:t></w:r></w:p></w:footnote>'
                "</w:footnotes>"
            ),
        )

        note = parse_protocol_docx("footnote.docx", content).tables[0].notes[0]

        self.assertEqual("5", note.marker)
        self.assertEqual("由中心实验室完成。\n必要时允许复测。", note.text)
        self.assertEqual("docx:footnote:5", note.source_locator)
        self.assertEqual("cell", note.target_scope)
        self.assertEqual("confirmed", note.review_status)

    def test_parse_protocol_docx_resolves_word_endnote_and_ignores_trademark_superscript(self):
        content = _build_docx_with_body_xml(
            title="Word尾注",
            body_xml=(
                "<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid>"
                "<w:tr><w:tc><w:p><w:r><w:t>检测项目</w:t></w:r>"
                '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>®</w:t></w:r>'
                '<w:r><w:endnoteReference w:id="8"/></w:r>'
                "</w:p></w:tc></w:tr></w:tbl>"
            ),
            endnotes_xml=(
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:endnote w:id="8"><w:p><w:r><w:t>尾注正文。</w:t></w:r></w:p></w:endnote>'
                "</w:endnotes>"
            ),
        )

        notes = parse_protocol_docx("endnote.docx", content).tables[0].notes

        self.assertEqual(1, len(notes))
        self.assertEqual("8", notes[0].marker)
        self.assertEqual("尾注正文。", notes[0].text)
        self.assertEqual("word_endnote", notes[0].source_kind)
        self.assertEqual("confirmed", notes[0].review_status)

    def test_parse_protocol_docx_combines_adjacent_superscript_runs_into_one_marker(self):
        content = _build_docx_with_body_xml(
            title="拆分上标",
            body_xml=(
                "<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid>"
                "<w:tr><w:tc><w:p><w:r><w:t>检测项目</w:t></w:r>"
                '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>3</w:t></w:r>'
                '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>0</w:t></w:r>'
                "</w:p></w:tc></w:tr></w:tbl>"
                f"{_paragraph_xml('30 由中心实验室完成。')}"
            ),
        )

        table = parse_protocol_docx("split-superscript.docx", content).tables[0]

        self.assertEqual(1, len(table.notes))
        self.assertEqual("30", table.notes[0].marker)
        self.assertEqual("由中心实验室完成。", table.notes[0].text)
        self.assertIn(":run:1-2", table.notes[0].marker_source_locator)

    def test_parse_protocol_docx_recognizes_explicit_numbered_lettered_and_abbreviation_notes(self):
        content = _build_docx_with_body_xml(
            title="连续表注",
            body_xml=(
                "<w:tbl><w:tblGrid><w:gridCol/></w:tblGrid>"
                f"<w:tr>{_cell_xml('项目')}</w:tr></w:tbl>"
                f"{_paragraph_xml('注1：第一条说明。')}"
                f"{_paragraph_xml('注a 第二条说明。')}"
                f"{_paragraph_xml('注：①第三条说明。')}"
                f"{_paragraph_xml('缩写说明：ALT，丙氨酸氨基转移酶。')}"
                f"{_paragraph_xml('普通正文。')}"
            ),
        )

        table = parse_protocol_docx("explicit-notes.docx", content).tables[0]

        self.assertEqual(["1", "a", "①", "缩写说明"], [note.marker for note in table.notes])
        self.assertEqual(
            ["第一条说明。", "第二条说明。", "第三条说明。", "ALT，丙氨酸氨基转移酶。"],
            [note.text for note in table.notes],
        )
        self.assertNotIn("普通正文。", [note.text for note in table.notes])

    def test_parse_protocol_docx_accepts_path_without_content(self):
        with tempfile.NamedTemporaryFile(suffix=".docx") as temp_file:
            temp_docx = Path(temp_file.name)
            temp_docx.write_bytes(
                _build_docx(
                    title="Path 输入方案",
                    paragraphs=["方案编号：PATH-001"],
                    table_rows=[],
                )
            )
            document = parse_protocol_docx(temp_docx)

        self.assertEqual("Path 输入方案", document.title)
        self.assertEqual("方案编号：PATH-001", document.paragraphs[0].text)

    def test_unsupported_protocol_type_raises_clear_error(self):
        with self.assertRaisesRegex(ValueError, "unsupported protocol file type"):
            parse_protocol_docx("protocol.pdf", b"%PDF")

    @unittest.skipUnless(MGK10_PROTOCOL.exists(), "MG-K10 raw protocol not available on this machine")
    def test_parse_real_mgk10_protocol_extracts_title_related_source_text(self):
        document = parse_protocol_docx(MGK10_PROTOCOL.name, MGK10_PROTOCOL.read_bytes())
        text = "\n".join(paragraph.text for paragraph in document.paragraphs[:80])

        self.assertIn("MG-K10-SAR-001", text)
        self.assertIn("临床研究方案", text)
        self.assertTrue(document.paragraphs[0].source_locator.startswith("docx:"))
        self.assertNotIn("eligibility_rules", document.__dict__)

    @unittest.skipUnless(RUX_PROTOCOL.exists(), "RUX raw protocol not available on this machine")
    def test_parse_real_rux_protocol_extracts_title_related_source_text(self):
        document = parse_protocol_docx(RUX_PROTOCOL.name, RUX_PROTOCOL.read_bytes())
        text = "\n".join(paragraph.text for paragraph in document.paragraphs[:120])

        self.assertIn("RUX-03-002", text)
        self.assertIn("临床研究方案", text)
        self.assertGreater(len(document.paragraphs), 100)
        intro = next(
            paragraph
            for paragraph in document.paragraphs
            if paragraph.text == "简介" and not paragraph.is_in_table
        )
        rationale = next(
            paragraph
            for paragraph in document.paragraphs
            if paragraph.text == "治疗依据" and not paragraph.is_in_table
        )
        self.assertEqual("heading 1", intro.style_name)
        self.assertEqual(0, intro.outline_level)
        self.assertEqual("1", rationale.num_id)
        self.assertEqual(1, rationale.ilvl)
        self.assertEqual(1, rationale.outline_level)
        table_image = next(
            image
            for image in document.embedded_images
            if image.caption is not None
            and image.caption.text == "表 8 SCORAD-主观症状评分"
        )
        image_bytes = base64.b64decode(table_image.image_base64, validate=True)
        self.assertEqual("table_image", table_image.semantic_role)
        self.assertEqual("docx:drawing:1128:0", table_image.source_locator)
        self.assertEqual("image/png", table_image.media_type)
        self.assertEqual(
            table_image.image_sha256,
            hashlib.sha256(image_bytes).hexdigest(),
        )

    @unittest.skipUnless(D001_PROTOCOL.exists(), "CMS-D001 raw protocol not available on this machine")
    def test_parse_real_d001_protocol_extracts_title_related_source_text(self):
        document = parse_protocol_docx(D001_PROTOCOL.name, D001_PROTOCOL.read_bytes())
        text = "\n".join(paragraph.text for paragraph in document.paragraphs[:120])

        self.assertIn("CMS-D001", text)
        self.assertIn("银屑病", text)
        self.assertGreater(len(document.paragraphs), 100)
        synopsis = next(
            paragraph
            for paragraph in document.paragraphs
            if paragraph.text == "方案摘要" and not paragraph.is_in_table
        )
        synopsis_overview = next(
            paragraph
            for paragraph in document.paragraphs
            if paragraph.text == "概要" and not paragraph.is_in_table
        )
        self.assertEqual("自控1.标题", synopsis.style_name)
        self.assertEqual("12", synopsis.num_id)
        self.assertEqual(0, synopsis.ilvl)
        self.assertEqual(0, synopsis.outline_level)
        self.assertEqual("自控1.1 标题", synopsis_overview.style_name)
        self.assertEqual(1, synopsis_overview.ilvl)
        self.assertEqual(1, synopsis_overview.outline_level)
        serialized = json.dumps(document.__dict__, default=lambda value: value.__dict__, ensure_ascii=False)
        self.assertNotIn("/Users/", serialized)

    @unittest.skipUnless(
        RUX_PROTOCOL.exists() and D001_PROTOCOL.exists() and PNH_PROTOCOL.exists(),
        "RUX, D001, and PNH raw protocols are required",
    )
    def test_parse_real_protocols_extract_table_captions_notes_and_stable_targets(self):
        samples = [
            (RUX_PROTOCOL, 2, "试验流程表", 10),
            (D001_PROTOCOL, 5, "表 1 Ⅱ期临床研究阶段流程表", 20),
            (PNH_PROTOCOL, 14, "表1 研究流程表", 30),
        ]

        for path, table_index, expected_caption, minimum_notes in samples:
            with self.subTest(path=path.name):
                first = parse_protocol_docx(path)
                second = parse_protocol_docx(path)
                table = first.tables[table_index]
                self.assertIsNotNone(table.caption)
                self.assertEqual(expected_caption, table.caption.text)
                self.assertGreaterEqual(len(table.notes), minimum_notes)
                self.assertTrue(any(note.target_scope == "cell" for note in table.notes))
                self.assertTrue(all(note.target_table_id == table.table_id for note in table.notes))
                self.assertEqual(
                    [note.note_id for note in table.notes],
                    [note.note_id for note in second.tables[table_index].notes],
                )
                if path == PNH_PROTOCOL:
                    self.assertTrue(
                        any(
                            note.marker == "30" and "sC5b-9" in note.text
                            for note in table.notes
                        )
                    )
                    self.assertFalse(any(note.marker == "0" for note in table.notes))


def _build_docx(title: str, paragraphs: list[str], table_rows: list[list[str]]) -> bytes:
    document_parts = [_paragraph_xml(text) for text in paragraphs]
    if table_rows:
        document_parts.append(_table_xml(table_rows))
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(document_parts)}<w:sectPr /></w:body>"
        "</w:document>"
    )
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{escape(title)}</dc:title>"
        "</cp:coreProperties>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("docProps/core.xml", core_xml)
    return buffer.getvalue()


def _build_docx_with_table_xml(title: str, table_xml: str) -> bytes:
    return _build_docx_with_body_xml(title=title, body_xml=table_xml)


def _build_docx_with_body_xml(
    title: str,
    body_xml: str,
    *,
    styles_xml: str = "",
    footnotes_xml: str = "",
    endnotes_xml: str = "",
) -> bytes:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body_xml}<w:sectPr /></w:body>"
        "</w:document>"
    )
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{escape(title)}</dc:title>"
        "</cp:coreProperties>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("docProps/core.xml", core_xml)
        if styles_xml:
            archive.writestr("word/styles.xml", styles_xml)
        if footnotes_xml:
            archive.writestr("word/footnotes.xml", footnotes_xml)
        if endnotes_xml:
            archive.writestr("word/endnotes.xml", endnotes_xml)
    return buffer.getvalue()


def _build_structured_docx() -> bytes:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>研究设计</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>研究人群</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>计划纳入符合方案要求的受试者。</w:t></w:r></w:p>'
        f'{_table_xml([["终点类型", "终点"], ["主要", "主要终点"]])}'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>统计分析</w:t></w:r></w:p>'
        "<w:sectPr />"
        "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:styleId="Heading1">'
        '<w:name w:val="heading 1"/><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="42"/>'
        '</w:numPr><w:outlineLvl w:val="0"/></w:pPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2">'
        '<w:name w:val="heading 2"/><w:basedOn w:val="Heading1"/>'
        '<w:pPr><w:numPr><w:ilvl w:val="1"/></w:numPr><w:outlineLvl w:val="1"/></w:pPr>'
        '</w:style></w:styles>'
    )
    numbering_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:abstractNum w:abstractNumId="7">'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1"/></w:lvl>'
        '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/></w:lvl>'
        '</w:abstractNum><w:num w:numId="42"><w:abstractNumId w:val="7"/></w:num>'
        '</w:numbering>'
    )
    core_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>结构化研究方案</dc:title>'
        '</cp:coreProperties>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
        archive.writestr("word/styles.xml", styles_xml)
        archive.writestr("word/numbering.xml", numbering_xml)
        archive.writestr("docProps/core.xml", core_xml)
    return buffer.getvalue()


def _paragraph_xml(text: str, *, style_id: str = "") -> str:
    properties = f'<w:pPr><w:pStyle w:val="{escape(style_id)}"/></w:pPr>' if style_id else ""
    return f"<w:p>{properties}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"


def _table_xml(rows: list[list[str]]) -> str:
    row_xml = []
    for row in rows:
        cell_xml = "".join(f"<w:tc>{_paragraph_xml(value)}</w:tc>" for value in row)
        row_xml.append(f"<w:tr>{cell_xml}</w:tr>")
    return f"<w:tbl>{''.join(row_xml)}</w:tbl>"


def _cell_xml(
    text: str,
    grid_span: int = 1,
    vertical_merge: str = "none",
    superscript: str = "",
) -> str:
    properties = []
    if grid_span > 1:
        properties.append(f'<w:gridSpan w:val="{grid_span}"/>')
    if vertical_merge == "restart":
        properties.append('<w:vMerge w:val="restart"/>')
    elif vertical_merge == "continue":
        properties.append("<w:vMerge/>")
    tc_properties = f"<w:tcPr>{''.join(properties)}</w:tcPr>" if properties else ""
    marker_xml = (
        f'<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>{escape(superscript)}</w:t></w:r>'
        if superscript
        else ""
    )
    return f"<w:tc>{tc_properties}<w:p><w:r><w:t>{escape(text)}</w:t></w:r>{marker_xml}</w:p></w:tc>"


def _caption_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="caption"/></w:style>'
        "</w:styles>"
    )


if __name__ == "__main__":
    unittest.main()
