"""Typed graph runtime package (Task 2R.1).

Public surface of the product typed orchestration runtime behind the
``OrchestratorPort``:

* :class:`GraphPlan` / :class:`GraphNodePlan` — closed, immutable,
  fail-closed plan vocabulary with a deterministic material hash;
* :class:`GraphRuntime` — the event-sourced runtime over product SQLite
  (committed reservations, v1_1 dependency-compacted contracts, advisory
  checkpoints, human decision pauses, never-auto-redispatched unknowns);
* :class:`OrchestratorPort` / :class:`NodeService` / the snapshot and status
  vocabulary in ``state``.

This package is product-owned and MUST NOT import ``pocs``; accepted PoC
case graphs enter through the PoC-side adapter
(``pocs.protocol_v3.orchestrator.typed_facade``).
"""

from app.protocol_workflow.graph.plan import (
    GraphNodeKind,
    GraphNodeOwner,
    GraphNodePlan,
    GraphPlan,
    GraphPlanError,
)
from app.protocol_workflow.graph.ports import (
    NodeService,
    NodeServiceRequest,
    OrchestratorPort,
)
from app.protocol_workflow.graph.runtime import GraphRuntime
from app.protocol_workflow.graph.state import (
    EVENT_CHECKPOINT,
    EVENT_CHECKPOINT_REPAIRED,
    EVENT_DECISION_PENDING,
    EVENT_DECISION_RECORDED,
    EVENT_NODE_RESULT,
    EVENT_RUN_COMPLETED,
    EVENT_RUN_STARTED,
    ORPHAN_DISPATCH_NOT_STARTED,
    RUNTIME_ACTOR_ID,
    GraphDecisionConflictError,
    GraphNodeStateRecord,
    GraphNodeStatus,
    GraphPlanBindingError,
    GraphRunError,
    GraphRunSnapshot,
    GraphRunStatus,
)

__all__ = [
    # plan vocabulary
    "GraphPlan",
    "GraphNodePlan",
    "GraphNodeKind",
    "GraphNodeOwner",
    "GraphPlanError",
    # ports
    "OrchestratorPort",
    "NodeService",
    "NodeServiceRequest",
    # runtime
    "GraphRuntime",
    # state vocabulary
    "GraphRunStatus",
    "GraphNodeStatus",
    "GraphNodeStateRecord",
    "GraphRunSnapshot",
    "GraphRunError",
    "GraphPlanBindingError",
    "GraphDecisionConflictError",
    "EVENT_RUN_STARTED",
    "EVENT_NODE_RESULT",
    "EVENT_DECISION_PENDING",
    "EVENT_DECISION_RECORDED",
    "EVENT_CHECKPOINT",
    "EVENT_CHECKPOINT_REPAIRED",
    "EVENT_RUN_COMPLETED",
    "RUNTIME_ACTOR_ID",
    "ORPHAN_DISPATCH_NOT_STARTED",
]
