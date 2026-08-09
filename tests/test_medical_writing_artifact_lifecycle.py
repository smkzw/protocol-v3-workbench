from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.api.app.medical_writing_artifact_lifecycle import (
    MedicalWritingArtifactIdentity,
    MedicalWritingArtifactLifecycleAuthorizationError,
    MedicalWritingArtifactLifecycleConflict,
    MedicalWritingArtifactLifecycleIntegrityError,
    MedicalWritingArtifactLifecycleNotFound,
    MedicalWritingArtifactLifecycleRepository,
    MedicalWritingArtifactLifecycleStale,
    MedicalWritingArtifactPrincipal,
    MedicalWritingArtifactRetentionPolicy,
)


NOW = "2026-08-02T00:00:00+00:00"
ELIGIBLE = "2026-08-01T00:00:00+00:00"
LATE = "2026-08-03T00:00:00+00:00"
HASHES = {
    "source_snapshot_sha256": "1" * 64,
    "docx_sha256": "2" * 64,
    "manifest_sha256": "3" * 64,
}


def _principal(tenant: str = "tenant-a") -> MedicalWritingArtifactPrincipal:
    return MedicalWritingArtifactPrincipal(
        subject_id="user-medical-manager",
        tenant_id=tenant,
        role="medical_manager",
        assurance="session-authenticated",
        authenticated=True,
    )


def _identity(*, generation: str = "g1", document: str = "protocol-1", tenant: str = "tenant-a"):
    return MedicalWritingArtifactIdentity(
        tenant_id=tenant,
        project_id="project-1",
        document_id=document,
        generation_id=generation,
        export_job_id=f"export-{generation}",
        mode="approved_final",
        **HASHES,
    )


def _policy(*, legal_hold: bool = False, eligible: str = ELIGIBLE):
    return MedicalWritingArtifactRetentionPolicy(
        policy_id="policy-approved-final",
        policy_revision=1,
        minimum_retain_until=eligible,
        purge_eligible_at=eligible,
        legal_hold=legal_hold,
    )


def _register(repo, *, generation="g1", make_current=False, key=None, policy=None):
    return repo.register(
        principal=_principal(),
        identity=_identity(generation=generation),
        artifact_relpath=f"project-1/{generation}/protocol.docx",
        policy=policy or _policy(),
        idempotency_key=key or f"register-{generation}",
        make_current=make_current,
        now=NOW,
    )


def test_validation_fails_closed_for_identity_principal_and_path(tmp_path):
    repo = MedicalWritingArtifactLifecycleRepository(tmp_path / "lifecycle.sqlite3")
    with pytest.raises(MedicalWritingArtifactLifecycleAuthorizationError):
        repo.register(
            principal=_principal().__class__(
                subject_id="user-medical-manager",
                tenant_id="tenant-a",
                role="medical_manager",
                assurance="session-authenticated",
                authenticated=False,
            ),
            identity=_identity(),
            artifact_relpath="project-1/g1/protocol.docx",
            policy=_policy(),
            idempotency_key="unauthenticated",
            now=NOW,
        )
    with pytest.raises(MedicalWritingArtifactLifecycleAuthorizationError):
        repo.register(
            principal=_principal("tenant-b"),
            identity=_identity(),
            artifact_relpath="project-1/g1/protocol.docx",
            policy=_policy(),
            idempotency_key="wrong-tenant",
            now=NOW,
        )
    with pytest.raises(MedicalWritingArtifactLifecycleIntegrityError):
        repo.register(
            principal=_principal(),
            identity=_identity(),
            artifact_relpath="../escape/protocol.docx",
            policy=_policy(),
            idempotency_key="traversal",
            now=NOW,
        )
    with pytest.raises(MedicalWritingArtifactLifecycleIntegrityError):
        repo.register(
            principal=_principal(),
            identity=_identity(),
            artifact_relpath="project-1//g1/protocol.docx",
            policy=_policy(),
            idempotency_key="non-normalized",
            now=NOW,
        )
    with pytest.raises(MedicalWritingArtifactLifecycleIntegrityError):
        repo.register(
            principal=_principal(),
            identity=MedicalWritingArtifactIdentity(
                tenant_id="tenant-a",
                project_id="project-1",
                document_id="protocol-1",
                generation_id="g1",
                export_job_id="export-g1",
                mode="approved_final",
                source_snapshot_sha256="not-a-digest",
                docx_sha256=HASHES["docx_sha256"],
                manifest_sha256=HASHES["manifest_sha256"],
            ),
            artifact_relpath="project-1/g1/protocol.docx",
            policy=_policy(),
            idempotency_key="bad-hash",
            now=NOW,
        )


def test_register_is_idempotent_and_restart_safe(tmp_path):
    db_path = tmp_path / "lifecycle.sqlite3"
    repo = MedicalWritingArtifactLifecycleRepository(db_path)
    first = _register(repo, make_current=True)
    replay = _register(repo, make_current=True)

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.event_id == first.event_id
    assert replay.record.as_dict() == first.record.as_dict()
    assert repo.current_pointer(
        principal=_principal(), project_id="project-1", document_id="protocol-1"
    ).artifact_id == first.record.artifact_id
    assert len(repo.events(
        principal=_principal(), project_id="project-1", artifact_id=first.record.artifact_id
    )) == 1

    restarted = MedicalWritingArtifactLifecycleRepository(db_path)
    assert restarted.get(
        principal=_principal(), project_id="project-1", artifact_id=first.record.artifact_id
    ).as_dict() == first.record.as_dict()


def test_register_concurrency_creates_one_event(tmp_path):
    db_path = tmp_path / "concurrent.sqlite3"

    def worker(_):
        return _register(
            MedicalWritingArtifactLifecycleRepository(db_path),
            make_current=True,
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(worker, range(6)))
    assert sum(result.replayed is False for result in results) == 1
    assert {result.event_id for result in results} == {results[0].event_id}
    assert len(MedicalWritingArtifactLifecycleRepository(db_path).events(
        principal=_principal(),
        project_id="project-1",
        artifact_id=results[0].record.artifact_id,
    )) == 1


def test_purge_is_policy_gated_and_commit_is_idempotent_without_bytes(tmp_path):
    repo = MedicalWritingArtifactLifecycleRepository(tmp_path / "purge.sqlite3")
    result = _register(repo)

    held = repo.request_purge(
        principal=_principal(),
        project_id="project-1",
        artifact_id=result.record.artifact_id,
        idempotency_key="purge-held",
        now=LATE,
    )
    assert held.allowed is True
    assert held.record.state == "purge_requested"

    with pytest.raises(MedicalWritingArtifactLifecycleIntegrityError):
        repo.commit_purge(
            principal=_principal(),
            project_id="project-1",
            artifact_id=result.record.artifact_id,
            deletion_proof_sha256="bad",
            idempotency_key="purge-commit-bad",
            now=LATE,
        )

    committed = repo.commit_purge(
        principal=_principal(),
        project_id="project-1",
        artifact_id=result.record.artifact_id,
        deletion_proof_sha256="4" * 64,
        idempotency_key="purge-commit",
        now=LATE,
    )
    replay = repo.commit_purge(
        principal=_principal(),
        project_id="project-1",
        artifact_id=result.record.artifact_id,
        deletion_proof_sha256="4" * 64,
        idempotency_key="purge-commit",
        now=LATE,
    )
    assert committed.record.state == "purged"
    assert replay.replayed is True
    assert not (tmp_path / "project-1").exists()
    actions = [event["action"] for event in repo.events(
        principal=_principal(), project_id="project-1", artifact_id=result.record.artifact_id
    )]
    assert actions == ["registered", "purge_requested", "purge_committed"]


def test_purge_blocked_by_hold_retention_and_current_pointer(tmp_path):
    repo = MedicalWritingArtifactLifecycleRepository(tmp_path / "gates.sqlite3")
    held = _register(repo, policy=_policy(legal_hold=True))
    held_result = repo.request_purge(
        principal=_principal(), project_id="project-1", artifact_id=held.record.artifact_id,
        idempotency_key="held", now=LATE,
    )
    assert held_result.allowed is False
    assert held_result.reason == "legal_hold_active"
    assert held_result.record.state == "active"

    retained = _register(repo, generation="g2", policy=_policy(eligible=LATE))
    retained_result = repo.request_purge(
        principal=_principal(), project_id="project-1", artifact_id=retained.record.artifact_id,
        idempotency_key="retained", now=NOW,
    )
    assert retained_result.allowed is False
    assert retained_result.reason == "retention_window_not_reached"

    current = _register(repo, generation="g3", make_current=True)
    current_result = repo.request_purge(
        principal=_principal(), project_id="project-1", artifact_id=current.record.artifact_id,
        idempotency_key="current", now=LATE,
    )
    assert current_result.allowed is False
    assert current_result.reason == "current_pointer_cannot_be_purged"


def test_rollback_moves_pointer_preserves_generations_and_rejects_stale(tmp_path):
    repo = MedicalWritingArtifactLifecycleRepository(tmp_path / "rollback.sqlite3")
    first = _register(repo, generation="g1", make_current=True)
    second = _register(repo, generation="g2", make_current=False)
    moved = repo.rollback_to(
        principal=_principal(), project_id="project-1", document_id="protocol-1",
        target_artifact_id=second.record.artifact_id, expected_pointer_revision=1,
        reason="restore prior reviewed generation", idempotency_key="rollback-1", now=LATE,
    )
    assert moved.allowed is True
    assert moved.pointer_revision == 2
    assert moved.record.current_pointer is True
    assert repo.get(
        principal=_principal(), project_id="project-1", artifact_id=first.record.artifact_id
    ).current_pointer is False
    assert repo.get(
        principal=_principal(), project_id="project-1", artifact_id=second.record.artifact_id
    ).state == "active"
    replay = repo.rollback_to(
        principal=_principal(), project_id="project-1", document_id="protocol-1",
        target_artifact_id=second.record.artifact_id, expected_pointer_revision=1,
        reason="restore prior reviewed generation", idempotency_key="rollback-1", now=LATE,
    )
    assert replay.replayed is True
    with pytest.raises(MedicalWritingArtifactLifecycleStale):
        repo.rollback_to(
            principal=_principal(), project_id="project-1", document_id="protocol-1",
            target_artifact_id=first.record.artifact_id, expected_pointer_revision=1,
            reason="stale request", idempotency_key="rollback-stale", now=LATE,
        )


def test_immutable_identity_and_event_rows_and_cross_tenant_isolation(tmp_path):
    db_path = tmp_path / "immutability.sqlite3"
    repo = MedicalWritingArtifactLifecycleRepository(db_path)
    result = _register(repo)
    with pytest.raises(MedicalWritingArtifactLifecycleNotFound):
        repo.get(principal=_principal("tenant-b"), project_id="project-1", artifact_id=result.record.artifact_id)

    with sqlite3.connect(db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE medical_writing_artifact_lifecycle_records SET document_id = 'tampered'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM medical_writing_artifact_lifecycle_events"
            )
        rows = connection.execute(
            "SELECT identity_json, detail_json, result_json FROM medical_writing_artifact_lifecycle_records "
            "JOIN medical_writing_artifact_lifecycle_events USING (tenant_id, project_id, artifact_id)"
        ).fetchall()
    assert len(rows) == 1
    assert all("DOCX_BYTES" not in repr(row) for row in rows)


def test_conflicting_idempotency_key_is_rejected(tmp_path):
    repo = MedicalWritingArtifactLifecycleRepository(tmp_path / "conflict.sqlite3")
    _register(repo, generation="g1", key="same-key")
    with pytest.raises(MedicalWritingArtifactLifecycleConflict):
        _register(repo, generation="g2", key="same-key")
