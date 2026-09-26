"""A19/A20 recoverable-starting-point fixture contract (0927V1 §7).

tests/fixtures/writing_reference_sources.py must build named starts through
REAL service chains only (document ingest → extraction → preparation batch →
translation batch with the deterministic offline pipeline → authoring journey
stage draft), record a full identity manifest, reload via SQLite file copy
with validation, detect schema drift by rebuilding (never silent), and make
direct-SQL approval forgery detectable — never commit it itself.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.acceptance import _gate_testkit as kit

MANIFEST_KEYS = (
    "format", "start_kind", "api_contract_version", "repo_schema_version",
    "builder_version", "source_sha256", "boundary_fakes", "state",
    "state_sha256",
)


def _builder():
    from tests.fixtures import writing_reference_sources as wrs
    return wrs


@pytest.fixture(scope="module")
def f1(tmp_path_factory):
    wrs = _builder()
    handle = wrs.build_start("F1", root=tmp_path_factory.mktemp("f1_start"))
    yield handle
    handle.cleanup()


def test_a19_f1_manifest_complete(f1):
    manifest = json.loads((f1.dir / "manifest.json").read_text(encoding="utf-8"))
    for key in MANIFEST_KEYS:
        assert key in manifest, key
    assert manifest["start_kind"] == "F1"
    assert manifest["format"] == "writing_reference_start/1"
    assert (f1.dir / "writing_reference.sqlite3").is_file()
    assert manifest["state"].get("batch_id"), manifest
    assert manifest["boundary_fakes"], "boundary fakes must be declared honestly"


def test_a20_f1_start_reloads_via_file_copy(f1, tmp_path):
    wrs = _builder()
    target = tmp_path / "reload"
    loaded = wrs.load_start_copy(f1.dir, target)
    assert (loaded.repo_path).is_file()
    wrs.verify_start(target)  # re-reads through product getters; must not raise


def test_a19_builder_uses_no_raw_sql():
    wrs = _builder()
    source = Path(wrs.__file__).read_text(encoding="utf-8")
    assert "import sqlite3" not in source, "builder must go through services/repository"
    assert "INSERT INTO" not in source
    assert "UPDATE " not in source
    assert "PRAGMA writable_schema" not in source


def test_a19_direct_sql_forgery_is_detected(f1, tmp_path):
    wrs = _builder()
    target = tmp_path / "forged"
    wrs.load_start_copy(f1.dir, target)
    # simulate the forbidden shortcut: raw SQL status rewrite on the copy
    connection = sqlite3.connect(str(target / "writing_reference.sqlite3"))
    current = connection.execute(
        "SELECT status FROM writing_reference_preparation_batches LIMIT 1"
    ).fetchone()[0]
    forged = "completed" if current != "completed" else "failed"
    connection.execute(
        "UPDATE writing_reference_preparation_batches SET status = ?", (forged,))
    connection.commit()
    connection.close()
    with pytest.raises(wrs.StartManifestMismatch):
        wrs.verify_start(target)


def test_a19_manifest_schema_drift_rebuild_not_silent(f1):
    wrs = _builder()
    manifest = json.loads((f1.dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["repo_schema_version"] == wrs.current_repo_schema_version()
    assert manifest["api_contract_version"] == wrs.current_api_contract_version()
    # a manifest from an incompatible schema must be rejected loudly on load
    stale = json.loads(json.dumps(manifest))
    stale["repo_schema_version"] = manifest["repo_schema_version"] + 1000
    stale_dir = f1.dir.parent / "stale_manifest"
    stale_dir.mkdir()
    for name in ("writing_reference.sqlite3",):
        (stale_dir / name).write_bytes((f1.dir / name).read_bytes())
    (stale_dir / "manifest.json").write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(wrs.StartManifestMismatch):
        wrs.load_start_copy(stale_dir, f1.dir.parent / "stale_load")
