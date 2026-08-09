from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pymupdf

from packages.contracts.workbench_contracts import WritingReferenceDocumentArtifact
from services.api.app.writing_reference import (
    EXTRACTION_MAPPING_VERSION,
    _PdfTextBlock,
    _source_fragment,
    extract_pdf_sections,
)
from services.api.app.writing_reference_repository import _payload_hash


REAL_NCT02290613_SAP = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/runtime/"
    "writing_reference_artifacts/b18d0f5682fe9b4e/"
    "wref_doc_e4358e70a88df5bb4d6f/"
    "c59410de222bb43a7951f9802253ad6dcface748c4513df0b21b7a1ed80126fe.pdf"
)


def artifact(content_hash: str) -> WritingReferenceDocumentArtifact:
    return WritingReferenceDocumentArtifact(
        artifact_id="wref_doc_extract_001",
        project_id="proj_rux_03_002",
        snapshot_id="wref_search_001",
        nct_id="NCT05014438",
        source_document_id="ctgov_NCT05014438_000",
        document_type="protocol_sap",
        filename="Prot_SAP_000.pdf",
        requested_url="https://clinicaltrials.gov/ProvidedDocs/38/NCT05014438/Prot_SAP_000.pdf",
        final_url="https://clinicaltrials.gov/ProvidedDocs/38/NCT05014438/Prot_SAP_000.pdf",
        content_type="application/pdf",
        actual_size=0,
        content_sha256=content_hash,
        file_integrity_status="verified",
        created_by="medical_manager",
        created_at=datetime(2026, 7, 12, tzinfo=timezone.utc),
    )


def pdf_fixture() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 50), "STUDY PROTOCOL", fontsize=14)
    page.insert_text((72, 72), "5 Study Objectives and Endpoints", fontsize=14)
    page.insert_text((72, 100), "The primary endpoint is change from baseline at Week 16.", fontsize=10)
    page2 = document.new_page()
    page2.insert_text((72, 72), "10 Statistical Considerations", fontsize=14)
    page2.insert_text((72, 100), "Statistical Analysis Plan", fontsize=12)
    page2.insert_text((72, 120), "The primary analysis uses the full analysis set.", fontsize=10)
    page2.insert_text((72, 140), "Missing data and multiplicity are addressed using statistical methods.", fontsize=10)
    page3 = document.new_page()
    page3.insert_text((72, 72), "APPENDIX 1: SCHEDULE OF ASSESSMENTS", fontsize=10)
    page3.insert_text((72, 100), "Screening Day 1 Week 4 Week 12", fontsize=9)
    page3.insert_text((72, 115), "Hematology", fontsize=12)
    page3.insert_text((72, 130), "All adverse events must be recorded in the eCRF.", fontsize=9)
    page3.insert_text((72, 160), "Visit procedures continue below this sentence.", fontsize=9)
    page4 = document.new_page()
    page4.insert_text((72, 72), "4 Other Study Procedures", fontsize=14)
    page4.insert_text((72, 100), "Day and Week details are outlined in the Schedule of Assessments (see Appendix 1).", fontsize=9)
    page5 = document.new_page()
    page5.insert_text((72, 72), "4 Other Study Information", fontsize=14)
    page5.insert_text(
        (72, 100),
        "The primary efficacy variable is response rate through Week 12.",
        fontsize=9,
    )
    payload = document.tobytes()
    document.close()
    return payload


def cross_page_fixture() -> bytes:
    document = pymupdf.open()
    for page_number in range(1, 5):
        page = document.new_page()
        page.insert_text(
            (72, 50),
            f"Sponsor Confidential Page {page_number} of 4 Protocol ABC-001",
            fontsize=9,
        )
        page.insert_text((210, 410), "Commercially Confidential Information", fontsize=9)
        page.insert_text(
            (72, 755),
            f"CONFIDENTIAL AND PROPRIETARY {page_number} of 4",
            fontsize=8,
        )
    document[0].insert_textbox(
        pymupdf.Rect(72, 685, 540, 735),
        "This paragraph is intentionally complete and must remain separate from the next page.",
        fontsize=10,
    )
    document[1].insert_textbox(
        pymupdf.Rect(72, 90, 540, 145),
        "this lowercase paragraph starts a new sentence despite its position at the page top.",
        fontsize=10,
    )
    document[1].insert_textbox(
        pymupdf.Rect(72, 685, 540, 735),
        "During a declared public health emergency that prevents on-site study visits,",
        fontsize=10,
    )
    document[2].insert_textbox(
        pymupdf.Rect(72, 90, 540, 145),
        "alternative methods of providing continuing care may be implemented by the investigator.",
        fontsize=10,
    )
    document[2].insert_textbox(
        pymupdf.Rect(72, 685, 540, 735),
        "The assessments required during the treatment period include",
        fontsize=10,
    )
    document[3].insert_textbox(
        pymupdf.Rect(72, 90, 540, 145),
        "(a) hematology and chemistry; (b) urinalysis; and (c) vital signs.",
        fontsize=10,
    )
    payload = document.tobytes()
    document.close()
    return payload


def landscape_running_header_fixture() -> bytes:
    document = pymupdf.open()
    for page_number in range(1, 4):
        page = document.new_page(width=842, height=595)
        page.insert_text(
            (58, 100),
            f"Sponsor Confidential Page {page_number} Protocol LANDSCAPE-001",
            fontsize=9,
        )
        page.insert_text((58, 145), "APPENDIX 1: SCHEDULE OF ASSESSMENTS", fontsize=11)
        page.insert_text(
            (58, 180),
            f"Visit {page_number} includes hematology and safety assessments.",
            fontsize=9,
        )
        page.insert_text(
            (325, 100 * page_number),
            "Commercially Confidential Information",
            fontsize=8,
        )
    payload = document.tobytes()
    document.close()
    return payload


def ruled_table_fixture() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 50), "5 Study Objectives and Endpoints", fontsize=14)
    x0, x1, x2 = 72, 300, 540
    y0, y1, y2, y3 = 90, 120, 180, 240
    page.draw_rect(pymupdf.Rect(x0, y0, x2, y3), color=(0, 0, 0), width=0.8)
    page.draw_line((x1, y0), (x1, y3), color=(0, 0, 0), width=0.8)
    for y in (y1, y2):
        page.draw_line((x0, y), (x2, y), color=(0, 0, 0), width=0.8)
    page.insert_text((82, 110), "Objectives", fontsize=9)
    page.insert_text((310, 110), "Endpoints", fontsize=9)
    page.insert_textbox(
        pymupdf.Rect(82, 130, 290, 172),
        "Compare active treatment with placebo.",
        fontsize=9,
    )
    page.insert_textbox(
        pymupdf.Rect(310, 130, 530, 172),
        "Change from baseline at Week 16.",
        fontsize=9,
    )
    page.insert_textbox(
        pymupdf.Rect(82, 190, 290, 232),
        "Evaluate safety and tolerability.",
        fontsize=9,
    )
    page.insert_textbox(
        pymupdf.Rect(310, 190, 530, 232),
        "Number of treatment-emergent adverse events.",
        fontsize=9,
    )
    page.insert_text(
        (72, 275),
        "Abbreviations: AD = atopic dermatitis; ADSD = Atopic Dermatitis Symptom",
        fontsize=8,
    )
    page.insert_text(
        (72, 292),
        "Diary; DLQI = Dermatology Life Quality Index.",
        fontsize=8,
    )
    payload = document.tobytes()
    document.close()
    return payload


class WritingReferenceExtractionTests(unittest.TestCase):
    @unittest.skipUnless(
        REAL_NCT02290613_SAP.is_file(),
        "real NCT02290613 SAP fixture is not available",
    )
    def test_real_sap_parser_bbox_drift_has_stable_versioned_fragment_hash(self) -> None:
        payload = REAL_NCT02290613_SAP.read_bytes()
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={
                "actual_size": len(payload),
                "artifact_id": "wref_doc_e4358e70a88df5bb4d6f",
                "project_id": "proj_user_7f4a47cb5b85",
                "snapshot_id": "wref_search_dfb256a4ae9d9b2f26df",
                "nct_id": "NCT02290613",
                "source_document_id": "ctgov_NCT02290613_001",
                "document_type": "sap",
                "filename": "SAP_001.pdf",
            }
        )
        parsed = extract_pdf_sections(payload, source)
        real_fragment = parsed.spans[16].source_fragments[0]
        parser_variant_a = _PdfTextBlock(
            physical_page=real_fragment.physical_page,
            block_index=real_fragment.block_index,
            source_locator=real_fragment.source_locator,
            bbox=(
                70.94400024414062,
                184.20008850097656,
                527.3840942382812,
                196.62657165527344,
            ),
            page_width=595.32,
            page_height=841.92,
            source_text=real_fragment.source_text,
            source_text_sha256=real_fragment.source_text_sha256,
            max_size=10.0,
            is_bold=False,
            schedule_page=False,
            layout_role=real_fragment.layout_role,
        )
        parser_variant_b = replace(
            parser_variant_a,
            bbox=(
                70.94400024414062,
                183.0800018310547,
                527.3840942382812,
                196.62657165527344,
            ),
        )

        fragment_a = _source_fragment(parser_variant_a)
        fragment_b = _source_fragment(parser_variant_b)
        fragment_hash_a = _payload_hash(fragment_a.model_dump(mode="json"))
        fragment_hash_b = _payload_hash(fragment_b.model_dump(mode="json"))

        spans_a = list(parsed.spans)
        spans_b = list(parsed.spans)
        spans_a[16] = spans_a[16].model_copy(
            update={"source_fragments": [fragment_a]}
        )
        spans_b[16] = spans_b[16].model_copy(
            update={"source_fragments": [fragment_b]}
        )
        extraction_hash_a = _payload_hash(
            parsed.model_copy(update={"spans": spans_a}).model_dump(mode="json")
        )
        extraction_hash_b = _payload_hash(
            parsed.model_copy(update={"spans": spans_b}).model_dump(mode="json")
        )

        self.assertEqual(
            "m11map_v11_ocr_reanchor_table_rows_bbox_q2pt",
            EXTRACTION_MAPPING_VERSION,
        )
        self.assertEqual(fragment_hash_a, fragment_hash_b)
        self.assertEqual(extraction_hash_a, extraction_hash_b)

    def test_generic_pdf_extraction_preserves_page_block_hash_and_m11_candidate(self) -> None:
        payload = pdf_fixture()
        source = artifact(__import__("hashlib").sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )

        result = extract_pdf_sections(payload, source)

        self.assertEqual(5, result.page_count)
        self.assertEqual("pending_visual_and_medical_structure_review", result.status)
        self.assertGreaterEqual(len(result.spans), 4)
        self.assertTrue(any(span.ich_m11_anchor == "objectives_endpoints" for span in result.spans))
        self.assertTrue(any(span.ich_m11_anchor == "statistics" for span in result.spans))
        schedule_spans = [span for span in result.spans if span.physical_page == 3]
        self.assertTrue(any(span.ich_m11_anchor == "schedule" for span in schedule_spans))
        self.assertEqual(
            "schedule",
            next(span for span in schedule_spans if "Visit procedures" in span.source_text).ich_m11_anchor,
        )
        self.assertEqual(
            "schedule",
            next(span for span in schedule_spans if "Hematology" in span.source_text).ich_m11_anchor,
        )
        self.assertEqual(
            "unmapped",
            next(span for span in result.spans if span.physical_page == 4 and "Schedule of Assessments" in span.source_text).ich_m11_anchor,
        )
        self.assertEqual(
            "objectives_endpoints",
            next(
                span
                for span in result.spans
                if span.physical_page == 5 and "primary efficacy variable" in span.source_text
            ).ich_m11_anchor,
        )
        self.assertTrue(all(len(span.source_text_sha256) == 64 for span in result.spans))
        self.assertTrue(all(span.source_fragments for span in result.spans))
        self.assertTrue(all("/Users/" not in span.source_locator for span in result.spans))

    def test_cross_page_continuation_is_merged_with_provenance_and_false_boundaries_stay_separate(self) -> None:
        payload = cross_page_fixture()
        source = artifact(__import__("hashlib").sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )

        result = extract_pdf_sections(payload, source)

        merged = [
            span
            for span in result.spans
            if span.semantic_merge_method == "cross_page_continuation_v1"
        ]
        self.assertEqual(1, len(merged))
        self.assertIn("public health emergency", merged[0].source_text)
        self.assertIn("alternative methods", merged[0].source_text)
        self.assertEqual([2, 3], [item.physical_page for item in merged[0].source_fragments])
        self.assertIn("repeated_margin_interstitials_skipped", merged[0].semantic_merge_reason_codes)
        self.assertTrue(merged[0].skipped_interstitials)
        self.assertTrue(
            any(
                span.source_text.startswith("This paragraph is intentionally complete")
                for span in result.spans
            )
        )
        self.assertTrue(
            any(
                span.source_text.startswith("this lowercase paragraph starts")
                for span in result.spans
            )
        )
        self.assertFalse(any("include (a) hematology" in span.source_text for span in result.spans))
        overlays = [
            span
            for span in result.spans
            if span.source_fragments[0].layout_role == "repeated_visual_overlay"
        ]
        self.assertEqual(4, len(overlays))
        self.assertTrue(all(span.ich_m11_anchor == "unmapped" for span in overlays))
        self.assertEqual(8, len(result.excluded_layout_fragments))

    def test_landscape_running_header_is_excluded_before_schedule_mapping(self) -> None:
        payload = landscape_running_header_fixture()
        source = artifact(__import__("hashlib").sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )

        result = extract_pdf_sections(payload, source)

        self.assertFalse(any("Sponsor Confidential Page" in span.source_text for span in result.spans))
        headers = [
            item
            for item in result.excluded_layout_fragments
            if item.fragment.layout_role == "repeated_margin_header"
        ]
        self.assertEqual(3, len(headers))
        overlays = [
            span
            for span in result.spans
            if span.source_fragments[0].layout_role == "repeated_visual_overlay"
        ]
        self.assertEqual(3, len(overlays))
        self.assertTrue(all(span.ich_m11_anchor == "unmapped" for span in overlays))
        self.assertTrue(
            all(
                span.ich_m11_anchor == "schedule"
                for span in result.spans
                if "hematology and safety assessments" in span.source_text
            )
        )

    def test_ruled_table_is_extracted_as_cell_preserving_rows(self) -> None:
        payload = ruled_table_fixture()
        source = artifact(__import__("hashlib").sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )

        result = extract_pdf_sections(payload, source)

        rows = [span for span in result.spans if span.source_text.startswith("|")]
        self.assertEqual(3, len(rows))
        self.assertEqual("| Objectives | Endpoints |", rows[0].source_text)
        self.assertIn(
            "| Compare active treatment with placebo. | "
            "Change from baseline at Week 16. |",
            [row.source_text for row in rows],
        )
        self.assertFalse(
            any(
                span.source_text == "Objectives"
                or span.source_text == "Endpoints"
                for span in result.spans
            )
        )
        self.assertTrue(
            all(row.ich_m11_anchor == "objectives_endpoints" for row in rows)
        )
        abbreviation = next(
            span
            for span in result.spans
            if span.source_text.startswith("Abbreviations:")
        )
        self.assertIn("Atopic Dermatitis Symptom Diary", abbreviation.source_text)
        self.assertEqual(
            "adjacent_abbreviation_continuation_v1",
            abbreviation.semantic_merge_method,
        )

    def test_hash_mismatch_fails_and_registered_pdf_content_remains_parseable(self) -> None:
        payload = pdf_fixture()
        with self.assertRaisesRegex(ValueError, "hash"):
            extract_pdf_sections(payload, artifact("0" * 64))

        suspicious = payload + b"\n/JavaScript\n"
        result = extract_pdf_sections(
            suspicious,
            artifact(__import__("hashlib").sha256(suspicious).hexdigest()).model_copy(
                update={"actual_size": len(suspicious)}
            ),
        )
        self.assertGreaterEqual(len(result.spans), 4)

    def test_manual_pdf_uses_upload_locator_without_claiming_clinicaltrials_source(self) -> None:
        payload = pdf_fixture()
        source = artifact(__import__("hashlib").sha256(payload).hexdigest()).model_copy(
            update={
                "actual_size": len(payload),
                "source_status": "user_uploaded",
                "source_document_id": "manual_001",
                "requested_url": "manual-upload:manual_001",
                "final_url": "manual-upload:manual_001",
            }
        )

        result = extract_pdf_sections(payload, source)

        self.assertTrue(result.spans)
        self.assertTrue(all(span.source_locator.startswith("upload:") for span in result.spans))
        self.assertFalse(any(span.source_locator.startswith("ctgov:") for span in result.spans))

    def test_blank_or_scanned_pdf_returns_zero_text_pages_for_ocr_recovery(self) -> None:
        """A fully scanned PDF with no native text blocks returns an
        empty-spans result with every page as a zero-text page, so the
        extraction service OCR recovery path can process it.  The
        extraction service (not the pure function) is responsible for
        raising if no OCR runner is configured."""
        document = pymupdf.open()
        document.new_page()
        payload = document.tobytes()
        document.close()
        source = artifact(__import__("hashlib").sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )

        result = extract_pdf_sections(payload, source)
        self.assertEqual([], result.spans)
        self.assertEqual([1], result.zero_text_pages)


if __name__ == "__main__":
    unittest.main()
