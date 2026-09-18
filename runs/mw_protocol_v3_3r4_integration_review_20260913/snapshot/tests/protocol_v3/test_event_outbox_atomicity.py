"""Functional integration tests for the Protocol v3 event-sourced unit of work:
canonical mutation / event / outbox atomic transaction, inbox-first
acknowledgement and cross-component crash recovery.

These tests verify the design-section-18 atomicity and recovery contract that
the :class:`EventSourcedUnitOfWork` coordinator enforces:

* A canonical CAS save, domain-event append and outbox enqueue commit or roll
  back together through the existing reference UoW.
* A dispatched side effect whose result reaches the inbox before outbox
  acknowledgement is consumed exactly once after restart.
* The same logical key + result is idempotent; a different result under the
  same key fails closed.

The tests use the in-memory UoW and repositories (the reference adapter) to
prove the coordinator composes the port contract correctly.  They do not test
the in-memory adapter itself (that is Task 1.3's responsibility) — they test
that the coordinator drives the adapter atomically.

Because the in-memory UoW closes after commit, multi-transaction scenarios
share the underlying repositories via :class:`_SharedState`, which produces a
fresh open UoW backed by the same store on each call.  This mirrors how a real
application service opens one UoW per business transaction against persistent
storage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DomainEvent,
    SideEffectKind,
    StudyDefinitionV3,
)
from app.protocol_workflow.events.models import (
    EventEnvelopeBuilder,
    EventTypeRegistry,
    SuccessfulReplayResult,
    UpcasterRegistry,
)
from app.protocol_workflow.events.outbox import (
    DispatchOutcomeKind,
    DispatchResult,
    OutboxDispatcher,
)
from app.protocol_workflow.events.inbox import (
    ConsumeOutcomeKind,
)
from app.protocol_workflow.events.store import (
    EventReplayEngine,
)
from app.protocol_workflow.events.unit_of_work import (
    EventSourcedUnitOfWork,
    MissingRepositoryError,
    MutationAbortedError,
    SideEffectRequest,
)
from app.protocol_workflow.ports.repositories import (
    IdempotencyConflictError,
    InboxStatus,
    OutboxStatus,
    RepositoryStateTransitionError,
    RevisionConflictError,
)
from app.protocol_workflow.storage.memory import (
    InMemoryArtifactStore,
    InMemoryCurrentAggregateRepository,
    InMemoryEventStreamRepository,
    InMemoryExecutionReservationRepository,
    InMemoryInboxRepository,
    InMemoryOutboxRepository,
    InMemoryReadModelRepository,
    InMemoryRevisionCasRepository,
    InMemoryUnitOfWork,
    _AggregateIndex,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 3, 0, 0, 0, tzinfo=timezone.utc)

_CURRENT_SCHEMA = "mw_protocol_v3_event_v1"
_PROJECT = "proj:test:1"
_STREAM = "stream:sd:test:1"
_SD_ID = "sd:test:1"
_RUN_ID = "wr:test:1"


def _fixed_clock(times: Optional[List[datetime]] = None):
    """Return a clock that yields successive values, cycling through *times*."""

    pool = times or [_T0, _T1, _T2]
    state = {"i": 0}

    def now() -> datetime:
        t = pool[state["i"] % len(pool)]
        state["i"] += 1
        return t

    return now


def _builder() -> EventEnvelopeBuilder:
    return EventEnvelopeBuilder()


def _coordinator(times: Optional[List[datetime]] = None) -> EventSourcedUnitOfWork:
    return EventSourcedUnitOfWork(builder=_builder(), clock=_fixed_clock(times))


def _build_study(
    *,
    revision: int = 1,
    previous_revision_sha256: Optional[str] = None,
) -> StudyDefinitionV3:
    """Build a minimal valid StudyDefinitionV3 for the given revision."""

    return StudyDefinitionV3(
        study_definition_id=_SD_ID,
        project_id=_PROJECT,
        revision=revision,
        previous_revision_sha256=previous_revision_sha256,
        normalized_seed_id="seed:test:1",
        normalized_seed_sha256="a" * 64,
        facts={"therapeutic_area": "oncology"},
        decision_record_ids=(),
        updated_at=_T0,
        canonical_state=CanonicalState.PROPOSED,
    )


def _event_params(
    *,
    event_id: str = "evt:1",
    event_type: str = "study_definition.revised",
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Keyword arguments for EventEnvelopeBuilder.build/continue_chain."""

    return {
        "domain_event_id": event_id,
        "stream_id": _STREAM,
        "event_type": event_type,
        "payload_schema_version": _CURRENT_SCHEMA,
        "upcaster_id": "noop:v1",
        "actor_type": ActorType.AI,
        "actor_id": "agent:corpus:1",
        "action": "revise",
        "reason": "test-revision",
        "payload": payload or {"revision": 1},
        "emitted_at": _T0,
    }


def _side_effect(
    *,
    logical_key: str = "se:fetch:1",
    payload_sha256: str = "f" * 64,
) -> SideEffectRequest:
    return SideEffectRequest(
        workflow_run_id=_RUN_ID,
        side_effect_kind=SideEffectKind.EXTERNAL_FETCH,
        logical_key=logical_key,
        payload_sha256=payload_sha256,
    )


class _SharedState:
    """Shared repository state across multiple single-use UoW instances.

    The in-memory UoW closes after commit.  To test multi-transaction scenarios
    (e.g. mutation 1 then mutation 2, or crash recovery across coordinator/UoW
    lifetimes), the underlying repositories are shared so committed state
    persists into the next UoW.  This proves repository-driven discovery at the
    port level; the in-memory reference adapter does not claim real
    cross-process durability.
    """

    def __init__(self) -> None:
        sd_index = _AggregateIndex()
        sdr_index = _AggregateIndex()
        self.sd_repo = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=sd_index
        )
        self.sd_cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=sd_index
        )
        self.sdr_repo = InMemoryCurrentAggregateRepository(
            identity_field="semantic_document_revision_id", index=sdr_index
        )
        self.sdr_cas = InMemoryRevisionCasRepository(
            identity_field="semantic_document_revision_id", index=sdr_index
        )
        self.ev_repo = InMemoryEventStreamRepository()
        self.ob_repo = InMemoryOutboxRepository()
        self.ib_repo = InMemoryInboxRepository()
        self.rv_repo = InMemoryExecutionReservationRepository()
        self.rm_repo = InMemoryReadModelRepository()
        self.artifacts = InMemoryArtifactStore()

    def new_uow(self) -> InMemoryUnitOfWork:
        """Return a fresh open UoW backed by the shared repositories."""

        return InMemoryUnitOfWork(
            study_definition_repository=self.sd_repo,
            study_definition_cas_repository=self.sd_cas,
            semantic_document_repository=self.sdr_repo,
            semantic_document_cas_repository=self.sdr_cas,
            event_stream_repository=self.ev_repo,
            outbox_repository=self.ob_repo,
            inbox_repository=self.ib_repo,
            reservation_repository=self.rv_repo,
            read_model_repository=self.rm_repo,
            artifact_store=self.artifacts,
        )


# ---------------------------------------------------------------------------
# Side-effect / semantic handlers
# ---------------------------------------------------------------------------


class _CountingHandler:
    """Side-effect handler that counts invocations and returns a fixed result."""

    def __init__(self, result_sha256: str = "r" * 64) -> None:
        self.result_sha256 = result_sha256
        self.calls = 0

    def __call__(self, message: Any) -> DispatchResult:
        self.calls += 1
        return DispatchResult(result_sha256=self.result_sha256)


class _FailOnceHandler:
    """Handler that fails on the first call then succeeds."""

    def __init__(self, result_sha256: str = "r" * 64) -> None:
        self.result_sha256 = result_sha256
        self.calls = 0

    def __call__(self, message: Any) -> DispatchResult:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("simulated dispatch failure")
        return DispatchResult(result_sha256=self.result_sha256)


class _NullSemanticHandler:
    """Semantic handler that counts invocations."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, result: Any) -> Any:
        self.calls += 1
        return None


class _RacingConflictInbox(InMemoryInboxRepository):
    """Hide one existing result to reproduce a get-then-record race."""

    hide_next_get: bool = True

    def get_result(self, project_id: str, logical_key: str):
        if self.hide_next_get:
            self.hide_next_get = False
            return None
        return super().get_result(project_id, logical_key)


# ---------------------------------------------------------------------------
# Atomic canonical mutation — commit
# ---------------------------------------------------------------------------


class TestAtomicMutationCommit:
    """CAS save, event append and outbox enqueue commit together."""

    def test_atomic_mutation_commits_all_three_operations(self) -> None:
        """A successful mutation persists the aggregate, appends the event,
        and enqueues the outbox message — all visible after commit."""

        state = _SharedState()
        coord = _coordinator()
        study = _build_study()

        with state.new_uow() as uow:
            result = coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=study,
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        # --- Aggregate persisted via CAS ---
        assert result.saved_aggregate.revision == 1
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        assert current is not None
        assert current.revision == 1

        # --- Event appended to stream ---
        events = state.ev_repo.read_events(_PROJECT, _STREAM)
        assert len(events) == 1
        assert events[0].event_type == "study_definition.revised"

        # --- Outbox message enqueued ---
        msg = state.ob_repo.find_by_logical_key(_PROJECT, "se:fetch:1")
        assert msg is not None
        assert msg.status == OutboxStatus.PENDING
        assert result.enqueued_outbox is not None
        assert result.enqueued_outbox.outbox_message_id == msg.outbox_message_id

    def test_atomic_mutation_without_side_effect(self) -> None:
        """A mutation with no side effect commits CAS + event but no outbox."""

        state = _SharedState()
        coord = _coordinator()
        study = _build_study()

        with state.new_uow() as uow:
            result = coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=study,
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=None,
                expected_revision=0,
            )

        assert result.enqueued_outbox is None
        assert state.ob_repo.find_by_logical_key(_PROJECT, "se:fetch:1") is None

    def test_build_and_apply_builds_event_from_stream_head(self) -> None:
        """build_and_apply derives sequence/previous_event_sha256 from the
        stream head and commits the full mutation across two transactions."""

        state = _SharedState()
        coord = _coordinator()

        # First mutation: revision 1.
        study1 = _build_study()
        with state.new_uow() as uow:
            coord.build_and_apply(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=study1,
                cas_repository_handle_name="study_definition_cas_repository",
                expected_revision=0,
                event=_event_params(event_id="evt:1", payload={"revision": 1}),
            )

        # Second mutation: revision 2, event continues the chain.
        sha1 = study1.material_sha256()
        study2 = StudyDefinitionV3(
            study_definition_id=_SD_ID,
            project_id=_PROJECT,
            revision=2,
            previous_revision_sha256=sha1,
            normalized_seed_id="seed:test:1",
            normalized_seed_sha256="a" * 64,
            facts={"therapeutic_area": "oncology"},
            decision_record_ids=(),
            updated_at=_T0,
            canonical_state=CanonicalState.PROPOSED,
        )
        with state.new_uow() as uow:
            coord.build_and_apply(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=study2,
                cas_repository_handle_name="study_definition_cas_repository",
                expected_revision=1,
                event=_event_params(event_id="evt:2", payload={"revision": 2}),
            )

        events = state.ev_repo.read_events(_PROJECT, _STREAM)
        assert len(events) == 2
        assert events[0].sequence == 1
        assert events[1].sequence == 2
        assert events[1].previous_event_sha256 == events[0].event_sha256

        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        assert current is not None
        assert current.revision == 2


# ---------------------------------------------------------------------------
# Atomic canonical mutation — rollback
# ---------------------------------------------------------------------------


class TestAtomicMutationRollback:
    """Failure at any step rolls back all prior writes in the transaction."""

    def test_rollback_on_cas_conflict_leaves_nothing_durable(self) -> None:
        """A CAS conflict at the save step rolls back the transaction; no
        event is appended and no outbox message is enqueued."""

        state = _SharedState()
        coord = _coordinator()

        # Pre-populate the aggregate at revision 1.
        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                expected_revision=0,
            )

        original_event_count = len(state.ev_repo.read_events(_PROJECT, _STREAM))
        head = state.ev_repo.get_stream_head(_PROJECT, _STREAM)
        assert head is not None

        # Attempt a second mutation with expected_revision=0 (conflict).
        # The event is a valid chain continuation; the failure is at CAS save.
        second_event = _builder().continue_chain(
            head_sha256=head.last_event_sha256,
            head_sequence=head.last_sequence,
            **_event_params(event_id="evt:2", payload={"revision": 2}),
        )
        with pytest.raises(MutationAbortedError) as exc_info:
            with state.new_uow() as uow:
                coord.apply_mutation(
                    uow,
                    project_id=_PROJECT,
                    stream_id=_STREAM,
                    aggregate=_build_study(),
                    cas_repository_handle_name="study_definition_cas_repository",
                    events=(second_event,),
                    side_effect=_side_effect(),
                    expected_revision=0,
                )

        assert exc_info.value.step == "cas_save"
        assert isinstance(exc_info.value.original, RevisionConflictError)

        # Rollback restored state: still only 1 event, no extra outbox message.
        assert len(state.ev_repo.read_events(_PROJECT, _STREAM)) == original_event_count
        assert state.ob_repo.find_by_logical_key(_PROJECT, "se:fetch:1") is None

    def test_rollback_on_event_append_failure(self) -> None:
        """A chain-break failure at the event-append step rolls back the CAS
        save — the aggregate must not be advanced."""

        state = _SharedState()
        coord = _coordinator()
        study = _build_study()

        # The event declares sequence=2 with a predecessor, which breaks the
        # append-only chain on an empty stream.
        bad_event = _builder().build(
            sequence=2,
            previous_event_sha256="0" * 64,
            **_event_params(),
        )
        with pytest.raises(MutationAbortedError) as exc_info:
            with state.new_uow() as uow:
                coord.apply_mutation(
                    uow,
                    project_id=_PROJECT,
                    stream_id=_STREAM,
                    aggregate=study,
                    cas_repository_handle_name="study_definition_cas_repository",
                    events=(bad_event,),
                    expected_revision=0,
                )

        assert exc_info.value.step == "event_append"

        # CAS save was rolled back: no aggregate exists.
        assert state.sd_repo.get_current(_PROJECT, _SD_ID) is None

    def test_rollback_on_outbox_enqueue_failure(self) -> None:
        """An idempotency conflict at the outbox-enqueue step rolls back the
        CAS save and event append."""

        state = _SharedState()
        coord = _coordinator()

        # First mutation: enqueue a side effect with payload hash "f"*64.
        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(payload_sha256="f" * 64),
                expected_revision=0,
            )

        original_event_count = len(state.ev_repo.read_events(_PROJECT, _STREAM))

        # Second mutation: enqueue the same logical key with a different
        # payload hash — idempotency conflict at the outbox step.
        sha1 = _build_study().material_sha256()
        study2 = StudyDefinitionV3(
            study_definition_id=_SD_ID,
            project_id=_PROJECT,
            revision=2,
            previous_revision_sha256=sha1,
            normalized_seed_id="seed:test:1",
            normalized_seed_sha256="a" * 64,
            facts={"therapeutic_area": "oncology"},
            decision_record_ids=(),
            updated_at=_T0,
            canonical_state=CanonicalState.PROPOSED,
        )
        head = state.ev_repo.get_stream_head(_PROJECT, _STREAM)
        assert head is not None
        with pytest.raises(MutationAbortedError) as exc_info:
            with state.new_uow() as uow:
                coord.apply_mutation(
                    uow,
                    project_id=_PROJECT,
                    stream_id=_STREAM,
                    aggregate=study2,
                    cas_repository_handle_name="study_definition_cas_repository",
                    events=(
                        _builder().continue_chain(
                            head_sha256=head.last_event_sha256,
                            head_sequence=head.last_sequence,
                            **_event_params(event_id="evt:2", payload={"revision": 2}),
                        ),
                    ),
                    side_effect=_side_effect(payload_sha256="e" * 64),
                    expected_revision=1,
                )

        assert exc_info.value.step == "outbox_enqueue"
        assert isinstance(exc_info.value.original, IdempotencyConflictError)

        # Rollback: aggregate still at revision 1, event count unchanged.
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        assert current is not None
        assert current.revision == 1
        assert len(state.ev_repo.read_events(_PROJECT, _STREAM)) == original_event_count

    def test_inactive_uow_fails_before_any_write(self) -> None:
        state = _SharedState()
        coord = _coordinator()
        uow = state.new_uow()

        with pytest.raises(MutationAbortedError) as exc_info:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                expected_revision=0,
            )

        assert exc_info.value.step == "unit_of_work_inactive"
        assert state.sd_repo.get_current(_PROJECT, _SD_ID) is None
        assert state.ev_repo.read_events(_PROJECT, _STREAM) == ()

    def test_empty_event_mutation_fails_before_cas_save(self) -> None:
        state = _SharedState()
        coord = _coordinator()

        with pytest.raises(MutationAbortedError) as exc_info:
            with state.new_uow() as uow:
                coord.apply_mutation(
                    uow,
                    project_id=_PROJECT,
                    stream_id=_STREAM,
                    aggregate=_build_study(),
                    cas_repository_handle_name="study_definition_cas_repository",
                    events=(),
                    expected_revision=0,
                )

        assert exc_info.value.step == "event_required"
        assert state.sd_repo.get_current(_PROJECT, _SD_ID) is None
        assert state.ev_repo.read_events(_PROJECT, _STREAM) == ()


# ---------------------------------------------------------------------------
# Missing repository handle
# ---------------------------------------------------------------------------


class TestMissingRepositoryHandle:
    """The coordinator fails fast when the UoW scope lacks a required handle."""

    def test_missing_cas_repository_raises(self) -> None:
        state = _SharedState()
        coord = _coordinator()

        with pytest.raises(MissingRepositoryError) as exc_info:
            with state.new_uow() as uow:
                coord.apply_mutation(
                    uow,
                    project_id=_PROJECT,
                    stream_id=_STREAM,
                    aggregate=_build_study(),
                    cas_repository_handle_name="nonexistent_repository",
                    events=(_builder().build(sequence=1, **_event_params()),),
                    expected_revision=0,
                )

        assert exc_info.value.handle_name == "nonexistent_repository"

    def test_missing_outbox_repository_raises_when_side_effect_given(
        self,
    ) -> None:
        state = _SharedState()
        state.ob_repo = InMemoryOutboxRepository()  # not wired
        coord = _coordinator()

        uow = InMemoryUnitOfWork(
            study_definition_repository=state.sd_repo,
            study_definition_cas_repository=state.sd_cas,
            event_stream_repository=state.ev_repo,
            outbox_repository=None,  # deliberately absent
            inbox_repository=state.ib_repo,
        )
        with pytest.raises(MissingRepositoryError) as exc_info:
            with uow:
                coord.apply_mutation(
                    uow,
                    project_id=_PROJECT,
                    stream_id=_STREAM,
                    aggregate=_build_study(),
                    cas_repository_handle_name="study_definition_cas_repository",
                    events=(_builder().build(sequence=1, **_event_params()),),
                    side_effect=_side_effect(),
                    expected_revision=0,
                )

        assert exc_info.value.handle_name == "outbox_repository"


# ---------------------------------------------------------------------------
# Inbox-first acknowledgement
# ---------------------------------------------------------------------------


class TestInboxFirstAcknowledgement:
    """The outbox is acknowledged only after the result is durable in the
    inbox — the exactly-once-semantic-effect guarantee."""

    def test_dispatch_pending_acknowledges_inbox_first(self) -> None:
        """A freshly-enqueued PENDING message is claimed, dispatched, the
        result is written to the inbox, and then the outbox is completed."""

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        outcomes = coord.dispatch_pending_side_effects(
            state.new_uow(), project_id=_PROJECT, handler=handler
        )

        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.kind == DispatchOutcomeKind.DISPATCHED
        assert outcome.message.status == OutboxStatus.COMPLETED
        assert outcome.inbox_result_sha256 == "r" * 64
        assert handler.calls == 1

        result = state.ib_repo.get_result(_PROJECT, "se:fetch:1")
        assert result is not None
        assert result.result_sha256 == "r" * 64
        assert result.status == InboxStatus.RECEIVED

    def test_public_ack_rejects_pending_before_handler_or_inbox_write(self) -> None:
        """A stale caller cannot dispatch a message that the repository has
        not atomically claimed into DISPATCHED."""

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)
        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )
        pending = state.ob_repo.find_by_logical_key(_PROJECT, "se:fetch:1")
        assert pending is not None
        assert pending.status is OutboxStatus.PENDING

        dispatcher = OutboxDispatcher(
            outbox=state.ob_repo,
            inbox=state.ib_repo,
            handler=handler,
            clock=_fixed_clock(),
        )
        with pytest.raises(RepositoryStateTransitionError):
            dispatcher.acknowledge_one(pending, _PROJECT)

        assert handler.calls == 0
        assert state.ib_repo.get_result(_PROJECT, "se:fetch:1") is None
        stored = state.ob_repo.get(_PROJECT, pending.outbox_message_id)
        assert stored is not None
        assert stored.status is OutboxStatus.PENDING

    def test_dispatch_pending_without_handler_returns_deferred(self) -> None:
        """Claiming without a handler exposes an explicit non-terminal
        outcome and leaves the message recoverable."""

        state = _SharedState()
        coord = _coordinator()
        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        with state.new_uow():
            outcomes = OutboxDispatcher(
                outbox=state.ob_repo,
                inbox=state.ib_repo,
                handler=None,
                clock=_fixed_clock(),
            ).dispatch_pending(_PROJECT, limit=1)

        assert len(outcomes) == 1
        assert outcomes[0].kind is DispatchOutcomeKind.DEFERRED_NO_HANDLER
        assert outcomes[0].message.status is OutboxStatus.DISPATCHED
        stored = state.ob_repo.get(_PROJECT, outcomes[0].message.outbox_message_id)
        assert stored is not None
        assert stored.status is OutboxStatus.DISPATCHED
        assert state.ib_repo.get_result(_PROJECT, "se:fetch:1") is None

    def test_outbox_failed_when_handler_raises(self) -> None:
        """If the side-effect handler raises, the outbox message is marked
        FAILED — it is never silently completed without an inbox result."""

        state = _SharedState()
        coord = _coordinator()
        handler = _FailOnceHandler(result_sha256="r" * 64)

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        outcomes = coord.dispatch_pending_side_effects(
            state.new_uow(), project_id=_PROJECT, handler=handler
        )

        assert len(outcomes) == 1
        outcome = outcomes[0]
        assert outcome.kind == DispatchOutcomeKind.FAILED
        assert outcome.message.status == OutboxStatus.FAILED
        assert handler.calls == 1

        # No inbox result was written.
        assert state.ib_repo.get_result(_PROJECT, "se:fetch:1") is None

    def test_re_dispatch_after_completion_is_noop(self) -> None:
        """After a message is COMPLETED, re-dispatching is a no-op: claim
        returns nothing and the handler is not re-invoked."""

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        coord.dispatch_pending_side_effects(
            state.new_uow(), project_id=_PROJECT, handler=handler
        )
        assert handler.calls == 1

        outcomes = coord.dispatch_pending_side_effects(
            state.new_uow(), project_id=_PROJECT, handler=handler
        )
        assert len(outcomes) == 0
        assert handler.calls == 1


# ---------------------------------------------------------------------------
# Cross-component crash recovery
# ---------------------------------------------------------------------------


class TestCrossComponentCrashRecovery:
    """Crash scenarios spanning the CAS, event, outbox and inbox components.

    The core design-section-18 recovery invariant: a crash at any point yields
    a deterministic resume.  These tests simulate crashes by splitting the
    dispatch/ack cycle across two UoW scopes (two "process lifetimes").
    """

    def test_crash_after_inbox_write_before_ack_resumes_from_inbox(self) -> None:
        """A crash after the side effect runs and the inbox write commits, but
        before the outbox ack, is resolved by completing the outbox WITHOUT
        re-dispatching (exactly-once semantic effect).

        Simulation: manually claim the message (PENDING → DISPATCHED), write
        the inbox result (as if the handler ran and committed), but leave the
        outbox DISPATCHED (crash before ack).  Recovery completes the outbox
        via the inbox without re-dispatching.
        """

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        # Simulate crash: claim → inbox write, but no outbox ack.
        with state.new_uow() as uow:
            claimed = state.ob_repo.claim_pending(_PROJECT, limit=1, claimed_at=_T0)
            assert len(claimed) == 1
            state.ib_repo.record_result(
                _PROJECT, "se:fetch:1", "r" * 64, received_at=_T1
            )
        # Outbox message is still DISPATCHED.

        # Recovery: inbox already has the result → complete without re-dispatch.
        result = coord.recover_dispatched(
            state.new_uow(),
            project_id=_PROJECT,
            messages=claimed,
            handler=handler,
        )

        assert len(result.recovered_completed) == 1
        assert result.re_dispatched == ()
        assert handler.calls == 0  # NOT re-dispatched

        msg = state.ob_repo.get(_PROJECT, claimed[0].outbox_message_id)
        assert msg is not None
        assert msg.status == OutboxStatus.COMPLETED

    def test_recovery_without_handler_remains_dispatched_not_failed(self) -> None:
        """No configured handler is a deferred recovery state, not a
        permanent failure classification."""

        state = _SharedState()
        coord = _coordinator()
        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )
        with state.new_uow():
            claimed = state.ob_repo.claim_pending(_PROJECT, limit=1, claimed_at=_T0)
            assert len(claimed) == 1

        result = OutboxDispatcher(
            outbox=state.ob_repo,
            inbox=state.ib_repo,
            handler=None,
            clock=_fixed_clock(),
        ).recover_dispatched(_PROJECT, messages=claimed, handler=None)

        assert result.recovered_completed == ()
        assert result.re_dispatched == ()
        assert result.failed == ()
        assert len(result.still_dispatched) == 1
        assert result.still_dispatched[0].status is OutboxStatus.DISPATCHED
        stored = state.ob_repo.get(_PROJECT, claimed[0].outbox_message_id)
        assert stored is not None
        assert stored.status is OutboxStatus.DISPATCHED

    def test_crash_during_dispatch_re_dispatches_on_recovery(self) -> None:
        """A crash during dispatch (handler ran but inbox write did not commit)
        is resolved by re-dispatching.  The handler must be idempotent; the
        inbox deduplicates the result."""

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        # Simulate crash: claim (PENDING → DISPATCHED), no inbox write.
        with state.new_uow() as uow:
            claimed = state.ob_repo.claim_pending(_PROJECT, limit=1, claimed_at=_T0)
            assert len(claimed) == 1

        # Recovery: no inbox result → re-dispatch.
        result = coord.recover_dispatched(
            state.new_uow(),
            project_id=_PROJECT,
            messages=claimed,
            handler=handler,
        )

        assert len(result.re_dispatched) == 1
        assert handler.calls == 1

        rec = state.ib_repo.get_result(_PROJECT, "se:fetch:1")
        assert rec is not None
        assert rec.result_sha256 == "r" * 64

        msg = state.ob_repo.get(_PROJECT, claimed[0].outbox_message_id)
        assert msg is not None
        assert msg.status == OutboxStatus.COMPLETED

    def test_restart_recovery_discovers_dispatched_from_repository(self) -> None:
        """A restarted process that retained no in-memory ``OutboxMessage``
        objects discovers ``DISPATCHED`` messages through the repository and
        completes them inbox-first without re-dispatching.

        This is the design-section-18 deterministic restart path: the caller
        supplies only the project scope and a handler — never a pre-crash
        message object.  The repository's ``list_dispatched`` is the authority
        for what work is outstanding.
        """

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)
        semantic = _NullSemanticHandler()

        # --- Phase 1: commit mutation + enqueue side effect ---
        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        # --- Phase 2: claim (PENDING → DISPATCHED), write inbox, then
        # "crash" before outbox ack.  We deliberately do NOT retain the
        # claimed message object past this block. ---
        with state.new_uow() as uow:
            claimed = state.ob_repo.claim_pending(_PROJECT, limit=1, claimed_at=_T0)
            assert len(claimed) == 1
            state.ib_repo.record_result(
                _PROJECT, "se:fetch:1", "r" * 64, received_at=_T1
            )
        # ``claimed`` goes out of scope here — the restarted process has no
        # in-memory message object.  (We rebind to None to make the intent
        # explicit and prevent accidental reuse.)
        claimed = None  # type: ignore[assignment]

        # --- Phase 3: restart.  Open a fresh UoW over the same shared
        # repository state and recover by project/limit only. ---
        restart_uow = state.new_uow()
        result = coord.recover_dispatched_from_repository(
            restart_uow,
            project_id=_PROJECT,
            limit=10,
            handler=handler,
        )

        # Inbox-first: the result was already in the inbox, so the outbox is
        # completed WITHOUT re-dispatching (exactly-once semantic effect).
        assert len(result.recovered_completed) == 1
        assert result.re_dispatched == ()
        assert result.failed == ()
        assert handler.calls == 0  # NOT re-dispatched

        # --- Phase 4: consume the inbox result exactly once ---
        consume_outcome = coord.consume_inbox_result(
            state.new_uow(),
            project_id=_PROJECT,
            logical_key="se:fetch:1",
            handler=semantic,
        )
        assert consume_outcome.kind == ConsumeOutcomeKind.CONSUMED
        assert semantic.calls == 1

        # --- Phase 5: re-consume is a no-op (exactly-once) ---
        re_consume = coord.consume_inbox_result(
            state.new_uow(),
            project_id=_PROJECT,
            logical_key="se:fetch:1",
            handler=semantic,
        )
        assert re_consume.kind == ConsumeOutcomeKind.SKIPPED_ALREADY_CONSUMED
        assert semantic.calls == 1

        # --- Phase 6: the outbox message is COMPLETED in the repository ---
        msg = state.ob_repo.find_by_logical_key(_PROJECT, "se:fetch:1")
        assert msg is not None
        assert msg.status == OutboxStatus.COMPLETED

    def test_restart_recovery_rediscovers_when_inbox_empty(self) -> None:
        """When the inbox has no result (crash during dispatch, before inbox
        write), repository-discovered recovery re-dispatches exactly once."""

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        # Claim (PENDING → DISPATCHED), no inbox write, then discard.
        with state.new_uow() as uow:
            state.ob_repo.claim_pending(_PROJECT, limit=1, claimed_at=_T0)

        # Restart: discover via repository, re-dispatch (inbox empty).
        result = coord.recover_dispatched_from_repository(
            state.new_uow(),
            project_id=_PROJECT,
            limit=10,
            handler=handler,
        )

        assert len(result.re_dispatched) == 1
        assert result.recovered_completed == ()
        assert handler.calls == 1

        rec = state.ib_repo.get_result(_PROJECT, "se:fetch:1")
        assert rec is not None
        assert rec.result_sha256 == "r" * 64

        msg = state.ob_repo.find_by_logical_key(_PROJECT, "se:fetch:1")
        assert msg is not None
        assert msg.status == OutboxStatus.COMPLETED


# ---------------------------------------------------------------------------
# Idempotency conflict — fail closed
# ---------------------------------------------------------------------------


class TestIdempotencyConflictFailClosed:
    """A different result hash under the same logical key fails closed."""

    def test_conflicting_result_hash_is_rejected_by_inbox(self) -> None:
        """The inbox port itself rejects a different result hash under the
        same logical key — this is the contract the dispatcher relies on."""

        state = _SharedState()
        state.ib_repo.record_result(_PROJECT, "se:fetch:1", "x" * 64, received_at=_T1)
        with pytest.raises(IdempotencyConflictError):
            state.ib_repo.record_result(
                _PROJECT, "se:fetch:1", "r" * 64, received_at=_T2
            )

    def test_dispatcher_fail_closed_on_inbox_conflict(self) -> None:
        """When the dispatcher's record_result hits an idempotency conflict,
        the outbox message is marked FAILED.

        We simulate the race by pre-writing the inbox with a different hash
        and then calling acknowledge_side_effect (the single-message crash
        recovery path) with a handler that returns a conflicting hash.
        """

        state = _SharedState()
        state.ib_repo = _RacingConflictInbox()
        coord = _coordinator()

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )

        # Claim the message (PENDING → DISPATCHED) and pre-write the inbox
        # with a DIFFERENT hash, simulating a prior dispatch that committed
        # a different result.
        with state.new_uow() as uow:
            claimed = state.ob_repo.claim_pending(_PROJECT, limit=1, claimed_at=_T0)
            assert len(claimed) == 1
            state.ib_repo.record_result(
                _PROJECT, "se:fetch:1", "x" * 64, received_at=_T1
            )
        # Outbox message is DISPATCHED; inbox has hash "x"*64.

        # The racing inbox hides the first read, then exposes the existing
        # different hash during record_result so the actual conflict branch is
        # exercised.
        handler = _CountingHandler(result_sha256="r" * 64)
        outcome = coord.acknowledge_side_effect(
            state.new_uow(),
            project_id=_PROJECT,
            outbox_message=claimed[0],
            handler=handler,
        )
        assert outcome.kind == DispatchOutcomeKind.IDEMPOTENCY_CONFLICT
        assert handler.calls == 1
        stored = state.ob_repo.get(_PROJECT, claimed[0].outbox_message_id)
        assert stored is not None
        assert stored.status is OutboxStatus.FAILED


# ---------------------------------------------------------------------------
# Inbox consumer — exactly-once semantic effect
# ---------------------------------------------------------------------------


class TestInboxConsumerIdempotencyContract:
    """The durable marker deduplicates completed results; crash-window handler
    execution remains at-least-once and therefore requires logical-key
    idempotency."""

    def test_consume_applies_effect_once(self) -> None:
        state = _SharedState()
        coord = _coordinator()
        semantic = _NullSemanticHandler()

        state.ib_repo.record_result(_PROJECT, "se:fetch:1", "r" * 64, received_at=_T0)

        outcome = coord.consume_inbox_result(
            state.new_uow(),
            project_id=_PROJECT,
            logical_key="se:fetch:1",
            handler=semantic,
        )
        assert outcome.kind == ConsumeOutcomeKind.CONSUMED
        assert semantic.calls == 1
        assert outcome.result is not None
        assert outcome.result.status == InboxStatus.CONSUMED

    def test_re_consume_skips_effect(self) -> None:
        state = _SharedState()
        coord = _coordinator()
        semantic = _NullSemanticHandler()

        state.ib_repo.record_result(_PROJECT, "se:fetch:1", "r" * 64, received_at=_T0)

        coord.consume_inbox_result(
            state.new_uow(),
            project_id=_PROJECT,
            logical_key="se:fetch:1",
            handler=semantic,
        )
        outcome = coord.consume_inbox_result(
            state.new_uow(),
            project_id=_PROJECT,
            logical_key="se:fetch:1",
            handler=semantic,
        )
        assert outcome.kind == ConsumeOutcomeKind.SKIPPED_ALREADY_CONSUMED
        assert semantic.calls == 1

    def test_consume_not_found(self) -> None:
        state = _SharedState()
        coord = _coordinator()
        semantic = _NullSemanticHandler()

        outcome = coord.consume_inbox_result(
            state.new_uow(),
            project_id=_PROJECT,
            logical_key="missing:key",
            handler=semantic,
        )
        assert outcome.kind == ConsumeOutcomeKind.NOT_FOUND
        assert outcome.result is None
        assert semantic.calls == 0

    def test_crash_after_effect_before_marker_requires_idempotent_handler(self) -> None:
        state = _SharedState()
        coord = _coordinator()
        state.ib_repo.record_result(_PROJECT, "se:fetch:1", "r" * 64, received_at=_T0)
        effects = {"count": 0}

        def crash_after_effect(_result: Any) -> None:
            effects["count"] += 1
            raise RuntimeError("crash before consumed marker")

        with pytest.raises(RuntimeError):
            coord.consume_inbox_result(
                state.new_uow(),
                project_id=_PROJECT,
                logical_key="se:fetch:1",
                handler=crash_after_effect,
            )
        with pytest.raises(RuntimeError):
            coord.consume_inbox_result(
                state.new_uow(),
                project_id=_PROJECT,
                logical_key="se:fetch:1",
                handler=crash_after_effect,
            )

        assert effects["count"] == 2
        assert (
            state.ib_repo.get_result(_PROJECT, "se:fetch:1").status
            is InboxStatus.RECEIVED
        )


# ---------------------------------------------------------------------------
# Full lifecycle integration
# ---------------------------------------------------------------------------


class TestFullLifecycleIntegration:
    """The full mutate → enqueue → dispatch → acknowledge → consume lifecycle
    in one coherent scenario, plus deterministic replay rebuild."""

    def test_mutate_dispatch_consume_and_replay_lifecycle(self) -> None:
        """End-to-end: atomic mutation enqueues a side effect, the dispatcher
        acknowledges it inbox-first, the consumer applies the semantic effect
        exactly once, and replaying the event stream rebuilds the same
        canonical hash."""

        state = _SharedState()
        coord = _coordinator()
        handler = _CountingHandler(result_sha256="r" * 64)
        semantic = _NullSemanticHandler()

        # --- Phase 1: atomic mutation ---
        with state.new_uow() as uow:
            mutation_result = coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(_builder().build(sequence=1, **_event_params()),),
                side_effect=_side_effect(),
                expected_revision=0,
            )
        assert mutation_result.enqueued_outbox is not None

        # --- Phase 2: dispatch + acknowledge inbox-first ---
        dispatch_outcomes = coord.dispatch_pending_side_effects(
            state.new_uow(), project_id=_PROJECT, handler=handler
        )
        assert len(dispatch_outcomes) == 1
        assert dispatch_outcomes[0].kind == DispatchOutcomeKind.DISPATCHED

        # --- Phase 3: consume the inbox result (semantic effect) ---
        consume_outcome = coord.consume_inbox_result(
            state.new_uow(),
            project_id=_PROJECT,
            logical_key="se:fetch:1",
            handler=semantic,
        )
        assert consume_outcome.kind == ConsumeOutcomeKind.CONSUMED
        assert semantic.calls == 1

        # --- Phase 4: deterministic replay rebuilds canonical state ---
        registry = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        registry.register_noop(_CURRENT_SCHEMA)

        class _EventHashReducer:
            """Reducer that returns the event's hash for replay verification."""

            def initial_state(self) -> Any:
                return None

            def apply(
                self,
                current: Any,
                migrated_payload: Mapping[str, Any],
                event: DomainEvent,
            ) -> Any:
                return event

            def canonical_revision_hash(self, state: Any) -> str:
                assert isinstance(state, DomainEvent)
                return state.event_sha256

        engine = EventReplayEngine(
            upcasters=registry,
            event_types=EventTypeRegistry(["study_definition.revised"]),
            reducer=_EventHashReducer(),
        )
        events = state.ev_repo.read_events(_PROJECT, _STREAM)
        replay = engine.replay_stream(events)
        assert not replay.is_quarantined
        success: SuccessfulReplayResult = replay.success
        assert success.events_replayed == 1
        assert success.canonical_revision_sha256 == events[0].event_sha256

    def test_two_mutations_form_valid_chain_and_independent_outbox(self) -> None:
        """Two successive atomic mutations produce a valid event chain and
        independent outbox messages."""

        state = _SharedState()
        coord = _coordinator([_T0, _T1, _T2, _T0, _T1, _T2])

        # Mutation 1.
        study1 = _build_study()
        with state.new_uow() as uow:
            coord.build_and_apply(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=study1,
                cas_repository_handle_name="study_definition_cas_repository",
                expected_revision=0,
                event=_event_params(event_id="evt:1", payload={"revision": 1}),
                side_effect=_side_effect(logical_key="se:1"),
            )

        # Mutation 2.
        sha1 = study1.material_sha256()
        study2 = StudyDefinitionV3(
            study_definition_id=_SD_ID,
            project_id=_PROJECT,
            revision=2,
            previous_revision_sha256=sha1,
            normalized_seed_id="seed:test:1",
            normalized_seed_sha256="a" * 64,
            facts={"therapeutic_area": "oncology"},
            decision_record_ids=(),
            updated_at=_T0,
            canonical_state=CanonicalState.PROPOSED,
        )
        with state.new_uow() as uow:
            coord.build_and_apply(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=study2,
                cas_repository_handle_name="study_definition_cas_repository",
                expected_revision=1,
                event=_event_params(event_id="evt:2", payload={"revision": 2}),
                side_effect=_side_effect(logical_key="se:2"),
            )

        events = state.ev_repo.read_events(_PROJECT, _STREAM)
        assert len(events) == 2
        assert events[1].previous_event_sha256 == events[0].event_sha256

        assert state.ob_repo.find_by_logical_key(_PROJECT, "se:1") is not None
        assert state.ob_repo.find_by_logical_key(_PROJECT, "se:2") is not None

        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        assert current is not None
        assert current.revision == 2

    def test_checkpoint_reconciliation_after_atomic_mutation(self) -> None:
        """After an atomic mutation commits an event, a checkpoint claiming
        completion backed by that event reconciles successfully; a checkpoint
        claiming a missing event quarantines."""

        from app.protocol_workflow.events.store import CheckpointClaim

        state = _SharedState()
        coord = _coordinator()

        with state.new_uow() as uow:
            coord.apply_mutation(
                uow,
                project_id=_PROJECT,
                stream_id=_STREAM,
                aggregate=_build_study(),
                cas_repository_handle_name="study_definition_cas_repository",
                events=(
                    _builder().build(
                        sequence=1,
                        **_event_params(payload={"node_id": "node:revise"}),
                    ),
                ),
                side_effect=None,
                expected_revision=0,
            )

        events = state.ev_repo.read_events(_PROJECT, _STREAM)
        registry = UpcasterRegistry(current_schema_version=_CURRENT_SCHEMA)
        registry.register_noop(_CURRENT_SCHEMA)

        class _PassReducer:
            def initial_state(self) -> Any:
                return None

            def apply(
                self,
                current: Any,
                migrated_payload: Mapping[str, Any],
                event: DomainEvent,
            ) -> Any:
                return event

            def canonical_revision_hash(self, state: Any) -> str:
                assert isinstance(state, DomainEvent)
                return state.event_sha256

        engine = EventReplayEngine(
            upcasters=registry,
            event_types=EventTypeRegistry(["study_definition.revised"]),
            reducer=_PassReducer(),
        )

        # Checkpoint backed by the committed event → success.
        claim_ok = CheckpointClaim(
            node_id="node:revise",
            expected_event_type="study_definition.revised",
            expected_event_sha256=events[0].event_sha256,
            expected_stream_id=_STREAM,
        )
        outcome_ok = engine.reconcile_checkpoint(claim_ok, events)
        assert not outcome_ok.is_quarantined

        # Checkpoint claiming a missing event type → quarantine.
        claim_bad = CheckpointClaim(
            node_id="node:freeze",
            expected_event_type="study_definition.frozen",
            expected_event_sha256="f" * 64,
            expected_stream_id=_STREAM,
        )
        outcome_bad = engine.reconcile_checkpoint(claim_bad, events)
        assert outcome_bad.is_quarantined
