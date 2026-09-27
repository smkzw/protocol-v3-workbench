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
loads.  Direct external clients bypassing the gateway are covered by the
activity/lsof checks and the idle-recycle window only — a declared
residual limitation.

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

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason


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
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"} if data else {},
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
        """Why the server is busy right now (None = free)."""
        if sentinel_snapshot(server["endpoint"])["inflight"] > 0:
            return "busy_inflight"
        activity = server.get("activity_path")
        if activity:
            status, body = self._get(f"{server['endpoint']}{activity}")
            if status != 200:
                return "busy_activity_unreadable"
            active = body.get("total_active_requests")
            waiting = body.get("total_waiting_requests")
            if active is None or waiting is None:
                # field shape drifts between oMLX builds (risk 7): fall back
                # to the nested active_models counters
                inner = body.get("active_models") or {}
                active = inner.get("total_active_requests")
                waiting = inner.get("total_waiting_requests")
            if active is None or waiting is None:
                return "busy_activity_unreadable"
            if int(active) > 0 or int(waiting) > 0:
                return "busy_activity"
        count = self._established_count(server["port"])
        if count is None:
            return "busy_connections_unreadable"
        if count > 0:
            return "busy_connections"
        return None

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
            # ensure side: a load must never evict a busy sibling
            busy = self._busy_reason(server)
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
            busy_again = self._busy_reason(server)
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
        else:
            status, _ = self._get(f"{server['endpoint']}/health")
            if status != 200:
                started = self._start_server(server_key, server, phase)
                if started["status"] != "ok":
                    return started

        # mutual exclusion: the two resident models cannot coexist (budget
        # arithmetic in mem_probe.md: ~29.8GB + ~80GB ≈ 110GB on 128GB)
        for other_key, other in cfg["servers"].items():
            if other_key == server_key or not self._resident(other):
                continue
            drained = self._drain(other_key, other, phase,
                                  force=False, wait_for_zero=False)
            if drained["status"] != "ok":
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
            self._audit("action/release-done", action="nothing_to_release",
                        target=server_key, reason=reason, before="not resident",
                        outcome="noop")
            return {"status": "noop", "reason": "already_released",
                    "phase": phase}

        drained = self._drain(server_key, server, phase, force=force,
                              wait_for_zero=True)
        if drained["status"] != "ok":
            return drained
        return {"status": "ok", "phase": phase, "server": server_key,
                "released": True, "reason": reason}

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
        return {"status": "ok", "servers": servers,
                "binding_flags": self._binding_flags(cfg)}

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
