#!/usr/bin/env python3
"""Fail-closed service orchestration for one locked final-5x3 E2E run.

The tool prepares one new isolated runtime, builds a receipt-scoped immutable
frontend snapshot, starts the API, obtains the baseline clean-state receipt,
then serves the snapshot with Vite preview and verifies the frontend/backend
runtime contract. It never launches a tester, creates PASS evidence, modifies
product source, reuses a failed run, or writes to the shared product runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from zoneinfo import ZoneInfo


SCRIPT_PATH = Path(__file__).resolve()
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from scripts.qc import mw_final_5x3_harness as HARNESS  # noqa: E402
from scripts.qc import mw_isolated_runtime_baseline as BASELINE  # noqa: E402


ALLOWED_RUN_ROOT = (
    WORKSPACE_ROOT / "runs/execution/mw_final_5x3_harness_20260728"
)
SHARED_RUNTIME = WORKSPACE_ROOT.parents[1] / "runtime"
FORBIDDEN_WORKBENCH_RUNTIME = WORKSPACE_ROOT / "runtime"
RUNTIME_CONTRACT_PATH = (
    WORKSPACE_ROOT
    / "packages/contracts/workbench_contracts/runtime_contract.json"
)
FRONTEND_DIR = WORKSPACE_ROOT / "frontend"
VITE_ENTRY = FRONTEND_DIR / "node_modules/vite/bin/vite.js"
XCODE_PYTHON = Path(
    "/Applications/Xcode.app/Contents/Developer/usr/bin/python3"
)
SERVICE_RECEIPT_NAME = "SERVICE_RECEIPT.json"
CLEAN_RECEIPT_NAME = BASELINE.RECEIPT_NAME
LOCK_NAME = ".mw_final_5x3_e2e_runtime.lock"
RECEIPT_SCHEMA_VERSION = "mw-final-5x3-e2e-service-receipt-2026-07-28.1"
STABLE_PORTS = {5174, 8911}
PERSPECTIVES = {"lazy_medical_writer", "engineer"}
ACTIVE_STATES = {
    "PREPARED",
    "API_STARTED",
    "CLEAN_STATE_VERIFIED",
    "FRONTEND_STARTED",
    "RUNNING",
    "STOPPING",
}
TERMINAL_STATES = {"STOPPED", "FAILED_STOPPED"}
TARGET_FILE_MODE = 0o600
TARGET_DIRECTORY_MODE = 0o700
DEFAULT_START_TIMEOUT_SECONDS = 120.0
DEFAULT_STOP_TIMEOUT_SECONDS = 15.0
BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")
SCHEDULED_ROLE_SETTINGS_NAME = "SCHEDULED_AI_ROLE_BINDINGS.json"
PRODUCT_AI_ROUTE_RECEIPT_NAME = "PRODUCT_AI_ROUTE_RECEIPT.json"
PRODUCT_AI_ROUTES = {
    "qwen_night": {
        "provider": "alibaba_token_plan",
        "profile_id": "independent_ai__alibaba_qwen38",
        "model": "qwen3.8-max-preview",
        "window": "22:00-08:00 Asia/Shanghai",
    },
    "deepseek_day": {
        "provider": "deepseek",
        "profile_id": "independent_ai__deepseek_v4_pro",
        "model": "deepseek-v4-pro",
        "window": "08:00-22:00 Asia/Shanghai",
    },
}


class RuntimeOrchestratorError(RuntimeError):
    """Raised when an orchestration safety or verification gate fails."""


@dataclass
class Hooks:
    """Injectable operating-system boundary used by deterministic tests."""

    popen: Callable[..., Any] = subprocess.Popen
    fetch_json: Optional[
        Callable[[str, Optional[dict[str, str]], float], Any]
    ] = None
    listener_pids: Optional[Callable[[int], set[int]]] = None
    process_identity: Optional[Callable[[int], Optional[dict[str, str]]]] = None
    send_signal: Callable[[int, int], None] = os.kill
    sleep: Callable[[float], None] = time.sleep
    monotonic: Callable[[], float] = time.monotonic
    baseline_prepare: Callable[..., dict[str, Any]] = BASELINE.prepare_baseline
    baseline_verify_startup: Callable[..., dict[str, Any]] = BASELINE.verify_startup
    frontend_build: Optional[Callable[..., dict[str, Any]]] = None


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if ".." in expanded.parts:
        raise RuntimeOrchestratorError(f"path traversal is forbidden: {path}")
    return Path(os.path.abspath(os.fspath(expanded)))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _assert_no_symlink_components(path: Path) -> None:
    absolute = _absolute_path(path)
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if not os.path.lexists(current):
            break
        metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode):
            raise RuntimeOrchestratorError(
                f"symbolic links are forbidden: {current}"
            )
        if current != absolute and not stat.S_ISDIR(metadata.st_mode):
            raise RuntimeOrchestratorError(
                f"path component is not a directory: {current}"
            )


def _validated_test_root(path: Path) -> Path:
    root = _absolute_path(path)
    _assert_no_symlink_components(root)
    if not root.is_dir():
        raise RuntimeOrchestratorError(
            f"test run root must be an existing directory: {root}"
        )
    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    resolved = root.resolve(strict=True)
    if not _is_within(resolved, system_temp):
        raise RuntimeOrchestratorError(
            f"test run root must stay under system temp: {system_temp}"
        )
    return resolved


def _resolve_run_root(
    run_root: Path = ALLOWED_RUN_ROOT,
    *,
    test_run_root: Optional[Path] = None,
) -> Path:
    candidate = _absolute_path(run_root)
    _assert_no_symlink_components(candidate)
    allowed = ALLOWED_RUN_ROOT.resolve(strict=False)
    if test_run_root is None:
        if candidate.resolve(strict=False) != allowed:
            raise RuntimeOrchestratorError(
                f"run root must equal the locked root: {allowed}"
            )
    else:
        test_root = _validated_test_root(test_run_root)
        if candidate.resolve(strict=False) != test_root:
            raise RuntimeOrchestratorError(
                "test run root override must equal the declared system-temp root"
            )
    if not candidate.is_dir():
        raise RuntimeOrchestratorError(
            f"run root must be an existing directory: {candidate}"
        )
    resolved = candidate.resolve(strict=True)
    shared = SHARED_RUNTIME.resolve(strict=False)
    forbidden = FORBIDDEN_WORKBENCH_RUNTIME.resolve(strict=False)
    if resolved in {shared, forbidden} or _is_within(shared, resolved):
        raise RuntimeOrchestratorError(
            "run root cannot be the shared runtime or its parent alias"
        )
    return resolved


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeOrchestratorError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeOrchestratorError(f"expected JSON object: {path}")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256_file(path)))
        digest.update(b"\0")
    return digest.hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        os.fchmod(file_descriptor, TARGET_FILE_MODE)
        with os.fdopen(file_descriptor, "wb", closefd=True) as handle:
            file_descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
        os.chmod(path, TARGET_FILE_MODE)
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temporary_name and os.path.lexists(temporary_name):
            os.unlink(temporary_name)


def _product_ai_route_for(moment: Optional[datetime] = None) -> dict[str, str]:
    observed = moment or datetime.now(BEIJING_TIMEZONE)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=BEIJING_TIMEZONE)
    local = observed.astimezone(BEIJING_TIMEZONE)
    clock = local.timetz().replace(tzinfo=None)
    route_key = (
        "qwen_night"
        if clock >= datetime_time(22, 0) or clock < datetime_time(8, 0)
        else "deepseek_day"
    )
    return {
        **PRODUCT_AI_ROUTES[route_key],
        "route_key": route_key,
        "selected_at": local.isoformat(),
        "selection_policy": (
            "qwen3.8-max-preview 22:00-08:00; "
            "deepseek-v4-pro 08:00-22:00; Asia/Shanghai"
        ),
    }


def _prepare_scheduled_role_overlay(
    *,
    runtime: Path,
    run_dir: Path,
    moment: Optional[datetime] = None,
) -> dict[str, Any]:
    route = _product_ai_route_for(moment)
    settings = _read_json(runtime / "ai_provider_settings.json")
    roles = _read_json(runtime / "ai_role_bindings.json")
    profiles = {
        str(item.get("profile_id", "")): item
        for item in settings.get("profiles", [])
        if isinstance(item, dict)
    }
    profile = profiles.get(route["profile_id"])
    if profile is None:
        raise RuntimeOrchestratorError(
            f"scheduled comprehensive-AI profile is missing: {route['profile_id']}"
        )
    observed_identity = {
        "provider": str(profile.get("provider", "")),
        "model": str(profile.get("model", "")),
    }
    expected_identity = {
        "provider": route["provider"],
        "model": route["model"],
    }
    if observed_identity != expected_identity or profile.get("enabled") is not True:
        raise RuntimeOrchestratorError(
            "scheduled comprehensive-AI profile identity is unavailable or disabled"
        )
    bindings = roles.get("bindings")
    if not isinstance(bindings, dict) or not isinstance(
        bindings.get("independent_ai"), dict
    ):
        raise RuntimeOrchestratorError(
            "AI role settings are missing the comprehensive-AI binding"
        )
    independent = dict(bindings["independent_ai"])
    independent.update(
        {
            "role_id": "independent_ai",
            "profile_id": route["profile_id"],
            "model": route["model"],
            "enabled": True,
            "capability_status": "unverified",
            "capability_reason": "",
            "capability_evidence_profile_id": "",
            "capability_evidence_model": "",
            "capability_verified_at": "",
        }
    )
    scheduled_roles = {
        **roles,
        "revision": int(roles.get("revision", 0)) + 1,
        "bindings": {**bindings, "independent_ai": independent},
    }
    overlay_path = run_dir / SCHEDULED_ROLE_SETTINGS_NAME
    receipt_path = run_dir / PRODUCT_AI_ROUTE_RECEIPT_NAME
    if os.path.lexists(overlay_path) or os.path.lexists(receipt_path):
        raise RuntimeOrchestratorError(
            "scheduled product-AI route files already exist; choose a new round"
        )
    _atomic_write_json(overlay_path, scheduled_roles)
    receipt = {
        "schema_version": "mw-product-ai-test-route-2026-07-29.1",
        "status": "SCHEDULED_ROLE_OVERLAY_READY",
        "role_id": "independent_ai",
        **route,
        "overlay_path": str(overlay_path.resolve(strict=True)),
        "overlay_sha256": _sha256_file(overlay_path),
        "source_role_settings_sha256": _sha256_file(
            runtime / "ai_role_bindings.json"
        ),
        "source_provider_settings_sha256": _sha256_file(
            runtime / "ai_provider_settings.json"
        ),
        "source_runtime_modified": False,
    }
    _atomic_write_json(receipt_path, receipt)
    return {
        **route,
        "overlay_path": overlay_path,
        "receipt_path": receipt_path,
        "overlay_sha256": receipt["overlay_sha256"],
    }


def _atomic_update_receipt(
    path: Path,
    receipt: dict[str, Any],
    runtime_root: Optional[Path],
) -> None:
    if path.name != SERVICE_RECEIPT_NAME:
        raise RuntimeOrchestratorError("unexpected service receipt filename")
    _assert_no_symlink_components(path.parent)
    if runtime_root is not None:
        encoded = json.dumps(
            receipt, ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        for filename in ("ai_provider_secrets.json", "ai_provider_master.key"):
            secret_path = runtime_root / filename
            if secret_path.is_file():
                secret = secret_path.read_bytes()
                if secret and secret in encoded:
                    raise RuntimeOrchestratorError(
                        f"service receipt would embed content from {filename}"
                    )
    _atomic_write_json(path, receipt)
    if stat.S_IMODE(path.stat().st_mode) != TARGET_FILE_MODE:
        raise RuntimeOrchestratorError("service receipt mode must be 0600")


def _lifecycle_event(state: str, detail: str) -> dict[str, str]:
    return {
        "state": state,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": detail,
    }


def _transition(
    receipt_path: Path,
    receipt: dict[str, Any],
    state: str,
    detail: str,
    *,
    runtime_root: Optional[Path],
) -> None:
    receipt["state"] = state
    receipt["updated_at"] = datetime.now(timezone.utc).isoformat()
    receipt.setdefault("lifecycle", []).append(_lifecycle_event(state, detail))
    _atomic_update_receipt(receipt_path, receipt, runtime_root)


@contextlib.contextmanager
def _root_lock(run_root: Path) -> Iterator[None]:
    lock_path = run_root / LOCK_NAME
    _assert_no_symlink_components(lock_path.parent)
    if os.path.lexists(lock_path) and stat.S_ISLNK(os.lstat(lock_path).st_mode):
        raise RuntimeOrchestratorError(
            f"service lock cannot be a symbolic link: {lock_path}"
        )
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, TARGET_FILE_MODE)
    except OSError as exc:
        raise RuntimeOrchestratorError(
            f"cannot open the service orchestration lock: {lock_path}"
        ) from exc
    try:
        os.fchmod(descriptor, TARGET_FILE_MODE)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _resolve_run_context(
    *,
    round_id: str,
    slot: str,
    perspective: str,
    run_root: Path = ALLOWED_RUN_ROOT,
    test_run_root: Optional[Path] = None,
) -> dict[str, Path]:
    root = _resolve_run_root(run_root, test_run_root=test_run_root)
    if not HARNESS.ROUND_ID_RE.fullmatch(round_id):
        raise RuntimeOrchestratorError(f"invalid round id: {round_id}")
    if slot not in HARNESS.LOCKED_SLOTS:
        raise RuntimeOrchestratorError(f"slot is not in the locked matrix: {slot}")
    if perspective not in PERSPECTIVES:
        raise RuntimeOrchestratorError(
            f"perspective must be one of {sorted(PERSPECTIVES)}"
        )
    round_dir = root / "rounds" / round_id
    run_dir = round_dir / "slots" / slot / perspective
    for path in (round_dir, run_dir):
        _assert_no_symlink_components(path)
        if not path.is_dir():
            raise RuntimeOrchestratorError(
                f"prepared harness directory is missing: {path}"
            )
    manifest = _read_json(round_dir / "ROUND_MANIFEST.json")
    if manifest.get("round_id") != round_id:
        raise RuntimeOrchestratorError("round manifest identity mismatch")
    if manifest.get("status") != "PREPARED_NOT_EXECUTED":
        raise RuntimeOrchestratorError(
            "round manifest must remain PREPARED_NOT_EXECUTED before service start"
        )
    expected = _read_json(run_dir / "EXPECTED_EVIDENCE.json")
    if (
        expected.get("slot") != slot
        or expected.get("perspective") != perspective
        or expected.get("status") != "NOT_STARTED"
    ):
        raise RuntimeOrchestratorError("run evidence contract identity mismatch")
    resolved_run = run_dir.resolve(strict=True)
    if not _is_within(resolved_run, root):
        raise RuntimeOrchestratorError("run directory escapes the locked run root")
    runtime = resolved_run / "runtime"
    for forbidden in (
        SHARED_RUNTIME.resolve(strict=False),
        FORBIDDEN_WORKBENCH_RUNTIME.resolve(strict=False),
    ):
        if runtime.resolve(strict=False) == forbidden:
            raise RuntimeOrchestratorError("isolated runtime aliases a shared runtime")
    return {
        "run_root": root,
        "round_dir": round_dir.resolve(strict=True),
        "run_dir": resolved_run,
        "runtime": runtime,
        "receipt": resolved_run / SERVICE_RECEIPT_NAME,
        "clean_receipt": resolved_run / CLEAN_RECEIPT_NAME,
        "browser_profile": resolved_run / "browser_profile",
        "downloads": resolved_run / "downloads",
        "logs": resolved_run / "service_logs",
        "frontend_snapshot": resolved_run / "frontend_snapshot",
    }


def _default_listener_pids(port: int) -> set[int]:
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    try:
        result = subprocess.run(
            [
                lsof,
                "-nP",
                "-t",
                f"-iTCP:{port}",
                "-sTCP:LISTEN",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeOrchestratorError(
            f"cannot inspect local listener on port {port}"
        ) from exc
    if result.returncode not in {0, 1}:
        raise RuntimeOrchestratorError(
            f"listener inspection failed on port {port}: {result.returncode}"
        )
    return {
        int(line.strip())
        for line in result.stdout.splitlines()
        if line.strip().isdigit()
    }


def _default_process_identity(pid: int) -> Optional[dict[str, str]]:
    if pid <= 0:
        return None
    try:
        start = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        command = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeOrchestratorError(
            f"cannot inspect process identity for PID {pid}"
        ) from exc
    start_text = start.stdout.strip()
    command_text = command.stdout.strip()
    if (
        start.returncode != 0
        or command.returncode != 0
        or not start_text
        or not command_text
    ):
        return None
    return {
        "start_marker": start_text,
        "command_sha256": hashlib.sha256(
            command_text.encode("utf-8")
        ).hexdigest(),
    }


def _listeners(hooks: Hooks, port: int) -> set[int]:
    inspector = hooks.listener_pids or _default_listener_pids
    return set(inspector(port))


def _identity(hooks: Hooks, pid: int) -> Optional[dict[str, str]]:
    inspector = hooks.process_identity or _default_process_identity
    return inspector(pid)


def _default_fetch_json(
    url: str,
    headers: Optional[dict[str, str]],
    timeout: float,
) -> Any:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is None
    ):
        raise RuntimeOrchestratorError(f"only explicit localhost HTTP is allowed: {url}")
    request = urllib.request.Request(url, headers=headers or {})
    opener = urllib.request.build_opener(BASELINE._RejectRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeOrchestratorError(
                    f"GET {url} returned HTTP {response.status}"
                )
            raw = response.read()
    except (OSError, urllib.error.URLError) as exc:
        raise RuntimeOrchestratorError(f"GET {url} failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeOrchestratorError(f"GET {url} returned invalid JSON") from exc


def _fetch(
    hooks: Hooks,
    url: str,
    headers: Optional[dict[str, str]] = None,
    timeout: float = 5.0,
) -> Any:
    fetcher = hooks.fetch_json or _default_fetch_json
    return fetcher(url, headers, timeout)


def _wait_for_json(
    hooks: Hooks,
    url: str,
    *,
    process: Any,
    timeout_seconds: float,
    headers: Optional[dict[str, str]] = None,
) -> Any:
    deadline = hooks.monotonic() + timeout_seconds
    last_error: Optional[Exception] = None
    while hooks.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeOrchestratorError(
                f"service exited before readiness: {url}"
            )
        try:
            return _fetch(hooks, url, headers=headers, timeout=2.0)
        except Exception as exc:  # readiness polling preserves the last cause
            last_error = exc
            hooks.sleep(0.2)
    raise RuntimeOrchestratorError(
        f"timed out waiting for {url}: {last_error}"
    )


def _receipt_is_proven_stopped(
    hooks: Hooks,
    receipt_path: Path,
    receipt: dict[str, Any],
) -> bool:
    state = receipt.get("state")
    if state not in ACTIVE_STATES | TERMINAL_STATES:
        raise RuntimeOrchestratorError(
            f"receipt state cannot prove runtime termination: {receipt_path}"
        )
    ports = receipt.get("ports")
    processes = receipt.get("processes")
    if not isinstance(ports, dict) or not isinstance(processes, dict):
        raise RuntimeOrchestratorError(
            f"receipt cannot prove runtime termination: {receipt_path}"
        )
    for name, port_key in (("api", "backend"), ("frontend", "frontend")):
        port = ports.get(port_key)
        if not isinstance(port, int):
            raise RuntimeOrchestratorError(
                f"receipt has invalid {port_key} port: {receipt_path}"
            )
        if _listeners(hooks, port):
            return False
        process_record = processes.get(name)
        if process_record is None:
            if state in ACTIVE_STATES:
                raise RuntimeOrchestratorError(
                    f"active receipt lacks the {name} process identity: {receipt_path}"
                )
            continue
        if not isinstance(process_record, dict):
            raise RuntimeOrchestratorError(
                f"receipt has invalid {name} process record: {receipt_path}"
            )
        pid = process_record.get("pid")
        expected_identity = process_record.get("identity")
        if (
            not isinstance(pid, int)
            or pid <= 0
            or not isinstance(expected_identity, dict)
        ):
            raise RuntimeOrchestratorError(
                f"receipt has invalid {name} process identity: {receipt_path}"
            )
        observed = _identity(hooks, pid)
        if _same_identity(expected_identity, observed):
            return False
    return True


def _claimed_ports(
    run_root: Path,
    hooks: Hooks,
    *,
    excluded_receipt: Optional[Path] = None,
) -> dict[int, Path]:
    claimed: dict[int, Path] = {}
    for receipt_path in run_root.rglob(SERVICE_RECEIPT_NAME):
        _assert_no_symlink_components(receipt_path)
        if excluded_receipt is not None and receipt_path == excluded_receipt:
            continue
        try:
            receipt = _read_json(receipt_path)
            if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
                raise RuntimeOrchestratorError(
                    f"unsupported service receipt schema: {receipt_path}"
                )
            if _receipt_is_proven_stopped(hooks, receipt_path, receipt):
                continue
        except Exception as exc:
            raise RuntimeOrchestratorError(
                "another slot/perspective runtime cannot be proven stopped; "
                f"run stop first before starting a new runtime: {receipt_path}"
            ) from exc
        ports = receipt.get("ports")
        if not isinstance(ports, dict):
            raise RuntimeOrchestratorError(
                "another slot/perspective runtime cannot be proven stopped; "
                f"run stop first before starting a new runtime: {receipt_path}"
            )
        for key in ("backend", "frontend"):
            port = ports.get(key)
            if not isinstance(port, int):
                raise RuntimeOrchestratorError(
                    "another slot/perspective runtime cannot be proven stopped; "
                    f"run stop first before starting a new runtime: {receipt_path}"
                )
            if port in claimed:
                raise RuntimeOrchestratorError(
                    f"duplicate active port claim {port}: {claimed[port]}, {receipt_path}"
                )
            claimed[port] = receipt_path
    return claimed


def _assert_serial_runtime_available(
    run_root: Path,
    hooks: Hooks,
    *,
    current_receipt: Path,
) -> None:
    claimed = _claimed_ports(
        run_root,
        hooks,
        excluded_receipt=current_receipt,
    )
    if not claimed:
        return
    active_receipts = sorted({str(path) for path in claimed.values()})
    raise RuntimeOrchestratorError(
        "another slot/perspective runtime is active; run stop first before "
        f"starting a new runtime: {', '.join(active_receipts)}"
    )


def _reserve_port(
    requested: Optional[int],
    *,
    claimed: dict[int, Path],
) -> tuple[int, socket.socket]:
    if requested is not None and requested != 0:
        if not isinstance(requested, int) or requested < 1024 or requested > 65535:
            raise RuntimeOrchestratorError(f"invalid localhost port: {requested}")
        if requested in STABLE_PORTS:
            raise RuntimeOrchestratorError(
                f"stable product port is forbidden for E2E isolation: {requested}"
            )
        if requested in claimed:
            raise RuntimeOrchestratorError(
                f"port {requested} is claimed by {claimed[requested]}"
            )
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
    try:
        reservation.bind(("127.0.0.1", 0 if requested in {None, 0} else requested))
        reservation.listen(1)
        port = int(reservation.getsockname()[1])
        if port in STABLE_PORTS or port in claimed:
            raise RuntimeOrchestratorError(
                f"allocated port is forbidden or already claimed: {port}"
            )
        return port, reservation
    except OSError as exc:
        reservation.close()
        raise RuntimeOrchestratorError(
            f"localhost port is unavailable: {requested or 'automatic'}"
        ) from exc
    except Exception:
        reservation.close()
        raise


def _validate_xcode_python(path: Path) -> Path:
    resolved = _absolute_path(path)
    if resolved != XCODE_PYTHON:
        raise RuntimeOrchestratorError(
            f"API Python must be the locked Xcode Python: {XCODE_PYTHON}"
        )
    _assert_no_symlink_components(resolved.parent)
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeOrchestratorError(f"Xcode Python is not executable: {resolved}")
    try:
        result = subprocess.run(
            [str(resolved), "-c", "import sys; print('.'.join(map(str, sys.version_info[:2])))"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
            env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeOrchestratorError("cannot verify Xcode Python 3.9") from exc
    if result.stdout.strip() != "3.9":
        raise RuntimeOrchestratorError(
            f"Xcode Python must be 3.9; observed {result.stdout.strip()}"
        )
    return resolved


def _resolve_node(node_path: Optional[Path]) -> Path:
    raw = str(node_path) if node_path is not None else shutil.which("node")
    if not raw:
        raise RuntimeOrchestratorError("Node.js executable was not found")
    candidate = _absolute_path(Path(raw))
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RuntimeOrchestratorError(
            f"Node.js path cannot be resolved: {candidate}"
        ) from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeOrchestratorError(f"Node.js is not executable: {candidate}")
    if not VITE_ENTRY.is_file():
        raise RuntimeOrchestratorError(f"Vite entry is missing: {VITE_ENTRY}")
    return resolved


def _build_frontend_snapshot(
    *,
    node: Path,
    output_dir: Path,
    backend_port: int,
    log_path: Path,
) -> dict[str, Any]:
    if os.path.lexists(output_dir):
        raise RuntimeOrchestratorError(
            f"frontend snapshot already exists: {output_dir}"
        )
    environment = dict(os.environ)
    environment["VITE_API_PROXY_TARGET"] = f"http://127.0.0.1:{backend_port}"
    command = [
        str(node),
        str(VITE_ENTRY),
        "build",
        "--outDir",
        str(output_dir),
        "--emptyOutDir",
    ]
    try:
        with log_path.open("ab", buffering=0) as log_handle:
            completed = subprocess.run(
                command,
                cwd=FRONTEND_DIR,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=300,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeOrchestratorError(
            f"frontend snapshot build failed: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise RuntimeOrchestratorError(
            f"frontend snapshot build exited {completed.returncode}; see {log_path}"
        )
    manifest = output_dir / "runtime-build.json"
    if not manifest.is_file():
        raise RuntimeOrchestratorError(
            "frontend snapshot lacks runtime-build.json"
        )
    return {
        "command": _command_summary(command),
        "tree_sha256": _sha256_tree(output_dir),
        "runtime_build_sha256": _sha256_file(manifest),
    }


def _command_summary(command: list[str]) -> dict[str, Any]:
    return {
        "executable": command[0],
        "argv": command[1:],
        "sha256": _canonical_sha256(command),
    }


def _process_receipt(
    hooks: Hooks,
    process: Any,
) -> dict[str, Any]:
    pid = int(process.pid)
    identity = _identity(hooks, pid)
    if identity is None:
        raise RuntimeOrchestratorError(
            f"cannot capture started process identity for PID {pid}"
        )
    return {"pid": pid, "identity": identity}


def _runtime_identity_hash(
    runtime: Path,
    clean_receipt: Path,
    scheduled_role_overlay: Optional[Path] = None,
) -> dict[str, str]:
    manifest = runtime / BASELINE.MANIFEST_NAME
    manifest_sha = _sha256_file(manifest)
    clean_sha = _sha256_file(clean_receipt)
    identity = {
        "runtime_resolved": str(runtime.resolve(strict=True)),
        "baseline_manifest_sha256": manifest_sha,
        "clean_state_receipt_sha256": clean_sha,
    }
    if scheduled_role_overlay is not None:
        identity["scheduled_role_overlay_sha256"] = _sha256_file(
            scheduled_role_overlay
        )
    return {
        **identity,
        "runtime_identity_sha256": _canonical_sha256(identity),
    }


def _verify_contract(
    hooks: Hooks,
    *,
    backend_port: int,
    frontend_port: int,
    frontend_manifest: Any,
) -> dict[str, Any]:
    contract = _read_json(RUNTIME_CONTRACT_PATH)
    if not isinstance(frontend_manifest, dict):
        raise RuntimeOrchestratorError("/runtime-build.json must be an object")
    expected_frontend = {
        "runtimeContractSchema": contract["schema_version"],
        "apiContractVersion": contract["api_contract_version"],
        "clientContractHeader": contract["client_contract_header"],
    }
    for key, expected in expected_frontend.items():
        if frontend_manifest.get(key) != expected:
            raise RuntimeOrchestratorError(
                f"frontend runtime-build mismatch for {key}"
            )
    backend_build = frontend_manifest.get("expectedBackendBuildId")
    frontend_build = frontend_manifest.get("frontendBuildId")
    if not isinstance(backend_build, str) or not backend_build.startswith("api-"):
        raise RuntimeOrchestratorError(
            "frontend runtime-build lacks expectedBackendBuildId"
        )
    if not isinstance(frontend_build, str) or not frontend_build.startswith("web-"):
        raise RuntimeOrchestratorError("frontend runtime-build lacks frontendBuildId")
    headers = {
        str(contract["client_contract_header"]): str(
            contract["api_contract_version"]
        ),
        "X-Workbench-Frontend-Build": frontend_build,
    }
    direct = _fetch(
        hooks,
        f"http://127.0.0.1:{backend_port}/api/runtime-readiness",
        headers=headers,
    )
    proxied = _fetch(
        hooks,
        f"http://127.0.0.1:{frontend_port}/api/runtime-readiness",
        headers=headers,
    )
    for label, payload in (("backend", direct), ("frontend proxy", proxied)):
        if not isinstance(payload, dict):
            raise RuntimeOrchestratorError(
                f"{label} runtime readiness must be an object"
            )
        expected = {
            "ready": True,
            "runtime_contract_schema": contract["schema_version"],
            "api_contract_version": contract["api_contract_version"],
            "backend_build_id": backend_build,
            "runtime_schema_version": BASELINE.EXPECTED_RUNTIME_SCHEMA_VERSION,
        }
        observed = {key: payload.get(key) for key in expected}
        if observed != expected:
            raise RuntimeOrchestratorError(
                f"{label} runtime readiness mismatch: {observed}"
            )
    return {
        "runtime_contract_schema": contract["schema_version"],
        "api_contract_version": contract["api_contract_version"],
        "backend_build_id": backend_build,
        "frontend_build_id": frontend_build,
        "direct_backend_ready": True,
        "frontend_proxy_ready": True,
    }


def _same_identity(
    expected: dict[str, str],
    observed: Optional[dict[str, str]],
) -> bool:
    return observed is not None and observed == expected


def _stop_one(
    hooks: Hooks,
    *,
    process_record: Optional[dict[str, Any]],
    port: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    _preflight_stop_one(
        hooks,
        process_record=process_record,
        port=port,
    )
    listeners_before = _listeners(hooks, port)
    if not process_record:
        if listeners_before:
            raise RuntimeOrchestratorError(
                f"port {port} is occupied without a receipt PID: {sorted(listeners_before)}"
            )
        return {"pid": None, "stopped": True, "already_absent": True}
    pid = process_record.get("pid")
    expected_identity = process_record.get("identity")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(expected_identity, dict):
        raise RuntimeOrchestratorError("service receipt contains an invalid process record")
    observed = _identity(hooks, pid)
    if observed is None:
        if listeners_before:
            raise RuntimeOrchestratorError(
                f"receipt PID {pid} is absent but port {port} is occupied by "
                f"{sorted(listeners_before)}"
            )
        return {"pid": pid, "stopped": True, "already_absent": True}
    if not _same_identity(expected_identity, observed):
        raise RuntimeOrchestratorError(
            f"PID {pid} identity changed; refusing to signal a reused PID"
        )
    if listeners_before and listeners_before != {pid}:
        raise RuntimeOrchestratorError(
            f"port {port} is not owned exclusively by receipt PID {pid}: "
            f"{sorted(listeners_before)}"
        )
    hooks.send_signal(pid, signal.SIGTERM)
    deadline = hooks.monotonic() + timeout_seconds
    while hooks.monotonic() < deadline:
        if _identity(hooks, pid) is None:
            break
        hooks.sleep(0.1)
    if _identity(hooks, pid) is not None:
        if not _same_identity(expected_identity, _identity(hooks, pid)):
            raise RuntimeOrchestratorError(
                f"PID {pid} identity changed during shutdown"
            )
        hooks.send_signal(pid, signal.SIGKILL)
        deadline = hooks.monotonic() + min(timeout_seconds, 5.0)
        while hooks.monotonic() < deadline:
            if _identity(hooks, pid) is None:
                break
            hooks.sleep(0.1)
    if _identity(hooks, pid) is not None:
        raise RuntimeOrchestratorError(f"receipt PID {pid} did not stop")
    listeners_after = _listeners(hooks, port)
    if listeners_after:
        raise RuntimeOrchestratorError(
            f"port {port} was not released after stopping PID {pid}: "
            f"{sorted(listeners_after)}"
        )
    return {"pid": pid, "stopped": True, "already_absent": False}


def _preflight_stop_one(
    hooks: Hooks,
    *,
    process_record: Optional[dict[str, Any]],
    port: int,
) -> None:
    listeners = _listeners(hooks, port)
    if not process_record:
        if listeners:
            raise RuntimeOrchestratorError(
                f"port {port} is occupied without a receipt PID: {sorted(listeners)}"
            )
        return
    pid = process_record.get("pid")
    expected_identity = process_record.get("identity")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(expected_identity, dict):
        raise RuntimeOrchestratorError("service receipt contains an invalid process record")
    observed = _identity(hooks, pid)
    if observed is None:
        if listeners:
            raise RuntimeOrchestratorError(
                f"receipt PID {pid} is absent but port {port} is occupied by "
                f"{sorted(listeners)}"
            )
        return
    if not _same_identity(expected_identity, observed):
        raise RuntimeOrchestratorError(
            f"PID {pid} identity changed; refusing to signal a reused PID"
        )
    if listeners and listeners != {pid}:
        raise RuntimeOrchestratorError(
            f"port {port} is not owned exclusively by receipt PID {pid}: "
            f"{sorted(listeners)}"
        )


def _terminate_spawned_process(process: Any, hooks: Hooks) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except Exception:
        return
    deadline = hooks.monotonic() + 5.0
    while hooks.monotonic() < deadline and process.poll() is None:
        hooks.sleep(0.1)
    if process.poll() is None:
        try:
            process.kill()
        except Exception:
            return


def start(
    *,
    round_id: str,
    slot: str,
    perspective: str,
    backend_port: Optional[int] = None,
    frontend_port: Optional[int] = None,
    run_root: Path = ALLOWED_RUN_ROOT,
    test_run_root: Optional[Path] = None,
    source_runtime: Optional[Path] = None,
    test_source_root: Optional[Path] = None,
    test_target_root: Optional[Path] = None,
    xcode_python: Path = XCODE_PYTHON,
    node_path: Optional[Path] = None,
    start_timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
    hooks: Optional[Hooks] = None,
    validate_python: bool = True,
) -> dict[str, Any]:
    active_hooks = hooks or Hooks()
    context = _resolve_run_context(
        round_id=round_id,
        slot=slot,
        perspective=perspective,
        run_root=run_root,
        test_run_root=test_run_root,
    )
    receipt_path = context["receipt"]
    runtime = context["runtime"]
    if backend_port == frontend_port and backend_port not in {None, 0}:
        raise RuntimeOrchestratorError("backend and frontend ports must be unique")
    if start_timeout_seconds <= 0:
        raise RuntimeOrchestratorError("start timeout must be positive")

    api_process = None
    frontend_process = None
    backend_reservation: Optional[socket.socket] = None
    frontend_reservation: Optional[socket.socket] = None
    receipt: Optional[dict[str, Any]] = None
    api_log_handle = None
    frontend_log_handle = None

    with _root_lock(context["run_root"]):
        if os.path.lexists(receipt_path):
            raise RuntimeOrchestratorError(
                f"service receipt already exists; choose a new round: {receipt_path}"
            )
        if os.path.lexists(runtime):
            raise RuntimeOrchestratorError(
                f"runtime already exists; failed/history runs cannot be reused: {runtime}"
            )
        _assert_serial_runtime_available(
            context["run_root"],
            active_hooks,
            current_receipt=receipt_path,
        )
        claimed: dict[int, Path] = {}
        backend, backend_reservation = _reserve_port(
            backend_port, claimed=claimed
        )
        claimed[backend] = receipt_path
        frontend, frontend_reservation = _reserve_port(
            frontend_port, claimed=claimed
        )
        try:
            python = (
                _validate_xcode_python(xcode_python)
                if validate_python
                else _absolute_path(xcode_python)
            )
            node = _resolve_node(node_path)
            api_command = [
                str(python),
                "-m",
                "uvicorn",
                "services.api.app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(backend),
            ]
            frontend_command = [
                str(node),
                str(VITE_ENTRY),
                "preview",
                "--host",
                "127.0.0.1",
                "--port",
                str(frontend),
                "--strictPort",
                "--outDir",
                str(context["frontend_snapshot"]),
            ]

            active_hooks.baseline_prepare(
                target_runtime=runtime,
                source_runtime=source_runtime,
                test_source_root=test_source_root,
                test_target_root=test_target_root,
            )
            product_ai_route = (
                _prepare_scheduled_role_overlay(
                    runtime=runtime,
                    run_dir=context["run_dir"],
                )
                if hooks is None
                else None
            )
            for path in (
                context["browser_profile"],
                context["downloads"],
                context["logs"],
            ):
                path.mkdir(mode=TARGET_DIRECTORY_MODE)
                os.chmod(path, TARGET_DIRECTORY_MODE)
            for log_name in ("api.log", "frontend.log"):
                log_path = context["logs"] / log_name
                descriptor = os.open(
                    log_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    TARGET_FILE_MODE,
                )
                os.close(descriptor)
            frontend_build_log = context["logs"] / "frontend_build.log"
            descriptor = os.open(
                frontend_build_log,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                TARGET_FILE_MODE,
            )
            os.close(descriptor)
            if active_hooks.frontend_build is not None:
                frontend_snapshot = active_hooks.frontend_build(
                    node=node,
                    output_dir=context["frontend_snapshot"],
                    backend_port=backend,
                    log_path=frontend_build_log,
                )
            else:
                frontend_snapshot = _build_frontend_snapshot(
                    node=node,
                    output_dir=context["frontend_snapshot"],
                    backend_port=backend,
                    log_path=frontend_build_log,
                )
            if hooks is None:
                config = HARNESS.read_json(HARNESS.DEFAULT_CONFIG_PATH)
                source_receipts = HARNESS.verify_authoritative_sources(
                    config,
                    WORKSPACE_ROOT,
                )
            else:
                source_receipts = []

            now = datetime.now(timezone.utc).isoformat()
            receipt = {
                "schema_version": RECEIPT_SCHEMA_VERSION,
                "state": "PREPARED",
                "created_at": now,
                "updated_at": now,
                "identity": {
                    "round_id": round_id,
                    "slot": slot,
                    "perspective": perspective,
                },
                "paths": {
                    "run_root": str(context["run_root"]),
                    "run_dir": str(context["run_dir"]),
                    "runtime": str(runtime.resolve(strict=True)),
                    "clean_state_receipt": str(context["clean_receipt"]),
                    "browser_profile": str(context["browser_profile"]),
                    "downloads": str(context["downloads"]),
                    "api_log": str(context["logs"] / "api.log"),
                    "frontend_log": str(context["logs"] / "frontend.log"),
                    "frontend_build_log": str(frontend_build_log),
                    "frontend_snapshot": str(
                        context["frontend_snapshot"].resolve(strict=True)
                    ),
                    "scheduled_ai_role_bindings": (
                        str(product_ai_route["overlay_path"])
                        if product_ai_route is not None
                        else ""
                    ),
                    "product_ai_route_receipt": (
                        str(product_ai_route["receipt_path"])
                        if product_ai_route is not None
                        else ""
                    ),
                },
                "ports": {"backend": backend, "frontend": frontend},
                "commands": {
                    "api": _command_summary(api_command),
                    "frontend": _command_summary(frontend_command),
                    "frontend_build": frontend_snapshot["command"],
                },
                "processes": {"api": None, "frontend": None},
                "baseline": {
                    "manifest": str(runtime / BASELINE.MANIFEST_NAME),
                    "manifest_sha256": _sha256_file(
                        runtime / BASELINE.MANIFEST_NAME
                    ),
                },
                "product_ai_route": (
                    {
                        key: value
                        for key, value in product_ai_route.items()
                        if key not in {"overlay_path", "receipt_path"}
                    }
                    if product_ai_route is not None
                    else None
                ),
                "clean_state": None,
                "runtime_identity": None,
                "contract": None,
                "frontend_snapshot": frontend_snapshot,
                "source_receipts_at_start": source_receipts,
                "failure": None,
                "external_tester_launched": False,
                "pass_created": False,
                "shared_runtime_modified": False,
                "lifecycle": [_lifecycle_event("PREPARED", "baseline prepared")],
            }
            _atomic_update_receipt(receipt_path, receipt, runtime)

            api_environment = {
                key: value
                for key, value in os.environ.items()
                if key != "PYTHONPATH"
            }
            api_environment.update(
                {
                    "WORKBENCH_RUNTIME_DIR": str(runtime.resolve(strict=True)),
                    "WORKBENCH_RUNTIME_DIR_SHA256": hashlib.sha256(
                        str(runtime.resolve(strict=True)).encode("utf-8")
                    ).hexdigest(),
                    "WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "false",
                    "WORKBENCH_CLIENT_CONTRACT_MODE": "enforce",
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            if product_ai_route is not None:
                api_environment["WORKBENCH_AI_ROLE_SETTINGS_PATH"] = str(
                    product_ai_route["overlay_path"]
                )
            backend_reservation.close()
            backend_reservation = None
            api_log_handle = (context["logs"] / "api.log").open("ab", buffering=0)
            api_process = active_hooks.popen(
                api_command,
                cwd=WORKSPACE_ROOT,
                env=api_environment,
                stdin=subprocess.DEVNULL,
                stdout=api_log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            receipt["processes"]["api"] = _process_receipt(
                active_hooks, api_process
            )
            _transition(
                receipt_path,
                receipt,
                "API_STARTED",
                "isolated API process started",
                runtime_root=runtime,
            )
            _wait_for_json(
                active_hooks,
                f"http://127.0.0.1:{backend}/api/health",
                process=api_process,
                timeout_seconds=start_timeout_seconds,
            )

            verify_kwargs: dict[str, Any] = {
                "target_runtime": runtime,
                "base_url": f"http://127.0.0.1:{backend}",
                "source_runtime": source_runtime,
                "server_pid": int(api_process.pid),
                "output_path": context["clean_receipt"],
                "test_source_root": test_source_root,
                "test_target_root": test_target_root,
            }
            if product_ai_route is not None:
                verify_kwargs["expected_roles"] = {
                    **BASELINE.EXPECTED_ROLES,
                    "independent_ai": {
                        "provider": product_ai_route["provider"],
                        "model": product_ai_route["model"],
                    },
                }
            if active_hooks.fetch_json is not None:
                verify_kwargs["http_getter"] = lambda url: _fetch(
                    active_hooks, url
                )
            if active_hooks.process_identity is not None:
                verify_kwargs["process_inspector"] = lambda base_url, pid: {
                    "pid": int(api_process.pid),
                    "environment": {
                        "WORKBENCH_RUNTIME_DIR": str(runtime.resolve(strict=True)),
                        "WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "false",
                    },
                }
            clean_result = active_hooks.baseline_verify_startup(**verify_kwargs)
            if (
                clean_result.get("status") != "CLEAN_STATE_VERIFIED"
                or Path(str(clean_result.get("receipt"))).resolve(strict=True)
                != context["clean_receipt"].resolve(strict=True)
                or stat.S_IMODE(context["clean_receipt"].stat().st_mode)
                != TARGET_FILE_MODE
            ):
                raise RuntimeOrchestratorError(
                    "baseline startup verification did not produce the fixed 0600 receipt"
                )
            receipt["clean_state"] = {
                "status": "CLEAN_STATE_VERIFIED",
                "receipt_sha256": _sha256_file(context["clean_receipt"]),
                "verified_before_frontend_start": True,
            }
            _transition(
                receipt_path,
                receipt,
                "CLEAN_STATE_VERIFIED",
                "clean-state receipt verified before frontend start",
                runtime_root=runtime,
            )

            frontend_environment = dict(os.environ)
            frontend_environment["VITE_API_PROXY_TARGET"] = (
                f"http://127.0.0.1:{backend}"
            )
            frontend_reservation.close()
            frontend_reservation = None
            frontend_log_handle = (
                context["logs"] / "frontend.log"
            ).open("ab", buffering=0)
            frontend_process = active_hooks.popen(
                frontend_command,
                cwd=FRONTEND_DIR,
                env=frontend_environment,
                stdin=subprocess.DEVNULL,
                stdout=frontend_log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            receipt["processes"]["frontend"] = _process_receipt(
                active_hooks, frontend_process
            )
            _transition(
                receipt_path,
                receipt,
                "FRONTEND_STARTED",
                "immutable Vite preview started after clean-state verification",
                runtime_root=runtime,
            )
            frontend_manifest = _wait_for_json(
                active_hooks,
                f"http://127.0.0.1:{frontend}/runtime-build.json",
                process=frontend_process,
                timeout_seconds=start_timeout_seconds,
            )
            receipt["contract"] = _verify_contract(
                active_hooks,
                backend_port=backend,
                frontend_port=frontend,
                frontend_manifest=frontend_manifest,
            )
            receipt["runtime_identity"] = _runtime_identity_hash(
                runtime,
                context["clean_receipt"],
                (
                    product_ai_route["overlay_path"]
                    if product_ai_route is not None
                    else None
                ),
            )
            _transition(
                receipt_path,
                receipt,
                "RUNNING",
                "frontend/backend contract verified",
                runtime_root=runtime,
            )
            return {
                "status": "RUNNING",
                "receipt": str(receipt_path),
                "clean_state_receipt": str(context["clean_receipt"]),
                "backend_url": f"http://127.0.0.1:{backend}",
                "frontend_url": f"http://127.0.0.1:{frontend}",
                "runtime": str(runtime.resolve(strict=True)),
                "runtime_identity_sha256": receipt["runtime_identity"][
                    "runtime_identity_sha256"
                ],
            }
        except Exception as exc:
            _terminate_spawned_process(frontend_process, active_hooks)
            _terminate_spawned_process(api_process, active_hooks)
            if receipt is not None:
                receipt["failure"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                try:
                    released = not _listeners(
                        active_hooks, receipt["ports"]["backend"]
                    ) and not _listeners(
                        active_hooks, receipt["ports"]["frontend"]
                    )
                    state = "FAILED_STOPPED" if released else "FAILED_ORPHANED"
                    _transition(
                        receipt_path,
                        receipt,
                        state,
                        "startup failed; task-created processes were stopped"
                        if released
                        else "startup failed and a test port remains occupied",
                        runtime_root=runtime if runtime.is_dir() else None,
                    )
                except Exception:
                    pass
            raise
        finally:
            if backend_reservation is not None:
                backend_reservation.close()
            if frontend_reservation is not None:
                frontend_reservation.close()
            if api_log_handle is not None:
                api_log_handle.close()
            if frontend_log_handle is not None:
                frontend_log_handle.close()


def status(
    *,
    round_id: str,
    slot: str,
    perspective: str,
    run_root: Path = ALLOWED_RUN_ROOT,
    test_run_root: Optional[Path] = None,
    hooks: Optional[Hooks] = None,
) -> dict[str, Any]:
    active_hooks = hooks or Hooks()
    context = _resolve_run_context(
        round_id=round_id,
        slot=slot,
        perspective=perspective,
        run_root=run_root,
        test_run_root=test_run_root,
    )
    receipt = _read_json(context["receipt"])
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise RuntimeOrchestratorError("unsupported service receipt schema")
    details = {}
    for name, port_key in (("api", "backend"), ("frontend", "frontend")):
        record = receipt.get("processes", {}).get(name)
        port = receipt.get("ports", {}).get(port_key)
        if not isinstance(port, int):
            raise RuntimeOrchestratorError("service receipt contains an invalid port")
        pid = record.get("pid") if isinstance(record, dict) else None
        observed = _identity(active_hooks, pid) if isinstance(pid, int) else None
        identity_match = (
            isinstance(record, dict)
            and isinstance(record.get("identity"), dict)
            and _same_identity(record["identity"], observed)
        )
        listeners = _listeners(active_hooks, port)
        details[name] = {
            "pid": pid,
            "identity_match": identity_match,
            "listener_pids": sorted(listeners),
            "listening_as_receipt_pid": (
                isinstance(pid, int) and listeners == {pid}
            ),
        }
    state = str(receipt.get("state"))
    if state == "RUNNING":
        observed_status = (
            "RUNNING"
            if all(
                item["identity_match"] and item["listening_as_receipt_pid"]
                for item in details.values()
            )
            else "DEGRADED"
        )
    elif state in TERMINAL_STATES:
        observed_status = (
            state
            if all(not item["listener_pids"] for item in details.values())
            else "DEGRADED"
        )
    else:
        observed_status = state
    return {
        "status": observed_status,
        "receipt_state": state,
        "receipt": str(context["receipt"]),
        "processes": details,
        "pass_created": False,
    }


def stop(
    *,
    round_id: str,
    slot: str,
    perspective: str,
    run_root: Path = ALLOWED_RUN_ROOT,
    test_run_root: Optional[Path] = None,
    stop_timeout_seconds: float = DEFAULT_STOP_TIMEOUT_SECONDS,
    hooks: Optional[Hooks] = None,
) -> dict[str, Any]:
    if stop_timeout_seconds <= 0:
        raise RuntimeOrchestratorError("stop timeout must be positive")
    active_hooks = hooks or Hooks()
    context = _resolve_run_context(
        round_id=round_id,
        slot=slot,
        perspective=perspective,
        run_root=run_root,
        test_run_root=test_run_root,
    )
    with _root_lock(context["run_root"]):
        receipt = _read_json(context["receipt"])
        if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
            raise RuntimeOrchestratorError("unsupported service receipt schema")
        if receipt.get("state") in TERMINAL_STATES:
            current = status(
                round_id=round_id,
                slot=slot,
                perspective=perspective,
                run_root=run_root,
                test_run_root=test_run_root,
                hooks=active_hooks,
            )
            if current["status"] == "DEGRADED":
                raise RuntimeOrchestratorError(
                    "terminal receipt ports are occupied; refusing unrelated signals"
                )
            return {
                "status": "ALREADY_STOPPED",
                "receipt": str(context["receipt"]),
                "ports_released": True,
            }
        _preflight_stop_one(
            active_hooks,
            process_record=receipt.get("processes", {}).get("frontend"),
            port=receipt["ports"]["frontend"],
        )
        _preflight_stop_one(
            active_hooks,
            process_record=receipt.get("processes", {}).get("api"),
            port=receipt["ports"]["backend"],
        )
        _transition(
            context["receipt"],
            receipt,
            "STOPPING",
            "receipt-scoped shutdown started",
            runtime_root=context["runtime"],
        )
        frontend_result = _stop_one(
            active_hooks,
            process_record=receipt.get("processes", {}).get("frontend"),
            port=receipt["ports"]["frontend"],
            timeout_seconds=stop_timeout_seconds,
        )
        api_result = _stop_one(
            active_hooks,
            process_record=receipt.get("processes", {}).get("api"),
            port=receipt["ports"]["backend"],
            timeout_seconds=stop_timeout_seconds,
        )
        if _listeners(active_hooks, receipt["ports"]["frontend"]) or _listeners(
            active_hooks, receipt["ports"]["backend"]
        ):
            raise RuntimeOrchestratorError("test ports were not released")
        receipt["stop"] = {
            "frontend": frontend_result,
            "api": api_result,
            "ports_released": True,
        }
        _transition(
            context["receipt"],
            receipt,
            "STOPPED",
            "receipt PIDs stopped and both ports released",
            runtime_root=context["runtime"],
        )
        return {
            "status": "STOPPED",
            "receipt": str(context["receipt"]),
            "ports_released": True,
            "stopped_pids": [
                item["pid"]
                for item in (frontend_result, api_result)
                if item["pid"] is not None and not item["already_absent"]
            ],
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("start", "status", "stop"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--round-id", required=True)
        subparser.add_argument("--slot", required=True)
        subparser.add_argument(
            "--perspective",
            required=True,
            choices=sorted(PERSPECTIVES),
        )
        if command == "start":
            subparser.add_argument("--backend-port", type=int)
            subparser.add_argument("--frontend-port", type=int)
            subparser.add_argument(
                "--start-timeout-seconds",
                type=float,
                default=DEFAULT_START_TIMEOUT_SECONDS,
            )
        if command == "stop":
            subparser.add_argument(
                "--stop-timeout-seconds",
                type=float,
                default=DEFAULT_STOP_TIMEOUT_SECONDS,
            )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        common = {
            "round_id": args.round_id,
            "slot": args.slot,
            "perspective": args.perspective,
        }
        if args.command == "start":
            result = start(
                **common,
                backend_port=args.backend_port,
                frontend_port=args.frontend_port,
                start_timeout_seconds=args.start_timeout_seconds,
            )
        elif args.command == "status":
            result = status(**common)
        else:
            result = stop(
                **common,
                stop_timeout_seconds=args.stop_timeout_seconds,
            )
    except RuntimeOrchestratorError as exc:
        print(
            json.dumps(
                {"status": "FAILED", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
