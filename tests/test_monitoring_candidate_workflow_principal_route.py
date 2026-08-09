from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_protocol_preparation_router import (
    create_monitoring_protocol_preparation_router,
)
from services.api.app.monitoring_rule_template_recommendation_router import (
    create_monitoring_rule_template_recommendation_router,
)
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
)


PROJECT = "candidate-route-project"
VERSION = "protocol-v1"
FACT = "fact-revision-1"


class _ProtocolService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def start(self, **kwargs):
        self.calls.append(("start", kwargs))
        return {"status": "queued"}

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return {"status": "ready"}

    def decide_candidate(self, **kwargs):
        self.calls.append(("decide", kwargs))
        return {"status": "user_rejected", "actor": kwargs["actor"]}


class _RuleTemplateService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def start(self, **kwargs):
        self.calls.append(("start", kwargs))
        return {"status": "queued"}

    def status(self, **kwargs):
        self.calls.append(("status", kwargs))
        return {"status": "ready"}

    def decide(self, **kwargs):
        self.calls.append(("decide", kwargs))
        return {"status": "user_rejected", "actor": kwargs["actor"]}


def _principal() -> MonitoringAuthenticatedPrincipal:
    return MonitoringAuthenticatedPrincipal(
        principal_id="verified-medical-manager",
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


def _protocol_client(service, *, resolver=None):
    app = FastAPI()
    app.include_router(
        create_monitoring_protocol_preparation_router(
            service=service,
            principal_resolver=resolver,
        )
    )
    return TestClient(app)


def _rule_client(service, *, resolver=None):
    app = FastAPI()
    app.include_router(
        create_monitoring_rule_template_recommendation_router(
            service=service,
            principal_resolver=resolver,
        )
    )
    return TestClient(app)


def test_protocol_preparation_production_default_blocks_before_service_access():
    service = _ProtocolService()
    response = _protocol_client(service).get(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/"
        f"protocol-preparation/protocol-versions/{VERSION}/status"
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
    assert service.calls == []


def test_protocol_preparation_uses_server_actor_for_candidate_decision():
    service = _ProtocolService()
    client = _protocol_client(service, resolver=lambda _request: _principal())
    response = client.post(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/"
        f"protocol-preparation/protocol-versions/{VERSION}/candidates/candidate-1/decision",
        json={
            "decision": "rejected",
            "actor": "client-spoof",
            "reason": "需补充证据。",
            "expected_input_revision_sha256": "b" * 64,
            "expected_source_revision": "source-rev-1",
        },
    )

    assert response.status_code == 200
    assert response.json()["actor"] == "verified-medical-manager"
    assert service.calls[-1][1]["actor"] == "verified-medical-manager"


def test_rule_template_production_default_blocks_before_service_access():
    service = _RuleTemplateService()
    response = _rule_client(service).post(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/"
        f"rule-template-recommendations/facts/{FACT}/start",
        json={"expected_fact_state_version": 1},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
    assert service.calls == []


def test_rule_template_uses_server_actor_for_candidate_decision():
    service = _RuleTemplateService()
    client = _rule_client(service, resolver=lambda _request: _principal())
    response = client.post(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/"
        f"rule-template-recommendations/facts/{FACT}/candidates/candidate-1/decision",
        json={
            "decision": "rejected",
            "actor": "client-spoof",
            "reason": "不采纳。",
            "expected_input_revision_sha256": "c" * 64,
            "expected_fact_state_version": 1,
        },
    )

    assert response.status_code == 200
    assert response.json()["actor"] == "verified-medical-manager"
    assert service.calls[-1][1]["actor"] == "verified-medical-manager"

