"""Pure SemanticDocument reducer with fact-revision binding and typed fact
proposals.

A :class:`SemanticDocumentRevision` is the product's only textual, structural
and layout working version — but it is a *projection* bound to an exact
:class:`StudyDefinitionV3` revision identity.  It must never become a second
fact store.  This module provides the pure, stateless reducer that is the only
path authorised to advance a document revision, enforcing the Protocol v3
design invariants from §14 and §15:

1. **Fact-revision binding** — every :class:`SemanticBlock` must reference fact
   paths that exist on the bound :class:`StudyDefinitionV3`.  A block that
   points at a fact the study definition does not hold is a phantom fact and is
   rejected with :class:`UnboundFactPathError`.  The document revision must
   also carry the *current* study definition material hash; a mismatch between
   the blocks' authority and the revision header is rejected with
   :class:`FactRevisionMismatchError`.

2. **CAS replay** — replaying the same ``(decision_record_id,
   snapshot_sha256, expected_state_revision)`` triple returns the exact prior
   revision and produces no new revision.  The proof of the original payload is
   the :class:`DocumentEffectLedger`, an immutable mapping from CAS identity to
   the recorded effect — including the full document payload hash.  This makes
   duplicate clicks, worker retries and restarts idempotent, mirroring the
   StudyDefinition and DecisionRecord reducers.  A different decision ID can
   never be mistaken for the original operation because the ledger is keyed by
   the full CAS triple.

3. **Typed failure** — stale expected revision, conflicting payload under the
   same CAS key, fact-revision mismatch, unbound fact paths, and attempts to
   silently apply a fact-touching edit each raise a distinct stable error.
   The application service translates these into :class:`ProtocolWorkflowError`
   types for the UI; this reducer never imports the error registry, keeping it
   free of UI/audit coupling.

4. **Typed fact proposal** — a free-text or block edit classified as touching
   or possibly touching a protected fact (``fact_or_uncertain`` per §14
   ``EditClass``) does **not** create a document revision.  Instead the
   reducer returns a deeply immutable :class:`FactProposal` carrying the
   candidate fact deltas and the affected fact paths, so the application can
   route it through the StudyDefinition adoption + impact-propagation path
   before re-projecting.

The reducer is pure: it receives explicit identity, time and expected-revision
inputs, returns a new immutable :class:`SemanticDocumentRevision`, and touches
no repository, filesystem, network, clock or model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DecisionRecord,
    SemanticBlock,
    SemanticDocumentRevision,
    StudyDefinitionV3,
)

from .hashing import (
    canonical_revision_hash,
    decision_cas_identity,
    material_sha256,
)
from .study_definition import study_revision_hash

__all__ = [
    "DocumentCasError",
    "DocumentEffect",
    "DocumentEffectLedger",
    "DocumentPayloadConflictError",
    "DocumentRevisionStaleError",
    "EditClass",
    "EditOutcome",
    "FactProposal",
    "FactProposalError",
    "FactRevisionMismatchError",
    "SemanticDocumentReducer",
    "UnboundFactPathError",
    "document_revision_hash",
]


# ---------------------------------------------------------------------------
# Edit classification (§14 canonical EditClass)
# ---------------------------------------------------------------------------


class EditClass(str, Enum):
    """Canonical classification of a free-text or block edit (design §14).

    The classification drives whether an edit may be applied locally or must be
    routed through the StudyDefinition fact-adoption path:

    * ``FORMAT_ONLY`` — style/font/spacing changes only; protected values,
      fact bindings, references and structural objects are unchanged.
    * ``WORDING_ONLY`` — wording changes only; protected values, fact bindings,
      references and structural objects are unchanged and validators pass.
    * ``STRUCTURE_OR_WORD_OBJECT`` — a structural object or Word object
      (table, SoA, figure, formula) is added/removed/reshaped, but no
      confirmed fact path is touched.
    * ``FACT_OR_UNCERTAIN`` — the edit touches or possibly touches a protected
      fact (dose/frequency/unit, population, objective/endpoint/estimand,
      assessment window, treatment/control, randomisation/blinding/stratification,
      sample size/statistics, safety rules, SoA/visits, applicability triggers,
      or any confirmed fact path).  When the classification is uncertain this
      value is the safe default.
    """

    FORMAT_ONLY = "format_only"
    WORDING_ONLY = "wording_only"
    STRUCTURE_OR_WORD_OBJECT = "structure_or_word_object"
    FACT_OR_UNCERTAIN = "fact_or_uncertain"


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------
#
# These mirror the StudyDefinition and DecisionRecord reducer discipline: they
# carry the identity context the application service needs for audit and UI
# translation, but they never import the user-facing error registry.  Keeping
# them local prevents the pure reducer from becoming coupled to UI copy.


class DocumentCasError(RuntimeError):
    """Base class for SemanticDocument CAS discipline failures.

    Carries the CAS identity context so the caller can attach it to audit
    records.
    """

    __slots__ = (
        "semantic_document_revision_id",
        "expected_revision",
        "detail",
    )

    def __init__(
        self,
        semantic_document_revision_id: str,
        expected_revision: int,
        detail: str,
    ) -> None:
        self.semantic_document_revision_id = semantic_document_revision_id
        self.expected_revision = expected_revision
        self.detail = detail
        super().__init__(detail)


class DocumentRevisionStaleError(DocumentCasError):
    """Raised when the caller's expected revision does not match current."""

    __slots__ = ("actual_revision",)

    def __init__(
        self,
        semantic_document_revision_id: str,
        expected_revision: int,
        actual_revision: int,
    ) -> None:
        self.actual_revision = actual_revision
        super().__init__(
            semantic_document_revision_id,
            expected_revision,
            (
                f"stale document revision for {semantic_document_revision_id}: "
                f"expected {expected_revision}, actual {actual_revision}"
            ),
        )


class DocumentPayloadConflictError(DocumentCasError):
    """Raised when the same CAS identity is replayed with a different payload.

    The ``(decision_record_id, snapshot_sha256, expected_state_revision)``
    triple matches a recorded effect in the ledger, but the incoming document
    payload (semantic blocks, chapter contract hashes, applicability identity)
    differs from what was originally applied.  This is a contract violation —
    a retry must resend identical bytes — not an idempotent replay.
    """

    __slots__ = (
        "cas_identity",
        "conflict_kind",
        "existing_sha256",
        "incoming_sha256",
    )

    def __init__(
        self,
        semantic_document_revision_id: str,
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
            semantic_document_revision_id,
            expected_revision,
            (
                f"conflicting document payload ({conflict_kind}) "
                f"under CAS identity {cas_identity}: "
                f"existing={existing_sha256} incoming={incoming_sha256}"
            ),
        )


class FactRevisionMismatchError(DocumentCasError):
    """Raised when a document revision's study-definition binding is stale.

    The reducer refuses to project a document against a study definition whose
    revision identity or material hash differs from the revision header.  This
    keeps the document from silently drifting from its fact authority (design
    §14: the document must not become a second fact store).
    """

    __slots__ = (
        "study_definition_id",
        "expected_sha256",
        "actual_sha256",
    )

    def __init__(
        self,
        semantic_document_revision_id: str,
        expected_revision: int,
        study_definition_id: str,
        expected_sha256: str,
        actual_sha256: str,
    ) -> None:
        self.study_definition_id = study_definition_id
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256
        super().__init__(
            semantic_document_revision_id,
            expected_revision,
            (
                f"fact revision mismatch for {semantic_document_revision_id}: "
                f"study_definition {study_definition_id} "
                f"expected {expected_sha256} actual {actual_sha256}"
            ),
        )


class UnboundFactPathError(DocumentCasError):
    """Raised when a semantic block references a fact path absent from the
    bound study definition.

    A block that points at a fact the study definition does not hold is a
    phantom fact — it would make the document a second, conflicting fact
    store.  The reducer rejects it so the caller can correct the binding or
    route the fact through StudyDefinition adoption first.
    """

    __slots__ = (
        "study_definition_id",
        "unbound_fact_paths",
    )

    def __init__(
        self,
        semantic_document_revision_id: str,
        expected_revision: int,
        study_definition_id: str,
        unbound_fact_paths: tuple[str, ...],
    ) -> None:
        self.study_definition_id = study_definition_id
        self.unbound_fact_paths = unbound_fact_paths
        super().__init__(
            semantic_document_revision_id,
            expected_revision,
            (
                f"unbound fact paths for {semantic_document_revision_id}: "
                f"{', '.join(unbound_fact_paths)} not present on "
                f"study_definition {study_definition_id}"
            ),
        )


class FactProposalError(DocumentCasError):
    """Raised when an edit classified as ``FACT_OR_UNCERTAIN`` is submitted to
    the direct-apply path.

    A fact-touching edit must be routed through the StudyDefinition adoption +
    impact-propagation path before it can re-project; it must not silently
    create a document revision.  This error carries the proposal payload so
    the application service can forward it without re-deriving it.
    """

    __slots__ = ("proposal",)

    def __init__(
        self,
        semantic_document_revision_id: str,
        expected_revision: int,
        proposal: "FactProposal",
    ) -> None:
        self.proposal = proposal
        super().__init__(
            semantic_document_revision_id,
            expected_revision,
            (
                f"fact-touching edit rejected from direct-apply path for "
                f"{semantic_document_revision_id}; "
                f"affected fact paths: {', '.join(proposal.affected_fact_paths)}"
            ),
        )


# ---------------------------------------------------------------------------
# Immutable document effect ledger
# ---------------------------------------------------------------------------


class DocumentEffect:
    """Immutable record of one applied document decision's effect payload.

    Captures the exact CAS identity, the material hash of the applied
    :class:`DecisionRecord`, the material hash of the full document mutation
    payload (semantic blocks, chapter contract hashes, applicability identity
    and hash, and the study-definition revision hash), a reference to the
    applied DecisionRecord (so a replay can return the *prior* object), and
    the resulting document revision identity.

    The result identity (``result_document_id``, ``result_revision``,
    ``result_revision_sha256``) binds the effect to the *produced* document
    revision.  On replay this proves the recorded decision cannot be claimed
    against unrelated state.
    """

    __slots__ = (
        "cas_identity",
        "decision_record",
        "decision_record_sha256",
        "document_payload_sha256",
        "result_document_id",
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
        document_payload_sha256: str,
        result_document_id: str,
        result_revision: int,
        result_previous_revision_sha256: str,
        result_revision_sha256: str,
    ) -> None:
        object.__setattr__(self, "cas_identity", cas_identity)
        object.__setattr__(self, "decision_record", decision_record)
        object.__setattr__(self, "decision_record_sha256", decision_record_sha256)
        object.__setattr__(self, "document_payload_sha256", document_payload_sha256)
        object.__setattr__(self, "result_document_id", result_document_id)
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
            raise AttributeError(f"DocumentEffect is immutable; cannot set {name!r}")
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"DocumentEffect is immutable; cannot delete {name!r}")


class DocumentEffectLedger:
    """Immutable, append-only mapping from CAS identity to applied effect.

    The ledger is the proof of what payload was applied under each CAS triple.
    It is consulted *before* any revision or snapshot check so that a
    duplicate request arriving after commit/restart — when the repository's
    *current* may already be the advanced revision — is recognised as a
    replay rather than rejected as stale.

    Instances are never mutated in place; :meth:`with_effect` returns a new
    ledger.
    """

    __slots__ = ("_effects", "_sealed")

    def __init__(
        self,
        effects: Optional[Mapping[str, DocumentEffect]] = None,
    ) -> None:
        raw = dict(effects) if effects else {}
        if any(key != effect.cas_identity for key, effect in raw.items()):
            raise ValueError("DocumentEffectLedger key must match effect CAS identity")
        object.__setattr__(self, "_effects", MappingProxyType(raw))
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError(
                f"DocumentEffectLedger is immutable; cannot set {name!r}"
            )
        object.__setattr__(self, name, value)

    def __delattr__(self, name: str) -> None:
        raise AttributeError(
            f"DocumentEffectLedger is immutable; cannot delete {name!r}"
        )

    @property
    def effects(self) -> Mapping[str, DocumentEffect]:
        """Read-only view of the CAS-identity → effect mapping."""
        return self._effects

    def find(self, cas_identity: str) -> Optional[DocumentEffect]:
        """Return the recorded effect for *cas_identity*, or ``None``."""
        return self._effects.get(cas_identity)

    def with_effect(self, effect: DocumentEffect) -> "DocumentEffectLedger":
        """Return a new ledger with *effect* recorded under its CAS identity."""
        if effect.cas_identity in self._effects:
            raise ValueError("DocumentEffectLedger cannot replace an existing effect")
        updated = dict(self._effects)
        updated[effect.cas_identity] = effect
        return DocumentEffectLedger(updated)

    def is_empty(self) -> bool:
        return not self._effects


# ---------------------------------------------------------------------------
# Deeply immutable typed fact proposal
# ---------------------------------------------------------------------------


def _deep_freeze(value: Any) -> Any:
    """Return a deeply immutable copy of a JSON-compatible value.

    * ``dict`` → ``MappingProxyType`` of a dict of frozen values;
    * ``list``/``tuple`` → ``tuple`` of frozen values;
    * ``str``/``int``/``float``/``bool``/``None`` → returned as-is.

    The result is non-aliasing: the caller retains its original mutable
    container, but every nested level of the returned value is read-only.
    """

    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("FactProposal fact-update keys must be strings")
        return MappingProxyType({k: _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(
        "FactProposal fact updates must contain only JSON-compatible values"
    )


class FactProposal:
    """Typed proposal carrying the candidate fact deltas from a fact-touching
    document edit.

    When a free-text or block edit is classified as ``FACT_OR_UNCERTAIN``
    (design §14), the reducer does **not** create a document revision.
    Instead it returns this proposal so the application can:

    1. route it through the StudyDefinition adoption path (DecisionRecord +
       CAS);
    2. run impact propagation across dependent chapters;
    3. re-project the SemanticDocumentRevision once the facts are accepted.

    The proposal is **deeply immutable**: ``proposed_fact_updates`` is stored
    as a ``MappingProxyType`` over deeply frozen copies, so caller mutation
    after construction and attempted mutation at every nested dict/list level
    cannot alter the proposal.  It carries only the fact-binding deltas — it
    is never a second fact authority.
    """

    __slots__ = (
        "_affected_fact_paths",
        "_proposed_fact_updates",
        "_originating_block_id",
        "_edit_class",
        "_reason",
    )

    def __init__(
        self,
        affected_fact_paths: tuple[str, ...],
        proposed_fact_updates: Optional[Mapping[str, Any]] = None,
        originating_block_id: Optional[str] = None,
        edit_class: EditClass = EditClass.FACT_OR_UNCERTAIN,
        reason: str = "",
    ) -> None:
        object.__setattr__(
            self,
            "_affected_fact_paths",
            tuple(sorted(set(affected_fact_paths))),
        )
        frozen_updates = _deep_freeze(dict(proposed_fact_updates or {}))
        object.__setattr__(self, "_proposed_fact_updates", frozen_updates)
        object.__setattr__(self, "_originating_block_id", originating_block_id)
        object.__setattr__(self, "_edit_class", edit_class)
        object.__setattr__(self, "_reason", reason)

    @property
    def affected_fact_paths(self) -> tuple[str, ...]:
        return self._affected_fact_paths

    @property
    def proposed_fact_updates(self) -> Mapping[str, Any]:
        return self._proposed_fact_updates

    @property
    def originating_block_id(self) -> Optional[str]:
        return self._originating_block_id

    @property
    def edit_class(self) -> EditClass:
        return self._edit_class

    @property
    def reason(self) -> str:
        return self._reason

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: D401
        raise AttributeError(f"FactProposal is immutable; cannot set {name!r}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"FactProposal is immutable; cannot delete {name!r}")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, FactProposal):
            return NotImplemented
        return (
            self._affected_fact_paths == other._affected_fact_paths
            and dict(self._proposed_fact_updates) == dict(other._proposed_fact_updates)
            and self._originating_block_id == other._originating_block_id
            and self._edit_class == other._edit_class
            and self._reason == other._reason
        )

    def __hash__(self) -> int:
        return hash(self._affected_fact_paths)

    def __repr__(self) -> str:
        return (
            f"FactProposal(affected_fact_paths={self._affected_fact_paths!r}, "
            f"edit_class={self._edit_class!r})"
        )


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


class _ReplayResult(Enum):
    """Internal tri-state for replay classification."""

    EXACT = "exact"
    CONFLICT = "conflict"
    FRESH = "fresh"


class SemanticDocumentReducer:
    """Pure, stateless reducer for :class:`SemanticDocumentRevision`.

    The reducer is the only path authorised to advance a document revision.
    It enforces fact-revision binding and CAS replay discipline.  The
    idempotent path (:meth:`replay_or_apply`) threads an explicit
    :class:`DocumentEffectLedger` so that the *exact* CAS triple is the replay
    key and the prior payload is provable.  Instances are safe to share;
    every method is a pure function that returns a *new* immutable
    :class:`SemanticDocumentRevision` (or a :class:`FactProposal`), and the
    receiver is never mutated.
    """

    __slots__ = ()

    # ------------------------------------------------------------------
    # Idempotent CAS replay / apply
    # ------------------------------------------------------------------

    def replay_or_apply(
        self,
        current: SemanticDocumentRevision,
        study_definition: StudyDefinitionV3,
        decision: DecisionRecord,
        ledger: DocumentEffectLedger,
        *,
        semantic_blocks: tuple[SemanticBlock, ...],
        chapter_contract_hashes: tuple[str, ...],
        applicability_snapshot_id: str,
        applicability_snapshot_sha256: str,
        now: datetime,
    ) -> tuple[SemanticDocumentRevision, DecisionRecord, DocumentEffectLedger, bool]:
        """Apply *decision* idempotently under CAS + fact-binding discipline.

        The **ledger is consulted first**, before any expected-revision or
        snapshot check.  This models a duplicate request arriving after
        commit/restart: the repository's *current* may already be the advanced
        revision, while the incoming *decision* still carries the original CAS
        triple.  The ledger proves the decision was already applied.

        Returns ``(new_revision, effective_decision, new_ledger, replayed)``:

        * ``replayed`` is ``True`` when the CAS identity matches a recorded
          effect in *ledger*, both the DecisionRecord material hash and the
          full document payload hash are identical, **and** *current* is a
          legitimate target for the replay.  In that case ``new_revision`` is
          *current* unchanged, ``effective_decision`` is the previously
          recorded DecisionRecord, and ``new_ledger`` is *ledger* unchanged.
        * ``replayed`` is ``False`` on a fresh apply — ``new_revision`` is the
          advanced revision, ``effective_decision`` is *decision*, and
          ``new_ledger`` is the advanced ledger.

        Raises :class:`DocumentPayloadConflictError` if the CAS identity matches
        a recorded effect but the DecisionRecord material hash or the document
        payload hash differs.

        Raises :class:`DocumentRevisionStaleError` if the CAS identity is not
        recorded and ``current.revision`` does not equal
        ``decision.expected_state_revision``, or the snapshot does not bind the
        current revision.

        Raises :class:`FactRevisionMismatchError` and
        :class:`UnboundFactPathError` as for :meth:`apply_decision`.
        """

        cas_identity = decision_cas_identity(
            decision.decision_record_id,
            decision.snapshot_sha256,
            decision.expected_state_revision,
        )
        incoming_decision_sha = decision.material_sha256()
        incoming_payload_sha = _document_payload_sha256(
            semantic_blocks=semantic_blocks,
            chapter_contract_hashes=chapter_contract_hashes,
            applicability_snapshot_id=applicability_snapshot_id,
            applicability_snapshot_sha256=applicability_snapshot_sha256,
            study_definition=study_definition,
        )

        # --- Phase 1: ledger lookup BEFORE revision/snapshot checks ---------
        existing = ledger.find(cas_identity)
        if existing is not None:
            if existing.decision_record_sha256 != incoming_decision_sha:
                raise DocumentPayloadConflictError(
                    semantic_document_revision_id=current.semantic_document_revision_id,
                    expected_revision=decision.expected_state_revision,
                    cas_identity=cas_identity,
                    conflict_kind="decision_record",
                    existing_sha256=existing.decision_record_sha256,
                    incoming_sha256=incoming_decision_sha,
                )
            if existing.document_payload_sha256 != incoming_payload_sha:
                raise DocumentPayloadConflictError(
                    semantic_document_revision_id=current.semantic_document_revision_id,
                    expected_revision=decision.expected_state_revision,
                    cas_identity=cas_identity,
                    conflict_kind="document_payload",
                    existing_sha256=existing.document_payload_sha256,
                    incoming_sha256=incoming_payload_sha,
                )
            # Payload is an exact match.  Verify fact authority + bindings.
            self._check_fact_authority(current, study_definition)
            self._check_block_fact_bindings(
                current,
                study_definition,
                semantic_blocks,
            )
            self._check_replay_target(current, decision, existing, ledger)
            return current, existing.decision_record, ledger, True

        # --- Phase 2: fresh apply -----------------------------------------
        self._check_revision(current, decision)
        self._check_snapshot(current, decision)
        self._check_fact_authority(current, study_definition)
        self._check_block_fact_bindings(
            current,
            study_definition,
            semantic_blocks,
        )
        new_revision = self._build_revision(
            current=current,
            study_definition=study_definition,
            decision=decision,
            semantic_blocks=semantic_blocks,
            chapter_contract_hashes=chapter_contract_hashes,
            applicability_snapshot_id=applicability_snapshot_id,
            applicability_snapshot_sha256=applicability_snapshot_sha256,
            now=now,
        )
        effect = DocumentEffect(
            cas_identity=cas_identity,
            decision_record=decision,
            decision_record_sha256=incoming_decision_sha,
            document_payload_sha256=incoming_payload_sha,
            result_document_id=new_revision.semantic_document_revision_id,
            result_revision=new_revision.revision,
            result_previous_revision_sha256=new_revision.previous_revision_sha256,
            result_revision_sha256=document_revision_hash(new_revision),
        )
        return new_revision, decision, ledger.with_effect(effect), False

    # ------------------------------------------------------------------
    # Fresh apply (non-idempotent path)
    # ------------------------------------------------------------------

    def apply_decision(
        self,
        current: SemanticDocumentRevision,
        study_definition: StudyDefinitionV3,
        decision: DecisionRecord,
        *,
        semantic_blocks: tuple[SemanticBlock, ...],
        chapter_contract_hashes: tuple[str, ...],
        applicability_snapshot_id: str,
        applicability_snapshot_sha256: str,
        now: datetime,
    ) -> SemanticDocumentRevision:
        """Advance *current* to the next revision via an accepted *decision*.

        This is the authoritative document-mutation path.  It is **not**
        idempotent on its own; callers that need replay safety must use
        :meth:`replay_or_apply` with a :class:`DocumentEffectLedger`.

        Raises :class:`DocumentRevisionStaleError` if ``current.revision``
        does not equal ``decision.expected_state_revision``, or the snapshot
        does not bind the current revision.

        Raises :class:`FactRevisionMismatchError` if the study-definition
        binding is stale.

        Raises :class:`UnboundFactPathError` if any block references a fact
        path absent from *study_definition*.
        """

        self._check_revision(current, decision)
        self._check_snapshot(current, decision)
        self._check_fact_authority(current, study_definition)
        self._check_block_fact_bindings(
            current,
            study_definition,
            semantic_blocks,
        )
        return self._build_revision(
            current=current,
            study_definition=study_definition,
            decision=decision,
            semantic_blocks=semantic_blocks,
            chapter_contract_hashes=chapter_contract_hashes,
            applicability_snapshot_id=applicability_snapshot_id,
            applicability_snapshot_sha256=applicability_snapshot_sha256,
            now=now,
        )

    # ------------------------------------------------------------------
    # Fact proposal path (fact-touching edits)
    # ------------------------------------------------------------------

    def propose_fact_update(
        self,
        current: SemanticDocumentRevision,
        study_definition: StudyDefinitionV3,
        *,
        affected_fact_paths: tuple[str, ...],
        proposed_fact_updates: Optional[Mapping[str, Any]] = None,
        originating_block_id: Optional[str] = None,
        reason: str = "",
    ) -> FactProposal:
        """Build a deeply immutable :class:`FactProposal` for a fact-touching
        edit.

        This method never creates a document revision.  It validates that the
        affected fact paths are a subset of the bound study definition's fact
        keys (so the proposal is well-formed), then returns an immutable
        :class:`FactProposal` for the application to route through the
        StudyDefinition adoption path.

        Raises :class:`UnboundFactPathError` if any affected path is absent
        from *study_definition*.
        """

        self._check_fact_authority(current, study_definition)
        unbound = _unbound_paths(affected_fact_paths, study_definition)
        if unbound:
            raise UnboundFactPathError(
                semantic_document_revision_id=current.semantic_document_revision_id,
                expected_revision=current.revision,
                study_definition_id=study_definition.study_definition_id,
                unbound_fact_paths=tuple(sorted(unbound)),
            )
        return FactProposal(
            affected_fact_paths=affected_fact_paths,
            proposed_fact_updates=proposed_fact_updates,
            originating_block_id=originating_block_id,
            edit_class=EditClass.FACT_OR_UNCERTAIN,
            reason=reason,
        )

    def classify_and_apply_edit(
        self,
        current: SemanticDocumentRevision,
        study_definition: StudyDefinitionV3,
        decision: DecisionRecord,
        ledger: DocumentEffectLedger,
        *,
        edit_class: EditClass,
        semantic_blocks: tuple[SemanticBlock, ...],
        chapter_contract_hashes: tuple[str, ...],
        applicability_snapshot_id: str,
        applicability_snapshot_sha256: str,
        affected_fact_paths: tuple[str, ...] = (),
        proposed_fact_updates: Optional[Mapping[str, Any]] = None,
        originating_block_id: Optional[str] = None,
        reason: str = "",
        now: datetime,
    ) -> "EditOutcome":
        """Classify an edit and either apply it or return a fact proposal.

        Per design §14, an edit classified as ``FACT_OR_UNCERTAIN`` must be
        routed through the StudyDefinition adoption path; it must not silently
        create a document revision.  All other edit classes advance the
        document revision directly via :meth:`replay_or_apply` — still under
        full CAS and payload checks.

        Returns an :class:`EditOutcome`:

        * ``applied`` is ``True`` with ``revision`` set when the edit advanced
          the document (or was an idempotent replay).
        * ``applied`` is ``False`` with ``proposal`` set when the edit is a
          fact proposal awaiting StudyDefinition adoption.

        Raises the same typed errors as :meth:`replay_or_apply` and
        :meth:`propose_fact_update`.
        """

        if edit_class is EditClass.FACT_OR_UNCERTAIN:
            proposal = self.propose_fact_update(
                current,
                study_definition,
                affected_fact_paths=affected_fact_paths,
                proposed_fact_updates=proposed_fact_updates,
                originating_block_id=originating_block_id,
                reason=reason,
            )
            return EditOutcome(
                applied=False,
                revision=None,
                ledger=ledger,
                proposal=proposal,
            )
        new_revision, effective_decision, new_ledger, replayed = self.replay_or_apply(
            current,
            study_definition,
            decision,
            ledger,
            semantic_blocks=semantic_blocks,
            chapter_contract_hashes=chapter_contract_hashes,
            applicability_snapshot_id=applicability_snapshot_id,
            applicability_snapshot_sha256=applicability_snapshot_sha256,
            now=now,
        )
        return EditOutcome(
            applied=True,
            revision=new_revision,
            effective_decision=effective_decision,
            ledger=new_ledger,
            replayed=replayed,
            proposal=None,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_revision(
        current: SemanticDocumentRevision,
        decision: DecisionRecord,
    ) -> None:
        if current.revision != decision.expected_state_revision:
            raise DocumentRevisionStaleError(
                semantic_document_revision_id=current.semantic_document_revision_id,
                expected_revision=decision.expected_state_revision,
                actual_revision=current.revision,
            )

    @staticmethod
    def _check_snapshot(
        current: SemanticDocumentRevision,
        decision: DecisionRecord,
    ) -> None:
        """Verify the decision's snapshot binds the exact current document
        revision.

        The snapshot must equal :func:`document_revision_hash` of *current* —
        not merely the material hash — so that same content at a different
        revision, lifecycle state, or predecessor chain is rejected.
        """

        expected_snapshot = document_revision_hash(current)
        if decision.snapshot_sha256 != expected_snapshot:
            raise DocumentRevisionStaleError(
                semantic_document_revision_id=current.semantic_document_revision_id,
                expected_revision=decision.expected_state_revision,
                actual_revision=current.revision,
            )

    @staticmethod
    def _check_fact_authority(
        current: SemanticDocumentRevision,
        study_definition: StudyDefinitionV3,
    ) -> None:
        """Ensure the study definition identity and material hash match the
        document header.

        The document may only project against the study definition it declares
        in its header.  A different identity is an application wiring error;
        a same-identity but different-hash study definition means the facts
        have moved and the document is stale.
        """

        if current.study_definition_id != study_definition.study_definition_id:
            raise FactRevisionMismatchError(
                semantic_document_revision_id=current.semantic_document_revision_id,
                expected_revision=current.revision,
                study_definition_id=study_definition.study_definition_id,
                expected_sha256=current.study_definition_sha256,
                actual_sha256=study_revision_hash(study_definition),
            )
        actual_sha = study_revision_hash(study_definition)
        if current.study_definition_sha256 != actual_sha:
            raise FactRevisionMismatchError(
                semantic_document_revision_id=current.semantic_document_revision_id,
                expected_revision=current.revision,
                study_definition_id=study_definition.study_definition_id,
                expected_sha256=current.study_definition_sha256,
                actual_sha256=actual_sha,
            )

    @staticmethod
    def _check_block_fact_bindings(
        current: SemanticDocumentRevision,
        study_definition: StudyDefinitionV3,
        semantic_blocks: tuple[SemanticBlock, ...],
    ) -> None:
        """Reject blocks that reference fact paths absent from the study
        definition (phantom facts).
        """

        all_unbound: list[str] = []
        for block in semantic_blocks:
            unbound = _unbound_paths(block.fact_paths, study_definition)
            if unbound:
                all_unbound.extend(sorted(unbound))
        if all_unbound:
            raise UnboundFactPathError(
                semantic_document_revision_id=current.semantic_document_revision_id,
                expected_revision=current.revision,
                study_definition_id=study_definition.study_definition_id,
                unbound_fact_paths=tuple(sorted(set(all_unbound))),
            )

    @staticmethod
    def _check_replay_target(
        current: SemanticDocumentRevision,
        decision: DecisionRecord,
        existing: DocumentEffect,
        ledger: DocumentEffectLedger,
    ) -> None:
        """Verify *current* is a legitimate replay target for a recorded
        effect.

        Authority must never regress to an earlier revision.  *current* is a
        valid replay target when it is the recorded result or a later
        descendant of the same aggregate.
        """

        if current.semantic_document_revision_id != existing.result_document_id:
            raise DocumentRevisionStaleError(
                semantic_document_revision_id=current.semantic_document_revision_id,
                expected_revision=decision.expected_state_revision,
                actual_revision=current.revision,
            )
        if current.revision == existing.result_revision:
            if document_revision_hash(current) == existing.result_revision_sha256:
                return
        elif current.revision > existing.result_revision:
            cursor_revision = current.revision
            cursor_sha256 = document_revision_hash(current)
            effects = tuple(ledger.effects.values())
            while cursor_revision > existing.result_revision:
                matches = tuple(
                    effect
                    for effect in effects
                    if effect.result_document_id
                    == current.semantic_document_revision_id
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
        raise DocumentRevisionStaleError(
            semantic_document_revision_id=current.semantic_document_revision_id,
            expected_revision=decision.expected_state_revision,
            actual_revision=current.revision,
        )

    @staticmethod
    def _build_revision(
        current: SemanticDocumentRevision,
        study_definition: StudyDefinitionV3,
        decision: DecisionRecord,
        *,
        semantic_blocks: tuple[SemanticBlock, ...],
        chapter_contract_hashes: tuple[str, ...],
        applicability_snapshot_id: str,
        applicability_snapshot_sha256: str,
        now: datetime,
    ) -> SemanticDocumentRevision:
        next_state = _next_canonical_state(current, decision)
        revision = SemanticDocumentRevision(
            semantic_document_revision_id=current.semantic_document_revision_id,
            project_id=current.project_id,
            revision=decision.state_revision,
            previous_revision_sha256=document_revision_hash(current),
            study_definition_id=study_definition.study_definition_id,
            study_definition_sha256=study_revision_hash(study_definition),
            applicability_snapshot_id=applicability_snapshot_id,
            applicability_snapshot_sha256=applicability_snapshot_sha256,
            semantic_blocks=semantic_blocks,
            chapter_contract_hashes=chapter_contract_hashes,
            updated_at=now,
            canonical_state=next_state,
        )
        return (
            revision if revision.schema_version == current.schema_version
            else revision.compact_dependencies()
        )


# ---------------------------------------------------------------------------
# Edit outcome value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EditOutcome:
    """Result of :meth:`SemanticDocumentReducer.classify_and_apply_edit`.

    Exactly one of ``revision`` / ``proposal`` is set:

    * ``applied`` ``True`` → ``revision`` holds the new (or replayed) document
      revision and ``proposal`` is ``None``.
    * ``applied`` ``False`` → ``proposal`` holds the typed fact proposal and
      ``revision`` is ``None``.
    """

    applied: bool
    revision: Optional[SemanticDocumentRevision]
    effective_decision: Optional[DecisionRecord] = None
    ledger: Optional[DocumentEffectLedger] = None
    replayed: bool = False
    proposal: Optional[FactProposal] = None


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------


def document_revision_hash(revision: SemanticDocumentRevision) -> str:
    """Canonical revision hash for a :class:`SemanticDocumentRevision`.

    Binds ``semantic_document_revision_id``, ``revision``,
    ``previous_revision_sha256``, ``canonical_state`` and the material hash so
    that same content at a different revision produces a different snapshot.

    This is the snapshot value a :class:`DecisionRecord` captures in its
    ``snapshot_sha256`` and that a fresh apply must match against the current
    document.
    """

    return canonical_revision_hash(
        aggregate_id=revision.semantic_document_revision_id,
        revision=revision.revision,
        previous_revision_sha256=revision.previous_revision_sha256,
        canonical_state=revision.canonical_state,
        material_sha256_value=revision.material_sha256(),
    )


def _document_payload_sha256(
    semantic_blocks: tuple[SemanticBlock, ...],
    chapter_contract_hashes: tuple[str, ...],
    applicability_snapshot_id: str,
    applicability_snapshot_sha256: str,
    study_definition: StudyDefinitionV3,
) -> str:
    """Material hash of the complete document mutation payload.

    Every field that distinguishes one projection from another participates:
    the semantic blocks (including their content, fact bindings and kind), the
    chapter contract hashes, the applicability snapshot identity and hash, and
    the exact study-definition revision identity.  Same CAS triple with any
    changed payload produces a different hash → conflict.
    """

    return material_sha256(
        {
            "semantic_blocks": tuple(
                block.material_sha256() for block in semantic_blocks
            ),
            "chapter_contract_hashes": chapter_contract_hashes,
            "applicability_snapshot_id": applicability_snapshot_id,
            "applicability_snapshot_sha256": applicability_snapshot_sha256,
            "study_definition_revision_hash": study_revision_hash(study_definition),
        }
    )


def _next_canonical_state(
    current: SemanticDocumentRevision,
    decision: DecisionRecord,
) -> CanonicalState:
    if (
        current.canonical_state is CanonicalState.PROPOSED
        and decision.canonical_state is CanonicalState.CONFIRMED
    ):
        return CanonicalState.CONFIRMED
    return current.canonical_state


def _unbound_paths(
    fact_paths: tuple[str, ...],
    study_definition: StudyDefinitionV3,
) -> set[str]:
    """Return the subset of *fact_paths* absent from the study definition."""

    known = set(study_definition.facts.keys())
    return {path for path in fact_paths if path not in known}
