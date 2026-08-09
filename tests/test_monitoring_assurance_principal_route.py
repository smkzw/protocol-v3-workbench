from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.monitoring_assurance_repository import (
    MonitoringAssuranceRepository,
)
from services.api.app.monitoring_assurance_router import (
    create_monitoring_assurance_router,
)
from services.api.app.monitoring_assurance_service import MonitoringAssuranceService
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
)
from services.api.app.monitoring_assurance_repository import MonitoringAssuranceError
from services.api.app.monitoring_identity_authorization import MonitoringRole


PROJECT = "proj_principal_route"
TENANT = "tenant-kangzhe"
FROZEN = {
    "batch_id": "batch-001",
    "batch_revision": "batchrev-001",
    "mapping_revision": "mapping-v1",
    "protocol_version_id": "prot-v1",
    "rule_pack_revision": "rules-v1",
    "dictionary_revision": "meddra-26.1",
    "ctcae_revision": "ctcae-5.0",
    "model_revision": "model-v1",
    "risk_snapshot_id": "risk-snapshot-1",
}


def _principal(
    *,
    project_scope: tuple[str, ...] = (PROJECT,),
    roles: tuple[MonitoringRole, ...] = (MonitoringRole.MEDICAL_MANAGER,),
):
    return MonitoringAuthenticatedPrincipal(
        principal_id="verified-medical-manager",
        tenant_id=TENANT,
        roles=roles,
        project_scope=project_scope,
        issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        authenticated=True,
        authn_method="test-server-session",
        session_id="server-session-secret",
        directory_revision="directory-test-v1",
        verification_ref_sha256="a" * 64,
    )


def _client(tmp_path: Path, *, resolver=None):
    repository = MonitoringAssuranceRepository(tmp_path / "assurance.sqlite3")
    service = MonitoringAssuranceService(repository, risk_reader=lambda *_: [])
    app = FastAPI()
    app.include_router(
        create_monitoring_assurance_router(
            repository=repository,
            service=service,
            project_resolver=lambda project_id: project_id,
            principal_resolver=resolver,
            require_server_principal=True,
        )
    )
    return TestClient(app), repository


def _body(**overrides):
    payload = {
        "mode": "pre_lock",
        "frozen_identity": dict(FROZEN),
        "idempotency_key": "principal-create-1",
        "owner": "医学经理",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("suffix", "body"),
    [
        (
            "tasks/task-1/readiness",
            {"expected_version": True},
        ),
        (
            "tasks/task-1/readiness",
            {"expected_version": 1, "planned_subjects": "1"},
        ),
        (
            "tasks/task-1/readiness",
            {"expected_version": 1, "actual_subjects": False},
        ),
        (
            "tasks/task-1/readiness",
            {"expected_version": 1, "planned_sites": "1"},
        ),
        (
            "tasks/task-1/readiness",
            {"expected_version": 1, "actual_sites": True},
        ),
        (
            "tasks/task-1/readiness",
            {"expected_version": 1, "critical_domains_covered": "1"},
        ),
        (
            "tasks/task-1/readiness",
            {"expected_version": 1, "critical_domains_expected": False},
        ),
        (
            "tasks/task-1/full-recompute-proof",
            {
                "expected_version": "1",
                "idempotency_key": "strict-proof",
                "proof_payload": {"planned_subjects": 0},
            },
        ),
        (
            "tasks/task-1/rollups",
            {"expected_version": False, "idempotency_key": "strict-rollup"},
        ),
        (
            "tasks/task-1/rollups",
            {
                "expected_version": 1,
                "idempotency_key": "strict-rollup-size",
                "min_sample_size": "30",
            },
        ),
        (
            "tasks/task-1/rollups",
            {
                "expected_version": 1,
                "idempotency_key": "strict-rollup-approval-int",
                "site_method_approved": 1,
            },
        ),
        (
            "tasks/task-1/rollups",
            {
                "expected_version": 1,
                "idempotency_key": "strict-rollup-approval-string",
                "site_method_approved": "true",
            },
        ),
        (
            "tasks/task-1/medical-review",
            {
                "expected_version": True,
                "idempotency_key": "strict-review",
                "review_payload": {},
            },
        ),
        (
            "tasks/task-1/complete",
            {
                "expected_version": "1",
                "idempotency_key": "strict-complete",
                "reauthenticated": True,
                "signature_evidence_sha256": "a" * 64,
            },
        ),
        (
            "tasks/task-1/complete",
            {
                "expected_version": 1,
                "idempotency_key": "strict-complete-reauth-int",
                "reauthenticated": 0,
                "signature_evidence_sha256": "a" * 64,
            },
        ),
        (
            "tasks/task-1/complete",
            {
                "expected_version": 1,
                "idempotency_key": "strict-complete-reauth-string",
                "reauthenticated": "false",
                "signature_evidence_sha256": "a" * 64,
            },
        ),
    ],
)
def test_assurance_cas_and_count_fields_reject_bool_and_numeric_string(
    tmp_path: Path,
    suffix: str,
    body: dict,
):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/{suffix}",
        json=body,
    )
    assert response.status_code == 422, response.text
    assert repository.list_tasks(PROJECT) == []


def test_production_default_blocks_write_without_server_principal(tmp_path: Path):
    client, repository = _client(tmp_path)

    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(),
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
    assert repository.list_tasks(PROJECT) == []


def test_verified_principal_is_the_only_created_by_identity(tmp_path: Path):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())

    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(),
    )

    assert response.status_code == 201, response.text
    assert response.json()["task"]["created_by"] == "verified-medical-manager"
    events = repository.list_audit_events(PROJECT, response.json()["task"]["task_id"])
    assert len(events) == 1
    assert events[0].principal_id == "verified-medical-manager"
    assert events[0].decision_allowed is True
    assert events[0].mutation_applied is True
    assert len(events[0].source_revision) == 64
    assert "server-session-secret" not in str(events[0].public_dict())


def test_scoped_monitor_can_read_public_assurance_audit_chain(tmp_path: Path):
    client, _ = _client(tmp_path, resolver=lambda _request: _principal())
    created = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key="audit-read-create"),
    )
    task_id = created.json()["task"]["task_id"]

    response = client.get(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/audit"
    )

    assert response.status_code == 200, response.text
    assert response.json()["principal_id"] == "verified-medical-manager"
    assert len(response.json()["items"]) == 1
    assert response.json()["items"][0]["action"] == "create_assurance_task"
    assert "server-session-secret" not in response.text


def test_audit_read_requires_server_principal_and_read_role(tmp_path: Path):
    no_principal_client, _ = _client(tmp_path / "none")
    missing = no_principal_client.get(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/task-1/audit"
    )
    assert missing.status_code == 503

    admin_client, _ = _client(
        tmp_path / "admin",
        resolver=lambda _request: _principal(roles=(MonitoringRole.SYSTEM_ADMIN,)),
    )
    denied = admin_client.get(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/task-1/audit"
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "monitoring_role_not_permitted"


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "tasks", None),
        ("GET", "tasks/task-1", None),
        ("POST", "tasks/task-1/readiness", {"expected_version": 1}),
        ("GET", "tasks/task-1/full-recompute-proof", None),
        ("GET", "tasks/task-1/rollups", None),
    ],
)
def test_every_assurance_read_route_requires_server_principal(
    tmp_path: Path,
    method: str,
    suffix: str,
    body: dict | None,
):
    client, _ = _client(tmp_path / suffix.replace("/", "-"))
    response = client.request(
        method,
        f"/api/projects/{PROJECT}/monitoring/assurance/{suffix}",
        json=body,
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
    assert "读取" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "tasks", None),
        ("GET", "tasks/task-1", None),
        ("POST", "tasks/task-1/readiness", {"expected_version": 1}),
        ("GET", "tasks/task-1/full-recompute-proof", None),
        ("GET", "tasks/task-1/rollups", None),
    ],
)
def test_every_assurance_read_route_requires_medical_audit_role(
    tmp_path: Path,
    method: str,
    suffix: str,
    body: dict | None,
):
    client, _ = _client(
        tmp_path / f"admin-{suffix.replace('/', '-')}",
        resolver=lambda _request: _principal(roles=(MonitoringRole.SYSTEM_ADMIN,)),
    )
    response = client.request(
        method,
        f"/api/projects/{PROJECT}/monitoring/assurance/{suffix}",
        json=body,
    )

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "monitoring_role_not_permitted"


@pytest.mark.parametrize(
    ("method", "suffix", "body", "expected_status"),
    [
        ("GET", "tasks", None, 200),
        ("GET", "tasks/task-1", None, 200),
        ("POST", "tasks/task-1/readiness", {"expected_version": 1}, 200),
        ("GET", "tasks/task-1/full-recompute-proof", None, 404),
        ("GET", "tasks/task-1/rollups", None, 404),
    ],
)
def test_scoped_medical_manager_can_reach_each_read_route(
    tmp_path: Path,
    method: str,
    suffix: str,
    body: dict | None,
    expected_status: int,
):
    client, _ = _client(tmp_path, resolver=lambda _request: _principal())
    created = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key=f"read-route-{suffix.replace('/', '-')}") ,
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["task"]["task_id"]
    response = client.request(
        method,
        f"/api/projects/{PROJECT}/monitoring/assurance/{suffix.replace('task-1', task_id)}",
        json=body,
    )

    assert response.status_code == expected_status, response.text


def test_readiness_stale_version_fails_closed_without_mutation(tmp_path: Path):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    created = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key="readiness-cas-create"),
    )
    assert created.status_code == 201, created.text
    task = created.json()["task"]

    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task['task_id']}/readiness",
        json={"expected_version": task["version"] + 1},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "assurance_version_conflict"
    current = repository.get(PROJECT, task["task_id"])
    assert current.version == task["version"]
    assert [event.action.value for event in repository.list_audit_events(PROJECT, task["task_id"])] == [
        "create_assurance_task"
    ]


def test_authorized_assurance_lifecycle_persists_one_hash_linked_event_per_write(
    tmp_path: Path,
):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    created = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key="audit-create-1"),
    )
    assert created.status_code == 201, created.text
    task = created.json()["task"]
    proof = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task['task_id']}/full-recompute-proof",
        json={
            "expected_version": task["version"],
            "idempotency_key": "audit-proof-1",
            "proof_payload": {
                "planned_subjects": 0,
                "actual_subjects": 0,
                "planned_sites": 0,
                "actual_sites": 0,
                "critical_domains": ["AE"],
                "planned_rules": 1,
                "actual_rules": 1,
                "per_domain_counts": [],
                "failures": 0,
                "skips": 0,
                "retries": 0,
                "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                "subject_reconciliation_ok": True,
                "site_reconciliation_ok": True,
                "trial_reconciliation_ok": True,
                "owner": "owner-1",
                "lock_impact": "no_impact",
            },
        },
    )
    assert proof.status_code == 200, proof.text
    review = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task['task_id']}/medical-review",
        json={
            "expected_version": proof.json()["task"]["version"],
            "idempotency_key": "audit-review-1",
            "review_payload": {"conclusion": "reviewed"},
        },
    )
    assert review.status_code == 200, review.text
    complete = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task['task_id']}/complete",
        json={
            "expected_version": review.json()["task"]["version"],
            "idempotency_key": "audit-complete-1",
            "reauthenticated": True,
            "signature_evidence_sha256": "b" * 64,
        },
    )
    assert complete.status_code == 200, complete.text

    events = repository.list_audit_events(PROJECT, task["task_id"])
    assert [event.action.value for event in events] == [
        "create_assurance_task",
        "record_assurance_evidence",
        "review_assurance",
        "complete_assurance",
    ]
    assert events[-1].payload["signature_evidence_sha256"] == "b" * 64
    assert all(event.mutation_applied for event in events)
    assert all(
        event.prev_event_hash == (events[index - 1].event_hash if index else "")
        for index, event in enumerate(events)
    )


def test_exact_idempotent_replay_does_not_duplicate_durable_audit(tmp_path: Path):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    body = _body(idempotency_key="audit-replay-1")
    first = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks", json=body
    )
    replay = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks", json=body
    )
    assert first.status_code == 201
    assert replay.status_code == 200
    task_id = first.json()["task"]["task_id"]
    assert len(repository.list_audit_events(PROJECT, task_id)) == 1


def test_rollup_write_advances_task_cas_and_is_audited(tmp_path: Path):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    created = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(mode="pre_inspection", idempotency_key="audit-rollup-create"),
    )
    assert created.status_code == 201, created.text
    task = created.json()["task"]
    rollup = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task['task_id']}/rollups",
        json={
            "expected_version": task["version"],
            "idempotency_key": "audit-rollup-1",
        },
    )

    assert rollup.status_code == 200, rollup.text
    assert rollup.json()["task"]["version"] == task["version"] + 1
    events = repository.list_audit_events(PROJECT, task["task_id"])
    assert [event.action.value for event in events] == [
        "create_assurance_task",
        "record_assurance_evidence",
    ]


def test_project_audit_chain_remains_verifiable_across_two_task_modes(
    tmp_path: Path,
):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    first = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key="audit-chain-pre-lock"),
    )
    second = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(mode="pre_inspection", idempotency_key="audit-chain-pre-inspection"),
    )
    assert first.status_code == 201
    assert second.status_code == 201

    first_event = repository.list_audit_events(
        PROJECT, first.json()["task"]["task_id"]
    )[0]
    second_event = repository.list_audit_events(
        PROJECT, second.json()["task"]["task_id"]
    )[0]
    assert second_event.prev_event_hash == first_event.event_hash


def test_audit_append_failure_rolls_back_assurance_mutation(
    tmp_path: Path, monkeypatch
):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())

    def fail(*_args, **_kwargs):
        raise MonitoringAssuranceError("forced audit append failure")

    monkeypatch.setattr(repository, "_append_audit_event", fail)
    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key="audit-rollback-1"),
    )

    assert response.status_code == 409
    assert repository.list_tasks(PROJECT) == []


def test_persisted_audit_tamper_is_detected(tmp_path: Path):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key="audit-tamper-1"),
    )
    task_id = response.json()["task"]["task_id"]
    with sqlite3.connect(repository.db_path) as connection:
        row = connection.execute(
            "SELECT audit_id, event_json FROM monitoring_assurance_audit_chain"
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE monitoring_assurance_audit_chain SET event_json = ? WHERE audit_id = ?",
            (row[1].replace("task_created", "forged_event"), row[0]),
        )

    with pytest.raises(MonitoringAssuranceError, match="audit chain"):
        repository.list_audit_events(PROJECT, task_id)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("event_hash", "f" * 64, "row hash mismatch"),
        ("prev_event_hash", "e" * 64, "row predecessor mismatch"),
        ("created_at", "not-a-time", "row timestamp is invalid"),
    ),
)
def test_persisted_audit_row_metadata_tamper_is_detected(
    tmp_path: Path, field: str, value: str, message: str
):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key=f"audit-row-{field}"),
    )
    task_id = response.json()["task"]["task_id"]
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            f"UPDATE monitoring_assurance_audit_chain SET {field} = ? "
            "WHERE task_id = ?",
            (value, task_id),
        )

    with pytest.raises(MonitoringAssuranceError, match=message):
        repository.list_audit_events(PROJECT, task_id)


def test_persisted_audit_task_row_binding_tamper_is_detected(tmp_path: Path):
    client, repository = _client(tmp_path, resolver=lambda _request: _principal())
    first = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(idempotency_key="audit-row-task-first"),
    )
    second = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(mode="pre_inspection", idempotency_key="audit-row-task-second"),
    )
    first_task_id = first.json()["task"]["task_id"]
    second_task_id = second.json()["task"]["task_id"]
    with sqlite3.connect(repository.db_path) as connection:
        connection.execute(
            "UPDATE monitoring_assurance_audit_chain SET task_id = ? "
            "WHERE task_id = ?",
            (second_task_id, first_task_id),
        )

    with pytest.raises(MonitoringAssuranceError, match="task binding mismatch"):
        repository.list_audit_events(PROJECT, first_task_id)


def test_client_actor_is_rejected_even_when_it_matches_verified_principal(
    tmp_path: Path,
):
    client, _ = _client(tmp_path, resolver=lambda _request: _principal())

    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(actor="verified-medical-manager"),
    )

    assert response.status_code == 403
    assert (
        response.json()["detail"]["code"] == "monitoring_client_actor_not_authoritative"
    )


def test_principal_project_scope_is_checked_against_canonical_route(
    tmp_path: Path,
):
    client, _ = _client(
        tmp_path,
        resolver=lambda _request: _principal(project_scope=("another-project",)),
    )

    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "monitoring_project_scope_denied"


def test_principal_role_is_checked_for_assurance_creation(tmp_path: Path):
    client, _ = _client(
        tmp_path,
        resolver=lambda _request: _principal(roles=(MonitoringRole.SYSTEM_ADMIN,)),
    )

    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(),
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "monitoring_role_not_permitted"


def test_complete_requires_reauthentication_before_service_mutation(tmp_path: Path):
    client, _ = _client(tmp_path, resolver=lambda _request: _principal())
    created = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=_body(),
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["task"]["task_id"]

    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/complete",
        json={
            "expected_version": 1,
            "idempotency_key": "principal-complete-1",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "monitoring_reauthentication_required"
