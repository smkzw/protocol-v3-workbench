from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from services.api.app.monitoring_audit_contract import (
    MonitoringAuditChainConflict,
    MonitoringAuditContractError,
    MonitoringAuditEvent,
    append_monitoring_audit_event,
    monitoring_audit_chain_payload,
    verify_monitoring_audit_chain,
)
from services.api.app.monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringAuthorizationRequest,
    MonitoringPrincipal,
    MonitoringRole,
    authorize_monitoring_action,
)


NOW = datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc)
PROJECT_ID = "proj_rux_03_002"


def _principal(*roles: MonitoringRole) -> MonitoringPrincipal:
    return MonitoringPrincipal(
        principal_id="user-001",
        roles=roles or (MonitoringRole.MEDICAL_MANAGER,),
        project_scope=(PROJECT_ID,),
        authenticated=True,
        authn_method="local-session",
        session_id="session-001",
        directory_revision="directory-v1",
    )


def _decision(
    principal: MonitoringPrincipal,
    action: MonitoringAction = MonitoringAction.CHANGE_RISK_DISPOSITION,
):
    return authorize_monitoring_action(
        principal,
        MonitoringAuthorizationRequest(
            request_id="request-001",
            principal_id=principal.principal_id,
            project_id=PROJECT_ID,
            action=action,
            target_scope="subject",
        ),
    )


def _event(
    principal: MonitoringPrincipal,
    *,
    audit_id: str = "audit-001",
    action: MonitoringAction = MonitoringAction.CHANGE_RISK_DISPOSITION,
    mutation_applied: bool = False,
    aggregate_version_before: int = 0,
    aggregate_version_after: int | None = None,
    prev_event_hash: str = "",
    payload: dict[str, object] | None = None,
) -> MonitoringAuditEvent:
    decision = _decision(principal, action)
    return MonitoringAuditEvent.from_authorization_decision(
        audit_id=audit_id,
        principal=principal,
        decision=decision,
        target_type="risk",
        target_id="risk-instance-001",
        source_revision="source-revision-001",
        mutation_applied=mutation_applied,
        aggregate_version_before=aggregate_version_before,
        aggregate_version_after=aggregate_version_after,
        occurred_at=NOW,
        prev_event_hash=prev_event_hash,
        payload=payload or {},
    )


def test_allowed_mutation_is_bound_to_decision_source_and_cas_versions() -> None:
    event = _event(
        _principal(),
        mutation_applied=True,
        payload={"disposition_state": "reviewed", "evidence_sha256": "a" * 64},
    )
    assert event.decision_allowed is True
    assert event.write_permitted is True
    assert event.aggregate_version_after == 1
    assert event.event_hash == event.public_dict()["event_hash"]
    with pytest.raises(TypeError):
        event.payload["changed"] = True  # type: ignore[index]


def test_denied_attempt_is_auditable_but_cannot_claim_a_mutation() -> None:
    writer = _principal(MonitoringRole.MEDICAL_WRITER)
    denied = _event(writer)
    assert denied.decision_allowed is False
    assert denied.write_permitted is False
    assert denied.mutation_applied is False
    with pytest.raises(
        MonitoringAuditContractError, match="allowed write authorization"
    ):
        _event(writer, mutation_applied=True)


def test_non_mutating_event_cannot_change_aggregate_version() -> None:
    principal = _principal()
    with pytest.raises(MonitoringAuditContractError, match="cannot change aggregate"):
        _event(
            principal,
            aggregate_version_before=1,
            aggregate_version_after=2,
        )


def test_principal_snapshot_mismatch_is_rejected() -> None:
    principal = _principal()
    other_session = MonitoringPrincipal(
        principal_id=principal.principal_id,
        roles=principal.roles,
        project_scope=principal.project_scope,
        authenticated=True,
        authn_method=principal.authn_method,
        session_id="session-rotated",
        directory_revision=principal.directory_revision,
    )
    with pytest.raises(MonitoringAuditContractError, match="principal hash"):
        MonitoringAuditEvent.from_authorization_decision(
            audit_id="audit-001",
            principal=other_session,
            decision=_decision(principal),
            target_type="risk",
            target_id="risk-instance-001",
            source_revision="source-revision-001",
            occurred_at=NOW,
        )


def test_sensitive_payload_keys_are_rejected_instead_of_persisted() -> None:
    with pytest.raises(MonitoringAuditContractError, match="secret-bearing"):
        _event(_principal(), payload={"session_id": "raw-session"})
    with pytest.raises(MonitoringAuditContractError, match="secret-bearing"):
        _event(_principal(), payload={"nested": {"access_token": "raw-token"}})


def test_chain_requires_predecessor_and_allows_exact_idempotent_replay() -> None:
    principal = _principal()
    first = _event(principal, action=MonitoringAction.READ_MONITORING)
    chain = append_monitoring_audit_event((), first)
    assert append_monitoring_audit_event(chain, first) is chain

    second = _event(
        principal,
        audit_id="audit-002",
        action=MonitoringAction.READ_SOURCE_EVIDENCE,
        prev_event_hash=first.event_hash,
    )
    chain = append_monitoring_audit_event(chain, second)
    assert verify_monitoring_audit_chain(chain) == second.event_hash
    assert len(monitoring_audit_chain_payload(chain)) == 2

    wrong_link = _event(
        principal,
        audit_id="audit-003",
        action=MonitoringAction.READ_MONITORING,
        prev_event_hash="f" * 64,
    )
    with pytest.raises(MonitoringAuditChainConflict, match="chain head"):
        append_monitoring_audit_event(chain, wrong_link)


def test_reusing_audit_id_with_changed_payload_is_blocked() -> None:
    principal = _principal()
    first = _event(principal)
    changed = _event(principal, payload={"reason": "changed"})
    with pytest.raises(MonitoringAuditChainConflict, match="reused"):
        append_monitoring_audit_event((first,), changed)


def test_target_and_hash_fields_are_closed_and_immutable() -> None:
    principal = _principal()
    with pytest.raises(MonitoringAuditContractError, match="target_type"):
        MonitoringAuditEvent.from_authorization_decision(
            audit_id="audit-001",
            principal=principal,
            decision=_decision(principal),
            target_type="unknown",  # type: ignore[arg-type]
            target_id="target-001",
            source_revision="source-revision-001",
            occurred_at=NOW,
        )
    with pytest.raises(MonitoringAuditContractError, match="lowercase SHA-256"):
        _event(principal, prev_event_hash="g" * 64)


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("authorization_decision_sha256", "A" * 64),
        ("authorization_decision_sha256", "a" * 64 + " "),
        ("authorization_decision_sha256", 123),
        ("prev_event_hash", "B" * 64),
        ("prev_event_hash", "b" * 64 + "\n"),
        ("prev_event_hash", 456),
    ),
)
def test_identity_hashes_require_exact_lowercase_bytes(field_name, value) -> None:
    event = _event(_principal())
    with pytest.raises(MonitoringAuditContractError, match="lowercase SHA-256"):
        replace(event, **{field_name: value, "event_hash": ""})


def test_empty_initial_predecessor_remains_canonical() -> None:
    event = _event(_principal(), prev_event_hash="")
    assert event.prev_event_hash == ""
