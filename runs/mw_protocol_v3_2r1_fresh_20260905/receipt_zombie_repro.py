"""Receipt-adoption zombie repro: unknown -> receipt hash -> downstream usability."""
import sys
from hashlib import sha256
from pathlib import Path

from app.protocol_workflow.canonical.hashing import canonical_json  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "protocol_v3"))
import test_graph_runtime as g  # noqa: E402
from app.protocol_workflow.graph import NodeServiceRequest  # noqa: E402

WORK = Path(sys.argv[1])
WORK.mkdir(parents=True, exist_ok=True)


def _sha(payload):
    return sha256(canonical_json(payload).encode()).hexdigest()


executions: dict = {}


def _timeout(request: NodeServiceRequest):
    executions[request.node.node_id] = executions.get(request.node.node_id, 0) + 1
    raise TimeoutError("synthetic dispatch timeout")


services = {n: _timeout for n in ("draft_node", "review_node", "final_node")}
runtime = g._runtime(WORK, services)
plan = g._probe_plan()
run_id = "run-receipt-zombie-1"
runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
blocked = runtime.run_to_completion(run_id, plan=plan)
print("blocked:", blocked.status.value)

fake_sha = _sha({"recovered": True})
recovered = runtime.resolve_unknown_with_receipt(
    run_id, node_id="draft_node", output_sha256=fake_sha)
print("draft after receipt:", recovered.nodes[0].status.value,
      "sha:", recovered.nodes[0].output_sha256)
print("result events for draft:",
      sum(1 for e in runtime.read_events(run_id)
          if e.event_type == "graph_node_result" and e.payload.get("node_id") == "draft_node"))

try:
    nxt = runtime.advance(run_id, plan=plan)
    print("advance ok:", nxt.status.value,
          {n.node_id: n.status.value for n in nxt.nodes})
except Exception as exc:
    print("advance RAISED:", type(exc).__name__, getattr(exc, "code", None), str(exc)[:220])
