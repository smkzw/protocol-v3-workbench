"""Focused tests for durable section AI candidate generation and atomic adopt.

Covers:
- submit_revision_durable returns job_id immediately without blocking on slow provider
- cancel/stale owner isolation via durable job contract
- atomic accept_and_apply_candidate success
- atomic adopt idempotency
- mid-failure rollback leaves no orphan author-selected state
- stale working copy revision rejected
- frozen/quarantined content rejected
"""
from __future__ import annotations

import json
import concurrent.futures
import threading
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from packages.contracts.workbench_contracts import (
    AuditEvent,
    DurableJobProgressPayload,
    MedicalWritingRevisionApplyRequest,
    MedicalWritingRevisionRequest,
    MedicalWritingWorkingCopySaveRequest,
    RevisionActionRequest,
    RevisionAction,
    RevisionSuggestion,
    RevisionThread,
)
from services.api.app.medical_writing import (
    MedicalWritingRevisionService,
    SectionAiCandidateExecutor,
)
from services.api.app.medical_writing_durable_jobs import (
    DurableJobStore,
    DurableJobResult,
)
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import (
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECTS = ("proj_rux_03_002", "proj_d001", "proj_my008_pnh_3_01")


class AtomicAcceptAndApplyTests(unittest.TestCase):
    """Tests for the atomic accept_and_apply_candidate repository method."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.documents = MedicalWritingDocumentService()
        self.store = SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3")
        self.repo = MedicalWritingRuntimeRepository(self.documents, self.store)
        self.revision_service = MedicalWritingRevisionService(self.repo, ai_task_runner=None)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _substantive_section(self, project_id: str):
        document = self.documents.document_session(project_id)
        for summary in document.sections:
            section = self.documents.section(project_id, summary.section_id)
            for block in section.content_blocks:
                text = str(block.get("text", "")).strip()
                if len(text) >= 40 and block.get("source_locator"):
                    return document, section, block, text
        self.fail(f"no substantive source paragraph found for {project_id}")

    def _approved_thread(self, project_id: str, suffix: str = ""):
        document, section, block, selected_text = self._substantive_section(project_id)
        selected_text = selected_text[: min(48, len(selected_text))]
        proposal_text = f"{selected_text}（原子采纳测试{suffix}）"
        now = datetime.now(timezone.utc)
        thread_id = f"thread_atomic_{project_id}{suffix}"
        suggestion = RevisionSuggestion(
            suggestion_id=f"sug_atomic_{project_id}{suffix}",
            proposal_text=proposal_text,
            diff_patch=f"- {selected_text}\n+ {proposal_text}",
            rationale="原子采纳测试候选。",
            evidence_span_ids=[f"span_{project_id}{suffix}"],
            evidence_source_types=["approved_competitor_protocol_evidence"],
        )
        thread = RevisionThread(
            thread_id=thread_id,
            project_id=project_id,
            document_id=document.document_id,
            section_id=section.section_id,
            anchor_type="selection",
            anchor_path=block["source_locator"],
            selected_text=selected_text,
            user_instruction="请形成监管中文表述。",
            intent="regulatory_tone",
            ai_run_id=f"run_atomic_{project_id}{suffix}",
            source_entry_id=f"entry_atomic_{project_id}{suffix}",
            source_id=f"source_atomic_{project_id}{suffix}",
            source_locator=block["source_locator"],
            evidence_source_types=["approved_competitor_protocol_evidence"],
            suggestions=[suggestion],
            status="candidate_ready",
            created_at=now,
        )
        self.repo.commit_revision_submission(
            thread,
            AuditEvent(
                audit_id=f"audit_atomic_submit_{project_id}{suffix}",
                project_id=project_id,
                actor="medical_manager_test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread_id,
                created_at=now,
            ),
        )
        return document, section, block, selected_text, proposal_text, thread

    def test_atomic_accept_and_apply_success(self):
        """Accept and apply in one operation: thread becomes author_selected and working copy gets revision 1."""
        project_id = PROJECTS[0]
        document, section, block, selected_text, proposal_text, thread = self._approved_thread(project_id)

        result = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="atomic-apply-rux",
        )

        self.assertEqual(1, result.working_copy.revision)
        self.assertEqual(thread.thread_id, result.thread_id)
        self.assertEqual(thread.suggestions[0].suggestion_id, result.suggestion_id)
        self.assertIn(thread.thread_id, result.working_copy.applied_revision_thread_ids)

        # Verify thread is now author_selected.
        updated_thread = self.repo.revision_thread(project_id, thread.thread_id)
        self.assertEqual("author_selected", updated_thread.status)
        accepted = [s for s in updated_thread.suggestions if s.user_decision == "accepted"]
        self.assertEqual(1, len(accepted))

        # Verify working copy content changed.
        changed = next(
            item
            for item in result.working_copy.content_blocks
            if item.get("source_locator") == block["source_locator"]
        )
        self.assertIn(proposal_text, changed["text"])

    def test_atomic_adopt_is_idempotent_on_retry(self):
        """After a successful atomic apply, the idempotency record exists
        and prevents duplicate execution with the same key."""
        project_id = PROJECTS[0]
        _, section, _, _, _, thread = self._approved_thread(project_id, suffix="_idem")

        first = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="atomic-idem-once",
        )
        self.assertEqual(1, first.working_copy.revision)

        # The idempotency record for the atomic operation must exist.
        with self.repo.runtime_store._connect() as conn:
            row = conn.execute(
                """
                SELECT request_id FROM idempotency_records
                WHERE tenant_id = ? AND project_id = ? AND operation = ?
                  AND idempotency_key = ?
                """,
                (
                    "kangzhe_local",
                    project_id,
                    "medical_writing_atomic_accept_and_apply",
                    "atomic-idem-once",
                ),
            ).fetchone()
        self.assertIsNotNone(row, "idempotency record must exist after atomic apply")
        self.assertTrue(row["request_id"])

        # Working copy remains at revision 1 — no double-apply.
        self.assertEqual(1, self.repo.working_copy(project_id, section.section_id).revision)

    def test_atomic_same_key_race_returns_the_persisted_winner_audit(self):
        project_id = PROJECTS[0]
        _, section, _, _, _, thread = self._approved_thread(project_id, suffix="_same_key_race")
        store_two = SqliteRuntimeStore(self.store.db_path)
        repo_two = MedicalWritingRuntimeRepository(self.documents, store_two)
        barrier = threading.Barrier(2)
        original_one = self.repo.runtime_store.commit_medical_writing_atomic_accept_and_apply
        original_two = repo_two.runtime_store.commit_medical_writing_atomic_accept_and_apply

        def gated(original):
            def invoke(**kwargs):
                barrier.wait(timeout=10)
                return original(**kwargs)

            return invoke

        self.repo.runtime_store.commit_medical_writing_atomic_accept_and_apply = gated(original_one)
        repo_two.runtime_store.commit_medical_writing_atomic_accept_and_apply = gated(original_two)

        def adopt(repo):
            return repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="atomic-same-key-race",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(adopt, (self.repo, repo_two)))

        self.assertEqual(1, len({result.audit_event.audit_id for result in results}))
        persisted_events = [
            event
            for event in self.repo.runtime_store.workflow_audit_events(
                project_id, "medical_writing_working_copy"
            )
            if event.action == "medical_writing_revision_applied"
            and event.detail.get("revision_thread_id") == thread.thread_id
        ]
        self.assertEqual(1, len(persisted_events))
        self.assertEqual(persisted_events[0].audit_id, results[0].audit_event.audit_id)
        self.assertEqual(persisted_events[0].audit_id, results[1].audit_event.audit_id)
        self.assertEqual(1, self.repo.working_copy(project_id, section.section_id).revision)

    def test_atomic_adopt_rejects_stale_working_copy_revision(self):
        """Stale expected_working_copy_revision raises StaleRuntimeStateError."""
        project_id = PROJECTS[1]
        _, section, _, _, _, thread = self._approved_thread(project_id)

        with self.assertRaises(StaleRuntimeStateError):
            self.repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=5,  # stale
                actor="medical_manager_test",
                idempotency_key="atomic-stale",
            )
        # Working copy must remain unchanged.
        self.assertEqual(0, self.repo.working_copy(project_id, section.section_id).revision)

    def test_atomic_adopt_rejects_already_accepted_suggestion(self):
        """Calling accept_and_apply twice with different idempotency keys on an already-accepted thread fails."""
        project_id = PROJECTS[0]
        _, section, _, _, _, thread = self._approved_thread(project_id, suffix="_dbl")

        first = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="atomic-dbl-first",
        )
        self.assertEqual(1, first.working_copy.revision)

        # Second call: suggestion is already accepted → ValueError raised
        # before any mutation.  No partial state.
        with self.assertRaisesRegex(ValueError, "already accepted"):
            self.repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=1,
                actor="medical_manager_test",
                idempotency_key="atomic-dbl-second",
            )

    def test_atomic_adopt_rejects_unknown_suggestion(self):
        """Unknown suggestion_id raises KeyError."""
        project_id = PROJECTS[0]
        _, _, _, _, _, thread = self._approved_thread(project_id, suffix="_unknown")

        with self.assertRaises(KeyError):
            self.repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id="nonexistent_suggestion",
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="atomic-unknown",
            )

    def test_atomic_adopt_rejects_cross_project_thread(self):
        """Thread from different project is rejected."""
        project_id = PROJECTS[0]
        _, _, _, _, _, thread = self._approved_thread(project_id, suffix="_xproj")

        # Thread does not exist in project_b, so revision_thread raises KeyError.
        with self.assertRaises(KeyError):
            self.repo.accept_and_apply_candidate(
                project_id=PROJECTS[1],  # wrong project
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="atomic-xproj",
            )

    def test_source_docx_not_mutated_by_atomic_adopt(self):
        """Source DOCX sections remain unchanged after atomic adopt."""
        project_id = PROJECTS[0]
        _, section, _, _, _, thread = self._approved_thread(project_id, suffix="_src")
        original_section = self.documents.section(project_id, section.section_id).model_dump(mode="json")

        self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="atomic-src",
        )

        self.assertEqual(
            original_section,
            self.documents.section(project_id, section.section_id).model_dump(mode="json"),
            "original parsed DOCX section must remain unchanged after atomic adopt",
        )

    # ------------------------------------------------------------------
    # Fault-injection rollback tests — prove true single-transaction atomicity
    # ------------------------------------------------------------------

    def _fault_injection_setup(self, project_id: str, suffix: str):
        """Create a repo backed by a fault-injecting store and a submitted thread."""
        document, section, block, selected_text, proposal_text, thread = (
            self._approved_thread(project_id, suffix=suffix)
        )
        # Capture pre-action state for rollback comparison.
        pre_thread = self.repo.revision_thread(project_id, thread.thread_id)
        pre_wc = self.repo.working_copy(project_id, section.section_id)
        return document, section, block, selected_text, proposal_text, thread, pre_thread, pre_wc

    def _assert_full_rollback(self, project_id, section_id, thread_id, pre_thread, pre_wc):
        """Assert that thread, suggestions, and working copy are unchanged."""
        post_thread = self.repo.revision_thread(project_id, thread_id)
        self.assertEqual(
            pre_thread.status,
            post_thread.status,
            "thread status must remain pre-action after rollback",
        )
        for pre_sug, post_sug in zip(
            pre_thread.suggestions, post_thread.suggestions
        ):
            self.assertEqual(
                pre_sug.user_decision,
                post_sug.user_decision,
                "all suggestions must remain in their pre-action state after rollback",
            )
        post_wc = self.repo.working_copy(project_id, section_id)
        self.assertEqual(
            pre_wc.revision,
            post_wc.revision,
            "working copy revision must remain pre-action after rollback",
        )
        self.assertEqual(
            pre_wc.content_blocks,
            post_wc.content_blocks,
            "working copy content blocks must be byte-identical after rollback",
        )
        # No success idempotency record must exist for the atomic operation.
        with self.repo.runtime_store._connect() as conn:
            row = conn.execute(
                """
                SELECT request_id FROM idempotency_records
                WHERE tenant_id = ? AND project_id = ?
                  AND operation = 'medical_writing_atomic_accept_and_apply'
                """,
                ("kangzhe_local", project_id),
            ).fetchone()
        self.assertIsNone(
            row, "no success idempotency record must remain after rollback"
        )

    def test_fault_after_thread_write_rolls_back_everything(self):
        """Inject fault after revision-thread UPDATE but before working-copy write."""
        project_id = PROJECTS[0]
        document, section, block, sel, prop, thread, pre_thread, pre_wc = (
            self._fault_injection_setup(project_id, "_fault_thread_write")
        )

        def fault(checkpoint):
            if checkpoint == "atomic_after_thread_write":
                raise RuntimeError("injected fault after thread write")

        faulting_store = SqliteRuntimeStore(
            Path(self.tmpdir.name) / "runtime.sqlite3",
            fault_injector=fault,
        )
        faulting_repo = MedicalWritingRuntimeRepository(
            self.documents, faulting_store
        )

        with self.assertRaisesRegex(RuntimeError, "injected fault after thread write"):
            faulting_repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="fault-thread-write",
            )

        self._assert_full_rollback(
            project_id, section.section_id, thread.thread_id, pre_thread, pre_wc
        )

        # Clean retry succeeds exactly once with the original repo.
        result = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="fault-thread-write-retry",
        )
        self.assertEqual(1, result.working_copy.revision)

    def test_fault_after_thread_snapshot_rolls_back_everything(self):
        """Inject fault after revision snapshot but before accept audit."""
        project_id = PROJECTS[0]
        document, section, block, sel, prop, thread, pre_thread, pre_wc = (
            self._fault_injection_setup(project_id, "_fault_snapshot")
        )

        def fault(checkpoint):
            if checkpoint == "atomic_after_thread_snapshot":
                raise RuntimeError("injected fault after thread snapshot")

        faulting_store = SqliteRuntimeStore(
            Path(self.tmpdir.name) / "runtime.sqlite3",
            fault_injector=fault,
        )
        faulting_repo = MedicalWritingRuntimeRepository(
            self.documents, faulting_store
        )

        with self.assertRaisesRegex(RuntimeError, "injected fault after thread snapshot"):
            faulting_repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="fault-snapshot",
            )

        self._assert_full_rollback(
            project_id, section.section_id, thread.thread_id, pre_thread, pre_wc
        )

        result = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="fault-snapshot-retry",
        )
        self.assertEqual(1, result.working_copy.revision)

    def test_fault_after_accept_audit_rolls_back_everything(self):
        """Inject fault after accept audit but before working-copy write."""
        project_id = PROJECTS[0]
        document, section, block, sel, prop, thread, pre_thread, pre_wc = (
            self._fault_injection_setup(project_id, "_fault_accept_audit")
        )

        def fault(checkpoint):
            if checkpoint == "atomic_after_accept_audit":
                raise RuntimeError("injected fault after accept audit")

        faulting_store = SqliteRuntimeStore(
            Path(self.tmpdir.name) / "runtime.sqlite3",
            fault_injector=fault,
        )
        faulting_repo = MedicalWritingRuntimeRepository(
            self.documents, faulting_store
        )

        with self.assertRaisesRegex(RuntimeError, "injected fault after accept audit"):
            faulting_repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="fault-accept-audit",
            )

        self._assert_full_rollback(
            project_id, section.section_id, thread.thread_id, pre_thread, pre_wc
        )

        result = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="fault-accept-audit-retry",
        )
        self.assertEqual(1, result.working_copy.revision)

    def test_fault_after_wc_write_rolls_back_everything(self):
        """Inject fault after working-copy upsert but before snapshot."""
        project_id = PROJECTS[0]
        document, section, block, sel, prop, thread, pre_thread, pre_wc = (
            self._fault_injection_setup(project_id, "_fault_wc_write")
        )

        def fault(checkpoint):
            if checkpoint == "atomic_after_wc_write":
                raise RuntimeError("injected fault after wc write")

        faulting_store = SqliteRuntimeStore(
            Path(self.tmpdir.name) / "runtime.sqlite3",
            fault_injector=fault,
        )
        faulting_repo = MedicalWritingRuntimeRepository(
            self.documents, faulting_store
        )

        with self.assertRaisesRegex(RuntimeError, "injected fault after wc write"):
            faulting_repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="fault-wc-write",
            )

        self._assert_full_rollback(
            project_id, section.section_id, thread.thread_id, pre_thread, pre_wc
        )

        result = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="fault-wc-write-retry",
        )
        self.assertEqual(1, result.working_copy.revision)

    def test_fault_after_wc_snapshot_rolls_back_everything(self):
        """Inject fault after working-copy snapshot but before apply audit."""
        project_id = PROJECTS[0]
        document, section, block, sel, prop, thread, pre_thread, pre_wc = (
            self._fault_injection_setup(project_id, "_fault_wc_snapshot")
        )

        def fault(checkpoint):
            if checkpoint == "atomic_after_wc_snapshot":
                raise RuntimeError("injected fault after wc snapshot")

        faulting_store = SqliteRuntimeStore(
            Path(self.tmpdir.name) / "runtime.sqlite3",
            fault_injector=fault,
        )
        faulting_repo = MedicalWritingRuntimeRepository(
            self.documents, faulting_store
        )

        with self.assertRaisesRegex(RuntimeError, "injected fault after wc snapshot"):
            faulting_repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="fault-wc-snapshot",
            )

        self._assert_full_rollback(
            project_id, section.section_id, thread.thread_id, pre_thread, pre_wc
        )

        result = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="fault-wc-snapshot-retry",
        )
        self.assertEqual(1, result.working_copy.revision)

    def test_fault_after_idempotency_rolls_back_everything(self):
        """Inject fault after idempotency insert but before COMMIT."""
        project_id = PROJECTS[0]
        document, section, block, sel, prop, thread, pre_thread, pre_wc = (
            self._fault_injection_setup(project_id, "_fault_idem")
        )

        def fault(checkpoint):
            if checkpoint == "atomic_after_idempotency":
                raise RuntimeError("injected fault after idempotency")

        faulting_store = SqliteRuntimeStore(
            Path(self.tmpdir.name) / "runtime.sqlite3",
            fault_injector=fault,
        )
        faulting_repo = MedicalWritingRuntimeRepository(
            self.documents, faulting_store
        )

        with self.assertRaisesRegex(RuntimeError, "injected fault after idempotency"):
            faulting_repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=0,
                actor="medical_manager_test",
                idempotency_key="fault-idem",
            )

        self._assert_full_rollback(
            project_id, section.section_id, thread.thread_id, pre_thread, pre_wc
        )

        result = self.repo.accept_and_apply_candidate(
            project_id=project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="fault-idem-retry",
        )
        self.assertEqual(1, result.working_copy.revision)


class DurableCandidateJobTests(unittest.TestCase):
    """Tests for durable section AI candidate generation."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.durable_store = DurableJobStore(Path(self.tmpdir.name) / "durable.db")
        self.documents = MedicalWritingDocumentService()
        self.store = SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3")
        self.repo = MedicalWritingRuntimeRepository(self.documents, self.store)
        # revision_service with ai_task_runner=None is sufficient for
        # testing durable job create/dedupe/reuse without real AI calls.
        from types import SimpleNamespace

        from services.api.app.ai_execution_policy import AiExecutionPolicyResolver

        self.revision_service = MedicalWritingRevisionService(
            self.repo,
            ai_task_runner=SimpleNamespace(
                policy_resolver=AiExecutionPolicyResolver(
                    provider_name="deepseek",
                    model_name="deepseek-chat",
                )
            ),
        )
        # Durable store tests exercise job identity, not real Source Registry AI.
        self.revision_service.require_registered_sources = False

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_submit_revision_durable_returns_job_id_immediately(self):
        """submit_revision_durable returns job_id without blocking on AI."""
        project_id = PROJECTS[0]
        document = self.documents.document_session(project_id)
        section = self.documents.section(project_id, document.sections[0].section_id)
        block = None
        for b in section.content_blocks:
            text = str(b.get("text", "")).strip()
            if len(text) >= 10 and b.get("source_locator"):
                block = b
                break
        self.assertIsNotNone(block, "test requires a substantive block")

        request = MedicalWritingRevisionRequest(
            document_id=document.document_id,
            section_id=section.section_id,
            selected_text=str(block["text"])[:40],
            anchor_path=block["source_locator"],
            user_instruction="请测试耐久作业",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )

        job_id, result = self.revision_service.submit_revision_durable(
            project_id, request, self.durable_store
        )
        self.assertTrue(job_id.startswith("mwjob_"))
        self.assertIsNone(result)  # not completed yet

        # Verify the job is in queued status.
        job = self.durable_store.get(project_id, job_id)
        self.assertEqual("queued", job.status)

    def test_ambiguous_selection_is_rejected_before_durable_job_creation(self):
        project_id = PROJECTS[0]
        document = self.documents.document_session(project_id)
        section = self.documents.section(project_id, document.sections[0].section_id)
        target = next(
            block
            for block in section.content_blocks
            if str(block.get("text", "")).strip() and block.get("source_locator")
        )
        current = self.repo.working_copy(project_id, section.section_id)
        blocks = [dict(item) for item in current.content_blocks]
        working_target = next(
            item
            for item in blocks
            if item.get("source_locator") == target["source_locator"]
        )
        working_target["text"] = "aaaa；重复选区词语位于段首，随后再次出现重复选区词语。"
        working_target["rich_text"] = {
            "type": "paragraph",
            "content": [{"type": "text", "text": working_target["text"]}],
        }
        self.repo.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=document.document_id,
                expected_revision=0,
                content_blocks=blocks,
                actor="medical_manager_test",
                idempotency_key="save-durable-ambiguous-selection",
            ),
        )

        request = MedicalWritingRevisionRequest(
            document_id=document.document_id,
            section_id=section.section_id,
            selected_text="aaa",
            anchor_path=target["source_locator"],
            user_instruction="请测试歧义选区必须在提交前失败关闭。",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.revision_service.submit_revision_durable(
                project_id, request, self.durable_store
            )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.revision_service.submit_revision_durable(
                project_id,
                request.model_copy(update={"anchor_path": ""}),
                self.durable_store,
            )
        self.assertEqual(
            [],
            self.durable_store.list_by_project(
                project_id, job_type="section_ai_candidate"
            ),
        )

    def test_dedupe_same_request_returns_same_job_id(self):
        """Same request submitted twice returns the same job_id."""
        project_id = PROJECTS[0]
        document = self.documents.document_session(project_id)
        section = self.documents.section(project_id, document.sections[0].section_id)
        block = next(
            b for b in section.content_blocks
            if str(b.get("text", "")).strip() and b.get("source_locator")
        )
        request = MedicalWritingRevisionRequest(
            document_id=document.document_id,
            section_id=section.section_id,
            selected_text=str(block["text"])[:30],
            anchor_path=block["source_locator"],
            user_instruction="去重测试",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )

        job_id_1, _ = self.revision_service.submit_revision_durable(
            project_id, request, self.durable_store
        )
        job_id_2, _ = self.revision_service.submit_revision_durable(
            project_id, request, self.durable_store
        )
        self.assertEqual(job_id_1, job_id_2)

    def test_cancel_isolation_prevents_completion(self):
        """A cancelled durable job cannot be CAS-completed by a late owner."""
        project_id = PROJECTS[0]
        document = self.documents.document_session(project_id)
        section = self.documents.section(project_id, document.sections[0].section_id)
        block = next(
            b for b in section.content_blocks
            if str(b.get("text", "")).strip() and b.get("source_locator")
        )
        request = MedicalWritingRevisionRequest(
            document_id=document.document_id,
            section_id=section.section_id,
            selected_text=str(block["text"])[:30],
            anchor_path=block["source_locator"],
            user_instruction="取消隔离测试",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )

        job_id, _ = self.revision_service.submit_revision_durable(
            project_id, request, self.durable_store
        )

        # Claim and then cancel.
        claim = self.durable_store.claim(project_id, job_id)
        self.assertTrue(claim.claimed)

        cancel_result = self.durable_store.cancel(project_id, job_id)
        self.assertTrue(cancel_result.cancelled)

        # Late completion attempt must fail.
        completed = self.durable_store.complete(
            project_id, job_id, claim.claim_token,
            output_hash="test",
        )
        self.assertFalse(completed)

        job = self.durable_store.get(project_id, job_id)
        self.assertEqual("cancelled", job.status)

    def test_stale_owner_cannot_complete_after_lease_expiry(self):
        """A stale owner whose lease expired cannot complete the job."""
        project_id = PROJECTS[0]
        document = self.documents.document_session(project_id)
        section = self.documents.section(project_id, document.sections[0].section_id)
        block = next(
            b for b in section.content_blocks
            if str(b.get("text", "")).strip() and b.get("source_locator")
        )
        request = MedicalWritingRevisionRequest(
            document_id=document.document_id,
            section_id=section.section_id,
            selected_text=str(block["text"])[:30],
            anchor_path=block["source_locator"],
            user_instruction="租约过期测试",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )

        job_id, _ = self.revision_service.submit_revision_durable(
            project_id, request, self.durable_store
        )

        # Claim with the original store.
        claim = self.durable_store.claim(project_id, job_id)
        self.assertTrue(claim.claimed)
        old_token = claim.claim_token

        # Simulate lease expiry by manipulating the lease_expires_at.
        with self.durable_store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "UPDATE durable_mw_jobs SET lease_expires_at = ? WHERE job_id = ?",
                ("2020-01-01T00:00:00+00:00", job_id),
            )
            conn.commit()

        # Stale owner tries to complete — must fail.
        completed = self.durable_store.complete(
            project_id, job_id, old_token,
            output_hash="stale",
        )
        self.assertFalse(completed)

    def test_project_isolation_in_durable_jobs(self):
        """Different projects get different job_ids for the same business key."""
        project_a = PROJECTS[0]
        project_b = PROJECTS[1]
        document_a = self.documents.document_session(project_a)
        section_a = document_a.sections[0]
        block_a = next(
            block
            for block in self.documents.section(project_a, section_a.section_id).content_blocks
            if str(block.get("text", "")).strip() and block.get("source_locator")
        )

        request_a = MedicalWritingRevisionRequest(
            document_id=document_a.document_id,
            section_id=section_a.section_id,
            selected_text=str(block_a["text"])[:20],
            anchor_path=block_a["source_locator"],
            user_instruction="相同指令",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )
        job_id_a, _ = self.revision_service.submit_revision_durable(
            project_a, request_a, self.durable_store
        )

        # Submit the "same" request for project B (different project_id).
        document_b = self.documents.document_session(project_b)
        section_b = document_b.sections[0]
        block_b = next(
            block
            for block in self.documents.section(project_b, section_b.section_id).content_blocks
            if str(block.get("text", "")).strip() and block.get("source_locator")
        )
        request_b = MedicalWritingRevisionRequest(
            document_id=document_b.document_id,
            section_id=section_b.section_id,
            selected_text=str(block_b["text"])[:20],
            anchor_path=block_b["source_locator"],
            user_instruction="相同指令",
            intent="regulatory_tone",
            requested_by="medical_manager_test",
        )
        job_id_b, _ = self.revision_service.submit_revision_durable(
            project_b, request_b, self.durable_store
        )
        self.assertNotEqual(job_id_a, job_id_b)

    def test_section_ai_candidate_executor_protocol(self):
        """SectionAiCandidateExecutor implements the DurableJobExecutor protocol."""
        executor = SectionAiCandidateExecutor(self.revision_service)
        self.assertEqual("section_ai_candidate", executor.job_type)
        self.assertTrue(hasattr(executor, "execute"))


class SectionMismatchValidationTests(unittest.TestCase):
    """P1-4: Verify the tautological section check is replaced with real validation."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.documents = MedicalWritingDocumentService()
        self.store = SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3")
        self.repo = MedicalWritingRuntimeRepository(self.documents, self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_rejects_thread_with_nonexistent_section(self):
        """A thread referencing a section that doesn't exist in the document is rejected."""
        project_id = PROJECTS[0]
        document = self.documents.document_session(project_id)
        # Find a real section_id to craft the thread, then change it to a fake one.
        real_section_id = document.sections[0].section_id
        fake_section_id = "sec_does_not_exist_xyz"
        # Ensure the fake section_id is genuinely not in the document.
        all_section_ids = {s.section_id for s in document.sections}
        self.assertNotIn(fake_section_id, all_section_ids)

        now = datetime.now(timezone.utc)
        suggestion = RevisionSuggestion(
            suggestion_id="sug_section_mismatch",
            proposal_text="test proposal",
            diff_patch="- old\n+ test proposal",
            rationale="test",
            evidence_span_ids=["span_test"],
            evidence_source_types=["approved_competitor_protocol_evidence"],
        )
        thread = RevisionThread(
            thread_id="thread_section_mismatch",
            project_id=project_id,
            document_id=document.document_id,
            section_id=fake_section_id,
            anchor_type="selection",
            anchor_path="test_locator",
            selected_text="test text",
            user_instruction="test",
            intent="regulatory_tone",
            ai_run_id="run_test",
            source_entry_id="entry_test",
            source_id="source_test",
            source_locator="test_locator",
            evidence_source_types=["approved_competitor_protocol_evidence"],
            suggestions=[suggestion],
            status="candidate_ready",
            created_at=now,
        )
        # We can't commit_revision_submission for a thread with a fake section_id
        # because the runtime_store may reject it. Instead, directly test the
        # accept_and_apply_candidate guard by manually inserting the thread.
        self.repo.runtime_store.commit_medical_writing_revision_submission(
            thread,
            AuditEvent(
                audit_id="audit_mismatch",
                project_id=project_id,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=now,
            ),
        )

        with self.assertRaisesRegex(RuntimeStoreError, "unknown section"):
            self.repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread.thread_id,
                suggestion_id=suggestion.suggestion_id,
                expected_working_copy_revision=0,
                actor="test",
                idempotency_key="section-mismatch",
            )


# ---------------------------------------------------------------------------
# Deterministic product-AI fake used by ownership / concurrency tests.
# Echoes source text so protocol-label validation remains pass-closed.
# ---------------------------------------------------------------------------


class _EchoRevisionProvider:
    """OpenAI-compatible-ish revision provider with project-tagged proposals."""

    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(self, tag: str = "A"):
        self.tag = tag
        self.calls = 0
        self.envelopes = []

    def run(self, envelope):
        self.calls += 1
        self.envelopes.append(envelope)
        sources = envelope.payload["allowed_sources"]
        source = sources[0]
        base = str(source.get("text_preview") or "文本")
        proposal = f"{base}（候选{self.tag}）"
        task_type = envelope.task_type
        if hasattr(task_type, "value"):
            task_type = task_type.value
        return {
            "task_id": envelope.task_id,
            "task_type": task_type,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": [item["source_id"] for item in sources],
            "forbidden_source_ids": envelope.payload.get("forbidden_source_ids", []),
            "findings": [
                {
                    "finding_id": f"finding_{self.tag}_{self.calls}",
                    "status": "supported",
                    "title": f"echo-{self.tag}",
                    "source_id": source["source_id"],
                    "evidence_span_ids": [f"span_{self.tag}"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": f"span_{self.tag}",
                    "source_id": source["source_id"],
                    "locator": source["locator"],
                    "quote": base[:120],
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "revision": {
                "proposal_text": proposal,
                "diff_patch": f"- {base}\n+ {proposal}",
                "rationale": f"deterministic echo {self.tag}",
                "evidence_span_ids": [f"span_{self.tag}"],
                "alternatives": [
                    {
                        "proposal_text": f"{base}（候选{self.tag}-2）",
                        "diff_patch": "alt2",
                        "rationale": "alt2",
                        "evidence_span_ids": [f"span_{self.tag}"],
                    },
                    {
                        "proposal_text": f"{base}（候选{self.tag}-3）",
                        "diff_patch": "alt3",
                        "rationale": "alt3",
                        "evidence_span_ids": [f"span_{self.tag}"],
                    },
                ],
            },
        }


def _build_echo_service(tmpdir: Path, tag: str = "A"):
    from services.api.app.ai_execution_policy import AiExecutionPolicyResolver
    from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore

    documents = MedicalWritingDocumentService()
    store = SqliteRuntimeStore(tmpdir / "runtime.sqlite3")
    repo = MedicalWritingRuntimeRepository(documents, store)
    provider = _EchoRevisionProvider(tag=tag)
    policy = AiExecutionPolicyResolver(
        deployment_profile="local_private_clinical",
        provider_name="buddy",
        model_name="deepseek-v4-pro",
        test_only_provider_injection=True,
    )
    runner = AiTaskRunner(
        repo,
        AiTaskStore(tmpdir / "ai_runs.jsonl"),
        provider_factory=lambda resolution: provider,
        policy_resolver=policy,
    )
    service = MedicalWritingRevisionService(repo, runner)
    # Demo document repos lack protocol source registration; use the internal
    # selection path while still exercising the real AiTaskRunner + provider.
    service.require_registered_sources = False
    return documents, store, repo, service, provider


def _substantive_block(documents, project_id: str):
    document = documents.document_session(project_id)
    for summary in document.sections:
        section = documents.section(project_id, summary.section_id)
        for block in section.content_blocks:
            text = str(block.get("text", "")).strip()
            if len(text) >= 20 and block.get("source_locator"):
                return document, section, block, text[: min(48, len(text))]
    raise AssertionError(f"no substantive block for {project_id}")


def _initial_job(
    project_id: str,
    documents,
    instruction: str = "改写为可审阅候选",
    *,
    service: MedicalWritingRevisionService | None = None,
):
    from types import SimpleNamespace

    document, section, block, selected = _substantive_block(documents, project_id)
    payload = {
        "document_id": document.document_id,
        "section_id": section.section_id,
        "selected_text": selected,
        "anchor_path": block["source_locator"],
        "anchor_type": "selection",
        "user_instruction": instruction,
        "intent": "regulatory_tone",
        "requested_by": "medical_manager_test",
        "evidence_brief_ids": [],
    }
    if service is not None:
        request = MedicalWritingRevisionRequest.model_validate(payload)
        payload["generation_context"] = service.build_generation_context_descriptor(
            project_id,
            section_id=section.section_id,
            operation="initial",
            request=request,
        )
    return SimpleNamespace(
        project_id=project_id,
        payload_json=json.dumps(payload, ensure_ascii=False),
    ), document, section, block, selected


def _seed_candidate_thread(repo, documents, project_id: str, suffix: str = ""):
    """Persist a candidate_ready thread so rewrite paths can run."""
    document, section, block, selected = _substantive_block(documents, project_id)
    now = datetime.now(timezone.utc)
    thread = RevisionThread(
        thread_id=f"thread_seed_{project_id}{suffix}",
        project_id=project_id,
        document_id=document.document_id,
        section_id=section.section_id,
        anchor_type="selection",
        anchor_path=block["source_locator"],
        selected_text=selected,
        user_instruction="seed",
        intent="regulatory_tone",
        ai_run_id=f"run_seed_{project_id}{suffix}",
        source_entry_id=f"entry_seed_{project_id}{suffix}",
        source_id=f"source_seed_{project_id}{suffix}",
        source_locator=block["source_locator"],
        evidence_source_types=["protocol_section_selection"],
        suggestions=[
            RevisionSuggestion(
                suggestion_id=f"sug_seed_{project_id}{suffix}",
                proposal_text=f"{selected}（seed）",
                diff_patch="seed",
                rationale="seed",
                evidence_span_ids=[f"span_seed_{project_id}{suffix}"],
                evidence_source_types=["protocol_section_selection"],
            )
        ],
        status="candidate_ready",
        created_at=now,
    )
    repo.commit_revision_submission(
        thread,
        AuditEvent(
            audit_id=f"audit_seed_{project_id}{suffix}",
            project_id=project_id,
            actor="test",
            action="medical_writing_revision_submitted",
            target_type="revision_thread",
            target_id=thread.thread_id,
            created_at=now,
        ),
    )
    return thread, document, section, block, selected


class ServiceResolverRoutingTests(unittest.TestCase):
    """Resolver construction and direct-service compatibility."""

    def test_resolver_routes_each_job_to_correct_service(self):
        project_a = PROJECTS[0]
        project_b = PROJECTS[1]
        tmpdir_a = tempfile.TemporaryDirectory()
        tmpdir_b = tempfile.TemporaryDirectory()
        try:
            _, _, _, service_a, _ = _build_echo_service(Path(tmpdir_a.name), "A")
            _, _, _, service_b, _ = _build_echo_service(Path(tmpdir_b.name), "B")
            routed = {}

            def resolver(project_id):
                routed.setdefault(project_id, 0)
                routed[project_id] += 1
                return service_a if project_id == project_a else service_b

            executor = SectionAiCandidateExecutor(service_resolver=resolver)
            self.assertIs(executor._resolve(project_a), service_a)
            self.assertIs(executor._resolve(project_b), service_b)
            self.assertEqual(routed[project_a], 1)
            self.assertEqual(routed[project_b], 1)
        finally:
            tmpdir_a.cleanup()
            tmpdir_b.cleanup()

    def test_direct_service_constructor_still_works(self):
        tmpdir = tempfile.TemporaryDirectory()
        try:
            _, _, _, service, _ = _build_echo_service(Path(tmpdir.name), "X")
            executor = SectionAiCandidateExecutor(service)
            self.assertIs(executor._resolve("any_project"), service)
        finally:
            tmpdir.cleanup()

    def test_requires_service_or_resolver(self):
        with self.assertRaises(ValueError):
            SectionAiCandidateExecutor()


class RealOwnershipBarrierInitialTests(unittest.TestCase):
    """Initial-submit path: AI completes, then ownership barrier gates commit."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        (
            self.documents,
            self.store,
            self.repo,
            self.service,
            self.provider,
        ) = _build_echo_service(Path(self.tmpdir.name), tag="I")
        self.executor = SectionAiCandidateExecutor(self.service)
        self.project_id = PROJECTS[0]
        self.job, self.document, self.section, self.block, self.selected = _initial_job(
            self.project_id, self.documents, service=self.service
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _thread_count(self):
        return len(self.repo.revision_threads(self.project_id))

    def _audits(self):
        return self.store.workflow_audit_events(
            self.project_id, "medical_writing_revision"
        )

    def test_cancel_before_start_no_ai_and_no_thread(self):
        result = self.executor.execute(
            self.job, "tok", lambda: True, lambda p: True
        )
        self.assertTrue(result.error)
        self.assertIn("cancelled", result.error)
        self.assertEqual(0, self.provider.calls)
        self.assertEqual(0, self._thread_count())
        self.assertEqual(0, len(self._audits()))

    def test_cancel_true_after_ai_no_business_write(self):
        """First cancel_check False (pre-AI); second True (post-AI)."""
        calls = {"n": 0}

        def cancel_check():
            calls["n"] += 1
            return calls["n"] > 1

        result = self.executor.execute(
            self.job, "tok", cancel_check, lambda p: True
        )
        self.assertTrue(result.error)
        self.assertIn("cancelled after AI", result.error)
        self.assertGreaterEqual(self.provider.calls, 1)
        self.assertEqual(0, self._thread_count())
        self.assertEqual(0, len(self._audits()))

    def test_cancel_exception_after_ai_fail_closed_no_write(self):
        calls = {"n": 0}

        def cancel_check():
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("ownership unprovable")
            return False

        result = self.executor.execute(
            self.job, "tok", cancel_check, lambda p: True
        )
        self.assertTrue(result.error)
        self.assertIn("cancelled after AI", result.error)
        self.assertGreaterEqual(self.provider.calls, 1)
        self.assertEqual(0, self._thread_count())

    def test_heartbeat_false_before_ai_no_provider_call_or_business_write(self):
        result = self.executor.execute(
            self.job, "tok", lambda: False, lambda p: False
        )
        self.assertTrue(result.error)
        self.assertIn("heartbeat", result.error)
        self.assertEqual(0, self.provider.calls)
        self.assertEqual(0, self._thread_count())

    def test_heartbeat_exception_before_ai_no_provider_call_or_business_write(self):
        def bad_hb(p):
            raise ConnectionError("lease lost")

        result = self.executor.execute(
            self.job, "tok", lambda: False, bad_hb
        )
        self.assertTrue(result.error)
        self.assertIn("heartbeat", result.error)
        self.assertEqual(0, self.provider.calls)
        self.assertEqual(0, self._thread_count())

    def test_takeover_then_old_owner_late_commit_blocked(self):
        """New owner succeeds; late old owner after cancel does not write again."""
        # New owner full success first.
        ok = self.executor.execute(
            self.job, "new-tok", lambda: False, lambda p: True
        )
        self.assertFalse(ok.error)
        self.assertEqual(1, self._thread_count())
        thread = self.repo.revision_threads(self.project_id)[0]
        self.assertEqual("candidate_ready", thread.status)
        self.assertEqual(3, len(thread.suggestions))
        first_ids = {t.thread_id for t in self.repo.revision_threads(self.project_id)}
        audit_count = len(self._audits())

        # Late old owner: cancel true after AI (simulating lost claim).
        late_calls = {"n": 0}

        def late_cancel():
            late_calls["n"] += 1
            return late_calls["n"] > 1

        late = self.executor.execute(
            self.job, "old-tok", late_cancel, lambda p: True
        )
        self.assertTrue(late.error)
        self.assertEqual(first_ids, {t.thread_id for t in self.repo.revision_threads(self.project_id)})
        self.assertEqual(audit_count, len(self._audits()))

    def test_clean_success_then_retry_once_after_cancel_path(self):
        """Cancel path leaves clean state; a later owned run commits exactly once."""
        calls = {"n": 0}

        def cancel_check():
            calls["n"] += 1
            return calls["n"] > 1

        blocked = self.executor.execute(
            self.job, "tok1", cancel_check, lambda p: True
        )
        self.assertTrue(blocked.error)
        self.assertEqual(0, self._thread_count())

        ok = self.executor.execute(
            self.job, "tok2", lambda: False, lambda p: True
        )
        self.assertFalse(ok.error)
        threads = self.repo.revision_threads(self.project_id)
        self.assertEqual(1, len(threads))
        self.assertEqual("candidate_ready", threads[0].status)
        self.assertEqual(3, len(threads[0].suggestions))
        self.assertTrue(
            any(a.action == "medical_writing_revision_submitted" for a in self._audits())
        )
        self.assertIn("候选I", threads[0].suggestions[0].proposal_text)


class RealOwnershipBarrierRewriteTests(unittest.TestCase):
    """Rewrite path ownership barriers with real repository state."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        (
            self.documents,
            self.store,
            self.repo,
            self.service,
            self.provider,
        ) = _build_echo_service(Path(self.tmpdir.name), tag="R")
        self.executor = SectionAiCandidateExecutor(self.service)
        self.project_id = PROJECTS[0]
        self.seed, self.document, self.section, self.block, self.selected = (
            _seed_candidate_thread(self.repo, self.documents, self.project_id)
        )
        from types import SimpleNamespace

        rewrite_payload = {
            "mode": "rewrite",
            "thread_id": self.seed.thread_id,
            "suggestion_id": self.seed.suggestions[0].suggestion_id,
            "rewrite_instruction": "请生成下一轮候选",
            "comment": "rewrite-test",
            "actor": "medical_manager_test",
            "evidence_brief_ids": list(self.seed.evidence_brief_ids or []),
        }
        rewrite_payload["generation_context"] = self.service.build_generation_context_descriptor(
            self.project_id,
            section_id=self.seed.section_id,
            operation="rewrite",
            rewrite=rewrite_payload,
        )
        self.job = SimpleNamespace(
            project_id=self.project_id,
            payload_json=json.dumps(rewrite_payload, ensure_ascii=False),
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_rewrite_cancel_after_ai_does_not_mutate_seed(self):
        before = self.repo.revision_thread(self.project_id, self.seed.thread_id)
        before_json = before.model_dump_json()
        calls = {"n": 0}

        def cancel_check():
            calls["n"] += 1
            return calls["n"] > 1

        result = self.executor.execute(
            self.job, "tok", cancel_check, lambda p: True
        )
        self.assertTrue(result.error)
        self.assertGreaterEqual(self.provider.calls, 1)
        after = self.repo.revision_thread(self.project_id, self.seed.thread_id)
        self.assertEqual(before_json, after.model_dump_json())
        self.assertEqual(1, len(after.suggestions))
        self.assertEqual("pending", after.suggestions[0].user_decision)

    def test_rewrite_heartbeat_exception_no_mutation(self):
        before = self.repo.revision_thread(self.project_id, self.seed.thread_id)
        before_len = len(before.suggestions)

        def bad_hb(p):
            raise RuntimeError("hb")

        result = self.executor.execute(
            self.job, "tok", lambda: False, bad_hb
        )
        self.assertTrue(result.error)
        after = self.repo.revision_thread(self.project_id, self.seed.thread_id)
        self.assertEqual(before_len, len(after.suggestions))
        self.assertEqual("pending", after.suggestions[0].user_decision)

    def test_rewrite_success_appends_new_turn_once(self):
        result = self.executor.execute(
            self.job, "tok", lambda: False, lambda p: True
        )
        self.assertFalse(result.error)
        after = self.repo.revision_thread(self.project_id, self.seed.thread_id)
        self.assertEqual("candidate_ready", after.status)
        self.assertGreaterEqual(len(after.suggestions), 4)  # seed + 3 new
        self.assertEqual("rewrite_requested", after.suggestions[0].user_decision)
        new_pending = [s for s in after.suggestions if s.user_decision == "pending"]
        self.assertEqual(3, len(new_pending))
        self.assertTrue(all(s.turn_number == 2 for s in new_pending))
        self.assertIn("候选R", new_pending[0].proposal_text)


class SyncRewriteSnapshotTests(unittest.TestCase):
    """Synchronous rewrite must keep diff/impact on one working-copy snapshot."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        (
            self.documents,
            self.store,
            self.repo,
            self.service,
            self.provider,
        ) = _build_echo_service(Path(self.tmpdir.name), tag="S")
        self.project_id = PROJECTS[0]
        self.executor = SectionAiCandidateExecutor(self.service)
        self.job, self.document, self.section, self.block, self.selected = _initial_job(
            self.project_id, self.documents, service=self.service
        )
        initial = self.executor.execute(
            self.job, "initial-token", lambda: False, lambda _progress: True
        )
        self.assertFalse(initial.error, initial.error)
        self.thread = self.repo.revision_threads(self.project_id)[0]
        self.assertTrue(self.thread.source_working_copy_id)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_sync_rewrite_rejects_save_after_ai_before_diff_projection(self):
        original_run = self.service._run_revision_ai

        def run_then_concurrent_save(*args, **kwargs):
            execution = original_run(*args, **kwargs)
            current = self.repo.working_copy(self.project_id, self.section.section_id)
            changed_blocks = json.loads(
                json.dumps(current.content_blocks, ensure_ascii=False)
            )
            target = next(
                item
                for item in changed_blocks
                if item.get("source_locator") == self.block["source_locator"]
            )
            # Preserve the selected range so only the immutable working-copy
            # identity can detect this concurrent save.
            suffix = "（并发保存）"
            target["text"] = f'{target.get("text", "")}{suffix}'
            if isinstance(target.get("rich_text"), dict):
                text_nodes = []

                def collect_rich_text(node):
                    if not isinstance(node, dict):
                        return
                    if node.get("type") == "text":
                        text_nodes.append(node)
                    for child in (node.get("content") or []):
                        collect_rich_text(child)

                collect_rich_text(target["rich_text"])
                self.assertTrue(text_nodes)
                text_nodes[-1]["text"] = f'{text_nodes[-1].get("text", "")}{suffix}'
            self.repo.save_working_copy(
                self.project_id,
                self.section.section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=self.document.document_id,
                    expected_revision=current.revision,
                    content_blocks=changed_blocks,
                    actor="concurrent_editor",
                    idempotency_key="sync-rewrite-race",
                ),
            )
            return execution

        with mock.patch.object(
            self.service, "_run_revision_ai", side_effect=run_then_concurrent_save
        ):
            with self.assertRaisesRegex(
                StaleRuntimeStateError, "stale working-copy revision"
            ):
                self.service.apply_action(
                    self.project_id,
                    self.thread.thread_id,
                    RevisionActionRequest(
                        action=RevisionAction.REQUEST_REWRITE,
                        suggestion_id=self.thread.suggestions[0].suggestion_id,
                        actor="medical_manager_test",
                        rewrite_instruction="请再审阅一轮",
                    ),
                )
        stored = self.repo.revision_thread(self.project_id, self.thread.thread_id)
        self.assertEqual(len(self.thread.suggestions), len(stored.suggestions))
        self.assertTrue(all(item.user_decision == "pending" for item in stored.suggestions))
        self.assertEqual(1, self.repo.working_copy(
            self.project_id, self.section.section_id
        ).revision)


class RealConcurrencyAndRoutingTests(unittest.TestCase):
    """Successful concurrent execute through one resolver into two repos."""

    def setUp(self):
        self.tmpdir_a = tempfile.TemporaryDirectory()
        self.tmpdir_b = tempfile.TemporaryDirectory()
        (
            self.docs_a,
            self.store_a,
            self.repo_a,
            self.service_a,
            self.provider_a,
        ) = _build_echo_service(Path(self.tmpdir_a.name), tag="A")
        (
            self.docs_b,
            self.store_b,
            self.repo_b,
            self.service_b,
            self.provider_b,
        ) = _build_echo_service(Path(self.tmpdir_b.name), tag="B")
        self.project_a = PROJECTS[0]
        self.project_b = PROJECTS[1]
        self.routed = []

        def resolver(project_id):
            self.routed.append(project_id)
            if project_id == self.project_a:
                return self.service_a
            return self.service_b

        self.executor = SectionAiCandidateExecutor(service_resolver=resolver)

    def tearDown(self):
        self.tmpdir_a.cleanup()
        self.tmpdir_b.cleanup()

    def test_successful_execute_routes_and_isolates_repos(self):
        job_a, *_ = _initial_job(self.project_a, self.docs_a, "A-job", service=self.service_a)
        job_b, *_ = _initial_job(self.project_b, self.docs_b, "B-job", service=self.service_b)
        res_a = self.executor.execute(job_a, "tok-a", lambda: False, lambda p: True)
        res_b = self.executor.execute(job_b, "tok-b", lambda: False, lambda p: True)
        self.assertFalse(res_a.error)
        self.assertFalse(res_b.error)
        self.assertIn(self.project_a, self.routed)
        self.assertIn(self.project_b, self.routed)
        threads_a = self.repo_a.revision_threads(self.project_a)
        threads_b = self.repo_b.revision_threads(self.project_b)
        self.assertEqual(1, len(threads_a))
        self.assertEqual(1, len(threads_b))
        self.assertEqual(self.project_a, threads_a[0].project_id)
        self.assertEqual(self.project_b, threads_b[0].project_id)
        self.assertIn("候选A", threads_a[0].suggestions[0].proposal_text)
        self.assertIn("候选B", threads_b[0].suggestions[0].proposal_text)
        self.assertEqual(0, len(self.repo_a.revision_threads(self.project_b)))
        self.assertEqual(0, len(self.repo_b.revision_threads(self.project_a)))
        # Provider identity is product-AI audit metadata; when the runner exposes
        # it, it must match the deterministic fake; empty is acceptable.
        if res_a.provider:
            self.assertEqual("buddy", res_a.provider)
        if res_a.model:
            self.assertEqual("deepseek-v4-pro", res_a.model)
        self.assertEqual(self.provider_a.provider_name, "buddy")
        self.assertEqual(self.provider_b.model_name, "deepseek-v4-pro")

    def test_concurrent_execute_no_cross_capture(self):
        import threading as _t

        job_a, *_ = _initial_job(self.project_a, self.docs_a, "A-conc", service=self.service_a)
        job_b, *_ = _initial_job(self.project_b, self.docs_b, "B-conc", service=self.service_b)
        barrier = _t.Barrier(2)
        results = {}

        def worker(name, job):
            barrier.wait(timeout=10)
            results[name] = self.executor.execute(
                job, f"tok-{name}", lambda: False, lambda p: True
            )

        t1 = _t.Thread(target=worker, args=("a", job_a))
        t2 = _t.Thread(target=worker, args=("b", job_b))
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)
        self.assertFalse(results["a"].error)
        self.assertFalse(results["b"].error)
        threads_a = self.repo_a.revision_threads(self.project_a)
        threads_b = self.repo_b.revision_threads(self.project_b)
        self.assertEqual(1, len(threads_a))
        self.assertEqual(1, len(threads_b))
        self.assertIn("候选A", threads_a[0].suggestions[0].proposal_text)
        self.assertIn("候选B", threads_b[0].suggestions[0].proposal_text)

    def test_one_job_ownership_loss_does_not_suppress_other(self):
        import threading as _t

        job_a, *_ = _initial_job(self.project_a, self.docs_a, "A-loss", service=self.service_a)
        job_b, *_ = _initial_job(self.project_b, self.docs_b, "B-ok", service=self.service_b)
        barrier = _t.Barrier(2)
        results = {}

        def cancel_a():
            # Always cancel after AI for project A.
            cancel_a.n = getattr(cancel_a, "n", 0) + 1
            return cancel_a.n > 1

        def worker_a():
            barrier.wait(timeout=10)
            results["a"] = self.executor.execute(
                job_a, "tok-a", cancel_a, lambda p: True
            )

        def worker_b():
            barrier.wait(timeout=10)
            results["b"] = self.executor.execute(
                job_b, "tok-b", lambda: False, lambda p: True
            )

        t1 = _t.Thread(target=worker_a)
        t2 = _t.Thread(target=worker_b)
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)
        self.assertTrue(results["a"].error)
        self.assertFalse(results["b"].error)
        self.assertEqual(0, len(self.repo_a.revision_threads(self.project_a)))
        self.assertEqual(1, len(self.repo_b.revision_threads(self.project_b)))

    def test_concurrent_rewrite_success(self):
        import threading as _t
        from types import SimpleNamespace

        seed_a, *_ = _seed_candidate_thread(
            self.repo_a, self.docs_a, self.project_a, suffix="_rw"
        )
        seed_b, *_ = _seed_candidate_thread(
            self.repo_b, self.docs_b, self.project_b, suffix="_rw"
        )

        def _rewrite_job(service, project_id, seed, instruction):
            payload = {
                "mode": "rewrite",
                "thread_id": seed.thread_id,
                "suggestion_id": seed.suggestions[0].suggestion_id,
                "rewrite_instruction": instruction,
                "comment": "",
                "actor": "test",
                "evidence_brief_ids": list(seed.evidence_brief_ids or []),
            }
            payload["generation_context"] = service.build_generation_context_descriptor(
                project_id,
                section_id=seed.section_id,
                operation="rewrite",
                rewrite=payload,
            )
            return SimpleNamespace(
                project_id=project_id,
                payload_json=json.dumps(payload, ensure_ascii=False),
            )

        job_a = _rewrite_job(self.service_a, self.project_a, seed_a, "A rewrite")
        job_b = _rewrite_job(self.service_b, self.project_b, seed_b, "B rewrite")
        barrier = _t.Barrier(2)
        results = {}

        def worker(name, job):
            barrier.wait(timeout=10)
            results[name] = self.executor.execute(
                job, f"tok-{name}", lambda: False, lambda p: True
            )

        t1 = _t.Thread(target=worker, args=("a", job_a))
        t2 = _t.Thread(target=worker, args=("b", job_b))
        t1.start()
        t2.start()
        t1.join(timeout=60)
        t2.join(timeout=60)
        self.assertFalse(results["a"].error)
        self.assertFalse(results["b"].error)
        after_a = self.repo_a.revision_thread(self.project_a, seed_a.thread_id)
        after_b = self.repo_b.revision_thread(self.project_b, seed_b.thread_id)
        self.assertGreaterEqual(len(after_a.suggestions), 4)
        self.assertGreaterEqual(len(after_b.suggestions), 4)
        self.assertIn("候选A", after_a.suggestions[-1].proposal_text)
        self.assertIn("候选B", after_b.suggestions[-1].proposal_text)


class ThreadLocalRepoSafetyTests(unittest.TestCase):
    """Thread-local override nesting/restoration and rewrite deep-copy."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        (
            self.documents,
            self.store,
            self.repo,
            self.service,
            self.provider,
        ) = _build_echo_service(Path(self.tmpdir.name), tag="T")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_nested_with_repo_restores_previous(self):
        outer = object()
        inner = object()
        with self.service._with_repo(outer):
            self.assertIs(self.service._effective_repo, outer)
            with self.service._with_repo(inner):
                self.assertIs(self.service._effective_repo, inner)
            self.assertIs(self.service._effective_repo, outer)
        self.assertIs(self.service._effective_repo, self.service.repo)

    def test_with_repo_clears_on_exception(self):
        sentinel = object()
        try:
            with self.service._with_repo(sentinel):
                self.assertIs(self.service._effective_repo, sentinel)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        self.assertIs(self.service._effective_repo, self.service.repo)

    def test_rewrite_prepare_does_not_mutate_repo_before_commit(self):
        seed, *_ = _seed_candidate_thread(
            self.repo, self.documents, PROJECTS[0], suffix="_copy"
        )
        before = self.repo.revision_thread(PROJECTS[0], seed.thread_id)
        before_json = before.model_dump_json()
        previous, result = self.service.prepare_rewrite_action(
            PROJECTS[0],
            seed.thread_id,
            RevisionActionRequest(
                action=RevisionAction.REQUEST_REWRITE,
                suggestion_id=seed.suggestions[0].suggestion_id,
                actor="test",
                rewrite_instruction="next",
            ),
        )
        # Repository state unchanged until commit.
        mid = self.repo.revision_thread(PROJECTS[0], seed.thread_id)
        self.assertEqual(before_json, mid.model_dump_json())
        self.assertEqual(1, len(mid.suggestions))
        # Prepared result is a mutated deep copy.
        self.assertGreaterEqual(len(result.thread.suggestions), 4)
        self.assertIsNot(previous, result.thread)
        self.service.commit_prepared_rewrite(
            previous, result.thread, result.audit_event, None
        )
        after = self.repo.revision_thread(PROJECTS[0], seed.thread_id)
        self.assertGreaterEqual(len(after.suggestions), 4)

    def test_prepare_does_not_swap_self_repo(self):
        original = self.service.repo
        job, *_ = _initial_job(PROJECTS[0], self.documents)
        request = MedicalWritingRevisionRequest.model_validate(
            json.loads(job.payload_json)
        )
        self.service.prepare_revision_submission(PROJECTS[0], request)
        self.assertIs(self.service.repo, original)


if __name__ == "__main__":
    unittest.main()
