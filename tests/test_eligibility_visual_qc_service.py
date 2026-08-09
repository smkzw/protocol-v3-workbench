from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app import eligibility
from services.api.app.eligibility_artifact_store import (
    ArtifactIntegrityError,
    EligibilityArtifactStore,
)
from services.api.app.eligibility_visual_qc_service import (
    EligibilityVisualQcImage,
    EligibilityVisualQcPacketError,
    EligibilityVisualQcService,
)
from services.api.app.eligibility_review_workflow import EligibilityReviewWorkflow
from services.api.app.main import app
from services.api.app.ocr_gateway import ocr_profile_digest
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


PROJECT_ID = "project-qc"
SUBJECT_ID = "subject-qc"
SOURCE_ID = "source-qc"
SOURCE_REVISION = "source-revision-qc"
SUBJECT_SOURCE_REVISION = "subject-source-revision-qc"
EXTRACTION_REVISION = "extraction-revision-qc"


class EligibilityVisualQcServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.store = SqliteRuntimeStore(root / "runtime.sqlite3")
        self.artifact_store = EligibilityArtifactStore(root / "artifacts")
        self.service = EligibilityVisualQcService(
            self.store,
            self.artifact_store,
        )
        self.store.replace_eligibility_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            SUBJECT_SOURCE_REVISION,
            [
                {
                    "source_id": SOURCE_ID,
                    "source_revision": SOURCE_REVISION,
                    "content_hash": "a" * 64,
                    "size_bytes": 128,
                    "media_class": "image",
                    "processing_unit_kind": "image",
                    "expected_unit_count": 1,
                }
            ],
        )

    def _create_job(self, job_id: str, *, job_kind: str = "ocr") -> None:
        payload = {
            "project_id": PROJECT_ID,
            "subject_id": SUBJECT_ID,
            "job_id": job_id,
            "job_kind": job_kind,
            "profile_version": "ocr-glm-v1",
            "source_id": SOURCE_ID,
            "source_revision": SOURCE_REVISION,
            "subject_source_revision": SUBJECT_SOURCE_REVISION,
            "cache_key": f"cache-{job_id}",
            "max_attempts": 3,
        }
        if job_kind == "ocr":
            payload["profile_digest"] = ocr_profile_digest("ocr-glm-v1")
        self.store.create_eligibility_evidence_job(
            payload,
            idempotency_key=f"create-{job_id}",
            request_fingerprint=f"fingerprint-{job_id}",
        )

    def _add_artifact(
        self,
        *,
        job_id: str,
        artifact_id: str,
        artifact_kind: str,
        body: bytes,
        media_type: str,
        locator: dict,
    ) -> Path:
        storage_key = f"{PROJECT_ID}/{SUBJECT_ID}/{job_id}/{artifact_id}"
        artifact = self.artifact_store.write(storage_key, body, media_type)
        self.store.add_eligibility_evidence_artifact(
            {
                "project_id": PROJECT_ID,
                "subject_id": SUBJECT_ID,
                "job_id": job_id,
                "artifact_id": artifact_id,
                "artifact_kind": artifact_kind,
                "storage_key": artifact.storage_key,
                "content_hash": artifact.content_hash,
                "size_bytes": artifact.size_bytes,
                "media_type": artifact.media_type,
                "source_id": SOURCE_ID,
                "source_revision": SOURCE_REVISION,
                "extraction_revision": EXTRACTION_REVISION,
                "locator": locator,
                "quality_state": "needs_visual_qc",
            }
        )
        return Path(self.artifact_store._root) / storage_key

    def _add_evidence(
        self,
        *,
        evidence_id: str,
        text_artifact_id: str,
        locator: dict,
    ) -> None:
        self.store.add_eligibility_evidence_span(
            {
                "project_id": PROJECT_ID,
                "subject_id": SUBJECT_ID,
                "evidence_id": evidence_id,
                "source_id": SOURCE_ID,
                "source_revision": SOURCE_REVISION,
                "extraction_revision": EXTRACTION_REVISION,
                "locator": locator,
                "metadata": {"artifact_id": text_artifact_id},
                "media_class": "image",
                "processing_state": "completed",
                "quality_state": "needs_visual_qc",
                "extraction_confidence": 0.98,
                "medical_verification_status": "not_reviewed",
            }
        )

    @staticmethod
    def _text_body(text: str = "受控 OCR 文本") -> bytes:
        return json.dumps(
            {
                "schema_version": "eligibility_ocr_artifact_v1",
                "extraction_revision": EXTRACTION_REVISION,
                "text": text,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _seed_direct_image_packet(self) -> tuple[bytes, Path]:
        self._create_job("ocr-job")
        image = b"\x89PNG\r\n\x1a\ncontrolled-image"
        image_path = self._add_artifact(
            job_id="ocr-job",
            artifact_id="input.png",
            artifact_kind="ocr_input_image",
            body=image,
            media_type="image/png",
            locator={"source": "direct_image"},
        )
        self._add_artifact(
            job_id="ocr-job",
            artifact_id="ocr.json",
            artifact_kind="ocr_text",
            body=self._text_body(),
            media_type="application/json",
            locator={"source": "direct_image"},
        )
        self._add_evidence(
            evidence_id="evidence-direct",
            text_artifact_id="ocr.json",
            locator={"source": "direct_image"},
        )
        return image, image_path

    def _commit_qc(
        self,
        *,
        revision: int,
        result: str,
        idempotency_key: str,
    ) -> None:
        sampled = result in {"sampled_pass", "sampled_fail"}
        self.store.commit_eligibility_evidence_visual_qc(
            project_id=PROJECT_ID,
            subject_id=SUBJECT_ID,
            evidence_id="evidence-direct",
            expected_qc_revision=revision,
            expected_source_revision=SOURCE_REVISION,
            expected_extraction_revision=EXTRACTION_REVISION,
            idempotency_key=idempotency_key,
            result=result,
            reason_code="fixture_visual_comparison",
            user_reason="Compared the complete controlled source image and OCR text.",
            sample_plan_id=("full-image-v1" if sampled else None),
            sample_unit=({"source": "direct_image"} if sampled else None),
            policy_version="visual-qc-policy-v1",
            actor="test-reviewer",
        )

    def test_direct_image_packet_returns_bound_text_image_and_qc_state(self) -> None:
        image, _ = self._seed_direct_image_packet()

        packet = self.service.queue(PROJECT_ID, SUBJECT_ID, offset=0, limit=20)

        self.assertEqual(1, packet["total"])
        self.assertEqual(1, packet["overall_total"])
        self.assertEqual(1, packet["status_counts"]["pending"])
        item = packet["items"][0]
        self.assertEqual("受控 OCR 文本", item["text"])
        self.assertEqual("input.png", item["image_artifact_id"])
        self.assertEqual(0, item["visual_qc"]["qc_revision"])
        self.assertIsNone(item["visual_qc"]["result"])
        served = self.service.image(PROJECT_ID, SUBJECT_ID, "input.png")
        self.assertEqual(image, served.body)
        self.assertEqual("image/png", served.media_type)

    def test_pdf_page_packet_uses_matching_page_image(self) -> None:
        self._create_job("ocr-page-job")
        self._create_job("render-job", job_kind="pdf_page_render")
        self._add_artifact(
            job_id="render-job",
            artifact_id="page-2.png",
            artifact_kind="pdf_page_image",
            body=b"\x89PNG\r\n\x1a\npage-two",
            media_type="image/png",
            locator={"page": 2, "dpi": 200},
        )
        self._add_artifact(
            job_id="ocr-page-job",
            artifact_id="page-2.json",
            artifact_kind="ocr_text",
            body=self._text_body("第二页文字"),
            media_type="application/json",
            locator={"page": 2},
        )
        self._add_evidence(
            evidence_id="evidence-page-2",
            text_artifact_id="page-2.json",
            locator={"page": 2, "region": [1, 2, 3, 4]},
        )

        item = self.service.queue(
            PROJECT_ID, SUBJECT_ID, offset=0, limit=1
        )["items"][0]

        self.assertEqual("第二页文字", item["text"])
        self.assertEqual("page-2.png", item["image_artifact_id"])

    def test_queue_paginates_without_exposing_internal_artifact_paths(self) -> None:
        self._seed_direct_image_packet()
        payload = self.service.queue(PROJECT_ID, SUBJECT_ID, offset=1, limit=1)

        self.assertEqual(1, payload["total"])
        self.assertEqual([], payload["items"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(str(self.artifact_store._root), serialized)
        self.assertNotIn("storage_key", serialized)
        self.assertNotIn("content_hash", serialized)

    def test_queue_filters_across_the_whole_subject_queue(self) -> None:
        self._seed_direct_image_packet()
        self._commit_qc(
            revision=0,
            result="sampled_pass",
            idempotency_key="qc-filter-pass",
        )

        pending = self.service.queue(
            PROJECT_ID,
            SUBJECT_ID,
            offset=0,
            limit=20,
            result_filter="pending",
        )
        passed = self.service.queue(
            PROJECT_ID,
            SUBJECT_ID,
            offset=0,
            limit=20,
            result_filter="sampled_pass",
        )

        self.assertEqual(0, pending["total"])
        self.assertEqual([], pending["items"])
        self.assertEqual(1, passed["total"])
        self.assertEqual(1, passed["overall_total"])
        self.assertEqual(1, passed["status_counts"]["sampled_pass"])

    def test_cross_subject_image_probe_is_not_found(self) -> None:
        self._seed_direct_image_packet()

        with self.assertRaises(KeyError):
            self.service.image(PROJECT_ID, "other-subject", "input.png")

    def test_image_from_non_current_source_revision_is_not_served(self) -> None:
        self._seed_direct_image_packet()
        self.store.replace_eligibility_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            "subject-source-revision-qc-r2",
            [
                {
                    "source_id": SOURCE_ID,
                    "source_revision": "source-revision-qc-r2",
                    "content_hash": "b" * 64,
                    "size_bytes": 256,
                    "media_class": "image",
                    "processing_unit_kind": "image",
                    "expected_unit_count": 1,
                }
            ],
        )

        with self.assertRaises(KeyError):
            self.service.image(PROJECT_ID, SUBJECT_ID, "input.png")

    def test_tampered_image_fails_integrity_verification(self) -> None:
        _, image_path = self._seed_direct_image_packet()
        image_path.write_bytes(b"tampered")

        with self.assertRaises(ArtifactIntegrityError):
            self.service.image(PROJECT_ID, SUBJECT_ID, "input.png")

    def test_missing_image_fails_closed(self) -> None:
        self._create_job("ocr-job")
        self._add_artifact(
            job_id="ocr-job",
            artifact_id="ocr.json",
            artifact_kind="ocr_text",
            body=self._text_body(),
            media_type="application/json",
            locator={"source": "direct_image"},
        )
        self._add_evidence(
            evidence_id="evidence-direct",
            text_artifact_id="ocr.json",
            locator={"source": "direct_image"},
        )

        with self.assertRaises(EligibilityVisualQcPacketError):
            self.service.queue(PROJECT_ID, SUBJECT_ID, offset=0, limit=20)

    def test_missing_text_binding_fails_closed(self) -> None:
        self._create_job("ocr-job")
        self._add_artifact(
            job_id="ocr-job",
            artifact_id="input.png",
            artifact_kind="ocr_input_image",
            body=b"\x89PNG\r\n\x1a\ncontrolled-image",
            media_type="image/png",
            locator={"source": "direct_image"},
        )
        self.store.add_eligibility_evidence_span(
            {
                "project_id": PROJECT_ID,
                "subject_id": SUBJECT_ID,
                "evidence_id": "evidence-without-text-binding",
                "source_id": SOURCE_ID,
                "source_revision": SOURCE_REVISION,
                "extraction_revision": EXTRACTION_REVISION,
                "locator": {"source": "direct_image"},
                "metadata": {},
                "media_class": "image",
                "processing_state": "completed",
                "quality_state": "needs_visual_qc",
                "extraction_confidence": 0.98,
                "medical_verification_status": "not_reviewed",
            }
        )

        with self.assertRaises(EligibilityVisualQcPacketError):
            self.service.queue(PROJECT_ID, SUBJECT_ID, offset=0, limit=20)

    def test_oversized_text_artifact_fails_closed(self) -> None:
        self._create_job("ocr-job")
        self._add_artifact(
            job_id="ocr-job",
            artifact_id="input.png",
            artifact_kind="ocr_input_image",
            body=b"\x89PNG\r\n\x1a\ncontrolled-image",
            media_type="image/png",
            locator={"source": "direct_image"},
        )
        self._add_artifact(
            job_id="ocr-job",
            artifact_id="ocr.json",
            artifact_kind="ocr_text",
            body=self._text_body("x" * 100_001),
            media_type="application/json",
            locator={"source": "direct_image"},
        )
        self._add_evidence(
            evidence_id="evidence-direct",
            text_artifact_id="ocr.json",
            locator={"source": "direct_image"},
        )

        with self.assertRaises(EligibilityVisualQcPacketError):
            self.service.queue(PROJECT_ID, SUBJECT_ID, offset=0, limit=20)

    def test_qc_pass_closes_unit_and_later_failure_reopens_it(self) -> None:
        self._seed_direct_image_packet()
        claimed = self.store.claim_next_eligibility_evidence_job(
            "qc-worker",
            job_kind="ocr",
            profile_version="ocr-glm-v1",
            profile_digest=ocr_profile_digest("ocr-glm-v1"),
        )
        self.assertIsNotNone(claimed)
        self.store.complete_eligibility_evidence_job(
            PROJECT_ID,
            "ocr-job",
            worker_id="qc-worker",
        )
        self._commit_qc(
            revision=0,
            result="sampled_pass",
            idempotency_key="qc-pass",
        )

        closed = self.service.reconcile_processing_unit(
            PROJECT_ID,
            SUBJECT_ID,
            "evidence-direct",
            qc_idempotency_key="qc-pass",
            actor="test-reviewer",
        )

        self.assertEqual("evidence_extracted", closed["processing_status"])
        self.assertEqual(1, closed["state_revision"])

        self._commit_qc(
            revision=1,
            result="sampled_fail",
            idempotency_key="qc-fail",
        )
        reopened = self.service.reconcile_processing_unit(
            PROJECT_ID,
            SUBJECT_ID,
            "evidence-direct",
            qc_idempotency_key="qc-fail",
            actor="test-reviewer",
        )

        self.assertEqual("manual_review_required", reopened["processing_status"])
        self.assertEqual(2, reopened["state_revision"])

    def test_visual_qc_post_route_closes_and_reopens_processing_unit(self) -> None:
        self._seed_direct_image_packet()
        claimed = self.store.claim_next_eligibility_evidence_job(
            "route-qc-worker",
            job_kind="ocr",
            profile_version="ocr-glm-v1",
            profile_digest=ocr_profile_digest("ocr-glm-v1"),
        )
        self.assertIsNotNone(claimed)
        self.store.complete_eligibility_evidence_job(
            PROJECT_ID,
            "ocr-job",
            worker_id="route-qc-worker",
        )
        workflow = EligibilityReviewWorkflow(self.store)
        subject = SimpleNamespace(project_id=PROJECT_ID, subject_id=SUBJECT_ID)
        url = (
            f"/api/projects/{PROJECT_ID}/eligibility/raw-intake/subjects/"
            f"{SUBJECT_ID}/evidence-spans/evidence-direct/visual-qc-records"
        )
        request = {
            "expected_qc_revision": 0,
            "expected_source_revision": SOURCE_REVISION,
            "expected_extraction_revision": EXTRACTION_REVISION,
            "idempotency_key": "route-qc-pass",
            "result": "sampled_pass",
            "reason_code": "visual_match",
            "user_reason": "The complete controlled image and OCR text match.",
            "sample_plan_id": "full-image-v1",
            "sample_unit": {"source": "direct_image"},
            "policy_version": "visual-qc-policy-v1",
            "actor": "medical_manager",
        }
        with (
            patch.object(
                eligibility,
                "_sync_review_identity",
                return_value=(workflow, None, subject),
            ),
            patch.object(
                eligibility,
                "eligibility_visual_qc_service",
                self.service,
            ),
        ):
            passed = TestClient(app).post(url, json=request)
            request.update(
                {
                    "expected_qc_revision": 1,
                    "idempotency_key": "route-qc-fail",
                    "result": "sampled_fail",
                    "reason_code": "ocr_content_mismatch",
                    "user_reason": "The controlled image and OCR text differ.",
                }
            )
            failed = TestClient(app).post(url, json=request)

        self.assertEqual(200, passed.status_code, passed.text)
        self.assertEqual(200, failed.status_code, failed.text)
        units = self.store.eligibility_source_processing_units(
            PROJECT_ID,
            SUBJECT_ID,
            SUBJECT_SOURCE_REVISION,
        )
        self.assertEqual(1, len(units))
        self.assertEqual("manual_review_required", units[0]["processing_status"])
        self.assertEqual(2, units[0]["state_revision"])


class EligibilityVisualQcApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.subject = SimpleNamespace(
            project_id=PROJECT_ID,
            subject_id=SUBJECT_ID,
        )

    def test_image_route_sets_private_no_sniff_headers(self) -> None:
        service = SimpleNamespace(
            image=lambda project_id, subject_id, artifact_id: (
                EligibilityVisualQcImage(
                    body=b"\x89PNG\r\n\x1a\ncontrolled",
                    media_type="image/png",
                )
            )
        )
        with (
            patch.object(
                eligibility,
                "_sync_review_identity",
                return_value=(None, None, self.subject),
            ),
            patch.object(
                eligibility,
                "eligibility_visual_qc_service",
                service,
            ),
        ):
            response = self.client.get(
                f"/api/projects/{PROJECT_ID}/eligibility/raw-intake/subjects/"
                f"{SUBJECT_ID}/visual-qc-artifacts/input.png/content"
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual("no-store, private", response.headers["cache-control"])
        self.assertEqual("nosniff", response.headers["x-content-type-options"])
        self.assertEqual("default-src 'none'; sandbox", response.headers["content-security-policy"])
        self.assertEqual("image/png", response.headers["content-type"])

    def test_queue_route_forwards_bounded_pagination(self) -> None:
        calls = []

        def queue(project_id, subject_id, *, offset, limit, result_filter):
            calls.append((project_id, subject_id, offset, limit, result_filter))
            return {"total": 0, "offset": offset, "limit": limit, "items": []}

        with (
            patch.object(
                eligibility,
                "_sync_review_identity",
                return_value=(None, None, self.subject),
            ),
            patch.object(
                eligibility,
                "eligibility_visual_qc_service",
                SimpleNamespace(queue=queue),
            ),
        ):
            response = self.client.get(
                f"/api/projects/{PROJECT_ID}/eligibility/raw-intake/subjects/"
                f"{SUBJECT_ID}/visual-qc-queue?offset=4&limit=9&qc_status=sampled_fail"
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            [(PROJECT_ID, SUBJECT_ID, 4, 9, "sampled_fail")],
            calls,
        )

    def test_route_sanitizes_integrity_failure(self) -> None:
        def fail(*args, **kwargs):
            raise ArtifactIntegrityError("private storage detail")

        with (
            patch.object(
                eligibility,
                "_sync_review_identity",
                return_value=(None, None, self.subject),
            ),
            patch.object(
                eligibility,
                "eligibility_visual_qc_service",
                SimpleNamespace(image=fail),
            ),
        ):
            response = self.client.get(
                f"/api/projects/{PROJECT_ID}/eligibility/raw-intake/subjects/"
                f"{SUBJECT_ID}/visual-qc-artifacts/input.png/content"
            )

        self.assertEqual(409, response.status_code)
        self.assertNotIn("private storage detail", response.text)


if __name__ == "__main__":
    unittest.main()
