"""Durable dispatch coordination against real SQLite (Task 1R.4).

These tests prove the committed-operation dispatch runtime end to end:

* **Durability before physical dispatch** — the coordinator wired through
  ``build_committed_reservation_repository_factory`` commits every
  reservation step (RESERVED claim, RUNNING transition, terminal outcome) as
  its own durable transaction, so a synthetic child process that dies at any
  point leaves a truthful recoverable record instead of losing the dispatch.
* **No takeover of active ownership** — a concurrent caller that observes a
  live RESERVED or RUNNING owner fails closed and never turns it into
  ``FAILED``; only an abandoned orphan shell is closed as a zero-attempt
  recovery, and an explicit retry is the only route to attempt ``N+1``.
* **Append-only history** — orphan recovery and explicit retries never
  delete or rewrite earlier attempts.

Crash checks use synthetic child processes only (``os._exit`` after the
physical side-effect boundary), never an in-process failure shim, so the
durability claims survive real process death.  No provider calls are made.
"""

from __future__ import annotations

import os
import multiprocessing
import sqlite3
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from app.protocol_workflow.ports.repositories import UnknownOutcomeConflictError
from app.protocol_workflow.runtime.reservations import ReservationCoordinator
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import (
    ExecutionTerminalState,
    ReservationStatus,
)
from test_execution_reservations import (
    _FakeTransport,
    _node_contract,
    _payload_a,
    _sha,
    _PROJ,
    _T0,
    _T1,
    _T2,
)

_T3 = datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repository_factory(path: Path):
    return build_committed_reservation_repository_factory(
        {"backend": "sqlite", "path": str(path)}
    )


def _row_from_independent_connection(path: Path, reservation_id: str):
    """Read one reservation row through a fresh connection, as a crash or a
    concurrent process would see the durable state."""
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT status, transport_attempts FROM execution_reservation "
            "WHERE execution_reservation_id=?",
            (reservation_id,),
        ).fetchone()


def _wait_for_durable_row(
    path: Path, reservation_id: str, expected: tuple, *, timeout: float = 10.0
) -> None:
    """Poll until the committed row is visible to an independent connection."""
    deadline = datetime.now(tz=timezone.utc).timestamp() + timeout
    last = None
    while datetime.now(tz=timezone.utc).timestamp() < deadline:
        last = _row_from_independent_connection(path, reservation_id)
        if last == expected:
            return
        threading.Event().wait(0.02)
    pytest.fail(
        f"durable row never became {expected!r}; last observation {last!r}"
    )


class _CountingTransport:
    """Transport wrapper that counts physical dispatches across handles."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.dispatch_count = 0

    def preflight(self, **kwargs: Any) -> Optional[str]:
        return self._inner.preflight(**kwargs)

    def dispatch(self, **kwargs: Any) -> Optional[dict[str, Any]]:
        self.dispatch_count += 1
        return self._inner.dispatch(**kwargs)


def _child_env() -> dict:
    """Environment for synthetic crash children: inherit the runner env and
    make the test helper module importable."""
    env = dict(os.environ)
    helper_dir = str(Path(__file__).resolve().parent)
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + os.pathsep + helper_dir
    return env


# Child programs are separate processes on purpose: the crash must bypass all
# in-process cleanup to prove durability of the committed rows.

_CRASH_BEFORE_RUNNING_CHILD = """
import os, sys
from app.protocol_workflow.runtime.reservations import ReservationCoordinator
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory,
)
from test_execution_reservations import (
    _node_contract, _payload_a, _PROJ, _T0,
)


class CrashBeforeRunningTransport:
    def preflight(self, *, project_id, reservation, payload):
        # The RESERVED claim is already committed at this boundary; die
        # before the RUNNING transition and any physical dispatch.
        os._exit(70)

    def dispatch(self, **kwargs):
        raise AssertionError("dispatch must never run")


factory = build_committed_reservation_repository_factory(
    {"backend": "sqlite", "path": sys.argv[1]}
)
with factory() as repository:
    ReservationCoordinator(repository).reserve_or_reuse(
        project_id=_PROJ,
        node_contract=_node_contract(),
        input_payload=_payload_a(),
        now=_T0,
        transport=CrashBeforeRunningTransport(),
    )
os._exit(0)  # unreachable
"""

_CRASH_AFTER_ACCEPT_CHILD = """
import os, sys
from app.protocol_workflow.runtime.reservations import ReservationCoordinator
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory,
)
from test_execution_reservations import (
    _node_contract, _payload_a, _PROJ, _T0,
)


class CrashAfterAcceptTransport:
    def preflight(self, **kwargs):
        return None

    def dispatch(self, *, reservation, **kwargs):
        # The provider accepted the call (physical side effect recorded),
        # then the process dies before any receipt can be persisted.
        open(sys.argv[2], "w").write("accepted")
        os._exit(71)


factory = build_committed_reservation_repository_factory(
    {"backend": "sqlite", "path": sys.argv[1]}
)
with factory() as repository:
    ReservationCoordinator(repository).reserve_or_reuse(
        project_id=_PROJ,
        node_contract=_node_contract(),
        input_payload=_payload_a(),
        now=_T0,
        transport=CrashAfterAcceptTransport(),
    )
os._exit(0)  # unreachable
"""


def _run_crash_child(script: str, db_path: Path, marker_path: Path):
    return subprocess.run(
        [sys.executable, "-c", script, str(db_path), str(marker_path)],
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )


# ---------------------------------------------------------------------------
# 1. Crash before the RUNNING transition: durable orphan shell
# ---------------------------------------------------------------------------


def test_child_crash_before_running_leaves_durable_orphan_shell(tmp_path):
    db_path = tmp_path / "crash-before.sqlite"
    result = _run_crash_child(
        _CRASH_BEFORE_RUNNING_CHILD, db_path, tmp_path / "unused.marker"
    )
    assert result.returncode == 70, result.stderr
    contract = _node_contract()

    # The process is dead, yet its RESERVED claim is durably queryable with
    # zero transport attempts: dispatch provably never started.
    fresh_factory = _repository_factory(db_path)
    with fresh_factory() as repository:
        shell = repository.find_by_logical_call(
            _PROJ, contract.logical_call_id, contract.idempotency_key
        )
        assert shell is not None
        assert shell.status is ReservationStatus.RESERVED
        assert shell.transport_attempts == 0
    row = _row_from_independent_connection(db_path, shell.execution_reservation_id)
    assert row == ("reserved", 0)

    # A new dispatch attempt in the survivor process closes the orphan shell
    # as a zero-attempt FAILED recovery (explicit orphan recovery context:
    # no live owner exists in this process) and never dispatches it.
    transport = _CountingTransport(_FakeTransport())
    with fresh_factory() as repository:
        outcome = ReservationCoordinator(repository).reserve_or_reuse(
            project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
            now=_T1, transport=transport,
        )
        assert outcome.status is ReservationStatus.FAILED
        assert outcome.error_code == "dispatch_not_started_recovery"
        assert outcome.reservation.transport_attempts == 0
        assert transport.dispatch_count == 0
        attempts = repository.list_attempts(_PROJ, contract.logical_call_id)
        assert len(attempts) == 1
        assert attempts[0].status is ReservationStatus.FAILED

    # A new attempt requires the explicit, auditable retry decision; it
    # appends attempt 2 without rewriting the disposed shell.
    retry_transport = _CountingTransport(_FakeTransport())
    with fresh_factory() as repository:
        coordinator = ReservationCoordinator(repository)
        retried = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T2,
            transport=retry_transport,
            retry_reason="recovery after crashed dispatch process",
            retry_decision_id="retry-decision:1r4-crash-before",
        )
        assert retried.attempt == 2
        assert retried.status is ReservationStatus.COMPLETED
        assert retry_transport.dispatch_count == 1
        attempts = repository.list_attempts(_PROJ, contract.logical_call_id)
        assert [reservation.attempt for reservation in attempts] == [1, 2]
        assert attempts[0].status is ReservationStatus.FAILED


def test_child_crash_after_dispatch_acceptance_keeps_running_claim(tmp_path):
    db_path = tmp_path / "crash-after.sqlite"
    marker_path = tmp_path / "provider-accepted.marker"
    result = _run_crash_child(_CRASH_AFTER_ACCEPT_CHILD, db_path, marker_path)
    assert result.returncode == 71, result.stderr
    assert marker_path.read_text() == "accepted"
    contract = _node_contract()

    fresh_factory = _repository_factory(db_path)
    with fresh_factory() as repository:
        crashed = repository.find_by_logical_call(
            _PROJ, contract.logical_call_id, contract.idempotency_key
        )
        assert crashed is not None
        assert crashed.execution_reservation_id is not None
    # The RUNNING claim with its transport attempt was durable before the
    # physical dispatch, so process death cannot erase the accepted call.
    assert _row_from_independent_connection(
        db_path, crashed.execution_reservation_id
    ) == ("running", 1)

    # Restart must not redispatch over the un-resolved RUNNING claim.
    transport = _CountingTransport(_FakeTransport())
    with fresh_factory() as repository:
        coordinator = ReservationCoordinator(repository)
        with pytest.raises(UnknownOutcomeConflictError):
            coordinator.reserve_or_reuse(
                project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
                now=_T1, transport=transport,
            )
        assert transport.dispatch_count == 0
        unresolved = coordinator.find_unresolved(_PROJ)
        assert [row.execution_reservation_id for row in unresolved] == [
            crashed.execution_reservation_id
        ]

        # Same-session reconciliation completes the crashed attempt from its
        # recovered receipt without a new physical dispatch.
        recovered = coordinator.recover_unknown(
            project_id=_PROJ,
            reservation_id=crashed.execution_reservation_id,
            recovered_output_receipt={
                "output_sha256": _sha(910),
                "provider_session_id": crashed.provider_session_id,
            },
            now=_T2,
        )
        assert recovered.status is ReservationStatus.COMPLETED
        assert recovered.attempt == crashed.attempt

    # After reconciliation the same logical call reuses the output.
    with fresh_factory() as repository:
        reused = ReservationCoordinator(repository).reserve_or_reuse(
            project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
            now=_T3, transport=transport,
        )
        assert reused.terminal_state is ExecutionTerminalState.COMPLETED
        assert reused.reservation.execution_reservation_id == (
            crashed.execution_reservation_id
        )
    assert transport.dispatch_count == 0


# ---------------------------------------------------------------------------
# 2. Concurrent live owners are never taken over
# ---------------------------------------------------------------------------


def _separate_process_owner(db_path, entered, release, result):
    class Transport:
        def preflight(self, **kwargs):
            entered.set()
            assert release.wait(30)
            return None

        def dispatch(self, *, reservation, **kwargs):
            return {
                "output_sha256": _sha(7),
                "provider_session_id": f"sess:{reservation.execution_reservation_id}",
            }

    try:
        with _repository_factory(db_path)() as repository:
            outcome = ReservationCoordinator(repository).reserve_or_reuse(
                project_id=_PROJ, node_contract=_node_contract(),
                input_payload=_payload_a(), now=_T0, transport=Transport(),
            )
            result.put(outcome.status.value)
    except BaseException as exc:
        result.put(repr(exc))
        raise


def test_separate_process_caller_preserves_live_reserved_owner(tmp_path):
    db_path = tmp_path / "cross-process.sqlite"
    factory = _repository_factory(db_path)
    context = multiprocessing.get_context("spawn")
    entered, release = context.Event(), context.Event()
    result = context.Queue()
    owner = context.Process(
        target=_separate_process_owner, args=(db_path, entered, release, result),
    )
    owner.start()
    try:
        assert entered.wait(30)
        contract = _node_contract()
        with factory() as repository:
            shell = repository.find_by_logical_call(
                _PROJ, contract.logical_call_id, contract.idempotency_key,
            )
            assert shell.status is ReservationStatus.RESERVED
            transport = _CountingTransport(_FakeTransport())
            with pytest.raises(UnknownOutcomeConflictError):
                ReservationCoordinator(repository).reserve_or_reuse(
                    project_id=_PROJ, node_contract=contract,
                    input_payload=_payload_a(), now=_T1, transport=transport,
                )
            assert transport.dispatch_count == 0
            assert repository.get(
                _PROJ, shell.execution_reservation_id,
            ).status is ReservationStatus.RESERVED
    finally:
        release.set()
        owner.join(30)
    assert owner.exitcode == 0
    assert result.get(timeout=5) == "completed"


def test_concurrent_orphan_recovery_converges_without_repository_error(tmp_path):
    db_path = tmp_path / "orphan-race.sqlite"
    crashed = _run_crash_child(
        _CRASH_BEFORE_RUNNING_CHILD, db_path, tmp_path / "unused.marker",
    )
    assert crashed.returncode == 70
    factory = _repository_factory(db_path)
    probed = threading.Barrier(2)
    outcomes, errors = [], []

    def recover():
        try:
            with factory() as repository:
                probe = repository.has_live_dispatch

                def synchronized_probe(*args):
                    active = probe(*args)
                    probed.wait(timeout=10)
                    return active

                repository.has_live_dispatch = synchronized_probe
                transport = _CountingTransport(_FakeTransport())
                outcome = ReservationCoordinator(repository).reserve_or_reuse(
                    project_id=_PROJ, node_contract=_node_contract(),
                    input_payload=_payload_a(), now=_T1, transport=transport,
                )
                assert transport.dispatch_count == 0
                outcomes.append(outcome.status)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=recover) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert outcomes == [ReservationStatus.FAILED, ReservationStatus.FAILED]


def test_concurrent_caller_never_disposes_live_reserved_owner(tmp_path):
    db_path = tmp_path / "live-reserved.sqlite"
    factory = _repository_factory(db_path)
    contract = _node_contract()
    owner_entered_preflight = threading.Event()
    release_owner = threading.Event()
    owner_result: list[Any] = []
    owner_error: list[BaseException] = []

    class LiveOwnerTransport:
        def preflight(self, *, project_id, reservation, payload):
            owner_entered_preflight.set()
            assert release_owner.wait(timeout=30)
            return None

        def dispatch(self, *, reservation, **kwargs):
            return {
                "output_sha256": _sha(7),
                "provider_session_id": f"sess:{reservation.execution_reservation_id}",
            }

    def run_owner() -> None:
        try:
            with factory() as repository:
                owner_result.append(
                    ReservationCoordinator(repository).reserve_or_reuse(
                        project_id=_PROJ, node_contract=contract,
                        input_payload=_payload_a(), now=_T0,
                        transport=LiveOwnerTransport(),
                    )
                )
        except BaseException as exc:  # noqa: BLE001
            owner_error.append(exc)

    owner_thread = threading.Thread(target=run_owner)
    owner_thread.start()
    assert owner_entered_preflight.wait(timeout=30)
    # The owner's shell is durably committed while it is still live.
    with factory() as repository:
        shell = repository.find_by_logical_call(
            _PROJ, contract.logical_call_id, contract.idempotency_key
        )
        assert shell is not None
    _wait_for_durable_row(db_path, shell.execution_reservation_id, ("reserved", 0))

    # A concurrent caller fail-closes on the live owner...
    with factory() as repository:
        with pytest.raises(UnknownOutcomeConflictError):
            ReservationCoordinator(repository).reserve_or_reuse(
                project_id=_PROJ, node_contract=contract,
                input_payload=_payload_a(), now=_T1,
                transport=_CountingTransport(_FakeTransport()),
            )
    # ...and the live owner is untouched: still RESERVED, zero attempts,
    # never turned into FAILED by the second caller.
    assert _row_from_independent_connection(
        db_path, shell.execution_reservation_id
    ) == ("reserved", 0)

    release_owner.set()
    owner_thread.join(timeout=30)
    assert owner_error == []
    assert owner_result[0].status is ReservationStatus.COMPLETED

    # After the owner resolves, the second caller converges to its result.
    reuse_transport = _CountingTransport(_FakeTransport())
    with factory() as repository:
        reused = ReservationCoordinator(repository).reserve_or_reuse(
            project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
            now=_T2, transport=reuse_transport,
        )
        assert reused.reservation.execution_reservation_id == (
            owner_result[0].reservation.execution_reservation_id
        )
    assert reuse_transport.dispatch_count == 0


def test_concurrent_caller_never_takes_over_live_running_owner(tmp_path):
    db_path = tmp_path / "live-running.sqlite"
    factory = _repository_factory(db_path)
    contract = _node_contract()
    owner_in_dispatch = threading.Event()
    release_owner = threading.Event()
    owner_result: list[Any] = []
    owner_error: list[BaseException] = []

    class LiveRunningOwnerTransport:
        def preflight(self, **kwargs):
            return None

        def dispatch(self, *, reservation, **kwargs):
            owner_in_dispatch.set()
            assert release_owner.wait(timeout=30)
            return {
                "output_sha256": _sha(8),
                "provider_session_id": f"sess:{reservation.execution_reservation_id}",
            }

    def run_owner() -> None:
        try:
            with factory() as repository:
                owner_result.append(
                    ReservationCoordinator(repository).reserve_or_reuse(
                        project_id=_PROJ, node_contract=contract,
                        input_payload=_payload_a(), now=_T0,
                        transport=LiveRunningOwnerTransport(),
                    )
                )
        except BaseException as exc:  # noqa: BLE001
            owner_error.append(exc)

    owner_thread = threading.Thread(target=run_owner)
    owner_thread.start()
    assert owner_in_dispatch.wait(timeout=30)
    with factory() as repository:
        running = repository.find_by_logical_call(
            _PROJ, contract.logical_call_id, contract.idempotency_key
        )
        assert running is not None
    _wait_for_durable_row(db_path, running.execution_reservation_id, ("running", 1))

    with factory() as repository:
        with pytest.raises(UnknownOutcomeConflictError):
            ReservationCoordinator(repository).reserve_or_reuse(
                project_id=_PROJ, node_contract=contract,
                input_payload=_payload_a(), now=_T1,
                transport=_CountingTransport(_FakeTransport()),
            )
    # The in-flight dispatch keeps ownership: RUNNING with its attempt.
    assert _row_from_independent_connection(
        db_path, running.execution_reservation_id
    ) == ("running", 1)

    release_owner.set()
    owner_thread.join(timeout=30)
    assert owner_error == []
    assert owner_result[0].status is ReservationStatus.COMPLETED


# ---------------------------------------------------------------------------
# 3. Explicit retry history over real SQLite
# ---------------------------------------------------------------------------


def test_unknown_outcome_explicit_retry_is_durable_and_append_only(tmp_path):
    db_path = tmp_path / "explicit-retry.sqlite"
    factory = _repository_factory(db_path)
    contract = _node_contract()

    with factory() as repository:
        outcome = ReservationCoordinator(repository).reserve_or_reuse(
            project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
            now=_T0,
            transport=_CountingTransport(
                _FakeTransport(raise_on_dispatch=TimeoutError("timeout"))
            ),
        )
    assert outcome.terminal_state is ExecutionTerminalState.UNKNOWN_OUTCOME
    attempt1_id = outcome.reservation.execution_reservation_id
    assert outcome.reservation.attempt == 1

    # Restart (fresh handle): the unknown outcome blocks automatic
    # redispatch fail-closed.
    retry_transport = _CountingTransport(_FakeTransport())
    with factory() as repository:
        coordinator = ReservationCoordinator(repository)
        with pytest.raises(UnknownOutcomeConflictError):
            coordinator.reserve_or_reuse(
                project_id=_PROJ, node_contract=contract,
                input_payload=_payload_a(), now=_T1, transport=retry_transport,
            )
        assert retry_transport.dispatch_count == 0

        # Only the explicit, auditable decision creates attempt 2.
        retried = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=retry_transport,
            retry_reason="explicit retry after unknown outcome",
            retry_decision_id="retry-decision:1r4-001",
        )
        assert retried.attempt == 2
        assert retried.status is ReservationStatus.COMPLETED
        assert retried.execution_reservation_id != attempt1_id
        assert retry_transport.dispatch_count == 1

    # Durability: a further restart observes the full append-only history,
    # with attempt 1 immutable under its original idempotency key.
    with factory() as repository:
        coordinator = ReservationCoordinator(repository)
        attempts = repository.list_attempts(_PROJ, contract.logical_call_id)
        assert [row.attempt for row in attempts] == [1, 2]
        first = repository.get(_PROJ, attempt1_id)
        assert first is not None
        assert first.status is ReservationStatus.UNKNOWN_OUTCOME
        assert first.idempotency_key == contract.idempotency_key
        assert first.transport_attempts == 1

        # Repeating the same decision identity is idempotent: no new
        # attempt, no new dispatch.
        replay_transport = _CountingTransport(_FakeTransport())
        again = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T2,
            transport=replay_transport,
            retry_reason="explicit retry after unknown outcome",
            retry_decision_id="retry-decision:1r4-001",
        )
        assert again.execution_reservation_id == retried.execution_reservation_id
        assert again.attempt == 2
        assert replay_transport.dispatch_count == 0
        assert len(repository.list_attempts(_PROJ, contract.logical_call_id)) == 2

        # The original key stays bound to the unresolved attempt 1: it is
        # never silently promoted to a retryable or reusable outcome.
        with pytest.raises(UnknownOutcomeConflictError):
            coordinator.reserve_or_reuse(
                project_id=_PROJ, node_contract=contract,
                input_payload=_payload_a(), now=_T2, transport=replay_transport,
            )
        assert replay_transport.dispatch_count == 0
