from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from packages.contracts.workbench_contracts import (
    AuditEvent,
    MedicalWritingRevisionApplyRequest,
    MedicalWritingTableCellAnchor,
    MedicalWritingWorkingCopySaveRequest,
    RevisionAction,
    RevisionActionRequest,
    RevisionSuggestion,
    RevisionThread,
)
from services.api.app.medical_writing import MedicalWritingRevisionService
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import RuntimeStoreError, SqliteRuntimeStore, StaleRuntimeStateError


PROJECTS = ("proj_rux_03_002", "proj_d001", "proj_my008_pnh_3_01")


class MedicalWritingRevisionApplicationTests(unittest.TestCase):
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
        proposal_text = f"{selected_text}（医学经理选用的修订{suffix}）"
        now = datetime.now(timezone.utc)
        thread_id = f"thread_apply_{project_id}{suffix}"
        suggestion = RevisionSuggestion(
            suggestion_id=f"suggestion_{project_id}{suffix}",
            proposal_text=proposal_text,
            diff_patch=f"- {selected_text}\n+ {proposal_text}",
            rationale="保持原意并形成可追溯的待应用修订。",
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
            ai_run_id=f"run_{project_id}{suffix}",
            source_entry_id=f"entry_{project_id}{suffix}",
            source_id=f"source_{project_id}{suffix}",
            source_locator=block["source_locator"],
            evidence_source_types=["approved_competitor_protocol_evidence"],
            suggestions=[suggestion],
            status="candidate_ready",
            created_at=now,
        )
        self.repo.commit_revision_submission(
            thread,
            AuditEvent(
                audit_id=f"audit_submit_{project_id}{suffix}",
                project_id=project_id,
                actor="medical_manager_test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread_id,
                created_at=now,
            ),
        )
        accepted = self.revision_service.apply_action(
            project_id,
            thread_id,
            RevisionActionRequest(
                action=RevisionAction.ACCEPT,
                suggestion_id=suggestion.suggestion_id,
                actor="medical_manager_test",
            ),
        ).thread
        return document, section, block, selected_text, proposal_text, accepted

    def test_three_real_protocols_apply_only_the_approved_selection_to_a_new_revision(self):
        for project_id in PROJECTS:
            with self.subTest(project_id=project_id):
                document, section, block, selected_text, proposal_text, _ = self._approved_thread(project_id)
                original_section = self.documents.section(project_id, section.section_id).model_dump(mode="json")

                result = self.repo.apply_approved_revision_to_working_copy(
                    project_id,
                    section.section_id,
                    f"thread_apply_{project_id}",
                    MedicalWritingRevisionApplyRequest(
                        expected_working_copy_revision=0,
                        actor="medical_manager_test",
                        idempotency_key=f"apply-{project_id}",
                    ),
                )

                self.assertEqual(1, result.working_copy.revision)
                self.assertEqual(f"thread_apply_{project_id}", result.thread_id)
                self.assertEqual(f"suggestion_{project_id}", result.suggestion_id)
                self.assertIn(result.thread_id, result.working_copy.applied_revision_thread_ids)
                changed = next(
                    item
                    for item in result.working_copy.content_blocks
                    if item.get("source_locator") == block["source_locator"]
                )
                self.assertIn(proposal_text, changed["text"])
                self.assertNotIn(selected_text + selected_text, changed["text"])
                self.assertEqual(
                    original_section,
                    self.documents.section(project_id, section.section_id).model_dump(mode="json"),
                    "original parsed DOCX section must remain unchanged",
                )
                snapshots = self.store.medical_writing_working_copy_snapshots(
                    project_id,
                    result.working_copy.working_copy_id,
                )
                self.assertEqual("apply_approved_ai_revision", snapshots[-1]["snapshot_type"])
                self.assertEqual("medical_writing_revision_applied", result.audit_event.action)
                self.assertEqual(
                    ["approved_competitor_protocol_evidence"],
                    result.audit_event.detail["evidence_source_types"],
                )
                self.assertEqual(
                    "adopted_as_project_fact",
                    result.audit_event.detail["fact_adoption_status"],
                )
                self.assertEqual(
                    "medical_manager_explicit_selection",
                    result.audit_event.detail["adoption_basis"],
                )
                self.assertEqual(0, result.audit_event.detail["previous_working_copy_revision"])
                self.assertEqual(1, result.audit_event.detail["new_working_copy_revision"])
                stored_thread = self.repo.revision_thread(
                    project_id, f"thread_apply_{project_id}"
                )
                self.assertEqual(
                    RevisionThread.selected_text_hash(stored_thread.selected_text),
                    result.audit_event.detail["selected_hash"],
                )

    def test_atomic_apply_rejects_protected_token_change_without_mutating_state(self):
        project_id = PROJECTS[0]
        document = self.documents.document_session(project_id)
        section = block = block_text = match = None
        for summary in document.sections:
            candidate_section = self.documents.section(project_id, summary.section_id)
            for candidate_block in candidate_section.content_blocks:
                candidate_text = str(candidate_block.get("text", ""))
                candidate_match = next(
                    (
                        candidate
                        for candidate in re.finditer(
                            r"(?<![A-Za-z0-9])\d+(?![A-Za-z0-9])",
                            candidate_text,
                        )
                        if candidate_text.count(candidate.group(0)) == 1
                    ),
                    None,
                )
                if candidate_match and candidate_block.get("source_locator"):
                    section = candidate_section
                    block = candidate_block
                    block_text = candidate_text
                    match = candidate_match
                    break
            if match:
                break
        if not match or section is None or block is None or block_text is None:
            self.fail("no unique numeric source token available for protected-token regression")
        selected_text = match.group(0)
        proposal_text = "999999"
        now = datetime.now(timezone.utc)
        thread_id = "thread_protected_token_reject"
        suggestion_id = "suggestion_protected_token_reject"
        thread = RevisionThread(
            thread_id=thread_id,
            project_id=project_id,
            document_id=document.document_id,
            section_id=section.section_id,
            anchor_type="selection",
            anchor_path=block["source_locator"],
            selected_text=selected_text,
            user_instruction="仅用于合同回归",
            intent="polish",
            ai_run_id="run_protected_token_reject",
            source_locator=block["source_locator"],
            suggestions=[
                RevisionSuggestion(
                    suggestion_id=suggestion_id,
                    proposal_text=proposal_text,
                    diff_patch=f"- {selected_text}\n+ {proposal_text}",
                    rationale="合同回归",
                )
            ],
            status="candidate_ready",
            created_at=now,
        )
        self.repo.commit_revision_submission(
            thread,
            AuditEvent(
                audit_id="audit_submit_protected_token_reject",
                project_id=project_id,
                actor="medical_manager_test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread_id,
                created_at=now,
            ),
        )
        before_thread = self.repo.revision_thread(project_id, thread_id)
        before_copy = self.repo.working_copy(project_id, section.section_id)

        with self.assertRaisesRegex(RuntimeStoreError, "protected token mismatch"):
            self.repo.accept_and_apply_candidate(
                project_id=project_id,
                thread_id=thread_id,
                suggestion_id=suggestion_id,
                expected_working_copy_revision=before_copy.revision,
                actor="medical_manager_test",
                idempotency_key="protected-token-reject-once",
            )

        after_thread = self.repo.revision_thread(project_id, thread_id)
        after_copy = self.repo.working_copy(project_id, section.section_id)
        self.assertEqual("pending", after_thread.suggestions[0].user_decision)
        self.assertEqual(before_thread.model_dump(mode="json"), after_thread.model_dump(mode="json"))
        self.assertEqual(before_copy.revision, after_copy.revision)
        self.assertEqual(before_copy.content_blocks, after_copy.content_blocks)
        self.assertEqual(
            before_copy.applied_revision_thread_ids,
            after_copy.applied_revision_thread_ids,
        )

    def test_authoritative_thread_revalidates_selected_hash_before_any_apply(self):
        project_id = PROJECTS[0]
        document, section, _, _, _, accepted = self._approved_thread(project_id)
        tampered = accepted.model_copy(deep=True)
        tampered.selected_hash = "0" * 64

        with self.assertRaisesRegex(
            StaleRuntimeStateError, "selected range hash does not match"
        ):
            self.repo.require_authoritative_revision_thread(
                project_id, section.section_id, tampered
            )

    def test_structured_cross_reference_marks_are_protected(self):
        source = {
            "rich_text": {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "见表1",
                        "marks": [
                            {
                                "type": "crossReference",
                                "attrs": {"targetKind": "table", "targetId": "table1"},
                            }
                        ],
                    }
                ],
            }
        }
        preserved = {
            "rich_text": {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "见新表1",
                        "marks": [
                            {
                                "type": "crossReference",
                                "attrs": {"targetKind": "table", "targetId": "table1"},
                            }
                        ],
                    }
                ],
            }
        }
        removed = {
            "rich_text": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "见新表1"}],
            }
        }
        self.repo._assert_cross_reference_marks_preserved(source, preserved)
        with self.assertRaisesRegex(RuntimeStoreError, "protected structured table"):
            self.repo._assert_cross_reference_marks_preserved(source, removed)

    def test_rich_text_replacement_can_span_adjacent_formatted_text_nodes(self):
        rich_text = {
            "type": "paragraph",
            "attrs": {"stylePreset": "body"},
            "content": [
                {
                    "type": "text",
                    "text": "前文目标段落",
                    "marks": [{"type": "bold"}],
                },
                {
                    "type": "text",
                    "text": "继续内容后文",
                    "marks": [
                        {
                            "type": "textStyle",
                            "attrs": {"color": "#231F20"},
                        }
                    ],
                },
            ],
        }

        updated = self.repo._replace_in_rich_text(
            rich_text,
            "目标段落继续内容",
            "医学批准修订",
        )

        self.assertEqual(
            "前文医学批准修订后文",
            self.repo._rich_text_plain_text(updated),
        )
        self.assertEqual(
            [{"type": "bold"}],
            updated["content"][0]["marks"],
        )
        self.assertEqual(
            [{"type": "textStyle", "attrs": {"color": "#231F20"}}],
            updated["content"][1]["marks"],
        )

    def test_rich_text_replacement_still_rejects_structural_breaks(self):
        rich_text = {
            "type": "paragraph",
            "attrs": {"stylePreset": "body"},
            "content": [
                {"type": "text", "text": "第一行"},
                {"type": "hardBreak"},
                {"type": "text", "text": "第二行"},
            ],
        }

        with self.assertRaisesRegex(RuntimeStoreError, "structural break"):
            self.repo._replace_in_rich_text(
                rich_text,
                "第一行\n第二行",
                "合并行",
            )

    def test_rich_text_doc_paragraph_boundary_is_preserved_for_local_replacement(self):
        rich_text = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "首段待润色内容"}],
                },
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "后续审核备注"}],
                },
            ],
        }

        updated = self.repo._replace_in_rich_text(
            rich_text,
            "首段待润色内容",
            "首段已完成医学润色",
        )

        self.assertEqual(
            "首段已完成医学润色\n后续审核备注",
            self.repo._rich_text_plain_text(updated),
        )
        self.assertEqual(
            "后续审核备注",
            updated["content"][1]["content"][0]["text"],
        )

    def test_rich_text_doc_paragraph_boundary_still_fails_closed_when_crossed(self):
        rich_text = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "首段"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "次段"}]},
            ],
        }

        with self.assertRaisesRegex(RuntimeStoreError, "structural break"):
            self.repo._replace_in_rich_text(rich_text, "首段\n次段", "合并为一段")

    def test_revision_selection_uses_current_working_copy_text_at_stable_locator(self):
        project_id = PROJECTS[0]
        document, section, block, _ = self._substantive_section(project_id)
        current = self.repo.working_copy(project_id, section.section_id)
        blocks = [dict(item) for item in current.content_blocks]
        target = next(
            item for item in blocks if item.get("source_locator") == block["source_locator"]
        )
        target["text"] = "当前工作副本已由医学经理修订，后续AI应基于该版本继续精调。"
        target["rich_text"] = {
            "type": "paragraph",
            "content": [{"type": "text", "text": target["text"]}],
        }
        self.repo.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=document.document_id,
                expected_revision=0,
                content_blocks=blocks,
                actor="medical_manager_test",
                idempotency_key="save-current-selection",
            ),
        )

        selected_text, locator = self.repo.normalize_revision_selection(
            project_id,
            section.section_id,
            target["text"],
            block["source_locator"],
        )

        self.assertEqual(target["text"], selected_text)
        self.assertEqual(block["source_locator"], locator)
        with self.assertRaisesRegex(ValueError, "current working-copy block"):
            self.repo.normalize_revision_selection(
                project_id,
                section.section_id,
                str(block["text"]),
                block["source_locator"],
            )

    def test_ambiguous_revision_selection_fails_closed_before_ai_submission(self):
        project_id = PROJECTS[0]
        document, section, block, _ = self._substantive_section(project_id)
        current = self.repo.working_copy(project_id, section.section_id)
        blocks = [dict(item) for item in current.content_blocks]
        target = next(
            item for item in blocks if item.get("source_locator") == block["source_locator"]
        )
        target["text"] = "aaaa；重复选区词语位于段首，随后再次出现重复选区词语。"
        target["rich_text"] = {
            "type": "paragraph",
            "content": [{"type": "text", "text": target["text"]}],
        }
        self.repo.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=document.document_id,
                expected_revision=0,
                content_blocks=blocks,
                actor="medical_manager_test",
                idempotency_key="save-ambiguous-selection",
            ),
        )

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.repo.normalize_revision_selection(
                project_id,
                section.section_id,
                "aaa",
                block["source_locator"],
            )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.repo.normalize_revision_selection(
                project_id,
                section.section_id,
                "重复选区词语",
                block["source_locator"],
            )
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            self.repo.normalize_revision_selection(
                project_id,
                section.section_id,
                "重复选区词语",
                "",
            )

        matching_blocks = [
            item
            for item in blocks
            if str(item.get("text", "")).strip()
        ]
        second = next(
            item
            for item in matching_blocks
            if item.get("source_locator") != block["source_locator"]
        )
        second["text"] = "另一个段落也包含重复选区词语。"
        second["rich_text"] = {
            "type": "paragraph",
            "content": [{"type": "text", "text": second["text"]}],
        }
        self.repo.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=document.document_id,
                expected_revision=1,
                content_blocks=blocks,
                actor="medical_manager_test",
                idempotency_key="save-ambiguous-selection-cross-block",
            ),
        )
        with self.assertRaisesRegex(ValueError, "multiple current working-copy blocks"):
            self.repo.normalize_revision_selection(
                project_id,
                section.section_id,
                "重复选区词语",
                "",
            )

    def test_replay_is_idempotent_but_second_business_application_is_rejected(self):
        project_id = PROJECTS[0]
        _, section, _, _, _, accepted_thread = self._approved_thread(project_id)
        request = MedicalWritingRevisionApplyRequest(
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="apply-rux-once",
        )
        first = self.repo.apply_approved_revision_to_working_copy(
            project_id, section.section_id, f"thread_apply_{project_id}", request
        )
        legacy_fingerprint = self.repo._payload_hash(
            {
                "project_id": project_id,
                "document_id": first.working_copy.document_id,
                "section_id": section.section_id,
                "thread_id": accepted_thread.thread_id,
                "suggestion_id": accepted_thread.suggestions[0].suggestion_id,
                "expected_working_copy_revision": 0,
                "actor": "medical_manager_test",
                "citation_bindings": self.repo._accepted_revision_citation_bindings(
                    project_id,
                    accepted_thread,
                    accepted_thread.suggestions[0],
                ),
            }
        )
        with sqlite3.connect(self.store.db_path) as connection:
            connection.execute(
                """
                UPDATE idempotency_records
                SET request_hash = ?
                WHERE project_id = ?
                  AND operation = 'medical_writing_approved_revision_apply'
                  AND idempotency_key = ?
                """,
                (legacy_fingerprint, project_id, request.idempotency_key),
            )
            connection.commit()
        later = self.repo.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=first.working_copy.document_id,
                expected_revision=1,
                content_blocks=first.working_copy.content_blocks,
                actor="medical_manager_test",
                idempotency_key="save-after-application",
            ),
        )
        replay = self.repo.apply_approved_revision_to_working_copy(
            project_id, section.section_id, f"thread_apply_{project_id}", request
        )
        self.assertEqual(first.working_copy.revision, replay.working_copy.revision)
        self.assertEqual(2, later.revision)
        self.assertEqual(2, self.repo.working_copy(project_id, section.section_id).revision)
        with self.assertRaisesRegex(RuntimeStoreError, "already applied"):
            self.repo.apply_approved_revision_to_working_copy(
                project_id,
                section.section_id,
                f"thread_apply_{project_id}",
                MedicalWritingRevisionApplyRequest(
                    expected_working_copy_revision=2,
                    actor="medical_manager_test",
                    idempotency_key="apply-rux-again",
                ),
            )

    def test_stale_revision_and_unselected_thread_fail_without_a_partial_write(self):
        project_id = PROJECTS[1]
        _, section, _, _, _, _ = self._approved_thread(project_id)
        with self.assertRaises(StaleRuntimeStateError):
            self.repo.apply_approved_revision_to_working_copy(
                project_id,
                section.section_id,
                f"thread_apply_{project_id}",
                MedicalWritingRevisionApplyRequest(
                    expected_working_copy_revision=2,
                    actor="medical_manager_test",
                    idempotency_key="apply-stale",
                ),
            )
        self.assertEqual(0, self.repo.working_copy(project_id, section.section_id).revision)

        document, pending_section, block, selected_text = self._substantive_section(PROJECTS[2])
        now = datetime.now(timezone.utc)
        pending = RevisionThread(
            thread_id="thread_pending_pnh",
            project_id=PROJECTS[2],
            document_id=document.document_id,
            section_id=pending_section.section_id,
            anchor_type="selection",
            anchor_path=block["source_locator"],
            selected_text=selected_text[:40],
            user_instruction="待审核",
            intent="regulatory_tone",
            ai_run_id="run_pending_pnh",
            suggestions=[RevisionSuggestion(
                suggestion_id="suggestion_pending_pnh",
                proposal_text="尚未选择的建议",
                diff_patch="",
                rationale="待审核",
            )],
            status="candidate_ready",
            created_at=now,
        )
        self.repo.commit_revision_submission(
            pending,
            AuditEvent(
                audit_id="audit_pending_pnh",
                project_id=PROJECTS[2],
                actor="medical_manager_test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=pending.thread_id,
                created_at=now,
            ),
        )
        with self.assertRaisesRegex(RuntimeStoreError, "not been selected"):
            self.repo.apply_approved_revision_to_working_copy(
                PROJECTS[2],
                pending_section.section_id,
                pending.thread_id,
                MedicalWritingRevisionApplyRequest(
                    expected_working_copy_revision=0,
                    actor="medical_manager_test",
                    idempotency_key="apply-pending-pnh",
                ),
            )
        self.assertEqual(0, self.repo.working_copy(PROJECTS[2], pending_section.section_id).revision)

    def test_cross_section_and_anchor_drift_fail_closed(self):
        project_id = PROJECTS[0]
        _, section, _, _, _, accepted = self._approved_thread(project_id, suffix="_drift")
        other_section = next(
            item
            for item in self.documents.document_session(project_id).sections
            if item.section_id != section.section_id
        )
        with self.assertRaisesRegex(RuntimeStoreError, "section"):
            self.repo.apply_approved_revision_to_working_copy(
                project_id,
                other_section.section_id,
                f"thread_apply_{project_id}_drift",
                MedicalWritingRevisionApplyRequest(
                    expected_working_copy_revision=0,
                    actor="medical_manager_test",
                    idempotency_key="apply-cross-section",
                ),
            )

        current = self.repo.working_copy(project_id, section.section_id)
        drifted_blocks = [dict(item) for item in current.content_blocks]
        target = next(
            item
            for item in drifted_blocks
            if item.get("source_locator") == accepted.anchor_path
        )
        target["text"] = "该段已由医学经理手工重写，原选中文本不再存在。"
        target["rich_text"] = {
            **target["rich_text"],
            "content": [{"type": "text", "text": target["text"]}],
        }
        self.repo.save_working_copy(
            project_id,
            section.section_id,
            request=MedicalWritingWorkingCopySaveRequest(
                document_id=current.document_id,
                expected_revision=0,
                content_blocks=drifted_blocks,
                actor="medical_manager_test",
                idempotency_key="manual-drift",
            ),
        )
        with self.assertRaisesRegex(RuntimeStoreError, "selected text"):
            self.repo.apply_approved_revision_to_working_copy(
                project_id,
                section.section_id,
                f"thread_apply_{project_id}_drift",
                MedicalWritingRevisionApplyRequest(
                    expected_working_copy_revision=1,
                    actor="medical_manager_test",
                    idempotency_key="apply-after-drift",
                ),
            )
        self.assertEqual(1, self.repo.working_copy(project_id, section.section_id).revision)

    def test_rich_text_marks_are_preserved_across_single_and_adjacent_nodes(self):
        project_id = PROJECTS[1]
        document, section, block, selected_text, proposal_text, accepted = self._approved_thread(
            project_id, suffix="_rich"
        )
        blocks = [dict(item) for item in self.repo.working_copy(project_id, section.section_id).content_blocks]
        target = next(item for item in blocks if item.get("source_locator") == accepted.anchor_path)
        target["rich_text"] = {
            "type": "paragraph",
            "content": [{"type": "text", "text": target["text"], "marks": [{"type": "bold"}]}],
        }
        self.repo.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=document.document_id,
                expected_revision=0,
                content_blocks=blocks,
                actor="medical_manager_test",
                idempotency_key="save-rich-text-d001",
            ),
        )
        applied = self.repo.apply_approved_revision_to_working_copy(
            project_id,
            section.section_id,
            accepted.thread_id,
            MedicalWritingRevisionApplyRequest(
                expected_working_copy_revision=1,
                actor="medical_manager_test",
                idempotency_key="apply-rich-text-d001",
            ),
        )
        changed = next(
            item
            for item in applied.working_copy.content_blocks
            if item.get("source_locator") == accepted.anchor_path
        )
        self.assertIn(proposal_text, changed["text"])
        self.assertEqual([{"type": "bold"}], changed["rich_text"]["content"][0]["marks"])
        self.assertTrue(applied.audit_event.detail["formatting_preserved"])
        self.assertNotEqual(
            applied.audit_event.detail["before_block_hash"],
            applied.audit_event.detail["after_block_hash"],
        )

        project_id = PROJECTS[2]
        document, section, block, selected_text, proposal_text, accepted = self._approved_thread(
            project_id, suffix="_cross_node"
        )
        blocks = [dict(item) for item in self.repo.working_copy(project_id, section.section_id).content_blocks]
        target = next(item for item in blocks if item.get("source_locator") == accepted.anchor_path)
        split_at = max(1, len(selected_text) // 2)
        target["rich_text"] = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": target["text"][:split_at], "marks": [{"type": "bold"}]},
                {"type": "text", "text": target["text"][split_at:]},
            ],
        }
        self.repo.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=document.document_id,
                expected_revision=0,
                content_blocks=blocks,
                actor="medical_manager_test",
                idempotency_key="save-cross-node-pnh",
            ),
        )
        cross_node_applied = self.repo.apply_approved_revision_to_working_copy(
            project_id,
            section.section_id,
            accepted.thread_id,
            MedicalWritingRevisionApplyRequest(
                expected_working_copy_revision=1,
                actor="medical_manager_test",
                idempotency_key="apply-cross-node-pnh",
            ),
        )
        cross_node_changed = next(
            item
            for item in cross_node_applied.working_copy.content_blocks
            if item.get("source_locator") == accepted.anchor_path
        )
        self.assertEqual(2, cross_node_applied.working_copy.revision)
        self.assertIn(proposal_text, cross_node_changed["text"])
        self.assertEqual(
            cross_node_changed["text"],
            self.repo._rich_text_plain_text(cross_node_changed["rich_text"]),
        )
        self.assertEqual(
            [{"type": "bold"}],
            cross_node_changed["rich_text"]["content"][0]["marks"],
        )

    def test_application_fault_rolls_back_copy_snapshot_audit_and_idempotency(self):
        project_id = PROJECTS[0]
        _, section, _, _, _, accepted = self._approved_thread(project_id, suffix="_fault")

        def fail(checkpoint: str):
            if checkpoint == "after_working_copy_snapshot":
                raise RuntimeError("apply transaction fault")

        failing_repo = MedicalWritingRuntimeRepository(
            self.documents,
            SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3", fault_injector=fail),
        )
        request = MedicalWritingRevisionApplyRequest(
            expected_working_copy_revision=0,
            actor="medical_manager_test",
            idempotency_key="apply-transaction-fault",
        )
        with self.assertRaisesRegex(RuntimeError, "apply transaction fault"):
            failing_repo.apply_approved_revision_to_working_copy(
                project_id,
                section.section_id,
                accepted.thread_id,
                request,
            )

        self.assertEqual(0, self.repo.working_copy(project_id, section.section_id).revision)
        applied_events = [
            event
            for event in self.store.workflow_audit_events(
                project_id, "medical_writing_working_copy"
            )
            if event.action == "medical_writing_revision_applied"
        ]
        self.assertEqual([], applied_events)
        successful = self.repo.apply_approved_revision_to_working_copy(
            project_id,
            section.section_id,
            accepted.thread_id,
            request,
        )
        self.assertEqual(1, successful.working_copy.revision)


def _table_block(suffix: str = "tc") -> dict:
    """Build a minimal table content block for table-cell revision tests."""
    block_id = f"block_{suffix}_table"
    table_id = f"table_{suffix}"
    row_ids = [f"row_{suffix}_h", f"row_{suffix}_1"]
    column_ids = [f"col_{suffix}_0", f"col_{suffix}_1"]
    values = [["类型", "名称"], ["主要", f"{suffix}原始主要终点文本"]]
    rows = []
    for ri, vals in enumerate(values):
        rows.append([
            {
                "cell_id": f"cell_{suffix}_{ri}_{ci}",
                "text": val,
                "grid_column_index": ci,
                "row_span": 1,
                "column_span": 1,
                "hidden": False,
                "style_role": "header" if ri == 0 else "body",
                "source_locator": f"docx:table:1:r{ri}:c{ci}",
                "structure_row_id": row_ids[ri],
                "structure_column_id": column_ids[ci],
            }
            for ci, val in enumerate(vals)
        ])
    return {
        "block_id": block_id,
        "block_type": "table",
        "table_id": table_id,
        "title": "终点表",
        "source_locator": "docx:table:1",
        "header_row_count": 1,
        "column_count": 2,
        "rows": rows,
        "structured_table": {
            "schema_version": "structured_table_v1",
            "version": 0,
            "domain": "objectives_endpoints",
            "title": "终点表",
            "review_state": "ai_draft",
            "row_ids": row_ids,
            "row_labels": ["表头", "主要"],
            "row_style_roles": ["header", "body"],
            "column_ids": column_ids,
            "column_labels": ["类型", "名称"],
            "column_style_roles": ["header", "header"],
            "column_width_twips": [1800, 4800],
            "column_source_locators": ["docx:table:1:c0", "docx:table:1:c1"],
            "notes": [],
        },
    }


class TableCellAtomicAdoptionTests(unittest.TestCase):
    """P0-C: Table-cell atomic accept_and_apply_candidate tests."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        from packages.contracts.workbench_contracts import (
            ProtocolDocument,
            ProtocolSection,
        )
        # Build a custom document service with a table block.
        self.project_id = "proj_table_atomic"
        document_id = "doc_table_atomic"
        section = ProtocolSection(
            section_id="sec_table",
            document_id=document_id,
            heading="研究目的与终点",
            content_blocks=[
                {
                    "block_id": "block_para",
                    "block_type": "paragraph",
                    "text": "原始方案研究目的。",
                    "source_locator": "docx:paragraph:1",
                },
                _table_block("tc"),
            ],
        )
        document = ProtocolDocument(
            document_id=document_id,
            project_id=self.project_id,
            protocol_id="PROTOCOL-TC",
            version="V1.0",
            sections=[section],
        )

        class TableDocService:
            def document_session(self, pid):
                return document

            def document_for_revision(self, pid):
                return document

            def section(self, pid, sid):
                return next(
                    s for s in document.sections if s.section_id == sid
                )

        self.documents = TableDocService()
        self.store = SqliteRuntimeStore(Path(self.tmpdir.name) / "runtime.sqlite3")
        self.repo = MedicalWritingRuntimeRepository(self.documents, self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _save_initial_working_copy(self):
        """Save the initial working copy containing the table block."""
        document = self.documents.document_session(self.project_id)
        section = self.documents.section(self.project_id, "sec_table")
        self.repo.save_working_copy(
            self.project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=document.document_id,
                expected_revision=0,
                content_blocks=section.content_blocks,
                actor="test",
                idempotency_key="setup-table",
            ),
        )

    def _table_cell_thread(self, proposal_text):
        """Create and commit a candidate_ready table-cell revision thread."""
        document = self.documents.document_session(self.project_id)
        section = self.documents.section(self.project_id, "sec_table")
        table_blk = section.content_blocks[1]
        cell = table_blk["rows"][1][1]
        anchor_path = json.dumps(
            {
                "block_id": table_blk["block_id"],
                "table_id": table_blk["table_id"],
                "row_id": cell["structure_row_id"],
                "column_id": cell["structure_column_id"],
                "cell_id": cell["cell_id"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        # Get the block hash from the current working copy (after save).
        wc = self.repo.working_copy(self.project_id, section.section_id)
        current_table_blk = wc.content_blocks[1]
        block_hash = self.repo._payload_hash(current_table_blk)
        anchor = MedicalWritingTableCellAnchor(
            working_copy_revision=1,
            table_version=0,
            block_id=table_blk["block_id"],
            table_id=table_blk["table_id"],
            row_id=cell["structure_row_id"],
            column_id=cell["structure_column_id"],
            cell_id=cell["cell_id"],
            captured_text=cell["text"],
            block_hash=block_hash,
        )
        now = datetime.now(timezone.utc)
        thread = RevisionThread(
            thread_id="thread_tc_atomic",
            project_id=self.project_id,
            document_id=document.document_id,
            section_id=section.section_id,
            anchor_type="table_cell",
            anchor_path=anchor_path,
            selected_text=cell["text"],
            user_instruction="优化表格",
            intent="medical_writing_revision",
            ai_run_id="run_tc_atomic",
            source_entry_id="entry_tc",
            source_id="source_tc",
            source_locator=anchor_path,
            table_cell_anchor=anchor,
            evidence_source_types=["approved_competitor_protocol_evidence"],
            suggestions=[RevisionSuggestion(
                suggestion_id="sug_tc_atomic",
                proposal_text=proposal_text,
                diff_patch="cell diff",
                rationale="test table-cell proposal",
                evidence_span_ids=["span_tc"],
                evidence_source_types=["approved_competitor_protocol_evidence"],
            )],
            status="candidate_ready",
            created_at=now,
        )
        self.repo.commit_revision_submission(
            thread,
            AuditEvent(
                audit_id="audit_tc_submit",
                project_id=self.project_id,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=now,
            ),
        )
        return thread, section

    def _target_cell_snapshot(self, working_copy, thread):
        anchor = thread.table_cell_anchor
        block = next(
            b
            for b in working_copy.content_blocks
            if str(b.get("block_id", "")) == anchor.block_id
        )
        target = None
        non_targets = []
        for row in block["rows"]:
            for cell in row:
                if cell["cell_id"] == anchor.cell_id:
                    target = cell
                else:
                    non_targets.append(
                        {
                            "cell_id": cell["cell_id"],
                            "text": cell.get("text"),
                            "rich_text": cell.get("rich_text"),
                        }
                    )
        return block, target, non_targets

    def test_table_cell_atomic_success(self):
        """Table-cell atomic adoption updates exact target cell text/rich-text."""
        self._save_initial_working_copy()
        proposal = "tc原始主要终点文本（表格原子采纳）"
        thread, section = self._table_cell_thread(proposal)
        pre_wc = self.repo.working_copy(self.project_id, section.section_id)
        pre_block, pre_target, pre_non_targets = self._target_cell_snapshot(pre_wc, thread)
        self.assertIsNotNone(pre_target)
        original_text = pre_target["text"]

        result = self.repo.accept_and_apply_candidate(
            project_id=self.project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=1,
            actor="test",
            idempotency_key="tc-atomic-success",
        )
        self.assertEqual(2, result.working_copy.revision)
        self.assertIn(thread.thread_id, result.working_copy.applied_revision_thread_ids)
        updated = self.repo.revision_thread(self.project_id, thread.thread_id)
        self.assertEqual("author_selected", updated.status)
        self.assertEqual("accepted", updated.suggestions[0].user_decision)

        post_block, post_target, post_non_targets = self._target_cell_snapshot(
            result.working_copy, thread
        )
        self.assertEqual(proposal, post_target["text"])
        # Plain/rich consistency when rich_text present.
        if isinstance(post_target.get("rich_text"), dict):
            plain_from_rich = self.repo._table_cell_rich_text_plain_text(
                post_target["rich_text"]
            )
            self.assertEqual(proposal, plain_from_rich)
        # Non-target cells preserved.
        self.assertEqual(pre_non_targets, post_non_targets)
        # Table CAS version advances on edit.
        from services.api.app.medical_writing_tables import MedicalWritingTableService

        table_svc = MedicalWritingTableService()
        pre_version = table_svc.from_table_block(pre_block).version
        post_version = table_svc.from_table_block(post_block).version
        self.assertGreater(post_version, pre_version)
        # Source document section unchanged (working-copy only write).
        source_section = self.documents.section(self.project_id, section.section_id)
        source_cell = None
        for row in source_section.content_blocks[1]["rows"]:
            for cell in row:
                if cell["cell_id"] == thread.table_cell_anchor.cell_id:
                    source_cell = cell
        self.assertIsNotNone(source_cell)
        self.assertEqual(original_text, source_cell["text"])

    def test_table_cell_atomic_rejects_stale_revision(self):
        """Table-cell atomic adoption rejects stale expected revision."""
        self._save_initial_working_copy()
        thread, section = self._table_cell_thread("stale proposal")

        with self.assertRaises(StaleRuntimeStateError):
            self.repo.accept_and_apply_candidate(
                project_id=self.project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=99,
                actor="test",
                idempotency_key="tc-atomic-stale",
            )
        self.assertEqual(1, self.repo.working_copy(self.project_id, section.section_id).revision)

    def test_table_cell_atomic_rejects_block_hash_drift(self):
        self._save_initial_working_copy()
        thread, section = self._table_cell_thread("hash drift proposal")
        # Corrupt stored block_hash on the thread payload to force drift.
        stored = self.repo.revision_thread(self.project_id, thread.thread_id)
        corrupted = stored.model_copy(deep=True)
        corrupted.table_cell_anchor = corrupted.table_cell_anchor.model_copy(
            update={"block_hash": "0" * 64}
        )
        self.store.commit_medical_writing_revision_action(
            stored,
            corrupted,
            AuditEvent(
                audit_id="audit_corrupt_hash",
                project_id=self.project_id,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=datetime.now(timezone.utc),
            ),
            None,
        )
        # Re-set status to candidate_ready with pending suggestion for adopt path.
        # The action commit may have preserved suggestion state; re-read.
        with self.assertRaises(RuntimeStoreError):
            self.repo.accept_and_apply_candidate(
                project_id=self.project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=1,
                actor="test",
                idempotency_key="tc-hash-drift",
            )

    def test_table_cell_atomic_rejects_selected_text_drift(self):
        self._save_initial_working_copy()
        thread, section = self._table_cell_thread("text drift proposal")
        stored = self.repo.revision_thread(self.project_id, thread.thread_id)
        corrupted = stored.model_copy(deep=True)
        corrupted.selected_text = "not-the-cell-anymore"
        # Keep the payload internally self-consistent so the persistence layer
        # accepts the intentionally stale thread and the authoritative gate
        # can reject it against the live cell.
        corrupted.selected_hash = RevisionThread.selected_text_hash(
            corrupted.selected_text
        )
        self.store.commit_medical_writing_revision_action(
            stored,
            corrupted,
            AuditEvent(
                audit_id="audit_corrupt_text",
                project_id=self.project_id,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=datetime.now(timezone.utc),
            ),
            None,
        )
        with self.assertRaises(RuntimeStoreError):
            self.repo.accept_and_apply_candidate(
                project_id=self.project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=1,
                actor="test",
                idempotency_key="tc-text-drift",
            )

    def test_table_cell_atomic_rejects_wrong_cell_identity(self):
        self._save_initial_working_copy()
        thread, section = self._table_cell_thread("wrong cell")
        stored = self.repo.revision_thread(self.project_id, thread.thread_id)
        corrupted = stored.model_copy(deep=True)
        corrupted.table_cell_anchor = corrupted.table_cell_anchor.model_copy(
            update={"cell_id": "cell_does_not_exist"}
        )
        # Keep anchor_path in sync so path validation does not fail first.
        corrupted.anchor_path = json.dumps(
            {
                "block_id": corrupted.table_cell_anchor.block_id,
                "table_id": corrupted.table_cell_anchor.table_id,
                "row_id": corrupted.table_cell_anchor.row_id,
                "column_id": corrupted.table_cell_anchor.column_id,
                "cell_id": "cell_does_not_exist",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.store.commit_medical_writing_revision_action(
            stored,
            corrupted,
            AuditEvent(
                audit_id="audit_wrong_cell",
                project_id=self.project_id,
                actor="test",
                action="medical_writing_revision_submitted",
                target_type="revision_thread",
                target_id=thread.thread_id,
                created_at=datetime.now(timezone.utc),
            ),
            None,
        )
        with self.assertRaises(RuntimeStoreError):
            self.repo.accept_and_apply_candidate(
                project_id=self.project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=1,
                actor="test",
                idempotency_key="tc-wrong-cell",
            )

    def test_table_cell_atomic_idempotent_replay(self):
        """Idempotent replay returns equal working-copy identity/result."""
        self._save_initial_working_copy()
        proposal = "idem proposal exact"
        thread, section = self._table_cell_thread(proposal)

        first = self.repo.accept_and_apply_candidate(
            project_id=self.project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=1,
            actor="test",
            idempotency_key="tc-atomic-idem",
        )
        legacy_fingerprint = self.repo._payload_hash(
            {
                "project_id": self.project_id,
                "document_id": first.working_copy.document_id,
                "section_id": section.section_id,
                "thread_id": thread.thread_id,
                "suggestion_id": thread.suggestions[0].suggestion_id,
                "expected_working_copy_revision": 1,
                "actor": "test",
                "citation_bindings": [],
            }
        )
        with sqlite3.connect(self.store.db_path) as connection:
            connection.execute(
                """
                UPDATE idempotency_records
                SET request_hash = ?
                WHERE project_id = ?
                  AND operation = 'medical_writing_atomic_accept_and_apply'
                  AND idempotency_key = ?
                """,
                (legacy_fingerprint, self.project_id, "tc-atomic-idem"),
            )
            connection.commit()
        second = self.repo.accept_and_apply_candidate(
            project_id=self.project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=1,
            actor="test",
            idempotency_key="tc-atomic-idem",
        )
        self.assertEqual(first.working_copy.revision, second.working_copy.revision)
        self.assertEqual(
            first.working_copy.working_copy_id, second.working_copy.working_copy_id
        )
        _, cell_a, _ = self._target_cell_snapshot(first.working_copy, thread)
        _, cell_b, _ = self._target_cell_snapshot(second.working_copy, thread)
        self.assertEqual(proposal, cell_a["text"])
        self.assertEqual(cell_a["text"], cell_b["text"])

    def test_table_cell_atomic_replay_returns_immutable_snapshot_after_later_edit(self):
        self._save_initial_working_copy()
        thread, section = self._table_cell_thread("immutable replay proposal")
        first = self.repo.accept_and_apply_candidate(
            project_id=self.project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=1,
            actor="test",
            idempotency_key="tc-immutable-replay",
        )

        later = json.loads(
            json.dumps(
                self.repo.working_copy(self.project_id, section.section_id).content_blocks,
                ensure_ascii=False,
            )
        )
        paragraph = next(block for block in later if block.get("block_type") != "table")
        paragraph["text"] = f"{paragraph['text']}（后续人工编辑）"
        if isinstance(paragraph.get("rich_text"), dict):
            paragraph["rich_text"] = {
                **paragraph["rich_text"],
                "content": [{"type": "text", "text": paragraph["text"]}],
            }
        self.repo.save_working_copy(
            self.project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=self.documents.document_session(self.project_id).document_id,
                expected_revision=first.working_copy.revision,
                content_blocks=later,
                actor="test",
                idempotency_key="tc-later-edit",
            ),
        )

        replay = self.repo.accept_and_apply_candidate(
            project_id=self.project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=1,
            actor="test",
            idempotency_key="tc-immutable-replay",
        )
        self.assertEqual(first.working_copy.revision, replay.working_copy.revision)
        self.assertEqual(first.working_copy.content_blocks, replay.working_copy.content_blocks)
        self.assertNotEqual(
            self.repo.working_copy(self.project_id, section.section_id).revision,
            replay.working_copy.revision,
        )

    def test_table_cell_atomic_replay_fails_closed_when_immutable_snapshot_is_missing(self):
        self._save_initial_working_copy()
        thread, section = self._table_cell_thread("missing snapshot proposal")
        first = self.repo.accept_and_apply_candidate(
            project_id=self.project_id,
            thread_id=thread.thread_id,
            suggestion_id=thread.suggestions[0].suggestion_id,
            expected_working_copy_revision=1,
            actor="test",
            idempotency_key="tc-missing-snapshot",
        )
        apply_audit_id = first.audit_event.audit_id
        with sqlite3.connect(self.store.db_path) as connection:
            # The production trigger intentionally makes snapshots immutable;
            # this temp-DB-only removal simulates storage loss so replay must
            # fail closed rather than returning the mutable current state.
            connection.execute(
                "DROP TRIGGER trg_medical_writing_working_copy_snapshot_no_delete"
            )
            connection.execute(
                """
                DELETE FROM medical_writing_working_copy_snapshots
                WHERE project_id = ? AND snapshot_id = ?
                """,
                (
                    self.project_id,
                    f"snapshot_{apply_audit_id}",
                ),
            )
            connection.commit()

        with self.assertRaisesRegex(RuntimeStoreError, "immutable application snapshot"):
            self.repo.accept_and_apply_candidate(
                project_id=self.project_id,
                thread_id=thread.thread_id,
                suggestion_id=thread.suggestions[0].suggestion_id,
                expected_working_copy_revision=1,
                actor="test",
                idempotency_key="tc-missing-snapshot",
            )

    def test_table_cell_atomic_fault_rolls_back_multiple_checkpoints(self):
        """Injected faults at several transaction boundaries leave no residue."""
        checkpoints = [
            "atomic_after_thread_write",
            "atomic_after_thread_snapshot",
            "atomic_after_accept_audit",
            "atomic_after_wc_write",
            "atomic_after_wc_snapshot",
            "atomic_after_idempotency",
        ]
        for checkpoint in checkpoints:
            with self.subTest(checkpoint=checkpoint):
                # Fresh store/repo per subtest to avoid residual injector state.
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                store = SqliteRuntimeStore(Path(tmp.name) / "runtime.sqlite3")
                repo = MedicalWritingRuntimeRepository(self.documents, store)
                # Save WC into this store.
                document = self.documents.document_session(self.project_id)
                section = self.documents.section(self.project_id, "sec_table")
                repo.save_working_copy(
                    self.project_id,
                    section.section_id,
                    MedicalWritingWorkingCopySaveRequest(
                        document_id=document.document_id,
                        expected_revision=0,
                        content_blocks=section.content_blocks,
                        actor="test",
                        idempotency_key=f"setup-{checkpoint}",
                    ),
                )
                # Build thread against this repo.
                table_blk = section.content_blocks[1]
                cell = table_blk["rows"][1][1]
                wc = repo.working_copy(self.project_id, section.section_id)
                current_table_blk = wc.content_blocks[1]
                block_hash = repo._payload_hash(current_table_blk)
                anchor_path = json.dumps(
                    {
                        "block_id": table_blk["block_id"],
                        "table_id": table_blk["table_id"],
                        "row_id": cell["structure_row_id"],
                        "column_id": cell["structure_column_id"],
                        "cell_id": cell["cell_id"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                anchor = MedicalWritingTableCellAnchor(
                    working_copy_revision=1,
                    table_version=0,
                    block_id=table_blk["block_id"],
                    table_id=table_blk["table_id"],
                    row_id=cell["structure_row_id"],
                    column_id=cell["structure_column_id"],
                    cell_id=cell["cell_id"],
                    captured_text=cell["text"],
                    block_hash=block_hash,
                )
                now = datetime.now(timezone.utc)
                proposal = f"fault proposal {checkpoint}"
                thread = RevisionThread(
                    thread_id=f"thread_tc_{checkpoint}",
                    project_id=self.project_id,
                    document_id=document.document_id,
                    section_id=section.section_id,
                    anchor_type="table_cell",
                    anchor_path=anchor_path,
                    selected_text=cell["text"],
                    user_instruction="优化表格",
                    intent="medical_writing_revision",
                    ai_run_id=f"run_{checkpoint}",
                    source_entry_id="entry_tc",
                    source_id="source_tc",
                    source_locator=anchor_path,
                    table_cell_anchor=anchor,
                    evidence_source_types=["approved_competitor_protocol_evidence"],
                    suggestions=[
                        RevisionSuggestion(
                            suggestion_id=f"sug_{checkpoint}",
                            proposal_text=proposal,
                            diff_patch="cell diff",
                            rationale="test",
                            evidence_span_ids=["span_tc"],
                            evidence_source_types=[
                                "approved_competitor_protocol_evidence"
                            ],
                        )
                    ],
                    status="candidate_ready",
                    created_at=now,
                )
                repo.commit_revision_submission(
                    thread,
                    AuditEvent(
                        audit_id=f"audit_submit_{checkpoint}",
                        project_id=self.project_id,
                        actor="test",
                        action="medical_writing_revision_submitted",
                        target_type="revision_thread",
                        target_id=thread.thread_id,
                        created_at=now,
                    ),
                )
                pre_thread = repo.revision_thread(self.project_id, thread.thread_id)
                pre_wc = repo.working_copy(self.project_id, section.section_id)
                _, pre_cell, _ = self._target_cell_snapshot(pre_wc, thread)
                pre_audits = store.workflow_audit_events(
                    self.project_id, "medical_writing_revision"
                )
                pre_audit_n = len(pre_audits)

                def fault(cp, target=checkpoint):
                    if cp == target:
                        raise RuntimeError(f"fault at {target}")

                faulting_store = SqliteRuntimeStore(
                    Path(tmp.name) / "runtime.sqlite3",
                    fault_injector=fault,
                )
                faulting_repo = MedicalWritingRuntimeRepository(
                    self.documents, faulting_store
                )
                with self.assertRaisesRegex(RuntimeError, "fault at"):
                    faulting_repo.accept_and_apply_candidate(
                        project_id=self.project_id,
                        thread_id=thread.thread_id,
                        suggestion_id=thread.suggestions[0].suggestion_id,
                        expected_working_copy_revision=1,
                        actor="test",
                        idempotency_key=f"tc-fault-{checkpoint}",
                    )

                # Re-open clean store handle on same db path without injector.
                clean_store = SqliteRuntimeStore(Path(tmp.name) / "runtime.sqlite3")
                clean_repo = MedicalWritingRuntimeRepository(self.documents, clean_store)
                post_thread = clean_repo.revision_thread(
                    self.project_id, thread.thread_id
                )
                self.assertEqual(pre_thread.status, post_thread.status)
                self.assertEqual("pending", post_thread.suggestions[0].user_decision)
                post_wc = clean_repo.working_copy(self.project_id, section.section_id)
                self.assertEqual(pre_wc.revision, post_wc.revision)
                _, post_cell, _ = self._target_cell_snapshot(post_wc, thread)
                self.assertEqual(pre_cell["text"], post_cell["text"])
                post_audits = clean_store.workflow_audit_events(
                    self.project_id, "medical_writing_revision"
                )
                self.assertEqual(pre_audit_n, len(post_audits))
                with clean_store._connect() as conn:
                    idem = conn.execute(
                        """
                        SELECT request_id FROM idempotency_records
                        WHERE tenant_id = ? AND project_id = ?
                          AND operation = 'medical_writing_atomic_accept_and_apply'
                          AND idempotency_key = ?
                        """,
                        (
                            "kangzhe_local",
                            self.project_id,
                            f"tc-fault-{checkpoint}",
                        ),
                    ).fetchone()
                self.assertIsNone(idem)

                # Clean retry succeeds exactly once.
                ok = clean_repo.accept_and_apply_candidate(
                    project_id=self.project_id,
                    thread_id=thread.thread_id,
                    suggestion_id=thread.suggestions[0].suggestion_id,
                    expected_working_copy_revision=1,
                    actor="test",
                    idempotency_key=f"tc-fault-retry-{checkpoint}",
                )
                self.assertEqual(2, ok.working_copy.revision)
                _, ok_cell, _ = self._target_cell_snapshot(ok.working_copy, thread)
                self.assertEqual(proposal, ok_cell["text"])


if __name__ == "__main__":
    unittest.main()
