"""Product SQLite storage adapter checks — Task 1R.1.

These tests pin the product-specific guarantees of
``app.protocol_workflow.storage.sqlite`` that the shared dual-backend
contract suite (``test_repository_backends.py``) cannot express:

* real durable file state — committed work survives a full close/reopen of
  the database through a fresh factory;
* durability pragmas (WAL journal mode, ``synchronous=FULL``,
  ``foreign_keys=ON``, validated ``busy_timeout``) enforced on every
  connection, with WAL persistent at file level;
* the SQLite >= 3.51.3 engine gate fails closed BEFORE any file/directory is
  created;
* invalid configuration fails closed before touching the filesystem;
* explicit schema-version table with ordered atomic migrations: repeated
  initialization is safe, a future/unknown schema version fails closed
  without rewriting contents, and an arbitrary foreign/legacy database is
  never adopted into the product schema;
* importing the adapter (and the selected-storage surface) has no side
  effects: no database, directory, worker or service is created;
* no PoC imports anywhere in the product adapter;
* the explicitly enabled product route on ``storage.selected`` works and its
  negative paths stay fail-closed.

Product DBs live only in test-owned tmp directories.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    ExecutionReservation,
    ReservationStatus,
    StudyDefinitionV3,
)
from app.protocol_workflow.events.models import EventEnvelopeBuilder
from app.protocol_workflow.ports.repositories import ChapterCoverageRecord

from app.protocol_workflow.ports.repositories import RevisionConflictError
from app.protocol_workflow.storage.selected import (
    StorageConfigurationError,
    StorageNotReadyError,
    StorageSelectionError,
    create_product_unit_of_work_factory,
    create_unit_of_work_factory,
)
from app.protocol_workflow.storage.sqlite import (
    MIN_SQLITE_VERSION,
    SCHEMA_VERSION_LATEST,
    SqliteSchemaVersionError,
    SqliteStorageConfigurationError,
    SqliteStorageError,
    _dt_from_iso,
    _dt_to_iso,
    assert_sqlite_version,
    build_unit_of_work_factory,
)
from app.protocol_workflow.ports.unit_of_work import UnitOfWorkClosedError

_REPO_ROOT = Path(__file__).resolve().parents[2]

_PRODUCT_TABLES = {
    "schema_version",
    "aggregate_revision",
    "event_stream",
    "outbox_message",
    "inbox_result",
    "execution_reservation",
    "read_chapter_coverage",
    "read_decision_graph",
    "read_workflow_run_status",
    # Task 1R.2 migration 2: durable project allowlist (empty admits none).
    "protocol_workflow_project_allowlist",
}


def _runtime_sqlite_version() -> tuple:
    return tuple(int(p) for p in sqlite3.sqlite_version.split(".")[:3])


_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_PROJ_R = "proj:repair"
_EVENT_BUILDER = EventEnvelopeBuilder()


def _study(
    *,
    study_id: str = "sd:repair:1",
    project_id: str = _PROJ_R,
    revision: int = 1,
) -> StudyDefinitionV3:
    return StudyDefinitionV3(
        study_definition_id=study_id,
        project_id=project_id,
        revision=revision,
        normalized_seed_id="seed:repair",
        normalized_seed_sha256="0" * 64,
        facts={"indication": "repair"},
        updated_at=_T0,
    )


def _built_event(
    *,
    event_id: str,
    stream_id: str,
    sequence: int,
    previous,
    payload: dict,
):
    return _EVENT_BUILDER.build(
        domain_event_id=event_id,
        stream_id=stream_id,
        sequence=sequence,
        event_type="study_definition.revised",
        payload_schema_version="mw_protocol_v3_event_v1",
        upcaster_id="noop:v1",
        actor_type=ActorType.AI,
        actor_id="agent:corpus:1",
        action="revise",
        reason="repair-test",
        payload=payload,
        emitted_at=_T0,
        previous_event_sha256=previous,
    )


@pytest.fixture(scope="module", autouse=True)
def _require_engine_gate() -> None:
    """Fail loudly (never skip) on a runtime below the product engine gate."""
    if _runtime_sqlite_version() < MIN_SQLITE_VERSION:
        pytest.fail(
            f"runtime SQLite {sqlite3.sqlite_version} is below the product "
            f"gate {MIN_SQLITE_VERSION}; the pinned runtime is "
            "/opt/homebrew/bin/python3.12"
        )


def _sqlite_config(tmp_path: Path, name: str = "product.sqlite") -> dict:
    return {"backend": "sqlite", "path": str(tmp_path / name)}


def _table_names(path: Path) -> set:
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Real file durability across close/reopen
# ---------------------------------------------------------------------------


class TestDurableFileState:
    def test_committed_state_survives_full_close_and_reopen(self, tmp_path) -> None:
        config = _sqlite_config(tmp_path)
        factory = build_unit_of_work_factory(config=config)
        from datetime import datetime, timezone

        from packages.contracts.workbench_contracts.protocol_v3 import (
            StudyDefinitionV3,
        )

        study = StudyDefinitionV3(
            study_definition_id="sd:durable:1",
            project_id="proj:durable",
            revision=1,
            normalized_seed_id="seed:1",
            normalized_seed_sha256="0" * 64,
            facts={"indication": "nsclc"},
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        with factory() as uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                "proj:durable", study, 0
            )
        # the committed UoW closed its connection; reopen through a fresh
        # factory (new connection) and verify durable state
        factory2 = build_unit_of_work_factory(config=config)
        with factory2() as uow:
            current = uow.study_definition_repository.get_current(
                "proj:durable", "sd:durable:1"
            )
            assert current is not None
            assert current.revision == 1
            assert current.facts == {"indication": "nsclc"}

    def test_wal_mode_is_persistent_at_file_level(self, tmp_path) -> None:
        path = tmp_path / "wal.sqlite"
        build_unit_of_work_factory(config={"backend": "sqlite", "path": str(path)})
        conn = sqlite3.connect(str(path))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert mode == "wal"


# ---------------------------------------------------------------------------
# Durability pragmas and connection discipline
# ---------------------------------------------------------------------------


class TestConnectionDiscipline:
    def test_uow_enforces_durability_pragmas(self, tmp_path) -> None:
        factory = build_unit_of_work_factory(
            config={
                "backend": "sqlite",
                "path": str(tmp_path / "pragma.sqlite"),
                "busy_timeout_ms": 2500,
            }
        )
        uow = factory()
        pragmas = uow.connection_pragmas()
        assert pragmas["journal_mode"] == "wal"
        # SQLite reports synchronous=2 for FULL
        assert pragmas["synchronous"] == 2
        assert pragmas["foreign_keys"] == 1
        assert pragmas["busy_timeout"] == 2500
        uow.rollback()

    def test_busy_timeout_must_be_a_positive_integer(self, tmp_path) -> None:
        for bad in (0, -1, "1000", 1.5, None):
            with pytest.raises(SqliteStorageConfigurationError):
                build_unit_of_work_factory(
                    config={
                        "backend": "sqlite",
                        "path": str(tmp_path / "bt.sqlite"),
                        "busy_timeout_ms": bad,
                    }
                )

    def test_synchronous_must_be_full(self, tmp_path) -> None:
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(
                config={
                    "backend": "sqlite",
                    "path": str(tmp_path / "sync.sqlite"),
                    "synchronous": "NORMAL",
                }
            )


# ---------------------------------------------------------------------------
# Engine version gate — fail closed before file creation
# ---------------------------------------------------------------------------


class TestEngineVersionGate:
    def test_gate_fails_closed_below_minimum(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(sqlite3, "sqlite_version", "3.51.2")
        with pytest.raises(SqliteStorageError):
            assert_sqlite_version()
        with pytest.raises(SqliteStorageError):
            build_unit_of_work_factory(
                config={"backend": "sqlite", "path": str(tmp_path / "gated.sqlite")}
            )
        # nothing was created before the gate fired
        assert list(tmp_path.iterdir()) == []

    def test_assert_accepts_current_runtime(self) -> None:
        assert assert_sqlite_version() >= MIN_SQLITE_VERSION

    def test_gate_constant_matches_selected_surface(self) -> None:
        from app.protocol_workflow.storage.selected import SELECTED_MIN_ENGINE_VERSION

        assert MIN_SQLITE_VERSION == SELECTED_MIN_ENGINE_VERSION == (3, 51, 3)


# ---------------------------------------------------------------------------
# Configuration fail-closed
# ---------------------------------------------------------------------------


class TestConfigurationFailClosed:
    def test_missing_backend_rejected(self, tmp_path) -> None:
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(config={"path": str(tmp_path / "x.sqlite")})

    def test_wrong_backend_rejected(self, tmp_path) -> None:
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(
                config={"backend": "postgres", "path": str(tmp_path / "x.sqlite")}
            )

    @pytest.mark.parametrize("bad_path", ["", None, 123, Path("")])
    def test_invalid_path_rejected(self, tmp_path, bad_path) -> None:
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(
                config={"backend": "sqlite", "path": bad_path}
            )
        assert list(tmp_path.iterdir()) == []

    def test_unknown_config_key_rejected(self, tmp_path) -> None:
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(
                config={
                    "backend": "sqlite",
                    "path": str(tmp_path / "x.sqlite"),
                    "journal_mode": "DELETE",
                }
            )
        assert list(tmp_path.iterdir()) == []

    def test_directory_path_rejected(self, tmp_path) -> None:
        target = tmp_path / "actually-a-dir"
        target.mkdir()
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(
                config={"backend": "sqlite", "path": str(target)}
            )

    def test_non_database_file_rejected_without_rewrite(self, tmp_path) -> None:
        path = tmp_path / "garbage.sqlite"
        path.write_bytes(b"this is not a sqlite database" * 32)
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(config={"backend": "sqlite", "path": str(path)})
        assert path.read_bytes().startswith(b"this is not a sqlite database")


# ---------------------------------------------------------------------------
# Schema version + migrations
# ---------------------------------------------------------------------------


class TestSchemaVersionAndMigrations:
    def test_bootstrap_creates_product_schema_with_version_three(self, tmp_path) -> None:
        path = tmp_path / "schema.sqlite"
        build_unit_of_work_factory(config={"backend": "sqlite", "path": str(path)})
        tables = _table_names(path)
        assert tables == _PRODUCT_TABLES
        conn = sqlite3.connect(str(path))
        try:
            version = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()[0]
        finally:
            conn.close()
        assert version == SCHEMA_VERSION_LATEST == 3

    def test_repeated_initialization_is_safe(self, tmp_path) -> None:
        from datetime import datetime, timezone

        from packages.contracts.workbench_contracts.protocol_v3 import (
            StudyDefinitionV3,
        )

        config = {"backend": "sqlite", "path": str(tmp_path / "repeat.sqlite")}
        factory = build_unit_of_work_factory(config=config)
        study = StudyDefinitionV3(
            study_definition_id="sd:repeat:1",
            project_id="proj:repeat",
            revision=1,
            normalized_seed_id="seed:1",
            normalized_seed_sha256="0" * 64,
            facts={"indication": "nsclc"},
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        with factory() as uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                "proj:repeat", study, 0
            )
        # re-initialize twice over existing data
        factory_again = build_unit_of_work_factory(config=config)
        build_unit_of_work_factory(config=config)
        with factory_again() as uow:
            assert uow.study_definition_repository.get_current_revision(
                "proj:repeat", "sd:repeat:1"
            ) == 1
        conn = sqlite3.connect(str(tmp_path / "repeat.sqlite"))
        try:
            version = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()[0]
        finally:
            conn.close()
        assert version == SCHEMA_VERSION_LATEST == 3

    def test_future_schema_fails_closed_without_rewrite(self, tmp_path) -> None:
        from datetime import datetime, timezone

        from packages.contracts.workbench_contracts.protocol_v3 import (
            StudyDefinitionV3,
        )

        path = tmp_path / "future.sqlite"
        config = {"backend": "sqlite", "path": str(path)}
        factory = build_unit_of_work_factory(config=config)
        study = StudyDefinitionV3(
            study_definition_id="sd:future:1",
            project_id="proj:future",
            revision=1,
            normalized_seed_id="seed:1",
            normalized_seed_sha256="0" * 64,
            facts={"indication": "nsclc"},
            updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        with factory() as uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                "proj:future", study, 0
            )
        # simulate a database written by a FUTURE product version
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("UPDATE schema_version SET version = 999")
            conn.commit()
        finally:
            conn.close()

        with pytest.raises(SqliteSchemaVersionError):
            build_unit_of_work_factory(config=config)

        # contents are untouched: future version row and committed data remain
        conn = sqlite3.connect(str(path))
        try:
            version = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT COUNT(*) FROM aggregate_revision"
            ).fetchone()[0]
        finally:
            conn.close()
        assert version == 999
        assert rows == 1

    def test_foreign_legacy_database_is_never_adopted(self, tmp_path) -> None:
        path = tmp_path / "legacy.sqlite"
        conn = sqlite3.connect(str(path))
        try:
            conn.execute("CREATE TABLE legacy_notes (letter TEXT NOT NULL)")
            conn.execute("INSERT INTO legacy_notes (letter) VALUES ('a')")
            conn.commit()
        finally:
            conn.close()
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory(config={"backend": "sqlite", "path": str(path)})
        # the foreign database is untouched
        conn = sqlite3.connect(str(path))
        try:
            letters = conn.execute("SELECT letter FROM legacy_notes").fetchall()
        finally:
            conn.close()
        assert letters == [("a",)]


# ---------------------------------------------------------------------------
# Import purity and PoC isolation
# ---------------------------------------------------------------------------


class TestImportPurity:
    def test_import_creates_no_database_directory_worker_or_service(
        self, tmp_path
    ) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(_REPO_ROOT / "services" / "api"), str(_REPO_ROOT / "packages"), str(_REPO_ROOT)]
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        code = (
            "import app.protocol_workflow.storage.sqlite as m; "
            "import app.protocol_workflow.storage.selected as s; "
            "print('imported-ok')"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(tmp_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "imported-ok" in proc.stdout
        # no database file, directory, worker or service artifact was created
        assert list(tmp_path.iterdir()) == [], (
            f"import side effects: {list(tmp_path.iterdir())}"
        )

    def test_product_adapter_never_imports_poc(self) -> None:
        adapter_source = (
            _REPO_ROOT
            / "services/api/app/protocol_workflow/storage/sqlite.py"
        ).read_text(encoding="utf-8")
        selected_source = (
            _REPO_ROOT
            / "services/api/app/protocol_workflow/storage/selected.py"
        ).read_text(encoding="utf-8")
        pattern = re.compile(r"^\s*(?:import pocs\b|from pocs\b)", re.MULTILINE)
        assert not pattern.search(adapter_source)
        assert not pattern.search(selected_source)
        assert "pocs.protocol_v3" not in adapter_source
        assert "pocs.protocol_v3" not in selected_source

    def test_product_schema_carries_no_poc_benchmark_tables(self, tmp_path) -> None:
        path = tmp_path / "scope.sqlite"
        build_unit_of_work_factory(config={"backend": "sqlite", "path": str(path)})
        tables = _table_names(path)
        assert "checkpoint_record" not in tables
        assert "quarantine_record" not in tables
        assert "migration_quarantine" not in tables


# ---------------------------------------------------------------------------
# Explicitly enabled product route on the selected-storage surface
# ---------------------------------------------------------------------------


class TestSelectedProductRoute:
    def test_product_route_returns_working_factory(self, tmp_path) -> None:
        factory = create_product_unit_of_work_factory(
            config={"backend": "sqlite", "path": str(tmp_path / "route.sqlite")}
        )
        uow = factory()
        assert uow is not None
        assert uow.connection_pragmas()["journal_mode"] == "wal"
        uow.rollback()

    def test_product_route_still_rejects_non_selected_backends(self, tmp_path) -> None:
        with pytest.raises(StorageSelectionError):
            create_product_unit_of_work_factory(
                config={"backend": "postgresql", "path": str(tmp_path / "x")}
            )
        with pytest.raises(StorageSelectionError):
            create_product_unit_of_work_factory(
                config={"backend": "memory", "path": str(tmp_path / "x")}
            )

    def test_product_route_without_config_fails_closed(self) -> None:
        with pytest.raises(StorageConfigurationError):
            create_product_unit_of_work_factory(config=None)
        with pytest.raises(StorageConfigurationError):
            create_product_unit_of_work_factory(config={})

    def test_product_route_invalid_adapter_config_propagates_blocker(
        self, tmp_path
    ) -> None:
        with pytest.raises(SqliteStorageConfigurationError):
            create_product_unit_of_work_factory(
                config={"backend": "sqlite", "path": ""}
            )

    def test_default_factory_without_builder_stays_fail_closed(
        self, tmp_path
    ) -> None:
        """The neutral factory must NOT silently pick up the product builder."""
        with pytest.raises(StorageNotReadyError):
            create_unit_of_work_factory(config={"backend": "sqlite"})

    def test_injection_path_stays_compatible(self, tmp_path) -> None:
        """The pre-existing adapter_builder injection hook still works with
        the product builder passed explicitly."""
        factory = create_unit_of_work_factory(
            config={"backend": "sqlite", "path": str(tmp_path / "inj.sqlite")},
            adapter_builder=build_unit_of_work_factory,
        )
        uow = factory()
        assert uow is not None
        uow.rollback()


# ---------------------------------------------------------------------------
# Repair 01: mutators require an active transaction (no autocommit escape)
# ---------------------------------------------------------------------------


class TestPreEntryMutationRejection:
    def test_mutators_rejected_before_entry_leave_zero_durable_changes(
        self, tmp_path
    ) -> None:
        factory = build_unit_of_work_factory(
            _sqlite_config(tmp_path, "preentry.sqlite")
        )
        uow = factory()
        try:
            # reads and diagnostics stay allowed before entry
            assert uow.study_definition_repository.get_current(
                _PROJ_R, "sd:repair:1"
            ) is None
            assert uow.connection_pragmas()["journal_mode"] == "wal"

            reservation = ExecutionReservation(
                execution_reservation_id="rsv:pre:1",
                node_execution_contract_id="nec:pre",
                logical_call_id="call:pre",
                idempotency_key="ik:pre",
                input_sha256="0" * 64,
                attempt=1,
                transport_attempts=0,
                provider_session_id=None,
                status=ReservationStatus.RESERVED,
                terminal_state=None,
                output_sha256=None,
                error_code=None,
                reserved_at=_T0,
                updated_at=_T0,
            )
            coverage = ChapterCoverageRecord(
                project_id=_PROJ_R,
                semantic_node_id="sn:pre",
                chapter_contract_sha256="0" * 64,
                substantive_content_contract_sha256="0" * 64,
                semantic_block_sha256="0" * 64,
                is_locked=False,
                has_substantive_content=True,
                evidence_admitted=True,
            )
            with pytest.raises(UnitOfWorkClosedError):
                uow.study_definition_cas_repository.save_with_expected_revision(
                    _PROJ_R, _study(), 0
                )
            with pytest.raises(UnitOfWorkClosedError):
                uow.event_stream_repository.append_events(_PROJ_R, "s:pre", ())
            with pytest.raises(UnitOfWorkClosedError):
                uow.outbox_repository.enqueue(
                    _PROJ_R, "run:pre", _any_side_effect_kind(), "lk:pre",
                    "0" * 64, _T0,
                )
            with pytest.raises(UnitOfWorkClosedError):
                uow.inbox_repository.record_result(_PROJ_R, "lk:pre", "0" * 64, _T0)
            with pytest.raises(UnitOfWorkClosedError):
                uow.reservation_repository.reserve(_PROJ_R, reservation)
            with pytest.raises(UnitOfWorkClosedError):
                uow.read_model_repository.replace_chapter_coverage(
                    _PROJ_R, "sdr:pre", (coverage,)
                )
        finally:
            uow.rollback()

        # rollback cannot undo what never happened and nothing leaked: the
        # reopened store is completely empty
        with factory() as check:
            assert check.study_definition_repository.get_current_revision(
                _PROJ_R, "sd:repair:1"
            ) is None
            assert check.event_stream_repository.read_events(_PROJ_R, "s:pre") == ()
            assert check.outbox_repository.find_by_logical_key(_PROJ_R, "lk:pre") is None
            assert check.inbox_repository.was_processed(_PROJ_R, "lk:pre") is False
            assert check.reservation_repository.find_unresolved(_PROJ_R) == ()
            assert check.read_model_repository.get_chapter_coverage(
                _PROJ_R, "sdr:pre"
            ) == ()

    def test_entered_mutators_still_work_and_nested_semantics_unchanged(
        self, tmp_path
    ) -> None:
        factory = build_unit_of_work_factory(
            _sqlite_config(tmp_path, "entered.sqlite")
        )
        with factory() as uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_R, _study(), 0
            )
            with factory_nested(uow):
                uow.outbox_repository.enqueue(
                    _PROJ_R, "run:r", _any_side_effect_kind(), "lk:r",
                    "0" * 64, _T0,
                )
        with factory() as check:
            assert check.study_definition_repository.get_current_revision(
                _PROJ_R, "sd:repair:1"
            ) == 1
            assert check.outbox_repository.find_by_logical_key(_PROJ_R, "lk:r") is not None


def _any_side_effect_kind():
    from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind

    return SideEffectKind.EXPORT


from contextlib import contextmanager


@contextmanager
def factory_nested(uow):
    """Second `with` on the SAME uow (nested scope, single transaction)."""
    with uow:
        yield uow


# ---------------------------------------------------------------------------
# Repair 01: SQL-level failure inside a compound write (savepoint atomicity)
# ---------------------------------------------------------------------------


def _add_trigger(path, sql: str) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


class TestSqlFailureAtomicity:
    def test_event_batch_sql_failure_persists_nothing(self, tmp_path) -> None:
        path = tmp_path / "batchfail.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _add_trigger(
            path,
            "CREATE TRIGGER synthetic_second_row_failure BEFORE INSERT ON event_stream "
            "WHEN NEW.sequence = 2 BEGIN SELECT RAISE(FAIL, 'synthetic write failure'); END",
        )
        first = _built_event(
            event_id="evt:1", stream_id="stream:r", sequence=1,
            previous=None, payload={"n": 1},
        )
        second = _built_event(
            event_id="evt:2", stream_id="stream:r", sequence=2,
            previous=first.event_sha256, payload={"n": 2},
        )
        with factory() as uow:
            # unrelated successful work in the same transaction
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_R, _study(), 0
            )
            with pytest.raises(sqlite3.IntegrityError):
                uow.event_stream_repository.append_events(
                    _PROJ_R, "stream:r", (first, second)
                )

        with factory() as check:
            assert check.event_stream_repository.read_events(_PROJ_R, "stream:r") == (), (
                "first event of the SQL-failed batch committed"
            )
            # unrelated successful work survived
            assert check.study_definition_repository.get_current_revision(
                _PROJ_R, "sd:repair:1"
            ) == 1

    def test_read_model_replace_sql_failure_keeps_previous_projection(
        self, tmp_path
    ) -> None:
        path = tmp_path / "replacefail.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        old = ChapterCoverageRecord(
            project_id=_PROJ_R,
            semantic_node_id="sn:1",
            chapter_contract_sha256="1" * 64,
            substantive_content_contract_sha256="1" * 64,
            semantic_block_sha256="1" * 64,
            is_locked=False,
            has_substantive_content=True,
            evidence_admitted=True,
        )
        with factory() as uow:
            uow.read_model_repository.replace_chapter_coverage(
                _PROJ_R, "sdr:r", (old,)
            )
        _add_trigger(
            path,
            "CREATE TRIGGER synthetic_replace_failure BEFORE INSERT ON read_chapter_coverage "
            "WHEN NEW.semantic_node_id = 'sn:2' BEGIN "
            "SELECT RAISE(FAIL, 'synthetic replace failure'); END",
        )
        updated_old = ChapterCoverageRecord(
            project_id=_PROJ_R,
            semantic_node_id="sn:1",
            chapter_contract_sha256="2" * 64,
            substantive_content_contract_sha256="2" * 64,
            semantic_block_sha256="2" * 64,
            is_locked=True,
            has_substantive_content=True,
            evidence_admitted=True,
        )
        new_row = ChapterCoverageRecord(
            project_id=_PROJ_R,
            semantic_node_id="sn:2",
            chapter_contract_sha256="3" * 64,
            substantive_content_contract_sha256="3" * 64,
            semantic_block_sha256="3" * 64,
            is_locked=False,
            has_substantive_content=True,
            evidence_admitted=True,
        )
        with factory() as uow:
            with pytest.raises(sqlite3.IntegrityError):
                uow.read_model_repository.replace_chapter_coverage(
                    _PROJ_R, "sdr:r", (updated_old, new_row)
                )

        with factory() as check:
            rows = check.read_model_repository.get_chapter_coverage(_PROJ_R, "sdr:r")
            # DELETE was rolled back with the failed INSERTs: previous
            # projection fully intact, nothing partially updated
            assert len(rows) == 1
            assert rows[0].semantic_node_id == "sn:1"
            assert rows[0].chapter_contract_sha256 == "1" * 64
            assert rows[0].is_locked is False


# ---------------------------------------------------------------------------
# Repair 01: volatile path rejection
# ---------------------------------------------------------------------------


class TestVolatilePathRejection:
    def test_memory_path_rejected_before_io(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        for bad in (":memory:", Path(":memory:")):
            with pytest.raises(SqliteStorageConfigurationError):
                build_unit_of_work_factory({"backend": "sqlite", "path": bad})
        assert list(tmp_path.iterdir()) == []

    def test_ordinary_relative_path_still_supported(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        factory = build_unit_of_work_factory(
            {"backend": "sqlite", "path": "relative.sqlite"}
        )
        assert (tmp_path / "relative.sqlite").exists()
        uow = factory()
        assert uow.connection_pragmas()["journal_mode"] == "wal"
        uow.rollback()


# ---------------------------------------------------------------------------
# Repair 01: foreign / malformed schema adoption preflight (read-only)
# ---------------------------------------------------------------------------


def _sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_rejected_untouched(tmp_path, name: str, build) -> None:
    path = tmp_path / name
    build(path)
    before = _sha256_of(path)
    wal_before = Path(str(path) + "-wal").exists()
    shm_before = Path(str(path) + "-shm").exists()
    with pytest.raises(SqliteStorageError):
        build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
    assert _sha256_of(path) == before, "rejection rewrote the database file"
    # pre-existing sidecars are never removed by the rejection path
    if wal_before:
        assert Path(str(path) + "-wal").exists()
    if shm_before:
        assert Path(str(path) + "-shm").exists()
    # SQLite's read-only open of a WAL database may leave runtime sidecars;
    # the -wal it leaves MUST be empty — no checkpoint content was written
    wal = Path(str(path) + "-wal")
    if not wal_before and wal.exists():
        assert wal.stat().st_size == 0, (
            "rejection left non-empty -wal (checkpoint content) behind"
        )


class TestForeignSchemaAdoption:
    def _fake_history_db(self, path: Path, versions: list) -> None:
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                "CREATE TABLE schema_version (version INTEGER, applied_at TEXT)"
            )
            for version in versions:
                conn.execute(
                    "INSERT INTO schema_version VALUES (?, 'synthetic')",
                    (version,),
                )
            conn.execute("CREATE TABLE unrelated_legacy_notes (note TEXT)")
            conn.execute("INSERT INTO unrelated_legacy_notes VALUES ('retain me')")
            conn.commit()
        finally:
            conn.close()

    def test_fake_version_zero_is_rejected_untouched(self, tmp_path) -> None:
        _assert_rejected_untouched(
            tmp_path, "v0.sqlite", lambda p: self._fake_history_db(p, [0])
        )

    def test_fake_version_one_is_rejected_untouched(self, tmp_path) -> None:
        _assert_rejected_untouched(
            tmp_path, "v1.sqlite", lambda p: self._fake_history_db(p, [1])
        )

    def test_duplicate_history_is_rejected(self, tmp_path) -> None:
        _assert_rejected_untouched(
            tmp_path, "dup.sqlite", lambda p: self._fake_history_db(p, [1, 1])
        )

    def test_zero_prefixed_history_is_rejected(self, tmp_path) -> None:
        _assert_rejected_untouched(
            tmp_path, "zerogap.sqlite", lambda p: self._fake_history_db(p, [0, 1])
        )

    def test_missing_owned_column_is_rejected(self, tmp_path) -> None:
        """A plausible history plus tables that LACK owned columns is not a
        product database and must never be adopted or migrated in place."""

        def build(path: Path) -> None:
            conn = sqlite3.connect(str(path))
            try:
                conn.execute(
                    "CREATE TABLE schema_version (version INTEGER, applied_at TEXT)"
                )
                conn.execute("INSERT INTO schema_version VALUES (1, 'synthetic')")
                # every owned table present, but aggregate_revision lost a column
                conn.execute(
                    "CREATE TABLE aggregate_revision ("
                    "aggregate_kind TEXT, project_id TEXT, aggregate_id TEXT, "
                    "revision INTEGER, previous_revision_sha256 TEXT)"
                )
                conn.execute(
                    "CREATE TABLE event_stream (project_id TEXT, stream_id TEXT, "
                    "sequence INTEGER, domain_event_id TEXT, body_json TEXT, "
                    "previous_event_sha256 TEXT, event_sha256 TEXT)"
                )
                conn.execute(
                    "CREATE TABLE outbox_message (project_id TEXT, outbox_message_id TEXT)"
                )
                conn.execute(
                    "CREATE TABLE inbox_result (project_id TEXT, inbox_result_id TEXT)"
                )
                conn.execute(
                    "CREATE TABLE execution_reservation (project_id TEXT, "
                    "execution_reservation_id TEXT)"
                )
                conn.execute(
                    "CREATE TABLE read_chapter_coverage (project_id TEXT, "
                    "semantic_document_revision_id TEXT, semantic_node_id TEXT)"
                )
                conn.execute(
                    "CREATE TABLE read_decision_graph (project_id TEXT, "
                    "study_definition_id TEXT, decision_key TEXT)"
                )
                conn.execute(
                    "CREATE TABLE read_workflow_run_status (project_id TEXT, "
                    "workflow_run_id TEXT)"
                )
                conn.commit()
            finally:
                conn.close()

        _assert_rejected_untouched(tmp_path, "shrunk.sqlite", build)

    def test_unrelated_table_besides_owned_schema_is_rejected(self, tmp_path) -> None:
        """Even a genuine product database gains no licence to carry unknown
        tables: unknown provenance is rejected instead of adopted."""

        def build(path: Path) -> None:
            factory = build_unit_of_work_factory(
                {"backend": "sqlite", "path": str(path)}
            )
            conn = sqlite3.connect(str(path))
            try:
                conn.execute(
                    "CREATE TABLE unrelated_legacy_notes (note TEXT)"
                )
                conn.commit()
            finally:
                conn.close()
            del factory

        _assert_rejected_untouched(tmp_path, "extra.sqlite", build)

    def test_empty_version_history_is_rejected(self, tmp_path) -> None:
        def build(path: Path) -> None:
            conn = sqlite3.connect(str(path))
            try:
                conn.execute(
                    "CREATE TABLE schema_version (version INTEGER, applied_at TEXT)"
                )
                conn.commit()
            finally:
                conn.close()

        _assert_rejected_untouched(tmp_path, "emptyv.sqlite", build)


# ---------------------------------------------------------------------------
# Repair 01: timestamp serialization boundary
# ---------------------------------------------------------------------------


class TestTimestampSerialization:
    def test_naive_datetime_rejected_not_reinterpreted(self) -> None:
        naive = datetime(2026, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError):
            _dt_to_iso(naive)

    def test_aware_utc_and_offset_roundtrip(self) -> None:
        utc = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert _dt_from_iso(_dt_to_iso(utc)) == utc
        cst = datetime(2026, 1, 1, 20, 0, tzinfo=timezone(timedelta(hours=8)))
        assert _dt_from_iso(_dt_to_iso(cst)) == cst
        # same instant as 12:00 UTC — normalized, not shifted by local time
        assert _dt_to_iso(cst) == _dt_to_iso(utc)
        assert _dt_to_iso(None) is None


# ---------------------------------------------------------------------------
# Repair 02: constraint-integrity adoption preflight
# ---------------------------------------------------------------------------


class TestConstraintIntegrityPreflight:
    """Same table/column NAMES are not the owned constrained schema.

    A CTAS clone (or any same-name/same-column rewrite) loses PRIMARY KEY,
    UNIQUE and NOT NULL semantics; the adoption preflight must verify the
    actual constraint structure, not just identifiers.  Rejection must leave
    the foreign database byte-identical.
    """

    def test_ctas_name_and_column_clone_is_rejected(self, tmp_path) -> None:
        source = tmp_path / "product.sqlite"
        build_unit_of_work_factory({"backend": "sqlite", "path": str(source)})

        def build(target: Path) -> None:
            conn = sqlite3.connect(str(target))
            try:
                conn.execute("ATTACH DATABASE ? AS product", (str(source),))
                tables = conn.execute(
                    "SELECT name FROM product.sqlite_master "
                    "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                for (tbl,) in tables:
                    conn.execute(
                        f'CREATE TABLE "{tbl}" AS SELECT * FROM product."{tbl}"'
                    )
                conn.commit()
            finally:
                conn.close()

        _assert_rejected_untouched(tmp_path, "ctas.sqlite", build)

    def _clone_and_tamper(self, tmp_path, name: str, tamper):
        """Copy an owned product database, then apply *tamper* to the copy."""
        source = tmp_path / "owned.sqlite"
        build_unit_of_work_factory({"backend": "sqlite", "path": str(source)})

        def build(target: Path) -> None:
            shutil.copy2(source, target)
            conn = sqlite3.connect(str(target))
            try:
                tamper(conn)
                conn.commit()
            finally:
                conn.close()

        return build

    def test_primary_key_and_unique_loss_on_event_stream_is_rejected(
        self, tmp_path
    ) -> None:
        def tamper(conn) -> None:
            conn.execute("ALTER TABLE event_stream RENAME TO event_stream_old")
            conn.execute(
                "CREATE TABLE event_stream ("
                "project_id TEXT NOT NULL, stream_id TEXT NOT NULL, "
                "sequence INTEGER NOT NULL, domain_event_id TEXT NOT NULL, "
                "body_json TEXT NOT NULL, previous_event_sha256 TEXT, "
                "event_sha256 TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO event_stream SELECT project_id, stream_id, sequence, "
                "domain_event_id, body_json, previous_event_sha256, event_sha256 "
                "FROM event_stream_old"
            )
            conn.execute("DROP TABLE event_stream_old")

        _assert_rejected_untouched(
            tmp_path,
            "no_pk.sqlite",
            self._clone_and_tamper(tmp_path, "no_pk_src.sqlite", tamper),
        )

    def test_unique_constraint_loss_on_outbox_is_rejected(self, tmp_path) -> None:
        def tamper(conn) -> None:
            conn.execute("ALTER TABLE outbox_message RENAME TO outbox_old")
            conn.execute(
                "CREATE TABLE outbox_message ("
                "project_id TEXT NOT NULL, outbox_message_id TEXT NOT NULL, "
                "workflow_run_id TEXT NOT NULL, side_effect_kind TEXT NOT NULL, "
                "logical_key TEXT NOT NULL, payload_sha256 TEXT NOT NULL, "
                "status TEXT NOT NULL, created_at TEXT NOT NULL, "
                "dispatched_at TEXT, completed_at TEXT, "
                "attempt INTEGER NOT NULL DEFAULT 0, error_detail TEXT, "
                "result_sha256 TEXT, result_received_at TEXT, result_consumed_at TEXT, "
                "PRIMARY KEY (project_id, outbox_message_id))"
            )
            conn.execute(
                "INSERT INTO outbox_message SELECT * FROM outbox_old"
            )
            conn.execute("DROP TABLE outbox_old")

        _assert_rejected_untouched(
            tmp_path,
            "no_unique.sqlite",
            self._clone_and_tamper(tmp_path, "no_unique_src.sqlite", tamper),
        )

    def test_not_null_loss_on_reservation_is_rejected(self, tmp_path) -> None:
        def tamper(conn) -> None:
            conn.execute(
                "ALTER TABLE execution_reservation RENAME TO reservation_old"
            )
            conn.execute(
                "CREATE TABLE execution_reservation ("
                "project_id TEXT NOT NULL, execution_reservation_id TEXT NOT NULL, "
                "node_execution_contract_id TEXT NOT NULL, "
                "logical_call_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, "
                "input_sha256 TEXT, attempt INTEGER NOT NULL, "
                "transport_attempts INTEGER NOT NULL DEFAULT 0, "
                "provider_session_id TEXT, status TEXT NOT NULL, "
                "terminal_state TEXT, output_sha256 TEXT, error_code TEXT, "
                "reserved_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
                "PRIMARY KEY (project_id, execution_reservation_id), "
                "UNIQUE (project_id, logical_call_id, idempotency_key), "
                "UNIQUE (project_id, logical_call_id, attempt))"
            )
            conn.execute(
                "INSERT INTO execution_reservation SELECT * FROM reservation_old"
            )
            conn.execute("DROP TABLE reservation_old")

        _assert_rejected_untouched(
            tmp_path,
            "no_notnull.sqlite",
            self._clone_and_tamper(tmp_path, "no_notnull_src.sqlite", tamper),
        )

    def test_untouched_product_copy_is_still_accepted(self, tmp_path) -> None:
        """Positive control: the constraint check must not over-reject an
        unmodified owned database."""
        source = tmp_path / "owned.sqlite"
        build_unit_of_work_factory({"backend": "sqlite", "path": str(source)})
        target = tmp_path / "copy.sqlite"
        shutil.copy2(source, target)
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(target)})
        uow = factory()
        assert uow.connection_pragmas()["journal_mode"] == "wal"
        uow.rollback()


class TestForwardMigrationAndClaimAtomicity:
    def test_failed_upgrade_preserves_v1_and_can_resume(self, tmp_path, monkeypatch):
        import app.protocol_workflow.storage.sqlite as adapter
        from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind

        path = tmp_path / "failed_upgrade.sqlite"
        config = {"backend": "sqlite", "path": path}
        # Task 1R.2 ships real migration 2: exercise the synthetic upgrade
        # against a true v1 base so the recorded v1 history assertions hold.
        v1_base = adapter._MIGRATIONS[:1]
        monkeypatch.setattr(adapter, "_MIGRATIONS", v1_base)
        monkeypatch.setattr(adapter, "SCHEMA_VERSION_LATEST", 1)
        factory = build_unit_of_work_factory(config)
        with factory() as uow:
            before = uow.outbox_repository.enqueue(
                "proj:upgrade", "run:1", SideEffectKind.EXPORT, "lk:1",
                "1" * 64, datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        original = v1_base
        create = "CREATE TABLE migration_probe (project_id TEXT NOT NULL PRIMARY KEY)"
        shape = {"migration_probe": ("project_id",)}
        monkeypatch.setattr(adapter, "_MIGRATIONS", original + (
            (2, "synthetic failing migration", (create, "INSERT INTO missing_table VALUES (1)"), shape),
        ))
        monkeypatch.setattr(adapter, "SCHEMA_VERSION_LATEST", 2)
        with pytest.raises(sqlite3.OperationalError, match="missing_table"):
            build_unit_of_work_factory(config)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT version FROM schema_version").fetchall() == [(1,)]
            assert conn.execute("SELECT name FROM sqlite_master WHERE name='migration_probe'").fetchall() == []
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        monkeypatch.setattr(adapter, "_MIGRATIONS", original + (
            (2, "synthetic repaired migration", (create,), shape),
        ))
        resumed = build_unit_of_work_factory(config)
        with resumed() as check:
            assert check.outbox_repository.find_by_logical_key("proj:upgrade", "lk:1") == before
        build_unit_of_work_factory(config)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall() == [(1,), (2,)]

    @pytest.mark.parametrize("warm_cache", [False, True])
    @pytest.mark.parametrize("change", ["add_table", "add_column"])
    def test_owned_v1_migrates_and_reopens_without_losing_rows(
        self, tmp_path, monkeypatch, change, warm_cache
    ):
        import app.protocol_workflow.storage.sqlite as adapter
        from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind

        path = tmp_path / "upgrade.sqlite"
        config = {"backend": "sqlite", "path": path}
        # Task 1R.2 ships real migration 2: start from a true v1 base so the
        # synthetic forward-migration mechanics keep their v1 assertions.
        v1_base = adapter._MIGRATIONS[:1]
        monkeypatch.setattr(adapter, "_MIGRATIONS", v1_base)
        monkeypatch.setattr(adapter, "SCHEMA_VERSION_LATEST", 1)
        factory = build_unit_of_work_factory(config)
        with factory() as uow:
            before = uow.outbox_repository.enqueue(
                "proj:upgrade", "run:1", SideEffectKind.EXPORT, "lk:1",
                "1" * 64, datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        if warm_cache:
            build_unit_of_work_factory(config)
        else:
            # Exercise cold startup as well as the formerly cached v1 path.
            monkeypatch.setattr(adapter, "_REFERENCE_SCHEMA_FINGERPRINT", None, raising=False)
        if change == "add_table":
            statement = "CREATE TABLE project_allowlist (project_id TEXT NOT NULL PRIMARY KEY)"
            fingerprint = {"project_allowlist": ("project_id",)}
        else:
            statement = "ALTER TABLE outbox_message ADD COLUMN migration_note TEXT"
            old_columns = adapter._MIGRATIONS[0][3]["outbox_message"]
            fingerprint = {"outbox_message": (*old_columns, "migration_note")}
        monkeypatch.setattr(adapter, "_MIGRATIONS", v1_base + (
            (2, "synthetic migration", (statement,), fingerprint),
        ))
        monkeypatch.setattr(adapter, "SCHEMA_VERSION_LATEST", 2)

        upgraded = build_unit_of_work_factory(config)
        for _ in range(2):
            with upgraded() as uow:
                assert uow.outbox_repository.find_by_logical_key("proj:upgrade", "lk:1") == before
            upgraded = build_unit_of_work_factory(config)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT version FROM schema_version ORDER BY version").fetchall() == [(1,), (2,)]
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    def test_caught_claim_failure_rolls_back_entire_claim_only(self, tmp_path):
        from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind

        path = tmp_path / "claim.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": path})
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with factory() as uow:
            for index in (1, 2, 3):
                uow.outbox_repository.enqueue(
                    "proj:claim", "run:1", SideEffectKind.EXPORT, f"lk:{index}",
                    str(index) * 64, now + timedelta(seconds=index),
                )
        with sqlite3.connect(path) as conn:
            conn.execute("CREATE TRIGGER fail_second_claim BEFORE UPDATE ON outbox_message "
                         "WHEN OLD.logical_key='lk:2' BEGIN SELECT RAISE(FAIL, 'claim failure'); END")
        with factory() as uow:
            unrelated = uow.outbox_repository.enqueue(
                "proj:other", "run:other", SideEffectKind.EXPORT, "lk:other", "4" * 64, now,
            )
            with pytest.raises(sqlite3.IntegrityError, match="claim failure"):
                uow.outbox_repository.claim_pending("proj:claim", limit=3, claimed_at=now)
        with factory() as check:
            for index in (1, 2, 3):
                message = check.outbox_repository.find_by_logical_key("proj:claim", f"lk:{index}")
                assert (message.status.value, message.attempt, message.dispatched_at) == ("pending", 0, None)
            assert check.outbox_repository.find_by_logical_key("proj:other", "lk:other") == unrelated
