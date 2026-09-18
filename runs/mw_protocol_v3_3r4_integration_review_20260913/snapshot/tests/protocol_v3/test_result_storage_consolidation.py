"""Task 1R.4 durable result-store consolidation — SQLite checks (red first).

Consolidation contract under test (see ``services/api/.../storage/sqlite.py``):

* Paired results (an ``outbox_message`` row exists for the logical key) are
  stored authoritatively in additive ``outbox_message`` columns
  (``result_sha256``, ``result_received_at``, ``result_consumed_at``).  New
  paired receipts MUST NOT insert a competing ``inbox_result`` row.
* Standalone results (no ``outbox_message`` row for the key) keep the legacy
  ``inbox_result`` representation; recording/consuming them MUST NOT invent
  an outbox dispatch row.
* Historical ``inbox_result`` rows survive migration byte-identical as
  evidence; reads prefer the consolidated outbox state once present, and
  writes adopt history verbatim (same id/sha/timestamps) instead of
  rewriting it.
* Receipt (``RECEIVED``) and business consumption (``CONSUMED``) stay
  distinct and MUST NOT collapse into the outbox ``COMPLETED`` dispatch ack.

Synthetic temp DBs only; no model calls.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.protocol_workflow.events.inbox import ConsumeOutcomeKind, InboxConsumer
from app.protocol_workflow.events.outbox import (
    DispatchOutcomeKind,
    DispatchResult,
    OutboxDispatcher,
)
from app.protocol_workflow.ports.repositories import (
    AggregateNotFoundError,
    IdempotencyConflictError,
    InboxStatus,
    OutboxStatus,
    RepositoryStateTransitionError,
)
from app.protocol_workflow.storage.sqlite import (
    SCHEMA_VERSION_LATEST,
    build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
_T3 = datetime(2026, 1, 4, tzinfo=timezone.utc)

_PROJ = "proj:1r4:consolidation"
_RUN = "run:1r4:1"
_PAYLOAD = "p" * 64
_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _raw(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _inbox_rows(path: Path):
    conn = _raw(path)
    try:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT project_id, inbox_result_id, logical_key, result_sha256,"
                " status, received_at, consumed_at FROM inbox_result"
                " ORDER BY project_id, logical_key"
            ).fetchall()
        ]
    finally:
        conn.close()


def _outbox_result_cols(path: Path, project_id: str, logical_key: str):
    conn = _raw(path)
    try:
        row = conn.execute(
            "SELECT result_sha256, result_received_at, result_consumed_at"
            " FROM outbox_message WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()
        return tuple(row) if row is not None else None
    finally:
        conn.close()


def _inbox_count(path: Path, project_id: str, logical_key: str) -> int:
    conn = _raw(path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM inbox_result WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()[0]
    finally:
        conn.close()


def _outbox_count(path: Path, project_id: str, logical_key: str) -> int:
    conn = _raw(path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM outbox_message WHERE project_id=? AND logical_key=?",
            (project_id, logical_key),
        ).fetchone()[0]
    finally:
        conn.close()


def _schema_history(path: Path):
    conn = _raw(path)
    try:
        return conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
    finally:
        conn.close()


class _FixedResultHandler:
    """Side-effect handler returning one fixed result hash."""

    def __init__(self, sha: str) -> None:
        self.calls = 0
        self.sha = sha

    def __call__(self, message):  # noqa: ANN001, ANN202
        self.calls += 1
        return DispatchResult(result_sha256=self.sha)


class _FailingHandler:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, message):  # noqa: ANN001, ANN202
        self.calls += 1
        raise RuntimeError("synthetic dispatch failure")


class _CountingSemantic:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, result):  # noqa: ANN001, ANN202
        self.calls += 1
        return None


def _enqueue(factory, key: str, project_id: str = _PROJ):
    with factory() as uow:
        return uow.outbox_repository.enqueue(
            project_id, _RUN, SideEffectKind.EXPORT, key, _PAYLOAD, _T0
        )


# ---------------------------------------------------------------------------
# Migration 2 -> 3: additive columns, history preserved, repeatable
# ---------------------------------------------------------------------------


class TestConsolidationMigration:
    def test_fresh_bootstrap_carries_result_columns_at_version_three(
        self, tmp_path
    ) -> None:
        path = tmp_path / "fresh3.sqlite"
        build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        assert SCHEMA_VERSION_LATEST == 3
        assert [tuple(r) for r in _schema_history(path)] == [(1,), (2,), (3,)]
        conn = _raw(path)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(outbox_message)")}
            assert {
                "result_sha256",
                "result_received_at",
                "result_consumed_at",
            } <= cols
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()

    def test_v2_history_migrates_preserving_ids_rows_and_repeatability(
        self, tmp_path, monkeypatch
    ) -> None:
        import app.protocol_workflow.storage.sqlite as adapter

        real_migrations = adapter._MIGRATIONS
        real_latest = adapter.SCHEMA_VERSION_LATEST
        assert real_latest == 3

        path = tmp_path / "v2upgrade.sqlite"
        config = {"backend": "sqlite", "path": str(path)}
        # True v2 base: first two migrations only.
        monkeypatch.setattr(adapter, "_MIGRATIONS", real_migrations[:2])
        monkeypatch.setattr(adapter, "SCHEMA_VERSION_LATEST", 2)
        v2factory = build_unit_of_work_factory(config)
        with v2factory() as uow:
            before_msg = uow.outbox_repository.enqueue(
                _PROJ, _RUN, SideEffectKind.EXPORT, "lk:paired", _PAYLOAD, _T0
            )
            before_paired = uow.inbox_repository.record_result(
                _PROJ, "lk:paired", _SHA_A, _T1
            )
            before_standalone = uow.inbox_repository.record_result(
                _PROJ, "lk:standalone", _SHA_B, _T1
            )
        before_rows = _inbox_rows(path)

        # Restore the real migration chain and upgrade: v2 -> v3.
        monkeypatch.setattr(adapter, "_MIGRATIONS", real_migrations)
        monkeypatch.setattr(adapter, "SCHEMA_VERSION_LATEST", real_latest)
        upgraded = build_unit_of_work_factory(config)

        assert [tuple(r) for r in _schema_history(path)] == [(1,), (2,), (3,)]
        with upgraded() as uow:
            assert (
                uow.outbox_repository.find_by_logical_key(_PROJ, "lk:paired")
                == before_msg
            )
            assert uow.inbox_repository.get_result(_PROJ, "lk:paired") == before_paired
            assert (
                uow.inbox_repository.get_result(_PROJ, "lk:standalone")
                == before_standalone
            )
        # Historical rows byte-identical; new columns NULL for the old row.
        assert _inbox_rows(path) == before_rows
        assert _outbox_result_cols(path, _PROJ, "lk:paired") == (None, None, None)
        # Repeat bootstrap: no extra effects.
        build_unit_of_work_factory(config)
        assert [tuple(r) for r in _schema_history(path)] == [(1,), (2,), (3,)]
        assert _inbox_rows(path) == before_rows
        conn = _raw(path)
        try:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Paired results: single outbox authority, no competing inbox row
# ---------------------------------------------------------------------------


class TestPairedResultSingleAuthority:
    def test_paired_receipt_writes_outbox_only(self, tmp_path) -> None:
        path = tmp_path / "paired.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        msg = _enqueue(factory, "lk:paired")

        with factory() as uow:
            first = uow.inbox_repository.record_result(_PROJ, "lk:paired", _SHA_A, _T1)
        assert first.status is InboxStatus.RECEIVED
        assert first.result_sha256 == _SHA_A
        assert first.received_at == _T1
        assert first.consumed_at is None
        assert first.inbox_result_id.startswith("ib-outbox-")
        assert first.inbox_result_id.endswith(msg.outbox_message_id)

        with factory() as uow:
            assert uow.inbox_repository.was_processed(_PROJ, "lk:paired") is True
            assert uow.inbox_repository.get_result(_PROJ, "lk:paired") == first

        # No competing inbox row; outbox holds receipt, nothing consumed.
        assert _inbox_count(path, _PROJ, "lk:paired") == 0
        assert _outbox_result_cols(path, _PROJ, "lk:paired") == (
            _SHA_A,
            _T1.isoformat(timespec="microseconds"),
            None,
        )

    def test_paired_replay_same_sha_is_idempotent(self, tmp_path) -> None:
        path = tmp_path / "replay.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _enqueue(factory, "lk:paired")

        with factory() as uow:
            first = uow.inbox_repository.record_result(_PROJ, "lk:paired", _SHA_A, _T1)
        with factory() as uow:
            replay = uow.inbox_repository.record_result(_PROJ, "lk:paired", _SHA_A, _T2)
        # First receipt wins; no duplicate rows or effects.
        assert replay == first
        assert replay.received_at == _T1
        assert _inbox_count(path, _PROJ, "lk:paired") == 0
        assert _outbox_count(path, _PROJ, "lk:paired") == 1

    def test_paired_hash_conflict_fails_closed(self, tmp_path) -> None:
        path = tmp_path / "conflict.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _enqueue(factory, "lk:paired")
        with factory() as uow:
            uow.inbox_repository.record_result(_PROJ, "lk:paired", _SHA_A, _T1)

        with factory() as uow:
            with pytest.raises(IdempotencyConflictError) as exc:
                uow.inbox_repository.record_result(_PROJ, "lk:paired", _SHA_B, _T2)
        assert exc.value.existing_sha256 == _SHA_A
        assert exc.value.incoming_sha256 == _SHA_B
        # Loser left no trace.
        assert _outbox_result_cols(path, _PROJ, "lk:paired") == (
            _SHA_A,
            _T1.isoformat(timespec="microseconds"),
            None,
        )
        assert _inbox_count(path, _PROJ, "lk:paired") == 0

    def test_conflict_against_historical_row_names_history(self, tmp_path) -> None:
        path = tmp_path / "histconflict.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        # Historical inbox row first (pre-consolidation evidence), then the
        # paired outbox row appears.
        with factory() as uow:
            hist = uow.inbox_repository.record_result(_PROJ, "lk:hist", _SHA_A, _T0)
        _enqueue(factory, "lk:hist")

        with factory() as uow:
            with pytest.raises(IdempotencyConflictError) as exc:
                uow.inbox_repository.record_result(_PROJ, "lk:hist", _SHA_B, _T2)
        assert exc.value.existing_sha256 == _SHA_A
        assert exc.value.incoming_sha256 == _SHA_B
        # History untouched; nothing consolidated for the loser.
        assert _inbox_rows(path) == [
            (_PROJ, hist.inbox_result_id, "lk:hist", _SHA_A, "received",
             _T0.isoformat(timespec="microseconds"), None)
        ]
        assert _outbox_result_cols(path, _PROJ, "lk:hist") == (None, None, None)

    def test_outbox_port_unchanged_on_new_schema(self, tmp_path) -> None:
        path = tmp_path / "outboxport.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as uow:
            first = uow.outbox_repository.enqueue(
                _PROJ, _RUN, SideEffectKind.EXPORT, "lk:1", _PAYLOAD, _T0
            )
            replay = uow.outbox_repository.enqueue(
                _PROJ, _RUN, SideEffectKind.EXPORT, "lk:1", _PAYLOAD, _T1
            )
            assert replay == first
            with pytest.raises(IdempotencyConflictError):
                uow.outbox_repository.enqueue(
                    _PROJ, _RUN, SideEffectKind.EXPORT, "lk:1", _SHA_A, _T2
                )


# ---------------------------------------------------------------------------
# Received vs consumed stay distinct; no premature completion synthesis
# ---------------------------------------------------------------------------


class TestReceivedConsumedDistinct:
    def test_consume_sets_consumed_without_completing_outbox(self, tmp_path) -> None:
        path = tmp_path / "consume.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _enqueue(factory, "lk:paired")
        with factory() as uow:
            uow.outbox_repository.claim_pending(_PROJ, limit=10, claimed_at=_T0)
            uow.inbox_repository.record_result(_PROJ, "lk:paired", _SHA_A, _T1)

        with factory() as uow:
            consumed = uow.inbox_repository.mark_consumed(_PROJ, "lk:paired", _T2)
        assert consumed.status is InboxStatus.CONSUMED
        assert consumed.result_sha256 == _SHA_A
        assert consumed.received_at == _T1
        assert consumed.consumed_at == _T2

        # Consumption is not a dispatch ack: status/completed_at untouched.
        with factory() as uow:
            msg = uow.outbox_repository.find_by_logical_key(_PROJ, "lk:paired")
            assert msg is not None
            assert msg.status is OutboxStatus.DISPATCHED
            assert msg.completed_at is None
        assert _outbox_result_cols(path, _PROJ, "lk:paired") == (
            _SHA_A,
            _T1.isoformat(timespec="microseconds"),
            _T2.isoformat(timespec="microseconds"),
        )
        assert _inbox_count(path, _PROJ, "lk:paired") == 0

    def test_double_consume_rejected(self, tmp_path) -> None:
        path = tmp_path / "double.sqlite"  # noqa: F841
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _enqueue(factory, "lk:paired")
        with factory() as uow:
            uow.inbox_repository.record_result(_PROJ, "lk:paired", _SHA_A, _T1)
            uow.inbox_repository.mark_consumed(_PROJ, "lk:paired", _T2)
        with factory() as uow:
            with pytest.raises(RepositoryStateTransitionError):
                uow.inbox_repository.mark_consumed(_PROJ, "lk:paired", _T3)

    def test_consume_without_any_result_not_found(self, tmp_path) -> None:
        path = tmp_path / "noresult.sqlite"  # noqa: F841
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _enqueue(factory, "lk:paired")
        with factory() as uow:
            with pytest.raises(AggregateNotFoundError):
                uow.inbox_repository.mark_consumed(_PROJ, "lk:paired", _T2)


# ---------------------------------------------------------------------------
# Standalone results: legacy representation, no invented dispatch
# ---------------------------------------------------------------------------


class TestStandaloneCompatibility:
    def test_standalone_record_and_consume_invents_no_outbox(self, tmp_path) -> None:
        path = tmp_path / "standalone.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})

        with factory() as uow:
            first = uow.inbox_repository.record_result(
                _PROJ, "lk:standalone", _SHA_B, _T1
            )
        assert first.status is InboxStatus.RECEIVED
        assert first.received_at == _T1
        assert _outbox_count(path, _PROJ, "lk:standalone") == 0

        with factory() as uow:
            assert uow.inbox_repository.was_processed(_PROJ, "lk:standalone") is True
            assert uow.inbox_repository.get_result(_PROJ, "lk:standalone") == first
            consumed = uow.inbox_repository.mark_consumed(_PROJ, "lk:standalone", _T2)
        assert consumed.status is InboxStatus.CONSUMED
        assert consumed.inbox_result_id == first.inbox_result_id
        assert consumed.received_at == _T1
        assert consumed.consumed_at == _T2
        # Consuming a standalone result still invents no dispatch row.
        assert _outbox_count(path, _PROJ, "lk:standalone") == 0
        assert _inbox_count(path, _PROJ, "lk:standalone") == 1

    def test_standalone_replay_and_conflict(self, tmp_path) -> None:
        path = tmp_path / "standalone2.sqlite"  # noqa: F841
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as uow:
            first = uow.inbox_repository.record_result(
                _PROJ, "lk:standalone", _SHA_B, _T1
            )
            assert (
                uow.inbox_repository.record_result(_PROJ, "lk:standalone", _SHA_B, _T2)
                == first
            )
            with pytest.raises(IdempotencyConflictError):
                uow.inbox_repository.record_result(
                    _PROJ, "lk:standalone", _SHA_A, _T2
                )


# ---------------------------------------------------------------------------
# Historical rows: preserved as evidence, adopted verbatim on write
# ---------------------------------------------------------------------------


class TestHistoricalPreservation:
    def test_historical_paired_row_adopted_verbatim_on_consume(
        self, tmp_path
    ) -> None:
        path = tmp_path / "adopt.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as uow:
            hist = uow.inbox_repository.record_result(_PROJ, "lk:hist", _SHA_A, _T0)
        _enqueue(factory, "lk:hist")

        # Pre-consolidation read still honours the historical row.
        with factory() as uow:
            assert uow.inbox_repository.get_result(_PROJ, "lk:hist") == hist

        with factory() as uow:
            consumed = uow.inbox_repository.mark_consumed(_PROJ, "lk:hist", _T2)
        assert consumed.inbox_result_id == hist.inbox_result_id
        assert consumed.status is InboxStatus.CONSUMED
        assert consumed.received_at == _T0
        assert consumed.consumed_at == _T2

        # Evidence row untouched (still RECEIVED); live state consolidated.
        assert _inbox_rows(path) == [
            (_PROJ, hist.inbox_result_id, "lk:hist", _SHA_A, "received",
             _T0.isoformat(timespec="microseconds"), None)
        ]
        assert _outbox_result_cols(path, _PROJ, "lk:hist") == (
            _SHA_A,
            _T0.isoformat(timespec="microseconds"),
            _T2.isoformat(timespec="microseconds"),
        )
        with factory() as uow:
            live = uow.inbox_repository.get_result(_PROJ, "lk:hist")
            assert live is not None and live.status is InboxStatus.CONSUMED

    def test_consumed_state_survives_factory_restart(self, tmp_path) -> None:
        path = tmp_path / "restart.sqlite"
        config = {"backend": "sqlite", "path": str(path)}
        factory = build_unit_of_work_factory(config)
        with factory() as uow:
            hist = uow.inbox_repository.record_result(_PROJ, "lk:hist", _SHA_A, _T0)
        _enqueue(factory, "lk:hist")
        with factory() as uow:
            uow.inbox_repository.mark_consumed(_PROJ, "lk:hist", _T2)

        restarted = build_unit_of_work_factory(config)
        with restarted() as uow:
            live = uow.inbox_repository.get_result(_PROJ, "lk:hist")
            assert live is not None
            assert live.status is InboxStatus.CONSUMED
            assert live.inbox_result_id == hist.inbox_result_id
            assert uow.inbox_repository.was_processed(_PROJ, "lk:hist") is True


# ---------------------------------------------------------------------------
# End to end: dispatch -> consume -> restart without duplicate effects
# ---------------------------------------------------------------------------


class TestEndToEndNoDuplicateEffects:
    def test_dispatch_consume_restart_has_no_duplicate_effects(
        self, tmp_path
    ) -> None:
        path = tmp_path / "e2e.sqlite"
        config = {"backend": "sqlite", "path": str(path)}
        factory = build_unit_of_work_factory(config)
        _enqueue(factory, "lk:e2e")

        handler = _FixedResultHandler(_SHA_A)
        with factory() as uow:
            dispatcher = OutboxDispatcher(
                outbox=uow.outbox_repository,
                inbox=uow.inbox_repository,
                handler=handler,
                clock=lambda: _T1,
            )
            outcomes = dispatcher.dispatch_pending(_PROJ, limit=10)
        assert len(outcomes) == 1
        assert outcomes[0].kind is DispatchOutcomeKind.DISPATCHED
        assert handler.calls == 1
        # Single authority: dispatch wrote no legacy inbox row.
        assert _inbox_count(path, _PROJ, "lk:e2e") == 0

        semantic = _CountingSemantic()
        with factory() as uow:
            consumer = InboxConsumer(
                inbox=uow.inbox_repository, handler=semantic, clock=lambda: _T2
            )
            outcome = consumer.consume(_PROJ, "lk:e2e")
        assert outcome.kind is ConsumeOutcomeKind.CONSUMED
        assert semantic.calls == 1

        # Restart on the same file: consumed replay applies no effect.
        restarted = build_unit_of_work_factory(config)
        semantic2 = _CountingSemantic()
        with restarted() as uow:
            consumer = InboxConsumer(
                inbox=uow.inbox_repository, handler=semantic2, clock=lambda: _T3
            )
            outcome = consumer.consume(_PROJ, "lk:e2e")
        assert outcome.kind is ConsumeOutcomeKind.SKIPPED_ALREADY_CONSUMED
        assert semantic2.calls == 0

        # Nothing left dispatched to recover.
        handler2 = _FixedResultHandler(_SHA_A)
        with restarted() as uow:
            recovery = OutboxDispatcher(
                outbox=uow.outbox_repository,
                inbox=uow.inbox_repository,
                handler=handler2,
                clock=lambda: _T3,
            ).recover_dispatched(_PROJ)
        assert recovery.recovered_completed == ()
        assert recovery.re_dispatched == ()
        assert recovery.still_dispatched == ()
        assert handler2.calls == 0

    def test_crash_after_receipt_before_ack_recovers_without_redispatch(
        self, tmp_path
    ) -> None:
        path = tmp_path / "crash.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _enqueue(factory, "lk:crash")

        # Crash split: claim commits, receipt commits, ack never runs.
        with factory() as uow:
            claimed = uow.outbox_repository.claim_pending(_PROJ, limit=1, claimed_at=_T0)
            assert len(claimed) == 1
        with factory() as uow:
            uow.inbox_repository.record_result(_PROJ, "lk:crash", _SHA_A, _T1)

        handler = _FixedResultHandler(_SHA_A)
        with factory() as uow:
            recovery = OutboxDispatcher(
                outbox=uow.outbox_repository,
                inbox=uow.inbox_repository,
                handler=handler,
                clock=lambda: _T2,
            ).recover_dispatched(_PROJ)
        assert len(recovery.recovered_completed) == 1
        assert recovery.re_dispatched == ()
        assert handler.calls == 0  # short-circuited on the consolidated receipt
        assert _inbox_count(path, _PROJ, "lk:crash") == 0
        with factory() as uow:
            msg = uow.outbox_repository.find_by_logical_key(_PROJ, "lk:crash")
            assert msg is not None and msg.status is OutboxStatus.COMPLETED

    def test_failed_dispatch_writes_no_result(self, tmp_path) -> None:
        path = tmp_path / "failed.sqlite"  # noqa: F841
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        _enqueue(factory, "lk:fail")
        handler = _FailingHandler()
        with factory() as uow:
            outcomes = OutboxDispatcher(
                outbox=uow.outbox_repository,
                inbox=uow.inbox_repository,
                handler=handler,
                clock=lambda: _T1,
            ).dispatch_pending(_PROJ, limit=10)
        assert len(outcomes) == 1
        assert outcomes[0].kind is DispatchOutcomeKind.FAILED
        assert handler.calls == 1
        with factory() as uow:
            assert uow.inbox_repository.get_result(_PROJ, "lk:fail") is None
            assert uow.inbox_repository.was_processed(_PROJ, "lk:fail") is False


# ---------------------------------------------------------------------------
# Migration-3 shape keeps the constraint-integrity preflight honest
# ---------------------------------------------------------------------------


class TestV3ConstraintPreflight:
    def test_unique_loss_on_widened_outbox_still_rejected(self, tmp_path) -> None:
        from app.protocol_workflow.storage.sqlite import (
            SqliteStorageConfigurationError,
        )

        path = tmp_path / "owned3.sqlite"
        factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
        with factory() as uow:
            uow.outbox_repository.enqueue(
                _PROJ, _RUN, SideEffectKind.EXPORT, "lk:1", _PAYLOAD, _T0
            )
        target = tmp_path / "nounique3.sqlite"
        shutil.copy2(path, target)
        conn = sqlite3.connect(str(target))
        try:
            conn.execute("ALTER TABLE outbox_message RENAME TO outbox_old")
            conn.execute(
                "CREATE TABLE outbox_message ("
                "project_id TEXT NOT NULL, outbox_message_id TEXT NOT NULL, "
                "workflow_run_id TEXT NOT NULL, side_effect_kind TEXT NOT NULL, "
                "logical_key TEXT NOT NULL, payload_sha256 TEXT NOT NULL, "
                "status TEXT NOT NULL, created_at TEXT NOT NULL, "
                "dispatched_at TEXT, completed_at TEXT, "
                "attempt INTEGER NOT NULL DEFAULT 0, error_detail TEXT, "
                "result_sha256 TEXT, result_received_at TEXT, "
                "result_consumed_at TEXT, "
                "PRIMARY KEY (project_id, outbox_message_id))"
            )
            conn.execute("INSERT INTO outbox_message SELECT * FROM outbox_old")
            conn.execute("DROP TABLE outbox_old")
            conn.commit()
        finally:
            conn.close()
        before = hashlib.sha256(target.read_bytes()).hexdigest()
        with pytest.raises(SqliteStorageConfigurationError):
            build_unit_of_work_factory({"backend": "sqlite", "path": str(target)})
        assert hashlib.sha256(target.read_bytes()).hexdigest() == before
