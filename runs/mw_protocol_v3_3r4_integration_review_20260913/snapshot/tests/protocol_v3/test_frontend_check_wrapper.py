from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIR = _ROOT / "scripts/qc/protocol_v3"
sys.path.insert(0, str(_SCRIPT_DIR))

from verify_toolchain_rebuild import (  # noqa: E402
    ManifestError,
    MANIFEST_PATH,
    load_manifest,
    validate_manifest_hashes,
)

import run_frontend_checks as frontend_wrapper  # noqa: E402


def _copy_manifest(repo_root: Path, manifest_root: Path) -> Path:
    manifest_text = (manifest_root / MANIFEST_PATH).read_text(encoding="utf-8")
    target_dir = repo_root / MANIFEST_PATH.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = repo_root / MANIFEST_PATH
    target.write_text(manifest_text, encoding="utf-8")
    return target


class FrontendCheckWrapperTests(unittest.TestCase):
    def test_wrapper_has_no_package_manager_override(self) -> None:
        """The wrapper must not expose a CLI override for the package manager or scripts.

        The manifest is the only execution authority; the argparse parser may
        only accept the bounded manifest actions; none may supply a package
        manager, lock file, or arbitrary script.
        """
        parser = frontend_wrapper._build_parser()
        actions = {action.dest for action in parser._actions}
        forbidden = {"manifest", "package_manager", "script", "lock", "npm", "pnpm"}
        self.assertFalse(forbidden & actions, f"wrapper must not accept overrides: {forbidden & actions}")

    def test_install_command_comes_only_from_manifest(self) -> None:
        manifest = load_manifest(_ROOT)
        expected = manifest["frontend"]["scripts"]["install"]
        self.assertEqual(
            expected,
            ["npm", "ci", "--ignore-scripts", "--audit=false", "--fund=false"],
        )
        parser = frontend_wrapper._build_parser()
        args = parser.parse_args(["--install"])
        self.assertTrue(args.install)
        self.assertFalse(hasattr(args, "package_manager"))

    def test_plan_unit_flag_and_legacy_alias_share_one_bounded_action(self) -> None:
        parser = frontend_wrapper._build_parser()
        self.assertTrue(parser.parse_args(["--unit"]).run_unit)
        self.assertTrue(parser.parse_args(["--run-unit"]).run_unit)

    def test_alternate_manifest_cli_argument_is_rejected(self) -> None:
        parser = frontend_wrapper._build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--manifest", "/private/tmp/alternate.json"])

    def test_node_binary_environment_cannot_override_unit_command(self) -> None:
        manifest = load_manifest(_ROOT)
        runtime = {
            "node": {"path": "/validated/node", "actual": "22.22.3"},
            "npm": {"path": "/validated/npm-cli.js", "actual": "10.9.8"},
        }
        fake = {
            "command": manifest["frontend"]["scripts"]["test:unit"],
            "returncode": 0,
            "stdout": "tests executed",
            "stderr": "",
        }
        with mock.patch.dict(os.environ, {"NODE_BINARY": "/usr/bin/true"}), mock.patch.object(
            frontend_wrapper, "_run_manifest_command", return_value=fake
        ) as runner:
            result = frontend_wrapper.run_unit_tests(_ROOT, manifest, runtime)
        runner.assert_called_once_with(_ROOT, manifest, "test:unit", runtime)
        self.assertEqual(result["command"], manifest["frontend"]["scripts"]["test:unit"])
        self.assertNotIn("/usr/bin/true", result["command"])

    def test_runtime_binary_hash_blocks_path_spoof(self) -> None:
        manifest = load_manifest(_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            fake_node = Path(tmp) / "node"
            fake_npm = Path(tmp) / "npm"
            fake_node.write_text("#!/bin/sh\necho v22.22.3\n", encoding="utf-8")
            fake_npm.write_text("#!/bin/sh\necho 10.9.8\n", encoding="utf-8")

            def fake_which(binary: str) -> str:
                return str(fake_node if binary == "node" else fake_npm)

            with mock.patch.object(frontend_wrapper.shutil, "which", side_effect=fake_which):
                with self.assertRaisesRegex(
                    frontend_wrapper.FrontendCheckError,
                    "executable sha256 mismatch",
                ):
                    frontend_wrapper.check_runtime_versions(_ROOT, manifest)

    def test_runtime_binary_provenance_matches_manifest(self) -> None:
        manifest = load_manifest(_ROOT)
        runtime = frontend_wrapper.check_runtime_versions(_ROOT, manifest)
        for binary in ("node", "npm"):
            self.assertTrue(Path(runtime[binary]["path"]).is_absolute())
            self.assertEqual(
                runtime[binary]["sha256"],
                manifest["frontend"]["runtime_binaries"][binary]["sha256"],
            )

    def test_wrapper_hash_precheck_matches_disk(self) -> None:
        manifest = load_manifest(_ROOT)
        result = validate_manifest_hashes(_ROOT, manifest=manifest)
        self.assertTrue(all(check["ok"] for check in result["checks"]))

    def test_check_inventory_matches_manifest_counts(self) -> None:
        manifest = load_manifest(_ROOT)
        runtime = frontend_wrapper.check_runtime_versions(_ROOT, manifest)
        result = frontend_wrapper.check_inventory(_ROOT, manifest, runtime)
        expected = manifest["frontend"]["test_inventory"]["counts"]
        actual = result["inventory"]["counts"]
        self.assertEqual(actual, expected)
        self.assertEqual(actual["total"], expected["total"])
        self.assertEqual(actual["vitest"] + actual["node"], actual["total"])

    def test_wrapper_fails_closed_on_stale_inventory_count(self) -> None:
        manifest = copy.deepcopy(load_manifest(_ROOT))
        manifest["frontend"]["test_inventory"]["counts"] = {
            "total": 999,
            "vitest": 998,
            "node": 1,
        }
        runtime = frontend_wrapper.check_runtime_versions(_ROOT, manifest)
        with self.assertRaisesRegex(
            frontend_wrapper.FrontendCheckError,
            "inventory count 'total' mismatch",
        ):
            frontend_wrapper.check_inventory(_ROOT, manifest, runtime)

    def test_inventory_cannot_hide_a_real_test_from_independent_discovery(self) -> None:
        manifest = load_manifest(_ROOT)
        runtime = frontend_wrapper.check_runtime_versions(_ROOT, manifest)
        actual = frontend_wrapper._run_manifest_command(
            _ROOT,
            manifest,
            "test:inventory:json",
            runtime,
        )
        inventory = json.loads(actual["stdout"])
        victim = next(
            item for item in inventory["tests"]
            if item["path"].startswith("src/features/medical-monitoring/")
        )
        victim["path"] = "src/features/fake/hidden-substitute.test.mjs"
        forged = {**actual, "stdout": json.dumps(inventory)}
        with mock.patch.object(
            frontend_wrapper,
            "_run_manifest_command",
            return_value=forged,
        ), self.assertRaisesRegex(
            frontend_wrapper.FrontendCheckError,
            "independent frontend test discovery mismatch",
        ):
            frontend_wrapper.check_inventory(_ROOT, manifest, runtime)

    def test_every_action_stops_before_execution_when_inventory_gate_fails(self) -> None:
        manifest = load_manifest(_ROOT)
        for action, callable_name in (
            ("--install", "run_install"),
            ("--unit", "run_unit_tests"),
            ("--build", "run_build"),
        ):
            with self.subTest(action=action), mock.patch.object(
                frontend_wrapper, "load_manifest", return_value=manifest
            ), mock.patch.object(
                frontend_wrapper, "validate_manifest_hashes", return_value={"checks": []}
            ), mock.patch.object(
                frontend_wrapper, "check_runtime_versions", return_value={}
            ), mock.patch.object(
                frontend_wrapper,
                "check_inventory",
                side_effect=frontend_wrapper.FrontendCheckError("inventory count mismatch"),
            ), mock.patch.object(frontend_wrapper, callable_name) as action_runner:
                self.assertEqual(frontend_wrapper.main([action]), 1)
                action_runner.assert_not_called()

    def test_combined_actions_repeat_all_gates_immediately_before_each_action(self) -> None:
        manifest = load_manifest(_ROOT)
        sequence: list[str] = []

        def mark(name: str, value: object):
            def _inner(*_args, **_kwargs):
                sequence.append(name)
                return value
            return _inner

        good_hashes = {"checks": [{"ok": True}]}
        good_runtime = {
            "node": {"actual": "22.22.3", "path": "/validated/node"},
            "npm": {"actual": "10.9.8", "path": "/validated/npm-cli.js"},
        }
        good_inventory = {
            "inventory": {"counts": {"total": 49, "vitest": 3, "node": 46}}
        }
        action_result = {"returncode": 0, "passed": True, "stdout": "", "stderr": ""}
        with mock.patch.object(
            frontend_wrapper, "load_manifest", side_effect=mark("load", manifest)
        ), mock.patch.object(
            frontend_wrapper, "validate_manifest_hashes", side_effect=mark("hash", good_hashes)
        ), mock.patch.object(
            frontend_wrapper, "check_runtime_versions", side_effect=mark("runtime", good_runtime)
        ), mock.patch.object(
            frontend_wrapper, "check_inventory", side_effect=mark("count", good_inventory)
        ), mock.patch.object(
            frontend_wrapper, "run_install", side_effect=mark("install", action_result)
        ), mock.patch.object(
            frontend_wrapper, "run_unit_tests", side_effect=mark("unit", action_result)
        ), mock.patch.object(
            frontend_wrapper, "run_build", side_effect=mark("build", action_result)
        ):
            self.assertEqual(frontend_wrapper.main(["--install", "--unit", "--build"]), 0)
        self.assertEqual(
            sequence,
            [
                "load", "hash", "runtime", "count", "install",
                "load", "hash", "runtime", "count", "unit",
                "load", "hash", "runtime", "count", "build",
            ],
        )

    def test_drift_after_install_stops_unit_and_build_before_execution(self) -> None:
        manifest = load_manifest(_ROOT)
        hash_calls = 0

        def hash_gate(*_args, **_kwargs):
            nonlocal hash_calls
            hash_calls += 1
            if hash_calls == 2:
                raise ManifestError("stale authority after install")
            return {"checks": [{"ok": True}]}

        good_runtime = {
            "node": {"actual": "22.22.3", "path": "/validated/node"},
            "npm": {"actual": "10.9.8", "path": "/validated/npm-cli.js"},
        }
        good_inventory = {
            "inventory": {"counts": {"total": 49, "vitest": 3, "node": 46}}
        }
        action_result = {"returncode": 0, "passed": True, "stdout": "", "stderr": ""}
        with mock.patch.object(
            frontend_wrapper, "load_manifest", return_value=manifest
        ), mock.patch.object(
            frontend_wrapper, "validate_manifest_hashes", side_effect=hash_gate
        ), mock.patch.object(
            frontend_wrapper, "check_runtime_versions", return_value=good_runtime
        ), mock.patch.object(
            frontend_wrapper, "check_inventory", return_value=good_inventory
        ), mock.patch.object(
            frontend_wrapper, "run_install", return_value=action_result
        ) as install, mock.patch.object(
            frontend_wrapper, "run_unit_tests", return_value=action_result
        ) as unit, mock.patch.object(
            frontend_wrapper, "run_build", return_value=action_result
        ) as build:
            self.assertEqual(frontend_wrapper.main(["--install", "--unit", "--build"]), 1)
        install.assert_called_once()
        unit.assert_not_called()
        build.assert_not_called()


class SideEffectSafetyTests(unittest.TestCase):
    """H6 side-effect contract: imports must not touch the source tree."""

    def test_wrapper_import_does_not_import_main_py(self) -> None:
        """Importing the wrapper module must not import legacy services main.py."""
        import importlib

        main_path = _ROOT / "services/api/app/main.py"
        if not main_path.is_file():
            self.skipTest("main.py not present in this worktree")
        # Re-import the wrapper fresh and confirm main is not loaded.
        for name in tuple(sys.modules):
            if name == "main" or name.endswith(".main"):
                sys.modules.pop(name, None)
        importlib.reload(frontend_wrapper)
        loaded_main = [name for name in sys.modules if name == "main" or name.endswith(".main")]
        self.assertEqual(loaded_main, [], f"wrapper import loaded main modules: {loaded_main}")

    def test_wrapper_and_verifier_modules_are_importable_without_side_effects(self) -> None:
        """A guarded import must change nothing under the repo root."""
        import importlib

        from verify_toolchain_rebuild import run_import_probe  # noqa: E402

        with mock.patch("subprocess.run", side_effect=AssertionError("process start on import")), mock.patch(
            "subprocess.Popen", side_effect=AssertionError("process start on import")
        ):
            importlib.reload(frontend_wrapper)
        # Importing should not raise and should register the module.
        self.assertIsNotNone(sys.modules.get("run_frontend_checks"))

    def test_import_probe_on_wrapper_module_has_no_source_tree_changes(self) -> None:
        """The manifest-gated Python import probe must report zero changed paths."""
        from verify_toolchain_rebuild import run_import_probe  # noqa: E402

        result = run_import_probe(
            Path(sys.executable),
            _ROOT,
            ("scripts.qc.protocol_v3.verify_toolchain_rebuild", "scripts.qc.protocol_v3.run_frontend_checks"),
            watch_root=_ROOT,
        )
        self.assertEqual(result["changed_paths"], [])
        self.assertEqual(result["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
