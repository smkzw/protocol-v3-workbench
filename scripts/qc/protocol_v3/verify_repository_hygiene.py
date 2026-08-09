from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from classify_repository import (
    HygieneError,
    _iter_repository_paths,
    _metadata_for_path,
    classify_path,
    load_rules,
)


def _entry_owner(entry: Mapping[str, object]) -> str:
    return str(entry.get("owner", "workbench_unresolved"))


def _drift_is_allowed(entry: Mapping[str, object], allowed: set) -> bool:
    return (
        _entry_owner(entry) in allowed
        and entry.get("classification") in {"protected_out_of_scope", "regenerable"}
    )


def verify_inventory_against_root(
    inventory: Mapping[str, object],
    root: Path,
    allowed_drift_owners: Iterable[str] = (),
    rules: Optional[Mapping[str, object]] = None,
) -> Mapping[str, object]:
    root = root.resolve(strict=True)
    allowed = set(allowed_drift_owners)
    expected_entries = {str(entry["path"]): dict(entry) for entry in inventory["entries"]}
    if len(expected_entries) != len(inventory["entries"]):
        raise HygieneError("inventory contains duplicate paths")
    actual_paths = {path.relative_to(root).as_posix() for path in _iter_repository_paths(root)}
    expected_paths = set(expected_entries)
    added = sorted(actual_paths - expected_paths)
    missing = sorted(expected_paths - actual_paths)
    blocked_added = []
    allowed_added = []
    for path in added:
        disposition = (
            classify_path(path, rules)
            if rules is not None
            else {
                "classification": "quarantine",
                "owner": "workbench_unresolved",
                "rule_id": "no_rules_for_added_path",
            }
        )
        record = {
            "path": path,
            "owner": disposition["owner"],
            "classification": disposition["classification"],
            "rule_id": disposition["rule_id"],
        }
        (allowed_added if _drift_is_allowed(disposition, allowed) else blocked_added).append(record)
    blocked_missing = [path for path in missing if not _drift_is_allowed(expected_entries[path], allowed)]
    allowed_missing = [path for path in missing if _drift_is_allowed(expected_entries[path], allowed)]

    changed = []
    allowed_changed = []
    for path in sorted(actual_paths & expected_paths):
        expected = expected_entries[path]
        actual = _metadata_for_path(root, root / path)
        material_keys = ("path_type", "size", "mtime_ns", "mode", "sha256", "link_target", "resolved_sha256", "escapes_root")
        mismatches = {
            key: {"expected": expected.get(key), "actual": actual.get(key)}
            for key in material_keys
            if expected.get(key) != actual.get(key)
        }
        if not mismatches:
            continue
        record = {"path": path, "owner": _entry_owner(expected), "mismatches": mismatches}
        if _drift_is_allowed(expected, allowed):
            allowed_changed.append(record)
        else:
            changed.append(record)

    if blocked_added or blocked_missing or changed:
        raise HygieneError(
            "repository inventory drift; added=%r missing=%r changed=%r"
            % (blocked_added[:20], blocked_missing[:20], changed[:20])
        )
    return {
        "root": str(root),
        "entry_count": len(expected_entries),
        "inventory_fingerprint": inventory["inventory_fingerprint"],
        "allowed_drift_owners": sorted(allowed),
        "allowed_added": allowed_added,
        "allowed_missing": allowed_missing,
        "allowed_changed": allowed_changed,
        "blocked_drift_count": 0,
    }


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Verify a repository hygiene inventory against its live root.")
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--allow-drift-owner", action="append", default=[])
    args = parser.parse_args(list(argv) if argv else None)
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    result = verify_inventory_against_root(
        inventory,
        args.root,
        args.allow_drift_owner,
        rules=load_rules(args.rules),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
