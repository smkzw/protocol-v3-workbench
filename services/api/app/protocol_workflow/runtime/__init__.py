"""Protocol v3 ExecutionReservation runtime public surface.

Re-exports the public API shipped by the two implementation modules so callers
depend on a single ``app.protocol_workflow.runtime`` package:

* :mod:`runtime.idempotency` — canonical input hash, logical-work identity,
  and the cross-provider fallback payload re-builder.
* :mod:`runtime.reservations` — :class:`ReservationCoordinator` and its
  transport/outcome contracts.

Design authority: frozen plan Task 1.6 and ``plans/mw_protocol_multi_agent_
rearchitecture_design_20260809.md`` sections 17.2 and 18.
"""

from __future__ import annotations

from app.protocol_workflow.runtime.idempotency import (
    FallbackSafetyViolation,
    canonical_input_hash,
    logical_work_key,
    rebuild_fallback_payload,
)
from app.protocol_workflow.runtime.reservations import (
    ExecutionTransport,
    ReservationCoordinator,
    ReservationOutcome,
)

__all__ = [
    "ExecutionTransport",
    "FallbackSafetyViolation",
    "ReservationCoordinator",
    "ReservationOutcome",
    "canonical_input_hash",
    "logical_work_key",
    "rebuild_fallback_payload",
]
