from __future__ import annotations

import importlib.util
import os
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar


DEFAULT_GATE_TOOL = Path("/Users/smkzw/.codex/tools/omlx_workload_gate.py")
DEFAULT_GATE_DB = Path.home() / ".codex" / "state" / "omlx_workload_gate.sqlite3"
EXPECTED_LIMITS = {"ocr": 8, "translation": 8, "total": 16}

T = TypeVar("T")


class OmlxWorkloadGateConfigurationError(RuntimeError):
    """Raised when the shared gate cannot be loaded with the required contract."""


class OmlxWorkloadGateRuntimeError(RuntimeError):
    """Raised when a request cannot retain a valid shared workload lease."""


def _positive_float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise OmlxWorkloadGateConfigurationError(
            f"{name} must be a positive number"
        ) from exc
    if value <= 0:
        raise OmlxWorkloadGateConfigurationError(
            f"{name} must be a positive number"
        )
    return value


@lru_cache(maxsize=4)
def _load_gate_module(tool_path_text: str):
    tool_path = Path(tool_path_text).expanduser().resolve()
    if not tool_path.is_file():
        raise OmlxWorkloadGateConfigurationError(
            "shared oMLX workload gate tool is unavailable"
        )
    module_name = f"_workbench_omlx_gate_{abs(hash(str(tool_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, tool_path)
    if spec is None or spec.loader is None:
        raise OmlxWorkloadGateConfigurationError(
            "shared oMLX workload gate tool could not be loaded"
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise OmlxWorkloadGateConfigurationError(
            "shared oMLX workload gate tool could not be loaded"
        ) from exc
    observed_limits = {
        "ocr": getattr(module, "OCR_LIMIT", None),
        "translation": getattr(module, "TRANSLATION_LIMIT", None),
        "total": getattr(module, "TOTAL_LIMIT", None),
    }
    if observed_limits != EXPECTED_LIMITS:
        raise OmlxWorkloadGateConfigurationError(
            "shared oMLX workload gate limits do not match the product contract"
        )
    if not all(
        hasattr(module, name)
        for name in ("WorkloadGate", "HeartbeatThread", "DEFAULT_LEASE_TTL")
    ):
        raise OmlxWorkloadGateConfigurationError(
            "shared oMLX workload gate API is incomplete"
        )
    return module


@dataclass(frozen=True)
class OmlxWorkloadGateSettings:
    tool_path: Path
    db_path: Path
    wait_timeout_seconds: float
    lease_ttl_seconds: float

    @classmethod
    def from_env(cls) -> "OmlxWorkloadGateSettings":
        return cls(
            tool_path=Path(
                os.environ.get(
                    "WORKBENCH_OMLX_WORKLOAD_GATE_TOOL",
                    str(DEFAULT_GATE_TOOL),
                )
            ).expanduser(),
            db_path=Path(
                os.environ.get(
                    "WORKBENCH_OMLX_WORKLOAD_GATE_DB",
                    str(DEFAULT_GATE_DB),
                )
            ).expanduser(),
            wait_timeout_seconds=_positive_float_env(
                "WORKBENCH_OMLX_WORKLOAD_GATE_WAIT_SECONDS",
                7200.0,
            ),
            lease_ttl_seconds=_positive_float_env(
                "WORKBENCH_OMLX_WORKLOAD_GATE_LEASE_TTL_SECONDS",
                180.0,
            ),
        )


class OmlxWorkloadGateClient:
    """Product adapter over the single cross-Agent SQLite admission gate."""

    def __init__(
        self,
        settings: OmlxWorkloadGateSettings | None = None,
        *,
        db_path: str | Path | None = None,
        tool_path: str | Path | None = None,
        wait_timeout_seconds: float | None = None,
        lease_ttl_seconds: float | None = None,
    ) -> None:
        resolved = settings or OmlxWorkloadGateSettings.from_env()
        if db_path is not None:
            resolved = OmlxWorkloadGateSettings(
                tool_path=resolved.tool_path,
                db_path=Path(db_path).expanduser(),
                wait_timeout_seconds=resolved.wait_timeout_seconds,
                lease_ttl_seconds=resolved.lease_ttl_seconds,
            )
        if tool_path is not None:
            resolved = OmlxWorkloadGateSettings(
                tool_path=Path(tool_path).expanduser(),
                db_path=resolved.db_path,
                wait_timeout_seconds=resolved.wait_timeout_seconds,
                lease_ttl_seconds=resolved.lease_ttl_seconds,
            )
        if wait_timeout_seconds is not None or lease_ttl_seconds is not None:
            resolved = OmlxWorkloadGateSettings(
                tool_path=resolved.tool_path,
                db_path=resolved.db_path,
                wait_timeout_seconds=(
                    float(wait_timeout_seconds)
                    if wait_timeout_seconds is not None
                    else resolved.wait_timeout_seconds
                ),
                lease_ttl_seconds=(
                    float(lease_ttl_seconds)
                    if lease_ttl_seconds is not None
                    else resolved.lease_ttl_seconds
                ),
            )
        if (
            resolved.wait_timeout_seconds <= 0
            or resolved.lease_ttl_seconds <= 0
        ):
            raise OmlxWorkloadGateConfigurationError(
                "workload gate timeouts must be positive"
            )
        self.settings = resolved
        self._module = _load_gate_module(str(resolved.tool_path))
        self._gate = self._module.WorkloadGate(resolved.db_path)

    @contextmanager
    def lease(self, *, kind: str, owner: str) -> Iterator[dict[str, Any]]:
        """Acquire a workload lease from the shared gate.

        The gate is only an admission/concurrency authority. Any legacy model
        metadata returned by the underlying tool is intentionally removed from
        the product lease so role bindings remain the sole model authority.
        """
        normalized_owner = " ".join(str(owner).split())[:160]
        if not normalized_owner:
            raise OmlxWorkloadGateConfigurationError(
                "workload gate owner is required"
            )
        lease = self._gate.acquire(
            kind,
            normalized_owner,
            timeout=self.settings.wait_timeout_seconds,
            lease_ttl=self.settings.lease_ttl_seconds,
            wait=True,
        )
        lease_id = str(lease.get("lease_id") or "")
        if not lease_id:
            raise OmlxWorkloadGateRuntimeError(
                "oMLX workload gate did not grant a lease"
            )
        heartbeat = self._module.HeartbeatThread(
            self._gate,
            lease_id,
            self.settings.lease_ttl_seconds,
        )
        heartbeat.start()
        body_error = False
        try:
            lease_payload = dict(lease)
            lease_payload.pop("model", None)
            yield lease_payload
        except BaseException:
            body_error = True
            raise
        finally:
            heartbeat.stop_event.set()
            heartbeat.join(timeout=2.0)
            released = self._gate.release(lease_id)
            if not body_error and (heartbeat.lost or not released):
                raise OmlxWorkloadGateRuntimeError(
                    "oMLX workload lease was lost before request completion"
                )

    def gate_selection(self) -> dict[str, Any]:
        """Return the shared gate contract without selecting role models."""
        gate = self._gate
        if hasattr(gate, "config"):
            config = dict(gate.config())
            config.pop("models", None)
            config["schema"] = "omlx_gate_selection_v2"
            return {
                "schema": config["schema"],
                "limits": dict(config.get("limits") or EXPECTED_LIMITS),
            }
        # Fallback for older gates that predate the config() method.
        module = self._module
        return {
            "schema": "omlx_gate_selection_v2",
            "limits": {
                "ocr": getattr(module, "OCR_LIMIT", 8),
                "translation": getattr(module, "TRANSLATION_LIMIT", 8),
                "total": getattr(module, "TOTAL_LIMIT", 16),
            },
            "db": str(self.settings.db_path),
        }

    def status(self) -> dict[str, Any]:
        status = dict(self._gate.status())
        return {
            "db": status.get("db", str(self.settings.db_path)),
            "active": dict(status.get("active") or {}),
            "queued": dict(status.get("queued") or {}),
            "total_active": int(status.get("total_active") or 0),
            "limits": dict(status.get("limits") or EXPECTED_LIMITS),
            "gate_contract": "shared_sqlite_ocr8_translation8_total16_v1",
        }


_default_client_lock = threading.Lock()
_default_client: OmlxWorkloadGateClient | None = None
_default_client_identity: tuple[str, str, str, str] | None = None


def default_omlx_workload_gate_client() -> OmlxWorkloadGateClient:
    global _default_client, _default_client_identity
    settings = OmlxWorkloadGateSettings.from_env()
    identity = (
        str(settings.tool_path),
        str(settings.db_path),
        str(settings.wait_timeout_seconds),
        str(settings.lease_ttl_seconds),
    )
    with _default_client_lock:
        if _default_client is None or _default_client_identity != identity:
            _default_client = OmlxWorkloadGateClient(settings)
            _default_client_identity = identity
        return _default_client


def run_gated_omlx_request(
    operation: Callable[[dict[str, Any]], T],
    *,
    kind: str,
    owner: str,
    gate_client: OmlxWorkloadGateClient | None = None,
) -> T:
    """Run an oMLX operation inside a shared workload-gate lease.

    ``operation`` receives only admission metadata. The role-bound adapter
    remains the authority for the oMLX model in the HTTP payload.
    """
    client = gate_client or default_omlx_workload_gate_client()
    with client.lease(kind=kind, owner=owner) as lease:
        return operation(lease)
