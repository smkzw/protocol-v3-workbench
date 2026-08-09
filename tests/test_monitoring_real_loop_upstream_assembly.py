from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from services.api.app.monitoring_real_loop_readiness import REAL_LOOP_UPSTREAM_GATE_NAMES
from services.api.app.monitoring_real_loop_upstream_assembly import (
    REAL_LOOP_UPSTREAM_EVIDENCE_KINDS,
    RealLoopUpstreamAssemblyError,
    RealLoopUpstreamAssemblyIssueCode,
    RealLoopUpstreamEvidence,
    assess_real_loop_upstream_assembly,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def complete_rows(
    statuses: dict[str, str] | None = None,
) -> list[RealLoopUpstreamEvidence]:
    statuses = statuses or {}
    return [
        RealLoopUpstreamEvidence(
            gate=gate,
            evidence_kind=REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate],
            evidence_ref=f"ref:{gate.replace('_', '-')}",
            evidence_sha256=digest(f"evidence:{gate}"),
            status=statuses.get(gate, "proven"),
        )
        for gate in REAL_LOOP_UPSTREAM_GATE_NAMES
    ]


class RealLoopUpstreamAssemblyTests(unittest.TestCase):
    WORKBENCH = Path(__file__).resolve().parents[1]

    def test_all_explicitly_proven_rows_assemble_true_booleans(self) -> None:
        report = assess_real_loop_upstream_assembly(complete_rows())

        self.assertEqual("assembled", report.status)
        self.assertEqual((), report.issues)
        self.assertEqual(5, len(report.evidence_rows))
        self.assertTrue(report.gate_input.b6_approved)
        self.assertTrue(report.gate_input.approved_input_ready)
        self.assertTrue(report.gate_input.source_token_revalidated)
        self.assertTrue(report.gate_input.aggregate_cas_complete)
        self.assertTrue(report.gate_input.runtime_identity_verified)
        self.assertFalse(report.to_dict()["write_permitted"])
        self.assertEqual(64, len(report.report_sha256))

    def test_non_proven_statuses_never_coerce_to_true(self) -> None:
        report = assess_real_loop_upstream_assembly(
            complete_rows(
                {
                    "b6_approved": "blocked",
                    "approved_input_ready": "fresh",
                    "source_token_revalidated": "not_proven",
                    "aggregate_cas_complete": "missing",
                    "runtime_identity_verified": "fresh",
                }
            )
        )

        self.assertEqual("assembled", report.status)
        self.assertEqual((), report.issues)
        self.assertFalse(report.gate_input.b6_approved)
        self.assertFalse(report.gate_input.approved_input_ready)
        self.assertFalse(report.gate_input.source_token_revalidated)
        self.assertFalse(report.gate_input.aggregate_cas_complete)
        self.assertFalse(report.gate_input.runtime_identity_verified)
        self.assertEqual(5, len(report.evidence_rows))

    def test_missing_status_may_preserve_an_empty_observation(self) -> None:
        rows = complete_rows({"runtime_identity_verified": "missing"})
        rows[-1] = RealLoopUpstreamEvidence(
            gate=rows[-1].gate,
            evidence_kind=rows[-1].evidence_kind,
            status="missing",
        )

        report = assess_real_loop_upstream_assembly(rows)

        self.assertEqual("assembled", report.status)
        self.assertEqual((), report.issues)
        self.assertFalse(report.gate_input.runtime_identity_verified)
        self.assertEqual("", report.gate_input.runtime_identity_evidence_ref)
        self.assertEqual("", report.gate_input.runtime_identity_evidence_sha256)

    def test_mapping_rows_are_supported_without_string_coercion(self) -> None:
        rows = [row.to_dict() for row in complete_rows()]
        report = assess_real_loop_upstream_assembly(rows)

        self.assertEqual("assembled", report.status)
        self.assertEqual((), report.issues)

    def test_missing_gate_fails_closed(self) -> None:
        rows = complete_rows()[:-1]

        report = assess_real_loop_upstream_assembly(rows)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopUpstreamAssemblyIssueCode.GATE_SET_MISMATCH,
            {issue.code for issue in report.issues},
        )
        self.assertFalse(report.gate_input.runtime_identity_verified)
        self.assertEqual("", report.gate_input.runtime_identity_evidence_ref)

    def test_duplicate_gate_invalidates_that_gate(self) -> None:
        rows = complete_rows()
        rows.append(rows[0])

        report = assess_real_loop_upstream_assembly(rows)

        self.assertEqual("blocked", report.status)
        self.assertIn(
            RealLoopUpstreamAssemblyIssueCode.GATE_DUPLICATE,
            {issue.code for issue in report.issues},
        )
        self.assertFalse(report.gate_input.b6_approved)
        self.assertEqual("", report.gate_input.b6_evidence_ref)

    def test_reused_ref_or_hash_invalidates_both_owners(self) -> None:
        rows = complete_rows()
        rows[1] = RealLoopUpstreamEvidence(
            gate=rows[1].gate,
            evidence_kind=rows[1].evidence_kind,
            evidence_ref=rows[0].evidence_ref,
            evidence_sha256=rows[0].evidence_sha256,
            status="proven",
        )

        report = assess_real_loop_upstream_assembly(rows)
        codes = {issue.code for issue in report.issues}

        self.assertEqual("blocked", report.status)
        self.assertIn(RealLoopUpstreamAssemblyIssueCode.EVIDENCE_REF_DUPLICATE, codes)
        self.assertIn(RealLoopUpstreamAssemblyIssueCode.EVIDENCE_HASH_DUPLICATE, codes)
        self.assertFalse(report.gate_input.b6_approved)
        self.assertFalse(report.gate_input.approved_input_ready)
        self.assertEqual("", report.gate_input.b6_evidence_ref)
        self.assertEqual("", report.gate_input.approved_input_evidence_ref)

    def test_wrong_kind_invalid_ref_hash_and_status_fail_closed(self) -> None:
        rows = complete_rows()
        rows[0] = RealLoopUpstreamEvidence(
            gate="b6_approved",
            evidence_kind="aggregate_cas_revalidation",
            evidence_ref="/unsafe/path.json",
            evidence_sha256="NOT-A-HASH",
            status="yes",
        )

        report = assess_real_loop_upstream_assembly(rows)
        codes = {issue.code for issue in report.issues}

        self.assertEqual("blocked", report.status)
        self.assertIn(RealLoopUpstreamAssemblyIssueCode.EVIDENCE_KIND_MISMATCH, codes)
        self.assertIn(RealLoopUpstreamAssemblyIssueCode.EVIDENCE_REF_INVALID, codes)
        self.assertIn(RealLoopUpstreamAssemblyIssueCode.EVIDENCE_HASH_INVALID, codes)
        self.assertIn(RealLoopUpstreamAssemblyIssueCode.EVIDENCE_STATUS_INVALID, codes)
        self.assertFalse(report.gate_input.b6_approved)
        self.assertEqual("", report.gate_input.b6_evidence_ref)

    def test_uppercase_hash_is_not_normalized_into_valid_evidence(self) -> None:
        row = complete_rows()[0]
        rows = complete_rows()
        rows[0] = RealLoopUpstreamEvidence(
            gate=row.gate,
            evidence_kind=row.evidence_kind,
            evidence_ref=row.evidence_ref,
            evidence_sha256=row.evidence_sha256.upper(),
            status="proven",
        )

        report = assess_real_loop_upstream_assembly(rows)

        self.assertIn(
            RealLoopUpstreamAssemblyIssueCode.EVIDENCE_HASH_INVALID,
            {issue.code for issue in report.issues},
        )
        self.assertFalse(report.gate_input.b6_approved)

    def test_padded_and_non_string_hashes_are_not_normalized(self) -> None:
        cases = (
            (complete_rows()[0].evidence_sha256 + " ",
             RealLoopUpstreamAssemblyIssueCode.EVIDENCE_HASH_INVALID),
            (123, RealLoopUpstreamAssemblyIssueCode.FIELD_INVALID),
        )
        for malformed, expected_code in cases:
            rows = complete_rows()
            row = rows[0]
            rows[0] = RealLoopUpstreamEvidence(
                gate=row.gate,
                evidence_kind=row.evidence_kind,
                evidence_ref=row.evidence_ref,
                evidence_sha256=malformed,
                status="proven",
            )

            report = assess_real_loop_upstream_assembly(rows)

            codes = {issue.code for issue in report.issues}
            self.assertIn(expected_code, codes)
            self.assertFalse(report.gate_input.b6_approved)

    def test_proven_without_a_pair_is_never_true(self) -> None:
        rows = complete_rows()
        rows[0] = RealLoopUpstreamEvidence(
            gate=rows[0].gate,
            evidence_kind=rows[0].evidence_kind,
            status="proven",
        )

        report = assess_real_loop_upstream_assembly(rows)

        self.assertIn(
            RealLoopUpstreamAssemblyIssueCode.EVIDENCE_PAIR_INCOMPLETE,
            {issue.code for issue in report.issues},
        )
        self.assertFalse(report.gate_input.b6_approved)

    def test_report_rejects_inconsistent_status(self) -> None:
        report = assess_real_loop_upstream_assembly(complete_rows())

        with self.assertRaisesRegex(RealLoopUpstreamAssemblyError, "status"):
            type(report)(
                status="blocked",
                gate_input=report.gate_input,
                evidence_rows=report.evidence_rows,
                issues=(),
            )

    def test_current_gate_artifacts_assemble_without_unlocking_any_gate(self) -> None:
        def load(relative: str) -> tuple[dict, str]:
            path = self.WORKBENCH / relative
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload, hashlib.sha256(path.read_bytes()).hexdigest()

        b6, b6_hash = load(
            "runs/execution/medical_monitoring_phase_b6_review_gate_20260801/"
            "B6_REVIEW_OUTCOME_GATE.json"
        )
        approved, approved_hash = load(
            "records/active_slices/medical_monitoring_approved_input_source_binding_20260803/"
            "APPROVED_INPUT_SOURCE_BINDING.json"
        )
        source_token, source_token_hash = load(
            "records/active_slices/medical_monitoring_source_token_evidence_revalidation_20260803/"
            "SOURCE_TOKEN_EVIDENCE_REVALIDATION.json"
        )
        cas, cas_hash = load(
            "records/active_slices/medical_monitoring_aggregate_cas_revalidation_20260803/"
            "B4_AGGREGATE_CAS_REVALIDATION.json"
        )
        rows = [
            RealLoopUpstreamEvidence(
                "b6_approved",
                REAL_LOOP_UPSTREAM_EVIDENCE_KINDS["b6_approved"],
                "ref:fs:b6-review-gate",
                b6_hash,
                "blocked" if b6["gate"]["status"] == "pending_review" else "proven",
            ),
            RealLoopUpstreamEvidence(
                "approved_input_ready",
                REAL_LOOP_UPSTREAM_EVIDENCE_KINDS["approved_input_ready"],
                "ref:fs:approved-input-binding",
                approved_hash,
                "proven"
                if approved["current_package_observation"]["approved_input_ready"]
                else "blocked",
            ),
            RealLoopUpstreamEvidence(
                "source_token_revalidated",
                REAL_LOOP_UPSTREAM_EVIDENCE_KINDS["source_token_revalidated"],
                "ref:fs:source-token-revalidation",
                source_token_hash,
                source_token["report"]["source_token_revalidation_status"],
            ),
            RealLoopUpstreamEvidence(
                "aggregate_cas_complete",
                REAL_LOOP_UPSTREAM_EVIDENCE_KINDS["aggregate_cas_complete"],
                "ref:fs:aggregate-cas-revalidation",
                cas_hash,
                "proven" if cas["report"]["cas_replay_complete"] else "blocked",
            ),
            RealLoopUpstreamEvidence(
                "runtime_identity_verified",
                REAL_LOOP_UPSTREAM_EVIDENCE_KINDS["runtime_identity_verified"],
                status="missing",
            ),
        ]

        report = assess_real_loop_upstream_assembly(rows)

        self.assertEqual("assembled", report.status)
        self.assertEqual((), report.issues)
        self.assertFalse(report.gate_input.b6_approved)
        self.assertFalse(report.gate_input.approved_input_ready)
        self.assertFalse(report.gate_input.source_token_revalidated)
        self.assertFalse(report.gate_input.aggregate_cas_complete)
        self.assertFalse(report.gate_input.runtime_identity_verified)
        self.assertEqual(5, len(report.evidence_rows))


if __name__ == "__main__":
    unittest.main()
