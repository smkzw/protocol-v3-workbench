"""Protocol v3 transport adapters for the Harness (Task 1.7).

This package holds the injected transport adapters that turn
:class:`~app.protocol_workflow.runtime.harness.HarnessDispatchRequest` objects
into typed :class:`~app.protocol_workflow.runtime.harness.DispatchReceipt`
objects.  Each adapter is a thin, deterministic wrapper over an injected
callable; it performs no network, model, OCR or translation access on its own.

Design authority: frozen plan Task 1.7 and
``plans/mw_protocol_multi_agent_rearchitecture_design_20260809.md`` section
17.2.

Adapters shipped here:

* :class:`~app.protocol_workflow.runtime.adapters.direct_api.DirectApiAdapter`
  — wraps an injected Direct API callable (e.g. DeepSeek, Paddle official).
* :class:`~app.protocol_workflow.runtime.adapters.local_omlx.LocalOmlxAdapter`
  — wraps an injected local oMLX callable and forwards the real lease acquired
  by the common Harness boundary.  The injected gate client, not this adapter,
  owns lease heartbeat and release for translation.
* :class:`~app.protocol_workflow.runtime.adapters.codex_app.CodexAppAdapter`
  — wraps an injected Codex App/CLI process/session transport.  Builds a
  ``codex exec`` (or ``codex exec resume``) command plan with explicit model,
  ``--json`` JSONL output, typed ``--output-schema`` and same-session resume;
  never generates ``--no-tools`` or ``--max-turns 1``.
* :class:`~app.protocol_workflow.runtime.adapters.omp_cli.OmpCliAdapter`
  — wraps an injected OMP CLI process/session transport.  Builds an ``omp``
  command plan with explicit provider/model, exact ``--thinking`` value,
  non-interactive ``-p``, ``--auto-approve``, tools enabled, long
  ``--max-time`` and optional same-session ``--resume``; never generates
  ``--no-tools`` or ``--max-turns 1``.

All adapters require a first-use connectivity probe.  The common
``ProbePolicy`` caches both successful and failed first-use outcomes by
adapter identity until an explicit cache clear, so a failed probe cannot be
silently retried inside the same run.  None sets ``max_turns=1``.
"""

from __future__ import annotations

from app.protocol_workflow.runtime.adapters.codex_app import CodexAppAdapter
from app.protocol_workflow.runtime.adapters.direct_api import DirectApiAdapter
from app.protocol_workflow.runtime.adapters.local_omlx import LocalOmlxAdapter
from app.protocol_workflow.runtime.adapters.omp_cli import OmpCliAdapter

__all__ = [
    "CodexAppAdapter",
    "DirectApiAdapter",
    "LocalOmlxAdapter",
    "OmpCliAdapter",
]
