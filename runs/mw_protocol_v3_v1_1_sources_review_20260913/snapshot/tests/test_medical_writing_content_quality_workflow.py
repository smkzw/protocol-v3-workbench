from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from packages.contracts.workbench_contracts import (
    ApprovalState,
    MedicalWritingContentDispositionRequest,
    MedicalWritingContentDispositionStatus,
    MedicalWritingWorkingCopySaveRequest,
    ProtocolDocument,
    ProtocolSection,
)
from packages.contracts.workbench_contracts.models import (
    MedicalWritingSectionFreezeRequest,
)
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import (
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


PROJECT_ID = "proj_content_quality_workflow"
SECTION_ID = "mwsec_content_quality_workflow"


class MutableDocumentService:
    def __init__(self):
        self.document = ProtocolDocument(
            document_id="mwdoc_content_quality_workflow",
            project_id=PROJECT_ID,
            protocol_id="CONTENT-QUALITY-WORKFLOW",
            version="V1.0",
            sections=[
                ProtocolSection(
                    section_id=SECTION_ID,
                    document_id="mwdoc_content_quality_workflow",
                    heading="附录 避孕要求",
                    approval_state=ApprovalState.IN_MEDICAL_REVIEW,
                    content_blocks=[
                        {
                            "block_id": "source_table_10_block",
                            "block_type": "table",
                            "table_id": "source_table_10",
                            "source_kind": "original_protocol_docx",
                            "source_locator": "docx:table:10",
                            "rows": [
                                [
                                    {
                                        "cell_id": "source_cell_10_2_0",
                                        "text": "对于研究中具有生育能力的女性受试者：<0}",
                                        "source_locator": "docx:table:10:row:2:cell:0",
                                        "row_index": 2,
                                        "cell_index": 0,
                                    }
                                ]
                            ],
                        }
                    ],
                )
            ],
        )

    def document_session(self, project_id: str) -> ProtocolDocument:
        assert project_id == PROJECT_ID
        session = self.document.model_copy(deep=True)
        session.sections = [
            section.model_copy(update={"content_blocks": []}, deep=True)
            for section in session.sections
        ]
        return session

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        assert project_id == PROJECT_ID
        return self.document.model_copy(deep=True)

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        assert project_id == PROJECT_ID
        return next(
            section.model_copy(deep=True)
            for section in self.document.sections
            if section.section_id == section_id
        )


class MedicalWritingContentQualityWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "runtime.sqlite3"
        self.documents = MutableDocumentService()
        self.store = SqliteRuntimeStore(self.db_path)
        self.repository = MedicalWritingRuntimeRepository(self.documents, self.store)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _request(self, finding, status, *, revision=0, key="content-quality-action-001"):
        return MedicalWritingContentDispositionRequest(
            status=status,
            reason="医学经理已核对原始方案及上下文，确认该项按当前处置执行。",
            actor="medical_manager_test",
            expected_content_fingerprint=finding.content_fingerprint,
            expected_content_revision=finding.content_revision,
            expected_disposition_revision=revision,
            idempotency_key=key,
        )

    def _save_source_as_working_copy(self):
        source = self.documents.section(PROJECT_ID, SECTION_ID)
        return self.repository.save_working_copy(
            PROJECT_ID,
            SECTION_ID,
            MedicalWritingWorkingCopySaveRequest(
                document_id=source.document_id,
                expected_revision=0,
                content_blocks=deepcopy(source.content_blocks),
                actor="medical_manager_test",
                idempotency_key="save-content-quality-working-copy",
            ),
        )

    def _freeze(self, working_copy, *, key="freeze-content-quality-section"):
        return self.repository.freeze_current_version(
            PROJECT_ID,
            SECTION_ID,
            MedicalWritingSectionFreezeRequest(
                document_id=working_copy.document_id,
                expected_working_copy_revision=working_copy.revision,
                actor="medical_manager_test",
                reason="医学作者已核对当前章节并确认冻结。",
                idempotency_key=key,
            ),
        )

    def test_disposition_survives_restart_but_changed_text_invalidates_confirmation(self):
        original = self.repository.content_quality(PROJECT_ID, SECTION_ID).findings[0]
        confirmed = self.repository.apply_content_disposition(
            PROJECT_ID,
            original.finding_id,
            self._request(
                original,
                MedicalWritingContentDispositionStatus.CONFIRMED_SOURCE_TEXT,
            ),
        )
        self.assertEqual("confirmed_source_text", confirmed.disposition_status)
        self.assertEqual(1, confirmed.disposition_revision)

        restarted = MedicalWritingRuntimeRepository(
            self.documents,
            SqliteRuntimeStore(self.db_path),
        )
        persisted = restarted.content_quality(PROJECT_ID, SECTION_ID).findings[0]
        self.assertEqual("confirmed_source_text", persisted.disposition_status)
        self.assertEqual(1, persisted.disposition_revision)
        self.assertEqual([], restarted.runtime_store.verify_audit_chain(PROJECT_ID))

        self.documents.document.sections[0].content_blocks[0]["rows"][0][0][
            "text"
        ] = "对于研究中具有生育能力的女性受试者，仍需确认：<0}"
        changed = restarted.content_quality(PROJECT_ID, SECTION_ID).findings[0]
        self.assertEqual(original.finding_id, changed.finding_id)
        self.assertNotEqual(original.content_fingerprint, changed.content_fingerprint)
        self.assertEqual("open", changed.disposition_status)
        self.assertEqual(1, changed.disposition_revision)

        with self.assertRaises(StaleRuntimeStateError):
            restarted.apply_content_disposition(
                PROJECT_ID,
                changed.finding_id,
                self._request(
                    original,
                    MedicalWritingContentDispositionStatus.CORRECTION_REQUIRED,
                    key="content-quality-stale-action",
                ),
            )

    def test_unresolved_finding_blocks_final_export_but_not_author_freeze_or_draft(self):
        working_copy = self._save_source_as_working_copy()

        draft = self.repository.assemble_document_for_export(PROJECT_ID, "draft_preview")
        self.assertEqual("draft_preview", draft.status)
        frozen = self._freeze(working_copy)
        self.assertEqual("frozen", frozen.working_copy.freeze_status)
        with self.assertRaisesRegex(RuntimeStoreError, "content quality"):
            self.repository.assemble_document_for_export(PROJECT_ID, "approved_final")

    def test_confirmation_allows_frozen_final_while_reopen_blocks_final_export(self):
        working_copy = self._save_source_as_working_copy()
        finding = self.repository.content_quality(PROJECT_ID, SECTION_ID).findings[0]
        confirmed = self.repository.apply_content_disposition(
            PROJECT_ID,
            finding.finding_id,
            self._request(
                finding,
                MedicalWritingContentDispositionStatus.CONFIRMED_SOURCE_TEXT,
                key="content-quality-confirm-before-approval",
            ),
        )
        frozen = self._freeze(
            working_copy, key="freeze-content-quality-confirmed"
        )
        self.assertEqual("frozen", frozen.working_copy.freeze_status)
        final_document = self.repository.assemble_document_for_export(
            PROJECT_ID,
            "approved_final",
        )
        self.assertEqual("author_frozen_final", final_document.status)

        reopened = self.repository.apply_content_disposition(
            PROJECT_ID,
            confirmed.finding_id,
            self._request(
                confirmed,
                MedicalWritingContentDispositionStatus.OPEN,
                revision=1,
                key="content-quality-reopen-after-approval",
            ),
        )
        self.assertEqual("open", reopened.disposition_status)
        with self.assertRaisesRegex(RuntimeStoreError, "content quality"):
            self.repository.assemble_document_for_export(PROJECT_ID, "approved_final")


if __name__ == "__main__":
    unittest.main()
