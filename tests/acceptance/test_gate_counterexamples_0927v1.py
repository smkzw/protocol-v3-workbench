"""0927V1 gate counterexamples P01-P16, verbatim contracts from the review kit
(runs/requirements_v2_20260919/t17_round19_review_kit_0927v1, evidence/
review_probe_results.json: 18 observations, 14 disagree).

Rule (red line 8): every counterexample first proved RED against the current
HEAD, then the implementation was fixed, then the same tests went GREEN.
P01/P02/P03/P10 are the review's controls and must stay green.

All fixtures live in pytest tmp dirs; runs are offline, zero real models
(A16), env vars set here are reverted by monkeypatch.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

import pytest

from tests.acceptance import _gate_testkit as kit


def _gate_argv(root, extra: list[str] | None = None) -> list[str]:
    argv = ["--root", str(root), "--scope", "backend", "--pytest-args", ".",
            "--skip-static", "--allow-missing-required-nodes"]
    return argv + (extra or [])


# --------------------------------------------------------------- controls


def test_p01_control_clean_suite_passes(tmp_path):
    kit.write_suite(tmp_path, {"test_passes.py": kit.PASS_BODY})
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path))
    assert doc is not None
    assert doc["verdict"] == "PASS", doc


def test_p02_control_unknown_failure_fails(tmp_path):
    kit.write_suite(tmp_path, {"test_fails.py": kit.FAIL_BODY})
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path))
    assert doc is not None
    assert doc["verdict"] == "FAIL", doc
    assert doc["failed_ids"], doc


def test_p03_control_collection_error_fails(tmp_path):
    kit.write_suite(tmp_path, {"test_broken.py": "def test_broken(:\n    pass\n"})
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path))
    assert doc is not None
    assert doc["verdict"] == "FAIL", doc
    assert doc.get("collection_errors", 0) >= 1, doc


def test_p10_control_known_failure_same_head(tmp_path):
    kit.write_suite(tmp_path, {"test_fails.py": kit.FAIL_BODY})
    sha = kit.git_repo_commit_all(tmp_path)
    gate = kit.load_gate_module()
    junit = tmp_path / "probe.xml"
    gate.run_pytest(tmp_path, junit, 120, ["."])
    report = gate.parse_junit(junit, tmp_path)
    report["returncode"] = 1
    bad = report["failures"] + report["errors"]
    assert bad, "fixture must produce a failure record"
    baseline = {
        "format": "known_failures_0926v1/1",
        "baseline_sha": sha,
        "pytest_failures": [
            {"nodeid": rec["nodeid"], "fingerprint": rec["fingerprint"], "caveat": ""}
            for rec in bad
        ],
        "static_findings": {},
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path, ["--baseline", str(baseline_path)]))
    assert doc is not None
    assert doc["verdict"] == "PASS_WITH_KNOWN_FAILURES", doc


# ----------------------------------------------------------- counterexamples


def test_p04_required_node_skipped_must_not_pass(tmp_path):
    """A04: a required testcase skipped via pytest.mark.skip must FAIL the
    gate, not count as covered (review P04: expected FAIL, observed PASS)."""
    kit.write_suite(tmp_path, {
        "test_keep.py": kit.PASS_BODY,
        "test_optional.py": (
            "import pytest\n\n\n"
            "@pytest.mark.skip(reason='gate probe: required test skipped')\n"
            "def test_must_not_be_skipped():\n    assert True\n"
        ),
    })
    required = tmp_path / "required_nodes.json"
    required.write_text(json.dumps(["test_optional.py::test_must_not_be_skipped"]),
                        encoding="utf-8")
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path, [
        "--required-nodes", str(required),
        "--allow-missing-required-nodes",  # tolerate ABSENT, never SKIP (A04)
    ]))
    assert doc is not None
    assert doc["verdict"] == "FAIL", doc
    assert "required_node_skipped" in doc["reasons"], doc


def test_p05_wrong_class_same_leaf_must_not_satisfy(tmp_path):
    """A05: another class with the same test leaf must not complete the
    required coverage (review P05: expected FAIL, observed PASS)."""
    kit.write_suite(tmp_path, {
        "test_cls.py": (
            "class TestOther:\n"
            "    def test_checked(self):\n"
            "        assert True\n"
        ),
    })
    required = tmp_path / "required_nodes.json"
    required.write_text(json.dumps(["test_cls.py::TestTarget::test_checked"]),
                        encoding="utf-8")
    # enforcement on: A05 tolerance must not extend to another class's
    # same-leaf test standing in for the required node
    _, doc = kit.run_gate_cli(["--root", str(tmp_path), "--scope", "backend",
                               "--pytest-args", ".", "--skip-static",
                               "--required-nodes", str(required)])
    assert doc is not None
    assert doc["verdict"] == "FAIL", doc
    assert "required_node_missing" in doc["reasons"], doc


def test_p06_missing_required_parameter_must_not_satisfy(tmp_path):
    """A05: only a different parametrize bracket ran -> the specific required
    parameter never ran (review P06: expected FAIL, observed PASS)."""
    kit.write_suite(tmp_path, {
        "test_param.py": (
            "import pytest\n\n\n"
            '@pytest.mark.parametrize("value", ["beta"])\n'
            "def test_case(value):\n"
            "    assert value == 'beta'\n"
        ),
    })
    required = tmp_path / "required_nodes.json"
    required.write_text(json.dumps(["test_param.py::test_case[alpha]"]),
                        encoding="utf-8")
    # enforcement on: a sibling parameter never satisfies the required one
    _, doc = kit.run_gate_cli(["--root", str(tmp_path), "--scope", "backend",
                               "--pytest-args", ".", "--skip-static",
                               "--required-nodes", str(required)])
    assert doc is not None
    assert doc["verdict"] == "FAIL", doc
    assert "required_node_missing" in doc["reasons"], doc


def test_p07_zero_tests_with_rc0_must_fail(tmp_path):
    """A06: a parsed-but-empty report with returncode 0 is contradictory and
    must FAIL (review P07: expected FAIL, observed PASS)."""
    gate = kit.load_gate_module()
    report = {"ok": True, "total": 0, "cases": [], "failures": [],
              "errors": [], "skipped": [], "returncode": 0}
    reasons: list[str] = []
    result = gate.evaluate_report_against_baseline(report, None, None, [], True, reasons)
    assert result["verdict"] == "FAIL", result
    assert "no_tests_in_report" in reasons, reasons


def test_p08_missing_report_through_cmd_run_is_structured(tmp_path, monkeypatch, capsys):
    """A06/F05: report_missing early-exit path must return the complete stable
    structure (no KeyError, no lost verdict); review P08 observed
    KeyError:baseline_not_run_count."""
    gate = kit.load_gate_module()
    kit.write_suite(tmp_path, {"test_passes.py": kit.PASS_BODY})

    def fake_run_pytest(root, junit_path, timeout, pytest_args, nodeid_report=None):
        return {"returncode": 0, "stdout": "", "stderr": "", "elapsed": 0.1,
                "timeout": False, "child": {}}

    monkeypatch.setattr(gate, "run_pytest", fake_run_pytest)
    args = argparse.Namespace(
        root=str(tmp_path), scope="backend", pytest_args=".", timeout=120,
        baseline=None, required_nodes=None, allow_missing_required_nodes=True,
        skip_static=True, evidence_dir=str(tmp_path / "evidence"),
        from_result=None,
    )
    rc = gate.cmd_run(args)  # must not raise
    out = capsys.readouterr().out
    assert "GATE_JSON=" in out, out
    doc = json.loads(out.split("GATE_JSON=", 1)[1])
    assert doc["verdict"] == "FAIL", doc
    assert "report_missing" in doc["reasons"], doc
    assert rc == 1
    for key in ("ran", "failed_ids", "known_matched", "dissolved",
                "suspected_data_class", "suspected_fingerprint_drift",
                "missing_required_nodes", "baseline_not_run_count"):
        assert key in doc, (key, doc)
    assert gate.validate_gate_result(doc) == [], gate.validate_gate_result(doc)


def test_p09_collection_error_through_real_cli_keeps_structure(tmp_path):
    """A06/F05: a collection error through the real CLI must still emit the
    full GATE_JSON + a validating result.json (review P09 observed
    KeyError:baseline_not_run_count with all evidence lost)."""
    kit.write_suite(tmp_path, {"test_broken.py": "def test_broken(:\n    pass\n"})
    proc, doc = kit.run_gate_cli(_gate_argv(tmp_path))
    assert "GATE_JSON=" in proc.stdout, (proc.stdout, proc.stderr[-2000:])
    assert "KeyError" not in proc.stderr, proc.stderr[-2000:]
    assert doc is not None and doc["verdict"] == "FAIL", doc
    gate = kit.load_gate_module()
    result_path = doc.get("result_path")
    assert result_path and os.path.isfile(result_path), doc
    result_doc = json.loads(open(result_path, encoding="utf-8").read())
    assert gate.validate_gate_result(result_doc) == [], result_doc


def test_p11_ancestor_baseline_not_blocked(tmp_path):
    """A02/F01: HEAD moved past the baseline commit -> verify ancestry and
    proceed; never auto-recapture (review P11: expected explicit ancestor-base
    comparison, observed BLOCKED before pytest)."""
    kit.write_suite(tmp_path, {"test_passes.py": kit.PASS_BODY})
    base_sha = kit.git_repo_commit_all(tmp_path, "baseline commit")
    (tmp_path / "test_extra_pass.py").write_text(kit.PASS_BODY, encoding="utf-8")
    head_sha = kit.git_repo_commit_all(tmp_path, "increment commit")
    assert base_sha != head_sha
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps({
        "format": "known_failures_0926v1/1",
        "baseline_sha": base_sha,
        "pytest_failures": [],
        "static_findings": {},
    }), encoding="utf-8")
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path, ["--baseline", str(baseline_path)]))
    assert doc is not None
    assert doc["verdict"] == "PASS", doc
    assert "baseline_sha_mismatch_requires_increment_review" not in doc["reasons"], doc
    assert doc.get("tested_commit") == head_sha, doc
    assert doc.get("baseline_commit") == base_sha, doc
    assert "test_extra_pass.py" in (doc.get("changed_files_vs_baseline") or []), doc


def test_p12_broken_pyflakes_not_false_green(tmp_path, monkeypatch):
    """A07: rc=1 with empty stdout + import-error stderr means the tool never
    ran -> ok=False, not an empty-but-ok result (review P12 observed ok=True)."""
    gate = kit.load_gate_module()
    (tmp_path / "services" / "api" / "app").mkdir(parents=True)
    real_run = subprocess.run

    class FakeCompleted:
        returncode = 1
        stdout = ""
        stderr = "/usr/bin/python: No module named 'pyflakes'"

    def fake_run(cmd, **kwargs):
        if "pyflakes" in cmd:
            return FakeCompleted()
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    result = gate.run_pyflakes(tmp_path)
    assert result.get("ok") is False, result
    assert result.get("reason") == "pyflakes_failed", result


def _make_fake_eslint(frontend, script_body: str) -> None:
    bin_dir = frontend / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    bin_path = bin_dir / "eslint"
    bin_path.write_text("#!/bin/sh\n" + script_body, encoding="utf-8")
    bin_path.chmod(0o755)


def test_p13_eslint_execution_failure_not_ok(tmp_path):
    """A07: eslint exiting 2 (config/crash) must be ok=False, not an empty
    noundef pass (review P13 observed ok=True, returncode 2)."""
    gate = kit.load_gate_module()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    _make_fake_eslint(frontend, "echo 'eslint crashed' >&2\nexit 2\n")
    result = gate.run_eslint(tmp_path)
    assert result.get("ok") is False, result
    assert result.get("reason") == "eslint_failed", result


def test_p14_eslint_corrupt_json_not_ok(tmp_path):
    """A07: unparseable eslint JSON must be ok=False (review P14 observed
    ok=True with parse_error)."""
    gate = kit.load_gate_module()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    _make_fake_eslint(frontend, "printf 'not JSON'\nexit 0\n")
    result = gate.run_eslint(tmp_path)
    assert result.get("ok") is False, result
    assert result.get("reason") == "eslint_report_unparseable", result


def test_p14b_eslint_fatal_counts_as_finding(tmp_path):
    """A07: fatal:true messages are findings even with rc 0."""
    gate = kit.load_gate_module()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    _make_fake_eslint(frontend, (
        "echo '[{\"filePath\":\"/x/y.js\",\"messages\":[{\"ruleId\":null,"
        "\"fatal\":true,\"severity\":2,\"message\":\"Parsing error: Unexpected token\","
        "\"line\":1,\"column\":1}]}]'\nexit 0\n"
    ))
    result = gate.run_eslint(tmp_path)
    assert result.get("ok") is True, result
    assert result.get("fatal_count", 0) == 1, result


def test_p15_offline_pytest_env_whitelist(tmp_path, monkeypatch):
    """A10/F02: the pytest child must not inherit live WORKBENCH_*/proxy env
    (review P15 observed live_runtime_inherited=True, proxy_inherited=True)."""
    monkeypatch.setenv("WORKBENCH_GATE_PROBE_SENTINEL", "live-leak")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    kit.write_suite(tmp_path, {"test_env.py": (
        "import os\n\n\n"
        "def test_offline_env_is_whitelisted():\n"
        "    assert 'WORKBENCH_GATE_PROBE_SENTINEL' not in os.environ\n"
        "    assert 'https_proxy' not in os.environ\n"
        "    assert 'HTTPS_PROXY' not in os.environ\n"
    )})
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path))
    assert doc is not None
    assert doc["verdict"] == "PASS", doc
    assert not doc.get("failed_ids"), doc


def test_p16_multi_root_ambiguity_blocked(tmp_path):
    """A08/F06: two candidate repos under --root must BLOCK with an explicit
    ambiguity reason, never silently pick one (review P16 observed
    'aaa-wrong' picked)."""
    for name in ("aaa-wrong", "bbb-right"):
        marker = tmp_path / name / "tools" / "acceptance"
        marker.mkdir(parents=True)
        (marker / "required_nodes.json").write_text("[]", encoding="utf-8")
    _, doc = kit.run_gate_cli(_gate_argv(tmp_path))
    assert doc is not None
    assert doc["verdict"] == "BLOCKED", doc
    assert "root_ambiguous_multi_candidate" in doc["reasons"], doc


def test_run_pytest_timeout_keeps_evidence_and_kills_own_group(tmp_path):
    """Red line 6-2: on timeout the gate must keep partial logs, record child
    identity, kill ONLY its own process group, and return a stable verdict —
    never an empty-stdout guess. Fixture: many fast tests print dots first so
    partial stdout is guaranteed non-empty, then a sleeper trips the limit."""
    fast = "".join(
        f"def test_fast_{i}():\n    assert {i} >= 0\n\n" for i in range(220)
    )
    kit.write_suite(tmp_path, {
        "test_many.py": fast,
        "test_sleep.py": "import time\n\n\ndef test_slow():\n    time.sleep(120)\n",
    })
    gate = kit.load_gate_module()
    started = time.monotonic()
    run = gate.run_pytest(tmp_path, tmp_path / "junit.xml", 6, ["test_many.py", "test_sleep.py"])
    elapsed = time.monotonic() - started
    assert run["timeout"] is True, run
    assert run["returncode"] is None, run
    assert elapsed < 60, elapsed
    child = run.get("child") or {}
    assert child.get("pid") and child.get("pgid"), child
    assert child.get("argv") and child.get("cwd"), child
    assert run["stdout"], "partial stdout was discarded on timeout"
    # the killed child's process group must be gone
    with pytest.raises(ProcessLookupError):
        os.killpg(int(child["pgid"]), 0)
