from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from services.api.app.monitoring_authorized_route_context import (
    MonitoringAuthorizedRouteContext,
    MonitoringAuthorizedRouteContextError,
    build_monitoring_authorized_route_context,
)
from services.api.app.monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringRole,
)
from services.api.app.monitoring_runtime_principal import (
    MonitoringRuntimePrincipalDenied,
    MonitoringRuntimePrincipalError,
    MonitoringAuthenticatedPrincipal,
)
from services.api.app.monitoring_runtime_route_context import (
    build_monitoring_runtime_route_context,
)


NOW = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
TENANT_ID = "tenant-medical"
PROJECT_ID = "proj_rux_03_002"
SESSION_REF = "session-001"
VERIFICATION_REF = "a" * 64


def _runtime_principal(
    *, roles: tuple[str, ...] = (MonitoringRole.MEDICAL_MANAGER.value,)
) -> MonitoringAuthenticatedPrincipal:
    return MonitoringAuthenticatedPrincipal.from_server_verified_claims(
        {
            "server_verified": True,
            "principal_id": "user-001",
            "tenant_id": TENANT_ID,
            "roles": list(roles),
            "project_scope": [PROJECT_ID],
            "issued_at": "2026-08-03T07:00:00+00:00",
            "expires_at": "2026-08-03T09:00:00+00:00",
            "authenticated": True,
            "authn_method": "local-session",
            "session_id": SESSION_REF,
            "directory_revision": "directory-v1",
            "verification_ref_sha256": VERIFICATION_REF,
        },
        now=NOW,
    )


def _route_context(
    *,
    principal: MonitoringAuthenticatedPrincipal | None = None,
    action: MonitoringAction = MonitoringAction.CHANGE_RISK_DISPOSITION,
    client_actor: str | None = None,
):
    return build_monitoring_runtime_route_context(
        principal or _runtime_principal(),
        request_id="request-001",
        route_project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        target_scope="subject",
        action=action,
        client_actor=client_actor,
        now=NOW,
    )


def _build(**kwargs):
    route_kwargs = kwargs.pop("route_kwargs", {})
    params = {
        "audit_id": "audit-001",
        "target_type": "risk",
        "target_id": "risk-instance-001",
        "source_revision": "source-revision-001",
        "occurred_at": NOW,
    }
    params.update(kwargs)
    return build_monitoring_authorized_route_context(
        _route_context(**route_kwargs),
        **params,
    )


def test_allowed_write_decision_is_audited_but_never_claims_execution() -> None:
    context = _build()

    assert isinstance(context, MonitoringAuthorizedRouteContext)
    assert context.decision.allowed is True
    assert context.decision.write_permitted is True
    assert context.audit_event.decision_allowed is True
    assert context.audit_event.write_permitted is True
    assert context.audit_event.mutation_applied is False
    assert context.execution_write_permitted is False
    assert context.public_dict()["persisted"] is False


def test_denied_role_is_still_auditable_without_authority() -> None:
    context = _build(
        route_kwargs={
            "principal": _runtime_principal(
                roles=(MonitoringRole.MEDICAL_WRITER.value,)
            )
        }
    )

    assert context.decision.allowed is False
    assert context.audit_event.decision_allowed is False
    assert context.audit_event.write_permitted is False
    assert context.execution_write_permitted is False


def test_public_handoff_contains_hashes_not_raw_session_material() -> None:
    public = _build().public_dict()
    serialized = str(public)

    assert SESSION_REF not in serialized
    assert "session_id" not in public["principal"]
    assert public["principal"]["session_id_sha256"]
    assert public["authorization"]["decision_sha256"]
    assert public["audit_event"]["event_hash"]


def test_route_context_rejects_client_actor_before_authorization() -> None:
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="client_actor"):
        _route_context(client_actor="medical_manager")


def test_required_audit_binding_fields_are_fail_closed() -> None:
    with pytest.raises(MonitoringAuthorizedRouteContextError, match="audit_id"):
        _build(audit_id="")
    with pytest.raises(MonitoringAuthorizedRouteContextError, match="source_revision"):
        _build(source_revision="")
    with pytest.raises(MonitoringAuthorizedRouteContextError, match="target_id"):
        _build(target_id="")


def test_audit_payload_and_version_are_not_a_write_escape_hatch() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _build(aggregate_version_before=-1)
    with pytest.raises(ValueError, match="secret-bearing"):
        _build(payload={"session_id": SESSION_REF})


def test_direct_context_construction_rejects_decision_snapshot_drift() -> None:
    context = _build()
    drifted_decision = replace(
        context.decision,
        principal_sha256="b" * 64,
        decision_sha256="",
    )
    with pytest.raises(
        MonitoringAuthorizedRouteContextError, match="hash does not match"
    ):
        MonitoringAuthorizedRouteContext(
            route_context=context.route_context,
            principal=context.principal,
            decision=drifted_decision,
            audit_event=context.audit_event,
        )


def test_route_context_rejects_malformed_principal_and_expiry() -> None:
    with pytest.raises(MonitoringRuntimePrincipalError):
        _runtime_principal(roles=("unknown-role",))
    with pytest.raises(MonitoringRuntimePrincipalDenied, match="principal_expired"):
        MonitoringAuthenticatedPrincipal.from_server_verified_claims(
            {
                "server_verified": True,
                "principal_id": "user-001",
                "tenant_id": TENANT_ID,
                "roles": [MonitoringRole.MEDICAL_MANAGER.value],
                "project_scope": [PROJECT_ID],
                "issued_at": "2026-08-03T06:00:00+00:00",
                "expires_at": "2026-08-03T07:00:00+00:00",
                "authenticated": True,
                "authn_method": "local-session",
                "session_id": SESSION_REF,
                "directory_revision": "directory-v1",
                "verification_ref_sha256": VERIFICATION_REF,
            },
            now=datetime(2026, 8, 3, 7, 1, tzinfo=timezone.utc),
        )


def test_no_implicit_route_or_persistence_side_effects() -> None:
    context = _build()
    assert context.audit_event.prev_event_hash == ""
    assert context.audit_event.aggregate_version_before == 0
    assert context.audit_event.aggregate_version_after == 0
    assert context.mutation_applied is False
