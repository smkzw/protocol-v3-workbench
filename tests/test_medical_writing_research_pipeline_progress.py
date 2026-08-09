from __future__ import annotations

import threading
from types import SimpleNamespace

from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineState,
    _project_stage_percent,
)


def test_parent_ranges_use_real_child_completion_and_remain_monotonic() -> None:
    triage_child = round((7 / 19) * 100)
    assert _project_stage_percent("triaging", triage_child, 22) == 27
    assert _project_stage_percent("preparing", round((14 / 99) * 100), 50) == 51
    assert _project_stage_percent("preparing", round((66 / 99) * 100), 51) == 55
    assert _project_stage_percent("preparing", 100, 55) == 58
    assert _project_stage_percent("translating", 36, 68) == 74
    assert _project_stage_percent("translating", 100, 74) == 85


def test_preparation_projection_uses_current_nct_and_document_label() -> None:
    batch = SimpleNamespace(
        status="running",
        document_item_count=99,
        completed_document_count=66,
        items=[
            SimpleNamespace(
                item_kind="public_document",
                status="running",
                nct_id="NCT02497001",
                filename="Prot_001.pdf",
            )
        ],
    )

    projection = MedicalWritingResearchPipelineService._preparation_progress_projection(
        batch
    )

    assert projection["phase"] == "document_preparation"
    assert projection["completed"] == 66
    assert projection["total"] == 99
    assert projection["label"] == "正在处理 NCT02497001 / Prot_001.pdf"
    assert projection["context"] == {
        "current_nct_id": "NCT02497001",
        "current_document_label": "Prot_001.pdf",
    }


def test_translation_projection_counts_terminal_items_and_critical_anchors() -> None:
    batch = {
        "status": "running",
        "counts": {"item_count": 10},
        "items": [
            {"generation_status": "candidate_ready", "ich_m11_anchor": "objectives_endpoints"},
            {"generation_status": "candidate_ready", "ich_m11_anchor": "eligibility"},
            {"generation_status": "fidelity_blocked", "ich_m11_anchor": "schedule"},
            {"generation_status": "pending", "ich_m11_anchor": "safety"},
        ],
    }

    projection = MedicalWritingResearchPipelineService._translation_progress_projection(
        batch
    )

    assert projection["phase"] == "critical_anchor_translation"
    assert projection["completed"] == 3
    assert projection["total"] == 10
    assert projection["context"]["critical_anchors_ready"] == 2
    assert projection["context"]["critical_anchors_total"] == 4
    assert projection["context"]["item_percent"] == 30
    assert projection["context"]["anchor_percent"] == 50
    assert projection["child_percent"] == 36


def test_child_projection_round_trips_through_persisted_pipeline_state() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_progress",
        project_id="proj_progress",
        stage="preparing",
        percent=50,
    )
    MedicalWritingResearchPipelineService._apply_child_progress(
        state,
        phase="document_preparation",
        completed=66,
        total=99,
        label="正在处理 NCT02497001 / Prot_001.pdf",
        context={"current_nct_id": "NCT02497001"},
    )

    restored = ResearchPipelineState.from_dict(state.as_dict())

    assert restored.progress_schema_version == "medical_writing_research_pipeline_progress_v1"
    assert restored.child_phase == "document_preparation"
    assert restored.child_completed == 66
    assert restored.child_total == 99
    assert restored.child_percent == 67
    assert restored.child_label == "正在处理 NCT02497001 / Prot_001.pdf"
    assert restored.child_context["current_nct_id"] == "NCT02497001"
    assert restored.percent == 55


def test_status_refresh_persists_real_preparation_projection_for_reload() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_status_progress",
        project_id="proj_status_progress",
        stage="preparing",
        percent=50,
        prep_batch_id="prep_status_progress",
    )

    class _JourneyService:
        def __init__(self) -> None:
            self.state = state

        def get(self, _project_id):
            return SimpleNamespace(
                research_pipeline=self.state.as_dict(),
                corpus_gate=None,
            )

        def save_research_pipeline(self, _project_id, payload):
            self.state = ResearchPipelineState.from_dict(payload)

    journey_service = _JourneyService()
    service = object.__new__(MedicalWritingResearchPipelineService)
    service._lock = threading.RLock()
    service.journey_service = journey_service
    service.triage_service = SimpleNamespace(repository=None)
    service.preparation_batch_service = SimpleNamespace(
        get=lambda _project_id, _batch_id: {
            "status": "running",
            "document_item_count": 99,
            "completed_document_count": 66,
            "items": [
                {
                    "item_kind": "public_document",
                    "status": "running",
                    "nct_id": "NCT02497001",
                    "filename": "Prot_001.pdf",
                }
            ],
        }
    )
    service.translation_batch_service = SimpleNamespace()

    response = service.status("proj_status_progress")

    assert response["pipeline"]["percent"] == 55
    assert response["pipeline"]["child_completed"] == 66
    assert response["pipeline"]["child_total"] == 99
    assert response["pipeline"]["child_label"] == "正在处理 NCT02497001 / Prot_001.pdf"
    reloaded = ResearchPipelineState.from_dict(journey_service.state.as_dict())
    assert reloaded.child_completed == 66
    assert reloaded.percent == 55


def test_status_replaces_stale_locked_detail_after_round1_material_is_ready() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_material_ready",
        project_id="proj_material_ready",
        stage="awaiting_corpus_admission",
        round1_material_ready=False,
        detail=(
            "第一轮研究材料尚未齐备（triage_not_finalized,"
            "protocol_structure_not_satisfied），设计推荐仍锁定。"
        ),
    )

    class _JourneyService:
        def __init__(self) -> None:
            self.state = state

        def get(self, _project_id):
            return SimpleNamespace(
                research_pipeline=self.state.as_dict(),
                corpus_gate=None,
            )

        def save_research_pipeline(self, _project_id, payload):
            self.state = ResearchPipelineState.from_dict(payload)

    journey_service = _JourneyService()
    service = object.__new__(MedicalWritingResearchPipelineService)
    service._lock = threading.RLock()
    service.journey_service = journey_service
    service.triage_service = SimpleNamespace(repository=None)
    service.preparation_batch_service = SimpleNamespace()
    service.translation_batch_service = SimpleNamespace()
    service._round1_material_ready = lambda *_args: (True, "material_ready")

    response = service.status("proj_material_ready")

    assert response["pipeline"]["round1_material_ready"] is True
    assert response["design_recommendations_unlocked"] is True
    assert response["pipeline"]["detail"] == (
        "第一轮竞品语料分析已完成，证据化研究设计推荐已开放。"
        "完整医学准入与PICOS对齐仍将在后续语料门中完成。"
    )


def test_status_keeps_retry_action_for_stale_partial_triage() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_stale_triage",
        project_id="proj_stale_triage",
        stage="failed",
        error_summary="competitor_triage_stale",
        triage_run_id="triage_stale",
        snapshot_id="snapshot_stale",
    )

    class _JourneyService:
        def __init__(self) -> None:
            self.state = state

        def get(self, _project_id):
            return SimpleNamespace(
                research_pipeline=self.state.as_dict(),
                corpus_gate=None,
                corpus_triage=None,
                discovery_basket_projection=None,
                search_plan=None,
            )

        def save_research_pipeline(self, _project_id, payload):
            self.state = ResearchPipelineState.from_dict(payload)

    run = SimpleNamespace(
        run_id="triage_stale",
        snapshot_id="snapshot_stale",
        status="stale",
        chunks=[
            SimpleNamespace(status="succeeded", chunk_id="done"),
            SimpleNamespace(status="failed", chunk_id="retry"),
        ],
    )
    journey_service = _JourneyService()
    service = object.__new__(MedicalWritingResearchPipelineService)
    service._lock = threading.RLock()
    service.journey_service = journey_service
    service.triage_service = SimpleNamespace(
        repository=SimpleNamespace(triage_run=lambda _project_id, _run_id: run)
    )
    service.preparation_batch_service = SimpleNamespace()
    service.translation_batch_service = SimpleNamespace()

    response = service.status("proj_stale_triage")

    assert response["pipeline"]["stage"] == "failed"
    assert response["triage_progress"]["status"] == "stale"
    assert response["triage_retryable"] is True


def test_status_fails_closed_without_persisting_downgrade_when_evidence_is_unavailable() -> None:
    state = ResearchPipelineState(
        pipeline_id="mwpipe_read_only_degraded",
        project_id="proj_read_only_degraded",
        stage="awaiting_corpus_admission",
        round1_material_ready=True,
        translation_batch_id="translation_missing_from_fixture",
        round1_analysis_id="analysis_bound",
        round1_analysis_output_hash="a" * 64,
        round1_brief_ids=["brief_bound"],
        round1_ai_route={"provider": "fixture", "model": "fixture-no-call"},
    )

    class _JourneyService:
        def __init__(self) -> None:
            self.state = state
            self.saved_payloads: list[dict] = []

        def get(self, _project_id):
            return SimpleNamespace(
                research_pipeline=self.state.as_dict(),
                corpus_gate=None,
                corpus_triage=None,
                discovery_basket_projection=None,
                search_plan=None,
            )

        def save_research_pipeline(self, _project_id, payload):
            self.saved_payloads.append(dict(payload))
            self.state = ResearchPipelineState.from_dict(payload)

    journey_service = _JourneyService()
    service = object.__new__(MedicalWritingResearchPipelineService)
    service._lock = threading.RLock()
    service.journey_service = journey_service
    service.triage_service = SimpleNamespace(repository=None)
    service.preparation_batch_service = SimpleNamespace()

    def _missing_translation(_project_id, _batch_id):
        raise FileNotFoundError("fixture omitted translation database")

    service.translation_batch_service = SimpleNamespace(get=_missing_translation)

    response = service.status("proj_read_only_degraded")

    assert response["read_only_degraded"] is True
    assert response["design_recommendations_unlocked"] is False
    assert response["unlock_reason"] == "research_pipeline_evidence_unavailable"
    assert response["pipeline"]["round1_material_ready"] is False
    assert journey_service.state.round1_material_ready is True
    assert journey_service.saved_payloads == []

    second = service.status("proj_read_only_degraded")
    assert second["read_only_degraded"] is True
    assert second["design_recommendations_unlocked"] is False
    assert journey_service.saved_payloads == []


def test_failed_retry_preserves_attempt_percent_and_clears_stale_child_projection() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)
    state = ResearchPipelineState(
        pipeline_id="mwpipe_retry_progress",
        project_id="proj_retry_progress",
        stage="failed",
        percent=55,
        child_phase="document_preparation",
        child_completed=66,
        child_total=99,
        child_percent=67,
        child_label="正在处理 NCT02497001 / Prot_001.pdf",
        child_context={"current_nct_id": "NCT02497001"},
        error_summary="document_preparation_failed",
    )

    service._set_stage(
        state,
        "triaging",
        detail="继续竞品分诊",
        error="",
    )

    assert state.percent == 55
    assert state.child_phase == ""
    assert state.child_completed == 0
    assert state.child_total == 0
    assert state.child_percent == 0
    assert state.child_label == ""
    assert state.child_context == {}
    assert state.error_summary == ""


def test_waiting_stage_in_same_phase_preserves_real_child_projection() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)
    state = ResearchPipelineState(
        pipeline_id="mwpipe_waiting_progress",
        project_id="proj_waiting_progress",
        stage="preparing",
        percent=55,
        child_phase="document_preparation",
        child_completed=66,
        child_total=99,
        child_percent=67,
        child_label="正在处理 NCT02497001 / Prot_001.pdf",
        child_context={"current_nct_id": "NCT02497001"},
    )

    service._set_stage(
        state,
        "awaiting_document_validation",
        detail="原文准备完成，等待批量确认",
    )

    assert state.percent == 58
    assert state.child_phase == "document_preparation"
    assert state.child_completed == 66
    assert state.child_total == 99
    assert state.child_label == "正在处理 NCT02497001 / Prot_001.pdf"


def test_stage_transitions_are_monotonic_and_only_success_reaches_100() -> None:
    service = object.__new__(MedicalWritingResearchPipelineService)

    state = ResearchPipelineState(stage="preparing", percent=55)
    service._set_stage(state, "failed", detail="准备失败")
    assert state.percent == 55
    service._set_stage(state, "triaging", detail="同一 attempt 重试")
    assert state.percent == 55

    state = ResearchPipelineState(stage="translating", percent=74)
    service._set_stage(state, "cancelled", detail="用户取消")
    assert state.percent == 74

    state = ResearchPipelineState(stage="corpus_ready", percent=95)
    service._set_stage(state, "analyzing_round2", detail="第二轮分析")
    assert state.percent == 96
    service._set_stage(state, "round2_ready", detail="第二轮完成")
    assert state.percent == 100


def test_legacy_terminal_100_is_recovered_from_persisted_work_evidence() -> None:
    failed = ResearchPipelineState.from_dict(
        {
            "stage": "failed",
            "percent": 100,
            "child_phase": "document_preparation",
            "child_completed": 66,
            "child_total": 99,
            "child_percent": 67,
        }
    )
    cancelled = ResearchPipelineState.from_dict(
        {
            "stage": "cancelled",
            "percent": 100,
            "snapshot_id": "snapshot_before_cancel",
        }
    )

    assert failed.percent == 55
    assert cancelled.percent == 8


def test_child_percent_does_not_regress_inside_the_same_phase() -> None:
    state = ResearchPipelineState(stage="searching", percent=8)
    MedicalWritingResearchPipelineService._apply_child_progress(
        state,
        phase="registry_search",
        completed=1,
        total=2,
        label="ClinicalTrials.gov 检索完成",
    )
    MedicalWritingResearchPipelineService._apply_child_progress(
        state,
        phase="registry_search",
        completed=0,
        total=2,
        child_percent=10,
        label="迟到的旧进度",
    )

    assert state.child_completed == 1
    assert state.child_percent == 50
    assert state.percent == 15


def test_search_publishes_two_real_registry_steps_and_empty_result_is_actionable() -> None:
    initial = ResearchPipelineState(
        pipeline_id="mwpipe_search_progress",
        project_id="proj_search_progress",
        stage="queued",
        percent=0,
    )

    class _JourneyService:
        def __init__(self) -> None:
            self.state = initial
            self.history = []
            self.journey = SimpleNamespace(
                research_pipeline=initial.as_dict(),
                search_plan=SimpleNamespace(
                    plan_id="plan_search_progress",
                    latest_snapshot_id="",
                    returned_count=0,
                ),
                framing=SimpleNamespace(
                    indication="慢性鼻窦炎伴鼻息肉",
                    study_phase="III期",
                    investigational_product="TEST-001",
                ),
                corpus_triage=None,
            )

        def get(self, _project_id):
            return self.journey

        def save_research_pipeline(self, _project_id, payload):
            self.state = ResearchPipelineState.from_dict(payload)
            self.journey.research_pipeline = self.state.as_dict()
            self.history.append(self.state.as_dict())

        def build_competitor_search_request(self, _project_id, _request):
            return {"query": "CRSwNP"}

        def attach_search_snapshot(self, _project_id, _snapshot, _request):
            return self.journey

    journey_service = _JourneyService()

    class _DiscoveryService:
        @staticmethod
        def create_search_snapshot(_project_id, _request):
            persisted = journey_service.state
            assert persisted.child_completed == 0
            assert persisted.child_total == 2
            assert persisted.child_label == "正在检索 ClinicalTrials.gov"
            return SimpleNamespace(
                snapshot_id="snapshot_empty",
                returned_count=0,
            )

    class _ChinaClient:
        @staticmethod
        def probe_and_search(**_kwargs):
            persisted = journey_service.state
            assert persisted.child_completed == 1
            assert persisted.child_total == 2
            assert "正在探针中国注册平台" in persisted.child_label
            return SimpleNamespace(
                as_dict=lambda: {"status": "reachable", "returned_count": 0}
            )

    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = journey_service
    service.discovery_service = _DiscoveryService()
    service.china_client_factory = _ChinaClient

    result = service.execute_stages(
        "proj_search_progress",
        initial,
        actor="medical_manager",
        auto_confirm_triage=False,
        heartbeat=lambda _progress: True,
    )

    registry_checkpoints = []
    for payload in journey_service.history:
        if payload["child_phase"] != "registry_search":
            continue
        checkpoint = (
            payload["child_completed"],
            payload["child_total"],
            payload["child_percent"],
            payload["percent"],
            payload["child_label"],
        )
        if not registry_checkpoints or registry_checkpoints[-1] != checkpoint:
            registry_checkpoints.append(checkpoint)

    assert registry_checkpoints == [
        (0, 2, 0, 8, "正在检索 ClinicalTrials.gov"),
        (1, 2, 50, 15, "ClinicalTrials.gov 检索完成，正在探针中国注册平台"),
        (2, 2, 100, 22, "中国注册平台探针完成"),
    ]
    assert result.stage == "awaiting_corpus_admission"
    assert result.error_summary == "no_public_protocol_results"
    assert result.child_context == {
        "fallback_mode": "shared_corpus_or_manual_upload",
        "confirmed_empty_basket": True,
        "downstream_heavy_stages_started": False,
    }
    assert result.percent == 90
    assert result.percent < 100


def test_both_analysis_rounds_publish_four_real_discrete_steps() -> None:
    for round_number, stage, start_percent, expected_parent_percent in (
        (1, "analyzing_round1", 85, 90),
        (2, "analyzing_round2", 96, 99),
    ):
        state = ResearchPipelineState(
            pipeline_id=f"mwpipe_analysis_round_{round_number}",
            project_id=f"proj_analysis_round_{round_number}",
            stage=stage,
            percent=start_percent,
            snapshot_id=f"snapshot_round_{round_number}",
            round1_ai_route={"profile_id": "synthesis-ai"},
        )

        class _JourneyService:
            def __init__(self) -> None:
                self.state = state
                self.history = []
                self.journey = SimpleNamespace(
                    research_pipeline=state.as_dict(),
                    framing=SimpleNamespace(),
                )

            def get(self, _project_id):
                return self.journey

            def save_research_pipeline(self, _project_id, payload):
                self.state = ResearchPipelineState.from_dict(payload)
                self.journey.research_pipeline = self.state.as_dict()
                self.history.append(self.state.as_dict())

        journey_service = _JourneyService()
        result_payload = {
            "status": "completed",
            "analysis_id": f"analysis_round_{round_number}",
            "output_hash": "a" * 64,
            "evidence_summary_ids": [f"finding_round_{round_number}"],
        }

        class _AnalysisService:
            @staticmethod
            def _project_context(_journey):
                return {"indication": "CRSwNP"}

            @staticmethod
            def _evidence_catalog(**_kwargs):
                return [
                    {
                        "evidence_id": "evidence_1",
                        "source_id": "artifact_1",
                        "evidence_text": "Protocol evidence",
                    }
                ]

            @staticmethod
            def analyze(**kwargs):
                persisted = journey_service.state
                assert persisted.child_completed == 2
                assert persisted.child_total == 4
                assert persisted.child_percent == 50
                assert "调用综合AI" in persisted.child_label
                if round_number == 2:
                    assert kwargs["pipeline_id"].endswith(":round2")
                return result_payload

            @staticmethod
            def get_analysis(_project_id, _analysis_id):
                return result_payload

        service = object.__new__(MedicalWritingResearchPipelineService)
        service.journey_service = journey_service
        service.corpus_analysis_ai_service = _AnalysisService()

        brief_ids = service._run_corpus_analysis(
            state.project_id,
            "medical_manager",
            state,
            round_number=round_number,
        )

        checkpoints = []
        for payload in journey_service.history:
            if payload["child_phase"] != f"round{round_number}_corpus_analysis":
                continue
            checkpoint = (
                payload["child_completed"],
                payload["child_percent"],
                payload["child_label"],
            )
            if not checkpoints or checkpoints[-1] != checkpoint:
                checkpoints.append(checkpoint)

        assert [item[0] for item in checkpoints] == [0, 1, 2, 3, 4]
        assert [item[1] for item in checkpoints] == [0, 25, 50, 75, 100]
        assert "收集" in checkpoints[0][2]
        assert "验证" in checkpoints[1][2]
        assert "调用综合AI" in checkpoints[2][2]
        assert "校验并持久化" in checkpoints[3][2]
        assert "已完成" in checkpoints[4][2]
        assert brief_ids == [f"finding_round_{round_number}"]
        assert state.percent == expected_parent_percent


def test_triage_projection_names_current_persisted_chunk_and_study() -> None:
    run = SimpleNamespace(
        run_id="triage_progress",
        snapshot_id="snapshot_progress",
        status="running",
        chunks=[
            SimpleNamespace(status="succeeded", chunk_id="chunk-1", results=[]),
            SimpleNamespace(
                status="running",
                chunk_id="chunk-2",
                results=[SimpleNamespace(nct_id="NCT00000002")],
            ),
        ],
    )
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.triage_service = SimpleNamespace(
        repository=SimpleNamespace(triage_run=lambda _project_id, _run_id: run)
    )
    state = ResearchPipelineState(
        project_id="proj_progress",
        stage="triaging",
        triage_run_id="triage_progress",
    )

    projection = service._triage_progress("proj_progress", state)

    assert projection["completed_chunks"] == 1
    assert projection["total_chunks"] == 2
    assert projection["percent"] == 50
    assert "2/2" in projection["label"]
    assert "NCT00000002" in projection["label"]
    assert projection["context"] == {
        "unit_type": "chunk",
        "current_chunk_id": "chunk-2",
        "current_study_id": "NCT00000002",
        "current_chunk_index": 2,
        "chunk_total": 2,
        "substep_percent": 0,
    }


def test_preparation_projection_keeps_real_page_substep_on_current_document() -> None:
    batch = {
        "status": "running",
        "document_item_count": 2,
        "completed_document_count": 0,
        "progress": {
            "phase": "ocr_rendering",
            "current_substep": "正在恢复第3页",
            "completed": 2,
            "total": 5,
            "percent": 18,
            "unit": "page",
            "context": {"page_index": 3},
        },
        "items": [
            {
                "item_kind": "public_document",
                "status": "running",
                "nct_id": "NCT00000003",
                "filename": "Protocol-003.pdf",
                "progress": {
                    "phase": "ocr_rendering",
                    "current_substep": "正在恢复第3页",
                    "completed": 2,
                    "total": 5,
                    "percent": 40,
                    "unit": "page",
                },
            },
            {"item_kind": "public_document", "status": "pending", "nct_id": "NCT00000004"},
        ],
    }

    projection = MedicalWritingResearchPipelineService._preparation_progress_projection(
        batch
    )

    assert projection["completed"] == 0
    assert projection["total"] == 2
    assert projection["child_percent"] == 18
    assert "NCT00000003 / Protocol-003.pdf" in projection["label"]
    assert "正在恢复第3页" in projection["label"]
    assert "子步骤 40%" in projection["label"]
    assert projection["context"]["unit_type"] == "page"
    assert projection["context"]["current_substep_percent"] == 40
    assert projection["context"]["page_index"] == 3


def test_translation_projection_names_current_persisted_chapter() -> None:
    batch = {
        "status": "running",
        "counts": {"item_count": 2},
        "items": [
            {
                "generation_status": "candidate_ready",
                "ich_m11_anchor": "objectives_endpoints",
                "nct_id": "NCT00000005",
                "filename": "Protocol-005.pdf",
            },
            {
                "generation_status": "pending",
                "ich_m11_anchor": "safety",
                "nct_id": "NCT00000006",
                "filename": "Protocol-006.pdf",
            },
        ],
    }

    projection = MedicalWritingResearchPipelineService._translation_progress_projection(
        batch
    )

    assert projection["completed"] == 1
    assert projection["total"] == 2
    assert projection["child_percent"] == 42
    assert "NCT00000006 / Protocol-006.pdf / 安全性" in projection["label"]
    assert projection["context"]["unit_type"] == "chapter"
    assert projection["context"]["current_chapter_label"] == "安全性"
    assert projection["context"]["current_substep_percent"] == 0


def test_translation_projection_uses_real_stage_and_chunk_progress() -> None:
    batch = {
        "status": "running",
        "counts": {"item_count": 2},
        "items": [
            {
                "generation_status": "candidate_ready",
                "ich_m11_anchor": "objectives_endpoints",
            },
            {
                "generation_status": "running",
                "pipeline_stage": "translating_hy_mt2",
                "pipeline_stage_detail": "正在翻译第3/10个分块",
                "ich_m11_anchor": "safety",
                "chunk_count": 10,
                "chunk_completed": 3,
                "chunk_running": 1,
            },
        ],
    }

    projection = MedicalWritingResearchPipelineService._translation_progress_projection(
        batch
    )

    # Item one is complete; item two is 31% through the persisted translation
    # stages: 10% planning boundary + 70% * 3/10 completed chunks.
    assert projection["context"]["item_percent"] == 66
    assert projection["context"]["current_substep_percent"] == 31
    assert projection["child_percent"] == 54
