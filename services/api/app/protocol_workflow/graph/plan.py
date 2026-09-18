"""Product-owned typed graph plan vocabulary (Task 2R.1).

The closed, immutable definition of one typed orchestration graph for the
product runtime (``app.protocol_workflow.graph.runtime``).  This vocabulary is
product-owned: it carries NO import from ``pocs`` — accepted PoC case graphs
enter through the thin PoC adapter
(``pocs.protocol_v3.orchestrator.typed_facade``), which converts their
vocabulary into these types.  The runtime consumes only this module's types.

A :class:`GraphPlan` binds ``project_id``/``branch_id``/``graph_id``/
``graph_version`` and a deterministic material SHA-256 (identity + sorted
structure only — no timestamps, run ids or counters), so a run can pin the
exact graph that started it and reject any other version on resume.

Validation fails closed at construction (raising :class:`GraphPlanError`
directly — pydantic propagates non-ValueError validator exceptions
unchanged) on: duplicate/unknown dependencies, self-dependencies, cycles,
duplicate node ids or logical keys, unknown output schemas, ambiguous output
producers, uncovered input schemas, inputs whose producer is not a declared
dependency, root inputs colliding with node outputs, and nodes without any
declared input.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, ClassVar, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.contracts.workbench_contracts.protocol_v3 import (
    NonEmptyText,
    PositiveRevision,
    Sha256,
    StableId,
)

__all__ = [
    "GraphNodeKind",
    "GraphNodeOwner",
    "GraphNodePlan",
    "GraphPlan",
    "GraphPlanError",
]


class GraphPlanError(RuntimeError):
    """Typed, stable failure of the product graph plan vocabulary.

    ``code`` is a stable machine name, ``path`` locates the offending field,
    ``message`` is human-readable.  Subclasses :class:`RuntimeError` (not
    ``ValueError``) deliberately: pydantic v2 propagates non-ValueError
    validator exceptions unchanged, so callers catch the typed error
    directly instead of unwrapping a ``ValidationError``.
    """

    def __init__(self, code: str, path: str, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(f"{code} at {path}: {message}")


class GraphNodeKind(str, Enum):
    """Closed set of node kinds the product runtime drives."""

    WORK = "work"
    CHECK = "check"
    CALCULATION = "calculation"
    DECISION = "decision"


class GraphNodeOwner(str, Enum):
    """Closed set of owners; mirrors product ``SkillDefinition.agent_role``
    literals plus the two deterministic/human roles the accepted case graphs
    require (``user`` decides, ``system`` runs deterministic checks)."""

    COORDINATOR = "coordinator"
    DESIGN_AND_SUMMARY = "design_and_summary"
    FULL_DRAFT = "full_draft"
    QUALITY_CONTROL = "quality_control"
    USER = "user"
    SYSTEM = "system"


def _unique(values: Tuple[str, ...], code: str, path: str, label: str) -> Tuple[str, ...]:
    if len(values) != len(set(values)):
        raise GraphPlanError(code, path, f"{label} must be unique")
    return values


class _GraphModel(BaseModel):
    """Frozen, closed plan model with fully re-validating copies."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        revalidate_instances="always",
    )

    def model_copy(
        self,
        *,
        update: Optional[dict[str, Any]] = None,
        deep: bool = False,
    ) -> "_GraphModel":
        """Copy with full re-validation (never a silent bypass)."""

        if update is None:
            return self
        merged = self.model_dump()
        merged.update(update)
        return type(self)(**merged)


class GraphNodePlan(_GraphModel):
    """One typed node of a :class:`GraphPlan`."""

    node_id: StableId
    kind: GraphNodeKind
    owner: GraphNodeOwner
    depends_on: Tuple[StableId, ...] = ()
    #: Typed input schemas this node consumes (root inputs or dependency
    #: outputs); at least one is required so every execution contract binds
    #: a non-empty dependency set.
    input_schemas: Tuple[NonEmptyText, ...] = ()
    output_schema: NonEmptyText
    #: Stable logical key of the node's effective artifact (idempotency
    #: scope).  Unique across the plan.
    logical_key: NonEmptyText
    #: Upper bound for explicit retry attempts of this node.
    allowed_attempts: PositiveRevision = 1

    @model_validator(mode="after")
    def _validate_node(self) -> "GraphNodePlan":
        if not self.input_schemas:
            raise GraphPlanError(
                "graph_node_inputs_empty",
                f"nodes/{self.node_id}/input_schemas",
                "every node must declare at least one input schema so its "
                "execution contract binds a dependency set",
            )
        _unique(self.depends_on, "graph_dependency_duplicate", f"nodes/{self.node_id}/depends_on", "dependencies")
        _unique(self.input_schemas, "graph_input_duplicate", f"nodes/{self.node_id}/input_schemas", "input schemas")
        if self.node_id in self.depends_on:
            raise GraphPlanError(
                "graph_cycle",
                f"nodes/{self.node_id}/depends_on",
                "a node must not depend on itself",
            )
        if self.kind is GraphNodeKind.DECISION and self.owner is not GraphNodeOwner.USER:
            raise GraphPlanError(
                "graph_decision_owner",
                f"nodes/{self.node_id}/owner",
                "decision nodes are owned by the human user",
            )
        return self


class GraphPlan(_GraphModel):
    """Closed immutable definition of one typed orchestration graph."""

    #: Fields that are presentation, not graph material.
    material_metadata_fields: ClassVar[frozenset[str]] = frozenset({"description"})

    project_id: StableId
    branch_id: StableId
    graph_id: StableId
    graph_version: NonEmptyText
    description: NonEmptyText
    schemas: Tuple[NonEmptyText, ...] = Field(min_length=1)
    root_inputs: Tuple[str, ...] = ()
    nodes: Tuple[GraphNodePlan, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_plan(self) -> "GraphPlan":
        node_ids = [node.node_id for node in self.nodes]
        _unique(
            tuple(node_ids), "graph_node_duplicate", "nodes", "node ids"
        )
        _unique(
            tuple(node.logical_key for node in self.nodes),
            "graph_logical_key_duplicate",
            "nodes",
            "logical keys",
        )
        _unique(self.schemas, "graph_schema_duplicate", "schemas", "schema names")
        schema_names = set(self.schemas)
        node_by_id = {node.node_id: node for node in self.nodes}
        for node in self.nodes:
            for dep in node.depends_on:
                if dep not in node_by_id:
                    raise GraphPlanError(
                        "graph_dependency_unknown",
                        f"nodes/{node.node_id}/depends_on",
                        f"unknown dependency {dep!r}",
                    )
            if node.output_schema not in schema_names:
                raise GraphPlanError(
                    "graph_schema_unknown",
                    f"nodes/{node.node_id}/output_schema",
                    f"unknown output schema {node.output_schema!r}",
                )
            for input_schema in node.input_schemas:
                if input_schema not in schema_names:
                    raise GraphPlanError(
                        "graph_schema_unknown",
                        f"nodes/{node.node_id}/input_schemas",
                        f"unknown input schema {input_schema!r}",
                    )
        for root in self.root_inputs:
            if root not in schema_names:
                raise GraphPlanError(
                    "graph_schema_unknown",
                    "root_inputs",
                    f"unknown root input schema {root!r}",
                )
        # Every declared schema is produced by at most one node; root inputs
        # are consumed, never produced.
        producers: dict[str, str] = {}
        for node in self.nodes:
            if node.output_schema in producers:
                raise GraphPlanError(
                    "graph_output_schema_ambiguous",
                    "nodes",
                    f"schema {node.output_schema!r} is produced by both "
                    f"{producers[node.output_schema]!r} and {node.node_id!r}",
                )
            producers[node.output_schema] = node.node_id
        for root in self.root_inputs:
            if root in producers:
                raise GraphPlanError(
                    "graph_root_input_conflict",
                    "root_inputs",
                    f"root input {root!r} is also produced by "
                    f"{producers[root]!r}",
                )
        # Typed input coverage: each consumed schema is a root input or the
        # output of exactly one *declared* dependency.  A missing link fails
        # closed — migration never auto-completes it.
        for node in self.nodes:
            for input_schema in node.input_schemas:
                if input_schema in self.root_inputs:
                    continue
                producer = producers.get(input_schema)
                if producer is None:
                    raise GraphPlanError(
                        "graph_input_uncovered",
                        f"nodes/{node.node_id}/input_schemas",
                        f"input schema {input_schema!r} is produced by no node "
                        "and is not a root input",
                    )
                if producer not in node.depends_on:
                    raise GraphPlanError(
                        "graph_dependency_missing",
                        f"nodes/{node.node_id}/depends_on",
                        f"input schema {input_schema!r} is produced by "
                        f"{producer!r}, which is not a declared dependency",
                    )
        self._assert_acyclic()
        return self

    # -- ordering ------------------------------------------------------------

    def topological_order(self) -> Tuple[str, ...]:
        """Deterministic dependency order (node id tie-break).

        Fails closed instead of returning a partial order if a bypassed
        instance contains a cycle.
        """

        ordered, remaining = self._kahn()
        if remaining:
            raise GraphPlanError(
                "graph_cycle",
                "nodes",
                f"graph contains a cycle among nodes: {sorted(remaining)}",
            )
        return ordered

    def _kahn(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        node_ids = {node.node_id for node in self.nodes}
        incoming: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for node in self.nodes:
            for dep in node.depends_on:
                if dep in node_ids:
                    incoming[node.node_id].add(dep)
        ready = sorted(node_id for node_id in node_ids if not incoming[node_id])
        ordered: list[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for node in self.nodes:
                if current in incoming[node.node_id]:
                    incoming[node.node_id].discard(current)
                    if not incoming[node.node_id]:
                        ready.append(node.node_id)
                        ready.sort()
        remaining = tuple(
            sorted(node_id for node_id in node_ids if incoming[node_id])
        )
        return tuple(ordered), remaining

    def _assert_acyclic(self) -> None:
        _, remaining = self._kahn()
        if remaining:
            raise GraphPlanError(
                "graph_cycle",
                "nodes",
                f"graph contains a cycle among nodes: {sorted(remaining)}",
            )

    def node(self, node_id: str) -> GraphNodePlan:
        """Return the declared node or fail closed."""

        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise GraphPlanError(
            "graph_node_unknown", f"nodes/{node_id}", f"unknown node {node_id!r}"
        )

    # -- material identity ----------------------------------------------------

    def material_payload(self) -> dict[str, Any]:
        """Canonical structural payload: identity + sorted structure only."""

        return {
            "branch_id": self.branch_id,
            "graph_id": self.graph_id,
            "graph_version": self.graph_version,
            "nodes": sorted(
                (
                    {
                        "allowed_attempts": node.allowed_attempts,
                        "depends_on": sorted(node.depends_on),
                        "input_schemas": sorted(node.input_schemas),
                        "kind": node.kind.value,
                        "logical_key": node.logical_key,
                        "node_id": node.node_id,
                        "output_schema": node.output_schema,
                        "owner": node.owner.value,
                    }
                    for node in self.nodes
                ),
                key=lambda item: item["node_id"],
            ),
            "project_id": self.project_id,
            "root_inputs": sorted(self.root_inputs),
            "schemas": sorted(self.schemas),
        }

    def material_sha256(self) -> Sha256:
        """Deterministic SHA-256 of the material payload."""

        payload = json.dumps(
            self.material_payload(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
