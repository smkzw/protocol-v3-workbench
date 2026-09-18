"""Terminal views use one reservation as their source of truth."""

from datetime import datetime, timezone

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    ExecutionReservation, ExecutionTerminalState, ReservationStatus,
)
from app.protocol_workflow.runtime.reservations import ReservationOutcome


@pytest.mark.parametrize("state", list(ExecutionTerminalState))
def test_terminal_view_derives_state_and_error_from_reservation(state):
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    completed = state is ExecutionTerminalState.COMPLETED
    reservation = ExecutionReservation(
        execution_reservation_id="res:projection",
        node_execution_contract_id="node:projection",
        logical_call_id="call:projection", idempotency_key="projection",
        input_sha256="a" * 64, attempt=1, provider_session_id="session:projection",
        status=ReservationStatus(state.value), terminal_state=state,
        output_sha256="b" * 64 if completed else None,
        error_code=None if completed else "dispatch_timeout",
        reserved_at=now, updated_at=now,
    )
    outcome = ReservationOutcome(reservation=reservation)
    assert outcome.terminal_state is state
    assert outcome.status is reservation.status
    assert outcome.error_code == reservation.error_code
    assert vars(outcome) == {"reservation": reservation}


@pytest.mark.parametrize("status", [ReservationStatus.RESERVED, ReservationStatus.RUNNING])
def test_active_reservation_cannot_be_presented_as_terminal(status):
    now = datetime(2026, 9, 5, tzinfo=timezone.utc)
    reservation = ExecutionReservation(
        execution_reservation_id="res:active",
        node_execution_contract_id="node:active", logical_call_id="call:active",
        idempotency_key="active", input_sha256="a" * 64, attempt=1,
        status=status, reserved_at=now, updated_at=now,
    )
    with pytest.raises(ValueError, match="terminal result"):
        ReservationOutcome(reservation=reservation)
