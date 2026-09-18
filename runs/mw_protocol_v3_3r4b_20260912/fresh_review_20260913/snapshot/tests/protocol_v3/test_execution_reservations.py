"""Functional black-box tests for the Protocol v3 ExecutionReservation runtime
(Task 1.6 of the approved multi-agent rearchitecture plan).

These tests encode the *approved* black-box behavior mandated by design
sections 17.2 and 18 and the frozen-plan micro-steps, **without** invoking any
live provider, OCR, translation, download or export runtime.  They drive the
runtime public surface that Workers 01 and 02 ship under
``app.protocol_workflow.runtime``:

* ``runtime.idempotency`` — canonical input hash, logical-work identity, and
  cross-provider fallback payload re-builder that strips forbidden material.
* ``runtime.reservations`` — ``ReservationCoordinator`` that wraps an
  ``ExecutionReservationRepository`` and enforces completed-reuse, unknown
  fail-closed, same-session/provider recovery, and append-only explicit retry.
* ``runtime`` (``__init__``) — re-exports the public surface.

The tests are black-box and deterministic: every external transport is
injected as a fake.  The three named legacy surfaces (DeepSeek prefill,
Paddle→GLM OCR fallback, translation downstream transition) are encoded as
*local comparison tests* that freeze their already-proved semantics —
post-dispatch ambiguity is ``unknown``, restart does not redispatch, and an
immutable recovered output can resume without repeating completed work — so
the new runtime is provably consistent with the prior local invariants.

This first pass is specification-first: the file is written before the runtime
modules exist, so it demonstrates the expected missing-runtime failures.
Codex resumes this same session after Workers 01 and 02 complete to integrate
the public surface and re-run these same tests.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    ExecutionReservation,
    ExecutionTerminalState,
    NodeExecutionContract,
    ReasoningEffort,
    ReservationStatus,
    SensitivityTier,
)
from app.protocol_workflow.ports.repositories import (
    UnknownOutcomeConflictError,
)
from app.protocol_workflow.storage.memory import (
    InMemoryExecutionReservationRepository,
)

# Public runtime surface shipped by Workers 01 (idempotency) and 02
# (reservations), re-exported by Worker 03 (__init__).  These imports are the
# specification boundary: until the modules exist the focused file fails at
# collection with a clear ModuleNotFoundError.
from app.protocol_workflow.runtime import (  # noqa: E402
    FallbackSafetyViolation,
    ReservationCoordinator,
    ReservationOutcome,
    canonical_input_hash,
    logical_work_key,
    rebuild_fallback_payload,
)


# ---------------------------------------------------------------------------
# Deterministic timestamps and project ids
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 1, 0, 0, 1, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 1, 0, 0, 2, tzinfo=timezone.utc)
_T3 = datetime(2026, 1, 1, 0, 0, 3, tzinfo=timezone.utc)

_PROJ = "proj:task16:001"
_NEC_ID = "nec:task16:prefill:1"
_SKILL_ID = "skill:prefill:v1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_RECEIPT = object()


class _FakeTransport:
    """Deterministic side-effect transport.

    Records every physical dispatch and returns a canned output receipt.  Can
    be configured to raise (timeout / missing receipt) to exercise the
    ``unknown_outcome`` classification path.
    """

    def __init__(
        self,
        *,
        output_receipt: Optional[dict[str, Any]] | object = _DEFAULT_RECEIPT,
        raise_on_dispatch: Optional[BaseException] = None,
        pre_dispatch_error_code: Optional[str] = None,
        delay: float = 0.0,
        on_preflight: Optional[Callable[[ExecutionReservation], None]] = None,
        on_dispatch: Optional[Callable[[ExecutionReservation], None]] = None,
    ) -> None:
        self._output_receipt = output_receipt
        self._raise_on_dispatch = raise_on_dispatch
        self._pre_dispatch_error_code = pre_dispatch_error_code
        self._delay = delay
        self._on_preflight = on_preflight
        self._on_dispatch = on_dispatch
        self.dispatch_count = 0
        self._lock = threading.Lock()

    def preflight(
        self,
        *,
        project_id: str,
        reservation: ExecutionReservation,
        payload: dict[str, Any],
    ) -> Optional[str]:
        """Return a stable error code before any physical dispatch.

        The coordinator must call this explicit pre-dispatch interface before
        ``dispatch``.  A non-empty code proves the provider was never called;
        it may therefore be persisted as ``failed`` rather than an ambiguous
        ``unknown_outcome``.
        """
        del project_id, payload
        if self._on_preflight is not None:
            self._on_preflight(reservation)
        return self._pre_dispatch_error_code

    def dispatch(
        self,
        *,
        project_id: str,
        reservation: ExecutionReservation,
        payload: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            self.dispatch_count += 1
        if self._on_dispatch is not None:
            self._on_dispatch(reservation)
        if self._delay:
            threading.Event().wait(self._delay)
        if self._raise_on_dispatch is not None:
            raise self._raise_on_dispatch
        if self._output_receipt is _DEFAULT_RECEIPT:
            # Default: a deterministic output receipt keyed to the payload.
            return {
                "output_sha256": _output_sha_for(payload),
                "provider_session_id": f"sess:{reservation.execution_reservation_id}",
            }
        assert self._output_receipt is None or isinstance(self._output_receipt, dict)
        return self._output_receipt


def _output_sha_for(payload: dict[str, Any]) -> str:
    """Deterministic 64-hex digest from payload material content."""
    import hashlib
    import json

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha(n: int = 0) -> str:
    return f"{n:064x}"


def _node_contract(
    *,
    node_execution_contract_id: str = _NEC_ID,
    logical_call_id: str = "call:task16:1",
    idempotency_key: str = "idem-task16-1",
    provider: str = "deepseek",
    allowed_providers: tuple[str, ...] = ("deepseek",),
    allowed_regions: tuple[str, ...] = ("cn",),
    sensitivity_tier: SensitivityTier = SensitivityTier.INTERNAL,
) -> NodeExecutionContract:
    """Build a minimal valid ``NodeExecutionContract`` for test dispatch."""
    return NodeExecutionContract(
        node_execution_contract_id=node_execution_contract_id,
        skill_definition_id=_SKILL_ID,
        role="llm",
        harness="direct_api",
        provider=provider,
        model="deepseek-v4-flash",
        reasoning_effort=ReasoningEffort.HIGH,
        same_session_recovery=True,
        timeout_seconds=300,
        fallback_policy_id="fbp:default",
        prompt_sha256=_sha(1),
        input_schema_ref="schema:prefill:input:v1",
        output_schema_ref="schema:prefill:output:v1",
        allowed_tools=(),
        allowed_paths=(),
        permission_policy_id="perm:default",
        input_artifact_hashes=(_sha(2),),
        sensitivity_tier=sensitivity_tier,
        allowed_providers=allowed_providers,
        allowed_regions=allowed_regions,
        redaction_policy_id="redact:default",
        retention_policy_id="retain:default",
        logical_call_id=logical_call_id,
        idempotency_key=idempotency_key,
    )


def _coordinator() -> ReservationCoordinator:
    """Build a coordinator over a fresh in-memory reservation repository."""
    return ReservationCoordinator(
        repository=InMemoryExecutionReservationRepository(),
    )


def _payload_a() -> dict[str, Any]:
    return {"prompt": "generate prefill", "source_text": "IB section 1"}


def _payload_a_equivalent() -> dict[str, Any]:
    """Same material content as ``_payload_a`` but different insertion order
    to prove canonical hashing is order-independent."""
    return {"source_text": "IB section 1", "prompt": "generate prefill"}


def _payload_b() -> dict[str, Any]:
    return {"prompt": "generate prefill", "source_text": "IB section 2"}


# ---------------------------------------------------------------------------
# 1. Legacy comparison semantics (three frozen local invariants)
# ---------------------------------------------------------------------------


class TestLegacyComparisonSemantics:
    """Freeze the three already-proved local semantics as black-box invariants
    of the new runtime, without invoking their live runtimes.

    These correspond to the first frozen-plan micro-step:

    * **prefill** — a timeout or post-dispatch persistence loss is classified
      ``unknown_outcome`` and the call is never automatically redispatched
      (``tests/test_medical_writing_authoring_prefill_ai.py``
      ``GenerationReservationTests``).
    * **OCR fallback** — Paddle→GLM fallback fires only after a verified
      Paddle rejection/failure; an outcome-unknown Paddle result re-raises and
      never starts a second model for the same page
      (``services/api/app/ocr_fallback_orchestrator.py``).
    * **translation downstream** — restart over a model call whose outcome
      cannot be proven never repeats the model call and fails closed
      ``model_call_outcome_unknown_after_restart``
      (``tests/test_writing_reference_translation_batch.py``).
    """

    def test_post_dispatch_ambiguity_is_unknown_not_failed(self) -> None:
        """Prefill invariant: a timeout during dispatch produces
        ``unknown_outcome``, never a retryable ``failed`` surrogate.  The
        reservation carries the single transport attempt and an error code."""
        coordinator = _coordinator()
        contract = _node_contract()
        transport = _FakeTransport(
            raise_on_dispatch=TimeoutError("simulated provider timeout"),
        )
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=transport,
        )
        assert outcome.terminal_state is ExecutionTerminalState.UNKNOWN_OUTCOME
        assert outcome.status is ReservationStatus.UNKNOWN_OUTCOME
        assert outcome.error_code is not None
        assert outcome.error_code != ""
        # Exactly one physical dispatch was attempted (then it timed out).
        assert transport.dispatch_count == 1
        assert outcome.reservation.transport_attempts == 1
        # No output hash for an unknown outcome.
        assert outcome.reservation.output_sha256 is None

    def test_restart_does_not_redispatch_unknown_outcome(self) -> None:
        """OCR / translation invariant: a second coordinator (simulated
        restart) over the preserved repository state refuses to re-dispatch
        an unresolved unknown outcome.  Zero additional dispatches."""
        repository = InMemoryExecutionReservationRepository()
        first = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        timeout_transport = _FakeTransport(
            raise_on_dispatch=TimeoutError("simulated provider timeout"),
        )
        first.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=timeout_transport,
        )
        assert timeout_transport.dispatch_count == 1

        # Simulated restart: a new coordinator over the SAME repository.
        restarted = ReservationCoordinator(repository=repository)
        working_transport = _FakeTransport()
        # Re-reserving the same logical call while the outcome is unresolved
        # must fail closed — no automatic redispatch.
        with pytest.raises(UnknownOutcomeConflictError):
            restarted.reserve_or_reuse(
                project_id=_PROJ,
                node_contract=contract,
                input_payload=_payload_a(),
                now=_T1,
                transport=working_transport,
            )
        # The restarted coordinator never dispatched.
        assert working_transport.dispatch_count == 0

    def test_immutable_recovered_output_resumes_without_repeating_work(
        self,
    ) -> None:
        """Translation downstream invariant: when a same-session/provider
        reconciliation recovers an output receipt, the reservation completes
        **without** a new physical dispatch.  The recovered output is treated
        as immutable evidence."""
        repository = InMemoryExecutionReservationRepository()
        first = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        timeout_transport = _FakeTransport(
            raise_on_dispatch=TimeoutError("simulated provider timeout"),
        )
        outcome = first.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=timeout_transport,
        )
        assert outcome.terminal_state is ExecutionTerminalState.UNKNOWN_OUTCOME

        # Same-session/provider recovery: a recovered output receipt arrives.
        recovered_output_sha = _sha(900)
        recovered = first.recover_unknown(
            project_id=_PROJ,
            reservation_id=outcome.reservation.execution_reservation_id,
            recovered_output_receipt={
                "output_sha256": recovered_output_sha,
                "provider_session_id": outcome.reservation.provider_session_id,
            },
            now=_T1,
        )
        # The reservation is now completed with the recovered output ...
        assert recovered.status is ReservationStatus.COMPLETED
        assert recovered.terminal_state is ExecutionTerminalState.COMPLETED
        assert recovered.output_sha256 == recovered_output_sha
        # ... and NO additional physical dispatch happened (still exactly 1).
        assert timeout_transport.dispatch_count == 1


# ---------------------------------------------------------------------------
# 2. Completed-result reuse with zero redispatches
# ---------------------------------------------------------------------------


class TestCompletedReuse:
    """A completed reservation with the same logical work and canonical input
    hash returns the existing output and causes zero physical redispatches."""

    def test_same_logical_work_and_input_hash_reuses_output(self) -> None:
        coordinator = _coordinator()
        contract = _node_contract()
        transport = _FakeTransport()
        first = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=transport,
        )
        assert first.terminal_state is ExecutionTerminalState.COMPLETED
        assert first.status is ReservationStatus.COMPLETED
        assert first.reservation.output_sha256 is not None
        assert transport.dispatch_count == 1

        # Second request: same logical work + same canonical input hash.
        second = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a_equivalent(),
            now=_T1,
            transport=transport,
        )
        assert second.terminal_state is ExecutionTerminalState.COMPLETED
        assert second.status is ReservationStatus.COMPLETED
        assert second.reservation.output_sha256 == first.reservation.output_sha256
        # Zero additional dispatch — the completed result was reused.
        assert transport.dispatch_count == 1

    def test_reuse_returns_same_reservation_identity(self) -> None:
        coordinator = _coordinator()
        contract = _node_contract()
        transport = _FakeTransport()
        first = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=transport,
        )
        second = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=transport,
        )
        assert (
            second.reservation.execution_reservation_id
            == first.reservation.execution_reservation_id
        )

    def test_completed_reuse_is_observed_after_simulated_restart(self) -> None:
        """A completed reservation survives a restart (new coordinator over the
        same repository) and is reused with zero dispatches."""
        repository = InMemoryExecutionReservationRepository()
        first_coord = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        first_transport = _FakeTransport()
        first_coord.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=first_transport,
        )

        # Restart.
        restarted = ReservationCoordinator(repository=repository)
        restart_transport = _FakeTransport()
        outcome = restarted.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=restart_transport,
        )
        assert outcome.terminal_state is ExecutionTerminalState.COMPLETED
        # The restarted coordinator never dispatched.
        assert restart_transport.dispatch_count == 0


# ---------------------------------------------------------------------------
# 3. Timeout / missing transport receipt -> unknown_outcome
# ---------------------------------------------------------------------------


class TestTimeoutClassification:
    """A timeout or missing transport receipt after dispatch produces
    ``unknown_outcome``, never a retryable ``failed`` surrogate."""

    def test_timeout_during_dispatch_is_unknown(self) -> None:
        coordinator = _coordinator()
        contract = _node_contract()
        transport = _FakeTransport(
            raise_on_dispatch=TimeoutError("provider timed out"),
        )
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=transport,
        )
        assert outcome.terminal_state is ExecutionTerminalState.UNKNOWN_OUTCOME
        assert outcome.reservation.error_code is not None

    def test_missing_receipt_after_dispatch_is_unknown(self) -> None:
        """A dispatch that returns no usable receipt (empty / None) is an
        unknown outcome, not a success or a failed surrogate."""
        coordinator = _coordinator()
        contract = _node_contract()
        transport = _FakeTransport(output_receipt=None)
        # The coordinator must treat a missing receipt as unknown.
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=transport,
        )
        assert outcome.terminal_state is ExecutionTerminalState.UNKNOWN_OUTCOME
        assert transport.dispatch_count == 1

    def test_verified_pre_dispatch_rejection_may_be_failed(self) -> None:
        """A verified pre-dispatch rejection (e.g. a structured contract
        refusal before any model call) may be classified ``failed`` rather
        than ``unknown_outcome``, because no dispatch ambiguity exists."""
        coordinator = _coordinator()
        contract = _node_contract()
        transport = _FakeTransport(
            pre_dispatch_error_code="contract_validation_refused_dispatch",
        )
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=transport,
        )
        # A verified pre-dispatch rejection is a deterministic failure.
        assert outcome.terminal_state is ExecutionTerminalState.FAILED
        assert outcome.reservation.error_code is not None
        # No physical dispatch happened for a verified pre-dispatch rejection.
        assert transport.dispatch_count == 0
        assert outcome.reservation.transport_attempts == 0


class TestPersistFirstOwnership:
    """The repository claim and RUNNING transition precede side effects."""

    def test_reservation_is_persisted_before_preflight_and_dispatch(self) -> None:
        repository = InMemoryExecutionReservationRepository()
        observations: list[tuple[str, ReservationStatus, int]] = []

        def observe_preflight(reservation: ExecutionReservation) -> None:
            persisted = repository.get(
                _PROJ,
                reservation.execution_reservation_id,
            )
            assert persisted is not None
            observations.append(
                ("preflight", persisted.status, persisted.transport_attempts)
            )

        def observe_dispatch(reservation: ExecutionReservation) -> None:
            persisted = repository.get(
                _PROJ,
                reservation.execution_reservation_id,
            )
            assert persisted is not None
            observations.append(
                ("dispatch", persisted.status, persisted.transport_attempts)
            )

        coordinator = ReservationCoordinator(repository=repository)
        coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=_node_contract(),
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                on_preflight=observe_preflight,
                on_dispatch=observe_dispatch,
            ),
        )
        assert observations == [
            ("preflight", ReservationStatus.RESERVED, 0),
            ("dispatch", ReservationStatus.RUNNING, 1),
        ]

    def test_terminal_persist_failure_leaves_running_and_restart_never_dispatches(
        self,
    ) -> None:
        class FailTerminalPersistRepository(InMemoryExecutionReservationRepository):
            fail_once = True

            def transition(self, *args: Any, **kwargs: Any) -> ExecutionReservation:
                if (
                    self.fail_once
                    and kwargs.get("to_status") is ReservationStatus.COMPLETED
                ):
                    self.fail_once = False
                    raise RuntimeError("simulated terminal persist failure")
                return super().transition(*args, **kwargs)

        repository = FailTerminalPersistRepository()
        first_transport = _FakeTransport()
        coordinator = ReservationCoordinator(repository=repository)
        with pytest.raises(RuntimeError, match="terminal persist failure"):
            coordinator.reserve_or_reuse(
                project_id=_PROJ,
                node_contract=_node_contract(),
                input_payload=_payload_a(),
                now=_T0,
                transport=first_transport,
            )
        assert first_transport.dispatch_count == 1
        attempts = repository.list_attempts(_PROJ, "call:task16:1")
        assert len(attempts) == 1
        assert attempts[0].status is ReservationStatus.RUNNING
        assert attempts[0].transport_attempts == 1

        unresolved = ReservationCoordinator(repository=repository).find_unresolved(
            _PROJ
        )
        assert unresolved == attempts

        restart_transport = _FakeTransport()
        restarted = ReservationCoordinator(repository=repository)
        with pytest.raises(UnknownOutcomeConflictError):
            restarted.reserve_or_reuse(
                project_id=_PROJ,
                node_contract=_node_contract(),
                input_payload=_payload_a(),
                now=_T1,
                transport=restart_transport,
            )
        assert restart_transport.dispatch_count == 0

    def test_restart_disposes_reserved_shell_without_dispatch(self) -> None:
        """A RESERVED shell proves the RUNNING/dispatch boundary was never
        crossed, so restart closes it as a zero-attempt failure."""
        repository = InMemoryExecutionReservationRepository()
        coordinator = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        input_sha = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload=_payload_a(),
        )
        shell = ExecutionReservation(
            execution_reservation_id="res:task16:dangling:0001",
            node_execution_contract_id=contract.node_execution_contract_id,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            input_sha256=input_sha,
            attempt=1,
            transport_attempts=0,
            provider_session_id="sess:task16:dangling:0001",
            status=ReservationStatus.RESERVED,
            terminal_state=None,
            output_sha256=None,
            error_code=None,
            reserved_at=_T0,
            updated_at=_T0,
        )
        repository.reserve(_PROJ, shell)
        transport = _FakeTransport()

        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=transport,
        )

        assert outcome.status is ReservationStatus.FAILED
        assert outcome.error_code == "dispatch_not_started_recovery"
        assert outcome.reservation.transport_attempts == 0
        assert transport.dispatch_count == 0
        assert coordinator.find_unresolved(_PROJ) == ()

    def test_two_coordinators_cannot_dispatch_the_same_claim_twice(self) -> None:
        repository = InMemoryExecutionReservationRepository()
        transport = _FakeTransport(delay=0.2)
        barrier = threading.Barrier(2)
        outcomes: list[ReservationOutcome] = []
        errors: list[BaseException] = []

        def run() -> None:
            try:
                barrier.wait(timeout=5)
                outcomes.append(
                    ReservationCoordinator(repository=repository).reserve_or_reuse(
                        project_id=_PROJ,
                        node_contract=_node_contract(),
                        input_payload=_payload_a(),
                        now=_T0,
                        transport=transport,
                    )
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run), threading.Thread(target=run)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert transport.dispatch_count == 1
        assert len(repository.list_attempts(_PROJ, "call:task16:1")) == 1
        assert len(outcomes) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], UnknownOutcomeConflictError)


# ---------------------------------------------------------------------------
# 4. Restart blocks automatic redispatch of unknown outcome
# ---------------------------------------------------------------------------


class TestRestartBlocksRedispatch:
    """Restart with an unresolved unknown outcome refuses automatic
    redispatch of the same logical call."""

    def test_restart_reserve_same_logical_call_raises(self) -> None:
        repository = InMemoryExecutionReservationRepository()
        first = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        first.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                raise_on_dispatch=TimeoutError("timeout"),
            ),
        )
        restarted = ReservationCoordinator(repository=repository)
        with pytest.raises(UnknownOutcomeConflictError):
            restarted.reserve_or_reuse(
                project_id=_PROJ,
                node_contract=contract,
                input_payload=_payload_a(),
                now=_T1,
                transport=_FakeTransport(),
            )

    def test_find_unknown_survives_restart(self) -> None:
        """The repository's ``find_unknown_outcome`` exposes the unresolved
        reservation after a restart so recovery can act on it."""
        repository = InMemoryExecutionReservationRepository()
        first = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        outcome = first.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                raise_on_dispatch=TimeoutError("timeout"),
            ),
        )
        restarted = ReservationCoordinator(repository=repository)
        unknowns = restarted.find_unknown_outcome(project_id=_PROJ)
        assert len(unknowns) == 1
        assert (
            unknowns[0].execution_reservation_id
            == outcome.reservation.execution_reservation_id
        )


# ---------------------------------------------------------------------------
# 5. Same-session/provider recovery
# ---------------------------------------------------------------------------


class TestSameSessionRecovery:
    """Same-session/provider reconciliation can complete the same unknown
    reservation from a recovered output receipt without creating a new
    physical provider call."""

    def test_recover_completes_unknown_reservation(self) -> None:
        coordinator = _coordinator()
        contract = _node_contract()
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                raise_on_dispatch=TimeoutError("timeout"),
            ),
        )
        recovered_sha = _sha(500)
        recovered = coordinator.recover_unknown(
            project_id=_PROJ,
            reservation_id=outcome.reservation.execution_reservation_id,
            recovered_output_receipt={
                "output_sha256": recovered_sha,
                "provider_session_id": outcome.reservation.provider_session_id,
            },
            now=_T1,
        )
        assert recovered.status is ReservationStatus.COMPLETED
        assert recovered.output_sha256 == recovered_sha

    def test_recover_unknown_reservation_uses_same_identity(self) -> None:
        """Recovery completes the SAME reservation — no new reservation id,
        no new attempt, no new logical call."""
        coordinator = _coordinator()
        contract = _node_contract()
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                raise_on_dispatch=TimeoutError("timeout"),
            ),
        )
        original_id = outcome.reservation.execution_reservation_id
        original_attempt = outcome.reservation.attempt
        recovered = coordinator.recover_unknown(
            project_id=_PROJ,
            reservation_id=original_id,
            recovered_output_receipt={
                "output_sha256": _sha(500),
                "provider_session_id": outcome.reservation.provider_session_id,
            },
            now=_T1,
        )
        assert recovered.execution_reservation_id == original_id
        assert recovered.attempt == original_attempt

    def test_after_recovery_reuse_works_without_redispatch(self) -> None:
        """Once an unknown reservation is recovered to completed, a subsequent
        same-input request reuses the recovered output with zero dispatches."""
        repository = InMemoryExecutionReservationRepository()
        coordinator = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        timeout_transport = _FakeTransport(
            raise_on_dispatch=TimeoutError("timeout"),
        )
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=timeout_transport,
        )
        coordinator.recover_unknown(
            project_id=_PROJ,
            reservation_id=outcome.reservation.execution_reservation_id,
            recovered_output_receipt={
                "output_sha256": _sha(500),
                "provider_session_id": outcome.reservation.provider_session_id,
            },
            now=_T1,
        )
        # Now reuse: a new transport that must never fire.
        reuse_transport = _FakeTransport()
        reused = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T2,
            transport=reuse_transport,
        )
        assert reused.terminal_state is ExecutionTerminalState.COMPLETED
        assert reuse_transport.dispatch_count == 0


# ---------------------------------------------------------------------------
# 6. Explicit retry creates append-only attempt N+1
# ---------------------------------------------------------------------------


class TestExplicitRetry:
    """Only an explicit, auditable retry decision may create attempt ``N+1``.
    Attempt ``N`` remains immutable and queryable, and concurrent duplicate
    retry decisions cannot create duplicate attempts."""

    def test_explicit_retry_creates_new_attempt_leaves_old_immutable(
        self,
    ) -> None:
        repository = InMemoryExecutionReservationRepository()
        coordinator = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                raise_on_dispatch=TimeoutError("timeout"),
            ),
        )
        old_id = outcome.reservation.execution_reservation_id
        old_attempt = outcome.reservation.attempt

        # Explicit retry with a working transport.
        retry_transport = _FakeTransport()
        retried = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=retry_transport,
            retry_reason="user-visible retry decision after unknown outcome",
            retry_decision_id="retry-decision:001",
        )
        # New attempt N+1 ...
        assert retried.attempt == old_attempt + 1
        # ... with a different reservation id (append-only, not an overwrite).
        assert retried.execution_reservation_id != old_id
        assert retry_transport.dispatch_count == 1

        # Attempt N is immutable and queryable.
        old = repository.get(_PROJ, old_id)
        assert old is not None
        assert old.status is ReservationStatus.UNKNOWN_OUTCOME
        assert old.attempt == old_attempt

    def test_retry_after_completed_is_a_new_attempt(self) -> None:
        """An explicit retry after a completed reservation also creates a new
        attempt rather than overwriting the completed record."""
        coordinator = _coordinator()
        contract = _node_contract()
        first = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(),
        )
        old_id = first.reservation.execution_reservation_id
        retried = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_b(),
            now=_T1,
            transport=_FakeTransport(),
            retry_reason="regeneration after content change",
            retry_decision_id="retry-decision:002",
        )
        assert retried.attempt == first.reservation.attempt + 1
        assert retried.execution_reservation_id != old_id

    def test_concurrent_duplicate_retry_creates_one_new_attempt(self) -> None:
        """Two concurrent explicit-retry decisions for the same logical call
        produce exactly one new dispatch and one new attempt; the loser
        observes the winner's outcome."""
        repository = InMemoryExecutionReservationRepository()
        coordinator = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        # Seed an unknown outcome.
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                raise_on_dispatch=TimeoutError("timeout"),
            ),
        )
        old_attempt = outcome.reservation.attempt

        retry_transport = _FakeTransport(delay=0.2)
        barrier = threading.Barrier(2)
        results: list[ExecutionReservation] = []
        errors: list[BaseException] = []

        def _retry_worker() -> None:
            try:
                barrier.wait(timeout=5)
                result = coordinator.retry_explicit(
                    project_id=_PROJ,
                    logical_call_id=contract.logical_call_id,
                    idempotency_key=contract.idempotency_key,
                    node_contract=contract,
                    input_payload=_payload_a(),
                    now=_T1,
                    transport=retry_transport,
                    retry_reason="concurrent retry",
                    retry_decision_id="retry-decision:003",
                )
                results.append(result)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=_retry_worker),
            threading.Thread(target=_retry_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert errors == []
        assert len(results) == 2
        # Exactly one physical dispatch.
        assert retry_transport.dispatch_count == 1
        # Both workers observed the same new attempt.
        assert (
            results[0].execution_reservation_id == results[1].execution_reservation_id
        )
        assert results[0].attempt == old_attempt + 1
        # Old attempt unchanged.
        old = repository.get(_PROJ, outcome.reservation.execution_reservation_id)
        assert old is not None
        assert old.attempt == old_attempt

    def test_distinct_retry_decisions_append_attempts_even_with_same_input(
        self,
    ) -> None:
        repository = InMemoryExecutionReservationRepository()
        coordinator = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(),
        )
        second = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=_FakeTransport(),
            retry_reason="first explicit regeneration",
            retry_decision_id="retry-decision:004",
        )
        third = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T2,
            transport=_FakeTransport(),
            retry_reason="second independent regeneration",
            retry_decision_id="retry-decision:005",
        )
        assert (second.attempt, third.attempt) == (2, 3)
        assert second.input_sha256 == third.input_sha256
        assert [
            reservation.attempt
            for reservation in repository.list_attempts(
                _PROJ,
                contract.logical_call_id,
            )
        ] == [1, 2, 3]

    def test_duplicate_retry_decision_is_idempotent(self) -> None:
        repository = InMemoryExecutionReservationRepository()
        coordinator = ReservationCoordinator(repository=repository)
        contract = _node_contract()
        coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(),
        )
        transport = _FakeTransport()
        first = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=transport,
            retry_reason="same decision replay",
            retry_decision_id="retry-decision:006",
        )
        replay = coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T2,
            transport=transport,
            retry_reason="same decision replay",
            retry_decision_id="retry-decision:006",
        )
        assert replay.execution_reservation_id == first.execution_reservation_id
        assert transport.dispatch_count == 1
        assert len(repository.list_attempts(_PROJ, contract.logical_call_id)) == 2

    def test_cross_coordinator_duplicate_retry_fails_closed_then_converges(
        self,
    ) -> None:
        """Repository ownership prevents duplicate dispatch across coordinator
        instances; an in-flight loser fails closed and a later replay converges."""
        repository = InMemoryExecutionReservationRepository()
        contract = _node_contract()
        ReservationCoordinator(repository).reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(),
        )
        coordinators = [
            ReservationCoordinator(repository),
            ReservationCoordinator(repository),
        ]
        transport = _FakeTransport(delay=0.2)
        barrier = threading.Barrier(2)
        results: list[ExecutionReservation] = []
        errors: list[BaseException] = []

        def _worker(coordinator: ReservationCoordinator) -> None:
            try:
                barrier.wait(timeout=5)
                results.append(
                    coordinator.retry_explicit(
                        project_id=_PROJ,
                        logical_call_id=contract.logical_call_id,
                        idempotency_key=contract.idempotency_key,
                        node_contract=contract,
                        input_payload=_payload_a(),
                        now=_T1,
                        transport=transport,
                        retry_reason="cross-coordinator duplicate",
                        retry_decision_id="retry-decision:cross-coordinator",
                    )
                )
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [
            threading.Thread(target=_worker, args=(coordinator,))
            for coordinator in coordinators
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert transport.dispatch_count == 1
        assert len(results) == 1
        assert len(errors) == 1
        assert isinstance(errors[0], UnknownOutcomeConflictError)

        replay = coordinators[0].retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T2,
            transport=transport,
            retry_reason="cross-coordinator duplicate",
            retry_decision_id="retry-decision:cross-coordinator",
        )
        assert replay.execution_reservation_id == results[0].execution_reservation_id
        assert transport.dispatch_count == 1

    def test_resolved_retry_does_not_rebind_original_unknown_key(self) -> None:
        """Attempt 1 remains immutable and fail-closed under its original key
        even after a later explicit retry completes successfully."""
        repository = InMemoryExecutionReservationRepository()
        coordinator = ReservationCoordinator(repository)
        contract = _node_contract()
        coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(raise_on_dispatch=TimeoutError("timeout")),
        )
        coordinator.retry_explicit(
            project_id=_PROJ,
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            node_contract=contract,
            input_payload=_payload_a(),
            now=_T1,
            transport=_FakeTransport(),
            retry_reason="resolve lineage with a new attempt",
            retry_decision_id="retry-decision:resolved-lineage",
        )
        original_transport = _FakeTransport()
        with pytest.raises(UnknownOutcomeConflictError):
            coordinator.reserve_or_reuse(
                project_id=_PROJ,
                node_contract=contract,
                input_payload=_payload_a(),
                now=_T2,
                transport=original_transport,
            )
        assert original_transport.dispatch_count == 0


# ---------------------------------------------------------------------------
# 7. Cross-provider fallback payload shaping
# ---------------------------------------------------------------------------


class TestFallbackPayloadShaping:
    """Provider fallback rebuilds a minimal payload from canonical source and
    excludes previous-provider scratchpad/session transcript/raw sensitive
    payload.  An unsafe package that cannot exclude forbidden material fails
    closed."""

    def test_fallback_excludes_previous_provider_scratchpad(self) -> None:
        """A fallback payload rebuilt from canonical source must not carry the
        previous provider's scratchpad."""
        canonical_source = {
            "prompt": "translate section",
            "source_text": "源文本",
        }
        payload = rebuild_fallback_payload(
            canonical_source=canonical_source,
            previous_provider_scratchpad={
                "internal_reasoning": "secret chain of thought",
            },
            sensitivity_tier=SensitivityTier.INTERNAL,
            allowed_providers=("deepseek",),
            allowed_regions=("cn",),
        )
        serialized = repr(payload).lower()
        assert "internal_reasoning" not in serialized
        assert "secret chain of thought" not in serialized
        # Canonical material is preserved.
        assert payload["source_text"] == "源文本"

    def test_fallback_excludes_session_transcript(self) -> None:
        canonical_source = {"prompt": "summarize", "context": "trial design"}
        payload = rebuild_fallback_payload(
            canonical_source=canonical_source,
            session_transcript=[
                {"role": "assistant", "content": "prior session output"},
            ],
            sensitivity_tier=SensitivityTier.INTERNAL,
            allowed_providers=("deepseek",),
            allowed_regions=("cn",),
        )
        serialized = repr(payload).lower()
        assert "prior session output" not in serialized

    def test_fallback_excludes_raw_sensitive_payload(self) -> None:
        canonical_source = {"prompt": "generate", "source_text": "public text"}
        payload = rebuild_fallback_payload(
            canonical_source=canonical_source,
            raw_sensitive_payload={"ib_confidential_paragraph": "secret"},
            sensitivity_tier=SensitivityTier.INTERNAL,
            allowed_providers=("deepseek",),
            allowed_regions=("cn",),
        )
        serialized = repr(payload).lower()
        assert "ib_confidential_paragraph" not in serialized
        assert "secret" not in serialized

    def test_fallback_fails_closed_on_unmovable_forbidden_material(
        self,
    ) -> None:
        """When forbidden material cannot be excluded (e.g. the canonical
        source itself is restricted and the target provider is outside the
        sensitivity allowlist), the re-builder fails closed."""
        canonical_source = {
            "prompt": "generate",
            "source_text": "restricted IB content",
        }
        with pytest.raises(FallbackSafetyViolation):
            rebuild_fallback_payload(
                canonical_source=canonical_source,
                sensitivity_tier=SensitivityTier.RESTRICTED,
                allowed_providers=("deepseek",),
                allowed_regions=("cn",),
                target_provider="unapproved-provider",
                target_region="cn",
            )

    def test_restricted_fallback_requires_explicit_target(self) -> None:
        with pytest.raises(
            FallbackSafetyViolation,
            match="explicit target provider and region",
        ):
            rebuild_fallback_payload(
                canonical_source={"prompt": "generate", "source_text": "restricted"},
                sensitivity_tier=SensitivityTier.RESTRICTED,
                allowed_providers=("deepseek",),
                allowed_regions=("cn",),
            )

    def test_fallback_rejects_nested_forbidden_fragment(self) -> None:
        with pytest.raises(FallbackSafetyViolation):
            rebuild_fallback_payload(
                canonical_source={
                    "prompt": "generate",
                    "nested": {"session_transcript": ["contaminated"]},
                },
                sensitivity_tier=SensitivityTier.INTERNAL,
                allowed_providers=("deepseek",),
                allowed_regions=("cn",),
            )


# ---------------------------------------------------------------------------
# 8. Canonical input hash and logical-work identity
# ---------------------------------------------------------------------------


class TestCanonicalInputHash:
    """The canonical input hash is deterministic, order-independent, and
    ignores runtime metadata (timestamps, attempt counters) that must not
    cause a materially-identical request to be misclassified as stale."""

    def test_same_material_content_same_hash(self) -> None:
        contract = _node_contract()
        h1 = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload=_payload_a(),
        )
        h2 = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload=_payload_a_equivalent(),
        )
        assert h1 == h2

    def test_different_material_different_hash(self) -> None:
        contract = _node_contract()
        h1 = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload=_payload_a(),
        )
        h2 = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload=_payload_b(),
        )
        assert h1 != h2

    def test_hash_ignores_runtime_metadata(self) -> None:
        """Adding a timestamp or attempt counter to the payload must not
        change the canonical hash — these are runtime metadata, not material
        content."""
        contract = _node_contract()
        base = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload=_payload_a(),
        )
        with_metadata = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload={
                **_payload_a(),
                "_timestamp": "2026-08-10T00:00:00Z",
                "_attempt": 2,
            },
        )
        assert base == with_metadata

    def test_retry_decision_key_does_not_change_material_input_hash(self) -> None:
        contract = _node_contract()
        original = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key=contract.idempotency_key,
            payload=_payload_a(),
        )
        retry = canonical_input_hash(
            logical_call_id=contract.logical_call_id,
            idempotency_key="idem-task16-1::retry-decision:007",
            payload=_payload_a(),
        )
        assert retry == original

    def test_logical_work_key_is_stable(self) -> None:
        key = logical_work_key(
            logical_call_id="call:task16:1",
            idempotency_key="idem-task16-1",
        )
        assert isinstance(key, str)
        assert key == logical_work_key(
            logical_call_id="call:task16:1",
            idempotency_key="idem-task16-1",
        )
        assert key != logical_work_key(
            logical_call_id="call:task16:2",
            idempotency_key="idem-task16-1",
        )


# ---------------------------------------------------------------------------
# 9. Coordinator outcome classification contract
# ---------------------------------------------------------------------------


class TestOutcomeClassification:
    """The coordinator's ``ReservationOutcome`` exposes a consistent terminal
    state / status / reservation triple for every path."""

    def test_completed_outcome_triple_is_consistent(self) -> None:
        coordinator = _coordinator()
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=_node_contract(),
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(),
        )
        assert outcome.terminal_state is ExecutionTerminalState.COMPLETED
        assert outcome.status is ReservationStatus.COMPLETED
        assert outcome.reservation.status is ReservationStatus.COMPLETED
        assert outcome.reservation.output_sha256 is not None

    def test_unknown_outcome_triple_is_consistent(self) -> None:
        coordinator = _coordinator()
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=_node_contract(),
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(
                raise_on_dispatch=TimeoutError("timeout"),
            ),
        )
        assert outcome.terminal_state is ExecutionTerminalState.UNKNOWN_OUTCOME
        assert outcome.status is ReservationStatus.UNKNOWN_OUTCOME
        assert outcome.reservation.status is ReservationStatus.UNKNOWN_OUTCOME
        assert outcome.reservation.error_code is not None
        assert outcome.reservation.output_sha256 is None

    def test_outcome_carries_dispatch_evidence(self) -> None:
        """Every completed outcome records the single transport attempt that
        produced it."""
        coordinator = _coordinator()
        outcome = coordinator.reserve_or_reuse(
            project_id=_PROJ,
            node_contract=_node_contract(),
            input_payload=_payload_a(),
            now=_T0,
            transport=_FakeTransport(),
        )
        assert outcome.reservation.transport_attempts == 1
        assert outcome.reservation.provider_session_id is not None
