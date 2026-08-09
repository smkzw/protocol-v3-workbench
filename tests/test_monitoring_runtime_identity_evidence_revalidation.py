from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from services.api.app.monitoring_runtime_identity_evidence_revalidation import (
    MonitoringRuntimeIdentityEvidenceIssueCode,
    RUNTIME_IDENTITY_EVIDENCE_SCHEMA_VERSION,
    revalidate_runtime_identity_evidence,
)


NOW = datetime(2026, 8, 4, 6, 0, tzinfo=timezone.utc)
PROJECTS = (
    "proj_mgk10_sar_real",
    "proj_rux_03_002",
    "proj_my008_3_02_candidate",
    "proj_my008_3_01_candidate",
    "proj_my009_uc",
)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _principal() -> dict:
    value = {
        "schema_version": "monitoring_runtime_principal_v1",
        "principal_id": "controlled-loop-service",
        "tenant_id": "tenant-kangzhe",
        "roles": ["medical_manager"],
        "project_scope": list(PROJECTS),
        "issued_at": (NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "authenticated": True,
        "authn_method": "host-verified-session",
        "session_id_sha256": "a" * 64,
        "directory_revision": "directory-v1",
        "verification_ref_sha256": "b" * 64,
        "authn_context": "server-verified",
        "assurance": "host-attested",
    }
    return value


def _payload(*, status: str = "not_proven", attestation: dict | None = None) -> dict:
    value = {
        "schema_version": RUNTIME_IDENTITY_EVIDENCE_SCHEMA_VERSION,
        "read_only": True,
        "observed_status": status,
        "evidence_ref": "runtime-identity-current",
        "verified_at": NOW.isoformat(),
        "tenant_id": "tenant-kangzhe",
        "principal": _principal(),
        "principal_identity_hash": _digest(_principal()),
        "authority": {
            "runtime_activation_permitted": False,
            "provider_call_permitted": False,
            "write_permitted": False,
            "migration_ready": False,
            "medical_authority_granted": False,
        },
    }
    if attestation is not None:
        value["attestation"] = attestation
    value["evidence_sha256"] = _digest(value)
    return value


def _attestation(*, host_verified: bool = True) -> dict:
    value = {
        "attestation_ref": "host-attestation-current",
        "verification_method": "host_server_verified_envelope_v1",
        "host_verified": host_verified,
    }
    value["attestation_sha256"] = _digest(value)
    return value


def test_missing_evidence_is_blocked_and_never_authoritative() -> None:
    report = revalidate_runtime_identity_evidence(None, expected_project_ids=PROJECTS, now=NOW)
    assert report.status == "blocked"
    assert report.runtime_identity_verified is False
    assert MonitoringRuntimeIdentityEvidenceIssueCode.PAYLOAD_MISSING in {
        item.code for item in report.issues
    }
    assert report.runtime_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.to_upstream_evidence_row()["status"] == "missing"


def test_not_proven_snapshot_can_be_fresh_without_becoming_verified() -> None:
    report = revalidate_runtime_identity_evidence(
        _payload(), expected_project_ids=PROJECTS, now=NOW
    )
    assert report.status == "fresh"
    assert report.evidence_fresh is True
    assert report.runtime_identity_verified is False
    assert report.attestation_verified is False
    assert report.project_scope_complete is True
    assert report.write_permitted is False
    assert report.to_upstream_evidence_row()["status"] == "not_proven"


def test_proven_status_requires_a_host_attestation_verifier() -> None:
    report = revalidate_runtime_identity_evidence(
        _payload(status="proven", attestation=_attestation()),
        expected_project_ids=PROJECTS,
        now=NOW,
    )
    assert report.status == "blocked"
    assert report.runtime_identity_verified is False
    assert MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_VERIFIER_MISSING in {
        item.code for item in report.issues
    }
    assert report.to_upstream_evidence_row()["status"] == "blocked"


def test_proven_status_requires_verifier_acceptance() -> None:
    payload = _payload(status="proven", attestation=_attestation())
    rejected = revalidate_runtime_identity_evidence(
        payload,
        expected_project_ids=PROJECTS,
        now=NOW,
        attestation_verifier=lambda _attestation: False,
    )
    assert rejected.status == "blocked"
    assert rejected.runtime_identity_verified is False
    assert MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_REJECTED in {
        item.code for item in rejected.issues
    }


def test_verified_attestation_can_prove_identity_but_not_grant_authority() -> None:
    payload = _payload(status="proven", attestation=_attestation())
    accepted = revalidate_runtime_identity_evidence(
        payload,
        expected_project_ids=PROJECTS,
        now=NOW,
        attestation_verifier=lambda value: value["attestation_ref"] == "host-attestation-current",
    )
    assert accepted.status == "fresh"
    assert accepted.runtime_identity_verified is True
    assert accepted.attestation_verified is True
    assert accepted.runtime_activation_permitted is False
    assert accepted.provider_call_permitted is False
    assert accepted.medical_authority_granted is False
    assert accepted.to_upstream_evidence_row()["status"] == "proven"


def test_digest_tamper_and_raw_session_material_fail_closed() -> None:
    payload = _payload()
    payload["principal"] = deepcopy(payload["principal"])
    payload["principal"]["session_id"] = "raw-secret"
    tampered = revalidate_runtime_identity_evidence(
        payload, expected_project_ids=PROJECTS, now=NOW
    )
    codes = {item.code for item in tampered.issues}
    assert MonitoringRuntimeIdentityEvidenceIssueCode.SECRET_FIELD_PRESENT in codes
    assert MonitoringRuntimeIdentityEvidenceIssueCode.EVIDENCE_HASH_MISMATCH in codes


def test_identity_evidence_hashes_require_exact_lowercase_bytes() -> None:
    payload = _payload()
    payload["evidence_sha256"] = payload["evidence_sha256"].upper()
    evidence_report = revalidate_runtime_identity_evidence(
        payload,
        expected_project_ids=PROJECTS,
        now=NOW,
    )
    assert MonitoringRuntimeIdentityEvidenceIssueCode.EVIDENCE_HASH_INVALID in {
        item.code for item in evidence_report.issues
    }

    payload = _payload()
    payload["principal_identity_hash"] = payload[
        "principal_identity_hash"
    ].upper()
    payload["evidence_sha256"] = _digest(payload)
    principal_report = revalidate_runtime_identity_evidence(
        payload,
        expected_project_ids=PROJECTS,
        now=NOW,
    )
    assert MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_IDENTITY_HASH_INVALID in {
        item.code for item in principal_report.issues
    }

    payload = _payload(status="proven", attestation=_attestation())
    payload["attestation"]["attestation_sha256"] = payload[
        "attestation"
    ]["attestation_sha256"].upper()
    payload["evidence_sha256"] = _digest(payload)
    attestation_report = revalidate_runtime_identity_evidence(
        payload,
        expected_project_ids=PROJECTS,
        now=NOW,
        attestation_verifier=lambda _value: True,
    )
    assert MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_HASH_INVALID in {
        item.code for item in attestation_report.issues
    }


def test_scope_or_time_drift_blocks_even_with_a_valid_shape() -> None:
    payload = _payload()
    payload["principal"] = deepcopy(payload["principal"])
    payload["principal"]["project_scope"] = [PROJECTS[0]]
    payload["principal_identity_hash"] = _digest(payload["principal"])
    payload["evidence_sha256"] = _digest({key: value for key, value in payload.items() if key != "evidence_sha256"})
    report = revalidate_runtime_identity_evidence(
        payload, expected_project_ids=PROJECTS, now=NOW
    )
    assert report.status == "blocked"
    assert MonitoringRuntimeIdentityEvidenceIssueCode.PROJECT_SCOPE_INCOMPLETE in {
        item.code for item in report.issues
    }
