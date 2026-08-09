from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pymupdf

from packages.contracts.workbench_contracts import WritingReferenceExtractionResult
from services.api.app.ocr_gateway import OcrResult
from services.api.app.writing_reference import (
    WritingReferenceExtractionService,
    extract_pdf_sections,
)
from services.api.app.writing_reference_ocr_evidence import (
    build_ocr_evidence_relpath,
    png_dimensions,
    resolve_ocr_evidence_path,
    write_immutable_ocr_png,
)
from services.api.app.writing_reference_repository import WritingReferenceRepository
from tests.test_writing_reference_extraction import artifact
from tests.test_writing_reference_extraction import pdf_fixture
from tests.test_writing_reference_repository import PROJECT_ID, snapshot


def blank_pdf(page_count: int) -> bytes:
    document = pymupdf.open()
    for _ in range(page_count):
        document.new_page()
    payload = document.tobytes()
    document.close()
    return payload


def png_fixture(*, dpi: int = 200) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    pixmap = page.get_pixmap(dpi=dpi)
    payload = pixmap.tobytes("png")
    document.close()
    return payload


class ImmutableOcrEvidenceTests(unittest.TestCase):
    def test_relpath_and_png_are_replayable_but_not_overwritable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = png_fixture()
            digest = hashlib.sha256(payload).hexdigest()
            relpath = build_ocr_evidence_relpath(
                "project/document/source.pdf",
                "pymupdf_1.26.4_m11map_v9_0123456789abcdef",
                143,
                200,
                digest,
            )

            self.assertIn("/ocr/", relpath)
            self.assertTrue(relpath.endswith(f"_{digest[:16]}.png"))
            self.assertTrue(
                write_immutable_ocr_png(root, relpath, payload, digest)
            )
            self.assertFalse(
                write_immutable_ocr_png(root, relpath, payload, digest)
            )
            stored = resolve_ocr_evidence_path(root, relpath)
            self.assertEqual(digest, hashlib.sha256(stored.read_bytes()).hexdigest())
            width, height = png_dimensions(stored.read_bytes())
            self.assertGreater(width, 1600)
            self.assertGreater(height, 2300)

            stored.write_bytes(payload + b"changed")
            with self.assertRaisesRegex(
                RuntimeError, "immutable OCR evidence PNG hash mismatch"
            ):
                write_immutable_ocr_png(root, relpath, payload, digest)

    def test_new_relpath_rejects_non_200_dpi_and_unsafe_revision(self) -> None:
        digest = hashlib.sha256(png_fixture()).hexdigest()
        with self.assertRaisesRegex(ValueError, "200 DPI"):
            build_ocr_evidence_relpath(
                "project/document/source.pdf",
                "extract_r1",
                1,
                300,
                digest,
            )
        with self.assertRaisesRegex(ValueError, "path-safe"):
            build_ocr_evidence_relpath(
                "project/document/source.pdf",
                "../extract_r1",
                1,
                200,
                digest,
            )


class WritingReferenceOcrEvidenceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.artifact_root = root / "artifacts"
        self.db_path = root / "writing_reference.sqlite3"
        self.repo = WritingReferenceRepository(self.db_path)
        self.repo.save_search_snapshot(snapshot(), idempotency_key="ocr-search")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _register_pdf(self, payload: bytes, *, key: str) -> object:
        source = artifact(hashlib.sha256(payload).hexdigest()).model_copy(
            update={"actual_size": len(payload)}
        )
        relative = f"safe/{source.artifact_id}/{key}.pdf"
        path = self.artifact_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        self.repo.save_document_artifact(
            source,
            storage_relpath=relative,
            idempotency_key=f"ocr-artifact-{key}",
        )
        return source

    def _stored_extraction(
        self, artifact_id: str, extraction_revision: str
    ) -> WritingReferenceExtractionResult:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM writing_reference_extractions
                WHERE project_id=? AND artifact_id=? AND extraction_revision=?
                """,
                (PROJECT_ID, artifact_id, extraction_revision),
            ).fetchone()
        self.assertIsNotNone(row)
        return WritingReferenceExtractionResult.model_validate(
            json.loads(row[0])
        )

    def test_text_and_empty_pages_both_persist_200_dpi_sidecars(self) -> None:
        source = self._register_pdf(blank_pdf(2), key="text-empty")
        calls: list[tuple[int, int, str, bytes]] = []

        def fake_ocr(
            page: int, dpi: int, model: str, image_bytes: bytes
        ) -> str:
            calls.append((page, dpi, model, image_bytes))
            return "5 Study Objectives and Endpoints" if page == 1 else " \n "

        result = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=fake_ocr,
        ).extract(
            PROJECT_ID,
            source.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="ocr-extract-text-empty",
        )

        self.assertEqual(2, len(calls))
        self.assertTrue(
            all(dpi == 200 and model == "GLM-OCR-bf16" for _, dpi, model, _ in calls)
        )
        self.assertEqual(
            ["text_recovered", "empty_text"],
            [item.ocr_result_status for item in result.ocr_recovery_pages],
        )
        self.assertEqual(1, len(result.spans))
        self.assertEqual("objectives_endpoints", result.spans[0].ich_m11_anchor)
        self.assertEqual(
            "5 Study Objectives and Endpoints",
            result.spans[0].section_heading,
        )
        self.assertEqual("", result.ocr_recovery_pages[1].span_id)
        self.assertEqual(0, result.ocr_recovery_pages[1].ocr_character_count)
        self.assertEqual(
            hashlib.sha256(b"").hexdigest(),
            result.ocr_recovery_pages[1].ocr_text_sha256,
        )

        for evidence in result.ocr_recovery_pages:
            path = resolve_ocr_evidence_path(
                self.artifact_root, evidence.storage_relpath
            )
            self.assertTrue(path.is_file())
            self.assertEqual(
                evidence.image_sha256,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
            self.assertEqual(evidence.image_size_bytes, path.stat().st_size)
            self.assertEqual(
                (evidence.image_width_px, evidence.image_height_px),
                png_dimensions(path.read_bytes()),
            )
            self.assertEqual(200, evidence.dpi)

        restarted = self._stored_extraction(
            source.artifact_id, result.extraction_revision
        )
        self.assertEqual(
            result.ocr_recovery_pages,
            restarted.ocr_recovery_pages,
        )

    def test_actual_page_model_and_mixed_qc_are_persisted(self) -> None:
        source = self._register_pdf(blank_pdf(2), key="mixed-model")
        qc_calls: list[str] = []

        def fake_ocr(page: int, dpi: int, model: str, image_bytes: bytes):
            actual_model = (
                "PaddleOCR-VL-1.6" if page == 1 else "GLM-OCR-bf16"
            )
            text = f"Protocol page {page}"
            return OcrResult(
                text=text,
                model=actual_model,
                source_token=f"page-{page}",
                content_hash=hashlib.sha256(image_bytes).hexdigest(),
                character_count=len(text),
                called_at=datetime.now(timezone.utc),
                duration_ms=1.0,
                provider="paddle_official" if page == 1 else "omlx_glm",
                fell_back=page == 2,
                primary_model="PaddleOCR-VL-1.6" if page == 2 else "",
                fallback_reason=(
                    "paddle_failure:timeout:job_2" if page == 2 else ""
                ),
            )

        def fake_qc(system_prompt: str, user_prompt: str) -> dict:
            qc_calls.append(user_prompt)
            return {"verdict": "pass", "notes": "boundary is consistent"}

        result = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=fake_ocr,
            ocr_model="PaddleOCR-VL-1.6",
            ocr_consistency_qc_runner=fake_qc,
        ).extract(
            PROJECT_ID,
            source.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="ocr-extract-mixed-model",
        )

        self.assertEqual(
            ["PaddleOCR-VL-1.6", "GLM-OCR-bf16"],
            [item.model for item in result.ocr_recovery_pages],
        )
        self.assertFalse(result.ocr_recovery_pages[0].fell_back)
        self.assertTrue(result.ocr_recovery_pages[1].fell_back)
        self.assertIn(
            "paddle_failure",
            result.ocr_recovery_pages[1].fallback_reason,
        )
        self.assertEqual(1, len(qc_calls))
        self.assertTrue(result.ocr_consistency_qc["triggered"])
        self.assertEqual("pass", result.ocr_consistency_qc["verdict"])

        restarted = self._stored_extraction(
            source.artifact_id, result.extraction_revision
        )
        self.assertEqual(
            result.ocr_consistency_qc, restarted.ocr_consistency_qc
        )

    def test_failed_ocr_batch_does_not_publish_partial_sidecars(self) -> None:
        source = self._register_pdf(blank_pdf(2), key="failed-batch")

        def fake_ocr(
            page: int, dpi: int, model: str, image_bytes: bytes
        ) -> str:
            if page == 2:
                raise RuntimeError("fake OCR failure")
            return "recovered page one"

        service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=fake_ocr,
        )
        with self.assertRaisesRegex(RuntimeError, "fake OCR failure"):
            service.extract(
                PROJECT_ID,
                source.artifact_id,
                actor="medical_manager",
                extraction_idempotency_key="ocr-extract-failed",
            )
        self.assertEqual([], list(self.artifact_root.rglob("*.png")))

    def test_empty_anomaly_ocr_keeps_native_text_and_records_evidence(self) -> None:
        source = self._register_pdf(pdf_fixture(), key="empty-anomaly")
        service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=lambda page, dpi, model, image_bytes: "",
        )
        with patch(
            "services.api.app.writing_reference.detect_anomaly_pages",
            return_value=[
                {
                    "physical_page": 1,
                    "reason": "vector_glyph_anomaly",
                }
            ],
        ):
            result = service.extract(
                PROJECT_ID,
                source.artifact_id,
                actor="medical_manager",
                extraction_idempotency_key="ocr-extract-empty-anomaly",
            )

        page_one_spans = [
            span for span in result.spans if span.physical_page == 1
        ]
        self.assertTrue(page_one_spans)
        self.assertTrue(
            any("primary endpoint" in span.source_text for span in page_one_spans)
        )
        evidence = result.ocr_recovery_pages[0]
        self.assertEqual("empty_text", evidence.ocr_result_status)
        self.assertEqual("ocr", evidence.channel)
        self.assertEqual("", evidence.span_id)
        self.assertTrue(evidence.native_channel)

    def test_anomaly_with_native_spans_and_ocr_uses_reconciled_channel(self) -> None:
        source = self._register_pdf(pdf_fixture(), key="native-anomaly")
        service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=lambda page, dpi, model, image_bytes: (
                "OCR recovered primary endpoint text"
            ),
        )
        with patch(
            "services.api.app.writing_reference.detect_anomaly_pages",
            return_value=[
                {
                    "physical_page": 1,
                    "reason": "vector_glyph_anomaly",
                }
            ],
        ):
            result = service.extract(
                PROJECT_ID,
                source.artifact_id,
                actor="medical_manager",
                extraction_idempotency_key="ocr-extract-native-anomaly",
            )

        evidence = result.ocr_recovery_pages[0]
        self.assertEqual("ocr_reconciled", evidence.channel)
        self.assertEqual("text_recovered", evidence.ocr_result_status)
        self.assertEqual("vector_glyph_anomaly", evidence.selection_reason)
        self.assertTrue(evidence.native_channel)
        page_one_spans = [
            span for span in result.spans if span.physical_page == 1
        ]
        self.assertEqual(1, len(page_one_spans))
        self.assertEqual("ocr_reconciled", page_one_spans[0].extraction_status)
        self.assertEqual(
            "objectives_endpoints",
            page_one_spans[0].ich_m11_anchor,
        )

    def test_anomaly_without_native_spans_uses_ordinary_ocr_recovery(self) -> None:
        payload = pdf_fixture()
        source = self._register_pdf(payload, key="no-native-anomaly")
        parsed = extract_pdf_sections(payload, source)
        no_native_result = parsed.model_copy(
            update={"spans": [], "zero_text_pages": []}
        )
        service = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=lambda page, dpi, model, image_bytes: (
                "OCR recovered image-only anomaly text"
            ),
        )
        with patch(
            "services.api.app.writing_reference.extract_pdf_sections",
            return_value=no_native_result,
        ), patch(
            "services.api.app.writing_reference.detect_anomaly_pages",
            return_value=[
                {
                    "physical_page": 1,
                    "reason": "image_only_anomaly",
                }
            ],
        ):
            result = service.extract(
                PROJECT_ID,
                source.artifact_id,
                actor="medical_manager",
                extraction_idempotency_key="ocr-extract-no-native-anomaly",
            )

        evidence = result.ocr_recovery_pages[0]
        self.assertEqual("ocr", evidence.channel)
        self.assertEqual("text_recovered", evidence.ocr_result_status)
        self.assertEqual("image_only_anomaly", evidence.selection_reason)
        self.assertEqual([], evidence.native_channel)
        page_one_spans = [
            span for span in result.spans if span.physical_page == 1
        ]
        self.assertEqual(1, len(page_one_spans))
        self.assertEqual("ocr_recovered", page_one_spans[0].extraction_status)

    def test_executor_never_exceeds_eight_concurrent_ocr_calls(self) -> None:
        source = self._register_pdf(blank_pdf(10), key="concurrency")
        lock = threading.Lock()
        active = 0
        maximum_active = 0

        def fake_ocr(
            page: int, dpi: int, model: str, image_bytes: bytes
        ) -> str:
            nonlocal active, maximum_active
            with lock:
                active += 1
                maximum_active = max(maximum_active, active)
            try:
                time.sleep(0.02)
                return f"Protocol content on page {page}"
            finally:
                with lock:
                    active -= 1

        result = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=fake_ocr,
        ).extract(
            PROJECT_ID,
            source.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="ocr-extract-concurrency",
        )
        self.assertEqual(10, len(result.ocr_recovery_pages))
        self.assertGreater(maximum_active, 1)
        self.assertLessEqual(maximum_active, 8)

    def test_recovered_spans_remain_in_physical_page_order(self) -> None:
        document = pymupdf.open()
        document.new_page()
        second_page = document.new_page()
        second_page.insert_text((72, 72), "Native protocol content on page two")
        payload = document.tobytes()
        document.close()
        source = self._register_pdf(payload, key="span-order")

        result = WritingReferenceExtractionService(
            self.repo,
            artifact_root=self.artifact_root,
            ocr_runner=lambda page, dpi, model, image_bytes: (
                "Recovered protocol content on page one" if page == 1 else ""
            ),
        ).extract(
            PROJECT_ID,
            source.artifact_id,
            actor="medical_manager",
            extraction_idempotency_key="ocr-extract-span-order",
        )

        self.assertEqual(
            sorted(span.physical_page for span in result.spans),
            [span.physical_page for span in result.spans],
        )
        self.assertEqual(1, result.spans[0].physical_page)
        self.assertEqual(2, result.spans[-1].physical_page)


if __name__ == "__main__":
    unittest.main()
