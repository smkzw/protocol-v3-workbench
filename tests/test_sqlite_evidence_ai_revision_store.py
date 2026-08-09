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
    AuditEvent,
    EvidenceAiRevisionProposal,
    EvidenceAiRevisionThread,
)
from services.api.app.sqlite_runtime_store import (  # noqa: E402
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECT_ID = "proj_my008_pnh_3_01"
PACKAGE_ID = "pnh_competitive_evidence"


def now() -> datetime:
    return datetime.now(timezone.utc)


def thread(revision: int = 1, *, decision: str = "pending") -> EvidenceAiRevisionThread:
    created_at = now()
    return EvidenceAiRevisionThread(
        thread_id="evidence-ai-thread-1",
        project_id=PROJECT_ID,
        package_id=PACKAGE_ID,
        anchor_type="picos_question",
        anchor_id="picos:population",
        base_picos_revision=10,
        evidence_package_hash="package-hash-v1",
        revision=revision,
        status="pending_medical_action" if decision == "pending" else decision,
        user_instruction="请基于已纳入PNH证据进一步收紧目标人群定义。",
        source_evidence_ids=["pnh:trial:1", "pnh:publication:1"],
        proposals=[
            EvidenceAiRevisionProposal(
                proposal_id="evidence-ai-proposal-1",
                ai_run_id="airun-pnh-1",
                proposal_text="建议聚焦既往C5抑制剂治疗后仍存在残余贫血的人群。",
                proposed_option_id="picos:population:option:2",
                rationale="来源证据提示该人群仍存在明确未满足需求。",
                evidence_span_ids=["span-1", "span-2"],
                uncertainty="需医学确认Hb、输血和治疗稳定期阈值。",
                user_decision=decision,
                created_at=created_at,
            )
        ],
        created_at=created_at,
        updated_at=created_at,
    )


def audit(audit_id: str, action: str) -> AuditEvent:
    return AuditEvent(
        audit_id=audit_id,
        project_id=PROJECT_ID,
        actor="medical_manager",
        action=action,
        target_type="evidence_ai_revision_thread",
        target_id="evidence-ai-thread-1",
        detail={},
        created_at=now(),
    )


class SqliteEvidenceAiRevisionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "runtime.sqlite3"
        self.store = SqliteRuntimeStore(self.db_path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_current_schema_and_submission_survive_restart(self):
        self.assertEqual(16, self.store.health_report()["schema_version"])
        original = thread()
        result = self.store.commit_evidence_ai_revision_submission(
            original,
            audit("audit-ai-submit", "submit_ai_revision"),
            idempotency_key="ai-submit-1",
            request_fingerprint="ai-submit-fingerprint-1",
        )
        self.assertFalse(result.replayed)

        replay = self.store.commit_evidence_ai_revision_submission(
            original,
            audit("audit-ai-submit", "submit_ai_revision"),
            idempotency_key="ai-submit-1",
            request_fingerprint="ai-submit-fingerprint-1",
        )
        self.assertTrue(replay.replayed)

        restarted = SqliteRuntimeStore(self.db_path)
        restored = restarted.evidence_ai_revision_thread(PROJECT_ID, original.thread_id)
        self.assertEqual(1, restored.revision)
        self.assertEqual("airun-pnh-1", restored.proposals[0].ai_run_id)
        self.assertEqual(1, len(restarted.evidence_ai_revision_threads(PROJECT_ID, PACKAGE_ID)))
        self.assertEqual([], restarted.evidence_ai_revision_threads("proj_mgk10_crswnp", PACKAGE_ID))

    def test_action_uses_numeric_cas_and_snapshots_are_immutable(self):
        original = thread()
        self.store.commit_evidence_ai_revision_submission(
            original,
            audit("audit-ai-submit", "submit_ai_revision"),
            idempotency_key="ai-submit-1",
            request_fingerprint="ai-submit-fingerprint-1",
        )
        updated = thread(2, decision="accepted")
        self.store.commit_evidence_ai_revision_action(
            original,
            updated,
            audit("audit-ai-accept", "accept_ai_revision"),
            expected_revision=1,
            idempotency_key="ai-accept-1",
            request_fingerprint="ai-accept-fingerprint-1",
        )
        self.assertEqual(
            "accepted",
            self.store.evidence_ai_revision_thread(PROJECT_ID, original.thread_id).status,
        )

        with self.assertRaises(StaleRuntimeStateError):
            self.store.commit_evidence_ai_revision_action(
                original,
                updated,
                audit("audit-ai-stale", "accept_ai_revision"),
                expected_revision=1,
                idempotency_key="ai-stale-1",
                request_fingerprint="ai-stale-fingerprint-1",
            )

        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE evidence_ai_revision_snapshots SET action='changed' WHERE thread_id=?",
                    (original.thread_id,),
                )


if __name__ == "__main__":
    unittest.main()
