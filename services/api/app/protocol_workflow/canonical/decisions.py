"""Pure DecisionRecord idempotent reducer with CAS discipline.

A :class:`DecisionRecord` is the durable, content-addressed proof that a
particular actor adopted a particular option for a particular decision key at a
particular point in the canonical state machine.  Because retries, duplicate
clicks and worker restarts all re-emit the *same* logical decision, the
authority layer must recognise an already-recorded decision and return the
original record rather than creating a second one.

This module provides the pure, stateless classification and transition logic
that the application service and repository adapter compose with persistence.
It enforces the Protocol v3 decision invariants:

1. **CAS replay** — two operations share the same CAS identity when and only
   when they replay the same ``(decision_record_id, snapshot_sha256,
   expected_state_revision)`` triple.  Replaying that triple with the *same*
   material payload returns the exact prior record; it never creates a second
   ledger entry or advances any revision.
2. **Typed conflict** — the same CAS triple presented with a *different*
   material payload is a contract violation, not an idempotent path.  It fails
   with :class:`DecisionPayloadConflictError`.
3. **Lifecycle discipline** — a decision may only move along the canonical
   state edges ``confirmed → frozen → superseded/quarantined``.  Same-state
   re-assertions are legal no-ops; illegal edges fail with
   :class:`IllegalDecisionTransitionError`.
4. **Purity** — the reducer receives explicit identity and time inputs, returns
   new immutable :class:`DecisionRecord` instances, and touches no repository,
   filesystem, network, clock or model.

The ``DecisionLedger`` value object is an immutable, append-only view over the
known decisions for a single decision key.  All mutating operations return a
*new* ledger; the receiver is never mutated.  This keeps the decision
classification logic testable without any storage dependency.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DecisionRecord,
    assert_canonical_state_transition,
)

from .hashing import decision_cas_identity

__all__ = [
    "DecisionCasError",
    "DecisionLedger",
    "DecisionPayloadConflictError",
    "DecisionReducer",
    "DecisionReplayResult",
    "IllegalDecisionTransitionError",
]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------
#
# These mirror the StudyDefinition reducer's discipline: they carry the
# identity context the application service needs for audit and UI translation,
# but they never import the user-facing error registry.  Keeping them local
# prevents the pure reducer from becoming coupled to UI copy.


class DecisionCasError(RuntimeError):
    """Base class for DecisionRecord CAS discipline failures.

    Carries the CAS identity triple so the caller can attach it to audit
    context.
    """

    __slots__ = (
        "decision_record_id",
        "snapshot_sha256",
        "expected_state_revision",
        "detail",
    )

    def __init__(
        self,
        decision_record_id: str,
        snapshot_sha256: str,
        expected_state_revision: int,
        detail: str,
    ) -> None:
        self.decision_record_id = decision_record_id
        self.snapshot_sha256 = snapshot_sha256
        self.expected_state_revision = expected_state_revision
        self.detail = detail
        super().__init__(detail)


class DecisionPayloadConflictError(DecisionCasError):
    """Raised when the same CAS identity is replayed with a different payload.

    The ``(decision_record_id, snapshot_sha256, expected_state_revision)``
    triple matches an already-recorded decision, but the incoming material hash
    differs.  This is a contract violation — a retry must resend identical
    bytes — not an idempotent replay.
    """

    __slots__ = ("cas_identity", "existing_decision_sha256", "incoming_decision_sha256")

    def __init__(
        self,
        decision_record_id: str,
        snapshot_sha256: str,
        expected_state_revision: int,
        cas_identity: str,
        existing_decision_sha256: str,
        incoming_decision_sha256: str,
    ) -> None:
        self.cas_identity = cas_identity
        self.existing_decision_sha256 = existing_decision_sha256
        self.incoming_decision_sha256 = incoming_decision_sha256
        super().__init__(
            decision_record_id,
            snapshot_sha256,
            expected_state_revision,
            (
                f"conflicting payload under CAS identity {cas_identity}: "
                f"existing={existing_decision_sha256} "
                f"incoming={incoming_decision_sha256}"
            ),
        )


class IllegalDecisionTransitionError(DecisionCasError):
    """Raised when a decision lifecycle transition violates the canonical
    state machine.

    Decisions may only advance along ``confirmed → frozen →
    superseded/quarantined``.  Same-state re-assertions are legal idempotent
    no-ops; any other edge is rejected.
    """

    __slots__ = ("current_state", "target_state")

    def __init__(
        self,
        decision_record_id: str,
        snapshot_sha256: str,
        expected_state_revision: int,
        current_state: CanonicalState,
        target_state: CanonicalState,
    ) -> None:
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(
            decision_record_id,
            snapshot_sha256,
            expected_state_revision,
            (
                f"illegal decision transition: "
                f"{current_state.value} -> {target_state.value}"
            ),
        )


# ---------------------------------------------------------------------------
# Immutable decision ledger
# ---------------------------------------------------------------------------


class DecisionReplayResult:
    """Immutable outcome of classifying an incoming decision against the
    ledger.

    ``replayed`` is ``True`` for an exact idempotent replay; in that case
    ``effective`` is the previously recorded record and ``ledger`` is the
    receiver unchanged.  ``replayed`` is ``False`` for a fresh record; in that
    case ``effective`` is the incoming record and ``ledger`` is the advanced
    ledger.
    """

    __slots__ = ("effective", "ledger", "replayed")

    def __init__(
        self,
        effective: DecisionRecord,
        ledger: "DecisionLedger",
        replayed: bool,
    ) -> None:
        self.effective = effective
        self.ledger = ledger
        self.replayed = replayed


class DecisionLedger:
    """Immutable, append-only view over the recorded decisions for one
    decision key.

    The ledger is indexed by CAS identity so that replay classification is a
    pure lookup.  Instances are never mutated in place; every mutating
    operation returns a *new* :class:`DecisionLedger`.

    Reconstruction discipline: a ledger built from a record tuple (e.g. rebuilt
    from an event stream) must fail closed if two records share the same CAS
    identity but carry *different* material — that is a corrupted or
    divergent stream, not a benign duplicate.  Exact duplicates (same identity
    *and* same material) are deduplicated deterministically: the first wins
    the identity slot and later exact copies are dropped from the ordered
    history, so replay is stable and idempotent.
    """

    __slots__ = ("_records", "_by_identity")

    def __init__(
        self,
        records: tuple[DecisionRecord, ...] = (),
    ) -> None:
        self._records: tuple[DecisionRecord, ...] = ()
        self._by_identity: dict[str, DecisionRecord] = {}
        for record in records:
            self._index_record(record)

    def _index_record(self, record: DecisionRecord) -> None:
        """Append *record* to the ordered history and identity index.

        Fail closed on a conflicting material under the same CAS identity;
        silently drop an exact duplicate (same identity + same material).
        """

        identity = _cas_identity_of(record)
        existing = self._by_identity.get(identity)
        if existing is not None:
            if existing.material_sha256() != record.material_sha256():
                raise DecisionPayloadConflictError(
                    decision_record_id=record.decision_record_id,
                    snapshot_sha256=record.snapshot_sha256,
                    expected_state_revision=record.expected_state_revision,
                    cas_identity=identity,
                    existing_decision_sha256=existing.material_sha256(),
                    incoming_decision_sha256=record.material_sha256(),
                )
            # Exact duplicate: keep the first, drop this copy.
            return
        self._records = (*self._records, record)
        self._by_identity[identity] = record

    @property
    def records(self) -> tuple[DecisionRecord, ...]:
        """Recorded decisions in insertion order (exact duplicates removed)."""
        return self._records

    def is_empty(self) -> bool:
        return not self._records

    def find_by_identity(
        self,
        decision_record_id: str,
        snapshot_sha256: str,
        expected_state_revision: int,
    ) -> Optional[DecisionRecord]:
        """Return the recorded decision for the CAS triple, or ``None``."""
        identity = decision_cas_identity(
            decision_record_id,
            snapshot_sha256,
            expected_state_revision,
        )
        return self._by_identity.get(identity)

    def _with(self, record: DecisionRecord) -> "DecisionLedger":
        """Return a new ledger with *record* appended.

        The caller (:meth:`DecisionReducer.replay_or_record`) guarantees the
        record's identity is either absent or exactly equal, so this path never
        raises.  Reconstruction-time conflict detection lives in
        :meth:`__init__` via :meth:`_index_record`.
        """

        clone = DecisionLedger()
        for existing in self._records:
            clone._index_record(existing)
        clone._index_record(record)
        return clone


def _cas_identity_of(record: DecisionRecord) -> str:
    return decision_cas_identity(
        record.decision_record_id,
        record.snapshot_sha256,
        record.expected_state_revision,
    )


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


class DecisionReducer:
    """Pure, stateless reducer for :class:`DecisionRecord` CAS replay and
    lifecycle transitions.

    Instances are safe to share.  Every method is a pure function that returns
    new immutable values; the receiver is never mutated.
    """

    __slots__ = ()

    # ------------------------------------------------------------------
    # Idempotent CAS replay / record
    # ------------------------------------------------------------------

    def replay_or_record(
        self,
        ledger: DecisionLedger,
        incoming: DecisionRecord,
    ) -> DecisionReplayResult:
        """Record *incoming* idempotently under CAS discipline.

        Returns a :class:`DecisionReplayResult`:

        * ``replayed`` is ``True`` when the CAS identity already matches a
          recorded decision *and* the material payload is identical.  In that
          case ``effective`` is the previously recorded record and ``ledger``
          is the input ledger unchanged.
        * ``replayed`` is ``False`` on a fresh record — ``effective`` is
          ``incoming`` and ``ledger`` is the advanced ledger.

        Raises :class:`DecisionPayloadConflictError` if the CAS identity
        matches a recorded decision but the material payload differs.
        """

        existing = ledger.find_by_identity(
            incoming.decision_record_id,
            incoming.snapshot_sha256,
            incoming.expected_state_revision,
        )
        if existing is None:
            advanced = ledger._with(incoming)
            return DecisionReplayResult(incoming, advanced, replayed=False)

        existing_hash = existing.material_sha256()
        incoming_hash = incoming.material_sha256()
        if existing_hash != incoming_hash:
            raise DecisionPayloadConflictError(
                decision_record_id=incoming.decision_record_id,
                snapshot_sha256=incoming.snapshot_sha256,
                expected_state_revision=incoming.expected_state_revision,
                cas_identity=_cas_identity_of(incoming),
                existing_decision_sha256=existing_hash,
                incoming_decision_sha256=incoming_hash,
            )
        return DecisionReplayResult(existing, ledger, replayed=True)

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def transition(
        self,
        record: DecisionRecord,
        target_state: CanonicalState,
        *,
        now: datetime,
    ) -> DecisionRecord:
        """Return a new :class:`DecisionRecord` advanced to *target_state*.

        Same-state re-assertions are legal idempotent no-ops and return the
        original record unchanged.  Illegal canonical-state edges raise
        :class:`IllegalDecisionTransitionError`.

        *now* is the explicit timestamp for the transitioned record's
        ``decided_at``; the reducer never consults a clock.
        """

        if record.canonical_state is target_state:
            return record
        try:
            resolved = assert_canonical_state_transition(
                record.canonical_state,
                target_state,
            )
        except ValueError as exc:
            raise IllegalDecisionTransitionError(
                decision_record_id=record.decision_record_id,
                snapshot_sha256=record.snapshot_sha256,
                expected_state_revision=record.expected_state_revision,
                current_state=record.canonical_state,
                target_state=target_state,
            ) from exc
        return _replace_decision(record, canonical_state=resolved, decided_at=now)

    def freeze(
        self,
        record: DecisionRecord,
        *,
        now: datetime,
    ) -> DecisionRecord:
        """Advance *record* to ``FROZEN``; idempotent if already frozen."""
        return self.transition(record, CanonicalState.FROZEN, now=now)

    def supersede(
        self,
        record: DecisionRecord,
        *,
        now: datetime,
    ) -> DecisionRecord:
        """Advance *record* to ``SUPERSEDED``; idempotent if already superseded."""
        return self.transition(record, CanonicalState.SUPERSEDED, now=now)

    def quarantine(
        self,
        record: DecisionRecord,
        *,
        now: datetime,
    ) -> DecisionRecord:
        """Advance *record* to ``QUARANTINED``; idempotent if already quarantined."""
        return self.transition(record, CanonicalState.QUARANTINED, now=now)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------


def _replace_decision(
    record: DecisionRecord,
    *,
    canonical_state: CanonicalState,
    decided_at: datetime,
) -> DecisionRecord:
    """Return a copy of *record* with the overridden fields.

    Uses ``model_copy`` so the frozen base is respected and the material hash
    is recomputed on demand by the new instance.
    """

    return record.model_copy(
        update={
            "canonical_state": canonical_state,
            "decided_at": decided_at,
        }
    )
