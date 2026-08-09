from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


WORKBENCH_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_CONTRACT_PATH = (
    WORKBENCH_ROOT
    / "packages"
    / "contracts"
    / "workbench_contracts"
    / "runtime_contract.json"
)


class RuntimeContractError(ValueError):
    pass


def load_runtime_contract(path: Path = RUNTIME_CONTRACT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = payload.get("required_capabilities")
    if not isinstance(required, list) or not required:
        raise RuntimeContractError("required_capabilities must be a non-empty list")
    seen: set[str] = set()
    for item in required:
        capability_id = str(item.get("id") or "").strip()
        method = str(item.get("method") or "").strip().upper()
        route_path = str(item.get("path") or "").strip()
        if not capability_id or capability_id in seen:
            raise RuntimeContractError("capability ids must be non-empty and unique")
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise RuntimeContractError(f"unsupported method for {capability_id}")
        if not route_path.startswith("/api/"):
            raise RuntimeContractError(f"invalid route path for {capability_id}")
        seen.add(capability_id)
    return payload


RUNTIME_CONTRACT = load_runtime_contract()
RUNTIME_CONTRACT_SCHEMA = str(RUNTIME_CONTRACT["schema_version"])
API_CONTRACT_VERSION = str(RUNTIME_CONTRACT["api_contract_version"])
CLIENT_CONTRACT_HEADER = str(RUNTIME_CONTRACT["client_contract_header"])


def source_fingerprint(
    source_root: Path,
    extensions: Iterable[str],
    *,
    prefix: str,
    digest_prefix_length: int,
) -> str:
    allowed = {str(extension) for extension in extensions}
    files = sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix in allowed and "__pycache__" not in path.parts
    )
    digest = sha256()
    for path in files:
        relative = path.relative_to(source_root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"{prefix}-{digest.hexdigest()[:digest_prefix_length]}"


def backend_build_id() -> str:
    config = RUNTIME_CONTRACT["build_fingerprint"]
    return source_fingerprint(
        WORKBENCH_ROOT / str(config["backend_source_root"]),
        config["backend_extensions"],
        prefix="api",
        digest_prefix_length=int(config["digest_prefix_length"]),
    )


BACKEND_BUILD_ID = backend_build_id()


def registered_route_contracts(routes: Iterable[Any]) -> set[tuple[str, str]]:
    registered: set[tuple[str, str]] = set()
    for route in routes:
        route_path = str(getattr(route, "path", "") or "")
        for method in getattr(route, "methods", set()) or set():
            registered.add((str(method).upper(), route_path))
    return registered


def evaluate_required_capabilities(routes: Iterable[Any]) -> list[dict[str, Any]]:
    registered = registered_route_contracts(routes)
    return [
        {
            "id": item["id"],
            "method": item["method"],
            "path": item["path"],
            "available": (item["method"], item["path"]) in registered,
        }
        for item in RUNTIME_CONTRACT["required_capabilities"]
    ]


def runtime_readiness_report(
    routes: Iterable[Any],
    *,
    runtime_health: Mapping[str, Any],
    ai_status: Mapping[str, Any],
) -> dict[str, Any]:
    capabilities = evaluate_required_capabilities(routes)
    missing = [item["id"] for item in capabilities if not item["available"]]
    configured = ai_status.get("configured") is True
    semantic_ai_tasks_enabled = ai_status.get("semantic_ai_tasks_enabled") is True
    codex_runtime_dependency = ai_status.get("codex_runtime_dependency") is True
    runtime_ready = (
        runtime_health.get("status") == "ok"
        and runtime_health.get("integrity_check") == "ok"
        and int(runtime_health.get("foreign_key_violations") or 0) == 0
    )
    ai_ready = (
        configured
        and semantic_ai_tasks_enabled
        and not codex_runtime_dependency
        and not ai_status.get("route_validation_errors")
    )
    if not ai_ready:
        missing.append("independent_ai")
    ready = runtime_ready and not missing
    return {
        "status": "ready" if ready else "blocked",
        "ready": ready,
        "runtime_contract_schema": RUNTIME_CONTRACT_SCHEMA,
        "api_contract_version": API_CONTRACT_VERSION,
        "backend_build_id": BACKEND_BUILD_ID,
        "runtime_schema_version": runtime_health.get("schema_version"),
        "required_capabilities": capabilities,
        "missing_capabilities": missing,
        "runtime_store_ready": runtime_ready,
        "independent_ai": {
            "ready": ai_ready,
            "configured": configured,
            "provider": ai_status.get("provider"),
            "model": ai_status.get("model"),
            "transport": ai_status.get("transport"),
            "semantic_ai_tasks_enabled": semantic_ai_tasks_enabled,
            "codex_runtime_dependency": codex_runtime_dependency,
            "route_validation_errors": list(ai_status.get("route_validation_errors") or []),
        },
    }


def client_contract_enforcement_enabled() -> bool:
    return os.environ.get("WORKBENCH_CLIENT_CONTRACT_MODE", "off").strip().lower() == "enforce"


def is_medical_writing_contract_path(path: str, method: str) -> bool:
    if method.upper() == "OPTIONS":
        return False
    return "/medical-writing" in path or (path == "/api/projects" and method.upper() == "POST")
