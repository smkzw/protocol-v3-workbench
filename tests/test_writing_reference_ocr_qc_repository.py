from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts.models import (
    WritingReferenceOcrConsistencyMedicalDispositionTarget,
    WritingReferenceOcrConsistencyQcRecheck,
)
from services.api.app.writing_reference import extract_pdf_sections
from services.api.app.writing_reference_repository import (
    WritingReferenceConflictError,
    WritingReferenceRepository,
    WritingReferenceStaleStateError,
    _payload_hash,
)
from tests.test_writing_reference_repository import snapshot
from tests.test_writing_reference_extraction import artifact, pdf_fixture


PROJECT_ID = "proj_rux_03_002"
NOW = datetime(2026, 7, 30, 8, 0, tzinfo=timezone.utc)


class WritingReferenceOcrQcRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "writing_reference.sqlite3"
        self.repo = WritingReferenceRepository(self.db_path)
        self.repo.save_search_snapshot(snapshot(), idempotency_key="ocr-search")
        self.pdf = pdf_fixture()
        self.artifact = artifact(hashlib.sha256(self.pdf).hexdigest()).model_copy(
            update={"actual_size": len(self.pdf), "created_at": NOW}
        )
        self.repo.save_document_artifact(
            self.artifact,
            storage_relpath="fixtures/ocr/source.pdf",
            idempotency_key="ocr-artifact",
        )
        qc = {"triggered": True, "verdict": "review_required", "notes": "boundary"}
        self.extraction = extract_pdf_sections(self.pdf, self.artifact).model_copy(
            update={
                "extraction_revision": "extract_ocr_r1",
                "ocr_consistency_qc": qc,
                "spans": [
                    span.model_copy(
                        update={
                            "span_id": f"{span.span_id}_ocr_r1",
                            "extraction_revision": "extract_ocr_r1",
                        }
                    )
                    for span in extract_pdf_sections(self.pdf, self.artifact).spans
                ],
            }
        )
        self.repo.save_extraction(self.extraction, idempotency_key="ocr-extraction-1")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _recheck(self, revision: int = 1, recheck_id: str | None = None, verdict: str = "review_required") -> WritingReferenceOcrConsistencyQcRecheck:
        qc_identity = _payload_hash(self.extraction.ocr_consistency_qc)
        return WritingReferenceOcrConsistencyQcRecheck(
            recheck_id=recheck_id or f"wref_ocr_recheck_{revision}",
            project_id=PROJECT_ID,
            artifact_id=self.artifact.artifact_id,
            extraction_revision=self.extraction.extraction_revision,
            base_qc_identity_hash=qc_identity,
            stage_version="mixed_ocr_consistency_qc_v2",
            schema_version="mixed_ocr_consistency_qc_v2",
            provider="deepseek_official",
            model="deepseek-v4-flash",
            prompt_version="mixed_ocr_boundary_v3",
            models=["paddle/PaddleOCR-VL-1.6", "omlx/GLM-OCR-bf16"],
            physical_pages=[2, 3],
            verdict=verdict,
            notes="verify page boundary",
            input_hash="i" * 64,
            output_hash=("o" * 63) + str(revision),
            revision=revision,
            created_at=NOW.replace(minute=revision),
        )

    def test_schema_v8_and_immutable_facts_survive_restart(self) -> None:
        self.assertEqual(8, self.repo.health_report()["schema_version"])
        recheck = self.repo.save_ocr_consistency_qc_recheck(
            self._recheck(), expected_revision=0, idempotency_key="ocr-recheck-1"
        )
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            extraction_before = connection.execute(
                "SELECT payload_json FROM writing_reference_extractions WHERE project_id=? AND artifact_id=?",
                (PROJECT_ID, self.artifact.artifact_id),
            ).fetchone()["payload_json"]
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE writing_reference_ocr_consistency_qc_recheck_records SET notes_json='[]' WHERE recheck_id=?",
                    (recheck.recheck_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM writing_reference_ocr_consistency_qc_recheck_records WHERE recheck_id=?",
                    (recheck.recheck_id,),
                )
            extraction_after = connection.execute(
                "SELECT payload_json FROM writing_reference_extractions WHERE project_id=? AND artifact_id=?",
                (PROJECT_ID, self.artifact.artifact_id),
            ).fetchone()["payload_json"]
        self.assertEqual(extraction_before, extraction_after)
        restarted = WritingReferenceRepository(self.db_path)
        self.assertEqual(recheck.model_dump(), restarted.latest_ocr_consistency_qc_recheck(PROJECT_ID, self.artifact.artifact_id).model_dump())

    def test_v7_to_v8_migration_is_additive_and_safe(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DELETE FROM schema_migrations WHERE version=8")
            for trigger in (
                "trg_wref_ocr_disposition_no_delete",
                "trg_wref_ocr_disposition_no_update",
                "trg_wref_ocr_recheck_no_delete",
                "trg_wref_ocr_recheck_no_update",
            ):
                connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            connection.execute("DROP TABLE writing_reference_ocr_consistency_medical_disposition_state")
            connection.execute("DROP TABLE writing_reference_ocr_consistency_medical_disposition_records")
            connection.execute("DROP TABLE writing_reference_ocr_consistency_qc_recheck_state")
            connection.execute("DROP TABLE writing_reference_ocr_consistency_qc_recheck_records")
        migrated = WritingReferenceRepository(self.db_path)
        self.assertEqual(8, migrated.health_report()["schema_version"])
        with sqlite3.connect(self.db_path) as connection:
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
            self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("writing_reference_ocr_consistency_qc_recheck_records", tables)
        self.assertIn("writing_reference_ocr_consistency_medical_disposition_state", tables)

    def test_recheck_idempotency_replay_and_conflict(self) -> None:
        first = self.repo.save_ocr_consistency_qc_recheck(self._recheck(), expected_revision=0, idempotency_key="same-key")
        replay = self.repo.save_ocr_consistency_qc_recheck(self._recheck(), expected_revision=0, idempotency_key="same-key")
        self.assertEqual(first.model_dump(), replay.model_dump())
        changed = self._recheck(recheck_id="wref_ocr_recheck_changed")
        changed = changed.model_copy(update={"notes": "different conclusion"})
        with self.assertRaises(WritingReferenceConflictError):
            self.repo.save_ocr_consistency_qc_recheck(changed, expected_revision=0, idempotency_key="same-key")
        with self.assertRaises(WritingReferenceConflictError):
            self.repo.save_ocr_consistency_qc_recheck(
                self._recheck(recheck_id=first.recheck_id).model_copy(update={"notes": "different conclusion"}),
                expected_revision=0,
                idempotency_key="another-key",
            )

    def test_effective_status_and_new_recheck_invalidates_old_confirmation(self) -> None:
        first = self.repo.save_ocr_consistency_qc_recheck(self._recheck(), expected_revision=0, idempotency_key="recheck-1")
        disposition = self.repo.record_ocr_consistency_medical_disposition(
            project_id=PROJECT_ID, artifact_id=self.artifact.artifact_id,
            extraction_revision=self.extraction.extraction_revision, recheck_id=first.recheck_id,
            recheck_revision=1, decision="confirmed", comment="医学已核对复核边界并同意继续使用",
            actor="medical_manager", expected_revision=0, idempotency_key="disposition-1",
        )
        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE writing_reference_ocr_consistency_medical_disposition_records SET comment='tampered' WHERE disposition_id=?",
                    (disposition.disposition_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM writing_reference_ocr_consistency_medical_disposition_records WHERE disposition_id=?",
                    (disposition.disposition_id,),
                )
        projection = self.repo.ocr_consistency_qc_reviews(PROJECT_ID)[0]
        self.assertEqual("medical_confirmed_with_residual_issue", projection.effective_status)
        second = self.repo.save_ocr_consistency_qc_recheck(self._recheck(2, recheck_id="wref_ocr_recheck_2"), expected_revision=1, idempotency_key="recheck-2")
        projection = self.repo.ocr_consistency_qc_reviews(PROJECT_ID)[0]
        self.assertEqual("pending_medical_confirmation", projection.effective_status)
        self.assertEqual("", projection.disposition_id)
        with sqlite3.connect(self.db_path) as connection:
            history_count = connection.execute(
                "SELECT COUNT(*) FROM writing_reference_ocr_consistency_medical_disposition_records WHERE disposition_id=?",
                (disposition.disposition_id,),
            ).fetchone()[0]
        self.assertEqual(1, history_count)
        current = self.repo.record_ocr_consistency_medical_disposition(
            project_id=PROJECT_ID, artifact_id=self.artifact.artifact_id,
            extraction_revision=self.extraction.extraction_revision, recheck_id=second.recheck_id,
            recheck_revision=2, decision="confirmed", comment="医学已核对第二版复核并同意继续使用",
            actor="medical_manager", expected_revision=0, idempotency_key="disposition-2",
        )
        self.assertNotEqual(disposition.disposition_id, current.disposition_id)
        self.assertEqual("medical_confirmed_with_residual_issue", self.repo.ocr_consistency_qc_reviews(PROJECT_ID)[0].effective_status)

    def test_stale_latest_extraction_and_stale_disposition_are_rejected(self) -> None:
        first = self.repo.save_ocr_consistency_qc_recheck(self._recheck(), expected_revision=0, idempotency_key="stale-recheck")
        with self.assertRaises(WritingReferenceStaleStateError):
            self.repo.save_ocr_consistency_qc_recheck(self._recheck(2, recheck_id="wrong-revision"), expected_revision=0, idempotency_key="wrong-expected")
        with self.assertRaises(WritingReferenceStaleStateError):
            self.repo.record_ocr_consistency_medical_disposition(
                project_id=PROJECT_ID, artifact_id=self.artifact.artifact_id,
                extraction_revision=self.extraction.extraction_revision, recheck_id=first.recheck_id,
                recheck_revision=1, decision="confirmed", comment="医学复核结论记录",
                actor="medical_manager", expected_revision=1, idempotency_key="stale-disposition",
            )

    def test_batch_has_partial_success(self) -> None:
        valid = self.repo.save_ocr_consistency_qc_recheck(self._recheck(), expected_revision=0, idempotency_key="batch-recheck")
        result = self.repo.record_batch_ocr_consistency_medical_disposition(
            project_id=PROJECT_ID,
            targets=[
                WritingReferenceOcrConsistencyMedicalDispositionTarget(
                    artifact_id=self.artifact.artifact_id,
                    extraction_revision=self.extraction.extraction_revision,
                    recheck_id=valid.recheck_id,
                    recheck_revision=1,
                    expected_revision=0,
                ),
                WritingReferenceOcrConsistencyMedicalDispositionTarget(
                    artifact_id=self.artifact.artifact_id,
                    extraction_revision=self.extraction.extraction_revision,
                    recheck_id=valid.recheck_id,
                    recheck_revision=1,
                    expected_revision=0,
                ),
            ],
            decision="confirmed",
            comment="批量医学复核：当前复核意见已逐项核对",
            actor="medical_manager",
            idempotency_key="batch-disposition",
        )
        self.assertEqual(["confirmed", "stale"], [item.outcome for item in result.outcomes])
        replay = self.repo.record_batch_ocr_consistency_medical_disposition(
            project_id=PROJECT_ID,
            targets=[item.model_copy(update={"expected_revision": 0}) for item in [
                WritingReferenceOcrConsistencyMedicalDispositionTarget(
                    artifact_id=self.artifact.artifact_id,
                    extraction_revision=self.extraction.extraction_revision,
                    recheck_id=valid.recheck_id,
                    recheck_revision=1,
                    expected_revision=0,
                ),
                WritingReferenceOcrConsistencyMedicalDispositionTarget(
                    artifact_id=self.artifact.artifact_id,
                    extraction_revision=self.extraction.extraction_revision,
                    recheck_id=valid.recheck_id,
                    recheck_revision=1,
                    expected_revision=0,
                ),
            ]],
            decision="confirmed", comment="批量医学复核：当前复核意见已逐项核对", actor="medical_manager", idempotency_key="batch-disposition",
        )
        self.assertEqual(
            [item.model_dump() for item in result.outcomes],
            [item.model_dump() for item in replay.outcomes],
        )

    def test_only_current_review_required_recheck_accepts_disposition(self) -> None:
        review = self.repo.save_ocr_consistency_qc_recheck(
            self._recheck(),
            expected_revision=0,
            idempotency_key="review-current",
        )
        passed = self.repo.save_ocr_consistency_qc_recheck(
            self._recheck(2, recheck_id="wref_ocr_recheck_pass", verdict="pass"),
            expected_revision=1,
            idempotency_key="pass-current",
        )
        with self.assertRaises(WritingReferenceStaleStateError):
            self.repo.record_ocr_consistency_medical_disposition(
                project_id=PROJECT_ID,
                artifact_id=self.artifact.artifact_id,
                extraction_revision=self.extraction.extraction_revision,
                recheck_id=review.recheck_id,
                recheck_revision=review.revision,
                decision="confirmed",
                comment="不得确认已经过期的 OCR 重检结论",
                actor="medical_manager",
                expected_revision=0,
                idempotency_key="stale-old-recheck",
            )
        with self.assertRaises(ValueError):
            self.repo.record_ocr_consistency_medical_disposition(
                project_id=PROJECT_ID,
                artifact_id=self.artifact.artifact_id,
                extraction_revision=self.extraction.extraction_revision,
                recheck_id=passed.recheck_id,
                recheck_revision=passed.revision,
                decision="confirmed",
                comment="通过结论无需额外医学确认",
                actor="medical_manager",
                expected_revision=0,
                idempotency_key="invalid-pass-disposition",
            )


if __name__ == "__main__":
    unittest.main()
