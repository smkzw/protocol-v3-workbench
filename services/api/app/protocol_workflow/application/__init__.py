"""Storage-neutral application layer for Protocol v3 (Task 1.9).

The application layer owns the typed command/query surface and the only
canonical mutation boundary (design sections 5.1 / 17.2).  It accepts an
injected :class:`~app.protocol_workflow.storage.selected.UnitOfWorkFactory`;
production storage selection stays fail-closed outside this package.

Public API surface
------------------
Commands
  * :class:`CreateStudyDefinitionCommand` — create revision 1 atomically.
  * :class:`ApplyStudyDecisionCommand` — advance a StudyDefinition revision.
  * :class:`SideEffectSpec` — optional outbox side effect.

Queries
  * :class:`GetStudyDefinitionQuery`
  * :class:`GetStudyDefinitionEventSummaryQuery`
  * :class:`GetDecisionGraphQuery`
  * :class:`GetWorkflowRunStatusQuery`

Service
  * :class:`ApplicationService` — command/query façade.
  * :class:`StudyDefinitionMutationResult` — mutation outcome.
"""

from __future__ import annotations

from .commands import (
    ApplyStudyDecisionCommand,
    CreateStudyDefinitionCommand,
    SideEffectSpec,
    study_definition_genesis_snapshot,
)
from .queries import (
    GetSemanticDocumentQuery,
    SemanticDocumentQueryResult,
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
from .service import (
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DECISION_APPLIED,
    ApplicationService,
    StudyDefinitionMutationResult,
    study_definition_stream_id,
)

__all__ = [
    # commands
    "ApplyStudyDecisionCommand",
    "CreateStudyDefinitionCommand",
    "SideEffectSpec",
    "study_definition_genesis_snapshot",
    # queries
    "GetSemanticDocumentQuery",
    "SemanticDocumentQueryResult",
    "DecisionGraphQueryResult",
    "DecisionSummary",
    "EventSummaryQueryResult",
    "GetDecisionGraphQuery",
    "GetStudyDefinitionEventSummaryQuery",
    "GetStudyDefinitionQuery",
    "GetWorkflowRunStatusQuery",
    "StudyDefinitionQueryResult",
    "WorkflowRunStatusQueryResult",
    # service
    "EVENT_TYPE_CREATED",
    "EVENT_TYPE_DECISION_APPLIED",
    "ApplicationService",
    "StudyDefinitionMutationResult",
    "study_definition_stream_id",
]
