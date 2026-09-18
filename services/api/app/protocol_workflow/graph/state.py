"""Run state vocabulary for the typed graph runtime (Task 2R.1).

Closed statuses, immutable snapshot records and typed errors of the
event-sourced graph runtime.  The authoritative run state is reconstructed
from the run's event stream (and the committed reservation ledger); the
``graph_checkpoint`` event is *advisory only* and never certifies node
completion or run completion.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.workbench_contracts.protocol_v3 import (
    NonEmptyText,
    Sha256,
    StableId,
)

__all__ = [
    "GraphRunStatus",
    "GraphNodeStatus",
    "GraphNodeStateRecord",
    "GraphRunSnapshot",
    "GraphRunError",
    "GraphPlanBindingError",
    "GraphDecisionConflictError",
    "GRAPH_EVENT_SCHEMA_VERSION",
    "GRAPH_EVENT_UPCASTER_ID",
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


class GraphRunStatus(str, Enum):
    """Closed run lifecycle states."""

    RUNNING = "running"
    AWAITING_DECISION = "awaiting_decision"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class GraphNodeStatus(str, Enum):
    """Closed per-node states, reconstructed from events + reservations.

    ``RUNNING`` never survives a process boundary: a reservation left
    running by a dead process reconstructs as ``BLOCKED_UNKNOWN`` (the
    physical outcome is unproven and never auto-redispatched).
    """

    PENDING = "pending"
    COMPLETED = "completed"
    AWAITING_DECISION = "awaiting_decision"
    FAILED = "failed"
    BLOCKED_UNKNOWN = "blocked_unknown"


class _StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class GraphNodeStateRecord(_StateModel):
    """Reconstructed state of one node in a run snapshot."""

    node_id: StableId
    status: GraphNodeStatus
    logical_key: NonEmptyText
    output_sha256: Optional[Sha256] = None
    attempt: Optional[int] = None
    executed_in_last_call: bool = False


class GraphRunSnapshot(_StateModel):
    """Black-box view of one graph run after a runtime call."""

    workflow_run_id: StableId
    project_id: StableId
    branch_id: StableId
    graph_id: StableId
    graph_version: NonEmptyText
    graph_sha256: Sha256
    status: GraphRunStatus
    nodes: Tuple[GraphNodeStateRecord, ...] = Field(min_length=1)
    #: ``None`` when the advisory checkpoint agrees with the authoritative
    #: event replay; otherwise a short divergence description.
    checkpoint_divergence: Optional[NonEmptyText] = None
    stop_reason: Optional[NonEmptyText] = None

    def node(self, node_id: str) -> GraphNodeStateRecord:
        for record in self.nodes:
            if record.node_id == node_id:
                return record
        raise KeyError(node_id)

    def node_output(self, node_id: str) -> Optional[Sha256]:
        """Effective artifact hash of one node (``None`` while absent)."""

        return self.node(node_id).output_sha256


class GraphRunError(RuntimeError):
    """Typed failure of a graph-runtime operation."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class GraphPlanBindingError(GraphRunError):
    """A plan does not match the identity bound to an existing run.

    Raised when a resume/advance names a graph whose version or material
    hash differs from the one the run started with (old graph rejected).
    """


class GraphDecisionConflictError(GraphRunError):
    """A decision key already holds a different recorded decision."""


# ---------------------------------------------------------------------------
# Event vocabulary
# ---------------------------------------------------------------------------

GRAPH_EVENT_SCHEMA_VERSION = "mw_protocol_v3_graph_event_v1"
GRAPH_EVENT_UPCASTER_ID = "graph-runtime-v1"

EVENT_RUN_STARTED = "graph_run_started"
EVENT_NODE_RESULT = "graph_node_result"
EVENT_DECISION_PENDING = "graph_decision_pending"
EVENT_DECISION_RECORDED = "graph_decision_recorded"
EVENT_CHECKPOINT = "graph_checkpoint"
EVENT_CHECKPOINT_REPAIRED = "graph_checkpoint_repaired"
EVENT_RUN_COMPLETED = "graph_run_completed"

#: Actor identity of runtime-written events (the writer); reviewer identity
#: travels on decision events as ``actor_id`` with ``actor_type=user``.
RUNTIME_ACTOR_ID = "graph-runtime"

#: Reservation error code proving a disposed orphan shell never crossed the
#: dispatch boundary (zero transport attempts) — mirrors the committed
#: reservation runtime's recovery classification.
ORPHAN_DISPATCH_NOT_STARTED = "dispatch_not_started_recovery"
