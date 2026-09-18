"""Independent reviewer probe — Task 1R.4 storage consolidation edge cases.

Covers scenarios the committed suite does not:
  P1  consumed-history adoption (legacy CONSUMED row + late outbox row)
  P2  adoption replay stability (second same-sha replay rewrites nothing)
  P3  duplicate delivery through the dispatcher after consumption
  P4  cross-project pairing isolation (same logical_key, different project)
  P5  migration 3 repeatability on a real v2 file with consumed history

Synthetic temp DBs only; no model calls; evidence per conference scope.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.protocol_workflow.events.inbox import ConsumeOutcomeKind, InboxConsumer
from app.protocol_workflow.events.outbox import (
    DispatchOutcomeKind,
    DispatchResult,
    OutboxDispatcher,
)
from app.protocol_workflow.ports.repositories import (
    InboxStatus,
    RepositoryStateTransitionError,
)
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
from packages.contracts.workbench_contracts.protocol_v3 import SideEffectKind

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
_T3 = datetime(2026, 1, 4, tzinfo=timezone.utc)
_SHA_A = "a" * 64
_PAYLOAD = "p" * 64

RESULTS: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, evidence: str) -> None:
    RESULTS.append((name, "PASS" if cond else "FAIL", evidence))


def raw(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def outbox_cols(path: Path, proj: str, key: str):
    conn = raw(path)
    try:
        row = conn.execute(
            "SELECT result_sha256, result_received_at, result_consumed_at"
            " FROM outbox_message WHERE project_id=? AND logical_key=?",
            (proj, key),
        ).fetchone()
        return tuple(row) if row else None
    finally:
        conn.close()


def inbox_rows(path: Path, proj: str, key: str):
    conn = raw(path)
    try:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT inbox_result_id, result_sha256, status, received_at,"
                " consumed_at FROM inbox_result WHERE project_id=? AND logical_key=?",
                (proj, key),
            ).fetchall()
        ]
    finally:
        conn.close()


def enqueue(factory, proj: str, key: str) -> None:
    with factory() as uow:
        uow.outbox_repository.enqueue(
            proj, "run:probe", SideEffectKind.EXPORT, key, _PAYLOAD, _T0
        )


class FixedHandler:
    def __init__(self, sha: str) -> None:
        self.calls = 0
        self.sha = sha

    def __call__(self, message):
        self.calls += 1
        return DispatchResult(result_sha256=self.sha)


class CountingSemantic:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, result):
        self.calls += 1


# --- P1 + P2: consumed-history adoption and replay stability --------------
def probe_consumed_history(tmp: Path) -> None:
    path = tmp / "p1_consumed_history.sqlite"
    config = {"backend": "sqlite", "path": str(path)}
    factory = build_unit_of_work_factory(config)
    # Pre-consolidation history: result received then consumed, no outbox row.
    with factory() as uow:
        hist = uow.inbox_repository.record_result("projA", "lk:ch", _SHA_A, _T0)
        uow.inbox_repository.mark_consumed("projA", "lk:ch", _T1)
    enqueue(factory, "projA", "lk:ch")

    # Same-sha replay adopts consumed history verbatim.
    with factory() as uow:
        replay = uow.inbox_repository.record_result("projA", "lk:ch", _SHA_A, _T3)
    check(
        "P1a consumed history adopted as CONSUMED",
        replay.status is InboxStatus.CONSUMED
        and replay.consumed_at == _T1
        and replay.received_at == _T0
        and replay.inbox_result_id == hist.inbox_result_id,
        f"status={replay.status} received_at={replay.received_at} "
        f"consumed_at={replay.consumed_at} id={replay.inbox_result_id}",
    )
    check(
        "P1b evidence row untouched by adoption",
        inbox_rows(path, "projA", "lk:ch")
        == [(hist.inbox_result_id, _SHA_A, "consumed",
             _T0.isoformat(timespec="microseconds"),
             _T1.isoformat(timespec="microseconds"))],
        str(inbox_rows(path, "projA", "lk:ch")),
    )
    check(
        "P1c outbox result columns mirror history verbatim",
        outbox_cols(path, "projA", "lk:ch")
        == (_SHA_A, _T0.isoformat(timespec="microseconds"),
            _T1.isoformat(timespec="microseconds")),
        str(outbox_cols(path, "projA", "lk:ch")),
    )

    # P2: second replay rewrites nothing (timestamps stable across restarts).
    with factory() as uow:
        replay2 = uow.inbox_repository.record_result("projA", "lk:ch", _SHA_A, _T2)
    check(
        "P2 adoption replay idempotent (first receipt wins)",
        replay2 == replay,
        f"first={replay!r} second={replay2!r}",
    )

    # Live consumed state must not accept mark_consumed again.
    with factory() as uow:
        try:
            uow.inbox_repository.mark_consumed("projA", "lk:ch", _T3)
            raised = False
        except RepositoryStateTransitionError:
            raised = True
    check("P2b mark_consumed after adopted CONSUMED fails closed", raised, "raised")

    # Consumer skips the adopted consumed result (no duplicate effect).
    semantic = CountingSemantic()
    with factory() as uow:
        outcome = InboxConsumer(
            inbox=uow.inbox_repository, handler=semantic, clock=lambda: _T3
        ).consume("projA", "lk:ch")
    check(
        "P2c consumer skips adopted consumed history",
        outcome.kind is ConsumeOutcomeKind.SKIPPED_ALREADY_CONSUMED
        and semantic.calls == 0,
        f"kind={outcome.kind} calls={semantic.calls}",
    )


# --- P3: duplicate delivery after consumption ------------------------------
def probe_duplicate_after_consume(tmp: Path) -> None:
    path = tmp / "p3_dup_after_consume.sqlite"
    factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
    enqueue(factory, "projA", "lk:dup")
    handler = FixedHandler(_SHA_A)
    with factory() as uow:
        outcomes = OutboxDispatcher(
            outbox=uow.outbox_repository,
            inbox=uow.inbox_repository,
            handler=handler,
            clock=lambda: _T1,
        ).dispatch_pending("projA", limit=10)
    assert outcomes[0].kind is DispatchOutcomeKind.DISPATCHED
    with factory() as uow:
        InboxConsumer(
            inbox=uow.inbox_repository, handler=CountingSemantic(), clock=lambda: _T2
        ).consume("projA", "lk:dup")

    # Simulate a duplicate delivery window: message back in DISPATCHED
    # (e.g. re-claim from a backup/crash boundary) with result already consumed.
    conn = raw(path)
    try:
        conn.execute(
            "UPDATE outbox_message SET status='dispatched', completed_at=NULL"
            " WHERE project_id='projA' AND logical_key='lk:dup'"
        )
        conn.commit()
    finally:
        conn.close()

    handler2 = FixedHandler(_SHA_A)
    with factory() as uow:
        recovery = OutboxDispatcher(
            outbox=uow.outbox_repository,
            inbox=uow.inbox_repository,
            handler=handler2,
            clock=lambda: _T3,
        ).recover_dispatched("projA")
    check(
        "P3 duplicate delivery after consume: no redispatch, no duplicate effect",
        len(recovery.recovered_completed) == 1
        and handler2.calls == 0
        and len(recovery.re_dispatched) == 0,
        f"recovered={len(recovery.recovered_completed)} calls={handler2.calls}",
    )
    check(
        "P3b consumption marker survives duplicate delivery",
        outbox_cols(path, "projA", "lk:dup")[2]
        == _T2.isoformat(timespec="microseconds"),
        str(outbox_cols(path, "projA", "lk:dup")),
    )


# --- P4: cross-project pairing isolation -----------------------------------
def probe_cross_project(tmp: Path) -> None:
    path = tmp / "p4_cross_project.sqlite"
    factory = build_unit_of_work_factory({"backend": "sqlite", "path": str(path)})
    enqueue(factory, "projA", "lk:shared")

    # Same logical key in another project must NOT pair with projA's outbox row.
    with factory() as uow:
        res_b = uow.inbox_repository.record_result("projB", "lk:shared", _SHA_A, _T1)
    check(
        "P4 cross-project same key records standalone (no invented pairing)",
        res_b.inbox_result_id.startswith("ib-")
        and not res_b.inbox_result_id.startswith("ib-outbox-")
        and outbox_cols(path, "projB", "lk:shared") is None
        and len(inbox_rows(path, "projB", "lk:shared")) == 1,
        f"id={res_b.inbox_result_id} projB_outbox={outbox_cols(path, 'projB', 'lk:shared')}",
    )
    # projA's paired row stays empty; projA receipt still routes to the outbox.
    with factory() as uow:
        res_a = uow.inbox_repository.record_result("projA", "lk:shared", _SHA_A, _T1)
    check(
        "P4b projA receipt still uses paired outbox authority",
        res_a.inbox_result_id.startswith("ib-outbox-")
        and len(inbox_rows(path, "projA", "lk:shared")) == 0,
        f"id={res_a.inbox_result_id}",
    )
    # Cross-project hash conflict must not leak: projB conflict raises, projA unaffected.
    with factory() as uow:
        try:
            uow.inbox_repository.record_result("projB", "lk:shared", "b" * 64, _T2)
            raised = False
        except Exception as exc:  # noqa: BLE001
            raised = type(exc).__name__ == "IdempotencyConflictError"
    check("P4c cross-project hash conflict fails closed in its own project", raised, "")


# --- P5: v2 file with consumed history upgrades repeatably ------------------
def probe_v2_consumed_upgrade(tmp: Path) -> None:
    import app.protocol_workflow.storage.sqlite as adapter

    real_migrations = adapter._MIGRATIONS
    real_latest = adapter.SCHEMA_VERSION_LATEST
    path = tmp / "p5_v2_upgrade.sqlite"
    config = {"backend": "sqlite", "path": str(path)}
    adapter._MIGRATIONS = real_migrations[:2]
    adapter.SCHEMA_VERSION_LATEST = 2
    try:
        v2factory = build_unit_of_work_factory(config)
        with v2factory() as uow:
            hist = uow.inbox_repository.record_result("projA", "lk:v2c", _SHA_A, _T0)
            uow.inbox_repository.mark_consumed("projA", "lk:v2c", _T1)
    finally:
        adapter._MIGRATIONS = real_migrations
        adapter.SCHEMA_VERSION_LATEST = real_latest

    upgraded = build_unit_of_work_factory(config)
    with upgraded() as uow:
        live = uow.inbox_repository.get_result("projA", "lk:v2c")
    check(
        "P5 v2 consumed history survives migration as CONSUMED with original id",
        live is not None
        and live.status is InboxStatus.CONSUMED
        and live.inbox_result_id == hist.inbox_result_id
        and live.consumed_at == _T1,
        f"status={live.status} id={live.inbox_result_id} consumed_at={live.consumed_at}",
    )
    # Repeat bootstrap on the migrated file: no extra effects, idempotent.
    build_unit_of_work_factory(config)
    conn = raw(path)
    try:
        versions = [r[0] for r in conn.execute(
            "SELECT version FROM schema_version ORDER BY rowid").fetchall()]
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    check(
        "P5b repeated bootstrap on migrated file is a no-op with intact history",
        versions == [1, 2, 3] and integrity == "ok"
        and len(inbox_rows(path, "projA", "lk:v2c")) == 1,
        f"versions={versions} integrity={integrity}",
    )


# --- P6: concurrent claim race — one physical dispatch ----------------------
def probe_concurrent_claim(tmp: Path) -> None:
    import threading

    path = tmp / "p6_claim_race.sqlite"
    config = {"backend": "sqlite", "path": str(path)}
    factory = build_unit_of_work_factory(config)
    enqueue(factory, "projA", "lk:race")

    claimed_totals: list = []
    barrier = threading.Barrier(2)

    def claimer() -> None:
        barrier.wait()
        with factory() as uow:
            claimed = uow.outbox_repository.claim_pending(
                "projA", limit=10, claimed_at=_T1
            )
            uow.commit()
            claimed_totals.append(len(claimed))

    threads = [threading.Thread(target=claimer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check(
        "P6 concurrent claims dispatch the pending message exactly once",
        sum(claimed_totals) == 1 and sorted(claimed_totals) == [0, 1],
        f"claimed_per_worker={claimed_totals}",
    )

    # Both workers then run the dispatcher; the loser must not re-dispatch.
    h1, h2 = FixedHandler(_SHA_A), FixedHandler(_SHA_A)
    with factory() as uow:
        OutboxDispatcher(
            outbox=uow.outbox_repository, inbox=uow.inbox_repository,
            handler=h1, clock=lambda: _T2,
        ).recover_dispatched("projA")
    with factory() as uow:
        OutboxDispatcher(
            outbox=uow.outbox_repository, inbox=uow.inbox_repository,
            handler=h2, clock=lambda: _T2,
        ).recover_dispatched("projA")
    with factory() as uow:
        result = uow.inbox_repository.get_result("projA", "lk:race")
    check(
        "P6b post-race recovery converges to one receipt, no duplicate result",
        result is not None
        and result.result_sha256 == _SHA_A
        and len(inbox_rows(path, "projA", "lk:race")) == 0,
        f"result={result.result_sha256 if result else None}",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="1r4_probe_") as td:
        tmp = Path(td)
        probe_consumed_history(tmp)
        probe_duplicate_after_consume(tmp)
        probe_cross_project(tmp)
        probe_v2_consumed_upgrade(tmp)
        probe_concurrent_claim(tmp)
    failed = 0
    print(f"{'probe':<58} {'result':<6} evidence")
    for name, result, evidence in RESULTS:
        if result == "FAIL":
            failed += 1
        print(f"{name:<58} {result:<6} {evidence}")
    print(f"\ntotal={len(RESULTS)} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
