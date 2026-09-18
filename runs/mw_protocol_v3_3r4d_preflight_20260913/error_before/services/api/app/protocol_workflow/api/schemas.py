"""Closed request/response schemas for the Protocol v3 API skeleton (Task 1.9).

Design authority: Protocol v3 multi-agent rearchitecture design sections 5.1
(authority boundary), 5.4 (Agent⑤ coordination boundary), 17.2 (only the
application service opens a unit of work), 18 (error handling) and the frozen
plan Task 1.9.

Every schema in this module is closed (``extra="forbid"``) and mirrors the
accepted canonical value objects and application/Agent⑤ result types without
exposing repositories, unit-of-work handles, storage adapters or audit-only
fields:

* mutation request bodies carry project/revision/idempotency/actor/reason and
  the full immutable :class:`DecisionRecord` — the same envelope the typed
  application commands require;
* query/aggregation responses expose only business-shaped values;
* there is deliberately NO client-supplied exception-card endpoint: a client
  must never invent a catalog failure.  Real :class:`ProtocolWorkflowError`
  failures cross the HTTP boundary only through the catalog's Chinese-native
  public copy (message / responsible area / retryability / next step), and
  machine codes, object ids, attempts, owner enums, recovery actions and
  audit detail/context never leave the server.

The API package imports no legacy writing routes and no medical-monitoring
implementation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    CanonicalState,
    DecisionRecord,
    JsonValue,
    NonEmptyText,
    NonNegativeInt,
    PositiveRevision,
    Sha256,
    SideEffectKind,
    StableId,
    StudyDefinitionV3,
    UnitInterval,
    WorkflowRunStatus,
)

from app.protocol_workflow.agent5 import (
    CoordinatorWorkPackage,
    GateObservation,
    GraphPin,
    PinnedSkill,
    TemplatePin,
)

__all__ = [
    # request
    "RunManifestPinRequest",
    "SideEffectSpecRequest",
    "StudyDefinitionCreateRequest",
    "StudyDefinitionDecisionApplyRequest",
    "WorkPackageDecompositionRequest",
    "WorkPackageSpecRequest",
    # response
    "CurrentStudyDefinitionResponse",
    "DecisionGraphRecordResponse",
    "DecisionGraphResponse",
    "DecisionRequestQueueResponse",
    "DecisionRequestResponse",
    "DecisionSummaryResponse",
    "EventSummaryResponse",
    "GateSummaryResponse",
    "ProgressSummaryResponse",
    "RunManifestResponse",
    "StudyDefinitionMutationResponse",
    "WorkPackageDecompositionResponse",
    "WorkflowRunStatusRecordResponse",
    "WorkflowRunStatusResponse",
]

_Facts = Annotated[dict[NonEmptyText, JsonValue], Field(min_length=1)]


# ---------------------------------------------------------------------------
# Mutation request bodies
# ---------------------------------------------------------------------------


class SideEffectSpecRequest(BaseModel):
    """Optional atomic outbox side effect attached to a mutation.

    The router rejects ``SideEffectKind.NONE`` by delegating to the typed
    application command (its construction validation is authoritative).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    workflow_run_id: StableId
    side_effect_kind: SideEffectKind


class StudyDefinitionCreateRequest(BaseModel):
    """Create the revision-1 StudyDefinition genesis aggregate.

    Mirrors :class:`CreateStudyDefinitionCommand`; the router rejects a body
    ``project_id`` that differs from the path before any service call and
    translates construction validation failures into the stable Chinese
    request envelope.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: StableId
    study_definition_id: StableId
    idempotency_key: NonEmptyText
    expected_revision: Literal[0] = 0
    actor_type: ActorType
    actor_id: StableId
    reason: NonEmptyText
    decision_record: DecisionRecord
    normalized_seed_id: StableId
    normalized_seed_sha256: Sha256
    initial_facts: _Facts
    side_effect: Optional[SideEffectSpecRequest] = None


class StudyDefinitionDecisionApplyRequest(BaseModel):
    """Apply an accepted decision to the current StudyDefinition revision.

    Mirrors :class:`ApplyStudyDecisionCommand`; the same path/body project
    isolation and command-validation translation apply.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: StableId
    study_definition_id: StableId
    idempotency_key: NonEmptyText
    expected_revision: PositiveRevision
    actor_type: ActorType
    actor_id: StableId
    reason: NonEmptyText
    decision_record: DecisionRecord
    fact_updates: Optional[dict[NonEmptyText, JsonValue]] = None
    side_effect: Optional[SideEffectSpecRequest] = None


# ---------------------------------------------------------------------------
# Agent⑤ request bodies
# ---------------------------------------------------------------------------


class RunManifestPinRequest(BaseModel):
    """Pin a run manifest from already approved inputs only.

    Mirrors :class:`Agent5Coordinator.pin_run_manifest`; the router builds a
    fresh query façade + coordinator for this request's identity triple, so
    the manifest always reflects the current StudyDefinition state.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: StableId
    study_definition_id: StableId
    workflow_run_id: StableId
    protocol_template: TemplatePin
    graph: GraphPin
    contract_schema_version: NonEmptyText
    #: An empty source lineage cannot be represented: Worker02's immutable
    #: RunManifest requires at least one pinned source revision, so the HTTP
    #: contract rejects an empty lineage structurally before the coordinator
    #: or any service call is constructed.
    source_revision_hashes: Annotated[tuple[Sha256, ...], Field(min_length=1)]
    skills: Optional[tuple[PinnedSkill, ...]] = None


class WorkPackageSpecRequest(BaseModel):
    """One registered coordinator work-package proposal."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    work_package_id: StableId
    skill_definition_id: StableId
    depends_on: tuple[StableId, ...] = ()
    exit_criteria_ref: Optional[StableId] = None


class WorkPackageDecompositionRequest(BaseModel):
    """Decompose registered coordinator work into a deterministic order."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_id: StableId
    study_definition_id: StableId
    workflow_run_id: StableId
    packages: Annotated[tuple[WorkPackageSpecRequest, ...], Field(min_length=1)]


# ---------------------------------------------------------------------------
# Mutation responses
# ---------------------------------------------------------------------------


class StudyDefinitionMutationResponse(BaseModel):
    """Typed outcome of a canonical StudyDefinition mutation.

    ``replayed`` is ``True`` when the command was an exact CAS replay (no
    second write).  Domain event/outbox detail stays server-side.
    """

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    study_definition_id: StableId
    definition: StudyDefinitionV3
    revision: PositiveRevision
    revision_sha256: Sha256
    effective_decision: DecisionRecord
    replayed: bool


# ---------------------------------------------------------------------------
# Query responses
# ---------------------------------------------------------------------------


class CurrentStudyDefinitionResponse(BaseModel):
    """Current StudyDefinition, its revision and canonical revision hash."""

    model_config = ConfigDict(extra="forbid")

    definition: Optional[StudyDefinitionV3]
    revision: Optional[PositiveRevision]
    revision_sha256: Optional[Sha256]


class DecisionSummaryResponse(BaseModel):
    """One applied decision derived from the authoritative event stream."""

    model_config = ConfigDict(extra="forbid")

    cas_identity: NonEmptyText
    decision_record_id: StableId
    decision_key: StableId
    selected_option_id: StableId
    state_revision: PositiveRevision
    applied_revision: PositiveRevision
    canonical_state: CanonicalState
    decided_at: datetime


class EventSummaryResponse(BaseModel):
    """Event-stream head identity plus the decision lineage summary."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    study_definition_id: StableId
    event_count: NonNegativeInt
    last_sequence: Optional[PositiveRevision]
    last_event_sha256: Optional[Sha256]
    decisions: tuple[DecisionSummaryResponse, ...] = ()


class DecisionGraphRecordResponse(BaseModel):
    """One decision-key projection record."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    decision_key: StableId
    decision_record_id: Optional[StableId]
    state_revision: Optional[PositiveRevision]
    selected_option_id: Optional[StableId]
    canonical_state: Optional[CanonicalState]


class DecisionGraphResponse(BaseModel):
    """The decision-graph read-model projection (may be empty)."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    study_definition_id: StableId
    records: tuple[DecisionGraphRecordResponse, ...] = ()


class WorkflowRunStatusRecordResponse(BaseModel):
    """One workflow-run status projection record."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    workflow_run_id: StableId
    status: WorkflowRunStatus
    display_progress: UnitInterval
    journey_counter: NonNegativeInt


class WorkflowRunStatusResponse(BaseModel):
    """Workflow-run status projection (``None`` when no projection exists)."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    workflow_run_id: StableId
    status: Optional[WorkflowRunStatusRecordResponse]


# ---------------------------------------------------------------------------
# Agent⑤ aggregation responses
# ---------------------------------------------------------------------------


class ProgressSummaryResponse(BaseModel):
    """Read-only progress/version aggregation (Agent⑤)."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    workflow_run_id: StableId
    run_status: Optional[WorkflowRunStatus] = None
    display_progress: UnitInterval = 0.0
    journey_counter: NonNegativeInt = 0
    study_definition_id: Optional[StableId] = None
    study_definition_revision: Optional[PositiveRevision] = None
    study_definition_sha256: Optional[Sha256] = None


class GateSummaryResponse(BaseModel):
    """Read-only Gate aggregation (Agent⑤); observations are immutable."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    workflow_run_id: StableId
    observations: tuple[GateObservation, ...] = ()


class DecisionRequestResponse(BaseModel):
    """One pending decision request from the decision-graph read-model."""

    model_config = ConfigDict(extra="forbid")

    decision_key: StableId
    decision_record_id: Optional[StableId] = None
    state_revision: Optional[PositiveRevision] = None
    selected_option_id: Optional[StableId] = None
    canonical_state: Optional[CanonicalState] = None


class DecisionRequestQueueResponse(BaseModel):
    """Deterministic queue of decisions awaiting user confirmation."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    study_definition_id: StableId
    requests: tuple[DecisionRequestResponse, ...] = ()


class RunManifestResponse(BaseModel):
    """The pinned immutable run manifest plus its deterministic content hash."""

    model_config = ConfigDict(extra="forbid")

    workflow_run_id: StableId
    project_id: StableId
    protocol_template_version: NonEmptyText
    protocol_template_sha256: Sha256
    graph_version: NonEmptyText
    graph_sha256: Sha256
    contract_schema_version: NonEmptyText
    skills: tuple[PinnedSkill, ...]
    source_revision_hashes: tuple[Sha256, ...]
    study_definition_id: StableId
    study_definition_revision: PositiveRevision
    study_definition_sha256: Sha256
    created_at: datetime
    content_sha256: Sha256


class WorkPackageDecompositionResponse(BaseModel):
    """Registered work-package decomposition with a deterministic order."""

    model_config = ConfigDict(extra="forbid")

    project_id: StableId
    workflow_run_id: StableId
    ordered_package_ids: tuple[StableId, ...]
    packages: tuple[CoordinatorWorkPackage, ...]
