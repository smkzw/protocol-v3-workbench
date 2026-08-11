"""Protocol v3 API skeleton (frozen plan Task 1.9).

The package owns the closed request/response schemas and the
:func:`create_protocol_workflow_router` factory under
``/api/projects/{project_id}/protocol-workflow``.

* The router is factory-tested through a local in-process ``FastAPI`` app;
  the shared ``main.py`` composition root is NOT edited and the router is NOT
  product-mounted by this task.
* Mutations translate the typed application commands (project / revision /
  idempotency / actor / reason / full immutable ``DecisionRecord``) and
  reject a path/body project mismatch before any service call; queries have
  zero write side effects.
* Every Agent⑤ request builds a fresh ``Agent5QueryFacade`` +
  ``Agent5Coordinator`` from that request's identity triple, so snapshots are
  never stale.
* Errors cross the HTTP boundary only through the catalog's Chinese-native
  public copy; machine codes, object ids, attempts, owner enums, recovery
  actions and audit detail/context stay server-side.  There is no
  client-supplied exception-card endpoint (a client must never invent a
  catalog failure); the internal Agent⑤ exception-card capability stays
  covered by the agent5 authority tests.  Hosting apps SHOULD register
  :func:`protocol_workflow_validation_exception_handler` to keep structural
  validation inside the same stable Chinese envelope.
* The package imports no legacy writing routes and no medical-monitoring
  implementation.

Public surface
--------------
* ``schemas`` — closed request/response models.
* ``router`` — ``create_protocol_workflow_router(...)`` and
  ``protocol_workflow_validation_exception_handler(...)``.
"""

from __future__ import annotations

from .router import (
    create_protocol_workflow_router,
    protocol_workflow_validation_exception_handler,
)
from .schemas import (
    CurrentStudyDefinitionResponse,
    DecisionGraphRecordResponse,
    DecisionGraphResponse,
    DecisionRequestQueueResponse,
    DecisionRequestResponse,
    DecisionSummaryResponse,
    EventSummaryResponse,
    GateSummaryResponse,
    ProgressSummaryResponse,
    RunManifestPinRequest,
    RunManifestResponse,
    SideEffectSpecRequest,
    StudyDefinitionCreateRequest,
    StudyDefinitionDecisionApplyRequest,
    StudyDefinitionMutationResponse,
    WorkPackageDecompositionRequest,
    WorkPackageDecompositionResponse,
    WorkPackageSpecRequest,
    WorkflowRunStatusRecordResponse,
    WorkflowRunStatusResponse,
)

__all__ = [
    # router
    "create_protocol_workflow_router",
    "protocol_workflow_validation_exception_handler",
    # request schemas
    "RunManifestPinRequest",
    "SideEffectSpecRequest",
    "StudyDefinitionCreateRequest",
    "StudyDefinitionDecisionApplyRequest",
    "WorkPackageDecompositionRequest",
    "WorkPackageSpecRequest",
    # response schemas
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
