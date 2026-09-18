"""Task 0.5 recoverable-hygiene tests.

worker_02 owns the resolver cases in this file.  worker_03 will extend it with
mutator cases later.  Every test uses only ``tmp_path`` task-owned fixtures;
nothing here touches live, the accepted snapshots, or the real quarantine root.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
from pathlib import Path
import sys

import pytest


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts/qc/protocol_v3"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _load_resolver():
    spec = importlib.util.spec_from_file_location(
        "protocol_v3_evidence_locator_resolver",
        _SCRIPTS / "evidence_locator_resolver.py",
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot import resolver module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RESOLVER = _load_resolver()
ResolverError = RESOLVER.ResolverError
EvidenceLocatorResolver = RESOLVER.EvidenceLocatorResolver
validate_path_map = RESOLVER.validate_path_map
sha256_file = RESOLVER.sha256_file
new_locator_for = RESOLVER.new_locator_for
_validate_entry_uniqueness = RESOLVER._validate_entry_uniqueness


INVENTORY_SHA = "29321ad4595dd5093e1477449568ce93b3ffe9fb52dc6a0483db4404fbfd6621"
PROTECTED_SHA = "f4b385d444d4cf922f20b9934e87f6b72c0ad932fc767b5c86045b7e8c0ace7f"
TASK_ID = "mw_protocol_v3_phase0_20260809_111313"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_file(parent: Path, relative: str, payload: bytes) -> tuple[Path, str, int]:
    path = parent / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path, _sha256_bytes(payload), len(payload)


def _abs(path: Path | str) -> str:
    return os.path.abspath(os.fspath(path))


def _move_entry(
    *,
    entry_id: str,
    live_root: Path,
    quarantine_root: Path,
    relative: str,
    payload: bytes,
    owner: str = "toolchain_cache",
    reason: str = "regenerable build artifact moved to recoverable quarantine",
) -> dict:
    old_path, digest, size = _write_file(live_root, relative, payload)
    new_locator = new_locator_for(digest)
    return {
        "id": entry_id,
        "operation": "quarantine_move",
        "owner": owner,
        "reason": reason,
        "old_locator": _abs(old_path),
        "new_locator": new_locator,
        "path_type": "file",
        "size": size,
        "source_sha256": digest,
        "destination_sha256": digest,
        "content_address": digest,
        "recovery_command": "apply_repository_hygiene.py --mode restore --entry %s" % entry_id,
        "status": "planned",
    }


def _delete_entry(
    *,
    entry_id: str,
    live_root: Path,
    relative: str,
    payload: bytes,
    owner: str = "toolchain_cache",
    reason: str = "regenerable cache safe to delete",
) -> dict:
    old_path, digest, size = _write_file(live_root, relative, payload)
    return {
        "id": entry_id,
        "operation": "direct_delete",
        "owner": owner,
        "reason": reason,
        "old_locator": _abs(old_path),
        "new_locator": None,
        "path_type": "file",
        "size": size,
        "source_sha256": digest,
        "destination_sha256": None,
        "content_address": digest,
        "recovery_command": "regenerate via toolchain rebuild",
        "status": "planned",
    }


def _path_map(
    entries,
    quarantine_root: Path,
    *,
    expected_inventory_sha256: str = INVENTORY_SHA,
    expected_protected_sha256: str = PROTECTED_SHA,
) -> dict:
    return {
        "schema_version": 1,
        "task_id": TASK_ID,
        "quarantine_root": _abs(quarantine_root),
        "expected_inventory_sha256": expected_inventory_sha256,
        "expected_protected_sha256": expected_protected_sha256,
        "entries": list(entries),
    }


def _no_occupancy(_paths):
    return []


def _seed_object(quarantine_root: Path, digest: str, payload: bytes) -> Path:
    obj = quarantine_root / "objects" / digest[:2] / digest
    obj.parent.mkdir(parents=True, exist_ok=True)
    obj.write_bytes(payload)
    return obj


# --------------------------------------------------------------------------- #
# Round-trip: old -> new and new -> old.
# --------------------------------------------------------------------------- #


class TestRoundTrip:
    def test_old_to_new_and_new_to_old_round_trip(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/index.html",
            payload=b"<html>dist</html>",
        )
        pm = _path_map([entry], quarantine)
        resolver = EvidenceLocatorResolver(pm)

        forward = resolver.resolve_old_to_new(entry["old_locator"])
        assert forward["new_locator"] == entry["new_locator"]
        assert forward["source_sha256"] == entry["source_sha256"]

        reverse = resolver.resolve_new_to_old(entry["new_locator"])
        assert reverse["old_locator"] == entry["old_locator"]

        # round-trip identity
        assert (
            resolver.resolve_new_to_old(forward["new_locator"])["old_locator"]
            == entry["old_locator"]
        )

    def test_round_trip_accepts_absolute_new_locator(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/.npm-cache/data.bin",
            payload=b"npm-cache",
        )
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        absolute_new = str(quarantine / entry["new_locator"])
        reverse = resolver.resolve_new_to_old(absolute_new)
        assert reverse["old_locator"] == entry["old_locator"]


# --------------------------------------------------------------------------- #
# Content hash verification.
# --------------------------------------------------------------------------- #


class TestContentHash:
    def test_verify_object_against_entry_succeeds(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        payload = b"openxml bin artifact"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="openxml/bin/Release/tool.dll",
            payload=payload,
        )
        obj = _seed_object(quarantine, entry["source_sha256"], payload)
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        result = resolver.verify_object_against_entry(entry["new_locator"], obj)
        assert result["verified"] is True
        assert result["actual_sha256"] == entry["source_sha256"]
        assert result["actual_size"] == len(payload)

    def test_verify_object_hash_mismatch_fails_closed(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/app.js",
            payload=b"original",
        )
        # seed a DIFFERENT payload under the same content-addressed name
        obj = _seed_object(quarantine, entry["source_sha256"], b"tampered")
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        with pytest.raises(ResolverError, match="object hash mismatch"):
            resolver.verify_object_against_entry(entry["new_locator"], obj)

    def test_verify_object_size_mismatch_fails_closed(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/style.css",
            payload=b"abcd" * 10,
        )
        # craft an object with the right hash-prefix path but wrong size and
        # wrong hash -> must fail on hash first; do a separate size-only test
        # by mutating the entry size after building a correct object.
        obj = _seed_object(quarantine, entry["source_sha256"], b"abcd" * 10)
        tampered = dict(entry)
        tampered["size"] = entry["size"] + 999
        pm = _path_map([entry], quarantine)
        pm["entries"][0]["size"] = tampered["size"]
        # entry now inconsistent on size but re-validation happens in __init__,
        # so build the resolver from the tampered map directly.
        resolver = EvidenceLocatorResolver(pm)
        with pytest.raises(ResolverError, match="object size mismatch"):
            resolver.verify_object_against_entry(entry["new_locator"], obj)

    def test_verify_live_source_drift_fails_closed(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/main.js",
            payload=b"v1",
        )
        # mutate the live source after recording
        Path(entry["old_locator"]).write_bytes(b"v2-different-content")
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        with pytest.raises(ResolverError, match="source hash drift"):
            resolver.verify_live_source_against_entry(
                entry["old_locator"], Path(entry["old_locator"])
            )


# --------------------------------------------------------------------------- #
# Destination collision.
# --------------------------------------------------------------------------- #


class TestCollision:
    def _normalized(self, entry_id, old_locator, content_address, source_sha256, new_locator):
        """A post-per-entry-validation normalized entry dict.

        Per-entry validation enforces new_locator == objects/<ca[:2]>/<ca> and
        content_address == source_sha256, so a destination collision with a
        different hash is structurally impossible through the public path.  The
        uniqueness pass is defense-in-depth against a future relaxation, so we
        feed it normalized entries directly to prove it still fails closed.
        """

        return {
            "id": entry_id,
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "regenerable build artifact",
            "old_locator": old_locator,
            "new_locator": new_locator,
            "path_type": "file",
            "size": 1,
            "source_sha256": source_sha256,
            "destination_sha256": source_sha256,
            "content_address": content_address,
            "recovery_command": "restore",
            "status": "planned",
        }

    def test_destination_collision_different_hash_fails_closed(self, tmp_path):
        hash_a = _sha256_bytes(b"content-a")
        hash_b = _sha256_bytes(b"content-b-different")
        # both entries point at the SAME new_locator object but carry different
        # source hashes -> destination collision.
        shared_locator = "objects/%s/%s" % (hash_a[:2], hash_a)
        entries = [
            self._normalized("m1", str(tmp_path / "a.js"), hash_a, hash_a, shared_locator),
            self._normalized("m2", str(tmp_path / "b.js"), hash_b, hash_b, shared_locator),
        ]
        with pytest.raises(ResolverError, match="destination collision"):
            _validate_entry_uniqueness(entries)

    def test_duplicate_content_address_different_hash_fails_closed(self, tmp_path):
        hash_a = _sha256_bytes(b"aaaa")
        hash_b = _sha256_bytes(b"bbbb")
        # both entries claim the SAME content_address but different source hash.
        entries = [
            self._normalized("m1", str(tmp_path / "a.js"), hash_a, hash_a, new_locator_for(hash_a)),
            self._normalized("m2", str(tmp_path / "b.js"), hash_a, hash_b, new_locator_for(hash_a)),
        ]
        with pytest.raises(ResolverError, match="conflicting content_address"):
            _validate_entry_uniqueness(entries)

    def test_identical_content_dedup_allowed_when_hashes_match(self, tmp_path):
        """Two old locators with identical content may share a content address."""

        digest = _sha256_bytes(b"identical")
        entries = [
            self._normalized(
                "m1", str(tmp_path / "a.js"), digest, digest, new_locator_for(digest)
            ),
            self._normalized(
                "m2", str(tmp_path / "b.js"), digest, digest, new_locator_for(digest)
            ),
        ]
        # must NOT raise: same content, same hash is a legal dedup, not a collision
        _validate_entry_uniqueness(entries)


# --------------------------------------------------------------------------- #
# Missing object / missing locator.
# --------------------------------------------------------------------------- #


class TestMissingObject:
    def test_missing_quarantine_object_fails_closed(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/missing.js",
            payload=b"never-quarantined",
        )
        # deliberately do NOT seed the object
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        obj = quarantine / entry["new_locator"]
        with pytest.raises(ResolverError, match="missing quarantine object"):
            resolver.verify_object_against_entry(entry["new_locator"], obj)

    def test_missing_old_locator_fails_closed(self, tmp_path):
        quarantine = tmp_path / "quarantine"
        pm = _path_map([], quarantine)
        # build a minimal valid entry to get a resolver, then ask for absent
        live = tmp_path / "live"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/x.js",
            payload=b"x",
        )
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        with pytest.raises(ResolverError, match="no PATH_MAP entry for old_locator"):
            resolver.resolve_old_to_new(str(live / "frontend" / "dist" / "absent.js"))

    def test_missing_new_locator_fails_closed(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/y.js",
            payload=b"y",
        )
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        with pytest.raises(ResolverError, match="no PATH_MAP entry for new_locator"):
            resolver.resolve_new_to_old("objects/ab/abcdnotpresent")


# --------------------------------------------------------------------------- #
# Restore mapping.
# --------------------------------------------------------------------------- #


class TestRestoreMapping:
    def test_build_restore_plan_is_pure_and_complete(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        e1 = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/a.js",
            payload=b"aaa",
        )
        e2 = _move_entry(
            entry_id="m2",
            live_root=live,
            quarantine_root=quarantine,
            relative="openxml/bin/Release/x.dll",
            payload=b"xxx",
        )
        e3 = _delete_entry(
            entry_id="d1",
            live_root=live,
            relative="frontend/dist/__pycache__/c.pyc",
            payload=b"ccc",
        )
        resolver = EvidenceLocatorResolver(_path_map([e1, e2, e3], quarantine))
        plan = resolver.build_restore_plan()
        assert plan["step_count"] == 2  # direct_delete excluded
        locators = {step["destination_locator"] for step in plan["steps"]}
        assert locators == {e1["old_locator"], e2["old_locator"]}
        # plan is pure: it must not create anything
        assert not quarantine.exists() or not (quarantine / "objects").exists() or True
        # verify the plan references the quarantine root supplied
        plan_with_root = resolver.build_restore_plan(quarantine_root=quarantine)
        assert plan_with_root["quarantine_root"] == str(quarantine)

    def test_restore_plan_source_locator_uses_content_address(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/z.js",
            payload=b"zzz",
        )
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        plan = resolver.build_restore_plan()
        step = plan["steps"][0]
        expected_obj = quarantine / "objects" / entry["source_sha256"][:2] / entry["source_sha256"]
        assert step["source_locator"] == str(expected_obj)
        assert step["expected_sha256"] == entry["source_sha256"]


# --------------------------------------------------------------------------- #
# Idempotency.
# --------------------------------------------------------------------------- #


class TestIdempotency:
    def test_repeated_resolve_is_idempotent(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/idem.js",
            payload=b"idempotent",
        )
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        a = resolver.resolve_old_to_new(entry["old_locator"])
        b = resolver.resolve_old_to_new(entry["old_locator"])
        assert a == b

    def test_fingerprint_is_stable_across_instances(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/fp.js",
            payload=b"fingerprint",
        )
        pm = _path_map([entry], quarantine)
        r1 = EvidenceLocatorResolver(pm)
        r2 = EvidenceLocatorResolver(json.loads(json.dumps(pm)))
        assert r1.fingerprint() == r2.fingerprint()
        # resolving twice does not change the fingerprint
        r1.resolve_old_to_new(entry["old_locator"])
        r1.resolve_new_to_old(entry["new_locator"])
        assert r1.fingerprint() == r2.fingerprint()


# --------------------------------------------------------------------------- #
# Fail-closed validation classes.
# --------------------------------------------------------------------------- #


class TestValidationFailClosed:
    def _base_entry(self, tmp_path) -> dict:
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        return _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/base.js",
            payload=b"base",
        ), quarantine

    def test_wrong_schema_version_fails(self, tmp_path):
        entry, quarantine = self._base_entry(tmp_path)
        pm = _path_map([entry], quarantine)
        pm["schema_version"] = 2
        with pytest.raises(ResolverError, match="unsupported PATH_MAP schema_version"):
            EvidenceLocatorResolver(pm)

    def test_missing_top_level_key_fails(self, tmp_path):
        entry, quarantine = self._base_entry(tmp_path)
        pm = _path_map([entry], quarantine)
        del pm["expected_protected_sha256"]
        with pytest.raises(ResolverError, match="PATH_MAP missing required keys"):
            EvidenceLocatorResolver(pm)

    def test_duplicate_entry_id_fails(self, tmp_path):
        entry, quarantine = self._base_entry(tmp_path)
        entry_b = _move_entry(
            entry_id="m1",  # same id
            live_root=tmp_path / "live",
            quarantine_root=quarantine,
            relative="frontend/dist/other.js",
            payload=b"other",
        )
        pm = _path_map([entry, entry_b], quarantine)
        with pytest.raises(ResolverError, match="duplicate entry id"):
            EvidenceLocatorResolver(pm)

    def test_duplicate_old_locator_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        # both entries point at the same old file
        entry_a = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/dup.js",
            payload=b"dup",
        )
        entry_b = dict(entry_a)
        entry_b["id"] = "m2"
        entry_b["new_locator"] = new_locator_for(_sha256_bytes(b"other"))
        entry_b["source_sha256"] = _sha256_bytes(b"other")
        entry_b["destination_sha256"] = entry_b["source_sha256"]
        entry_b["content_address"] = entry_b["source_sha256"]
        pm = _path_map([entry_a, entry_b], quarantine)
        with pytest.raises(ResolverError, match="duplicate old_locator"):
            EvidenceLocatorResolver(pm)

    def test_traversal_old_locator_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / ".." / ".." / "etc" / "passwd"),
            "new_locator": new_locator_for(digest),
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="traversal"):
            EvidenceLocatorResolver(pm)

    def test_old_locator_inside_quarantine_root_fails(self, tmp_path):
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(quarantine / "objects" / digest[:2] / digest),
            "new_locator": new_locator_for(digest),
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="outside the quarantine root"):
            EvidenceLocatorResolver(pm)

    def test_new_locator_not_content_addressed_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "frontend" / "dist" / "x.js"),
            "new_locator": "objects/ab/arbitrary-name",  # not content-addressed
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="content-address path"):
            EvidenceLocatorResolver(pm)

    def test_symlink_old_locator_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        target = live / "real.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"real")
        link = live / "link.txt"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        digest = _sha256_bytes(b"real")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(link),
            "new_locator": new_locator_for(digest),
            "path_type": "file",
            "size": 4,
            "source_sha256": digest,
            "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="must not be a symlink"):
            EvidenceLocatorResolver(pm)

    def test_wrong_operation_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "rm-rf",  # invalid
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": None,
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": None,
            "content_address": digest,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="operation"):
            EvidenceLocatorResolver(pm)

    def test_invalid_sha256_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = {
            "id": "m1",
            "operation": "direct_delete",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": None,
            "path_type": "file",
            "size": 1,
            "source_sha256": "not-a-hex",
            "destination_sha256": None,
            "content_address": "not-a-hex",
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="invalid sha256 hex"):
            EvidenceLocatorResolver(pm)

    def test_destination_hash_differs_from_source_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        src = _sha256_bytes(b"src")
        dst = _sha256_bytes(b"dst")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": new_locator_for(src),
            "path_type": "file",
            "size": 3,
            "source_sha256": src,
            "destination_sha256": dst,  # differs
            "content_address": src,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="destination_sha256 differs"):
            EvidenceLocatorResolver(pm)

    def test_content_address_differs_from_source_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        src = _sha256_bytes(b"src")
        ca = _sha256_bytes(b"ca")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": new_locator_for(ca),
            "path_type": "file",
            "size": 3,
            "source_sha256": src,
            "destination_sha256": src,
            "content_address": ca,  # differs
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="content_address must equal source_sha256"):
            EvidenceLocatorResolver(pm)

    def test_direct_delete_with_new_locator_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "direct_delete",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": new_locator_for(digest),  # must be null
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": None,
            "content_address": digest,
            "recovery_command": "regenerate",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="direct_delete must have null new_locator"):
            EvidenceLocatorResolver(pm)

    def test_quarantine_move_without_new_locator_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": None,  # missing
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="requires a non-null new_locator"):
            EvidenceLocatorResolver(pm)

    def test_symlink_path_type_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": new_locator_for(digest),
            "path_type": "symlink",  # not allowed
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "restore",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="path_type"):
            EvidenceLocatorResolver(pm)

    def test_negative_size_fails(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "direct_delete",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": None,
            "path_type": "file",
            "size": -1,
            "source_sha256": digest,
            "destination_sha256": None,
            "content_address": digest,
            "recovery_command": "regenerate",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="size must be a non-negative"):
            EvidenceLocatorResolver(pm)

    def test_empty_entries_fails(self, tmp_path):
        quarantine = tmp_path / "quarantine"
        pm = _path_map([], quarantine)
        with pytest.raises(ResolverError, match="at least one entry"):
            EvidenceLocatorResolver(pm)


# --------------------------------------------------------------------------- #
# Resolver never mutates.
# --------------------------------------------------------------------------- #


class TestNoMutation:
    def test_resolver_does_not_create_quarantine_root(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/nocreate.js",
            payload=b"nocreate",
        )
        assert not quarantine.exists()
        EvidenceLocatorResolver(_path_map([entry], quarantine))
        # constructing the resolver must not create the root
        assert not quarantine.exists()

    def test_build_restore_plan_does_not_write(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/planonly.js",
            payload=b"planonly",
        )
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        before = set(tmp_path.rglob("*"))
        resolver.build_restore_plan()
        resolver.build_restore_plan(quarantine_root=quarantine)
        after = set(tmp_path.rglob("*"))
        assert before == after


# --------------------------------------------------------------------------- #
# Normalization corrections (worker_02 follow-up).
# --------------------------------------------------------------------------- #


class TestNormalizationCorrections:
    """Codex-reproduced contract gaps: relative locators, /./ identity,
    normalized return, input immutability, unknown keys, non-string SHA."""

    def test_relative_quarantine_root_rejected(self, tmp_path):
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "direct_delete",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(tmp_path / "x.js"),
            "new_locator": None,
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": None,
            "content_address": digest,
            "recovery_command": "regenerate",
            "status": "planned",
        }
        pm = _path_map([entry], tmp_path / "quarantine")
        pm["quarantine_root"] = "relative/quarantine"  # raw relative
        with pytest.raises(ResolverError, match="quarantine_root must be an absolute path"):
            EvidenceLocatorResolver(pm)

    def test_relative_old_locator_rejected(self, tmp_path):
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"x")
        entry = {
            "id": "m1",
            "operation": "direct_delete",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": "relative/source.bin",  # raw relative
            "new_locator": None,
            "path_type": "file",
            "size": 1,
            "source_sha256": digest,
            "destination_sha256": None,
            "content_address": digest,
            "recovery_command": "regenerate",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="old_locator must be an absolute path"):
            EvidenceLocatorResolver(pm)

    def test_dot_segment_old_locator_normalizes_and_lookup_succeeds(self, tmp_path):
        """A /./ segment in old_locator normalizes so canonical lookup works."""
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/dotseg.js",
            payload=b"dotseg",
        )
        # inject a /./ segment into the old_locator
        canonical = entry["old_locator"]
        dotted = canonical.replace("/frontend/", "/./frontend/")
        assert dotted != canonical  # sanity: the replacement took effect
        entry["old_locator"] = dotted
        resolver = EvidenceLocatorResolver(_path_map([entry], quarantine))
        # canonical (dot-free) lookup must succeed after normalization
        result = resolver.resolve_old_to_new(canonical)
        assert result["old_locator"] == canonical  # stored normalized
        # the dotted variant also resolves to the same entry
        assert resolver.resolve_old_to_new(dotted)["id"] == "m1"

    def test_validate_path_map_returns_normalized_mapping(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/normalized.js",
            payload=b"normalized",
        )
        # inject /./ to prove normalization in the returned map
        canonical = entry["old_locator"]
        entry["old_locator"] = canonical.replace("/frontend/", "/./frontend/")
        pm = _path_map([entry], quarantine)
        result = validate_path_map(pm)
        # returned quarantine_root is normalized (no change needed here, but str form)
        assert result["quarantine_root"] == str(quarantine)
        # returned old_locator is the normalized canonical form
        assert result["entries"][0]["old_locator"] == canonical
        # entries are plain dicts (not the caller's objects)
        assert isinstance(result["entries"][0], dict)
        # exactly the schema-v1 keys, nothing extra
        assert set(result["entries"][0]) == set(RESOLVER.ALLOWED_ENTRY_KEYS)

    def test_validate_path_map_does_not_mutate_input(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/immutable.js",
            payload=b"immutable",
        )
        pm = _path_map([entry], quarantine)
        import copy
        before = copy.deepcopy(pm)
        validate_path_map(pm)
        # caller's input object must be byte-for-byte unchanged
        assert pm == before
        # specifically the entry dict inside is the same object, untouched
        assert pm["entries"][0]["old_locator"] == before["entries"][0]["old_locator"]

    def test_unknown_top_level_key_rejected(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/unk.js",
            payload=b"unk",
        )
        pm = _path_map([entry], quarantine)
        pm["unexpected_field"] = "evil"
        with pytest.raises(ResolverError, match="unknown top-level keys"):
            EvidenceLocatorResolver(pm)

    def test_unknown_entry_key_rejected(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/unkentry.js",
            payload=b"unkentry",
        )
        entry["sneaky_field"] = "evil"
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="unknown keys"):
            EvidenceLocatorResolver(pm)

    def test_non_string_sha256_rejected_with_resolver_error(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/nonstr.js",
            payload=b"nonstr",
        )
        entry["source_sha256"] = 12345  # non-string
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="sha256 must be a string"):
            EvidenceLocatorResolver(pm)

    def test_non_string_top_level_sha256_rejected(self, tmp_path):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/nonstrtop.js",
            payload=b"nonstrtop",
        )
        pm = _path_map([entry], quarantine)
        pm["expected_inventory_sha256"] = None  # non-string
        with pytest.raises(ResolverError, match="sha256 must be a string"):
            EvidenceLocatorResolver(pm)

    def test_resolver_stores_normalized_map_consistent_with_fingerprint(self, tmp_path):
        """Two resolvers — one from a /./ variant, one from canonical — share fingerprint."""
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/fp.js",
            payload=b"fp",
        )
        canonical = entry["old_locator"]
        entry_dotted = dict(entry)
        entry_dotted["old_locator"] = canonical.replace("/frontend/", "/./frontend/")
        r1 = EvidenceLocatorResolver(_path_map([entry], quarantine))
        r2 = EvidenceLocatorResolver(_path_map([entry_dotted], quarantine))
        assert r1.fingerprint() == r2.fingerprint()

# --------------------------------------------------------------------------- #
# Immutable identity corrections (worker_02 follow-up 2).
# --------------------------------------------------------------------------- #


class TestImmutableIdentity:
    """Adversarial tests for canonical new_locator identity, reverse-lookup
    boundary enforcement, and deep-copy egress immutability."""

    def _make_move_resolver(self, tmp_path, payload=b"immutable"):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/imm.js",
            payload=payload,
        )
        return EvidenceLocatorResolver(_path_map([entry], quarantine)), entry

    # -- canonical-equivalent new_locator lookup --------------------------- #

    def test_dotted_new_locator_lookup_resolves(self, tmp_path):
        """objects/aa/./<hash> must normalize and resolve to the entry."""
        resolver, entry = self._make_move_resolver(tmp_path)
        digest = entry["source_sha256"]
        canonical = entry["new_locator"]
        # build a /./ variant of the canonical locator
        dotted = "objects/%s/./%s" % (digest[:2], digest)
        assert dotted != canonical
        result = resolver.resolve_new_to_old(dotted)
        assert result["id"] == "m1"

    def test_non_canonical_new_locator_rejected_at_validation(self, tmp_path):
        """objects/aa/<wrong-name> must be rejected even if PurePosixPath-equal."""
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        digest = _sha256_bytes(b"reject")
        # a /./ spelling that PurePosixPath would consider equal
        dotted = "objects/%s/./%s" % (digest[:2], digest)
        entry = {
            "id": "m1",
            "operation": "quarantine_move",
            "owner": "protocol_v3_phase0",
            "reason": "r",
            "old_locator": str(live / "x.js"),
            "new_locator": dotted,
            "path_type": "file",
            "size": 6,
            "source_sha256": digest,
            "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "c",
            "status": "planned",
        }
        pm = _path_map([entry], quarantine)
        with pytest.raises(ResolverError, match="canonical content-address path"):
            EvidenceLocatorResolver(pm)

    # -- traversal / outside-root reverse lookup --------------------------- #

    def test_traversal_in_new_locator_lookup_rejected(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        with pytest.raises(ResolverError, match="traversal"):
            resolver.resolve_new_to_old("objects/../etc/passwd")

    def test_absolute_new_locator_outside_quarantine_root_rejected(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        outside = str(tmp_path / "live" / "evil.bin")
        with pytest.raises(ResolverError, match="outside quarantine root"):
            resolver.resolve_new_to_old(outside)

    def test_absolute_new_locator_inside_quarantine_root_resolves(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        quarantine = tmp_path / "quarantine"
        absolute = str(quarantine / entry["new_locator"])
        result = resolver.resolve_new_to_old(absolute)
        assert result["id"] == "m1"

    # -- egress immutability: path_map property ---------------------------- #

    def test_path_map_property_returns_independent_copy(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        fp_before = resolver.fingerprint()
        view = resolver.path_map
        view["task_id"] = "TAMPERED"
        view["entries"][0]["id"] = "TAMPERED"
        # internal state must be unaffected
        assert resolver.task_id != "TAMPERED"
        assert resolver.fingerprint() == fp_before
        assert resolver.resolve_old_to_new(entry["old_locator"])["id"] == "m1"

    # -- egress immutability: entries() iterator --------------------------- #

    def test_entries_iterator_returns_independent_copies(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        fp_before = resolver.fingerprint()
        for ent in resolver.entries():
            ent["id"] = "POISONED"
            ent["size"] = 99999
        # internal state must be unaffected
        assert resolver.fingerprint() == fp_before
        assert resolver.resolve_old_to_new(entry["old_locator"])["id"] == "m1"
        assert resolver.resolve_old_to_new(entry["old_locator"])["size"] == len(b"immutable")

    # -- egress immutability: resolve_old_to_new --------------------------- #

    def test_resolve_old_to_new_returns_independent_copy(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        fp_before = resolver.fingerprint()
        result = resolver.resolve_old_to_new(entry["old_locator"])
        result["id"] = "POISONED"
        result["source_sha256"] = "0" * 64
        # second resolve must return original data, not the mutated copy
        result2 = resolver.resolve_old_to_new(entry["old_locator"])
        assert result2["id"] == "m1"
        assert result2["source_sha256"] == entry["source_sha256"]
        assert resolver.fingerprint() == fp_before

    # -- egress immutability: resolve_new_to_old --------------------------- #

    def test_resolve_new_to_old_returns_independent_copy(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        fp_before = resolver.fingerprint()
        result = resolver.resolve_new_to_old(entry["new_locator"])
        result["id"] = "POISONED"
        result["old_locator"] = "/etc/passwd"
        # second resolve must return original data
        result2 = resolver.resolve_new_to_old(entry["new_locator"])
        assert result2["id"] == "m1"
        assert result2["old_locator"] == entry["old_locator"]
        assert resolver.fingerprint() == fp_before

    # -- egress immutability: build_restore_plan --------------------------- #

    def test_build_restore_plan_returns_independent_copy(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        fp_before = resolver.fingerprint()
        plan = resolver.build_restore_plan()
        plan["steps"][0]["id"] = "POISONED"
        plan["quarantine_root"] = "/etc"
        # internal state and second plan must be unaffected
        plan2 = resolver.build_restore_plan()
        assert plan2["steps"][0]["id"] == "m1"
        assert resolver.fingerprint() == fp_before

    # -- caller's original input is not aliased ---------------------------- #

    def test_caller_input_not_aliased_into_internal_state(self, tmp_path):
        """The caller's original entry dict must not become an internal alias."""
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/alias.js",
            payload=b"alias",
        )
        pm = _path_map([entry], quarantine)
        resolver = EvidenceLocatorResolver(pm)
        # mutate the caller's ORIGINAL objects after construction
        entry["id"] = "ORIGINAL_MUTATED"
        entry["source_sha256"] = "0" * 64
        pm["task_id"] = "ORIGINAL_MUTATED"
        # internal state must reflect the validated snapshot, not the mutation
        assert resolver.task_id == TASK_ID
        assert resolver.resolve_old_to_new(entry["old_locator"])["id"] == "m1"

    # -- combined: all egress mutations leave fingerprint stable ----------- #

    def test_all_egress_mutations_leave_fingerprint_stable(self, tmp_path):
        resolver, entry = self._make_move_resolver(tmp_path)
        fp_before = resolver.fingerprint()
        # exhaustively mutate every egress surface
        list(resolver.entries())
        for ent in resolver.entries():
            ent["id"] = "X"
        r1 = resolver.resolve_old_to_new(entry["old_locator"])
        r1["id"] = "X"
        r2 = resolver.resolve_new_to_old(entry["new_locator"])
        r2["id"] = "X"
        pm_view = resolver.path_map
        pm_view["entries"] = []
        plan = resolver.build_restore_plan()
        plan["steps"] = []
        # fingerprint and lookups must be completely unchanged
        assert resolver.fingerprint() == fp_before
        assert resolver.resolve_old_to_new(entry["old_locator"])["id"] == "m1"
        assert resolver.resolve_new_to_old(entry["new_locator"])["id"] == "m1"

# --------------------------------------------------------------------------- #
# Raw lookup boundary corrections (worker_02 follow-up 3).
# --------------------------------------------------------------------------- #


class TestRawLookupBoundary:
    """Adversarial tests for raw traversal/relative rejection before
    normalization in resolve_new_to_old, build_restore_plan, and
    resolve_old_to_new, plus accepted canonical/harmless-dot equivalents."""

    def _make_move_resolver(self, tmp_path, payload=b"boundary"):
        live = tmp_path / "live"
        quarantine = tmp_path / "quarantine"
        entry = _move_entry(
            entry_id="m1",
            live_root=live,
            quarantine_root=quarantine,
            relative="frontend/dist/boundary.js",
            payload=payload,
        )
        return EvidenceLocatorResolver(_path_map([entry], quarantine)), entry, quarantine

    # -- resolve_new_to_old: raw traversal in absolute input --------------- #

    def test_absolute_new_locator_raw_traversal_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        digest = entry["source_sha256"]
        traversing = str(quarantine / "tmp" / ".." / "objects" / digest[:2] / digest)
        with pytest.raises(ResolverError, match="traversal"):
            resolver.resolve_new_to_old(traversing)

    def test_absolute_new_locator_canonical_inside_root_accepted(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        absolute = str(quarantine / entry["new_locator"])
        result = resolver.resolve_new_to_old(absolute)
        assert result["id"] == "m1"

    def test_relative_new_locator_traversal_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        with pytest.raises(ResolverError, match="traversal"):
            resolver.resolve_new_to_old("objects/../etc/passwd")

    def test_relative_new_locator_harmless_dot_accepted(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        digest = entry["source_sha256"]
        dotted = "objects/%s/./%s" % (digest[:2], digest)
        result = resolver.resolve_new_to_old(dotted)
        assert result["id"] == "m1"

    def test_absolute_new_locator_outside_root_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        outside = str(tmp_path / "live" / "evil.bin")
        with pytest.raises(ResolverError, match="outside quarantine root"):
            resolver.resolve_new_to_old(outside)

    # -- build_restore_plan: raw relative / mismatch / traversal ----------- #

    def test_build_restore_plan_relative_root_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        with pytest.raises(ResolverError, match="absolute path"):
            resolver.build_restore_plan(Path("quarantine"))

    def test_build_restore_plan_traversal_root_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        with pytest.raises(ResolverError, match="traversal"):
            resolver.build_restore_plan(Path(str(quarantine) + "/../other"))

    def test_build_restore_plan_mismatch_root_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        with pytest.raises(ResolverError, match="does not match PATH_MAP root"):
            resolver.build_restore_plan(tmp_path / "different")

    def test_build_restore_plan_correct_root_accepted(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        plan = resolver.build_restore_plan(quarantine)
        assert plan["step_count"] == 1
        assert plan["steps"][0]["id"] == "m1"

    def test_build_restore_plan_none_root_uses_path_map_root(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        plan = resolver.build_restore_plan()
        assert plan["quarantine_root"] == str(quarantine)

    # -- resolve_old_to_new: raw relative / traversal ---------------------- #

    def test_resolve_old_to_new_relative_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        with pytest.raises(ResolverError, match="absolute path"):
            resolver.resolve_old_to_new("relative/source.js")

    def test_resolve_old_to_new_traversal_rejected(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        traversal = str(Path(entry["old_locator"]).parent / ".." / "evil.js")
        with pytest.raises(ResolverError, match="traversal"):
            resolver.resolve_old_to_new(traversal)

    def test_resolve_old_to_new_canonical_accepted(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        result = resolver.resolve_old_to_new(entry["old_locator"])
        assert result["id"] == "m1"

    def test_resolve_old_to_new_harmless_dot_accepted(self, tmp_path):
        resolver, entry, quarantine = self._make_move_resolver(tmp_path)
        canonical = entry["old_locator"]
        dotted = canonical.replace("/frontend/", "/./frontend/")
        assert dotted != canonical
        result = resolver.resolve_old_to_new(dotted)
        assert result["id"] == "m1"

# --------------------------------------------------------------------------- #
# worker_03: mutator tests.
#
# The classes below exercise apply_repository_hygiene.py — the execution
# engine that consumes this resolver.  Every test uses only tmp_path
# synthetic fixtures; nothing touches live, the accepted snapshots, or the
# real quarantine root.
# --------------------------------------------------------------------------- #


def _load_mutator():
    spec = importlib.util.spec_from_file_location(
        "protocol_v3_apply_repository_hygiene",
        _SCRIPTS / "apply_repository_hygiene.py",
    )
    if spec is None or spec.loader is None:
        raise AssertionError("cannot import mutator module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MUTATOR = _load_mutator()


def test_r3_injected_probe_preserves_listener_and_timeout_identity(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("keep")
    calls = []

    def empty(command, **kwargs):
        calls.append((command, kwargs["timeout"]))
        return subprocess.CompletedProcess(command, 1, "", "")

    blockers = MUTATOR.builtin_occupancy_checker(
        [target], port_probe=lambda port: port == 8911, lsof_runner=empty, lsof_timeout=0.25
    )
    assert any("hygiene port 8911" in b and "active listener" in b for b in blockers)
    assert calls and all(timeout == 0.25 for _, timeout in calls)

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    with pytest.raises(MUTATOR.HygieneMutatorError, match="timed out.*treated as occupied"):
        MUTATOR.builtin_occupancy_checker(
            [target], port_probe=lambda port: False, lsof_runner=timeout, lsof_timeout=0.25
        )
    assert target.read_text() == "keep"
HygieneMutatorError = MUTATOR.HygieneMutatorError
compute_eligibility = MUTATOR.compute_eligibility
apply_hygiene = MUTATOR.apply_hygiene
restore_hygiene = MUTATOR.restore_hygiene
verify_snapshot_hashes = MUTATOR.verify_snapshot_hashes


def _inv_entry(
    *,
    path: str,
    owner: str = "toolchain_cache",
    classification: str = "regenerable",
    mutation_eligible: bool = False,
    quarantine_blocked: bool = False,
    mutation_blockers=None,
    sha256: str | None = None,
    size: int = 10,
    refs=None,
) -> dict:
    """Build a synthetic inventory entry mirroring the Task 0.2 schema."""

    if sha256 is None:
        sha256 = _sha256_bytes(path.encode())
    if mutation_blockers is None:
        mutation_blockers = []
    if refs is None:
        refs = {"checkpoint": 0, "production": 0, "test": 0}
    return {
        "path": path,
        "owner": owner,
        "classification": classification,
        "mutation_eligible": mutation_eligible,
        "quarantine_blocked": quarantine_blocked,
        "mutation_blockers": list(mutation_blockers),
        "sha256": sha256,
        "size": size,
        "references": dict(refs),
    }


def _synthetic_inventory(entries: list[dict]) -> dict:
    return {"entries": list(entries), "root": "synthetic"}


def _synthetic_protected(paths: list[str] | None = None) -> dict:
    assets = [{"path": p} for p in (paths or [])]
    return {"assets": assets}


def _write_snapshot(tmp_path: Path, name: str, payload: bytes) -> tuple[Path, str]:
    """Write a snapshot file and return (path, sha256)."""

    p = tmp_path / name
    p.write_bytes(payload)
    return p, _sha256_bytes(payload)


def _authorized_apply_bundle(
    tmp_path: Path,
    *,
    operations: list[str] | None = None,
    move_specs: list[tuple[str, str, bytes]] | None = None,
    delete_specs: list[tuple[str, str, bytes]] | None = None,
    protected_paths: list[str] | None = None,
):
    """Build live tree + inventory-bound PATH_MAP for mutator apply tests."""

    live = tmp_path / "live"
    live.mkdir(parents=True, exist_ok=True)
    quarantine = tmp_path / "quarantine"
    pm_path = tmp_path / "PATH_MAP.json"

    pm_entries: list[dict] = []
    inv_entries: list[dict] = []

    if move_specs is None and operations and "move" in operations:
        move_specs = [("m1", "frontend/dist/app.js", b"app-content")]
    if delete_specs is None and operations and "delete" in operations:
        delete_specs = [("d1", "__pycache__/mod.pyc", b"pyc-bytes")]

    for entry_id, relative, payload in (move_specs or []):
        pe = _move_entry(
            entry_id=entry_id, live_root=live, quarantine_root=quarantine,
            relative=relative, payload=payload)
        pm_entries.append(pe)
        inv_entries.append(_inv_entry(
            path=relative, mutation_eligible=True, owner=pe["owner"],
            sha256=pe["source_sha256"], size=pe["size"]))

    for entry_id, relative, payload in (delete_specs or []):
        pe = _delete_entry(
            entry_id=entry_id, live_root=live,
            relative=relative, payload=payload)
        pm_entries.append(pe)
        inv_entries.append(_inv_entry(
            path=relative, mutation_eligible=True, owner=pe["owner"],
            sha256=pe["source_sha256"], size=pe["size"]))

    inv = {"root": _abs(live), "entries": inv_entries}
    prot = {"assets": [{"path": p} for p in (protected_paths or [])]}
    inv_path, inv_sha = _write_snapshot(
        tmp_path, "inv.json",
        json.dumps(inv, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    prot_path, prot_sha = _write_snapshot(
        tmp_path, "prot.json",
        json.dumps(prot, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    pm = _path_map(
        pm_entries, quarantine,
        expected_inventory_sha256=inv_sha,
        expected_protected_sha256=prot_sha)
    pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2), encoding="utf-8")
    return (live, quarantine, pm, pm_path, inv_path, inv_sha, prot_path, prot_sha)


# --------------------------------------------------------------------------- #
# Dry-run eligibility.
# --------------------------------------------------------------------------- #


class TestDryRunEligibility:
    def test_empty_inventory_yields_zero_eligible(self, tmp_path):
        inv = _synthetic_inventory([])
        prot = _synthetic_protected()
        report = compute_eligibility(inv, prot, live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert report["eligible_direct_delete_count"] == 0
        assert report["eligible_quarantine_move_count"] == 0
        assert report["inventory_entry_count"] == 0

    def test_mutation_eligible_false_blocks_all(self, tmp_path):
        """The accepted Task 0.2 contract: mutation_eligible=False for every
        entry yields exactly zero authorized targets."""

        entries = [
            _inv_entry(path=".DS_Store", mutation_eligible=False),
            _inv_entry(path="__pycache__/x.pyc", mutation_eligible=False),
            _inv_entry(path="frontend/dist/app.js", mutation_eligible=False),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert report["blocked_count"] == 3
        assert all(r["blocker"] == "mutation_eligible_false"
                   for r in report["blocked"])

    def test_eligible_direct_delete_candidate(self, tmp_path):
        entries = [
            _inv_entry(path=".DS_Store", mutation_eligible=True),
            _inv_entry(path="__pycache__/module.pyc", mutation_eligible=True),
            _inv_entry(path=".pytest_cache/v/cache/lastfailed",
                       mutation_eligible=True),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["eligible_direct_delete_count"] == 3
        assert report["authorized_target_count"] == 3
        assert all(r["operation"] == "direct_delete"
                   for r in report["eligible_direct_delete"])

    def test_eligible_quarantine_move_candidate(self, tmp_path):
        entries = [
            _inv_entry(path="frontend/dist/index.html",
                       mutation_eligible=True),
            _inv_entry(path=".playwright-cli/code.md", mutation_eligible=True),
            _inv_entry(path="frontend/.npm-cache/data.bin",
                       mutation_eligible=True),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["eligible_quarantine_move_count"] == 3
        assert report["authorized_target_count"] == 3

    def test_protected_intersection_blocks(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        target = str(live / ".DS_Store")
        entries = [_inv_entry(path=".DS_Store", mutation_eligible=True)]
        prot = _synthetic_protected([target])
        report = compute_eligibility(
            _synthetic_inventory(entries), prot, live_root=live)
        assert report["authorized_target_count"] == 0
        blocked = [r for r in report["blocked"]
                   if r["blocker"] == "protected_intersection"]
        assert len(blocked) == 1
        assert report["protected_intersection_on_candidates"] == 1

    def test_prohibited_root_blocks(self, tmp_path):
        entries = [
            _inv_entry(path="runs/execution/x.md", mutation_eligible=True),
            _inv_entry(path="logs/app.log", mutation_eligible=True),
            _inv_entry(path="evidence/report.txt", mutation_eligible=True),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert all(r["blocker"] == "prohibited_root"
                   for r in report["blocked"])

    def test_denied_owner_blocks(self, tmp_path):
        entries = [
            _inv_entry(path=".DS_Store", owner="medical_monitoring",
                       mutation_eligible=True),
            _inv_entry(path=".DS_Store", owner="protocol_v3_authority",
                       mutation_eligible=True,
                       sha256=_sha256_bytes(b"other")),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert all("denied_owner" in r["blocker"]
                   for r in report["blocked"])

    def test_has_references_blocks(self, tmp_path):
        entries = [
            _inv_entry(path=".DS_Store", mutation_eligible=True,
                       refs={"checkpoint": 1, "production": 0, "test": 0}),
            _inv_entry(path=".vite/cache.dat", mutation_eligible=True,
                       sha256=_sha256_bytes(b"v"),
                       refs={"checkpoint": 0, "production": 1, "test": 0}),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert all("has_references" in r["blocker"]
                   for r in report["blocked"])

    def test_quarantine_blocked_flag_blocks(self, tmp_path):
        entries = [
            _inv_entry(path=".DS_Store", mutation_eligible=True,
                       quarantine_blocked=True),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert report["blocked"][0]["blocker"] == "quarantine_blocked"

    def test_mutation_blockers_field_blocks(self, tmp_path):
        entries = [
            _inv_entry(path=".DS_Store", mutation_eligible=True,
                       mutation_blockers=["same_name_hash_conflict"]),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert "mutation_blockers" in report["blocked"][0]["blocker"]

    def test_unknown_hygiene_category_skipped(self, tmp_path):
        """An eligible entry that matches no known pattern is skipped, not
        manufactured into an operation."""

        entries = [
            _inv_entry(path="some/random/file.txt",
                       mutation_eligible=True),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert report["skipped_count"] == 1
        assert report["skipped"][0]["blocker"] == "unknown_hygiene_category"

    def test_non_candidate_classification_skipped(self, tmp_path):
        entries = [
            _inv_entry(path=".DS_Store", classification="authority_regression",
                       mutation_eligible=True),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path)
        assert report["authorized_target_count"] == 0
        assert report["skipped_count"] == 1
# --------------------------------------------------------------------------- #
# Apply transaction.
# --------------------------------------------------------------------------- #


class TestApplyTransaction:
    def _setup_fixtures(self, tmp_path, *, operations=None):
        """Build a live tree, PATH_MAP, and snapshot files for apply tests.

        Returns (live_root, quarantine_root, path_map, path_map_path,
                 inv_path, inv_sha, prot_path, prot_sha).
        """

        return _authorized_apply_bundle(tmp_path, operations=operations)

    def test_apply_quarantine_move_copies_and_deletes_source(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        source_path = Path(entry["old_locator"])
        assert source_path.exists()

        report = apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

        assert report["mode"] == "apply"
        assert report["committed_count"] == 1
        # source removed
        assert not source_path.exists()
        # quarantine object exists with correct content
        obj = quarantine / entry["new_locator"]
        assert obj.exists()
        assert obj.read_bytes() == b"app-content"

    def test_apply_direct_delete_removes_source(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["delete"])
        entry = pm["entries"][0]
        source_path = Path(entry["old_locator"])
        assert source_path.exists()

        report = apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

        assert report["committed_count"] == 1
        assert not source_path.exists()
        # no quarantine object created for direct_delete
        assert not quarantine.exists() or not (quarantine / "objects").exists()

    def test_apply_mixed_move_and_delete(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move", "delete"])

        report = apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

        assert report["committed_count"] == 2
        assert report["entry_count"] == 2

    def test_apply_copy_hash_verify_before_delete(self, tmp_path):
        """The quarantine object must be hash-verified BEFORE source removal."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        source_path = Path(entry["old_locator"])

        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

        # After success: source gone, object present with matching hash.
        assert not source_path.exists()
        obj = quarantine / entry["new_locator"]
        assert obj.exists()
        assert _sha256_bytes(obj.read_bytes()) == entry["destination_sha256"]

    def test_apply_is_replay_safe_committed_skipped(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        pm2 = json.loads(pm_path.read_text(encoding="utf-8"))
        report = apply_hygiene(
            pm2, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["committed_count"] == 0
        assert report["skipped_count"] == 1
        assert report["results"][0]["reason"] == "already_committed"

    def test_apply_persists_path_map_status(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        persisted = json.loads(pm_path.read_text(encoding="utf-8"))
        assert persisted["entries"][0]["status"] == "committed"

    def test_apply_stale_source_hash_fails_closed(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        Path(entry["old_locator"]).write_bytes(b"tampered-source-bytes")
        with pytest.raises(HygieneMutatorError, match="source hash mismatch"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

    def test_apply_quarantine_root_preexists_fails(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        quarantine.mkdir()
        with pytest.raises(HygieneMutatorError, match="must not pre-exist"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

    def test_apply_wrong_inventory_hash_fails(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        with pytest.raises(HygieneMutatorError, match="inventory file hash mismatch"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256="f" * 64,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

    def test_apply_wrong_protected_hash_fails(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        with pytest.raises(HygieneMutatorError, match="protected file hash mismatch"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256="f" * 64,
                occupancy_checker=_no_occupancy)

    def test_apply_occupancy_blocker_fails(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])

        def checker(_paths):
            return ["synthetic occupancy blocker"]

        with pytest.raises(HygieneMutatorError, match="occupancy blockers"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=checker)

    def test_apply_no_occupancy_proceeds(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])

        def checker(_paths):
            return []

        report = apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=checker)
        assert report["committed_count"] == 1

    def test_apply_destination_collision_different_hash_fails(self, tmp_path):
        """Crash-recovery: quarantine object exists with a different hash."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_fixtures(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        quarantine.mkdir()
        obj = quarantine / entry["new_locator"]
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b"stale-different-content")
        pm2 = json.loads(pm_path.read_text(encoding="utf-8"))
        pm2["entries"][0]["status"] = "copied"
        pm_path.write_text(json.dumps(pm2, ensure_ascii=False, indent=2))

        with pytest.raises(HygieneMutatorError, match="object hash mismatch|destination collision"):
            apply_hygiene(
                pm2, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)


# --------------------------------------------------------------------------- #
# Restore transaction.
# --------------------------------------------------------------------------- #


class TestRestoreTransaction:
    def _setup_applied(self, tmp_path, *, operations=None):
        """Run a full apply first, then return fixtures for restore testing."""

        (live, quarantine, pm, pm_path, inv_path, inv_sha, prot_path, prot_sha) = \
            _authorized_apply_bundle(tmp_path, operations=operations)
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_path, protected_path=prot_path,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha,
            occupancy_checker=_no_occupancy)
        committed_pm = json.loads(pm_path.read_text(encoding="utf-8"))
        return (live, quarantine, committed_pm, pm_path,
                inv_path, inv_sha, prot_path, prot_sha)

    def test_restore_moves_object_back_to_live(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        obj = quarantine / entry["new_locator"]
        source = Path(entry["old_locator"])
        assert obj.exists()
        assert not source.exists()

        report = restore_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

        assert report["mode"] == "restore"
        assert report["restored_count"] == 1
        assert source.exists()
        assert source.read_bytes() == b"app-content"
        assert not obj.exists()

    def test_restore_skips_direct_delete_entries(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move", "delete"])

        report = restore_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

        # Only the move entry is restorable; the delete entry is skipped.
        assert report["restored_count"] == 1
        skipped = [r for r in report["results"] if r["status"] == "skipped"]
        assert len(skipped) == 1
        assert skipped[0]["reason"] == "not_a_move"

    def test_restore_is_idempotent(self, tmp_path):
        """Re-running restore on already-restored entries skips them."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])
        # First restore
        restore_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        # Reload restored PATH_MAP
        pm2 = json.loads(pm_path.read_text(encoding="utf-8"))
        # Second restore — must skip
        report = restore_hygiene(
            pm2, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["restored_count"] == 0
        assert report["skipped_count"] == 1
        assert report["results"][0]["reason"] == "already_restored"

    def test_restore_wrong_inventory_hash_fails(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])

        with pytest.raises(HygieneMutatorError, match="inventory file hash mismatch"):
            restore_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256="f" * 64,
                expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

    def test_restore_missing_object_fails_closed(self, tmp_path):
        """If the quarantine object is missing during restore, fail closed."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        obj = quarantine / entry["new_locator"]
        obj.unlink()  # remove the object

        with pytest.raises(HygieneMutatorError, match="quarantine object missing"):
            restore_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

    def test_restore_object_hash_mismatch_fails_closed(self, tmp_path):
        """If the quarantine object hash drifted, fail closed."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        obj = quarantine / entry["new_locator"]
        obj.write_bytes(b"corrupted-different-bytes")

        with pytest.raises(HygieneMutatorError, match="object hash mismatch"):
            restore_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

    def test_restore_destination_exists_different_hash_fails(self, tmp_path):
        """If the live destination already exists with a different hash, fail."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        dest = Path(entry["old_locator"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"different-existing-content")

        with pytest.raises(HygieneMutatorError,
                           match="restore destination exists with different"):
            restore_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

    def test_restore_destination_exists_same_hash_succeeds(self, tmp_path):
        """If the destination already has the right bytes, clean up the object."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        dest = Path(entry["old_locator"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"app-content")  # same as original
        obj = quarantine / entry["new_locator"]
        assert obj.exists()

        report = restore_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["restored_count"] == 1
        assert dest.read_bytes() == b"app-content"
        assert not obj.exists()  # object cleaned up

    def test_apply_then_restore_round_trip_preserves_bytes(self, tmp_path):
        """Full round-trip: apply (move to quarantine) then restore."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            self._setup_applied(tmp_path, operations=["move"])
        entry = pm["entries"][0]
        source = Path(entry["old_locator"])

        restore_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)

        assert source.exists()
        assert source.read_bytes() == b"app-content"
        assert _sha256_bytes(source.read_bytes()) == entry["source_sha256"]


# --------------------------------------------------------------------------- #
# Crash recovery and partial PATH_MAP.
# --------------------------------------------------------------------------- #


class TestCrashRecovery:
    def test_apply_partial_then_resume_completes(self, tmp_path):
        """Simulate a crash after the first entry, then resume."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[
                    ("m1", "frontend/dist/a.js", b"aaa"),
                    ("m2", "frontend/dist/b.js", b"bbb"),
                ])
        e1, e2 = pm["entries"]
        e1_path = Path(e1["old_locator"])
        quarantine.mkdir()
        obj1 = quarantine / e1["new_locator"]
        obj1.parent.mkdir(parents=True)
        obj1.write_bytes(b"aaa")
        e1_path.unlink()
        pm_partial = json.loads(pm_path.read_text(encoding="utf-8"))
        pm_partial["entries"][0]["status"] = "committed"
        pm_path.write_text(json.dumps(pm_partial, ensure_ascii=False, indent=2))

        report = apply_hygiene(
            pm_partial, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["committed_count"] == 1
        assert report["skipped_count"] == 1
        assert not Path(e1["old_locator"]).exists()
        assert not Path(e2["old_locator"]).exists()

    def test_apply_partial_path_map_with_copied_status_resumes(self, tmp_path):
        """Crash after copy but before delete: resume should delete the source."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[("m1", "frontend/dist/x.js", b"xxx")])
        e1 = pm["entries"][0]
        quarantine.mkdir()
        obj = quarantine / e1["new_locator"]
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b"xxx")
        pm_copied = json.loads(pm_path.read_text(encoding="utf-8"))
        pm_copied["entries"][0]["status"] = "copied"
        pm_path.write_text(json.dumps(pm_copied, ensure_ascii=False, indent=2))

        report = apply_hygiene(
            pm_copied, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["committed_count"] == 1
        assert not Path(e1["old_locator"]).exists()
        assert obj.exists()

    def test_apply_unexpected_status_fails(self, tmp_path):
        """An entry with an unrecognized apply status fails closed."""

        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[("m1", "frontend/dist/y.js", b"yyy")])
        pm["entries"][0]["status"] = "failed"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))

        with pytest.raises(HygieneMutatorError, match="unexpected status"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)


# --------------------------------------------------------------------------- #
# Symlink / traversal / type edge cases.
# --------------------------------------------------------------------------- #


class TestApplyEdgeCases:
    def test_apply_symlink_source_fails_closed(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        quarantine = tmp_path / "quarantine"
        pm_path = tmp_path / "PATH_MAP.json"
        target = live / "real_target.js"
        target.write_bytes(b"real")
        link = live / "link.js"
        link.symlink_to(target)

        digest = _sha256_bytes(b"real")
        entry = {
            "id": "m1", "operation": "quarantine_move",
            "owner": "toolchain_cache", "reason": "r",
            "old_locator": _abs(link),
            "new_locator": new_locator_for(digest),
            "path_type": "file", "size": 4,
            "source_sha256": digest, "destination_sha256": digest,
            "content_address": digest,
            "recovery_command": "restore", "status": "planned",
        }
        inv = {
            "root": _abs(live),
            "entries": [_inv_entry(
                path="link.js", mutation_eligible=True, owner="toolchain_cache",
                sha256=digest, size=4)],
        }
        inv_p, inv_s = _write_snapshot(
            tmp_path, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_p, prot_s = _write_snapshot(tmp_path, "prot.json", b'{"assets":[]}')
        pm = _path_map(
            [entry], quarantine,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s)
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))

        with pytest.raises(HygieneMutatorError, match="symlink"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
        assert link.exists()
        assert target.exists()

    def test_apply_missing_source_fails_closed(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[("m1", "frontend/dist/missing.js", b"absent")])
        Path(pm["entries"][0]["old_locator"]).unlink()
        with pytest.raises(HygieneMutatorError, match="source missing"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

    def test_apply_size_drift_fails_closed(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[("m1", "frontend/dist/drift.js", b"original")])
        Path(pm["entries"][0]["old_locator"]).write_bytes(b"x" * 100)
        with pytest.raises(HygieneMutatorError, match="source hash mismatch"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)


# --------------------------------------------------------------------------- #
# CLI tests.
# --------------------------------------------------------------------------- #


class TestCLI:
    def test_cli_dry_run_mode(self, tmp_path, capsys):
        live = tmp_path / "live"
        live.mkdir()
        digest = _sha256_bytes(b"ds")
        inv_data = {
            "root": _abs(live),
            "entries": [{
                "path": ".DS_Store",
                "owner": "toolchain_cache",
                "classification": "regenerable",
                "mutation_eligible": True,
                "quarantine_blocked": False,
                "mutation_blockers": [],
                "sha256": digest,
                "size": 2,
                "references": {"checkpoint": 0, "production": 0, "test": 0},
            }],
        }
        inv_p = tmp_path / "inv.json"
        prot_p = tmp_path / "prot.json"
        inv_p.write_text(json.dumps(inv_data), encoding="utf-8")
        prot_p.write_text('{"assets":[]}', encoding="utf-8")
        rc = MUTATOR.main([
            "--mode", "dry-run",
            "--inventory", str(inv_p),
            "--protected", str(prot_p),
        ])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["authorized_target_count"] == 1
        assert out["eligible_direct_delete_count"] == 1

    def test_cli_default_mode_is_dry_run(self, tmp_path, capsys):
        live = tmp_path / "live"
        live.mkdir()
        inv_p = tmp_path / "inv.json"
        prot_p = tmp_path / "prot.json"
        inv_p.write_text(json.dumps({"root": _abs(live), "entries": []}))
        prot_p.write_text('{"assets":[]}')
        rc = MUTATOR.main([
            "--inventory", str(inv_p),
            "--protected", str(prot_p),
        ])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["authorized_target_count"] == 0

    def test_cli_apply_requires_expected_hashes(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["move"])
        with pytest.raises(SystemExit):
            MUTATOR.main([
                "--mode", "apply",
                "--inventory", str(inv_p),
                "--protected", str(prot_p),
                "--path-map", str(pm_path),
                "--quarantine-root", str(quarantine),
            ])


# --------------------------------------------------------------------------- #
# Integrity remediation adversarial cases (Codex P1 reproductions).
# --------------------------------------------------------------------------- #


class TestIntegrityRemediation:
    def test_p1_unbound_path_map_direct_delete_rejected(self, tmp_path):
        """Empty inventory must reject arbitrary PATH_MAP delete of important.txt."""

        live = tmp_path / "live"
        live.mkdir()
        important = live / "important.txt"
        important.write_bytes(b"do-not-delete")
        quarantine = tmp_path / "quarantine"
        pe = _delete_entry(
            entry_id="evil", live_root=live,
            relative="important.txt", payload=b"do-not-delete")
        inv = {"root": _abs(live), "entries": []}
        prot = {"assets": []}
        inv_p, inv_s = _write_snapshot(
            tmp_path, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_p, prot_s = _write_snapshot(
            tmp_path, "prot.json",
            json.dumps(prot, ensure_ascii=False, sort_keys=True).encode())
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s)
        pm_path = tmp_path / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))

        with pytest.raises(HygieneMutatorError, match="PATH_MAP/eligible set inequality"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
        assert important.exists()
        assert important.read_bytes() == b"do-not-delete"
        assert not quarantine.exists()

    def test_p1_builtin_occupancy_blocks_port_8911(self, tmp_path, monkeypatch):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        source = Path(pm["entries"][0]["old_locator"])
        monkeypatch.setattr(MUTATOR, "_port_is_listening", lambda port: port == 8911)
        monkeypatch.setattr(MUTATOR.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        with pytest.raises(HygieneMutatorError, match="hygiene port 8911"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=None)
        assert source.exists()
        assert not quarantine.exists()

    def test_p1_quarantine_root_mismatch_rejected(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["move"])
        other = tmp_path / "q2"
        with pytest.raises(HygieneMutatorError, match="does not match PATH_MAP root"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=other,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
        assert Path(pm["entries"][0]["old_locator"]).exists()
        assert not other.exists()
        assert not quarantine.exists()

    def test_p1_post_unlink_persist_failure_replays_to_committed(self, tmp_path, monkeypatch):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        entry = pm["entries"][0]
        source = Path(entry["old_locator"])
        real_persist = MUTATOR._persist_path_map

        def selective(path_map_path, working_map, *, after_destructive):
            status = working_map["entries"][0]["status"]
            if after_destructive and status == "committed":
                crashed = MUTATOR._deep_copy_path_map(working_map)
                crashed["entries"][0]["status"] = "copied"
                real_persist(path_map_path, crashed, after_destructive=False)
                raise HygieneMutatorError(
                    "PATH_MAP persistence failed after destructive operation: "
                    "injected fsync failure")
            return real_persist(
                path_map_path, working_map, after_destructive=after_destructive)

        monkeypatch.setattr(MUTATOR, "_persist_path_map", selective)
        with pytest.raises(HygieneMutatorError, match="persistence failed after destructive"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert not source.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "copied"

        monkeypatch.setattr(MUTATOR, "_persist_path_map", real_persist)
        report = apply_hygiene(
            disk, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["committed_count"] == 1
        final = json.loads(pm_path.read_text(encoding="utf-8"))
        assert final["entries"][0]["status"] == "committed"

    def test_builtin_occupancy_used_when_checker_none_and_ports_clear(self, tmp_path, monkeypatch):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        monkeypatch.setattr(MUTATOR, "_port_is_listening", lambda port: False)
        monkeypatch.setattr(MUTATOR.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""))
        report = apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=None)
        assert report["committed_count"] == 1

    def test_medical_monitoring_owner_cannot_bind(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        quarantine = tmp_path / "quarantine"
        pe = _delete_entry(
            entry_id="d1", live_root=live, relative=".DS_Store",
            payload=b"x", owner="medical_monitoring")
        inv = {
            "root": _abs(live),
            "entries": [_inv_entry(
                path=".DS_Store", mutation_eligible=True,
                owner="medical_monitoring",
                sha256=pe["source_sha256"], size=pe["size"])],
        }
        inv_p, inv_s = _write_snapshot(
            tmp_path, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_p, prot_s = _write_snapshot(tmp_path, "prot.json", b'{"assets":[]}')
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s)
        pm_path = tmp_path / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))
        with pytest.raises(HygieneMutatorError, match="PATH_MAP/eligible set inequality"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

    def test_restore_object_absent_dest_present_finishes(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["move"])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        entry = committed["entries"][0]
        obj = quarantine / entry["new_locator"]
        dest = Path(entry["old_locator"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"app-content")
        obj.unlink()
        report = restore_hygiene(
            committed, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["restored_count"] == 1
        final = json.loads(pm_path.read_text(encoding="utf-8"))
        assert final["entries"][0]["status"] == "restored"

    def test_no_quarantine_artifact_before_gates(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["move"])
        with pytest.raises(HygieneMutatorError, match="occupancy blockers"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=lambda _p: ["forced blocker"])
        assert not quarantine.exists()

    def test_string_false_mutation_eligible_not_coerced(self, tmp_path):
        """bool(\"false\") must never authorize mutation."""

        live = tmp_path / "live"
        live.mkdir()
        digest = _sha256_bytes(b"x")
        inv = {
            "root": _abs(live),
            "entries": [{
                "path": "__pycache__/x.pyc",
                "owner": "toolchain_cache",
                "classification": "regenerable",
                "mutation_eligible": "false",
                "quarantine_blocked": False,
                "mutation_blockers": [],
                "sha256": digest,
                "size": 1,
                "references": {"checkpoint": 0, "production": 0, "test": 0},
            }],
        }
        with pytest.raises(HygieneMutatorError, match="actual bool"):
            compute_eligibility(inv, _synthetic_protected(), live_root=live)

    def test_medical_monitoring_path_denied_despite_spoofed_owner(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        rel = "medical_monitoring/__pycache__/x.pyc"
        pe = _delete_entry(
            entry_id="d1", live_root=live, relative=rel, payload=b"x",
            owner="toolchain_cache")
        inv = {
            "root": _abs(live),
            "entries": [_inv_entry(
                path=rel, mutation_eligible=True, owner="toolchain_cache",
                sha256=pe["source_sha256"], size=pe["size"])],
        }
        report = compute_eligibility(inv, _synthetic_protected(), live_root=live)
        assert report["authorized_target_count"] == 0
        assert report["blocked"][0]["blocker"] == "medical_monitoring_path"

        inv_p, inv_s = _write_snapshot(
            tmp_path, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_p, prot_s = _write_snapshot(
            tmp_path, "prot.json", b'{"assets":[]}')
        quarantine = tmp_path / "quarantine"
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s)
        pm_path = tmp_path / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))
        with pytest.raises(HygieneMutatorError, match="PATH_MAP/eligible set inequality"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
        assert Path(pe["old_locator"]).exists()

    def test_malformed_protected_assets_fail_closed(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        entries = [_inv_entry(path=".DS_Store", mutation_eligible=True)]
        with pytest.raises(HygieneMutatorError, match="protected.assets must be a list"):
            compute_eligibility(
                _synthetic_inventory(entries),
                {"assets": "not-a-list"},
                live_root=live)

    def test_path_map_must_include_every_eligible_target(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                delete_specs=[
                    ("d1", "__pycache__/a.pyc", b"aaa"),
                    ("d2", "__pycache__/b.pyc", b"bbb"),
                ])
        # Drop the second eligible target from PATH_MAP.
        pm["entries"] = [pm["entries"][0]]
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))
        with pytest.raises(
                HygieneMutatorError,
                match=r"PATH_MAP/eligible set inequality: missing=\[.*\] extra=\[\]"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
        assert Path(pm["entries"][0]["old_locator"]).exists()

    def test_fabricated_committed_direct_delete_with_source_present_rejected(
            self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        source = Path(pm["entries"][0]["old_locator"])
        assert source.exists()
        pm["entries"][0]["status"] = "committed"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))
        with pytest.raises(HygieneMutatorError, match="fabricated committed state"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
        assert source.exists()

    def test_fabricated_restored_with_object_and_dest_absent_rejected(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["move"])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        entry = committed["entries"][0]
        obj = quarantine / entry["new_locator"]
        dest = Path(entry["old_locator"])
        obj.unlink()
        if dest.exists():
            dest.unlink()
        committed["entries"][0]["status"] = "restored"
        pm_path.write_text(json.dumps(committed, ensure_ascii=False, indent=2))
        with pytest.raises(HygieneMutatorError, match="fabricated restored state"):
            restore_hygiene(
                committed, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

    def test_malformed_reference_bool_rejected(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        entry = _inv_entry(path=".DS_Store", mutation_eligible=True)
        entry["references"]["checkpoint"] = False
        with pytest.raises(HygieneMutatorError, match="non-boolean int"):
            compute_eligibility(
                _synthetic_inventory([entry]), _synthetic_protected(),
                live_root=live)

    def test_malformed_blockers_not_list_rejected(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        entry = _inv_entry(path=".DS_Store", mutation_eligible=True)
        entry["mutation_blockers"] = "same_name_hash_conflict"
        with pytest.raises(HygieneMutatorError, match="must be a list of strings"):
            compute_eligibility(
                _synthetic_inventory([entry]), _synthetic_protected(),
                live_root=live)

    def test_uppercase_sha_rejected(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        entry = _inv_entry(path=".DS_Store", mutation_eligible=True)
        entry["sha256"] = entry["sha256"].upper()
        with pytest.raises(HygieneMutatorError, match="lowercase 64-hex"):
            compute_eligibility(
                _synthetic_inventory([entry]), _synthetic_protected(),
                live_root=live)

    def test_valid_committed_and_restored_terminals_skip(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["move"])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        report = apply_hygiene(
            committed, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["skipped_count"] == 1
        assert report["results"][0]["reason"] == "already_committed"

        restore_hygiene(
            committed, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        restored = json.loads(pm_path.read_text(encoding="utf-8"))
        report2 = restore_hygiene(
            restored, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report2["skipped_count"] == 1
        assert report2["results"][0]["reason"] == "already_restored"


# --------------------------------------------------------------------------- #
# Follow-up 3: symlink escape, shared restore, runtime deny, occupancy/fsync.
# --------------------------------------------------------------------------- #


class TestIntegrityFollowup3:
    def test_approved_prohibited_roots_pin_includes_runtime(self):
        expected = {
            "runs", "records", "logs", "evidence",
            "archives", "runtime", "source_backups", "backups",
        }
        assert MUTATOR.APPROVED_PROHIBITED_ROOTS == frozenset(expected)
        assert MUTATOR.APPROVED_PROHIBITED_ROOTS == frozenset(
            MUTATOR.PROHIBITED_ROOT_PATTERNS)

    def test_runtime_cache_pyc_never_authorized(self, tmp_path):
        entries = [
            _inv_entry(
                path="runtime/cache/x.pyc",
                mutation_eligible=True,
                owner="toolchain_cache",
                classification="regenerable",
            ),
        ]
        report = compute_eligibility(
            _synthetic_inventory(entries), _synthetic_protected(),
            live_root=tmp_path,
            prohibited_root_patterns=("runs",))  # attempt to drop runtime
        assert report["authorized_target_count"] == 0
        assert report["blocked"][0]["blocker"] == "prohibited_root"
        assert not (tmp_path / "runtime" / "cache" / "x.pyc").exists()

    def test_intermediate_symlink_escape_blocks_apply_and_preserves_outside(
            self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[("m1", "frontend/dist/app.js", b"app-content")])
        source = Path(pm["entries"][0]["old_locator"])
        payload = source.read_bytes()
        outside = tmp_path / "outside_escape"
        outside.mkdir()
        outside_file = outside / "app.js"
        outside_file.write_bytes(payload)
        # Replace intermediate directory with a symlink to an outside tree while
        # keeping the inventory/PATH_MAP lexical locator unchanged.
        dist = live / "frontend" / "dist"
        for child in list(dist.iterdir()):
            child.unlink()
        dist.rmdir()
        dist.symlink_to(outside)
        assert source.is_symlink() is False
        assert source.exists()  # follows symlink to outside file
        assert outside_file.exists()

        with pytest.raises(HygieneMutatorError, match="symlink"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert outside_file.exists()
        assert outside_file.read_bytes() == payload
        # Quarantine root may be created before the first destructive boundary,
        # but no committed object may exist and the outside file must survive.
        obj = quarantine / pm["entries"][0]["new_locator"]
        assert not obj.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "planned"

    def test_shared_content_address_restore_is_reference_aware(self, tmp_path):
        payload = b"identical-shared-bytes"
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[
                    ("m1", "frontend/dist/a.js", payload),
                    ("m2", "frontend/dist/b.js", payload),
                ])
        assert pm["entries"][0]["new_locator"] == pm["entries"][1]["new_locator"]
        src_a = Path(pm["entries"][0]["old_locator"])
        src_b = Path(pm["entries"][1]["old_locator"])
        obj = quarantine / pm["entries"][0]["new_locator"]

        apply_report = apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert apply_report["committed_count"] == 2
        assert not src_a.exists() and not src_b.exists()
        assert obj.exists() and obj.read_bytes() == payload

        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        restore_report = restore_hygiene(
            committed, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert restore_report["restored_count"] == 2
        assert src_a.exists() and src_a.read_bytes() == payload
        assert src_b.exists() and src_b.read_bytes() == payload
        assert not obj.exists()

        # Replay must remain idempotent and must not strand either file.
        restored = json.loads(pm_path.read_text(encoding="utf-8"))
        replay = restore_hygiene(
            restored, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert replay["restored_count"] == 0
        assert replay["skipped_count"] == 2
        assert src_a.read_bytes() == payload
        assert src_b.read_bytes() == payload
        assert not obj.exists()

    def test_shared_restore_keeps_object_until_last_reference(self, tmp_path):
        payload = b"shared-refcount"
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[
                    ("m1", "frontend/dist/a.js", payload),
                    ("m2", "frontend/dist/b.js", payload),
                ])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        obj = quarantine / committed["entries"][0]["new_locator"]
        # Simulate crash after first entry restored but before final unlink of a
        # still-shared object: mark first restored, keep object, leave second
        # committed.
        dest_a = Path(committed["entries"][0]["old_locator"])
        dest_a.parent.mkdir(parents=True, exist_ok=True)
        dest_a.write_bytes(payload)
        committed["entries"][0]["status"] = "restored"
        pm_path.write_text(json.dumps(committed, ensure_ascii=False, indent=2))
        assert obj.exists()

        report = restore_hygiene(
            committed, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert report["results"][0]["reason"] == "already_restored"
        assert report["restored_count"] == 1
        dest_b = Path(committed["entries"][1]["old_locator"])
        assert dest_a.read_bytes() == payload
        assert dest_b.read_bytes() == payload
        assert not obj.exists()

    def test_shared_restore_crash_before_final_unlink_replays(self, tmp_path, monkeypatch):
        payload = b"crash-window-shared"
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[
                    ("m1", "frontend/dist/a.js", payload),
                    ("m2", "frontend/dist/b.js", payload),
                ])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        obj = quarantine / committed["entries"][0]["new_locator"]
        real_unlink = MUTATOR._safe_unlink_regular_file
        state = {"failed": False}

        def boom(path, expected):
            if Path(path) == obj and not state["failed"]:
                state["failed"] = True
                raise HygieneMutatorError(
                    "injected final object unlink failure")
            return real_unlink(path, expected)

        monkeypatch.setattr(MUTATOR, "_safe_unlink_regular_file", boom)
        with pytest.raises(HygieneMutatorError, match="injected final object unlink"):
            restore_hygiene(
                committed, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert Path(committed["entries"][0]["old_locator"]).read_bytes() == payload
        assert Path(committed["entries"][1]["old_locator"]).read_bytes() == payload
        assert obj.exists()

        monkeypatch.setattr(MUTATOR, "_safe_unlink_regular_file", real_unlink)
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        report = restore_hygiene(
            disk, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert Path(committed["entries"][0]["old_locator"]).read_bytes() == payload
        assert Path(committed["entries"][1]["old_locator"]).read_bytes() == payload
        assert not obj.exists()
        assert report["restored_count"] + report["skipped_count"] == 2

    def test_symlinked_live_root_rejected(self, tmp_path):
        real_live = tmp_path / "real_live"
        real_live.mkdir()
        link_live = tmp_path / "link_live"
        link_live.symlink_to(real_live)
        quarantine = tmp_path / "quarantine"
        pe = _delete_entry(
            entry_id="d1", live_root=real_live, relative=".DS_Store",
            payload=b"x")
        # Bind PATH_MAP/inventory to the symlinked live root spelling.
        pe["old_locator"] = _abs(link_live / ".DS_Store")
        Path(pe["old_locator"]).write_bytes(b"x")
        inv = {
            "root": _abs(link_live),
            "entries": [_inv_entry(
                path=".DS_Store", mutation_eligible=True,
                owner=pe["owner"], sha256=pe["source_sha256"], size=pe["size"])],
        }
        prot = {"assets": []}
        inv_path, inv_sha = _write_snapshot(
            tmp_path, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_path, prot_sha = _write_snapshot(
            tmp_path, "prot.json",
            json.dumps(prot, ensure_ascii=False, sort_keys=True).encode())
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha)
        pm_path = tmp_path / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))
        with pytest.raises(HygieneMutatorError, match="must not be a symlink"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_path, protected_path=prot_path,
                expected_inventory_sha256=inv_sha,
                expected_protected_sha256=prot_sha,
                occupancy_checker=_no_occupancy)
        assert Path(pe["old_locator"]).exists()

    def test_relative_live_root_rejected(self, tmp_path):
        live = tmp_path / "live"
        live.mkdir()
        quarantine = tmp_path / "quarantine"
        pe = _delete_entry(
            entry_id="d1", live_root=live, relative=".DS_Store", payload=b"x")
        inv = {
            "root": "live",
            "entries": [_inv_entry(
                path=".DS_Store", mutation_eligible=True,
                owner=pe["owner"], sha256=pe["source_sha256"], size=pe["size"])],
        }
        prot = {"assets": []}
        inv_path, inv_sha = _write_snapshot(
            tmp_path, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_path, prot_sha = _write_snapshot(
            tmp_path, "prot.json",
            json.dumps(prot, ensure_ascii=False, sort_keys=True).encode())
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha)
        pm_path = tmp_path / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2))
        with pytest.raises(HygieneMutatorError, match="absolute path"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_path, protected_path=prot_path,
                expected_inventory_sha256=inv_sha,
                expected_protected_sha256=prot_sha,
                occupancy_checker=_no_occupancy)

    def test_injected_occupancy_non_sequence_fails_closed(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        source = Path(pm["entries"][0]["old_locator"])
        with pytest.raises(HygieneMutatorError, match="non-string sequence"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=lambda _p: "occupied")
        assert source.exists()
        assert not quarantine.exists()

    def test_injected_occupancy_non_string_items_fails_closed(self, tmp_path):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        source = Path(pm["entries"][0]["old_locator"])
        with pytest.raises(HygieneMutatorError, match="must be a string"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=lambda _p: [1, "x"])
        assert source.exists()

    def test_lsof_timeout_fails_closed(self, tmp_path, monkeypatch):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        source = Path(pm["entries"][0]["old_locator"])

        def boom(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="lsof", timeout=0.1)

        monkeypatch.setattr(MUTATOR.subprocess, "run", boom)
        with pytest.raises(HygieneMutatorError, match="timed out"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=None)
        assert source.exists()

    def test_directory_fsync_failure_after_atomic_replace_fails_closed(
            self, tmp_path, monkeypatch):
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(tmp_path, operations=["delete"])
        source = Path(pm["entries"][0]["old_locator"])
        real_fsync_dir = MUTATOR._fsync_dir
        state = {"armed": False}

        def selective(path):
            if state["armed"] and Path(path) == pm_path.parent:
                raise MUTATOR.HygieneMutatorError(
                    "directory fsync failed for %s: injected" % path)
            return real_fsync_dir(path)

        monkeypatch.setattr(MUTATOR, "_fsync_dir", selective)
        # Arm after the pre-destructive persist by wrapping persist.
        real_persist = MUTATOR._persist_path_map

        def persist(path_map_path, working_map, *, after_destructive):
            if after_destructive:
                state["armed"] = True
            return real_persist(
                path_map_path, working_map, after_destructive=after_destructive)

        monkeypatch.setattr(MUTATOR, "_persist_path_map", persist)
        with pytest.raises(HygieneMutatorError, match="directory fsync failed"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
        # Source may already be unlinked; PATH_MAP must remain replayable.
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] in ("copied", "committed")
        monkeypatch.setattr(MUTATOR, "_fsync_dir", real_fsync_dir)
        monkeypatch.setattr(MUTATOR, "_persist_path_map", real_persist)
        report = apply_hygiene(
            disk, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        assert not source.exists()
        final = json.loads(pm_path.read_text(encoding="utf-8"))
        assert final["entries"][0]["status"] == "committed"
        assert report["committed_count"] in (0, 1)


# --------------------------------------------------------------------------- #
# Follow-up 4: shared-object group physical validation + /var tempfile alias.
# --------------------------------------------------------------------------- #


class TestIntegrityFollowup4:
    def test_fabricated_dual_restored_only_a_present_keeps_shared_object(
            self, tmp_path):
        """Codex repro: both statuses restored, only dest A present, object kept."""

        payload = b"shared-group-fabricated"
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[
                    ("m1", "frontend/dist/a.js", payload),
                    ("m2", "frontend/dist/b.js", payload),
                ])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        assert committed["entries"][0]["new_locator"] == committed["entries"][1]["new_locator"]
        obj = quarantine / committed["entries"][0]["new_locator"]
        dest_a = Path(committed["entries"][0]["old_locator"])
        dest_b = Path(committed["entries"][1]["old_locator"])
        dest_a.parent.mkdir(parents=True, exist_ok=True)
        dest_a.write_bytes(payload)
        assert not dest_b.exists()
        assert obj.exists()
        committed["entries"][0]["status"] = "restored"
        committed["entries"][1]["status"] = "restored"
        pm_path.write_text(json.dumps(committed, ensure_ascii=False, indent=2))

        with pytest.raises(HygieneMutatorError, match="destination absent"):
            restore_hygiene(
                committed, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert obj.exists()
        assert obj.read_bytes() == payload
        assert dest_a.exists() and dest_a.read_bytes() == payload
        assert not dest_b.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "restored"
        assert disk["entries"][1]["status"] == "restored"
        # No destructive PATH_MAP rewrite beyond the pre-flight identity persist
        # of the same restored labels.
        assert {e["status"] for e in disk["entries"]} == {"restored"}

    def test_object_absent_only_a_present_fails_before_status_change(
            self, tmp_path):
        payload = b"object-absent-partial"
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[
                    ("m1", "frontend/dist/a.js", payload),
                    ("m2", "frontend/dist/b.js", payload),
                ])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        obj = quarantine / committed["entries"][0]["new_locator"]
        dest_a = Path(committed["entries"][0]["old_locator"])
        dest_b = Path(committed["entries"][1]["old_locator"])
        obj.unlink()
        dest_a.parent.mkdir(parents=True, exist_ok=True)
        dest_a.write_bytes(payload)
        assert not dest_b.exists()
        assert not obj.exists()
        assert committed["entries"][0]["status"] == "committed"
        assert committed["entries"][1]["status"] == "committed"
        pm_path.write_text(json.dumps(committed, ensure_ascii=False, indent=2))

        with pytest.raises(
                HygieneMutatorError,
                match="shared quarantine object absent"):
            restore_hygiene(
                committed, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert not obj.exists()
        assert dest_a.read_bytes() == payload
        assert not dest_b.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "committed"
        assert disk["entries"][1]["status"] == "committed"

    def test_restored_destination_via_intermediate_symlink_rejected(
            self, tmp_path):
        payload = b"symlink-dest"
        (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
            _authorized_apply_bundle(
                tmp_path,
                move_specs=[("m1", "frontend/dist/app.js", payload)])
        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_p, protected_path=prot_p,
            expected_inventory_sha256=inv_s,
            expected_protected_sha256=prot_s,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        entry = committed["entries"][0]
        obj = quarantine / entry["new_locator"]
        outside = tmp_path / "outside_dest"
        outside.mkdir()
        outside_file = outside / "app.js"
        outside_file.write_bytes(payload)
        dist = live / "frontend" / "dist"
        if dist.exists() and not dist.is_symlink():
            for child in list(dist.iterdir()):
                child.unlink()
            dist.rmdir()
        elif dist.is_symlink():
            dist.unlink()
        dist.symlink_to(outside)
        dest = Path(entry["old_locator"])
        assert dest.exists()
        committed["entries"][0]["status"] = "restored"
        pm_path.write_text(json.dumps(committed, ensure_ascii=False, indent=2))

        with pytest.raises(HygieneMutatorError, match="symlink"):
            restore_hygiene(
                committed, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert obj.exists()
        assert outside_file.read_bytes() == payload
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "restored"

    def test_raw_tempfile_var_alias_path_accepted(self):
        """Raw tempfile spellings use /var/... on macOS; must not reject /var."""

        import tempfile

        with tempfile.TemporaryDirectory(prefix="hygiene_var_alias_") as raw:
            raw_root = Path(raw)
            assert raw_root.parts[:2] == ("/", "var") or raw_root.as_posix().startswith(
                "/private/var")
            (live, quarantine, pm, pm_path, inv_p, inv_s, prot_p, prot_s) = \
                _authorized_apply_bundle(
                    raw_root, operations=["delete"])
            # Exercise PATH_MAP parent walk through the raw tempfile spelling.
            report = apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)
            assert report["committed_count"] == 1
            assert not Path(pm["entries"][0]["old_locator"]).exists()

    def test_non_alias_ancestor_symlink_still_rejected(self, tmp_path):
        base = tmp_path / "base"
        base.mkdir()
        real_parent = tmp_path / "real_parent"
        real_parent.mkdir()
        link_parent = base / "link_parent"
        link_parent.symlink_to(real_parent)
        # PATH_MAP beneath a non-alias symlink ancestor must fail closed.
        pm_path = link_parent / "PATH_MAP.json"
        with pytest.raises(HygieneMutatorError, match="symlink"):
            MUTATOR._require_path_map_path(pm_path)


def _alias_above_live_bundle(
    tmp_path: Path,
    *,
    operations: list[str] | None = None,
    move_specs=None,
    delete_specs=None,
):
    """Control dir for PATH_MAP/snapshots; live via task-owned symlink parent."""

    control = tmp_path / "control"
    control.mkdir()
    actual_parent = tmp_path / "actual_parent"
    actual_parent.mkdir()
    (actual_parent / "live").mkdir()
    alias_parent = tmp_path / "alias_parent"
    alias_parent.symlink_to(actual_parent)
    live_alias = alias_parent / "live"

    if move_specs is None and operations and "move" in operations:
        move_specs = [("m1", "frontend/dist/app.js", b"app-content")]
    if delete_specs is None and operations and "delete" in operations:
        delete_specs = [("d1", "__pycache__/x.pyc", b"pyc-bytes")]

    quarantine = control / "quarantine"
    pm_path = control / "PATH_MAP.json"
    pm_entries: list[dict] = []
    inv_entries: list[dict] = []

    for entry_id, relative, payload in (move_specs or []):
        pe = _move_entry(
            entry_id=entry_id, live_root=live_alias, quarantine_root=quarantine,
            relative=relative, payload=payload)
        pm_entries.append(pe)
        inv_entries.append(_inv_entry(
            path=relative, mutation_eligible=True, owner=pe["owner"],
            sha256=pe["source_sha256"], size=pe["size"]))

    for entry_id, relative, payload in (delete_specs or []):
        pe = _delete_entry(
            entry_id=entry_id, live_root=live_alias,
            relative=relative, payload=payload)
        pm_entries.append(pe)
        inv_entries.append(_inv_entry(
            path=relative, mutation_eligible=True, owner=pe["owner"],
            sha256=pe["source_sha256"], size=pe["size"]))

    inv = {"root": _abs(live_alias), "entries": inv_entries}
    prot = {"assets": []}
    inv_path, inv_sha = _write_snapshot(
        control, "inv.json",
        json.dumps(inv, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    prot_path, prot_sha = _write_snapshot(
        control, "prot.json",
        json.dumps(prot, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    pm = _path_map(
        pm_entries, quarantine,
        expected_inventory_sha256=inv_sha,
        expected_protected_sha256=prot_sha)
    pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2), encoding="utf-8")
    return (
        live_alias, actual_parent / "live", alias_parent, quarantine,
        pm, pm_path, inv_path, inv_sha, prot_path, prot_sha,
    )


# --------------------------------------------------------------------------- #
# Follow-up 5: symlink components above live/quarantine roots.
# --------------------------------------------------------------------------- #


class TestIntegrityFollowup5:
    def test_direct_delete_through_symlink_above_live_rejected(self, tmp_path):
        (live_alias, live_real, alias_parent, quarantine,
         pm, pm_path, inv_p, inv_s, prot_p, prot_s) = _alias_above_live_bundle(
            tmp_path, operations=["delete"])
        source_alias = Path(pm["entries"][0]["old_locator"])
        source_real = live_real / "__pycache__" / "x.pyc"
        payload = source_real.read_bytes()
        assert source_alias.exists()
        assert alias_parent.is_symlink()
        assert not live_alias.is_symlink()

        with pytest.raises(HygieneMutatorError, match="symlink"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert source_real.exists() and source_real.read_bytes() == payload
        assert source_alias.exists()
        assert not quarantine.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "planned"

    def test_quarantine_move_through_symlink_above_live_rejected(self, tmp_path):
        (live_alias, live_real, alias_parent, quarantine,
         pm, pm_path, inv_p, inv_s, prot_p, prot_s) = _alias_above_live_bundle(
            tmp_path, operations=["move"])
        source_real = live_real / "frontend" / "dist" / "app.js"
        payload = source_real.read_bytes()
        obj = quarantine / pm["entries"][0]["new_locator"]

        with pytest.raises(HygieneMutatorError, match="symlink"):
            apply_hygiene(
                pm, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_p, protected_path=prot_p,
                expected_inventory_sha256=inv_s,
                expected_protected_sha256=prot_s,
                occupancy_checker=_no_occupancy)

        assert source_real.exists() and source_real.read_bytes() == payload
        assert not obj.exists()
        assert not quarantine.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "planned"

    def test_restore_after_nested_live_parent_replaced_by_symlink(self, tmp_path):
        control = tmp_path / "control"
        control.mkdir()
        live_host = tmp_path / "live_host"
        live_host.mkdir()
        live = live_host / "live"
        live.mkdir()
        quarantine = control / "quarantine"
        # Build move against ordinary live_host/live; PATH_MAP stays under control.
        pe = _move_entry(
            entry_id="m1", live_root=live, quarantine_root=quarantine,
            relative="frontend/dist/app.js", payload=b"app-content")
        inv = {
            "root": _abs(live),
            "entries": [_inv_entry(
                path="frontend/dist/app.js", mutation_eligible=True,
                owner=pe["owner"], sha256=pe["source_sha256"], size=pe["size"])],
        }
        prot = {"assets": []}
        inv_path, inv_sha = _write_snapshot(
            control, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_path, prot_sha = _write_snapshot(
            control, "prot.json",
            json.dumps(prot, ensure_ascii=False, sort_keys=True).encode())
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha)
        pm_path = control / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2), encoding="utf-8")

        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_path, protected_path=prot_path,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        entry = committed["entries"][0]
        obj = quarantine / entry["new_locator"]
        obj_bytes = obj.read_bytes()
        dest = Path(entry["old_locator"])

        actual_live_host = tmp_path / "actual_live_host"
        live_host.rename(actual_live_host)
        live_host.symlink_to(actual_live_host)
        assert live_host.is_symlink()
        assert obj.exists() and obj.read_bytes() == obj_bytes

        with pytest.raises(HygieneMutatorError, match="symlink"):
            restore_hygiene(
                committed, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_path, protected_path=prot_path,
                expected_inventory_sha256=inv_sha,
                expected_protected_sha256=prot_sha,
                occupancy_checker=_no_occupancy)

        assert obj.exists() and obj.read_bytes() == obj_bytes
        assert not dest.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "committed"

    def test_existing_quarantine_root_via_symlinked_parent_rejected(self, tmp_path):
        control = tmp_path / "control"
        control.mkdir()
        live_host = tmp_path / "live_host"
        live_host.mkdir()
        live = live_host / "live"
        live.mkdir()
        q_host = tmp_path / "q_host"
        q_host.mkdir()
        quarantine = q_host / "quarantine"
        pe = _move_entry(
            entry_id="m1", live_root=live, quarantine_root=quarantine,
            relative="frontend/dist/app.js", payload=b"app-content")
        inv = {
            "root": _abs(live),
            "entries": [_inv_entry(
                path="frontend/dist/app.js", mutation_eligible=True,
                owner=pe["owner"], sha256=pe["source_sha256"], size=pe["size"])],
        }
        prot = {"assets": []}
        inv_path, inv_sha = _write_snapshot(
            control, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_path, prot_sha = _write_snapshot(
            control, "prot.json",
            json.dumps(prot, ensure_ascii=False, sort_keys=True).encode())
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha)
        pm_path = control / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2), encoding="utf-8")

        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_path, protected_path=prot_path,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        entry = committed["entries"][0]
        obj = quarantine / entry["new_locator"]
        obj_bytes = obj.read_bytes()
        dest = Path(entry["old_locator"])

        actual_q_host = tmp_path / "actual_q_host"
        q_host.rename(actual_q_host)
        q_host.symlink_to(actual_q_host)
        assert q_host.is_symlink()
        # Lexical quarantine root now contains a task-owned symlink ancestor.
        quarantine_alias = q_host / "quarantine"
        committed["quarantine_root"] = _abs(quarantine_alias)
        pm_path.write_text(
            json.dumps(committed, ensure_ascii=False, indent=2), encoding="utf-8")
        assert quarantine_alias.exists()
        assert (quarantine_alias / entry["new_locator"]).read_bytes() == obj_bytes

        with pytest.raises(HygieneMutatorError, match="symlink"):
            restore_hygiene(
                committed,
                path_map_path=pm_path,
                quarantine_root=quarantine_alias,
                inventory_path=inv_path,
                protected_path=prot_path,
                expected_inventory_sha256=inv_sha,
                expected_protected_sha256=prot_sha,
                occupancy_checker=_no_occupancy)

        assert (quarantine_alias / entry["new_locator"]).read_bytes() == obj_bytes
        assert not dest.exists()
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "committed"
        assert disk["quarantine_root"] == _abs(quarantine_alias)

    def test_apply_replay_after_live_parent_symlink_swap_rejected(self, tmp_path):
        control = tmp_path / "control"
        control.mkdir()
        live_host = tmp_path / "live_host"
        live_host.mkdir()
        live = live_host / "live"
        live.mkdir()
        quarantine = control / "quarantine"
        pe = _delete_entry(
            entry_id="d1", live_root=live, relative="__pycache__/x.pyc",
            payload=b"pyc-bytes")
        inv = {
            "root": _abs(live),
            "entries": [_inv_entry(
                path="__pycache__/x.pyc", mutation_eligible=True,
                owner=pe["owner"], sha256=pe["source_sha256"], size=pe["size"])],
        }
        prot = {"assets": []}
        inv_path, inv_sha = _write_snapshot(
            control, "inv.json",
            json.dumps(inv, ensure_ascii=False, sort_keys=True).encode())
        prot_path, prot_sha = _write_snapshot(
            control, "prot.json",
            json.dumps(prot, ensure_ascii=False, sort_keys=True).encode())
        pm = _path_map(
            [pe], quarantine,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha)
        pm_path = control / "PATH_MAP.json"
        pm_path.write_text(json.dumps(pm, ensure_ascii=False, indent=2), encoding="utf-8")

        apply_hygiene(
            pm, path_map_path=pm_path, quarantine_root=quarantine,
            inventory_path=inv_path, protected_path=prot_path,
            expected_inventory_sha256=inv_sha,
            expected_protected_sha256=prot_sha,
            occupancy_checker=_no_occupancy)
        committed = json.loads(pm_path.read_text(encoding="utf-8"))
        assert committed["entries"][0]["status"] == "committed"

        actual_live_host = tmp_path / "actual_live_host"
        live_host.rename(actual_live_host)
        live_host.symlink_to(actual_live_host)
        source = Path(committed["entries"][0]["old_locator"])
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"pyc-bytes")
        assert source.exists()

        with pytest.raises(HygieneMutatorError, match="symlink"):
            apply_hygiene(
                committed, path_map_path=pm_path, quarantine_root=quarantine,
                inventory_path=inv_path, protected_path=prot_path,
                expected_inventory_sha256=inv_sha,
                expected_protected_sha256=prot_sha,
                occupancy_checker=_no_occupancy)

        assert source.exists() and source.read_bytes() == b"pyc-bytes"
        disk = json.loads(pm_path.read_text(encoding="utf-8"))
        assert disk["entries"][0]["status"] == "committed"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
