"""Verbatim function excerpts from run_acceptance_gate.py at 5b4c8c1.
Only dependency imports/module constants are provided as harness scaffolding.
This is not the full upstream module and does not run the product suite.
Source ranges: 39-90, 123-159, 214-252, 315-339, 395-495.
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path
_ROOT_DISCOVERY_NOTE = None
_SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist",
              ".pytest_cache", "runs"}
HARD_FAIL_EXIT_CODES = {2: "interrupted_or_collection", 3: "internal_error",
                        4: "usage_error", 5: "no_tests_collected"}

def discover_repo_root(root: Path) -> Path:
    """Accept a project/parent dir as --root: if it is not itself a gate tree,
    locate the unique tools/acceptance/required_nodes.json below it."""
    global _ROOT_DISCOVERY_NOTE
    if (root / "tools/acceptance/required_nodes.json").is_file():
        _ROOT_DISCOVERY_NOTE = None
        return root
    candidates: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > 4:
            return
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_dir() or entry.name in _SKIP_DIRS:
                continue
            if (entry / "tools/acceptance/required_nodes.json").is_file():
                candidates.append(entry)
            else:
                walk(entry, depth + 1)

    walk(root, 1)
    if not candidates:
        _ROOT_DISCOVERY_NOTE = "no tools/acceptance/required_nodes.json under root; gate files missing"
        return root
    if len(candidates) == 1:
        _ROOT_DISCOVERY_NOTE = f"discovered repo root below --root: {candidates[0].name}"
        return candidates[0]
    _ROOT_DISCOVERY_NOTE = (
        f"multiple candidate repo roots, chose lexicographically first: "
        f"{[str(c) for c in candidates]}")
    return sorted(candidates)[0]


def run_pytest(root: Path, junit_path: Path, timeout: int, pytest_args: list[str]) -> dict:
    cmd = [
        sys.executable, "-m", "pytest", *pytest_args, "-q",
        "-p", "no:cacheprovider", "--continue-on-collection-errors",
        f"--junitxml={junit_path}",
    ]
    # Team-documented backend test convention (HANDOFF R11/R15):
    # PYTHONPATH=services/api:. relative to the tree under test.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": f"services/api{os.pathsep}."}
    started = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(root), capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "elapsed": round(time.time() - started, 1),
            "timeout": False,
        }
    except subprocess.TimeoutExpired:
        return {
            "returncode": None, "stdout": "", "stderr": "",
            "elapsed": round(time.time() - started, 1), "timeout": True,
        }


def run_pyflakes(root: Path) -> dict:
    target = root / "services" / "api" / "app"
    if not target.is_dir():
        return {"ok": False, "reason": "target_missing"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pyflakes", str(target)],
            capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError:
        return {"ok": False, "reason": "pyflakes_not_installed"}
    findings, ignored = [], {}
    for line in (proc.stdout or "").splitlines():
        m = re.match(r"^(.+?):(\d+):(\d+):\s*(.+)$", line)
        if not m:
            continue
        path, lineno, col, message = m.group(1), m.group(2), m.group(3), m.group(4)
        if message.startswith("undefined name"):
            name = message.split("'", 1)[1].rstrip("'") if "'" in message else message
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            findings.append({"location": f"{rel}:{lineno}:{col}", "name": name})
        else:
            key = _pyflakes_category(message)
            ignored[key] = ignored.get(key, 0) + 1
    return {"ok": True, "undefined_name": findings,
            "ignored_counted_by_category": ignored}


def run_eslint(root: Path) -> dict:
    frontend = root / "frontend"
    bin_path = frontend / "node_modules" / ".bin" / "eslint"
    if not bin_path.exists():
        return {"ok": False, "reason": "eslint_not_installed"}
    proc = subprocess.run(
        [str(bin_path), "src", "--config", "eslint.config.mjs", "--format", "json"],
        cwd=str(frontend), capture_output=True, text=True, timeout=600,
    )
    findings = []
    try:
        reports = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return {"ok": True, "returncode": proc.returncode, "noundef": [],
                "parse_error": (proc.stdout or proc.stderr or "")[:400]}
    for file_report in reports:
        for message in file_report.get("messages", []):
            if message.get("ruleId") == "no-undef":
                rel = os.path.relpath(file_report.get("filePath", ""), frontend)
                findings.append(
                    f"{rel}: line {message.get('line')}, col {message.get('column')}, "
                    f"{message.get('message')}"
                )
    return {"ok": True, "returncode": proc.returncode, "noundef": findings}


def evaluate_report_against_baseline(report: dict, baseline: dict | None,
                                     head_sha: str | None,
                                     required_nodes: list[str],
                                     allow_missing_required: bool,
                                     reasons: list[str]) -> dict:
    """Shared FAIL/KNOWN/PASS decision for a parsed pytest report."""
    result = {
        "ran": report.get("total", 0) if report.get("ok") else 0,
        "failed_ids": [],
        "known_matched": [],
        "dissolved": [],
        "suspected_data_class": [],
        "suspected_fingerprint_drift": [],
        "missing_required_nodes": [],
    }
    if not report.get("ok"):
        result["verdict"] = "FAIL"
        reasons.append(str(report.get("reason")))
        return result

    returncode = report.get("returncode")
    hard = HARD_FAIL_EXIT_CODES.get(returncode)
    if hard:
        reasons.append(f"pytest_exit_{returncode}_{hard}")
        result["verdict"] = "FAIL"
        return result

    all_bad = report["failures"] + report["errors"]
    baseline_failures = (baseline or {}).get("pytest_failures") or []
    baseline_usable = bool(
        baseline
        and baseline.get("format") != "UNREADABLE"
        and baseline.get("baseline_sha") == head_sha
    )
    if baseline and not baseline_usable:
        reasons.append("baseline_not_bound_to_current_head")
    baseline_map = {entry["nodeid"]: entry for entry in baseline_failures}
    messages = {rec["nodeid"]: rec["message"] for rec in all_bad}
    for rec in all_bad:
        entry = baseline_map.get(rec["nodeid"])
        if baseline_usable and entry and entry.get("fingerprint") == rec["fingerprint"]:
            result["known_matched"].append(rec["nodeid"])
        else:
            result["failed_ids"].append(rec["nodeid"])
            if "isolated_runtime" in messages.get(rec["nodeid"], ""):
                result["suspected_data_class"].append(rec["nodeid"])
            elif rec["nodeid"] in baseline_map:
                # same test failing on both sides with different fingerprints:
                # environment-content-brittle output, needs human classification
                result["suspected_fingerprint_drift"].append(rec["nodeid"])
    failing_nodes = {r["nodeid"] for r in all_bad}
    executed = set(report["cases"])
    # dissolved = baseline failures that RAN and passed this time; baseline
    # entries outside this run are counted, never claimed as dissolved.
    result["dissolved"] = sorted(
        n for n in (set(baseline_map) - failing_nodes) if n in executed)
    result["baseline_not_run_count"] = len([
        n for n in baseline_map if n not in executed])

    # Match on (module path, test leaf); unittest class segments on either
    # side are ignored and parametrize brackets tolerated.
    def _case_key(nodeid: str) -> tuple[str, str]:
        parts = nodeid.split("::")
        module = parts[0]
        if module.endswith(".py"):
            module = module[:-3]
        return module.replace("/", "."), parts[-1].split("[")[0]

    reported = {_case_key(c) for c in report["cases"]}
    result["missing_required_nodes"] = [
        n for n in required_nodes if _case_key(n) not in reported
    ]
    required_missing_enforced = bool(result["missing_required_nodes"]) \
        and not allow_missing_required
    if required_missing_enforced:
        reasons.append("required_node_missing")

    if returncode not in (0, 1) or result["failed_ids"] \
            or required_missing_enforced:
        result["verdict"] = "FAIL"
    elif returncode == 1 and result["known_matched"]:
        result["verdict"] = "PASS_WITH_KNOWN_FAILURES"
    else:
        result["verdict"] = "PASS"
    return result
