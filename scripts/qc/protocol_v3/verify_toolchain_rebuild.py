"""Reproducibility checks for Protocol v3 Task 0.3.

The frozen toolchain manifest is the only CLI command authority: it pins the
package manager, commands, Python version and lock.  Candidate-source hashes
are also anchored in this verifier so a manifest plus dependency/test source
cannot be co-forged without changing the verifier itself.  Task 0.4 adds the
external immutable authority for that verifier source.  Pure parsing and
validation functions remain importable for focused tests, but the command-line
entrypoint accepts no requirements, lock, interpreter, import-module or script
override.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Sequence


PYTHON_VERSION_RE = re.compile(r"Python\s+(?P<version>\d+\.\d+)")
REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>[^\s;]+)"
    r"(?:\s*;\s*(?P<marker>.*))?$"
)
HASH_RE = re.compile(r"--hash=(?P<algorithm>[A-Za-z0-9_-]+):(?P<digest>[0-9a-fA-F]+)")
GROUP_RE = re.compile(r"^#\s*\[(?P<group>[A-Za-z0-9_]+)\]\s*$")
LICENSE_GROUP_RE = re.compile(r"^#\s*License group:\s*(?P<group>.+?)\s*$")

EXCLUDED_DISTRIBUTIONS = frozenset({"fitz", "pymupdf"})


class LockValidationError(ValueError):
    """Raised when the declared input and generated hash lock disagree."""

class ManifestError(ValueError):
    """Raised when the frozen toolchain manifest is missing, malformed or stale."""


MANIFEST_SCHEMA = "protocol-v3-toolchain.v1"
MANIFEST_PATH = Path("config/medical_writing/protocol_v3/toolchain_manifest.json")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

PYTHON_INTERPRETER = "python3.12"
PYTHON_MANIFEST_PATHS = {
    "requirements_input": "services/api/requirements-protocol-v3.in",
    "lock": "services/api/requirements-protocol-v3.lock",
}
PYTHON_COMPILER_CONTRACT = {
    "name": "pip-tools",
    "version": "7.6.0",
    "command": (
        "python -m piptools compile --generate-hashes --resolver=backtracking "
        "--strip-extras --output-file services/api/requirements-protocol-v3.lock "
        "services/api/requirements-protocol-v3.in"
    ),
}
PYTHON_CLEAN_INSTALL_CONTRACT = {
    "venv_create": ["{python}", "-m", "venv", "{venv}"],
    "install": [
        "{venv_python}",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--require-hashes",
        "--no-deps",
        "-r",
        "{lock}",
    ],
    "verify": ["{venv_python}", "-m", "pip", "check"],
    "import_probe_modules": ["scripts.qc.protocol_v3.verify_toolchain_rebuild"],
}
FRONTEND_NODE_VERSION = "22.22.3"
FRONTEND_NPM_VERSION = "10.9.8"
FRONTEND_RUNTIME_SHA256 = {
    "node": "5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c",
    "npm": "8e5f6f3429f8cdbe693cdc29904e9d5a7b127a494bd15c804bd54c7403bfcbe7",
}
FRONTEND_PACKAGE_MANAGER_FIELD = "npm@10.9.8"
FRONTEND_LOCKFILE_VERSION = 3
FRONTEND_PACKAGE_COUNT = 329
FRONTEND_INVENTORY_SCHEMA = "protocol-v3-test-inventory.v1"
FRONTEND_INVENTORY_COUNTS = {"total": 63, "vitest": 15, "node": 48}
FRONTEND_TEST_PATHS_SHA256 = "bbc6a3920a4cfe572a998fe41f9c377564c3d10392e4c5cfc3d671d20d71bf88"
FRONTEND_IGNORED_DIRECTORIES = [
    ".cache",
    ".git",
    ".npm-cache",
    ".vite",
    "coverage",
    "dist",
    "node_modules",
    "output",
    "runtime",
]
FRONTEND_TEST_SUFFIXES = {
    ".test.jsx": "vitest",
    ".test.mjs": "node",
}
FRONTEND_VITEST_ARGS = [
    "run",
    "--config",
    "vite.config.mjs",
    "--environment",
    "jsdom",
]
FRONTEND_VITEST_ENTRY = "frontend/node_modules/vitest/vitest.mjs"
FRONTEND_NODE_RUNNER_ARGS = ["--test"]
FRONTEND_VITEST_PATHS = [
    "src/features/medical-writing/AuthoringCandidatePackagePanel.test.jsx",
    "src/features/medical-writing/MedicalWritingPreviewPanel.test.jsx",
    "src/features/medical-writing/MedicalWritingSynopsisProjectIntake.test.jsx",
    "src/features/medical-writing/protocol-workbench/ChapterDraftPreview.test.jsx",
    "src/features/medical-writing/protocol-workbench/DesignElementsCards.test.jsx",
    "src/features/medical-writing/protocol-workbench/ManuscriptWorkspace.test.jsx",
    "src/features/medical-writing/protocol-workbench/ProtocolIntakeWorkspace.test.jsx",
    "src/features/medical-writing/protocol-workbench/ProtocolSourceIntake.test.jsx",
    "src/features/medical-writing/protocol-workbench/RegimenAdoptionCard.test.jsx",
    "src/features/medical-writing/protocol-workbench/RegimenDesignWorkspace.test.jsx",
    "src/features/medical-writing/protocol-workbench/RegimenProposalCard.test.jsx",
    "src/features/medical-writing/protocol-workbench/ResearchInformationCard.test.jsx",
    "src/features/medical-writing/protocol-workbench/StudyContextWorkspace.test.jsx",
    "src/features/medical-writing/protocol-workbench/office/GenOfficeFrame.test.jsx",
    "tests/ProtocolSourceSelectionRecovery.test.jsx"
]
FRONTEND_EXPLICIT_NODE_QC_PATHS = [
    "tests/monitoring_child_read_contract_qc.mjs",
    "tests/monitoring_source_only_ui_qc.mjs",
]
FRONTEND_EXCLUDED_CONTROLLED_QC_PATHS = [
    "tests/monitoring_content_confirmation_qc.mjs",
    "tests/monitoring_real_projects_actions_qc.mjs",
    "tests/monitoring_real_projects_qc.mjs",
    "tests/monitoring_upload_qc.mjs",
]
FRONTEND_EXCLUDED_CONTROLLED_QC_REASON = (
    "requires live service, browser and/or runtime data; protected E2E gate only"
)
FRONTEND_EXCLUDED_STALE_QC_PATHS = [
    "tests/monitoring_unavailable_state_qc.mjs",
]
FRONTEND_EXCLUDED_STALE_QC_REASON = (
    "protected medical-monitoring baseline QC is stale against baseline source; "
    "monitoring owner adjudication required"
)
FRONTEND_PACKAGE_SCRIPT_CONTRACT = {
    "build": "vite build",
    "test:inventory": "node tests/protocol_v3_test_inventory.mjs --check",
    "test:unit:vitest": "node tests/protocol_v3_test_inventory.mjs --run vitest",
    "test:unit:node": "node tests/protocol_v3_test_inventory.mjs --run node",
    "test:unit": "node tests/protocol_v3_test_inventory.mjs --run all",
}
FRONTEND_MANIFEST_PATHS = {
    "package": "frontend/package.json",
    "lock": "frontend/package-lock.json",
    "test_inventory": "frontend/tests/protocol_v3_test_inventory.mjs",
}
FRONTEND_QUARANTINE_PATHS = {
    "pnpm_lock": "quarantine/protocol_v3/task03/frontend/pnpm-lock.yaml",
    "pnpm_workspace": "quarantine/protocol_v3/task03/frontend/pnpm-workspace.yaml",
}
CANONICAL_SOURCE_SHA256 = {
    "python.requirements_input": "9fd153ebb36125d68d575383ce15334f15ca294eff4ed6d50af72cdc58495045",
    "python.lock": "1e771c8f4f3a90410714f94107cecd42662574fa560eb72ce9ee89e6e5921698",
    "frontend.package": "2238c1e0000483f2c599b2c9ad6793ad8b4bb10855fd6f8bb8802cdfbbeceb5e",
    "frontend.lock": "d2b30162757bf5b0028372e43ef631fd9d282eec30cbc976bfd330fc753c237a",
    "frontend.test_inventory": "0a037e0d24de4674fadc52fa8a1cb46aeb95afb9378e3790074cd1297766d75d",
    "frontend.quarantined_inactive_pnpm.pnpm_lock": "3f101b4e9c833a5154af12f250644cfe60ada682d351c9f028484159d038fba8",
    "frontend.quarantined_inactive_pnpm.pnpm_workspace": "d6d0c24446d91ef762d37c6ba801bb516e65d7055aa9f8027fcd457409a97ce1",
}
FRONTEND_SCRIPT_CONTRACT = {
    "install": ["npm", "ci", "--ignore-scripts", "--audit=false", "--fund=false"],
    "test:inventory": ["node", "tests/protocol_v3_test_inventory.mjs", "--check"],
    "test:inventory:json": ["node", "tests/protocol_v3_test_inventory.mjs", "--json"],
    "test:unit:vitest": ["node", "tests/protocol_v3_test_inventory.mjs", "--run", "vitest"],
    "test:unit:node": ["node", "tests/protocol_v3_test_inventory.mjs", "--run", "node"],
    "test:unit": ["node", "tests/protocol_v3_test_inventory.mjs", "--run", "all"],
    "build": ["npm", "run", "build"],
}


class ToolchainRebuildError(RuntimeError):
    """Raised when a clean Python rebuild or import probe fails."""


def test_inventory_digest(tests: Sequence[dict[str, str]]) -> str:
    """Return the frozen identity of the complete runner/path inventory."""
    encoded = json.dumps(
        list(tests),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Requirement:
    name: str
    version: str
    group: str


@dataclass(frozen=True)
class LockEntry:
    name: str
    version: str
    marker: str | None
    hashes: tuple[str, ...]


def normalize_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def lock_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def _manifest_file_sha256(path: Path) -> str:
    """SHA-256 of a manifest-referenced source file (used for hash pre-checks)."""
    return lock_sha256(path)


def _canonical_manifest_path(repo_root: Path) -> Path:
    return (repo_root / MANIFEST_PATH).resolve()


def _resolve_canonical_manifest_path(repo_root: Path, manifest_path: Path | None) -> Path:
    canonical = _canonical_manifest_path(repo_root)
    requested = manifest_path or MANIFEST_PATH
    if not requested.is_absolute():
        requested = repo_root / requested
    resolved = requested.resolve()
    if resolved != canonical:
        raise ManifestError(
            f"alternate toolchain manifest is forbidden: expected {canonical}, got {resolved}"
        )
    return canonical


def _validate_manifest_contract(manifest: dict[str, Any]) -> None:
    """Validate every execution-bearing manifest field before it is trusted."""
    python = manifest.get("python")
    frontend = manifest.get("frontend")
    if not isinstance(python, dict) or not isinstance(frontend, dict):
        raise ManifestError("manifest must contain object sections 'python' and 'frontend'")
    if python.get("version") != "3.12":
        raise ManifestError("manifest python.version must be '3.12'")
    if python.get("interpreter") != PYTHON_INTERPRETER:
        raise ManifestError(
            f"manifest python.interpreter must be {PYTHON_INTERPRETER!r}"
        )
    if python.get("compiler") != PYTHON_COMPILER_CONTRACT:
        raise ManifestError("manifest python.compiler does not match the frozen contract")
    for key in ("requirements_input", "lock", "clean_install", "license_groups"):
        if not isinstance(python.get(key), dict):
            raise ManifestError(f"manifest python section missing object: {key}")
    for key, expected_path in PYTHON_MANIFEST_PATHS.items():
        section = python[key]
        if section.get("path") != expected_path:
            raise ManifestError(
                f"manifest python.{key}.path must be {expected_path!r}"
            )
    lock_contract = python["lock"]
    excluded = lock_contract.get("excluded")
    if (
        not isinstance(lock_contract.get("direct_count"), int)
        or lock_contract["direct_count"] < 1
        or not isinstance(lock_contract.get("entry_count"), int)
        or lock_contract["entry_count"] < lock_contract["direct_count"]
        or lock_contract.get("hash_algorithm") != "sha256"
        or not isinstance(excluded, list)
        or any(not isinstance(name, str) or not name for name in excluded)
        or {normalize_distribution_name(name) for name in excluded}
        != EXCLUDED_DISTRIBUTIONS
    ):
        raise ManifestError("manifest python.lock metadata is invalid")
    if python["clean_install"] != PYTHON_CLEAN_INSTALL_CONTRACT:
        raise ManifestError(
            "manifest python.clean_install does not match the frozen command contract"
        )
    license_groups = python["license_groups"]
    if (
        not license_groups
        or any(
            not isinstance(group, str)
            or not isinstance(packages, list)
            or not packages
            or any(not isinstance(package, str) or not package for package in packages)
            for group, packages in license_groups.items()
        )
    ):
        raise ManifestError("manifest python.license_groups is invalid")
    if frontend.get("package_manager") != "npm":
        raise ManifestError("manifest frontend.package_manager must be 'npm'")
    if frontend.get("node_version") != FRONTEND_NODE_VERSION:
        raise ManifestError(
            f"manifest frontend.node_version must be {FRONTEND_NODE_VERSION!r}"
        )
    if frontend.get("npm_version") != FRONTEND_NPM_VERSION:
        raise ManifestError(
            f"manifest frontend.npm_version must be {FRONTEND_NPM_VERSION!r}"
        )
    runtime_binaries = frontend.get("runtime_binaries")
    if not isinstance(runtime_binaries, dict) or set(runtime_binaries) != {"node", "npm"}:
        raise ManifestError("manifest frontend.runtime_binaries must declare node and npm")
    for key, version in (("node", FRONTEND_NODE_VERSION), ("npm", FRONTEND_NPM_VERSION)):
        binary = runtime_binaries[key]
        if (
            not isinstance(binary, dict)
            or set(binary) != {"version", "sha256"}
            or binary.get("version") != version
            or not isinstance(binary.get("sha256"), str)
            or not SHA256_RE.match(binary["sha256"])
            or binary["sha256"] != FRONTEND_RUNTIME_SHA256[key]
        ):
            raise ManifestError(
                f"manifest frontend.runtime_binaries.{key} is invalid"
            )
    for key, expected_path in FRONTEND_MANIFEST_PATHS.items():
        section = frontend.get(key)
        if not isinstance(section, dict) or section.get("path") != expected_path:
            raise ManifestError(
                f"manifest frontend.{key}.path must be {expected_path!r}"
            )
    if frontend["package"].get("package_manager_field") != FRONTEND_PACKAGE_MANAGER_FIELD:
        raise ManifestError("manifest frontend.package.package_manager_field is invalid")
    if frontend["lock"].get("lockfile_version") != FRONTEND_LOCKFILE_VERSION:
        raise ManifestError("manifest frontend.lock.lockfile_version is invalid")
    if frontend["lock"].get("package_count") != FRONTEND_PACKAGE_COUNT:
        raise ManifestError("manifest frontend.lock.package_count is invalid")
    quarantine = frontend.get("quarantined_inactive_pnpm")
    if not isinstance(quarantine, dict) or quarantine.get("status") != "inactive_quarantined":
        raise ManifestError("manifest must declare pnpm files as inactive_quarantined")
    for key, expected_path in FRONTEND_QUARANTINE_PATHS.items():
        section = quarantine.get(key)
        if not isinstance(section, dict) or section.get("path") != expected_path:
            raise ManifestError(
                f"manifest frontend.quarantined_inactive_pnpm.{key}.path must be {expected_path!r}"
            )
    scripts = frontend.get("scripts")
    if not isinstance(scripts, dict):
        raise ManifestError("manifest frontend.scripts must be an object")
    if set(scripts) != set(FRONTEND_SCRIPT_CONTRACT):
        raise ManifestError(
            "manifest frontend.scripts keys do not match the frozen contract"
        )
    for key, expected in FRONTEND_SCRIPT_CONTRACT.items():
        if scripts.get(key) != expected:
            raise ManifestError(
                f"manifest frontend.scripts.{key} does not match the frozen command"
            )
    inventory = frontend["test_inventory"]
    if inventory.get("schema_version") != FRONTEND_INVENTORY_SCHEMA:
        raise ManifestError("manifest frontend.test_inventory.schema_version is invalid")
    if inventory.get("ignored_directories") != FRONTEND_IGNORED_DIRECTORIES:
        raise ManifestError("manifest frontend.test_inventory.ignored_directories is invalid")
    if inventory.get("test_suffixes") != FRONTEND_TEST_SUFFIXES:
        raise ManifestError("manifest frontend.test_inventory.test_suffixes is invalid")
    if inventory.get("vitest_paths") != FRONTEND_VITEST_PATHS:
        raise ManifestError("manifest frontend.test_inventory.vitest_paths is invalid")
    if inventory.get("explicit_node_paths") != FRONTEND_EXPLICIT_NODE_QC_PATHS:
        raise ManifestError("manifest frontend.test_inventory.explicit_node_paths is invalid")
    if (
        inventory.get("excluded_controlled_qc_paths")
        != FRONTEND_EXCLUDED_CONTROLLED_QC_PATHS
    ):
        raise ManifestError(
            "manifest frontend.test_inventory.excluded_controlled_qc_paths is invalid"
        )
    if (
        inventory.get("excluded_controlled_qc_reason")
        != FRONTEND_EXCLUDED_CONTROLLED_QC_REASON
    ):
        raise ManifestError(
            "manifest frontend.test_inventory.excluded_controlled_qc_reason is invalid"
        )
    if inventory.get("excluded_stale_qc_paths") != FRONTEND_EXCLUDED_STALE_QC_PATHS:
        raise ManifestError(
            "manifest frontend.test_inventory.excluded_stale_qc_paths is invalid"
        )
    if inventory.get("excluded_stale_qc_reason") != FRONTEND_EXCLUDED_STALE_QC_REASON:
        raise ManifestError(
            "manifest frontend.test_inventory.excluded_stale_qc_reason is invalid"
        )
    counts = inventory.get("counts")
    if counts != FRONTEND_INVENTORY_COUNTS:
        raise ManifestError("manifest frontend.test_inventory.counts is invalid")
    if inventory.get("paths_sha256") != FRONTEND_TEST_PATHS_SHA256:
        raise ManifestError("manifest frontend.test_inventory.paths_sha256 is invalid")
    if frontend.get("vitest_args") != FRONTEND_VITEST_ARGS:
        raise ManifestError("manifest frontend.vitest_args is invalid")
    if frontend.get("vitest_entry") != FRONTEND_VITEST_ENTRY:
        raise ManifestError("manifest frontend.vitest_entry is invalid")
    if frontend.get("node_runner_args") != FRONTEND_NODE_RUNNER_ARGS:
        raise ManifestError("manifest frontend.node_runner_args is invalid")


def load_manifest(repo_root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Load and structurally validate the frozen toolchain manifest.

    The manifest is the only execution authority; this function refuses a
    schema it does not recognise and rejects missing required sections so
    that a stale or hand-edited manifest fails closed.
    """
    path = _resolve_canonical_manifest_path(repo_root, manifest_path)
    if not path.is_file():
        raise ManifestError(f"toolchain manifest not found: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"toolchain manifest is not valid JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ManifestError("toolchain manifest must be a JSON object")
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ManifestError(
            f"manifest schema_version must be {MANIFEST_SCHEMA!r}; "
            f"got {manifest.get('schema_version')!r}"
        )
    _validate_manifest_contract(manifest)
    return manifest


def _resolve_manifest_path(repo_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ManifestError(f"manifest path must be a non-empty relative string: {relative!r}")
    repo_root = repo_root.resolve()
    path = Path(relative)
    if path.is_absolute():
        raise ManifestError(f"absolute manifest path is forbidden: {relative}")
    resolved = (repo_root / path).resolve()
    if resolved == repo_root or repo_root not in resolved.parents:
        raise ManifestError(f"manifest path escapes repository root: {relative}")
    return resolved


def _read_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"{label} must contain a JSON object")
    return value


def validate_frontend_file_contract(
    repo_root: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """Bind manifest metadata to package.json and package-lock.json semantics."""

    frontend = manifest["frontend"]
    package_path = _resolve_manifest_path(repo_root, frontend["package"]["path"])
    lock_path = _resolve_manifest_path(repo_root, frontend["lock"]["path"])
    package = _read_json_object(package_path, "frontend package.json")
    lock = _read_json_object(lock_path, "frontend package-lock.json")
    if package.get("packageManager") != FRONTEND_PACKAGE_MANAGER_FIELD:
        raise ManifestError("frontend package.json packageManager does not match manifest")
    scripts = package.get("scripts")
    if not isinstance(scripts, dict):
        raise ManifestError("frontend package.json scripts must be an object")
    for key, expected in FRONTEND_PACKAGE_SCRIPT_CONTRACT.items():
        if scripts.get(key) != expected:
            raise ManifestError(
                f"frontend package.json scripts.{key} must be {expected!r}"
            )
    expected_engines = {
        "node": FRONTEND_NODE_VERSION,
        "npm": FRONTEND_NPM_VERSION,
    }
    if package.get("engines") != expected_engines:
        raise ManifestError("frontend package.json engines do not match frozen runtime")
    if lock.get("lockfileVersion") != FRONTEND_LOCKFILE_VERSION:
        raise ManifestError("frontend package-lock.json lockfileVersion mismatch")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or "" not in packages:
        raise ManifestError("frontend package-lock.json packages/root entry is missing")
    actual_package_count = len(packages) - 1
    if actual_package_count != FRONTEND_PACKAGE_COUNT:
        raise ManifestError(
            "frontend package-lock.json package count mismatch: "
            f"expected={FRONTEND_PACKAGE_COUNT} actual={actual_package_count}"
        )
    lock_root = packages[""]
    if not isinstance(lock_root, dict):
        raise ManifestError("frontend package-lock.json root entry must be an object")
    for key in ("dependencies", "devDependencies", "engines"):
        if lock_root.get(key) != package.get(key):
            raise ManifestError(
                f"frontend package-lock.json root {key} does not match package.json"
            )
    return {
        "package_manager_field": package["packageManager"],
        "package_scripts": {
            key: scripts[key] for key in FRONTEND_PACKAGE_SCRIPT_CONTRACT
        },
        "engines": expected_engines,
        "lockfile_version": lock["lockfileVersion"],
        "package_count": actual_package_count,
    }


def validate_manifest_hashes(
    repo_root: Path,
    manifest_path: Path | None = None,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify every declared hash in the manifest against the on-disk files.

    This is the manifest-only gate: it runs before any command.  Every
    referenced file (requirements input, Python lock, package.json,
    package-lock, inventory script, and the frozen pnpm files) must exist and
    match its pinned sha256.  A single mismatch fails closed.
    """
    if manifest is None:
        manifest = load_manifest(repo_root, manifest_path)
    checks: list[dict[str, Any]] = []

    def _check(label: str, section: dict[str, Any], file_key: str = "path", hash_key: str = "sha256") -> None:
        if file_key not in section or hash_key not in section:
            raise ManifestError(f"manifest {label!r} entry must declare {file_key!r} and {hash_key!r}")
        path = _resolve_manifest_path(repo_root, section[file_key])
        expected = section[hash_key]
        if not isinstance(expected, str) or not SHA256_RE.match(expected):
            raise ManifestError(f"manifest {label!r} sha256 is not a 64-char hex digest: {expected!r}")
        frozen = CANONICAL_SOURCE_SHA256.get(label)
        if frozen is None or expected != frozen:
            raise ManifestError(
                f"manifest {label} sha256 does not match the frozen source authority: "
                f"expected={frozen} actual={expected}"
            )
        if not path.is_file():
            raise ManifestError(f"manifest {label!r} referenced file is missing: {path}")
        actual = _manifest_file_sha256(path)
        checks.append({"label": label, "path": str(path), "expected": expected, "actual": actual, "ok": actual == expected})
        if actual != expected:
            raise ManifestError(
                f"{label} hash mismatch for {path}: manifest={expected} actual={actual}"
            )

    py = manifest["python"]
    if "requirements_input" not in py or "lock" not in py:
        raise ManifestError("manifest python section must declare requirements_input and lock")
    _check("python.requirements_input", py["requirements_input"])
    _check("python.lock", py["lock"])

    fe = manifest["frontend"]
    if "package" not in fe or "lock" not in fe:
        raise ManifestError("manifest frontend section must declare package and lock")
    _check("frontend.package", fe["package"])
    _check("frontend.lock", fe["lock"])
    _check("frontend.test_inventory", fe["test_inventory"])
    quarantine = fe["quarantined_inactive_pnpm"]
    _check("frontend.quarantined_inactive_pnpm.pnpm_lock", quarantine["pnpm_lock"])
    _check("frontend.quarantined_inactive_pnpm.pnpm_workspace", quarantine["pnpm_workspace"])

    frontend_contract = validate_frontend_file_contract(repo_root, manifest)
    return {
        "schema_version": manifest["schema_version"],
        "checks": checks,
        "frontend_contract": frontend_contract,
    }


def python_lock_validation_from_manifest(
    repo_root: Path,
    manifest_path: Path | None = None,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the Python hash lock using paths pinned in the manifest."""
    if manifest is None:
        manifest = load_manifest(repo_root, manifest_path)
    requirements = _resolve_manifest_path(repo_root, manifest["python"]["requirements_input"]["path"])
    lock = _resolve_manifest_path(repo_root, manifest["python"]["lock"]["path"])
    expected_python = manifest["python"].get("version", "3.12")
    result = validate_hash_lock(lock, requirements, expected_python=expected_python)
    lock_contract = manifest["python"]["lock"]
    for key in ("entry_count", "direct_count"):
        if result[key] != lock_contract[key]:
            raise ManifestError(
                f"manifest python.lock.{key} mismatch: "
                f"manifest={lock_contract[key]} actual={result[key]}"
            )
    declared_groups = {
        group: {normalize_distribution_name(name) for name in names}
        for group, names in manifest["python"]["license_groups"].items()
    }
    actual_groups = {
        group: {normalize_distribution_name(name) for name in details["packages"]}
        for group, details in result["direct_groups"].items()
    }
    if declared_groups != actual_groups:
        raise ManifestError("manifest python.license_groups does not match requirements input")
    return result


def _read_logical_lines(path: Path) -> list[str]:
    logical: list[str] = []
    current = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if current:
                logical.append(current)
                current = ""
            continue
        if line.startswith("--") and not line.startswith("--hash="):
            if current:
                logical.append(current)
                current = ""
            continue
        continuation = line.endswith("\\")
        if continuation:
            line = line[:-1].rstrip()
        current = f"{current} {line}".strip()
        if not continuation:
            logical.append(current)
            current = ""
    if current:
        logical.append(current)
    return logical


def parse_requirement_groups(path: Path) -> dict[str, dict[str, str]]:
    """Parse exact-pinned direct requirements and their declared purpose.

    The input file is intentionally the human-maintained grouping boundary;
    the generated lock remains the install authority.  A requirement outside
    a group or duplicated across groups fails closed.
    """

    groups: dict[str, dict[str, str]] = {}
    license_groups: dict[str, str] = {}
    current_group: str | None = None
    seen: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        group_match = GROUP_RE.match(line)
        if group_match:
            current_group = group_match.group("group")
            groups.setdefault(current_group, {})
            continue
        license_match = LICENSE_GROUP_RE.match(line)
        if license_match and current_group:
            license_groups[current_group] = license_match.group("group")
            continue
        if not line or line.startswith("#"):
            continue
        if line.startswith("-"):
            raise LockValidationError(f"unsupported option in requirements input: {line}")
        match = REQUIREMENT_RE.match(line)
        if not match:
            raise LockValidationError(f"requirements input must use exact == pins: {line}")
        if current_group is None:
            raise LockValidationError(f"ungrouped requirement: {line}")
        name = match.group("name")
        normalized = normalize_distribution_name(name)
        if normalized in EXCLUDED_DISTRIBUTIONS:
            raise LockValidationError(f"excluded distribution is not allowed: {name}")
        if normalized in seen:
            raise LockValidationError(
                f"requirement appears in multiple groups: {name} ({seen[normalized]}, {current_group})"
            )
        seen[normalized] = current_group
        groups[current_group][name] = match.group("version")

    if not groups or any(not values for values in groups.values()):
        raise LockValidationError("requirements input must contain non-empty groups")
    # Kept as an attribute-like side channel for callers that need the license
    # labels without making the public return shape harder to use in tests.
    parse_requirement_groups.last_license_groups = license_groups  # type: ignore[attr-defined]
    return groups


def declared_license_groups(path: Path) -> dict[str, dict[str, Any]]:
    groups = parse_requirement_groups(path)
    license_groups = getattr(parse_requirement_groups, "last_license_groups", {})
    return {
        group: {
            "license_group": license_groups.get(group, "UNDECLARED"),
            "packages": dict(sorted(values.items(), key=lambda item: normalize_distribution_name(item[0]))),
        }
        for group, values in sorted(groups.items())
    }


def _parse_lock_entries(path: Path) -> dict[str, LockEntry]:
    entries: dict[str, LockEntry] = {}
    for line in _read_logical_lines(path):
        hash_start = line.find("--hash=")
        if hash_start < 0:
            requirement_part = line
            hash_part = ""
        else:
            requirement_part = line[:hash_start].rstrip()
            hash_part = line[hash_start:]
        match = REQUIREMENT_RE.match(requirement_part)
        if not match:
            raise LockValidationError(f"invalid lock requirement line: {line}")
        if any(token in line for token in ("@", "git+", "file:", "http://", "https://")):
            raise LockValidationError(f"non-index requirement is not allowed in hash lock: {line}")
        hashes = tuple(
            f"{hash_match.group('algorithm').casefold()}:{hash_match.group('digest').casefold()}"
            for hash_match in HASH_RE.finditer(hash_part)
        )
        if not hashes:
            raise LockValidationError(f"lock entry has no hash: {line}")
        if any(not item.startswith("sha256:") or len(item) != len("sha256:") + 64 for item in hashes):
            raise LockValidationError(f"lock entry contains a non-SHA256 hash: {line}")
        normalized = normalize_distribution_name(match.group("name"))
        if normalized in EXCLUDED_DISTRIBUTIONS:
            raise LockValidationError(f"excluded distribution is present in lock: {match.group('name')}")
        if normalized in entries:
            raise LockValidationError(f"duplicate lock entry: {match.group('name')}")
        entries[normalized] = LockEntry(
            name=match.group("name"),
            version=match.group("version"),
            marker=match.group("marker"),
            hashes=hashes,
        )
    if not entries:
        raise LockValidationError("hash lock has no package entries")
    return entries


def validate_hash_lock(
    lock_path: Path,
    requirements_path: Path,
    *,
    expected_python: str = "3.12",
) -> dict[str, Any]:
    if not lock_path.is_file():
        raise LockValidationError(f"hash lock does not exist: {lock_path}")
    lock_text = lock_path.read_text(encoding="utf-8")
    if "autogenerated by pip-compile" not in lock_text:
        raise LockValidationError("hash lock is not marked as pip-compile output")
    header = "\n".join(lock_text.splitlines()[:8])
    version_match = PYTHON_VERSION_RE.search(header)
    if version_match is None or version_match.group("version") != expected_python:
        raise LockValidationError(
            f"hash lock must record Python {expected_python} in its compiler header"
        )
    groups = parse_requirement_groups(requirements_path)
    direct: dict[str, Requirement] = {}
    for group, values in groups.items():
        for name, version in values.items():
            direct[normalize_distribution_name(name)] = Requirement(name, version, group)
    entries = _parse_lock_entries(lock_path)
    missing = sorted(set(direct) - set(entries))
    if missing:
        raise LockValidationError(f"direct requirements missing from lock: {', '.join(missing)}")
    mismatched = [
        f"{direct[name].name}: input {direct[name].version} != lock {entries[name].version}"
        for name in direct
        if entries[name].version != direct[name].version
    ]
    if mismatched:
        raise LockValidationError("version mismatch: " + "; ".join(mismatched))
    return {
        "lock_sha256": lock_sha256(lock_path),
        "entry_count": len(entries),
        "direct_count": len(direct),
        "packages": [entry.name for _, entry in sorted(entries.items())],
        "direct_groups": declared_license_groups(requirements_path),
        "python": expected_python,
    }


def _venv_python(venv_dir: Path) -> Path:
    candidate = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not candidate.is_file():
        raise ToolchainRebuildError(f"virtualenv interpreter is missing: {candidate}")
    return candidate


def _filesystem_state(root: Path) -> dict[str, tuple[str, int, int, str]]:
    """Return a deterministic, non-following snapshot for side-effect checks."""

    state: dict[str, tuple[str, int, int, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            state[relative] = ("symlink", 0, 0, os.readlink(path))
            continue
        if path.is_dir():
            state[relative] = ("directory", 0, path.stat().st_mode & 0o777, "")
            continue
        if path.is_file():
            state[relative] = (
                "file",
                path.stat().st_size,
                path.stat().st_mode & 0o777,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return state


def run_import_probe(
    python_executable: Path,
    repo_root: Path,
    modules: Sequence[str],
    *,
    watch_root: Path | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    if not modules:
        raise ToolchainRebuildError("import probe requires at least one module")
    before = _filesystem_state(watch_root) if watch_root else None
    code = "import importlib; " + "; ".join(
        f"importlib.import_module({module!r})" for module in modules
    )
    env = os.environ.copy()
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(repo_root),
        }
    )
    completed = subprocess.run(
        [str(python_executable), "-c", code],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    after = _filesystem_state(watch_root) if watch_root else None
    changed = sorted(set(before or {}) ^ set(after or {})) if before is not None and after is not None else []
    if before is not None and after is not None:
        changed.extend(sorted(path for path in set(before) & set(after) if before[path] != after[path]))
    result = {
        "command": [str(python_executable), "-c", code],
        "modules": list(modules),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "changed_paths": changed,
    }
    if completed.returncode != 0:
        raise ToolchainRebuildError(
            f"Python import probe failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    if changed:
        raise ToolchainRebuildError(
            "Python import probe changed watched paths: " + ", ".join(changed)
        )
    return result


def _run_checked(command: Sequence[str], *, cwd: Path, timeout: int = 900) -> dict[str, Any]:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    result = {
        "command": list(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        raise ToolchainRebuildError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr.strip()}"
        )
    return result


def clean_python_rebuild(
    repo_root: Path,
    requirements_path: Path,
    lock_path: Path,
    rebuild_root: Path,
    *,
    python_executable: str,
    clean_install_contract: dict[str, list[str]],
    timeout: int = 900,
) -> dict[str, Any]:
    """Install the hash lock into a new venv and run only explicit imports.

    ``rebuild_root`` must be outside ``repo_root`` and must not already exist;
    this prevents silently inheriting a prior environment or overwriting a
    user-created directory.
    """

    repo_root = repo_root.resolve()
    requirements_path = requirements_path.resolve()
    lock_path = lock_path.resolve()
    rebuild_root = rebuild_root.resolve()
    if rebuild_root == repo_root or repo_root in rebuild_root.parents:
        raise ToolchainRebuildError("clean rebuild root must be outside the source tree")
    if rebuild_root.exists():
        raise ToolchainRebuildError(f"clean rebuild root already exists: {rebuild_root}")
    validation = validate_hash_lock(lock_path, requirements_path, expected_python="3.12")
    rebuild_root.parent.mkdir(parents=True, exist_ok=True)
    rebuild_root.mkdir()
    venv_dir = rebuild_root / ".venv"
    commands: list[dict[str, Any]] = []
    create_command = _render_manifest_command(
        clean_install_contract["venv_create"],
        {"{python}": python_executable, "{venv}": str(venv_dir)},
    )
    commands.append(_run_checked(create_command, cwd=repo_root, timeout=timeout))
    venv_python = _venv_python(venv_dir)
    install_command = _render_manifest_command(
        clean_install_contract["install"],
        {"{venv_python}": str(venv_python), "{lock}": str(lock_path)},
    )
    commands.append(
        _run_checked(
            install_command,
            cwd=repo_root,
            timeout=timeout,
        )
    )
    verify_command = _render_manifest_command(
        clean_install_contract["verify"],
        {"{venv_python}": str(venv_python)},
    )
    commands.append(_run_checked(verify_command, cwd=repo_root, timeout=timeout))
    import_result = run_import_probe(
        venv_python,
        repo_root,
        tuple(clean_install_contract["import_probe_modules"]),
        watch_root=repo_root,
        timeout=timeout,
    )
    return {
        "python": "3.12",
        "python_executable": str(venv_python),
        "lock": str(lock_path),
        "lock_sha256": validation["lock_sha256"],
        "entry_count": validation["entry_count"],
        "rebuild_root": str(rebuild_root),
        "commands": commands,
        "import_probe": import_result,
    }


def _render_manifest_command(
    template: Sequence[str],
    replacements: dict[str, str],
) -> list[str]:
    """Render only whole-token placeholders from a structurally frozen command."""

    rendered: list[str] = []
    for token in template:
        if token in replacements:
            rendered.append(replacements[token])
        elif "{" in token or "}" in token:
            raise ManifestError(f"unresolved manifest command placeholder: {token}")
        else:
            rendered.append(token)
    return rendered


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=None,
                        help="canonical frozen manifest path; alternate paths fail closed")
    parser.add_argument("--rebuild-root", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def _run_manifest_mode(args: argparse.Namespace) -> dict[str, Any]:
    """Manifest-only verification: hash pre-check, Python lock validation, optional rebuild."""
    manifest = load_manifest(args.repo_root, args.manifest)
    hash_check = validate_manifest_hashes(args.repo_root, args.manifest, manifest=manifest)
    lock_validation = python_lock_validation_from_manifest(args.repo_root, args.manifest, manifest=manifest)
    result: dict[str, Any] = {
        "mode": "manifest",
        "manifest": str(args.manifest or MANIFEST_PATH),
        "hash_check": hash_check,
        "python_lock": lock_validation,
    }
    rebuild_root = getattr(args, "rebuild_root", None)
    if rebuild_root:
        requirements = _resolve_manifest_path(args.repo_root, manifest["python"]["requirements_input"]["path"])
        lock = _resolve_manifest_path(args.repo_root, manifest["python"]["lock"]["path"])
        result["rebuild"] = clean_python_rebuild(
            args.repo_root,
            requirements,
            lock,
            rebuild_root,
            python_executable=manifest["python"]["interpreter"],
            clean_install_contract=manifest["python"]["clean_install"],
        )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = _run_manifest_mode(args)
        payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        print(payload)
        return 0
    except (LockValidationError, ManifestError, ToolchainRebuildError, OSError, subprocess.SubprocessError) as exc:
        print(f"toolchain verification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
