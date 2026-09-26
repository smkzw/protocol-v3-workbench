"""FAST lane counterexamples (0927V1 three-lane plan; A10/A12/A13/A16).

Contracts proven red against the pre-lane HEAD, then green after the lane
implementation lands:
- A10 unit control: the pytest child env whitelist strips WORKBENCH_*/proxies;
- A10 import-time: the session binds app runtime private (test_a10_import_binding.py);
- A12: unmapped changed files expand to their module tests, untestable files
  are reported (never silently dropped), and selection is explicit — not --lf;
- A13: toolchain identity recorded; second cycle with unchanged toolchain
  reports deps_unchanged=True and zero install/download actions;
- A16: the FAST lane certifies offline — model credentials and proxies are
  stripped before any child process runs.

All fixtures are tmp trees with their own git repo; zero network, zero models.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from tests.acceptance import _gate_testkit as kit

FAST_TRIGGERS = {
    "format": "lane_triggers/1",
    "fast": {
        "path_prefixes": {
            "services/api/app/lane_demo": {
                "module": "lane_demo",
                "tests": ["tests/test_lane_demo.py"],
            },
        },
        "always_selected": ["tests/test_lane_demo.py"],
    },
}


def _make_fast_fixture(tmp_path: Path) -> None:
    (tmp_path / "tools" / "acceptance").mkdir(parents=True)
    (tmp_path / "tools" / "acceptance" / "required_nodes.json").write_text("[]",
                                                                            encoding="utf-8")
    (tmp_path / "tools" / "acceptance" / "lane_triggers.json").write_text(
        json.dumps(FAST_TRIGGERS), encoding="utf-8")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package-lock.json").write_text(
        '{"lockfileVersion": 3, "packages": {}}\n', encoding="utf-8")
    (tmp_path / "services" / "api" / "app").mkdir(parents=True)
    (tmp_path / "services" / "api" / "app" / "lane_demo.py").write_text(
        "VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lane_demo.py").write_text(
        "import os\n\n\n"
        "def test_fast_lane_env_is_clean():\n"
        "    for key in os.environ:\n"
        "        assert not key.startswith('WORKBENCH_'), key\n"
        "        assert 'proxy' not in key.lower(), key\n"
        "    assert os.environ.get('PATH'), 'PATH must survive the whitelist'\n",
        encoding="utf-8",
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    kit.git_repo_commit_all(tmp_path, "fast fixture base")
    # an UNCOMMITTED local change: the FAST lane triggers on the working tree
    demo = tmp_path / "services" / "api" / "app" / "lane_demo.py"
    demo.write_text("VALUE = 1\n# local edit\n", encoding="utf-8")


def _fast_argv(tmp_path: Path) -> list[str]:
    return ["--root", str(tmp_path), "--plan", "fast", "--skip-static",
            "--allow-missing-required-nodes"]


# ------------------------------------------------- A10 unit control (green now)


def test_a10_control_gate_test_env_strips_live_vars(tmp_path, monkeypatch):
    gate = kit.load_gate_module()
    monkeypatch.setenv("WORKBENCH_AI_API_KEY", "live-key")
    monkeypatch.setenv("WORKBENCH_RUNTIME_DIR", "/live/runtime")
    monkeypatch.setenv("WORKBENCH_INBOX", "/live/inbox.json")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    env = gate._gate_test_env(tmp_path, tmp_path / "plugin")
    for key in ("WORKBENCH_AI_API_KEY", "WORKBENCH_RUNTIME_DIR", "WORKBENCH_INBOX",
                "HTTP_PROXY", "https_proxy"):
        assert key not in env, key
    assert env["PYTHONPATH"].split(os.pathsep)[0] == "services/api"


# --------------------------------------------------------------- A12 selection


def test_a12_unmapped_change_expands_to_module_and_reports_not_run(tmp_path):
    gate = kit.load_gate_module()
    (tmp_path / "services" / "api" / "app").mkdir(parents=True)
    (tmp_path / "services" / "api" / "app" / "orchid_metric.py").write_text(
        "VALUE = 1\n", encoding="utf-8")
    (tmp_path / "services" / "api" / "app" / "ghost_module.py").write_text(
        "VALUE = 2\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_orchid_metric.py").write_text(
        "def test_orchid():\n    assert True\n", encoding="utf-8")
    triggers = {"format": "lane_triggers/1", "fast": {"path_prefixes": {}}}

    result = gate.select_lane_tests(
        tmp_path,
        ["services/api/app/orchid_metric.py", "services/api/app/ghost_module.py"],
        plan="fast", triggers=triggers)

    # module convention expansion: the changed module's own test file is in
    assert "tests/test_orchid_metric.py" in result["selected"], result
    # untestable changed file is REPORTED, never silently dropped (A12)
    ghost = [u for u in result["unmapped_no_tests"]
             if u["path"].endswith("ghost_module.py")]
    assert ghost and ghost[0].get("reason"), result
    # explicit selection, not a last-failed (--lf) rerun
    assert result["selection_mode"] == "explicit_selection_not_last_failed", result

    # security sentinels are always selected, even with zero changes (红线9)
    empty = gate.select_lane_tests(tmp_path, [], plan="fast", triggers=triggers)
    assert any("test_writing_reference_numeric_fidelity" in s
               for s in empty["selected"]), empty


# --------------------------------------------------- A13/A16 fast lane result


def test_a13_second_cycle_records_zero_install(tmp_path):
    _make_fast_fixture(tmp_path)
    proc, first = kit.run_gate_cli(_fast_argv(tmp_path))
    assert first is not None, (proc.stdout, proc.stderr[-1500:])
    assert first["verdict"] == "PASS", first
    assert first["deps_unchanged"] is None, first  # first cycle: no prior state
    assert first["install_actions"] == [], first
    identity = first["toolchain_identity"]
    assert identity["package_lock_sha256"], identity

    proc, second = kit.run_gate_cli(_fast_argv(tmp_path))
    assert second is not None, (proc.stdout, proc.stderr[-1500:])
    assert second["verdict"] == "PASS", second
    assert second["deps_unchanged"] is True, second  # toolchain unchanged
    assert second["install_actions"] == [], second

    # a toolchain change (lockfile edited) must flip the flag, not hide it
    lock = tmp_path / "frontend" / "package-lock.json"
    lock.write_text('{"lockfileVersion": 3, "packages": {}, "x": 1}\n',
                    encoding="utf-8")
    proc, third = kit.run_gate_cli(_fast_argv(tmp_path))
    assert third is not None, (proc.stdout, proc.stderr[-1500:])
    assert third["verdict"] == "PASS", third
    assert third["deps_unchanged"] is False, third
    assert third["install_actions"] == [], third  # recorded, never auto-installed


def test_a16_fast_lane_certifies_offline(tmp_path, monkeypatch):
    _make_fast_fixture(tmp_path)
    monkeypatch.setenv("WORKBENCH_AI_API_KEY", "live-key")
    monkeypatch.setenv("WORKBENCH_AI_BASE_URL", "http://live.example.invalid")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    proc, doc = kit.run_gate_cli(_fast_argv(tmp_path))
    assert doc is not None, (proc.stdout, proc.stderr[-1500:])
    assert doc["verdict"] == "PASS", doc
    assert doc["selected"], doc
    assert doc["offline_audit"]["clean"] is True, doc
    assert "WORKBENCH_AI_API_KEY" in doc["offline_audit"]["stripped_keys"], doc
    assert set(doc["phases"]) >= {"env_check_s", "selection_s", "pytest_s", "total_s"}, doc
