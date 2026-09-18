"""Recovery concurrency uses real SQLite transactions and overlapping callers."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from test_graph_runtime import _runtime, _probe_plan, _root_inputs, _sha_of
from app.protocol_workflow.graph import GraphRunError


@pytest.mark.parametrize("identical", [False, True])
def test_overlapping_receipts_commit_one_result(tmp_path, identical):
    def timeout(request):
        raise TimeoutError("synthetic unknown")

    services = {n: timeout for n in ("draft_node", "review_node", "final_node")}
    setup = _runtime(tmp_path, services)
    setup.start_run(_probe_plan(), workflow_run_id="receipt-race", root_inputs=_root_inputs())
    assert setup.run_to_completion("receipt-race").status.value == "blocked"
    barrier = Barrier(2, timeout=10)

    def recover(index):
        runtime = _runtime(tmp_path, services)
        original = runtime._append_node_result

        def append(**kwargs):
            barrier.wait()
            return original(**kwargs)

        runtime._append_node_result = append
        payload = {"node": "draft_node", "value": 0 if identical else index}
        try:
            runtime.resolve_unknown_with_receipt(
                "receipt-race", node_id="draft_node", output=payload,
                output_sha256=_sha_of(payload),
            )
            return "ok"
        except GraphRunError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(recover, (0, 1)))
    assert sorted(outcomes) == (["ok", "ok"] if identical else ["graph_node_completed", "ok"])
    results = [e for e in setup.read_events("receipt-race")
               if e.event_type == "graph_node_result" and e.payload["node_id"] == "draft_node"]
    assert len(results) == 1
    attempts = setup.reservation_attempts("receipt-race", "draft_node")
    assert len(attempts) == 1
    assert attempts[0].output_sha256 == results[0].payload["output_sha256"]


@pytest.mark.parametrize("identical", [False, True])
def test_overlapping_starts_commit_one_binding(tmp_path, identical):
    setup = _runtime(tmp_path, {})
    barrier = Barrier(2, timeout=10)

    def start(index):
        runtime = _runtime(tmp_path, {})
        original = runtime._append_events_tx

        def append(*args, **kwargs):
            barrier.wait()
            return original(*args, **kwargs)

        runtime._append_events_tx = append
        roots = _root_inputs()
        if not identical:
            roots["study_facts"]["population"] = str(index)
        try:
            runtime.start_run(_probe_plan(), workflow_run_id="start-race", root_inputs=roots)
            return "ok"
        except GraphRunError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(start, (0, 1)))
    assert sorted(outcomes) == (["ok", "ok"] if identical else ["graph_run_binding_conflict", "ok"])
    assert sum(e.event_type == "graph_run_started" for e in setup.read_events("start-race")) == 1


def test_reused_receipt_checks_supplied_payload(tmp_path):
    def timeout(request):
        raise TimeoutError("synthetic unknown")

    runtime = _runtime(tmp_path, {"draft_node": timeout})
    runtime.start_run(_probe_plan(), workflow_run_id="reuse", root_inputs=_root_inputs())
    runtime.run_to_completion("reuse")
    payload = {"node": "draft_node", "value": "original"}
    runtime.resolve_unknown_with_receipt(
        "reuse", node_id="draft_node", output=payload, output_sha256=_sha_of(payload),
    )
    with pytest.raises(GraphRunError) as raised:
        runtime.resolve_unknown_with_receipt(
            "reuse", node_id="draft_node", output={"value": "different"},
            output_sha256=_sha_of(payload),
        )
    assert raised.value.code == "graph_receipt_hash_mismatch"
