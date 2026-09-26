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
import socket
import subprocess
import sys
import tempfile
import time
import importlib.util
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

GATE_VERSION = "g0-0927v1/1"
GATE_RESULT_SCHEMA = "g0_result/2"

# Safety-boundary failures (numbers/source/authority/data-loss) are never
# waivable via the known-failures baseline (red line 9). Built-in floor plus
# optional tools/acceptance/security_sentinels.json extensions.
DEFAULT_SENTINEL_PREFIXES = (
    "tests/test_writing_reference_numeric_fidelity",
    "tests/test_writing_reference_final_candidate_fidelity",
    "tests/test_writing_reference_translation_service",
    "tests/test_medical_writing_source_preserving_export",
    "tests/test_medical_writing_registered_sources",
    "tests/test_phase1_corpus_source_boundaries",
    "tests/protocol_v3/test_source_identity_product",
    "tests/protocol_v3/test_pinned_chapter_sources",
    "tests/protocol_v3/test_agent5_authority_boundary",
    "tests/protocol_v3/test_frozen_authority_manifest",
    "tests/test_medical_risk_authority",
    "tests/test_monitoring_identity_authorization",
    "tests/test_monitoring_approval_source_gate",
    "tests/test_medical_writing_authoring_journey",
)


def load_sentinel_prefixes() -> list[str]:
    prefixes = set(DEFAULT_SENTINEL_PREFIXES)
    sentinel_path = Path(__file__).resolve().parent / "security_sentinels.json"
    try:
        doc = json.loads(sentinel_path.read_text(encoding="utf-8"))
        prefixes |= {str(p) for p in doc.get("module_prefixes") or []}
    except (OSError, ValueError):
        pass
    return sorted(prefixes)

# set by main(): --json asks for bare single-line JSON (no GATE_JSON= prefix),
# because the consuming harness parses stdout as raw JSON.
_BARE_JSON = False
_ROOT_DISCOVERY_NOTE: str | None = None

_SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist",
              ".pytest_cache", "runs"}


class RootAmbiguityError(Exception):
    """A08/F06: multiple candidate repo roots under --root; the caller must
    pass the exact root instead of letting the gate silently pick one."""

    def __init__(self, candidates: list[str]):
        super().__init__("multiple candidate repo roots")
        self.candidates = candidates


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
        "multiple candidate repo roots, refusing to choose: "
        f"{[str(c) for c in candidates]}")
    raise RootAmbiguityError([str(c) for c in sorted(candidates)])

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

# A10/F02: the pytest child runs in an offline sandbox — live WORKBENCH_*,
# provider credentials and proxies must never leak into test runs (failure
# fingerprints under the old {**os.environ} inheritance were env-brittle).
_GATE_ENV_ALLOWLIST = {
    "PATH", "HOME", "SHELL", "USER", "LOGNAME", "TMPDIR", "TEMP", "TMP",
    "LANG", "LC_ALL", "LC_CTYPE", "SYSTEMROOT", "COMSPEC",
    "PYTHONDONTWRITEBYTECODE", "PYTHONHASHSEED",
}


def _gate_test_env(root: Path, plugin_dir: Path) -> dict:
    env = {key: value for key, value in os.environ.items()
           if key in _GATE_ENV_ALLOWLIST or key.startswith("PYTHON")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Team-documented backend test convention (HANDOFF R11/R15):
    # PYTHONPATH=services/api:. relative to the tree under test; the gate
    # plugin dir is appended last so repo packages keep priority.
    env["PYTHONPATH"] = os.pathsep.join(
        [f"services/api", ".", str(plugin_dir)])
    return env


def _kill_own_process_group(proc: subprocess.Popen) -> None:
    """Red line 6-2: on timeout kill exactly the process group this gate
    started (start_new_session makes pgid == pid), TERM first, then KILL."""
    import signal
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def run_pytest(root: Path, junit_path: Path, timeout: int, pytest_args: list[str],
               nodeid_report: Path | None = None) -> dict:
    cmd = [
        sys.executable, "-m", "pytest", *pytest_args, "-q",
        "-p", "no:cacheprovider", "--continue-on-collection-errors",
        f"--junitxml={junit_path}",
    ]
    plugin_dir = Path(__file__).resolve().parent
    if nodeid_report is not None and (plugin_dir / "gate_nodeid_recorder.py").is_file():
        cmd += ["-p", "gate_nodeid_recorder", f"--nodeid-report={nodeid_report}"]
    env = _gate_test_env(root, plugin_dir)
    started = time.time()
    # start_new_session: the child gets its own process group so a timeout
    # can only ever kill THIS gate's group, never user processes.
    proc = subprocess.Popen(
        cmd, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env, start_new_session=True,
    )
    child = {"pid": proc.pid, "pgid": proc.pid, "argv": cmd, "cwd": str(root),
             "started_at": now_iso()}
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_own_process_group(proc)
        # reaping after the kill returns whatever output was produced so far;
        # partial logs are kept as evidence, never discarded (red line 6-2).
        stdout, stderr = proc.communicate()
    child.update({"ended_at": now_iso(), "timed_out": timed_out})
    return {
        "returncode": None if timed_out else proc.returncode,
        "stdout": stdout or "",
        "stderr": stderr or "",
        "elapsed": round(time.time() - started, 1),
        "timeout": timed_out,
        "child": child,
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
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "pyflakes_timeout"}
    # A07: rc=1 with parseable stdout findings means the tool ran; rc=1 with
    # no parseable output (broken install/import error) or any other rc means
    # the tool itself failed — never an empty-but-ok pass.
    findings, ignored = [], {}
    any_line_parsed = False
    for line in (proc.stdout or "").splitlines():
        m = re.match(r"^(.+?):(\d+):(\d+):\s*(.+)$", line)
        if not m:
            continue
        any_line_parsed = True
        path, lineno, col, message = m.group(1), m.group(2), m.group(3), m.group(4)
        if message.startswith("undefined name"):
            name = message.split("'", 1)[1].rstrip("'") if "'" in message else message
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            findings.append({"location": f"{rel}:{lineno}:{col}", "name": name})
        else:
            key = _pyflakes_category(message)
            ignored[key] = ignored.get(key, 0) + 1
    tool_ran = proc.returncode == 0 or (proc.returncode == 1 and any_line_parsed)
    if not tool_ran:
        return {"ok": False, "reason": "pyflakes_failed",
                "returncode": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-400:]}
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
    try:
        proc = subprocess.run(
            [str(bin_path), "src", "--config", "eslint.config.mjs", "--format", "json"],
            cwd=str(frontend), capture_output=True, text=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "eslint_timeout"}
    # A07: an execution failure (config error, crash: rc not in {0,1}) or a
    # corrupt report is tool failure, not an empty-noundef green.
    if proc.returncode not in (0, 1):
        return {"ok": False, "reason": "eslint_failed",
                "returncode": proc.returncode,
                "stderr_tail": (proc.stderr or "")[-400:]}
    try:
        reports = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return {"ok": False, "reason": "eslint_report_unparseable",
                "returncode": proc.returncode,
                "parse_error": (proc.stdout or proc.stderr or "")[:400]}
    findings, fatal_count = [], 0
    for file_report in reports:
        for message in file_report.get("messages", []):
            if message.get("fatal"):
                fatal_count += 1
            if message.get("ruleId") == "no-undef":
                rel = os.path.relpath(file_report.get("filePath", ""), frontend)
                findings.append(
                    f"{rel}: line {message.get('line')}, col {message.get('column')}, "
                    f"{message.get('message')}"
                )
    return {"ok": True, "returncode": proc.returncode, "noundef": findings,
            "fatal_count": fatal_count}


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


def git_is_ancestor(root: Path, ancestor_sha: str, descendant_sha: str) -> bool | None:
    """True/False per merge-base --is-ancestor; None when git cannot answer."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor",
             ancestor_sha, descendant_sha],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None


def git_changed_files(root: Path, base_sha: str, head_sha: str) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", f"{base_sha}..{head_sha}"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()] \
        if proc.returncode == 0 else []


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


def required_node_status(executed_records: list[dict] | None, nodeid: str,
                         executed_cases: set[str] | None = None,
                         skipped_cases: set[str] | None = None) -> tuple[bool, str]:
    """Exact-native-nodeid required-test judgement (A04/A05).

    With recorder records: satisfied only when setup passed AND call passed
    without an xfail marker. A skipped/xfailed/failed run of the exact nodeid
    is 'required_node_skipped'; absence is 'required_node_missing'. Same-leaf
    tests on other classes or other parametrize brackets never match.

    Legacy fallback (no records, e.g. selftest fixtures): exact nodeid among
    junit-rebuilt cases; junit cannot see the setup/call split.
    """
    if executed_records is not None:
        recs = [r for r in executed_records
                if isinstance(r, dict) and r.get("nodeid") == nodeid]
        setup_ok = any(r.get("when") == "setup" and r.get("outcome") == "passed"
                       for r in recs)
        call_ok = any(r.get("when") == "call" and r.get("outcome") == "passed"
                      and not r.get("wasxfail") for r in recs)
        if call_ok and setup_ok:
            return True, "ran_passed"
        if recs:
            return False, "required_node_skipped"
        return False, "required_node_missing"
    executed = executed_cases if executed_cases is not None else set()
    skipped = skipped_cases if skipped_cases is not None else set()
    if nodeid in skipped:
        return False, "required_node_skipped"
    if nodeid in executed:
        return True, "ran_passed"
    return False, "required_node_missing"


def evaluate_report_against_baseline(report: dict, baseline: dict | None,
                                     head_sha: str | None,
                                     required_nodes: list[str],
                                     allow_missing_required: bool,
                                     reasons: list[str],
                                     *,
                                     baseline_usable: bool | None = None,
                                     executed_records: list[dict] | None = None,
                                     sentinel_prefixes: list[str] | None = None) -> dict:
    """Shared FAIL/KNOWN/PASS decision for a parsed pytest report.

    Every return path carries the complete schema keys, so downstream
    projection can never KeyError (A06/F05)."""
    result = {
        "ran": report.get("total", 0) if report.get("ok") else 0,
        "failed_ids": [],
        "known_matched": [],
        "dissolved": [],
        "suspected_data_class": [],
        "suspected_fingerprint_drift": [],
        "missing_required_nodes": [],
        "skipped_required_nodes": [],
        "security_sentinel_blocked": [],
        "baseline_not_run_count": 0,
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

    # A06/P07: an empty parsed report with a green returncode is
    # contradictory — the suite never ran; never treat it as PASS.
    if not report.get("total"):
        reasons.append("no_tests_in_report")
        result["verdict"] = "FAIL"
        return result

    all_bad = report["failures"] + report["errors"]
    baseline_failures = (baseline or {}).get("pytest_failures") or []
    if baseline_usable is None:
        baseline_usable = bool(
            baseline
            and baseline.get("format") != "UNREADABLE"
            and baseline.get("baseline_sha") == head_sha
        )
    if baseline and not baseline_usable:
        reasons.append("baseline_not_bound_to_current_head")
    baseline_map = {entry["nodeid"]: entry for entry in baseline_failures}
    messages = {rec["nodeid"]: rec["message"] for rec in all_bad}
    sentinel_prefixes = sentinel_prefixes if sentinel_prefixes is not None else []
    for rec in all_bad:
        entry = baseline_map.get(rec["nodeid"])
        fingerprint_match = bool(
            baseline_usable and entry
            and entry.get("fingerprint") == rec["fingerprint"])
        sentinel_hit = any(rec["nodeid"].startswith(prefix)
                           for prefix in sentinel_prefixes)
        if fingerprint_match and not sentinel_hit:
            result["known_matched"].append(rec["nodeid"])
        else:
            result["failed_ids"].append(rec["nodeid"])
            if fingerprint_match and sentinel_hit:
                # red line 9: matching the baseline never waives a
                # safety-boundary failure; it stays a current failure.
                result["security_sentinel_blocked"].append(rec["nodeid"])
            elif "isolated_runtime" in messages.get(rec["nodeid"], ""):
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

    statuses = {
        node: required_node_status(executed_records, node, executed,
                                   set(report["skipped"]))
        for node in required_nodes
    }
    result["missing_required_nodes"] = [
        node for node, (ok, status) in statuses.items()
        if not ok and status == "required_node_missing"]
    result["skipped_required_nodes"] = [
        node for node, (ok, status) in statuses.items()
        if not ok and status == "required_node_skipped"]
    required_missing_enforced = bool(result["missing_required_nodes"]) \
        and not allow_missing_required
    if required_missing_enforced:
        reasons.append("required_node_missing")
    # A04: a skipped/xfailed required test is rejected even when missing
    # required nodes would be tolerated — skip is never coverage.
    if result["skipped_required_nodes"]:
        reasons.append("required_node_skipped")

    if returncode not in (0, 1) or result["failed_ids"] \
            or required_missing_enforced or result["skipped_required_nodes"]:
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
    gate.setdefault("snapshot_at", now_iso())
    line = json.dumps(gate, ensure_ascii=False)
    print(line if _BARE_JSON else "GATE_JSON=" + line)
    return {"PASS": 0, "PASS_WITH_KNOWN_FAILURES": 0, "FAIL": 1, "BLOCKED": 2}[gate["verdict"]]


# ---------------------------------------------------------------- result doc


_RUN_RESULT_INT_KEYS = ("ran", "failed", "baseline_not_run_count",
                        "collection_errors", "skipped_count")
_RUN_RESULT_LIST_KEYS = ("failed_ids", "known_matched", "dissolved",
                         "suspected_data_class", "suspected_fingerprint_drift",
                         "missing_required_nodes", "reasons")
_RUN_RESULT_OPTIONAL_LIST_KEYS = ("skipped_required_nodes",
                                  "security_sentinel_blocked",
                                  "changed_files_vs_baseline")


def validate_gate_result(doc) -> list[str]:
    """A09: strict schema check for the authoritative run result doc.
    Returns a list of problems; empty means the doc conforms."""
    if not isinstance(doc, dict):
        return ["result_not_a_json_object"]
    problems: list[str] = []
    if doc.get("schema_version") != GATE_RESULT_SCHEMA:
        problems.append("schema_version_invalid")
    if doc.get("verdict") not in ("PASS", "PASS_WITH_KNOWN_FAILURES",
                                  "BLOCKED", "FAIL"):
        problems.append("verdict_invalid")
    if doc.get("mode") not in ("run", "from_result"):
        problems.append("mode_invalid")
    for key in ("gate_version", "mode", "root", "snapshot_at"):
        value = doc.get(key)
        if not isinstance(value, str) or not value:
            problems.append(f"{key}_must_be_nonempty_string")
    reasons = doc.get("reasons")
    if not isinstance(reasons, list) or not all(
            isinstance(item, str) for item in reasons):
        problems.append("reasons_must_be_string_list")
    if doc.get("mode") != "run":
        return problems
    for key in _RUN_RESULT_INT_KEYS:
        value = doc.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            problems.append(f"{key}_must_be_int")
    for key in _RUN_RESULT_LIST_KEYS:
        value = doc.get(key)
        if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value):
            problems.append(f"{key}_must_be_string_list")
    for key in _RUN_RESULT_OPTIONAL_LIST_KEYS:
        if key not in doc:
            continue
        value = doc.get(key)
        if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value):
            problems.append(f"{key}_must_be_string_list")
    for key in ("tested_commit", "baseline_commit"):
        if key not in doc:
            problems.append(f"{key}_required")
            continue
        value = doc[key]
        if value is not None and not isinstance(value, str):
            problems.append(f"{key}_must_be_string_or_null")
    if doc.get("scope") not in ("backend", "frontend", "all"):
        problems.append("scope_invalid")
    failed_ids = doc.get("failed_ids")
    failed = doc.get("failed")
    if isinstance(failed_ids, list) and isinstance(failed, int) \
            and not isinstance(failed, bool) and failed != len(failed_ids):
        problems.append("failed_count_mismatch")
    return problems


def _atomic_write_json(path: Path, doc: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _prepare_run_evidence(root: Path, requested_evidence_dir: str | None) -> dict:
    base = Path(requested_evidence_dir) if requested_evidence_dir \
        else root / "runs" / "acceptance_gate"
    run_dir = base / f"run_{now_iso().replace(':', '')}_{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return {
        "dir": run_dir,
        "result": run_dir / "result.json",
        "junit": run_dir / "junit.xml",
        "nodeid_report": run_dir / "nodeid_report.json",
        "pytest_stdout": run_dir / "pytest_stdout.log",
        "pytest_stderr": run_dir / "pytest_stderr.log",
    }


def _finish_run(gate: dict, reasons: list[str], evidence: dict | None) -> int:
    """Validate, persist the authoritative result atomically, then emit.
    All cmd_run exits route through here so every path keeps full evidence."""
    gate["reasons"] = reasons
    gate.setdefault("verdict", "FAIL")
    gate.setdefault("failed", 0)
    gate.setdefault("ran", 0)
    for key in ("failed_ids", "known_matched", "dissolved",
                "suspected_data_class", "suspected_fingerprint_drift",
                "missing_required_nodes"):
        gate.setdefault(key, [])
    gate.setdefault("baseline_not_run_count", 0)
    gate.setdefault("collection_errors", 0)
    gate.setdefault("skipped_count", 0)
    gate["schema_version"] = GATE_RESULT_SCHEMA
    gate["snapshot_at"] = now_iso()
    gate.setdefault("root_discovery", _ROOT_DISCOVERY_NOTE)
    problems = validate_gate_result(gate)
    if problems:
        # never silently emit a non-conforming authority doc: surface the
        # violation, mark FAIL, and still persist the doc as evidence.
        gate["verdict"] = "FAIL"
        gate["reasons"] = reasons + [f"result_schema_violation:{p}" for p in problems]
    if evidence is not None:
        gate["evidence_dir"] = str(evidence["dir"])
        gate["result_path"] = str(evidence["result"])
        _atomic_write_json(evidence["result"], gate)
    return emit(gate)


def run_required_selftests(script: Path, names: list[str], timeout: int) -> list[dict]:
    """A002-A004/layout/fingerprint listed in required_nodes.json are actually
    executed here (previously their names were loaded and never run)."""
    results = []
    for name in names:
        entry: dict = {"case": name}
        try:
            proc = subprocess.run(
                [sys.executable, str(script), "--selftest", name, "--json"],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            entry.update(passed=False, error="timeout")
            results.append(entry)
            continue
        except FileNotFoundError:
            entry.update(passed=False, error="interpreter_missing")
            results.append(entry)
            continue
        doc = None
        try:
            doc = json.loads((proc.stdout or "").strip() or "null")
        except json.JSONDecodeError:
            pass
        entry.update(
            passed=bool(proc.returncode == 0 and isinstance(doc, dict)
                        and doc.get("verdict") == "PASS" and doc.get("failed") == 0),
            returncode=proc.returncode,
            verdict=(doc or {}).get("verdict") if isinstance(doc, dict) else None,
        )
        results.append(entry)
    return results


# ---------------------------------------------------------------- commands


def cmd_run(args) -> int:
    requested = Path(args.root).resolve()
    root, fallback = resolve_root(requested)
    reasons: list[str] = [fallback] if fallback else []
    gate: dict = {"gate_version": GATE_VERSION, "mode": "run", "scope": args.scope,
                  "requested_root": str(requested), "root": str(root),
                  "head_sha": git_head(root), "reasons": reasons,
                  "python": sys.version.split()[0]}
    evidence = _prepare_run_evidence(root, getattr(args, "evidence_dir", None))

    baseline_path = Path(args.baseline) if args.baseline else \
        root / "tools/acceptance/known_failures_0926v1.json"
    baseline = load_baseline(baseline_path)
    baseline_sha = (baseline or {}).get("baseline_sha") \
        if baseline and baseline.get("format") != "UNREADABLE" else None
    head_sha = gate["head_sha"]
    gate["baseline"] = {
        "path": str(baseline_path),
        "present": baseline is not None,
        "sha": baseline_sha,
        "matches_head": bool(baseline_sha and head_sha
                             and baseline_sha == head_sha),
    }
    gate["tested_commit"] = head_sha
    gate["baseline_commit"] = baseline_sha
    required_path = Path(args.required_nodes) if args.required_nodes else \
        root / "tools/acceptance/required_nodes.json"
    junit_nodes, selftest_nodes, required_present = load_required_nodes(required_path)
    if not required_present and not args.allow_missing_required_nodes:
        gate["verdict"] = "FAIL"
        reasons.append("required_nodes_file_missing")
        return _finish_run(gate, reasons, evidence)

    # A02/F01: tested_commit and baseline_commit are separate. A baseline
    # from an ancestor commit is an explicit increment base: verify ancestry,
    # record the change scope, and proceed. A baseline from an unrelated or
    # descendant commit is BLOCKED — never silently recaptured (A03).
    ancestor_verified = False
    if baseline_sha and head_sha and baseline_sha != head_sha:
        is_ancestor = git_is_ancestor(root, baseline_sha, head_sha)
        if is_ancestor is True:
            ancestor_verified = True
            reasons.append("baseline_is_ancestor_of_head_increment_mode")
            gate["changed_files_vs_baseline"] = git_changed_files(
                root, baseline_sha, head_sha)
        elif is_ancestor is False:
            gate["verdict"] = "BLOCKED"
            reasons.append("baseline_sha_mismatch_requires_increment_review")
            return _finish_run(gate, reasons, evidence)
        else:
            gate["verdict"] = "BLOCKED"
            reasons.append("baseline_ancestor_check_unavailable")
            return _finish_run(gate, reasons, evidence)
    baseline_usable = bool(baseline_sha and head_sha
                           and (baseline_sha == head_sha or ancestor_verified))

    sentinel_prefixes = load_sentinel_prefixes()
    gate["security_sentinel_count"] = len(sentinel_prefixes)

    scope = args.scope
    if scope in ("backend", "all"):
        junit_path = evidence["junit"]
        nodeid_report = evidence["nodeid_report"]
        run = run_pytest(root, junit_path, args.timeout, args.pytest_args.split(),
                         nodeid_report=nodeid_report)
        gate["pytest"] = {"returncode": run["returncode"], "elapsed_s": run["elapsed"],
                          "timeout": run["timeout"], "child_identity": run.get("child"),
                          "logs": {"junit_xml": str(junit_path),
                                   "pytest_stdout": str(evidence["pytest_stdout"]),
                                   "pytest_stderr": str(evidence["pytest_stderr"]),
                                   "nodeid_report": str(nodeid_report)}}
        # A06/F05: logs persist in the evidence dir; the tmp dir no longer
        # swallows the junit report, and partial timeout output is kept.
        evidence["pytest_stdout"].write_text(run["stdout"], encoding="utf-8")
        evidence["pytest_stderr"].write_text(run["stderr"], encoding="utf-8")
        report = parse_junit(junit_path, root)
        report["returncode"] = run["returncode"]
        executed_records = None
        if nodeid_report.is_file():
            try:
                executed_records = json.loads(
                    nodeid_report.read_text(encoding="utf-8")).get("records")
                if not isinstance(executed_records, list):
                    executed_records = None
                    reasons.append("nodeid_report_unparseable")
            except (OSError, ValueError):
                executed_records = None
                reasons.append("nodeid_report_unparseable")
        else:
            reasons.append("nodeid_report_missing")
        enforce_required = not args.allow_missing_required_nodes
        if enforce_required and junit_nodes and executed_records is None:
            # A04/A05 need per-phase records; without them required coverage
            # cannot be proven -> FAIL rather than fuzzy-match.
            reasons.append("required_evidence_missing")

        verdict_part = evaluate_report_against_baseline(
            report, baseline, head_sha, junit_nodes,
            args.allow_missing_required_nodes, reasons,
            baseline_usable=baseline_usable,
            executed_records=executed_records,
            sentinel_prefixes=sentinel_prefixes)
        gate.update({k: v for k, v in verdict_part.items() if k != "verdict"})
        gate["failed"] = len(gate["failed_ids"])
        _escalate(gate, verdict_part["verdict"])
        gate["collection_errors"] = len(report.get("errors", []))
        gate["skipped_count"] = len(report.get("skipped", []))

        if selftest_nodes:
            selftest_results = run_required_selftests(
                Path(__file__).resolve(), selftest_nodes,
                min(args.timeout, 900))
            gate["selftest_results"] = selftest_results
            if any(not r.get("passed") for r in selftest_results):
                _escalate(gate, "FAIL")
                reasons.append("required_selftest_failed")

        pyf = {"ok": True, "undefined_name": [], "ignored_counted_by_category": {}}
        if not args.skip_static:
            pyf = run_pyflakes(root)
        if not pyf.get("ok"):
            _escalate(gate, "FAIL")
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
                _escalate(gate, "FAIL")
                reasons.append("new_pyflakes_undefined_name")

    if scope in ("frontend", "all"):
        lint = run_eslint(root)
        if not lint.get("ok"):
            _escalate(gate, "BLOCKED")
            reasons.append(f"eslint_{lint.get('reason')}")
        else:
            if lint.get("fatal_count"):
                _escalate(gate, "FAIL")
                reasons.append("eslint_fatal_error")
            baseline_lint = set(((baseline or {}).get("static_findings") or {})
                                .get("eslint_noundef") or [])
            new_lint = sorted(set(lint["noundef"]) - baseline_lint)
            gate["eslint"] = {"noundef_count": len(lint["noundef"]),
                              "new_vs_baseline": new_lint,
                              "returncode": lint["returncode"],
                              "fatal_count": lint.get("fatal_count", 0)}
            if new_lint:
                _escalate(gate, "FAIL")
                reasons.append("new_eslint_noundef")
            else:
                # findings exist but all match the baseline: acceptable
                _escalate(gate, "PASS")

    return _finish_run(gate, reasons, evidence)


def cmd_from_result(args) -> int:
    """A09: re-emit a saved authoritative result without re-running anything.
    A parse or schema failure is a stable structured FAIL, never a rerun."""
    result_path = Path(args.from_result)
    gate: dict = {"gate_version": GATE_VERSION, "mode": "from_result",
                  "root": str(Path(args.root).resolve()),
                  "result_path": str(result_path), "reasons": []}
    try:
        doc = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        gate["verdict"] = "FAIL"
        gate["reasons"].append(f"result_unreadable:{type(exc).__name__}")
        return emit(gate)
    problems = validate_gate_result(doc)
    if problems:
        gate["verdict"] = "FAIL"
        gate["reasons"].append("result_schema_violation")
        gate["schema_problems"] = problems
        return emit(gate)
    gate.update(doc)
    gate["mode"] = "from_result"
    gate.setdefault("verdict", "FAIL")
    return emit(gate)


# ---------------------------------------------------------------- lanes 0927V1
#
# FAST  — offline selection for a local change: explicit mapping + module
#         convention expansion, security sentinels always in, whitelisted
#         child env, phase timing, zero install (A10/A12/A13/A16).
# REPLAY — identity-gated real service: reuse only a service whose
#         /api/runtime-readiness build id matches the tree (A14); a mismatched
#         same-port impostor is refused and the lane starts its OWN instance
#         on a private port/runtime, never killing existing listeners (A15).
# LIVE  — explicit opt-in only; read-only /models probe, no chat, no server
#         management; evidence-reuse key recorded, execution deferred until an
#         authorized LIVE window (8002 MTPLX absent -> honest BLOCKED).


def load_lane_triggers(root: Path | None) -> dict:
    """Per-root overrides win (fixtures), else the gate-adjacent lane file."""
    candidates = []
    if root is not None:
        candidates.append(root / "tools" / "acceptance" / "lane_triggers.json")
    candidates.append(Path(__file__).resolve().parent / "lane_triggers.json")
    for path in candidates:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except (OSError, ValueError):
            continue
    return {"format": "lane_triggers/1", "fast": {"path_prefixes": {}}}


def select_lane_tests(root: Path, changed_files: list[str], plan: str = "fast",
                      triggers: dict | None = None) -> dict:
    """A12: explicit selection engine — trigger mapping first, then the
    module convention (app module foo.py -> tests/test_foo*.py), untestable
    files REPORTED (never silently dropped), security sentinels always in,
    and never a last-failed (--lf) rerun."""
    if triggers is None:
        triggers = load_lane_triggers(root)
    lane = (triggers or {}).get(plan) or {}
    prefixes = lane.get("path_prefixes") or {}
    always = lane.get("always_selected")
    if always is None:
        always = [prefix + ".py" for prefix in load_sentinel_prefixes()]

    selected: list[str] = []
    selected_reasons: list[dict] = []
    unmapped_no_tests: list[dict] = []
    tests_dir = root / "tests"

    def add(tests: list[str], reason: str, path: str) -> None:
        for test in tests:
            if test not in selected:
                selected.append(test)
            selected_reasons.append(
                {"path": path, "test": test, "reason": reason})

    for changed in changed_files:
        normalized = changed.replace(os.sep, "/")
        matched = False
        best = ""
        for prefix in sorted(prefixes, key=len, reverse=True):
            if normalized.startswith(prefix):
                best = prefix
                break
        if best:
            add(list(prefixes[best].get("tests") or []),
                f"mapping:{best}", normalized)
            matched = True
        if not matched:
            name = Path(normalized).stem
            if normalized.startswith("services/api/app/") and name not in ("__init__",):
                convention = sorted(
                    p.relative_to(root).as_posix()
                    for p in tests_dir.rglob(f"test_{name}*.py")
                ) if tests_dir.is_dir() else []
                if convention:
                    add(convention, f"module_convention:{name}", normalized)
                    matched = True
        if not matched:
            unmapped_no_tests.append({
                "path": normalized,
                "reason": "no_lane_mapping_and_no_module_test_file_found",
            })
    for entry in always:
        if entry not in selected:
            selected.append(entry)
            selected_reasons.append({
                "path": "", "test": entry,
                "reason": "always_selected_security_sentinel"})
    return {
        "selected": selected,
        "selected_reasons": selected_reasons,
        "unmapped_no_tests": unmapped_no_tests,
        "selection_mode": "explicit_selection_not_last_failed",
        "last_failed_only": False,
        "not_run_scope": ("lane selection is partial by design; the full "
                          "suite remains its own lane and is never implied"),
    }


def compute_toolchain_identity(root: Path) -> dict:
    """A13: what 'environment unchanged' means here. Python has no lock file
    (only frontend/package-lock.json exists) — recorded honestly as such."""
    lock = root / "frontend" / "package-lock.json"
    lock_digest = None
    if lock.is_file():
        lock_digest = hashlib.sha256(lock.read_bytes()).hexdigest()
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "venv_prefix": str(Path(sys.prefix).resolve()),
        "package_lock_sha256": lock_digest,
        "python_lockfile": "none_in_repo",
    }


def _lane_deps_unchanged(evidence_base: Path, identity: dict) -> bool | None:
    """Compare with the previous cycle's recorded identity; None on first run."""
    state_path = evidence_base / "lane_state.json"
    previous = None
    try:
        previous = json.loads(
            state_path.read_text(encoding="utf-8")).get("toolchain_identity")
    except (OSError, ValueError):
        previous = None
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(state_path, {"toolchain_identity": identity,
                                        "updated_at": now_iso()})
    except OSError:
        pass
    if previous is None:
        return None
    return previous == identity


_LANE_ENV_MODEL_PREFIXES = ("WORKBENCH_AI_", "WORKBENCH_MONITORING_AI_")
_LANE_ENV_STRIPPED_EXACT = ("WORKBENCH_RUNTIME_DIR", "WORKBENCH_INBOX",
                            "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR",
                            "WORKBENCH_INCLUDE_REFERENCE_PROJECTS",
                            "WORKBENCH_PADDLE_OCR_MAX_CONCURRENCY")


def offline_lane_audit(child_env: dict, parent_env_keys: set[str]) -> dict:
    """A16: certify that no model credential/endpoint/proxy/live-path variable
    survives into the lane's child process environment."""

    def sensitive(key: str) -> bool:
        return (key.startswith(_LANE_ENV_MODEL_PREFIXES)
                or key in _LANE_ENV_STRIPPED_EXACT
                or "proxy" in key.lower())

    stripped = sorted(key for key in parent_env_keys
                      if sensitive(key) and key not in child_env)
    leaked = sorted(key for key in child_env if sensitive(key))
    return {"stripped_keys": stripped, "leaked_keys": leaked,
            "clean": not leaked,
            "network": "offline_selection_only_no_external_endpoints"}


def probe_service_identity(base_url: str, expected_build_id: str | None,
                           timeout: int = 5) -> dict:
    """A14/A15: identity probe against /api/runtime-readiness (read-only)."""
    live = _get_json(f"{base_url.rstrip('/')}/api/runtime-readiness",
                     timeout=timeout)
    reachable = isinstance(live, dict) and "_error" not in live
    identity_ok = bool(reachable and expected_build_id
                       and live.get("backend_build_id") == expected_build_id)
    reasons = []
    if not reachable:
        reasons.append("runtime_readiness_unreachable")
    elif not identity_ok:
        reasons.append("backend_build_id_mismatch")
    return {"base_url": base_url, "reachable": reachable,
            "identity_ok": identity_ok, "live": live, "reasons": reasons}


def service_process_owner(port: int) -> dict:
    """Best-effort listener ownership via system tools; NEVER signals."""
    try:
        proc = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                              capture_output=True, text=True, timeout=10)
        pids = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"pid": None, "owned": None, "note": "lsof_unavailable"}
    if not pids:
        return {"pid": None, "owned": None, "note": "no_listener"}
    command = ""
    try:
        ps = subprocess.run(["ps", "-p", pids[0], "-o", "command="],
                            capture_output=True, text=True, timeout=10)
        command = ps.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    # ownership identity is primary via build id; the command line is context
    return {"pid": pids[0], "command": command[:300], "owned": None,
            "note": "identity_is_primary_check"}


def _default_replay_spawn(root: Path, expected_build_id: str | None,
                          runtime_dir: Path):
    """Launch the REAL backend on a free port with the given private runtime."""
    free = socket.socket()
    free.bind(("127.0.0.1", 0))
    port = free.getsockname()[1]
    free.close()
    env = _gate_test_env(root, Path(__file__).resolve().parent)
    env["WORKBENCH_RUNTIME_DIR"] = str(runtime_dir)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(root / "services" / "api"), str(root)])
    log_path = runtime_dir / "replay_backend.log"
    log_handle = open(log_path, "ab")
    try:
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host",
             "127.0.0.1", "--port", str(port)],
            cwd=str(root), stdout=log_handle, stderr=log_handle,
            env=env, start_new_session=True)
    finally:
        log_handle.close()

    def stop() -> None:
        import signal
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    deadline = time.monotonic() + 120
    probe = {"reachable": False}
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        probe = probe_service_identity(f"http://127.0.0.1:{port}",
                                       expected_build_id, timeout=3)
        if probe["reachable"]:
            break
        time.sleep(1.0)
    return port, stop, {"pid": process.pid, "runtime_dir": str(runtime_dir),
                        "log": str(log_path), "ready_probe": probe}


def ensure_replay_service(root: Path | None,
                          expected_build_id: str | None = None,
                          preferred_port: int | None = None,
                          spawn=None, probe_timeout: int = 5) -> dict:
    """A14/A15: reuse ONLY an identity-matching service; on refusal start the
    lane's own instance (private port+runtime). Never kills any listener."""
    if expected_build_id is None and root is not None:
        expected_build_id = backend_fingerprint(root)
    refusal: list[str] = []
    if preferred_port:
        probe = probe_service_identity(f"http://127.0.0.1:{preferred_port}",
                                       expected_build_id, timeout=probe_timeout)
        if probe["reachable"]:
            owner = service_process_owner(preferred_port)
            if not probe["identity_ok"]:
                refusal.append("backend_build_id_mismatch")
            if not refusal:
                return {"reused": True, "port": preferred_port,
                        "base_url": probe["base_url"], "own_port": None,
                        "refusal_reasons": [], "identity_ok": True,
                        "runtime_dir": None, "ownership": owner}
        else:
            refusal.extend(probe["reasons"])
    else:
        refusal.append("no_existing_service_provided")
    runtime_dir = Path(tempfile.mkdtemp(prefix="wb_replay_runtime_"))
    if spawn is None:
        def spawn(runtime_dir_arg: Path):
            return _default_replay_spawn(root, expected_build_id, runtime_dir_arg)
    own_port, stop, meta = spawn(runtime_dir)
    own_probe = probe_service_identity(f"http://127.0.0.1:{own_port}",
                                       expected_build_id, timeout=10)
    return {"reused": False, "port": own_port, "own_port": own_port,
            "base_url": f"http://127.0.0.1:{own_port}",
            "refusal_reasons": refusal,
            "identity_ok": own_probe["identity_ok"],
            "runtime_dir": meta.get("runtime_dir", str(runtime_dir)),
            "stop": stop, "process": meta}


def cmd_plan_fast(args) -> int:
    started = time.monotonic()
    requested = Path(args.root).resolve()
    root, fallback = resolve_root(requested)
    reasons: list[str] = [fallback] if fallback else []
    head_sha = git_head(root)
    baseline_path = Path(args.baseline) if args.baseline else \
        root / "tools/acceptance/known_failures_0926v1.json"
    baseline = load_baseline(baseline_path)
    baseline_sha = (baseline or {}).get("baseline_sha") \
        if baseline and baseline.get("format") != "UNREADABLE" else None
    gate: dict = {"gate_version": GATE_VERSION, "mode": "run", "plan": "fast",
                  "scope": "backend", "requested_root": str(requested),
                  "root": str(root), "head_sha": head_sha,
                  "tested_commit": head_sha, "baseline_commit": baseline_sha,
                  "reasons": reasons, "python": sys.version.split()[0],
                  "known_failures_waivers": "none_in_fast_lane"}
    evidence = _prepare_run_evidence(root, getattr(args, "evidence_dir", None))

    env_check_started = time.monotonic()
    identity = compute_toolchain_identity(root)
    deps_unchanged = _lane_deps_unchanged(evidence["dir"].parent, identity)
    parent_keys = set(os.environ.keys())
    child_env = _gate_test_env(root, Path(__file__).resolve().parent)
    audit = offline_lane_audit(child_env, parent_keys)
    gate["toolchain_identity"] = identity
    gate["deps_unchanged"] = deps_unchanged
    gate["install_actions"] = []
    gate["offline_audit"] = audit
    gate["phases"] = {"env_check_s": round(time.monotonic() - env_check_started, 3)}
    if not audit["clean"]:
        reasons.append("offline_env_audit_leaked")
        gate["verdict"] = "FAIL"
        return _finish_run(gate, reasons, evidence)

    selection_started = time.monotonic()
    triggers = load_lane_triggers(root)
    changed: list[str] = []
    if head_sha:
        worktree = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=30)
        if worktree.returncode == 0:
            changed.extend(line for line in worktree.stdout.splitlines()
                           if line.strip())
    if baseline_sha and head_sha and baseline_sha != head_sha \
            and git_is_ancestor(root, baseline_sha, head_sha):
        changed.extend(git_changed_files(root, baseline_sha, head_sha))
        gate["changed_files_vs_baseline"] = git_changed_files(
            root, baseline_sha, head_sha)
    seen: set[str] = set()
    changed = [c for c in changed if not (c in seen or seen.add(c))]
    gate["changed_files"] = changed
    selection = select_lane_tests(root, changed, plan="fast", triggers=triggers)
    gate.update({key: selection[key] for key in
                 ("selected", "selected_reasons", "unmapped_no_tests",
                  "selection_mode", "last_failed_only", "not_run_scope")})
    gate["phases"]["selection_s"] = round(
        time.monotonic() - selection_started, 3)
    if not selection["selected"]:
        gate["verdict"] = "BLOCKED"
        reasons.append("fast_lane_no_tests_selected")
        return _finish_run(gate, reasons, evidence)

    pytest_started = time.monotonic()
    nodeid_report = evidence["nodeid_report"]
    run = run_pytest(root, evidence["junit"], args.timeout, selection["selected"],
                     nodeid_report=nodeid_report)
    gate["pytest"] = {"returncode": run["returncode"], "elapsed_s": run["elapsed"],
                      "timeout": run["timeout"], "child_identity": run.get("child"),
                      "logs": {"junit_xml": str(evidence["junit"]),
                               "pytest_stdout": str(evidence["pytest_stdout"]),
                               "pytest_stderr": str(evidence["pytest_stderr"]),
                               "nodeid_report": str(nodeid_report)}}
    evidence["pytest_stdout"].write_text(run["stdout"], encoding="utf-8")
    evidence["pytest_stderr"].write_text(run["stderr"], encoding="utf-8")
    gate["phases"]["pytest_s"] = round(time.monotonic() - pytest_started, 3)

    report = parse_junit(evidence["junit"], root)
    report["returncode"] = run["returncode"]
    executed_records = None
    if nodeid_report.is_file():
        try:
            executed_records = json.loads(
                nodeid_report.read_text(encoding="utf-8")).get("records")
            if not isinstance(executed_records, list):
                executed_records = None
        except (OSError, ValueError):
            executed_records = None
    verdict_part = evaluate_report_against_baseline(
        report, None, head_sha, [], True, reasons,
        baseline_usable=False, executed_records=executed_records,
        sentinel_prefixes=load_sentinel_prefixes())
    gate.update({k: v for k, v in verdict_part.items() if k != "verdict"})
    gate["failed"] = len(gate["failed_ids"])
    _escalate(gate, verdict_part["verdict"])
    gate["collection_errors"] = len(report.get("errors", []))
    gate["skipped_count"] = len(report.get("skipped", []))
    gate["phases"]["total_s"] = round(time.monotonic() - started, 3)
    return _finish_run(gate, reasons, evidence)


def cmd_plan_replay(args) -> int:
    requested = Path(args.root).resolve()
    root, fallback = resolve_root(requested)
    reasons: list[str] = [fallback] if fallback else []
    head_sha = git_head(root)
    gate: dict = {"gate_version": GATE_VERSION, "mode": "run", "plan": "replay",
                  "scope": "backend", "requested_root": str(requested),
                  "root": str(root), "head_sha": head_sha,
                  "tested_commit": head_sha, "baseline_commit": None,
                  "reasons": reasons, "python": sys.version.split()[0]}
    evidence = _prepare_run_evidence(root, getattr(args, "evidence_dir", None))
    triggers = load_lane_triggers(root)
    replay_tests = ((triggers.get("replay") or {}).get("tests")) or []
    gate["selected"] = replay_tests
    if not replay_tests:
        gate["verdict"] = "BLOCKED"
        reasons.append("replay_lane_no_tests_configured")
        return _finish_run(gate, reasons, evidence)

    decision = ensure_replay_service(
        root, preferred_port=getattr(args, "replay_port", None))
    gate["replay_service"] = {
        "reused": decision["reused"], "port": decision["port"],
        "base_url": decision["base_url"],
        "refusal_reasons": decision["refusal_reasons"],
        "identity_ok": decision["identity_ok"],
        "runtime_dir": decision["runtime_dir"],
        "ownership": decision.get("ownership")}
    if not decision["identity_ok"]:
        stop = decision.get("stop")
        if callable(stop):
            stop()
        gate["verdict"] = "BLOCKED"
        reasons.append("replay_instance_identity_failed")
        return _finish_run(gate, reasons, evidence)

    run = run_pytest(root, evidence["junit"], args.timeout, replay_tests,
                     nodeid_report=evidence["nodeid_report"])
    gate["pytest"] = {"returncode": run["returncode"], "elapsed_s": run["elapsed"],
                      "timeout": run["timeout"], "child_identity": run.get("child"),
                      "logs": {"junit_xml": str(evidence["junit"]),
                               "pytest_stdout": str(evidence["pytest_stdout"]),
                               "pytest_stderr": str(evidence["pytest_stderr"]),
                               "nodeid_report": str(evidence["nodeid_report"])}}
    evidence["pytest_stdout"].write_text(run["stdout"], encoding="utf-8")
    evidence["pytest_stderr"].write_text(run["stderr"], encoding="utf-8")
    report = parse_junit(evidence["junit"], root)
    report["returncode"] = run["returncode"]
    executed_records = None
    if evidence["nodeid_report"].is_file():
        try:
            executed_records = json.loads(
                evidence["nodeid_report"].read_text(encoding="utf-8")).get("records")
            if not isinstance(executed_records, list):
                executed_records = None
        except (OSError, ValueError):
            executed_records = None
    verdict_part = evaluate_report_against_baseline(
        report, None, gate["head_sha"], [], True, reasons,
        baseline_usable=False, executed_records=executed_records,
        sentinel_prefixes=load_sentinel_prefixes())
    gate.update({k: v for k, v in verdict_part.items() if k != "verdict"})
    gate["failed"] = len(gate["failed_ids"])
    _escalate(gate, verdict_part["verdict"])
    gate["collection_errors"] = len(report.get("errors", []))
    gate["skipped_count"] = len(report.get("skipped", []))
    gate["smoke"] = ("skipped_by_default_desktop_safety"
                     if not getattr(args, "with_smoke", False)
                     else "see separate check_smoke run")
    stop = decision.get("stop")
    if callable(stop):
        stop()  # the lane's own instance is cleaned up; reused ones untouched
    return _finish_run(gate, reasons, evidence)


def cmd_plan_live(args) -> int:
    requested = Path(args.root).resolve()
    root, fallback = resolve_root(requested)
    reasons: list[str] = [fallback] if fallback else []
    head_sha = git_head(root)
    gate: dict = {"gate_version": GATE_VERSION, "mode": "run", "plan": "live",
                  "scope": "backend", "requested_root": str(requested),
                  "root": str(root), "head_sha": head_sha,
                  "tested_commit": head_sha, "baseline_commit": None,
                  "reasons": reasons, "python": sys.version.split()[0]}
    evidence = _prepare_run_evidence(root, getattr(args, "evidence_dir", None))
    if not getattr(args, "live", False):
        gate["verdict"] = "BLOCKED"
        reasons.append("live_requires_explicit_opt_in")
        return _finish_run(gate, reasons, evidence)
    triggers = load_lane_triggers(root)
    required_models = (triggers.get("live") or {}).get("required_models") or []
    probe_results = []
    for entry in required_models:
        # read-only /models probe; never a chat request, never a restart
        live = _get_json(f"{str(entry.get('base_url')).rstrip('/')}/models",
                         timeout=5)
        ids = [m.get("id") for m in (live.get("data") or [])] \
            if isinstance(live, dict) and "_error" not in live else []
        ok = entry.get("model") in ids
        probe_results.append({"role": entry.get("role"), "base_url": entry.get("base_url"),
                              "model": entry.get("model"), "listed": ok})
        if not ok:
            reasons.append(f"model_unreachable:{entry.get('role')}")
    gate["model_probe"] = probe_results
    gate["model_probe_mode"] = "read_only_models_listing_no_chat"
    if any(not p["listed"] for p in probe_results):
        gate["verdict"] = "BLOCKED"
        return _finish_run(gate, reasons, evidence)
    reuse_key = hashlib.sha256(json.dumps({
        "backend_build_id": backend_fingerprint(root),
        "frontend_fingerprint": frontend_fingerprint(root),
        "toolchain_identity": compute_toolchain_identity(root),
        "required_models": required_models,
    }, sort_keys=True).encode("utf-8")).hexdigest()
    gate["evidence_reuse_key"] = reuse_key
    gate["verdict"] = "BLOCKED"
    reasons.append("live_execution_deferred_evidence_key_recorded")
    return _finish_run(gate, reasons, evidence)


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
    parser.add_argument("--evidence-dir", default=None,
                        help="directory for authoritative run results (default <root>/runs/acceptance_gate)")
    parser.add_argument("--plan", choices=["fast", "replay", "live"], default=None,
                        help="lane plan (0927V1): fast offline selection, replay identity-gated real service, live opt-in")
    parser.add_argument("--live", action="store_true",
                        help="explicit opt-in required for --plan live")
    parser.add_argument("--replay-port", type=int, default=None,
                        help="existing backend port to identity-check for --plan replay")
    parser.add_argument("--with-smoke", action="store_true",
                        help="run browser smoke during replay (default off: desktop safety)")
    sub = parser.add_mutually_exclusive_group()
    sub.add_argument("--baseline-capture", action="store_true")
    sub.add_argument("--check-runtime", action="store_true")
    sub.add_argument("--check-smoke", action="store_true")
    sub.add_argument("--from-result", default=None, metavar="PATH",
                     help="re-read a saved result.json (A09); never re-runs the suite")
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
    try:
        args.root = str(discover_repo_root(Path(args.root).resolve()))
    except RootAmbiguityError as exc:
        gate = {"gate_version": GATE_VERSION, "mode": "run",
                "root_discovery": _ROOT_DISCOVERY_NOTE,
                "root_candidates": exc.candidates,
                "verdict": "BLOCKED",
                "reasons": ["root_ambiguous_multi_candidate",
                            "pass an explicit --root naming the exact repo"]}
        return emit(gate)
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
    if args.from_result:
        return cmd_from_result(args)
    if args.plan == "fast":
        return cmd_plan_fast(args)
    if args.plan == "replay":
        return cmd_plan_replay(args)
    if args.plan == "live":
        return cmd_plan_live(args)
    if args.selftest:
        return cmd_selftest(args)
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
