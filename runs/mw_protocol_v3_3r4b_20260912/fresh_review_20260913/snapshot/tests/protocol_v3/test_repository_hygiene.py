from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "scripts/qc/protocol_v3"))

from classify_repository import build_inventory, load_rules
from verify_repository_hygiene import HygieneError, verify_inventory_against_root


class RepositoryHygieneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = load_rules(
            _ROOT / "config/medical_writing/protocol_v3/repository_hygiene_rules.json"
        )

    def _write(self, root: Path, relative: str, text: str = "x\n") -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_inventory_assigns_all_seven_explainable_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "packages/contracts/workbench_contracts/models.py")
            self._write(root, "services/api/app/medical_writing_legacy.py")
            self._write(root, "tests/test_medical_writing_regression.py")
            self._write(root, "runs/old_run.md")
            self._write(root, "frontend/node_modules/pkg/index.js")
            self._write(root, "loose_unknown.bin")
            self._write(root, "poc/medical_monitoring_ai_native_r1/src/domain.py")
            self._write(root, "logs/agent_health/pi-opencode-go-deepseek-v4-flash.json")
            self._write(root, "runtime/medical_writing.sqlite3", "")
            self._write(root, "services/api/assets/medical_writing_corpus/corpus.jsonl")
            self._write(root, "--indications")
            self._write(root, "records/handoffs/CODEX_NO_LOSS_PAUSE_MEDICAL_MONITORING.md")
            self._write(root, "runs/browser_profile/DIPS-wal")

            inventory = build_inventory(root, self.rules, task_id="unit-test", workers=2)
            by_path = {entry["path"]: entry for entry in inventory["entries"]}

            self.assertEqual(by_path["packages/contracts/workbench_contracts/models.py"]["classification"], "reuse")
            self.assertEqual(by_path["services/api/app/medical_writing_legacy.py"]["classification"], "migrate_then_retire")
            self.assertEqual(by_path["tests/test_medical_writing_regression.py"]["classification"], "authority_regression")
            self.assertEqual(by_path["runs/old_run.md"]["classification"], "historical_archive")
            self.assertEqual(by_path["frontend/node_modules/pkg/index.js"]["classification"], "regenerable")
            self.assertEqual(by_path["loose_unknown.bin"]["classification"], "quarantine")
            self.assertEqual(by_path["poc/medical_monitoring_ai_native_r1/src/domain.py"]["classification"], "protected_out_of_scope")
            self.assertEqual(by_path["logs/agent_health/pi-opencode-go-deepseek-v4-flash.json"]["owner"], "harness_runtime")
            self.assertEqual(by_path["runtime/medical_writing.sqlite3"]["owner"], "immutable_runtime_evidence")
            self.assertEqual(by_path["services/api/assets/medical_writing_corpus/corpus.jsonl"]["classification"], "authority_regression")
            self.assertEqual(by_path["--indications"]["owner"], "orphan_process_artifact")
            self.assertEqual(by_path["records/handoffs/CODEX_NO_LOSS_PAUSE_MEDICAL_MONITORING.md"]["owner"], "medical_monitoring")
            self.assertEqual(by_path["runs/browser_profile/DIPS-wal"]["owner"], "immutable_runtime_evidence")
            self.assertEqual(inventory["summary"]["entry_count"], 13)
            self.assertEqual(set(inventory["summary"]["classification_counts"]), set(self.rules["classifications"]))

    def test_nested_workbench_records_canonical_hash_relation_and_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "same.py", "same\n")
            self._write(root, "implementation/workbench/same.py", "same\n")
            self._write(root, "different.py", "new\n")
            self._write(root, "implementation/workbench/different.py", "old\n")

            inventory = build_inventory(root, self.rules, task_id="unit-test", workers=2)
            by_path = {entry["path"]: entry for entry in inventory["entries"]}
            same = by_path["implementation/workbench/same.py"]
            different = by_path["implementation/workbench/different.py"]

            self.assertEqual(same["canonical_relation"]["status"], "same_hash")
            self.assertEqual(different["canonical_relation"]["status"], "hash_conflict")
            self.assertTrue(same["quarantine_blocked"])
            self.assertTrue(different["quarantine_blocked"])
            self.assertIn("nested_canonical_hash_conflict", different["mutation_blockers"])

    def test_symlink_metadata_and_post_inventory_change_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self._write(root, "services/api/app/module.py", "VALUE = 1\n")
            os.symlink("module.py", root / "services/api/app/module_link.py")
            inventory = build_inventory(root, self.rules, task_id="unit-test", workers=2)
            by_path = {entry["path"]: entry for entry in inventory["entries"]}
            self.assertEqual(by_path["services/api/app/module_link.py"]["path_type"], "symlink")
            self.assertEqual(by_path["services/api/app/module_link.py"]["link_target"], "module.py")
            verify_inventory_against_root(inventory, root)

            target.write_text("VALUE = 2\n", encoding="utf-8")
            with self.assertRaises(HygieneError):
                verify_inventory_against_root(inventory, root)

    def test_inventory_is_json_serializable_and_records_reference_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "services/api/app/helper.py", "VALUE = 1\n")
            self._write(root, "services/api/app/main.py", "from . import helper\n")
            self._write(root, "tests/test_helper.py", "import helper\n")
            self._write(root, "runs/checkpoint.md", "See services/api/app/helper.py\n")

            inventory = build_inventory(root, self.rules, task_id="unit-test", workers=2)
            helper = next(entry for entry in inventory["entries"] if entry["path"] == "services/api/app/helper.py")
            self.assertGreaterEqual(helper["references"]["production"], 1)
            self.assertGreaterEqual(helper["references"]["test"], 1)
            self.assertGreaterEqual(helper["references"]["checkpoint"], 1)
            json.dumps(inventory, ensure_ascii=False, sort_keys=True)

    def test_new_path_owner_is_resolved_by_rules_not_filename_substring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "services/api/app/main.py")
            inventory = build_inventory(root, self.rules, task_id="unit-test", workers=2)

            self._write(root, "notes/medical_monitoring_injection.txt")
            with self.assertRaises(HygieneError):
                verify_inventory_against_root(
                    inventory,
                    root,
                    allowed_drift_owners=("medical_monitoring",),
                    rules=self.rules,
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write(root, "services/api/app/main.py")
            inventory = build_inventory(root, self.rules, task_id="unit-test", workers=2)
            self._write(
                root,
                "prompts/execution/medical_monitoring_ai_native_r1/worker_followup.md",
            )
            result = verify_inventory_against_root(
                inventory,
                root,
                allowed_drift_owners=("medical_monitoring",),
                rules=self.rules,
            )
            self.assertEqual(result["blocked_drift_count"], 0)
            self.assertEqual(result["allowed_added"][0]["owner"], "medical_monitoring")


if __name__ == "__main__":
    unittest.main()
