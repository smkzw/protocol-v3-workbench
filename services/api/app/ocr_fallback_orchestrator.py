"""Paddle-primary → oMLX GLM fallback orchestrator for single-page OCR.

This orchestrator wraps the dedicated Paddle adapter and the existing
``LocalOcrGateway`` (GLM).  It tries Paddle first.  Only after a verified
Paddle request or terminal failure does it fall back to GLM.  The actual
per-page model, provider identity, and fallback reason are persisted in
the returned ``OcrFallbackResult`` so the extraction service can record
accurate provenance — GLM output is never mislabeled as Paddle.

All external transports are injectable for deterministic tests.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .paddle_ocr_adapter import (
    PADDLE_OCR_MODEL,
    PaddleOcrAdapter,
    PaddleOcrError,
    PaddleOcrJobFailedError,
    PaddleOcrOutcomeUnknownError,
    PaddleOcrSettings,
    PaddleOcrSubmissionRejectedError,
    PaddleOcrTimeoutError,
)

# GLM fallback model identifier — must match ocr_gateway.DEFAULT_MODEL.
GLM_FALLBACK_MODEL = "GLM-OCR-bf16"

# Provider identity strings for provenance.
PROVIDER_PADDLE = "paddle_official"
PROVIDER_GLM_OMLX = "omlx_glm"

# Reasons recorded on fallback.
FALLBACK_REASON_PREFIX = "paddle_failure"


@dataclass(frozen=True)
class OcrFallbackResult:
    """Result of a single-page OCR attempt with primary/fallback provenance.

    ``provider`` and ``model`` always reflect the *actual* model that produced
    ``text``.  When fallback occurred, ``fallback_reason`` is non-empty and
    ``primary_model`` records the model that was attempted first.
    """

    text: str
    model: str
    provider: str
    source_token: str
    content_hash: str
    character_count: int
    called_at: str  # ISO-8601 UTC
    duration_ms: float
    fell_back: bool = False
    primary_model: str = ""
    fallback_reason: str = ""


class OcrFallbackOrchestrator:
    """Orchestrates Paddle-primary → GLM fallback for single-page OCR.

    The orchestrator accepts an optional ``paddle_adapter`` (which itself has
    injectable transports).  When ``paddle_adapter`` is ``None``, the
    orchestrator skips directly to GLM — this path is used when the Paddle
    credential is not configured.
    """

    def __init__(
        self,
        paddle_adapter: Optional[PaddleOcrAdapter] = None,
        glm_runner: Optional[Callable[[bytes, str], str]] = None,
    ) -> None:
        self._paddle_adapter = paddle_adapter
        self._glm_runner = glm_runner

    def run(self, image_bytes: bytes, mime_type: str = "image/png") -> OcrFallbackResult:
        """Run OCR on a single page image.

        Tries Paddle first (if configured).  On any verified Paddle failure
        (exception), falls back to GLM.  Returns the result with accurate
        provenance.
        """
        import hashlib

        called_at_dt = datetime.now(timezone.utc)
        started = time.perf_counter()
        content_hash = hashlib.sha256(image_bytes).hexdigest()
        source_token = _opaque_source_token(content_hash)

        # --- Primary: Paddle -------------------------------------------------
        if self._paddle_adapter is not None:
            try:
                job_result = self._paddle_adapter.submit_and_wait(image_bytes, mime_type)
                if job_result.pages:
                    text = job_result.pages[0].markdown
                    if text.strip():
                        duration_ms = (time.perf_counter() - started) * 1000
                        return OcrFallbackResult(
                            text=text,
                            model=PADDLE_OCR_MODEL,
                            provider=PROVIDER_PADDLE,
                            source_token=source_token,
                            content_hash=content_hash,
                            character_count=len(text),
                            called_at=called_at_dt.isoformat(),
                            duration_ms=duration_ms,
                            fell_back=False,
                        )
                # A completed remote call with unusable text has already spent
                # the model call. Starting GLM here would duplicate execution.
                raise PaddleOcrOutcomeUnknownError(
                    "Paddle OCR completed with unusable text",
                    job_id=job_result.job_id,
                )
            except PaddleOcrOutcomeUnknownError:
                # Once provider acceptance is possible, fail closed. A caller
                # may resume/reconcile the same remote job, but must not start
                # a second model for the same page.
                raise
            except PaddleOcrJobFailedError as exc:
                reason = f"{FALLBACK_REASON_PREFIX}:job_failed:{exc.job_id}"
            except PaddleOcrSubmissionRejectedError as exc:
                reason = f"{FALLBACK_REASON_PREFIX}:error:{_sanitize(str(exc))}"
            except PaddleOcrError:
                # Unknown adapter failures are not proof of non-acceptance.
                raise
        else:
            reason = f"{FALLBACK_REASON_PREFIX}:not_configured"

        # --- Fallback: GLM via oMLX -----------------------------------------
        if self._glm_runner is None:
            raise RuntimeError(
                "Paddle OCR failed and GLM fallback runner is not configured"
            )

        glm_text = self._glm_runner(image_bytes, mime_type)
        duration_ms = (time.perf_counter() - started) * 1000
        return OcrFallbackResult(
            text=glm_text,
            model=GLM_FALLBACK_MODEL,
            provider=PROVIDER_GLM_OMLX,
            source_token=source_token,
            content_hash=content_hash,
            character_count=len(glm_text),
            called_at=called_at_dt.isoformat(),
            duration_ms=duration_ms,
            fell_back=True,
            primary_model=PADDLE_OCR_MODEL,
            fallback_reason=reason,
        )


def detect_mixed_model_evidence(models: list[str]) -> bool:
    """Return True if a document's OCR evidence spans more than one model.

    Used by the extraction/QC layer to decide whether a focused consistency-QC
    stage should run before corpus admission.
    """
    unique = {m.strip() for m in models if m and m.strip()}
    return len(unique) > 1


def _opaque_source_token(content_hash: str) -> str:
    import hashlib

    digest = hashlib.sha256(
        f"ocr-fallback-v1|{content_hash}".encode("ascii")
    ).hexdigest()
    return f"ocrsrc_{digest[:16]}"


def _sanitize(text: str) -> str:
    """Remove any potential credential fragments from error messages."""
    # Keep only the first 120 chars and strip anything that looks like a token.
    import re

    truncated = text[:120]
    return re.sub(r"[A-Za-z0-9]{32,}", "[redacted]", truncated)
