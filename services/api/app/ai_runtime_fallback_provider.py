"""Small synchronous provider chain for interactive product AI calls."""

from __future__ import annotations

from hashlib import sha256
import json
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
        self.fallback_chain_id = "raif_" + sha256(
            _canonical_json(
                [
                    {
                        "profile_id": profile_id,
                        "provider": str(getattr(provider, "provider_name", "")),
                        "model": str(getattr(provider, "model_name", "")),
                        "thinking": str(getattr(provider, "default_thinking", "") or ""),
                        "reasoning_effort": str(
                            getattr(provider, "default_reasoning_effort", "") or ""
                        ),
                    }
                    for profile_id, provider in self._providers
                ]
            ).encode("utf-8")
        ).hexdigest()[:24]

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
                if status in FALLBACK_HTTP_STATUSES
                else ""
            )
        if failure_code in {"provider_transport_error", "provider_response_empty"}:
            return failure_code
        return ""

    def run(self, envelope: Any) -> Any:
        self._active_index = 0
        self.fallback_reason = ""
        last_error: Exception | None = None
        for index, (_profile_id, provider) in enumerate(self._providers):
            self._active_index = index
            try:
                return provider.run(envelope)
            except Exception as exc:
                reason = self._reason(exc)
                if not reason or index == len(self._providers) - 1:
                    raise
                self.fallback_reason = reason
                last_error = exc
        assert last_error is not None
        raise last_error
