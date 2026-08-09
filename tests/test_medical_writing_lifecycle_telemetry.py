from __future__ import annotations

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.api.app.medical_writing_artifact_lifecycle import (
    MedicalWritingArtifactIdentity,
)
from services.api.app.medical_writing_lifecycle_telemetry import (
    MEDICAL_WRITING_LIFECYCLE_TELEMETRY_SCHEMA,
    MedicalWritingLifecycleTelemetryConflict,
    MedicalWritingLifecycleTelemetryError,
    MedicalWritingLifecycleTelemetryEvent,
    MedicalWritingLifecycleTelemetryRepository,
)


NOW = "2026-08-02T00:00:00+00:00"
HASHES = {
    "source_snapshot_sha256": "1" * 64,
    "docx_sha256": "2" * 64,
    "manifest_sha256": "3" * 64,
}


def _identity(*, generation_id: str = "g1") -> MedicalWritingArtifactIdentity:
    return MedicalWritingArtifactIdentity(
        tenant_id="tenant-a",
        project_id="project-1",
        document_id="protocol-1",
        generation_id=generation_id,
        export_job_id=f"export-{generation_id}",
        mode="approved_final",
        **HASHES,
    )


def _event(
    *,
    event_id: str = "event-1",
    event_type: str = "created",
    identity: MedicalWritingArtifactIdentity | None = None,
    error_code: str = "",
    principal_subject: str = "",
    principal_assurance: str = "",
    detail: dict | None = None,
) -> MedicalWritingLifecycleTelemetryEvent:
    return MedicalWritingLifecycleTelemetryEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at=NOW,
        identity=identity or _identity(),
        policy_id="approved-final",
        policy_revision=1,
        request_id=f"request-{event_id}",
        trace_id=f"trace-{event_id}",
        principal_subject=principal_subject,
        principal_assurance=principal_assurance,
        error_code=error_code,
        detail=detail,
    )


def test_event_contract_is_secret_free_and_fail_closed():
    event = _event(
        principal_subject="user-1",
        principal_assurance="synthetic-assurance",
        detail={"operation": "append", "counts": {"items": 3}},
    )
    payload = event.as_dict()
    assert payload["schema_version"] == MEDICAL_WRITING_LIFECYCLE_TELEMETRY_SCHEMA
    assert payload["identity"]["project_id"] == "project-1"
    assert len(payload["event_hash"]) == 64
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "document_text" not in serialized
    assert "password" not in serialized
    assert "session_ref" not in serialized

    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        _event(event_type="unknown").as_dict()
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        _event(event_type="failed").as_dict()
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        _event(detail={"access_token": "do-not-store"}).as_dict()
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        _event(principal_subject="user-1").as_dict()
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        _event(identity=_identity()).__class__(
            event_id="event-bad-time",
            event_type="created",
            occurred_at="2026-08-02T00:00:00",
            identity=_identity(),
            policy_id="approved-final",
            policy_revision=1,
            request_id="request-bad-time",
            trace_id="trace-bad-time",
        ).as_dict()


def test_append_replay_restart_and_event_hash(tmp_path):
    db_path = tmp_path / "telemetry.sqlite3"
    event = _event()
    first = MedicalWritingLifecycleTelemetryRepository(db_path).append(
        event, idempotency_key="append-1"
    )
    assert first.replayed is False
    assert first.event_hash == event.as_dict()["event_hash"]

    restarted = MedicalWritingLifecycleTelemetryRepository(db_path)
    replay = restarted.append(event, idempotency_key="append-1")
    assert replay.replayed is True
    assert replay.event.as_dict()["event_hash"] == first.event_hash
    assert restarted.event_count(tenant_id="tenant-a", project_id="project-1") == 1
    assert restarted.events(tenant_id="tenant-a", project_id="project-1")[0].event_id == "event-1"


def test_conflicting_idempotency_or_event_identity_fails_closed(tmp_path):
    repository = MedicalWritingLifecycleTelemetryRepository(tmp_path / "conflicts.sqlite3")
    repository.append(_event(), idempotency_key="append-1")
    with pytest.raises(MedicalWritingLifecycleTelemetryConflict):
        repository.append(
            _event(event_id="event-2", detail={"changed": True}),
            idempotency_key="append-1",
        )
    with pytest.raises(MedicalWritingLifecycleTelemetryConflict):
        repository.append(_event(event_id="event-1"), idempotency_key="append-2")


def test_concurrent_duplicate_workers_create_one_event(tmp_path):
    repository = MedicalWritingLifecycleTelemetryRepository(tmp_path / "concurrent.sqlite3")
    event = _event()

    def append_once():
        return repository.append(event, idempotency_key="worker-safe-key")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: append_once(), range(8)))
    assert sum(result.replayed is False for result in results) == 1
    assert sum(result.replayed is True for result in results) == 7
    assert repository.event_count(tenant_id="tenant-a", project_id="project-1") == 1


def test_sqlite_rows_are_immutable(tmp_path):
    db_path = tmp_path / "immutable.sqlite3"
    repository = MedicalWritingLifecycleTelemetryRepository(db_path)
    repository.append(_event(), idempotency_key="append-1")
    connection = sqlite3.connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE medical_writing_lifecycle_telemetry_events SET event_type = 'completed'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM medical_writing_lifecycle_telemetry_events")
    finally:
        connection.rollback()
        connection.close()
    assert repository.event_count(tenant_id="tenant-a", project_id="project-1") == 1


def test_recovery_can_be_system_emitted_but_principal_pair_is_atomic():
    assert _event(event_type="recovery").as_dict()["principal_subject"] == ""
    assert _event(
        event_type="recovery",
        principal_subject="service-recovery",
        principal_assurance="system-attested",
    ).as_dict()["principal_assurance"] == "system-attested"
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        _event(event_type="recovery", principal_assurance="system-attested").as_dict()


def test_persisted_payload_validation_does_not_normalize_bad_records():
    payload = _event().as_dict()
    bad_schema = copy.deepcopy(payload)
    bad_schema["schema_version"] = "legacy"
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        MedicalWritingLifecycleTelemetryEvent.from_dict(bad_schema)

    extra_field = copy.deepcopy(payload)
    extra_field["untrusted_field"] = "must not be persisted"
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        MedicalWritingLifecycleTelemetryEvent.from_dict(extra_field)

    missing_hash = copy.deepcopy(payload)
    missing_hash.pop("event_hash")
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        MedicalWritingLifecycleTelemetryEvent.from_dict(missing_hash)

    bad_detail = copy.deepcopy(payload)
    bad_detail["detail"] = ["not-an-object"]
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        MedicalWritingLifecycleTelemetryEvent.from_dict(bad_detail)

    bad_policy_revision = copy.deepcopy(payload)
    bad_policy_revision["policy_revision"] = "not-an-int"
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        MedicalWritingLifecycleTelemetryEvent.from_dict(bad_policy_revision)

    bad_hash = copy.deepcopy(payload)
    bad_hash["detail"] = {"changed": True}
    with pytest.raises(MedicalWritingLifecycleTelemetryError):
        MedicalWritingLifecycleTelemetryEvent.from_dict(bad_hash)
