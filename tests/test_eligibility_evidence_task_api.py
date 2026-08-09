from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app import eligibility
from services.api.app.main import app
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


class EligibilityEvidenceTaskApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteRuntimeStore(Path(self.tmp.name) / "runtime.sqlite3")
        eligibility.configure_eligibility_review_workflow(self.store)
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def _real_inputs_available(self, project_id):
        config = eligibility.RAW_INTAKE_PROJECTS[project_id]
        return Path(config.protocol_path).exists() and Path(config.raw_subject_root).exists()

    def _source_and_kind(self, project_id, subject_id):
        config = eligibility.RAW_INTAKE_PROJECTS[project_id]
        subject = eligibility.raw_intake_service.subject_manifest(config, subject_id)
        source = subject.sources[0]
        kind = "pdf_text_extraction" if source.source_type == "pdf" else "media_classification"
        return source, kind

    def test_two_real_projects_create_replay_list_and_cancel_project_scoped_jobs(self):
        cases = (
            ("proj_d001", "SA07005"),
            ("proj_my009_uc", "S01009"),
        )
        for project_id, subject_id in cases:
            if not self._real_inputs_available(project_id):
                self.skipTest(f"real eligibility inputs unavailable: {project_id}")
            with self.subTest(project_id=project_id):
                source, job_kind = self._source_and_kind(project_id, subject_id)
                base = (
                    f"/api/projects/{project_id}/eligibility/raw-intake/subjects/"
                    f"{subject_id}/evidence-jobs"
                )
                profile_version = (
                    "pdf-text-pymupdf-v1"
                    if job_kind == "pdf_text_extraction"
                    else "media-classification-v1"
                )
                request = {
                    "source_id": source.source_id,
                    "job_kind": job_kind,
                    "profile_version": profile_version,
                    "idempotency_key": f"api-create-{project_id}",
                    "priority": 10,
                    "max_attempts": 3,
                }
                first = self.client.post(base, json=request)
                replay = self.client.post(base, json=request)
                self.assertEqual(200, first.status_code, first.text)
                self.assertEqual(200, replay.status_code, replay.text)
                self.assertFalse(first.json()["replayed"])
                self.assertTrue(replay.json()["replayed"])
                job = first.json()["job"]
                self.assertEqual(project_id, job["project_id"])
                self.assertEqual(subject_id, job["subject_id"])
                self.assertEqual("queued", job["status"])

                listed = self.client.get(base)
                self.assertEqual(200, listed.status_code, listed.text)
                self.assertEqual([job["job_id"]], [item["job_id"] for item in listed.json()])
                serialized = json.dumps(listed.json(), ensure_ascii=False)
                for forbidden in ("cache_key", "lease_owner", "content_hash", "/Users/"):
                    self.assertNotIn(forbidden, serialized)

                cancelled = self.client.post(
                    f"{base}/{job['job_id']}/cancel",
                    json={"actor": "medical_manager"},
                )
                self.assertEqual(200, cancelled.status_code, cancelled.text)
                self.assertEqual("cancelled", cancelled.json()["status"])

    def test_artifact_projection_omits_storage_key_and_hash(self):
        if not self._real_inputs_available("proj_d001"):
            self.skipTest("D001 real eligibility inputs unavailable")
        source, job_kind = self._source_and_kind("proj_d001", "SA07005")
        base = (
            "/api/projects/proj_d001/eligibility/raw-intake/subjects/"
            "SA07005/evidence-jobs"
        )
        created = self.client.post(
            base,
            json={
                "source_id": source.source_id,
                "job_kind": job_kind,
                "profile_version": (
                    "pdf-text-pymupdf-v1"
                    if job_kind == "pdf_text_extraction"
                    else "media-classification-v1"
                ),
                "idempotency_key": "api-artifact-job",
                "priority": 0,
                "max_attempts": 3,
            },
        )
        self.assertEqual(200, created.status_code, created.text)
        job = created.json()["job"]
        self.store.add_eligibility_evidence_artifact(
            {
                "project_id": "proj_d001",
                "subject_id": "SA07005",
                "job_id": job["job_id"],
                "artifact_id": "eligartifact-api-001",
                "artifact_kind": "ocr_text",
                "storage_key": "proj_d001/SA07005/job/page-001.json",
                "content_hash": "a" * 64,
                "size_bytes": 10,
                "media_type": "application/json",
                "source_id": source.source_id,
                "source_revision": source.source_revision,
                "extraction_revision": "extract-api-001",
                "locator": {"page": 1},
                "quality_state": "needs_visual_qc",
            }
        )
        response = self.client.get(f"{base}/{job['job_id']}/artifacts")
        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual("eligartifact-api-001", response.json()[0]["artifact_id"])
        serialized = json.dumps(response.json(), ensure_ascii=False)
        self.assertNotIn("storage_key", serialized)
        self.assertNotIn("content_hash", serialized)
        self.assertNotIn("/Users/", serialized)

    def test_two_real_projects_visual_qc_api_replay_cas_and_public_projection(self):
        cases = (
            ("proj_d001", "SA07005"),
            ("proj_my009_uc", "S01009"),
        )
        for project_id, subject_id in cases:
            if not self._real_inputs_available(project_id):
                self.skipTest(f"real eligibility inputs unavailable: {project_id}")
            with self.subTest(project_id=project_id):
                review_url = (
                    f"/api/projects/{project_id}/eligibility/raw-intake/subjects/"
                    f"{subject_id}/review"
                )
                synced = self.client.get(review_url)
                self.assertEqual(200, synced.status_code, synced.text)
                source = synced.json()["subject"]["sources"][0]
                evidence_id = f"visual-qc-api-{project_id}"
                extraction_revision = f"extract-{project_id}-1"
                self.store.add_eligibility_evidence_span(
                    {
                        "project_id": project_id,
                        "subject_id": subject_id,
                        "evidence_id": evidence_id,
                        "source_id": source["source_id"],
                        "source_revision": source["source_revision"],
                        "extraction_revision": extraction_revision,
                        "locator": {"page": 1, "region": [1, 2, 3, 4]},
                        "media_class": "text_document_image",
                        "processing_state": "needs_visual_qc",
                        "quality_state": "needs_visual_qc",
                        "extraction_confidence": 0.9,
                        "medical_verification_status": "not_reviewed",
                    }
                )
                qc_url = (
                    f"/api/projects/{project_id}/eligibility/raw-intake/subjects/"
                    f"{subject_id}/evidence-spans/{evidence_id}/visual-qc-records"
                )
                request = {
                    "expected_qc_revision": 0,
                    "expected_source_revision": source["source_revision"],
                    "expected_extraction_revision": extraction_revision,
                    "idempotency_key": f"visual-qc-api-key-{project_id}",
                    "result": "sampled_pass",
                    "reason_code": "visual_comparison_completed",
                    "user_reason": "The source image and extraction match.",
                    "sample_plan_id": "api-sample-plan-v1",
                    "sample_unit": {"page": 1, "region": [1, 2, 3, 4]},
                    "policy_version": "visual-qc-policy-v1",
                    "actor": "medical_manager",
                }
                first = self.client.post(qc_url, json=request)
                replay = self.client.post(qc_url, json=request)
                self.assertEqual(200, first.status_code, first.text)
                self.assertEqual(200, replay.status_code, replay.text)
                self.assertFalse(first.json()["replayed"])
                self.assertTrue(replay.json()["replayed"])
                self.assertEqual(
                    "unverified_client_claim", first.json()["identity_assurance"]
                )
                self.assertFalse(first.json()["is_electronic_signature"])

                stale_request = dict(request)
                stale_request["idempotency_key"] += "-stale"
                stale = self.client.post(qc_url, json=stale_request)
                self.assertEqual(409, stale.status_code, stale.text)

                public_review = self.client.get(review_url)
                self.assertEqual(200, public_review.status_code, public_review.text)
                public_evidence = next(
                    row
                    for row in public_review.json()["evidence"]
                    if row["evidence_id"] == evidence_id
                )
                self.assertTrue(public_evidence["valid_for_decisive_review"])
                self.assertEqual("sampled_pass", public_evidence["visual_qc"]["result"])
                serialized = json.dumps(public_evidence, ensure_ascii=False)
                self.assertNotIn("request_hash", serialized)
                self.assertNotIn("idempotency_key", serialized)


if __name__ == "__main__":
    unittest.main()
