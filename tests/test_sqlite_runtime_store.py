from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import (  # noqa: E402
    ApprovalAction,
    ApprovalDecisionRecord,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    RuxRiskDispositionAction,
    RuxRiskDispositionRecord,
)
from services.api.app.sqlite_runtime_store import (  # noqa: E402
    IdempotencyConflictError,
    RuntimeStoreIntegrityError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECT_ID = "proj_rux_03_002"
OTHER_PROJECT_ID = "proj_other_study"
NOW = datetime(2026, 7, 10, 10, 30, tzinfo=timezone.utc)


class SqliteRuntimeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "runtime" / "workbench_runtime.sqlite3"

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, fault_injector=None, **kwargs):
        return SqliteRuntimeStore(self.db_path, fault_injector=fault_injector, **kwargs)

    def gate(self, project_id=PROJECT_ID, state=ApprovalState.IN_MEDICAL_REVIEW):
        return ApprovalGate(
            approval_id="approval_rux_disposition_risk_001_source001",
            project_id=project_id,
            target_type="medical_monitoring_risk_disposition",
            target_id="risk_001",
            state=state,
            requested_by="medical_manager",
            review_comments="仅批准内部Query草稿/处置建议，不代表对外Query已执行、风险关闭或归档。",
            created_at=NOW,
            updated_at=NOW,
        )

    def disposition(
        self,
        action=RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL,
        previous_state="query_draft",
        new_state="submitted_for_approval",
        project_id=PROJECT_ID,
        record_id="rux_disposition_001",
        comment="提交医学经理审批后再发中心Query。",
    ):
        return RuxRiskDispositionRecord(
            record_id=record_id,
            project_id=project_id,
            item_id="rux-risk:risk_001",
            risk_id="risk_001",
            subject_id="S01017",
            rule_id="RUX-LAB-ALT-AST",
            action=action,
            previous_state=previous_state,
            new_state=new_state,
            actor="medical_manager",
            comment=comment,
            query_draft_text="请中心确认ALT/AST升高是否已记录AE。" if action == RuxRiskDispositionAction.QUERY_DRAFT else "",
            approval_ref=self.gate(project_id).approval_id if action == RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL else "",
            source_version="source-v1",
            source_refs_snapshot=[],
            created_at=NOW,
        )

    def audit(self, project_id=PROJECT_ID, audit_id="audit_runtime_001", action="approval.approve"):
        return AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor="medical_manager",
            action=action,
            target_type="approval_gate",
            target_id=self.gate(project_id).approval_id,
            detail={"previous_state": "in_medical_review", "new_state": "medically_approved"},
            created_at=NOW,
        )

    def decision(self, project_id=PROJECT_ID, decision_id="decision_runtime_001", blocked=False):
        return ApprovalDecisionRecord(
            decision_id=decision_id,
            approval_id=self.gate(project_id).approval_id,
            project_id=project_id,
            action=ApprovalAction.APPROVE,
            actor="medical_manager",
            previous_state=ApprovalState.IN_MEDICAL_REVIEW,
            new_state=ApprovalState.IN_MEDICAL_REVIEW if blocked else ApprovalState.MEDICALLY_APPROVED,
            comment="存在阻断项" if blocked else "仅批准内部处置建议。",
            blocked=blocked,
            audit_event_id=self.audit(project_id).audit_id,
            created_at=NOW,
        )

    def seed_query_draft(self, store, project_id=PROJECT_ID, key_prefix="seed"):
        reviewed = self.disposition(
            action=RuxRiskDispositionAction.REVIEWED,
            previous_state="pending_review",
            new_state="reviewed",
            project_id=project_id,
            record_id=f"{key_prefix}_reviewed",
        )
        query_draft = self.disposition(
            action=RuxRiskDispositionAction.QUERY_DRAFT,
            previous_state="reviewed",
            new_state="query_draft",
            project_id=project_id,
            record_id=f"{key_prefix}_query_draft",
        )
        store.commit_rux_disposition(reviewed, idempotency_key=f"{key_prefix}-reviewed")
        store.commit_rux_disposition(query_draft, idempotency_key=f"{key_prefix}-query")

    def test_rux_gate_and_disposition_commit_atomically(self):
        store = self.store()
        self.seed_query_draft(store)

        result = store.commit_rux_disposition(
            self.disposition(),
            approval=self.gate(),
            idempotency_key="submit-risk-001",
        )

        self.assertFalse(result.replayed)
        self.assertEqual([self.gate()], store.gates(PROJECT_ID))
        self.assertEqual(self.disposition(), store.records(PROJECT_ID)[-1])
        self.assertEqual(3, len(store.records(PROJECT_ID)))
        self.assertEqual([], store.verify_audit_chain(PROJECT_ID))

    def test_rux_faults_roll_back_gate_and_disposition(self):
        for checkpoint in ("after_gate", "after_disposition"):
            with self.subTest(checkpoint=checkpoint):
                db_path = self.root / checkpoint / "runtime.sqlite3"

                def fail(current):
                    if current == checkpoint:
                        raise RuntimeError(f"fault:{checkpoint}")

                seed_store = SqliteRuntimeStore(db_path)
                self.seed_query_draft(seed_store, key_prefix=f"seed-{checkpoint}")
                store = SqliteRuntimeStore(db_path, fault_injector=fail)
                with self.assertRaisesRegex(RuntimeError, checkpoint):
                    store.commit_rux_disposition(
                        self.disposition(),
                        approval=self.gate(),
                        idempotency_key=f"fault-{checkpoint}",
                    )
                self.assertEqual([], store.gates(PROJECT_ID))
                self.assertEqual(2, len(store.records(PROJECT_ID)))
                self.assertEqual("query_draft", store.records(PROJECT_ID)[-1].new_state)

    def test_approval_gate_audit_and_decision_commit_atomically(self):
        store = self.store()
        approved_gate = self.gate(state=ApprovalState.MEDICALLY_APPROVED).model_copy(
            update={"reviewed_by": "medical_manager", "approved_by": "medical_manager"}
        )

        result = store.commit_approval_action(
            approved_gate,
            self.audit(),
            self.decision(),
            idempotency_key="approve-risk-001",
        )

        self.assertFalse(result.replayed)
        self.assertEqual([approved_gate], store.gates(PROJECT_ID))
        self.assertEqual([self.audit()], store.audit_events(PROJECT_ID))
        self.assertEqual([self.decision()], store.decisions(PROJECT_ID))

    def test_approval_faults_roll_back_gate_audit_and_decision(self):
        for checkpoint in ("after_gate", "after_audit", "after_decision"):
            with self.subTest(checkpoint=checkpoint):
                db_path = self.root / checkpoint / "approval.sqlite3"

                def fail(current):
                    if current == checkpoint:
                        raise RuntimeError(f"fault:{checkpoint}")

                store = SqliteRuntimeStore(db_path, fault_injector=fail)
                with self.assertRaisesRegex(RuntimeError, checkpoint):
                    store.commit_approval_action(
                        self.gate(state=ApprovalState.MEDICALLY_APPROVED),
                        self.audit(),
                        self.decision(),
                        idempotency_key=f"fault-{checkpoint}",
                    )
                self.assertEqual([], store.gates(PROJECT_ID))
                self.assertEqual([], store.audit_events(PROJECT_ID))
                self.assertEqual([], store.decisions(PROJECT_ID))

    def test_blocked_approval_persists_audit_and_decision_without_gate_update(self):
        store = self.store()
        blocked_audit = self.audit(action="approval.approve.blocked")
        blocked_decision = self.decision(blocked=True)

        store.commit_approval_action(
            None,
            blocked_audit,
            blocked_decision,
            idempotency_key="blocked-risk-001",
        )

        self.assertEqual([], store.gates(PROJECT_ID))
        self.assertEqual([blocked_audit], store.audit_events(PROJECT_ID))
        self.assertEqual([blocked_decision], store.decisions(PROJECT_ID))

    def test_same_idempotency_key_and_payload_replays_without_duplicates(self):
        store = self.store()
        self.seed_query_draft(store)

        first = store.commit_rux_disposition(
            self.disposition(), approval=self.gate(), idempotency_key="same-key"
        )
        replay = store.commit_rux_disposition(
            self.disposition(), approval=self.gate(), idempotency_key="same-key"
        )

        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(1, len(store.gates(PROJECT_ID)))
        self.assertEqual(3, len(store.records(PROJECT_ID)))

    def test_same_idempotency_key_with_different_payload_conflicts(self):
        store = self.store()
        self.seed_query_draft(store)
        store.commit_rux_disposition(
            self.disposition(), approval=self.gate(), idempotency_key="same-key"
        )

        with self.assertRaises(IdempotencyConflictError):
            store.commit_rux_disposition(
                self.disposition(comment="修改后的不同请求"),
                approval=self.gate(),
                idempotency_key="same-key",
            )

        self.assertEqual(3, len(store.records(PROJECT_ID)))

    def test_stale_disposition_is_rejected_and_audited_without_state_change(self):
        store = self.store()
        reviewed = self.disposition(
            action=RuxRiskDispositionAction.REVIEWED,
            previous_state="pending_review",
            new_state="reviewed",
            record_id="rux_reviewed_001",
        )
        stale = self.disposition(
            action=RuxRiskDispositionAction.QUERY_DRAFT,
            previous_state="pending_review",
            new_state="query_draft",
            record_id="rux_stale_001",
        )
        store.commit_rux_disposition(reviewed, idempotency_key="reviewed-key")

        with self.assertRaises(StaleRuntimeStateError):
            store.commit_rux_disposition(stale, idempotency_key="stale-key")

        self.assertEqual([reviewed], store.records(PROJECT_ID))
        rejection_events = [
            event for event in store.runtime_audit_records(PROJECT_ID)
            if event["event_type"] == "stale_write_rejected"
        ]
        self.assertEqual(1, len(rejection_events))
        self.assertEqual("reviewed", rejection_events[0]["detail"]["actual_state"])

    def test_two_connections_cannot_both_commit_from_the_same_disposition_state(self):
        first_store = self.store()
        second_store = self.store()
        barrier = threading.Barrier(2)
        first_record = self.disposition(
            action=RuxRiskDispositionAction.REVIEWED,
            previous_state="pending_review",
            new_state="reviewed",
            record_id="concurrent_review_001",
            comment="并发医学复核请求一。",
        )
        second_record = first_record.model_copy(
            update={
                "record_id": "concurrent_review_002",
                "comment": "并发医学复核请求二。",
            }
        )

        def commit(store, record, key):
            barrier.wait(timeout=5)
            try:
                store.commit_rux_disposition(record, idempotency_key=key)
                return "committed"
            except StaleRuntimeStateError:
                return "stale"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = [
                future.result(timeout=10)
                for future in (
                    pool.submit(commit, first_store, first_record, "concurrent-1"),
                    pool.submit(commit, second_store, second_record, "concurrent-2"),
                )
            ]

        self.assertEqual(["committed", "stale"], sorted(outcomes))
        committed = self.store().records(PROJECT_ID)
        self.assertEqual(1, len(committed))
        self.assertEqual("reviewed", committed[0].new_state)
        rejection_events = [
            event
            for event in self.store().runtime_audit_records(PROJECT_ID)
            if event["event_type"] == "stale_write_rejected"
        ]
        self.assertEqual(1, len(rejection_events))

    def test_legacy_import_is_idempotent_and_reports_malformed_lines(self):
        gate_path = self.root / "legacy" / "approval_gates.jsonl"
        disposition_path = self.root / "legacy" / "rux_dispositions.jsonl"
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(
            json.dumps(self.gate().model_dump(mode="json"), ensure_ascii=False) + "\n{bad-json\n",
            encoding="utf-8",
        )
        disposition_path.write_text(
            json.dumps(self.disposition().model_dump(mode="json"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        first = self.store(
            legacy_gate_path=gate_path,
            legacy_disposition_path=disposition_path,
        )
        second = self.store(
            legacy_gate_path=gate_path,
            legacy_disposition_path=disposition_path,
        )

        self.assertEqual([self.gate()], second.gates(PROJECT_ID))
        self.assertEqual([self.disposition()], second.records(PROJECT_ID))
        self.assertEqual(1, first.legacy_import_report()["malformed_lines"])
        self.assertEqual(1, second.legacy_import_report()["malformed_lines"])

    def test_restart_recovers_committed_records(self):
        first = self.store()
        self.seed_query_draft(first)
        first.commit_rux_disposition(
            self.disposition(), approval=self.gate(), idempotency_key="restart-submit"
        )
        first.commit_approval_action(
            self.gate(state=ApprovalState.MEDICALLY_APPROVED),
            self.audit(),
            self.decision(),
            idempotency_key="restart-approve",
        )

        restarted = self.store()

        self.assertEqual(3, len(restarted.records(PROJECT_ID)))
        self.assertEqual(1, len(restarted.gates(PROJECT_ID)))
        self.assertEqual(1, len(restarted.audit_events(PROJECT_ID)))
        self.assertEqual(1, len(restarted.decisions(PROJECT_ID)))

    def test_audit_hash_chain_detects_tampering(self):
        store = self.store()
        self.seed_query_draft(store)
        store.commit_rux_disposition(
            self.disposition(), approval=self.gate(), idempotency_key="tamper-submit"
        )
        store.commit_approval_action(
            self.gate(state=ApprovalState.MEDICALLY_APPROVED),
            self.audit(),
            self.decision(),
            idempotency_key="tamper-approve",
        )
        self.assertEqual([], store.verify_audit_chain(PROJECT_ID))

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE runtime_audit_chain SET detail_json = ? WHERE project_id = ? AND sequence_no = 1",
                ('{"tampered":true}', PROJECT_ID),
            )
            connection.commit()

        self.assertTrue(store.verify_audit_chain(PROJECT_ID))

    def test_audit_hash_chain_detects_linked_business_record_tampering(self):
        store = self.store()
        self.seed_query_draft(store)
        store.commit_rux_disposition(
            self.disposition(), approval=self.gate(), idempotency_key="linked-submit"
        )
        store.commit_approval_action(
            self.gate(state=ApprovalState.MEDICALLY_APPROVED),
            self.audit(),
            self.decision(),
            idempotency_key="linked-approve",
        )
        self.assertEqual([], store.verify_audit_chain(PROJECT_ID))

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE approval_audit_events SET payload_json = ? WHERE project_id = ?",
                ('{"tampered":true}', PROJECT_ID),
            )
            connection.commit()

        violations = store.verify_audit_chain(PROJECT_ID)
        self.assertTrue(any("approval audit payload" in item for item in violations))

    def test_same_ids_are_isolated_by_project(self):
        store = self.store()
        self.seed_query_draft(store, project_id=PROJECT_ID, key_prefix="project-a")
        self.seed_query_draft(store, project_id=OTHER_PROJECT_ID, key_prefix="project-b")
        store.commit_rux_disposition(
            self.disposition(), approval=self.gate(), idempotency_key="same-key"
        )
        store.commit_rux_disposition(
            self.disposition(project_id=OTHER_PROJECT_ID),
            approval=self.gate(project_id=OTHER_PROJECT_ID),
            idempotency_key="same-key",
        )

        self.assertEqual(PROJECT_ID, store.records(PROJECT_ID)[-1].project_id)
        self.assertEqual(OTHER_PROJECT_ID, store.records(OTHER_PROJECT_ID)[-1].project_id)
        self.assertEqual(PROJECT_ID, store.gates(PROJECT_ID)[0].project_id)
        self.assertEqual(OTHER_PROJECT_ID, store.gates(OTHER_PROJECT_ID)[0].project_id)

    def test_existing_preversion_database_is_backed_up_before_migration(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("CREATE TABLE legacy_marker(value TEXT NOT NULL)")
            connection.execute("INSERT INTO legacy_marker(value) VALUES ('before-v1')")
            connection.commit()

        store = self.store()

        backups = list(self.db_path.parent.glob("workbench_runtime.sqlite3.v0.*.bak"))
        self.assertEqual(1, len(backups))
        with sqlite3.connect(backups[0]) as backup:
            marker = backup.execute("SELECT value FROM legacy_marker").fetchone()[0]
        self.assertEqual("before-v1", marker)
        self.assertEqual(16, store.health_report()["schema_version"])

    def test_health_report_fails_when_any_project_audit_chain_is_tampered(self):
        store = self.store()
        self.seed_query_draft(store)
        self.seed_query_draft(store, project_id=OTHER_PROJECT_ID, key_prefix="other")
        self.assertEqual("ok", store.health_report()["status"])

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE runtime_audit_chain SET detail_json = ? WHERE project_id = ? AND sequence_no = 1",
                ('{"tampered":true}', OTHER_PROJECT_ID),
            )
            connection.commit()

        health = store.health_report()
        self.assertEqual("error", health["status"])
        self.assertEqual(2, health["audit_chain_projects"])
        self.assertGreater(health["audit_chain_violation_count"], 0)

    def test_corrupted_database_is_rejected_as_runtime_integrity_error(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_bytes(b"not-a-sqlite-database")

        with self.assertRaises(RuntimeStoreIntegrityError):
            self.store()


if __name__ == "__main__":
    unittest.main()
