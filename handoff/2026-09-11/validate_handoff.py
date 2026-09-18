"""Validate this handoff artifact; does not execute or import the product."""
from pathlib import Path
import json, re, hashlib, subprocess, datetime
HERE=Path(__file__).resolve().parent
W=HERE.parents[1]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=HERE/"artifact_manifest.json"
validation=HERE/"document_validation.json"
# Reserve only the two self-referenced package entries before link validation.
for p in (manifest,validation):
    if not p.exists(): p.write_text("{}\n")
main=HERE/"HANDOFF_PROTOCOL_V3_20260911.md"
text=main.read_text()
goal=json.loads((HERE/"goal_snapshot.json").read_text())
embedded=text.split("## 15. 当前原生 Goal 原文（逐字保留）",1)[1].split("~~~text\n",1)[1].split("\n~~~",1)[0]
missing=[];links=set()
for p in (main,HERE/"SOURCE_COMPONENT_INDEX.md"):
    for target in re.findall(r"\]\(<([^>]+)>\)",p.read_text()):
        if target.startswith("/"):
            links.add(str(Path(target).resolve()))
            if not Path(target).exists():missing.append(target)
state=json.loads((HERE/"current_state_verification.json").read_text())
source_changes=[]
for r in state["source_checks"]+state["authority_checks"]:
    p=Path(r["path"])
    if not p.is_file() or sha(p)!=r["sha256"]:source_changes.append(str(p))
inventory=json.loads((HERE/"source_component_inventory.json").read_text())
inventory_changes=[r["path"] for r in inventory if not Path(r["path"]).exists() or sha(Path(r["path"]))!=r["sha256"]]
current_status=subprocess.check_output(["git","status","--short","--untracked-files=normal"],cwd=W,text=True)
start_status=(HERE/"git_status_at_handoff.txt").read_text()
status_unchanged=current_status==start_status
report={
 "validated_at":datetime.datetime.now().astimezone().isoformat(),
 "scope":"Handoff document/link/goal/file checks only; no new product test or acceptance.",
 "main_document_lines":len(text.splitlines()),
 "local_link_target_count":len(links),
 "missing_local_link_targets":sorted(set(missing)),
 "goal_matches_api_snapshot_verbatim":embedded==goal["objective"],
 "goal_plaintext_matches_api_snapshot_verbatim":(HERE/"GOAL_CURRENT_VERBATIM.txt").read_text()==goal["objective"],
 "captured_goal_status":goal["status"],
 "all_numbered_sections_0_to_16_present":all(re.search(rf"^## {i}\. ",text,re.M) for i in range(17)),
 "unresolved_template_tokens":re.findall(r"\[\[[^\]]+\]\]|WROOT",text),
 "source_or_authority_changes_during_handoff":source_changes,
 "component_inventory_changes_during_handoff":inventory_changes,
 "git_status_unchanged_since_handoff_capture":status_unchanged,
 "known_recovery_limitation":"Two original ZCode model-io files absent as of 2026-09-11; native session metadata exists, continuation completeness unverified.",
 "not_performed":["Product tests","Models or agents","Services","Live runtime health","Browser E2E","Native Word","Resume/cutover"]
}
report["artifact_validation_passed"]=all((
 not missing,report["goal_matches_api_snapshot_verbatim"],
 report["goal_plaintext_matches_api_snapshot_verbatim"],
 report["all_numbered_sections_0_to_16_present"],
 not report["unresolved_template_tokens"],not source_changes,
 not inventory_changes,status_unchanged,goal["status"]=="paused"
))
validation.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
entries=[{"path":p.name,"bytes":p.stat().st_size,"sha256":sha(p)} for p in sorted(HERE.iterdir()) if p.is_file() and p!=manifest]
manifest.write_text(json.dumps({"created_at":report["validated_at"],"scope":"This handoff package; excludes its own manifest to avoid recursive hashing. Original source files and private session logs are not copied.","files":entries},ensure_ascii=False,indent=2)+"\n")
hash_ok=all(sha(HERE/r["path"])==r["sha256"] for r in entries)
print(json.dumps({"validation":report,"package_files":len(entries)+1,"package_hashes_match":hash_ok},ensure_ascii=False,indent=2))
if not report["artifact_validation_passed"] or not hash_ok: raise SystemExit(1)
