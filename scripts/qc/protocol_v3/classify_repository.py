from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set


class HygieneError(RuntimeError):
    """Raised when repository classification cannot produce an auditable inventory."""


TEXT_SUFFIXES = {
    ".cfg", ".cs", ".csproj", ".css", ".html", ".ini", ".js", ".json",
    ".jsonl", ".jsx", ".lock", ".md", ".mjs", ".py", ".sh", ".toml",
    ".ts", ".tsx", ".txt", ".yaml", ".yml",
}
PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_.@+-]+(?:/[A-Za-z0-9_.@+ -]+)+|[A-Za-z0-9_.@+-]+\.[A-Za-z0-9]{1,12}")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
REFERENCE_LINE_RE = re.compile(r"\b(?:from|import|require|include_router|route|router|href|src)\b")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_rules(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "reuse", "migrate_then_retire", "authority_regression", "historical_archive",
        "regenerable", "quarantine", "protected_out_of_scope",
    }
    actual = set(payload.get("classifications", []))
    if actual != expected:
        raise HygieneError("classification set mismatch: %r" % sorted(actual))
    if not payload.get("rules") or not payload.get("default"):
        raise HygieneError("rules and default disposition are required")
    return payload


def _matches(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(path, pattern) for pattern in patterns)


def classify_path(path: str, rules: Mapping[str, object]) -> Mapping[str, object]:
    for raw_rule in rules["rules"]:
        rule = dict(raw_rule)
        if not _matches(path, rule.get("patterns", [])):
            continue
        if _matches(path, rule.get("exclude_patterns", [])):
            continue
        return {
            "classification": rule["classification"],
            "owner": rule["owner"],
            "rule_id": rule["id"],
            "reason": rule["reason"],
            "quarantine_blocked": bool(rule.get("quarantine_blocked", False)),
        }
    default = dict(rules["default"])
    return {
        "classification": default["classification"],
        "owner": default["owner"],
        "rule_id": "default_unresolved",
        "reason": default["reason"],
        "quarantine_blocked": bool(default.get("quarantine_blocked", True)),
    }


def _iter_repository_paths(root: Path) -> List[Path]:
    paths: List[Path] = []
    for current, dirnames, filenames in os.walk(str(root), topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: List[str] = []
        for dirname in sorted(dirnames):
            path = current_path / dirname
            if path.is_symlink():
                paths.append(path)
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            paths.append(current_path / filename)
    return sorted(paths, key=lambda item: item.relative_to(root).as_posix())


def _metadata_for_path(root: Path, path: Path) -> MutableMapping[str, object]:
    relative = path.relative_to(root).as_posix()
    before = path.lstat()
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISLNK(before.st_mode):
        link_target = os.readlink(str(path))
        resolved = path.resolve(strict=False)
        escapes_root = False
        try:
            resolved.relative_to(root)
        except ValueError:
            escapes_root = True
        resolved_sha = None
        if not escapes_root and resolved.is_file():
            resolved_sha = _sha256_file(resolved)
        return {
            "path": relative,
            "path_type": "symlink",
            "size": len(link_target.encode("utf-8")),
            "mtime_ns": before.st_mtime_ns,
            "mode": mode,
            "sha256": _sha256_bytes(link_target.encode("utf-8")),
            "link_target": link_target,
            "resolved_path": str(resolved),
            "resolved_sha256": resolved_sha,
            "escapes_root": escapes_root,
        }
    if not stat.S_ISREG(before.st_mode):
        raise HygieneError("unsupported repository path type: %s" % relative)
    digest = _sha256_file(path)
    after = path.lstat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size, after.st_mtime_ns, after.st_ino
    ):
        raise HygieneError("path changed while hashing: %s" % relative)
    return {
        "path": relative,
        "path_type": "file",
        "size": after.st_size,
        "mtime_ns": after.st_mtime_ns,
        "mode": mode,
        "sha256": digest,
        "link_target": None,
        "resolved_path": None,
        "resolved_sha256": None,
        "escapes_root": False,
    }


def _reference_surface(path: str) -> Optional[str]:
    if path.startswith(("services/api/app/", "frontend/src/", "packages/contracts/")):
        return "production"
    if path.startswith(("tests/", "frontend/tests/")):
        return "test"
    if path.startswith((
        "context/", "plans/", "runs/", "reviews/", "metrics/", "prompts/",
        "records/", "evidence/",
    )):
        return "checkpoint"
    return None


def _reference_tokens(path: Path) -> Set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    tokens = {token.strip("'\"`()[]{}:,;") for token in PATH_TOKEN_RE.findall(text)}
    for line in text.splitlines():
        if REFERENCE_LINE_RE.search(line):
            tokens.update(IDENTIFIER_RE.findall(line))
    return {token for token in tokens if token}


def _build_reference_index(
    root: Path,
    entries: Sequence[Mapping[str, object]],
    max_bytes: int,
) -> Mapping[str, Counter]:
    indexes = {"production": Counter(), "test": Counter(), "checkpoint": Counter()}
    for entry in entries:
        path = str(entry["path"])
        surface = _reference_surface(path)
        if surface is None or entry["path_type"] != "file" or int(entry["size"]) > max_bytes:
            continue
        if PurePosixPath(path).suffix.lower() not in TEXT_SUFFIXES:
            continue
        for token in _reference_tokens(root / path):
            indexes[surface][token] += 1
    return indexes


def _reference_counts(path: str, indexes: Mapping[str, Counter]) -> Mapping[str, int]:
    pure = PurePosixPath(path)
    keys = {path, pure.name, pure.stem}
    counts = {}
    for surface, index in indexes.items():
        counts[surface] = sum(int(index.get(key, 0)) for key in keys)
    return counts


def _canonical_relation(root: Path, entry: Mapping[str, object]) -> Optional[Mapping[str, object]]:
    prefix = "implementation/workbench/"
    path = str(entry["path"])
    if not path.startswith(prefix):
        return None
    canonical = path[len(prefix):]
    candidate = root / canonical
    if not candidate.exists() and not candidate.is_symlink():
        return {"canonical_path": canonical, "status": "missing_canonical", "canonical_sha256": None}
    canonical_meta = _metadata_for_path(root, candidate)
    status = "same_hash" if canonical_meta["sha256"] == entry["sha256"] else "hash_conflict"
    return {
        "canonical_path": canonical,
        "status": status,
        "canonical_sha256": canonical_meta["sha256"],
    }


def _fingerprint(entries: Sequence[Mapping[str, object]]) -> str:
    material = [
        {
            "path": entry["path"],
            "path_type": entry["path_type"],
            "size": entry["size"],
            "sha256": entry["sha256"],
            "mode": entry["mode"],
            "classification": entry["classification"],
            "owner": entry["owner"],
        }
        for entry in entries
    ]
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(encoded)


def build_inventory(
    root: Path,
    rules: Mapping[str, object],
    task_id: str,
    workers: int = 8,
) -> Mapping[str, object]:
    root = root.resolve(strict=True)
    started = datetime.now(timezone.utc)
    paths = _iter_repository_paths(root)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        raw_entries = list(executor.map(lambda path: _metadata_for_path(root, path), paths))

    reference_index = _build_reference_index(
        root,
        raw_entries,
        max_bytes=int(rules["text_reference_scan_max_bytes"]),
    )
    current_cutoff_ns = int(
        (started - timedelta(days=int(rules["current_age_days"]))).timestamp() * 1_000_000_000
    )

    entries: List[MutableMapping[str, object]] = []
    basename_hashes: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    for raw_entry in raw_entries:
        entry = dict(raw_entry)
        entry.update(classify_path(str(entry["path"]), rules))
        entry["age_band"] = (
            "current" if int(entry["mtime_ns"]) >= current_cutoff_ns else "cold"
        )
        entry["references"] = _reference_counts(str(entry["path"]), reference_index)
        entry["production_import_or_route"] = bool(entry["references"]["production"])
        entry["test_reference"] = bool(entry["references"]["test"])
        entry["checkpoint_reference"] = bool(entry["references"]["checkpoint"])
        entry["canonical_relation"] = _canonical_relation(root, entry)
        entry["mutation_blockers"] = []
        if entry["owner"] == "workbench_unresolved":
            entry["mutation_blockers"].append("unknown_owner")
        if entry["escapes_root"]:
            entry["mutation_blockers"].append("external_symlink")
        if entry["canonical_relation"] and entry["canonical_relation"]["status"] == "hash_conflict":
            entry["mutation_blockers"].append("nested_canonical_hash_conflict")
        if entry["classification"] in {"quarantine", "regenerable"} and entry["checkpoint_reference"]:
            entry["mutation_blockers"].append("immutable_locator_reference")
        entry["quarantine_blocked"] = bool(entry["quarantine_blocked"] or entry["mutation_blockers"])
        entry["mutation_eligible"] = False
        entry["occupancy"] = "not_checked_task_0_2_read_only"
        basename_hashes[PurePosixPath(str(entry["path"])).name][str(entry["sha256"])].append(str(entry["path"]))
        entries.append(entry)

    conflicts = []
    conflict_names = set()
    for basename, hashes in sorted(basename_hashes.items()):
        if len(hashes) <= 1:
            continue
        conflict_names.add(basename)
        conflicts.append({
            "basename": basename,
            "variants": [
                {"sha256": digest, "paths": sorted(paths_for_hash)}
                for digest, paths_for_hash in sorted(hashes.items())
            ],
        })
    for entry in entries:
        entry["same_name_hash_conflict"] = PurePosixPath(str(entry["path"])).name in conflict_names
        if entry["same_name_hash_conflict"] and entry["classification"] in {"quarantine", "regenerable"}:
            if "same_name_hash_conflict" not in entry["mutation_blockers"]:
                entry["mutation_blockers"].append("same_name_hash_conflict")
            entry["quarantine_blocked"] = True

    classification_counts = Counter(str(entry["classification"]) for entry in entries)
    owner_counts = Counter(str(entry["owner"]) for entry in entries)
    summary = {
        "entry_count": len(entries),
        "total_bytes": sum(int(entry["size"]) for entry in entries),
        "classification_counts": {
            classification: int(classification_counts.get(classification, 0))
            for classification in rules["classifications"]
        },
        "owner_counts": dict(sorted(owner_counts.items())),
        "current_count": sum(1 for entry in entries if entry["age_band"] == "current"),
        "cold_count": sum(1 for entry in entries if entry["age_band"] == "cold"),
        "unknown_owner_count": sum(1 for entry in entries if entry["owner"] == "workbench_unresolved"),
        "quarantine_blocked_count": sum(1 for entry in entries if entry["quarantine_blocked"]),
        "checkpoint_reference_blocker_count": sum(
            1 for entry in entries if "immutable_locator_reference" in entry["mutation_blockers"]
        ),
        "same_name_hash_conflict_group_count": len(conflicts),
        "nested_same_hash_count": sum(
            1 for entry in entries if entry["canonical_relation"] and entry["canonical_relation"]["status"] == "same_hash"
        ),
        "nested_hash_conflict_count": sum(
            1 for entry in entries if entry["canonical_relation"] and entry["canonical_relation"]["status"] == "hash_conflict"
        ),
        "nested_missing_canonical_count": sum(
            1 for entry in entries if entry["canonical_relation"] and entry["canonical_relation"]["status"] == "missing_canonical"
        ),
        "mutation_eligible_count": 0,
    }
    return {
        "schema_version": 1,
        "policy_id": rules["policy_id"],
        "task_id": task_id,
        "root": str(root),
        "created_at": started.isoformat(),
        "inventory_fingerprint": _fingerprint(entries),
        "reference_signal_version": "basename-path-import-hint-v1",
        "reference_signals_are_deletion_authority": False,
        "summary": summary,
        "same_name_hash_conflicts": conflicts,
        "entries": entries,
    }


def write_inventory(path: Path, inventory: Mapping[str, object]) -> None:
    path = path.absolute()
    if path.exists():
        raise HygieneError("inventory output already exists: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=False)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(inventory, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Build a read-only Protocol v3 repository hygiene inventory.")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(list(argv) if argv else None)
    inventory = build_inventory(args.root, load_rules(args.rules), args.task_id, workers=args.workers)
    write_inventory(args.output, inventory)
    print(json.dumps({
        "output": str(args.output.absolute()),
        "inventory_fingerprint": inventory["inventory_fingerprint"],
        "summary": inventory["summary"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
