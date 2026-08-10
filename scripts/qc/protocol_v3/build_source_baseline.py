from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
from datetime import datetime, timezone
from typing import Dict, Iterable, Iterator, List, Mapping, Sequence


class BaselineError(RuntimeError):
    """Raised when the source-only boundary cannot be proven safe."""


POLICY_VERSION = "mw-protocol-v3-source-baseline-v3"

ROOT_ALLOWED_FILES = {
    "AGENTS.md",
    "README.md",
    "pytest.ini",
}

# These files are required by Phase 0 toolchain reproduction. They are exact
# allowlist entries rather than permission to copy the rest of either parent.
EXACT_ALLOWED_FILES = {
    "frontend/AGENTS.md",
    "frontend/index.html",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/pnpm-lock.yaml",
    "frontend/pnpm-workspace.yaml",
    "frontend/vite.config.mjs",
    "services/api/requirements-medical-writing.txt",
    "services/api/requirements-vlm.txt",
    "plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md",
    "plans/mw_system_rearchitecture_design_decisions_20260808.md",
    ".hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md",
}

# These are application source/test modules, not authentication material.  Keep
# the exemption exact so the generic filename heuristic cannot silently omit
# an import dependency while unrelated token-named files remain outside it.
EXACT_TOKEN_SOURCE_FILES = {
    "packages/contracts/workbench_contracts/protected_tokens.py",
    "services/api/app/medical_writing_protected_tokens.py",
    "tests/test_medical_writing_protected_tokens.py",
}

ALLOWED_PREFIXES = (
    "packages/contracts",
    "services/api/app",
    "frontend/src",
    "frontend/tests",
    "tests",
    "scripts",
    "tools",
    "config",
    "deploy",
)

POC_PREFIX = "pocs/protocol_v3"
POC_ALLOWED_SUFFIXES = {
    ".py",
    ".mjs",
    ".jsx",
    ".json",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".cs",
    ".csproj",
    ".lock",
    ".txt",
}

DENIED_DIRECTORY_NAMES = {
    ".git",
    ".npm-cache",
    ".playwright-cli",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vite",
    "__pycache__",
    "archives",
    "backups",
    "cache",
    "caches",
    ".cache",
    "dist",
    "evidence",
    "logs",
    "node_modules",
    "records",
    "results",
    "runs",
    "runtime",
    "source_backups",
}

DENIED_SUFFIXES = {
    ".db",
    ".docx",
    ".key",
    ".pdf",
    ".pem",
    ".pfx",
    ".pyc",
    ".sqlite",
    ".sqlite3",
    ".wal",
    ".shm",
}

DENIED_EXACT_FILES = {
    ".DS_Store",
    ".env",
    "frontend/.DS_Store",
    "frontend/.npmrc",
}

SPECIAL_DENIED_PREFIXES = {
    "tools/openxml_docx_validator/bin/Release",
    "tools/openxml_docx_validator/obj",
}

PLAN_POC_PATTERN = re.compile(r"pocs/protocol_v3/[A-Za-z0-9_.\-/]+")
RUNTIME_STATE_FILE_PATTERN = re.compile(
    r"^runtime(?:[-_].*)?\.(?:json|jsonl|toml|ya?ml)$",
    flags=re.IGNORECASE,
)


def validate_relative_path(value: str) -> str:
    if not value or "\x00" in value:
        raise BaselineError("relative path is empty or contains NUL")
    path = PurePosixPath(value)
    if path.is_absolute() or value in {".", ".."} or any(part in {"", ".", ".."} for part in path.parts):
        raise BaselineError("unsafe relative path: %r" % value)
    normalized = path.as_posix()
    if normalized != value.replace(os.sep, "/"):
        raise BaselineError("non-canonical relative path: %r" % value)
    return normalized


def _has_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _is_denied_directory_name(name: str) -> bool:
    return name in DENIED_DIRECTORY_NAMES or name.endswith("_evidence")


def _contains_denied_directory(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return any(_is_denied_directory_name(part) for part in parts[:-1])


def _looks_sensitive(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    if path in EXACT_TOKEN_SOURCE_FILES:
        return False
    if path == "config/ai.env.example":
        return False
    if name in {".env", ".npmrc"}:
        return True
    if name.startswith(".env.") and not name.endswith(".example"):
        return True
    if any(token in name for token in ("credential", "private_key", "secret", "token")):
        return True
    return False


def is_source_candidate(relative_path: str) -> bool:
    try:
        path = validate_relative_path(relative_path)
    except BaselineError:
        return False

    if (
        path in DENIED_EXACT_FILES
        or PurePosixPath(path).name == ".DS_Store"
        or _contains_denied_directory(path)
        or _looks_sensitive(path)
    ):
        return False
    if any(_has_prefix(path, prefix) for prefix in SPECIAL_DENIED_PREFIXES):
        return False
    name = PurePosixPath(path).name.lower()
    if (
        PurePosixPath(path).suffix.lower() in DENIED_SUFFIXES
        or name.endswith(("-wal", "-shm"))
        or (
            _has_prefix(path, "services/api/app")
            and RUNTIME_STATE_FILE_PATTERN.fullmatch(name)
        )
    ):
        return False

    if path in ROOT_ALLOWED_FILES or path in EXACT_ALLOWED_FILES:
        return True
    if _has_prefix(path, POC_PREFIX):
        return PurePosixPath(path).suffix.lower() in POC_ALLOWED_SUFFIXES
    return any(_has_prefix(path, prefix) for prefix in ALLOWED_PREFIXES)


def _should_prune_directory(relative_path: str) -> bool:
    path = validate_relative_path(relative_path)
    parts = PurePosixPath(path).parts
    if any(_is_denied_directory_name(part) for part in parts):
        return True
    return any(_has_prefix(path, prefix) for prefix in SPECIAL_DENIED_PREFIXES)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def iter_source_paths(root: Path) -> Iterator[Path]:
    root = root.resolve(strict=True)
    candidates: Dict[str, Path] = {}

    for relative in sorted(ROOT_ALLOWED_FILES | EXACT_ALLOWED_FILES):
        path = root / relative
        if path.exists() or path.is_symlink():
            candidates[relative] = path

    roots_to_walk = list(ALLOWED_PREFIXES) + [POC_PREFIX]
    for prefix in roots_to_walk:
        start = root / prefix
        if not start.exists():
            continue
        if start.is_symlink():
            raise BaselineError("allowlisted root cannot be a symlink: %s" % prefix)
        for current, dirnames, filenames in os.walk(str(start), followlinks=False):
            current_path = Path(current)
            relative_current = current_path.relative_to(root).as_posix()
            kept_dirs: List[str] = []
            for dirname in sorted(dirnames):
                relative_dir = (PurePosixPath(relative_current) / dirname).as_posix()
                full_dir = current_path / dirname
                if full_dir.is_symlink():
                    raise BaselineError("directory symlink is not allowed: %s" % relative_dir)
                if not _should_prune_directory(relative_dir):
                    kept_dirs.append(dirname)
            dirnames[:] = kept_dirs
            for filename in sorted(filenames):
                full_path = current_path / filename
                relative = full_path.relative_to(root).as_posix()
                if is_source_candidate(relative):
                    candidates[relative] = full_path

    for relative in sorted(candidates):
        yield candidates[relative]


def _entry_for_path(root: Path, path: Path) -> Mapping[str, object]:
    relative = path.relative_to(root).as_posix()
    validate_relative_path(relative)
    if not is_source_candidate(relative):
        raise BaselineError("path escaped source policy: %s" % relative)

    metadata = path.lstat()
    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISLNK(metadata.st_mode):
        target = os.readlink(str(path))
        if os.path.isabs(target):
            raise BaselineError("absolute symlink target is not allowed: %s" % relative)
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise BaselineError("symlink escapes source root: %s" % relative) from exc
        if not resolved.is_file():
            raise BaselineError("symlink target must be a regular file: %s" % relative)
        resolved_relative = resolved.relative_to(root).as_posix()
        if not is_source_candidate(resolved_relative):
            raise BaselineError("symlink target is outside source policy: %s" % relative)
        return {
            "path": relative,
            "type": "symlink",
            "size": len(target.encode("utf-8")),
            "sha256": _sha256_bytes(target.encode("utf-8")),
            "resolved_sha256": _sha256_file(resolved),
            "link_target": target,
            "mode": mode,
            "mtime_ns": metadata.st_mtime_ns,
        }
    if not stat.S_ISREG(metadata.st_mode):
        raise BaselineError("only regular files and safe symlinks are allowed: %s" % relative)
    return {
        "path": relative,
        "type": "file",
        "size": metadata.st_size,
        "sha256": _sha256_file(path),
        "mode": mode,
        "mtime_ns": metadata.st_mtime_ns,
    }


def _material_fingerprint(entries: Sequence[Mapping[str, object]]) -> str:
    material = []
    for entry in entries:
        material.append(
            {
                key: entry[key]
                for key in ("path", "type", "size", "sha256", "resolved_sha256", "link_target", "mode")
                if key in entry
            }
        )
    encoded = json.dumps(material, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _sha256_bytes(encoded)


def build_manifest(root: Path, task_id: str, plan_poc_paths: Sequence[str] = ()) -> Mapping[str, object]:
    root = root.resolve(strict=True)
    entries = [_entry_for_path(root, path) for path in iter_source_paths(root)]
    if not entries:
        raise BaselineError("source allowlist produced no files")
    paths = [str(entry["path"]) for entry in entries]
    if len(paths) != len(set(paths)):
        raise BaselineError("source manifest contains duplicate paths")
    for required in ("AGENTS.md", "frontend/package.json", "services/api/app/main.py"):
        if (root / required).exists() and required not in paths:
            raise BaselineError("required source path missing from manifest: %s" % required)
    return {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "task_id": task_id,
        "source_root": str(root),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content_fingerprint": _material_fingerprint(entries),
        "entry_count": len(entries),
        "regular_file_count": sum(1 for entry in entries if entry["type"] == "file"),
        "symlink_count": sum(1 for entry in entries if entry["type"] == "symlink"),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "plan_poc_paths": list(plan_poc_paths),
        "entries": entries,
    }


def validate_plan_poc_paths(plan_text: str) -> List[str]:
    matches = []
    for match in PLAN_POC_PATTERN.findall(plan_text):
        candidate = match.rstrip("/.,;:)]}`")
        suffix = PurePosixPath(candidate).suffix.lower()
        if not suffix:
            continue
        if not is_source_candidate(candidate):
            raise BaselineError("planned PoC source path is outside source policy: %s" % candidate)
        matches.append(candidate)
    return sorted(set(matches))


def create_source_tar(root: Path, manifest: Mapping[str, object], tar_path: Path) -> None:
    root = root.resolve(strict=True)
    tar_path = tar_path.absolute()
    if tar_path.exists():
        raise BaselineError("tar target already exists: %s" % tar_path)
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(str(tar_path), "w", format=tarfile.PAX_FORMAT) as archive:
        for raw_entry in manifest["entries"]:
            entry = dict(raw_entry)
            relative = validate_relative_path(str(entry["path"]))
            source = root / relative
            info = archive.gettarinfo(str(source), arcname=relative)
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            info.mtime = int(int(entry["mtime_ns"]) / 1_000_000_000)
            if entry["type"] == "file":
                with source.open("rb") as handle:
                    archive.addfile(info, handle)
            elif entry["type"] == "symlink":
                archive.addfile(info)
            else:
                raise BaselineError("unknown manifest entry type: %r" % entry["type"])


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def build_snapshot(live_root: Path, snapshot_root: Path, task_id: str, plan_path: Path) -> Mapping[str, object]:
    live_root = live_root.resolve(strict=True)
    snapshot_root = snapshot_root.absolute()
    if snapshot_root.exists():
        raise BaselineError("snapshot target already exists: %s" % snapshot_root)
    plan_text = plan_path.read_text(encoding="utf-8")
    plan_poc_paths = validate_plan_poc_paths(plan_text)
    manifest = build_manifest(live_root, task_id=task_id, plan_poc_paths=plan_poc_paths)
    snapshot_root.mkdir(parents=True, exist_ok=False)
    manifest_path = snapshot_root / "manifest.json"
    tar_path = snapshot_root / "source.tar"
    _write_json_atomic(manifest_path, manifest)
    create_source_tar(live_root, manifest, tar_path)
    manifest_sha = _sha256_file(manifest_path)
    tar_sha = _sha256_file(tar_path)
    checksum_path = snapshot_root / "manifest.sha256"
    checksum_path.write_text(
        "%s  manifest.json\n%s  source.tar\n" % (manifest_sha, tar_sha), encoding="utf-8"
    )
    return {
        "task_id": task_id,
        "snapshot_root": str(snapshot_root),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "tar_path": str(tar_path),
        "tar_sha256": tar_sha,
        "entry_count": manifest["entry_count"],
        "total_bytes": manifest["total_bytes"],
        "content_fingerprint": manifest["content_fingerprint"],
        "plan_poc_path_count": len(plan_poc_paths),
    }


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Build a fail-closed Protocol v3 source-only baseline.")
    parser.add_argument("--live-root", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--plan-path", required=True, type=Path)
    args = parser.parse_args(list(argv) if argv else None)
    result = build_snapshot(args.live_root, args.snapshot_root, args.task_id, args.plan_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
