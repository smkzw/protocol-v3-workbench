from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.api.app.ocr_gateway import ocr_profile_digest
from services.api.app.sqlite_runtime_store import (
    RuntimeStoreIntegrityError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


class EligibilitySourceProcessingUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = SqliteRuntimeStore(
            Path(self.temp_dir.name) / "runtime.sqlite3"
        )
        self.project_id = "project-unit-ledger"
        self.subject_id = "SUBJECT-001"
        self.source_id = "source-pdf"
        self.source_revision = "source-pdf-r1"
        self.subject_source_revision = "subject-sources-r1"
        self.extraction_revision = "extract-r1"
        self.store.replace_eligibility_subject_sources(
            self.project_id,
            self.subject_id,
            self.subject_source_revision,
            [
                {
                    "source_id": self.source_id,
                    "source_revision": self.source_revision,
                    "content_hash": "1" * 64,
                    "size_bytes": 1024,
                    "media_class": "pdf",
                    "processing_unit_kind": "page",
                    "expected_unit_count": 2,
                }
            ],
        )
        self.store.create_eligibility_evidence_job(
            {
                "project_id": self.project_id,
                "subject_id": self.subject_id,
                "job_id": "job-pdf",
                "job_kind": "ocr",
                "profile_version": "ocr-glm-v1",
                "profile_digest": ocr_profile_digest("ocr-glm-v1"),
                "source_id": self.source_id,
                "source_revision": self.source_revision,
                "subject_source_revision": self.subject_source_revision,
                "cache_key": "unit-ledger-cache",
                "max_attempts": 3,
            },
            idempotency_key="create-unit-ledger-job",
            request_fingerprint="create-unit-ledger-job-v1",
        )
        self._add_artifact("artifact-page-1", 1, quality_state="needs_visual_qc")
        self._add_artifact("artifact-page-2", 2)
        self.store.add_eligibility_evidence_span(
            {
                "project_id": self.project_id,
                "subject_id": self.subject_id,
                "evidence_id": "evidence-page-1",
                "source_id": self.source_id,
                "source_revision": self.source_revision,
                "extraction_revision": self.extraction_revision,
                "locator": {"page": 1},
                "metadata": {"artifact_id": "artifact-page-1"},
                "media_class": "pdf",
                "processing_state": "completed",
                "quality_state": "sampled_pass",
                "extraction_confidence": 0.99,
                "medical_verification_status": "not_reviewed",
            }
        )
        self.store.commit_eligibility_evidence_visual_qc(
            project_id=self.project_id,
            subject_id=self.subject_id,
            evidence_id="evidence-page-1",
            expected_qc_revision=0,
            expected_source_revision=self.source_revision,
            expected_extraction_revision=self.extraction_revision,
            idempotency_key="qc-page-1",
            result="sampled_pass",
            reason_code="full_page_check",
            user_reason="Compared against the complete page.",
            sample_plan_id="full-page-v1",
            sample_unit={"page": 1},
            policy_version="visual-qc-policy-v1",
            actor="test-reviewer",
        )

    def _add_artifact(
        self,
        artifact_id: str,
        page: int,
        *,
        quality_state: str = "sampled_pass",
    ) -> None:
        self.store.add_eligibility_evidence_artifact(
            {
                "project_id": self.project_id,
                "subject_id": self.subject_id,
                "job_id": "job-pdf",
                "artifact_id": artifact_id,
                "artifact_kind": "ocr_text",
                "storage_key": f"controlled/{artifact_id}.json",
                "content_hash": str(page) * 64,
                "size_bytes": 128,
                "media_type": "application/json",
                "source_id": self.source_id,
                "source_revision": self.source_revision,
                "extraction_revision": self.extraction_revision,
                "locator": {"page": page},
                "quality_state": quality_state,
            }
        )

    def _state(self) -> str:
        with self.store._connect() as connection:
            return self.store._subject_evidence_processing_state(
                connection,
                project_id=self.project_id,
                subject_id=self.subject_id,
                subject_source_revision=self.subject_source_revision,
            )

    def _complete_extraction_job(self) -> None:
        claimed = self.store.claim_next_eligibility_evidence_job(
            "test-worker",
            job_kind="ocr",
            profile_version="ocr-glm-v1",
            profile_digest=ocr_profile_digest("ocr-glm-v1"),
        )
        self.assertIsNotNone(claimed)
        self.store.complete_eligibility_evidence_job(
            self.project_id,
            "job-pdf",
            worker_id="test-worker",
        )

    def test_all_declared_pages_must_be_resolved(self) -> None:
        self._complete_extraction_job()
        first = self.store.commit_eligibility_source_processing_unit(
            project_id=self.project_id,
            subject_id=self.subject_id,
            source_id=self.source_id,
            source_revision=self.source_revision,
            subject_source_revision=self.subject_source_revision,
            unit_index=1,
            expected_state_revision=0,
            processing_status="evidence_extracted",
            artifact_id="artifact-page-1",
            extraction_revision=self.extraction_revision,
            evidence_ids=["evidence-page-1"],
            reason_code="evidence_extracted_from_full_page",
            actor="test-worker",
            idempotency_key="unit-page-1",
        )
        self.assertFalse(first["replayed"])
        self.assertEqual("partial", self._state())

        second = self.store.commit_eligibility_source_processing_unit(
            project_id=self.project_id,
            subject_id=self.subject_id,
            source_id=self.source_id,
            source_revision=self.source_revision,
            subject_source_revision=self.subject_source_revision,
            unit_index=2,
            expected_state_revision=0,
            processing_status="processed_no_relevant_evidence",
            artifact_id="artifact-page-2",
            extraction_revision=self.extraction_revision,
            evidence_ids=[],
            reason_code="full_page_processed_no_eligibility_evidence",
            actor="test-worker",
            idempotency_key="unit-page-2",
        )
        self.assertEqual("completed", self._state())
        units = self.store.eligibility_source_processing_units(
            self.project_id,
            self.subject_id,
            self.subject_source_revision,
        )
        self.assertEqual(2, len(units))
        self.assertEqual([], units[1]["evidence_ids"])
        self.assertNotIn("storage_key", json.dumps(units))

        later = self.store.commit_eligibility_source_processing_unit(
            project_id=self.project_id,
            subject_id=self.subject_id,
            source_id=self.source_id,
            source_revision=self.source_revision,
            subject_source_revision=self.subject_source_revision,
            unit_index=2,
            expected_state_revision=1,
            processing_status="manual_review_required",
            artifact_id=None,
            extraction_revision=None,
            evidence_ids=[],
            reason_code="later_manual_review_request",
            actor="test-reviewer",
            idempotency_key="unit-page-2-revision-2",
        )
        self.assertEqual(2, later["state_revision"])

        replay = self.store.commit_eligibility_source_processing_unit(
            project_id=self.project_id,
            subject_id=self.subject_id,
            source_id=self.source_id,
            source_revision=self.source_revision,
            subject_source_revision=self.subject_source_revision,
            unit_index=2,
            expected_state_revision=0,
            processing_status="processed_no_relevant_evidence",
            artifact_id="artifact-page-2",
            extraction_revision=self.extraction_revision,
            evidence_ids=[],
            reason_code="full_page_processed_no_eligibility_evidence",
            actor="test-worker",
            idempotency_key="unit-page-2",
        )
        self.assertTrue(replay["replayed"])
        self.assertEqual(second["record_id"], replay["record_id"])
        self.assertEqual(1, replay["state_revision"])
        self.assertEqual(
            "processed_no_relevant_evidence", replay["processing_status"]
        )

    def test_new_subject_source_revision_does_not_reuse_old_unit_state(self) -> None:
        self._complete_extraction_job()
        self.store.commit_eligibility_source_processing_unit(
            project_id=self.project_id,
            subject_id=self.subject_id,
            source_id=self.source_id,
            source_revision=self.source_revision,
            subject_source_revision=self.subject_source_revision,
            unit_index=1,
            expected_state_revision=0,
            processing_status="evidence_extracted",
            artifact_id="artifact-page-1",
            extraction_revision=self.extraction_revision,
            evidence_ids=["evidence-page-1"],
            reason_code="old_contract_page_processed",
            actor="test-worker",
            idempotency_key="old-contract-page-1",
        )
        self.store.replace_eligibility_subject_sources(
            self.project_id,
            self.subject_id,
            "subject-sources-r2",
            [
                {
                    "source_id": self.source_id,
                    "source_revision": self.source_revision,
                    "content_hash": "1" * 64,
                    "size_bytes": 1024,
                    "media_class": "pdf",
                    "processing_unit_kind": "page",
                    "expected_unit_count": 2,
                }
            ],
        )
        with self.store._connect() as connection:
            state = self.store._subject_evidence_processing_state(
                connection,
                project_id=self.project_id,
                subject_id=self.subject_id,
                subject_source_revision="subject-sources-r2",
            )
        self.assertEqual("not_started", state)
        self.assertEqual(
            [],
            self.store.eligibility_source_processing_units(
                self.project_id,
                self.subject_id,
                "subject-sources-r2",
            ),
        )

    def test_resolved_unit_rejects_artifact_from_queued_job(self) -> None:
        with self.assertRaisesRegex(
            StaleRuntimeStateError, "extraction job is not durably completed"
        ):
            self.store.commit_eligibility_source_processing_unit(
                project_id=self.project_id,
                subject_id=self.subject_id,
                source_id=self.source_id,
                source_revision=self.source_revision,
                subject_source_revision=self.subject_source_revision,
                unit_index=1,
                expected_state_revision=0,
                processing_status="evidence_extracted",
                artifact_id="artifact-page-1",
                extraction_revision=self.extraction_revision,
                evidence_ids=["evidence-page-1"],
                reason_code="queued_job_must_not_resolve_unit",
                actor="test-worker",
                idempotency_key="queued-job-unit-1",
            )

    def test_no_evidence_unit_still_requires_artifact_level_qc(self) -> None:
        self._complete_extraction_job()
        self._add_artifact(
            "artifact-page-2-needs-qc",
            2,
            quality_state="needs_visual_qc",
        )

        with self.assertRaisesRegex(
            StaleRuntimeStateError,
            "without evidence has not passed quality control",
        ):
            self.store.commit_eligibility_source_processing_unit(
                project_id=self.project_id,
                subject_id=self.subject_id,
                source_id=self.source_id,
                source_revision=self.source_revision,
                subject_source_revision=self.subject_source_revision,
                unit_index=2,
                expected_state_revision=0,
                processing_status="processed_no_relevant_evidence",
                artifact_id="artifact-page-2-needs-qc",
                extraction_revision=self.extraction_revision,
                evidence_ids=[],
                reason_code="full_page_processed_no_eligibility_evidence",
                actor="test-worker",
                idempotency_key="unit-page-2-needs-qc",
            )

    def test_archive_container_cannot_be_resolved_without_member_extraction(self) -> None:
        self.store.replace_eligibility_subject_sources(
            self.project_id,
            "SUBJECT-ARCHIVE",
            "archive-sources-r1",
            [
                {
                    "source_id": "source-archive",
                    "source_revision": "source-archive-r1",
                    "content_hash": "a" * 64,
                    "size_bytes": 512,
                    "media_class": "archive",
                    "processing_unit_kind": "archive_container",
                    "expected_unit_count": 1,
                }
            ],
        )
        with self.assertRaisesRegex(ValueError, "safe member extraction"):
            self.store.commit_eligibility_source_processing_unit(
                project_id=self.project_id,
                subject_id="SUBJECT-ARCHIVE",
                source_id="source-archive",
                source_revision="source-archive-r1",
                subject_source_revision="archive-sources-r1",
                unit_index=1,
                expected_state_revision=0,
                processing_status="processed_no_relevant_evidence",
                artifact_id="artifact-page-1",
                extraction_revision=self.extraction_revision,
                evidence_ids=[],
                reason_code="incorrect_archive_resolution_attempt",
                actor="test-worker",
                idempotency_key="archive-unit-1",
            )

    def test_partial_v14_schema_is_rejected_transactionally(self) -> None:
        db_path = Path(self.temp_dir.name) / "malformed-v14.sqlite3"
        SqliteRuntimeStore(db_path)
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_source_unit_record_no_update"
            )
            connection.execute(
                "DROP TRIGGER IF EXISTS trg_eligibility_source_unit_record_no_delete"
            )
            connection.execute("DROP TABLE eligibility_source_processing_unit_state")
            connection.execute("DROP TABLE eligibility_source_processing_unit_records")
            connection.execute("DELETE FROM schema_migrations WHERE version = 14")
            connection.execute(
                "CREATE TABLE eligibility_source_processing_unit_records(unexpected TEXT)"
            )
            connection.commit()

        with self.assertRaisesRegex(
            RuntimeStoreIntegrityError, "non-contiguous schema migration history"
        ):
            SqliteRuntimeStore(db_path)
        with sqlite3.connect(db_path) as connection:
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                ).fetchall()
            ]
        self.assertEqual(16, versions[-1])
        self.assertNotIn(14, versions)
        self.assertTrue(list(db_path.parent.glob("malformed-v14.sqlite3.v13.*.bak")))


if __name__ == "__main__":
    unittest.main()
