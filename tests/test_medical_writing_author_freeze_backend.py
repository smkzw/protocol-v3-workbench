from __future__ import annotations

import json
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    ApprovalAction,
    ApprovalDecisionRecord,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    MedicalWritingRevisionApplyRequest,
    MedicalWritingWorkingCopy,
    MedicalWritingWorkingCopyBindingRecoveryRequest,
    MedicalWritingWorkingCopySaveRequest,
    ProtocolDocument,
    ProtocolSection,
    RevisionSuggestion,
    RevisionThread,
)
from packages.contracts.workbench_contracts.models import (
    MedicalWritingSectionFreezeRequest,
)
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app import main as app_main
from services.api.app.medical_writing_study_consistency import (
    MedicalWritingStudyConsistencyService,
)
from services.api.app.medical_writing_table_templates import (
    MedicalWritingTableTemplateService,
)
from services.api.app.medical_writing_tables import MedicalWritingTableService
from services.api.app.sqlite_runtime_store import (
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


NOW = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
DEFINITION_ID = "mwdef_author_freeze"
DEFINITION_REVISION = 3
DEFINITION_SHA = "a" * 64
PROJECT_A = "proj_author_freeze_a"
PROJECT_B = "proj_author_freeze_b"


@dataclass
class Definition:
    definition_id: str = DEFINITION_ID
    revision: int = DEFINITION_REVISION
    state_sha256: str = DEFINITION_SHA


@dataclass
class Journey:
    study_definition: Definition = field(default_factory=Definition)
    invalidated_dependents: list[str] = field(default_factory=list)


class JourneyService:
    def __init__(self, project_ids: tuple[str, ...]):
        self.projects = {project_id: Journey() for project_id in project_ids}

    def has_project(self, project_id: str) -> bool:
        return project_id in self.projects

    def get(self, project_id: str) -> Journey:
        return self.projects[project_id]


class DocumentService:
    def __init__(self, project_ids: tuple[str, ...]):
        self.documents: dict[str, ProtocolDocument] = {}
        for project_id in project_ids:
            token = project_id.rsplit("_", 1)[-1]
            document_id = f"mwdoc_author_freeze_{token}"
            table = MedicalWritingTableTemplateService().instantiate(
                "analysis_sets",
                title="分析集定义",
                instance_id=f"author-freeze-{token}",
            )
            table["source_kind"] = "original_protocol_docx"
            table["source_locator"] = "docx:table:1"
            table["structured_table"]["source_lineage"] = ["docx:table:1"]
            self.documents[project_id] = ProtocolDocument(
                document_id=document_id,
                project_id=project_id,
                protocol_id=f"FREEZE-{token.upper()}",
                version="V1.0",
                source_study_definition_id=DEFINITION_ID,
                source_study_definition_revision=DEFINITION_REVISION,
                source_study_definition_sha256=DEFINITION_SHA,
                sections=[
                    ProtocolSection(
                        section_id=f"mwsec_author_freeze_{token}",
                        document_id=document_id,
                        heading="研究目的",
                        content_blocks=[
                            {
                                "block_id": f"paragraph_{token}",
                                "block_type": "paragraph",
                                "text": f"{token} 原始章节正文。",
                                "source_locator": "docx:paragraph:10",
                            },
                            table,
                        ],
                    ),
                    ProtocolSection(
                        section_id=f"mwsec_omitted_{token}",
                        document_id=document_id,
                        heading="不适用章节",
                        applicability_status="not_applicable",
                        applicability_render_action="omit",
                        content_blocks=[],
                    ),
                ],
            )

    def document_session(self, project_id: str) -> ProtocolDocument:
        return self.documents[project_id].model_copy(deep=True)

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        return self.document_session(project_id)

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        return next(
            section.model_copy(deep=True)
            for section in self.documents[project_id].sections
            if section.section_id == section_id
        )


@pytest.fixture()
def author_freeze_runtime():
    temporary = tempfile.TemporaryDirectory()
    documents = DocumentService((PROJECT_A, PROJECT_B))
    journeys = JourneyService((PROJECT_A, PROJECT_B))
    store = SqliteRuntimeStore(Path(temporary.name) / "runtime.sqlite3")
    consistency = MedicalWritingStudyConsistencyService(
        documents,
        journeys,
        runtime_store=store,
    )
    repository = MedicalWritingRuntimeRepository(documents, store, consistency)
    try:
        yield temporary, documents, journeys, store, repository
    finally:
        temporary.cleanup()


def _section(documents: DocumentService, project_id: str) -> ProtocolSection:
    return documents.documents[project_id].sections[0]


def _save(
    repository: MedicalWritingRuntimeRepository,
    documents: DocumentService,
    project_id: str,
    *,
    expected_revision: int = 0,
    blocks: list[dict] | None = None,
    key: str = "save-author-freeze-r1",
):
    section = _section(documents, project_id)
    return repository.save_working_copy(
        project_id,
        section.section_id,
        MedicalWritingWorkingCopySaveRequest(
            document_id=section.document_id,
            expected_revision=expected_revision,
            content_blocks=blocks or section.content_blocks,
            actor="medical_manager",
            idempotency_key=key,
        ),
    )


def _freeze_request(
    documents: DocumentService,
    project_id: str,
    revision: int,
    *,
    key: str = "freeze-author-version-001",
    binding: tuple[str, int | None, str] = (
        DEFINITION_ID,
        DEFINITION_REVISION,
        DEFINITION_SHA,
    ),
) -> MedicalWritingSectionFreezeRequest:
    return MedicalWritingSectionFreezeRequest(
        document_id=documents.documents[project_id].document_id,
        expected_working_copy_revision=revision,
        expected_study_definition_id=binding[0],
        expected_study_definition_revision=binding[1],
        expected_study_definition_sha256=binding[2],
        reason="医学作者已完成本章节内容、表格和来源核对，确认冻结当前版本。",
        actor="medical_manager",
        idempotency_key=key,
    )


def _freeze(
    repository: MedicalWritingRuntimeRepository,
    documents: DocumentService,
    project_id: str,
    revision: int = 1,
    *,
    key: str = "freeze-author-version-001",
):
    section = _section(documents, project_id)
    return repository.freeze_current_version(
        project_id,
        section.section_id,
        _freeze_request(documents, project_id, revision, key=key),
    )


def test_freeze_is_idempotent_audited_and_final_export_uses_current_snapshot(
    author_freeze_runtime,
):
    _, documents, _, store, repository = author_freeze_runtime
    saved = _save(repository, documents, PROJECT_A)

    frozen = _freeze(repository, documents, PROJECT_A, saved.revision)
    repeated = _freeze(
        repository,
        documents,
        PROJECT_A,
        saved.revision,
        key="freeze-author-version-different-key",
    )

    assert frozen.working_copy.freeze_status == "frozen"
    assert frozen.working_copy.approval_state == ApprovalState.AI_DRAFT
    assert repeated.replayed is True
    assert repeated.freeze_record.snapshot_id == frozen.freeze_record.snapshot_id
    history = repository.section_freeze_history(
        PROJECT_A, _section(documents, PROJECT_A).section_id
    )
    assert len(history) == 1
    assert history[0].is_current is True
    readiness = repository.final_freeze_readiness(PROJECT_A)
    assert readiness.ready is True
    assert readiness.required_section_count == 1
    assert readiness.omitted_not_applicable_section_count == 1
    final = repository.assemble_document_for_export(PROJECT_A, "approved_final")
    assert final.status == "author_frozen_final"
    assert store.verify_audit_chain(PROJECT_A) == []


def test_stale_revision_cross_project_and_binding_drift_fail_closed(
    author_freeze_runtime,
):
    _, documents, journeys, _, repository = author_freeze_runtime
    saved = _save(repository, documents, PROJECT_A)
    section = _section(documents, PROJECT_A)

    with pytest.raises(StaleRuntimeStateError, match="stale section freeze revision"):
        repository.freeze_current_version(
            PROJECT_A,
            section.section_id,
            _freeze_request(documents, PROJECT_A, saved.revision + 1),
        )
    foreign_request = _freeze_request(documents, PROJECT_B, saved.revision)
    with pytest.raises(RuntimeStoreError, match="canonical project document"):
        repository.freeze_current_version(
            PROJECT_A, section.section_id, foreign_request
        )

    journeys.projects[PROJECT_A].study_definition.revision += 1
    journeys.projects[PROJECT_A].study_definition.state_sha256 = "b" * 64
    with pytest.raises(RuntimeStoreError, match="unbound|stale"):
        repository.freeze_current_version(
            PROJECT_A,
            section.section_id,
            _freeze_request(documents, PROJECT_A, saved.revision),
        )


def test_body_and_structured_table_edits_invalidate_only_current_freeze(
    author_freeze_runtime,
):
    _, documents, _, _, repository = author_freeze_runtime
    saved = _save(repository, documents, PROJECT_A)
    first_freeze = _freeze(repository, documents, PROJECT_A, saved.revision)
    blocks = [dict(block) for block in first_freeze.working_copy.content_blocks]
    blocks[0] = dict(blocks[0])
    blocks[0]["text"] = "作者修改后的章节正文。"
    edited = _save(
        repository,
        documents,
        PROJECT_A,
        expected_revision=saved.revision,
        blocks=blocks,
        key="save-after-body-freeze",
    )
    assert edited.freeze_status == "editable"
    assert edited.frozen_snapshot_id is None
    assert len(
        repository.section_freeze_history(
            PROJECT_A, _section(documents, PROJECT_A).section_id
        )
    ) == 1

    second_freeze = _freeze(
        repository,
        documents,
        PROJECT_A,
        edited.revision,
        key="freeze-after-body-edit",
    )
    table_index = next(
        index
        for index, block in enumerate(second_freeze.working_copy.content_blocks)
        if block.get("block_type") == "table"
    )
    table_service = MedicalWritingTableService()
    table = table_service.from_table_block(
        second_freeze.working_copy.content_blocks[table_index]
    )
    editable_cell = next(cell for row in table.rows[1:] for cell in row.cells)
    updated_table = table_service.apply_operations(
        table,
        [{"op": "edit_cell", "cell_id": editable_cell.cell_id, "text": "更新后的分析集定义"}],
        expected_version=table.version,
    )
    table_blocks = [dict(block) for block in second_freeze.working_copy.content_blocks]
    table_blocks[table_index] = table_service.to_table_block(updated_table)
    table_edited = _save(
        repository,
        documents,
        PROJECT_A,
        expected_revision=edited.revision,
        blocks=table_blocks,
        key="save-after-table-freeze",
    )
    assert table_edited.freeze_status == "editable"
    assert len(
        repository.section_freeze_history(
            PROJECT_A, _section(documents, PROJECT_A).section_id
        )
    ) == 2


def test_selected_ai_candidate_application_invalidates_freeze_without_approval_gate(
    author_freeze_runtime,
):
    _, documents, _, store, repository = author_freeze_runtime
    saved = _save(repository, documents, PROJECT_A)
    frozen = _freeze(repository, documents, PROJECT_A, saved.revision)
    section = _section(documents, PROJECT_A)
    selected_text = frozen.working_copy.content_blocks[0]["text"]
    thread = RevisionThread(
        thread_id="thread_author_selected_001",
        project_id=PROJECT_A,
        document_id=section.document_id,
        section_id=section.section_id,
        anchor_type="paragraph",
        anchor_path="docx:paragraph:10",
        selected_text=selected_text,
        user_instruction="请优化表述。",
        intent="rewrite",
        ai_run_id="ai_run_author_selected_001",
        source_study_definition_id=DEFINITION_ID,
        source_study_definition_revision=DEFINITION_REVISION,
        source_study_definition_sha256=DEFINITION_SHA,
        source_working_copy_id=frozen.working_copy.working_copy_id,
        source_working_copy_revision=frozen.working_copy.revision,
        source_working_copy_content_sha256=repository._payload_hash(
            frozen.working_copy.content_blocks
        ),
        suggestions=[
            RevisionSuggestion(
                suggestion_id="suggestion_author_selected_001",
                proposal_text="作者选中的AI候选正文。",
                diff_patch="replace",
                rationale="表述更清晰。",
                user_decision="accepted",
                fact_adoption_status="adopted_as_project_fact",
            )
        ],
        status="author_selected",
        created_at=NOW,
        resolved_at=NOW,
    )
    store.commit_medical_writing_revision_submission(
        thread,
        AuditEvent(
            audit_id="audit_author_selected_thread",
            project_id=PROJECT_A,
            actor="medical_manager",
            action="medical_writing_revision_submitted",
            target_type="revision_thread",
            target_id=thread.thread_id,
            created_at=NOW,
        ),
    )

    applied = repository.apply_approved_revision_to_working_copy(
        PROJECT_A,
        section.section_id,
        thread.thread_id,
        MedicalWritingRevisionApplyRequest(
            expected_working_copy_revision=frozen.working_copy.revision,
            actor="medical_manager",
            idempotency_key="apply-author-selected-001",
        ),
    )
    assert applied.working_copy.freeze_status == "editable"
    assert applied.working_copy.content_blocks[0]["text"] == "作者选中的AI候选正文。"
    assert repository.approvals(PROJECT_A) == []


@pytest.mark.parametrize(
    "operation",
    ["accept_and_bind", "revert_to_authoritative_baseline"],
)
def test_binding_recovery_advances_revision_and_clears_historical_freeze(
    author_freeze_runtime,
    operation: str,
):
    _, documents, _, store, repository = author_freeze_runtime
    documents.documents[PROJECT_A] = documents.documents[PROJECT_A].model_copy(
        update={
            "source_study_definition_id": "",
            "source_study_definition_revision": None,
            "source_study_definition_sha256": "",
        },
        deep=True,
    )
    section = _section(documents, PROJECT_A)
    frozen_snapshot_id = f"legacy_freeze_{operation}"
    legacy = MedicalWritingWorkingCopy(
        working_copy_id=f"working_copy_{operation}",
        project_id=PROJECT_A,
        document_id=section.document_id,
        section_id=section.section_id,
        source_document_version="V1.0",
        revision=1,
        content_blocks=section.content_blocks,
        approval_state=ApprovalState.AI_DRAFT,
        freeze_status="frozen",
        frozen_revision=1,
        frozen_snapshot_id=frozen_snapshot_id,
        frozen_by="medical_manager",
        frozen_at=NOW,
        frozen_study_definition_id="mwdef_old",
        frozen_study_definition_revision=1,
        frozen_study_definition_sha256="c" * 64,
        source_study_definition_id="mwdef_old",
        source_study_definition_revision=1,
        source_study_definition_sha256="c" * 64,
        created_by="medical_manager",
        updated_by="medical_manager",
        created_at=NOW,
        updated_at=NOW,
    )
    store.commit_medical_writing_working_copy_save(
        legacy,
        AuditEvent(
            audit_id=f"audit_seed_{operation}",
            project_id=PROJECT_A,
            actor="medical_manager",
            action="medical_writing_working_copy_saved",
            target_type="medical_writing_working_copy",
            target_id=legacy.working_copy_id,
            created_at=NOW,
        ),
        expected_revision=0,
        idempotency_key=f"seed-{operation}",
        request_fingerprint=f"seed-{operation}",
    )
    request = MedicalWritingWorkingCopyBindingRecoveryRequest(
        document_id=section.document_id,
        expected_working_copy_revision=1,
        reason="医学作者核对了历史正文与当前StudyDefinition，确认执行受控恢复。",
        acknowledge_binding=True,
        actor="medical_manager",
        idempotency_key=f"recover-{operation}",
    )
    result = (
        repository.accept_and_bind_working_copy(PROJECT_A, section.section_id, request)
        if operation == "accept_and_bind"
        else repository.revert_to_authoritative_baseline(
            PROJECT_A, section.section_id, request
        )
    )
    assert result.working_copy.revision == 2
    assert result.working_copy.freeze_status == "editable"
    assert result.working_copy.frozen_snapshot_id is None


@pytest.mark.parametrize(
    "fault_checkpoint",
    [
        "after_section_freeze_snapshot",
        "after_section_freeze_legacy_gate_retirement",
        "after_section_freeze_runtime_audit",
    ],
)
def test_freeze_transaction_fault_rolls_back_every_record(
    author_freeze_runtime,
    fault_checkpoint: str,
):
    temporary, documents, journeys, _, repository = author_freeze_runtime
    saved = _save(repository, documents, PROJECT_A)
    section = _section(documents, PROJECT_A)
    legacy_gate = ApprovalGate(
        approval_id=f"approval_legacy_fault_{fault_checkpoint}",
        project_id=PROJECT_A,
        target_type="medical_writing_working_copy",
        target_id=saved.working_copy_id,
        target_revision=saved.revision,
        state=ApprovalState.IN_MEDICAL_REVIEW,
        requested_by="medical_manager",
        created_at=NOW,
        updated_at=NOW,
    )
    stored_saved = repository.runtime_store.medical_writing_working_copy_by_id(
        PROJECT_A, saved.working_copy_id
    )
    repository.runtime_store.ensure_medical_writing_approval_gate(
        legacy_gate,
        stored_saved,
        stored_saved.model_copy(
            update={"approval_state": ApprovalState.IN_MEDICAL_REVIEW}, deep=True
        ),
    )

    def fail(checkpoint: str):
        if checkpoint == fault_checkpoint:
            raise RuntimeError("injected freeze failure")

    failing_store = SqliteRuntimeStore(
        Path(temporary.name) / "runtime.sqlite3",
        fault_injector=fail,
    )
    failing_consistency = MedicalWritingStudyConsistencyService(
        documents,
        journeys,
        runtime_store=failing_store,
    )
    failing_repository = MedicalWritingRuntimeRepository(
        documents, failing_store, failing_consistency
    )
    with pytest.raises(RuntimeError, match="injected freeze failure"):
        _freeze(failing_repository, documents, PROJECT_A, saved.revision)

    clean_store = SqliteRuntimeStore(Path(temporary.name) / "runtime.sqlite3")
    clean_repository = MedicalWritingRuntimeRepository(
        documents,
        clean_store,
        MedicalWritingStudyConsistencyService(
            documents, journeys, runtime_store=clean_store
        ),
    )
    current = clean_repository.working_copy(
        PROJECT_A, section.section_id
    )
    assert current.freeze_status == "editable"
    assert not any(
        item["snapshot_type"] == "author_freeze"
        for item in clean_store.medical_writing_working_copy_snapshots(
            PROJECT_A, current.working_copy_id
        )
    )
    assert not any(
        event.action == "medical_writing_section_version_frozen"
        for event in clean_store.workflow_audit_events(
            PROJECT_A, "medical_writing_section_freeze"
        )
    )
    persisted_legacy_gate = next(
        gate
        for gate in clean_store.gates(PROJECT_A)
        if gate.approval_id == legacy_gate.approval_id
    )
    assert persisted_legacy_gate.state == ApprovalState.IN_MEDICAL_REVIEW


def test_legacy_medical_writing_states_map_without_blocking_and_monitoring_approval_survives(
    author_freeze_runtime,
):
    _, documents, _, store, repository = author_freeze_runtime
    section = _section(documents, PROJECT_A)
    legacy_audit_id = "audit_legacy_medically_approved"
    legacy_snapshot_id = f"snapshot_{legacy_audit_id}"
    legacy = MedicalWritingWorkingCopy(
        working_copy_id="working_copy_legacy_medically_approved",
        project_id=PROJECT_A,
        document_id=section.document_id,
        section_id=section.section_id,
        source_document_version="V1.0",
        revision=1,
        content_blocks=section.content_blocks,
        approval_state=ApprovalState.MEDICALLY_APPROVED,
        approved_revision=1,
        approved_snapshot_id=legacy_snapshot_id,
        content_authority_state="active_authoritative",
        source_study_definition_id=DEFINITION_ID,
        source_study_definition_revision=DEFINITION_REVISION,
        source_study_definition_sha256=DEFINITION_SHA,
        created_by="legacy_medical_manager",
        updated_by="legacy_medical_manager",
        created_at=NOW,
        updated_at=NOW,
    )
    store.commit_medical_writing_working_copy_save(
        legacy,
        AuditEvent(
            audit_id=legacy_audit_id,
            project_id=PROJECT_A,
            actor="legacy_medical_manager",
            action="legacy_medical_writing_approval_imported",
            target_type="medical_writing_working_copy",
            target_id=legacy.working_copy_id,
            created_at=NOW,
        ),
        expected_revision=0,
        idempotency_key="legacy-medically-approved",
        request_fingerprint="legacy-medically-approved",
        operation="legacy_medical_writing_approval_import",
        snapshot_type="approval",
    )
    legacy_freeze_keys = {
        "freeze_status",
        "frozen_revision",
        "frozen_snapshot_id",
        "frozen_by",
        "frozen_at",
        "frozen_study_definition_id",
        "frozen_study_definition_revision",
        "frozen_study_definition_sha256",
    }
    with sqlite3.connect(store.db_path) as connection:
        current_payload = json.loads(
            connection.execute(
                """
                SELECT payload_json FROM medical_writing_working_copies
                WHERE project_id = ? AND working_copy_id = ?
                """,
                (PROJECT_A, legacy.working_copy_id),
            ).fetchone()[0]
        )
        snapshot_payload = json.loads(
            connection.execute(
                """
                SELECT payload_json FROM medical_writing_working_copy_snapshots
                WHERE project_id = ? AND snapshot_id = ?
                """,
                (PROJECT_A, legacy_snapshot_id),
            ).fetchone()[0]
        )
        for key in legacy_freeze_keys:
            current_payload.pop(key, None)
            snapshot_payload.pop(key, None)
        connection.execute(
            """
            UPDATE medical_writing_working_copies SET payload_json = ?
            WHERE project_id = ? AND working_copy_id = ?
            """,
            (
                json.dumps(current_payload, ensure_ascii=False),
                PROJECT_A,
                legacy.working_copy_id,
            ),
        )
        snapshot_trigger_sql = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'trigger'
              AND name = 'trg_medical_writing_working_copy_snapshot_no_update'
            """
        ).fetchone()[0]
        connection.execute(
            "DROP TRIGGER trg_medical_writing_working_copy_snapshot_no_update"
        )
        connection.execute(
            """
            UPDATE medical_writing_working_copy_snapshots SET payload_json = ?
            WHERE project_id = ? AND snapshot_id = ?
            """,
            (
                json.dumps(snapshot_payload, ensure_ascii=False),
                PROJECT_A,
                legacy_snapshot_id,
            ),
        )
        connection.execute(snapshot_trigger_sql)
        connection.commit()
    visible = repository.working_copy(PROJECT_A, section.section_id)
    assert visible.approval_state == ApprovalState.AI_DRAFT
    assert visible.freeze_status == "frozen"
    assert repository.final_freeze_readiness(PROJECT_A).ready is True

    monitoring_gate = ApprovalGate(
        approval_id="approval_monitoring_001",
        project_id=PROJECT_A,
        target_type="medical_monitoring_risk_disposition",
        target_id="risk_001",
        state=ApprovalState.MEDICALLY_APPROVED,
        requested_by="medical_monitor",
        reviewed_by="medical_manager",
        approved_by="medical_manager",
        created_at=NOW,
        updated_at=NOW,
    )
    monitoring_audit = AuditEvent(
        audit_id="audit_monitoring_approval_001",
        project_id=PROJECT_A,
        actor="medical_manager",
        action="approval.approve",
        target_type="approval_gate",
        target_id=monitoring_gate.approval_id,
        created_at=NOW,
    )
    monitoring_decision = ApprovalDecisionRecord(
        decision_id="decision_monitoring_approval_001",
        approval_id=monitoring_gate.approval_id,
        project_id=PROJECT_A,
        action=ApprovalAction.APPROVE,
        actor="medical_manager",
        previous_state=ApprovalState.IN_MEDICAL_REVIEW,
        new_state=ApprovalState.MEDICALLY_APPROVED,
        audit_event_id=monitoring_audit.audit_id,
        created_at=NOW,
    )
    store.commit_approval_action(
        monitoring_gate,
        monitoring_audit,
        monitoring_decision,
        idempotency_key="monitoring-approval-unaffected",
        request_fingerprint="monitoring-approval-unaffected",
    )
    assert next(
        gate
        for gate in store.gates(PROJECT_A)
        if gate.approval_id == monitoring_gate.approval_id
    ).state == ApprovalState.MEDICALLY_APPROVED


def test_legacy_in_review_state_is_editable_and_draft_preview_is_not_gated(
    author_freeze_runtime,
):
    _, documents, _, store, repository = author_freeze_runtime
    section = _section(documents, PROJECT_A)
    legacy = MedicalWritingWorkingCopy(
        working_copy_id="working_copy_legacy_in_review",
        project_id=PROJECT_A,
        document_id=section.document_id,
        section_id=section.section_id,
        source_document_version="V1.0",
        revision=1,
        content_blocks=section.content_blocks,
        approval_state=ApprovalState.IN_MEDICAL_REVIEW,
        content_authority_state="active_authoritative",
        source_study_definition_id=DEFINITION_ID,
        source_study_definition_revision=DEFINITION_REVISION,
        source_study_definition_sha256=DEFINITION_SHA,
        created_by="legacy_medical_manager",
        updated_by="legacy_medical_manager",
        created_at=NOW,
        updated_at=NOW,
    )
    store.commit_medical_writing_working_copy_save(
        legacy,
        AuditEvent(
            audit_id="audit_legacy_in_review",
            project_id=PROJECT_A,
            actor="legacy_medical_manager",
            action="legacy_medical_writing_review_imported",
            target_type="medical_writing_working_copy",
            target_id=legacy.working_copy_id,
            created_at=NOW,
        ),
        expected_revision=0,
        idempotency_key="legacy-in-review",
        request_fingerprint="legacy-in-review",
        operation="legacy_medical_writing_review_import",
    )
    visible = repository.working_copy(PROJECT_A, section.section_id)
    assert visible.approval_state == ApprovalState.AI_DRAFT
    assert repository.assemble_document_for_export(PROJECT_A, "draft_preview").status == "draft_preview"
    blocks = [dict(block) for block in visible.content_blocks]
    blocks[0] = dict(blocks[0])
    blocks[0]["text"] = "旧审阅状态迁移后的可编辑正文。"
    saved = _save(
        repository,
        documents,
        PROJECT_A,
        expected_revision=1,
        blocks=blocks,
        key="save-after-legacy-review",
    )
    assert saved.revision == 2
    assert saved.approval_state == ApprovalState.AI_DRAFT


def test_freeze_api_replaces_legacy_approval_route(author_freeze_runtime):
    _, documents, _, store, repository = author_freeze_runtime
    saved = _save(repository, documents, PROJECT_A)
    section = _section(documents, PROJECT_A)
    legacy_gate = ApprovalGate(
        approval_id="approval_working_copy_legacy_api",
        project_id=PROJECT_A,
        target_type="medical_writing_working_copy",
        target_id=saved.working_copy_id,
        target_revision=saved.revision,
        state=ApprovalState.IN_MEDICAL_REVIEW,
        requested_by="medical_manager",
        created_at=NOW,
        updated_at=NOW,
    )
    store.ensure_medical_writing_approval_gate(
        legacy_gate,
        store.medical_writing_working_copy_by_id(PROJECT_A, saved.working_copy_id),
        store.medical_writing_working_copy_by_id(
            PROJECT_A, saved.working_copy_id
        ).model_copy(
            update={"approval_state": ApprovalState.IN_MEDICAL_REVIEW}, deep=True
        ),
    )

    with (
        patch(
            "services.api.app.main.medical_writing_runtime_repository",
            repository,
        ),
        patch(
            "services.api.app.main._canonical_module_project_id",
            side_effect=lambda project_id, _module: project_id,
        ),
        patch(
            "services.api.app.main._canonical_project_id",
            side_effect=lambda project_id: project_id,
        ),
    ):
        client = TestClient(app_main.app)
        retired = client.post(
            f"/api/projects/{PROJECT_A}/approvals/{legacy_gate.approval_id}/actions",
            json={
                "action": "approve",
                "actor": "medical_manager",
                "comment": "不应再进入审批中心。",
                "idempotency_key": "legacy-approval-action",
            },
        )
        assert retired.status_code == 410

        freeze = client.post(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/freeze-current-version",
            json=_freeze_request(
                documents, PROJECT_A, saved.revision, key="freeze-via-api-001"
            ).model_dump(mode="json"),
        )
        assert freeze.status_code == 200, freeze.text
        assert freeze.json()["working_copy"]["freeze_status"] == "frozen"
        history = client.get(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/freeze-history"
        )
        assert history.status_code == 200
        assert len(history.json()) == 1
        readiness = client.get(
            f"/api/projects/{PROJECT_A}/medical-writing/freeze-readiness"
        )
        assert readiness.status_code == 200
        assert readiness.json()["ready"] is True
        unfreeze_request = _freeze_request(
            documents,
            PROJECT_A,
            saved.revision,
            key="unfreeze-via-api-001",
        ).model_copy(update={"reason": "作者需要继续修订本章节，显式解除当前冻结。"})
        unfrozen = client.post(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/unfreeze",
            json=unfreeze_request.model_dump(mode="json"),
        )
        assert unfrozen.status_code == 200, unfrozen.text
        assert unfrozen.json()["working_copy"]["freeze_status"] == "editable"
        repeated_unfreeze = client.post(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/unfreeze",
            json=unfreeze_request.model_dump(mode="json"),
        )
        assert repeated_unfreeze.status_code == 200
        assert repeated_unfreeze.json()["replayed"] is True
        history_after_unfreeze = client.get(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/freeze-history"
        )
        assert len(history_after_unfreeze.json()) == 1
        assert history_after_unfreeze.json()[0]["is_current"] is False
        readiness_after_unfreeze = client.get(
            f"/api/projects/{PROJECT_A}/medical-writing/freeze-readiness"
        )
        assert readiness_after_unfreeze.json()["ready"] is False
        obsolete_freeze_replay = client.post(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/freeze-current-version",
            json=_freeze_request(
                documents, PROJECT_A, saved.revision, key="freeze-via-api-001"
            ).model_dump(mode="json"),
        )
        assert obsolete_freeze_replay.status_code == 409
        assert "obsolete freeze" in obsolete_freeze_replay.json()["detail"]
        refreeze_request = _freeze_request(
            documents,
            PROJECT_A,
            saved.revision,
            key="refreeze-via-api-002",
        )
        refrozen = client.post(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/freeze-current-version",
            json=refreeze_request.model_dump(mode="json"),
        )
        assert refrozen.status_code == 200, refrozen.text
        obsolete_unfreeze_replay = client.post(
            f"/api/projects/{PROJECT_A}/medical-writing/working-copies/{section.section_id}/unfreeze",
            json=unfreeze_request.model_dump(mode="json"),
        )
        assert obsolete_unfreeze_replay.status_code == 409
        assert "obsolete unfreeze" in obsolete_unfreeze_replay.json()["detail"]
        retired_gate = next(
            gate
            for gate in store.gates(PROJECT_A)
            if gate.approval_id == legacy_gate.approval_id
        )
        assert retired_gate.state == ApprovalState.SUPERSEDED
