from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest

from services.api.app.monitoring_real_loop_readiness import REAL_LOOP_UPSTREAM_GATE_NAMES
from services.api.app.monitoring_real_loop_status_mapping import (
    RealLoopStatusMappingError,
    RealLoopStatusMappingIssueCode,
    derive_real_loop_upstream_status,
)


class RealLoopStatusMappingTests(unittest.TestCase):
    WORKBENCH = Path(__file__).resolve().parents[1]

    def load(self, relative: str) -> dict:
        return json.loads((self.WORKBENCH / relative).read_text(encoding="utf-8"))

    @staticmethod
    def payload_hash(payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()

    @staticmethod
    def b6_payload(status: str = "pending_review") -> dict:
        return {
            "read_only": True,
            "write_permitted": False,
            "migration_write_permitted": False,
            "gate": {
                "status": status,
                "migration_ready": status == "approved",
                "write_permitted": False,
                "candidate_count": 2,
                "outcome_count": 2,
                "missing_candidate_record_ids": [],
                "rejected_candidate_record_ids": [],
                "pending_candidate_record_ids": [],
                "unresolved_blockers": [],
                "accepted_review_ids": ["review-1", "review-2"]
                if status == "approved"
                else [],
            },
        }

    @staticmethod
    def base_approved_input_report() -> dict:
        return {
            "status": "ready",
            "approved_input_ready": True,
            "source_manifest_replay_complete": True,
            "reviewer_outcomes_complete": True,
            "source_lineage_complete": True,
            "aggregate_cas_complete": True,
            "residual_blockers_clear": True,
            "write_permitted": False,
            "migration_ready": False,
            "issues": [],
        }

    @staticmethod
    def source_token_report() -> dict:
        return {
            "status": "fresh",
            "evidence_fresh": True,
            "source_token_revalidation_status": "proven",
            "source_token_synthesized": False,
            "issue_count": 0,
            "issues": [],
            "read_only": True,
            "authority_granted": False,
            "medical_authority_granted": False,
            "migration_ready": False,
            "provider_permitted": False,
            "runtime_write_permitted": False,
            "release_ready": False,
            "write_permitted": False,
        }

    @staticmethod
    def aggregate_cas_report() -> dict:
        return {
            "status": "fresh",
            "evidence_fresh": True,
            "artifact_payload_valid": True,
            "source_payload_valid": True,
            "replay_report_matches": True,
            "metadata_chain_complete": True,
            "cas_replay_complete": True,
            "issue_count": 0,
            "replay_issue_count": 0,
            "issues": [],
            "read_only": True,
            "authority_granted": False,
            "medical_authority_granted": False,
            "migration_ready": False,
            "aggregate_write_permitted": False,
            "runtime_write_permitted": False,
            "release_ready": False,
        }

    def test_current_filesystem_payloads_remain_non_proven(self) -> None:
        b6 = self.load(
            "runs/execution/medical_monitoring_phase_b6_review_gate_20260801/"
            "B6_REVIEW_OUTCOME_GATE.json"
        )
        approved = self.load(
            "records/active_slices/medical_monitoring_approved_input_source_binding_20260803/"
            "APPROVED_INPUT_SOURCE_BINDING.json"
        )
        source_token = self.load(
            "records/active_slices/medical_monitoring_source_token_evidence_revalidation_20260803/"
            "SOURCE_TOKEN_EVIDENCE_REVALIDATION.json"
        )
        cas = self.load(
            "records/active_slices/medical_monitoring_aggregate_cas_revalidation_20260803/"
            "B4_AGGREGATE_CAS_REVALIDATION.json"
        )

        self.assertEqual("blocked", derive_real_loop_upstream_status("b6_approved", b6).status)
        self.assertEqual(
            "blocked", derive_real_loop_upstream_status("approved_input_ready", approved).status
        )
        self.assertEqual(
            "not_proven",
            derive_real_loop_upstream_status("source_token_revalidated", source_token).status,
        )
        self.assertEqual(
            "blocked", derive_real_loop_upstream_status("aggregate_cas_complete", cas).status
        )
        self.assertEqual(
            "missing",
            derive_real_loop_upstream_status("runtime_identity_verified", None).status,
        )

    def test_b6_requires_full_candidate_approval_to_be_proven(self) -> None:
        result = derive_real_loop_upstream_status("b6_approved", self.b6_payload("approved"))

        self.assertEqual("proven", result.status)
        self.assertEqual((), result.issues)
        self.assertEqual(64, len(result.result_sha256))

        pending = derive_real_loop_upstream_status("b6_approved", self.b6_payload())
        self.assertEqual("blocked", pending.status)

    def test_b6_malformed_or_authority_true_is_missing(self) -> None:
        malformed = self.b6_payload("approved")
        malformed["gate"]["candidate_count"] = "2"
        result = derive_real_loop_upstream_status("b6_approved", malformed)
        self.assertEqual("missing", result.status)
        self.assertIn(
            RealLoopStatusMappingIssueCode.FIELD_TYPE_INVALID,
            {issue.code for issue in result.issues},
        )

        authority = self.b6_payload("approved")
        authority["write_permitted"] = True
        authority_result = derive_real_loop_upstream_status("b6_approved", authority)
        self.assertEqual("missing", authority_result.status)

    def test_approved_input_supports_base_and_controlled_shapes(self) -> None:
        base = self.base_approved_input_report()
        self.assertEqual(
            "proven", derive_real_loop_upstream_status("approved_input_ready", base).status
        )
        controlled = {
            "status": "ready",
            "approved_input_ready": True,
            "source_batch_preflight_complete": True,
            "source_batch_binding_sha256": "a" * 64,
            "issues": [],
            "write_permitted": False,
            "migration_ready": False,
            "base_report": base,
        }
        self.assertEqual(
            "proven",
            derive_real_loop_upstream_status("approved_input_ready", controlled).status,
        )
        blocked = deepcopy(base)
        blocked["approved_input_ready"] = False
        self.assertEqual(
            "blocked",
            derive_real_loop_upstream_status("approved_input_ready", blocked).status,
        )

    def test_source_token_requires_content_proof_not_freshness_alone(self) -> None:
        proven = derive_real_loop_upstream_status(
            "source_token_revalidated", {"report": self.source_token_report()}
        )
        self.assertEqual("proven", proven.status)

        unresolved = self.source_token_report()
        unresolved["source_token_revalidation_status"] = "not_proven"
        unresolved_result = derive_real_loop_upstream_status(
            "source_token_revalidated", {"report": unresolved}
        )
        self.assertEqual("not_proven", unresolved_result.status)

        authority = self.source_token_report()
        authority["release_ready"] = True
        authority_result = derive_real_loop_upstream_status(
            "source_token_revalidated", {"report": authority}
        )
        self.assertEqual("missing", authority_result.status)

    def test_aggregate_cas_requires_complete_replay_and_no_authority(self) -> None:
        proven = derive_real_loop_upstream_status(
            "aggregate_cas_complete", {"report": self.aggregate_cas_report()}
        )
        self.assertEqual("proven", proven.status)

        blocked = self.aggregate_cas_report()
        blocked["cas_replay_complete"] = False
        blocked_result = derive_real_loop_upstream_status(
            "aggregate_cas_complete", {"report": blocked}
        )
        self.assertEqual("blocked", blocked_result.status)

    def test_runtime_identity_never_accepts_generic_verified_boolean(self) -> None:
        result = derive_real_loop_upstream_status(
            "runtime_identity_verified", {"verified": True, "status": "verified"}
        )

        self.assertEqual("missing", result.status)
        self.assertIn(
            RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
            {issue.code for issue in result.issues},
        )

    def test_unknown_or_malformed_payload_is_missing_without_type_error(self) -> None:
        for gate in REAL_LOOP_UPSTREAM_GATE_NAMES:
            result = derive_real_loop_upstream_status(gate, {"status": []})
            self.assertEqual("missing", result.status)
            self.assertTrue(result.issues)

    def test_hash_argument_is_strict_and_gate_is_canonical(self) -> None:
        with self.assertRaisesRegex(RealLoopStatusMappingError, "SHA-256"):
            derive_real_loop_upstream_status(
                "b6_approved", self.b6_payload(), payload_sha256="A" * 64
            )
        with self.assertRaisesRegex(RealLoopStatusMappingError, "canonical"):
            derive_real_loop_upstream_status("other", {})


if __name__ == "__main__":
    unittest.main()
