"""0924V2 §5 model phase scheduler.

MTPLX (8002) and oMLX (8001) each hold ~30GB resident models and cannot
coexist on this 128GB machine alongside the workbench. Rather than a fixed
"server A for phase X" mapping, the scheduler sends a lightweight probe to
the target server's model to trigger on-demand load, and optionally sends
an unload signal to the other server — all through standard OpenAI-compatible
APIs. No server restart, no admin endpoint, no process kill.

Round21: server/model process lifecycle (start, load, mutual-exclusion
unload, stop) moved to model_lifecycle_orchestrator.py, which drives the
same endpoints from services/api/config/model_lifecycle.json.  This module
keeps the phase->model contract and the A18 chat probe; its frozen
constants are contract-tested (test_p_scheduler_frozen_constants_unchanged).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any, Optional

logger = logging.getLogger(__name__)

MTPLX_BASE = "http://127.0.0.1:8002/v1"
OMLX_BASE = "http://127.0.0.1:8001/v1"

MTPLX_MODEL = "mtplx-flash-next-optimized-speed"
OMLX_TRANSLATION_MODEL = "dawncr0w--Hy-MT2-30B-A3B-oQ8-MLX"

_PROBE_MAX_TOKENS = 1
_PROBE_TIMEOUT = 120

# A17: phases map to exactly the models they need; an unmapped phase maps to
# nothing and must never auto-wake any server. Read-only readiness checks
# (warm=False) use /models listings and never send a chat request.
PHASE_MODEL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "translation": ("translation",),
    "triage": ("triage",),
}

_ROLE_BASE = {"translation": OMLX_BASE, "triage": MTPLX_BASE}
_ROLE_MODEL = {
    "translation": OMLX_TRANSLATION_MODEL,
    "triage": MTPLX_MODEL,
}


def _chat_probe(base_url: str, model: str,
                max_tokens: int = _PROBE_MAX_TOKENS) -> tuple[bool, str]:
    """Send a minimal chat request to trigger on-demand model load.

    A bare HTTP 200 is NOT success (A18): the response body must name the
    requested model and carry a non-empty choice, otherwise the target
    model's capability is unproven.

    ``max_tokens`` lets the round21 lifecycle orchestrator pass its configured
    probe budget (hard-capped at 8 there); the default keeps the historical
    1-token probe for all existing callers.  Frozen constants above (bases,
    models, PHASE_MODEL_REQUIREMENTS) are contract-tested and must not move.
    """
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT) as resp:
            if resp.status != 200:
                return False, f"HTTP {resp.status}"
            try:
                data = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                return False, f"probe_body_unparseable: {exc}"
            returned_model = data.get("model")
            if returned_model != model:
                return False, (
                    f"probe_model_mismatch: requested={model} "
                    f"responded={returned_model!r}"
                )
            if not data.get("choices"):
                return False, "probe_empty_choices"
            return True, ""
    except urllib.error.HTTPError as exc:
        body_text = ""
        try:
            body_text = exc.read().decode("utf-8")[:300]
        except Exception:
            pass
        return False, f"HTTP {exc.code}: {body_text}"
    except Exception as exc:
        return False, str(exc)


def warm_translation_model() -> tuple[bool, str]:
    """Ensure the oMLX translation model is loaded and responsive."""
    return _chat_probe(OMLX_BASE, OMLX_TRANSLATION_MODEL)


def warm_triage_model() -> tuple[bool, str]:
    """Ensure the MTPLX model is loaded and responsive."""
    return _chat_probe(MTPLX_BASE, MTPLX_MODEL)


def list_resident_models(base_url: str) -> list[str]:
    """Return model IDs the server reports as available."""
    try:
        req = urllib.request.Request(f"{base_url}/models")
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("id", "") for m in data.get("data", [])]
    except Exception:
        return []


def phase_model_readiness(phase: str, warm: bool = False) -> dict[str, Any]:
    """Report readiness for exactly the models the phase requires.

    warm=False (default, read-only): check the /models listing only — no chat
    request is sent (A17: 只读检查不chat).
    warm=True: probe ONLY the phase-required model to trigger its on-demand
    load; other servers are left alone. An unmapped phase warms nothing.
    """
    required_roles = PHASE_MODEL_REQUIREMENTS.get(phase)
    result: dict[str, Any] = {
        "phase": phase,
        "warm": bool(warm),
        "roles": {},
        "unknown_phase": required_roles is None,
    }
    if not required_roles:
        return result
    for role in required_roles:
        base_url, model = _ROLE_BASE[role], _ROLE_MODEL[role]
        if warm:
            ok, err = _chat_probe(base_url, model)
        else:
            ok = model in list_resident_models(base_url)
            err = "" if ok else "model_not_listed_as_resident"
        result["roles"][role] = {"ready": ok, "error": err}
    return result
