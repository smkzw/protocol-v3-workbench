"""Deployment-level gateway overrides for the DeepSeek direct-API transport.

T17 round 10/11 regression tests.  The OmniRoute key-pool gateway rewrites
the response ``model`` field (``deepseek-flash`` → the pool's exit identity)
and historically required a deployment override to (a) point the adapter at
the gateway endpoint, (b) declare the expected exit identity, and (c) keep
harness receipt-identity validation green.  The endpoint override was
documented but never implemented, which sent gateway credentials to
api.deepseek.com (401 → ``probe_failed`` → ``unknown_outcome`` with no
diagnostics).  These tests lock each layer of the corrected behaviour.

Offline synthetic tests only: fake opener, fake sink, synthetic credential;
no service, model or network is touched.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.protocol_workflow.registries.loader import RoleEntry, _TargetProfile
from app.protocol_workflow.runtime.adapters.deepseek_api import (
    DEEPSEEK_CHAT_COMPLETIONS_ENDPOINT,
    DEEPSEEK_DEFAULT_MODEL,
    build_deepseek_api_adapter,
)
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.harness import (
    ArtifactRef,
    build_request,
)
from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    NodeExecutionContract,
    ReasoningEffort,
    SensitivityTier,
    SideEffectKind,
    SkillDefinition,
)

FAKE_CREDENTIAL = "test-synthetic-gateway-key"
INPUT_ARTIFACT_SHA = "c" * 64
OUTPUT_SCHEMA = "research-seed.generate.v1"
GATEWAY_ENDPOINT = "http://gateway.internal:20128/v1/chat/completions"
EXIT_MODEL = "deepseek-latest-cloud"


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.status = 200

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _FakeOpener:
    def __init__(self, outcomes: list[_FakeResponse]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    def open(self, request: Any, timeout: float | None = None) -> Any:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        self.requests.append({"url": request.full_url, "data": request.data})
        return outcome


class _FakeSink:
    def __init__(self) -> None:
        self.stored: list[str] = []

    def __call__(self, content: str) -> str:
        self.stored.append(content)
        return f"out-{len(self.stored)}"


def _completion(model: str, content: str = "generated completion") -> _FakeResponse:
    return _FakeResponse({
        "id": "chatcmpl-gw-1",
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    })


def _role_entry() -> RoleEntry:
    return RoleEntry(
        role_id="product-llm",
        role_kind="llm",
        description="test gateway role",
        thinking_configurable=True,
        default_effort="max",
        allowed_efforts=("low", "high", "max"),
        target_profile=_TargetProfile(
            provider="deepseek",
            model=DEEPSEEK_DEFAULT_MODEL,
            harness="direct-api",
            regions=("cn",),
            sensitivity_tier="confidential",
            declared_runtime_note="test target profile",
        ),
    )


def _contract() -> NodeExecutionContract:
    return NodeExecutionContract(
        node_execution_contract_id="nec:gw:1",
        skill_definition_id="skill.research-seed-proposal",
        role="product-llm",
        harness="direct-api",
        provider="deepseek",
        model=DEEPSEEK_DEFAULT_MODEL,
        reasoning_effort=ReasoningEffort.MAX,
        provider_session_id=None,
        same_session_recovery=True,
        timeout_seconds=600,
        fallback_policy_id="fbp:default",
        prompt_sha256="b" * 64,
        input_schema_ref="research-seed.generate-input.v1",
        output_schema_ref=OUTPUT_SCHEMA,
        allowed_tools=("glm-completion",),
        allowed_paths=("artifacts/research-seed/",),
        permission_policy_id="perm:default",
        input_artifact_hashes=(INPUT_ARTIFACT_SHA,),
        sensitivity_tier="confidential",
        allowed_providers=("deepseek",),
        allowed_regions=("cn",),
        redaction_policy_id="red:default",
        retention_policy_id="ret:default",
        logical_call_id="lc:seed-generate:1",
        idempotency_key="idem-gw-1",
    )


def _skill() -> SkillDefinition:
    return SkillDefinition(
        skill_definition_id="skill.research-seed-proposal",
        skill_version="1.0.0",
        agent_role="full_draft",
        input_schema_ref="research-seed.generate-input.v1",
        output_schema_ref=OUTPUT_SCHEMA,
        evidence_requirements=("source-bound-content",),
        allowed_tools=("glm-completion",),
        allowed_paths=("artifacts/research-seed/",),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        acceptance_test_ids=("at.seed.1",),
        canonical_state=CanonicalState.FROZEN,
    )


def _request() -> Any:
    return build_request(
        node_contract=_contract(),
        skill=_skill(),
        role_entry=_role_entry(),
        artifacts=(ArtifactRef(ref="research-intake", sha256=INPUT_ARTIFACT_SHA),),
        selected_region="cn",
    )


def _gateway_opener(exit_model: str = EXIT_MODEL) -> _FakeOpener:
    # Probe succeeds against the gateway identity, then the completion.
    return _FakeOpener([_completion(exit_model), _completion(exit_model)])


@pytest.fixture(autouse=True)
def _clean_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "WORKBENCH_PROTOCOL_V3_AI_ENDPOINT",
        "WORKBENCH_PROTOCOL_V3_AI_KEY",
        "WORKBENCH_PROTOCOL_V3_AI_MODEL",
        "WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WORKBENCH_PROTOCOL_V3_AI_KEY", FAKE_CREDENTIAL)


def test_gateway_rewrite_without_declaration_fails_closed() -> None:
    """Default discipline unchanged: with no declaration the transport-level
    identity check rejects the rewritten exit model (strict request-model
    equality), and the failure carries the identity mismatch text."""
    probe_ok = _FakeOpener([
        _completion(DEEPSEEK_DEFAULT_MODEL), _completion(EXIT_MODEL),
    ])
    adapter = build_deepseek_api_adapter(output_sink=_FakeSink(),
                                         http_opener=probe_ok)
    result = HarnessDispatcher().dispatch(request=_request(), adapter=adapter)
    assert result.success is False
    assert result.error_code == "dispatch_exception"
    assert EXIT_MODEL in (result.error_message or "")
    assert "model mismatch" in (result.error_message or "")


def test_gateway_rewrite_with_declaration_passes_and_receipt_stays_honest() -> None:
    """A declared exit identity satisfies harness validation while the
    receipt records the API-observed identity verbatim."""
    adapter = build_deepseek_api_adapter(
        expected_response_model_override=EXIT_MODEL,
        output_sink=_FakeSink(), http_opener=_gateway_opener(),
    )
    assert getattr(adapter, "expected_response_model", None) == EXIT_MODEL
    result = HarnessDispatcher().dispatch(request=_request(), adapter=adapter)
    assert result.success is True, result.error_message
    assert result.receipt is not None
    assert result.receipt.observed_model == EXIT_MODEL
    assert result.receipt.observed_provider == "deepseek"


def test_env_declared_exit_identity_reaches_harness_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL", EXIT_MODEL)
    adapter = build_deepseek_api_adapter(output_sink=_FakeSink(),
                                         http_opener=_gateway_opener())
    assert getattr(adapter, "expected_response_model", None) == EXIT_MODEL
    result = HarnessDispatcher().dispatch(request=_request(), adapter=adapter)
    assert result.success is True, result.error_message


def test_endpoint_env_override_reaches_the_http_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented endpoint override must actually redirect the HTTP
    call — regression for the missing override read that produced 401s
    against the direct endpoint."""
    monkeypatch.setenv("WORKBENCH_PROTOCOL_V3_AI_ENDPOINT", GATEWAY_ENDPOINT)
    monkeypatch.setenv("WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL", EXIT_MODEL)
    opener = _gateway_opener()
    adapter = build_deepseek_api_adapter(output_sink=_FakeSink(),
                                         http_opener=opener)
    assert adapter.probe() is True
    assert opener.calls == 1
    assert opener.requests[0]["url"] == GATEWAY_ENDPOINT
    assert opener.requests[0]["url"] != DEEPSEEK_CHAT_COMPLETIONS_ENDPOINT


def test_no_overrides_keeps_direct_endpoint_and_strict_identity() -> None:
    opener = _FakeOpener([
        _completion(DEEPSEEK_DEFAULT_MODEL), _completion(DEEPSEEK_DEFAULT_MODEL),
    ])
    adapter = build_deepseek_api_adapter(output_sink=_FakeSink(),
                                         http_opener=opener)
    assert getattr(adapter, "expected_response_model", None) is None
    result = HarnessDispatcher().dispatch(request=_request(), adapter=adapter)
    assert result.success is True, result.error_message
    assert opener.requests[0]["url"] == DEEPSEEK_CHAT_COMPLETIONS_ENDPOINT
    assert result.receipt is not None
    assert result.receipt.observed_model == DEEPSEEK_DEFAULT_MODEL
