from __future__ import annotations

import pytest

from services.api.app.medical_writing_artifact_lifecycle import (
    MedicalWritingArtifactIdentity,
    MedicalWritingArtifactPrincipal,
    MedicalWritingArtifactLifecycleConflict,
    MedicalWritingArtifactLifecycleRepository,
    MedicalWritingArtifactLifecycleStale,
    MedicalWritingArtifactRetentionPolicy,
)
from services.api.app.medical_writing_artifact_rollback import (
    MedicalWritingArtifactRollbackBindingMismatch,
    MedicalWritingArtifactRollbackIntent,
    artifact_identity_sha256,
    execute_artifact_rollback,
)
from services.api.app.medical_writing_principal_acl import (
    MedicalWritingAclGrant,
    MedicalWritingAclPolicy,
    MedicalWritingAuthenticatedPrincipal,
    MedicalWritingPrincipalAclDenied,
)


NOW = "2026-08-02T00:00:00+00:00"
LATE = "2026-08-03T00:00:00+00:00"
PRINCIPAL_EXPIRES = "2026-08-04T00:00:00+00:00"
HASHES = {
    "source_snapshot_sha256": "1" * 64,
    "docx_sha256": "2" * 64,
    "manifest_sha256": "3" * 64,
}


def _principal(tenant: str = "tenant-a"):
    return MedicalWritingAuthenticatedPrincipal(
        subject_id="user-1",
        tenant_id=tenant,
        assurance="synthetic-assurance",
        issued_at="2026-07-31T00:00:00+00:00",
        expires_at=PRINCIPAL_EXPIRES,
        authenticated=True,
        role="medical_manager",
        authn_context="synthetic-context",
        session_ref_sha256="a" * 64,
    )


def _lifecycle_principal(tenant: str = "tenant-a"):
    return MedicalWritingArtifactPrincipal(
        subject_id="user-1",
        tenant_id=tenant,
        role="medical_manager",
        assurance="synthetic-assurance",
        authenticated=True,
    )


def _policy(*, subject: str = "user-1"):
    return MedicalWritingAclPolicy(
        policy_id="rollback-policy",
        policy_revision=1,
        effective_from="2026-08-01T00:00:00+00:00",
        grants=(
            MedicalWritingAclGrant(
                grant_id="rollback-grant",
                tenant_id="tenant-a",
                project_id="project-1",
                document_id="protocol-1",
                subject_id=subject,
                actions=("rollback",),
                effective_from="2026-08-01T00:00:00+00:00",
            ),
        ),
    )


def _repo(tmp_path):
    repo = MedicalWritingArtifactLifecycleRepository(tmp_path / "rollback.sqlite3")
    policy = MedicalWritingArtifactRetentionPolicy(
        policy_id="approved-final",
        policy_revision=1,
        minimum_retain_until="2026-08-01T00:00:00+00:00",
        purge_eligible_at="2026-08-01T00:00:00+00:00",
    )
    current = repo.register(
        principal=_lifecycle_principal(),
        identity=MedicalWritingArtifactIdentity(
            tenant_id="tenant-a", project_id="project-1", document_id="protocol-1",
            generation_id="g1", export_job_id="export-g1", mode="approved_final", **HASHES,
        ),
        artifact_relpath="project-1/g1/protocol.docx",
        policy=policy,
        idempotency_key="register-g1",
        make_current=True,
        now=NOW,
    )
    target = repo.register(
        principal=_lifecycle_principal(),
        identity=MedicalWritingArtifactIdentity(
            tenant_id="tenant-a", project_id="project-1", document_id="protocol-1",
            generation_id="g2", export_job_id="export-g2", mode="approved_final", **HASHES,
        ),
        artifact_relpath="project-1/g2/protocol.docx",
        policy=policy,
        idempotency_key="register-g2",
        make_current=False,
        now=NOW,
    )
    return repo, current.record, target.record


def _intent(current, target, *, key="rollback-1", **overrides):
    values = {
        "request_id": "rollback-request-1",
        "project_id": "project-1",
        "document_id": "protocol-1",
        "current_artifact_id": current.artifact_id,
        "current_identity_sha256": artifact_identity_sha256(current),
        "target_artifact_id": target.artifact_id,
        "target_identity_sha256": artifact_identity_sha256(target),
        "expected_pointer_revision": 1,
        "reason": "restore reviewed generation",
        "idempotency_key": key,
        "client_actor": "user-1",
        "trace_id": "trace-rollback-1",
    }
    values.update(overrides)
    return MedicalWritingArtifactRollbackIntent(**values)


def test_rollback_requires_acl_and_moves_only_pointer_with_replay(tmp_path):
    repo, current, target = _repo(tmp_path)
    first = execute_artifact_rollback(
        repository=repo, principal=_principal(), policy=_policy(),
        intent=_intent(current, target), now=LATE,
    )
    replay = execute_artifact_rollback(
        repository=repo, principal=_principal(), policy=_policy(),
        intent=_intent(current, target), now=LATE,
    )
    assert first.lifecycle_result.allowed is True
    assert first.replayed is False
    assert replay.replayed is True
    assert first.lifecycle_result.event_id == replay.lifecycle_result.event_id
    assert repo.current_pointer(
        principal=_lifecycle_principal(), project_id="project-1", document_id="protocol-1"
    ).artifact_id == target.artifact_id
    assert repo.get(
        principal=_lifecycle_principal(), project_id="project-1", artifact_id=current.artifact_id
    ).current_pointer is False
    assert repo.get(
        principal=_lifecycle_principal(), project_id="project-1", artifact_id=current.artifact_id
    ).state == "active"
    events = repo.events(
        principal=_lifecycle_principal(), project_id="project-1", artifact_id=target.artifact_id
    )
    assert len(events) == 2
    assert [event["action"] for event in events] == ["registered", "rollback_succeeded"]


def test_rollback_denies_spoofed_actor_and_cross_tenant(tmp_path):
    repo, current, target = _repo(tmp_path)
    with pytest.raises(MedicalWritingPrincipalAclDenied) as exc_info:
        execute_artifact_rollback(
            repository=repo, principal=_principal(), policy=_policy(),
            intent=_intent(current, target, client_actor="spoofed"), now=LATE,
        )
    assert exc_info.value.reason_code == "client_actor_spoofed"
    with pytest.raises(MedicalWritingPrincipalAclDenied):
        execute_artifact_rollback(
            repository=repo, principal=_principal("tenant-b"), policy=_policy(),
            intent=_intent(current, target, client_actor="user-1"), now=LATE,
        )


def test_rollback_rejects_stale_pointer_and_identity_mismatch(tmp_path):
    repo, current, target = _repo(tmp_path)
    moved = execute_artifact_rollback(
        repository=repo, principal=_principal(), policy=_policy(),
        intent=_intent(current, target), now=LATE,
    )
    assert moved.replayed is False
    with pytest.raises(MedicalWritingArtifactLifecycleStale):
        execute_artifact_rollback(
            repository=repo, principal=_principal(), policy=_policy(),
            intent=_intent(current, target, key="rollback-stale"), now=LATE,
        )

    repo2, current2, target2 = _repo(tmp_path / "hash")
    with pytest.raises(MedicalWritingArtifactRollbackBindingMismatch):
        execute_artifact_rollback(
            repository=repo2, principal=_principal(), policy=_policy(),
            intent=_intent(current2, target2, current_identity_sha256="f" * 64), now=LATE,
        )


def test_rollback_rejects_purged_target_and_conflicting_replay(tmp_path):
    repo, current, target = _repo(tmp_path)
    purge = repo.request_purge(
        principal=_lifecycle_principal(), project_id="project-1", artifact_id=target.artifact_id,
        idempotency_key="purge-target", now=LATE,
    )
    assert purge.allowed is True
    repo.commit_purge(
        principal=_lifecycle_principal(), project_id="project-1", artifact_id=target.artifact_id,
        deletion_proof_sha256="5" * 64, idempotency_key="purge-target-commit", now=LATE,
    )
    with pytest.raises(MedicalWritingArtifactLifecycleConflict):
        execute_artifact_rollback(
            repository=repo, principal=_principal(), policy=_policy(),
            intent=_intent(current, target), now=LATE,
        )

    repo2, current2, target2 = _repo(tmp_path / "conflict")
    execute_artifact_rollback(
        repository=repo2, principal=_principal(), policy=_policy(),
        intent=_intent(current2, target2), now=LATE,
    )
    with pytest.raises(MedicalWritingArtifactLifecycleConflict):
        execute_artifact_rollback(
            repository=repo2, principal=_principal(), policy=_policy(),
            intent=_intent(current2, target2, reason="different reason"), now=LATE,
        )
