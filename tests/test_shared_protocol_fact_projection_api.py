from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from services.api.app.main import app
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import MonitoringAuthenticatedPrincipal


class _PrincipalMiddleware:
    def __init__(self, application, principal):
        self.application = application
        self.principal = principal

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope.setdefault("state", {})["monitoring_principal"] = self.principal
        await self.application(scope, receive, send)


client = TestClient(
    _PrincipalMiddleware(
        app,
        MonitoringAuthenticatedPrincipal(
            principal_id="shared-protocol-facts-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_rux_03_002",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="shared-protocol-facts-test-session",
            directory_revision="shared-protocol-facts-test-v1",
            verification_ref_sha256="e" * 64,
        ),
    )
)


def test_shared_protocol_fact_api_is_read_only_and_privacy_bounded():
    response = client.get(
        "/api/projects/proj_rux_03_002/shared-protocol-facts",
        params={"consumer": "medical_monitoring"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert (
        payload["contract_version"]
        == "shared_protocol_fact_projection_v1"
    )
    assert payload["project_id"] == "proj_rux_03_002"
    assert payload["consumer"] == "medical_monitoring"
    for fact in payload["facts"]:
        assert fact["project_id"] == "proj_rux_03_002"
        assert fact["consumer"] == "medical_monitoring"
        assert fact["status"] == "confirmed"
    rendered = response.text
    for forbidden in (
        "/Users/",
        "/private/",
        "system_prompt",
        "provider_request",
        "provider_response",
    ):
        assert forbidden not in rendered


def test_shared_protocol_fact_api_rejects_unknown_consumer():
    response = client.get(
        "/api/projects/proj_rux_03_002/shared-protocol-facts",
        params={"consumer": "unknown_module"},
    )

    assert response.status_code == 422


def test_shared_protocol_fact_api_rejects_cross_project_scope():
    response = client.get(
        "/api/projects/proj_mgk10_sar_demo/shared-protocol-facts",
        params={"consumer": "medical_monitoring"},
    )

    assert response.status_code == 403, response.text
