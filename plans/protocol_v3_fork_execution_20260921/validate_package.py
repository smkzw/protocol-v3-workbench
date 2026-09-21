"""Read-only handoff integrity check, not a product test suite."""
from pathlib import Path
import argparse
import hashlib
import json
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--workspace", type=Path, help="Optional checkout to compare source hashes")
args = parser.parse_args()
root = Path(__file__).resolve().parent
errors = []
warnings = []
def read(name):
    return json.loads((root / name).read_text())
def digest(data):
    return hashlib.sha256(data).hexdigest()
manifest = read("PACKAGE_MANIFEST.json")
for item in manifest["files"]:
    file = root / item["path"]
    if not file.is_file() or digest(file.read_bytes()) != item["sha256"]:
        errors.append("package hash mismatch: " + item["path"])
index = read("TASK_INDEX.json")
tasks = {task["id"]: task for task in index["tasks"]}
if set(tasks) != {f"F{i:02}" for i in range(14)}:
    errors.append("expected F00-F13")
seen = set()
def visit(key, ancestors):
    if key in ancestors:
        errors.append("dependency cycle: " + key)
        return
    if key not in tasks:
        errors.append("unknown dependency: " + key)
        return
    if key in seen:
        return
    for dependency in tasks[key]["depends_on"]:
        visit(dependency, ancestors | {key})
    seen.add(key)
for key, task in tasks.items():
    visit(key, set())
    for field in ("execution", "verification"):
        if not (root / task[field]).is_file():
            errors.append("missing task file: " + task[field])
covered = {criterion for task in tasks.values() for criterion in task["acceptance"]}
expected = {f"A{i:02}" for i in range(1, 27)} | {f"V{i:02}" for i in range(1, 9)}
if expected - covered:
    errors.append("missing criteria: " + str(sorted(expected - covered)))
state = read("SOURCE_STATE.json")
with tarfile.open(root / "source_overlay.tar.gz", "r:gz") as archive:
    expected_files = {item["path"]: item for item in state["overlay_files"]}
    if set(archive.getnames()) != set(expected_files):
        errors.append("overlay file inventory mismatch")
    for name, item in expected_files.items():
        member = archive.extractfile(name)
        if member is None or digest(member.read()) != item["sha256"]:
            errors.append("overlay hash mismatch: " + name)
if args.workspace:
    for item in state["overlay_files"]:
        file = args.workspace / item["path"]
        if not file.is_file() or digest(file.read_bytes()) != item["sha256"]:
            warnings.append("checkout drift; compare, do not overwrite: " + item["path"])
for item in read("AUTHORITY_MANIFEST.json")["files"]:
    file = Path(item["path"])
    if not file.is_file():
        warnings.append("external reference unavailable: " + str(file))
    elif digest(file.read_bytes()) != item["sha256"]:
        warnings.append("external source changed; re-anchor: " + str(file))
print(json.dumps({"package_ok": not errors, "tasks": len(tasks),
    "criteria": len(expected), "errors": errors, "warnings": warnings,
    "scope": "package integrity only; no product tests or product acceptance"},
    ensure_ascii=False, indent=2))
raise SystemExit(1 if errors else 0)
