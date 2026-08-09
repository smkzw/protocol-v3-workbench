from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from services.api.app.sqlite_runtime_store import (
    IdempotencyConflictError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


class EligibilityVisualQcTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "runtime.sqlite3"
        self.store = SqliteRuntimeStore(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def seed(
        self,
        *,
        project_id="proj_d001",
        subject_id="SA11004",
        evidence_id="evidence-1",
        source_revision="source-rev-1",
        extraction_revision="extract-rev-1",
        processing_state="needs_visual_qc",
    ):
        self.store.replace_eligibility_rule_revision(
            project_id,
            "rule-rev-1",
            [
                {
                    "criterion_uid": "criterion-in-01",
                    "criterion_kind": "inclusion",
                    "source_rule_label": "IN-01",
                    "source_locator": {"paragraph": 1},
                    "normalized_text_hash": "rule-hash",
                    "display_order": 1,
                }
            ],
        )
        self.store.replace_eligibility_subject_sources(
            project_id,
            subject_id,
            "subject-source-rev-1",
            [
                {
                    "source_id": "source-1",
                    "source_revision": source_revision,
                    "content_hash": f"hash-{project_id}",
                    "size_bytes": 100,
                    "media_class": "text_document_image",
                }
            ],
        )
        self.store.add_eligibility_evidence_span(
            {
                "project_id": project_id,
                "subject_id": subject_id,
                "evidence_id": evidence_id,
                "source_id": "source-1",
                "source_revision": source_revision,
                "extraction_revision": extraction_revision,
                "locator": {"page": 1, "region": [1, 2, 3, 4]},
                "media_class": "text_document_image",
                "processing_state": processing_state,
                "quality_state": "needs_visual_qc",
                "extraction_confidence": 0.91,
                "medical_verification_status": "not_reviewed",
            }
        )

    def qc(self, **updates):
        payload = {
            "project_id": "proj_d001",
            "subject_id": "SA11004",
            "evidence_id": "evidence-1",
            "expected_qc_revision": 0,
            "expected_source_revision": "source-rev-1",
            "expected_extraction_revision": "extract-rev-1",
            "idempotency_key": "qc-key-1",
            "result": "sampled_pass",
            "reason_code": "visual_comparison_completed",
            "user_reason": "The rendered page and extracted region match.",
            "sample_plan_id": "sample-plan-v1",
            "sample_unit": {"page": 1, "region": [1, 2, 3, 4]},
            "policy_version": "visual-qc-policy-v1",
            "actor": "medical_manager",
        }
        payload.update(updates)
        return self.store.commit_eligibility_evidence_visual_qc(**payload)

    @staticmethod
    def review_record(**updates):
        payload = {
            "record_id": "review-record-1",
            "project_id": "proj_d001",
            "subject_id": "SA11004",
            "criterion_uid": "criterion-in-01",
            "criterion_kind": "inclusion",
            "record_type": "medical_action",
            "action": "revise_decision",
            "action_decision": "met",
            "ai_draft_decision": None,
            "medical_decision": "met",
            "evidence_processing_state": "completed",
            "rule_revision": "rule-rev-1",
            "subject_source_revision": "subject-source-rev-1",
            "previous_state_revision": 0,
            "new_state_revision": 1,
            "evidence_ids": ["evidence-1"],
            "reason": "Criterion supported by current evidence.",
            "actor": "medical_manager",
            "ai_draft_record_id": None,
            "medical_record_id": "review-record-1",
        }
        payload.update(updates)
        return payload

    def commit_review(self, **record_updates):
        return self.store.commit_eligibility_review_action(
            self.review_record(**record_updates),
            expected_state_revision=0,
            expected_rule_revision="rule-rev-1",
            expected_subject_source_revision="subject-source-rev-1",
            idempotency_key="review-key-1",
            request_fingerprint="review-fingerprint-1",
        )

    def test_pass_replay_projection_restart_and_immutability(self):
        self.seed()
        first = self.qc()
        replay = self.qc()
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.qc_record_id, replay.qc_record_id)

        evidence = self.store.eligibility_subject_evidence_spans(
            "proj_d001", "SA11004"
        )[0]
        self.assertTrue(evidence["valid_for_decisive_review"])
        self.assertEqual("needs_visual_qc", evidence["stored_state"]["processing_state"])
        self.assertEqual("completed", evidence["effective_state"]["processing_state"])
        self.assertEqual("not_reviewed", evidence["medical_verification_status"])
        self.assertEqual("unverified_client_claim", evidence["visual_qc"]["identity_assurance"])
        self.assertFalse(evidence["visual_qc"]["is_electronic_signature"])
        self.assertNotIn("request_hash", str(evidence))

        restarted = SqliteRuntimeStore(self.db_path)
        self.assertTrue(
            restarted.eligibility_subject_evidence_spans(
                "proj_d001", "SA11004"
            )[0]["valid_for_decisive_review"]
        )
        with sqlite3.connect(self.db_path) as connection:
            record_id = connection.execute(
                "SELECT qc_record_id FROM eligibility_evidence_visual_qc_records"
            ).fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE eligibility_evidence_visual_qc_records SET user_reason='x' WHERE qc_record_id=?",
                    (record_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM eligibility_evidence_visual_qc_records WHERE qc_record_id=?",
                    (record_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM eligibility_evidence_spans")

    def test_validation_idempotency_conflict_and_cas(self):
        self.seed()
        with self.assertRaisesRegex(ValueError, "sample_plan_id"):
            self.qc(sample_plan_id=None)
        with self.assertRaisesRegex(ValueError, "reasons"):
            self.qc(user_reason="  ")
        self.qc()
        with self.assertRaises(IdempotencyConflictError):
            self.qc(user_reason="Different payload")
        with self.assertRaises(StaleRuntimeStateError):
            self.qc(idempotency_key="qc-key-stale")
        rejection_types = {
            item["event_type"]
            for item in self.store.runtime_audit_records("proj_d001")
        }
        self.assertIn(
            "eligibility_visual_qc_idempotency_conflict_rejected",
            rejection_types,
        )
        self.assertIn(
            "eligibility_visual_qc_stale_write_rejected",
            rejection_types,
        )

    def test_latest_qc_record_controls_effective_projection(self):
        self.seed()
        self.qc()
        manual = self.qc(
            expected_qc_revision=1,
            idempotency_key="qc-key-manual-2",
            result="manual_review_required",
            sample_plan_id=None,
            sample_unit=None,
            user_reason="A second reviewer requires manual reconciliation.",
        )
        self.assertEqual(2, manual.qc_revision)
        evidence = self.store.eligibility_subject_evidence_spans(
            "proj_d001", "SA11004"
        )[0]
        self.assertFalse(evidence["valid_for_decisive_review"])
        self.assertEqual("manual_review_required", evidence["visual_qc"]["result"])
        with self.assertRaisesRegex(
            ValueError, "evidence_not_valid_for_decisive_review"
        ):
            self.commit_review()

    def test_no_qc_fail_and_manual_cannot_be_decisive_or_overridden(self):
        for result in (None, "sampled_fail", "manual_review_required"):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                self.store = SqliteRuntimeStore(Path(tmp) / "runtime.sqlite3")
                self.seed()
                if result == "sampled_fail":
                    self.qc(result=result)
                elif result == "manual_review_required":
                    self.qc(
                        result=result,
                        sample_plan_id=None,
                        sample_unit=None,
                    )
                with self.assertRaisesRegex(
                    ValueError, "evidence_not_valid_for_decisive_review"
                ):
                    self.commit_review(evidence_processing_state="completed")
                self.assertIsNone(
                    self.store.eligibility_review_state(
                        "proj_d001", "SA11004", "criterion-in-01"
                    )
                )

    def test_fail_and_manual_do_not_complete_server_evidence_processing(self):
        for result in ("sampled_fail", "manual_review_required"):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                self.store = SqliteRuntimeStore(Path(tmp) / "runtime.sqlite3")
                self.seed()
                self.qc(
                    result=result,
                    sample_plan_id=("sample-plan-v1" if result == "sampled_fail" else None),
                    sample_unit=(
                        {"page": 1, "region": [1, 2, 3, 4]}
                        if result == "sampled_fail"
                        else None
                    ),
                )
                with self.assertRaisesRegex(
                    ValueError, "derived by the server"
                ):
                    self.commit_review(
                        action_decision="insufficient_evidence",
                        medical_decision="insufficient_evidence",
                        evidence_ids=[],
                    )

    def test_ai_draft_batch_cannot_reference_unpassed_evidence(self):
        self.seed()
        row = {
            "record_id": "ai-record-1",
            "project_id": "proj_d001",
            "subject_id": "SA11004",
            "criterion_uid": "criterion-in-01",
            "criterion_kind": "inclusion",
            "record_type": "ai_draft",
            "action": "save_ai_draft",
            "action_decision": "met",
            "evidence_processing_state": "completed",
            "rule_revision": "rule-rev-1",
            "subject_source_revision": "subject-source-rev-1",
            "previous_state_revision": 0,
            "new_state_revision": 1,
            "evidence_ids": ["evidence-1"],
            "reason": "AI draft rationale.",
            "actor": "workbench_ai_gateway",
        }
        with self.assertRaisesRegex(StaleRuntimeStateError, "visual-QC passed"):
            self.store.commit_eligibility_ai_draft_batch(
                [row],
                batch_id="batch-1",
                idempotency_key="batch-key-1",
                request_fingerprint="batch-fingerprint-1",
            )
        self.qc()
        committed = self.store.commit_eligibility_ai_draft_batch(
            [row],
            batch_id="batch-2",
            idempotency_key="batch-key-2",
            request_fingerprint="batch-fingerprint-2",
        )
        self.assertEqual(1, committed.state_revisions["criterion-in-01"])

    def test_d001_my009_project_subject_source_and_extraction_isolation(self):
        self.seed()
        self.seed(
            project_id="proj_my009_uc",
            subject_id="S01009",
            source_revision="my-source-rev-1",
            extraction_revision="my-extract-rev-1",
        )
        self.qc()
        with self.assertRaises(StaleRuntimeStateError):
            self.qc(
                project_id="proj_my009_uc",
                subject_id="S01009",
                idempotency_key="cross-project",
            )
        with self.assertRaises(StaleRuntimeStateError):
            self.qc(
                idempotency_key="wrong-extraction",
                expected_extraction_revision="extract-rev-stale",
            )
        self.qc(
            project_id="proj_my009_uc",
            subject_id="S01009",
            expected_source_revision="my-source-rev-1",
            expected_extraction_revision="my-extract-rev-1",
            idempotency_key="my-qc-key",
        )
        self.assertTrue(
            self.store.eligibility_subject_evidence_spans(
                "proj_my009_uc", "S01009"
            )[0]["valid_for_decisive_review"]
        )

    def test_concurrent_cas_allows_one_writer(self):
        self.seed()
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        def submit(index):
            barrier.wait()
            try:
                result = self.qc(idempotency_key=f"concurrent-{index}")
                outcome = ("committed", result.qc_revision)
            except StaleRuntimeStateError:
                outcome = ("stale", None)
            with lock:
                outcomes.append(outcome)

        threads = [threading.Thread(target=submit, args=(index,)) for index in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(["committed", "stale"], sorted(item[0] for item in outcomes))

    def test_fault_injection_rolls_back_record_state_audit_and_idempotency(self):
        for checkpoint in (
            "after_eligibility_visual_qc_record",
            "after_eligibility_visual_qc_state",
            "after_eligibility_visual_qc_audit",
            "after_eligibility_visual_qc_idempotency",
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "runtime.sqlite3"
                seed = SqliteRuntimeStore(path)
                self.store = seed
                self.seed()

                def fail(current):
                    if current == checkpoint:
                        raise RuntimeError(f"fault:{checkpoint}")

                self.store = SqliteRuntimeStore(path, fault_injector=fail)
                with self.assertRaisesRegex(RuntimeError, checkpoint):
                    self.qc()
                with sqlite3.connect(path) as connection:
                    self.assertEqual(
                        0,
                        connection.execute(
                            "SELECT COUNT(*) FROM eligibility_evidence_visual_qc_records"
                        ).fetchone()[0],
                    )
                    self.assertEqual(
                        0,
                        connection.execute(
                            "SELECT COUNT(*) FROM eligibility_evidence_visual_qc_state"
                        ).fetchone()[0],
                    )
                    self.assertEqual(
                        0,
                        connection.execute(
                            "SELECT COUNT(*) FROM idempotency_records WHERE operation LIKE 'eligibility_visual_qc:%'"
                        ).fetchone()[0],
                    )
                self.assertEqual([], self.store.runtime_audit_records("proj_d001"))

    def test_v10_to_current_migration_creates_backup_and_is_repeatable(self):
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DROP TABLE eligibility_evidence_visual_qc_state")
            connection.execute("DROP TABLE eligibility_evidence_visual_qc_records")
            connection.execute("DELETE FROM schema_migrations WHERE version >= 11")
            connection.commit()
        migrated = SqliteRuntimeStore(self.db_path)
        self.assertTrue(list(self.root.glob("runtime.sqlite3.v10.*.bak")))
        restarted = SqliteRuntimeStore(self.db_path)
        with restarted._connect() as connection:
            self.assertEqual(
                16,
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
            )
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
            self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())
        self.assertIsNotNone(migrated)


if __name__ == "__main__":
    unittest.main()
