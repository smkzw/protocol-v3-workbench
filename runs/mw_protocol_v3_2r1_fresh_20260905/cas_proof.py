"""Deterministic TOCTOU proof: force interleaving A.T1,B.T1,A.T2,B.T2 via
runtime-level wrappers (no product source edits). If record_decision had a
CAS, the loser would raise GraphDecisionConflictError; without it both record.
"""
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "protocol_v3"))
import test_graph_runtime as g  # noqa: E402

WORK = Path(sys.argv[1])
WORK.mkdir(parents=True, exist_ok=True)

executions: dict = {}
runtime = g._runtime(WORK, g._probe_services(executions))
plan = g._probe_plan()
run_id = "run-cas-proof-1"
runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
snap = runtime.run_to_completion(run_id, plan=plan)
assert snap.status.value == "awaiting_decision"

b_loaded = threading.Event()

orig_load = runtime._load
orig_append = runtime._append_events
roles: dict = {}


def patched_load(workflow_run_id, *, caller_plan=None):
    view = orig_load(workflow_run_id, caller_plan=caller_plan)
    if roles.get(threading.get_ident()) == "B":
        b_loaded.set()
    return view


def patched_append(workflow_run_id, specs):
    if roles.get(threading.get_ident()) == "A" and not getattr(patched_append, "fired", False):
        patched_append.fired = True
        assert b_loaded.wait(timeout=30), "B never finished its check-first load"
    return orig_append(workflow_run_id, specs)


runtime._load = patched_load
runtime._append_events = patched_append

outcomes = {}


def racer(role, decision_id, actor_id, approved):
    roles[threading.get_ident()] = role
    try:
        runtime.record_decision(
            run_id, node_id="lock_node", decision_id=decision_id,
            actor_id=actor_id, value={"approved": approved},
            reason=f"racer {role}")
        outcomes[role] = "recorded"
    except Exception as exc:  # noqa: BLE001
        outcomes[role] = f"{type(exc).__name__}:{getattr(exc, 'code', '')}"

# Start A first and wait until it is parked between its check (T1) and its
# append (T2); then start B so both checks observed "no decision".
tA = threading.Thread(target=racer, args=("A", "dec-aaa", "reviewer-aaa", True))
tB = threading.Thread(target=racer, args=("B", "dec-bbb", "reviewer-bbb", False))
tA.start()
for _ in range(300):
    if getattr(patched_append, "fired", False):
        break
    import time as _t
    _t.sleep(0.01)
assert getattr(patched_append, "fired", False), "A never reached its append"
tB.start()
tA.join(60)
tB.join(60)

events = runtime.read_events(run_id)
recorded = [e for e in events if e.event_type == "graph_decision_recorded"]
print("outcomes:", outcomes)
print("n_decision_recorded:", len(recorded),
      [e.payload.get("decision_id") for e in recorded])
print("threads alive:", tA.is_alive(), tB.is_alive())
