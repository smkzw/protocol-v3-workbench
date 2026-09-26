from __future__ import annotations

from types import SimpleNamespace

from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    PreparedDocumentAdmissionResult,
    ResearchPipelineState,
)


PROJECT_ID = "proj_a1_preparation_progress"
SNAPSHOT_ID = "wref_search_a1_locked"
PIPELINE_ID = "mwpipe_a1_progress"


class _Batch(SimpleNamespace):
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return vars(self)


def _batch(
    *,
    status: str,
    first_status: str,
    second_status: str,
    completed_document_count: int,
):
    return _Batch(
        batch_id="wref_prep_a1_progress",
        status=status,
        retained_candidate_ids=["NCT00000001", "NCT00000002"],
        retained_candidate_count=2,
        document_item_count=2,
        pending_document_count=sum(
            item_status == "pending"
            for item_status in (first_status, second_status)
        ),
        running_document_count=sum(
            item_status == "running"
            for item_status in (first_status, second_status)
        ),
        completed_document_count=completed_document_count,
        failed_count=0,
        items=[
            SimpleNamespace(
                nct_id="NCT00000001",
                document_id="ctgov_NCT00000001_protocol",
                filename="NCT00000001_Protocol.pdf",
                document_type="protocol",
                item_kind="public_document",
                status=first_status,
            ),
            SimpleNamespace(
                nct_id="NCT00000002",
                document_id="ctgov_NCT00000002_sap",
                filename="NCT00000002_SAP.pdf",
                document_type="sap",
                item_kind="public_document",
                status=second_status,
            ),
        ],
    )


class _PreparationService:
    def __init__(self) -> None:
        self.accepted = _batch(
            status="accepted",
            first_status="pending",
            second_status="pending",
            completed_document_count=0,
        )
        self.completed = _batch(
            status="completed",
            first_status="prepared",
            second_status="prepared",
            completed_document_count=2,
        )
        self.callback_received = False

    def create(self, project_id: str, request):
        assert project_id == PROJECT_ID
        assert request.snapshot_id == SNAPSHOT_ID
        return self.accepted

    def admit_next_stage(self, project_id: str, batch_id: str, request):
        """Match the real service interface (bounded stage admission).

        These scenarios carry no deferred items, so the pipeline must never
        reach stage admission here.
        """
        raise AssertionError("stage admission is not expected in this scenario")

    def run_pending(
        self,
        project_id: str,
        batch_id: str,
        actor: str,
        *,
        progress_callback=None,
    ) -> None:
        assert project_id == PROJECT_ID
        assert batch_id == self.accepted.batch_id
        assert actor == "medical_manager"
        assert progress_callback is not None
        self.callback_received = True
        progress_callback(
            _batch(
                status="running",
                first_status="running",
                second_status="pending",
                completed_document_count=0,
            )
        )
        progress_callback(
            _batch(
                status="running",
                first_status="prepared",
                second_status="running",
                completed_document_count=1,
            )
        )
        progress_callback(self.completed)

    def get(self, project_id: str, batch_id: str):
        assert project_id == PROJECT_ID
        assert batch_id == self.accepted.batch_id
        return self.completed


def test_sync_preparation_persists_and_heartbeats_real_scope_and_progress() -> None:
    state = ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage="awaiting_triage_confirm",
        snapshot_id=SNAPSHOT_ID,
    )
    journey = SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
    )
    preparation_service = _PreparationService()
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = SimpleNamespace(get=lambda _project_id: journey)
    service.preparation_batch_service = preparation_service
    service._confirm_triage_basket = (
        lambda _project_id, _actor, _state, _retained: [
            "NCT00000001",
            "NCT00000002",
        ]
    )
    service._find_reusable_preparation_batch = (
        lambda _project_id, snapshot_id, retained_ids: None
    )
    service._admit_prepared_public_documents = lambda *_args, **_kwargs: (
        PreparedDocumentAdmissionResult(admitted_count=2)
    )
    service._translate_analyze_and_finalize = (
        lambda _project_id, *, actor, state, snapshot_id, heartbeat=None: state
    )

    persisted: list[dict] = []

    def persist(_project_id: str, current: ResearchPipelineState):
        persisted.append(current.as_dict())
        return current

    service._persist = persist
    heartbeats = []

    def heartbeat(payload) -> bool:
        heartbeats.append(payload)
        return True

    result = service.continue_after_triage(
        PROJECT_ID,
        actor="medical_manager",
        retained_candidate_ids=["NCT00000001", "NCT00000002"],
        heartbeat=heartbeat,
        state=state,
    )

    assert preparation_service.callback_received
    progress_details = [
        payload.message
        for payload in heartbeats
        if payload.message.startswith("锁定候选")
    ]
    assert progress_details == [
        (
            "锁定候选 2 项、公开文档 2 份、已完成 0 份；"
            "正在处理 NCT00000001 / NCT00000001_Protocol.pdf"
        ),
        (
            "锁定候选 2 项、公开文档 2 份、已完成 1 份；"
            "正在处理 NCT00000002 / NCT00000002_SAP.pdf"
        ),
        "锁定候选 2 项、公开文档 2 份、已完成 2 份",
    ]
    preparing_states = [
        payload for payload in persisted if payload["stage"] == "preparing"
    ]
    assert preparing_states
    assert all(payload["eta_seconds"] is None for payload in preparing_states)
    assert any(
        payload["detail"] == progress_details[-1] for payload in preparing_states
    )
    assert result.prep_batch_id == preparation_service.accepted.batch_id


def test_parent_projection_preserves_active_file_substep_and_projected_percent() -> None:
    batch = SimpleNamespace(
        status="running",
        document_item_count=2,
        completed_document_count=1,
        progress=SimpleNamespace(
            phase="ocr_completing",
            current_substep="OCR 第 91 页完成（全文共 120 页）",
            completed=2,
            total=5,
            percent=75,
            unit="page",
            context={
                "item_id": "item_b",
                "nct_id": "NCT00000002",
                "document_label": "NCT00000002_SAP.pdf",
                "physical_page": 91,
                "document_page_total": 120,
                "completed_ocr_pages": 2,
                "ocr_page_total": 5,
            },
        ),
        current_item_id="item_b",
        current_nct_id="NCT00000002",
        current_document_label="NCT00000002_SAP.pdf",
        items=[
            SimpleNamespace(
                item_kind="public_document",
                status="prepared",
                nct_id="NCT00000001",
                filename="NCT00000001_Protocol.pdf",
            ),
            SimpleNamespace(
                item_kind="public_document",
                status="running",
                nct_id="NCT00000002",
                filename="NCT00000002_SAP.pdf",
            ),
        ],
    )

    projection = MedicalWritingResearchPipelineService._preparation_progress_projection(batch)

    assert projection["completed"] == 1
    assert projection["total"] == 2
    assert projection["child_percent"] == 75
    assert projection["label"] == (
        "正在处理 NCT00000002 / NCT00000002_SAP.pdf；"
        "OCR 第 91 页完成（全文共 120 页）；已完成 2/5 个需识别页面"
    )
    assert projection["context"] == {
        "current_item_id": "item_b",
        "current_nct_id": "NCT00000002",
        "current_document_label": "NCT00000002_SAP.pdf",
        "unit_type": "page",
        "current_object_label": "NCT00000002 / NCT00000002_SAP.pdf",
        "current_substep": "OCR 第 91 页完成（全文共 120 页）",
        "current_substep_percent": 75,
        "current_unit": "page",
        "item_completed": 2,
        "item_total": 5,
        "item_id": "item_b",
        "nct_id": "NCT00000002",
        "document_label": "NCT00000002_SAP.pdf",
        "physical_page": 91,
        "document_page_total": 120,
        "completed_ocr_pages": 2,
        "ocr_page_total": 5,
    }


def test_parent_projection_survives_last_item_terminalization_window() -> None:
    batch = SimpleNamespace(
        status="running",
        document_item_count=2,
        completed_document_count=2,
        progress=SimpleNamespace(
            phase="completed",
            current_substep="全部文件准备完成",
            completed=2,
            total=2,
            percent=100,
            unit="file",
            context={},
        ),
        current_item_id="",
        current_nct_id="",
        current_document_label="",
        items=[
            SimpleNamespace(
                item_kind="public_document",
                status="prepared",
                nct_id="NCT00000001",
                filename="NCT00000001_Protocol.pdf",
            ),
            SimpleNamespace(
                item_kind="public_document",
                status="prepared",
                nct_id="NCT00000002",
                filename="NCT00000002_SAP.pdf",
            ),
        ],
    )

    projection = MedicalWritingResearchPipelineService._preparation_progress_projection(
        batch
    )

    assert projection["completed"] == 2
    assert projection["total"] == 2
    assert projection["child_percent"] == 100
    assert projection["label"] == "原文准备已完成"
    assert projection["context"]["current_substep"] == "全部文件准备完成"
    assert projection["context"]["current_substep_percent"] == 100
    assert projection["context"]["item_completed"] == 2
    assert projection["context"]["item_total"] == 2
