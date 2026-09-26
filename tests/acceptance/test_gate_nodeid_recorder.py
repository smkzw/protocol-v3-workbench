"""A04/A05: the gate nodeid recorder plugin records exact native nodeids with
setup/call/teardown outcomes, and required-test satisfaction is judged on
them (never on class-stripped / param-stripped approximations).

Plugin runs under the repo's real pytest via -p gate_nodeid_recorder;
offline, zero deps, zero models.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.acceptance import _gate_testkit as kit

MIX_BODY = """import pytest


def test_ok():
    assert True


@pytest.mark.skip(reason="probe skip")
def test_skipme():
    assert True


@pytest.mark.xfail(reason="probe xfail")
def test_xf():
    assert False


@pytest.mark.parametrize("value", ["a", "b"])
def test_par(value):
    assert value == "a"
"""


def _records_for(tmp_path, body: str, filename: str = "test_mix.py") -> list[dict]:
    kit.write_suite(tmp_path, {filename: body})
    report_path = tmp_path / "nodeid_report.json"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(kit.GATE_DIR) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", ".", "-q", "-p", "no:cacheprovider",
         "-p", "gate_nodeid_recorder", f"--nodeid-report={report_path}"],
        cwd=str(tmp_path), capture_output=True, text=True, env=env, timeout=180,
    )
    assert report_path.is_file(), (proc.stdout, proc.stderr[-2000:])
    return json.loads(report_path.read_text(encoding="utf-8"))["records"]


def _phases(records: list[dict], nodeid: str) -> set[tuple[str, str, bool]]:
    return {
        (r["when"], r["outcome"], bool(r.get("wasxfail")))
        for r in records if r["nodeid"] == nodeid
    }


def test_recorder_writes_exact_native_nodeids(tmp_path):
    records = _records_for(tmp_path, MIX_BODY)
    assert _phases(records, "test_mix.py::test_ok") >= {
        ("setup", "passed", False), ("call", "passed", False)}
    # skipped: setup skipped, call never ran
    skip_phases = _phases(records, "test_mix.py::test_skipme")
    assert ("setup", "skipped", False) in skip_phases
    assert not any(when == "call" for when, _, _ in skip_phases)
    # xfail: call outcome skipped with wasxfail marker
    assert ("call", "skipped", True) in _phases(records, "test_mix.py::test_xf")
    # parametrize: each parameter is its own exact nodeid
    assert ("call", "passed", False) in _phases(records, "test_mix.py::test_par[a]")
    assert ("call", "failed", False) in _phases(records, "test_mix.py::test_par[b]")


def _gate():
    return kit.load_gate_module()


def test_required_status_passes_only_on_exact_pass(tmp_path):
    gate = _gate()
    records = _records_for(tmp_path, MIX_BODY)
    ok, status = gate.required_node_status(records, "test_mix.py::test_ok")
    assert ok is True and status == "ran_passed", (ok, status)


def test_required_status_rejects_skip(tmp_path):
    gate = _gate()
    records = _records_for(tmp_path, MIX_BODY)
    ok, status = gate.required_node_status(records, "test_mix.py::test_skipme")
    assert ok is False and status == "required_node_skipped", (ok, status)


def test_required_status_rejects_xfail(tmp_path):
    gate = _gate()
    records = _records_for(tmp_path, MIX_BODY)
    ok, status = gate.required_node_status(records, "test_mix.py::test_xf")
    assert ok is False and status == "required_node_skipped", (ok, status)


def test_required_status_exact_parameter_only():
    gate = _gate()
    records = [
        {"nodeid": "t.py::test_par[a]", "when": "setup", "outcome": "passed", "wasxfail": False},
        {"nodeid": "t.py::test_par[a]", "when": "call", "outcome": "passed", "wasxfail": False},
    ]
    ok, status = gate.required_node_status(records, "t.py::test_par[a]")
    assert ok is True and status == "ran_passed"
    ok_b, status_b = gate.required_node_status(records, "t.py::test_par[b]")
    assert ok_b is False and status_b == "required_node_missing", (ok_b, status_b)


def test_required_status_class_exact_only():
    gate = _gate()
    records = [
        {"nodeid": "t.py::TestOther::test_checked", "when": "setup", "outcome": "passed", "wasxfail": False},
        {"nodeid": "t.py::TestOther::test_checked", "when": "call", "outcome": "passed", "wasxfail": False},
    ]
    ok, status = gate.required_node_status(records, "t.py::TestTarget::test_checked")
    assert ok is False and status == "required_node_missing", (ok, status)
