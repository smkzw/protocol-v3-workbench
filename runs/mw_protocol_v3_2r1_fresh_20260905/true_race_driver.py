"""True-overlap decision race driver (fresh review evidence, read-only vs product).

Spawns two record_decision racers CONCURRENTLY (Popen) against a paused run,
unlike tests/protocol_v3/test_graph_runtime_recovery.py::TestConcurrentDecision
which spawns them sequentially (list comprehension over blocking subprocess.run).
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "protocol_v3"))

import test_graph_runtime as g  # noqa: E402

WORK = Path(sys.argv[1])
WORK.mkdir(parents=True, exist_ok=True)
MODE = sys.argv[2]  # "conflict" or "duplicate"

executions: dict = {}
runtime = g._runtime(WORK, g._probe_services(executions))
plan = g._probe_plan()
run_id = f"run-true-race-{MODE}"
runtime.start_run(plan, workflow_run_id=run_id, root_inputs=g._root_inputs())
snap = runtime.run_to_completion(run_id, plan=plan)
assert snap.status.value == "awaiting_decision", snap.status

markers = [str(WORK / f"racer-{i}.marker") for i in range(2)]
for m in markers:
    try:
        Path(m).unlink()
    except FileNotFoundError:
        pass

env = {
    "PATH": "/Users/smkzw/.local/bin:/opt/homebrew/bin:/usr/bin:/bin",
    "HOME": "/Users/smkzw",
    "LANG": "en_US.UTF-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONNOUSERSITE": "1",
    "PYTHONPATH": ":".join([
        str(REPO_ROOT / "tests" / "protocol_v3"),
        str(REPO_ROOT / "services" / "api"),
        str(REPO_ROOT / "packages"),
        str(REPO_ROOT),
    ]),
    "WORKBENCH_RUNTIME_DIR": str(WORK),
}
script = (
    "import sys; sys.path.insert(0, {tests!r}); "
    "import test_graph_runtime_recovery as m; "
    "m.child_main(sys.argv[1])".format(tests=str(REPO_ROOT / "tests" / "protocol_v3"))
)

procs = []
for index in range(2):
    if MODE == "duplicate":
        dec, actor, approved = "dec-same", "reviewer-same", True
    else:
        dec, actor, approved = f"dec-racer-{index}", f"reviewer-{index}", index == 0
    payload = {
        "work_dir": str(WORK),
        "evidence_path": str(WORK / f"racer-{index}.json"),
        "run_id": run_id,
        "mode": "record_decision_race",
        "target": "lock_node",
        "barrier_markers": markers,
        "racer_index": index,
        "decision_id": dec,
        "actor_id": actor,
        "approved": approved,
    }
    procs.append(subprocess.Popen(
        [sys.executable, "-c", script, json.dumps(payload)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
        cwd=str(REPO_ROOT),
    ))
outs = [p.communicate(timeout=120) for p in procs]
codes = [p.returncode for p in procs]

evidence = []
for index in range(2):
    p = WORK / f"racer-{index}.json"
    evidence.append(json.loads(p.read_text()) if p.exists() else {"outcome": "NO_EVIDENCE"})

events = runtime.read_events(run_id)
recorded = [e for e in events if e.event_type == "graph_decision_recorded"]
results = [e for e in events if e.event_type == "graph_node_result"
           and e.payload.get("node_id") == "lock_node"]

print(json.dumps({
    "mode": MODE,
    "returncodes": codes,
    "outcomes": [e.get("outcome") for e in evidence],
    "errors": [e.get("error") for e in evidence],
    "n_decision_recorded": len(recorded),
    "n_lock_results": len(results),
    "decision_ids": [e.payload.get("decision_id") for e in recorded],
    "stderrs": [o[1][-2000:] for o in outs],
}, indent=1, sort_keys=True))
