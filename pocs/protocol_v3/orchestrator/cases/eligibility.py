"""Protocol v3 orchestrator PoC — eligibility case graph (Task 2.1, worker 02).

Immutable typed definition of the eligibility-criteria workflow: evidence-bound
criterion drafting, deterministic cross-criterion contradiction review,
independent Agent④ QC and a user decision/lock point.

This module is a *pure typed definition* built from Worker 01's shared
vocabulary (:mod:`pocs.protocol_v3.orchestrator`): no scheduler, no runtime,
no clinical truth stored in graph state.  The registry loader
(:func:`pocs.protocol_v3.orchestrator.cases.load_case`) requires this module
to export ``GRAPH: CaseGraph`` bound to :class:`CaseId.ELIGIBILITY`.

Topology (maps to the accepted design ``mw_protocol_multi_agent_rearchitecture_design_20260809.md``):

* ``draft_eligibility_criteria`` — Agent② clinical worker drafts candidate
  criteria from labeled synthetic study facts and admitted evidence
  (design §10.1: 临床 worker 疾病/人群).  D1 design-consistency gate.
* ``bind_criterion_evidence`` — Agent② binds every criterion to admitted
  evidence units or an explicit decision reference; model free generation is
  not a source (design §11.2: source-bound 主张).  D1 gate.
* ``cross_criterion_consistency`` — deterministic system reducer that
  *flags* inclusion/exclusion contradictions and overlapping pairs; it never
  edits criteria and never resolves a clinical judgment (design §10.1:
  deterministic reducer, §10.4: 适用性无未决冲突).  D1 gate.
* ``qc_review_criteria`` — Agent④ fresh-context QC review point (design §13):
  typed findings with P0–P4 severity and typed dispositions; a clean Q1
  verdict requires ``open_count=0``.  Q1 gate.
* ``eligibility_decision_lock`` — USER-owned decision/lock point (design
  §5.4: Agent⑤ never self-approves, 最终由确定性门和 Agent④ clean verdict 共同
  决定).  Unresolved clinical judgments are recorded here as a reason-coded
  DecisionRecord — never defaulted by the system.  ``user_decision`` gate.
* ``finalize_eligibility_criteria`` — deterministic freeze of the decided,
  evidence-bound criteria into the final locked artifact; idempotent by
  logical key (design §14 CAS: duplicate click/worker/restart only returns
  the existing locked artifact, never a second semantic effect).  D1 gate.

The finalization edge from ``eligibility_decision_lock`` is typed
:class:`EdgeKind.DECISION` (the finalizer consumes the decision record); the
lock node additionally requires the consistency report and the Agent④ QC
verdict via :class:`EdgeKind.GATE` edges, so an unresolved contradiction or
open QC finding cannot satisfy the lock.

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
GRAPH_VERSION = "eligibility_graph_v1"
OLD_GRAPH_VERSION = "eligibility_graph_v0"

# ---------------------------------------------------------------------------
# Closed per-case schema vocabulary (output artifacts + root inputs)
# ---------------------------------------------------------------------------

SCHEMAS = (
    SchemaDecl(
        name="study_facts",
        description=(
            "labeled synthetic study-fact container (population/design facts) "
            "seeding the eligibility case; PoC placeholder, no real patient data"
        ),
    ),
    SchemaDecl(
        name="admitted_evidence",
        description=(
            "labeled synthetic evidence units (locator, context, source role, "
            "quality) available for criterion evidence binding"
        ),
    ),
    SchemaDecl(
        name="drafted_criteria",
        description=(
            "drafted eligibility criteria artifact: criterion id, statement, "
            "rationale; unfinalized proposal, no clinical decision"
        ),
    ),
    SchemaDecl(
        name="evidence_bound_criteria",
        description=(
            "eligibility criteria artifact where every criterion is bound to "
            "admitted evidence units or an explicit decision reference"
        ),
    ),
    SchemaDecl(
        name="criterion_consistency_report",
        description=(
            "deterministic cross-criterion contradiction report (criterion "
            "pairs, conflict type, affected ids); flags only, never resolves"
        ),
    ),
    SchemaDecl(
        name="qc_findings",
        description=(
            "Agent④ fresh-context QC findings artifact: typed dispositions, "
            "P0-P4 severity, locator; clean requires open_count=0"
        ),
    ),
    SchemaDecl(
        name="eligibility_lock_decision",
        description=(
            "reason-coded user DecisionRecord adopting/amending the "
            "eligibility criteria; unresolved clinical judgments are decided "
            "here, never defaulted by the system"
        ),
    ),
    SchemaDecl(
        name="locked_eligibility_criteria",
        description=(
            "final immutable eligibility criteria artifact frozen from the "
            "decision record and the evidence-bound criteria"
        ),
    ),
)

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

NODES = (
    NodeContract(
        node_id="draft_eligibility_criteria",
        kind=NodeKind.WORK,
        owner=OwnerRole.DESIGN_AND_SUMMARY,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("study_facts", "admitted_evidence"),
        output_schema="drafted_criteria",
        depends_on=(),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        side_effect_key_template="eligibility.draft.{criterion_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="bind_criterion_evidence",
        kind=NodeKind.WORK,
        owner=OwnerRole.DESIGN_AND_SUMMARY,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("drafted_criteria", "admitted_evidence"),
        output_schema="evidence_bound_criteria",
        depends_on=("draft_eligibility_criteria",),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        side_effect_key_template="eligibility.bind.{criterion_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="cross_criterion_consistency",
        kind=NodeKind.CHECK,
        owner=OwnerRole.SYSTEM,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("evidence_bound_criteria",),
        output_schema="criterion_consistency_report",
        depends_on=("bind_criterion_evidence",),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="eligibility.consistency.{report_id}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
    NodeContract(
        node_id="qc_review_criteria",
        kind=NodeKind.WORK,
        owner=OwnerRole.QUALITY_CONTROL,
        gate=GateKind.Q1_INDEPENDENT_QC,
        inputs=("evidence_bound_criteria", "criterion_consistency_report"),
        output_schema="qc_findings",
        depends_on=("bind_criterion_evidence", "cross_criterion_consistency"),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="eligibility.qc.{finding_id}",
        failure_policy=FailurePolicy.BOUNDED_RETRY,
        allowed_attempts=3,
    ),
    NodeContract(
        node_id="eligibility_decision_lock",
        kind=NodeKind.DECISION,
        owner=OwnerRole.USER,
        gate=GateKind.USER_DECISION,
        inputs=(
            "evidence_bound_criteria",
            "criterion_consistency_report",
            "qc_findings",
        ),
        output_schema="eligibility_lock_decision",
        depends_on=(
            "bind_criterion_evidence",
            "cross_criterion_consistency",
            "qc_review_criteria",
        ),
        side_effect_kind=SideEffectKind.DECISION_RECORD,
        side_effect_key_template="eligibility.lock.{revision}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
    NodeContract(
        node_id="finalize_eligibility_criteria",
        kind=NodeKind.CHECK,
        owner=OwnerRole.SYSTEM,
        gate=GateKind.D1_DESIGN_CONSISTENCY,
        inputs=("eligibility_lock_decision", "evidence_bound_criteria"),
        output_schema="locked_eligibility_criteria",
        depends_on=("eligibility_decision_lock", "bind_criterion_evidence"),
        side_effect_kind=SideEffectKind.ARTIFACT_CREATE,
        side_effect_key_template="eligibility.finalize.{revision}",
        failure_policy=FailurePolicy.FAIL_CLOSED,
        allowed_attempts=1,
    ),
)


def _edge(source: str, target: str, kind: EdgeKind = EdgeKind.DATA) -> Edge:
    """Typed dependency edge helper (data by default)."""
    return Edge(source_node_id=source, target_node_id=target, kind=kind)


EDGES = (
    _edge("draft_eligibility_criteria", "bind_criterion_evidence"),
    _edge("bind_criterion_evidence", "cross_criterion_consistency"),
    _edge("bind_criterion_evidence", "qc_review_criteria"),
    _edge("cross_criterion_consistency", "qc_review_criteria"),
    _edge("bind_criterion_evidence", "eligibility_decision_lock"),
    _edge("cross_criterion_consistency", "eligibility_decision_lock", EdgeKind.GATE),
    _edge("qc_review_criteria", "eligibility_decision_lock"),
    _edge("qc_review_criteria", "eligibility_decision_lock", EdgeKind.GATE),
    _edge(
        "eligibility_decision_lock",
        "finalize_eligibility_criteria",
        EdgeKind.DECISION,
    ),
    _edge("bind_criterion_evidence", "finalize_eligibility_criteria"),
)

# ---------------------------------------------------------------------------
# Injection points — all five Task 2.1 kinds, represented, never executed
# ---------------------------------------------------------------------------

INJECTIONS = (
    InjectionPoint(
        injection_kind=InjectionKind.KILL_BEFORE,
        target_node_id="bind_criterion_evidence",
        logical_key="eligibility.bind.{criterion_id}",
        expectation=(
            "kill before the evidence-binding node runs leaves no partial "
            "artifact; deterministic resume re-runs the node from clean state; "
            "the artifact store stays idempotent by logical key "
            "(FK_IDEMPOTENCY_CONFLICT on conflicting writes)"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.KILL_AFTER,
        target_node_id="draft_eligibility_criteria",
        logical_key="eligibility.draft.{criterion_id}",
        expectation=(
            "kill after the draft artifact is written; resume reuses the "
            "existing artifact by logical key, never creating a second draft "
            "lineage or duplicate semantic effect"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.DUPLICATE_RESUME,
        target_node_id="finalize_eligibility_criteria",
        logical_key="eligibility.finalize.{revision}",
        expectation=(
            "duplicate resume of the same finalize logical key returns the "
            "existing locked artifact and reservation without a second freeze "
            "(design §14 CAS); reservation ledger idempotent by "
            "(logical_call_id, idempotency_key)"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.CONCURRENT_DECISION,
        target_node_id="eligibility_decision_lock",
        logical_key="eligibility.lock.{revision}",
        expectation=(
            "only one actor may hold the lock decision key; a second "
            "concurrent claim fails closed (FK_CONCURRENT_DECISION); exactly "
            "one DecisionRecord per revision, never double-applied"
        ),
    ),
    InjectionPoint(
        injection_kind=InjectionKind.OLD_GRAPH_MIGRATION,
        logical_key="eligibility.graph.migration",
        old_graph_version=OLD_GRAPH_VERSION,
        expectation=(
            "an eligibility graph from the old version (missing evidence "
            "binding, consistency or QC link, or unknown schema names) fails "
            "closed (CC_SCHEMA_UNKNOWN / CC_INPUT_UNCOVERED / "
            "CC_EDGE_UNMATCHED_DEPENDENCY); migration never auto-completes "
            "missing links or silently re-versions artifacts"
        ),
    ),
)

# ---------------------------------------------------------------------------
# Closed immutable graph definition
# ---------------------------------------------------------------------------

GRAPH = CaseGraph(
    case_id=CaseId.ELIGIBILITY,
    project_id=PROJECT_ID,
    branch_id=BRANCH_ID,
    graph_version=GRAPH_VERSION,
    description=(
        "Immutable typed contract of the eligibility-criteria case: "
        "evidence-bound criterion drafting, deterministic cross-criterion "
        "contradiction review, Agent④ QC and a user decision/lock point; "
        "unresolved clinical judgments stay an explicit user decision"
    ),
    schemas=SCHEMAS,
    root_inputs=("study_facts", "admitted_evidence"),
    nodes=NODES,
    edges=EDGES,
    injections=INJECTIONS,
)
