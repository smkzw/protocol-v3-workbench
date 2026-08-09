from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from services.api.app.monitoring_real_loop_semantics_binding import (
    RealLoopSemanticsBindingIssueCode,
    bind_real_loop_semantics,
)


class RealLoopSemanticsBindingTests(unittest.TestCase):
    WORKBENCH = Path(__file__).resolve().parents[1]
    MANIFEST = (
        WORKBENCH
        / "records/active_slices/medical_monitoring_real_loop_current_manifest_20260804/"
        "CURRENT_REAL_LOOP_GATE_MANIFEST.json"
    )
    SNAPSHOT = (
        WORKBENCH
        / "records/active_slices/medical_monitoring_real_loop_evidence_semantics_20260804/"
        "CURRENT_REAL_LOOP_EVIDENCE_SEMANTICS.json"
    )

    def load_pair(self) -> tuple[dict, dict]:
        return (
            json.loads(self.MANIFEST.read_text(encoding="utf-8")),
            json.loads(self.SNAPSHOT.read_text(encoding="utf-8")),
        )

    def test_current_semantic_snapshot_matches_current_manifest(self) -> None:
        manifest, snapshot = self.load_pair()

        first = bind_real_loop_semantics(manifest, snapshot)
        second = bind_real_loop_semantics(manifest, snapshot)

        self.assertEqual("matched", first.status)
        self.assertEqual((), first.issues)
        self.assertEqual(first.report_sha256, second.report_sha256)
        self.assertEqual(manifest["report_sha256"], first.manifest_report_sha256)
        self.assertEqual(snapshot["snapshot_sha256"], first.snapshot_sha256)
        self.assertEqual(first.snapshot_sha256, first.recomputed_snapshot_sha256)
        self.assertFalse(first.to_dict()["runtime_activation_permitted"])
        self.assertFalse(first.to_dict()["provider_call_permitted"])
        self.assertFalse(first.to_dict()["write_permitted"])

    def test_manifest_report_hash_mutation_blocks_binding(self) -> None:
        manifest, snapshot = self.load_pair()
        manifest["report_sha256"] = "0" * 64

        report = bind_real_loop_semantics(manifest, snapshot)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopSemanticsBindingIssueCode.SOURCE_MANIFEST_HASH_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_snapshot_source_hash_mutation_blocks_binding(self) -> None:
        manifest, snapshot = self.load_pair()
        snapshot["source_manifest_report_sha256"] = "f" * 64

        report = bind_real_loop_semantics(manifest, snapshot)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopSemanticsBindingIssueCode.SOURCE_MANIFEST_HASH_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_mapping_result_hash_mutation_blocks_binding(self) -> None:
        manifest, snapshot = self.load_pair()
        snapshot["rows"][0]["mapping_result_sha256"] = "f" * 64
        snapshot["rows"][0]["semantic_sha256"] = "0" * 64
        snapshot["snapshot_sha256"] = "0" * 64

        report = bind_real_loop_semantics(manifest, snapshot)

        self.assertEqual("blocked", report.status)
        codes = {issue.code for issue in report.issues}
        self.assertIn(RealLoopSemanticsBindingIssueCode.MAPPING_RESULT_HASH_MISMATCH, codes)
        self.assertIn(RealLoopSemanticsBindingIssueCode.SEMANTIC_HASH_INVALID, codes)

    def test_derived_status_mutation_blocks_binding(self) -> None:
        manifest, snapshot = self.load_pair()
        snapshot["rows"][2]["derived_status"] = "proven"
        snapshot["rows"][2]["semantic_sha256"] = "0" * 64
        snapshot["snapshot_sha256"] = "0" * 64

        report = bind_real_loop_semantics(manifest, snapshot)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopSemanticsBindingIssueCode.DERIVED_STATUS_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_authority_or_generic_signature_mutation_blocks_binding(self) -> None:
        manifest, snapshot = self.load_pair()
        snapshot["signature_verified"] = True
        snapshot["write_permitted"] = True
        snapshot["snapshot_sha256"] = "0" * 64

        report = bind_real_loop_semantics(manifest, snapshot)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopSemanticsBindingIssueCode.AUTHORITY_FLAG_TRUE,
            {issue.code for issue in report.issues},
        )

    def test_missing_gate_or_invalid_shape_fails_closed(self) -> None:
        manifest, snapshot = self.load_pair()
        del snapshot["rows"][-1]

        report = bind_real_loop_semantics(manifest, snapshot)
        malformed = bind_real_loop_semantics(None, snapshot)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopSemanticsBindingIssueCode.GATE_SET_MISMATCH,
            {issue.code for issue in report.issues},
        )
        self.assertEqual("blocked", malformed.status)
        self.assertIn(
            RealLoopSemanticsBindingIssueCode.MANIFEST_SHAPE_INVALID,
            {issue.code for issue in malformed.issues},
        )

    def test_snapshot_mutation_does_not_change_original_pair(self) -> None:
        manifest, snapshot = self.load_pair()
        changed = deepcopy(snapshot)
        changed["rows"][1]["issue_count"] = 99

        report = bind_real_loop_semantics(manifest, changed)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopSemanticsBindingIssueCode.ISSUE_COUNT_MISMATCH,
            {issue.code for issue in report.issues},
        )


if __name__ == "__main__":
    unittest.main()
