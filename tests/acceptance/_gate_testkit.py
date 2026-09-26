"""Shared helpers for the 0927V1 gate counterexample tests.

Loads the REAL tools/acceptance/run_acceptance_gate.py by file path so tests
exercise the shipped script. Offline, zero third-party deps, zero real models
(A16). Fixture trees live in pytest tmp dirs and are cleaned by pytest.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_SCRIPT = REPO_ROOT / "tools" / "acceptance" / "run_acceptance_gate.py"
GATE_DIR = REPO_ROOT / "tools" / "acceptance"
SCHEDULER_SCRIPT = REPO_ROOT / "services" / "api" / "app" / "model_phase_scheduler.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_gate_module():
    return load_module(GATE_SCRIPT, "_gate_under_test")


def load_scheduler_module():
    return load_module(SCHEDULER_SCRIPT, "_model_phase_scheduler_under_test")


def run_gate_cli(argv: list[str], timeout: int = 300):
    """Run the real gate script in a subprocess; return (proc, doc_or_None)."""
    proc = subprocess.run(
        [sys.executable, str(GATE_SCRIPT), *argv],
        capture_output=True, text=True, timeout=timeout,
    )
    match = re.search(r"GATE_JSON=(\{.*\})", proc.stdout)
    return proc, (json.loads(match.group(1)) if match else None)


def write_suite(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = .\n", encoding="utf-8")


PASS_BODY = "def test_always_passes():\n    assert True\n"
FAIL_BODY = "def test_always_fails():\n    assert False, 'deliberate failure'\n"


def git_repo_commit_all(root: Path, message: str = "fixture commit") -> str:
    """git init + commit everything under root; return the commit sha."""
    def git(*argv: str) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *argv],
            capture_output=True, text=True, timeout=60, check=True,
        )
        return proc.stdout

    git("init", "-q")
    git("add", "-A")
    git("-c", "user.email=gate-probe@example.invalid",
        "-c", "user.name=gate-probe",
        "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", message)
    return git("rev-parse", "HEAD").strip()
