from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from services.api.app.monitoring_real_loop_manifest_replay import (
    RealLoopManifestReplayArtifact,
    RealLoopManifestReplayIssueCode,
    replay_real_loop_current_manifest,
)


class RealLoopManifestReplayTests(unittest.TestCase):
    WORKBENCH = Path(__file__).resolve().parents[1]
    MANIFEST = (
        WORKBENCH
        / "records/active_slices/medical_monitoring_real_loop_current_manifest_20260804/"
        "CURRENT_REAL_LOOP_GATE_MANIFEST.json"
    )

    def load_artifact(self, gate: str, relative: str, ref: str) -> RealLoopManifestReplayArtifact:
        path = self.WORKBENCH / relative
        return RealLoopManifestReplayArtifact(
            gate=gate,
            evidence_ref=ref,
            artifact_bytes=path.read_bytes(),
            payload=json.loads(path.read_text(encoding="utf-8")),
        )

    def current_artifacts(self) -> list[RealLoopManifestReplayArtifact]:
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
            RealLoopManifestReplayArtifact(
                gate="runtime_identity_verified",
                allow_missing=True,
            ),
        ]

    def test_current_manifest_replays_exactly_without_authority(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))

        first = replay_real_loop_current_manifest(manifest, self.current_artifacts())
        second = replay_real_loop_current_manifest(manifest, self.current_artifacts())

        self.assertEqual("matched", first.status)
        self.assertEqual((), first.issues)
        self.assertEqual(first.report_sha256, second.report_sha256)
        self.assertEqual(manifest["report_sha256"], first.expected_manifest_report_sha256)
        self.assertFalse(first.to_dict()["runtime_activation_permitted"])
        self.assertFalse(first.to_dict()["provider_call_permitted"])
        self.assertFalse(first.to_dict()["write_permitted"])

    def test_source_bytes_mutation_fails_closed(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        artifacts = self.current_artifacts()
        original = artifacts[0]
        artifacts[0] = RealLoopManifestReplayArtifact(
            gate=original.gate,
            evidence_ref=original.evidence_ref,
            artifact_bytes=original.artifact_bytes + b"\n",
            payload=original.payload,
        )

        report = replay_real_loop_current_manifest(manifest, artifacts)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopManifestReplayIssueCode.ARTIFACT_HASH_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_payload_mutation_fails_closed(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        artifacts = self.current_artifacts()
        original = artifacts[0]
        changed = deepcopy(original.payload)
        changed["gate"]["pending_candidate_record_ids"] = ["mutated"]
        artifacts[0] = RealLoopManifestReplayArtifact(
            gate=original.gate,
            evidence_ref=original.evidence_ref,
            artifact_bytes=original.artifact_bytes,
            payload=changed,
        )

        report = replay_real_loop_current_manifest(manifest, artifacts)

        self.assertEqual("blocked", report.status)
        codes = {issue.code for issue in report.issues}
        self.assertIn(RealLoopManifestReplayIssueCode.PAYLOAD_HASH_MISMATCH, codes)
        self.assertIn(RealLoopManifestReplayIssueCode.MAPPING_RESULT_HASH_MISMATCH, codes)

    def test_persisted_report_hash_mutation_fails_closed(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        manifest["report_sha256"] = "0" * 64

        report = replay_real_loop_current_manifest(manifest, self.current_artifacts())

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopManifestReplayIssueCode.MANIFEST_REPORT_HASH_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_persisted_row_hash_mutation_fails_closed(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        manifest["rows"][0]["mapping_result_sha256"] = "f" * 64

        report = replay_real_loop_current_manifest(manifest, self.current_artifacts())

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopManifestReplayIssueCode.MAPPING_RESULT_HASH_MISMATCH,
            {issue.code for issue in report.issues},
        )

    def test_required_source_bytes_missing_fails_closed(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        artifacts = self.current_artifacts()
        original = artifacts[0]
        artifacts[0] = RealLoopManifestReplayArtifact(
            gate=original.gate,
            evidence_ref=original.evidence_ref,
            payload=original.payload,
        )

        report = replay_real_loop_current_manifest(manifest, artifacts)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopManifestReplayIssueCode.ARTIFACT_BYTES_MISSING,
            {issue.code for issue in report.issues},
        )

    def test_missing_runtime_row_is_allowed_only_when_explicit(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        artifacts = self.current_artifacts()
        artifacts[-1] = RealLoopManifestReplayArtifact(
            gate="runtime_identity_verified",
            allow_missing=False,
        )

        report = replay_real_loop_current_manifest(manifest, artifacts)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopManifestReplayIssueCode.ARTIFACT_BYTES_MISSING,
            {issue.code for issue in report.issues},
        )

    def test_invalid_manifest_shape_fails_closed(self) -> None:
        report = replay_real_loop_current_manifest(None, self.current_artifacts())

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopManifestReplayIssueCode.MANIFEST_SHAPE_INVALID,
            {issue.code for issue in report.issues},
        )


if __name__ == "__main__":
    unittest.main()
