from datetime import datetime, timedelta, timezone

import pytest

from services.api.app.monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringRole,
)
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
    MonitoringRuntimePrincipalDenied,
    MonitoringRuntimePrincipalError,
    build_monitoring_authorization_request,
    require_server_derived_actor,
)


NOW = datetime(2026, 8, 3, 7, 0, tzinfo=timezone.utc)
PROJECT = "proj_rux_03_002"
VERIFICATION_REF = "a" * 64


def _claims(**overrides):
    payload = {
        "server_verified": True,
        "principal_id": "user-001",
        "tenant_id": "tenant-kangzhe",
        "roles": [MonitoringRole.MEDICAL_MANAGER.value],
        "project_scope": [PROJECT],
        "issued_at": NOW - timedelta(minutes=5),
        "expires_at": NOW + timedelta(hours=1),
        "authenticated": True,
        "authn_method": "local-session",
        "session_id": "session-secret-value",
        "directory_revision": "directory-v1",
        "verification_ref_sha256": VERIFICATION_REF,
        "authn_context": "password-plus-session",
        "assurance": "directory-verified",
    }
    payload.update(overrides)
    return payload


def test_verified_envelope_derives_principal_without_exposing_session_or_client_actor():
    principal = MonitoringAuthenticatedPrincipal.from_server_verified_claims(
        _claims(), now=NOW
    )
    assert principal.server_actor_at(now=NOW) == "user-001"
    assert principal.to_monitoring_principal(now=NOW).roles == (
        MonitoringRole.MEDICAL_MANAGER,
    )
    public = principal.public_dict()
    assert public["session_id_sha256"]
    assert "session-secret-value" not in str(public)
    assert require_server_derived_actor(principal, now=NOW) == "user-001"


def test_unverified_or_incomplete_envelope_fails_closed():
    with pytest.raises(MonitoringRuntimePrincipalError, match="server_verified"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(server_verified=False), now=NOW
        )
    with pytest.raises(MonitoringRuntimePrincipalError, match="verification_ref_sha256"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(verification_ref_sha256=""), now=NOW
        )
    with pytest.raises(MonitoringRuntimePrincipalError, match="wildcard"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(project_scope=["*"]), now=NOW
        )


@pytest.mark.parametrize(
    "verification_ref",
    ("A" * 64, " " + VERIFICATION_REF, 123, "g" * 64),
)
def test_verification_reference_rejects_noncanonical_digest_shape(
    verification_ref: object,
):
    with pytest.raises(
        MonitoringRuntimePrincipalError,
        match="verification_ref_sha256.*lowercase SHA-256",
    ):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(verification_ref_sha256=verification_ref), now=NOW
        )


def test_time_window_and_authentication_are_enforced():
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="principal_expired"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(expires_at=NOW), now=NOW
        )
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="principal_not_yet_valid"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(issued_at=NOW + timedelta(minutes=1)), now=NOW
        )
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="not_authenticated"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(authenticated=False), now=NOW
        )

    expired_claims = _claims(expires_at=NOW - timedelta(minutes=1))
    expired_claims.pop("server_verified")
    expired = MonitoringAuthenticatedPrincipal(**expired_claims)
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="principal_expired"):
        _ = expired.server_actor_at(now=NOW)


def test_client_actor_is_never_authoritative_even_when_it_matches_principal():
    principal = MonitoringAuthenticatedPrincipal.from_server_verified_claims(
        _claims(), now=NOW
    )
    with pytest.raises(
        MonitoringRuntimePrincipalDenied, match="client_actor_not_authoritative"
    ):
        require_server_derived_actor(principal, "user-001", now=NOW)


def test_route_request_builder_derives_identity_and_binds_tenant():
    principal = MonitoringAuthenticatedPrincipal.from_server_verified_claims(
        _claims(), now=NOW
    )
    request = build_monitoring_authorization_request(
        principal,
        request_id="request-001",
        project_id=PROJECT,
        tenant_id="tenant-kangzhe",
        target_scope="subject",
        action=MonitoringAction.CHANGE_RISK_DISPOSITION,
        high_risk=True,
        reauthenticated=True,
        signature_evidence_sha256="b" * 64,
        now=NOW,
    )
    assert request.principal_id == "user-001"
    assert request.high_risk is True
    assert request.reauthenticated is True
    assert request.signature_evidence_sha256 == "b" * 64


def test_tenant_mismatch_and_forged_actor_fail_before_route_authorization():
    principal = MonitoringAuthenticatedPrincipal.from_server_verified_claims(
        _claims(), now=NOW
    )
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="tenant_scope_denied"):
        build_monitoring_authorization_request(
            principal,
            request_id="request-001",
            project_id=PROJECT,
            tenant_id="other-tenant",
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            now=NOW,
        )
    with pytest.raises(
        MonitoringRuntimePrincipalDenied, match="client_actor_not_authoritative"
    ):
        build_monitoring_authorization_request(
            principal,
            request_id="request-001",
            project_id=PROJECT,
            target_scope="trial",
            action=MonitoringAction.READ_MONITORING,
            client_actor="medical_manager",
            now=NOW,
        )


def test_duplicate_or_unknown_roles_are_rejected_by_existing_contract():
    with pytest.raises(MonitoringRuntimePrincipalError, match="unique"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(roles=[MonitoringRole.MEDICAL_MANAGER.value] * 2), now=NOW
        )
    with pytest.raises(MonitoringRuntimePrincipalError, match="unsupported"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            _claims(roles=["unknown-role"]), now=NOW
        )
