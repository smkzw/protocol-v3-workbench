"""0924V2 §5 model phase scheduler.

MTPLX (8002) and oMLX (8001) each hold ~30GB resident models and cannot
coexist on this 128GB machine alongside the workbench. Rather than a fixed
"server A for phase X" mapping, the scheduler sends a lightweight probe to
the target server's model to trigger on-demand load, and optionally sends
an unload signal to the other server — all through standard OpenAI-compatible
APIs. No server restart, no admin endpoint, no process kill.
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


def _chat_probe(base_url: str, model: str) -> tuple[bool, str]:
    """Send a minimal chat request to trigger on-demand model load."""
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": _PROBE_MAX_TOKENS,
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
            return resp.status == 200, ""
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


def phase_model_readiness(phase: str) -> dict[str, Any]:
    """Report which phase-required models are currently responsive."""
    omlx_ok, omlx_err = warm_translation_model()
    mtplx_ok, mtplx_err = warm_triage_model()
    return {
        "phase": phase,
        "translation_model_ready": omlx_ok,
        "translation_model_error": omlx_err,
        "triage_model_ready": mtplx_ok,
        "triage_model_error": mtplx_err,
    }
