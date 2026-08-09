from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
)
from services.api.app.medical_risk_repository import MedicalRiskRepository
from services.api.app.monitoring_assurance_repository import (
    AssuranceIdempotencyConflictError,
    AssuranceDriftError,
    MonitoringAssuranceAuditContext,
    MonitoringAssuranceError,
    MonitoringAssuranceRepository,
)
from services.api.app.monitoring_assurance_router import (
    create_monitoring_assurance_router,
)
from services.api.app.monitoring_assurance_service import (
    MonitoringAssuranceService,
    RiskReference,
    create_medical_risk_reference_reader,
    validate_pre_inspection_rollup,
)
from services.api.app.monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringAuthorizationRequest,
    MonitoringPrincipal,
    MonitoringRole,
    authorize_monitoring_action,
)


PROJECT = "proj_test"
FROZEN = {
    "batch_id": "batch-001",
    "batch_revision": "batchrev-001",
    "mapping_revision": "mapping-v3",
    "protocol_version_id": "prot-v1",
    "rule_pack_revision": "rules-v5",
    "dictionary_revision": "meddra-26.1",
    "ctcae_revision": "ctcae-5.0",
    "model_revision": "model-v1",
    "risk_snapshot_id": "risksnap_abc123",
}
FROZEN_ALT = {**FROZEN, "risk_snapshot_id": "risksnap_xyz789"}


def _risk(
    *,
    risk_instance_id: str = "ri-1",
    risk_key: str = "rk-1",
    subject_id: str = "S001",
    site_id: str = "SITE-A",
    primary_category: str = "AE/MH漏报",
    severity: str = "high",
    status: str = "new",
    is_safety_pv: bool = False,
    is_concomitant_medication: bool = False,
    is_study_treatment: bool = False,
    closure_evidence_present: bool = False,
    scope_type: str = "subject",
    scope_id: str = "",
    batch_delta: str = "new",
) -> RiskReference:
    return RiskReference(
        risk_instance_id=risk_instance_id,
        risk_key=risk_key,
        project_id=PROJECT,
        subject_id=subject_id,
        site_id=site_id,
        primary_category=primary_category,
        severity=severity,
        status=status,
        scope_type=scope_type,
        scope_id=scope_id or subject_id,
        batch_delta=batch_delta,
        is_safety_pv=is_safety_pv,
        is_concomitant_medication=is_concomitant_medication,
        is_study_treatment=is_study_treatment,
        closure_evidence_present=closure_evidence_present,
    )


def _risks_reader(risks):
    def reader(project_id, snapshot_id):
        return list(risks)
    return reader


@pytest.mark.parametrize(
    "signature",
    [f" {'a' * 64}", f"{'a' * 64} ", "A" * 64, 123],
)
def test_assurance_audit_context_rejects_noncanonical_signature_digest(
    signature: object,
) -> None:
    principal = MonitoringPrincipal(
        principal_id="user-001",
        roles=(MonitoringRole.MEDICAL_MANAGER,),
        project_scope=(PROJECT,),
        authenticated=True,
        authn_method="local-session",
        session_id="session-001",
        directory_revision="directory-v1",
    )
    decision = authorize_monitoring_action(
        principal,
        MonitoringAuthorizationRequest(
            request_id="request-001",
            principal_id=principal.principal_id,
            project_id=PROJECT,
            action=MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
            target_scope="trial",
        ),
    )
    assert decision.allowed is True
    with pytest.raises(MonitoringAssuranceError, match="lowercase SHA-256"):
        MonitoringAssuranceAuditContext(
            principal=principal,
            decision=decision,
            signature_evidence_sha256=signature,
        )


def _make_client(tmp_path, risks=None):
    repo = MonitoringAssuranceRepository(Path(tmp_path) / "assurance.sqlite3")
    svc = MonitoringAssuranceService(repo, risk_reader=_risks_reader(risks or []))
    app = FastAPI()
    app.include_router(
        create_monitoring_assurance_router(
            repository=repo,
            service=svc,
            project_resolver=lambda pid: (
                PROJECT if pid in {PROJECT, "alias-1"} else pid
            ),
            require_server_principal=False,
        )
    )
    return TestClient(app), repo, svc


def _persisted_risk(
    *,
    risk_id: str,
    risk_key: str,
    category: str,
    source_domain: str,
    subject_id: str,
    site_id: str,
    safety_pv: bool = False,
) -> RiskCase:
    tags = [f"source_domain:{source_domain}"]
    if safety_pv:
        tags.append("safety_pv")
    return RiskCase(
        risk_id=risk_id,
        risk_key=risk_key,
        risk_instance_id=risk_id,
        project_id=PROJECT,
        module="medical_monitoring",
        risk_type=category,
        primary_category=category,
        tags=tags,
        title=f"Risk {risk_id}",
        subject_id=subject_id,
        site_id=site_id,
        severity=RiskSeverity.HIGH,
        status=RiskStatus.ACTION_REQUIRED,
        source_batch_id="batch-real-1",
        rule_id=f"rule-{risk_id}",
        rationale="Persisted medical risk fact",
        recommended_action="Medical review",
        created_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
    )


def _real_risk_repository(tmp_path):
    repository = MedicalRiskRepository(Path(tmp_path) / "medical-risks.sqlite3")
    snapshot = repository.save_snapshot(
        project_id=PROJECT,
        source_batch_id="batch-real-1",
        source_revision="source-real-1",
        rule_profile_revision="rules-real-1",
        engine_version="engine-real-1",
        evaluated_subject_count=2,
        risks=[
            _persisted_risk(
                risk_id="risk-cm-1",
                risk_key="riskkey-cm-1",
                category="prohibited_concomitant_medication_pd",
                source_domain="CM",
                subject_id="S001",
                site_id="SITE-A",
            ),
            _persisted_risk(
                risk_id="risk-study-1",
                risk_key="riskkey-study-1",
                category="study_treatment_interruption",
                source_domain="EX",
                subject_id="S001",
                site_id="SITE-A",
            ),
            _persisted_risk(
                risk_id="risk-pv-1",
                risk_key="riskkey-pv-1",
                category="laboratory_abnormality",
                source_domain="LB",
                subject_id="S002",
                site_id="SITE-B",
                safety_pv=True,
            ),
        ],
    )
    return repository, snapshot


def _make_real_repository_client(tmp_path):
    risk_repository, snapshot = _real_risk_repository(tmp_path)
    assurance_repository = MonitoringAssuranceRepository(
        Path(tmp_path) / "assurance.sqlite3"
    )
    service = MonitoringAssuranceService(
        assurance_repository,
        risk_reader=create_medical_risk_reference_reader(risk_repository),
    )
    app = FastAPI()
    app.include_router(
        create_monitoring_assurance_router(
            repository=assurance_repository,
            service=service,
            project_resolver=lambda pid: pid,
            require_server_principal=False,
        )
    )
    return TestClient(app), risk_repository, snapshot


def _create_task(client, **overrides):
    body = {
        "mode": "pre_lock",
        "frozen_identity": dict(FROZEN),
        "idempotency_key": "create-1",
        "actor": "medical_manager",
        "owner": "owner-1",
    }
    body.update(overrides)
    response = client.post(
        f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
        json=body,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


# ---------------------------------------------------------------------------
# Migration / restart
# ---------------------------------------------------------------------------


class TestMigrationRestart:
    def test_repository_survives_restart(self, tmp_path):
        path = tmp_path / "assurance.sqlite3"
        repo1 = MonitoringAssuranceRepository(path)
        result = repo1.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="create-1",
            actor="medical_manager",
        )
        task_id = result.task.task_id

        repo2 = MonitoringAssuranceRepository(path)
        task = repo2.get(PROJECT, task_id)
        assert task.task_id == task_id
        assert task.status == "draft"
        events = repo2.list_events(PROJECT, task_id)
        assert events[0].event_type == "task_created"

    @pytest.mark.parametrize(
        ("field_name", "value", "message"),
        (
            ("project_id", "other-project", "parent binding mismatch"),
            ("payload_json", "[]", "payload must be an object"),
            ("created_at", "not-a-time", "timestamp is invalid"),
        ),
    )
    def test_lifecycle_event_root_tamper_is_rejected_on_read(
        self,
        tmp_path,
        field_name,
        value,
        message,
    ):
        path = tmp_path / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        created = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key=f"event-root-tamper-{field_name}",
            actor="medical_manager",
        ).task

        with sqlite3.connect(path) as connection:
            connection.execute(
                f"UPDATE monitoring_assurance_events SET {field_name} = ? "
                "WHERE task_id = ?",
                (value, created.task_id),
            )

        with pytest.raises(AssuranceDriftError, match=message):
            repo.list_events(PROJECT, created.task_id)

    def test_semantically_valid_frozen_identity_tamper_is_rejected_on_restart_read(
        self, tmp_path
    ):
        path = tmp_path / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        created = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="create-task-tamper",
            actor="medical_manager",
        ).task
        tampered = dict(FROZEN)
        tampered["batch_revision"] = "batchrev-tampered"
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_assurance_tasks SET frozen_identity_json = ? "
                "WHERE task_id = ?",
                (json.dumps(tampered), created.task_id),
            )

        reopened = MonitoringAssuranceRepository(path)
        with pytest.raises(
            AssuranceDriftError,
            match="assurance task identity hash mismatch",
        ):
            reopened.get(PROJECT, created.task_id)

    @pytest.mark.parametrize(
        ("field_name", "value", "message"),
        (
            ("version", 1.5, "version is invalid"),
            ("created_at", "not-a-time", "timestamps are invalid"),
            ("created_by", " medical_manager ", "created_by is invalid"),
        ),
    )
    def test_task_root_shape_tamper_is_rejected_on_restart_read(
        self,
        tmp_path,
        field_name,
        value,
        message,
    ):
        path = tmp_path / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        created = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key=f"root-tamper-{field_name}",
            actor="medical_manager",
        ).task

        with sqlite3.connect(path) as connection:
            connection.execute(
                f"UPDATE monitoring_assurance_tasks SET {field_name} = ? "
                "WHERE task_id = ?",
                (value, created.task_id),
            )

        with pytest.raises(AssuranceDriftError, match=message):
            MonitoringAssuranceRepository(path).get(PROJECT, created.task_id)


# ---------------------------------------------------------------------------
# Create / list / get / idempotency / cross-project
# ---------------------------------------------------------------------------


class TestCreateListGet:
    def test_create_list_get_task(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        created = _create_task(client)
        assert created["task"]["mode"] == "pre_lock"
        assert created["task"]["status"] == "draft"
        assert created["replayed"] is False

        replay = _create_task(client)
        assert replay["replayed"] is True

        listed = client.get(f"/api/projects/{PROJECT}/monitoring/assurance/tasks")
        assert listed.status_code == 200
        assert len(listed.json()["items"]) == 1

        task_id = created["task"]["task_id"]
        detail = client.get(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}"
        )
        assert detail.status_code == 200
        assert detail.json()["task"]["task_id"] == task_id

    def test_idempotency_replay_same_and_conflict_different(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        body = {
            "mode": "pre_lock",
            "frozen_identity": dict(FROZEN),
            "idempotency_key": "idem-1",
            "actor": "medical_manager",
        }
        first = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks", json=body
        )
        assert first.status_code == 201

        replay = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks", json=body
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True

        conflict_body = {
            "mode": "pre_lock",
            "frozen_identity": dict(FROZEN_ALT),
            "idempotency_key": "idem-1",
            "actor": "other",
        }
        conflict = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks", json=conflict_body
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "assurance_idempotency_conflict"

    def test_only_one_active_task_per_mode(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        _create_task(client)
        body2 = {
            "mode": "pre_lock",
            "frozen_identity": dict(FROZEN_ALT),
            "idempotency_key": "create-2",
        }
        response = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks", json=body2
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "assurance_state_conflict"

    def test_pre_lock_and_pre_inspection_coexist(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        r1 = _create_task(client, mode="pre_lock")
        r2 = _create_task(client, mode="pre_inspection", idempotency_key="create-2")
        assert r1["task"]["mode"] == "pre_lock"
        assert r2["task"]["mode"] == "pre_inspection"

    def test_cross_project_get_returns_404(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        created = _create_task(client)
        task_id = created["task"]["task_id"]
        response = client.get(
            f"/api/projects/other-project/monitoring/assurance/tasks/{task_id}"
        )
        assert response.status_code == 404


class TestIdempotencyReadShape:
    def _create_repository_task(self, tmp_path):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        result = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="idem-root",
            actor="medical_manager",
        )
        return path, repo, result.task

    def test_replay_operation_binding_is_checked(self, tmp_path):
        path, repo, task = self._create_repository_task(tmp_path)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_assurance_idempotency SET operation = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                ("complete_task", PROJECT, "idem-root"),
            )

        with pytest.raises(
            AssuranceIdempotencyConflictError, match="different operation"
        ):
            repo.create_task(
                project_id=PROJECT,
                mode="pre_lock",
                frozen_identity=FROZEN,
                idempotency_key="idem-root",
                actor="medical_manager",
            )

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        (
            ("response_json", "[]", "response is invalid"),
            ("created_at", "not-a-time", "timestamp is invalid"),
        ),
    )
    def test_replay_persisted_root_shape_is_checked(
        self, tmp_path, field, value, message
    ):
        path, repo, task = self._create_repository_task(tmp_path)
        with sqlite3.connect(path) as connection:
            connection.execute(
                f"UPDATE monitoring_assurance_idempotency SET {field} = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                (value, PROJECT, "idem-root"),
            )

        with pytest.raises(AssuranceDriftError, match=message):
            repo.create_task(
                project_id=PROJECT,
                mode="pre_lock",
                frozen_identity=FROZEN,
                idempotency_key="idem-root",
                actor="medical_manager",
            )

    def test_replay_response_task_binding_is_checked(self, tmp_path):
        path, repo, task = self._create_repository_task(tmp_path)
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT response_json FROM monitoring_assurance_idempotency "
                "WHERE project_id = ? AND idempotency_key = ?",
                (PROJECT, "idem-root"),
            ).fetchone()
            assert row is not None
            response = json.loads(row[0])
            response["task"]["task_id"] = "other-task"
            connection.execute(
                "UPDATE monitoring_assurance_idempotency SET response_json = ? "
                "WHERE project_id = ? AND idempotency_key = ?",
                (json.dumps(response), PROJECT, "idem-root"),
            )

        with pytest.raises(AssuranceDriftError, match="task binding mismatch"):
            repo.create_task(
                project_id=PROJECT,
                mode="pre_lock",
                frozen_identity=FROZEN,
                idempotency_key="idem-root",
                actor="medical_manager",
            )


# ---------------------------------------------------------------------------
# Version CAS conflict
# ---------------------------------------------------------------------------


class TestVersionCAS:
    def test_version_conflict_returns_409(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        created = _create_task(client)
        task_id = created["task"]["task_id"]

        # Use stale version on a write endpoint (medical-review)
        response = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/medical-review",
            json={
                "expected_version": 999,
                "idempotency_key": "review-cas",
                "review_payload": {"conclusion": "ok"},
            },
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "assurance_version_conflict"


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------


class TestDrift:
    def test_drifted_identity_blocks_proof(self, tmp_path):
        repo = MonitoringAssuranceRepository(tmp_path / "a.sqlite3")
        result = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="c1",
            actor="m",
        )
        task = result.task
        with pytest.raises(AssuranceDriftError):
            repo.save_full_recompute_proof(
                project_id=PROJECT,
                task_id=task.task_id,
                proof_payload={
                    "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                    "owner": "o",
                    "lock_impact": "none",
                },
                expected_version=task.version,
                actor="m",
                idempotency_key="p1",
                frozen_identity=FROZEN_ALT,
            )


# ---------------------------------------------------------------------------
# Readiness gaps
# ---------------------------------------------------------------------------


class TestReadiness:
    def test_readiness_gaps_prevent_completion(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        created = _create_task(client)
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/readiness",
            json={
                "expected_version": v,
                "planned_subjects": 10,
                "actual_subjects": 5,
                "planned_sites": 3,
                "actual_sites": 2,
                "critical_domains_expected": 5,
                "critical_domains_covered": 3,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["ready"] is False
        assert "subject_coverage_incomplete" in resp.json()["gaps"]

        # Cannot complete from draft state
        complete = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/complete",
            json={
                "expected_version": v,
                "idempotency_key": "complete-1",
                "confirmed_by": "medical_manager",
            },
        )
        assert complete.status_code == 409


# ---------------------------------------------------------------------------
# Full recompute proof
# ---------------------------------------------------------------------------


class TestFullRecomputeProof:
    @pytest.mark.parametrize(
        ("field", "value"),
        (
            ("failures", False),
            ("skips", ""),
            ("planned_subjects", -1),
            ("subject_reconciliation_ok", "false"),
        ),
    )
    def test_malformed_counts_and_booleans_fail_closed(
        self, tmp_path, field, value
    ):
        repo = MonitoringAssuranceRepository(Path(tmp_path) / "assurance.sqlite3")
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="create-1",
            actor="medical_manager",
        ).task
        payload = {
            "planned_subjects": 1,
            "actual_subjects": 1,
            "planned_sites": 1,
            "actual_sites": 1,
            "critical_domains": ["AE"],
            "planned_rules": 1,
            "actual_rules": 1,
            "per_domain_counts": [],
            "failures": 0,
            "skips": 0,
            "retries": 0,
            "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
            "owner": "owner-1",
            "lock_impact": "no_impact",
        }
        payload[field] = value

        with pytest.raises(MonitoringAssuranceError, match=field):
            repo.save_full_recompute_proof(
                project_id=PROJECT,
                task_id=task.task_id,
                proof_payload=payload,
                expected_version=task.version,
                actor="medical_manager",
                idempotency_key=f"proof-{field}",
            )

    def test_persisted_malformed_proof_is_rejected_on_read(self, tmp_path):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="create-1",
            actor="medical_manager",
        ).task
        repo.save_full_recompute_proof(
            project_id=PROJECT,
            task_id=task.task_id,
            proof_payload={
                "planned_subjects": 1,
                "actual_subjects": 1,
                "planned_sites": 1,
                "actual_sites": 1,
                "critical_domains": ["AE"],
                "planned_rules": 1,
                "actual_rules": 1,
                "per_domain_counts": [],
                "failures": 0,
                "skips": 0,
                "retries": 0,
                "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                "owner": "owner-1",
                "lock_impact": "no_impact",
            },
            expected_version=task.version,
            actor="medical_manager",
            idempotency_key="proof-1",
        )
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT proof_id, proof_json FROM monitoring_assurance_full_recompute_proofs"
            ).fetchone()
            assert row is not None
            proof_payload = json.loads(row[1])
            proof_payload["failures"] = False
            connection.execute(
                "UPDATE monitoring_assurance_full_recompute_proofs SET proof_json = ? WHERE proof_id = ?",
                (json.dumps(proof_payload), row[0]),
            )

        with pytest.raises(MonitoringAssuranceError, match="failures"):
            repo.get_full_recompute_proof(PROJECT, task.task_id)

    def test_persisted_semantically_valid_proof_tamper_is_rejected_on_read(
        self, tmp_path
    ):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="create-valid-tamper-1",
            actor="medical_manager",
        ).task
        repo.save_full_recompute_proof(
            project_id=PROJECT,
            task_id=task.task_id,
            proof_payload={
                "planned_subjects": 1,
                "actual_subjects": 1,
                "planned_sites": 1,
                "actual_sites": 1,
                "critical_domains": ["AE"],
                "planned_rules": 1,
                "actual_rules": 1,
                "per_domain_counts": [],
                "failures": 0,
                "skips": 0,
                "retries": 0,
                "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                "owner": "owner-1",
                "lock_impact": "no_impact",
            },
            expected_version=task.version,
            actor="medical_manager",
            idempotency_key="proof-valid-tamper-1",
        )
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT proof_id, proof_json FROM monitoring_assurance_full_recompute_proofs"
            ).fetchone()
            assert row is not None
            proof_payload = json.loads(row[1])
            proof_payload["owner"] = "tampered-owner"
            connection.execute(
                "UPDATE monitoring_assurance_full_recompute_proofs SET proof_json = ? WHERE proof_id = ?",
                (json.dumps(proof_payload), row[0]),
            )

        with pytest.raises(AssuranceDriftError, match="content hash mismatch"):
            repo.get_full_recompute_proof(PROJECT, task.task_id)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        (
            ("mode", "not-a-mode", "mode is invalid"),
            ("critical_domains", "AE", "critical_domains is invalid"),
            ("per_domain_counts", ["not-a-mapping"], "per_domain_counts is invalid"),
            ("created_at", "not-a-time", "timestamps are invalid"),
        ),
    )
    def test_persisted_proof_root_shape_is_rejected_on_read(
        self, tmp_path, field, value, message
    ):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key=f"proof-root-{field}",
            actor="medical_manager",
        ).task
        repo.save_full_recompute_proof(
            project_id=PROJECT,
            task_id=task.task_id,
            proof_payload={
                "planned_subjects": 1,
                "actual_subjects": 1,
                "planned_sites": 1,
                "actual_sites": 1,
                "critical_domains": ["AE"],
                "planned_rules": 1,
                "actual_rules": 1,
                "per_domain_counts": [],
                "failures": 0,
                "skips": 0,
                "retries": 0,
                "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                "owner": "owner-1",
                "lock_impact": "no_impact",
            },
            expected_version=task.version,
            actor="medical_manager",
            idempotency_key=f"proof-save-{field}",
        )

        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT proof_id, proof_json FROM monitoring_assurance_full_recompute_proofs"
            ).fetchone()
            assert row is not None
            proof_payload = json.loads(row[1])
            proof_payload[field] = value
            connection.execute(
                "UPDATE monitoring_assurance_full_recompute_proofs SET proof_json = ? WHERE proof_id = ?",
                (json.dumps(proof_payload), row[0]),
            )

        with pytest.raises(AssuranceDriftError, match=message):
            repo.get_full_recompute_proof(PROJECT, task.task_id)

    def test_persisted_proof_row_rejects_padded_project_identity(self, tmp_path):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="proof-row-project-padding",
            actor="medical_manager",
        ).task
        repo.save_full_recompute_proof(
            project_id=PROJECT,
            task_id=task.task_id,
            proof_payload={
                "planned_subjects": 1,
                "actual_subjects": 1,
                "planned_sites": 1,
                "actual_sites": 1,
                "critical_domains": ["AE"],
                "planned_rules": 1,
                "actual_rules": 1,
                "per_domain_counts": [],
                "failures": 0,
                "skips": 0,
                "retries": 0,
                "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                "owner": "owner-1",
                "lock_impact": "no_impact",
            },
            expected_version=task.version,
            actor="medical_manager",
            idempotency_key="proof-row-project-padding-save",
        )

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_assurance_full_recompute_proofs SET project_id = ? "
                "WHERE task_id = ?",
                (f" {PROJECT} ", task.task_id),
            )

        with pytest.raises(AssuranceDriftError, match="proof project_id is invalid"):
            repo.get_full_recompute_proof(PROJECT, task.task_id)

    def test_persisted_malformed_medical_review_flag_is_rejected_on_read(
        self, tmp_path
    ):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_lock",
            frozen_identity=FROZEN,
            idempotency_key="create-flag-1",
            actor="medical_manager",
        ).task

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_assurance_tasks "
                "SET medical_review_recorded = ? WHERE task_id = ?",
                ("false", task.task_id),
            )

        with pytest.raises(MonitoringAssuranceError, match="medical_review_recorded"):
            repo.get(PROJECT, task.task_id)

    @pytest.mark.parametrize(
        ("field", "value", "message"),
        (
            ("subject_rollup", "not-a-list", "subject_rollup is invalid"),
            ("trial_rollup", [], "trial_rollup is invalid"),
            ("created_at", "not-a-time", "timestamps are invalid"),
        ),
    )
    def test_persisted_rollup_root_shape_is_rejected_on_read(
        self, tmp_path, field, value, message
    ):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_inspection",
            frozen_identity=FROZEN,
            idempotency_key=f"rollup-root-{field}",
            actor="medical_manager",
        ).task
        repo.save_rollup(
            project_id=PROJECT,
            task_id=task.task_id,
            rollup_payload={"risk_snapshot_id": FROZEN["risk_snapshot_id"]},
            expected_version=task.version,
            actor="medical_manager",
            idempotency_key=f"rollup-save-{field}",
        )

        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT task_id, rollup_json FROM monitoring_assurance_rollups"
            ).fetchone()
            assert row is not None
            rollup_payload = json.loads(row[1])
            rollup_payload[field] = value
            connection.execute(
                "UPDATE monitoring_assurance_rollups SET rollup_json = ? WHERE task_id = ?",
                (json.dumps(rollup_payload), row[0]),
            )

        with pytest.raises(AssuranceDriftError, match=message):
            repo.get_rollup(PROJECT, task.task_id)

    def test_persisted_rollup_row_project_binding_is_rejected_on_read(self, tmp_path):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_inspection",
            frozen_identity=FROZEN,
            idempotency_key="rollup-row-project",
            actor="medical_manager",
        ).task
        repo.save_rollup(
            project_id=PROJECT,
            task_id=task.task_id,
            rollup_payload={"risk_snapshot_id": FROZEN["risk_snapshot_id"]},
            expected_version=task.version,
            actor="medical_manager",
            idempotency_key="rollup-row-project-save",
        )

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_assurance_rollups SET project_id = ? WHERE task_id = ?",
                ("other-project", task.task_id),
            )

        with pytest.raises(AssuranceDriftError, match="identity does not match"):
            repo.get_rollup(PROJECT, task.task_id)

    def test_persisted_rollup_row_rejects_padded_project_identity(self, tmp_path):
        path = Path(tmp_path) / "assurance.sqlite3"
        repo = MonitoringAssuranceRepository(path)
        task = repo.create_task(
            project_id=PROJECT,
            mode="pre_inspection",
            frozen_identity=FROZEN,
            idempotency_key="rollup-row-project-padding",
            actor="medical_manager",
        ).task
        repo.save_rollup(
            project_id=PROJECT,
            task_id=task.task_id,
            rollup_payload={"risk_snapshot_id": FROZEN["risk_snapshot_id"]},
            expected_version=task.version,
            actor="medical_manager",
            idempotency_key="rollup-row-project-padding-save",
        )

        with sqlite3.connect(path) as connection:
            connection.execute(
                "UPDATE monitoring_assurance_rollups SET project_id = ? "
                "WHERE task_id = ?",
                (f" {PROJECT} ", task.task_id),
            )

        with pytest.raises(AssuranceDriftError, match="rollup project_id is invalid"):
            repo.get_rollup(PROJECT, task.task_id)

    def test_incomplete_recompute_blocks_completion(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        created = _create_task(client)
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        proof_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/full-recompute-proof",
            json={
                "expected_version": v,
                "idempotency_key": "proof-1",
                "actor": "medical_manager",
                "proof_payload": {
                    "planned_subjects": 10,
                    "actual_subjects": 10,
                    "planned_sites": 3,
                    "actual_sites": 3,
                    "critical_domains": ["AE", "LB", "CM"],
                    "planned_rules": 8,
                    "actual_rules": 8,
                    "per_domain_counts": [],
                    "failures": 1,
                    "skips": 0,
                    "retries": 0,
                    "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                    "owner": "owner-1",
                    "lock_impact": "no_impact",
                },
            },
        )
        assert proof_resp.status_code == 200
        v2 = proof_resp.json()["task"]["version"]

        review = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/medical-review",
            json={
                "expected_version": v2,
                "idempotency_key": "review-1",
                "review_payload": {"conclusion": "reviewed"},
            },
        )
        assert review.status_code == 200
        v3 = review.json()["task"]["version"]

        complete = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/complete",
            json={
                "expected_version": v3,
                "idempotency_key": "complete-1",
                "confirmed_by": "medical_manager",
            },
        )
        assert complete.status_code == 409

    def test_recompute_proof_idempotent_replay(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        created = _create_task(client)
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        body = {
            "expected_version": v,
            "idempotency_key": "proof-replay",
            "actor": "medical_manager",
            "proof_payload": {
                "planned_subjects": 10,
                "actual_subjects": 10,
                "planned_sites": 3,
                "actual_sites": 3,
                "critical_domains": ["AE"],
                "planned_rules": 5,
                "actual_rules": 5,
                "per_domain_counts": [],
                "failures": 0,
                "skips": 0,
                "retries": 0,
                "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                "owner": "owner-1",
                "lock_impact": "no_impact",
            },
        }
        first = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/full-recompute-proof",
            json=body,
        )
        assert first.status_code == 200
        assert first.json()["replayed"] is False
        assert first.json()["proof"]["provenance_status"] == "mixed_provenance"

        read_back = client.get(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/full-recompute-proof"
        )
        assert read_back.status_code == 200
        assert read_back.json()["proof"]["provenance_status"] == "mixed_provenance"

        # For idempotent replay, send the exact same body (same expected_version).
        # The idempotency layer should short-circuit before the version CAS check.
        replay = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/full-recompute-proof",
            json=body,
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True


# ---------------------------------------------------------------------------
# Three-level reconciliation
# ---------------------------------------------------------------------------


class TestThreeLevelReconciliation:
    def test_exact_instance_set_reconciliation(self, tmp_path):
        risks = [
            _risk(risk_instance_id="ri-1", subject_id="S001", site_id="A"),
            _risk(risk_instance_id="ri-2", subject_id="S001", site_id="A"),
            _risk(risk_instance_id="ri-3", subject_id="S002", site_id="B"),
            _risk(risk_instance_id="ri-4", subject_id="S002", site_id="B"),
            _risk(risk_instance_id="ri-5", subject_id="S003", site_id="A"),
        ]
        client, _, _ = _make_client(tmp_path, risks)
        created = _create_task(client, mode="pre_inspection")
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/rollups",
            json={
                "expected_version": v,
                "idempotency_key": "rollup-1",
                "site_method_approved": False,
            },
        )
        assert resp.status_code == 200, resp.text
        trial = resp.json()["rollup"]["trial_rollup"]
        assert trial["total_risk_count"] == 5

        subject_ids = set()
        for item in resp.json()["rollup"]["subject_rollup"]:
            subject_ids.update(item["risk_instance_ids"])
        assert subject_ids == {"ri-1", "ri-2", "ri-3", "ri-4", "ri-5"}

        site_ids = set()
        for item in resp.json()["rollup"]["site_rollup"]:
            site_ids.update(item["risk_instance_ids"])
        assert site_ids == {"ri-1", "ri-2", "ri-3", "ri-4", "ri-5"}


# ---------------------------------------------------------------------------
# Site clustering descriptive-only
# ---------------------------------------------------------------------------


class TestSiteClusteringDescriptive:
    def test_no_method_approved_is_descriptive_only(self, tmp_path):
        risks = [_risk(subject_id=f"S{i:03d}", site_id="A") for i in range(5)]
        client, _, _ = _make_client(tmp_path, risks)
        created = _create_task(client, mode="pre_inspection")
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/rollups",
            json={
                "expected_version": v,
                "idempotency_key": "rollup-1",
                "site_method_approved": False,
            },
        )
        assert resp.status_code == 200
        for site in resp.json()["rollup"]["site_rollup"]:
            cluster = site.get("cluster", {})
            assert cluster.get("signal_status") == "descriptive_only"
            assert cluster.get("method_identity") == "no_project_method"

    def test_small_sample_is_descriptive_only(self, tmp_path):
        risks = [_risk(subject_id=f"S{i:03d}", site_id="A") for i in range(3)]
        client, _, _ = _make_client(tmp_path, risks)
        created = _create_task(client, mode="pre_inspection")
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/rollups",
            json={
                "expected_version": v,
                "idempotency_key": "rollup-1",
                "site_method_approved": True,
                "min_sample_size": 30,
            },
        )
        assert resp.status_code == 200
        for site in resp.json()["rollup"]["site_rollup"]:
            cluster = site.get("cluster", {})
            assert cluster.get("signal_status") == "descriptive_only"
            assert cluster.get("sample_adequate") is False


# ---------------------------------------------------------------------------
# Safety/PV and CM vs study-treatment
# ---------------------------------------------------------------------------


class TestSafetyPVAndCMvsStudyTreatment:
    def test_safety_pv_and_cm_distinct_from_study_treatment(self, tmp_path):
        risks = [
            _risk(risk_instance_id="pv-1", is_safety_pv=True, primary_category="SAE一致性"),
            _risk(risk_instance_id="cm-1", is_concomitant_medication=True, primary_category="禁限用药"),
            _risk(risk_instance_id="st-1", is_study_treatment=True, primary_category="试验药物变更"),
            _risk(
                risk_instance_id="cm-st",
                is_concomitant_medication=True,
                is_study_treatment=True,
                primary_category="混合",
            ),
        ]
        client, _, _ = _make_client(tmp_path, risks)
        created = _create_task(client, mode="pre_inspection")
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/rollups",
            json={"expected_version": v, "idempotency_key": "rollup-1"},
        )
        assert resp.status_code == 200
        dist = resp.json()["rollup"]["distributions"]
        assert dist["safety_pv"]["count"] == 1
        assert dist["safety_pv"]["is_additional_dimension"] is True

        cm_st = dist["concomitant_medication_vs_study_treatment"]
        assert cm_st["cm_risk_count"] == 1
        assert cm_st["study_treatment_risk_count"] == 2
        assert cm_st["distinct"] is True


# ---------------------------------------------------------------------------
# Real MedicalRiskRepository adapter
# ---------------------------------------------------------------------------


class TestRealMedicalRiskRepositoryAdapter:
    def test_pinned_snapshot_rollup_uses_minimal_references(self, tmp_path):
        client, risk_repository, snapshot = _make_real_repository_client(tmp_path)
        reader = create_medical_risk_reference_reader(risk_repository)
        references = reader(PROJECT, snapshot.snapshot_id)

        assert len(references) == 3
        assert not hasattr(references[0], "title")
        assert not hasattr(references[0], "rationale")
        assert sum(item.is_concomitant_medication for item in references) == 1
        assert sum(item.is_study_treatment for item in references) == 1
        assert all(
            not (
                item.is_concomitant_medication
                and item.is_study_treatment
            )
            for item in references
        )

        frozen_identity = {
            **FROZEN,
            "batch_id": "batch-real-1",
            "batch_revision": "source-real-1",
            "rule_pack_revision": "rules-real-1",
            "risk_snapshot_id": snapshot.snapshot_id,
        }
        pre_lock = _create_task(
            client,
            mode="pre_lock",
            frozen_identity=frozen_identity,
            idempotency_key="create-real-prelock",
        )
        proof = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/"
            f"{pre_lock['task']['task_id']}/full-recompute-proof",
            json={
                "expected_version": pre_lock["task"]["version"],
                "idempotency_key": "real-proof-1",
                "proof_payload": {
                    "planned_subjects": 2,
                    "actual_subjects": 2,
                    "planned_sites": 2,
                    "actual_sites": 2,
                    "critical_domains": ["CM", "EX", "LB"],
                    "planned_rules": 3,
                    "actual_rules": 3,
                    "per_domain_counts": [],
                    "failures": 0,
                    "skips": 0,
                    "retries": 0,
                    "pinned_risk_snapshot_id": snapshot.snapshot_id,
                    "owner": "owner-1",
                    "lock_impact": "no_impact",
                },
            },
        )
        assert proof.status_code == 200, proof.text
        assert proof.json()["proof"]["open_risk_count"] == 3
        assert proof.json()["proof"]["open_high_risk_count"] == 3
        assert proof.json()["proof"]["subject_reconciliation_ok"] is True
        assert proof.json()["proof"]["site_reconciliation_ok"] is True
        assert proof.json()["proof"]["trial_reconciliation_ok"] is True

        created = _create_task(
            client,
            mode="pre_inspection",
            frozen_identity=frozen_identity,
            idempotency_key="create-real-preinspection",
        )
        response = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/"
            f"{created['task']['task_id']}/rollups",
            json={
                "expected_version": created["task"]["version"],
                "idempotency_key": "real-rollup-1",
                "site_method_approved": False,
            },
        )

        assert response.status_code == 200, response.text
        rollup = response.json()["rollup"]
        expected_ids = {"risk-cm-1", "risk-study-1", "risk-pv-1"}
        assert set(rollup["trial_rollup"]["risk_instance_ids"]) == expected_ids
        assert {
            risk_id
            for item in rollup["subject_rollup"]
            for risk_id in item["risk_instance_ids"]
        } == expected_ids
        assert {
            risk_id
            for item in rollup["site_rollup"]
            for risk_id in item["risk_instance_ids"]
        } == expected_ids
        assert all(
            item["cluster"]["signal_status"] == "descriptive_only"
            for item in rollup["site_rollup"]
        )
        assert rollup["distributions"]["safety_pv"]["count"] == 1
        cm_st = rollup["distributions"][
            "concomitant_medication_vs_study_treatment"
        ]
        assert cm_st == {
            "cm_risk_count": 1,
            "study_treatment_risk_count": 1,
            "distinct": True,
        }

    def test_cross_project_and_snapshot_drift_fail_closed(self, tmp_path):
        client, risk_repository, snapshot = _make_real_repository_client(tmp_path)
        reader = create_medical_risk_reference_reader(risk_repository)

        with pytest.raises(AssuranceDriftError):
            reader("other-project", snapshot.snapshot_id)

        frozen_identity = {
            **FROZEN,
            "batch_id": "batch-real-1",
            "batch_revision": "source-real-1",
            "rule_pack_revision": "rules-real-1",
            "risk_snapshot_id": snapshot.snapshot_id,
        }
        created = _create_task(
            client,
            mode="pre_inspection",
            frozen_identity=frozen_identity,
        )
        risk_repository.save_snapshot(
            project_id=PROJECT,
            source_batch_id="batch-real-2",
            source_revision="source-real-2",
            rule_profile_revision="rules-real-1",
            engine_version="engine-real-1",
            evaluated_subject_count=2,
            risks=[],
        )

        drift = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/"
            f"{created['task']['task_id']}/rollups",
            json={
                "expected_version": created["task"]["version"],
                "idempotency_key": "real-rollup-drift",
            },
        )
        assert drift.status_code == 409
        assert drift.json()["detail"]["code"] == "assurance_drift_detected"

        cross_project = client.get(
            f"/api/projects/other-project/monitoring/assurance/tasks/"
            f"{created['task']['task_id']}"
        )
        assert cross_project.status_code == 404


# ---------------------------------------------------------------------------
# Extra forbid
# ---------------------------------------------------------------------------


class TestExtraForbid:
    def test_extra_field_forbidden(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        response = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks",
            json={
                "mode": "pre_lock",
                "frozen_identity": dict(FROZEN),
                "idempotency_key": "create-1",
                "actor": "medical_manager",
                "unexpected_field": "should_fail",
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Public response redaction
# ---------------------------------------------------------------------------


class TestPublicRedaction:
    def test_no_local_paths_in_response(self, tmp_path):
        client, _, _ = _make_client(tmp_path)
        created = _create_task(client)
        response_text = str(created)
        assert "/Users/" not in response_text
        assert "blob_relative_path" not in response_text


# ---------------------------------------------------------------------------
# Pre-inspection full lifecycle
# ---------------------------------------------------------------------------


class TestPreInspectionCompletion:
    def test_pre_inspection_completes_after_rollup_and_review(self, tmp_path):
        risks = [
            _risk(
                risk_instance_id="ri-1",
                subject_id="S001",
                site_id="A",
                closure_evidence_present=True,
            ),
            _risk(
                risk_instance_id="ri-2",
                subject_id="S002",
                site_id="A",
                status="resolved",
                closure_evidence_present=True,
            ),
        ]
        client, _, _ = _make_client(tmp_path, risks)
        created = _create_task(client, mode="pre_inspection")
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        rollup_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/rollups",
            json={"expected_version": v, "idempotency_key": "rollup-1"},
        )
        assert rollup_resp.status_code == 200
        v2 = rollup_resp.json()["task"]["version"]

        review_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/medical-review",
            json={
                "expected_version": v2,
                "idempotency_key": "review-1",
                "review_payload": {"conclusion": "ok"},
            },
        )
        assert review_resp.status_code == 200
        v3 = review_resp.json()["task"]["version"]

        complete_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/complete",
            json={
                "expected_version": v3,
                "idempotency_key": "complete-1",
                "confirmed_by": "medical_manager",
            },
        )
        assert complete_resp.status_code == 200
        assert complete_resp.json()["task"]["status"] == "completed"

    def test_pre_inspection_completion_rejects_persisted_rollup_identity_drift(
        self, tmp_path
    ):
        risks = [
            _risk(
                risk_instance_id="ri-1",
                subject_id="S001",
                site_id="SITE-A",
                closure_evidence_present=True,
            ),
            _risk(
                risk_instance_id="ri-2",
                subject_id="S002",
                site_id="SITE-B",
                closure_evidence_present=True,
            ),
        ]
        client, _, service = _make_client(tmp_path, risks)
        created = _create_task(client, mode="pre_inspection")
        task_id = created["task"]["task_id"]

        rollup_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/rollups",
            json={
                "expected_version": created["task"]["version"],
                "idempotency_key": "rollup-drift-1",
            },
        )
        assert rollup_resp.status_code == 200
        rollup_payload = rollup_resp.json()["rollup"]
        assert validate_pre_inspection_rollup(
            service.get_task(PROJECT, task_id), rollup_payload
        ) == ()

        review_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/medical-review",
            json={
                "expected_version": rollup_resp.json()["task"]["version"],
                "idempotency_key": "review-drift-1",
                "review_payload": {"conclusion": "ok"},
            },
        )
        assert review_resp.status_code == 200

        tampered = json.loads(json.dumps(rollup_payload))
        tampered["site_rollup"][0]["risk_instance_ids"] = []
        with sqlite3.connect(Path(tmp_path) / "assurance.sqlite3") as connection:
            connection.execute(
                "UPDATE monitoring_assurance_rollups SET rollup_json = ? WHERE task_id = ?",
                (json.dumps(tampered), task_id),
            )
            connection.commit()

        complete_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/complete",
            json={
                "expected_version": review_resp.json()["task"]["version"],
                "idempotency_key": "complete-drift-1",
                "confirmed_by": "medical_manager",
            },
        )
        assert complete_resp.status_code == 409
        assert complete_resp.json()["detail"]["code"] == "assurance_drift_detected"
        assert "content hash mismatch" in complete_resp.json()["detail"]["message"]


# ---------------------------------------------------------------------------
# Closed risks lacking evidence
# ---------------------------------------------------------------------------


class TestClosedRisksLackingEvidence:
    def test_closed_risk_without_evidence_blocks_pre_lock_completion(self, tmp_path):
        risks = [
            _risk(
                risk_instance_id="ri-c1",
                status="resolved",
                closure_evidence_present=False,
            ),
        ]
        client, _, _ = _make_client(tmp_path, risks)
        created = _create_task(client, mode="pre_lock")
        task_id = created["task"]["task_id"]
        v = created["task"]["version"]

        proof_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/full-recompute-proof",
            json={
                "expected_version": v,
                "idempotency_key": "proof-1",
                "proof_payload": {
                    "planned_subjects": 1,
                    "actual_subjects": 1,
                    "planned_sites": 1,
                    "actual_sites": 1,
                    "critical_domains": ["AE"],
                    "planned_rules": 1,
                    "actual_rules": 1,
                    "per_domain_counts": [],
                    "failures": 0,
                    "skips": 0,
                    "retries": 0,
                    "pinned_risk_snapshot_id": FROZEN["risk_snapshot_id"],
                    "owner": "owner-1",
                    "lock_impact": "no_impact",
                },
            },
        )
        assert proof_resp.status_code == 200
        v2 = proof_resp.json()["task"]["version"]

        review_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/medical-review",
            json={
                "expected_version": v2,
                "idempotency_key": "review-1",
                "review_payload": {"conclusion": "ok"},
            },
        )
        assert review_resp.status_code == 200
        v3 = review_resp.json()["task"]["version"]

        complete_resp = client.post(
            f"/api/projects/{PROJECT}/monitoring/assurance/tasks/{task_id}/complete",
            json={
                "expected_version": v3,
                "idempotency_key": "complete-1",
                "confirmed_by": "medical_manager",
            },
        )
        assert complete_resp.status_code == 409
        assert "evidence" in complete_resp.json()["detail"]["message"].lower()
