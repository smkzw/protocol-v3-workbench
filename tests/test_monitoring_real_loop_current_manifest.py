from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from services.api.app.monitoring_real_loop_current_manifest import (
    RealLoopCurrentGateArtifact,
    RealLoopCurrentManifestIssueCode,
    build_real_loop_current_manifest,
)
from services.api.app.monitoring_real_loop_readiness import REAL_LOOP_UPSTREAM_GATE_NAMES


class RealLoopCurrentManifestTests(unittest.TestCase):
    WORKBENCH = Path(__file__).resolve().parents[1]

    def load_artifact(self, gate: str, relative: str, ref: str) -> RealLoopCurrentGateArtifact:
        path = self.WORKBENCH / relative
        return RealLoopCurrentGateArtifact(
            gate=gate,
            evidence_ref=ref,
            artifact_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            payload=json.loads(path.read_text(encoding="utf-8")),
        )

    def current_artifacts(self) -> list[RealLoopCurrentGateArtifact]:
        return [
            self.load_artifact(
                "b6_approved",
                "runs/execution/medical_monitoring_phase_b6_review_gate_20260801/"
                "B6_REVIEW_OUTCOME_GATE.json",
                "ref:fs:b6-review-gate",
            ),
            self.load_artifact(
                "approved_input_ready",
                "records/active_slices/medical_monitoring_approved_input_source_binding_20260803/"
                "APPROVED_INPUT_SOURCE_BINDING.json",
                "ref:fs:approved-input-binding",
            ),
            self.load_artifact(
                "source_token_revalidated",
                "records/active_slices/medical_monitoring_source_token_evidence_revalidation_20260803/"
                "SOURCE_TOKEN_EVIDENCE_REVALIDATION.json",
                "ref:fs:source-token-revalidation",
            ),
            self.load_artifact(
                "aggregate_cas_complete",
                "records/active_slices/medical_monitoring_aggregate_cas_revalidation_20260803/"
                "B4_AGGREGATE_CAS_REVALIDATION.json",
                "ref:fs:aggregate-cas-revalidation",
            ),
            RealLoopCurrentGateArtifact("runtime_identity_verified"),
        ]

    def test_current_filesystem_manifest_is_blocked_and_deterministic(self) -> None:
        first = build_real_loop_current_manifest(self.current_artifacts())
        second = build_real_loop_current_manifest(self.current_artifacts())

        self.assertEqual("blocked", first.status)
        self.assertEqual(first.report_sha256, second.report_sha256)
        self.assertEqual(5, len(first.rows))
        self.assertEqual(
            ["blocked", "blocked", "not_proven", "blocked", "missing"],
            [row.status for row in first.rows],
        )
        self.assertEqual((), first.issues)
        self.assertEqual("assembled", first.assembly.status)
        self.assertEqual((), first.assembly.issues)
        self.assertFalse(first.gate_input.b6_approved)
        self.assertFalse(first.gate_input.approved_input_ready)
        self.assertFalse(first.gate_input.source_token_revalidated)
        self.assertFalse(first.gate_input.aggregate_cas_complete)
        self.assertFalse(first.gate_input.runtime_identity_verified)
        self.assertFalse(first.to_dict()["write_permitted"])

    def test_payload_mutation_changes_manifest_identity(self) -> None:
        artifacts = self.current_artifacts()
        original = build_real_loop_current_manifest(artifacts)
        changed = deepcopy(artifacts[0].payload)
        changed["gate"]["pending_candidate_record_ids"] = ["new-pending"]
        artifacts[0] = RealLoopCurrentGateArtifact(
            gate=artifacts[0].gate,
            evidence_ref=artifacts[0].evidence_ref,
            artifact_sha256=artifacts[0].artifact_sha256,
            payload=changed,
        )

        mutated = build_real_loop_current_manifest(artifacts)

        self.assertNotEqual(original.report_sha256, mutated.report_sha256)
        self.assertNotEqual(
            original.rows[0].payload_sha256, mutated.rows[0].payload_sha256
        )

    def test_duplicate_artifact_hash_blocks_assembly_even_when_mapping_is_valid(self) -> None:
        artifacts = self.current_artifacts()
        artifacts[1] = RealLoopCurrentGateArtifact(
            gate=artifacts[1].gate,
            evidence_ref=artifacts[1].evidence_ref,
            artifact_sha256=artifacts[0].artifact_sha256,
            payload=artifacts[1].payload,
        )

        report = build_real_loop_current_manifest(artifacts)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            "evidence_hash_duplicate",
            {issue.code.value for issue in report.assembly.issues},
        )

    def test_invalid_identity_and_missing_gate_are_visible(self) -> None:
        artifacts = self.current_artifacts()[:-1]
        artifacts[0] = RealLoopCurrentGateArtifact(
            gate="b6_approved",
            evidence_ref="/unsafe/path.json",
            artifact_sha256="not-a-hash",
            payload=artifacts[0].payload,
        )

        report = build_real_loop_current_manifest(artifacts)
        codes = {issue.code for issue in report.issues}

        self.assertEqual("blocked", report.status)
        self.assertIn(RealLoopCurrentManifestIssueCode.REF_INVALID, codes)
        self.assertIn(RealLoopCurrentManifestIssueCode.HASH_INVALID, codes)
        self.assertIn(RealLoopCurrentManifestIssueCode.GATE_SET_MISMATCH, codes)

    def test_artifact_hash_requires_exact_lowercase_bytes(self) -> None:
        for malformed in ("A" * 64, "a" * 64 + " ", 123):
            artifacts = self.current_artifacts()
            artifacts[0] = RealLoopCurrentGateArtifact(
                gate=artifacts[0].gate,
                evidence_ref=artifacts[0].evidence_ref,
                artifact_sha256=malformed,
                payload=artifacts[0].payload,
            )

            report = build_real_loop_current_manifest(artifacts)

            self.assertEqual("blocked", report.status)
            self.assertIn(
                RealLoopCurrentManifestIssueCode.HASH_INVALID,
                {issue.code for issue in report.issues},
            )

    def test_unknown_runtime_verified_payload_does_not_unlock_manifest(self) -> None:
        artifacts = self.current_artifacts()
        artifacts[-1] = RealLoopCurrentGateArtifact(
            gate="runtime_identity_verified",
            evidence_ref="ref:runtime-generic",
            artifact_sha256="a" * 64,
            payload={"verified": True, "status": "verified"},
        )

        report = build_real_loop_current_manifest(artifacts)

        self.assertEqual("blocked", report.status)
        self.assertEqual("missing", report.rows[-1].status)
        self.assertFalse(report.gate_input.runtime_identity_verified)

    def test_manifest_rows_follow_canonical_gate_order(self) -> None:
        report = build_real_loop_current_manifest(reversed(self.current_artifacts()))

        self.assertEqual(REAL_LOOP_UPSTREAM_GATE_NAMES, tuple(row.gate for row in report.rows))


if __name__ == "__main__":
    unittest.main()
