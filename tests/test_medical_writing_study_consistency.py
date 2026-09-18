from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

import pytest

from packages.contracts.workbench_contracts import (
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingGreenfieldSectionSeed,
    MedicalWritingPhase1Part,
    MedicalWritingPicosDefinition,
    MedicalWritingStudyDefinition,
    MedicalWritingStudyFraming,
    MedicalWritingStudyRebindRequest,
    MedicalWritingStudyReconciliationConfirmRequest,
    MedicalWritingStructuredStudyDesign,
    MedicalWritingWorkingCopySaveRequest,
    ProtocolDocument,
    ProtocolSection,
)
from packages.contracts.workbench_contracts.models import (
    MedicalWritingSectionFreezeRequest,
)
from services.api.app.medical_writing_greenfield import _build_greenfield_document
from services.api.app.medical_writing_document import MedicalWritingDocumentService
from services.api.app.medical_writing_greenfield import (
    CompositeMedicalWritingDocumentService,
    GreenfieldMedicalWritingDocumentService,
)
from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore
from services.api.app.medical_writing_study_consistency import (
    MedicalWritingStudyConsistencyService,
)
from services.api.app.sqlite_runtime_store import RuntimeStoreError


def _document(*, revision: int | None = 3, state_hash: str = "a" * 64):
    return ProtocolDocument(
        document_id="mwdoc_consistency",
        project_id="proj_consistency",
        protocol_id="CMS-RA-001",
        version="V1.0",
        source_study_definition_id=("mwdef_consistency" if revision else ""),
        source_study_definition_revision=revision,
        source_study_definition_sha256=(state_hash if revision else ""),
        sections=[
            ProtocolSection(
                section_id="section_synopsis",
                document_id="mwdoc_consistency",
                heading="方案摘要",
                section_number="1.1",
                template_node_id="ich_m11_1_1",
            ),
            ProtocolSection(
                section_id="section_eligibility",
                document_id="mwdoc_consistency",
                heading="入选标准",
                section_number="5.2",
                template_node_id="ich_m11_5_2",
            ),
            ProtocolSection(
                section_id="section_statistics",
                document_id="mwdoc_consistency",
                heading="统计分析",
                section_number="10.4",
                template_node_id="ich_m11_10_4",
            ),
        ],
    )


class _Documents:
    def __init__(self, document):
        self.document = document

    def document_for_revision(self, _project_id):
        return self.document


class _Journeys:
    def __init__(self, definition=None, invalidated=None, exists=True):
        self.definition = definition
        self.invalidated = invalidated or []
        self.exists = exists

    def has_project(self, _project_id):
        return self.exists

    def get(self, _project_id):
        return SimpleNamespace(
            study_definition=self.definition,
            invalidated_dependents=self.invalidated,
        )


def _definition(*, revision=3, state_hash="a" * 64, definition_id="mwdef_consistency"):
    return SimpleNamespace(
        definition_id=definition_id,
        revision=revision,
        state_sha256=state_hash,
    )


def _structured_definition(
    *,
    study_phase: str,
    structured_design: MedicalWritingStructuredStudyDesign,
    design_pattern: str = "",
    design_archetype: str = "",
) -> MedicalWritingStudyDefinition:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    return MedicalWritingStudyDefinition(
        definition_id="mwdef_structured_consistency",
        project_id="proj_consistency",
        revision=1,
        origin="guided_greenfield",
        framing=MedicalWritingStudyFraming(
            protocol_id="CMS-TEST-001",
            document_title="Structured consistency test",
            indication="Test indication",
            clinicaltrials_condition_term="Test condition",
            study_phase=study_phase,
            investigational_product="TEST-IP",
            design_pattern=design_pattern,
            structured_design=structured_design,
        ),
        picos=MedicalWritingPicosDefinition(
            design_archetype=design_archetype,
        ),
        state_sha256="c" * 64,
        created_at=now,
        updated_at=now,
        updated_by="test",
    )


def test_greenfield_document_persists_complete_study_definition_binding():
    request = MedicalWritingGreenfieldCreateRequest(
        protocol_id="CMS-RA-001",
        version="V1.0",
        document_title="类风湿关节炎I期临床试验方案",
        indication="类风湿关节炎",
        study_phase="I期",
        source_study_definition_id="mwdef_consistency",
        source_study_definition_revision=3,
        source_study_definition_sha256="a" * 64,
        sections=[
            MedicalWritingGreenfieldSectionSeed(
                section_key="protocol_synopsis",
                heading="方案摘要",
            )
        ],
        actor="medical_manager_test",
        idempotency_key="create-consistency-document",
    )
    document = _build_greenfield_document(
        "proj_consistency",
        request,
        "b" * 64,
    )
    assert document.source_study_definition_id == "mwdef_consistency"
    assert document.source_study_definition_revision == 3
    assert document.source_study_definition_sha256 == "a" * 64


def test_protocol_document_rejects_partial_or_invalid_definition_binding():
    with pytest.raises(ValueError, match="must be provided together"):
        ProtocolDocument(
            document_id="mwdoc_partial",
            project_id="proj_consistency",
            protocol_id="CMS-RA-001",
            version="V1.0",
            source_study_definition_id="mwdef_consistency",
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _document(state_hash="A" * 64)


def test_current_binding_does_not_block_approval_or_final_export():
    service = MedicalWritingStudyConsistencyService(
        _Documents(_document()),
        _Journeys(_definition()),
    )
    state = service.status("proj_consistency")
    assert state.status == "current"
    assert not state.blocks_new_approval
    assert not state.blocks_approved_export
    service.require_new_approval("proj_consistency", "section_eligibility")
    service.require_approved_export("proj_consistency")


def test_structured_design_consistency_warns_without_blocking_projection():
    definition = _structured_definition(
        study_phase="III期",
        structured_design=MedicalWritingStructuredStudyDesign(
            randomization_mode="randomized",
            blinding_mode="double_blind",
            comparator_type="placebo",
            phase1_parts=[
                MedicalWritingPhase1Part(
                    part_code="SAD",
                    population="健康受试者",
                    cohort_dose="10 mg队列",
                )
            ],
        ),
        design_pattern="非随机、开放标签、阳性对照研究",
        design_archetype="randomized_confirmatory",
    )
    service = MedicalWritingStudyConsistencyService(
        _Documents(_document(revision=1, state_hash="c" * 64)),
        _Journeys(definition),
    )

    projection = service.validate_structured_design_authority("proj_consistency")

    assert projection.design_view.phase1_parts == []
    assert projection.deterministic_projection_allowed is True
    assert projection.blockers
    assert all(item.severity == "warning" for item in projection.blockers)
    assert {
        item.code for item in projection.blockers
    } == {
        "non_phase1_study_should_not_contain_phase1_parts",
        "study_design_semantic_mismatch",
    }


def test_stale_binding_maps_dependents_and_blocks_only_affected_new_approval():
    service = MedicalWritingStudyConsistencyService(
        _Documents(_document(revision=2, state_hash="b" * 64)),
        _Journeys(_definition(), ["eligibility_sections"]),
    )
    state = service.status("proj_consistency")
    assert state.status == "stale"
    assert state.blocks_approved_export
    assert [item.section_id for item in state.affected_sections] == [
        "section_eligibility"
    ]
    with pytest.raises(RuntimeStoreError, match="PICOS"):
        service.require_new_approval("proj_consistency", "section_eligibility")
    service.require_new_approval("proj_consistency", "section_statistics")
    with pytest.raises(RuntimeStoreError, match="PICOS"):
        service.require_approved_export("proj_consistency")


def test_unbound_legacy_without_authoring_journey_remains_usable_without_fake_binding():
    service = MedicalWritingStudyConsistencyService(
        _Documents(_document(revision=None)),
        _Journeys(exists=False),
    )
    state = service.status("proj_consistency")
    assert state.status == "unbound_legacy"
    assert state.current_definition_id == ""
    assert not state.blocks_new_approval
    assert not state.blocks_approved_export


def test_unbound_document_with_authoring_journey_fails_closed():
    service = MedicalWritingStudyConsistencyService(
        _Documents(_document(revision=None)),
        _Journeys(_definition(), ["protocol_synopsis"]),
    )
    state = service.status("proj_consistency")
    assert state.status == "binding_required"
    assert state.blocks_new_approval
    assert [item.section_id for item in state.affected_sections] == [
        "section_synopsis",
        "section_eligibility",
        "section_statistics",
    ]


class _MutableJourneys:
    def __init__(self):
        self.definition = _definition(revision=1, state_hash="a" * 64)
        self.invalidated = []

    def change_eligibility(self):
        self.definition = _definition(revision=2, state_hash="b" * 64)
        self.invalidated = ["eligibility_sections"]

    def has_project(self, _project_id):
        return True

    def get(self, _project_id):
        return SimpleNamespace(
            study_definition=self.definition,
            invalidated_dependents=list(self.invalidated),
        )

    def acknowledge_document_synchronization(
        self,
        _project_id,
        *,
        definition_id,
        definition_revision,
        definition_sha256,
        actor,
        idempotency_key,
    ):
        assert definition_id == self.definition.definition_id
        assert definition_revision == self.definition.revision
        assert definition_sha256 == self.definition.state_sha256
        assert actor
        assert idempotency_key
        self.invalidated = []
        return self.get(_project_id)


class _ImportedDocuments:
    """Read-only imported protocol used to exercise first StudyDefinition binding."""

    def __init__(self, source_path: Path):
        self.source_path = source_path
        self.document = ProtocolDocument(
            document_id="mwdoc_imported_consistency",
            project_id="proj_imported_consistency",
            protocol_id="CMS-IMPORTED-001",
            version="V1.0",
            sections=[
                ProtocolSection(
                    section_id="section_imported_synopsis",
                    document_id="mwdoc_imported_consistency",
                    heading="方案摘要",
                    section_number="1.1",
                    template_node_id="ich_m11_1_1",
                    content_blocks=[
                        {
                            "block_id": "paragraph_imported_synopsis",
                            "block_type": "paragraph",
                            "text": "原始导入方案摘要。",
                            "source_locator": "docx:paragraph:10",
                        }
                    ],
                ),
                ProtocolSection(
                    section_id="section_imported_eligibility",
                    document_id="mwdoc_imported_consistency",
                    heading="入选标准",
                    section_number="5.2",
                    template_node_id="ich_m11_5_2",
                    content_blocks=[
                        {
                            "block_id": "paragraph_imported_eligibility",
                            "block_type": "paragraph",
                            "text": "年龄18至65岁。",
                            "source_locator": "docx:paragraph:20",
                        }
                    ],
                ),
            ],
        )

    def document_session(self, project_id: str) -> ProtocolDocument:
        assert project_id == self.document.project_id
        return self.document.model_copy(deep=True)

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        return self.document_session(project_id)

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        assert project_id == self.document.project_id
        return next(
            section.model_copy(deep=True)
            for section in self.document.sections
            if section.section_id == section_id
        )

    def source_mode(self, project_id: str) -> str:
        assert project_id == self.document.project_id
        return "original_protocol_docx"

    def original_protocol_path(self, project_id: str) -> Path:
        assert project_id == self.document.project_id
        return self.source_path


def _imported_binding_runtime(tmp_path: Path):
    source_path = tmp_path / "CMS-IMPORTED-001临床试验方案.docx"
    source_bytes = b"PK\x03\x04immutable-imported-protocol"
    source_path.write_bytes(source_bytes)
    documents = _ImportedDocuments(source_path)
    store = SqliteRuntimeStore(tmp_path / "runtime_imported_binding.sqlite3")

    # Simulate an author-edited working copy that predates StudyDefinition creation.
    unbound_repository = MedicalWritingRuntimeRepository(documents, store)
    section_id = "section_imported_eligibility"
    baseline = unbound_repository.working_copy(
        documents.document.project_id, section_id
    )
    authored_blocks = [dict(item) for item in baseline.content_blocks]
    authored_blocks[0] = {
        **authored_blocks[0],
        "text": "年龄18至70岁；医学经理已补充疾病活动度要求。",
    }
    saved = unbound_repository.save_working_copy(
        documents.document.project_id,
        section_id,
        MedicalWritingWorkingCopySaveRequest(
            document_id=documents.document.document_id,
            expected_revision=baseline.revision,
            content_blocks=authored_blocks,
            actor="medical_manager_test",
            idempotency_key="save-imported-before-definition",
        ),
    )

    journeys = _MutableJourneys()
    greenfield = GreenfieldMedicalWritingDocumentService(
        tmp_path / "greenfield_imported_binding.sqlite3"
    )
    consistency = MedicalWritingStudyConsistencyService(
        documents,
        journeys,
        greenfield,
        store,
    )
    repository = MedicalWritingRuntimeRepository(documents, store, consistency)
    return SimpleNamespace(
        project_id=documents.document.project_id,
        documents=documents,
        source_path=source_path,
        source_bytes=source_bytes,
        store=store,
        journeys=journeys,
        consistency=consistency,
        repository=repository,
        saved=saved,
    )


def _rebind_request(
    preview,
    *,
    idempotency_key: str = "bind-imported-document",
) -> MedicalWritingStudyRebindRequest:
    return MedicalWritingStudyRebindRequest(
        preview_id=preview.preview_id,
        expected_document_id=preview.document_id,
        expected_baseline_revision=preview.baseline_revision,
        expected_baseline_sha256=preview.baseline_sha256,
        confirm_content_preserved=True,
        confirm_affected_approvals_reset=True,
        reason="确认将既有导入文档受控绑定至当前研究设计，并保留工作副本供调和。",
        actor="medical_manager_test",
        idempotency_key=idempotency_key,
    )


def test_imported_legacy_first_binding_preserves_source_and_working_copy(
    tmp_path: Path,
):
    runtime = _imported_binding_runtime(tmp_path)
    source_before = runtime.source_path.read_bytes()
    source_document_before = runtime.documents.document_for_revision(
        runtime.project_id
    )
    stored_before = runtime.store.medical_writing_working_copy_by_id(
        runtime.project_id, runtime.saved.working_copy_id
    )

    preview = runtime.consistency.rebind_preview(runtime.project_id)

    assert preview.can_apply
    assert preview.blocking_reasons == []
    assert preview.consistency.status == "binding_required"
    assert preview.document_id == runtime.documents.document.document_id
    assert preview.affected_working_copy_count == 1

    result = runtime.consistency.apply_rebind(
        runtime.project_id, _rebind_request(preview)
    )

    current_binding = (
        runtime.journeys.definition.definition_id,
        runtime.journeys.definition.revision,
        runtime.journeys.definition.state_sha256,
    )
    assert result.consistency.status == "reconciliation_required"
    assert runtime.consistency.effective_document_binding(
        runtime.project_id
    ) == current_binding
    assert runtime.repository.protocol(runtime.project_id).source_study_definition_id == (
        current_binding[0]
    )

    # Binding is additive: neither the source DOCX nor its parsed source document mutates.
    assert runtime.source_path.read_bytes() == source_before == runtime.source_bytes
    assert (
        runtime.documents.document_for_revision(runtime.project_id).model_dump(
            mode="json"
        )
        == source_document_before.model_dump(mode="json")
    )
    assert not runtime.documents.document.source_study_definition_id

    rebound = runtime.store.medical_writing_working_copy_by_id(
        runtime.project_id, runtime.saved.working_copy_id
    )
    assert rebound.revision == stored_before.revision + 1
    assert rebound.content_blocks == stored_before.content_blocks
    assert (
        rebound.source_study_definition_id,
        rebound.source_study_definition_revision,
        rebound.source_study_definition_sha256,
    ) == current_binding
    assert rebound.study_definition_reconciliation_required
    assert rebound.approval_state.value == "ai_draft"
    assert rebound.approved_snapshot_id is None

    replay = runtime.consistency.apply_rebind(
        runtime.project_id, _rebind_request(preview)
    )
    assert replay.model_dump(mode="json") == result.model_dump(mode="json")
    assert (
        runtime.store.medical_writing_working_copy_by_id(
            runtime.project_id, runtime.saved.working_copy_id
        ).revision
        == rebound.revision
    )
    assert runtime.source_path.read_bytes() == source_before


def test_imported_legacy_first_binding_rejects_stale_preview(tmp_path: Path):
    runtime = _imported_binding_runtime(tmp_path)
    preview = runtime.consistency.rebind_preview(runtime.project_id)
    assert preview.can_apply

    # A concurrent author save changes the preflight hash without touching the source DOCX.
    unbound_repository = MedicalWritingRuntimeRepository(
        runtime.documents, runtime.store
    )
    stored = runtime.store.medical_writing_working_copy_by_id(
        runtime.project_id, runtime.saved.working_copy_id
    )
    changed_blocks = [dict(item) for item in stored.content_blocks]
    changed_blocks[0] = {
        **changed_blocks[0],
        "text": "年龄18至75岁；预检后作者又补充了新的医学判断。",
    }
    unbound_repository.save_working_copy(
        runtime.project_id,
        stored.section_id,
        MedicalWritingWorkingCopySaveRequest(
            document_id=stored.document_id,
            expected_revision=stored.revision,
            content_blocks=changed_blocks,
            actor="medical_manager_test",
            idempotency_key="save-imported-after-preview",
        ),
    )

    with pytest.raises(RuntimeStoreError, match="preview is stale|预检.*过期"):
        runtime.consistency.apply_rebind(
            runtime.project_id,
            _rebind_request(
                preview, idempotency_key="bind-imported-from-stale-preview"
            ),
        )
    assert runtime.consistency.status(runtime.project_id).status == "binding_required"
    assert runtime.source_path.read_bytes() == runtime.source_bytes


def test_module_resolution_resets_rebuilt_copy_and_supersedes_removed_copy(
    tmp_path: Path,
):
    project_id = "proj_module_resolution_reset"
    greenfield = GreenfieldMedicalWritingDocumentService(
        tmp_path / "greenfield_modules.sqlite3"
    )
    greenfield.create(
        project_id,
        MedicalWritingGreenfieldCreateRequest(
            protocol_id="CMS-RA-002",
            version="V1.0",
            document_title="动态章节运行时测试方案",
            indication="类风湿关节炎",
            study_phase="II期",
            source_study_definition_id="mwdef_consistency",
            source_study_definition_revision=1,
            source_study_definition_sha256="a" * 64,
            sections=[
                MedicalWritingGreenfieldSectionSeed(
                    section_key="synopsis",
                    heading="方案摘要",
                    section_number="1.1",
                    initial_text="本研究当前不设置期中分析。",
                ),
                MedicalWritingGreenfieldSectionSeed(
                    section_key="interim",
                    heading="期中分析",
                    section_number="10.9",
                    initial_text="将在完成50%主要终点评价后实施期中分析。",
                ),
            ],
            actor="medical_manager_test",
            idempotency_key="create-module-reset-document",
        ),
    )
    documents = CompositeMedicalWritingDocumentService(
        MedicalWritingDocumentService(), greenfield
    )
    store = SqliteRuntimeStore(tmp_path / "runtime_modules.sqlite3")
    consistency = MedicalWritingStudyConsistencyService(
        documents, _MutableJourneys(), greenfield, store
    )
    repository = MedicalWritingRuntimeRepository(documents, store, consistency)
    session = repository.document_session(project_id)
    copies = {}
    for section in session.sections:
        source_copy = repository.working_copy(project_id, section.section_id)
        copies[section.section_number] = repository.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=session.document_id,
                expected_revision=0,
                content_blocks=source_copy.content_blocks,
                actor="medical_manager_test",
                idempotency_key=f"save-module-{section.section_number}",
            ),
        )
    synopsis_freeze = repository.freeze_current_version(
        project_id,
        copies["1.1"].section_id,
        MedicalWritingSectionFreezeRequest(
            document_id=session.document_id,
            expected_working_copy_revision=copies["1.1"].revision,
            expected_study_definition_id="mwdef_consistency",
            expected_study_definition_revision=1,
            expected_study_definition_sha256="a" * 64,
            actor="medical_manager_test",
            reason="医学作者已核对当前摘要并确认本章定稿。",
            idempotency_key="freeze-module-synopsis",
        ),
    )
    assert synopsis_freeze.working_copy.freeze_status == "frozen"

    reset = consistency.reset_after_module_resolution(
        project_id,
        document_id=session.document_id,
        updated_section_ids=[copies["1.1"].section_id],
        removed_section_ids=[copies["10.9"].section_id],
        actor="medical_manager_test",
        idempotency_key="module-interim-off-runtime",
        baseline_revision=2,
    )
    assert reset["reset_approval_count"] == 0
    synopsis_after = repository.working_copy(project_id, copies["1.1"].section_id)
    interim_after = repository.working_copy(project_id, copies["10.9"].section_id)
    assert synopsis_after.approval_state.value == "ai_draft"
    assert synopsis_after.freeze_status == "invalidated"
    assert synopsis_after.study_definition_reconciliation_required
    assert interim_after.approval_state.value == "ai_draft"
    assert interim_after.freeze_status == "editable"
    assert not interim_after.study_definition_reconciliation_required
    history = repository.section_freeze_history(
        project_id, copies["1.1"].section_id
    )
    assert len(history) == 1
    assert history[0].is_current is False

    replay = consistency.reset_after_module_resolution(
        project_id,
        document_id=session.document_id,
        updated_section_ids=[copies["1.1"].section_id],
        removed_section_ids=[copies["10.9"].section_id],
        actor="medical_manager_test",
        idempotency_key="module-interim-off-runtime",
        baseline_revision=2,
    )
    assert replay == reset
    assert store.medical_writing_working_copy_by_id(
        project_id, copies["1.1"].working_copy_id
    ).revision == synopsis_after.revision


def test_rebind_advances_all_bindings_and_reconciles_only_affected_content(
    tmp_path: Path,
):
    project_id = "proj_consistency_rebind"
    greenfield = GreenfieldMedicalWritingDocumentService(tmp_path / "greenfield.sqlite3")
    create_request = MedicalWritingGreenfieldCreateRequest(
        protocol_id="CMS-RA-001",
        version="V1.0",
        document_title="类风湿关节炎I期临床试验方案",
        indication="类风湿关节炎",
        study_phase="I期",
        source_study_definition_id="mwdef_consistency",
        source_study_definition_revision=1,
        source_study_definition_sha256="a" * 64,
        sections=[
            MedicalWritingGreenfieldSectionSeed(
                section_key="eligibility",
                heading="入选标准",
                section_number="5.2",
                initial_text="年龄18至65岁。",
            ),
            MedicalWritingGreenfieldSectionSeed(
                section_key="statistics",
                heading="统计分析",
                section_number="10.4",
                initial_text="主要终点采用分层分析。",
            ),
        ],
        actor="medical_manager_test",
        idempotency_key="create-rebind-document",
    )
    greenfield.create(project_id, create_request)
    documents = CompositeMedicalWritingDocumentService(
        MedicalWritingDocumentService(), greenfield
    )
    store = SqliteRuntimeStore(tmp_path / "runtime.sqlite3")
    journeys = _MutableJourneys()
    consistency = MedicalWritingStudyConsistencyService(
        documents, journeys, greenfield, store
    )
    repository = MedicalWritingRuntimeRepository(documents, store, consistency)
    session = repository.document_session(project_id)
    saved_by_section = {}
    for section in session.sections:
        working = repository.working_copy(project_id, section.section_id)
        content_blocks = [dict(item) for item in working.content_blocks]
        content_blocks[1] = dict(content_blocks[1])
        content_blocks[1]["text"] += "（医学经理已复核）"
        saved = repository.save_working_copy(
            project_id,
            section.section_id,
            MedicalWritingWorkingCopySaveRequest(
                document_id=session.document_id,
                expected_revision=0,
                content_blocks=content_blocks,
                actor="medical_manager_test",
                idempotency_key=f"save-{section.section_id}",
            ),
        )
        frozen = repository.freeze_current_version(
            project_id,
            section.section_id,
            MedicalWritingSectionFreezeRequest(
                document_id=session.document_id,
                expected_working_copy_revision=saved.revision,
                expected_study_definition_id="mwdef_consistency",
                expected_study_definition_revision=1,
                expected_study_definition_sha256="a" * 64,
                actor="medical_manager_test",
                reason="医学作者已完成本章节内容核对并确认定稿。",
                idempotency_key=f"freeze-{section.section_id}",
            ),
        )
        assert frozen.working_copy.freeze_status == "frozen"
        saved_by_section[section.section_number] = saved

    journeys.change_eligibility()
    with pytest.raises(RuntimeStoreError, match="PICOS"):
        repository.assemble_document_for_export(project_id, "approved_final")
    preview = consistency.rebind_preview(project_id)
    assert preview.can_apply
    assert preview.approval_reset_count == 0
    assert [item.section_number for item in preview.affected_sections] == ["5.2"]
    eligibility_before = store.medical_writing_working_copy_by_id(
        project_id, saved_by_section["5.2"].working_copy_id
    )
    statistics_before = store.medical_writing_working_copy_by_id(
        project_id, saved_by_section["10.4"].working_copy_id
    )
    eligibility_snapshots_before = store.medical_writing_working_copy_snapshots(
        project_id, eligibility_before.working_copy_id
    )

    rebind_request = MedicalWritingStudyRebindRequest(
        preview_id=preview.preview_id,
        expected_document_id=preview.document_id,
        expected_baseline_revision=preview.baseline_revision,
        expected_baseline_sha256=preview.baseline_sha256,
        confirm_content_preserved=True,
        confirm_affected_approvals_reset=True,
        reason="研究人群标准已经更新，需要使受影响章节的当前冻结失效。",
        actor="medical_manager_test",
        idempotency_key="rebind-after-eligibility-change",
    )
    def fail_after_snapshot(checkpoint):
        if checkpoint == "after_study_rebind_snapshot":
            raise RuntimeError("injected study rebind failure")

    store.fault_injector = fail_after_snapshot
    with pytest.raises(RuntimeError, match="injected study rebind failure"):
        consistency.apply_rebind(
            project_id,
            rebind_request.model_copy(
                update={"idempotency_key": "rebind-fault-injection"}
            ),
        )
    store.fault_injector = None
    assert consistency.rebind_preview(project_id).preview_id == preview.preview_id
    assert store.medical_writing_working_copy_by_id(
        project_id, eligibility_before.working_copy_id
    ) == eligibility_before
    assert len(
        store.medical_writing_working_copy_snapshots(
            project_id, eligibility_before.working_copy_id
        )
    ) == len(eligibility_snapshots_before)
    result = consistency.apply_rebind(project_id, rebind_request)
    assert result.consistency.status == "reconciliation_required"
    assert result.reset_approval_count == 0
    eligibility_after = store.medical_writing_working_copy_by_id(
        project_id, eligibility_before.working_copy_id
    )
    statistics_after = store.medical_writing_working_copy_by_id(
        project_id, statistics_before.working_copy_id
    )
    assert eligibility_after.revision == eligibility_before.revision + 1
    assert eligibility_after.content_blocks == eligibility_before.content_blocks
    assert eligibility_after.approval_state.value == "ai_draft"
    assert eligibility_after.approved_snapshot_id is None
    assert eligibility_after.source_study_definition_revision == 2
    assert statistics_after.revision == statistics_before.revision + 1
    assert statistics_after.content_blocks == statistics_before.content_blocks
    assert statistics_after.approval_state.value == "ai_draft"
    assert statistics_after.approved_snapshot_id is None
    assert statistics_after.source_study_definition_revision == 2
    assert not statistics_after.study_definition_reconciliation_required
    assert repository.working_copy(
        project_id, eligibility_after.section_id
    ).freeze_status == "invalidated"
    assert repository.working_copy(
        project_id, statistics_after.section_id
    ).freeze_status == "invalidated"
    eligibility_snapshots_after = store.medical_writing_working_copy_snapshots(
        project_id, eligibility_before.working_copy_id
    )
    assert len(eligibility_snapshots_after) == len(eligibility_snapshots_before) + 1
    assert eligibility_snapshots_after[-1]["snapshot_type"] == "study_definition_rebind"
    assert any(
        item["snapshot_type"] == "author_freeze"
        for item in eligibility_snapshots_after
    )
    assert journeys.invalidated == []
    replay = consistency.apply_rebind(project_id, rebind_request)
    assert replay.model_dump(mode="json") == result.model_dump(mode="json")
    with pytest.raises(Exception, match="idempotency key"):
        consistency.apply_rebind(
            project_id,
            rebind_request.model_copy(
                update={"reason": "复用同一幂等键但改变医学理由，应被后端拒绝。"}
            ),
        )
    with pytest.raises(RuntimeStoreError, match="调和"):
        repository.freeze_current_version(
            project_id,
            eligibility_after.section_id,
            MedicalWritingSectionFreezeRequest(
                document_id=result.document_id,
                expected_working_copy_revision=eligibility_after.revision,
                expected_study_definition_id="mwdef_consistency",
                expected_study_definition_revision=2,
                expected_study_definition_sha256="b" * 64,
                actor="medical_manager_test",
                reason="调和未完成时不得冻结当前章节版本。",
                idempotency_key="freeze-before-reconciliation",
            ),
        )
    reconciled_blocks = [dict(item) for item in eligibility_after.content_blocks]
    reconciled_blocks[1] = dict(reconciled_blocks[1])
    reconciled_blocks[1]["text"] = "年龄18至70岁，且疾病活动度符合当前方案定义。"
    edited_for_current_definition = repository.save_working_copy(
        project_id,
        eligibility_after.section_id,
        MedicalWritingWorkingCopySaveRequest(
            document_id=result.document_id,
            expected_revision=eligibility_after.revision,
            content_blocks=reconciled_blocks,
            actor="medical_manager_test",
            idempotency_key="edit-eligibility-for-current-definition",
        ),
    )
    assert edited_for_current_definition.study_definition_reconciliation_required
    reconciled = consistency.confirm_section_reconciliation(
        project_id,
        edited_for_current_definition.section_id,
        MedicalWritingStudyReconciliationConfirmRequest(
            document_id=result.document_id,
            expected_working_copy_revision=edited_for_current_definition.revision,
            reason="已将更新后的年龄范围和疾病活动度标准逐项核对到本章节正文。",
            acknowledge_content_reconciled=True,
            actor="medical_manager_test",
            idempotency_key="confirm-eligibility-reconciliation",
        ),
    )
    assert reconciled.consistency.status == "current"
    assert not reconciled.working_copy.study_definition_reconciliation_required
    assert reconciled.working_copy.revision == edited_for_current_definition.revision + 1
    assert consistency.status(project_id).status == "current"
    with pytest.raises(RuntimeStoreError, match="frozen|freeze"):
        repository.assemble_document_for_export(project_id, "approved_final")
    refrozen_eligibility = repository.freeze_current_version(
        project_id,
        reconciled.working_copy.section_id,
        MedicalWritingSectionFreezeRequest(
            document_id=result.document_id,
            expected_working_copy_revision=reconciled.working_copy.revision,
            expected_study_definition_id="mwdef_consistency",
            expected_study_definition_revision=2,
            expected_study_definition_sha256="b" * 64,
            actor="medical_manager_test",
            reason="已按更新后的入选标准重新核对并冻结。",
            idempotency_key="refreeze-eligibility-after-rebind",
        ),
    )
    assert refrozen_eligibility.working_copy.freeze_status == "frozen"
    refrozen_statistics = repository.freeze_current_version(
        project_id,
        statistics_after.section_id,
        MedicalWritingSectionFreezeRequest(
            document_id=result.document_id,
            expected_working_copy_revision=statistics_after.revision,
            expected_study_definition_id="mwdef_consistency",
            expected_study_definition_revision=2,
            expected_study_definition_sha256="b" * 64,
            actor="medical_manager_test",
            reason="已确认统计章节与当前StudyDefinition一致并冻结。",
            idempotency_key="refreeze-statistics-after-binding",
        ),
    )
    assert refrozen_statistics.working_copy.freeze_status == "frozen"
    assert repository.final_freeze_readiness(project_id).ready
    # Consistent bindings/freeze do not turn two synthetic short clauses into
    # a complete protocol. Preserve document completeness as a separate check.
    with pytest.raises(RuntimeStoreError, match="substantive_body_missing"):
        repository.assemble_document_for_export(project_id, "approved_final")
