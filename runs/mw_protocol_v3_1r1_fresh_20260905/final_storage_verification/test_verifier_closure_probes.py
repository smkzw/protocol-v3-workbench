"""Independent closure probes re-running the round-2 counterexample mechanics
with CORRECT criteria against the repaired adapter.

Round-2 probes (runs/.../repair_verification/) asserted the then-broken
behavior (v1 database rejected once migration 2 exists; partial claim
survives).  They are preserved as historical evidence and are NOT gates.  These
probes re-execute the same scenarios and assert the fixed contract: forward
migration succeeds and retains data; a caught mid-claim SQL failure rolls back
the whole claim.  The migration registry is monkeypatched in-process only and
restored by pytest's monkeypatch fixture.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

import app.protocol_workflow.storage.sqlite as sqlite_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind


_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_PROJ = "proj:verify:closure"


def _sha(n: int) -> str:
    return f"{n:064x}"


class TestR1ClosureForwardMigration:
    def test_round2_allowlist_scenario_now_migrates(self, tmp_path, monkeypatch):
        path = tmp_path / "forward.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as uow:
            original_message = uow.outbox_repository.enqueue(
                _PROJ, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(1), _T0,
            )
        # Warm the process exactly like the round-2 probe did (factory build
        # over the v1 database before the future migration exists).
        build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})

        monkeypatch.setattr(
            sqlite_adapter,
            "_MIGRATIONS",
            sqlite_adapter._MIGRATIONS
            + (
                (
                    2,
                    "synthetic 1R.2-style project allowlist (round-2 scenario)",
                    (
                        """
                        CREATE TABLE IF NOT EXISTS project_allowlist (
                            project_id     TEXT NOT NULL,
                            allowlist_state TEXT NOT NULL,
                            PRIMARY KEY (project_id)
                        )
                        """,
                    ),
                    {"project_allowlist": ("project_id", "allowlist_state")},
                ),
            ),
        )
        monkeypatch.setattr(
            sqlite_adapter, "SCHEMA_VERSION_LATEST",
            sqlite_adapter._MIGRATIONS[-1][0],
        )

        # Round 2: this exact call raised SqliteStorageConfigurationError.
        upgraded = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with upgraded() as check:
            assert (
                check.outbox_repository.find_by_logical_key(_PROJ, "lk:1")
                == original_message
            )
        # Reopen again: post-upgrade preflight must accept the v2 database.
        reopened = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with reopened() as check:
            assert (
                check.outbox_repository.find_by_logical_key(_PROJ, "lk:1")
                == original_message
            )
        with sqlite3.connect(str(path)) as conn:
            versions = conn.execute(
                "SELECT version FROM schema_version ORDER BY version"
            ).fetchall()
            assert versions == [(1,), (2,)]
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


class TestR2ClosureClaimAtomicity:
    def test_round2_partial_claim_scenario_now_rolls_back_whole_claim(
        self, tmp_path
    ):
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
            unrelated = uow.outbox_repository.enqueue(
                "proj:verify:other", "run:x", SideEffectKind.EXPORT, "lk:other",
                _sha(9), _T0,
            )
            with pytest.raises(sqlite3.IntegrityError):
                uow.outbox_repository.claim_pending(_PROJ, limit=10, claimed_at=_T1)

        with factory() as check:
            outbox = check.outbox_repository
            for key in ("lk:1", "lk:2", "lk:3"):
                message = outbox.find_by_logical_key(_PROJ, key)
                assert (message.status.value, message.attempt, message.dispatched_at) == (
                    "pending", 0, None,
                )
            assert outbox.find_by_logical_key("proj:verify:other", "lk:other") == unrelated
