"""Authority boundary tests for the Agent⑤ control surface (Protocol v3 Task 1.9).

Design authority: design sections 5.3 / 5.4 / 18 / 19 and the frozen plan
Task 1.9.  The tests prove:

**Positive**
* immutable, closed, deterministic pinning of an approved registry selection
  and run manifest (template/graph/schema/skill/source/StudyDefinition pins);
* deterministic dependency order for registered coordinator work packages;
* read-only aggregation of progress, versions and Gate observations (store
  fingerprints unchanged);
* strict public/audit exception-card separation using the catalog's
  Chinese-native public copy only.

**Negative (fail-closed by API shape AND runtime checks)**
* forbidden method absence — no fact mutation, severity change, Gate
  lower/override/skip, Agent④ verdict replacement, failure→completion
  relabel, DecisionRecord construction or ``可提交定稿`` assertion;
* constructor/object attribute inspection — repository/UoW/factory/reducer/
  storage/ledger handles cannot hide behind naming; the query façade is a
  narrow one-shot snapshot adapter; the raw service and mutable selections
  are rejected at construction;
* recursive retained-object-graph scan (cycle-safe, bounded) — the
  coordinator, the facade and every produced value cannot reach an
  ApplicationService / UnitOfWorkFactory / repository / reducer / storage
  adapter through bound-method ``__self__``, closure cells, partials,
  mappings or sequences; decoy tests prove the scanner is not vacuous;
* direct fact mutation is impossible; Gate observations are immutable and the
  vocabulary has no ``skipped`` result; GateSummary/ProgressSummary have no
  submission-ready capability.

All tests use an explicit shared-state in-memory UoW factory; product storage
is never routed to Memory.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import types
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

import pydantic
import pytest

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DecisionRecord,
    SideEffectKind,
    SkillDefinition,
    WorkflowRunStatus,
)
from app.protocol_workflow.application import (
    ApplicationService,
    CreateStudyDefinitionCommand,
    GetDecisionGraphQuery,
    GetStudyDefinitionQuery,
    GetWorkflowRunStatusQuery,
    study_definition_genesis_snapshot,
    study_definition_stream_id,
)
from app.protocol_workflow.agent5 import (
    Agent5Coordinator,
    Agent5QueryFacade,
    CoordinatorWorkPackage,
    DecisionRequestQueue,
    ExceptionCard,
    ExceptionCardPublicPayload,
    GateObservation,
    GateResult,
    GateSummary,
    GraphPin,
    PinnedSkill,
    ProgressSummary,
    RegistrySelection,
    RunManifest,
    TemplatePin,
    WorkPackageGraph,
    WorkPackageSpec,
)
from app.protocol_workflow.canonical import (
    DecisionEffectLedger,
    DecisionLedger,
    DecisionReducer,
    StudyDefinitionReducer,
    study_revision_hash,
)
from app.protocol_workflow.errors import (
    OWNER_PUBLIC_LABEL,
    ProtocolErrorCode,
    ProtocolErrorOwner,
    ProtocolWorkflowError,
    RecoveryAction,
)
from app.protocol_workflow.events.unit_of_work import EventSourcedUnitOfWork
from app.protocol_workflow.ports.artifacts import ArtifactStore
from app.protocol_workflow.ports.repositories import (
    CurrentAggregateRepository,
    DecisionGraphRecord,
    EventStreamRepository,
    ExecutionReservationRepository,
    InboxRepository,
    OutboxRepository,
    ReadModelRepository,
    RevisionCasRepository,
    WorkflowRunStatusRecord,
)
from app.protocol_workflow.ports.unit_of_work import UnitOfWork
from app.protocol_workflow.registries import load_skill_registry
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

_TEMPLATE_PIN = TemplatePin(template_version="template:v1", template_sha256="b" * 64)
_GRAPH_PIN = GraphPin(graph_version="graph:v1", graph_sha256="c" * 64)
_SOURCE_REVISIONS = ("d" * 64,)

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "config/medical_writing/protocol_v3/skill_registry.json"
)


# ---------------------------------------------------------------------------
# Shared-state memory adapter (clone of test_application_service._SharedState)
# ---------------------------------------------------------------------------


class _SharedState:
    """Shared repositories across single-use UoW instances."""

    def __init__(self) -> None:
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
        self.ev_repo = InMemoryEventStreamRepository()
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
        return self.new_uow


# ---------------------------------------------------------------------------
# Builders
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
        side_effect=None,
    )


def _service(state: _SharedState) -> ApplicationService:
    return ApplicationService(unit_of_work_factory=state.factory(), clock=lambda: _T0)


def _facade(state: _SharedState) -> Agent5QueryFacade:
    return Agent5QueryFacade(
        service=_service(state),
        project_id=_PROJECT,
        study_definition_id=_SD_ID,
        workflow_run_id=_RUN_ID,
    )


def _selection() -> RegistrySelection:
    document = load_skill_registry(_REGISTRY_PATH)
    return RegistrySelection(skills=document.skill_definitions())


def _coordinator(
    state: _SharedState | None = None,
    *,
    gate_observer=None,
) -> Agent5Coordinator:
    state = state if state is not None else _SharedState()
    return Agent5Coordinator(
        application=_facade(state),
        registry_selection=_selection(),
        gate_observer=gate_observer,
        clock=lambda: _T0,
    )


def _populated() -> Tuple[_SharedState, ApplicationService]:
    state = _SharedState()
    svc = _service(state)
    svc.create_study_definition(_create_command())
    return state, svc


def _pin(
    state: _SharedState,
    *,
    skills: Tuple[PinnedSkill, ...] | None = None,
) -> RunManifest:
    return _coordinator(state).pin_run_manifest(
        project_id=_PROJECT,
        workflow_run_id=_RUN_ID,
        protocol_template=_TEMPLATE_PIN,
        graph=_GRAPH_PIN,
        contract_schema_version="mw_protocol_v3_contract_v1",
        source_revision_hashes=_SOURCE_REVISIONS,
        study_definition_id=_SD_ID,
        skills=skills,
    )


def _run_manifest(
    *,
    skills: Tuple[PinnedSkill, ...] | None = None,
    source_revision_hashes: Tuple[str, ...] = _SOURCE_REVISIONS,
) -> RunManifest:
    """Direct RunManifest construction for lineage-focused tests."""
    return RunManifest(
        workflow_run_id=_RUN_ID,
        project_id=_PROJECT,
        protocol_template_version="template:v1",
        protocol_template_sha256="b" * 64,
        graph_version="graph:v1",
        graph_sha256="c" * 64,
        contract_schema_version="mw_protocol_v3_contract_v1",
        skills=skills if skills is not None else _selection().pinned(),
        source_revision_hashes=source_revision_hashes,
        study_definition_id=_SD_ID,
        study_definition_revision=1,
        study_definition_sha256="a" * 64,
        created_at=_T0,
    )


def _error() -> ProtocolWorkflowError:
    return ProtocolWorkflowError(
        code=ProtocolErrorCode.P1_REVISION_STALE,
        object_id=_SD_ID,
        owner=ProtocolErrorOwner.APPLICATION_SERVICE,
        retryable=True,
        attempt=2,
        audit_detail="backend log at /tmp/traceback.py:12 failed",
        audit_context={"event_id": "ev:1", "path": "/tmp/x", "attempt_log": "retry-2"},
    )


# ---------------------------------------------------------------------------
# Fingerprint helpers (read-only probes against the shared store)
# ---------------------------------------------------------------------------


def _aggregate_fp(state: _SharedState) -> Tuple[Any, ...]:
    current = state.sd_repo.get_current(_PROJECT, _SD_ID)
    if current is None:
        return (0, "", "", ())
    return (
        current.revision,
        study_revision_hash(current),
        current.material_sha256(),
        tuple(sorted(current.decision_record_ids)),
    )


def _event_fp(state: _SharedState) -> Tuple[Any, ...]:
    return tuple(state.ev_repo.read_events(_PROJECT, study_definition_stream_id(_SD_ID)))


def _outbox_fp(state: _SharedState) -> Tuple[Any, ...]:
    return tuple(
        sorted(
            (m.logical_key, m.payload_sha256, m.status.value, m.workflow_run_id)
            for m in state.ob_repo._messages.values()
            if m.project_id == _PROJECT
        )
    )


def _rm_fp(state: _SharedState) -> Tuple[Any, ...]:
    return (
        state.rm_repo.get_workflow_run_status(_PROJECT, _RUN_ID),
        state.rm_repo.get_decision_graph(_PROJECT, _SD_ID),
    )


def _store_fp(state: _SharedState) -> Tuple[Any, ...]:
    return (_aggregate_fp(state), _event_fp(state), _outbox_fp(state), _rm_fp(state))


def _seed_run_status(
    state: _SharedState,
    status: WorkflowRunStatus,
    *,
    display_progress: float = 0.4,
    journey_counter: int = 3,
) -> None:
    """Seed the workflow-run read-model inside an open UoW so the shared
    repository's mutation guard is open (mirrors a projector write)."""
    uow = state.new_uow()
    with uow:
        uow.read_model_repository.upsert_workflow_run_status(
            WorkflowRunStatusRecord(
                project_id=_PROJECT,
                workflow_run_id=_RUN_ID,
                status=status,
                display_progress=display_progress,
                journey_counter=journey_counter,
            )
        )


def _seed_decision_graph(
    state: _SharedState, records: Tuple[DecisionGraphRecord, ...]
) -> None:
    uow = state.new_uow()
    with uow:
        uow.read_model_repository.replace_decision_graph(_PROJECT, _SD_ID, records)


# ---------------------------------------------------------------------------
# Retained-object-graph authority scan (cycle-safe, bounded)
# ---------------------------------------------------------------------------
#
# A coordinator may only retain the narrow snapshot facade, the approved
# selection and typed callbacks.  This scanner walks the FULL retained graph —
# instance dicts, slots, bound-method ``__self__``, closure cells,
# ``functools.partial`` args/keywords, mapping keys/values and sequence items
# — with cycle protection (``id`` set) and hard depth/node bounds.  Class
# objects, modules and function ``__globals__`` are deliberately not descended
# into: they are shared program state, not instance-retained state.
#
# The decoy tests below prove the scanner is NOT vacuous: it must detect an
# ApplicationService hidden behind every one of those reference kinds.

_MAX_RETAINED_DEPTH = 16
_MAX_RETAINED_NODES = 4096

#: Concrete/port authority handles Agent⑤ must never retain: the application
#: service, unit-of-work (port + event-sourced helper), repositories, reducer
#: / ledger value objects, artifact store and the in-memory adapters.
_FORBIDDEN_HANDLE_TYPES = (
    ApplicationService,
    UnitOfWork,
    EventSourcedUnitOfWork,
    CurrentAggregateRepository,
    RevisionCasRepository,
    EventStreamRepository,
    OutboxRepository,
    InboxRepository,
    ExecutionReservationRepository,
    ReadModelRepository,
    ArtifactStore,
    StudyDefinitionReducer,
    DecisionReducer,
    DecisionEffectLedger,
    DecisionLedger,
    InMemoryUnitOfWork,
    InMemoryCurrentAggregateRepository,
    InMemoryRevisionCasRepository,
    InMemoryEventStreamRepository,
    InMemoryOutboxRepository,
    InMemoryInboxRepository,
    InMemoryExecutionReservationRepository,
    InMemoryReadModelRepository,
    InMemoryArtifactStore,
    _AggregateIndex,
)

#: Attribute names that would smuggle the injected UnitOfWorkFactory (a
#: non-runtime-checkable callable Protocol) onto a retained object.  Probed
#: only on callable members, so plain value objects never match.
_FACTORY_MEMBER_NAMES = (
    "_factory",
    "factory",
    "unit_of_work_factory",
    "new_uow",
    "uow_factory",
)


def _is_authority_handle(obj: Any) -> bool:
    if isinstance(obj, _FORBIDDEN_HANDLE_TYPES):
        return True
    if callable(obj) and not isinstance(obj, type):
        for name in _FACTORY_MEMBER_NAMES:
            member = getattr(obj, name, None)
            if callable(member):
                return True
    return False


def _slot_names(cls: type) -> Tuple[str, ...]:
    names: list[str] = []
    for klass in cls.__mro__:
        slots = getattr(klass, "__slots__", ())
        if isinstance(slots, str):
            slots = (slots,)
        for name in slots:
            if name in ("__dict__", "__weakref__") or name in names:
                continue
            names.append(name)
    return tuple(names)


def _referents(obj: Any) -> Iterator[Any]:
    """Direct object references of one retained value (bounded policy)."""
    if obj is None or isinstance(
        obj, (str, bytes, int, float, bool, complex, datetime)
    ):
        return
    if isinstance(obj, types.MethodType):
        yield obj.__self__
        return
    if isinstance(obj, functools.partial):
        yield obj.func
        yield from obj.args
        yield from obj.keywords.values()
        return
    if isinstance(obj, types.FunctionType):
        if obj.__closure__ is not None:
            for cell in obj.__closure__:
                contents = cell.cell_contents
                if contents is not None:
                    yield contents
        return
    if isinstance(obj, Mapping):
        yield from obj.keys()
        yield from obj.values()
        return
    if isinstance(obj, (tuple, list, set, frozenset)):
        yield from obj
        return
    if isinstance(obj, type):
        return
    instance_dict = getattr(obj, "__dict__", None)
    if isinstance(instance_dict, dict):
        yield from instance_dict.values()
    for name in _slot_names(type(obj)):
        try:
            value = getattr(obj, name)
        except AttributeError:
            continue
        if value is not None:
            yield value


def _collect_authority_handles(root: Any) -> list[Any]:
    """DFS over the retained graph; returns every authority handle found."""
    found: list[Any] = []
    seen: set[int] = set()
    stack: list[Tuple[Any, int]] = [(root, 0)]
    nodes = 0
    while stack and nodes < _MAX_RETAINED_NODES:
        current, depth = stack.pop()
        nodes += 1
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        if _is_authority_handle(current):
            found.append(current)
            continue  # a handle's internals are already classified
        if depth >= _MAX_RETAINED_DEPTH:
            continue
        for ref in _referents(current):
            if ref is None or id(ref) in seen:
                continue
            stack.append((ref, depth + 1))
    return found


def _closure_holding(value: Any) -> Any:
    """Return a function whose closure cell retains ``value``."""

    def _hidden() -> Any:
        return value

    return _hidden


# ---------------------------------------------------------------------------
# Tests — registry selection (immutable, closed, pinned)
# ---------------------------------------------------------------------------


class TestRegistrySelection:
    def test_selection_is_closed_pinned_and_immutable(self) -> None:
        selection = _selection()
        assert selection.model_config.get("frozen") is True
        assert selection.model_config.get("extra") == "forbid"
        pinned = selection.pinned()
        ids = [pin.skill_definition_id for pin in pinned]
        assert len(ids) == len(set(ids))
        for pin in pinned:
            skill = selection.skill_by_id(pin.skill_definition_id)
            assert skill is not None
            assert pin.skill_sha256 == skill.material_sha256()
        # deterministic: pinned() is ID-sorted
        assert ids == sorted(ids)

    def test_selection_rejects_mutable_list(self) -> None:
        skills = _selection().skills
        with pytest.raises(pydantic.ValidationError, match="immutable tuple"):
            RegistrySelection(skills=list(skills))

    def test_selection_rejects_unpinned_dict_entries(self) -> None:
        with pytest.raises(pydantic.ValidationError):
            RegistrySelection(skills=({"skill_definition_id": "skill.x"},))

    def test_selection_rejects_non_frozen_skill(self) -> None:
        unapproved = SkillDefinition(
            skill_definition_id="skill.unapproved",
            skill_version="1.0.0",
            agent_role="coordinator",
            input_schema_ref="in",
            output_schema_ref="out",
            evidence_requirements=("evidence",),
            acceptance_test_ids=("test:1",),
            canonical_state=CanonicalState.CONFIRMED,
        )
        with pytest.raises(pydantic.ValidationError, match="not FROZEN"):
            RegistrySelection(skills=(unapproved,))

    def test_selection_rejects_duplicate_skill_ids(self) -> None:
        skills = _selection().skills
        with pytest.raises(pydantic.ValidationError, match="duplicate"):
            RegistrySelection(skills=(skills[0], skills[0]))


# ---------------------------------------------------------------------------
# Tests — run manifest pinning
# ---------------------------------------------------------------------------


class TestRunManifestPinning:
    def test_pin_records_approved_versions_only(self) -> None:
        state, _svc = _populated()
        manifest = _pin(state)
        assert manifest.project_id == _PROJECT
        assert manifest.workflow_run_id == _RUN_ID
        assert manifest.protocol_template_version == "template:v1"
        assert manifest.protocol_template_sha256 == _TEMPLATE_PIN.template_sha256
        assert manifest.graph_version == "graph:v1"
        assert manifest.graph_sha256 == _GRAPH_PIN.graph_sha256
        assert manifest.contract_schema_version == "mw_protocol_v3_contract_v1"
        assert manifest.source_revision_hashes == _SOURCE_REVISIONS
        assert manifest.study_definition_id == _SD_ID
        assert manifest.study_definition_revision == 1
        # StudyDefinition hash comes from the approved aggregate, not Agent⑤
        current = state.sd_repo.get_current(_PROJECT, _SD_ID)
        assert manifest.study_definition_sha256 == study_revision_hash(current)
        # skills are exactly the approved selection, ID-sorted
        assert manifest.skills == _selection().pinned()

    def test_pin_is_deterministic(self) -> None:
        state, _svc = _populated()
        first = _pin(state)
        second = _pin(state)
        assert first == second
        assert first.content_sha256() == second.content_sha256()
        assert len(first.content_sha256()) == 64

    def test_pin_rejects_unknown_skill(self) -> None:
        state, _svc = _populated()
        with pytest.raises(ValueError, match="unknown skill"):
            _pin(
                state,
                skills=(
                    PinnedSkill(
                        skill_definition_id="skill.not-registered",
                        skill_sha256="e" * 64,
                    ),
                ),
            )

    def test_pin_rejects_skill_hash_mismatch(self) -> None:
        state, _svc = _populated()
        selection = _selection()
        real_id = selection.skills[0].skill_definition_id
        with pytest.raises(ValueError, match="hash mismatch"):
            _pin(
                state,
                skills=(PinnedSkill(skill_definition_id=real_id, skill_sha256="f" * 64),),
            )

    def test_pin_rejects_missing_study_definition(self) -> None:
        state = _SharedState()
        coordinator = _coordinator(state)
        with pytest.raises(ValueError, match="not available"):
            coordinator.pin_run_manifest(
                project_id=_PROJECT,
                workflow_run_id=_RUN_ID,
                protocol_template=_TEMPLATE_PIN,
                graph=_GRAPH_PIN,
                contract_schema_version="mw_protocol_v3_contract_v1",
                source_revision_hashes=_SOURCE_REVISIONS,
                study_definition_id=_SD_ID,
            )

    def test_pin_rejects_mutable_collections(self) -> None:
        state, _svc = _populated()
        coordinator = _coordinator(state)
        with pytest.raises(TypeError, match="immutable tuple"):
            coordinator.pin_run_manifest(
                project_id=_PROJECT,
                workflow_run_id=_RUN_ID,
                protocol_template=_TEMPLATE_PIN,
                graph=_GRAPH_PIN,
                contract_schema_version="mw_protocol_v3_contract_v1",
                source_revision_hashes=[_SOURCE_REVISIONS[0]],
                study_definition_id=_SD_ID,
            )

    def test_manifest_rejects_duplicate_skill_ids(self) -> None:
        state, _svc = _populated()
        selection = _selection()
        pins = (selection.pinned()[0], selection.pinned()[0])
        with pytest.raises(pydantic.ValidationError, match="duplicate"):
            RunManifest(
                workflow_run_id=_RUN_ID,
                project_id=_PROJECT,
                protocol_template_version="template:v1",
                protocol_template_sha256="b" * 64,
                graph_version="graph:v1",
                graph_sha256="c" * 64,
                contract_schema_version="mw_protocol_v3_contract_v1",
                skills=pins,
                source_revision_hashes=_SOURCE_REVISIONS,
                study_definition_id=_SD_ID,
                study_definition_revision=1,
                study_definition_sha256="a" * 64,
                created_at=_T0,
            )


# ---------------------------------------------------------------------------
# Tests — pinned source revision lineage (mirrors canonical WorkflowRun)
# ---------------------------------------------------------------------------


class TestSourceRevisionLineage:
    def test_single_source_revision_accepted(self) -> None:
        manifest = _run_manifest(source_revision_hashes=(_SOURCE_REVISIONS[0],))
        assert manifest.source_revision_hashes == (_SOURCE_REVISIONS[0],)
        assert len(manifest.content_sha256()) == 64

    def test_multiple_unique_source_revisions_accepted(self) -> None:
        hashes = ("d" * 64, "e" * 64)
        manifest = _run_manifest(source_revision_hashes=hashes)
        assert manifest.source_revision_hashes == hashes
        # deterministic content hash unchanged by the new constraint
        assert manifest.content_sha256() == _run_manifest(
            source_revision_hashes=hashes
        ).content_sha256()

    def test_empty_source_revision_lineage_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="at least 1 item"):
            _run_manifest(source_revision_hashes=())

    def test_duplicate_source_revisions_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="duplicate"):
            _run_manifest(
                source_revision_hashes=(_SOURCE_REVISIONS[0], _SOURCE_REVISIONS[0])
            )

    def test_mutable_source_revision_sequence_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="immutable tuple"):
            _run_manifest(source_revision_hashes=[_SOURCE_REVISIONS[0]])

    def test_coordinator_pin_fails_closed_on_empty_lineage(self) -> None:
        """An empty source lineage never yields a manifest through the
        coordinator pin path."""
        state, _svc = _populated()
        with pytest.raises(pydantic.ValidationError, match="at least 1 item"):
            _coordinator(state).pin_run_manifest(
                project_id=_PROJECT,
                workflow_run_id=_RUN_ID,
                protocol_template=_TEMPLATE_PIN,
                graph=_GRAPH_PIN,
                contract_schema_version="mw_protocol_v3_contract_v1",
                source_revision_hashes=(),
                study_definition_id=_SD_ID,
            )


# ---------------------------------------------------------------------------
# Tests — deterministic work decomposition
# ---------------------------------------------------------------------------


def _packages() -> Tuple[WorkPackageSpec, ...]:
    return (
        WorkPackageSpec(
            work_package_id="wp:3",
            skill_definition_id="skill.workflow-coordination",
            depends_on=("wp:1", "wp:2"),
        ),
        WorkPackageSpec(
            work_package_id="wp:2",
            skill_definition_id="skill.source-acquisition-plan",
            depends_on=("wp:1",),
        ),
        WorkPackageSpec(
            work_package_id="wp:1",
            skill_definition_id="skill.workflow-coordination",
        ),
    )


class TestWorkPackageDecomposition:
    def test_deterministic_dependency_order(self) -> None:
        coordinator = _coordinator()
        packages = _packages()
        orders = set()
        for permutation in (packages, packages[::-1], (packages[1], packages[0], packages[2])):
            graph = coordinator.decompose_coordinator_work(packages=permutation)
            orders.add(graph.ordered_package_ids())
        assert len(orders) == 1
        assert orders.pop() == ("wp:1", "wp:2", "wp:3")
        # dependencies always precede dependents and skills are pinned
        graph = coordinator.decompose_coordinator_work(packages=packages)
        ordered = graph.ordered_packages()
        assert [p.work_package_id for p in ordered] == ["wp:1", "wp:2", "wp:3"]
        selection = _selection()
        assert ordered[2].skill_sha256 == selection.skill_hash("skill.workflow-coordination")
        assert ordered[1].skill_sha256 == selection.skill_hash("skill.source-acquisition-plan")

    def test_decompose_rejects_unknown_skill(self) -> None:
        coordinator = _coordinator()
        with pytest.raises(ValueError, match="unknown or unregistered skill"):
            coordinator.decompose_coordinator_work(
                packages=(
                    WorkPackageSpec(
                        work_package_id="wp:1",
                        skill_definition_id="skill.not-registered",
                    ),
                )
            )

    def test_decompose_rejects_duplicate_package_ids(self) -> None:
        coordinator = _coordinator()
        with pytest.raises(ValueError, match="duplicate"):
            coordinator.decompose_coordinator_work(
                packages=(
                    WorkPackageSpec(
                        work_package_id="wp:1",
                        skill_definition_id="skill.workflow-coordination",
                    ),
                    WorkPackageSpec(
                        work_package_id="wp:1",
                        skill_definition_id="skill.workflow-coordination",
                    ),
                )
            )

    def test_decompose_rejects_dependency_cycle(self) -> None:
        coordinator = _coordinator()
        with pytest.raises(ValueError, match="cycle"):
            coordinator.decompose_coordinator_work(
                packages=(
                    WorkPackageSpec(
                        work_package_id="wp:1",
                        skill_definition_id="skill.workflow-coordination",
                        depends_on=("wp:2",),
                    ),
                    WorkPackageSpec(
                        work_package_id="wp:2",
                        skill_definition_id="skill.workflow-coordination",
                        depends_on=("wp:1",),
                    ),
                )
            )

    def test_decompose_rejects_missing_dependency(self) -> None:
        coordinator = _coordinator()
        with pytest.raises(ValueError, match="unknown"):
            coordinator.decompose_coordinator_work(
                packages=(
                    WorkPackageSpec(
                        work_package_id="wp:1",
                        skill_definition_id="skill.workflow-coordination",
                        depends_on=("wp:missing",),
                    ),
                )
            )

    def test_decompose_rejects_empty_and_mutable_inputs(self) -> None:
        coordinator = _coordinator()
        with pytest.raises(ValueError, match="must not be empty"):
            coordinator.decompose_coordinator_work(packages=())
        with pytest.raises(TypeError, match="immutable tuple"):
            coordinator.decompose_coordinator_work(packages=[_packages()[0]])

    def test_self_dependency_rejected(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="depend on itself"):
            WorkPackageSpec(
                work_package_id="wp:1",
                skill_definition_id="skill.workflow-coordination",
                depends_on=("wp:1",),
            )


# ---------------------------------------------------------------------------
# Tests — read-only aggregation
# ---------------------------------------------------------------------------


class TestReadOnlyAggregation:
    def test_progress_reflects_run_status_verbatim(self) -> None:
        for status in (
            WorkflowRunStatus.CREATED,
            WorkflowRunStatus.RUNNING,
            WorkflowRunStatus.FAILED,
            WorkflowRunStatus.INTERRUPTED,
            WorkflowRunStatus.QUARANTINED,
            WorkflowRunStatus.COMPLETED,
        ):
            state, _svc = _populated()
            _seed_run_status(state, status)
            summary = _coordinator(state).aggregate_progress(
                project_id=_PROJECT, workflow_run_id=_RUN_ID, study_definition_id=_SD_ID
            )
            assert summary.run_status is status
            assert summary.display_progress == 0.4
            assert summary.journey_counter == 3
            assert summary.study_definition_id == _SD_ID
            assert summary.study_definition_revision == 1
            # no derived completed/submission flag exists
            assert "completed" not in ProgressSummary.model_fields
            assert "submission" not in "".join(ProgressSummary.model_fields).casefold()

    def test_aggregation_leaves_store_unchanged(self) -> None:
        state, _svc = _populated()
        _seed_run_status(state, WorkflowRunStatus.RUNNING, display_progress=0.5, journey_counter=1)
        _seed_decision_graph(
            state,
            (
                DecisionGraphRecord(
                    project_id=_PROJECT,
                    decision_key="decision:arm",
                    decision_record_id=None,
                    state_revision=None,
                    selected_option_id=None,
                    canonical_state=None,
                ),
            ),
        )
        coordinator = _coordinator(
            state,
            gate_observer=lambda: (
                GateObservation(
                    gate_id="gate:p1:g1",
                    gate_phase="P1",
                    result=GateResult.PASSED,
                    observed_at=_T0,
                    observed_by="verifier:1",
                ),
            ),
        )
        before = _store_fp(state)
        coordinator.aggregate_progress(
            project_id=_PROJECT, workflow_run_id=_RUN_ID, study_definition_id=_SD_ID
        )
        coordinator.aggregate_gates(project_id=_PROJECT, workflow_run_id=_RUN_ID)
        coordinator.build_decision_request_queue(
            project_id=_PROJECT, study_definition_id=_SD_ID
        )
        assert _store_fp(state) == before

    def test_gate_summary_deterministic_and_read_only(self) -> None:
        late = GateObservation(
            gate_id="gate:q1:g1",
            gate_phase="Q1",
            result=GateResult.FAILED,
            observed_at=_T0,
            observed_by="verifier:1",
        )
        early = GateObservation(
            gate_id="gate:p1:g1",
            gate_phase="P1",
            result=GateResult.PASSED,
            observed_at=_T0,
            observed_by="verifier:1",
        )
        # reversed input order must not change the summary
        coordinator = _coordinator(gate_observer=lambda: (late, early))
        summary = coordinator.aggregate_gates(project_id=_PROJECT, workflow_run_id=_RUN_ID)
        assert [o.gate_id for o in summary.observations] == ["gate:p1:g1", "gate:q1:g1"]
        assert summary.result_by_gate() == {
            "gate:p1:g1": GateResult.PASSED,
            "gate:q1:g1": GateResult.FAILED,
        }
        assert "submission_ready" not in GateSummary.model_fields

    def test_gate_summary_empty_without_observer(self) -> None:
        summary = _coordinator().aggregate_gates(project_id=_PROJECT, workflow_run_id=_RUN_ID)
        assert summary.observations == ()

    def test_gate_observer_must_return_typed_values(self) -> None:
        coordinator = _coordinator(gate_observer=lambda: ("not-an-observation",))
        with pytest.raises(TypeError, match="GateObservation"):
            coordinator.aggregate_gates(project_id=_PROJECT, workflow_run_id=_RUN_ID)

    def test_decision_request_queue_contains_only_unresolved(self) -> None:
        state, _svc = _populated()
        _seed_decision_graph(
            state,
            (
                DecisionGraphRecord(
                    project_id=_PROJECT,
                    decision_key="decision:dose",
                    decision_record_id="dr:1",
                    state_revision=1,
                    selected_option_id="opt:1",
                    canonical_state=CanonicalState.CONFIRMED,
                ),
                DecisionGraphRecord(
                    project_id=_PROJECT,
                    decision_key="decision:arm",
                    decision_record_id=None,
                    state_revision=None,
                    selected_option_id=None,
                    canonical_state=None,
                ),
                DecisionGraphRecord(
                    project_id=_PROJECT,
                    decision_key="decision:blinded",
                    decision_record_id=None,
                    state_revision=None,
                    selected_option_id=None,
                    canonical_state=CanonicalState.PROPOSED,
                ),
            ),
        )
        queue = _coordinator(state).build_decision_request_queue(
            project_id=_PROJECT, study_definition_id=_SD_ID
        )
        assert queue.study_definition_id == _SD_ID
        assert [r.decision_key for r in queue.requests] == ["decision:arm", "decision:blinded"]
        assert all(r.decision_record_id is None for r in queue.requests)
        assert "decision:dose" not in [r.decision_key for r in queue.requests]


# ---------------------------------------------------------------------------
# Tests — exception cards (strict public/audit separation)
# ---------------------------------------------------------------------------


class TestExceptionCards:
    def test_public_payload_uses_catalog_copy_only(self) -> None:
        error = _error()
        card = _coordinator().to_exception_card(error, card_id="card:test:1")
        public = card.public.model_dump()
        definition = error.definition
        assert set(public) == {"message", "responsible_area", "can_retry", "next_step"}
        assert public["message"] == definition.public_message
        assert public["responsible_area"] == OWNER_PUBLIC_LABEL[error.owner]
        assert public["can_retry"] is definition.retryable
        assert public["next_step"] == definition.public_next_step

    def test_audit_payload_carries_machine_fields_only(self) -> None:
        error = _error()
        card = _coordinator().to_exception_card(error, card_id="card:test:2")
        audit = card.audit.model_dump()
        assert set(audit) == {
            "error_code",
            "phase",
            "object_id",
            "owner",
            "retryable",
            "recovery_action",
            "attempt",
            "audit_detail",
            "audit_context",
        }
        assert audit["error_code"] == ProtocolErrorCode.P1_REVISION_STALE.value
        assert audit["phase"] == 1
        assert audit["object_id"] == _SD_ID
        assert audit["owner"] == ProtocolErrorOwner.APPLICATION_SERVICE.value
        assert audit["recovery_action"] == RecoveryAction.REFRESH_STALE_REVISION.value
        assert audit["attempt"] == 2
        assert "traceback" in audit["audit_detail"]
        assert audit["audit_context"]["path"] == "/tmp/x"

    def test_public_payload_never_leaks_audit_content(self) -> None:
        card = _coordinator().to_exception_card(_error(), card_id="card:test:3")
        forbidden = ("mw-pro-", "traceback", "backend", "log", "门", "信号", "/", "\\")
        for field_name, value in card.public.model_dump().items():
            lowered = str(value).casefold()
            for token in forbidden:
                assert token not in lowered, (field_name, token, value)

    def test_public_payload_rejects_internal_wording(self) -> None:
        with pytest.raises(pydantic.ValidationError, match="internal implementation wording"):
            ExceptionCardPublicPayload(
                message="方案生成失败，请查看日志",  # 日志 (log) is forbidden
                responsible_area="方案统筹",
                can_retry=True,
                next_step="请稍后重试",
            )
        with pytest.raises(pydantic.ValidationError, match="internal implementation wording"):
            ExceptionCardPublicPayload(
                message="四层门尚未通过",  # 门 is forbidden
                responsible_area="方案统筹",
                can_retry=False,
                next_step="请完成相关核对",
            )
        with pytest.raises(pydantic.ValidationError, match="internal implementation wording"):
            ExceptionCardPublicPayload(
                message="写入路径 a/b 失败",  # raw path separator is forbidden
                responsible_area="方案统筹",
                can_retry=True,
                next_step="请稍后重试",
            )

    def test_card_is_immutable_and_closed(self) -> None:
        card = _coordinator().to_exception_card(_error(), card_id="card:test:4")
        assert card.model_config.get("frozen") is True
        assert card.model_config.get("extra") == "forbid"
        with pytest.raises(pydantic.ValidationError):
            card.audit = card.audit  # type: ignore[assignment]

    def test_to_exception_card_rejects_non_protocol_error(self) -> None:
        with pytest.raises(TypeError, match="ProtocolWorkflowError"):
            _coordinator().to_exception_card(
                RuntimeError("boom"), card_id="card:test:5"
            )


# ---------------------------------------------------------------------------
# Tests — authority boundary (fail-closed by API shape and runtime checks)
# ---------------------------------------------------------------------------

_FORBIDDEN_METHOD_NAMES = (
    # direct fact / StudyDefinition mutation
    "create_study_definition",
    "apply_decision",
    "mutate_facts",
    "update_facts",
    "patch_facts",
    "set_facts",
    # severity
    "change_severity",
    "set_severity",
    "raise_severity",
    # Gate lower / override / skip
    "lower_gate",
    "override_gate",
    "skip_gate",
    "pass_gate",
    "fail_gate",
    "change_gate_result",
    # Agent④ verdict replacement
    "replace_qc_verdict",
    "replace_agent4_verdict",
    "set_qc_clean_verdict",
    "overwrite_qc_verdict",
    # failure -> completion relabel
    "mark_completed",
    "mark_complete",
    "relabel_completed",
    "relabel_failed",
    "set_run_status",
    "set_progress",
    # independent 可提交定稿 assertion
    "assert_submission_ready",
    "mark_submission_ready",
    "approve_submission",
    "prepare_submission",
    "freeze_submission",
    # unowned DecisionRecord construction
    "create_decision_record",
    "build_decision_record",
    "make_decision_record",
    # storage / persistence access
    "open_unit_of_work",
    "commit",
    "rollback",
    "save",
    "flush",
)

_FORBIDDEN_ATTRIBUTE_TOKENS = (
    "unit_of_work",
    "uow",
    "repositor",
    "reducer",
    "storage",
    "cas",
    "ledger",
    "artifact_store",
    "event_stream",
    "factory",
    "denominator",
    "severity",
)


class TestAuthorityBoundary:
    def test_coordinator_exposes_no_forbidden_mutation_capabilities(self) -> None:
        coordinator = _coordinator()
        for name in _FORBIDDEN_METHOD_NAMES:
            assert not hasattr(coordinator, name), name
            with pytest.raises(AttributeError):
                getattr(coordinator, name)

    def test_coordinator_attributes_have_no_authority_handles(self) -> None:
        coordinator = _coordinator()
        attribute_names = set(vars(coordinator))
        for name in attribute_names:
            lowered = name.casefold()
            for token in _FORBIDDEN_ATTRIBUTE_TOKENS:
                assert token not in lowered, name
        # the only stored dependencies are the narrow facade, the approved
        # selection, the typed observer and the clock
        assert attribute_names == {
            "_application",
            "_registry_selection",
            "_gate_observer",
            "_clock",
        }

    def test_query_facade_is_narrow(self) -> None:
        facade = _facade(_SharedState())
        # slots-only: no __dict__ to smuggle handles into
        assert not hasattr(facade, "__dict__")
        for name in dir(facade):
            assert "create_study_definition" not in name
            assert "apply_decision" not in name
        for forbidden in ("unit_of_work_factory", "repositories", "uow", "factory"):
            assert not hasattr(facade, forbidden), forbidden
        with pytest.raises(AttributeError):
            facade.apply_decision  # noqa: B018
        with pytest.raises(AttributeError):
            facade.create_study_definition  # noqa: B018
        # the facade retains only frozen snapshot values — never callables or
        # bound service methods (the retained-graph scan proves no handle is
        # reachable from those values either)
        for slot in (
            "_study_definition",
            "_event_summary",
            "_decision_graph",
            "_workflow_run_status",
        ):
            value = getattr(facade, slot)
            assert not callable(value)
            assert _collect_authority_handles(value) == []

    def test_facade_rejects_foreign_identity_queries(self) -> None:
        state, _svc = _populated()
        facade = _facade(state)
        with pytest.raises(ValueError, match="does not match the captured snapshot"):
            facade.get_study_definition(
                GetStudyDefinitionQuery(
                    project_id=_OTHER_PROJECT, study_definition_id=_SD_ID
                )
            )
        with pytest.raises(ValueError, match="does not match the captured snapshot"):
            facade.get_workflow_run_status(
                GetWorkflowRunStatusQuery(
                    project_id=_PROJECT, workflow_run_id="wr:other:1"
                )
            )

    def test_coordinator_rejects_raw_service_and_mutable_inputs(self) -> None:
        state = _SharedState()
        svc = _service(state)
        selection = _selection()
        with pytest.raises(TypeError, match="Agent5QueryFacade"):
            Agent5Coordinator(application=svc, registry_selection=selection)
        with pytest.raises(TypeError, match="RegistrySelection"):
            Agent5Coordinator(
                application=_facade(state), registry_selection={"skills": ()}
            )
        with pytest.raises(TypeError, match="callable"):
            Agent5Coordinator(
                application=_facade(state),
                registry_selection=selection,
                gate_observer="not-callable",
            )

    def test_direct_fact_mutation_impossible(self) -> None:
        state, _svc = _populated()
        facade = _facade(state)
        result = facade.get_study_definition(
            GetStudyDefinitionQuery(project_id=_PROJECT, study_definition_id=_SD_ID)
        )
        assert result.definition is not None
        with pytest.raises(TypeError):
            result.definition.facts["new"] = 1  # type: ignore[index]
        # the run manifest and other Agent⑤ results never expose facts
        manifest = _pin(state)
        assert not hasattr(manifest, "facts")
        summary = _coordinator(state).aggregate_progress(
            project_id=_PROJECT, workflow_run_id=_RUN_ID, study_definition_id=_SD_ID
        )
        assert not hasattr(summary, "facts")

    def test_gate_observation_immutable_and_has_no_skip_vocabulary(self) -> None:
        assert {member.value for member in GateResult} == {
            "passed",
            "failed",
            "blocked",
            "pending",
        }
        observation = GateObservation(
            gate_id="gate:p1:g1",
            gate_phase="P1",
            result=GateResult.FAILED,
            observed_at=_T0,
            observed_by="verifier:1",
        )
        with pytest.raises(pydantic.ValidationError):
            observation.result = GateResult.PASSED  # type: ignore[assignment]

    def test_no_submission_ready_capability_anywhere(self) -> None:
        coordinator = _coordinator()
        for name in ("assert_submission_ready", "mark_submission_ready", "approve_submission"):
            assert not hasattr(coordinator, name)
        gate_summary = GateSummary(project_id=_PROJECT, workflow_run_id=_RUN_ID)
        assert "submission_ready" not in GateSummary.model_fields
        progress = ProgressSummary(project_id=_PROJECT, workflow_run_id=_RUN_ID)
        assert "completed" not in ProgressSummary.model_fields
        assert "submission" not in "".join(ProgressSummary.model_fields).casefold()

    def test_no_decision_record_construction_path(self) -> None:
        coordinator = _coordinator()
        for name in dir(coordinator):
            assert "decision_record" not in name.casefold(), name
        for name in dir(coordinator.application):
            assert "decision_record" not in name.casefold(), name
        # coordinator results never carry a DecisionRecord
        queue = coordinator.build_decision_request_queue(
            project_id=_PROJECT, study_definition_id=_SD_ID
        )
        for request in queue.requests:
            assert not isinstance(request, DecisionRecord)

    def test_value_objects_are_frozen_and_closed(self) -> None:
        selection = _selection()
        skill = selection.skills[0]
        instances = [
            selection,
            PinnedSkill(
                skill_definition_id=skill.skill_definition_id,
                skill_sha256=skill.material_sha256(),
            ),
            _TEMPLATE_PIN,
            _GRAPH_PIN,
            RunManifest(
                workflow_run_id=_RUN_ID,
                project_id=_PROJECT,
                protocol_template_version="template:v1",
                protocol_template_sha256="b" * 64,
                graph_version="graph:v1",
                graph_sha256="c" * 64,
                contract_schema_version="mw_protocol_v3_contract_v1",
                skills=selection.pinned(),
                source_revision_hashes=_SOURCE_REVISIONS,
                study_definition_id=_SD_ID,
                study_definition_revision=1,
                study_definition_sha256="a" * 64,
                created_at=_T0,
            ),
            WorkPackageSpec(
                work_package_id="wp:1",
                skill_definition_id=skill.skill_definition_id,
            ),
            CoordinatorWorkPackage(
                work_package_id="wp:1",
                skill_definition_id=skill.skill_definition_id,
                skill_sha256=skill.material_sha256(),
                input_schema_ref=skill.input_schema_ref,
                output_schema_ref=skill.output_schema_ref,
            ),
            WorkPackageGraph(
                packages=(
                    CoordinatorWorkPackage(
                        work_package_id="wp:1",
                        skill_definition_id=skill.skill_definition_id,
                        skill_sha256=skill.material_sha256(),
                        input_schema_ref=skill.input_schema_ref,
                        output_schema_ref=skill.output_schema_ref,
                    ),
                )
            ),
            GateObservation(
                gate_id="gate:p1:g1",
                gate_phase="P1",
                result=GateResult.PENDING,
                observed_at=_T0,
                observed_by="verifier:1",
            ),
            GateSummary(project_id=_PROJECT, workflow_run_id=_RUN_ID),
            ProgressSummary(project_id=_PROJECT, workflow_run_id=_RUN_ID),
            DecisionRequestQueue(project_id=_PROJECT, study_definition_id=_SD_ID),
            _coordinator().to_exception_card(_error(), card_id="card:test:9"),
        ]
        for instance in instances:
            assert instance.model_config.get("frozen") is True, type(instance).__name__
            assert instance.model_config.get("extra") == "forbid", type(instance).__name__
            field_name = next(iter(type(instance).model_fields))
            with pytest.raises(pydantic.ValidationError):
                setattr(instance, field_name, getattr(instance, field_name))


# ---------------------------------------------------------------------------
# Tests — recursive retained-object-graph authority (cycle-safe, bounded)
# ---------------------------------------------------------------------------


class TestRetainedGraphAuthority:
    """The coordinator and every object it retains must never reach an
    ApplicationService, UnitOfWorkFactory, repository, reducer or storage
    adapter — even hidden behind bound-method ``__self__``, closure cells,
    partials, mappings or sequences.

    The decoy tests prove the scanner is not vacuous: each reference kind is
    seeded with a live ApplicationService and MUST be detected.  The old
    bound-method facade implementation fails ``test_*_retained_graph_*``
    because its slots retained ``service.get_*`` bound methods whose
    ``__self__`` is the service.
    """

    def test_coordinator_retained_graph_has_no_authority_handles(self) -> None:
        state, _svc = _populated()
        _seed_run_status(state, WorkflowRunStatus.RUNNING)
        coordinator = _coordinator(state, gate_observer=lambda: ())
        assert _collect_authority_handles(coordinator) == []

    def test_facade_retained_graph_has_no_authority_handles(self) -> None:
        state, _svc = _populated()
        facade = _facade(state)
        assert _collect_authority_handles(facade) == []
        # each captured snapshot value is itself handle-free
        for slot in (
            "_study_definition",
            "_event_summary",
            "_decision_graph",
            "_workflow_run_status",
        ):
            assert _collect_authority_handles(getattr(facade, slot)) == []

    def test_retained_graph_of_run_results_has_no_authority_handles(self) -> None:
        state, _svc = _populated()
        _seed_run_status(state, WorkflowRunStatus.QUARANTINED)
        coordinator = _coordinator(
            state,
            gate_observer=lambda: (
                GateObservation(
                    gate_id="gate:p1:g1",
                    gate_phase="P1",
                    result=GateResult.BLOCKED,
                    observed_at=_T0,
                    observed_by="verifier:1",
                ),
            ),
        )
        manifest = coordinator.pin_run_manifest(
            project_id=_PROJECT,
            workflow_run_id=_RUN_ID,
            protocol_template=_TEMPLATE_PIN,
            graph=_GRAPH_PIN,
            contract_schema_version="mw_protocol_v3_contract_v1",
            source_revision_hashes=_SOURCE_REVISIONS,
            study_definition_id=_SD_ID,
        )
        results = (
            manifest,
            coordinator.decompose_coordinator_work(packages=_packages()),
            coordinator.aggregate_progress(
                project_id=_PROJECT,
                workflow_run_id=_RUN_ID,
                study_definition_id=_SD_ID,
            ),
            coordinator.aggregate_gates(project_id=_PROJECT, workflow_run_id=_RUN_ID),
            coordinator.build_decision_request_queue(
                project_id=_PROJECT, study_definition_id=_SD_ID
            ),
            coordinator.to_exception_card(_error(), card_id="card:retained:1"),
        )
        for result in results:
            assert _collect_authority_handles(result) == [], type(result).__name__

    def test_scanner_detects_service_behind_bound_method(self) -> None:
        svc = _service(_SharedState())
        found = _collect_authority_handles(svc.get_study_definition)
        assert any(isinstance(obj, ApplicationService) for obj in found)

    def test_scanner_detects_service_behind_partial(self) -> None:
        svc = _service(_SharedState())
        found = _collect_authority_handles(functools.partial(svc.get_study_definition))
        assert any(isinstance(obj, ApplicationService) for obj in found)

    def test_scanner_detects_service_behind_closure_cell(self) -> None:
        svc = _service(_SharedState())
        found = _collect_authority_handles(_closure_holding(svc))
        assert any(isinstance(obj, ApplicationService) for obj in found)

    def test_scanner_detects_service_behind_mapping_and_sequence(self) -> None:
        svc = _service(_SharedState())
        for decoy in (
            {"hidden": svc},
            (svc,),
            [svc],
            {"nested": {"deeper": (svc,)}},
        ):
            found = _collect_authority_handles(decoy)
            assert any(isinstance(obj, ApplicationService) for obj in found), (
                type(decoy).__name__
            )

    def test_scanner_handles_cycles(self) -> None:
        node: Dict[str, Any] = {}
        node["self"] = node
        node["svc"] = _service(_SharedState())
        found = _collect_authority_handles(node)
        assert any(isinstance(obj, ApplicationService) for obj in found)
