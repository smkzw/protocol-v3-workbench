"""Task 3R.4C: fact-labeled impact plan consumable by 3R.4D adoption.

Red-first: this module failed collection (``build_fact_labeled_impact_plan``
missing) before the implementation landed.  No assertion is weakened and no
``xfail`` is used.

Scope boundaries asserted here:

* the plan is registry infrastructure: it is not a medical approval, and it is
  not an adoption — D must bind actual adoption in one UoW with its own
  operation key (plan hashes are projection hashes, never work keys);
* applicability reuse is B's source-bound three-state machinery
  (``RulePredicate`` source hashes via ``load_applicability_rules``, and
  ``evaluate_predicates``); unknown stays candidate, false is never a missing
  value, and no clinical causality is inferred from an ``all`` combination;
* canonical→contract translation reuses ``affected_chapter_fact_paths``; dotted
  canonical keys stay literal and are never split into member addresses;
* the executable-plan gate refuses graphs carrying structural findings
  (unknown dependency target / missing repair owner) while the graph stays
  viewable for diagnosis.

The current assembled registry is assembled from the authored config contracts
(not the frozen 3R.3 artifact) and must accept the current
``fact_bindings.json`` (743 paths) and ``applicability_rules.json`` (70 rules)
through B's own fail-closed loaders — that is the version-binding proof.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from app.protocol_workflow.registries.applicability import (
    FactPredicate,
    RulePredicate,
    load_applicability_rules,
)
from app.protocol_workflow.registries.chapters import load_chapter_registry
from app.protocol_workflow.registries.dependency_graph import (
    DependencyGraphError,
    EdgeKind,
    ImpactPlanNotExecutable,
    ImpactReason,
    build_dependency_graph,
    build_fact_labeled_impact_plan,
    fact_bindings_plan_hash,
)
from app.protocol_workflow.registries.fact_bindings import (
    FactBinding,
    load_fact_catalog,
)
from test_dependency_graph import (
    TEMPLATE_ID,
    TEMPLATE_SHA256,
    _chapter,
    _conditional_rule,
    _edge_pairs,
    _policy,
    _registry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = (
    REPO_ROOT / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
)

#: Accepted current-registry anchors (computed from the authored contracts,
#: never guessed; the graph is rebuilt by the fixture on every run).
CURRENT_NODE_COUNT = 111
CURRENT_SCHEDULING_EDGE_COUNT = 41
CURRENT_CONSISTENCY_EDGE_COUNT = 55
CURRENT_MEMBERSHIP_SOURCES = {
    "fact_requirement": 797,
    "conditional_trigger": 90,
    "conditional_when_active": 111,
}

#: Real anchors used by the small explicit expectation sets below.
ENDPOINT_FACT = "picos.primary_endpoint"
ENDPOINT_FACT_LABELED_AFFECTED = 10
DOSE_CANONICAL = "picos.intervention_dose_regimen"
DOSE_CARRIER = "contract:v2-n-4-3:v2"
SYNOPSIS_ALIAS = "synopsis.interventions"
SYNOPSIS_CARRIER = "contract:v2-n-1-1:v2"
INTERIM_TRIGGER = "statistics.interim.applicable"
INTERIM_RULE_CONTRACT = "contract:v2-n-11-4-9:v2"
INTERIM_RULE_ID = "conditional:v2-n-11-4-9:interim"


# ---------------------------------------------------------------------------
# Current assembled registry (authored config contracts + B catalogs).
# ---------------------------------------------------------------------------


def _build_current_registry_payload() -> dict:
    from app.protocol_workflow.registries.chapters import (
        ChapterSkillManifest,
        _expected_roles_from_template,
    )
    from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2

    node_tree = json.loads((TEMPLATE_DIR / "node_tree.json").read_text())
    roles, _ = _expected_roles_from_template(node_tree)
    # The unheaded cover carrier is part of the accepted 111-carrier set.
    roles["v2_front_block"] = "cover"
    contracts = {}
    for path in sorted((TEMPLATE_DIR / "chapter_contracts").glob("*.json")):
        contract = ChapterContractV2.model_validate_json(path.read_text())
        contracts[contract.semantic_node_id] = contract
    claims: set[str] = set()
    for contract in contracts.values():
        content = contract.substantive_content
        claims.update(item.claim_type for item in content.claim_requirements)
        for rule in contract.conditional_applicability_rules:
            claims.update(rule.required_when_active_claim_types)
        for group in content.evidence_source_requirements:
            claims.update(group.admission_claim_types)
    catalog = json.loads((TEMPLATE_DIR / "applicability_rules.json").read_text())
    for declaration in catalog["rules"]:
        claims.update(declaration.get("required_when_active_claim_types", []))
        for item in declaration.get("inactive_claim_requirements", []):
            claims.add(item["claim_type"])
        for item in declaration.get("active_evidence_requirements", []):
            claims.update(item["admission_claim_types"])
        for item in declaration.get("inactive_evidence_requirements", []):
            claims.update(item["admission_claim_types"])
    bindings_payload = json.loads((TEMPLATE_DIR / "fact_bindings.json").read_text())
    chapters = []
    for node_id in sorted(contracts):
        skill = ChapterSkillManifest.model_validate_json(
            (TEMPLATE_DIR / "chapter_skills" / f"{node_id}.json").read_text()
        )
        chapters.append(
            {
                "node_id": node_id,
                "coverage_role": roles[node_id],
                "contract": json.loads(contracts[node_id].model_dump_json()),
                "skills": [json.loads(skill.model_dump_json())],
            }
        )
    return {
        "schema_version": "protocol-v3-chapter-registry.v1",
        "generated_for": "test:3r4c:current-assembled-registry",
        "authority": (
            "3R.4C test assembly of the authored config chapter contracts; "
            "structure-only, fixtures intentionally empty; not product content"
        ),
        "template_id": TEMPLATE_ID,
        "template_sha256": TEMPLATE_SHA256,
        "fact_vocabulary": sorted(
            item["fact_path"] for item in bindings_payload["bindings"]
        ),
        "claim_vocabulary": sorted(claims),
        "chapters": chapters,
        "fixtures": [],
    }


def _independent_fact_labeled_closure(payload: dict, fact_paths: tuple[str, ...]) -> set[str]:
    """Raw-JSON fixpoint oracle: direct carriers + transitive dependency_ids.

    Never reads consistency edges and never mirrors the engine traversal.
    """
    carriers: dict[str, set[str]] = collections.defaultdict(set)
    dependents: dict[str, set[str]] = collections.defaultdict(set)
    for chapter in payload["chapters"]:
        contract_id = chapter["contract"]["chapter_contract_id"]
        for requirement in chapter["contract"]["substantive_content"]["fact_requirements"]:
            carriers[requirement["fact_path"]].add(contract_id)
        for rule in chapter["contract"].get("conditional_applicability_rules", []):
            for path in rule["triggering_fact_paths"]:
                carriers[path].add(contract_id)
            for path in rule["required_when_active_fact_paths"]:
                carriers[path].add(contract_id)
        for dependency in chapter["contract"].get("dependency_ids", []):
            dependents[dependency].add(contract_id)
    affected = {cid for path in fact_paths for cid in carriers[path]}
    stable = False
    while not stable:
        stable = True
        for upstream, downstream in list(dependents.items()):
            if upstream in affected and not downstream <= affected:
                affected |= downstream
                stable = False
    return affected


@pytest.fixture(scope="module")
def current_payload() -> dict:
    return _build_current_registry_payload()


@pytest.fixture(scope="module")
def current_document(current_payload):
    return load_chapter_registry(current_payload)


@pytest.fixture(scope="module")
def current_graph(current_document):
    return build_dependency_graph(current_document)


@pytest.fixture(scope="module")
def current_fact_catalog(current_document):
    # B's own fail-closed loader: only passes when the catalog binds exactly
    # this assembled registry (template + vocabulary + contract hashes).
    return load_fact_catalog(TEMPLATE_DIR / "fact_bindings.json", current_document)


@pytest.fixture(scope="module")
def current_rules(current_document):
    contracts = [entry.contract for entry in current_document.chapters]
    catalog = load_applicability_rules(
        TEMPLATE_DIR / "applicability_rules.json", contracts
    )
    return catalog.rules


# ---------------------------------------------------------------------------
# Synthetic bridge / derivation / value-fidelity behaviour (small sets).
# ---------------------------------------------------------------------------


def _plan(graph, before, after, **kwargs):
    return build_fact_labeled_impact_plan(
        graph, facts_before=before, facts_after=after, **kwargs
    )


def _bridge_graph(**extra_c):
    chapters = [
        _chapter("v2_t_a", facts=(("test.fact.x", "required"),)),
        _chapter(
            "v2_t_b",
            facts=(("test.fact.x", "required"), ("test.fact.y", "required")),
        ),
        _chapter("v2_t_c", facts=(("test.fact.y", "required"),), **extra_c),
    ]
    return build_dependency_graph(load_chapter_registry(_registry(chapters)))


def test_plan_reopens_only_carriers_of_actually_changed_facts():
    graph = _bridge_graph()
    plan = _plan(graph, {"test.fact.x": 1, "test.fact.y": "same"},
                 {"test.fact.x": 2, "test.fact.y": "same"})
    # Only x actually changed: A and B directly; C stays out despite the B–C
    # consistency bridge on y.
    assert plan.changed_canonical_paths == ("test.fact.x",)
    assert plan.changed_fact_paths == ("test.fact.x",)
    assert plan.confirmed_reopen_contract_ids == (
        "contract:v2-t-a:v2",
        "contract:v2-t-b:v2",
    )
    assert plan.candidate_check_contract_ids == ()
    assert plan.entry_for("contract:v2-t-c:v2") is None
    entry_b = plan.entry_for("contract:v2-t-b:v2")
    assert entry_b.reason is ImpactReason.DIRECT_FACT_USE
    assert entry_b.via_fact_paths == ("test.fact.x",)
    assert entry_b.via_contract_ids == ()


def test_plan_value_fidelity_preserves_false_zero_and_fabricates_nothing():
    graph = _bridge_graph()

    # Same fact, same value: no change is fabricated (nothing reopens).
    untouched = _plan(graph, {"test.fact.x": False}, {"test.fact.x": False})
    assert untouched.changed_canonical_paths == ()
    assert untouched.entries == ()
    untouched_zero = _plan(graph, {"test.fact.x": 0}, {"test.fact.x": 0})
    assert untouched_zero.changed_canonical_paths == ()

    # false -> 0 and 0 -> false are actual native JSON value changes.
    false_to_zero = _plan(graph, {"test.fact.x": False}, {"test.fact.x": 0})
    assert false_to_zero.changed_canonical_paths == ("test.fact.x",)
    assert false_to_zero.confirmed_reopen_contract_ids == (
        "contract:v2-t-a:v2",
        "contract:v2-t-b:v2",
    )
    zero_to_false = _plan(graph, {"test.fact.x": 0}, {"test.fact.x": False})
    assert zero_to_false.changed_canonical_paths == ("test.fact.x",)

    # Added / removed keys are actual changes; the report keeps the paths.
    added = _plan(graph, {}, {"test.fact.x": True})
    assert added.changed_canonical_paths == ("test.fact.x",)
    removed = _plan(graph, {"test.fact.x": True}, {})
    assert removed.changed_canonical_paths == ("test.fact.x",)


def test_plan_explicit_derived_change_propagates_only_when_actually_changed():
    graph = _bridge_graph()
    # Derivation recomputed y in the same unit of work: y actually changed, so
    # C is reopened as a direct carrier of y (not through the bridge).
    derived = _plan(
        graph,
        {"test.fact.x": 1, "test.fact.y": "old"},
        {"test.fact.x": 2, "test.fact.y": "new"},
    )
    assert derived.changed_fact_paths == ("test.fact.x", "test.fact.y")
    entry_c = derived.entry_for("contract:v2-t-c:v2")
    assert entry_c is not None
    assert entry_c.reason is ImpactReason.DIRECT_FACT_USE
    assert entry_c.via_fact_paths == ("test.fact.y",)
    assert entry_c.confirmation == "confirmed_reopen"


def test_plan_conditional_unknown_stays_candidate_and_resolved_reopens():
    rule_id = "condition:test-trigger"
    payload = _registry(
        [
            _chapter(
                "v2_t_a",
                facts=(("test.fact.plain", "required"),),
                conditional_rules=(
                    _conditional_rule(
                        rule_id,
                        triggers=("test.fact.trigger",),
                        when_active=("test.fact.when_active",),
                    ),
                ),
            ),
            _chapter(
                "v2_t_b",
                facts=(("test.fact.plain", "required"),),
                deps=("contract:v2-t-a:v2",),
                repair_policy=_policy("v2_t_b", ("contract:v2-t-a:v2",)),
            ),
        ]
    )
    document = load_chapter_registry(payload)
    graph = build_dependency_graph(document)
    source_rule = document.chapters[0].contract.conditional_applicability_rules[0]
    # B's source-bound predicate declaration: hash binds the current rule.
    declaration = RulePredicate(
        rule_id=source_rule.conditional_applicability_rule_id,
        source_rule_sha256=source_rule.material_sha256(),
        predicates=(
            FactPredicate(fact_path="test.fact.trigger", expected=True),
        ),
        mode="all",
    )

    # Trigger resolved True -> False: obligation release is an actual change;
    # the chapter reopens (it is the trigger's owner) with an obligation change.
    resolved = _plan(
        graph,
        {"test.fact.trigger": True},
        {"test.fact.trigger": False},
        rules=(declaration,),
    )
    entry_a = resolved.entry_for("contract:v2-t-a:v2")
    assert entry_a.confirmation == "confirmed_reopen"
    rule_plan = entry_a.rule_plans[0]
    assert rule_plan.rule_id == rule_id
    assert rule_plan.state_before == "applicable"
    assert rule_plan.state_after == "not_applicable"
    assert rule_plan.disposition == "obligation_change"
    # Real scheduling fan-out: the dependent follows with the same labels.
    entry_b = resolved.entry_for("contract:v2-t-b:v2")
    assert entry_b.reason is ImpactReason.SCHEDULING
    assert entry_b.confirmation == "confirmed_reopen"
    assert entry_b.via_contract_ids == ("contract:v2-t-a:v2",)

    # Trigger unknown after the change (value None / key absent): the rule
    # cannot be resolved, so the conditional involvement stays a candidate
    # check — it must not directly invalidate confirmed content.
    unknown = _plan(
        graph,
        {"test.fact.trigger": True},
        {"test.fact.trigger": None},
        rules=(declaration,),
    )
    pending_entry = unknown.entry_for("contract:v2-t-a:v2")
    assert pending_entry.confirmation == "candidate_check"
    assert pending_entry.rule_plans[0].disposition == "pending_facts"
    assert pending_entry.rule_plans[0].state_after == "conditional"
    assert unknown.candidate_check_contract_ids == (
        "contract:v2-t-a:v2",
        "contract:v2-t-b:v2",
    )
    assert unknown.confirmed_reopen_contract_ids == ()
    # The pending status propagates through real scheduling: the dependent is
    # also a candidate, not a confirmed reopen.
    assert unknown.entry_for("contract:v2-t-b:v2").confirmation == "candidate_check"

    # False is never a missing value: False resolves the predicate decisively.
    # The previously unknown side stays honestly recorded as conditional.
    false_resolves = _plan(
        graph,
        {"test.fact.trigger": None},
        {"test.fact.trigger": False},
        rules=(declaration,),
    )
    resolved_entry = false_resolves.entry_for("contract:v2-t-a:v2")
    assert resolved_entry.confirmation == "confirmed_reopen"
    assert resolved_entry.rule_plans[0].state_before == "conditional"
    assert resolved_entry.rule_plans[0].state_after == "not_applicable"
    assert resolved_entry.rule_plans[0].disposition == "pending_facts"

    # Without any rules supplied, conditional involvement cannot resolve and
    # stays candidate — never silently treated as unconditional.
    unbound = _plan(graph, {"test.fact.trigger": True}, {"test.fact.trigger": False})
    assert unbound.entry_for("contract:v2-t-a:v2").confirmation == "candidate_check"


def test_plan_projection_alias_refresh_does_not_reverse_invalidate():
    """Summary projection: alias-side change never reopens the canonical owner."""
    graph = build_dependency_graph(
        load_chapter_registry(
            _registry(
                [
                    _chapter(
                        "v2_t_s",
                        facts=(("synopsis.interventions", "required"),),
                    ),
                    _chapter(
                        "v2_t_d",
                        facts=(("picos.intervention_dose_regimen", "required"),),
                    ),
                ]
            )
        )
    )
    bindings = (
        FactBinding(
            fact_path="synopsis.interventions",
            canonical_path="picos.intervention_dose_regimen",
            value_type="json",
            source_refs=("test:synthetic-alias",),
        ),
        FactBinding(
            fact_path="picos.intervention_dose_regimen",
            canonical_path="picos.intervention_dose_regimen",
            value_type="json",
            source_refs=("test:synthetic-canonical",),
        ),
    )

    # Forward: the canonical fact actually changed -> alias carrier reopens
    # through the explicit binding translation.
    forward = _plan(
        graph,
        {"picos.intervention_dose_regimen": {"arms": 1}},
        {"picos.intervention_dose_regimen": {"arms": 2}},
        bindings=bindings,
    )
    assert forward.changed_fact_paths == (
        "picos.intervention_dose_regimen",
        "synopsis.interventions",
    )
    assert forward.entry_for("contract:v2-t-s:v2").reason is ImpactReason.DIRECT_FACT_USE
    assert forward.entry_for("contract:v2-t-d:v2").reason is ImpactReason.DIRECT_FACT_USE

    # Reverse: only the alias-side value moved while the canonical owner did
    # not change.  The summary chapter gets a projection refresh candidate;
    # the canonical owner and every other chapter stay untouched.
    reverse = _plan(
        graph,
        {"synopsis.interventions": {"arms": 1}},
        {"synopsis.interventions": {"arms": 2}},
        bindings=bindings,
    )
    assert reverse.changed_canonical_paths == ("synopsis.interventions",)
    assert reverse.entries == ()
    assert reverse.confirmed_reopen_contract_ids == ()
    assert [
        (refresh.contract_id, refresh.fact_path, refresh.canonical_path)
        for refresh in reverse.projection_refreshes
    ] == [("contract:v2-t-s:v2", "synopsis.interventions",
           "picos.intervention_dose_regimen")]
    assert reverse.entry_for("contract:v2-t-d:v2") is None

    # Canonical changes with no contract binding invalidate nothing silently:
    # they are reported as unmapped instead of reopening all chapters.
    unmapped = _plan(
        graph,
        {"internal.unbound.note": 1},
        {"internal.unbound.note": 2},
        bindings=bindings,
    )
    assert unmapped.unmapped_canonical_paths == ("internal.unbound.note",)
    assert unmapped.entries == ()


def test_plan_keeps_dotted_keys_literal_and_never_splits_member_addresses():
    graph = _bridge_graph()
    literal = _plan(graph, {"test.fact.x": 1}, {"test.fact.x": 2})
    assert literal.changed_fact_paths == ("test.fact.x",)
    # A nested member change is a change of the literal key "a.b.c" only when
    # that literal key exists; it is never decomposed into "a" + members.
    nested = _plan(
        graph,
        {"test.fact.x": {"b": {"c": 1}}},
        {"test.fact.x": {"b": {"c": 2}}},
    )
    assert nested.changed_canonical_paths == ("test.fact.x",)
    assert "test.fact.x.b" not in nested.changed_fact_paths
    assert "test.fact.x.b.c" not in nested.changed_fact_paths


def test_plan_executable_gate_refuses_findings_but_graph_stays_viewable():
    document = load_chapter_registry(
        _registry(
            [
                _chapter("v2_t_a", facts=(("test.fact.alpha", "required"),)),
                _chapter(
                    "v2_t_b",
                    facts=(("test.fact.beta", "required"),),
                    deps=("contract:v2-t-a:v2", "contract:v2-t-ghost:v2"),
                    repair_policy=_policy(
                        "v2_t_b", ("contract:v2-t-ghost:v2",), owner="ai"
                    ),
                ),
            ]
        )
    )
    graph = build_dependency_graph(document)
    assert {finding.code for finding in graph.findings} == {
        "missing_repair_owner",
        "unknown_dependency_target",
    }
    # Diagnostic view stays available on the defective graph.
    plan = _plan(graph, {"test.fact.beta": 1}, {"test.fact.beta": 2})
    assert plan.entries[0].contract_id == "contract:v2-t-b:v2"
    assert plan.is_executable() is False
    with pytest.raises(ImpactPlanNotExecutable) as excinfo:
        plan.require_executable()
    assert {finding.code for finding in excinfo.value.findings} == {
        "missing_repair_owner",
        "unknown_dependency_target",
    }


def test_plan_hash_is_projection_identity_never_an_adoption_work_key():
    graph = _bridge_graph()
    first_call = _plan(graph, {"test.fact.x": 1}, {"test.fact.x": 2})
    second_call = _plan(graph, {"test.fact.x": 1}, {"test.fact.x": 2})
    # Pure projection: equal inputs give the identical plan hash.
    assert first_call == second_call
    assert first_call.plan_sha256 == second_call.plan_sha256

    # Dose increase then later dose revert: two distinct study revisions that
    # D must adopt as two separate operations share one projection hash —
    # proof that the hash cannot serve as an adoption idempotency key.
    increase = _plan(graph, {"test.fact.x": 10}, {"test.fact.x": 20})
    revert = _plan(graph, {"test.fact.x": 20}, {"test.fact.x": 10})
    assert increase.changed_canonical_paths == revert.changed_canonical_paths
    assert increase.entries == revert.entries
    assert increase.plan_sha256 == revert.plan_sha256

    # Distinct projections do hash differently (path set changes the hash).
    widened = _plan(
        graph,
        {"test.fact.x": 10, "test.fact.y": 1},
        {"test.fact.x": 20, "test.fact.y": 2},
    )
    assert widened.plan_sha256 != increase.plan_sha256


def test_plan_scheduling_chain_reports_via_chain_and_consistency_never_seeds():
    chapters = [
        _chapter("v2_t_a", facts=(("test.fact.x", "required"),)),
        _chapter(
            "v2_t_b",
            facts=(("test.fact.z", "required"),),
            deps=("contract:v2-t-a:v2",),
            repair_policy=_policy("v2_t_b", ("contract:v2-t-a:v2",)),
        ),
        _chapter(
            "v2_t_c",
            facts=(("test.fact.z", "required"), ("test.fact.w", "required")),
            deps=("contract:v2-t-b:v2",),
            repair_policy=_policy("v2_t_c", ("contract:v2-t-b:v2",)),
        ),
        _chapter("v2_t_d", facts=(("test.fact.w", "required"),)),
    ]
    graph = build_dependency_graph(load_chapter_registry(_registry(chapters)))
    # a --(sched)-> b --(sched)-> c; c and d share w (consistency link).
    assert _edge_pairs(graph, EdgeKind.CONSISTENCY_IMPACT) == {
        ("contract:v2-t-b:v2", "contract:v2-t-c:v2"),
        ("contract:v2-t-c:v2", "contract:v2-t-d:v2"),
    }
    plan = _plan(graph, {"test.fact.x": 1}, {"test.fact.x": 2})
    # Real fan-out, untruncated: the whole downstream chain follows.
    assert plan.confirmed_reopen_contract_ids == (
        "contract:v2-t-a:v2",
        "contract:v2-t-b:v2",
        "contract:v2-t-c:v2",
    )
    entry_c = plan.entry_for("contract:v2-t-c:v2")
    assert entry_c.reason is ImpactReason.SCHEDULING
    assert entry_c.via_fact_paths == ("test.fact.x",)
    # The scheduling-reached chapter does not fabricate a label for its own
    # unchanged facts: d shares w with c but w never changed, so d stays out.
    assert plan.entry_for("contract:v2-t-d:v2") is None
    assert "contract:v2-t-d:v2" not in plan.confirmed_reopen_contract_ids


# ---------------------------------------------------------------------------
# Current assembled registry: version binding + real full fan-out.
# ---------------------------------------------------------------------------


def test_current_registry_graph_binds_authored_contracts(current_graph):
    assert len(current_graph.nodes) == CURRENT_NODE_COUNT
    assert len(current_graph.scheduling_edges) == CURRENT_SCHEDULING_EDGE_COUNT
    assert len(current_graph.consistency_edges) == CURRENT_CONSISTENCY_EDGE_COUNT
    sources = collections.Counter(
        membership.source.value for membership in current_graph.memberships
    )
    assert dict(sources) == CURRENT_MEMBERSHIP_SOURCES
    assert current_graph.findings == ()
    assert current_graph.template_id == TEMPLATE_ID


def test_current_registry_plan_full_fanout_and_version_bindings(
    current_payload, current_graph, current_fact_catalog, current_rules
):
    plan = build_fact_labeled_impact_plan(
        current_graph,
        facts_before={ENDPOINT_FACT: {"definition": "old"}},
        facts_after={ENDPOINT_FACT: {"definition": "new"}},
        bindings=current_fact_catalog.bindings,
        rules=current_rules,
    )
    # Version bindings: the plan is bound to this exact registry projection
    # and to the exact binding set of the current fact-binding catalog (whose
    # registry binding was proven by B's own fail-closed loader in the
    # fixture).
    assert plan.registry_sha256 == current_graph.registry_sha256
    assert plan.graph_schema_version == "protocol-v3-dependency-graph.v1"
    assert plan.fact_bindings_sha256 == fact_bindings_plan_hash(
        current_fact_catalog.bindings
    )
    assert plan.applicability_rules_sha256 is not None
    assert plan.findings == ()
    assert plan.is_executable() is True
    plan.require_executable()

    # Full fact-labeled fan-out on the real registry, against the raw-JSON
    # oracle (small explicit expectation: 4 direct carriers + 6 scheduling).
    assert len(plan.entries) == ENDPOINT_FACT_LABELED_AFFECTED
    assert plan.confirmed_reopen_contract_ids == tuple(
        sorted(_independent_fact_labeled_closure(current_payload, (ENDPOINT_FACT,)))
    )
    direct_ids = tuple(
        sorted(
            entry.contract_id
            for entry in plan.entries
            if entry.reason is ImpactReason.DIRECT_FACT_USE
        )
    )
    assert len(direct_ids) == 4
    scheduling_ids = [
        entry for entry in plan.entries if entry.reason is ImpactReason.SCHEDULING
    ]
    assert len(scheduling_ids) == 6
    assert all(
        entry.confirmation == "confirmed_reopen" for entry in plan.entries
    )


def test_current_registry_alias_translation_reopens_synopsis(
    current_graph, current_fact_catalog
):
    bindings = current_fact_catalog.bindings
    plan = build_fact_labeled_impact_plan(
        current_graph,
        facts_before={DOSE_CANONICAL: {"regimen": "old"}},
        facts_after={DOSE_CANONICAL: {"regimen": "new"}},
        bindings=bindings,
    )
    assert SYNOPSIS_ALIAS in plan.changed_fact_paths
    synopsis_entry = plan.entry_for(SYNOPSIS_CARRIER)
    assert synopsis_entry is not None
    assert synopsis_entry.reason is ImpactReason.DIRECT_FACT_USE
    assert SYNOPSIS_ALIAS in synopsis_entry.via_fact_paths
    assert plan.entry_for(DOSE_CARRIER).via_fact_paths == (DOSE_CANONICAL,)

    # Alias-side-only movement is a projection refresh, never a reopen of the
    # canonical dose carrier.
    reverse = build_fact_labeled_impact_plan(
        current_graph,
        facts_before={SYNOPSIS_ALIAS: {"regimen": "old"}},
        facts_after={SYNOPSIS_ALIAS: {"regimen": "new"}},
        bindings=bindings,
    )
    assert reverse.entries == ()
    assert reverse.entry_for(DOSE_CARRIER) is None
    assert any(
        refresh.fact_path == SYNOPSIS_ALIAS
        and refresh.contract_id == SYNOPSIS_CARRIER
        and refresh.canonical_path == DOSE_CANONICAL
        for refresh in reverse.projection_refreshes
    )


def test_current_registry_interim_unknown_vs_resolved(current_graph, current_rules):
    # The interim chapter declares statistics.interim.applicable both as a
    # plain fact requirement and as the trigger of its interim rule, so the
    # chapter itself reopens when the boolean actually changes.  The RULE
    # layer is what stays a candidate: with the new value unknown, every
    # interim rule disposition is pending — the obligation set is not decided
    # and confirmed conditional content is not invalidated by inference.
    unknown = build_fact_labeled_impact_plan(
        current_graph,
        facts_before={INTERIM_TRIGGER: True},
        facts_after={INTERIM_TRIGGER: None},
        rules=current_rules,
    )
    interim_entry = unknown.entry_for(INTERIM_RULE_CONTRACT)
    assert interim_entry.confirmation == "confirmed_reopen"
    assert INTERIM_TRIGGER in interim_entry.via_fact_paths
    rule_plans = {item.rule_id: item for item in interim_entry.rule_plans}
    assert rule_plans[INTERIM_RULE_ID].disposition == "pending_facts"
    assert rule_plans[INTERIM_RULE_ID].state_after == "conditional"
    assert rule_plans[INTERIM_RULE_ID].state_before == "applicable"
    # The other interim rules triggered by the same boolean stay pending too.
    assert all(
        item.disposition == "pending_facts" for item in rule_plans.values()
    )
    assert INTERIM_RULE_CONTRACT in unknown.confirmed_reopen_contract_ids

    # Resolved True -> False: the obligations are explicitly released; the
    # chapter reopens with an obligation change (shared-owner projection stays
    # B's execution concern; the plan reports the rule state truthfully).
    resolved = build_fact_labeled_impact_plan(
        current_graph,
        facts_before={INTERIM_TRIGGER: True},
        facts_after={INTERIM_TRIGGER: False},
        rules=current_rules,
    )
    resolved_entry = resolved.entry_for(INTERIM_RULE_CONTRACT)
    assert resolved_entry.confirmation == "confirmed_reopen"
    resolved_plans = {item.rule_id: item for item in resolved_entry.rule_plans}
    assert resolved_plans[INTERIM_RULE_ID].disposition == "obligation_change"
    assert resolved_plans[INTERIM_RULE_ID].state_after == "not_applicable"
    assert resolved_plans[INTERIM_RULE_ID].state_before == "applicable"

    # None is not silently read as False: only the unknown case above leaves
    # pending dispositions, proving false/None separation on the real ruleset.


def test_current_registry_unindexed_and_stability(current_graph):
    plan = build_fact_labeled_impact_plan(
        current_graph,
        facts_before={"test.fact.not.in.the.registry": 1},
        facts_after={"test.fact.not.in.the.registry": 2},
    )
    assert plan.unindexed_fact_paths == ("test.fact.not.in.the.registry",)
    assert plan.entries == ()
    # Purity: repeated calls do not mutate and give identical projections.
    before = current_graph.projection_sha256()
    again = build_fact_labeled_impact_plan(
        current_graph,
        facts_before={ENDPOINT_FACT: 1},
        facts_after={ENDPOINT_FACT: 2},
    )
    assert current_graph.projection_sha256() == before
    assert again.entries == again.entries


# ---------------------------------------------------------------------------
# Owner follow-up 01: B shared-owner semantics for controlled obligations.
#
# A base fact_requirement can sit under explicit conditional control (B's
# ``conditional_fact_paths``): it is only unconditional when no contract rule
# controls it.  When-active obligations follow B's accepted shared-owner
# semantics from ``_project_obligations``: any applicable owner keeps the
# obligation active; all not_applicable owners release it (stale content must
# still be refreshed); any unresolved owner without an applicable one leaves
# the field undecided (candidate, never silently false).  A chapter's own
# conditional decision is computed from its own contract rules only — neither
# the scheduling flow nor another chapter's decided owner on the same field
# may override it.
# ---------------------------------------------------------------------------


def _shared_owner_graph(base_requirement: bool, shared: bool, **extra_c):
    rules = [
        _conditional_rule("rule:a", triggers=("trigger.a",), when_active=("payload.x",))
    ]
    if shared:
        rules.append(
            _conditional_rule("rule:b", triggers=("trigger.b",), when_active=("payload.x",))
        )
    facts = (("payload.x", "required"),) if base_requirement else (("plain.x", "required"),)
    document = load_chapter_registry(
        _registry(
            [
                _chapter(
                    "v2_t_a",
                    facts=facts,
                    conditional_rules=tuple(rules),
                    **extra_c,
                )
            ]
        )
    )
    declarations = []
    for index, rule in enumerate(
        document.chapters[0].contract.conditional_applicability_rules
    ):
        declarations.append(
            RulePredicate(
                rule_id=rule.conditional_applicability_rule_id,
                source_rule_sha256=rule.material_sha256(),
                predicates=(
                    FactPredicate(
                        fact_path="trigger." + ("a" if index == 0 else "b"),
                        expected=True,
                    ),
                ),
                source_contract_sha256=document.chapters[0].contract.material_sha256(),
                conditional_fact_paths=("payload.x",),
            )
        )
    return build_dependency_graph(document), tuple(declarations)


def test_owner_case_controlled_base_requirement_unknown_is_candidate():
    graph, declarations = _shared_owner_graph(base_requirement=True, shared=False)
    plan = _plan(graph, {"payload.x": 1}, {"payload.x": 2}, rules=declarations)
    entry = plan.entry_for("contract:v2-t-a:v2")
    assert entry.confirmation == "candidate_check"
    assert plan.candidate_check_contract_ids == ("contract:v2-t-a:v2",)
    assert plan.confirmed_reopen_contract_ids == ()
    rule_plan = entry.rule_plans[0]
    assert rule_plan.state_after == "conditional"
    assert rule_plan.disposition == "pending_facts"


def test_owner_case_shared_active_owner_wins_over_unknown():
    graph, declarations = _shared_owner_graph(base_requirement=False, shared=True)
    plan = _plan(
        graph,
        {"payload.x": 1, "trigger.a": True},
        {"payload.x": 2, "trigger.a": True},
        rules=declarations,
    )
    entry = plan.entry_for("contract:v2-t-a:v2")
    assert entry.confirmation == "confirmed_reopen"
    assert plan.confirmed_reopen_contract_ids == ("contract:v2-t-a:v2",)
    rule_plans = {item.rule_id: item for item in entry.rule_plans}
    assert rule_plans["rule:a"].state_before == "applicable"
    assert rule_plans["rule:a"].state_after == "applicable"
    assert rule_plans["rule:a"].disposition == "stable"
    assert rule_plans["rule:b"].state_after == "conditional"
    assert rule_plans["rule:b"].disposition == "pending_facts"


def test_owner_release_refreshes_stale_content():
    graph, declarations = _shared_owner_graph(base_requirement=True, shared=False)
    # Owner was applicable before (content existed under the active rule) and
    # the trigger flips to False: the obligation is determinately released and
    # the stale content must be refreshed — a confirmed reopen, not a drop.
    plan = _plan(
        graph,
        {"payload.x": 1, "trigger.a": True},
        {"payload.x": 2, "trigger.a": False},
        rules=declarations,
    )
    entry = plan.entry_for("contract:v2-t-a:v2")
    assert entry.confirmation == "confirmed_reopen"
    assert entry.rule_plans[0].disposition == "obligation_change"
    assert entry.rule_plans[0].state_after == "not_applicable"


def test_owner_all_inactive_and_active_inactive_owner_combinations():
    # All owners inactive (already released on both sides) stays decidable.
    graph, declarations = _shared_owner_graph(base_requirement=True, shared=False)
    plan = _plan(
        graph,
        {"payload.x": 1, "trigger.a": False},
        {"payload.x": 2, "trigger.a": False},
        rules=declarations,
    )
    assert plan.entry_for("contract:v2-t-a:v2").confirmation == "confirmed_reopen"

    # Active + inactive: the applicable owner keeps the field active.
    shared_graph, shared_declarations = _shared_owner_graph(
        base_requirement=False, shared=True
    )
    plan = _plan(
        shared_graph,
        {"payload.x": 1, "trigger.a": True, "trigger.b": False},
        {"payload.x": 2, "trigger.a": True, "trigger.b": False},
        rules=shared_declarations,
    )
    assert plan.entry_for("contract:v2-t-a:v2").confirmation == "confirmed_reopen"


def test_owner_all_unknown_owners_stay_candidate():
    graph, declarations = _shared_owner_graph(base_requirement=False, shared=True)
    plan = _plan(graph, {"payload.x": 1}, {"payload.x": 2}, rules=declarations)
    assert plan.entry_for("contract:v2-t-a:v2").confirmation == "candidate_check"
    assert plan.candidate_check_contract_ids == ("contract:v2-t-a:v2",)


def test_unconditional_fact_still_reopens():
    graph, declarations = _shared_owner_graph(base_requirement=False, shared=False)
    # plain.x is a plain required fact of this contract and no rule controls
    # it; changing it reopens the chapter.
    plan = _plan(graph, {"plain.x": 1}, {"plain.x": 2}, rules=declarations)
    assert plan.confirmed_reopen_contract_ids == ("contract:v2-t-a:v2",)


def test_consistency_and_scheduling_never_override_own_conditional_decision():
    rules_a = (
        _conditional_rule("rule:a", triggers=("trigger.a",), when_active=("payload.x",)),
    )
    rules_b = (
        _conditional_rule("rule:b", triggers=("trigger.b",), when_active=("payload.x",)),
    )
    payload = _registry(
        [
            _chapter(
                "v2_t_a",
                facts=(("plain.fact", "required"), ("payload.x", "required")),
                conditional_rules=rules_a,
            ),
            _chapter(
                "v2_t_b",
                facts=(("plain.fact", "required"),),
                conditional_rules=rules_b,
                deps=("contract:v2-t-a:v2",),
                repair_policy=_policy("v2_t_b", ("contract:v2-t-a:v2",)),
            ),
        ]
    )
    document = load_chapter_registry(payload)
    graph = build_dependency_graph(document)
    declarations = []
    for entry in document.chapters:
        trigger_path = (
            "trigger.a" if entry.contract.semantic_node_id == "v2_t_a" else "trigger.b"
        )
        rule = entry.contract.conditional_applicability_rules[0]
        declarations.append(
            RulePredicate(
                rule_id=rule.conditional_applicability_rule_id,
                source_rule_sha256=rule.material_sha256(),
                predicates=(FactPredicate(fact_path=trigger_path, expected=True),),
                source_contract_sha256=entry.contract.material_sha256(),
                conditional_fact_paths=("payload.x",),
            )
        )
    declarations = tuple(declarations)

    # Chapter a's payload.x requirement is controlled by its own unknown rule
    # (candidate); chapter b's when-active owner is applicable (reopen).  The
    # consistency link on shared paths must not let b's decided owner flip a's
    # own undecided conditional decision, and b's scheduling dependency on a
    # must not decide a's rule either — while b itself stays a confirmed
    # reopen through its own active owner.
    plan = _plan(
        graph,
        {"payload.x": 1, "trigger.b": True},
        {"payload.x": 2, "trigger.b": True},
        rules=declarations,
    )
    entry_a = plan.entry_for("contract:v2-t-a:v2")
    assert entry_a.confirmation == "candidate_check"
    assert entry_a.rule_plans[0].rule_id == "rule:a"
    assert entry_a.rule_plans[0].state_after == "conditional"
    assert plan.candidate_check_contract_ids == ("contract:v2-t-a:v2",)
    entry_b = plan.entry_for("contract:v2-t-b:v2")
    assert entry_b.confirmation == "confirmed_reopen"
    assert entry_b.rule_plans[0].rule_id == "rule:b"
    assert entry_b.rule_plans[0].state_after == "applicable"
    assert plan.is_executable() is True


def test_hard_cycle_still_rejected_for_plan_graphs():
    shared = (("test.fact.shared", "required"),)
    cyclic = _registry(
        [
            _chapter(
                "v2_t_a",
                facts=shared,
                deps=("contract:v2-t-c:v2",),
                repair_policy=_policy("v2_t_a", ("contract:v2-t-c:v2",)),
            ),
            _chapter(
                "v2_t_b",
                facts=shared,
                deps=("contract:v2-t-a:v2",),
                repair_policy=_policy("v2_t_b", ("contract:v2-t-a:v2",)),
            ),
            _chapter(
                "v2_t_c",
                facts=shared,
                deps=("contract:v2-t-b:v2",),
                repair_policy=_policy("v2_t_c", ("contract:v2-t-b:v2",)),
            ),
        ]
    )
    with pytest.raises(DependencyGraphError) as excinfo:
        build_dependency_graph(load_chapter_registry(cyclic))
    assert "scheduling cycle" in str(excinfo.value)
