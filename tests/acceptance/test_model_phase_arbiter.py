"""Concurrency arbitration counterexamples (red-first, 0928).

The two managed servers are mutually exclusive (one GPU budget).  When
concurrent users hit different phases the arbiter must QUEUE the cross-phase
request (never error, never drop), switch only after the minimum dwell window
(batching queued demand, preventing flip-flop), time out explicitly, and
audit every queue/switch/wait.  Everything here is offline: stub clock, stub
HTTP, zero real models (A16) — reuses the round21 fakes.

r1 cross-phase queues + strict alternation + same-phase concurrency counting
r2 dwell window blocks reverse switch; same-server keeps serving (batching)
r3 queue timeout -> explicit LifecycleRefusal, queue drained, audited
r4 idle release unaffected; release invalidates the arbiter grant
r5 every arbiter audit row carries the full field set
r6 _managed_dispatch routes managed endpoints through the arbiter
r7 gateway queue timeout surfaces as explicit provider error (no silence)
r8 warm (try_warm) respects the arbiter: defers under busy/dwell, no flip
r9 warm_phase module convenience never raises, even with a broken config
r10 OCR endpoint (role-bound remote OCR gateway) is bracketed by arbitration
"""
from __future__ import annotations

import importlib
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.acceptance.test_model_lifecycle_orchestrator import (  # noqa: E402
    MTPLX,
    MTPLX_MODEL,
    OMLX,
    World,
    _audit_lines,
    _base_config,
    _mtplx_up,
    _omlx_up,
    _pidfile,
    _script_mtplx_lifecycle,
    _write_store,
)


class _Resp:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _wait_until(pred, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    pytest.fail("condition not met within timeout")


@pytest.fixture()
def world(tmp_path):
    store = tmp_path / "runtime"
    _write_store(store)
    w = World(tmp_path, _base_config(tmp_path, store))
    yield w
    w.orch_mod.reset_managed_cache(None)


def _arb(world, **cfg_over):
    world.cfg.update(cfg_over)
    return world.orch_mod.PhaseArbiter(
        world.o, clock=world.clock, sleep=world.clock.sleep)


def _full_mtplx_world(world):
    """MTPLX resident + lifecycle-scriptable + restarts on launch, so a
    switch away from it can actually drain and a switch back can restart."""
    _mtplx_up(world.http)
    _pidfile(world.tmp)
    _script_mtplx_lifecycle(world)
    _mtplx_restarts_on_launch(world)


def _mtplx_restarts_on_launch(world):
    """Lifecycle-scriptable MTPLX that comes up as a consequence of launch
    (round21 test_f pattern) — for scenarios where ensure() starts it."""
    real_launch = world.launch

    def _launching(argv, log_path=None):
        world.http.prepend(f"{MTPLX}/health", "GET", 200, {"ok": True})
        world.http.prepend(f"{MTPLX}/v1/chat/completions", "POST", 200,
                           {"model": MTPLX_MODEL,
                            "choices": [{"message": {"role": "assistant",
                                                     "content": "pong"}}]})
        return real_launch(argv, log_path=log_path)

    world.o.launch = _launching


def _veto_8001_connections(world):
    """A stray established TCP connection on 8001 (admin UI / sampler /
    third-party session) — the round25 busy_connections veto source."""
    world.commands.script.insert(0, (
        lambda argv: (argv and argv[0] == "lsof"
                      and "ESTABLISHED" in " ".join(argv)
                      and "iTCP:8001" in " ".join(argv)),
        (0, "python 51634 44u IPv4 "
            "TCP 127.0.0.1:64994->127.0.0.1:8001 (ESTABLISHED)")))


_ALIVE_CMDLINE = ("/opt/MTPLX/runtime-venv/bin/python -m mtplx.server.openai "
                  "--model /opt/models/X --port 8002 --model-id "
                  "mtplx-flash-next-optimized-speed")


def _mtplx_script_restartable(world):
    """Lifecycle-scriptable MTPLX whose ps/lsof/HTTP state stays consistent
    across start/stop cycles — launch marks the process alive, stop marks it
    gone (needed by multi-attempt rollback scenarios)."""
    state = {"up": False}
    real_launch = world.launch

    def _ps(argv, joined):
        return ((0, _ALIVE_CMDLINE) if state["up"] else (1, ""))

    def _listen(argv, joined):
        return ((0, "python 76719 14u IPv4 "
                    "TCP 127.0.0.1:8002 (LISTEN)") if state["up"] else (1, ""))

    def _established(argv, joined):
        return (0, "")

    def _stop(argv, joined):
        if state["up"]:
            state["up"] = False
            world.http.prepend(f"{MTPLX}/health", "GET", 503, {})
        return (0, "", "")

    def _launching(argv, log_path=None):
        state["up"] = True
        world.http.prepend(f"{MTPLX}/health", "GET", 200, {"ok": True})
        world.http.prepend(f"{MTPLX}/v1/chat/completions", "POST", 200,
                           {"model": MTPLX_MODEL,
                            "choices": [{"message": {"role": "assistant",
                                                     "content": "pong"}}]})
        return real_launch(argv, log_path=log_path)

    world.commands.script.insert(0, (
        lambda argv: argv and argv[0] == "ps", _ps))
    world.commands.script.insert(0, (
        lambda argv: (argv and argv[0] == "lsof"
                      and "LISTEN" in " ".join(argv)
                      and "iTCP:8002" in " ".join(argv)), _listen))
    world.commands.script.insert(0, (
        lambda argv: (argv and argv[0] == "lsof"
                      and "ESTABLISHED" in " ".join(argv)
                      and "iTCP:8002" in " ".join(argv)), _established))
    world.commands.script.insert(0, (
        lambda argv: " stop " in f" {' '.join(argv)} ", _stop))
    world.o.launch = _launching
    return state


def _enter(cm):
    return cm.__enter__()


# ------------------------------------------------------------------ r1


def test_r1_cross_phase_queues_and_alternates_never_double(world):
    # huge queue timeout: under a stub clock a queued waiter would otherwise
    # burn the default budget instantly; this scenario releases it manually
    arb = _arb(world, arbitration_queue_timeout_seconds=10 ** 9)
    _omlx_up(world.http)
    _full_mtplx_world(world)
    a = arb.lease("translation", reason="user-a")
    _enter(a)
    snap = arb.snapshot()
    assert snap["current"] == "omlx", snap
    assert snap["users"]["omlx"] == 1, snap

    outcome: dict = {}

    def _b():
        try:
            lease = arb.lease("triage", reason="user-b")
            lease.__enter__()
            outcome["lease"] = lease
            outcome["granted"] = True
        except BaseException as exc:  # surfaced to assertions
            outcome["error"] = exc

    tb = threading.Thread(target=_b, daemon=True)
    tb.start()
    _wait_until(lambda: len(arb.snapshot()["queue"]) == 1)
    assert tb.is_alive(), "cross-phase request must queue, not error or grant"

    # same-phase concurrency counting: user-c joins instantly (①)
    c = arb.lease("translation", reason="user-c")
    _enter(c)
    assert arb.snapshot()["users"]["omlx"] == 2, arb.snapshot()
    c.__exit__(None, None, None)
    a.__exit__(None, None, None)

    # dwell window: the switch must not happen before min dwell elapses
    assert tb.is_alive(), "reverse switch inside dwell window must keep waiting"
    world.clock.advance(601)
    tb.join(5)
    assert outcome.get("granted"), outcome
    assert arb.snapshot()["current"] == "mtplx", arb.snapshot()
    outcome["lease"].__exit__(None, None, None)
    assert arb.snapshot()["users"]["mtplx"] == 0, arb.snapshot()
    # strict alternation: only ever one server granted at a time
    assert arb.snapshot()["queue"] == [], arb.snapshot()


# ------------------------------------------------------------------ r2


def test_r2_dwell_blocks_reverse_same_server_serves(world, monkeypatch):
    # huge queue timeout: the waiter must be released by the scenario, not
    # by burning the budget under the stub clock
    arb = _arb(world, arbitration_queue_timeout_seconds=10 ** 9)
    ensure_calls: list[str] = []

    def _fake_ensure(phase):
        ensure_calls.append(phase)
        return {"status": "ok", "phase": phase}

    monkeypatch.setattr(world.o, "ensure", _fake_ensure)
    with arb.lease("translation", reason="u1"):
        pass
    assert ensure_calls == ["translation"], ensure_calls
    assert arb.snapshot()["current"] == "omlx", arb.snapshot()

    # a same-server user is active while the reverse request arrives
    d = arb.lease("translation", reason="u3")
    _enter(d)

    outcome: dict = {}

    def _b():
        lease = arb.lease("triage", reason="u2")
        lease.__enter__()
        outcome["lease"] = lease
        outcome["granted"] = True

    tb = threading.Thread(target=_b, daemon=True)
    tb.start()
    _wait_until(lambda: len(arb.snapshot()["queue"]) == 1)
    assert tb.is_alive(), "queued reverse request must not flip the grant"

    # same-server (omlx) requests keep being served instantly during the window
    e = arb.lease("translation", reason="u4")
    _enter(e)
    e.__exit__(None, None, None)
    assert tb.is_alive()

    d.__exit__(None, None, None)  # busy clears, but the dwell window holds
    assert tb.is_alive(), "reverse switch must wait out the dwell window"

    world.clock.advance(601)
    tb.join(5)
    assert outcome.get("granted"), outcome
    assert ensure_calls == ["translation", "triage"], ensure_calls
    assert arb.snapshot()["current"] == "mtplx", arb.snapshot()
    outcome["lease"].__exit__(None, None, None)


# ------------------------------------------------------------------ r3


def test_r3_queue_timeout_explicit_error_and_audit(world):
    arb = _arb(world, arbitration_queue_timeout_seconds=30)
    _omlx_up(world.http)
    a = arb.lease("translation", reason="user-a")
    _enter(a)

    outcome: dict = {}

    def _b():
        try:
            arb.lease("triage", reason="user-b").__enter__()
            outcome["granted"] = True
        except BaseException as exc:
            outcome["error"] = exc

    tb = threading.Thread(target=_b, daemon=True)
    tb.start()
    tb.join(5)
    assert "granted" not in outcome, outcome
    err = outcome.get("error")
    assert isinstance(err, world.orch_mod.LifecycleRefusal), outcome
    assert err.reason == "phase_queue_timeout", outcome
    assert arb.snapshot()["queue"] == [], "timed-out entry must leave the queue"
    assert arb.snapshot()["users"]["omlx"] == 1, arb.snapshot()
    a.__exit__(None, None, None)
    assert arb.snapshot()["users"]["omlx"] == 0, arb.snapshot()
    assert any("arbiter/timeout" in ln for ln in _audit_lines(world))


# ------------------------------------------------------------------ r4


def test_r4_idle_release_unaffected_and_grant_invalidated(world):
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _full_mtplx_world(world)

    with arb.managed_lease(f"{OMLX}/v1", reason="u1"):
        pass
    assert arb.snapshot()["current"] == "omlx", arb.snapshot()

    released = world.o.release("translation", reason="drill", force=False)
    assert released["status"] == "ok", released
    assert arb.snapshot()["current"] is None, "release must invalidate the grant"

    # next lease re-ensures from scratch (fresh A18 probe, not a blind fast path)
    probes_before = len(world.http.chat_calls(8001))
    with arb.managed_lease(f"{OMLX}/v1", reason="u2"):
        pass
    assert len(world.http.chat_calls(8001)) > probes_before

    # idle-recycle window still honoured on mtplx (noop, no stop command).
    # The sentinel stamps wall-clock time while the world clock is a stub,
    # so align the stamped request time with the stub clock first.
    with arb.managed_lease(f"{MTPLX}/v1", reason="u3"):
        pass
    key = world.orch_mod._key(MTPLX)
    world.orch_mod._sentinel_state[key]["last_request_ts"] = \
        world.clock.t - 10
    world.commands.calls.clear()  # only post-noop commands matter here
    noop = world.o.release("triage", reason="drill", force=False)
    assert noop["status"] == "noop", noop
    assert noop["reason"] == "idle_window_open", noop
    assert not world.commands.ran("stop --port 8002"), world.commands.calls


# ------------------------------------------------------------------ r5


def test_r5_arbiter_audit_rows_complete(world):
    # default queue timeout huge; user-b's timeout is per-call below
    arb = _arb(world, arbitration_queue_timeout_seconds=10 ** 9)
    _omlx_up(world.http)
    _full_mtplx_world(world)
    a = arb.lease("translation", reason="user-a")
    _enter(a)
    outcome: dict = {}

    def _b():
        try:
            arb.lease("triage", reason="user-b",
                      timeout=30).__enter__()
            outcome["granted"] = True
        except BaseException as exc:
            outcome["error"] = exc

    tb = threading.Thread(target=_b, daemon=True)
    tb.start()
    tb.join(5)
    assert "error" in outcome, outcome  # user-b timed out: queue + timeout

    # a queued request that survives to a grant covers the wait row
    outcome2: dict = {}

    def _c():
        try:
            lease = arb.lease("triage", reason="user-c")
            lease.__enter__()
            outcome2["lease"] = lease
            outcome2["granted"] = True
        except BaseException as exc:
            outcome2["error"] = exc

    tc = threading.Thread(target=_c, daemon=True)
    tc.start()
    _wait_until(lambda: len(arb.snapshot()["queue"]) == 1)
    a.__exit__(None, None, None)
    world.clock.advance(601)
    tc.join(5)
    assert outcome2.get("granted"), outcome2
    outcome2["lease"].__exit__(None, None, None)

    arb_lines = [ln for ln in _audit_lines(world) if "arbiter/" in ln]
    assert arb_lines, "queue/switch/wait/timeout must all leave audit rows"
    for ln in arb_lines:
        for field in ("动作=", "目标=", "原因=", "结果="):
            assert field in ln, (field, ln)
    joined = "\n".join(arb_lines)
    for tag in ("arbiter/switch", "arbiter/queue", "arbiter/wait",
                "arbiter/timeout"):
        assert tag in joined, (tag, joined)


# ------------------------------------------------------------------ r6


def test_r6_managed_dispatch_routes_through_arbiter(world, monkeypatch):
    gw = importlib.import_module("services.api.app.ai_gateway")
    arb = _arb(world)
    world.orch_mod.set_arbiter(arb)
    _mtplx_up(world.http)
    try:
        observed: dict = {}

        def fake_urlopen(req, timeout=None):
            observed["users"] = arb.snapshot()["users"].get("mtplx", 0)
            observed["inflight"] = world.orch_mod.sentinel_snapshot(
                f"{MTPLX}/v1")["inflight"]
            return _Resp({"model": "m", "choices": [
                {"message": {"role": "assistant", "content": "{\"ok\": true}"}}]})

        monkeypatch.setattr(gw.urllib.request, "urlopen", fake_urlopen)
        provider = gw.OpenAICompatibleAiProvider(
            base_url=f"{MTPLX}/v1", api_key="k", model_name="m", max_attempts=1)
        envelope = gw.AiPromptEnvelope(
            task_id="t", task_type=gw.AiTaskType.MEDICAL_WRITING_REVISION,
            prompt_version="v1", system_prompt="s", payload={"x": 1})
        parsed = provider.run(envelope)
        assert parsed == {"ok": True}, parsed
        # RED assertion: the dispatch must be arbitrated AND sentinel-counted
        assert observed == {"users": 1, "inflight": 1}, observed
        snap = arb.snapshot()
        assert snap["users"]["mtplx"] == 0, snap
        assert world.orch_mod.sentinel_snapshot(f"{MTPLX}/v1")["inflight"] == 0
    finally:
        world.orch_mod.set_arbiter(None)


# ------------------------------------------------------------------ r7


def test_r7_gateway_queue_timeout_surfaces_explicit_error(world, monkeypatch):
    gw = importlib.import_module("services.api.app.ai_gateway")
    arb = _arb(world, arbitration_queue_timeout_seconds=5)
    world.orch_mod.set_arbiter(arb)
    _omlx_up(world.http)
    try:
        monkeypatch.setattr(
            gw.urllib.request, "urlopen",
            lambda req, timeout=None: pytest.fail("must not reach the server"))
        provider = gw.OpenAICompatibleAiProvider(
            base_url=f"{MTPLX}/v1", api_key="k", model_name="m", max_attempts=1)
        envelope = gw.AiPromptEnvelope(
            task_id="t", task_type=gw.AiTaskType.MEDICAL_WRITING_REVISION,
            prompt_version="v1", system_prompt="s", payload={"x": 1})
        hold = arb.lease("translation", reason="holder")
        _enter(hold)
        try:
            with pytest.raises(gw.AiProviderRuntimeError) as excinfo:
                provider.run(envelope)
            code = (getattr(excinfo.value, "diagnostics", {}) or {}).get(
                "failure_code")
            assert code == "phase_queue_timeout", code
        finally:
            hold.__exit__(None, None, None)
    finally:
        world.orch_mod.set_arbiter(None)


# ------------------------------------------------------------------ r8


def test_r8_warm_respects_arbiter(world):
    arb = _arb(world)
    _omlx_up(world.http)
    # idle + no dwell pending -> warm runs ensure (same cost as round21)
    first = arb.try_warm("translation")
    assert first["status"] == "ok", first
    probes = len(world.http.chat_calls(8001))
    second = arb.try_warm("translation")
    assert second["status"] == "ok", second
    assert len(world.http.chat_calls(8001)) > probes, "same-server warm probes"

    # busy sibling user -> warm must defer, never flip the server
    hold = arb.lease("translation", reason="holder")
    _enter(hold)
    try:
        deferred = arb.try_warm("triage")
        assert deferred["status"] == "deferred", deferred
    finally:
        hold.__exit__(None, None, None)

    # dwell pending after a switch -> reverse warm defers even when idle
    _mtplx_up(world.http)
    with arb.lease("triage", reason="switcher"):
        pass
    assert arb.snapshot()["current"] == "mtplx", arb.snapshot()
    omlx_probes = len(world.http.chat_calls(8001))
    reverse = arb.try_warm("translation")
    assert reverse["status"] == "deferred", reverse
    assert len(world.http.chat_calls(8001)) == omlx_probes


# ------------------------------------------------------------------ r9


def test_r9_warm_phase_never_raises_even_with_broken_config(tmp_path):
    orch_mod = importlib.import_module("services.api.app."
                                       "model_lifecycle_orchestrator")
    orch_mod.reset_managed_cache(None)
    cfg = _base_config(tmp_path, tmp_path / "nowhere")
    cfg["runtime_store_dir"] = str(tmp_path / "nowhere")
    orch = orch_mod.ModelLifecycleOrchestrator(config=cfg)
    arb = orch_mod.PhaseArbiter(orch, clock=lambda: 1000.0, sleep=lambda s: None)
    orch_mod.set_arbiter(arb)
    try:
        result = orch_mod.warm_phase("triage")
        assert result["status"] == "refused", result
        assert result["reason"] == "runtime_store_missing", result
    finally:
        orch_mod.set_arbiter(None)


# ------------------------------------------------------------------ r10


def test_r10_ocr_endpoint_bracketed_by_arbitration(world, monkeypatch):
    main_mod = importlib.import_module("services.api.app.main")
    from services.api.app.chapter_translation_pipeline import (
        CompositePipelineUnavailableError,
    )
    from services.api.app.ocr_gateway import OcrRequest

    arb = _arb(world, arbitration_queue_timeout_seconds=5)
    world.orch_mod.set_arbiter(arb)
    _omlx_up(world.http)
    try:
        gateway = main_mod._RoleBoundRemoteOcrGateway(
            base_url=f"{OMLX}/v1", model="ocr-model", api_key="k",
            timeout_seconds=5, use_omlx_gate=False)
        request = OcrRequest(image_bytes=b"\x89PNG\r\n\x1a\n",
                             image_suffix=".png")
        observed: dict = {}

        def fake_urlopen(req, timeout=None):
            observed["users"] = arb.snapshot()["users"].get("omlx", 0)
            observed["inflight"] = world.orch_mod.sentinel_snapshot(
                f"{OMLX}/v1")["inflight"]
            return _Resp({"model": "ocr-model", "choices": [
                {"message": {"role": "assistant", "content": "OCR TEXT"}}]})

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        # RED assertion: OCR against the managed translation server must be
        # arbitrated and sentinel-counted (bypass closed), not a bare urlopen.
        result = gateway.run(request)
        assert result.text == "OCR TEXT", result
        assert observed == {"users": 1, "inflight": 1}, observed
        assert arb.snapshot()["users"].get("omlx", 0) == 0, arb.snapshot()

        # cross-phase: after mtplx takes the grant (inside the dwell window),
        # OCR must queue and time out explicitly instead of hitting an
        # unloaded server.
        world.clock.advance(601)
        _mtplx_up(world.http)
        hold = arb.lease("triage", reason="mtplx-holder")
        _enter(hold)
        try:
            with pytest.raises(CompositePipelineUnavailableError) as excinfo:
                gateway.run(request)
            context = excinfo.value.__context__
            assert context is not None, excinfo.value
            assert "queue_timeout" in repr(context), (excinfo.value, context)
            assert observed.get("users") == 1, observed  # never reached urlopen again
        finally:
            hold.__exit__(None, None, None)
    finally:
        world.orch_mod.set_arbiter(None)


# ------------------------------------------------- r11 (round25 P0-A)


def test_r11_vetoed_switch_rolls_back_the_server_it_started(world):
    """round25 09:47:25: ensure() launched MTPLX, then the exclusion drain of
    oMLX was vetoed — the launched server stayed resident (co-residency).
    The switch must roll back: what ensure() started, ensure() stops."""
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _mtplx_script_restartable(world)
    # real in-flight gateway work on oMLX vetoes the drain (busy_inflight)
    world.orch_mod.gateway_dispatch_begin(f"{OMLX}/v1")
    try:
        with pytest.raises(world.orch_mod.LifecycleRefusal) as excinfo:
            arb.lease("triage", reason="queued-user").__enter__()
        assert excinfo.value.reason == "busy_inflight", excinfo.value
        # RED (round25 P0-A): the launched MTPLX must be stopped again
        assert world.commands.ran("stop --port 8002"), world.commands.calls
        assert arb.snapshot()["current"] is None, arb.snapshot()
    finally:
        world.orch_mod.gateway_dispatch_end(f"{OMLX}/v1")
    # single-load restored: translation serves again immediately
    with arb.lease("translation", reason="recover"):
        pass
    assert arb.snapshot()["current"] == "omlx", arb.snapshot()


# ------------------------------------------------- r12 (round25 P1-D)


def test_r12_failed_switch_resets_the_dwell_window(world, monkeypatch):
    """round25 P1-D (code inference): a failed switch only cleared `current`
    but kept `_switched_at`, freezing BOTH phases until the dwell window
    ran out (~10 min). A failed switch never took effect, so the dwell gate
    must reset with it."""
    arb = _arb(world, arbitration_queue_timeout_seconds=10 ** 9)
    ensure_calls: list[str] = []

    def _fake_ensure(phase):
        ensure_calls.append(phase)
        if phase == "triage":
            return {"status": "refused", "reason": "busy_inflight",
                    "detail": "omlx has in-flight work"}
        return {"status": "ok", "phase": phase}

    monkeypatch.setattr(world.o, "ensure", _fake_ensure)
    with arb.lease("translation", reason="u1"):
        pass
    world.clock.advance(601)
    with pytest.raises(world.orch_mod.LifecycleRefusal) as excinfo:
        arb.lease("triage", reason="queued-user").__enter__()
    assert excinfo.value.reason == "busy_inflight", excinfo.value
    snap = arb.snapshot()
    assert snap["current"] is None, snap
    # RED (round25 P1-D): the failed switch must not keep the dwell gate shut
    assert snap["switched_at"] is None, snap
    clock_before = world.clock.t
    with arb.lease("translation", reason="recover"):
        pass
    assert world.clock.t - clock_before < 10, \
        "re-grant after a failed switch must not burn the dwell window"
    assert ensure_calls[-1] == "translation", ensure_calls


# ------------------------------------------------- r13 (round25 P1-C)


def test_r13_idle_stray_connection_no_longer_vetoes_when_activity_idle(world):
    """round25 P1-C: oMLX reports its own activity; when the activity
    endpoint is readable and shows zero active/waiting work, a stray idle
    TCP connection (admin UI, MarkItDown, sampler) must not veto the
    switch. Real work still vetoes (r11's sentinel path)."""
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _script_mtplx_lifecycle(world)
    _mtplx_restarts_on_launch(world)
    _veto_8001_connections(world)
    with arb.lease("triage", reason="queued-user") as grant:
        assert grant["server"] == "mtplx"
    assert arb.snapshot()["current"] == "mtplx", arb.snapshot()
    # oMLX was properly drained (unload issued), never co-resident
    unloads = [c for c in world.http.calls
               if c[0] == "POST" and "/unload" in c[1]]
    assert unloads, world.http.calls


# ------------------------------------------------- r14 (round25 P1-C)


def test_r14_transient_connection_clears_within_the_retry_window(world):
    """Servers without an activity endpoint (MTPLX) keep the connection
    veto, but a one-shot refusal gives no transient a chance to clear:
    ensure-side drains retry within a bounded window."""
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _full_mtplx_world(world)
    polls = {"established_8002": 0}

    def _established(argv, joined):
        polls["established_8002"] += 1
        if polls["established_8002"] == 1:
            return (0, "python 9219 15u IPv4 "
                       "TCP 127.0.0.1:8002->127.0.0.1:53671 (ESTABLISHED)")
        return (0, "")

    world.commands.script.insert(0, (
        lambda argv: (argv and argv[0] == "lsof"
                      and "ESTABLISHED" in " ".join(argv)
                      and "iTCP:8002" in " ".join(argv)),
        _established))
    with arb.lease("translation", reason="recover"):
        pass
    assert arb.snapshot()["current"] == "omlx", arb.snapshot()
    assert polls["established_8002"] >= 2, polls
    assert world.commands.ran("stop --port 8002"), world.commands.calls


def test_r14b_persistent_connection_still_refuses_after_bounded_retries(world):
    """The retry window is bounded: a persistent veto still refuses (a load
    must never evict a busy server), after exactly the configured number
    of attempts."""
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _full_mtplx_world(world)
    polls = {"established_8002": 0}

    def _established(argv, joined):
        polls["established_8002"] += 1
        return (0, "python 9219 15u IPv4 "
                   "TCP 127.0.0.1:8002->127.0.0.1:53671 (ESTABLISHED)")

    world.commands.script.insert(0, (
        lambda argv: (argv and argv[0] == "lsof"
                      and "ESTABLISHED" in " ".join(argv)
                      and "iTCP:8002" in " ".join(argv)),
        _established))
    with pytest.raises(world.orch_mod.LifecycleRefusal) as excinfo:
        arb.lease("translation", reason="recover").__enter__()
    assert excinfo.value.reason == "busy_connections", excinfo.value
    # bounded composition: drain re-checks (3) x switch retries (3, AGG25
    # P1-7) — still bounded, never an endless retry loop
    assert polls["established_8002"] == 9, polls
    assert "switch retried 2x" in str(excinfo.value.detail), excinfo.value
    assert not world.commands.ran("stop --port 8002"), world.commands.calls
    assert arb.snapshot()["current"] is None, arb.snapshot()


# ------------------------------------------------- r15 (AGG25 P1-7)


def test_r15_switch_failure_requeues_head_and_retries_to_success(
        world, monkeypatch):
    """AGG25 P1-7: a queued user whose switch fails once must be retried
    within the timeout budget (keeping its FIFO position), not get a bare
    502 after waiting ten minutes."""
    arb = _arb(world, arbitration_queue_timeout_seconds=10 ** 9)
    ensure_calls: list[str] = []

    def _fake_ensure(phase):
        ensure_calls.append(phase)
        if len(ensure_calls) == 2:  # first triage switch attempt fails
            return {"status": "refused", "reason": "busy_inflight",
                    "detail": "omlx has in-flight work"}
        return {"status": "ok", "phase": phase}

    monkeypatch.setattr(world.o, "ensure", _fake_ensure)
    with arb.lease("translation", reason="u1"):
        pass
    world.clock.advance(601)
    with arb.lease("triage", reason="queued-user"):
        pass
    assert ensure_calls == ["translation", "triage", "triage"], ensure_calls
    assert arb.snapshot()["current"] == "mtplx", arb.snapshot()
    joined = "\n".join(_audit_lines(world))
    assert "arbiter/retry" in joined, joined


def test_r15b_retry_cap_exhausted_raises_explicit_switch_error(
        world, monkeypatch):
    """With the retry cap exhausted the user gets the explicit switch
    refusal (never a silent drop), after exactly the configured attempts."""
    arb = _arb(world, arbitration_queue_timeout_seconds=10 ** 9,
               arbitration_switch_retry_attempts=2)
    ensure_calls: list[str] = []

    def _fake_ensure(phase):
        ensure_calls.append(phase)
        if phase == "triage":
            return {"status": "refused", "reason": "busy_inflight",
                    "detail": "omlx has in-flight work"}
        return {"status": "ok", "phase": phase}

    monkeypatch.setattr(world.o, "ensure", _fake_ensure)
    with arb.lease("translation", reason="u1"):
        pass
    world.clock.advance(601)
    with pytest.raises(world.orch_mod.LifecycleRefusal) as excinfo:
        arb.lease("triage", reason="queued-user").__enter__()
    assert excinfo.value.reason == "busy_inflight", excinfo.value
    assert ensure_calls == ["translation", "triage", "triage"], ensure_calls
    assert arb.snapshot()["current"] is None, arb.snapshot()
    joined = "\n".join(_audit_lines(world))
    assert "arbiter/retry" in joined, joined


def test_r15c_retry_wait_respects_queue_timeout(world, monkeypatch):
    """If the requeued wait itself outlives the queue budget, the explicit
    phase_queue_timeout surfaces (never a silent hang)."""
    arb = _arb(world, arbitration_queue_timeout_seconds=5,
               arbitration_switch_retry_attempts=5)
    ensure_calls: list[str] = []
    holders: list = []

    def _fake_ensure(phase):
        ensure_calls.append(phase)
        if phase == "triage":
            if len([c for c in ensure_calls if c == "triage"]) == 1:
                # while the failed switch retries, a translation user takes
                # the grant back — the requeued wait must burn the budget
                holder = arb.lease("translation", reason="late-holder")
                holder.__enter__()
                holders.append(holder)
            return {"status": "refused", "reason": "busy_inflight",
                    "detail": "omlx has in-flight work"}
        return {"status": "ok", "phase": phase}

    monkeypatch.setattr(world.o, "ensure", _fake_ensure)
    with arb.lease("translation", reason="u1"):
        pass
    world.clock.advance(601)
    outcome: dict = {}

    def _victim():
        try:
            arb.lease("triage", reason="queued-user").__enter__()
            outcome["granted"] = True
        except BaseException as exc:
            outcome["error"] = exc

    tv = threading.Thread(target=_victim, daemon=True)
    tv.start()
    tv.join(5)
    assert "granted" not in outcome, outcome
    err = outcome.get("error")
    assert isinstance(err, world.orch_mod.LifecycleRefusal), outcome
    assert err.reason == "phase_queue_timeout", outcome
    for holder in holders:
        holder.__exit__(None, None, None)


def test_r15d_lifecycle_status_route_exposes_arbiter(world):
    """AGG25 P1-7: the arbiter queue position must be observable so the UI
    can tell a queued user where they stand."""
    from fastapi.testclient import TestClient
    arb = _arb(world)
    _omlx_up(world.http)
    hold = arb.lease("translation", reason="holder")
    _enter(hold)
    try:
        # the lease holder's orchestrator reports the live arbiter state
        status = world.o.status()
        assert status["arbiter"]["current"] == "omlx", status
        assert status["arbiter"]["queue"] == [], status
        world.orch_mod.set_arbiter(arb)
        try:
            main_mod = importlib.import_module("services.api.app.main")
            with TestClient(main_mod.app) as client:
                resp = client.get("/api/model-lifecycle/status")
                assert resp.status_code == 200, resp.text
                payload = resp.json()
                assert "arbiter" in payload, payload
                assert set(payload["servers"]) == {"omlx", "mtplx"}, payload
        finally:
            world.orch_mod.set_arbiter(None)
    finally:
        hold.__exit__(None, None, None)


# ------------------------------------------------- r16 (AGG25 P1-8)


def _mtplx_flight_world(world, active: int):
    """MTPLX resident with a /v1/mtplx/flight activity endpoint wired in."""
    world.cfg["servers"]["mtplx"]["activity_path"] = "/v1/mtplx/flight"
    _full_mtplx_world(world)
    world.http.prepend(f"{MTPLX}/v1/mtplx/flight", "GET", 200, {
        "active": [{"rid": f"r{i}"} for i in range(active)],
        "recent": [],
    })


def test_r16_mtplx_flight_activity_vetoes_when_busy(world):
    """AGG25 P1-8: MTPLX's flight endpoint is an authoritative activity
    signal — real in-flight work vetoes the drain without consulting
    established-connection counts."""
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _mtplx_flight_world(world, active=2)
    established = {"n": 0}
    world.commands.script.insert(0, (
        lambda argv: (argv and argv[0] == "lsof"
                      and "ESTABLISHED" in " ".join(argv)),
        lambda argv, joined: established.__setitem__(
            "n", established["n"] + 1) or (0, "")))
    with pytest.raises(world.orch_mod.LifecycleRefusal) as excinfo:
        arb.lease("translation", reason="recover").__enter__()
    assert excinfo.value.reason == "busy_activity", excinfo.value
    assert established["n"] == 0, established  # connection veto not consulted


def test_r16b_mtplx_flight_idle_connections_no_longer_veto(world):
    """Idle keep-alive connections on 8002 no longer veto the switch when
    the flight endpoint reports zero in-flight requests."""
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _mtplx_flight_world(world, active=0)
    world.commands.script.insert(0, (
        lambda argv: (argv and argv[0] == "lsof"
                      and "ESTABLISHED" in " ".join(argv)
                      and "iTCP:8002" in " ".join(argv)),
        (0, "python 9219 15u IPv4 "
            "TCP 127.0.0.1:8002->127.0.0.1:53671 (ESTABLISHED)")))
    with arb.lease("translation", reason="recover"):
        pass
    assert arb.snapshot()["current"] == "omlx", arb.snapshot()
    assert world.commands.ran("stop --port 8002"), world.commands.calls


def test_r16c_final_recheck_rides_out_a_transient_blip(world):
    """The TOCTOU re-check right before the irreversible step reuses the
    bounded retry window: an activity blip between the checks and the
    unload must not veto the whole switch (oMLX activity is authoritative,
    so the blip rides the activity signal)."""
    arb = _arb(world)
    _omlx_up(world.http, translation_loaded=True)
    _full_mtplx_world(world)
    reads = {"activity": 0}

    def _flappy_activity(url):
        reads["activity"] += 1
        active = 1 if reads["activity"] % 2 == 1 else 0
        return (200, {"total_active_requests": active,
                      "total_waiting_requests": 0})

    world.http.routes.insert(0, (
        lambda url, m: ("admin/api/activity" in url and m == "GET"),
        _flappy_activity))
    with arb.lease("triage", reason="queued-user"):
        pass
    assert arb.snapshot()["current"] == "mtplx", arb.snapshot()
    # ensure-side check + TOCTOU re-check both rode out one busy blip each
    assert reads["activity"] >= 4, reads
    unloads = [c for c in world.http.calls
               if c[0] == "POST" and "/unload" in c[1]]
    assert unloads, world.http.calls
