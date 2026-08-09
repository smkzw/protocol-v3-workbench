from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.api.app.ai_gateway import AiPromptEnvelope
from services.api.app.monitoring_ai_repository import MonitoringAiRepository
from services.api.app.monitoring_ai_contracts import (
    MonitoringAiInputRevision,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
)
from services.api.app.monitoring_ai_router import (
    FieldMappingStartRequest,
    MappingDraftConfirmRequest,
    MappingDraftFieldEditRequest,
    MappingDraftAssembleRequest,
    MappingRunAdoptRequest,
    RiskSemanticTaskStartRequest,
    SemanticTaskStartRequest,
    create_monitoring_ai_router,
    current_monitoring_ai_revision,
    monitoring_input_revision_for_profile_identity,
)
from services.api.app.monitoring_ai_field_profiler import (
    MonitoringAIFieldProfiler,
)
from services.api.app.monitoring_ai_source_packet import MonitoringAiSourcePacket
from services.api.app.monitoring_ai_risk_packet import MonitoringAiRiskPacket
from services.api.app.monitoring_ai_service import (
    MonitoringAiRuntimeBinding,
    MonitoringAiService,
)
from services.api.app.monitoring_batch_repository import (
    BatchRecord,
    DiffReadyBatch,
    FieldProfileBatchIdentity,
    FieldProfileSourceBindingIdentity,
    MonitoringBatchRepositoryError,
    NormalizedRow,
)
from services.api.app.monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
)
from services.api.app.monitoring_mapping_activation import (
    MonitoringMappingActivationService,
)


SOURCE_HASH = "a" * 64


def test_monitoring_ai_router_numeric_requests_reject_booleans() -> None:
    requests = (
        lambda: FieldMappingStartRequest(batch_id="batch-api", chunk_size=True),
        lambda: SemanticTaskStartRequest(
            task_type="risk_evidence_summary",
            business_key="semantic-api",
            source_ids=["source-1"],
            context={"field": "value"},
            max_attempts=True,
        ),
        lambda: RiskSemanticTaskStartRequest(
            task_type="risk_evidence_summary",
            business_key="risk-api",
            risk_instance_id="risk-1",
            max_attempts=True,
        ),
        lambda: MappingDraftFieldEditRequest(
            domain="AE",
            source_field="AETERM",
            patch={},
            expected_version=True,
            idempotency_key="edit-1",
        ),
        lambda: MappingDraftConfirmRequest(
            expected_version=True,
            confirmation_reason="confirm",
            idempotency_key="confirm-1",
        ),
        lambda: MappingDraftConfirmRequest(
            expected_version=1,
            expected_project_version=True,
            confirmation_reason="confirm",
            idempotency_key="confirm-2",
        ),
    )
    for build in requests:
        with pytest.raises(ValidationError):
            build()


@pytest.mark.parametrize("digest", (f" {SOURCE_HASH}", SOURCE_HASH.upper(), "g" * 64, 123))
def test_monitoring_ai_router_mapping_digest_requests_reject_noncanonical_shapes(
    digest: object,
) -> None:
    with pytest.raises(ValidationError):
        MappingDraftAssembleRequest(
            batch_id="batch-api",
            full_profile_sha256=digest,
        )
    with pytest.raises(ValidationError):
        MappingRunAdoptRequest(
            batch_id="batch-api",
            full_profile_sha256=digest,
            reason="采用完整字段建议。",
        )


@pytest.mark.parametrize("retry_failed", (0, 1, "false", "true"))
def test_monitoring_ai_router_retry_flag_rejects_bool_like_values(
    retry_failed: object,
) -> None:
    with pytest.raises(ValidationError):
        FieldMappingStartRequest(
            batch_id="batch-api",
            retry_failed=retry_failed,
        )


class FakeBatchRepository:
    def __init__(self):
        self.version = 1
        self.profile_load_count = 0
        self.mapping_revision = None
        self.source_content_sha256 = SOURCE_HASH
        self.source_binding_identity_sha256 = "d" * 64
        self.identity_sha256 = "e" * 64

    def get_batch(self, batch_id: str) -> BatchRecord:
        if batch_id != "batch-api":
            raise MonitoringBatchRepositoryError("not found")
        return BatchRecord(
            batch_id=batch_id,
            project_id="project-api",
            state="frozen",
            version=self.version,
            expected_domains=("AE",),
            active_mapping_revision=None,
            full_snapshot_proof={"confirmed": True},
            created_at="2026-07-29T00:00:00+00:00",
            updated_at="2026-07-29T00:00:00+00:00",
            frozen_at="2026-07-29T00:00:00+00:00",
        )

    def load_diff_ready_batch(self, batch_id: str) -> DiffReadyBatch:
        if batch_id != "batch-api":
            raise MonitoringBatchRepositoryError("not found")
        return DiffReadyBatch(
            batch_id=batch_id,
            project_id="project-api",
            state="frozen",
            version=self.version,
            expected_domains=("AE",),
            mapping_revision=None,
            source_bindings=(("source-api", SOURCE_HASH),),
            source_hashes=(SOURCE_HASH,),
            rows=(
                NormalizedRow(
                    business_key="AE|001",
                    domain="AE",
                    data={
                        "SUBJID": "001",
                        "AETERM": "头痛",
                        "AESEV": "轻度",
                    },
                    source_locator={"sheet": "AE", "row": 2},
                    row_fingerprint="b" * 64,
                ),
            ),
        )

    def load_profile_ready_batch(self, batch_id: str) -> DiffReadyBatch:
        self.profile_load_count += 1
        return self.load_diff_ready_batch(batch_id)

    def load_field_profile_cache_identity(
        self,
        batch_id: str,
    ) -> FieldProfileBatchIdentity:
        if batch_id != "batch-api":
            raise MonitoringBatchRepositoryError("not found")
        binding = FieldProfileSourceBindingIdentity(
            source_id="source-registration-api",
            source_entry_id="source-api",
            source_content_sha256=self.source_content_sha256,
            binding_revision=1,
            binding_sha256="c" * 64,
        )
        return FieldProfileBatchIdentity(
            schema_version="monitoring_field_profile_batch_identity.v1",
            batch_id=batch_id,
            project_id="project-api",
            state="frozen",
            batch_version=self.version,
            expected_domains=("AE",),
            mapping_revision=self.mapping_revision,
            source_bindings=(binding,),
            row_count=1,
            row_set_sha256="a" * 64,
            schema_field_count=0,
            schema_fields_sha256="b" * 64,
            content_identity_sha256="f" * 64,
            source_binding_identity_sha256=(
                self.source_binding_identity_sha256
            ),
            identity_sha256=self.identity_sha256,
        )


class FakeProvider:
    provider_name = "test-provider"
    model_name = "test-model"
    expected_response_model = "test-model"
    response_model = "test-model"
    transport_name = "openai_compatible"

    def run(self, envelope: AiPromptEnvelope) -> dict[str, Any]:
        if (
            envelope.payload["monitoring_task_type"]
            == "protocol_clause_structuring"
        ):
            evidence_ids = [
                item["evidence_id"]
                for item in envelope.payload["input_payload"]["evidence_packet"]
            ]
            return {
                "schema_version": "monitoring_ai_v1",
                "task_id": envelope.task_id,
                "task_type": "protocol_clause_structuring",
                "input_revision_sha256": envelope.payload[
                    "input_revision_sha256"
                ],
                "candidates": [
                    {
                        "candidate_type": "protocol_clause_structure",
                        "title": "禁用药条款结构化候选",
                        "text": "方案要求筛选期停用指定药物。",
                        "structured_payload": {
                            "clause_id": "clause-api-001",
                            "fact_type": "concomitant_medication_prohibited",
                            "subject_scope": "所有拟入组受试者",
                            "conditions": ["筛选期正在使用指定药物"],
                            "time_windows": ["随机前完成洗脱"],
                            "thresholds": [],
                            "exceptions": [],
                            "required_actions": ["核对停药与随机日期"],
                            "evidence_ids": evidence_ids,
                        },
                        "claims": [
                            {
                                "claim_id": "claim-api-001",
                                "kind": "fact",
                                "text": "方案原文包含随机前洗脱要求。",
                                "confidence": 0.9,
                                "uncertainty": "",
                                "user_action": "核对具体药物和洗脱时长。",
                                "evidence_ids": evidence_ids,
                            }
                        ],
                    }
                ],
            }
        if envelope.payload["monitoring_task_type"] == "risk_evidence_summary":
            evidence_ids = [
                item["evidence_id"]
                for item in envelope.payload["input_payload"]["evidence_packet"]
            ]
            return {
                "schema_version": "monitoring_ai_v1",
                "task_id": envelope.task_id,
                "task_type": "risk_evidence_summary",
                "input_revision_sha256": envelope.payload[
                    "input_revision_sha256"
                ],
                "candidates": [
                    {
                        "candidate_type": "risk_evidence_summary",
                        "title": "风险证据摘要候选",
                        "text": "原始用药记录与方案禁用药条款需结合复核。",
                        "structured_payload": {
                            "risk_id": "current-risk",
                            "facts": ["记录显示受试者使用了相关合并用药。"],
                            "inferences": ["用药时间可能与禁用窗口重叠。"],
                            "data_gaps": ["尚需确认实际停药日期。"],
                            "recommended_actions": ["核对原始病历和停药日期。"],
                            "evidence_ids": evidence_ids,
                        },
                        "claims": [
                            {
                                "claim_id": "risk-claim-api-001",
                                "kind": "inference",
                                "text": "用药时间可能与方案禁用窗口重叠。",
                                "confidence": 0.8,
                                "uncertainty": "实际停药日期尚待核对。",
                                "user_action": "核对原始病历和停药日期。",
                                "evidence_ids": evidence_ids,
                            }
                        ],
                    }
                ],
            }
        profile = envelope.payload["input_payload"]["field_profile"]
        source = envelope.payload["authorized_source_pairs"][0]
        mappings = []
        evidence = []
        for index, field in enumerate(profile["fields"], start=1):
            evidence_id = f"evidence-{index}"
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "source_entry_id": source["source_entry_id"],
                    "source_content_sha256": source["source_content_sha256"],
                    "locator": f"{field['domain']}.{field['field']}",
                    "quote": "",
                    "raw_fields": {
                        "domain": field["domain"],
                        "field": field["field"],
                        "inferred_type": field["inferred_type"],
                    },
                }
            )
            mappings.append(
                {
                    "domain": field["domain"],
                    "source_field": field["field"],
                    "recommended_role": f"source_{field['field'].lower()}",
                    "field_kind": "source_collected",
                    "confidence": 0.8,
                    "uncertainty": "需结合项目数据字典确认。",
                    "user_action": "确认字段角色。",
                    "related_fields": [],
                    "evidence_ids": [evidence_id],
                }
            )
        return {
            "schema_version": "monitoring_ai_v1",
            "task_id": envelope.task_id,
            "task_type": envelope.payload["monitoring_task_type"],
            "input_revision_sha256": envelope.payload["input_revision_sha256"],
            "candidates": [
                {
                    "candidate_type": "listing_field_mapping_set",
                    "title": "字段映射建议",
                    "text": "根据冻结批次字段画像生成。",
                    "structured_payload": {"field_mappings": mappings},
                    "claims": [
                        {
                            "claim_id": "claim-1",
                            "kind": "recommendation",
                            "text": "建议确认字段映射。",
                            "confidence": 0.8,
                            "uncertainty": "尚未结合项目数据字典。",
                            "user_action": "逐项确认。",
                            "evidence_ids": [item["evidence_id"] for item in evidence],
                        }
                    ],
                    "evidence": evidence,
                }
            ],
        }


def _service(
    tmp_path: Path,
    batch_repository: FakeBatchRepository,
) -> tuple[MonitoringAiRepository, MonitoringAiService]:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    service: MonitoringAiService

    def resolve(job):
        return current_monitoring_ai_revision(
            repository,
            batch_repository,
            job,
        )

    service = MonitoringAiService(
        repository,
        runtime_resolver=lambda: MonitoringAiRuntimeBinding(
            profile_id="independent-ai-test",
            provider="test-provider",
            model="test-model",
            env={
                "WORKBENCH_AI_PROVIDER": "test-provider",
                "WORKBENCH_AI_TRANSPORT": "openai_compatible",
                "WORKBENCH_AI_BASE_URL": "https://example.invalid/v1",
                "WORKBENCH_AI_API_KEY": "test-key",
                "WORKBENCH_AI_MODEL": "test-model",
                "WORKBENCH_AI_EXPECTED_RESPONSE_MODEL": "test-model",
                "WORKBENCH_AI_DEPLOYMENT_PROFILE": "local_private_clinical",
            },
        ),
        provider_factory=lambda _env: FakeProvider(),
        current_revision_resolver=resolve,
    )
    return repository, service


def test_field_mapping_api_submits_runs_and_accepts_candidate(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    mapping_repository = MonitoringMappingDraftRepository(repository.path)
    activation_service = MonitoringMappingActivationService(mapping_repository)
    wake_count = {"value": 0}
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
            mapping_repository=mapping_repository,
            mapping_activation_service=activation_service,
            worker_wake=lambda: wake_count.__setitem__(
                "value",
                wake_count["value"] + 1,
            ),
        )
    )
    client = TestClient(app)

    started = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={"batch_id": "batch-api", "chunk_size": 12},
    )

    assert started.status_code == 202, started.text
    payload = started.json()
    assert payload["field_count"] == 3
    assert payload["job_count"] == 1
    assert payload["jobs"][0]["status"] == "queued"
    assert wake_count["value"] == 1
    status_endpoint = (
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-status?batch_id=batch-api"
    )
    initial_status = client.get(status_endpoint)
    assert initial_status.status_code == 200, initial_status.text
    assert initial_status.json()["job_count"] == 1
    assert initial_status.json()["field_count"] == 3
    assert initial_status.json()["draft"] is None
    assert initial_status.json()["job_details"][0]["candidates"] == []
    assert batch_repository.profile_load_count == 1

    oversized = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={"batch_id": "batch-api", "chunk_size": 13},
    )
    assert oversized.status_code == 422

    result = service.run_next("api-test-worker")
    assert result.processed is True
    assert result.job is not None
    assert batch_repository.profile_load_count == 1
    job_id = result.job.job_id

    details = client.get(
        f"/api/projects/project-api/modules/medical-monitoring/ai/jobs/{job_id}"
    )
    assert details.status_code == 200
    candidate = details.json()["candidates"][0]
    assert candidate["status"] == "proposed"
    completed_status = client.get(status_endpoint)
    assert completed_status.status_code == 200
    assert len(completed_status.json()["job_details"][0]["candidates"]) == 1

    assembled = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-runs/adopt",
        json={
            "batch_id": "batch-api",
            "full_profile_sha256": payload["profile_sha256"],
            "actor": "medical_manager",
            "reason": "采用完整字段建议进入校对。",
        },
    )
    assert assembled.status_code == 201, assembled.text
    assert repository.candidates(
        "project-api",
        job_id,
    )[0].status.value == "accepted"
    draft = assembled.json()
    assert draft["status"] == "draft"
    assert draft["confirmed_revision_id"] == ""
    assert len(draft["fields"]) == 3
    draft_status = client.get(status_endpoint)
    assert draft_status.status_code == 200
    assert draft_status.json()["draft"]["draft_id"] == draft["draft_id"]

    edited = client.patch(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        f"mapping-drafts/{draft['draft_id']}/field",
        json={
            "domain": "AE",
            "source_field": "AETERM",
            "patch": {
                "recommended_role": "adverse_event_reported_term",
                "uncertainty": "已结合项目数据字典核对。",
            },
            "expected_version": draft["version"],
            "actor": "medical_manager",
            "idempotency_key": "edit-aeterm-v1",
        },
    )
    assert edited.status_code == 200, edited.text
    edited_draft = edited.json()
    assert edited_draft["version"] == 2

    confirmed = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        f"mapping-drafts/{draft['draft_id']}/confirm",
        json={
            "expected_version": edited_draft["version"],
            "confirmed_by": "medical_manager",
            "confirmation_reason": "已核对全部字段角色和来源。",
            "idempotency_key": "confirm-batch-api-v1",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    revision = confirmed.json()
    assert revision["mapping_revision"].startswith("monmaprev_")
    assert revision["activation"]["state"]["mapping_revision"] == revision[
        "mapping_revision"
    ]
    assert revision["activation"]["state"]["project_version"] == 1
    confirmed_status = client.get(status_endpoint)
    assert confirmed_status.status_code == 200
    assert confirmed_status.json()["draft"]["status"] == "confirmed"
    assert (
        confirmed_status.json()["draft"]["confirmed_revision_id"]
        == revision["mapping_revision"]
    )

    read_back = client.get(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        f"mapping-revisions/{revision['mapping_revision']}"
    )
    assert read_back.status_code == 200
    assert read_back.json() == {
        key: value for key, value in revision.items() if key != "activation"
    }
    active = client.get(
        "/api/projects/project-api/modules/medical-monitoring/ai/active-mapping"
    )
    assert active.status_code == 200
    assert active.json()["mapping_revision"] == revision["mapping_revision"]


def test_repeated_formal_field_mapping_start_reuses_verified_profile_cache(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    batch_repository.object_root = tmp_path / "batch-objects"
    repository, service = _service(tmp_path, batch_repository)
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    endpoint = (
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs"
    )

    first = client.post(endpoint, json={"batch_id": "batch-api"})
    second = client.post(endpoint, json={"batch_id": "batch-api"})

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text
    assert first.json()["profile_sha256"] == second.json()["profile_sha256"]
    assert first.json()["jobs"] == second.json()["jobs"]
    assert batch_repository.profile_load_count == 1
    stored = repository.get(
        "project-api",
        first.json()["jobs"][0]["job_id"],
    )
    assert stored.input_revision.source_binding_revision == (
        "source-binding:" + "d" * 64
    )


def test_formal_start_reuses_compatible_pre_binding_contract_and_candidates(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    snapshot = MonitoringAIFieldProfiler(
        batch_repository,
    ).profile_batch("batch-api")
    identity = batch_repository.load_field_profile_cache_identity("batch-api")
    legacy_jobs = service.submit_listing_field_mapping_chunks(
        project_id="project-api",
        input_revision=monitoring_input_revision_for_profile_identity(
            identity,
            include_binding_identity=False,
        ),
        field_profile=snapshot.to_ai_payload(),
    )
    completed = service.run_next("legacy-mapping-worker")
    assert completed.processed is True
    legacy_job = repository.get("project-api", legacy_jobs[0].job_id)
    assert legacy_job.status.value == "completed"
    assert legacy_job.input_revision.source_binding_revision == ""
    assert len(repository.candidates("project-api", legacy_job.job_id)) == 1

    modern_jobs = service.submit_listing_field_mapping_chunks(
        project_id="project-api",
        input_revision=monitoring_input_revision_for_profile_identity(identity),
        field_profile=snapshot.to_ai_payload(),
    )
    assert modern_jobs[0].job_id != legacy_job.job_id
    assert repository.get(
        "project-api",
        legacy_job.job_id,
    ).status.value == "stale_input"

    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    status_endpoint = (
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-status?batch_id=batch-api"
    )
    status_before_retry = client.get(status_endpoint)
    assert status_before_retry.status_code == 200
    assert status_before_retry.json()["job_count"] == 1
    assert (
        status_before_retry.json()["job_details"][0]["job"]["job_id"]
        == legacy_job.job_id
    )

    restarted = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={
            "batch_id": "batch-api",
            "chunk_size": 12,
            "retry_failed": True,
        },
    )
    assert restarted.status_code == 202, restarted.text
    assert restarted.json()["job_count"] == 1
    assert restarted.json()["jobs"][0]["job_id"] == legacy_job.job_id
    assert restarted.json()["jobs"][0]["status"] == "completed"
    assert repository.get(
        "project-api",
        modern_jobs[0].job_id,
    ).status.value == "stale_input"
    restored_candidates = repository.candidates(
        "project-api",
        legacy_job.job_id,
    )
    assert len(restored_candidates) == 1
    assert restored_candidates[0].status.value == "proposed"

    status_after_retry = client.get(status_endpoint)
    assert status_after_retry.status_code == 200
    assert len(
        status_after_retry.json()["job_details"][0]["candidates"]
    ) == 1


def test_pre_binding_contract_is_not_reused_after_batch_revision_changes(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    snapshot = MonitoringAIFieldProfiler(
        batch_repository,
    ).profile_batch("batch-api")
    identity = batch_repository.load_field_profile_cache_identity("batch-api")
    legacy_jobs = service.submit_listing_field_mapping_chunks(
        project_id="project-api",
        input_revision=monitoring_input_revision_for_profile_identity(
            identity,
            include_binding_identity=False,
        ),
        field_profile=snapshot.to_ai_payload(),
    )
    batch_repository.version = 2
    batch_repository.identity_sha256 = "9" * 64

    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    started = TestClient(app).post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={"batch_id": "batch-api"},
    )

    assert started.status_code == 202, started.text
    assert started.json()["jobs"][0]["job_id"] != legacy_jobs[0].job_id
    current = repository.get(
        "project-api",
        started.json()["jobs"][0]["job_id"],
    )
    assert current.input_revision.batch_revision == "batch-api:v2"
    assert current.input_revision.source_binding_revision == (
        "source-binding:" + "d" * 64
    )


def test_field_mapping_status_excludes_obsolete_revision_hash(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    started = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={"batch_id": "batch-api", "chunk_size": 12},
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["jobs"][0]["job_id"]
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_jobs
            SET status = ?, input_revision_sha256 = ?
            WHERE project_id = ? AND job_id = ?
            """,
            ("stale_input", "f" * 64, "project-api", job_id),
        )

    status = client.get(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-status?batch_id=batch-api"
    )

    assert status.status_code == 200, status.text
    assert status.json()["job_count"] == 0
    assert status.json()["job_details"] == []


def test_retry_failed_mapping_recovers_expired_final_leases_first(
    tmp_path: Path,
    monkeypatch,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    wake_count = {"value": 0}
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
            worker_wake=lambda: wake_count.__setitem__(
                "value",
                wake_count["value"] + 1,
            ),
        )
    )
    client = TestClient(app)
    endpoint = (
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs"
    )
    started = client.post(endpoint, json={"batch_id": "batch-api"})
    assert started.status_code == 202
    job_id = started.json()["jobs"][0]["job_id"]
    running = repository.claim_next("lost-worker")
    assert running is not None and running.job_id == job_id
    repository.fail(
        running,
        owner="lost-worker",
        failure_code="provider_unavailable",
        failure_message="provider unavailable",
        retryable=False,
    )

    calls: list[str] = []
    original = repository.expire_exhausted_leases

    def observe_recovery(*, project_id: str = "") -> int:
        calls.append(project_id)
        return original(project_id=project_id)

    monkeypatch.setattr(
        repository,
        "expire_exhausted_leases",
        observe_recovery,
    )
    retried = client.post(
        endpoint,
        json={
            "batch_id": "batch-api",
            "chunk_size": 12,
            "retry_failed": True,
        },
    )

    assert retried.status_code == 202, retried.text
    assert calls == ["project-api"]
    assert retried.json()["jobs"][0]["status"] == "queued"
    assert repository.get("project-api", job_id).status.value == "queued"
    assert wake_count["value"] == 2


def test_candidate_decision_fails_when_frozen_batch_revision_changes(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    started = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={"batch_id": "batch-api"},
    )
    job_id = started.json()["jobs"][0]["job_id"]
    service.run_next("api-test-worker")
    candidate = repository.candidates("project-api", job_id)[0]
    batch_repository.version = 2

    response = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/candidates/"
        f"{candidate.candidate_id}/decision",
        json={"decision": "accepted", "actor": "medical_manager"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "monitoring_ai_candidate_stale"


def test_current_listing_revision_uses_lightweight_binding_identity(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    started = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={"batch_id": "batch-api"},
    )
    assert started.status_code == 202, started.text
    job = repository.get(
        "project-api",
        started.json()["jobs"][0]["job_id"],
    )
    initial_profile_loads = batch_repository.profile_load_count

    assert (
        current_monitoring_ai_revision(
            repository,
            batch_repository,
            job,
        )
        == job.input_revision_sha256
    )
    assert batch_repository.profile_load_count == initial_profile_loads

    batch_repository.source_binding_identity_sha256 = "1" * 64
    batch_repository.identity_sha256 = "2" * 64
    assert (
        current_monitoring_ai_revision(
            repository,
            batch_repository,
            job,
        )
        != job.input_revision_sha256
    )
    assert batch_repository.profile_load_count == initial_profile_loads


@pytest.mark.parametrize(
    "profile_sha256",
    [f" {SOURCE_HASH}", f"{SOURCE_HASH} ", SOURCE_HASH.upper(), 123],
)
def test_current_listing_revision_rejects_noncanonical_persisted_profile_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_sha256: object,
) -> None:
    batch_repository = FakeBatchRepository()
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    base_revision = MonitoringAiInputRevision(
        project_id="project-api",
        batch_revision="batch-revision-a",
    )
    job = SimpleNamespace(
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
        project_id="project-api",
        job_id="job-listing-digest-shape",
        input_revision=base_revision,
        input_revision_sha256=base_revision.revision_sha256,
    )
    monkeypatch.setattr(
        repository,
        "input_payload",
        lambda _project_id, _job_id: {
            "field_profile": {
                "batch_id": "batch-api",
                "profile_sha256": profile_sha256,
            },
        },
    )

    assert current_monitoring_ai_revision(repository, batch_repository, job) == ""

def test_monitoring_ai_api_does_not_cross_project_boundary(tmp_path: Path) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    client = TestClient(app)

    response = client.post(
        "/api/projects/another-project/modules/medical-monitoring/ai/"
        "field-mapping-jobs",
        json={"batch_id": "batch-api"},
    )

    assert response.status_code == 404
    assert repository.list_jobs("another-project") == ()


def test_semantic_api_uses_server_resolved_evidence_and_runs(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    revision = MonitoringAiInputRevision(
        project_id="project-api",
        protocol_version="protocol-registry-v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="protocol-source",
                source_content_sha256=SOURCE_HASH,
            ),
        ),
    )
    packet = MonitoringAiSourcePacket(
        input_revision=revision,
        source_ids=("protocol-span-1",),
        evidence_packet=(
            {
                "evidence_id": "protocol-evidence-1",
                "source_entry_id": "protocol-source",
                "source_content_sha256": SOURCE_HASH,
                "locator": "docx:paragraph:42",
                "quote": "随机前应停用方案规定的禁用药物。",
                "raw_fields": {
                    "source_id": "protocol-span-1",
                    "source_type": "protocol_docx_paragraph",
                },
            },
        ),
    )
    resolver_calls: list[tuple[str, list[str]]] = []

    def resolve_source_packet(
        project_id: str,
        source_ids: list[str],
    ) -> MonitoringAiSourcePacket:
        resolver_calls.append((project_id, source_ids))
        return packet

    wake_count = {"value": 0}
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
            source_packet_resolver=resolve_source_packet,
            worker_wake=lambda: wake_count.__setitem__(
                "value",
                wake_count["value"] + 1,
            ),
        )
    )
    client = TestClient(app)

    started = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/semantic-jobs",
        json={
            "task_type": "protocol_clause_structuring",
            "business_key": "protocol-clause-api-001",
            "source_ids": ["protocol-span-1"],
            "context": {"purpose": "禁用药条款结构化"},
        },
    )

    assert started.status_code == 202, started.text
    assert started.json()["status"] == "queued"
    assert resolver_calls == [("project-api", ["protocol-span-1"])]
    assert wake_count["value"] == 1

    result = service.run_next("semantic-api-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.status.value == "completed"
    candidates = repository.candidates("project-api", result.job.job_id)
    assert len(candidates) == 1
    assert candidates[0].evidence[0].quote == (
        "随机前应停用方案规定的禁用药物。"
    )
    assert candidates[0].evidence[0].locator == "docx:paragraph:42"


def test_evidence_span_search_api_is_read_only_bounded_and_project_scoped(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    calls: list[tuple[str, str, list[str], int]] = []

    def searcher(
        project_id: str,
        entry_id: str,
        query: list[str],
        *,
        limit: int,
    ) -> tuple[dict[str, Any], ...]:
        calls.append((project_id, entry_id, query, limit))
        if project_id != "project-api":
            raise KeyError(entry_id)
        return (
            {
                "source_id": "protocol-span-250",
                "source_entry_id": entry_id,
                "locator": "docx:paragraph:250",
                "text": "随机前停用方案规定的禁用药物。",
                "score": 2002,
                "matched_keywords": ["停用", "禁用药"],
                "match_reason": "命中关键词：停用、禁用药；共出现 2 次",
            },
        )

    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
            source_span_searcher=searcher,
        )
    )
    client = TestClient(app)
    endpoint = (
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "evidence-spans/search"
    )

    response = client.get(
        endpoint,
        params=[
            ("entry_id", "src_protocol_001"),
            ("query", "停用"),
            ("query", "禁用药"),
            ("limit", "20"),
        ],
    )

    assert response.status_code == 200, response.text
    assert response.json()["result_count"] == 1
    assert response.json()["results"][0]["source_id"] == "protocol-span-250"
    assert calls == [
        ("project-api", "src_protocol_001", ["停用", "禁用药"], 20)
    ]
    assert client.post(
        endpoint,
        params={
            "entry_id": "src_protocol_001",
            "query": "停用",
        },
    ).status_code == 405
    assert client.get(
        endpoint,
        params={
            "entry_id": "src_protocol_001",
            "query": "停用",
            "limit": 201,
        },
    ).status_code == 422


def test_semantic_api_requires_resolver_and_rejects_mapping_task(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
        )
    )
    client = TestClient(app)
    endpoint = (
        "/api/projects/project-api/modules/medical-monitoring/ai/semantic-jobs"
    )

    unavailable = client.post(
        endpoint,
        json={
            "task_type": "risk_evidence_summary",
            "business_key": "risk-api-001",
            "source_ids": ["risk-source-1"],
            "context": {"risk_id": "risk-api-001"},
        },
    )
    invalid_task = client.post(
        endpoint,
        json={
            "task_type": "listing_field_mapping",
            "business_key": "mapping-api-001",
            "source_ids": ["source-1"],
            "context": {"purpose": "field mapping"},
        },
    )

    assert unavailable.status_code == 503
    assert (
        unavailable.json()["detail"]["code"]
        == "monitoring_ai_source_resolver_unavailable"
    )
    assert invalid_task.status_code == 422


def test_risk_api_uses_current_risk_packet_and_rejects_wrong_task(
    tmp_path: Path,
) -> None:
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    revision = MonitoringAiInputRevision(
        project_id="project-api",
        risk_snapshot_revision="risk-snapshot-v1",
        rule_pack_revision="rule-pack-v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="risk-evidence-source",
                source_content_sha256=SOURCE_HASH,
            ),
        ),
    )
    packet = MonitoringAiRiskPacket(
        input_revision=revision,
        risk_instance_id="risk-instance-api-001",
        risk_context={
            "risk_ref": "current-risk",
            "primary_category": "用药依从性",
            "severity": "high",
        },
        evidence_packet=(
            {
                "evidence_id": "risk-evidence-api-001",
                "source_entry_id": "risk-evidence-source",
                "source_content_sha256": SOURCE_HASH,
                "locator": "listing:demo.xlsx:sheet:CM:row:3",
                "quote": "2026-06-01 非试验用合并用药 布洛芬 200mg QD",
                "raw_fields": {"evidence_kind": "original_data"},
            },
        ),
    )
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
            risk_packet_resolver=lambda _project_id, _risk_id: packet,
        )
    )
    client = TestClient(app)
    endpoint = "/api/projects/project-api/modules/medical-monitoring/ai/risk-jobs"

    started = client.post(
        endpoint,
        json={
            "task_type": "risk_evidence_summary",
            "business_key": "risk-summary-api-001",
            "risk_instance_id": "risk-instance-api-001",
            "context": {"purpose": "医学复核前证据摘要"},
        },
    )
    wrong_task = client.post(
        endpoint,
        json={
            "task_type": "protocol_clause_structuring",
            "business_key": "wrong-risk-task",
            "risk_instance_id": "risk-instance-api-001",
        },
    )

    assert started.status_code == 202, started.text
    result = service.run_next("risk-api-worker")
    assert result.job is not None
    assert result.job.status.value == "completed"
    candidate = repository.candidates("project-api", result.job.job_id)[0]
    assert candidate.evidence[0].quote.startswith("2026-06-01")
    assert wrong_task.status_code == 422


def test_protocol_semantic_job_uses_v12_prompt_contract(
    tmp_path: Path,
) -> None:
    """API-submitted protocol clause jobs carry the mandatory v12 prompt
    contract; v9-v11 are retired and the v8 contract is
    legacy-terminal only after cutover."""
    batch_repository = FakeBatchRepository()
    repository, service = _service(tmp_path, batch_repository)
    revision = MonitoringAiInputRevision(
        project_id="project-api",
        protocol_version="protocol-registry-v1",
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="protocol-source",
                source_content_sha256=SOURCE_HASH,
            ),
        ),
    )
    packet = MonitoringAiSourcePacket(
        input_revision=revision,
        source_ids=("protocol-span-1",),
        evidence_packet=(
            {
                "evidence_id": "protocol-evidence-1",
                "source_entry_id": "protocol-source",
                "source_content_sha256": SOURCE_HASH,
                "locator": "docx:paragraph:42",
                "quote": "随机前应停用方案规定的禁用药物。",
                "raw_fields": {
                    "source_id": "protocol-span-1",
                    "source_type": "protocol_docx_paragraph",
                },
            },
        ),
    )
    wake_count = {"value": 0}
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=service,
            batch_repository=batch_repository,
            require_server_principal=False,
            source_packet_resolver=lambda _project_id, _source_ids: packet,
            worker_wake=lambda: wake_count.__setitem__(
                "value",
                wake_count["value"] + 1,
            ),
        )
    )
    client = TestClient(app)

    started = client.post(
        "/api/projects/project-api/modules/medical-monitoring/ai/"
        "semantic-jobs",
        json={
            "task_type": "protocol_clause_structuring",
            "business_key": "protocol-clause-v12-api-001",
            "source_ids": ["protocol-span-1"],
            "context": {"purpose": "禁用药条款结构化"},
        },
    )

    assert started.status_code == 202, started.text
    assert started.json()["status"] == "queued"
    assert wake_count["value"] == 1

    result = service.run_next("semantic-api-worker")
    assert result.processed is True
    assert result.job is not None
    assert result.job.status.value == "completed"
    assert result.job.prompt_version == (
        "monitoring-protocol-clause-structuring-v12"
    )
    assert len(repository.candidates("project-api", result.job.job_id)) == 1
