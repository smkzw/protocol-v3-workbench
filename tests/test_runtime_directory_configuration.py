from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeDirectoryConfigurationTests(unittest.TestCase):
    def test_all_mutable_stores_follow_runtime_directory_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_dir = Path(temp_dir).resolve()
            script = """
import json
import services.api.app.main as main

print(json.dumps({
    "runtime_dir": str(main.RUNTIME_DIR),
    "sqlite": str(main.runtime_store.db_path),
    "ai_runs": str(main.ai_task_runner.store.jsonl_path),
    "source_registry": str(main.source_registry.store.jsonl_path),
    "tfl": str(main.tfl_review_store.path),
    "safety": str(main.safety_review_store.runtime_store.db_path),
    "inbox": str(main.workbench_inbox_service.store.path),
    "writing_reference_artifact_root": str(main._writing_reference_artifact_root),
    "writing_reference_artifact_root_exists": main._writing_reference_artifact_root.is_dir(),
    "ocr_gateway_configured": main._ocr_gateway is not None,
}, ensure_ascii=False))
"""
            env = os.environ.copy()
            env["WORKBENCH_RUNTIME_DIR"] = str(runtime_dir)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
                timeout=90,
            )
            payload = json.loads(result.stdout.strip().splitlines()[-1])

            self.assertEqual(str(runtime_dir), payload.pop("runtime_dir"))
            self.assertTrue(payload.pop("writing_reference_artifact_root_exists"))
            self.assertTrue(payload.pop("ocr_gateway_configured"))
            for path in payload.values():
                self.assertEqual(runtime_dir, Path(path).parent)


if __name__ == "__main__":
    unittest.main()
