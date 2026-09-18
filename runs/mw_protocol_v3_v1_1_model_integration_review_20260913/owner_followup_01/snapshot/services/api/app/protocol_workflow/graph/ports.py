"""Typed ports for the product graph runtime (Task 2R.2 OrchestratorPort).

``OrchestratorPort`` is the product boundary a typed orchestration facade
drives: start, advance step-by-step, complete, record human decisions and
recover blocked work — everything through durable product storage.  Node
behavior is injected as :class:`NodeService` callables (deterministic typed
services stand in for models, QC and calculation; they perform no I/O and no
provider calls). Configured model executors use ``ConfiguredNodeServiceRequest``
with their persisted contract; they remain outside this deterministic service
protocol and do not receive repository or runtime handles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable
from packages.contracts.workbench_contracts.protocol_v3 import NodeExecutionContract

from app.protocol_workflow.graph.plan import GraphNodePlan, GraphPlan
from app.protocol_workflow.graph.state import GraphRunSnapshot

__all__ = ["OrchestratorPort", "NodeService", "NodeServiceRequest", "ConfiguredNodeServiceRequest"]


@runtime_checkable
class NodeService(Protocol):
    """Deterministic typed behavior of one plan node.

    The service receives the node's material inputs (dependency/root
    payloads with their content hashes) and returns a JSON-able payload —
    the node's effective artifact.  It must be pure: no repository, clock,
    network or provider access.
    """

    def __call__(self, request: "NodeServiceRequest") -> Mapping[str, Any]: ...


class NodeServiceRequest:
    """Material handed to one node-service invocation."""

    __slots__ = ("plan", "node", "inputs", "input_hashes", "attempt", "reservation_id")

    def __init__(
        self,
        *,
        plan: GraphPlan,
        node: GraphNodePlan,
        inputs: Mapping[str, Any],
        input_hashes: Mapping[str, str],
        attempt: int,
        reservation_id: str,
    ) -> None:
        self.plan = plan
        self.node = node
        self.inputs = inputs
        self.input_hashes = input_hashes
        self.attempt = attempt
        self.reservation_id = reservation_id


class ConfiguredNodeServiceRequest(NodeServiceRequest):
    """A configured executor also receives its persisted execution contract.

    Plain deterministic services retain their original input-only interface.
    Neither request gives the executor a repository or runtime handle.
    """

    __slots__ = ('execution_contract',)

    def __init__(self, *, execution_contract: NodeExecutionContract, **kwargs) -> None:
        super().__init__(**kwargs)
        self.execution_contract = execution_contract


@dataclass(frozen=True)
class ConfiguredNodeServiceResult:
    """Material result and the provider-issued receipt identity, kept separate."""

    payload: Mapping[str, Any]
    provider_session_id: str


@runtime_checkable
class OrchestratorPort(Protocol):
    """Product typed orchestration boundary.

    Implementations persist all run state through the product storage
    adapter (unit-of-work event streams plus the committed-operation
    reservation repository), reconstruct from authoritative events/results,
    treat checkpoints as advisory, pause at human decisions, and never
    auto-redispatch unknown outcomes.
    """

    def start_run(
        self,
        plan: GraphPlan,
        *,
        workflow_run_id: str,
        root_inputs: Mapping[str, Any],
    ) -> GraphRunSnapshot: ...

    def load_run(self, plan: GraphPlan, workflow_run_id: str) -> GraphRunSnapshot: ...

    def advance(
        self, workflow_run_id: str, plan: GraphPlan | None = None
    ) -> GraphRunSnapshot: ...

    def run_to_completion(
        self, workflow_run_id: str, plan: GraphPlan | None = None
    ) -> GraphRunSnapshot: ...

    def record_decision(
        self,
        workflow_run_id: str,
        *,
        node_id: str,
        decision_id: str,
        actor_id: str,
        value: Mapping[str, Any],
        reason: str,
    ) -> GraphRunSnapshot: ...

    def read_events(self, workflow_run_id: str): ...
