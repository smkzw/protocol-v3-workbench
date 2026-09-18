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
from app.protocol_workflow.storage.selected import UnitOfWorkFactory

from .commands import (
    ApplyStudyDecisionCommand,
    CreateStudyDefinitionCommand,
    study_definition_genesis_snapshot,
)
from .queries import (
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

    __slots__ = ("_factory", "_clock", "_coordinator", "_reducer")

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        coordinator: Optional[EventSourcedUnitOfWork] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        if not callable(unit_of_work_factory):
            raise ValueError("unit_of_work_factory must be callable")
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
                    # create decision may proceed (ledger-first classification).
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
                if ledger.find(cas_id) is None:
                    # Genuinely fresh decision: validate before CAS write.
                    self._validate_fresh_apply(command, current)

                new_def, effective, _ledger, replayed = self._reducer.replay_or_apply(
                    current,
                    command.decision_record,
                    ledger,
                    fact_updates=command.fact_updates,
                    now=now,
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
        """Read the decision-graph read-model projection (existing contract)."""

        try:
            with self._factory() as uow:
                rm = uow.read_model_repository
                if rm is None:
                    raise _MissingRepositoryError("read_model_repository")
                records = rm.get_decision_graph(
                    query.project_id, query.study_definition_id
                )
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

    # --- Missing repository handle — P1_DECISION_CAS ---
    if isinstance(exc, (MissingRepositoryError, _MissingRepositoryError)):
        return ProtocolWorkflowError(
            code=ProtocolErrorCode.P1_DECISION_CAS,
            object_id=object_id,
            owner=ProtocolErrorOwner.COORDINATOR_AGENT,
            retryable=True,
            attempt=1,
            audit_detail=str(exc),
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
            AggregateNotFoundError,
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
