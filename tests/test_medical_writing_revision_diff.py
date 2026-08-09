from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from hashlib import sha256

from packages.contracts.workbench_contracts import (
    RevisionDiffSegment,
    RevisionAcceptAndApplyRequest,
    RevisionSuggestion,
    RevisionThread,
)
from services.api.app.medical_writing_revision_diff import build_revision_diff
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository


class RevisionDiffContractTests(unittest.TestCase):
    def test_replacement_is_stable_delete_then_insert(self):
        result = build_revision_diff("研究药物为A。", "研究药物为B。")
        self.assertEqual(
            ["equal", "delete", "insert", "equal"],
            [item.operation for item in result.segments],
        )
        self.assertEqual(
            ["A", "B"],
            [item.text for item in result.segments if item.operation != "equal"],
        )
        self.assertEqual(
            sha256("研究药物为A。".encode()).hexdigest(), result.source_hash
        )

    def test_new_suggestion_diff_identity_is_checked_against_thread_selection(self):
        diff = build_revision_diff("原文", "候选")
        suggestion = RevisionSuggestion(
            suggestion_id="sug_diff_contract",
            proposal_text="候选",
            diff_patch="legacy display patch",
            rationale="确定性合同测试",
            diff_segments=list(diff.segments),
            diff_source_hash=diff.source_hash,
            diff_proposal_hash=diff.proposal_hash,
            impact_status="known",
        )
        thread = RevisionThread(
            thread_id="thread_diff_contract",
            project_id="proj_diff_contract",
            document_id="doc_diff_contract",
            section_id="sec_diff_contract",
            anchor_type="paragraph",
            anchor_path="block:1",
            selected_text="原文",
            user_instruction="润色",
            intent="polish",
            ai_run_id="run_diff_contract",
            suggestions=[suggestion],
            created_at=datetime.now(timezone.utc),
        )
        self.assertEqual(diff.source_hash, thread.selected_hash)

        with self.assertRaises(ValueError):
            RevisionSuggestion(
                suggestion_id="sug_bad_diff_contract",
                proposal_text="候选",
                diff_patch="legacy display patch",
                rationale="tamper",
                diff_segments=list(diff.segments),
                diff_source_hash=diff.source_hash,
                diff_proposal_hash=sha256("篡改".encode()).hexdigest(),
                impact_status="known",
            )

    def test_diff_segments_must_be_paired_with_both_hashes(self):
        with self.assertRaises(ValueError):
            RevisionSuggestion(
                suggestion_id="sug_unbound_segments",
                proposal_text="候选",
                diff_patch="legacy display patch",
                rationale="tamper",
                diff_segments=[
                    RevisionDiffSegment(
                        operation="insert",
                        source_start=0,
                        source_end=0,
                        proposal_start=0,
                        proposal_end=1,
                        text="伪",
                    )
                ],
            )

    def test_protected_token_status_requires_bound_diff_and_issues(self):
        with self.assertRaises(ValueError):
            RevisionSuggestion(
                suggestion_id="sug_unbound_protected_tokens",
                proposal_text="候选 5 mg",
                diff_patch="legacy display patch",
                rationale="protected token contract",
                protected_token_status="violated",
            )
        diff = build_revision_diff("剂量 5 mg。", "剂量 10 g。")
        suggestion = RevisionSuggestion(
            suggestion_id="sug_bound_protected_tokens",
            proposal_text="剂量 10 g。",
            diff_patch="legacy display patch",
            rationale="protected token contract",
            diff_segments=list(diff.segments),
            diff_source_hash=diff.source_hash,
            diff_proposal_hash=diff.proposal_hash,
            impact_status="known",
            protected_token_status="violated",
            protected_token_issues=[
                {
                    "kind": "numeric_unit",
                    "source_text": "5 mg",
                    "reason_code": "protected_token_missing",
                    "message": "missing",
                }
            ],
        )
        self.assertEqual("violated", suggestion.protected_token_status)

    def test_legacy_suggestion_without_protected_token_fields_remains_readable(self):
        suggestion = RevisionSuggestion(
            suggestion_id="sug_legacy_protected_tokens",
            proposal_text="历史候选",
            diff_patch="legacy display patch",
            rationale="legacy",
        )
        self.assertEqual("legacy_unavailable", suggestion.protected_token_status)
        self.assertEqual([], suggestion.protected_token_issues)

    def test_thread_rejects_forged_protected_token_status(self):
        source = "剂量 5 mg。"
        proposal = "剂量 10 g。"
        diff = build_revision_diff(source, proposal)
        suggestion = RevisionSuggestion(
            suggestion_id="sug_forged_protected_status",
            proposal_text=proposal,
            diff_patch="legacy display patch",
            rationale="tamper",
            diff_segments=list(diff.segments),
            diff_source_hash=diff.source_hash,
            diff_proposal_hash=diff.proposal_hash,
            impact_status="known",
            protected_token_status="verified",
        )
        with self.assertRaisesRegex(ValueError, "protected-token status"):
            RevisionThread(
                thread_id="thread_forged_protected_status",
                project_id="proj_forged_protected_status",
                document_id="doc_forged_protected_status",
                section_id="sec_forged_protected_status",
                anchor_type="paragraph",
                anchor_path="block:1",
                selected_text=source,
                user_instruction="润色",
                intent="polish",
                ai_run_id="run_forged_protected_status",
                suggestions=[suggestion],
                created_at=datetime.now(timezone.utc),
            )

    def test_accept_and_apply_request_has_nonnegative_revision_and_idempotency_contract(self):
        request = RevisionAcceptAndApplyRequest(
            suggestion_id=" sug_1 ",
            expected_working_copy_revision=0,
            actor=" medical_manager ",
            idempotency_key=" apply-123 ",
        )
        self.assertEqual("sug_1", request.suggestion_id)
        self.assertEqual("medical_manager", request.actor)
        self.assertEqual("apply-123", request.idempotency_key)
        with self.assertRaises(ValueError):
            RevisionAcceptAndApplyRequest(
                suggestion_id="sug_1",
                expected_working_copy_revision=-1,
                idempotency_key="apply-123",
            )
        with self.assertRaises(ValueError):
            RevisionAcceptAndApplyRequest(
                suggestion_id="sug_1",
                expected_working_copy_revision=0,
                idempotency_key="short",
            )

    def test_thread_rejects_forged_segment_text_even_when_hashes_match(self):
        diff = build_revision_diff("原文", "候选")
        forged = [segment.model_copy() for segment in diff.segments]
        forged[0] = forged[0].model_copy(update={"text": "伪文"})
        suggestion = RevisionSuggestion(
            suggestion_id="sug_forged_segments",
            proposal_text="候选",
            diff_patch="legacy display patch",
            rationale="tamper",
            diff_segments=forged,
            diff_source_hash=diff.source_hash,
            diff_proposal_hash=diff.proposal_hash,
            impact_status="known",
        )
        with self.assertRaises(ValueError):
            RevisionThread(
                thread_id="thread_forged_segments",
                project_id="proj_forged_segments",
                document_id="doc_forged_segments",
                section_id="sec_forged_segments",
                anchor_type="paragraph",
                anchor_path="block:1",
                selected_text="原文",
                user_instruction="润色",
                intent="polish",
                ai_run_id="run_forged_segments",
                suggestions=[suggestion],
                created_at=datetime.now(timezone.utc),
            )

    def test_impact_projection_uses_only_shared_source_fact_ids(self):
        target_block = {
            "block_id": "block_target",
            "source_locator": "loc_target",
            "block_type": "paragraph",
            "source_fact_ids": ["fact:design.randomized"],
        }
        downstream_block = {
            "block_id": "block_downstream",
            "source_locator": "loc_downstream",
            "block_type": "paragraph",
            "source_fact_ids": ["fact:design.randomized"],
        }
        unrelated_block = {
            "block_id": "block_unrelated",
            "source_locator": "loc_unrelated",
            "block_type": "paragraph",
            "source_fact_ids": ["fact:other"],
        }
        document = SimpleNamespace(
            document_id="doc_impact",
            sections=[
                SimpleNamespace(section_id="sec_target", content_blocks=[target_block]),
                SimpleNamespace(
                    section_id="sec_downstream",
                    content_blocks=[downstream_block],
                ),
                SimpleNamespace(
                    section_id="sec_unrelated",
                    content_blocks=[unrelated_block],
                ),
            ],
        )
        target_wc = SimpleNamespace(section_id="sec_target", content_blocks=[target_block])
        downstream_wc = SimpleNamespace(
            section_id="sec_downstream", content_blocks=[downstream_block]
        )
        store = SimpleNamespace(
            medical_writing_working_copies_for_document=lambda *_: [downstream_wc]
        )
        repo = object.__new__(MedicalWritingRuntimeRepository)
        repo.runtime_store = store
        repo.project = lambda *_: document
        repo.working_copy = lambda *_: target_wc
        repo.document_service = SimpleNamespace(
            section=lambda _project_id, requested_section_id: next(
                section
                for section in document.sections
                if section.section_id == requested_section_id
            )
        )

        status, refs = repo.revision_impact_projection(
            "proj_impact", "sec_target", "loc_target"
        )
        self.assertEqual("known", status)
        self.assertEqual(
            {"block_target", "block_downstream"},
            {ref.block_id for ref in refs},
        )
        self.assertFalse(any(ref.block_id == "block_unrelated" for ref in refs))

    def test_missing_source_fact_and_external_evidence_are_unresolved(self):
        target = {"block_id": "block_no_fact", "source_locator": "loc", "block_type": "paragraph"}
        document = SimpleNamespace(
            document_id="doc_unresolved",
            sections=[SimpleNamespace(section_id="sec", content_blocks=[target])],
        )
        target_wc = SimpleNamespace(section_id="sec", content_blocks=[target])
        repo = object.__new__(MedicalWritingRuntimeRepository)
        repo.runtime_store = SimpleNamespace(
            medical_writing_working_copies_for_document=lambda *_: []
        )
        repo.project = lambda *_: document
        repo.working_copy = lambda *_: target_wc
        status, refs = repo.revision_impact_projection(
            "proj_unresolved",
            "sec",
            "loc",
            evidence_brief_ids=["brief_external"],
        )
        self.assertEqual("unresolved", status)
        self.assertIn(
            "source_fact_identity_missing", {ref.reason_code for ref in refs}
        )
        self.assertIn(
            "external_evidence_dependency_not_indexed",
            {ref.reason_code for ref in refs},
        )

    def test_unreadable_sibling_section_is_fail_closed(self):
        target_block = {
            "block_id": "block_target",
            "source_locator": "loc_target",
            "block_type": "paragraph",
            "source_fact_ids": ["fact:design.randomized"],
        }
        document = SimpleNamespace(
            document_id="doc_unreadable_sibling",
            sections=[
                SimpleNamespace(section_id="sec_target", content_blocks=[target_block]),
                SimpleNamespace(section_id="sec_sibling", content_blocks=[]),
            ],
        )
        target_wc = SimpleNamespace(section_id="sec_target", content_blocks=[target_block])
        repo = object.__new__(MedicalWritingRuntimeRepository)
        repo.runtime_store = SimpleNamespace(
            medical_writing_working_copies_for_document=lambda *_: []
        )
        repo.project = lambda *_: document
        repo.working_copy = lambda *_: target_wc

        def unreadable_section(*_args):
            raise RuntimeError("section index unavailable")

        repo.document_service = SimpleNamespace(section=unreadable_section)
        status, refs = repo.revision_impact_projection(
            "proj_unreadable_sibling", "sec_target", "loc_target"
        )
        self.assertEqual("unresolved", status)
        self.assertIn(
            "dependent_section_index_unavailable", {ref.reason_code for ref in refs}
        )


if __name__ == "__main__":
    unittest.main()
