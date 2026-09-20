"""Stdlib-only Zhipu (GLM) Direct API product transport (Task 1R.6).

Composes the accepted :class:`~app.protocol_workflow.runtime.adapters.direct_api.DirectApiAdapter`
with a pure-stdlib chat-completions transport for the user-approved default
product profile: ``zhipu-coding-plan`` / ``glm-5.3-flash`` on the official
coding endpoint ``https://open.bigmodel.cn/api/coding/paas/v4/chat/completions``
(pinned by the omp zhipu-coding-plan catalog; NOT the metered generic
endpoint).  Manufacturer-verified reasoning-effort levels are ``low``/``high``/
``max`` with default ``max``.

Offline and security discipline (matching the harness and 1R.6 contract):

* the credential comes from an **injected resolver callable** (the real omp
  resolver is supplied by Codex); this module never reads ``~/.omp`` or any
  credential store, and the resolved credential is used exactly once inside
  the call closure — it never appears in the request JSON body, receipts,
  probe state, ``repr`` or error text;
* the HTTP opener and the output sink are injected; tests inject fakes and
  the adapter stays fully deterministic;
* the probe executes **exactly one** minimal completion (``"ping"``, never
  project or patient payload) and records a safe requested/effective identity
  receipt; there is no automatic credential, model or transport retry — the
  first-use caching discipline is owned by the existing harness
  :class:`~app.protocol_workflow.runtime.harness.ProbePolicy`;
* normal dispatch stores the generated content through the injected output
  sink and returns the real content sha256, the sink's artifact ref, the
  response id and the response ``model`` — identity is never fabricated;
* the provider response carries only ``model``: the observed provider is the
  fixed official transport endpoint identity (``zhipu-coding-plan``), not an
  invented response field;
* blank completions, mismatched models, missing receipt ids and
  empty/truncated (non-``stop``) completions fail typed; raw HTTP error
  bodies are suppressed from durable output; the request timeout is long
  (600s) by design — the controller waits via the runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.protocol_workflow.runtime.adapters.direct_api import DirectApiAdapter
from app.protocol_workflow.runtime.artifact_messages import resolve_artifact_messages

__all__ = [
    "ALLOWED_REASONING_EFFORTS",
    "DEFAULT_MODEL",
    "DEFAULT_REASONING_EFFORT",
    "PROVIDER_ID",
    "REQUEST_TIMEOUT_SECONDS",
    "ZHIPU_CODING_CHAT_COMPLETIONS_ENDPOINT",
    "ZhipuProbeReceipt",
    "ZhipuTransportError",
    "build_zhipu_api_adapter",
]

#: Fixed public provider identity of the official transport endpoint.  The
#: provider response carries only ``model``; this constant is the observed
#: provider — it is never read from the response body.
PROVIDER_ID = "zhipu-coding-plan"

#: User-approved default product model (Plan v2 Task 1R.6).
DEFAULT_MODEL = "glm-5.3-flash"

#: Manufacturer-verified default reasoning effort.
DEFAULT_REASONING_EFFORT = "max"

#: Manufacturer-verified supported reasoning-effort levels.
ALLOWED_REASONING_EFFORTS = ("low", "high", "max")

#: Official coding-plan endpoint pinned by the omp zhipu-coding-plan catalog.
ZHIPU_CODING_CHAT_COMPLETIONS_ENDPOINT = (
    "https://open.bigmodel.cn/api/coding/paas/v4/chat/completions"
)

#: Long timeout by design; the controller waits via the runner.
REQUEST_TIMEOUT_SECONDS = 600

#: Injected callable returning the credential string for one call.
CredentialResolver = Callable[[], str]

#: Injected callable storing generated content and returning a logical
#: artifact ref for the stored output.
OutputSink = Callable[[str], str]
ReceiptSink = Callable[[str, dict[str, Any]], str]


class ZhipuTransportError(RuntimeError):
    """Typed, credential-free transport failure.

    Messages carry only stable status/type facts.  Raw HTTP error bodies are
    deliberately discarded and never reach durable output, error text or logs.
    """


@dataclass(frozen=True)
class ZhipuProbeReceipt:
    """Safe requested/effective identity receipt for the single probe call.

    Carries identity only — never the completion content and never the
    credential.
    """

    requested_model: str
    requested_reasoning_effort: str
    ok: bool
    observed_model: str = ""
    response_id: str = ""
    error: str = ""


class _ZhipuProbeState:
    """Bounded holder for probe receipts, attached to the composed adapter."""

    def __init__(self) -> None:
        self.receipts: tuple[ZhipuProbeReceipt, ...] = ()


def build_zhipu_api_adapter(
    *,
    model: str = DEFAULT_MODEL,
    provider_id: str = PROVIDER_ID,
    provider_label: str = "zhipu",
    credential_resolver: CredentialResolver,
    output_sink: OutputSink | None = None,
    receipt_sink: ReceiptSink | None = None,
    http_opener: Any | None = None,
    endpoint: str = ZHIPU_CODING_CHAT_COMPLETIONS_ENDPOINT,
    timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    expected_response_model_override: str | None = None,
    artifact_text_resolver: Callable[[str, str], str] | None = None,
    max_input_bytes: int | None = None,
) -> DirectApiAdapter:
    """Compose a :class:`DirectApiAdapter` over the stdlib Zhipu transport.

    ``credential_resolver`` and one output sink are mandatory injected
    callables. ``receipt_sink`` persists content and its complete work receipt
    together; the legacy ``output_sink`` remains supported. ``http_opener`` defaults to a stdlib
    ``urllib.request`` opener; tests inject a fake.  The returned adapter
    exposes a ``probe_state`` attribute holding the safe probe receipts.

    Product tasks may supply a resolver for complete, hash-bound text and an
    explicit aggregate byte budget. The default retains the existing snippet
    transport. The resolver receives only selected ref/hash pairs, not a model
    worker or unrestricted filesystem handle.
    """
    if credential_resolver is None:
        raise ValueError("credential_resolver must be injected; no default exists")
    if output_sink is None and receipt_sink is None:
        raise ValueError("output_sink must be injected; no default exists")
    if output_sink is not None and receipt_sink is not None:
        raise ValueError('select one output_sink or receipt_sink')
    if not model.strip():
        raise ValueError("model must be non-empty")
    if artifact_text_resolver is not None:
        if not callable(artifact_text_resolver):
            raise ValueError("artifact_text_resolver must be callable")
        if isinstance(max_input_bytes, bool) or not isinstance(max_input_bytes, int) or max_input_bytes <= 0:
            raise ValueError("full artifact input requires a positive max_input_bytes budget")
    elif max_input_bytes is not None:
        raise ValueError("max_input_bytes requires artifact_text_resolver")
    opener = http_opener if http_opener is not None else urllib.request.build_opener()
    probe_state = _ZhipuProbeState()

    def _complete(body: dict[str, Any]) -> dict[str, Any]:
        """Execute exactly one HTTP completion and return the parsed mapping."""
        try:
            credential = credential_resolver()
        except Exception:
            raise ZhipuTransportError(f"{provider_label} credential resolution failed") from None
        if not isinstance(credential, str) or not credential.strip():
            raise ZhipuTransportError(
                f"{provider_label} credential resolver returned no usable credential"
            )
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {credential}",
            },
            method="POST",
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                status = getattr(response, "status", None) or response.getcode()
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            # Discard the HTTP error body: it must never reach durable
            # output, error text or logs.
            raise ZhipuTransportError(
                f"{provider_label} completion failed with http status {exc.code}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ZhipuTransportError(
                f"{provider_label} transport unreachable: {type(exc).__name__}"
            ) from None
        if status != 200:
            raise ZhipuTransportError(
                f"{provider_label} completion returned http status {status}"
            )
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise ZhipuTransportError(
                f"{provider_label} completion returned invalid json"
            ) from None
        if not isinstance(parsed, dict):
            raise ZhipuTransportError(
                f"{provider_label} completion response must be a json object"
            )
        return parsed

    def _validated_completion(
        parsed: dict[str, Any], *, requested_model: str,
        expected_response_model_override: str | None = None,
    ) -> tuple[str, str, str]:
        """Return ``(response_id, observed_model, content)`` after typed checks."""
        response_id = parsed.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            raise ZhipuTransportError(
                f"{provider_label} completion response is missing a receipt id"
            )
        observed_model = parsed.get("model")
        if not isinstance(observed_model, str) or not observed_model.strip():
            raise ZhipuTransportError(
                f"{provider_label} completion response is missing the model identity"
            )
        # 网关池（OmniRoute 等）可能重写响应 model 字段：部署可用
        # WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL 显式声明出口身份；未声明
        # 时维持严格相等（默认直连行为不变）。
        import os as _os
        expected_override = _os.environ.get(
            "WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL", "").strip() or (
            expected_response_model_override or "")
        expected = expected_override or requested_model
        if observed_model != expected:
            raise ZhipuTransportError(
                f"{provider_label} completion model mismatch: requested "
                f"{requested_model!r}, observed {observed_model!r}"
            )
        choices = parsed.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ZhipuTransportError(
                f"{provider_label} completion response must carry exactly one choice"
            )
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ZhipuTransportError(
                f"{provider_label} completion choice must be a json object"
            )
        if choice.get("finish_reason") != "stop":
            raise ZhipuTransportError(
                "zhipu completion is empty or truncated: finish_reason="
                f"{choice.get('finish_reason')!r}"
            )
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ZhipuTransportError(
                f"{provider_label} completion content is empty or blank"
            )
        return response_id, observed_model, content

    def _completion_body(
        *, effort: str, messages: list[dict[str, str]]
    ) -> dict[str, Any]:
        return {
            "model": model,
            "messages": messages,
            "reasoning_effort": effort,
            "stream": False,
        }

    def _compose_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
        """Compose the minimal user message from bounded artifact material."""
        if artifact_text_resolver is not None:
            def resolve(ref: str, sha256: str) -> str:
                try:
                    return artifact_text_resolver(ref, sha256)
                except Exception:
                    raise ZhipuTransportError("full artifact input resolution failed") from None

            try:
                return resolve_artifact_messages(
                    payload.get("input_artifacts") or [], resolve,
                    max_input_bytes=max_input_bytes,
                )
            except ValueError as exc:
                raise ZhipuTransportError(str(exc)) from None
        parts: list[str] = []
        for artifact in payload.get("input_artifacts") or []:
            if not isinstance(artifact, dict) or not all(
                isinstance(artifact.get(key), str) and artifact[key].strip()
                for key in ("ref", "sha256")
            ):
                raise ZhipuTransportError("dispatch carries a malformed input artifact")
            header = f"[{artifact['ref']} | sha256:{artifact['sha256']}]"
            snippet = artifact.get("snippet") or ""
            parts.append(f"{header}\n{snippet}" if snippet else header)
        return [{"role": "user", "content": "\n\n".join(parts)}]

    def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
        output_schema_ref = str(payload.get("output_schema_ref", "") or "")
        if not output_schema_ref.strip():
            raise ZhipuTransportError("dispatch payload carries no output_schema_ref")
        effort = str(payload.get("reasoning_effort", ""))
        if effort not in ALLOWED_REASONING_EFFORTS:
            raise ZhipuTransportError(
                f"reasoning effort {effort!r} is outside the provider profile "
                f"allowed set {list(ALLOWED_REASONING_EFFORTS)}"
            )
        body = _completion_body(
            effort=effort, messages=_compose_messages(payload)
        )
        parsed = _complete(body)
        response_id, observed_model, content = _validated_completion(
            parsed, requested_model=model,
            expected_response_model_override=expected_response_model_override,
        )
        output_sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
        receipt_data = {
            'provider_session_id': response_id, 'observed_provider': provider_id,
            'observed_model': observed_model, 'output_schema_ref': output_schema_ref,
            'output_sha256': output_sha,
            'node_execution_contract_id': payload['node_execution_contract_id'],
            'logical_call_id': payload['logical_call_id'], 'idempotency_key': payload['idempotency_key'],
            'prompt_sha256': payload['prompt_sha256'], 'requested_reasoning_effort': effort,
            'input_artifacts': [{'ref': a['ref'], 'sha256': a['sha256']}
                                for a in payload.get('input_artifacts') or []],
        }
        artifact_ref = receipt_sink(content, receipt_data) if receipt_sink is not None else output_sink(content)
        if not isinstance(artifact_ref, str) or not artifact_ref.strip():
            raise ZhipuTransportError(
                f"{provider_label} output sink returned no usable artifact ref"
            )
        return {
            "provider_session_id": response_id,
            "output_sha256": output_sha,
            "observed_provider": provider_id,
            "observed_model": observed_model,
            "output_artifact_ref": artifact_ref,
            "output_schema_ref": output_schema_ref,
        }

    def _run_probe_once() -> ZhipuProbeReceipt:
        body = _completion_body(
            effort=DEFAULT_REASONING_EFFORT,
            messages=[{"role": "user", "content": "ping"}],
        )
        try:
            parsed = _complete(body)
            response_id, observed_model, _ = _validated_completion(
                parsed, requested_model=model,
                expected_response_model_override=expected_response_model_override,
            )
        except ZhipuTransportError as exc:
            return ZhipuProbeReceipt(
                requested_model=model,
                requested_reasoning_effort=DEFAULT_REASONING_EFFORT,
                ok=False,
                error=str(exc),
            )
        return ZhipuProbeReceipt(
            requested_model=model,
            requested_reasoning_effort=DEFAULT_REASONING_EFFORT,
            ok=True,
            observed_model=observed_model,
            response_id=response_id,
        )

    def _probe() -> bool:
        receipt = _run_probe_once()
        probe_state.receipts = (*probe_state.receipts, receipt)
        return receipt.ok

    adapter = DirectApiAdapter(
        provider=provider_id,
        model=model,
        dispatch_fn=_dispatch,
        probe_fn=_probe,
    )
    adapter.probe_state = probe_state  # type: ignore[attr-defined]
    # Deployment-level gateway declaration (OmniRoute 等网关会重写响应 model
    # 字段)。Harness 回执身份校验优先采用该声明，回执仍如实记录 API 观察
    # 身份；未声明时保持 request.model 严格相等。
    resolved_override = (
        os.environ.get("WORKBENCH_PROTOCOL_V3_AI_EXPECTED_MODEL", "").strip()
        or (expected_response_model_override or "")
    ).strip()
    if resolved_override:
        adapter.expected_response_model = resolved_override  # type: ignore[attr-defined]
    return adapter
