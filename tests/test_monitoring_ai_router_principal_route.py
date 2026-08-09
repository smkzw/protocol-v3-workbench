from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.monitoring_ai_contracts import MonitoringAiTaskType
from services.api.app.monitoring_ai_repository import MonitoringAiStateConflictError
from services.api.app.monitoring_ai_router import create_monitoring_ai_router
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
)


PROJECT = "ai-router-principal-project"


class _Repository:
    def __init__(self) -> None:
        self.decide_actor = ""
        self.read_calls = 0

    def list_jobs(self, *args, **kwargs):
        self.read_calls += 1
        return ()

    def job_for_candidate(self, project_id: str, candidate_id: str):
        return SimpleNamespace(
            job_id="job-1",
            task_type=MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
            input_revision_sha256="a" * 64,
        )

    def candidates(self, project_id: str, job_id: str):
        return ()

    def decide_candidate(self, project_id: str, candidate_id: str, **kwargs):
        self.decide_actor = kwargs["actor"]
        raise MonitoringAiStateConflictError("test capture")


def _principal() -> MonitoringAuthenticatedPrincipal:
    return MonitoringAuthenticatedPrincipal(
        principal_id="verified-ai-medical-manager",
        tenant_id="tenant-kangzhe",
        roles=(MonitoringRole.MEDICAL_MANAGER,),
        project_scope=(PROJECT,),
        issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        authenticated=True,
        authn_method="test-server-session",
        session_id="server-session-secret",
        directory_revision="directory-test-v1",
        verification_ref_sha256="a" * 64,
    )


def _client(repository, *, resolver=None, wake=None):
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=object(),
            batch_repository=object(),
            worker_wake=wake or (lambda: None),
            principal_resolver=resolver,
        )
    )
    return TestClient(app)


def test_ai_route_blocks_without_principal_before_repository_access():
    repository = _Repository()
    client = _client(repository)
    response = client.get(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/ai/jobs"
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
    assert repository.read_calls == 0


def test_ai_candidate_decision_uses_server_actor_not_client_actor():
    repository = _Repository()
    client = _client(repository, resolver=lambda _request: _principal())
    response = client.post(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/ai/"
        "candidates/candidate-1/decision",
        json={
            "decision": "rejected",
            "actor": "client-spoof",
            "reason": "不采纳。",
        },
    )

    assert response.status_code == 409
    assert repository.decide_actor == "verified-ai-medical-manager"

