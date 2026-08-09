from __future__ import annotations

import hashlib
import io
import unittest
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from packages.contracts.workbench_contracts import WritingReferenceDocumentArtifact
from services.api.app.writing_reference_docx import (
    DOCX_PARSER_VERSION,
    extract_docx_sections,
)


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def docx_artifact(payload: bytes) -> WritingReferenceDocumentArtifact:
    return WritingReferenceDocumentArtifact(
        artifact_id="wref_upload_docx_001",
        project_id="proj_rux_03_002",
        snapshot_id="manual_upload_001",
        nct_id="NCT05014438",
        source_document_id="manual_protocol_001",
        document_type="protocol_sap",
        filename="Protocol_and_SAP.docx",
        requested_url="upload://Protocol_and_SAP.docx",
        final_url="upload://Protocol_and_SAP.docx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        actual_size=len(payload),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        file_integrity_status="verified",
        created_by="medical_manager",
        created_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )


def build_docx(body_xml: str) -> bytes:
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.'
        'wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body_xml}'
        "<w:sectPr/></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def paragraph_xml(text: str, *, style: str = "", bold: bool = False) -> str:
    properties = f'<w:pPr><w:pStyle w:val="{escape(style)}"/></w:pPr>' if style else ""
    run_properties = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return (
        f"<w:p>{properties}<w:r>{run_properties}"
        f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'
    )


def table_xml(rows: list[list[str]], *, bold_first_row: bool = False) -> str:
    row_values = []
    for row_index, row in enumerate(rows):
        cells = []
        for cell in row:
            cells.append(
                "<w:tc>"
                + paragraph_xml(cell, bold=bold_first_row and row_index == 0)
                + "</w:tc>"
            )
        row_values.append("<w:tr>" + "".join(cells) + "</w:tr>")
    return "<w:tbl>" + "".join(row_values) + "</w:tbl>"


class WritingReferenceDocxTests(unittest.TestCase):
    def test_preserves_paragraph_and_table_row_order_and_text(self) -> None:
        payload = build_docx(
            paragraph_xml("1 Study Overview", style="Heading1")
            + (
                "<w:p><w:r><w:t>Paragraph before</w:t></w:r>"
                '<w:r><w:t xml:space="preserve"> the table.</w:t></w:r></w:p>'
            )
            + table_xml(
                [
                    ["Visit", "Procedure"],
                    ["Screening", "Consent & eligibility"],
                ],
                bold_first_row=True,
            )
            + paragraph_xml("Paragraph after the table.")
        )

        result = extract_docx_sections(payload, docx_artifact(payload))

        self.assertEqual(
            [
                "1 Study Overview",
                "Paragraph before the table.",
                "Visit\tProcedure",
                "Screening\tConsent & eligibility",
                "Paragraph after the table.",
            ],
            [span.source_text for span in result.spans],
        )
        self.assertEqual(list(range(5)), [span.block_index for span in result.spans])
        self.assertTrue(all(span.physical_page == 1 for span in result.spans))
        self.assertEqual(
            [
                f"upload:NCT05014438:wref_upload_docx_001:p1:b{index}"
                for index in range(5)
            ],
            [span.source_locator for span in result.spans],
        )
        self.assertTrue(
            all(
                span.source_text_sha256
                == hashlib.sha256(span.source_text.encode("utf-8")).hexdigest()
                for span in result.spans
            )
        )

    def test_maps_m11_headings_and_carries_schedule_anchor_into_table_rows(self) -> None:
        payload = build_docx(
            paragraph_xml("5 Study Objectives and Endpoints", style="Heading1")
            + paragraph_xml("The primary endpoint is change from baseline at Week 16.")
            + paragraph_xml("APPENDIX 1: SCHEDULE OF ASSESSMENTS", style="Heading1")
            + table_xml(
                [["Visit", "Procedure"], ["Screening", "Hematology"]],
                bold_first_row=True,
            )
            + paragraph_xml("10 Statistical Considerations", style="Heading1")
            + paragraph_xml("The primary analysis uses the full analysis set.")
        )

        result = extract_docx_sections(payload, docx_artifact(payload))
        spans = {span.source_text: span for span in result.spans}

        self.assertEqual(
            "objectives_endpoints",
            spans["The primary endpoint is change from baseline at Week 16."].ich_m11_anchor,
        )
        self.assertEqual("schedule", spans["Visit\tProcedure"].ich_m11_anchor)
        self.assertEqual("schedule", spans["Screening\tHematology"].ich_m11_anchor)
        self.assertEqual(
            "statistics",
            spans["The primary analysis uses the full analysis set."].ich_m11_anchor,
        )

    def test_maps_chinese_protocol_headings_and_carries_anchor_into_content(self) -> None:
        payload = build_docx(
            paragraph_xml("5 研究目的与终点", style="标题1")
            + paragraph_xml("主要终点为第16周较基线的变化。")
            + paragraph_xml("6 入选标准", style="标题1")
            + paragraph_xml("年龄18至75周岁。")
            + paragraph_xml("表1 研究流程表", style="标题1")
            + table_xml([["研究项目", "筛选期"], ["血常规", "X"]])
            + paragraph_xml("10 统计学分析", style="标题1")
            + paragraph_xml("主要分析集为全分析集。")
        )

        result = extract_docx_sections(payload, docx_artifact(payload))
        spans = {span.source_text: span for span in result.spans}

        self.assertEqual("objectives_endpoints", spans["主要终点为第16周较基线的变化。"].ich_m11_anchor)
        self.assertEqual("eligibility", spans["年龄18至75周岁。"].ich_m11_anchor)
        self.assertEqual("schedule", spans["血常规\tX"].ich_m11_anchor)
        self.assertEqual("statistics", spans["主要分析集为全分析集。"].ich_m11_anchor)

    def test_table_keyword_matches_do_not_leak_into_following_unrelated_rows(self) -> None:
        payload = build_docx(
            table_xml(
                [
                    ["缩写", "英文", "中文"],
                    ["CTCAE", "Adverse Events", "不良事件通用术语标准"],
                    ["PK", "Pharmacokinetics", "药代动力学"],
                ],
                bold_first_row=True,
            )
        )

        result = extract_docx_sections(payload, docx_artifact(payload))
        spans = {span.source_text: span for span in result.spans}

        self.assertEqual("safety", spans["CTCAE\tAdverse Events\t不良事件通用术语标准"].ich_m11_anchor)
        self.assertEqual("unmapped", spans["PK\tPharmacokinetics\t药代动力学"].ich_m11_anchor)

    def test_schedule_context_wins_over_safety_words_inside_the_same_table(self) -> None:
        payload = build_docx(
            paragraph_xml("表1 Ⅱ期临床研究阶段流程表", style="标题1")
            + table_xml(
                [
                    ["项目", "筛选期", "安全性随访"],
                    ["血常规", "X", "X"],
                ]
            )
        )

        result = extract_docx_sections(payload, docx_artifact(payload))

        self.assertTrue(result.spans)
        self.assertTrue(all(span.ich_m11_anchor == "schedule" for span in result.spans))

    def test_extraction_revision_and_span_ids_are_stable_and_content_bound(self) -> None:
        payload = build_docx(paragraph_xml("Protocol Summary", style="Heading1"))
        source = docx_artifact(payload)

        first = extract_docx_sections(payload, source)
        second = extract_docx_sections(payload, source)

        self.assertEqual(DOCX_PARSER_VERSION, first.parser_version)
        self.assertIn(source.content_sha256, first.extraction_revision)
        self.assertEqual(first.extraction_revision, second.extraction_revision)
        self.assertEqual(
            [span.span_id for span in first.spans],
            [span.span_id for span in second.spans],
        )

    def test_rejects_non_docx_and_empty_docx(self) -> None:
        not_docx = b"this is not a ZIP package"
        empty_docx = build_docx(paragraph_xml(""))

        with self.subTest("non-DOCX payload"):
            with self.assertRaisesRegex(ValueError, "DOCX|ZIP"):
                extract_docx_sections(not_docx, docx_artifact(not_docx))
        with self.subTest("empty DOCX"):
            with self.assertRaisesRegex(ValueError, "no extractable text"):
                extract_docx_sections(empty_docx, docx_artifact(empty_docx))

    def test_rejects_zip_without_docx_content_type(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
            )
            archive.writestr(
                "word/document.xml",
                f'<w:document xmlns:w="{WORD_NS}"><w:body/></w:document>',
            )
        payload = buffer.getvalue()

        with self.assertRaisesRegex(ValueError, "not an OOXML DOCX"):
            extract_docx_sections(payload, docx_artifact(payload))

    def test_rejects_artifact_hash_and_size_mismatches(self) -> None:
        payload = build_docx(paragraph_xml("Protocol Summary", style="Heading1"))
        source = docx_artifact(payload)

        with self.subTest("hash"):
            with self.assertRaisesRegex(ValueError, "hash"):
                extract_docx_sections(
                    payload,
                    source.model_copy(update={"content_sha256": "0" * 64}),
                )
        with self.subTest("size"):
            with self.assertRaisesRegex(ValueError, "size"):
                extract_docx_sections(
                    payload,
                    source.model_copy(update={"actual_size": len(payload) + 1}),
                )


if __name__ == "__main__":
    unittest.main()
