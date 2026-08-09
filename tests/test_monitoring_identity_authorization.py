from __future__ import annotations

import pytest

from services.api.app.monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringAuthorizationReason,
    MonitoringAuthorizationRequest,
    MonitoringPrincipal,
    MonitoringRole,
    authorization_decision_payload,
    authorize_monitoring_action,
    build_first_release_medical_manager_principal,
)


PROJECT_ID = "proj_rux_03_002"
SIGNATURE = "a" * 64


def _principal(
    *roles: MonitoringRole,
    projects: tuple[str, ...] = (PROJECT_ID,),
    authenticated: bool = True,
) -> MonitoringPrincipal:
    return MonitoringPrincipal(
        principal_id="user-001",
        roles=roles or (MonitoringRole.MEDICAL_MANAGER,),
        project_scope=projects,
        authenticated=authenticated,
        authn_method="local-session",
        session_id="session-001",
        directory_revision="directory-v1",
    )


def _request(
    principal: MonitoringPrincipal,
    action: MonitoringAction,
    *,
    high_risk: bool = False,
    reauthenticated: bool = False,
    signature: str = "",
    project_id: str = PROJECT_ID,
) -> MonitoringAuthorizationRequest:
    return MonitoringAuthorizationRequest(
        request_id="request-001",
        principal_id=principal.principal_id,
        project_id=project_id,
        action=action,
        target_scope="subject",
        high_risk=high_risk,
        reauthenticated=reauthenticated,
        signature_evidence_sha256=signature,
    )


def test_authenticated_principal_requires_explicit_session_and_scope() -> None:
    with pytest.raises(ValueError, match="authn_method and session_id"):
        MonitoringPrincipal(
            principal_id="user-001",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=(PROJECT_ID,),
            authenticated=True,
        )
    with pytest.raises(ValueError, match="wildcard"):
        MonitoringPrincipal(
            principal_id="user-001",
            roles=(MonitoringRole.MEDICAL_MANAGER,),
            project_scope=("*",),
        )


def test_unauthenticated_or_wrong_project_fails_closed() -> None:
    unauthenticated = _principal(authenticated=False)
    denied = authorize_monitoring_action(
        unauthenticated,
        _request(unauthenticated, MonitoringAction.READ_MONITORING),
    )
    assert denied.allowed is False
    assert denied.reason is MonitoringAuthorizationReason.AUTHENTICATION_REQUIRED

    principal = _principal()
    denied = authorize_monitoring_action(
        principal,
        _request(
            principal, MonitoringAction.READ_MONITORING, project_id="other-project"
        ),
    )
    assert denied.reason is MonitoringAuthorizationReason.PROJECT_SCOPE_DENIED


def test_medical_manager_can_review_and_dispose_without_default_second_approval() -> (
    None
):
    principal = _principal()
    review = authorize_monitoring_action(
        principal,
        _request(principal, MonitoringAction.REVIEW_AI_CANDIDATE),
    )
    disposition = authorize_monitoring_action(
        principal,
        _request(principal, MonitoringAction.CHANGE_RISK_DISPOSITION),
    )
    assert review.allowed is True
    assert disposition.allowed is True
    assert disposition.write_permitted is True


def test_assurance_actions_are_explicitly_scoped_to_medical_manager_or_director():
    manager = _principal()
    for action in (
        MonitoringAction.CREATE_ASSURANCE_TASK,
        MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
        MonitoringAction.REVIEW_ASSURANCE,
    ):
        decision = authorize_monitoring_action(manager, _request(manager, action))
        assert decision.allowed is True
        assert decision.write_permitted is True

    system_admin = _principal(MonitoringRole.SYSTEM_ADMIN, projects=("__system__",))
    denied = authorize_monitoring_action(
        system_admin,
        _request(
            system_admin,
            MonitoringAction.CREATE_ASSURANCE_TASK,
            project_id="__system__",
        ),
    )
    assert denied.reason is MonitoringAuthorizationReason.ROLE_NOT_PERMITTED


def test_medical_writer_is_read_and_export_only() -> None:
    principal = _principal(MonitoringRole.MEDICAL_WRITER)
    readable = authorize_monitoring_action(
        principal,
        _request(principal, MonitoringAction.READ_SOURCE_EVIDENCE),
    )
    denied = authorize_monitoring_action(
        principal,
        _request(principal, MonitoringAction.CHANGE_RISK_DISPOSITION),
    )
    assert readable.allowed is True
    assert readable.write_permitted is False
    assert denied.reason is MonitoringAuthorizationReason.ROLE_NOT_PERMITTED


def test_system_admin_cannot_change_medical_judgement() -> None:
    principal = _principal(MonitoringRole.SYSTEM_ADMIN, projects=("__system__",))
    runtime = authorize_monitoring_action(
        principal,
        _request(
            principal, MonitoringAction.ADMINISTER_RUNTIME, project_id="__system__"
        ),
    )
    medical = authorize_monitoring_action(
        principal,
        _request(
            principal,
            MonitoringAction.CHANGE_RISK_DISPOSITION,
            project_id="__system__",
        ),
    )
    assert runtime.allowed is True
    assert runtime.write_permitted is True
    assert medical.reason is MonitoringAuthorizationReason.ROLE_NOT_PERMITTED


def test_high_risk_disposition_requires_reauthentication_and_signature() -> None:
    principal = _principal()
    request = _request(
        principal,
        MonitoringAction.CHANGE_RISK_DISPOSITION,
        high_risk=True,
    )
    missing_reauth = authorize_monitoring_action(principal, request)
    assert (
        missing_reauth.reason is MonitoringAuthorizationReason.REAUTHENTICATION_REQUIRED
    )

    missing_signature = authorize_monitoring_action(
        principal,
        _request(
            principal,
            MonitoringAction.CHANGE_RISK_DISPOSITION,
            high_risk=True,
            reauthenticated=True,
        ),
    )
    assert (
        missing_signature.reason
        is MonitoringAuthorizationReason.ELECTRONIC_SIGNATURE_REQUIRED
    )

    allowed = authorize_monitoring_action(
        principal,
        _request(
            principal,
            MonitoringAction.CHANGE_RISK_DISPOSITION,
            high_risk=True,
            reauthenticated=True,
            signature=SIGNATURE,
        ),
    )
    assert allowed.allowed is True
    assert allowed.requires_e_signature is True


def test_high_risk_close_and_rule_change_are_director_only() -> None:
    manager = _principal()
    denied = authorize_monitoring_action(
        manager,
        _request(manager, MonitoringAction.CONFIRM_HIGH_RISK_CLOSE),
    )
    assert denied.reason is MonitoringAuthorizationReason.MEDICAL_DIRECTOR_ROLE_REQUIRED

    director = _principal(MonitoringRole.MEDICAL_DIRECTOR)
    allowed = authorize_monitoring_action(
        director,
        _request(
            director,
            MonitoringAction.CONFIRM_HIGH_RISK_CLOSE,
            reauthenticated=True,
            signature=SIGNATURE,
        ),
    )
    assert allowed.allowed is True
    assert allowed.write_permitted is True


def test_principal_mismatch_and_invalid_signature_do_not_authorize() -> None:
    principal = _principal()
    mismatch = authorize_monitoring_action(
        principal,
        MonitoringAuthorizationRequest(
            request_id="request-001",
            principal_id="other-user",
            project_id=PROJECT_ID,
            action=MonitoringAction.READ_MONITORING,
            target_scope="trial",
        ),
    )
    assert mismatch.reason is MonitoringAuthorizationReason.PRINCIPAL_MISMATCH
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _request(
            principal,
            MonitoringAction.APPROVE_RULE_CHANGE,
            signature="g" * 64,
        )


@pytest.mark.parametrize(
    "signature",
    ("A" * 64, " " + SIGNATURE, 123),
)
def test_signature_evidence_rejects_noncanonical_digest_shape(signature: object) -> None:
    principal = _principal()
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        _request(
            principal,
            MonitoringAction.APPROVE_RULE_CHANGE,
            signature=signature,
        )


def test_first_release_helper_is_explicit_and_decision_payload_is_stable() -> None:
    principal = build_first_release_medical_manager_principal(
        principal_id="user-001",
        project_ids=(PROJECT_ID,),
        authn_method="local-session",
        session_id="session-001",
    )
    decision = authorize_monitoring_action(
        principal,
        _request(principal, MonitoringAction.READ_MONITORING),
    )
    payload = authorization_decision_payload(decision)
    assert principal.roles == (MonitoringRole.MEDICAL_MANAGER,)
    assert payload["decision_sha256"] == decision.decision_sha256
    assert authorization_decision_payload(decision) == payload
