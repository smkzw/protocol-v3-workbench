"""Registry-level typed dependency / impact graph for Protocol v3 (Task 3R.4).

This module is registry infrastructure only: it indexes an accepted
:class:`~app.protocol_workflow.registries.chapters.ChapterRegistryDocument`
into an explicit, typed edge structure and computes deterministic impact sets.
It authors no clinical content, decides no medical or QC judgment, calls no
product model, and writes nothing.  Its output is structural impact only —
never a medical approval; actual adoption is 3R.4D's responsibility inside one
unit of work (calling these pure functions twice with equal results is not
adoption idempotency).

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

Fact-labeled propagation (3R.4C)
--------------------------------
Impact propagation carries the set of *actually changed* fact paths as labels.
A ``consistency_impact`` edge may only forward the labels its ``shared_fact_paths``
actually carry, and it never overrides the receiving chapter's own decidedness
for a path it declares — obligation decidedness is per contract, so neither a
consistency link nor another chapter's decided owner on the same field may
flip a chapter's own conditional decision.  A chapter that shares only
*unchanged* facts is never reopened across a consistency bridge (the
reproduced owner counterexample A{x}, B{x,y}, C{y}: changing x affects A and B
directly; C is reopened only when y itself is actually changed, e.g. by an
explicit derivation in the same unit of work).  A ``scheduling`` edge
forwards the full upstream label set: the real downstream fan-out is never
truncated, but a scheduling-reached chapter never fabricates labels for its
own unchanged facts, so it cannot seed further consistency propagation.  Every
affected chapter keeps its reason (direct / consistency / scheduling), its via
fact paths and — in the plan — its via contract chain.

Obligation decidedness mirrors B's accepted shared-owner semantics
(``_project_obligations``): a declared fact_requirement is only unconditional
when no rule of its contract controls it through ``conditional_fact_paths``;
for controlled requirements and when-active obligations any applicable owner
keeps the obligation active, a determinate release requires every owner
resolved not_applicable (stale content is then refreshed), and with no
applicable owner plus any unresolved owner the field stays undecided — a
candidate, never silently read as false.

Two entry points exist deliberately:

* :meth:`DependencyGraph.impact` — the legacy diagnostic projection over the
  graph.  Since 3R.4C it is fact-labeled too (the over-bridge defect is fixed
  in the shared engine), but it accepts changed paths at face value without
  value verification.
* :func:`build_fact_labeled_impact_plan` — the adoption-grade plan consumed by
  3R.4D: it diffs native JSON before/after fact values (preserving ``false``
  vs ``0`` type differences; equal values fabricate no change), translates
  canonical keys into the contract vocabulary through B's
  ``affected_chapter_fact_paths`` (alias keys are literal; dotted keys are
  never split into member addresses), evaluates conditional rules with B's
  source-bound three-state predicates (unknown stays a candidate and never
  directly invalidates confirmed content; ``false`` is never read as a missing
  value; no clinical causality is inferred from an ``all`` combination), and
  refuses execution on graphs with structural findings.

Purity / CAS declaration
------------------------
``build_dependency_graph``, :meth:`DependencyGraph.impact` and
:func:`build_fact_labeled_impact_plan` are pure functions of their inputs.
The module keeps no store, no cache and no module-level mutable state.

``impact_sha256`` and ``plan_sha256`` are *projection hashes*: they identify
one impact projection over one registry, nothing more.  Two historically
distinct adoptions (for example a dose increase and its later revert) produce
the same projection hash, so neither hash may be used as a project-level
adoption idempotency key — D must bind base revision, operation key and the
actual fact changes in its own unit of work.

Every identified structural defect is reported, never silently dropped:
unknown dependency targets and declared dependencies without a repair owner are
typed error findings on the graph (the graph stays viewable for diagnosis, but
:meth:`FactLabeledImpactPlan.require_executable` refuses to hand such a graph
to an executable writing plan), and a hard scheduling cycle rejects the graph
outright.
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

from app.protocol_workflow.registries.applicability import (
    ApplicabilityStatus,
    RulePredicate,
    evaluate_predicates,
)
from app.protocol_workflow.registries.chapters import (
    ChapterRegistryDocument,
    load_chapter_registry,
)
from app.protocol_workflow.registries.fact_bindings import (
    FactBinding,
    _json,
    affected_chapter_fact_paths,
)

__all__ = [
    "GRAPH_SCHEMA_VERSION",
    "MISSING_REPAIR_OWNER",
    "PLAN_SCHEMA_VERSION",
    "UNKNOWN_DEPENDENCY_TARGET",
    "AffectedChapterPlan",
    "ChapterNode",
    "ConditionalRulePlan",
    "ConsistencyEdge",
    "DependencyGraph",
    "DependencyGraphError",
    "EdgeKind",
    "FactLabeledImpactPlan",
    "FactMembership",
    "GraphFinding",
    "ImpactPlanNotExecutable",
    "ImpactReason",
    "ImpactReport",
    "MembershipSource",
    "ProjectionRefresh",
    "SchedulingEdge",
    "build_dependency_graph",
    "build_fact_labeled_impact_plan",
    "fact_bindings_plan_hash",
]

#: Schema identity of the rendered graph projection.
GRAPH_SCHEMA_VERSION = "protocol-v3-dependency-graph.v1"

#: Schema identity of the fact-labeled impact plan.
PLAN_SCHEMA_VERSION = "protocol-v3-fact-labeled-impact-plan.v1"

#: Findings that identify a registry-level defect instead of a hard rejection.
UNKNOWN_DEPENDENCY_TARGET = "unknown_dependency_target"
MISSING_REPAIR_OWNER = "missing_repair_owner"

#: Anything the existing fail-closed chapter loader accepts.
GraphSource = Union[ChapterRegistryDocument, str, Path, Mapping[str, Any]]


class DependencyGraphError(ValueError):
    """Raised when the registry cannot form a sound scheduling DAG."""


class ImpactPlanNotExecutable(ValueError):
    """The graph carries structural findings; the plan is diagnostic only."""

    def __init__(self, findings: Iterable[GraphFinding]) -> None:
        self.findings = tuple(findings)
        super().__init__(
            "graph carries structural findings; the impact plan stays viewable "
            "for diagnosis but cannot produce an executable writing plan: "
            + "; ".join(f"{item.code}:{item.location}" for item in self.findings)
        )


class EdgeKind(str, Enum):
    """The three relationship kinds kept explicitly distinct."""

    FACT_MEMBERSHIP = "fact_membership"
    SCHEDULING = "scheduling"
    CONSISTENCY_IMPACT = "consistency_impact"


class ImpactReason(str, Enum):
    """Why one chapter is part of a fact-labeled impact plan."""

    DIRECT_FACT_USE = "direct_fact_use"
    CONSISTENCY_IMPACT = "consistency_impact"
    SCHEDULING = "scheduling"


class MembershipSource(str, Enum):
    """Where a fact membership was declared in the chapter contract."""

    FACT_REQUIREMENT = "fact_requirement"
    CONDITIONAL_TRIGGER = "conditional_trigger"
    CONDITIONAL_WHEN_ACTIVE = "conditional_when_active"


#: Dispositions of one conditional rule under the before/after facts.
DISPOSITION_STABLE = "stable"
DISPOSITION_OBLIGATION_CHANGE = "obligation_change"
DISPOSITION_PENDING_FACTS = "pending_facts"

#: Chapter-level confirmation outcomes of a plan.
CONFIRMATION_REOPEN = "confirmed_reopen"
CONFIRMATION_CANDIDATE = "candidate_check"


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
    """Deterministic impact of one changed-material-fact update.

    Legacy diagnostic projection; see :meth:`DependencyGraph.impact`.
    ``impact_sha256`` is a projection hash, not an adoption work key.
    """

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
class ConditionalRulePlan:
    """One conditional rule's three-state disposition for one chapter.

    States carry B's raw three-state values (``applicable`` /
    ``not_applicable`` / ``conditional``); ``None`` means no executable
    declaration exists.  Any unresolved side makes the disposition
    ``pending_facts`` — unknown stays a candidate and never directly
    invalidates confirmed content.  An ``all`` combination is never decomposed
    into per-fact clinical causality: the disposition is recorded per rule
    only.
    """

    contract_id: str
    rule_id: str
    changed_triggering_fact_paths: tuple[str, ...]
    state_before: Optional[str]
    state_after: Optional[str]
    disposition: str


@dataclass(frozen=True)
class AffectedChapterPlan:
    """One affected chapter with its reason, labels and rule dispositions."""

    contract_id: str
    reason: ImpactReason
    confirmation: str
    via_fact_paths: tuple[str, ...]
    via_contract_ids: tuple[str, ...]
    rule_plans: tuple[ConditionalRulePlan, ...] = ()


@dataclass(frozen=True)
class ProjectionRefresh:
    """A display-only alias movement; never a confirmed reopen."""

    contract_id: str
    fact_path: str
    canonical_path: str


@dataclass(frozen=True)
class FactLabeledImpactPlan:
    """Adoption-grade deterministic impact plan consumed by 3R.4D.

    Candidate repairs (:data:`CONFIRMATION_CANDIDATE` — unresolved
    applicability, projection refreshes) stay strictly separate from chapters
    whose confirmed content must actually be re-confirmed
    (:data:`CONFIRMATION_REOPEN`).  ``plan_sha256`` is a projection hash, not
    a logical work key; the plan is not a medical approval and not an
    adoption.
    """

    plan_schema_version: str
    graph_schema_version: str
    template_id: str
    registry_sha256: str
    changed_canonical_paths: tuple[str, ...]
    changed_fact_paths: tuple[str, ...]
    unmapped_canonical_paths: tuple[str, ...]
    unindexed_fact_paths: tuple[str, ...]
    projection_refreshes: tuple[ProjectionRefresh, ...]
    entries: tuple[AffectedChapterPlan, ...]
    confirmed_reopen_contract_ids: tuple[str, ...]
    candidate_check_contract_ids: tuple[str, ...]
    fact_bindings_sha256: Optional[str]
    applicability_rules_sha256: Optional[str]
    findings: tuple[GraphFinding, ...]
    plan_sha256: str

    def affects(self, contract_id: str) -> bool:
        return any(entry.contract_id == contract_id for entry in self.entries)

    def entry_for(self, contract_id: str) -> Optional[AffectedChapterPlan]:
        return next(
            (
                entry
                for entry in self.entries
                if entry.contract_id == contract_id
            ),
            None,
        )

    def is_executable(self) -> bool:
        """False when the graph carries structural findings."""
        return not self.findings

    def require_executable(self) -> None:
        """Refuse an executable writing plan on a defective graph."""
        if self.findings:
            raise ImpactPlanNotExecutable(self.findings)


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

        Legacy diagnostic projection over the graph; propagation is
        fact-labeled (see module docstring).  The paths are taken at face
        value — for value-verified, alias-aware, applicability-aware planning
        use :func:`build_fact_labeled_impact_plan`.  Pure function of (this
        registry projection, changed facts); ``impact_sha256`` is a projection
        hash, not an adoption work key.
        """
        changed = _normalise_fact_paths(changed_fact_paths)
        carriers: dict[str, set[str]] = {}
        for membership in self.memberships:
            carriers.setdefault(membership.fact_path, set()).add(
                membership.contract_id
            )
        direct_contracts = sorted(
            {cid for path in changed for cid in carriers.get(path, ())}
        )
        seeds = {
            contract_id: {
                path: True for path in changed if contract_id in carriers[path]
            }
            for contract_id in direct_contracts
        }
        labels, reasons, _via = self._propagate_labels(seeds)
        direct_ids = tuple(sorted(seeds))
        consistency_ids = tuple(
            sorted(
                cid
                for cid, kind in reasons.items()
                if kind is EdgeKind.CONSISTENCY_IMPACT
            )
        )
        scheduling_ids = tuple(
            sorted(
                cid for cid, kind in reasons.items() if kind is EdgeKind.SCHEDULING
            )
        )
        affected_ids = tuple(sorted(labels))
        unindexed = tuple(path for path in changed if path not in carriers)
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

    def _propagate_labels(
        self, seeds: dict[str, dict[str, bool]]
    ) -> tuple[dict[str, dict[str, bool]], dict[str, EdgeKind], dict[str, tuple[str, ...]]]:
        """Fact-labeled propagation over the typed edges.

        ``seeds`` maps each directly affected chapter to its initial label set
        (changed path -> resolved state).  Returns the final label set per
        affected chapter, the first-discovery reason for every non-seed
        chapter, and the via-contract chain recorded at discovery.

        Consistency edges forward only the labels they actually share, so
        unchanged shared facts never bridge an impact, and a consistency
        delivery never overrides the receiving chapter's own decidedness for
        a path it declares (obligation decidedness is per contract).  Scheduling
        edges forward the full upstream label set (real fan-out is never
        truncated) but a scheduling-reached chapter fabricates no labels of
        its own and therefore cannot seed further consistency propagation.
        Deterministic: waves are sorted and consistency delivery is
        considered before scheduling delivery within a wave.
        """
        shared: dict[frozenset[str], set[str]] = {}
        neighbours: dict[str, set[str]] = {}
        for edge in self.consistency_edges:
            key = frozenset((edge.left_contract_id, edge.right_contract_id))
            shared.setdefault(key, set()).update(edge.shared_fact_paths)
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

        labels: dict[str, dict[str, bool]] = {
            contract_id: dict(paths) for contract_id, paths in seeds.items()
        }
        seen = set(labels)
        discovered: dict[str, EdgeKind] = {}
        via: dict[str, set[str]] = {}
        frontier = sorted(labels)
        while frontier:
            deliveries: list[tuple[EdgeKind, str, str, dict[str, bool]]] = []
            for contract_id in frontier:
                outgoing = labels[contract_id]
                for neighbour in sorted(neighbours.get(contract_id, ())):
                    shared_paths = shared.get(
                        frozenset((contract_id, neighbour)), frozenset()
                    )
                    carry = {
                        path: state
                        for path, state in outgoing.items()
                        if path in shared_paths
                    }
                    if carry:
                        deliveries.append(
                            (EdgeKind.CONSISTENCY_IMPACT, contract_id, neighbour, carry)
                        )
            for contract_id in frontier:
                outgoing = labels[contract_id]
                if not outgoing:
                    continue
                for dependent in sorted(dependents.get(contract_id, ())):
                    deliveries.append(
                        (EdgeKind.SCHEDULING, contract_id, dependent, dict(outgoing))
                    )
            deliveries.sort(
                key=lambda item: (item[0].value, item[1], item[2])
            )
            next_frontier: set[str] = set()
            for kind, source, target, carry in deliveries:
                merged = labels.setdefault(target, {})
                grew = False
                for path, state in carry.items():
                    if kind is EdgeKind.CONSISTENCY_IMPACT and path in merged:
                        # Obligation decidedness is per contract: a
                        # consistency link never overrides the target's own
                        # conditional decision for a path it declares.
                        continue
                    if path not in merged:
                        merged[path] = state
                        grew = True
                    elif state and not merged[path]:
                        merged[path] = True
                        grew = True
                if target not in seen:
                    seen.add(target)
                    discovered[target] = kind
                    via[target] = {source}
                    next_frontier.add(target)
                elif grew:
                    next_frontier.add(target)
            frontier = sorted(next_frontier)
        return labels, discovered, {
            contract_id: tuple(sorted(sources))
            for contract_id, sources in via.items()
        }

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
# Fact-labeled impact plan (3R.4C; consumed by 3R.4D adoption)
# ---------------------------------------------------------------------------


def fact_bindings_plan_hash(bindings: Iterable[FactBinding]) -> str:
    """Deterministic identity of the binding set a plan was built with.

    Projection hash over the explicit ``FactBinding`` declarations; pairing a
    plan with B's ``load_fact_catalog`` (which validates the whole catalog
    against the registry) is what proves source binding.
    """
    items = list(bindings)
    index: dict[str, FactBinding] = {}
    for binding in items:
        if binding.fact_path in index:
            raise DependencyGraphError(
                f"duplicate fact binding declaration: {binding.fact_path!r}"
            )
        index[binding.fact_path] = binding
    return _digest(
        [
            index[path].model_dump(mode="json")
            for path in sorted(index)
        ]
    )


def _diff_fact_values(
    facts_before: Mapping[str, Any], facts_after: Mapping[str, Any]
) -> tuple[str, ...]:
    """Literal-key diff preserving native JSON type differences.

    ``False`` and ``0`` never compare equal; the same fact with the same value
    fabricates no change; keys are compared literally and dotted keys are
    never split into member addresses.
    """
    changed: list[str] = []
    for path in sorted(set(facts_before) | set(facts_after)):
        if path not in facts_before or path not in facts_after:
            changed.append(path)
            continue
        try:
            before_blob = _json(facts_before[path])
            after_blob = _json(facts_after[path])
        except (ValueError, TypeError) as exc:
            raise DependencyGraphError(
                f"fact {path!r} value is not canonical JSON: {exc}"
            ) from None
        if before_blob != after_blob:
            changed.append(path)
    return tuple(changed)


def _rule_state(
    declaration: Optional[RulePredicate], facts: Mapping[str, Any]
) -> Optional[str]:
    """B's three-state evaluation; ``None`` when the rule cannot resolve."""
    if declaration is None:
        return None
    status = evaluate_predicates(
        declaration.predicates, facts, mode=declaration.mode
    )
    return status.value


def build_fact_labeled_impact_plan(
    graph: DependencyGraph,
    *,
    facts_before: Mapping[str, Any],
    facts_after: Mapping[str, Any],
    bindings: Iterable[FactBinding] = (),
    rules: Iterable[RulePredicate] = (),
) -> FactLabeledImpactPlan:
    """Deterministic adoption-grade impact plan over one graph projection.

    Args:
        graph: the accepted registry projection (from
            :func:`build_dependency_graph`).
        facts_before / facts_after: canonical ``StudyDefinition.facts``
            mappings before and after the unit of work.  A path is an actual
            change only when its native JSON value differs (type-preserving);
            equal values fabricate nothing and missing keys are changes, not
            implicit ``False``.
        bindings: B's :class:`~app.protocol_workflow.registries.fact_bindings.FactBinding`
            declarations (from the current ``fact_bindings.json`` catalog).
            Canonical changes are translated into contract vocabulary with
            ``affected_chapter_fact_paths``; an input key that is itself a
            binding alias (its canonical owner did not change) becomes a
            display-only :class:`ProjectionRefresh` that never reopens the
            canonical owner.  Without bindings, input keys are used as literal
            contract fact paths.
        rules: B's :class:`~app.protocol_workflow.registries.applicability.RulePredicate`
            declarations (from the current ``applicability_rules.json``
            catalog).  Conditional involvement resolves only through these
            source-bound three-state predicates; unknown stays a candidate and
            never directly invalidates confirmed content.

    Returns:
        :class:`FactLabeledImpactPlan` — view the plan, then call
        :meth:`FactLabeledImpactPlan.require_executable` before consuming it
        as a writing plan.  The plan is a projection: not a medical approval
        and not an adoption; D binds actual adoption in its own unit of work
        with its own operation key (``plan_sha256`` is not a work key).
    """
    if not isinstance(facts_before, Mapping) or not isinstance(facts_after, Mapping):
        raise DependencyGraphError(
            "facts_before and facts_after must be canonical fact mappings"
        )
    changed_canonical = _diff_fact_values(facts_before, facts_after)

    binding_index: dict[str, FactBinding] = {}
    for binding in bindings:
        if binding.fact_path in binding_index:
            raise DependencyGraphError(
                f"duplicate fact binding declaration: {binding.fact_path!r}"
            )
        binding_index[binding.fact_path] = binding

    alias_keys = {
        path
        for path, binding in binding_index.items()
        if binding.canonical_path is not None and binding.canonical_path != path
    }
    projection_keys = sorted(set(changed_canonical) & alias_keys)
    canonical_inputs = [path for path in changed_canonical if path not in projection_keys]
    if binding_index:
        changed_contract_paths = affected_chapter_fact_paths(
            binding_index.values(), canonical_inputs
        )
        canonical_universe = {
            binding.canonical_path
            for binding in binding_index.values()
            if binding.canonical_path is not None
        }
        unmapped = tuple(
            path for path in changed_canonical
            if path not in projection_keys and path not in canonical_universe
        )
    else:
        changed_contract_paths = tuple(sorted(canonical_inputs))
        unmapped = ()

    projection_refreshes = tuple(
        ProjectionRefresh(
            contract_id=contract_id,
            fact_path=path,
            canonical_path=(
                binding_index[path].canonical_path
                if binding_index[path].canonical_path is not None
                else path
            ),
        )
        for path in projection_keys
        for contract_id in graph.contracts_for_fact(path)
    )

    carriers: dict[str, set[str]] = {}
    memberships_by_pair: dict[tuple[str, str], list[FactMembership]] = {}
    for membership in graph.memberships:
        carriers.setdefault(membership.fact_path, set()).add(membership.contract_id)
        memberships_by_pair.setdefault(
            (membership.contract_id, membership.fact_path), []
        ).append(membership)

    rule_index: dict[str, RulePredicate] = {}
    for declaration in rules:
        if declaration.rule_id in rule_index:
            raise DependencyGraphError(
                f"duplicate applicability rule declaration: {declaration.rule_id!r}"
            )
        rule_index[declaration.rule_id] = declaration
    rules_digest = (
        _digest(
            {
                "rules": [
                    rule_index[rule_id].model_dump(mode="json")
                    for rule_id in sorted(rule_index)
                ]
            }
        )
        if rule_index
        else None
    )

    rules_by_contract: dict[str, set[str]] = {}
    for membership in graph.memberships:
        for rule_id in membership.conditional_rule_ids:
            rules_by_contract.setdefault(membership.contract_id, set()).add(rule_id)

    applicable_value = ApplicabilityStatus.APPLICABLE.value
    not_applicable_value = ApplicabilityStatus.NOT_APPLICABLE.value

    def _label_resolved(contract_id: str, path: str) -> bool:
        """Decidedness of this chapter's effective obligations on one path.

        Mirrors B's accepted shared-owner semantics (``_project_obligations``):
        any applicable owner keeps the obligation active (shared active owner
        wins); a determinate release needs every owner resolved
        not_applicable (the stale content must then be refreshed); with no
        applicable owner and any unresolved owner the field stays undecided —
        pending, never silently read as false.  A declared fact_requirement
        is only unconditional when no rule of the same contract controls it
        through ``conditional_fact_paths``; if any rule of the contract lacks
        an executable declaration the requirement cannot be proven
        unconditional either.
        """
        memberships = memberships_by_pair.get((contract_id, path), ())
        if not memberships:
            return False

        def owner_state(rule_id: str) -> Optional[str]:
            return _rule_state(rule_index.get(rule_id), facts_after)

        def owners_decided(rule_ids) -> bool:
            states = [owner_state(rule_id) for rule_id in rule_ids]
            if any(state == applicable_value for state in states):
                return True
            return bool(states) and all(
                state == not_applicable_value for state in states
            )

        contract_rules = rules_by_contract.get(contract_id, set())
        undeclared_rule = any(
            rule_id not in rule_index for rule_id in contract_rules
        )
        decisive = False
        for membership in memberships:
            if membership.source is MembershipSource.CONDITIONAL_TRIGGER:
                for rule_id in membership.conditional_rule_ids:
                    if owner_state(rule_id) in (
                        applicable_value,
                        not_applicable_value,
                    ):
                        decisive = True
            elif membership.source is MembershipSource.CONDITIONAL_WHEN_ACTIVE:
                if owners_decided(membership.conditional_rule_ids):
                    decisive = True
            else:  # FACT_REQUIREMENT
                controlling = tuple(
                    rule_id
                    for rule_id in contract_rules
                    if rule_id in rule_index
                    and path in rule_index[rule_id].conditional_fact_paths
                )
                if not controlling:
                    if not undeclared_rule:
                        decisive = True  # plain unconditional declared fact
                elif owners_decided(controlling):
                    decisive = True
        return decisive

    seeds: dict[str, dict[str, bool]] = {}
    for path in changed_contract_paths:
        for contract_id in sorted(carriers.get(path, ())):
            seeds.setdefault(contract_id, {})[path] = _label_resolved(
                contract_id, path
            )
    labels, reasons, via = graph._propagate_labels(seeds)

    entries: list[AffectedChapterPlan] = []
    for contract_id in sorted(labels):
        chapter_labels = labels[contract_id]
        if contract_id in seeds:
            reason = ImpactReason.DIRECT_FACT_USE
        else:
            edge_kind = reasons[contract_id]
            reason = (
                ImpactReason.CONSISTENCY_IMPACT
                if edge_kind is EdgeKind.CONSISTENCY_IMPACT
                else ImpactReason.SCHEDULING
            )
        rule_plans: dict[str, ConditionalRulePlan] = {}
        for path in sorted(chapter_labels):
            for membership in memberships_by_pair.get((contract_id, path), ()):
                for rule_id in membership.conditional_rule_ids:
                    if rule_id in rule_plans:
                        continue
                    state_before = _rule_state(rule_index.get(rule_id), facts_before)
                    state_after = _rule_state(rule_index.get(rule_id), facts_after)
                    unresolved = (
                        state_before is None
                        or state_after is None
                        or state_before == ApplicabilityStatus.CONDITIONAL.value
                        or state_after == ApplicabilityStatus.CONDITIONAL.value
                    )
                    if unresolved:
                        disposition = DISPOSITION_PENDING_FACTS
                    elif state_before == state_after:
                        disposition = DISPOSITION_STABLE
                    else:
                        disposition = DISPOSITION_OBLIGATION_CHANGE
                    rule_plans[rule_id] = ConditionalRulePlan(
                        contract_id=contract_id,
                        rule_id=rule_id,
                        changed_triggering_fact_paths=tuple(
                            sorted(
                                other
                                for other in chapter_labels
                                if any(
                                    item.source is MembershipSource.CONDITIONAL_TRIGGER
                                    and rule_id in item.conditional_rule_ids
                                    for item in memberships_by_pair.get(
                                        (contract_id, other), ()
                                    )
                                )
                            )
                        ),
                        state_before=state_before,
                        state_after=state_after,
                        disposition=disposition,
                    )
        entries.append(
            AffectedChapterPlan(
                contract_id=contract_id,
                reason=reason,
                confirmation=(
                    CONFIRMATION_REOPEN
                    if any(chapter_labels.values())
                    else CONFIRMATION_CANDIDATE
                ),
                via_fact_paths=tuple(sorted(chapter_labels)),
                via_contract_ids=via.get(contract_id, ()),
                rule_plans=tuple(rule_plans[rule_id] for rule_id in sorted(rule_plans)),
            )
        )

    confirmed = tuple(
        entry.contract_id
        for entry in entries
        if entry.confirmation == CONFIRMATION_REOPEN
    )
    candidates = tuple(
        entry.contract_id
        for entry in entries
        if entry.confirmation == CONFIRMATION_CANDIDATE
    )
    unindexed = tuple(
        path for path in changed_contract_paths if path not in carriers
    )
    digest_payload = {
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "graph_schema_version": GRAPH_SCHEMA_VERSION,
        "template_id": graph.template_id,
        "registry_sha256": graph.registry_sha256,
        "changed_canonical_paths": list(changed_canonical),
        "changed_fact_paths": list(changed_contract_paths),
        "unmapped_canonical_paths": list(unmapped),
        "unindexed_fact_paths": list(unindexed),
        "projection_refreshes": [
            {
                "contract_id": item.contract_id,
                "fact_path": item.fact_path,
                "canonical_path": item.canonical_path,
            }
            for item in projection_refreshes
        ],
        "entries": [
            {
                "contract_id": entry.contract_id,
                "reason": entry.reason.value,
                "confirmation": entry.confirmation,
                "via_fact_paths": list(entry.via_fact_paths),
                "via_contract_ids": list(entry.via_contract_ids),
                "rule_plans": [
                    {
                        "rule_id": item.rule_id,
                        "changed_triggering_fact_paths": list(
                            item.changed_triggering_fact_paths
                        ),
                        "state_before": item.state_before,
                        "state_after": item.state_after,
                        "disposition": item.disposition,
                    }
                    for item in entry.rule_plans
                ],
            }
            for entry in entries
        ],
        "confirmed_reopen_contract_ids": list(confirmed),
        "candidate_check_contract_ids": list(candidates),
        "fact_bindings_sha256": (
            fact_bindings_plan_hash(binding_index.values()) if binding_index else None
        ),
        "applicability_rules_sha256": rules_digest,
        "findings": [
            {
                "code": item.code,
                "severity": item.severity,
                "location": item.location,
                "message": item.message,
            }
            for item in graph.findings
        ],
    }
    return FactLabeledImpactPlan(
        plan_schema_version=PLAN_SCHEMA_VERSION,
        graph_schema_version=GRAPH_SCHEMA_VERSION,
        template_id=graph.template_id,
        registry_sha256=graph.registry_sha256,
        changed_canonical_paths=changed_canonical,
        changed_fact_paths=changed_contract_paths,
        unmapped_canonical_paths=unmapped,
        unindexed_fact_paths=unindexed,
        projection_refreshes=projection_refreshes,
        entries=tuple(entries),
        confirmed_reopen_contract_ids=confirmed,
        candidate_check_contract_ids=candidates,
        fact_bindings_sha256=(
            fact_bindings_plan_hash(binding_index.values()) if binding_index else None
        ),
        applicability_rules_sha256=rules_digest,
        findings=graph.findings,
        plan_sha256=_digest(digest_payload),
    )


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
