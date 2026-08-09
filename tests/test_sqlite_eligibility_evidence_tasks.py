from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.api.app.sqlite_runtime_store import (
    IdempotencyConflictError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)
from services.api.app.eligibility_evidence_tasks import EligibilityEvidenceTaskService
from services.api.app.ocr_gateway import ocr_profile_digest
from services.api.app.sqlite_runtime_store import RuntimeStoreIntegrityError


NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


class SqliteEligibilityEvidenceTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteRuntimeStore(Path(self.tmp.name) / "runtime.sqlite3")
        self.store.replace_eligibility_subject_sources(
            "proj_d001",
            "SA07005",
            "subject-source-rev-001",
            [
                {
                    "source_id": "source-001",
                    "source_revision": "source-rev-001",
                    "content_hash": "source-hash-001",
                    "size_bytes": 128,
                    "media_class": "image",
                }
            ],
        )
        self.store.replace_eligibility_subject_sources(
            "proj_my009_uc",
            "S01009",
            "subject-source-rev-001",
            [
                {
                    "source_id": "source-001",
                    "source_revision": "source-rev-001",
                    "content_hash": "source-hash-002",
                    "size_bytes": 128,
                    "media_class": "image",
                }
            ],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def job(self, **updates):
        payload = {
            "project_id": "proj_d001",
            "subject_id": "SA07005",
            "job_id": "eligjob-001",
            "job_kind": "ocr",
            "profile_version": "ocr-glm-v1",
            "source_id": "source-001",
            "source_revision": "source-rev-001",
            "subject_source_revision": "subject-source-rev-001",
            "cache_key": "cache-key-001",
            "max_attempts": 3,
            "priority": 10,
            "created_at": NOW.isoformat(),
        }
        payload.update(updates)
        if payload["job_kind"] == "ocr":
            payload["profile_digest"] = ocr_profile_digest(payload["profile_version"])
        else:
            payload.pop("profile_digest", None)
        return payload

    def create(self, **updates):
        return self.store.create_eligibility_evidence_job(
            self.job(**updates),
            idempotency_key="create-job-001",
            request_fingerprint="create-fingerprint-001",
        )

    def create_render_parent(
        self, *, pages=(1,), progress_total=1, lease_seconds=60
    ):
        self.store.replace_eligibility_subject_sources(
            "proj_d001", "SA07005", "subject-source-pdf-v1",
            [{
                "source_id": "source-pdf-1",
                "source_revision": "source-pdf-rev-1",
                "content_hash": "f" * 64,
                "size_bytes": 1024,
                "media_class": "pdf",
            }],
        )
        self.store.create_eligibility_evidence_job(
            self.job(
                job_id="render-parent-1",
                job_kind="pdf_page_render",
                profile_version="pdf-render-200dpi-v1",
                source_id="source-pdf-1",
                source_revision="source-pdf-rev-1",
                subject_source_revision="subject-source-pdf-v1",
                cache_key="render-parent-cache",
            ),
            idempotency_key="create-render-parent",
            request_fingerprint="render-parent-fingerprint",
        )
        self.store.claim_next_eligibility_evidence_job(
            "render-worker", now=NOW, lease_seconds=lease_seconds,
            profile_version="pdf-render-200dpi-v1",
        )
        for page in pages:
            self.store.add_eligibility_evidence_artifact({
                "project_id": "proj_d001",
                "subject_id": "SA07005",
                "job_id": "render-parent-1",
                "artifact_id": f"page-artifact-{page}",
                "artifact_kind": "pdf_page_image",
                "storage_key": (
                    f"proj_d001/SA07005/render-parent-1/page-{page:04d}.png"
                ),
                "content_hash": f"{page:x}" * 64,
                "size_bytes": 128,
                "media_type": "image/png",
                "source_id": "source-pdf-1",
                "source_revision": "source-pdf-rev-1",
                "extraction_revision": f"render-rev-{page}",
                "locator": {"page": page, "dpi": 200},
                "quality_state": "needs_visual_qc",
                "created_at": NOW.isoformat(),
            })
        self.store.heartbeat_eligibility_evidence_job(
            "proj_d001", "render-parent-1", worker_id="render-worker",
            progress_current=progress_total, progress_total=progress_total,
            now=NOW, lease_seconds=lease_seconds,
        )

    def test_create_is_idempotent_project_scoped_and_rejects_changed_replay(self):
        first = self.create()
        replay = self.create()
        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual("queued", replay["job"]["status"])

        with self.assertRaises(IdempotencyConflictError):
            self.store.create_eligibility_evidence_job(
                self.job(priority=99),
                idempotency_key="create-job-001",
                request_fingerprint="changed-fingerprint",
            )

        other = self.store.create_eligibility_evidence_job(
            self.job(project_id="proj_my009_uc", subject_id="S01009"),
            idempotency_key="create-job-001",
            request_fingerprint="create-fingerprint-001",
        )
        self.assertEqual("proj_my009_uc", other["job"]["project_id"])

    def test_claim_heartbeat_retry_and_restart_are_durable(self):
        self.create()
        claimed = self.store.claim_next_eligibility_evidence_job(
            "worker-a", now=NOW, lease_seconds=60
        )
        self.assertEqual("running", claimed["status"])
        self.assertEqual(1, claimed["attempt_count"])
        self.assertIsNone(
            self.store.claim_next_eligibility_evidence_job(
                "worker-b", now=NOW + timedelta(seconds=30), lease_seconds=60
            )
        )

        heartbeat = self.store.heartbeat_eligibility_evidence_job(
            "proj_d001",
            "eligjob-001",
            worker_id="worker-a",
            now=NOW + timedelta(seconds=30),
            lease_seconds=90,
            progress_current=1,
            progress_total=2,
        )
        self.assertEqual(1, heartbeat["progress_current"])

        waiting = self.store.fail_eligibility_evidence_job(
            "proj_d001",
            "eligjob-001",
            worker_id="worker-a",
            error_code="ocr_empty_response",
            retry_at=NOW + timedelta(minutes=2),
            now=NOW + timedelta(seconds=40),
        )
        self.assertEqual("retry_wait", waiting["status"])
        self.assertNotIn("error_detail", waiting)

        restarted = SqliteRuntimeStore(self.store.db_path)
        self.assertIsNone(
            restarted.claim_next_eligibility_evidence_job(
                "worker-b", now=NOW + timedelta(minutes=1), lease_seconds=60
            )
        )
        reclaimed = restarted.claim_next_eligibility_evidence_job(
            "worker-b", now=NOW + timedelta(minutes=3), lease_seconds=60
        )
        self.assertEqual(2, reclaimed["attempt_count"])
        completed = restarted.complete_eligibility_evidence_job(
            "proj_d001",
            "eligjob-001",
            worker_id="worker-b",
            now=NOW + timedelta(minutes=3, seconds=10),
        )
        self.assertEqual("succeeded", completed["status"])

    def test_same_worker_id_cannot_finish_a_reclaimed_job_with_old_lease_token(self):
        self.create()
        first = self.store.claim_next_eligibility_evidence_job(
            "worker-reused",
            now=NOW,
            lease_seconds=60,
        )
        reclaimed = self.store.claim_next_eligibility_evidence_job(
            "worker-reused",
            now=NOW + timedelta(seconds=61),
            lease_seconds=60,
        )
        self.assertNotEqual(first["lease_token"], reclaimed["lease_token"])

        with self.assertRaises(StaleRuntimeStateError):
            self.store.complete_eligibility_evidence_job(
                "proj_d001",
                "eligjob-001",
                worker_id="worker-reused",
                lease_token=first["lease_token"],
                now=NOW + timedelta(seconds=62),
            )
        completed = self.store.complete_eligibility_evidence_job(
            "proj_d001",
            "eligjob-001",
            worker_id="worker-reused",
            lease_token=reclaimed["lease_token"],
            now=NOW + timedelta(seconds=62),
        )
        self.assertEqual("succeeded", completed["status"])

    def test_worker_claim_is_filtered_by_processing_profile(self):
        self.create()
        self.store.create_eligibility_evidence_job(
            self.job(
                job_id="eligjob-002",
                cache_key="cache-key-002",
                profile_version="ocr-paddle-v1",
            ),
            idempotency_key="create-job-002",
            request_fingerprint="create-fingerprint-002",
        )

        paddle = self.store.claim_next_eligibility_evidence_job(
            "worker-paddle",
            now=NOW,
            lease_seconds=60,
            job_kind="ocr",
            profile_version="ocr-paddle-v1",
        )
        self.assertEqual("eligjob-002", paddle["job_id"])
        self.assertEqual("ocr-paddle-v1", paddle["profile_version"])
        glm = self.store.claim_next_eligibility_evidence_job(
            "worker-glm",
            now=NOW,
            lease_seconds=60,
            job_kind="ocr",
            profile_version="ocr-glm-v1",
        )
        self.assertEqual("eligjob-001", glm["job_id"])

    def test_cancel_and_worker_ownership_fail_closed(self):
        self.create()
        self.store.claim_next_eligibility_evidence_job(
            "worker-a", now=NOW, lease_seconds=60
        )
        with self.assertRaises(StaleRuntimeStateError):
            self.store.complete_eligibility_evidence_job(
                "proj_d001", "eligjob-001", worker_id="worker-b", now=NOW
            )
        cancelled = self.store.cancel_eligibility_evidence_job(
            "proj_d001", "eligjob-001", actor="medical_manager", now=NOW
        )
        self.assertEqual("cancelled", cancelled["status"])
        with self.assertRaises(StaleRuntimeStateError):
            self.store.complete_eligibility_evidence_job(
                "proj_d001", "eligjob-001", worker_id="worker-a", now=NOW
            )

    def test_artifact_metadata_is_immutable_and_project_scoped(self):
        self.create()
        self.store.add_eligibility_evidence_artifact(
            {
                "project_id": "proj_d001",
                "subject_id": "SA07005",
                "job_id": "eligjob-001",
                "artifact_id": "eligartifact-001",
                "artifact_kind": "ocr_text",
                "storage_key": "proj_d001/SA07005/eligjob-001/page-001.json",
                "content_hash": "a" * 64,
                "size_bytes": 128,
                "media_type": "application/json",
                "source_id": "source-001",
                "source_revision": "source-rev-001",
                "extraction_revision": "extract-rev-001",
                "locator": {"page": 1},
                "quality_state": "needs_visual_qc",
                "created_at": NOW.isoformat(),
            }
        )
        artifacts = self.store.eligibility_evidence_artifacts(
            "proj_d001", "eligjob-001"
        )
        self.assertEqual(1, len(artifacts))
        self.assertEqual("page-001.json", Path(artifacts[0]["storage_key"]).name)
        self.assertEqual([], self.store.eligibility_evidence_artifacts("proj_my009_uc", "eligjob-001"))

        with self.assertRaises(ValueError):
            self.store.add_eligibility_evidence_artifact(
                {
                    **artifacts[0],
                    "content_hash": "b" * 64,
                }
            )

    def test_pdf_page_expansion_is_restart_safe_hash_bound_and_profile_isolated(self):
        self.create_render_parent()
        finalized = self.store.finalize_pdf_render_with_ocr_children(
            "proj_d001", "render-parent-1", worker_id="render-worker",
            profile_versions=("ocr-glm-v1", "ocr-paddle-v1"), now=NOW,
        )
        self.assertEqual("succeeded", finalized["parent"]["status"])
        self.assertEqual(2, len(finalized["children"]))
        self.assertEqual(
            {ocr_profile_digest("ocr-glm-v1"), ocr_profile_digest("ocr-paddle-v1")},
            {child["profile_digest"] for child in finalized["children"]},
        )
        self.assertEqual(2, len({child["cache_key"] for child in finalized["children"]}))
        service = EligibilityEvidenceTaskService(self.store)
        glm = service.expand_pdf_render_to_ocr(
            project_id="proj_d001", parent_job_id="render-parent-1",
            profile_version="ocr-glm-v1", idempotency_key="expand-a",
        )
        self.assertEqual(1, len(glm))
        self.assertTrue(glm[0]["replayed"])
        self.assertEqual("render-parent-1", glm[0]["job"]["parent_job_id"])
        self.assertEqual(1, glm[0]["job"]["page_index"])
        self.assertNotIn("input_artifact_id", glm[0]["job"])
        self.assertNotIn("cache_key", glm[0]["job"])
        self.assertNotIn("profile_digest", glm[0]["job"])

        restarted = EligibilityEvidenceTaskService(SqliteRuntimeStore(self.store.db_path))
        replay = restarted.expand_pdf_render_to_ocr(
            project_id="proj_d001", parent_job_id="render-parent-1",
            profile_version="ocr-glm-v1", idempotency_key="expand-after-restart",
        )
        self.assertTrue(replay[0]["replayed"])
        paddle = restarted.expand_pdf_render_to_ocr(
            project_id="proj_d001", parent_job_id="render-parent-1",
            profile_version="ocr-paddle-v1", idempotency_key="expand-paddle",
        )
        self.assertNotEqual(glm[0]["job"]["job_id"], paddle[0]["job"]["job_id"])
        jobs = restarted.store.eligibility_subject_evidence_jobs(
            "proj_d001", "SA07005"
        )
        self.assertEqual(2, len([job for job in jobs if job["job_kind"] == "ocr"]))

        internal = restarted.store.eligibility_evidence_job(
            "proj_d001", glm[0]["job"]["job_id"]
        )
        self.assertEqual("page-artifact-1", internal["input_artifact_id"])
        with sqlite3.connect(self.store.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE eligibility_evidence_jobs SET page_index = 2
                    WHERE project_id = ? AND job_id = ?
                    """,
                    ("proj_d001", internal["job_id"]),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    UPDATE eligibility_evidence_jobs SET profile_digest = ?
                    WHERE project_id = ? AND job_id = ?
                    """,
                    ("f" * 64, "proj_d001", internal["job_id"]),
                )

    def test_schema_v9_migrates_to_current_and_is_restart_safe(self):
        self.create()
        with sqlite3.connect(self.store.db_path) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_visual_qc_record_no_update"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_visual_qc_record_no_delete"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_evidence_span_no_delete"
            )
            connection.execute("DROP TABLE eligibility_evidence_visual_qc_state")
            connection.execute("DROP TABLE eligibility_evidence_visual_qc_records")
            connection.execute(
                "DROP INDEX IF EXISTS idx_eligibility_evidence_span_extraction_identity"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_evidence_job_profile_digest_immutable"
            )
            connection.execute(
                "ALTER TABLE eligibility_evidence_jobs DROP COLUMN profile_digest"
            )
            connection.execute("DELETE FROM schema_migrations WHERE version >= 10")
            connection.commit()

        migrated = SqliteRuntimeStore(self.store.db_path)
        with sqlite3.connect(self.store.db_path) as connection:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(eligibility_evidence_jobs)"
                ).fetchall()
            }
        self.assertEqual(16, version)
        self.assertIn("profile_digest", columns)
        migrated_job = migrated.eligibility_evidence_job(
            "proj_d001", "eligjob-001"
        )
        self.assertEqual(
            ocr_profile_digest("ocr-glm-v1"), migrated_job["profile_digest"]
        )
        backups = list(Path(self.tmp.name).glob("runtime.sqlite3.v9.*.bak"))
        self.assertEqual(1, len(backups))
        restarted = SqliteRuntimeStore(migrated.db_path)
        self.assertEqual(16, restarted.health_report()["schema_version"])

    def test_pdf_page_child_rejects_incomplete_parent_and_cross_project_artifact(self):
        self.create_render_parent()
        service = EligibilityEvidenceTaskService(self.store)
        with self.assertRaisesRegex(ValueError, "completed PDF render"):
            service.expand_pdf_render_to_ocr(
                project_id="proj_d001", parent_job_id="render-parent-1",
                profile_version="ocr-glm-v1", idempotency_key="expand-incomplete",
            )
        self.store.finalize_pdf_render_with_ocr_children(
            "proj_d001", "render-parent-1", worker_id="render-worker",
            profile_versions=("ocr-glm-v1",), now=NOW,
        )
        self.store.create_eligibility_evidence_job(
            self.job(
                project_id="proj_my009_uc", subject_id="S01009",
                job_id="other-render-parent", job_kind="pdf_page_render",
                profile_version="pdf-render-200dpi-v1",
                cache_key="other-render-cache",
            ),
            idempotency_key="other-render-parent",
            request_fingerprint="other-render-parent-fingerprint",
        )
        self.store.add_eligibility_evidence_artifact({
            "project_id": "proj_my009_uc", "subject_id": "S01009",
            "job_id": "other-render-parent",
            "artifact_id": "artifact-from-other-project",
            "artifact_kind": "pdf_page_image",
            "storage_key": "proj_my009_uc/S01009/other-render-parent/page-0001.png",
            "content_hash": "b" * 64, "size_bytes": 128,
            "media_type": "image/png", "source_id": "source-001",
            "source_revision": "source-rev-001",
            "extraction_revision": "other-render-rev",
            "locator": {"page": 1, "dpi": 200},
            "quality_state": "needs_visual_qc", "created_at": NOW.isoformat(),
        })
        with self.assertRaisesRegex(ValueError, "current project"):
            self.store.create_eligibility_evidence_job(
                self.job(
                    job_id="cross-project-child",
                    source_id="source-pdf-1",
                    source_revision="source-pdf-rev-1",
                    subject_source_revision="subject-source-pdf-v1",
                    cache_key="cross-project-cache",
                    parent_job_id="render-parent-1",
                    input_artifact_id="artifact-from-other-project",
                    page_index=1,
                ),
                idempotency_key="cross-project-child",
                request_fingerprint="cross-project-child-fingerprint",
            )

    def test_atomic_finalize_rolls_back_all_children_and_parent_on_fault(self):
        self.create_render_parent()

        def fail(checkpoint):
            if checkpoint == "eligibility_pdf_render_after_children_insert":
                raise RuntimeError("injected atomic finalize failure")

        self.store.fault_injector = fail
        with self.assertRaisesRegex(RuntimeError, "injected"):
            self.store.finalize_pdf_render_with_ocr_children(
                "proj_d001", "render-parent-1", worker_id="render-worker",
                profile_versions=("ocr-glm-v1", "ocr-paddle-v1"), now=NOW,
            )
        parent = self.store.eligibility_evidence_job(
            "proj_d001", "render-parent-1"
        )
        self.assertEqual("running", parent["status"])
        self.assertEqual(
            [], self.store.eligibility_pdf_render_ocr_children(
                "proj_d001", "render-parent-1"
            )
        )

    def test_atomic_finalize_rejects_missing_page_and_expired_or_old_lease(self):
        self.create_render_parent(pages=(1,), progress_total=2, lease_seconds=10)
        with self.assertRaisesRegex(RuntimeStoreIntegrityError, "cover progress_total"):
            self.store.finalize_pdf_render_with_ocr_children(
                "proj_d001", "render-parent-1", worker_id="render-worker",
                profile_versions=("ocr-glm-v1",), now=NOW,
            )
        self.store.add_eligibility_evidence_artifact({
            "project_id": "proj_d001", "subject_id": "SA07005",
            "job_id": "render-parent-1", "artifact_id": "duplicate-page-1",
            "artifact_kind": "pdf_page_image",
            "storage_key": "proj_d001/SA07005/render-parent-1/duplicate-0001.png",
            "content_hash": "d" * 64, "size_bytes": 128,
            "media_type": "image/png", "source_id": "source-pdf-1",
            "source_revision": "source-pdf-rev-1",
            "extraction_revision": "duplicate-render-rev-1",
            "locator": {"page": 1, "dpi": 200},
            "quality_state": "needs_visual_qc", "created_at": NOW.isoformat(),
        })
        with self.assertRaisesRegex(RuntimeStoreIntegrityError, "inconsistent"):
            self.store.finalize_pdf_render_with_ocr_children(
                "proj_d001", "render-parent-1", worker_id="render-worker",
                profile_versions=("ocr-glm-v1",), now=NOW,
            )
        with self.assertRaises(StaleRuntimeStateError):
            self.store.finalize_pdf_render_with_ocr_children(
                "proj_d001", "render-parent-1", worker_id="old-worker",
                profile_versions=("ocr-glm-v1",), now=NOW,
            )
        with self.assertRaisesRegex(StaleRuntimeStateError, "expired"):
            self.store.finalize_pdf_render_with_ocr_children(
                "proj_d001", "render-parent-1", worker_id="render-worker",
                profile_versions=("ocr-glm-v1",),
                now=NOW + timedelta(seconds=11),
            )
        self.assertEqual(
            [], self.store.eligibility_pdf_render_ocr_children(
                "proj_d001", "render-parent-1"
            )
        )

    def test_generic_completion_cannot_bypass_atomic_render_finalizer(self):
        self.create_render_parent()
        with self.assertRaisesRegex(ValueError, "atomic OCR child"):
            self.store.complete_eligibility_evidence_job(
                "proj_d001", "render-parent-1", worker_id="render-worker", now=NOW
            )
        self.assertEqual(
            "running",
            self.store.eligibility_evidence_job(
                "proj_d001", "render-parent-1"
            )["status"],
        )


if __name__ == "__main__":
    unittest.main()
