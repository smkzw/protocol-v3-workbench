"""Registry-level typed dependency / impact graph for Protocol v3 (Task 3R.4).

This module is registry infrastructure only: it indexes an accepted
:class:`~app.protocol_workflow.registries.chapters.ChapterRegistryDocument`
into an explicit, typed edge structure and computes deterministic impact sets.
It authors no clinical content, decides no medical or QC judgment, calls no
product model, and writes nothing.

Three relationship kinds stay explicitly typed and separate:

``fact_membership``
    A chapter declares fact paths in ``fact_requirements`` (required, optional
    or forbidden) and in ``conditional_applicability_rules`` (both the
    triggering paths and the when-active obligations).  Conditional paths are
    resolved as first-class change targets, not only the unconditionally
    required ones.

``scheduling``
    ONLY explicit ``ChapterContractV2.dependency_ids`` become hard/order edges
    of the scheduling DAG (upstream dependency -> dependent chapter).  Cross
    references, shared facts or chapter numbering are never promoted into a
    scheduling edge.

``consistency_impact``
    Reciprocal clinical relationships (summary/body, SoA/assessments,
    endpoint/estimand/statistics, dose/design/population) are derived from
    shared fact membership and stay outside the scheduling DAG.  They can
    therefore never fabricate a scheduling cycle, and a real hard cycle is
    never hidden behind a reciprocal link.

Impact computation returns every affected chapter without truncation: the seed
is the set of chapters that declare a changed material fact path, and the
closure adds the reciprocal consistency neighbours (transitively) plus the
downstream chapters of the scheduling DAG in dependency order.

Purity / CAS declaration
------------------------
``build_dependency_graph`` and :meth:`DependencyGraph.impact` are pure
functions of (accepted registry, changed material facts).  The module keeps no
store, no cache and no module-level mutable state; the impact set is recomputed
from frozen inputs and the same fact update always yields the same affected set
and the same ``impact_sha256`` adoption key -- one adoption per fact update,
with no second editable store.  :meth:`DependencyGraph.projection` renders the
graph purely as a read-only projection of the accepted registry; the rendering
is not a new content authority.  Project-confirmation invalidation therefore
uses the changed material facts and the reported affected set, never a blanket
reopen-all.

Every identified structural defect is reported, never silently dropped:
unknown dependency targets and declared dependencies without a repair owner are
typed error findings on the graph, and a hard scheduling cycle rejects the
graph outright.
"""

from __future__ import annotations

import itertools
import json
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Any, ClassVar, Optional, Union

from app.protocol_workflow.registries.chapters import (
    ChapterRegistryDocument,
    load_chapter_registry,
)

__all__ = [
    "GRAPH_SCHEMA_VERSION",
    "MISSING_REPAIR_OWNER",
    "UNKNOWN_DEPENDENCY_TARGET",
    "ChapterNode",
    "ConsistencyEdge",
    "DependencyGraph",
    "DependencyGraphError",
    "EdgeKind",
    "FactMembership",
    "GraphFinding",
    "ImpactReport",
    "MembershipSource",
    "SchedulingEdge",
    "build_dependency_graph",
]

#: Schema identity of the rendered graph projection.
GRAPH_SCHEMA_VERSION = "protocol-v3-dependency-graph.v1"

#: Findings that identify a registry-level defect instead of a hard rejection.
UNKNOWN_DEPENDENCY_TARGET = "unknown_dependency_target"
MISSING_REPAIR_OWNER = "missing_repair_owner"

#: Anything the existing fail-closed chapter loader accepts.
GraphSource = Union[ChapterRegistryDocument, str, Path, Mapping[str, Any]]


class DependencyGraphError(ValueError):
    """Raised when the registry cannot form a sound scheduling DAG."""


class EdgeKind(str, Enum):
    """The three relationship kinds kept explicitly distinct."""

    FACT_MEMBERSHIP = "fact_membership"
    SCHEDULING = "scheduling"
    CONSISTENCY_IMPACT = "consistency_impact"


class MembershipSource(str, Enum):
    """Where a fact membership was declared in the chapter contract."""

    FACT_REQUIREMENT = "fact_requirement"
    CONDITIONAL_TRIGGER = "conditional_trigger"
    CONDITIONAL_WHEN_ACTIVE = "conditional_when_active"


@dataclass(frozen=True)
class ChapterNode:
    """One accepted registry carrier."""

    contract_id: str
    node_id: str
    coverage_role: str


@dataclass(frozen=True)
class FactMembership:
    """``fact_membership`` edge: a chapter declares a fact path."""

    kind: ClassVar[EdgeKind] = EdgeKind.FACT_MEMBERSHIP

    contract_id: str
    fact_path: str
    obligation: Optional[str]
    source: MembershipSource
    conditional_rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SchedulingEdge:
    """``scheduling`` edge: dependent chapter -> upstream dependency."""

    kind: ClassVar[EdgeKind] = EdgeKind.SCHEDULING

    upstream_contract_id: str
    dependent_contract_id: str
    repair_owner: Optional[str]
    repair_policy_id: Optional[str]


@dataclass(frozen=True)
class ConsistencyEdge:
    """``consistency_impact`` edge: reciprocal shared-fact relationship."""

    kind: ClassVar[EdgeKind] = EdgeKind.CONSISTENCY_IMPACT

    left_contract_id: str
    right_contract_id: str
    shared_fact_paths: tuple[str, ...]
    reciprocal: bool = True


@dataclass(frozen=True)
class GraphFinding:
    """An identified registry-level defect (never silently dropped)."""

    code: str
    severity: str
    location: str
    message: str


@dataclass(frozen=True)
class ImpactReport:
    """Deterministic impact of one changed-material-fact update."""

    changed_fact_paths: tuple[str, ...]
    direct_contract_ids: tuple[str, ...]
    consistency_contract_ids: tuple[str, ...]
    scheduling_contract_ids: tuple[str, ...]
    affected_contract_ids: tuple[str, ...]
    unindexed_fact_paths: tuple[str, ...]
    findings: tuple[GraphFinding, ...]
    impact_sha256: str

    def affects(self, contract_id: str) -> bool:
        """True when the contract is part of the affected set."""
        return contract_id in self.affected_contract_ids


@dataclass(frozen=True)
class DependencyGraph:
    """Read-only typed dependency/impact graph over one accepted registry.

    Immutable by construction: every collection is a tuple and every value is a
    scalar, so impact computation cannot mutate the graph and the same inputs
    always yield the same output.
    """

    template_id: str
    registry_sha256: str
    nodes: tuple[ChapterNode, ...]
    memberships: tuple[FactMembership, ...]
    scheduling_edges: tuple[SchedulingEdge, ...]
    consistency_edges: tuple[ConsistencyEdge, ...]
    findings: tuple[GraphFinding, ...]

    # -- typed-edge projection -------------------------------------------

    @property
    def edges(
        self,
    ) -> tuple[FactMembership | SchedulingEdge | ConsistencyEdge, ...]:
        """Every typed edge; each carries ``kind``."""
        return self.memberships + self.scheduling_edges + self.consistency_edges

    def edge_kinds(self) -> tuple[EdgeKind, ...]:
        return tuple(sorted({edge.kind for edge in self.edges}, key=lambda k: k.value))

    # -- lookups ----------------------------------------------------------

    def contract_ids(self) -> tuple[str, ...]:
        return tuple(node.contract_id for node in self.nodes)

    def contracts_for_fact(self, fact_path: str) -> tuple[str, ...]:
        """Every chapter declaring the fact path (any obligation, any source)."""
        return tuple(
            sorted(
                {
                    membership.contract_id
                    for membership in self.memberships
                    if membership.fact_path == fact_path
                }
            )
        )

    def memberships_for_contract(self, contract_id: str) -> tuple[FactMembership, ...]:
        return tuple(
            membership
            for membership in self.memberships
            if membership.contract_id == contract_id
        )

    def scheduling_dependencies(self, contract_id: str) -> tuple[str, ...]:
        """Upstream dependencies declared by the chapter (hard edges only)."""
        return tuple(
            sorted(
                edge.upstream_contract_id
                for edge in self.scheduling_edges
                if edge.dependent_contract_id == contract_id
            )
        )

    def scheduling_dependents(self, contract_id: str) -> tuple[str, ...]:
        """Chapters that declare the given contract as a hard dependency."""
        return tuple(
            sorted(
                edge.dependent_contract_id
                for edge in self.scheduling_edges
                if edge.upstream_contract_id == contract_id
            )
        )

    def consistency_neighbours(self, contract_id: str) -> tuple[str, ...]:
        """Reciprocal shared-fact neighbours (outside the scheduling DAG)."""
        neighbours = set()
        for edge in self.consistency_edges:
            if edge.left_contract_id == contract_id:
                neighbours.add(edge.right_contract_id)
            elif edge.right_contract_id == contract_id:
                neighbours.add(edge.left_contract_id)
        return tuple(sorted(neighbours))

    def topological_order(self) -> tuple[str, ...]:
        """Dependency-first order over the scheduling DAG (hard edges only).

        Edges whose upstream target is not an accepted carrier are excluded
        from the ordering: they are identified findings, and an unknown target
        cannot order a chapter.
        """
        known = set(self.contract_ids())
        indegree = {contract_id: 0 for contract_id in known}
        dependents: dict[str, list[str]] = {contract_id: [] for contract_id in known}
        for edge in self.scheduling_edges:
            if edge.upstream_contract_id in known and edge.dependent_contract_id in known:
                indegree[edge.dependent_contract_id] += 1
                dependents[edge.upstream_contract_id].append(edge.dependent_contract_id)
        for values in dependents.values():
            values.sort()
        ready = deque(sorted(cid for cid, degree in indegree.items() if degree == 0))
        order: list[str] = []
        while ready:
            contract_id = ready.popleft()
            order.append(contract_id)
            for dependent in dependents[contract_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        return tuple(order)

    # -- impact -----------------------------------------------------------

    def impact(self, changed_fact_paths: Iterable[str]) -> ImpactReport:
        """Every affected chapter for the changed material fact paths.

        Pure function of (this registry projection, changed facts): the same
        update always yields the same affected set and the same
        ``impact_sha256`` adoption key.  Nothing is written and the graph is
        never mutated.
        """
        changed = _normalise_fact_paths(changed_fact_paths)
        carriers: dict[str, set[str]] = {}
        for membership in self.memberships:
            carriers.setdefault(membership.fact_path, set()).add(
                membership.contract_id
            )
        neighbours: dict[str, set[str]] = {}
        for edge in self.consistency_edges:
            neighbours.setdefault(edge.left_contract_id, set()).add(
                edge.right_contract_id
            )
            neighbours.setdefault(edge.right_contract_id, set()).add(
                edge.left_contract_id
            )
        dependents: dict[str, set[str]] = {}
        known = set(self.contract_ids())
        for edge in self.scheduling_edges:
            if (
                edge.upstream_contract_id in known
                and edge.dependent_contract_id in known
            ):
                dependents.setdefault(edge.upstream_contract_id, set()).add(
                    edge.dependent_contract_id
                )

        direct = {cid for path in changed for cid in carriers.get(path, ())}
        unindexed = tuple(path for path in changed if path not in carriers)
        affected = set(direct)
        consistency_reached: set[str] = set()
        scheduling_reached: set[str] = set()
        frontier = sorted(direct)
        while frontier:
            discovered: dict[str, EdgeKind] = {}
            for contract_id in frontier:
                for neighbour in sorted(neighbours.get(contract_id, ())):
                    if neighbour not in affected and neighbour not in discovered:
                        discovered[neighbour] = EdgeKind.CONSISTENCY_IMPACT
                for dependent in sorted(dependents.get(contract_id, ())):
                    if dependent not in affected and dependent not in discovered:
                        discovered[dependent] = EdgeKind.SCHEDULING
            for contract_id, kind in sorted(discovered.items()):
                if kind is EdgeKind.CONSISTENCY_IMPACT:
                    consistency_reached.add(contract_id)
                else:
                    scheduling_reached.add(contract_id)
            affected |= set(discovered)
            frontier = sorted(discovered)

        direct_ids = tuple(sorted(direct))
        consistency_ids = tuple(sorted(consistency_reached))
        scheduling_ids = tuple(sorted(scheduling_reached))
        affected_ids = tuple(sorted(affected))
        digest = _digest(
            {
                "domain": "protocol-v3-dependency-impact.v1",
                "registry_sha256": self.registry_sha256,
                "changed_fact_paths": list(changed),
                "direct_contract_ids": list(direct_ids),
                "consistency_contract_ids": list(consistency_ids),
                "scheduling_contract_ids": list(scheduling_ids),
                "affected_contract_ids": list(affected_ids),
            }
        )
        return ImpactReport(
            changed_fact_paths=changed,
            direct_contract_ids=direct_ids,
            consistency_contract_ids=consistency_ids,
            scheduling_contract_ids=scheduling_ids,
            affected_contract_ids=affected_ids,
            unindexed_fact_paths=unindexed,
            findings=self.findings,
            impact_sha256=digest,
        )

    # -- projection -------------------------------------------------------

    def projection(self) -> dict[str, Any]:
        """JSON-able read-only rendering; not a new authority."""
        return {
            "graph_schema_version": GRAPH_SCHEMA_VERSION,
            "authority": (
                "projection of the accepted chapter registry; "
                "not a content authority and not a second editable store"
            ),
            "template_id": self.template_id,
            "registry_sha256": self.registry_sha256,
            "edge_counts": {
                EdgeKind.FACT_MEMBERSHIP.value: len(self.memberships),
                EdgeKind.SCHEDULING.value: len(self.scheduling_edges),
                EdgeKind.CONSISTENCY_IMPACT.value: len(self.consistency_edges),
            },
            "nodes": [
                {
                    "contract_id": node.contract_id,
                    "node_id": node.node_id,
                    "coverage_role": node.coverage_role,
                }
                for node in self.nodes
            ],
            "edges": [
                {
                    "kind": edge.kind.value,
                    "contract_id": edge.contract_id,
                    "fact_path": edge.fact_path,
                    "obligation": edge.obligation,
                    "source": edge.source.value,
                    "conditional_rule_ids": list(edge.conditional_rule_ids),
                }
                for edge in self.memberships
            ]
            + [
                {
                    "kind": edge.kind.value,
                    "upstream_contract_id": edge.upstream_contract_id,
                    "dependent_contract_id": edge.dependent_contract_id,
                    "repair_owner": edge.repair_owner,
                    "repair_policy_id": edge.repair_policy_id,
                }
                for edge in self.scheduling_edges
            ]
            + [
                {
                    "kind": edge.kind.value,
                    "left_contract_id": edge.left_contract_id,
                    "right_contract_id": edge.right_contract_id,
                    "shared_fact_paths": list(edge.shared_fact_paths),
                    "reciprocal": edge.reciprocal,
                }
                for edge in self.consistency_edges
            ],
            "findings": [
                {
                    "code": finding.code,
                    "severity": finding.severity,
                    "location": finding.location,
                    "message": finding.message,
                }
                for finding in self.findings
            ],
        }

    def projection_sha256(self) -> str:
        return _digest(self.projection())


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def _digest(payload: Any) -> str:
    blob = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(blob).hexdigest()


def _normalise_fact_paths(changed_fact_paths: Iterable[str]) -> tuple[str, ...]:
    paths = {value.strip() for value in changed_fact_paths}
    paths.discard("")
    return tuple(sorted(paths))


def _unresolved_hard_edge_nodes(
    scheduling_edges: tuple[SchedulingEdge, ...], known: set[str]
) -> tuple[str, ...]:
    """Nodes whose hard-edge order cannot be resolved (a cycle is present)."""
    indegree = {contract_id: 0 for contract_id in known}
    dependents: dict[str, list[str]] = {contract_id: [] for contract_id in known}
    for edge in scheduling_edges:
        if (
            edge.upstream_contract_id in known
            and edge.dependent_contract_id in known
        ):
            indegree[edge.dependent_contract_id] += 1
            dependents[edge.upstream_contract_id].append(edge.dependent_contract_id)
    ready = deque(sorted(cid for cid, degree in indegree.items() if degree == 0))
    resolved = 0
    while ready:
        contract_id = ready.popleft()
        resolved += 1
        for dependent in dependents[contract_id]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    if resolved == len(known):
        return ()
    return tuple(sorted(cid for cid, degree in indegree.items() if degree > 0))


def build_dependency_graph(source: GraphSource) -> DependencyGraph:
    """Build the typed dependency/impact graph for an accepted registry.

    ``source`` may be an already-loaded
    :class:`~app.protocol_workflow.registries.chapters.ChapterRegistryDocument`,
    a filesystem path or an already-parsed mapping; paths and mappings are
    loaded through the existing fail-closed ``load_chapter_registry``.

    Raises :class:`DependencyGraphError` when explicit ``dependency_ids`` form a
    hard scheduling cycle: a cyclic hard edge is not admitted into the DAG, and
    reciprocal consistency links never legalise it.
    """
    document = (
        source
        if isinstance(source, ChapterRegistryDocument)
        else load_chapter_registry(source)
    )

    nodes = tuple(
        sorted(
            (
                ChapterNode(
                    contract_id=entry.contract.chapter_contract_id,
                    node_id=entry.node_id,
                    coverage_role=entry.coverage_role,
                )
                for entry in document.chapters
            ),
            key=lambda node: node.contract_id,
        )
    )
    known = {node.contract_id for node in nodes}

    memberships: list[FactMembership] = []
    scheduling_edges: list[SchedulingEdge] = []
    findings: list[GraphFinding] = []

    for entry in sorted(document.chapters, key=lambda item: item.node_id):
        contract = entry.contract
        contract_id = contract.chapter_contract_id
        for requirement in contract.substantive_content.fact_requirements:
            memberships.append(
                FactMembership(
                    contract_id=contract_id,
                    fact_path=requirement.fact_path,
                    obligation=requirement.obligation.value,
                    source=MembershipSource.FACT_REQUIREMENT,
                )
            )
        for rule in contract.conditional_applicability_rules:
            rule_ids = (rule.conditional_applicability_rule_id,)
            for fact_path in rule.triggering_fact_paths:
                memberships.append(
                    FactMembership(
                        contract_id=contract_id,
                        fact_path=fact_path,
                        obligation=None,
                        source=MembershipSource.CONDITIONAL_TRIGGER,
                        conditional_rule_ids=rule_ids,
                    )
                )
            for fact_path in rule.required_when_active_fact_paths:
                memberships.append(
                    FactMembership(
                        contract_id=contract_id,
                        fact_path=fact_path,
                        obligation=None,
                        source=MembershipSource.CONDITIONAL_WHEN_ACTIVE,
                        conditional_rule_ids=rule_ids,
                    )
                )

        policy = contract.dependency_repair_policy
        covered = set(policy.dependency_ids) if policy is not None else set()
        for dependency_id in contract.dependency_ids:
            has_owner = policy is not None and dependency_id in covered
            location = f"{dependency_id}->{contract_id}"
            scheduling_edges.append(
                SchedulingEdge(
                    upstream_contract_id=dependency_id,
                    dependent_contract_id=contract_id,
                    repair_owner=policy.repair_owner.value if has_owner else None,
                    repair_policy_id=(
                        policy.dependency_repair_policy_id if has_owner else None
                    ),
                )
            )
            if dependency_id not in known:
                findings.append(
                    GraphFinding(
                        code=UNKNOWN_DEPENDENCY_TARGET,
                        severity="error",
                        location=location,
                        message=(
                            "declared dependency target is not an accepted "
                            "carrier in this registry; the edge is kept and "
                            "identified, never silently dropped"
                        ),
                    )
                )
            if not has_owner:
                findings.append(
                    GraphFinding(
                        code=MISSING_REPAIR_OWNER,
                        severity="error",
                        location=location,
                        message=(
                            "declared dependency has no repair owner in the "
                            "chapter repair policy; drift cannot be assigned"
                        ),
                    )
                )

    memberships.sort(
        key=lambda item: (
            item.contract_id,
            item.fact_path,
            item.source.value,
            item.conditional_rule_ids,
        )
    )

    carriers: dict[str, set[str]] = {}
    for membership in memberships:
        carriers.setdefault(membership.fact_path, set()).add(membership.contract_id)
    shared_facts: dict[tuple[str, str], set[str]] = {}
    for fact_path, contract_ids in carriers.items():
        if len(contract_ids) < 2:
            continue
        for left, right in itertools.combinations(sorted(contract_ids), 2):
            shared_facts.setdefault((left, right), set()).add(fact_path)
    consistency_edges = tuple(
        ConsistencyEdge(
            left_contract_id=left,
            right_contract_id=right,
            shared_fact_paths=tuple(sorted(paths)),
        )
        for (left, right), paths in sorted(shared_facts.items())
    )

    scheduling_tuple = tuple(scheduling_edges)
    unresolved = _unresolved_hard_edge_nodes(scheduling_tuple, known)
    if unresolved:
        raise DependencyGraphError(
            "hard scheduling cycle: explicit dependency_ids form an "
            "unresolvable order among "
            f"{list(unresolved)}; hard edges are not admitted into the DAG "
            "and reciprocal consistency links never legalise a cycle"
        )

    return DependencyGraph(
        template_id=document.template_id,
        registry_sha256=sha256(
            document.model_dump_json().encode("utf-8")
        ).hexdigest(),
        nodes=nodes,
        memberships=tuple(memberships),
        scheduling_edges=scheduling_tuple,
        consistency_edges=consistency_edges,
        findings=tuple(sorted(findings, key=lambda item: (item.code, item.location))),
    )
