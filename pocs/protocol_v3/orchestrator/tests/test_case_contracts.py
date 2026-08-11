"""Protocol v3 orchestrator PoC — integrated Task 2.1 case-contract tests
(worker 03).

The single integrated test for the three frozen Task 2.1 orchestrator PoC
cases (eligibility, objective-estimand-endpoint, sample-size).  It verifies,
for all three graphs at once:

* **Closure** — registry closedness, dependency/topology closure, acyclicity
  (verified with an independent reference implementation, not the library
  helper), closed Gate/owner/schema/edge vocabularies, every edge
  load-bearing (removing any one fails closed), required injection coverage,
  deterministic material hash pinned to stable constants.
* **Recovery / concurrent injection representability** — kill-before /
  kill-after / duplicate-resume / concurrent-decision / old-graph-migration
  are declared per graph and the deterministic fakes represent them:
  idempotent logical keys, no duplicate semantic effect, fail-closed
  conflicts.
* **Isolation** — project/branch binding guards (``CC_BINDING_MISMATCH``),
  FakeRuntime isolation across projects/branches, deterministic replay
  across equal construction.
* **Fail-closed** — unknown node/owner/Gate/schema/dependency, cycles,
  invalid side-effect/failure-policy/injection declarations, mutable nested
  inputs and deep-immutability violations are rejected with the stable typed
  codes.
* **No product/scheduler/provider/storage surface** — importing the
  orchestrator tree pulls in no product, scheduler, provider or storage
  module (subprocess module-delta probe).

Every number in the case definitions is a retry-attempt limit; the tests
assert no other numeric value exists in any graph payload, so no invented
sample-size value can become a clinical fact/default.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any, Dict, Tuple

import pytest
from pydantic import ValidationError

from pocs.protocol_v3.orchestrator import (
    CASE_CONTRACT_SCHEMA_VERSION,
    CASE_IDS,
    INJECTION_KINDS,
    CaseContractError,
    CaseGraph,
    CaseId,
    Edge,
    EdgeKind,
    FailurePolicy,
    FrozenJsonDict,
    FrozenJsonList,
    GateKind,
    InjectionKind,
    InjectionPoint,
    NodeContract,
    NodeKind,
    OwnerRole,
    SchemaDecl,
    SideEffectKind,
    assert_case_graph_binding,
    assert_deep_immutable,
    canonical_json,
    freeze_input,
)
from pocs.protocol_v3.orchestrator.cases import (
    CASE_MODULES,
    assert_registry_closed,
    iter_case_graphs,
    load_case,
)
from pocs.protocol_v3.orchestrator.fakes import (
    DEFAULT_EPOCH,
    DEFAULT_STEP,
    ArtifactRef,
    DecisionRecord,
    FakeClock,
    FakeContractError,
    FakeIdFactory,
    FakeReservationStatus,
    FakeRuntime,
)

# ---------------------------------------------------------------------------
# Pinned deterministic-hash contract (computed at Task 2.1 worker 03 build
# time under python3.12 / pydantic 2.13.4; stable across processes because
# the material payload is identity + sorted structure only, no timestamps,
# run ids, sessions or counters).
# ---------------------------------------------------------------------------

EXPECTED_HASHES: Dict[str, str] = {
    "eligibility": (
        "f9d99776159d8d5a48dccfe0956746d8c1f4469bf2141a321b91b1cfbe1f484b"
    ),
    "objective_estimand_endpoint": (
        "42c3ed3523c8a201340a6ad4a1546e55d37e1f518c17d3d952028dddd01226d0"
    ),
    "sample_size": "77870c7aabf047030716da6ad00727926529b1d4b719ed4aeed35445ed195ef4",
}

#: Shared project/branch identity the three cases bind to (each case module
#: exports the same constants; one FakeRuntime binds to all three).
PROJECT_ID = "mw-protocol-v3-poc"
BRANCH_ID = "orchestrator-poc-v1"

#: Labeled synthetic predecessor graph versions pinned by the
#: old-graph-migration injections (never shipped).
OLD_GRAPH_VERSIONS = {
    "eligibility": "eligibility_graph_v0",
    "objective_estimand_endpoint": "objective_estimand_endpoint_graph_v0",
    "sample_size": "sample_size_graph_v0",
}

INJECTION_KIND_NAMES = frozenset(kind.value for kind in INJECTION_KINDS)

#: Top-level modules that MUST NOT be imported by the orchestrator tree.
FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "app",
        "services",
        "packages",
        "langgraph",
        "langchain",
        "sqlalchemy",
        "sqlite3",
        "openai",
        "anthropic",
        "httpx",
        "requests",
        "fastapi",
        "torch",
        "numpy",
        "scipy",
        "statsmodels",
    }
)
FORBIDDEN_IMPORT_PREFIXES = (
    "pocs.protocol_v3.storage",
    "pocs.protocol_v3.word_receipt",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _err_codes(exc: ValidationError) -> Tuple[str, ...]:
    """Extract the stable CaseContractError codes wrapped in a
    pydantic.ValidationError (the shared models raise CaseContractError from
    ``model_validator`` callbacks; pydantic wraps them)."""
    codes: list[str] = []
    for err in exc.errors():
        ctx = err.get("ctx") or {}
        inner = ctx.get("error")
        if isinstance(inner, CaseContractError):
            codes.append(inner.code)
            continue
        message = err.get("msg", "")
        for prefix in ("CC_", "FK_"):
            start = message.find(prefix)
            if start != -1:
                codes.append(message[start : start + 60].split()[0].rstrip(":"))
                break
    return tuple(codes)


def _reference_topological_order(graph: CaseGraph) -> Tuple[str, ...]:
    """Correct Kahn topological order over *distinct* edge sources.

    Independent cross-check of ``CaseGraph.topological_order()``: parallel
    typed edges (DATA+GATE) from one source form one dependency, and this
    implementation never double-decrements (a defect that previously existed
    in the library helper and is covered by the explicit regression tests
    below).  Keeping the independent implementation means the graph contract
    is verified without trusting the helper.
    """
    node_ids = frozenset(node.node_id for node in graph.nodes)
    incoming: Dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in graph.edges:
        incoming[edge.target_node_id].add(edge.source_node_id)
    indegree = {node_id: len(sources) for node_id, sources in incoming.items()}
    ready = sorted(node_id for node_id in node_ids if indegree[node_id] == 0)
    ordered: list[str] = []
    while ready:
        current = ready.pop(0)
        ordered.append(current)
        for target in sorted(node_ids):
            if current not in incoming[target]:
                continue
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    return tuple(ordered)


def _payload_numbers(value: Any, path: str = "") -> list[Tuple[str, Any]]:
    """Every numeric value in a material payload, skipping ``allowed_attempts``
    (the only number a case definition may carry)."""
    found: list[Tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "allowed_attempts":
                continue
            found.extend(_payload_numbers(item, f"{path}.{key}" if path else key))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_payload_numbers(item, f"{path}[{index}]"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        found.append((path or "<root>", value))
    return found


def _rebuild_reversed(graph: CaseGraph) -> CaseGraph:
    """Equivalent graph constructed from reversed tuples (construction-order
    independence probe)."""
    return graph.model_copy(
        update={
            "schemas": tuple(reversed(graph.schemas)),
            "nodes": tuple(reversed(graph.nodes)),
            "edges": tuple(reversed(graph.edges)),
            "injections": tuple(reversed(graph.injections)),
        }
    )


@pytest.fixture(scope="module")
def graphs() -> Tuple[CaseGraph, ...]:
    return iter_case_graphs()


@pytest.fixture(scope="module")
def graph_by_id(graphs: Tuple[CaseGraph, ...]) -> Dict[str, CaseGraph]:
    return {graph.case_id.value: graph for graph in graphs}


# ---------------------------------------------------------------------------
# Registry closedness and loading
# ---------------------------------------------------------------------------


def test_registry_contains_exactly_the_three_frozen_cases() -> None:
    assert tuple(case_id.value for case_id in CASE_IDS) == (
        "eligibility",
        "objective_estimand_endpoint",
        "sample_size",
    )
    assert set(CASE_MODULES) == set(CASE_IDS)
    assert set(CASE_MODULES.values()) == {
        "eligibility",
        "objective_estimand_endpoint",
        "sample_size",
    }


def test_all_three_graphs_load_and_registry_is_closed(graphs) -> None:
    assert len(graphs) == 3
    assert len({graph.case_id for graph in graphs}) == 3
    assert_registry_closed(graphs)  # must not raise


def test_registry_fails_closed_when_a_case_is_missing(graphs) -> None:
    with pytest.raises(CaseContractError) as raised:
        assert_registry_closed(graphs[:2])
    assert raised.value.code == "CC_CASE_REGISTRY_OPEN"


def test_load_case_fails_closed_on_case_id_mismatch(monkeypatch) -> None:
    import pocs.protocol_v3.orchestrator.cases.eligibility as eligibility_module

    monkeypatch.setattr(eligibility_module, "GRAPH", load_case(CaseId.SAMPLE_SIZE))
    with pytest.raises(CaseContractError) as raised:
        load_case(CaseId.ELIGIBILITY)
    assert raised.value.code == "CC_CASE_ID_MISMATCH"


def test_every_graph_binds_to_the_shared_project_branch(graphs) -> None:
    for graph in graphs:
        assert graph.project_id == PROJECT_ID
        assert graph.branch_id == BRANCH_ID
        assert graph.schema_version == CASE_CONTRACT_SCHEMA_VERSION
        assert_case_graph_binding(graph, PROJECT_ID, BRANCH_ID)  # must not raise


def test_every_graph_has_distinct_stable_identity(graphs) -> None:
    assert len({graph.graph_version for graph in graphs}) == 3
    for graph in graphs:
        assert graph.graph_version.endswith("_v1")
        assert graph.material_sha256() == EXPECTED_HASHES[graph.case_id.value]


# ---------------------------------------------------------------------------
# Closure: topology, dependencies, vocabularies, acyclicity
# ---------------------------------------------------------------------------


def test_every_graph_is_acyclic_with_a_valid_reference_dependency_order(
    graphs,
) -> None:
    for graph in graphs:
        order = _reference_topological_order(graph)
        assert set(order) == {node.node_id for node in graph.nodes}
        assert len(order) == len(graph.nodes)
        position = {node_id: index for index, node_id in enumerate(order)}
        for edge in graph.edges:
            assert position[edge.source_node_id] < position[edge.target_node_id], (
                f"{graph.case_id.value}: {edge.source_node_id} must precede "
                f"{edge.target_node_id}"
            )


def test_topological_order_helper_returns_a_valid_deterministic_order(
    graphs,
) -> None:
    """Library-helper contract (regression for the Worker 01 double-decrement
    defect): the order is deterministic, covers every node exactly once, and
    every typed edge — including parallel DATA/GATE pairs from one source —
    has its source strictly before its target."""
    for graph in graphs:
        first = graph.topological_order()
        second = graph.topological_order()
        assert first == second
        assert set(first) == {node.node_id for node in graph.nodes}
        assert len(first) == len(graph.nodes)
        position = {node_id: index for index, node_id in enumerate(first)}
        for edge in graph.edges:
            assert position[edge.source_node_id] < position[edge.target_node_id], (
                f"{graph.case_id.value}: {edge.source_node_id} must precede "
                f"{edge.target_node_id} (edge kind {edge.kind.value})"
            )


def test_node_dependencies_match_declared_depends_on_distinct_sorted(
    graphs,
) -> None:
    """``node_dependencies`` returns the deterministic sorted *distinct* edge
    sources of a node; parallel typed edges (DATA+GATE) from one source count
    once, so the result equals the node's declared ``depends_on`` deduplicated
    and sorted.  Unknown node ids fail closed."""
    for graph in graphs:
        for node in graph.nodes:
            assert graph.node_dependencies(node.node_id) == tuple(
                sorted(set(node.depends_on))
            ), f"{graph.case_id.value}/{node.node_id}"
    with pytest.raises(CaseContractError) as raised:
        graphs[0].node_dependencies("ghost_node")
    assert raised.value.code == "CC_NODE_UNKNOWN"


def test_parallel_typed_edges_from_one_source_are_one_dependency(graphs) -> None:
    """Explicit regression fixture for the parallel DATA/GATE edges already
    present in the three real graphs: each graph carries at least one
    (source, target) pair with two edge kinds; the topological order places
    every such source before its target; and ``node_dependencies`` counts the
    source once (no duplicate id in the returned tuple)."""
    for graph in graphs:
        kinds_by_pair: Dict[Tuple[str, str], set[str]] = {}
        for edge in graph.edges:
            kinds_by_pair.setdefault(
                (edge.source_node_id, edge.target_node_id), set()
            ).add(edge.kind.value)
        parallel = {
            pair: kinds
            for pair, kinds in kinds_by_pair.items()
            if len(kinds) > 1
        }
        assert parallel, (
            f"{graph.case_id.value} has no parallel typed edge pair "
            "to exercise the deduplication contract"
        )
        order = graph.topological_order()
        position = {node_id: index for index, node_id in enumerate(order)}
        for (source, target), kinds in parallel.items():
            assert position[source] < position[target], (
                f"{graph.case_id.value}: parallel {source}->{target} "
                f"({sorted(kinds)}) must stay in dependency order"
            )
            assert graph.node_dependencies(target).count(source) == 1
        for node in graph.nodes:
            assert len(graph.node_dependencies(node.node_id)) == len(
                set(graph.node_dependencies(node.node_id))
            )
    # The exact regression that previously produced a non-topological order:
    # the statistical review must precede the decision lock it gates.
    sample_size = next(
        graph for graph in graphs if graph.case_id.value == "sample_size"
    )
    order = sample_size.topological_order()
    assert order.index("statistical_review") < order.index(
        "sample_size_decision_lock"
    )


def test_closed_vocabularies_and_declared_schema_closure(graphs) -> None:
    owner_roles = {role.value for role in OwnerRole}
    gate_kinds = {gate.value for gate in GateKind}
    node_kinds = {kind.value for kind in NodeKind}
    edge_kinds = {kind.value for kind in EdgeKind}
    side_effects = {kind.value for kind in SideEffectKind}
    failure_policies = {policy.value for policy in FailurePolicy}

    for graph in graphs:
        schema_names = {schema.name for schema in graph.schemas}
        node_ids = {node.node_id for node in graph.nodes}
        assert graph.root_inputs and set(graph.root_inputs) <= schema_names
        for node in graph.nodes:
            assert node.owner.value in owner_roles
            assert node.gate.value in gate_kinds
            assert node.kind.value in node_kinds
            assert node.failure_policy.value in failure_policies
            assert node.output_schema in schema_names
            assert set(node.inputs) <= schema_names
            assert set(node.depends_on) <= node_ids - {node.node_id}
        for edge in graph.edges:
            assert edge.kind.value in edge_kinds
            assert edge.source_node_id in node_ids
            assert edge.target_node_id in node_ids
        for point in graph.injections:
            assert point.injection_kind.value in {k.value for k in InjectionKind}


def test_dependencies_exactly_match_incoming_edge_sources(graphs) -> None:
    for graph in graphs:
        incoming: Dict[str, set[str]] = {node.node_id: set() for node in graph.nodes}
        for edge in graph.edges:
            incoming[edge.target_node_id].add(edge.source_node_id)
        for node in graph.nodes:
            assert set(node.depends_on) == incoming[node.node_id], (
                f"{graph.case_id.value}/{node.node_id}"
            )


def test_every_dependency_is_load_bearing(graphs) -> None:
    """Removing every edge of any (source, target) dependency fails closed:
    no declared dependency is redundant.  Parallel typed edges (DATA+GATE)
    from one source form one dependency, so the whole group is removed
    together."""
    for graph in graphs:
        groups: Dict[Tuple[str, str], list[Edge]] = {}
        for edge in graph.edges:
            groups.setdefault((edge.source_node_id, edge.target_node_id), []).append(edge)
        for (source, target), group in groups.items():
            remaining = tuple(
                candidate
                for candidate in graph.edges
                if (candidate.source_node_id, candidate.target_node_id) != (source, target)
            )
            with pytest.raises(ValidationError) as raised:
                graph.model_copy(update={"edges": remaining})
            assert "CC_EDGE_UNMATCHED_DEPENDENCY" in _err_codes(raised.value), (
                f"{graph.case_id.value}: removing {source}->{target} must fail closed"
            )


def test_every_graph_has_a_clinically_meaningful_topology(graphs) -> None:
    """Each graph contains at least one agent work node, one deterministic
    system node and exactly one user decision/lock node; every case has a
    finalizer consuming the decision record via a DECISION edge."""
    for graph in graphs:
        kinds = {node.node_id: node.kind for node in graph.nodes}
        assert any(kind is NodeKind.WORK for kind in kinds.values())
        assert any(
            kind in (NodeKind.CHECK, NodeKind.CALCULATION)
            for kind in kinds.values()
        )
        locks = [
            node
            for node in graph.nodes
            if node.kind is NodeKind.DECISION and node.owner is OwnerRole.USER
        ]
        assert len(locks) == 1
        decision_edges = [
            edge
            for edge in graph.edges
            if edge.kind is EdgeKind.DECISION and edge.source_node_id == locks[0].node_id
        ]
        assert len(decision_edges) == 1
        finalizer = next(
            node for node in graph.nodes if node.node_id == decision_edges[0].target_node_id
        )
        assert finalizer.kind is NodeKind.CHECK
        assert finalizer.owner is OwnerRole.SYSTEM


def test_sample_size_topology_binds_assumptions_to_calculation_to_decision(
    graph_by_id,
) -> None:
    graph = graph_by_id["sample_size"]
    node_ids = {node.node_id for node in graph.nodes}
    expected = {
        "define_hypothesis_and_targets",
        "define_statistical_assumptions",
        "derive_sample_size",
        "statistical_review",
        "sample_size_decision_lock",
        "finalize_sample_size",
    }
    assert node_ids == expected
    schemas = {schema.name for schema in graph.schemas}
    assert {
        "hypothesis_and_targets",
        "statistical_assumptions",
        "sample_size_calculation",
        "qc_findings",
        "sample_size_decision",
        "locked_sample_size",
    } <= schemas
    # The deterministic calculation consumes the targets and the assumption
    # set; the lock consumes the calculation and the QC findings and is
    # gated by both.
    calc = graph.node("derive_sample_size")
    assert calc.kind is NodeKind.CALCULATION
    assert calc.owner is OwnerRole.SYSTEM
    assert set(calc.inputs) == {"hypothesis_and_targets", "statistical_assumptions"}
    lock = graph.node("sample_size_decision_lock")
    assert lock.owner is OwnerRole.USER
    assert lock.gate is GateKind.USER_DECISION
    assert set(lock.inputs) >= {
        "sample_size_calculation",
        "qc_findings",
        "statistical_assumptions",
    }
    gate_sources = {
        edge.source_node_id
        for edge in graph.edges
        if edge.target_node_id == lock.node_id and edge.kind is EdgeKind.GATE
    }
    assert gate_sources == {"derive_sample_size", "statistical_review"}


def test_no_invented_numeric_value_lives_in_any_case_definition(graphs) -> None:
    """The only numbers a case graph may carry are retry-attempt limits;
    no sample-size/statistical value can become a clinical fact/default."""
    for graph in graphs:
        assert _payload_numbers(graph.material_payload()) == [], (
            f"{graph.case_id.value} carries numeric values outside allowed_attempts"
        )


def test_sample_size_assumption_schemas_are_explicitly_labeled_synthetic(
    graph_by_id,
) -> None:
    graph = graph_by_id["sample_size"]
    assumption_schemas = {
        "study_facts",
        "hypothesis_and_targets",
        "statistical_assumptions",
    }
    by_name = {schema.name: schema for schema in graph.schemas}
    for name in assumption_schemas:
        assert "synthetic" in by_name[name].description.lower(), name
    assert "synthetic" in graph.description.lower()
    assert "no invented numeric default" in graph.description.lower()


# ---------------------------------------------------------------------------
# Deterministic hashes
# ---------------------------------------------------------------------------


def test_hashes_match_pinned_contract_and_are_pairwise_distinct(graphs) -> None:
    hashes = {}
    for graph in graphs:
        digest = graph.material_sha256()
        assert digest == EXPECTED_HASHES[graph.case_id.value]
        assert len(digest) == 64
        hashes[graph.case_id.value] = digest
    assert len(set(hashes.values())) == 3


def test_hash_is_independent_of_construction_order(graphs) -> None:
    for graph in graphs:
        assert _rebuild_reversed(graph).material_sha256() == graph.material_sha256()


def test_hash_binds_project_branch_and_version(graph_by_id) -> None:
    graph = graph_by_id["eligibility"]
    original = graph.material_sha256()
    rebound = graph.model_copy(update={"branch_id": "other-poc-branch"})
    assert rebound.material_sha256() != original
    bumped = graph.model_copy(update={"graph_version": "eligibility_graph_v9"})
    assert bumped.material_sha256() != original


def test_hashes_are_stable_across_independent_processes(graphs) -> None:
    """Fresh python process (no shared module cache) reproduces the pinned
    hashes — the hash carries no session/run/clock state."""
    script = (
        "import sys; "
        "from pocs.protocol_v3.orchestrator.cases import iter_case_graphs; "
        "print(','.join(g.material_sha256() for g in iter_case_graphs()))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [os.getcwd(), "services/api", "packages", os.environ.get("PYTHONPATH", "")]
            ),
        },
    )
    assert result.returncode == 0, result.stderr
    observed = result.stdout.strip().split(",")
    expected = [EXPECTED_HASHES[graph.case_id.value] for graph in graphs]
    assert observed == expected


# ---------------------------------------------------------------------------
# Side-effect keys
# ---------------------------------------------------------------------------


def test_side_effect_key_templates_are_stable_unique_and_namespaced(graphs) -> None:
    namespace_by_case = {
        "eligibility": "eligibility.",
        "objective_estimand_endpoint": "objective_estimand.",
        "sample_size": "sample_size.",
    }
    all_templates = set()
    for graph in graphs:
        for node in graph.nodes:
            if node.side_effect_kind is SideEffectKind.NONE:
                assert node.side_effect_key_template is None
                continue
            assert node.side_effect_key_template is not None
            template = node.side_effect_key_template
            assert template.startswith(namespace_by_case[graph.case_id.value])
            assert "{" in template and "}" in template
            assert template not in all_templates  # globally unique
            all_templates.add(template)
    assert len(all_templates) == sum(
        sum(1 for n in graph.nodes if n.side_effect_kind is not SideEffectKind.NONE)
        for graph in graphs
    )


def test_every_graph_has_exactly_one_decision_record_side_effect(graphs) -> None:
    for graph in graphs:
        recorders = [
            node
            for node in graph.nodes
            if node.side_effect_kind is SideEffectKind.DECISION_RECORD
        ]
        assert len(recorders) == 1
        assert recorders[0].kind is NodeKind.DECISION
        assert recorders[0].owner is OwnerRole.USER


# ---------------------------------------------------------------------------
# Injection coverage and representability contracts
# ---------------------------------------------------------------------------


def test_all_five_injection_kinds_declared_exactly_once_per_graph(graphs) -> None:
    for graph in graphs:
        declared = [point.injection_kind for point in graph.injections]
        assert len(declared) == 5
        assert {kind.value for kind in declared} == INJECTION_KIND_NAMES
        assert set(graph.injection_kinds()) == INJECTION_KIND_NAMES


def test_injection_points_target_declared_nodes(graphs) -> None:
    for graph in graphs:
        node_ids = {node.node_id for node in graph.nodes}
        for point in graph.injections:
            if point.target_node_id is not None:
                assert point.target_node_id in node_ids
            assert point.logical_key
            assert point.expectation


def test_old_graph_migration_is_graph_level_and_pins_a_predecessor_version(
    graphs,
) -> None:
    for graph in graphs:
        migrations = [
            point
            for point in graph.injections
            if point.injection_kind is InjectionKind.OLD_GRAPH_MIGRATION
        ]
        assert len(migrations) == 1
        point = migrations[0]
        assert point.target_node_id is None
        assert point.old_graph_version == OLD_GRAPH_VERSIONS[graph.case_id.value]
        assert point.old_graph_version != graph.graph_version


# ---------------------------------------------------------------------------
# Fail-closed construction matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation, expected_code",
    [
        # unknown edge endpoints / duplicate / self edges
        (
            lambda g: {
                "edges": (
                    Edge(
                        source_node_id="ghost_node",
                        target_node_id="draft_eligibility_criteria",
                        kind=EdgeKind.DATA,
                    ),
                )
            },
            "CC_EDGE_UNKNOWN_NODE",
        ),
        (
            lambda g: {"edges": g.edges + (g.edges[0],)},
            "CC_EDGE_DUPLICATE",
        ),
        (
            lambda g: {
                "edges": g.edges
                + (
                    Edge(
                        source_node_id="draft_eligibility_criteria",
                        target_node_id="draft_eligibility_criteria",
                        kind=EdgeKind.DATA,
                    ),
                )
            },
            "CC_EDGE_SELF",
        ),
        # missing link (input coverage / dependency agreement)
        (
            lambda g: {"edges": g.edges[:-1]},
            "CC_EDGE_UNMATCHED_DEPENDENCY",
        ),
        # unknown / duplicate schemas and root inputs
        (
            lambda g: {"schemas": g.schemas + (g.schemas[0],)},
            "CC_SCHEMA_DUPLICATE",
        ),
        (
            lambda g: {"root_inputs": ("study_facts", "study_facts")},
            "CC_ROOT_INPUT_DUPLICATE",
        ),
        # unknown output schema on a node
        (
            lambda g: {
                "nodes": tuple(
                    node.model_copy(update={"output_schema": "ghost_schema"})
                    if node.node_id == "draft_eligibility_criteria"
                    else node
                    for node in g.nodes
                )
            },
            "CC_SCHEMA_UNKNOWN",
        ),
        # declared input produced by neither dependency nor root
        (
            lambda g: {
                "nodes": tuple(
                    node.model_copy(update={"inputs": ("locked_eligibility_criteria",)})
                    if node.node_id == "draft_eligibility_criteria"
                    else node
                    for node in g.nodes
                )
            },
            "CC_INPUT_UNCOVERED",
        ),
        # duplicate node id
        (
            lambda g: {"nodes": g.nodes + (g.nodes[0],)},
            "CC_NODE_DUPLICATE",
        ),
        # injection coverage / targets
        (
            lambda g: {"injections": g.injections[1:]},
            "CC_INJECTION_KIND_MISSING",
        ),
        (
            lambda g: {"injections": g.injections + (g.injections[0],)},
            "CC_INJECTION_KIND_DUPLICATE",
        ),
        (
            lambda g: {
                "injections": tuple(
                    point.model_copy(update={"target_node_id": "ghost_node"})
                    if point.injection_kind is InjectionKind.KILL_BEFORE
                    else point
                    for point in g.injections
                )
            },
            "CC_INJECTION_TARGET",
        ),
    ],
)
def test_graph_mutations_fail_closed(
    graph_by_id, mutation, expected_code
) -> None:
    graph = graph_by_id["eligibility"]
    with pytest.raises(ValidationError) as raised:
        graph.model_copy(update=mutation(graph))
    assert expected_code in _err_codes(raised.value), (
        f"wanted {expected_code}, got {_err_codes(raised.value)}"
    )


def test_cycle_fails_closed(graph_by_id) -> None:
    graph = graph_by_id["eligibility"]
    nodes = tuple(
        node.model_copy(update={"depends_on": ("finalize_eligibility_criteria",)})
        if node.node_id == "draft_eligibility_criteria"
        else node
        for node in graph.nodes
    )
    edges = graph.edges + (
        Edge(
            source_node_id="finalize_eligibility_criteria",
            target_node_id="draft_eligibility_criteria",
            kind=EdgeKind.DATA,
        ),
    )
    with pytest.raises(ValidationError) as raised:
        graph.model_copy(update={"nodes": nodes, "edges": edges})
    assert "CC_CYCLE" in _err_codes(raised.value)


def test_minimal_three_node_cycle_behind_parallel_pair_fails_closed() -> None:
    """Regression (Worker 01 repair4 defect 1): a cycle (b_node->c_node->
    b_node) hidden behind a DATA+GATE parallel pair (a_node->b_node twice)
    must fail closed at construction with CC_CYCLE — the old per-edge Kahn
    over-decremented b_node and masked the cycle."""
    nodes = (
        NodeContract(
            node_id="a_node",
            kind=NodeKind.CHECK,
            owner=OwnerRole.SYSTEM,
            gate=GateKind.D1_DESIGN_CONSISTENCY,
            inputs=(),
            output_schema="s1",
            depends_on=(),
            side_effect_kind=SideEffectKind.NONE,
        ),
        NodeContract(
            node_id="b_node",
            kind=NodeKind.CHECK,
            owner=OwnerRole.SYSTEM,
            gate=GateKind.D1_DESIGN_CONSISTENCY,
            inputs=(),
            output_schema="s1",
            depends_on=("a_node", "c_node"),
            side_effect_kind=SideEffectKind.NONE,
        ),
        NodeContract(
            node_id="c_node",
            kind=NodeKind.CHECK,
            owner=OwnerRole.SYSTEM,
            gate=GateKind.D1_DESIGN_CONSISTENCY,
            inputs=(),
            output_schema="s1",
            depends_on=("b_node",),
            side_effect_kind=SideEffectKind.NONE,
        ),
    )
    edges = (
        Edge(source_node_id="a_node", target_node_id="b_node", kind=EdgeKind.DATA),
        Edge(source_node_id="a_node", target_node_id="b_node", kind=EdgeKind.GATE),
        Edge(source_node_id="b_node", target_node_id="c_node", kind=EdgeKind.DATA),
        Edge(source_node_id="c_node", target_node_id="b_node", kind=EdgeKind.DATA),
    )
    injections = (
        InjectionPoint(
            injection_kind=InjectionKind.KILL_BEFORE,
            target_node_id="a_node",
            logical_key="probe.kill_before",
            expectation="probe",
        ),
        InjectionPoint(
            injection_kind=InjectionKind.KILL_AFTER,
            target_node_id="a_node",
            logical_key="probe.kill_after",
            expectation="probe",
        ),
        InjectionPoint(
            injection_kind=InjectionKind.DUPLICATE_RESUME,
            target_node_id="a_node",
            logical_key="probe.duplicate",
            expectation="probe",
        ),
        InjectionPoint(
            injection_kind=InjectionKind.CONCURRENT_DECISION,
            target_node_id="a_node",
            logical_key="probe.concurrent",
            expectation="probe",
        ),
        InjectionPoint(
            injection_kind=InjectionKind.OLD_GRAPH_MIGRATION,
            logical_key="probe.migration",
            old_graph_version="probe_graph_v0",
            expectation="probe",
        ),
    )
    with pytest.raises(ValidationError) as raised:
        CaseGraph(
            case_id=CaseId.SAMPLE_SIZE,
            project_id=PROJECT_ID,
            branch_id=BRANCH_ID,
            graph_version="probe_graph_v1",
            description="probe minimal three-node cycle behind a parallel pair",
            schemas=(SchemaDecl(name="s1", description="probe schema"),),
            root_inputs=(),
            nodes=nodes,
            edges=edges,
            injections=injections,
        )
    assert "CC_CYCLE" in _err_codes(raised.value)


def test_eligibility_back_edge_to_lock_fails_closed_as_cycle(graph_by_id) -> None:
    """Regression (Worker 01 repair4 defect 1): adding
    finalize_eligibility_criteria -> eligibility_decision_lock (DATA) with
    the lock's depends_on extended to match creates the cycle
    lock->finalize->lock; construction must fail closed with CC_CYCLE even
    though edges and depends_on agree with each other."""
    graph = graph_by_id["eligibility"]
    nodes = tuple(
        node.model_copy(
            update={
                "depends_on": node.depends_on
                + ("finalize_eligibility_criteria",)
            }
        )
        if node.node_id == "eligibility_decision_lock"
        else node
        for node in graph.nodes
    )
    edges = graph.edges + (
        Edge(
            source_node_id="finalize_eligibility_criteria",
            target_node_id="eligibility_decision_lock",
            kind=EdgeKind.DATA,
        ),
    )
    with pytest.raises(ValidationError) as raised:
        graph.model_copy(update={"nodes": nodes, "edges": edges})
    assert "CC_CYCLE" in _err_codes(raised.value)


def test_topological_order_fails_closed_on_bypassed_cyclic_graph(graph_by_id) -> None:
    """Regression (Worker 01 repair4 defect 2): a CaseGraph instance that
    bypassed construction validation (model_construct) yet contains a cycle
    must make topological_order raise CC_CYCLE — it never returns a partial
    order."""
    graph = graph_by_id["sample_size"]
    cyclic_edges = graph.edges + (
        Edge(
            source_node_id="finalize_sample_size",
            target_node_id="sample_size_decision_lock",
            kind=EdgeKind.DATA,
        ),
    )
    bypassed = CaseGraph.model_construct(
        case_id=graph.case_id,
        project_id=graph.project_id,
        branch_id=graph.branch_id,
        schema_version=graph.schema_version,
        graph_version=graph.graph_version,
        description=graph.description,
        schemas=graph.schemas,
        root_inputs=graph.root_inputs,
        nodes=graph.nodes,
        edges=cyclic_edges,
        injections=graph.injections,
    )
    assert isinstance(bypassed, CaseGraph)
    assert len(bypassed.edges) == len(graph.edges) + 1  # bypass truly differs
    with pytest.raises(CaseContractError) as raised:
        bypassed.topological_order()
    assert raised.value.code == "CC_CYCLE"
    # positive control: the same edges minus the back-edge order cleanly
    assert graph.topological_order()[-1] == "finalize_sample_size"


@pytest.mark.parametrize(
    "node_kwargs, expected_code",
    [
        (
            {"side_effect_kind": SideEffectKind.ARTIFACT_CREATE},
            "CC_SIDE_EFFECT_KEY_MISSING",
        ),
        (
            {"side_effect_key_template": "x.{id}"},
            "CC_SIDE_EFFECT_KEY_UNEXPECTED",
        ),
        (
            {"failure_policy": FailurePolicy.FAIL_CLOSED, "allowed_attempts": 3},
            "CC_FAILURE_POLICY",
        ),
        (
            {"failure_policy": FailurePolicy.BOUNDED_RETRY, "allowed_attempts": 1},
            "CC_FAILURE_POLICY",
        ),
        (
            {"inputs": ("schema_a", "schema_a")},
            "CC_INPUT_DUPLICATE",
        ),
        (
            {"depends_on": ("dep_a", "dep_a")},
            "CC_DEPENDENCY_DUPLICATE",
        ),
    ],
)
def test_node_contract_violations_fail_closed(node_kwargs, expected_code) -> None:
    kwargs = {
        "node_id": "probe_node",
        "kind": NodeKind.CHECK,
        "owner": OwnerRole.SYSTEM,
        "gate": GateKind.D1_DESIGN_CONSISTENCY,
        "inputs": (),
        "output_schema": "schema_a",
        "depends_on": (),
        "side_effect_kind": SideEffectKind.NONE,
        "failure_policy": FailurePolicy.FAIL_CLOSED,
        "allowed_attempts": 1,
    }
    kwargs.update(node_kwargs)
    with pytest.raises(ValidationError) as raised:
        NodeContract(**kwargs)
    assert expected_code in _err_codes(raised.value)


@pytest.mark.parametrize(
    "injection_kwargs, expected_code",
    [
        (
            {"injection_kind": InjectionKind.OLD_GRAPH_MIGRATION},
            "CC_INJECTION_MIGRATION",
        ),
        (
            {
                "injection_kind": InjectionKind.OLD_GRAPH_MIGRATION,
                "old_graph_version": "v0",
                "target_node_id": "probe_node",
            },
            "CC_INJECTION_MIGRATION",
        ),
        (
            {
                "injection_kind": InjectionKind.KILL_BEFORE,
                "old_graph_version": "v0",
                "target_node_id": "probe_node",
            },
            "CC_INJECTION_MIGRATION",
        ),
        (
            {"injection_kind": InjectionKind.KILL_BEFORE, "target_node_id": None},
            "CC_INJECTION_TARGET",
        ),
    ],
)
def test_injection_point_contract_violations_fail_closed(
    injection_kwargs, expected_code
) -> None:
    kwargs = {
        "injection_kind": InjectionKind.KILL_BEFORE,
        "target_node_id": "probe_node",
        "logical_key": "probe.key",
        "expectation": "probe",
    }
    kwargs.update(injection_kwargs)
    with pytest.raises(ValidationError) as raised:
        InjectionPoint(**kwargs)
    assert expected_code in _err_codes(raised.value)


def test_binding_mismatch_fails_closed(graph_by_id) -> None:
    graph = graph_by_id["eligibility"]
    with pytest.raises(CaseContractError) as raised:
        assert_case_graph_binding(graph, "some-other-project", BRANCH_ID)
    assert raised.value.code == "CC_BINDING_MISMATCH"


def test_unknown_node_lookup_fails_closed(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    with pytest.raises(CaseContractError) as raised:
        graph.node("ghost_node")
    assert raised.value.code == "CC_NODE_UNKNOWN"
    with pytest.raises(CaseContractError) as raised:
        graph.node_dependencies("ghost_node")
    assert raised.value.code == "CC_NODE_UNKNOWN"


def test_old_graph_with_a_missing_link_fails_closed(graph_by_id) -> None:
    """An old-version graph (missing assumption→calculation link) cannot be
    constructed: migration never silently completes a missing link."""
    graph = graph_by_id["sample_size"]
    dropped = tuple(
        edge
        for edge in graph.edges
        if not (
            edge.source_node_id == "define_statistical_assumptions"
            and edge.target_node_id == "derive_sample_size"
        )
    )
    with pytest.raises(ValidationError) as raised:
        graph.model_copy(update={"edges": dropped, "graph_version": "sample_size_graph_v0"})
    assert "CC_EDGE_UNMATCHED_DEPENDENCY" in _err_codes(raised.value)


# ---------------------------------------------------------------------------
# Deep immutability
# ---------------------------------------------------------------------------


def test_contract_models_are_frozen(graph_by_id) -> None:
    graph = graph_by_id["eligibility"]
    with pytest.raises(ValidationError):
        graph.description = "mutated"
    with pytest.raises(ValidationError):
        graph.nodes[0].node_id = "mutated"
    assert graph.model_copy() is graph  # identical copy is the same object
    changed = graph.model_copy(update={"graph_version": "eligibility_graph_v9"})
    assert changed is not graph
    assert changed.graph_version == "eligibility_graph_v9"
    assert graph.graph_version == "eligibility_graph_v1"


def test_frozen_json_containers_reject_mutation() -> None:
    mapping = FrozenJsonDict(a=1, nested=FrozenJsonList([1, 2]))
    with pytest.raises(TypeError):
        mapping["a"] = 2
    with pytest.raises(TypeError):
        mapping["b"] = 3
    with pytest.raises(TypeError):
        mapping.pop("a")
    with pytest.raises(TypeError):
        mapping.clear()
    sequence = FrozenJsonList([1, 2])
    with pytest.raises(TypeError):
        sequence.append(3)
    with pytest.raises(TypeError):
        sequence[0] = 9


def test_assert_deep_immutable_accepts_frozen_and_rejects_mutable() -> None:
    frozen = freeze_input({"a": [1, {"b": (2, 3)}], "c": "text"})
    assert isinstance(frozen, FrozenJsonDict)
    assert isinstance(frozen["a"], FrozenJsonList)
    assert isinstance(frozen["a"][1], FrozenJsonDict)
    assert_deep_immutable(frozen)  # must not raise

    with pytest.raises(CaseContractError) as raised:
        assert_deep_immutable({"a": 1})
    assert raised.value.code == "CC_INPUT_MUTABLE"
    with pytest.raises(CaseContractError) as raised:
        assert_deep_immutable([1])
    assert raised.value.code == "CC_INPUT_MUTABLE"
    with pytest.raises(CaseContractError) as raised:
        assert_deep_immutable({1, 2})
    assert raised.value.code == "CC_INPUT_MUTABLE"
    with pytest.raises(CaseContractError) as raised:
        freeze_input({1, 2})
    assert raised.value.code == "CC_INPUT_NOT_JSONABLE"


def test_graph_read_helpers_return_immutable_views(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    order = graph.topological_order()
    with pytest.raises(TypeError):
        order[0] = "mutated"  # tuples are immutable
    deps = graph.node_dependencies("sample_size_decision_lock")
    assert isinstance(deps, tuple)
    payload = graph.material_payload()
    # canonical JSON round-trip proves the payload is plain JSON-able
    assert canonical_json(payload) == canonical_json(dict(payload))


# ---------------------------------------------------------------------------
# Deterministic fakes: idempotent logical keys, replay, isolation
# ---------------------------------------------------------------------------


def test_fake_clock_is_deterministic_and_rejects_invalid_inputs() -> None:
    first = FakeClock(epoch=DEFAULT_EPOCH, step=DEFAULT_STEP)
    second = FakeClock(epoch=DEFAULT_EPOCH, step=DEFAULT_STEP)
    assert [first.now() for _ in range(4)] == [second.now() for _ in range(4)]
    assert first.now().tzinfo is not None
    with pytest.raises(ValueError):
        FakeClock(epoch=DEFAULT_EPOCH.replace(tzinfo=None))
    with pytest.raises(ValueError):
        FakeClock(step=DEFAULT_STEP - DEFAULT_STEP)


def test_fake_id_factory_is_stable_and_isolates_project_branch() -> None:
    base = FakeIdFactory("poc-project", "poc-branch")
    assert base.id_for("artifact", "logical-key") == base.id_for("artifact", "logical-key")
    assert base.artifact_id("logical-key") == base.id_for("artifact", "logical-key")
    assert base.decision_id("logical-key") == base.id_for("decision", "logical-key")
    assert base.reservation_id("logical-key") == base.id_for("reservation", "logical-key")
    other_branch = FakeIdFactory("poc-project", "other-branch")
    assert other_branch.id_for("artifact", "logical-key") != base.id_for(
        "artifact", "logical-key"
    )
    other_project = FakeIdFactory("other-project", "poc-branch")
    assert other_project.id_for("artifact", "logical-key") != base.id_for(
        "artifact", "logical-key"
    )


def _seed_calculation_artifact(
    runtime: FakeRuntime, graph: CaseGraph, logical_key: str = "sample_size.calc.1"
):
    """Deterministic helper: store a calculation artifact for the
    sample-size derive node (schema contract enforced by the store)."""
    return runtime.artifacts.put(
        graph,
        node_id="derive_sample_size",
        logical_key=logical_key,
        schema_name="sample_size_calculation",
        payload=freeze_input(
            {
                "formula": "two_sample_prop",
                "n_per_arm": 100,
                "assumption_snapshot": "labeled-synthetic-v1",
            }
        ),
    )


def test_artifact_store_is_idempotent_by_logical_key(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    first = _seed_calculation_artifact(runtime, graph)
    second = _seed_calculation_artifact(runtime, graph)  # duplicate resume
    assert first is second
    assert runtime.artifacts.count() == 1  # no second lineage
    assert first.artifact_id == runtime.ids.artifact_id("sample_size.calc.1")
    assert first.node_id == "derive_sample_size"
    assert first.schema_name == "sample_size_calculation"
    assert len(first.payload_sha256) == 64


def test_artifact_store_fails_closed_on_conflicts(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    _seed_calculation_artifact(runtime, graph)
    with pytest.raises(FakeContractError) as raised:
        _seed_calculation_artifact(runtime, graph, logical_key="sample_size.calc.2")
        # different logical key is fine; now conflict on the SAME key:
        runtime.artifacts.put(
            graph,
            node_id="derive_sample_size",
            logical_key="sample_size.calc.1",
            schema_name="sample_size_calculation",
            payload=freeze_input({"formula": "different"}),
        )
    assert raised.value.code == "FK_IDEMPOTENCY_CONFLICT"


def test_artifact_store_validates_node_schema_and_immutability(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    with pytest.raises(CaseContractError) as raised:
        runtime.artifacts.put(
            graph,
            node_id="ghost_node",
            logical_key="sample_size.calc.1",
            schema_name="sample_size_calculation",
            payload=freeze_input({"a": 1}),
        )
    assert raised.value.code == "CC_NODE_UNKNOWN"
    with pytest.raises(CaseContractError) as raised:
        runtime.artifacts.put(
            graph,
            node_id="derive_sample_size",
            logical_key="sample_size.calc.1",
            schema_name="hypothesis_and_targets",
            payload=freeze_input({"a": 1}),
        )
    assert raised.value.code == "CC_SCHEMA_MISMATCH"
    with pytest.raises(CaseContractError) as raised:
        runtime.artifacts.put(
            graph,
            node_id="derive_sample_size",
            logical_key="sample_size.calc.1",
            schema_name="sample_size_calculation",
            payload={"mutable": [1]},  # not frozen -> deep-immutability violation
        )
    assert raised.value.code == "CC_INPUT_MUTABLE"


def test_stored_artifact_payload_is_deep_immutable(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    ref = _seed_calculation_artifact(runtime, graph)
    assert isinstance(ref.payload, FrozenJsonDict)
    with pytest.raises(TypeError):
        ref.payload["formula"] = "mutated"
    with pytest.raises(ValidationError):
        ref.artifact_id = "mutated"  # frozen model


def test_direct_fake_record_construction_rejects_mutable_payloads() -> None:
    """Regression (Worker 01 repair4 defect 3): constructing ArtifactRef /
    DecisionRecord *directly* with a mutable nested payload/value must fail
    closed with CC_INPUT_MUTABLE (no silent freeze at model construction);
    the freeze_input equivalents construct and stay deep-locked on read."""
    artifact_base = {
        "artifact_id": "probe_artifact_1",
        "logical_key": "probe.logical.1",
        "node_id": "derive_sample_size",
        "schema_name": "sample_size_calculation",
        "project_id": PROJECT_ID,
        "branch_id": BRANCH_ID,
        "payload_sha256": "0" * 64,
        "created_at": DEFAULT_EPOCH,
    }
    with pytest.raises(ValidationError) as raised:
        ArtifactRef(**artifact_base, payload={"x": [1]})
    assert "CC_INPUT_MUTABLE" in _err_codes(raised.value)
    with pytest.raises(ValidationError) as raised:
        ArtifactRef(**artifact_base, payload=[1, {"y": 2}])
    assert "CC_INPUT_MUTABLE" in _err_codes(raised.value)

    frozen_ref = ArtifactRef(**artifact_base, payload=freeze_input({"x": [1]}))
    assert isinstance(frozen_ref.payload, FrozenJsonDict)
    assert isinstance(frozen_ref.payload["x"], FrozenJsonList)
    with pytest.raises(TypeError):
        frozen_ref.payload["x"].append(2)

    decision_base = {
        "decision_id": "probe_decision_1",
        "decision_key": "probe.decision.1",
        "project_id": PROJECT_ID,
        "branch_id": BRANCH_ID,
        "snapshot_sha256": "0" * 64,
        "reason": "probe",
        "actor": "user-a",
        "decided_at": DEFAULT_EPOCH,
    }
    with pytest.raises(ValidationError) as raised:
        DecisionRecord(**decision_base, value={"x": [1]})
    assert "CC_INPUT_MUTABLE" in _err_codes(raised.value)

    frozen_record = DecisionRecord(**decision_base, value=freeze_input({"x": [1]}))
    assert isinstance(frozen_record.value, FrozenJsonDict)
    assert isinstance(frozen_record.value["x"], FrozenJsonList)
    with pytest.raises(TypeError):
        frozen_record.value["x"].append(2)


def test_decision_board_concurrent_claim_fails_closed(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    key = "sample_size.lock.1"
    claim = runtime.decisions.claim(graph, decision_key=key, actor="user-a")
    assert claim.decision_key == key
    assert claim.actor == "user-a"
    # same actor re-claim is idempotent
    assert runtime.decisions.claim(graph, decision_key=key, actor="user-a") is claim
    # a second actor fails closed
    with pytest.raises(FakeContractError) as raised:
        runtime.decisions.claim(graph, decision_key=key, actor="user-b")
    assert raised.value.code == "FK_CONCURRENT_DECISION"

    value = freeze_input({"approved_n_per_arm": 100, "assumption_snapshot": "labeled-synthetic-v1"})
    recorded = runtime.decisions.record(
        graph, decision_key=key, value=value, reason="approved", actor="user-a"
    )
    assert runtime.decisions.get(key) is recorded
    assert len(runtime.decisions.iter_decisions()) == 1
    # duplicate resume returns the existing decision (no double apply)
    again = runtime.decisions.record(
        graph, decision_key=key, value=value, reason="approved", actor="user-a"
    )
    assert again is recorded
    assert len(runtime.decisions.iter_decisions()) == 1
    # conflicting re-record fails closed
    with pytest.raises(FakeContractError) as raised:
        runtime.decisions.record(
            graph,
            decision_key=key,
            value=freeze_input({"approved_n_per_arm": 999}),
            reason="approved",
            actor="user-a",
        )
    assert raised.value.code == "FK_IDEMPOTENCY_CONFLICT"
    # claiming an already-recorded key fails closed
    with pytest.raises(FakeContractError) as raised:
        runtime.decisions.claim(graph, decision_key=key, actor="user-c")
    assert raised.value.code == "FK_IDEMPOTENCY_CONFLICT"


def test_decision_board_recording_over_foreign_claim_fails_closed(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    key = "sample_size.lock.2"
    runtime.decisions.claim(graph, decision_key=key, actor="user-a")
    with pytest.raises(FakeContractError) as raised:
        runtime.decisions.record(
            graph, decision_key=key, value=freeze_input({"n": 1}), reason="r", actor="user-b"
        )
    assert raised.value.code == "FK_CONCURRENT_DECISION"


def test_reservation_ledger_duplicate_resume_and_terminal_semantics(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    first = runtime.reservations.reserve(
        graph,
        node_id="derive_sample_size",
        logical_call_id="sample_size.calc.call",
        idempotency_key="ik-1",
        input_sha256="0" * 64,
    )
    # duplicate resume: same logical key, no second attempt
    second = runtime.reservations.reserve(
        graph,
        node_id="derive_sample_size",
        logical_call_id="sample_size.calc.call",
        idempotency_key="ik-1",
        input_sha256="0" * 64,
    )
    assert second is first
    assert runtime.reservations.count() == 1
    assert first.attempt == 1
    assert first.status is FakeReservationStatus.RESERVED

    running = runtime.reservations.start(first.reservation_id)
    assert running.status is FakeReservationStatus.RUNNING
    completed = runtime.reservations.complete(running.reservation_id, "a" * 64)
    assert completed.status is FakeReservationStatus.COMPLETED
    assert completed.output_sha256 == "a" * 64
    # resume after completion returns the completed lineage: no re-execution
    resumed = runtime.reservations.resume(
        logical_call_id="sample_size.calc.call", idempotency_key="ik-1"
    )
    assert resumed is completed
    # failed reservations require explicit owner repair
    failed = runtime.reservations.reserve(
        graph,
        node_id="statistical_review",
        logical_call_id="sample_size.qc.call",
        idempotency_key="ik-1",
        input_sha256="b" * 64,
    )
    failed = runtime.reservations.start(failed.reservation_id)
    failed = runtime.reservations.fail(failed.reservation_id, "QC_REJECTED")
    assert failed.status is FakeReservationStatus.FAILED
    with pytest.raises(FakeContractError) as raised:
        runtime.reservations.resume(
            logical_call_id="sample_size.qc.call", idempotency_key="ik-1"
        )
    assert raised.value.code == "FK_TERMINAL_FAILED"
    # unknown outcome is never auto-redispatched
    unknown = runtime.reservations.reserve(
        graph,
        node_id="finalize_sample_size",
        logical_call_id="sample_size.finalize.call",
        idempotency_key="ik-1",
        input_sha256="c" * 64,
    )
    unknown = runtime.reservations.start(unknown.reservation_id)
    unknown = runtime.reservations.mark_unknown_outcome(unknown.reservation_id, "CRASH")
    assert unknown.status is FakeReservationStatus.UNKNOWN_OUTCOME
    with pytest.raises(FakeContractError) as raised:
        runtime.reservations.resume(
            logical_call_id="sample_size.finalize.call", idempotency_key="ik-1"
        )
    assert raised.value.code == "FK_UNKNOWN_OUTCOME"


def test_reservation_terminal_state_contract_fails_closed(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    reservation = runtime.reservations.reserve(
        graph,
        node_id="derive_sample_size",
        logical_call_id="sample_size.calc.call",
        idempotency_key="ik-2",
        input_sha256="0" * 64,
    )
    # RESERVED -> COMPLETED is not a legal transition
    with pytest.raises(FakeContractError) as raised:
        runtime.reservations.complete(reservation.reservation_id, "a" * 64)
    assert raised.value.code == "FK_INVALID_TRANSITION"

    running = runtime.reservations.start(reservation.reservation_id)
    # a malformed output hash cannot enter the ledger (Sha256 validation)
    with pytest.raises(ValidationError):
        runtime.reservations.complete(running.reservation_id, "not-a-hash")
    # terminal state combos are rejected by the fully re-validated rebuild
    with pytest.raises(ValidationError) as raised:
        running.model_copy(
            update={
                "status": FakeReservationStatus.COMPLETED,
                "terminal_state": "completed",
                "output_sha256": "a" * 64,
                "error_code": "CONTRADICTION",
            }
        )
    assert "FK_TERMINAL_FIELDS" in _err_codes(raised.value)
    with pytest.raises(ValidationError) as raised:
        running.model_copy(
            update={
                "status": FakeReservationStatus.COMPLETED,
                "terminal_state": "wrong_terminal",
                "output_sha256": "a" * 64,
            }
        )
    assert "FK_TERMINAL_STATE" in _err_codes(raised.value)
    with pytest.raises(ValidationError) as raised:
        running.model_copy(update={"terminal_state": "completed"})
    assert "FK_TERMINAL_STATE" in _err_codes(raised.value)
    # terminal reservations are final
    completed = runtime.reservations.complete(running.reservation_id, "e" * 64)
    assert completed.status is FakeReservationStatus.COMPLETED
    with pytest.raises(FakeContractError) as raised:
        runtime.reservations.fail(completed.reservation_id, "LATE_FAILURE")
    assert raised.value.code == "FK_INVALID_TRANSITION"


def test_fakes_fail_closed_on_unbound_graph(graph_by_id) -> None:
    graph = graph_by_id["eligibility"]  # bound to PROJECT_ID/BRANCH_ID
    foreign = FakeRuntime("other-project", "other-branch")
    with pytest.raises(CaseContractError) as raised:
        foreign.artifacts.put(
            graph,
            node_id="draft_eligibility_criteria",
            logical_key="eligibility.draft.1",
            schema_name="drafted_criteria",
            payload=freeze_input({"draft": "x"}),
        )
    assert raised.value.code == "CC_BINDING_MISMATCH"
    with pytest.raises(CaseContractError) as raised:
        foreign.decisions.claim(
            graph, decision_key="eligibility.lock.1", actor="user-a"
        )
    assert raised.value.code == "CC_BINDING_MISMATCH"
    with pytest.raises(CaseContractError) as raised:
        foreign.reservations.reserve(
            graph,
            node_id="draft_eligibility_criteria",
            logical_call_id="eligibility.draft.call",
            idempotency_key="ik-1",
            input_sha256="0" * 64,
        )
    assert raised.value.code == "CC_BINDING_MISMATCH"


def test_project_branch_isolation_between_runtimes(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime_a = FakeRuntime(PROJECT_ID, BRANCH_ID)
    runtime_b = FakeRuntime("isolated-project", "isolated-branch")
    # The sample-size graph is bound to the shared project/branch; rebind a
    # copy to the isolated runtime's identity (construction re-validates).
    isolated_graph = graph.model_copy(
        update={"project_id": "isolated-project", "branch_id": "isolated-branch"}
    )
    ref_a = _seed_calculation_artifact(runtime_a, graph)
    ref_b = _seed_calculation_artifact(runtime_b, isolated_graph)
    assert ref_a.artifact_id != ref_b.artifact_id
    assert ref_a.project_id != ref_b.project_id
    assert runtime_a.artifacts.get("sample_size.calc.1") is ref_a
    assert runtime_b.artifacts.get("sample_size.calc.1") is ref_b
    assert runtime_a.artifacts.get("sample_size.calc.1") is not ref_b

    decision_a = runtime_a.decisions.record(
        graph,
        decision_key="sample_size.lock.1",
        value=freeze_input({"n": 100}),
        reason="approved",
        actor="user-a",
    )
    decision_b = runtime_b.decisions.record(
        isolated_graph,
        decision_key="sample_size.lock.1",
        value=freeze_input({"n": 100}),
        reason="approved",
        actor="user-a",
    )
    assert decision_a.decision_id != decision_b.decision_id
    assert decision_a.snapshot_sha256 == decision_b.snapshot_sha256


def test_deterministic_replay_across_equal_runtimes(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    first = FakeRuntime(PROJECT_ID, BRANCH_ID)
    second = FakeRuntime(PROJECT_ID, BRANCH_ID)
    for runtime in (first, second):
        _seed_calculation_artifact(runtime, graph, logical_key="sample_size.calc.replay")
        runtime.decisions.claim(
            graph, decision_key="sample_size.lock.replay", actor="user-a"
        )
        runtime.decisions.record(
            graph,
            decision_key="sample_size.lock.replay",
            value=freeze_input({"approved_n_per_arm": 100}),
            reason="approved",
            actor="user-a",
        )
        runtime.reservations.reserve(
            graph,
            node_id="derive_sample_size",
            logical_call_id="sample_size.calc.replay.call",
            idempotency_key="ik-1",
            input_sha256="0" * 64,
        )
    a_ref = first.artifacts.get("sample_size.calc.replay")
    b_ref = second.artifacts.get("sample_size.calc.replay")
    assert a_ref.artifact_id == b_ref.artifact_id
    assert a_ref.created_at == b_ref.created_at
    assert (
        first.decisions.get("sample_size.lock.replay").decision_id
        == second.decisions.get("sample_size.lock.replay").decision_id
    )
    assert (
        first.reservations.get("sample_size.calc.replay.call", "ik-1").reservation_id
        == second.reservations.get("sample_size.calc.replay.call", "ik-1").reservation_id
    )


def test_fake_records_are_deep_immutable(graph_by_id) -> None:
    graph = graph_by_id["sample_size"]
    runtime = FakeRuntime(PROJECT_ID, BRANCH_ID)
    ref = _seed_calculation_artifact(runtime, graph)
    with pytest.raises(ValidationError):
        ref.created_at = DEFAULT_EPOCH
    decision = runtime.decisions.record(
        graph,
        decision_key="sample_size.lock.1",
        value=freeze_input({"n": 1, "nested": {"a": [1]}}),
        reason="approved",
        actor="user-a",
    )
    assert isinstance(decision.value, FrozenJsonDict)
    with pytest.raises(TypeError):
        decision.value["n"] = 2
    with pytest.raises(ValidationError):
        decision.decision_id = "mutated"


# ---------------------------------------------------------------------------
# No product/scheduler/provider/storage surface
# ---------------------------------------------------------------------------


def test_importing_orchestrator_tree_touches_no_product_or_runtime_surface() -> None:
    """Fresh subprocess: importing the orchestrator tree must not import any
    product (``app``/``services``/``packages``), scheduler (``langgraph``),
    provider, storage or data-layer module, and must not touch the sibling
    PoC storage/word_receipt packages."""
    script = r"""
import sys
before = set(sys.modules)
import pocs.protocol_v3.orchestrator
import pocs.protocol_v3.orchestrator.fakes
import pocs.protocol_v3.orchestrator.cases
import pocs.protocol_v3.orchestrator.cases.eligibility
import pocs.protocol_v3.orchestrator.cases.objective_estimand_endpoint
import pocs.protocol_v3.orchestrator.cases.sample_size
added = sorted(set(sys.modules) - before)
print("\n".join(added))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        timeout=120,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                [os.getcwd(), "services/api", "packages", os.environ.get("PYTHONPATH", "")]
            ),
        },
    )
    assert result.returncode == 0, result.stderr
    added_modules = {line for line in result.stdout.splitlines() if line.strip()}
    roots = {module.split(".")[0] for module in added_modules}
    assert roots & FORBIDDEN_IMPORT_ROOTS == set(), (
        f"orchestrator imports forbidden roots: {sorted(roots & FORBIDDEN_IMPORT_ROOTS)}"
    )
    for prefix in FORBIDDEN_IMPORT_PREFIXES:
        assert not any(module.startswith(prefix) for module in added_modules), (
            f"orchestrator imports forbidden module prefix {prefix}"
        )
    # sanity: the orchestrator tree itself and its dependency surface loaded
    assert "pocs.protocol_v3.orchestrator" in added_modules
    assert "pocs.protocol_v3.orchestrator.cases.sample_size" in added_modules
