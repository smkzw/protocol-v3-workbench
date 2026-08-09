from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from packages.contracts.workbench_contracts import AiTaskRequest, AiTaskSourceRef
from services.api.app.ai_execution_policy import AiExecutionPolicyDenied, AiExecutionPolicyResolver
from services.api.app.ai_gateway import (
    AiPromptEnvelope,
    AiSourceRef,
    AiTaskSpec,
    AiTaskType,
    PromptRegistry,
    validate_ai_output,
)
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore
from services.api.app.demo_repository import DemoRepository


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
PROJECT_ID = "proj_d001"
PACKET_DIGEST = "eligpacket_" + "a" * 64


def eligibility_context(**updates):
    context = {
        "batch_id": "eligbatch_in_001",
        "subject_token": "eligsub_subject_001",
        "criterion_kind": "inclusion",
        "criterion_uids": ["criterion-in-01", "criterion-in-02"],
        "rule_revision": "eligrulev_001",
        "subject_source_revision": "eligsubsrcv_001",
        "packet_digest": PACKET_DIGEST,
        "allowed_evidence_ids": ["evidence-001", "evidence-002"],
    }
    context.update(updates)
    return context


class EligibilityBatchProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(self, mutate=None):
        self.mutate = mutate
        self.calls = []

    def run(self, envelope: AiPromptEnvelope):
        self.calls.append(envelope)
        context = envelope.payload["task_context"]
        output = {
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
            "criterion_results": [
                {
                    "criterion_uid": "criterion-in-01",
                    "decision": "met",
                    "evidence_ids": ["evidence-001"],
                    "rationale": "Current evidence supports the criterion draft.",
                    "needs_medical_confirmation": True,
                },
                {
                    "criterion_uid": "criterion-in-02",
                    "decision": "insufficient_evidence",
                    "evidence_ids": [],
                    "rationale": "The processed source does not contain enough evidence.",
                    "needs_medical_confirmation": True,
                },
            ],
        }
        if self.mutate is not None:
            self.mutate(output)
        return output


class EligibilityAiContractTests(unittest.TestCase):
    def setUp(self):
        self.sources = [
            AiTaskSourceRef(
                source_id=f"evidence-00{index}",
                source_type="eligibility_evidence_span",
                title=f"证据 {index}",
                locator=f"source:{index}:page:1",
                text_preview=f"Bounded eligibility evidence text {index}.",
                project_id=PROJECT_ID,
                module="eligibility_review",
            )
            for index in (1, 2)
        ]
        self.request = AiTaskRequest(
            module="eligibility_review",
            task_type="eligibility_rule_review",
            prompt_version="eligibility_rule_review_v0_1",
            allowed_sources=self.sources,
            user_instruction="仅处理本批次入选标准，输出待医学确认草稿。",
            task_context=eligibility_context(),
        )
        self.policy = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="buddy",
            model_name="deepseek-v4-pro",
        )

    def runner(self, provider, root):
        return AiTaskRunner(
            DemoRepository(PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"),
            AiTaskStore(root / "ai_runs.jsonl"),
            provider_factory=lambda resolution: provider,
            policy_resolver=self.policy,
        )

    def test_prompt_contract_is_single_kind_versioned_and_medically_gated(self):
        spec = AiTaskSpec(
            task_id="eligibility-task-001",
            task_type=AiTaskType.ELIGIBILITY_RULE_REVIEW,
            prompt_version="eligibility_rule_review_v0_1",
            allowed_sources=[
                AiSourceRef(
                    source_id="evidence-001",
                    source_type="eligibility_evidence_span",
                    title="证据",
                    locator="source:1",
                    text_preview="bounded text",
                )
            ],
            task_context=eligibility_context(),
        )
        envelope = PromptRegistry().build(spec)
        contract = envelope.payload["task_specific_output_contract"]
        self.assertEqual(
            ["criterion-in-01", "criterion-in-02"],
            contract["criterion_results"]["criterion_uids"],
        )
        self.assertFalse(contract["criterion_results"]["additional_properties"])
        self.assertIn("不得引用另一类标准", envelope.system_prompt)
        self.assertIn("needs_medical_confirmation", envelope.system_prompt)

    def test_valid_batch_passes_generic_and_trusted_context_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = EligibilityBatchProvider()
            run = self.runner(provider, Path(tmp)).submit_internal(
                PROJECT_ID, self.request
            )
        self.assertEqual("completed", run.status)
        self.assertEqual("passed", run.output_validation_status)
        self.assertEqual(eligibility_context(), run.task_context_summary)
        self.assertEqual(1, len(provider.calls))

    def test_invalid_batches_fail_as_whole_without_provider_substitution(self):
        mutations = {
            "missing criterion": lambda output: output["criterion_results"].pop(),
            "duplicate criterion": lambda output: output["criterion_results"].__setitem__(
                1, deepcopy(output["criterion_results"][0])
            ),
            "cross kind decision": lambda output: output["criterion_results"][0].__setitem__(
                "decision", "present"
            ),
            "unknown evidence": lambda output: output["criterion_results"][0].__setitem__(
                "evidence_ids", ["evidence-unknown"]
            ),
            "decisive result without evidence": lambda output: output[
                "criterion_results"
            ][0].__setitem__("evidence_ids", []),
            "revision mismatch": lambda output: output.__setitem__(
                "rule_revision", "eligrulev_wrong"
            ),
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                provider = EligibilityBatchProvider(mutation)
                run = self.runner(provider, Path(tmp)).submit_internal(
                    PROJECT_ID, self.request
                )
                self.assertEqual("failed", run.status)
                self.assertEqual("failed", run.output_validation_status)
                self.assertEqual(1, len(provider.calls))
                self.assertTrue(run.validation_errors)

    def test_internal_policy_rejects_missing_or_mixed_task_context_before_provider(self):
        bad_contexts = (
            {},
            eligibility_context(criterion_kind="mixed"),
            eligibility_context(criterion_uids=["criterion-in-01"] * 2),
            eligibility_context(allowed_evidence_ids=["evidence-001"] * 2),
        )
        for context in bad_contexts:
            with self.subTest(context=context):
                request = self.request.model_copy(update={"task_context": context})
                with self.assertRaises(AiExecutionPolicyDenied):
                    self.policy.resolve_internal(PROJECT_ID, request)

    def test_schema_validator_rejects_cross_kind_and_unapproved_results(self):
        provider = EligibilityBatchProvider()
        spec = AiTaskSpec(
            task_id="eligibility-validation-001",
            task_type=AiTaskType.ELIGIBILITY_RULE_REVIEW,
            prompt_version="eligibility_rule_review_v0_1",
            allowed_sources=[],
            task_context=eligibility_context(),
        )
        envelope = type(
            "Envelope",
            (),
            {
                "task_id": spec.task_id,
                "task_type": spec.task_type,
                "prompt_version": spec.prompt_version,
                "payload": {
                    "task_context": spec.task_context,
                    "allowed_sources": [
                        {"source_id": "evidence-001"},
                        {"source_id": "evidence-002"},
                    ],
                    "forbidden_source_ids": [],
                },
            },
        )()
        output = provider.run(envelope)
        self.assertEqual([], validate_ai_output(output))
        output["criterion_results"][0]["decision"] = "present"
        output["criterion_results"][1]["needs_medical_confirmation"] = False
        errors = validate_ai_output(output)
        self.assertTrue(any("invalid for inclusion" in error for error in errors))
        self.assertTrue(any("requires needs_medical_confirmation=true" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
