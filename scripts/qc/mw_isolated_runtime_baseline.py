#!/usr/bin/env python3
"""Prepare and verify an isolated runtime baseline.

Preparation copies only the four system-level AI configuration files. Startup
verification observes an already-running local service and its SQLite stores.
The tool never starts or stops services and never creates PASS evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


SCRIPT_PATH = Path(__file__).resolve()
WORKSPACE_ROOT = SCRIPT_PATH.parents[2]
PRODUCT_ROOT = WORKSPACE_ROOT.parents[1]
DEFAULT_SOURCE_RUNTIME = PRODUCT_ROOT / "runtime"
FORBIDDEN_WORKBENCH_RUNTIME = WORKSPACE_ROOT / "runtime"
ALLOWED_RUN_ROOTS = (
    WORKSPACE_ROOT / "runs/execution/mw_final_5x3_harness_20260728",
    WORKSPACE_ROOT / "runs/execution/mw_final_4x3_harness_20260727",
    WORKSPACE_ROOT / "runs/execution/mw_final_release_matrix_20260727",
)
MANIFEST_NAME = "BASELINE_MANIFEST.json"
RECEIPT_NAME = "CLEAN_STATE_RECEIPT.json"
BASELINE_FILES = (
    "ai_provider_settings.json",
    "ai_provider_secrets.json",
    "ai_provider_master.key",
    "ai_role_bindings.json",
)
TARGET_FILE_MODE = 0o600
TARGET_DIRECTORY_MODE = 0o700
SCHEMA_VERSION = "mw-isolated-runtime-baseline-2026-07-27.1"
RECEIPT_SCHEMA_VERSION = "mw-clean-state-receipt-2026-07-27.1"
PENDING_PROJECT_STATUS = "\u5f85\u542f\u52a8\u9a8c\u8bc1"
EXPECTED_RUNTIME_SCHEMA_VERSION = 16
EXPECTED_ROLES = {
    "independent_ai": {
        "provider": "alibaba_token_plan",
        "model": "qwen3.8-max-preview",
    },
    "ocr": {
        "provider": "omlx",
        "model": "GLM-OCR-bf16",
    },
    "translation_body": {
        "provider": "omlx",
        "model": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX",
    },
    "translation_support": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
    },
}
SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}


class BaselineError(RuntimeError):
    """Raised when a baseline safety or verification gate fails closed."""


def _absolute_path(path: Path) -> Path:
    expanded = path.expanduser()
    if ".." in expanded.parts:
        raise BaselineError(f"path traversal is forbidden: {path}")
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
            raise BaselineError(f"symbolic links are forbidden: {current}")
        if current != absolute and not stat.S_ISDIR(metadata.st_mode):
            raise BaselineError(f"path component is not a directory: {current}")


def _validated_test_root(path: Path) -> Path:
    root = _absolute_path(path)
    _assert_no_symlink_components(root)
    if not root.is_dir():
        raise BaselineError(f"test root must be an existing directory: {root}")
    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    resolved = root.resolve(strict=True)
    if not _is_within(resolved, system_temp):
        raise BaselineError(f"test root must stay under system temp: {system_temp}")
    return resolved


def _validate_boundary(
    candidate: Path,
    *,
    test_target_root: Optional[Path],
) -> Path:
    absolute = _absolute_path(candidate)
    _assert_no_symlink_components(absolute)
    allowed_roots = [
        _absolute_path(raw_root).resolve(strict=False)
        for raw_root in ALLOWED_RUN_ROOTS
    ]
    for raw_root in ALLOWED_RUN_ROOTS:
        root = _absolute_path(raw_root)
        if not _is_within(absolute, root):
            continue
        _assert_no_symlink_components(root)
        resolved_root = root.resolve(strict=False)
        if _is_within(absolute, resolved_root):
            return absolute
    if test_target_root is not None:
        test_root = _validated_test_root(test_target_root)
        if _is_within(absolute, test_root):
            return absolute
    raise BaselineError(
        f"target must stay under one of the fixed run roots {allowed_roots} "
        "or an explicit system-temp test root"
    )


def resolve_source_runtime(
    source_runtime: Optional[Path] = None,
    *,
    test_source_root: Optional[Path] = None,
) -> Path:
    default_source = DEFAULT_SOURCE_RUNTIME.resolve(strict=False)
    forbidden = FORBIDDEN_WORKBENCH_RUNTIME.resolve(strict=False)
    if default_source == forbidden:
        raise BaselineError(
            "default source resolution collapsed to forbidden workbench/runtime"
        )

    candidate = default_source if source_runtime is None else _absolute_path(source_runtime)
    _assert_no_symlink_components(candidate)
    if candidate == forbidden:
        raise BaselineError("workbench/runtime is forbidden as a source runtime")
    if candidate != default_source:
        if test_source_root is None:
            raise BaselineError(
                "non-default source requires an explicit system-temp test root"
            )
        test_root = _validated_test_root(test_source_root)
        if not _is_within(candidate, test_root):
            raise BaselineError(f"source must stay under test root {test_root}")
    if not candidate.is_dir():
        raise BaselineError(f"source runtime must be an existing directory: {candidate}")
    return candidate.resolve(strict=True)


def resolve_new_target_runtime(
    target_runtime: Path,
    *,
    test_target_root: Optional[Path] = None,
) -> Path:
    target = _validate_boundary(
        target_runtime,
        test_target_root=test_target_root,
    )
    if os.path.lexists(target):
        raise BaselineError(f"target must be a new directory and already exists: {target}")
    if not target.parent.is_dir():
        raise BaselineError(f"target parent must already exist: {target.parent}")
    _assert_no_symlink_components(target.parent)
    return target


def resolve_existing_target_runtime(
    target_runtime: Path,
    *,
    test_target_root: Optional[Path] = None,
) -> Path:
    target = _validate_boundary(
        target_runtime,
        test_target_root=test_target_root,
    )
    if not target.is_dir():
        raise BaselineError(f"target runtime must be an existing directory: {target}")
    return target.resolve(strict=True)


def resolve_new_receipt_path(
    target_runtime: Path,
    output_path: Optional[Path] = None,
    *,
    test_target_root: Optional[Path] = None,
) -> Path:
    candidate = (
        target_runtime.parent / RECEIPT_NAME
        if output_path is None
        else output_path
    )
    output = _validate_boundary(
        candidate,
        test_target_root=test_target_root,
    )
    if output.name != RECEIPT_NAME:
        raise BaselineError(f"receipt filename must be {RECEIPT_NAME}")
    if not output.parent.is_dir():
        raise BaselineError(f"receipt parent must already exist: {output.parent}")
    _assert_no_symlink_components(output.parent)
    if os.path.lexists(output):
        raise BaselineError(f"receipt path already exists: {output}")
    return output


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mode_string(path: Path) -> str:
    return f"{stat.S_IMODE(path.stat().st_mode):04o}"


def _inspect_source_files(source_runtime: Path) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for filename in BASELINE_FILES:
        path = source_runtime / filename
        if not os.path.lexists(path):
            raise BaselineError(f"required source file is missing: {path}")
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise BaselineError(f"source files cannot be symbolic links: {path}")
        if not stat.S_ISREG(metadata.st_mode):
            raise BaselineError(f"source file must be a regular file: {path}")
        receipts.append(
            {
                "filename": filename,
                "source_path": str(path.resolve(strict=True)),
                "bytes": metadata.st_size,
                "sha256": _sha256_file(path),
                "source_mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
            }
        )
    return receipts


def _atomic_copy(source: Path, target: Path) -> None:
    open_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    source_fd = os.open(source, open_flags)
    temp_fd = -1
    temp_name = ""
    try:
        source_metadata = os.fstat(source_fd)
        if not stat.S_ISREG(source_metadata.st_mode):
            raise BaselineError(f"source file changed type during copy: {source}")
        temp_fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.fchmod(temp_fd, TARGET_FILE_MODE)
        with os.fdopen(source_fd, "rb", closefd=True) as source_handle:
            source_fd = -1
            with os.fdopen(temp_fd, "wb", closefd=True) as target_handle:
                temp_fd = -1
                shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
                target_handle.flush()
                os.fsync(target_handle.fileno())
        os.replace(temp_name, target)
        temp_name = ""
        os.chmod(target, TARGET_FILE_MODE)
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name and os.path.lexists(temp_name):
            os.unlink(temp_name)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temp_fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        os.fchmod(temp_fd, TARGET_FILE_MODE)
        with os.fdopen(temp_fd, "wb", closefd=True) as handle:
            temp_fd = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        temp_name = ""
        os.chmod(path, TARGET_FILE_MODE)
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name and os.path.lexists(temp_name):
            os.unlink(temp_name)


def _manifest_payload(
    source_runtime: Path,
    target_runtime: Path,
    source_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    files = []
    for receipt in source_receipts:
        target_path = target_runtime / receipt["filename"]
        files.append(
            {
                **receipt,
                "target_path": str(target_path.resolve(strict=True)),
                "mode": _mode_string(target_path),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FILES_VERIFIED_PROJECT_STATE_PENDING_STARTUP",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_runtime_resolved": str(source_runtime),
        "target_runtime_resolved": str(target_runtime),
        "copy_policy": {
            "whitelist_only": True,
            "allowed_files": list(BASELINE_FILES),
            "sqlite_copied": False,
            "wal_copied": False,
            "shm_copied": False,
            "jsonl_copied": False,
            "project_or_artifact_copied": False,
            "secret_content_embedded": False,
        },
        "files": files,
        "zero_project_state": {
            "status": "PENDING_STARTUP_VERIFICATION",
            "display_status": PENDING_PROJECT_STATUS,
            "verified": False,
            "project_count": None,
        },
        "service_started": False,
        "product_api_called": False,
        "pass_created": False,
    }


def prepare_baseline(
    *,
    target_runtime: Path,
    source_runtime: Optional[Path] = None,
    test_source_root: Optional[Path] = None,
    test_target_root: Optional[Path] = None,
) -> dict[str, Any]:
    source = resolve_source_runtime(
        source_runtime,
        test_source_root=test_source_root,
    )
    target_candidate = _absolute_path(target_runtime)
    if target_candidate == source:
        raise BaselineError("source and target runtime must differ")
    target = resolve_new_target_runtime(
        target_candidate,
        test_target_root=test_target_root,
    )
    source_receipts = _inspect_source_files(source)

    target.mkdir(mode=TARGET_DIRECTORY_MODE)
    os.chmod(target, TARGET_DIRECTORY_MODE)
    try:
        for receipt in source_receipts:
            source_path = source / receipt["filename"]
            target_path = target / receipt["filename"]
            _atomic_copy(source_path, target_path)
            if target_path.stat().st_size != receipt["bytes"]:
                raise BaselineError(
                    f"copied byte count mismatch: {receipt['filename']}"
                )
            if _sha256_file(target_path) != receipt["sha256"]:
                raise BaselineError(f"copied hash mismatch: {receipt['filename']}")
            if _mode_string(target_path) != "0600":
                raise BaselineError(f"copied mode mismatch: {receipt['filename']}")

        manifest = _manifest_payload(source, target, source_receipts)
        _atomic_write_json(target / MANIFEST_NAME, manifest)
        verification = verify_files(
            target_runtime=target,
            source_runtime=source,
            test_source_root=test_source_root,
            test_target_root=test_target_root,
        )
        return {
            "status": "BASELINE_PREPARED",
            "source_runtime": str(source),
            "target_runtime": str(target),
            "manifest": str(target / MANIFEST_NAME),
            "verification": verification["status"],
        }
    except Exception:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        raise


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BaselineError(f"cannot read baseline manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BaselineError(f"baseline manifest must be a JSON object: {path}")
    return value


def _verify_baseline_files(
    *,
    target_runtime: Path,
    source_runtime: Optional[Path] = None,
    test_source_root: Optional[Path] = None,
    test_target_root: Optional[Path] = None,
    require_exact_file_set: bool,
) -> dict[str, Any]:
    source = resolve_source_runtime(
        source_runtime,
        test_source_root=test_source_root,
    )
    target = resolve_existing_target_runtime(
        target_runtime,
        test_target_root=test_target_root,
    )
    if source == target:
        raise BaselineError("source and target runtime must differ")

    expected_names = set(BASELINE_FILES) | {MANIFEST_NAME}
    observed_names = {item.name for item in target.iterdir()}
    if not expected_names.issubset(observed_names):
        missing = sorted(expected_names - observed_names)
        raise BaselineError(f"target baseline files are missing: {missing}")
    if require_exact_file_set and observed_names != expected_names:
        unexpected = sorted(observed_names - expected_names)
        missing = sorted(expected_names - observed_names)
        raise BaselineError(
            f"target file set mismatch; unexpected={unexpected}, missing={missing}"
        )

    manifest_path = target / MANIFEST_NAME
    for path in [manifest_path, *(target / name for name in BASELINE_FILES)]:
        metadata = os.lstat(path)
        if stat.S_ISLNK(metadata.st_mode):
            raise BaselineError(f"target files cannot be symbolic links: {path}")
        if not stat.S_ISREG(metadata.st_mode):
            raise BaselineError(f"target file must be a regular file: {path}")
        if f"{stat.S_IMODE(metadata.st_mode):04o}" != "0600":
            raise BaselineError(f"target file mode must be 0600: {path}")

    manifest = _read_manifest(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BaselineError("unexpected baseline manifest schema_version")
    if manifest.get("status") != "FILES_VERIFIED_PROJECT_STATE_PENDING_STARTUP":
        raise BaselineError("unexpected baseline manifest status")
    if manifest.get("source_runtime_resolved") != str(source):
        raise BaselineError("manifest source runtime does not match")
    if manifest.get("target_runtime_resolved") != str(target):
        raise BaselineError("manifest target runtime does not match")
    if manifest.get("zero_project_state") != {
        "status": "PENDING_STARTUP_VERIFICATION",
        "display_status": PENDING_PROJECT_STATUS,
        "verified": False,
        "project_count": None,
    }:
        raise BaselineError("zero-project state must remain pending startup verification")

    policy = manifest.get("copy_policy")
    if not isinstance(policy, dict) or policy != {
        "whitelist_only": True,
        "allowed_files": list(BASELINE_FILES),
        "sqlite_copied": False,
        "wal_copied": False,
        "shm_copied": False,
        "jsonl_copied": False,
        "project_or_artifact_copied": False,
        "secret_content_embedded": False,
    }:
        raise BaselineError("manifest copy policy is not the locked whitelist policy")

    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise BaselineError("manifest files must be a list")
    entries_by_name = {
        entry.get("filename"): entry for entry in entries if isinstance(entry, dict)
    }
    if set(entries_by_name) != set(BASELINE_FILES) or len(entries) != len(
        BASELINE_FILES
    ):
        raise BaselineError("manifest file list does not match the locked whitelist")

    source_receipts = {
        item["filename"]: item for item in _inspect_source_files(source)
    }
    for filename in BASELINE_FILES:
        entry = entries_by_name[filename]
        source_receipt = source_receipts[filename]
        target_path = target / filename
        expected_entry = {
            **source_receipt,
            "target_path": str(target_path.resolve(strict=True)),
            "mode": "0600",
        }
        if entry != expected_entry:
            raise BaselineError(f"manifest receipt mismatch: {filename}")
        if target_path.stat().st_size != entry["bytes"]:
            raise BaselineError(f"target byte count mismatch: {filename}")
        if _sha256_file(target_path) != entry["sha256"]:
            raise BaselineError(f"target hash mismatch: {filename}")

    return {
        "status": "FILES_VERIFIED_PROJECT_STATE_PENDING_STARTUP",
        "source_runtime": str(source),
        "target_runtime": str(target),
        "verified_file_count": len(BASELINE_FILES),
        "startup_additional_entry_count": len(observed_names - expected_names),
        "zero_project_state": PENDING_PROJECT_STATUS,
    }


def verify_files(
    *,
    target_runtime: Path,
    source_runtime: Optional[Path] = None,
    test_source_root: Optional[Path] = None,
    test_target_root: Optional[Path] = None,
) -> dict[str, Any]:
    return _verify_baseline_files(
        target_runtime=target_runtime,
        source_runtime=source_runtime,
        test_source_root=test_source_root,
        test_target_root=test_target_root,
        require_exact_file_set=True,
    )


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BaselineError(f"startup verification rejects HTTP redirects: {code}")


def _normalize_local_base_url(base_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(base_url)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise BaselineError(
            "base URL must be plain HTTP on 127.0.0.1 or localhost with an "
            "explicit port and no path, credentials, query, or fragment"
        )
    return f"http://{parsed.hostname}:{parsed.port}", parsed.port


def _fetch_json(url: str) -> Any:
    opener = urllib.request.build_opener(_RejectRedirects())
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=10) as response:
            if response.status != 200:
                raise BaselineError(
                    f"startup verification endpoint returned HTTP {response.status}: {url}"
                )
            content_type = response.headers.get_content_type()
            if content_type != "application/json":
                raise BaselineError(
                    f"startup verification endpoint is not JSON: {url}"
                )
            return json.load(response)
    except BaselineError:
        raise
    except (OSError, ValueError, urllib.error.HTTPError) as exc:
        raise BaselineError(
            f"cannot read startup verification endpoint {url}: "
            f"{type(exc).__name__}"
        ) from exc


def _validate_health(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise BaselineError("/api/health must return a JSON object")
    runtime_store = payload.get("runtime_store")
    if not isinstance(runtime_store, dict):
        raise BaselineError("/api/health runtime_store is missing")
    checks = {
        "status": payload.get("status"),
        "runtime_store_status": runtime_store.get("status"),
        "schema_version": runtime_store.get("schema_version"),
        "integrity_check": runtime_store.get("integrity_check"),
        "foreign_key_violations": runtime_store.get("foreign_key_violations"),
    }
    expected = {
        "status": "ok",
        "runtime_store_status": "ok",
        "schema_version": EXPECTED_RUNTIME_SCHEMA_VERSION,
        "integrity_check": "ok",
        "foreign_key_violations": 0,
    }
    if checks != expected:
        raise BaselineError(f"/api/health failed locked checks: {checks}")
    return checks


def _validate_projects(payload: Any) -> dict[str, Any]:
    if payload != []:
        raise BaselineError("/api/projects must return the exact empty JSON array")
    return {"exact_empty_array": True, "project_count": 0}


def _validate_roles(
    payload: Any,
    expected_roles: Optional[dict[str, dict[str, str]]] = None,
) -> list[dict[str, Any]]:
    expected_roles = EXPECTED_ROLES if expected_roles is None else expected_roles
    if not isinstance(payload, dict) or not isinstance(payload.get("roles"), list):
        raise BaselineError("/api/ai-gateway/roles/status roles are missing")
    roles = payload["roles"]
    by_id = {
        role.get("role_id"): role for role in roles if isinstance(role, dict)
    }
    if set(by_id) != set(expected_roles) or len(roles) != len(expected_roles):
        raise BaselineError(
            "AI role_id set must exactly match the four locked runtime roles"
        )
    receipts = []
    for role_id, expected_identity in expected_roles.items():
        role = by_id[role_id]
        observed_identity = {
            "provider": role.get("provider"),
            "model": role.get("model"),
        }
        if role.get("ready") is not True:
            raise BaselineError(f"AI role is not ready: {role_id}")
        if role.get("current_runnable") is not True:
            raise BaselineError(f"AI role is not currently runnable: {role_id}")
        if observed_identity != expected_identity:
            raise BaselineError(
                f"AI role identity mismatch for {role_id}: {observed_identity}"
            )
        receipts.append(
            {
                "role_id": role_id,
                "ready": True,
                "current_runnable": True,
                **observed_identity,
            }
        )
    return receipts


def _discover_listener_pid(port: int) -> int:
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
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BaselineError(
            f"cannot identify the local listener on port {port}"
        ) from exc
    pids = {
        int(line.strip())
        for line in result.stdout.splitlines()
        if line.strip().isdigit()
    }
    if len(pids) != 1:
        raise BaselineError(
            f"expected exactly one local listener on port {port}; found {sorted(pids)}"
        )
    return next(iter(pids))


def _inspect_server_process(base_url: str, server_pid: Optional[int]) -> dict[str, Any]:
    _, port = _normalize_local_base_url(base_url)
    listener_pid = _discover_listener_pid(port)
    if server_pid is not None:
        if server_pid <= 0:
            raise BaselineError("server PID must be a positive integer")
        if server_pid != listener_pid:
            raise BaselineError(
                f"declared server PID {server_pid} does not own port {port}"
            )
    pid = listener_pid
    inspection_environment = os.environ.copy()
    inspection_environment.update(
        {
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "LC_CTYPE": "C.UTF-8",
        }
    )
    try:
        result = subprocess.run(
            ["/bin/ps", "eww", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=inspection_environment,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BaselineError(f"cannot inspect environment for server PID {pid}") from exc
    environment = {}
    for key in (
        "WORKBENCH_RUNTIME_DIR",
        "WORKBENCH_INCLUDE_REFERENCE_PROJECTS",
    ):
        match = re.search(rf"(?:^|\s){re.escape(key)}=([^\s]+)", result.stdout)
        if match is None:
            raise BaselineError(f"server environment is missing {key}")
        environment[key] = match.group(1)
    runtime_hash_match = re.search(
        r"(?:^|\s)WORKBENCH_RUNTIME_DIR_SHA256=([0-9a-f]{64})(?:\s|$)",
        result.stdout,
    )
    if runtime_hash_match is not None:
        environment["WORKBENCH_RUNTIME_DIR_SHA256"] = runtime_hash_match.group(1)
    return {
        "pid": pid,
        "environment": environment,
    }


def _validate_process_receipt(
    process_receipt: Any,
    target_runtime: Path,
) -> dict[str, Any]:
    if not isinstance(process_receipt, dict):
        raise BaselineError("server process inspection returned an invalid receipt")
    pid = process_receipt.get("pid")
    environment = process_receipt.get("environment")
    if not isinstance(pid, int) or pid <= 0 or not isinstance(environment, dict):
        raise BaselineError("server process receipt is missing PID or environment")
    observed_runtime = environment.get("WORKBENCH_RUNTIME_DIR")
    if observed_runtime is None:
        raise BaselineError("server environment is missing WORKBENCH_RUNTIME_DIR")
    expected_runtime_hash = hashlib.sha256(
        str(target_runtime).encode("utf-8")
    ).hexdigest()
    observed_runtime_hash = environment.get("WORKBENCH_RUNTIME_DIR_SHA256")
    if (
        observed_runtime_hash is not None
        and observed_runtime_hash != expected_runtime_hash
    ):
        raise BaselineError(
            "server WORKBENCH_RUNTIME_DIR_SHA256 does not equal the target runtime"
        )
    runtime_evidence = "process_environment"
    try:
        resolved_runtime = _absolute_path(Path(str(observed_runtime))).resolve(
            strict=True
        )
    except OSError as exc:
        if "\ufffd" not in str(observed_runtime):
            raise BaselineError(
                "server WORKBENCH_RUNTIME_DIR does not resolve to an existing path"
            ) from exc
        if observed_runtime_hash is None:
            raise BaselineError(
                "server runtime path was lossy and runtime hash evidence is missing"
            ) from exc
        resolved_runtime = target_runtime
        runtime_evidence = "runtime_path_hash_after_lossy_ps"
    if resolved_runtime != target_runtime:
        raise BaselineError(
            "server WORKBENCH_RUNTIME_DIR does not equal the target runtime"
        )
    include_references = environment.get("WORKBENCH_INCLUDE_REFERENCE_PROJECTS")
    if include_references != "false":
        raise BaselineError(
            "server WORKBENCH_INCLUDE_REFERENCE_PROJECTS must equal false"
        )
    return {
        "pid": pid,
        "runtime_evidence": runtime_evidence,
        "environment": {
            "WORKBENCH_RUNTIME_DIR": str(resolved_runtime),
            "WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "false",
        },
    }


def _quoted_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _is_project_table(_table_name: str, columns: list[str]) -> bool:
    lowered_columns = [column.lower() for column in columns]
    return any(
        column == "project_id" or column.endswith("_project_id")
        for column in lowered_columns
    )


def inventory_project_sqlite(target_runtime: Path) -> dict[str, Any]:
    database_paths = sorted(
        path
        for path in target_runtime.rglob("*")
        if path.is_file() and path.suffix.lower() in SQLITE_SUFFIXES
    )
    if not database_paths:
        raise BaselineError("startup runtime contains no SQLite databases")

    databases = []
    project_table_count = 0
    total_project_rows = 0
    user_projects_seen = False
    for database_path in database_paths:
        metadata = os.lstat(database_path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise BaselineError(
                f"SQLite inventory requires regular non-symlink files: {database_path}"
            )
        resolved_database = database_path.resolve(strict=True)
        if not _is_within(resolved_database, target_runtime):
            raise BaselineError(f"SQLite path escapes target runtime: {database_path}")
        try:
            connection = sqlite3.connect(
                resolved_database.as_uri() + "?mode=ro",
                uri=True,
                timeout=5,
            )
            connection.execute("PRAGMA query_only=ON")
            table_names = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            project_tables = []
            for table_name in table_names:
                quoted = _quoted_identifier(table_name)
                columns = [
                    row[1]
                    for row in connection.execute(f"PRAGMA table_info({quoted})")
                ]
                if not _is_project_table(table_name, columns):
                    continue
                row_count = int(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {quoted}"
                    ).fetchone()[0]
                )
                project_columns = sorted(
                    column
                    for column in columns
                    if column.lower() == "project_id"
                    or column.lower().endswith("_project_id")
                )
                project_tables.append(
                    {
                        "table": table_name,
                        "row_count": row_count,
                        "project_locator_columns": project_columns,
                    }
                )
                project_table_count += 1
                total_project_rows += row_count
                if (
                    resolved_database.name == "user_projects.sqlite3"
                    and table_name == "user_projects"
                ):
                    user_projects_seen = True
            databases.append(
                {
                    "path": str(resolved_database.relative_to(target_runtime)),
                    "access_mode": "read_only",
                    "schema_table_count": len(table_names),
                    "project_bearing": bool(project_tables),
                    "project_tables": project_tables,
                }
            )
        except sqlite3.Error as exc:
            raise BaselineError(
                f"read-only SQLite inventory failed: {database_path.name}"
            ) from exc
        finally:
            if "connection" in locals():
                connection.close()
                del connection

    if not user_projects_seen:
        raise BaselineError(
            "startup runtime is missing user_projects.sqlite3/user_projects"
        )
    if project_table_count == 0:
        raise BaselineError("startup runtime has no recognized project-bearing tables")
    if total_project_rows != 0:
        raise BaselineError(
            f"project-bearing SQLite tables must contain zero rows; found "
            f"{total_project_rows}"
        )
    return {
        "access_mode": "read_only",
        "database_count": len(databases),
        "project_bearing_database_count": sum(
            1 for item in databases if item["project_bearing"]
        ),
        "known_project_table_count": project_table_count,
        "total_project_rows": 0,
        "databases": databases,
    }


def _assert_runtime_tree_has_no_symlinks(target_runtime: Path) -> None:
    for root, directories, files in os.walk(target_runtime, followlinks=False):
        for name in [*directories, *files]:
            path = Path(root) / name
            if stat.S_ISLNK(os.lstat(path).st_mode):
                raise BaselineError(f"startup runtime contains a symbolic link: {path}")


def _assert_receipt_has_no_secret_content(
    payload: dict[str, Any],
    target_runtime: Path,
) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    for filename in ("ai_provider_secrets.json", "ai_provider_master.key"):
        secret = (target_runtime / filename).read_bytes()
        if secret and secret in encoded:
            raise BaselineError(f"clean-state receipt would embed content from {filename}")


def verify_startup(
    *,
    target_runtime: Path,
    base_url: str,
    source_runtime: Optional[Path] = None,
    server_pid: Optional[int] = None,
    output_path: Optional[Path] = None,
    test_source_root: Optional[Path] = None,
    test_target_root: Optional[Path] = None,
    http_getter: Optional[Callable[[str], Any]] = None,
    process_inspector: Optional[
        Callable[[str, Optional[int]], dict[str, Any]]
    ] = None,
    expected_roles: Optional[dict[str, dict[str, str]]] = None,
) -> dict[str, Any]:
    target = resolve_existing_target_runtime(
        target_runtime,
        test_target_root=test_target_root,
    )
    receipt_path = resolve_new_receipt_path(
        target,
        output_path,
        test_target_root=test_target_root,
    )
    _assert_runtime_tree_has_no_symlinks(target)
    baseline = _verify_baseline_files(
        target_runtime=target,
        source_runtime=source_runtime,
        test_source_root=test_source_root,
        test_target_root=test_target_root,
        require_exact_file_set=False,
    )
    normalized_base_url, _ = _normalize_local_base_url(base_url)
    getter = _fetch_json if http_getter is None else http_getter
    health = _validate_health(getter(normalized_base_url + "/api/health"))
    projects = _validate_projects(getter(normalized_base_url + "/api/projects"))
    roles = _validate_roles(
        getter(normalized_base_url + "/api/ai-gateway/roles/status"),
        expected_roles=expected_roles,
    )
    inspector = (
        _inspect_server_process if process_inspector is None else process_inspector
    )
    process = _validate_process_receipt(
        inspector(normalized_base_url, server_pid),
        target,
    )
    sqlite_inventory = inventory_project_sqlite(target)

    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": "CLEAN_STATE_VERIFIED",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "target_runtime_resolved": str(target),
        "base_url": normalized_base_url,
        "server_pid": process["pid"],
        "baseline": {
            "manifest": str((target / MANIFEST_NAME).resolve(strict=True)),
            "manifest_sha256": _sha256_file(target / MANIFEST_NAME),
            "verified_file_count": baseline["verified_file_count"],
            "startup_additional_entry_count": baseline[
                "startup_additional_entry_count"
            ],
            "whitelist_only": True,
        },
        "api": {
            "health": health,
            "projects": projects,
            "roles": roles,
        },
        "process_environment": process["environment"],
        "process_runtime_evidence": process["runtime_evidence"],
        "sqlite_inventory": sqlite_inventory,
        "secret_content_embedded": False,
        "service_started_by_tool": False,
        "service_stopped_by_tool": False,
        "shared_runtime_modified": False,
        "pass_created": False,
    }
    _assert_receipt_has_no_secret_content(receipt, target)
    _atomic_write_json(receipt_path, receipt)
    if _mode_string(receipt_path) != "0600":
        raise BaselineError("clean-state receipt mode must be 0600")
    return {
        "status": "CLEAN_STATE_VERIFIED",
        "target_runtime": str(target),
        "base_url": normalized_base_url,
        "server_pid": process["pid"],
        "receipt": str(receipt_path),
        "project_count": 0,
        "project_table_rows": 0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare or verify an isolated runtime baseline."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "verify-files", "verify-startup"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--target", type=Path, required=True)
        subparser.add_argument("--source", type=Path)
        subparser.add_argument(
            "--test-source-root",
            type=Path,
            help=argparse.SUPPRESS,
        )
        subparser.add_argument(
            "--test-target-root",
            type=Path,
            help=argparse.SUPPRESS,
        )
        if command == "verify-startup":
            subparser.add_argument("--base-url", required=True)
            subparser.add_argument("--server-pid", type=int)
            subparser.add_argument("--output", type=Path)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        common = {
            "target_runtime": args.target,
            "source_runtime": args.source,
            "test_source_root": args.test_source_root,
            "test_target_root": args.test_target_root,
        }
        if args.command == "prepare":
            result = prepare_baseline(**common)
        elif args.command == "verify-files":
            result = verify_files(**common)
        else:
            result = verify_startup(
                **common,
                base_url=args.base_url,
                server_pid=args.server_pid,
                output_path=args.output,
            )
    except BaselineError as exc:
        print(
            json.dumps(
                {
                    "status": (
                        "FAILED" if args.command == "verify-startup" else "ERROR"
                    ),
                    "error": str(exc),
                },
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
