#!/usr/bin/env python3
"""Contract tests for the runtime-owned oMLX workload gate.

These tests load the *proposed* gate module (not the live global gate) via a
temporary import path, use a throwaway SQLite database, and never launch real
OCR or translation. They prove the manager-frozen contract:

1. ``config`` returns exact models, limits 8/8/16, schema, and DB path.
2. A caller model that does not match the authoritative selection is rejected
   before any lease is granted (fail-closed).
3. No lease row exists in the DB after a rejection.
4. A granted lease's ``model`` always equals the gate authoritative default.
5. ``release`` cleans up in a ``finally`` path, leaving zero active leases.
6. Admission arithmetic honours OCR<=8, translation<=8, total<=16.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
# The contract under test is the gate module the shipped client actually loads
# (services.api.app.omlx_workload_gate_client -> WORKBENCH_OMLX_WORKLOAD_GATE_TOOL
# override, else the shared runtime tool). The historical artifacts/ copy was a
# local-only proposal snapshot that never entered version control, so pointing
# the tests at it broke every clean checkout.
GATE_TOOL = Path(
    os.environ.get(
        "WORKBENCH_OMLX_WORKLOAD_GATE_TOOL",
        str(Path.home() / ".codex" / "tools" / "omlx_workload_gate.py"),
    )
).expanduser()


def _load_gate_module():
    """Load the runtime gate as an isolated module so the live global gate is untouched."""
    spec = importlib.util.spec_from_file_location("omlx_workload_gate_proposed", str(GATE_TOOL))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["omlx_workload_gate_proposed"] = mod
    spec.loader.exec_module(mod)
    return mod


class GateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not GATE_TOOL.is_file():
            raise unittest.SkipTest(
                f"runtime oMLX workload gate tool not installed: {GATE_TOOL}"
            )
        cls.gate_mod = _load_gate_module()

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "test_gate.sqlite3")
        self.gate = self.gate_mod.WorkloadGate(self.db_path)

    def tearDown(self):
        self._tmpdir.cleanup()

    # -- 1. config returns exact contract --
    def test_config_returns_exact_models_and_limits(self):
        cfg = self.gate.config()
        self.assertEqual(cfg["schema"], "omlx_gate_selection_v1")
        self.assertEqual(
            cfg["models"],
            {"ocr": "GLM-OCR-bf16", "translation": "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"},
        )
        self.assertEqual(cfg["limits"], {"ocr": 8, "translation": 8, "total": 16})
        self.assertEqual(cfg["db"], str(Path(self.db_path)))

    def test_selection_alias_matches_config(self):
        self.assertEqual(self.gate.selection(), self.gate.config())

    # -- 2. caller model mismatch rejected before lease --
    def test_acquire_rejects_nonmatching_ocr_model(self):
        with self.assertRaises(ValueError) as ctx:
            self.gate.acquire("ocr", "test-owner", model="some-other-model", timeout=0.1)
        self.assertIn("model override rejected", str(ctx.exception))

    def test_acquire_rejects_nonmatching_translation_model(self):
        with self.assertRaises(ValueError) as ctx:
            self.gate.acquire(
                "translation",
                "test-owner",
                model="caller-selected-translation-model",
                timeout=0.1,
            )
        self.assertIn("model override rejected", str(ctx.exception))

    def test_run_rejects_nonmatching_model(self):
        """The run() method delegates to acquire() so the same guard applies."""
        # We can't easily call run() without a real command, but we can verify
        # that acquire() (which run() calls) rejects before any DB write.
        with self.assertRaises(ValueError):
            self.gate.acquire("ocr", "test-owner", model="wrong", timeout=0.1)

    # -- 3. no lease on rejection --
    def test_no_lease_row_after_rejection(self):
        try:
            self.gate.acquire("ocr", "test-owner", model="wrong", timeout=0.1)
        except ValueError:
            pass
        status = self.gate.status()
        self.assertEqual(status["active"]["ocr"], 0)
        self.assertEqual(status["active"]["translation"], 0)
        self.assertEqual(len(status["leases"]), 0)

    # -- 4. default model in granted lease --
    def test_granted_lease_uses_authoritative_model(self):
        lease = self.gate.acquire("ocr", "test-owner", timeout=1.0)
        self.assertEqual(lease["model"], "GLM-OCR-bf16")
        self.assertEqual(lease["model"], self.gate_mod.DEFAULT_MODELS["ocr"])
        self.gate.release(lease["lease_id"])

    def test_granted_translation_lease_uses_authoritative_model(self):
        lease = self.gate.acquire("translation", "test-owner", timeout=1.0)
        self.assertEqual(
            lease["model"], "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"
        )
        self.gate.release(lease["lease_id"])

    def test_none_model_grants_authoritative_default(self):
        """model=None must use the authoritative default, not fail."""
        lease = self.gate.acquire("ocr", "test-owner", model=None, timeout=1.0)
        self.assertEqual(lease["model"], self.gate_mod.DEFAULT_MODELS["ocr"])
        self.gate.release(lease["lease_id"])

    # -- 5. finally release leaves zero leases --
    def test_finally_release_leaves_zero_leases(self):
        lease = self.gate.acquire("ocr", "test-owner", timeout=1.0)
        try:
            pass  # simulate work
        finally:
            self.gate.release(lease["lease_id"])
        status = self.gate.status()
        self.assertEqual(status["active"]["ocr"], 0)
        self.assertEqual(len(status["leases"]), 0)

    def test_release_after_exception(self):
        """Even if the operation raises, release must still execute."""
        lease = self.gate.acquire("translation", "test-owner", timeout=1.0)
        try:
            raise RuntimeError("simulated operation failure")
        except RuntimeError:
            pass
        finally:
            self.gate.release(lease["lease_id"])
        status = self.gate.status()
        self.assertEqual(status["active"]["translation"], 0)

    # -- 6. 8/8/16 admission arithmetic --
    def test_ocr_limit_8(self):
        leases = []
        for i in range(8):
            l = self.gate.acquire("ocr", f"ocr-worker-{i}", timeout=1.0)
            self.assertIn("lease_id", l)
            leases.append(l)
        # 9th should fail immediately with no wait
        rejected = self.gate.acquire("ocr", "ocr-worker-9", timeout=0.01, wait=False)
        self.assertNotIn("lease_id", rejected)
        self.assertFalse(rejected.get("granted", True))
        for l in leases:
            self.gate.release(l["lease_id"])

    def test_translation_limit_8(self):
        leases = []
        for i in range(8):
            l = self.gate.acquire("translation", f"tr-worker-{i}", timeout=1.0)
            self.assertIn("lease_id", l)
            leases.append(l)
        rejected = self.gate.acquire(
            "translation", "tr-worker-9", timeout=0.01, wait=False
        )
        self.assertNotIn("lease_id", rejected)
        for l in leases:
            self.gate.release(l["lease_id"])

    def test_total_limit_16(self):
        leases = []
        for i in range(8):
            leases.append(
                self.gate.acquire("ocr", f"ocr-{i}", timeout=1.0)
            )
        for i in range(8):
            leases.append(
                self.gate.acquire("translation", f"tr-{i}", timeout=1.0)
            )
        # 17th lease should be rejected regardless of kind
        rejected = self.gate.acquire("ocr", "extra", timeout=0.01, wait=False)
        self.assertNotIn("lease_id", rejected)
        rejected_tr = self.gate.acquire(
            "translation", "extra-tr", timeout=0.01, wait=False
        )
        self.assertNotIn("lease_id", rejected_tr)
        for l in leases:
            self.gate.release(l["lease_id"])

    def test_combined_8_8_peak(self):
        """Simulate 8 OCR + 8 translation concurrent; peak total must be 16."""
        results = []
        errors = []

        def worker(kind, idx):
            try:
                lease = self.gate.acquire(kind, f"peak-{kind}-{idx}", timeout=2.0)
                results.append(lease)
                time.sleep(0.05)
                if "lease_id" in lease:
                    self.gate.release(lease["lease_id"])
            except Exception as exc:
                errors.append(exc)

        threads = []
        for i in range(8):
            threads.append(threading.Thread(target=worker, args=("ocr", i)))
        for i in range(8):
            threads.append(threading.Thread(target=worker, args=("translation", i)))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        granted = [r for r in results if "lease_id" in r]
        self.assertEqual(len(granted), 16)
        # After all threads finish, gate should be empty
        status = self.gate.status()
        self.assertEqual(status["total_active"], 0)

    # -- CLI compatibility --
    def test_cli_config_command(self):
        """The config CLI subcommand must work and return the contract."""
        import json
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(GATE_TOOL),
                "--db",
                self.db_path,
                "config",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(proc.returncode, 0)
        cfg = json.loads(proc.stdout)
        self.assertEqual(cfg["schema"], "omlx_gate_selection_v1")
        self.assertEqual(cfg["limits"]["total"], 16)

    def test_cli_acquire_no_model_flag(self):
        """The acquire CLI must succeed without --model (uses authoritative default)."""
        import json
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(GATE_TOOL),
                "--db",
                self.db_path,
                "acquire",
                "--kind",
                "ocr",
                "--owner",
                "cli-test",
                "--timeout",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lease = json.loads(proc.stdout)
        self.assertEqual(lease["model"], "GLM-OCR-bf16")
        # cleanup
        self.gate.release(lease["lease_id"])

    def test_cli_acquire_rejects_model_flag(self):
        """The acquire CLI must reject --model (flag removed)."""
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(GATE_TOOL),
                "--db",
                self.db_path,
                "acquire",
                "--kind",
                "ocr",
                "--owner",
                "cli-test",
                "--model",
                "should-not-work",
                "--timeout",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main()
