from datetime import datetime, timedelta, timezone

import pytest

from services.api.app.monitoring_identity_authorization import MonitoringAction
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
    MonitoringRuntimePrincipalDenied,
)
from services.api.app.monitoring_runtime_route_context import (
    MonitoringRuntimeRouteContext,
    MonitoringRuntimeRouteContextError,
    build_monitoring_runtime_route_context,
)


NOW = datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc)
PROJECT = "proj_rux_03_002"
TENANT = "tenant-kangzhe"
SHA = "a" * 64


def _principal(**overrides):
    payload = {
        "server_verified": True,
        "principal_id": "user-001",
        "tenant_id": TENANT,
        "roles": ["medical_manager"],
        "project_scope": [PROJECT],
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
        "authenticated": True,
        "authn_method": "local-session",
        "session_id": "session-secret-value",
        "directory_revision": "directory-v1",
        "verification_ref_sha256": SHA,
    }
    payload.update(overrides)
    return MonitoringAuthenticatedPrincipal.from_server_verified_claims(payload, now=NOW)


def test_route_context_binds_server_principal_to_tenant_project_and_action():
    context = build_monitoring_runtime_route_context(
        _principal(),
        request_id="request-001",
        route_project_id=PROJECT,
        tenant_id=TENANT,
        target_scope="trial",
        action=MonitoringAction.COMPLETE_ASSURANCE,
        high_risk=True,
        reauthenticated=True,
        signature_evidence_sha256="b" * 64,
        now=NOW,
    )
    assert context.principal_id == "user-001"
    assert context.project_id == PROJECT
    assert context.action is MonitoringAction.COMPLETE_ASSURANCE
    assert context.request.high_risk is True
    assert context.request.reauthenticated is True
    assert context.validated_at == NOW
    public = context.public_dict()
    assert public["schema_version"] == "monitoring_runtime_route_context_v1"
    assert "session-secret-value" not in str(public)


def test_direct_context_construction_still_validates_the_principal_window():
    principal = _principal()
    request = build_monitoring_runtime_route_context(
        principal,
        request_id="request-001",
        route_project_id=PROJECT,
        tenant_id=TENANT,
        target_scope="trial",
        action=MonitoringAction.READ_MONITORING,
        now=NOW,
    ).request
    with pytest.raises(MonitoringRuntimeRouteContextError, match="principal is not valid"):
        MonitoringRuntimeRouteContext(
            principal=principal,
            request=request,
            tenant_id=TENANT,
            project_id=PROJECT,
            validated_at=NOW - timedelta(days=1),
        )


def test_route_context_rejects_wrong_tenant_or_project_before_authorization():
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="tenant_scope_denied"):
        build_monitoring_runtime_route_context(
            _principal(),
            request_id="request-001",
            route_project_id=PROJECT,
            tenant_id="other-tenant",
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            now=NOW,
        )
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="project_scope_denied"):
        build_monitoring_runtime_route_context(
            _principal(),
            request_id="request-001",
            route_project_id="other-project",
            tenant_id=TENANT,
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            now=NOW,
        )


def test_route_context_rejects_client_actor_even_when_it_matches():
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="client_actor_not_authoritative"):
        build_monitoring_runtime_route_context(
            _principal(),
            request_id="request-001",
            route_project_id=PROJECT,
            tenant_id=TENANT,
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            client_actor="user-001",
            now=NOW,
        )


def test_route_context_requires_live_principal_and_nonempty_route_fields():
    expired_claims = {
        "principal_id": "user-001",
        "tenant_id": TENANT,
        "roles": ("medical_manager",),
        "project_scope": (PROJECT,),
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW - timedelta(seconds=1),
        "authenticated": True,
        "authn_method": "local-session",
        "session_id": "session-secret-value",
        "directory_revision": "directory-v1",
        "verification_ref_sha256": SHA,
    }
    expired = MonitoringAuthenticatedPrincipal(**expired_claims)
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="principal_expired"):
        build_monitoring_runtime_route_context(
            expired,
            request_id="request-001",
            route_project_id=PROJECT,
            tenant_id=TENANT,
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            now=NOW,
        )
    with pytest.raises(MonitoringRuntimeRouteContextError, match="request_id is required"):
        build_monitoring_runtime_route_context(
            _principal(),
            request_id="",
            route_project_id=PROJECT,
            tenant_id=TENANT,
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            now=NOW,
        )


def test_route_context_rejects_non_principal_and_invalid_target_scope():
    with pytest.raises(MonitoringRuntimeRouteContextError, match="server-verified"):
        build_monitoring_runtime_route_context(
            object(),
            request_id="request-001",
            route_project_id=PROJECT,
            tenant_id=TENANT,
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            now=NOW,
        )
    with pytest.raises(ValueError, match="unsupported target_scope"):
        build_monitoring_runtime_route_context(
            _principal(),
            request_id="request-001",
            route_project_id=PROJECT,
            tenant_id=TENANT,
            target_scope="risk",
            action=MonitoringAction.READ_MONITORING,
            now=NOW,
        )


def test_route_context_does_not_authorize_or_write():
    context = build_monitoring_runtime_route_context(
        _principal(),
        request_id="request-001",
        route_project_id=PROJECT,
        tenant_id=TENANT,
        target_scope="subject",
        action=MonitoringAction.CHANGE_RISK_DISPOSITION,
        now=NOW,
    )
    assert context.request.principal_id == context.principal.principal_id
    assert not hasattr(context, "decision")
    assert not hasattr(context, "mutation_applied")
