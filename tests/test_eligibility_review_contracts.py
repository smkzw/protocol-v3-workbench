from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    EligibilityCriterionKind,
    EligibilityEvidenceProcessingState,
    EligibilityExclusionDecision,
    EligibilityInclusionDecision,
    EligibilityReviewAction,
    EligibilityReviewActionRequest,
    EligibilityReviewActionResult,
    EligibilityReviewState,
    EligibilitySubjectAggregate,
    EligibilitySubjectAggregateStatus,
)


class EligibilityReviewContractTests(unittest.TestCase):
    def request_payload(self, **updates):
        payload = {
            "criterion_kind": "inclusion",
            "expected_state_revision": 0,
            "expected_rule_revision": "eligrulev_001",
            "expected_subject_source_revision": "eligsubsrcv_001",
            "idempotency_key": "review-key-001",
            "actor": "medical_manager",
            "action": "revise_decision",
            "decision": "met",
            "reason": "Current versioned evidence supports this review.",
            "evidence_ids": ["evidence-001"],
            "evidence_processing_state": "completed",
        }
        payload.update(updates)
        return payload

    def state_payload(self, **updates):
        payload = {
            "project_id": "project-d001",
            "subject_id": "subject-sa07005",
            "criterion_uid": "criterion-in-01",
            "criterion_kind": "inclusion",
            "rule_revision": "eligrulev_001",
            "subject_source_revision": "eligsubsrcv_001",
            "state_revision": 2,
            "evidence_processing_state": "completed",
            "ai_draft_decision": "met",
            "medical_decision": "not_met",
            "latest_action": "revise_decision",
            "reason": "Medical review revised the AI draft.",
            "evidence_ids": ["evidence-001"],
            "ai_draft_record_id": "record-ai-001",
            "medical_record_id": "record-medical-001",
            "latest_record_id": "record-medical-001",
            "updated_at": datetime(2026, 7, 11, tzinfo=timezone.utc),
        }
        payload.update(updates)
        return payload

    def test_request_forbids_extra_fields_and_requires_cas_identity(self):
        request = EligibilityReviewActionRequest.model_validate(
            self.request_payload()
        )
        self.assertEqual(0, request.expected_state_revision)
        self.assertEqual("eligrulev_001", request.expected_rule_revision)
        self.assertEqual(
            "eligsubsrcv_001",
            request.expected_subject_source_revision,
        )
        self.assertEqual("review-key-001", request.idempotency_key)

        with self.assertRaises(ValidationError):
            EligibilityReviewActionRequest.model_validate(
                self.request_payload(project_id="body-project-not-allowed")
            )
        with self.assertRaises(ValidationError):
            EligibilityReviewActionRequest.model_validate(
                self.request_payload(expected_state_revision=-1)
            )
        with self.assertRaises(ValidationError):
            EligibilityReviewActionRequest.model_validate(
                self.request_payload(idempotency_key="   ")
            )

    def test_inclusion_and_exclusion_decisions_use_separate_enums(self):
        inclusion = EligibilityReviewActionRequest.model_validate(
            self.request_payload(decision="met")
        )
        exclusion = EligibilityReviewActionRequest.model_validate(
            self.request_payload(
                criterion_kind="exclusion",
                decision="absent",
            )
        )

        self.assertIsInstance(
            inclusion.decision,
            EligibilityInclusionDecision,
        )
        self.assertIsInstance(
            exclusion.decision,
            EligibilityExclusionDecision,
        )
        self.assertEqual(EligibilityCriterionKind.INCLUSION, inclusion.criterion_kind)
        self.assertEqual(EligibilityCriterionKind.EXCLUSION, exclusion.criterion_kind)

    def test_inclusion_and_exclusion_enum_boundaries_fail_closed(self):
        for invalid_decision in ("absent", "present"):
            with self.subTest(kind="inclusion", decision=invalid_decision):
                with self.assertRaises(ValidationError):
                    EligibilityReviewActionRequest.model_validate(
                        self.request_payload(decision=invalid_decision)
                    )

        for invalid_decision in ("met", "not_met"):
            with self.subTest(kind="exclusion", decision=invalid_decision):
                with self.assertRaises(ValidationError):
                    EligibilityReviewActionRequest.model_validate(
                        self.request_payload(
                            criterion_kind="exclusion",
                            decision=invalid_decision,
                        )
                    )

    def test_shared_decision_values_are_typed_by_criterion_kind(self):
        inclusion = EligibilityReviewActionRequest.model_validate(
            self.request_payload(decision="insufficient_evidence")
        )
        exclusion = EligibilityReviewActionRequest.model_validate(
            self.request_payload(
                criterion_kind="exclusion",
                decision="insufficient_evidence",
            )
        )

        self.assertIsInstance(inclusion.decision, EligibilityInclusionDecision)
        self.assertIsInstance(exclusion.decision, EligibilityExclusionDecision)

    def test_action_payload_and_evidence_processing_state_are_strict(self):
        with self.assertRaisesRegex(ValidationError, "requires a decision"):
            EligibilityReviewActionRequest.model_validate(
                self.request_payload(decision=None)
            )
        with self.assertRaisesRegex(ValidationError, "cannot carry a decision"):
            EligibilityReviewActionRequest.model_validate(
                self.request_payload(action="request_evidence")
            )
        compatibility_request = EligibilityReviewActionRequest.model_validate(
            self.request_payload(
                decision="insufficient_evidence",
                evidence_processing_state="partial",
            )
        )
        self.assertEqual(
            EligibilityEvidenceProcessingState.PARTIAL,
            compatibility_request.evidence_processing_state,
        )

        request = EligibilityReviewActionRequest.model_validate(
            self.request_payload(
                action="request_evidence",
                decision=None,
                evidence_processing_state="running",
            )
        )
        self.assertEqual(
            EligibilityEvidenceProcessingState.RUNNING,
            request.evidence_processing_state,
        )

        with self.assertRaisesRegex(ValidationError, "requires evidence_ids"):
            EligibilityReviewActionRequest.model_validate(
                self.request_payload(evidence_ids=[])
            )
        with self.assertRaisesRegex(ValidationError, "requires evidence_ids"):
            EligibilityReviewActionRequest.model_validate(
                self.request_payload(
                    action="accept_ai_draft",
                    decision=None,
                    evidence_ids=[],
                )
            )

    def test_response_keeps_ai_draft_and_medical_decision_separate(self):
        state = EligibilityReviewState.model_validate(self.state_payload())
        result = EligibilityReviewActionResult(
            request_id="request-001",
            record_id="record-medical-001",
            state_revision=2,
            replayed=False,
            state=state,
        )

        self.assertEqual(EligibilityInclusionDecision.MET, state.ai_draft_decision)
        self.assertEqual(
            EligibilityInclusionDecision.NOT_MET,
            state.medical_decision,
        )
        self.assertEqual(2, result.state_revision)

        with self.assertRaises(ValidationError):
            EligibilityReviewState.model_validate(
                self.state_payload(ai_draft_decision="present")
            )
        with self.assertRaises(ValidationError):
            EligibilityReviewState.model_validate(
                self.state_payload(unexpected="not allowed")
            )

    def test_aggregate_allows_only_non_formal_review_statuses(self):
        aggregate = EligibilitySubjectAggregate(
            project_id="project-d001",
            subject_id="subject-sa07005",
            rule_revision="eligrulev_001",
            criterion_count=36,
            reviewed_count=36,
            statuses=[EligibilitySubjectAggregateStatus.MEDICAL_REVIEW_PENDING],
        )
        self.assertEqual(
            [EligibilitySubjectAggregateStatus.MEDICAL_REVIEW_PENDING],
            aggregate.statuses,
        )

        for forbidden_status in (
            "eligible",
            "not_eligible",
            "randomization_release",
            "ready_for_randomization",
        ):
            with self.subTest(status=forbidden_status):
                with self.assertRaises(ValidationError):
                    EligibilitySubjectAggregate(
                        project_id="project-d001",
                        subject_id="subject-sa07005",
                        rule_revision="eligrulev_001",
                        criterion_count=36,
                        reviewed_count=36,
                        statuses=[forbidden_status],
                    )

    def test_new_contract_schemas_do_not_publish_formal_release_values(self):
        schemas = json.dumps(
            {
                "request": EligibilityReviewActionRequest.model_json_schema(),
                "result": EligibilityReviewActionResult.model_json_schema(),
                "aggregate": EligibilitySubjectAggregate.model_json_schema(),
            },
            sort_keys=True,
        )
        for forbidden_literal in (
            '"eligible"',
            '"not_eligible"',
            '"randomization_release"',
            '"ready_for_randomization"',
        ):
            self.assertNotIn(forbidden_literal, schemas)


if __name__ == "__main__":
    unittest.main()
