from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from datetime import datetime, timezone

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidate,
    MonitoringAiCandidateStatus,
    MonitoringAiClaim,
    MonitoringAiClaimKind,
    MonitoringAiEvidence,
    MonitoringAiTaskType,
)

from services.api.app.monitoring_daily_run_repository import (
    DailyRunInput,
    MonitoringDailyRunRepository,
)
from services.api.app.monitoring_daily_run_router import (
    _ai_progress_dict,
    create_monitoring_daily_run_router,
)
from services.api.app.monitoring_daily_run_ai_service import (
    MonitoringDailyAiProgress,
    MonitoringDailyAiReviewCandidate,
)
from services.api.app.monitoring_daily_run_service import (
    MonitoringDailyRunServiceError,
)
from services.api.app.monitoring_identity_authorization import MonitoringRole
from services.api.app.monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
)


class _Service:
    def __init__(self, repository):
        self.repository = repository
        self.worker_calls = []

    def prepare(self, *, project_id, batch_id, idempotency_key, actor):
        if batch_id == "missing":
            raise MonitoringDailyRunServiceError(
                "monitoring_batch_not_found",
                "未找到医学监查批次。",
            )
        if batch_id == "drifted":
            raise MonitoringDailyRunServiceError(
                "monitoring_rule_pack_identity_drift",
                "已发布规则包的字段映射身份与当前已激活映射不一致，请按最新映射重新确认规则并发布规则包。",
            )
        if batch_id == "record":
            return self.repository.create_or_get(
                DailyRunInput(
                    project_id=project_id,
                    batch_id=batch_id,
                    baseline_batch_id=None,
                    batch_version=2,
                    mapping_revision="mapping-v1",
                    rule_pack_revision="",
                    rule_resolution_mode="record_applicability",
                    rule_identity_sha256="e" * 64,
                    engine_version="rule-engine-v1",
                    diff_algorithm_version="monitoring_batch_diff.v2",
                ),
                idempotency_key=idempotency_key,
                actor=actor,
            )
        return self.repository.create_or_get(
            DailyRunInput(
                project_id=project_id,
                batch_id=batch_id,
                baseline_batch_id=None,
                batch_version=2,
                mapping_revision="mapping-v1",
                rule_pack_revision="rule-pack-v1",
                engine_version="rule-engine-v1",
                diff_algorithm_version="monitoring_batch_diff.v2",
            ),
            idempotency_key=idempotency_key,
            actor=actor,
        )

    def start_readiness(self, *, project_id, batch_id):
        return {
            "project_id": project_id,
            "batch_id": batch_id,
            "ready": batch_id != "blocked",
            "state_code": "ready" if batch_id != "blocked" else "monitoring_mapping_required",
            "message": "可启动" if batch_id != "blocked" else "请先确认字段映射",
            "next_action": "start_daily_run" if batch_id != "blocked" else "confirm_mapping",
        }

    def process_prepared(self, **kwargs):
        self.worker_calls.append(("process", kwargs["owner"]))
        run = self.repository.get(kwargs["project_id"], kwargs["run_id"])
        return SimpleNamespace(
            to_dict=lambda: {
                "run": run.to_dict(),
                "diff_snapshot": None,
                "next_action": "run_rules",
            }
        )

    def execute_rules(self, **kwargs):
        self.worker_calls.append(("execute-rules", kwargs["owner"]))
        run = self.repository.get(kwargs["project_id"], kwargs["run_id"])
        return SimpleNamespace(
            to_dict=lambda: {
                "run": run.to_dict(),
                "rule_result": {
                    "snapshot_id": "monrules-1",
                    "candidate_count": 2,
                    "diagnostic_count": 1,
                    "evaluated_record_count": 8,
                },
                "next_action": "run_independent_ai",
            }
        )


class _AnalysisService:
    def __init__(self):
        self.worker_calls = []

    def submit_ai(self, **kwargs):
        self.worker_calls.append(("submit-ai", kwargs["owner"]))
        return SimpleNamespace(
            to_dict=lambda: {
                "run": {"run_id": kwargs["run_id"]},
                "next_action": "wait_for_independent_ai",
            }
        )

    def assemble_risks(self, **kwargs):
        self.worker_calls.append(("assemble-risks", kwargs["owner"]))
        return SimpleNamespace(
            to_dict=lambda: {
                "run": {"run_id": kwargs["run_id"]},
                "next_action": "review_risks",
            }
        )


def _client(temporary):
    repository = MonitoringDailyRunRepository(
        Path(temporary.name) / "daily-runs.sqlite3"
    )
    app = FastAPI()
    app.include_router(
        create_monitoring_daily_run_router(
            repository=repository,
            service=_Service(repository),
            project_resolver=lambda project_id: (
                "project-1" if project_id == "alias-1" else project_id
            ),
            require_server_principal=False,
        )
    )
    return TestClient(app), repository


def _principal(
    *,
    project_scope=("project-1",),
    roles=(MonitoringRole.MEDICAL_MANAGER,),
):
    return MonitoringAuthenticatedPrincipal(
        principal_id="verified-daily-reader",
        tenant_id="tenant-kangzhe",
        roles=roles,
        project_scope=project_scope,
        issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
        authenticated=True,
        authn_method="test-server-session",
        session_id="server-session-secret",
        directory_revision="directory-test-v1",
        verification_ref_sha256="b" * 64,
    )


def _production_client(temporary, *, resolver=None, analysis_service=None):
    repository = MonitoringDailyRunRepository(
        Path(temporary.name) / "daily-runs.sqlite3"
    )
    app = FastAPI()
    service = _Service(repository)
    app.include_router(
        create_monitoring_daily_run_router(
            repository=repository,
            service=service,
            analysis_service=analysis_service,
            project_resolver=lambda project_id: (
                "project-1" if project_id == "alias-1" else project_id
            ),
            principal_resolver=resolver,
            require_server_principal=True,
        )
    )
    app.state.monitoring_daily_run_service = service
    app.state.monitoring_daily_run_analysis_service = analysis_service
    return TestClient(app), repository


@pytest.mark.parametrize(
    ("method", "suffix", "params"),
    [
        ("GET", "", {}),
        ("GET", "readiness", {"batch_id": "batch-1"}),
        ("GET", "run-1", {}),
        ("GET", "run-1/ai-progress", {}),
    ],
)
def test_every_daily_read_route_requires_server_principal(
    tmp_path: Path,
    method: str,
    suffix: str,
    params: dict,
):
    temporary = SimpleNamespace(name=str(tmp_path / suffix.replace("/", "-")))
    Path(temporary.name).mkdir(parents=True, exist_ok=True)
    client, _ = _production_client(temporary)
    path = f"/api/projects/project-1/monitoring/daily-runs/{suffix}".rstrip("/")
    response = client.request(method, path, params=params)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
    assert "读取" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    ("method", "suffix", "params"),
    [
        ("GET", "", {}),
        ("GET", "readiness", {"batch_id": "batch-1"}),
        ("GET", "run-1", {}),
        ("GET", "run-1/ai-progress", {}),
    ],
)
def test_daily_read_routes_require_monitoring_read_role(
    tmp_path: Path,
    method: str,
    suffix: str,
    params: dict,
):
    temporary = SimpleNamespace(name=str(tmp_path / f"admin-{suffix.replace('/', '-') }"))
    Path(temporary.name).mkdir(parents=True, exist_ok=True)
    client, _ = _production_client(
        temporary,
        resolver=lambda _request: _principal(roles=(MonitoringRole.SYSTEM_ADMIN,)),
    )
    path = f"/api/projects/project-1/monitoring/daily-runs/{suffix}".rstrip("/")
    response = client.request(method, path, params=params)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "monitoring_role_not_permitted"


def test_scoped_medical_manager_can_read_daily_run_surfaces(tmp_path: Path):
    temporary = SimpleNamespace(name=str(tmp_path / "scoped"))
    Path(temporary.name).mkdir(parents=True, exist_ok=True)
    client, _ = _production_client(
        temporary,
        resolver=lambda _request: _principal(),
    )
    listed = client.get("/api/projects/alias-1/monitoring/daily-runs")
    readiness = client.get(
        "/api/projects/alias-1/monitoring/daily-runs/readiness",
        params={"batch_id": "blocked"},
    )
    missing = client.get(
        "/api/projects/alias-1/monitoring/daily-runs/run-missing"
    )
    progress = client.get(
        "/api/projects/alias-1/monitoring/daily-runs/run-missing/ai-progress"
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["project_id"] == "project-1"
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["ready"] is False
    assert missing.status_code == 404, missing.text
    assert progress.status_code == 503, progress.text
    assert progress.json()["detail"]["code"] == "monitoring_daily_analysis_unavailable"


_WRITE_CASES = (
    ("", {"batch_id": "batch-1", "idempotency_key": "prepare-1", "actor": "payload-spoof"}),
    ("run-1/process", {"expected_version": 1, "owner": "payload-owner"}),
    ("run-1/execute-rules", {"expected_version": 1, "owner": "payload-owner"}),
    ("run-1/submit-ai", {"expected_version": 1, "owner": "payload-owner"}),
    ("run-1/assemble-risks", {"expected_version": 1, "owner": "payload-owner"}),
    ("run-1/acknowledge-partial", {"expected_version": 1, "actor": "payload-spoof"}),
    ("run-1/ready-to-confirm", {"expected_version": 1, "actor": "payload-spoof"}),
    ("run-1/supersede", {"replacement_run_id": "run-2", "expected_version": 1, "actor": "payload-spoof"}),
    ("run-1/confirm", {"expected_run_version": 1, "expected_baseline_revision": 0, "confirmed_by": "payload-spoof"}),
)


@pytest.mark.parametrize(
    ("suffix", "body"),
    [
        ("run-1/process", {"expected_version": True, "owner": "worker"}),
        ("run-1/execute-rules", {"expected_version": "1", "owner": "worker"}),
        ("run-1/submit-ai", {"expected_version": False, "owner": "worker"}),
        ("run-1/assemble-risks", {"expected_version": "1", "owner": "worker"}),
        ("run-1/acknowledge-partial", {"expected_version": True, "actor": "manager"}),
        ("run-1/ready-to-confirm", {"expected_version": "1", "actor": "manager"}),
        ("run-1/supersede", {"replacement_run_id": "run-2", "expected_version": False, "actor": "manager"}),
        ("run-1/supersede", {"replacement_run_id": "run-2", "expected_version": "1", "actor": "manager"}),
        (
            "run-1/confirm",
            {
                "expected_run_version": True,
                "expected_baseline_revision": 0,
                "confirmed_by": "manager",
                "reauthenticated": True,
                "signature_evidence_sha256": "a" * 64,
            },
        ),
        (
            "run-1/confirm",
            {
                "expected_run_version": 1,
                "expected_baseline_revision": 0,
                "confirmed_by": "manager",
                "reauthenticated": 0,
                "signature_evidence_sha256": "a" * 64,
            },
        ),
        (
            "run-1/confirm",
            {
                "expected_run_version": 1,
                "expected_baseline_revision": 0,
                "confirmed_by": "manager",
                "reauthenticated": "false",
                "signature_evidence_sha256": "a" * 64,
            },
        ),
    ],
)
def test_daily_cas_version_fields_reject_bool_and_numeric_string(
    tmp_path: Path,
    suffix: str,
    body: dict,
):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "strict-input")),
        resolver=lambda _request: _principal(),
    )
    response = client.post(
        f"/api/projects/project-1/monitoring/daily-runs/{suffix}",
        json=body,
    )
    assert response.status_code == 422, response.text
    assert repository.list_runs("project-1") == ()


@pytest.mark.parametrize(("suffix", "body"), _WRITE_CASES)
def test_every_daily_write_route_requires_server_principal(
    tmp_path: Path,
    suffix: str,
    body: dict,
):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "missing"))
    )
    path = f"/api/projects/project-1/monitoring/daily-runs/{suffix}".rstrip("/")
    response = client.post(path, json=body)
    assert response.status_code == 503, response.text
    assert response.json()["detail"]["code"] == "monitoring_principal_unavailable"
    assert "写入" in response.json()["detail"]["message"]
    assert repository.list_runs("project-1") == ()


@pytest.mark.parametrize(("suffix", "body"), _WRITE_CASES)
def test_every_daily_write_route_requires_mapped_role(
    tmp_path: Path,
    suffix: str,
    body: dict,
):
    client, _ = _production_client(
        SimpleNamespace(name=str(tmp_path / "admin")),
        resolver=lambda _request: _principal(roles=(MonitoringRole.SYSTEM_ADMIN,)),
    )
    path = f"/api/projects/project-1/monitoring/daily-runs/{suffix}".rstrip("/")
    response = client.post(path, json=body)
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "monitoring_role_not_permitted"


def test_scoped_manager_write_uses_verified_actor_not_payload_actor(
    tmp_path: Path,
):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "scoped-write")),
        resolver=lambda _request: _principal(),
    )
    response = client.post(
        "/api/projects/alias-1/monitoring/daily-runs",
        json={
            "batch_id": "batch-1",
            "idempotency_key": "verified-actor-1",
            "actor": "payload-spoof",
        },
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["run"]["run_id"]
    events = repository.list_events(run_id)
    assert events
    assert events[0].actor == "verified-daily-reader"
    assert "payload-spoof" not in response.text


def test_worker_routes_use_verified_server_actor_not_payload_owner(
    tmp_path: Path,
):
    analysis = _AnalysisService()
    client, _ = _production_client(
        SimpleNamespace(name=str(tmp_path / "verified-owner")),
        resolver=lambda _request: _principal(),
        analysis_service=analysis,
    )
    created = client.post(
        "/api/projects/project-1/monitoring/daily-runs",
        json={
            "batch_id": "batch-1",
            "idempotency_key": "verified-owner-1",
            "actor": "payload-actor",
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["run"]["run_id"]
    expected = created.json()["run"]["version"]
    body = {"expected_version": expected, "owner": "payload-owner"}

    process = client.post(
        f"/api/projects/project-1/monitoring/daily-runs/{run_id}/process",
        json=body,
    )
    execute = client.post(
        f"/api/projects/project-1/monitoring/daily-runs/{run_id}/execute-rules",
        json=body,
    )
    submit = client.post(
        f"/api/projects/project-1/monitoring/daily-runs/{run_id}/submit-ai",
        json=body,
    )
    assemble = client.post(
        f"/api/projects/project-1/monitoring/daily-runs/{run_id}/assemble-risks",
        json=body,
    )
    assert process.status_code == 200, process.text
    assert execute.status_code == 200, execute.text
    assert submit.status_code == 200, submit.text
    assert assemble.status_code == 200, assemble.text
    assert client.app.state.monitoring_daily_run_service.worker_calls == [
        ("process", "verified-daily-reader"),
        ("execute-rules", "verified-daily-reader"),
    ]
    assert analysis.worker_calls == [
        ("submit-ai", "verified-daily-reader"),
        ("assemble-risks", "verified-daily-reader"),
    ]


def test_daily_write_rejects_project_scope_before_mutation(tmp_path: Path):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "scope-denied")),
        resolver=lambda _request: _principal(project_scope=("other-project",)),
    )
    response = client.post(
        "/api/projects/project-1/monitoring/daily-runs",
        json={
            "batch_id": "batch-1",
            "idempotency_key": "scope-denied-1",
            "actor": "payload-spoof",
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "monitoring_project_scope_denied"
    assert repository.list_runs("project-1") == ()


def test_daily_confirm_requires_reauthentication_before_signature(
    tmp_path: Path,
):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "confirm-reauth")),
        resolver=lambda _request: _principal(),
    )
    response = client.post(
        "/api/projects/project-1/monitoring/daily-runs/run-missing/confirm",
        json={
            "expected_run_version": 1,
            "expected_baseline_revision": 0,
            "confirmed_by": "payload-spoof",
            "signature_evidence_sha256": "c" * 64,
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "monitoring_reauthentication_required"
    assert repository.list_runs("project-1") == ()


def test_daily_confirm_requires_signature_after_reauthentication(
    tmp_path: Path,
):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "confirm-signature")),
        resolver=lambda _request: _principal(),
    )
    response = client.post(
        "/api/projects/project-1/monitoring/daily-runs/run-missing/confirm",
        json={
            "expected_run_version": 1,
            "expected_baseline_revision": 0,
            "confirmed_by": "payload-spoof",
            "reauthenticated": True,
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "monitoring_electronic_signature_required"
    assert repository.list_runs("project-1") == ()


def test_daily_confirm_with_evidence_reaches_existing_not_found_path(
    tmp_path: Path,
):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "confirm-valid")),
        resolver=lambda _request: _principal(),
    )
    response = client.post(
        "/api/projects/project-1/monitoring/daily-runs/run-missing/confirm",
        json={
            "expected_run_version": 1,
            "expected_baseline_revision": 0,
            "confirmed_by": "payload-spoof",
            "reauthenticated": True,
            "signature_evidence_sha256": "d" * 64,
        },
    )
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "monitoring_run_not_found"
    assert repository.list_runs("project-1") == ()


def test_daily_confirm_rejects_malformed_signature_evidence(
    tmp_path: Path,
):
    client, repository = _production_client(
        SimpleNamespace(name=str(tmp_path / "confirm-invalid")),
        resolver=lambda _request: _principal(),
    )
    response = client.post(
        "/api/projects/project-1/monitoring/daily-runs/run-missing/confirm",
        json={
            "expected_run_version": 1,
            "expected_baseline_revision": 0,
            "confirmed_by": "payload-spoof",
            "reauthenticated": True,
            "signature_evidence_sha256": "not-a-sha",
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["detail"]["code"] == "monitoring_authorization_request_invalid"
    assert repository.list_runs("project-1") == ()


def test_prepare_list_get_and_replay_daily_run():
    with TemporaryDirectory() as path:
        temporary = SimpleNamespace(name=path)
        client, _ = _client(temporary)
        request = {
            "batch_id": "batch-1",
            "idempotency_key": "prepare-1",
            "actor": "medical_manager",
        }

        created = client.post(
            "/api/projects/alias-1/monitoring/daily-runs",
            json=request,
        )
        replay = client.post(
            "/api/projects/alias-1/monitoring/daily-runs",
            json=request,
        )

        assert created.status_code == 201
        assert created.json()["project_id"] == "project-1"
        assert created.json()["replayed"] is False
        assert replay.json()["replayed"] is True
        run_id = created.json()["run"]["run_id"]
        listed = client.get("/api/projects/alias-1/monitoring/daily-runs")
        detail = client.get(
            f"/api/projects/alias-1/monitoring/daily-runs/{run_id}"
        )
        assert listed.status_code == 200
        assert listed.json()["active_run"]["run_id"] == run_id
        assert len(listed.json()["items"]) == 1
        assert detail.status_code == 200
        assert detail.json()["run"]["batch_id"] == "batch-1"


def test_readiness_is_read_only_and_uses_canonical_project():
    with TemporaryDirectory() as path:
        temporary = SimpleNamespace(name=path)
        client, repository = _client(temporary)
        response = client.get(
            "/api/projects/alias-1/monitoring/daily-runs/readiness",
            params={"batch_id": "blocked"},
        )
        assert response.status_code == 200
        assert response.json()["project_id"] == "project-1"
        assert response.json()["ready"] is False
        assert response.json()["next_action"] == "confirm_mapping"
        assert repository.list_runs("project-1") == ()


def test_prepare_returns_stable_error_contract():
    with TemporaryDirectory() as path:
        temporary = SimpleNamespace(name=path)
        client, _ = _client(temporary)
        response = client.post(
            "/api/projects/project-1/monitoring/daily-runs",
            json={
                "batch_id": "missing",
                "idempotency_key": "missing-1",
                "actor": "medical_manager",
            },
        )
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "monitoring_batch_not_found"


def test_prepare_propagates_rule_pack_identity_drift_error_contract():
    with TemporaryDirectory() as path:
        temporary = SimpleNamespace(name=path)
        client, repository = _client(temporary)
        response = client.post(
            "/api/projects/project-1/monitoring/daily-runs",
            json={
                "batch_id": "drifted",
                "idempotency_key": "drifted-1",
                "actor": "medical_manager",
            },
        )
        assert response.status_code == 409
        assert (
            response.json()["detail"]["code"]
            == "monitoring_rule_pack_identity_drift"
        )
        assert repository.list_runs("project-1") == ()


def test_process_endpoint_returns_product_progress_not_internal_events():
    with TemporaryDirectory() as path:
        temporary = SimpleNamespace(name=path)
        client, _ = _client(temporary)
        created = client.post(
            "/api/projects/project-1/monitoring/daily-runs",
            json={
                "batch_id": "batch-1",
                "idempotency_key": "prepare-1",
                "actor": "medical_manager",
            },
        ).json()
        response = client.post(
            (
                "/api/projects/project-1/monitoring/daily-runs/"
                f"{created['run']['run_id']}/process"
            ),
            json={
                "expected_version": created["run"]["version"],
                "owner": "monitoring-worker",
            },
        )
        assert response.status_code == 200
        assert response.json()["next_action"] == "run_rules"
        assert "events" not in response.json()


def test_execute_rules_endpoint_returns_compact_product_progress():
    with TemporaryDirectory() as path:
        temporary = SimpleNamespace(name=path)
        client, _ = _client(temporary)
        created = client.post(
            "/api/projects/project-1/monitoring/daily-runs",
            json={
                "batch_id": "batch-1",
                "idempotency_key": "prepare-rules",
                "actor": "medical_manager",
            },
        ).json()
        response = client.post(
            (
                "/api/projects/project-1/monitoring/daily-runs/"
                f"{created['run']['run_id']}/execute-rules"
            ),
            json={
                "expected_version": created["run"]["version"],
                "owner": "monitoring-worker",
            },
        )
        assert response.status_code == 200
        assert response.json()["next_action"] == "run_independent_ai"
        assert response.json()["rule_result"]["candidate_count"] == 2
        assert "events" not in response.json()


def test_record_mode_run_exposes_frozen_rule_identity_in_contract():
    with TemporaryDirectory() as path:
        temporary = SimpleNamespace(name=path)
        client, _ = _client(temporary)
        created = client.post(
            "/api/projects/project-1/monitoring/daily-runs",
            json={
                "batch_id": "record",
                "idempotency_key": "record-prepare-1",
                "actor": "medical_manager",
            },
        )

        assert created.status_code == 201
        run = created.json()["run"]
        assert run["rule_resolution_mode"] == "record_applicability"
        assert run["rule_pack_revision"] == ""
        assert run["rule_identity_sha256"] == "e" * 64

        detail = client.get(
            "/api/projects/project-1/monitoring/daily-runs/" f"{run['run_id']}"
        )
        assert detail.status_code == 200
        assert detail.json()["run"]["rule_identity_sha256"] == "e" * 64


def test_ai_progress_exposes_read_only_source_bound_candidate_projection():
    content_hash = "a" * 64
    evidence = MonitoringAiEvidence(
        evidence_id="evidence-1",
        source_entry_id="listing-1",
        source_content_sha256=content_hash,
        locator="AE!row-2",
        quote="恶心，持续两天",
        raw_fields={"domain": "AE", "subject_id": "S001"},
        input_revision_sha256=content_hash,
    )
    claim = MonitoringAiClaim(
        claim_id="claim-1",
        kind=MonitoringAiClaimKind.FACT,
        text="AE 记录包含恶心。",
        confidence=0.9,
        evidence_ids=("evidence-1",),
    )
    candidate = MonitoringAiCandidate(
        candidate_id="candidate-1",
        job_id="job-1",
        project_id="project-1",
        task_type=MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
        candidate_type="cross_table_clue",
        title="跨表线索",
        text="请医学监查员核对 AE 与给药记录。",
        claims=(claim,),
        evidence=(evidence,),
        status=MonitoringAiCandidateStatus.PROPOSED,
        input_revision_sha256=content_hash,
        prompt_version="daily-run-ai-v1",
        created_at=datetime.now(timezone.utc),
    )
    progress = MonitoringDailyAiProgress(
        project_id="project-1",
        run_id="run-1",
        status="completed",
        total=1,
        queued=0,
        running=0,
        completed=1,
        failed=0,
        candidates=(MonitoringDailyAiReviewCandidate(
            subject_id="S001",
            job_id="job-1",
            candidate=candidate,
        ),),
        failures=(),
    )

    payload = _ai_progress_dict(progress)
    assert payload["candidate_count"] == 1
    assert payload["candidates"][0]["subject_id"] == "S001"
    assert payload["candidates"][0]["candidate"]["candidate_id"] == "candidate-1"
    assert payload["candidates"][0]["candidate"]["evidence"][0]["locator"] == "AE!row-2"
    assert payload["candidates"][0]["candidate"]["confidence_summary"]["requires_user_review"] is True
