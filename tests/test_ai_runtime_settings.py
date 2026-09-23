from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
import urllib.request

import pytest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from services.api.app.ai_gateway import (
    ALIBABA_TOKEN_PLAN_BASE_URL,
    ALIBABA_TOKEN_PLAN_MODEL,
    DisabledAiProvider,
    OpenAICompatibleAiProvider,
    ai_gateway_status_from_env,
    configured_ai_provider_from_env,
)
from services.api.app.ai_runtime_settings import (
    ALIBABA_TOKEN_PLAN_API_KEY_ENV,
    AiProviderProfile,
    AiRuntimeSettingsStore,
)


class AiRuntimeSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.settings_path = self.root / "ai_provider_settings.json"
        self.store = AiRuntimeSettingsStore(self.settings_path)
        self.profile = AiProviderProfile(
            profile_id="alibaba_qwen38",
            provider="alibaba_token_plan",
            label="Qwen 3.8",
            base_url=ALIBABA_TOKEN_PLAN_BASE_URL,
            model=ALIBABA_TOKEN_PLAN_MODEL,
            expected_response_model=ALIBABA_TOKEN_PLAN_MODEL,
            api_key_env=ALIBABA_TOKEN_PLAN_API_KEY_ENV,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_profile_and_secret_are_stored_separately_and_never_returned(self):
        self.store.upsert(self.profile, api_key="private-test-key", activate=True)

        public = self.store.public_payload()
        serialized = json.dumps(public, ensure_ascii=False)

        self.assertEqual("alibaba_qwen38", public["active_profile_id"])
        self.assertTrue(public["profiles"][0]["api_key_configured"])
        self.assertNotIn("private-test-key", serialized)
        self.assertNotIn("private-test-key", self.settings_path.read_text())
        self.assertEqual("private-test-key", self.store.credentials.get("alibaba_qwen38"))
        self.assertEqual(
            stat.S_IMODE(self.settings_path.stat().st_mode),
            0o600,
        )
        self.assertEqual(
            stat.S_IMODE(self.store.credentials.secret_path.stat().st_mode),
            0o600,
        )

    def test_active_profile_overlays_environment_for_product_provider(self):
        self.store.upsert(self.profile, api_key="private-test-key", activate=True)

        values = self.store.active_env({})

        self.assertEqual("alibaba_token_plan", values["WORKBENCH_AI_PROVIDER"])
        self.assertEqual(ALIBABA_TOKEN_PLAN_MODEL, values["WORKBENCH_AI_MODEL"])
        self.assertEqual("private-test-key", values["WORKBENCH_AI_API_KEY"])
        self.assertEqual(
            "private-test-key", values[ALIBABA_TOKEN_PLAN_API_KEY_ENV]
        )

    def test_token_plan_profile_accepts_existing_legacy_environment_name(self):
        legacy_profile = AiProviderProfile(
            **{
                **self.profile.__dict__,
                "api_key_env": "ALIBABA_CODING_PLAN_API_KEY",
            }
        )
        self.store.upsert(legacy_profile, activate=True)

        values = self.store.active_env(
            {"ALIBABA_TOKEN_PLAN_CN_API_KEY": "existing-token-plan-key"}
        )

        self.assertEqual(
            "existing-token-plan-key", values["WORKBENCH_AI_API_KEY"]
        )
        self.assertEqual(
            "existing-token-plan-key",
            values["ALIBABA_CODING_PLAN_API_KEY"],
        )

    def test_disabled_independent_role_blocks_profile_and_environment_fallback(self):
        self.store.upsert(self.profile, api_key="private-test-key", activate=True)
        role_path = self.root / "ai_role_bindings.json"
        role_path.write_text(
            json.dumps(
                {
                    "schema_version": "ai_role_bindings_v1",
                    "revision": 1,
                    "bindings": {
                        "independent_ai": {
                            "role_id": "independent_ai",
                            "profile_id": self.profile.profile_id,
                            "model": self.profile.model,
                            "enabled": False,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        values = self.store.active_env(
            {
                "WORKBENCH_AI_PROVIDER": "deepseek",
                "WORKBENCH_AI_MODEL": "deepseek-v4-pro",
                "WORKBENCH_AI_BASE_URL": "https://api.deepseek.com/v1",
                "WORKBENCH_AI_API_KEY": "must-not-survive",
            }
        )

        self.assertEqual("disabled", values["WORKBENCH_AI_PROVIDER"])
        self.assertEqual("", values["WORKBENCH_AI_MODEL"])
        self.assertEqual("", values["WORKBENCH_AI_API_KEY"])
        self.assertEqual("disabled", values["WORKBENCH_AI_DEPLOYMENT_PROFILE"])

    def test_v2_disabled_independent_role_blocks_active_environment(self):
        self.store.upsert(self.profile, api_key="private-test-key", activate=True)
        role_path = self.root / "ai_role_bindings.json"
        role_path.write_text(
            json.dumps(
                {
                    "schema_version": "ai_role_bindings_v2",
                    "revision": 1,
                    "bindings": {
                        "independent_ai": {
                            "role_id": "independent_ai",
                            "profile_id": self.profile.profile_id,
                            "model": self.profile.model,
                            "enabled": False,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            {"WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path)},
            clear=False,
        ):
            values = self.store.active_env({})

        self.assertEqual("disabled", values["WORKBENCH_AI_PROVIDER"])
        self.assertEqual("", values["WORKBENCH_AI_MODEL"])
        self.assertEqual("", values["WORKBENCH_AI_API_KEY"])

    def test_v2_role_profile_overrides_stale_legacy_active_profile(self):
        self.store.upsert(self.profile, api_key="legacy-key", activate=True)
        role_profile = AiProviderProfile(
            profile_id="independent_ai__alibaba_qwen38",
            provider="alibaba_token_plan",
            label="Qwen 3.8 comprehensive AI",
            base_url=ALIBABA_TOKEN_PLAN_BASE_URL,
            model=ALIBABA_TOKEN_PLAN_MODEL,
            expected_response_model=ALIBABA_TOKEN_PLAN_MODEL,
            api_key_env="ALIBABA_CODING_PLAN_API_KEY",
        )
        self.store.upsert(
            role_profile,
            api_key="role-key",
            activate_if_empty=False,
        )
        role_path = self.root / "ai_role_bindings.json"
        role_path.write_text(
            json.dumps(
                {
                    "schema_version": "ai_role_bindings_v2",
                    "revision": 1,
                    "bindings": {
                        "independent_ai": {
                            "role_id": "independent_ai",
                            "profile_id": role_profile.profile_id,
                            "model": role_profile.model,
                            "enabled": True,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

        with patch.dict(
            os.environ,
            {"WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path)},
            clear=False,
        ):
            values = self.store.active_env({})
            effective = self.store.effective_independent_profile()

        self.assertEqual(
            "alibaba_qwen38",
            self.store.active_profile().profile_id,
        )
        self.assertIsNotNone(effective)
        self.assertEqual(role_profile.profile_id, effective.profile_id)
        self.assertEqual("role-key", values["WORKBENCH_AI_API_KEY"])
        self.assertEqual(ALIBABA_TOKEN_PLAN_MODEL, values["WORKBENCH_AI_MODEL"])

    def test_gateway_returns_disabled_provider_when_independent_role_is_disabled(self):
        role_path = self.root / "ai_role_bindings.json"
        with patch.dict(
            os.environ,
            {
                "WORKBENCH_AI_SETTINGS_PATH": str(self.settings_path),
                "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(role_path),
            },
            clear=True,
        ):
            self.store.upsert(self.profile, api_key="private-test-key", activate=True)
            role_path.write_text(
                json.dumps(
                    {
                        "schema_version": "ai_role_bindings_v1",
                        "revision": 1,
                        "bindings": {
                            "independent_ai": {
                                "role_id": "independent_ai",
                                "profile_id": self.profile.profile_id,
                                "model": self.profile.model,
                                "enabled": False,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            provider = configured_ai_provider_from_env()
            status = ai_gateway_status_from_env()

        self.assertIsInstance(provider, DisabledAiProvider)
        self.assertFalse(status["semantic_ai_tasks_enabled"])

    def test_gateway_uses_runtime_profile_when_no_explicit_env_is_supplied(self):
        with patch.dict(
            os.environ,
            {"WORKBENCH_AI_SETTINGS_PATH": str(self.settings_path)},
            clear=True,
        ):
            self.store.upsert(self.profile, api_key="private-test-key", activate=True)
            provider = configured_ai_provider_from_env()
            status = ai_gateway_status_from_env()

        self.assertIsInstance(provider, OpenAICompatibleAiProvider)
        self.assertEqual(ALIBABA_TOKEN_PLAN_MODEL, provider.model_name)
        self.assertEqual("alibaba_qwen38", status["active_profile_id"])
        self.assertTrue(status["semantic_ai_tasks_enabled"])
        self.assertNotIn("private-test-key", json.dumps(status))

    def test_profile_revision_changes_only_when_profile_definition_changes(self):
        first = self.store.upsert(
            self.profile, api_key="private-test-key", activate=True
        )
        self.assertEqual(1, first["profiles"][0]["revision"])

        same = self.store.upsert(
            self.profile, api_key="rotated-private-test-key", activate=True
        )
        self.assertEqual(1, same["profiles"][0]["revision"])

        changed = self.store.upsert(
            AiProviderProfile(
                **{
                    **self.profile.__dict__,
                    "model": "qwen3.8-max-preview-v2",
                }
            ),
            activate=True,
        )
        self.assertEqual(2, changed["profiles"][0]["revision"])

    def test_profile_delete_removes_definition_and_credential(self):
        self.store.upsert(
            self.profile, api_key="private-test-key", activate=True
        )

        deleted = self.store.delete(self.profile.profile_id)

        self.assertEqual("", deleted["active_profile_id"])
        self.assertEqual([], deleted["profiles"])
        self.assertEqual("", self.store.credentials.get(self.profile.profile_id))
        with self.assertRaises(KeyError):
            self.store.profile(self.profile.profile_id)


class AiRuntimeSettingsApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings_path = Path(self.temp.name) / "ai_provider_settings.json"
        self.env = patch.dict(
            os.environ,
            {"WORKBENCH_AI_SETTINGS_PATH": str(self.settings_path)},
            clear=False,
        )
        self.env.start()
        from services.api.app.main import app

        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_profile_crud_contract_is_write_only_for_secret(self):
        response = self.client.put(
            "/api/ai-gateway/profiles/test_qwen",
            json={
                "profile_id": "test_qwen",
                "provider": "alibaba_token_plan",
                "label": "Qwen test",
                "base_url": ALIBABA_TOKEN_PLAN_BASE_URL,
                "model": ALIBABA_TOKEN_PLAN_MODEL,
                "expected_response_model": ALIBABA_TOKEN_PLAN_MODEL,
                "api_key_env": "ALIBABA_CODING_PLAN_API_KEY",
                "api_key": "api-secret-value",
                "activate": True,
            },
        )

        self.assertEqual(200, response.status_code, response.text)
        payload = response.json()
        self.assertEqual("independent_ai__test_qwen", payload["active_profile_id"])
        test_profile = next(
            item for item in payload["profiles"] if item["profile_id"] == "test_qwen"
        )
        self.assertTrue(test_profile["api_key_configured"])
        self.assertNotIn("api-secret-value", response.text)

        settings = self.client.get("/api/ai-gateway/settings")
        self.assertEqual(200, settings.status_code)
        self.assertNotIn("api-secret-value", settings.text)

    def test_profile_path_and_body_must_match(self):
        response = self.client.put(
            "/api/ai-gateway/profiles/path_id",
            json={
                "profile_id": "body_id",
                "provider": "deepseek",
                "label": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-v4-pro",
            },
        )

        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# R04: model discovery error classification and loopback proxy isolation
# ---------------------------------------------------------------------------


def _discovery_profile(base_url="http://127.0.0.1:8002/v1"):
    from services.api.app.ai_runtime_settings import AiProviderProfile

    return AiProviderProfile(
        profile_id="mtplx_local",
        provider="openai_compatible",
        label="MTPLX local",
        base_url=base_url,
        model="mtplx-flash-next-optimized-speed",
    )


def test_discovery_loopback_classification():
    from services.api.app.ai_runtime_settings import _discovery_loopback

    assert _discovery_loopback("http://127.0.0.1:8002/v1/models") is True
    assert _discovery_loopback("http://localhost:8002/v1/models") is True
    assert _discovery_loopback("http://[::1]:8002/v1/models") is True
    assert _discovery_loopback("https://api.deepseek.com/v1/models") is False


def test_discovery_401_reports_auth_required_with_status():
    import io
    import urllib.error
    from services.api.app import ai_runtime_settings as m

    def _fake_opener(*_args, **_kwargs):
        class _Op:
            def open(self, request, timeout=None):
                raise urllib.error.HTTPError(
                    request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"")
                )

        return _Op()

    original = m.urllib.request.build_opener
    m.urllib.request.build_opener = _fake_opener
    try:
        with pytest.raises(m.ModelDiscoveryError) as excinfo:
            m.discover_models(_discovery_profile())
    finally:
        m.urllib.request.build_opener = original
    assert excinfo.value.layer == "auth_required"
    assert excinfo.value.status == 401
    assert "127.0.0.1:8002" in str(excinfo.value)


def test_discovery_array_json_root_reports_invalid_schema():
    from services.api.app import ai_runtime_settings as m

    def _fake_opener(*_args, **_kwargs):
        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'[{"id":"not-an-openai-shape"}]'

        class _Op:
            def open(self, request, timeout=None):
                return _Response()

        return _Op()

    original = m.urllib.request.build_opener
    m.urllib.request.build_opener = _fake_opener
    try:
        with pytest.raises(m.ModelDiscoveryError) as excinfo:
            m.discover_models(_discovery_profile())
    finally:
        m.urllib.request.build_opener = original
    assert excinfo.value.layer == "invalid_schema"


def test_discovery_loopback_bypasses_proxy_and_cloud_keeps_default():
    from services.api.app import ai_runtime_settings as m

    captured = []

    def _fake_build_opener(*handlers):
        captured.append(handlers)

        class _Op:
            def __init__(self, payload):
                self._payload = payload

            def open(self, request, timeout=None):
                class _Response:
                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        return False

                    def read(self):
                        import json as _json

                        return _json.dumps({"data": []}).encode("utf-8")

                return _Response()

        return _Op({"data": []})

    original = m.urllib.request.build_opener
    m.urllib.request.build_opener = _fake_build_opener
    try:
        m.discover_models(_discovery_profile("http://127.0.0.1:8002/v1"))
        m.discover_models(_discovery_profile("https://api.example.com/v1"))
    finally:
        m.urllib.request.build_opener = original
    # loopback path builds the no-proxy opener as the ProxyHandler call;
    # the cloud endpoint (last call) must keep the default opener policy.
    proxy_calls = [
        index
        for index, handlers in enumerate(captured)
        if any(isinstance(h, urllib.request.ProxyHandler) for h in handlers)
    ]
    assert proxy_calls, "loopback discovery never built a no-proxy opener"
    assert captured[-1] == (), "cloud discovery must not receive proxy handlers"
