from __future__ import annotations

import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.sqlite_runtime_store import (  # noqa: E402
    IdempotencyConflictError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECT_ID = "proj_d001"
OTHER_PROJECT_ID = "proj_my009"
SUBJECT_ID = "shared-subject"
CRITERION_UID = "criterion-in-01"
RULE_REVISION = "rule-rev-1"
SOURCE_REVISION = "source-rev-1"
SUBJECT_SOURCE_REVISION = "subject-source-rev-1"
NOW = datetime(2026, 7, 11, 4, 0, tzinfo=timezone.utc)


class SqliteEligibilityReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "runtime.sqlite3"
        self.store = SqliteRuntimeStore(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def seed_identity(self, store=None, *, project_id=PROJECT_ID):
        target = store or self.store
        target.replace_eligibility_rule_revision(
            project_id,
            RULE_REVISION,
            [
                {
                    "criterion_uid": CRITERION_UID,
                    "criterion_kind": "inclusion",
                    "source_rule_label": "IN-01",
                    "source_locator": {"document": "protocol.docx", "paragraph": 10},
                    "normalized_text_hash": "rule-text-hash",
                    "display_order": 1,
                }
            ],
            created_at=NOW,
        )
        target.replace_eligibility_subject_sources(
            project_id,
            SUBJECT_ID,
            SUBJECT_SOURCE_REVISION,
            [
                {
                    "source_id": "source-1",
                    "source_revision": SOURCE_REVISION,
                    "content_hash": "source-content-hash",
                    "size_bytes": 123,
                    "media_class": "text_document_image",
                }
            ],
            created_at=NOW,
        )
        target.add_eligibility_evidence_span(
            {
                "evidence_id": "evidence-1",
                "project_id": project_id,
                "subject_id": SUBJECT_ID,
                "source_id": "source-1",
                "source_revision": SOURCE_REVISION,
                "extraction_revision": "extract-rev-1",
                "locator": {"page": 1, "region": [10, 20, 30, 40]},
                "media_class": "text_document_image",
                "processing_state": "completed",
                "quality_state": "sampled_pass",
                "extraction_confidence": 0.92,
                "medical_verification_status": "not_reviewed",
                "created_at": NOW.isoformat(),
            }
        )
        target.commit_eligibility_evidence_visual_qc(
            project_id=project_id,
            subject_id=SUBJECT_ID,
            evidence_id="evidence-1",
            expected_qc_revision=0,
            expected_source_revision=SOURCE_REVISION,
            expected_extraction_revision="extract-rev-1",
            idempotency_key=f"seed-qc-{project_id}",
            result="sampled_pass",
            reason_code="fixture_visual_check",
            user_reason="Fixture image and extracted region were visually compared.",
            sample_plan_id="fixture-plan-v1",
            sample_unit={"page": 1, "region": [10, 20, 30, 40]},
            policy_version="fixture-policy-v1",
            actor="medical_manager",
        )

    def review_record(self, **updates):
        payload = {
            "record_id": "review-record-1",
            "project_id": PROJECT_ID,
            "subject_id": SUBJECT_ID,
            "criterion_uid": CRITERION_UID,
            "criterion_kind": "inclusion",
            "record_type": "medical_action",
            "action": "revise_decision",
            "action_decision": "met",
            "ai_draft_decision": None,
            "medical_decision": "met",
            "evidence_processing_state": "completed",
            "rule_revision": RULE_REVISION,
            "subject_source_revision": SUBJECT_SOURCE_REVISION,
            "previous_state_revision": 0,
            "new_state_revision": 1,
            "evidence_ids": ["evidence-1"],
            "reason": "Current source metadata supports this criterion review.",
            "actor": "medical_manager",
            "ai_draft_record_id": None,
            "medical_record_id": "review-record-1",
            "created_at": NOW.isoformat(),
        }
        payload.update(updates)
        return payload

    def commit(self, record=None, *, key="criterion-key-1", fingerprint="fingerprint-1"):
        return self.store.commit_eligibility_review_action(
            record or self.review_record(),
            expected_state_revision=0,
            expected_rule_revision=RULE_REVISION,
            expected_subject_source_revision=SUBJECT_SOURCE_REVISION,
            idempotency_key=key,
            request_fingerprint=fingerprint,
        )

    def test_identical_rule_and_source_registration_is_database_noop(self):
        self.seed_identity()
        before = sha256(self.db_path.read_bytes()).hexdigest()

        self.store.replace_eligibility_rule_revision(
            PROJECT_ID,
            RULE_REVISION,
            [
                {
                    "criterion_uid": CRITERION_UID,
                    "criterion_kind": "inclusion",
                    "source_rule_label": "IN-01",
                    "source_locator": {"document": "protocol.docx", "paragraph": 10},
                    "normalized_text_hash": "rule-text-hash",
                    "display_order": 1,
                }
            ],
            created_at=NOW,
        )
        self.store.replace_eligibility_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            SUBJECT_SOURCE_REVISION,
            [
                {
                    "source_id": "source-1",
                    "source_revision": SOURCE_REVISION,
                    "content_hash": "source-content-hash",
                    "size_bytes": 123,
                    "media_class": "text_document_image",
                }
            ],
            created_at=NOW,
        )

        self.assertEqual(before, sha256(self.db_path.read_bytes()).hexdigest())

    def test_schema_v7_is_additive_and_backs_up_an_isolated_v5_database(self):
        v5_path = self.root / "isolated-v5.sqlite3"
        with sqlite3.connect(v5_path) as connection:
            connection.execute(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                [(version, NOW.isoformat()) for version in range(1, 6)],
            )
            connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
            connection.execute("INSERT INTO legacy_marker(value) VALUES ('v5-preserved')")
            connection.commit()

        SqliteRuntimeStore(v5_path)

        backups = list(self.root.glob("isolated-v5.sqlite3.v5.*.bak"))
        self.assertEqual(1, len(backups))
        with sqlite3.connect(backups[0]) as backup:
            self.assertEqual(
                "v5-preserved",
                backup.execute("SELECT value FROM legacy_marker").fetchone()[0],
            )
            self.assertEqual(
                5,
                backup.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
            )
        with sqlite3.connect(v5_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertEqual(
                {
                    "eligibility_source_revisions",
                    "eligibility_rule_revisions",
                    "eligibility_evidence_spans",
                    "eligibility_review_records",
                    "eligibility_review_state",
                    "eligibility_evidence_jobs",
                    "eligibility_evidence_job_attempts",
                    "eligibility_evidence_artifacts",
                    "eligibility_evidence_visual_qc_records",
                    "eligibility_evidence_visual_qc_state",
                    "eligibility_vlm_profile_revisions",
                    "eligibility_vlm_profile_state",
                    "eligibility_controlled_artifact_records",
                    "eligibility_controlled_artifact_state",
                    "eligibility_vlm_job_bindings",
                    "eligibility_vlm_descriptor_records",
                    "eligibility_vlm_current_state",
                    "eligibility_vlm_audit_events",
                    "eligibility_vlm_circuit_state",
                    "eligibility_vlm_circuit_permits",
                    "eligibility_vlm_circuit_samples",
                    "eligibility_source_processing_unit_records",
                    "eligibility_source_processing_unit_state",
                },
                {
                    name for name in tables if name.startswith("eligibility_")
                },
            )
            self.assertEqual(
                "v5-preserved",
                connection.execute("SELECT value FROM legacy_marker").fetchone()[0],
            )
            self.assertEqual(
                16,
                connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
            )
            self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
            self.assertEqual([], connection.execute("PRAGMA foreign_key_check").fetchall())

    def test_cas_idempotency_restart_and_project_scope(self):
        self.seed_identity()
        first = self.commit()
        replay = self.commit()

        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(first.record_id, replay.record_id)
        self.assertEqual(1, len(self.store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)))

        with self.assertRaises(IdempotencyConflictError):
            self.commit(
                self.review_record(reason="Different payload"),
                fingerprint="different-fingerprint",
            )
        with self.assertRaises(StaleRuntimeStateError):
            self.store.commit_eligibility_review_action(
                self.review_record(record_id="stale-record"),
                expected_state_revision=0,
                expected_rule_revision=RULE_REVISION,
                expected_subject_source_revision=SUBJECT_SOURCE_REVISION,
                idempotency_key="stale-key",
                request_fingerprint="stale-fingerprint",
            )
        rejection_events = [
            event
            for event in self.store.runtime_audit_records(PROJECT_ID)
            if event["event_type"] == "eligibility_stale_write_rejected"
        ]
        self.assertEqual(1, len(rejection_events))
        self.assertEqual(
            {
                "subject_id",
                "criterion_uid",
                "expected_state_revision",
                "expected_rule_revision",
                "expected_subject_source_revision",
                "request_hash",
                "reason_code",
            },
            set(rejection_events[0]["detail"]),
        )
        self.assertNotIn("reason", rejection_events[0]["detail"])

        restarted = SqliteRuntimeStore(self.db_path)
        state = restarted.eligibility_review_state(PROJECT_ID, SUBJECT_ID, CRITERION_UID)
        self.assertEqual(1, state["state_revision"])
        self.assertEqual("met", state["medical_decision"])

        self.seed_identity(restarted, project_id=OTHER_PROJECT_ID)
        other = self.review_record(
            record_id="other-record",
            project_id=OTHER_PROJECT_ID,
            medical_record_id="other-record",
        )
        restarted.commit_eligibility_review_action(
            other,
            expected_state_revision=0,
            expected_rule_revision=RULE_REVISION,
            expected_subject_source_revision=SUBJECT_SOURCE_REVISION,
            idempotency_key="criterion-key-1",
            request_fingerprint="fingerprint-1",
        )
        self.assertEqual(
            1,
            restarted.eligibility_review_state(
                OTHER_PROJECT_ID, SUBJECT_ID, CRITERION_UID
            )["state_revision"],
        )
        self.assertEqual(
            [],
            restarted.eligibility_review_records("proj_unknown", SUBJECT_ID),
        )

    def test_same_idempotency_key_is_allowed_for_another_criterion(self):
        self.seed_identity()
        self.store.replace_eligibility_rule_revision(
            PROJECT_ID,
            "rule-rev-2",
            [
                {
                    "criterion_uid": "criterion-in-02",
                    "criterion_kind": "inclusion",
                    "source_rule_label": "IN-02",
                    "source_locator": {"document": "protocol.docx", "paragraph": 11},
                    "normalized_text_hash": "rule-text-hash-2",
                    "display_order": 2,
                }
            ],
            created_at=NOW,
        )
        record = self.review_record(
            record_id="criterion-2-record",
            criterion_uid="criterion-in-02",
            rule_revision="rule-rev-2",
            medical_record_id="criterion-2-record",
        )
        self.store.commit_eligibility_review_action(
            record,
            expected_state_revision=0,
            expected_rule_revision="rule-rev-2",
            expected_subject_source_revision=SUBJECT_SOURCE_REVISION,
            idempotency_key="criterion-key-1",
            request_fingerprint="fingerprint-1",
        )
        self.assertEqual(1, len(self.store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)))

    def test_reset_after_source_change_uses_new_current_revision_and_clears_decisions(self):
        self.seed_identity()
        self.commit()
        self.store.replace_eligibility_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            "subject-source-rev-2",
            [
                {
                    "source_id": "source-1",
                    "source_revision": "source-rev-2",
                    "content_hash": "source-content-hash-2",
                    "size_bytes": 124,
                    "media_class": "text_document_image",
                }
            ],
            created_at=NOW,
        )
        reset = self.review_record(
            record_id="reset-record-2",
            action="reset_after_source_change",
            action_decision=None,
            medical_decision=None,
            rule_revision=RULE_REVISION,
            subject_source_revision="subject-source-rev-2",
            previous_state_revision=1,
            new_state_revision=2,
            evidence_ids=[],
            medical_record_id=None,
        )

        result = self.store.commit_eligibility_review_action(
            reset,
            expected_state_revision=1,
            expected_rule_revision=RULE_REVISION,
            expected_subject_source_revision="subject-source-rev-2",
            idempotency_key="reset-after-source-change-2",
            request_fingerprint="reset-after-source-change-fingerprint-2",
        )

        self.assertEqual(2, result.state_revision)
        state = self.store.eligibility_review_state(
            PROJECT_ID, SUBJECT_ID, CRITERION_UID
        )
        self.assertIsNone(state["ai_draft_decision"])
        self.assertIsNone(state["medical_decision"])
        self.assertEqual("subject-source-rev-2", state["subject_source_revision"])
        self.assertEqual(
            ["revise_decision", "reset_after_source_change"],
            [
                row["action"]
                for row in self.store.eligibility_review_records(
                    PROJECT_ID, SUBJECT_ID, CRITERION_UID
                )
            ],
        )

    def test_reset_without_revision_drift_is_rejected(self):
        self.seed_identity()
        self.commit()
        reset = self.review_record(
            record_id="invalid-reset-record",
            action="reset_after_source_change",
            action_decision=None,
            medical_decision=None,
            previous_state_revision=1,
            new_state_revision=2,
            evidence_ids=[],
            medical_record_id=None,
        )
        with self.assertRaisesRegex(ValueError, "requires rule or source revision drift"):
            self.store.commit_eligibility_review_action(
                reset,
                expected_state_revision=1,
                expected_rule_revision=RULE_REVISION,
                expected_subject_source_revision=SUBJECT_SOURCE_REVISION,
                idempotency_key="invalid-reset",
                request_fingerprint="invalid-reset-fingerprint",
            )

    def test_old_evidence_is_rejected_after_subject_source_revision_changes(self):
        self.seed_identity()
        self.store.replace_eligibility_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            "subject-source-rev-2",
            [
                {
                    "source_id": "source-1",
                    "source_revision": "source-rev-2",
                    "content_hash": "source-content-hash-2",
                    "size_bytes": 124,
                    "media_class": "text_document_image",
                }
            ],
            created_at=NOW,
        )
        stale_evidence_record = self.review_record(
            record_id="stale-evidence-record",
            subject_source_revision="subject-source-rev-2",
        )
        with self.assertRaisesRegex(
            StaleRuntimeStateError, "evidence is missing or stale"
        ):
            self.store.commit_eligibility_review_action(
                stale_evidence_record,
                expected_state_revision=0,
                expected_rule_revision=RULE_REVISION,
                expected_subject_source_revision="subject-source-rev-2",
                idempotency_key="stale-evidence-key",
                request_fingerprint="stale-evidence-fingerprint",
            )
        self.assertIsNone(
            self.store.eligibility_review_state(
                PROJECT_ID, SUBJECT_ID, CRITERION_UID
            )
        )
        rejection_events = [
            event
            for event in self.store.runtime_audit_records(PROJECT_ID)
            if event["event_type"] == "eligibility_stale_write_rejected"
        ]
        self.assertEqual(1, len(rejection_events))

    def test_concurrent_first_writes_allow_one_commit_and_audit_one_stale_loser(self):
        self.seed_identity()
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        def submit(index):
            record = self.review_record(
                record_id=f"concurrent-record-{index}",
                medical_record_id=f"concurrent-record-{index}",
                reason=f"Concurrent review attempt {index}.",
            )
            barrier.wait()
            try:
                result = self.store.commit_eligibility_review_action(
                    record,
                    expected_state_revision=0,
                    expected_rule_revision=RULE_REVISION,
                    expected_subject_source_revision=SUBJECT_SOURCE_REVISION,
                    idempotency_key=f"concurrent-key-{index}",
                    request_fingerprint=f"concurrent-fingerprint-{index}",
                )
                outcome = ("committed", result.state_revision)
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
        self.assertEqual(
            1,
            self.store.eligibility_review_state(
                PROJECT_ID, SUBJECT_ID, CRITERION_UID
            )["state_revision"],
        )
        self.assertEqual(
            1,
            len(
                [
                    event
                    for event in self.store.runtime_audit_records(PROJECT_ID)
                    if event["event_type"] == "eligibility_stale_write_rejected"
                ]
            ),
        )

    def test_faults_roll_back_record_state_and_audit(self):
        for checkpoint in (
            "after_eligibility_review_record",
            "after_eligibility_review_state",
            "after_eligibility_runtime_audit",
        ):
            with self.subTest(checkpoint=checkpoint):
                db_path = self.root / checkpoint / "runtime.sqlite3"
                seed_store = SqliteRuntimeStore(db_path)
                self.seed_identity(seed_store)

                def fail(current):
                    if current == checkpoint:
                        raise RuntimeError(f"fault:{checkpoint}")

                store = SqliteRuntimeStore(db_path, fault_injector=fail)
                baseline_audit = store.runtime_audit_records(PROJECT_ID)
                with self.assertRaisesRegex(RuntimeError, checkpoint):
                    store.commit_eligibility_review_action(
                        self.review_record(),
                        expected_state_revision=0,
                        expected_rule_revision=RULE_REVISION,
                        expected_subject_source_revision=SUBJECT_SOURCE_REVISION,
                        idempotency_key="rollback-key",
                        request_fingerprint="rollback-fingerprint",
                    )
                self.assertEqual([], store.eligibility_review_records(PROJECT_ID, SUBJECT_ID))
                self.assertIsNone(
                    store.eligibility_review_state(PROJECT_ID, SUBJECT_ID, CRITERION_UID)
                )
                self.assertEqual(
                    baseline_audit, store.runtime_audit_records(PROJECT_ID)
                )


if __name__ == "__main__":
    unittest.main()
