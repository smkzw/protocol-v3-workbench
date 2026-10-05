"""20261005 串行根治：owner授权接管 + 严格互斥串行（删除20261004e共存旁路）。

实测裁决（runs/.../t17_round27_loop/scheduler_root_fix_20261005/）：
- 双模型"加载时"装得下、"生成时"装不下——MTPLX 生成时懒加载权重，
  dawncr0w 驻留下实测 swap 22GB（0928 同型事故）。共存旁路已删除。
- oMLX balanced 档动态上限不计内核可逐出的文件缓存（27.4GB 可用仍判
  18.9GB 上限）→ memory_guard_tier=aggressive 由编排器对齐（带审计）。

新契约（红先修后）：
- 未纳管的 8002 监听者（用户 MTPLX GUI 服务器）：busy 检查通过（无在途
  调用）且 /v1/models 探针确认 MTPLX 家族且 mtplx_takeover.enabled 时，
  授权接管停机让位（CLI stop 优先、SIGTERM 兜底、绝不 SIGKILL 外来进程、
  停不确认 fail-closed）；三者任一不满足维持原 server_unowned 拒绝。
- 健康的外来 MTPLX 监听者在 mtplx 相被授权复用（owner 指示直接从 GUI
  调用模型），登记 reuse 台账。
- 接管/复用都不写 pidfile（防下一相位 pidfile_identity_mismatch 误拒）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.api.app.model_lifecycle_orchestrator import (
    ModelLifecycleOrchestrator,
)

LIVE_LISTENER_PID = 399999
FOREIGN_CMDLINE = "/opt/homebrew/Cellar/python@3.12/Python mtplx.server.openai --port 8002"
MTPLX_MODELS_BODY = {"models": [
    {"id": "mtplx-flash-next-optimized-speed", "loaded": True}
]}


def _mtplx_server(pidfile: str) -> dict:
    return {
        "endpoint": "http://127.0.0.1:8002",
        "port": 8002,
        "process_managed": True,
        "managed_model_id": "mtplx-flash-next-optimized-speed",
        "pidfile_path": pidfile,
        "pid_identity_markers": ["runtime-venv", "mtplx.server.openai"],
        "stop_command": ["mtplx", "stop", "--port", "8002"],
        "activity_path": "/v1/mtplx/flight",
        "phases": ["design"],
    }


def _omlx_server() -> dict:
    return {
        "endpoint": "http://127.0.0.1:8001",
        "port": 8001,
        "process_managed": False,
        "managed_model_id": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
        "admin_models_path": "/admin/api/models",
        "unload_path": "/admin/api/models/{model}/unload",
        "load_memory_precheck": {
            "estimated_model_bytes": 31250000000,
            "factor": 1.1,
        },
        "memory_guard_tier": "aggressive",
        "phases": ["translation"],
    }


class _Http:
    """状态化HTTP假件：mtplx(8002)=外来GUI服务器；omlx(8001)按需驻留。"""

    def __init__(self, *, mtplx_family=True, omlx_loaded=False,
                 omlx_tier="balanced"):
        self.calls: list[tuple[str, str]] = []
        self.mtplx_family = mtplx_family
        self.mtplx_alive = True
        self.omlx_loaded = omlx_loaded
        self.omlx_tier = omlx_tier
        self.tier_posts: list[dict] = []
        self.unloads: list[str] = []

    def __call__(self, method: str, url: str, payload=None, timeout: float = 30.0):
        self.calls.append((method, url))
        if ":8002" in url:
            if not self.mtplx_alive:
                return 503, {"detail": "down"}
            if "/v1/models" in url:
                if self.mtplx_family:
                    return 200, {"models": [
                        {"id": "mtplx-flash-next-optimized-speed"}]}
                return 200, {"models": [{"id": "some-other-server"}]}
            if "/health" in url:
                return 200, {"startup": {"pid": LIVE_LISTENER_PID}}
            if "/v1/mtplx/flight" in url:
                return 200, {"active": []}
            if "/v1/chat/completions" in url:
                return 200, {
                    "model": "mtplx-flash-next-optimized-speed",
                    "choices": [{"message": {"content": "pong"}}],
                }
            return 200, MTPLX_MODELS_BODY
        # 8001 (omlx)
        if "/admin/api/global-settings" in url:
            if method == "POST":
                self.tier_posts.append(dict(payload or {}))
                self.omlx_tier = (payload or {}).get(
                    "memory_guard_tier", self.omlx_tier)
                return 200, {"success": True}
            return 200, {"memory": {"memory_guard_tier": self.omlx_tier}}
        if "/admin/api/activity" in url:
            return 200, {"model_memory_max": 100 * 1024 ** 3}
        if "/admin/api/models" in url and method == "POST" and "/unload" in url:
            self.unloads.append(url)
            self.omlx_loaded = False
            return 200, {"status": "ok"}
        if "/admin/api/models" in url:
            return 200, {"models": [
                {"id": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
                 "loaded": self.omplx_loaded if False else self.omlx_loaded},
            ]}
        if "/v1/chat/completions" in url:
            return 200, {
                "model": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
                "choices": [{"message": {"content": "pong"}}],
            }
        if "/health" in url:
            return 200, {}
        return 200, {}


class _Commands:
    """状态化命令假件：CLI stop 后端口让位；kill 后亦让位（可禁用）。"""

    def __init__(self, *, cli_stop_effective=True, sigterm_effective=True):
        self.stop_calls: list[list[str]] = []
        self.kill_signals: list[tuple[int, int]] = []
        self.stopped = False
        self.cli_stop_effective = cli_stop_effective
        self.sigterm_effective = sigterm_effective
        self.http: _Http | None = None

    def _server_down(self) -> None:
        self.stopped = True
        if self.http is not None:
            self.http.mtplx_alive = False

    def __call__(self, argv, timeout=None):
        if argv and argv[0] == "lsof" and "-sTCP:LISTEN" in argv:
            if self.stopped:
                return 0, "", ""
            return 0, (f"COMMAND PID USER\nPython {LIVE_LISTENER_PID} u\n",
                       "")[0], ""
        if argv and argv[0] == "lsof":
            return 0, "", ""
        if argv and argv[0] == "ps":
            return 0, FOREIGN_CMDLINE, ""
        if argv[:2] == ["mtplx", "stop"]:
            self.stop_calls.append(list(argv))
            if self.cli_stop_effective:
                self._server_down()
            return 0, "", ""
        return 0, "", ""

    def kill(self, pid: int, sig: int) -> None:
        self.kill_signals.append((pid, sig))
        if sig == 9:
            return
        if self.sigterm_effective:
            self._server_down()


class SerialTakeoverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.pidfile = str(root / "mtplx_server.pid")
        # 陈账pidfile：指向死pid1，但ps返回外来cmdline→identity mismatch路径
        Path(self.pidfile).write_text("launched_pid=1\n", encoding="utf-8")
        self.state_path = str(root / "orchestrator_state.json")
        self.audit_path = str(root / "actions.log")
        self.store_dir = root / "store"
        self.store_dir.mkdir()
        (self.store_dir / "ai_provider_settings.json").write_text(
            json.dumps({"profiles": [
                {"profile_id": "p_omlx",
                 "base_url": "http://127.0.0.1:8001/v1", "enabled": True},
                {"profile_id": "p_mtplx",
                 "base_url": "http://127.0.0.1:8002/v1", "enabled": True},
            ]}, ensure_ascii=False), encoding="utf-8")
        (self.store_dir / "ai_role_bindings.json").write_text(
            json.dumps({"bindings": {
                "translation_body": {"enabled": True,
                                     "profile_id": "p_omlx"},
                "design": {"enabled": True, "profile_id": "p_mtplx"},
            }}, ensure_ascii=False), encoding="utf-8")
        self._tick = [0.0]
        self.http: _Http | None = None
        self.commands: _Commands | None = None

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _orch(self, *, takeover_enabled=True, http: _Http | None = None,
              commands: _Commands | None = None) -> ModelLifecycleOrchestrator:
        self.http = http or _Http()
        self.commands = commands or _Commands()
        self.commands.http = self.http
        config = {
            "probe_max_tokens": 8,
            "poll_interval_seconds": 0.01,
            "release_confirm_timeout_seconds": 0.2,
            "state_file_path": self.state_path,
            "audit_log_path": self.audit_path,
            "runtime_store_dir": str(self.store_dir),
            "servers": {
                "omlx": _omlx_server(),
                "mtplx": _mtplx_server(self.pidfile),
            },
            "phase_roles": {
                "translation": ["translation_body"],
                "design": ["design"],
            },
            "protected_roles": [],
        }
        if takeover_enabled:
            config["mtplx_takeover"] = {
                "enabled": True, "identity_probe": "/v1/models"}
        return ModelLifecycleOrchestrator(
            config=config,
            http=self.http,
            commands=self.commands,
            kill=self.commands.kill,
            clock=lambda: (self._tick.__setitem__(0, self._tick[0] + 0.05)
                           or self._tick[0]),
            sleep=lambda _s: None,
        )

    def _state(self) -> dict:
        path = Path(self.state_path)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _audit_text(self) -> str:
        path = Path(self.audit_path)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # ------------------------------------------------------------- takeover

    def test_translation_takes_over_idle_foreign_mtplx_listener(self):
        orch = self._orch()
        result = orch.ensure("translation")
        self.assertEqual("ok", result.get("status"), result)
        self.assertEqual(1, len(self.commands.stop_calls),
                         "必须经CLI stop接管让位")
        self.assertEqual([], self.commands.kill_signals,
                         "CLI确认后不得再发信号")
        self.assertIn("takeover", self._state(), "接管必须留台账")
        self.assertIn("authorized_takeover_foreign_listener",
                      self._audit_text())
        self.assertNotIn("launched_pid=%d" % LIVE_LISTENER_PID,
                         Path(self.pidfile).read_text(encoding="utf-8"),
                         "接管不得写pidfile（防下相位mismatch误拒）")

    def test_takeover_disabled_keeps_original_refusal(self):
        orch = self._orch(takeover_enabled=False)
        result = orch.ensure("translation")
        self.assertEqual("refused", result.get("status"), result)
        self.assertEqual("server_unowned", result.get("reason"))
        self.assertEqual([], self.commands.stop_calls)
        self.assertEqual([], self.commands.kill_signals)

    def test_non_mtplx_listener_never_signalled(self):
        http = _Http(mtplx_family=False)
        orch = self._orch(http=http)
        result = orch.ensure("translation")
        self.assertEqual("refused", result.get("status"), result)
        self.assertEqual("server_unowned", result.get("reason"))
        self.assertEqual([], self.commands.stop_calls,
                         "探针不过不得发停机命令")
        self.assertEqual([], self.commands.kill_signals)
        self.assertIn("takeover_identity_probe_failed", self._audit_text())

    def test_unconfirmed_takeover_fail_closed_no_sigkill(self):
        commands = _Commands(cli_stop_effective=False,
                             sigterm_effective=False)
        orch = self._orch(commands=commands)
        result = orch.ensure("translation")
        self.assertEqual("refused", result.get("status"), result)
        self.assertEqual("takeover_stop_unconfirmed", result.get("reason"))
        signals = [sig for _pid, sig in commands.kill_signals]
        self.assertIn(15, signals, "SIGTERM兜底必须发出")
        self.assertNotIn(9, signals, "对外来进程绝不SIGKILL")

    # --------------------------------------------------------------- reuse

    def test_design_reuses_healthy_foreign_listener_via_gui(self):
        # 8001翻译模型驻留→切design必须先卸载（串行）；8002外来健康→复用
        http = _Http(omlx_loaded=True)
        orch = self._orch(http=http)
        result = orch.ensure("design")
        self.assertEqual("ok", result.get("status"), result)
        self.assertEqual(1, len(http.unloads), "必须卸载8001翻译模型（串行）")
        self.assertEqual([], self.commands.stop_calls,
                         "design相对外来健康监听者=复用，不得停机")
        self.assertIn("reuse", self._state())

    # ---------------------------------------------------------- guard tier

    def test_guard_tier_aligned_before_omlx_load(self):
        http = _Http(omlx_loaded=False, omlx_tier="balanced")
        orch = self._orch(http=http)
        result = orch.ensure("translation")
        self.assertEqual("ok", result.get("status"), result)
        self.assertTrue(http.tier_posts, "balanced→aggressive必须POST对齐")
        self.assertEqual("aggressive",
                         http.tier_posts[0]["memory_guard_tier"])
        self.assertIn("omlx_memory_guard_tier_align", self._audit_text())

    def test_guard_tier_noop_when_aligned(self):
        http = _Http(omlx_loaded=True, omlx_tier="aggressive")
        orch = self._orch(http=http)
        result = orch.ensure("translation")
        self.assertEqual("ok", result.get("status"), result)
        self.assertEqual([], http.tier_posts, "档位相符不得多余POST")


if __name__ == "__main__":
    unittest.main()
