from __future__ import annotations

import json

import pytest

from services.api.app.medical_writing_principal_acl import (
    MedicalWritingAccessRequest,
    MedicalWritingAclGrant,
    MedicalWritingAclPolicy,
    MedicalWritingAuthenticatedPrincipal,
    MedicalWritingPrincipalAclDenied,
    MedicalWritingPrincipalAclIntegrityError,
    authorize_medical_writing_request,
    require_medical_writing_authorization,
)


NOW = "2026-08-02T00:00:00+00:00"
LATER = "2026-08-03T00:00:00+00:00"
EXPIRED = "2026-08-01T00:00:00+00:00"
ISSUED = "2026-07-31T00:00:00+00:00"


def _principal(
    *,
    tenant: str = "tenant-a",
    subject: str = "user-1",
    authenticated: bool = True,
    expires: str = LATER,
):
    return MedicalWritingAuthenticatedPrincipal(
        subject_id=subject,
        tenant_id=tenant,
        assurance="synthetic-session-assurance",
        issued_at=ISSUED,
        expires_at=expires,
        authenticated=authenticated,
        role="medical_manager",
        authn_context="synthetic-test",
        session_ref_sha256="a" * 64,
    )


def _request(
    *,
    tenant: str = "tenant-a",
    project: str = "project-1",
    document: str | None = "protocol-1",
    action: str = "read",
    actor: str | None = "user-1",
):
    return MedicalWritingAccessRequest(
        request_id="request-1",
        tenant_id=tenant,
        project_id=project,
        document_id=document,
        action=action,
        client_actor=actor,
        trace_id="trace-1",
    )


def _policy(*, subject: str = "user-1", document: str | None = "protocol-1", actions=("read",)):
    return MedicalWritingAclPolicy(
        policy_id="policy-1",
        policy_revision=1,
        effective_from=EXPIRED,
        grants=(
            MedicalWritingAclGrant(
                grant_id="grant-1",
                tenant_id="tenant-a",
                project_id="project-1",
                document_id=document,
                subject_id=subject,
                actions=tuple(actions),
                effective_from=EXPIRED,
                expires_at=LATER,
            ),
        ),
    )


def test_explicit_grant_allows_and_decision_is_canonical_without_secrets():
    result = require_medical_writing_authorization(
        principal=_principal(),
        request=_request(),
        policy=_policy(),
        now=NOW,
    )
    payload = result.as_dict()
    assert result.allowed is True
    assert result.reason_code == "explicit_grant"
    assert payload["audit_payload"]["principal_subject"] == "user-1"
    assert "session_ref_sha256" not in json.dumps(payload)
    assert "synthetic-session-assurance" not in json.dumps(payload)
    assert len(result.decision_hash) == 64
    assert result.decision_hash == authorize_medical_writing_request(
        principal=_principal(), request=_request(), policy=_policy(), now=NOW
    ).decision_hash


@pytest.mark.parametrize(
    ("principal_kwargs", "request_kwargs", "policy", "reason"),
    [
        ({"authenticated": False}, {}, _policy(), "principal_not_authenticated"),
        ({"expires": EXPIRED}, {}, _policy(), "principal_expired"),
        ({"tenant": "tenant-b"}, {}, _policy(), "tenant_mismatch"),
        ({}, {"actor": "spoofed-user"}, _policy(), "client_actor_spoofed"),
        ({}, {"action": "export"}, _policy(), "no_matching_grant"),
        ({}, {"document": "other-document"}, _policy(), "no_matching_grant"),
        ({}, {"project": "other-project"}, _policy(), "no_matching_grant"),
    ],
)
def test_fail_closed_decision_codes(principal_kwargs, request_kwargs, policy, reason):
    result = authorize_medical_writing_request(
        principal=_principal(**principal_kwargs),
        request=_request(**request_kwargs),
        policy=policy,
        now=NOW,
    )
    assert result.allowed is False
    assert result.reason_code == reason
    with pytest.raises(MedicalWritingPrincipalAclDenied) as exc_info:
        require_medical_writing_authorization(
            principal=_principal(**principal_kwargs),
            request=_request(**request_kwargs),
            policy=policy,
            now=NOW,
        )
    assert exc_info.value.reason_code == reason


def test_project_scope_does_not_implicitly_grant_document_scope():
    project_policy = _policy(document=None)
    project_request = _request(document=None)
    document_request = _request(document="protocol-1")
    project_result = authorize_medical_writing_request(
        principal=_principal(), request=project_request, policy=project_policy, now=NOW
    )
    document_result = authorize_medical_writing_request(
        principal=_principal(), request=document_request, policy=project_policy, now=NOW
    )
    assert project_result.allowed is True
    assert document_result.allowed is False


def test_policy_and_grant_windows_fail_closed():
    policy_not_yet = MedicalWritingAclPolicy(
        policy_id="future-policy",
        policy_revision=1,
        effective_from=LATER,
        grants=_policy().grants,
    )
    result = authorize_medical_writing_request(
        principal=_principal(), request=_request(), policy=policy_not_yet, now=NOW
    )
    assert result.reason_code == "policy_not_yet_effective"

    expired_grant = _policy()
    grant = expired_grant.grants[0]
    expired_policy = MedicalWritingAclPolicy(
        policy_id="expired-grant-policy",
        policy_revision=1,
        effective_from=EXPIRED,
        grants=(
            MedicalWritingAclGrant(
                grant_id=grant.grant_id,
                tenant_id=grant.tenant_id,
                project_id=grant.project_id,
                document_id=grant.document_id,
                subject_id=grant.subject_id,
                actions=grant.actions,
                effective_from=EXPIRED,
                expires_at=EXPIRED,
            ),
        ),
    )
    with pytest.raises(MedicalWritingPrincipalAclIntegrityError):
        expired_policy.as_dict()


def test_malformed_inputs_are_rejected_without_default_permissions():
    with pytest.raises(MedicalWritingPrincipalAclIntegrityError):
        _request(action="*").as_dict()
    with pytest.raises(MedicalWritingPrincipalAclIntegrityError):
        _policy(actions=("read", "read")).as_dict()
    with pytest.raises(MedicalWritingPrincipalAclIntegrityError):
        MedicalWritingAclPolicy(
            policy_id="empty",
            policy_revision=1,
            effective_from=EXPIRED,
            grants=(),
        ).as_dict()
    with pytest.raises(MedicalWritingPrincipalAclIntegrityError):
        MedicalWritingAuthenticatedPrincipal(
            subject_id="user-1",
            tenant_id="tenant-a",
            assurance="assurance",
            issued_at=EXPIRED,
            expires_at=LATER,
            authenticated=True,
            role="medical_manager",
            session_ref_sha256="not-a-hash",
        ).as_dict()
