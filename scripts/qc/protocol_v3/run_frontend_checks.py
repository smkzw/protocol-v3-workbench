"""Manifest-only frontend reproducibility wrapper for Protocol v3 Task 0.3.

This wrapper has no command-line override for the package manager, scripts, or
lock files: the frozen toolchain manifest is the only command authority.
Before any frontend command runs, every manifest-declared hash is checked both
against the verifier's source anchor and the on-disk file.  Test discovery is
also repeated independently in Python and compared with the Node inventory, so
a co-forged inventory script cannot silently drop a test surface.

H4 (dependency rebuild) and H5 (test discovery) are exercised by dispatching to
the frozen inventory script; H6 (side effects) is preserved because this module
imports nothing from ``services/api/app`` and starts no worker or service.
"""

from __future__ import annotations

import argparse
import os
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

# Reuse the manifest and hash machinery from the Python verifier so that the
# Python and frontend wrappers share one authority and one hash contract.
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from verify_toolchain_rebuild import (  # noqa: E402
    FRONTEND_EXCLUDED_CONTROLLED_QC_PATHS,
    FRONTEND_EXCLUDED_CONTROLLED_QC_REASON,
    FRONTEND_EXCLUDED_STALE_QC_PATHS,
    FRONTEND_EXCLUDED_STALE_QC_REASON,
    FRONTEND_EXPLICIT_NODE_QC_PATHS,
    FRONTEND_TEST_PATHS_SHA256,
    ManifestError,
    load_manifest,
    lock_sha256,
    test_inventory_digest,
    validate_manifest_hashes,
)


class FrontendCheckError(RuntimeError):
    """Raised when a manifest-driven frontend check fails."""


def _frontend_root(repo_root: Path, manifest: dict[str, Any]) -> Path:
    package_path = manifest["frontend"]["package"]["path"]
    path = Path(package_path)
    if not path.is_absolute():
        path = repo_root / path
    return path.parent


def _run_manifest_command(
    repo_root: Path,
    manifest: dict[str, Any],
    script_key: str,
    runtime_versions: dict[str, Any],
    *,
    timeout: int = 900,
) -> dict[str, Any]:
    """Run one structurally validated command from the canonical manifest."""
    frontend = _frontend_root(repo_root, manifest)
    declared = list(manifest["frontend"]["scripts"][script_key])
    if declared[0] == "node":
        command = [runtime_versions["node"]["path"], *declared[1:]]
    elif declared[0] == "npm":
        command = [
            runtime_versions["node"]["path"],
            runtime_versions["npm"]["path"],
            *declared[1:],
        ]
    else:
        raise FrontendCheckError(
            f"unsupported manifest executable for {script_key}: {declared[0]!r}"
        )
    completed = subprocess.run(
        command,
        cwd=frontend,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": command,
        "cwd": str(frontend),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def check_runtime_versions(repo_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Resolve, hash and version-check the exact Node/npm executables."""

    frontend = _frontend_root(repo_root, manifest)
    resolved: dict[str, Path] = {}
    for binary in ("node", "npm"):
        candidate = shutil.which(binary)
        if candidate is None:
            raise FrontendCheckError(f"{binary} executable is not available on PATH")
        path = Path(candidate).resolve()
        if not path.is_file():
            raise FrontendCheckError(f"{binary} executable is not a file: {path}")
        resolved[binary] = path
    observations: dict[str, Any] = {}
    for binary, command in (
        ("node", [str(resolved["node"]), "--version"]),
        (
            "npm",
            [str(resolved["node"]), str(resolved["npm"]), "--version"],
        ),
    ):
        contract = manifest["frontend"]["runtime_binaries"][binary]
        expected = contract["version"]
        actual_sha256 = lock_sha256(resolved[binary])
        if actual_sha256 != contract["sha256"]:
            raise FrontendCheckError(
                f"{binary} executable sha256 mismatch: "
                f"expected={contract['sha256']} actual={actual_sha256} "
                f"path={resolved[binary]}"
            )
        completed = subprocess.run(
            command,
            cwd=frontend,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        actual = completed.stdout.strip().removeprefix("v")
        observations[binary] = {
            "command": command,
            "path": str(resolved[binary]),
            "sha256": actual_sha256,
            "returncode": completed.returncode,
            "expected": expected,
            "actual": actual,
            "ok": completed.returncode == 0 and actual == expected,
        }
        if not observations[binary]["ok"]:
            raise FrontendCheckError(
                f"{binary} version mismatch: expected={expected!r} actual={actual!r} "
                f"returncode={completed.returncode}"
            )
    return observations


def _discover_frontend_tests(
    repo_root: Path,
    manifest: dict[str, Any],
) -> list[dict[str, str]]:
    """Discover every frontend test without trusting the Node inventory code."""
    frontend_root = _frontend_root(repo_root, manifest).resolve()
    contract = manifest["frontend"]["test_inventory"]
    ignored = set(contract["ignored_directories"])
    suffixes = contract["test_suffixes"]
    explicit_node = set(contract["explicit_node_paths"])
    excluded_controlled = set(contract["excluded_controlled_qc_paths"])
    excluded_stale = set(contract["excluded_stale_qc_paths"])
    discovered: list[dict[str, str]] = []
    for current, directories, files in os.walk(frontend_root, topdown=True, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            directory
            for directory in directories
            if directory not in ignored and not (current_path / directory).is_symlink()
        )
        for filename in sorted(files):
            path = current_path / filename
            relative = path.relative_to(frontend_root).as_posix()
            if relative.startswith("tests/monitoring_") and filename.endswith("_qc.mjs"):
                if (
                    relative in explicit_node
                    or relative in excluded_controlled
                    or relative in excluded_stale
                ):
                    continue
                raise FrontendCheckError(
                    f"unclassified frontend QC script: {relative}"
                )
            if ".test." not in filename:
                continue
            if path.is_symlink():
                raise FrontendCheckError(
                    f"test symlink is not an executable inventory entry: "
                    f"{path.relative_to(frontend_root).as_posix()}"
                )
            matches = [
                runner for suffix, runner in suffixes.items() if filename.endswith(suffix)
            ]
            if len(matches) != 1:
                raise FrontendCheckError(
                    "unknown or ambiguous frontend test suffix: "
                    f"{path.relative_to(frontend_root).as_posix()}"
                )
            discovered.append(
                {
                    "path": path.relative_to(frontend_root).as_posix(),
                    "runner": matches[0],
                }
            )
    for relative in FRONTEND_EXPLICIT_NODE_QC_PATHS:
        declared = frontend_root / relative
        if declared.is_symlink() or not declared.is_file():
            raise FrontendCheckError(
                f"explicit Node QC path is missing or not a regular file: {relative}"
            )
        discovered.append({"path": relative, "runner": "node"})
    for relative in FRONTEND_EXCLUDED_CONTROLLED_QC_PATHS:
        declared = frontend_root / relative
        if declared.is_symlink() or not declared.is_file():
            raise FrontendCheckError(
                f"controlled QC exclusion is missing or not a regular file: {relative}"
            )
    for relative in FRONTEND_EXCLUDED_STALE_QC_PATHS:
        declared = frontend_root / relative
        if declared.is_symlink() or not declared.is_file():
            raise FrontendCheckError(
                f"stale QC exclusion is missing or not a regular file: {relative}"
            )
    return sorted(discovered, key=lambda item: item["path"])


def check_inventory(
    repo_root: Path,
    manifest: dict[str, Any],
    runtime_versions: dict[str, Any],
) -> dict[str, Any]:
    """Run the frozen inventory and cross-check an independent discovery pass.

    The manifest pins both counts and the complete runner/path digest.  Python
    scans the frontend independently using the frozen suffix/ignore contract;
    both views must be identical before an action may run.
    """
    result = _run_manifest_command(
        repo_root,
        manifest,
        "test:inventory:json",
        runtime_versions,
    )
    if result["returncode"] != 0:
        raise FrontendCheckError(
            f"inventory check failed ({result['returncode']}): {result['stderr'].strip()}"
        )
    try:
        inventory = json.loads(result["stdout"])
    except json.JSONDecodeError as exc:
        raise FrontendCheckError(f"inventory did not return JSON: {exc}") from exc
    expected = manifest["frontend"]["test_inventory"]["counts"]
    for key in ("total", "vitest", "node"):
        if inventory.get("counts", {}).get(key) != expected[key]:
            raise FrontendCheckError(
                f"inventory count {key!r} mismatch: manifest={expected[key]} "
                f"actual={inventory.get('counts', {}).get(key)}"
            )
    inventory_contract = manifest["frontend"]["test_inventory"]
    if inventory.get("schema_version") != inventory_contract["schema_version"]:
        raise FrontendCheckError("inventory schema_version does not match manifest")
    if inventory.get("root") != "frontend":
        raise FrontendCheckError("inventory root must be 'frontend'")
    if inventory.get("ignored_directories") != inventory_contract["ignored_directories"]:
        raise FrontendCheckError("inventory ignored_directories do not match manifest")
    if (
        inventory.get("explicit_node_paths") != FRONTEND_EXPLICIT_NODE_QC_PATHS
        or inventory_contract.get("explicit_node_paths") != FRONTEND_EXPLICIT_NODE_QC_PATHS
    ):
        raise FrontendCheckError("inventory explicit Node QC paths do not match contract")
    if (
        inventory.get("excluded_controlled_qc_paths")
        != FRONTEND_EXCLUDED_CONTROLLED_QC_PATHS
        or inventory_contract.get("excluded_controlled_qc_paths")
        != FRONTEND_EXCLUDED_CONTROLLED_QC_PATHS
    ):
        raise FrontendCheckError("inventory controlled QC exclusions do not match contract")
    if (
        inventory.get("excluded_controlled_qc_reason")
        != FRONTEND_EXCLUDED_CONTROLLED_QC_REASON
        or inventory_contract.get("excluded_controlled_qc_reason")
        != FRONTEND_EXCLUDED_CONTROLLED_QC_REASON
    ):
        raise FrontendCheckError("inventory controlled QC exclusion reason is invalid")
    if (
        inventory.get("excluded_stale_qc_paths") != FRONTEND_EXCLUDED_STALE_QC_PATHS
        or inventory_contract.get("excluded_stale_qc_paths")
        != FRONTEND_EXCLUDED_STALE_QC_PATHS
    ):
        raise FrontendCheckError("inventory stale QC exclusions do not match contract")
    if (
        inventory.get("excluded_stale_qc_reason") != FRONTEND_EXCLUDED_STALE_QC_REASON
        or inventory_contract.get("excluded_stale_qc_reason")
        != FRONTEND_EXCLUDED_STALE_QC_REASON
    ):
        raise FrontendCheckError("inventory stale QC exclusion reason is invalid")
    tests = inventory.get("tests")
    commands = inventory.get("commands")
    if not isinstance(tests, list) or not isinstance(commands, dict):
        raise FrontendCheckError("inventory tests/commands are malformed")
    independently_discovered = _discover_frontend_tests(repo_root, manifest)
    if tests != independently_discovered:
        inventory_paths = {
            item.get("path") for item in tests if isinstance(item, dict)
        }
        discovered_paths = {item["path"] for item in independently_discovered}
        missing = sorted(discovered_paths - inventory_paths)
        extra = sorted(inventory_paths - discovered_paths)
        raise FrontendCheckError(
            "independent frontend test discovery mismatch: "
            f"missing={missing} extra={extra}"
        )
    paths_sha256 = test_inventory_digest(independently_discovered)
    if (
        paths_sha256 != inventory_contract.get("paths_sha256")
        or paths_sha256 != FRONTEND_TEST_PATHS_SHA256
    ):
        raise FrontendCheckError(
            "frontend test path identity mismatch: "
            f"expected={FRONTEND_TEST_PATHS_SHA256} actual={paths_sha256}"
        )
    suffix_contract = inventory_contract["test_suffixes"]
    expected_paths: dict[str, list[str]] = {"vitest": [], "node": []}
    for test in tests:
        if not isinstance(test, dict) or not isinstance(test.get("path"), str):
            raise FrontendCheckError("inventory contains a malformed test entry")
        matched = (
            ["node"]
            if test["path"] in FRONTEND_EXPLICIT_NODE_QC_PATHS
            else [
                runner
                for suffix, runner in suffix_contract.items()
                if test["path"].endswith(suffix)
            ]
        )
        if len(matched) != 1 or test.get("runner") != matched[0]:
            raise FrontendCheckError(
                f"inventory runner/suffix mismatch for {test['path']}"
            )
        expected_paths[matched[0]].append(test["path"])
    if expected_paths["vitest"] != inventory_contract["vitest_paths"]:
        raise FrontendCheckError("inventory Vitest paths do not match manifest")
    vitest = commands.get("vitest")
    node = commands.get("node")
    if not isinstance(vitest, dict) or not isinstance(node, dict):
        raise FrontendCheckError("inventory runner commands are missing")
    if (
        vitest.get("runner") != "vitest"
        or vitest.get("command") != "vitest"
        or vitest.get("paths") != expected_paths["vitest"]
        or vitest.get("args")
        != [*manifest["frontend"]["vitest_args"], *expected_paths["vitest"]]
    ):
        raise FrontendCheckError("inventory Vitest command does not match manifest")
    if (
        node.get("runner") != "node"
        or Path(str(node.get("command", ""))).resolve()
        != Path(runtime_versions["node"]["path"]).resolve()
        or node.get("paths") != expected_paths["node"]
        or node.get("args")
        != [*manifest["frontend"]["node_runner_args"], *expected_paths["node"]]
    ):
        raise FrontendCheckError("inventory Node command does not match manifest")
    return {
        "inventory": inventory,
        "expected_counts": expected,
        "paths_sha256": paths_sha256,
    }


def run_unit_tests(
    repo_root: Path,
    manifest: dict[str, Any],
    runtime_versions: dict[str, Any],
) -> dict[str, Any]:
    """Run the dual-runner unit suite (vitest + node) through the inventory."""
    result = _run_manifest_command(
        repo_root,
        manifest,
        "test:unit",
        runtime_versions,
    )
    return {
        "command": result["command"],
        "returncode": result["returncode"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "passed": result["returncode"] == 0,
    }


def run_install(
    repo_root: Path,
    manifest: dict[str, Any],
    runtime_versions: dict[str, Any],
) -> dict[str, Any]:
    """Install the frozen lock using only the manifest-declared command."""
    result = _run_manifest_command(
        repo_root,
        manifest,
        "install",
        runtime_versions,
    )
    return {
        **result,
        "passed": result["returncode"] == 0,
    }


def run_build(
    repo_root: Path,
    manifest: dict[str, Any],
    runtime_versions: dict[str, Any],
) -> dict[str, Any]:
    """Run the frozen build script from the frontend root."""
    result = _run_manifest_command(
        repo_root,
        manifest,
        "build",
        runtime_versions,
    )
    frontend = _frontend_root(repo_root, manifest)
    output_index = frontend / "dist/index.html"
    output_assets = frontend / "dist/assets"
    output_ok = (
        result["returncode"] == 0
        and output_index.is_file()
        and output_index.stat().st_size > 0
        and output_assets.is_dir()
        and any(path.is_file() for path in output_assets.iterdir())
    )
    return {
        **result,
        "output_index": str(output_index),
        "output_verified": output_ok,
        "passed": output_ok,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true",
                        help="validate manifest hashes and inventory counts only")
    parser.add_argument("--install", action="store_true",
                        help="run the manifest-declared clean install command")
    parser.add_argument("--unit", "--run-unit", action="store_true", dest="run_unit",
                        help="run the dual-runner unit suite")
    parser.add_argument("--build", action="store_true",
                        help="run the frozen frontend build")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _run_pre_action_gates(
    repo_root: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Reload canonical authority and re-run every gate before one action."""
    manifest = load_manifest(repo_root)
    hash_check = validate_manifest_hashes(repo_root, manifest=manifest)
    runtime_versions = check_runtime_versions(repo_root, manifest)
    inventory = check_inventory(repo_root, manifest, runtime_versions)
    return manifest, hash_check, runtime_versions, inventory


def _compact_gate_record(
    action: str,
    hash_check: dict[str, Any],
    runtime_versions: dict[str, Any],
    inventory: dict[str, Any],
) -> dict[str, Any]:
    return {
        "before_action": action,
        "hash_check_count": len(hash_check["checks"]),
        "hashes_ok": all(item["ok"] for item in hash_check["checks"]),
        "runtime_versions": {
            binary: observation["actual"]
            for binary, observation in runtime_versions.items()
        },
        "inventory_counts": inventory["inventory"]["counts"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result: dict[str, Any] = {
            "mode": "frontend",
            "manifest": "config/medical_writing/protocol_v3/toolchain_manifest.json",
            "package_manager": "npm",
            "action_gates": [],
        }
        actions = [
            ("install", args.install, run_install, "clean install"),
            ("unit", args.run_unit, run_unit_tests, "unit tests"),
            ("build", args.build, run_build, "build"),
        ]
        selected = [item for item in actions if item[1]]

        if not selected:
            # Check-only/default invocation still executes one complete gate.
            manifest, hash_check, runtime_versions, inventory = _run_pre_action_gates(
                args.repo_root
            )
            result.update(
                {
                    "package_manager": manifest["frontend"]["package_manager"],
                    "hash_check": hash_check,
                    "runtime_versions": runtime_versions,
                    "inventory": inventory,
                }
            )
            result["action_gates"].append(
                _compact_gate_record("check", hash_check, runtime_versions, inventory)
            )

        for action, _enabled, runner, label in selected:
            # Re-load the canonical manifest and repeat hash/runtime/inventory
            # immediately before every selected action.  A prior install is
            # allowed to change node_modules only; any authority or inventory
            # drift stops unit/build before they start.
            manifest, hash_check, runtime_versions, inventory = _run_pre_action_gates(
                args.repo_root
            )
            if "hash_check" not in result:
                result.update(
                    {
                        "package_manager": manifest["frontend"]["package_manager"],
                        "hash_check": hash_check,
                        "runtime_versions": runtime_versions,
                        "inventory": inventory,
                    }
                )
            result["action_gates"].append(
                _compact_gate_record(action, hash_check, runtime_versions, inventory)
            )
            result[action] = runner(args.repo_root, manifest, runtime_versions)
            if not result[action]["passed"]:
                raise FrontendCheckError(
                    f"{label} failed ({result[action]['returncode']})"
                )

        payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        print(payload)
        return 0
    except (ManifestError, FrontendCheckError, OSError, subprocess.SubprocessError) as exc:
        print(f"frontend check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
