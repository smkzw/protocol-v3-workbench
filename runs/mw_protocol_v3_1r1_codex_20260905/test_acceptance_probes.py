"""Independent acceptance probes against the unchanged worker candidate."""
import hashlib
import runpy
import sqlite3
from pathlib import Path

import pytest

from app.protocol_workflow.storage.sqlite import (
    SqliteStorageError, build_unit_of_work_factory,
)

fixtures = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tests/protocol_v3/test_repository_backends.py"))


def test_product_route_rejects_volatile_sqlite_memory_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SqliteStorageError):
        build_unit_of_work_factory({"backend": "sqlite", "path": ":memory:"})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("version", [0, 1])
def test_foreign_version_table_is_rejected_without_mutation(tmp_path, version):
    path = tmp_path / "foreign.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE schema_version(version INTEGER, applied_at TEXT)")
        conn.execute("INSERT INTO schema_version VALUES (?, 'synthetic')", (version,))
        conn.execute("CREATE TABLE unrelated_legacy_notes(note TEXT)")
        conn.execute("INSERT INTO unrelated_legacy_notes VALUES ('retain me')")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    error = None
    try:
        build_unit_of_work_factory({"backend": "sqlite", "path": path})
    except SqliteStorageError as exc:
        error = exc
    assert error is not None, "foreign/unknown schema was accepted"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_unentered_scope_cannot_persist_a_rolled_back_mutation(tmp_path):
    factory = build_unit_of_work_factory({"backend": "sqlite", "path": tmp_path / "uow.sqlite"})
    uow = factory()
    try:
        try:
            uow.study_definition_cas_repository.save_with_expected_revision(
                fixtures["_PROJ_A"], fixtures["_study"](), 0,
            )
        except RuntimeError:
            pass  # Rejecting an unentered UoW is an acceptable fail-closed result.
    finally:
        uow.rollback()
    with factory() as check:
        assert check.study_definition_repository.get_current(
            fixtures["_PROJ_A"], "sd:test:1",
        ) is None, "mutation escaped transaction and survived rollback"


def test_sql_write_failure_caught_inside_uow_does_not_commit_half_batch(tmp_path):
    path = tmp_path / "batch.sqlite"
    factory = build_unit_of_work_factory({"backend": "sqlite", "path": path})
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER synthetic_second_row_failure BEFORE INSERT ON event_stream "
                     "WHEN NEW.sequence = 2 BEGIN SELECT RAISE(FAIL, 'synthetic write failure'); END")
    first = fixtures["_built_event"](event_id="evt:1", stream_id="stream:1", sequence=1, previous=None, payload={"n": 1})
    second = fixtures["_built_event"](event_id="evt:2", stream_id="stream:1", sequence=2, previous=first.event_sha256, payload={"n": 2})
    with factory() as uow:
        with pytest.raises(sqlite3.IntegrityError):
            uow.event_stream_repository.append_events(fixtures["_PROJ_A"], "stream:1", (first, second))
    with factory() as check:
        assert check.event_stream_repository.read_events(fixtures["_PROJ_A"], "stream:1") == (), "first event of failed batch committed"
