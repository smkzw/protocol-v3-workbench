from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from packages.contracts.workbench_contracts import (
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalState,
    AuditEvent,
    MedicalWritingWorkingCopySaveRequest,
    ProtocolDocument,
    ProtocolSection,
    RevisionSuggestion,
    RevisionThread,
)
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app import main as app_main
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_manifest import D001_PROTOCOL_DOCX, RUX_PROTOCOL_DOCX
from services.api.app.sqlite_runtime_store import (
    IDENTITY_ASSURANCE,
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


NOW = datetime(2026, 7, 10, 6, 0, tzinfo=timezone.utc)
PROJECTS = ("proj_rux_03_002", "proj_d001")


class StubDocumentService:
    def __init__(self):
        self.documents = {}
        for project_id in PROJECTS:
            suffix = project_id.removeprefix("proj_")
            document_id = f"mwdoc_{suffix}_source"
            section = ProtocolSection(
                section_id=f"mwsec_{suffix}_objectives",
                document_id=document_id,
                heading="研究目的",
                content_blocks=[
                    {
                        "block_id": f"block_{suffix}_001",
                        "block_type": "paragraph",
                        "text": f"{suffix} 原始研究目的正文。",
                        "source_locator": "docx:paragraph:10",
                    }
                ],
            )
            self.documents[project_id] = ProtocolDocument(
                document_id=document_id,
                project_id=project_id,
                protocol_id=suffix.upper(),
                version="source-v1",
                sections=[section],
            )

    def document_session(self, project_id: str) -> ProtocolDocument:
        return self.documents[project_id]

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        return self.documents[project_id]

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        return next(
            section
            for section in self.documents[project_id].sections
            if section.section_id == section_id
        )


def make_thread(project_id: str, *, status: str = "pending_medical_approval") -> RevisionThread:
    suffix = project_id.removeprefix("proj_")
    document_id = f"mwdoc_{suffix}_source"
    section_id = f"mwsec_{suffix}_objectives"
    decision = (
        "accepted"
        if status in {"author_selected", "accepted_pending_medical_approval"}
        else "pending"
    )
    return RevisionThread(
        thread_id=f"thread_{suffix}_001",
        project_id=project_id,
        document_id=document_id,
        section_id=section_id,
        anchor_type="paragraph",
        anchor_path="docx:paragraph:10",
        selected_text=f"{suffix} 原始研究目的正文。",
        user_instruction="请优化医学写作表述。",
        intent="medical_writing_revision",
        ai_run_id=f"ai_run_{suffix}_001",
        suggestions=[
            RevisionSuggestion(
                suggestion_id=f"suggestion_{suffix}_001",
                proposal_text=f"{suffix} 修订候选正文。",
                diff_patch="candidate patch",
                rationale="提高正文清晰度。",
                evidence_span_ids=[f"span_{suffix}_001"],
                uncertainty="需医学经理确认。",
                user_decision=decision,
            )
        ],
        status=status,
        created_at=NOW,
        resolved_at=NOW if status != "pending_medical_approval" else None,
    )


def make_audit(project_id: str, audit_id: str, action: str) -> AuditEvent:
    return AuditEvent(
        audit_id=audit_id,
        project_id=project_id,
        actor="medical_manager_test",
        action=action,
        target_type="revision_thread",
        target_id=make_thread(project_id).thread_id,
        created_at=NOW,
    )


class MedicalWritingWorkingCopyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "runtime.sqlite3"
        self.documents = StubDocumentService()
        self.store = SqliteRuntimeStore(self.db_path)
        self.repository = MedicalWritingRuntimeRepository(self.documents, self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def save_request(
        self,
        project_id: str,
        *,
        expected_revision: int,
        text: str,
        key: str,
    ) -> MedicalWritingWorkingCopySaveRequest:
        section = self.documents.documents[project_id].sections[0]
        block = dict(section.content_blocks[0])
        block["text"] = text
        return MedicalWritingWorkingCopySaveRequest(
            document_id=section.document_id,
            expected_revision=expected_revision,
            content_blocks=[block],
            actor="medical_manager_test",
            idempotency_key=key,
        )

    def seed_accepted_thread(self, project_id: str) -> RevisionThread:
        initial = make_thread(project_id)
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit(project_id, f"audit_{project_id}_submit", "medical_writing_revision_submitted"),
        )
        accepted = make_thread(project_id, status="author_selected")
        self.store.commit_medical_writing_revision_action(
            initial,
            accepted,
            make_audit(project_id, f"audit_{project_id}_accept", "medical_writing_revision_accept"),
            None,
        )
        return accepted

    def test_project_isolated_saves_are_versioned_snapshotted_and_survive_restart(self):
        for project_id in PROJECTS:
            with self.subTest(project_id=project_id):
                section = self.documents.documents[project_id].sections[0]
                saved = self.repository.save_working_copy(
                    project_id,
                    section.section_id,
                    self.save_request(
                        project_id,
                        expected_revision=0,
                        text=f"{project_id} 医学经理修订稿。",
                        key=f"save-{project_id}-r1",
                    ),
                )
                self.assertEqual(1, saved.revision)
                self.assertEqual(ApprovalState.AI_DRAFT, saved.approval_state)

        restarted = MedicalWritingRuntimeRepository(
            self.documents,
            SqliteRuntimeStore(self.db_path),
        )
        for project_id in PROJECTS:
            section = self.documents.documents[project_id].sections[0]
            recovered = restarted.working_copy(project_id, section.section_id)
            self.assertEqual(1, recovered.revision)
            self.assertIn(project_id, recovered.content_blocks[0]["text"])
            snapshots = restarted.runtime_store.medical_writing_working_copy_snapshots(
                project_id,
                recovered.working_copy_id,
            )
            self.assertEqual(1, len(snapshots))
            self.assertEqual("save", snapshots[0]["snapshot_type"])
            self.assertEqual([], restarted.runtime_store.verify_audit_chain(project_id))
            self.assertTrue(
                all(
                    event["identity_assurance"] == IDENTITY_ASSURANCE
                    for event in restarted.runtime_store.runtime_audit_records(project_id)
                )
            )

    def test_v2_database_is_backed_up_before_current_migration(self):
        self.store = None
        with sqlite3.connect(self.db_path) as connection:
            for trigger in [
                "trg_evidence_ai_revision_snapshot_no_update",
                "trg_evidence_ai_revision_snapshot_no_delete",
                "trg_evidence_review_record_no_update",
                "trg_evidence_review_record_no_delete",
                "trg_evidence_picos_decision_record_no_update",
                "trg_evidence_picos_decision_record_no_delete",
                "trg_evidence_picos_snapshot_no_update",
                "trg_evidence_picos_snapshot_no_delete",
                "trg_evidence_picos_handoff_no_update",
                "trg_evidence_picos_handoff_no_delete",
                "trg_eligibility_review_record_no_update",
                "trg_eligibility_review_record_no_delete",
                "trg_eligibility_evidence_artifact_no_update",
                "trg_eligibility_evidence_artifact_no_delete",
                "trg_eligibility_evidence_attempt_no_update",
                "trg_eligibility_evidence_span_no_update",
                "trg_eligibility_evidence_span_no_delete",
                "trg_eligibility_visual_qc_record_no_update",
                "trg_eligibility_visual_qc_record_no_delete",
            ]:
                connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            for table in [
                "eligibility_evidence_visual_qc_state",
                "eligibility_evidence_visual_qc_records",
                "eligibility_evidence_artifacts",
                "eligibility_evidence_job_attempts",
                "eligibility_evidence_jobs",
                "eligibility_review_state",
                "eligibility_review_records",
                "eligibility_evidence_spans",
                "eligibility_rule_revisions",
                "eligibility_source_revisions",
                "evidence_ai_revision_snapshots",
                "evidence_ai_revision_threads",
                "evidence_picos_writing_handoffs",
                "evidence_picos_working_state_snapshots",
                "evidence_picos_decision_records",
                "evidence_picos_working_states",
                "evidence_review_records",
            ]:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            connection.execute(
                "DROP TRIGGER trg_medical_writing_working_copy_snapshot_no_update"
            )
            connection.execute(
                "DROP TRIGGER trg_medical_writing_working_copy_snapshot_no_delete"
            )
            connection.execute("DROP TABLE medical_writing_working_copy_snapshots")
            connection.execute("DROP TABLE medical_writing_working_copies")
            connection.execute("DELETE FROM schema_migrations WHERE version >= 3")
            connection.commit()

        migrated = SqliteRuntimeStore(self.db_path)
        self.assertEqual(16, migrated.health_report()["schema_version"])
        backups = list(self.db_path.parent.glob("runtime.sqlite3.v2.*.bak"))
        self.assertEqual(1, len(backups))
        with sqlite3.connect(backups[0]) as backup:
            self.assertEqual(
                2,
                backup.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
            )
            table = backup.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
                ("medical_writing_working_copies",),
            ).fetchone()
            self.assertIsNone(table)

    def test_save_is_idempotent_and_stale_revision_is_rejected(self):
        project_id = PROJECTS[0]
        section = self.documents.documents[project_id].sections[0]
        request = self.save_request(
            project_id,
            expected_revision=0,
            text="第一版 working copy。",
            key="stable-save-key",
        )
        first = self.repository.save_working_copy(project_id, section.section_id, request)
        replay = self.repository.save_working_copy(project_id, section.section_id, request)
        self.assertEqual(first.model_dump(mode="json"), replay.model_dump(mode="json"))
        self.assertEqual(
            1,
            len(self.store.medical_writing_working_copy_snapshots(project_id, first.working_copy_id)),
        )

        with self.assertRaises(StaleRuntimeStateError):
            self.repository.save_working_copy(
                project_id,
                section.section_id,
                self.save_request(
                    project_id,
                    expected_revision=0,
                    text="错误覆盖版本。",
                    key="stale-save-key",
                ),
            )
        current = self.repository.working_copy(project_id, section.section_id)
        self.assertEqual(1, current.revision)
        self.assertEqual("第一版 working copy。", current.content_blocks[0]["text"])
        self.assertIn(
            "stale_write_rejected",
            [event["event_type"] for event in self.store.runtime_audit_records(project_id)],
        )

    def test_save_rejects_client_injected_fields_outside_canonical_source_block(self):
        project_id = PROJECTS[0]
        section = self.documents.documents[project_id].sections[0]
        request = self.save_request(
            project_id,
            expected_revision=0,
            text="合法正文但附带非法字段。",
            key="reject-extra-field",
        )
        request.content_blocks[0]["server_path"] = "/Users/private/source.docx"
        with self.assertRaisesRegex(ValueError, "canonical source block fields"):
            self.repository.save_working_copy(project_id, section.section_id, request)
        with self.assertRaises(KeyError):
            self.store.medical_writing_working_copy(
                project_id,
                section.document_id,
                section.section_id,
            )

    def test_rich_text_marks_are_validated_persisted_and_source_linked(self):
        project_id = PROJECTS[0]
        section = self.documents.documents[project_id].sections[0]
        request = self.save_request(
            project_id,
            expected_revision=0,
            text="加粗斜体正文",
            key="rich-text-save",
        )
        request.content_blocks[0]["rich_text"] = {
            "type": "paragraph",
            "attrs": {
                "stylePreset": "body",
                "textAlign": "justify",
                "lineHeight": 1.5,
                "spacingBeforePt": 0,
                "spacingAfterPt": 4,
                "leftIndentChars": 0,
                "rightIndentChars": 0,
                "firstLineIndentChars": 2,
            },
            "content": [
                {
                    "type": "text",
                    "text": "加粗",
                    "marks": [
                        {"type": "bold"},
                        {"type": "underline"},
                        {
                            "type": "textStyle",
                            "attrs": {
                                "fontFamily": "黑体",
                                "fontSize": "12pt",
                                "color": "#C00000",
                            },
                        },
                    ],
                },
                {
                    "type": "text",
                    "text": "斜体正文",
                    "marks": [
                        {"type": "italic"},
                        {"type": "highlight", "attrs": {"color": "#FFFF00"}},
                    ],
                },
            ],
        }
        saved = self.repository.save_working_copy(project_id, section.section_id, request)
        self.assertEqual(request.content_blocks[0]["rich_text"], saved.content_blocks[0]["rich_text"])

        multiline_project = project_id
        multiline_section = section
        multiline = self.save_request(
            multiline_project,
            expected_revision=1,
            text="第一段。\n第二段。",
            key="rich-text-multiline-save",
        )
        multiline.content_blocks[0]["rich_text"] = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "第一段。"}]},
                {"type": "paragraph", "content": [{"type": "text", "text": "第二段。"}]},
            ],
        }
        multiline_saved = self.repository.save_working_copy(
            multiline_project,
            multiline_section.section_id,
            multiline,
        )
        self.assertEqual("doc", multiline_saved.content_blocks[0]["rich_text"]["type"])
        self.assertEqual("第一段。\n第二段。", multiline_saved.content_blocks[0]["text"])

        invalid_project = PROJECTS[1]
        invalid_section = self.documents.documents[invalid_project].sections[0]
        invalid = self.save_request(
            invalid_project,
            expected_revision=0,
            text="不允许链接",
            key="invalid-rich-text-save",
        )
        invalid.content_blocks[0]["rich_text"] = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "不允许链接", "marks": [{"type": "link"}]},
            ],
        }
        with self.assertRaisesRegex(ValueError, "marks are invalid"):
            self.repository.save_working_copy(
                invalid_project,
                invalid_section.section_id,
                invalid,
            )

    def test_citation_mark_requires_and_persists_project_reference_id(self):
        project_id = PROJECTS[0]
        section = self.documents.documents[project_id].sections[0]
        request = self.save_request(
            project_id,
            expected_revision=0,
            text="疗效结论[1]",
            key="citation-rich-text-save",
        )
        citation_mark = {
            "type": "citation",
            "attrs": {"referenceId": "mwref_0123456789abcdef0123"},
        }
        request.content_blocks[0]["rich_text"] = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "疗效结论"},
                {"type": "text", "text": "[1]", "marks": [citation_mark]},
            ],
        }
        saved = self.repository.save_working_copy(project_id, section.section_id, request)
        self.assertEqual(
            citation_mark,
            saved.content_blocks[0]["rich_text"]["content"][1]["marks"][0],
        )

        invalid_project = PROJECTS[1]
        invalid_section = self.documents.documents[invalid_project].sections[0]
        invalid = self.save_request(
            invalid_project,
            expected_revision=0,
            text="疗效结论[1]",
            key="invalid-citation-rich-text-save",
        )
        invalid.content_blocks[0]["rich_text"] = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "疗效结论"},
                {
                    "type": "text",
                    "text": "[1]",
                    "marks": [{"type": "citation", "attrs": {"referenceId": "other-project"}}],
                },
            ],
        }
        with self.assertRaisesRegex(ValueError, "citation is invalid"):
            self.repository.save_working_copy(
                invalid_project,
                invalid_section.section_id,
                invalid,
            )

    def test_multi_reference_citation_mark_round_trips_as_one_group(self):
        project_id = PROJECTS[0]
        section = self.documents.documents[project_id].sections[0]
        request = self.save_request(
            project_id,
            expected_revision=0,
            text="联合证据[1,2]",
            key="multi-citation-rich-text-save",
        )
        citation_mark = {
            "type": "citation",
            "attrs": {
                "referenceIds": [
                    "mwref_0123456789abcdef0123",
                    "mwref_abcdef0123456789abcd",
                ]
            },
        }
        request.content_blocks[0]["rich_text"] = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "联合证据"},
                {"type": "text", "text": "[1,2]", "marks": [citation_mark]},
            ],
        }
        saved = self.repository.save_working_copy(project_id, section.section_id, request)
        self.assertEqual(
            citation_mark,
            saved.content_blocks[0]["rich_text"]["content"][1]["marks"][0],
        )

    def test_cross_reference_mark_persists_stable_target_identity_only(self):
        project_id = PROJECTS[0]
        section = self.documents.documents[project_id].sections[0]
        request = self.save_request(
            project_id,
            expected_revision=0,
            text="见表 1。",
            key="cross-reference-rich-text-save",
        )
        cross_reference_mark = {
            "type": "crossReference",
            "attrs": {
                "targetKind": "table",
                "targetId": "ptbl_0123456789abcdef",
            },
        }
        request.content_blocks[0]["rich_text"] = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "见"},
                {"type": "text", "text": "表 1", "marks": [cross_reference_mark]},
                {"type": "text", "text": "。"},
            ],
        }
        saved = self.repository.save_working_copy(
            project_id,
            section.section_id,
            request,
        )
        self.assertEqual(
            cross_reference_mark,
            saved.content_blocks[0]["rich_text"]["content"][1]["marks"][0],
        )

        invalid_project = PROJECTS[1]
        invalid_section = self.documents.documents[invalid_project].sections[0]
        invalid = self.save_request(
            invalid_project,
            expected_revision=0,
            text="见表 1。",
            key="invalid-cross-reference-rich-text-save",
        )
        invalid.content_blocks[0]["rich_text"] = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "见"},
                {
                    "type": "text",
                    "text": "表 1",
                    "marks": [
                        {
                            "type": "crossReference",
                            "attrs": {
                                "targetKind": "table",
                                "targetId": "ptbl_1",
                                "bookmarkName": "_client_injected",
                            },
                        }
                    ],
                },
                {"type": "text", "text": "。"},
            ],
        }
        with self.assertRaisesRegex(ValueError, "cross-reference is invalid"):
            self.repository.save_working_copy(
                invalid_project,
                invalid_section.section_id,
                invalid,
            )

    def test_save_fault_rolls_back_copy_snapshot_and_workflow_audit(self):
        project_id = PROJECTS[0]
        section = self.documents.documents[project_id].sections[0]

        def fail(checkpoint: str):
            if checkpoint == "after_working_copy_snapshot":
                raise RuntimeError("working copy fault")

        failing_repo = MedicalWritingRuntimeRepository(
            self.documents,
            SqliteRuntimeStore(self.db_path, fault_injector=fail),
        )
        with self.assertRaisesRegex(RuntimeError, "working copy fault"):
            failing_repo.save_working_copy(
                project_id,
                section.section_id,
                self.save_request(
                    project_id,
                    expected_revision=0,
                    text="不得残留的工作副本。",
                    key="fault-save-key",
                ),
            )

        restarted = SqliteRuntimeStore(self.db_path)
        with self.assertRaises(KeyError):
            restarted.medical_writing_working_copy(project_id, section.document_id, section.section_id)
        self.assertEqual([], restarted.workflow_audit_events(project_id, "medical_writing_working_copy"))
        self.assertEqual([], restarted.runtime_audit_records(project_id))

    def legacy_contract_revision_approval_actions_persist_atomically_for_both_projects(self):
        scenarios = (
            (ApprovalAction.APPROVE, ApprovalState.MEDICALLY_APPROVED, "medically_approved"),
            (ApprovalAction.RETURN_FOR_REVISION, ApprovalState.RETURNED_FOR_REVISION, "returned_for_revision"),
            (ApprovalAction.REJECT, ApprovalState.SUPERSEDED, "superseded"),
        )
        for project_index, project_id in enumerate(PROJECTS):
            for action_index, (action, expected_gate_state, expected_thread_status) in enumerate(scenarios):
                with self.subTest(project_id=project_id, action=action.value):
                    db_path = Path(self.tmpdir.name) / f"approval-{project_index}-{action_index}.sqlite3"
                    store = SqliteRuntimeStore(db_path)
                    repository = MedicalWritingRuntimeRepository(self.documents, store)
                    self.store = store
                    self.repository = repository
                    accepted = self.seed_accepted_thread(project_id)
                    gate = repository.ensure_revision_approval_gate(accepted, "medical_manager_test")
                    result = repository.record_approval_action(
                        project_id,
                        gate.approval_id,
                        ApprovalActionRequest(
                            action=action,
                            actor="medical_manager_test",
                            comment=f"{project_id}-{action.value}",
                            idempotency_key=f"approval-{project_id}-{action.value}",
                        ),
                    )
                    self.assertEqual(expected_gate_state, result.approval.state)

                    restarted_store = SqliteRuntimeStore(db_path)
                    restarted_repo = MedicalWritingRuntimeRepository(self.documents, restarted_store)
                    self.assertEqual(
                        expected_gate_state,
                        restarted_repo.approval(project_id, gate.approval_id).state,
                    )
                    self.assertEqual(
                        expected_thread_status,
                        restarted_repo.revision_thread(project_id, accepted.thread_id).status,
                    )
                    self.assertEqual(1, len(restarted_store.decisions(project_id)))
                    self.assertEqual(1, len(restarted_store.audit_events(project_id)))
                    self.assertEqual([], restarted_store.verify_audit_chain(project_id))

    def legacy_contract_final_approval_retry_is_idempotent_and_fault_rolls_back_all_records(self):
        project_id = PROJECTS[0]
        accepted = self.seed_accepted_thread(project_id)
        gate = self.repository.ensure_revision_approval_gate(accepted, "medical_manager_test")
        request = ApprovalActionRequest(
            action=ApprovalAction.APPROVE,
            actor="medical_manager_test",
            comment="医学批准测试。",
            idempotency_key="approve-once",
        )
        first = self.repository.record_approval_action(project_id, gate.approval_id, request)
        replay = self.repository.record_approval_action(project_id, gate.approval_id, request)
        self.assertEqual(first.decision.decision_id, replay.decision.decision_id)
        self.assertEqual(1, len(self.store.decisions(project_id)))
        self.assertEqual(1, len(self.store.audit_events(project_id)))

        fault_db = Path(self.tmpdir.name) / "approval-fault.sqlite3"
        seed_store = SqliteRuntimeStore(fault_db)
        seed_repo = MedicalWritingRuntimeRepository(self.documents, seed_store)
        self.store = seed_store
        self.repository = seed_repo
        accepted = self.seed_accepted_thread(project_id)
        gate = seed_repo.ensure_revision_approval_gate(accepted, "medical_manager_test")

        def fail(checkpoint: str):
            if checkpoint == "after_decision":
                raise RuntimeError("approval fault")

        failing_repo = MedicalWritingRuntimeRepository(
            self.documents,
            SqliteRuntimeStore(fault_db, fault_injector=fail),
        )
        with self.assertRaisesRegex(RuntimeError, "approval fault"):
            failing_repo.record_approval_action(
                project_id,
                gate.approval_id,
                ApprovalActionRequest(
                    action=ApprovalAction.REJECT,
                    actor="medical_manager_test",
                    comment="不得残留。",
                    idempotency_key="fault-approval",
                ),
            )

        restarted = SqliteRuntimeStore(fault_db)
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, restarted.gates(project_id)[0].state)
        self.assertEqual(
            "accepted_pending_medical_approval",
            restarted.medical_writing_revision_thread(project_id, accepted.thread_id).status,
        )
        self.assertEqual([], restarted.decisions(project_id))
        self.assertEqual([], restarted.audit_events(project_id))

    def legacy_contract_working_copy_approval_freezes_current_revision_and_detects_audit_tampering(self):
        project_id = PROJECTS[1]
        section = self.documents.documents[project_id].sections[0]
        saved = self.repository.save_working_copy(
            project_id,
            section.section_id,
            self.save_request(
                project_id,
                expected_revision=0,
                text="D001 待批准 working copy。",
                key="d001-save",
            ),
        )
        gate = self.repository.ensure_working_copy_approval_gate(saved, "medical_manager_test")
        self.assertEqual(f"研究方案章节：{section.heading}", gate.display_title)
        self.assertIn("工作副本版本 1", gate.display_detail)
        pending = self.repository.working_copy(project_id, section.section_id)
        self.assertEqual(ApprovalState.IN_MEDICAL_REVIEW, pending.approval_state)
        with self.assertRaisesRegex(RuntimeStoreError, "not editable"):
            self.repository.save_working_copy(
                project_id,
                section.section_id,
                self.save_request(
                    project_id,
                    expected_revision=1,
                    text="不得绕过审批门继续保存。",
                    key="d001-save-during-review",
                ),
            )
        result = self.repository.record_approval_action(
            project_id,
            gate.approval_id,
            ApprovalActionRequest(
                action=ApprovalAction.APPROVE,
                actor="medical_manager_test",
                comment="批准当前 working copy 版本。",
                idempotency_key="d001-working-copy-approve",
            ),
        )
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, result.approval.state)

        restarted = SqliteRuntimeStore(self.db_path)
        approved = restarted.medical_writing_working_copy(
            project_id,
            section.document_id,
            section.section_id,
        )
        self.assertEqual(1, approved.revision)
        self.assertEqual(ApprovalState.MEDICALLY_APPROVED, approved.approval_state)
        self.assertEqual(1, approved.approved_revision)
        snapshots = restarted.medical_writing_working_copy_snapshots(
            project_id,
            approved.working_copy_id,
        )
        self.assertEqual(
            ["save", "approval_submission", "approval"],
            [item["snapshot_type"] for item in snapshots],
        )

        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "UPDATE runtime_audit_chain SET detail_json = ? WHERE project_id = ? AND event_type = ?",
                ('{"tampered":true}', project_id, "medical_writing_final_approval_committed"),
            )
            connection.commit()
        self.assertTrue(restarted.verify_audit_chain(project_id))
        self.assertEqual("error", restarted.health_report()["status"])

    def legacy_contract_returned_working_copy_requires_new_saved_revision_before_resubmission(self):
        project_id = PROJECTS[1]
        section = self.documents.documents[project_id].sections[0]
        saved = self.repository.save_working_copy(
            project_id,
            section.section_id,
            self.save_request(
                project_id,
                expected_revision=0,
                text="D001 首次审批版本。",
                key="d001-return-r1",
            ),
        )
        gate = self.repository.ensure_working_copy_approval_gate(saved, "medical_manager_test")
        self.repository.record_approval_action(
            project_id,
            gate.approval_id,
            ApprovalActionRequest(
                action=ApprovalAction.RETURN_FOR_REVISION,
                actor="medical_manager_test",
                comment="请修订后重新提交。",
                idempotency_key="d001-return-action",
            ),
        )
        returned = self.repository.working_copy(project_id, section.section_id)
        self.assertEqual(ApprovalState.RETURNED_FOR_REVISION, returned.approval_state)
        with self.assertRaisesRegex(RuntimeStoreError, "save a new revision"):
            self.repository.ensure_working_copy_approval_gate(
                returned,
                "medical_manager_test",
            )

        revised = self.repository.save_working_copy(
            project_id,
            section.section_id,
            self.save_request(
                project_id,
                expected_revision=1,
                text="D001 退回后修订版本。",
                key="d001-return-r2",
            ),
        )
        self.assertEqual(2, revised.revision)
        self.assertEqual(ApprovalState.AI_DRAFT, revised.approval_state)
        resubmitted = self.repository.ensure_working_copy_approval_gate(
            revised,
            "medical_manager_test",
        )
        self.assertEqual(2, resubmitted.target_revision)
        self.assertNotEqual(gate.approval_id, resubmitted.approval_id)

    def legacy_contract_snapshots_are_immutable_and_gate_payload_tampering_is_detected(self):
        project_id = PROJECTS[1]
        section = self.documents.documents[project_id].sections[0]
        saved = self.repository.save_working_copy(
            project_id,
            section.section_id,
            self.save_request(
                project_id,
                expected_revision=0,
                text="D001 immutable snapshot test。",
                key="d001-immutable-save",
            ),
        )
        gate = self.repository.ensure_working_copy_approval_gate(saved, "medical_manager_test")
        self.repository.record_approval_action(
            project_id,
            gate.approval_id,
            ApprovalActionRequest(
                action=ApprovalAction.APPROVE,
                actor="medical_manager_test",
                comment="批准不可变快照测试。",
                idempotency_key="d001-immutable-approve",
            ),
        )
        self.assertEqual([], self.store.verify_audit_chain(project_id))

        with sqlite3.connect(self.db_path) as connection:
            with self.assertRaisesRegex(
                sqlite3.IntegrityError,
                "snapshots are immutable",
            ):
                connection.execute(
                    """
                    UPDATE medical_writing_working_copy_snapshots
                    SET payload_json = ? WHERE project_id = ?
                    """,
                    ('{"tampered":true}', project_id),
                )
            connection.rollback()

        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM approval_gates WHERE project_id = ? AND approval_id = ?",
                (project_id, gate.approval_id),
            ).fetchone()
            payload = json.loads(row[0])
            payload["state"] = "ai_draft"
            connection.execute(
                "UPDATE approval_gates SET payload_json = ? WHERE project_id = ? AND approval_id = ?",
                (json.dumps(payload, ensure_ascii=False), project_id, gate.approval_id),
            )
            connection.commit()
        violations = self.store.verify_audit_chain(project_id)
        self.assertTrue(any("gate state mismatch" in item for item in violations))


class MedicalWritingWorkingCopyApiTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "runtime.sqlite3"
        self.documents = StubDocumentService()
        self.store = SqliteRuntimeStore(self.db_path)
        self.repository = MedicalWritingRuntimeRepository(self.documents, self.store)
        self.patch = patch(
            "services.api.app.main.medical_writing_runtime_repository",
            self.repository,
        )
        self.patch.start()
        self.client = TestClient(app_main.app)

    def tearDown(self):
        self.patch.stop()
        self.tmpdir.cleanup()

    def test_real_working_copy_save_and_author_freeze_routes_use_sqlite_repository(self):
        project_id = "proj_rux_03_002"
        section = self.documents.documents[project_id].sections[0]
        initial = self.client.get(
            f"/api/projects/{project_id}/medical-writing/working-copies/{section.section_id}"
        )
        self.assertEqual(200, initial.status_code, initial.text)
        self.assertEqual(0, initial.json()["revision"])

        block = dict(section.content_blocks[0])
        block["text"] = "RUX 真实 working copy API 修订稿。"
        saved = self.client.post(
            f"/api/projects/{project_id}/medical-writing/working-copies/{section.section_id}",
            json={
                "document_id": section.document_id,
                "expected_revision": 0,
                "content_blocks": [block],
                "actor": "medical_manager_test",
                "idempotency_key": "api-save-rux-r1",
            },
        )
        self.assertEqual(200, saved.status_code, saved.text)
        self.assertEqual(1, saved.json()["revision"])

        retired_gate_response = self.client.post(
            f"/api/projects/{project_id}/medical-writing/working-copies/"
            f"{section.section_id}/approval-gate?requested_by=medical_manager_test"
        )
        self.assertEqual(410, retired_gate_response.status_code)
        frozen = self.client.post(
            f"/api/projects/{project_id}/medical-writing/working-copies/"
            f"{section.section_id}/freeze-current-version",
            json={
                "document_id": section.document_id,
                "expected_working_copy_revision": 1,
                "reason": "医学作者已完成本章节内容核对并确认冻结当前版本。",
                "actor": "medical_manager_test",
                "idempotency_key": "api-freeze-rux-working-copy",
            },
        )
        self.assertEqual(200, frozen.status_code, frozen.text)
        self.assertEqual("frozen", frozen.json()["working_copy"]["freeze_status"])

        restarted = SqliteRuntimeStore(self.db_path)
        stored = restarted.medical_writing_working_copy(
            project_id,
            section.document_id,
            section.section_id,
        )
        self.assertEqual(ApprovalState.AI_DRAFT, stored.approval_state)
        self.assertEqual("frozen", stored.freeze_status)
        self.assertEqual(1, stored.frozen_revision)
        self.assertEqual([], restarted.verify_audit_chain(project_id))

    def test_legacy_revision_application_route_is_retired_for_real_project(self):
        project_id = "proj_rux_03_002"
        section = self.documents.documents[project_id].sections[0]
        initial = make_thread(project_id)
        accepted = make_thread(project_id, status="author_selected")
        self.store.commit_medical_writing_revision_submission(
            initial,
            make_audit(project_id, "audit_api_apply_submit", "medical_writing_revision_submitted"),
        )
        self.store.commit_medical_writing_revision_action(
            initial,
            accepted,
            make_audit(project_id, "audit_api_apply_accept", "medical_writing_revision_accept"),
            None,
        )

        applied = self.client.post(
            f"/api/projects/{project_id}/medical-writing/working-copies/{section.section_id}"
            f"/revision-threads/{accepted.thread_id}/apply",
            json={
                "expected_working_copy_revision": 0,
                "actor": "medical_manager_test",
                "idempotency_key": "apply-api-rux-thread",
            },
        )
        self.assertEqual(410, applied.status_code, applied.text)
        self.assertIn("atomic accept-and-apply", applied.json()["detail"])


@unittest.skipUnless(
    RUX_PROTOCOL_DOCX.exists() and D001_PROTOCOL_DOCX.exists(),
    "real protocol DOCX fixtures are unavailable",
)
class RealProtocolWorkingCopyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "real-protocol-runtime.sqlite3"
        self.documents = MedicalWritingDocumentService()
        self.store = SqliteRuntimeStore(self.db_path)
        self.repository = MedicalWritingRuntimeRepository(self.documents, self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_rux_and_d001_original_sections_save_and_recover_without_cross_project_state(self):
        saved_by_project = {}
        for project_id in PROJECTS:
            session = self.documents.document_session(project_id)
            section = next(
                self.documents.section(project_id, summary.section_id)
                for summary in session.sections
                if any(
                    block.get("block_type") != "table"
                    for block in self.documents.section(
                        project_id,
                        summary.section_id,
                    ).content_blocks
                )
            )
            blocks = deepcopy(section.content_blocks)
            paragraph = next(
                block for block in blocks if block.get("block_type") != "table"
            )
            paragraph["text"] = f"{paragraph['text']}（{project_id} working copy 测试修订）"
            paragraph["rich_text"] = {
                **paragraph["rich_text"],
                "content": [{"type": "text", "text": paragraph["text"]}],
            }
            saved = self.repository.save_working_copy(
                project_id,
                section.section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=session.document_id,
                    expected_revision=0,
                    content_blocks=blocks,
                    actor="medical_manager_test",
                    idempotency_key=f"real-save-{project_id}",
                ),
            )
            saved_by_project[project_id] = saved

        restarted = MedicalWritingRuntimeRepository(
            MedicalWritingDocumentService(),
            SqliteRuntimeStore(self.db_path),
        )
        for project_id, saved in saved_by_project.items():
            recovered = restarted.working_copy(project_id, saved.section_id)
            self.assertEqual(saved.working_copy_id, recovered.working_copy_id)
            self.assertEqual(1, recovered.revision)
            self.assertTrue(
                any(
                    project_id in str(block.get("text", ""))
                    for block in recovered.content_blocks
                )
            )
            self.assertEqual([], restarted.runtime_store.verify_audit_chain(project_id))
        self.assertNotEqual(
            saved_by_project[PROJECTS[0]].working_copy_id,
            saved_by_project[PROJECTS[1]].working_copy_id,
        )

    def test_rux_and_d001_table_cell_edits_persist_in_versioned_working_copies(self):
        saved_by_project = {}
        for project_id in PROJECTS:
            session = self.documents.document_session(project_id)
            section = next(
                self.documents.section(project_id, summary.section_id)
                for summary in session.sections
                if any(
                    block.get("block_type") == "table"
                    for block in self.documents.section(project_id, summary.section_id).content_blocks
                )
            )
            blocks = deepcopy(section.content_blocks)
            table = next(block for block in blocks if block.get("block_type") == "table")
            original = table["rows"][0][0]["text"]
            table["rows"][0][0]["text"] = f"{original}（{project_id} 表格工作副本修订）"
            saved_by_project[project_id] = self.repository.save_working_copy(
                project_id,
                section.section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=session.document_id,
                    expected_revision=0,
                    content_blocks=blocks,
                    actor="medical_manager_test",
                    idempotency_key=f"real-table-save-{project_id}",
                ),
            )

        restarted = MedicalWritingRuntimeRepository(
            MedicalWritingDocumentService(),
            SqliteRuntimeStore(self.db_path),
        )
        for project_id, saved in saved_by_project.items():
            recovered = restarted.working_copy(project_id, saved.section_id)
            table = next(
                block for block in recovered.content_blocks if block.get("block_type") == "table"
            )
            self.assertIn(project_id, table["rows"][0][0]["text"])
            self.assertEqual(1, recovered.revision)
            self.assertEqual([], restarted.runtime_store.verify_audit_chain(project_id))

    def test_rux_and_d001_legacy_table_roles_hydrate_without_overwriting_cell_edits(self):
        saved_by_project = {}
        for project_id in PROJECTS:
            session = self.documents.document_session(project_id)
            section = next(
                self.documents.section(project_id, summary.section_id)
                for summary in session.sections
                if any(
                    block.get("block_type") == "table"
                    and block.get("structured_table", {}).get("role")
                    in {"layout", "protocol_synopsis", "document_control"}
                    for block in self.documents.section(
                        project_id,
                        summary.section_id,
                    ).content_blocks
                )
            )
            blocks = deepcopy(section.content_blocks)
            table = next(
                block
                for block in blocks
                if block.get("block_type") == "table"
                and block.get("structured_table", {}).get("role")
                in {"layout", "protocol_synopsis", "document_control"}
            )
            expected_role = table["structured_table"].pop("role")
            original = table["rows"][0][0]["text"]
            table["rows"][0][0]["text"] = (
                f"{original}（{project_id} 历史角色兼容测试修订）"
            )
            saved = self.repository.save_working_copy(
                project_id,
                section.section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=session.document_id,
                    expected_revision=0,
                    content_blocks=blocks,
                    actor="medical_manager_test",
                    idempotency_key=f"legacy-table-role-{project_id}",
                ),
            )
            saved_by_project[project_id] = (saved, expected_role)

        restarted = MedicalWritingRuntimeRepository(
            MedicalWritingDocumentService(),
            SqliteRuntimeStore(self.db_path),
        )
        for project_id, (saved, expected_role) in saved_by_project.items():
            recovered = restarted.working_copy(project_id, saved.section_id)
            table = next(
                block
                for block in recovered.content_blocks
                if block.get("block_type") == "table"
                and project_id in block["rows"][0][0]["text"]
            )
            self.assertEqual(expected_role, table["structured_table"]["role"])
            self.assertIn("历史角色兼容测试修订", table["rows"][0][0]["text"])
            self.assertEqual([], restarted.runtime_store.verify_audit_chain(project_id))

    def test_legacy_table_role_hydration_does_not_overwrite_an_explicit_role(self):
        source = {
            "block_id": "table-role-source",
            "block_type": "table",
            "source_locator": "docx:table:7",
            "structured_table": {"role": "layout"},
            "rows": [],
        }
        candidate = deepcopy(source)
        candidate["structured_table"]["role"] = "body_content"

        hydrated = self.repository._hydrate_legacy_working_copy_formatting(
            [source],
            [candidate],
        )

        self.assertEqual("body_content", hydrated[0]["structured_table"]["role"])

    def test_rux_source_docx_image_table_is_immutable_and_survives_restart(self):
        project_id = "proj_rux_03_002"
        session = self.documents.document_session(project_id)
        section = next(
            self.documents.section(project_id, summary.section_id)
            for summary in session.sections
            if any(
                block.get("figure_kind") == "source_docx_image"
                for block in self.documents.section(
                    project_id,
                    summary.section_id,
                ).content_blocks
            )
        )
        blocks = deepcopy(section.content_blocks)
        source_image = next(
            block
            for block in blocks
            if block.get("figure_kind") == "source_docx_image"
        )
        saved = self.repository.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=session.document_id,
                expected_revision=0,
                content_blocks=blocks,
                actor="medical_manager_test",
                idempotency_key="real-rux-source-image-save",
            ),
        )

        restarted = MedicalWritingRuntimeRepository(
            MedicalWritingDocumentService(),
            SqliteRuntimeStore(self.db_path),
        )
        recovered = restarted.working_copy(project_id, section.section_id)
        recovered_image = next(
            block
            for block in recovered.content_blocks
            if block.get("figure_kind") == "source_docx_image"
        )
        for field in (
            "block_id",
            "figure_id",
            "title",
            "semantic_role",
            "source_locator",
            "media_part_name",
            "media_type",
            "image_base64",
            "image_sha256",
            "source_caption",
        ):
            self.assertEqual(source_image[field], recovered_image[field])
        self.assertEqual(1, saved.revision)
        self.assertEqual([], restarted.runtime_store.verify_audit_chain(project_id))

        without_image = [
            block
            for block in deepcopy(recovered.content_blocks)
            if block.get("block_id") != recovered_image["block_id"]
        ]
        with self.assertRaisesRegex(
            ValueError,
            "preserve every canonical source block",
        ):
            restarted.save_working_copy(
                project_id,
                section.section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=session.document_id,
                    expected_revision=1,
                    content_blocks=without_image,
                    actor="medical_manager_test",
                    idempotency_key="real-rux-source-image-delete",
                ),
            )

        tampered = deepcopy(recovered.content_blocks)
        tampered_image = next(
            block
            for block in tampered
            if block.get("figure_kind") == "source_docx_image"
        )
        tampered_image["title"] = "表 8 被篡改的题注"
        with self.assertRaisesRegex(
            ValueError,
            "may not change source-linked title",
        ):
            restarted.save_working_copy(
                project_id,
                section.section_id,
                MedicalWritingWorkingCopySaveRequest(
                    document_id=session.document_id,
                    expected_revision=1,
                    content_blocks=tampered,
                    actor="medical_manager_test",
                    idempotency_key="real-rux-source-image-tamper",
                ),
            )


if __name__ == "__main__":
    unittest.main()
