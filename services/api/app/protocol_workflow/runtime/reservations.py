"""Reservation coordinator for Protocol v3 execution reservations.

This module implements the :class:`ReservationCoordinator` runtime that wraps
an :class:`ExecutionReservationRepository` and enforces the exactly-once /
unknown-outcome discipline mandated by design sections 17.2 and 18:

* **Completed-result reuse** — a reservation with the same logical work and
  canonical input hash that already reached ``COMPLETED`` is returned without a
  new physical dispatch.

* **Unknown fail-closed** — a timeout or missing receipt after dispatch is
  classified ``UNKNOWN_OUTCOME``, never a retryable ``failed`` surrogate.  A
  subsequent request for the same logical call while the outcome is unresolved
  MUST fail closed (raise :class:`UnknownOutcomeConflictError`) rather than
  automatically redispatch.

* **Same-session/provider recovery** — a recovered output receipt can complete
  an unknown-outcome reservation *without* a new dispatch, preserving the
  single transport attempt.

* **Explicit append-only retry** — only an explicit, auditable retry decision
  may create attempt ``N+1``.  Attempt ``N`` remains immutable and queryable
  under its original idempotency key; the new attempt is stored under a derived
  key so concurrent duplicate retries are idempotent.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import RLock
from typing import Any, Optional, Protocol

from packages.contracts.workbench_contracts.protocol_v3 import (
    ExecutionReservation,
    ExecutionTerminalState,
    NodeExecutionContract,
    ReservationStatus,
)
from app.protocol_workflow.runtime.idempotency import canonical_input_hash
from app.protocol_workflow.ports.repositories import (
    IdempotencyConflictError,
    UnknownOutcomeConflictError,
)

__all__ = [
    "ExecutionTransport",
    "ReservationCoordinator",
    "ReservationOutcome",
]


# ---------------------------------------------------------------------------
# Transport protocol
# ---------------------------------------------------------------------------


class ExecutionTransport(Protocol):
    """Side-effect boundary for dispatching a reservation to a provider.

    The transport exposes two explicit surfaces so the coordinator can
    distinguish a deterministic pre-dispatch rejection (which may be classified
    ``FAILED`` because no dispatch ambiguity exists) from an ambiguous
    post-dispatch failure (which MUST be ``UNKNOWN_OUTCOME``).
    """

    def preflight(
        self,
        *,
        project_id: str,
        reservation: ExecutionReservation,
        payload: dict[str, Any],
    ) -> Optional[str]:
        """Return a stable error code if the dispatch is refused *before* any
        provider call.  ``None`` means the dispatch may proceed."""
        ...

    def dispatch(
        self,
        *,
        project_id: str,
        reservation: ExecutionReservation,
        payload: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Physically dispatch the reservation and return an output receipt.

        The receipt, when non-``None``, MUST contain ``output_sha256`` and
        ``provider_session_id``.  Returning ``None`` (or raising) signals a
        post-dispatch ambiguity classified ``UNKNOWN_OUTCOME``.
        """
        ...


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReservationOutcome:
    """The coordinator's black-box result for a reserve/reuse decision.

    The triple (``terminal_state``, ``status``, ``reservation``) is always
    consistent: ``status`` is ``reservation.status`` and ``terminal_state`` is
    ``reservation.terminal_state``.
    """

    terminal_state: ExecutionTerminalState
    status: ReservationStatus
    reservation: ExecutionReservation
    error_code: Optional[str] = None


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


#: Error codes assigned to terminal reservations.  Each is a stable id that
#: satisfies the ``StableId`` regex so it can be persisted on the reservation.
_ERROR_DISPATCH_TIMEOUT = "dispatch_timeout"
_ERROR_DISPATCH_NO_RECEIPT = "dispatch_no_receipt"
_ERROR_DISPATCH_EXCEPTION = "dispatch_exception"
_ERROR_DISPATCH_NOT_STARTED_RECOVERY = "dispatch_not_started_recovery"


class _RepositoryLike(Protocol):
    """Structural subset of :class:`ExecutionReservationRepository` used by the
    coordinator.  Declared privately so the coordinator depends on the exact
    method surface it calls."""

    def reserve(
        self,
        project_id: str,
        reservation: ExecutionReservation,
    ) -> ExecutionReservation: ...

    def get(
        self,
        project_id: str,
        execution_reservation_id: str,
    ) -> Optional[ExecutionReservation]: ...

    def find_by_logical_call(
        self,
        project_id: str,
        logical_call_id: str,
        idempotency_key: str,
    ) -> Optional[ExecutionReservation]: ...

    def transition(
        self,
        project_id: str,
        execution_reservation_id: str,
        *,
        to_status: ReservationStatus,
        terminal_state: Optional[ExecutionTerminalState] = None,
        output_sha256: Optional[str] = None,
        error_code: Optional[str] = None,
        provider_session_id: Optional[str] = None,
        transport_attempts: Optional[int] = None,
        updated_at: Any,
    ) -> ExecutionReservation: ...

    def list_attempts(
        self,
        project_id: str,
        logical_call_id: str,
    ) -> tuple[ExecutionReservation, ...]: ...

    def find_unknown_outcome(
        self, project_id: str
    ) -> tuple[ExecutionReservation, ...]: ...

    def find_unresolved(self, project_id: str) -> tuple[ExecutionReservation, ...]: ...


class ReservationCoordinator:
    """Coordinates execution reservations over a repository.

    The coordinator is the single runtime entry point that enforces the
    Protocol v3 reservation discipline.  It is transport-agnostic: every
    physical dispatch is injected as an :class:`ExecutionTransport`, so the
    coordinator is deterministic and unit-testable without a live provider.

    Retry serialization is local to one coordinator instance.  Across
    processes or coordinator instances, the repository remains the atomic
    owner: a duplicate decision that observes an in-flight winning row fails
    closed and converges to that row on a later call after it becomes terminal.
    """

    def __init__(self, repository: _RepositoryLike) -> None:
        self._repository = repository
        # Per-coordinator lock serialising explicit retries so concurrent
        # duplicate retry decisions for the same logical call produce exactly
        # one new dispatch and one new attempt.
        self._retry_lock = RLock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reserve_or_reuse(
        self,
        *,
        project_id: str,
        node_contract: NodeExecutionContract,
        input_payload: dict[str, Any],
        now: Any,
        transport: ExecutionTransport,
    ) -> ReservationOutcome:
        """Reserve a logical call or reuse a completed result.

        Decision tree:

        1. Compute the canonical input hash.
        2. Look up an existing reservation for the logical call + idempotency
           key.  If one exists:
           * ``COMPLETED`` with matching input → return it (zero dispatches).
           * ``UNKNOWN_OUTCOME`` → fail closed (the repository raises
             :class:`UnknownOutcomeConflictError` on ``reserve``; we surface
             it by delegating to ``reserve`` for the same effect).
           * ``RESERVED`` → a crash happened before the atomic ``RUNNING``
             transition, proving that physical dispatch never started.
             Dispose the dangling shell as ``FAILED`` with zero transport
             attempts; a new call still requires an explicit retry decision.
           * ``RUNNING`` → fail closed because physical dispatch started but
             no terminal receipt was persisted.
        3. Otherwise dispatch via the transport and classify the outcome:
           * pre-dispatch rejection → ``FAILED`` (no dispatch ambiguity).
           * exception / missing receipt → ``UNKNOWN_OUTCOME``.
           * valid receipt → ``COMPLETED``.
        4. Persist the terminal reservation (or surface the reuse).
        """
        logical_call_id = node_contract.logical_call_id
        idempotency_key = node_contract.idempotency_key
        input_sha = canonical_input_hash(
            logical_call_id=logical_call_id,
            idempotency_key=idempotency_key,
            payload=input_payload,
        )

        existing = self._repository.find_by_logical_call(
            project_id, logical_call_id, idempotency_key
        )
        if existing is not None:
            if existing.input_sha256 != input_sha:
                raise IdempotencyConflictError(
                    project_id,
                    logical_call_id,
                    existing.input_sha256,
                    input_sha,
                )
            if existing.status is ReservationStatus.RESERVED:
                disposed = self._repository.transition(
                    project_id,
                    existing.execution_reservation_id,
                    to_status=ReservationStatus.FAILED,
                    terminal_state=ExecutionTerminalState.FAILED,
                    output_sha256=None,
                    error_code=_ERROR_DISPATCH_NOT_STARTED_RECOVERY,
                    provider_session_id=existing.provider_session_id,
                    transport_attempts=0,
                    updated_at=now,
                )
                return ReservationOutcome(
                    terminal_state=ExecutionTerminalState.FAILED,
                    status=ReservationStatus.FAILED,
                    reservation=disposed,
                    error_code=_ERROR_DISPATCH_NOT_STARTED_RECOVERY,
                )
            return _outcome_for_existing(project_id, existing)

        return self._dispatch_and_persist(
            project_id=project_id,
            node_contract=node_contract,
            input_payload=input_payload,
            input_sha=input_sha,
            now=now,
            transport=transport,
            attempt=1,
            idempotency_key=idempotency_key,
        )

    def recover_unknown(
        self,
        *,
        project_id: str,
        reservation_id: str,
        recovered_output_receipt: dict[str, Any],
        now: Any,
    ) -> ExecutionReservation:
        """Complete an unknown-outcome reservation from a recovered receipt.

        The recovered output is treated as immutable evidence: no new physical
        dispatch occurs.  The reservation transitions in place (same id, same
        attempt) from ``UNKNOWN_OUTCOME`` to ``COMPLETED``.
        """
        recovered_sha = recovered_output_receipt["output_sha256"]
        recovered_session = recovered_output_receipt.get("provider_session_id")

        return self._repository.transition(
            project_id,
            reservation_id,
            to_status=ReservationStatus.COMPLETED,
            terminal_state=ExecutionTerminalState.COMPLETED,
            output_sha256=recovered_sha,
            error_code=None,
            provider_session_id=recovered_session,
            updated_at=now,
        )

    def retry_explicit(
        self,
        *,
        project_id: str,
        logical_call_id: str,
        idempotency_key: str,
        node_contract: NodeExecutionContract,
        input_payload: dict[str, Any],
        now: Any,
        transport: ExecutionTransport,
        retry_reason: str,
        retry_decision_id: str,
    ) -> ExecutionReservation:
        """Create an explicit, auditable attempt ``N+1`` for a logical call.

        ``retry_decision_id`` is the durable identity of the user/system retry
        decision.  Repeating that identity is idempotent; a distinct identity
        appends the next attempt even when the material input is unchanged.
        The original idempotency key remains bound to immutable attempt 1, so
        resolving a later attempt never makes the original unknown row reusable.
        """
        if not retry_reason.strip():
            raise ValueError("retry_reason must be non-empty")
        if not retry_decision_id.strip():
            raise ValueError("retry_decision_id must be non-empty")

        input_sha = canonical_input_hash(
            logical_call_id=logical_call_id,
            idempotency_key=idempotency_key,
            payload=input_payload,
        )
        decision_key = _derive_retry_idempotency_key(
            idempotency_key,
            retry_decision_id,
        )

        with self._retry_lock:
            for _allocation_attempt in range(32):
                existing_decision = self._repository.find_by_logical_call(
                    project_id,
                    logical_call_id,
                    decision_key,
                )
                if existing_decision is not None:
                    if existing_decision.input_sha256 != input_sha:
                        raise IdempotencyConflictError(
                            project_id,
                            decision_key,
                            existing_decision.input_sha256,
                            input_sha,
                        )
                    return _outcome_for_existing(
                        project_id,
                        existing_decision,
                    ).reservation

                attempts = self._repository.list_attempts(
                    project_id,
                    logical_call_id,
                )
                if not attempts:
                    raise ValueError(
                        "explicit retry requires an existing reservation attempt"
                    )
                new_attempt = attempts[-1].attempt + 1
                try:
                    outcome = self._dispatch_and_persist(
                        project_id=project_id,
                        node_contract=node_contract,
                        input_payload=input_payload,
                        input_sha=input_sha,
                        now=now,
                        transport=transport,
                        attempt=new_attempt,
                        idempotency_key=decision_key,
                    )
                except IdempotencyConflictError:
                    # A different retry decision may have atomically claimed
                    # the same attempt number.  Re-read the append-only lineage
                    # and allocate the next number; no physical dispatch has
                    # occurred because reserve() owns the claim.
                    continue
                return outcome.reservation
        raise RuntimeError("retry attempt allocation did not converge")

    def find_unknown_outcome(self, project_id: str) -> tuple[ExecutionReservation, ...]:
        """Return all unresolved unknown-outcome reservations for the project."""
        return self._repository.find_unknown_outcome(project_id)

    def find_unresolved(self, project_id: str) -> tuple[ExecutionReservation, ...]:
        """Return every nonterminal or outcome-unknown row needing recovery."""
        return self._repository.find_unresolved(project_id)

    # ------------------------------------------------------------------
    # Internal dispatch + persist
    # ------------------------------------------------------------------

    def _dispatch_and_persist(
        self,
        *,
        project_id: str,
        node_contract: NodeExecutionContract,
        input_payload: dict[str, Any],
        input_sha: str,
        now: Any,
        transport: ExecutionTransport,
        attempt: int,
        idempotency_key: str,
    ) -> ReservationOutcome:
        """Dispatch and persist a reservation using persist-first discipline.

        **Persist-first ordering** — a RESERVED shell is committed to the
        repository *before* the physical dispatch so that a crash between
        dispatch acceptance and persistence leaves a recoverable record
        instead of silently losing the reservation.  After dispatch resolves,
        the shell is transitioned in place to its terminal state
        (``UNKNOWN_OUTCOME`` or ``COMPLETED``).

        The RESERVED shell is the atomic ownership claim and carries zero
        transport attempts.  Preflight runs only after ownership is proven.
        Immediately before physical dispatch, the repository atomically moves
        the shell to RUNNING and records the first transport attempt.
        """
        reservation_id = _new_reservation_id()
        provider_session_id = f"sess:{reservation_id}"

        shell = ExecutionReservation(
            execution_reservation_id=reservation_id,
            node_execution_contract_id=node_contract.node_execution_contract_id,
            logical_call_id=node_contract.logical_call_id,
            idempotency_key=idempotency_key,
            input_sha256=input_sha,
            attempt=attempt,
            transport_attempts=0,
            provider_session_id=provider_session_id,
            status=ReservationStatus.RESERVED,
            terminal_state=None,
            output_sha256=None,
            error_code=None,
            reserved_at=now,
            updated_at=now,
        )
        persisted_shell = self._repository.reserve(project_id, shell)
        if persisted_shell.execution_reservation_id != reservation_id:
            return _outcome_for_existing(project_id, persisted_shell)

        try:
            preflight_error = transport.preflight(
                project_id=project_id,
                reservation=persisted_shell,
                payload=input_payload,
            )
        except Exception:
            preflight_error = "preflight_exception"
        if preflight_error is not None:
            failed = self._repository.transition(
                project_id,
                reservation_id,
                to_status=ReservationStatus.FAILED,
                terminal_state=ExecutionTerminalState.FAILED,
                output_sha256=None,
                error_code=preflight_error,
                provider_session_id=provider_session_id,
                transport_attempts=0,
                updated_at=now,
            )
            return ReservationOutcome(
                terminal_state=ExecutionTerminalState.FAILED,
                status=ReservationStatus.FAILED,
                reservation=failed,
                error_code=preflight_error,
            )

        running = self._repository.transition(
            project_id,
            reservation_id,
            to_status=ReservationStatus.RUNNING,
            terminal_state=None,
            output_sha256=None,
            error_code=None,
            provider_session_id=provider_session_id,
            transport_attempts=1,
            updated_at=now,
        )

        receipt: Optional[dict[str, Any]] = None
        dispatch_error_code: Optional[str] = None
        try:
            receipt = transport.dispatch(
                project_id=project_id,
                reservation=running,
                payload=input_payload,
            )
        except TimeoutError:
            dispatch_error_code = _ERROR_DISPATCH_TIMEOUT
        except Exception:
            dispatch_error_code = _ERROR_DISPATCH_EXCEPTION

        if dispatch_error_code is None and not _receipt_is_usable(receipt):
            dispatch_error_code = _ERROR_DISPATCH_NO_RECEIPT

        if dispatch_error_code is not None:
            # Post-dispatch ambiguity: the provider may have accepted the
            # call but we cannot prove the outcome.
            persisted = self._repository.transition(
                project_id,
                reservation_id,
                to_status=ReservationStatus.UNKNOWN_OUTCOME,
                terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
                output_sha256=None,
                error_code=dispatch_error_code,
                provider_session_id=provider_session_id,
                transport_attempts=running.transport_attempts,
                updated_at=now,
            )
            return ReservationOutcome(
                terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
                status=ReservationStatus.UNKNOWN_OUTCOME,
                reservation=persisted,
                error_code=dispatch_error_code,
            )

        # --- success ----------------------------------------------------
        output_sha = receipt["output_sha256"]  # type: ignore[index]
        # A successful live receipt may replace the harness-minted placeholder
        # with the provider-issued session identity.  Once an outcome becomes
        # UNKNOWN, recovery is stricter and must present that persisted session
        # identity; the repository enforces that distinction.
        receipt_session = receipt.get("provider_session_id") or provider_session_id  # type: ignore[union-attr]

        persisted = self._repository.transition(
            project_id,
            reservation_id,
            to_status=ReservationStatus.COMPLETED,
            terminal_state=ExecutionTerminalState.COMPLETED,
            output_sha256=output_sha,
            error_code=None,
            provider_session_id=receipt_session,
            transport_attempts=running.transport_attempts,
            updated_at=now,
        )
        return ReservationOutcome(
            terminal_state=ExecutionTerminalState.COMPLETED,
            status=ReservationStatus.COMPLETED,
            reservation=persisted,
            error_code=None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_reservation_id() -> str:
    """Return a fresh reservation id satisfying the ``StableId`` pattern."""
    return f"res:{uuid.uuid4().hex[:24]}"


def _derive_retry_idempotency_key(
    original_key: str,
    retry_decision_id: str,
) -> str:
    """Bind a retry attempt to its explicit durable decision identity.

    The attempt number is intentionally absent: repeating the same decision
    must find the same append-only row, while a distinct decision allocates a
    new attempt even if it carries identical input content.
    """
    return f"{original_key}::retry-decision:{retry_decision_id}"


def _outcome_for_existing(
    project_id: str,
    reservation: ExecutionReservation,
) -> ReservationOutcome:
    """Reuse a terminal outcome or fail closed for in-flight/unknown work."""
    if reservation.status in {
        ReservationStatus.RESERVED,
        ReservationStatus.RUNNING,
        ReservationStatus.UNKNOWN_OUTCOME,
    }:
        raise UnknownOutcomeConflictError(
            project_id,
            aggregate_id=reservation.logical_call_id,
            detail=(
                "reservation is unresolved; same logical call must not be "
                "dispatched again"
            ),
        )
    if reservation.terminal_state is None:
        raise RuntimeError("terminal reservation has no terminal_state")
    return ReservationOutcome(
        terminal_state=reservation.terminal_state,
        status=reservation.status,
        reservation=reservation,
        error_code=reservation.error_code,
    )


def _receipt_is_usable(receipt: Optional[dict[str, Any]]) -> bool:
    """Return ``True`` when *receipt* carries the required output fields."""
    if not isinstance(receipt, dict):
        return False
    output_sha = receipt.get("output_sha256")
    if not isinstance(output_sha, str) or not output_sha:
        return False
    return True
