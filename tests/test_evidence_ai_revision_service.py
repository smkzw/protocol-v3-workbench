from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.contracts.workbench_contracts import AiTaskRunStatus  # noqa: E402
from services.api.app.ai_execution_policy import AiExecutionPolicyResolver  # noqa: E402
from services.api.app.ai_gateway import DisabledAiProvider  # noqa: E402
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore  # noqa: E402
from services.api.app.demo_repository import DemoRepository  # noqa: E402
from services.api.app.evidence_ai_revision import EvidenceAiRevisionService  # noqa: E402
from services.api.app.evidence_design_manifest import PNH_COMPETITOR_DB, EvidenceDesignManifestService  # noqa: E402
from services.api.app.evidence_picos_workflow import EvidencePicosWorkflowService, SqliteEvidencePicosDecisionStore  # noqa: E402
from services.api.app.sqlite_runtime_store import SqliteRuntimeStore  # noqa: E402


class PicosRevisionProvider:
    provider_name = "test_private_provider"
    model_name = "test-clinical-model"

    def __init__(self):
        self.calls = []

    def run(self, envelope):
        self.calls.append(envelope)
        source = envelope.payload["allowed_sources"][0]
        return {
            "task_id": envelope.payload["task_id"],
            "task_type": envelope.payload["task_type"],
            "provider": self.provider_name,
            "model": self.model_name,
            "prompt_version": envelope.payload["prompt_version"],
            "input_source_ids": [item["source_id"] for item in envelope.payload["allowed_sources"]],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [
                {
                    "finding_id": "finding-1",
                    "status": "needs_medical_confirmation",
                    "title": "目标PNH人群建议修订",
                    "source_id": source["source_id"],
                    "evidence_span_ids": ["span-1"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span-1",
                    "source_id": source["source_id"],
                    "locator": source["locator"],
                    "quote": source["text_preview"][:120],
                }
            ],
            "uncertainties": [
                {
                    "level": "medical_review",
                    "description": "Hb、输血和既往治疗稳定期阈值需医学确认。",
                }
            ],
            "needs_medical_confirmation": True,
            "schema_version": envelope.payload["schema_version"],
            "revision": {
                "anchor_type": "picos_question",
                "anchor_id": "picos:population",
                "proposal_text": "建议聚焦既往C5抑制剂治疗后仍存在残余贫血的人群。",
                "proposed_option_id": "picos:population:option:2",
                "rationale": "该人群存在明确未满足需求，但阈值仍需医学确认。",
                "evidence_span_ids": ["span-1"],
            },
        }


@unittest.skipUnless(PNH_COMPETITOR_DB.exists(), "PNH evidence source is unavailable")
class EvidenceAiRevisionServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.runtime = SqliteRuntimeStore(root / "runtime.sqlite3")
        self.manifests = EvidenceDesignManifestService()
        self.picos = EvidencePicosWorkflowService(
            self.manifests,
            SqliteEvidencePicosDecisionStore(self.runtime),
        )
        self.repo = DemoRepository(ROOT / "demo_data" / "workbench_demo_v0_1.json")

    def tearDown(self):
        self.tmp.cleanup()

    def runner(self, provider):
        return AiTaskRunner(
            self.repo,
            AiTaskStore(Path(self.tmp.name) / f"ai-runs-{len(getattr(provider, 'calls', []))}.jsonl"),
            provider_factory=lambda resolution: provider,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="approved_private_documents",
                provider_name=provider.provider_name,
                model_name=provider.model_name,
            ),
        )

    def test_submit_accept_and_rewrite_are_persisted_but_do_not_directly_edit_picos(self):
        provider = PicosRevisionProvider()
        service = EvidenceAiRevisionService(
            self.manifests,
            self.picos,
            self.runner(provider),
            self.runtime,
        )
        project_id = "proj_my008_pnh_3_01"
        workflow = self.picos.workflow(project_id)
        result = service.submit(
            project_id,
            workflow.package_id,
            {
                "anchor_id": "picos:population",
                "user_instruction": "请进一步明确既往补体抑制剂治疗和残余贫血边界。",
                "expected_picos_revision": 0,
                "expected_evidence_package_hash": workflow.evidence_package_hash,
                "idempotency_key": "ai-pnh-submit-1",
            },
        )
        self.assertEqual("pending_medical_action", result.thread.status)
        self.assertTrue(result.requires_explicit_picos_action)
        self.assertEqual("select_option", result.recommended_picos_action["action"])
        self.assertEqual(0, self.picos.workflow(project_id).revision)
        self.assertEqual(1, len(provider.calls))

        accepted = service.apply_action(
            project_id,
            result.thread.thread_id,
            {
                "action": "accept",
                "proposal_id": result.proposal.proposal_id,
                "expected_thread_revision": 1,
                "idempotency_key": "ai-pnh-accept-1",
            },
        )
        self.assertEqual("accepted_pending_explicit_picos_action", accepted.thread.status)
        self.assertEqual(0, self.picos.workflow(project_id).revision)

        second = service.submit(
            project_id,
            workflow.package_id,
            {
                "anchor_id": "picos:population",
                "user_instruction": "请提出另一版更保守的人群定义。",
                "expected_picos_revision": 0,
                "expected_evidence_package_hash": workflow.evidence_package_hash,
                "idempotency_key": "ai-pnh-submit-2",
            },
        )
        rewritten = service.apply_action(
            project_id,
            second.thread.thread_id,
            {
                "action": "request_rewrite",
                "proposal_id": second.proposal.proposal_id,
                "expected_thread_revision": 1,
                "rewrite_instruction": "保留经治人群，但补充稳定治疗期的不确定性。",
                "idempotency_key": "ai-pnh-rewrite-1",
            },
        )
        self.assertEqual(2, rewritten.thread.revision)
        self.assertEqual(2, len(rewritten.thread.proposals))
        self.assertEqual("rewrite_requested", rewritten.thread.proposals[0].user_decision)
        self.assertEqual(3, len(provider.calls))

        restarted = EvidenceAiRevisionService(
            EvidenceDesignManifestService(),
            EvidencePicosWorkflowService(EvidenceDesignManifestService(), SqliteEvidencePicosDecisionStore(SqliteRuntimeStore(self.runtime.db_path))),
            self.runner(provider),
            SqliteRuntimeStore(self.runtime.db_path),
        )
        self.assertEqual(2, restarted.list_threads(project_id, workflow.package_id)[-1].revision)

    def test_disabled_provider_fails_closed_without_thread_creation(self):
        provider = DisabledAiProvider()
        service = EvidenceAiRevisionService(
            self.manifests,
            self.picos,
            self.runner(provider),
            self.runtime,
        )
        workflow = self.picos.workflow("proj_my008_pnh_3_01")
        with self.assertRaises(ValueError):
            service.submit(
                workflow.project_id,
                workflow.package_id,
                {
                    "anchor_id": "picos:population",
                    "user_instruction": "请修订人群定义。",
                    "expected_picos_revision": 0,
                    "expected_evidence_package_hash": workflow.evidence_package_hash,
                },
            )
        self.assertEqual([], self.runtime.evidence_ai_revision_threads(workflow.project_id, workflow.package_id))


if __name__ == "__main__":
    unittest.main()
