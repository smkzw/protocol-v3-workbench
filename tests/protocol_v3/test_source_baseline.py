from __future__ import annotations

import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

_THIS_FILE = Path(__file__).resolve()
_ISOLATED_SCRIPT_DIR = _THIS_FILE.parents[2] / "scripts/qc/protocol_v3"
if _ISOLATED_SCRIPT_DIR.is_dir():
    sys.path.insert(0, str(_ISOLATED_SCRIPT_DIR))

from build_source_baseline import (
    BaselineError,
    build_manifest,
    create_source_tar,
    is_source_candidate,
    validate_plan_poc_paths,
    validate_relative_path,
)
from verify_source_baseline import (
    safe_extract_tar,
    verify_manifest_against_root,
    verify_tar_against_manifest,
)


class SourcePolicyTests(unittest.TestCase):
    def test_allowlist_keeps_required_source_and_toolchain_files(self) -> None:
        allowed = (
            "AGENTS.md",
            "README.md",
            "pytest.ini",
            "packages/contracts/workbench_contracts/models.py",
            "services/api/app/main.py",
            "services/api/requirements-medical-writing.txt",
            "frontend/AGENTS.md",
            "frontend/package.json",
            "frontend/package-lock.json",
            "frontend/pnpm-lock.yaml",
            "frontend/pnpm-workspace.yaml",
            "frontend/src/App.jsx",
            "frontend/tests/example_qc.mjs",
            "tests/test_example.py",
            "scripts/qc/example.py",
            "tools/openxml_docx_validator/Program.cs",
            "tools/openxml_docx_validator/bin/osx-arm64/openxml-docx-validator",
            "config/ai.env.example",
            "deploy/medical_writing_local/build_release_bundle.py",
            "plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md",
            "plans/mw_system_rearchitecture_design_decisions_20260808.md",
            ".hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md",
            "pocs/protocol_v3/word_receipt/contract.py",
        )
        for relative_path in allowed:
            with self.subTest(relative_path=relative_path):
                self.assertTrue(is_source_candidate(relative_path))

    def test_allowlist_rejects_runtime_evidence_cache_and_sensitive_files(self) -> None:
        rejected = (
            "runtime/state.sqlite3",
            "runs/run.md",
            "records/item.json",
            "evidence/receipt.pdf",
            "archives/archive.tar",
            "services/api/app/state.sqlite3",
            "services/api/app/__pycache__/main.pyc",
            "frontend/node_modules/react/index.js",
            "frontend/dist/index.html",
            "frontend/.npm-cache/_cacache/x",
            "frontend/tests/worker_02_evidence/screenshot.png",
            "deploy/medical_writing_local/logs/backend.log",
            "tools/openxml_docx_validator/bin/Release/net8.0/app",
            "tools/openxml_docx_validator/obj/project.assets.json",
            "pocs/protocol_v3/word_receipt/results/receipt.json",
            "pocs/protocol_v3/word_receipt/fixture.docx",
            ".env",
            "config/private.pem",
            "frontend/.npmrc",
        )
        for relative_path in rejected:
            with self.subTest(relative_path=relative_path):
                self.assertFalse(is_source_candidate(relative_path))

    def test_relative_path_validation_rejects_escape_and_absolute_paths(self) -> None:
        for value in ("../escape", "a/../../escape", "/absolute", "", "."):
            with self.subTest(value=value):
                with self.assertRaises(BaselineError):
                    validate_relative_path(value)

    def test_plan_poc_inventory_rejects_uncovered_extensions(self) -> None:
        self.assertEqual(
            validate_plan_poc_paths(
                "Create: pocs/protocol_v3/editor/runner.py\n"
                "Test: pocs/protocol_v3/editor/tests/test_runner.py\n"
            ),
            [
                "pocs/protocol_v3/editor/runner.py",
                "pocs/protocol_v3/editor/tests/test_runner.py",
            ],
        )
        with self.assertRaises(BaselineError):
            validate_plan_poc_paths("Create: pocs/protocol_v3/editor/result.bin\n")


class ManifestAndTarTests(unittest.TestCase):
    def _make_source_root(self, root: Path) -> None:
        (root / "services/api/app").mkdir(parents=True)
        (root / "frontend/src").mkdir(parents=True)
        (root / "plans").mkdir(parents=True)
        (root / ".hermes/plans").mkdir(parents=True)
        (root / "AGENTS.md").write_text("rules\n", encoding="utf-8")
        (root / "services/api/app/example.py").write_text("VALUE = 1\n", encoding="utf-8")
        (root / "frontend/src/example.jsx").write_text("export default 1\n", encoding="utf-8")
        (root / "plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md").write_text(
            "design\n", encoding="utf-8"
        )
        (root / ".hermes/plans/2026-08-09_020923-mw-protocol-multi-agent-rearchitecture.md").write_text(
            "plan\n", encoding="utf-8"
        )

    def test_manifest_and_tar_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            extracted = base / "extracted"
            tar_path = base / "source.tar"
            source.mkdir()
            self._make_source_root(source)

            manifest = build_manifest(source, task_id="unit-test")
            create_source_tar(source, manifest, tar_path)
            verify_tar_against_manifest(tar_path, manifest, extracted)
            verify_manifest_against_root(manifest, extracted)

            paths = {entry["path"] for entry in manifest["entries"]}
            self.assertIn("services/api/app/example.py", paths)
            self.assertNotIn("source.tar", paths)

    def test_manifest_detects_post_snapshot_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            self._make_source_root(source)
            manifest = build_manifest(source, task_id="unit-test")
            (source / "services/api/app/example.py").write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaises(BaselineError):
                verify_manifest_against_root(manifest, source)

    def test_external_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source.mkdir()
            self._make_source_root(source)
            outside = base / "outside.py"
            outside.write_text("secret\n", encoding="utf-8")
            os.symlink(outside, source / "services/api/app/external.py")
            with self.assertRaises(BaselineError):
                build_manifest(source, task_id="unit-test")

    def test_safe_extract_rejects_traversal_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tar_path = base / "bad.tar"
            with tarfile.open(tar_path, "w") as archive:
                info = tarfile.TarInfo("../escape.txt")
                payload = b"escape"
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            with self.assertRaises(BaselineError):
                safe_extract_tar(tar_path, base / "out")

    def test_manifest_json_is_serializable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            source.mkdir()
            self._make_source_root(source)
            serialized = json.dumps(build_manifest(source, task_id="unit-test"), sort_keys=True)
            self.assertIn('"schema_version": 1', serialized)


if __name__ == "__main__":
    unittest.main()
