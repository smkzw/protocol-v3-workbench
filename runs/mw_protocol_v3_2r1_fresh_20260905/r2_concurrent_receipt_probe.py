"""Round-2 probe B: two concurrent payload-bearing receipt recoveries with
DIFFERENT payloads. Both pass the blocked check (barrier), then both append.
Observe: how many result events land, loser error type, reservation state.
"""
import sys
import tempfile
import threading
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "protocol_v3"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
sys.path.insert(0, str(REPO_ROOT / "packages"))
sys.path.insert(0, str(REPO_ROOT))

import test_graph_runtime as g  # noqa: E402
from app.protocol_workflow.canonical.hashing import canonical_json  # noqa: E402
from app.protocol_workflow.graph import NodeServiceRequest  # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="mw2r1-r2receipt-"))


def _sha(p):
    return sha256(canonical_json(p).encode()).hexdigest()


def _timeout(request: NodeServiceRequest):
    raise TimeoutError("synthetic unknown")


setup = g._runtime(WORK, {n: _timeout for n in ("draft_node", "review_node", "final_node")})
plan = g._probe_plan()
run_id = "run-r2-receipt-1"
setup.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
assert setup.run_to_completion(run_id, plan=plan).status.value == "blocked"

PAY = {
    "A": {"node": "draft_node", "label": "recovered-by-a"},
    "B": {"node": "draft_node", "label": "recovered-by-b"},
}
barrier = threading.Barrier(2, timeout=30)
outcomes: dict = {}


def recover(role):
    rt = g._runtime(WORK, {n: _timeout for n in ("draft_node", "review_node", "final_node")})
    orig = rt._append_node_result

    def gated(**kwargs):
        barrier.wait()
        return orig(**kwargs)

    rt._append_node_result = gated
    try:
        snap = rt.resolve_unknown_with_receipt(
            run_id, node_id="draft_node",
            output=PAY[role], output_sha256=_sha(PAY[role]))
        outcomes[role] = f"ok:{snap.nodes[0].status.value}"
    except Exception as exc:  # noqa: BLE001
        outcomes[role] = f"{type(exc).__name__}:{getattr(exc, 'code', '')}"


tA = threading.Thread(target=recover, args=("A",))
tB = threading.Thread(target=recover, args=("B",))
tA.start()
tB.start()
tA.join(90)
tB.join(90)

events = setup.read_events(run_id)
results = [e for e in events if e.event_type == "graph_node_result"
           and e.payload.get("node_id") == "draft_node"]
print("outcomes:", outcomes)
print("n_draft_results:", len(results),
      [e.payload.get("output", {}).get("label") for e in results])
print("attempts:", [(a.attempt, a.status.value) for a in
                     setup.reservation_attempts(run_id, "draft_node")])
print("threads alive:", tA.is_alive(), tB.is_alive())
