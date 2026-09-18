"""Reservation recovery against actual SQLite, without provider calls."""

import sqlite3

import pytest

from app.protocol_workflow.ports.repositories import UnknownOutcomeConflictError
from app.protocol_workflow.runtime.reservations import ReservationCoordinator
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory,
    build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import ExecutionTerminalState
from test_execution_reservations import (
    _FakeTransport, _node_contract, _payload_a, _PROJ, _T0, _T1, _T2, _sha,
)


def test_sqlite_unknown_recovery_restart_and_completed_reuse(tmp_path):
    config = {"backend": "sqlite", "path": str(tmp_path / "reservation.sqlite")}
    factory = build_unit_of_work_factory(config)
    contract = _node_contract()
    transport = _FakeTransport(raise_on_dispatch=TimeoutError("synthetic"))
    with factory() as uow:
        outcome = ReservationCoordinator(uow.reservation_repository).reserve_or_reuse(
            project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
            now=_T0, transport=transport,
        )
    assert outcome.terminal_state is ExecutionTerminalState.UNKNOWN_OUTCOME
    assert transport.dispatch_count == 1
    unused = _FakeTransport()
    restarted = build_unit_of_work_factory(config)
    with restarted() as uow:
        coordinator = ReservationCoordinator(uow.reservation_repository)
        with pytest.raises(UnknownOutcomeConflictError):
            coordinator.reserve_or_reuse(
                project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
                now=_T1, transport=unused,
            )
        recovered = coordinator.recover_unknown(
            project_id=_PROJ, reservation_id=outcome.reservation.execution_reservation_id,
            recovered_output_receipt={
                "output_sha256": _sha(900),
                "provider_session_id": outcome.reservation.provider_session_id,
            }, now=_T1,
        )
    with restarted() as uow:
        reused = ReservationCoordinator(uow.reservation_repository).reserve_or_reuse(
            project_id=_PROJ, node_contract=contract, input_payload=_payload_a(),
            now=_T2, transport=unused,
        )
        assert len(uow.reservation_repository.list_attempts(_PROJ, contract.logical_call_id)) == 1
    assert reused.reservation == recovered
    assert reused.terminal_state is ExecutionTerminalState.COMPLETED
    assert unused.dispatch_count == 0


def test_sqlite_claim_is_durable_before_physical_dispatch(tmp_path):
    """The dispatch runtime's committed-operation entrypoint makes each
    reservation step durable before the transport runs: at the moment of
    physical dispatch an independent connection must already observe the
    RUNNING claim with its first transport attempt."""
    path = tmp_path / "before-dispatch.sqlite"
    repository_factory = build_committed_reservation_repository_factory(
        {"backend": "sqlite", "path": str(path)}
    )
    observed = []

    def observe_from_independent_connection(reservation):
        with sqlite3.connect(path) as conn:
            observed.append(conn.execute(
                "SELECT status, transport_attempts FROM execution_reservation "
                "WHERE execution_reservation_id=?",
                (reservation.execution_reservation_id,),
            ).fetchone())

    with repository_factory() as repository:
        ReservationCoordinator(repository).reserve_or_reuse(
            project_id=_PROJ, node_contract=_node_contract(), input_payload=_payload_a(),
            now=_T0, transport=_FakeTransport(on_dispatch=observe_from_independent_connection),
        )
    assert observed == [("running", 1)]
