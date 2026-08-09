from __future__ import annotations

from dataclasses import dataclass, replace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.monitoring_batch_repository import CompletenessGateError
from services.api.app.monitoring_metric_configuration_router import (
    create_monitoring_metric_configuration_router,
)
from services.api.app.monitoring_metric_configuration_service import (
    MonitoringMetricConfigurationError,
    MonitoringMetricConfigurationService,
)
from tests.test_monitoring_metric_configuration import (
    PROJECT,
    VERSION,
    _fact,
    _profile,
)
from tests.test_monitoring_protocol_rules import _version


@dataclass(frozen=True)
class _Batch:
    batch_id: str = "batch-001"
    project_id: str = PROJECT
    state: str = "frozen"


class _ProtocolRepository:
    def __init__(self, *facts):
        self.version = replace(
            _version(PROJECT, "V1.0", "2026-01-01"),
            protocol_version_id=VERSION,
        )
        self.facts = tuple(facts)

    def protocol_version(self, protocol_version_id):
        if protocol_version_id != VERSION:
            from services.api.app.monitoring_protocol_rule_repository import (
                MonitoringProtocolRecordNotFound,
            )

            raise MonitoringProtocolRecordNotFound("protocol version not found")
        return self.version

    def facts_for_version(self, protocol_version_id):
        assert protocol_version_id == VERSION
        return self.facts


class _BatchRepository:
    def __init__(self, batch: _Batch):
        self.batch = batch

    def get_batch(self, batch_id):
        if batch_id != self.batch.batch_id:
            from services.api.app.monitoring_batch_repository import (
                MonitoringBatchRepositoryError,
            )

            raise MonitoringBatchRepositoryError("batch not found")
        return self.batch


class _Profiler:
    def __init__(self, *, fail=False):
        self.fail = fail

    def profile_frozen_batch(self, batch_id):
        assert batch_id == "batch-001"
        if self.fail:
            raise CompletenessGateError("batch is not frozen")
        return _profile()


def _service(*, batch: _Batch = _Batch(), profiler: _Profiler | None = None):
    return MonitoringMetricConfigurationService(
        protocol_repository=_ProtocolRepository(
            _fact(),
            _fact(status="ai_candidate", key="efficacy.ai"),
        ),
        batch_repository=_BatchRepository(batch),
        profiler=profiler or _Profiler(),
    )


def test_service_returns_candidate_only_bundle_and_keeps_unconfirmed_gap_visible():
    bundle = _service().build(
        project_id=PROJECT,
        protocol_version_id=VERSION,
        batch_id="batch-001",
    )

    assert bundle.status == "candidate_only"
    assert bundle.medically_confirmed is False
    assert bundle.usable_candidate_count == 1
    assert any(item.code.value == "unconfirmed_protocol_fact" for item in bundle.issues)


def test_service_fails_closed_on_project_batch_mismatch_and_unfrozen_profile():
    try:
        _service(batch=_Batch(project_id="other-project")).build(
            project_id=PROJECT,
            protocol_version_id=VERSION,
            batch_id="batch-001",
        )
    except MonitoringMetricConfigurationError as exc:
        assert exc.code == "monitoring_metric_batch_not_found"
        assert exc.http_status == 404
    else:
        raise AssertionError("project mismatch must be rejected")

    try:
        _service(profiler=_Profiler(fail=True)).build(
            project_id=PROJECT,
            protocol_version_id=VERSION,
            batch_id="batch-001",
        )
    except MonitoringMetricConfigurationError as exc:
        assert exc.code == "monitoring_metric_batch_not_frozen"
        assert exc.http_status == 409
    else:
        raise AssertionError("unfrozen batch must be rejected")


def test_router_exposes_review_metadata_without_confirmation_or_write_route():
    app = FastAPI()
    app.include_router(
        create_monitoring_metric_configuration_router(
            service=_service(),
            project_resolver=lambda value: PROJECT if value == "alias" else value,
            require_server_principal=False,
        )
    )
    response = TestClient(app).get(
        f"/api/projects/alias/modules/medical-monitoring/metric-configuration/"
        f"protocol-versions/{VERSION}/candidates",
        params={"batch_id": "batch-001"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "candidate_only"
    assert payload["medically_confirmed"] is False
    assert payload["review"] == {
        "candidate_only": True,
        "requires_medical_confirmation": True,
        "issue_count": 1,
    }
    assert payload["candidates"][0]["status"] == "pending_medical_confirmation"


def test_router_maps_service_errors_to_stable_http_detail():
    app = FastAPI()
    app.include_router(
        create_monitoring_metric_configuration_router(
            service=_service(profiler=_Profiler(fail=True)),
            require_server_principal=False,
        )
    )
    response = TestClient(app).get(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/metric-configuration/"
        f"protocol-versions/{VERSION}/candidates",
        params={"batch_id": "batch-001"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "monitoring_metric_batch_not_frozen",
        "message": "只有完整冻结的 listing 批次可以生成指标候选。",
    }


def test_router_fails_closed_without_server_verified_principal():
    app = FastAPI()
    app.include_router(
        create_monitoring_metric_configuration_router(
            service=_service(),
            principal_resolver=lambda request: None,
        )
    )
    response = TestClient(app).get(
        f"/api/projects/{PROJECT}/modules/medical-monitoring/metric-configuration/"
        f"protocol-versions/{VERSION}/candidates",
        params={"batch_id": "batch-001"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "monitoring_principal_unavailable",
        "message": "服务器未提供有效验证身份，指标候选读取已阻断。",
    }
