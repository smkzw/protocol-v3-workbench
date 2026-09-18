"""Functional tests for the Protocol v3 application service (Task 1.9).

Tests verify the three-layer contract:

1. **Immutable typed commands** — every mutation carries project/revision/
   idempotency/actor/reason and a full DecisionRecord; construction validates
   the CAS relationship before any repository use.

2. **Canonical mutation boundary** — the service is the ONLY component that
   opens a UoW and obtains repositories; a StudyDefinition decision-mutation
   path composes the accepted reducer + event-sourced UoW helper; CAS + event
   + outbox commit atomically; exact replay is idempotent with no second
   write; stale revision, snapshot mismatch, same-key/different-payload and
   project mismatch all fail closed with the existing typed error catalog.

3. **Read-only queries** — every query leaves aggregate/event/outbox counts
   and hashes unchanged; no CAS save, event append, outbox enqueue or
   read-model mutation occurs.

All tests use an explicit shared-state in-memory UoW factory; product
configuration is never routed to Memory.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from typing import Any, Dict, Tuple

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DecisionRecord,
    DomainEvent,
    SideEffectKind,
    StudyDefinitionV3,
)
from app.protocol_workflow.application import (
    ApplyStudyDecisionCommand,
    ApplicationService,
    CreateStudyDefinitionCommand,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DECISION_APPLIED,
    GetDecisionGraphQuery,
    GetStudyDefinitionEventSummaryQuery,
    GetStudyDefinitionQuery,
    GetWorkflowRunStatusQuery,
    SideEffectSpec,
    StudyDefinitionMutationResult,
    study_definition_genesis_snapshot,
    study_definition_stream_id,
)
from app.protocol_workflow.canonical import (
    DecisionEffectLedger,
    decision_cas_identity,
    exact_payload_sha256,
    study_revision_hash,
)
from app.protocol_workflow.errors import (
    ProtocolErrorCode,
    ProtocolWorkflowError,
)
from app.protocol_workflow.events.unit_of_work import MissingRepositoryError
from app.protocol_workflow.ports.repositories import (
    EventSequenceConflictError,
    InboxRepository,
    OutboxRepository,
    ReadModelRepository,
    StreamHead,
)
from app.protocol_workflow.ports.unit_of_work import UnitOfWork
from app.protocol_workflow.storage.memory import (
    InMemoryCurrentAggregateRepository,
    InMemoryEventStreamRepository,
    InMemoryExecutionReservationRepository,
    InMemoryInboxRepository,
    InMemoryOutboxRepository,
    InMemoryReadModelRepository,
    InMemoryRevisionCasRepository,
    InMemoryUnitOfWork,
    InMemoryArtifactStore,
    _AggregateIndex,
)


# ---------------------------------------------------------------------------
# Constants and fixtures
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)

_PROJECT = "proj:test:sd:1"
_OTHER_PROJECT = "proj:test:sd:2"
_SD_ID = "sd:test:1"
_SEED_ID = "seed:test:1"
_SEED_SHA = "a" * 64
_RUN_ID = "wr:test:1"
_FACTS = {
    "picos.population.indication": "中重度活动性溃疡性结肠炎",
    "picos.intervention.dose": "10 mg 每日一次",
}


# ---------------------------------------------------------------------------
# Shared-state memory adapter (clone of test_event_outbox_atomicity._SharedState)
# ---------------------------------------------------------------------------


class _SharedState:
    """Shared repositories across single-use UoW instances.

    Each service call opens a fresh UoW backed by these shared repos, so
    committed state persists into subsequent calls — the in-memory analogue
    of a real application service against persistent storage.
    """

    def __init__(self, *, event_append_failure: bool = False) -> None:
        sd_index = _AggregateIndex()
        self.sd_repo = InMemoryCurrentAggregateRepository(
            identity_field="study_definition_id", index=sd_index,
        )
        self.sd_cas = InMemoryRevisionCasRepository(
            identity_field="study_definition_id", index=sd_index,
        )
        self.sdr_repo = InMemoryCurrentAggregateRepository(
            identity_field="semantic_document_revision_id",
            index=_AggregateIndex(),
        )
        self.sdr_cas = InMemoryRevisionCasRepository(
            identity_field="semantic_document_revision_id",
            index=_AggregateIndex(),
        )
        self.ev_repo: InMemoryEventStreamRepository = (
            _FailingEventStreamRepository()
            if event_append_failure
            else InMemoryEventStreamRepository()
        )
        self.ob_repo = InMemoryOutboxRepository()
        self.ib_repo = InMemoryInboxRepository()
        self.rv_repo = InMemoryExecutionReservationRepository()
        self.rm_repo = InMemoryReadModelRepository()
        self.artifacts = InMemoryArtifactStore()

    def new_uow(self) -> InMemoryUnitOfWork:
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

    def factory(self):
        """Return a UnitOfWorkFactory that opens a fresh UoW over shared repos."""
        return self.new_uow


class _FailingEventStreamRepository(InMemoryEventStreamRepository):
    """Test-only event repo that fails every append to prove the UoW rollback
    boundary at the event step."""

    def append_events(self, project_id, stream_id, events):
        raise EventSequenceConflictError(
            project_id,
            stream_id,
            expected_sequence=None,
            actual_sequence=None,
            detail="simulated event append failure",
        )


# ---------------------------------------------------------------------------
# Command / decision / query builders
# ---------------------------------------------------------------------------


def _decision(
    *,
    decision_record_id: str = "decision:create:001",
    decision_key: str = "decision:create",
    snapshot_sha256: str,
    expected_state_revision: int,
    actor_type: ActorType = ActorType.USER,
    actor_id: str = "user:medical-writer",
    reason: str = "接受 AI 推荐的默认剂量设计。",
    canonical_state: CanonicalState = CanonicalState.CONFIRMED,
    **overrides: Any,
) -> DecisionRecord:
    payload = {
        "decision_record_id": decision_record_id,
        "decision_key": decision_key,
        "snapshot_sha256": snapshot_sha256,
        "expected_state_revision": expected_state_revision,
        "state_revision": expected_state_revision + 1,
        "option_ids": ("option:dose:001", "option:dose:002"),
        "selected_option_id": "option:dose:001",
        "actor_type": actor_type,
        "actor_id": actor_id,
        "reason": reason,
        "decided_at": _T0,
        "canonical_state": canonical_state,
    }
    payload.update(overrides)
    return DecisionRecord(**payload)


def _create_command(
    *,
    project_id: str = _PROJECT,
    study_definition_id: str = _SD_ID,
    idempotency_key: str = "idem:create:1",
    facts: Dict[str, Any] | None = None,
    side_effect: SideEffectSpec | None = None,
    **overrides: Any,
) -> CreateStudyDefinitionCommand:
    facts = facts if facts is not None else dict(_FACTS)
    snapshot = study_definition_genesis_snapshot(
        study_definition_id=study_definition_id,
        project_id=project_id,
        normalized_seed_id=_SEED_ID,
        normalized_seed_sha256=_SEED_SHA,
        facts=facts,
        decided_at=_T0,
    )
    dr = _decision(
        decision_record_id=overrides.pop("decision_record_id", "decision:create:001"),
        decision_key=overrides.pop("decision_key", "decision:create"),
        snapshot_sha256=snapshot,
        expected_state_revision=0,
    )
    return CreateStudyDefinitionCommand(
        project_id=project_id,
        study_definition_id=study_definition_id,
        idempotency_key=idempotency_key,
        expected_revision=overrides.pop("expected_revision", 0),
        actor_type=overrides.pop("actor_type", ActorType.USER),
        actor_id=overrides.pop("actor_id", "user:medical-writer"),
        reason=overrides.pop("reason", "接受 AI 推荐的默认剂量设计。"),
        decision_record=overrides.pop("decision_record", dr),
        normalized_seed_id=overrides.pop("normalized_seed_id", _SEED_ID),
        normalized_seed_sha256=overrides.pop("normalized_seed_sha256", _SEED_SHA),
        initial_facts=overrides.pop("initial_facts", facts),
        side_effect=side_effect,
    )


def _apply_command(
    *,
    project_id: str = _PROJECT,
    study_definition_id: str = _SD_ID,
    idempotency_key: str = "idem:apply:1",
    expected_revision: int,
    snapshot_sha256: str,
    decision_record_id: str = "decision:dose:001",
    decision_key: str = "decision:dose",
    fact_updates: Dict[str, Any] | None = None,
    side_effect: SideEffectSpec | None = None,
    **overrides: Any,
) -> ApplyStudyDecisionCommand:
    dr = _decision(
        decision_record_id=decision_record_id,
        decision_key=decision_key,
        snapshot_sha256=snapshot_sha256,
        expected_state_revision=expected_revision,
    )
    return ApplyStudyDecisionCommand(
        project_id=project_id,
        study_definition_id=study_definition_id,
        idempotency_key=idempotency_key,
        expected_revision=expected_revision,
        actor_type=overrides.pop("actor_type", ActorType.USER),
        actor_id=overrides.pop("actor_id", "user:medical-writer"),
        reason=overrides.pop("reason", "接受 AI 推荐的默认剂量设计。"),
        decision_record=overrides.pop("decision_record", dr),
        fact_updates=fact_updates,
        side_effect=side_effect,
    )


def _side_effect_spec(
    *,
    workflow_run_id: str = _RUN_ID,
    kind: SideEffectKind = SideEffectKind.CANONICAL_PROPOSAL,
) -> SideEffectSpec:
    return SideEffectSpec(workflow_run_id=workflow_run_id, side_effect_kind=kind)


# ---------------------------------------------------------------------------
# Service fixture
# ---------------------------------------------------------------------------


def _service(state: _SharedState) -> ApplicationService:
    return ApplicationService(
        unit_of_work_factory=state.factory(),
        clock=lambda: _T0,
    )


# ---------------------------------------------------------------------------
# Fingerprint helpers (read-only probes against the shared store)
# ---------------------------------------------------------------------------


def _aggregate_fp(
    state: _SharedState,
    project_id: str = _PROJECT,
    sd_id: str = _SD_ID,
) -> Tuple[int, str, str, tuple]:
    current = state.sd_repo.get_current(project_id, sd_id)
    if current is None:
        return (0, "", "", ())
    return (
        current.revision,
        study_revision_hash(current),
        current.material_sha256(),
        tuple(sorted(current.decision_record_ids)),
    )


def _event_fp(state: _SharedState, *, project_id: str = _PROJECT, sd_id: str = _SD_ID):
    return state.ev_repo.read_events(project_id, study_definition_stream_id(sd_id))


def _outbox_fp(state: _SharedState, *, project_id: str = _PROJECT) -> tuple:
    return tuple(
        sorted(
            (
                m.logical_key,
                m.payload_sha256,
                m.status.value,
                m.workflow_run_id,
            )
            for m in state.ob_repo._messages.values()
            if m.project_id == project_id
        )
    )


# ---------------------------------------------------------------------------
# Tests — Create
# ---------------------------------------------------------------------------


class TestCreateStudyDefinition:
    """Atomic creation: CAS save + event append + optional outbox commit."""

    def test_create_persists_cas_event_and_outbox(self) -> None:
        """A successful create writes the aggregate, appends a created event
        and enqueues the outbox message."""
        state = _SharedState()
        svc = _service(state)
        spec = _side_effect_spec()
        cmd = _create_command(side_effect=spec)
        result = svc.create_study_definition(cmd)

        assert result.replayed is False
        assert result.revision == 1
        assert result.definition.revision == 1
        assert result.definition.project_id == _PROJECT
        assert result.definition.facts == _FACTS
        assert result.definition.decision_record_ids == ("decision:create:001",)
        assert result.definition.canonical_state is CanonicalState.CONFIRMED
        assert len(result.appended_events) == 1
        assert result.appended_events[0].event_type == EVENT_TYPE_CREATED
        assert result.enqueued_outbox is not None
        assert result.enqueued_outbox.logical_key == cmd.idempotency_key

        # persisted state
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        assert current is not None and current.revision == 1
        events = _event_fp(state)
        assert len(events) == 1
        expected_cas = decision_cas_identity(
            cmd.decision_record.decision_record_id,
            cmd.decision_record.snapshot_sha256,
            0,
        )
        assert events[0].payload["cas_identity"] == expected_cas
        assert events[0].payload["result_revision"] == 1
        msg = state.ob_repo.find_by_logical_key(_PROJECT, cmd.idempotency_key)
        assert msg is not None and msg.status.value == "pending"

    def test_create_exact_replay_is_idempotent(self) -> None:
        """Replaying the exact same create command (same CAS triple, same
        payload) returns the prior result with no second write."""
        state = _SharedState()
        svc = _service(state)
        spec = _side_effect_spec()
        cmd = _create_command(side_effect=spec)
        first = svc.create_study_definition(cmd)
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        second = svc.create_study_definition(cmd)
        assert second.replayed is True
        assert second.definition.revision == 1
        assert second.definition is first.definition
        assert second.revision == first.revision
        assert second.appended_events == ()
        assert second.enqueued_outbox is None

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before
        assert len(_event_fp(state)) == 1

    def test_create_replay_different_idempotency_key_still_replays(self) -> None:
        """Replay is keyed by the CAS triple, not the idempotency key."""
        state = _SharedState()
        svc = _service(state)
        cmd1 = _create_command(idempotency_key="idem:a")
        first = svc.create_study_definition(cmd1)
        cmd2 = _create_command(idempotency_key="idem:b")
        second = svc.create_study_definition(cmd2)

        assert second.replayed is True
        assert second.definition is first.definition
        assert len(_event_fp(state)) == 1

    def test_create_without_side_effect_writes_no_outbox(self) -> None:
        state = _SharedState()
        svc = _service(state)
        cmd = _create_command(side_effect=None)
        result = svc.create_study_definition(cmd)

        assert result.replayed is False
        assert result.enqueued_outbox is None
        assert _outbox_fp(state) == ()


# ---------------------------------------------------------------------------
# Tests — Apply Decision
# ---------------------------------------------------------------------------


class TestApplyStudyDecision:
    """Decision-mutation path through reducer + event-sourced UoW."""

    def test_apply_advances_revision_with_effect(self) -> None:
        state = _SharedState()
        svc = _service(state)
        create_result = svc.create_study_definition(_create_command())
        snapshot = study_revision_hash(create_result.definition)

        cmd = _apply_command(
            expected_revision=1,
            snapshot_sha256=snapshot,
            fact_updates={"picos.population.age": "成人"},
            side_effect=_side_effect_spec(),
        )
        result = svc.apply_decision(cmd)

        assert result.replayed is False
        assert result.revision == 2
        assert result.definition.facts["picos.population.age"] == "成人"
        assert result.definition.decision_record_ids == (
            "decision:create:001",
            "decision:dose:001",
        )
        assert result.definition.canonical_state is CanonicalState.CONFIRMED
        events = _event_fp(state)
        assert len(events) == 2
        assert events[1].event_type == EVENT_TYPE_DECISION_APPLIED
        assert events[1].payload["fact_updates_sha256"] == exact_payload_sha256(
            {"picos.population.age": "成人"}
        )
        msg = state.ob_repo.find_by_logical_key(_PROJECT, cmd.idempotency_key)
        assert msg is not None and msg.status.value == "pending"

    def test_apply_exact_replay_returns_prior_without_writes(self) -> None:
        state = _SharedState()
        svc = _service(state)
        create_result = svc.create_study_definition(_create_command())
        snapshot = study_revision_hash(create_result.definition)
        cmd = _apply_command(
            expected_revision=1, snapshot_sha256=snapshot,
        )
        first = svc.apply_decision(cmd)
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        second = svc.apply_decision(cmd)
        assert second.replayed is True
        assert second.definition is first.definition
        assert second.revision == first.revision
        assert second.appended_events == ()
        assert second.enqueued_outbox is None

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before

    def test_apply_without_side_effect_appends_event_only(self) -> None:
        state = _SharedState()
        svc = _service(state)
        create_result = svc.create_study_definition(_create_command())
        snapshot = study_revision_hash(create_result.definition)
        cmd = _apply_command(
            expected_revision=1,
            snapshot_sha256=snapshot,
            side_effect=None,
        )
        result = svc.apply_decision(cmd)

        assert result.replayed is False
        assert result.enqueued_outbox is None
        assert len(_event_fp(state)) == 2
        assert _outbox_fp(state) == ()


# ---------------------------------------------------------------------------
# Tests — Fail-closed behaviour
# ---------------------------------------------------------------------------


class TestFailClosed:
    """Every failure path rolls back or rejects cleanly; no second revision,
    event or outbox side effect is left durable."""

    def test_stale_revision_fails_closed(self) -> None:
        state = _SharedState()
        svc = _service(state)
        create_result = svc.create_study_definition(_create_command())
        snap1 = study_revision_hash(create_result.definition)
        svc.apply_decision(
            _apply_command(expected_revision=1, snapshot_sha256=snap1)
        )
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        snap2 = study_revision_hash(current)
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.apply_decision(
                _apply_command(
                    expected_revision=1,
                    snapshot_sha256=snap2,
                    decision_record_id="decision:dose:002",
                )
            )
        err = exc_info.value
        assert err.code == ProtocolErrorCode.P1_REVISION_STALE
        assert err.retryable is True

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before

    def test_snapshot_mismatch_fails_closed(self) -> None:
        state = _SharedState()
        svc = _service(state)
        create_result = svc.create_study_definition(_create_command())
        snap1 = study_revision_hash(create_result.definition)
        svc.apply_decision(
            _apply_command(expected_revision=1, snapshot_sha256=snap1)
        )
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.apply_decision(
                _apply_command(
                    expected_revision=current.revision,
                    snapshot_sha256="b" * 64,
                    decision_record_id="decision:dose:002",
                )
            )
        assert exc_info.value.code == ProtocolErrorCode.P1_REVISION_STALE

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before

    def test_same_idempotency_key_different_payload_rolls_back(self) -> None:
        """Second mutation (fresh CAS) using the same idempotency key as the
        first side effect triggers an outbox conflict; the whole second
        transaction rolls back leaving the first mutation's state intact."""
        state = _SharedState()
        svc = _service(state)
        shared_key = "idem:shared:1"
        spec = _side_effect_spec()
        svc.create_study_definition(
            _create_command(idempotency_key=shared_key, side_effect=spec)
        )
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        snapshot = study_revision_hash(current)
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.apply_decision(
                _apply_command(
                    idempotency_key=shared_key,
                    expected_revision=1,
                    snapshot_sha256=snapshot,
                    decision_record_id="decision:dose:002",
                    decision_key="decision:dose2",
                    side_effect=spec,
                )
            )
        assert exc_info.value.code == ProtocolErrorCode.P1_DECISION_CAS

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before

    def test_project_mismatch_fails_closed(self) -> None:
        """A command scoped to a different project finds no aggregate; no
        cross-project state is exposed or mutated."""
        state = _SharedState()
        svc = _service(state)
        svc.create_study_definition(_create_command())
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.apply_decision(
                _apply_command(
                    project_id=_OTHER_PROJECT,
                    expected_revision=1,
                    snapshot_sha256="b" * 64,
                )
            )
        assert exc_info.value.code == ProtocolErrorCode.P1_OBJECT_NOT_FOUND

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before

    def test_create_on_existing_with_different_decision_fails_closed(self) -> None:
        """A second create with a different CAS identity (different
        decision_record_id) on an existing aggregate is stale; nothing is
        written."""
        state = _SharedState()
        svc = _service(state)
        svc.create_study_definition(_create_command())
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.create_study_definition(
                _create_command(
                    decision_record_id="decision:create:002",
                    decision_key="decision:create2",
                )
            )
        assert exc_info.value.code == ProtocolErrorCode.P1_REVISION_STALE

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before

    def test_rollback_on_event_append_failure(self) -> None:
        """An event-append failure rolls back the CAS save and leaves no
        aggregate, no event and no outbox message."""
        state = _SharedState(event_append_failure=True)
        svc = _service(state)

        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.create_study_definition(_create_command())
        assert exc_info.value.code == ProtocolErrorCode.P1_CHECKPOINT_EVENT_MISMATCH
        assert exc_info.value.retryable is False
        assert state.sd_repo.get_current(_PROJECT, _SD_ID) is None
        assert _event_fp(state) == ()
        assert _outbox_fp(state) == ()

    def test_frozen_fact_overwrite_fails_closed(self) -> None:
        """Changing an existing fact while the definition is CONFIRMED is
        rejected by the reducer; the failed mutation leaves no second write."""
        state = _SharedState()
        svc = _service(state)
        svc.create_study_definition(_create_command())
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        snapshot = study_revision_hash(current)
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.apply_decision(
                _apply_command(
                    expected_revision=1,
                    snapshot_sha256=snapshot,
                    fact_updates={"picos.intervention.dose": "20 mg 每日一次"},
                )
            )
        assert exc_info.value.code == ProtocolErrorCode.P1_DECISION_CAS

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before


# ---------------------------------------------------------------------------
# Tests — Queries
# ---------------------------------------------------------------------------


class TestQueries:
    """Every query leaves all aggregate/event/outbox/read-model counts and
    hashes unchanged."""

    @pytest.fixture()
    def populated(self):
        state = _SharedState()
        svc = _service(state)
        cr = svc.create_study_definition(_create_command())
        snap = study_revision_hash(cr.definition)
        svc.apply_decision(
            _apply_command(
                expected_revision=1,
                snapshot_sha256=snap,
                fact_updates={"picos.population.age": "成人"},
            )
        )
        return state, svc

    def test_queries_return_correct_results(self, populated) -> None:
        state, svc = populated
        q1 = svc.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=_PROJECT, study_definition_id=_SD_ID,
            )
        )
        assert q1.definition is not None
        assert q1.revision == 2
        assert q1.revision_sha256 == study_revision_hash(q1.definition)

        q2 = svc.get_study_definition_event_summary(
            GetStudyDefinitionEventSummaryQuery(
                project_id=_PROJECT, study_definition_id=_SD_ID,
            )
        )
        assert q2.event_count == 2
        assert q2.last_sequence == 2
        assert len(q2.decisions) == 2
        assert q2.decisions[0].decision_record_id == "decision:create:001"
        assert q2.decisions[0].applied_revision == 1
        assert q2.decisions[0].canonical_state is CanonicalState.CONFIRMED
        assert q2.decisions[1].decision_record_id == "decision:dose:001"
        assert q2.decisions[1].applied_revision == 2

        q3 = svc.get_decision_graph(
            GetDecisionGraphQuery(
                project_id=_PROJECT, study_definition_id=_SD_ID,
            )
        )
        assert {row.decision_record_id for row in q3.records} == {
            "decision:create:001", "decision:dose:001",
        }
        assert all(row.current_validity == "unverified" for row in q3.records)

        q4 = svc.get_workflow_run_status(
            GetWorkflowRunStatusQuery(
                project_id=_PROJECT, workflow_run_id=_RUN_ID,
            )
        )
        assert q4.status is None

        q5 = svc.get_study_definition(
            GetStudyDefinitionQuery(
                project_id="proj:none:1", study_definition_id=_SD_ID,
            )
        )
        assert q5.definition is None and q5.revision is None

    def test_queries_leave_zero_write_side_effects(self, populated) -> None:
        state, svc = populated
        before_def = state.sd_repo.get_current(_PROJECT, _SD_ID)
        before_events = _event_fp(state)
        before_outbox = _outbox_fp(state)
        before_rm_dec = state.rm_repo.get_decision_graph(_PROJECT, _SD_ID)
        before_rm_run = state.rm_repo.get_workflow_run_status(_PROJECT, _RUN_ID)

        svc.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=_PROJECT, study_definition_id=_SD_ID,
            )
        )
        svc.get_study_definition_event_summary(
            GetStudyDefinitionEventSummaryQuery(
                project_id=_PROJECT, study_definition_id=_SD_ID,
            )
        )
        svc.get_decision_graph(
            GetDecisionGraphQuery(
                project_id=_PROJECT, study_definition_id=_SD_ID,
            )
        )
        svc.get_workflow_run_status(
            GetWorkflowRunStatusQuery(
                project_id=_PROJECT, workflow_run_id=_RUN_ID,
            )
        )

        after_def = state.sd_repo.get_current(_PROJECT, _SD_ID)
        assert after_def is before_def
        assert study_revision_hash(after_def) == study_revision_hash(before_def)
        assert _event_fp(state) == before_events
        assert _outbox_fp(state) == before_outbox
        assert state.rm_repo.get_decision_graph(_PROJECT, _SD_ID) == before_rm_dec
        assert state.rm_repo.get_workflow_run_status(_PROJECT, _RUN_ID) == before_rm_run


# ---------------------------------------------------------------------------
# Tests — Command immutability and validation
# ---------------------------------------------------------------------------


class TestCommandValidation:
    def test_commands_are_frozen(self) -> None:
        cmd = _create_command()
        assert cmd.__dataclass_params__.frozen is True
        with pytest.raises(dataclasses.FrozenInstanceError):
            cmd.project_id = "x"  # type: ignore[misc]

    def test_decision_record_is_frozen(self) -> None:
        cmd = _create_command()
        assert cmd.decision_record.model_config.get("frozen") is True

    def test_study_facts_are_frozen(self) -> None:
        state = _SharedState()
        svc = _service(state)
        result = svc.create_study_definition(_create_command())
        with pytest.raises(TypeError):
            result.definition.facts["new"] = 1  # type: ignore[index]

    def test_create_rejects_expected_revision_not_zero(self) -> None:
        with pytest.raises(ValueError, match="expected_revision must be 0"):
            _create_command(expected_revision=1)  # type: ignore

    def test_create_rejects_non_confirmed_decision(self) -> None:
        snap = study_definition_genesis_snapshot(
            study_definition_id=_SD_ID,
            project_id=_PROJECT,
            normalized_seed_id=_SEED_ID,
            normalized_seed_sha256=_SEED_SHA,
            facts=_FACTS,
            decided_at=_T0,
        )
        dr = _decision(
            snapshot_sha256=snap,
            expected_state_revision=0,
            canonical_state=CanonicalState.FROZEN,
        )
        with pytest.raises(ValueError, match="must be CONFIRMED"):
            _create_command(decision_record=dr)

    def test_create_rejects_mismatched_snapshot(self) -> None:
        dr = _decision(
            snapshot_sha256="b" * 64,
            expected_state_revision=0,
        )
        with pytest.raises(ValueError, match="genesis baseline"):
            _create_command(decision_record=dr)

    def test_apply_rejects_expected_revision_zero(self) -> None:
        with pytest.raises(ValueError, match="expected_revision must be >= 1"):
            _apply_command(
                expected_revision=0,
                snapshot_sha256="a" * 64,
            )

    def test_apply_rejects_decision_alignment_mismatch(self) -> None:
        dr = _decision(
            snapshot_sha256="a" * 64,
            expected_state_revision=5,
        )
        with pytest.raises(ValueError, match="expected_state_revision must equal"):
            _apply_command(
                expected_revision=3,
                snapshot_sha256="a" * 64,
                decision_record=dr,
            )

    def test_side_effect_rejects_none_kind(self) -> None:
        with pytest.raises(ValueError, match="must not be SideEffectKind.NONE"):
            SideEffectSpec(
                workflow_run_id=_RUN_ID,
                side_effect_kind=SideEffectKind.NONE,
            )


# ---------------------------------------------------------------------------
# Tests — Error translation
# ---------------------------------------------------------------------------


class TestErrorTranslation:
    def test_errors_are_typed_with_public_payload(self) -> None:
        state = _SharedState()
        svc = _service(state)
        create_result = svc.create_study_definition(_create_command())
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        snap = study_revision_hash(current)
        before = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )

        # Mismatched snapshot triggers P1_REVISION_STALE
        with pytest.raises(ProtocolWorkflowError) as exc_info:
            svc.apply_decision(
                _apply_command(
                    expected_revision=1,
                    snapshot_sha256="b" * 64,
                    decision_record_id="decision:dose:002",
                )
            )
        err = exc_info.value
        assert err.code == ProtocolErrorCode.P1_REVISION_STALE
        assert err.object_id == _SD_ID
        assert err.attempt == 1
        public = err.to_public_payload()
        assert "当前页面不是方案的最新版本" in public["message"]
        assert public["can_retry"] is True
        audit = err.to_audit_payload()
        assert audit["error_code"] == "MW-PRO-P1-REVISION-STALE"
        assert audit["object_id"] == _SD_ID
        assert audit["audit_context"]["project_id"] == _PROJECT

        after = (
            _aggregate_fp(state),
            _event_fp(state),
            _outbox_fp(state),
        )
        assert after == before


# ---------------------------------------------------------------------------
# Tests — No repository/UoW handles in results
# ---------------------------------------------------------------------------


class TestResultsDoNotExposeRepositories:
    def test_mutation_results_expose_no_handles(self) -> None:
        state = _SharedState()
        svc = _service(state)
        result = svc.create_study_definition(_create_command())
        for value in vars(result).values():
            if value is None:
                continue
            assert not isinstance(value, (
                InMemoryUnitOfWork,
                InMemoryCurrentAggregateRepository,
                InMemoryRevisionCasRepository,
                InMemoryEventStreamRepository,
                InMemoryOutboxRepository,
                InMemoryInboxRepository,
                InMemoryReadModelRepository,
            ))

    def test_query_results_expose_no_handles(self) -> None:
        state = _SharedState()
        svc = _service(state)
        svc.create_study_definition(_create_command())
        q = svc.get_study_definition(
            GetStudyDefinitionQuery(
                project_id=_PROJECT, study_definition_id=_SD_ID,
            )
        )
        for value in vars(q).values():
            if value is None:
                continue
            assert not isinstance(value, (
                InMemoryUnitOfWork,
                InMemoryCurrentAggregateRepository,
                InMemoryRevisionCasRepository,
                InMemoryEventStreamRepository,
                InMemoryOutboxRepository,
            ))
