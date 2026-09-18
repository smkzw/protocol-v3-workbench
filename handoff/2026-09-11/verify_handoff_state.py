"""Read source evidence and write only this handoff directory; never import product code."""
from pathlib import Path
import hashlib, json, subprocess, datetime
HERE = Path(__file__).resolve().parent
W = HERE.parents[1]
def sha(p):
    h = hashlib.sha256()
    with Path(p).open("rb") as f:
        for block in iter(lambda:f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
def git(*args):
    return subprocess.check_output(["git", *args], cwd=W, text=True)
def inspect_record(r, relative=False):
    p = W / r["path"] if relative else Path(r["path"])
    actual = sha(p) if p.is_file() else None
    return {"path": str(p), "exists": p.is_file(), "sha256": actual,
            "expected_sha256": r.get("sha256"), "matches_pause": actual == r.get("sha256"),
            "size": p.stat().st_size if p.is_file() else None}
old = json.loads((W / "runs/mw_protocol_v3_no_loss_pause_20260908/snapshot_manifest.json").read_text())
closure = json.loads((W / "runs/mw_protocol_v3_no_loss_pause_20260908/pause_closure_manifest.json").read_text())
latest = {r["path"]: r for r in old["files"]}
latest.update({r["path"]: r for r in closure})
status = git("status", "--short", "--untracked-files=normal")
(HERE / "git_status_at_handoff.txt").write_text(status)
(HERE / "tracked_worktree_at_handoff.patch").write_text(git("diff", "--binary", "--no-ext-diff"))
goal = json.loads((HERE / "goal_snapshot.json").read_text())
(HERE / "GOAL_CURRENT_VERBATIM.txt").write_text(goal["objective"])
tpl = W / "config/medical_writing/protocol_v3/templates/tp_ma_07_v2"
fixture = json.loads((W / "tests/fixtures/protocol_v3/chapter_content_v2/batch1.json").read_text())
tasks = []
for p in sorted((W / ".trellis/tasks").glob("*/task.json")):
    d = json.loads(p.read_text())
    tasks.append({"path":str(p), "status":d.get("status"),"meta":d.get("meta")})
source_checks = [inspect_record(r,True) for r in latest.values()]
authorities = [inspect_record(r) for r in old["authorities"]]
raw_logs = [inspect_record(r) for r in old["raw_log_pointers"]]
report = {
    "checked_at":datetime.datetime.now().astimezone().isoformat(),
    "scope":"Read-only file, git, task and prior-evidence checks. No product tests, servers, models, workers, Word, browser or live runtime checks executed.",
    "workspace":str(W), "branch":git("branch","--show-current").strip(),
    "head":git("rev-parse","HEAD").strip(), "commit_count":int(git("rev-list","--count","HEAD")),
    "git_status_normal_lines":len(status.splitlines()),
    "tracked_modified_entries":sum(not s.startswith("??") for s in status.splitlines()),
    "untracked_normal_entries":sum(s.startswith("??") for s in status.splitlines()),
    "goal_status":goal["status"], "goal_utf8_sha256":sha(HERE/"GOAL_CURRENT_VERBATIM.txt"),
    "pause_original_snapshot_count":len(old["files"]),
    "pause_closure_count":len(closure), "reconciled_unique_count":len(latest),
    "source_changes":[r for r in source_checks if not r["matches_pause"]],
    "source_checks":source_checks, "authority_checks":authorities, "raw_log_checks":raw_logs,
    "final_runner_reports_present":{p:(W/p).exists() for p in old["final_reports_present"]},
    "chapter_contract_count":len(list((tpl/"chapter_contracts").glob("*.json"))),
    "chapter_skill_count":len(list((tpl/"chapter_skills").glob("*.json"))),
    "fixture_shape": list(fixture) if isinstance(fixture,dict) else "list",
    "batch1_fixture_count":len(fixture.get("fixtures",[])) if isinstance(fixture,dict) else len(fixture),
    "batch2_fixture_present":(W/"tests/fixtures/protocol_v3/chapter_content_v2/batch2.json").exists(),
    "tasks":tasks,
    "limitations":["Pause snapshot covers selected files, not the entire repository or every external document.",
                   "Historical test totals are not rerun results for 2026-09-11.",
                   "Raw private logs are only hashed in place; their contents are not copied."]
}
(HERE/"current_state_verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print(json.dumps({k:report[k] for k in ("checked_at","head","commit_count","tracked_modified_entries","untracked_normal_entries","reconciled_unique_count","source_changes","goal_status","chapter_contract_count","chapter_skill_count","batch1_fixture_count","fixture_shape","final_runner_reports_present")},ensure_ascii=False,indent=2))
print("authority mismatches",json.dumps([r for r in authorities if not r["matches_pause"]],ensure_ascii=False))
print("raw log mismatches",json.dumps([r for r in raw_logs if not r["matches_pause"]],ensure_ascii=False))
