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
            principal_id="source-content-projection-test",
            tenant_id="tenant-kangzhe",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("proj_rux_03_002",),
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            authenticated=True,
            authn_method="test-server-session",
            session_id="source-content-projection-test-session",
            directory_revision="source-content-projection-test-v1",
            verification_ref_sha256="5" * 64,
        ),
    )
)


def test_source_content_projection_api_is_project_scoped_and_privacy_bounded():
    response = client.get(
        "/api/projects/proj_rux_03_002/source-contents",
        params={"module": "medical_monitoring"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["contract_version"] == "source_content_projection_v1"
    assert payload["project_id"] == "proj_rux_03_002"
    for content in payload["contents"]:
        assert content["project_id"] == "proj_rux_03_002"
        assert all(
            binding["module"] == "medical_monitoring"
            for binding in content["bindings"]
        )
    rendered = response.text
    for forbidden in (
        "content_hash",
        "storage_key",
        "server_path",
        "/Users/",
    ):
        assert forbidden not in rendered


def test_source_content_projection_api_canonicalizes_project_aliases():
    canonical = client.get(
        "/api/projects/proj_rux_03_002/source-contents"
    )
    alias = client.get(
        "/api/projects/rux_03_002_monitoring_raw/source-contents"
    )

    assert canonical.status_code == alias.status_code == 200
    assert canonical.json() == alias.json()
