"""Protocol v3 orchestrator PoC — objective-estimand-endpoint case graph
(Task 2.1, worker 02).

Immutable typed definition of the objective → estimand-attributes → endpoint
→ cross-objective-consistency workflow: objective, complete estimand
attribute set, endpoint definition/tool/timepoint and cross-objective
consistency stay linked; a missing link cannot satisfy the final decision
Gate.

This module is a *pure typed definition* built from Worker 01's shared
vocabulary (:mod:`pocs.protocol_v3.orchestrator`): no scheduler, no runtime,
no clinical truth stored in graph state.  The registry loader
(:func:`pocs.protocol_v3.orchestrator.cases.load_case`) requires this module
to export ``GRAPH: CaseGraph`` bound to
:class:`CaseId.OBJECTIVE_ESTIMAND_ENDPOINT`.

Topology (maps to the accepted design ``mw_protocol_multi_agent_rearchitecture_design_20260809.md`` §10.1/§10.2: O: objective→estimand→endpoint、窗口/基线/工具/评估者/伴发事件/缺失):

* ``define_objectives`` — Agent② clinical worker drafts the study objectives
  from labeled synthetic study facts.  D1 design-consistency gate.
* ``define_estimand_attributes`` — Agent② statistical/estimand worker
  defines, per objective, the complete estimand attribute set: population,
  variable/endpoint, intercurrent events, summary measure and analysis
  method (standard estimand attribute dimensions per design §10.2).  A
  partial attribute set is not a complete artifact.  D1 gate.
* ``define_endpoint`` — Agent② defines each endpoint's definition, assessment
  tool and timepoint/assessment window; definition/tool/timepoint must be
  complete.  D1 gate.
* ``cross_objective_consistency`` — deterministic system reducer that links
  every objective→estimand→endpoint triple and flags missing or inconsistent
  links (an endpoint reused across objectives must share
  definition/tool/timepoint); it never completes a missing link.  D1 gate.
* ``qc_review_objective_chain`` — Agent④ fresh-context QC review point
  (design §13): typed findings, P0–P4 severity; clean requires
  ``open_count=0``.  Q1 gate.
* ``objective_chain_decision_lock`` — USER-owned decision Gate (design §5.4):
  the chain is adopted as a reason-coded DecisionRecord and can *only* be
  recorded when the consistency report and the QC verdict are present and
  clean — missing links stay open and block the Gate, never a default.  Also
  idempotent by decision key (design §14 CAS).
* ``finalize_objective_chain`` — deterministic freeze of the decided chain
  into the final locked artifact, consuming the decision record via a typed
  :class:`EdgeKind.DECISION` edge.  D1 gate.

Missing-link discipline is enforced structurally: the consistency node and
the lock node both require objective, estimand attributes and endpoint
artifacts as inputs, and the lock node carries
:class:`EdgeKind.GATE` edges from the consistency report (D1) and the Agent④
QC verdict (Q1) — removing any link fails closed at construction
(``CC_INPUT_UNCOVERED`` / ``CC_EDGE_UNMATCHED_DEPENDENCY``) or blocks the
lock at run time.

All five injection kinds are declared as :class:`InjectionPoint` records
(kill-before, kill-after, duplicate-resume, concurrent-decision,
old-graph-migration); they are represented, never executed.

Synthetic-only: every schema description is a labeled PoC placeholder.  No
patient data and no invented regulatory/scientific facts.
"""

from __future__ import annotations

from . import (
    CaseGraph,
    CaseId,
    Edge,
    EdgeKind,
    FailurePolicy,
    GateKind,
    InjectionKind,
    InjectionPoint,
    NodeContract,
    NodeKind,
    OwnerRole,
    SchemaDecl,
    SideEffectKind,
)

__all__ = [
    "GRAPH",
    "PROJECT_ID",
    "BRANCH_ID",
    "GRAPH_VERSION",
    "OLD_GRAPH_VERSION",
]

#: Stable project/branch identity shared by the three Task 2.1 case graphs so
#: one :class:`~pocs.protocol_v3.orchestrator.fakes.FakeRuntime` can bind to
#: all of them (fakes fail closed on mismatch, ``CC_BINDING_MISMATCH``).
PROJECT_ID = "mw-protocol-v3-poc"
BRANCH_ID = "orchestrator-poc-v1"

#: This graph's version and the labeled synthetic predecessor version that
#: never shipped (used by the old-graph-migration injection declaration).
GRAPH_VERSION = "objective_estimand_endpoint_graph_v1"
OLD_GRAPH_VERSION = "objective_estimand_endpoint_graph_v0"

# ---------------------------------------------------------------------------
# Closed per-case schema vocabulary (output artifacts + root inputs)
# ---------------------------------------------------------------------------

SCHEMAS = (
    SchemaDecl(
        name="study_facts",
        description=(
            "labeled synthetic study-fact container (population/design-intent "
            "facts) seeding the objective-estimand-endpoint case; PoC "
            "placeholder, no real patient data"
        ),
    ),
    SchemaDecl(
        name="objectives_draft",
        description=(
            "drafted study objectives artifact: objective id, primary/secondary "
            "flag, intent statement; unfinalized proposal"
        ),
    ),
    SchemaDecl(
        name="estimand_attributes",
        description=(
            "per-objective estimand attribute set artifact: population, "
            "variable/endpoint, intercurrent events, summary measure, analysis "
            "method (standard estimand attribute dimensions per the accepted "
            "design §10.2); a partial set is not a complete artifact"
        ),
    ),
    SchemaDecl(
        name="endpoint_definitions",
        description=(
            "per-estimand endpoint definition artifact: endpoint id, "
            "definition, assessment tool, timepoint/assessment window; "
            "definition/tool/timepoint must be complete"
        ),
    ),
    SchemaDecl(
        name="cross_objective_consistency_report",
        description=(
            "deterministic cross-objective consistency report: every "
            "objective→estimand→endpoint link present and consistent (an "
            "endpoint reused across objectives shares definition/tool/"
            "timepoint); flags missing links, never completes them"
        ),
    ),
    SchemaDecl(
        name="qc_findings",
        description=(
            "Agent④ fresh-context QC findings artifact for the objective "
            "chain: typed dispositions, P0-P4 severity, locator; clean "
            "requires open_count=0"
        ),
    ),
    SchemaDecl(
        name="objective_chain_lock_decision",
        description=(
            "reason-coded user DecisionRecord adopting the "
            "objective-estimand-endpoint chain; cannot be recorded while the "
            "consistency report or QC leaves missing links or open findings"
        ),
    ),
    SchemaDecl(
        name="locked_objective_chain",
        description=(
            "final immutable objective→estimand→endpoint chain artifact "
            "frozen from the decision record and all linked artifacts"
        ),
    ),
)

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

NODES = (
    NodeContract(
        node_id="define_objectives",
        kind=NodeKind.WORK,
        owner=OwnerRole.DESIGN_AND_SUMMARY,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("study_facts",),
        output_schema="objectives_draft",
        depends_on=(),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        side_effect_key_template="objective_estimand.objective.{objective_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="define_estimand_attributes",
        kind=NodeKind.WORK,
        owner=OwnerRole.DESIGN_AND_SUMMARY,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("objectives_draft",),
        output_schema="estimand_attributes",
        depends_on=("define_objectives",),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        side_effect_key_template=(
            "objective_estimand.estimand.{estimand_id}.{attribute_id}"
        ),
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="define_endpoint",
        kind=NodeKind.WORK,
        owner=OwnerRole.DESIGN_AND_SUMMARY,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("estimand_attributes",),
        output_schema="endpoint_definitions",
        depends_on=("define_estimand_attributes",),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        side_effect_key_template="objective_estimand.endpoint.{endpoint_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="cross_objective_consistency",
        kind=NodeKind.CHECK,
        owner=OwnerRole.SYSTEM,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=(
            "objectives_draft",
            "estimand_attributes",
            "endpoint_definitions",
        ),
        output_schema="cross_objective_consistency_report",
        depends_on=(
            "define_objectives",
            "define_estimand_attributes",
            "define_endpoint",
        ),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="objective_estimand.consistency.{report_id}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
    NodeContract(
        node_id="qc_review_objective_chain",
        kind=NodeKind.WORK,
        owner=OwnerRole.QUALITY_CONTROL,
        gate=GateKind.Q1_INDEPENDENT_QC,
        inputs=(
            "estimand_attributes",
            "endpoint_definitions",
            "cross_objective_consistency_report",
        ),
        output_schema="qc_findings",
        depends_on=(
            "define_estimand_attributes",
            "define_endpoint",
            "cross_objective_consistency",
        ),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="objective_estimand.qc.{finding_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="objective_chain_decision_lock",
        kind=NodeKind.DECISION,
        owner=OwnerRole.USER,
        gate=GateKind.USER_DECISION,
        inputs=(
            "objectives_draft",
            "estimand_attributes",
            "endpoint_definitions",
            "cross_objective_consistency_report",
            "qc_findings",
        ),
        output_schema="objective_chain_lock_decision",
        depends_on=(
            "define_objectives",
            "define_estimand_attributes",
            "define_endpoint",
            "cross_objective_consistency",
            "qc_review_objective_chain",
        ),
        side_effect_kind=SideEffectKind.DECISION_RECORD,
        side_effect_key_template="objective_estimand.lock.{revision}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
    NodeContract(
        node_id="finalize_objective_chain",
        kind=NodeKind.CHECK,
        owner=OwnerRole.SYSTEM,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=(
            "objective_chain_lock_decision",
            "objectives_draft",
            "estimand_attributes",
            "endpoint_definitions",
        ),
        output_schema="locked_objective_chain",
        depends_on=(
            "objective_chain_decision_lock",
            "define_objectives",
            "define_estimand_attributes",
            "define_endpoint",
        ),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="objective_estimand.finalize.{revision}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
)


def _edge(source: str, target: str, kind: EdgeKind = EdgeKind.DATA) -> Edge:
    """Typed dependency edge helper (data by default)."""
    return Edge(source_node_id=source, target_node_id=target, kind=kind)


EDGES = (
    _edge("define_objectives", "define_estimand_attributes"),
    _edge("define_estimand_attributes", "define_endpoint"),
    _edge("define_objectives", "cross_objective_consistency"),
    _edge("define_estimand_attributes", "cross_objective_consistency"),
    _edge("define_endpoint", "cross_objective_consistency"),
    _edge("define_estimand_attributes", "qc_review_objective_chain"),
    _edge("define_endpoint", "qc_review_objective_chain"),
    _edge("cross_objective_consistency", "qc_review_objective_chain"),
    _edge("define_objectives", "objective_chain_decision_lock"),
    _edge("define_estimand_attributes", "objective_chain_decision_lock"),
    _edge("define_endpoint", "objective_chain_decision_lock"),
    _edge(
        "cross_objective_consistency",
        "objective_chain_decision_lock",
        EdgeKind.GATE,
    ),
    _edge("qc_review_objective_chain", "objective_chain_decision_lock"),
    _edge(
        "qc_review_objective_chain",
        "objective_chain_decision_lock",
        EdgeKind.GATE,
    ),
    _edge(
        "objective_chain_decision_lock",
        "finalize_objective_chain",
        EdgeKind.DECISION,
    ),
    _edge("define_objectives", "finalize_objective_chain"),
    _edge("define_estimand_attributes", "finalize_objective_chain"),
    _edge("define_endpoint", "finalize_objective_chain"),
)

# ---------------------------------------------------------------------------
# Injection points — all five Task 2.1 kinds, represented, never executed
# ---------------------------------------------------------------------------

INJECTIONS = (
    InjectionPoint(
        injection_kind=InjectionKind.KILL_BEFORE,
        target_node_id="define_estimand_attributes",
        logical_key="objective_estimand.estimand.{estimand_id}.{attribute_id}",
        expectation=(
            "kill before the estimand-attributes node runs leaves no partial "
            "attribute set; deterministic resume re-runs the node from clean "
            "state; the artifact store stays idempotent by logical key "
            "(FK_IDEMPOTENCY_CONFLICT on conflicting writes)"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.KILL_AFTER,
        target_node_id="define_endpoint",
        logical_key="objective_estimand.endpoint.{endpoint_id}",
        expectation=(
            "kill after the endpoint artifact is written; resume reuses the "
            "existing artifact by logical key; no duplicate endpoint lineage "
            "or semantic effect"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.DUPLICATE_RESUME,
        target_node_id="objective_chain_decision_lock",
        logical_key="objective_estimand.lock.{revision}",
        expectation=(
            "duplicate resume of the same lock decision key returns the "
            "existing DecisionRecord (design §14 CAS); no second decision and "
            "no double state change"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.CONCURRENT_DECISION,
        target_node_id="objective_chain_decision_lock",
        logical_key="objective_estimand.lock.{revision}.claim",
        expectation=(
            "two actors claiming the same lock decision key fail closed "
            "(FK_CONCURRENT_DECISION); only the single claim holder may "
            "record, and exactly one DecisionRecord per revision is kept"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.OLD_GRAPH_MIGRATION,
        logical_key="objective_estimand.graph.migration",
        old_graph_version=OLD_GRAPH_VERSION,
        expectation=(
            "an old-version graph missing an estimand attribute or endpoint "
            "link (unknown/uncovered schema or unmatched dependency) fails "
            "closed (CC_SCHEMA_UNKNOWN / CC_INPUT_UNCOVERED / "
            "CC_EDGE_UNMATCHED_DEPENDENCY); migration never silently "
            "completes a missing objective→estimand→endpoint link"
        ),
    ),
)

# ---------------------------------------------------------------------------
# Closed immutable graph definition
# ---------------------------------------------------------------------------

GRAPH = CaseGraph(
    case_id=CaseId.OBJECTIVE_ESTIMAND_ENDPOINT,
    project_id=PROJECT_ID,
    branch_id=BRANCH_ID,
    graph_version=GRAPH_VERSION,
    description=(
        "Immutable typed contract of the objective-estimand-endpoint case: "
        "objective, complete estimand attribute set, endpoint "
        "definition/tool/timepoint and cross-objective consistency stay "
        "linked; missing links cannot satisfy the final decision Gate"
    ),
    schemas=SCHEMAS,
    root_inputs=("study_facts",),
    nodes=NODES,
    edges=EDGES,
    injections=INJECTIONS,
)
