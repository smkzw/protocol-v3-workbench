"""Strict immutable typed commands for the Protocol v3 application service.

Design authority: Protocol v3 multi-agent rearchitecture design section 5.1
(authority boundary), section 17.2 (only the application service opens a unit
of work) and the frozen plan Task 1.9.  Commands are the ONLY typed entry
surface for canonical mutations; agents, coordinators and API handlers submit
commands and receive typed results/errors, never repository or UoW handles.

Every mutation command is an immutable frozen dataclass carrying:

* ``project_id`` — the project scope for every repository access;
* ``expected_revision`` — the CAS precondition the caller believes is current
  (``0`` means the aggregate must not yet exist);
* ``idempotency_key`` — the side-effect idempotency key (outbox logical key);
* ``actor_type`` / ``actor_id`` — who is issuing the request;
* ``reason`` — a substantive, non-empty justification;
* ``decision_record`` — the full immutable :class:`DecisionRecord` the
  mutation materialises; its ``expected_state_revision`` MUST equal the
  command's ``expected_revision`` and its ``state_revision`` MUST advance it
  exactly once.

The command/DecisionRecord relationship (including the creation snapshot
binding) is validated at construction time — purely, before any repository
use.  The application service additionally validates the command against the
*current aggregate state* (project match, revision and snapshot binding)
before the CAS write.

No public/program UI copy lives here: commands carry domain data only and are
translated to typed results/errors by the application service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Optional

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DecisionRecord,
    JsonValue,
    SideEffectKind,
    StudyDefinitionV3,
)

from app.protocol_workflow.canonical import study_revision_hash
from app.protocol_workflow.canonical.decision_inputs import (
    ConfirmationDependency,
    DecisionInputRef,
    input_refs_payload,
)

__all__ = [
    "ApplyStudyDecisionCommand",
    "CreateStudyDefinitionCommand",
    "SideEffectSpec",
    "TemplateAdoptionIntent",
    "study_definition_genesis_snapshot",
]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _require_non_empty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_expected_revision(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    return value


def _require_actor_type(value: ActorType) -> ActorType:
    if not isinstance(value, ActorType):
        raise ValueError("actor_type must be an ActorType enum value")
    return value


def _require_decision_record(value: DecisionRecord) -> DecisionRecord:
    if not isinstance(value, DecisionRecord):
        raise ValueError("decision_record must be a DecisionRecord")
    return value


def _require_facts(
    value: Mapping[str, JsonValue], label: str
) -> Mapping[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    if not value:
        raise ValueError(f"{label} must not be empty")
    return value


def _validate_decision_alignment(
    decision: DecisionRecord, expected_revision: int
) -> None:
    """Bind the decision CAS triple to the command's CAS precondition."""
    if decision.expected_state_revision != expected_revision:
        raise ValueError(
            "decision_record.expected_state_revision must equal the command "
            f"expected_revision ({expected_revision})"
        )
    if decision.state_revision != expected_revision + 1:
        raise ValueError(
            "decision_record.state_revision must advance the expected CAS "
            "revision exactly once"
        )


# ---------------------------------------------------------------------------
# Genesis snapshot helper
# ---------------------------------------------------------------------------


def study_definition_genesis_snapshot(
    *,
    study_definition_id: str,
    project_id: str,
    normalized_seed_id: str,
    normalized_seed_sha256: str,
    facts: Mapping[str, JsonValue],
    decided_at: datetime,
) -> str:
    """Canonical revision hash of the revision-1 genesis baseline.

    The genesis baseline is the would-be revision-1 :class:`StudyDefinitionV3`
    with the command's seed identity and fact set, an empty decision lineage
    and ``PROPOSED`` state — the store state a create decision is captured
    against (nothing exists at ``expected_state_revision == 0``).  A create
    command's ``decision_record.snapshot_sha256`` MUST equal this hash.
    """

    baseline = StudyDefinitionV3(
        study_definition_id=study_definition_id,
        project_id=project_id,
        revision=1,
        previous_revision_sha256=None,
        normalized_seed_id=normalized_seed_id,
        normalized_seed_sha256=normalized_seed_sha256,
        facts=dict(facts),
        decision_record_ids=(),
        updated_at=decided_at,
        canonical_state=CanonicalState.PROPOSED,
    )
    return study_revision_hash(baseline)


# ---------------------------------------------------------------------------
# Optional outbox side effect
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SideEffectSpec:
    """Optional outbox side effect enqueued atomically with a mutation.

    The outbox ``logical_key`` is the command's ``idempotency_key`` and the
    ``payload_sha256`` is computed by the service from the effect payload, so
    the same idempotency key carrying a *different* decision content fails
    closed at the outbox enqueue step (and the whole transaction rolls back).
    An exact replay never enqueues at all.
    """

    workflow_run_id: str
    side_effect_kind: SideEffectKind

    def __post_init__(self) -> None:
        _require_non_empty(self.workflow_run_id, "workflow_run_id")
        if not isinstance(self.side_effect_kind, SideEffectKind):
            raise ValueError("side_effect_kind must be a SideEffectKind enum value")
        if self.side_effect_kind is SideEffectKind.NONE:
            raise ValueError("side_effect_kind must not be SideEffectKind.NONE")


# ---------------------------------------------------------------------------
# Mutation commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CreateStudyDefinitionCommand:
    """Create the revision-1 StudyDefinition genesis aggregate.

    Creation is itself a canonical mutation: it CAS-creates the genesis
    aggregate at ``expected_revision == 0``, appends a
    ``study_definition.created`` domain event and (optionally) enqueues an
    outbox message in the same unit of work.

    Genesis discipline
    ------------------
    The create ``decision_record`` MUST be ``CONFIRMED`` (the first
    adoption) and MUST carry ``expected_state_revision == 0`` /
    ``state_revision == 1``.  Its ``snapshot_sha256`` MUST bind the genesis
    baseline (:func:`study_definition_genesis_snapshot`).  The created
    aggregate materialises the baseline with the decision lineage and the
    natural PROPOSED → CONFIRMED first-accept transition, mirroring
    :meth:`StudyDefinitionReducer.apply_decision`'s output shape.
    """

    project_id: str
    study_definition_id: str
    idempotency_key: str
    expected_revision: int
    actor_type: ActorType
    actor_id: str
    reason: str
    decision_record: DecisionRecord
    normalized_seed_id: str
    normalized_seed_sha256: str
    initial_facts: Mapping[str, JsonValue]
    side_effect: Optional[SideEffectSpec] = None

    def __post_init__(self) -> None:
        _require_non_empty(self.project_id, "project_id")
        _require_non_empty(self.study_definition_id, "study_definition_id")
        _require_non_empty(self.idempotency_key, "idempotency_key")
        _require_expected_revision(self.expected_revision)
        _require_actor_type(self.actor_type)
        _require_non_empty(self.actor_id, "actor_id")
        _require_non_empty(self.reason, "reason")
        _require_decision_record(self.decision_record)
        _require_non_empty(self.normalized_seed_id, "normalized_seed_id")
        _require_facts(self.initial_facts, "initial_facts")
        if self.expected_revision != 0:
            raise ValueError(
                "create command expected_revision must be 0 "
                "(the aggregate must not yet exist)"
            )
        if self.decision_record.canonical_state is not CanonicalState.CONFIRMED:
            raise ValueError(
                "create decision_record must be CONFIRMED (the first adoption)"
            )
        _validate_decision_alignment(self.decision_record, self.expected_revision)
        expected_snapshot = study_definition_genesis_snapshot(
            study_definition_id=self.study_definition_id,
            project_id=self.project_id,
            normalized_seed_id=self.normalized_seed_id,
            normalized_seed_sha256=self.normalized_seed_sha256,
            facts=self.initial_facts,
            decided_at=self.decision_record.decided_at,
        )
        if self.decision_record.snapshot_sha256 != expected_snapshot:
            raise ValueError(
                "create decision_record.snapshot_sha256 does not bind the "
                "genesis baseline revision hash"
            )


# ---------------------------------------------------------------------------
# Template-bound adoption intent (3R.4D)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TemplateAdoptionIntent:
    """Explicit template context for one fact adoption.

    The intent itself carries only caller-owned choices: which confirmed alias
    mappings and which condition-controlled facts to retire explicitly from
    the current facts, and (optionally) the template identity the caller
    believes it is adopting against — the service binds the actual
    source-bound current template itself and rejects a mismatched echo.
    Fact updates and decision input refs stay in their existing command
    fields; the template context never changes their meaning.  Retirement is
    an explicit removal, never a null write, and immutable history keeps every
    removed value.
    """

    retired_fact_paths: tuple[str, ...] = ()
    template_id: Optional[str] = None

    def __post_init__(self) -> None:
        for path in self.retired_fact_paths:
            _require_non_empty(path, "retired_fact_path")
        if len(set(self.retired_fact_paths)) != len(self.retired_fact_paths):
            raise ValueError("retired fact paths must be unique")
        if self.template_id is not None:
            _require_non_empty(self.template_id, "template_id")


@dataclass(frozen=True)
class ApplyStudyDecisionCommand:
    """Apply an accepted decision to the current StudyDefinition revision.

    The decision CAS triple (``decision_record_id``, ``snapshot_sha256``,
    ``expected_state_revision``) must bind the *current* revision:
    ``expected_revision >= 1``, the snapshot MUST equal the canonical revision
    hash of the current aggregate (validated by the service before repository
    use), and the reducer advances the aggregate to
    ``state_revision == expected_revision + 1``.

    ``fact_updates`` optionally merge new fact paths into the definition;
    overwriting an existing fact while the definition is confirmed/frozen is
    rejected by the reducer (:class:`FrozenFactOverwriteError`).
    """

    project_id: str
    study_definition_id: str
    idempotency_key: str
    expected_revision: int
    actor_type: ActorType
    actor_id: str
    reason: str
    decision_record: DecisionRecord
    fact_updates: Optional[Mapping[str, JsonValue]] = None
    side_effect: Optional[SideEffectSpec] = None
    revise_confirmed_facts: bool = False
    decision_input_refs: Optional[tuple[DecisionInputRef, ...]] = None
    confirmation_dependencies: Optional[tuple[ConfirmationDependency, ...]] = None
    template_adoption: Optional[TemplateAdoptionIntent] = None

    def __post_init__(self) -> None:
        input_refs_payload(self.decision_input_refs)
        if self.confirmation_dependencies is not None:
            object.__setattr__(
                self,
                "confirmation_dependencies",
                tuple(
                    item
                    if isinstance(item, ConfirmationDependency)
                    else ConfirmationDependency.model_validate(item)
                    for item in self.confirmation_dependencies
                ),
            )
        if type(self.revise_confirmed_facts) is not bool:
            raise ValueError("revise_confirmed_facts must be a native boolean")
        if self.template_adoption is not None:
            if not isinstance(self.template_adoption, TemplateAdoptionIntent):
                raise ValueError(
                    "template_adoption must be a TemplateAdoptionIntent"
                )
            if self.revise_confirmed_facts is not True:
                raise ValueError(
                    "template-bound adoption requires explicit confirmed fact "
                    "revision intent"
                )
        _require_non_empty(self.project_id, "project_id")
        _require_non_empty(self.study_definition_id, "study_definition_id")
        _require_non_empty(self.idempotency_key, "idempotency_key")
        _require_expected_revision(self.expected_revision)
        _require_actor_type(self.actor_type)
        _require_non_empty(self.actor_id, "actor_id")
        _require_non_empty(self.reason, "reason")
        _require_decision_record(self.decision_record)
        if self.expected_revision < 1:
            raise ValueError("apply command expected_revision must be >= 1")
        _validate_decision_alignment(self.decision_record, self.expected_revision)
        if self.fact_updates is not None and not isinstance(
            self.fact_updates, Mapping
        ):
            raise ValueError("fact_updates must be a mapping or None")
