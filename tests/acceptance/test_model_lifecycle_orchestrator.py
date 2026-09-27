"""Round21 lifecycle orchestrator counterexamples (red-first, 0927).

Medical-writing local model server lifecycle automation for exactly two
managed servers: oMLX (127.0.0.1:8001, translation) and MTPLX
(127.0.0.1:8002, triage/design).  Everything here is offline: urllib and
subprocess are injected fakes, the runtime store / config / pidfile / audit
log live in pytest tmp dirs.  Zero real models, zero network (A16).

Scenario letters follow the approved round21 plan:
a identity refuse, b idempotent ensure, c probe-load + A18, d mutual
exclusion with drain + release-confirm, e busy refuse, f offline start via
configured absolute command, g unknown phase, h audit fields, i config
fail-closed (missing / probe tokens > 8), i2 memory-guard precheck, j A18
regression, k binding drift (production-shaped store), l medical-monitoring
protected binding, m drain protocol + sentinel counters, n release-confirm
failure fail-closed, o scheduler old probe signature still valid, p frozen
scheduler constants, q pid adoption.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ORCH = "services.api.app.model_lifecycle_orchestrator"

OMLX = "http://127.0.0.1:8001"
MTPLX = "http://127.0.0.1:8002"
TRANSLATION_MODEL = "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"
MTPLX_MODEL = "mtplx-flash-next-optimized-speed"


def _orch():
    return importlib.import_module(ORCH)


# --------------------------------------------------------------------- fakes


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def advance(self, seconds: float) -> None:
        self.t += seconds


class FakeHTTP:
    """Scriptable (status, body) per (method, url); records every call."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.routes: list[tuple[object, object]] = []  # (pred(url, method), result)
        self.default = (503, {})

    def on(self, pred, result):
        self.routes.append((pred, result))
        return self

    def on_url(self, substr, method, status, body):
        return self.on(lambda url, m, s=substr, mm=method: s in url and m == mm,
                       (status, body))

    def prepend(self, substr, method, status, body):
        """Highest-priority route (used to override earlier fixtures)."""
        self.routes.insert(0, (
            lambda url, m, s=substr, mm=method: s in url and m == mm,
            (status, body)))

    def __call__(self, method, url, payload=None, timeout=None):
        self.calls.append((method, url, payload))
        for pred, result in self.routes:
            hit = pred(url, method)
            if hit:
                return result(url) if callable(result) else result
        return self.default

    def chat_calls(self, port):
        return [c for c in self.calls
                if c[0] == "POST" and f":{port}/v1/chat/completions" in c[1]]


class FakeCommands:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.script: list[tuple[object, object]] = []

    def on(self, pred, result):
        self.script.append((pred, result))

    def on_first_token(self, token, result):
        return self.on(lambda argv, t=token: argv and argv[0] == t, result)

    def __call__(self, argv, timeout=None):
        self.calls.append(list(argv))
        joined = " ".join(argv)
        for pred, result in self.script:
            hit = pred(argv)
            if hit:
                value = (result(argv, joined)
                         if callable(result) and _wants_args(result) else result)
                return self._norm(value)
        return (1, "", "")

    @staticmethod
    def _norm(value):
        # scripts may use (rc, out); the orchestrator unpacks (rc, out, err)
        if isinstance(value, tuple) and len(value) == 2:
            return (value[0], value[1], "")
        return value

    def ran(self, substr):
        return any(substr in " ".join(argv) for argv in self.calls)


def _wants_args(fn):
    import inspect

    try:
        return len(inspect.signature(fn).parameters) >= 1
    except (TypeError, ValueError):
        return False


class FakeLaunch:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, argv, log_path=None):
        self.calls.append(list(argv))
        return 424242  # launcher pid; server pid discovered via lsof fake


# ------------------------------------------------------------------ fixtures


def _write_store(store: Path, *, translation_base: str = f"{OMLX}/v1",
                 medmon_profile_id: str = "medical_monitoring_ai__cms_router",
                 medmon_base: str = "https://cloud.example/v1",
                 medmon_binding_enabled: bool = True):
    store.mkdir(parents=True, exist_ok=True)
    profiles = [
        {"profile_id": "translation_body_local_omlx", "base_url": translation_base,
         "provider": "omlx", "model": TRANSLATION_MODEL, "enabled": True},
        {"profile_id": medmon_profile_id, "base_url": medmon_base,
         "provider": "cms-router", "model": "glm", "enabled": True},
    ]
    (store / "ai_provider_settings.json").write_text(json.dumps({
        "schema_version": 1, "revision": 1, "active_profile_id": "",
        "profiles": profiles,
    }), encoding="utf-8")
    (store / "ai_role_bindings.json").write_text(json.dumps({
        "schema_version": 1, "revision": 1,
        "bindings": {
            "translation_body": {"role_id": "translation_body",
                                 "profile_id": "translation_body_local_omlx",
                                 "enabled": True},
            "medical_monitoring_ai": {"role_id": "medical_monitoring_ai",
                                      "profile_id": medmon_profile_id,
                                      "enabled": medmon_binding_enabled},
        },
    }), encoding="utf-8")


def _base_config(tmp: Path, store: Path, **over) -> dict:
    cfg = {
        "schema_version": 1,
        "probe_max_tokens": 8,
        "release_confirm_timeout_seconds": 10,
        "start_timeout_seconds": 10,
        "poll_interval_seconds": 1,
        "phase_roles": {"translation": ["translation_body"],
                        "triage": ["triage"], "design": ["design"]},
        "protected_roles": ["translation_body", "triage", "design"],
        "runtime_store_dir": str(store),
        "audit_log_path": str(tmp / "actions.log"),
        "state_file_path": str(tmp / "orchestrator_state.json"),
        "servers": {
            "omlx": {
                "endpoint": OMLX, "port": 8001, "phases": ["translation"],
                "managed_model_id": TRANSLATION_MODEL,
                "process_managed": False,
                "admin_models_path": "/admin/api/models",
                "activity_path": "/admin/api/activity",
                "unload_path": "/admin/api/models/{model}/unload",
                "start_command": ["/Applications/oMLX.app/Contents/MacOS/omlx-cli",
                                  "start"],
                "load_memory_precheck": {"estimated_model_bytes": 31250000000,
                                         "factor": 1.1},
            },
            "mtplx": {
                "endpoint": MTPLX, "port": 8002, "phases": ["triage", "design"],
                "managed_model_id": MTPLX_MODEL,
                "process_managed": True,
                "pidfile_path": str(tmp / "mtplx_server.pid"),
                "server_log_path": str(tmp / "mtplx_server.log"),
                "pid_identity_markers": ["runtime-venv", "--port 8002"],
                "start_command": ["/opt/MTPLX/runtime-venv/bin/mtplx", "quickstart",
                                  "--model", "/opt/models/X", "--port", "8002",
                                  "--yes"],
                "stop_command": ["/opt/MTPLX/runtime-venv/bin/mtplx", "stop",
                                 "--port", "8002", "--grace-seconds", "30"],
                "idle_recycle_seconds": 1800,
            },
        },
    }
    for key, value in over.items():
        cfg[key] = value
    return cfg


def _omlx_up(http: FakeHTTP, *, translation_loaded: bool = False,
             memory_max: int = 50_000_000_000) -> dict:
    """Register a healthy oMLX; returns a mutable state dict so a scripted
    unload can flip the admin/models residency (completion confirmation)."""
    state = {"loaded": translation_loaded}
    http.on_url(f"{OMLX}/health", "GET", 200, {"status": "ok"})
    http.on_url(f"{OMLX}/v1/models", "GET", 200,
                {"data": [{"id": TRANSLATION_MODEL}]})
    http.on(lambda url, m: url == f"{OMLX}/admin/api/models" and m == "GET",
            lambda url, s=state: (200, {"models": [
                {"id": TRANSLATION_MODEL, "loaded": s["loaded"],
                 "is_loading": False}]}))
    http.on_url(f"{OMLX}/admin/api/activity", "GET", 200, {
        "active_models": {"models": [], "model_memory_used": 239584576,
                          "model_memory_max": memory_max},
        "total_active_requests": 0, "total_waiting_requests": 0,
    })
    http.on_url(f"{OMLX}/v1/chat/completions", "POST", 200,
                {"model": TRANSLATION_MODEL,
                 "choices": [{"message": {"role": "assistant", "content": "pong"}}]})
    http.on(lambda url, m: m == "POST"
            and url == (f"{OMLX}/admin/api/models/{TRANSLATION_MODEL}/unload"),
            lambda url, s=state: (s.update(loaded=False), (200, {"ok": True}))[1])
    return state


def _mtplx_up(http: FakeHTTP):
    http.on_url(f"{MTPLX}/health", "GET", 200, {"ok": True})
    http.on_url(f"{MTPLX}/v1/models", "GET", 200,
                {"data": [{"id": MTPLX_MODEL}]})
    http.on_url(f"{MTPLX}/v1/chat/completions", "POST", 200,
                {"model": MTPLX_MODEL,
                 "choices": [{"message": {"role": "assistant", "content": "pong"}}]})


def _mtplx_down(http: FakeHTTP):
    http.on_url(f"{MTPLX}/health", "GET", 503, {})


_ALIVE_CMDLINE = ("/opt/MTPLX/runtime-venv/bin/python -m mtplx.server.openai "
                  "--model /opt/models/X --port 8002 --model-id "
                  "mtplx-flash-next-optimized-speed")


def _script_mtplx_lifecycle(world, stop_effective: bool = True) -> dict:
    """Stateful ps/lsof scripts + a stop command that flips the fake world,
    mirroring what a real stop does (process gone, listener gone, health 503)."""
    state = {"up": True}
    world.commands.on_first_token(
        "ps", lambda argv, joined, s=state: (
            (0, _ALIVE_CMDLINE) if s["up"] else (1, "")))
    world.commands.on(
        lambda argv: argv and argv[0] == "lsof" and "LISTEN" in argv,
        lambda argv, joined, s=state: (
            (0, "python 76719 14u IPv4 TCP 127.0.0.1:8002 (LISTEN)")
            if s["up"] else (1, "")))
    world.commands.on(
        lambda argv: argv and argv[0] == "lsof" and "ESTABLISHED" in argv,
        (0, ""))

    def _stop(argv, joined, s=state, effective=stop_effective):
        if effective:
            s["up"] = False
            world.http.routes.insert(
                0, (lambda url, m: ":8002/health" in url and m == "GET",
                    (503, {})))
        return (0, "", "")

    world.commands.on(
        lambda argv: " stop " in f" {' '.join(argv)} ", _stop)
    return state


def _pidfile(tmp: Path, pid: int = 76719):
    (tmp / "mtplx_server.pid").write_text(f"launched_pid={pid}\n", encoding="utf-8")


class World:
    def __init__(self, tmp: Path, cfg: dict):
        self.tmp = tmp
        self.cfg = cfg
        self.http = FakeHTTP()
        self.commands = FakeCommands()
        self.launch = FakeLaunch()
        self.clock = FakeClock()
        self.orch_mod = _orch()
        self.orch_mod.reset_managed_cache(
            {OMLX, MTPLX, f"{OMLX}/v1", f"{MTPLX}/v1"})
        self.o = self.orch_mod.ModelLifecycleOrchestrator(
            config=cfg, http=self.http, commands=self.commands,
            launch=self.launch, clock=self.clock, sleep=self.clock.sleep)

    def teardown(self):
        self.orch_mod.reset_managed_cache(None)


@pytest.fixture()
def world(tmp_path):
    store = tmp_path / "runtime"
    _write_store(store)
    w = World(tmp_path, _base_config(tmp_path, store))
    yield w
    w.teardown()


def _audit_lines(w: World) -> list[str]:
    path = Path(w.cfg["audit_log_path"])
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ------------------------------------------------------------ a: identity


def test_a_pidfile_identity_mismatch_refuses_and_audits(world):
    _mtplx_up(world.http)
    _pidfile(world.tmp, pid=999)
    world.commands.on_first_token("ps", (0, "/bin/other-server --port 9999"))
    result = world.o.ensure("triage")
    assert result["status"] == "refused", result
    assert result["reason"] == "pidfile_identity_mismatch", result
    assert not world.launch.calls, world.launch.calls
    assert not world.commands.ran("stop"), world.commands.calls
    assert any("pidfile_identity_mismatch" in ln for ln in _audit_lines(world))


# --------------------------------------------------------- b: idempotence


def test_b_ensure_idempotent_when_healthy_and_resident(world):
    _mtplx_up(world.http)
    _pidfile(world.tmp)
    world.commands.on_first_token("ps", (0, _ALIVE_CMDLINE))
    first = world.o.ensure("triage")
    assert first["status"] == "ok", first
    commands_before = list(world.commands.calls)
    launch_before = list(world.launch.calls)
    second = world.o.ensure("triage")
    assert second["status"] == "ok", second
    assert second.get("action_taken") in (False, None), second
    # idempotence: no server action the second time (read-only ps allowed)
    for argv in world.commands.calls[len(commands_before):]:
        assert not ("stop" in argv or "start" in argv), argv
    assert world.launch.calls == launch_before
    assert world.http.chat_calls(8002), "A18 probe must verify the served model"


# ------------------------------------------------- c: cold load probe + A18


def test_c_probe_loads_translation_then_a18_passes(world):
    _omlx_up(world.http, translation_loaded=False)
    _mtplx_down(world.http)
    result = world.o.ensure("translation")
    assert result["status"] == "ok", result
    chats = world.http.chat_calls(8001)
    assert chats, "probe-load must be the primary load path"
    payload = chats[0][2]
    assert payload["model"] == TRANSLATION_MODEL, payload
    assert payload["max_tokens"] == 8, payload


# --------------------------------------- d: mutual exclusion drain + release


def test_d_busy_free_other_resident_drains_then_loads(world):
    _omlx_up(world.http, translation_loaded=False)
    _mtplx_up(world.http)
    _pidfile(world.tmp)
    _script_mtplx_lifecycle(world)
    result = world.o.ensure("translation")
    assert result["status"] == "ok", result
    assert world.commands.ran("stop --port 8002"), world.commands.calls
    stop_idx = next(i for i, argv in enumerate(world.commands.calls)
                    if "stop" in argv)
    chats = world.http.chat_calls(8001)
    assert chats, "probe load must happen after the drain"
    assert any("action/stop" in ln or "action/release-done" in ln
               for ln in _audit_lines(world))


def test_d2_release_reports_unload_and_confirm_for_omlx(world):
    _omlx_up(world.http, translation_loaded=True)
    _mtplx_down(world.http)
    result = world.o.release("translation", reason="test_unload")
    assert result["status"] == "ok", result
    unloads = [c for c in world.http.calls
               if c[0] == "POST" and "/unload" in c[1]]
    assert unloads, world.http.calls
    assert any("action/unload" in ln for ln in _audit_lines(world))
    assert any("action/release-done" in ln for ln in _audit_lines(world))


# ------------------------------------------------------------- e: busy refuse


def test_e_inflight_dispatch_refuses_busy(world):
    _omlx_up(world.http, translation_loaded=False)
    _mtplx_up(world.http)
    _pidfile(world.tmp)
    world.orch_mod.gateway_dispatch_begin(f"{MTPLX}/v1")
    try:
        result = world.o.ensure("translation")
        assert result["status"] == "refused", result
        assert result["reason"].startswith("busy"), result
        assert not world.commands.ran("stop --port 8002")
        assert not world.http.chat_calls(8001)
    finally:
        world.orch_mod.gateway_dispatch_end(f"{MTPLX}/v1")


# ------------------------------------------------------- f: offline start


def test_f_offline_uses_configured_absolute_command(world):
    _mtplx_down(world.http)
    real_launch = world.launch

    def launching(argv, log_path=None):
        # the server comes up as a consequence of the launch
        world.http.prepend(f"{MTPLX}/health", "GET", 200, {"ok": True})
        world.http.prepend(f"{MTPLX}/v1/models", "GET", 200,
                           {"data": [{"id": MTPLX_MODEL}]})
        world.http.prepend(f"{MTPLX}/v1/chat/completions", "POST", 200,
                           {"model": MTPLX_MODEL,
                            "choices": [{"message": {"content": "pong"}}]})
        return real_launch(argv, log_path=log_path)

    world.o.launch = launching
    result = world.o.ensure("triage")
    assert result["status"] == "ok", result
    assert world.launch.calls, "offline server must be launched"
    assert world.launch.calls[0] == world.cfg["servers"]["mtplx"]["start_command"]
    joined_calls = " ".join(" ".join(a) for a in world.launch.calls)
    assert "open" not in joined_calls and " -a " not in f" {joined_calls} "
    assert ".local/bin/mtplx" not in joined_calls
    pidfile = (world.tmp / "mtplx_server.pid").read_text(encoding="utf-8")
    assert "launched_pid=424242" in pidfile, pidfile


# ------------------------------------------------------- g: unknown phase


def test_g_unknown_phase_zero_actions(world):
    result = world.o.ensure("mystery-phase")
    assert result["status"] == "refused", result
    assert result["reason"] == "unknown_phase", result
    assert world.http.calls == []
    assert world.commands.calls == []
    assert world.launch.calls == []


# ---------------------------------------------------------- h: audit fields


def test_h_audit_lines_carry_full_fields(world):
    _mtplx_up(world.http)
    _pidfile(world.tmp)
    world.commands.on_first_token("ps", (0, _ALIVE_CMDLINE))
    world.o.ensure("triage")
    world.o.ensure("mystery-phase")
    lines = _audit_lines(world)
    assert lines, "every ensure must leave an audit trail"
    for ln in lines:
        for field in ("动作=", "目标=", "原因=", "结果="):
            assert field in ln, (field, ln)


# ------------------------------------------------------- i: config fail-closed


def test_i_missing_config_refuses(world, tmp_path):
    w = World(tmp_path, _base_config(tmp_path, tmp_path / "runtime"))
    w.cfg["runtime_store_dir"] = str(tmp_path / "nowhere")
    try:
        result = w.o.ensure("triage")
        assert result["status"] == "refused", result
        assert result["reason"] == "runtime_store_missing", result
    finally:
        w.teardown()


def test_i2_probe_tokens_above_eight_refuse(world, tmp_path):
    store = tmp_path / "runtime"
    _write_store(store)
    cfg = _base_config(tmp_path, store, probe_max_tokens=64)
    w = World(tmp_path, cfg)
    try:
        result = w.o.ensure("triage")
        assert result["status"] == "refused", result
        assert result["reason"] == "probe_max_tokens_exceeds_limit", result
        assert w.http.chat_calls(8002) == []
    finally:
        w.teardown()


def test_i3_memory_guard_blocks_omlx_load(world):
    _omlx_up(world.http, translation_loaded=False, memory_max=10_000_000_000)
    _mtplx_down(world.http)
    result = world.o.ensure("translation")
    assert result["status"] == "refused", result
    assert result["reason"] == "memory_guard", result
    assert world.http.chat_calls(8001) == []


# ------------------------------------------------------------- j: A18 reject


def test_j_a18_wrong_model_body_fails_ensure(world):
    _omlx_up(world.http, translation_loaded=False)
    _mtplx_down(world.http)
    world.http.prepend(f"{OMLX}/v1/chat/completions", "POST", 200,
                       {"model": "SOME-OTHER-MODEL",
                        "choices": [{"message": {"content": "pong"}}]})
    result = world.o.ensure("translation")
    assert result["status"] == "failed", result
    assert "a18" in result["reason"], result
    assert not world.launch.calls


# ----------------------------------------------------------- k: binding drift


def test_k_binding_drift_refuses_translation_like_production(world, tmp_path):
    store = tmp_path / "runtime"
    _write_store(store, translation_base="http://127.0.0.1:8000/v1")
    w = World(tmp_path, _base_config(tmp_path, store))
    try:
        _omlx_up(w.http, translation_loaded=False)
        _mtplx_up(w.http)
        result = w.o.ensure("translation")
        assert result["status"] == "refused", result
        assert result["reason"] == "binding_base_url_mismatch", result
        assert w.http.chat_calls(8001) == []
        assert not w.commands.ran("stop --port 8002")
        status = w.o.status()
        assert status["binding_flags"]["translation_body"] == "binding_base_url_mismatch"
    finally:
        w.teardown()


# ------------------------------------------- l: medical monitoring protection


def test_l_enabled_foreign_binding_blocks_release(world, tmp_path):
    store = tmp_path / "runtime"
    _write_store(store, medmon_profile_id="medical_monitoring_ai__mtplx_local",
                 medmon_base=f"{MTPLX}/v1")
    w = World(tmp_path, _base_config(tmp_path, store))
    try:
        _mtplx_up(w.http)
        _pidfile(w.tmp)
        w.commands.on_first_token("ps", (0, "/opt/MTPLX/runtime-venv/bin/python --port 8002"))
        result = w.o.release("triage", reason="drill")
        assert result["status"] == "refused", result
        assert result["reason"] == "protected_binding_active", result
        assert not w.commands.ran("stop --port 8002")
    finally:
        w.teardown()


def test_l2_cloud_bound_medmon_does_not_block_release(world):
    _mtplx_up(world.http)
    _pidfile(world.tmp)
    _script_mtplx_lifecycle(world)
    result = world.o.release("triage", reason="drill")
    assert result["status"] == "ok", result
    assert world.commands.ran("stop --port 8002")


# --------------------------------------------------------- m: drain protocol


def test_m_draining_refuses_new_dispatch_and_release_waits_for_zero(world):
    orch_mod = world.orch_mod
    orch_mod.set_draining(f"{MTPLX}/v1", True)
    try:
        with pytest.raises(orch_mod.LifecycleRefusal) as excinfo:
            orch_mod.gateway_dispatch_begin(f"{MTPLX}/v1")
        assert excinfo.value.reason == "managed_server_draining"

        # release with one in-flight dispatch that clears during the wait
        orch_mod.set_draining(f"{MTPLX}/v1", False)
        _mtplx_up(world.http)
        _pidfile(world.tmp)
        _script_mtplx_lifecycle(world)
        orch_mod.gateway_dispatch_begin(f"{MTPLX}/v1")
        original_sleep = world.clock.sleep

        def sleep_then_release_idle(seconds):
            original_sleep(seconds)
            orch_mod.gateway_dispatch_end(f"{MTPLX}/v1")

        world.o.sleep = sleep_then_release_idle
        result = world.o.release("triage", reason="drill", force=True)
        assert result["status"] == "ok", result
        assert world.commands.ran("stop --port 8002")
        snap = orch_mod.sentinel_snapshot(f"{MTPLX}/v1")
        assert snap["draining"] is False, snap
    finally:
        orch_mod.set_draining(f"{MTPLX}/v1", False)
        orch_mod.reset_managed_cache(None)


def test_m2_sentinel_counts_only_managed_endpoints(world):
    orch_mod = world.orch_mod
    orch_mod.gateway_dispatch_begin(f"{MTPLX}/v1")
    orch_mod.gateway_dispatch_begin("https://cloud.example/v1")
    assert orch_mod.sentinel_snapshot(f"{MTPLX}/v1")["inflight"] == 1
    assert orch_mod.sentinel_snapshot("https://cloud.example/v1")["inflight"] == 0
    orch_mod.gateway_dispatch_end(f"{MTPLX}/v1")
    assert orch_mod.sentinel_snapshot(f"{MTPLX}/v1")["inflight"] == 0


def test_m3_gateway_sentinel_brackets_dispatch_and_refuses_draining(monkeypatch):
    gw = importlib.import_module("services.api.app.ai_gateway")
    orch_mod = _orch()
    orch_mod.reset_managed_cache({f"{MTPLX}/v1"})
    try:

        class _Resp:
            status = 200

            def read(self):
                return json.dumps({
                    "model": "m",
                    "choices": [{"message": {"role": "assistant",
                                             "content": "{\"ok\": true}"}}],
                }).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(gw.urllib.request, "urlopen",
                            lambda req, timeout=None: _Resp())
        provider = gw.OpenAICompatibleAiProvider(
            base_url=f"{MTPLX}/v1", api_key="k", model_name="m", max_attempts=1)
        envelope = gw.AiPromptEnvelope(
            task_id="t", task_type=gw.AiTaskType.MEDICAL_WRITING_REVISION,
            prompt_version="v1", system_prompt="s", payload={"x": 1})
        parsed = provider.run(envelope)
        assert parsed == {"ok": True}, parsed
        assert orch_mod.sentinel_snapshot(f"{MTPLX}/v1")["inflight"] == 0

        orch_mod.set_draining(f"{MTPLX}/v1", True)
        try:
            with pytest.raises(gw.AiProviderRuntimeError) as excinfo:
                provider.run(envelope)
            code = (getattr(excinfo.value, "diagnostics", {}) or {}).get(
                "failure_code")
            assert code == "managed_server_draining", code
        finally:
            orch_mod.set_draining(f"{MTPLX}/v1", False)
    finally:
        orch_mod.reset_managed_cache(None)


# ------------------------------------------- n: release-confirm failure gate


def test_n_release_confirm_failure_fails_closed(world):
    _mtplx_up(world.http)
    _pidfile(world.tmp)
    # stop "runs" but the process and the listener never go away
    _script_mtplx_lifecycle(world, stop_effective=False)
    result = world.o.release("triage", reason="drill")
    assert result["status"] == "failed", result
    assert result["reason"] == "release_confirm_timeout", result
    assert any("release_confirm_timeout" in ln for ln in _audit_lines(world))
    # fail-closed: further lifecycle work on that phase is refused
    after = world.o.ensure("triage")
    assert after["status"] == "refused", after
    assert after["reason"] == "release_unconfirmed", after


# ---------------------------------------------- o: scheduler compatibility


def test_o_scheduler_chat_probe_old_signature(monkeypatch):
    import tests.acceptance._gate_testkit as kit

    mod = kit.load_scheduler_module()

    class _Resp:
        status = 200

        def read(self):
            return json.dumps({
                "model": mod.OMLX_TRANSLATION_MODEL,
                "choices": [{"message": {"content": "pong"}}],
            }).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(mod.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp())
    ok, err = mod._chat_probe(mod.OMLX_BASE, mod.OMLX_TRANSLATION_MODEL)
    assert ok is True and err == "", (ok, err)


# ------------------------------------------------- p: frozen scheduler values


def test_p_scheduler_frozen_constants_unchanged():
    import tests.acceptance._gate_testkit as kit

    mod = kit.load_scheduler_module()
    assert mod.OMLX_BASE == "http://127.0.0.1:8001/v1"
    assert mod.MTPLX_BASE == "http://127.0.0.1:8002/v1"
    assert mod.OMLX_TRANSLATION_MODEL == "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"
    assert mod.MTPLX_MODEL == "mtplx-flash-next-optimized-speed"
    assert mod.PHASE_MODEL_REQUIREMENTS == {
        "translation": ("translation",),
        "triage": ("triage",),
    }


# ----------------------------------------------------------- q: pid adoption


def test_q_adopt_records_verified_identity(world):
    _mtplx_up(world.http)
    _pidfile(world.tmp, pid=76719)
    world.commands.on_first_token("ps", (0, _ALIVE_CMDLINE))
    record = world.o.adopt("mtplx", operator="implementer",
                           evidence="LIVE step0 adoption")
    assert record["adopted"] is True, record
    assert record["checks"]["cmdline_markers_ok"] is True, record
    assert record["checks"]["served_model_id_ok"] is True, record
    state = json.loads((world.tmp / "orchestrator_state.json").read_text())
    assert state["adoption"]["mtplx"]["adopted"] is True
    assert any("state/adoption" in ln for ln in _audit_lines(world))
    # mismatched cmdline refuses adoption
    world.commands.script.clear()
    world.commands.on_first_token("ps", (0, "/bin/other --port 9999"))
    refused = world.o.adopt("mtplx", operator="implementer", evidence="x")
    assert refused["adopted"] is False, refused
    assert refused["reason"] == "pidfile_identity_mismatch", refused
