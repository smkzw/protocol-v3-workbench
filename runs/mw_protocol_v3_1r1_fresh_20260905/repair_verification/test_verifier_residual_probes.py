"""Independent verifier probes for residual concerns after the Task 1R.1 repair.

Read-only with respect to product source: these probes exercise the CURRENT
adapter to determine (a) whether claim_pending is a savepoint-atomic compound
write like the repaired event-batch/projection paths, and (b) whether an owned
v1 database can still be adopted once a FUTURE migration 2 is appended (the
1R.2 allowlist-table scenario).  The future-migration probe monkeypatches the
module migration registry in-process only and restores it afterwards.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

import app.protocol_workflow.storage.sqlite as sqlite_adapter
from app.protocol_workflow.storage.sqlite import (
    SqliteStorageConfigurationError,
    build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind


_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_PROJ = "proj:verify:residual"


def _sha(n: int) -> str:
    return f"{n:064x}"


class TestClaimPendingAtomicity:
    def test_mid_claim_sql_failure_leaves_partial_claim(self, tmp_path) -> None:
        """claim_pending updates rows in a loop WITHOUT a savepoint.  A SQL
        failure on a later row, caught inside the caller's transaction, lets
        the earlier claims commit — the same defect class repaired for event
        batches and projection replacement.  This probe RECORDS the current
        behavior; DISPATCHED is a recoverable state, so the impact is a
        partial claim plus a lost return tuple, not lost work."""
        path = tmp_path / "claim.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as uow:
            for i in (1, 2, 3):
                uow.outbox_repository.enqueue(
                    _PROJ, f"run:{i}", SideEffectKind.EXPORT, f"lk:{i}",
                    _sha(30 + i), _T0,
                )
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(
                "CREATE TRIGGER synthetic_claim_failure BEFORE UPDATE ON outbox_message "
                "WHEN OLD.logical_key = 'lk:2' BEGIN "
                "SELECT RAISE(FAIL, 'synthetic claim failure'); END"
            )
            conn.commit()
        finally:
            conn.close()

        with factory() as uow:
            outbox = uow.outbox_repository
            with pytest.raises(sqlite3.IntegrityError):
                outbox.claim_pending(_PROJ, limit=10, claimed_at=_T1)
            # caller catches inside the transaction and lets it commit

        with factory() as check:
            outbox = check.outbox_repository
            states = {
                m.logical_key: m.status.value
                for m in (
                    outbox.find_by_logical_key(_PROJ, "lk:1"),
                    outbox.find_by_logical_key(_PROJ, "lk:2"),
                    outbox.find_by_logical_key(_PROJ, "lk:3"),
                )
            }
            attempts = {
                m.logical_key: m.attempt
                for m in (
                    outbox.find_by_logical_key(_PROJ, "lk:1"),
                    outbox.find_by_logical_key(_PROJ, "lk:2"),
                    outbox.find_by_logical_key(_PROJ, "lk:3"),
                )
            }
        # Current observed behavior: lk:1 was claimed (DISPATCHED, attempt=1)
        # while lk:2/lk:3 stayed PENDING — a partial claim survived the
        # caught failure.  Assert the OBSERVED state so the finding is
        # executable evidence, not a claim.
        assert states == {"lk:1": "dispatched", "lk:2": "pending", "lk:3": "pending"}
        assert attempts == {"lk:1": 1, "lk:2": 0, "lk:3": 0}


class TestForwardMigrationAdoption:
    def _make_owned_v1_database(self, path) -> None:
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as uow:
            uow.outbox_repository.enqueue(
                _PROJ, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(1), _T0,
            )

    def test_owned_v1_db_rejected_once_migration2_exists(self, tmp_path) -> None:
        """1R.2 will append a migration 2 (project allowlist table).  The
        adoption preflight compares the existing database against a reference
        fingerprint built from ALL migrations (latest schema), not from the
        APPLIED subset, so an owned v1 database should be rejected instead of
        migrated forward.  This probe RECORDS that current behavior."""
        path = tmp_path / "forward.sqlite"
        self._make_owned_v1_database(path)

        original_migrations = sqlite_adapter._MIGRATIONS
        original_latest = sqlite_adapter.SCHEMA_VERSION_LATEST
        original_fingerprint = sqlite_adapter._REFERENCE_SCHEMA_FINGERPRINT
        allowlist_columns = ("project_id", "allowlist_state")
        try:
            sqlite_adapter._MIGRATIONS = original_migrations + (
                (
                    2,
                    "synthetic 1R.2-style project allowlist",
                    (
                        """
                        CREATE TABLE IF NOT EXISTS project_allowlist (
                            project_id     TEXT NOT NULL,
                            allowlist_state TEXT NOT NULL,
                            PRIMARY KEY (project_id)
                        )
                        """,
                    ),
                    {"project_allowlist": allowlist_columns},
                ),
            )
            sqlite_adapter.SCHEMA_VERSION_LATEST = sqlite_adapter._MIGRATIONS[-1][0]
            sqlite_adapter._REFERENCE_SCHEMA_FINGERPRINT = None

            with pytest.raises(SqliteStorageConfigurationError) as excinfo:
                build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
            print(f"\n[forward-migration probe] rejection: {excinfo.value}")
        finally:
            sqlite_adapter._MIGRATIONS = original_migrations
            sqlite_adapter.SCHEMA_VERSION_LATEST = original_latest
            sqlite_adapter._REFERENCE_SCHEMA_FINGERPRINT = original_fingerprint

        # Control: with the registry restored, the SAME owned v1 database is
        # adopted again without error.
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as check:
            assert check.outbox_repository.find_by_logical_key(_PROJ, "lk:1") is not None
