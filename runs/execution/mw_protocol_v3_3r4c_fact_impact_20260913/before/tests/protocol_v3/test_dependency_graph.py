"""Task 3R.4 tests: registry-level typed dependency / impact graph.

Red-first contract: this test module was authored before
``services/api/app/protocol_workflow/registries/dependency_graph.py`` existed
and was observed failing as a collection error (module not found) before the
implementation landed.  No assertion was weakened and no ``xfail`` is used.

The binding deterministic list from
``reviews/mw_protocol_v3_3r4_dependency_preparation_20260906.md`` is covered by:

* ``test_hard_scheduling_cycle_rejected``
* ``test_reciprocal_consistency_links_are_legal_and_create_no_false_cycle``
* ``test_missing_repair_owner_and_unknown_target_are_identified``
* ``test_unrelated_chapters_remain_stable``
* ``test_broad_dose_endpoint_change_returns_every_affected_chapter_without_truncation``
* ``test_same_fact_update_has_a_single_adoption_effect``

The graph is a read-only projection over the accepted 111-carrier assembled
registry (``runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_assembled.json``).
It is a pure function of (registry, changed material facts); it is not a second
editable store and it renders no new content authority.  Medical adequacy and
the end-to-end document-edit pipeline (6R) are explicitly out of scope.
"""

from __future__ import annotations

import collections
import dataclasses
import itertools
import json
from pathlib import Path

import pytest

from app.protocol_workflow.registries.chapters import load_chapter_registry
from app.protocol_workflow.registries.dependency_graph import (
    DependencyGraphError,
    EdgeKind,
    MembershipSource,
    build_dependency_graph,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_REGISTRY_PATH = (
    REPO_ROOT
    / "runs/mw_protocol_v3_3r3_batch8_fresh_20260911/final_all8_assembled.json"
)

TEMPLATE_ID = "tp_ma_07_v2"
TEMPLATE_SHA256 = (
    "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756"
)

#: Accepted-registry anchors (frozen 3R.3 artifact; counts are never guessed).
ACCEPTED_NODE_COUNT = 111
ACCEPTED_SCHEDULING_EDGE_COUNT = 41
ACCEPTED_CONSISTENCY_EDGE_COUNT = 43
ACCEPTED_DEPENDENT_CARRIER_COUNT = 34

#: High-fan-out dose / endpoint fact paths and their complete accepted closures.
BROAD_FACT_CASES = (
    ("picos.intervention_dose_regimen", 1, 24),
    ("picos.primary_endpoint", 4, 24),
)

#: Conditional-only fact paths (declared by conditional_applicability_rules and
#: by no unconditionally required fact_requirement).
CONDITIONAL_WHEN_ACTIVE_ONLY = "procedure.contact_visit_date"
CONDITIONAL_WHEN_ACTIVE_ONLY_CONTRACT = "contract:v2-n-7-3:v2"
CONDITIONAL_TRIGGER_ONLY = "safety.central_lab_applicable"
CONDITIONAL_TRIGGER_ONLY_CONTRACT = "contract:v2-n-9-2:v2"

#: A fact path carried by exactly one chapter with no consistency or scheduling
#: neighbour: its change must not move any other chapter.
ISOLATED_FACT_PATH = "diagram.phase_arm_structure"
ISOLATED_FACT_CONTRACT = "contract:v2-n-1-2:v2"
UNRELATED_TO_ISOLATED = "contract:v2-n-6-1-2:v2"


# ---------------------------------------------------------------------------
# Synthetic registries (valid per the existing closed loader; tiny on purpose).
# ---------------------------------------------------------------------------


def _contract_id(node_id: str) -> str:
    return "contract:" + node_id.replace("_", "-") + ":v2"


def _fact_requirement(fact_path: str, obligation: str) -> dict:
    return {
        "fact_path": fact_path,
        "obligation": obligation,
        "rationale": f"{fact_path} 的测试义务。",
    }


def _conditional_rule(
    rule_id: str, *, triggers: tuple[str, ...], when_active: tuple[str, ...]
) -> dict:
    return {
        "conditional_applicability_rule_id": rule_id,
        "triggering_fact_paths": list(triggers),
        "condition": "测试条件",
        "rationale": "测试条件适用性规则。",
        "required_when_active_fact_paths": list(when_active),
    }


def _policy(node_id: str, dependency_ids: tuple[str, ...], owner: str = "ai") -> dict:
    return {
        "dependency_repair_policy_id": f"repair:{node_id.replace('_', '-')}:v2",
        "dependency_ids": list(dependency_ids),
        "downstream_impact": "上游依赖漂移时修复本节点。",
        "repair_owner": owner,
        "max_repair_attempts": 1,
        "repair_steps": [
            {
                "repair_step_id": f"repair:{node_id.replace('_', '-')}:v2:step",
                "sequence": 1,
                "action": "按上游变更重算本节点。",
                "owner": owner,
            }
        ],
    }


def _chapter(
    node_id: str,
    *,
    facts: tuple[tuple[str, str], ...] = (),
    conditional_rules: tuple[dict, ...] = (),
    deps: tuple[str, ...] = (),
    repair_policy: dict | None = None,
) -> dict:
    contract_id = _contract_id(node_id)
    slug = node_id.replace("_", "-")
    return {
        "node_id": node_id,
        "coverage_role": "heading_leaf",
        "contract": {
            "chapter_contract_id": contract_id,
            "semantic_node_id": node_id,
            "contract_version": "test-v1",
            "template_id": TEMPLATE_ID,
            "template_sha256": TEMPLATE_SHA256,
            "chapter_skill_id": f"skill:chapter:{slug}:test",
            "chapter_skill_version": "test-v1",
            "substantive_content": {
                "substantive_content_contract_id": f"content:{slug}:v2",
                "chapter_contract_id": contract_id,
                "fact_requirements": [
                    _fact_requirement(path, obligation) for path, obligation in facts
                ],
                "claim_requirements": [
                    {
                        "claim_type": "test_claim",
                        "obligation": "required",
                        "rationale": "测试声明义务。",
                    }
                ],
                "project_specific_elements": [f"{node_id} 的测试项目要素。"],
                "skeleton_risk_rules": ["测试骨架风险规则。"],
            },
            "word_rules": {
                "word_formatting_rules_id": f"word:rules:{slug}",
                "required_styles": ["Heading 1"],
            },
            "positive_qc_rules": [
                {
                    "positive_qc_rule_id": f"qc:{slug}:1",
                    "rule": "测试正性 QC 规则。",
                }
            ],
            "conditional_applicability_rules": list(conditional_rules),
            "dependency_ids": list(deps),
            "dependency_repair_policy": repair_policy,
            "canonical_state": "frozen",
        },
        "skills": [
            {
                "skill_id": f"skill:chapter:{slug}:test",
                "skill_version": "test-v1",
                "node_id": node_id,
                "chapter_contract_id": contract_id,
                "template_id": TEMPLATE_ID,
                "template_sha256": TEMPLATE_SHA256,
                "input_schema_ref": (
                    "app.protocol_workflow.registries.chapters:ChapterSkillInput"
                ),
                "output_schema_ref": (
                    "app.protocol_workflow.registries.chapters:ChapterSkillOutput"
                ),
                "prompt_contract": {
                    "prompt_version": "test-v1",
                    "instructions": "测试指令。",
                    "forbidden_behaviors": ["不得虚构事实。"],
                },
                "provenance_requirements": ["provenance:test"],
                "error_codes": [f"err:{slug}:missing"],
            }
        ],
    }


def _registry(chapters: list[dict]) -> dict:
    fact_paths = []
    for chapter in chapters:
        contract = chapter["contract"]
        for requirement in contract["substantive_content"]["fact_requirements"]:
            fact_paths.append(requirement["fact_path"])
        for rule in contract["conditional_applicability_rules"]:
            fact_paths.extend(rule["triggering_fact_paths"])
            fact_paths.extend(rule["required_when_active_fact_paths"])
    return {
        "schema_version": "protocol-v3-chapter-registry.v1",
        "generated_for": "test:3r4:dependency-graph",
        "authority": "3R.4 synthetic test fixture; not product content",
        "template_id": TEMPLATE_ID,
        "template_sha256": TEMPLATE_SHA256,
        "fact_vocabulary": sorted(set(fact_paths) or {"test.fact.alpha"}),
        "claim_vocabulary": ["test_claim"],
        "chapters": chapters,
        "fixtures": [],
    }


def _edge_pairs(graph, kind: EdgeKind) -> set[tuple[str, str]]:
    pairs = set()
    for edge in graph.edges:
        if edge.kind is not kind:
            continue
        if kind is EdgeKind.SCHEDULING:
            pairs.add((edge.upstream_contract_id, edge.dependent_contract_id))
        elif kind is EdgeKind.CONSISTENCY_IMPACT:
            pairs.add((edge.left_contract_id, edge.right_contract_id))
        else:  # fact_membership
            pairs.add((edge.contract_id, edge.fact_path))
    return pairs


# ---------------------------------------------------------------------------
# Independent reference closure over the raw accepted JSON (no module code).
# ---------------------------------------------------------------------------


def _reference_closure(fact_paths: tuple[str, ...]) -> set[str]:
    payload = json.loads(REAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    carriers: dict[str, set[str]] = collections.defaultdict(set)
    dependents: dict[str, set[str]] = collections.defaultdict(set)
    for chapter in payload["chapters"]:
        contract_id = chapter["contract"]["chapter_contract_id"]
        content = chapter["contract"]["substantive_content"]
        for requirement in content["fact_requirements"]:
            carriers[requirement["fact_path"]].add(contract_id)
        for rule in chapter["contract"].get("conditional_applicability_rules", []):
            for path in rule["triggering_fact_paths"]:
                carriers[path].add(contract_id)
            for path in rule["required_when_active_fact_paths"]:
                carriers[path].add(contract_id)
        for dependency in chapter["contract"].get("dependency_ids", []):
            dependents[dependency].add(contract_id)
    links: dict[str, set[str]] = collections.defaultdict(set)
    for carriers_for_fact in carriers.values():
        for left, right in itertools.combinations(sorted(carriers_for_fact), 2):
            links[left].add(right)
            links[right].add(left)
    affected = {cid for path in fact_paths for cid in carriers[path]}
    frontier = set(affected)
    while frontier:
        discovered: set[str] = set()
        for contract_id in sorted(frontier):
            discovered |= (links[contract_id] | dependents[contract_id]) - affected
        affected |= discovered
        frontier = discovered
    return affected


@pytest.fixture(scope="module")
def real_graph():
    return build_dependency_graph(REAL_REGISTRY_PATH)


# ---------------------------------------------------------------------------
# Binding deterministic tests (prep doc list).
# ---------------------------------------------------------------------------


def test_hard_scheduling_cycle_rejected():
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
    document = load_chapter_registry(cyclic)
    with pytest.raises(DependencyGraphError) as excinfo:
        build_dependency_graph(document)
    message = str(excinfo.value)
    assert "scheduling cycle" in message
    for contract_id in (
        "contract:v2-t-a:v2",
        "contract:v2-t-b:v2",
        "contract:v2-t-c:v2",
    ):
        assert contract_id in message

    # Reciprocal shared-fact links must never be used as a cycle workaround:
    # the same three chapters with the closing hard edge removed build fine and
    # carry consistency edges on every pair.
    acyclic = _registry(
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
            _chapter("v2_t_c", facts=shared),
        ]
    )
    graph = build_dependency_graph(load_chapter_registry(acyclic))
    assert graph.findings == ()
    assert _edge_pairs(graph, EdgeKind.SCHEDULING) == {
        ("contract:v2-t-c:v2", "contract:v2-t-a:v2"),
        ("contract:v2-t-a:v2", "contract:v2-t-b:v2"),
    }
    assert _edge_pairs(graph, EdgeKind.CONSISTENCY_IMPACT) == {
        ("contract:v2-t-a:v2", "contract:v2-t-b:v2"),
        ("contract:v2-t-a:v2", "contract:v2-t-c:v2"),
        ("contract:v2-t-b:v2", "contract:v2-t-c:v2"),
    }


def test_reciprocal_consistency_links_are_legal_and_create_no_false_cycle():
    document = load_chapter_registry(
        _registry(
            [
                _chapter(
                    "v2_t_a",
                    facts=(("test.fact.shared", "required"),),
                    deps=("contract:v2-t-b:v2",),
                    repair_policy=_policy("v2_t_a", ("contract:v2-t-b:v2",)),
                ),
                _chapter(
                    "v2_t_b",
                    facts=(
                        ("test.fact.shared", "required"),
                        ("test.fact.beta", "optional"),
                    ),
                ),
                _chapter(
                    "v2_t_c",
                    facts=(("test.fact.shared", "required"),),
                    deps=("contract:v2-t-a:v2",),
                    repair_policy=_policy("v2_t_c", ("contract:v2-t-a:v2",)),
                ),
            ]
        )
    )
    graph = build_dependency_graph(document)
    assert graph.findings == ()

    scheduling = _edge_pairs(graph, EdgeKind.SCHEDULING)
    assert scheduling == {
        ("contract:v2-t-b:v2", "contract:v2-t-a:v2"),
        ("contract:v2-t-a:v2", "contract:v2-t-c:v2"),
    }
    consistency = {
        (edge.left_contract_id, edge.right_contract_id): edge
        for edge in graph.edges
        if edge.kind is EdgeKind.CONSISTENCY_IMPACT
    }
    assert set(consistency) == {
        ("contract:v2-t-a:v2", "contract:v2-t-b:v2"),
        ("contract:v2-t-a:v2", "contract:v2-t-c:v2"),
        ("contract:v2-t-b:v2", "contract:v2-t-c:v2"),
    }
    for edge in consistency.values():
        assert edge.reciprocal is True
        assert edge.shared_fact_paths == ("test.fact.shared",)
    # The pair carrying both a hard edge and a reciprocal clinical link stays
    # legal: the consistency link never enters the scheduling DAG.
    order = graph.topological_order()
    assert len(order) == 3
    assert order.index("contract:v2-t-b:v2") < order.index("contract:v2-t-a:v2")
    assert order.index("contract:v2-t-a:v2") < order.index("contract:v2-t-c:v2")


def test_missing_repair_owner_and_unknown_target_are_identified():
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
    assert all(finding.severity == "error" for finding in graph.findings)
    ownerless = next(
        finding
        for finding in graph.findings
        if finding.code == "missing_repair_owner"
    )
    assert ownerless.location == "contract:v2-t-a:v2->contract:v2-t-b:v2"
    unknown = next(
        finding
        for finding in graph.findings
        if finding.code == "unknown_dependency_target"
    )
    assert unknown.location == "contract:v2-t-ghost:v2->contract:v2-t-b:v2"

    # Identified, never silently dropped: both declared hard edges survive.
    scheduling = {
        edge.upstream_contract_id: edge
        for edge in graph.edges
        if edge.kind is EdgeKind.SCHEDULING
    }
    assert set(scheduling) == {"contract:v2-t-a:v2", "contract:v2-t-ghost:v2"}
    assert scheduling["contract:v2-t-a:v2"].repair_owner is None
    assert scheduling["contract:v2-t-ghost:v2"].repair_owner == "ai"
    assert _edge_pairs(graph, EdgeKind.SCHEDULING) == {
        ("contract:v2-t-a:v2", "contract:v2-t-b:v2"),
        ("contract:v2-t-ghost:v2", "contract:v2-t-b:v2"),
    }
    # The dangling target is not a registry carrier and is never invented.
    report = graph.impact(["test.fact.beta"])
    assert report.affected_contract_ids == ("contract:v2-t-b:v2",)
    assert report.findings == graph.findings
    assert all(node.contract_id != "contract:v2-t-ghost:v2" for node in graph.nodes)
    # It cannot corrupt the resolvable order either: the remaining hard edge
    # still orders the accepted carriers.
    assert graph.topological_order() == (
        "contract:v2-t-a:v2",
        "contract:v2-t-b:v2",
    )


def test_unrelated_chapters_remain_stable(real_graph):
    document = load_chapter_registry(
        _registry(
            [
                _chapter("v2_t_a", facts=(("test.fact.alpha", "required"),)),
                _chapter("v2_t_b", facts=(("test.fact.alpha", "required"),)),
                _chapter("v2_t_c", facts=(("test.fact.gamma", "required"),)),
                _chapter("v2_t_d", facts=(("test.fact.gamma", "required"),)),
            ]
        )
    )
    graph = build_dependency_graph(document)
    projection_before = graph.projection_sha256()
    report = graph.impact(["test.fact.alpha"])
    assert report.affected_contract_ids == (
        "contract:v2-t-a:v2",
        "contract:v2-t-b:v2",
    )
    assert report.affects("contract:v2-t-c:v2") is False
    assert report.affects("contract:v2-t-d:v2") is False
    second = graph.impact(["test.fact.gamma"])
    assert second.affected_contract_ids == (
        "contract:v2-t-c:v2",
        "contract:v2-t-d:v2",
    )
    assert second.affects("contract:v2-t-a:v2") is False
    assert second.affects("contract:v2-t-b:v2") is False
    assert graph.projection_sha256() == projection_before
    assert graph.contracts_for_fact("test.fact.gamma") == (
        "contract:v2-t-c:v2",
        "contract:v2-t-d:v2",
    )

    # Accepted registry: a chapter-unique fact moves exactly one chapter.
    projection_before_real = real_graph.projection_sha256()
    isolated = real_graph.impact([ISOLATED_FACT_PATH])
    assert isolated.affected_contract_ids == (ISOLATED_FACT_CONTRACT,)
    assert isolated.affects(UNRELATED_TO_ISOLATED) is False
    assert isolated.affects("contract:v2-n-11-1:v2") is False
    assert real_graph.projection_sha256() == projection_before_real

    # Confirmation invalidation is keyed to the changed material facts: a fact
    # path no chapter declares invalidates nothing instead of reopening all 111.
    unindexed = real_graph.impact(["test.fact.not.in.the.registry"])
    assert unindexed.affected_contract_ids == ()
    assert unindexed.unindexed_fact_paths == ("test.fact.not.in.the.registry",)


def test_broad_dose_endpoint_change_returns_every_affected_chapter_without_truncation(
    real_graph,
):
    for fact_path, direct_size, expected_affected in BROAD_FACT_CASES:
        direct = real_graph.contracts_for_fact(fact_path)
        report = real_graph.impact([fact_path])
        assert len(direct) == direct_size
        assert set(direct) < set(report.affected_contract_ids)
        assert len(report.affected_contract_ids) == expected_affected
        assert report.affected_contract_ids == tuple(
            sorted(report.affected_contract_ids)
        )
        assert len(report.affected_contract_ids) == len(
            set(report.affected_contract_ids)
        )
        # Complete set: equal to an independent naive closure over the raw JSON.
        assert set(report.affected_contract_ids) == _reference_closure((fact_path,))
        # Every affected chapter is classified exactly once (no omission).
        assert (
            len(report.direct_contract_ids)
            + len(report.consistency_contract_ids)
            + len(report.scheduling_contract_ids)
            == len(report.affected_contract_ids)
        )
        assert len(report.scheduling_contract_ids) > 0


def test_same_fact_update_has_a_single_adoption_effect(real_graph):
    first = real_graph.impact(["picos.primary_endpoint"])
    second = real_graph.impact(["picos.primary_endpoint"])
    assert first == second
    assert first.impact_sha256 == second.impact_sha256

    # The same fact update expressed twice / in another order is one adoption.
    duplicated = real_graph.impact(
        ["picos.primary_endpoint", "picos.primary_endpoint"]
    )
    assert duplicated.changed_fact_paths == ("picos.primary_endpoint",)
    assert duplicated.impact_sha256 == first.impact_sha256

    # Graph rendering is a projection, not a second editable store: reading it
    # never mutates the graph and a rebuilt graph adopts the same state.
    projection_before = real_graph.projection_sha256()
    real_graph.impact(["picos.intervention_dose_regimen"])
    assert real_graph.projection_sha256() == projection_before
    rebuilt = build_dependency_graph(REAL_REGISTRY_PATH)
    assert rebuilt.registry_sha256 == real_graph.registry_sha256
    assert rebuilt.impact(["picos.primary_endpoint"]).impact_sha256 == (
        first.impact_sha256
    )

    # A combined update is the union of the single-fact adoptions.
    dose = real_graph.impact(["intervention.dose_regimen"])
    combined = real_graph.impact(
        ["picos.primary_endpoint", "intervention.dose_regimen"]
    )
    assert set(combined.affected_contract_ids) == set(
        first.affected_contract_ids
    ) | set(dose.affected_contract_ids)
    assert len(combined.affected_contract_ids) == 31
    assert len(combined.affected_contract_ids) > len(first.affected_contract_ids)

    # The module keeps no editable store: its value objects are frozen.
    with pytest.raises(dataclasses.FrozenInstanceError):
        real_graph.nodes = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        real_graph.impact(["picos.primary_endpoint"]).affected_contract_ids = ()


# ---------------------------------------------------------------------------
# Further deterministic checks over the accepted registry.
# ---------------------------------------------------------------------------


def test_typed_edges_keep_the_three_relationship_kinds_distinct(real_graph):
    kinds = {edge.kind for edge in real_graph.edges}
    assert kinds == {
        EdgeKind.FACT_MEMBERSHIP,
        EdgeKind.SCHEDULING,
        EdgeKind.CONSISTENCY_IMPACT,
    }

    # Fact membership indexes every obligation and resolves conditional paths
    # (conditional-only paths are first-class change targets, never dropped).
    by_source = collections.Counter(
        membership.source for membership in real_graph.memberships
    )
    assert by_source == collections.Counter(
        {
            MembershipSource.FACT_REQUIREMENT: 759,
            MembershipSource.CONDITIONAL_TRIGGER: 52,
            MembershipSource.CONDITIONAL_WHEN_ACTIVE: 80,
        }
    )
    by_obligation = collections.Counter(
        membership.obligation for membership in real_graph.memberships
    )
    assert by_obligation == collections.Counter(
        {"required": 586, "optional": 88, "forbidden": 85, None: 132}
    )
    assert all(
        membership.obligation is None
        for membership in real_graph.memberships
        if membership.source is not MembershipSource.FACT_REQUIREMENT
    )
    assert all(
        membership.conditional_rule_ids
        for membership in real_graph.memberships
        if membership.source is not MembershipSource.FACT_REQUIREMENT
    )
    assert len({item.fact_path for item in real_graph.memberships}) == 724

    payload = json.loads(REAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    declared_pairs = set()
    carriers = 0
    for chapter in payload["chapters"]:
        contract = chapter["contract"]
        if contract.get("dependency_ids"):
            carriers += 1
        for dependency in contract.get("dependency_ids", []):
            declared_pairs.add(
                (dependency, contract["chapter_contract_id"])
            )
    assert carriers == ACCEPTED_DEPENDENT_CARRIER_COUNT
    # Scheduling admits explicit dependency_ids only; no cross-reference is
    # promoted into a hard edge.
    assert _edge_pairs(real_graph, EdgeKind.SCHEDULING) == declared_pairs
    assert len(declared_pairs) == ACCEPTED_SCHEDULING_EDGE_COUNT
    assert len(_edge_pairs(real_graph, EdgeKind.CONSISTENCY_IMPACT)) == (
        ACCEPTED_CONSISTENCY_EDGE_COUNT
    )
    # endpoint/estimand/statistics style reciprocity: the four carriers of the
    # primary endpoint fact produce six reciprocal consistency pairs.
    endpoint_pairs = [
        edge
        for edge in real_graph.edges
        if edge.kind is EdgeKind.CONSISTENCY_IMPACT
        and "picos.primary_endpoint" in edge.shared_fact_paths
    ]
    assert len(endpoint_pairs) == 6
    assert all(edge.reciprocal for edge in endpoint_pairs)


def test_accepted_registry_graph_is_complete_acyclic_and_error_free(real_graph):
    assert real_graph.findings == ()
    assert len(real_graph.nodes) == ACCEPTED_NODE_COUNT
    node_ids = {node.contract_id for node in real_graph.nodes}
    assert len(node_ids) == ACCEPTED_NODE_COUNT
    for edge in real_graph.scheduling_edges:
        assert edge.dependent_contract_id in node_ids
        assert edge.upstream_contract_id in node_ids
        assert edge.repair_owner in {"ai", "user", "system"}
    for membership in real_graph.memberships:
        assert membership.contract_id in node_ids
    order = real_graph.topological_order()
    assert len(order) == ACCEPTED_NODE_COUNT
    position = {contract_id: index for index, contract_id in enumerate(order)}
    for edge in real_graph.scheduling_edges:
        assert position[edge.upstream_contract_id] < position[edge.dependent_contract_id]


def test_conditional_fact_paths_resolve_to_their_chapters(real_graph):
    when_active = [
        membership
        for membership in real_graph.memberships
        if membership.fact_path == CONDITIONAL_WHEN_ACTIVE_ONLY
    ]
    assert [(item.contract_id, item.source) for item in when_active] == [
        (
            CONDITIONAL_WHEN_ACTIVE_ONLY_CONTRACT,
            MembershipSource.CONDITIONAL_WHEN_ACTIVE,
        )
    ]
    assert when_active[0].conditional_rule_ids

    trigger_only = [
        membership
        for membership in real_graph.memberships
        if membership.fact_path == CONDITIONAL_TRIGGER_ONLY
    ]
    assert [(item.contract_id, item.source) for item in trigger_only] == [
        (CONDITIONAL_TRIGGER_ONLY_CONTRACT, MembershipSource.CONDITIONAL_TRIGGER)
    ]

    # A conditional-only fact path is a first-class change target: the chapter
    # that requires it only when its rule is active is still affected.
    report = real_graph.impact([CONDITIONAL_WHEN_ACTIVE_ONLY])
    assert CONDITIONAL_WHEN_ACTIVE_ONLY_CONTRACT in report.affected_contract_ids
    assert report.unindexed_fact_paths == ()

    # A trigger-only change marks the applicability owner chapter as affected.
    trigger_report = real_graph.impact([CONDITIONAL_TRIGGER_ONLY])
    assert CONDITIONAL_TRIGGER_ONLY_CONTRACT in trigger_report.affected_contract_ids


def test_build_dependency_graph_accepts_document_mapping_and_path():
    payload = _registry(
        [
            _chapter("v2_t_a", facts=(("test.fact.shared", "required"),)),
            _chapter("v2_t_b", facts=(("test.fact.shared", "required"),)),
        ]
    )
    from_document = build_dependency_graph(load_chapter_registry(payload))
    from_mapping = build_dependency_graph(payload)
    assert from_document.projection_sha256() == from_mapping.projection_sha256()
    assert from_document.registry_sha256 == from_mapping.registry_sha256

    from_path = build_dependency_graph(REAL_REGISTRY_PATH)
    from_real_mapping = build_dependency_graph(
        json.loads(REAL_REGISTRY_PATH.read_text(encoding="utf-8"))
    )
    assert from_path.registry_sha256 == from_real_mapping.registry_sha256
    assert from_path.projection_sha256() == from_real_mapping.projection_sha256()
