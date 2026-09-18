"""Pure StudyDefinition reducer with CAS discipline.

The reducer is the only path that advances a :class:`StudyDefinitionV3`
revision.  It enforces three invariants from the Protocol v3 design:

1. **Unique fact authority** — the StudyDefinition is the only fact store; no
   caller can silently overwrite a frozen or confirmed fact.
2. **CAS replay** — replaying the same ``(decision_record_id,
   snapshot_sha256, expected_state_revision)`` triple returns the exact prior
   decision and produces no new revision.  This makes duplicate clicks, worker
   retries and restarts idempotent.
3. **Typed failure** — stale expected revision, conflicting payload (DecisionRecord
   material or fact updates) under the same CAS key, and frozen-fact overwrite
   each raise a distinct stable error.  The application service is responsible
   for translating these into :class:`ProtocolWorkflowError` types for the UI;
   this reducer never imports the error registry, keeping it free of UI/audit
   coupling.

The reducer is pure: it receives explicit identity, time and expected-revision
inputs, returns a new :class:`StudyDefinitionV3`, and touches no repository,
filesystem, network, clock or model.

Idempotency is proved by an explicit :class:`DecisionEffectLedger` — an
immutable, append-only mapping from CAS identity to the *exact* effect payload
(DecisionRecord material hash + fact-update hash).  The ledger is a pure input/
output: the caller threads it through reducer calls the same way it threads the
StudyDefinition itself.  ``decision_record_ids`` on the StudyDefinition is a
convenience lineage pointer but is **not** sufficient to prove the prior payload;
only the effect ledger can.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Optional

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DecisionRecord,
    JsonValue,
    StudyDefinitionV3,
)

from .hashing import (
    canonical_revision_hash,
    decision_cas_identity,
    exact_payload_sha256,
    material_sha256,
)

__all__ = [
    "StudyDefinitionCasError",
    "RevisionStaleError",
    "DecisionPayloadConflictError",
    "FrozenFactOverwriteError",
    "StudyDefinitionReducer",
    "DecisionEffectLedger",
    "DecisionEffect",
]


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------
#
# These are intentionally local to the canonical reducer layer.  They carry the
# identity context the application service needs to build an audit record and a
# UI error, but they do not (and must not) import the user-facing error
# registry.  Keeping them separate prevents the pure reducer from becoming
# coupled to UI copy.


class StudyDefinitionCasError(RuntimeError):
    """Base class for StudyDefinition CAS discipline failures.

    Carries ``study_definition_id`` and ``expected_revision`` so the caller can
    attach them to audit context.
    """

    __slots__ = ("study_definition_id", "expected_revision", "detail")

    def __init__(
        self,
        study_definition_id: str,
        expected_revision: int,
        detail: str,
    ) -> None:
        self.study_definition_id = study_definition_id
        self.expected_revision = expected_revision
        self.detail = detail
        super().__init__(detail)


class RevisionStaleError(StudyDefinitionCasError):
    """Raised when the caller's expected revision does not match current.

    The caller assumed ``expected_state_revision`` was current, but the
    definition is already at ``actual_revision``.  The operation must be
    retried against the latest revision.
    """

    __slots__ = ("actual_revision",)

    def __init__(
        self,
        study_definition_id: str,
        expected_revision: int,
        actual_revision: int,
    ) -> None:
        self.actual_revision = actual_revision
        super().__init__(
            study_definition_id,
            expected_revision,
            (
                f"stale expected revision {expected_revision}; "
                f"current is {actual_revision}"
            ),
        )


class DecisionPayloadConflictError(StudyDefinitionCasError):
    """Raised when the same CAS identity is replayed with a different payload.

    The ``(decision_record_id, snapshot_sha256, expected_state_revision)``
    triple matches an already-applied decision, but either the incoming
    :class:`DecisionRecord` material hash or the fact-update hash differs from
    the recorded effect.  This is a contract violation — a retry must resend
    identical bytes — not an idempotent path.

    ``conflict_kind`` is ``"decision_record"`` when the DecisionRecord material
    differs, or ``"fact_updates"`` when the fact-update payload differs.
    """

    __slots__ = (
        "cas_identity",
        "conflict_kind",
        "existing_sha256",
        "incoming_sha256",
    )

    def __init__(
        self,
        study_definition_id: str,
        expected_revision: int,
        cas_identity: str,
        conflict_kind: str,
        existing_sha256: str,
        incoming_sha256: str,
    ) -> None:
        self.cas_identity = cas_identity
        self.conflict_kind = conflict_kind
        self.existing_sha256 = existing_sha256
        self.incoming_sha256 = incoming_sha256
        super().__init__(
            study_definition_id,
            expected_revision,
            (
                f"conflicting {conflict_kind} under CAS identity {cas_identity}: "
                f"existing={existing_sha256} incoming={incoming_sha256}"
            ),
        )


class FrozenFactOverwriteError(StudyDefinitionCasError):
    """Raised when a fact update attempts to change a protected (frozen) fact.

    Protected facts are those present in the current definition while it is in
    ``CONFIRMED`` or ``FROZEN`` canonical state.  Overwriting them requires a
    new accepted decision, not a silent reducer mutation.
    """

    __slots__ = ("protected_fact_paths",)

    def __init__(
        self,
        study_definition_id: str,
        expected_revision: int,
        protected_fact_paths: tuple[str, ...],
    ) -> None:
        self.protected_fact_paths = protected_fact_paths
        super().__init__(
            study_definition_id,
            expected_revision,
            (
                f"refusing to overwrite protected facts: "
                f"{', '.join(protected_fact_paths)}"
            ),
        )


# ---------------------------------------------------------------------------
# Immutable decision effect ledger
# ---------------------------------------------------------------------------


class DecisionEffect:
    """Immutable record of one applied decision's effect payload.

    Captures the exact CAS identity, the material hash of the applied
    :class:`DecisionRecord`, the material hash of the fact updates, a reference
    to the applied DecisionRecord (so a replay can return the *prior* object,
    not a reconstructed copy), and the resulting StudyDefinition revision
    identity.

    The result identity (``result_study_definition_id``, ``result_revision``,
    ``result_revision_sha256``) binds the effect to the *produced* authority
    revision.  On replay this proves the recorded decision cannot be claimed
    against unrelated state: the current authority must be the recorded result
    or a later descendant of the same aggregate.
    """

    __slots__ = (
        "cas_identity",
        "decision_record",
        "decision_record_sha256",
        "fact_updates_sha256",
        "result_study_definition_id",
        "result_revision",
        "result_previous_revision_sha256",
        "result_revision_sha256",
        "_sealed",
    )

    def __init__(
        self,
        cas_identity: str,
        decision_record: DecisionRecord,
        decision_record_sha256: str,
        fact_updates_sha256: str,
        result_study_definition_id: str,
        result_revision: int,
        result_previous_revision_sha256: str,
        result_revision_sha256: str,
    ) -> None:
        object.__setattr__(self, "cas_identity", cas_identity)
        object.__setattr__(self, "decision_record", decision_record)
        object.__setattr__(self, "decision_record_sha256", decision_record_sha256)
        object.__setattr__(self, "fact_updates_sha256", fact_updates_sha256)
        object.__setattr__(
            self, "result_study_definition_id", result_study_definition_id
        )
        object.__setattr__(self, "result_revision", result_revision)
        object.__setattr__(
            self,
            "result_previous_revision_sha256",
            result_previous_revision_sha256,
        )
        object.__setattr__(self, "result_revision_sha256", result_revision_sha256)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError(f"DecisionEffect is immutable; cannot set {name!r}")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"DecisionEffect is immutable; cannot delete {name!r}")


class DecisionEffectLedger:
    """Immutable, append-only mapping from CAS identity to applied effect.

    The ledger is the proof of what payload was applied under each CAS triple.
    ``StudyDefinitionV3.decision_record_ids`` is a convenience lineage pointer
    but cannot prove the prior payload — only this ledger can.

    Instances are never mutated in place; :meth:`with_effect` returns a new
    ledger.
    """

    __slots__ = ("_effects", "_sealed")

    def __init__(
        self,
        effects: Mapping[str, DecisionEffect] | None = None,
    ) -> None:
        raw = dict(effects) if effects else {}
        if any(key != effect.cas_identity for key, effect in raw.items()):
            raise ValueError("DecisionEffectLedger key must match effect CAS identity")
        object.__setattr__(self, "_effects", MappingProxyType(raw))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError(
                f"DecisionEffectLedger is immutable; cannot set {name!r}"
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"DecisionEffectLedger is immutable; cannot delete {name!r}"
        )

    @property
    def effects(self) -> Mapping[str, DecisionEffect]:
        """Read-only view of the CAS-identity → effect mapping."""
        return self._effects

    def find(self, cas_identity: str) -> Optional[DecisionEffect]:
        """Return the recorded effect for *cas_identity*, or ``None``."""
        return self._effects.get(cas_identity)

    def with_effect(self, effect: DecisionEffect) -> "DecisionEffectLedger":
        """Return a new ledger with *effect* recorded under its CAS identity."""
        if effect.cas_identity in self._effects:
            raise ValueError("DecisionEffectLedger cannot replace an existing effect")
        updated = dict(self._effects)
        updated[effect.cas_identity] = effect
        return DecisionEffectLedger(updated)

    def is_empty(self) -> bool:
        return not self._effects


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


class _ReplayResult(Enum):
    """Internal tri-state for replay classification."""

    EXACT = "exact"
    CONFLICT = "conflict"
    FRESH = "fresh"


class StudyDefinitionReducer:
    """Pure stateless reducer for :class:`StudyDefinitionV3`.

    Instances are safe to share.  Every method is a pure function that returns
    a *new* immutable :class:`StudyDefinitionV3` (and, for the idempotent path,
    a new :class:`DecisionEffectLedger`); the current instance is never mutated
    (the model itself is frozen).

    The idempotent path (:meth:`replay_or_apply`) threads an explicit
    :class:`DecisionEffectLedger` so that the *exact* CAS triple is the replay
    key and the prior DecisionRecord object is returned on replay.
    """

    __slots__ = ()

    # ------------------------------------------------------------------
    # Idempotent CAS replay / apply
    # ------------------------------------------------------------------

    def replay_or_apply(
        self,
        current: StudyDefinitionV3,
        decision: DecisionRecord,
        ledger: DecisionEffectLedger,
        *,
        fact_updates: Optional[Mapping[str, JsonValue]] = None,
        now: datetime,
    ) -> tuple[StudyDefinitionV3, DecisionRecord, DecisionEffectLedger, bool]:
        """Apply *decision* idempotently under CAS discipline.

        The **ledger is consulted first**, before any expected-revision or
        snapshot check.  This models a duplicate request arriving after
        commit/restart: the repository's *current* may already be the advanced
        revision (or a later descendant), while the incoming *decision* still
        carries the original CAS triple.  The ledger proves the decision was
        already applied, so the stale-revision check must not fire.

        Returns ``(new_definition, effective_decision, new_ledger, replayed)``:

        * ``replayed`` is ``True`` when the CAS identity matches a recorded
          effect in *ledger*, both the DecisionRecord material hash and the
          fact-update hash are identical, **and** *current* is a legitimate
          target for the replay (the recorded result revision, or a later
          descendant of the same aggregate).  In that case
          ``new_definition`` is *current* unchanged — authority is never
          regressed to an earlier revision — ``effective_decision`` is the
          previously recorded DecisionRecord object, and ``new_ledger`` is
          *ledger* unchanged.
        * ``replayed`` is ``False`` on a fresh apply — ``new_definition`` is the
          advanced revision with ``decision.decision_record_id`` appended,
          ``effective_decision`` is *decision*, and ``new_ledger`` is the
          advanced ledger.

        Raises :class:`DecisionPayloadConflictError` if the CAS identity matches
        a recorded effect but the DecisionRecord material hash or the fact-update
        hash differs.

        Raises :class:`RevisionStaleError` if the CAS identity is *not* recorded
        (a genuinely fresh decision) and ``current.revision`` does not equal
        ``decision.expected_state_revision``, or the snapshot does not bind the
        current revision.  Also raised when a recorded replay is attempted
        against *unrelated* state (different aggregate, or current at a lower
        revision than the recorded result without containing the decision in its
        lineage).

        Raises :class:`FrozenFactOverwriteError` if *fact_updates* changes a
        protected fact while the definition is confirmed or frozen.

        *decision* must already satisfy the :class:`DecisionRecord` contract
        (``state_revision == expected_state_revision + 1``); that invariant is
        enforced by the model itself.
        """

        cas_identity = decision_cas_identity(
            decision.decision_record_id,
            decision.snapshot_sha256,
            decision.expected_state_revision,
        )
        incoming_decision_sha = decision.material_sha256()
        incoming_fact_sha = _fact_updates_sha256(fact_updates)

        # --- Phase 1: ledger lookup BEFORE revision/snapshot checks ---------
        # A duplicate request after commit/restart carries the original CAS
        # triple but the repository's current may be the advanced revision or a
        # later descendant.  The ledger is the proof of a prior apply.
        existing = ledger.find(cas_identity)
        if existing is not None:
            # Validate the payload matches the recorded effect.
            if existing.decision_record_sha256 != incoming_decision_sha:
                raise DecisionPayloadConflictError(
                    study_definition_id=current.study_definition_id,
                    expected_revision=decision.expected_state_revision,
                    cas_identity=cas_identity,
                    conflict_kind="decision_record",
                    existing_sha256=existing.decision_record_sha256,
                    incoming_sha256=incoming_decision_sha,
                )
            if existing.fact_updates_sha256 != incoming_fact_sha:
                raise DecisionPayloadConflictError(
                    study_definition_id=current.study_definition_id,
                    expected_revision=decision.expected_state_revision,
                    cas_identity=cas_identity,
                    conflict_kind="fact_updates",
                    existing_sha256=existing.fact_updates_sha256,
                    incoming_sha256=incoming_fact_sha,
                )
            # Payload is an exact match.  Now verify *current* is a legitimate
            # replay target — never regress authority to an earlier revision.
            self._check_replay_target(current, decision, existing, ledger)
            return current, existing.decision_record, ledger, True

        # --- Phase 2: fresh apply -----------------------------------------
        # The decision is genuinely new: verify the expected revision and
        # snapshot bind the exact current revision before advancing.
        self._check_revision(current, decision)
        self._check_snapshot(current, decision)

        new_definition = self.apply_decision(
            current,
            decision,
            fact_updates=fact_updates,
            now=now,
        )
        effect = DecisionEffect(
            cas_identity=cas_identity,
            decision_record=decision,
            decision_record_sha256=incoming_decision_sha,
            fact_updates_sha256=incoming_fact_sha,
            result_study_definition_id=new_definition.study_definition_id,
            result_revision=new_definition.revision,
            result_previous_revision_sha256=new_definition.previous_revision_sha256,
            result_revision_sha256=study_revision_hash(new_definition),
        )
        return new_definition, decision, ledger.with_effect(effect), False

    # ------------------------------------------------------------------
    # Fresh apply (non-idempotent path)
    # ------------------------------------------------------------------

    def apply_decision(
        self,
        current: StudyDefinitionV3,
        decision: DecisionRecord,
        *,
        fact_updates: Optional[Mapping[str, JsonValue]] = None,
        now: datetime,
    ) -> StudyDefinitionV3:
        """Advance *current* to the next revision via an accepted *decision*.

        This is the authoritative fact-mutation path.  It is **not** idempotent
        on its own; callers that need replay safety must use
        :meth:`replay_or_apply` with a :class:`DecisionEffectLedger`.

        Raises :class:`RevisionStaleError` if ``current.revision`` does not
        equal ``decision.expected_state_revision``.

        Raises :class:`RevisionStaleError` if ``decision.snapshot_sha256`` does
        not equal the canonical revision hash of *current* — the snapshot must
        bind the exact revision the decision was captured against.

        Raises :class:`FrozenFactOverwriteError` if *fact_updates* changes a
        protected fact.

        The returned definition:

        * has ``revision = decision.state_revision``;
        * has ``previous_revision_sha256 = canonical_revision_hash(current)``;
        * has ``decision_record_ids`` extended with
          ``decision.decision_record_id``;
        * inherits ``study_definition_id``, ``project_id``, ``normalized_seed``
          identity, and the fact set (optionally updated);
        * keeps the same ``canonical_state`` as *current* unless *current* is
          ``PROPOSED`` and the decision advances it to ``CONFIRMED`` (the
          natural first-accept transition).
        """

        self._check_revision(current, decision)
        self._check_snapshot(current, decision)
        merged_facts = self._merge_facts(current, decision, fact_updates)
        next_state = self._next_canonical_state(current, decision)
        current_revision_hash = study_revision_hash(current)
        return StudyDefinitionV3(
            study_definition_id=current.study_definition_id,
            project_id=current.project_id,
            revision=decision.state_revision,
            previous_revision_sha256=current_revision_hash,
            normalized_seed_id=current.normalized_seed_id,
            normalized_seed_sha256=current.normalized_seed_sha256,
            facts=merged_facts,
            decision_record_ids=(
                *current.decision_record_ids,
                decision.decision_record_id,
            ),
            updated_at=now,
            canonical_state=next_state,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_revision(
        current: StudyDefinitionV3,
        decision: DecisionRecord,
    ) -> None:
        if current.revision != decision.expected_state_revision:
            raise RevisionStaleError(
                study_definition_id=current.study_definition_id,
                expected_revision=decision.expected_state_revision,
                actual_revision=current.revision,
            )

    @staticmethod
    def _check_snapshot(
        current: StudyDefinitionV3,
        decision: DecisionRecord,
    ) -> None:
        """Verify the decision's snapshot binds the exact current revision.

        The snapshot must equal :func:`canonical_revision_hash` of *current* —
        not merely the material hash — so that same content at a different
        revision, lifecycle state, or predecessor chain is rejected.
        """

        expected_snapshot = study_revision_hash(current)
        if decision.snapshot_sha256 != expected_snapshot:
            raise RevisionStaleError(
                study_definition_id=current.study_definition_id,
                expected_revision=decision.expected_state_revision,
                actual_revision=current.revision,
            )

    @staticmethod
    def _check_replay_target(
        current: StudyDefinitionV3,
        decision: DecisionRecord,
        existing: DecisionEffect,
        ledger: DecisionEffectLedger,
    ) -> None:
        """Verify *current* is a legitimate replay target for a recorded effect.

        Authority must never regress to an earlier revision.  The recorded
        effect binds the result revision identity.  *current* is a valid replay
        target when it is the recorded result or a later descendant of the same
        aggregate.  This covers the commit/restart duplicate-request scenario:
        the repository has advanced past the recorded result, the incoming
        decision carries the original CAS triple, and the replay must return
        *current* unchanged.

        If *current* is at a lower revision than the recorded result, or belongs
        to a different aggregate, the replay is against unrelated state and must
        fail closed with :class:`RevisionStaleError`.
        """

        if current.study_definition_id != existing.result_study_definition_id:
            raise RevisionStaleError(
                study_definition_id=current.study_definition_id,
                expected_revision=decision.expected_state_revision,
                actual_revision=current.revision,
            )
        if current.revision == existing.result_revision:
            if study_revision_hash(current) == existing.result_revision_sha256:
                return
        elif current.revision > existing.result_revision:
            cursor_revision = current.revision
            cursor_sha256 = study_revision_hash(current)
            effects = tuple(ledger.effects.values())
            while cursor_revision > existing.result_revision:
                matches = tuple(
                    effect
                    for effect in effects
                    if effect.result_study_definition_id == current.study_definition_id
                    and effect.result_revision == cursor_revision
                    and effect.result_revision_sha256 == cursor_sha256
                )
                if len(matches) != 1:
                    break
                cursor_sha256 = matches[0].result_previous_revision_sha256
                cursor_revision -= 1
            if (
                cursor_revision == existing.result_revision
                and cursor_sha256 == existing.result_revision_sha256
            ):
                return
        raise RevisionStaleError(
            study_definition_id=current.study_definition_id,
            expected_revision=decision.expected_state_revision,
            actual_revision=current.revision,
        )

    @staticmethod
    def _merge_facts(
        current: StudyDefinitionV3,
        decision: DecisionRecord,
        fact_updates: Optional[Mapping[str, JsonValue]],
    ) -> dict[str, JsonValue]:
        if not fact_updates:
            return dict(current.facts)

        protected = _protected_fact_paths(current, fact_updates)
        if protected:
            raise FrozenFactOverwriteError(
                study_definition_id=current.study_definition_id,
                expected_revision=decision.expected_state_revision,
                protected_fact_paths=tuple(sorted(protected)),
            )

        merged: dict[str, JsonValue] = dict(current.facts)
        merged.update(fact_updates)
        return merged

    @staticmethod
    def _next_canonical_state(
        current: StudyDefinitionV3,
        decision: DecisionRecord,
    ) -> CanonicalState:
        if (
            current.canonical_state is CanonicalState.PROPOSED
            and decision.canonical_state is CanonicalState.CONFIRMED
        ):
            return CanonicalState.CONFIRMED
        return current.canonical_state


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------


def study_revision_hash(definition: StudyDefinitionV3) -> str:
    """Canonical revision hash for a :class:`StudyDefinitionV3`.

    Binds ``study_definition_id``, ``revision``, ``previous_revision_sha256``,
    ``canonical_state`` and the material hash so that same material at a
    different revision produces a different snapshot.
    """

    return canonical_revision_hash(
        aggregate_id=definition.study_definition_id,
        revision=definition.revision,
        previous_revision_sha256=definition.previous_revision_sha256,
        canonical_state=definition.canonical_state,
        material_sha256_value=definition.material_sha256(),
    )


def _fact_updates_sha256(
    fact_updates: Optional[Mapping[str, JsonValue]],
) -> str:
    """Material hash of a fact-update payload (``None`` and empty are identical)."""

    if not fact_updates:
        return material_sha256({})
    return exact_payload_sha256(dict(fact_updates))


def _protected_fact_paths(
    current: StudyDefinitionV3,
    fact_updates: Mapping[str, JsonValue],
) -> set[str]:
    """Return fact paths whose existing value would change under *fact_updates*
    and which are protected (confirmed/frozen).

    Adding a *new* fact path is always allowed — it does not overwrite an
    existing authority.  Only changing an existing fact that differs in value
    while the definition is confirmed or frozen is blocked here.
    """

    if current.canonical_state not in {
        CanonicalState.CONFIRMED,
        CanonicalState.FROZEN,
    }:
        return set()

    blocked: set[str] = set()
    for path, incoming_value in fact_updates.items():
        if path not in current.facts:
            continue
        existing = current.facts[path]
        existing_hash = exact_payload_sha256(existing)
        incoming_hash = exact_payload_sha256(incoming_value)
        if existing_hash != incoming_hash:
            blocked.add(path)
    return blocked
