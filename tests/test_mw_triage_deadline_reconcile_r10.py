"""Deterministic tests for the research-pipeline triage deadline race (r10).

At the 900-second polling boundary the parent research pipeline can exhaust its
deadline while the durable competitor-triage child finishes inside the last
sleep window. Before raising ``分诊超时`` the parent must perform one final
authoritative reconciliation of the durable child and the bound triage run:

- a completed/review-ready child/run/snapshot promotes the parent to
  ``awaiting_triage_confirm`` (no duplicate AI work, no retry offered);
- a genuinely incomplete or failed child still fails truthfully.

These tests drive ``_await_triage_child`` / ``_triage_review_ready_at_deadline``
directly with a fake clock so the deadline edge is exercised deterministically.
The fake clock starts *before* the deadline and jumps far past it on the first
``sleep`` — reproducing the exact race where the child completes inside the last
sleep window: the polling loop reads a non-terminal child, sleeps past the
deadline, and the final reconciliation then reads the completed child.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from packages.contracts.workbench_contracts import (
    DurableJobCreateRequest,
    DurableJobProgressPayload,
    DurableJobRecord,
)
from services.api.app.medical_writing_durable_jobs import (
    DurableJobStore,
    DurableJobWorker,
)
from services.api.app.medical_writing_research_pipeline import (
    MedicalWritingResearchPipelineService,
    ResearchPipelineDurableExecutor,
    ResearchPipelineError,
    ResearchPipelineState,
    TriageWaitTimeoutError,
)

PROJECT_ID = "proj_copd"
PIPELINE_ID = "mwpipe_copd"
SNAPSHOT_ID = "wref_search_copd"
RUN_ID = "ct_run_copd"
JOB_ID = "mwjob_child_copd"


class _FakeClock:
    """Deterministic clock: starts before the deadline, jumps past it on sleep."""

    def __init__(self, start: float = 1000.0, sleep_jump: float = 2000.0) -> None:
        self.now = start
        self.sleep_jump = sleep_jump
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += self.sleep_jump


class _FakeDurableStore:
    """Returns a scripted sequence of child statuses across successive polls.

    The last status is sticky once the sequence is exhausted, so the in-loop
    poll and the final reconciliation can observe different states — exactly
    the race where the child finishes inside the last sleep window.
    """

    def __init__(self, statuses: list[str], error_summary: str = "") -> None:
        self._statuses = list(statuses)
        self._error_summary = error_summary
        self.get_calls = 0

    def get(self, project_id: str, job_id: str) -> DurableJobRecord:
        assert project_id == PROJECT_ID
        assert job_id == JOB_ID
        index = min(self.get_calls, len(self._statuses) - 1)
        self.get_calls += 1
        return _record(self._statuses[index], self._error_summary)


class _JourneyService:
    def __init__(self, state: ResearchPipelineState) -> None:
        self.state = state
        self.save_count = 0

    def get(self, project_id: str) -> SimpleNamespace:
        assert project_id == PROJECT_ID
        return SimpleNamespace(
            research_pipeline=self.state.as_dict(),
            corpus_gate=None,
        )

    def save_research_pipeline(self, project_id: str, payload: dict) -> None:
        assert project_id == PROJECT_ID
        self.state = ResearchPipelineState.from_dict(payload)
        self.save_count += 1


def _chunks(specs: list[tuple[str, str]]) -> list[SimpleNamespace]:
    return [SimpleNamespace(chunk_id=cid, status=status) for cid, status in specs]


def _run(status: str, chunks: list[SimpleNamespace] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=RUN_ID,
        snapshot_id=SNAPSHOT_ID,
        status=status,
        chunks=chunks or [],
    )


def _state(stage: str = "triaging", error_summary: str = "") -> ResearchPipelineState:
    return ResearchPipelineState(
        pipeline_id=PIPELINE_ID,
        project_id=PROJECT_ID,
        stage=stage,
        percent=22,
        snapshot_id=SNAPSHOT_ID,
        triage_run_id=RUN_ID,
        error_summary=error_summary,
    )


def _service(
    state: ResearchPipelineState,
    run: SimpleNamespace,
    store: _FakeDurableStore,
) -> tuple[MedicalWritingResearchPipelineService, _JourneyService]:
    journey_service = _JourneyService(state)
    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = journey_service
    service.triage_service = SimpleNamespace(
        repository=SimpleNamespace(
            triage_run=lambda project_id, run_id: (
                run
                if project_id == PROJECT_ID and run_id == RUN_ID
                else None
            )
        )
    )
    service.durable_store = store
    service._lock = threading.RLock()
    return service, journey_service


def _record(status: str, error_summary: str = "") -> DurableJobRecord:
    return DurableJobRecord(
        job_id=JOB_ID,
        project_id=PROJECT_ID,
        job_type="competitor_triage",
        business_key="bk",
        request_hash="0123456789abcdef",
        status=status,
        progress=DurableJobProgressPayload(percent=1.0),
        error_summary=error_summary,
        created_at="2026-07-28T15:05:56+00:00",
        updated_at="2026-07-28T15:20:54+00:00",
    )


def _patch_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    import services.api.app.medical_writing_research_pipeline as module

    monkeypatch.setattr(module.time, "time", clock.time)
    monkeypatch.setattr(module.time, "monotonic", clock.time)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)
    return clock


def _drive(service: MedicalWritingResearchPipelineService) -> bool:
    return service._await_triage_child(
        PROJECT_ID,
        service.get_state(PROJECT_ID),
        JOB_ID,
        actor="medical_manager",
        pulse=lambda _detail: None,
    )


def test_child_completed_on_final_deadline_edge_promotes_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child that is completed/review-ready exactly at the deadline edge must
    promote the parent to awaiting_triage_confirm, not report 分诊超时."""
    chunks = _chunks([("chunk-%02d" % i, "succeeded") for i in range(19)])
    run = _run("review_ready", chunks)
    # In-loop poll sees the child still running; the final reconciliation (after
    # the sleep jumps past the deadline) sees it completed.
    store = _FakeDurableStore(["running", "completed"])
    service, journey = _service(_state(), run, store)
    clock = _patch_clock(monkeypatch)

    stopped = _drive(service)

    assert stopped is False
    # Exactly one in-loop poll + sleep, then the deadline-edge reconciliation.
    assert clock.sleeps == [2.5]
    assert store.get_calls == 2
    # The helper authorizes the normal post-triage path; it must not own the
    # pause or bypass the caller's auto-confirm branch.
    assert journey.state.stage == "triaging"
    assert journey.save_count == 0


def test_deadline_edge_reconciliation_never_duplicates_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the deadline-edge promotion, repeated status polls are idempotent
    and no retry/new-run control is offered for the review-ready run."""
    chunks = _chunks([("chunk-%02d" % i, "succeeded") for i in range(19)])
    run = _run("review_ready", chunks)
    store = _FakeDurableStore(["running", "completed"])
    service, journey = _service(_state(), run, store)
    _patch_clock(monkeypatch)

    assert _drive(service) is False

    def _forbidden(*_args, **_kwargs):  # pragma: no cover - defensive
        raise AssertionError("deadline reconciliation must not start triage work")

    service.triage_service.create_run = _forbidden
    service.triage_service.retry_run = _forbidden

    # A second wait observes the same completed child and returns normally;
    # neither pass creates or retries AI work.
    assert _drive(service) is False
    assert journey.save_count == 0


def test_deadline_edge_preserves_auto_confirm_continuation_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(
        "review_ready",
        _chunks([("chunk-%02d" % i, "succeeded") for i in range(19)]),
    )
    store = _FakeDurableStore(["running", "completed"])
    service, journey = _service(_state(), run, store)
    _patch_clock(monkeypatch)

    # False is the same outcome as in-window completion. execute_stages owns
    # the subsequent `if not auto_confirm_triage` / continue_after_triage
    # branch, so deadline-edge completion cannot bypass auto-confirm.
    assert _drive(service) is False
    assert journey.state.stage == "triaging"
    assert journey.save_count == 0


def test_execute_stages_auto_confirm_continues_after_deadline_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real stage orchestrator must continue after deadline-edge success.

    This guards the semantic regression where ``_await_triage_child`` returned
    ``True`` for a completed child and made ``execute_stages`` return early,
    silently bypassing the existing auto-confirm continuation.
    """
    state = _state(stage="idle")
    run = _run(
        "review_ready",
        _chunks([("chunk-%02d" % i, "succeeded") for i in range(19)]),
    )
    store = _FakeDurableStore(["running", "completed"])
    journey = _JourneyService(state)
    journey.get = lambda project_id: SimpleNamespace(
        research_pipeline=journey.state.as_dict(),
        corpus_gate=None,
        search_plan=SimpleNamespace(
            latest_snapshot_id=SNAPSHOT_ID,
            returned_count=19,
        ),
        framing=SimpleNamespace(
            indication="慢性阻塞性肺疾病",
            study_phase="III期",
            investigational_product="吸入制剂",
        ),
        corpus_triage=None,
        revision=1,
    )

    service = object.__new__(MedicalWritingResearchPipelineService)
    service.journey_service = journey
    service.discovery_service = SimpleNamespace()
    service.china_client_factory = lambda: SimpleNamespace(
        probe_and_search=lambda **_kwargs: SimpleNamespace(
            as_dict=lambda: {"status": "not_available"}
        )
    )
    service.triage_provider_factory = lambda: object()
    service.triage_service = SimpleNamespace(
        repository=SimpleNamespace(
            triage_run=lambda project_id, run_id: (
                run
                if project_id == PROJECT_ID and run_id == RUN_ID
                else None
            )
        ),
        create_run=lambda project_id, request, provider: SimpleNamespace(
            run_id=RUN_ID,
            job_id=JOB_ID,
        ),
    )
    service.durable_store = store
    service._lock = threading.RLock()
    continuation_calls: list[dict] = []

    def _continue_after_triage(project_id: str, **kwargs):
        continuation_calls.append(
            {
                "project_id": project_id,
                "stage_at_call": kwargs["state"].stage,
                "detail_at_call": kwargs["state"].detail,
            }
        )
        return service._set_stage(
            kwargs["state"],
            "preparing",
            detail="已进入分诊后的标准继续路径",
        )

    service.continue_after_triage = _continue_after_triage
    clock = _patch_clock(monkeypatch)

    result = service.execute_stages(
        PROJECT_ID,
        state,
        actor="medical_manager",
        auto_confirm_triage=True,
        heartbeat=lambda _progress: True,
    )

    assert clock.sleeps == [2.5]
    assert store.get_calls == 2
    assert result.stage == "preparing"
    assert len(continuation_calls) == 1
    assert continuation_calls[0]["project_id"] == PROJECT_ID
    assert continuation_calls[0]["stage_at_call"] == "awaiting_triage_confirm"
    assert "自动保留" in continuation_calls[0]["detail_at_call"]


def test_genuine_timeout_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A child still queued when the deadline is exhausted must fail truthfully
    with 分诊超时 and leave the parent unpromoted."""
    run = _run("running", _chunks([("chunk-00", "pending")]))
    store = _FakeDurableStore(["queued"])
    service, journey = _service(_state(), run, store)
    _patch_clock(monkeypatch)

    with pytest.raises(ResearchPipelineError, match="分诊超时"):
        _drive(service)

    assert journey.state.stage == "triaging"
    assert journey.save_count == 0


def test_completed_child_but_unready_run_still_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A completed durable child whose bound run is not review-ready must not be
    promoted — the parent still fails with 分诊超时 (fail-closed)."""
    run = _run("running", _chunks([("chunk-00", "running")]))
    store = _FakeDurableStore(["running", "completed"])
    service, journey = _service(_state(), run, store)
    _patch_clock(monkeypatch)

    with pytest.raises(ResearchPipelineError, match="分诊超时"):
        _drive(service)

    assert journey.state.stage == "triaging"
    assert journey.save_count == 0


def test_failed_child_at_deadline_reports_truthful_child_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed durable child must surface its own error, never 分诊超时."""
    run = _run("failed", _chunks([("chunk-00", "failed")]))
    store = _FakeDurableStore(["running", "failed"], error_summary="model overload")
    service, _journey = _service(_state(), run, store)
    _patch_clock(monkeypatch)

    with pytest.raises(ResearchPipelineError, match="分诊任务结束为 failed"):
        _drive(service)


def test_progress_projection_agrees_with_durable_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the deadline-edge promotion, the user-facing projection reflects the
    durable run (review-ready, live chunk counts) and offers no retry."""
    chunks = _chunks([("chunk-%02d" % i, "succeeded") for i in range(19)])
    run = _run("review_ready", chunks)
    store = _FakeDurableStore(["running", "completed"])
    service, _journey = _service(
        _state(stage="failed", error_summary="ResearchPipelineError: 分诊超时"),
        run,
        store,
    )
    _patch_clock(monkeypatch)

    assert _drive(service) is False
    # Simulate the standard post-triage pause owned by execute_stages.
    state = service._set_stage(
        service.get_state(PROJECT_ID),
        "awaiting_triage_confirm",
        detail="分诊已完成，请确认保留的竞品篮子后继续下载方案原文。",
        eta_seconds=None,
    )
    service._persist(PROJECT_ID, state)

    status = service.status(PROJECT_ID)
    progress = status["triage_progress"]
    assert progress["run_id"] == RUN_ID
    assert progress["snapshot_id"] == SNAPSHOT_ID
    assert progress["status"] == "review_ready"
    assert progress["completed_chunks"] == 19
    assert progress["total_chunks"] == 19
    assert progress["percent"] == 100
    assert status["pipeline"]["stage"] == "awaiting_triage_confirm"
    assert status["triage_retryable"] is False


def test_normal_completion_before_deadline_uses_standard_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child that completes inside the polling window returns control to the
    standard confirm pause (unchanged behavior, no deadline reconciliation)."""
    run = _run("review_ready", _chunks([("chunk-00", "succeeded")]))
    store = _FakeDurableStore(["completed"])
    service, journey = _service(_state(), run, store)
    # Clock stays before the deadline and never jumps: the first poll sees the
    # completed child and breaks out of the loop normally.
    import services.api.app.medical_writing_research_pipeline as module

    monkeypatch.setattr(module.time, "time", lambda: 1000.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: 1000.0)
    monkeypatch.setattr(module.time, "sleep", lambda _s: None)

    stopped = _drive(service)

    assert stopped is False
    assert store.get_calls == 1
    assert journey.save_count == 0


def test_business_progress_can_continue_beyond_old_900_second_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monotonic child progress keeps the parent waiting beyond the old edge."""
    run = _run("review_ready", _chunks([("chunk-00", "succeeded")]))
    store = _FakeDurableStore(["running", "running", "running", "completed"])
    service, journey = _service(_state(), run, store)
    clock = _FakeClock(start=1000.0, sleep_jump=400.0)
    import services.api.app.medical_writing_research_pipeline as module

    monkeypatch.setattr(module.time, "time", clock.time)
    monkeypatch.setattr(module.time, "monotonic", clock.time)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)
    completed = iter([1, 2, 3, 4])
    service._triage_progress = lambda _project_id, _state: {
        "completed_chunks": next(completed),
        "total_chunks": 4,
        "percent": 25,
        "label": "正在处理竞品分诊",
    }

    assert _drive(service) is False
    assert clock.now - 1000.0 == 1200.0
    assert store.get_calls == 4
    assert journey.state.stage == "triaging"


def test_live_lease_without_business_progress_still_stalls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lease heartbeat is liveness evidence, not business-progress evidence."""
    run = _run("running", _chunks([("chunk-00", "pending")]))
    store = _FakeDurableStore(["running"])
    service, _journey = _service(_state(), run, store)
    clock = _FakeClock(start=1000.0, sleep_jump=1300.0)
    import services.api.app.medical_writing_research_pipeline as module

    monkeypatch.setattr(module.time, "time", clock.time)
    monkeypatch.setattr(module.time, "monotonic", clock.time)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)

    with pytest.raises(TriageWaitTimeoutError, match="未产生新的业务进度"):
        _drive(service)


def test_absolute_ceiling_applies_even_when_progress_keeps_advancing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intermittent progress cannot keep the parent alive without a hard cap."""
    run = _run("running", _chunks([("chunk-00", "running")]))
    store = _FakeDurableStore(["running"])
    service, _journey = _service(_state(), run, store)
    clock = _FakeClock(start=1000.0, sleep_jump=2500.0)
    import services.api.app.medical_writing_research_pipeline as module

    monkeypatch.setattr(module.time, "time", clock.time)
    monkeypatch.setattr(module.time, "monotonic", clock.time)
    monkeypatch.setattr(module.time, "sleep", clock.sleep)
    counter = {"value": 0}

    def _progress(_project_id, _state):
        counter["value"] += 1
        return {
            "completed_chunks": counter["value"],
            "total_chunks": 99,
            "percent": counter["value"],
            "label": "正在处理竞品分诊",
        }

    service._triage_progress = _progress

    with pytest.raises(TriageWaitTimeoutError, match="绝对等待上限"):
        _drive(service)
    assert clock.now - 1000.0 >= 7200.0


def test_parent_timeout_is_non_retryable_and_never_projects_terminal_100() -> None:
    """A live child timeout must not enqueue a duplicate parent attempt."""
    run = _run(
        "running",
        _chunks(
            [("chunk-%02d" % i, "succeeded" if i < 8 else "pending")
             for i in range(15)]
        ),
    )
    store = _FakeDurableStore(["running"])
    state = _state()
    state.round1_ai_route = {"provider": "alibaba", "model": "qwen3.8-max-preview"}
    service, journey = _service(state, run, store)

    def _timeout(*_args, **_kwargs):
        raise TriageWaitTimeoutError("分诊超时：子任务长时间未产生新的业务进度")

    service.execute_stages = _timeout
    job = DurableJobRecord(
        job_id="mwjob_parent_copd",
        project_id=PROJECT_ID,
        job_type="research_pipeline",
        business_key="bk-parent",
        request_hash="abcdef0123456789",
        status="running",
        progress=DurableJobProgressPayload(percent=0.22),
        payload_json=(
            '{"actor":"medical_manager","auto_confirm_triage":true,'
            '"corpus_analysis_ai_route":'
            '{"provider":"alibaba","model":"qwen3.8-max-preview"}}'
        ),
        created_at="2026-07-28T15:05:56+00:00",
        updated_at="2026-07-28T15:20:54+00:00",
    )

    result = ResearchPipelineDurableExecutor(service).execute(
        job,
        "claim-parent",
        lambda: False,
        lambda _progress: True,
    )

    assert result.error.startswith("分诊超时")
    assert result.retryable is False
    assert journey.state.stage == "triaging"
    assert journey.state.percent < 100
    assert "后台子任务状态已保留" in journey.state.detail


def test_inline_timeout_keeps_recoverable_triaging_projection() -> None:
    run = _run(
        "running",
        _chunks([("chunk-00", "succeeded"), ("chunk-01", "pending")]),
    )
    service, journey = _service(_state(), run, _FakeDurableStore(["running"]))

    def _timeout(*_args, **_kwargs):
        raise TriageWaitTimeoutError("分诊超时：子任务长时间未产生新的业务进度")

    service.execute_stages = _timeout

    payload = service._run_inline(
        PROJECT_ID,
        service.get_state(PROJECT_ID),
        actor="medical_manager",
        auto_confirm_triage=True,
    )

    assert payload["mode"] == "inline"
    assert payload["pipeline"]["stage"] == "triaging"
    assert payload["pipeline"]["percent"] < 100
    assert "后台子任务状态已保留" in payload["pipeline"]["detail"]
    assert journey.state.stage == "triaging"


def test_real_worker_timeout_does_not_retry_and_later_reconciles(
    tmp_path,
) -> None:
    run = _run(
        "running",
        _chunks([("chunk-00", "succeeded"), ("chunk-01", "pending")]),
    )
    state = _state()
    state.round1_ai_route = {"provider": "alibaba", "model": "qwen3.8-max-preview"}
    service, journey = _service(state, run, _FakeDurableStore(["running"]))

    def _timeout(*_args, **_kwargs):
        raise TriageWaitTimeoutError("分诊超时：子任务长时间未产生新的业务进度")

    service.execute_stages = _timeout
    store = DurableJobStore(tmp_path / "durable_jobs.sqlite3")
    service.durable_store = store
    worker = DurableJobWorker(
        store,
        poll_interval_seconds=0.01,
        enable_sweeper=False,
    )
    worker.register_executor(ResearchPipelineDurableExecutor(service))
    request = DurableJobCreateRequest(
        project_id=PROJECT_ID,
        job_type="research_pipeline",
        business_key="parent-timeout-real-worker",
        request_hash="fedcba9876543210",
        input_hash="fedcba9876543210",
        payload_json=(
            '{"actor":"medical_manager","auto_confirm_triage":true,'
            '"corpus_analysis_ai_route":'
            '{"provider":"alibaba","model":"qwen3.8-max-preview"}}'
        ),
        created_by="test",
        max_attempts=3,
    )
    job = store.create_or_reuse(request)

    try:
        worker.wake(PROJECT_ID, job.job_id)
        deadline = time.monotonic() + 3.0
        record = store.get(PROJECT_ID, job.job_id)
        while record.status not in {"completed", "failed", "cancelled"}:
            assert time.monotonic() < deadline
            time.sleep(0.01)
            record = store.get(PROJECT_ID, job.job_id)

        assert record.status == "failed"
        assert record.attempt_count == 1
        assert "分诊超时" in record.error_summary
        assert journey.state.stage == "triaging"
        assert journey.state.percent < 100

        run.status = "review_ready"
        run.chunks = _chunks(
            [("chunk-00", "succeeded"), ("chunk-01", "succeeded")]
        )
        recovered = service.status(PROJECT_ID)
        assert recovered["pipeline"]["stage"] == "awaiting_triage_confirm"
        assert recovered["pipeline"]["error_summary"] == ""
    finally:
        worker.shutdown(timeout=1.0)
