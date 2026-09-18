"""Offline synthetic tests for the Zhipu (GLM) stdlib product transport.

Task 1R.6.  The transport is exercised through the real
:class:`~app.protocol_workflow.runtime.harness.HarnessDispatcher` +
:class:`~app.protocol_workflow.runtime.adapters.direct_api.DirectApiAdapter`
factory composition with a fake injected HTTP opener, fake output sink and
fake credential resolver.  No service, model, network or credential store is
touched; the credential string is synthetic test material.

Harness ordering note: the dispatcher runs the first-use probe *before* the
transport dispatch, so failure-classification tests replay a successful probe
outcome first and a failing completion outcome second.
"""

from __future__ import annotations

import hashlib
import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from app.protocol_workflow.registries.loader import RoleEntry, _TargetProfile
from app.protocol_workflow.runtime.adapters.direct_api import DirectApiAdapter
from app.protocol_workflow.runtime.adapters.zhipu_api import (
    ALLOWED_REASONING_EFFORTS,
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    PROVIDER_ID,
    REQUEST_TIMEOUT_SECONDS,
    ZHIPU_CODING_CHAT_COMPLETIONS_ENDPOINT,
    ZhipuTransportError,
    build_zhipu_api_adapter,
)
from app.protocol_workflow.runtime.harness import (
    ArtifactRef,
    HarnessDispatcher,
    build_request,
)
from app.protocol_workflow.runtime.product_profiles import (
    select_role_registry_document,
)

from packages.contracts.workbench_contracts.protocol_v3 import (
    CanonicalState,
    NodeExecutionContract,
    ReasoningEffort,
    SensitivityTier,
    SideEffectKind,
    SkillDefinition,
)

# ---------------------------------------------------------------------------
# Deterministic constants and fakes
# ---------------------------------------------------------------------------

FAKE_CREDENTIAL = "test-synthetic-credential-material"
INPUT_ARTIFACT_SHA = "c" * 64
OUTPUT_SCHEMA = "https://protocol-v3.local/schemas/chapter-draft-output.v1.json"
INPUT_SCHEMA = "https://protocol-v3.local/schemas/chapter-draft-input.v1.json"
PROBE_PING = "ping"


def _completion_body(
    *,
    response_id: str = "chatcmpl-test-1",
    model: str = DEFAULT_MODEL,
    content: str = "generated product completion",
    finish_reason: str | None = "stop",
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    return {
        "id": response_id,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], *, status: int = 200) -> None:
        self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _FakeRawResponse(_FakeResponse):
    """A response carrying a raw (possibly non-JSON) body."""

    def __init__(self, body: bytes, *, status: int = 200) -> None:
        super().__init__({})
        self._body = body
        self.status = status


class _FakeOpener:
    """Records every request; replays a list of outcomes (the last repeats)."""

    def __init__(self, outcomes: list[_FakeResponse | Exception]) -> None:
        if not outcomes:
            raise ValueError("at least one outcome is required")
        self._outcomes = list(outcomes)
        self.calls = 0
        self.requests: list[dict[str, Any]] = []

    def open(self, request: Any, timeout: float | None = None) -> Any:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        self.requests.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "data": request.data,
                "method": request.get_method(),
                "timeout": timeout,
            }
        )
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeSink:
    def __init__(self) -> None:
        self.stored: list[str] = []

    def __call__(self, content: str) -> str:
        self.stored.append(content)
        return f"glm-out-{len(self.stored)}"


def _resolver(calls: list[int] | None = None) -> Any:
    def resolve() -> str:
        if calls is not None:
            calls.append(1)
        return FAKE_CREDENTIAL

    return resolve


def _http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        ZHIPU_CODING_CHAT_COMPLETIONS_ENDPOINT,
        status,
        "Internal Server Error" if status == 500 else "Bad Gateway",
        None,
        io.BytesIO(b"provider detail SECRET-BODY-MATERIAL"),
    )


# ---------------------------------------------------------------------------
# GLM role / contract helpers (mirrors the harness-test fixture discipline)
# ---------------------------------------------------------------------------


def _glm_role_entry() -> RoleEntry:
    return RoleEntry(
        role_id="product-llm",
        role_kind="llm",
        description="test glm role",
        thinking_configurable=True,
        default_effort="max",
        allowed_efforts=("low", "high", "max"),
        target_profile=_TargetProfile(
            provider=PROVIDER_ID,
            model=DEFAULT_MODEL,
            harness="direct-api",
            regions=("cn",),
            sensitivity_tier="confidential",
            declared_runtime_note="test target profile",
        ),
    )


def _skill() -> SkillDefinition:
    return SkillDefinition(
        skill_definition_id="skill.chapter-draft",
        skill_version="1.0.0",
        agent_role="full_draft",
        input_schema_ref=INPUT_SCHEMA,
        output_schema_ref=OUTPUT_SCHEMA,
        evidence_requirements=("source-bound-content",),
        allowed_tools=("glm-completion",),
        allowed_paths=("artifacts/chapter-draft/",),
        side_effect_kind=SideEffectKind.CANONICAL_PROPOSAL,
        acceptance_test_ids=("at.chapter-draft.1",),
        canonical_state=CanonicalState.FROZEN,
    )


def _node_contract(
    *,
    effort: ReasoningEffort = ReasoningEffort.MAX,
) -> NodeExecutionContract:
    return NodeExecutionContract(
        node_execution_contract_id="nec:test:1",
        skill_definition_id="skill.chapter-draft",
        role="product-llm",
        harness="direct-api",
        provider=PROVIDER_ID,
        model=DEFAULT_MODEL,
        reasoning_effort=effort,
        provider_session_id=None,
        same_session_recovery=True,
        timeout_seconds=300,
        fallback_policy_id="fbp:default",
        prompt_sha256="b" * 64,
        input_schema_ref=INPUT_SCHEMA,
        output_schema_ref=OUTPUT_SCHEMA,
        allowed_tools=("glm-completion",),
        allowed_paths=("artifacts/chapter-draft/",),
        permission_policy_id="perm:default",
        input_artifact_hashes=(INPUT_ARTIFACT_SHA,),
        sensitivity_tier=SensitivityTier.CONFIDENTIAL,
        allowed_providers=(PROVIDER_ID,),
        allowed_regions=("cn",),
        redaction_policy_id="red:default",
        retention_policy_id="ret:default",
        logical_call_id="lc:chapter-1-draft:1",
        idempotency_key="idem-1",
    )


def _glm_request(*, effort: ReasoningEffort = ReasoningEffort.MAX) -> Any:
    return build_request(
        node_contract=_node_contract(effort=effort),
        skill=_skill(),
        role_entry=_glm_role_entry(),
        artifacts=(ArtifactRef(ref="seed", sha256=INPUT_ARTIFACT_SHA),),
        selected_region="cn",
    )


def _adapter(
    *outcomes: _FakeResponse | Exception,
    sink: _FakeSink | None = None,
    opener: _FakeOpener | None = None,
) -> tuple[DirectApiAdapter, _FakeOpener, _FakeSink]:
    fake_opener = opener or _FakeOpener(list(outcomes))
    fake_sink = sink or _FakeSink()
    adapter = build_zhipu_api_adapter(
        credential_resolver=_resolver(),
        output_sink=fake_sink,
        http_opener=fake_opener,
    )
    return adapter, fake_opener, fake_sink


# ---------------------------------------------------------------------------
# Construction and constants
# ---------------------------------------------------------------------------


def test_transport_constants_match_verified_profile() -> None:
    assert PROVIDER_ID == "zhipu-coding-plan"
    assert DEFAULT_MODEL == "glm-5.3-flash"
    assert DEFAULT_REASONING_EFFORT == "max"
    assert ALLOWED_REASONING_EFFORTS == ("low", "high", "max")
    assert (
        ZHIPU_CODING_CHAT_COMPLETIONS_ENDPOINT
        == "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
    )
    assert REQUEST_TIMEOUT_SECONDS == 600


def test_resolver_and_sink_are_mandatory() -> None:
    with pytest.raises(ValueError, match="credential_resolver"):
        build_zhipu_api_adapter(
            credential_resolver=None,  # type: ignore[arg-type]
            output_sink=_FakeSink(),
        )
    with pytest.raises(ValueError, match="output_sink"):
        build_zhipu_api_adapter(
            credential_resolver=_resolver(),
            output_sink=None,  # type: ignore[arg-type]
        )


def test_adapter_identity_uses_direct_api_composition() -> None:
    adapter, _, _ = _adapter(_FakeResponse(_completion_body()))
    assert isinstance(adapter, DirectApiAdapter)
    assert adapter.identity == f"direct-api:{PROVIDER_ID}:{DEFAULT_MODEL}"
    assert adapter.provider == PROVIDER_ID
    assert adapter.model == DEFAULT_MODEL
    assert adapter.harness == "direct-api"


# ---------------------------------------------------------------------------
# Full harness dispatch path under fake HTTP
# ---------------------------------------------------------------------------


def test_valid_dispatch_through_harness_returns_real_receipt() -> None:
    content = "generated product completion"
    adapter, opener, sink = _adapter(_FakeResponse(_completion_body(content=content)))
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)

    assert result.success is True
    assert result.dispatched is True
    receipt = result.receipt
    assert receipt is not None
    # No fabricated identity: session id and model come from the response.
    assert receipt.provider_session_id == "chatcmpl-test-1"
    assert receipt.observed_provider == PROVIDER_ID
    assert receipt.observed_model == DEFAULT_MODEL
    assert receipt.output_schema_ref == OUTPUT_SCHEMA
    assert receipt.output_artifact_ref == "glm-out-1"
    assert receipt.output_sha256 == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert sink.stored == [content]
    # One probe completion + one product completion; no retries.
    assert opener.calls == 2


def test_dispatch_request_shape_carries_model_effort_and_artifacts() -> None:
    adapter, opener, _ = _adapter(_FakeResponse(_completion_body()))
    HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)

    completion = opener.requests[1]
    assert completion["method"] == "POST"
    assert completion["url"] == ZHIPU_CODING_CHAT_COMPLETIONS_ENDPOINT
    assert completion["timeout"] == REQUEST_TIMEOUT_SECONDS
    body = json.loads(completion["data"].decode("utf-8"))
    assert body["model"] == DEFAULT_MODEL
    assert body["reasoning_effort"] == "max"
    assert body["stream"] is False
    assert body["messages"][0]["role"] == "user"
    assert "seed" in body["messages"][0]["content"]
    # The credential travels only in the Authorization header, never the body.
    assert FAKE_CREDENTIAL not in completion["data"].decode("utf-8")
    headers = {k.lower(): v for k, v in completion["headers"].items()}
    assert headers["authorization"] == f"Bearer {FAKE_CREDENTIAL}"


def test_default_registry_profile_drives_the_full_harness_path() -> None:
    """The committed default registry profile must satisfy the harness and the
    composed transport end-to-end under fake HTTP."""
    document = select_role_registry_document(confirm_alternative=False)
    role_entry = next(role for role in document.roles if role.role_kind == "llm")
    contract = _node_contract()
    assert contract.provider == role_entry.target_profile.provider
    assert contract.model == role_entry.target_profile.model
    adapter, opener, _ = _adapter(_FakeResponse(_completion_body()))
    result = HarnessDispatcher().dispatch(
        request=build_request(
            node_contract=contract,
            skill=_skill(),
            role_entry=role_entry,
            artifacts=(ArtifactRef(ref="seed", sha256=INPUT_ARTIFACT_SHA),),
            selected_region="cn",
        ),
        adapter=adapter,
    )
    assert result.success is True
    assert result.receipt is not None
    assert result.receipt.observed_model == role_entry.target_profile.model
    assert opener.calls == 2


# ---------------------------------------------------------------------------
# Probe discipline: exactly one minimal completion, cached first-use
# ---------------------------------------------------------------------------


def test_probe_executes_exactly_one_minimal_completion() -> None:
    adapter, opener, sink = _adapter(_FakeResponse(_completion_body()))
    assert adapter.probe() is True
    assert opener.calls == 1
    probe = opener.requests[0]
    body = json.loads(probe["data"].decode("utf-8"))
    assert body["model"] == DEFAULT_MODEL
    assert body["reasoning_effort"] == DEFAULT_REASONING_EFFORT
    # The probe carries a minimal ping, never artifact or project payload.
    assert body["messages"] == [{"role": "user", "content": PROBE_PING}]
    assert "seed" not in probe["data"].decode("utf-8")
    # Probe content is never written to the output sink.
    assert sink.stored == []
    receipts = getattr(adapter, "probe_state").receipts
    assert len(receipts) == 1
    assert receipts[0].ok is True
    assert receipts[0].requested_model == DEFAULT_MODEL
    assert receipts[0].observed_model == DEFAULT_MODEL
    assert receipts[0].response_id == "chatcmpl-test-1"
    assert FAKE_CREDENTIAL not in str(receipts[0])


def test_probe_failure_records_safe_receipt_once() -> None:
    adapter, opener, _ = _adapter(_http_error(502))
    assert adapter.probe() is False
    assert opener.calls == 1
    receipts = getattr(adapter, "probe_state").receipts
    assert len(receipts) == 1
    assert receipts[0].ok is False
    assert receipts[0].observed_model == ""
    assert receipts[0].response_id == ""
    # The raw HTTP error body never reaches the durable receipt.
    assert "SECRET-BODY-MATERIAL" not in str(receipts[0])


def test_cached_probe_failure_prevents_reprobe_and_dispatch() -> None:
    adapter, opener, _ = _adapter(_http_error(502))
    dispatcher = HarnessDispatcher()
    r1 = dispatcher.dispatch(request=_glm_request(), adapter=adapter)
    r2 = dispatcher.dispatch(request=_glm_request(), adapter=adapter)
    assert r1.success is False
    assert r1.error_code == "probe_failed"
    assert r1.dispatched is False
    assert r2.error_code == "probe_failed"
    # Exactly one probe call ever; the cached failure is not retried and no
    # product completion ran.
    assert opener.calls == 1
    assert len(getattr(adapter, "probe_state").receipts) == 1


def test_cached_probe_prevents_reprobe_on_subsequent_dispatch() -> None:
    adapter, opener, _ = _adapter(_FakeResponse(_completion_body()))
    dispatcher = HarnessDispatcher()
    assert dispatcher.dispatch(request=_glm_request(), adapter=adapter).success
    assert dispatcher.dispatch(request=_glm_request(), adapter=adapter).success
    # Two product completions + exactly one first-use probe.
    assert opener.calls == 3
    assert len(getattr(adapter, "probe_state").receipts) == 1


# ---------------------------------------------------------------------------
# Dispatch failure classification (typed, no product completion where blocked)
# ---------------------------------------------------------------------------


def test_glm_role_rejects_medium_effort_at_request_build() -> None:
    with pytest.raises(Exception, match="allowed_efforts"):
        build_request(
            node_contract=_node_contract(effort=ReasoningEffort.MEDIUM),
            skill=_skill(),
            role_entry=_glm_role_entry(),
            artifacts=(ArtifactRef(ref="seed", sha256=INPUT_ARTIFACT_SHA),),
            selected_region="cn",
        )


def test_effort_outside_provider_profile_fails_before_product_http() -> None:
    """Transport-level defence-in-depth: a request that reached the transport
    through a permissive role fixture still fails typed before any product
    completion HTTP call."""
    permissive_role = RoleEntry(
        role_id="product-llm",
        role_kind="llm",
        description="permissive test role",
        thinking_configurable=True,
        default_effort="max",
        allowed_efforts=("low", "medium", "high", "max"),
        target_profile=_TargetProfile(
            provider=PROVIDER_ID,
            model=DEFAULT_MODEL,
            harness="direct-api",
            regions=("cn",),
            sensitivity_tier="confidential",
            declared_runtime_note="test target profile",
        ),
    )
    request = build_request(
        node_contract=_node_contract(effort=ReasoningEffort.MEDIUM),
        skill=_skill(),
        role_entry=permissive_role,
        artifacts=(ArtifactRef(ref="seed", sha256=INPUT_ARTIFACT_SHA),),
        selected_region="cn",
    )
    adapter, opener, _ = _adapter(_FakeResponse(_completion_body()))
    result = HarnessDispatcher().dispatch(request=request, adapter=adapter)
    assert result.success is False
    assert "outside the provider profile" in (result.error_message or "")
    # Only the first-use probe ran; the product completion never executed.
    assert opener.calls == 1
    assert len(opener.requests) == 1


def test_model_mismatch_rejected_without_sink_write() -> None:
    adapter, _, sink = _adapter(
        _FakeResponse(_completion_body()),
        _FakeResponse(_completion_body(model="glm-4.7-air")),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert "model mismatch" in (result.error_message or "")
    assert sink.stored == []


def test_missing_receipt_id_rejected() -> None:
    body = _completion_body()
    body["id"] = "  "
    adapter, _, sink = _adapter(
        _FakeResponse(_completion_body()),
        _FakeResponse(body),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert "receipt id" in (result.error_message or "")
    assert sink.stored == []


def test_blank_completion_rejected() -> None:
    adapter, _, sink = _adapter(
        _FakeResponse(_completion_body()),
        _FakeResponse(_completion_body(content="   ")),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert "empty or blank" in (result.error_message or "")
    assert sink.stored == []


def test_truncated_completion_rejected() -> None:
    adapter, _, sink = _adapter(
        _FakeResponse(_completion_body()),
        _FakeResponse(_completion_body(finish_reason="length")),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert "truncated" in (result.error_message or "")
    assert sink.stored == []


def test_missing_finish_reason_rejected() -> None:
    adapter, _, _ = _adapter(
        _FakeResponse(_completion_body()),
        _FakeResponse(_completion_body(finish_reason=None)),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert "truncated" in (result.error_message or "")


def test_non_json_completion_body_rejected() -> None:
    adapter, _, sink = _adapter(
        _FakeResponse(_completion_body()),
        _FakeRawResponse(b"[1, 2, 3]"),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert "json" in (result.error_message or "")
    assert sink.stored == []


def test_http_error_body_is_suppressed_from_durable_output() -> None:
    adapter, _, _ = _adapter(
        _FakeResponse(_completion_body()),
        _http_error(500),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert result.dispatched is True
    assert "SECRET-BODY-MATERIAL" not in (result.error_message or "")
    assert "http status 500" in (result.error_message or "")


def test_transport_error_type_is_typed_and_reason_free() -> None:
    adapter, _, _ = _adapter(
        _FakeResponse(_completion_body()),
        urllib.error.URLError(OSError("connection refused")),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert result.error_code == "dispatch_exception"
    assert result.error_message.startswith(f"{ZhipuTransportError.__name__}: ")
    assert "connection refused" not in (result.error_message or "")


def test_non_200_status_rejected() -> None:
    adapter, _, _ = _adapter(
        _FakeResponse(_completion_body()),
        _FakeResponse(_completion_body(), status=201),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert "http status 201" in (result.error_message or "")


# ---------------------------------------------------------------------------
# Credential hygiene
# ---------------------------------------------------------------------------


def test_credential_never_appears_in_receipt_or_probe_material() -> None:
    adapter, opener, sink = _adapter(_FakeResponse(_completion_body()))
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is True
    assert result.receipt is not None
    assert FAKE_CREDENTIAL not in str(result.receipt)
    assert FAKE_CREDENTIAL not in repr(adapter)
    assert FAKE_CREDENTIAL not in sink.stored[0]
    probe_receipts = getattr(adapter, "probe_state").receipts
    for receipt in probe_receipts:
        assert FAKE_CREDENTIAL not in repr(receipt)
    # The transport never carries the credential in the JSON request body.
    body_text = opener.requests[1]["data"].decode("utf-8")
    assert FAKE_CREDENTIAL not in body_text


def test_blank_resolved_credential_fails_typed_at_dispatch() -> None:
    resolver_calls: list[int] = []

    def sequence_resolver() -> str:
        resolver_calls.append(1)
        if len(resolver_calls) == 1:
            return FAKE_CREDENTIAL
        return "   "

    adapter = build_zhipu_api_adapter(
        credential_resolver=sequence_resolver,
        output_sink=_FakeSink(),
        http_opener=_FakeOpener([_FakeResponse(_completion_body())]),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert result.error_code == "dispatch_exception"
    assert "credential" in (result.error_message or "")
    assert result.receipt is None
    # One probe + one attempted dispatch: no transport retry loop.
    assert len(resolver_calls) == 2


def test_blank_probe_credential_fails_closed_at_probe() -> None:
    def blank_resolver() -> str:
        return "   "

    adapter = build_zhipu_api_adapter(
        credential_resolver=blank_resolver,
        output_sink=_FakeSink(),
        http_opener=_FakeOpener([_FakeResponse(_completion_body())]),
    )
    result = HarnessDispatcher().dispatch(request=_glm_request(), adapter=adapter)
    assert result.success is False
    assert result.error_code == "probe_failed"
    receipts = getattr(adapter, "probe_state").receipts
    assert receipts[0].ok is False
    assert "credential" in receipts[0].error


def test_raising_resolver_produces_failed_probe_receipt() -> None:
    from app.protocol_workflow.runtime.omp_credentials import OmpCredentialError

    def unavailable():
        raise OmpCredentialError("omp_credentials_unavailable")

    opener = _FakeOpener([_FakeResponse(_completion_body())])
    adapter = build_zhipu_api_adapter(
        credential_resolver=unavailable, output_sink=_FakeSink(), http_opener=opener,
    )
    assert adapter.probe() is False
    assert opener.calls == 0
    assert len(adapter.probe_state.receipts) == 1
    assert adapter.probe_state.receipts[0].error == "zhipu credential resolution failed"


def test_missing_output_schema_rejected_before_http_and_sink() -> None:
    adapter, opener, sink = _adapter(_FakeResponse(_completion_body()))
    payload = _glm_request().to_payload()
    payload["output_schema_ref"] = ""
    with pytest.raises(ZhipuTransportError, match="output_schema_ref"):
        adapter._dispatch_fn(payload)
    assert opener.calls == 0
    assert sink.stored == []


def test_malformed_artifact_rejected_typed_before_http() -> None:
    adapter, opener, sink = _adapter(_FakeResponse(_completion_body()))
    payload = _glm_request().to_payload()
    payload["input_artifacts"] = [{"ref": "missing-hash"}]
    with pytest.raises(ZhipuTransportError, match="artifact"):
        adapter._dispatch_fn(payload)
    assert opener.calls == 0
    assert sink.stored == []


# ---------------------------------------------------------------------------
# Registry-driven profile discipline
# ---------------------------------------------------------------------------


def test_default_registry_declares_glm_profile_for_both_thinking_roles() -> None:
    document = select_role_registry_document(confirm_alternative=False)
    for role_kind in ("llm", "ocr_translation_support"):
        role = next(role for role in document.roles if role.role_kind == role_kind)
        assert role.target_profile.provider == PROVIDER_ID
        assert role.target_profile.model == DEFAULT_MODEL
        assert role.default_effort == DEFAULT_REASONING_EFFORT
        assert tuple(role.allowed_efforts) == ALLOWED_REASONING_EFFORTS
