from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from services.api.app.eligibility_artifact_store import EligibilityArtifactStore
from services.api.app.eligibility_evidence_worker import EligibilityEvidenceWorker
from services.api.app.ocr_gateway import (
    OcrGatewayConfigurationError,
    OcrGatewayRuntimeError,
    OcrResult,
    ocr_profile_digest,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
PNG_BYTES = b"\x89PNG\r\n\x1a\nsynthetic"


class FakeOcrGateway:
    def __init__(self, *, fail=False, model="GLM-OCR-bf16"):
        self.fail = fail
        self.settings = SimpleNamespace(model=model)

    def run(self, request):
        if self.fail:
            raise OcrGatewayRuntimeError("private provider detail")
        content_hash = (
            hashlib.sha256(request.image_bytes).hexdigest()
            if request.image_bytes is not None
            else "a" * 64
        )
        return OcrResult(
            text="可见文字 120/80 mmHg",
            model=self.settings.model,
            source_token="ocrsrc_test",
            content_hash=content_hash,
            character_count=20,
            called_at=NOW,
            duration_ms=1.0,
        )


class EligibilityEvidenceWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source = root / "source.png"
        self.source.write_bytes(PNG_BYTES)
        self.store = SqliteRuntimeStore(root / "runtime.sqlite3")
        self.artifacts = EligibilityArtifactStore(root / "artifacts")
        self.store.replace_eligibility_subject_sources(
            "proj_d001",
            "SA07005",
            "subject-source-v1",
            [{
                "source_id": "source-1",
                "source_revision": "source-rev-1",
                "content_hash": "source-hash-1",
                "size_bytes": len(PNG_BYTES),
                "media_class": "image",
            }],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def create_job(self, *, job_id="job-1", kind="ocr"):
        return self.store.create_eligibility_evidence_job(
            {
                "project_id": "proj_d001",
                "subject_id": "SA07005",
                "job_id": job_id,
                "job_kind": kind,
                "profile_version": "ocr-glm-v1" if kind == "ocr" else "vlm-minimax-v1",
                "source_id": "source-1",
                "source_revision": "source-rev-1",
                "subject_source_revision": "subject-source-v1",
                "cache_key": f"cache-{job_id}",
                "max_attempts": 3,
                "profile_digest": (
                    ocr_profile_digest("ocr-glm-v1") if kind == "ocr" else None
                ),
                "created_at": NOW.isoformat(),
            },
            idempotency_key=f"create-{job_id}",
            request_fingerprint=f"fingerprint-{job_id}",
        )

    def worker(self, gateway):
        return EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifacts,
            source_resolver=lambda job: self.source,
            ocr_gateway=gateway,
            clock=lambda: NOW,
        )

    def create_pdf_job(self, *, job_id, kind, profile):
        import pymupdf

        pdf_path = Path(self.tmp.name) / "source.pdf"
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "Digitally born eligibility source text with sufficient content for extraction and visual review.",
        )
        document.new_page()
        document.save(pdf_path)
        document.close()
        self.source = pdf_path
        self.store.replace_eligibility_subject_sources(
            "proj_d001",
            "SA07005",
            "subject-source-pdf-v1",
            [{
                "source_id": "source-pdf-1",
                "source_revision": "source-pdf-rev-1",
                "content_hash": "source-pdf-hash-1",
                "size_bytes": pdf_path.stat().st_size,
                "media_class": "pdf",
            }],
        )
        return self.store.create_eligibility_evidence_job(
            {
                "project_id": "proj_d001",
                "subject_id": "SA07005",
                "job_id": job_id,
                "job_kind": kind,
                "profile_version": profile,
                "source_id": "source-pdf-1",
                "source_revision": "source-pdf-rev-1",
                "subject_source_revision": "subject-source-pdf-v1",
                "cache_key": f"cache-{job_id}",
                "max_attempts": 3,
                "created_at": NOW.isoformat(),
            },
            idempotency_key=f"create-{job_id}",
            request_fingerprint=f"fingerprint-{job_id}",
        )

    def test_ocr_job_writes_controlled_artifact_and_unverified_evidence_only(self):
        self.create_job()
        result = self.worker(FakeOcrGateway()).run_once("worker-1")
        self.assertEqual("succeeded", result["status"])
        artifacts = self.store.eligibility_evidence_artifacts("proj_d001", "job-1")
        self.assertEqual(2, len(artifacts))
        by_kind = {artifact["artifact_kind"]: artifact for artifact in artifacts}
        self.assertEqual({"ocr_input_image", "ocr_text"}, set(by_kind))
        spans = self.store.eligibility_subject_evidence_spans("proj_d001", "SA07005")
        self.assertEqual(1, len(spans))
        self.assertEqual("needs_visual_qc", spans[0]["processing_state"])
        self.assertEqual("needs_visual_qc", spans[0]["quality_state"])
        self.assertEqual("not_reviewed", spans[0]["medical_verification_status"])
        body = self.artifacts.read_bytes(
            by_kind["ocr_text"]["storage_key"],
            expected_hash=by_kind["ocr_text"]["content_hash"],
            expected_size_bytes=by_kind["ocr_text"]["size_bytes"],
        )
        self.assertIn("可见文字".encode(), body)
        input_body = self.artifacts.read_bytes(
            by_kind["ocr_input_image"]["storage_key"],
            expected_hash=by_kind["ocr_input_image"]["content_hash"],
            expected_size_bytes=by_kind["ocr_input_image"]["size_bytes"],
        )
        self.assertEqual(self.source.read_bytes(), input_body)

    def test_runtime_failure_enters_retry_wait_without_provider_detail(self):
        self.create_job()
        result = self.worker(FakeOcrGateway(fail=True)).run_once("worker-1")
        self.assertEqual("retry_wait", result["status"])
        self.assertEqual("ocr_runtime_failure", result["error_code"])
        self.assertNotIn("private", str(result))

    def test_unbound_vlm_job_creation_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "exact profile digest"):
            self.create_job(job_id="job-vlm", kind="vlm")
        self.assertEqual(
            [], self.store.eligibility_evidence_artifacts("proj_d001", "job-vlm")
        )

    def test_pdf_text_job_separates_selectable_text_from_scan_required_page(self):
        self.create_pdf_job(
            job_id="job-pdf-text",
            kind="pdf_text_extraction",
            profile="pdf-text-pymupdf-v1",
        )
        worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifacts,
            source_resolver=lambda job: self.source,
            profile_version="pdf-text-pymupdf-v1",
            clock=lambda: NOW,
        )
        result = worker.run_once("worker-pdf-text")

        self.assertEqual("succeeded", result["status"])
        self.assertEqual(2, result["progress_current"])
        self.assertEqual(2, result["progress_total"])
        artifacts = self.store.eligibility_evidence_artifacts(
            "proj_d001", "job-pdf-text"
        )
        self.assertEqual(2, len(artifacts))
        self.assertEqual(
            {1: "needs_visual_qc", 2: "manual_review_required"},
            {item["locator"]["page"]: item["quality_state"] for item in artifacts},
        )
        spans = self.store.eligibility_subject_evidence_spans(
            "proj_d001", "SA07005"
        )
        self.assertEqual(1, len(spans))
        self.assertEqual({"page": 1}, spans[0]["locator"])

    def test_pdf_render_job_creates_page_images_without_evidence_conclusion(self):
        self.create_pdf_job(
            job_id="job-pdf-render",
            kind="pdf_page_render",
            profile="pdf-render-200dpi-v1",
        )
        worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifacts,
            source_resolver=lambda job: self.source,
            profile_version="pdf-render-200dpi-v1",
            ocr_child_profiles=("ocr-glm-v1", "ocr-paddle-v1"),
            clock=lambda: NOW,
        )
        result = worker.run_once("worker-pdf-render")

        self.assertEqual("succeeded", result["status"])
        artifacts = self.store.eligibility_evidence_artifacts(
            "proj_d001", "job-pdf-render"
        )
        self.assertEqual(2, len(artifacts))
        self.assertTrue(all(item["media_type"] == "image/png" for item in artifacts))
        children = self.store.eligibility_pdf_render_ocr_children(
            "proj_d001", "job-pdf-render"
        )
        self.assertEqual(4, len(children))
        self.assertEqual(
            {"ocr-glm-v1", "ocr-paddle-v1"},
            {child["profile_version"] for child in children},
        )
        self.assertEqual(
            [],
            self.store.eligibility_subject_evidence_spans("proj_d001", "SA07005"),
        )

    def _render_and_expand(self, profile="ocr-glm-v1"):
        from services.api.app.eligibility_evidence_tasks import EligibilityEvidenceTaskService

        self.create_pdf_job(
            job_id="job-pdf-render",
            kind="pdf_page_render",
            profile="pdf-render-200dpi-v1",
        )
        render_worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifacts,
            source_resolver=lambda job: self.source,
            profile_version="pdf-render-200dpi-v1",
            ocr_child_profiles=(profile,),
            clock=lambda: NOW,
        )
        self.assertEqual("succeeded", render_worker.run_once("render-worker")["status"])
        return EligibilityEvidenceTaskService(self.store).expand_pdf_render_to_ocr(
            project_id="proj_d001",
            parent_job_id="job-pdf-render",
            profile_version=profile,
            idempotency_key=f"expand-{profile}",
        )

    def test_pdf_page_ocr_reads_verified_artifact_bytes_without_resolving_pdf(self):
        children = self._render_and_expand()

        class ArtifactBytesGateway(FakeOcrGateway):
            def run(self, request):
                if request.source_path is not None:
                    raise AssertionError("OCR child must not receive a filesystem path")
                if not request.image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise AssertionError("OCR child must receive verified PNG bytes")
                if request.image_suffix != ".png":
                    raise AssertionError("OCR child image type must be explicit")
                return super().run(request)

        worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifacts,
            source_resolver=lambda job: (_ for _ in ()).throw(
                AssertionError("raw PDF resolver must not be called")
            ),
            ocr_gateway=ArtifactBytesGateway(),
            profile_version="ocr-glm-v1",
            clock=lambda: NOW,
        )
        result = worker.run_once("ocr-child-worker")
        self.assertEqual("succeeded", result["status"])
        self.assertIn(
            result["job_id"], {child["job"]["job_id"] for child in children}
        )
        spans = self.store.eligibility_subject_evidence_spans(
            "proj_d001", "SA07005"
        )
        self.assertEqual("needs_visual_qc", spans[0]["processing_state"])
        self.assertEqual("not_reviewed", spans[0]["medical_verification_status"])
        completed_child = self.store.eligibility_evidence_job(
            "proj_d001", result["job_id"]
        )
        self.assertEqual(completed_child["page_index"], spans[0]["locator"]["page"])

    def test_pdf_page_ocr_rejects_tampered_artifact_before_gateway_call(self):
        children = self._render_and_expand()
        claimed_child_id = min(child["job"]["job_id"] for child in children)
        child = self.store.eligibility_evidence_job(
            "proj_d001", claimed_child_id
        )
        artifact = self.store.eligibility_evidence_artifact(
            "proj_d001", child["input_artifact_id"]
        )
        (Path(self.tmp.name) / "artifacts" / artifact["storage_key"]).write_bytes(
            b"tampered"
        )

        class MustNotRunGateway:
            settings = SimpleNamespace(model="GLM-OCR-bf16")

            def run(self, request):
                raise AssertionError("gateway must not receive a corrupt artifact")

        worker = EligibilityEvidenceWorker(
            store=self.store,
            artifact_store=self.artifacts,
            source_resolver=lambda job: self.source,
            ocr_gateway=MustNotRunGateway(),
            profile_version="ocr-glm-v1",
            clock=lambda: NOW,
        )
        result = worker.run_once("ocr-child-worker")
        self.assertEqual("failed", result["status"])
        self.assertEqual("input_artifact_integrity_failure", result["error_code"])

    def test_worker_startup_rejects_profile_model_mismatch(self):
        with self.assertRaises(OcrGatewayConfigurationError):
            EligibilityEvidenceWorker(
                store=self.store,
                artifact_store=self.artifacts,
                source_resolver=lambda job: self.source,
                ocr_gateway=FakeOcrGateway(model="GLM-OCR-bf16"),
                profile_version="ocr-paddle-v1",
                clock=lambda: NOW,
            )


if __name__ == "__main__":
    unittest.main()
