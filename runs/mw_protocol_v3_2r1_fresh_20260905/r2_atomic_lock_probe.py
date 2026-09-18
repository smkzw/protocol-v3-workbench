"""Round-2 probe A: prove the decision guard+insert share one atomic tx.

Parks writer A INSIDE its append transaction (after the guard passed, between
event build and row insert) while holding the SQLite write lock; writer B must
make NO progress until A commits, then must fail with the TYPED conflict and
exactly one decision event must exist.
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "protocol_v3"))
sys.path.insert(0, str(REPO_ROOT / "services" / "api"))
sys.path.insert(0, str(REPO_ROOT / "packages"))
sys.path.insert(0, str(REPO_ROOT))

import test_graph_runtime as g  # noqa: E402
from app.protocol_workflow.events.models import EventEnvelopeBuilder  # noqa: E402
from app.protocol_workflow.graph.state import GraphDecisionConflictError  # noqa: E402

WORK = Path(tempfile.mkdtemp(prefix="mw2r1-r2atom-"))

setup = g._runtime(WORK, g._probe_services({}))
plan = g._probe_plan()
run_id = "run-r2-atomic-1"
setup.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
assert setup.run_to_completion(run_id, plan=plan).status.value == "awaiting_decision"

parked = threading.Event()
release = threading.Event()
orig_build = EventEnvelopeBuilder.build
state = {"a_builds": 0}


def counting_build(self, **kwargs):
    # Only writer A's tx is armed (see roles); park after its 2nd event build,
    # i.e. after the guard passed and inside the write tx, before row insert.
    if roles.get(threading.get_ident()) == "A":
        state["a_builds"] += 1
        if state["a_builds"] == 2:
            parked.set()
            assert release.wait(timeout=30), "never released"
    return orig_build(self, **kwargs)


EventEnvelopeBuilder.build = counting_build

roles: dict = {}
outcomes: dict = {}
b_finished_while_parked = {"value": None}


def racer(role, decision_id, actor_id, approved):
    roles[threading.get_ident()] = role
    rt = g._runtime(WORK, g._probe_services({}))
    try:
        rt.record_decision(
            run_id, node_id="lock_node", decision_id=decision_id,
            actor_id=actor_id, value={"approved": approved},
            reason=f"racer {role}")
        outcomes[role] = "recorded"
    except GraphDecisionConflictError:
        outcomes[role] = "conflict"
    except Exception as exc:  # noqa: BLE001
        outcomes[role] = f"RAW:{type(exc).__name__}"


tA = threading.Thread(target=racer, args=("A", "dec-aaa", "reviewer-aaa", True))
tA.start()
assert parked.wait(timeout=30), "A never parked inside its tx"
tB = threading.Thread(target=racer, args=("B", "dec-bbb", "reviewer-bbb", False))
tB.start()
time.sleep(2.0)  # busy_timeout is 5s: B must still be blocked, not finished
b_finished_while_parked["value"] = not tB.is_alive()
release.set()
tA.join(60)
tB.join(60)

events = setup.read_events(run_id)
recorded = [e for e in events if e.event_type == "graph_decision_recorded"]
print("B finished while A parked (want False):", b_finished_while_parked["value"])
print("outcomes (want A=recorded B=conflict):", outcomes)
print("n_decision_recorded (want 1):", len(recorded),
      [e.payload.get("decision_id") for e in recorded])
assert b_finished_while_parked["value"] is False, "B progressed while A held the tx"
assert outcomes == {"A": "recorded", "B": "conflict"}, outcomes
assert len(recorded) == 1 and recorded[0].payload.get("decision_id") == "dec-aaa"
print("PROBE-A PASS")
