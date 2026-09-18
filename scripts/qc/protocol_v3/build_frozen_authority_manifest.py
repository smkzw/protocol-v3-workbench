"""Build and verify the Protocol v3 Phase 0 read-only protection manifest.

This module deliberately has no application imports.  It resolves the explicit
rules, validates symlink/path boundaries, rehashes the selected files, records
SQLite logical state through an immutable read-only URI, and writes the
immutable protected-asset fixture.  Its comparator is fail-closed: an unknown
path, protected byte change, unresolved/ownerless rule, or protected SQLite
logical change is an error.

The output is deterministic: timestamps, inode numbers, and process state are
not part of the manifest.  SQLite/WAL/SHM bytes are recorded as physical assets;
WAL/SHM are never treated as logical database state here.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import copy
import glob
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


POLICY_ID = "mw-protocol-v3-protected-paths-v1"
MANIFEST_SCHEMA_VERSION = 1
SQLITE_MAIN_SUFFIXES = (".sqlite", ".sqlite3", ".db", ".db3")
SQLITE_SIDE_SUFFIXES = ("-wal", "-shm")
LOCAL_IMPORT_ROOT_NAMES = {
    "app",
    "config",
    "frontend",
    "packages",
    "scripts",
    "services",
    "tests",
    "tools",
}

# This root is explicitly authorized by the Task 0.4 execution context.  It is
# intentionally narrower than the parent CMSS-SOP department tree: only the
# protocol-writing SOP candidate root is admitted, and only the actual Word/
# Excel candidate files below it are selected.
CMSS_SOP_PROTOCOL_CANDIDATE_ROOT = Path(
    "/Users/smkzw/Documents/康哲项目资料/综合资料/医学部自控文件体系/02 医学开发部/医学科学组/"
    "CMSS-SOP-MD-5101-01 临床研究方案撰写操作规程-陈魁"
)
CMSS_SOP_PROTOCOL_RULE_ID = "cmss_sop_md_5101_protocol_template_authority"
MEDICAL_MONITORING_INVENTORY_RULE_ID = "medical_monitoring_inventory_paths"


class FrozenAuthorityError(RuntimeError):
    """Raised when a protection rule cannot be resolved without guessing."""


def _authority_relocations() -> dict[str, Path]:
    """Resolve only the hash-verified R.1 amendment; never alter frozen rows."""
    spec = importlib.util.spec_from_file_location(
        "authority_locator_amendment", Path(__file__).with_name("authority_locator_amendment.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return module.current_locators()
    except (ValueError, OSError, KeyError) as exc:
        raise FrozenAuthorityError(f"authority locator amendment invalid: {exc}") from exc


def canonical_json_bytes(value: Any) -> bytes:
    """Return the byte representation used for all manifest fingerprints."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _lexical_absolute(value: str | os.PathLike[str]) -> Path:
    path = Path(os.path.abspath(os.fspath(value)))
    if not path.is_absolute():
        raise FrozenAuthorityError(f"absolute locator required: {value!r}")
    return path


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _within_any(path: Path, roots: Sequence[Path]) -> bool:
    return any(_within(path, root) for root in roots)


def _lexical_path_key(path: Path) -> str:
    return str(_lexical_absolute(path))


def _path_exists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenAuthorityError(f"cannot load JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FrozenAuthorityError(f"JSON object required: {path}")
    return value


def load_rules(path: Path) -> Mapping[str, Any]:
    rules = _load_json(path)
    if rules.get("schema_version") != 1:
        raise FrozenAuthorityError("protected rules schema_version must be 1")
    if rules.get("policy_id") != POLICY_ID:
        raise FrozenAuthorityError("protected rules policy_id mismatch")
    raw_rules = rules.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        raise FrozenAuthorityError("protected rules must contain a non-empty rules list")
    rule_ids: list[str] = []
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, dict):
            raise FrozenAuthorityError("each protected rule must be an object")
        rule_id = str(raw_rule.get("id", ""))
        owner = str(raw_rule.get("owner", ""))
        allowed = raw_rule.get("allowed")
        locator_type = str(raw_rule.get("locator_type", ""))
        if not rule_id or rule_id in rule_ids:
            raise FrozenAuthorityError(f"duplicate or empty rule id: {rule_id!r}")
        if not owner:
            raise FrozenAuthorityError(f"ownerless rule: {rule_id}")
        if allowed != "read_only":
            raise FrozenAuthorityError(f"rule {rule_id} is not read_only")
        if locator_type not in {
            "explicit_paths",
            "patterns",
            "inventory_owner",
            "python_import_graph",
        }:
            raise FrozenAuthorityError(f"unsupported locator_type for {rule_id}: {locator_type}")
        rule_ids.append(rule_id)
    allowed_roots = rules.get("allowed_roots")
    if not isinstance(allowed_roots, list) or not allowed_roots:
        raise FrozenAuthorityError("allowed_roots is required")
    for root in allowed_roots:
        if not _lexical_absolute(str(root)):
            raise FrozenAuthorityError(f"allowed root is not absolute: {root!r}")
    _effective_rules(rules)
    return rules


def _effective_rules(rules: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate and return the persisted Task 0.4 rule contract.

    CMSS-SOP-MD-5101 is part of the persisted protected-rule authority.  This
    function deliberately performs validation only: it must never synthesize
    an omitted root or rule at runtime.
    """

    effective = copy.deepcopy(dict(rules))
    cmss_root = str(CMSS_SOP_PROTOCOL_CANDIDATE_ROOT)
    allowed_roots = {str(value) for value in effective.get("allowed_roots", [])}
    if cmss_root not in allowed_roots:
        raise FrozenAuthorityError(
            "persisted protected rules omit the authorized CMSS-SOP-MD-5101 root: "
            + cmss_root
        )
    if str(effective.get("cmss_sop_protocol_candidate_root", "")) != cmss_root:
        raise FrozenAuthorityError(
            "persisted cmss_sop_protocol_candidate_root does not match the authorized root"
        )
    if not CMSS_SOP_PROTOCOL_CANDIDATE_ROOT.is_dir():
        _authority_relocations()

    persisted = [
        rule
        for rule in effective.get("rules", [])
        if isinstance(rule, dict) and str(rule.get("id", "")) == CMSS_SOP_PROTOCOL_RULE_ID
    ]
    if len(persisted) != 1:
        raise FrozenAuthorityError(
            f"persisted protected rules must contain exactly one {CMSS_SOP_PROTOCOL_RULE_ID} rule"
        )
    rule = persisted[0]
    expected_patterns = {
        str(CMSS_SOP_PROTOCOL_CANDIDATE_ROOT / "**" / "*.docx"),
        str(CMSS_SOP_PROTOCOL_CANDIDATE_ROOT / "**" / "*.xlsx"),
    }
    if {
        str(value) for value in rule.get("patterns", [])
    } != expected_patterns:
        raise FrozenAuthorityError(
            f"persisted {CMSS_SOP_PROTOCOL_RULE_ID} patterns do not match the authorized root"
        )
    required_fields = {
        "owner": "clinical_template_authority",
        "allowed": "read_only",
        "locator_type": "patterns",
    }
    for field, expected in required_fields.items():
        if rule.get(field) != expected:
            raise FrozenAuthorityError(
                f"persisted {CMSS_SOP_PROTOCOL_RULE_ID} field {field!r} must be {expected!r}"
            )
    if not rule.get("mandatory") or not rule.get("require_each_pattern"):
        raise FrozenAuthorityError(
            f"persisted {CMSS_SOP_PROTOCOL_RULE_ID} must be mandatory and require each pattern"
        )
    if int(rule.get("minimum_match_count", 0)) < 1:
        raise FrozenAuthorityError(
            f"persisted {CMSS_SOP_PROTOCOL_RULE_ID} must require a nonzero match count"
        )
    resolved_paths = rule.get("resolved_paths")
    if not isinstance(resolved_paths, list) or not resolved_paths:
        raise FrozenAuthorityError(
            f"persisted {CMSS_SOP_PROTOCOL_RULE_ID} must contain resolved_paths"
        )
    if int(rule.get("resolved_path_count", -1)) != len(resolved_paths):
        raise FrozenAuthorityError(
            f"persisted {CMSS_SOP_PROTOCOL_RULE_ID} resolved_path_count mismatch"
        )
    if not isinstance(rule.get("reference_count"), int) or rule["reference_count"] < 0:
        raise FrozenAuthorityError(
            f"persisted {CMSS_SOP_PROTOCOL_RULE_ID} must contain a nonnegative reference_count"
        )
    return effective


def load_inventory(rules: Mapping[str, Any]) -> Mapping[str, Any]:
    descriptor = rules.get("accepted_task02_inventory")
    if not isinstance(descriptor, dict):
        raise FrozenAuthorityError("accepted_task02_inventory descriptor is required")
    inventory_path = _lexical_absolute(str(descriptor.get("path", "")))
    if not inventory_path.is_file():
        raise FrozenAuthorityError(f"accepted inventory is missing: {inventory_path}")
    expected_hash = str(descriptor.get("sha256", ""))
    actual_hash = _sha256_file(inventory_path)
    if expected_hash != actual_hash:
        raise FrozenAuthorityError(
            f"accepted inventory hash mismatch: expected={expected_hash} actual={actual_hash}"
        )
    inventory = _load_json(inventory_path)
    expected_root = _lexical_path_key(_lexical_absolute(str(descriptor.get("root", ""))))
    actual_root = _lexical_path_key(_lexical_absolute(str(inventory.get("root", ""))))
    if expected_root != actual_root:
        raise FrozenAuthorityError(
            f"inventory root mismatch: expected={expected_root} actual={actual_root}"
        )
    if descriptor.get("inventory_fingerprint") != inventory.get("inventory_fingerprint"):
        raise FrozenAuthorityError("accepted inventory fingerprint mismatch")
    if not isinstance(inventory.get("entries"), list):
        raise FrozenAuthorityError("inventory entries must be a list")
    return inventory


def _allowed_roots(rules: Mapping[str, Any]) -> list[Path]:
    roots = [_lexical_absolute(str(value)) for value in rules["allowed_roots"]]
    return [root.resolve(strict=False) for root in roots]


def _validate_symlink(path: Path, allowed_roots: Sequence[Path]) -> None:
    target = os.readlink(str(path))
    if os.path.isabs(target):
        raise FrozenAuthorityError(f"absolute symlink target is forbidden: {path}")
    resolved = path.resolve(strict=True)
    if not _within_any(resolved, allowed_roots):
        raise FrozenAuthorityError(f"symlink escapes allowed roots: {path} -> {target}")
    if resolved.is_dir():
        raise FrozenAuthorityError(
            f"directory symlink requires an explicit audited locator: {path} -> {target}"
        )
    if not resolved.is_file():
        raise FrozenAuthorityError(f"symlink target is not a regular file: {path} -> {target}")


def _expand_tree(path: Path, allowed_roots: Sequence[Path]) -> set[Path]:
    path = _lexical_absolute(path)
    if not _path_exists(path):
        return set()
    if path.is_symlink():
        _validate_symlink(path, allowed_roots)
        return {path}
    if path.is_file():
        return {path}
    if not path.is_dir():
        raise FrozenAuthorityError(f"unsupported locator type: {path}")

    result: set[Path] = set()
    for current, dirnames, filenames in os.walk(str(path), topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dirname in sorted(dirnames):
            child = current_path / dirname
            if child.is_symlink():
                _validate_symlink(child, allowed_roots)
                raise FrozenAuthorityError(
                    f"directory symlink cannot be expanded implicitly: {child}"
                )
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            child = current_path / filename
            if child.is_symlink():
                _validate_symlink(child, allowed_roots)
            elif not child.is_file():
                raise FrozenAuthorityError(f"non-regular file in protected directory: {child}")
            result.add(child)
    return result


def _expand_patterns(patterns: Iterable[str], allowed_roots: Sequence[Path]) -> tuple[set[Path], dict[str, int]]:
    resolved: set[Path] = set()
    counts: dict[str, int] = {}
    for raw_pattern in patterns:
        pattern = str(raw_pattern)
        if not os.path.isabs(pattern):
            raise FrozenAuthorityError(f"protected pattern is not absolute: {pattern}")
        if pattern in {
            str(CMSS_SOP_PROTOCOL_CANDIDATE_ROOT / "**" / "*.docx"),
            str(CMSS_SOP_PROTOCOL_CANDIDATE_ROOT / "**" / "*.xlsx"),
        }:
            # Frozen keys remain logical identities. Physical locators are explicit
            # in the additive amendment and rehashed before every resolution.
            relocated = _authority_relocations()
            matched = {Path(old) for old in relocated if old.endswith(Path(pattern).suffix)}
            resolved.update(matched)
            counts[pattern] = len(matched)
            continue
        expanded: set[Path] = set()
        # Python 3.9 (the repository's system interpreter) lacks glob's
        # include_hidden argument.  A terminal `/**` is a directory contract,
        # so expand that literal directory directly and retain hidden files.
        if pattern.endswith("/**"):
            expanded.update(_expand_tree(Path(pattern[:-3].rstrip("/")), allowed_roots))
        else:
            try:
                hits = glob.glob(pattern, recursive=True, include_hidden=True)
            except TypeError:  # pragma: no cover - exercised on Python 3.9
                hits = glob.glob(pattern, recursive=True)
            for hit in sorted(hits):
                expanded.update(_expand_tree(Path(hit), allowed_roots))
        resolved.update(expanded)
        counts[pattern] = len(expanded)
    return resolved, counts


def _inventory_entries(
    inventory: Mapping[str, Any],
    owner: str,
    rule: Mapping[str, Any] | None = None,
) -> list[Mapping[str, Any]]:
    include_prefixes = None
    if rule is not None and rule.get("include_inventory_top_level_prefixes"):
        include_prefixes = {
            str(value).strip("/")
            for value in rule.get("include_inventory_top_level_prefixes", [])
        }
    entries: list[Mapping[str, Any]] = []
    for entry in inventory["entries"]:
        if not isinstance(entry, dict) or str(entry.get("owner", "")) != owner:
            continue
        if include_prefixes:
            path = str(entry.get("path", ""))
            top_level = path.split("/", 1)[0]
            if top_level not in include_prefixes:
                continue
        entries.append(entry)
    return entries


def _inventory_path(inventory: Mapping[str, Any], entry: Mapping[str, Any]) -> Path:
    root = _lexical_absolute(str(inventory["root"]))
    relative = str(entry.get("path", ""))
    if not relative or PurePosixPath(relative).is_absolute():
        raise FrozenAuthorityError(f"inventory path is not relative: {relative!r}")
    if any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts):
        raise FrozenAuthorityError(f"unsafe inventory path: {relative!r}")
    return root / relative


def _scope_prefix_for_inventory_path(inventory: Mapping[str, Any], entry: Mapping[str, Any]) -> Path | None:
    relative = PurePosixPath(str(entry.get("path", "")))
    parts = relative.parts
    if len(parts) >= 3 and parts[:2] in {
        ("runs", "execution"),
        ("records", "active_slices"),
        ("records", "handoffs"),
    }:
        return _lexical_absolute(inventory["root"]) / PurePosixPath(*parts[:3])
    return None


def _inventory_reference(entry: Mapping[str, Any]) -> tuple[dict[str, int], int]:
    raw = entry.get("references")
    if not isinstance(raw, dict):
        return {"checkpoint": 0, "production": 0, "test": 0}, 0
    values = {
        key: int(raw.get(key, 0) or 0)
        for key in ("checkpoint", "production", "test")
    }
    return values, sum(values.values())


def _inventory_maps(inventory: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    by_path: dict[str, Mapping[str, Any]] = {}
    by_owner: dict[str, Mapping[str, Any]] = {}
    for entry in inventory["entries"]:
        if not isinstance(entry, dict):
            raise FrozenAuthorityError("inventory entry must be an object")
        path = _lexical_path_key(_inventory_path(inventory, entry))
        if path in by_path:
            raise FrozenAuthorityError(f"duplicate inventory path: {path}")
        by_path[path] = entry
        by_owner[f"{entry.get('owner')}:{path}"] = entry
    return by_path, by_owner


def _inventory_missing_allowlist(
    rule: Mapping[str, Any],
    allowed_roots: Sequence[Path],
) -> set[str] | None:
    """Validate the exact persisted missing-path set for medical monitoring."""

    if "allow_missing_inventory_entries" in rule:
        raise FrozenAuthorityError(
            f"open-ended allow_missing_inventory_entries is forbidden for {rule['id']}"
        )
    if str(rule.get("id", "")) != MEDICAL_MONITORING_INVENTORY_RULE_ID:
        return None

    raw_paths = rule.get("inventory_stale_missing_paths")
    expected_count = rule.get("inventory_stale_missing_count")
    if not isinstance(raw_paths, list):
        raise FrozenAuthorityError(
            f"{MEDICAL_MONITORING_INVENTORY_RULE_ID} requires inventory_stale_missing_paths"
        )
    if type(expected_count) is not int or expected_count != len(raw_paths):
        raise FrozenAuthorityError(
            f"{MEDICAL_MONITORING_INVENTORY_RULE_ID} missing-path count mismatch"
        )

    normalized: list[str] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise FrozenAuthorityError(
                f"{MEDICAL_MONITORING_INVENTORY_RULE_ID} missing-path allowlist contains an empty entry"
            )
        if not os.path.isabs(raw_path):
            raise FrozenAuthorityError(
                f"{MEDICAL_MONITORING_INVENTORY_RULE_ID} missing-path allowlist requires "
                f"absolute raw entries: {raw_path!r}"
            )
        path = _lexical_absolute(raw_path)
        if not _within_any(path, allowed_roots):
            raise FrozenAuthorityError(
                f"{MEDICAL_MONITORING_INVENTORY_RULE_ID} missing-path escapes allowed roots: {path}"
            )
        normalized.append(_lexical_path_key(path))
    if len(normalized) != len(set(normalized)):
        raise FrozenAuthorityError(
            f"{MEDICAL_MONITORING_INVENTORY_RULE_ID} missing-path allowlist contains duplicates"
        )
    return set(normalized)


def _module_name_for_path(path: Path, local_roots: Sequence[Path]) -> str | None:
    for root in local_roots:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if relative.suffix == ".py":
            relative = relative.with_suffix("")
        if relative.name == "__init__":
            relative = relative.parent
        return ".".join(relative.parts)
    return None


def _module_file(module: str, local_roots: Sequence[Path]) -> Path | None:
    if not module:
        return None
    parts = tuple(part for part in module.split(".") if part)
    if not parts:
        return None
    for root in local_roots:
        base = root.joinpath(*parts)
        candidate = base.with_suffix(".py")
        if candidate.is_file() or candidate.is_symlink():
            return candidate
        package = base / "__init__.py"
        if package.is_file() or package.is_symlink():
            return package
        # The live workbench keeps ``packages.contracts`` as a namespace-style
        # compatibility import while the concrete implementation lives under
        # ``packages/contracts/workbench_contracts``.
        if parts[:2] == ("packages", "contracts") and len(parts) >= 3:
            compatibility_base = root / "packages" / "contracts" / "workbench_contracts" / Path(*parts[2:])
            candidate = compatibility_base.with_suffix(".py")
            if candidate.is_file() or candidate.is_symlink():
                return candidate
            package = compatibility_base / "__init__.py"
            if package.is_file() or package.is_symlink():
                return package
    return None


def _module_namespace_exists(module: str, local_roots: Sequence[Path]) -> bool:
    parts = tuple(part for part in module.split(".") if part)
    if not parts:
        return False
    return any(root.joinpath(*parts).is_dir() for root in local_roots)


def _is_probably_local_module(module: str) -> bool:
    head = module.split(".", 1)[0]
    return (
        head in LOCAL_IMPORT_ROOT_NAMES
        or head.startswith("monitoring")
        or head.startswith("medical_monitoring")
        or head.startswith("medical_writing")
    )


def _resolve_import_graph(
    seed_paths: Iterable[Path],
    local_roots: Sequence[Path],
) -> tuple[set[Path], list[dict[str, str]], list[str]]:
    queue = sorted({path for path in seed_paths if path.suffix == ".py"}, key=_lexical_path_key)
    visited: set[Path] = set()
    edges: list[dict[str, str]] = []
    unresolved_local: set[str] = set()
    while queue:
        source = queue.pop(0)
        source = _lexical_absolute(source)
        if source in visited:
            continue
        if not source.is_file():
            raise FrozenAuthorityError(f"import seed/dependency missing: {source}")
        visited.add(source)
        try:
            tree = ast.parse(source.read_text(encoding="utf-8", errors="strict"), filename=str(source))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise FrozenAuthorityError(f"cannot parse protected Python dependency {source}: {exc}") from exc
        current_module = _module_name_for_path(source, local_roots)
        current_parts = current_module.split(".") if current_module else []
        discovered: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    discovered.append((alias.name, "import"))
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base_parts = current_parts[:-node.level] if current_parts else []
                    if node.module:
                        base_parts.extend(node.module.split("."))
                        discovered.append((".".join(base_parts), "from"))
                    else:
                        for alias in node.names:
                            discovered.append((".".join(base_parts + [alias.name]), "from"))
                elif node.module:
                    discovered.append((node.module, "from"))
        for module, import_kind in discovered:
            candidate = _module_file(module, local_roots)
            if candidate is None:
                if _is_probably_local_module(module) and not _module_namespace_exists(module, local_roots):
                    unresolved_local.add(module)
                continue
            candidate = _lexical_absolute(candidate)
            edges.append({"source": str(source), "module": module, "target": str(candidate)})
            if candidate not in visited:
                queue.append(candidate)
        queue.sort(key=_lexical_path_key)
    if unresolved_local:
        unresolved = sorted(unresolved_local)
        raise FrozenAuthorityError(
            "unresolved local imports in medical-monitoring dependency graph: "
            + ", ".join(unresolved[:40])
            + (" ..." if len(unresolved) > 40 else "")
        )
    return visited, edges, []


def _resolve_rule_locators(
    rule: Mapping[str, Any],
    rules: Mapping[str, Any],
    inventory: Mapping[str, Any],
    allowed_roots: Sequence[Path],
    raw_by_id: Mapping[str, set[Path]],
    *,
    validate_frozen: bool = True,
) -> dict[str, Any]:
    rule_id = str(rule["id"])
    locator_type = str(rule["locator_type"])
    paths: set[Path] = set()
    pattern_counts: dict[str, int] = {}
    scope_prefixes: set[Path] = set()
    dependency_edges: list[dict[str, str]] = []
    unresolved_imports: list[str] = []
    missing_inventory_paths: list[str] = []

    if locator_type == "explicit_paths":
        locators = rule.get("locators")
        if not isinstance(locators, list) or not locators:
            raise FrozenAuthorityError(f"explicit locators required for {rule_id}")
        for raw_locator in locators:
            locator = _lexical_absolute(str(raw_locator))
            expanded = _expand_tree(locator, allowed_roots)
            if not expanded:
                if bool(rule.get("require_each_locator", False)) or bool(rule.get("mandatory", False)):
                    raise FrozenAuthorityError(f"zero-match mandatory locator {rule_id}: {locator}")
            paths.update(expanded)
            pattern_counts[str(locator)] = len(expanded)
    elif locator_type == "patterns":
        patterns = rule.get("patterns")
        if not isinstance(patterns, list) or not patterns:
            raise FrozenAuthorityError(f"patterns required for {rule_id}")
        paths, pattern_counts = _expand_patterns(patterns, allowed_roots)
        if bool(rule.get("require_each_pattern", False)):
            empty = [pattern for pattern, count in pattern_counts.items() if count == 0]
            if empty:
                raise FrozenAuthorityError(f"zero-match mandatory patterns for {rule_id}: {empty}")
    elif locator_type == "inventory_owner":
        owner = str(rule.get("inventory_owner", ""))
        if not owner:
            raise FrozenAuthorityError(f"inventory_owner missing for {rule_id}")
        missing_allowlist = _inventory_missing_allowlist(rule, allowed_roots)
        entries = _inventory_entries(inventory, owner, rule)
        if not entries and bool(rule.get("mandatory", False)):
            raise FrozenAuthorityError(f"inventory owner has zero matches: {owner}")
        for entry in entries:
            path = _inventory_path(inventory, entry)
            if not _path_exists(path):
                missing_path = _lexical_path_key(path)
                missing_inventory_paths.append(missing_path)
                if missing_allowlist is None:
                    raise FrozenAuthorityError(f"inventory path is missing for {rule_id}: {path}")
                continue
            paths.add(path)
            if bool(rule.get("include_scope_prefixes", False)):
                scope = _scope_prefix_for_inventory_path(inventory, entry)
                if scope is not None:
                    scope_prefixes.add(scope)
        if bool(rule.get("include_scope_prefixes", False)):
            if rule.get("scope_prefixes"):
                scope_prefixes = {
                    _lexical_absolute(str(value)) for value in rule.get("scope_prefixes", [])
                }
            for scope in sorted(scope_prefixes, key=_lexical_path_key):
                paths.update(_expand_tree(scope, allowed_roots))
        if missing_allowlist is not None:
            observed_missing = set(missing_inventory_paths)
            newly_missing = sorted(observed_missing - missing_allowlist)
            no_longer_missing = sorted(missing_allowlist - observed_missing)
            if newly_missing or no_longer_missing:
                raise FrozenAuthorityError(
                    f"exact inventory missing-path allowlist drift for {rule_id}: "
                    f"newly_missing={newly_missing} no_longer_missing={no_longer_missing}"
                )
        pattern_counts[owner] = len(paths)
    elif locator_type == "python_import_graph":
        seed_rule_ids = rule.get("seed_rule_ids")
        if not isinstance(seed_rule_ids, list) or not seed_rule_ids:
            raise FrozenAuthorityError(f"seed_rule_ids required for {rule_id}")
        missing_seed_rules = [seed for seed in seed_rule_ids if seed not in raw_by_id]
        if missing_seed_rules:
            raise FrozenAuthorityError(f"dependency seed rules must precede {rule_id}: {missing_seed_rules}")
        seeds = set().union(*(raw_by_id[seed] for seed in seed_rule_ids))
        local_roots_raw = rule.get("local_import_roots")
        if not isinstance(local_roots_raw, list) or not local_roots_raw:
            raise FrozenAuthorityError(f"local_import_roots required for {rule_id}")
        local_roots = [_lexical_absolute(str(value)) for value in local_roots_raw]
        paths, dependency_edges, unresolved_imports = _resolve_import_graph(seeds, local_roots)
        pattern_counts["python_import_graph"] = len(paths)
    else:  # pragma: no cover - load_rules guards this branch
        raise FrozenAuthorityError(f"unsupported locator type: {locator_type}")

    exclude_rule_ids = rule.get("exclude_rule_ids", [])
    if not isinstance(exclude_rule_ids, list):
        raise FrozenAuthorityError(f"exclude_rule_ids must be a list for {rule_id}")
    unknown_excludes = [value for value in exclude_rule_ids if value not in raw_by_id]
    if unknown_excludes:
        raise FrozenAuthorityError(f"unknown exclude rule ids for {rule_id}: {unknown_excludes}")
    raw_paths = set(paths)
    excluded_paths = set().union(*(raw_by_id[value] for value in exclude_rule_ids)) if exclude_rule_ids else set()
    paths.difference_update(excluded_paths)
    if bool(rule.get("mandatory", False)) and not paths:
        raise FrozenAuthorityError(f"zero-match mandatory rule: {rule_id}")
    minimum = int(rule.get("minimum_match_count", 1 if rule.get("mandatory", False) else 0))
    if len(paths) < minimum:
        raise FrozenAuthorityError(
            f"rule {rule_id} resolved {len(paths)} paths but requires {minimum}"
        )
    if rule.get("max_match_count") is not None and len(paths) > int(rule["max_match_count"]):
        raise FrozenAuthorityError(f"rule {rule_id} exceeded max_match_count")

    frozen_paths = rule.get("resolved_paths")
    if validate_frozen and frozen_paths is not None:
        if not isinstance(frozen_paths, list) or any(not os.path.isabs(str(value)) for value in frozen_paths):
            raise FrozenAuthorityError(f"resolved_paths must be absolute for {rule_id}")
        expected = {_lexical_path_key(str(value)) for value in frozen_paths}
        actual = {_lexical_path_key(path) for path in paths}
        if expected != actual:
            added = sorted(actual - expected)
            missing = sorted(expected - actual)
            raise FrozenAuthorityError(
                f"unknown/current protected path drift for {rule_id}: "
                f"added={added[:20]} missing={missing[:20]}"
            )
        expected_set_sha = rule.get("resolved_path_set_sha256")
        if expected_set_sha and expected_set_sha != _path_set_sha256(actual):
            raise FrozenAuthorityError(f"resolved path set fingerprint mismatch for {rule_id}")

    return {
        "rule_id": rule_id,
        "owner": str(rule["owner"]),
        "category": str(rule.get("category", "uncategorized")),
        "paths": paths,
        "raw_paths": raw_paths,
        "excluded_paths": excluded_paths,
        "pattern_counts": pattern_counts,
        "scope_prefixes": scope_prefixes,
        "dependency_edges": dependency_edges,
        "unresolved_imports": unresolved_imports,
        "missing_inventory_paths": sorted(missing_inventory_paths),
    }


def _path_set_sha256(paths: Iterable[str | Path]) -> str:
    values = sorted(_lexical_path_key(Path(path)) for path in paths)
    return canonical_json_sha256(values)


def resolve_rules(
    rules: Mapping[str, Any],
    inventory: Mapping[str, Any] | None = None,
    *,
    validate_frozen: bool = True,
) -> tuple[dict[str, dict[str, Any]], Mapping[str, Any]]:
    rules = _effective_rules(rules)
    inventory = inventory or load_inventory(rules)
    allowed_roots = _allowed_roots(rules)
    raw_by_id: dict[str, set[Path]] = {}
    resolutions: dict[str, dict[str, Any]] = {}
    for raw_rule in rules["rules"]:
        rule = dict(raw_rule)
        rule_id = str(rule["id"])
        resolution = _resolve_rule_locators(
            rule,
            rules,
            inventory,
            allowed_roots,
            raw_by_id,
            validate_frozen=validate_frozen,
        )
        raw_by_id[rule_id] = set(resolution["raw_paths"])
        resolutions[rule_id] = resolution

    claims: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for rule_id, resolution in resolutions.items():
        for path in resolution["paths"]:
            claims[_lexical_path_key(path)].append((rule_id, resolution["owner"]))
    conflicts = {
        path: claim_list
        for path, claim_list in claims.items()
        if len({owner for _, owner in claim_list}) > 1
    }
    if conflicts:
        sample = {path: claims[path] for path in sorted(conflicts)[:20]}
        raise FrozenAuthorityError(f"duplicate path-owner conflicts: {sample}")
    for path, claim_list in claims.items():
        if not path or any(not owner for _, owner in claim_list):
            raise FrozenAuthorityError(f"ownerless protected path claim: {path}")
    return resolutions, inventory


def freeze_rules(
    rules: Mapping[str, Any],
    resolutions: Mapping[str, Mapping[str, Any]],
    inventory: Mapping[str, Any],
) -> Mapping[str, Any]:
    frozen = copy.deepcopy(dict(rules))
    inventory_by_path, _ = _inventory_maps(inventory)
    frozen_rules: list[MutableMapping[str, Any]] = []
    for raw_rule in frozen["rules"]:
        rule = dict(raw_rule)
        resolution = resolutions[str(rule["id"])]
        paths = sorted(_lexical_path_key(path) for path in resolution["paths"])
        refs: dict[str, int] = {}
        ref_surfaces: dict[str, dict[str, int]] = {}
        for path in paths:
            entry = inventory_by_path.get(path)
            surfaces, total = _inventory_reference(entry) if entry else (
                {"checkpoint": 0, "production": 0, "test": 0},
                0,
            )
            refs[path] = total
            ref_surfaces[path] = surfaces
        rule["resolved_paths"] = paths
        rule["resolved_path_count"] = len(paths)
        rule["resolved_path_set_sha256"] = _path_set_sha256(paths)
        rule["reference_count"] = sum(refs.values())
        rule["reference_counts"] = refs
        rule["reference_surfaces"] = ref_surfaces
        if resolution.get("scope_prefixes"):
            rule["scope_prefixes"] = sorted(
                _lexical_path_key(path) for path in resolution["scope_prefixes"]
            )
        else:
            rule.pop("scope_prefixes", None)
        if resolution.get("dependency_edges"):
            rule["dependency_seed_path_count"] = len(
                [path for path in paths if path.endswith(".py")]
            )
            rule["dependency_edge_count"] = len(resolution["dependency_edges"])
        if resolution.get("missing_inventory_paths"):
            rule["inventory_stale_missing_count"] = len(resolution["missing_inventory_paths"])
            rule["inventory_stale_missing_paths"] = sorted(resolution["missing_inventory_paths"])
        if resolution.get("unresolved_imports"):
            rule["unresolved_imports"] = sorted(resolution["unresolved_imports"])
        frozen_rules.append(rule)
    frozen["rules"] = frozen_rules
    frozen["freeze_contract"] = {
        "resolved_paths_are_exact": True,
        "unknown_current_paths": "reject",
        "hash_source": "current_disk_rehashed_at_build",
        "sqlite_logical_fingerprint": "worker_03_read_only_hook",
        "wal_shm_logical_state": "never_inferred_from_physical_hash",
    }
    return frozen


def _path_record(path: Path, allowed_roots: Sequence[Path]) -> Mapping[str, Any]:
    path = _lexical_absolute(path)
    logical_path = path
    if _within(path, CMSS_SOP_PROTOCOL_CANDIDATE_ROOT):
        relocated = _authority_relocations()
        if str(path) not in relocated:
            raise FrozenAuthorityError(f"unknown authority locator: {path}")
        path = relocated[str(path)]
    if not _path_exists(path):
        raise FrozenAuthorityError(f"protected path disappeared while hashing: {path}")
    before = path.lstat()
    mode = stat.S_IMODE(before.st_mode)
    if stat.S_ISLNK(before.st_mode):
        _validate_symlink(path, allowed_roots)
        target = os.readlink(str(path))
        resolved = path.resolve(strict=True)
        return {
            "path": str(path),
            "path_type": "symlink",
            "size": len(target.encode("utf-8")),
            "mode": mode,
            "sha256": _sha256_bytes(target.encode("utf-8")),
            "link_target": target,
            "resolved_path": str(resolved),
            "resolved_sha256": _sha256_file(resolved),
        }
    if not stat.S_ISREG(before.st_mode):
        raise FrozenAuthorityError(f"protected path is not a regular file: {path}")
    digest = _sha256_file(path)
    after = path.lstat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise FrozenAuthorityError(f"protected path changed while hashing: {path}")
    return {
        "path": str(logical_path),
        "path_type": "file",
        "size": after.st_size,
        "mode": mode,
        "sha256": digest,
        "link_target": None,
        "resolved_path": None,
        "resolved_sha256": None,
    }


def _is_sqlite_main(path: Path) -> bool:
    return path.name.casefold().endswith(SQLITE_MAIN_SUFFIXES)


def _is_sqlite_sidecar(path: Path) -> bool:
    return path.name.casefold().endswith(SQLITE_SIDE_SUFFIXES)


def _sqlite_identifier(value: str) -> str:
    """Quote an SQLite identifier without interpolating executable SQL."""

    return '"' + value.replace('"', '""') + '"'


def _sqlite_uri(path: Path) -> str:
    """Build the only URI permitted for protected SQLite reads."""

    return path.resolve(strict=True).as_uri() + "?mode=ro&immutable=1"


def _normalize_sqlite_schema_sql(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _normalize_sqlite_value(value: Any) -> Any:
    """Convert SQLite values to deterministic, JSON-safe values."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, bytes):
        return {"__sqlite_type__": "blob", "hex": value.hex()}
    if isinstance(value, float):
        if math.isnan(value):
            return {"__sqlite_type__": "float", "value": "nan"}
        if math.isinf(value):
            return {"__sqlite_type__": "float", "value": "-inf" if value < 0 else "inf"}
        return value
    return {"__sqlite_type__": type(value).__name__, "repr": repr(value)}


def _sqlite_columns(connection: sqlite3.Connection, table_name: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"PRAGMA table_info({_sqlite_identifier(table_name)})"
    ).fetchall()
    return [
        {
            "cid": int(row[0]),
            "name": str(row[1]),
            "type": str(row[2] or ""),
            "notnull": int(row[3]),
            "default": _normalize_sqlite_value(row[4]),
            "pk": int(row[5]),
        }
        for row in rows
    ]


def _sqlite_table_rows(
    connection: sqlite3.Connection,
    table_name: str,
    columns: Sequence[Mapping[str, Any]],
) -> tuple[int, str]:
    """Hash a table's canonical row stream without using writable SQLite APIs."""

    table_sql = _sqlite_identifier(table_name)
    column_names = [str(column["name"]) for column in columns]
    query = f"SELECT * FROM {table_sql}"
    # Ordering by every declared column makes the logical fingerprint
    # independent of physical row order, including after a temporary-copy
    # mutation.  SQLite accepts mixed-type ordering and BLOB ordering.
    if column_names and len(column_names) <= 64:
        query += " ORDER BY " + ", ".join(_sqlite_identifier(name) for name in column_names)
    elif column_names:
        primary_keys = [
            str(column["name"])
            for column in columns
            if int(column.get("pk", 0) or 0) > 0
        ]
        if primary_keys and len(primary_keys) <= 64:
            query += " ORDER BY " + ", ".join(
                _sqlite_identifier(name) for name in primary_keys
            )

    try:
        cursor = connection.execute(query)
    except sqlite3.DatabaseError:
        # A virtual table can reject ORDER BY on a hidden/generated column.
        # Retry the read without an ordering clause; a failure still blocks the
        # manifest rather than silently weakening the protection contract.
        cursor = connection.execute(f"SELECT * FROM {table_sql}")

    digest = hashlib.sha256()
    row_count = 0
    for row in cursor:
        normalized_row = [_normalize_sqlite_value(value) for value in row]
        payload = canonical_json_bytes(normalized_row)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        row_count += 1
    return row_count, digest.hexdigest()


def fingerprint_sqlite(
    path: Path,
    *,
    database_file_sha256: str | None = None,
    database_file_size: int | None = None,
) -> Mapping[str, Any]:
    """Return a stable logical fingerprint using an immutable read-only URI.

    WAL/SHM files are deliberately not opened or consulted.  The main database
    physical hash is recorded separately from the logical material so a
    sidecar-only physical difference can never be mislabeled as a row change.
    """

    path = _lexical_absolute(path)
    if not path.is_file() or path.is_symlink():
        raise FrozenAuthorityError(f"SQLite main candidate must be a regular file: {path}")
    file_hash = database_file_sha256 or _sha256_file(path)
    file_size = int(path.stat().st_size if database_file_size is None else database_file_size)
    uri = _sqlite_uri(path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
        integrity = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
        if not integrity or any(value.casefold() != "ok" for value in integrity):
            raise FrozenAuthorityError(
                f"SQLite integrity_check failed for {path}: {integrity!r}"
            )

        schema_rows = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "ORDER BY type, name, tbl_name"
        ).fetchall()
        schema = [
            {
                "type": str(row[0]),
                "name": str(row[1]),
                "tbl_name": str(row[2]),
                "sql": _normalize_sqlite_schema_sql(row[3]),
            }
            for row in schema_rows
        ]
        table_names = [entry["name"] for entry in schema if entry["type"] == "table"]
        table_counts: dict[str, int] = {}
        row_fingerprint: dict[str, str] = {}
        table_fingerprints: dict[str, str] = {}
        for table_name in table_names:
            columns = _sqlite_columns(connection, table_name)
            count, row_digest = _sqlite_table_rows(connection, table_name, columns)
            table_counts[table_name] = count
            row_fingerprint[table_name] = row_digest
            table_fingerprints[table_name] = canonical_json_sha256(
                {
                    "columns": columns,
                    "row_count": count,
                    "row_fingerprint": row_digest,
                }
            )
        logical_material = {
            "integrity_check": integrity,
            "schema": schema,
            "table_counts": dict(sorted(table_counts.items())),
            "row_fingerprint": dict(sorted(row_fingerprint.items())),
        }
        return {
            "status": "ok",
            "database_file_sha256": file_hash,
            "database_file_size": file_size,
            "integrity_check": integrity,
            "schema": schema,
            "table_counts": dict(sorted(table_counts.items())),
            "row_fingerprint": dict(sorted(row_fingerprint.items())),
            "table_fingerprints": dict(sorted(table_fingerprints.items())),
            "logical_fingerprint": canonical_json_sha256(logical_material),
            "read_only_uri_contract": "file:<absolute-path>?mode=ro&immutable=1",
            "wal_shm_excluded": True,
        }
    except FrozenAuthorityError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise FrozenAuthorityError(f"SQLite logical fingerprint failed for {path}: {exc}") from exc
    finally:
        if connection is not None:
            connection.close()


def _physical_asset_material(asset: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        key: asset.get(key)
        for key in (
            "path",
            "path_type",
            "size",
            "mode",
            "sha256",
            "link_target",
            "resolved_sha256",
            "owner",
            "rule_ids",
        )
    }


def _validate_summary_int(
    summary: Mapping[str, Any],
    key: str,
    expected: int,
    label: str,
) -> None:
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise FrozenAuthorityError(f"{label} summary.{key} must be an integer: {value!r}")
    if value != expected:
        raise FrozenAuthorityError(
            f"{label} summary.{key} mismatch: expected={expected!r} actual={value!r}"
        )


def _validate_summary_count_map(
    summary: Mapping[str, Any],
    key: str,
    expected: Mapping[str, int],
    label: str,
) -> None:
    value = summary.get(key)
    if not isinstance(value, Mapping):
        raise FrozenAuthorityError(f"{label} summary.{key} must be an object: {value!r}")
    actual: dict[str, int] = {}
    for raw_name, raw_count in value.items():
        if not isinstance(raw_name, str):
            raise FrozenAuthorityError(
                f"{label} summary.{key} contains a non-string key: {raw_name!r}"
            )
        if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
            raise FrozenAuthorityError(
                f"{label} summary.{key} contains an invalid count: {raw_name}={raw_count!r}"
            )
        actual[raw_name] = raw_count
    if actual != dict(expected):
        raise FrozenAuthorityError(
            f"{label} summary.{key} mismatch: expected={dict(expected)!r} actual={actual!r}"
        )


def _validate_manifest_summary(
    manifest: Mapping[str, Any],
    assets: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> None:
    """Validate summary fields derived from the manifest itself.

    The builder emits assets in lexical path order.  Reusing that list order
    here keeps the physical fingerprint anchored to the same deterministic
    material used during generation instead of trusting a copied summary.
    """

    summary = manifest.get("summary")
    if not isinstance(summary, Mapping):
        raise FrozenAuthorityError(f"{label} manifest summary is missing")

    _validate_summary_int(summary, "asset_count", len(assets), label)
    physical_fingerprint = summary.get("physical_fingerprint")
    if not isinstance(physical_fingerprint, str):
        raise FrozenAuthorityError(
            f"{label} summary.physical_fingerprint must be a string: {physical_fingerprint!r}"
        )
    expected_physical_fingerprint = canonical_json_sha256(
        [_physical_asset_material(asset) for asset in assets]
    )
    if physical_fingerprint != expected_physical_fingerprint:
        raise FrozenAuthorityError(
            f"{label} summary.physical_fingerprint mismatch: "
            f"expected={expected_physical_fingerprint!r} actual={physical_fingerprint!r}"
        )

    expected_by_owner = dict(
        sorted(Counter(str(asset["owner"]) for asset in assets).items())
    )
    expected_by_category: Counter[str] = Counter()
    for asset in assets:
        for category in asset["categories"]:
            expected_by_category[str(category)] += 1
    _validate_summary_count_map(summary, "by_owner", expected_by_owner, label)
    _validate_summary_count_map(
        summary,
        "by_category",
        dict(sorted(expected_by_category.items())),
        label,
    )

    expected_unresolved_rule_ids = sorted(
        str(report["id"])
        for report in reports
        if report["mandatory"] is True and report["resolved_path_count"] == 0
    )
    expected_zero_match_rule_ids = sorted(
        str(report["id"]) for report in reports if report["resolved_path_count"] == 0
    )
    for key, expected in (
        ("unresolved_rule_ids", expected_unresolved_rule_ids),
        ("zero_match_rule_ids", expected_zero_match_rule_ids),
    ):
        value = summary.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise FrozenAuthorityError(f"{label} summary.{key} must be a string list: {value!r}")
        if value != expected:
            raise FrozenAuthorityError(
                f"{label} summary.{key} mismatch: expected={expected!r} actual={value!r}"
            )
    _validate_summary_int(summary, "unresolved_count", len(expected_unresolved_rule_ids), label)
    _validate_summary_int(summary, "zero_match_rule_count", len(expected_zero_match_rule_ids), label)

    _validate_summary_int(
        summary,
        "mandatory_rule_count",
        sum(1 for report in reports if report["mandatory"] is True),
        label,
    )
    _validate_summary_int(
        summary,
        "sqlite_main_count",
        sum("sqlite_logical_fingerprint" in asset for asset in assets),
        label,
    )
    _validate_summary_int(
        summary,
        "sqlite_sidecar_count",
        sum("sqlite_physical_companion" in asset for asset in assets),
        label,
    )
    _validate_summary_int(
        summary,
        "sqlite_logical_ready_count",
        sum(
            isinstance(asset.get("sqlite_logical_fingerprint"), Mapping)
            and asset["sqlite_logical_fingerprint"].get("status") == "ok"
            for asset in assets
        ),
        label,
    )
    _validate_summary_int(
        summary,
        "inventory_stale_missing_count",
        sum(report["inventory_stale_missing_count"] for report in reports),
        label,
    )

    missing_paths = summary.get("inventory_stale_missing_paths")
    if not isinstance(missing_paths, list) or any(
        not isinstance(path, str) or not os.path.isabs(path) for path in missing_paths
    ):
        raise FrozenAuthorityError(
            f"{label} summary.inventory_stale_missing_paths must be absolute string paths: "
            f"{missing_paths!r}"
        )
    if missing_paths != sorted(set(missing_paths)):
        raise FrozenAuthorityError(
            f"{label} summary.inventory_stale_missing_paths must be sorted and unique"
        )
    if len(missing_paths) != summary["inventory_stale_missing_count"]:
        raise FrozenAuthorityError(
            f"{label} summary.inventory_stale_missing_paths count mismatch: "
            f"expected={summary['inventory_stale_missing_count']!r} actual={len(missing_paths)!r}"
        )

    for key in (
        "ownerless_count",
        "duplicate_path_owner_conflict_count",
        "symlink_escape_count",
        "unknown_current_path_count",
    ):
        _validate_summary_int(summary, key, 0, label)

    source_roots = manifest.get("source_roots")
    if not isinstance(source_roots, Mapping):
        raise FrozenAuthorityError(f"{label} manifest source_roots are missing")
    cmss_root = source_roots.get("cmss_sop_protocol_candidate_root")
    if not isinstance(cmss_root, str) or not cmss_root:
        raise FrozenAuthorityError(
            f"{label} source_roots.cmss_sop_protocol_candidate_root is missing"
        )
    _validate_summary_int(
        summary,
        "cmss_sop_protocol_candidate_count",
        sum(cmss_root in str(asset["path"]) for asset in assets),
        label,
    )


def _rule_lookup(rules: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(rule["id"]): rule for rule in rules["rules"]}


def build_physical_manifest(
    rules: Mapping[str, Any],
    inventory: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Build the complete physical + logical protected-asset manifest."""

    source_rules = rules
    rules = _effective_rules(rules)
    resolutions, inventory = resolve_rules(rules, inventory, validate_frozen=True)
    allowed_roots = _allowed_roots(rules)
    inventory_by_path, _ = _inventory_maps(inventory)
    claims: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for rule_id, resolution in resolutions.items():
        for path in resolution["paths"]:
            claims[_lexical_path_key(path)].append(
                (rule_id, resolution["owner"], resolution["category"])
            )

    assets: list[dict[str, Any]] = []
    sqlite_logical_cache: dict[tuple[str, int], Mapping[str, Any]] = {}
    for raw_path in sorted(claims):
        path = Path(raw_path)
        record = dict(_path_record(path, allowed_roots))
        inventory_entry = inventory_by_path.get(raw_path)
        if inventory_entry is not None:
            expected_type = str(inventory_entry.get("path_type", ""))
            expected_size = int(inventory_entry.get("size", -1))
            expected_hash = str(inventory_entry.get("sha256", ""))
            if (record["path_type"], int(record["size"]), record["sha256"]) != (
                expected_type,
                expected_size,
                expected_hash,
            ):
                raise FrozenAuthorityError(
                    f"stale Task 0.2 inventory for {raw_path}: "
                    f"expected=({expected_type},{expected_size},{expected_hash}) "
                    f"actual=({record['path_type']},{record['size']},{record['sha256']})"
                )
        expected_authority_hash = rules.get("known_authority_hashes", {}).get(raw_path)
        if expected_authority_hash and expected_authority_hash != record["sha256"]:
            raise FrozenAuthorityError(
                f"decisive authority hash mismatch for {raw_path}: "
                f"expected={expected_authority_hash} actual={record['sha256']}"
            )
        claim_list = sorted(claims[raw_path])
        owners = sorted({owner for _, owner, _ in claim_list})
        if len(owners) != 1:
            raise FrozenAuthorityError(f"ownerless/conflicting asset claim: {raw_path}: {claim_list}")
        rule_ids = sorted({rule_id for rule_id, _, _ in claim_list})
        categories = sorted({category for _, _, category in claim_list})
        surfaces, reference_count = _inventory_reference(inventory_entry) if inventory_entry else (
            {"checkpoint": 0, "production": 0, "test": 0},
            0,
        )
        asset: dict[str, Any] = {
            **record,
            "owner": owners[0],
            "category": categories[0] if len(categories) == 1 else categories,
            "categories": categories,
            "rule_ids": rule_ids,
            "allowed": "read_only",
            "reference_count": reference_count,
            "reference_surfaces": surfaces,
        }
        if _is_sqlite_main(path):
            cache_key = (str(record["sha256"]), int(record["size"]))
            logical = sqlite_logical_cache.get(cache_key)
            if logical is None:
                logical = fingerprint_sqlite(
                    path,
                    database_file_sha256=str(record["sha256"]),
                    database_file_size=int(record["size"]),
                )
                sqlite_logical_cache[cache_key] = logical
            asset["sqlite_logical_fingerprint"] = dict(logical)
        elif _is_sqlite_sidecar(path):
            asset["sqlite_physical_companion"] = {
                "logical_state": "not_inferred",
                "physical_hash_only": True,
                "logical_change_never_inferred": True,
                "sidecar_kind": "wal" if path.name.casefold().endswith("-wal") else "shm",
                "main_path": str(path)[:-4],
            }
        assets.append(asset)

    owner_counts = Counter(str(asset["owner"]) for asset in assets)
    category_counts = Counter()
    for asset in assets:
        for category in asset["categories"]:
            category_counts[category] += 1
    rule_reports: list[dict[str, Any]] = []
    unresolved_rule_ids: list[str] = []
    zero_match_rule_ids: list[str] = []
    for rule in rules["rules"]:
        rule_id = str(rule["id"])
        resolution = resolutions[rule_id]
        count = len(resolution["paths"])
        if count == 0:
            zero_match_rule_ids.append(rule_id)
            if bool(rule.get("mandatory", False)):
                unresolved_rule_ids.append(rule_id)
        rule_reports.append(
            {
                "id": rule_id,
                "owner": str(rule["owner"]),
                "category": str(rule.get("category", "uncategorized")),
                "mandatory": bool(rule.get("mandatory", False)),
                "allowed": str(rule["allowed"]),
                "resolved_path_count": count,
                "resolved_path_set_sha256": _path_set_sha256(resolution["paths"]),
                "reference_count": sum(
                    _inventory_reference(inventory_by_path[path])[1]
                    if path in inventory_by_path
                    else 0
                    for path in map(_lexical_path_key, resolution["paths"])
                ),
                "pattern_match_counts": dict(sorted(resolution["pattern_counts"].items())),
                "scope_prefix_count": len(resolution["scope_prefixes"]),
                "dependency_edge_count": len(resolution["dependency_edges"]),
                "inventory_stale_missing_count": len(resolution.get("missing_inventory_paths", [])),
            }
        )
    if unresolved_rule_ids:
        raise FrozenAuthorityError(f"mandatory unresolved/zero-match rules: {unresolved_rule_ids}")

    inventory_stale_missing = sorted(
        {
            path
            for resolution in resolutions.values()
            for path in resolution.get("missing_inventory_paths", [])
        }
    )

    physical_fingerprint = canonical_json_sha256(
        [_physical_asset_material(asset) for asset in assets]
    )
    rules_sha256 = canonical_json_sha256(rules)
    inventory_descriptor = rules["accepted_task02_inventory"]
    cmss_root = str(rules.get("cmss_sop_protocol_candidate_root", ""))
    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "policy_id": POLICY_ID,
        "manifest_kind": "immutable_protected_assets",
        "source_roots": {
            "workbench_root": str(rules["workbench_root"]),
            "isolated_workspace_root": str(rules["isolated_workspace_root"]),
            "external_template_root": str(rules["external_template_root"]),
            "cmss_sop_protocol_candidate_root": cmss_root,
        },
        "rules_sha256": rules_sha256,
        "source_rules_sha256": canonical_json_sha256(source_rules),
        "accepted_task02_inventory": {
            "path": str(inventory_descriptor["path"]),
            "sha256": str(inventory_descriptor["sha256"]),
            "inventory_fingerprint": str(inventory_descriptor["inventory_fingerprint"]),
        },
        "assets": assets,
        "rule_reports": rule_reports,
        "summary": {
            "asset_count": len(assets),
            "physical_fingerprint": physical_fingerprint,
            "by_owner": dict(sorted(owner_counts.items())),
            "by_category": dict(sorted(category_counts.items())),
            "mandatory_rule_count": sum(1 for rule in rules["rules"] if rule.get("mandatory")),
            "unresolved_count": len(unresolved_rule_ids),
            "unresolved_rule_ids": sorted(unresolved_rule_ids),
            "zero_match_rule_count": len(zero_match_rule_ids),
            "zero_match_rule_ids": sorted(zero_match_rule_ids),
            "ownerless_count": 0,
            "duplicate_path_owner_conflict_count": 0,
            "symlink_escape_count": 0,
            "unknown_current_path_count": 0,
            "inventory_stale_missing_count": len(inventory_stale_missing),
            "inventory_stale_missing_paths": inventory_stale_missing,
            "sqlite_main_count": sum(1 for asset in assets if "sqlite_logical_fingerprint" in asset),
            "sqlite_sidecar_count": sum(1 for asset in assets if "sqlite_physical_companion" in asset),
            "sqlite_logical_ready_count": sum(
                1
                for asset in assets
                if asset.get("sqlite_logical_fingerprint", {}).get("status") == "ok"
            ),
                "cmss_sop_protocol_candidate_count": sum(
                    1
                    for asset in assets
                    if cmss_root and cmss_root in str(asset["path"])
                ),
        },
        "worker_03_hooks": {
            "sqlite_logical_fingerprint": {
                "required": True,
                "read_only_uri": "file:<absolute-path>?mode=ro&immutable=1",
                "required_components": [
                    "database_file_sha256",
                    "integrity_check",
                    "schema",
                    "table_counts",
                    "row_fingerprint",
                    "logical_fingerprint",
                ],
                "wal_shm_are_physical_only": True,
            },
            "comparator": {
                "physical_source_hook": "compare_physical_manifest",
                "must_fail_closed_on": [
                    "unknown_source_diff",
                    "protected_path_hash_change",
                    "sqlite_logical_row_change",
                    "unresolved_rule",
                    "ownerless_match",
                ],
                "mutation_fixture_policy": "temporary_copies_only",
            },
        },
        "canonicalization": {
            "encoding": "utf-8",
            "ensure_ascii": False,
            "sort_keys": True,
            "separators": [",", ":"],
            "newline": "\\n",
        },
    }
    return manifest


def build_manifest(
    rules: Mapping[str, Any],
    inventory: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Compatibility alias used by worker 3 and the eventual QC test."""

    return build_physical_manifest(rules, inventory)


def _manifest_asset_map(
    manifest: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Mapping[str, Any]]:
    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        raise FrozenAuthorityError(f"{label} manifest assets must be a non-empty list")
    result: dict[str, Mapping[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise FrozenAuthorityError(f"{label} manifest contains a non-object asset")
        path = str(asset.get("path", ""))
        if not path or not os.path.isabs(path):
            raise FrozenAuthorityError(f"{label} manifest has a non-absolute asset path: {path!r}")
        if path in result:
            raise FrozenAuthorityError(f"{label} manifest has duplicate asset path: {path}")
        owner = str(asset.get("owner", ""))
        if not owner:
            raise FrozenAuthorityError(f"{label} manifest has ownerless asset: {path}")
        if asset.get("allowed") != "read_only":
            raise FrozenAuthorityError(f"{label} asset is not read_only: {path}")
        if not isinstance(asset.get("rule_ids"), list) or not asset["rule_ids"]:
            raise FrozenAuthorityError(f"{label} asset has no rule reference: {path}")
        if not isinstance(asset.get("categories"), list) or not asset["categories"]:
            raise FrozenAuthorityError(f"{label} asset has no category reference: {path}")
        reference_count = asset.get("reference_count")
        if isinstance(reference_count, bool) or not isinstance(reference_count, int) or reference_count < 0:
            raise FrozenAuthorityError(f"{label} asset has invalid reference_count: {path}")
        reference_surfaces = asset.get("reference_surfaces")
        if not isinstance(reference_surfaces, Mapping):
            raise FrozenAuthorityError(f"{label} asset has no reference_surfaces: {path}")
        for surface in ("checkpoint", "production", "test"):
            value = reference_surfaces.get(surface)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise FrozenAuthorityError(
                    f"{label} asset has invalid reference surface {surface}: {path}"
                )

        logical = asset.get("sqlite_logical_fingerprint")
        companion = asset.get("sqlite_physical_companion")
        if logical is not None:
            if not isinstance(logical, Mapping):
                raise FrozenAuthorityError(f"{label} SQLite logical record is not an object: {path}")
            required = (
                "status",
                "database_file_sha256",
                "database_file_size",
                "integrity_check",
                "schema",
                "table_counts",
                "row_fingerprint",
                "table_fingerprints",
                "logical_fingerprint",
                "read_only_uri_contract",
                "wal_shm_excluded",
            )
            missing = [key for key in required if key not in logical]
            if missing:
                raise FrozenAuthorityError(
                    f"{label} SQLite logical record missing {missing}: {path}"
                )
            if logical.get("status") != "ok":
                raise FrozenAuthorityError(f"{label} SQLite logical record is unresolved: {path}")
            if logical.get("database_file_sha256") != asset.get("sha256"):
                raise FrozenAuthorityError(
                    f"{label} SQLite logical/database hash mismatch: {path}"
                )
            if logical.get("read_only_uri_contract") != "file:<absolute-path>?mode=ro&immutable=1":
                raise FrozenAuthorityError(f"{label} SQLite read-only URI contract mismatch: {path}")
            if logical.get("wal_shm_excluded") is not True:
                raise FrozenAuthorityError(f"{label} SQLite logical record includes WAL/SHM: {path}")
            if not isinstance(logical.get("integrity_check"), list) or not logical["integrity_check"]:
                raise FrozenAuthorityError(f"{label} SQLite integrity result is missing: {path}")
            if any(str(value).casefold() != "ok" for value in logical["integrity_check"]):
                raise FrozenAuthorityError(f"{label} SQLite integrity result is not clean: {path}")
            if not isinstance(logical.get("schema"), list):
                raise FrozenAuthorityError(f"{label} SQLite schema is not normalized: {path}")
            for key in ("table_counts", "row_fingerprint", "table_fingerprints"):
                if not isinstance(logical.get(key), Mapping):
                    raise FrozenAuthorityError(f"{label} SQLite {key} is missing: {path}")
        if companion is not None:
            if not isinstance(companion, Mapping):
                raise FrozenAuthorityError(f"{label} SQLite companion is not an object: {path}")
            if companion.get("physical_hash_only") is not True:
                raise FrozenAuthorityError(f"{label} SQLite companion is not physical-only: {path}")
            if companion.get("logical_change_never_inferred") is not True:
                raise FrozenAuthorityError(f"{label} SQLite companion can infer logical state: {path}")
            if companion.get("logical_state") != "not_inferred":
                raise FrozenAuthorityError(f"{label} SQLite companion has logical state: {path}")

        result[path] = asset

    reports = manifest.get("rule_reports")
    if not isinstance(reports, list) or not reports:
        raise FrozenAuthorityError(f"{label} manifest rule_reports are missing")
    report_ids: set[str] = set()
    for report in reports:
        if not isinstance(report, Mapping):
            raise FrozenAuthorityError(f"{label} manifest contains a non-object rule report")
        rule_id = str(report.get("id", ""))
        owner = str(report.get("owner", ""))
        if not rule_id or rule_id in report_ids:
            raise FrozenAuthorityError(f"{label} manifest has duplicate/empty rule report: {rule_id!r}")
        report_ids.add(rule_id)
        if not owner:
            raise FrozenAuthorityError(f"{label} manifest has ownerless rule report: {rule_id}")
        if report.get("allowed") != "read_only":
            raise FrozenAuthorityError(f"{label} rule report is not read_only: {rule_id}")
        mandatory = report.get("mandatory")
        if not isinstance(mandatory, bool):
            raise FrozenAuthorityError(
                f"{label} rule report has invalid mandatory flag: {rule_id}={mandatory!r}"
            )
        count = report.get("resolved_path_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise FrozenAuthorityError(f"{label} rule report has invalid match count: {rule_id}")
        if report.get("mandatory") is True and count == 0:
            raise FrozenAuthorityError(f"{label} rule report is unresolved: {rule_id}")
        reference_count = report.get("reference_count")
        if isinstance(reference_count, bool) or not isinstance(reference_count, int) or reference_count < 0:
            raise FrozenAuthorityError(f"{label} rule report has invalid reference_count: {rule_id}")
        inventory_stale_missing_count = report.get("inventory_stale_missing_count")
        if (
            isinstance(inventory_stale_missing_count, bool)
            or not isinstance(inventory_stale_missing_count, int)
            or inventory_stale_missing_count < 0
        ):
            raise FrozenAuthorityError(
                f"{label} rule report has invalid inventory_stale_missing_count: "
                f"{rule_id}={inventory_stale_missing_count!r}"
            )

    _validate_manifest_summary(manifest, assets, reports, label=label)
    return result


def _logical_sqlite_material(fingerprint: Mapping[str, Any]) -> Mapping[str, Any]:
    """Strip physical main-file metadata from logical comparison material."""

    return {
        key: fingerprint.get(key)
        for key in (
            "integrity_check",
            "schema",
            "table_counts",
            "row_fingerprint",
            "table_fingerprints",
            "logical_fingerprint",
        )
    }


def compare_sqlite_logical_fingerprints(
    frozen_manifest: Mapping[str, Any],
    current_manifest: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Compare protected main-database logical state, excluding sidecars."""

    expected = {
        path: asset
        for path, asset in _manifest_asset_map(frozen_manifest, label="frozen").items()
        if asset.get("sqlite_logical_fingerprint") is not None
    }
    actual = {
        path: asset
        for path, asset in _manifest_asset_map(current_manifest, label="current").items()
        if asset.get("sqlite_logical_fingerprint") is not None
    }
    added = sorted(set(actual) - set(expected))
    missing = sorted(set(expected) - set(actual))
    changed: list[dict[str, Any]] = []
    for path in sorted(set(expected) & set(actual)):
        expected_fp = expected[path]["sqlite_logical_fingerprint"]
        actual_fp = actual[path]["sqlite_logical_fingerprint"]
        if _logical_sqlite_material(expected_fp) != _logical_sqlite_material(actual_fp):
            changed.append(
                {
                    "path": path,
                    "expected": _logical_sqlite_material(expected_fp),
                    "actual": _logical_sqlite_material(actual_fp),
                }
            )
    if added or missing or changed:
        raise FrozenAuthorityError(
            "protected SQLite logical row change: "
            f"added={added[:20]} missing={missing[:20]} changed={[item['path'] for item in changed[:20]]}"
        )
    return {
        "ok": True,
        "compared_count": len(expected),
        "added": [],
        "missing": [],
        "changed": [],
        "wal_shm_physical_only": True,
    }


def compare_physical_manifest(
    frozen_manifest: Mapping[str, Any],
    current_manifest: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Compare the complete manifest and fail closed on every protected drift."""

    expected = _manifest_asset_map(frozen_manifest, label="frozen")
    actual = _manifest_asset_map(current_manifest, label="current")
    for key in ("unknown_source_diffs", "unknown_source_paths"):
        unknown = current_manifest.get(key)
        if unknown:
            raise FrozenAuthorityError(f"unknown source diff: {key}={unknown!r}")
    for key in ("schema_version", "policy_id", "manifest_kind", "rules_sha256", "source_rules_sha256"):
        if frozen_manifest.get(key) != current_manifest.get(key):
            raise FrozenAuthorityError(
                f"manifest contract drift for {key}: "
                f"expected={frozen_manifest.get(key)!r} actual={current_manifest.get(key)!r}"
            )
    for key in ("source_roots", "accepted_task02_inventory", "rule_reports", "canonicalization"):
        if frozen_manifest.get(key) != current_manifest.get(key):
            raise FrozenAuthorityError(f"manifest authority drift for {key}")

    logical_report = compare_sqlite_logical_fingerprints(frozen_manifest, current_manifest)
    added = sorted(set(actual) - set(expected))
    missing = sorted(set(expected) - set(actual))
    changed: list[dict[str, Any]] = []
    material_keys = (
        "path_type",
        "size",
        "mode",
        "sha256",
        "link_target",
        "resolved_sha256",
        "owner",
        "category",
        "categories",
        "rule_ids",
        "allowed",
        "reference_count",
        "reference_surfaces",
    )
    for path in sorted(set(expected) & set(actual)):
        delta = {
            key: {"expected": expected[path].get(key), "actual": actual[path].get(key)}
            for key in material_keys
            if expected[path].get(key) != actual[path].get(key)
        }
        if delta:
            changed.append({"path": path, "delta": delta})
    if added or missing or changed:
        raise FrozenAuthorityError(
            f"physical protected manifest drift: added={added[:20]} missing={missing[:20]} changed={changed[:20]}"
        )
    return {
        "ok": True,
        "asset_count": len(expected),
        "added": [],
        "missing": [],
        "changed": [],
        "logical_sqlite_comparison": logical_report,
    }


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path = _lexical_absolute(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(payload, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--freeze-rules",
        action="store_true",
        help="Resolve current paths once, write concrete resolved_paths into --rules, then build output.",
    )
    args = parser.parse_args(argv)
    rules = load_rules(args.rules)
    inventory = load_inventory(rules)
    resolutions, _ = resolve_rules(rules, inventory, validate_frozen=not args.freeze_rules)
    if args.freeze_rules:
        rules = freeze_rules(rules, resolutions, inventory)
        _write_json(args.rules, rules)
    manifest = build_manifest(rules, inventory)
    _write_json(args.output, manifest)
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
