# -*- coding: utf-8 -*-
"""SMOKE-r1-2 ③a（R27 收敛修订）反例：陈旧所有权台账把相位切换永久锁死。

现场（actions.log 978-1706 行，09-29 21:33 至 10-01 00:14 连续复现）：
MTPLX pidfile 持有已死 pid 18233（reason=process_not_running），真实服务以
另一 pid 在 8002 服役；翻译相位要切 oMLX 必须先停 MTPLX，旧逻辑对一切
owned=False 一律拒绝（"refusing to stop a server we do not own"），Hy-MT2
翻译 16 项全部 failed_retryable——纯簿记问题，oMLX 实际已加载翻译模型。

修后契约（fail-closed 保留给真实外来进程）：
- 台账 pid 死/缺 + 端口无监听 → 无可停者，停机视为已完成（和解+审计）；
- 台账 pid 死/缺 + 端口有监听且 cmdline 命中本部署身份标记 → 自纳管
  （重写 pidfile + adoption 台账 + 审计），正常停机；
- 监听进程不属于本部署（cmdline 不匹配）或无法观测端口 → 维持原拒绝；
- pidfile_identity_mismatch（活 pid 但身份不符）→ 维持原拒绝。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.api.app.model_lifecycle_orchestrator import (
    ModelLifecycleOrchestrator,
)

DEAD_LEDGER_PID = 18233
LIVE_LISTENER_PID = 63756
MTPLX_ENDPOINT = "http://127.0.0.1:8002"
DEPLOYMENT_CMDLINE = (
    "/Users/smkzw/Library/Application Support/MTPLX/runtime-venv/bin/python "
    "-P -m mtplx.server.openai --port 8002 --profile turbo"
)
FOREIGN_CMDLINE = "/usr/local/bin/someotherd --port 8002"


def _server(pidfile: str) -> dict:
    return {
        "endpoint": "http://127.0.0.1:8002",
        "port": 8002,
        "process_managed": True,
        "managed_model_id": "mtplx-flash-next-optimized-speed",
        "pidfile_path": pidfile,
        "pid_identity_markers": [
            "runtime-venv",
            "mtplx.server.openai",
            "--port 8002",
        ],
        "stop_command": ["mtplx", "stop", "--port", "8002"],
        "activity_path": "/v1/mtplx/flight",
    }


def _http(method: str, url: str, payload=None, timeout: float = 30.0,
          health_status=503, admin_models=None):
    if "/health" in url:
        return health_status, {}
    if "/admin/api/models" in url:
        return 200, admin_models if admin_models is not None else {"models": []}
    if "/v1/mtplx/flight" in url:
        # flight-style payload: no in-flight requests
        return 200, {"active": []}
    return 200, {}


class _Commands:
    """ps/lsof/stop fakes; records stop_command invocations."""

    def __init__(self, *, listener_pid, live_cmdline=None):
        self.listener_pid = listener_pid
        self.live_cmdline = live_cmdline
        self.stop_calls: list[list[str]] = []

    def __call__(self, argv, timeout: float | None = None):
        if argv and argv[0] == "ps":
            pid = int(argv[2])
            if pid == LIVE_LISTENER_PID and self.live_cmdline:
                return 0, self.live_cmdline, ""
            return 1, "", ""
        if argv and argv[0] == "lsof" and "-sTCP:LISTEN" in argv:
            if self.listener_pid is None:
                return 0, "", ""
            return 0, (
                f"COMMAND PID USER\npython {self.listener_pid} u\n"
            ), ""
        if argv and argv[0] == "lsof" and "-sTCP:ESTABLISHED" in argv:
            return 0, "", ""
        if argv and argv[:2] == ["mtplx", "stop"]:
            self.stop_calls.append(list(argv))
            # stop makes the listener disappear
            self.listener_pid = None
            return 0, "", ""
        return 0, "", ""


class OwnershipReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.pidfile = str(root / "mtplx_server.pid")
        Path(self.pidfile).write_text(
            f"launched_pid={DEAD_LEDGER_PID}\n", encoding="utf-8"
        )
        self.state_path = str(root / "orchestrator_state.json")
        self.audit_path = str(root / "actions.log")
        self.config = {
            "probe_max_tokens": 8,
            "poll_interval_seconds": 0.01,
            "release_confirm_timeout_seconds": 0.2,
            "drain_busy_retry_attempts": 1,
            "state_file_path": self.state_path,
            "audit_log_path": self.audit_path,
        }
        self.server = _server(self.pidfile)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _orchestrator(self, commands, http=_http) -> ModelLifecycleOrchestrator:
        # SMOKE-r2-1 ③ 测试安全：_drain 现在会直接向 health 自报 pid 发信号
        # （默认 os.kill）——夹具里的 pid 值取自真实环境常量，必须注入记录
        # 型假 kill，绝不让测试碰到真进程（曾发生：默认 os.kill 向真实
        # MTPLX 发了 SIGTERM，服务器自愈重启；此守卫防再发）。
        signals: list[tuple[int, int]] = []

        def fake_kill(pid, sig):
            signals.append((pid, sig))
            if sig == 15:  # SIGTERM: 假装进程退出
                commands.listener_pid = None
            return None

        self.recorded_signals = signals
        # 推进型假时钟：直接停机的 grace/confirm 轮询依赖时钟前进
        clock_state = {"t": 0.0}

        def advancing_clock():
            clock_state["t"] += 0.02
            return clock_state["t"]

        return ModelLifecycleOrchestrator(
            config=self.config,
            http=http,
            commands=commands,
            kill=fake_kill,
            clock=advancing_clock,
            sleep=lambda _s: None,
        )

    def _set_latch(self) -> None:
        Path(self.state_path).write_text(
            json.dumps({"release_unconfirmed": {"mtplx": True}},
                       ensure_ascii=False),
            encoding="utf-8",
        )

    def test_dead_ledger_no_listener_means_stop_complete(self):
        """台账 pid 已死且端口无监听：无可停者，停机完成，不发停机命令。"""
        commands = _Commands(listener_pid=None)
        orch = self._orchestrator(commands)
        result = orch._drain(
            "mtplx", self.server, "translation",
            force=False, wait_for_zero=False,
        )
        self.assertEqual("ok", result["status"], result)
        self.assertEqual([], commands.stop_calls)
        self.assertIn(
            "stale_ledger_stop_complete",
            Path(self.audit_path).read_text(encoding="utf-8"),
        )

    def test_dead_ledger_matching_listener_self_adopts_then_stops(self):
        """台账 pid 已死但端口监听者命中部署身份标记：自纳管后正常停机。"""
        commands = _Commands(
            listener_pid=LIVE_LISTENER_PID,
            live_cmdline=DEPLOYMENT_CMDLINE,
        )
        orch = self._orchestrator(commands)
        result = orch._drain(
            "mtplx", self.server, "translation",
            force=False, wait_for_zero=False,
        )
        self.assertEqual("ok", result["status"], result)
        # SMOKE-r2-1 ③ 修后契约：直接受管停机确认成功——不再调用 CLI stop
        # （CLI 对启用鉴权的服务器必然 not_mtplx 拒止），信号发给被纳管的
        # 监听 pid
        self.assertEqual([], commands.stop_calls)
        import signal as _signal
        self.assertEqual(
            [(LIVE_LISTENER_PID, _signal.SIGTERM)], self.recorded_signals
        )
        # pidfile 被重写为真实监听 pid
        self.assertEqual(
            f"launched_pid={LIVE_LISTENER_PID}\n",
            Path(self.pidfile).read_text(encoding="utf-8"),
        )
        # adoption 台账 + 审计留痕
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertTrue(state["adoption"]["mtplx"]["adopted"])
        self.assertEqual(
            LIVE_LISTENER_PID, state["adoption"]["mtplx"]["pid"]
        )
        audit = Path(self.audit_path).read_text(encoding="utf-8")
        self.assertIn("adopt_stale_pidfile_server", audit)

    def test_foreign_live_listener_still_refused(self):
        """端口被非本部署进程占用：维持 fail-closed 拒绝（不杀外来进程）。"""
        commands = _Commands(
            listener_pid=LIVE_LISTENER_PID,
            live_cmdline=FOREIGN_CMDLINE,
        )
        orch = self._orchestrator(commands)
        result = orch._drain(
            "mtplx", self.server, "translation",
            force=False, wait_for_zero=False,
        )
        self.assertEqual("refused", result["status"], result)
        self.assertEqual("server_unowned", result["reason"])
        self.assertEqual([], commands.stop_calls)

    def test_alive_but_mismatched_pidfile_keeps_refusal(self):
        """pidfile 指向活进程但 cmdline 身份不符：原拒绝语义原样保留。"""
        Path(self.pidfile).write_text(
            f"launched_pid={LIVE_LISTENER_PID}\n", encoding="utf-8"
        )
        commands = _Commands(
            listener_pid=LIVE_LISTENER_PID,
            live_cmdline=FOREIGN_CMDLINE,
        )
        orch = self._orchestrator(commands)
        identity = orch._mtplx_identity(self.server, orch._read_state())
        self.assertFalse(identity["owned"])
        self.assertEqual("pidfile_identity_mismatch", identity["reason"])
        result = orch._drain(
            "mtplx", self.server, "translation",
            force=False, wait_for_zero=False,
        )
        self.assertEqual("refused", result["status"], result)
        self.assertEqual([], commands.stop_calls)


class ReleaseUnconfirmedRecoveryTests(unittest.TestCase):
    """SMOKE-r1-3 共性主根因：release_unconfirmed 闩毒化全生命周期。

    现场（orchestrator_state.json mtime 19:11Z，
    release_unconfirmed={"mtplx": true}）：rollback 的 stop 实际已生效但
    未在确认窗内观测到 → ⑤ mwjob_582d291f… 4.7 分钟即死（未发生模型
    调用）、翻译 17 项停滞，需人工改状态文件。修后契约：观测已释放则
    自清闩放行；仍驻留/无法观测维持 fail-closed。
    """

    def setUp(self) -> None:
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.pidfile = str(root / "mtplx_server.pid")
        Path(self.pidfile).write_text(
            f"launched_pid={LIVE_LISTENER_PID}\n", encoding="utf-8")
        self.state_path = str(root / "orchestrator_state.json")
        self.audit_path = str(root / "actions.log")
        self.config = {
            "probe_max_tokens": 8,
            "poll_interval_seconds": 0.01,
            "release_confirm_timeout_seconds": 0.2,
            "state_file_path": self.state_path,
            "audit_log_path": self.audit_path,
        }
        self.server = {
            "endpoint": MTPLX_ENDPOINT,
            "port": 8002,
            "process_managed": True,
            "managed_model_id": "mtplx-flash-next-optimized-speed",
            "pidfile_path": self.pidfile,
            "pid_identity_markers": ["mtplx.server.openai"],
            "stop_command": ["mtplx", "stop", "--port", "8002"],
        }

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _orch(self, commands, http=_http):
        # 同上：注入记录型假 kill，测试绝不触碰真实进程
        def fake_kill(pid, sig):
            commands.recorded = getattr(commands, "recorded", [])
            commands.recorded.append((pid, sig))
            return None

        clock_state = {"t": 0.0}

        def advancing_clock():
            clock_state["t"] += 0.02
            return clock_state["t"]

        return ModelLifecycleOrchestrator(
            config=self.config, http=http, commands=commands,
            kill=fake_kill, clock=advancing_clock, sleep=lambda _s: None)

    def _latch(self):
        Path(self.state_path).write_text(
            json.dumps({"release_unconfirmed": {"mtplx": True}}),
            encoding="utf-8")

    def test_latch_cleared_when_server_actually_released(self):
        """进程型：端口无监听 + health 非 200 = 实际已释放 → 清闩放行。"""
        self._latch()
        commands = _Commands(listener_pid=None)
        orch = self._orch(commands)
        self.assertTrue(
            orch._recover_release_unconfirmed("mtplx", self.server))
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual({}, state.get("release_unconfirmed"))
        self.assertIn(
            "release_unconfirmed_recovered",
            Path(self.audit_path).read_text(encoding="utf-8"))

    def test_latch_cleared_when_server_resident_readopted(self):
        """进程型：health 200（仍在服役，stop 从未生效）→ 陈账方向相反，
        清闩并把驻留服务器重新采用（互斥排水/A18 探针仍把关；后续真实
        release 失败由 _drain 重新置闩）——这正是 r3 现场：MTPLX 驻留
        +闩毒化导致 ⑤ 全拒的死锁出口。"""
        self._latch()
        commands = _Commands(listener_pid=LIVE_LISTENER_PID)
        orch = self._orch(
            commands,
            http=lambda m, u, p=None, timeout=30.0: (200, {})
            if "/health" in u else (200, {"active": []}))
        self.assertTrue(
            orch._recover_release_unconfirmed("mtplx", self.server))
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual({}, state.get("release_unconfirmed"))
        self.assertIn(
            "resident server re-adopted",
            Path(self.audit_path).read_text(encoding="utf-8"))

    def test_latch_cleared_for_unloaded_model_server(self):
        """卸载型（oMLX）：受管模型未加载 = 实际已释放 → 清闩放行。"""
        omlx_server = {
            "endpoint": "http://127.0.0.1:8001",
            "port": 8001,
            "process_managed": False,
            "managed_model_id": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            "admin_models_path": "/admin/api/models",
        }
        Path(self.state_path).write_text(
            json.dumps({"release_unconfirmed": {"omlx": True}}),
            encoding="utf-8")
        orch = self._orch(_Commands(listener_pid=None))
        self.assertTrue(
            orch._recover_release_unconfirmed("omlx", omlx_server))
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual({}, state.get("release_unconfirmed"))

    def test_latch_cleared_when_model_server_still_loaded(self):
        """卸载型：受管模型仍在加载（unload 从未生效）→ 同样清闩重新
        采用（后续真实卸载失败会重新置闩）。"""
        omlx_server = {
            "endpoint": "http://127.0.0.1:8001",
            "port": 8001,
            "process_managed": False,
            "managed_model_id": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
            "admin_models_path": "/admin/api/models",
        }
        Path(self.state_path).write_text(
            json.dumps({"release_unconfirmed": {"omlx": True}}),
            encoding="utf-8")
        admin_models = {"models": [
            {"id": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX", "loaded": True}
        ]}
        orch = self._orch(
            _Commands(listener_pid=None),
            http=lambda m, u, p=None, timeout=30.0: (
                (200, admin_models) if "/admin/api/models" in u
                else (200, {})))
        self.assertTrue(
            orch._recover_release_unconfirmed("omlx", omlx_server))
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual({}, state.get("release_unconfirmed"))

    def test_confirmed_release_clears_latch(self):
        """SMOKE-r1-3 补充：确认成功的释放必须清闩——此前闩只置不清，
        任何一次确认超时都永久毒化（需人工改状态文件）。"""
        self._latch()
        commands = _Commands(
            listener_pid=LIVE_LISTENER_PID,
            live_cmdline=DEPLOYMENT_CMDLINE,
        )
        orch = self._orch(commands)
        result = orch._drain("mtplx", self.server, "design",
                             force=True, wait_for_zero=True)
        self.assertEqual("ok", result["status"], result)
        state = json.loads(Path(self.state_path).read_text(encoding="utf-8"))
        self.assertEqual({}, state.get("release_unconfirmed"))


class DirectManagedStopTests(unittest.TestCase):
    """SMOKE-r2-1 ③反例：CLI stop 对启用鉴权的 MTPLX 必然拒止。

    活体复现（本会话）：`mtplx stop --port 8002` → rc=1，
    {"ok": false, "reason": "not_mtplx"}——CLI 的 stop_daemon 不带
    api_key，/health 401 被归类为 PORT_FOREIGN；而同一时刻 health 自报
    startup.pid=63756 与台账一致。编排器配置的 stop_command 因此永远
    无法释放服务器，每次跨相位切换都 120s 确认超时 → release_unconfirmed
    闩（actions.log 08:01-08:05 三连）。修后契约：直接受管停机——
    SIGTERM 打到 health 自报 pid（先双重校验：health pid == 台账 pid 且
    cmdline 命中部署标记），grace 窗内轮询释放，超时升级 SIGKILL；身份
    不匹配维持拒绝；CLI 命令保留为回退。
    """

    def setUp(self) -> None:
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.pidfile = str(root / "mtplx_server.pid")
        Path(self.pidfile).write_text(
            f"launched_pid={LIVE_LISTENER_PID}\n", encoding="utf-8")
        self.state_path = str(root / "orchestrator_state.json")
        self.audit_path = str(root / "actions.log")
        self.config = {
            "probe_max_tokens": 8,
            "poll_interval_seconds": 0.01,
            "release_confirm_timeout_seconds": 0.3,
            "stop_grace_seconds": 0.05,
            "state_file_path": self.state_path,
            "audit_log_path": self.audit_path,
        }
        self.server = {
            "endpoint": MTPLX_ENDPOINT,
            "port": 8002,
            "process_managed": True,
            "managed_model_id": "mtplx-flash-next-optimized-speed",
            "pidfile_path": self.pidfile,
            "pid_identity_markers": ["mtplx.server.openai"],
            "stop_command": ["mtplx", "stop", "--port", "8002"],
        }

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _orch(self, commands, kill, http=_http):
        # advancing fake clock so grace/confirm windows always progress
        state = {"t": 0.0}

        def clock():
            state["t"] += 0.02
            return state["t"]

        return ModelLifecycleOrchestrator(
            config=self.config, http=http, commands=commands, kill=kill,
            clock=clock, sleep=lambda _s: None)

    def test_sigterm_releases_and_confirms(self):
        health_pids = iter([LIVE_LISTENER_PID, LIVE_LISTENER_PID])
        signals = []

        def kill(pid, sig):
            signals.append((pid, sig))
            # SIGTERM 后：监听消失、health 失效 → release 确认成立
            commands.listener_pid = None

        import signal as _signal
        commands = _Commands(
            listener_pid=LIVE_LISTENER_PID,
            live_cmdline=DEPLOYMENT_CMDLINE,
        )

        def http(method, url, payload=None, timeout=30.0):
            if "/health" in url:
                if commands.listener_pid is None:
                    return 503, {}
                try:
                    return 200, {"ok": True,
                                 "startup": {"pid": next(health_pids)}}
                except StopIteration:
                    return 200, {"ok": True,
                                 "startup": {"pid": LIVE_LISTENER_PID}}
            if "/v1/mtplx/flight" in url:
                return 200, {"active": []}
            return 200, {}

        orch = self._orch(commands, kill, http=http)

        result = orch._drain("mtplx", self.server, "translation",
                             force=False, wait_for_zero=False)
        self.assertEqual("ok", result["status"], result)
        self.assertEqual([(LIVE_LISTENER_PID, _signal.SIGTERM)], signals)
        # CLI stop 未被调用（直接停机已确认）
        self.assertEqual([], commands.stop_calls)
        audit = Path(self.audit_path).read_text(encoding="utf-8")
        self.assertIn("direct_stop_sigterm", audit)

    def test_identity_mismatch_refuses_to_signal(self):
        health_pids = iter([LIVE_LISTENER_PID])
        signals = []

        def kill(pid, sig):
            signals.append((pid, sig))

        commands = _Commands(
            listener_pid=LIVE_LISTENER_PID,
            live_cmdline=DEPLOYMENT_CMDLINE,
        )

        def http(method, url, payload=None, timeout=30.0):
            if "/health" in url:
                # health 自报另一个 pid → 与台账不一致 → 拒绝发信号
                return 200, {"ok": True, "startup": {"pid": 99999}}
            if "/v1/mtplx/flight" in url:
                return 200, {"active": []}
            return 200, {}

        orch = self._orch(commands, kill, http=http)
        result = orch._drain("mtplx", self.server, "translation",
                             force=False, wait_for_zero=False)
        # 修后契约：身份交叉校验失败 → 本轮排水直接拒绝（不置闩、不回退
        # CLI、绝不发信号——驻留服务器在服役，拒签未知 pid）
        self.assertEqual("refused", result["status"], result)
        self.assertEqual("direct_stop_identity_mismatch", result["reason"])
        self.assertEqual([], signals)
        self.assertEqual([], commands.stop_calls)
        # 拒绝路径不写任何状态：状态文件根本不应被创建/改动
        self.assertFalse(
            Path(self.state_path).exists(),
            "身份不匹配拒绝不得写状态文件（不置闩）",
        )

    def test_sigkill_escalation_after_grace(self):
        import signal as _signal
        signals = []
        commands = _Commands(
            listener_pid=LIVE_LISTENER_PID,
            live_cmdline=DEPLOYMENT_CMDLINE,
        )

        def kill(pid, sig):
            signals.append((pid, sig))
            if sig == _signal.SIGKILL:
                commands.listener_pid = None

        orch = self._orch(commands, kill)

        def http(method, url, payload=None, timeout=30.0):
            if "/health" in url:
                if commands.listener_pid is None:
                    return 503, {}
                return 200, {"ok": True,
                             "startup": {"pid": LIVE_LISTENER_PID}}
            if "/v1/mtplx/flight" in url:
                return 200, {"active": []}
            return 200, {}

        state = {"t": 0.0}

        def clock():
            state["t"] += 0.02
            return state["t"]

        orch = ModelLifecycleOrchestrator(
            config=self.config, http=http, commands=commands, kill=kill,
            clock=clock, sleep=lambda _s: None)
        result = orch._stop_process_managed(
            "mtplx", self.server,
            {"owned": True, "pid": LIVE_LISTENER_PID}, 0.3)
        self.assertTrue(result)
        import signal as _s
        self.assertIn((LIVE_LISTENER_PID, _s.SIGTERM), signals)
        self.assertIn((LIVE_LISTENER_PID, _s.SIGKILL), signals)


if __name__ == "__main__":
    unittest.main()
