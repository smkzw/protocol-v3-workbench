from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIR = _ROOT / "scripts/qc/protocol_v3"
sys.path.insert(0, str(_SCRIPT_DIR))

from verify_toolchain_rebuild import (  # noqa: E402
    ManifestError,
    MANIFEST_PATH,
    MANIFEST_SCHEMA,
    load_manifest,
    python_lock_validation_from_manifest,
    validate_manifest_hashes,
)


def _copy_manifest(repo_root: Path, manifest_root: Path) -> Path:
    """Copy the real manifest into a temp repo_root so tests can mutate safely."""
    manifest_text = (manifest_root / MANIFEST_PATH).read_text(encoding="utf-8")
    target_dir = repo_root / MANIFEST_PATH.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    target = repo_root / MANIFEST_PATH
    target.write_text(manifest_text, encoding="utf-8")
    return target


def _stage_manifest_files(repo_root: Path, manifest_root: Path) -> None:
    """Copy every hash-referenced source file into the temp repo_root."""
    manifest = json.loads((manifest_root / MANIFEST_PATH).read_text(encoding="utf-8"))
    referenced = [
        manifest["python"]["requirements_input"]["path"],
        manifest["python"]["lock"]["path"],
        manifest["frontend"]["package"]["path"],
        manifest["frontend"]["lock"]["path"],
        manifest["frontend"]["test_inventory"]["path"],
        manifest["frontend"]["quarantined_inactive_pnpm"]["pnpm_lock"]["path"],
        manifest["frontend"]["quarantined_inactive_pnpm"]["pnpm_workspace"]["path"],
    ]
    for relative in referenced:
        src = manifest_root / relative
        dst = repo_root / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())


class ToolchainManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_manifest(_ROOT)

    def test_manifest_schema_and_required_sections(self) -> None:
        self.assertEqual(self.manifest["schema_version"], MANIFEST_SCHEMA)
        self.assertIn("python", self.manifest)
        self.assertIn("frontend", self.manifest)
        self.assertEqual(self.manifest["frontend"]["package_manager"], "npm")
        self.assertEqual(
            self.manifest["frontend"]["quarantined_inactive_pnpm"]["status"],
            "inactive_quarantined",
        )

    def test_manifest_rejects_alternate_path_even_with_same_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            alternate = Path(tmp) / "alternate.json"
            alternate.write_text(
                (_ROOT / MANIFEST_PATH).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ManifestError, "alternate toolchain manifest is forbidden"):
                load_manifest(_ROOT, alternate)

    def test_manifest_rejects_true_as_install_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = _copy_manifest(repo, _ROOT)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["frontend"]["scripts"]["install"] = ["/usr/bin/true"]
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "scripts.install"):
                load_manifest(repo, target)

    def test_python_execution_authority_is_structurally_frozen(self) -> None:
        mutations = (
            (
                "absolute requirements path",
                lambda data: data["python"]["requirements_input"].update(
                    {"path": "/private/tmp/requirements.in"}
                ),
                "requirements_input.path",
            ),
            (
                "fake install",
                lambda data: data["python"]["clean_install"].update(
                    {"install": ["/usr/bin/true"]}
                ),
                "clean_install",
            ),
            (
                "interpreter override",
                lambda data: data["python"].update(
                    {"interpreter": "/usr/bin/true"}
                ),
                "interpreter",
            ),
        )
        for label, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                target = _copy_manifest(repo, _ROOT)
                data = json.loads(target.read_text(encoding="utf-8"))
                mutate(data)
                target.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ManifestError, expected_error):
                    load_manifest(repo, target)

    def test_frontend_execution_metadata_is_structurally_frozen(self) -> None:
        mutations = (
            ("node version", lambda data: data["frontend"].update({"node_version": "0.0.0"}), "node_version"),
            ("npm version", lambda data: data["frontend"].update({"npm_version": "0.0.0"}), "npm_version"),
            (
                "package manager field",
                lambda data: data["frontend"]["package"].update(
                    {"package_manager_field": "npm@0.0.0"}
                ),
                "package_manager_field",
            ),
            (
                "node binary authority",
                lambda data: data["frontend"]["runtime_binaries"]["node"].update(
                    {"sha256": "0" * 64}
                ),
                "runtime_binaries.node",
            ),
            (
                "lockfile version",
                lambda data: data["frontend"]["lock"].update({"lockfile_version": 2}),
                "lockfile_version",
            ),
            (
                "package count",
                lambda data: data["frontend"]["lock"].update({"package_count": 1}),
                "package_count",
            ),
            (
                "inventory schema",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"schema_version": "wrong"}
                ),
                "schema_version",
            ),
            (
                "ignored directories",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"ignored_directories": []}
                ),
                "ignored_directories",
            ),
            (
                "test suffixes",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"test_suffixes": {".test.mjs": "vitest"}}
                ),
                "test_suffixes",
            ),
            (
                "vitest paths",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"vitest_paths": ["fake.test.jsx"]}
                ),
                "vitest_paths",
            ),
            (
                "explicit Node QC paths",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"explicit_node_paths": []}
                ),
                "explicit_node_paths",
            ),
            (
                "controlled QC exclusions",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"excluded_controlled_qc_paths": []}
                ),
                "excluded_controlled_qc_paths",
            ),
            (
                "controlled QC exclusion reason",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"excluded_controlled_qc_reason": "generic exclusion"}
                ),
                "excluded_controlled_qc_reason",
            ),
            (
                "stale QC exclusions",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"excluded_stale_qc_paths": []}
                ),
                "excluded_stale_qc_paths",
            ),
            (
                "stale QC exclusion reason",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"excluded_stale_qc_reason": "generic exclusion"}
                ),
                "excluded_stale_qc_reason",
            ),
            (
                "vitest args",
                lambda data: data["frontend"].update({"vitest_args": ["/usr/bin/true"]}),
                "vitest_args",
            ),
            (
                "vitest entry",
                lambda data: data["frontend"].update({"vitest_entry": "/usr/bin/true"}),
                "vitest_entry",
            ),
            (
                "node runner args",
                lambda data: data["frontend"].update({"node_runner_args": ["/usr/bin/true"]}),
                "node_runner_args",
            ),
        )
        for label, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                target = _copy_manifest(repo, _ROOT)
                data = json.loads(target.read_text(encoding="utf-8"))
                mutate(data)
                target.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ManifestError, expected_error):
                    load_manifest(repo, target)

    def test_package_build_script_cannot_be_coforged_with_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = _copy_manifest(repo, _ROOT)
            _stage_manifest_files(repo, _ROOT)
            package_path = repo / "frontend/package.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["scripts"]["build"] = "true"
            package_path.write_text(json.dumps(package), encoding="utf-8")
            data = json.loads(target.read_text(encoding="utf-8"))
            data["frontend"]["package"]["sha256"] = (
                hashlib.sha256(package_path.read_bytes()).hexdigest()
            )
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ManifestError, "frozen source authority|scripts.build"):
                validate_manifest_hashes(repo, target)

    def test_dependency_source_and_manifest_hash_cannot_be_coforged(self) -> None:
        mutations = (
            ("frontend package", "frontend", "package", "frontend/package.json"),
            ("frontend lock", "frontend", "lock", "frontend/package-lock.json"),
            ("Python input", "python", "requirements_input", "services/api/requirements-protocol-v3.in"),
            ("Python lock", "python", "lock", "services/api/requirements-protocol-v3.lock"),
            ("test inventory", "frontend", "test_inventory", "frontend/tests/protocol_v3_test_inventory.mjs"),
        )
        for label, top, section, relative in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                target = _copy_manifest(repo, _ROOT)
                _stage_manifest_files(repo, _ROOT)
                source = repo / relative
                source.write_bytes(source.read_bytes() + b"\n")
                data = json.loads(target.read_text(encoding="utf-8"))
                data[top][section]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
                target.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ManifestError, "frozen source authority"):
                    validate_manifest_hashes(repo, target)

    def test_inventory_counts_and_path_identity_are_frozen(self) -> None:
        mutations = (
            (
                "counts",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"counts": {"total": 9, "vitest": 3, "node": 6}}
                ),
                "counts",
            ),
            (
                "path identity",
                lambda data: data["frontend"]["test_inventory"].update(
                    {"paths_sha256": "0" * 64}
                ),
                "paths_sha256",
            ),
        )
        for label, mutate, expected_error in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                target = _copy_manifest(repo, _ROOT)
                data = json.loads(target.read_text(encoding="utf-8"))
                mutate(data)
                target.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaisesRegex(ManifestError, expected_error):
                    load_manifest(repo, target)

    def test_manifest_counts_must_match_the_hash_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = _copy_manifest(repo, _ROOT)
            _stage_manifest_files(repo, _ROOT)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["python"]["lock"]["entry_count"] += 1
            target.write_text(json.dumps(data), encoding="utf-8")
            manifest = load_manifest(repo, target)
            with self.assertRaisesRegex(ManifestError, "entry_count mismatch"):
                python_lock_validation_from_manifest(repo, target, manifest=manifest)

    def test_manifest_hashes_match_disk(self) -> None:
        result = validate_manifest_hashes(_ROOT)
        self.assertTrue(result["checks"], "manifest must declare at least one hash check")
        for check in result["checks"]:
            self.assertTrue(
                check["ok"],
                f"hash mismatch: {check['label']} {check['path']}",
            )

    def test_package_lock_is_the_only_active_frontend_lock(self) -> None:
        active = sorted(
            path.name
            for path in (_ROOT / "frontend").iterdir()
            if path.is_file() and ("lock" in path.name or "workspace" in path.name)
        )
        self.assertEqual(active, ["package-lock.json"])
        quarantine = self.manifest["frontend"]["quarantined_inactive_pnpm"]
        for key in ("pnpm_lock", "pnpm_workspace"):
            self.assertTrue((_ROOT / quarantine[key]["path"]).is_file())

    def test_python_lock_validates_from_manifest(self) -> None:
        result = python_lock_validation_from_manifest(_ROOT)
        self.assertEqual(result["entry_count"], self.manifest["python"]["lock"]["entry_count"])
        self.assertEqual(result["direct_count"], self.manifest["python"]["lock"]["direct_count"])

    def test_manifest_rejects_wrong_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = _copy_manifest(repo, _ROOT)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["schema_version"] = "protocol-v3-toolchain.v0"
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                load_manifest(repo, target)

    def test_manifest_fails_closed_on_stale_lock_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = _copy_manifest(repo, _ROOT)
            _stage_manifest_files(repo, _ROOT)
            # Point a required file (the Python lock) at a wrong hash so the
            # pre-execution gate fails.  We do NOT mutate the source file: only
            # the manifest hash, which is exactly the staleness we must catch.
            data = json.loads(target.read_text(encoding="utf-8"))
            data["python"]["lock"]["sha256"] = "0" * 64
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError) as ctx:
                validate_manifest_hashes(repo, target)
            self.assertIn("python.lock sha256 does not match the frozen source authority", str(ctx.exception))

    def test_manifest_rejects_non_hex_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = _copy_manifest(repo, _ROOT)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["frontend"]["lock"]["sha256"] = "not-a-hex-digest"
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                validate_manifest_hashes(repo, target)

    def test_manifest_rejects_missing_referenced_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target = _copy_manifest(repo, _ROOT)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["frontend"]["test_inventory"]["path"] = "frontend/tests/does_not_exist.mjs"
            target.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ManifestError):
                validate_manifest_hashes(repo, target)


if __name__ == "__main__":
    unittest.main()
