"""Protocol v3 orchestrator PoC — sample-size case graph (Task 2.1, worker 03).

Immutable typed definition of the sample-size workflow: hypothesis/alpha/
multiplicity/power targets and a labeled synthetic assumption set
(effect, variance/event rate, dropout, design/allocation, analysis
assumptions) are bound to a deterministic calculation artifact, then an
independent statistical review and a user-approved decision lock it.

This module is a *pure typed definition* built from Worker 01's shared
vocabulary (:mod:`pocs.protocol_v3.orchestrator`): no scheduler, no runtime,
no clinical truth stored in graph state.  The registry loader
(:func:`pocs.protocol_v3.orchestrator.cases.load_case`) requires this module
to export ``GRAPH: CaseGraph`` bound to :class:`CaseId.SAMPLE_SIZE`.

Topology (maps to the accepted design
``mw_protocol_multi_agent_rearchitecture_design_20260809.md`` §10.1/§10.2/§5.4/§13/§14):

* ``define_hypothesis_and_targets`` — Agent② statistical/estimand worker
  drafts the hypothesis (null/alternative), alpha, multiplicity strategy and
  power target from labeled synthetic study facts (design §10.1 statistical
  worker: 样本量、alpha、多重性; §10.2 S dimension).  D1 design-consistency gate.
* ``define_statistical_assumptions`` — Agent② statistical worker binds the
  effect size, variance/event rate, dropout rate, design/allocation and the
  analysis assumptions (analysis population, missing-data method, sensitivity
  approach).  Every value is a labeled synthetic PoC placeholder: no number
  becomes a clinical fact or a default (design §5.3/§10.3: 推荐默认项必须可解释、
  有证据; missing effect/variance/dropout evidence must never be invented).
  D1 gate.
* ``derive_sample_size`` — deterministic SYSTEM calculation node: binds the
  targets and the full assumption set to a calculation artifact (formula id,
  parameter mapping, computed N per arm, rounding rule, sensitivity summary).
  Missing inputs fail closed structurally (``CC_INPUT_UNCOVERED``); the node
  never fabricates a missing effect/variance/dropout value (design §10.1:
  deterministic reducer 效应假设→样本量 closure).  D1 gate.
* ``statistical_review`` — Agent④ fresh-context independent statistical review
  point (design §13): typed findings with P0–P4 severity and typed
  dispositions; a clean Q1 verdict requires ``open_count=0``.  Q1 gate.
* ``sample_size_decision_lock`` — USER-owned decision/lock point (design
  §5.4: Agent⑤ never self-approves; 最终由确定性门和 Agent④ clean verdict 共同
  决定).  The approved decision is a reason-coded DecisionRecord and can only
  be recorded when the deterministic calculation and the clean statistical
  review are present (GATE edges); unresolved statistical judgments are
  decided here, never defaulted by the system.  Idempotent by decision key
  (design §14 CAS: duplicate click/worker/restart only returns the existing
  DecisionRecord, never a second decision).
* ``finalize_sample_size`` — deterministic freeze of the approved sample size
  into the final locked artifact, consuming the decision record via a typed
  :class:`EdgeKind.DECISION` edge.  D1 gate.

Missing-link discipline is enforced structurally: the calculation node and
the lock node both require the targets and the assumption-set artifacts as
inputs, and the lock node carries :class:`EdgeKind.GATE` edges from the
calculation (D1) and the Agent④ statistical review (Q1) — removing any link
fails closed at construction (``CC_INPUT_UNCOVERED`` /
``CC_EDGE_UNMATCHED_DEPENDENCY``) or blocks the lock at run time.

All five injection kinds are declared as :class:`InjectionPoint` records
(kill-before, kill-after, duplicate-resume, concurrent-decision,
old-graph-migration); they are represented, never executed.

Synthetic-only: every schema description is a labeled PoC placeholder.  No
patient data, no real trial statistics and no invented regulatory/scientific
facts; no numeric sample-size assumption is encoded in this definition.
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
GRAPH_VERSION = "sample_size_graph_v1"
OLD_GRAPH_VERSION = "sample_size_graph_v0"

# ---------------------------------------------------------------------------
# Closed per-case schema vocabulary (output artifacts + root inputs)
# ---------------------------------------------------------------------------

SCHEMAS = (
    SchemaDecl(
        name="study_facts",
        description=(
            "labeled synthetic study-fact container (population/design-intent "
            "facts) seeding the sample-size case; PoC placeholder, no real "
            "patient data"
        ),
    ),
    SchemaDecl(
        name="hypothesis_and_targets",
        description=(
            "hypothesis and design-target artifact: null/alternative "
            "hypothesis, alpha, multiplicity strategy, power target; every "
            "value is a labeled synthetic PoC placeholder, never a clinical "
            "default"
        ),
    ),
    SchemaDecl(
        name="statistical_assumptions",
        description=(
            "labeled synthetic statistical assumption set: effect size, "
            "variance or event rate, dropout rate, design/allocation, and "
            "analysis assumptions (analysis population, missing-data method, "
            "sensitivity approach); missing effect/variance/dropout evidence "
            "is never invented — the set must be complete to feed the "
            "calculation"
        ),
    ),
    SchemaDecl(
        name="sample_size_calculation",
        description=(
            "deterministic calculation artifact binding the targets and the "
            "full assumption set: formula id, parameter mapping, computed N "
            "per arm, rounding rule, sensitivity summary; derived by a "
            "system-owned node, never a model or a clinical judgment"
        ),
    ),
    SchemaDecl(
        name="qc_findings",
        description=(
            "Agent④ fresh-context independent statistical review findings "
            "artifact: typed dispositions, P0-P4 severity, locator; clean "
            "requires open_count=0"
        ),
    ),
    SchemaDecl(
        name="sample_size_decision",
        description=(
            "reason-coded user DecisionRecord adopting/amending the sample "
            "size; cannot be recorded while the deterministic calculation or "
            "the statistical review leaves open issues; unresolved statistical "
            "judgments are decided here, never defaulted by the system"
        ),
    ),
    SchemaDecl(
        name="locked_sample_size",
        description=(
            "final immutable sample-size artifact frozen from the approved "
            "decision record and the deterministic calculation"
        ),
    ),
)

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

NODES = (
    NodeContract(
        node_id="define_hypothesis_and_targets",
        kind=NodeKind.WORK,
        owner=OwnerRole.DESIGN_AND_SUMMARY,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("study_facts",),
        output_schema="hypothesis_and_targets",
        depends_on=(),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        side_effect_key_template="sample_size.targets.{target_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="define_statistical_assumptions",
        kind=NodeKind.WORK,
        owner=OwnerRole.DESIGN_AND_SUMMARY,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("hypothesis_and_targets",),
        output_schema="statistical_assumptions",
        depends_on=("define_hypothesis_and_targets",),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        side_effect_key_template="sample_size.assumption.{assumption_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="derive_sample_size",
        kind=NodeKind.CALCULATION,
        owner=OwnerRole.SYSTEM,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("hypothesis_and_targets", "statistical_assumptions"),
        output_schema="sample_size_calculation",
        depends_on=("define_hypothesis_and_targets", "define_statistical_assumptions"),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="sample_size.calculation.{revision}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
    NodeContract(
        node_id="statistical_review",
        kind=NodeKind.WORK,
        owner=OwnerRole.QUALITY_CONTROL,
        gate=GateKind.Q1_INDEPENDENT_QC,
        inputs=("statistical_assumptions", "sample_size_calculation"),
        output_schema="qc_findings",
        depends_on=("define_statistical_assumptions", "derive_sample_size"),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="sample_size.qc.{finding_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="sample_size_decision_lock",
        kind=NodeKind.DECISION,
        owner=OwnerRole.USER,
        gate=GateKind.USER_DECISION,
        inputs=(
            "hypothesis_and_targets",
            "statistical_assumptions",
            "sample_size_calculation",
            "qc_findings",
        ),
        output_schema="sample_size_decision",
        depends_on=(
            "define_hypothesis_and_targets",
            "define_statistical_assumptions",
            "derive_sample_size",
            "statistical_review",
        ),
        side_effect_kind=SideEffectKind.DECISION_RECORD,
        side_effect_key_template="sample_size.lock.{revision}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
    NodeContract(
        node_id="finalize_sample_size",
        kind=NodeKind.CHECK,
        owner=OwnerRole.SYSTEM,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("sample_size_decision", "sample_size_calculation"),
        output_schema="locked_sample_size",
        depends_on=("sample_size_decision_lock", "derive_sample_size"),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="sample_size.finalize.{revision}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
)


def _edge(source: str, target: str, kind: EdgeKind = EdgeKind.DATA) -> Edge:
    """Typed dependency edge helper (data by default)."""
    return Edge(source_node_id=source, target_node_id=target, kind=kind)


EDGES = (
    _edge("define_hypothesis_and_targets", "define_statistical_assumptions"),
    _edge("define_hypothesis_and_targets", "derive_sample_size"),
    _edge("define_statistical_assumptions", "derive_sample_size"),
    _edge("define_statistical_assumptions", "statistical_review"),
    _edge("derive_sample_size", "statistical_review"),
    _edge("define_hypothesis_and_targets", "sample_size_decision_lock"),
    _edge("define_statistical_assumptions", "sample_size_decision_lock"),
    _edge("derive_sample_size", "sample_size_decision_lock"),
    _edge("derive_sample_size", "sample_size_decision_lock", EdgeKind.GATE),
    _edge("statistical_review", "sample_size_decision_lock"),
    _edge("statistical_review", "sample_size_decision_lock", EdgeKind.GATE),
    _edge(
        "sample_size_decision_lock",
        "finalize_sample_size",
        EdgeKind.DECISION,
    ),
    _edge("derive_sample_size", "finalize_sample_size"),
)

# ---------------------------------------------------------------------------
# Injection points — all five Task 2.1 kinds, represented, never executed
# ---------------------------------------------------------------------------

INJECTIONS = (
    InjectionPoint(
        injection_kind=InjectionKind.KILL_BEFORE,
        target_node_id="define_statistical_assumptions",
        logical_key="sample_size.assumption.{assumption_id}",
        expectation=(
            "kill before the assumption-set node runs leaves no partial "
            "assumption set; deterministic resume re-runs the node from clean "
            "state; the artifact store stays idempotent by logical key "
            "(FK_IDEMPOTENCY_CONFLICT on conflicting writes)"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.KILL_AFTER,
        target_node_id="derive_sample_size",
        logical_key="sample_size.calculation.{revision}",
        expectation=(
            "kill after the calculation artifact is written; resume reuses "
            "the existing artifact by logical key; no duplicate calculation "
            "lineage or semantic effect"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.DUPLICATE_RESUME,
        target_node_id="sample_size_decision_lock",
        logical_key="sample_size.lock.{revision}",
        expectation=(
            "duplicate resume of the same lock decision key returns the "
            "existing DecisionRecord (design §14 CAS); no second decision and "
            "no double state change"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.CONCURRENT_DECISION,
        target_node_id="sample_size_decision_lock",
        logical_key="sample_size.lock.{revision}.claim",
        expectation=(
            "two actors claiming the same lock decision key fail closed "
            "(FK_CONCURRENT_DECISION); only the single claim holder may "
            "record, and exactly one DecisionRecord per revision is kept"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.OLD_GRAPH_MIGRATION,
        logical_key="sample_size.graph.migration",
        old_graph_version=OLD_GRAPH_VERSION,
        expectation=(
            "an old-version sample-size graph missing a hypothesis/target, "
            "assumption or calculation link (unknown/uncovered schema or "
            "unmatched dependency) fails closed (CC_SCHEMA_UNKNOWN / "
            "CC_INPUT_UNCOVERED / CC_EDGE_UNMATCHED_DEPENDENCY); migration "
            "never silently completes a missing link and never invents a "
            "missing effect/variance/dropout value"
        ),
    ),
)

# ---------------------------------------------------------------------------
# Closed immutable graph definition
# ---------------------------------------------------------------------------

GRAPH = CaseGraph(
    case_id=CaseId.SAMPLE_SIZE,
    project_id=PROJECT_ID,
    branch_id=BRANCH_ID,
    graph_version=GRAPH_VERSION,
    description=(
        "Immutable typed contract of the sample-size case: hypothesis/"
        "alpha/multiplicity/power targets and labeled synthetic assumptions "
        "(effect, variance/event rate, dropout, design/allocation, analysis) "
        "are bound to a deterministic calculation artifact, then an "
        "independent statistical review and a user-approved decision lock the "
        "sample size; no invented numeric default is treated as a clinical "
        "fact"
    ),
    schemas=SCHEMAS,
    root_inputs=("study_facts",),
    nodes=NODES,
    edges=EDGES,
    injections=INJECTIONS,
)
