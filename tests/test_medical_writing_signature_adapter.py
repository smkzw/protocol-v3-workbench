from __future__ import annotations

import json

import pytest

from services.api.app.medical_writing_principal_acl import MedicalWritingAuthenticatedPrincipal
from services.api.app.medical_writing_signature_adapter import (
    MedicalWritingSignatureBindingMismatch,
    MedicalWritingSignatureDenied,
    MedicalWritingSignatureError,
    MedicalWritingSignatureVerification,
    create_verified_signature_record,
)


ISSUED = "2026-07-31T00:00:00+00:00"
SIGNED = "2026-08-02T00:00:00+00:00"
VERIFIED = "2026-08-02T00:01:00+00:00"
EXPIRES = "2026-08-03T00:00:00+00:00"
HASHES = {
    "signed_payload_sha256": "1" * 64,
    "source_snapshot_sha256": "2" * 64,
    "docx_sha256": "3" * 64,
    "manifest_sha256": "4" * 64,
}


def _principal(*, expires: str = EXPIRES):
    return MedicalWritingAuthenticatedPrincipal(
        subject_id="user-1",
        tenant_id="tenant-a",
        assurance="synthetic-assurance",
        issued_at=ISSUED,
        expires_at=expires,
        authenticated=True,
        role="medical_manager",
        authn_context="synthetic-context",
        session_ref_sha256="a" * 64,
    )


def _verification(**overrides):
    values = {
        "provider_id": "approved-signature-adapter",
        "verification_reference": "verification-ref-1",
        "assurance_reference": "assurance-ref-1",
        "status": "verified",
        "verified_at": VERIFIED,
        "signed_payload_sha256": HASHES["signed_payload_sha256"],
        "provider_signature_id": "provider-signature-1",
    }
    values.update(overrides)
    return MedicalWritingSignatureVerification(**values)


def _create(**overrides):
    values = {
        "signature_id": "signature-1",
        "artifact_id": "mwartifact-1",
        "document_id": "protocol-1",
        "meaning": "approval",
        "signer_display_name": "Synthetic Medical Manager",
        "signer_role": "medical_manager",
        "signed_at": SIGNED,
        "principal": _principal(),
        "verification": _verification(),
        "audit_event_id": "audit-signature-1",
        "expected_artifact_id": "mwartifact-1",
        "expected_source_snapshot_sha256": HASHES["source_snapshot_sha256"],
        "expected_docx_sha256": HASHES["docx_sha256"],
        "expected_manifest_sha256": HASHES["manifest_sha256"],
        **HASHES,
    }
    values.update(overrides)
    return create_verified_signature_record(**values)


def test_verified_record_binds_signer_provider_and_payload_without_word_approval():
    record = _create()
    payload = record.as_dict()
    assert payload["meaning"] == "approval"
    assert payload["signer_subject_id"] == "user-1"
    assert payload["provider_id"] == "approved-signature-adapter"
    assert payload["signed_payload_sha256"] == HASHES["signed_payload_sha256"]
    assert payload["word_verified_is_not_signature"] is True
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "synthetic-context" not in serialized
    assert "session_ref_sha256" not in serialized
    assert len(record.signature_identity_sha256) == 64
    assert _create().signature_identity_sha256 == record.signature_identity_sha256


@pytest.mark.parametrize("status", ["denied", "unavailable", "revoked", "mismatch"])
def test_non_verified_provider_evidence_fails_closed(status):
    with pytest.raises(MedicalWritingSignatureDenied) as exc_info:
        _create(verification=_verification(status=status, reason_code=f"{status}_reason", provider_signature_id=""))
    assert exc_info.value.reason_code == f"provider_verification_{status}_reason"


def test_expired_signer_and_provider_verification_before_signed_time_fail_closed():
    with pytest.raises(MedicalWritingSignatureDenied) as exc_info:
        _create(principal=_principal(expires=SIGNED))
    assert exc_info.value.reason_code == "signer_principal_principal_expired"

    with pytest.raises(MedicalWritingSignatureBindingMismatch):
        _create(verification=_verification(verified_at="2026-08-01T23:59:00+00:00"))


def test_payload_and_artifact_binding_mismatches_fail_closed():
    with pytest.raises(MedicalWritingSignatureBindingMismatch):
        _create(expected_artifact_id="other-artifact")
    with pytest.raises(MedicalWritingSignatureBindingMismatch):
        _create(
            verification=_verification(signed_payload_sha256="9" * 64)
        )


def test_invalid_meaning_hash_and_provider_evidence_are_rejected():
    with pytest.raises(MedicalWritingSignatureError):
        _create(meaning="automatic_approval")
    with pytest.raises(MedicalWritingSignatureError):
        _create(docx_sha256="not-a-hash")
    with pytest.raises(MedicalWritingSignatureError):
        _create(verification=_verification(status="verified", provider_signature_id="", reason_code=""))
    with pytest.raises(MedicalWritingSignatureError):
        _verification(status="unknown", reason_code="bad").as_dict()


def test_missing_provider_assurance_and_reference_are_rejected():
    with pytest.raises(MedicalWritingSignatureError):
        _create(verification=_verification(assurance_reference=""))
    with pytest.raises(MedicalWritingSignatureError):
        _create(verification=_verification(verification_reference=""))
