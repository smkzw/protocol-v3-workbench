from __future__ import annotations

import unittest

from packages.contracts.workbench_contracts import AiTaskRequest, AiTaskSourceRef
from services.api.app.ai_gateway import (
    ALIBABA_TOKEN_PLAN_BASE_URL,
    ALIBABA_TOKEN_PLAN_MODEL,
    ALIBABA_TOKEN_PLAN_PROVIDER,
)
from services.api.app.ai_execution_policy import (
    AiExecutionPolicyDenied,
    AiExecutionPolicyResolver,
)


DIRECT_BASE_URL = "https://api.deepseek.com/v1"
PRO_MODEL = "deepseek-v4-pro"
FLASH_MODEL = "deepseek-v4-flash"
PROJECT_ID = "proj_medical_writing_direct_ai_policy"


class MedicalWritingDirectAiPolicyTests(unittest.TestCase):
    def _request(self, task_type: str) -> AiTaskRequest:
        prompt_versions = {
            "medical_writing_revision": "medical_writing_revision_v1_4",
            "protocol_synopsis_structuring": "protocol_synopsis_structuring_v0_9",
            "document_section_extraction": "document_section_extraction_v0_1",
            "regulatory_translation_zh": "regulatory_translation_zh_v0_5",
        }
        task_context = {}
        if task_type == "regulatory_translation_zh":
            task_context = {
                "glossary_version": "cms_regulatory_zh_v1",
                "source_span_revision": "source_r1",
                "document_sha256": "a" * 64,
            }
        return AiTaskRequest(
            module="medical_writing",
            task_type=task_type,
            prompt_version=prompt_versions[task_type],
            allowed_sources=[
                AiTaskSourceRef(
                    source_id="source_001",
                    source_type="protocol_section",
                    title="Protocol source",
                    locator="section:1",
                    text_preview="Source text.",
                    project_id=PROJECT_ID,
                    module="medical_writing",
                )
            ],
            task_context=task_context,
        )

    def _resolver(
        self,
        *,
        provider_name: str = "deepseek",
        transport_name: str = "openai_compatible",
        base_url: str = DIRECT_BASE_URL,
        model_name: str = PRO_MODEL,
        test_only_provider_injection: bool = False,
    ) -> AiExecutionPolicyResolver:
        return AiExecutionPolicyResolver(
            deployment_profile="approved_private_documents",
            provider_name=provider_name,
            transport_name=transport_name,
            base_url=base_url,
            model_name=model_name,
            test_only_provider_injection=test_only_provider_injection,
        )

    def _resolve(self, task_type: str, **route):
        return self._resolver(**route).resolve_internal(
            PROJECT_ID, self._request(task_type)
        )

    def test_authoring_and_synopsis_accept_exact_direct_pro(self):
        for task_type in (
            "medical_writing_revision",
            "protocol_synopsis_structuring",
        ):
            with self.subTest(task_type=task_type):
                resolution = self._resolve(task_type)
                self.assertEqual("deepseek", resolution.provider_name)
                self.assertEqual("openai_compatible", resolution.transport_name)
                self.assertEqual(DIRECT_BASE_URL, resolution.base_url)
                self.assertEqual(PRO_MODEL, resolution.model_name)
                self.assertEqual(PRO_MODEL, resolution.required_response_model)

    def test_all_medical_writing_tasks_accept_exact_qwen38_product_route(self):
        for task_type in (
            "medical_writing_revision",
            "protocol_synopsis_structuring",
            "document_section_extraction",
            "regulatory_translation_zh",
        ):
            with self.subTest(task_type=task_type):
                resolution = self._resolve(
                    task_type,
                    provider_name=ALIBABA_TOKEN_PLAN_PROVIDER,
                    base_url=ALIBABA_TOKEN_PLAN_BASE_URL,
                    model_name=ALIBABA_TOKEN_PLAN_MODEL,
                )
                self.assertEqual(
                    ALIBABA_TOKEN_PLAN_PROVIDER, resolution.provider_name
                )
                self.assertEqual(
                    ALIBABA_TOKEN_PLAN_MODEL, resolution.required_response_model
                )

    def test_buddy_over_hermes_is_rejected(self):
        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "provider must be one of"
        ):
            self._resolve(
                "medical_writing_revision",
                provider_name="buddy",
                transport_name="hermes_cli",
            )

    def test_deepseek_over_hermes_is_rejected(self):
        with self.assertRaisesRegex(
            AiExecutionPolicyDenied, "transport must be openai_compatible"
        ):
            self._resolve(
                "protocol_synopsis_structuring", transport_name="hermes_cli"
            )

    def test_wrong_base_url_is_rejected(self):
        with self.assertRaisesRegex(AiExecutionPolicyDenied, "base URL"):
            self._resolve(
                "medical_writing_revision",
                base_url="https://proxy.example/v1",
            )

    def test_missing_or_wrong_model_is_rejected(self):
        for model_name in ("", "deepseek-v4-flash", "deepseek-chat"):
            with self.subTest(model_name=model_name):
                with self.assertRaisesRegex(AiExecutionPolicyDenied, "model must be"):
                    self._resolve(
                        "medical_writing_revision", model_name=model_name
                    )

    def test_flash_exception_is_limited_to_structure_and_translation_tasks(self):
        for task_type in (
            "document_section_extraction",
            "regulatory_translation_zh",
        ):
            with self.subTest(task_type=task_type):
                resolution = self._resolve(task_type, model_name=FLASH_MODEL)
                self.assertEqual(FLASH_MODEL, resolution.required_response_model)

        with self.assertRaisesRegex(AiExecutionPolicyDenied, "model must be"):
            self._resolve("protocol_synopsis_structuring", model_name=FLASH_MODEL)

    def test_fake_provider_requires_explicit_test_only_injection(self):
        with self.assertRaises(AiExecutionPolicyDenied):
            self._resolve(
                "medical_writing_revision",
                provider_name="fake_provider",
                transport_name="fake_transport",
                base_url="test://provider",
                model_name="fake_model",
            )

        resolution = self._resolve(
            "medical_writing_revision",
            provider_name="fake_provider",
            transport_name="fake_transport",
            base_url="test://provider",
            model_name="fake_model",
            test_only_provider_injection=True,
        )
        self.assertTrue(resolution.test_only_provider_injection)


if __name__ == "__main__":
    unittest.main()
