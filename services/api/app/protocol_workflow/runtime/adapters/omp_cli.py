"""OMP CLI transport adapter for the Protocol v3 Harness (Task 1.7).

The OMP CLI adapter wraps an injected process/session transport that
represents an ``omp`` invocation.  The adapter itself performs **no** process
spawn, network access or model call: the injected transport owns all physical
side effects, which makes the adapter fully deterministic under a fake
transport.

Authoritative local capability evidence (re-read directly from the local
``omp`` executable at ``/Users/smkzw/.local/bin/omp``)::

    $ omp --help
    omp v17.2.9
    ...
      --provider=<value>           Provider to use (legacy; prefer --model)
      --model=<value>              Model to use (fuzzy match ...)
      --thinking=<value>           Set thinking level: off, minimal, low,
                                    medium, high, xhigh, max, auto
      -p, --print                  Non-interactive mode: process prompt and exit
      --auto-approve               Auto-approve all tool calls (skip approval ...)
      --max-time=<value>           Stop the session after this duration ...
      -r, --resume=<value>         Resume a session (by ID prefix, path, ...)
      --no-tools                   Disable all built-in tools

Key facts confirmed from the local help:

* Non-interactive mode is ``-p``/``--print``; there is no ``--yes`` flag.
* Automatic tool approval is ``--auto-approve``.
* ``--thinking`` accepts exactly ``off|minimal|low|medium|high|xhigh|max|auto``;
  ``on`` is **invalid** and must not be generated.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` section
17.2.  The adapter obeys the same offline discipline as the harness:

* a **mandatory** first-use connectivity probe is injected (no ``lambda: True``
  default); only a successful probe is cached;
* a pure :meth:`preflight` returns a stable rejection error for
  identity/provider/model mismatches *before* the physical transport boundary;
* ``--no-tools`` is never generated — tools stay enabled;
* ``--max-turns 1`` is never generated — the adapter dispatches exactly once
  per validated request and never auto-re-dispatches on latency or unknown
  outcome;
* non-interactive execution is always requested (``-p``);
* automatic tool approval is always requested (``--auto-approve``);
* a long ``--max-time`` is always set so waiting follows the global runner
  contract, never a single-turn cutoff;
* the typed receipt is constructed from all six explicit physical transport
  fields; no field is defaulted or relabeled;
* same-session ``--resume`` is used only when an explicit, non-null session id
  is supplied.  The adapter **never** substitutes the idempotency key for a
  provider session id.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.protocol_workflow.runtime.harness import (
    AdapterOutcome,
    DispatchReceipt,
    HarnessDispatchRequest,
)

__all__ = ["OmpCliAdapter", "build_omp_cli_plan"]


# ---------------------------------------------------------------------------
# Injectable transport types
# ---------------------------------------------------------------------------

#: An OMP process/session transport receives the built command plan plus the
#: policy-validated request payload and returns a receipt-shaped mapping.
OmpTransport = Callable[[Sequence[str], dict[str, Any]], dict[str, Any]]

#: A mandatory probe callable.  Must be injected; there is no default.
OmpProbe = Callable[[], bool]


# ---------------------------------------------------------------------------
# Command-plan builder (pure; never executed by the adapter)
# ---------------------------------------------------------------------------

_OMP_ENTRYPOINT = "omp"
_PROVIDER_FLAG = "--provider"
_MODEL_FLAG = "--model"
_THINKING_FLAG = "--thinking"
_PRINT_FLAG = "-p"
_AUTO_APPROVE_FLAG = "--auto-approve"
_MAX_TIME_FLAG = "--max-time"
_RESUME_FLAG = "--resume"
_DEFAULT_MAX_TIME = "3600"

#: The exact set of thinking values accepted by ``omp --thinking`` confirmed
#: from local help: ``off, minimal, low, medium, high, xhigh, max, auto``.
_SUPPORTED_THINKING = frozenset(
    {"off", "minimal", "low", "medium", "high", "xhigh", "max", "auto"}
)

#: Canonical ``ReasoningEffort`` → OMP ``--thinking`` value mapping.
#: ``none`` → ``off``; every other supported effort maps to itself.
_EFFORT_TO_THINKING: dict[str, str] = {
    "none": "off",
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "max",
}


def _resolve_thinking_value(reasoning_effort: str) -> str:
    """Map a contract reasoning effort to the exact OMP ``--thinking`` value."""
    effort = reasoning_effort.strip().lower()
    if effort not in _EFFORT_TO_THINKING:
        raise ValueError(
            f"build_omp_cli_plan unsupported reasoning_effort {effort!r}; "
            f"supported: {sorted(_EFFORT_TO_THINKING)}"
        )
    thinking = _EFFORT_TO_THINKING[effort]
    if thinking not in _SUPPORTED_THINKING:  # pragma: no cover — invariant
        raise ValueError(
            f"internal mapping error: {effort!r} → {thinking!r} not in "
            f"supported thinking set {sorted(_SUPPORTED_THINKING)}"
        )
    return thinking


def build_omp_cli_plan(
    *,
    provider: str,
    model: str,
    reasoning_effort: str,
    session_id: str | None = None,
    max_time: str = _DEFAULT_MAX_TIME,
) -> list[str]:
    """Build the ``omp`` argument list for a dispatch.

    Pure function; never executed by the adapter.
    """
    if not provider.strip():
        raise ValueError("build_omp_cli_plan provider must be non-empty")
    if not model.strip():
        raise ValueError("build_omp_cli_plan model must be non-empty")

    thinking = _resolve_thinking_value(reasoning_effort)

    plan: list[str] = [
        _PROVIDER_FLAG,
        provider.strip(),
        _MODEL_FLAG,
        model.strip(),
        _THINKING_FLAG,
        thinking,
        _PRINT_FLAG,
        _AUTO_APPROVE_FLAG,
        _MAX_TIME_FLAG,
        max_time.strip(),
    ]
    sid = session_id.strip() if session_id is not None else ""
    if sid:
        plan.extend([_RESUME_FLAG, sid])
    return plan


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class OmpCliAdapter:
    """Injected OMP CLI transport adapter.

    Parameters
    ----------
    provider:
        Provider identity this adapter represents.
    model:
        Model identity this adapter represents.
    transport:
        Injected callable performing the physical OMP call.  MUST return a
        mapping with all six receipt fields.
    probe_fn:
        **Mandatory** injected probe callable.  No default.
    entrypoint:
        Optional override of the OMP CLI entrypoint.
    max_time:
        Optional override of the ``--max-time`` ceiling.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        transport: OmpTransport,
        probe_fn: OmpProbe,
        entrypoint: str | None = None,
        max_time: str | None = None,
    ) -> None:
        if not provider.strip():
            raise ValueError("OmpCliAdapter provider must be non-empty")
        if not model.strip():
            raise ValueError("OmpCliAdapter model must be non-empty")
        if transport is None:
            raise ValueError("OmpCliAdapter transport must be injected")
        if probe_fn is None:
            raise ValueError(
                "OmpCliAdapter probe_fn must be injected; "
                "no lambda: True default is permitted"
            )
        self._provider = provider.strip()
        self._model = model.strip()
        self._transport = transport
        self._probe_fn = probe_fn
        self._entrypoint = (entrypoint or _OMP_ENTRYPOINT).strip()
        self._max_time = (max_time or _DEFAULT_MAX_TIME).strip()

    @property
    def identity(self) -> str:
        return f"omp-cli:{self._provider}:{self._model}"

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def harness(self) -> str:
        return "omp-cli"

    def preflight(self, request: HarnessDispatchRequest) -> AdapterOutcome:
        """Pure pre-dispatch check returning a stable rejection error.

        Identity/provider/model mismatches are caught here so they report
        ``dispatched=False`` and never enter the physical transport boundary.
        """
        if request.provider != self._provider:
            return AdapterOutcome(
                error_code="adapter_provider_mismatch",
                error_message=(
                    f"OmpCliAdapter provider mismatch: "
                    f"adapter={self._provider!r} request={request.provider!r}"
                ),
            )
        if request.model != self._model:
            return AdapterOutcome(
                error_code="adapter_model_mismatch",
                error_message=(
                    f"OmpCliAdapter model mismatch: "
                    f"adapter={self._model!r} request={request.model!r}"
                ),
            )
        return AdapterOutcome()

    def build_command_plan(
        self,
        request: HarnessDispatchRequest,
        *,
        session_id: str | None = None,
    ) -> list[str]:
        """Build the full ``omp`` command plan for *request*."""
        args = build_omp_cli_plan(
            provider=request.provider,
            model=request.model,
            reasoning_effort=request.reasoning_effort.value,
            session_id=session_id,
            max_time=self._max_time,
        )
        return [self._entrypoint, *args]

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
        """Dispatch *request* through the injected OMP transport.

        ``session_id`` controls whether the plan appends ``--resume``.
        ``lease`` is accepted for protocol uniformity (ignored — OMP CLI is not
        a gated role).

        All six receipt fields must be present in the physical transport
        mapping; the adapter never fabricates any field.
        """
        plan = self.build_command_plan(request, session_id=session_id)
        raw = self._transport(plan, request.to_payload())
        if not isinstance(raw, dict):
            raise TypeError(
                "OmpCliAdapter transport must return a mapping, got "
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
                f"OmpCliAdapter transport mapping is missing/blank receipt "
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
