"""Codex App/CLI transport adapter for the Protocol v3 Harness (Task 1.7).

The Codex App/CLI adapter wraps an injected process/session transport that
represents a ``codex exec`` invocation.  The adapter itself performs **no**
process spawn, network access or model call: the injected transport owns all
physical side effects, which makes the adapter fully deterministic under a
fake transport.

Authoritative local capability evidence (re-read directly from the bundled
``codex`` executable at ``/Applications/ChatGPT.app/Contents/Resources/codex``)::

    $ codex exec --help
    ...
      -m, --model <MODEL>          Model the agent should use
      --output-schema <FILE>       Path to a JSON Schema file describing the
                                    model's final response shape
      --json                       Print events to stdout as JSONL

    $ codex exec resume --help
    Resume a previous session by id or pick the most recent with --last

    Usage: codex exec resume [OPTIONS] [SESSION_ID] [PROMPT]
    ...
      -m, --model <MODEL>          Model the agent should use
      --output-schema <FILE>       Path to a JSON Schema file ...
      --json                       Print events to stdout as JSONL

Key facts confirmed from the local help:

* JSONL output is requested with ``--json``, **not** a nonexistent ``--jsonl``.
* Same-session recovery uses the ``codex exec resume SESSION_ID`` subcommand;
  there is no ``--resume`` flag on ``codex exec``.
* ``--output-schema`` takes a **filesystem path** to a JSON Schema file, not a
  URI.  The request carries schema refs like
  ``https://protocol-v3.local/schemas/chapter-draft-output.v1.json``; the
  adapter resolves them to real local files via an injected
  ``schema_path_resolver`` before command planning.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` section
17.2.  The adapter obeys the same offline discipline as the harness:

* a **mandatory** first-use connectivity probe is injected (no ``lambda: True``
  default); only a successful probe is cached (the
  :class:`~app.protocol_workflow.runtime.harness.ProbePolicy` enforces this);
* a pure :meth:`preflight` returns a stable rejection error for
  identity/provider/model mismatches and schema-resolution failures *before*
  the physical transport boundary;
* ``--max-turns 1`` is never generated — the adapter dispatches exactly once
  per validated request and never auto-re-dispatches on latency or unknown
  outcome;
* ``--no-tools`` is never generated — tools stay enabled;
* the typed receipt is constructed from all six explicit physical transport
  fields (provider session id, output hash, observed provider, observed model,
  logical output artifact ref, output schema ref); no field is defaulted or
  relabeled;
* same-session recovery uses ``codex exec resume SESSION_ID`` only when an
  explicit, non-null session id is supplied.  A new dispatch has no resume
  token.  The adapter **never** substitutes the idempotency key for a
  provider session id.

The adapter is role-aware: it knows the provider/model identity it
represents so it can refuse a request whose declared provider/model does not
match (defence-in-depth against a misrouted contract).  It never edits the
shared workload gate and never makes a live model call.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.protocol_workflow.runtime.harness import (
    AdapterOutcome,
    DispatchReceipt,
    HarnessDispatchRequest,
)

__all__ = ["CodexAppAdapter", "build_codex_exec_plan"]


# ---------------------------------------------------------------------------
# Injectable transport types
# ---------------------------------------------------------------------------

#: A Codex process/session transport receives the built command plan plus the
#: policy-validated request payload and returns a receipt-shaped mapping.
#: Under a deterministic fake it returns a fixed receipt mapping; in
#: production it would spawn/poll ``codex exec`` (or ``codex exec resume``).
CodexTransport = Callable[[Sequence[str], dict[str, Any]], dict[str, Any]]

#: A mandatory probe callable.  Must be injected; there is no default.
CodexProbe = Callable[[], bool]

#: A schema-path resolver maps a request output_schema_ref (a logical URI like
#: ``https://protocol-v3.local/schemas/chapter-draft-output.v1.json``) to a real
#: local JSON Schema file path that ``codex --output-schema`` accepts.  The
#: resolver MUST return a path to an existing regular file; the adapter
#: verifies this in preflight.
SchemaPathResolver = Callable[[str], "str | None"]


# ---------------------------------------------------------------------------
# Command-plan builder (pure; never executed by the adapter)
# ---------------------------------------------------------------------------

#: The default Codex CLI entrypoint used in command plans.
_CODEX_ENTRYPOINT = "codex"

#: The ``exec`` subcommand.
_EXEC_SUBCOMMAND = "exec"

#: The ``resume`` subcommand (nested under ``exec``).
_RESUME_SUBCOMMAND = "resume"

#: The explicit model flag confirmed by ``codex exec --help``.
_MODEL_FLAG = "--model"

#: The JSONL output flag confirmed by ``codex exec --help``.
_JSON_FLAG = "--json"

#: The typed output schema flag confirmed by ``codex exec --help``.
_SCHEMA_FLAG = "--output-schema"


def build_codex_exec_plan(
    *,
    model: str,
    output_schema_path: str,
    session_id: str | None = None,
) -> list[str]:
    """Build the ``codex exec`` argument list for a dispatch.

    This is a **pure** function: it returns the argument list that *would* be
    passed to the Codex CLI, but it never executes anything.  It accepts a
    **local filesystem path** to a JSON Schema file (``output_schema_path``),
    NOT a schema ref URI.  The caller (the adapter) resolves the ref before
    calling this function.

    When ``session_id`` is ``None`` (a new dispatch) the plan is::

        exec --model <model> --json --output-schema <path>

    When ``session_id`` is a non-empty string (same-session recovery) the
    plan uses the ``exec resume`` subcommand::

        exec resume <session_id> --model <model> --json --output-schema <path>

    Both shapes always:

    * select an explicit ``--model``;
    * request JSONL output via ``--json`` (the real flag, not ``--jsonl``);
    * bind the typed ``--output-schema`` to a local file path;
    * keep tools enabled (never generate ``--no-tools``);
    * never generate ``--max-turns 1``.
    """
    if not model.strip():
        raise ValueError("build_codex_exec_plan model must be non-empty")
    if not output_schema_path.strip():
        raise ValueError("build_codex_exec_plan output_schema_path must be non-empty")
    if output_schema_path.strip().lower().startswith(("http://", "https://")):
        raise ValueError(
            "build_codex_exec_plan output_schema_path must be a local file path, "
            "not a schema URI"
        )
    if not output_schema_path.strip().lower().endswith(".json"):
        raise ValueError(
            "build_codex_exec_plan output_schema_path must name a JSON file"
        )

    common_flags = [
        _MODEL_FLAG,
        model.strip(),
        _JSON_FLAG,
        _SCHEMA_FLAG,
        output_schema_path.strip(),
    ]

    sid = session_id.strip() if session_id is not None else ""
    if sid:
        return [_EXEC_SUBCOMMAND, _RESUME_SUBCOMMAND, sid, *common_flags]
    return [_EXEC_SUBCOMMAND, *common_flags]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class CodexAppAdapter:
    """Injected Codex App/CLI transport adapter.

    Parameters
    ----------
    provider:
        The provider identity this adapter represents (e.g. ``"codex-app"``).
    model:
        The model identity this adapter represents.
    transport:
        The injected callable that performs the physical Codex process/session
        call.  MUST return a mapping with all six receipt fields.
    probe_fn:
        **Mandatory** injected probe callable.  There is no default — a missing
        probe is rejected at construction.
    schema_path_resolver:
        **Mandatory** injected resolver that maps a request ``output_schema_ref``
        URI to a real local JSON Schema file path.  The adapter verifies the
        resolved path is an existing regular file in preflight.
    entrypoint:
        Optional override of the Codex CLI entrypoint.  Defaults to ``"codex"``.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        transport: CodexTransport,
        probe_fn: CodexProbe,
        schema_path_resolver: SchemaPathResolver,
        entrypoint: str | None = None,
    ) -> None:
        if not provider.strip():
            raise ValueError("CodexAppAdapter provider must be non-empty")
        if not model.strip():
            raise ValueError("CodexAppAdapter model must be non-empty")
        if transport is None:
            raise ValueError("CodexAppAdapter transport must be injected")
        if probe_fn is None:
            raise ValueError(
                "CodexAppAdapter probe_fn must be injected; "
                "no lambda: True default is permitted"
            )
        if schema_path_resolver is None:
            raise ValueError("CodexAppAdapter schema_path_resolver must be injected")
        self._provider = provider.strip()
        self._model = model.strip()
        self._transport = transport
        self._probe_fn = probe_fn
        self._schema_path_resolver = schema_path_resolver
        self._entrypoint = (entrypoint or _CODEX_ENTRYPOINT).strip()

    @property
    def identity(self) -> str:
        return f"codex-app:{self._provider}:{self._model}"

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    @property
    def harness(self) -> str:
        return "codex-app"

    def _resolve_schema_path(self, output_schema_ref: str) -> str | None:
        """Resolve a schema ref URI to a local file path via the injected resolver.

        Returns the resolved path, or ``None`` if the resolver cannot map it.
        """
        resolved = self._schema_path_resolver(output_schema_ref)
        if resolved is None:
            return None
        value = str(resolved).strip()
        if not value or value.lower().startswith(("http://", "https://")):
            return None
        return os.path.abspath(os.path.expanduser(value))

    def preflight(self, request: HarnessDispatchRequest) -> AdapterOutcome:
        """Pure pre-dispatch check returning a stable rejection error.

        Identity/provider/model mismatches and schema-resolution failures are
        caught here so they report ``dispatched=False`` and never enter the
        physical transport boundary.
        """
        if request.provider != self._provider:
            return AdapterOutcome(
                error_code="adapter_provider_mismatch",
                error_message=(
                    f"CodexAppAdapter provider mismatch: "
                    f"adapter={self._provider!r} request={request.provider!r}"
                ),
            )
        if request.model != self._model:
            return AdapterOutcome(
                error_code="adapter_model_mismatch",
                error_message=(
                    f"CodexAppAdapter model mismatch: "
                    f"adapter={self._model!r} request={request.model!r}"
                ),
            )
        # Schema ref must resolve to a real local JSON Schema file.
        schema_path = self._resolve_schema_path(request.output_schema_ref)
        if schema_path is None:
            return AdapterOutcome(
                error_code="schema_ref_unmapped",
                error_message=(
                    f"CodexAppAdapter cannot resolve output_schema_ref "
                    f"{request.output_schema_ref!r} to a local file path"
                ),
            )
        if not os.path.isfile(schema_path):
            return AdapterOutcome(
                error_code="schema_file_missing",
                error_message=(
                    f"CodexAppAdapter resolved schema path "
                    f"{schema_path!r} is not an existing regular file"
                ),
            )
        if not schema_path.lower().endswith(".json"):
            return AdapterOutcome(
                error_code="schema_file_invalid",
                error_message=(
                    f"CodexAppAdapter resolved schema path {schema_path!r} "
                    "must name a JSON file"
                ),
            )
        return AdapterOutcome()

    def build_command_plan(
        self,
        request: HarnessDispatchRequest,
        *,
        session_id: str | None = None,
    ) -> list[str]:
        """Build the full ``codex exec`` command plan for *request*.

        Returns the complete argument list including the entrypoint.  The
        schema ref is resolved to a local file path; the plan never contains
        the raw URI.

        ``session_id`` is an explicit nullable input.  When ``None`` the plan
        is a new ``codex exec``.  When non-empty it uses ``codex exec resume``.
        """
        schema_path = self._resolve_schema_path(request.output_schema_ref)
        if schema_path is None:
            raise ValueError(
                f"CodexAppAdapter cannot resolve output_schema_ref "
                f"{request.output_schema_ref!r}"
            )
        args = build_codex_exec_plan(
            model=request.model,
            output_schema_path=schema_path,
            session_id=session_id,
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
        """Dispatch *request* through the injected Codex transport.

        ``session_id`` controls new vs resumed dispatch.  ``lease`` is accepted
        for protocol uniformity (ignored — Codex is not a gated role).

        All six receipt fields must be present in the physical transport
        mapping; the adapter never fabricates any field.
        """
        plan = self.build_command_plan(request, session_id=session_id)
        raw = self._transport(plan, request.to_payload())
        if not isinstance(raw, dict):
            raise TypeError(
                "CodexAppAdapter transport must return a mapping, got "
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
                f"CodexAppAdapter transport mapping is missing/blank receipt "
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
