from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from packages.contracts.workbench_contracts import AiTaskSourceRef
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver
from services.api.app.ai_gateway import AiPromptEnvelope, DisabledAiProvider
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore
from services.api.app.demo_repository import DemoRepository
from services.api.app.eligibility_ai_review import (
    EligibilityAiBatchService,
    EligibilityAiCriterion,
    plan_criterion_batches,
)
from services.api.app.eligibility_protocol_rules import eligibility_criterion_text_hash
from services.api.app.eligibility_review_workflow import (
    CriterionKind,
    EligibilityReviewWorkflow,
)
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
PROJECT_ID = "proj_ai_batch"
SUBJECT_ID = "SUBJECT-001"
RULE_REVISION = "rule-revision-ai-1"
SUBJECT_SOURCE_REVISION = "subject-source-ai-1"
PACKET_DIGEST = "eligpacket_" + "b" * 64


class EligibilityBatchProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(self, fail_kind=""):
        self.fail_kind = fail_kind
        self.calls = []

    def run(self, envelope: AiPromptEnvelope):
        self.calls.append(envelope)
        context = envelope.payload["task_context"]
        results = []
        for uid in context["criterion_uids"]:
            results.append(
                {
                    "criterion_uid": uid,
                    "decision": (
                        "met" if context["criterion_kind"] == "inclusion" else "absent"
                    ),
                    "evidence_ids": ["evidence-1"],
                    "rationale": "Versioned evidence supports this AI draft.",
                    "needs_medical_confirmation": True,
                }
            )
        if context["criterion_kind"] == self.fail_kind:
            results.pop()
        return {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.prompt_version,
            "input_source_ids": [
                source["source_id"] for source in envelope.payload["allowed_sources"]
            ],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [],
            "evidence_spans": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "batch_id": context["batch_id"],
            "criterion_kind": context["criterion_kind"],
            "rule_revision": context["rule_revision"],
            "subject_source_revision": context["subject_source_revision"],
            "packet_digest": context["packet_digest"],
            "criterion_results": results,
        }


def criteria(kind, count, start=1):
    prefix = "in" if kind == CriterionKind.INCLUSION else "ex"
    return [
        EligibilityAiCriterion(
            criterion_uid=f"{prefix}-{index:02d}",
            criterion_kind=kind,
            text=f"Criterion {prefix}-{index:02d}",
            source_locator=f"docx:paragraph:{index}",
            display_order=index,
        )
        for index in range(start, start + count)
    ]


def seed_store(store, all_criteria):
    store.replace_eligibility_rule_revision(
        PROJECT_ID,
        RULE_REVISION,
        [
            {
                "criterion_uid": item.criterion_uid,
                "criterion_kind": item.criterion_kind.value,
                "source_rule_label": item.criterion_uid.upper(),
                "source_locator": {"locator": item.source_locator},
                "normalized_text_hash": eligibility_criterion_text_hash(item.text),
                "display_order": item.display_order,
            }
            for item in all_criteria
        ],
    )
    store.replace_eligibility_subject_sources(
        PROJECT_ID,
        SUBJECT_ID,
        SUBJECT_SOURCE_REVISION,
        [
            {
                "source_id": "source-1",
                "source_revision": "source-revision-1",
                "content_hash": "source-content-hash-1",
                "size_bytes": 100,
                "media_class": "text_document_image",
            }
        ],
    )
    store.add_eligibility_evidence_span(
        {
            "evidence_id": "evidence-1",
            "project_id": PROJECT_ID,
            "subject_id": SUBJECT_ID,
            "source_id": "source-1",
            "source_revision": "source-revision-1",
            "extraction_revision": "extract-revision-1",
            "locator": {"page": 1, "region": [1, 2, 3, 4]},
            "media_class": "text_document_image",
            "processing_state": "completed",
            "quality_state": "sampled_pass",
            "extraction_confidence": 0.95,
            "medical_verification_status": "not_reviewed",
        }
    )
    store.commit_eligibility_evidence_visual_qc(
        project_id=PROJECT_ID,
        subject_id=SUBJECT_ID,
        evidence_id="evidence-1",
        expected_qc_revision=0,
        expected_source_revision="source-revision-1",
        expected_extraction_revision="extract-revision-1",
        idempotency_key="ai-fixture-qc-pass",
        result="sampled_pass",
        reason_code="fixture_visual_comparison",
        user_reason="Fixture page and extracted region were compared.",
        sample_plan_id="fixture-full-page-v1",
        sample_unit={"page": 1, "region": [1, 2, 3, 4]},
        policy_version="visual-qc-policy-v1",
        actor="test_qc_reviewer",
    )


def ai_records(all_criteria):
    return [
        {
            "record_id": f"record-{item.criterion_uid}",
            "project_id": PROJECT_ID,
            "subject_id": SUBJECT_ID,
            "criterion_uid": item.criterion_uid,
            "criterion_kind": item.criterion_kind.value,
            "record_type": "ai_draft",
            "action": "save_ai_draft",
            "action_decision": (
                "met" if item.criterion_kind == CriterionKind.INCLUSION else "absent"
            ),
            "evidence_processing_state": "completed",
            "rule_revision": RULE_REVISION,
            "subject_source_revision": SUBJECT_SOURCE_REVISION,
            "previous_state_revision": 0,
            "new_state_revision": 1,
            "evidence_ids": ["evidence-1"],
            "reason": "Synthetic AI batch rationale.",
            "actor": "workbench_ai_gateway",
        }
        for item in all_criteria
    ]


class EligibilityAiReviewTests(unittest.TestCase):
    def _service(self, root, store, provider):
        runner = AiTaskRunner(
            DemoRepository(PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"),
            AiTaskStore(root / "ai_runs.jsonl"),
            provider_factory=lambda resolution: provider,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )
        return EligibilityAiBatchService(runner, EligibilityReviewWorkflow(store))

    @staticmethod
    def _evidence_source(evidence_id="evidence-1"):
        return AiTaskSourceRef(
            source_id=evidence_id,
            source_type="eligibility_evidence_span",
            title="Evidence 1",
            locator="source:1:page:1",
            text_preview="Bounded synthetic evidence.",
            project_id=PROJECT_ID,
            module="eligibility_review",
        )

    def test_batch_planner_uses_five_to_eight_or_explicit_single_tasks(self):
        self.assertEqual([8, 8, 7, 7], [len(batch) for batch in plan_criterion_batches(criteria(CriterionKind.EXCLUSION, 30))])
        self.assertEqual([5, 5], [len(batch) for batch in plan_criterion_batches(criteria(CriterionKind.INCLUSION, 10))])
        self.assertEqual([8, 1], [len(batch) for batch in plan_criterion_batches(criteria(CriterionKind.INCLUSION, 9))])
        self.assertEqual([1, 1, 1, 1], [len(batch) for batch in plan_criterion_batches(criteria(CriterionKind.INCLUSION, 4))])
        with self.assertRaisesRegex(ValueError, "one criterion kind"):
            plan_criterion_batches(
                criteria(CriterionKind.INCLUSION, 1)
                + criteria(CriterionKind.EXCLUSION, 1)
            )

    def test_in_and_ex_batches_are_independent_and_failed_batch_writes_no_drafts(self):
        all_criteria = criteria(CriterionKind.INCLUSION, 5) + criteria(
            CriterionKind.EXCLUSION, 5, start=101
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SqliteRuntimeStore(root / "runtime.sqlite3")
            seed_store(store, all_criteria)
            provider = EligibilityBatchProvider(fail_kind="exclusion")
            runner = AiTaskRunner(
                DemoRepository(PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"),
                AiTaskStore(root / "ai_runs.jsonl"),
                provider_factory=lambda resolution: provider,
                policy_resolver=AiExecutionPolicyResolver(
                    deployment_profile="local_private_clinical",
                    provider_name="buddy",
                    model_name="deepseek-v4-pro",
                ),
            )
            service = EligibilityAiBatchService(
                runner, EligibilityReviewWorkflow(store)
            )
            result = service._run_verified_subject(
                project_id=PROJECT_ID,
                subject_id=SUBJECT_ID,
                subject_token="eligsub_subject_001",
                rule_revision=RULE_REVISION,
                subject_source_revision=SUBJECT_SOURCE_REVISION,
                packet_digest=PACKET_DIGEST,
                criteria=all_criteria,
                evidence_sources=[
                    AiTaskSourceRef(
                        source_id="evidence-1",
                        source_type="eligibility_evidence_span",
                        title="Evidence 1",
                        locator="source:1:page:1",
                        text_preview="Bounded synthetic evidence.",
                        project_id=PROJECT_ID,
                        module="eligibility_review",
                    )
                ],
            )

            self.assertEqual(2, len(provider.calls))
            self.assertEqual(
                ["inclusion", "exclusion"],
                [
                    call.payload["task_context"]["criterion_kind"]
                    for call in provider.calls
                ],
            )
            self.assertTrue(result.batches[0].drafts_persisted)
            self.assertFalse(result.batches[1].drafts_persisted)
            self.assertEqual("failed", result.batches[1].status)
            self.assertEqual(
                5,
                len(store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)),
            )
            self.assertTrue(
                all(
                    store.eligibility_review_state(
                        PROJECT_ID, SUBJECT_ID, item.criterion_uid
                    )
                    is not None
                    for item in all_criteria[:5]
                )
            )
            self.assertTrue(
                all(
                    store.eligibility_review_state(
                        PROJECT_ID, SUBJECT_ID, item.criterion_uid
                    )
                    is None
                    for item in all_criteria[5:]
                )
            )

    def test_noncanonical_or_unverified_inputs_make_zero_provider_calls(self):
        batch_criteria = criteria(CriterionKind.INCLUSION, 5)
        cases = (
            (
                "forged rule text",
                [
                    EligibilityAiCriterion(
                        criterion_uid=item.criterion_uid,
                        criterion_kind=item.criterion_kind,
                        text=("forged" if index == 0 else item.text),
                        source_locator=item.source_locator,
                        display_order=item.display_order,
                    )
                    for index, item in enumerate(batch_criteria)
                ],
                [self._evidence_source()],
                "canonical",
            ),
            (
                "forged rule locator",
                [
                    EligibilityAiCriterion(
                        criterion_uid=item.criterion_uid,
                        criterion_kind=item.criterion_kind,
                        text=item.text,
                        source_locator=(
                            "docx:paragraph:999" if index == 0 else item.source_locator
                        ),
                        display_order=item.display_order,
                    )
                    for index, item in enumerate(batch_criteria)
                ],
                [self._evidence_source()],
                "canonical",
            ),
            (
                "unknown evidence",
                batch_criteria,
                [self._evidence_source("unknown-evidence")],
                "evidence",
            ),
        )
        for label, supplied_criteria, sources, expected_error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                store = SqliteRuntimeStore(root / "runtime.sqlite3")
                seed_store(store, batch_criteria)
                provider = EligibilityBatchProvider()
                service = self._service(root, store, provider)
                with self.assertRaisesRegex(Exception, expected_error):
                    service._run_verified_subject(
                        project_id=PROJECT_ID,
                        subject_id=SUBJECT_ID,
                        subject_token="eligsub_subject_001",
                        rule_revision=RULE_REVISION,
                        subject_source_revision=SUBJECT_SOURCE_REVISION,
                        packet_digest=PACKET_DIGEST,
                        criteria=supplied_criteria,
                        evidence_sources=sources,
                    )
                self.assertEqual([], provider.calls)

    def test_completed_packet_batch_replays_before_a_second_provider_call(self):
        batch_criteria = criteria(CriterionKind.INCLUSION, 5)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SqliteRuntimeStore(root / "runtime.sqlite3")
            seed_store(store, batch_criteria)
            provider = EligibilityBatchProvider()
            service = self._service(root, store, provider)
            request = {
                "project_id": PROJECT_ID,
                "subject_id": SUBJECT_ID,
                "subject_token": "eligsub_subject_001",
                "rule_revision": RULE_REVISION,
                "subject_source_revision": SUBJECT_SOURCE_REVISION,
                "packet_digest": PACKET_DIGEST,
                "criteria": batch_criteria,
                "evidence_sources": [self._evidence_source()],
            }
            first = service._run_verified_subject(**request)
            replay = service._run_verified_subject(**request)

            self.assertEqual(1, len(provider.calls))
            self.assertEqual("completed", first.batches[0].status)
            self.assertEqual("replayed", replay.batches[0].status)
            self.assertTrue(replay.batches[0].drafts_persisted)
            self.assertEqual(
                5,
                len(store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)),
            )

    def test_disabled_ai_blocks_without_fallback_or_draft_persistence(self):
        batch_criteria = criteria(CriterionKind.INCLUSION, 5)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = SqliteRuntimeStore(root / "runtime.sqlite3")
            seed_store(store, batch_criteria)
            runner = AiTaskRunner(
                DemoRepository(PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"),
                AiTaskStore(root / "ai_runs.jsonl"),
                provider_factory=lambda resolution: DisabledAiProvider(),
                policy_resolver=AiExecutionPolicyResolver(
                    deployment_profile="local_private_clinical",
                    provider_name="disabled",
                    model_name="not_configured",
                ),
            )
            service = EligibilityAiBatchService(
                runner, EligibilityReviewWorkflow(store)
            )
            result = service._run_verified_subject(
                project_id=PROJECT_ID,
                subject_id=SUBJECT_ID,
                subject_token="eligsub_subject_001",
                rule_revision=RULE_REVISION,
                subject_source_revision=SUBJECT_SOURCE_REVISION,
                packet_digest=PACKET_DIGEST,
                criteria=batch_criteria,
                evidence_sources=[self._evidence_source()],
            )

            self.assertEqual("blocked", result.batches[0].status)
            self.assertFalse(result.batches[0].drafts_persisted)
            self.assertEqual(
                [], store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)
            )

    def test_atomic_batch_faults_leave_no_partial_records_states_audit_or_idempotency(self):
        batch_criteria = criteria(CriterionKind.INCLUSION, 5)
        for checkpoint in (
            "after_eligibility_ai_batch_records",
            "after_eligibility_ai_batch_states",
            "after_eligibility_ai_batch_audit",
        ):
            with self.subTest(checkpoint=checkpoint), tempfile.TemporaryDirectory() as tmp:
                db_path = Path(tmp) / "runtime.sqlite3"
                seed = SqliteRuntimeStore(db_path)
                seed_store(seed, batch_criteria)
                baseline_audit = seed.runtime_audit_records(PROJECT_ID)

                def fail(current):
                    if current == checkpoint:
                        raise RuntimeError(f"fault:{checkpoint}")

                store = SqliteRuntimeStore(db_path, fault_injector=fail)
                with self.assertRaisesRegex(RuntimeError, checkpoint):
                    store.commit_eligibility_ai_draft_batch(
                        ai_records(batch_criteria),
                        batch_id="batch-atomic-1",
                        idempotency_key="batch-atomic-key-1",
                        request_fingerprint="batch-atomic-fingerprint-1",
                    )
                self.assertEqual([], store.eligibility_review_records(PROJECT_ID, SUBJECT_ID))
                self.assertEqual([], store.eligibility_subject_review_states(PROJECT_ID, SUBJECT_ID))
                self.assertEqual(
                    baseline_audit,
                    store.runtime_audit_records(PROJECT_ID),
                )

    def test_atomic_batch_replay_and_stale_member_reject_whole_batch(self):
        batch_criteria = criteria(CriterionKind.INCLUSION, 5)
        with tempfile.TemporaryDirectory() as tmp:
            store = SqliteRuntimeStore(Path(tmp) / "runtime.sqlite3")
            seed_store(store, batch_criteria)
            records = ai_records(batch_criteria)
            first = store.commit_eligibility_ai_draft_batch(
                records,
                batch_id="batch-replay-1",
                idempotency_key="batch-replay-key-1",
                request_fingerprint="batch-replay-fingerprint-1",
            )
            replay = store.commit_eligibility_ai_draft_batch(
                records,
                batch_id="batch-replay-1",
                idempotency_key="batch-replay-key-1",
                request_fingerprint="batch-replay-fingerprint-1",
            )
            self.assertFalse(first.replayed)
            self.assertTrue(replay.replayed)
            self.assertEqual(first.state_revisions, replay.state_revisions)
            self.assertEqual(5, len(store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)))

            stale_records = ai_records(batch_criteria)
            stale_records[0]["previous_state_revision"] = 1
            stale_records[0]["new_state_revision"] = 2
            for row in stale_records[1:]:
                row["record_id"] += "-stale"
            with self.assertRaisesRegex(Exception, "stale"):
                store.commit_eligibility_ai_draft_batch(
                    stale_records,
                    batch_id="batch-stale-2",
                    idempotency_key="batch-stale-key-2",
                    request_fingerprint="batch-stale-fingerprint-2",
                )
            self.assertEqual(5, len(store.eligibility_review_records(PROJECT_ID, SUBJECT_ID)))
            rejected = [
                event
                for event in store.runtime_audit_records(PROJECT_ID)
                if event["event_type"] == "eligibility_ai_batch_rejected"
            ]
            self.assertEqual(1, len(rejected))


if __name__ == "__main__":
    unittest.main()
