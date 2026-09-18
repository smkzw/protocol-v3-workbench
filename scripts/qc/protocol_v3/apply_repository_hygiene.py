"""Protocol v3 Phase 0 Task 0.5 recoverable-hygiene mutator.

Authority and crash-integrity contract:

- Default mode is dry-run. Apply/restore require explicit mode plus hash pins.
- Every PATH_MAP target is bound one-to-one to an exact inventory-eligible
  result under the hash-pinned inventory/protected snapshots. Basename or
  path-component shape alone never authorizes mutation.
- Caller quarantine root and PATH_MAP root must be identical; PATH_MAP pin
  fields must equal the explicit CLI/API hash arguments.
- ``path_map_path`` is required for apply/restore. Existing on-disk maps are
  identity-checked; the validated map is persisted before any destructive
  boundary. Quarantine artifacts are not created before gates pass.
- ``occupancy_checker=None`` invokes the built-in fail-closed checker (ports,
  open handles, SQLite sidecars). Injected checkers are for tests only; the
  CLI never bypasses the built-in default.
- Crash windows are deterministic: durable pre-delete ``copied`` state allows
  replay when the source is already absent; restore validates explicit
  object/destination combinations. Post-destructive PATH_MAP persistence
  failures are never swallowed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

MUTATOR_POLICY_ID = "mw-protocol-v3-recoverable-hygiene-mutator-v1"

HYGIENE_PORTS = (8910, 8911, 5173, 5174)

PROHIBITED_ROOT_PATTERNS = (
    "runs", "records", "logs", "evidence",
    "archives", "runtime", "source_backups", "backups",
)

# Frozen approved forbidden-root set for tests and fail-closed comparisons.
APPROVED_PROHIBITED_ROOTS = frozenset(PROHIBITED_ROOT_PATTERNS)

LSOF_TIMEOUT_SECONDS = 5.0

DIRECT_DELETE_BASENAMES = frozenset({".DS_Store"})
DIRECT_DELETE_PATH_COMPONENTS = ("__pycache__", ".pytest_cache", ".ruff_cache", ".vite")
DIRECT_DELETE_SUFFIXES = (".pyc",)

QUARANTINE_MOVE_PATH_COMPONENTS = (
    ("frontend", "dist"),
    (".playwright-cli",),
    ("screenlog.0",),
    ("frontend", ".npm-cache"),
    ("bin", "Release"),
)

DENIED_OWNERS = frozenset({
    "medical_monitoring", "immutable_runtime_evidence",
    "protocol_v3_authority", "medical_writing_regression",
    "clinical_product_source_corpus", "shared_workbench_source",
    "design_visual_process_archive", "workbench_evidence_archive",
})

# Path-component spellings used by this workspace for medical-monitoring trees.
# Independent of owner spelling; owner deny remains defense-in-depth.
MEDICAL_MONITORING_PATH_MARKERS = frozenset({
    "medical_monitoring",
    "medical-monitoring",
})

CANDIDATE_CLASSIFICATIONS = frozenset({"regenerable", "quarantine"})

_HEX_LOWER = frozenset("0123456789abcdef")

_SCRIPTS_DIR = Path(__file__).resolve().parent

OccupancyChecker = Callable[[Sequence[Path]], Sequence[str]]


class HygieneMutatorError(RuntimeError):
    """Raised when a hygiene operation cannot proceed safely."""


_RESOLVER: Any = None


def _resolver():
    global _RESOLVER
    if _RESOLVER is None:
        path = _SCRIPTS_DIR / "evidence_locator_resolver.py"
        spec = importlib.util.spec_from_file_location(
            "protocol_v3_evidence_locator_resolver", path)
        if spec is None or spec.loader is None:
            raise HygieneMutatorError("cannot import resolver module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _RESOLVER = module
    return _RESOLVER


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_file_path(file_path: Path) -> str:
    return sha256_file(Path(file_path))


def _lexical_absolute(value: str | os.PathLike[str]) -> Path:
    return Path(os.path.abspath(os.fspath(value)))


def _fsync_dir(path: Path) -> None:
    """Fsync a directory; fail closed if the platform cannot do so."""

    dir_path = Path(path)
    if not dir_path.is_dir():
        raise HygieneMutatorError(
            "cannot fsync non-directory path: %s" % dir_path)
    flags = getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_RDONLY", 0)
    try:
        fd = os.open(str(dir_path), flags)
    except OSError as exc:
        raise HygieneMutatorError(
            "directory fsync open failed for %s: %s" % (dir_path, exc)
        ) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise HygieneMutatorError(
            "directory fsync failed for %s: %s" % (dir_path, exc)
        ) from exc
    finally:
        os.close(fd)


def _lstat_no_follow(path: Path) -> os.stat_result:
    try:
        return os.lstat(str(path))
    except OSError as exc:
        raise HygieneMutatorError(
            "lstat failed for %s: %s" % (path, exc)
        ) from exc


def _reject_if_symlink(path: Path, label: str) -> os.stat_result:
    st = _lstat_no_follow(path)
    if stat_is_symlink(st):
        raise HygieneMutatorError(
            "%s must not be a symlink: %s" % (label, path))
    return st


def stat_is_symlink(st: os.stat_result) -> bool:
    import stat as stat_mod
    return stat_mod.S_ISLNK(st.st_mode)


# Narrow, verified macOS system root aliases only. These are firm-link style
# spellings above task fixtures (e.g. tempfile -> /var/folders/...); they must
# never authorize a symlink at or below live/quarantine/PATH_MAP roots.
_ALLOWED_PLATFORM_ROOT_ALIASES = {
    Path("/var"): Path("/private/var"),
    Path("/tmp"): Path("/private/tmp"),
    Path("/etc"): Path("/private/etc"),
}


def _is_allowed_platform_root_alias(path: Path, st: os.stat_result) -> bool:
    if not stat_is_symlink(st):
        return False
    lexical = _lexical_absolute(path)
    expected = _ALLOWED_PLATFORM_ROOT_ALIASES.get(lexical)
    if expected is None:
        return False
    try:
        real = Path(os.path.realpath(str(lexical)))
    except OSError:
        return False
    return real == expected


def _assert_existing_components_not_symlinked(path: Path, label: str) -> Path:
    """Reject symlink components, allowing only verified platform root aliases."""

    lexical = _lexical_absolute(path)
    parts = lexical.parts
    if not parts:
        raise HygieneMutatorError("%s path is empty" % label)
    cursor = Path(parts[0])
    if cursor.exists() or os.path.lexists(str(cursor)):
        st = _lstat_no_follow(cursor)
        if stat_is_symlink(st) and not _is_allowed_platform_root_alias(cursor, st):
            raise HygieneMutatorError(
                "%s path component is a symlink: %s" % (label, cursor))
    for part in parts[1:]:
        cursor = cursor / part
        if not os.path.lexists(str(cursor)):
            break
        st = _lstat_no_follow(cursor)
        if stat_is_symlink(st) and not _is_allowed_platform_root_alias(cursor, st):
            raise HygieneMutatorError(
                "%s path component is a symlink: %s" % (label, cursor))
    return lexical


def _assert_root_not_symlinked(root: Path, label: str, *, must_exist: bool = True) -> Path:
    """Accept a root only after every existing lexical ancestor is safe.

    Platform root aliases (``/var`` → ``/private/var``, etc.) remain allowed.
    Arbitrary task-owned symlink components above the root are always rejected,
    including when the leaf itself is an ordinary directory.
    """

    lexical = _require_raw_absolute_path(root, label)
    exists = lexical.exists() or os.path.lexists(str(lexical))
    if must_exist and not exists:
        raise HygieneMutatorError("%s does not exist: %s" % (label, lexical))
    # Validate every existing ancestor above the root leaf. The leaf is checked
    # separately so a symlinked root keeps the explicit "must not be a symlink"
    # contract while symlink-above-root attacks are still caught.
    parent = lexical.parent
    if parent != lexical:
        _assert_existing_components_not_symlinked(parent, label)
    if exists:
        # The root node itself must never be a symlink. Verified platform
        # aliases are exact paths like /var and are not valid task roots.
        _reject_if_symlink(lexical, label)
    return lexical


def _assert_path_within_root_no_symlink(
    root: Path,
    target: Path,
    *,
    label: str,
    must_exist: bool = True,
) -> tuple[Path, os.stat_result | None]:
    """Reject symlink components and realpath escapes under root."""

    root_lex = _lexical_absolute(root)
    target_lex = _lexical_absolute(target)
    # Re-validate root ancestry on every boundary so a parent swap between
    # prepare and unlink/restore cannot bypass the initial pin.
    if not root_lex.exists():
        raise HygieneMutatorError("%s root does not exist: %s" % (label, root_lex))
    _assert_existing_components_not_symlinked(root_lex, "%s root" % label)
    _reject_if_symlink(root_lex, "%s root" % label)

    try:
        rel = target_lex.relative_to(root_lex)
    except ValueError as exc:
        raise HygieneMutatorError(
            "%s lexical path escapes root %s: %s" % (label, root_lex, target_lex)
        ) from exc

    cursor = root_lex
    deepest_existing = root_lex
    missing = False
    for part in PurePosixPath(rel.as_posix()).parts:
        cursor = cursor / part
        if missing or not os.path.lexists(str(cursor)):
            missing = True
            continue
        st = _lstat_no_follow(cursor)
        if stat_is_symlink(st):
            raise HygieneMutatorError(
                "%s path component is a symlink: %s" % (label, cursor))
        deepest_existing = cursor

    if must_exist and missing:
        if "source" in label:
            raise HygieneMutatorError(
                "source missing before removal: %s" % target_lex)
        raise HygieneMutatorError(
            "%s path does not exist: %s" % (label, target_lex))

    try:
        root_real = Path(os.path.realpath(str(root_lex)))
        deep_real = Path(os.path.realpath(str(deepest_existing)))
    except OSError as exc:
        raise HygieneMutatorError(
            "%s realpath failed: %s" % (label, exc)
        ) from exc
    try:
        deep_real.relative_to(root_real)
    except ValueError as exc:
        raise HygieneMutatorError(
            "%s realpath escapes root %s: %s" % (label, root_real, deep_real)
        ) from exc

    if missing:
        return target_lex, None

    final_st = _lstat_no_follow(target_lex)
    if stat_is_symlink(final_st):
        raise HygieneMutatorError(
            "%s path component is a symlink: %s" % (label, target_lex))
    # Full target realpath containment when the leaf exists.
    try:
        target_real = Path(os.path.realpath(str(target_lex)))
        target_real.relative_to(root_real)
    except ValueError as exc:
        raise HygieneMutatorError(
            "%s realpath escapes root %s: %s" % (label, root_real, target_real)
        ) from exc
    except OSError as exc:
        raise HygieneMutatorError(
            "%s realpath failed: %s" % (label, exc)
        ) from exc
    return target_lex, final_st


def _safe_unlink_regular_file(path: Path, expected: os.stat_result) -> None:
    """Unlink a regular file with no-follow revalidation at the boundary."""

    import stat as stat_mod

    path = _lexical_absolute(path)
    st = _lstat_no_follow(path)
    if stat_is_symlink(st):
        raise HygieneMutatorError(
            "refusing to unlink symlink at destructive boundary: %s" % path)
    if not stat_mod.S_ISREG(st.st_mode):
        raise HygieneMutatorError(
            "refusing to unlink non-regular file: %s" % path)
    if (st.st_ino, st.st_dev, st.st_size, st.st_mtime_ns) != (
        expected.st_ino, expected.st_dev, expected.st_size, expected.st_mtime_ns
    ):
        raise HygieneMutatorError(
            "inode/device identity changed before unlink: %s" % path)

    parent = path.parent
    dir_flags = getattr(os, "O_RDONLY", 0) | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    open_flags = dir_flags | nofollow
    try:
        dir_fd = os.open(str(parent), open_flags)
    except OSError as exc:
        raise HygieneMutatorError(
            "cannot open parent directory without following symlinks "
            "for unlink of %s: %s" % (path, exc)
        ) from exc
    try:
        name = path.name
        try:
            st2 = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except TypeError as exc:
            raise HygieneMutatorError(
                "platform lacks dir_fd no-follow stat for safe unlink: %s" % exc
            ) from exc
        except OSError as exc:
            raise HygieneMutatorError(
                "dir_fd stat failed before unlink of %s: %s" % (path, exc)
            ) from exc
        if stat_is_symlink(st2) or not stat_mod.S_ISREG(st2.st_mode):
            raise HygieneMutatorError(
                "target is not a regular file at unlink boundary: %s" % path)
        if (st2.st_ino, st2.st_dev) != (expected.st_ino, expected.st_dev):
            raise HygieneMutatorError(
                "target inode swapped before unlink: %s" % path)
        try:
            os.unlink(name, dir_fd=dir_fd)
        except TypeError as exc:
            raise HygieneMutatorError(
                "platform lacks dir_fd unlink; refusing unsafe fallback: %s"
                % exc
            ) from exc
        try:
            os.fsync(dir_fd)
        except OSError as exc:
            raise HygieneMutatorError(
                "directory fsync failed after unlink of %s: %s" % (path, exc)
            ) from exc
    finally:
        os.close(dir_fd)


def _require_raw_absolute_path(
    value: str | os.PathLike[str] | None,
    label: str,
) -> Path:
    """Require a raw absolute, traversal-free path before normalization."""

    if value is None:
        raise HygieneMutatorError("%s is required" % label)
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw:
        raise HygieneMutatorError("%s must be a non-empty path string" % label)
    if ".." in PurePosixPath(raw).parts:
        raise HygieneMutatorError(
            "%s must not contain traversal segments: %s" % (label, raw))
    if not os.path.isabs(raw):
        raise HygieneMutatorError(
            "%s must be an absolute path before normalization, got %r"
            % (label, raw))
    return _lexical_absolute(raw)


def _resolve_live_absolute(live_root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise HygieneMutatorError(
            "inventory path must be a non-empty relative string")
    rel = PurePosixPath(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise HygieneMutatorError(
            "inventory path must be relative and traversal-free: %s" % relative_path)
    return _lexical_absolute(live_root / relative_path)


def _is_under_prohibited_root(relative_path: str,
                              prohibited_patterns: Sequence[str]) -> bool:
    parts = PurePosixPath(relative_path).parts
    for pattern in prohibited_patterns:
        pat = tuple(pattern.split("/"))
        if len(parts) >= len(pat) and parts[:len(pat)] == pat:
            return True
    return False


def _is_medical_monitoring_path(relative_path: str) -> bool:
    """Path-level medical-monitoring deny independent of owner spelling."""

    for part in PurePosixPath(relative_path).parts:
        if part in MEDICAL_MONITORING_PATH_MARKERS:
            return True
        lowered = part.lower()
        if "medical_monitoring" in lowered or "medical-monitoring" in lowered:
            return True
    return False


def _is_direct_delete_candidate(relative_path: str) -> bool:
    """Classify operation type for an already-eligible inventory path only."""

    parts = PurePosixPath(relative_path).parts
    if parts and parts[-1] in DIRECT_DELETE_BASENAMES:
        return True
    for component in DIRECT_DELETE_PATH_COMPONENTS:
        if component in parts:
            return True
    if parts and parts[-1].endswith(DIRECT_DELETE_SUFFIXES):
        return True
    return False


def _is_quarantine_move_candidate(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    for comp_parts in QUARANTINE_MOVE_PATH_COMPONENTS:
        for i in range(len(parts) - len(comp_parts) + 1):
            if parts[i:i + len(comp_parts)] == comp_parts:
                return True
    if ".venv" in parts or "node_modules" in parts:
        return True
    return False


def _require_exact_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise HygieneMutatorError(
            "%s must be an actual bool, got %s" % (label, type(value).__name__))
    return value


def _require_nonneg_int(value: Any, label: str) -> int:
    # Reject bool explicitly: bool is a subclass of int in Python.
    if type(value) is not int:
        raise HygieneMutatorError(
            "%s must be a non-boolean int, got %s"
            % (label, type(value).__name__))
    if value < 0:
        raise HygieneMutatorError("%s must be non-negative, got %r" % (label, value))
    return value


def _require_sha256_hex(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise HygieneMutatorError(
            "%s must be a string, got %s" % (label, type(value).__name__))
    if len(value) != 64 or any(ch not in _HEX_LOWER for ch in value):
        raise HygieneMutatorError(
            "%s must be lowercase 64-hex, got %r" % (label, value))
    return value


def _require_blocker_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise HygieneMutatorError(
            "%s must be a list of strings, got %s"
            % (label, type(value).__name__))
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise HygieneMutatorError(
                "%s[%d] must be a string, got %s"
                % (label, index, type(item).__name__))
        out.append(item)
    return out


def _validate_and_collect_protected_paths(protected: Any) -> frozenset[str]:
    """Fail closed on malformed protected manifests; never invent an empty deny."""

    if not isinstance(protected, dict):
        raise HygieneMutatorError("protected must be a JSON object")
    if "assets" not in protected:
        raise HygieneMutatorError("protected.assets is required")
    assets = protected["assets"]
    if not isinstance(assets, list):
        raise HygieneMutatorError(
            "protected.assets must be a list, got %s" % type(assets).__name__)
    out: set[str] = set()
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise HygieneMutatorError(
                "protected.assets[%d] must be an object, got %s"
                % (index, type(asset).__name__))
        if "path" not in asset:
            raise HygieneMutatorError(
                "protected.assets[%d].path is required" % index)
        path = asset["path"]
        if not isinstance(path, str) or not path:
            raise HygieneMutatorError(
                "protected.assets[%d].path must be a non-empty string" % index)
        if not os.path.isabs(path):
            raise HygieneMutatorError(
                "protected.assets[%d].path must be absolute, got %r"
                % (index, path))
        if ".." in PurePosixPath(path).parts:
            raise HygieneMutatorError(
                "protected.assets[%d].path must not contain traversal" % index)
        out.add(str(_lexical_absolute(path)))
        if "resolved_path" in asset and asset["resolved_path"] is not None:
            resolved = asset["resolved_path"]
            if not isinstance(resolved, str) or not resolved:
                raise HygieneMutatorError(
                    "protected.assets[%d].resolved_path must be a non-empty string"
                    % index)
            if not os.path.isabs(resolved):
                raise HygieneMutatorError(
                    "protected.assets[%d].resolved_path must be absolute"
                    % index)
            if ".." in PurePosixPath(resolved).parts:
                raise HygieneMutatorError(
                    "protected.assets[%d].resolved_path must not contain traversal"
                    % index)
            out.add(str(_lexical_absolute(resolved)))
    return frozenset(out)


def _parse_inventory_entry(raw_entry: Any, *, live_root: Path) -> dict[str, Any]:
    """Strictly validate one inventory entry; never coerce authority fields."""

    if not isinstance(raw_entry, dict):
        raise HygieneMutatorError("inventory entry must be a JSON object")
    relative_path = raw_entry.get("path")
    if not isinstance(relative_path, str) or not relative_path:
        raise HygieneMutatorError(
            "inventory entry path must be a non-empty relative string")
    if PurePosixPath(relative_path).is_absolute() or ".." in PurePosixPath(relative_path).parts:
        raise HygieneMutatorError(
            "inventory path must be relative and traversal-free: %s" % relative_path)
    owner = raw_entry.get("owner")
    if not isinstance(owner, str) or not owner:
        raise HygieneMutatorError(
            "inventory entry owner must be a non-empty string for %s"
            % relative_path)
    classification = raw_entry.get("classification")
    if not isinstance(classification, str) or not classification:
        raise HygieneMutatorError(
            "inventory entry classification must be a non-empty string for %s"
            % relative_path)
    if "mutation_eligible" not in raw_entry:
        raise HygieneMutatorError(
            "inventory entry mutation_eligible is required for %s" % relative_path)
    mutation_eligible = _require_exact_bool(
        raw_entry["mutation_eligible"],
        "inventory entry %s.mutation_eligible" % relative_path)
    if "quarantine_blocked" not in raw_entry:
        raise HygieneMutatorError(
            "inventory entry quarantine_blocked is required for %s" % relative_path)
    quarantine_blocked = _require_exact_bool(
        raw_entry["quarantine_blocked"],
        "inventory entry %s.quarantine_blocked" % relative_path)
    if "mutation_blockers" not in raw_entry:
        raise HygieneMutatorError(
            "inventory entry mutation_blockers is required for %s" % relative_path)
    mutation_blockers = _require_blocker_list(
        raw_entry["mutation_blockers"],
        "inventory entry %s.mutation_blockers" % relative_path)
    if "references" not in raw_entry:
        raise HygieneMutatorError(
            "inventory entry references is required for %s" % relative_path)
    references = raw_entry["references"]
    if not isinstance(references, dict):
        raise HygieneMutatorError(
            "inventory entry references must be an object for %s" % relative_path)
    for key in ("checkpoint", "production", "test"):
        if key not in references:
            raise HygieneMutatorError(
                "inventory entry references.%s is required for %s"
                % (key, relative_path))
    ref_checkpoint = _require_nonneg_int(
        references["checkpoint"],
        "inventory entry %s.references.checkpoint" % relative_path)
    ref_production = _require_nonneg_int(
        references["production"],
        "inventory entry %s.references.production" % relative_path)
    ref_test = _require_nonneg_int(
        references["test"],
        "inventory entry %s.references.test" % relative_path)
    if "sha256" not in raw_entry:
        raise HygieneMutatorError(
            "inventory entry sha256 is required for %s" % relative_path)
    sha256 = _require_sha256_hex(
        raw_entry["sha256"], "inventory entry %s.sha256" % relative_path)
    if "size" not in raw_entry:
        raise HygieneMutatorError(
            "inventory entry size is required for %s" % relative_path)
    size = _require_nonneg_int(
        raw_entry["size"], "inventory entry %s.size" % relative_path)
    live_abs = str(_resolve_live_absolute(live_root, relative_path))
    return {
        "path": relative_path,
        "live_abs": live_abs,
        "owner": owner,
        "classification": classification,
        "mutation_eligible": mutation_eligible,
        "quarantine_blocked": quarantine_blocked,
        "mutation_blockers": mutation_blockers,
        "sha256": sha256,
        "size": size,
        "references": {
            "checkpoint": ref_checkpoint,
            "production": ref_production,
            "test": ref_test,
        },
    }


def compute_eligibility(
    inventory: Any,
    protected: Any,
    *,
    live_root: Path,
    prohibited_root_patterns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Compute eligible / skipped / blocked targets. Read-only."""

    if not isinstance(inventory, dict):
        raise HygieneMutatorError("inventory must be a JSON object")
    entries = inventory.get("entries", [])
    if not isinstance(entries, list):
        raise HygieneMutatorError("inventory.entries must be a list")
    protected_paths = _validate_and_collect_protected_paths(protected)
    live_root = _lexical_absolute(live_root)
    # Approved categorical roots are immutable; callers may only add extras.
    prohibited = set(APPROVED_PROHIBITED_ROOTS)
    if prohibited_root_patterns is not None:
        prohibited.update(str(p) for p in prohibited_root_patterns)
    prohibited_root_patterns = tuple(sorted(prohibited))

    eligible_direct_delete: list[dict[str, Any]] = []
    eligible_quarantine_move: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for raw_entry in entries:
        record = _parse_inventory_entry(raw_entry, live_root=live_root)
        relative_path = record["path"]
        owner = record["owner"]
        classification = record["classification"]
        mutation_eligible = record["mutation_eligible"]
        quarantine_blocked = record["quarantine_blocked"]
        mutation_blockers = record["mutation_blockers"]
        live_abs = record["live_abs"]
        refs = record["references"]

        if not mutation_eligible:
            record["blocker"] = "mutation_eligible_false"
            blocked.append(record)
            continue
        if owner in DENIED_OWNERS:
            record["blocker"] = "denied_owner:%s" % owner
            blocked.append(record)
            continue
        if _is_medical_monitoring_path(relative_path):
            record["blocker"] = "medical_monitoring_path"
            blocked.append(record)
            continue
        if classification not in CANDIDATE_CLASSIFICATIONS:
            record["blocker"] = "non_candidate_classification:%s" % classification
            skipped.append(record)
            continue
        if quarantine_blocked:
            record["blocker"] = "quarantine_blocked"
            blocked.append(record)
            continue
        if mutation_blockers:
            record["blocker"] = "mutation_blockers:%s" % ",".join(mutation_blockers)
            blocked.append(record)
            continue
        if live_abs in protected_paths:
            record["blocker"] = "protected_intersection"
            blocked.append(record)
            continue
        if _is_under_prohibited_root(relative_path, prohibited_root_patterns):
            record["blocker"] = "prohibited_root"
            blocked.append(record)
            continue
        total_refs = refs["checkpoint"] + refs["production"] + refs["test"]
        if total_refs > 0:
            record["blocker"] = "has_references:%d" % total_refs
            blocked.append(record)
            continue

        # Operation type is derived only after exact inventory eligibility.
        if _is_direct_delete_candidate(relative_path):
            record["operation"] = "direct_delete"
            eligible_direct_delete.append(record)
        elif _is_quarantine_move_candidate(relative_path):
            record["operation"] = "quarantine_move"
            eligible_quarantine_move.append(record)
        else:
            record["blocker"] = "unknown_hygiene_category"
            skipped.append(record)

    authorized = len(eligible_direct_delete) + len(eligible_quarantine_move)
    return {
        "policy_id": MUTATOR_POLICY_ID,
        "live_root": str(live_root),
        "inventory_entry_count": len(entries),
        "eligible_direct_delete": eligible_direct_delete,
        "eligible_quarantine_move": eligible_quarantine_move,
        "eligible_direct_delete_count": len(eligible_direct_delete),
        "eligible_quarantine_move_count": len(eligible_quarantine_move),
        "skipped": skipped,
        "blocked": blocked,
        "skipped_count": len(skipped),
        "blocked_count": len(blocked),
        "protected_intersection_on_candidates": sum(
            1 for r in blocked if r.get("blocker") == "protected_intersection"),
        "quarantine_approved_field_present": "quarantine_approved" in inventory,
        "authorized_target_count": authorized,
    }


def verify_snapshot_hashes(
    inventory_path: Path,
    protected_path: Path,
    expected_inventory_sha256: str,
    expected_protected_sha256: str,
) -> None:
    actual_inv = sha256_file_path(inventory_path)
    if actual_inv != expected_inventory_sha256:
        raise HygieneMutatorError(
            "inventory file hash mismatch: expected %s, got %s (path=%s)"
            % (expected_inventory_sha256, actual_inv, inventory_path))
    actual_prot = sha256_file_path(protected_path)
    if actual_prot != expected_protected_sha256:
        raise HygieneMutatorError(
            "protected file hash mismatch: expected %s, got %s (path=%s)"
            % (expected_protected_sha256, actual_prot, protected_path))


def _write_path_map_atomic(path: Path, data: Mapping[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_existing_components_not_symlinked(path.parent, "PATH_MAP parent")
    if path.exists() or os.path.lexists(str(path)):
        _reject_if_symlink(path, "PATH_MAP path")
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(path))
        _fsync_dir(path.parent)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _assert_existing_components_not_symlinked(
        destination.parent, "atomic-copy destination parent")
    fd, tmp_name = tempfile.mkstemp(
        prefix=destination.name + ".", suffix=".tmp",
        dir=str(destination.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out_handle:
            with source.open("rb") as in_handle:
                shutil.copyfileobj(in_handle, out_handle, length=1024 * 1024)
            out_handle.flush()
            os.fsync(out_handle.fileno())
        os.replace(str(tmp_path), str(destination))
        _fsync_dir(destination.parent)
    except BaseException:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _deep_copy_path_map(path_map: Mapping[str, Any]) -> dict[str, Any]:
    import copy
    return copy.deepcopy(dict(path_map))


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _inventory_live_root(inventory: Mapping[str, Any]) -> Path:
    root = inventory.get("root")
    if not isinstance(root, str) or not root:
        raise HygieneMutatorError("inventory.root must be a non-empty string")
    if not os.path.isabs(root):
        raise HygieneMutatorError(
            "inventory.root must be an absolute path, got %r" % root)
    return _lexical_absolute(root)


def _eligible_by_abs_path(eligibility: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    by_abs: dict[str, dict[str, Any]] = {}
    for bucket in (
        eligibility["eligible_direct_delete"],
        eligibility["eligible_quarantine_move"],
    ):
        for record in bucket:
            key = str(_lexical_absolute(record["live_abs"]))
            if key in by_abs:
                raise HygieneMutatorError(
                    "duplicate eligible inventory target: %s" % key)
            by_abs[key] = record
    return by_abs


def _bind_path_map_to_eligibility(
    path_map: Mapping[str, Any],
    eligibility: Mapping[str, Any],
) -> None:
    """Require exact set equality between eligible inventory and PATH_MAP targets."""

    eligible = _eligible_by_abs_path(eligibility)
    eligible_keys = set(eligible.keys())
    seen: set[str] = set()
    for index, entry in enumerate(path_map["entries"]):
        if not isinstance(entry, dict):
            raise HygieneMutatorError(
                "PATH_MAP entry %d malformed: not an object" % index)
        try:
            old = str(_lexical_absolute(entry["old_locator"]))
        except Exception as exc:
            raise HygieneMutatorError(
                "PATH_MAP entry %d old_locator invalid: %s" % (index, exc)
            ) from exc
        if old in seen:
            raise HygieneMutatorError(
                "duplicate PATH_MAP target for %s" % old)
        seen.add(old)
        target = eligible.get(old)
        if target is None:
            continue  # collected below as extra
        if entry.get("operation") != target["operation"]:
            raise HygieneMutatorError(
                "PATH_MAP operation mismatch for %s: map=%r eligible=%r"
                % (old, entry.get("operation"), target["operation"]))
        if entry.get("owner") != target["owner"]:
            raise HygieneMutatorError(
                "PATH_MAP owner mismatch for %s: map=%r eligible=%r"
                % (old, entry.get("owner"), target["owner"]))
        if entry.get("source_sha256") != target["sha256"]:
            raise HygieneMutatorError(
                "PATH_MAP source SHA mismatch for %s" % old)
        if entry.get("size") != target["size"]:
            raise HygieneMutatorError(
                "PATH_MAP size mismatch for %s: map=%r eligible=%r"
                % (old, entry.get("size"), target["size"]))
        if type(entry.get("size")) is not int:
            raise HygieneMutatorError(
                "PATH_MAP size type coercion rejected for %s" % old)
        refs = target["references"]
        if refs["checkpoint"] or refs["production"] or refs["test"]:
            raise HygieneMutatorError(
                "eligible target unexpectedly has references: %s" % old)

    missing = sorted(eligible_keys - seen)
    extra = sorted(seen - eligible_keys)
    if missing or extra:
        raise HygieneMutatorError(
            "PATH_MAP/eligible set inequality: missing=%s extra=%s"
            % (missing, extra))


def _require_path_map_path(path_map_path: Path | None) -> Path:
    if path_map_path is None:
        raise HygieneMutatorError(
            "path_map_path is required for apply/restore durability")
    durable = _require_raw_absolute_path(path_map_path, "path_map_path")
    _assert_existing_components_not_symlinked(durable.parent, "PATH_MAP parent")
    if os.path.lexists(str(durable)):
        _reject_if_symlink(durable, "PATH_MAP path")
    return durable


def _assert_root_and_pin_identity(
    resolver: Any,
    *,
    quarantine_root: Path,
    expected_inventory_sha256: str,
    expected_protected_sha256: str,
) -> Path:
    caller_root = _assert_root_not_symlinked(
        quarantine_root, "caller quarantine_root", must_exist=False)
    map_root = _assert_root_not_symlinked(
        resolver.quarantine_root, "PATH_MAP quarantine_root", must_exist=False)
    if caller_root != map_root:
        raise HygieneMutatorError(
            "caller quarantine root %s does not match PATH_MAP root %s"
            % (caller_root, map_root))
    if resolver.expected_inventory_sha256 != expected_inventory_sha256:
        raise HygieneMutatorError(
            "PATH_MAP expected_inventory_sha256 does not match explicit argument")
    if resolver.expected_protected_sha256 != expected_protected_sha256:
        raise HygieneMutatorError(
            "PATH_MAP expected_protected_sha256 does not match explicit argument")
    return map_root


def _validate_committed_terminal(
    entry: Mapping[str, Any],
    *,
    map_root: Path,
    operation_quarantine_move: str,
) -> None:
    source_path = Path(entry["old_locator"])
    operation = entry["operation"]
    if operation == operation_quarantine_move:
        object_path = map_root / entry["new_locator"]
        if source_path.exists():
            raise HygieneMutatorError(
                "fabricated committed state for %s: source still present"
                % entry.get("id"))
        _verify_object_after_copy(object_path, entry)
        return
    # direct_delete
    if source_path.exists():
        raise HygieneMutatorError(
            "fabricated committed state for %s: source still present"
            % entry.get("id"))


def _entries_sharing_object(
    working_map: Mapping[str, Any],
    new_locator: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in working_map.get("entries", []):
        if not isinstance(raw, dict):
            continue
        if raw.get("new_locator") != new_locator:
            continue
        out.append(raw)
    return out


def _unresolved_entries_sharing_object(
    working_map: Mapping[str, Any],
    new_locator: str,
    *,
    exclude_entry_id: str | None = None,
) -> list[dict[str, Any]]:
    """Entries that still need a shared quarantine object (not yet restored)."""

    out: list[dict[str, Any]] = []
    for raw in _entries_sharing_object(working_map, new_locator):
        if exclude_entry_id is not None and raw.get("id") == exclude_entry_id:
            continue
        if raw.get("status") == "restored":
            continue
        out.append(raw)
    return out


def _destination_physically_restored(
    entry: Mapping[str, Any],
    *,
    live_root: Path,
) -> tuple[Path, os.stat_result]:
    """Require a hash-exact regular destination under live_root with no symlinks."""

    dest_path = Path(entry["old_locator"])
    if not os.path.lexists(str(dest_path)):
        raise HygieneMutatorError(
            "fabricated restored state for %s: destination absent"
            % entry.get("id"))
    try:
        dest_lex, dest_st = _assert_path_within_root_no_symlink(
            live_root, dest_path, label="restore destination", must_exist=True)
    except HygieneMutatorError as exc:
        msg = str(exc)
        if "symlink" in msg or "realpath escapes" in msg:
            raise HygieneMutatorError(
                "fabricated restored state for %s: destination path escapes "
                "or is reached through a symlink: %s"
                % (entry.get("id"), msg)
            ) from exc
        raise HygieneMutatorError(
            "fabricated restored state for %s: destination absent"
            % entry.get("id")
        ) from exc
    if dest_st is None:
        raise HygieneMutatorError(
            "fabricated restored state for %s: destination absent"
            % entry.get("id"))
    import stat as stat_mod
    if stat_is_symlink(dest_st) or not stat_mod.S_ISREG(dest_st.st_mode):
        raise HygieneMutatorError(
            "fabricated restored state for %s: destination must be a regular file"
            % entry.get("id"))
    actual = sha256_file(dest_lex)
    if actual != entry["source_sha256"]:
        raise HygieneMutatorError(
            "fabricated restored state for %s: destination hash mismatch"
            % entry.get("id"))
    if dest_st.st_size != entry["size"]:
        raise HygieneMutatorError(
            "fabricated restored state for %s: destination size mismatch"
            % entry.get("id"))
    return dest_lex, dest_st


def _assert_shared_object_group_ready_for_unlink(
    working_map: Mapping[str, Any],
    new_locator: str,
    *,
    live_root: Path,
    map_root: Path,
) -> None:
    """Read-only group gate: every shared reference must be durably restored.

    Status labels alone never authorize unlinking a content-addressed object.
    """

    group = _entries_sharing_object(working_map, new_locator)
    if not group:
        raise HygieneMutatorError(
            "shared object group empty for %s" % new_locator)
    for entry in group:
        if entry.get("status") != "restored":
            raise HygieneMutatorError(
                "shared object group incomplete for unlink: entry %s status %r"
                % (entry.get("id"), entry.get("status")))
        _destination_physically_restored(entry, live_root=live_root)
    object_path = map_root / new_locator
    _assert_path_within_root_no_symlink(
        map_root, object_path, label="quarantine object", must_exist=True)


def _assert_shared_group_recoverable_without_object(
    working_map: Mapping[str, Any],
    new_locator: str,
    *,
    live_root: Path,
    current_entry_id: str,
) -> None:
    """When the shared object is absent, every group destination must be valid."""

    group = _entries_sharing_object(working_map, new_locator)
    for entry in group:
        dest_path = Path(entry["old_locator"])
        try:
            _destination_physically_restored(entry, live_root=live_root)
        except HygieneMutatorError as exc:
            raise HygieneMutatorError(
                "shared quarantine object absent and group member %s lacks a "
                "valid destination (current=%s): %s"
                % (entry.get("id"), current_entry_id, exc)
            ) from exc
        _ = dest_path


def _validate_restored_terminal(
    entry: Mapping[str, Any],
    *,
    map_root: Path,
    live_root: Path,
    working_map: Mapping[str, Any] | None = None,
) -> None:
    object_path = map_root / entry["new_locator"]
    if object_path.exists() or os.path.lexists(str(object_path)):
        # Object may remain while unresolved peers still need it, or in the
        # crash window after every referencing entry is restored but before the
        # final shared-object unlink.
        _assert_path_within_root_no_symlink(
            map_root, object_path, label="quarantine object", must_exist=True)
        _verify_object_after_copy(object_path, entry)
    _destination_physically_restored(entry, live_root=live_root)
    _ = working_map


def _validate_copied_before_replay(
    entry: Mapping[str, Any],
    *,
    map_root: Path,
    operation_quarantine_move: str,
) -> None:
    """Explicit copied-state combinations before crash-replay mutation."""

    source_path = Path(entry["old_locator"])
    operation = entry["operation"]
    if operation == operation_quarantine_move:
        object_path = map_root / entry["new_locator"]
        _verify_object_after_copy(object_path, entry)
        if source_path.exists():
            _verify_source_before_removal(source_path, entry)
        return
    # direct_delete pre-delete marker: source may still exist or already be gone.
    if source_path.exists():
        _verify_source_before_removal(source_path, entry)


def _validate_on_disk_path_map_identity(
    path_map_path: Path,
    path_map: Mapping[str, Any],
) -> None:
    if not path_map_path.exists():
        return
    on_disk = _load_json(path_map_path)
    resolver_mod = _resolver()
    try:
        disk_resolver = resolver_mod.EvidenceLocatorResolver(on_disk)
        mem_resolver = resolver_mod.EvidenceLocatorResolver(path_map)
    except Exception as exc:
        raise HygieneMutatorError(
            "on-disk PATH_MAP identity validation failed: %s" % exc) from exc
    if disk_resolver.fingerprint() != mem_resolver.fingerprint():
        raise HygieneMutatorError(
            "on-disk PATH_MAP identity mismatch at %s" % path_map_path)


def _port_is_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _run_lsof(args: Sequence[str], *, timeout: float = LSOF_TIMEOUT_SECONDS,
              runner=None) -> subprocess.CompletedProcess[str]:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout < float("inf"):
        raise HygieneMutatorError("occupancy timeout must be finite and positive")
    try:
        return (runner or subprocess.run)(
            ["lsof", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise HygieneMutatorError(
            "required occupancy inspection command unavailable: lsof"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise HygieneMutatorError(
            "open-handle inspection timed out after %.1fs (treated as occupied): %s"
            % (timeout, " ".join(args))
        ) from exc


def builtin_occupancy_checker(targets: Sequence[Path], *, port_probe=None,
                              lsof_runner=None,
                              lsof_timeout: float = LSOF_TIMEOUT_SECONDS) -> list[str]:
    """Fail-closed built-in occupancy gate used when no checker is injected."""

    blockers: list[str] = []
    probe = port_probe or _port_is_listening
    def inspect_handles(args):
        return _run_lsof(args, timeout=lsof_timeout, runner=lsof_runner)

    for port in HYGIENE_PORTS:
        if probe(port):
            blockers.append("hygiene port %d has an active listener" % port)

    for target in targets:
        path = Path(target)
        if not path.exists():
            continue
        completed = inspect_handles(["-nP", str(path)])
        if completed.returncode not in (0, 1):
            raise HygieneMutatorError(
                "ambiguous open-handle inspection for %s: rc=%s stderr=%r"
                % (path, completed.returncode, completed.stderr.strip()))
        if completed.returncode == 0 and completed.stdout.strip():
            blockers.append("open handle on target %s" % path)

        # SQLite main DB sidecars: if target looks like a DB, inspect WAL/SHM.
        for sidecar in (Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            if not sidecar.exists():
                continue
            side = inspect_handles(["-nP", str(sidecar)])
            if side.returncode not in (0, 1):
                raise HygieneMutatorError(
                    "ambiguous SQLite sidecar inspection for %s: rc=%s"
                    % (sidecar, side.returncode))
            if side.returncode == 0 and side.stdout.strip():
                blockers.append("open handle on SQLite sidecar %s" % sidecar)

    # Process ownership probe for declared hygiene ports.
    for port in HYGIENE_PORTS:
        completed = inspect_handles(["-nP", "-iTCP:%d" % port, "-sTCP:LISTEN"])
        if completed.returncode not in (0, 1):
            raise HygieneMutatorError(
                "ambiguous process inspection for port %d: rc=%s"
                % (port, completed.returncode))
        if completed.returncode == 0 and completed.stdout.strip():
            if "hygiene port %d has an active listener" % port not in blockers:
                blockers.append(
                    "hygiene port %d held by process: %s"
                    % (port, completed.stdout.splitlines()[0][:200]))
    return blockers


def _resolve_occupancy_checker(
    occupancy_checker: OccupancyChecker | None,
) -> OccupancyChecker:
    if occupancy_checker is None:
        return builtin_occupancy_checker
    return occupancy_checker


def _invoke_occupancy_checker(
    checker: OccupancyChecker,
    targets: Sequence[Path],
) -> list[str]:
    """Fail closed unless the checker returns a non-string sequence of strings."""

    raw = checker(targets)
    if isinstance(raw, (str, bytes, bytearray)):
        raise HygieneMutatorError(
            "occupancy checker must return a non-string sequence of strings, "
            "got %s" % type(raw).__name__)
    if not isinstance(raw, Sequence):
        raise HygieneMutatorError(
            "occupancy checker must return a sequence of strings, got %s"
            % type(raw).__name__)
    blockers: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise HygieneMutatorError(
                "occupancy checker result[%d] must be a string, got %s"
                % (index, type(item).__name__))
        blockers.append(item)
    return blockers


def _verify_source_before_removal(source_path: Path, entry: Mapping[str, Any]) -> None:
    if entry.get("path_type") != "file":
        raise HygieneMutatorError(
            "entry %s path_type must be 'file', got %r"
            % (entry.get("id"), entry.get("path_type")))
    if not source_path.exists():
        raise HygieneMutatorError("source missing before removal: %s" % source_path)
    if source_path.is_symlink():
        raise HygieneMutatorError(
            "source must be a regular file, not a symlink: %s" % source_path)
    if not source_path.is_file():
        raise HygieneMutatorError("source must be a regular file: %s" % source_path)
    actual_hash = sha256_file(source_path)
    if actual_hash != entry["source_sha256"]:
        raise HygieneMutatorError(
            "source hash mismatch for %s: expected %s, got %s"
            % (source_path, entry["source_sha256"], actual_hash))
    if source_path.stat().st_size != entry["size"]:
        raise HygieneMutatorError(
            "source size mismatch for %s: expected %d, got %d"
            % (source_path, entry["size"], source_path.stat().st_size))


def _verify_object_after_copy(object_path: Path, entry: Mapping[str, Any]) -> None:
    if not object_path.exists():
        raise HygieneMutatorError(
            "quarantine object missing after copy: %s" % object_path)
    if object_path.is_symlink():
        raise HygieneMutatorError(
            "object must be a regular file, not a symlink: %s" % object_path)
    actual_hash = sha256_file(object_path)
    expected_hash = entry["destination_sha256"]
    if actual_hash != expected_hash:
        raise HygieneMutatorError(
            "object hash mismatch for %s: expected %s, got %s"
            % (object_path, expected_hash, actual_hash))
    if object_path.stat().st_size != entry["size"]:
        raise HygieneMutatorError(
            "object size mismatch for %s: expected %d, got %d"
            % (object_path, entry["size"], object_path.stat().st_size))


def _persist_path_map(
    path_map_path: Path,
    working_map: Mapping[str, Any],
    *,
    after_destructive: bool,
) -> None:
    try:
        _write_path_map_atomic(path_map_path, working_map)
    except Exception as exc:
        if after_destructive:
            raise HygieneMutatorError(
                "PATH_MAP persistence failed after destructive operation: %s" % exc
            ) from exc
        raise


def _prepare_authority_context(
    path_map: Mapping[str, Any],
    *,
    path_map_path: Path,
    quarantine_root: Path,
    inventory_path: Path,
    protected_path: Path,
    expected_inventory_sha256: str,
    expected_protected_sha256: str,
) -> tuple[Any, dict[str, Any], Path, dict[str, Any], dict[str, Any], Path]:
    resolver_mod = _resolver()
    try:
        resolver = resolver_mod.EvidenceLocatorResolver(path_map)
    except Exception as exc:
        raise HygieneMutatorError("PATH_MAP validation failed: %s" % exc) from exc

    verify_snapshot_hashes(
        inventory_path, protected_path,
        expected_inventory_sha256, expected_protected_sha256)

    inventory = _load_json(inventory_path)
    protected = _load_json(protected_path)
    if not isinstance(inventory, dict) or not isinstance(protected, dict):
        raise HygieneMutatorError("inventory/protected must be JSON objects")

    live_root = _assert_root_not_symlinked(
        _inventory_live_root(inventory), "inventory live_root", must_exist=True)
    map_root = _assert_root_and_pin_identity(
        resolver,
        quarantine_root=quarantine_root,
        expected_inventory_sha256=expected_inventory_sha256,
        expected_protected_sha256=expected_protected_sha256,
    )
    _validate_on_disk_path_map_identity(path_map_path, path_map)

    eligibility = compute_eligibility(inventory, protected, live_root=live_root)
    _bind_path_map_to_eligibility(resolver.path_map, eligibility)
    return resolver, _deep_copy_path_map(resolver.path_map), map_root, eligibility, inventory, live_root


def apply_hygiene(
    path_map: Mapping[str, Any],
    *,
    path_map_path: Path | None = None,
    quarantine_root: Path,
    inventory_path: Path,
    protected_path: Path,
    expected_inventory_sha256: str,
    expected_protected_sha256: str,
    occupancy_checker: OccupancyChecker | None = None,
) -> dict[str, Any]:
    """Execute quarantine-move / direct-delete with authority and crash safety."""

    resolver_mod = _resolver()
    OPERATION_QUARANTINE_MOVE = resolver_mod.OPERATION_QUARANTINE_MOVE
    durable_path = _require_path_map_path(path_map_path)

    resolver, working_map, map_root, _eligibility, _inventory, live_root = \
        _prepare_authority_context(
            path_map,
            path_map_path=durable_path,
            quarantine_root=quarantine_root,
            inventory_path=inventory_path,
            protected_path=protected_path,
            expected_inventory_sha256=expected_inventory_sha256,
            expected_protected_sha256=expected_protected_sha256,
        )

    has_started = any(
        e["status"] in ("committed", "copied")
        for e in working_map["entries"])
    if not has_started and map_root.exists():
        raise HygieneMutatorError(
            "quarantine root must not pre-exist on fresh apply: %s" % map_root)

    target_sources = [Path(entry["old_locator"]) for entry in working_map["entries"]]
    checker = _resolve_occupancy_checker(occupancy_checker)
    blockers = _invoke_occupancy_checker(checker, target_sources)
    if blockers:
        raise HygieneMutatorError(
            "occupancy blockers detected: %s" % "; ".join(blockers))

    # Persist validated pre-destructive state before any mutation artifact.
    _persist_path_map(durable_path, working_map, after_destructive=False)

    needs_quarantine_tree = any(
        e["operation"] == OPERATION_QUARANTINE_MOVE and e["status"] != "committed"
        for e in working_map["entries"])
    if needs_quarantine_tree:
        map_root.mkdir(parents=True, exist_ok=True)
        _assert_root_not_symlinked(map_root, "quarantine root", must_exist=True)

    results: list[dict[str, Any]] = []
    destructive_pending = False
    try:
        for entry in working_map["entries"]:
            entry_id = entry["id"]
            operation = entry["operation"]
            status = entry["status"]
            source_path = Path(entry["old_locator"])

            if status == "committed":
                _validate_committed_terminal(
                    entry,
                    map_root=map_root,
                    operation_quarantine_move=OPERATION_QUARANTINE_MOVE)
                results.append({
                    "id": entry_id, "operation": operation,
                    "status": "skipped", "reason": "already_committed"})
                continue

            if status not in ("planned", "copied"):
                raise HygieneMutatorError(
                    "entry %s has unexpected status %r "
                    "(expected planned/copied/committed)" % (entry_id, status))

            if operation == OPERATION_QUARANTINE_MOVE:
                object_path = map_root / entry["new_locator"]
                if status == "planned":
                    source_lex, source_st = _assert_path_within_root_no_symlink(
                        live_root, source_path, label="apply source",
                        must_exist=True)
                    _verify_source_before_removal(source_lex, entry)
                    if object_path.exists() or os.path.lexists(str(object_path)):
                        _assert_path_within_root_no_symlink(
                            map_root, object_path, label="quarantine object",
                            must_exist=True)
                        existing_hash = sha256_file(object_path)
                        if existing_hash != entry["destination_sha256"]:
                            raise HygieneMutatorError(
                                "destination collision at %s: existing %s != expected %s"
                                % (object_path, existing_hash,
                                   entry["destination_sha256"]))
                    else:
                        _assert_path_within_root_no_symlink(
                            map_root, object_path, label="quarantine object",
                            must_exist=False)
                        _atomic_copy(source_lex, object_path)
                        _assert_path_within_root_no_symlink(
                            map_root, object_path, label="quarantine object",
                            must_exist=True)
                    _verify_object_after_copy(object_path, entry)
                    entry["status"] = "copied"
                    _persist_path_map(
                        durable_path, working_map, after_destructive=False)
                    status = "copied"

                # Durable pre-delete ("copied"): validate combinations first.
                _validate_copied_before_replay(
                    entry,
                    map_root=map_root,
                    operation_quarantine_move=OPERATION_QUARANTINE_MOVE)
                if source_path.exists() or os.path.lexists(str(source_path)):
                    source_lex, source_st = _assert_path_within_root_no_symlink(
                        live_root, source_path, label="apply source",
                        must_exist=True)
                    if source_st is None:
                        raise HygieneMutatorError(
                            "apply source missing at destructive boundary: %s"
                            % source_lex)
                    destructive_pending = True
                    _safe_unlink_regular_file(source_lex, source_st)
                entry["status"] = "committed"
                destructive_pending = True
                _persist_path_map(
                    durable_path, working_map, after_destructive=True)
                destructive_pending = False
                results.append({
                    "id": entry_id, "operation": operation,
                    "status": "committed", "source": str(source_path)})
                continue

            # direct_delete: durable pre-delete marker is status "copied".
            if status == "planned":
                source_lex, source_st = _assert_path_within_root_no_symlink(
                    live_root, source_path, label="apply source",
                    must_exist=True)
                _verify_source_before_removal(source_lex, entry)
                entry["status"] = "copied"
                _persist_path_map(
                    durable_path, working_map, after_destructive=False)
                status = "copied"

            _validate_copied_before_replay(
                entry,
                map_root=map_root,
                operation_quarantine_move=OPERATION_QUARANTINE_MOVE)
            if source_path.exists() or os.path.lexists(str(source_path)):
                source_lex, source_st = _assert_path_within_root_no_symlink(
                    live_root, source_path, label="apply source",
                    must_exist=True)
                if source_st is None:
                    raise HygieneMutatorError(
                        "apply source missing at destructive boundary: %s"
                        % source_lex)
                destructive_pending = True
                _safe_unlink_regular_file(source_lex, source_st)
            entry["status"] = "committed"
            destructive_pending = True
            _persist_path_map(durable_path, working_map, after_destructive=True)
            destructive_pending = False
            results.append({
                "id": entry_id, "operation": operation,
                "status": "committed", "source": str(source_path)})
    except BaseException:
        if destructive_pending:
            _persist_path_map(durable_path, working_map, after_destructive=True)
        raise

    return {
        "mode": "apply",
        "policy_id": MUTATOR_POLICY_ID,
        "quarantine_root": str(map_root),
        "entry_count": len(working_map["entries"]),
        "committed_count": sum(1 for r in results if r["status"] == "committed"),
        "skipped_count": sum(1 for r in results if r["status"] == "skipped"),
        "results": results,
    }


def restore_hygiene(
    path_map: Mapping[str, Any],
    *,
    path_map_path: Path | None = None,
    quarantine_root: Path,
    inventory_path: Path,
    protected_path: Path,
    expected_inventory_sha256: str,
    expected_protected_sha256: str,
    occupancy_checker: OccupancyChecker | None = None,
) -> dict[str, Any]:
    """Restore quarantined objects with explicit crash-window handling."""

    resolver_mod = _resolver()
    OPERATION_QUARANTINE_MOVE = resolver_mod.OPERATION_QUARANTINE_MOVE
    durable_path = _require_path_map_path(path_map_path)

    resolver, working_map, map_root, _eligibility, _inventory, live_root = \
        _prepare_authority_context(
            path_map,
            path_map_path=durable_path,
            quarantine_root=quarantine_root,
            inventory_path=inventory_path,
            protected_path=protected_path,
            expected_inventory_sha256=expected_inventory_sha256,
            expected_protected_sha256=expected_protected_sha256,
        )
    if map_root.exists():
        _assert_root_not_symlinked(map_root, "quarantine root", must_exist=True)

    target_dests = [
        Path(entry["old_locator"]) for entry in working_map["entries"]
        if entry["operation"] == OPERATION_QUARANTINE_MOVE
    ]
    checker = _resolve_occupancy_checker(occupancy_checker)
    blockers = _invoke_occupancy_checker(checker, target_dests)
    if blockers:
        raise HygieneMutatorError(
            "occupancy blockers detected: %s" % "; ".join(blockers))

    _persist_path_map(durable_path, working_map, after_destructive=False)

    results: list[dict[str, Any]] = []
    destructive_pending = False
    try:
        for entry in working_map["entries"]:
            entry_id = entry["id"]
            operation = entry["operation"]
            status = entry["status"]

            if operation != OPERATION_QUARANTINE_MOVE:
                results.append({
                    "id": entry_id, "operation": operation,
                    "status": "skipped", "reason": "not_a_move"})
                continue

            if status == "restored":
                _validate_restored_terminal(
                    entry,
                    map_root=map_root,
                    live_root=live_root,
                    working_map=working_map)
                object_path = map_root / entry["new_locator"]
                if os.path.lexists(str(object_path)):
                    peers = _unresolved_entries_sharing_object(
                        working_map, entry["new_locator"])
                    if not peers:
                        # All statuses say restored: only unlink after every
                        # destination is physically valid under live_root.
                        _assert_shared_object_group_ready_for_unlink(
                            working_map,
                            entry["new_locator"],
                            live_root=live_root,
                            map_root=map_root)
                        object_lex, object_st = _assert_path_within_root_no_symlink(
                            map_root, object_path, label="quarantine object",
                            must_exist=True)
                        if object_st is None:
                            raise HygieneMutatorError(
                                "quarantine object missing before final unlink: %s"
                                % object_path)
                        destructive_pending = True
                        _safe_unlink_regular_file(object_lex, object_st)
                        _persist_path_map(
                            durable_path, working_map, after_destructive=True)
                        destructive_pending = False
                    # else: unresolved peers still need the shared object.
                results.append({
                    "id": entry_id, "operation": operation,
                    "status": "skipped", "reason": "already_restored"})
                continue

            if status not in ("committed", "copied"):
                raise HygieneMutatorError(
                    "entry %s cannot restore from status %r "
                    "(expected committed/copied)" % (entry_id, status))

            if status == "copied":
                # Copied during apply means object exists; restore treats it as
                # a recoverable quarantine object still awaiting commit/restore.
                _validate_copied_before_replay(
                    entry,
                    map_root=map_root,
                    operation_quarantine_move=OPERATION_QUARANTINE_MOVE)

            object_path = map_root / entry["new_locator"]
            dest_path = Path(entry["old_locator"])
            object_lexists = os.path.lexists(str(object_path))
            dest_lexists = os.path.lexists(str(dest_path))

            if object_lexists:
                object_lex, object_st = _assert_path_within_root_no_symlink(
                    map_root, object_path, label="quarantine object",
                    must_exist=True)
                if object_st is None:
                    raise HygieneMutatorError(
                        "quarantine object missing during restore: %s"
                        % object_path)
                if object_path.is_symlink() or not object_path.is_file():
                    raise HygieneMutatorError(
                        "quarantine object must be a regular file: %s"
                        % object_path)
                actual_hash = sha256_file(object_path)
                if actual_hash != entry["destination_sha256"]:
                    raise HygieneMutatorError(
                        "object hash mismatch during restore for %s: "
                        "expected %s, got %s"
                        % (object_path, entry["destination_sha256"], actual_hash))
                if dest_lexists:
                    dest_lex, _dest_st = _assert_path_within_root_no_symlink(
                        live_root, dest_path, label="restore destination",
                        must_exist=True)
                    dest_hash = sha256_file(dest_lex)
                    if dest_hash != entry["source_sha256"]:
                        raise HygieneMutatorError(
                            "restore destination exists with different hash: %s "
                            "(existing %s != expected %s)"
                            % (dest_path, dest_hash, entry["source_sha256"]))
                else:
                    _assert_path_within_root_no_symlink(
                        live_root, dest_path, label="restore destination",
                        must_exist=False)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    _assert_path_within_root_no_symlink(
                        live_root, dest_path.parent,
                        label="restore destination parent",
                        must_exist=True)
                    _atomic_copy(object_path, dest_path)
                    dest_lex, _dest_st = _assert_path_within_root_no_symlink(
                        live_root, dest_path, label="restore destination",
                        must_exist=True)
                    restored_hash = sha256_file(dest_lex)
                    if restored_hash != entry["source_sha256"]:
                        raise HygieneMutatorError(
                            "restored file hash mismatch for %s: expected %s, got %s"
                            % (dest_path, entry["source_sha256"], restored_hash))
                # Tentatively mark restored in memory, then either keep the
                # shared object for unresolved peers or unlink only after the
                # full group passes physical validation.
                prior_status = status
                entry["status"] = "restored"
                peers = _unresolved_entries_sharing_object(
                    working_map, entry["new_locator"])
                if not peers:
                    try:
                        _assert_shared_object_group_ready_for_unlink(
                            working_map,
                            entry["new_locator"],
                            live_root=live_root,
                            map_root=map_root)
                    except HygieneMutatorError:
                        entry["status"] = prior_status
                        raise
                    object_lex, object_st = _assert_path_within_root_no_symlink(
                        map_root, object_path, label="quarantine object",
                        must_exist=True)
                    if object_st is None:
                        entry["status"] = prior_status
                        raise HygieneMutatorError(
                            "quarantine object missing before final unlink: %s"
                            % object_path)
                    destructive_pending = True
                    _safe_unlink_regular_file(object_lex, object_st)
                else:
                    destructive_pending = True
                _persist_path_map(durable_path, working_map, after_destructive=True)
                destructive_pending = False
                results.append({
                    "id": entry_id, "operation": operation,
                    "status": "restored", "destination": str(dest_path)})
                continue

            if dest_lexists:
                # Crash window: object already removed; destination must match.
                # Before advancing status, every shared-group destination must
                # already be physically valid — otherwise fail closed.
                try:
                    _assert_shared_group_recoverable_without_object(
                        working_map,
                        entry["new_locator"],
                        live_root=live_root,
                        current_entry_id=str(entry_id))
                except HygieneMutatorError:
                    # Also cover the single-entry case via direct dest check.
                    # For multi-entry groups the helper already failed closed.
                    raise
                dest_lex, _dest_st = _assert_path_within_root_no_symlink(
                    live_root, dest_path, label="restore destination",
                    must_exist=True)
                dest_hash = sha256_file(dest_lex)
                if dest_hash != entry["source_sha256"]:
                    raise HygieneMutatorError(
                        "restore destination exists with different hash: %s "
                        "(existing %s != expected %s)"
                        % (dest_path, dest_hash, entry["source_sha256"]))
                entry["status"] = "restored"
                # Advance any other group members whose destinations are already
                # valid and whose status is still committed/copied.
                for peer in _entries_sharing_object(
                        working_map, entry["new_locator"]):
                    if peer.get("id") == entry_id:
                        continue
                    if peer.get("status") == "restored":
                        continue
                    _destination_physically_restored(peer, live_root=live_root)
                    peer["status"] = "restored"
                destructive_pending = True
                _persist_path_map(durable_path, working_map, after_destructive=True)
                destructive_pending = False
                results.append({
                    "id": entry_id, "operation": operation,
                    "status": "restored", "destination": str(dest_path)})
                continue

            raise HygieneMutatorError(
                "quarantine object missing during restore: %s" % object_path)
    except BaseException:
        if destructive_pending:
            _persist_path_map(durable_path, working_map, after_destructive=True)
        raise

    return {
        "mode": "restore",
        "policy_id": MUTATOR_POLICY_ID,
        "quarantine_root": str(map_root),
        "entry_count": len(working_map["entries"]),
        "restored_count": sum(1 for r in results if r["status"] == "restored"),
        "skipped_count": sum(1 for r in results if r["status"] == "skipped"),
        "results": results,
    }


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(
        description="Protocol v3 Phase 0 Task 0.5 recoverable-hygiene mutator.")
    parser.add_argument(
        "--mode", choices=("dry-run", "apply", "restore"), default="dry-run",
        help="dry-run (default): compute eligibility only. "
             "apply: execute quarantine-move/direct-delete. "
             "restore: restore quarantined objects to live.")
    parser.add_argument("--path-map", type=Path, help="PATH_MAP.json path")
    parser.add_argument("--inventory", type=Path, required=True,
                        help="repository_hygiene_inventory.json path")
    parser.add_argument("--protected", type=Path, required=True,
                        help="immutable_protected_assets.json path")
    parser.add_argument("--live-root", type=Path,
                        help="optional live root; must match inventory.root")
    parser.add_argument("--quarantine-root", type=Path,
                        help="quarantine root (must match PATH_MAP root)")
    parser.add_argument("--expected-inventory-sha256", default="",
                        help="required for apply/restore")
    parser.add_argument("--expected-protected-sha256", default="",
                        help="required for apply/restore")
    args = parser.parse_args(list(argv) if argv else None)

    inventory = _load_json(args.inventory)
    protected = _load_json(args.protected)
    if not isinstance(inventory, dict):
        raise SystemExit("inventory must be a JSON object")

    live_root = _inventory_live_root(inventory)
    if args.live_root is not None:
        caller_live = _lexical_absolute(args.live_root)
        if caller_live != live_root:
            raise SystemExit(
                "caller --live-root %s does not match inventory.root %s"
                % (caller_live, live_root))

    if args.mode == "dry-run":
        report = compute_eligibility(
            inventory, protected, live_root=live_root)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if not args.expected_inventory_sha256 or not args.expected_protected_sha256:
        parser.error(
            "--expected-inventory-sha256 and --expected-protected-sha256 "
            "are required for --mode %s" % args.mode)
    if args.path_map is None:
        parser.error("--path-map is required for --mode %s" % args.mode)
    if args.quarantine_root is None:
        parser.error("--quarantine-root is required for --mode %s" % args.mode)

    path_map = _load_json(args.path_map)
    # CLI never injects occupancy_checker — built-in fail-closed checker runs.
    if args.mode == "apply":
        report = apply_hygiene(
            path_map, path_map_path=args.path_map,
            quarantine_root=args.quarantine_root,
            inventory_path=args.inventory, protected_path=args.protected,
            expected_inventory_sha256=args.expected_inventory_sha256,
            expected_protected_sha256=args.expected_protected_sha256)
    else:
        report = restore_hygiene(
            path_map, path_map_path=args.path_map,
            quarantine_root=args.quarantine_root,
            inventory_path=args.inventory, protected_path=args.protected,
            expected_inventory_sha256=args.expected_inventory_sha256,
            expected_protected_sha256=args.expected_protected_sha256)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
