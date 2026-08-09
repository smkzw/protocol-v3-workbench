from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace

import pytest

from services.api.app.monitoring_authorized_route_context import (
    build_monitoring_authorized_route_context,
)
from services.api.app.monitoring_identity_authorization import MonitoringAction
from services.api.app.monitoring_read_action_contract import (
    MonitoringReadActionContractError,
    MonitoringReadSurface,
    build_monitoring_read_action_contract,
)
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
)
from services.api.app.monitoring_runtime_route_context import (
    build_monitoring_runtime_route_context,
)


NOW = datetime(2026, 8, 4, 5, 0, tzinfo=timezone.utc)
TENANT_ID = "tenant-medical"
PROJECT_ID = "proj_rux_03_002"
SOURCE_SHA = "a" * 64
RESPONSE_SHA = "b" * 64


def _principal(*, role: str = "medical_manager") -> MonitoringAuthenticatedPrincipal:
    return MonitoringAuthenticatedPrincipal.from_server_verified_claims(
        {
            "server_verified": True,
            "principal_id": "user-001",
            "tenant_id": TENANT_ID,
            "roles": [role],
            "project_scope": [PROJECT_ID],
            "issued_at": "2026-08-04T04:00:00+00:00",
            "expires_at": "2026-08-04T06:00:00+00:00",
            "authenticated": True,
            "authn_method": "local-session",
            "session_id": "session-secret-001",
            "directory_revision": "directory-v1",
            "verification_ref_sha256": "c" * 64,
        },
        now=NOW,
    )


def _context(
    *,
    surface: MonitoringReadSurface,
    action: MonitoringAction | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    role: str = "medical_manager",
    source_revision: str = SOURCE_SHA,
    request_id: str = "request-read-001",
    audit_id: str = "audit-read-001",
):
    resolved_action = action or {
        MonitoringReadSurface.DASHBOARD: MonitoringAction.READ_DASHBOARD,
        MonitoringReadSurface.WORKBENCH_INBOX: MonitoringAction.READ_WORKBENCH_INBOX,
        MonitoringReadSurface.AI_RUN_CATALOG: MonitoringAction.READ_AI_RUN,
        MonitoringReadSurface.AI_RUN_DETAIL: MonitoringAction.READ_AI_RUN,
        MonitoringReadSurface.AI_RUN_ARTIFACTS: MonitoringAction.READ_AI_ARTIFACT,
    }[surface]
    resolved_target_type = target_type or (
        "project"
        if surface
        in {
            MonitoringReadSurface.DASHBOARD,
            MonitoringReadSurface.WORKBENCH_INBOX,
            MonitoringReadSurface.AI_RUN_CATALOG,
        }
        else "runtime"
    )
    resolved_target_id = target_id or (
        PROJECT_ID if resolved_target_type == "project" else "run-001"
    )
    route = build_monitoring_runtime_route_context(
        _principal(role=role),
        request_id=request_id,
        route_project_id=PROJECT_ID,
        tenant_id=TENANT_ID,
        target_scope="trial",
        action=resolved_action,
        now=NOW,
    )
    return build_monitoring_authorized_route_context(
        route,
        audit_id=audit_id,
        target_type=resolved_target_type,
        target_id=resolved_target_id,
        source_revision=source_revision,
        occurred_at=NOW,
    )


def _build(surface: MonitoringReadSurface, **kwargs):
    context_kwargs = kwargs.pop("context_kwargs", {})
    params = {
        "source_snapshot_sha256": SOURCE_SHA,
        "response_snapshot_sha256": RESPONSE_SHA,
        "idempotency_key": f"{surface.value}:read:001",
        "cas_version": 0,
    }
    params.update(kwargs)
    return build_monitoring_read_action_contract(
        _context(surface=surface, **context_kwargs),
        surface=surface,
        **params,
    )


@pytest.mark.parametrize(
    "surface",
    tuple(MonitoringReadSurface),
)
def test_each_surface_binds_exact_action_and_non_mutating_cas(surface) -> None:
    contract = _build(surface)

    assert contract.action.value in {
        "read_dashboard",
        "read_workbench_inbox",
        "read_ai_run",
        "read_ai_artifact",
    }
    assert contract.project_id == PROJECT_ID
    assert contract.tenant_id == TENANT_ID
    assert contract.audit_id.endswith("001")
    assert contract.authorized_context.execution_write_permitted is False
    assert contract.authorized_context.audit_event.mutation_applied is False
    assert contract.cas_version == 0
    assert contract.public_dict()["persisted"] is False


def test_same_read_request_replays_to_the_same_contract_identity() -> None:
    context_kwargs = {
        "request_id": "request-replay-001",
        "audit_id": "audit-replay-001",
    }
    first = _build(
        MonitoringReadSurface.DASHBOARD,
        context_kwargs=context_kwargs,
        idempotency_key="dashboard:read:replay",
    )
    second = _build(
        MonitoringReadSurface.DASHBOARD,
        context_kwargs=context_kwargs,
        idempotency_key="dashboard:read:replay",
    )

    assert first.contract_sha256 == second.contract_sha256
    assert first.idempotency_key_sha256 == second.idempotency_key_sha256


def test_surface_action_mismatch_is_fail_closed() -> None:
    with pytest.raises(MonitoringReadActionContractError, match="requires action"):
        _build(
            MonitoringReadSurface.DASHBOARD,
            context_kwargs={"action": MonitoringAction.READ_MONITORING},
        )


def test_denied_or_write_authorization_cannot_become_a_read_handoff() -> None:
    with pytest.raises(MonitoringReadActionContractError, match="denied"):
        _build(
            MonitoringReadSurface.DASHBOARD,
            context_kwargs={"role": "medical_writer"},
        )


def test_source_response_idempotency_and_cas_evidence_are_required() -> None:
    with pytest.raises(MonitoringReadActionContractError, match="source snapshot"):
        _build(
            MonitoringReadSurface.DASHBOARD,
            context_kwargs={"source_revision": "d" * 64},
        )
    with pytest.raises(MonitoringReadActionContractError, match="response_snapshot_sha256"):
        _build(
            MonitoringReadSurface.DASHBOARD,
            response_snapshot_sha256="not-a-digest",
        )
    with pytest.raises(MonitoringReadActionContractError, match="idempotency_key"):
        _build(MonitoringReadSurface.DASHBOARD, idempotency_key="../token")
    with pytest.raises(MonitoringReadActionContractError, match="cas_version"):
        _build(MonitoringReadSurface.DASHBOARD, cas_version=1)


def test_target_scope_and_immutable_hash_drift_are_rejected() -> None:
    with pytest.raises(MonitoringReadActionContractError, match="project audit target"):
        _build(
            MonitoringReadSurface.DASHBOARD,
            context_kwargs={"target_type": "runtime", "target_id": "run-001"},
        )
    contract = _build(MonitoringReadSurface.DASHBOARD)
    with pytest.raises(MonitoringReadActionContractError, match="contract_sha256"):
        replace(
            contract,
            response_snapshot_sha256="d" * 64,
            contract_sha256=contract.contract_sha256,
        )


def test_public_payload_hashes_secrets_and_keeps_read_handoff_non_persistent() -> None:
    contract = _build(
        MonitoringReadSurface.WORKBENCH_INBOX,
        idempotency_key="inbox:read:secret-like-but-safe",
    )
    public = contract.public_dict()
    serialized = str(public)

    assert "session-secret-001" not in serialized
    assert "secret-like-but-safe" not in serialized
    assert public["idempotency_key_sha256"] == contract.idempotency_key_sha256
    assert public["read_only"] is True
    assert public["persisted"] is False
    assert public["mutation_applied"] is False
