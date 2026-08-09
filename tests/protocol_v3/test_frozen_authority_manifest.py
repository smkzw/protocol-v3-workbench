"""Task 0.4 fail-closed protection and SQLite contradiction tests."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = ROOT / "scripts/qc/protocol_v3/build_frozen_authority_manifest.py"
RULES_PATH = ROOT / "tests/fixtures/protocol_v3/protected_path_rules.json"
MANIFEST_PATH = ROOT / "tests/fixtures/protocol_v3/immutable_protected_assets.json"
BASELINE_PATH = ROOT / "tests/fixtures/protocol_v3/mutable_source_baseline.json"
DC018_PATH = ROOT / "plans/mw_protocol_multi_agent_rearchitecture_design_clarification_dc018.md"

EXPECTED_PLAN_SHA256 = "fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914"
EXPECTED_DESIGN_SHA256 = "321169afc9f33f572b803661b6c6eeb598304267fcb33cdf7de4faf0b00ad0d8"
EXPECTED_DECISIONS_SHA256 = "04d99dd3cb239c49f5de52d1b0fe0fdd959007def509e0931907614894eb816a"
EXPECTED_DC018_SHA256 = "01a6b66e39465bdb42012192761fdfe4d852f18edf176752bba6406528108974"
EXPECTED_BASELINE_SHA256 = "32e274b47ec14a40f0bcaa280b4e8b81ccf06f61b3ee0c0606055d4d54f27d67"
EXPECTED_BASELINE_COMMIT = "2a4837e24a0cb71129fbd3f1e8672b8f9e6e8323"


def _load_builder():
    spec = importlib.util.spec_from_file_location("protocol_v3_frozen_manifest", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import builder: {BUILDER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BUILDER = _load_builder()
FROZEN = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_manifest_with_asset(frozen: dict, index: int, **changes) -> dict:
    current = dict(frozen)
    current["assets"] = list(frozen["assets"])
    asset = dict(frozen["assets"][index])
    asset.update(changes)
    current["assets"][index] = asset
    return current


def _minimal_manifest(assets: list[dict], *, rules_sha: str = "rules", source_rules_sha: str = "source") -> dict:
    by_owner: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for asset in assets:
        by_owner[asset["owner"]] = by_owner.get(asset["owner"], 0) + 1
        for category in asset["categories"]:
            by_category[category] = by_category.get(category, 0) + 1
    return {
        "schema_version": 1,
        "policy_id": BUILDER.POLICY_ID,
        "manifest_kind": "immutable_protected_assets",
        "rules_sha256": rules_sha,
        "source_rules_sha256": source_rules_sha,
        "source_roots": {
            "root": "/tmp/protocol-v3-test-root",
            "cmss_sop_protocol_candidate_root": "/tmp/protocol-v3-test-root/cmss",
        },
        "accepted_task02_inventory": {"path": "/tmp/inventory.json", "sha256": "inventory", "inventory_fingerprint": "fingerprint"},
        "canonicalization": {"encoding": "utf-8", "ensure_ascii": False, "sort_keys": True, "separators": [",", ":"], "newline": "\\n"},
        "assets": assets,
        "rule_reports": [
            {
                "id": "test_rule",
                "owner": "test_owner",
                "category": "test",
                "mandatory": True,
                "allowed": "read_only",
                "resolved_path_count": len(assets),
                "resolved_path_set_sha256": "path-set",
                "reference_count": 0,
                "pattern_match_counts": {"test": len(assets)},
                "scope_prefix_count": 0,
                "dependency_edge_count": 0,
                "inventory_stale_missing_count": 0,
            }
        ],
        "summary": {
            "asset_count": len(assets),
            "physical_fingerprint": BUILDER.canonical_json_sha256(
                [BUILDER._physical_asset_material(asset) for asset in assets]
            ),
            "by_owner": by_owner,
            "by_category": by_category,
            "mandatory_rule_count": 1,
            "unresolved_count": 0,
            "unresolved_rule_ids": [],
            "zero_match_rule_count": 0,
            "zero_match_rule_ids": [],
            "ownerless_count": 0,
            "duplicate_path_owner_conflict_count": 0,
            "symlink_escape_count": 0,
            "unknown_current_path_count": 0,
            "inventory_stale_missing_count": 0,
            "inventory_stale_missing_paths": [],
            "sqlite_main_count": sum("sqlite_logical_fingerprint" in asset for asset in assets),
            "sqlite_sidecar_count": sum("sqlite_physical_companion" in asset for asset in assets),
            "sqlite_logical_ready_count": sum(
                isinstance(asset.get("sqlite_logical_fingerprint"), dict)
                and asset["sqlite_logical_fingerprint"].get("status") == "ok"
                for asset in assets
            ),
            "cmss_sop_protocol_candidate_count": 0,
        },
    }


def _asset_base(path: Path, *, owner: str = "test_owner", rule_id: str = "test_rule") -> dict:
    path = path.resolve()
    return {
        "path": str(path),
        "path_type": "file",
        "size": path.stat().st_size,
        "mode": stat.S_IMODE(path.stat().st_mode),
        "sha256": _sha256(path),
        "link_target": None,
        "resolved_path": None,
        "resolved_sha256": None,
        "owner": owner,
        "category": "test",
        "categories": ["test"],
        "rule_ids": [rule_id],
        "allowed": "read_only",
        "reference_count": 0,
        "reference_surfaces": {"checkpoint": 0, "production": 0, "test": 0},
    }


def _sqlite_asset(path: Path, fingerprint: dict, *, logical_path: Path | None = None) -> dict:
    asset = _asset_base(path)
    if logical_path is not None:
        asset["path"] = str(logical_path.resolve())
    asset["sqlite_logical_fingerprint"] = fingerprint
    return asset


def _sidecar_asset(path: Path, main_path: Path, *, logical_path: Path | None = None) -> dict:
    asset = _asset_base(path)
    if logical_path is not None:
        asset["path"] = str(logical_path.resolve())
    asset["sqlite_physical_companion"] = {
        "logical_state": "not_inferred",
        "physical_hash_only": True,
        "logical_change_never_inferred": True,
        "sidecar_kind": "wal" if path.name.endswith("-wal") else "shm",
        "main_path": str(main_path.resolve()),
    }
    return asset


def _synthetic_inventory_case(tmp_path: Path) -> tuple[dict, dict, list[Path], list[str], str]:
    inventory_root = tmp_path / "inventory"
    inventory_root.mkdir()
    missing_relative = [f"records/missing_{index:02d}.json" for index in range(12)]
    present_relative = "records/present.json"
    present_path = inventory_root / present_relative
    present_path.parent.mkdir(parents=True)
    present_path.write_text("present\n", encoding="utf-8")
    missing_paths = [str((inventory_root / relative).resolve()) for relative in missing_relative]
    entries = [
        {"owner": "medical_monitoring", "path": relative}
        for relative in missing_relative + [present_relative]
    ]
    rule = {
        "id": BUILDER.MEDICAL_MONITORING_INVENTORY_RULE_ID,
        "owner": "medical_monitoring",
        "category": "medical_monitoring_source_tests_runs_records",
        "allowed": "read_only",
        "locator_type": "inventory_owner",
        "inventory_owner": "medical_monitoring",
        "mandatory": True,
        "minimum_match_count": 1,
        "inventory_stale_missing_count": len(missing_paths),
        "inventory_stale_missing_paths": missing_paths,
    }
    inventory = {"root": str(inventory_root), "entries": entries}
    return rule, inventory, [inventory_root.resolve()], missing_paths, str(present_path.resolve())


def test_clean_manifest_passes_and_covers_all_authority_surfaces():
    result = BUILDER.compare_physical_manifest(FROZEN, FROZEN)
    assert result["ok"] is True
    assert result["asset_count"] == 5992
    assert result["logical_sqlite_comparison"]["compared_count"] == 1211
    assert FROZEN["summary"]["mandatory_rule_count"] == 9
    assert FROZEN["summary"]["sqlite_logical_ready_count"] == 1211
    assert FROZEN["summary"]["sqlite_sidecar_count"] == 1776
    assert FROZEN["summary"]["cmss_sop_protocol_candidate_count"] == 13
    assert FROZEN["summary"]["unresolved_count"] == 0
    assert FROZEN["summary"]["ownerless_count"] == 0
    cmss_root = FROZEN["source_roots"]["cmss_sop_protocol_candidate_root"]
    cmss_assets = [asset["path"] for asset in FROZEN["assets"] if cmss_root in asset["path"]]
    assert len(cmss_assets) == 13
    assert all(path.casefold().endswith((".docx", ".xlsx")) for path in cmss_assets)
    assert all("CMSS-SOP-MD-5101" in path for path in cmss_assets)


def test_summary_asset_count_tamper_fails_closed():
    for forged_count in (len(FROZEN["assets"]) + 1, True):
        current = copy.deepcopy(FROZEN)
        current["summary"]["asset_count"] = forged_count
        assert current["assets"] == FROZEN["assets"]
        with pytest.raises(BUILDER.FrozenAuthorityError, match=r"summary\.asset_count"):
            BUILDER.compare_physical_manifest(FROZEN, current)


def test_summary_physical_fingerprint_tamper_fails_closed():
    current = copy.deepcopy(FROZEN)
    current["summary"]["physical_fingerprint"] = "forged-derived-fingerprint"
    assert current["assets"] == FROZEN["assets"]
    with pytest.raises(BUILDER.FrozenAuthorityError, match=r"summary\.physical_fingerprint"):
        BUILDER.compare_physical_manifest(FROZEN, current)


def test_exact_missing_allowlist_current_twelve_passes_with_synthetic_observation(tmp_path: Path):
    rules = BUILDER.load_rules(RULES_PATH)
    persisted = next(
        rule
        for rule in rules["rules"]
        if rule["id"] == BUILDER.MEDICAL_MONITORING_INVENTORY_RULE_ID
    )
    assert persisted["inventory_stale_missing_count"] == 12
    assert len(persisted["inventory_stale_missing_paths"]) == 12
    assert BUILDER._inventory_missing_allowlist(
        persisted, BUILDER._allowed_roots(rules)
    ) == set(persisted["inventory_stale_missing_paths"])

    rule, inventory, allowed_roots, missing_paths, _ = _synthetic_inventory_case(tmp_path)
    resolution = BUILDER._resolve_rule_locators(
        rule,
        {},
        inventory,
        allowed_roots,
        {},
    )
    assert resolution["missing_inventory_paths"] == missing_paths
    assert len(resolution["paths"]) == 1


def test_missing_allowlist_rejects_raw_relative_spelling():
    rules = BUILDER.load_rules(RULES_PATH)
    persisted = next(
        rule
        for rule in rules["rules"]
        if rule["id"] == BUILDER.MEDICAL_MONITORING_INVENTORY_RULE_ID
    )
    relative_rule = copy.deepcopy(persisted)
    raw_absolute = persisted["inventory_stale_missing_paths"][0]
    raw_relative = os.path.relpath(raw_absolute, start=ROOT)
    assert not os.path.isabs(raw_relative)
    relative_rule["inventory_stale_missing_paths"][0] = raw_relative
    with pytest.raises(BUILDER.FrozenAuthorityError, match="absolute raw entries"):
        BUILDER._inventory_missing_allowlist(relative_rule, BUILDER._allowed_roots(rules))


def test_missing_allowlist_removal_blocks_with_synthetic_inventory(tmp_path: Path):
    rule, inventory, allowed_roots, missing_paths, _ = _synthetic_inventory_case(tmp_path)
    rule["inventory_stale_missing_paths"] = missing_paths[:-1]
    rule["inventory_stale_missing_count"] = len(missing_paths) - 1
    with pytest.raises(BUILDER.FrozenAuthorityError, match="no_longer_missing"):
        BUILDER._resolve_rule_locators(rule, {}, inventory, allowed_roots, {})


def test_missing_allowlist_unobserved_addition_blocks_with_synthetic_inventory(tmp_path: Path):
    rule, inventory, allowed_roots, missing_paths, present_path = _synthetic_inventory_case(tmp_path)
    rule["inventory_stale_missing_paths"] = missing_paths + [present_path]
    rule["inventory_stale_missing_count"] = len(missing_paths) + 1
    with pytest.raises(BUILDER.FrozenAuthorityError, match="no_longer_missing"):
        BUILDER._resolve_rule_locators(rule, {}, inventory, allowed_roots, {})


def test_missing_allowlist_newly_missing_entry_blocks_with_synthetic_inventory(tmp_path: Path):
    rule, inventory, allowed_roots, _, _ = _synthetic_inventory_case(tmp_path)
    inventory["entries"].append(
        {"owner": "medical_monitoring", "path": "records/newly_missing.json"}
    )
    with pytest.raises(BUILDER.FrozenAuthorityError, match="newly_missing"):
        BUILDER._resolve_rule_locators(rule, {}, inventory, allowed_roots, {})


def test_persisted_cmss_rule_is_authority_not_runtime_synthesis():
    rules = BUILDER.load_rules(RULES_PATH)
    cmss_rules = [
        rule
        for rule in rules["rules"]
        if rule.get("id") == BUILDER.CMSS_SOP_PROTOCOL_RULE_ID
    ]
    assert len(rules["rules"]) == 9
    assert len(cmss_rules) == 1
    persisted = cmss_rules[0]
    effective = BUILDER._effective_rules(rules)
    assert effective == rules
    assert persisted["owner"] == "clinical_template_authority"
    assert persisted["allowed"] == "read_only"
    assert persisted["locator_type"] == "patterns"
    assert persisted["mandatory"] is True
    assert persisted["require_each_pattern"] is True
    assert len(persisted["resolved_paths"]) == 13
    assert persisted["reference_count"] >= 0
    assert set(persisted["reference_counts"]) == set(persisted["resolved_paths"])
    assert set(persisted["reference_surfaces"]) == set(persisted["resolved_paths"])
    assert FROZEN["rules_sha256"] == FROZEN["source_rules_sha256"]
    assert FROZEN["source_rules_sha256"] == BUILDER.canonical_json_sha256(rules)
    output_rule = next(
        report
        for report in FROZEN["rule_reports"]
        if report["id"] == BUILDER.CMSS_SOP_PROTOCOL_RULE_ID
    )
    assert output_rule["owner"] == persisted["owner"]
    assert output_rule["allowed"] == persisted["allowed"]
    assert output_rule["resolved_path_count"] == 13
    assert isinstance(output_rule["reference_count"], int)
    for asset in FROZEN["assets"]:
        if BUILDER.CMSS_SOP_PROTOCOL_RULE_ID not in asset["rule_ids"]:
            continue
        assert asset["owner"] == persisted["owner"]
        assert asset["allowed"] == persisted["allowed"]
        assert isinstance(asset["reference_count"], int)
        assert set(asset["reference_surfaces"]) == {"checkpoint", "production", "test"}
    omitted = copy.deepcopy(rules)
    omitted["rules"] = [
        rule
        for rule in omitted["rules"]
        if rule.get("id") != BUILDER.CMSS_SOP_PROTOCOL_RULE_ID
    ]
    with pytest.raises(BUILDER.FrozenAuthorityError, match="must contain exactly one"):
        BUILDER._effective_rules(omitted)


def test_exact_authority_hashes_and_mutable_baseline_commit_are_frozen():
    assert _sha256(DC018_PATH) == EXPECTED_DC018_SHA256
    assert _sha256(ROOT / ".hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md") == EXPECTED_PLAN_SHA256
    assert _sha256(ROOT / "plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md") == EXPECTED_DESIGN_SHA256
    assert _sha256(ROOT / "plans/mw_system_rearchitecture_design_decisions_20260808.md") == EXPECTED_DECISIONS_SHA256
    assert _sha256(BASELINE_PATH) == EXPECTED_BASELINE_SHA256
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline["source_commit"] == EXPECTED_BASELINE_COMMIT
    assert baseline["entry_count"] == 1029
    assert baseline["content_fingerprint"] == "3606b57b4e82164a0f622ec84a0ee8c0a4ad8585c7b82a845ebcee3e71707540"
    assert baseline["tree_audit"]["unknown_entries"] == []


def test_deterministic_rebuild_and_required_owner_reference_fields(tmp_path: Path):
    database = tmp_path / "fixture.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO rows(value) VALUES ('stable')")
        connection.commit()
    first = BUILDER.fingerprint_sqlite(database)
    second = BUILDER.fingerprint_sqlite(database)
    assert BUILDER.canonical_json_bytes(first) == BUILDER.canonical_json_bytes(second)
    assert first["status"] == "ok"
    assert first["table_counts"] == {"rows": 1}
    assert first["read_only_uri_contract"] == "file:<absolute-path>?mode=ro&immutable=1"
    for asset in FROZEN["assets"]:
        assert asset["owner"]
        assert asset["rule_ids"]
        assert asset["allowed"] == "read_only"
        assert isinstance(asset["reference_count"], int)
        assert set(asset["reference_surfaces"]) == {"checkpoint", "production", "test"}
    sqlite_assets = [asset for asset in FROZEN["assets"] if "sqlite_logical_fingerprint" in asset]
    assert len(sqlite_assets) == FROZEN["summary"]["sqlite_main_count"] == 1211
    assert {
        asset["sqlite_logical_fingerprint"]["read_only_uri_contract"]
        for asset in sqlite_assets
    } == {"file:<absolute-path>?mode=ro&immutable=1"}


def test_copied_source_mutation_and_unknown_source_diff_fail_closed(tmp_path: Path):
    source_asset_index = next(
        index
        for index, asset in enumerate(FROZEN["assets"])
        if asset["path"].endswith("mw_protocol_multi_agent_rearchitecture_design_20260809.md")
    )
    source = Path(FROZEN["assets"][source_asset_index]["path"])
    copied = tmp_path / source.name
    shutil.copy2(source, copied)
    copied.write_bytes(copied.read_bytes() + b"\n# adversarial source mutation\n")
    current = _copy_manifest_with_asset(
        FROZEN,
        source_asset_index,
        size=copied.stat().st_size,
        sha256=_sha256(copied),
    )
    with pytest.raises(
        BUILDER.FrozenAuthorityError,
        match=r"(summary\.physical_fingerprint|physical protected manifest drift)",
    ):
        BUILDER.compare_physical_manifest(FROZEN, current)

    unknown = dict(FROZEN)
    unknown["unknown_source_diffs"] = [str(tmp_path / "not-in-frozen-baseline.py")]
    with pytest.raises(BUILDER.FrozenAuthorityError, match="unknown source diff"):
        BUILDER.compare_physical_manifest(FROZEN, unknown)

    unknown_path = tmp_path / "unknown.py"
    unknown_path.write_text("UNKNOWN = True\n", encoding="utf-8")
    unknown_asset = _asset_base(unknown_path, owner="unknown_owner", rule_id="unknown_rule")
    unknown_asset_manifest = dict(FROZEN)
    unknown_asset_manifest["assets"] = list(FROZEN["assets"]) + [unknown_asset]
    with pytest.raises(
        BUILDER.FrozenAuthorityError,
        match=r"(summary\.asset_count|physical protected manifest drift)",
    ):
        BUILDER.compare_physical_manifest(FROZEN, unknown_asset_manifest)


def test_copied_sqlite_row_mutation_fails_logical_comparator(tmp_path: Path):
    original = tmp_path / "original.sqlite3"
    with sqlite3.connect(original) as connection:
        connection.execute("CREATE TABLE protected_rows (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO protected_rows(value) VALUES ('before')")
        connection.commit()
    original_hash = _sha256(original)
    copied = tmp_path / "copied.sqlite3"
    shutil.copy2(original, copied)
    with sqlite3.connect(copied) as connection:
        connection.execute("UPDATE protected_rows SET value = 'after' WHERE id = 1")
        connection.commit()

    before = dict(BUILDER.fingerprint_sqlite(original))
    after = dict(BUILDER.fingerprint_sqlite(copied))
    assert before["read_only_uri_contract"].endswith("mode=ro&immutable=1")
    assert before["table_counts"] == after["table_counts"]
    assert before["row_fingerprint"] != after["row_fingerprint"]
    assert _sha256(original) == original_hash

    frozen_asset = _sqlite_asset(original, before)
    current_asset = _sqlite_asset(copied, after, logical_path=original)
    frozen = _minimal_manifest([frozen_asset])
    current = _minimal_manifest([current_asset])
    with pytest.raises(BUILDER.FrozenAuthorityError, match="protected SQLite logical row change"):
        BUILDER.compare_physical_manifest(frozen, current)


def test_wal_shm_physical_only_drift_never_becomes_logical_row_change(tmp_path: Path):
    database = tmp_path / "protected.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE rows (id INTEGER PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO rows(value) VALUES ('same')")
        connection.commit()
    fingerprint = dict(BUILDER.fingerprint_sqlite(database))
    wal = tmp_path / "protected.sqlite3-wal"
    shm = tmp_path / "protected.sqlite3-shm"
    wal.write_bytes(b"baseline-wal")
    shm.write_bytes(b"baseline-shm")
    main_asset = _sqlite_asset(database, fingerprint)
    wal_asset = _sidecar_asset(wal, database)
    shm_asset = _sidecar_asset(shm, database)
    frozen = _minimal_manifest([main_asset, wal_asset, shm_asset])

    current_wal = tmp_path / "current.sqlite3-wal"
    current_shm = tmp_path / "current.sqlite3-shm"
    shutil.copy2(wal, current_wal)
    shutil.copy2(shm, current_shm)
    current_wal.write_bytes(b"physical-only-wal-change")
    current_shm.write_bytes(b"physical-only-shm-change")
    current_main = _sqlite_asset(database, fingerprint)
    current_wal_asset = _sidecar_asset(current_wal, database, logical_path=wal)
    current_shm_asset = _sidecar_asset(current_shm, database, logical_path=shm)
    current = _minimal_manifest([current_main, current_wal_asset, current_shm_asset])

    assert BUILDER.compare_sqlite_logical_fingerprints(frozen, current)["ok"] is True
    with pytest.raises(BUILDER.FrozenAuthorityError, match="physical protected manifest drift") as error:
        BUILDER.compare_physical_manifest(frozen, current)
    assert "protected SQLite logical row change" not in str(error.value)


def test_symlink_escape_ownerless_and_unresolved_rules_fail_closed(tmp_path: Path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    target = outside / "secret.txt"
    target.write_text("outside\n", encoding="utf-8")
    link = allowed / "escape.txt"
    link.symlink_to(target)
    with pytest.raises(BUILDER.FrozenAuthorityError, match="(absolute symlink target|symlink escapes allowed roots)"):
        BUILDER._validate_symlink(link, [allowed.resolve()])
    relative_link = allowed / "relative_escape.txt"
    relative_link.symlink_to(Path("../outside/secret.txt"))
    with pytest.raises(BUILDER.FrozenAuthorityError, match="symlink escapes allowed roots"):
        BUILDER._validate_symlink(relative_link, [allowed.resolve()])

    ownerless = dict(FROZEN)
    ownerless["rule_reports"] = [dict(report) for report in FROZEN["rule_reports"]]
    ownerless["rule_reports"][0]["owner"] = ""
    with pytest.raises(BUILDER.FrozenAuthorityError, match="ownerless rule report"):
        BUILDER.compare_physical_manifest(FROZEN, ownerless)

    unresolved = dict(FROZEN)
    unresolved["rule_reports"] = [dict(report) for report in FROZEN["rule_reports"]]
    unresolved["rule_reports"][0]["mandatory"] = True
    unresolved["rule_reports"][0]["resolved_path_count"] = 0
    unresolved["summary"] = dict(FROZEN["summary"])
    unresolved["summary"]["unresolved_count"] = 1
    unresolved["summary"]["zero_match_rule_count"] = 1
    with pytest.raises(BUILDER.FrozenAuthorityError, match="unresolved"):
        BUILDER.compare_physical_manifest(FROZEN, unresolved)

    missing_reference = _copy_manifest_with_asset(FROZEN, 0)
    del missing_reference["assets"][0]["reference_count"]
    with pytest.raises(BUILDER.FrozenAuthorityError, match="reference_count"):
        BUILDER.compare_physical_manifest(FROZEN, missing_reference)
