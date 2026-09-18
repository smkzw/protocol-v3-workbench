"""Independent deterministic interleaving; temporary SQLite only."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock

import pytest
import test_graph_runtime as g
from app.protocol_workflow.graph.state import GraphDecisionConflictError, GraphRunError


def test_conflicting_decisions_cannot_both_pass_stale_precheck(tmp_path):
    setup = g._runtime(tmp_path, g._probe_services({}))
    setup.start_run(g._probe_plan(), workflow_run_id="race-probe", root_inputs=g._root_inputs())
    setup.run_to_completion("race-probe")
    rendezvous = Barrier(2, timeout=10)
    commit_order = Lock()

    def submit(index):
        runtime = g._runtime(tmp_path, g._probe_services({}))
        append = runtime._append_events

        def interleave(run_id, specs):
            if specs[0][0] == "graph_decision_recorded":
                rendezvous.wait()
                with commit_order:
                    return append(run_id, specs)
            return append(run_id, specs)

        runtime._append_events = interleave
        try:
            runtime.record_decision(
                "race-probe", node_id="lock_node", decision_id=f"choice-{index}",
                actor_id=f"writer-{index}", value={"approved": index == 0}, reason="choice",
            )
            return "recorded"
        except GraphDecisionConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, (0, 1)))
    records = [event for event in setup.read_events("race-probe")
               if event.event_type == "graph_decision_recorded"]
    assert len(records) == 1, (outcomes, [event.payload["decision_id"] for event in records])
    assert sorted(outcomes) == ["conflict", "recorded"]


def test_same_run_cannot_silently_accept_changed_root_facts(tmp_path):
    runtime = g._runtime(tmp_path, g._probe_services({}))
    runtime.start_run(g._probe_plan(), workflow_run_id="facts-probe", root_inputs=g._root_inputs())
    changed = {"study_facts": {"population": "different-synthetic", "phase": "III"}}
    with pytest.raises(GraphRunError):
        runtime.start_run(g._probe_plan(), workflow_run_id="facts-probe", root_inputs=changed)


def test_decision_content_hash_matches_actual_downstream_payload(tmp_path):
    runtime = g._runtime(tmp_path, g._probe_services({}))
    runtime.start_run(g._probe_plan(), workflow_run_id="hash-probe", root_inputs=g._root_inputs())
    runtime.run_to_completion("hash-probe")
    runtime.record_decision("hash-probe", node_id="lock_node", decision_id="choice",
                            actor_id="human", value={"approved": True}, reason="reviewed")
    results = [e.payload for e in runtime.read_events("hash-probe")
               if e.event_type == "graph_node_result" and e.payload["node_id"] == "lock_node"]
    assert results[0]["output_sha256"] == g._sha_of(results[0]["output"])


def test_reopen_final_result_without_completion_event_finishes_without_dispatch(tmp_path):
    runtime = g._runtime(tmp_path, g._probe_services({}))
    runtime.start_run(g._probe_plan(), workflow_run_id="final-probe", root_inputs=g._root_inputs())
    runtime.run_to_completion("final-probe")
    runtime.record_decision("final-probe", node_id="lock_node", decision_id="choice",
                            actor_id="human", value={"approved": True}, reason="reviewed")

    def crash_before_completion(*args):
        raise RuntimeError("synthetic interruption after durable final result")

    runtime._finish_run_if_complete = crash_before_completion
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        runtime.advance("final-probe")
    calls = {}
    reopened = g._runtime(tmp_path, g._probe_services(calls))
    result = reopened.advance("final-probe")
    assert calls == {}
    assert result.status.value == "completed"


def test_hash_only_legacy_receipt_call_returns_blocked_not_typeerror(tmp_path):
    def timeout(request):
        raise TimeoutError("synthetic unknown")

    runtime = g._runtime(tmp_path, {"draft_node": timeout})
    runtime.start_run(g._probe_plan(), workflow_run_id="receipt-probe", root_inputs=g._root_inputs())
    assert runtime.run_to_completion("receipt-probe").status.value == "blocked"
    snapshot = runtime.resolve_unknown_with_receipt(
        "receipt-probe", node_id="draft_node", output_sha256="a" * 64,
    )
    assert snapshot.status.value == "blocked"
    assert snapshot.stop_reason == "unknown_outcome_requires_payload_bearing_receipt"
