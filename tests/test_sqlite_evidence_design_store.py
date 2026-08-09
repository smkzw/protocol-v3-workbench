from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
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
    EvidencePicosDecisionAction,
    EvidencePicosDecisionRecord,
    EvidencePicosQuestionState,
    EvidencePicosSnapshot,
    EvidencePicosWorkingState,
    EvidencePicosWritingHandoff,
    EvidenceReviewAction,
    EvidenceReviewRecord,
)
from services.api.app.sqlite_runtime_store import (  # noqa: E402
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECT_ID = "proj_my008_pnh_3_01"
PACKAGE_ID = "pnh_competitive_evidence"
EVIDENCE_ID = "pnh_competitive_evidence:trial:v1:example"


def now() -> datetime:
    return datetime.now(timezone.utc)


def audit(audit_id: str, action: str, target_type: str, target_id: str) -> AuditEvent:
    return AuditEvent(
        audit_id=audit_id,
        project_id=PROJECT_ID,
        actor="medical_manager",
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail={},
        created_at=now(),
    )


def state(revision: int, *, status: str = "待医学确认") -> EvidencePicosWorkingState:
    return EvidencePicosWorkingState(
        working_state_id=f"picos_state:{PROJECT_ID}:{PACKAGE_ID}",
        project_id=PROJECT_ID,
        package_id=PACKAGE_ID,
        evidence_package_hash="package-hash-v1",
        revision=revision,
        approval_state=ApprovalState.AI_DRAFT,
        question_states=[
            EvidencePicosQuestionState(
                question_id="picos:population",
                selected_option_id="picos:population:option:1",
                user_rationale="选择目标PNH人群并保留既往补体抑制剂分层。",
                decision_status=status,
                writing_target_section="入排标准/研究人群",
            )
        ],
        created_at=now(),
        updated_at=now(),
    )


class SqliteEvidenceDesignStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "runtime.sqlite3"
        self.store = SqliteRuntimeStore(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_current_schema_contains_evidence_tables_and_immutable_snapshots(self):
        self.assertEqual(16, self.store.health_report()["schema_version"])
        with sqlite3.connect(self.db_path) as connection:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            self.assertTrue(
                {
                    "evidence_review_records",
                    "evidence_picos_working_states",
                    "evidence_picos_decision_records",
                    "evidence_picos_working_state_snapshots",
                    "evidence_picos_writing_handoffs",
                }.issubset(tables)
            )

    def test_evidence_review_is_append_only_revisioned_and_project_scoped(self):
        first = EvidenceReviewRecord(
            record_id="review-1",
            project_id=PROJECT_ID,
            package_id=PACKAGE_ID,
            evidence_id=EVIDENCE_ID,
            action=EvidenceReviewAction.INCLUDE,
            reason="符合PNH目标研究与来源边界。",
            screening_status="已纳入",
            previous_revision=0,
            new_revision=1,
            created_at=now(),
        )
        self.store.commit_evidence_review_action(
            first,
            audit("audit-review-1", "include", "evidence_candidate", EVIDENCE_ID),
            expected_revision=0,
            idempotency_key="review-key-1",
            request_fingerprint="review-fingerprint-1",
        )
        replay = self.store.commit_evidence_review_action(
            first,
            audit("audit-review-1", "include", "evidence_candidate", EVIDENCE_ID),
            expected_revision=0,
            idempotency_key="review-key-1",
            request_fingerprint="review-fingerprint-1",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(1, len(self.store.evidence_review_records(PROJECT_ID, PACKAGE_ID, EVIDENCE_ID)))
        self.assertEqual([], self.store.evidence_review_records("proj_mgk10_crswnp", PACKAGE_ID, EVIDENCE_ID))

        stale = first.model_copy(update={"record_id": "review-stale", "new_revision": 1})
        with self.assertRaises(StaleRuntimeStateError):
            self.store.commit_evidence_review_action(
                stale,
                audit("audit-review-stale", "include", "evidence_candidate", EVIDENCE_ID),
                expected_revision=0,
                idempotency_key="review-key-stale",
                request_fingerprint="review-fingerprint-stale",
            )

    def test_picos_package_state_uses_numeric_cas_and_survives_restart(self):
        previous = state(0)
        updated = state(1)
        record = EvidencePicosDecisionRecord(
            record_id="picos-record-1",
            project_id=PROJECT_ID,
            package_id=PACKAGE_ID,
            working_state_id=updated.working_state_id,
            question_id="picos:population",
            action=EvidencePicosDecisionAction.SELECT_OPTION,
            option_id="picos:population:option:1",
            user_rationale="选择目标PNH人群并保留既往补体抑制剂分层。",
            from_status="待用户确认",
            to_status="待医学确认",
            previous_revision=0,
            new_revision=1,
            created_at=now(),
        )
        self.store.commit_evidence_picos_action(
            previous,
            updated,
            record,
            audit("audit-picos-1", "select_option", "evidence_picos_working_state", updated.working_state_id),
            expected_revision=0,
            idempotency_key="picos-key-1",
            request_fingerprint="picos-fingerprint-1",
        )

        restored = SqliteRuntimeStore(self.db_path)
        self.assertEqual(1, restored.evidence_picos_working_state(PROJECT_ID, PACKAGE_ID).revision)
        self.assertEqual(1, len(restored.evidence_picos_decision_records(PROJECT_ID, PACKAGE_ID)))
        self.assertEqual(1, len(restored.evidence_picos_working_state_snapshots(PROJECT_ID, updated.working_state_id)))

        with self.assertRaises(StaleRuntimeStateError):
            restored.commit_evidence_picos_action(
                previous,
                updated,
                record.model_copy(update={"record_id": "picos-record-stale"}),
                audit("audit-picos-stale", "select_option", "evidence_picos_working_state", updated.working_state_id),
                expected_revision=0,
                idempotency_key="picos-key-stale",
                request_fingerprint="picos-fingerprint-stale",
            )

    def test_snapshot_is_immutable_and_handoff_is_blocked_until_medically_approved(self):
        previous = state(0)
        updated = state(1, status="写作候选")
        record = EvidencePicosDecisionRecord(
            record_id="picos-record-snapshot",
            project_id=PROJECT_ID,
            package_id=PACKAGE_ID,
            working_state_id=updated.working_state_id,
            question_id="picos:population",
            action=EvidencePicosDecisionAction.MARK_WRITING_CANDIDATE,
            from_status="待医学确认",
            to_status="写作候选",
            previous_revision=0,
            new_revision=1,
            created_at=now(),
        )
        self.store.commit_evidence_picos_action(
            previous,
            updated,
            record,
            audit("audit-picos-snapshot-base", "mark_writing_candidate", "evidence_picos_working_state", updated.working_state_id),
            expected_revision=0,
            idempotency_key="picos-snapshot-base",
            request_fingerprint="picos-snapshot-base-fingerprint",
        )

        approval_id = "approval:picos-state:r1"
        snapshot = EvidencePicosSnapshot(
            snapshot_id="picos-snapshot-1",
            project_id=PROJECT_ID,
            package_id=PACKAGE_ID,
            working_state_id=updated.working_state_id,
            revision=1,
            evidence_package_hash=updated.evidence_package_hash,
            approval_id=approval_id,
            question_states=updated.question_states,
            created_at=now(),
        )
        pending_gate = ApprovalGate(
            approval_id=approval_id,
            project_id=PROJECT_ID,
            target_type="evidence_picos_snapshot",
            target_id=snapshot.snapshot_id,
            target_revision=1,
            state=ApprovalState.IN_MEDICAL_REVIEW,
            requested_by="medical_manager",
            created_at=now(),
            updated_at=now(),
        )
        self.store.commit_evidence_picos_snapshot(
            snapshot,
            pending_gate,
            audit("audit-picos-snapshot", "submit_medical_review", "evidence_picos_snapshot", snapshot.snapshot_id),
            expected_revision=1,
            idempotency_key="snapshot-key-1",
            request_fingerprint="snapshot-fingerprint-1",
        )

        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE evidence_picos_working_state_snapshots SET snapshot_type='changed' WHERE snapshot_id=?",
                    (snapshot.snapshot_id,),
                )

        handoff = EvidencePicosWritingHandoff(
            handoff_id="picos-handoff-1",
            project_id=PROJECT_ID,
            package_id=PACKAGE_ID,
            working_state_id=updated.working_state_id,
            snapshot_id=snapshot.snapshot_id,
            approval_id=approval_id,
            approved_revision=1,
            source_refs=["picos-snapshot-1"],
            created_at=now(),
        )
        with self.assertRaises(RuntimeStoreError):
            self.store.commit_evidence_picos_handoff(
                handoff,
                audit("audit-handoff-blocked", "create_handoff", "evidence_picos_handoff", handoff.handoff_id),
                idempotency_key="handoff-blocked",
                request_fingerprint="handoff-blocked-fingerprint",
            )

        approved_gate = pending_gate.model_copy(
            update={
                "state": ApprovalState.MEDICALLY_APPROVED,
                "reviewed_by": "medical_director",
                "approved_by": "medical_director",
                "updated_at": now(),
            }
        )
        approval_audit = audit("audit-approval", "approve", "approval_gate", approval_id)
        decision = ApprovalDecisionRecord(
            decision_id="decision-approval-1",
            approval_id=approval_id,
            project_id=PROJECT_ID,
            action=ApprovalAction.APPROVE,
            actor="medical_director",
            previous_state=ApprovalState.IN_MEDICAL_REVIEW,
            new_state=ApprovalState.MEDICALLY_APPROVED,
            audit_event_id=approval_audit.audit_id,
            created_at=now(),
        )
        self.store.commit_approval_action(
            approved_gate,
            approval_audit,
            decision,
            idempotency_key="approve-picos-1",
            request_fingerprint="approve-picos-fingerprint-1",
        )
        self.store.commit_evidence_picos_handoff(
            handoff,
            audit("audit-handoff-ok", "create_handoff", "evidence_picos_handoff", handoff.handoff_id),
            idempotency_key="handoff-ok",
            request_fingerprint="handoff-ok-fingerprint",
        )
        self.assertEqual([handoff], self.store.evidence_picos_handoffs(PROJECT_ID, PACKAGE_ID))


if __name__ == "__main__":
    unittest.main()
