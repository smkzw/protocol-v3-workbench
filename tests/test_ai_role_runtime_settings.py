from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app.ai_role_runtime_settings import (
    DEFAULT_OCR_MODEL,
    GATE_OWNED_ROLES,
    GATE_TRANSLATION_BODY_MODEL,
    INDEPENDENT_AI_ROLE,
    INDEPENDENT_AI_MTPLX_MODEL,
    INDEPENDENT_AI_MTPLX_PROFILE_ID,
    LOCAL_OMLX_PROFILE_ID,
    OCR_PADDLE_PROFILE_ID,
    OCR_ROLE,
    PADDLE_OCR_MODEL,
    TRANSLATION_BODY_ROLE,
    TRANSLATION_SUPPORT_ROLE,
    THINKING_ENABLED,
    THINKING_DISABLED,
    AiRoleBinding,
    AiRoleRuntimeSettingsStore,
)
from services.api.app.ai_runtime_settings import (
    AiProviderProfile,
    AiRuntimeSettingsStore,
)


class AiRoleRuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider_store = AiRuntimeSettingsStore(
            self.root / "ai_provider_settings.json"
        )
        self.provider_store.upsert(
            AiProviderProfile(
                profile_id="existing_ai",
                provider="alibaba_token_plan",
                label="Existing independent AI",
                base_url="https://example.invalid/v1",
                model="qwen3.8-max-preview",
                expected_response_model="qwen3.8-max-preview",
                api_key_env="TEST_AI_KEY",
            ),
            api_key="secret-value",
            activate=True,
        )
        self.store = AiRoleRuntimeSettingsStore(
            self.root / "ai_role_bindings.json",
            self.provider_store,
        )

    def tearDown(self):
        self.temp.cleanup()

    @patch(
        "services.api.app.ai_role_runtime_settings.discover_models",
        return_value=[
            DEFAULT_OCR_MODEL,
            GATE_TRANSLATION_BODY_MODEL,
        ],
    )
    def test_migration_keeps_four_independent_role_bindings_and_availability(
        self,
        _discover,
    ):
        payload = self.store.public_payload()
        roles = {item["role_id"]: item for item in payload["roles"]}

        self.assertTrue(self.store.settings_path.exists())
        self.assertEqual(
            0o600,
            stat.S_IMODE(self.store.settings_path.stat().st_mode),
        )
        self.assertIn(
            LOCAL_OMLX_PROFILE_ID,
            {item.profile_id for item in self.provider_store.profiles()},
        )
        self.assertEqual(
            INDEPENDENT_AI_MTPLX_PROFILE_ID,
            roles[INDEPENDENT_AI_ROLE]["profile_id"],
        )
        self.assertEqual(INDEPENDENT_AI_MTPLX_MODEL, roles[INDEPENDENT_AI_ROLE]["model"])
        self.assertEqual("enabled", roles[INDEPENDENT_AI_ROLE]["thinking"])
        self.assertEqual("medium", roles[INDEPENDENT_AI_ROLE]["reasoning_effort"])
        self.assertFalse(roles[OCR_ROLE]["gate_owned_model"])
        self.assertTrue(roles[OCR_ROLE]["model_editable"])
        self.assertEqual(PADDLE_OCR_MODEL, roles[OCR_ROLE]["model"])
        self.assertFalse(roles[OCR_ROLE]["ready"])
        self.assertIn("API Key", roles[OCR_ROLE]["blocked_reason"])
        self.assertEqual(
            GATE_TRANSLATION_BODY_MODEL,
            roles[TRANSLATION_BODY_ROLE]["model"],
        )
        self.assertTrue(roles[TRANSLATION_BODY_ROLE]["ready"])
        self.assertNotEqual(
            roles[OCR_ROLE]["profile_id"],
            roles[TRANSLATION_BODY_ROLE]["profile_id"],
        )
        self.assertNotIn("secret-value", json.dumps(payload, ensure_ascii=False))

    @patch(
        "services.api.app.ai_role_runtime_settings.discover_models",
        return_value=[
            DEFAULT_OCR_MODEL,
            GATE_TRANSLATION_BODY_MODEL,
        ],
    )
    def test_stale_non_authoritative_runtime_model_is_persistently_migrated(
        self,
        _discover,
    ):
        # Simulate a v1 runtime file with a shared profile and a custom body model.
        stale_payload = {
            "schema_version": "ai_role_bindings_v1",
            "revision": 5,
            "bindings": {
                "independent_ai": {
                    "role_id": "independent_ai",
                    "profile_id": "existing_ai",
                    "model": "qwen3.8-max-preview",
                    "enabled": True,
                },
                "ocr": {
                    "role_id": "ocr",
                    "profile_id": "local_omlx",
                    "model": "GLM-OCR-bf16",
                    "enabled": True,
                },
                "translation_body": {
                    "role_id": "translation_body",
                    "profile_id": "local_omlx",
                    "model": "legacy-non-authoritative-model",
                    "enabled": True,
                },
                "translation_support": {
                    "role_id": "translation_support",
                    "profile_id": "deepseek_translation_support",
                    "model": "deepseek-v4-flash",
                    "enabled": True,
                },
            },
        }
        self.store.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.store.settings_path.write_text(
            json.dumps(stale_payload, ensure_ascii=False), encoding="utf-8"
        )
        migrated = self.store.migrate()
        binding = AiRoleBinding(
            **migrated["bindings"][TRANSLATION_BODY_ROLE]
        )
        self.assertEqual("legacy-non-authoritative-model", binding.model)
        self.assertNotEqual(
            migrated["bindings"][OCR_ROLE]["profile_id"],
            migrated["bindings"][TRANSLATION_BODY_ROLE]["profile_id"],
        )
        persisted = json.loads(
            self.store.settings_path.read_text(encoding="utf-8")
        )
        self.assertEqual(
            "legacy-non-authoritative-model",
            persisted["bindings"][TRANSLATION_BODY_ROLE]["model"],
        )

    def test_deepseek_flash_role_gets_an_isolated_copy_of_support_credential(self):
        self.provider_store.upsert(
            AiProviderProfile(
                profile_id="deepseek_translation_support",
                provider="deepseek",
                label="DeepSeek support",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-flash",
                expected_response_model="deepseek-v4-flash",
                api_key_env="DEEPSEEK_API_KEY",
            ),
            api_key="deepseek-secret",
            activate=False,
        )

        self.store.migrate()

        independent = self.provider_store.profile(
            "independent_ai__deepseek_v4_flash"
        )
        self.assertEqual("deepseek-v4-flash", independent.model)
        self.assertEqual(
            "deepseek-secret",
            self.provider_store.credentials.get(independent.profile_id),
        )

    def test_ocr_and_translation_models_are_editable(self):
        self.store.migrate()
        updated = self.store.upsert(
            AiRoleBinding(
                role_id=TRANSLATION_BODY_ROLE,
                profile_id=LOCAL_OMLX_PROFILE_ID,
                model="custom-translation-model",
            )
        )
        self.assertEqual(
            "custom-translation-model",
            updated["bindings"][TRANSLATION_BODY_ROLE]["model"],
        )

    def test_thinking_options_are_persisted_only_for_llm_roles_and_reach_role_env(self):
        self.store.migrate()
        self.store.upsert(
            AiRoleBinding(
                role_id=INDEPENDENT_AI_ROLE,
                profile_id="existing_ai",
                model="qwen3.8-max-preview",
                thinking=THINKING_ENABLED,
                reasoning_effort="xhigh",
            )
        )
        self.store.upsert(
            AiRoleBinding(
                role_id=TRANSLATION_SUPPORT_ROLE,
                profile_id="existing_ai",
                model="deepseek-v4-flash",
                thinking=THINKING_ENABLED,
                reasoning_effort="high",
            )
        )
        independent_env = self.store.role_env(INDEPENDENT_AI_ROLE, {})
        support_env = self.store.role_env(TRANSLATION_SUPPORT_ROLE, {})
        self.assertEqual(THINKING_ENABLED, independent_env["WORKBENCH_AI_THINKING"])
        self.assertEqual("xhigh", independent_env["WORKBENCH_AI_REASONING_EFFORT"])
        self.assertEqual(THINKING_ENABLED, support_env["WORKBENCH_AI_THINKING"])
        self.assertEqual("high", support_env["WORKBENCH_AI_REASONING_EFFORT"])

        self.store.upsert(
            AiRoleBinding(
                role_id=OCR_ROLE,
                profile_id=OCR_PADDLE_PROFILE_ID,
                model=PADDLE_OCR_MODEL,
                thinking=THINKING_ENABLED,
                reasoning_effort="xhigh",
            )
        )
        ocr = self.store.binding(OCR_ROLE)
        self.assertEqual(THINKING_DISABLED, ocr.thinking)
        self.assertEqual("low", ocr.reasoning_effort)

    @patch(
        "services.api.app.ai_role_runtime_settings.discover_models",
        return_value=["custom-ocr", "custom-translation"],
    )
    def test_gate_model_resolver_is_ignored_and_role_defaults_remain_editable(
        self,
        _discover,
    ):
        store = AiRoleRuntimeSettingsStore(
            self.root / "custom_gate_role_bindings.json",
            self.provider_store,
            gate_model_resolver=lambda: {
                OCR_ROLE: "custom-ocr",
                TRANSLATION_BODY_ROLE: "custom-translation",
            },
        )

        roles = {
            item["role_id"]: item for item in store.public_payload()["roles"]
        }

        self.assertEqual(PADDLE_OCR_MODEL, roles[OCR_ROLE]["model"])
        self.assertEqual(
            GATE_TRANSLATION_BODY_MODEL,
            roles[TRANSLATION_BODY_ROLE]["model"],
        )

    def test_independent_role_binding_preserves_legacy_active_profile_contract(self):
        self.store.migrate()
        self.provider_store.upsert(
            AiProviderProfile(
                profile_id="alternative_ai",
                provider="deepseek",
                label="Alternative independent AI",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-v4-pro",
                expected_response_model="deepseek-v4-pro",
                api_key_env="DEEPSEEK_API_KEY",
            ),
        )
        self.store.upsert(
            AiRoleBinding(
                role_id=INDEPENDENT_AI_ROLE,
                profile_id="alternative_ai",
                model="deepseek-v4-pro",
            )
        )

        self.assertEqual(
            "independent_ai__alternative_ai",
            self.provider_store.active_profile().profile_id,
        )
        role_env = self.store.role_env(INDEPENDENT_AI_ROLE, {})
        self.assertEqual("deepseek-v4-pro", role_env["WORKBENCH_AI_MODEL"])
        self.assertEqual(INDEPENDENT_AI_ROLE, role_env["WORKBENCH_AI_ROLE"])

    def test_role_binding_model_isolated_from_source_profile(self):
        self.store.migrate()
        payload = self.store.upsert(
            AiRoleBinding(
                role_id=INDEPENDENT_AI_ROLE,
                profile_id="existing_ai",
                model="different-model",
            )
        )
        self.assertEqual(
            "different-model",
            payload["bindings"][INDEPENDENT_AI_ROLE]["model"],
        )

    def test_same_provider_credentials_and_models_never_overlap(self):
        self.store.migrate()
        role_models = {
            INDEPENDENT_AI_ROLE: "semantic-model",
            OCR_ROLE: DEFAULT_OCR_MODEL,
            TRANSLATION_BODY_ROLE: "body-model",
            "translation_support": "support-model",
        }
        for index, (role_id, model) in enumerate(role_models.items()):
            profile_id = f"shared-provider-{index}"
            self.provider_store.upsert(
                AiProviderProfile(
                    profile_id=profile_id,
                    provider="deepseek",
                    label=role_id,
                    base_url="https://api.deepseek.com/v1",
                    model=model,
                    expected_response_model=model,
                    api_key_env="DEEPSEEK_API_KEY",
                ),
                api_key=f"secret-{role_id}",
            )
            self.store.upsert(AiRoleBinding(role_id=role_id, profile_id=profile_id, model=model))

        bindings = {role_id: self.store.binding(role_id) for role_id in role_models}
        self.assertEqual(4, len({binding.profile_id for binding in bindings.values()}))
        for role_id, binding in bindings.items():
            values = self.store.role_env(role_id, {})
            self.assertEqual(role_models[role_id], values["WORKBENCH_AI_MODEL"])
            self.assertEqual(f"secret-{role_id}", values["WORKBENCH_AI_API_KEY"])

    def test_non_specialized_ocr_is_explicitly_blocked_without_probe(self):
        self.store.migrate()
        self.store.upsert(
            AiRoleBinding(
                role_id=OCR_ROLE,
                profile_id="existing_ai",
                model="qwen3.8-max-preview",
            )
        )
        role = next(
            item for item in self.store.public_payload()["roles"] if item["role_id"] == OCR_ROLE
        )
        self.assertEqual("blocked_unverified_visual", role["capability_status"])
        self.assertFalse(role["ready"])
        self.assertIn("视觉能力探针", role["blocked_reason"])

    @patch(
        "services.api.app.ai_role_runtime_settings.discover_models",
        return_value=["qwen3.8-vl"],
    )
    def test_visual_probe_evidence_unlocks_only_exact_ocr_profile_and_model(
        self,
        _discover,
    ):
        self.provider_store.upsert(
            AiProviderProfile(
                profile_id="vision_ai",
                provider="openai_compatible",
                label="Vision AI",
                base_url="https://example.invalid/v1",
                model="qwen3.8-vl",
                expected_response_model="qwen3.8-vl",
                api_key_env="VISION_AI_KEY",
            ),
            api_key="vision-secret",
        )
        bound = self.store.upsert(
            AiRoleBinding(
                role_id=OCR_ROLE,
                profile_id="vision_ai",
                model="qwen3.8-vl",
            )
        )
        isolated = bound["bindings"][OCR_ROLE]
        self.store.record_ocr_visual_probe(
            profile_id=isolated["profile_id"],
            model="qwen3.8-vl",
        )

        role = next(
            item
            for item in self.store.public_payload()["roles"]
            if item["role_id"] == OCR_ROLE
        )
        self.assertEqual("visual_probe_passed", role["capability_status"])
        self.assertTrue(role["ready"])

        self.store.upsert(
            AiRoleBinding(
                role_id=OCR_ROLE,
                profile_id=isolated["profile_id"],
                model="qwen3.8-vl-next",
            )
        )
        changed = next(
            item
            for item in self.store.public_payload()["roles"]
            if item["role_id"] == OCR_ROLE
        )
        self.assertEqual(
            "blocked_unverified_visual",
            changed["capability_status"],
        )
        self.assertFalse(changed["ready"])

    @patch(
        "services.api.app.ai_role_runtime_settings.discover_models",
        return_value=[
            DEFAULT_OCR_MODEL,
            GATE_TRANSLATION_BODY_MODEL,
        ],
    )
    def test_disabled_independent_role_blocks_role_env_and_execution_status(
        self,
        _discover,
    ):
        self.store.migrate()
        self.store.upsert(
            AiRoleBinding(
                role_id=INDEPENDENT_AI_ROLE,
                profile_id="existing_ai",
                model="qwen3.8-max-preview",
                enabled=False,
            )
        )

        with self.assertRaisesRegex(ValueError, "disabled"):
            self.store.role_env(INDEPENDENT_AI_ROLE, {})
        roles = {
            item["role_id"]: item for item in self.store.public_payload()["roles"]
        }
        self.assertFalse(roles[INDEPENDENT_AI_ROLE]["ready"])
        self.assertFalse(
            roles[INDEPENDENT_AI_ROLE]["execution_binding_consumed"]
        )


class AiRoleRuntimeSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(
            os.environ,
            {
                "WORKBENCH_AI_SETTINGS_PATH": str(
                    self.root / "ai_provider_settings.json"
                ),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(
                    self.root / "ai_role_bindings.json"
                ),
            },
            clear=False,
        )
        self.env.start()
        from services.api.app.main import app

        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    @patch(
        "services.api.app.ai_role_runtime_settings.discover_models",
        return_value=[
            DEFAULT_OCR_MODEL,
            GATE_TRANSLATION_BODY_MODEL,
        ],
    )
    def test_role_api_exposes_editable_model_and_capability_contract(self, _discover):
        status = self.client.get("/api/ai-gateway/roles/status")
        self.assertEqual(200, status.status_code, status.text)
        role = next(
            item
            for item in status.json()["roles"]
            if item["role_id"] == TRANSLATION_BODY_ROLE
        )
        self.assertEqual(GATE_TRANSLATION_BODY_MODEL, role["model"])
        self.assertFalse(role["gate_owned_model"])
        self.assertTrue(role["model_editable"])
        self.assertIn("recommendation", role)

    def test_translation_role_upsert_via_api_can_change_model(self):
        response = self.client.put(
            f"/api/ai-gateway/roles/{TRANSLATION_BODY_ROLE}",
            json={
                "profile_id": "local_omlx",
                "model": "custom-translation-model",
                "enabled": True,
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        role = next(item for item in response.json()["roles"] if item["role_id"] == TRANSLATION_BODY_ROLE)
        self.assertEqual("custom-translation-model", role["model"])

    def test_llm_role_api_persists_thinking_mode_and_effort(self):
        response = self.client.put(
            f"/api/ai-gateway/roles/{TRANSLATION_SUPPORT_ROLE}",
            json={
                "profile_id": "local_omlx",
                "model": "deepseek-v4-flash",
                "enabled": True,
                "thinking": "enabled",
                "reasoning_effort": "high",
            },
        )
        self.assertEqual(200, response.status_code, response.text)
        role = next(
            item
            for item in response.json()["roles"]
            if item["role_id"] == TRANSLATION_SUPPORT_ROLE
        )
        self.assertTrue(role["thinking_configurable"])
        self.assertEqual("enabled", role["thinking"])
        self.assertEqual("high", role["reasoning_effort"])
        self.assertIn("xhigh", role["reasoning_efforts"])
        self.assertIn("max", role["reasoning_efforts"])

    def test_unknown_role_fails_closed(self):
        response = self.client.put(
            "/api/ai-gateway/roles/not_a_role",
            json={
                "profile_id": "missing",
                "model": "model",
            },
        )
        self.assertEqual(404, response.status_code)
        self.assertEqual("AI role not found", response.json()["detail"])

    def _configure_paddle_ocr_role(self):
        profile_response = self.client.put(
            f"/api/ai-gateway/profiles/{OCR_PADDLE_PROFILE_ID}",
            json={
                "profile_id": OCR_PADDLE_PROFILE_ID,
                "provider": "paddle_official",
                "label": "PaddleOCR-VL-1.6 官方异步 API",
                "base_url": "https://paddleocr.aistudio-app.com",
                "model": PADDLE_OCR_MODEL,
                "transport": "paddle_async_job",
                "deployment_profile": "local_private_clinical",
                "timeout_seconds": 120,
                "expected_response_model": PADDLE_OCR_MODEL,
                "api_key_env": "PADDLE_OCR_API_KEY",
                "deployment_scope": "cloud",
                "discovery_mode": "manual_plus_probe",
                "enabled": True,
                "api_key": "test-paddle-secret",
                "activate": False,
            },
        )
        self.assertEqual(200, profile_response.status_code, profile_response.text)
        bind_response = self.client.put(
            f"/api/ai-gateway/roles/{OCR_ROLE}",
            json={
                "profile_id": OCR_PADDLE_PROFILE_ID,
                "model": PADDLE_OCR_MODEL,
                "enabled": True,
            },
        )
        self.assertEqual(200, bind_response.status_code, bind_response.text)
        return next(
            item
            for item in bind_response.json()["roles"]
            if item["role_id"] == OCR_ROLE
        )

    def test_non_specialized_ocr_visual_probe_uses_image_and_unlocks_role(self):
        profile_id = "ocr__vision_probe"
        profile_response = self.client.put(
            f"/api/ai-gateway/profiles/{profile_id}",
            json={
                "profile_id": profile_id,
                "provider": "openai_compatible",
                "label": "Vision probe model",
                "base_url": "https://vision.example.invalid/v1",
                "model": "vision-general-model",
                "transport": "openai_compatible",
                "deployment_profile": "local_private_clinical",
                "timeout_seconds": 120,
                "expected_response_model": "vision-general-model",
                "api_key_env": "VISION_TEST_KEY",
                "deployment_scope": "cloud",
                "discovery_mode": "manual_plus_probe",
                "enabled": True,
                "api_key": "test-secret",
                "activate": False,
            },
        )
        self.assertEqual(200, profile_response.status_code, profile_response.text)
        bind_response = self.client.put(
            f"/api/ai-gateway/roles/{OCR_ROLE}",
            json={
                "profile_id": profile_id,
                "model": "vision-general-model",
                "enabled": True,
            },
        )
        self.assertEqual(200, bind_response.status_code, bind_response.text)
        bound_role = next(
            item
            for item in bind_response.json()["roles"]
            if item["role_id"] == OCR_ROLE
        )
        self.assertFalse(bound_role["ready"])

        captured = {}

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {"message": {"content": "CMS VISION 7429"}}
                        ]
                    }
                ).encode("utf-8")

        def fake_urlopen(request, timeout):
            if request.data is None:
                class _ModelsResponse(_Response):
                    def read(self):
                        return json.dumps(
                            {
                                "data": [
                                    {"id": DEFAULT_OCR_MODEL},
                                    {"id": GATE_TRANSLATION_BODY_MODEL},
                                ]
                            }
                        ).encode("utf-8")

                return _ModelsResponse()
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response()

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            probe_response = self.client.post(
                "/api/ai-gateway/roles/ocr/probe-visual",
                json={
                    "profile_id": bound_role["profile_id"],
                    "model": "vision-general-model",
                },
            )

        self.assertEqual(200, probe_response.status_code, probe_response.text)
        self.assertEqual("vision-general-model", captured["payload"]["model"])
        content = captured["payload"]["messages"][0]["content"]
        self.assertTrue(
            any(
                item.get("type") == "image_url"
                and item["image_url"]["url"].startswith(
                    "data:image/png;base64,"
                )
                for item in content
            )
        )
        probed_role = next(
            item
            for item in probe_response.json()["roles"]
            if item["role_id"] == OCR_ROLE
        )
        self.assertEqual(
            "visual_probe_passed",
            probed_role["capability_status"],
        )
        self.assertTrue(probed_role["ready"])

    def test_paddle_visual_probe_uses_dedicated_role_gateway(self):
        from datetime import datetime, timezone

        from services.api.app.ocr_gateway import OcrResult

        bound_role = self._configure_paddle_ocr_role()
        calls = []

        class _PaddleGateway:
            def run(self, request):
                calls.append(request)
                return OcrResult(
                    text="CMS VISION 7429",
                    model=PADDLE_OCR_MODEL,
                    provider="paddle_official",
                    source_token="ocrsrc_paddle_probe",
                    content_hash="a" * 64,
                    character_count=15,
                    called_at=datetime.now(timezone.utc),
                    duration_ms=12.0,
                )

        with patch(
            "services.api.app.main._build_role_bound_ocr_gateway",
            return_value=_PaddleGateway(),
        ):
            response = self.client.post(
                "/api/ai-gateway/roles/ocr/probe-visual",
                json={
                    "profile_id": bound_role["profile_id"],
                    "model": PADDLE_OCR_MODEL,
                },
            )

        self.assertEqual(200, response.status_code, response.text)
        self.assertEqual(1, len(calls))
        self.assertEqual(
            "paddle_official",
            response.json()["visual_probe"]["provider"],
        )

    def test_paddle_visual_probe_rejects_glm_fallback_result(self):
        from datetime import datetime, timezone

        from services.api.app.ocr_gateway import OcrResult

        bound_role = self._configure_paddle_ocr_role()
        calls = []

        class _FallbackGateway:
            def run(self, request):
                calls.append(request)
                return OcrResult(
                    text="CMS VISION 7429",
                    model=DEFAULT_OCR_MODEL,
                    provider="omlx",
                    source_token="ocrsrc_glm_fallback_probe",
                    content_hash="b" * 64,
                    character_count=15,
                    called_at=datetime.now(timezone.utc),
                    duration_ms=10.0,
                    fell_back=True,
                    primary_model=PADDLE_OCR_MODEL,
                    fallback_reason="paddle_failure:test",
                )

        with patch(
            "services.api.app.main._build_role_bound_ocr_gateway",
            return_value=_FallbackGateway(),
        ):
            response = self.client.post(
                "/api/ai-gateway/roles/ocr/probe-visual",
                json={
                    "profile_id": bound_role["profile_id"],
                    "model": PADDLE_OCR_MODEL,
                },
            )

        self.assertEqual(502, response.status_code, response.text)
        self.assertEqual(1, len(calls))
        self.assertIn("Paddle", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
