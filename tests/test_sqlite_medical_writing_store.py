from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    ApprovalAction,
    ApprovalDecisionRecord,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    RevisionSuggestion,
    RevisionThread,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore, StaleRuntimeStateError


NOW = datetime(2026, 7, 10, 4, 30, tzinfo=timezone.utc)
PROJECT_ID = "proj_rux_03_002"


def make_thread(status: str = "pending_medical_approval", decision: str = "pending") -> RevisionThread:
    resolved_at = NOW if status != "pending_medical_approval" else None
    return RevisionThread(
        thread_id="thread_real_rux_001",
        project_id=PROJECT_ID,
        document_id="rux_03_002_protocol_writing_doc_protocol",
        section_id="rux_03_002_protocol_writing_sec_001",
        anchor_type="paragraph",
        anchor_path="docx:paragraph:12",
        selected_text="原始方案正文。",
        user_instruction="请调整为更清晰的医学写作表述。",
        intent="medical_writing_revision",
        ai_run_id="ai_run_real_rux_001",
        suggestions=[
            RevisionSuggestion(
                suggestion_id="suggestion_real_rux_001",
                proposal_text="修订后的方案正文。",
                diff_patch="- 原始方案正文。\n+ 修订后的方案正文。",
                rationale="保留原意并提高可读性。",
                evidence_span_ids=["span_real_rux_001"],
                uncertainty="需医学经理确认。",
                user_decision=decision,
            )
        ],
        status=status,
        created_at=NOW,
        resolved_at=resolved_at,
    )


def make_audit(audit_id: str, action: str) -> AuditEvent:
    return AuditEvent(
        audit_id=audit_id,
        project_id=PROJECT_ID,
        actor="medical_manager_test",
        action=action,
        target_type="revision_thread",
        target_id="thread_real_rux_001",
        detail={"source": "test"},
        created_at=NOW,
    )


def make_gate() -> ApprovalGate:
    return ApprovalGate(
        approval_id="approval_revision_thread_real_rux_001",
        project_id=PROJECT_ID,
        target_type="medical_writing_revision_thread",
        target_id="thread_real_rux_001",
        state=ApprovalState.IN_MEDICAL_REVIEW,
        requested_by="medical_manager_test",
        review_comments="待医学批准。",
        created_at=NOW,
        updated_at=NOW,
    )


class SqliteMedicalWritingStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "runtime.sqlite3"
        self.store = SqliteRuntimeStore(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_legacy_thread_json_without_candidate_provenance_uses_safe_defaults(self):
        payload = make_thread().model_dump(mode="json")
        payload.pop("evidence_source_types")
        payload["suggestions"][0].pop("evidence_source_types")
        payload["suggestions"][0].pop("fact_adoption_status")

        restored = RevisionThread.model_validate(payload)

        self.assertEqual([], restored.evidence_source_types)
        self.assertEqual([], restored.suggestions[0].evidence_source_types)
        self.assertEqual(
            "candidate_only",
            restored.suggestions[0].fact_adoption_status,
        )

        payload["suggestions"][0]["user_decision"] = "accepted"
        restored_accepted = RevisionThread.model_validate(payload)
        self.assertEqual(
            "adopted_as_project_fact",
            restored_accepted.suggestions[0].fact_adoption_status,
        )

    def test_revision_thread_selected_hash_backfills_legacy_json_and_rejects_tamper(self):
        original = make_thread()
        payload = original.model_dump(mode="json")
        payload.pop("selected_hash")

        restored = RevisionThread.model_validate(payload)

        self.assertEqual(
            RevisionThread.selected_text_hash(original.selected_text),
            restored.selected_hash,
        )
        payload["selected_hash"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "selected_hash does not match"):
            RevisionThread.model_validate(payload)
        payload["selected_hash"] = ""
        with self.assertRaisesRegex(ValueError, "selected_hash does not match"):
            RevisionThread.model_validate(payload)

        assigned_tamper = original.model_copy(deep=True)
        assigned_tamper.selected_hash = "0" * 64
        with self.assertRaisesRegex(ValueError, "selected_hash does not match"):
            self.store.commit_medical_writing_revision_submission(
                assigned_tamper,
                make_audit("audit_selected_hash_tamper", "medical_writing_revision_submitted"),
            )

    def test_legacy_thread_json_can_accept_after_cold_restart_without_false_stale_write(self):
        initial = make_thread()
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit(
                "audit_submit_legacy_provenance",
                "medical_writing_revision_submitted",
            ),
        )
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_revision_threads
                WHERE project_id = ? AND thread_id = ?
                """,
                (PROJECT_ID, initial.thread_id),
            ).fetchone()
            payload = json.loads(row[0])
            payload.pop("selected_hash", None)
            payload.pop("evidence_source_types")
            payload["suggestions"][0].pop("evidence_source_types")
            payload["suggestions"][0].pop("fact_adoption_status")
            connection.execute(
                """
                UPDATE medical_writing_revision_threads
                SET payload_json = ?
                WHERE project_id = ? AND thread_id = ?
                """,
                (json.dumps(payload), PROJECT_ID, initial.thread_id),
            )
            connection.commit()

        restarted = SqliteRuntimeStore(self.db_path)
        previous = restarted.medical_writing_revision_thread(
            PROJECT_ID,
            initial.thread_id,
        )
        self.assertEqual(
            RevisionThread.selected_text_hash(previous.selected_text),
            previous.selected_hash,
        )
        accepted = previous.model_copy(deep=True)
        accepted.status = "medically_approved"
        accepted.resolved_at = NOW
        accepted.suggestions[0].user_decision = "accepted"
        accepted.suggestions[0].fact_adoption_status = "adopted_as_project_fact"

        restarted.commit_medical_writing_revision_action(
            previous,
            accepted,
            make_audit(
                "audit_accept_legacy_provenance",
                "medical_writing_revision_accept",
            ),
        )

        stored = restarted.medical_writing_revision_thread(
            PROJECT_ID,
            initial.thread_id,
        )
        self.assertEqual("medically_approved", stored.status)
        self.assertEqual(
            "adopted_as_project_fact",
            stored.suggestions[0].fact_adoption_status,
        )

    def test_submission_and_accept_action_survive_cold_restart_with_valid_audit_chain(self):
        initial = make_thread()
        initial.evidence_source_types = ["approved_competitor_protocol_evidence"]
        initial.suggestions[0].evidence_source_types = [
            "approved_competitor_protocol_evidence"
        ]
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit("audit_submit_001", "medical_writing_revision_submitted"),
        )

        accepted = initial.model_copy(deep=True)
        accepted.status = "accepted_pending_medical_approval"
        accepted.resolved_at = NOW
        accepted.suggestions[0].user_decision = "accepted"
        accepted.suggestions[0].fact_adoption_status = "adopted_as_project_fact"
        self.store.commit_medical_writing_revision_action(
            initial,
            accepted,
            make_audit("audit_accept_001", "medical_writing_revision_accept"),
            make_gate(),
        )

        restarted = SqliteRuntimeStore(self.db_path)
        stored = restarted.medical_writing_revision_thread(PROJECT_ID, initial.thread_id)
        self.assertEqual("accepted_pending_medical_approval", stored.status)
        self.assertEqual("accepted", stored.suggestions[0].user_decision)
        self.assertEqual(
            ["approved_competitor_protocol_evidence"],
            stored.evidence_source_types,
        )
        self.assertEqual(
            "adopted_as_project_fact",
            stored.suggestions[0].fact_adoption_status,
        )
        self.assertEqual(1, len(restarted.gates(PROJECT_ID)))
        self.assertEqual(2, len(restarted.workflow_audit_events(PROJECT_ID, "medical_writing_revision")))
        self.assertEqual([], restarted.verify_audit_chain(PROJECT_ID))
        self.assertEqual(16, restarted.health_report()["schema_version"])

    def test_legacy_selected_hash_row_can_complete_final_approval_cas(self):
        initial = make_thread()
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit("audit_submit_final_legacy", "medical_writing_revision_submitted"),
        )
        accepted = initial.model_copy(deep=True)
        accepted.status = "accepted_pending_medical_approval"
        accepted.resolved_at = NOW
        accepted.suggestions[0].user_decision = "accepted"
        accepted.suggestions[0].fact_adoption_status = "adopted_as_project_fact"
        self.store.commit_medical_writing_revision_action(
            initial,
            accepted,
            make_audit("audit_accept_final_legacy", "medical_writing_revision_accept"),
            make_gate(),
        )
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_revision_threads
                WHERE project_id = ? AND thread_id = ?
                """,
                (PROJECT_ID, initial.thread_id),
            ).fetchone()
            payload = json.loads(row[0])
            payload.pop("selected_hash", None)
            connection.execute(
                """
                UPDATE medical_writing_revision_threads
                SET payload_json = ?
                WHERE project_id = ? AND thread_id = ?
                """,
                (json.dumps(payload), PROJECT_ID, initial.thread_id),
            )
            connection.commit()

        restarted = SqliteRuntimeStore(self.db_path)
        previous = restarted.medical_writing_revision_thread(
            PROJECT_ID, initial.thread_id
        )
        updated = previous.model_copy(
            update={"status": "medically_approved", "resolved_at": NOW},
            deep=True,
        )
        approval = make_gate().model_copy(
            update={
                "state": ApprovalState.MEDICALLY_APPROVED,
                "review_comments": "完成 legacy selected_hash 兼容批准。",
                "reviewed_by": "medical_manager_test",
                "approved_by": "medical_manager_test",
                "updated_at": NOW,
            }
        )
        audit = AuditEvent(
            audit_id="audit_final_legacy_approval",
            project_id=PROJECT_ID,
            actor="medical_manager_test",
            action="approval.approve",
            target_type="approval_gate",
            target_id=approval.approval_id,
            created_at=NOW,
        )
        decision = ApprovalDecisionRecord(
            decision_id="decision_final_legacy_approval",
            approval_id=approval.approval_id,
            project_id=PROJECT_ID,
            action=ApprovalAction.APPROVE,
            actor="medical_manager_test",
            previous_state=ApprovalState.IN_MEDICAL_REVIEW,
            new_state=ApprovalState.MEDICALLY_APPROVED,
            comment="完成 legacy selected_hash 兼容批准。",
            blocked=False,
            audit_event_id=audit.audit_id,
            created_at=NOW,
        )
        restarted.commit_medical_writing_approval_action(
            approval,
            audit,
            decision,
            previous_thread=previous,
            updated_thread=updated,
            target_snapshot_id="snapshot_final_legacy_approval",
            idempotency_key="final-legacy-approval",
            request_fingerprint="final-legacy-approval",
        )
        stored = restarted.medical_writing_revision_thread(
            PROJECT_ID, initial.thread_id
        )
        self.assertEqual("medically_approved", stored.status)
        self.assertEqual(
            RevisionThread.selected_text_hash(stored.selected_text),
            stored.selected_hash,
        )
        self.assertEqual([], restarted.verify_audit_chain(PROJECT_ID))
    def test_action_persistence_revalidates_in_memory_candidate_adoption_state(self):
        initial = make_thread()
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit(
                "audit_submit_invalid_adoption",
                "medical_writing_revision_submitted",
            ),
        )
        invalid = initial.model_copy(deep=True)
        invalid.suggestions[0].fact_adoption_status = "adopted_as_project_fact"

        with self.assertRaisesRegex(
            ValueError,
            "project-fact adoption requires explicit medical-author acceptance",
        ):
            self.store.commit_medical_writing_revision_action(
                initial,
                invalid,
                make_audit(
                    "audit_accept_invalid_adoption",
                    "medical_writing_revision_accept",
                ),
            )

        stored = self.store.medical_writing_revision_thread(
            PROJECT_ID,
            initial.thread_id,
        )
        self.assertEqual("pending", stored.suggestions[0].user_decision)
        self.assertEqual(
            "candidate_only",
            stored.suggestions[0].fact_adoption_status,
        )

    def test_submission_is_atomic_when_fault_occurs_after_thread_insert(self):
        def fail(checkpoint: str):
            if checkpoint == "after_revision_thread":
                raise RuntimeError("fault injected")

        store = SqliteRuntimeStore(self.db_path, fault_injector=fail)
        with self.assertRaisesRegex(RuntimeError, "fault injected"):
            store.commit_medical_writing_revision_submission(
                make_thread(),
                make_audit("audit_submit_fault", "medical_writing_revision_submitted"),
            )

        restarted = SqliteRuntimeStore(self.db_path)
        self.assertEqual([], restarted.medical_writing_revision_threads(PROJECT_ID))
        self.assertEqual([], restarted.workflow_audit_events(PROJECT_ID))
        self.assertEqual([], restarted.runtime_audit_records(PROJECT_ID))

    def test_stale_action_is_rejected_without_overwriting_current_thread(self):
        initial = make_thread()
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit("audit_submit_stale", "medical_writing_revision_submitted"),
        )
        rejected = initial.model_copy(deep=True)
        rejected.status = "rejected"
        rejected.resolved_at = NOW
        rejected.suggestions[0].user_decision = "rejected"
        self.store.commit_medical_writing_revision_action(
            initial,
            rejected,
            make_audit("audit_reject_stale", "medical_writing_revision_reject"),
        )

        accepted = initial.model_copy(deep=True)
        accepted.status = "accepted_pending_medical_approval"
        accepted.suggestions[0].user_decision = "accepted"
        with self.assertRaises(StaleRuntimeStateError):
            self.store.commit_medical_writing_revision_action(
                initial,
                accepted,
                make_audit("audit_accept_stale", "medical_writing_revision_accept"),
                make_gate(),
            )

        current = self.store.medical_writing_revision_thread(PROJECT_ID, initial.thread_id)
        self.assertEqual("rejected", current.status)
        self.assertEqual([], self.store.gates(PROJECT_ID))
        event_types = [event["event_type"] for event in self.store.runtime_audit_records(PROJECT_ID)]
        self.assertIn("stale_write_rejected", event_types)

    def test_two_turn_rewrite_action_is_atomic_when_fault_occurs_after_thread_update(self):
        initial = make_thread()
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit("audit_submit_rewrite_fault", "medical_writing_revision_submitted"),
        )
        rewritten = initial.model_copy(deep=True)
        rewritten.suggestions[0].user_decision = "rewrite_requested"
        rewritten.suggestions.append(
            RevisionSuggestion(
                suggestion_id="suggestion_real_rux_002",
                proposal_text="第二轮修订后的方案正文。",
                diff_patch="- 原始方案正文。\n+ 第二轮修订后的方案正文。",
                rationale="根据医学反馈进一步调整。",
                evidence_span_ids=["span_real_rux_002"],
                uncertainty="需医学经理确认。",
                turn_number=2,
                parent_suggestion_id=initial.suggestions[0].suggestion_id,
                user_instruction="请进一步调整。",
                user_comment="保留限定条件。",
                ai_run_id="ai_run_real_rux_002",
                created_at=NOW,
            )
        )
        rewritten.user_instruction = "请进一步调整。"
        rewritten.ai_run_id = "ai_run_real_rux_002"

        def fail(checkpoint: str):
            if checkpoint == "after_revision_thread":
                raise RuntimeError("fault injected after rewrite update")

        fault_store = SqliteRuntimeStore(self.db_path, fault_injector=fail)
        with self.assertRaisesRegex(RuntimeError, "fault injected after rewrite update"):
            fault_store.commit_medical_writing_revision_action(
                initial,
                rewritten,
                make_audit("audit_rewrite_fault", "medical_writing_revision_request_rewrite"),
            )

        restarted = SqliteRuntimeStore(self.db_path)
        stored = restarted.medical_writing_revision_thread(PROJECT_ID, initial.thread_id)
        self.assertEqual(1, len(stored.suggestions))
        self.assertEqual("pending", stored.suggestions[0].user_decision)
        self.assertEqual(
            ["medical_writing_revision_submitted"],
            [event.action for event in restarted.workflow_audit_events(PROJECT_ID, "medical_writing_revision")],
        )


if __name__ == "__main__":
    unittest.main()
