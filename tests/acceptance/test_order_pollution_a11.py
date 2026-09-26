"""A11 permanent regression: the generation-context route-digest tests must
pass under ANY collection order relative to tests/test_ai_execution_policy.py.

Evidence chain (2026-09-27, this repo, HEAD 5b4c8c1):
- polluter: tests/test_ai_execution_policy.py — its COLLECTION-TIME import
  (from services.api.app.main import app, line 27) seeds
  ai_provider_settings.json (enabled cloud fallback chain) into the current
  WORKBENCH_RUNTIME_DIR via main.py:1840 import-time store bootstrap;
- victim: tests/test_medical_writing_generation_context_v2.py digest tests —
  their _policy_runner resolvers do not set test_only_provider_injection, so
  route_identity_snapshot(refresh=True, task_type=medical_writing_revision)
  consults the live settings (ai_execution_policy.py:458-464,
  _capture_revision_cloud_route :359-383) and overrides both pinned routes —
  digests become identical and the policy-change assertion fails.
- Victim solo (settings file absent) passes; under the polluter's import it
  fails in EVERY collection order (import order = collection order), which is
  the honest import-order-pollution signature. Fix: the harness boundary flag
  test_only_provider_injection=True in _policy_runner (the product's
  documented freeze, ai_execution_policy.py:446-452). No assertion changed.

Each step runs a REAL subprocess pytest with a hard timeout (red line 6-2);
offline, zero models (A16); the subprocess env deliberately omits
WORKBENCH_RUNTIME_DIR so tests/conftest.py provisions a fresh private runtime
per run — no state leaks between steps.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

VICTIM = ("tests/test_medical_writing_generation_context_v2.py"
          "::GenerationContextDescriptorTests::test_policy_change_changes_digest")
POLLUTER = ("tests/test_ai_execution_policy.py"
            "::AiExecutionPolicyTests::test_ai_result_reads_fail_closed_before_runner_access")

ORDER_PLUGIN = ["-p", "pytest_order_control"]
SUBPROCESS_TIMEOUT_S = 240


def _run_nodes(*nodes: str, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", str(Path.home())),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "PYTHONPATH": "services/api:.:tools/acceptance",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    cmd = [sys.executable, "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider",
           *(extra or [])]
    return subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, capture_output=True,
                          text=True, timeout=SUBPROCESS_TIMEOUT_S)


def test_a11_step1_victim_alone_passes():
    proc = _run_nodes(VICTIM)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_a11_step2_polluter_before_victim_passes():
    # pre-fix this was RED in every order: collecting the polluter seeds the
    # live settings that override the victim's pinned routes.
    proc = _run_nodes(POLLUTER, VICTIM)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_a11_step3_victim_before_polluter_passes():
    proc = _run_nodes(VICTIM, POLLUTER)
    assert proc.returncode == 0, proc.stdout + proc.stderr[-1500:]


def test_a11_step4_seeded_random_orders_pass():
    for seed in (20260927, 1, 42):
        proc = _run_nodes(POLLUTER, VICTIM, extra=[*ORDER_PLUGIN, f"--order-seed={seed}"])
        assert proc.returncode == 0, (seed, proc.stdout + proc.stderr[-1500:])
