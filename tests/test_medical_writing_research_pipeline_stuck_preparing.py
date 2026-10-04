"""R26 自检第4次（本轮）P0-1：AI分诊路径研究流水线 preparing 死锁。

现场（proj_user_97c9c19afb20，backend_5301_round27_restart.log）：
1. 分诊运行期间用户编辑研究框架事实 → triage run 过期；
2. 用户点『确认分诊后继续』：continue_after_triage 先持久化 stage=preparing，
   再创建准备批次；confirm_basket 因过期失败 → 回退 legacy finalize 又因
   PICOS 未完成必然失败 → 准备批次创建抛
   "preparation requires either finalized corpus triage or a confirmed
   discovery basket projection for the locked snapshot"（422）；
   流水线被毒化停留在 preparing(50%)、无批次、无 durable 作业；
3. 用户重新分诊后点『确认并锁定全部824项』：confirm 成功 + discovery 投影
   写入，但 advance_after_basket_confirm 只接受 awaiting_triage_confirm，
   静默返回 advanced=False，不创建续跑作业；
4. 『确认分诊后继续』按钮只按 awaiting_triage_confirm 渲染（消失），
   resume 端点拒绝 preparing（"当前阶段 preparing 不允许从文档处理入口恢复"），
   唯一出路=取消研究流水线（现场实测后端无外连、CPU≈0）。

修复契约（红先修后）：
- ① continue_after_triage/_continue_after_confirmed_triage：准备批次创建
  失败时不得把流水线毒化在 preparing——回退到 awaiting_triage_confirm
  （真实可行动门：按钮可见、advance 可再入）后原样抛错；
- ② advance_after_basket_confirm：篮子已确认（锁定快照存在确认投影）且
  流水线卡在 preparing、无准备批次、无在途 durable 作业时，必须创建
  durable 续跑作业（自愈既有毒化状态，而不是静默 advanced=False）；
- ③ status() 读路径自愈：同样条件的卡死 preparing 在状态读取时被
  reconcile 回 awaiting_triage_confirm（前端轮询即可恢复按钮）；
- ④ _confirm_triage_basket：两条确认路径都没有把任何篮子权威写入 journey
  时，抛出可行动的明确错误（说明分诊已过期/需重新确认或补 PICOS），
  而不是放行进入必然失败的原文准备。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineError,
    ResearchPipelineState,
)

PROJECT_ID = "proj_stuck_preparing_guard"
SNAPSHOT_ID = "wref_stuck_preparing"


class _JourneyStore:
    """Minimal journey service double with in-memory pipeline persistence."""

    def __init__(self, journey_payload):
        self._journey = journey_payload
        self._pipeline = None

    def get(self, project_id):
        return self._namespace()

    def _namespace(self):
        journey = SimpleNamespace(**dict(self._journey))
        if self._pipeline is not None:
            journey.research_pipeline = self._pipeline
        else:
            journey.research_pipeline = None
        return journey

    def save_research_pipeline(self, project_id, payload):
        self._pipeline = payload
        return self._namespace()


def _journey_payload(
    *,
    discovery_retained=None,
    corpus_finalized=False,
    corpus_retained=None,
):
    payload = {
        "search_plan": SimpleNamespace(latest_snapshot_id=SNAPSHOT_ID),
        "corpus_gate": SimpleNamespace(
            access_permitted=False,
            override=SimpleNamespace(active=False),
        ),
    }
    if discovery_retained is not None:
        payload["discovery_basket_projection"] = SimpleNamespace(
            confirmation_id="ct_conf_stuck_001",
            confirmation_hash="hash_stuck_001",
            snapshot_id=SNAPSHOT_ID,
            retained_nct_ids=list(discovery_retained),
            excluded_nct_ids=[],
            run_id="ct_run_stuck_001",
            actor="medical_manager",
            reason="确认竞品篮子",
            projected_at="2026-10-03T00:00:00+00:00",
        )
    if corpus_finalized or corpus_retained:
        payload["corpus_triage"] = SimpleNamespace(
            status="finalized" if corpus_finalized else "pending",
            snapshot_id=SNAPSHOT_ID,
            retained_candidate_ids=list(corpus_retained or []),
            reason="",
            actor="medical_manager",
            finalized_at="2026-10-03T00:00:00+00:00",
        )
    return payload


def _service(journey_store, durable_store=None, durable_worker=None):
    return MedicalWritingResearchPipelineService(
        journey_service=journey_store,
        discovery_service=SimpleNamespace(),
        triage_service=SimpleNamespace(repository=SimpleNamespace()),
        preparation_batch_service=SimpleNamespace(),
        translation_batch_service=SimpleNamespace(),
        corpus_readiness_service=SimpleNamespace(),
        china_client_factory=lambda: None,
        durable_store=durable_store,
        durable_worker=durable_worker,
        corpus_analysis_ai_service=SimpleNamespace(),
    )


def _seed_state(journey_store, stage="awaiting_triage_confirm"):
    state = ResearchPipelineState(
        pipeline_id="mwpipe_stuck_preparing",
        project_id=PROJECT_ID,
        stage=stage,
        snapshot_id=SNAPSHOT_ID,
        triage_run_id="ct_run_stuck_001",
    )
    journey_store.save_research_pipeline(PROJECT_ID, state.as_dict())
    return state


class _FakeDurableStore:
    def __init__(self):
        self.jobs = {}

    def create_or_reuse(self, request):
        self.jobs[request.business_key] = request
        return SimpleNamespace(job_id=f"mwjob_{len(self.jobs)}")

    def get(self, project_id, job_id):
        return self.jobs.get(job_id) and SimpleNamespace(status="completed")


class _FakeDurableWorker:
    def __init__(self):
        self.executors = []
        self.woken = []

    def register_executor(self, executor):
        self.executors.append(executor)

    def wake(self, project_id, job_id):
        self.woken.append(job_id)
        return True


# --- ① 准备批次创建失败不得毒化 preparing -------------------------------


def test_continue_after_triage_reverts_preparing_when_preparation_create_fails(
    monkeypatch,
):
    store = _JourneyStore(_journey_payload())
    service = _service(store)
    _seed_state(store)

    monkeypatch.setattr(
        service,
        "_confirm_triage_basket",
        lambda *args, **kwargs: ["NCT00000001"],
    )
    monkeypatch.setattr(
        service, "_find_reusable_preparation_batch", lambda *a, **k: None
    )

    def _fail_create(*args, **kwargs):
        raise ValueError(
            "preparation requires either finalized corpus triage or a "
            "confirmed discovery basket projection for the locked snapshot"
        )

    monkeypatch.setattr(
        service.preparation_batch_service, "create", _fail_create, raising=False
    )

    with pytest.raises(ValueError) as raised:
        service.continue_after_triage(PROJECT_ID, actor="medical_manager")

    assert "preparation requires" in str(raised.value)
    persisted = service.get_state(PROJECT_ID)
    assert persisted.stage != "preparing", (
        "准备批次创建失败后流水线不得停留在 preparing（现场死锁态）；"
        "应回到 awaiting_triage_confirm 让『确认分诊后继续』按钮与"
        "篮子确认 advance 仍可进入。"
    )
    assert persisted.stage == "awaiting_triage_confirm"


def test_continue_after_confirmed_triage_reverts_preparing_on_prep_failure(
    monkeypatch,
):
    store = _JourneyStore(
        _journey_payload(discovery_retained=["NCT00000001"])
    )
    service = _service(store)
    _seed_state(store)

    monkeypatch.setattr(
        service, "_find_reusable_preparation_batch", lambda *a, **k: None
    )

    def _fail_create(*args, **kwargs):
        raise ValueError("confirmed basket has no retained candidates")

    monkeypatch.setattr(
        service.preparation_batch_service, "create", _fail_create, raising=False
    )

    with pytest.raises(ValueError):
        service._continue_after_confirmed_triage(
            PROJECT_ID,
            actor="medical_manager",
            frozen_retained_ids=["NCT00000001"],
        )

    persisted = service.get_state(PROJECT_ID)
    assert persisted.stage != "preparing"
    assert persisted.stage == "awaiting_triage_confirm"


# --- ② advance_after_basket_confirm 自愈卡死 preparing -------------------


def test_advance_after_basket_confirm_recovers_stuck_preparing_without_batch():
    store = _JourneyStore(
        _journey_payload(discovery_retained=["NCT00000001", "NCT00000002"])
    )
    durable_store = _FakeDurableStore()
    worker = _FakeDurableWorker()
    service = _service(store, durable_store=durable_store, durable_worker=worker)
    state = _seed_state(store, stage="preparing")
    # 现场毒化态：无准备批次、无在途作业。
    assert not state.prep_batch_id
    assert not state.job_id

    result = service.advance_after_basket_confirm(
        PROJECT_ID,
        actor="medical_manager",
        idempotency_key="recover-stuck-preparing-001",
    )

    assert result.get("advanced") is True, (
        "篮子已确认且流水线卡在 preparing（无批次、无在途作业）时，"
        "确认端点的 advance 必须创建 durable 续跑作业自愈，而不是静默"
        "返回 advanced=False 把用户推向取消流水线。"
    )
    assert result.get("job_id")
    assert worker.woken, "durable 续跑作业创建后必须唤醒 worker"
    assert service.get_state(PROJECT_ID).stage == "preparing"


def test_advance_after_basket_confirm_ignores_preparing_without_confirmed_basket():
    store = _JourneyStore(_journey_payload())
    durable_store = _FakeDurableStore()
    worker = _FakeDurableWorker()
    service = _service(store, durable_store=durable_store, durable_worker=worker)
    _seed_state(store, stage="preparing")

    result = service.advance_after_basket_confirm(
        PROJECT_ID,
        actor="medical_manager",
        idempotency_key="recover-stuck-preparing-002",
    )

    assert result.get("advanced") is False
    assert not durable_store.jobs


# --- ③ status() 读路径自愈 ------------------------------------------------


def test_status_reconciles_stuck_preparing_back_to_triage_confirm():
    store = _JourneyStore(
        _journey_payload(discovery_retained=["NCT00000001"])
    )
    service = _service(store)
    _seed_state(store, stage="preparing")

    payload = service.status(PROJECT_ID)

    stage = payload.get("pipeline", {}).get("stage") or payload.get("stage")
    assert stage == "awaiting_triage_confirm", (
        "卡死的 preparing（无批次、无在途作业、篮子已确认）应在状态读取时"
        "自愈回 awaiting_triage_confirm，让前端轮询恢复继续入口。"
    )
    assert service.get_state(PROJECT_ID).stage == "awaiting_triage_confirm"


def test_status_keeps_preparing_while_durable_job_live():
    store = _JourneyStore(
        _journey_payload(discovery_retained=["NCT00000001"])
    )
    durable_store = _FakeDurableStore()

    class _LiveJobStore(_FakeDurableStore):
        def get(self, project_id, job_id):
            return SimpleNamespace(status="running")

    live_store = _LiveJobStore()
    service = _service(store, durable_store=live_store)
    state = _seed_state(store, stage="preparing")
    state.job_id = "mwjob_live_001"
    store.save_research_pipeline(PROJECT_ID, state.as_dict())

    payload = service.status(PROJECT_ID)

    stage = payload.get("pipeline", {}).get("stage") or payload.get("stage")
    assert stage == "preparing", "在途 durable 作业的 preparing 不得被读路径改写"
    assert service.get_state(PROJECT_ID).stage == "preparing"


# --- ④ 无篮子权威时给出可行动错误 ---------------------------------------


def test_confirm_triage_basket_raises_actionable_error_without_journey_authority(
    monkeypatch,
):
    store = _JourneyStore(_journey_payload())
    service = _service(store)
    state = _seed_state(store)

    class _StaleTriageService:
        class repository:
            @staticmethod
            def triage_run(project_id, run_id):
                raise KeyError(run_id)

        @staticmethod
        def confirm_basket(*args, **kwargs):
            raise RuntimeError("competitor triage run is stale")

    service.triage_service = _StaleTriageService()

    class _FailingFinalize:
        @staticmethod
        def finalize_triage(*args, **kwargs):
            raise ValueError(
                "PICOS and competitor search must be complete before "
                "triage finalization"
            )

    service.corpus_readiness_service = _FailingFinalize()
    monkeypatch.setattr(
        service,
        "_auto_retain_public_protocol_candidates",
        lambda *args, **kwargs: ["NCT00000001"],
    )

    with pytest.raises(ResearchPipelineError) as raised:
        service._confirm_triage_basket(
            PROJECT_ID, "medical_manager", state, None
        )

    message = str(raised.value)
    assert "重新" in message and "分诊" in message, (
        "两条确认路径都未写入篮子权威时必须给出含重新分诊指引的可行动"
        f"错误，实际：{message}"
    )
