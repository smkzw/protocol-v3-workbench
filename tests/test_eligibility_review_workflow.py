from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.eligibility_review_workflow import (  # noqa: E402
    CriterionKind,
    EligibilityDecision,
    EligibilityReviewAction,
    EligibilityReviewRequest,
    EligibilityReviewWorkflow,
    EvidenceProcessingState,
    eligibility_subject_source_revision,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore  # noqa: E402


PROJECT_ID = "proj_d001"
SUBJECT_ID = "SA07005"
RULE_REVISION = "rule-rev-1"


class EligibilityReviewWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = SqliteRuntimeStore(Path(self.tmp.name) / "runtime.sqlite3")
        self.workflow = EligibilityReviewWorkflow(self.store)
        self.subject_source_revision = self.workflow.register_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            [
                {
                    "source_id": "source-1",
                    "source_revision": "source-rev-1",
                    "content_hash": "source-hash-1",
                    "size_bytes": 100,
                    "media_class": "text_document_image",
                }
            ],
        )
        self.workflow.register_rule_revision(
            PROJECT_ID,
            RULE_REVISION,
            [
                {
                    "criterion_uid": "in-01",
                    "criterion_kind": "inclusion",
                    "source_rule_label": "IN-01",
                    "source_locator": {"paragraph": 10},
                    "normalized_text_hash": "in-rule-hash",
                    "display_order": 1,
                },
                {
                    "criterion_uid": "ex-01",
                    "criterion_kind": "exclusion",
                    "source_rule_label": "EX-01",
                    "source_locator": {"paragraph": 20},
                    "normalized_text_hash": "ex-rule-hash",
                    "display_order": 2,
                },
            ],
        )
        self.workflow.register_evidence_span(
            evidence_id="evidence-1",
            project_id=PROJECT_ID,
            subject_id=SUBJECT_ID,
            source_id="source-1",
            source_revision="source-rev-1",
            extraction_revision="extract-rev-1",
            locator={"page": 1, "region": [1, 2, 3, 4]},
            media_class="text_document_image",
            processing_state=EvidenceProcessingState.COMPLETED,
            quality_state="sampled_pass",
            extraction_confidence=0.9,
            medical_verification_status="not_reviewed",
        )
        self.store.commit_eligibility_evidence_visual_qc(
            project_id=PROJECT_ID,
            subject_id=SUBJECT_ID,
            evidence_id="evidence-1",
            expected_qc_revision=0,
            expected_source_revision="source-rev-1",
            expected_extraction_revision="extract-rev-1",
            idempotency_key="workflow-fixture-qc-pass",
            result="sampled_pass",
            reason_code="fixture_visual_comparison",
            user_reason="Fixture page and extracted region were compared.",
            sample_plan_id="fixture-full-page-v1",
            sample_unit={"page": 1, "region": [1, 2, 3, 4]},
            policy_version="visual-qc-policy-v1",
            actor="test_qc_reviewer",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, **updates):
        payload = {
            "project_id": PROJECT_ID,
            "subject_id": SUBJECT_ID,
            "criterion_uid": "in-01",
            "criterion_kind": CriterionKind.INCLUSION,
            "expected_state_revision": 0,
            "expected_rule_revision": RULE_REVISION,
            "expected_subject_source_revision": self.subject_source_revision,
            "idempotency_key": "review-key-1",
            "actor": "medical_manager",
            "action": EligibilityReviewAction.REVISE_DECISION,
            "decision": EligibilityDecision.MET,
            "reason": "Reviewed against current evidence metadata.",
            "evidence_ids": ("evidence-1",),
            "evidence_processing_state": EvidenceProcessingState.COMPLETED,
        }
        payload.update(updates)
        return EligibilityReviewRequest(**payload)

    def test_inclusion_and_exclusion_decision_vocabularies_are_disjoint(self):
        inclusion = self.workflow.allowed_decisions(CriterionKind.INCLUSION)
        exclusion = self.workflow.allowed_decisions(CriterionKind.EXCLUSION)

        self.assertEqual(
            {
                "met",
                "not_met",
                "insufficient_evidence",
                "not_applicable",
                "requires_investigator_judgment",
            },
            {item.value for item in inclusion},
        )
        self.assertEqual(
            {
                "absent",
                "present",
                "insufficient_evidence",
                "not_applicable",
                "requires_investigator_judgment",
            },
            {item.value for item in exclusion},
        )
        self.assertNotIn("pass", {item.value for item in inclusion | exclusion})
        self.assertNotIn("fail", {item.value for item in inclusion | exclusion})

    def test_internal_source_revision_must_match_canonical_contract(self):
        sources = [
            {
                "source_id": "raw-source-1",
                "source_revision": "raw-source-rev-1",
                "content_hash": "raw-content-hash-1",
                "size_bytes": 55,
                "media_class": "pdf",
                "processing_unit_kind": "page",
                "expected_unit_count": 2,
                "expected_unit_count_status": "known",
            }
        ]
        canonical = eligibility_subject_source_revision(
            PROJECT_ID,
            "SA07006",
            sources,
        )
        provided = self.workflow.register_subject_sources(
            PROJECT_ID,
            "SA07006",
            sources,
            subject_source_revision=canonical,
        )
        self.assertEqual(canonical, provided)
        with self.assertRaisesRegex(ValueError, "canonical source contract"):
            self.workflow.register_subject_sources(
                PROJECT_ID,
                "SA07007",
                sources,
                subject_source_revision="eligsubsrcv_forged",
            )

    def test_client_processing_state_cannot_downgrade_server_completed_evidence(self):
        result = self.workflow.apply_action(
            self.request(
                decision=EligibilityDecision.INSUFFICIENT_EVIDENCE,
                evidence_processing_state=EvidenceProcessingState.NOT_STARTED,
                evidence_ids=(),
                idempotency_key="insufficient-server-authoritative",
            )
        )
        self.assertEqual("completed", result.state["evidence_processing_state"])

    def test_decisive_review_requires_current_evidence_reference(self):
        with self.assertRaisesRegex(ValueError, "requires evidence_ids"):
            self.workflow.apply_action(
                self.request(evidence_ids=(), idempotency_key="no-evidence")
            )
        self.assertEqual([], self.store.eligibility_review_records(PROJECT_ID, SUBJECT_ID))

    def test_ai_draft_is_separate_from_medical_decision_and_survives_acceptance(self):
        draft = self.workflow.apply_action(
            self.request(
                action=EligibilityReviewAction.SAVE_AI_DRAFT,
                actor="workbench_ai_gateway",
                idempotency_key="ai-draft-1",
            )
        )
        self.assertEqual(1, draft.state_revision)
        self.assertEqual("met", draft.state["ai_draft_decision"])
        self.assertIsNone(draft.state["medical_decision"])

        accepted = self.workflow.apply_action(
            self.request(
                action=EligibilityReviewAction.ACCEPT_AI_DRAFT,
                expected_state_revision=1,
                idempotency_key="accept-ai-1",
            )
        )
        self.assertEqual(2, accepted.state_revision)
        self.assertEqual("met", accepted.state["ai_draft_decision"])
        self.assertEqual("met", accepted.state["medical_decision"])
        records = self.store.eligibility_review_records(PROJECT_ID, SUBJECT_ID, "in-01")
        self.assertEqual(["ai_draft", "medical_action"], [row["record_type"] for row in records])

    def test_accept_ai_draft_is_rejected_when_no_ai_draft_exists(self):
        with self.assertRaisesRegex(ValueError, "requires an existing AI draft"):
            self.workflow.apply_action(
                self.request(
                    action=EligibilityReviewAction.ACCEPT_AI_DRAFT,
                    decision=None,
                    evidence_ids=(),
                    idempotency_key="accept-without-ai-draft",
                )
            )
        self.assertEqual(
            [], self.store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)
        )

    def test_all_not_applicable_remains_medical_review_pending(self):
        self.workflow.apply_action(
            self.request(
                decision=EligibilityDecision.NOT_APPLICABLE,
                evidence_ids=(),
                idempotency_key="in-not-applicable",
            )
        )
        self.workflow.apply_action(
            self.request(
                criterion_uid="ex-01",
                criterion_kind=CriterionKind.EXCLUSION,
                decision=EligibilityDecision.NOT_APPLICABLE,
                evidence_ids=(),
                idempotency_key="ex-not-applicable",
            )
        )

        aggregate = EligibilityReviewWorkflow(self.store).aggregate_subject_review(
            PROJECT_ID,
            SUBJECT_ID,
        )
        self.assertEqual(2, aggregate.reviewed_count)
        self.assertEqual(("medical_review_pending",), aggregate.statuses)

    def test_subject_aggregate_contains_review_statuses_only(self):
        self.workflow.apply_action(
            self.request(
                decision=EligibilityDecision.NOT_MET,
                idempotency_key="in-gap-1",
            )
        )
        self.workflow.apply_action(
            self.request(
                criterion_uid="ex-01",
                criterion_kind=CriterionKind.EXCLUSION,
                decision=EligibilityDecision.PRESENT,
                idempotency_key="ex-present-1",
            )
        )

        aggregate = self.workflow.aggregate_subject_review(PROJECT_ID, SUBJECT_ID)
        self.assertIn("has_inclusion_failure", aggregate.statuses)
        self.assertIn("has_exclusion", aggregate.statuses)
        self.assertNotIn("has_gaps", aggregate.statuses)
        self.assertNotIn("eligible", aggregate.statuses)
        self.assertNotIn("not_eligible", aggregate.statuses)
        self.assertEqual(2, aggregate.criterion_count)

    def test_subject_aggregate_ignores_decision_from_previous_rule_revision(self):
        self.workflow.apply_action(self.request())
        self.workflow.register_rule_revision(
            PROJECT_ID,
            "rule-rev-2",
            [
                {
                    "criterion_uid": "in-01",
                    "criterion_kind": "inclusion",
                    "source_rule_label": "IN-01",
                    "source_locator": {"paragraph": 11},
                    "normalized_text_hash": "in-rule-hash-v2",
                    "display_order": 1,
                },
                {
                    "criterion_uid": "ex-01",
                    "criterion_kind": "exclusion",
                    "source_rule_label": "EX-01",
                    "source_locator": {"paragraph": 20},
                    "normalized_text_hash": "ex-rule-hash",
                    "display_order": 2,
                },
            ],
        )

        aggregate = self.workflow.aggregate_subject_review(PROJECT_ID, SUBJECT_ID)

        self.assertEqual("rule-rev-2", aggregate.rule_revision)
        self.assertEqual(0, aggregate.reviewed_count)
        self.assertIn("blocked_by_incomplete_review", aggregate.statuses)

    def test_subject_aggregate_ignores_decision_from_previous_source_revision(self):
        self.workflow.apply_action(self.request())
        self.workflow.register_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            [
                {
                    "source_id": "source-1",
                    "source_revision": "source-rev-2",
                    "content_hash": "source-hash-2",
                    "size_bytes": 101,
                    "media_class": "text_document_image",
                }
            ],
        )

        aggregate = self.workflow.aggregate_subject_review(PROJECT_ID, SUBJECT_ID)

        self.assertEqual(0, aggregate.reviewed_count)
        self.assertIn("blocked_by_incomplete_review", aggregate.statuses)

    def test_request_evidence_makes_existing_decision_incomplete_without_rewriting_history(self):
        first = self.workflow.apply_action(self.request())
        records_before = self.store.eligibility_review_records(
            PROJECT_ID, SUBJECT_ID, "in-01"
        )

        requested = self.workflow.apply_action(
            self.request(
                action=EligibilityReviewAction.REQUEST_EVIDENCE,
                decision=None,
                evidence_ids=(),
                expected_state_revision=first.state_revision,
                evidence_processing_state=EvidenceProcessingState.QUEUED,
                idempotency_key="request-more-evidence",
            )
        )

        self.assertEqual("met", requested.state["medical_decision"])
        self.assertEqual("request_evidence", requested.state["latest_action"])
        aggregate = self.workflow.aggregate_subject_review(PROJECT_ID, SUBJECT_ID)
        self.assertEqual(0, aggregate.reviewed_count)
        self.assertIn("blocked_by_incomplete_review", aggregate.statuses)
        records_after = self.store.eligibility_review_records(
            PROJECT_ID, SUBJECT_ID, "in-01"
        )
        self.assertEqual(records_before[0], records_after[0])
        self.assertEqual(
            ["revise_decision", "request_evidence"],
            [record["action"] for record in records_after],
        )

    def test_defer_review_makes_existing_decision_incomplete_without_rewriting_history(self):
        first = self.workflow.apply_action(self.request())
        records_before = self.store.eligibility_review_records(
            PROJECT_ID, SUBJECT_ID, "in-01"
        )

        deferred = self.workflow.apply_action(
            self.request(
                action=EligibilityReviewAction.DEFER_REVIEW,
                decision=None,
                evidence_ids=(),
                expected_state_revision=first.state_revision,
                idempotency_key="defer-existing-review",
            )
        )

        self.assertEqual("met", deferred.state["medical_decision"])
        self.assertEqual("defer_review", deferred.state["latest_action"])
        aggregate = self.workflow.aggregate_subject_review(PROJECT_ID, SUBJECT_ID)
        self.assertEqual(0, aggregate.reviewed_count)
        self.assertIn("blocked_by_incomplete_review", aggregate.statuses)
        records_after = self.store.eligibility_review_records(
            PROJECT_ID, SUBJECT_ID, "in-01"
        )
        self.assertEqual(records_before[0], records_after[0])
        self.assertEqual(
            ["revise_decision", "defer_review"],
            [record["action"] for record in records_after],
        )

    def test_reset_after_source_change_requires_drift_and_clears_both_decision_layers(self):
        first = self.workflow.apply_action(self.request())
        with self.assertRaisesRegex(ValueError, "requires rule or source revision drift"):
            self.workflow.apply_action(
                self.request(
                    action=EligibilityReviewAction.RESET_AFTER_SOURCE_CHANGE,
                    decision=None,
                    evidence_ids=(),
                    expected_state_revision=first.state_revision,
                    idempotency_key="reset-without-drift",
                )
            )

        new_source_revision = self.workflow.register_subject_sources(
            PROJECT_ID,
            SUBJECT_ID,
            [
                {
                    "source_id": "source-1",
                    "source_revision": "source-rev-2",
                    "content_hash": "source-hash-2",
                    "size_bytes": 101,
                    "media_class": "text_document_image",
                }
            ],
        )
        reset = self.workflow.apply_action(
            self.request(
                action=EligibilityReviewAction.RESET_AFTER_SOURCE_CHANGE,
                decision=None,
                evidence_ids=(),
                expected_state_revision=first.state_revision,
                expected_subject_source_revision=new_source_revision,
                evidence_processing_state=EvidenceProcessingState.NOT_STARTED,
                idempotency_key="reset-with-drift",
            )
        )
        self.assertEqual(2, reset.state_revision)
        self.assertIsNone(reset.state["ai_draft_decision"])
        self.assertIsNone(reset.state["medical_decision"])
        self.assertEqual(new_source_revision, reset.state["subject_source_revision"])


if __name__ == "__main__":
    unittest.main()
