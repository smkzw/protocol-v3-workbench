from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from services.api.app.monitoring_real_loop_evidence_semantics import (
    RealLoopEvidenceSemanticsError,
    RealLoopEvidenceSemanticsIssueCode,
    assess_real_loop_evidence_semantics,
)


class RealLoopEvidenceSemanticsTests(unittest.TestCase):
    WORKBENCH = Path(__file__).resolve().parents[1]
    MANIFEST = (
        WORKBENCH
        / "records/active_slices/medical_monitoring_real_loop_current_manifest_20260804/"
        "CURRENT_REAL_LOOP_GATE_MANIFEST.json"
    )

    def payload(self, relative: str) -> dict:
        return json.loads((self.WORKBENCH / relative).read_text(encoding="utf-8"))

    def test_current_sources_keep_freshness_decision_replay_and_signature_separate(self) -> None:
        cases = {
            "b6_approved": (
                self.payload(
                    "runs/execution/medical_monitoring_phase_b6_review_gate_20260801/"
                    "B6_REVIEW_OUTCOME_GATE.json"
                ),
                ("blocked", "not_observed", "pending", "incomplete"),
            ),
            "approved_input_ready": (
                self.payload(
                    "records/active_slices/medical_monitoring_approved_input_source_binding_20260803/"
                    "APPROVED_INPUT_SOURCE_BINDING.json"
                ),
                ("blocked", "blocked", "blocked", "incomplete"),
            ),
            "source_token_revalidated": (
                self.payload(
                    "records/active_slices/medical_monitoring_source_token_evidence_revalidation_20260803/"
                    "SOURCE_TOKEN_EVIDENCE_REVALIDATION.json"
                ),
                ("not_proven", "fresh_observed", "not_applicable", "not_proven"),
            ),
            "aggregate_cas_complete": (
                self.payload(
                    "records/active_slices/medical_monitoring_aggregate_cas_revalidation_20260803/"
                    "B4_AGGREGATE_CAS_REVALIDATION.json"
                ),
                ("blocked", "fresh_observed", "not_applicable", "incomplete"),
            ),
            "runtime_identity_verified": (None, ("missing", "missing", "missing", "missing")),
        }

        reports = {
            gate: assess_real_loop_evidence_semantics(gate, payload)
            for gate, (payload, _) in cases.items()
        }

        for gate, (_, expected) in cases.items():
            report = reports[gate]
            self.assertEqual(expected[0], report.derived_status, gate)
            self.assertEqual(expected[1], report.freshness_status, gate)
            self.assertEqual(expected[2], report.decision_status, gate)
            self.assertEqual(expected[3], report.replay_status, gate)
            self.assertEqual("not_verified", report.signature_status, gate)
            self.assertFalse(report.to_dict()["runtime_activation_permitted"])
            self.assertFalse(report.to_dict()["provider_call_permitted"])
            self.assertFalse(report.to_dict()["write_permitted"])

        self.assertIn(
            "formal reviewer decisions remain pending",
            reports["b6_approved"].interpretation,
        )
        self.assertIn(
            "source-token content proof is not proven",
            reports["source_token_revalidated"].interpretation,
        )
        self.assertIn(
            "aggregate/CAS replay remains incomplete",
            reports["aggregate_cas_complete"].interpretation,
        )

    def test_mapping_result_hash_is_bound_to_current_manifest(self) -> None:
        manifest = json.loads(self.MANIFEST.read_text(encoding="utf-8"))
        payload = self.payload(
            "records/active_slices/medical_monitoring_source_token_evidence_revalidation_20260803/"
            "SOURCE_TOKEN_EVIDENCE_REVALIDATION.json"
        )

        report = assess_real_loop_evidence_semantics(
            "source_token_revalidated",
            payload,
            payload_sha256=manifest["rows"][2]["payload_sha256"],
        )

        self.assertEqual(
            manifest["rows"][2]["mapping_result_sha256"],
            report.mapping_result_sha256,
        )

    def test_generic_signature_flag_is_not_accepted(self) -> None:
        payload = self.payload(
            "records/active_slices/medical_monitoring_source_token_evidence_revalidation_20260803/"
            "SOURCE_TOKEN_EVIDENCE_REVALIDATION.json"
        )
        payload["signature_verified"] = True

        report = assess_real_loop_evidence_semantics(
            "source_token_revalidated", payload
        )

        self.assertEqual("not_verified", report.signature_status)
        self.assertIn(
            RealLoopEvidenceSemanticsIssueCode.SIGNATURE_SCHEMA_UNSUPPORTED,
            {issue.code for issue in report.issues},
        )

    def test_malformed_payload_fails_closed(self) -> None:
        report = assess_real_loop_evidence_semantics(
            "aggregate_cas_complete", {"report": "not-an-object"}
        )

        self.assertEqual("missing", report.derived_status)
        self.assertEqual("missing", report.freshness_status)
        self.assertEqual("not_verified", report.signature_status)
        self.assertIn(
            RealLoopEvidenceSemanticsIssueCode.STATUS_MAPPING_ISSUE,
            {issue.code for issue in report.issues},
        )

    def test_semantics_are_deterministic_and_signature_cannot_be_promoted(self) -> None:
        payload = self.payload(
            "runs/execution/medical_monitoring_phase_b6_review_gate_20260801/"
            "B6_REVIEW_OUTCOME_GATE.json"
        )
        first = assess_real_loop_evidence_semantics("b6_approved", payload)
        second = assess_real_loop_evidence_semantics("b6_approved", deepcopy(payload))

        self.assertEqual(first.semantic_sha256, second.semantic_sha256)
        with self.assertRaises(RealLoopEvidenceSemanticsError):
            type(first)(
                gate=first.gate,
                evidence_kind=first.evidence_kind,
                derived_status=first.derived_status,
                freshness_status=first.freshness_status,
                decision_status=first.decision_status,
                replay_status=first.replay_status,
                signature_status="verified",
                interpretation=first.interpretation,
                mapping_result_sha256=first.mapping_result_sha256,
            )


if __name__ == "__main__":
    unittest.main()
