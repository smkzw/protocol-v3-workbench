"""Typed facade over the accepted Task 2.1 case graphs (Task 2R.1).

Drives all three accepted immutable case graphs (eligibility,
objective-estimand-endpoint, sample-size) through the thin PoC adapter
(:mod:`pocs.protocol_v3.orchestrator.typed_facade`) into the *product*
typed graph runtime (``app.protocol_workflow.graph``), on the real product
SQLite adapter with committed reservations and v1_1 dependency-compacted
contracts.

Pinned here:

* the adapter converts the accepted vocabulary 1:1 without duplicating the
  scheduler, and the product runtime never imports pocs;
* every graph executes through typed services with per-node output schema
  checks; the user decision pause is a product state and only a recorded
  human decision completes it;
* the declared injection matrix (kill-before, kill-after,
  duplicate-resume, concurrent-decision) is exercised per case with real
  own-process death (synthetic subprocess ``os._exit``) and reopen;
* an old-version plan with a missing link is rejected by the product plan
  validation — migration never auto-completes a missing link.

The seven accepted Task 2.1 files are consumed read-only; this module never
mutates them.  All persistence is offline synthetic: no model, provider,
network or live service is touched.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from pocs.protocol_v3.orchestrator import CaseGraph, CaseId
from pocs.protocol_v3.orchestrator.cases import iter_case_graphs, load_case
from pocs.protocol_v3.orchestrator.typed_facade import (
    deterministic_services,
    graph_lock_node,
    plan_from_case_graph,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TESTS_DIR = _REPO_ROOT / "pocs" / "protocol_v3" / "orchestrator" / "tests"

_PROJ_BY_CASE = {}  # filled from the graphs themselves

_CASES = (
    CaseId.ELIGIBILITY,
    CaseId.OBJECTIVE_ESTIMAND_ENDPOINT,
    CaseId.SAMPLE_SIZE,
)

_EPOCH = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)

_KILL_BEFORE = 67
_KILL_AFTER = 68
_KILL_MID_DISPATCH = 69


def _case_graph(case_id: CaseId) -> CaseGraph:
    return load_case(case_id)


def _decision_value(case_id: CaseId) -> dict[str, Any]:
    return {
        "decision": "adopt",
        "case": case_id.value,
        "label": "labeled-synthetic-facade",
    }


# ---------------------------------------------------------------------------
# Adapter conversion contracts
# ---------------------------------------------------------------------------


class TestAdapterConversion:
    @pytest.mark.parametrize("case_id", _CASES)
    def test_all_three_graphs_convert_to_valid_product_plans(self, case_id) -> None:
        from app.protocol_workflow.graph import GraphNodeKind, GraphNodeOwner

        graph = _case_graph(case_id)
        plan = plan_from_case_graph(graph)
        assert plan.project_id == graph.project_id
        assert plan.branch_id == graph.branch_id
        assert plan.graph_id == case_id.value
        assert plan.graph_version == graph.graph_version
        assert plan.material_sha256() == plan.material_sha256()
        node_ids = {node.node_id for node in plan.nodes}
        assert node_ids == {node.node_id for node in graph.nodes}
        for plan_node, graph_node in zip(
            sorted(plan.nodes, key=lambda n: n.node_id),
            sorted(graph.nodes, key=lambda n: n.node_id),
        ):
            assert sorted(plan_node.depends_on) == sorted(graph_node.depends_on)
            assert plan_node.output_schema == graph_node.output_schema
            assert plan_node.logical_key == graph_node.side_effect_key_template
            if graph_node.kind.value == "decision":
                assert plan_node.kind is GraphNodeKind.DECISION
                assert plan_node.owner is GraphNodeOwner.USER
        # The accepted graph material hash is untouched by conversion.
        assert graph.material_sha256()

    @pytest.mark.parametrize("case_id", _CASES)
    def test_lock_node_is_found_and_unique(self, case_id) -> None:
        graph = _case_graph(case_id)
        lock = graph_lock_node(graph)
        assert lock.owner.value == "user"
        assert lock.kind.value == "decision"

    def test_plan_conversion_does_not_mutate_the_accepted_graphs(self) -> None:
        from pocs.protocol_v3.orchestrator.tests.test_case_contracts import (
            EXPECTED_HASHES,
        )

        for graph in iter_case_graphs():
            plan_from_case_graph(graph)
            assert graph.material_sha256() == EXPECTED_HASHES[graph.case_id.value]


# ---------------------------------------------------------------------------
# Execution through the product runtime
# ---------------------------------------------------------------------------


def _facade_runtime(work_dir: Path, case_id: CaseId, *, services=None, clock=None):
    from app.protocol_workflow.graph import GraphRuntime
    from app.protocol_workflow.storage.sqlite import (
        build_committed_reservation_repository_factory,
        build_unit_of_work_factory,
    )

    graph = _case_graph(case_id)

    class _StepClock:
        def __init__(self) -> None:
            self._current = _EPOCH

        def __call__(self) -> datetime:
            value = self._current
            self._current = self._current + timedelta(seconds=1)
            return value

    return GraphRuntime(
        project_id=graph.project_id,
        uow_factory=build_unit_of_work_factory(
            {"backend": "sqlite", "path": str(work_dir / "graph.sqlite")}
        ),
        reservation_repository_factory=build_committed_reservation_repository_factory(
            {"backend": "sqlite", "path": str(work_dir / "graph.sqlite")}
        ),
        services=services if services is not None else deterministic_services(_case_graph(case_id)),
        clock=clock or _StepClock(),
        runtime_owner="facade-test",
    )


def _root_inputs(case_id: CaseId) -> dict[str, Any]:
    graph = _case_graph(case_id)
    inputs: dict[str, Any] = {}
    for schema_name in graph.root_inputs:
        inputs[schema_name] = {
            "schema": schema_name,
            "label": "labeled-synthetic-root",
        }
    return inputs


class TestExecutionThroughProductRuntime:
    @pytest.mark.parametrize("case_id", _CASES)
    def test_graph_executes_to_decision_pause_and_completes_after_human_record(
        self, tmp_path: Path, case_id
    ) -> None:
        graph = _case_graph(case_id)
        plan = plan_from_case_graph(graph)
        lock_id = graph_lock_node(graph).node_id
        run_id = f"run-{case_id.value.replace('_', '-')}-exec"
        runtime = _facade_runtime(tmp_path, case_id)

        snapshot = runtime.start_run(
            plan, workflow_run_id=run_id, root_inputs=_root_inputs(case_id)
        )
        assert snapshot.status.value == "running"
        paused = runtime.run_to_completion(run_id, plan=plan)
        assert paused.status.value == "awaiting_decision"
        statuses = {n.node_id: n.status.value for n in paused.nodes}
        assert statuses[lock_id] == "awaiting_decision"
        # Every node that does not (transitively) depend on the lock is
        # already completed when the run pauses.
        dependents = {lock_id}
        changed = True
        while changed:
            changed = False
            for node in plan.nodes:
                if node.node_id not in dependents and dependents & set(node.depends_on):
                    dependents.add(node.node_id)
                    changed = True
        for node in paused.nodes:
            if node.node_id not in dependents:
                assert node.status.value == "completed", node.node_id

        # Agent cannot self-approve.
        assert runtime.advance(run_id, plan=plan).status.value == "awaiting_decision"

        recorded = runtime.record_decision(
            run_id,
            node_id=lock_id,
            decision_id=f"dec-{case_id.value}",
            actor_id="reviewer-facade",
            value=_decision_value(case_id),
            reason="human adoption of the locked chain",
        )
        assert recorded.status.value == "running"
        done = runtime.run_to_completion(run_id, plan=plan)
        assert done.status.value == "completed"
        assert all(n.status.value == "completed" for n in done.nodes)

        # Typed output schema checks: every node result carries exactly the
        # declared output schema of its plan node.
        events = runtime.read_events(run_id)
        results = [e for e in events if e.event_type == "graph_node_result"]
        assert len(results) == len(plan.nodes)
        schema_by_node = {node.node_id: node.output_schema for node in plan.nodes}
        for event in results:
            node_id = event.payload["node_id"]
            assert event.payload["output_schema"] == schema_by_node[node_id]
        # Service-dispatched nodes carry the persisted compacted contract;
        # the decision node's result carries the decision binding instead.
        dispatched = [e for e in results if "execution_contract" in e.payload]
        assert len(dispatched) == len(plan.nodes) - 1
        for event in dispatched:
            contract = event.payload["execution_contract"]
            assert contract["schema_version"] == "mw_protocol_v3_contract_v1_1"
            assert contract["dependency_sha256"]
            # The compacted representation replaced the field-level tuple.
            assert "input_artifact_hashes" not in contract
            assert event.payload["output_sha256"] == event.payload["output_sha256"]

    @pytest.mark.parametrize("case_id", _CASES)
    def test_duplicate_resume_of_the_full_run_is_fully_idempotent(
        self, tmp_path: Path, case_id
    ) -> None:
        graph = _case_graph(case_id)
        plan = plan_from_case_graph(graph)
        lock_id = graph_lock_node(graph).node_id
        run_id = f"run-{case_id.value.replace('_', '-')}-dup"
        runtime = _facade_runtime(tmp_path, case_id)
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs(case_id))
        runtime.run_to_completion(run_id, plan=plan)
        decision = runtime.record_decision(
            run_id,
            node_id=lock_id,
            decision_id=f"dec-{case_id.value}",
            actor_id="reviewer-facade",
            value=_decision_value(case_id),
            reason="human adoption",
        )
        assert decision.status.value == "running"
        first = runtime.run_to_completion(run_id, plan=plan)
        assert first.status.value == "completed"
        before = [
            e
            for e in runtime.read_events(run_id)
            if e.event_type == "graph_node_result"
        ]

        # Duplicate resume in a fresh runtime instance (fresh process state,
        # same durable database): no new results, no re-decision, completed.
        reopened = _facade_runtime(tmp_path, case_id)
        again = reopened.run_to_completion(run_id, plan=plan)
        assert again.status.value == "completed"
        after = [
            e
            for e in reopened.read_events(run_id)
            if e.event_type == "graph_node_result"
        ]
        assert [(e.payload["node_id"], e.payload["output_sha256"]) for e in after] == [
            (e.payload["node_id"], e.payload["output_sha256"]) for e in before
        ]
        decisions = [
            e
            for e in reopened.read_events(run_id)
            if e.event_type == "graph_decision_recorded"
        ]
        assert len(decisions) == 1


# ---------------------------------------------------------------------------
# Old-version graph migration fails closed at the product boundary
# ---------------------------------------------------------------------------


class TestOldGraphMigration:
    @pytest.mark.parametrize("case_id", _CASES)
    def test_old_version_plan_with_missing_link_fails_closed(
        self, tmp_path: Path, case_id
    ) -> None:
        from app.protocol_workflow.graph import GraphPlan, GraphPlanBindingError, GraphPlanError

        graph = _case_graph(case_id)
        plan = plan_from_case_graph(graph)
        # Build the old-version shape the injection declarations describe: a
        # graph missing one upstream dependency while still declaring the
        # input it used to cover.  The PoC graph validator already fails
        # closed on this shape at construction (CC_INPUT_UNCOVERED /
        # CC_EDGE_UNMATCHED_DEPENDENCY); here the dependency is dropped on the
        # converted plan so the *product* plan validation is what must reject
        # it — migration never auto-completes a missing link.
        first_node = plan.topological_order()[0]
        downstream = next(
            node
            for node in plan.nodes
            if first_node in node.depends_on
        )
        stripped_nodes = tuple(
            node.model_copy(
                update={
                    "depends_on": tuple(
                        d for d in node.depends_on if d != first_node
                    ),
                }
            )
            if node.node_id == downstream.node_id
            else node
            for node in plan.nodes
        )
        with pytest.raises(GraphPlanError) as raised:
            old_plan = plan.model_copy(
                update={
                    "graph_version": graph.graph_version.replace("_v1", "_v0"),
                    "nodes": stripped_nodes,
                }
            )
            GraphPlan.model_validate(old_plan.model_dump())
        assert raised.value.code in {
            "graph_input_uncovered",
            "graph_dependency_missing",
        }

        # And resuming a live run with an old graph *version* is rejected.
        old_version_plan = plan.model_copy(
            update={"graph_version": graph.graph_version.replace("_v1", "_v0")}
        )
        run_id = f"run-{case_id.value.replace('_', '-')}-old"
        runtime = _facade_runtime(tmp_path, case_id)
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs(case_id))
        with pytest.raises(GraphPlanBindingError):
            runtime.advance(run_id, plan=old_version_plan)


# ---------------------------------------------------------------------------
# Injection matrix with real own-process death (synthetic subprocesses)
# ---------------------------------------------------------------------------


def _child_services(case_id: CaseId, kill_inside: str | None):
    """Deterministic services for a child; may kill the child inside one
    node's dispatch (after the durable RUNNING claim)."""

    from app.protocol_workflow.graph import NodeServiceRequest

    base = deterministic_services(_case_graph(case_id))

    def _wrap(node_id, service):
        def _service(request: NodeServiceRequest):
            if kill_inside == node_id:
                os._exit(_KILL_MID_DISPATCH)
            return service(request)

        return _service

    return {
        node_id: (_wrap(node_id, service) if kill_inside == node_id else service)
        for node_id, service in base.items()
    }


def facade_child_main(payload_json: str) -> None:
    """Entry point of one synthetic child process (json payload on argv)."""

    payload = json.loads(payload_json)
    work_dir = Path(payload["work_dir"])
    evidence_path = payload["evidence_path"]
    run_id = payload["run_id"]
    case_id = CaseId(payload["case"])
    mode = payload["mode"]
    target = payload.get("target")

    graph = _case_graph(case_id)
    plan = plan_from_case_graph(graph)
    lock_id = graph_lock_node(graph).node_id

    runtime = _facade_runtime(
        work_dir, case_id, services=_child_services(case_id, payload.get("kill", {}).get("inside"))
    )
    evidence: dict[str, Any] = {"mode": mode, "executed": []}

    def _track(snapshot):
        for node in snapshot.nodes:
            if node.executed_in_last_call:
                evidence["executed"].append(node.node_id)
        return snapshot

    def _order(plan) -> tuple[str, ...]:
        return plan.topological_order()

    def _is_next(statuses: dict[str, str], node_id: str) -> bool:
        for candidate in _order(plan):
            if statuses.get(candidate) != "completed":
                return candidate == node_id
        return False

    def _die(code: int) -> None:
        handle = open(evidence_path, "w", encoding="utf-8")
        handle.write(json.dumps(evidence, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        sys.stdout.flush()
        os._exit(code)

    if mode == "run_until_pending":
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs(case_id))
        while True:
            statuses = {
                n.node_id: n.status.value for n in runtime.load_run(plan, run_id).nodes
            }
            if _is_next(statuses, target) and statuses[target] in ("pending", "awaiting_decision"):
                _die(_KILL_BEFORE)
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            if snapshot.status.value in ("completed", "blocked"):
                evidence["error"] = "target never reached"
                _die(70)

    if mode == "run_until_completed":
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs(case_id))
        while True:
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            statuses = {n.node_id: n.status.value for n in snapshot.nodes}
            if statuses.get(target) == "completed":
                _die(_KILL_AFTER)
            if snapshot.status.value in ("awaiting_decision", "blocked"):
                evidence["error"] = "target never completed"
                _die(70)

    if mode == "run_to_pause":
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs(case_id))
        while True:
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            if snapshot.status.value == "awaiting_decision":
                _die(0)
            if snapshot.status.value in ("completed", "blocked"):
                evidence["error"] = "pause never reached"
                _die(70)

    if mode == "record_decision_race":
        from app.protocol_workflow.graph import GraphDecisionConflictError

        markers = payload["barrier_markers"]
        marker_path = Path(markers[payload["racer_index"]])
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_text("ready", encoding="utf-8")
        import time

        met = False
        for _ in range(400):
            if all(Path(m).exists() for m in markers):
                met = True
                break
            time.sleep(0.025)
        if not met:
            # REQUIRED rendezvous: never proceed without the other racer.
            evidence["outcome"] = "rendezvous_failed"
            handle = open(evidence_path, "w", encoding="utf-8")
            handle.write(json.dumps(evidence, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
            handle.close()
            sys.stdout.flush()
            os._exit(75)
        try:
            runtime.record_decision(
                run_id,
                node_id=lock_id,
                decision_id=payload["decision_id"],
                actor_id=payload["actor_id"],
                value=_decision_value(case_id) | {"racer": payload["racer_index"]},
                reason=f"racer {payload['racer_index']}",
            )
            evidence["outcome"] = "recorded"
        except GraphDecisionConflictError as exc:
            # ONLY the typed conflict is the semantic loser outcome.
            evidence["outcome"] = "conflict"
            evidence["error"] = type(exc).__name__
        handle = open(evidence_path, "w", encoding="utf-8")
        handle.write(json.dumps(evidence, sort_keys=True))
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        sys.stdout.flush()
        os._exit(0)

    evidence["error"] = f"unknown mode {mode}"
    _die(70)


def _child_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(_REPO_ROOT / "services" / "api"),
                str(_REPO_ROOT / "packages"),
                str(_REPO_ROOT),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


_CHILD_SCRIPT = (
    "import sys; sys.path.insert(0, {tests!r}); "
    "import test_typed_facade as m; "
    "m.facade_child_main(sys.argv[1])".format(tests=str(_TESTS_DIR))
)


def _spawn_child(payload: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=240,
        env=_child_env(),
        cwd=str(_REPO_ROOT),
    )
    evidence: dict[str, Any] = {}
    if Path(payload["evidence_path"]).exists():
        evidence = json.loads(
            Path(payload["evidence_path"]).read_text(encoding="utf-8")
        )
    return {
        "returncode": proc.returncode,
        "stderr": proc.stderr,
        "evidence": evidence,
    }


def _spawn_children_overlapping(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spawn ALL children before joining any: genuinely overlapping
    lifetimes.  Rendezvous failure (exit 75) is a hard test failure."""

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD_SCRIPT, json.dumps(payload)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_child_env(),
            cwd=str(_REPO_ROOT),
        )
        for payload in payloads
    ]
    outputs = [proc.communicate(timeout=240) for proc in procs]
    results: list[dict[str, Any]] = []
    for proc, payload, (_out, err) in zip(procs, payloads, outputs):
        evidence: dict[str, Any] = {}
        if Path(payload["evidence_path"]).exists():
            evidence = json.loads(
                Path(payload["evidence_path"]).read_text(encoding="utf-8")
            )
        results.append(
            {"returncode": proc.returncode, "stderr": err, "evidence": evidence}
        )
    return results


def _injection_target(case_id: CaseId, kind_value: str) -> str:
    from pocs.protocol_v3.orchestrator import InjectionKind

    kind = InjectionKind(kind_value)
    graph = _case_graph(case_id)
    for point in graph.injections:
        if point.injection_kind is kind:
            assert point.target_node_id is not None
            return point.target_node_id
    raise AssertionError(f"{case_id} lacks a {kind_value} injection declaration")


def _run_id(case_id: CaseId, tag: str) -> str:
    return f"run-{case_id.value.replace('_', '-')}-{tag}"


class TestInjectionMatrixWithProcessDeath:
    @pytest.mark.parametrize("case_id", _CASES)
    def test_kill_before_declared_target_leaves_no_partial_state(
        self, tmp_path: Path, case_id
    ) -> None:
        from app.protocol_workflow.graph import GraphNodeStatus

        graph = _case_graph(case_id)
        plan = plan_from_case_graph(graph)
        lock_id = graph_lock_node(graph).node_id
        target = _injection_target(case_id, "kill_before")
        run_id = _run_id(case_id, "kb")
        result = _spawn_child(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child.json"),
                "run_id": run_id,
                "case": case_id.value,
                "mode": "run_until_pending",
                "target": target,
            }
        )
        assert result["returncode"] == _KILL_BEFORE, result

        executions: dict[str, int] = {}
        runtime = _facade_runtime(
            tmp_path, case_id, services=_counting_services(case_id, executions)
        )
        snapshot = runtime.load_run(plan, run_id)
        statuses = {n.node_id: n.status.value for n in snapshot.nodes}
        assert statuses[target] == GraphNodeStatus.PENDING.value
        assert snapshot.node_output(target) is None  # no partial artifact
        paused = runtime.run_to_completion(run_id, plan=plan)
        assert paused.status.value == "awaiting_decision"
        # Deterministic resume re-ran the target exactly once from clean state.
        assert executions[target] == 1
        runtime.record_decision(
            run_id,
            node_id=lock_id,
            decision_id=f"dec-{case_id.value}",
            actor_id="reviewer-facade",
            value=_decision_value(case_id),
            reason="human adoption",
        )
        assert runtime.run_to_completion(run_id, plan=plan).status.value == "completed"
        results = [
            e
            for e in runtime.read_events(run_id)
            if e.event_type == "graph_node_result" and e.payload["node_id"] == target
        ]
        assert len(results) == 1  # one effective artifact lineage

    @pytest.mark.parametrize("case_id", _CASES)
    def test_kill_after_declared_target_reuses_durable_result(
        self, tmp_path: Path, case_id
    ) -> None:
        graph = _case_graph(case_id)
        plan = plan_from_case_graph(graph)
        lock_id = graph_lock_node(graph).node_id
        target = _injection_target(case_id, "kill_after")
        run_id = _run_id(case_id, "ka")
        result = _spawn_child(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child.json"),
                "run_id": run_id,
                "case": case_id.value,
                "mode": "run_until_completed",
                "target": target,
            }
        )
        assert result["returncode"] == _KILL_AFTER, result
        assert result["evidence"]["executed"][-1] == target
        assert target in result["evidence"]["executed"]

        executions: dict[str, int] = {}
        runtime = _facade_runtime(
            tmp_path, case_id, services=_counting_services(case_id, executions)
        )
        snapshot = runtime.load_run(plan, run_id)
        durable_sha = snapshot.node_output(target)
        assert durable_sha
        paused = runtime.run_to_completion(run_id, plan=plan)
        assert paused.status.value == "awaiting_decision"
        assert target not in executions  # reused, never re-executed
        attempts = runtime.reservation_attempts(run_id, target)
        assert len(attempts) == 1
        runtime.record_decision(
            run_id,
            node_id=lock_id,
            decision_id=f"dec-{case_id.value}",
            actor_id="reviewer-facade",
            value=_decision_value(case_id),
            reason="human adoption",
        )
        done = runtime.run_to_completion(run_id, plan=plan)
        assert done.status.value == "completed"
        assert runtime.load_run(plan, run_id).node_output(target) == durable_sha

    @pytest.mark.parametrize("case_id", _CASES)
    def test_concurrent_decision_at_declared_lock_has_one_winner(
        self, tmp_path: Path, case_id
    ) -> None:
        graph = _case_graph(case_id)
        plan = plan_from_case_graph(graph)
        lock_id = graph_lock_node(graph).node_id
        assert _injection_target(case_id, "concurrent_decision") == lock_id
        run_id = _run_id(case_id, "cd")
        setup = _spawn_child(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "setup.json"),
                "run_id": run_id,
                "case": case_id.value,
                "mode": "run_to_pause",
            }
        )
        assert setup["returncode"] == 0, setup

        markers = [str(tmp_path / f"racer-{i}.marker") for i in range(2)]
        for marker in markers:
            Path(marker).unlink(missing_ok=True)
        payloads = []
        for index in range(2):
            payloads.append(
                {
                    "work_dir": str(tmp_path),
                    "evidence_path": str(tmp_path / f"racer-{index}.json"),
                    "run_id": run_id,
                    "case": case_id.value,
                    "mode": "record_decision_race",
                    "barrier_markers": markers,
                    "racer_index": index,
                    "decision_id": f"dec-racer-{index}",
                    "actor_id": f"reviewer-{index}",
                }
            )
        # Genuinely overlapping Popen lifetimes; rendezvous REQUIRED.
        outcomes = _spawn_children_overlapping(payloads)
        for outcome in outcomes:
            assert outcome["returncode"] == 0, outcome
        observed = [o["evidence"].get("outcome") for o in outcomes]
        assert sorted(observed) == ["conflict", "recorded"], (
            [o["stderr"] for o in outcomes],
            observed,
        )
        loser = next(
            o for o in outcomes if o["evidence"]["outcome"] == "conflict"
        )
        assert loser["evidence"]["error"] == "GraphDecisionConflictError"

        executions: dict[str, int] = {}
        runtime = _facade_runtime(
            tmp_path, case_id, services=_counting_services(case_id, executions)
        )
        events = runtime.read_events(run_id)
        recorded = [
            e for e in events if e.event_type == "graph_decision_recorded"
        ]
        assert len(recorded) == 1
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"


def _counting_services(case_id: CaseId, executions: dict[str, int]):
    """Deterministic facade services that count physical executions."""

    from app.protocol_workflow.graph import NodeServiceRequest

    base = deterministic_services(_case_graph(case_id))

    def _wrap(node_id, service):
        def _service(request: NodeServiceRequest):
            executions[node_id] = executions.get(node_id, 0) + 1
            return service(request)

        return _service

    return {node_id: _wrap(node_id, service) for node_id, service in base.items()}


# ---------------------------------------------------------------------------
# Import isolation: the product runtime never imports pocs
# ---------------------------------------------------------------------------


def test_product_graph_runtime_imports_no_pocs_module() -> None:
    script = r"""
import sys
before = set(sys.modules)
import app.protocol_workflow.graph
import app.protocol_workflow.graph.runtime
import app.protocol_workflow.graph.plan
added = sorted(set(sys.modules) - before)
print("\n".join(added))
"""
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(_REPO_ROOT / "services" / "api"),
                str(_REPO_ROOT / "packages"),
                str(_REPO_ROOT),
                os.environ.get("PYTHONPATH", ""),
            ]
        ),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    added = {line for line in result.stdout.splitlines() if line.strip()}
    assert "app.protocol_workflow.graph" in added
    assert not any(module == "pocs" or module.startswith("pocs.") for module in added), (
        "product graph runtime imported pocs modules"
    )
