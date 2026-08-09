"""Read-only revalidation of the controlled runtime-identity evidence seam.

The real-project LOOP needs a separately evidenced, server-verified principal
before a provider or controlled runtime can be considered.  The existing
runtime-principal module validates an in-memory host envelope; this module
validates the *persisted evidence handoff* around that envelope.  It does not
authenticate a user, parse a token, call a provider, start a runtime, or grant
any authority.

The ``proven`` branch requires an explicit host-attestation verifier supplied
by the caller.  A self-asserted ``host_verified`` boolean is never sufficient.
Without that verifier, missing or ``not_proven`` evidence remains a fresh
diagnostic observation, while ``runtime_identity_verified`` stays false.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any

from .monitoring_identity_authorization import MonitoringRole


RUNTIME_IDENTITY_EVIDENCE_SCHEMA_VERSION = (
    "medical_monitoring_runtime_identity_evidence_v1"
)
RUNTIME_IDENTITY_EVIDENCE_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_runtime_identity_evidence_revalidation_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ALLOWED_STATUS = {"missing", "not_proven", "blocked", "proven"}
_ALLOWED_VERIFICATION_METHOD = "host_server_verified_envelope_v1"
_SECRET_KEYS = {
    "access_token",
    "authorization",
    "cookie",
    "password",
    "refresh_token",
    "secret",
    "session_id",
    "token",
}
_PRINCIPAL_KEYS = {
    "schema_version",
    "principal_id",
    "tenant_id",
    "roles",
    "project_scope",
    "issued_at",
    "expires_at",
    "authenticated",
    "authn_method",
    "session_id_sha256",
    "directory_revision",
    "verification_ref_sha256",
    "authn_context",
    "assurance",
}


class MonitoringRuntimeIdentityEvidenceError(ValueError):
    """Raised when a runtime-identity evidence request is malformed."""


class MonitoringRuntimeIdentityEvidenceIssueCode(str, Enum):
    PAYLOAD_MISSING = "payload_missing"
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    SCHEMA_INVALID = "schema_invalid"
    FIELD_INVALID = "field_invalid"
    STATUS_INVALID = "status_invalid"
    STATUS_CONTRADICTION = "status_contradiction"
    AUTHORITY_FLAG_MISSING = "authority_flag_missing"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    SECRET_FIELD_PRESENT = "secret_field_present"
    EVIDENCE_REF_INVALID = "evidence_ref_invalid"
    EVIDENCE_HASH_INVALID = "evidence_hash_invalid"
    EVIDENCE_HASH_MISMATCH = "evidence_hash_mismatch"
    EVIDENCE_PAIR_INCOMPLETE = "evidence_pair_incomplete"
    PRINCIPAL_MISSING = "principal_missing"
    PRINCIPAL_SHAPE_INVALID = "principal_shape_invalid"
    PRINCIPAL_IDENTITY_HASH_INVALID = "principal_identity_hash_invalid"
    PRINCIPAL_IDENTITY_HASH_MISMATCH = "principal_identity_hash_mismatch"
    PRINCIPAL_UNAUTHENTICATED = "principal_unauthenticated"
    PRINCIPAL_TIME_INVALID = "principal_time_invalid"
    PRINCIPAL_TIME_STALE = "principal_time_stale"
    TENANT_MISMATCH = "tenant_mismatch"
    PROJECT_SCOPE_INVALID = "project_scope_invalid"
    PROJECT_SCOPE_INCOMPLETE = "project_scope_incomplete"
    ATTESTATION_MISSING = "attestation_missing"
    ATTESTATION_SHAPE_INVALID = "attestation_shape_invalid"
    ATTESTATION_REF_INVALID = "attestation_ref_invalid"
    ATTESTATION_HASH_INVALID = "attestation_hash_invalid"
    ATTESTATION_HASH_MISMATCH = "attestation_hash_mismatch"
    ATTESTATION_METHOD_INVALID = "attestation_method_invalid"
    ATTESTATION_VERIFIER_MISSING = "attestation_verifier_missing"
    ATTESTATION_REJECTED = "attestation_rejected"


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise MonitoringRuntimeIdentityEvidenceError(
            "runtime-identity evidence must be JSON serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _safe_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_SAFE_REF_RE.fullmatch(value.strip()))


def _parse_time(value: Any, *, subject: str) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _has_secret_key(value: Any, *, path: str = "payload") -> str | None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = _text(key).lower()
            current = f"{path}.{key_text}" if key_text else path
            if key_text in _SECRET_KEYS:
                return current
            found = _has_secret_key(child, path=current)
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _has_secret_key(child, path=f"{path}[{index}]")
            if found:
                return found
    return None


@dataclass(frozen=True)
class MonitoringRuntimeIdentityEvidenceIssue:
    code: MonitoringRuntimeIdentityEvidenceIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise MonitoringRuntimeIdentityEvidenceError(
                "runtime-identity issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class MonitoringRuntimeIdentityEvidenceReport:
    """Freshness result; authority and mutation flags are always false."""

    status: str
    evidence_fresh: bool
    runtime_identity_verified: bool
    principal_payload_valid: bool
    attestation_payload_valid: bool
    attestation_verified: bool
    principal_time_valid: bool
    project_scope_complete: bool
    observed_status: str
    evidence_ref: str
    evidence_sha256: str
    principal_identity_hash: str
    attestation_ref: str = ""
    attestation_sha256: str = ""
    issue_count: int = 0
    issues: tuple[MonitoringRuntimeIdentityEvidenceIssue, ...] = ()
    schema_version: str = RUNTIME_IDENTITY_EVIDENCE_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    runtime_activation_permitted: bool = False
    provider_call_permitted: bool = False
    write_permitted: bool = False
    migration_ready: bool = False
    medical_authority_granted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != RUNTIME_IDENTITY_EVIDENCE_REVALIDATION_SCHEMA_VERSION:
            raise MonitoringRuntimeIdentityEvidenceError(
                "unsupported runtime-identity evidence revalidation schema"
            )
        if self.status not in {"fresh", "blocked"}:
            raise MonitoringRuntimeIdentityEvidenceError("status must be fresh or blocked")
        if self.observed_status not in _ALLOWED_STATUS:
            raise MonitoringRuntimeIdentityEvidenceError("observed_status is invalid")
        for name in (
            "read_only",
            "authority_granted",
            "runtime_activation_permitted",
            "provider_call_permitted",
            "write_permitted",
            "migration_ready",
            "medical_authority_granted",
        ):
            expected = True if name == "read_only" else False
            if getattr(self, name) is not expected:
                raise MonitoringRuntimeIdentityEvidenceError(f"{name} must remain {expected}")
        for name in (
            "evidence_fresh",
            "runtime_identity_verified",
            "principal_payload_valid",
            "attestation_payload_valid",
            "attestation_verified",
            "principal_time_valid",
            "project_scope_complete",
        ):
            if not isinstance(getattr(self, name), bool):
                raise MonitoringRuntimeIdentityEvidenceError(f"{name} must be boolean")
        if isinstance(self.issue_count, bool) or not isinstance(self.issue_count, int) or self.issue_count < 0:
            raise MonitoringRuntimeIdentityEvidenceError("issue_count must be a non-negative integer")
        issues = tuple(self.issues)
        if any(not isinstance(item, MonitoringRuntimeIdentityEvidenceIssue) for item in issues):
            raise MonitoringRuntimeIdentityEvidenceError("issues contain an invalid value")
        if self.issue_count != len(issues):
            raise MonitoringRuntimeIdentityEvidenceError("issue_count must equal len(issues)")
        if self.runtime_identity_verified and not (
            self.observed_status == "proven"
            and self.principal_payload_valid
            and self.attestation_payload_valid
            and self.attestation_verified
            and self.principal_time_valid
            and self.project_scope_complete
            and not issues
        ):
            raise MonitoringRuntimeIdentityEvidenceError(
                "runtime_identity_verified requires a complete verified evidence set"
            )
        expected_fresh = not issues
        if self.evidence_fresh != expected_fresh or (self.status == "fresh") != expected_fresh:
            raise MonitoringRuntimeIdentityEvidenceError(
                "status does not match evidence freshness"
            )
        object.__setattr__(self, "evidence_ref", _text(self.evidence_ref))
        for name in (
            "evidence_sha256",
            "principal_identity_hash",
            "attestation_sha256",
        ):
            value = getattr(self, name)
            canonical = value if _valid_sha(value) else ""
            object.__setattr__(self, name, canonical)
        object.__setattr__(self, "attestation_ref", _text(self.attestation_ref))
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "runtime_identity_verified": self.runtime_identity_verified,
            "principal_payload_valid": self.principal_payload_valid,
            "attestation_payload_valid": self.attestation_payload_valid,
            "attestation_verified": self.attestation_verified,
            "principal_time_valid": self.principal_time_valid,
            "project_scope_complete": self.project_scope_complete,
            "observed_status": self.observed_status,
            "evidence_ref": self.evidence_ref,
            "evidence_sha256": self.evidence_sha256,
            "principal_identity_hash": self.principal_identity_hash,
            "attestation_ref": self.attestation_ref,
            "attestation_sha256": self.attestation_sha256,
            "issue_count": self.issue_count,
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "runtime_activation_permitted": self.runtime_activation_permitted,
            "provider_call_permitted": self.provider_call_permitted,
            "write_permitted": self.write_permitted,
            "migration_ready": self.migration_ready,
            "medical_authority_granted": self.medical_authority_granted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}

    def to_upstream_evidence_row(self) -> dict[str, str]:
        """Project this diagnostic result into the canonical upstream row shape.

        A blocked report can never be projected as ``proven``.  This helper is
        intentionally a plain mapping so the caller still has to pass it
        through ``assess_real_loop_upstream_assembly``; it does not activate a
        gate or persist a decision.
        """

        if self.observed_status == "missing":
            status = "missing"
        elif self.status != "fresh":
            status = "blocked"
        elif self.runtime_identity_verified:
            status = "proven"
        else:
            status = self.observed_status
        return {
            "gate": "runtime_identity_verified",
            "evidence_kind": "runtime_identity_revalidation",
            "evidence_ref": self.evidence_ref,
            "evidence_sha256": self.evidence_sha256,
            "status": status,
        }


def _issue(
    issues: list[MonitoringRuntimeIdentityEvidenceIssue],
    code: MonitoringRuntimeIdentityEvidenceIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(
        MonitoringRuntimeIdentityEvidenceIssue(
            code=code,
            subject=_text(subject) or "payload",
            detail=_text(detail) or "invalid runtime-identity evidence",
        )
    )


def revalidate_runtime_identity_evidence(
    payload: Mapping[str, Any] | None,
    *,
    expected_project_ids: Iterable[str] = (),
    now: datetime | None = None,
    attestation_verifier: Callable[[Mapping[str, Any]], bool] | None = None,
) -> MonitoringRuntimeIdentityEvidenceReport:
    """Revalidate a persisted runtime-identity evidence handoff.

    ``attestation_verifier`` is an explicit host-controlled seam.  It is
    required only when the submitted observation claims ``proven``.  This
    function never treats a boolean in the document as cryptographic proof.
    """

    issues: list[MonitoringRuntimeIdentityEvidenceIssue] = []
    expected_projects = tuple(dict.fromkeys(_text(item) for item in expected_project_ids if _text(item)))
    if payload is None:
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.PAYLOAD_MISSING,
            "payload",
            "no runtime-identity evidence document was supplied",
        )
        return _build_report(
            issues=issues,
            observed_status="missing",
            evidence_ref="",
            evidence_sha256="",
            principal_identity_hash="",
            principal_payload_valid=False,
            attestation_payload_valid=False,
            attestation_verified=False,
            principal_time_valid=False,
            project_scope_complete=False,
            runtime_identity_verified=False,
        )
    if not isinstance(payload, Mapping):
        raise MonitoringRuntimeIdentityEvidenceError("payload must be an object or None")

    secret_path = _has_secret_key(payload)
    if secret_path:
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.SECRET_FIELD_PRESENT,
            secret_path,
            "runtime evidence must never carry raw session, token, cookie or secret material",
        )
    if payload.get("schema_version") != RUNTIME_IDENTITY_EVIDENCE_SCHEMA_VERSION:
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.SCHEMA_INVALID,
            "schema_version",
            "unexpected runtime-identity evidence schema",
        )
    if payload.get("read_only") is not True:
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.FIELD_INVALID,
            "read_only",
            "runtime-identity evidence must declare read_only=true",
        )
    observed_status = _text(payload.get("observed_status"))
    if observed_status not in _ALLOWED_STATUS:
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.STATUS_INVALID,
            "observed_status",
            "observed_status must be missing, not_proven, blocked or proven",
        )
        observed_status = "blocked"

    evidence_ref = _text(payload.get("evidence_ref"))
    evidence_sha256 = payload.get("evidence_sha256")
    if not isinstance(evidence_sha256, str):
        evidence_sha256 = ""
    if not _safe_ref(evidence_ref):
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.EVIDENCE_REF_INVALID,
            "evidence_ref",
            "evidence_ref must be an opaque safe identifier",
        )
    if not _valid_sha(evidence_sha256):
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.EVIDENCE_HASH_INVALID,
            "evidence_sha256",
            "evidence_sha256 must be a lowercase SHA-256",
        )
    else:
        without_digest = dict(payload)
        without_digest.pop("evidence_sha256", None)
        if _digest(without_digest) != evidence_sha256:
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.EVIDENCE_HASH_MISMATCH,
                "evidence_sha256",
                "evidence_sha256 does not match the canonical evidence payload",
            )
    if bool(evidence_ref) != bool(evidence_sha256):
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.EVIDENCE_PAIR_INCOMPLETE,
            "evidence_ref",
            "evidence_ref and evidence_sha256 must be supplied together",
        )

    authority = payload.get("authority")
    if not isinstance(authority, Mapping):
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.AUTHORITY_FLAG_MISSING,
            "authority",
            "authority must explicitly contain all false flags",
        )
    else:
        for key in (
            "runtime_activation_permitted",
            "provider_call_permitted",
            "write_permitted",
            "migration_ready",
            "medical_authority_granted",
        ):
            if key not in authority:
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.AUTHORITY_FLAG_MISSING,
                    f"authority.{key}",
                    "authority flag is required and must remain false",
                )
            elif authority[key] is not False:
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.AUTHORITY_FLAG_TRUE,
                    f"authority.{key}",
                    "runtime-identity evidence cannot grant authority",
                )

    principal = payload.get("principal")
    principal_identity_hash = payload.get("principal_identity_hash")
    if not isinstance(principal_identity_hash, str):
        principal_identity_hash = ""
    principal_valid = True
    principal_time_valid = False
    project_scope_complete = False
    principal_tenant = ""
    if not isinstance(principal, Mapping):
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_MISSING,
            "principal",
            "a public principal snapshot is required; raw session material is not accepted",
        )
        principal_valid = False
    else:
        unknown_keys = set(principal) - _PRINCIPAL_KEYS
        if unknown_keys:
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_SHAPE_INVALID,
                "principal",
                f"principal contains unsupported fields: {sorted(map(str, unknown_keys))}",
            )
            principal_valid = False
        if principal.get("schema_version") != "monitoring_runtime_principal_v1":
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_SHAPE_INVALID,
                "principal.schema_version",
                "principal snapshot has an unexpected schema",
            )
            principal_valid = False
        for key in ("principal_id", "tenant_id", "authn_method", "directory_revision"):
            if not _text(principal.get(key)):
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_SHAPE_INVALID,
                    f"principal.{key}",
                    "principal field must be a non-empty string",
                )
                principal_valid = False
        principal_tenant = _text(principal.get("tenant_id"))
        if principal.get("authenticated") is not True:
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_UNAUTHENTICATED,
                "principal.authenticated",
                "runtime identity must be explicitly authenticated",
            )
            principal_valid = False
        roles = principal.get("roles")
        if (
            not isinstance(roles, list)
            or not roles
            or len(roles) != len(set(roles))
            or any(not _text(role) for role in roles)
        ):
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_SHAPE_INVALID,
                "principal.roles",
                "roles must be a non-empty unique string array",
            )
            principal_valid = False
        else:
            for role in roles:
                try:
                    MonitoringRole(role)
                except ValueError:
                    _issue(
                        issues,
                        MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_SHAPE_INVALID,
                        "principal.roles",
                        f"unsupported monitoring role: {role}",
                    )
                    principal_valid = False
        scope = principal.get("project_scope")
        if (
            not isinstance(scope, list)
            or not scope
            or len(scope) != len(set(scope))
            or any(not _text(item) for item in scope)
            or "*" in scope
        ):
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PROJECT_SCOPE_INVALID,
                "principal.project_scope",
                "project_scope must be a non-empty unique list without wildcard scope",
            )
            principal_valid = False
            scope = []
        issued = _parse_time(principal.get("issued_at"), subject="principal.issued_at")
        expires = _parse_time(principal.get("expires_at"), subject="principal.expires_at")
        checked_at = _parse_time(payload.get("verified_at"), subject="verified_at")
        if issued is None or expires is None or checked_at is None or expires <= issued:
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_TIME_INVALID,
                "principal",
                "issued_at/expires_at/verified_at must be timezone-aware and ordered",
            )
        else:
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            principal_time_valid = issued <= checked_at < expires and issued <= current < expires
            if not principal_time_valid:
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_TIME_STALE,
                    "principal",
                    "the host verification time and current revalidation time must be inside the principal window",
                )
        for key in ("session_id_sha256", "verification_ref_sha256"):
            if not _valid_sha(principal.get(key)):
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_SHAPE_INVALID,
                    f"principal.{key}",
                    "principal public digest must be a lowercase SHA-256",
                )
                principal_valid = False
        if not _valid_sha(principal_identity_hash):
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_IDENTITY_HASH_INVALID,
                "principal_identity_hash",
                "principal_identity_hash must be a lowercase SHA-256",
            )
        elif _digest(dict(principal)) != principal_identity_hash:
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PRINCIPAL_IDENTITY_HASH_MISMATCH,
                "principal_identity_hash",
                "principal_identity_hash does not match the public principal snapshot",
            )
        if _text(payload.get("tenant_id")) != principal_tenant:
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.TENANT_MISMATCH,
                "tenant_id",
                "evidence tenant_id must match principal.tenant_id",
            )
        if expected_projects and not set(expected_projects).issubset(set(scope)):
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.PROJECT_SCOPE_INCOMPLETE,
                "principal.project_scope",
                "principal scope does not cover every required controlled-loop project",
            )
        else:
            project_scope_complete = bool(scope) and (not expected_projects or set(expected_projects).issubset(set(scope)))

    attestation = payload.get("attestation")
    attestation_valid = True
    attestation_verified = False
    attestation_ref = ""
    attestation_sha256 = ""
    if observed_status == "proven":
        if not isinstance(attestation, Mapping):
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_MISSING,
                "attestation",
                "proven runtime identity requires a host attestation object",
            )
            attestation_valid = False
        else:
            attestation_ref = _text(attestation.get("attestation_ref"))
            attestation_sha256 = attestation.get("attestation_sha256")
            if not isinstance(attestation_sha256, str):
                attestation_sha256 = ""
            if not _safe_ref(attestation_ref):
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_REF_INVALID,
                    "attestation.attestation_ref",
                    "attestation_ref must be an opaque safe identifier",
                )
                attestation_valid = False
            if not _valid_sha(attestation_sha256):
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_HASH_INVALID,
                    "attestation.attestation_sha256",
                    "attestation_sha256 must be a lowercase SHA-256",
                )
                attestation_valid = False
            else:
                attestation_without_digest = dict(attestation)
                attestation_without_digest.pop("attestation_sha256", None)
                if _digest(attestation_without_digest) != attestation_sha256:
                    _issue(
                        issues,
                        MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_HASH_MISMATCH,
                        "attestation.attestation_sha256",
                        "attestation_sha256 does not match the canonical attestation payload",
                    )
                    attestation_valid = False
            if attestation.get("verification_method") != _ALLOWED_VERIFICATION_METHOD:
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_METHOD_INVALID,
                    "attestation.verification_method",
                    "proven evidence requires the host_server_verified_envelope_v1 method",
                )
                attestation_valid = False
            if attestation.get("host_verified") is not True:
                _issue(
                    issues,
                    MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_REJECTED,
                    "attestation.host_verified",
                    "host_verified must be true only inside an attestation checked by the host verifier",
                )
                attestation_valid = False
            if attestation_valid:
                if attestation_verifier is None:
                    _issue(
                        issues,
                        MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_VERIFIER_MISSING,
                        "attestation",
                        "a caller-supplied host attestation verifier is required for proven status",
                    )
                else:
                    try:
                        attestation_verified = attestation_verifier(attestation) is True
                    except Exception as exc:  # pragma: no cover - defensive boundary
                        attestation_verified = False
                        _issue(
                            issues,
                            MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_REJECTED,
                            "attestation",
                            f"host attestation verifier raised {type(exc).__name__}",
                        )
                    if not attestation_verified:
                        _issue(
                            issues,
                            MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_REJECTED,
                            "attestation",
                            "host attestation verifier did not confirm the evidence",
                        )
    elif isinstance(attestation, Mapping):
        if attestation.get("host_verified") is True:
            _issue(
                issues,
                MonitoringRuntimeIdentityEvidenceIssueCode.STATUS_CONTRADICTION,
                "attestation.host_verified",
                "not_proven or blocked evidence cannot carry a positive host verification",
            )
            attestation_valid = False
    elif attestation is not None:
        _issue(
            issues,
            MonitoringRuntimeIdentityEvidenceIssueCode.ATTESTATION_SHAPE_INVALID,
            "attestation",
            "attestation must be an object when supplied",
        )
        attestation_valid = False

    runtime_verified = (
        observed_status == "proven"
        and principal_valid
        and attestation_valid
        and attestation_verified
        and principal_time_valid
        and project_scope_complete
        and not issues
    )
    return _build_report(
        issues=issues,
        observed_status=observed_status,
        evidence_ref=evidence_ref,
        evidence_sha256=evidence_sha256,
        principal_identity_hash=principal_identity_hash,
        principal_payload_valid=principal_valid,
        attestation_payload_valid=attestation_valid,
        attestation_verified=attestation_verified,
        principal_time_valid=principal_time_valid,
        project_scope_complete=project_scope_complete,
        runtime_identity_verified=runtime_verified,
        attestation_ref=attestation_ref,
        attestation_sha256=attestation_sha256,
    )


def _build_report(
    *,
    issues: list[MonitoringRuntimeIdentityEvidenceIssue],
    observed_status: str,
    evidence_ref: str,
    evidence_sha256: str,
    principal_identity_hash: str,
    principal_payload_valid: bool,
    attestation_payload_valid: bool,
    attestation_verified: bool,
    principal_time_valid: bool,
    project_scope_complete: bool,
    runtime_identity_verified: bool,
    attestation_ref: str = "",
    attestation_sha256: str = "",
) -> MonitoringRuntimeIdentityEvidenceReport:
    return MonitoringRuntimeIdentityEvidenceReport(
        status="fresh" if not issues else "blocked",
        evidence_fresh=not issues,
        runtime_identity_verified=runtime_identity_verified,
        principal_payload_valid=principal_payload_valid,
        attestation_payload_valid=attestation_payload_valid,
        attestation_verified=attestation_verified,
        principal_time_valid=principal_time_valid,
        project_scope_complete=project_scope_complete,
        observed_status=observed_status,
        evidence_ref=evidence_ref,
        evidence_sha256=evidence_sha256,
        principal_identity_hash=principal_identity_hash,
        attestation_ref=attestation_ref,
        attestation_sha256=attestation_sha256,
        issue_count=len(issues),
        issues=tuple(issues),
    )


__all__ = [
    "RUNTIME_IDENTITY_EVIDENCE_SCHEMA_VERSION",
    "RUNTIME_IDENTITY_EVIDENCE_REVALIDATION_SCHEMA_VERSION",
    "MonitoringRuntimeIdentityEvidenceError",
    "MonitoringRuntimeIdentityEvidenceIssue",
    "MonitoringRuntimeIdentityEvidenceIssueCode",
    "MonitoringRuntimeIdentityEvidenceReport",
    "revalidate_runtime_identity_evidence",
]
