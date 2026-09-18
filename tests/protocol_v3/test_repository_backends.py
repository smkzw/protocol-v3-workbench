"""Dual-backend ports contract suite — Task 1R.1.

One shared, backend-parametrised contract suite running against BOTH the
in-memory reference implementation and the product SQLite adapter
(``app.protocol_workflow.storage.sqlite``).  The suite compares observable
``ports.repositories`` / ``ports.unit_of_work`` semantics — CAS revision
history, append-only event ordering and hash linkage, transactional-outbox and
inbox idempotency, execution-reservation unknown-outcome discipline, read-model
projection replacement, and unit-of-work commit/rollback/nested/closed
lifecycle — never storage internals.

Scope notes (Task 1R.1 execution context):

* The memory fixture shares one store across sequential UoWs (factory-level
  state sharing is backend-specific and not a port guarantee); only one UoW is
  alive at a time in these tests, on both backends.
* Committed state is always observed through a fresh UoW from the same factory
  (``store.inspect``), so both backends verify through the same port surface.
* Concurrency/Crash/backup behaviour is PoC + Task 1R.3 evidence, not re-proven
  here; this suite pins the functional repository contract on the product
  adapter.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Callable, Optional

import pytest
from pydantic import ValidationError

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DomainEvent,
    ExecutionReservation,
    ExecutionTerminalState,
    ReservationStatus,
    SemanticBlock,
    SemanticBlockKind,
    SemanticDocumentRevision,
    SideEffectKind,
    StudyDefinitionV3,
    WorkflowRunStatus,
)
from app.protocol_workflow.events.models import EventEnvelopeBuilder
from app.protocol_workflow.ports.repositories import (
    AggregateNotFoundError,
    ChapterCoverageRecord,
    DecisionGraphRecord,
    EventSequenceConflictError,
    IdempotencyConflictError,
    InboxStatus,
    OutboxMessage,
    OutboxStatus,
    RepositoryStateTransitionError,
    RevisionConflictError,
    StreamHead,
    UnknownOutcomeConflictError,
    WorkflowRunStatusRecord,
)
from app.protocol_workflow.ports.unit_of_work import (
    UnitOfWork,
    UnitOfWorkClosedError,
)
from app.protocol_workflow.storage.memory import (
    InMemoryUnitOfWork,
    build_in_memory_unit_of_work,
)
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, tzinfo=timezone.utc)
_T2 = datetime(2026, 1, 3, tzinfo=timezone.utc)
_T3 = datetime(2026, 1, 4, tzinfo=timezone.utc)

_PROJ_A = "proj:alpha:001"
_PROJ_B = "proj:beta:002"

_BUILDER = EventEnvelopeBuilder()


def _sha(n: int) -> str:
    return f"{n:064x}"


def _study(
    *,
    study_id: str = "sd:test:1",
    project_id: str = _PROJ_A,
    revision: int = 1,
    previous: Optional[str] = None,
) -> StudyDefinitionV3:
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


def _doc_block(*, block_id: str = "sb:test:1") -> SemanticBlock:
    return SemanticBlock(
        semantic_block_id=block_id,
        semantic_node_id="sn:test:1",
        chapter_contract_id="cc:test:1",
        substantive_content_contract_id="scc:test:1",
        block_kind=SemanticBlockKind.PARAGRAPH,
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


def _built_event(
    *,
    event_id: str,
    stream_id: str,
    sequence: int,
    previous: Optional[str],
    payload: dict,
    project_id: str = _PROJ_A,
) -> DomainEvent:
    """Build a chain-consistent domain event (real canonical hashes)."""
    return _BUILDER.build(
        domain_event_id=event_id,
        stream_id=stream_id,
        sequence=sequence,
        event_type="study_definition.revised",
        payload_schema_version="mw_protocol_v3_event_v1",
        upcaster_id="noop:v1",
        actor_type=ActorType.AI,
        actor_id="agent:corpus:1",
        action="revise",
        reason="contract-test",
        payload=payload,
        emitted_at=_T0,
        previous_event_sha256=previous,
    )


def _raw_event(
    *,
    event_id: str,
    stream_id: str = "stream:test:1",
    sequence: int,
    previous: Optional[str],
    event_sha: str,
    project_id: str = _PROJ_A,
) -> DomainEvent:
    """Directly construct a DomainEvent with arbitrary hash fields (for
    storage-level chain-violation cases the store must reject)."""
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
        reason="contract-test",
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
    project_id: str = _PROJ_A,
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


def _coverage(
    node_id: str,
    *,
    project_id: str = _PROJ_A,
    locked: bool = False,
) -> ChapterCoverageRecord:
    return ChapterCoverageRecord(
        project_id=project_id,
        semantic_node_id=node_id,
        chapter_contract_sha256=_sha(20),
        substantive_content_contract_sha256=_sha(21),
        semantic_block_sha256=_sha(22),
        is_locked=locked,
        has_substantive_content=True,
        evidence_admitted=True,
    )


def _decision(
    key: str,
    *,
    project_id: str = _PROJ_A,
    state: CanonicalState = CanonicalState.CONFIRMED,
    revision: int = 3,
) -> DecisionGraphRecord:
    return DecisionGraphRecord(
        project_id=project_id,
        decision_key=key,
        decision_record_id=f"dr:{key}",
        state_revision=revision,
        selected_option_id=f"opt:{key}",
        canonical_state=state,
    )


@pytest.fixture(params=["memory", "sqlite"], ids=["memory", "sqlite"])
def store(request, tmp_path) -> SimpleNamespace:
    """One shared store per backend, addressed only through UoW factories.

    ``factory()`` opens a fresh UoW over the same store; ``inspect(fn)`` runs
    ``fn(uow)`` inside a fresh UoW and returns the result — the identical
    port-level observation path for both backends.
    """
    if request.param == "memory":
        base = build_in_memory_unit_of_work()
        handles = {
            f.name: getattr(base, f.name)
            for f in dataclasses.fields(InMemoryUnitOfWork)
            if not f.name.startswith("_")
        }

        def factory() -> InMemoryUnitOfWork:
            return InMemoryUnitOfWork(**handles)

    else:
        factory = build_unit_of_work_factory(
            config={"backend": "sqlite", "path": tmp_path / "contract.sqlite"}
        )

    def inspect(fn: Callable[[UnitOfWork], object]) -> object:
        with factory() as uow:
            return fn(uow)

    return SimpleNamespace(name=request.param, factory=factory, inspect=inspect)


# ---------------------------------------------------------------------------
# Aggregate CAS + revision history (both aggregate types)
# ---------------------------------------------------------------------------


class TestAggregateCas:
    def test_create_revision_one_then_read_back(self, store) -> None:
        with store.factory() as uow:
            saved_study = uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(), 0
            )
            saved_doc = uow.semantic_document_cas_repository.save_with_expected_revision(
                _PROJ_A, _doc(), 0
            )
            assert saved_study.revision == 1
            assert saved_doc.revision == 1

        def read(uow: UnitOfWork) -> object:
            return (
                uow.study_definition_repository.get_current(_PROJ_A, "sd:test:1"),
                uow.study_definition_repository.get_current_revision(_PROJ_A, "sd:test:1"),
                uow.study_definition_repository.get_at_revision(_PROJ_A, "sd:test:1", 1),
                uow.semantic_document_repository.get_current(_PROJ_A, "sdr:test:1"),
                uow.semantic_document_repository.get_current_revision(_PROJ_A, "sdr:test:1"),
            )

        (study, study_rev, study_at_1, doc, doc_rev) = store.inspect(read)
        assert study is not None and study.revision == 1
        assert study_rev == 1
        assert study_at_1 is not None and study_at_1.revision == 1
        assert doc is not None and doc.revision == 1
        assert doc_rev == 1

    def test_revision_history_is_retained(self, store) -> None:
        with store.factory() as uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(revision=1), 0
            )
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A,
                _study(revision=2, previous=_sha(1)),
                1,
            )

        def read(uow: UnitOfWork) -> object:
            return (
                uow.study_definition_repository.get_current_revision(_PROJ_A, "sd:test:1"),
                uow.study_definition_repository.get_at_revision(_PROJ_A, "sd:test:1", 1),
                uow.study_definition_repository.get_at_revision(_PROJ_A, "sd:test:1", 2),
            )

        current_rev, rev1, rev2 = store.inspect(read)
        assert current_rev == 2
        assert rev1 is not None and rev1.revision == 1
        assert rev2 is not None and rev2.revision == 2

    def test_cas_preconditions_are_exact(self, store) -> None:
        with store.factory() as uow:
            cas = uow.study_definition_cas_repository
            cas.save_with_expected_revision(_PROJ_A, _study(revision=1), 0)
            with pytest.raises(RevisionConflictError) as exc_a:
                cas.save_with_expected_revision(_PROJ_A, _study(revision=1), 0)
            assert exc_a.value.actual_revision == 1
            with pytest.raises(RevisionConflictError):
                cas.save_with_expected_revision(
                    _PROJ_A, _study(revision=2, previous=_sha(1)), 2
                )
            with pytest.raises(RevisionConflictError):
                cas.save_with_expected_revision(
                    _PROJ_A, _study(revision=5, previous=_sha(1)), 1
                )
            with pytest.raises(RevisionConflictError):
                cas.save_with_expected_revision(
                    _PROJ_B,
                    _study(revision=2, previous=_sha(1), project_id=_PROJ_B),
                    0,
                )
            # exact precondition succeeds
            cas.save_with_expected_revision(_PROJ_A, _study(revision=2, previous=_sha(1)), 1)

    def test_cas_create_race_both_expect_zero(self, store) -> None:
        with store.factory() as uow:
            cas = uow.study_definition_cas_repository
            cas.save_with_expected_revision(_PROJ_A, _study(revision=1), 0)
            with pytest.raises(RevisionConflictError) as exc:
                cas.save_with_expected_revision(
                    _PROJ_A, _study(study_id="sd:test:1", revision=1), 0
                )
            assert exc.value.expected_revision == 0
            assert exc.value.actual_revision == 1

    def test_get_current_required_raises_when_missing(self, store) -> None:
        def read(uow: UnitOfWork) -> object:
            try:
                uow.study_definition_repository.get_current_required(_PROJ_A, "sd:missing")
                return "no-raise"
            except AggregateNotFoundError:
                return "raised"

        assert store.inspect(read) == "raised"

    def test_same_aggregate_id_isolated_across_projects(self, store) -> None:
        with store.factory() as uow:
            sd_cas = uow.study_definition_cas_repository
            sd_cas.save_with_expected_revision(_PROJ_A, _study(study_id="sd:dup"), 0)
            sd_cas.save_with_expected_revision(
                _PROJ_B, _study(study_id="sd:dup", project_id=_PROJ_B), 0
            )
            sd_cas.save_with_expected_revision(
                _PROJ_A,
                _study(study_id="sd:dup", revision=2, previous=_sha(1)),
                1,
            )

        def read(uow: UnitOfWork) -> object:
            repo = uow.study_definition_repository
            return (
                repo.get_current_revision(_PROJ_A, "sd:dup"),
                repo.get_current_revision(_PROJ_B, "sd:dup"),
                repo.get_at_revision(_PROJ_B, "sd:dup", 2),
            )

        rev_a, rev_b, proj_b_rev2 = store.inspect(read)
        assert (rev_a, rev_b) == (2, 1)
        assert proj_b_rev2 is None


# ---------------------------------------------------------------------------
# Append-only event stream
# ---------------------------------------------------------------------------


class TestEventStream:
    def test_append_read_ordering_and_head(self, store) -> None:
        e1 = _built_event(
            event_id="evt:1", stream_id="stream:test:1", sequence=1,
            previous=None, payload={"n": 1},
        )
        e2 = _built_event(
            event_id="evt:2", stream_id="stream:test:1", sequence=2,
            previous=e1.event_sha256, payload={"n": 2},
        )
        e3 = _built_event(
            event_id="evt:3", stream_id="stream:test:1", sequence=3,
            previous=e2.event_sha256, payload={"n": 3},
        )
        with store.factory() as uow:
            appended = uow.event_stream_repository.append_events(
                _PROJ_A, "stream:test:1", (e1, e2, e3)
            )
            assert appended == (e1, e2, e3)

        def read(uow: UnitOfWork) -> object:
            repo = uow.event_stream_repository
            return (
                repo.read_events(_PROJ_A, "stream:test:1"),
                repo.read_events(_PROJ_A, "stream:test:1", from_sequence=2),
                repo.get_stream_head(_PROJ_A, "stream:test:1"),
            )

        events, tail, head = store.inspect(read)
        assert tuple(e.sequence for e in events) == (1, 2, 3)
        assert tuple(e.event_sha256 for e in events) == (
            e1.event_sha256, e2.event_sha256, e3.event_sha256,
        )
        assert tuple(e.previous_event_sha256 for e in tail) == (
            e1.event_sha256, e2.event_sha256,
        )
        assert isinstance(head, StreamHead)
        assert head.last_sequence == 3
        assert head.event_count == 3
        assert head.last_event_sha256 == e3.event_sha256

    def test_empty_stream_head_is_none(self, store) -> None:
        def read(uow: UnitOfWork) -> object:
            return (
                uow.event_stream_repository.get_stream_head(_PROJ_A, "stream:empty"),
                uow.event_stream_repository.read_events(_PROJ_A, "stream:empty"),
            )

        head, events = store.inspect(read)
        assert head is None
        assert events == ()

    @pytest.mark.parametrize(
        "bad_suffix",
        ["gap", "prev_mismatch", "duplicate_event_id", "duplicate_sequence", "wrong_stream"],
    )
    def test_chain_violation_rejects_whole_batch(self, store, bad_suffix) -> None:
        e1 = _built_event(
            event_id="evt:1", stream_id="stream:test:1", sequence=1,
            previous=None, payload={"n": 1},
        )
        with store.factory() as uow:
            uow.event_stream_repository.append_events(_PROJ_A, "stream:test:1", (e1,))

            if bad_suffix == "gap":
                bad = _built_event(
                    event_id="evt:3", stream_id="stream:test:1", sequence=3,
                    previous=e1.event_sha256, payload={"n": 3},
                )
            elif bad_suffix == "prev_mismatch":
                bad = _built_event(
                    event_id="evt:2", stream_id="stream:test:1", sequence=2,
                    previous=_sha(999), payload={"n": 2},
                )
            elif bad_suffix == "duplicate_event_id":
                bad = _built_event(
                    event_id="evt:1", stream_id="stream:test:1", sequence=2,
                    previous=e1.event_sha256, payload={"n": 2},
                )
            elif bad_suffix == "duplicate_sequence":
                dup = _built_event(
                    event_id="evt:2", stream_id="stream:test:1", sequence=2,
                    previous=e1.event_sha256, payload={"n": 2},
                )
                bad = (dup, dup)
            else:
                bad = _raw_event(
                    event_id="evt:9", stream_id="stream:other", sequence=2,
                    previous=e1.event_sha256, event_sha=_sha(9),
                )

            batch = bad if isinstance(bad, tuple) else (bad,)
            with pytest.raises(EventSequenceConflictError):
                uow.event_stream_repository.append_events(_PROJ_A, "stream:test:1", batch)

        def read(uow: UnitOfWork) -> object:
            return uow.event_stream_repository.read_events(_PROJ_A, "stream:test:1")

        events = store.inspect(read)
        assert tuple(e.sequence for e in events) == (1,), (
            f"partial batch leaked for case {bad_suffix}"
        )

    def test_event_batch_failure_inside_uow_does_not_leak_partial_batch(
        self, store
    ) -> None:
        """A caught repository exception must not leave a partially written
        event batch when the caller lets the surrounding transaction commit."""
        good = _built_event(
            event_id="evt:good", stream_id="stream:test:1", sequence=1,
            previous=None, payload={"n": 1},
        )
        broken = _raw_event(
            event_id="evt:broken", stream_id="stream:test:1", sequence=2,
            previous=_sha(404), event_sha=_sha(41),
        )
        with store.factory() as uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(), 0
            )
            try:
                uow.event_stream_repository.append_events(
                    _PROJ_A, "stream:test:1", (good, broken)
                )
            except EventSequenceConflictError:
                pass  # caller catches inside the larger transaction
            uow.outbox_repository.enqueue(
                _PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(30), _T0
            )

        def read(uow: UnitOfWork) -> object:
            return (
                uow.study_definition_repository.get_current_revision(_PROJ_A, "sd:test:1"),
                uow.event_stream_repository.read_events(_PROJ_A, "stream:test:1"),
                uow.outbox_repository.find_by_logical_key(_PROJ_A, "lk:1"),
            )

        study_rev, events, outbox = store.inspect(read)
        assert study_rev == 1
        assert events == (), "partially written event batch leaked past the failure"
        assert outbox is not None

    def test_batch_prefix_rolls_back_to_committed_head_on_later_violation(
        self, store
    ) -> None:
        """When a LATER event of a batch violates the chain, nothing from the
        batch persists: the stream stays exactly at the committed head, and
        the head itself remains intact for continued appends."""
        e1 = _built_event(
            event_id="evt:1", stream_id="stream:test:1", sequence=1,
            previous=None, payload={"n": 1},
        )
        with store.factory() as uow:
            uow.event_stream_repository.append_events(
                _PROJ_A, "stream:test:1", (e1,)
            )
        good = _built_event(
            event_id="evt:2", stream_id="stream:test:1", sequence=2,
            previous=e1.event_sha256, payload={"n": 2},
        )
        gapped = _built_event(
            event_id="evt:3", stream_id="stream:test:1", sequence=4,
            previous=good.event_sha256, payload={"n": 3},
        )
        with store.factory() as uow:
            with pytest.raises(EventSequenceConflictError):
                uow.event_stream_repository.append_events(
                    _PROJ_A, "stream:test:1", (good, gapped)
                )
            # the stream is still usable inside the same transaction
            uow.event_stream_repository.append_events(
                _PROJ_A, "stream:test:1", (good,)
            )

        def read(uow: UnitOfWork) -> object:
            return tuple(
                e.sequence
                for e in uow.event_stream_repository.read_events(
                    _PROJ_A, "stream:test:1"
                )
            )

        assert store.inspect(read) == (1, 2)

    def test_same_stream_and_event_id_isolated_across_projects(self, store) -> None:
        evt_a = _built_event(
            event_id="evt:shared:1", stream_id="stream:shared", sequence=1,
            previous=None, payload={"owner": "A"},
        )
        evt_b = _built_event(
            event_id="evt:shared:1", stream_id="stream:shared", sequence=1,
            previous=None, payload={"owner": "B"},
        )
        with store.factory() as uow:
            repo = uow.event_stream_repository
            repo.append_events(_PROJ_A, "stream:shared", (evt_a,))
            repo.append_events(_PROJ_B, "stream:shared", (evt_b,))

        def read(uow: UnitOfWork) -> object:
            repo = uow.event_stream_repository
            return (
                tuple(e.payload["owner"] for e in repo.read_events(_PROJ_A, "stream:shared")),
                tuple(e.payload["owner"] for e in repo.read_events(_PROJ_B, "stream:shared")),
                repo.get_stream_head(_PROJ_A, "stream:shared").event_count,
                repo.get_stream_head(_PROJ_B, "stream:shared").event_count,
            )

        owners_a, owners_b, count_a, count_b = store.inspect(read)
        assert owners_a == ("A",)
        assert owners_b == ("B",)
        assert (count_a, count_b) == (1, 1)


# ---------------------------------------------------------------------------
# Transactional outbox + idempotent inbox
# ---------------------------------------------------------------------------


class TestOutboxInbox:
    def test_enqueue_idempotent_replay_and_conflict(self, store) -> None:
        with store.factory() as uow:
            first = uow.outbox_repository.enqueue(
                _PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(30), _T0
            )
            replay = uow.outbox_repository.enqueue(
                _PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(30), _T1
            )
            assert replay.outbox_message_id == first.outbox_message_id
            assert replay.status is OutboxStatus.PENDING
            assert replay.attempt == 0
            assert replay.side_effect_kind is SideEffectKind.EXPORT
            with pytest.raises(IdempotencyConflictError) as exc:
                uow.outbox_repository.enqueue(
                    _PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(31), _T2
                )
            assert exc.value.existing_sha256 == _sha(30)
            assert exc.value.incoming_sha256 == _sha(31)
            assert uow.outbox_repository.find_by_logical_key(_PROJ_A, "lk:1") == first

    def test_outbox_claim_and_completion_lifecycle(self, store) -> None:
        with store.factory() as uow:
            outbox = uow.outbox_repository
            m1 = outbox.enqueue(_PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(30), _T0)
            m2 = outbox.enqueue(_PROJ_A, "run:1", SideEffectKind.ARTIFACT_CREATE, "lk:2", _sha(31), _T0)
            claimed = outbox.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
            assert {m.outbox_message_id for m in claimed} == {
                m1.outbox_message_id, m2.outbox_message_id,
            }
            assert all(m.status is OutboxStatus.DISPATCHED for m in claimed)
            assert all(m.attempt == 1 for m in claimed)
            assert all(m.dispatched_at == _T1 for m in claimed)
            assert outbox.claim_pending(_PROJ_A, limit=10, claimed_at=_T2) == ()
            done = outbox.mark_completed(_PROJ_A, m1.outbox_message_id, _T2)
            assert done.status is OutboxStatus.COMPLETED
            assert done.completed_at == _T2
            with pytest.raises(RepositoryStateTransitionError):
                outbox.mark_completed(_PROJ_A, m1.outbox_message_id, _T3)

        def read(uow: UnitOfWork) -> object:
            outbox = uow.outbox_repository
            return (
                outbox.get(_PROJ_A, m1.outbox_message_id).status,
                outbox.get(_PROJ_A, m1.outbox_message_id).attempt,
                outbox.list_dispatched(_PROJ_A, limit=10),
            )

        status, attempt, dispatched = store.inspect(read)
        assert status is OutboxStatus.COMPLETED
        assert attempt == 1
        assert tuple(m.outbox_message_id for m in dispatched) == (m2.outbox_message_id,)

    def test_outbox_mark_failed(self, store) -> None:
        with store.factory() as uow:
            outbox = uow.outbox_repository
            msg = outbox.enqueue(_PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:f", _sha(32), _T0)
            with pytest.raises(RepositoryStateTransitionError):
                outbox.mark_failed(_PROJ_A, msg.outbox_message_id, "too early", _T1)
            outbox.claim_pending(_PROJ_A, limit=5, claimed_at=_T1)
            failed = outbox.mark_failed(_PROJ_A, msg.outbox_message_id, "boom", _T2)
            assert failed.status is OutboxStatus.FAILED
            assert failed.error_detail == "boom"
            assert failed.completed_at == _T2

    def test_outbox_claim_is_project_scoped(self, store) -> None:
        with store.factory() as uow:
            outbox = uow.outbox_repository
            a = outbox.enqueue(_PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:dup", _sha(30), _T0)
            b = outbox.enqueue(_PROJ_B, "run:1", SideEffectKind.EXPORT, "lk:dup", _sha(30), _T0)
            claimed = outbox.claim_pending(_PROJ_A, limit=10, claimed_at=_T1)
            assert [m.outbox_message_id for m in claimed] == [a.outbox_message_id]

        def read(uow: UnitOfWork) -> object:
            outbox = uow.outbox_repository
            return (
                outbox.get(_PROJ_A, a.outbox_message_id).status,
                outbox.get(_PROJ_B, b.outbox_message_id).status,
            )

        status_a, status_b = store.inspect(read)
        assert status_a is OutboxStatus.DISPATCHED
        assert status_b is OutboxStatus.PENDING

    def test_inbox_idempotency_and_transitions(self, store) -> None:
        with store.factory() as uow:
            inbox = uow.inbox_repository
            first = inbox.record_result(_PROJ_A, "lk:1", _sha(50), _T0)
            assert first.status is InboxStatus.RECEIVED
            replay = inbox.record_result(_PROJ_A, "lk:1", _sha(50), _T1)
            assert replay == first
            with pytest.raises(IdempotencyConflictError) as exc:
                inbox.record_result(_PROJ_A, "lk:1", _sha(51), _T2)
            assert exc.value.existing_sha256 == _sha(50)
            assert exc.value.incoming_sha256 == _sha(51)
            assert inbox.was_processed(_PROJ_A, "lk:1") is True
            assert inbox.was_processed(_PROJ_A, "lk:other") is False
            assert inbox.get_result(_PROJ_A, "lk:1") == first
            consumed = inbox.mark_consumed(_PROJ_A, "lk:1", _T2)
            assert consumed.status is InboxStatus.CONSUMED
            assert consumed.consumed_at == _T2
            with pytest.raises(RepositoryStateTransitionError):
                inbox.mark_consumed(_PROJ_A, "lk:1", _T3)
            with pytest.raises(AggregateNotFoundError):
                inbox.mark_consumed(_PROJ_A, "lk:never-recorded", _T3)

    def test_inbox_same_key_isolated_across_projects(self, store) -> None:
        with store.factory() as uow:
            inbox = uow.inbox_repository
            a = inbox.record_result(_PROJ_A, "lk:dup", _sha(50), _T0)
            inbox.mark_consumed(_PROJ_A, "lk:dup", _T1)
            b = inbox.record_result(_PROJ_B, "lk:dup", _sha(50), _T0)

        def read(uow: UnitOfWork) -> object:
            inbox = uow.inbox_repository
            return (
                inbox.get_result(_PROJ_A, "lk:dup").status,
                inbox.get_result(_PROJ_B, "lk:dup").status,
                inbox.was_processed(_PROJ_B, "lk:dup"),
            )

        status_a, status_b, processed_b = store.inspect(read)
        assert status_a is InboxStatus.CONSUMED
        assert status_b is InboxStatus.RECEIVED
        assert processed_b is True
        assert a.project_id == _PROJ_A and b.project_id == _PROJ_B


# ---------------------------------------------------------------------------
# Execution reservations
# ---------------------------------------------------------------------------


class TestReservations:
    def test_reserve_idempotent_and_input_conflict(self, store) -> None:
        with store.factory() as uow:
            repo = uow.reservation_repository
            first = repo.reserve(_PROJ_A, _reservation())
            replay = repo.reserve(_PROJ_A, _reservation())
            assert replay == first
            assert repo.get(_PROJ_A, "rsv:test:1") == first
            assert repo.find_by_logical_call(_PROJ_A, "call:test:1", "idem-key-1") == first
            with pytest.raises(IdempotencyConflictError) as exc:
                repo.reserve(_PROJ_A, _reservation(input_sha=_sha(101)))
            assert exc.value.existing_sha256 == _sha(100)
            assert exc.value.incoming_sha256 == _sha(101)

    def test_attempt_lineage_is_append_only(self, store) -> None:
        with store.factory() as uow:
            repo = uow.reservation_repository
            repo.reserve(_PROJ_A, _reservation())
            with pytest.raises(IdempotencyConflictError):
                repo.reserve(
                    _PROJ_A,
                    _reservation(
                        reservation_id="rsv:test:dup-attempt",
                        idempotency_key="idem-key-other",
                        attempt=1,
                    ),
                )
            repo.reserve(
                _PROJ_A,
                _reservation(
                    reservation_id="rsv:test:2",
                    idempotency_key="idem-key-2",
                    attempt=2,
                ),
            )
            attempts = repo.list_attempts(_PROJ_A, "call:test:1")
            assert tuple(r.attempt for r in attempts) == (1, 2)
            assert tuple(r.execution_reservation_id for r in attempts) == (
                "rsv:test:1", "rsv:test:2",
            )

    def test_unknown_outcome_blocks_and_resolution_retains_session(self, store) -> None:
        with store.factory() as uow:
            repo = uow.reservation_repository
            repo.reserve(_PROJ_A, _reservation())
            with pytest.raises(RepositoryStateTransitionError):
                repo.transition(
                    _PROJ_A, "rsv:test:1",
                    to_status=ReservationStatus.RUNNING,
                    provider_session_id="sess:coord:1",
                    updated_at=_T1,
                )
            running = repo.transition(
                _PROJ_A, "rsv:test:1",
                to_status=ReservationStatus.RUNNING,
                provider_session_id="sess:coord:1",
                transport_attempts=1,
                updated_at=_T1,
            )
            assert running.status is ReservationStatus.RUNNING
            assert running.provider_session_id == "sess:coord:1"
            unknown = repo.transition(
                _PROJ_A, "rsv:test:1",
                to_status=ReservationStatus.UNKNOWN_OUTCOME,
                terminal_state=ExecutionTerminalState.UNKNOWN_OUTCOME,
                error_code="err:transport:unknown",
                updated_at=_T2,
            )
            assert unknown.provider_session_id == "sess:coord:1"
            with pytest.raises(UnknownOutcomeConflictError):
                repo.reserve(_PROJ_A, _reservation())
            unresolved = repo.find_unresolved(_PROJ_A)
            assert tuple(r.execution_reservation_id for r in unresolved) == ("rsv:test:1",)
            assert tuple(
                r.execution_reservation_id for r in repo.find_unknown_outcome(_PROJ_A)
            ) == ("rsv:test:1",)
            with pytest.raises(RepositoryStateTransitionError):
                repo.transition(
                    _PROJ_A, "rsv:test:1",
                    to_status=ReservationStatus.COMPLETED,
                    terminal_state=ExecutionTerminalState.COMPLETED,
                    output_sha256=_sha(9),
                    provider_session_id="sess:evil:9",
                    updated_at=_T3,
                )
            resolved = repo.transition(
                _PROJ_A, "rsv:test:1",
                to_status=ReservationStatus.COMPLETED,
                terminal_state=ExecutionTerminalState.COMPLETED,
                output_sha256=_sha(9),
                updated_at=_T3,
            )
            assert resolved.status is ReservationStatus.COMPLETED
            assert resolved.provider_session_id == "sess:coord:1"
            assert resolved.error_code is None
            assert resolved.output_sha256 == _sha(9)
            idempotent = repo.reserve(_PROJ_A, _reservation())
            assert idempotent == resolved
            assert repo.find_unresolved(_PROJ_A) == ()
            assert repo.find_unknown_outcome(_PROJ_A) == ()

    def test_illegal_transitions_fail_closed(self, store) -> None:
        with store.factory() as uow:
            repo = uow.reservation_repository
            repo.reserve(_PROJ_A, _reservation())
            with pytest.raises(RepositoryStateTransitionError):
                repo.transition(
                    _PROJ_A, "rsv:test:1",
                    to_status=ReservationStatus.COMPLETED,
                    terminal_state=ExecutionTerminalState.COMPLETED,
                    output_sha256=_sha(9),
                    updated_at=_T1,
                )
            repo.transition(
                _PROJ_A, "rsv:test:1",
                to_status=ReservationStatus.RUNNING,
                provider_session_id="sess:coord:1",
                transport_attempts=1,
                updated_at=_T1,
            )
            with pytest.raises(RepositoryStateTransitionError):
                repo.transition(
                    _PROJ_A, "rsv:test:1",
                    to_status=ReservationStatus.FAILED,
                    terminal_state=ExecutionTerminalState.FAILED,
                    error_code="err:x",
                    provider_session_id="sess:coord:1",
                    transport_attempts=0,
                    updated_at=_T2,
                )
            with pytest.raises(RepositoryStateTransitionError):
                repo.transition(
                    _PROJ_A, "rsv:test:1",
                    to_status=ReservationStatus.RESERVED,
                    updated_at=_T2,
                )

    def test_failed_terminal_path_requires_error_and_session(self, store) -> None:
        with store.factory() as uow:
            repo = uow.reservation_repository
            repo.reserve(
                _PROJ_A,
                _reservation(
                    reservation_id="rsv:fail:1",
                    logical_call_id="call:fail",
                    idempotency_key="ik:fail",
                ),
            )
            # A terminal transition off a session-less reservation cannot
            # build a valid record (terminal states require a provider
            # session), so the repository raises the record-validation error
            # on both backends before anything is written.
            with pytest.raises(ValidationError):
                repo.transition(
                    _PROJ_A, "rsv:fail:1",
                    to_status=ReservationStatus.FAILED,
                    terminal_state=ExecutionTerminalState.FAILED,
                    error_code="err:precheck",
                    transport_attempts=0,
                    updated_at=_T1,
                )
            failed = repo.transition(
                _PROJ_A, "rsv:fail:1",
                to_status=ReservationStatus.FAILED,
                terminal_state=ExecutionTerminalState.FAILED,
                error_code="err:precheck",
                provider_session_id="sess:never:1",
                transport_attempts=0,
                updated_at=_T1,
            )
            assert failed.status is ReservationStatus.FAILED
            assert failed.error_code == "err:precheck"

    def test_reservations_are_project_scoped(self, store) -> None:
        with store.factory() as uow:
            repo = uow.reservation_repository
            repo.reserve(_PROJ_A, _reservation())
            repo.reserve(_PROJ_B, _reservation(project_id=_PROJ_B))
            repo.transition(
                _PROJ_A, "rsv:test:1",
                to_status=ReservationStatus.RUNNING,
                provider_session_id="sess:a",
                transport_attempts=1,
                updated_at=_T1,
            )
            attempts_b = repo.list_attempts(_PROJ_B, "call:test:1")
            assert len(attempts_b) == 1
            assert attempts_b[0].status is ReservationStatus.RESERVED
            unknown_a = repo.find_unknown_outcome(_PROJ_A)
            assert unknown_a == ()


# ---------------------------------------------------------------------------
# Read-model projections
# ---------------------------------------------------------------------------


class TestReadModels:
    def test_replace_chapter_coverage_clears_stale_rows(self, store) -> None:
        with store.factory() as uow:
            rm = uow.read_model_repository
            rm.replace_chapter_coverage(
                _PROJ_A, "sdr:test:1", (_coverage("sn:1"), _coverage("sn:2"))
            )
            first = rm.get_chapter_coverage(_PROJ_A, "sdr:test:1")
            assert len(first) == 2
            rm.replace_chapter_coverage(
                _PROJ_A, "sdr:test:1", (_coverage("sn:2", locked=True),)
            )
            second = rm.get_chapter_coverage(_PROJ_A, "sdr:test:1")
            assert len(second) == 1
            assert second[0].semantic_node_id == "sn:2"
            assert second[0].is_locked is True

        def read(uow: UnitOfWork) -> object:
            return uow.read_model_repository.get_chapter_coverage(_PROJ_A, "sdr:test:1")

        final = store.inspect(read)
        assert tuple(r.semantic_node_id for r in final) == ("sn:2",)

    def test_replace_decision_graph_clears_stale_keys(self, store) -> None:
        with store.factory() as uow:
            rm = uow.read_model_repository
            rm.replace_decision_graph(
                _PROJ_A, "sd:test:1",
                (_decision("primary_endpoint"), _decision("control")),
            )
            rm.replace_decision_graph(
                _PROJ_A, "sd:test:1", (_decision("primary_endpoint"),)
            )
            records = rm.get_decision_graph(_PROJ_A, "sd:test:1")
            assert len(records) == 1
            assert records[0].decision_key == "primary_endpoint"
            assert records[0].canonical_state is CanonicalState.CONFIRMED

    def test_read_model_project_isolation(self, store) -> None:
        with store.factory() as uow:
            rm = uow.read_model_repository
            rm.replace_chapter_coverage(
                _PROJ_A, "sdr:dup", (_coverage("sn:a", project_id=_PROJ_A),)
            )
            rm.replace_chapter_coverage(
                _PROJ_B, "sdr:dup", (_coverage("sn:b", project_id=_PROJ_B),)
            )
            rm.replace_decision_graph(
                _PROJ_A, "sd:dup", (_decision("k", project_id=_PROJ_A),)
            )
            rm.replace_decision_graph(
                _PROJ_B, "sd:dup", (_decision("k", project_id=_PROJ_B, state=CanonicalState.RAW),)
            )
            cov_a = rm.get_chapter_coverage(_PROJ_A, "sdr:dup")
            cov_b = rm.get_chapter_coverage(_PROJ_B, "sdr:dup")
            dec_a = rm.get_decision_graph(_PROJ_A, "sd:dup")
            dec_b = rm.get_decision_graph(_PROJ_B, "sd:dup")
            assert tuple(r.semantic_node_id for r in cov_a) == ("sn:a",)
            assert tuple(r.semantic_node_id for r in cov_b) == ("sn:b",)
            assert dec_a[0].canonical_state is CanonicalState.CONFIRMED
            assert dec_b[0].canonical_state is CanonicalState.RAW

    def test_workflow_run_status_upsert(self, store) -> None:
        record = WorkflowRunStatusRecord(
            project_id=_PROJ_A,
            workflow_run_id="run:1",
            status=WorkflowRunStatus.RUNNING,
            display_progress=0.5,
            journey_counter=2,
        )
        updated = WorkflowRunStatusRecord(
            project_id=_PROJ_A,
            workflow_run_id="run:1",
            status=WorkflowRunStatus.COMPLETED,
            display_progress=1.0,
            journey_counter=3,
        )
        with store.factory() as uow:
            rm = uow.read_model_repository
            rm.upsert_workflow_run_status(record)
            assert rm.get_workflow_run_status(_PROJ_A, "run:1") == record
            rm.upsert_workflow_run_status(updated)
            assert rm.get_workflow_run_status(_PROJ_A, "run:1") == updated
            assert rm.get_workflow_run_status(_PROJ_B, "run:1") is None


# ---------------------------------------------------------------------------
# Unit-of-work transaction lifecycle
# ---------------------------------------------------------------------------


class TestUnitOfWorkLifecycle:
    def test_commit_makes_canonical_event_outbox_durable_together(self, store) -> None:
        e1 = _built_event(
            event_id="evt:1", stream_id="stream:test:1", sequence=1,
            previous=None, payload={"n": 1},
        )
        with store.factory() as uow:
            assert uow.is_active is True
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(), 0
            )
            uow.event_stream_repository.append_events(_PROJ_A, "stream:test:1", (e1,))
            uow.outbox_repository.enqueue(
                _PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(30), _T0
            )

        def read(uow: UnitOfWork) -> object:
            return (
                uow.study_definition_repository.get_current_revision(_PROJ_A, "sd:test:1"),
                len(uow.event_stream_repository.read_events(_PROJ_A, "stream:test:1")),
                uow.outbox_repository.find_by_logical_key(_PROJ_A, "lk:1") is not None,
            )

        study_rev, event_count, has_outbox = store.inspect(read)
        assert (study_rev, event_count, has_outbox) == (1, 1, True)

    def test_rollback_discards_all_three_writes(self, store) -> None:
        e1 = _built_event(
            event_id="evt:1", stream_id="stream:test:1", sequence=1,
            previous=None, payload={"n": 1},
        )
        with pytest.raises(RuntimeError, match="force rollback"):
            with store.factory() as uow:
                uow.study_definition_cas_repository.save_with_expected_revision(
                    _PROJ_A, _study(), 0
                )
                uow.event_stream_repository.append_events(_PROJ_A, "stream:test:1", (e1,))
                uow.outbox_repository.enqueue(
                    _PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:1", _sha(30), _T0
                )
                raise RuntimeError("force rollback")

        def read(uow: UnitOfWork) -> object:
            return (
                uow.study_definition_repository.get_current_revision(_PROJ_A, "sd:test:1"),
                uow.event_stream_repository.read_events(_PROJ_A, "stream:test:1"),
                uow.outbox_repository.find_by_logical_key(_PROJ_A, "lk:1"),
                uow.inbox_repository.was_processed(_PROJ_A, "lk:1"),
            )

        study_rev, events, outbox, processed = store.inspect(read)
        assert study_rev is None
        assert events == ()
        assert outbox is None
        assert processed is False

    def test_nested_with_blocks_commit_once_at_outermost(self, store) -> None:
        uow = store.factory()
        with uow:
            with uow:
                assert uow.is_active is True
                uow.study_definition_cas_repository.save_with_expected_revision(
                    _PROJ_A, _study(), 0
                )
            assert uow.is_active is True
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(revision=2, previous=_sha(1)), 1
            )
        assert uow.is_active is False

        def read(uw: UnitOfWork) -> object:
            return uw.study_definition_repository.get_current_revision(_PROJ_A, "sd:test:1")

        assert store.inspect(read) == 2

    def test_mutations_after_commit_fail_closed(self, store) -> None:
        uow = store.factory()
        with uow:
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(), 0
            )
        with pytest.raises(UnitOfWorkClosedError):
            uow.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(revision=2, previous=_sha(1)), 1
            )
        with pytest.raises(UnitOfWorkClosedError):
            uow.event_stream_repository.append_events(_PROJ_A, "s", ())
        with pytest.raises(UnitOfWorkClosedError):
            uow.outbox_repository.enqueue(
                _PROJ_A, "run:1", SideEffectKind.EXPORT, "lk:x", _sha(1), _T0
            )
        with pytest.raises(UnitOfWorkClosedError):
            uow.inbox_repository.record_result(_PROJ_A, "lk:x", _sha(1), _T0)
        with pytest.raises(UnitOfWorkClosedError):
            uow.reservation_repository.reserve(_PROJ_A, _reservation())
        with pytest.raises(UnitOfWorkClosedError):
            uow.read_model_repository.replace_decision_graph(_PROJ_A, "sd:x", ())

    def test_rollback_is_idempotent_and_enter_after_close_raises(self, store) -> None:
        uow = store.factory()
        uow.rollback()
        uow.rollback()
        assert uow.is_active is False
        with pytest.raises(RuntimeError):
            with uow:
                pass

        uow2 = store.factory()
        with uow2:
            uow2.study_definition_cas_repository.save_with_expected_revision(
                _PROJ_A, _study(), 0
            )
        uow2.rollback()
        uow2.rollback()

        def read(uw: UnitOfWork) -> object:
            return uw.study_definition_repository.get_current_revision(_PROJ_A, "sd:test:1")

        assert store.inspect(read) == 1

    def test_uow_satisfies_runtime_checkable_port(self, store) -> None:
        uow = store.factory()
        assert isinstance(uow, UnitOfWork)
        with uow:
            assert uow.study_definition_repository is not None
            assert uow.study_definition_cas_repository is not None
            assert uow.semantic_document_repository is not None
            assert uow.semantic_document_cas_repository is not None
            assert uow.event_stream_repository is not None
            assert uow.outbox_repository is not None
            assert uow.inbox_repository is not None
            assert uow.reservation_repository is not None
            assert uow.read_model_repository is not None
