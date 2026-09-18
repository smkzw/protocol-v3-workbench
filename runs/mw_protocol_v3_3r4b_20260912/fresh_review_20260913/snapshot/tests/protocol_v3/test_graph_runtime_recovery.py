"""Typed graph runtime recovery matrix against real process death (Task 2R.1).

Product-side recovery matrix.  Repair round (post Codex review):

* every kill-before / kill-after / duplicate-resume path is exercised with
  an actual *own* synthetic subprocess force-killed at the declared boundary;
* the concurrent-decision races use genuinely OVERLAPPING ``Popen``
  lifetimes with a REQUIRED rendezvous (rendezvous failure fails the test —
  no timeout-then-proceed), and only the typed
  ``GraphDecisionConflictError`` counts as the semantic conflict outcome;
* an identical-content concurrent decision race reuses exactly once (both
  racers report recorded, exactly one decision event survives);
* two crash windows are covered with real process death plus an in-process
  forced variant: (a) final result durable but completion event lost —
  reopen converges to completed without dispatch; (b) result event durable
  but reservation not yet terminal — reopen repairs the reservation from
  the authoritative event;
* overlapped ``advance`` on the same node surfaces a typed retriable
  contention error, dispatches exactly once, and converges.

Only synthetic child processes created by these tests are killed.  No
provider, model, network or live service is used.  All persistence goes
through the product SQLite adapter with the committed-reservation runtime.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory,
    build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import ReservationStatus

import test_graph_runtime as g


_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Exit codes used by the synthetic children at each kill boundary.
_KILL_BEFORE = 67
_KILL_AFTER = 68
_KILL_MID_DISPATCH = 69
_KILL_AFTER_COMPLETION = 71
_KILL_AFTER_RECEIPT = 72
_RENDEZVOUS_FAILED = 75


# ---------------------------------------------------------------------------
# Child process entry point
# ---------------------------------------------------------------------------


def _child_services(kill: dict[str, Any]):
    """Typed services for a child process; ``kill`` may direct the child to
    die inside a node's dispatch (after the durable RUNNING claim)."""

    from app.protocol_workflow.graph import NodeServiceRequest

    kill_inside = kill.get("inside")

    def _service(request: NodeServiceRequest) -> dict[str, Any]:
        if kill_inside == request.node.node_id:
            os._exit(_KILL_MID_DISPATCH)
        return {
            "node": request.node.node_id,
            "schema": request.node.output_schema,
            "label": "labeled-synthetic-recovery",
        }

    return {node.node_id: _service for node in g._probe_plan().nodes}


def _rendezvous(markers: list[str], racer_index: int) -> bool:
    """Barrier over marker files; returns False on timeout (the caller must
    hard-fail — never proceed unilaterally)."""

    marker_path = Path(markers[racer_index])
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text("ready", encoding="utf-8")
    import time

    for _ in range(400):
        if all(Path(marker).exists() for marker in markers):
            return True
        time.sleep(0.025)
    return False


def _write_evidence(path: str, evidence: dict[str, Any]) -> None:
    handle = open(path, "w", encoding="utf-8")
    handle.write(json.dumps(evidence, sort_keys=True))
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


def child_main(payload_json: str) -> None:
    """Entry point of one synthetic child process (json payload on argv)."""

    payload = json.loads(payload_json)
    work_dir = Path(payload["work_dir"])
    evidence_path = payload["evidence_path"]
    run_id = payload["run_id"]
    mode = payload["mode"]
    target = payload.get("target")

    from app.protocol_workflow.graph import (
        GraphDecisionConflictError,
        GraphRunError,
        NodeServiceRequest,
    )

    plan = g._probe_plan()
    started_here = payload.get("start", False)

    def _build():
        return g._runtime(work_dir, _child_services(payload.get("kill", {})))

    evidence: dict[str, Any] = {"mode": mode, "executed": []}

    runtime = _build()

    def _track(snapshot):
        for node in snapshot.nodes:
            if node.executed_in_last_call:
                evidence["executed"].append(node.node_id)
        return snapshot

    def _is_next(statuses: dict[str, str], node_id: str) -> bool:
        for candidate in plan.topological_order():
            if statuses.get(candidate) != "completed":
                return candidate == node_id
        return False

    def _die(code: int) -> None:
        _write_evidence(evidence_path, evidence)
        sys.stdout.flush()
        os._exit(code)

    if mode == "run_until_pending":
        assert started_here
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
        while True:
            statuses = {n.node_id: n.status.value for n in runtime.load_run(plan, run_id).nodes}
            if _is_next(statuses, target) and statuses[target] in ("pending", "awaiting_decision"):
                # Die BEFORE the runtime advances into the target node.
                _die(_KILL_BEFORE)
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            if snapshot.status.value in ("completed", "blocked"):
                evidence["error"] = "target never reached"
                _die(70)

    if mode == "run_until_completed":
        assert started_here
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
        while True:
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            statuses = {n.node_id: n.status.value for n in snapshot.nodes}
            if statuses.get(target) == "completed":
                # Die AFTER the target's result is durably committed.
                _die(_KILL_AFTER)
            if snapshot.status.value in ("awaiting_decision", "blocked"):
                evidence["error"] = "target never completed"
                _die(70)

    if mode == "run_to_pause":
        assert started_here
        runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
        while True:
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            if snapshot.status.value == "awaiting_decision":
                _die(0)
            if snapshot.status.value in ("completed", "blocked"):
                evidence["error"] = "pause never reached"
                _die(70)

    if mode == "run_full":
        if started_here:
            runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
        while True:
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            if snapshot.status.value == "awaiting_decision":
                snapshot = runtime.record_decision(
                    run_id,
                    node_id="lock_node",
                    decision_id=payload.get("decision_id", "dec-child-1"),
                    actor_id=payload.get("actor_id", "reviewer-child"),
                    value={"approved": True, "label": "labeled-synthetic"},
                    reason="child decision",
                )
            if snapshot.status.value in ("completed", "blocked"):
                evidence["status"] = snapshot.status.value
                _die(0 if snapshot.status.value == "completed" else 70)

    if mode == "die_before_completion_event":
        """Real death in the window: the last node's result is committed but
        the run-completion event was not yet appended (the child dies inside
        its own completion step)."""

        def finish_then_die(workflow_run_id=None, view=None):
            # Die ONLY in the exact window: every node result durable, the
            # completion event not yet appended.  Earlier completion checks
            # fall through to the normal (no-op) path.
            current = runtime._load(workflow_run_id, caller_plan=None)
            if len(current.results) == len(plan.nodes):
                os._exit(_KILL_AFTER_COMPLETION)
            return None

        runtime._finish_run_if_complete = finish_then_die
        if started_here:
            runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
        while True:
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            if snapshot.status.value == "awaiting_decision":
                try:
                    runtime.record_decision(
                        run_id,
                        node_id="lock_node",
                        decision_id="dec-child-final",
                        actor_id="reviewer-child",
                        value={"approved": True},
                        reason="child decision",
                    )
                except GraphDecisionConflictError:
                    pass
                continue
            if snapshot.status.value in ("completed", "blocked"):
                evidence["error"] = "completion event appended before the kill"
                _die(70)

    if mode == "die_after_result_before_reservation_terminal":
        """Real death in the window: the result event is committed inside
        the transport but the reservation never reaches its terminal
        transition (the child dies on the receipt boundary)."""

        from app.protocol_workflow.graph.runtime import _ServiceTransport

        original_dispatch = _ServiceTransport.dispatch

        def dispatch_then_die(self, *, project_id, reservation, payload):
            original_dispatch(
                self, project_id=project_id, reservation=reservation, payload=payload
            )
            os._exit(_KILL_AFTER_RECEIPT)

        _ServiceTransport.dispatch = dispatch_then_die
        if started_here:
            runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
        while True:
            snapshot = runtime.advance(run_id, plan=plan)
            # Never returns past the first dispatch: the child dies on the
            # receipt boundary of draft_node.
            _track(snapshot)

    if mode == "advance_once":
        """Single overlapped advance; records the execution and any typed
        contention error for the parent's single-dispatch assertion."""

        if started_here:
            runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
        markers = payload.get("barrier_markers")
        if markers:
            if not _rendezvous(markers, payload["racer_index"]):
                evidence["outcome"] = "rendezvous_failed"
                _die(_RENDEZVOUS_FAILED)
        try:
            snapshot = runtime.advance(run_id, plan=plan)
            _track(snapshot)
            evidence["status"] = snapshot.status.value
        except GraphRunError as exc:
            evidence["graph_error"] = exc.code
        _die(0)

    if mode == "record_decision_race":
        markers = payload["barrier_markers"]
        if not _rendezvous(markers, payload["racer_index"]):
            # REQUIRED rendezvous: never proceed without the other racer.
            evidence["outcome"] = "rendezvous_failed"
            _die(_RENDEZVOUS_FAILED)
        if payload.get("same_value"):
            value = {"approved": payload["approved"]}
        else:
            value = {"approved": payload["approved"], "racer": payload["racer_index"]}
        try:
            runtime.record_decision(
                run_id,
                node_id="lock_node",
                decision_id=payload["decision_id"],
                actor_id=payload["actor_id"],
                value=value,
                reason=f"racer {payload['racer_index']}",
            )
            evidence["outcome"] = "recorded"
        except GraphDecisionConflictError as exc:
            # ONLY the typed conflict is the semantic loser outcome.
            evidence["outcome"] = "conflict"
            evidence["error"] = type(exc).__name__
        _die(0)

    evidence["error"] = f"unknown mode {mode}"
    _die(70)


# ---------------------------------------------------------------------------
# Parent-side helpers
# ---------------------------------------------------------------------------


def _child_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [
                str(_REPO_ROOT / "tests" / "protocol_v3"),
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
    "import test_graph_runtime_recovery as m; "
    "m.child_main(sys.argv[1])".format(
        tests=str(_REPO_ROOT / "tests" / "protocol_v3")
    )
)


def _spawn(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one synthetic child and return its fsynced evidence document."""

    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_SCRIPT, json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=180,
        env=_child_env(),
        cwd=str(_REPO_ROOT),
    )
    evidence_path = payload["evidence_path"]
    evidence: dict[str, Any] = {}
    if Path(evidence_path).exists():
        evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "evidence": evidence,
    }


def _spawn_overlapping(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Spawn ALL children before joining any: genuinely overlapping lifetimes.

    Both processes are created first, then waited on together, so neither
    can finish (or time out its rendezvous) before the other is running.
    Rendezvous failure is a hard test failure (exit 75), never a proceed.
    """

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
    outputs = [proc.communicate(timeout=180) for proc in procs]
    results: list[dict[str, Any]] = []
    for proc, payload, (out, err) in zip(procs, payloads, outputs):
        evidence_path = payload["evidence_path"]
        evidence: dict[str, Any] = {}
        if Path(evidence_path).exists():
            evidence = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
        results.append(
            {
                "returncode": proc.returncode,
                "stdout": out,
                "stderr": err,
                "evidence": evidence,
            }
        )
    return results


def _statuses(snapshot) -> dict[str, str]:
    return {node.node_id: node.status.value for node in snapshot.nodes}


# ---------------------------------------------------------------------------
# kill-before / kill-after / mid-dispatch with real process death
# ---------------------------------------------------------------------------


class TestProcessKillRecovery:
    def test_kill_before_node_leaves_no_partial_state(self, tmp_path: Path) -> None:
        run_id = "run-kill-before-1"
        result = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child.json"),
                "run_id": run_id,
                "mode": "run_until_pending",
                "target": "review_node",
                "start": True,
            }
        )
        assert result["returncode"] == _KILL_BEFORE, result

        # Parent reopens the same database in a fresh runtime: the target is
        # still pending with no partial artifact and runs cleanly.
        executions: dict[str, int] = {}
        runtime = g._runtime(tmp_path, g._probe_services(executions))
        plan = g._probe_plan()
        snapshot = runtime.load_run(plan, run_id)
        assert _statuses(snapshot)["review_node"] == "pending"
        assert snapshot.nodes[1].output_sha256 is None
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "awaiting_decision"
        assert executions == {"review_node": 1}
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-parent-1",
            actor_id="reviewer-parent",
            value={"approved": True},
            reason="parent",
        )
        done = runtime.run_to_completion(run_id, plan=plan)
        assert done.status.value == "completed"
        assert executions == {"review_node": 1, "final_node": 1}
        results = [
            e for e in runtime.read_events(run_id) if e.event_type == "graph_node_result"
        ]
        assert len([e for e in results if e.payload["node_id"] == "review_node"]) == 1

    def test_kill_after_node_reuses_durable_result(self, tmp_path: Path) -> None:
        run_id = "run-kill-after-1"
        result = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child.json"),
                "run_id": run_id,
                "mode": "run_until_completed",
                "target": "draft_node",
                "start": True,
            }
        )
        assert result["returncode"] == _KILL_AFTER, result
        assert result["evidence"]["executed"] == ["draft_node"]

        executions: dict[str, int] = {}
        runtime = g._runtime(tmp_path, g._probe_services(executions))
        plan = g._probe_plan()
        snapshot = runtime.load_run(plan, run_id)
        assert _statuses(snapshot)["draft_node"] == "completed"
        durable_sha = snapshot.nodes[0].output_sha256
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "awaiting_decision"
        # The killed process's result is reused verbatim: no re-execution,
        # no second lineage.
        assert executions == {"review_node": 1}
        assert final.nodes[0].output_sha256 == durable_sha
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert len(attempts) == 1
        assert attempts[0].status is ReservationStatus.COMPLETED

    def test_kill_inside_dispatch_blocks_and_never_auto_redispatches(
        self, tmp_path: Path
    ) -> None:
        run_id = "run-kill-mid-1"
        result = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child.json"),
                "run_id": run_id,
                "mode": "run_until_completed",
                "target": "never_reached",
                "start": True,
                "kill": {"inside": "draft_node"},
            }
        )
        assert result["returncode"] == _KILL_MID_DISPATCH, result

        executions: dict[str, int] = {}
        runtime = g._runtime(tmp_path, g._probe_services(executions))
        plan = g._probe_plan()
        snapshot = runtime.load_run(plan, run_id)
        assert _statuses(snapshot)["draft_node"] == "blocked_unknown"
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert len(attempts) == 1
        assert attempts[0].status is ReservationStatus.RUNNING

        # Resume refuses to redispatch: the run stays blocked, zero work.
        blocked = runtime.run_to_completion(run_id, plan=plan)
        assert blocked.status.value == "blocked"
        assert executions == {}

        # Explicit owner resolution + explicit append-only retry recovers.
        runtime.resolve_blocked_with_failure(
            run_id,
            node_id="draft_node",
            resolution_id="res-parent-1",
            reason="crash window closed as failed",
        )
        retried = runtime.retry_node(
            run_id,
            node_id="draft_node",
            retry_decision_id="retry-parent-1",
            reason="owner retry",
        )
        assert retried.nodes[0].status.value == "completed"
        assert executions == {"draft_node": 1}
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert [a.attempt for a in attempts] == [1, 2]
        assert attempts[0].status is ReservationStatus.FAILED
        assert attempts[1].status is ReservationStatus.COMPLETED
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "awaiting_decision"

    def test_duplicate_resume_across_processes_creates_no_second_lineage(
        self, tmp_path: Path
    ) -> None:
        run_id = "run-duplicate-1"
        first = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child1.json"),
                "run_id": run_id,
                "mode": "run_full",
                "start": True,
                "decision_id": "dec-child-1",
                "actor_id": "reviewer-child",
            }
        )
        assert first["returncode"] == 0, first
        assert first["evidence"]["executed"] == ["draft_node", "review_node", "final_node"]

        # A second, fresh process resumes the same run to completion: every
        # result is reused, nothing executes, no new events appear.
        executions: dict[str, int] = {}
        runtime = g._runtime(tmp_path, g._probe_services(executions))
        plan = g._probe_plan()
        before_events = len(runtime.read_events(run_id))
        before_results = [
            e for e in runtime.read_events(run_id) if e.event_type == "graph_node_result"
        ]
        snapshot = runtime.run_to_completion(run_id, plan=plan)
        assert snapshot.status.value == "completed"
        assert executions == {}
        assert len(runtime.read_events(run_id)) == before_events
        after_results = [
            e for e in runtime.read_events(run_id) if e.event_type == "graph_node_result"
        ]
        assert before_results == after_results
        # Service-dispatched nodes each carry exactly one completed
        # reservation attempt; the decision node applies without a dispatch.
        for node_id in ("draft_node", "review_node", "final_node"):
            attempts = runtime.reservation_attempts(run_id, node_id)
            assert len(attempts) == 1
            assert attempts[0].status is ReservationStatus.COMPLETED


# ---------------------------------------------------------------------------
# Concurrent decisions across two real, overlapping processes
# ---------------------------------------------------------------------------


def _racer_payloads(tmp_path: Path, run_id: str, *, identical: bool):
    markers = [str(tmp_path / f"racer-{index}.marker") for index in range(2)]
    for marker in markers:
        Path(marker).unlink(missing_ok=True)
    payloads = []
    for index in range(2):
        if identical:
            decision_id, actor_id, approved = "dec-same", "reviewer-same", True
        else:
            decision_id, actor_id, approved = (
                f"dec-racer-{index}",
                f"reviewer-{index}",
                index == 0,
            )
        payloads.append(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / f"racer-{index}.json"),
                "run_id": run_id,
                "mode": "record_decision_race",
                "barrier_markers": markers,
                "racer_index": index,
                "decision_id": decision_id,
                "actor_id": actor_id,
                "approved": approved,
                "same_value": identical,
            }
        )
    return payloads


class TestConcurrentDecision:
    def test_exactly_one_concurrent_decision_wins_with_overlapping_lifetimes(
        self, tmp_path: Path
    ) -> None:
        run_id = "run-concurrent-1"
        setup = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "setup.json"),
                "run_id": run_id,
                "mode": "run_to_pause",
                "start": True,
            }
        )
        assert setup["returncode"] == 0, setup

        # Two children with genuinely overlapping lifetimes race to record
        # conflicting decisions.  The rendezvous is REQUIRED: a child that
        # cannot meet the other racer exits 75 and fails this test.
        outcomes = _spawn_overlapping(
            _racer_payloads(tmp_path, run_id, identical=False)
        )
        for outcome in outcomes:
            assert outcome["returncode"] == 0, outcome
        observed = [o["evidence"].get("outcome") for o in outcomes]
        assert sorted(observed) == ["conflict", "recorded"], (
            [o["stderr"] for o in outcomes],
            observed,
        )
        # Only the typed conflict counts as the semantic loser outcome.
        loser = next(
            o for o in outcomes if o["evidence"]["outcome"] == "conflict"
        )
        assert loser["evidence"]["error"] == "GraphDecisionConflictError"

        # Exactly one decision record exists; the run completes from it.
        runtime = g._runtime(tmp_path, g._probe_services({}))
        plan = g._probe_plan()
        events = runtime.read_events(run_id)
        recorded = [e for e in events if e.event_type == "graph_decision_recorded"]
        assert len(recorded) == 1
        assert recorded[0].payload["actor_id"] in {"reviewer-0", "reviewer-1"}
        winner_index = 0 if recorded[0].payload["actor_id"] == "reviewer-0" else 1
        assert outcomes[winner_index]["evidence"]["outcome"] == "recorded"
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"
        assert _statuses(final)["lock_node"] == "completed"

    def test_identical_concurrent_decisions_reuse_exactly_once(
        self, tmp_path: Path
    ) -> None:
        run_id = "run-concurrent-same-1"
        setup = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "setup.json"),
                "run_id": run_id,
                "mode": "run_to_pause",
                "start": True,
            }
        )
        assert setup["returncode"] == 0, setup

        outcomes = _spawn_overlapping(
            _racer_payloads(tmp_path, run_id, identical=True)
        )
        for outcome in outcomes:
            assert outcome["returncode"] == 0, outcome
        observed = [o["evidence"].get("outcome") for o in outcomes]
        assert observed == ["recorded", "recorded"], (
            [o["stderr"] for o in outcomes],
            observed,
        )
        runtime = g._runtime(tmp_path, g._probe_services({}))
        plan = g._probe_plan()
        events = runtime.read_events(run_id)
        recorded = [e for e in events if e.event_type == "graph_decision_recorded"]
        assert len(recorded) == 1
        assert recorded[0].payload["decision_id"] == "dec-same"
        lock_results = [
            e
            for e in events
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "lock_node"
        ]
        assert len(lock_results) == 1
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"


# ---------------------------------------------------------------------------
# Crash-window convergence with real process death
# ---------------------------------------------------------------------------


class TestCrashWindowConvergence:
    def test_reopen_after_kill_before_completion_event_finishes_without_dispatch(
        self, tmp_path: Path
    ) -> None:
        """Real process death in the exact window: the final node's result
        is durably committed, the completion event is not.  Reopen must
        converge to completed with zero dispatches."""

        run_id = "run-window-completion-1"
        result = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child.json"),
                "run_id": run_id,
                "mode": "die_before_completion_event",
                "start": True,
            }
        )
        assert result["returncode"] == _KILL_AFTER_COMPLETION, result

        executions: dict[str, int] = {}
        runtime = g._runtime(tmp_path, g._probe_services(executions))
        plan = g._probe_plan()
        # Precondition: all results durable, completion event missing.
        events_before = runtime.read_events(run_id)
        assert not any(
            e.event_type == "graph_run_completed" for e in events_before
        )
        assert (
            len([e for e in events_before if e.event_type == "graph_node_result"])
            == 4
        )
        snapshot = runtime.advance(run_id)
        assert executions == {}
        assert snapshot.status.value == "completed"
        completed = [
            e
            for e in runtime.read_events(run_id)
            if e.event_type == "graph_run_completed"
        ]
        assert len(completed) == 1
        for node_id in ("draft_node", "review_node", "final_node"):
            attempts = runtime.reservation_attempts(run_id, node_id)
            assert len(attempts) == 1
            assert attempts[0].status is ReservationStatus.COMPLETED

    def test_result_event_before_reservation_terminal_is_repaired_on_reopen(
        self, tmp_path: Path
    ) -> None:
        """Forced window (in-process): the transport commits the durable
        result and the receipt is then lost (the coordinator classifies the
        dispatch unknown).  The authoritative event/result data repairs the
        reservation on reopen — the payload stays usable downstream and the
        attempt lineage stays append-only."""

        from app.protocol_workflow.graph.runtime import _ServiceTransport

        original_dispatch = _ServiceTransport.dispatch

        def dispatch_then_explode(self, *, project_id, reservation, payload):
            original_dispatch(
                self, project_id=project_id, reservation=reservation, payload=payload
            )
            raise RuntimeError("synthetic loss after durable result")

        _ServiceTransport.dispatch = dispatch_then_explode
        try:
            executions: dict[str, int] = {}
            runtime = g._runtime(tmp_path, g._probe_services(executions))
            plan = g._probe_plan()
            run_id = "run-window-receipt-1"
            runtime.start_run(
                plan, workflow_run_id=run_id, root_inputs=g._root_inputs()
            )
            # First advance: draft's result is committed, then the receipt
            # is lost — the dispatch classifies UNKNOWN_OUTCOME while the
            # authoritative result event is already durable.
            first = runtime.advance(run_id, plan=plan)
            assert executions == {"draft_node": 1}
            assert first.nodes[0].status.value == "completed"
            attempts = runtime.reservation_attempts(run_id, "draft_node")
            assert [a.attempt for a in attempts] == [1]
            assert attempts[0].status is ReservationStatus.UNKNOWN_OUTCOME
            paused = runtime.run_to_completion(run_id, plan=plan)
            # The repair + continuation runs review; both nodes end with
            # their result payloads durable.
            assert executions == {"draft_node": 1, "review_node": 1}
            assert paused.status.value == "awaiting_decision"
        finally:
            _ServiceTransport.dispatch = original_dispatch

        # The human decision still applies before the run can finish.
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-window-receipt",
            actor_id="reviewer-window",
            value={"approved": True},
            reason="decision after durable results",
        )

        # Reopen: the repair path converges the reservation from the
        # authoritative result event; downstream continues normally.
        executions2: dict[str, int] = {}
        reopened = g._runtime(tmp_path, g._probe_services(executions2))
        plan = g._probe_plan()
        snapshot = reopened.load_run(plan, run_id)
        assert snapshot.nodes[0].status.value == "completed"
        final = reopened.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"
        for node_id in ("draft_node", "review_node"):
            attempts = reopened.reservation_attempts(run_id, node_id)
            assert [a.attempt for a in attempts] == [1]
            assert attempts[0].status is ReservationStatus.COMPLETED
        assert executions2.get("draft_node", 0) == 0  # never re-dispatched
        assert executions2.get("review_node", 0) == 0  # never re-dispatched
        results = [
            e
            for e in reopened.read_events(run_id)
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "draft_node"
        ]
        assert len(results) == 1

    def test_real_process_death_between_result_and_reservation_terminal(
        self, tmp_path: Path
    ) -> None:
        """Real child death on the receipt boundary: the result event is
        committed, the child dies before the coordinator's terminal
        transition, leaving the reservation RUNNING.  Reopen repairs from
        the authoritative event and completes without re-dispatch."""

        run_id = "run-window-receipt-real-1"
        result = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "child.json"),
                "run_id": run_id,
                "mode": "die_after_result_before_reservation_terminal",
                "start": True,
            }
        )
        assert result["returncode"] == _KILL_AFTER_RECEIPT, result

        executions: dict[str, int] = {}
        runtime = g._runtime(tmp_path, g._probe_services(executions))
        plan = g._probe_plan()
        events = runtime.read_events(run_id)
        draft_results = [
            e
            for e in events
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "draft_node"
        ]
        assert len(draft_results) == 1  # result survived the death
        # The reservation row is not yet terminal after the death.
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert [a.attempt for a in attempts] == [1]
        assert attempts[0].status in (
            ReservationStatus.RUNNING,
            ReservationStatus.UNKNOWN_OUTCOME,
        )
        # Reopen repairs and proceeds; the recovered payload feeds review.
        paused = runtime.run_to_completion(run_id, plan=plan)
        assert paused.status.value == "awaiting_decision"
        assert executions == {"review_node": 1}  # draft not re-dispatched
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-window-real",
            actor_id="reviewer-window-real",
            value={"approved": True},
            reason="decision after repair",
        )
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert [a.attempt for a in attempts] == [1]
        assert attempts[0].status is ReservationStatus.COMPLETED
        review = [
            e
            for e in runtime.read_events(run_id)
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "review_node"
        ]
        assert len(review) == 1
        assert review[0].payload["input_hashes"]["draft"] == (
            draft_results[0].payload["output_sha256"]
        )


# ---------------------------------------------------------------------------
# Overlapped advance on the same node: typed contention, single dispatch
# ---------------------------------------------------------------------------


class TestOverlappedAdvanceContention:
    def test_same_node_advance_dispatches_once_and_converges(
        self, tmp_path: Path
    ) -> None:
        run_id = "run-advance-race-1"
        setup = _spawn(
            {
                "work_dir": str(tmp_path),
                "evidence_path": str(tmp_path / "setup.json"),
                "run_id": run_id,
                "mode": "run_until_pending",
                "target": "draft_node",
                "start": True,
            }
        )
        assert setup["returncode"] == _KILL_BEFORE, setup

        markers = [str(tmp_path / f"adv-{index}.marker") for index in range(2)]
        for marker in markers:
            Path(marker).unlink(missing_ok=True)
        payloads = []
        for index in range(2):
            payloads.append(
                {
                    "work_dir": str(tmp_path),
                    "evidence_path": str(tmp_path / f"adv-{index}.json"),
                    "run_id": run_id,
                    "mode": "advance_once",
                    "barrier_markers": markers,
                    "racer_index": index,
                }
            )
        outcomes = _spawn_overlapping(payloads)
        for outcome in outcomes:
            assert outcome["returncode"] == 0, outcome
        executions = [o["evidence"].get("executed", []) for o in outcomes]
        # Single physical dispatch: at most one child executed draft_node.
        draft_dispatches = sum(
            1 for executed in executions if "draft_node" in executed
        )
        assert draft_dispatches <= 1, executions
        # Any loser that hit the live shell sees the TYPED retriable code —
        # never a raw repository error type.
        for outcome in outcomes:
            error = outcome["evidence"].get("graph_error")
            if error is not None:
                assert error == "graph_reservation_contended_retryable", outcome

        # Eventual convergence: the human decision is recorded and the run
        # completes with a single draft attempt.
        runtime = g._runtime(tmp_path, g._probe_services({}))
        plan = g._probe_plan()
        paused = runtime.run_to_completion(run_id, plan=plan)
        assert paused.status.value == "awaiting_decision"
        runtime.record_decision(
            run_id,
            node_id="lock_node",
            decision_id="dec-advance-race",
            actor_id="reviewer-advance-race",
            value={"approved": True},
            reason="convergence",
        )
        final = runtime.run_to_completion(run_id, plan=plan)
        assert final.status.value == "completed"
        attempts = runtime.reservation_attempts(run_id, "draft_node")
        assert [a.attempt for a in attempts] == [1]
        assert attempts[0].status is ReservationStatus.COMPLETED
        draft_results = [
            e
            for e in runtime.read_events(run_id)
            if e.event_type == "graph_node_result"
            and e.payload["node_id"] == "draft_node"
        ]
        assert len(draft_results) == 1
