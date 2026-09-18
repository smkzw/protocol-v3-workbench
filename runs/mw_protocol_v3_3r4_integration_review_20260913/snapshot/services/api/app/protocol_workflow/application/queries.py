"""Typed read-only queries and results for the Protocol v3 application service.

Design authority: Protocol v3 multi-agent rearchitecture design sections 5.1
and 18, and the frozen plan Task 1.9.  Queries are explicit typed read
operations executed by the application service through a fresh unit of work.
They never write: no CAS save, event append, outbox enqueue, inbox
acknowledgement or read-model mutation.

Results expose current StudyDefinition state, decision/event summaries and
workflow status only through the existing contracts (canonical value objects,
the append-only event stream and the read-model port).  No repository or
unit-of-work handle is exposed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    StudyDefinitionV3,
)

from app.protocol_workflow.ports.repositories import (
    DecisionGraphRecord,
    WorkflowRunStatusRecord,
)

__all__ = [
    "DecisionGraphQueryResult",
    "DecisionSummary",
    "EventSummaryQueryResult",
    "GetDecisionGraphQuery",
    "GetStudyDefinitionEventSummaryQuery",
    "GetStudyDefinitionQuery",
    "GetWorkflowRunStatusQuery",
    "StudyDefinitionQueryResult",
    "WorkflowRunStatusQueryResult",
]


def _require_query_identity(project_id: str, *object_ids: str) -> None:
    for label, value in (("project_id", project_id), *[("object_id", o) for o in object_ids]):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be a non-empty string")


@dataclass(frozen=True)
class GetStudyDefinitionQuery:
    """Read the current StudyDefinition aggregate and its revision identity."""

    project_id: str
    study_definition_id: str

    def __post_init__(self) -> None:
        _require_query_identity(self.project_id, self.study_definition_id)


@dataclass(frozen=True)
class GetStudyDefinitionEventSummaryQuery:
    """Read the study's event-stream summary and decision lineage.

    The decision summaries are derived from the authoritative event stream
    (the same ledger rebuild the mutation path uses), so they never touch a
    read-model write path.
    """

    project_id: str
    study_definition_id: str

    def __post_init__(self) -> None:
        _require_query_identity(self.project_id, self.study_definition_id)


@dataclass(frozen=True)
class GetDecisionGraphQuery:
    """Read latest decisions from the committed event stream.

    Historical confirmation and current input validity are distinct. Legacy
    records without input bindings remain unverified for current validity.
    """

    project_id: str
    study_definition_id: str

    def __post_init__(self) -> None:
        _require_query_identity(self.project_id, self.study_definition_id)


@dataclass(frozen=True)
class GetWorkflowRunStatusQuery:
    """Read the workflow-run status read-model projection."""

    project_id: str
    workflow_run_id: str

    def __post_init__(self) -> None:
        _require_query_identity(self.project_id, self.workflow_run_id)


# ---------------------------------------------------------------------------
# Typed results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StudyDefinitionQueryResult:
    """Current StudyDefinition, its revision and its canonical revision hash.

    ``definition`` is ``None`` when no aggregate exists for the identity.
    """

    definition: Optional[StudyDefinitionV3]
    revision: Optional[int]
    revision_sha256: Optional[str]


@dataclass(frozen=True)
class DecisionSummary:
    """One applied decision derived from the authoritative event stream.

    ``applied_revision`` is the aggregate revision the decision produced
    (the recorded effect's result revision).
    """

    cas_identity: str
    decision_record_id: str
    decision_key: str
    selected_option_id: str
    state_revision: int
    applied_revision: int
    canonical_state: CanonicalState
    decided_at: datetime


@dataclass(frozen=True)
class EventSummaryQueryResult:
    """Event-stream head identity plus the decision lineage summary."""

    project_id: str
    study_definition_id: str
    event_count: int
    last_sequence: Optional[int]
    last_event_sha256: Optional[str]
    decisions: Tuple[DecisionSummary, ...]


@dataclass(frozen=True)
class DecisionGraphQueryResult:
    """Decision-graph read-model projection records (may be empty)."""

    project_id: str
    study_definition_id: str
    records: Tuple[DecisionGraphRecord, ...]


@dataclass(frozen=True)
class WorkflowRunStatusQueryResult:
    """Workflow-run status projection (``None`` when no projection exists)."""

    project_id: str
    workflow_run_id: str
    status: Optional[WorkflowRunStatusRecord]
