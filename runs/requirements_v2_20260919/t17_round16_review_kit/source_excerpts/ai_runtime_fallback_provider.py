"""Small synchronous provider chain for interactive product AI calls."""

from __future__ import annotations

from hashlib import sha256
import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from .ai_gateway import AiProviderRuntimeError


FALLBACK_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class RuntimeFallbackAiProvider:
    """Run one in-memory frozen provider chain and expose the effective route."""

    def __init__(self, providers: Iterable[tuple[str, Any]]) -> None:
        self._providers = list(providers)
        if not self._providers:
            raise ValueError("AI provider chain is empty")
        self._active_index = 0
        self.fallback_reason = ""
        # R03: the chain identity must change when the effective execution
        # route changes (endpoint/base_url, transport, expected response
        # model, profile revision), not only when the logical preference
        # changes.  Old receipts keep their persisted ids; only new runs
        # compute the upgraded identity.
        self.fallback_chain_id = "raif_" + sha256(
            _canonical_json(
                [
                    {
                        "profile_id": profile_id,
                        "provider": str(getattr(provider, "provider_name", "")),
                        "model": str(getattr(provider, "model_name", "")),
                        "base_url": str(getattr(provider, "base_url", "") or ""),
                        "transport": str(getattr(provider, "transport_name", "") or ""),
                        "expected_response_model": str(
                            getattr(provider, "expected_response_model", "") or ""
                        ),
                        "profile_revision": str(
                            getattr(provider, "profile_revision", "") or ""
                        ),
                        "thinking": str(getattr(provider, "default_thinking", "") or ""),
                        "reasoning_effort": str(
                            getattr(provider, "default_reasoning_effort", "") or ""
                        ),
                    }
                    for profile_id, provider in self._providers
                ]
            ).encode("utf-8")
        ).hexdigest()[:24]
        self.last_attempts: list[dict[str, Any]] = []

    @property
    def _active(self) -> tuple[str, Any]:
        return self._providers[self._active_index]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._active[1], name)

    @property
    def route_profile_id(self) -> str:
        return self._active[0]

    @property
    def fallback_depth(self) -> int:
        return self._active_index

    @property
    def timeout_seconds(self) -> float:
        return float(getattr(self._active[1], "timeout_seconds"))

    @timeout_seconds.setter
    def timeout_seconds(self, value: float) -> None:
        for _profile_id, provider in self._providers:
            provider.timeout_seconds = float(value)

    @staticmethod
    def _reason(exc: Exception) -> str:
        if not isinstance(exc, AiProviderRuntimeError):
            return ""
        diagnostics = dict(exc.diagnostics or {})
        failure_code = str(diagnostics.get("failure_code") or "")
        if failure_code == "provider_http_error":
            try:
                status = int(diagnostics.get("http_status"))
            except (TypeError, ValueError):
                return ""
            return (
                f"{failure_code}:{status}"
                if 500 <= status <= 599 or status in FALLBACK_HTTP_STATUSES
                else ""
            )
        if failure_code in {"provider_transport_error", "provider_response_empty"}:
            return failure_code
        return ""

    def run(self, envelope: Any) -> Any:
        self._active_index = 0
        self.fallback_reason = ""
        attempts: list[dict[str, Any]] = []
        self.last_attempts = attempts
        last_error: Exception | None = None
        for index, (profile_id, provider) in enumerate(self._providers):
            self._active_index = index
            # R05: per-attempt metadata (no prompt/response bodies, no
            # credentials) so route evidence explains what actually ran.
            started_wall = datetime.now(timezone.utc)
            started_perf = time.perf_counter()
            entry: dict[str, Any] = {
                "depth": index,
                "profile_id": profile_id,
                "provider": str(getattr(provider, "provider_name", "")),
                "model": str(getattr(provider, "model_name", "")),
                "endpoint": str(getattr(provider, "base_url", "") or ""),
                "expected_response_model": str(
                    getattr(provider, "expected_response_model", "") or ""
                ),
                "started_at": started_wall.isoformat(timespec="milliseconds"),
            }
            try:
                result = provider.run(envelope)
            except Exception as exc:
                reason = self._reason(exc)
                entry["ok"] = False
                entry["duration_ms"] = int((time.perf_counter() - started_perf) * 1000)
                entry["failure_reason"] = reason or type(exc).__name__
                attempts.append(entry)
                if not reason or index == len(self._providers) - 1:
                    raise
                self.fallback_reason = reason
                last_error = exc
            else:
                entry["ok"] = True
                entry["duration_ms"] = int((time.perf_counter() - started_perf) * 1000)
                attempts.append(entry)
                return result
        assert last_error is not None
        raise last_error

    @property
    def attempts(self) -> list[dict[str, Any]]:
        """Metadata for the most recent run (empty before the first run)."""
        return list(self.last_attempts)
