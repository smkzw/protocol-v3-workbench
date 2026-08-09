from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts import (
    AiTaskFromRegistryRequest,
    AiTaskRequest,
    AiTaskSourceRef,
)
from services.api.app.ai_execution_policy import (
    AiExecutionPolicyDenied,
    AiExecutionPolicyResolver,
)
from services.api.app.ai_gateway import AiPromptEnvelope
from services.api.app.ai_task_runner import AiTaskRunner, AiTaskStore, public_ai_run
from services.api.app.demo_repository import DemoRepository
from services.api.app.main import app
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal
from services.api.app.source_intake import SourceRegistryService, SourceRegistryStore
from tests.test_source_registry import _minimal_xlsx_bytes


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[1]
PROJECT_ID = "proj_mgk10_sar_demo"


class RecordingProvider:
    provider_name = "buddy"
    model_name = "deepseek-v4-pro"

    def __init__(
        self,
        *,
        provider_override="",
        model_override="",
        prompt_override="",
        unsafe_evidence=False,
    ):
        self.calls = []
        self.provider_override = provider_override
        self.model_override = model_override
        self.prompt_override = prompt_override
        self.unsafe_evidence = unsafe_evidence

    def run(self, envelope: AiPromptEnvelope):
        self.calls.append(envelope)
        source = envelope.payload["allowed_sources"][0]
        return {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": self.provider_override or self.provider_name,
            "model": self.model_override or self.model_name,
            "prompt_version": self.prompt_override or envelope.prompt_version,
            "input_source_ids": [source["source_id"]],
            "forbidden_source_ids": envelope.payload["forbidden_source_ids"],
            "findings": [
                {
                    "finding_id": "finding_001",
                    "status": "supported",
                    "title": "字段映射候选",
                    "source_id": source["source_id"],
                    "evidence_span_ids": ["span_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_001",
                    "source_id": source["source_id"],
                    "locator": (
                        "/Users/private/evidence.xlsx"
                        if self.unsafe_evidence
                        else source["locator"]
                    ),
                    "quote": (
                        "CONFIDENTIAL PATIENT TEXT /Users/private/source.xlsx"
                        if self.unsafe_evidence
                        else source["text_preview"]
                    ),
                }
            ],
            "uncertainties": [
                {"level": "medical_review", "description": "需医学经理确认。"}
            ],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }


class NeverCalledRunner:
    def __init__(self):
        self.called = False

    def submit_registered(self, *args, **kwargs):
        self.called = True
        raise AssertionError("direct source payload route must not reach the AI runner")


class ProviderFactory:
    def __init__(self, provider):
        self.provider = provider
        self.calls = []

    def __call__(self, resolution):
        self.calls.append(resolution)
        return self.provider


class LazyProviderFactory:
    def __init__(self):
        self.calls = []
        self.provider = None

    def __call__(self, resolution):
        self.calls.append(resolution)
        self.provider = RecordingProvider()
        return self.provider


class AiExecutionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = DemoRepository(
            PROJECT_ROOT / "demo_data" / "workbench_demo_v0_1.json"
        )
        self.registry = SourceRegistryService(
            SourceRegistryStore(self.root / "sources.jsonl")
        )
        self.registered = self.registry.register_listing_file(
            PROJECT_ID,
            "edc_listing.xlsx",
            _minimal_xlsx_bytes(),
            module="medical_monitoring",
        )
        self.source_id = self.registered.spans[0].source_id

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _principal() -> MonitoringAuthenticatedPrincipal:
        return MonitoringAuthenticatedPrincipal(
            principal_id="ai-execution-policy-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=(PROJECT_ID,),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="ai-execution-policy-test-session",
            directory_revision="ai-execution-policy-test-v1",
            verification_ref_sha256="a" * 64,
        )

    def request(self, **updates):
        payload = {
            "module": "medical_monitoring",
            "task_type": "listing_semantic_mapping",
            "expected_prompt_version": "listing_semantic_mapping_v0_1",
            "source_ids": [self.source_id],
            "forbidden_source_ids": ["client_excluded_reference"],
            "user_instruction": "仅基于登记的原始 listing 建议字段映射。",
        }
        payload.update(updates)
        return AiTaskFromRegistryRequest(**payload)

    def runner(self, provider):
        provider_factory = ProviderFactory(provider)
        return AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name=provider.provider_name,
                model_name=provider.model_name,
            ),
        )

    def test_medical_writing_revision_policy_accepts_plan_pin_only_as_known_optional_key(self):
        resolver = AiExecutionPolicyResolver(
            deployment_profile="local_private_clinical",
            provider_name="openai_compatible",
            model_name="loopback-test",
            test_only_provider_injection=True,
        )
        context = {
            "revision_intent": "medical_writing_revision",
            "intent_label": "改写",
            "directional_goal": "在不改变事实的前提下规范表达。",
            "preservation_rules": ["不得新增事实。"],
            "candidate_count": 3,
            "candidate_blueprints": ["标准版", "精炼版", "保守版"],
            "protocol_assembly_plan": {
                "plan_id": "plan-001",
                "plan_revision": 2,
                "plan_sha256": "b" * 64,
            },
        }
        normalized = resolver._validate_medical_writing_revision_context(context)
        self.assertEqual("plan-001", normalized["protocol_assembly_plan"]["plan_id"])
        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "task_context keys must match"
        ):
            resolver._validate_medical_writing_revision_context(
                {**context, "unexpected": True}
            )

    def test_direct_allowed_sources_api_is_fail_closed_before_runner_or_provider(self):
        fake_runner = NeverCalledRunner()
        client = TestClient(app)
        response = None
        with patch("services.api.app.main.ai_task_runner", fake_runner):
            response = client.post(
                f"/api/projects/{PROJECT_ID}/ai-runs",
                json={
                    "module": "medical_monitoring",
                    "task_type": "listing_semantic_mapping",
                    "prompt_version": "attacker_selected_prompt",
                    "allowed_sources": [
                        {
                            "source_id": "forged_source",
                            "source_type": "forged",
                            "title": "forged",
                            "locator": "/Users/private/forged.xlsx",
                            "text_preview": "forged patient data",
                        }
                    ],
                },
            )

        self.assertEqual(403, response.status_code)
        self.assertIn("registered source IDs", response.json()["detail"])
        self.assertFalse(fake_runner.called)

    def test_cross_module_source_is_denied_without_provider_call(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "same module"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(
                    module="eligibility_review",
                    task_type="protocol_rule_extraction",
                    expected_prompt_version="protocol_rule_extraction_v0_1",
                ),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_registered_source_eligibility_review_requires_trusted_batch_service(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "trusted server batch service"
        ):
            runner.submit_registered(
                PROJECT_ID,
                self.request(
                    module="eligibility_review",
                    task_type="eligibility_rule_review",
                    expected_prompt_version="eligibility_rule_review_v0_1",
                ),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_task_module_mismatch_is_denied_without_provider_call(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "not allowed in module"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(task_type="medical_writing_revision"),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_prompt_version_is_server_selected_and_client_mismatch_is_denied(self):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "prompt version mismatch"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(expected_prompt_version="attacker_prompt_v9"),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_policy_denial_occurs_before_provider_factory_is_called(self):
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "factory_guard_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )
        with self.assertRaises(AiExecutionPolicyDenied):
            runner.submit_registered(
                PROJECT_ID,
                self.request(expected_prompt_version="attacker_prompt_v9"),
                self.registry,
            )

        self.assertEqual([], provider_factory.calls)
        self.assertIsNone(provider_factory.provider)

    def test_client_exclusions_can_only_restrict_and_cannot_overlap_selected_sources(
        self,
    ):
        provider = RecordingProvider()
        runner = self.runner(provider)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "selected and forbidden"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(forbidden_source_ids=[self.source_id]),
                self.registry,
            )

        self.assertEqual([], provider.calls)

    def test_sensitive_listing_is_denied_for_document_only_deployment_profile(self):
        provider = RecordingProvider()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "restricted_profile_ai_runs.jsonl"),
            provider_factory=ProviderFactory(provider),
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="approved_private_documents",
                provider_name=provider.provider_name,
                model_name=provider.model_name,
            ),
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "sensitive_subject_data"):
            runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        self.assertEqual([], provider.calls)

    def test_valid_registered_source_reaches_provider_with_server_policy(self):
        provider = RecordingProvider()
        run = self.runner(provider).submit_registered(
            PROJECT_ID,
            self.request(),
            self.registry,
        )

        self.assertEqual("completed", run.status)
        self.assertEqual("sensitive_subject_data", run.data_classification)
        self.assertEqual("local_private_clinical", run.deployment_profile)
        self.assertEqual("registered_sources", run.request_origin)
        self.assertTrue(run.policy_decision_id.startswith("policy_"))
        self.assertEqual(1, len(provider.calls))
        envelope = provider.calls[0]
        self.assertEqual("listing_semantic_mapping_v0_1", envelope.prompt_version)
        self.assertIn(
            "client_excluded_reference", envelope.payload["forbidden_source_ids"]
        )
        self.assertIn("previous_ai_summary", envelope.payload["forbidden_source_ids"])
        self.assertTrue(envelope.payload["allowed_sources"][0]["text_preview"])

    def test_provider_identity_and_prompt_must_match_effective_server_decision(self):
        for provider in (
            RecordingProvider(provider_override="forged-provider"),
            RecordingProvider(model_override="forged-model"),
            RecordingProvider(prompt_override="forged-prompt"),
        ):
            with self.subTest(
                provider=provider.provider_override, model=provider.model_override
            ):
                run = self.runner(provider).submit_registered(
                    PROJECT_ID,
                    self.request(),
                    self.registry,
                )
                self.assertEqual("failed", run.status)
                self.assertTrue(
                    any("mismatch" in message for message in run.validation_errors),
                    run.validation_errors,
                )

    def test_provider_factory_identity_mismatch_is_denied_before_provider_run(self):
        provider = RecordingProvider()
        provider.provider_name = "unexpected-provider"
        factory = ProviderFactory(provider)
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "provider_mismatch_ai_runs.jsonl"),
            provider_factory=factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )

        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "provider configuration mismatch"
        ):
            runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        self.assertEqual(1, len(factory.calls))
        self.assertEqual([], provider.calls)

    def test_duplicate_requested_source_ids_are_denied_before_provider_factory(self):
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "duplicate_source_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "duplicate source_ids"):
            runner.submit_registered(
                PROJECT_ID,
                self.request(source_ids=[self.source_id, self.source_id]),
                self.registry,
            )

        self.assertEqual([], provider_factory.calls)

    def test_cross_module_source_id_collision_is_denied_before_provider_factory(self):
        conflicting = self.registered.model_copy(
            update={
                "entry": self.registered.entry.model_copy(
                    update={"module": "eligibility_review"}
                ),
                "spans": [
                    span.model_copy(update={"module": "eligibility_review"})
                    for span in self.registered.spans
                ],
            }
        )
        self.registry.store.append(conflicting)
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "ambiguous_source_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "ambiguous"):
            runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        self.assertEqual([], provider_factory.calls)

    def test_internal_source_requires_project_and_module_binding_before_provider_factory(
        self,
    ):
        provider_factory = LazyProviderFactory()
        runner = AiTaskRunner(
            self.repo,
            AiTaskStore(self.root / "internal_binding_ai_runs.jsonl"),
            provider_factory=provider_factory,
            policy_resolver=AiExecutionPolicyResolver(
                deployment_profile="local_private_clinical",
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            ),
        )
        forged_source = AiTaskSourceRef(
            source_id="forged_internal_source",
            source_type="protocol_section_selection",
            title="forged",
            locator="sections.1",
            text_preview="forged",
            project_id="proj_other_study",
            module="medical_writing",
        )
        request = AiTaskRequest(
            module="medical_writing",
            task_type="medical_writing_revision",
            prompt_version="medical_writing_revision_v1_4",
            allowed_sources=[forged_source],
        )

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "canonical project"):
            runner.submit_internal(PROJECT_ID, request)

        self.assertEqual([], provider_factory.calls)

    def test_legacy_run_store_is_atomically_rewritten_to_audit_safe_projection(self):
        provider = RecordingProvider(unsafe_evidence=True)
        runner = self.runner(provider)
        run = runner.submit_registered(PROJECT_ID, self.request(), self.registry)
        store_path = self.root / "ai_runs.jsonl"
        store_path.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        migrated = AiTaskStore(store_path)

        serialized = store_path.read_text(encoding="utf-8")
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn(self.registered.spans[0].text_preview, serialized)
        self.assertEqual(
            [run.run_id], [item.run_id for item in migrated.list_runs(PROJECT_ID)]
        )
        backups = list(self.root.glob("ai_runs.jsonl.pre_audit_safe.*.bak"))
        self.assertEqual(1, len(backups))
        backup_serialized = backups[0].read_text(encoding="utf-8")
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", backup_serialized)
        self.assertNotIn("/Users/", backup_serialized)
        self.assertNotIn(self.registered.spans[0].text_preview, backup_serialized)

    def test_persisted_and_public_run_projections_do_not_include_source_text_or_quotes(
        self,
    ):
        provider = RecordingProvider(unsafe_evidence=True)
        runner = self.runner(provider)
        run = runner.submit_registered(PROJECT_ID, self.request(), self.registry)

        persisted = (self.root / "ai_runs.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", persisted)
        self.assertNotIn("/Users/", persisted)
        self.assertNotIn(self.registered.spans[0].text_preview, persisted)

        public = public_ai_run(run)
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn("CONFIDENTIAL PATIENT TEXT", serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertFalse(
            any("text_preview" in source for source in public["input_sources"])
        )
        self.assertFalse(any("quote" in item for item in public["evidence_entries"]))
        self.assertEqual(
            {"output_hash", "top_level_keys", "finding_count", "evidence_span_count"},
            set(public["artifacts"][0]["payload"]),
        )

    def test_registered_source_execution_api_fails_closed_before_runner(self):
        runner = NeverCalledRunner()
        client = TestClient(app)
        with (
            patch("services.api.app.main.source_registry", self.registry),
            patch("services.api.app.main.ai_task_runner", runner),
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
        ):
            response = client.post(
                f"/api/projects/{PROJECT_ID}/ai-runs/from-sources",
                json=self.request().model_dump(mode="json"),
            )

        self.assertEqual(403, response.status_code, response.text)
        self.assertEqual(
            "monitoring_write_action_unconfigured",
            response.json()["detail"]["code"],
        )
        self.assertFalse(runner.called)

    def test_registered_source_execution_api_requires_server_principal(self):
        runner = NeverCalledRunner()
        client = TestClient(app)
        with patch("services.api.app.main.ai_task_runner", runner):
            response = client.post(
                f"/api/projects/{PROJECT_ID}/ai-runs/from-sources",
                json=self.request().model_dump(mode="json"),
            )

        self.assertEqual(503, response.status_code, response.text)
        self.assertEqual(
            "monitoring_principal_unavailable",
            response.json()["detail"]["code"],
        )
        self.assertFalse(runner.called)

    def test_ai_result_reads_fail_closed_before_runner_access(self):
        runner = Mock()
        client = TestClient(app)
        paths = (
            f"/api/projects/{PROJECT_ID}/ai-runs",
            f"/api/projects/{PROJECT_ID}/ai-runs/run_missing",
            f"/api/projects/{PROJECT_ID}/ai-runs/run_missing/artifacts",
        )
        with patch("services.api.app.main.ai_task_runner", runner):
            without_principal = [client.get(path) for path in paths]
        with (
            patch("services.api.app.main.ai_task_runner", runner),
            patch(
                "services.api.app.main.resolve_monitoring_principal_from_request",
                return_value=self._principal(),
            ),
        ):
            with_principal = [client.get(path) for path in paths]

        for response in without_principal:
            self.assertEqual(503, response.status_code, response.text)
            self.assertEqual(
                "monitoring_principal_unavailable",
                response.json()["detail"]["code"],
            )
        for response in with_principal:
            self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(
                "monitoring_read_action_unconfigured",
                response.json()["detail"]["code"],
            )
        runner.list_runs.assert_not_called()
        runner.get.assert_not_called()
        runner.artifacts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
