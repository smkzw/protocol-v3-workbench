from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from packages.contracts.workbench_contracts import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
    WorkbenchInboxActionRecord,
    WorkbenchItemAction,
)
from services.api.app.medical_monitoring_router import (
    create_medical_monitoring_router,
)
from services.api.app.medical_monitoring_summary import MedicalMonitoringSummaryService
from services.api.app.medical_risk_repository import MedicalRiskRepository
from services.api.app.monitoring_project_registry import BoundMonitoringProjectAdapter
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
)
from services.api.app.workbench_inbox import (
    WorkbenchInboxStore,
    _monitoring_source_version,
)


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)
PROJECT_ID = "proj_test"
SOURCE_REVISION = "monsrcv_test_001"


class FakeManifestService:
    def __init__(self, implementation_status: str = "available") -> None:
        self.implementation_status = implementation_status

    def canonical_project_id(self, project_id: str) -> str:
        if project_id in {PROJECT_ID, "project-alias"}:
            return PROJECT_ID
        raise KeyError(project_id)

    def module_binding(self, project_id: str, module: str):
        if project_id != PROJECT_ID or module != "medical_monitoring":
            raise KeyError((project_id, module))
        return SimpleNamespace(
            route_project_id=PROJECT_ID,
            implementation_status=self.implementation_status,
            primary_source_ids=["src_listing"],
            supplemental_source_ids=["src_protocol"],
            display_batch_label="2026-07-29 EDC Listing",
            display_extract_date="2026-07-29",
        )


class FakeRegistry:
    def __init__(self) -> None:
        self.adapter = FakeAdapter()

    def has(self, project_id: str) -> bool:
        return project_id == PROJECT_ID

    def get(self, project_id: str):
        if project_id != PROJECT_ID:
            raise KeyError(project_id)
        return self.adapter


class FakeBatchRepository:
    def __init__(self, projects: dict[str, str] | None = None) -> None:
        self.projects = projects or {
            "batch_previous": PROJECT_ID,
            "batch_current": PROJECT_ID,
        }

    def get_batch(self, batch_id: str):
        project_id = self.projects[batch_id]
        return SimpleNamespace(batch_id=batch_id, project_id=project_id)


class FakeBatchService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def detailed_diff(self, previous_batch_id: str, current_batch_id: str):
        self.calls.append((previous_batch_id, current_batch_id))
        return {
            "previous_batch_id": previous_batch_id,
            "current_batch_id": current_batch_id,
            "row_diff": {
                "new_keys": ["AE|S001|2"],
                "changed_keys": ["LB|S001|1"],
                "persisting_keys": ["AE|S001|1"],
                "removed_keys": [],
                "requires_rereview_keys": [],
                "missing_current_domains": [],
                "removal_resolution_blocked_keys": [],
            },
            "field_changes": [
                {"business_key": "LB|S001|1", "field_name": "LBORRES", "current_value": "2"},
                {"business_key": "LB|S001|1", "field_name": "LBSTRESC", "current_value": "high"},
            ],
            "schema_diffs": [],
            "identity_match_counts": {},
            "identity_match_samples": [],
            "removal_eligible_keys": [],
            "removal_blocked_keys": [],
            "full_snapshot_proven": True,
            "algorithm_version": "monitoring_batch_diff.v3",
            "output_sha256": "a" * 64,
        }


class FakeAdapter:
    def subject_ids(self) -> list[str]:
        return ["S001", "S002"]

    def subject_catalog(self) -> dict:
        return {
            "project_id": PROJECT_ID,
            "source_revision": SOURCE_REVISION,
            "subjects": [
                {"id": "S001", "site": "01"},
                {"id": "S002", "site": "02"},
            ],
        }

    def source_revision(self) -> str:
        return SOURCE_REVISION

    def risk_profile_revision(self) -> str:
        return "rules_v1"

    def risk_engine_version(self) -> str:
        return "engine_v1"

    def risk_resolution_complete(self) -> bool:
        return False

    def resolve_source_fragment(self, locator: str) -> dict:
        return {
            "source_type": "listing",
            "locator_kind": "row",
            "display_locator": locator,
            "primary_summary": f"冻结事实：{locator}",
            "text": f"原始记录 {locator}",
            "fields": [{"field": "原始值", "value": locator}],
        }

    def evaluate_subject_risks(self, subject_id: str) -> list[RiskCase]:
        suffix = subject_id.removeprefix("S")
        return [
            _risk(
                suffix,
                severity=RiskSeverity.HIGH if subject_id == "S001" else RiskSeverity.MEDIUM,
                status=RiskStatus.ACTION_REQUIRED if subject_id == "S001" else RiskStatus.NEW,
            )
        ]


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    (
        (True, True),
        (False, False),
        ("false", False),
        (1, False),
        (None, False),
    ),
)
def test_bound_adapter_risk_resolution_requires_literal_boolean(
    raw_value: object,
    expected: bool,
) -> None:
    service = SimpleNamespace(
        risk_resolution_complete=lambda: raw_value,
    )
    adapter = BoundMonitoringProjectAdapter(PROJECT_ID, service)

    assert adapter.risk_resolution_complete() is expected


class FakeProjectionInbox:
    def monitoring_query_workflow_policy(self, project_id: str):
        assert project_id == PROJECT_ID
        return {
            "internal_approval_required": False,
            "formal_send_managed_outside_monitoring": True,
        }

    def monitoring_risk_items(self, project_id: str, actor: str = "medical_manager"):
        assert project_id == PROJECT_ID
        assert actor == "medical_manager"
        return [
            SimpleNamespace(
                item_id="monitoring-risk:riskinst_001",
                source_id="legacy_001",
                risk_instance_id="riskinst_001",
                status="已说明，无需外部动作",
                unread=False,
                needs_action=False,
                action_label="查看医学处置记录",
                source_version="monitoring:source-v1",
                source_refs=[],
                disposition_kind=None,
                medical_judgments=None,
                updated_at=NOW,
            )
        ]


def _risk(
    suffix: str,
    *,
    severity: RiskSeverity,
    status: RiskStatus,
    primary_category: str = "ae_mh_temporal_or_classification_review",
    title: str | None = None,
    subject_id: str | None = None,
    site_id: str = "01",
    created_at: datetime = NOW,
    source_revision: str = SOURCE_REVISION,
) -> RiskCase:
    resolved_subject_id = subject_id or f"S{suffix}"
    return RiskCase(
        risk_id=f"legacy_{suffix}",
        risk_key=f"riskkey_{suffix}",
        risk_instance_id=f"riskinst_{suffix}",
        project_id=PROJECT_ID,
        module="medical_monitoring",
        risk_type="AE/MH漏报",
        primary_category=primary_category,
        title=title or f"风险 {suffix}",
        subject_id=resolved_subject_id,
        site_id=site_id,
        severity=severity,
        status=status,
        source_batch_id="batch_001",
        source_revision=source_revision,
        rule_profile_revision="rules_v1",
        engine_version="engine_v1",
        batch_delta="unclassified",
        rule_id=f"RULE_{suffix}",
        evidence_span_ids=[f"listing:AE:row:{suffix}"],
        rationale="原始数据存在需医学复核的不一致。",
        recommended_action="核对原始记录。",
        created_at=created_at,
    )


def _app(
    repository,
    inbox_service=None,
    *,
    batch_repository=None,
    batch_service=None,
    principal_resolver=None,
    require_server_principal=False,
    monitoring_implementation_status="available",
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_medical_monitoring_router(
            risk_repository=repository,
            batch_repository=batch_repository,
            batch_service=batch_service,
            project_source_manifest_service=FakeManifestService(
                monitoring_implementation_status
            ),
            workbench_inbox_service=inbox_service,
            monitoring_registry=FakeRegistry(),
            principal_resolver=principal_resolver,
            require_server_principal=require_server_principal,
        )
    )
    return TestClient(app)


def _monitoring_principal(
    *,
    project_scope: tuple[str, ...] = (PROJECT_ID,),
    roles: tuple[MonitoringRole, ...] = (MonitoringRole.MEDICAL_MANAGER,),
):
    return MonitoringAuthenticatedPrincipal(
        principal_id="medical_manager",
        tenant_id="tenant-kangzhe",
        roles=roles,
        project_scope=project_scope,
        issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        authenticated=True,
        authn_method="test-server-session",
        session_id="server-session-secret",
        directory_revision="directory-test-v1",
        verification_ref_sha256="e" * 64,
    )


def _database_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _row_counts(path: Path) -> tuple[int, int]:
    with sqlite3.connect(path) as connection:
        snapshots = connection.execute(
            "SELECT COUNT(*) FROM medical_risk_snapshots"
        ).fetchone()[0]
        risks = connection.execute(
            "SELECT COUNT(*) FROM medical_risk_instances"
        ).fetchone()[0]
    return snapshots, risks


@pytest.mark.parametrize(
    "suffix",
    (
        "summary",
        "deep-link",
        "risk-snapshots/current",
        "risk-snapshots/current/export",
        "risk-taxonomy",
    ),
)
def test_primary_monitoring_reads_require_server_principal(
    suffix: str,
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository, require_server_principal=True)
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}"
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
        assert "读取" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    "suffix",
    (
        "summary",
        "deep-link",
        "risk-snapshots/current",
        "risk-snapshots/current/export",
        "risk-taxonomy",
    ),
)
def test_primary_monitoring_reads_require_monitoring_role(
    suffix: str,
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(
                roles=(MonitoringRole.SYSTEM_ADMIN,)
            ),
        )
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}"
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "monitoring_role_not_permitted"


def test_scoped_medical_manager_can_read_primary_summary_and_taxonomy() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(),
        )
        summary = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/summary",
            params={"actor": "payload-spoof"},
        )
        taxonomy = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-taxonomy"
        )
        assert summary.status_code == 200, summary.text
        assert summary.json()["project_id"] == PROJECT_ID
        assert taxonomy.status_code == 200, taxonomy.text
        assert taxonomy.json()["project_id"] == PROJECT_ID


def test_canonical_batch_diff_requires_server_principal_before_batch_lookup() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        batch_repository = FakeBatchRepository()
        batch_service = FakeBatchService()
        client = _app(
            repository,
            batch_repository=batch_repository,
            batch_service=batch_service,
            require_server_principal=True,
        )
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/batch-diff",
            params={
                "previous_batch_id": "batch_previous",
                "current_batch_id": "batch_current",
            },
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
        assert batch_service.calls == []


def test_canonical_batch_diff_is_server_scoped_and_paginates_field_changes() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        batch_repository = FakeBatchRepository()
        batch_service = FakeBatchService()
        client = _app(
            repository,
            batch_repository=batch_repository,
            batch_service=batch_service,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(),
        )
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/batch-diff",
            params={
                "previous_batch_id": "batch_previous",
                "current_batch_id": "batch_current",
                "offset": 1,
                "limit": 1,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["project_id"] == PROJECT_ID
        assert payload["field_change_total"] == 2
        assert payload["field_changes"] == [
            {
                "business_key": "LB|S001|1",
                "field_name": "LBSTRESC",
                "current_value": "high",
            }
        ]
        assert payload["offset"] == 1
        assert payload["limit"] == 1
        assert batch_service.calls == [("batch_previous", "batch_current")]


def test_canonical_batch_diff_rejects_cross_project_batch_before_diff_service() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        batch_repository = FakeBatchRepository(
            {"batch_previous": PROJECT_ID, "batch_current": "other_project"}
        )
        batch_service = FakeBatchService()
        client = _app(
            repository,
            batch_repository=batch_repository,
            batch_service=batch_service,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(),
        )
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/batch-diff",
            params={
                "previous_batch_id": "batch_previous",
                "current_batch_id": "batch_current",
            },
        )
        assert response.status_code == 404, response.text
        assert response.json()["detail"]["code"] == "monitoring_batch_diff_not_found"
        assert batch_service.calls == []


def test_canonical_batch_diff_fails_closed_when_batch_service_is_not_injected() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            batch_repository=FakeBatchRepository(),
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(),
        )
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/batch-diff",
            params={
                "previous_batch_id": "batch_previous",
                "current_batch_id": "batch_current",
            },
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_batch_diff_unavailable"


def test_source_manifest_only_monitoring_module_is_blocked_after_authentication() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(),
            monitoring_implementation_status="source_manifest_only",
        )
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/summary"
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == (
            "medical_monitoring_source_not_activated"
        )
        assert response.json()["detail"]["readiness"]["can_start"] is False


def test_source_manifest_only_monitoring_run_is_blocked_before_registry_write() -> None:
    with TemporaryDirectory() as tmp:
        database = Path(tmp) / "medical_risks.sqlite3"
        repository = MedicalRiskRepository(database)
        client = _app(
            repository,
            require_server_principal=False,
            monitoring_implementation_status="source_manifest_only",
        )
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/runs"
        )
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == (
            "medical_monitoring_source_not_activated"
        )
        assert _row_counts(database) == (0, 0)


def test_primary_monitoring_read_rejects_project_scope_before_lookup() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(
                project_scope=("other-project",)
            ),
        )
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/summary"
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "monitoring_project_scope_denied"


def test_primary_monitoring_run_requires_server_principal_before_snapshot_write() -> None:
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "medical_risks.sqlite3"
        repository = MedicalRiskRepository(db_path)
        before_digest = _database_digest(db_path)
        client = _app(repository, require_server_principal=True)
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/runs"
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
        assert "写入" in response.json()["detail"]["message"]
        assert _database_digest(db_path) == before_digest


def test_primary_monitoring_run_requires_run_rules_permission() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(
                roles=(MonitoringRole.MEDICAL_WRITER,)
            ),
        )
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/runs"
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "monitoring_role_not_permitted"


@pytest.mark.parametrize(
    ("suffix", "params"),
    (
        ("protocol-versions", {}),
        ("protocol-versions/version-1/facts", {}),
        ("protocol-applicability-assignments", {}),
        (
            "protocol-applicability-assignments/resolve",
            {"centre_id": "01", "event_date": "2026-01-01"},
        ),
        ("rule-packs", {}),
        ("rule-packs/current", {}),
        ("rule-packs/pack-1", {}),
        ("rule-packs/pack-1/rules/RULE-1/source", {}),
        ("rule-packs/pack-1/diff/pack-2", {}),
        ("rule-packs/pack-1/shadow-sample-sets", {}),
        ("rule-packs/pack-1/shadow-lineage-evidence", {}),
        ("rule-packs/pack-1/shadow-runs", {}),
        ("rule-reviews", {}),
    ),
)
def test_protocol_and_rule_reads_require_server_principal(
    suffix: str,
    params: dict[str, str],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository, require_server_principal=True)
        response = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            params=params,
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
        assert "读取" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "protocol-facts/from-ai-candidate",
            {
                "protocol_version_id": "version-1",
                "candidate_id": "candidate-1",
                "fact_key": "fact-1",
                "proposed_fact_type": "eligibility",
            },
        ),
        ("rule-packs/pack-1/start-shadow", {"actor": "payload-spoof"}),
        (
            "rule-packs/pack-1/automatic-shadow-runs",
            {"batch_id": "batch-1", "actor": "payload-spoof"},
        ),
        ("rule-packs/pack-1/shadow-runs", {"batch_id": "batch-1"}),
    ),
)
def test_exact_action_protocol_rule_writes_require_server_principal(
    suffix: str,
    body: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository, require_server_principal=True)
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            json=body,
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
        assert "写入" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "protocol-facts/from-ai-candidate",
            {
                "protocol_version_id": "version-1",
                "candidate_id": "candidate-1",
                "fact_key": "fact-1",
                "proposed_fact_type": "eligibility",
            },
        ),
        ("rule-packs/pack-1/start-shadow", {"actor": "payload-spoof"}),
        (
            "rule-packs/pack-1/automatic-shadow-runs",
            {"batch_id": "batch-1", "actor": "payload-spoof"},
        ),
        ("rule-packs/pack-1/shadow-runs", {"batch_id": "batch-1"}),
    ),
)
def test_exact_action_protocol_rule_writes_require_matching_role(
    suffix: str,
    body: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(
                roles=(MonitoringRole.MEDICAL_WRITER,)
            ),
        )
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            json=body,
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "monitoring_role_not_permitted"


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "protocol-facts/fact-1/confirm",
            {
                "expected_state_version": 1,
                "fact_type": "eligibility",
                "deterministic_template": {},
                "confirmed_by": "payload-spoof",
            },
        ),
        (
            "rule-packs/pack-1/rules/rule-1/confirm",
            {"expected_state_version": 1, "confirmed_by": "payload-spoof"},
        ),
        ("rule-packs/pack-1/confirm-shadow", {"confirmed_by": "payload-spoof"}),
        ("rule-packs/pack-1/publish", {"actor": "payload-spoof"}),
    ),
)
def test_rule_change_writes_require_server_principal_before_lookup(
    suffix: str,
    body: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository, require_server_principal=True)
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            json=body,
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
        assert "写入" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "protocol-facts/fact-1/confirm",
            {
                "expected_state_version": 1,
                "fact_type": "eligibility",
                "deterministic_template": {},
                "confirmed_by": "payload-spoof",
            },
        ),
        (
            "rule-packs/pack-1/rules/rule-1/confirm",
            {"expected_state_version": 1, "confirmed_by": "payload-spoof"},
        ),
        ("rule-packs/pack-1/confirm-shadow", {"confirmed_by": "payload-spoof"}),
        ("rule-packs/pack-1/publish", {"actor": "payload-spoof"}),
    ),
)
def test_rule_change_writes_require_medical_director_role(
    suffix: str,
    body: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(),
        )
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            json=body,
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == (
            "monitoring_medical_director_role_required"
        )


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "protocol-facts/fact-1/confirm",
            {
                "expected_state_version": 1,
                "fact_type": "eligibility",
                "deterministic_template": {},
                "confirmed_by": "payload-spoof",
            },
        ),
        (
            "rule-packs/pack-1/rules/rule-1/confirm",
            {"expected_state_version": 1, "confirmed_by": "payload-spoof"},
        ),
        ("rule-packs/pack-1/confirm-shadow", {"confirmed_by": "payload-spoof"}),
        ("rule-packs/pack-1/publish", {"actor": "payload-spoof"}),
    ),
)
def test_rule_change_writes_require_reauthentication(
    suffix: str,
    body: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(
                roles=(MonitoringRole.MEDICAL_DIRECTOR,)
            ),
        )
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            json=body,
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == (
            "monitoring_reauthentication_required"
        )


def test_rule_change_with_director_reauth_and_evidence_reaches_service_boundary() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(
                roles=(MonitoringRole.MEDICAL_DIRECTOR,)
            ),
        )
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
            "rule-packs/pack-1/publish",
            json={
                "actor": "payload-spoof",
                "reauthenticated": True,
                "signature_evidence_sha256": "a" * 64,
            },
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == (
            "monitoring_rule_authoring_unavailable"
        )


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "protocol-versions",
            {
                "source_entry_id": "source-1",
                "protocol_code": "PROTO-1",
                "version_label": "V1.0",
                "version_date": "2026-01-01",
            },
        ),
        (
            "protocol-applicability-assignments",
            {
                "protocol_version_id": "version-1",
                "centre_id": "01",
                "operational_effective_from": "2026-01-01",
                "operational_effective_to": "2026-12-31",
                "evidence_text": "方案证据",
                "evidence_source_entry_id": "source-1",
                "evidence_locator": "p1",
            },
        ),
        (
            "protocol-applicability-assignments/assignment-1/confirm",
            {"expected_state_version": 1},
        ),
        (
            "protocol-applicability-assignments/assignment-1/retire",
            {"expected_state_version": 1},
        ),
        (
            "rule-packs/drafts",
            {
                "protocol_version_id": "version-1",
                "fact_revision_ids": ["fact-1"],
            },
        ),
    ),
)
def test_policy_gap_writes_fail_closed_without_server_principal(
    suffix: str,
    body: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository, require_server_principal=True)
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            json=body,
        )
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"


@pytest.mark.parametrize(
    ("suffix", "body"),
    (
        (
            "protocol-versions",
            {
                "source_entry_id": "source-1",
                "protocol_code": "PROTO-1",
                "version_label": "V1.0",
                "version_date": "2026-01-01",
            },
        ),
        (
            "protocol-applicability-assignments",
            {
                "protocol_version_id": "version-1",
                "centre_id": "01",
                "operational_effective_from": "2026-01-01",
                "operational_effective_to": "2026-12-31",
                "evidence_text": "方案证据",
                "evidence_source_entry_id": "source-1",
                "evidence_locator": "p1",
            },
        ),
        (
            "protocol-applicability-assignments/assignment-1/confirm",
            {"expected_state_version": 1},
        ),
        (
            "protocol-applicability-assignments/assignment-1/retire",
            {"expected_state_version": 1},
        ),
        (
            "rule-packs/drafts",
            {
                "protocol_version_id": "version-1",
                "fact_revision_ids": ["fact-1"],
            },
        ),
    ),
)
def test_policy_gap_writes_surface_unconfigured_action_after_identity_check(
    suffix: str,
    body: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(
            repository,
            require_server_principal=True,
            principal_resolver=lambda _request: _monitoring_principal(),
        )
        response = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/{suffix}",
            json=body,
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == (
            "monitoring_write_action_unconfigured"
        )


def test_empty_summary_does_not_compute_or_write_a_snapshot() -> None:
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "medical_risks.sqlite3"
        repository = MedicalRiskRepository(db_path)
        before_digest = _database_digest(db_path)
        before_counts = _row_counts(db_path)

        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/summary"
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["snapshot_status"] == "empty"
        assert payload["latest_complete_batch"] is None
        assert payload["open_risk_count"] == 0
        assert payload["unread_count"] == 0
        assert payload["high_risk_open_count"] == 0
        assert payload["needs_action_count"] == 0
        assert payload["recent_run_status"]["status"] == "not_started"
        assert _row_counts(db_path) == before_counts == (0, 0)
        assert _database_digest(db_path) == before_digest


@pytest.mark.parametrize("raw_value", ("false", 1, None))
def test_summary_registry_availability_requires_literal_boolean(raw_value: object) -> None:
    class MalformedRegistry:
        def has(self, project_id: str) -> object:
            assert project_id == PROJECT_ID
            return raw_value

    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        service = MedicalMonitoringSummaryService(
            risk_repository=repository,
            project_source_manifest_service=FakeManifestService(),
            monitoring_registry=MalformedRegistry(),
        )

        payload = service.module_summary(PROJECT_ID)

        assert payload["availability"] == "not_registered"
        assert payload["snapshot_status"] == "empty"


def test_empty_current_snapshot_query_does_not_compute_or_write() -> None:
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "medical_risks.sqlite3"
        repository = MedicalRiskRepository(db_path)
        before_digest = _database_digest(db_path)
        before_counts = _row_counts(db_path)

        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-snapshots/current",
            params={"subject_id": "S001"},
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["snapshot_status"] == "empty"
        assert payload["items"] == []
        assert payload["total"] == 0
        assert payload["applied_filters"]["subject_id"] == "S001"
        assert _row_counts(db_path) == before_counts == (0, 0)
        assert _database_digest(db_path) == before_digest


def test_explicit_run_generates_snapshot_and_repeated_run_is_idempotent() -> None:
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "medical_risks.sqlite3"
        repository = MedicalRiskRepository(db_path)
        client = _app(repository)

        first = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/runs"
        )

        assert first.status_code == 201, first.text
        first_payload = first.json()
        assert first_payload["status"] == "snapshot_generated"
        assert first_payload["subjects_evaluated"] == 2
        assert first_payload["risk_count"] == 2
        assert _row_counts(db_path) == (1, 2)

        snapshot = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-snapshots/current"
        )
        assert snapshot.status_code == 200, snapshot.text
        assert snapshot.json()["snapshot_id"] == first_payload["snapshot_id"]
        assert snapshot.json()["total"] == 2
        assert snapshot.json()["subjects_evaluated"] == 2
        assert snapshot.json()["analysis_source"] == "persisted_snapshot"
        assert all(item["frozen_evidence_count"] == 1 for item in snapshot.json()["items"])
        assert all(item["evidence_capture_complete"] is True for item in snapshot.json()["items"])
        assert all("evidence_snapshots" not in item for item in snapshot.json()["items"])

        second = client.post(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/runs"
        )
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "current_snapshot_reused"
        assert second.json()["snapshot_id"] == first_payload["snapshot_id"]
        assert _row_counts(db_path) == (1, 2)


def test_current_snapshot_exposes_one_unified_detection_and_work_item_projection() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=1,
            risks=[
                _risk(
                    "001",
                    severity=RiskSeverity.HIGH,
                    status=RiskStatus.ACTION_REQUIRED,
                )
            ],
        )

        response = _app(repository, FakeProjectionInbox()).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-snapshots/current"
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        item = payload["items"][0]
        assert item["detection_status"] == "action_required"
        assert (
            item["risk_category_code"]
            == "ae_mh_temporal_or_classification_review"
        )
        assert item["risk_category_label"] == "AE/MH关系复核"
        assert item["taxonomy_version"] == payload["taxonomy"]["taxonomy_version"]
        assert item["risk_item"] == item["title"]
        assert item["disposition_status"] == "explained_no_external_action"
        assert item["updated_at"] == item["work_item"]["last_action_at"]
        assert item["work_item"]["medical_disposition_status"] == "已说明，无需外部动作"
        assert item["work_item"]["medical_disposition_state"] == "explained_no_external_action"
        assert item["work_item"]["read_state"] == "read"
        assert item["work_item"]["needs_action"] is False
        assert item["work_item"]["query_workflow_state"] == "not_applicable"
        assert payload["query_workflow_policy"]["internal_approval_required"] is False
        assert payload["rollup"]["trial"]["risk_count"] == 1
        assert payload["rollup"]["trial"]["unread_count"] == 0
        assert payload["rollup"]["trial"]["needs_action_count"] == 0
        assert payload["rollup"]["trial"]["medical_disposition_counts"] == {
            "explained_no_external_action": 1
        }
        assert sum(row["risk_count"] for row in payload["rollup"]["sites"]) == 1
        assert sum(row["risk_count"] for row in payload["rollup"]["subjects"]) == 1


def test_risk_taxonomy_endpoint_is_closed_and_project_scoped() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")

        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-taxonomy"
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["project_id"] == PROJECT_ID
        assert payload["closed"] is True
        assert len(payload["categories"]) == 18
        assert all(
            item["taxonomy_version"] == payload["taxonomy_version"]
            for item in payload["categories"]
        )


def test_current_snapshot_supports_all_seven_column_filters_and_sorts() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=3,
            risks=[
                _risk(
                    "001",
                    severity=RiskSeverity.LOW,
                    status=RiskStatus.NEW,
                    primary_category="data_quality",
                    title="Beta data item",
                    subject_id="S002",
                    site_id="02",
                    created_at=NOW - timedelta(days=2),
                ),
                _risk(
                    "002",
                    severity=RiskSeverity.HIGH,
                    status=RiskStatus.ACTION_REQUIRED,
                    primary_category="laboratory_abnormality",
                    title="Alpha laboratory item",
                    subject_id="S001",
                    site_id="01",
                    created_at=NOW - timedelta(days=1),
                ).model_copy(update={"tags": ["safety_pv"]}),
                _risk(
                    "003",
                    severity=RiskSeverity.MEDIUM,
                    status=RiskStatus.IN_REVIEW,
                    primary_category="study_treatment_adherence",
                    title="Gamma adherence item",
                    subject_id="S003",
                    site_id="01",
                ).model_copy(
                    update={
                        "tags": [
                            "source_domain:ex",
                            "study_treatment_record",
                        ]
                    }
                ),
            ],
        )
        client = _app(repository, FakeProjectionInbox())
        endpoint = (
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
            "risk-snapshots/current"
        )
        filters = {
            "subject_id": ("S001", "riskinst_002"),
            "site_id": ("02", "riskinst_001"),
            "severity": ("medium", "riskinst_003"),
            "risk_category_code": (
                "laboratory_abnormality",
                "riskinst_002",
            ),
            "risk_item": ("adherence", "riskinst_003"),
            "disposition_status": (
                "explained_no_external_action",
                "riskinst_001",
            ),
            "updated_at": ("2026-07-28", "riskinst_002"),
        }
        for field, (value, expected_id) in filters.items():
            response = client.get(endpoint, params={field: value})
            assert response.status_code == 200, (field, response.text)
            assert [item["risk_instance_id"] for item in response.json()["items"]] == [
                expected_id
            ]

        expected_ascending = {
            "subject_id": ["S001", "S002", "S003"],
            "site_id": ["01", "01", "02"],
            "severity": ["low", "medium", "high"],
            "risk_category_code": [
                "data_quality",
                "laboratory_abnormality",
                "study_treatment_adherence",
            ],
            "risk_item": [
                "Alpha laboratory item",
                "Beta data item",
                "Gamma adherence item",
            ],
            "disposition_status": [
                "explained_no_external_action",
                "pending_review",
                "pending_review",
            ],
            "updated_at": [
                "2026-07-28T00:00:00+00:00",
                "2026-07-29T00:00:00+00:00",
                "2026-07-29T00:00:00+00:00",
            ],
        }
        for sort_by, expected in expected_ascending.items():
            response = client.get(
                endpoint,
                params={"sort_by": sort_by, "sort_direction": "asc"},
            )
            assert response.status_code == 200, (sort_by, response.text)
            assert [
                item[sort_by] for item in response.json()["items"]
            ] == expected
            assert response.json()["sort"]["stable_tiebreaker"] == (
                "risk_instance_id"
            )


def test_current_snapshot_rejects_unknown_fields_and_invalid_sort_values() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository)
        endpoint = (
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
            "risk-snapshots/current"
        )

        unknown = client.get(endpoint, params={"title_filter": "AE"})
        invalid_sort = client.get(endpoint, params={"sort_by": "title"})
        invalid_category = client.get(
            endpoint,
            params={"risk_category_code": "free_text_category"},
        )

        assert unknown.status_code == 422
        assert (
            unknown.json()["detail"]["code"]
            == "unknown_risk_snapshot_query_field"
        )
        assert invalid_sort.status_code == 422
        assert invalid_category.status_code == 422
        assert (
            invalid_category.json()["detail"]["code"]
            == "unsupported_risk_category_code"
        )


def test_current_snapshot_desc_sort_is_stable_across_pages_with_ties() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        snapshot = repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=5,
            risks=[
                _risk("001", severity=RiskSeverity.HIGH, status=RiskStatus.IN_REVIEW),
                _risk(
                    "002",
                    severity=RiskSeverity.CRITICAL,
                    status=RiskStatus.IN_REVIEW,
                ),
                _risk("003", severity=RiskSeverity.HIGH, status=RiskStatus.IN_REVIEW),
                _risk(
                    "004",
                    severity=RiskSeverity.MEDIUM,
                    status=RiskStatus.IN_REVIEW,
                ),
                _risk("005", severity=RiskSeverity.LOW, status=RiskStatus.IN_REVIEW),
            ],
        )
        client = _app(repository)
        endpoint = (
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
            "risk-snapshots/current"
        )

        pages = [
            client.get(
                endpoint,
                params={
                    "snapshot_id": snapshot.snapshot_id,
                    "sort_by": "severity",
                    "sort_direction": "desc",
                    "page": page,
                    "page_size": 2,
                },
            )
            for page in (1, 2, 3)
        ]

        assert all(response.status_code == 200 for response in pages)
        items = [
            item
            for response in pages
            for item in response.json()["items"]
        ]
        assert [item["severity"] for item in items] == [
            "critical",
            "high",
            "high",
            "medium",
            "low",
        ]
        assert [item["risk_instance_id"] for item in items[1:3]] == [
            "riskinst_003",
            "riskinst_001",
        ]
        assert len({item["risk_instance_id"] for item in items}) == 5


def test_snapshot_id_pins_pagination_when_a_new_snapshot_arrives() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        first = repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=4,
            risks=[
                _risk(
                    f"00{index}",
                    severity=RiskSeverity.MEDIUM,
                    status=RiskStatus.IN_REVIEW,
                    subject_id=f"S00{index}",
                )
                for index in range(1, 5)
            ],
        )
        client = _app(repository)
        endpoint = (
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/"
            "risk-snapshots/current"
        )
        first_page = client.get(
            endpoint,
            params={
                "sort_by": "subject_id",
                "sort_direction": "asc",
                "page": 1,
                "page_size": 2,
            },
        )
        assert first_page.status_code == 200, first_page.text
        assert first_page.json()["snapshot_id"] == first.snapshot_id
        assert [
            item["subject_id"] for item in first_page.json()["items"]
        ] == ["S001", "S002"]

        second_revision = "monsrcv_test_002"
        second = repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision=second_revision,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=5,
            risks=[
                _risk(
                    f"00{index}",
                    severity=RiskSeverity.MEDIUM,
                    status=RiskStatus.IN_REVIEW,
                    subject_id=f"S00{index}",
                    source_revision=second_revision,
                )
                for index in range(1, 6)
            ],
        )

        pinned_second_page = client.get(
            endpoint,
            params={
                "snapshot_id": first.snapshot_id,
                "sort_by": "subject_id",
                "sort_direction": "asc",
                "page": 2,
                "page_size": 2,
            },
        )
        assert pinned_second_page.status_code == 200, pinned_second_page.text
        payload = pinned_second_page.json()
        assert payload["snapshot_id"] == first.snapshot_id
        assert payload["current_snapshot_id"] == second.snapshot_id
        assert payload["is_current_snapshot"] is False
        assert [item["subject_id"] for item in payload["items"]] == [
            "S003",
            "S004",
        ]

        missing = client.get(
            endpoint,
            params={"snapshot_id": "risksnap_missing"},
        )
        assert missing.status_code == 409
        assert (
            missing.json()["detail"]["code"]
            == "medical_monitoring_snapshot_not_found"
        )


def test_current_snapshot_hides_terminal_detections_unless_explicitly_requested() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=2,
            risks=[
                _risk("001", severity=RiskSeverity.HIGH, status=RiskStatus.ACTION_REQUIRED),
                _risk("002", severity=RiskSeverity.MEDIUM, status=RiskStatus.SUPERSEDED),
            ],
        )
        client = _app(repository)

        current = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-snapshots/current"
        )
        assert current.status_code == 200, current.text
        assert current.json()["total"] == 1
        assert current.json()["items"][0]["risk_key"] == "riskkey_001"
        assert current.json()["applied_filters"]["include_terminal"] is False

        audit = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-snapshots/current",
            params={"include_terminal": "true"},
        )
        assert audit.status_code == 200, audit.text
        assert audit.json()["total"] == 2
        assert audit.json()["applied_filters"]["include_terminal"] is True

        superseded = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/risk-snapshots/current",
            params={"status": "superseded"},
        )
        assert superseded.status_code == 200, superseded.text
        assert superseded.json()["total"] == 1
        assert superseded.json()["items"][0]["risk_key"] == "riskkey_002"


def test_summary_projects_snapshot_counts_and_read_state_without_recalculation() -> None:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        repository = MedicalRiskRepository(root / "medical_risks.sqlite3")
        risks = [
            _risk("001", severity=RiskSeverity.HIGH, status=RiskStatus.ACTION_REQUIRED),
            _risk("002", severity=RiskSeverity.MEDIUM, status=RiskStatus.NEW),
            _risk("003", severity=RiskSeverity.CRITICAL, status=RiskStatus.RESOLVED),
        ]
        snapshot = repository.save_snapshot(
            project_id=PROJECT_ID,
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=3,
            risks=risks,
        )
        inbox_store = WorkbenchInboxStore(root / "workbench_inbox_actions.jsonl")
        first = repository.list_risks(PROJECT_ID, snapshot.snapshot_id)[0]
        inbox_store.append(
            WorkbenchInboxActionRecord(
                record_id="read_001",
                project_id=PROJECT_ID,
                item_id=f"monitoring-risk:{first.risk_instance_id}",
                action=WorkbenchItemAction.MARK_READ,
                actor="medical_manager",
                source_version=_monitoring_source_version(first, SOURCE_REVISION),
                created_at=NOW,
            )
        )
        inbox_service = SimpleNamespace(
            store=inbox_store,
            rux_disposition_store=None,
        )
        before_counts = _row_counts(repository.db_path)

        response = _app(repository, inbox_service).get(
            "/api/projects/project-alias/modules/medical-monitoring/summary"
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["project_id"] == PROJECT_ID
        assert payload["snapshot_status"] == "available"
        assert payload["open_risk_count"] == 2
        assert payload["unread_count"] == 1
        assert payload["high_risk_open_count"] == 1
        assert payload["needs_action_count"] == 2
        assert payload["latest_complete_batch"]["snapshot_id"] == snapshot.snapshot_id
        assert (
            payload["latest_complete_batch"]["batch_label"]
            == "2026-07-29 EDC Listing"
        )
        assert payload["recent_run_status"]["status"] == "snapshot_available"
        assert payload["default_deep_link"]["project_id"] == PROJECT_ID
        assert _row_counts(repository.db_path) == before_counts


def test_deep_link_contract_normalizes_valid_subject_focus() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        snapshot = repository.save_snapshot(
            project_id=PROJECT_ID,
            source_batch_id="batch_001",
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=2,
            risks=[
                _risk(
                    "001",
                    severity=RiskSeverity.HIGH,
                    status=RiskStatus.ACTION_REQUIRED,
                )
            ],
        )
        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={
                "scope": "subject",
                "view": "timeline",
                "site_id": " 01 ",
                "subject_id": " S001 ",
                "risk_key": " riskkey_001 ",
                "risk_instance_id": " riskinst_001 ",
                "batch_id": " risksnap_001 ",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["scope"] == "subject"
        assert payload["view"] == "timeline"
        assert payload["site_id"] == "01"
        assert payload["subject_id"] == "S001"
        assert payload["risk_key"] == "riskkey_001"
        assert payload["risk_instance_id"] == "riskinst_001"
        assert payload["batch_id"] == "risksnap_001"
        assert payload["risk_snapshot_id"] == snapshot.snapshot_id
        assert "project_id=proj_test" in payload["href"]
        assert "view=timeline" in payload["href"]

        evidence = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={
                "scope": "subject",
                "view": "evidence",
                "subject_id": "S001",
                "risk_instance_id": "riskinst_001",
            },
        )
        assert evidence.status_code == 200, evidence.text
        assert evidence.json()["view"] == "evidence"


def test_deep_link_contract_rejects_incoherent_scope_and_view() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        client = _app(repository)

        missing_site = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={"scope": "site"},
        )
        assert missing_site.status_code == 422
        assert missing_site.json()["detail"]["code"] == "site_id_required"

        trial_with_subject = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={"scope": "trial", "subject_id": "S001"},
        )
        assert trial_with_subject.status_code == 422
        assert trial_with_subject.json()["detail"]["code"] == "trial_scope_conflict"

        timeline_without_subject = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={"scope": "trial", "view": "timeline"},
        )
        assert timeline_without_subject.status_code == 422
        assert (
            timeline_without_subject.json()["detail"]["code"]
            == "subject_view_requires_subject"
        )

        evidence_without_risk = client.get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={"scope": "trial", "view": "evidence"},
        )
        assert evidence_without_risk.status_code == 422
        assert (
            evidence_without_risk.json()["detail"]["code"]
            == "evidence_view_requires_risk"
        )


def test_deep_link_round_trips_full_pinned_checklist_and_evidence_state() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        snapshot = repository.save_snapshot(
            project_id=PROJECT_ID,
            source_batch_id="batch_001",
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=2,
            risks=[
                _risk(
                    "001",
                    severity=RiskSeverity.HIGH,
                    status=RiskStatus.ACTION_REQUIRED,
                )
            ],
        )
        before_digest = _database_digest(repository.db_path)
        before_counts = _row_counts(repository.db_path)
        params = {
            "scope": "subject",
            "view": "evidence",
            "site_id": "01",
            "subject_id": "S001",
            "risk_key": "riskkey_001",
            "risk_instance_id": "riskinst_001",
            "batch_id": "batch_001",
            "evidence_tab": "sources",
            "filter_subject_id": "S001",
            "filter_site_id": "01",
            "filter_severity": "high",
            "filter_risk_category_code": (
                "ae_mh_temporal_or_classification_review"
            ),
            "filter_risk_item": "风险 001",
            "filter_disposition_status": "pending_review",
            "filter_updated_at": "2026-07-29",
            "sort_by": "subject_id",
            "sort_direction": "asc",
            "page": 1,
            "page_size": 25,
            "risk_snapshot_id": snapshot.snapshot_id,
        }

        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params=params,
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["contract_version"].endswith(".2")
        assert payload["risk_snapshot_id"] == snapshot.snapshot_id
        assert payload["evidence_tab"] == "sources"
        assert payload["risk_sort_by"] == "subject_id"
        assert payload["risk_sort_direction"] == "asc"
        assert payload["risk_page"] == 1
        assert payload["risk_page_size"] == 25
        canonical = {
            key: values[0]
            for key, values in parse_qs(urlparse(payload["href"]).query).items()
        }
        for key, expected in {
            "project_id": PROJECT_ID,
            "scope": "subject",
            "view": "evidence",
            "site_id": "01",
            "subject_id": "S001",
            "risk_key": "riskkey_001",
            "risk_instance_id": "riskinst_001",
            "batch_id": "batch_001",
            "evidence_tab": "sources",
            "filter_subject_id": "S001",
            "filter_site_id": "01",
            "filter_severity": "high",
            "filter_risk_category_code": (
                "ae_mh_temporal_or_classification_review"
            ),
            "filter_risk_item": "风险 001",
            "filter_disposition_status": "pending_review",
            "filter_updated_at": "2026-07-29",
            "risk_sort_by": "subject_id",
            "risk_sort_direction": "asc",
            "risk_page": "1",
            "risk_page_size": "25",
            "risk_snapshot_id": snapshot.snapshot_id,
        }.items():
            assert canonical[key] == expected
        assert _row_counts(repository.db_path) == before_counts
        assert _database_digest(repository.db_path) == before_digest


def test_deep_link_rejects_invalid_closed_values_and_page_bounds() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        repository.save_snapshot(
            project_id=PROJECT_ID,
            source_batch_id="batch_001",
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=2,
            risks=[
                _risk(
                    "001",
                    severity=RiskSeverity.HIGH,
                    status=RiskStatus.ACTION_REQUIRED,
                )
            ],
        )
        client = _app(repository)
        endpoint = (
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link"
        )

        for params in (
            {"evidence_tab": "raw-log"},
            {"risk_sort_by": "title"},
            {"risk_sort_direction": "sideways"},
            {"filter_severity": "urgent"},
            {"filter_risk_category_code": "invented_category"},
            {"filter_disposition_status": "invented_state"},
            {"filter_updated_at": "29/07/2026"},
            {"risk_page": 0},
            {"risk_page_size": 201},
        ):
            response = client.get(endpoint, params=params)
            assert response.status_code == 422, (params, response.text)

        out_of_range = client.get(endpoint, params={"page": 2, "page_size": 50})
        assert out_of_range.status_code == 422
        assert (
            out_of_range.json()["detail"]["code"]
            == "medical_monitoring_page_out_of_range"
        )

        conflict = client.get(
            endpoint,
            params={"risk_page": 1, "page": 2},
        )
        assert conflict.status_code == 422
        assert conflict.json()["detail"]["code"] == "conflicting_page"


def test_deep_link_rejects_snapshot_owned_by_another_project() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        other_project = "proj_other"
        other_snapshot = repository.save_snapshot(
            project_id=other_project,
            source_batch_id="batch_other",
            source_revision="source_other",
            rule_profile_revision="rules_other",
            engine_version="engine_other",
            evaluated_subject_count=1,
            risks=[
                _risk(
                    "900",
                    severity=RiskSeverity.MEDIUM,
                    status=RiskStatus.NEW,
                    source_revision="source_other",
                ).model_copy(
                    update={
                        "project_id": other_project,
                        "source_batch_id": "batch_other",
                        "rule_profile_revision": "rules_other",
                        "engine_version": "engine_other",
                    }
                )
            ],
        )

        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={"risk_snapshot_id": other_snapshot.snapshot_id},
        )

        assert response.status_code == 409
        assert (
            response.json()["detail"]["code"]
            == "medical_monitoring_snapshot_not_found"
        )


def test_deep_link_redirects_stale_instance_by_stable_risk_key() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")
        first_risk = _risk(
            "001",
            severity=RiskSeverity.HIGH,
            status=RiskStatus.ACTION_REQUIRED,
        ).model_copy(
            update={
                "risk_key": "riskkey_stable",
                "risk_instance_id": "riskinst_old",
            }
        )
        repository.save_snapshot(
            project_id=PROJECT_ID,
            source_batch_id="batch_001",
            source_revision=SOURCE_REVISION,
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=2,
            risks=[first_risk],
        )
        current_snapshot = repository.save_snapshot(
            project_id=PROJECT_ID,
            source_batch_id="batch_002",
            source_revision="monsrcv_test_002",
            rule_profile_revision="rules_v1",
            engine_version="engine_v1",
            evaluated_subject_count=2,
            risks=[
                first_risk.model_copy(
                    update={
                        "risk_instance_id": "riskinst_current",
                        "source_batch_id": "batch_002",
                        "source_revision": "monsrcv_test_002",
                    }
                )
            ],
        )

        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={
                "scope": "subject",
                "view": "evidence",
                "site_id": "01",
                "subject_id": "S001",
                "risk_instance_id": "riskinst_old",
                "evidence_tab": "history",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["risk_key"] == "riskkey_stable"
        assert payload["risk_instance_id"] == "riskinst_current"
        assert payload["risk_snapshot_id"] == current_snapshot.snapshot_id
        assert payload["redirect_reason"] == "risk_instance_replaced_in_snapshot"
        assert payload["redirect_from_risk_instance_id"] == "riskinst_old"
        assert "risk_instance_id=riskinst_current" in payload["href"]
        assert "evidence_tab=history" in payload["href"]


def test_deep_link_rejects_missing_subject_before_opening_subject_view() -> None:
    with TemporaryDirectory() as tmp:
        repository = MedicalRiskRepository(Path(tmp) / "medical_risks.sqlite3")

        response = _app(repository).get(
            f"/api/projects/{PROJECT_ID}/modules/medical-monitoring/deep-link",
            params={
                "scope": "subject",
                "view": "timeline",
                "site_id": "01",
                "subject_id": "S999",
            },
        )

        assert response.status_code == 404
        assert (
            response.json()["detail"]["code"]
            == "medical_monitoring_subject_not_found"
        )
