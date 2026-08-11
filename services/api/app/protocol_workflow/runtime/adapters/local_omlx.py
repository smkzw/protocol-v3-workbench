"""Local oMLX transport adapter for the Protocol v3 Harness (Task 1.7).

The local oMLX adapter wraps an injected callable that represents a local oMLX
model call (translation via ``dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX``).  The
unified workload-gate policy (effective model selection + real lease) now
lives at the common :class:`~app.protocol_workflow.runtime.harness.HarnessDispatcher`
boundary, so this adapter focuses on the physical transport: it receives the
active gate lease from the dispatcher and forwards it to the injected
callable.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` sections
17.2 and 18; accepted Task 1.7 contract.

Key rules preserved by this adapter:

* **Mandatory probe injection.**  ``probe_fn`` must be injected; there is no
  ``lambda: True`` default.

* **Pure preflight.**  Identity/provider/model mismatches are caught in
  :meth:`preflight` so they report ``dispatched=False`` and never enter the
  physical transport boundary.

* **Lease forwarding.**  The dispatcher acquires the correct
  ``ocr``/``translation`` lease at the common boundary and passes it to
  :meth:`dispatch`; the adapter forwards it to the injected callable so the
  physical transport can use the admission metadata.

* **No relabel.**  The observed identity comes from the runtime receipt only;
  the adapter never relabels output as the declared model.

* **No ``max_turns=1``.**  The adapter dispatches exactly once per validated
  request and never auto-re-dispatches.

The adapter performs **no** network, model, OCR or translation access on its
own: the dispatch callable is injected.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from app.protocol_workflow.runtime.harness import (
    AdapterOutcome,
    DispatchReceipt,
    HarnessDispatchRequest,
    HarnessPolicyError,
)

__all__ = ["LocalOmlxAdapter", "OcrRoleGateMismatchError"]


# ---------------------------------------------------------------------------
# Errors (retained for import-compatibility with existing callers/tests)
# ---------------------------------------------------------------------------


class OcrRoleGateMismatchError(HarnessPolicyError):
    """A declared OCR role cannot be executed by the current shared gate.

    .. deprecated::
        Gate consistency is now enforced at the common
        :class:`~app.protocol_workflow.runtime.harness.HarnessDispatcher`
        boundary via :class:`~app.protocol_workflow.runtime.harness.WorkloadGateError`.
        This class is retained for import compatibility.
    """


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

#: A local oMLX dispatch callable receives the policy-validated request
#: payload plus the active gate lease mapping and returns a receipt-shaped
#: mapping.
OmlxDispatchCallable = Callable[
    [dict[str, Any], Mapping[str, Any]],
    dict[str, Any],
]

#: A mandatory probe callable.  Must be injected; there is no default.
OmlxProbeCallable = Callable[[], bool]


class LocalOmlxAdapter:
    """Injected local oMLX transport adapter.

    Parameters
    ----------
    provider:
        The provider identity this adapter represents (``"local-omlx"``).
    model:
        The model identity this adapter represents (translation model).
    dispatch_fn:
        The injected callable that performs the physical local oMLX call.
        It receives the policy-validated request payload plus the active gate
        lease mapping and returns a receipt-shaped mapping.
    probe_fn:
        **Mandatory** injected probe callable.  There is no default.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        dispatch_fn: OmlxDispatchCallable,
        probe_fn: OmlxProbeCallable,
    ) -> None:
        if not provider.strip():
            raise ValueError("LocalOmlxAdapter provider must be non-empty")
        if not model.strip():
            raise ValueError("LocalOmlxAdapter model must be non-empty")
        if dispatch_fn is None:
            raise ValueError("LocalOmlxAdapter dispatch_fn must be injected")
        if probe_fn is None:
            raise ValueError(
                "LocalOmlxAdapter probe_fn must be injected; "
                "no lambda: True default is permitted"
            )
        self._provider = provider.strip()
        self._model = model.strip()
        self._dispatch_fn = dispatch_fn
        self._probe_fn = probe_fn

    @property
    def identity(self) -> str:
        """Stable adapter identity for probe caching."""
        return f"local-omlx:{self._provider}:{self._model}"

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def harness(self) -> str:
        return "local-omlx"

    def preflight(self, request: HarnessDispatchRequest) -> AdapterOutcome:
        """Pure pre-dispatch check returning a stable rejection error."""
        if request.provider != self._provider:
            return AdapterOutcome(
                error_code="adapter_provider_mismatch",
                error_message=(
                    f"LocalOmlxAdapter provider mismatch: "
                    f"adapter={self._provider!r} request={request.provider!r}"
                ),
            )
        if request.model != self._model:
            return AdapterOutcome(
                error_code="adapter_model_mismatch",
                error_message=(
                    f"LocalOmlxAdapter model mismatch: "
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

        The active gate lease (acquired by the dispatcher at the common
        boundary) is forwarded to the injected callable.  The adapter never
        sets ``max_turns=1`` and never auto-re-dispatches.

        All receipt fields must be present in the physical transport mapping;
        the adapter never fabricates ``observed_provider``, ``observed_model``,
        ``output_schema_ref`` or any other field from registry/request text.
        """
        active_lease: Mapping[str, Any] = lease if lease is not None else {}
        raw = self._dispatch_fn(request.to_payload(), active_lease)
        if not isinstance(raw, dict):
            raise TypeError(
                "LocalOmlxAdapter dispatch_fn must return a mapping, got "
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
                f"LocalOmlxAdapter dispatch_fn mapping is missing/blank receipt "
                f"field(s): {missing}"
            )
        # The observed identity comes from the runtime receipt only; the
        # adapter never relabels output as the declared model.
        return DispatchReceipt(
            provider_session_id=str(raw["provider_session_id"]),
            output_sha256=str(raw["output_sha256"]),
            observed_provider=str(raw["observed_provider"]),
            observed_model=str(raw["observed_model"]),
            output_artifact_ref=str(raw["output_artifact_ref"]),
            output_schema_ref=str(raw["output_schema_ref"]),
        )
