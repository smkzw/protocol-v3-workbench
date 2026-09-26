#!/usr/bin/env python3
"""G0 acceptance gate for protocol-v3 workbench (A001-A007).

Anti-false-green rules (F08):
- pytest runs in a subprocess with NO shell pipe; the real returncode decides.
- JUnit XML is parsed structurally; missing/corrupt report, collection errors,
  zero tests, missing required nodes and wall-clock timeout all FAIL.
- Known failures require nodeid + fingerprint + baseline SHA three-way match;
  no failure-count thresholds. A baseline bound to another HEAD is BLOCKED.

Exit-code policy: pytest 0 -> PASS path; pytest 1 (tests failed) may be
PASS_WITH_KNOWN_FAILURES only when EVERY failure matches the locked baseline;
any other exit code (2 interrupted/collection, 3 internal, 4 usage, 5 no
tests), a missing/corrupt report, or a timeout is FAIL regardless of text.

Layout note (R1): every path is resolved from --root (default: cwd), never
from __file__, so the same script governs the real repo (invoked with
--root <exported tree>) and a copy placed inside a tree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import time
import importlib.util
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

GATE_VERSION = "g0-0926v1/2"

# set by main(): --json asks for bare single-line JSON (no GATE_JSON= prefix),
# because the consuming harness parses stdout as raw JSON.
_BARE_JSON = False
_ROOT_DISCOVERY_NOTE: str | None = None

_SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist",
              ".pytest_cache", "runs"}


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

# pytest exit codes that are never eligible for PASS/PASS_WITH_KNOWN_FAILURES
HARD_FAIL_EXIT_CODES = {2: "interrupted_or_collection", 3: "internal_error",
                        4: "usage_error", 5: "no_tests_collected"}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


import re as _re

_TMPBASE_RE = _re.compile(r"/(?:private/)?var/folders/[A-Za-z0-9_]+")
_PYTEST_N_RE = _re.compile(r"pytest-\d+")


def normalize_message(message: str, root: Path) -> str:
    """Neutralize checkout root and volatile temp paths so fingerprints are
    stable across environments and pytest runs."""
    variants = {str(root), str(root).rstrip("/"), str(root.resolve())}
    for variant in sorted(variants, key=len, reverse=True):
        message = message.replace(variant, "<ROOT>")
    message = _TMPBASE_RE.sub("<TMPBASE>", message)
    message = _PYTEST_N_RE.sub("pytest-<N>", message)
    return message


def error_fingerprint(exc_class: str, rel_path: str, message: str, root: Path) -> str:
    """sha256(exc_class | root-relative path | message with root -> <ROOT>)[:12]."""
    payload = f"{exc_class}|{rel_path}|{normalize_message(message, root)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- pytest run


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


def parse_junit(junit_path: Path, root: Path) -> dict:
    """Parse a pytest JUnit XML report into structured counts and failures."""
    if not junit_path.exists():
        return {"ok": False, "reason": "report_missing"}
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError:
        return {"ok": False, "reason": "report_corrupted"}
    root_el = tree.getroot()
    suites = [root_el] if root_el.tag == "testsuite" else root_el.findall("testsuite")
    cases, failures, errors, skipped = [], [], [], []
    total = 0
    for suite in suites:
        total += int(suite.get("tests", "0") or 0)
        for case in suite.iter("testcase"):
            classname = case.get("classname") or ""
            name = case.get("name") or ""
            nodeid = junit_nodeid(classname, name, root)
            for child in case:
                if child.tag == "failure":
                    failures.append(_failure_record(classname, name, child, root))
                elif child.tag == "error":
                    errors.append(_failure_record(classname, name, child, root))
                elif child.tag == "skipped":
                    skipped.append(nodeid)
            cases.append(nodeid)
    return {
        "ok": True,
        "total": total,
        "cases": cases,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }


def junit_nodeid(classname: str, name: str, root: Path) -> str:
    """pytest 9 junitxml has no file/line attrs; rebuild a readable nodeid.

    classname is the dotted module path (plus unittest class suffix); resolve
    it against the tree so display nodeids are real pytest ids. Falls back to
    the dotted form (collection errors report the module as the bare name).
    """
    if not classname:
        return name  # collection error: name is the dotted module path
    parts = classname.split(".")
    for k in range(len(parts), 0, -1):
        candidate = Path("/".join(parts[:k]) + ".py")
        if (root / candidate).is_file():
            module = candidate.as_posix()
            suffix = parts[k:]
            return "::".join([module, *suffix, name]) if suffix else f"{module}::{name}"
    return f"{classname}::{name}"


def _failure_record(classname: str, name: str, element, root: Path) -> dict:
    exc_class = element.get("type") or "Exception"
    message = element.get("message") or ""
    text = element.text or ""
    nodeid = junit_nodeid(classname, name, root)
    rel = nodeid.split("::")[0]
    return {
        "nodeid": nodeid,
        "exc_class": exc_class,
        "message": normalize_message(message, root)[:400],
        "fingerprint": error_fingerprint(exc_class, rel, message + "\n" + text, root),
    }


# ---------------------------------------------------------------- static checks


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


def _pyflakes_category(message: str) -> str:
    """Coarse stable buckets for explicitly-ignored finding classes (R3)."""
    if "imported but unused" in message:
        return "imported_but_unused"
    if "assigned to but never used" in message:
        return "assigned_but_never_used"
    if "f-string is missing placeholders" in message:
        return "fstring_missing_placeholders"
    if "redefinition" in message:
        return "redefinition"
    if "dictionary key" in message and "repeated" in message:
        return "dict_key_repeated"
    if "unable to detect undefined names" in message:
        return "unable_to_detect_undefined_names"
    if "may be undefined, or defined from star imports" in message:
        return "possibly_undefined_star_import"
    if "unpacking" in message:
        return "unpacking"
    return "other"


def frontend_fingerprint(root: Path) -> str | None:
    """Replicate vite.config.mjs sourceFingerprint (Node relative semantics)."""
    contract_path = root / "packages" / "contracts" / "workbench_contracts" / "runtime_contract.json"
    if not contract_path.is_file():
        return None
    config = json.loads(contract_path.read_text(encoding="utf-8"))["build_fingerprint"]
    source_root = root / str(config["frontend_source_root"])
    allowed = {str(e) for e in config["frontend_extensions"]}
    files = [
        p for p in source_root.rglob("*")
        if p.is_file() and p.suffix in allowed and "__pycache__" not in p.parts
    ]
    files += [root / rel for rel in config["frontend_additional_files"]]
    digest = hashlib.sha256()
    for path in sorted(files):
        rel = os.path.relpath(path, source_root).replace(os.sep, "/")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"web-{digest.hexdigest()[: int(config['digest_prefix_length'])]}"


def backend_fingerprint(root: Path) -> str | None:
    """Reuse services/api/app/runtime_readiness.py source_fingerprint, bound to root."""
    module_path = root / "services" / "api" / "app" / "runtime_readiness.py"
    if not module_path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(
        f"_gate_runtime_readiness_{abs(hash(str(root)))}", module_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    config = module.RUNTIME_CONTRACT["build_fingerprint"]
    return module.source_fingerprint(
        root / str(config["backend_source_root"]),
        config["backend_extensions"],
        prefix="api",
        digest_prefix_length=int(config["digest_prefix_length"]),
    )


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


# ---------------------------------------------------------------- baseline


def load_baseline(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"format": "UNREADABLE"}


def git_head(root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError:
        return None
    return proc.stdout.strip() or None if proc.returncode == 0 else None


def is_gate_repo(root: Path) -> bool:
    return ((root / "tools/acceptance/required_nodes.json").is_file()
            and (root / "pytest.ini").is_file() and (root / "tests").is_dir())


def resolve_root(requested: Path) -> tuple[Path, str | None]:
    """Harness callers may pass a parent project dir as --root. When the
    requested dir carries no repo markers but the gate's own repo does, fall
    back to the gate repo. The fallback is always surfaced in GATE_JSON."""
    if is_gate_repo(requested):
        return requested, None
    gate_repo = Path(__file__).resolve().parents[1]
    if gate_repo != requested and is_gate_repo(gate_repo):
        return gate_repo, "root_fallback_to_gate_repo"
    return requested, None


def load_required_nodes(path: Path) -> tuple[list[str], list[str], bool]:
    """Returns (junit_nodes, selftest_nodes, file_present)."""
    if not path.is_file():
        return [], [], False
    junit_nodes, selftest_nodes = [], []
    for entry in json.loads(path.read_text(encoding="utf-8")):
        if isinstance(entry, str) and entry.startswith("selftest:"):
            selftest_nodes.append(entry[len("selftest:"):])
        elif isinstance(entry, str):
            junit_nodes.append(entry)
        elif isinstance(entry, dict) and entry.get("kind") == "selftest":
            selftest_nodes.append(entry["nodeid"])
        elif isinstance(entry, dict):
            junit_nodes.append(entry["nodeid"])
    return junit_nodes, selftest_nodes, True


# ---------------------------------------------------------------- verdict


def _escalate(gate: dict, verdict: str) -> None:
    """Only ever move toward the worse outcome; never demote a failure."""
    order = {"PASS": 0, "PASS_WITH_KNOWN_FAILURES": 1, "BLOCKED": 2, "FAIL": 3}
    current = gate.get("verdict")
    if current is None or order[verdict] > order[current]:
        gate["verdict"] = verdict


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


def emit(gate: dict) -> int:
    gate.setdefault("verdict", "FAIL")
    gate.setdefault("reasons", ["no_gate_checks_ran"])
    gate.setdefault("failed", 0)
    gate.setdefault("root_discovery", _ROOT_DISCOVERY_NOTE)
    gate["snapshot_at"] = now_iso()
    line = json.dumps(gate, ensure_ascii=False)
    print(line if _BARE_JSON else "GATE_JSON=" + line)
    return {"PASS": 0, "PASS_WITH_KNOWN_FAILURES": 0, "FAIL": 1, "BLOCKED": 2}[gate["verdict"]]


# ---------------------------------------------------------------- commands


def cmd_run(args) -> int:
    requested = Path(args.root).resolve()
    root, fallback = resolve_root(requested)
    reasons: list[str] = [fallback] if fallback else []
    gate: dict = {"gate_version": GATE_VERSION, "mode": "run", "scope": args.scope,
                  "requested_root": str(requested), "root": str(root),
                  "head_sha": git_head(root), "reasons": reasons,
                  "python": sys.version.split()[0]}

    baseline_path = Path(args.baseline) if args.baseline else \
        root / "tools/acceptance/known_failures_0926v1.json"
    baseline = load_baseline(baseline_path)
    gate["baseline"] = {
        "path": str(baseline_path),
        "present": baseline is not None,
        "sha": (baseline or {}).get("baseline_sha"),
        "matches_head": bool(baseline
                             and baseline.get("format") != "UNREADABLE"
                             and baseline.get("baseline_sha") == gate["head_sha"]),
    }
    required_path = Path(args.required_nodes) if args.required_nodes else \
        root / "tools/acceptance/required_nodes.json"
    junit_nodes, selftest_nodes, required_present = load_required_nodes(required_path)
    if not required_present and not args.allow_missing_required_nodes:
        gate["verdict"] = "FAIL"
        reasons.append("required_nodes_file_missing")
        return emit(gate)

    if baseline and gate["head_sha"] and baseline.get("format") != "UNREADABLE" \
            and baseline.get("baseline_sha") != gate["head_sha"]:
        # risk 7: a baseline from another HEAD must never become a waiver umbrella
        gate["verdict"] = "BLOCKED"
        reasons.append("baseline_sha_mismatch_requires_increment_review")
        return emit(gate)

    scope = args.scope
    if scope in ("backend", "all"):
        with tempfile.TemporaryDirectory(prefix="g0_junit_") as tmp:
            junit_path = Path(tmp) / "report.xml"
            run = run_pytest(root, junit_path, args.timeout, args.pytest_args.split())
            gate["pytest"] = {"returncode": run["returncode"], "elapsed_s": run["elapsed"],
                              "timeout": run["timeout"]}
            report = parse_junit(junit_path, root)
        report["returncode"] = run["returncode"]
        verdict_part = evaluate_report_against_baseline(
            report, baseline, gate["head_sha"], junit_nodes,
            args.allow_missing_required_nodes, reasons)
        gate.update({k: verdict_part[k] for k in
                     ("ran", "failed_ids", "known_matched", "dissolved",
                      "suspected_data_class", "suspected_fingerprint_drift",
                      "missing_required_nodes", "baseline_not_run_count")})
        gate["failed"] = len(gate["failed_ids"])
        _escalate(gate, verdict_part["verdict"])
        gate["collection_errors"] = len(report.get("errors", []))
        gate["skipped_count"] = len(report.get("skipped", []))

        pyf = {"ok": True, "undefined_name": [], "ignored_counted_by_category": {}}
        if not args.skip_static:
            pyf = run_pyflakes(root)
        if not pyf.get("ok"):
            gate["verdict"] = "FAIL"
            reasons.append(f"pyflakes_{pyf.get('reason')}")
        else:
            baseline_undef = {
                f"{f['location']}: {f['name']}"
                for f in (((baseline or {}).get("static_findings") or {})
                          .get("pyflakes_undefined_name") or [])
            }
            current_undef = [f"{f['location']}: {f['name']}" for f in pyf["undefined_name"]]
            new_undef = sorted(set(current_undef) - baseline_undef)
            gate["pyflakes"] = {
                "undefined_name_count": len(current_undef),
                "new_vs_baseline": new_undef,
                "ignored_counted_by_category": pyf["ignored_counted_by_category"],
            }
            if new_undef:
                gate["verdict"] = "FAIL"
                reasons.append("new_pyflakes_undefined_name")

    if scope in ("frontend", "all"):
        lint = run_eslint(root)
        if not lint.get("ok"):
            _escalate(gate, "BLOCKED")
            reasons.append(f"eslint_{lint.get('reason')}")
        else:
            baseline_lint = set(((baseline or {}).get("static_findings") or {})
                                .get("eslint_noundef") or [])
            new_lint = sorted(set(lint["noundef"]) - baseline_lint)
            gate["eslint"] = {"noundef_count": len(lint["noundef"]),
                              "new_vs_baseline": new_lint,
                              "returncode": lint["returncode"]}
            if new_lint:
                _escalate(gate, "FAIL")
                reasons.append("new_eslint_noundef")
            else:
                # findings exist but all match the baseline: acceptable
                _escalate(gate, "PASS")

    return emit(gate)


def cmd_baseline_capture(args) -> int:
    root = Path(args.root).resolve()  # capture targets an explicit export tree; no fallback
    real_root = Path(args.real_root).resolve()
    reasons: list[str] = []
    gate: dict = {"gate_version": GATE_VERSION, "mode": "baseline_capture",
                  "root": str(root), "real_root": str(real_root),
                  "baseline_sha": args.baseline_sha, "reasons": reasons}
    if not args.baseline_sha:
        gate["verdict"] = "FAIL"
        reasons.append("baseline_sha_required")
        return emit(gate)

    with tempfile.TemporaryDirectory(prefix="g0_baseline_junit_") as tmp:
        junit_path = Path(tmp) / "report.xml"
        run = run_pytest(root, junit_path, args.timeout, args.pytest_args.split())
        report = parse_junit(junit_path, root)
    report["returncode"] = run["returncode"]
    failures = report.get("failures", []) + report.get("errors", [])
    pytest_failures = [
        {"nodeid": rec["nodeid"], "fingerprint": rec["fingerprint"], "caveat": ""}
        for rec in failures
    ]

    # R2 lock precondition: at least one captured failure must reproduce in the
    # real repo with the same normalized fingerprint before the baseline locks.
    cross_env = {"passed": False, "verified_nodeid": None, "checked": []}
    for rec in failures[:10]:
        nodeid = rec["nodeid"]
        if "::" in nodeid:
            pytest_target = nodeid
        else:
            candidate = nodeid.replace(".", "/") + ".py"
            pytest_target = candidate if (real_root / candidate).is_file() else nodeid
        with tempfile.TemporaryDirectory(prefix="g0_xenv_") as tmp:
            real_junit = Path(tmp) / "report.xml"
            run_pytest(real_root, real_junit, 900, [pytest_target])
            real_report = parse_junit(real_junit, real_root)
        real_bad = real_report.get("failures", []) + real_report.get("errors", [])
        match = next((r for r in real_bad if r["fingerprint"] == rec["fingerprint"]), None)
        cross_env["checked"].append({"nodeid": nodeid, "reproduced": match is not None})
        if match and not cross_env["passed"]:
            cross_env["passed"] = True
            cross_env["verified_nodeid"] = nodeid

    pyf = run_pyflakes(root)
    baseline_doc = {
        "format": "known_failures_0926v1/1",
        "baseline_sha": args.baseline_sha,
        "captured_at": now_iso(),
        "environment": {
            "python": sys.version.split()[0],
            "pytest": _pytest_version(),
            "platform": platform.platform(),
        },
        "pytest_args": args.pytest_args.split(),
        "pytest_returncode": run["returncode"],
        "pytest_run_total": report.get("total"),
        "pytest_failures": pytest_failures,
        "static_findings": {
            "pyflakes_undefined_name": pyf.get("undefined_name") if pyf.get("ok") else None,
            "pyflakes_ignored_counted_by_category": pyf.get("ignored_counted_by_category") if pyf.get("ok") else None,
            "eslint_noundef": [],
            "eslint_note": "eslint not installed at capture time; install happens after clean A007 capture (R5)",
        },
        "fingerprint_cross_env_check": cross_env,
    }
    out_path = Path(args.baseline_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(baseline_doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    gate.update({
        "baseline_out": str(out_path),
        "captured_failures": len(pytest_failures),
        "pytest_returncode": run["returncode"],
        "pytest_run_total": report.get("total"),
        "fingerprint_cross_env_check": cross_env,
    })
    gate["verdict"] = "PASS" if cross_env["passed"] else "FAIL"
    gate["failed"] = 0 if cross_env["passed"] else 1
    if not cross_env["passed"]:
        reasons.append("cross_env_fingerprint_check_failed_baseline_not_locked")
    return emit(gate)


def _pytest_version() -> str:
    proc = subprocess.run([sys.executable, "-m", "pytest", "--version"],
                          capture_output=True, text=True, timeout=60)
    out = (proc.stdout or proc.stderr).splitlines()
    return out[0].strip() if out else "unknown"


def _get_json(url: str, timeout: int = 5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - report, never crash the gate
        return {"_error": f"{type(exc).__name__}: {exc}"}


def cmd_check_runtime(args) -> int:
    requested = Path(args.root).resolve()
    root, fallback = resolve_root(requested)
    reasons: list[str] = [fallback] if fallback else []
    gate: dict = {"gate_version": GATE_VERSION, "mode": "check_runtime",
                  "requested_root": str(requested), "root": str(root), "reasons": reasons,
                  "note": "live values are computed once at process start, not per request"}
    head = git_head(root)
    api_fp = backend_fingerprint(root)
    web_fp = frontend_fingerprint(root)
    gate["recomputed"] = {"head_sha": head, "backend": api_fp, "frontend": web_fp}
    backend_live = _get_json(f"{args.api_base}/api/runtime-readiness")
    frontend_live = _get_json(f"{args.frontend_base}/runtime-build.json")
    gate["runtime_identity"] = {"backend_live": backend_live, "frontend_live": frontend_live}

    backend_ok = isinstance(backend_live, dict) and backend_live.get("backend_build_id") == api_fp
    frontend_expect_ok = isinstance(frontend_live, dict) and "_error" not in frontend_live and (
        frontend_live.get("expectedBackendBuildId") == api_fp
        and frontend_live.get("frontendBuildId") == web_fp
    )
    gate["checks"] = {
        "live_backend_matches_tree": backend_ok,
        "live_frontend_expectation_matches_tree": frontend_expect_ok,
    }

    dist_path = root / "frontend" / "dist" / "runtime-build.json"
    dist_stale = None
    if dist_path.is_file():
        try:
            dist_doc = json.loads(dist_path.read_text(encoding="utf-8"))
            dist_stale = dist_doc.get("expectedBackendBuildId") != api_fp
        except json.JSONDecodeError:
            dist_stale = True
    gate["dist"] = {"path": str(dist_path), "present": dist_path.is_file(),
                    "stale": dist_stale,
                    "preview_production_acceptance_blocked": bool(dist_stale)}

    if backend_ok and frontend_expect_ok:
        gate["verdict"] = "PASS"
        if dist_stale:
            reasons.append("dist_runtime_build_stale_preview_production_blocked")
    else:
        gate["verdict"] = "BLOCKED"
        reasons.append("runtime_identity_mismatch_or_unreachable")
    return emit(gate)


def cmd_check_smoke(args) -> int:
    root, _fallback = resolve_root(Path(args.root).resolve())
    script = Path(args.smoke_script) if args.smoke_script else \
        Path(__file__).parent / "browser_smoke.js"
    gate: dict = {"gate_version": GATE_VERSION, "mode": "check_smoke",
                  "root": str(root), "script": str(script)}
    if not script.is_file():
        gate["verdict"] = "BLOCKED"
        gate["reasons"] = ["smoke_script_missing"]
        return emit(gate)
    try:
        with script.open("rb") as stdin:
            proc = subprocess.run(
                ["ego-browser", "nodejs"], stdin=stdin,
                capture_output=True, text=True, timeout=args.smoke_timeout,
            )
    except FileNotFoundError:
        gate["verdict"] = "BLOCKED"
        gate["reasons"] = ["ego_browser_cli_not_found"]
        return emit(gate)
    except subprocess.TimeoutExpired:
        gate["verdict"] = "BLOCKED"
        gate["reasons"] = ["smoke_timeout"]
        return emit(gate)
    output = proc.stdout + proc.stderr
    match = re.search(r"SMOKE_JSON=(\{.*\})", output)
    gate["smoke_raw_tail"] = output[-800:]
    if not match:
        gate["verdict"] = "BLOCKED"
        gate["reasons"] = ["smoke_json_not_emitted"]
        return emit(gate)
    smoke = json.loads(match.group(1))
    gate["smoke"] = smoke
    gate["verdict"] = smoke.get("verdict", "BLOCKED")
    gate["reasons"] = smoke.get("reasons", [])
    return emit(gate)


# ---------------------------------------------------------------- selftests


def _write_mini_suite(root: Path, *, broken: bool = False, failing: bool = False,
                      root_in_message: bool = False) -> None:
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = .\n", encoding="utf-8")
    (root / "test_passes.py").write_text(
        "def test_always_passes():\n    assert 1 + 1 == 2\n", encoding="utf-8")
    if broken:
        (root / "test_broken.py").write_text("def test_broken(:\n    pass\n", encoding="utf-8")
    if failing:
        if root_in_message:
            body = (
                "from pathlib import Path\n\n"
                "def test_always_fails():\n"
                "    p = Path(__file__).resolve().parent\n"
                "    raise AssertionError(f'deliberate failure at {p}')\n"
            )
        else:
            body = "def test_always_fails():\n    assert False, 'deliberate failure'\n"
        (root / "test_fails.py").write_text(body, encoding="utf-8")


def _run_gate(script: Path, args: list[str]) -> tuple[int, dict | None]:
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=900,
    )
    match = re.search(r"GATE_JSON=(\{.*\})", proc.stdout)
    return proc.returncode, (json.loads(match.group(1)) if match else None)


def selftest_A002() -> dict:
    """A002: collection error, pytest text has no 'failed' word; gate must FAIL."""
    with tempfile.TemporaryDirectory(prefix="g0_a002_") as tmp:
        root = Path(tmp)
        _write_mini_suite(root, broken=True)
        _, doc = _run_gate(Path(__file__).resolve(),
                           ["--root", str(root), "--scope", "backend", "--pytest-args", ".",
                            "--skip-static", "--allow-missing-required-nodes"])
        ok = (doc is not None
              and doc.get("verdict") == "FAIL"
              and doc.get("pytest", {}).get("returncode") not in (0, None)
              and doc.get("collection_errors", 0) >= 1)
        return {"case": "A002", "passed": ok,
                "verdict": doc and doc.get("verdict"),
                "reasons": doc and doc.get("reasons"),
                "collection_errors": doc and doc.get("collection_errors"),
                "detail": "collection error with no 'failed' word in text output; gate FAILs on the structured error entry"}


def selftest_A003() -> dict:
    """A003: `pytest | tee` masks the real exit code with 0; the gate does not."""
    with tempfile.TemporaryDirectory(prefix="g0_a003_") as tmp:
        root = Path(tmp)
        _write_mini_suite(root, failing=True)
        piped = subprocess.run(
            ["sh", "-c",
             f"cd '{root}' && {sys.executable} -m pytest -q -p no:cacheprovider | tee pipe.log > /dev/null; "
             f"echo EXIT=$?"],
            capture_output=True, text=True, timeout=300,
        )
        exit_lines = [ln for ln in piped.stdout.splitlines() if ln.startswith("EXIT=")]
        tee_masked_green = bool(exit_lines) and exit_lines[-1] == "EXIT=0"
        _, doc = _run_gate(Path(__file__).resolve(),
                           ["--root", str(root), "--scope", "backend", "--pytest-args", ".",
                            "--skip-static", "--allow-missing-required-nodes"])
        ok = (tee_masked_green and doc is not None
              and doc.get("verdict") == "FAIL"
              and doc.get("pytest", {}).get("returncode") == 1)
        return {"case": "A003", "passed": ok,
                "piped_exit": exit_lines[-1] if exit_lines else None,
                "gate_verdict": doc and doc.get("verdict"),
                "gate_returncode": doc and doc.get("pytest", {}).get("returncode"),
                "detail": "pipeline EXIT=0 is tee's status; real pytest exit was 1; gate FAILs on the real code"}


def selftest_A004() -> dict:
    """A004: zero tests / truncated report / missing report / required node absent."""
    results = []
    # (a) empty suite -> pytest exit 5 -> FAIL
    with tempfile.TemporaryDirectory(prefix="g0_a004a_") as tmp:
        root = Path(tmp)
        _write_mini_suite(root)
        (root / "test_passes.py").unlink()
        _, doc = _run_gate(Path(__file__).resolve(),
                           ["--root", str(root), "--scope", "backend", "--pytest-args", ".",
                            "--skip-static", "--allow-missing-required-nodes"])
        results.append({"case": "A004a_zero_tests",
                        "passed": doc is not None and doc.get("verdict") == "FAIL"
                        and any(r.startswith("pytest_exit_5") for r in doc.get("reasons", [])),
                        "reasons": doc and doc.get("reasons")})
    # (b) truncated junit -> report_corrupted
    with tempfile.TemporaryDirectory(prefix="g0_a004b_") as tmp:
        root = Path(tmp)
        _write_mini_suite(root, failing=True)
        junit = root / "truncated.xml"
        run_pytest(root, junit, 120, ["."])
        raw = junit.read_text(encoding="utf-8")
        junit.write_text(raw[: max(1, len(raw) // 2)], encoding="utf-8")
        report = parse_junit(junit, root)
        report["returncode"] = 0
        reasons: list[str] = []
        verdict = evaluate_report_against_baseline(report, None, None, [], True, reasons)
        results.append({"case": "A004b_truncated_junit",
                        "passed": verdict["verdict"] == "FAIL" and "report_corrupted" in reasons,
                        "reasons": reasons})
    # (c) missing report
    with tempfile.TemporaryDirectory(prefix="g0_a004c_") as tmp:
        root = Path(tmp)
        _write_mini_suite(root)
        report = parse_junit(root / "nope" / "missing.xml", root)
        report["returncode"] = 0
        reasons2: list[str] = []
        verdict = evaluate_report_against_baseline(report, None, None, [], True, reasons2)
        results.append({"case": "A004c_missing_report",
                        "passed": verdict["verdict"] == "FAIL" and "report_missing" in reasons2,
                        "reasons": reasons2})
    # (d) required node absent from report
    with tempfile.TemporaryDirectory(prefix="g0_a004d_") as tmp:
        root = Path(tmp)
        _write_mini_suite(root)
        required = root / "required_nodes.json"
        required.write_text(json.dumps(["tests/test_absent.py::test_missing"]), encoding="utf-8")
        _, doc = _run_gate(Path(__file__).resolve(),
                           ["--root", str(root), "--scope", "backend", "--pytest-args", ".",
                            "--skip-static", "--required-nodes", str(required)])
        results.append({"case": "A004d_required_node_missing",
                        "passed": doc is not None and doc.get("verdict") == "FAIL"
                        and "required_node_missing" in doc.get("reasons", []),
                        "reasons": doc and doc.get("reasons")})
    return {"case": "A004", "passed": all(r["passed"] for r in results), "subcases": results}


def selftest_layout() -> dict:
    """R1: same fixture, same verdict from both invocation layouts."""
    with tempfile.TemporaryDirectory(prefix="g0_layoutA_") as tmp_a, \
            tempfile.TemporaryDirectory(prefix="g0_layoutB_") as tmp_b:
        root_a, root_b = Path(tmp_a), Path(tmp_b)
        _write_mini_suite(root_a, failing=True, root_in_message=True)
        _write_mini_suite(root_b, failing=True, root_in_message=True)
        real_script = Path(__file__).resolve()
        # layout A: script lives in the real repo, tree passed via --root
        _, doc_a = _run_gate(real_script, ["--root", str(root_a), "--scope", "backend", "--pytest-args", ".",
                                           "--skip-static", "--allow-missing-required-nodes"])
        # layout B: script copied into the tree, invoked directly with cwd=tree
        copy_dir = root_b / "tools" / "acceptance"
        copy_dir.mkdir(parents=True)
        copy_script = copy_dir / "run_acceptance_gate.py"
        copy_script.write_text(real_script.read_text(encoding="utf-8"), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(copy_script), "--scope", "backend", "--pytest-args", ".",
             "--skip-static", "--allow-missing-required-nodes"],
            cwd=str(root_b), capture_output=True, text=True, timeout=900)
        match = re.search(r"GATE_JSON=(\{.*\})", proc.stdout)
        doc_b = json.loads(match.group(1)) if match else None
        passed = bool(
            doc_a and doc_b
            and doc_a.get("verdict") == doc_b.get("verdict") == "FAIL"
            and doc_a.get("failed_ids") == doc_b.get("failed_ids")
        )
        return {"case": "layout", "passed": passed,
                "layout_a_verdict": doc_a and doc_a.get("verdict"),
                "layout_b_verdict": doc_b and doc_b.get("verdict"),
                "detail": "script+--root vs script-copied-into-tree agree on verdict and nodeid"}


def _fingerprint_of_fixture_root(root: Path) -> str | None:
    junit_dir = Path(tempfile.mkdtemp())
    try:
        run_pytest(root, junit_dir / "r.xml", 120, ["test_fails.py"])
        report = parse_junit(junit_dir / "r.xml", root)
        bad = report.get("failures", []) + report.get("errors", [])
        return bad[0]["fingerprint"] if bad else None
    finally:
        pass


def selftest_fingerprint() -> dict:
    """R2: message containing the absolute root fingerprints identically under two roots."""
    with tempfile.TemporaryDirectory(prefix="g0_fp_A_") as tmp_a, \
            tempfile.TemporaryDirectory(prefix="g0_fp_B_") as tmp_b:
        root_a, root_b = Path(tmp_a), Path(tmp_b)
        _write_mini_suite(root_a, failing=True, root_in_message=True)
        _write_mini_suite(root_b, failing=True, root_in_message=True)
        rec_a = _fingerprint_of_fixture_root(root_a)
        rec_b = _fingerprint_of_fixture_root(root_b)
        return {"case": "fingerprint", "passed": bool(rec_a and rec_a == rec_b),
                "fingerprint_root_a": rec_a, "fingerprint_root_b": rec_b,
                "detail": "abs-root-bearing failure message normalizes to identical fingerprint"}


SELFTEST_CASES = {
    "A002": selftest_A002,
    "A003": selftest_A003,
    "A004": selftest_A004,
    "layout": selftest_layout,
    "fingerprint": selftest_fingerprint,
}


def cmd_selftest(args) -> int:
    selected = list(SELFTEST_CASES) if args.selftest == "all" else [args.selftest]
    results = [SELFTEST_CASES[name]() for name in selected]
    all_ok = all(r.get("passed") for r in results)
    gate = {"gate_version": GATE_VERSION, "mode": "selftest",
            "verdict": "PASS" if all_ok else "FAIL",
            "failed": sum(1 for r in results if not r.get("passed")),
            "cases": results, "snapshot_at": now_iso()}
    line = json.dumps(gate, ensure_ascii=False)
    print(line if _BARE_JSON else "GATE_JSON=" + line)
    return 0 if all_ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="G0 acceptance gate (A001-A007)")
    parser.add_argument("--root", default=os.getcwd(),
                        help="tree under test; every path resolves from here (default: cwd)")
    parser.add_argument("positional", nargs="?", default=None,
                        choices=["run", "backend", "frontend", "all"],
                        help="optional positional mode/scope; 'backend --json' == '--scope backend --json'")
    parser.add_argument("--scope", choices=["backend", "frontend", "all"], default=None)
    parser.add_argument("--json", action="store_true", default=False,
                        help="emit single-line GATE_JSON only (already the default stdout contract)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="whole-suite wall clock seconds; timeout -> report missing -> FAIL")
    parser.add_argument("--pytest-args", default="tests")
    parser.add_argument("--baseline", default=None,
                        help="known-failures JSON (default <root>/tools/acceptance/known_failures_0926v1.json)")
    parser.add_argument("--required-nodes", default=None,
                        help="required node list (default <root>/tools/acceptance/required_nodes.json)")
    parser.add_argument("--allow-missing-required-nodes", action="store_true",
                        help="selftest fixtures only; real gate runs must not use this")
    parser.add_argument("--skip-static", action="store_true",
                        help="selftest fixtures only: skip the pyflakes pass (no services tree)")
    sub = parser.add_mutually_exclusive_group()
    sub.add_argument("--baseline-capture", action="store_true")
    sub.add_argument("--check-runtime", action="store_true")
    sub.add_argument("--check-smoke", action="store_true")
    sub.add_argument("--selftest", choices=list(SELFTEST_CASES) + ["all"])
    parser.add_argument("--baseline-sha", default=None)
    parser.add_argument("--baseline-out", default=None)
    parser.add_argument("--real-root", default=None,
                        help="real repo root for baseline cross-env fingerprint check")
    parser.add_argument("--api-base", default="http://127.0.0.1:5301")
    parser.add_argument("--frontend-base", default="http://127.0.0.1:5186")
    parser.add_argument("--smoke-script", default=None)
    parser.add_argument("--smoke-timeout", type=int, default=180)

    args = parser.parse_args(argv)
    global _BARE_JSON
    _BARE_JSON = bool(args.json)
    args.root = str(discover_repo_root(Path(args.root).resolve()))
    if args.positional == "run":
        args.positional = None
    if args.scope is None and args.positional in ("backend", "frontend", "all"):
        args.scope = args.positional
    if args.scope is None:
        args.scope = "backend"
    if args.baseline_capture:
        if not args.baseline_out:
            parser.error("--baseline-capture requires --baseline-out")
        if not args.real_root:
            parser.error("--baseline-capture requires --real-root (cross-env fingerprint check)")
        return cmd_baseline_capture(args)
    if args.check_runtime:
        return cmd_check_runtime(args)
    if args.check_smoke:
        return cmd_check_smoke(args)
    if args.selftest:
        return cmd_selftest(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
