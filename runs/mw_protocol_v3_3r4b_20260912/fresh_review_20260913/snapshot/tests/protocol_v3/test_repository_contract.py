"""Functional contract tests for the Protocol v3 repository ports and the
in-memory implementation.

These tests prove the functional storage contracts required by Task 1.3 of the
approved Protocol v3 multi-agent rearchitecture plan:

* **get-current** — the current revision of a versioned aggregate is retrievable
  and cheap revision probes are correct.
* **CAS revision conflict** — ``save_with_expected_revision`` rejects lost
  updates and creation races; the precondition is exact.
* **append-only event order** — the event stream enforces strictly ascending
  ``sequence`` with a matching ``previous_event_sha256`` chain; duplicate events
  and sequence gaps are rejected; existing events are never mutated.
* **outbox/inbox/reservation idempotency** — replaying the same logical key +
  same content hash returns the existing record; a different hash under the same
  logical key raises ``IdempotencyConflictError``.
* **unit-of-work commit/rollback** — rollback discards uncommitted mutations;
  commit preserves them; post-closure access is closed.
* **project separation** — identities are isolated by ``project_id``.

They also prove the application-service ownership boundary *structurally* by
verifying that the public ``NodeExecutionContract`` contains no repository or
storage handle field.

These are functional contract tests, not security tests: no path, permission,
symlink, TOCTOU or adversarial-input behaviour is exercised (per the task risk
boundaries).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DomainEvent,
    ExecutionReservation,
    ExecutionTerminalState,
    NodeExecutionContract,
    ReservationStatus,
    SemanticBlock,
    SemanticBlockKind,
    SemanticDocumentRevision,
    SideEffectKind,
    StudyDefinitionV3,
)
from app.protocol_workflow.ports.repositories import (
    AggregateNotFoundError,
    ChapterCoverageRecord,
    CurrentAggregateRepository,
    DecisionGraphRecord,
    EventSequenceConflictError,
    EventStreamRepository,
    ExecutionReservationRepository,
    IdempotencyConflictError,
    InboxRepository,
    InboxStatus,
    OutboxRepository,
    OutboxStatus,
    ReadModelRepository,
    RepositoryStateTransitionError,
    RevisionConflictError,
    RevisionCasRepository,
    UnknownOutcomeConflictError,
    WorkflowRunStatusRecord,
)
from app.protocol_workflow.ports.unit_of_work import (
    UnitOfWork,
    UnitOfWorkClosedError,
)
from app.protocol_workflow.storage.memory import (
    InMemoryCurrentAggregateRepository,
    InMemoryEventStreamRepository,
    InMemoryExecutionReservationRepository,
    InMemoryInboxRepository,
    InMemoryOutboxRepository,
    InMemoryReadModelRepository,
    InMemoryRevisionCasRepository,
    _AggregateIndex,
    build_in_memory_unit_of_work,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 3, tzinfo=timezone.utc)

_PROJ_A = "proj:alpha:001"
_PROJ_B = "proj:beta:002"


def _sha(n: int = 0) -> str:
    """Return a valid 64-hex SHA-256 string with a deterministic suffix."""
    return f"{n:064x}"


def _study(
    *,
    study_id: str = "sd:test:1",
    project_id: str = _PROJ_A,
    revision: int = 1,
    previous: Optional[str] = None,
) -> StudyDefinitionV3:
    """Build a minimal valid ``StudyDefinitionV3`` for the given revision."""
    return StudyDefinitionV3(
        study_definition_id=study_id,
        project_id=project_id,
        revision=revision,
        previous_revision_sha256=previous,
        normalized_seed_id="seed:test:1",
        normalized_seed_sha256=_sha(1),
        facts={"indication": "breast cancer"},
        updated_at=_T0,
    )


def _doc_block(
    *,
    block_id: str = "sb:test:1",
) -> SemanticBlock:
    return SemanticBlock(
        semantic_block_id=block_id,
        semantic_node_id="sn:test:1",
        chapter_contract_id="cc:test:1",
        substantive_content_contract_id="scc:test:1",
        block_kind=SemanticBlockKind.NARRATIVE,
        content="Draft narrative content.",
        fact_paths=("facts.indication",),
        claim_evidence_link_ids=("cel:test:1",),
        medical_admission_unit_ids=("mau:test:1",),
        content_sha256=_sha(2),
    )


def _doc(
    *,
    doc_id: str = "sdr:test:1",
    project_id: str = _PROJ_A,
    revision: int = 1,
    previous: Optional[str] = None,
) -> SemanticDocumentRevision:
    return SemanticDocumentRevision(
        semantic_document_revision_id=doc_id,
        project_id=project_id,
        revision=revision,
        previous_revision_sha256=previous,
        study_definition_id="sd:test:1",
        study_definition_sha256=_sha(1),
        applicability_snapshot_id="as:test:1",
        applicability_snapshot_sha256=_sha(3),
        semantic_blocks=(_doc_block(),),
        chapter_contract_hashes=(_sha(4),),
        updated_at=_T0,
    )


def _event(
    *,
    event_id: str,
    stream_id: str = "stream:test:1",
    sequence: int,
    previous: Optional[str],
    event_sha: str,
    project_id: str = _PROJ_A,
) -> DomainEvent:
    return DomainEvent(
        domain_event_id=event_id,
        stream_id=stream_id,
        sequence=sequence,
        event_type="study_definition.revised",
        payload_schema_version="mw_protocol_v3_event_v1",
        upcaster_id="noop:v1",
        actor_type=ActorType.AI,
        actor_id="agent:corpus:1",
        action="revise",
        reason="functional-test",
        payload={"revision": sequence},
        payload_sha256=_sha(sequence + 10),
        previous_event_sha256=previous,
        event_sha256=event_sha,
        emitted_at=_T0,
    )


def _reservation(
    *,
    reservation_id: str = "rsv:test:1",
    logical_call_id: str = "call:test:1",
    idempotency_key: str = "idem-key-1",
    input_sha: str = _sha(100),
    status: ReservationStatus = ReservationStatus.RESERVED,
    terminal_state: Optional[ExecutionTerminalState] = None,
    output_sha: Optional[str] = None,
    error_code: Optional[str] = None,
    provider_session_id: Optional[str] = None,
    attempt: int = 1,
    transport_attempts: int = 0,
) -> ExecutionReservation:
    return ExecutionReservation(
        execution_reservation_id=reservation_id,
        node_execution_contract_id="nec:test:1",
        logical_call_id=logical_call_id,
        idempotency_key=idempotency_key,
        input_sha256=input_sha,
        attempt=attempt,
        transport_attempts=transport_attempts,
        provider_session_id=provider_session_id,
        status=status,
        terminal_state=terminal_state,
        output_sha256=output_sha,
        error_code=error_code,
        reserved_at=_T0,
        updated_at=_T0,
    )


# ---------------------------------------------------------------------------
# Port structural conformance
# ---------------------------------------------------------------------------


class TestPortConformance:
    """The in-memory implementations satisfy their ``runtime_checkable`` ports."""

    def test_repositories_satisfy_their_runtime_checkable_ports(self) -> None:
        index = _AggregateIndex()
        current = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=index
        )
        cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=index
        )
        events = InMemoryEventStreamRepository()
        outbox = InMemoryOutboxRepository()
        inbox = InMemoryInboxRepository()
        reservations = InMemoryExecutionReservationRepository()
        read_models = InMemoryReadModelRepository()

        assert isinstance(current, CurrentAggregateRepository)
        assert isinstance(cas, RevisionCasRepository)
        assert isinstance(events, EventStreamRepository)
        assert isinstance(outbox, OutboxRepository)
        assert isinstance(inbox, InboxRepository)
        assert isinstance(reservations, ExecutionReservationRepository)
        assert isinstance(read_models, ReadModelRepository)

    def test_unit_of_work_satisfies_the_runtime_checkable_port(self) -> None:
        uow = build_in_memory_unit_of_work()
        assert isinstance(uow, UnitOfWork)


# ---------------------------------------------------------------------------
# Port 1 — get-current
# ---------------------------------------------------------------------------


class TestGetCurrent:
    """``CurrentAggregateRepository`` returns the latest non-superseded
    revision and supports cheap revision probes and historical lookups."""

    def _repositories(self):
        index = _AggregateIndex()
        current = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=index
        )
        cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=index
        )
        return current, cas

    def test_get_current_returns_none_when_absent(self) -> None:
        current, _ = self._repositories()
        assert current.get_current(_PROJ_A, "sd:test:1") is None
        assert current.get_current_revision(_PROJ_A, "sd:test:1") is None

    def test_get_current_required_raises_when_absent(self) -> None:
        current, _ = self._repositories()
        with pytest.raises(AggregateNotFoundError):
            current.get_current_required(_PROJ_A, "sd:test:1")

    def test_get_current_returns_latest_revision(self) -> None:
        current, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        r2 = _study(revision=2, previous=r1.material_sha256())
        cas.save_with_expected_revision(_PROJ_A, r2, expected_revision=1)

        assert current.get_current_revision(_PROJ_A, "sd:test:1") == 2
        assert current.get_current(_PROJ_A, "sd:test:1").revision == 2

    def test_get_at_revision_returns_historical(self) -> None:
        current, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        r2 = _study(revision=2, previous=r1.material_sha256())
        cas.save_with_expected_revision(_PROJ_A, r2, expected_revision=1)

        historical = current.get_at_revision(_PROJ_A, "sd:test:1", 1)
        assert historical is not None
        assert historical.revision == 1

    def test_get_at_revision_returns_none_for_missing_revision(self) -> None:
        current, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)

        assert current.get_at_revision(_PROJ_A, "sd:test:1", 99) is None


# ---------------------------------------------------------------------------
# Port 3 — CAS revision conflict
# ---------------------------------------------------------------------------


class TestRevisionCas:
    """``RevisionCasRepository`` enforces optimistic concurrency via
    ``expected_revision``."""

    def _repositories(self):
        index = _AggregateIndex()
        current = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=index
        )
        cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=index
        )
        return current, cas

    def test_create_with_expected_zero_persists_revision_one(self) -> None:
        _, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        saved = cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        assert saved.revision == 1

    def test_create_fails_when_aggregate_already_exists(self) -> None:
        _, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)

        with pytest.raises(RevisionConflictError) as exc_info:
            cas.save_with_expected_revision(
                _PROJ_A, _study(revision=1), expected_revision=0
            )
        assert exc_info.value.expected_revision == 0
        assert exc_info.value.actual_revision == 1

    def test_update_with_correct_expected_succeeds(self) -> None:
        _, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        r2 = _study(revision=2, previous=r1.material_sha256())
        saved = cas.save_with_expected_revision(_PROJ_A, r2, expected_revision=1)
        assert saved.revision == 2

    def test_update_with_stale_expected_raises_conflict(self) -> None:
        _, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        r2 = _study(revision=2, previous=r1.material_sha256())
        cas.save_with_expected_revision(_PROJ_A, r2, expected_revision=1)

        # A concurrent writer that still believes revision 1 is current.
        r2_alt = _study(revision=2, previous=r1.material_sha256(), study_id="sd:test:1")
        with pytest.raises(RevisionConflictError) as exc_info:
            cas.save_with_expected_revision(_PROJ_A, r2_alt, expected_revision=1)
        assert exc_info.value.expected_revision == 1
        assert exc_info.value.actual_revision == 2

    def test_update_with_nonexistent_expected_raises_conflict(self) -> None:
        _, cas = self._repositories()
        r2 = _study(revision=2, previous=_sha(50))
        with pytest.raises(RevisionConflictError) as exc_info:
            cas.save_with_expected_revision(_PROJ_A, r2, expected_revision=1)
        assert exc_info.value.actual_revision is None

    def test_revision_must_advance_by_exactly_one(self) -> None:
        _, cas = self._repositories()
        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        # revision jump 1 -> 3 is illegal even with a correct expected.
        r3 = _study(revision=3, previous=r1.material_sha256())
        with pytest.raises(RevisionConflictError):
            cas.save_with_expected_revision(_PROJ_A, r3, expected_revision=1)


# ---------------------------------------------------------------------------
# Port 2 — append-only event stream
# ---------------------------------------------------------------------------


class TestEventStream:
    """``EventStreamRepository`` enforces append-only chain integrity."""

    def test_append_single_event_and_read_back(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(
            event_id="evt:1",
            sequence=1,
            previous=None,
            event_sha=_sha(101),
        )
        appended = repo.append_events(_PROJ_A, "stream:test:1", [e1])
        assert len(appended) == 1

        replayed = repo.read_events(_PROJ_A, "stream:test:1")
        assert replayed == (e1,)

        head = repo.get_stream_head(_PROJ_A, "stream:test:1")
        assert head is not None
        assert head.last_sequence == 1
        assert head.last_event_sha256 == _sha(101)
        assert head.event_count == 1

    def test_append_batch_in_order_succeeds(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        e2 = _event(event_id="evt:2", sequence=2, previous=_sha(1), event_sha=_sha(2))
        e3 = _event(event_id="evt:3", sequence=3, previous=_sha(2), event_sha=_sha(3))
        appended = repo.append_events(_PROJ_A, "stream:test:1", [e1, e2, e3])
        assert len(appended) == 3
        assert repo.get_stream_head(_PROJ_A, "stream:test:1").event_count == 3

    def test_existing_events_are_never_mutated(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        repo.append_events(_PROJ_A, "stream:test:1", [e1])

        e2 = _event(event_id="evt:2", sequence=2, previous=_sha(1), event_sha=_sha(2))
        repo.append_events(_PROJ_A, "stream:test:1", [e2])

        replayed = repo.read_events(_PROJ_A, "stream:test:1")
        assert replayed[0] == e1  # first event unchanged
        assert replayed[1] == e2

    def test_sequence_gap_is_rejected(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        repo.append_events(_PROJ_A, "stream:test:1", [e1])

        e3 = _event(event_id="evt:3", sequence=3, previous=_sha(1), event_sha=_sha(3))
        with pytest.raises(EventSequenceConflictError):
            repo.append_events(_PROJ_A, "stream:test:1", [e3])

    def test_broken_previous_event_chain_is_rejected(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        repo.append_events(_PROJ_A, "stream:test:1", [e1])

        e2 = _event(event_id="evt:2", sequence=2, previous=_sha(999), event_sha=_sha(2))
        with pytest.raises(EventSequenceConflictError):
            repo.append_events(_PROJ_A, "stream:test:1", [e2])

    def test_duplicate_domain_event_id_is_rejected(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        repo.append_events(_PROJ_A, "stream:test:1", [e1])

        e1_dup = _event(
            event_id="evt:1", sequence=2, previous=_sha(1), event_sha=_sha(2)
        )
        with pytest.raises(EventSequenceConflictError):
            repo.append_events(_PROJ_A, "stream:test:1", [e1_dup])

    def test_duplicate_sequence_is_rejected(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        repo.append_events(_PROJ_A, "stream:test:1", [e1])

        e1_seq = _event(event_id="evt:1b", sequence=1, previous=None, event_sha=_sha(2))
        with pytest.raises(EventSequenceConflictError):
            repo.append_events(_PROJ_A, "stream:test:1", [e1_seq])

    def test_event_stream_id_must_match_append_target(self) -> None:
        repo = InMemoryEventStreamRepository()
        wrong_stream = _event(
            event_id="evt:wrong-stream",
            stream_id="stream:other:1",
            sequence=1,
            previous=None,
            event_sha=_sha(1),
        )
        with pytest.raises(EventSequenceConflictError):
            repo.append_events(_PROJ_A, "stream:test:1", [wrong_stream])
        assert repo.read_events(_PROJ_A, "stream:test:1") == ()

    def test_empty_stream_head_is_none(self) -> None:
        repo = InMemoryEventStreamRepository()
        assert repo.get_stream_head(_PROJ_A, "stream:empty:1") is None

    def test_read_events_from_sequence(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        e2 = _event(event_id="evt:2", sequence=2, previous=_sha(1), event_sha=_sha(2))
        e3 = _event(event_id="evt:3", sequence=3, previous=_sha(2), event_sha=_sha(3))
        repo.append_events(_PROJ_A, "stream:test:1", [e1, e2, e3])

        from_seq2 = repo.read_events(_PROJ_A, "stream:test:1", from_sequence=2)
        assert from_seq2 == (e2, e3)


# ---------------------------------------------------------------------------
# Port 4 — transactional outbox idempotency
# ---------------------------------------------------------------------------


class TestOutboxIdempotency:
    """The outbox replays the same logical key + payload idempotently and
    rejects a different payload under the same logical key."""

    def test_enqueue_returns_same_message_on_replay(self) -> None:
        repo = InMemoryOutboxRepository()
        msg1 = repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:protocol:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        msg2 = repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:protocol:1",
            payload_sha256=_sha(1),
            created_at=_T1,
        )
        assert msg1 == msg2
        assert msg1.status is OutboxStatus.PENDING

    def test_enqueue_different_payload_under_same_key_raises(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:protocol:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        with pytest.raises(IdempotencyConflictError) as exc_info:
            repo.enqueue(
                _PROJ_A,
                "wr:test:1",
                SideEffectKind.EXTERNAL_FETCH,
                logical_key="fetch:protocol:1",
                payload_sha256=_sha(2),
                created_at=_T1,
            )
        assert exc_info.value.existing_sha256 == _sha(1)
        assert exc_info.value.incoming_sha256 == _sha(2)

    def test_claim_dispatch_and_complete_lifecycle(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:protocol:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        claimed = repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
        assert len(claimed) == 1
        assert claimed[0].status is OutboxStatus.DISPATCHED
        assert claimed[0].attempt == 1
        assert claimed[0].dispatched_at == _T1

        msg_id = claimed[0].outbox_message_id
        completed = repo.mark_completed(_PROJ_A, msg_id, completed_at=_T2)
        assert completed.status is OutboxStatus.COMPLETED

    def test_pending_cannot_bypass_dispatch_to_terminal_state(self) -> None:
        repo = InMemoryOutboxRepository()
        pending = repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:protocol:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        with pytest.raises(RepositoryStateTransitionError):
            repo.mark_completed(_PROJ_A, pending.outbox_message_id, _T1)
        with pytest.raises(RepositoryStateTransitionError):
            repo.mark_failed(_PROJ_A, pending.outbox_message_id, "boom", _T1)
        assert (
            repo.get(_PROJ_A, pending.outbox_message_id).status is OutboxStatus.PENDING
        )

    def test_claim_does_not_reclaim_dispatched(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.ARTIFACT_CREATE,
            logical_key="create:doc:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
        second = repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T2)
        assert second == ()

    def test_mark_failed_transitions_to_failed(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXPORT,
            logical_key="export:docx:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        claimed = repo.claim_pending(_PROJ_A, limit=1, claimed_at=_T1)
        failed = repo.mark_failed(_PROJ_A, claimed[0].outbox_message_id, "timeout", _T2)
        assert failed.status is OutboxStatus.FAILED
        assert failed.error_detail == "timeout"

    def test_find_by_logical_key(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:protocol:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        found = repo.find_by_logical_key(_PROJ_A, "fetch:protocol:1")
        assert found is not None
        assert found.payload_sha256 == _sha(1)
        assert repo.find_by_logical_key(_PROJ_A, "missing:key") is None


# ---------------------------------------------------------------------------
# Port 4 — recoverable dispatched discovery
# ---------------------------------------------------------------------------


class TestOutboxListDispatched:
    """``list_dispatched`` discovers recoverable ``DISPATCHED`` messages for
    deterministic restart recovery without retained in-memory objects."""

    def test_returns_only_dispatched_messages(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:2",
            payload_sha256=_sha(2),
            created_at=_T1,
        )
        # Only claim the first → second stays PENDING.
        repo.claim_pending(_PROJ_A, limit=1, claimed_at=_T1)
        dispatched = repo.list_dispatched(_PROJ_A, limit=10)
        assert len(dispatched) == 1
        assert dispatched[0].status is OutboxStatus.DISPATCHED
        assert dispatched[0].logical_key == "fetch:1"

    def test_excludes_completed_and_failed(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(_PROJ_A, "wr:1", SideEffectKind.EXPORT, "k:1", _sha(1), _T0)
        repo.enqueue(_PROJ_A, "wr:1", SideEffectKind.EXPORT, "k:2", _sha(2), _T0)
        claimed = repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
        repo.mark_completed(_PROJ_A, claimed[0].outbox_message_id, _T2)
        repo.mark_failed(_PROJ_A, claimed[1].outbox_message_id, "boom", _T2)
        assert repo.list_dispatched(_PROJ_A, limit=10) == ()

    def test_project_isolation(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(_PROJ_A, "wr:1", SideEffectKind.EXPORT, "k:a", _sha(1), _T0)
        repo.enqueue(_PROJ_B, "wr:1", SideEffectKind.EXPORT, "k:b", _sha(2), _T0)
        repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
        repo.claim_pending(_PROJ_B, limit=10, claimed_at=_T1)
        a = repo.list_dispatched(_PROJ_A, limit=10)
        b = repo.list_dispatched(_PROJ_B, limit=10)
        assert len(a) == 1 and a[0].logical_key == "k:a"
        assert len(b) == 1 and b[0].logical_key == "k:b"

    def test_stable_order_by_created_then_id(self) -> None:
        repo = InMemoryOutboxRepository()
        # Enqueue in reverse chronological order to prove sorting.
        repo.enqueue(_PROJ_A, "wr:1", SideEffectKind.EXPORT, "late", _sha(1), _T2)
        repo.enqueue(_PROJ_A, "wr:1", SideEffectKind.EXPORT, "early", _sha(2), _T0)
        repo.enqueue(_PROJ_A, "wr:1", SideEffectKind.EXPORT, "mid", _sha(3), _T1)
        repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
        dispatched = repo.list_dispatched(_PROJ_A, limit=10)
        keys = [m.logical_key for m in dispatched]
        assert keys == ["early", "mid", "late"]

    def test_limit_caps_results(self) -> None:
        repo = InMemoryOutboxRepository()
        for i in range(5):
            repo.enqueue(
                _PROJ_A,
                "wr:1",
                SideEffectKind.EXPORT,
                f"k:{i}",
                _sha(i),
                _T0,
            )
        repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
        assert len(repo.list_dispatched(_PROJ_A, limit=2)) == 2
        assert len(repo.list_dispatched(_PROJ_A, limit=10)) == 5

    def test_is_read_only(self) -> None:
        """``list_dispatched`` does not transition status or increment attempt."""
        repo = InMemoryOutboxRepository()
        repo.enqueue(_PROJ_A, "wr:1", SideEffectKind.EXPORT, "k:1", _sha(1), _T0)
        claimed = repo.claim_pending(_PROJ_A, limit=1, claimed_at=_T1)
        assert claimed[0].attempt == 1
        before = repo.get(_PROJ_A, claimed[0].outbox_message_id)
        repo.list_dispatched(_PROJ_A, limit=10)
        after = repo.get(_PROJ_A, claimed[0].outbox_message_id)
        assert after.status is OutboxStatus.DISPATCHED
        assert after.attempt == before.attempt


# ---------------------------------------------------------------------------
# Port 5 — idempotent inbox
# ---------------------------------------------------------------------------


class TestInboxIdempotency:
    """The inbox replays the same result idempotently and rejects conflicting
    results under the same logical key."""

    def test_record_result_replays_idempotently(self) -> None:
        repo = InMemoryInboxRepository()
        r1 = repo.record_result(_PROJ_A, "fetch:protocol:1", _sha(1), _T0)
        r2 = repo.record_result(_PROJ_A, "fetch:protocol:1", _sha(1), _T1)
        assert r1 == r2
        assert r1.status is InboxStatus.RECEIVED

    def test_record_conflicting_result_raises(self) -> None:
        repo = InMemoryInboxRepository()
        repo.record_result(_PROJ_A, "fetch:protocol:1", _sha(1), _T0)
        with pytest.raises(IdempotencyConflictError):
            repo.record_result(_PROJ_A, "fetch:protocol:1", _sha(2), _T1)

    def test_was_processed_and_get_result(self) -> None:
        repo = InMemoryInboxRepository()
        assert repo.was_processed(_PROJ_A, "fetch:protocol:1") is False
        repo.record_result(_PROJ_A, "fetch:protocol:1", _sha(1), _T0)
        assert repo.was_processed(_PROJ_A, "fetch:protocol:1") is True
        assert repo.get_result(_PROJ_A, "fetch:protocol:1").result_sha256 == _sha(1)

    def test_mark_consumed(self) -> None:
        repo = InMemoryInboxRepository()
        repo.record_result(_PROJ_A, "fetch:protocol:1", _sha(1), _T0)
        consumed = repo.mark_consumed(_PROJ_A, "fetch:protocol:1", _T1)
        assert consumed.status is InboxStatus.CONSUMED
        assert consumed.consumed_at == _T1

        with pytest.raises(RepositoryStateTransitionError):
            repo.mark_consumed(_PROJ_A, "fetch:protocol:1", _T2)


# ---------------------------------------------------------------------------
# Port 6 — execution reservation idempotency
# ---------------------------------------------------------------------------


class TestReservationIdempotency:
    """Reservations are idempotent by ``(logical_call_id, idempotency_key,
    input_sha256)`` and enforce the unknown-outcome gate."""

    def test_reserve_returns_same_record_on_replay(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        r1 = repo.reserve(_PROJ_A, _reservation())
        r2 = repo.reserve(_PROJ_A, _reservation())
        assert r1 == r2

    def test_reserve_conflicting_input_raises(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation(input_sha=_sha(1)))
        with pytest.raises(IdempotencyConflictError):
            repo.reserve(_PROJ_A, _reservation(input_sha=_sha(2)))

    def test_find_by_logical_call(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        found = repo.find_by_logical_call(_PROJ_A, "call:test:1", "idem-key-1")
        assert found is not None
        assert found.execution_reservation_id == "rsv:test:1"
        assert repo.find_by_logical_call(_PROJ_A, "call:missing", "x") is None

    def test_transition_to_completed(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        updated = repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.COMPLETED,
            terminal_state=ExecutionTerminalState.COMPLETED,
            output_sha256=_sha(200),
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        assert updated.status is ReservationStatus.COMPLETED
        assert updated.output_sha256 == _sha(200)

    def test_unknown_outcome_blocks_re_dispatch(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.UNKNOWN_OUTCOME,
            terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
            error_code="err:transport:unknown",
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        # Re-dispatching the same logical call while unknown-outcome must fail.
        with pytest.raises(UnknownOutcomeConflictError):
            repo.reserve(_PROJ_A, _reservation())

    def test_find_unknown_outcome(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.UNKNOWN_OUTCOME,
            terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
            error_code="err:transport:unknown",
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        unknowns = repo.find_unknown_outcome(_PROJ_A)
        assert len(unknowns) == 1
        assert unknowns[0].status is ReservationStatus.UNKNOWN_OUTCOME

    def test_find_unresolved_includes_running_and_unknown_only_for_project(
        self,
    ) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        running = repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        repo.reserve(
            _PROJ_B,
            _reservation(
                reservation_id="rsv:other:1",
                logical_call_id="call:other:1",
            ),
        )
        assert repo.find_unresolved(_PROJ_A) == (running,)
        assert repo.find_unresolved(_PROJ_B)[0].execution_reservation_id == (
            "rsv:other:1"
        )

    def test_closed_state_machine_rejects_illegal_edges(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        with pytest.raises(RepositoryStateTransitionError):
            repo.transition(
                _PROJ_A,
                "rsv:test:1",
                to_status=ReservationStatus.COMPLETED,
                terminal_state=ExecutionTerminalState.COMPLETED,
                output_sha256=_sha(200),
                provider_session_id="sess:1",
                updated_at=_T1,
            )

    def test_transport_attempts_increment_only_when_dispatch_starts(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        running = repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        assert running.transport_attempts == 1
        with pytest.raises(RepositoryStateTransitionError):
            repo.transition(
                _PROJ_A,
                "rsv:test:1",
                to_status=ReservationStatus.COMPLETED,
                terminal_state=ExecutionTerminalState.COMPLETED,
                output_sha256=_sha(200),
                provider_session_id="sess:1",
                transport_attempts=2,
                updated_at=_T2,
            )

    def test_transition_revalidates_terminal_record_before_commit(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        with pytest.raises(ValueError, match="completed reservations require output"):
            repo.transition(
                _PROJ_A,
                "rsv:test:1",
                to_status=ReservationStatus.COMPLETED,
                terminal_state=ExecutionTerminalState.COMPLETED,
                provider_session_id="sess:1",
                transport_attempts=1,
                updated_at=_T2,
            )
        persisted = repo.get(_PROJ_A, "rsv:test:1")
        assert persisted is not None
        assert persisted.status is ReservationStatus.RUNNING

    def test_attempt_lineage_is_append_only_ordered_and_project_isolated(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        first = _reservation()
        second = _reservation(
            reservation_id="rsv:test:2",
            idempotency_key="idem-key-2",
            attempt=2,
        )
        repo.reserve(_PROJ_A, first)
        repo.reserve(_PROJ_A, second)
        assert repo.list_attempts(_PROJ_A, "call:test:1") == (first, second)
        assert repo.list_attempts(_PROJ_B, "call:test:1") == ()
        assert repo.get(_PROJ_A, first.execution_reservation_id) == first

    def test_duplicate_attempt_number_is_rejected(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        with pytest.raises(IdempotencyConflictError):
            repo.reserve(
                _PROJ_A,
                _reservation(
                    reservation_id="rsv:test:other",
                    idempotency_key="idem-key:other",
                    attempt=1,
                ),
            )

    def test_unknown_recovery_requires_same_provider_session(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.UNKNOWN_OUTCOME,
            terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
            error_code="err:transport:unknown",
            provider_session_id="sess:1",
            transport_attempts=1,
            updated_at=_T2,
        )
        with pytest.raises(RepositoryStateTransitionError):
            repo.transition(
                _PROJ_A,
                "rsv:test:1",
                to_status=ReservationStatus.COMPLETED,
                terminal_state=ExecutionTerminalState.COMPLETED,
                output_sha256=_sha(200),
                provider_session_id="sess:other",
                transport_attempts=1,
                updated_at=_T2,
            )

    def test_live_completion_may_adopt_provider_receipt_session(self) -> None:
        """RUNNING carries a coordinator placeholder; its live success receipt
        may replace that value before the outcome becomes recovery-bound."""
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(_PROJ_A, _reservation())
        repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:harness-placeholder",
            transport_attempts=1,
            updated_at=_T1,
        )
        completed = repo.transition(
            _PROJ_A,
            "rsv:test:1",
            to_status=ReservationStatus.COMPLETED,
            terminal_state=ExecutionTerminalState.COMPLETED,
            output_sha256=_sha(200),
            provider_session_id="sess:provider-receipt",
            transport_attempts=1,
            updated_at=_T2,
        )
        assert completed.provider_session_id == "sess:provider-receipt"


# ---------------------------------------------------------------------------
# Port 7 — read models (project separation)
# ---------------------------------------------------------------------------


class TestReadModels:
    """Read-model projections are project-isolated and return empty defaults."""

    def test_chapter_coverage_project_isolation(self) -> None:
        repo = InMemoryReadModelRepository()
        record_a = ChapterCoverageRecord(
            project_id=_PROJ_A,
            semantic_node_id="sn:test:1",
            chapter_contract_sha256=_sha(1),
            substantive_content_contract_sha256=_sha(2),
            semantic_block_sha256=_sha(3),
            is_locked=False,
            has_substantive_content=True,
            evidence_admitted=True,
        )
        repo.replace_chapter_coverage(_PROJ_A, "sdr:test:1", [record_a])

        assert repo.get_chapter_coverage(_PROJ_A, "sdr:test:1") == (record_a,)
        assert repo.get_chapter_coverage(_PROJ_B, "sdr:test:1") == ()

    def test_decision_graph_project_isolation(self) -> None:
        repo = InMemoryReadModelRepository()
        record_a = DecisionGraphRecord(
            project_id=_PROJ_A,
            decision_key="dk:test:1",
            decision_record_id="drec:test:1",
            state_revision=1,
            selected_option_id="opt:test:1",
            canonical_state=CanonicalState.CONFIRMED,
        )
        repo.replace_decision_graph(_PROJ_A, "sd:test:1", [record_a])

        assert repo.get_decision_graph(_PROJ_A, "sd:test:1") == (record_a,)
        assert repo.get_decision_graph(_PROJ_B, "sd:test:1") == ()

    def test_workflow_run_status_project_isolation(self) -> None:
        repo = InMemoryReadModelRepository()
        status_a = WorkflowRunStatusRecord(
            project_id=_PROJ_A,
            workflow_run_id="wr:test:1",
            status="running",
            display_progress=0.5,
            journey_counter=1,
        )
        repo.upsert_workflow_run_status(status_a)

        assert (
            repo.get_workflow_run_status(_PROJ_A, "wr:test:1").display_progress == 0.5
        )
        assert repo.get_workflow_run_status(_PROJ_B, "wr:test:1") is None


# ---------------------------------------------------------------------------
# Project separation across CAS repositories
# ---------------------------------------------------------------------------


class TestProjectSeparation:
    """Aggregates, events and outbox entries are isolated by ``project_id``."""

    def test_cas_aggregates_are_project_isolated(self) -> None:
        index = _AggregateIndex()
        cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=index
        )
        current = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=index
        )

        r1a = _study(study_id="sd:shared:1", project_id=_PROJ_A, revision=1)
        cas.save_with_expected_revision(_PROJ_A, r1a, expected_revision=0)

        # Same aggregate id in a different project is independent.
        r1b = _study(study_id="sd:shared:1", project_id=_PROJ_B, revision=1)
        cas.save_with_expected_revision(_PROJ_B, r1b, expected_revision=0)

        assert current.get_current_revision(_PROJ_A, "sd:shared:1") == 1
        assert current.get_current_revision(_PROJ_B, "sd:shared:1") == 1
        assert current.get_current(_PROJ_A, "sd:shared:1").project_id == _PROJ_A
        assert current.get_current(_PROJ_B, "sd:shared:1").project_id == _PROJ_B

    def test_event_streams_are_project_isolated(self) -> None:
        repo = InMemoryEventStreamRepository()
        e1 = _event(
            event_id="evt:1",
            stream_id="stream:shared:1",
            sequence=1,
            previous=None,
            event_sha=_sha(1),
            project_id=_PROJ_A,
        )
        repo.append_events(_PROJ_A, "stream:shared:1", [e1])

        # The same stream id in a different project is a separate empty stream.
        assert repo.get_stream_head(_PROJ_B, "stream:shared:1") is None
        assert repo.read_events(_PROJ_B, "stream:shared:1") == ()

    def test_outbox_claim_is_project_isolated(self) -> None:
        repo = InMemoryOutboxRepository()
        repo.enqueue(
            _PROJ_A,
            "wr:test:1",
            SideEffectKind.EXTERNAL_FETCH,
            logical_key="fetch:shared:1",
            payload_sha256=_sha(1),
            created_at=_T0,
        )
        # Project B claims nothing even if the logical key matches.
        claimed_b = repo.claim_pending(_PROJ_B, limit=10, claimed_at=_T1)
        assert claimed_b == ()

        claimed_a = repo.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
        assert len(claimed_a) == 1


# ---------------------------------------------------------------------------
# Execution-reservation project isolation
# ---------------------------------------------------------------------------


class TestReservationProjectIsolation:
    """Execution-reservation recovery/query APIs are project-scoped.

    A reservation created and transitioned to ``UNKNOWN_OUTCOME`` in one project
    must not be visible to, retrievable by, or mutable from another project's
    repository calls.  This is ordinary functional project isolation, not a
    security control.
    """

    def test_find_unknown_outcome_returns_only_own_project(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(
            _PROJ_A, _reservation(reservation_id="rsv:a:1", logical_call_id="call:a:1")
        )
        repo.reserve(
            _PROJ_B, _reservation(reservation_id="rsv:b:1", logical_call_id="call:b:1")
        )

        repo.transition(
            _PROJ_A,
            "rsv:a:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:a:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        repo.transition(
            _PROJ_A,
            "rsv:a:1",
            to_status=ReservationStatus.UNKNOWN_OUTCOME,
            terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
            error_code="err:transport:unknown",
            provider_session_id="sess:a:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        repo.transition(
            _PROJ_B,
            "rsv:b:1",
            to_status=ReservationStatus.RUNNING,
            provider_session_id="sess:b:1",
            transport_attempts=1,
            updated_at=_T1,
        )
        repo.transition(
            _PROJ_B,
            "rsv:b:1",
            to_status=ReservationStatus.UNKNOWN_OUTCOME,
            terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
            error_code="err:transport:unknown",
            provider_session_id="sess:b:1",
            transport_attempts=1,
            updated_at=_T1,
        )

        unknowns_a = repo.find_unknown_outcome(_PROJ_A)
        unknowns_b = repo.find_unknown_outcome(_PROJ_B)

        assert {r.execution_reservation_id for r in unknowns_a} == {"rsv:a:1"}
        assert {r.execution_reservation_id for r in unknowns_b} == {"rsv:b:1"}

    def test_wrong_project_get_returns_none(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(
            _PROJ_A, _reservation(reservation_id="rsv:a:1", logical_call_id="call:a:1")
        )

        # Owning project retrieves the reservation.
        assert repo.get(_PROJ_A, "rsv:a:1") is not None
        assert repo.get(_PROJ_A, "rsv:a:1").execution_reservation_id == "rsv:a:1"
        # Wrong project sees nothing.
        assert repo.get(_PROJ_B, "rsv:a:1") is None

    def test_wrong_project_transition_raises_and_leaves_owner_unchanged(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        repo.reserve(
            _PROJ_A, _reservation(reservation_id="rsv:a:1", logical_call_id="call:a:1")
        )

        # Wrong-project transition must raise the repository not-found exception.
        with pytest.raises(AggregateNotFoundError):
            repo.transition(
                _PROJ_B,
                "rsv:a:1",
                to_status=ReservationStatus.COMPLETED,
                terminal_state=ExecutionTerminalState.COMPLETED,
                output_sha256=_sha(200),
                provider_session_id="sess:b:1",
                updated_at=_T1,
            )

        # The owner project's reservation is untouched.
        owner = repo.get(_PROJ_A, "rsv:a:1")
        assert owner is not None
        assert owner.status is ReservationStatus.RESERVED

    def test_same_reservation_id_is_independent_across_projects(self) -> None:
        repo = InMemoryExecutionReservationRepository()
        record_a = _reservation(
            reservation_id="rsv:shared:1",
            logical_call_id="call:a:shared",
        )
        record_b = _reservation(
            reservation_id="rsv:shared:1",
            logical_call_id="call:b:shared",
        )

        repo.reserve(_PROJ_A, record_a)
        repo.reserve(_PROJ_B, record_b)

        assert repo.get(_PROJ_A, "rsv:shared:1") == record_a
        assert repo.get(_PROJ_B, "rsv:shared:1") == record_b
        assert (
            repo.find_by_logical_call(_PROJ_A, "call:a:shared", "idem-key-1")
            == record_a
        )
        assert (
            repo.find_by_logical_call(_PROJ_B, "call:b:shared", "idem-key-1")
            == record_b
        )


# ---------------------------------------------------------------------------
# Unit of work — commit / rollback
# ---------------------------------------------------------------------------


class TestUnitOfWork:
    """The UoW provides explicit commit/rollback semantics and does not expose
    repositories to agent/harness contracts."""

    def test_rollback_discards_uncommitted_mutations(self) -> None:
        uow = build_in_memory_unit_of_work()
        cas = uow.study_definition_cas_repository
        assert cas is not None

        with pytest.raises(RuntimeError, match="boom"):
            with uow:
                r1 = _study(revision=1, previous=None)
                cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
                # Raise inside the with block to trigger rollback.
                raise RuntimeError("boom")

        # After rollback the aggregate must not be visible.
        current = uow.study_definition_repository
        assert current is not None
        assert current.get_current(_PROJ_A, "sd:test:1") is None

    def test_commit_preserves_mutations(self) -> None:
        uow = build_in_memory_unit_of_work()
        cas = uow.study_definition_cas_repository
        assert cas is not None

        with uow:
            r1 = _study(revision=1, previous=None)
            cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        # Exiting cleanly commits.

        current = uow.study_definition_repository
        assert current is not None
        assert current.get_current_revision(_PROJ_A, "sd:test:1") == 1

    def test_explicit_rollback_discards(self) -> None:
        uow = build_in_memory_unit_of_work()
        cas = uow.study_definition_cas_repository
        assert cas is not None
        events = uow.event_stream_repository
        assert events is not None

        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        e1 = _event(event_id="evt:1", sequence=1, previous=None, event_sha=_sha(1))
        events.append_events(_PROJ_A, "stream:test:1", [e1])

        uow.rollback()

        current = uow.study_definition_repository
        assert current is not None
        assert current.get_current(_PROJ_A, "sd:test:1") is None
        assert events.get_stream_head(_PROJ_A, "stream:test:1") is None

    def test_nested_with_commits_only_at_outermost(self) -> None:
        uow = build_in_memory_unit_of_work()
        cas = uow.study_definition_cas_repository
        assert cas is not None

        with uow:
            with uow:
                r1 = _study(revision=1, previous=None)
                cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
            # Inner exit does not commit; mutation is still pending.
        # Outer exit commits.

        current = uow.study_definition_repository
        assert current is not None
        assert current.get_current_revision(_PROJ_A, "sd:test:1") == 1

    def test_rollback_is_idempotent_after_commit(self) -> None:
        uow = build_in_memory_unit_of_work()
        cas = uow.study_definition_cas_repository
        assert cas is not None

        r1 = _study(revision=1, previous=None)
        cas.save_with_expected_revision(_PROJ_A, r1, expected_revision=0)
        uow.commit()
        # Rollback after commit is a no-op; committed data survives.
        uow.rollback()

        current = uow.study_definition_repository
        assert current is not None
        assert current.get_current_revision(_PROJ_A, "sd:test:1") == 1

    def test_commit_closes_every_uow_mutator(self) -> None:
        uow = build_in_memory_unit_of_work()
        cas = uow.study_definition_cas_repository
        events = uow.event_stream_repository
        outbox = uow.outbox_repository
        inbox = uow.inbox_repository
        reservations = uow.reservation_repository
        read_models = uow.read_model_repository
        artifacts = uow.artifact_store
        assert all(
            handle is not None
            for handle in (
                cas,
                events,
                outbox,
                inbox,
                reservations,
                read_models,
                artifacts,
            )
        )

        uow.commit()
        actions = (
            lambda: cas.save_with_expected_revision(
                _PROJ_A, _study(revision=1, previous=None), expected_revision=0
            ),
            lambda: events.append_events(
                _PROJ_A,
                "stream:closed:1",
                [
                    _event(
                        event_id="evt:closed:1",
                        sequence=1,
                        previous=None,
                        event_sha=_sha(1),
                    )
                ],
            ),
            lambda: outbox.enqueue(
                _PROJ_A,
                "wr:closed:1",
                SideEffectKind.EXTERNAL_FETCH,
                "fetch:closed:1",
                _sha(1),
                _T0,
            ),
            lambda: inbox.record_result(_PROJ_A, "fetch:closed:1", _sha(2), _T0),
            lambda: reservations.reserve(
                _PROJ_A,
                _reservation(
                    reservation_id="rsv:closed:1",
                    logical_call_id="call:closed:1",
                ),
            ),
            lambda: read_models.replace_chapter_coverage(_PROJ_A, "sdr:closed:1", ()),
            lambda: artifacts.store(
                "artifact:closed:1",
                b"closed",
                media_type="application/octet-stream",
                created_at=_T0,
            ),
        )
        for action in actions:
            with pytest.raises(UnitOfWorkClosedError):
                action()

    def test_uow_does_not_leak_repositories_onto_node_contract(self) -> None:
        """Application-service boundary: the repository/storage handles are
        dependencies of the UoW, never fields of ``NodeExecutionContract``."""
        contract_fields = set(NodeExecutionContract.model_fields)
        forbidden = {
            "repository",
            "repositories",
            "event_stream_repository",
            "outbox_repository",
            "inbox_repository",
            "reservation_repository",
            "read_model_repository",
            "artifact_store",
            "unit_of_work",
            "uow",
        }
        leaked = contract_fields & forbidden
        assert leaked == set(), (
            f"NodeExecutionContract must not carry repository/storage handles; "
            f"leaked fields: {leaked}"
        )


# ---------------------------------------------------------------------------
# Application-service boundary — structural proof
# ---------------------------------------------------------------------------


class TestApplicationServiceBoundary:
    """``NodeExecutionContract`` is the agent/harness-facing execution contract.

    Per design section 17.2 / 18, repository and artifact-store handles are
    application-service dependencies.  They MUST NOT appear on the contract.
    This test proves that structurally by inspecting every declared field name
    and its annotated type, so a renamed handle cannot sneak in.
    """

    @staticmethod
    def _type_repr(annotation) -> str:
        return str(annotation).lower()

    def test_no_field_name_suggests_a_storage_or_repository_handle(self) -> None:
        forbidden_substrings = (
            "repository",
            "artifact_store",
            "artifactstore",
            "unit_of_work",
            "unitofwork",
            "outbox",
            "inbox",
            "read_model",
            "readmodel",
            "storage",
            "database",
            "transaction",
            "connection",
            "cursor",
        )
        for name in NodeExecutionContract.model_fields:
            lowered = name.lower()
            for substr in forbidden_substrings:
                assert substr not in lowered, (
                    f"NodeExecutionContract field {name!r} matches forbidden "
                    f"substring {substr!r}; repository/storage handles must "
                    f"not appear on the agent/harness contract"
                )

    def test_no_field_annotation_is_a_repository_or_uow_type(self) -> None:
        """No field annotation references any port type."""
        port_type_names = {
            "currentaggregaterepository",
            "revisioncasrepository",
            "eventstreamrepository",
            "outboxrepository",
            "inboxrepository",
            "executionreservationrepository",
            "readmodelrepository",
            "artifactstore",
            "unitofwork",
        }
        for name, field_info in NodeExecutionContract.model_fields.items():
            repr_lower = self._type_repr(field_info.annotation)
            for port_name in port_type_names:
                assert port_name not in repr_lower, (
                    f"NodeExecutionContract field {name!r} annotation "
                    f"{field_info.annotation} references port type {port_name}"
                )
