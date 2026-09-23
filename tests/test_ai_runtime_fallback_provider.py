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


# ---------------------------------------------------------------------------
# R03/R05: execution-route identity and per-attempt trail
# ---------------------------------------------------------------------------


def test_chain_identity_changes_when_endpoint_changes():
    class _Routed(_Provider):
        pass

    def _chain(base_url, expected=""):
        provider = _Routed("mtplx", "qwen-local")
        provider.base_url = base_url
        provider.transport_name = "openai_compatible"
        provider.expected_response_model = expected
        provider.profile_revision = "7"
        return RuntimeFallbackAiProvider([("profile_mtplx", provider)])

    on_8002 = _chain("http://127.0.0.1:8002/v1")
    on_11234 = _chain("http://127.0.0.1:11234/v1")
    same_again = _chain("http://127.0.0.1:8002/v1")
    assert on_8002.fallback_chain_id != on_11234.fallback_chain_id
    assert on_8002.fallback_chain_id == same_again.fallback_chain_id


def test_run_records_per_attempt_metadata_trail():
    primary = _Provider(
        "mtplx",
        "qwen-local",
        failure=_http_error(429),
    )
    primary.base_url = "http://127.0.0.1:8002/v1"
    primary.expected_response_model = "mtplx-flash-next-optimized-speed"
    fallback = _Provider("cms-router", "deepseek-latest-cloud")
    fallback.base_url = "http://localhost:20128/v1"
    chain = RuntimeFallbackAiProvider(
        [("profile_mtplx", primary), ("profile_cms", fallback)]
    )
    chain.run(SimpleNamespace())

    attempts = chain.attempts
    assert [item["depth"] for item in attempts] == [0, 1]
    assert attempts[0]["ok"] is False
    assert attempts[0]["failure_reason"] == "provider_http_error:429"
    assert attempts[0]["endpoint"] == "http://127.0.0.1:8002/v1"
    assert attempts[0]["expected_response_model"] == (
        "mtplx-flash-next-optimized-speed"
    )
    assert attempts[1]["ok"] is True
    assert "started_at" in attempts[1] and "duration_ms" in attempts[1]
    # no prompt/response bodies in the trail
    assert all("envelope" not in item for item in attempts)
