"""Application service for Protocol v3 canonical mutations and queries.

Design authority: Protocol v3 multi-agent rearchitecture design sections 5.1
(authority boundary), 5.4 (Agent⑤ coordination boundary), 17.2 (Harness
Adapter / only the application service opens a unit of work), 18 (LangGraph,
recovery and error handling) and 19 (four-layer submission gate).

This service is the ONLY component that opens a unit of work and obtains
repositories (design section 17.2).  Agents and API handlers receive a narrow
command/query façade — never a ``UnitOfWorkFactory``, repositories, reducers
or CAS handles.

Contract
--------
* Every canonical mutation is an immutable typed command
  (``commands.py``) carrying project/revision/idempotency/actor/reason and a
  full immutable ``DecisionRecord``; the command/project/DecisionRecord
  relationship is validated before repository use (construction-time for
  genesis binding, service-level for project match / revision / snapshot).
* A mutation composes the accepted ``StudyDefinitionReducer``
  (``replay_or_apply``) with the accepted ``EventSourcedUnitOfWork``
  (``build_and_apply``): canonical CAS save, domain event append and optional
  outbox enqueue commit in ONE transaction.  An exact replay returns the prior
  result and performs no second write.
* The ``DecisionEffectLedger`` is rebuilt from the project event stream before
  each mutation (design section 18: the event log is authoritative).
* Queries are explicit typed read operations through a fresh UoW and never
  write.
* Failures are translated to the finite typed error catalog
  (``protocol_workflow.errors``) and public/program text never leaves this
  layer; no repository/UoW handle appears in any return value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    DecisionRecord,
    DomainEvent,
    StudyDefinitionV3,
)

from app.protocol_workflow.canonical import (
    DecisionEffect,
    DecisionEffectLedger,
    DecisionPayloadConflictError,
    FrozenFactOverwriteError,
    RevisionStaleError,
    StudyDefinitionReducer,
    decision_cas_identity,
    exact_payload_sha256,
    material_sha256,
    study_revision_hash,
)
from app.protocol_workflow.canonical.study_definition import (
    TEMPLATE_FACT_ADOPTION_OPERATION,
)
from app.protocol_workflow.canonical.decision_inputs import (
    ConfirmationBinding,
    DecisionInputBinding,
    bind_confirmation_dependencies,
    bind_decision_inputs,
    confirmation_validity,
    current_input_validity,
)
from app.protocol_workflow.errors import (
    ProtocolErrorCode,
    ProtocolErrorOwner,
    ProtocolWorkflowError,
)
from app.protocol_workflow.events.unit_of_work import (
    EventSourcedUnitOfWork,
    MissingRepositoryError,
    MutationAbortedError,
    SideEffectRequest,
)
from app.protocol_workflow.ports.repositories import (
    AggregateNotFoundError,
    DecisionGraphRecord,
    EventSequenceConflictError,
    IdempotencyConflictError,
    OutboxMessage,
    RevisionConflictError,
    WorkflowRunStatusRecord,
)
from app.protocol_workflow.registries.template_runtime import CurrentTemplate
from app.protocol_workflow.storage.selected import UnitOfWorkFactory

from .adoption import (
    TEMPLATE_FACT_ADOPTION_SCHEMA,
    GetTemplateAdoptionQuery,
    TemplateAdoptionFlow,
    TemplateAdoptionQueryResult,
    TemplateAdoptionValidationError,
    adoption_intent_material,
    prepare_template_adoption,
    recompute_adoption_intent_sha256,
    validate_retirement_presence,
)
from .commands import (
    ApplyStudyDecisionCommand,
    CreateStudyDefinitionCommand,
    study_definition_genesis_snapshot,
)
from .queries import (
    GetSemanticDocumentQuery,
    SemanticDocumentQueryResult,
    RecoverStudyDecisionQuery,
    ListStudyDefinitionsQuery,
    DecisionGraphQueryResult,
    DecisionSummary,
    EventSummaryQueryResult,
    GetDecisionGraphQuery,
    GetStudyDefinitionEventSummaryQuery,
    GetStudyDefinitionQuery,
    GetWorkflowRunStatusQuery,
    StudyDefinitionQueryResult,
    WorkflowRunStatusQueryResult,
)

__all__ = [
    "EVENT_TYPE_CREATED",
    "EVENT_TYPE_DECISION_APPLIED",
    "ApplicationService",
    "StudyDefinitionMutationResult",
    "study_definition_stream_id",
]


# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

EVENT_TYPE_CREATED: str = "study_definition.created"
EVENT_TYPE_DECISION_APPLIED: str = "study_definition.decision_applied"
_DECISION_EVENT_TYPES: frozenset[str] = frozenset(
    {EVENT_TYPE_CREATED, EVENT_TYPE_DECISION_APPLIED}
)
_EVENT_SCHEMA_VERSION: str = "mw_protocol_v3_event_v1"
_EVENT_UPCASTER_ID: str = "noop:v1"
_CAS_REPOSITORY_HANDLE: str = "study_definition_cas_repository"


# ---------------------------------------------------------------------------
# Stream identity
# ---------------------------------------------------------------------------


def study_definition_stream_id(study_definition_id: str) -> str:
    """Deterministic event-stream identity for one StudyDefinition aggregate.

    The stream is scoped by ``(project_id, stream_id)`` in the event
    repository; the same ``study_definition_id`` in different projects
    produces distinct streams by virtue of the project-scope prefix.
    """

    return f"stream:study_definition:{study_definition_id}"


# ---------------------------------------------------------------------------
# Internal typed errors (translated before leaving the service)
# ---------------------------------------------------------------------------


class _ApplicationServiceError(RuntimeError):
    """Base for application-layer internal failures."""


class _ProjectMismatchError(_ApplicationServiceError):
    """Command project does not match the aggregate's project."""

    __slots__ = ("expected_project", "actual_project")

    def __init__(self, *, expected_project: str, actual_project: str) -> None:
        self.expected_project = expected_project
        self.actual_project = actual_project
        super().__init__(
            f"command project {expected_project!r} does not match aggregate "
            f"project {actual_project!r}"
        )


class _LedgerRebuildError(_ApplicationServiceError):
    """The event stream contains a corrupt or incomplete decision effect."""

    __slots__ = ("event_id", "detail")

    def __init__(self, *, event_id: str, detail: str) -> None:
        self.event_id = event_id
        self.detail = detail
        super().__init__(f"ledger rebuild failed for event {event_id}: {detail}")


class _MissingRepositoryError(_ApplicationServiceError):
    """A required repository handle is absent from the UoW scope."""


class _CurrentTemplateUnavailableError(_ApplicationServiceError):
    """The configured current-template loader failed or is absent."""


# ---------------------------------------------------------------------------
# Mutation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StudyDefinitionMutationResult:
    """Typed outcome of a canonical StudyDefinition mutation.

    ``replayed`` is ``True`` when the command was an exact CAS replay: no
    second revision/event/outbox was written and ``definition`` is the
    current aggregate unchanged.  ``appended_events`` and ``enqueued_outbox``
    are empty on replay.  No repository or unit-of-work handle is exposed.
    """

    project_id: str
    study_definition_id: str
    definition: StudyDefinitionV3
    revision: int
    revision_sha256: str
    effective_decision: DecisionRecord
    replayed: bool
    appended_events: Tuple[DomainEvent, ...] = ()
    enqueued_outbox: Optional[OutboxMessage] = None


# ---------------------------------------------------------------------------
# Clock default
# ---------------------------------------------------------------------------


def _default_utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Application service
# ---------------------------------------------------------------------------


class ApplicationService:
    """Storage-neutral command/query façade — the only canonical mutation
    boundary (design section 5.1 / 17.2).

    Accepts an injected ``UnitOfWorkFactory`` (protocol from
    ``storage.selected``); production storage selection remains fail-closed
    outside this layer.
    """

    __slots__ = ("_factory", "_clock", "_coordinator", "_reducer", "_current_template_loader")

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        coordinator: Optional[EventSourcedUnitOfWork] = None,
        clock: Optional[Callable[[], datetime]] = None,
        current_template_loader: Optional[Callable[[], CurrentTemplate]] = None,
    ) -> None:
        if not callable(unit_of_work_factory):
            raise ValueError("unit_of_work_factory must be callable")
        if current_template_loader is not None and not callable(current_template_loader):
            raise ValueError("current_template_loader must be callable or None")
        self._factory = unit_of_work_factory
        self._clock: Callable[[], datetime] = (
            clock if clock is not None else _default_utc_now
        )
        self._coordinator: EventSourcedUnitOfWork = (
            coordinator
            if coordinator is not None
            else EventSourcedUnitOfWork(clock=self._clock)
        )
        self._reducer: StudyDefinitionReducer = StudyDefinitionReducer()
        self._current_template_loader = current_template_loader

    # ------------------------------------------------------------------
    # Public mutation API
    # ------------------------------------------------------------------

    def create_study_definition(
        self, command: CreateStudyDefinitionCommand
    ) -> StudyDefinitionMutationResult:
        """Create the genesis revision-1 StudyDefinition atomically.

        On exact replay (same ``decision_record_id``, ``snapshot_sha256``
        and ``expected_state_revision`` triple carrying an identical payload
        against an aggregate whose revision matches the recorded result) the
        prior result is returned with no second write.
        """

        stream_id = study_definition_stream_id(command.study_definition_id)
        try:
            with self._factory() as uow:
                repo = self._require_study_repo(uow)
                current = repo.get_current(
                    command.project_id, command.study_definition_id
                )
                events = self._read_stream(
                    uow, command.project_id, stream_id
                )
                ledger = self._rebuild_ledger(
                    events,
                    project_id=command.project_id,
                    study_definition_id=command.study_definition_id,
                )
                now = self._clock()

                if current is not None:
                    # Aggregate exists: only an exact replay of the same
                    # create decision may proceed (ledger-first classification);
                    # a different create decision fails closed as stale.
                    new_def, effective, _ledger, replayed = self._reducer.replay_or_apply(
                        current, command.decision_record, ledger, now=now,
                    )
                    return StudyDefinitionMutationResult(
                        project_id=command.project_id,
                        study_definition_id=command.study_definition_id,
                        definition=new_def,
                        revision=new_def.revision,
                        revision_sha256=study_revision_hash(new_def),
                        effective_decision=effective,
                        replayed=replayed,
                    )

                # Fresh create: validate the genesis discipline (pure defence-
                # in-depth — construction already enforces the invariant).
                self._validate_create_genesis(command)

                baseline = StudyDefinitionV3(
                    study_definition_id=command.study_definition_id,
                    project_id=command.project_id,
                    revision=1,
                    previous_revision_sha256=None,
                    normalized_seed_id=command.normalized_seed_id,
                    normalized_seed_sha256=command.normalized_seed_sha256,
                    facts=dict(command.initial_facts),
                    decision_record_ids=(),
                    updated_at=now,
                    canonical_state=CanonicalState.PROPOSED,
                )
                created = baseline.model_copy(
                    update={
                        "decision_record_ids": (
                            command.decision_record.decision_record_id,
                        ),
                        "canonical_state": _first_accept_state(
                            command.decision_record
                        ),
                    }
                )

                cas_id = decision_cas_identity(
                    command.decision_record.decision_record_id,
                    command.decision_record.snapshot_sha256,
                    command.decision_record.expected_state_revision,
                )
                effect = DecisionEffect(
                    cas_identity=cas_id,
                    decision_record=command.decision_record,
                    decision_record_sha256=command.decision_record.material_sha256(),
                    fact_updates_sha256=material_sha256({}),
                    result_study_definition_id=created.study_definition_id,
                    result_revision=created.revision,
                    result_previous_revision_sha256=created.previous_revision_sha256,
                    result_revision_sha256=study_revision_hash(created),
                )
                payload = _effect_payload(
                    effect,
                    project_id=command.project_id,
                    study_definition_id=command.study_definition_id,
                    idempotency_key=command.idempotency_key,
                    fact_updates=None,
                )
                # Additive reconstruction extension: old decision-ledger events
                # remain readable and are never rewritten. New streams carry
                # their immutable genesis, independent of the current snapshot.
                payload["reconstruction_schema_version"] = "study_genesis_v1"
                payload["genesis_definition"] = created.model_dump(mode="json")
                side = _build_side_effect(
                    command.idempotency_key, command.side_effect,
                    payload_sha256=exact_payload_sha256(payload),
                )
                atomic = self._coordinator.build_and_apply(
                    uow,
                    project_id=command.project_id,
                    stream_id=stream_id,
                    aggregate=created,
                    cas_repository_handle_name=_CAS_REPOSITORY_HANDLE,
                    expected_revision=0,
                    event=_event_kwargs(
                        stream_id=stream_id,
                        event_type=EVENT_TYPE_CREATED,
                        domain_event_id=_decision_event_id(
                            stream_id, cas_id
                        ),
                        actor_type=command.actor_type,
                        actor_id=command.actor_id,
                        action=EVENT_TYPE_CREATED,
                        reason=command.reason,
                        payload=payload,
                        emitted_at=now,
                    ),
                    side_effect=side,
                )
                agg = atomic.saved_aggregate
                assert isinstance(agg, StudyDefinitionV3)
                return StudyDefinitionMutationResult(
                    project_id=command.project_id,
                    study_definition_id=command.study_definition_id,
                    definition=agg,
                    revision=agg.revision,
                    revision_sha256=study_revision_hash(agg),
                    effective_decision=command.decision_record,
                    replayed=False,
                    appended_events=atomic.appended_events,
                    enqueued_outbox=atomic.enqueued_outbox,
                )
        except _EXCEPTION_MAP as exc:
            raise _translate(
                exc,
                project_id=command.project_id,
                object_id=command.study_definition_id,
                idempotency_key=command.idempotency_key,
                decision_record_id=command.decision_record.decision_record_id,
                expected_revision=command.expected_revision,
            ) from exc

    def apply_decision(
        self, command: ApplyStudyDecisionCommand
    ) -> StudyDefinitionMutationResult:
        """Apply an accepted decision to the current StudyDefinition revision."""

        stream_id = study_definition_stream_id(command.study_definition_id)
        try:
            with self._factory() as uow:
                repo = self._require_study_repo(uow)
                current = repo.get_current(
                    command.project_id, command.study_definition_id
                )
                if current is None:
                    raise AggregateNotFoundError(
                        command.project_id,
                        aggregate_id=command.study_definition_id,
                    )
                if current.project_id != command.project_id:
                    raise _ProjectMismatchError(
                        expected_project=command.project_id,
                        actual_project=current.project_id,
                    )
                events = self._read_stream(
                    uow, command.project_id, stream_id
                )
                ledger = self._rebuild_ledger(
                    events,
                    project_id=command.project_id,
                    study_definition_id=command.study_definition_id,
                )
                now = self._clock()

                cas_id = decision_cas_identity(
                    command.decision_record.decision_record_id,
                    command.decision_record.snapshot_sha256,
                    command.decision_record.expected_state_revision,
                )
                # Ledger-first: the request-level adoption intent is all the
                # reducer needs for replay classification, so an exact replay
                # never loads the current template and template drift never
                # invalidates an identical caller request.  The loaded
                # template is enforced only on a genuinely fresh apply.
                adoption_flow: Optional[TemplateAdoptionFlow] = None
                intent_material: Optional[Mapping[str, Any]] = None
                if command.template_adoption is not None:
                    intent_material = adoption_intent_material(
                        retired_fact_paths=(
                            command.template_adoption.retired_fact_paths
                        ),
                        request_template_id=command.template_adoption.template_id,
                    )
                if ledger.find(cas_id) is None:
                    # Genuinely fresh decision: validate before CAS write.
                    self._validate_fresh_apply(command, current)
                    # One logical operation per idempotency key within this
                    # aggregate — a different decision reusing the key is a
                    # conflict with zero effects (no side effect required).
                    self._reject_reused_idempotency_key(
                        events, command, cas_id
                    )
                    if command.template_adoption is not None:
                        try:
                            template = self._load_current_template()
                        except _CurrentTemplateUnavailableError:
                            raise
                        except (ValueError, OSError) as exc:
                            # Any current-template acquisition failure is a
                            # configuration problem, never a request error.
                            raise _CurrentTemplateUnavailableError(str(exc)) from exc
                        adoption_flow = prepare_template_adoption(
                            template=template,
                            retired_fact_paths=(
                                command.template_adoption.retired_fact_paths
                            ),
                            template_id=command.template_adoption.template_id,
                        )
                        # State-dependent intent checks run only on a fresh
                        # apply, after the ledger proved no prior effect.
                        validate_retirement_presence(
                            adoption_flow.retired_fact_paths, current.facts
                        )

                new_def, effective, _ledger, replayed = self._reducer.replay_or_apply(
                    current,
                    command.decision_record,
                    ledger,
                    fact_updates=command.fact_updates,
                    now=now,
                    revise_confirmed_facts=command.revise_confirmed_facts,
                    decision_input_refs=command.decision_input_refs,
                    retired_fact_paths=(
                        adoption_flow.retired_fact_paths
                        if adoption_flow is not None
                        else None
                    ),
                    adoption_material=intent_material,
                )

                if replayed:
                    return StudyDefinitionMutationResult(
                        project_id=command.project_id,
                        study_definition_id=command.study_definition_id,
                        definition=new_def,
                        revision=new_def.revision,
                        revision_sha256=study_revision_hash(new_def),
                        effective_decision=effective,
                        replayed=True,
                    )

                effect = _ledger.find(cas_id)
                assert effect is not None
                payload = _effect_payload(
                    effect,
                    project_id=command.project_id,
                    study_definition_id=command.study_definition_id,
                    idempotency_key=command.idempotency_key,
                    fact_updates=command.fact_updates,
                )
                if adoption_flow is not None:
                    # Validation, snapshot and impact plan run BEFORE any write
                    # and bind the exact base/result revisions; a rejection
                    # aborts the unit of work with nothing durable.
                    payload["operation"] = TEMPLATE_FACT_ADOPTION_OPERATION
                    payload["template_adoption"] = (
                        adoption_flow.validate_and_build_payload(
                            facts_before=current.facts,
                            adopted=new_def,
                            facts_before_revision=current.revision,
                            facts_before_revision_sha256=study_revision_hash(current),
                            request_template_id=(
                                command.template_adoption.template_id
                            ),
                            now=now,
                        )
                    )
                elif command.revise_confirmed_facts:
                    payload["operation"] = "confirmed_fact_revision.v1"
                if command.decision_input_refs is not None:
                    payload["decision_input_binding"] = bind_decision_inputs(
                        command.decision_input_refs, new_def.facts, study_revision_hash(new_def)
                    ).model_dump(mode="json")
                if command.confirmation_dependencies is not None:
                    payload["confirmation_binding"] = bind_confirmation_dependencies(
                        command.decision_record.decision_key,
                        command.confirmation_dependencies,
                        new_def.facts,
                        study_revision_hash(new_def),
                    ).model_dump(mode="json")
                side = _build_side_effect(
                    command.idempotency_key, command.side_effect,
                    payload_sha256=exact_payload_sha256(payload),
                )
                atomic = self._coordinator.build_and_apply(
                    uow,
                    project_id=command.project_id,
                    stream_id=stream_id,
                    aggregate=new_def,
                    cas_repository_handle_name=_CAS_REPOSITORY_HANDLE,
                    expected_revision=command.expected_revision,
                    event=_event_kwargs(
                        stream_id=stream_id,
                        event_type=EVENT_TYPE_DECISION_APPLIED,
                        domain_event_id=_decision_event_id(
                            stream_id, cas_id
                        ),
                        actor_type=command.actor_type,
                        actor_id=command.actor_id,
                        action=EVENT_TYPE_DECISION_APPLIED,
                        reason=command.reason,
                        payload=payload,
                        emitted_at=now,
                    ),
                    side_effect=side,
                )
                agg = atomic.saved_aggregate
                assert isinstance(agg, StudyDefinitionV3)
                return StudyDefinitionMutationResult(
                    project_id=command.project_id,
                    study_definition_id=command.study_definition_id,
                    definition=agg,
                    revision=agg.revision,
                    revision_sha256=study_revision_hash(agg),
                    effective_decision=effective,
                    replayed=False,
                    appended_events=atomic.appended_events,
                    enqueued_outbox=atomic.enqueued_outbox,
                )
        except _EXCEPTION_MAP as exc:
            raise _translate(
                exc,
                project_id=command.project_id,
                object_id=command.study_definition_id,
                idempotency_key=command.idempotency_key,
                decision_record_id=command.decision_record.decision_record_id,
                expected_revision=command.expected_revision,
            ) from exc

    # ------------------------------------------------------------------
    # Public query API
    # ------------------------------------------------------------------

    def lookup_decision(self, query: RecoverStudyDecisionQuery) -> Optional[StudyDefinitionMutationResult]:
        """Read an intact committed receipt, independent of later producer code."""
        record = query.decision_record
        try:
            with self._factory() as uow:
                current = self._require_study_repo(uow).get_current(query.project_id, query.study_definition_id)
                if current is None:
                    raise AggregateNotFoundError(query.project_id, aggregate_id=query.study_definition_id)
                events = self._read_stream(uow, query.project_id, study_definition_stream_id(query.study_definition_id))
                ledger = self._rebuild_ledger(events, project_id=query.project_id,
                                              study_definition_id=query.study_definition_id)
                cas_id = decision_cas_identity(record.decision_record_id, record.snapshot_sha256,
                                               record.expected_state_revision)
                self._reject_reused_idempotency_key(events, query, cas_id)
                effect = ledger.find(cas_id)
                if effect is None:
                    return None
                # The operation must name this recorded CAS, not just another
                # operation carrying an otherwise identical human decision.
                if not any(e.payload.get("idempotency_key") == query.idempotency_key
                           and e.payload.get("cas_identity") == cas_id for e in events):
                    return None
                incoming_sha = record.material_sha256()
                if effect.decision_record_sha256 != incoming_sha:
                    raise DecisionPayloadConflictError(query.study_definition_id, record.expected_state_revision,
                        cas_id, "decision_record", effect.decision_record_sha256, incoming_sha)
                return StudyDefinitionMutationResult(project_id=query.project_id,
                    study_definition_id=query.study_definition_id, definition=current,
                    revision=current.revision, revision_sha256=study_revision_hash(current),
                    effective_decision=effect.decision_record, replayed=True)
        except _EXCEPTION_MAP as exc:
            raise _translate(exc, project_id=query.project_id, object_id=query.study_definition_id,
                idempotency_key=query.idempotency_key, decision_record_id=record.decision_record_id,
                expected_revision=record.expected_state_revision) from exc

    def recover_decision(self, command: ApplyStudyDecisionCommand) -> Optional[StudyDefinitionMutationResult]:
        """Find an exact committed intent without attempting a fresh application.

        A missing receipt says only that no matching commit was observed. It
        does not authorize redispatch of an uncertain or still-running request.
        Existing reducer replay checks bind the complete original material;
        current templates are neither loaded nor applied during this lookup.
        """
        try:
            with self._factory() as uow:
                current = self._require_study_repo(uow).get_current(command.project_id, command.study_definition_id)
                if current is None:
                    raise AggregateNotFoundError(command.project_id, aggregate_id=command.study_definition_id)
                events = self._read_stream(uow, command.project_id, study_definition_stream_id(command.study_definition_id))
                ledger = self._rebuild_ledger(events, project_id=command.project_id,
                                              study_definition_id=command.study_definition_id)
                cas_id = decision_cas_identity(command.decision_record.decision_record_id,
                    command.decision_record.snapshot_sha256, command.decision_record.expected_state_revision)
                self._reject_reused_idempotency_key(events, command, cas_id)
                if ledger.find(cas_id) is None:
                    return None
                material = None if command.template_adoption is None else adoption_intent_material(
                    retired_fact_paths=command.template_adoption.retired_fact_paths,
                    request_template_id=command.template_adoption.template_id)
                definition, effective, _, replayed = self._reducer.replay_or_apply(
                    current, command.decision_record, ledger, fact_updates=command.fact_updates,
                    now=self._clock(), revise_confirmed_facts=command.revise_confirmed_facts,
                    decision_input_refs=command.decision_input_refs, adoption_material=material)
                assert replayed  # The committed ledger entry was found above.
                return StudyDefinitionMutationResult(project_id=command.project_id,
                    study_definition_id=command.study_definition_id, definition=definition,
                    revision=definition.revision, revision_sha256=study_revision_hash(definition),
                    effective_decision=effective, replayed=True)
        except _EXCEPTION_MAP as exc:
            raise _translate(exc, project_id=command.project_id, object_id=command.study_definition_id,
                idempotency_key=command.idempotency_key,
                decision_record_id=command.decision_record.decision_record_id,
                expected_revision=command.expected_revision) from exc

    def list_study_definitions(self, query: ListStudyDefinitionsQuery) -> tuple[StudyDefinitionQueryResult, ...]:
        """Discover existing identities without creating a competing study."""
        try:
            with self._factory() as uow:
                definitions = self._require_study_repo(uow).list_current(query.project_id)
                return tuple(StudyDefinitionQueryResult(definition=definition,
                    revision=definition.revision, revision_sha256=study_revision_hash(definition))
                    for definition in definitions)
        except _EXCEPTION_MAP as exc:
            raise _translate(exc, project_id=query.project_id, object_id=query.project_id) from exc

    def get_study_definition(
        self, query: GetStudyDefinitionQuery
    ) -> StudyDefinitionQueryResult:
        """Read the current StudyDefinition aggregate and its revision hash."""

        try:
            with self._factory() as uow:
                repo = self._require_study_repo(uow)
                current = repo.get_current(
                    query.project_id, query.study_definition_id
                )
                if current is None:
                    return StudyDefinitionQueryResult(
                        definition=None, revision=None, revision_sha256=None
                    )
                return StudyDefinitionQueryResult(
                    definition=current,
                    revision=current.revision,
                    revision_sha256=study_revision_hash(current),
                )
        except _EXCEPTION_MAP as exc:
            raise _translate(
                exc,
                project_id=query.project_id,
                object_id=query.study_definition_id,
            ) from exc

    def get_manuscript_plan(self, query: GetStudyDefinitionQuery):
        """Prepare every carrier from one immutable current study read."""
        from app.protocol_workflow.agent3.manuscript_plan import manuscript_preparation_view
        current = self.get_study_definition(query)
        if current.definition is None:
            return None
        try:
            return manuscript_preparation_view(self._load_current_template(), current.definition)
        except _EXCEPTION_MAP as exc:
            raise _translate(exc, project_id=query.project_id,
                             object_id=query.study_definition_id) from exc

    def prepare_manuscript_chapter(self, query: GetStudyDefinitionQuery, *, node_id,
                                   source_preparation, source_run_id, expected_study_sha256):
        """Pin a current study and a completed source bundle without dispatching.

        Historical generation recovery reads its original request elsewhere;
        this fresh preparation must match the study the user is viewing.
        """
        from app.protocol_workflow.agent3.chapter_draft import prepare_study_chapter
        from app.protocol_workflow.agent3.source_preparation import SourcePreparationIncomplete
        current = self.get_study_definition(query)
        if current.definition is None:
            raise ValueError('chapter_study_missing')
        if current.revision_sha256 != expected_study_sha256:
            raise ValueError('chapter_study_revision_changed')
        if source_preparation.project_id != query.project_id:
            raise ValueError('chapter_source_context_changed')
        seed = source_preparation.prepared_seed(source_run_id)
        context = current.definition.facts.get('research.input_context')
        if not isinstance(context, dict) or context.get('source_intake_sha256') != seed.input_sha256:
            raise ValueError('chapter_source_context_changed')
        bundle = source_preparation.read(source_run_id)
        if bundle is None:
            raise SourcePreparationIncomplete(source_preparation.state(source_run_id))
        return prepare_study_chapter(self._load_current_template(), current.definition,
            node_id, bundle.evidence, source_material=bundle)

    def get_semantic_document(self, query: GetSemanticDocumentQuery) -> SemanticDocumentQueryResult:
        """Read persisted text and its study binding in one transaction.

        A changed study does not rewrite the manuscript or prove that every
        paragraph is clinically invalid. It requires affected-content review.
        """
        from app.protocol_workflow.canonical.document import document_revision_hash
        try:
            with self._factory() as uow:
                repo = uow.semantic_document_repository
                if repo is None:
                    raise _MissingRepositoryError("semantic_document_repository")
                document = repo.get_current(query.project_id, query.semantic_document_revision_id)
                if document is None or document.study_definition_id != query.study_definition_id:
                    return SemanticDocumentQueryResult(None, None, "missing")
                study = self._require_study_repo(uow).get_current(query.project_id, query.study_definition_id)
                binding = ("missing" if study is None else "current"
                           if study_revision_hash(study) == document.study_definition_sha256 else "changed")
                return SemanticDocumentQueryResult(document, document_revision_hash(document), binding)
        except _EXCEPTION_MAP as exc:
            raise _translate(exc, project_id=query.project_id,
                             object_id=query.semantic_document_revision_id) from exc

    def get_study_definition_event_summary(
        self, query: GetStudyDefinitionEventSummaryQuery
    ) -> EventSummaryQueryResult:
        """Read the event-stream head and decision lineage from the stream."""

        stream_id = study_definition_stream_id(query.study_definition_id)
        try:
            with self._factory() as uow:
                ev_repo = uow.event_stream_repository
                if ev_repo is None:
                    raise _MissingRepositoryError(
                        "event_stream_repository"
                    )
                events = ev_repo.read_events(query.project_id, stream_id)
                ledger = self._rebuild_ledger(
                    events,
                    project_id=query.project_id,
                    study_definition_id=query.study_definition_id,
                )
                head = ev_repo.get_stream_head(query.project_id, stream_id)
                decisions = tuple(
                    sorted(
                        (
                            DecisionSummary(
                                cas_identity=eff.cas_identity,
                                decision_record_id=eff.decision_record.decision_record_id,
                                decision_key=eff.decision_record.decision_key,
                                selected_option_id=eff.decision_record.selected_option_id,
                                state_revision=eff.decision_record.state_revision,
                                applied_revision=eff.result_revision,
                                canonical_state=eff.decision_record.canonical_state,
                                decided_at=eff.decision_record.decided_at,
                            )
                            for eff in ledger.effects.values()
                        ),
                        key=lambda d: (d.state_revision, d.cas_identity),
                    )
                )
                return EventSummaryQueryResult(
                    project_id=query.project_id,
                    study_definition_id=query.study_definition_id,
                    event_count=head.event_count if head is not None else 0,
                    last_sequence=head.last_sequence if head is not None else None,
                    last_event_sha256=(
                        head.last_event_sha256 if head is not None else None
                    ),
                    decisions=decisions,
                )
        except _EXCEPTION_MAP as exc:
            raise _translate(
                exc,
                project_id=query.project_id,
                object_id=query.study_definition_id,
            ) from exc

    def get_decision_graph(
        self, query: GetDecisionGraphQuery
    ) -> DecisionGraphQueryResult:
        """Read the latest applied decision per key from authoritative events."""

        try:
            with self._factory() as uow:
                rm = uow.read_model_repository
                if rm is None:
                    raise _MissingRepositoryError("read_model_repository")
                # Planned decision nodes may exist before the first study revision.
                planned = rm.get_decision_graph(query.project_id, query.study_definition_id)
                events = self._read_stream(
                    uow, query.project_id,
                    study_definition_stream_id(query.study_definition_id),
                )
                ledger = self._rebuild_ledger(
                    events, project_id=query.project_id,
                    study_definition_id=query.study_definition_id,
                )
                # Reconstruct from committed events rather than an unmaintained cache.
                # Legacy decisions have no bound input read-set: do not label them current.
                current = self._require_study_repo(uow).get_current(
                    query.project_id, query.study_definition_id
                )
                bindings = {}
                confirmations = {}
                for event in events:
                    payload = event.payload
                    if event.event_type not in _DECISION_EVENT_TYPES:
                        continue
                    if "decision_input_binding" in payload:
                        try:
                            binding = DecisionInputBinding.model_validate(payload["decision_input_binding"])
                            if binding.adopted_revision_sha256 != payload["result_revision_sha256"]:
                                raise ValueError("input binding revision mismatch")
                            bindings[payload["cas_identity"]] = binding
                        except (KeyError, TypeError, ValueError) as exc:
                            raise _LedgerRebuildError(event_id=event.domain_event_id, detail=str(exc)) from exc
                    if "confirmation_binding" in payload:
                        try:
                            confirmed = ConfirmationBinding.model_validate(payload["confirmation_binding"])
                            if confirmed.adopted_revision_sha256 != payload["result_revision_sha256"]:
                                raise ValueError("confirmation binding revision mismatch")
                            prior = confirmations.get(confirmed.decision_key)
                            if prior is not None and prior != confirmed:
                                # The same decision key must not carry two
                                # different medical-dependency declarations;
                                # surfacing the conflict instead of silently
                                # trusting the newest declaration.
                                raise ValueError(
                                    "conflicting confirmation dependency declarations for "
                                    f"{confirmed.decision_key}"
                                )
                            confirmations[confirmed.decision_key] = confirmed
                        except (KeyError, TypeError, ValueError) as exc:
                            raise _LedgerRebuildError(event_id=event.domain_event_id, detail=str(exc)) from exc
                latest = {record.decision_key: record for record in planned}
                for effect in sorted(ledger.effects.values(), key=lambda e: e.result_revision):
                    decision = effect.decision_record
                    confirmed = confirmations.get(decision.decision_key)
                    if confirmed is not None and current is not None:
                        # Medical dependencies drive the user-facing validity;
                        # the producer read-set stays recorded for production
                        # reconciliation but no longer reopens this card.
                        validity = confirmation_validity(confirmed, current.facts)
                    elif effect.cas_identity in bindings and current is not None:
                        validity = current_input_validity(bindings[effect.cas_identity], current.facts)
                    else:
                        validity = "unverified"
                    latest[decision.decision_key] = DecisionGraphRecord(
                        project_id=query.project_id,
                        decision_key=decision.decision_key,
                        decision_record_id=decision.decision_record_id,
                        state_revision=decision.state_revision,
                        selected_option_id=decision.selected_option_id,
                        canonical_state=decision.canonical_state,
                        current_validity=validity,
                    )
                records = tuple(latest[key] for key in sorted(latest))
                return DecisionGraphQueryResult(
                    project_id=query.project_id,
                    study_definition_id=query.study_definition_id,
                    records=tuple(records),
                )
        except _EXCEPTION_MAP as exc:
            raise _translate(
                exc,
                project_id=query.project_id,
                object_id=query.study_definition_id,
            ) from exc

    def get_template_adoption(
        self, query: GetTemplateAdoptionQuery
    ) -> Optional[TemplateAdoptionQueryResult]:
        """Read the latest template-bound adoption record from the events.

        Read-only: the record is the versioned adoption part of the committed
        decision event, re-verified for its identity bindings before it is
        returned.  ``None`` means this study has no template-bound adoption.
        """

        try:
            with self._factory() as uow:
                ev_repo = uow.event_stream_repository
                if ev_repo is None:
                    raise _MissingRepositoryError("event_stream_repository")
                events = ev_repo.read_events(
                    query.project_id,
                    study_definition_stream_id(query.study_definition_id),
                )
                for event in reversed(events):
                    payload = event.payload
                    if (
                        event.event_type not in _DECISION_EVENT_TYPES
                        or "template_adoption" not in payload
                    ):
                        continue
                    adoption = payload["template_adoption"]
                    try:
                        if adoption.get("schema_version") != TEMPLATE_FACT_ADOPTION_SCHEMA:
                            raise ValueError("unsupported template adoption schema")
                        if (
                            adoption["result_revision_sha256"]
                            != payload["result_revision_sha256"]
                        ):
                            raise ValueError(
                                "adoption result hash does not bind the committed event"
                            )
                        snapshot = adoption["applicability_snapshot"]
                        plan = adoption["impact_plan"]
                        template = adoption["template"]
                        if (
                            snapshot["study_definition_sha256"]
                            != payload["result_revision_sha256"]
                        ):
                            raise ValueError(
                                "applicability snapshot does not bind the adopted revision"
                            )
                        if plan["registry_sha256"] != template["registry_sha256"]:
                            raise ValueError(
                                "impact plan does not bind the adopted template identity"
                            )
                        if (
                            plan["applicability_rules_sha256"]
                            != template["applicability_rules_sha256"]
                        ):
                            raise ValueError(
                                "impact plan does not bind the adopted rule set"
                            )
                        record = payload["decision_record"]
                        return TemplateAdoptionQueryResult(
                            project_id=query.project_id,
                            study_definition_id=query.study_definition_id,
                            cas_identity=payload["cas_identity"],
                            decision_record_id=record["decision_record_id"],
                            decision_key=record["decision_key"],
                            base_revision=adoption["base_revision"],
                            base_revision_sha256=adoption["base_revision_sha256"],
                            applied_revision=payload["result_revision"],
                            applied_revision_sha256=payload["result_revision_sha256"],
                            facts_before_sha256=adoption["facts_before_sha256"],
                            facts_after_sha256=adoption["facts_after_sha256"],
                            changed_fact_paths=tuple(adoption["changed_fact_paths"]),
                            retired_fact_paths=tuple(adoption["retired_fact_paths"]),
                            template=template,
                            applicability_snapshot=snapshot,
                            impact_plan=plan,
                        )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise _LedgerRebuildError(
                            event_id=event.domain_event_id,
                            detail=f"invalid template adoption payload: {exc}",
                        ) from exc
                return None
        except _EXCEPTION_MAP as exc:
            raise _translate(
                exc,
                project_id=query.project_id,
                object_id=query.study_definition_id,
            ) from exc

    def get_workflow_run_status(
        self, query: GetWorkflowRunStatusQuery
    ) -> WorkflowRunStatusQueryResult:
        """Read the workflow-run status projection."""

        try:
            with self._factory() as uow:
                rm = uow.read_model_repository
                if rm is None:
                    raise _MissingRepositoryError("read_model_repository")
                status = rm.get_workflow_run_status(
                    query.project_id, query.workflow_run_id
                )
                return WorkflowRunStatusQueryResult(
                    project_id=query.project_id,
                    workflow_run_id=query.workflow_run_id,
                    status=status,
                )
        except _EXCEPTION_MAP as exc:
            raise _translate(
                exc,
                project_id=query.project_id,
                object_id=query.workflow_run_id,
            ) from exc

    # ------------------------------------------------------------------
    # Pre-repository-use validation
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_create_genesis(
        command: CreateStudyDefinitionCommand,
    ) -> None:
        """Re-validate the creation genesis discipline before the CAS write.

        This defence-in-depth re-checks the pure command invariants at the
        repository boundary; the construction-time validation already
        guarantees them, but the explicit check makes the pre-repository
        validation audit-visible and guards against future refactors.
        """

        expected_snapshot = study_definition_genesis_snapshot(
            study_definition_id=command.study_definition_id,
            project_id=command.project_id,
            normalized_seed_id=command.normalized_seed_id,
            normalized_seed_sha256=command.normalized_seed_sha256,
            facts=command.initial_facts,
            decided_at=command.decision_record.decided_at,
        )
        if command.decision_record.snapshot_sha256 != expected_snapshot:
            raise RevisionStaleError(
                command.study_definition_id, 0, 0
            )

    @staticmethod
    def _reject_reused_idempotency_key(
        events: Sequence[DomainEvent],
        command: Any,
        cas_id: str,
    ) -> None:
        """One logical operation per idempotency key within this aggregate.

        The key identifies the logical operation even when no outbox side
        effect is attached: a *different* decision (different CAS identity)
        reusing a recorded key is rejected with zero effects, while the key's
        own decision replays exactly.  Runs only on the fresh path, after the
        ledger proved no recorded effect for this CAS identity.
        """

        for event in events:
            payload = event.payload
            if event.event_type not in _DECISION_EVENT_TYPES:
                continue
            recorded_key = payload.get("idempotency_key")
            recorded_cas = payload.get("cas_identity")
            if recorded_key == command.idempotency_key and recorded_cas != cas_id:
                raise IdempotencyConflictError(
                    command.project_id,
                    command.idempotency_key,
                    existing_sha256=str(recorded_cas),
                    incoming_sha256=cas_id,
                )

    @staticmethod
    def _validate_fresh_apply(
        command: ApplyStudyDecisionCommand,
        current: StudyDefinitionV3,
    ) -> None:
        """Validate the command/aggregate relationship for a fresh decision.

        Exact replays are exempt: the ledger proves a prior apply, and the
        incoming decision legitimately carries the ORIGINAL revision and
        snapshot.  Fresh decisions must bind the exact current revision and
        snapshot.
        """

        if command.expected_revision != current.revision:
            raise RevisionStaleError(
                command.study_definition_id,
                command.expected_revision,
                current.revision,
            )
        expected_snapshot = study_revision_hash(current)
        if command.decision_record.snapshot_sha256 != expected_snapshot:
            raise RevisionStaleError(
                command.study_definition_id,
                command.expected_revision,
                current.revision,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require_study_repo(uow: Any) -> Any:
        repo = getattr(uow, "study_definition_repository", None)
        if repo is None:
            raise MissingRepositoryError("study_definition_repository")
        return repo

    def _load_current_template(self) -> CurrentTemplate:
        """Load the current authored template through the injected loader.

        Legacy commands never reach this path, so historical replays never
        depend on template loading.  A loader failure is a configuration
        problem, not a user decision to re-confirm.
        """

        if self._current_template_loader is None:
            raise _MissingRepositoryError("current_template_loader")
        try:
            template = self._current_template_loader()
        except (ValueError, OSError) as exc:
            raise _CurrentTemplateUnavailableError(str(exc)) from exc
        if not isinstance(template, CurrentTemplate):
            raise _CurrentTemplateUnavailableError(
                "current template loader returned an unsupported object"
            )
        return template

    @staticmethod
    def _read_stream(
        uow: Any, project_id: str, stream_id: str
    ) -> Tuple[DomainEvent, ...]:
        ev_repo = getattr(uow, "event_stream_repository", None)
        if ev_repo is None:
            raise MissingRepositoryError("event_stream_repository")
        return ev_repo.read_events(project_id, stream_id)

    def _rebuild_ledger(
        self,
        events: Sequence[DomainEvent],
        *,
        project_id: str,
        study_definition_id: str,
    ) -> DecisionEffectLedger:
        """Rebuild the DecisionEffectLedger from the authoritative event stream.

        Only decision-effect events contribute; their payloads carry the full
        ``DecisionEffect`` so replay classification is deterministic without
        any read-model or side repository (design section 18: the event log
        is the authority).
        """

        ledger = DecisionEffectLedger()
        for event in events:
            if event.event_type not in _DECISION_EVENT_TYPES:
                continue
            payload = event.payload
            if payload.get("kind") != "decision_effect":
                raise _LedgerRebuildError(
                    event_id=event.domain_event_id,
                    detail="decision event payload missing 'kind' field",
                )
            try:
                cas_identity = payload["cas_identity"]
                record = DecisionRecord.model_validate(
                    payload["decision_record"]
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise _LedgerRebuildError(
                    event_id=event.domain_event_id,
                    detail=(
                        "decision event payload missing or invalid "
                        f"decision_record/cas_identity: {exc}"
                    ),
                ) from exc
            expected_id = decision_cas_identity(
                record.decision_record_id,
                record.snapshot_sha256,
                record.expected_state_revision,
            )
            if cas_identity != expected_id:
                raise _LedgerRebuildError(
                    event_id=event.domain_event_id,
                    detail="payload cas_identity does not match the embedded DecisionRecord triple",
                )
            stored_dr_sha = payload.get("decision_record_sha256")
            if stored_dr_sha != record.material_sha256():
                raise _LedgerRebuildError(
                    event_id=event.domain_event_id,
                    detail="payload decision_record_sha256 does not match DecisionRecord material hash",
                )
            if payload.get("operation") == TEMPLATE_FACT_ADOPTION_OPERATION:
                # The recorded intent hash must bind the recorded contents
                # (updates, input binding refs, template echo, retirement),
                # not merely exist — verified on every rebuild.
                try:
                    recomputed = recompute_adoption_intent_sha256(payload)
                except (KeyError, TypeError, ValueError) as exc:
                    raise _LedgerRebuildError(
                        event_id=event.domain_event_id,
                        detail=f"invalid template adoption payload: {exc}",
                    ) from exc
                if payload["fact_updates_sha256"] != recomputed:
                    raise _LedgerRebuildError(
                        event_id=event.domain_event_id,
                        detail="payload fact_updates_sha256 does not match the recorded adoption intent",
                    )
            try:
                effect = DecisionEffect(
                    cas_identity=cas_identity,
                    decision_record=record,
                    decision_record_sha256=stored_dr_sha,
                    fact_updates_sha256=payload["fact_updates_sha256"],
                    result_study_definition_id=payload[
                        "result_study_definition_id"
                    ],
                    result_revision=payload["result_revision"],
                    result_previous_revision_sha256=payload[
                        "result_previous_revision_sha256"
                    ],
                    result_revision_sha256=payload["result_revision_sha256"],
                )
                ledger = ledger.with_effect(effect)
            except (KeyError, TypeError, ValueError) as exc:
                raise _LedgerRebuildError(
                    event_id=event.domain_event_id,
                    detail=f"invalid decision effect payload: {exc}",
                ) from exc
        return ledger


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


# Set of exception types the translate handler understands.
_EXCEPTION_MAP = (
    RevisionStaleError,
    DecisionPayloadConflictError,
    FrozenFactOverwriteError,
    AggregateNotFoundError,
    RevisionConflictError,
    IdempotencyConflictError,
    EventSequenceConflictError,
    MissingRepositoryError,
    MutationAbortedError,
    TemplateAdoptionValidationError,
    _ApplicationServiceError,
)


def _translate(
    exc: BaseException,
    *,
    project_id: str,
    object_id: str,
    idempotency_key: Optional[str] = None,
    decision_record_id: Optional[str] = None,
    expected_revision: Optional[int] = None,
) -> ProtocolWorkflowError:
    """Map a domain/repo error to the finite typed error catalog."""

    ctx: dict[str, Any] = {"project_id": project_id}
    if idempotency_key is not None:
        ctx["idempotency_key"] = idempotency_key
    if decision_record_id is not None:
        ctx["decision_record_id"] = decision_record_id
    if expected_revision is not None:
        ctx["expected_revision"] = expected_revision

    # --- MutationAbortedError — unwrap the original cause ----
    if isinstance(exc, MutationAbortedError):
        if exc.original is not None:
            return _translate(
                exc.original,
                project_id=project_id,
                object_id=object_id,
                idempotency_key=idempotency_key,
                decision_record_id=decision_record_id,
                expected_revision=expected_revision,
            )
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_DECISION_CAS,
            object_id=object_id,
            owner=ProtocolErrorOwner.COORDINATOR_AGENT,
            retryable=True,
            attempt=1,
            audit_detail=str(exc),
            audit_context=ctx,
        )

    # --- Project mismatch — P1_DECISION_CAS / identity-mismatch family ---
    if isinstance(exc, _ProjectMismatchError):
        ctx["expected_project"] = exc.expected_project
        ctx["actual_project"] = exc.actual_project
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_DECISION_CAS,
            object_id=object_id,
            owner=ProtocolErrorOwner.COORDINATOR_AGENT,
            retryable=True,
            attempt=1,
            audit_detail=str(exc),
            audit_context=ctx,
        )

    # --- Ledger corruption requires event recovery, not another decision. ---
    if isinstance(exc, _LedgerRebuildError):
        ctx["event_id"] = exc.event_id
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH,
            object_id=object_id,
            owner=ProtocolErrorOwner.APPLICATION_SERVICE,
            retryable=False,
            attempt=1,
            audit_detail=exc.detail,
            audit_context=ctx,
        )

    # Missing objects and configuration cannot be repaired by reconfirming a decision.
    if isinstance(exc, (MissingRepositoryError, _MissingRepositoryError, AggregateNotFoundError)):
        code = (
            ProtocolErrorCode.P1_OBJECT_NOT_FOUND
            if isinstance(exc, AggregateNotFoundError)
            else ProtocolErrorCode.P1_SERVICE_CONFIGURATION_INCOMPLETE
        )
        return ProtocolWorkflowError(
            code=code,
            object_id=object_id,
            owner=ProtocolErrorOwner.APPLICATION_SERVICE,
            retryable=False,
            attempt=1,
            audit_detail=str(exc),
            audit_context=ctx,
        )

    # The current authored template could not be loaded source-bound.
    if isinstance(exc, _CurrentTemplateUnavailableError):
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_SERVICE_CONFIGURATION_INCOMPLETE,
            object_id=object_id,
            owner=ProtocolErrorOwner.APPLICATION_SERVICE,
            retryable=False,
            attempt=1,
            audit_detail=exc.detail if hasattr(exc, "detail") else str(exc),
            audit_context=ctx,
        )

    # A template-bound adoption contradicting the confirmed template state is
    # a design-consistency problem the user resolves by revising the inputs.
    if isinstance(exc, TemplateAdoptionValidationError):
        ctx["adoption_rejection_kind"] = exc.kind
        if exc.fact_paths:
            ctx["fact_paths"] = list(exc.fact_paths)
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.D1_STUDY_DEFINITION_INCOMPLETE,
            object_id=object_id,
            owner=ProtocolErrorOwner.DESIGN_AGENT,
            retryable=True,
            attempt=1,
            audit_detail=exc.detail,
            audit_context=ctx,
        )

    # --- Stale revision / snapshot / CAS conflict — P1_REVISION_STALE ---
    if isinstance(exc, (RevisionStaleError, RevisionConflictError)):
        if isinstance(exc, RevisionStaleError):
            ctx["actual_revision"] = exc.actual_revision
        if isinstance(exc, RevisionConflictError):
            ctx["actual_revision"] = exc.actual_revision
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_REVISION_STALE,
            object_id=object_id,
            owner=ProtocolErrorOwner.APPLICATION_SERVICE,
            retryable=True,
            attempt=1,
            audit_detail=str(exc),
            audit_context=ctx,
        )

    # --- Event chain corruption — P1_CHECKPOINT_EVENT_MISMATCH ---
    if isinstance(exc, EventSequenceConflictError):
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH,
            object_id=object_id,
            owner=ProtocolErrorOwner.APPLICATION_SERVICE,
            retryable=False,
            attempt=1,
            audit_detail=str(exc),
            audit_context=ctx,
        )

    # --- CAS decision / identity / payload family — P1_DECISION_CAS ---
    if isinstance(
        exc,
        (
            DecisionPayloadConflictError,
            FrozenFactOverwriteError,
            IdempotencyConflictError,
        ),
    ):
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_DECISION_CAS,
            object_id=object_id,
            owner=ProtocolErrorOwner.COORDINATOR_AGENT,
            retryable=True,
            attempt=1,
            audit_detail=str(exc),
            audit_context=ctx,
        )

    # Never swallow unknown errors into a wrong code.
    raise exc


# ---------------------------------------------------------------------------
# Private module-level helpers
# ---------------------------------------------------------------------------


def _first_accept_state(decision: DecisionRecord) -> CanonicalState:
    """Natural PROPOSED → CONFIRMED transition for a create decision."""

    if decision.canonical_state is CanonicalState.CONFIRMED:
        return CanonicalState.CONFIRMED
    return CanonicalState.PROPOSED


def _decision_event_id(stream_id: str, cas_identity: str) -> str:
    """Deterministic domain-event id for a decision mutation event."""

    return f"{stream_id}:decision:{cas_identity}"


def _event_kwargs(
    *,
    stream_id: str,
    event_type: str,
    domain_event_id: str,
    actor_type: Any,
    actor_id: str,
    action: str,
    reason: str,
    payload: dict[str, Any],
    emitted_at: datetime,
) -> dict[str, Any]:
    return {
        "domain_event_id": domain_event_id,
        "stream_id": stream_id,
        "event_type": event_type,
        "payload_schema_version": _EVENT_SCHEMA_VERSION,
        "upcaster_id": _EVENT_UPCASTER_ID,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "reason": reason,
        "payload": payload,
        "emitted_at": emitted_at,
    }


def _effect_payload(
    effect: DecisionEffect,
    *,
    project_id: str,
    study_definition_id: str,
    idempotency_key: str,
    fact_updates: Optional[Mapping[str, Any]],
) -> dict[str, Any]:
    """Serialise the full DecisionEffect into a JSON-safe event payload."""

    return {
        "kind": "decision_effect",
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "idempotency_key": idempotency_key,
        "cas_identity": effect.cas_identity,
        "decision_record": effect.decision_record.model_dump(mode="json"),
        "decision_record_sha256": effect.decision_record_sha256,
        "fact_updates": None if fact_updates is None else dict(fact_updates),
        "fact_updates_sha256": effect.fact_updates_sha256,
        "result_study_definition_id": effect.result_study_definition_id,
        "result_revision": effect.result_revision,
        "result_previous_revision_sha256": effect.result_previous_revision_sha256,
        "result_revision_sha256": effect.result_revision_sha256,
    }


def _build_side_effect(
    idempotency_key: str,
    side_spec: Any,
    *,
    payload_sha256: str,
) -> Optional[SideEffectRequest]:
    """Build the outbox SideEffectRequest from the command's spec."""

    if side_spec is None:
        return None
    return SideEffectRequest(
        workflow_run_id=side_spec.workflow_run_id,
        side_effect_kind=side_spec.side_effect_kind,
        logical_key=idempotency_key,
        payload_sha256=payload_sha256,
    )
