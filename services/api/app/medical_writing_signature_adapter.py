"""Provider-neutral electronic-signature evidence for medical-writing exports.

This module is intentionally not a signature provider.  It accepts a typed
verification result from an approved external adapter and binds that result to
one immutable artifact generation, source snapshot, and signer principal.
``word_verified`` and local hashes are renderer evidence only; neither can
create a signature record.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .medical_writing_principal_acl import (
    MedicalWritingAuthenticatedPrincipal,
    MedicalWritingPrincipalAclDenied,
)


MEDICAL_WRITING_SIGNATURE_SCHEMA = "medical_writing_signature_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MEANINGS = frozenset({"review", "approval", "authorship"})
_VERIFICATION_STATUSES = frozenset(
    {"verified", "denied", "unavailable", "revoked", "mismatch"}
)


class MedicalWritingSignatureError(ValueError):
    """Base error for malformed signature evidence."""


class MedicalWritingSignatureDenied(PermissionError):
    """Raised when an external verification result cannot be accepted."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


class MedicalWritingSignatureBindingMismatch(MedicalWritingSignatureError):
    """Raised when signature evidence is bound to another artifact generation."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalWritingSignatureError(f"{field_name} is required")
    return text


def _parse_datetime(value: Any, *, field_name: str) -> datetime:
    text = _require_text(value, field_name=field_name)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MedicalWritingSignatureError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise MedicalWritingSignatureError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _iso_datetime(value: Any, *, field_name: str) -> str:
    return _parse_datetime(value, field_name=field_name).isoformat()


def _sha256_text(value: Any, *, field_name: str) -> str:
    text = _require_text(value, field_name=field_name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise MedicalWritingSignatureError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return text


@dataclass(frozen=True)
class MedicalWritingSignatureVerification:
    """Evidence returned by an external, policy-approved signature adapter."""

    provider_id: str
    verification_reference: str
    assurance_reference: str
    status: str
    verified_at: str
    signed_payload_sha256: str
    reason_code: str = ""
    provider_signature_id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        provider_id = _require_text(self.provider_id, field_name="provider_id")
        verification_ref = _require_text(
            self.verification_reference, field_name="verification_reference"
        )
        assurance_ref = _require_text(
            self.assurance_reference, field_name="assurance_reference"
        )
        status = _require_text(self.status, field_name="status").lower()
        if status not in _VERIFICATION_STATUSES:
            raise MedicalWritingSignatureError(
                f"unsupported signature verification status: {status}"
            )
        verified_at = _iso_datetime(self.verified_at, field_name="verified_at")
        payload_hash = _sha256_text(
            self.signed_payload_sha256, field_name="signed_payload_sha256"
        )
        reason = str(self.reason_code or "").strip()
        provider_signature_id = str(self.provider_signature_id or "").strip()
        if status == "verified" and (reason or not provider_signature_id):
            raise MedicalWritingSignatureError(
                "verified signature evidence requires provider_signature_id and no denial reason"
            )
        if status != "verified" and not reason:
            raise MedicalWritingSignatureError(
                "non-verified signature evidence requires reason_code"
            )
        return {
            "schema_version": MEDICAL_WRITING_SIGNATURE_SCHEMA,
            "provider_id": provider_id,
            "verification_reference": verification_ref,
            "assurance_reference": assurance_ref,
            "status": status,
            "verified_at": verified_at,
            "signed_payload_sha256": payload_hash,
            "reason_code": reason,
            "provider_signature_id": provider_signature_id,
        }


@dataclass(frozen=True)
class MedicalWritingSignatureRecord:
    """Immutable value object for one verified signature binding."""

    signature_id: str
    artifact_id: str
    document_id: str
    meaning: str
    signer_subject_id: str
    signer_tenant_id: str
    signer_display_name: str
    signer_role: str
    signed_at: str
    provider_id: str
    verification_reference: str
    assurance_reference: str
    provider_signature_id: str
    signed_payload_sha256: str
    source_snapshot_sha256: str
    docx_sha256: str
    manifest_sha256: str
    principal_identity_sha256: str
    verification_identity_sha256: str
    audit_event_id: str
    signature_identity_sha256: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": MEDICAL_WRITING_SIGNATURE_SCHEMA,
            "signature_id": self.signature_id,
            "artifact_id": self.artifact_id,
            "document_id": self.document_id,
            "meaning": self.meaning,
            "signer_subject_id": self.signer_subject_id,
            "signer_tenant_id": self.signer_tenant_id,
            "signer_display_name": self.signer_display_name,
            "signer_role": self.signer_role,
            "signed_at": self.signed_at,
            "provider_id": self.provider_id,
            "verification_reference": self.verification_reference,
            "assurance_reference": self.assurance_reference,
            "provider_signature_id": self.provider_signature_id,
            "signed_payload_sha256": self.signed_payload_sha256,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "docx_sha256": self.docx_sha256,
            "manifest_sha256": self.manifest_sha256,
            "principal_identity_sha256": self.principal_identity_sha256,
            "verification_identity_sha256": self.verification_identity_sha256,
            "audit_event_id": self.audit_event_id,
            "signature_identity_sha256": self.signature_identity_sha256,
            "word_verified_is_not_signature": True,
        }


def create_verified_signature_record(
    *,
    signature_id: str,
    artifact_id: str,
    document_id: str,
    meaning: str,
    signer_display_name: str,
    signer_role: str,
    signed_at: str,
    principal: MedicalWritingAuthenticatedPrincipal,
    verification: MedicalWritingSignatureVerification,
    signed_payload_sha256: str,
    source_snapshot_sha256: str,
    docx_sha256: str,
    manifest_sha256: str,
    audit_event_id: str,
    expected_artifact_id: Optional[str] = None,
    expected_source_snapshot_sha256: Optional[str] = None,
    expected_docx_sha256: Optional[str] = None,
    expected_manifest_sha256: Optional[str] = None,
) -> MedicalWritingSignatureRecord:
    """Create a verified record only after all external evidence is bound."""

    signature_id = _require_text(signature_id, field_name="signature_id")
    artifact_id = _require_text(artifact_id, field_name="artifact_id")
    document_id = _require_text(document_id, field_name="document_id")
    meaning = _require_text(meaning, field_name="meaning").lower()
    if meaning not in _MEANINGS:
        raise MedicalWritingSignatureError(
            "meaning must be one of review, approval, or authorship"
        )
    display_name = _require_text(signer_display_name, field_name="signer_display_name")
    signer_role = _require_text(signer_role, field_name="signer_role")
    signed_iso = _iso_datetime(signed_at, field_name="signed_at")
    payload_hash = _sha256_text(signed_payload_sha256, field_name="signed_payload_sha256")
    source_hash = _sha256_text(source_snapshot_sha256, field_name="source_snapshot_sha256")
    docx_hash = _sha256_text(docx_sha256, field_name="docx_sha256")
    manifest_hash = _sha256_text(manifest_sha256, field_name="manifest_sha256")
    audit_event_id = _require_text(audit_event_id, field_name="audit_event_id")

    expected_pairs = (
        (expected_artifact_id, artifact_id, "artifact_id"),
        (expected_source_snapshot_sha256, source_hash, "source_snapshot_sha256"),
        (expected_docx_sha256, docx_hash, "docx_sha256"),
        (expected_manifest_sha256, manifest_hash, "manifest_sha256"),
    )
    for expected, actual, field_name in expected_pairs:
        if expected is not None and _require_text(expected, field_name=f"expected_{field_name}") != actual:
            raise MedicalWritingSignatureBindingMismatch(
                f"signature {field_name} does not match expected artifact binding"
            )

    try:
        principal.validate(now=signed_iso)
    except MedicalWritingPrincipalAclDenied as exc:
        raise MedicalWritingSignatureDenied(
            f"signer_principal_{exc.reason_code}"
        ) from exc
    principal_payload = principal.as_dict()
    verification_payload = verification.as_dict()
    if verification_payload["status"] != "verified":
        raise MedicalWritingSignatureDenied(
            f"provider_verification_{verification_payload['reason_code']}"
        )
    if verification_payload["signed_payload_sha256"] != payload_hash:
        raise MedicalWritingSignatureBindingMismatch(
            "provider signed payload hash does not match the record payload"
        )

    provider_verified_at = _parse_datetime(
        verification_payload["verified_at"], field_name="verified_at"
    )
    signed_dt = _parse_datetime(signed_iso, field_name="signed_at")
    if provider_verified_at < signed_dt:
        raise MedicalWritingSignatureBindingMismatch(
            "provider verification predates the signed timestamp"
        )

    base = {
        "schema_version": MEDICAL_WRITING_SIGNATURE_SCHEMA,
        "signature_id": signature_id,
        "artifact_id": artifact_id,
        "document_id": document_id,
        "meaning": meaning,
        "signer_subject_id": principal_payload["subject_id"],
        "signer_tenant_id": principal_payload["tenant_id"],
        "signer_display_name": display_name,
        "signer_role": signer_role,
        "signed_at": signed_iso,
        "provider_id": verification_payload["provider_id"],
        "verification_reference": verification_payload["verification_reference"],
        "assurance_reference": verification_payload["assurance_reference"],
        "provider_signature_id": verification_payload["provider_signature_id"],
        "signed_payload_sha256": payload_hash,
        "source_snapshot_sha256": source_hash,
        "docx_sha256": docx_hash,
        "manifest_sha256": manifest_hash,
        "principal_identity_sha256": principal.identity_hash,
        "verification_identity_sha256": _sha256(verification_payload),
        "audit_event_id": audit_event_id,
        "word_verified_is_not_signature": True,
    }
    signature_identity_sha256 = _sha256(base)
    return MedicalWritingSignatureRecord(
        signature_id=signature_id,
        artifact_id=artifact_id,
        document_id=document_id,
        meaning=meaning,
        signer_subject_id=principal_payload["subject_id"],
        signer_tenant_id=principal_payload["tenant_id"],
        signer_display_name=display_name,
        signer_role=signer_role,
        signed_at=signed_iso,
        provider_id=verification_payload["provider_id"],
        verification_reference=verification_payload["verification_reference"],
        assurance_reference=verification_payload["assurance_reference"],
        provider_signature_id=verification_payload["provider_signature_id"],
        signed_payload_sha256=payload_hash,
        source_snapshot_sha256=source_hash,
        docx_sha256=docx_hash,
        manifest_sha256=manifest_hash,
        principal_identity_sha256=principal.identity_hash,
        verification_identity_sha256=_sha256(verification_payload),
        audit_event_id=audit_event_id,
        signature_identity_sha256=signature_identity_sha256,
    )
