"""Protocol v3 orchestrator PoC — deterministic fakes (Task 2.1, worker 01).

In-memory, deterministic, project/branch-bound fakes for the exact surfaces
the later Task 2.1/2.2 tests need — clock, ids, artifact refs/store,
decisions and reservations.  Properties:

* **Project/branch bound** — every fake is constructed with one
  ``project_id``/``branch_id``; any store operation handed a
  :class:`~pocs.protocol_v3.orchestrator.CaseGraph` bound elsewhere fails
  closed (``CC_BINDING_MISMATCH``).
* **Deterministic** — equal construction + equal call sequence produce equal
  values; ids are derived from a fixed namespace + project/branch + kind +
  logical key, never from counters or wall clocks.
* **Deep immutable on read** — returned records are frozen Pydantic models;
  payloads are validated deep-immutable at write time (mutable nested input
  is rejected with ``CC_INPUT_MUTABLE``) and shared unchanged.  Callers that
  hold plain dicts/lists normalize with :func:`freeze_input` first.
* **Idempotent by logical key** — the same logical key resolves to the same
  record; conflicting re-writes raise a typed error instead of silently
  overwriting (no duplicate semantic effect).
* **Validated state transitions** — reservation state changes are rebuilt
  through the model constructor (no non-validating ``model_copy(update=...)``
  bypass); invalid hashes, empty error codes and inconsistent terminal
  field combinations fail closed.
* **No I/O, provider or storage effects** — pure in-memory; nothing touches
  files, sockets, databases or model providers.

PoC-only artifact; MUST NOT be imported by product code.  Uses only stdlib +
the already-pinned Pydantic and the contract vocabulary from this package.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional, Tuple

from pydantic import ConfigDict, Field, model_validator

from . import (
    AwareDateTime,
    CaseContractError,
    CaseContractModel,
    NonEmptyText,
    PositiveRevision,
    Sha256,
    StableId,
    assert_case_graph_binding,
    assert_deep_immutable,
    canonical_json,
    freeze_input,
)

__all__ = [
    "FakeContractError",
    "FakeClock",
    "FakeIdFactory",
    "ArtifactRef",
    "FakeArtifactStore",
    "PendingDecision",
    "DecisionRecord",
    "FakeDecisionBoard",
    "FakeReservationStatus",
    "FakeReservation",
    "FakeReservationLedger",
    "FakeRuntime",
]

#: Fixed deterministic epoch so two FakeRuntime instances with the same
#: project/branch behave identically (no wall clock, no randomness).
DEFAULT_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
DEFAULT_STEP = timedelta(seconds=1)


class FakeContractError(CaseContractError):
    """Typed, stable failure emitted by the fakes.

    Truly subclasses the contract error (no duplicated field
    implementation): ``code``/``path``/``message`` and the ``<code> at
    <path>: <message>`` formatting come from :class:`CaseContractError`,
    so callers can catch one error family.
    """


class FakeClock:
    """Deterministic clock: fixed epoch + fixed step, advanced per ``now()``.

    ``now()`` returns an aware datetime; the sequence is fully determined by
    construction and call count, so replaying a test reproduces the exact
    timestamps.  No I/O, no wall clock.
    """

    def __init__(
        self,
        epoch: datetime = DEFAULT_EPOCH,
        step: timedelta = DEFAULT_STEP,
    ) -> None:
        if epoch.tzinfo is None or epoch.utcoffset() is None:
            raise ValueError("epoch must be an aware datetime")
        if step <= timedelta(0):
            raise ValueError("step must be a positive timedelta")
        self._epoch = epoch
        self._step = step
        self._index = 0

    def now(self) -> datetime:
        value = self._epoch + self._index * self._step
        self._index += 1
        return value


class FakeIdFactory:
    """Deterministic id generator, bound to one project/branch.

    ``id_for(kind, logical_key)`` = ``namespace_kind_<sha256 prefix>`` where
    the digest covers namespace + project + branch + kind + logical key:
    ids are stable, unique per logical key, and cannot collide across
    projects/branches even when logical keys repeat.
    """

    def __init__(self, project_id: str, branch_id: str, namespace: str = "mw_poc") -> None:
        self._project_id = project_id
        self._branch_id = branch_id
        self._namespace = namespace

    def _digest(self, kind: str, logical_key: str) -> str:
        material = f"{self._namespace}|{self._project_id}|{self._branch_id}|{kind}|{logical_key}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]

    def id_for(self, kind: str, logical_key: str) -> str:
        return f"{self._namespace}_{kind}_{self._digest(kind, logical_key)}"

    def artifact_id(self, logical_key: str) -> str:
        return self.id_for("artifact", logical_key)

    def decision_id(self, logical_key: str) -> str:
        return self.id_for("decision", logical_key)

    def reservation_id(self, logical_key: str) -> str:
        return self.id_for("reservation", logical_key)


class _FakeModel(CaseContractModel):
    """Frozen, closed fake model with the validated ``model_copy`` override.

    Inherits the contract base's ``model_copy``: any ``update`` rebuilds
    through the model constructor and re-runs every field/model validator,
    so fakes cannot smuggle invalid state (bad hashes, empty error codes,
    inconsistent terminal combinations) past a non-validating copy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ArtifactRef(_FakeModel):
    """Immutable reference to one stored artifact; payload is frozen."""

    artifact_id: NonEmptyText
    logical_key: NonEmptyText
    node_id: StableId
    schema_name: NonEmptyText
    project_id: StableId
    branch_id: StableId
    payload_sha256: Sha256
    created_at: AwareDateTime
    payload: Any = None  # frozen JSON-compatible value (never mutated)

    @model_validator(mode="after")
    def _validate_payload_deep_immutable(self) -> "ArtifactRef":
        """Reject mutable nested payload at construction (``CC_INPUT_MUTABLE``).

        Direct construction (and any validated rebuild) of an artifact with
        a plain dict/list payload fails closed instead of accepting mutable
        state that contradicts the immutable-artifact read contract.  Callers
        normalize with :func:`~pocs.protocol_v3.orchestrator.freeze_input`
        first; the store path already enforces this before constructing.
        """
        if self.payload is not None:
            assert_deep_immutable(self.payload, path="payload")
        return self


class FakeArtifactStore:
    """In-memory artifact store, idempotent by logical key.

    ``put`` validates project/branch binding, node declaration and
    output-schema match (``CC_NODE_UNKNOWN`` / ``CC_SCHEMA_MISMATCH``) and
    deep immutability, then stores the payload; mutable nested input is
    rejected (``CC_INPUT_MUTABLE``) — callers normalize with
    :func:`~pocs.protocol_v3.orchestrator.freeze_input` first.  A second
    ``put`` with the same logical key returns the existing artifact when
    content matches and fails closed (``FK_IDEMPOTENCY_CONFLICT``) when it
    does not — no silent overwrite, no duplicate artifact lineage.
    """

    def __init__(
        self,
        project_id: str,
        branch_id: str,
        ids: Optional[FakeIdFactory] = None,
        clock: Optional[FakeClock] = None,
    ) -> None:
        self.project_id = project_id
        self.branch_id = branch_id
        self._ids = ids or FakeIdFactory(project_id, branch_id)
        self._clock = clock or FakeClock()
        self._store: dict[str, ArtifactRef] = {}

    def put(
        self,
        graph,
        *,
        node_id: str,
        logical_key: str,
        schema_name: str,
        payload: Any,
    ) -> ArtifactRef:
        assert_case_graph_binding(graph, self.project_id, self.branch_id)
        # Unknown node ids fail closed (CC_NODE_UNKNOWN via graph.node);
        # the artifact schema must equal the node's declared output schema
        # (CC_SCHEMA_MISMATCH) — existing in the graph is not sufficient.
        node = graph.node(node_id)
        if schema_name != node.output_schema:
            raise FakeContractError(
                "CC_SCHEMA_MISMATCH",
                f"artifacts/{logical_key}/schema_name",
                f"schema {schema_name!r} does not match node {node_id!r} "
                f"declared output schema {node.output_schema!r}",
            )
        assert_deep_immutable(payload, path=f"artifacts/{logical_key}/payload")
        digest = hashlib.sha256(
            canonical_json(payload).encode("utf-8")
        ).hexdigest()
        existing = self._store.get(logical_key)
        if existing is not None:
            if (
                existing.node_id == node_id
                and existing.schema_name == schema_name
                and existing.payload_sha256 == digest
            ):
                return existing
            raise FakeContractError(
                "FK_IDEMPOTENCY_CONFLICT",
                f"artifacts/{logical_key}",
                "logical key already holds a different artifact",
            )
        ref = ArtifactRef(
            artifact_id=self._ids.artifact_id(logical_key),
            logical_key=logical_key,
            node_id=node_id,
            schema_name=schema_name,
            project_id=self.project_id,
            branch_id=self.branch_id,
            payload_sha256=digest,
            created_at=self._clock.now(),
            payload=payload,
        )
        self._store[logical_key] = ref
        return ref

    def get(self, logical_key: str) -> Optional[ArtifactRef]:
        return self._store.get(logical_key)

    def contains(self, logical_key: str) -> bool:
        return logical_key in self._store

    def iter_artifacts(self) -> Tuple[ArtifactRef, ...]:
        return tuple(
            sorted(self._store.values(), key=lambda ref: ref.logical_key)
        )

    def count(self) -> int:
        return len(self._store)


class PendingDecision(_FakeModel):
    """One open concurrent-decision claim (never executed, just represented)."""

    pending_decision_id: NonEmptyText
    decision_key: NonEmptyText
    actor: NonEmptyText
    project_id: StableId
    branch_id: StableId
    claimed_at: AwareDateTime


class DecisionRecord(_FakeModel):
    """Immutable reason-coded decision (mirrors the product DecisionRecord
    shape minimally: stable key + value snapshot + reason + actor)."""

    decision_id: NonEmptyText
    decision_key: NonEmptyText
    project_id: StableId
    branch_id: StableId
    snapshot_sha256: Sha256
    reason: NonEmptyText
    actor: NonEmptyText
    decided_at: AwareDateTime
    value: Any = None  # frozen JSON-compatible value

    @model_validator(mode="after")
    def _validate_value_deep_immutable(self) -> "DecisionRecord":
        """Reject mutable nested value at construction (``CC_INPUT_MUTABLE``).

        Direct construction (and any validated rebuild) of a decision with a
        plain dict/list value fails closed instead of accepting mutable
        state.  Callers normalize with
        :func:`~pocs.protocol_v3.orchestrator.freeze_input` first; the board
        path already enforces this before constructing.
        """
        if self.value is not None:
            assert_deep_immutable(self.value, path="value")
        return self


class FakeDecisionBoard:
    """In-memory decision board, idempotent by decision_key.

    ``claim`` opens a pending decision for one actor (used to *represent*
    the concurrent-decision injection); a second actor claiming the same key
    fails closed with ``FK_CONCURRENT_DECISION``.  ``record`` commits a
    decision (payload must be deep immutable — mutable nested input is
    rejected with ``CC_INPUT_MUTABLE``); conflicting re-records or recording
    over a different actor's open claim fail closed.  Decisions are never
    double-applied.
    """

    def __init__(
        self,
        project_id: str,
        branch_id: str,
        ids: Optional[FakeIdFactory] = None,
        clock: Optional[FakeClock] = None,
    ) -> None:
        self.project_id = project_id
        self.branch_id = branch_id
        self._ids = ids or FakeIdFactory(project_id, branch_id)
        self._clock = clock or FakeClock()
        self._records: dict[str, DecisionRecord] = {}
        self._pending: dict[str, PendingDecision] = {}

    def claim(self, graph, *, decision_key: str, actor: str) -> PendingDecision:
        assert_case_graph_binding(graph, self.project_id, self.branch_id)
        recorded = self._records.get(decision_key)
        if recorded is not None:
            raise FakeContractError(
                "FK_IDEMPOTENCY_CONFLICT",
                f"decisions/{decision_key}",
                "cannot claim an already-recorded decision key",
            )
        existing = self._pending.get(decision_key)
        if existing is not None:
            if existing.actor == actor:
                return existing
            raise FakeContractError(
                "FK_CONCURRENT_DECISION",
                f"decisions/{decision_key}",
                f"concurrent claim by {actor!r} while {existing.actor!r} holds the key",
            )
        pending = PendingDecision(
            pending_decision_id=self._ids.decision_id(f"pending:{decision_key}"),
            decision_key=decision_key,
            actor=actor,
            project_id=self.project_id,
            branch_id=self.branch_id,
            claimed_at=self._clock.now(),
        )
        self._pending[decision_key] = pending
        return pending

    def record(
        self,
        graph,
        *,
        decision_key: str,
        value: Any,
        reason: str,
        actor: str,
    ) -> DecisionRecord:
        assert_case_graph_binding(graph, self.project_id, self.branch_id)
        assert_deep_immutable(value, path=f"decisions/{decision_key}/value")
        snapshot = hashlib.sha256(
            canonical_json(value).encode("utf-8")
        ).hexdigest()
        existing = self._records.get(decision_key)
        if existing is not None:
            if (
                existing.snapshot_sha256 == snapshot
                and existing.reason == reason
                and existing.actor == actor
            ):
                return existing
            raise FakeContractError(
                "FK_IDEMPOTENCY_CONFLICT",
                f"decisions/{decision_key}",
                "decision key already holds a different decision",
            )
        pending = self._pending.get(decision_key)
        if pending is not None and pending.actor != actor:
            raise FakeContractError(
                "FK_CONCURRENT_DECISION",
                f"decisions/{decision_key}",
                f"cannot record while {pending.actor!r} holds an open concurrent claim",
            )
        record = DecisionRecord(
            decision_id=self._ids.decision_id(decision_key),
            decision_key=decision_key,
            project_id=self.project_id,
            branch_id=self.branch_id,
            snapshot_sha256=snapshot,
            reason=reason,
            actor=actor,
            decided_at=self._clock.now(),
            value=value,
        )
        self._records[decision_key] = record
        self._pending.pop(decision_key, None)
        return record

    def get(self, decision_key: str) -> Optional[DecisionRecord]:
        return self._records.get(decision_key)

    def pending_for(self, decision_key: str) -> Optional[PendingDecision]:
        return self._pending.get(decision_key)

    def iter_decisions(self) -> Tuple[DecisionRecord, ...]:
        return tuple(
            sorted(self._records.values(), key=lambda record: record.decision_key)
        )


class FakeReservationStatus(str, Enum):
    """Closed reservation states (mirror product ``ReservationStatus``)."""

    RESERVED = "reserved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN_OUTCOME = "unknown_outcome"


_TERMINAL_STATUSES = frozenset(
    {
        FakeReservationStatus.COMPLETED,
        FakeReservationStatus.FAILED,
        FakeReservationStatus.UNKNOWN_OUTCOME,
    }
)

_RESERVATION_TRANSITIONS = {
    FakeReservationStatus.RESERVED: frozenset(
        {FakeReservationStatus.RUNNING, FakeReservationStatus.FAILED}
    ),
    FakeReservationStatus.RUNNING: frozenset(
        {
            FakeReservationStatus.COMPLETED,
            FakeReservationStatus.FAILED,
            FakeReservationStatus.UNKNOWN_OUTCOME,
        }
    ),
}


class FakeReservation(_FakeModel):
    """Immutable reservation record mirroring the product
    ``ExecutionReservation`` shape (logical key + idempotency key + input
    hash + attempt + status), without any storage/provider semantics."""

    reservation_id: NonEmptyText
    logical_call_id: NonEmptyText
    idempotency_key: NonEmptyText
    node_id: StableId
    project_id: StableId
    branch_id: StableId
    input_sha256: Sha256
    attempt: PositiveRevision
    status: FakeReservationStatus = FakeReservationStatus.RESERVED
    terminal_state: Optional[str] = None
    output_sha256: Optional[Sha256] = None
    error_code: Optional[NonEmptyText] = None
    reserved_at: AwareDateTime
    updated_at: AwareDateTime

    @model_validator(mode="after")
    def _validate_terminal_state(self) -> "FakeReservation":
        """Enforce the product ``ExecutionReservation`` terminal contract.

        Terminal statuses require a matching ``terminal_state``; completed
        requires an output hash and no error code; failed/unknown require an
        error code and no output hash; non-terminal reservations cannot
        carry terminal results.  Because every state change is a fully
        re-validated rebuild, an inconsistent combination can never enter
        the ledger.
        """
        if self.status in _TERMINAL_STATUSES:
            if self.terminal_state is None or self.terminal_state != self.status.value:
                raise FakeContractError(
                    "FK_TERMINAL_STATE",
                    f"reservations/{self.logical_call_id}",
                    f"terminal_state must match terminal status {self.status.value}",
                )
        elif self.terminal_state is not None:
            raise FakeContractError(
                "FK_TERMINAL_STATE",
                f"reservations/{self.logical_call_id}",
                "non-terminal reservations must not declare terminal_state",
            )
        if self.status is FakeReservationStatus.COMPLETED:
            if self.output_sha256 is None or self.error_code is not None:
                raise FakeContractError(
                    "FK_TERMINAL_FIELDS",
                    f"reservations/{self.logical_call_id}",
                    "completed reservations require an output hash and no error code",
                )
        elif self.status in {
            FakeReservationStatus.FAILED,
            FakeReservationStatus.UNKNOWN_OUTCOME,
        }:
            if self.error_code is None or self.output_sha256 is not None:
                raise FakeContractError(
                    "FK_TERMINAL_FIELDS",
                    f"reservations/{self.logical_call_id}",
                    "failed/unknown reservations require an error code and no output hash",
                )
        else:
            if self.output_sha256 is not None or self.error_code is not None:
                raise FakeContractError(
                    "FK_TERMINAL_FIELDS",
                    f"reservations/{self.logical_call_id}",
                    "non-terminal reservations cannot carry terminal results",
                )
        return self


class FakeReservationLedger:
    """In-memory reservation ledger, idempotent by
    ``(logical_call_id, idempotency_key)``.

    * ``reserve`` is idempotent: re-reserving the same logical call returns
      the existing reservation (duplicate-resume representation) and never
      creates a second attempt.
    * ``resume`` returns the completed reservation without re-execution;
      FAILED and UNKNOWN_OUTCOME reservations fail closed
      (``FK_TERMINAL_FAILED`` / ``FK_UNKNOWN_OUTCOME``) — an unknown outcome
      is never auto-redispatched (frozen plan principle 11).
    * every state change is a single fully re-validated rebuild (no
      non-validating ``model_copy(update=...)``) and a model validator
      enforces the product terminal contract: completed needs an output
      hash and no error code; failed/unknown need an error code and no
      output hash; terminal states are final.
    """

    def __init__(
        self,
        project_id: str,
        branch_id: str,
        ids: Optional[FakeIdFactory] = None,
        clock: Optional[FakeClock] = None,
    ) -> None:
        self.project_id = project_id
        self.branch_id = branch_id
        self._ids = ids or FakeIdFactory(project_id, branch_id)
        self._clock = clock or FakeClock()
        self._store: dict[Tuple[str, str], FakeReservation] = {}

    def _key(self, logical_call_id: str, idempotency_key: str) -> Tuple[str, str]:
        return (logical_call_id, idempotency_key)

    def reserve(
        self,
        graph,
        *,
        node_id: str,
        logical_call_id: str,
        idempotency_key: str,
        input_sha256: str,
    ) -> FakeReservation:
        assert_case_graph_binding(graph, self.project_id, self.branch_id)
        graph.node(node_id)  # unknown node ids fail closed (CC_NODE_UNKNOWN)
        key = self._key(logical_call_id, idempotency_key)
        existing = self._store.get(key)
        if existing is not None:
            return existing  # duplicate resume: same logical key, no new attempt
        now = self._clock.now()
        reservation = FakeReservation(
            reservation_id=self._ids.reservation_id(
                f"{logical_call_id}:{idempotency_key}"
            ),
            logical_call_id=logical_call_id,
            idempotency_key=idempotency_key,
            node_id=node_id,
            project_id=self.project_id,
            branch_id=self.branch_id,
            input_sha256=input_sha256,
            attempt=1,
            reserved_at=now,
            updated_at=now,
        )
        self._store[key] = reservation
        return reservation

    def _assert_transition(
        self, reservation: FakeReservation, target: FakeReservationStatus
    ) -> None:
        """Fail closed unless *reservation* may legally move to *target*."""
        if reservation.status in _TERMINAL_STATUSES:
            raise FakeContractError(
                "FK_INVALID_TRANSITION",
                f"reservations/{reservation.logical_call_id}",
                f"terminal reservation cannot transition from {reservation.status.value}",
            )
        allowed = _RESERVATION_TRANSITIONS[reservation.status]
        if target not in allowed:
            raise FakeContractError(
                "FK_INVALID_TRANSITION",
                f"reservations/{reservation.logical_call_id}",
                f"cannot transition {reservation.status.value} -> {target.value}",
            )

    def start(self, reservation_id: str) -> FakeReservation:
        reservation = self._by_id(reservation_id)
        self._assert_transition(reservation, FakeReservationStatus.RUNNING)
        updated = reservation.model_copy(
            update={
                "status": FakeReservationStatus.RUNNING,
                "updated_at": self._clock.now(),
            }
        )
        self._replace(reservation, updated)
        return updated

    def complete(self, reservation_id: str, output_sha256: str) -> FakeReservation:
        reservation = self._by_id(reservation_id)
        self._assert_transition(reservation, FakeReservationStatus.COMPLETED)
        # One fully re-validated rebuild: status, terminal_state,
        # output_sha256 and error_code are checked together, so a
        # non-64-hex output hash or an inconsistent terminal combination
        # fails closed here instead of being accepted by a
        # non-validating model_copy.
        updated = reservation.model_copy(
            update={
                "status": FakeReservationStatus.COMPLETED,
                "terminal_state": "completed",
                "output_sha256": output_sha256,
                "error_code": None,
                "updated_at": self._clock.now(),
            }
        )
        self._replace(reservation, updated)
        return updated

    def fail(self, reservation_id: str, error_code: str) -> FakeReservation:
        reservation = self._by_id(reservation_id)
        self._assert_transition(reservation, FakeReservationStatus.FAILED)
        updated = reservation.model_copy(
            update={
                "status": FakeReservationStatus.FAILED,
                "terminal_state": "failed",
                "error_code": error_code,
                "output_sha256": None,
                "updated_at": self._clock.now(),
            }
        )
        self._replace(reservation, updated)
        return updated

    def mark_unknown_outcome(
        self, reservation_id: str, error_code: str
    ) -> FakeReservation:
        reservation = self._by_id(reservation_id)
        self._assert_transition(
            reservation, FakeReservationStatus.UNKNOWN_OUTCOME
        )
        updated = reservation.model_copy(
            update={
                "status": FakeReservationStatus.UNKNOWN_OUTCOME,
                "terminal_state": "unknown_outcome",
                "error_code": error_code,
                "output_sha256": None,
                "updated_at": self._clock.now(),
            }
        )
        self._replace(reservation, updated)
        return updated

    def resume(self, *, logical_call_id: str, idempotency_key: str) -> FakeReservation:
        key = self._key(logical_call_id, idempotency_key)
        existing = self._store.get(key)
        if existing is None:
            raise FakeContractError(
                "FK_NOT_FOUND",
                f"reservations/{logical_call_id}",
                "no reservation exists for the logical call",
            )
        if existing.status is FakeReservationStatus.COMPLETED:
            return existing  # no re-execution: completed lineage is final
        if existing.status is FakeReservationStatus.UNKNOWN_OUTCOME:
            raise FakeContractError(
                "FK_UNKNOWN_OUTCOME",
                f"reservations/{logical_call_id}",
                "unknown_outcome must not be auto-redispatched",
            )
        if existing.status is FakeReservationStatus.FAILED:
            raise FakeContractError(
                "FK_TERMINAL_FAILED",
                f"reservations/{logical_call_id}",
                "failed reservation requires explicit owner repair, not resume",
            )
        return existing  # reserved/running: caller may continue the same attempt

    def get(self, logical_call_id: str, idempotency_key: str) -> Optional[FakeReservation]:
        return self._store.get(self._key(logical_call_id, idempotency_key))

    def iter_reservations(self) -> Tuple[FakeReservation, ...]:
        return tuple(
            sorted(
                self._store.values(), key=lambda item: item.logical_call_id
            )
        )

    def count(self) -> int:
        return len(self._store)

    def _by_id(self, reservation_id: str) -> FakeReservation:
        for reservation in self._store.values():
            if reservation.reservation_id == reservation_id:
                return reservation
        raise FakeContractError(
            "FK_NOT_FOUND",
            f"reservations/{reservation_id}",
            "unknown reservation id",
        )

    def _replace(
        self, old: FakeReservation, new: FakeReservation
    ) -> None:
        self._store[self._key(old.logical_call_id, old.idempotency_key)] = new


class FakeRuntime:
    """One project/branch-bound bundle of all deterministic fakes.

    Constructing two ``FakeRuntime`` instances with the same project/branch
    (and optional epoch/step) yields byte-identical behavior, which is what
    the later deterministic-replay tests rely on.
    """

    def __init__(
        self,
        project_id: str,
        branch_id: str,
        *,
        epoch: datetime = DEFAULT_EPOCH,
        step: timedelta = DEFAULT_STEP,
    ) -> None:
        self.project_id = project_id
        self.branch_id = branch_id
        self.clock = FakeClock(epoch=epoch, step=step)
        self.ids = FakeIdFactory(project_id, branch_id)
        self.artifacts = FakeArtifactStore(
            project_id, branch_id, ids=self.ids, clock=self.clock
        )
        self.decisions = FakeDecisionBoard(
            project_id, branch_id, ids=self.ids, clock=self.clock
        )
        self.reservations = FakeReservationLedger(
            project_id, branch_id, ids=self.ids, clock=self.clock
        )

    def bound(self) -> Tuple[str, str]:
        return (self.project_id, self.branch_id)
