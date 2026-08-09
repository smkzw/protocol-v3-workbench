from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WORKBENCH_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WORKBENCH_ROOT))

from services.api.app.runtime_readiness import (  # noqa: E402
    API_CONTRACT_VERSION,
    BACKEND_BUILD_ID,
    CLIENT_CONTRACT_HEADER,
    RUNTIME_CONTRACT_SCHEMA,
)
from services.api.app.ai_gateway import (  # noqa: E402
    ALIBABA_TOKEN_PLAN_MODEL,
    ALIBABA_TOKEN_PLAN_PROVIDER,
)


FRONTEND_URL = "http://127.0.0.1:5174"
BACKEND_URL = "http://127.0.0.1:8911"
WRITING_SESSION_PATH = (
    "/api/projects/proj_rux_03_002/medical-writing/document-session"
)


def read_json(url: str, *, headers: dict[str, str] | None = None) -> tuple[int, dict]:
    request = Request(url, headers=headers or {})
    try:
        with urlopen(request, timeout=15) as response:
            payload = response.read()
            try:
                return response.status, json.loads(payload)
            except JSONDecodeError:
                return response.status, {
                    "_read_error": "response_is_not_json",
                    "_content_type": response.headers.get_content_type(),
                }
    except HTTPError as error:
        payload = error.read()
        try:
            return error.code, json.loads(payload)
        except JSONDecodeError:
            return error.code, {
                "_read_error": "http_error_response_is_not_json",
                "_content_type": error.headers.get_content_type(),
            }
    except (URLError, TimeoutError) as error:
        return 0, {
            "_read_error": "endpoint_unreachable",
            "_exception_type": type(error).__name__,
        }


def require(condition: bool, message: str, failures: list[str]) -> None:
    if not condition:
        failures.append(message)


def main() -> int:
    failures: list[str] = []
    api_status, api_readiness = read_json(f"{BACKEND_URL}/api/runtime-readiness")
    proxy_status, proxy_readiness = read_json(f"{FRONTEND_URL}/api/runtime-readiness")
    frontend_status, frontend_build = read_json(f"{FRONTEND_URL}/runtime-build.json")
    health_status, health = read_json(f"{BACKEND_URL}/api/health")
    legacy_status, legacy_payload = read_json(f"{BACKEND_URL}{WRITING_SESSION_PATH}")
    stale_status, stale_payload = read_json(
        f"{BACKEND_URL}{WRITING_SESSION_PATH}",
        headers={CLIENT_CONTRACT_HEADER: "stale-medical-writing-contract"},
    )
    current_status, current_payload = read_json(
        f"{BACKEND_URL}{WRITING_SESSION_PATH}",
        headers={CLIENT_CONTRACT_HEADER: API_CONTRACT_VERSION},
    )

    require(api_status == 200 and api_readiness.get("ready") is True, "backend readiness failed", failures)
    require(proxy_status == 200 and proxy_readiness == api_readiness, "frontend proxy is not bound to the ready backend", failures)
    require(frontend_status == 200, "frontend runtime build manifest is unavailable", failures)
    require(frontend_build.get("runtimeContractSchema") == RUNTIME_CONTRACT_SCHEMA, "frontend runtime-contract schema mismatch", failures)
    require(frontend_build.get("apiContractVersion") == API_CONTRACT_VERSION, "frontend API contract mismatch", failures)
    require(frontend_build.get("expectedBackendBuildId") == BACKEND_BUILD_ID, "frontend expects another backend build", failures)
    require(api_readiness.get("backend_build_id") == BACKEND_BUILD_ID, "running backend build differs from source release", failures)
    require(api_readiness.get("missing_capabilities") == [], "required medical-writing capabilities are missing", failures)
    require(api_readiness.get("runtime_schema_version") == 16, "runtime schema is not version 16", failures)

    ai = api_readiness.get("independent_ai") or {}
    require(ai.get("ready") is True, "independent AI route is not ready", failures)
    require(
        ai.get("provider") == ALIBABA_TOKEN_PLAN_PROVIDER,
        "default independent AI provider is not Alibaba Token Plan",
        failures,
    )
    require(
        ai.get("model") == ALIBABA_TOKEN_PLAN_MODEL,
        "default independent AI model is not qwen3.8-max-preview",
        failures,
    )
    require(
        ai.get("route_validation_errors") == [],
        "independent AI route validation failed",
        failures,
    )
    require(ai.get("codex_runtime_dependency") is False, "product AI depends on Codex runtime", failures)

    store = health.get("runtime_store") or {}
    require(health_status == 200 and health.get("status") == "ok", "health endpoint failed", failures)
    require(store.get("integrity_check") == "ok", "SQLite integrity check failed", failures)
    require(store.get("foreign_key_violations") == 0, "SQLite foreign-key violations found", failures)
    require(store.get("audit_chain_violation_count") == 0, "audit-chain violations found", failures)

    for label, status, payload in (
        ("legacy client", legacy_status, legacy_payload),
        ("stale client", stale_status, stale_payload),
    ):
        require(status == 409, f"{label} was not rejected", failures)
        require(
            (payload.get("detail") or {}).get("code") == "workbench_client_contract_mismatch",
            f"{label} rejection did not use the contract mismatch code",
            failures,
        )
    require(current_status == 200 and bool(current_payload.get("document_id")), "current client contract cannot read the real RUX document", failures)

    report = {
        "status": "pass" if not failures else "fail",
        "frontend_url": f"{FRONTEND_URL}/",
        "frontend_build_id": frontend_build.get("frontendBuildId"),
        "backend_build_id": BACKEND_BUILD_ID,
        "api_contract_version": API_CONTRACT_VERSION,
        "runtime_contract_schema": RUNTIME_CONTRACT_SCHEMA,
        "runtime_schema_version": api_readiness.get("runtime_schema_version"),
        "required_capability_count": len(api_readiness.get("required_capabilities") or []),
        "independent_ai": ai,
        "client_contract_gate": {
            "legacy_status": legacy_status,
            "stale_status": stale_status,
            "current_status": current_status,
        },
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
