"""NEW-9（R27 第1轮末修订）：零篮子确认不得静默锁死。

反例（R1A 内部测试者一现场）：本适应症候选全为 I 期 PK 研究被合理排除 →
确认分诊时篮子必为 0 → 旧行为静默落 awaiting_corpus_admission 空篮锁定，
筛选/标记/重新检索全部禁用，正常按流程操作必然死锁。修复后：
- 无语料出路记录（共享语料/手动上传未准入、语料门例外未记录）时，
  continue_after_triage 对零篮子拒绝（API 层 409），并给出三条出路；
- 已记录例外（corpus_gate override/access_permitted）时，空篮子是合法
  医学决定，维持可行动的 awaiting_corpus_admission 兜底。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineConflictError,
    ResearchPipelineState,
)

PROJECT_ID = "proj_zero_basket_guard"


def _service(journey) -> MedicalWritingResearchPipelineService:
    return MedicalWritingResearchPipelineService(
        journey_service=journey,
        discovery_service=SimpleNamespace(),
        triage_service=SimpleNamespace(repository=SimpleNamespace()),
        preparation_batch_service=SimpleNamespace(),
        translation_batch_service=SimpleNamespace(),
        corpus_readiness_service=SimpleNamespace(),
        china_client_factory=lambda: None,
        corpus_analysis_ai_service=SimpleNamespace(),
    )


def _state() -> ResearchPipelineState:
    return ResearchPipelineState(
        pipeline_id="mwpipe_zero_basket",
        project_id=PROJECT_ID,
        stage="awaiting_triage_confirm",
        snapshot_id="wref_zero_basket",
    )


def _journey(override_active: bool, access_permitted: bool = False) -> SimpleNamespace:
    journey = _journey_payload(override_active, access_permitted)
    journey.get = lambda project_id: journey
    return journey


def _journey_payload(override_active: bool, access_permitted: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        search_plan=SimpleNamespace(latest_snapshot_id="wref_zero_basket"),
        corpus_gate=SimpleNamespace(
            access_permitted=access_permitted,
            override=SimpleNamespace(active=override_active),
        ),
    )


def _install_empty_confirm(monkeypatch: pytest.MonkeyPatch, service) -> None:
    monkeypatch.setattr(
        service, "_confirm_triage_basket", lambda *args, **kwargs: []
    )
    fallback_state = _state()
    fallback_state.stage = "awaiting_corpus_admission"
    fallback_state.error_summary = "no_retainable_candidates"
    monkeypatch.setattr(
        service,
        "_persist_no_retainable_candidate_fallback",
        lambda *args, **kwargs: fallback_state,
    )


def test_zero_basket_confirm_without_exception_record_is_refused(monkeypatch) -> None:
    journey = _journey(override_active=False)
    service = _service(journey)
    _install_empty_confirm(monkeypatch, service)

    with pytest.raises(ResearchPipelineConflictError) as refused:
        service.continue_after_triage(PROJECT_ID, actor="medical_manager_test")

    message = str(refused.value)
    assert "0 项" in message
    # 三条出路必须逐一点名（与前端 title 同款文案口径）。
    assert "标记为保留" in message or "重新确认" in message
    assert "检索" in message
    assert "共享语料或手动上传" in message
    assert "例外" in message


def test_zero_basket_confirm_with_recorded_exception_keeps_actionable_fallback(
    monkeypatch,
) -> None:
    journey = _journey(override_active=True)
    service = _service(journey)
    _install_empty_confirm(monkeypatch, service)

    state = service.continue_after_triage(PROJECT_ID, actor="medical_manager_test")

    assert state.stage == "awaiting_corpus_admission"
    assert state.error_summary == "no_retainable_candidates"


def test_zero_basket_confirm_with_admitted_corpus_keeps_actionable_fallback(
    monkeypatch,
) -> None:
    journey = _journey(override_active=False, access_permitted=True)
    service = _service(journey)
    _install_empty_confirm(monkeypatch, service)

    state = service.continue_after_triage(PROJECT_ID, actor="medical_manager_test")

    assert state.stage == "awaiting_corpus_admission"
