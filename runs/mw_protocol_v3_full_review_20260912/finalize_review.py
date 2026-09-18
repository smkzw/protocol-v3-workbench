"""Close this review's evidence only. No product/test/source writes."""
from __future__ import annotations
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree

W = Path(__file__).resolve().parents[2]
R = Path(__file__).resolve().parent
G = Path("/Users/smkzw/.codex/tools/hermes_workflow_guard.py")
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
def run(args, destination):
    result = subprocess.run(args, cwd=W, capture_output=True, text=True)
    (R / destination).write_text(result.stdout + result.stderr)
    return {"returncode": result.returncode, "evidence": str((R / destination).relative_to(W))}

errors = []
before = json.loads((R / "source_inventory_before.json").read_text())
changed, after = [], []
for item in before:
    p = W / item["path"]
    actual = {"path": item["path"], "bytes": p.stat().st_size if p.exists() else None,
              "sha256": digest(p) if p.exists() else None}
    after.append(actual)
    if actual != item:
        changed.append({"before": item, "after": actual})
dump(R / "source_inventory_after.json", after)
if changed:
    errors.append("protected source inventory changed")
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=W, text=True).strip()
if head != "84488d307eae240cc48808dea506691091817354":
    errors.append("HEAD changed during review")
git_after = subprocess.check_output(["git", "status", "--short"], cwd=W, text=True)
(R / "git_status_after.txt").write_text(git_after)
git_before = set((R / "git_status_before.txt").read_text().splitlines())
added_status = sorted(set(git_after.splitlines()) - git_before)
removed_status = sorted(git_before - set(git_after.splitlines()))
source_prefixes = ("services/", "frontend/", "packages/", "config/", "tests/", "scripts/")
new_source_status = [line for line in added_status if line[3:].strip('"').startswith(source_prefixes)]
if new_source_status:
    errors.append("new product/source status outside review scope")

authorities = {
 "../plan-upgrade-20260905/mw_protocol_v3_design_v1.3_20260905.md":
 "d97a0d3de6f4a5cf3ed9b8c17d43e35895c04910605605be9f668aba0f80efc5",
 "../plan-upgrade-20260905/mw_protocol_v3_implementation_plan_v2_20260905.md":
 "040eb6ad323047737e8be6a3a23344fdb719dc85230ef7994b96c9af29257607",
 "../plan-upgrade-20260905/mw_protocol_v3_execution_handoff_20260905.md":
 "ab5136d65bedf28f81d6c64405f71130986fa415f0e1dbc7b7e7b793a149e200",
 ".hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md":
 "fa99fbd38588a5d3a8f35d3936c3e84c26cfd4a9eea58d8aa739e93363d54914",
 "/Users/smkzw/Documents/康哲项目资料/SOP/SOP For AI/TP-MA-07 临床试验方案（2期或3期）_清洁版_v2.0_20260905.docx":
 "018d28d37b3e58ee97f41414371b78fc9251cbe0942f0b8baa875948bb143756",
}
authority_results = []
for p, expected in authorities.items():
    path = W / p
    sha = digest(path) if path.exists() else None
    authority_results.append({"path": str(path.resolve()), "sha256": sha, "expected_sha256": expected, "matches": sha == expected})
    if sha != expected:
        errors.append(f"authority mismatch: {p}")
snapshot_results = []
for item in json.loads((R / "plan_review_snapshot/manifest.json").read_text()):
    sha = digest(W / item["snapshot"])
    snapshot_results.append({**item, "current_snapshot_sha256": sha, "unchanged": sha == item["sha256"]})
    if sha != item["sha256"]:
        errors.append("frozen reviewer snapshot changed")

execution_check = run([sys.executable, str(G), "audit-execution", "--task-id",
 "mw_protocol_v3_full_review_20260912", "--task-type", "finite_code_task", "--workspace", "."], "execution_audit.json")
if execution_check["returncode"]:
    errors.append("execution audit failed")
gate_results = []
for kind, task in [("execution", "mw_protocol_v3_full_review_20260912"), ("conference", "mw_protocol_v3_replan_review_20260912")]:
    result = run([sys.executable, str(G), "review-gate", "--review", f"reviews/codex_{kind}_{task}_review.md",
                  "--metrics", f"metrics/{task}_{kind}_metrics.md", "--require-verification"], kind + "_review_gate.json")
    gate_results.append(result)
    if result["returncode"]:
        errors.append(kind + " review-gate failed")
sys.path.insert(0, str(G.parent))
import hermes_workflow_guard as guard
task = "mw_protocol_v3_replan_review_20260912"
route_manifest = json.loads((W / f"context/{task}_general_single_object_route_manifest.json").read_text())
declared = {**route_manifest["variants"][route_manifest["packet_period"]], "schedule_variants": route_manifest["variants"]}
conference_errors = guard.audit_runner_receipt(
 W / f"runs/conference/{task}/general_single_object.md",
 W / f"logs/conference/{task}/general_single_object_stdout.txt", declared)
if conference_errors:
    errors.extend(conference_errors)
dump(R / "conference_receipt_audit.json", {"errors": conference_errors, "ok": not conference_errors,
 "scope": "receipt identity, terminal state and report bytes; not independent scientific/product acceptance"})
receipt_results = []
for kind, task, role in [
 ("execution", "mw_protocol_v3_full_review_20260912", "worker_01"),
 ("execution", "mw_protocol_v3_full_review_20260912", "worker_02"),
 ("conference", "mw_protocol_v3_replan_review_20260912", "general_single_object")]:
    lp = W / f"logs/{kind}/{task}/{role}_stdout.txt"
    j = json.loads(lp.read_text())
    final = j["rounds"][-1]
    report = W / f"runs/{kind}/{task}/{role}.md"
    result = {"role": role, "report": str(report.relative_to(W)), "report_sha256": digest(report),
      "receipt": str(lp.relative_to(W)), "receipt_sha256": digest(lp),
      "bound": digest(report) == j.get("output_sha256"), "returncode": final.get("returncode"),
      "stop_reason": final.get("stop_reason"), "session_id": final.get("session_id"),
      "actual_round_provider": final.get("provider"), "actual_round_model": final.get("model"),
      "requested_effort": final.get("requested_effort") or final.get("zcode_effort_requested"),
      "observed_effort": (final.get("zcode_runtime_identity") or {}).get("observed_effort"),
      "duration_seconds": final.get("duration_seconds"), "recorded_tools": final.get("tool_call_count"),
      "runtime_identity": final.get("runtime_identity") or final.get("zcode_runtime_identity")}
    receipt_results.append(result)
    if not result["bound"] or result["returncode"] != 0:
        errors.append("unbound or failed required report: " + role)
dump(R / "runtime_receipt_summary.json", receipt_results)

docs = [
 "reviews/mw_protocol_v3_full_review_20260912.md",
 "reviews/mw_protocol_v3_component_map_20260912.md",
 "plans/mw_protocol_v3_design_v1.4_20260912.md",
 "plans/mw_protocol_v3_implementation_plan_v3_20260912.md",
 "plans/mw_protocol_v3_goal_prompt_20260912.txt",
 "plans/mw_protocol_v3_execution_tracking_20260905.md",
 "plans/codex_execution_mw_protocol_v3_full_review_20260912.md",
 "plans/codex_main_venue_mw_protocol_v3_replan_review_20260912.md",
 "reviews/codex_execution_mw_protocol_v3_full_review_20260912_review.md",
 "reviews/codex_conference_mw_protocol_v3_replan_review_20260912_review.md",
 "metrics/mw_protocol_v3_full_review_20260912_execution_metrics.md",
 "metrics/mw_protocol_v3_replan_review_20260912_conference_metrics.md",
 ".trellis/tasks/09-11-protocol-v3-3r4/task.json",
 ".trellis/tasks/09-11-protocol-v3-3r4/checkpoint.md",
 ".trellis/tasks/09-11-protocol-v3-3r4/prd.md",
 ".trellis/tasks/09-12-protocol-v3-review-replan/task.json",
 ".trellis/tasks/09-12-protocol-v3-review-replan/checkpoint.md",
]
link_errors, checked_links = [], 0
for d in docs:
    p = W / d
    if not p.exists():
        errors.append("missing deliverable: " + d)
        continue
    if p.suffix == ".md":
        for href in re.findall(r"\]\(([^\n]+?)\)", p.read_text()):
            href = href.strip("<>")
            if href.startswith(("http:", "https:", "#")):
                continue
            href = re.sub(r":\d+$", "", unquote(href.split("#")[0]))
            target = Path(href) if href.startswith("/") else p.parent / href
            checked_links += 1
            if not target.exists():
                link_errors.append({"document": d, "target": href})
if link_errors:
    errors.append("broken local Markdown links")

parent = json.loads((W / ".trellis/tasks/09-11-protocol-v3-3r4/task.json").read_text())
if parent["assignee"] != "codex" or not parent["meta"]["user_paused"] or parent.get("completedAt"):
    errors.append("parent must remain owner=codex, paused and unaccepted")
test_suites = ElementTree.parse(R / "protocol_v3_baseline.xml").getroot()
tests = list(test_suites.iter("testcase"))
pytest_summary = {"tests": len(tests), "failures": len(list(test_suites.iter("failure"))),
 "errors": len(list(test_suites.iter("error"))), "skipped": len(list(test_suites.iter("skipped")))}
vitest = json.loads((R / "frontend_vitest.json").read_text())
test_results = {"pytest": pytest_summary,
 "vitest": {"passed": vitest.get("numPassedTests"), "failed": vitest.get("numFailedTests")},
 "node": {"evidence": "runs/mw_protocol_v3_full_review_20260912/frontend_durable_node.log"}}
if pytest_summary != {"tests": 1860, "failures": 0, "errors": 0, "skipped": 0} or vitest.get("numPassedTests") != 18:
    errors.append("test report summary mismatch")

result = {"completed_at": datetime.now().astimezone().isoformat(), "scope": "engineering review and documentation only",
 "head": head, "protected_source_files": len(before), "protected_source_changes": changed,
 "new_source_status": new_source_status, "git_status_added": added_status, "git_status_removed": removed_status,
 "authority_hashes": authority_results, "frozen_snapshot_hashes": snapshot_results,
 "execution_audit": execution_check, "review_gates": gate_results, "conference_receipt_errors": conference_errors,
 "required_runners": receipt_results, "tests": test_results, "local_markdown_links_checked": checked_links,
 "broken_local_links": link_errors, "parent_task_user_paused": parent["meta"]["user_paused"],
 "goal_state_last_observed": "paused", "goal_objective_changed_by_this_task": False,
 "original_goal_file_sha256": digest(R / "GOAL_BEFORE_VERBATIM.txt"),
 "unperformed": ["full browser E2E", "real product model generation", "OCR/translation", "native Word", "clinical sign-off", "live cutover"],
 "limitations": ["Backend runner top-level/fallback-label telemetry contradiction unresolved",
 "Frontend tool telemetry does not prove every claimed read",
 "Fresh review has context but not model independence from backend fallback",
 "Map covers whole module scope, not every line or every clinical design"],
 "errors": errors}
if not errors:
    taskp = W / ".trellis/tasks/09-12-protocol-v3-review-replan/task.json"
    taskj = json.loads(taskp.read_text())
    taskj["status"] = "completed"
    taskj["completedAt"] = result["completed_at"]
    taskj["meta"].update({"product_implementation_resumed": False, "acceptance_scope": "review_and_document_revision_only",
       "evidence": "runs/mw_protocol_v3_full_review_20260912/final_verification.json",
       "next_product_task": ".trellis/tasks/09-11-protocol-v3-3r4/task.json"})
    dump(taskp, taskj)
    cp = W / ".trellis/tasks/09-12-protocol-v3-review-replan/checkpoint.md"
    text = cp.read_text().replace("- [ ]", "- [x]")
    text += """

## 本轮交付结案（产品暂停保持）
审阅/设计/Plan/Goal文档完成，用户已选择完整可用路径优先。父3R.4仍未验收且user_paused。
源码771文件hash保持、权威模板/旧批准文档hash保持；1860v3、18frontend、1Node及定向反例有证据。
两worker+fresh设计review已终态，具体意见由Codex按源码裁定；runner标签矛盾及同模型独立性限制见owner review。
已更新设计v1.4/Planv3/Goal文本与Trellis3R.4PRD/当前索引；旧Goal原文保存，原生Goal仍paused未改objective。
最终证据runs/mw_protocol_v3_full_review_20260912/final_verification.json。保留历史，无产品源码/原测试修改，无服务或产品调用，无清理。
下一实施动作：用户恢复后先重锚当前树，再3R.4A→B→C→D，进入Ⅱ/Ⅲ期V1完整路径；不要重派旧fresh或从1R.2开始。
"""
    cp.write_text(text)
result["deliverable_hashes"] = [
 {"path": p, "sha256": digest(W / p), "bytes": (W / p).stat().st_size} for p in docs if (W / p).exists()]
dump(R / "final_verification.json", result)
print(json.dumps({"ok": not errors, "errors": errors, "protected_source_files": len(before),
 "protected_source_changes": len(changed), "head": head, "tests": test_results,
 "local_links_checked": checked_links, "broken_local_links": link_errors,
 "required_runners": len(receipt_results), "product_paused": parent["meta"]["user_paused"]}, ensure_ascii=False, indent=2))
raise SystemExit(0 if not errors else 1)
