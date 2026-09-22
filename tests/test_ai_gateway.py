from __future__ import annotations

import sys
import subprocess
import unittest
from unittest.mock import patch
import http.client
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.ai_gateway import (  # noqa: E402
    ALIBABA_TOKEN_PLAN_API_KEY_ENV,
    ALIBABA_TOKEN_PLAN_BASE_URL,
    ALIBABA_TOKEN_PLAN_MODEL,
    ALIBABA_TOKEN_PLAN_PROVIDER,
    AiGatewayConfigurationError,
    AiPromptEnvelope,
    AiProviderRuntimeError,
    AiSourceRef,
    AiTaskSpec,
    AiTaskType,
    DisabledAiProvider,
    HermesCliAiProvider,
    OpenAICompatibleAiProvider,
    PromptRegistry,
    ai_gateway_status_from_env,
    configured_ai_provider_from_env,
    direct_deepseek_env,
    validate_ai_output,
)


class AiGatewayTests(unittest.TestCase):
    def source(self) -> AiSourceRef:
        return AiSourceRef(
            source_id="protocol_mgk10_v21_docx_p12",
            source_type="protocol_docx_span",
            title="MG-K10-SAR V2.1 研究方案",
            locator="docx:paragraph:120-150",
            text_preview="随机前需完成禁限用药洗脱。",
        )

    def picos_output(self) -> dict:
        return {
            "task_id": "task_picos_001",
            "task_type": "picos_design_coach",
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": "picos_design_coach_v0_1",
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": [],
            "findings": [
                {
                    "finding_id": "finding_picos_001",
                    "status": "supported",
                    "title": "主要终点选项需要医学确认",
                    "source_id": "protocol_mgk10_v21_docx_p12",
                    "evidence_span_ids": ["span_picos_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_picos_001",
                    "source_id": "protocol_mgk10_v21_docx_p12",
                    "locator": "docx:paragraph:120",
                    "quote": "主要终点拟为治疗期关键时间窗内 rTNSS 较基线变化。",
                }
            ],
            "uncertainties": [
                {"level": "medical_review", "description": "需医学经理选择终点选项。"}
            ],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "revision": {
                "anchor_type": "picos_outcome",
                "anchor_id": "primary_outcome",
                "proposal_text": "建议将主要终点表述为治疗期关键时间窗内 rTNSS 较基线变化。",
                "proposed_option_id": "outcome_rtnss_change",
                "rationale": "该表述与返回的方案证据一致，需医学经理决定是否采纳。",
                "evidence_span_ids": ["span_picos_001"],
            },
        }

    def test_prompt_envelope_forces_external_provider_and_source_boundaries(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_001",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
            forbidden_source_ids=["criteria_rules_md", "timeline_json_reference"],
        )

        envelope = PromptRegistry().build(spec)

        self.assertEqual("task_protocol_rules_001", envelope.task_id)
        self.assertIn("独立 AI provider", envelope.system_prompt)
        self.assertIn("不是 Codex", envelope.system_prompt)
        self.assertIn("不得生成空证据 finding", envelope.system_prompt)
        self.assertIn("forbidden_source_ids", envelope.system_prompt)
        self.assertEqual(
            ["criteria_rules_md", "timeline_json_reference"],
            envelope.payload["forbidden_source_ids"],
        )
        self.assertEqual(
            "protocol_mgk10_v21_docx_p12",
            envelope.payload["allowed_sources"][0]["source_id"],
        )
        self.assertIn(
            "needs_medical_confirmation", envelope.payload["required_output_keys"]
        )
        self.assertIn("output_schema", envelope.payload)
        self.assertIn("finding_id", envelope.payload["output_schema"]["findings"][0])
        self.assertIn("span_id", envelope.payload["output_schema"]["evidence_spans"][0])

    def test_prompt_registry_rejects_source_overlap(self):
        spec = AiTaskSpec(
            task_id="bad_task",
            task_type=AiTaskType.ELIGIBILITY_RULE_REVIEW,
            prompt_version="eligibility_rule_review_v0_1",
            allowed_sources=[self.source()],
            forbidden_source_ids=["protocol_mgk10_v21_docx_p12"],
        )

        with self.assertRaisesRegex(
            AiGatewayConfigurationError, "both allowed and forbidden"
        ):
            PromptRegistry().build(spec)

    def test_prompt_registry_supports_medical_related_evidence_design_data_analysis_tfl_safety_pv_tasks(
        self,
    ):
        for task_type in [
            AiTaskType.COMPETITIVE_INTELLIGENCE,
            AiTaskType.TFL_GENERATION_ASSIST,
            AiTaskType.SAFETY_CASE_MEDICAL_REVIEW,
        ]:
            with self.subTest(task_type=task_type.value):
                spec = AiTaskSpec(
                    task_id=f"task_{task_type.value}",
                    task_type=task_type,
                    prompt_version=f"{task_type.value}_v0_1",
                    allowed_sources=[self.source()],
                    forbidden_source_ids=["legacy_summary"],
                )
                envelope = PromptRegistry().build(spec)
                self.assertEqual(task_type.value, envelope.payload["task_type"])
                self.assertIn("allowed_sources", envelope.system_prompt)

    def test_prompt_registry_includes_exact_picos_revision_contract(self):
        spec = AiTaskSpec(
            task_id="task_picos_001",
            task_type=AiTaskType.PICOS_DESIGN_COACH,
            prompt_version="picos_design_coach_v0_1",
            allowed_sources=[self.source()],
        )

        envelope = PromptRegistry().build(spec)

        revision_contract = envelope.payload["task_specific_output_contract"][
            "revision"
        ]
        self.assertEqual(
            {
                "anchor_type",
                "anchor_id",
                "proposal_text",
                "proposed_option_id",
                "rationale",
                "evidence_span_ids",
            },
            set(revision_contract["required_keys"]),
        )
        self.assertFalse(revision_contract["additional_properties"])
        self.assertIn("AI建议修订", envelope.system_prompt)
        self.assertIn("只能使用 payload.allowed_sources", envelope.system_prompt)
        self.assertIn("不得直接覆盖任何 PICOS 决定", envelope.system_prompt)
        self.assertIn("等待医学用户操作", envelope.system_prompt)

    def test_disabled_provider_fails_explicitly(self):
        spec = AiTaskSpec(
            task_id="task_writing_001",
            task_type=AiTaskType.MEDICAL_WRITING_REVISION,
            prompt_version="medical_writing_revision_v0_1",
            allowed_sources=[self.source()],
        )
        envelope = PromptRegistry().build(spec)

        with self.assertRaisesRegex(AiGatewayConfigurationError, "not configured"):
            DisabledAiProvider().run(envelope)

    def test_medical_writing_revision_contract_is_in_primary_output_schema(self):
        spec = AiTaskSpec(
            task_id="task_writing_schema_001",
            task_type=AiTaskType.MEDICAL_WRITING_REVISION,
            prompt_version="medical_writing_revision_v1_4",
            allowed_sources=[self.source()],
            task_context={
                "revision_intent": "medical_writing_revision",
                "intent_label": "改写",
                "directional_goal": "在不改变事实的前提下规范表达。",
                "preservation_rules": ["不得新增事实。"],
                "candidate_count": 3,
                "candidate_blueprints": ["标准版", "精炼版", "保守版"],
            },
        )

        envelope = PromptRegistry().build(spec)

        self.assertIs(
            envelope.payload["output_schema"]["revision"],
            envelope.payload["task_specific_output_contract"]["revision"],
        )
        self.assertIn(
            "must be true",
            envelope.payload["output_schema"]["needs_medical_confirmation"],
        )
        self.assertIn(
            "shared_phase1_protocol_reference_corpus",
            envelope.system_prompt,
        )

    def test_medical_writing_revision_accepts_confirmed_plan_pin_and_rejects_unknown_context(self):
        base_context = {
            "revision_intent": "medical_writing_revision",
            "intent_label": "改写",
            "directional_goal": "在不改变事实的前提下规范表达。",
            "preservation_rules": ["不得新增事实。"],
            "candidate_count": 3,
            "candidate_blueprints": ["标准版", "精炼版", "保守版"],
        }
        plan_context = {
            **base_context,
            "protocol_assembly_plan": {
                "plan_id": "plan-001",
                "plan_revision": 2,
                "plan_sha256": "a" * 64,
            },
        }
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="task_writing_plan_pin",
                task_type=AiTaskType.MEDICAL_WRITING_REVISION,
                prompt_version="medical_writing_revision_v1_4",
                allowed_sources=[self.source()],
                task_context=plan_context,
            )
        )
        self.assertEqual(
            2,
            envelope.payload["task_context"]["protocol_assembly_plan"]["plan_revision"],
        )
        with self.assertRaisesRegex(
            AiGatewayConfigurationError, "task_context keys must match"
        ):
            PromptRegistry().build(
                AiTaskSpec(
                    task_id="task_writing_unknown_context",
                    task_type=AiTaskType.MEDICAL_WRITING_REVISION,
                    prompt_version="medical_writing_revision_v1_4",
                    allowed_sources=[self.source()],
                    task_context={**base_context, "unexpected": True},
                )
            )

    def test_writing_prompt_allows_only_contiguous_verbatim_reference_quotes(self):
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="task_medical_writing_revision",
                task_type=AiTaskType.MEDICAL_WRITING_REVISION,
                prompt_version="medical_writing_revision_v1_4",
                allowed_sources=[self.source()],
                task_context={},
            )
        )
        quote_contract = envelope.payload["output_schema"]["evidence_spans"][0]["quote"]
        self.assertIn("exact contiguous quote", quote_contract)
        self.assertIn("最短充分连续片段", envelope.system_prompt)
        self.assertIn("不得改写、翻译、拼接不连续句段", envelope.system_prompt)

    def test_translation_prompt_requires_complete_exact_source_quote(self):
        task_type = AiTaskType.REGULATORY_TRANSLATION_ZH
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id=f"task_{task_type.value}",
                task_type=task_type,
                prompt_version=f"{task_type.value}_v0_1",
                allowed_sources=[self.source()],
                task_context={
                    "glossary_version": "cms_regulatory_zh_v1",
                    "source_span_revision": "span_r1",
                    "document_sha256": "a" * 64,
                },
            )
        )
        quote_contract = envelope.payload["output_schema"]["evidence_spans"][0]["quote"]
        self.assertIn(
            "complete matching allowed_sources.text_preview exactly", quote_contract
        )
        self.assertIn("不得截短、改写、翻译", envelope.system_prompt)
        translation_contract = envelope.payload["output_schema"]["translation"]
        self.assertEqual(
            {
                "translated_text",
                "glossary_version",
                "rationale",
                "evidence_span_ids",
            },
            set(translation_contract["required_keys"]),
        )
        self.assertIn("最外层必须包含 translation 对象", envelope.system_prompt)

    def test_medical_writing_prompt_routes_tables_to_structured_designer(self):
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="task_writing_table_boundary",
                task_type=AiTaskType.MEDICAL_WRITING_REVISION,
                prompt_version="medical_writing_revision_v0_1",
                allowed_sources=[self.source()],
            )
        )

        self.assertIn("proposal_text不得包含Markdown表格语法", envelope.system_prompt)
        self.assertIn("结构化表格模板/设计器", envelope.system_prompt)

    def test_configured_ai_provider_from_env_returns_disabled_without_required_config(
        self,
    ):
        provider = configured_ai_provider_from_env({})

        self.assertIsInstance(provider, DisabledAiProvider)

    def test_openai_compatible_factory_applies_configured_timeout(self):
        provider = configured_ai_provider_from_env(
            {
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_BASE_URL": "https://provider.example/v1",
                "WORKBENCH_AI_API_KEY": "test-key",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
                "WORKBENCH_AI_PROVIDER": "buddy",
                "WORKBENCH_AI_TIMEOUT_SECONDS": "640",
            }
        )

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual(640.0, provider.timeout_seconds)

    def test_direct_deepseek_factory_uses_standard_secret_and_official_route(self):
        provider = configured_ai_provider_from_env(
            {
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "DEEPSEEK_API_KEY": "direct-test-key",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
                "WORKBENCH_AI_PROVIDER": "deepseek",
            }
        )

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual("https://api.deepseek.com/v1", provider.base_url)
        self.assertEqual("direct-test-key", provider.api_key)
        self.assertEqual("deepseek-v4-pro", provider.expected_response_model)

    def test_direct_deepseek_prefers_dedicated_secret_over_global_provider_secret(self):
        provider = configured_ai_provider_from_env(
            {
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_API_KEY": "other-provider-key",
                "DEEPSEEK_API_KEY": "direct-test-key",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
                "WORKBENCH_AI_PROVIDER": "deepseek",
            }
        )

        self.assertEqual("direct-test-key", provider.api_key)

    def test_qwen38_factory_uses_pinned_token_plan_route_and_dedicated_secret(self):
        provider = configured_ai_provider_from_env(
            {
                ALIBABA_TOKEN_PLAN_API_KEY_ENV: "qwen-test-key",
                "WORKBENCH_AI_MODEL": ALIBABA_TOKEN_PLAN_MODEL,
                "WORKBENCH_AI_PROVIDER": ALIBABA_TOKEN_PLAN_PROVIDER,
            }
        )

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual(ALIBABA_TOKEN_PLAN_BASE_URL, provider.base_url)
        self.assertEqual("qwen-test-key", provider.api_key)
        self.assertEqual(ALIBABA_TOKEN_PLAN_MODEL, provider.expected_response_model)

    def test_qwen38_factory_accepts_legacy_token_plan_secret_alias(self):
        provider = configured_ai_provider_from_env(
            {
                "ALIBABA_CODING_PLAN_API_KEY": "legacy-qwen-test-key",
                "WORKBENCH_AI_MODEL": ALIBABA_TOKEN_PLAN_MODEL,
                "WORKBENCH_AI_PROVIDER": ALIBABA_TOKEN_PLAN_PROVIDER,
            }
        )

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual("legacy-qwen-test-key", provider.api_key)

    def test_qwen38_factory_rejects_unpinned_endpoint_or_model(self):
        common = {
            ALIBABA_TOKEN_PLAN_API_KEY_ENV: "qwen-test-key",
            "WORKBENCH_AI_PROVIDER": ALIBABA_TOKEN_PLAN_PROVIDER,
        }

        wrong_endpoint = configured_ai_provider_from_env(
            {
                **common,
                "WORKBENCH_AI_BASE_URL": "https://proxy.example/v1",
                "WORKBENCH_AI_MODEL": ALIBABA_TOKEN_PLAN_MODEL,
            }
        )
        wrong_model = configured_ai_provider_from_env(
            {
                **common,
                "WORKBENCH_AI_MODEL": "qwen3.7-max",
            }
        )

        self.assertIsInstance(wrong_endpoint, DisabledAiProvider)
        self.assertIsInstance(wrong_model, DisabledAiProvider)

    def test_direct_deepseek_env_overrides_global_qwen_route(self):
        values = direct_deepseek_env(
            "deepseek-v4-flash",
            {
                "WORKBENCH_AI_PROVIDER": ALIBABA_TOKEN_PLAN_PROVIDER,
                "WORKBENCH_AI_MODEL": ALIBABA_TOKEN_PLAN_MODEL,
                "WORKBENCH_AI_BASE_URL": ALIBABA_TOKEN_PLAN_BASE_URL,
            },
        )

        self.assertEqual("deepseek", values["WORKBENCH_AI_PROVIDER"])
        self.assertEqual("deepseek-v4-flash", values["WORKBENCH_AI_MODEL"])
        self.assertEqual("https://api.deepseek.com/v1", values["WORKBENCH_AI_BASE_URL"])

    def test_direct_deepseek_factory_rejects_hermes_or_model_alias(self):
        common = {
            "DEEPSEEK_API_KEY": "direct-test-key",
            "WORKBENCH_AI_PROVIDER": "deepseek",
        }

        hermes = configured_ai_provider_from_env(
            {
                **common,
                "WORKBENCH_AI_TRANSPORT": "hermes_cli",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
            }
        )
        alias = configured_ai_provider_from_env(
            {
                **common,
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_MODEL": "deepseek-chat",
            }
        )

        self.assertIsInstance(hermes, DisabledAiProvider)
        self.assertIsInstance(alias, DisabledAiProvider)

    def test_direct_deepseek_factory_accepts_pinned_translation_flash_model(self):
        provider = configured_ai_provider_from_env(
            {
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "DEEPSEEK_API_KEY": "direct-test-key",
                "WORKBENCH_AI_MODEL": "deepseek-v4-flash",
                "WORKBENCH_AI_PROVIDER": "deepseek",
            }
        )

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual("deepseek-v4-flash", provider.model_name)
        self.assertEqual("deepseek-v4-flash", provider.expected_response_model)

    def test_direct_deepseek_status_requires_exact_product_route(self):
        status = ai_gateway_status_from_env(
            {
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "DEEPSEEK_API_KEY": "direct-test-key",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
                "WORKBENCH_AI_PROVIDER": "deepseek",
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            }
        )

        self.assertTrue(status["configured"])
        self.assertTrue(status["semantic_ai_tasks_enabled"])
        self.assertTrue(status["response_model_identity_required"])
        self.assertEqual([], status["route_validation_errors"])
        self.assertIn("DEEPSEEK_API_KEY", status["required_env"])
        self.assertNotIn("WORKBENCH_AI_HERMES_PROVIDER", status["required_env"])

    def test_qwen38_status_requires_exact_product_route_without_secret_exposure(self):
        status = ai_gateway_status_from_env(
            {
                ALIBABA_TOKEN_PLAN_API_KEY_ENV: "qwen-test-key",
                "WORKBENCH_AI_PROVIDER": ALIBABA_TOKEN_PLAN_PROVIDER,
                "WORKBENCH_AI_MODEL": ALIBABA_TOKEN_PLAN_MODEL,
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            }
        )

        self.assertTrue(status["configured"])
        self.assertTrue(status["semantic_ai_tasks_enabled"])
        self.assertTrue(status["response_model_identity_required"])
        self.assertEqual(ALIBABA_TOKEN_PLAN_PROVIDER, status["provider"])
        self.assertEqual(ALIBABA_TOKEN_PLAN_MODEL, status["model"])
        self.assertIn(ALIBABA_TOKEN_PLAN_API_KEY_ENV, status["required_env"])
        self.assertNotIn("qwen-test-key", json.dumps(status, ensure_ascii=False))

    def test_qwen38_status_names_missing_dedicated_secret(self):
        status = ai_gateway_status_from_env(
            {
                "WORKBENCH_AI_PROVIDER": ALIBABA_TOKEN_PLAN_PROVIDER,
                "WORKBENCH_AI_MODEL": ALIBABA_TOKEN_PLAN_MODEL,
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            }
        )

        self.assertFalse(status["configured"])
        self.assertIn(ALIBABA_TOKEN_PLAN_API_KEY_ENV, status["missing_env"])
        self.assertNotIn("WORKBENCH_AI_API_KEY", status["missing_env"])

    def test_ai_gateway_status_is_explicitly_disabled_without_external_provider(self):
        status = ai_gateway_status_from_env({})

        self.assertFalse(status["configured"])
        self.assertFalse(status["semantic_ai_tasks_enabled"])
        self.assertFalse(status["codex_runtime_dependency"])
        self.assertEqual("not_configured", status["model"])
        self.assertEqual(
            [
                "WORKBENCH_AI_BASE_URL",
                "WORKBENCH_AI_API_KEY",
                "WORKBENCH_AI_MODEL",
                "WORKBENCH_AI_DEPLOYMENT_PROFILE",
            ],
            status["missing_env"],
        )

    def test_ai_gateway_status_reports_configured_external_model_without_secret(self):
        status = ai_gateway_status_from_env(
            {
                "WORKBENCH_AI_BASE_URL": "https://ai.example.test/v1",
                "WORKBENCH_AI_API_KEY": "secret-value",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
                "WORKBENCH_AI_PROVIDER": "buddy",
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "approved_private_clinical",
            }
        )

        self.assertTrue(status["configured"])
        self.assertTrue(status["semantic_ai_tasks_enabled"])
        self.assertFalse(status["codex_runtime_dependency"])
        self.assertEqual("buddy", status["provider"])
        self.assertEqual("deepseek-v4-pro", status["model"])
        self.assertEqual("approved_private_clinical", status["deployment_profile"])
        self.assertNotIn("secret-value", json.dumps(status, ensure_ascii=False))

    @patch(
        "services.api.app.ai_gateway.shutil.which", return_value="/usr/local/bin/hermes"
    )
    def test_ai_gateway_status_supports_hermes_cli_without_copying_provider_secret(
        self, _which
    ):
        status = ai_gateway_status_from_env(
            {
                "WORKBENCH_AI_TRANSPORT": "hermes_cli",
                "WORKBENCH_AI_HERMES_PROVIDER": "buddy",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
                "WORKBENCH_AI_PROVIDER": "buddy",
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "approved_private_documents",
            }
        )

        self.assertTrue(status["configured"])
        self.assertTrue(status["semantic_ai_tasks_enabled"])
        self.assertEqual("hermes_cli", status["transport"])
        self.assertEqual("buddy", status["hermes_provider"])
        self.assertEqual([], status["missing_env"])

    @patch(
        "services.api.app.ai_gateway.shutil.which", return_value="/usr/local/bin/hermes"
    )
    @patch("services.api.app.ai_gateway.subprocess.run")
    def test_hermes_cli_provider_uses_isolated_bounded_turns_and_parses_final_json(
        self, run, _which
    ):
        expected = self.picos_output()
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout="reasoning trace\nsession_id: test-session\n"
            + json.dumps(expected, ensure_ascii=False),
            stderr="",
        )
        provider = HermesCliAiProvider(
            hermes_provider="buddy",
            model_name="deepseek-v4-pro",
            provider_name="buddy",
        )
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="task_picos_001",
                task_type=AiTaskType.PICOS_DESIGN_COACH,
                prompt_version="picos_design_coach_v0_1",
                allowed_sources=[self.source()],
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            )
        )

        self.assertEqual(expected, provider.run(envelope))
        command = run.call_args.args[0]
        self.assertIn("--ignore-rules", command)
        self.assertIn("--max-turns", command)
        self.assertEqual("1", command[command.index("--max-turns") + 1])
        self.assertEqual("buddy", command[command.index("--provider") + 1])
        self.assertEqual("deepseek-v4-pro", command[command.index("--model") + 1])

    @patch(
        "services.api.app.ai_gateway.shutil.which", return_value="/usr/local/bin/hermes"
    )
    @patch("services.api.app.ai_gateway.subprocess.run")
    def test_hermes_cli_timeout_does_not_leak_prompt_or_command(self, run, _which):
        run.side_effect = subprocess.TimeoutExpired(
            cmd=["hermes", "chat", "--query", "sensitive clinical source"],
            timeout=300,
        )
        provider = HermesCliAiProvider(
            hermes_provider="buddy",
            model_name="deepseek-v4-pro",
            provider_name="buddy",
        )
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="task_picos_001",
                task_type=AiTaskType.PICOS_DESIGN_COACH,
                prompt_version="picos_design_coach_v0_1",
                allowed_sources=[self.source()],
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            )
        )

        with self.assertRaises(AiProviderRuntimeError) as raised:
            provider.run(envelope)
        self.assertEqual(
            "Hermes CLI request timed out after 300 seconds",
            str(raised.exception),
        )
        self.assertNotIn("sensitive clinical source", str(raised.exception))

    @patch(
        "services.api.app.ai_gateway.shutil.which", return_value="/usr/local/bin/hermes"
    )
    @patch("services.api.app.ai_gateway.subprocess.run")
    def test_hermes_cli_provider_parses_code_fenced_json_after_trace(self, run, _which):
        expected = self.picos_output()
        run.return_value = SimpleNamespace(
            returncode=0,
            stdout=(
                "trace {not-json}\n```json\n"
                + json.dumps(expected, ensure_ascii=False)
                + "\n```\n"
            ),
            stderr="",
        )
        provider = HermesCliAiProvider(
            hermes_provider="buddy",
            model_name="deepseek-v4-pro",
            provider_name="buddy",
        )
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="task_picos_001",
                task_type=AiTaskType.PICOS_DESIGN_COACH,
                prompt_version="picos_design_coach_v0_1",
                allowed_sources=[self.source()],
                provider_name="buddy",
                model_name="deepseek-v4-pro",
            )
        )

        self.assertEqual(expected, provider.run(envelope))

    def test_openai_compatible_provider_sends_prompt_envelope_and_parses_json(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_001",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )
        envelope = PromptRegistry().build(spec)
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            provider_name="buddy",
            timeout_seconds=1,
        )
        provider_payload = {
            "task_id": "task_protocol_rules_001",
            "task_type": "protocol_rule_extraction",
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": "protocol_rule_extraction_v0_1",
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }

        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "```json\n"
                                + json.dumps(provider_payload, ensure_ascii=False)
                                + "\n```"
                            }
                        }
                    ]
                }
            )
            result = provider.run(envelope)

        self.assertEqual(provider_payload, result)
        request = urlopen.call_args.args[0]
        self.assertEqual(
            "https://ai.example.test/v1/chat/completions", request.full_url
        )
        self.assertEqual("Bearer test-key", request.headers["Authorization"])
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual("deepseek-v4-pro", body["model"])
        self.assertIn("不是 Codex", body["messages"][0]["content"])
        self.assertEqual("user", body["messages"][1]["role"])
        self.assertNotIn("thinking", body)

    def test_opencode_go_provider_sends_required_transport_identity_headers(self):
        envelope = PromptRegistry().build(
            AiTaskSpec(
                task_id="task_opencode_go_001",
                task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
                prompt_version="protocol_rule_extraction_v0_1",
                allowed_sources=[self.source()],
            )
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://opencode.ai/zen/go/v1",
            api_key="test-key",
            model_name="deepseek-v4.1-flash",
            provider_name="opencode-go",
            timeout_seconds=1,
        )
        provider_payload = {
            "task_id": envelope.task_id,
            "task_type": envelope.task_type.value,
            "provider": "opencode-go",
            "model": "deepseek-v4.1-flash",
            "prompt_version": envelope.prompt_version,
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }
        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "model": "deepseek-v4.1-flash",
                    "choices": [{"message": {"content": json.dumps(provider_payload)}}],
                }
            )
            provider.run(envelope)

        request = urlopen.call_args.args[0]
        self.assertEqual("omp/medical-writing-protocol-v3", request.headers["User-agent"])
        self.assertRegex(request.headers["X-opencode-session"], r"^[0-9a-f-]{36}$")

    def test_opencode_go_factory_resolves_omp_credential_environment(self):
        provider = configured_ai_provider_from_env(
            {
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_PROVIDER": "opencode-go",
                "WORKBENCH_AI_MODEL": "deepseek-v4.1-flash",
                "WORKBENCH_AI_BASE_URL": "https://opencode.ai/zen/go/v1",
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "deepseek-v4.1-flash",
                "OPENCODE_API_KEY": "omp-owned-test-key",
            }
        )

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual("omp-owned-test-key", provider.api_key)
        self.assertEqual("deepseek-v4.1-flash", provider.model_name)

    def test_openai_compatible_provider_can_disable_thinking_per_envelope(self):
        envelope = AiPromptEnvelope(
            task_id="task_flash_qc",
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version="flash_integration_qc_v0_1",
            system_prompt="Return JSON.",
            payload={"source_text": "Source", "translated_text": "译文"},
            thinking="disabled",
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
            model_name="deepseek-v4-flash",
            timeout_seconds=1,
        )
        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {"choices": [{"message": {"content": '{"passed":true}'}}]}
            )
            self.assertEqual({"passed": True}, provider.run(envelope))

        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual({"type": "disabled"}, body["thinking"])

    def test_role_defaults_override_hardcoded_envelope_reasoning_options(self):
        envelope = AiPromptEnvelope(
            task_id="task_role_options",
            task_type=AiTaskType.PICOS_DESIGN_COACH,
            prompt_version="picos_design_coach_v0_1",
            system_prompt="Return JSON.",
            payload={"value": "x"},
            thinking="disabled",
            reasoning_effort="low",
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
            model_name="deepseek-v4-flash",
            timeout_seconds=1,
            default_thinking="enabled",
            default_reasoning_effort="xhigh",
        )
        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {"choices": [{"message": {"content": '{"ok":true}'}}]}
            )
            self.assertEqual({"ok": True}, provider.run(envelope))

        body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual({"type": "enabled"}, body["thinking"])
        self.assertEqual("xhigh", body["reasoning_effort"])

    def test_openai_compatible_provider_retries_incomplete_response(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_retry",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
        )
        provider_payload = {
            "task_id": "task_protocol_rules_retry",
            "task_type": "protocol_rule_extraction",
            "provider": "openai_compatible",
            "model": "deepseek-v4-pro",
            "prompt_version": "protocol_rule_extraction_v0_1",
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }

        with (
            patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen,
            patch("services.api.app.ai_gateway.time.sleep") as sleep,
            patch("services.api.app.ai_gateway.random.uniform", return_value=0.0),
        ):
            urlopen.side_effect = [
                http.client.IncompleteRead(b""),
                _FakeResponse(
                    {
                        "choices": [
                            {"message": {"content": json.dumps(provider_payload)}}
                        ]
                    }
                ),
            ]
            result = provider.run(PromptRegistry().build(spec))

        self.assertEqual(provider_payload, result)
        self.assertEqual(2, urlopen.call_count)
        sleep.assert_called_once_with(0.5)

    def test_openai_compatible_provider_stops_after_bounded_transient_retries(self):
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
        )
        spec = AiTaskSpec(
            task_id="task_protocol_rules_retry_exhausted",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )

        with (
            patch(
                "services.api.app.ai_gateway.urllib.request.urlopen",
                side_effect=http.client.IncompleteRead(b""),
            ) as urlopen,
            patch("services.api.app.ai_gateway.time.sleep") as sleep,
            patch("services.api.app.ai_gateway.random.uniform", return_value=0.0),
        ):
            with self.assertRaisesRegex(
                AiProviderRuntimeError, "after bounded retries"
            ):
                provider.run(PromptRegistry().build(spec))

        self.assertEqual(3, urlopen.call_count)
        self.assertEqual(
            [unittest.mock.call(0.5), unittest.mock.call(1.0)], sleep.call_args_list
        )

    def test_openai_compatible_provider_retries_retryable_http_status(self):
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
        )
        envelope = AiPromptEnvelope(
            task_id="task_retry_http_429",
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version="flash_integration_qc_v0_1",
            system_prompt="Return JSON.",
            payload={"source_text": "Source", "translated_text": "译文"},
            thinking="disabled",
        )
        retryable = urllib.error.HTTPError(
            "https://ai.example.test/v1/chat/completions",
            429,
            "rate limited",
            None,
            None,
        )
        with (
            patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen,
            patch("services.api.app.ai_gateway.time.sleep") as sleep,
            patch("services.api.app.ai_gateway.random.uniform", return_value=0.0),
        ):
            urlopen.side_effect = [
                retryable,
                _FakeResponse(
                    {"choices": [{"message": {"content": '{"passed":true}'}}]}
                ),
            ]
            self.assertEqual({"passed": True}, provider.run(envelope))

        self.assertEqual(2, urlopen.call_count)
        sleep.assert_called_once_with(0.5)

    def test_openai_compatible_provider_does_not_retry_non_retryable_http_status(self):
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
        )
        envelope = AiPromptEnvelope(
            task_id="task_no_retry_http_400",
            task_type=AiTaskType.REGULATORY_TRANSLATION_ZH,
            prompt_version="flash_integration_qc_v0_1",
            system_prompt="Return JSON.",
            payload={"source_text": "Source", "translated_text": "译文"},
            thinking="disabled",
        )
        non_retryable = urllib.error.HTTPError(
            "https://ai.example.test/v1/chat/completions",
            400,
            "bad request",
            None,
            None,
        )
        with (
            patch(
                "services.api.app.ai_gateway.urllib.request.urlopen",
                side_effect=non_retryable,
            ) as urlopen,
            patch("services.api.app.ai_gateway.time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(AiProviderRuntimeError, "HTTP 400"):
                provider.run(envelope)

        self.assertEqual(1, urlopen.call_count)
        sleep.assert_not_called()

    def test_openai_compatible_provider_rejects_non_json_content(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_001",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
        )

        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {"choices": [{"message": {"content": "not json"}}]}
            )
            with self.assertRaisesRegex(AiProviderRuntimeError, "not valid JSON"):
                provider.run(PromptRegistry().build(spec))

    def test_openai_compatible_provider_preserves_safe_empty_content_diagnostics(self):
        envelope = AiPromptEnvelope(
            task_id="task_empty_final_content",
            task_type=AiTaskType.COMPETITIVE_INTELLIGENCE,
            prompt_version="corpus_analysis_v11",
            system_prompt="Return a JSON object in message.content.",
            payload={"value": "x"},
            thinking="enabled",
            reasoning_effort="xhigh",
            max_output_tokens=32_768,
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-flash",
            provider_name="deepseek",
            expected_response_model="deepseek-v4-flash",
            timeout_seconds=1,
        )
        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": "",
                                "reasoning_content": "先核对证据层级。",
                            },
                        }
                    ],
                }
            )
            with self.assertRaisesRegex(
                AiProviderRuntimeError, "provider_response_empty"
            ) as raised:
                provider.run(envelope)

        diagnostics = raised.exception.diagnostics
        self.assertEqual("provider_response_empty", diagnostics["failure_code"])
        self.assertEqual("json", diagnostics["wire_format"])
        self.assertEqual(0, diagnostics["message_content_chars"])
        self.assertGreater(diagnostics["message_reasoning_content_chars"], 0)
        self.assertEqual("deepseek-v4-flash", provider.response_model)
        self.assertNotIn("response_body", diagnostics)
        self.assertEqual(64, len(diagnostics["response_sha256"]))

    def test_empty_completion_without_model_is_transient_not_identity_mismatch(self):
        envelope = AiPromptEnvelope(
            task_id="task_empty_missing_model",
            task_type=AiTaskType.COMPETITIVE_INTELLIGENCE,
            prompt_version="corpus_analysis_v11",
            system_prompt="Return JSON.",
            payload={"value": "x"},
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-flash",
            provider_name="deepseek",
            expected_response_model="deepseek-v4-flash",
            timeout_seconds=1,
            max_attempts=1,
        )
        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {"choices": [{"message": {"content": ""}}]}
            )
            with self.assertRaises(AiProviderRuntimeError) as raised:
                provider.run(envelope)

        self.assertEqual(
            "provider_response_empty",
            raised.exception.diagnostics["failure_code"],
        )

    def test_openai_compatible_provider_retries_transient_empty_final_content(self):
        envelope = AiPromptEnvelope(
            task_id="task_empty_then_complete",
            task_type=AiTaskType.COMPETITIVE_INTELLIGENCE,
            prompt_version="corpus_analysis_v11",
            system_prompt="Return one JSON object.",
            payload={"value": "x"},
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4.1-flash",
            provider_name="opencode-go",
            expected_response_model="deepseek-v4.1-flash",
            timeout_seconds=1,
            max_attempts=2,
        )
        empty = _FakeResponse(
            {
                "model": "deepseek-v4.1-flash",
                "choices": [{"finish_reason": "stop", "message": {"content": ""}}],
            }
        )
        complete = _FakeResponse(
            {
                "model": "deepseek-v4.1-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": json.dumps({"status": "ok"})},
                    }
                ],
            }
        )
        with patch(
            "services.api.app.ai_gateway.urllib.request.urlopen",
            side_effect=[empty, complete],
        ) as urlopen, patch("services.api.app.ai_gateway.time.sleep"):
            result = provider.run(envelope)

        self.assertEqual({"status": "ok"}, result)
        self.assertEqual(2, urlopen.call_count)

    def test_openai_compatible_provider_accepts_json_wrapped_by_thinking_text(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_wrapped_json",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            timeout_seconds=1,
        )
        expected = {
            "response_text": "已完成结构化拆解",
            "proposals": [],
            "questions": [],
        }
        wrapped = (
            "<think>核对字段白名单和输出结构。</think>\n"
            "以下为结构化结果：\n"
            f"{json.dumps(expected, ensure_ascii=False)}\n"
            "请按系统规则继续校验。"
        )

        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {"choices": [{"message": {"content": wrapped}}]}
            )
            result = provider.run(PromptRegistry().build(spec))

        self.assertEqual(expected, result)

    def test_openai_compatible_provider_rejects_response_model_mismatch(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_model_identity",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            provider_name="deepseek",
            expected_response_model="deepseek-v4-pro",
            timeout_seconds=1,
        )

        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "model": "deepseek-v4-flash",
                    "choices": [
                        {"message": {"content": json.dumps(self.picos_output())}}
                    ],
                }
            )
            with self.assertRaisesRegex(AiProviderRuntimeError, "model identity"):
                provider.run(PromptRegistry().build(spec))
        # A mismatched response is rejected, but its actual model identity is
        # retained so the failed call remains auditable.
        self.assertEqual("deepseek-v4-flash", provider.response_model)

    def test_openai_compatible_provider_exposes_only_successfully_verified_response_model(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_verified_model_identity",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://api.deepseek.com/v1",
            api_key="test-key",
            model_name="deepseek-v4-pro",
            provider_name="deepseek",
            expected_response_model="deepseek-v4-pro",
            timeout_seconds=1,
        )
        self.assertEqual("openai_compatible", provider.transport_name)
        self.assertEqual("", provider.response_model)

        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeResponse(
                {
                    "model": "deepseek-v4-pro",
                    "choices": [
                        {"message": {"content": json.dumps(self.picos_output())}}
                    ],
                }
            )
            result = provider.run(PromptRegistry().build(spec))

        self.assertEqual(self.picos_output(), result)
        self.assertEqual("deepseek-v4-pro", provider.response_model)

    def test_openai_compatible_provider_parses_streaming_sse_response(self):
        spec = AiTaskSpec(
            task_id="task_protocol_rules_sse",
            task_type=AiTaskType.PROTOCOL_RULE_EXTRACTION,
            prompt_version="protocol_rule_extraction_v0_1",
            allowed_sources=[self.source()],
        )
        provider = OpenAICompatibleAiProvider(
            base_url="https://ai.example.test/v1",
            api_key="test-key",
            model_name="glm-5.2",
            provider_name="buddy",
            timeout_seconds=1,
        )
        output = {
            "task_id": "task_protocol_rules_sse",
            "task_type": "protocol_rule_extraction",
            "provider": "buddy",
            "model": "glm-5.2",
            "prompt_version": "protocol_rule_extraction_v0_1",
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [],
            "uncertainties": [],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }
        content = json.dumps(output, ensure_ascii=False)
        midpoint = len(content) // 2
        sse = "\n".join(
            [
                "data: "
                + json.dumps({"choices": [{"delta": {"content": content[:midpoint]}}]}),
                "",
                "data: "
                + json.dumps({"choices": [{"delta": {"content": content[midpoint:]}}]}),
                "",
                "data: [DONE]",
                "",
            ]
        )

        with patch("services.api.app.ai_gateway.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _FakeRawResponse(sse)
            result = provider.run(PromptRegistry().build(spec))

        self.assertEqual(output, result)

    def test_validate_ai_output_requires_schema_keys_and_types(self):
        valid = {
            "task_id": "task_001",
            "task_type": "protocol_rule_extraction",
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": "protocol_rule_extraction_v0_1",
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": ["criteria_rules_md"],
            "findings": [
                {
                    "finding_id": "finding_001",
                    "status": "supported",
                    "title": "示例规则候选",
                    "source_id": "protocol_mgk10_v21_docx_p12",
                    "evidence_span_ids": ["span_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_001",
                    "source_id": "protocol_mgk10_v21_docx_p12",
                    "locator": "docx:paragraph:120",
                    "quote": "随机前需完成禁限用药洗脱。",
                }
            ],
            "uncertainties": [{"level": "data_gap", "description": "需后续医学确认。"}],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }
        self.assertEqual([], validate_ai_output(valid))

        invalid = dict(valid)
        invalid.pop("evidence_spans")
        invalid["findings"] = "not-list"
        self.assertIn(
            "missing required key: evidence_spans", validate_ai_output(invalid)
        )

    def test_validate_ai_output_reports_unhashable_wrong_types_without_crashing(self):
        invalid = {
            "task_id": "task_bad_types",
            "task_type": ["protocol_rule_extraction"],
            "provider": "buddy",
            "model": "glm-5.2",
            "prompt_version": "protocol_rule_extraction_v0_1",
            "input_source_ids": ["source_001"],
            "forbidden_source_ids": [],
            "findings": [
                {
                    "finding_id": "finding_001",
                    "status": "supported",
                    "title": "bad source type",
                    "source_id": ["source_001"],
                    "evidence_span_ids": ["span_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_001",
                    "source_id": ["source_001"],
                    "locator": "docx:p1",
                    "quote": "text",
                }
            ],
            "uncertainties": [],
            "needs_medical_confirmation": [True],
            "schema_version": ["ai_task_output_v0_1"],
        }

        errors = validate_ai_output(invalid)

        self.assertTrue(any("task_type must be" in error for error in errors))
        self.assertTrue(any("schema_version must be" in error for error in errors))
        self.assertIn("needs_medical_confirmation must be boolean", errors)
        self.assertTrue(
            any("source_id must be a non-empty string" in error for error in errors)
        )

    def test_validate_ai_output_rejects_unbound_or_forbidden_evidence(self):
        invalid = {
            "task_id": "task_001",
            "task_type": "protocol_rule_extraction",
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": "protocol_rule_extraction_v0_1",
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": ["criteria_rules_md"],
            "findings": [
                {
                    "finding_id": "finding_001",
                    "status": "supported",
                    "title": "伪造规则候选",
                    "source_id": "criteria_rules_md",
                    "evidence_span_ids": ["missing_span"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_001",
                    "source_id": "criteria_rules_md",
                    "locator": "markdown:line:1",
                    "quote": "旧规则文件内容。",
                }
            ],
            "uncertainties": ["not-structured"],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
        }

        errors = validate_ai_output(invalid)

        self.assertIn(
            "findings[0].source_id is not in input_source_ids: criteria_rules_md",
            errors,
        )
        self.assertIn(
            "findings[0].source_id references forbidden source: criteria_rules_md",
            errors,
        )
        self.assertIn(
            "evidence_spans[0].source_id is not in input_source_ids: criteria_rules_md",
            errors,
        )
        self.assertIn(
            "evidence_spans[0].source_id references forbidden source: criteria_rules_md",
            errors,
        )
        self.assertIn(
            "findings[0] references unknown evidence_span_id: missing_span", errors
        )
        self.assertIn("uncertainties[0] must be an object", errors)

    def test_validate_picos_revision_accepts_exact_operational_contract(self):
        self.assertEqual([], validate_ai_output(self.picos_output()))

    def test_validate_picos_revision_rejects_missing_extra_or_empty_fields(self):
        missing_revision = self.picos_output()
        missing_revision.pop("revision")
        self.assertIn(
            "picos_design_coach output requires revision object",
            validate_ai_output(missing_revision),
        )

        for key in [
            "anchor_type",
            "anchor_id",
            "proposal_text",
            "proposed_option_id",
            "rationale",
            "evidence_span_ids",
        ]:
            with self.subTest(missing_key=key):
                output = self.picos_output()
                output["revision"].pop(key)
                self.assertIn(
                    f"revision missing required key: {key}", validate_ai_output(output)
                )

        unexpected = self.picos_output()
        unexpected["revision"]["diff_patch"] = "not part of the PICOS contract"
        self.assertIn(
            "revision contains unexpected key: diff_patch",
            validate_ai_output(unexpected),
        )

        for key in [
            "anchor_type",
            "anchor_id",
            "proposal_text",
            "proposed_option_id",
            "rationale",
        ]:
            with self.subTest(empty_key=key):
                output = self.picos_output()
                output["revision"][key] = "  "
                self.assertIn(
                    f"revision.{key} must be a non-empty string",
                    validate_ai_output(output),
                )

        empty_evidence = self.picos_output()
        empty_evidence["revision"]["evidence_span_ids"] = []
        self.assertIn(
            "revision.evidence_span_ids must be a non-empty list of strings",
            validate_ai_output(empty_evidence),
        )

        not_pending = self.picos_output()
        not_pending["needs_medical_confirmation"] = False
        self.assertIn(
            "picos_design_coach requires needs_medical_confirmation=true",
            validate_ai_output(not_pending),
        )

    def test_validate_picos_revision_rejects_unbound_evidence_paths_and_overclaims(
        self,
    ):
        unbound = self.picos_output()
        unbound["revision"]["evidence_span_ids"] = ["missing_span"]
        self.assertIn(
            "revision references unknown evidence_span_id: missing_span",
            validate_ai_output(unbound),
        )

        local_path = self.picos_output()
        local_path["revision"]["proposal_text"] = (
            "参考 /Users/example/Desktop/picos.txt。"
        )
        self.assertTrue(
            any("local path" in error for error in validate_ai_output(local_path))
        )

        for overclaim_text in [
            "该决定已医学批准。",
            "该决定可正式提交监管。",
            "无需人工复核。",
        ]:
            with self.subTest(overclaim_text=overclaim_text):
                overclaim = self.picos_output()
                overclaim["revision"]["rationale"] = overclaim_text
                self.assertTrue(
                    any(
                        "forbidden PICOS revision claim" in error
                        for error in validate_ai_output(overclaim)
                    )
                )

    def test_validate_medical_writing_revision_requires_revision_contract(self):
        output = {
            "task_id": "task_revision_001",
            "task_type": "medical_writing_revision",
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": "medical_writing_revision_v0_1",
            "input_source_ids": ["protocol_mgk10_v21_docx_p12"],
            "forbidden_source_ids": [],
            "findings": [
                {
                    "finding_id": "finding_revision_001",
                    "status": "supported",
                    "title": "主要终点表述可更贴近方案正文",
                    "source_id": "protocol_mgk10_v21_docx_p12",
                    "evidence_span_ids": ["span_revision_001"],
                }
            ],
            "evidence_spans": [
                {
                    "span_id": "span_revision_001",
                    "source_id": "protocol_mgk10_v21_docx_p12",
                    "locator": "docx:paragraph:120",
                    "quote": "主要终点拟为治疗期关键时间窗内 rTNSS 较基线变化。",
                }
            ],
            "uncertainties": [
                {"level": "medical_review", "description": "需医学经理确认终点措辞。"}
            ],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "revision": {
                "proposal_text": "主要终点为治疗期关键时间窗内 rTNSS 较基线的变化。",
                "diff_patch": "- 主要终点拟为治疗期关键时间窗内 rTNSS 较基线变化。\n+ 主要终点为治疗期关键时间窗内 rTNSS 较基线的变化。",
                "rationale": "将拟为调整为方案正文中更确定的终点描述，仍需医学批准。",
                "evidence_span_ids": ["span_revision_001"],
                "alternatives": [
                    {
                        "proposal_text": "主要疗效终点为治疗期关键时间窗内 rTNSS 相对基线的变化。",
                        "diff_patch": "替代版本 2",
                        "rationale": "突出主要疗效终点属性。",
                        "evidence_span_ids": ["span_revision_001"],
                    },
                    {
                        "proposal_text": "本研究的主要终点为治疗期关键时间窗内 rTNSS 较基线的变化。",
                        "diff_patch": "替代版本 3",
                        "rationale": "采用研究方案正文的完整句式。",
                        "evidence_span_ids": ["span_revision_001"],
                    },
                ],
            },
        }

        self.assertEqual([], validate_ai_output(output))

        self.assertEqual(2, len(output["revision"]["alternatives"]))

        missing_revision = dict(output)
        missing_revision.pop("revision")
        self.assertIn(
            "medical_writing_revision output requires revision object",
            validate_ai_output(missing_revision),
        )

        overclaim = dict(output)
        overclaim["revision"] = dict(output["revision"])
        overclaim["revision"]["proposal_text"] = "该文本已医学批准，可正式提交监管。"
        errors = validate_ai_output(overclaim)
        self.assertTrue(
            any("forbidden medical-writing claim" in error for error in errors)
        )

        markdown_table = json.loads(json.dumps(output))
        markdown_table["revision"]["proposal_text"] = (
            "| 分析集 | 定义 |\n| --- | --- |\n| FAS | 所有随机受试者 |"
        )
        errors = validate_ai_output(markdown_table)
        self.assertTrue(any("unrendered Markdown table" in error for error in errors))

        missing_alternatives = json.loads(json.dumps(output))
        missing_alternatives["revision"].pop("alternatives")
        self.assertIn(
            "revision.alternatives must contain 2 to 4 candidate objects",
            validate_ai_output(missing_alternatives),
        )

        unknown_alternative_evidence = json.loads(json.dumps(output))
        unknown_alternative_evidence["revision"]["alternatives"][0][
            "evidence_span_ids"
        ] = ["missing_span"]
        self.assertTrue(
            any(
                "revision.alternatives[0] references unknown evidence_span_id: missing_span"
                in error
                for error in validate_ai_output(unknown_alternative_evidence)
            )
        )

        duplicate_candidate = json.loads(json.dumps(output))
        duplicate_candidate["revision"]["alternatives"][0]["proposal_text"] = (
            "主要终点为治疗期关键时间窗内 rTNSS 较基线的变化。"
        )
        self.assertIn(
            "medical-writing revision candidates must be textually distinct",
            validate_ai_output(duplicate_candidate),
        )

    def test_protocol_synopsis_structuring_requires_source_bound_study_definition(self):
        output = {
            "task_id": "task_synopsis_001",
            "task_type": "protocol_synopsis_structuring",
            "provider": "buddy",
            "model": "deepseek-v4-pro",
            "prompt_version": "protocol_synopsis_structuring_v0_1",
            "input_source_ids": ["synopsis_chunk_1"],
            "forbidden_source_ids": [],
            "findings": [],
            "evidence_spans": [
                {
                    "span_id": "synopsis_ev_1",
                    "source_id": "synopsis_chunk_1",
                    "locator": "synopsis:p1:b1",
                    "quote": "本研究为类风湿关节炎II期随机双盲安慰剂对照研究。",
                }
            ],
            "uncertainties": [
                {"level": "data_gap", "description": "样本量策略待医学经理补充。"}
            ],
            "needs_medical_confirmation": True,
            "schema_version": "ai_task_output_v0_1",
            "study_definition": {
                "framing": {"indication": "类风湿关节炎", "study_phase": "II期"},
                "picos": {"design_archetype": "randomized_confirmatory"},
                "synopsis_text": "本研究为II期随机双盲安慰剂对照研究。",
                "missing_fields": ["picos.sample_size_strategy"],
                "conflict_notes": [],
                "field_evidence_span_ids": {"framing.indication": ["synopsis_ev_1"]},
            },
        }
        self.assertEqual([], validate_ai_output(output))

        unknown = json.loads(json.dumps(output))
        unknown["study_definition"]["field_evidence_span_ids"]["framing.indication"] = [
            "missing_span"
        ]
        self.assertTrue(
            any(
                "unknown evidence_span_id" in error
                for error in validate_ai_output(unknown)
            )
        )

        auto_approved = json.loads(json.dumps(output))
        auto_approved["needs_medical_confirmation"] = False
        self.assertIn(
            "protocol_synopsis_structuring requires needs_medical_confirmation=true",
            validate_ai_output(auto_approved),
        )

        unsupported_with_empty_mapping = json.loads(json.dumps(output))
        unsupported_with_empty_mapping["study_definition"]["field_evidence_span_ids"][
            "picos.sample_size_strategy"
        ] = []
        self.assertEqual([], validate_ai_output(unsupported_with_empty_mapping))

        supported_with_empty_mapping = json.loads(json.dumps(output))
        supported_with_empty_mapping["study_definition"]["field_evidence_span_ids"][
            "framing.indication"
        ] = []
        self.assertTrue(
            any(
                "must contain evidence span IDs" in error
                for error in validate_ai_output(supported_with_empty_mapping)
            )
        )

        instrument = json.loads(json.dumps(output))
        instrument["study_definition"]["picos"]["assessment_instruments"] = [
            {
                "canonical_name_zh": "皮肤病生活质量指数",
                "evidence_span_ids": ["synopsis_ev_1"],
            }
        ]
        instrument["study_definition"]["field_evidence_span_ids"][
            "picos.assessment_instruments"
        ] = ["synopsis_ev_1"]
        self.assertEqual([], validate_ai_output(instrument))

        missing_item_evidence = json.loads(json.dumps(instrument))
        missing_item_evidence["study_definition"]["picos"]["assessment_instruments"][0][
            "evidence_span_ids"
        ] = []
        self.assertTrue(
            any(
                "evidence_span_ids must contain direct evidence span IDs" in error
                for error in validate_ai_output(missing_item_evidence)
            )
        )

        item_not_in_field = json.loads(json.dumps(instrument))
        item_not_in_field["evidence_spans"].append(
            {
                "span_id": "synopsis_ev_2",
                "source_id": "synopsis_chunk_1",
                "locator": "synopsis:p2:b1",
                "quote": "采用皮肤病生活质量指数评估生活质量。",
            }
        )
        item_not_in_field["study_definition"]["picos"]["assessment_instruments"][0][
            "evidence_span_ids"
        ] = ["synopsis_ev_2"]
        self.assertTrue(
            any(
                "evidence_span_id is absent from field-level evidence" in error
                for error in validate_ai_output(item_not_in_field)
            )
        )

        excessive_item_evidence = json.loads(json.dumps(instrument))
        for index in range(2, 7):
            excessive_item_evidence["evidence_spans"].append(
                {
                    "span_id": f"synopsis_ev_{index}",
                    "source_id": "synopsis_chunk_1",
                    "locator": f"synopsis:p{index}:b1",
                    "quote": f"量表直接证据{index}。",
                }
            )
        all_ids = [f"synopsis_ev_{index}" for index in range(1, 7)]
        excessive_item_evidence["study_definition"]["picos"]["assessment_instruments"][
            0
        ]["evidence_span_ids"] = all_ids
        excessive_item_evidence["study_definition"]["field_evidence_span_ids"][
            "picos.assessment_instruments"
        ] = all_ids
        self.assertTrue(
            any(
                "must contain at most 5 direct evidence spans" in error
                for error in validate_ai_output(excessive_item_evidence)
            )
        )


class _FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class _FakeRawResponse(_FakeResponse):
    def __init__(self, body: str):
        self.body = body

    def read(self) -> bytes:
        return self.body.encode("utf-8")


if __name__ == "__main__":
    unittest.main()
