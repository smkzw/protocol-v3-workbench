"""Thin PoC adapter: accepted Task 2.1 case graphs → product graph runtime
(Task 2R.1).

This module is the one-directional bridge between the accepted immutable
case vocabulary (:mod:`pocs.protocol_v3.orchestrator`) and the product typed
orchestration runtime (:mod:`app.protocol_workflow.graph`).  It is a *PoC*
artifact living under ``pocs/`` — product code never imports it (the product
runtime imports nothing from ``pocs``; the import direction is strictly
PoC → product, never reverse).

Responsibilities (deliberately narrow — the scheduler lives in the product
runtime and is NOT duplicated here):

* :func:`plan_from_case_graph` — convert one accepted :class:`CaseGraph`
  into a validated product :class:`~app.protocol_workflow.graph.GraphPlan`,
  mapping the closed enums (``NodeKind``/``OwnerRole``), declared schemas,
  root inputs, dependencies and stable side-effect logical keys 1:1.  The
  conversion is read-only: the seven accepted Task 2.1 files and their
  material hashes are never mutated (the product plan material hash is a
  *new* product-side identity; the accepted graph hashes stay pinned by the
  accepted Task 2.1 tests).
* :func:`deterministic_services` — one deterministic, offline typed service
  per node producing labeled synthetic placeholder payloads (no model, QC,
  calculation, network or storage call; no numeric sample-size value is
  invented — payloads are labeled placeholders only).
* :func:`graph_lock_node` — the single USER decision/lock node of a case.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping

from pocs.protocol_v3.orchestrator import (
    NodeContract,
    NodeKind,
    OwnerRole,
    CaseGraph,
)

from app.protocol_workflow.graph import (
    GraphNodeKind,
    GraphNodeOwner,
    GraphNodePlan,
    GraphPlan,
    NodeServiceRequest,
)

__all__ = [
    "plan_from_case_graph",
    "deterministic_services",
    "graph_lock_node",
    "TypedFacadeError",
]


class TypedFacadeError(RuntimeError):
    """Typed failure of the PoC→product conversion."""


_NODE_KIND_MAP: Mapping[NodeKind, GraphNodeKind] = {
    NodeKind.WORK: GraphNodeKind.WORK,
    NodeKind.CHECK: GraphNodeKind.CHECK,
    NodeKind.CALCULATION: GraphNodeKind.CALCULATION,
    NodeKind.DECISION: GraphNodeKind.DECISION,
}

_OWNER_ROLE_MAP: Mapping[OwnerRole, GraphNodeOwner] = {
    OwnerRole.COORDINATOR: GraphNodeOwner.COORDINATOR,
    OwnerRole.DESIGN_AND_SUMMARY: GraphNodeOwner.DESIGN_AND_SUMMARY,
    OwnerRole.QUALITY_CONTROL: GraphNodeOwner.QUALITY_CONTROL,
    OwnerRole.USER: GraphNodeOwner.USER,
    OwnerRole.SYSTEM: GraphNodeOwner.SYSTEM,
}


def _convert_node(node: NodeContract) -> GraphNodePlan:
    try:
        kind = _NODE_KIND_MAP[node.kind]
        owner = _OWNER_ROLE_MAP[node.owner]
    except KeyError as exc:  # pragma: no cover - closed enums, defensive
        raise TypedFacadeError(
            f"node {node.node_id!r} carries vocabulary outside the accepted "
            f"Task 2.1 case enums: {exc}"
        ) from exc
    logical_key = node.side_effect_key_template or node.node_id
    return GraphNodePlan(
        node_id=node.node_id,
        kind=kind,
        owner=owner,
        depends_on=tuple(sorted(set(node.depends_on))),
        input_schemas=tuple(node.inputs),
        output_schema=node.output_schema,
        logical_key=logical_key,
        allowed_attempts=node.allowed_attempts,
    )


def plan_from_case_graph(graph: CaseGraph) -> GraphPlan:
    """Convert one accepted case graph into a product plan (read-only).

    The accepted graph is consumed, never mutated.  The product plan
    validator re-checks topology/coverage fail-closed, so a conversion can
    never widen what the accepted graph already guarantees.
    """

    return GraphPlan(
        project_id=graph.project_id,
        branch_id=graph.branch_id,
        graph_id=graph.case_id.value,
        graph_version=graph.graph_version,
        description=graph.description,
        schemas=tuple(schema.name for schema in graph.schemas),
        root_inputs=tuple(graph.root_inputs),
        nodes=tuple(_convert_node(node) for node in graph.nodes),
    )


def graph_lock_node(graph: CaseGraph) -> NodeContract:
    """Return the single USER decision/lock node of *graph*."""

    locks = [
        node
        for node in graph.nodes
        if node.kind is NodeKind.DECISION and node.owner is OwnerRole.USER
    ]
    if len(locks) != 1:
        raise TypedFacadeError(
            f"case {graph.case_id.value} must declare exactly one user "
            f"decision lock; found {len(locks)}"
        )
    return locks[0]


def deterministic_services(
    graph: CaseGraph,
) -> Dict[str, Callable[[NodeServiceRequest], Mapping[str, Any]]]:
    """One deterministic offline typed service per node of *graph*.

    Every payload is a labeled synthetic placeholder derived only from the
    node's identity and its inputs' content hashes: same inputs reproduce
    byte-identical outputs (deterministic replay), and no clinical or
    statistical value is invented.
    """

    services: Dict[str, Callable[[NodeServiceRequest], Mapping[str, Any]]] = {}

    def _make(node: NodeContract):
        def _service(request: NodeServiceRequest) -> Mapping[str, Any]:
            return {
                "node": node.node_id,
                "output_schema": node.output_schema,
                "owner": node.owner.value,
                "label": "labeled-synthetic-facade",
                "input_sha256": dict(sorted(request.input_hashes.items())),
                "attempt": request.attempt,
            }

        return _service

    for node in graph.nodes:
        services[node.node_id] = _make(node)
    return services
