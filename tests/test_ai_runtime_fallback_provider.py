from types import SimpleNamespace

import pytest

from services.api.app.ai_gateway import AiProviderRuntimeError
from services.api.app.ai_runtime_fallback_provider import RuntimeFallbackAiProvider
from services.api.app.medical_writing_authoring_prefill_ai import DeepSeekPrefillAdapter


class _Provider:
    def __init__(self, provider, model, *, failure=None):
        self.provider_name = provider
        self.model_name = model
        self.default_thinking = "enabled"
        self.default_reasoning_effort = "medium"
        self.max_attempts = 1
        self.timeout_seconds = 300.0
        self.failure = failure
        self.calls = 0

    def run(self, _envelope):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return {"status": "ok"}


def _http_error(status):
    return AiProviderRuntimeError(
        f"HTTP {status}",
        diagnostics={
            "failure_code": "provider_http_error",
            "http_status": status,
        },
    )


def test_runtime_provider_chain_falls_back_after_429_and_exposes_actual_route():
    primary = _Provider("mtplx", "qwen-local", failure=_http_error(429))
    fallback = _Provider("cms-router", "deepseek-latest-cloud")
    chain = RuntimeFallbackAiProvider(
        [("profile_mtplx", primary), ("profile_cms", fallback)]
    )

    assert chain.run(SimpleNamespace()) == {"status": "ok"}
    assert chain.provider_name == "cms-router"
    assert chain.model_name == "deepseek-latest-cloud"
    assert chain.route_profile_id == "profile_cms"
    assert chain.fallback_depth == 1
    assert chain.fallback_reason == "provider_http_error:429"
    assert chain.fallback_chain_id.startswith("raif_")
    assert primary.calls == fallback.calls == 1


def test_runtime_provider_chain_does_not_fallback_after_400():
    primary = _Provider("mtplx", "qwen-local", failure=_http_error(400))
    fallback = _Provider("cms-router", "deepseek-latest-cloud")
    chain = RuntimeFallbackAiProvider(
        [("profile_mtplx", primary), ("profile_cms", fallback)]
    )

    with pytest.raises(AiProviderRuntimeError):
        chain.run(SimpleNamespace())

    assert primary.calls == 1
    assert fallback.calls == 0


def test_runtime_provider_chain_applies_timeout_to_every_route():
    primary = _Provider("mtplx", "qwen-local")
    fallback = _Provider("cms-router", "deepseek-latest-cloud")
    chain = RuntimeFallbackAiProvider(
        [("profile_mtplx", primary), ("profile_cms", fallback)]
    )

    chain.timeout_seconds = 900

    assert primary.timeout_seconds == 900
    assert fallback.timeout_seconds == 900


def test_prefill_accepts_gateway_verified_fallback_chain_without_fake_model_key():
    primary = _Provider("mtplx", "qwen-local", failure=_http_error(429))
    fallback = _Provider("cms-router", "deepseek-latest-cloud")
    chain = RuntimeFallbackAiProvider(
        [("profile_mtplx", primary), ("profile_cms", fallback)]
    )
    adapter = DeepSeekPrefillAdapter(provider=chain, model_name="qwen-local")

    assert adapter._call_provider({"project": "synthetic"}) == {"status": "ok"}
    assert chain.model_name == "deepseek-latest-cloud"
