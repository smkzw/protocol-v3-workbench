"""Direct API transport adapter for the Protocol v3 Harness (Task 1.7).

The Direct API adapter wraps an injected callable that represents a direct
provider API call (DeepSeek chat completions, Paddle official async job
submission/polling, etc.).  The adapter itself performs **no** network access:
the injected callable owns all physical side effects, which makes the adapter
fully deterministic under a fake callable.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` section
17.2.  The adapter obeys the same offline discipline as the harness:

* a **mandatory** first-use connectivity probe is injected (no ``lambda: True``
  default); only a successful probe is cached (the
  :class:`~app.protocol_workflow.runtime.harness.ProbePolicy` enforces this);
* a pure :meth:`preflight` returns a stable rejection error for
  identity/provider/model mismatches *before* the physical transport boundary;
* ``max_turns=1`` is never set — the adapter dispatches exactly once per
  validated request and never auto-re-dispatches on latency or unknown
  outcome;
* the typed receipt owns the observed provider/model identity (runtime
  authority), a logical output artifact ref and the output schema ref.

The adapter is role-aware: it knows which Direct-API provider/model identity
it represents so it can refuse a request whose declared provider/model does
not match (defence-in-depth against a misrouted contract).  It never edits
the shared workload gate and never makes a live OCR/translation call.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.protocol_workflow.runtime.harness import (
    AdapterOutcome,
    DispatchReceipt,
    HarnessDispatchRequest,
)

__all__ = ["DirectApiAdapter"]


# A Direct API callable receives the policy-validated request payload and
# returns a receipt-shaped mapping.  The adapter normalises the mapping into
# a typed :class:`DispatchReceipt`.
DirectApiCallable = Callable[[dict[str, object]], dict[str, object]]

# A mandatory probe callable.  Must be injected; there is no default.
DirectApiProbe = Callable[[], bool]


class DirectApiAdapter:
    """Injected Direct API transport adapter.

    Parameters
    ----------
    provider:
        The provider identity this adapter represents (e.g. ``"deepseek"``,
        ``"paddle-official"``).  Used for probe caching and defence-in-depth
        routing checks.
    model:
        The model identity this adapter represents.
    dispatch_fn:
        The injected callable that performs the physical Direct API call.
        Under a deterministic fake it returns a fixed receipt mapping; in
        production it would call the provider API.  The callable MUST return
        a mapping with ``provider_session_id``, ``output_sha256``,
        ``output_artifact_ref``, ``output_schema_ref``,
        ``observed_provider`` and ``observed_model``.
    probe_fn:
        **Mandatory** injected probe callable.  A real adapter injects a
        cheap connectivity check.  There is no default — missing probes are
        rejected at construction.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        dispatch_fn: DirectApiCallable,
        probe_fn: DirectApiProbe,
    ) -> None:
        if not provider.strip():
            raise ValueError("DirectApiAdapter provider must be non-empty")
        if not model.strip():
            raise ValueError("DirectApiAdapter model must be non-empty")
        if dispatch_fn is None:
            raise ValueError("DirectApiAdapter dispatch_fn must be injected")
        if probe_fn is None:
            raise ValueError(
                "DirectApiAdapter probe_fn must be injected; "
                "no lambda: True default is permitted"
            )
        self._provider = provider.strip()
        self._model = model.strip()
        self._dispatch_fn = dispatch_fn
        self._probe_fn = probe_fn

    @property
    def identity(self) -> str:
        """Stable adapter identity for probe caching.

        The identity is the ``provider/model/harness`` triple so two adapters
        pointing at the same provider/model but different harnesses
        (``direct-api`` vs a future CLI harness) get independent probe caches.
        """
        return f"direct-api:{self._provider}:{self._model}"

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def harness(self) -> str:
        return "direct-api"

    def preflight(self, request: HarnessDispatchRequest) -> AdapterOutcome:
        """Pure pre-dispatch check returning a stable rejection error.

        Identity/provider/model mismatches are caught here so they report
        ``dispatched=False`` and never enter the physical transport boundary.
        """
        if request.provider != self._provider:
            return AdapterOutcome(
                error_code="adapter_provider_mismatch",
                error_message=(
                    f"DirectApiAdapter provider mismatch: "
                    f"adapter={self._provider!r} request={request.provider!r}"
                ),
            )
        if request.model != self._model:
            return AdapterOutcome(
                error_code="adapter_model_mismatch",
                error_message=(
                    f"DirectApiAdapter model mismatch: "
                    f"adapter={self._model!r} request={request.model!r}"
                ),
            )
        return AdapterOutcome()

    def probe(self) -> bool:
        """Return ``True`` iff the injected probe callable reports reachable."""
        return bool(self._probe_fn())

    def dispatch(
        self,
        request: HarnessDispatchRequest,
        *,
        session_id: str | None = None,
        lease: Mapping[str, Any] | None = None,
    ) -> DispatchReceipt:
        """Dispatch *request* through the injected callable.

        The adapter never sets ``max_turns=1`` and never auto-re-dispatches.
        ``session_id`` is accepted for same-session recovery; ``lease`` carries
        the active workload-gate lease for OCR/translation roles (ignored by
        Direct API transports that do not use the gate admission metadata).

        All receipt fields must be present in the physical transport mapping;
        the adapter never fabricates ``observed_provider``, ``observed_model``,
        ``output_schema_ref`` or any other field from registry/request text.
        """
        payload = request.to_payload()
        raw = self._dispatch_fn(payload)
        if not isinstance(raw, dict):
            raise TypeError(
                "DirectApiAdapter dispatch_fn must return a mapping, got "
                f"{type(raw).__name__}"
            )
        _REQUIRED_RECEIPT_KEYS = (
            "provider_session_id",
            "output_sha256",
            "observed_provider",
            "observed_model",
            "output_artifact_ref",
            "output_schema_ref",
        )
        missing = [k for k in _REQUIRED_RECEIPT_KEYS if not str(raw.get(k, "")).strip()]
        if missing:
            raise ValueError(
                f"DirectApiAdapter dispatch_fn mapping is missing/blank receipt "
                f"field(s): {missing}"
            )
        return DispatchReceipt(
            provider_session_id=str(raw["provider_session_id"]),
            output_sha256=str(raw["output_sha256"]),
            observed_provider=str(raw["observed_provider"]),
            observed_model=str(raw["observed_model"]),
            output_artifact_ref=str(raw["output_artifact_ref"]),
            output_schema_ref=str(raw["output_schema_ref"]),
        )
