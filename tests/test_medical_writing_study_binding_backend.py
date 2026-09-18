from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.contracts.workbench_contracts import (
    ApprovalState,
    AuditEvent,
    MedicalWritingRevisionApplyRequest,
    MedicalWritingWorkingCopy,
    MedicalWritingWorkingCopyBindingRecoveryRequest,
    MedicalWritingWorkingCopySaveRequest,
    ProtocolDocument,
    ProtocolSection,
    RevisionSuggestion,
    RevisionAction,
    RevisionActionRequest,
    RevisionThread,
)
from services.api.app.medical_writing import MedicalWritingRevisionService
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.medical_writing_study_consistency import (
    MedicalWritingStudyConsistencyService,
)
from services.api.app.sqlite_runtime_store import (
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


NOW = datetime(2026, 7, 22, 8, 0, tzinfo=timezone.utc)
CURRENT_ID = "mwdef_binding_current"
CURRENT_REVISION = 4
CURRENT_SHA = "a" * 64


@dataclass
class Definition:
    definition_id: str = CURRENT_ID
    revision: int = CURRENT_REVISION
    state_sha256: str = CURRENT_SHA


@dataclass
class Journey:
    study_definition: Definition = field(default_factory=Definition)
    invalidated_dependents: list[str] = field(default_factory=list)


class JourneyService:
    def __init__(self, projects: tuple[str, ...]):
        self.projects = {project_id: Journey() for project_id in projects}

    def has_project(self, project_id: str) -> bool:
        return project_id in self.projects

    def get(self, project_id: str) -> Journey:
        return self.projects[project_id]


class ImportedDocumentService:
    def __init__(self, projects: tuple[str, ...]):
        self.documents: dict[str, ProtocolDocument] = {}
        for project_id in projects:
            token = project_id.removeprefix("proj_")
            document_id = f"mwdoc_{token}_imported"
            section = ProtocolSection(
                section_id=f"mwsec_{token}_objectives",
                document_id=document_id,
                heading="研究目的",
                content_blocks=[
                    {
                        "block_id": f"block_{token}_source",
                        "block_type": "paragraph",
                        "text": f"{token} 权威源基线。",
                        "source_locator": "docx:paragraph:10",
                        "source_kind": "original_protocol_docx",
                    }
                ],
            )
            self.documents[project_id] = ProtocolDocument(
                document_id=document_id,
                project_id=project_id,
                protocol_id=token.upper(),
                version="V1.0",
                sections=[section],
            )

    def document_session(self, project_id: str) -> ProtocolDocument:
        return self.documents[project_id].model_copy(deep=True)

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        return self.documents[project_id].model_copy(deep=True)

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        return next(
            section.model_copy(deep=True)
            for section in self.documents[project_id].sections
            if section.section_id == section_id
        )


@pytest.fixture()
def binding_runtime():
    temporary = tempfile.TemporaryDirectory()
    projects = ("proj_alpha", "proj_beta")
    documents = ImportedDocumentService(projects)
    store = SqliteRuntimeStore(Path(temporary.name) / "runtime.sqlite3")
    consistency = MedicalWritingStudyConsistencyService(
        documents,
        JourneyService(projects),
        runtime_store=store,
    )
    repository = MedicalWritingRuntimeRepository(documents, store, consistency)
    try:
        yield documents, store, repository, consistency
    finally:
        temporary.cleanup()


def _section(documents: ImportedDocumentService, project_id: str) -> ProtocolSection:
    return documents.documents[project_id].sections[0]


def _seed_quarantined_copy(
    documents: ImportedDocumentService,
    store: SqliteRuntimeStore,
    project_id: str,
    *,
    binding: tuple[str, int | None, str] = ("", None, ""),
    text: str = "旧项目正文，不得自动洗成当前绑定。",
) -> MedicalWritingWorkingCopy:
    section = _section(documents, project_id)
    block = dict(section.content_blocks[0])
    block["text"] = text
    working_copy = MedicalWritingWorkingCopy(
        working_copy_id=f"working_copy_{project_id}",
        project_id=project_id,
        document_id=section.document_id,
        section_id=section.section_id,
        source_document_version="V1.0",
        revision=1,
        content_blocks=[block],
        approval_state=ApprovalState.AI_DRAFT,
        source_study_definition_id=binding[0],
        source_study_definition_revision=binding[1],
        source_study_definition_sha256=binding[2],
        created_by="legacy_import",
        updated_by="legacy_import",
        created_at=NOW,
        updated_at=NOW,
    )
    audit = AuditEvent(
        audit_id=f"audit_seed_{project_id}",
        project_id=project_id,
        actor="legacy_import",
        action="medical_writing_working_copy_saved",
        target_type="medical_writing_working_copy",
        target_id=working_copy.working_copy_id,
        created_at=NOW,
    )
    store.commit_medical_writing_working_copy_save(
        working_copy,
        audit,
        expected_revision=0,
        idempotency_key=f"seed-{project_id}",
        request_fingerprint=f"seed-{project_id}",
    )
    return working_copy


def _recovery_request(
    documents: ImportedDocumentService,
    project_id: str,
    *,
    expected_revision: int,
    key: str,
) -> MedicalWritingWorkingCopyBindingRecoveryRequest:
    return MedicalWritingWorkingCopyBindingRecoveryRequest(
        document_id=documents.documents[project_id].document_id,
        expected_working_copy_revision=expected_revision,
        reason="医学作者已核对当前研究定义与待恢复正文，确认执行受控绑定。",
        acknowledge_binding=True,
        actor="medical_manager",
        idempotency_key=key,
    )


def test_unbound_read_is_quarantined_and_normal_save_cannot_launder(binding_runtime):
    documents, store, repository, _ = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    seeded = _seed_quarantined_copy(documents, store, project_id)

    visible = repository.working_copy(project_id, section.section_id)
    assert visible.content_authority_state == "historical_quarantined"
    assert visible.quarantined_revision == 1
    assert visible.content_blocks[0]["text"] == section.content_blocks[0]["text"]
    assert visible.content_blocks[0]["text"] != seeded.content_blocks[0]["text"]
    assert repository.historical_quarantined_working_copy(
        project_id, section.section_id
    ).content_blocks[0]["text"] == seeded.content_blocks[0]["text"]

    laundering = MedicalWritingWorkingCopySaveRequest(
        document_id=section.document_id,
        expected_revision=1,
        content_blocks=seeded.content_blocks,
        actor="medical_manager",
        idempotency_key="attempt-normal-launder",
    )
    with pytest.raises(RuntimeStoreError, match="unbound|stale|launder"):
        repository.save_working_copy(project_id, section.section_id, laundering)
    with pytest.raises(RuntimeStoreError):
        repository.assemble_document_for_export(project_id, "draft_preview")
    assert store.medical_writing_working_copy(
        project_id, section.document_id, section.section_id
    ).revision == 1


@pytest.mark.parametrize(
    "binding",
    [
        ("", None, ""),
        (CURRENT_ID, CURRENT_REVISION - 1, "b" * 64),
        ("mwdef_foreign", CURRENT_REVISION, CURRENT_SHA),
    ],
)
def test_missing_stale_and_foreign_binding_all_fail_closed(binding_runtime, binding):
    documents, store, repository, consistency = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    _seed_quarantined_copy(documents, store, project_id, binding=binding)
    assert repository.working_copy(
        project_id, section.section_id
    ).content_authority_state == "historical_quarantined"
    assert consistency.status(project_id).status == "binding_required"
    with pytest.raises(RuntimeStoreError):
        repository.assemble_document_for_export(project_id, "draft_preview")


def test_accept_and_bind_is_atomic_idempotent_and_preserves_source(binding_runtime):
    documents, store, repository, consistency = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    source_before = documents.documents[project_id].model_dump(mode="json")
    seeded = _seed_quarantined_copy(documents, store, project_id)
    request = _recovery_request(
        documents, project_id, expected_revision=1, key="accept-binding-once"
    )

    first = repository.accept_and_bind_working_copy(
        project_id, section.section_id, request
    )
    replay = repository.accept_and_bind_working_copy(
        project_id, section.section_id, request
    )
    assert first.working_copy.model_dump(mode="json") == replay.working_copy.model_dump(
        mode="json"
    )
    assert first.working_copy.revision == 2
    assert first.working_copy.content_authority_state == "active_authoritative"
    assert first.working_copy.content_blocks[0]["text"] == seeded.content_blocks[0]["text"]
    assert consistency.status(project_id).status == "current"
    assert repository.assemble_document_for_export(
        project_id, "draft_preview"
    ).sections[0].content_blocks[0]["text"] == seeded.content_blocks[0]["text"]
    assert documents.documents[project_id].model_dump(mode="json") == source_before

    snapshots = store.medical_writing_working_copy_snapshots(
        project_id, first.working_copy.working_copy_id
    )
    quarantines = [item for item in snapshots if item["snapshot_type"] == "historical_quarantine"]
    assert len(quarantines) == 1
    assert quarantines[0]["working_copy"].content_blocks[0]["text"] == seeded.content_blocks[0]["text"]
    historical = repository.historical_quarantined_working_copy(
        project_id, section.section_id
    )
    assert historical.content_authority_state == "historical_quarantined"
    assert historical.quarantined_revision == seeded.revision
    assert historical.content_blocks == seeded.content_blocks
    assert len(
        [
            event
            for event in store.workflow_audit_events(
                project_id, "medical_writing_working_copy"
            )
            if event.action == "medical_writing_working_copy_accepted_and_bound"
        ]
    ) == 1


def test_revert_creates_new_revision_from_source_and_keeps_quarantine(binding_runtime):
    documents, store, repository, _ = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    seeded = _seed_quarantined_copy(documents, store, project_id, text="应隔离的旧正文。")
    result = repository.revert_to_authoritative_baseline(
        project_id,
        section.section_id,
        _recovery_request(
            documents, project_id, expected_revision=1, key="revert-source-baseline"
        ),
    )
    assert result.working_copy.revision == 2
    assert result.working_copy.content_blocks == section.content_blocks
    assert result.working_copy.content_blocks != seeded.content_blocks
    quarantined = repository.runtime_store.medical_writing_working_copy_snapshots(
        project_id, result.working_copy.working_copy_id
    )
    assert any(item["snapshot_type"] == "historical_quarantine" for item in quarantined)


def test_imported_source_without_working_copy_gets_additive_binding(binding_runtime):
    documents, store, repository, consistency = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    source_before = documents.documents[project_id].model_dump(mode="json")

    result = repository.revert_to_authoritative_baseline(
        project_id,
        section.section_id,
        _recovery_request(
            documents, project_id, expected_revision=0, key="bind-pristine-import"
        ),
    )

    assert result.working_copy.revision == 1
    assert result.working_copy.content_blocks == section.content_blocks
    assert result.quarantined_snapshot_id == ""
    assert store.medical_writing_document_binding_sidecar(
        project_id, section.document_id
    ) == {
        "definition_id": CURRENT_ID,
        "definition_revision": CURRENT_REVISION,
        "definition_sha256": CURRENT_SHA,
        "audit_id": result.audit_event.audit_id,
        "created_at": result.audit_event.created_at,
    }
    assert not any(
        item["snapshot_type"] == "historical_quarantine"
        for item in store.medical_writing_working_copy_snapshots(
            project_id, result.working_copy.working_copy_id
        )
    )
    assert documents.documents[project_id].model_dump(mode="json") == source_before
    assert consistency.status(project_id).status == "current"
    assert repository.assemble_document_for_export(
        project_id, "draft_preview"
    ).sections[0].content_blocks == section.content_blocks


def test_cross_project_and_stale_recovery_are_rejected(binding_runtime):
    documents, store, repository, _ = binding_runtime
    alpha = "proj_alpha"
    beta = "proj_beta"
    alpha_section = _section(documents, alpha)
    _seed_quarantined_copy(documents, store, alpha)

    foreign = _recovery_request(
        documents, beta, expected_revision=1, key="foreign-document-bind"
    )
    with pytest.raises(RuntimeStoreError, match="does not match"):
        repository.accept_and_bind_working_copy(alpha, alpha_section.section_id, foreign)

    stale = _recovery_request(
        documents, alpha, expected_revision=0, key="stale-binding-revision"
    )
    with pytest.raises(StaleRuntimeStateError, match="stale"):
        repository.accept_and_bind_working_copy(alpha, alpha_section.section_id, stale)
    assert store.medical_writing_working_copy(
        alpha, alpha_section.document_id, alpha_section.section_id
    ).revision == 1


def test_partial_failure_rolls_back_sidecar_revision_snapshot_and_audit(binding_runtime):
    documents, store, repository, consistency = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    _seed_quarantined_copy(documents, store, project_id)
    baseline_snapshot_count = len(
        store.medical_writing_working_copy_snapshots(
            project_id, f"working_copy_{project_id}"
        )
    )
    store.fault_injector = lambda checkpoint: (
        (_ for _ in ()).throw(RuntimeError("injected binding failure"))
        if checkpoint == "after_working_copy_quarantine_snapshot"
        else None
    )
    with pytest.raises(RuntimeError, match="injected binding failure"):
        repository.accept_and_bind_working_copy(
            project_id,
            section.section_id,
            _recovery_request(
                documents, project_id, expected_revision=1, key="rollback-binding"
            ),
        )
    store.fault_injector = None
    assert store.medical_writing_working_copy(
        project_id, section.document_id, section.section_id
    ).revision == 1
    assert len(
        store.medical_writing_working_copy_snapshots(
            project_id, f"working_copy_{project_id}"
        )
    ) == baseline_snapshot_count
    assert store.medical_writing_document_binding_sidecar(
        project_id, section.document_id
    ) is None
    assert consistency.status(project_id).status == "binding_required"


def test_revision_thread_missing_binding_cannot_be_applied(binding_runtime):
    documents, store, repository, _ = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    _seed_quarantined_copy(documents, store, project_id)
    recovered = repository.revert_to_authoritative_baseline(
        project_id,
        section.section_id,
        _recovery_request(
            documents, project_id, expected_revision=1, key="bind-before-thread"
        ),
    ).working_copy
    thread = RevisionThread(
        thread_id="thread_unbound_legacy",
        project_id=project_id,
        document_id=section.document_id,
        section_id=section.section_id,
        anchor_type="paragraph",
        anchor_path="docx:paragraph:10",
        selected_text=section.content_blocks[0]["text"],
        user_instruction="优化研究目的。",
        intent="medical_writing_revision",
        ai_run_id="run_unbound_legacy",
        source_locator="docx:paragraph:10",
        suggestions=[
            RevisionSuggestion(
                suggestion_id="suggestion_unbound_legacy",
                proposal_text="修订候选。",
                diff_patch="replace",
                rationale="提高表达清晰度。",
                user_decision="accepted",
            )
        ],
        status="medically_approved",
        created_at=NOW,
        resolved_at=NOW,
    )
    store.commit_medical_writing_revision_submission(
        thread,
        AuditEvent(
            audit_id="audit_thread_unbound",
            project_id=project_id,
            actor="medical_manager",
            action="medical_writing_revision_submitted",
            target_type="revision_thread",
            target_id=thread.thread_id,
            created_at=NOW,
        ),
    )
    with pytest.raises(RuntimeStoreError, match="unbound or stale"):
        repository.apply_approved_revision_to_working_copy(
            project_id,
            section.section_id,
            thread.thread_id,
            MedicalWritingRevisionApplyRequest(
                expected_working_copy_revision=recovered.revision,
                actor="medical_manager",
                idempotency_key="apply-unbound-thread",
            ),
        )
    assert store.medical_writing_working_copy(
        project_id, section.document_id, section.section_id
    ).revision == recovered.revision


def test_candidate_acceptance_rejects_missing_revision_thread_binding(binding_runtime):
    documents, store, repository, _ = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    _seed_quarantined_copy(documents, store, project_id)
    repository.revert_to_authoritative_baseline(
        project_id,
        section.section_id,
        _recovery_request(
            documents, project_id, expected_revision=1, key="bind-before-unbound-candidate"
        ),
    )
    thread = RevisionThread(
        thread_id="thread_unbound_candidate",
        project_id=project_id,
        document_id=section.document_id,
        section_id=section.section_id,
        anchor_type="paragraph",
        anchor_path="docx:paragraph:10",
        selected_text=section.content_blocks[0]["text"],
        user_instruction="优化研究目的。",
        intent="medical_writing_revision",
        ai_run_id="run_unbound_candidate",
        source_locator="docx:paragraph:10",
        suggestions=[
            RevisionSuggestion(
                suggestion_id="suggestion_unbound_candidate",
                proposal_text="修订候选。",
                diff_patch="replace",
                rationale="提高表达清晰度。",
            )
        ],
        status="candidate_ready",
        created_at=NOW,
    )
    store.commit_medical_writing_revision_submission(
        thread,
        AuditEvent(
            audit_id="audit_thread_unbound_candidate",
            project_id=project_id,
            actor="medical_manager",
            action="medical_writing_revision_submitted",
            target_type="revision_thread",
            target_id=thread.thread_id,
            created_at=NOW,
        ),
    )

    service = MedicalWritingRevisionService(repository, None)
    with pytest.raises(RuntimeStoreError, match="unbound or stale"):
        service.apply_action(
            project_id,
            thread.thread_id,
            RevisionActionRequest(
                action=RevisionAction.ACCEPT,
                suggestion_id="suggestion_unbound_candidate",
                actor="medical_manager",
            ),
        )
    persisted = store.medical_writing_revision_thread(project_id, thread.thread_id)
    assert persisted.status == "candidate_ready"
    assert persisted.suggestions[0].user_decision == "pending"


def test_candidate_acceptance_rejects_stale_working_copy_revision(binding_runtime):
    documents, store, repository, _ = binding_runtime
    project_id = "proj_alpha"
    section = _section(documents, project_id)
    _seed_quarantined_copy(documents, store, project_id)
    recovered = repository.revert_to_authoritative_baseline(
        project_id,
        section.section_id,
        _recovery_request(
            documents, project_id, expected_revision=1, key="bind-before-candidate"
        ),
    ).working_copy
    thread = RevisionThread(
        thread_id="thread_current_then_stale",
        project_id=project_id,
        document_id=section.document_id,
        section_id=section.section_id,
        anchor_type="paragraph",
        anchor_path="docx:paragraph:10",
        selected_text=section.content_blocks[0]["text"],
        user_instruction="优化研究目的。",
        intent="medical_writing_revision",
        ai_run_id="run_current_then_stale",
        source_locator="docx:paragraph:10",
        source_study_definition_id=CURRENT_ID,
        source_study_definition_revision=CURRENT_REVISION,
        source_study_definition_sha256=CURRENT_SHA,
        source_working_copy_id=recovered.working_copy_id,
        source_working_copy_revision=recovered.revision,
        source_working_copy_content_sha256=repository._payload_hash(
            recovered.content_blocks
        ),
        suggestions=[
            RevisionSuggestion(
                suggestion_id="suggestion_current_then_stale",
                proposal_text="修订候选。",
                diff_patch="replace",
                rationale="提高表达清晰度。",
            )
        ],
        status="candidate_ready",
        created_at=NOW,
    )
    store.commit_medical_writing_revision_submission(
        thread,
        AuditEvent(
            audit_id="audit_thread_current_then_stale",
            project_id=project_id,
            actor="medical_manager",
            action="medical_writing_revision_submitted",
            target_type="revision_thread",
            target_id=thread.thread_id,
            created_at=NOW,
        ),
    )
    edited_blocks = [dict(block) for block in recovered.content_blocks]
    edited_blocks[0]["text"] = "作者已先行修改的当前正文。"
    repository.save_working_copy(
        project_id,
        section.section_id,
        MedicalWritingWorkingCopySaveRequest(
            document_id=section.document_id,
            expected_revision=recovered.revision,
            content_blocks=edited_blocks,
            actor="medical_manager",
            idempotency_key="edit-after-candidate-created",
        ),
    )
    service = MedicalWritingRevisionService(repository, None)
    with pytest.raises(StaleRuntimeStateError, match="stale working-copy"):
        service.apply_action(
            project_id,
            thread.thread_id,
            RevisionActionRequest(
                action=RevisionAction.ACCEPT,
                suggestion_id="suggestion_current_then_stale",
                actor="medical_manager",
            ),
        )
    assert store.medical_writing_revision_thread(
        project_id, thread.thread_id
    ).status == "candidate_ready"
    assert store.verify_audit_chain(project_id) == []
