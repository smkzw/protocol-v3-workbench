"""Medical-writing local model lifecycle orchestrator (round21, v1).

Automates the full lifecycle of exactly TWO managed local servers:

- oMLX  @ 127.0.0.1:8001  translation model (dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX)
- MTPLX @ 127.0.0.1:8002  triage/design model (mtplx-flash-next-optimized-speed)

Nothing else is ever started, stopped or unloaded: the live 8910 workbench,
medical-monitoring processes and every non-managed endpoint are out of scope
by contract.  Cloud routing is NOT touched — this module never writes
provider bindings, it only reads them (drift refusal; A18: a cloud answer is
never evidence of local capability).

Entry points (all idempotent, all audited to the round21 actions.log):

- ensure(phase)                    server up -> exclusion -> load -> A18 verify
- release(phase, reason[, force])  drain -> unload/stop -> completion confirm
- status()                         health/residency/binding flags/sentinel
- adopt(server, ...)               one-time adoption of an external server

In-flight safety (single API process assumption, documented limitation):
requests leaving through ai_gateway's only urlopen are counted by the
sentinel below (gateway_dispatch_begin/end).  Draining first sets the
draining flag (new dispatches refused through the gateway's existing
runtime-error path — no new cloud routing), then waits for the counter to
reach zero, re-checks activity/lsof, and only then executes stop/unload,
followed by a completion confirmation whose failure fail-closes further
loads.  Busy detection (round25 P1-C): when a server reports its own
activity endpoint, that signal is authoritative — idle established TCP
connections no longer veto a switch; the connection check remains for
servers without an activity signal (plus a bounded retry window), and as a
fail-closed fallback when activity is unreadable.  Direct external clients
bypassing the gateway are covered by the activity check and the
idle-recycle window only while their work is in flight — a declared
residual limitation.

Switch atomicity (round25 P0-A): a failed ensure() rolls back the server
it started (stop/unload + confirm), so a vetoed drain can no longer leave
a freshly launched model resident beside the incumbent; the arbitration
lease resets its dwell gate on failure so neither phase is frozen until
the window expires (round25 P1-D).

Cross-phase arbitration (0928): the two servers are mutually exclusive, so
concurrent users hitting different phases must be arbitrated, not race the
lifecycle.  ``PhaseArbiter`` (below) grants per-phase leases: same-phase
requests are counted concurrently; a cross-phase request whose holder is
busy enters a FIFO queue (never an error, never dropped) and is granted
only after the minimum dwell window since the last actual switch — queued
demand batches instead of flip-flopping the two servers.  Queue waits that
exceed ``arbitration_queue_timeout_seconds`` raise an explicit
``phase_queue_timeout`` refusal (surfaced through the gateway's existing
runtime-error path).  Every queue/switch/wait/timeout is audited.
ai_gateway's ``_managed_dispatch`` acquires/releases this arbiter around
each managed dispatch (the old sentinel counting is merged into the same
bracket), and the API warm-up sites go through ``warm_phase`` so warm
requests can never flip a server that other users are actively using.

Policy values (thresholds, timeouts, commands, store paths) live in
services/api/config/model_lifecycle.json — never in code constants.  Missing
config is fail-closed.  Probe max_tokens is capped at 8 (red line 4).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

MODULE_FILE = Path(__file__).resolve()
DEFAULT_CONFIG_PATH = (
    os.environ.get("MODEL_LIFECYCLE_CONFIG")
    or str(MODULE_FILE.parents[1] / "config" / "model_lifecycle.json")
)
REPO_ROOT = MODULE_FILE.parents[3]

MAX_PROBE_TOKENS = 8


class LifecycleRefusal(RuntimeError):
    """A lifecycle action was refused (policy/identity/safety) — never fatal."""

    # NEW-12(b)（R27 第2轮修订）：编排器拒绝按 reason 携带可直接展示的中文
    # zh_message；detail 保持工程英文（审计/日志），前端优先取 zh_message。
    def __init__(self, reason: str, detail: str = "", zh_message: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason
        self.zh_message = (
            zh_message
            or _REFUSAL_ZH_DEFAULTS.get(reason)
            or _REFUSAL_ZH_DEFAULTS["__default__"]
        )


# NEW-12(b)：按 reason 的默认中文指引；专用 raise 点可用显式 zh_message
# 覆盖。未列 reason 默认给通用模型忙指引，绝不为空。
_REFUSAL_ZH_DEFAULTS = {
    "__default__": "本地模型服务正忙或暂不可用，请稍后重试。",
    "ensure_failed": "本地模型服务正忙或正在冷启动，任务已排队，请稍候重试。",
    "phase_queue_timeout": "本地模型服务占用较高，当前请求排队超时；已保留的任务可稍后重试或继续处理。",
    "server_offline": "本地模型服务当前不可达，请稍后重试。",
    "draining": "本地模型服务正在切换/释放中，请稍后重试。",
}


# --------------------------------------------------------------------------
# In-process dispatch sentinel (single API process assumption)
# --------------------------------------------------------------------------

_sentinel_lock = threading.Lock()
_sentinel_state: dict[str, dict] = {}
_MANAGED_ENDPOINTS: set[str] | None = None  # None = not loaded yet


def _key(url: str) -> str:
    return urlparse(url).netloc or url


def reset_managed_cache(endpoints=None) -> None:
    """Point the sentinel at a set of managed endpoint URLs (tests/injection).

    ``None`` reloads from the default config on next use.
    """
    global _MANAGED_ENDPOINTS
    with _sentinel_lock:
        _MANAGED_ENDPOINTS = (
            None if endpoints is None else {_key(e) for e in endpoints}
        )


def _managed_keys() -> set[str]:
    global _MANAGED_ENDPOINTS
    with _sentinel_lock:
        if _MANAGED_ENDPOINTS is not None:
            return _MANAGED_ENDPOINTS
    try:
        cfg = load_config(DEFAULT_CONFIG_PATH)
        keys = {_key(s["endpoint"]) for s in cfg.get("servers", {}).values()}
    except Exception:
        # Config unavailable: sentinel counting is blind (fail-open counting
        # only); ensure/release still fail closed on the missing config.
        keys = set()
    with _sentinel_lock:
        _MANAGED_ENDPOINTS = keys
        return keys


def gateway_dispatch_begin(base_url: str) -> None:
    """Count one outgoing dispatch; refuse it while the server is draining."""
    key = _key(base_url)
    if key not in _managed_keys():
        return
    with _sentinel_lock:
        state = _sentinel_state.setdefault(
            key, {"inflight": 0, "draining": False, "last_request_ts": 0.0})
        if state["draining"]:
            raise LifecycleRefusal(
                "managed_server_draining",
                f"{base_url} is being drained for lifecycle maintenance; "
                "dispatch refused (existing fallback chain applies)")
        state["inflight"] += 1
        state["last_request_ts"] = time.time()


def gateway_dispatch_end(base_url: str) -> None:
    with _sentinel_lock:
        state = _sentinel_state.get(_key(base_url))
        if state and state["inflight"] > 0:
            state["inflight"] -= 1


def set_draining(base_url: str, value: bool) -> None:
    with _sentinel_lock:
        state = _sentinel_state.setdefault(
            _key(base_url), {"inflight": 0, "draining": False,
                             "last_request_ts": 0.0})
        state["draining"] = bool(value)


def sentinel_snapshot(base_url: str) -> dict:
    with _sentinel_lock:
        state = _sentinel_state.get(_key(base_url))
        if not state:
            return {"inflight": 0, "draining": False, "last_request_ts": 0.0}
        return dict(state)


# --------------------------------------------------------------------------
# Default IO (real environment); tests inject fakes instead
# --------------------------------------------------------------------------


def _http_json(method: str, url: str, payload=None, timeout: float = 30.0):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    # 0930 fix: MTPLX now enforces bearer auth on ALL endpoints including
    # /health and /v1/models (observed 401 with model fully resident). The
    # orchestrator's bare probes were misread as "server offline", causing a
    # 2h+ launch-retry loop while the server was healthy all along. Attach
    # the local MTPLX key from the environment (default matches the server's
    # documented local default) so probes authenticate.
    mtplx_key = os.environ.get("MTPLX_API_KEY", "mtplx-local")
    if ":8002" in url and mtplx_key:
        headers["Authorization"] = f"Bearer {mtplx_key}"
    req = urllib.request.Request(
        url, data=data,
        headers=headers,
        method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    try:
        return int(getattr(resp, "status", 200)), json.loads(body)
    except json.JSONDecodeError:
        return int(getattr(resp, "status", 200)), {"_raw": body}


def _run_command(argv: list[str], timeout: float = 180.0):
    proc = subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _launch_detached(argv: list[str], log_path: str | None = None) -> int:
    log = open(log_path, "ab") if log_path else subprocess.DEVNULL
    try:
        proc = subprocess.Popen(
            argv, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
        return proc.pid
    finally:
        if log_path:
            log.close()


def load_config(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _resolve(path: str | Path) -> Path:
    """Config paths may be repo-relative; resolve against REPO_ROOT so the
    audit/state/pidfile locations never drift with the process CWD."""
    p = Path(path)
    return p if p.is_absolute() else REPO_ROOT / p


# --------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------


class ModelLifecycleOrchestrator:
    """One API process, two managed servers, everything audited."""

    def __init__(self, config: dict | None = None, config_path: str | None = None,
                 http=None, commands=None, launch=None, clock=None, sleep=None):
        self.config = config
        self.config_path = config_path
        self.http = http or _http_json
        self.commands = commands or _run_command
        self.launch = launch or _launch_detached
        self.clock = clock or time.time
        self.sleep = sleep or time.sleep
        # set by PhaseArbiter when one is attached (release notifications)
        self.arbiter = None

    # ------------------------------------------------------------- plumbing

    def _load_config(self) -> dict:
        if self.config is None:
            path = self.config_path or DEFAULT_CONFIG_PATH
            try:
                self.config = load_config(path)
            except Exception as exc:
                raise LifecycleRefusal("config_missing", f"{path}: {exc}")
        cfg = self.config
        try:
            tokens = int(cfg.get("probe_max_tokens", 0))
        except (TypeError, ValueError):
            tokens = 0
        if tokens < 1 or tokens > MAX_PROBE_TOKENS:
            raise LifecycleRefusal(
                "probe_max_tokens_exceeds_limit",
                f"probe_max_tokens={cfg.get('probe_max_tokens')!r} exceeds "
                f"the hard cap of {MAX_PROBE_TOKENS} (red line 4)")
        for key in ("phase_roles", "protected_roles", "servers",
                    "runtime_store_dir", "audit_log_path", "state_file_path"):
            if key not in cfg:
                raise LifecycleRefusal("config_invalid", f"missing {key}")
        return cfg

    def _audit(self, tag: str, action: str, target: str, reason: str,
               precheck: str = "-", before: str = "-", outcome: str = "-",
               duration_s: float | None = None) -> None:
        cfg = self.config or {}
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration = "-" if duration_s is None else f"{duration_s:.2f}s"
        line = (
            f"{ts} [{tag}] 动作={action} | 目标={target} | 原因={reason} | "
            f"前置校核={precheck} | 前状态={before} | 结果={outcome} | "
            f"耗时={duration}"
        )
        path = cfg.get("audit_log_path")
        if path:
            try:
                path = _resolve(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass  # audit best-effort; never blocks the API

    def _read_state(self) -> dict:
        path = (self.config or {}).get("state_file_path")
        if path and _resolve(path).exists():
            try:
                return json.loads(_resolve(path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        return {}

    def _write_state(self, state: dict) -> None:
        path = (self.config or {}).get("state_file_path")
        if not path:
            return
        path = _resolve(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = f"{path}.tmp"
        Path(tmp).write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8")
        os.replace(tmp, path)

    def _refuse(self, reason: str, detail: str, phase: str = "",
                target: str = "-") -> dict:
        self._audit(f"refused/{reason}", action="lifecycle_refusal",
                    target=target, reason=reason, outcome=f"refused: {detail}")
        return {"status": "refused", "reason": reason, "detail": detail,
                "phase": phase}

    def _get(self, url: str, timeout: float = 15.0):
        try:
            return self.http("GET", url, None, timeout)
        except Exception as exc:
            return -1, {"_error": str(exc)}

    def _post(self, url: str, payload=None, timeout: float = 180.0):
        try:
            return self.http("POST", url, payload, timeout)
        except Exception as exc:
            return -1, {"_error": str(exc)}

    # ---------------------------------------------------------- store / cfg

    def _server_for_phase(self, cfg: dict, phase: str):
        for key, server in cfg["servers"].items():
            if phase in server.get("phases", []):
                return key, server
        return None, None

    def _read_store(self, cfg: dict):
        store_dir = Path(cfg["runtime_store_dir"])
        settings = store_dir / "ai_provider_settings.json"
        bindings = store_dir / "ai_role_bindings.json"
        if not settings.exists() or not bindings.exists():
            raise LifecycleRefusal(
                "runtime_store_missing", f"missing files under {store_dir}")
        profiles = {
            p.get("profile_id"): p
            for p in json.loads(settings.read_text(encoding="utf-8"))
            .get("profiles", [])
            if isinstance(p, dict) and p.get("profile_id")
        }
        binding_map = (
            json.loads(bindings.read_text(encoding="utf-8")).get("bindings", {}))
        return profiles, binding_map

    def _same_host_port(self, url_a: str, url_b: str) -> bool:
        return bool(_key(url_a)) and _key(url_a) == _key(url_b)

    def _expected_endpoint_by_role(self, cfg: dict) -> dict[str, str]:
        expected: dict[str, str] = {}
        for phase, roles in cfg["phase_roles"].items():
            for key, server in cfg["servers"].items():
                if phase in server.get("phases", []):
                    for role in roles:
                        expected.setdefault(role, server["endpoint"])
        return expected

    def _binding_flags(self, cfg: dict) -> dict[str, str]:
        """Per scheme-role flag: drift / elsewhere / ok / no_binding."""
        try:
            profiles, binding_map = self._read_store(cfg)
        except LifecycleRefusal:
            return {role: "store_unreadable" for role in cfg["protected_roles"]}
        expected_map = self._expected_endpoint_by_role(cfg)
        flags: dict[str, str] = {}
        for role in cfg["protected_roles"]:
            binding = binding_map.get(role) or {}
            if not binding.get("enabled"):
                flags[role] = "binding_disabled"
                continue
            profile = profiles.get(binding.get("profile_id"))
            if not profile:
                flags[role] = "binding_profile_unresolved"
                continue
            base_url = profile.get("base_url", "")
            expected = expected_map.get(role)
            if expected and self._same_host_port(base_url, expected):
                flags[role] = "ok"
            elif any(self._same_host_port(base_url, s["endpoint"])
                     for s in cfg["servers"].values()):
                flags[role] = "points_elsewhere"
            else:
                flags[role] = "binding_base_url_mismatch"
        return flags

    # --------------------------------------------------------- identity/ops

    def _read_pidfile(self, server: dict) -> int | None:
        path = server.get("pidfile_path")
        if not path or not _resolve(path).exists():
            return None
        try:
            text = _resolve(path).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        for part in text.replace(";", " ").split():
            if part.startswith("launched_pid="):
                try:
                    return int(part.split("=", 1)[1])
                except ValueError:
                    return None
        return None

    def _proc_cmdline(self, pid: int):
        try:
            rc, out, _ = self.commands(["ps", "-p", str(pid), "-o", "command="])
        except Exception:
            return None
        if rc != 0:
            return None
        return out.strip() or None

    def _cmdline_ok(self, server: dict, cmdline: str) -> bool:
        markers = server.get("pid_identity_markers") or []
        return all(marker in cmdline for marker in markers)

    def _mtplx_identity(self, server: dict, state: dict) -> dict:
        """Read-only ownership identity for the process-managed server."""
        pid = self._read_pidfile(server)
        if pid is None:
            adopted = (state.get("adoption") or {}).get("mtplx") or {}
            pid = adopted.get("pid")
        if pid is None:
            return {"owned": False, "pid": None, "reason": "no_pidfile"}
        cmdline = self._proc_cmdline(pid)
        if cmdline is None:
            return {"owned": False, "pid": pid, "reason": "process_not_running"}
        if not self._cmdline_ok(server, cmdline):
            return {"owned": False, "pid": pid,
                    "reason": "pidfile_identity_mismatch", "cmdline": cmdline}
        return {"owned": True, "pid": pid, "cmdline": cmdline}

    def _listen_pid(self, port: int) -> int | None:
        """PID listening on the port; None = confirmed no listener;
        -1 = cannot observe (fail-closed for stop confirmation)."""
        try:
            rc, out, _ = self.commands(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"])
        except Exception:
            return -1
        if not out.strip():
            return None
        for line in out.strip().splitlines():
            parts = line.split()
            if len(parts) > 1 and parts[1].isdigit():
                return int(parts[1])
        return -1

    def _established_count(self, port: int) -> int | None:
        """Established-connection count; None = cannot observe (fail-closed).

        lsof exits non-zero when nothing matches, so rc is ignored: an empty
        output means zero established connections (the normal idle case).
        """
        try:
            rc, out, _ = self.commands(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED"])
        except Exception:
            return None
        return len([ln for ln in out.splitlines() if ln.strip()])

    def _wait_health(self, server: dict, timeout: float) -> bool:
        deadline = self.clock() + timeout
        interval = float((self.config or {}).get("poll_interval_seconds", 1.0))
        while True:
            status, _ = self._get(f"{server['endpoint']}/health", timeout=5.0)
            if status == 200:
                return True
            if self.clock() >= deadline:
                return False
            self.sleep(interval)

    def _start_server(self, server_key: str, server: dict, phase: str) -> dict:
        if server.get("process_managed"):
            self._audit("action/start", action="launch_detached",
                        target=f"{server_key}@{server['endpoint']}",
                        reason=f"ensure({phase}) server offline",
                        precheck="health!=200, not owned by us",
                        before="offline", outcome="launch issued")
            launcher_pid = self.launch(
                list(server["start_command"]),
                log_path=(str(_resolve(server["server_log_path"]))
                          if server.get("server_log_path") else None))
        else:
            self._audit("action/start", action="run_start_command",
                        target=f"{server_key}@{server['endpoint']}",
                        reason=f"ensure({phase}) server offline",
                        precheck="health!=200", before="offline",
                        outcome="start command issued")
            self.commands(list(server["start_command"]))
            launcher_pid = None
        timeout = float(server.get("start_timeout_seconds")
                        or (self.config or {}).get("start_timeout_seconds", 120))
        if not self._wait_health(server, timeout):
            self._audit("action/start-failed", action="start_timeout",
                        target=server_key, reason=f"ensure({phase})",
                        before="launch issued",
                        outcome="health never reached 200 within timeout")
            return {"status": "failed", "reason": "start_timeout",
                    "phase": phase}
        if server.get("process_managed"):
            pid = self._listen_pid(server["port"])
            if (pid is None or pid < 0) and launcher_pid:
                # lsof found nothing (or cannot run): fall back to the
                # launcher pid recorded at launch time
                pid = launcher_pid
            if pid is None:
                self._audit("action/start", action="pid_discovery_failed",
                            target=server_key, reason="no listener found",
                            before="launched", outcome="pidfile not written")
            else:
                _resolve(server["pidfile_path"]).write_text(
                    f"launched_pid={pid}\n", encoding="utf-8")
                cmdline = self._proc_cmdline(pid)
                if cmdline is not None and not self._cmdline_ok(server, cmdline):
                    return self._refuse(
                        "pidfile_identity_mismatch",
                        f"freshly started pid={pid} cmdline={cmdline!r}",
                        phase=phase, target=server_key)
        return {"status": "ok"}

    # ------------------------------------------------------- in-flight/drain

    def _busy_reason(self, server: dict) -> str | None:
        """Why the server is busy right now (None = free).

        round25 P1-C: when the server's own activity endpoint is readable,
        it is authoritative — idle established TCP connections (admin UI,
        MarkItDown, monitors, third-party sessions) no longer veto a switch;
        real work still does (active/waiting > 0, or the gateway sentinel).
        The established-connection check remains the veto for servers
        without an activity signal and as a fail-closed fallback when the
        activity endpoint itself is unreadable.
        """
        if sentinel_snapshot(server["endpoint"])["inflight"] > 0:
            return "busy_inflight"
        activity = server.get("activity_path")
        if activity:
            status, body = self._get(f"{server['endpoint']}{activity}")
            if status == 200:
                active = body.get("total_active_requests")
                waiting = body.get("total_waiting_requests")
                if active is None or waiting is None:
                    # field shape drifts between oMLX builds (risk 7): fall
                    # back to the nested active_models counters
                    inner = body.get("active_models") or {}
                    active = inner.get("total_active_requests")
                    waiting = inner.get("total_waiting_requests")
                if active is None or waiting is None:
                    # flight-style payloads (MTPLX /v1/mtplx/flight): a list
                    # of live in-flight requests; queued-but-not-started work
                    # is not tracked there
                    flight = body.get("active")
                    if isinstance(flight, list):
                        active, waiting = len(flight), 0
                if active is not None and waiting is not None:
                    if int(active) > 0 or int(waiting) > 0:
                        return "busy_activity"
                    return None  # activity authoritative: idle, no veto
            # unreadable activity: fall through to the connection veto
        count = self._established_count(server["port"])
        if count is None:
            return "busy_connections_unreadable"
        if count > 0:
            return "busy_connections"
        return None

    def _busy_reason_with_retry(self, server: dict) -> str | None:
        """_busy_reason within the bounded re-check window (AGG25 P1-8): a
        transient blip gets drain_busy_retry_attempts chances to clear
        before it counts as a veto."""
        interval = float((self.config or {}).get("poll_interval_seconds", 1.0))
        attempts = max(1, int((self.config or {}).get(
            "drain_busy_retry_attempts", 3)))
        busy = None
        for attempt in range(attempts):
            busy = self._busy_reason(server)
            if not busy:
                break
            if attempt < attempts - 1:
                self.sleep(interval)
        return busy

    def _resident(self, server: dict) -> bool:
        if server.get("process_managed"):
            status, _ = self._get(f"{server['endpoint']}/health")
            return status == 200
        status, body = self._get(
            f"{server['endpoint']}"
            f"{server.get('admin_models_path', '/admin/api/models')}")
        if status != 200:
            return False
        for entry in body.get("models", []) or []:
            if entry.get("id") == server["managed_model_id"]:
                return bool(entry.get("loaded")) and not entry.get("is_loading")
        return False

    def _confirm_released(self, server_key: str, server: dict,
                          timeout: float) -> bool:
        interval = float((self.config or {}).get("poll_interval_seconds", 1.0))
        deadline = self.clock() + timeout
        while True:
            if server.get("process_managed"):
                pid = self._listen_pid(server["port"])
                health_status, _ = self._get(f"{server['endpoint']}/health",
                                             timeout=3.0)
                if pid is None and health_status != 200:
                    return True
            else:
                status, body = self._get(
                    f"{server['endpoint']}"
                    f"{server.get('admin_models_path', '/admin/api/models')}")
                if status == 200:
                    for entry in body.get("models", []) or []:
                        if entry.get("id") == server["managed_model_id"]:
                            if (not entry.get("loaded")
                                    and not entry.get("is_loading")):
                                return True
                            break
                    else:
                        return True
            if self.clock() >= deadline:
                return False
            self.sleep(interval)

    def _drain(self, server_key: str, server: dict, phase: str,
               force: bool, wait_for_zero: bool) -> dict:
        """Refuse-or-drain one managed server; completion-confirmed.

        wait_for_zero=False (ensure side): any in-flight work refuses the
        drain outright — a load must never evict a busy sibling.
        wait_for_zero=True (release side): set draining, WAIT for the counter
        to hit zero, re-check, then execute.
        ``force`` widens only the idle window, never live traffic.
        """
        interval = float((self.config or {}).get("poll_interval_seconds", 1.0))
        confirm_timeout = float(
            (self.config or {}).get("release_confirm_timeout_seconds", 120))

        if not wait_for_zero:
            # ensure side: a load must never evict a busy sibling.  round25
            # P1-C: the busy signal is re-checked within a bounded window so
            # a transient blip (sampler poll, keep-alive churn) does not
            # veto a switch in one shot; a persistent veto still refuses.
            busy = self._busy_reason_with_retry(server)
            if busy:
                return self._refuse(busy,
                                    f"{server_key} has in-flight work",
                                    phase=phase, target=server_key)
        else:
            # release side: honour the idle-recycle window unless forced
            idle = float(server.get("idle_recycle_seconds", 0) or 0)
            snap = sentinel_snapshot(server["endpoint"])
            since = self.clock() - snap["last_request_ts"]
            if (not force and idle > 0 and snap["last_request_ts"] > 0
                    and 0 <= since < idle):
                return {"status": "noop", "reason": "idle_window_open",
                        "phase": phase}

        t0 = self.clock()
        set_draining(server["endpoint"], True)
        try:
            if wait_for_zero:
                deadline = self.clock() + confirm_timeout
                while sentinel_snapshot(server["endpoint"])["inflight"] > 0:
                    if self.clock() >= deadline:
                        return self._refuse(
                            "drain_inflight_timeout",
                            "dispatch counter never reached zero",
                            phase=phase, target=server_key)
                    self.sleep(interval)
            # TOCTOU mitigation: final re-check before the irreversible step
            # (AGG25 P1-8: same bounded window as the ensure-side check, so a
            # blip between the checks cannot veto the whole switch)
            busy_again = self._busy_reason_with_retry(server)
            if busy_again:
                return self._refuse(busy_again,
                                    "re-check found in-flight work",
                                    phase=phase, target=server_key)

            if server.get("process_managed"):
                identity = self._mtplx_identity(server, self._read_state())
                if not identity["owned"]:
                    return self._refuse(
                        identity.get("reason", "server_unowned"),
                        f"refusing to stop a server we do not own: {identity}",
                        phase=phase, target=server_key)
                self._audit("action/stop", action="run_stop_command",
                            target=f"{server_key}@{server['endpoint']}",
                            reason=f"drain for {'release' if wait_for_zero else f'ensure({phase})'}",
                            precheck="inflight=0, activity=0, no established",
                            before=f"pid={identity['pid']} health=200",
                            outcome="stop command issued")
                self.commands(list(server["stop_command"]),
                              timeout=confirm_timeout + 60)
                confirmed = self._confirm_released(
                    server_key, server, confirm_timeout)
            else:
                model_id = server["managed_model_id"]
                self._audit("action/unload", action="admin_unload",
                            target=f"{server_key}@{server['endpoint']}/{model_id}",
                            reason=f"drain for {'release' if wait_for_zero else f'ensure({phase})'}",
                            precheck="inflight=0, activity=0, no established",
                            before="resident", outcome="unload POST issued")
                status, _ = self._post(
                    f"{server['endpoint']}"
                    f"{server.get('unload_path', '/admin/api/models/{model}/unload')}"
                    .format(model=model_id))
                confirmed = (status == 200
                             and self._confirm_released(server_key, server,
                                                        confirm_timeout))

            duration = self.clock() - t0
            if not confirmed:
                state = self._read_state()
                state.setdefault("release_unconfirmed", {})[server_key] = True
                self._write_state(state)
                self._audit("action/release-failed",
                            action="release_confirm_timeout",
                            target=server_key,
                            reason="completion confirmation failed; "
                                   "fail-closed until manual recovery",
                            before="release issued",
                            outcome="refusing further loads",
                            duration_s=duration)
                return {"status": "failed", "reason": "release_confirm_timeout",
                        "phase": phase}
            self._audit("action/release-done", action="drain_complete",
                        target=server_key, reason=f"phase={phase}",
                        before="resident", outcome="released and confirmed",
                        duration_s=duration)
            return {"status": "ok"}
        finally:
            set_draining(server["endpoint"], False)

    def _rollback_started(self, server_key: str, server: dict,
                          phase: str) -> None:
        """round25 P0-A: stop/unload a server THIS ensure() started after the
        switch failed — a launched target must never stay resident beside the
        incumbent.  If the rollback itself fails, fail closed (release
        unconfirmed) so no further lifecycle work proceeds unattended."""
        self._audit("action/rollback", action="rollback_started_server",
                    target=server_key, reason=f"ensure({phase}) switch "
                    "failed after start; rolling back the started server",
                    before="launched by this ensure", outcome="rollback issued")
        rolled_back = self._drain(server_key, server, phase, force=True,
                                  wait_for_zero=True)
        if rolled_back["status"] == "ok":
            self._audit("action/rollback-done",
                        action="rollback_complete", target=server_key,
                        reason=f"ensure({phase})", before="launched",
                        outcome="stopped and confirmed")
            return
        state = self._read_state()
        state.setdefault("release_unconfirmed", {})[server_key] = True
        self._write_state(state)
        self._audit("action/rollback-failed",
                    action="rollback_confirm_timeout", target=server_key,
                    reason=f"ensure({phase}) rollback did not confirm; "
                           "fail-closed until manual recovery",
                    before="release issued", outcome="refusing further loads")

    # ---------------------------------------------------------------- ensure

    def ensure(self, phase: str) -> dict:
        t0 = self.clock()
        try:
            cfg = self._load_config()
        except LifecycleRefusal as exc:
            self.config = self.config or {}
            return self._refuse(exc.reason, exc.detail, phase=phase)
        try:
            return self._ensure(cfg, phase, t0)
        except LifecycleRefusal as exc:
            return self._refuse(exc.reason, exc.detail, phase=phase)

    def _ensure(self, cfg: dict, phase: str, t0: float) -> dict:
        roles = cfg["phase_roles"].get(phase)
        if not roles:
            return self._refuse("unknown_phase", f"phase={phase!r} not mapped",
                                phase=phase)
        server_key, server = self._server_for_phase(cfg, phase)
        if server is None:
            return self._refuse("unknown_phase",
                                f"no server serves phase={phase!r}",
                                phase=phase)

        if not Path(cfg["runtime_store_dir"]).exists():
            return self._refuse("runtime_store_missing",
                                cfg["runtime_store_dir"], phase=phase)

        state = self._read_state()
        if (state.get("release_unconfirmed") or {}).get(server_key):
            return self._refuse(
                "release_unconfirmed",
                "a previous release never completed; manual recovery required",
                phase=phase, target=server_key)

        # binding-driven endpoint + drift refusal: read the same store the
        # workbench reads; never write it (red line 3)
        profiles, binding_map = self._read_store(cfg)
        for role in roles:
            binding = binding_map.get(role) or {}
            if not binding.get("enabled"):
                continue  # role unbound/disabled: the binding source is silent
            profile = profiles.get(binding.get("profile_id"))
            if not profile:
                return self._refuse(
                    "binding_profile_unresolved",
                    f"role={role} profile={binding.get('profile_id')!r}",
                    phase=phase, target=server_key)
            if not self._same_host_port(profile.get("base_url", ""),
                                        server["endpoint"]):
                return self._refuse(
                    "binding_base_url_mismatch",
                    f"role={role} profile base_url="
                    f"{profile.get('base_url')!r} vs managed "
                    f"{server['endpoint']}",
                    phase=phase, target=server_key)

        # identity / reuse-first (read-only); healthy foreign instances are
        # reused, only a confirmed identity mismatch refuses
        started_here = False
        if server.get("process_managed"):
            identity = self._mtplx_identity(server, state)
            healthy = self._resident(server)
            if (healthy
                    and identity.get("reason") == "pidfile_identity_mismatch"):
                return self._refuse(
                    "pidfile_identity_mismatch",
                    f"pid={identity.get('pid')} "
                    f"cmdline={identity.get('cmdline')!r}",
                    phase=phase, target=server_key)
            if not healthy:
                started = self._start_server(server_key, server, phase)
                if started["status"] != "ok":
                    return started
                started_here = True
        else:
            status, _ = self._get(f"{server['endpoint']}/health")
            if status != 200:
                started = self._start_server(server_key, server, phase)
                if started["status"] != "ok":
                    return started
                started_here = True

        # mutual exclusion: the two resident models cannot coexist (budget
        # arithmetic in mem_probe.md: ~29.8GB + ~80GB ≈ 110GB on 128GB).
        # round25 P0-A: if the switch fails after we started the target,
        # roll it back — what ensure() started, ensure() stops.  Otherwise a
        # vetoed drain leaves the freshly launched server resident next to
        # the incumbent (persistent double load, no self-healing).
        for other_key, other in cfg["servers"].items():
            if other_key == server_key or not self._resident(other):
                continue
            drained = self._drain(other_key, other, phase,
                                  force=False, wait_for_zero=False)
            if drained["status"] != "ok":
                if started_here:
                    self._rollback_started(server_key, server, phase)
                if drained["status"] == "refused":
                    return {"status": "refused",
                            "reason": drained.get("reason", "drain_refused"),
                            "detail": drained.get("detail", ""),
                            "phase": phase}
                return drained

        action_taken = False
        if not self._resident(server):
            if not server.get("process_managed"):
                precheck = self._memory_precheck(server)
                if precheck is not None:
                    return self._refuse("memory_guard", precheck, phase=phase,
                                        target=server_key)
            self._audit("action/load-probe", action="chat_probe_load",
                        target=f"{server_key}/{server['managed_model_id']}",
                        reason=f"ensure({phase}) model not resident",
                        precheck="identity ok, exclusion ok, memory ok",
                        before="not resident", outcome="probe issued")
            action_taken = True

        ok, err, tokens = self._a18_probe(server)
        duration = self.clock() - t0
        if not ok:
            self._audit("action/load-failed", action="a18_probe_failed",
                        target=f"{server_key}/{server['managed_model_id']}",
                        reason=f"ensure({phase})", before="probe sent",
                        outcome=err or "a18_failed", duration_s=duration)
            return {"status": "failed", "reason": "a18_probe_failed",
                    "detail": err, "phase": phase}
        self._audit("action/ensure-done", action="ensure_complete",
                    target=f"{server_key}/{server['managed_model_id']}",
                    reason=f"ensure({phase})",
                    before="loaded" if action_taken else "already resident",
                    outcome=f"A18 verified (identity+choices, "
                            f"max_tokens={tokens})", duration_s=duration)
        return {"status": "ok", "phase": phase, "server": server_key,
                "action_taken": action_taken,
                "model": server["managed_model_id"]}

    def _memory_precheck(self, server: dict) -> str | None:
        """Live-derived precheck only: guard ceiling ≥ est×factor, else refuse."""
        precheck = server.get("load_memory_precheck") or {}
        if not precheck:
            return None
        status, body = self._get(
            f"{server['endpoint']}"
            f"{server.get('activity_path', '/admin/api/activity')}")
        if status != 200:
            return f"activity unreadable (HTTP {status})"
        ceiling = body.get("model_memory_max")
        if ceiling is None:
            ceiling = (body.get("active_models") or {}).get("model_memory_max")
        if ceiling is None:
            return "model_memory_max missing from activity; fail-closed"
        needed = (float(precheck.get("estimated_model_bytes", 0))
                  * float(precheck.get("factor", 1.1)))
        if float(ceiling) < needed:
            return f"model_memory_max={ceiling} < est×factor={needed:.0f}"
        return None

    def _a18_probe(self, server: dict):
        """Chat probe: identity + non-empty choices. Returns (ok, err, tokens)."""
        tokens = int((self.config or {}).get("probe_max_tokens", 1))
        status, body = self._post(
            f"{server['endpoint']}/v1/chat/completions",
            {"model": server["managed_model_id"],
             "messages": [{"role": "user", "content": "ping"}],
             "max_tokens": tokens},
            timeout=float((self.config or {}).get("probe_timeout_seconds", 180)))
        if status != 200:
            return False, f"HTTP {status}", tokens
        if body.get("model") != server["managed_model_id"]:
            return False, (f"a18 model mismatch: requested="
                           f"{server['managed_model_id']!r} responded="
                           f"{body.get('model')!r}"), tokens
        if not body.get("choices"):
            return False, "a18 empty choices", tokens
        return True, "", tokens

    # --------------------------------------------------------------- release

    def release(self, phase: str, reason: str, force: bool = False) -> dict:
        t0 = self.clock()
        try:
            cfg = self._load_config()
        except LifecycleRefusal as exc:
            self.config = self.config or {}
            return self._refuse(exc.reason, exc.detail, phase=phase)
        try:
            return self._release(cfg, phase, reason, force, t0)
        except LifecycleRefusal as exc:
            return self._refuse(exc.reason, exc.detail, phase=phase)

    def _release(self, cfg: dict, phase: str, reason: str, force: bool,
                 t0: float) -> dict:
        roles = cfg["phase_roles"].get(phase)
        server_key, server = (None, None)
        if roles:
            server_key, server = self._server_for_phase(cfg, phase)
        if not roles or server is None:
            return self._refuse("unknown_phase", f"phase={phase!r}",
                                phase=phase)

        state = self._read_state()
        if (state.get("release_unconfirmed") or {}).get(server_key):
            return self._refuse("release_unconfirmed",
                                "previous release unconfirmed", phase=phase,
                                target=server_key)

        # medical-monitoring (and any foreign role) refusal: an ENABLED
        # binding of a non-scheme role pointing at this managed server
        # blocks the release for human adjudication
        profiles, binding_map = self._read_store(cfg)
        for role, binding in binding_map.items():
            if role in cfg["protected_roles"] or not binding.get("enabled"):
                continue
            profile = profiles.get(binding.get("profile_id"))
            if profile and self._same_host_port(profile.get("base_url", ""),
                                                server["endpoint"]):
                return self._refuse(
                    "protected_binding_active",
                    f"role={role} is enabled against {server_key}; human "
                    "adjudication required before release",
                    phase=phase, target=server_key)

        if not self._resident(server):
            self._note_released(server_key)
            self._audit("action/release-done", action="nothing_to_release",
                        target=server_key, reason=reason, before="not resident",
                        outcome="noop")
            return {"status": "noop", "reason": "already_released",
                    "phase": phase}

        drained = self._drain(server_key, server, phase, force=force,
                              wait_for_zero=True)
        self._note_released(server_key)
        if drained["status"] != "ok":
            return drained
        return {"status": "ok", "phase": phase, "server": server_key,
                "released": True, "reason": reason}

    def _note_released(self, server_key: str) -> None:
        arbiter = getattr(self, "arbiter", None)
        if arbiter is not None:
            try:
                arbiter.note_released(server_key)
            except Exception:
                pass  # notification is advisory; release result stands

    # ---------------------------------------------------------------- status

    def status(self) -> dict:
        try:
            cfg = self._load_config()
        except LifecycleRefusal as exc:
            return {"status": "degraded", "reason": exc.reason,
                    "detail": exc.detail}
        state = self._read_state()
        servers = {}
        for key, server in cfg["servers"].items():
            health_status, _ = self._get(f"{server['endpoint']}/health")
            healthy = health_status == 200
            entry = {
                "healthy": healthy,
                "resident": self._resident(server) if healthy else False,
                "release_unconfirmed": bool(
                    (state.get("release_unconfirmed") or {}).get(key)),
                "sentinel": sentinel_snapshot(server["endpoint"]),
            }
            if server.get("process_managed"):
                entry["identity"] = self._mtplx_identity(server, state)
            servers[key] = entry
        arbiter = getattr(self, "arbiter", None)
        return {"status": "ok", "servers": servers,
                "binding_flags": self._binding_flags(cfg),
                "arbiter": arbiter.snapshot() if arbiter is not None else None}

    # ---------------------------------------------------------------- adopt

    def adopt(self, server_key: str, operator: str = "",
              evidence: str = "") -> dict:
        """One-time adoption of an already-running externally launched server."""
        try:
            cfg = self._load_config()
        except LifecycleRefusal as exc:
            return {"adopted": False, "reason": exc.reason, "detail": exc.detail}
        server = cfg["servers"].get(server_key)
        if server is None or not server.get("process_managed"):
            return {"adopted": False, "reason": "not_process_managed"}
        pid = self._read_pidfile(server)
        checks = {"pidfile_ok": pid is not None}
        cmdline = self._proc_cmdline(pid) if pid is not None else None
        checks["process_alive"] = cmdline is not None
        checks["cmdline_markers_ok"] = bool(
            cmdline and self._cmdline_ok(server, cmdline))
        status, body = self._get(f"{server['endpoint']}/v1/models")
        checks["served_model_id_ok"] = status == 200 and any(
            m.get("id") == server["managed_model_id"]
            for m in (body.get("data") or []))
        if not all(checks.values()):
            reason = ("pidfile_identity_mismatch"
                      if checks["process_alive"]
                      and not checks["cmdline_markers_ok"]
                      else "adoption_checks_failed")
            self._audit("refused/adoption", action="adopt", target=server_key,
                        reason=f"adoption refused: {checks}",
                        before="unmanaged external", outcome="refused")
            return {"adopted": False, "reason": reason, "checks": checks}
        state = self._read_state()
        state["adoption"] = {
            server_key: {
                "adopted": True, "pid": pid, "operator": operator,
                "evidence": evidence,
                "adopted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "checks": checks,
            },
        }
        self._write_state(state)
        self._audit("state/adoption", action="adopt_external_server",
                    target=f"{server_key} pid={pid}",
                    reason=evidence or "LIVE step0 adoption",
                    precheck=f"checks={checks}", before="unmanaged external",
                    outcome="adopted, pidfile management resumed")
        return {"adopted": True, "pid": pid, "checks": checks}


# --------------------------------------------------------------------------
# Module-level convenience (the call site in main.py stays best-effort)
# --------------------------------------------------------------------------

_default_orchestrator: ModelLifecycleOrchestrator | None = None
_default_lock = threading.Lock()


def _default() -> ModelLifecycleOrchestrator:
    global _default_orchestrator
    with _default_lock:
        if _default_orchestrator is None:
            _default_orchestrator = ModelLifecycleOrchestrator()
        return _default_orchestrator


def ensure_phase(phase: str) -> dict:
    return _default().ensure(phase)


def release_phase(phase: str, reason: str, force: bool = False) -> dict:
    return _default().release(phase, reason, force=force)


def lifecycle_status() -> dict:
    return _default().status()


# --------------------------------------------------------------------------
# Cross-phase concurrency arbiter (0928)
# --------------------------------------------------------------------------


class _ArbEntry:
    __slots__ = ("server", "phase", "reason", "enqueued_at")

    def __init__(self, server: str, phase: str, reason: str):
        self.server = server
        self.phase = phase
        self.reason = reason
        self.enqueued_at: float | None = None


class PhaseArbiter:
    """Serialize model residency between the two mutually exclusive servers.

    One API process, one GPU budget: at any moment a single server holds the
    grant (``current``).  Semantics:

    - same-phase requests are counted concurrently and served instantly —
      the grant survives idle periods so a burst never re-loads per request;
    - a cross-phase request whose holder has active users (or which arrives
      inside the minimum dwell window since the last actual switch) enters a
      FIFO queue and waits — never an error, never dropped;
    - after the dwell window expires the queue head switches: the switcher
      runs ``ensure()`` (drain + load + A18) while later same-server joiners
      wait on the per-server ready flag instead of racing the load;
    - a queue wait exceeding ``arbitration_queue_timeout_seconds`` raises
      ``LifecycleRefusal("phase_queue_timeout")`` — an explicit error that
      the gateway surfaces through the existing fallback chain;
    - every queue/switch/wait/timeout is audited to the round21 actions.log.

    Waits are poll loops on an injected clock/sleep so tests can drive the
    full timeline with a stub clock (zero real time, zero real models).
    """

    def __init__(self, orchestrator: ModelLifecycleOrchestrator,
                 clock=None, sleep=None):
        self.orch = orchestrator
        self.clock = clock or time.monotonic
        self.sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._current: str | None = None
        self._users: dict[str, int] = {}
        self._queue: deque[_ArbEntry] = deque()
        self._switched_at: float | None = None
        self._ready: dict[str, bool] = {}    # False only during a switch load
        self._ready_error: dict[str, str] = {}
        orchestrator.arbiter = self

    # ------------------------------------------------------------- plumbing

    def _cfg(self) -> dict:
        return self.orch._load_config()

    def _dwell(self, cfg: dict) -> float:
        return float(cfg.get("arbitration_min_dwell_seconds", 600))

    def _queue_timeout(self, cfg: dict) -> float:
        return float(cfg.get("arbitration_queue_timeout_seconds", 1800))

    def _poll(self, cfg: dict) -> float:
        return max(0.05, min(1.0, float(cfg.get("poll_interval_seconds", 1))))

    def _server_for_phase(self, cfg: dict, phase: str):
        return self.orch._server_for_phase(cfg, phase)

    def _phase_for_endpoint(self, base_url: str):
        cfg = self._cfg()
        key = _key(base_url)
        for server_key, server in cfg["servers"].items():
            if _key(server["endpoint"]) == key:
                phases = server.get("phases") or []
                return server_key, (phases[0] if phases else None), server
        return None, None, None

    def handles_endpoint(self, base_url: str) -> bool:
        try:
            server_key, _, _ = self._phase_for_endpoint(base_url)
        except LifecycleRefusal:
            return False  # config unavailable: degrade to today's behavior
        return server_key is not None

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "current": self._current,
                "users": dict(self._users),
                "queue": [{"phase": e.phase, "server": e.server,
                           "reason": e.reason} for e in self._queue],
                "switched_at": self._switched_at,
            }

    def note_released(self, server_key: str) -> None:
        """Orchestrator hook: the server was released/fail-closed underneath
        us; drop the grant so the next acquire re-ensures residency."""
        with self._lock:
            if self._current == server_key or self._current is None:
                self._current = None
                self._ready[server_key] = True

    def _queue_remove(self, entry: _ArbEntry) -> None:
        try:
            self._queue.remove(entry)
        except ValueError:
            pass

    def _release_user(self, server_key: str) -> None:
        with self._lock:
            if self._users.get(server_key, 0) > 0:
                self._users[server_key] -= 1

    def _audit(self, tag: str, action: str, target: str, reason: str,
               before: str = "-", outcome: str = "-",
               duration_s: float | None = None) -> None:
        self.orch._audit(tag, action=action, target=target, reason=reason,
                         before=before, outcome=outcome,
                         duration_s=duration_s)

    # ---------------------------------------------------------------- grant

    def begin_use(self, phase: str, reason: str = "dispatch",
                  timeout: float | None = None,
                  requeue_head: bool = False) -> dict:
        """Acquire the grant for a phase; blocks (queued) until granted.

        ``requeue_head`` (AGG25 P1-7): a switching lease that failed and is
        retrying re-enters the queue at the FRONT — it keeps the FIFO
        position it earned by waiting first.

        Raises LifecycleRefusal("phase_queue_timeout") when the wait exceeds
        the queue timeout, or "unknown_phase" for an unmapped phase.
        """
        cfg = self._cfg()
        server_key, server = self._server_for_phase(cfg, phase)
        if server is None:
            raise LifecycleRefusal("unknown_phase",
                                   f"phase={phase!r} not mapped to a managed "
                                   "server")
        dwell = self._dwell(cfg)
        poll = self._poll(cfg)
        deadline = self.clock() + (self._queue_timeout(cfg)
                                   if timeout is None else float(timeout))
        entry = _ArbEntry(server_key, phase, reason)
        ensure_required = False
        waited = 0.0
        while True:
            now = self.clock()
            nap = poll
            with self._lock:
                if self._current == server_key:
                    self._queue_remove(entry)
                    self._users[server_key] = \
                        self._users.get(server_key, 0) + 1
                    waited = (now - entry.enqueued_at
                              if entry.enqueued_at is not None else 0.0)
                    break
                dwell_ok = (self._switched_at is None
                            or now - self._switched_at >= dwell)
                busy = sum(self._users.values())
                head = (not self._queue) or self._queue[0] is entry
                if busy == 0 and head and dwell_ok:
                    self._queue_remove(entry)
                    prev = self._current
                    self._current = server_key
                    self._users[server_key] = \
                        self._users.get(server_key, 0) + 1
                    waited = (now - entry.enqueued_at
                              if entry.enqueued_at is not None else 0.0)
                    if prev != server_key:
                        self._switched_at = now
                        self._ready[server_key] = False
                        self._ready_error.pop(server_key, None)
                        ensure_required = True
                        self._audit(
                            "arbiter/switch", action="phase_switch",
                            target=f"{phase}@{server_key}", reason=reason,
                            before=f"current={prev}",
                            outcome=f"granted, queued={len(self._queue)}")
                    break
                if entry.enqueued_at is None:
                    entry.enqueued_at = now
                    if requeue_head and self._queue:
                        self._queue.appendleft(entry)
                    else:
                        self._queue.append(entry)
                    self._audit(
                        "arbiter/queue", action="queue_enter",
                        target=f"{phase}@{server_key}", reason=reason,
                        before=f"current={self._current}, users={busy}",
                        outcome=("requeued at front (position kept)"
                                 if requeue_head else
                                 f"queued at position {len(self._queue)}"))
                if now >= deadline:
                    self._queue_remove(entry)
                    waited = (now - entry.enqueued_at
                              if entry.enqueued_at is not None else 0.0)
                    self._audit(
                        "arbiter/timeout", action="queue_timeout",
                        target=f"{phase}@{server_key}", reason=reason,
                        before=f"current={self._current}, users={busy}",
                        outcome=f"queue_timeout after {waited:.0f}s",
                        duration_s=waited)
                    raise LifecycleRefusal(
                        "phase_queue_timeout",
                        f"phase={phase} queue_timeout after {waited:.0f}s "
                        f"(current={self._current}, "
                        f"queue={len(self._queue)})")
                if (self._switched_at is not None
                        and now - self._switched_at < dwell):
                    nap = min(nap, dwell - (now - self._switched_at) + 0.05)
            nap = min(max(0.05, nap), max(0.05, deadline - self.clock()))
            self.sleep(nap)

        # switcher runs ensure() itself in lease(); same-server joiners wait
        # for that load to finish instead of racing it
        if not ensure_required:
            err = self._wait_ready(server_key, deadline)
            if err is not None:
                self._release_user(server_key)
                if err == "phase_queue_timeout":
                    raise LifecycleRefusal(
                        "phase_queue_timeout",
                        f"phase={phase} queue_timeout while "
                        f"server={server_key} was still loading")
                raise LifecycleRefusal(
                    err, f"ensure({phase}) failed on {server_key}; queued "
                         "dispatch aborted")
        if entry.enqueued_at is not None:
            total = self.clock() - entry.enqueued_at
            self._audit("arbiter/wait", action="queue_grant",
                        target=f"{phase}@{server_key}", reason=reason,
                        before="queued",
                        outcome="granted after wait", duration_s=total)
        return {"status": "granted", "phase": phase, "server": server_key,
                "ensure_required": ensure_required}

    def end_use(self, phase: str) -> None:
        cfg = self._cfg()
        server_key, _ = self._server_for_phase(cfg, phase)
        if server_key is None:
            return
        self._release_user(server_key)

    def _wait_ready(self, server_key: str, deadline: float) -> str | None:
        """Wait out a switch-load in flight; returns an error reason or None."""
        cfg = self._cfg()
        poll = self._poll(cfg)
        while True:
            with self._lock:
                if self._ready.get(server_key, True):
                    return self._ready_error.get(server_key)
            now = self.clock()
            if now >= deadline:
                return "phase_queue_timeout"
            self.sleep(min(poll, max(0.05, deadline - now)))

    # ---------------------------------------------------------------- lease

    @contextmanager
    def lease(self, phase: str, reason: str = "dispatch",
              timeout: float | None = None):
        """Grant + (on switch) ensure, then release on exit.

        Non-fast-path grants run ensure() — the load (with drain, A18)
        happens before the first dispatch of the new grant.  AGG25 P1-7: a
        failed switch does not surface to the user immediately — the lease
        re-enters the queue at the front (position kept) and retries ensure
        within the queue-timeout budget, up to
        ``arbitration_switch_retry_attempts``; every retry is audited.  Only
        a spent budget raises — phase_queue_timeout on wait exhaustion, the
        underlying refusal when the retry cap is hit.
        """
        cfg = self._cfg()
        attempts_limit = max(1, int(cfg.get(
            "arbitration_switch_retry_attempts", 3)))
        deadline = self.clock() + (self._queue_timeout(cfg)
                                   if timeout is None else float(timeout))
        grant = self.begin_use(phase, reason=reason, timeout=timeout)
        attempt = 0
        while True:
            try:
                if not grant["ensure_required"]:
                    yield grant
                    return
                result = self.orch.ensure(phase)
                with self._lock:
                    self._ready[grant["server"]] = True
                    if result.get("status") != "ok":
                        self._ready_error[grant["server"]] = result.get(
                            "reason", "ensure_failed")
                        self._current = None
                        # round25 P1-D: the failed switch never took effect,
                        # so the dwell gate must not keep both phases frozen
                        # until it expires — reset it with the grant.
                        self._switched_at = None
                if result.get("status") == "ok":
                    yield grant
                    return
            finally:
                self._release_user(grant["server"])
            # switch failed: retry within the budget unless spent
            attempt += 1
            fail_reason = result.get("reason", "ensure_failed")
            fail_detail = (result.get("detail")
                           or f"ensure({phase}) failed during arbitration")
            remaining = deadline - self.clock()
            if attempt >= attempts_limit or remaining <= 0:
                raise LifecycleRefusal(
                    fail_reason,
                    f"{fail_detail} (switch retried {attempt - 1}x, "
                    f"budget {'spent' if remaining <= 0 else 'capped'})")
            self._audit("arbiter/retry", action="switch_retry_requeue",
                        target=f"{phase}@{grant['server']}",
                        reason=fail_reason,
                        before=f"attempt {attempt} failed",
                        outcome=f"requeued at front, budget left "
                                f"{remaining:.0f}s")
            grant = self.begin_use(phase, reason=reason, timeout=remaining,
                                   requeue_head=True)

    @contextmanager
    def managed_lease(self, base_url: str, reason: str = "dispatch",
                      timeout: float | None = None):
        """Arbitration bracket for one managed dispatch: grant -> ensure ->
        sentinel counting -> dispatch body -> release (⑤: the old sentinel
        begin/end is merged into this same bracket)."""
        server_key, phase, server = self._phase_for_endpoint(base_url)
        if server_key is None:
            raise LifecycleRefusal("unknown_managed_endpoint",
                                   f"{base_url} is not a managed server")
        with self.lease(phase, reason=reason, timeout=timeout) as grant:
            gateway_dispatch_begin(server["endpoint"])
            try:
                yield grant
            finally:
                gateway_dispatch_end(server["endpoint"])

    # ----------------------------------------------------------------- warm

    def try_warm(self, phase: str, reason: str = "warm") -> dict:
        """Best-effort warm-up that can never flip a busy server.

        Same contract as the round21 direct ``ensure_phase`` warm when the
        phase already holds the (idle or active) grant; otherwise defers —
        warm requests must not queue behind users nor violate the dwell
        window.  Never raises.
        """
        try:
            cfg = self._cfg()
            server_key, server = self._server_for_phase(cfg, phase)
            if server is None:
                return {"status": "refused", "reason": "unknown_phase",
                        "detail": f"phase={phase!r}", "phase": phase}
            with self._lock:
                current = self._current
                busy = sum(self._users.values())
                queued = len(self._queue)
                dwell_pending = (
                    self._switched_at is not None
                    and self.clock() - self._switched_at
                    < self._dwell(cfg))
            if current == server_key:
                return self.orch.ensure(phase)
            if busy or queued or dwell_pending:
                self._audit("arbiter/warm-deferred", action="warm_deferred",
                            target=f"{phase}@{server_key}", reason=reason,
                            before=f"current={current}, users={busy}",
                            outcome=f"deferred (queued={queued}, "
                                    f"dwell_pending={dwell_pending})")
                return {"status": "deferred",
                        "reason": "arbitration_busy", "phase": phase}
            with self.lease(phase, reason=reason, timeout=0.0):
                pass
            return {"status": "ok", "phase": phase, "server": server_key,
                    "warm": True}
        except LifecycleRefusal as exc:
            return {"status": "refused", "reason": exc.reason,
                    "detail": exc.detail, "phase": phase}
        except Exception as exc:
            return {"status": "refused", "reason": "arbiter_error",
                    "detail": str(exc), "phase": phase}


# module-level arbiter singleton over the default orchestrator (tests may
# replace it via set_arbiter)

_arbiter_lock = threading.Lock()
_arbiter_singleton: PhaseArbiter | None = None


def _default_arbiter() -> PhaseArbiter | None:
    global _arbiter_singleton
    with _arbiter_lock:
        if _arbiter_singleton is None:
            try:
                _arbiter_singleton = PhaseArbiter(_default())
            except Exception:
                return None
        return _arbiter_singleton


def set_arbiter(arbiter: PhaseArbiter | None) -> None:
    """Point the module singleton at an explicit arbiter (tests/injection)."""
    global _arbiter_singleton
    with _arbiter_lock:
        _arbiter_singleton = arbiter


def warm_phase(phase: str, reason: str = "api_warmup") -> dict:
    """Best-effort, never-raising warm-up through the arbiter (main.py call
    sites keep their try/except best-effort contract)."""
    arb = _default_arbiter()
    if arb is None:
        return {"status": "refused", "reason": "arbiter_unavailable",
                "phase": phase}
    return arb.try_warm(phase, reason=reason)
