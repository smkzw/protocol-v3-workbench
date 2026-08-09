from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiCandidateStatus,
    MonitoringAiInputRevision,
    MonitoringAiJobCreate,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    content_sha256,
)
from services.api.app.monitoring_ai_field_profiler import MonitoringAIFieldProfiler
from services.api.app.monitoring_ai_repository import (
    MonitoringAiRepository,
    MonitoringAiRepositoryError,
    MonitoringAiStateConflictError,
)
from services.api.app.monitoring_ai_router import (
    create_monitoring_ai_router,
    monitoring_input_revision_for_batch,
)
from services.api.app.monitoring_ai_service import (
    MonitoringAiService,
    monitoring_revision_with_field_profile,
)
from services.api.app.monitoring_batch_repository import (
    DiffReadyBatch,
    NormalizedRow,
)
from services.api.app.monitoring_deterministic_metadata_mapping import (
    DETERMINISTIC_METADATA_MAPPING_VERSION,
    DETERMINISTIC_METADATA_MODEL,
    LEGACY_V7_DETERMINISTIC_REPAIR_REASON,
    LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
)
from services.api.app.monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
)


SOURCE_HASH = "a" * 64
INPUT_HASH = "b" * 64
PROFILE_HASH = "c" * 64


def _field(name: str, *, domain: str = "DD") -> dict[str, Any]:
    return {
        "domain": domain,
        "field": name,
        "total_rows": 12,
        "non_empty_count": 12,
        "null_rate": 0.0,
        "inferred_type": "string",
        "unique_value_count": 2,
        "top_values": [],
        "representative_values": ["value"],
        "anomaly_examples": [],
    }


def _chunk_profile(
    field_names: tuple[str, ...] = ("__FORMOID", "DOMAIN"),
    *,
    batch_id: str = "batch-v7",
    profile_sha256: str = PROFILE_HASH,
) -> dict[str, Any]:
    ordered_names = tuple(
        sorted(field_names, key=lambda value: (value.casefold(), value))
    )
    return {
        "schema_version": "monitoring_ai_field_profile_v3",
        "batch_id": batch_id,
        "project_id": "project-alpha",
        "batch_revision": 1,
        "mapping_revision": None,
        "expected_domains": ["DD"],
        "source_bindings": [
            {
                "source_entry_id": "source-listing",
                "source_content_sha256": SOURCE_HASH,
            }
        ],
        "source_sha256s": [SOURCE_HASH],
        "row_count": 12,
        "input_sha256": INPUT_HASH,
        "fields": [_field(name) for name in ordered_names],
        "relationships": [],
        "profile_sha256": profile_sha256,
        "payload_policy": "field_statistics_without_row_or_identifier_values_v1",
        "scope": "complete_profile_chunk",
        "full_profile_sha256": profile_sha256,
        "full_input_sha256": INPUT_HASH,
        "full_field_count": len(ordered_names),
        "domain": "DD",
        "domain_field_count": len(ordered_names),
        "domain_field_names": list(ordered_names),
        "chunk_index": 1,
        "chunk_total": 1,
        "chunk_size_limit": 12,
    }


def _revision(
    *,
    project_id: str = "project-alpha",
    batch_revision: str = "batch-v7:v1",
    profile_sha256: str = PROFILE_HASH,
) -> MonitoringAiInputRevision:
    base = MonitoringAiInputRevision(
        project_id=project_id,
        batch_revision=batch_revision,
        sources=(
            MonitoringAiSourceBinding(
                source_entry_id="source-listing",
                source_content_sha256=SOURCE_HASH,
            ),
        ),
    )
    return monitoring_revision_with_field_profile(base, profile_sha256)


def _service(repository: MonitoringAiRepository) -> MonitoringAiService:
    def forbidden_runtime():
        raise AssertionError("legacy deterministic repair must not resolve or call AI")

    return MonitoringAiService(
        repository,
        runtime_resolver=forbidden_runtime,
        provider_factory=lambda _env: (_ for _ in ()).throw(
            AssertionError("legacy deterministic repair must not create an AI provider")
        ),
    )


def _create_job(
    repository: MonitoringAiRepository,
    *,
    profile: dict[str, Any] | None = None,
    task_type: MonitoringAiTaskType = MonitoringAiTaskType.LISTING_FIELD_MAPPING,
    prompt_version: str = LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
    business_key: str = "listing-field-mapping:batch-v7:DD:0001-of-0001",
) -> Any:
    profile = profile or _chunk_profile()
    revision = _revision(
        batch_revision=f"{profile['batch_id']}:v{profile['batch_revision']}",
        profile_sha256=profile["profile_sha256"],
    )
    return repository.create_or_get(
        MonitoringAiJobCreate(
            project_id="project-alpha",
            task_type=task_type,
            input_revision=revision,
            input_payload={"field_profile": profile},
            prompt_version=prompt_version,
            profile_id="legacy-independent-ai",
            provider="legacy-provider",
            requested_model="legacy-requested-model",
            max_attempts=1,
            business_key=business_key,
        )
    )


def _fail_job(
    repository: MonitoringAiRepository,
    *,
    profile: dict[str, Any] | None = None,
    task_type: MonitoringAiTaskType = MonitoringAiTaskType.LISTING_FIELD_MAPPING,
    prompt_version: str = LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
    failure_code: str = "invalid_ai_output",
    business_key: str = "listing-field-mapping:batch-v7:DD:0001-of-0001",
) -> Any:
    created = _create_job(
        repository,
        profile=profile,
        task_type=task_type,
        prompt_version=prompt_version,
        business_key=business_key,
    )
    running = repository.claim_next("legacy-worker")
    assert running is not None and running.job_id == created.job_id
    repository.record_attempt(
        running,
        owner="legacy-worker",
        request_payload={"legacy_prompt": prompt_version},
        response_payload={"invalid": "legacy output"},
        response_model="legacy-requested-model",
        outcome="invalid_output",
        failure_code=failure_code,
        failure_message="legacy output omitted source_metadata",
    )
    return repository.fail(
        running,
        owner="legacy-worker",
        failure_code=failure_code,
        failure_message="legacy output omitted source_metadata",
        retryable=False,
    )


def _repair(
    service: MonitoringAiService,
    job: Any,
    *,
    batch_id: str = "batch-v7",
    input_revision_sha256: str | None = None,
    full_profile_sha256: str = PROFILE_HASH,
    reason: str = "修复旧版纯技术元数据输出。",
    idempotency_key: str = "repair-v7-dd-001",
):
    return service.repair_failed_v7_deterministic_mapping(
        project_id=job.project_id,
        job_id=job.job_id,
        expected_batch_id=batch_id,
        expected_input_revision_sha256=(
            input_revision_sha256 or job.input_revision_sha256
        ),
        expected_full_profile_sha256=full_profile_sha256,
        actor="medical-monitoring-migration",
        reason=reason,
        idempotency_key=idempotency_key,
    )


def _completed_repair(tmp_path: Path):
    database = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(database)
    failed = _fail_job(repository)
    result = _repair(_service(repository), failed)
    return database, repository, failed, result


def test_v7_pure_metadata_repair_is_auditable_idempotent_and_assemblable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "monitoring-ai.sqlite3"
    repository = MonitoringAiRepository(database)
    failed = _fail_job(repository)
    original_attempts = repository.attempts(failed.project_id, failed.job_id)
    service = _service(repository)

    first = _repair(service, failed)
    replay = _repair(service, failed)

    assert first.job.status == MonitoringAiJobStatus.COMPLETED
    assert replay.job == first.job
    assert replay.candidate == first.candidate
    assert replay.repair == first.repair
    assert first.job.job_id == failed.job_id
    assert first.job.business_key == failed.business_key
    assert first.job.input_revision_sha256 == failed.input_revision_sha256
    assert first.job.prompt_version == LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION
    assert first.job.provider == failed.provider
    assert first.job.requested_model == failed.requested_model
    assert first.job.response_model == DETERMINISTIC_METADATA_MODEL
    assert first.job.attempt_count == failed.attempt_count
    assert repository.attempts(failed.project_id, failed.job_id) == original_attempts
    assert len(repository.candidates(failed.project_id, failed.job_id)) == 1
    assert [
        (
            item["source_field"],
            item["field_kind"],
        )
        for item in first.candidate.structured_payload["field_mappings"]
    ] == [
        ("__FORMOID", "source_metadata"),
        ("DOMAIN", "source_metadata"),
    ]
    provenance = first.repair["provenance"]
    assert provenance == {
        "schema_version": "monitoring_field_mapping_provenance_v1",
        "provenance": "deterministic_rule",
        "deterministic_rule_version": DETERMINISTIC_METADATA_MAPPING_VERSION,
        "ai_inference_used": False,
        "migration_reason": LEGACY_V7_DETERMINISTIC_REPAIR_REASON,
        "field_origins": first.candidate.structured_payload[
            "mapping_provenance"
        ]["field_origins"],
    }
    assert all(
        evidence.raw_fields["provenance"] == "deterministic_rule"
        and evidence.raw_fields["deterministic_rule_version"]
        == DETERMINISTIC_METADATA_MAPPING_VERSION
        and evidence.raw_fields["ai_inference_used"] is False
        and evidence.raw_fields["migration_reason"]
        == LEGACY_V7_DETERMINISTIC_REPAIR_REASON
        for evidence in first.candidate.evidence
    )
    assert first.repair["actor"] == "medical-monitoring-migration"
    assert first.repair["reason"] == "修复旧版纯技术元数据输出。"
    assert first.repair["original_status"] == "failed"
    assert first.repair["original_failure_code"] == "invalid_ai_output"
    assert first.repair["original_attempt_count"] == failed.attempt_count
    assert first.repair["output_sha256"] == first.job.output_sha256
    assert content_sha256(first.repair["raw_output"]) == first.job.output_sha256
    assert first.repair["raw_output"]["requested_model"] == (
        failed.requested_model
    )
    assert first.repair["raw_output"]["prompt_version"] == (
        LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION
    )

    repository.decide_candidate(
        failed.project_id,
        first.candidate.candidate_id,
        decision=MonitoringAiCandidateStatus.ACCEPTED,
        actor="medical-manager",
        reason="进入旧 v7 字段映射草稿人工校对。",
        current_input_revision_sha256=failed.input_revision_sha256,
    )
    draft = MonitoringMappingDraftRepository(database).assemble(
        failed.project_id,
        "batch-v7",
        PROFILE_HASH,
        prompt_version=LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
    )
    assert {
        (item.domain, item.source_field, item.field_kind.value)
        for item in draft.fields
    } == {
        ("DD", "__FORMOID", "source_metadata"),
        ("DD", "DOMAIN", "source_metadata"),
    }

    reopened = MonitoringAiRepository(database)
    assert reopened.deterministic_repair_by_idempotency(
        failed.project_id,
        "repair-v7-dd-001",
    ) == first.repair
    with sqlite3.connect(database) as connection:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="deterministic repair is immutable",
        ):
            connection.execute(
                """
                UPDATE monitoring_ai_deterministic_repairs
                SET reason = 'changed' WHERE repair_id = ?
                """,
                (first.repair["repair_id"],),
            )


def test_deterministic_repair_read_rejects_raw_output_hash_drift(
    tmp_path: Path,
) -> None:
    database, repository, failed, result = _completed_repair(tmp_path)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DROP TRIGGER trg_monitoring_ai_deterministic_repair_no_update"
        )
        connection.execute(
            "UPDATE monitoring_ai_deterministic_repairs "
            "SET raw_output_json = ? WHERE repair_id = ?",
            ('{"tampered":true}', result.repair["repair_id"]),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="raw output hash mismatch",
    ):
        repository.deterministic_repair_by_idempotency(
            failed.project_id,
            "repair-v7-dd-001",
        )


def test_deterministic_repair_read_rejects_non_object_provenance(
    tmp_path: Path,
) -> None:
    database, repository, failed, result = _completed_repair(tmp_path)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DROP TRIGGER trg_monitoring_ai_deterministic_repair_no_update"
        )
        connection.execute(
            "UPDATE monitoring_ai_deterministic_repairs "
            "SET provenance_json = ? WHERE repair_id = ?",
            ('["tampered"]', result.repair["repair_id"]),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="provenance must be an object",
    ):
        repository.deterministic_repair_by_idempotency(
            failed.project_id,
            "repair-v7-dd-001",
        )


def test_deterministic_repair_read_rejects_cross_job_candidate_binding(
    tmp_path: Path,
) -> None:
    database, repository, failed, result = _completed_repair(tmp_path)
    other_failed = _fail_job(
        repository,
        profile=_chunk_profile(
            field_names=("__FORMOID", "OTHER"),
            batch_id="batch-v7-other",
        ),
        business_key="listing-field-mapping:batch-v7-other:DD:0001-of-0001",
    )

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DROP TRIGGER trg_monitoring_ai_deterministic_repair_no_update"
        )
        connection.execute(
            "UPDATE monitoring_ai_deterministic_repairs SET job_id = ? "
            "WHERE repair_id = ?",
            (other_failed.job_id, result.repair["repair_id"]),
        )

    with pytest.raises(
        MonitoringAiRepositoryError,
        match="parent binding mismatch",
    ):
        repository.deterministic_repair_by_idempotency(
            failed.project_id,
            "repair-v7-dd-001",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        (
            "original_attempt_count",
            1.5,
            "original_attempt_count must be an integer",
        ),
        ("request_sha256", "not-hash", "request_sha256 must be a lowercase SHA-256"),
        ("request_sha256", "A" * 64, "request_sha256 must be a lowercase SHA-256"),
        ("request_sha256", f" {'a' * 64}", "request_sha256 must be a lowercase SHA-256"),
        ("actor", "", "actor must be non-empty text"),
        ("created_at", "not-a-time", "created_at must be an ISO datetime"),
    ),
)
def test_deterministic_repair_read_rejects_root_shape_tamper(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    database, repository, failed, result = _completed_repair(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DROP TRIGGER trg_monitoring_ai_deterministic_repair_no_update"
        )
        connection.execute(
            f"UPDATE monitoring_ai_deterministic_repairs SET {field} = ? "
            "WHERE repair_id = ?",
            (value, result.repair["repair_id"]),
        )

    with pytest.raises(MonitoringAiRepositoryError, match=message):
        repository.deterministic_repair_by_idempotency(
            failed.project_id,
            "repair-v7-dd-001",
        )


def test_v7_repair_rejects_idempotency_key_with_changed_meaning(
    tmp_path: Path,
) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    failed = _fail_job(repository)
    service = _service(repository)
    _repair(service, failed)

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="different meaning",
    ):
        _repair(service, failed, reason="改变后的请求含义。")


@pytest.mark.parametrize(
    ("prompt_version", "task_type", "failure_code"),
    (
        ("monitoring-listing-field-mapping-v9", MonitoringAiTaskType.LISTING_FIELD_MAPPING, "invalid_ai_output"),
        (LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION, MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING, "invalid_ai_output"),
        (LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION, MonitoringAiTaskType.LISTING_FIELD_MAPPING, "provider_timeout"),
    ),
)
def test_v7_repair_rejects_wrong_prompt_task_or_failure(
    tmp_path: Path,
    prompt_version: str,
    task_type: MonitoringAiTaskType,
    failure_code: str,
) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    failed = _fail_job(
        repository,
        prompt_version=prompt_version,
        task_type=task_type,
        failure_code=failure_code,
    )

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="only failed v7 listing",
    ):
        _repair(_service(repository), failed)


@pytest.mark.parametrize(
    "status",
    (
        MonitoringAiJobStatus.QUEUED,
        MonitoringAiJobStatus.RUNNING,
        MonitoringAiJobStatus.COMPLETED,
        MonitoringAiJobStatus.BLOCKED,
        MonitoringAiJobStatus.STALE_INPUT,
        MonitoringAiJobStatus.CANCELLED,
    ),
)
def test_v7_repair_rejects_every_non_failed_status(
    tmp_path: Path,
    status: MonitoringAiJobStatus,
) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    job = _create_job(repository)
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_jobs
            SET status = ?, failure_code = 'invalid_ai_output'
            WHERE job_id = ?
            """,
            (status.value, job.job_id),
        )
    current = repository.get(job.project_id, job.job_id)

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="only failed v7 listing",
    ):
        _repair(_service(repository), current)


@pytest.mark.parametrize(
    "field_name",
    ("PAGE", "FORM", "LINE", "AEOID"),
)
def test_v7_repair_rejects_ambiguous_metadata_like_fields(
    tmp_path: Path,
    field_name: str,
) -> None:
    profile = _chunk_profile((field_name,))
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    failed = _fail_job(repository, profile=profile)

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="semantic, mixed or ambiguous",
    ):
        _repair(_service(repository), failed)


def test_v7_repair_accepts_visit_identity_fields_after_v13_role_freeze(
    tmp_path: Path,
) -> None:
    profile = _chunk_profile(("VISIT", "VISITNUM"))
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    failed = _fail_job(repository, profile=profile)

    repaired = _repair(_service(repository), failed)

    mappings = {
        item["source_field"]: (
            item["field_kind"],
            item["recommended_role"],
        )
        for item in repaired.candidate.structured_payload["field_mappings"]
    }
    assert mappings == {
        "VISIT": ("source_metadata", "visit_name"),
        "VISITNUM": ("source_metadata", "visit_sequence_number"),
    }


def test_v7_repair_rejects_mixed_chunk_and_identity_drift(
    tmp_path: Path,
) -> None:
    profile = _chunk_profile(("DOMAIN", "DDTERM"))
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    failed = _fail_job(repository, profile=profile)
    service = _service(repository)

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="semantic, mixed or ambiguous",
    ):
        _repair(service, failed)
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="input revision is stale",
    ):
        _repair(
            service,
            failed,
            input_revision_sha256="d" * 64,
            idempotency_key="repair-drifted-revision",
        )
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="batch or field profile identity drifted",
    ):
        _repair(
            service,
            failed,
            full_profile_sha256="e" * 64,
            idempotency_key="repair-drifted-profile",
        )
    with pytest.raises(
        MonitoringAiStateConflictError,
        match="batch or field profile identity drifted",
    ):
        _repair(
            service,
            failed,
            batch_id="another-batch",
            idempotency_key="repair-drifted-batch",
        )


def test_v7_repair_rejects_existing_candidate(
    tmp_path: Path,
) -> None:
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    failed = _fail_job(repository)
    service = _service(repository)
    repaired = _repair(service, failed)
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            """
            UPDATE monitoring_ai_jobs
            SET status = 'failed', failure_code = 'invalid_ai_output'
            WHERE job_id = ?
            """,
            (failed.job_id,),
        )
    failed_again = repository.get(failed.project_id, failed.job_id)

    with pytest.raises(
        MonitoringAiStateConflictError,
        match="no candidates",
    ):
        _repair(
            service,
            failed_again,
            idempotency_key="repair-existing-candidate",
        )
    assert repository.candidates(failed.project_id, failed.job_id) == (
        repaired.candidate,
    )


class _PureMetadataBatchRepository:
    def __init__(self) -> None:
        self.version = 1
        self.batch = DiffReadyBatch(
            batch_id="batch-api-v7",
            project_id="project-api",
            state="frozen",
            version=self.version,
            expected_domains=("DD",),
            mapping_revision=None,
            source_bindings=(("source-listing", SOURCE_HASH),),
            source_hashes=(SOURCE_HASH,),
            rows=(
                NormalizedRow(
                    business_key="DD|001",
                    domain="DD",
                    data={"__FORMOID": "FORM.DD", "DOMAIN": "DD"},
                    source_locator={"sheet": "DD", "row": 2},
                    row_fingerprint="f" * 64,
                ),
            ),
        )

    def load_profile_ready_batch(self, batch_id: str) -> DiffReadyBatch:
        if batch_id != self.batch.batch_id:
            raise ValueError("batch not found")
        return self.batch


def _chunk_from_snapshot(snapshot_payload: dict[str, Any]) -> dict[str, Any]:
    fields = sorted(
        snapshot_payload["fields"],
        key=lambda item: (
            str(item["field"]).strip().casefold(),
            str(item["field"]).strip(),
        ),
    )
    names = [str(item["field"]).strip() for item in fields]
    profile = dict(snapshot_payload)
    profile.update(
        {
            "scope": "complete_profile_chunk",
            "full_profile_sha256": snapshot_payload["profile_sha256"],
            "full_input_sha256": snapshot_payload["input_sha256"],
            "full_field_count": len(fields),
            "domain": "DD",
            "domain_field_count": len(fields),
            "domain_field_names": names,
            "chunk_index": 1,
            "chunk_total": 1,
            "chunk_size_limit": 12,
            "fields": fields,
            "relationships": [],
        }
    )
    return profile


def test_repair_endpoint_requires_current_batch_profile_and_does_not_wake_worker(
    tmp_path: Path,
) -> None:
    batch_repository = _PureMetadataBatchRepository()
    snapshot = MonitoringAIFieldProfiler(
        batch_repository
    ).profile_loaded_batch(batch_repository.batch)
    payload = snapshot.to_ai_payload()
    profile = _chunk_from_snapshot(payload)
    revision = monitoring_revision_with_field_profile(
        monitoring_input_revision_for_batch(batch_repository.batch),
        snapshot.profile_sha256,
    )
    repository = MonitoringAiRepository(tmp_path / "monitoring-ai.sqlite3")
    created = repository.create_or_get(
        MonitoringAiJobCreate(
            project_id="project-api",
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING,
            input_revision=revision,
            input_payload={"field_profile": profile},
            prompt_version=LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION,
            profile_id="legacy-independent-ai",
            provider="legacy-provider",
            requested_model="legacy-requested-model",
            max_attempts=1,
            business_key=(
                "listing-field-mapping:batch-api-v7:DD:0001-of-0001"
            ),
        )
    )
    running = repository.claim_next("legacy-worker")
    assert running is not None
    repository.record_attempt(
        running,
        owner="legacy-worker",
        request_payload={"legacy": True},
        response_payload={"invalid": True},
        response_model="legacy-requested-model",
        outcome="invalid_output",
        failure_code="invalid_ai_output",
        failure_message="legacy output omitted source metadata",
    )
    failed = repository.fail(
        running,
        owner="legacy-worker",
        failure_code="invalid_ai_output",
        failure_message="legacy output omitted source metadata",
        retryable=False,
    )
    wake_count = {"value": 0}
    app = FastAPI()
    app.include_router(
        create_monitoring_ai_router(
            repository=repository,
            service=_service(repository),
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
        f"jobs/{created.job_id}/deterministic-repair"
    )
    request = {
        "expected_batch_id": "batch-api-v7",
        "expected_input_revision_sha256": revision.revision_sha256,
        "expected_full_profile_sha256": snapshot.profile_sha256,
        "actor": "medical-monitoring-migration",
        "reason": "修复旧版纯技术元数据输出。",
        "idempotency_key": "api-repair-v7-dd-001",
    }

    response = client.post(endpoint, json=request)
    replay = client.post(endpoint, json=request)

    assert response.status_code == 200, response.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == response.json()
    assert response.json()["job"]["job_id"] == failed.job_id
    assert response.json()["job"]["status"] == "completed"
    assert response.json()["candidate"]["prompt_version"] == (
        LEGACY_V7_FIELD_MAPPING_PROMPT_VERSION
    )
    assert response.json()["repair"]["original_failure_code"] == (
        "invalid_ai_output"
    )
    assert wake_count["value"] == 0

    drifted = dict(request)
    drifted["idempotency_key"] = "api-repair-v7-drifted"
    drifted["expected_full_profile_sha256"] = "e" * 64
    conflict = client.post(endpoint, json=drifted)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == (
        "monitoring_ai_deterministic_repair_conflict"
    )

    with sqlite3.connect(repository.path) as connection:
        repair_count = connection.execute(
            "SELECT COUNT(*) FROM monitoring_ai_deterministic_repairs"
        ).fetchone()[0]
        persisted_payload = connection.execute(
            """
            SELECT input_payload_json FROM monitoring_ai_jobs
            WHERE job_id = ?
            """,
            (failed.job_id,),
        ).fetchone()[0]
    assert repair_count == 1
    assert json.loads(persisted_payload) == {"field_profile": profile}


def test_sqlite_repair_migration_is_idempotent(tmp_path: Path) -> None:
    database = tmp_path / "monitoring-ai.sqlite3"
    MonitoringAiRepository(database)
    MonitoringAiRepository(database)

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(monitoring_ai_deterministic_repairs)"
            ).fetchall()
        }
        triggers = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'trigger'
                  AND tbl_name = 'monitoring_ai_deterministic_repairs'
                """
            ).fetchall()
        }
    assert "raw_output_json" in columns
    assert triggers == {
        "trg_monitoring_ai_deterministic_repair_no_update",
        "trg_monitoring_ai_deterministic_repair_no_delete",
    }
