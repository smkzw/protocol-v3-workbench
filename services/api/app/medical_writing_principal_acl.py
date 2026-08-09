"""Provider-neutral, route-free principal and ACL decisions for medical writing.

The module deliberately stops at an authorization boundary.  An upstream
identity/session adapter must construct ``MedicalWritingAuthenticatedPrincipal``
from a server-verified assertion; this module never parses bearer tokens,
cookies, client ``actor`` values, or identity-provider claims.  A caller must
also supply an explicit, versioned grant for the exact tenant/project/document
scope and action.  There are no default roles, wildcard grants, or inferred
project permissions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple


MEDICAL_WRITING_PRINCIPAL_ACL_SCHEMA = "medical_writing_principal_acl_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIONS = frozenset(
    {
        "read",
        "create",
        "update",
        "review",
        "approve",
        "export",
        "download",
        "purge",
        "rollback",
        "signature",
    }
)


class MedicalWritingPrincipalAclError(ValueError):
    """Base error for malformed principal, policy, or request data."""


class MedicalWritingPrincipalAclDenied(PermissionError):
    """Raised by ``require_authorized`` when a decision is not allowed."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


class MedicalWritingPrincipalAclIntegrityError(MedicalWritingPrincipalAclError):
    """Raised when a principal, request, grant, or policy is malformed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalWritingPrincipalAclIntegrityError(f"{field_name} is required")
    return text


def _optional_text(value: Any, *, field_name: str) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise MedicalWritingPrincipalAclIntegrityError(
            f"{field_name} must be omitted or non-empty"
        )
    return text


def _parse_datetime(value: Any, *, field_name: str) -> datetime:
    text = _require_text(value, field_name=field_name)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MedicalWritingPrincipalAclIntegrityError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise MedicalWritingPrincipalAclIntegrityError(
            f"{field_name} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _iso_datetime(value: Any, *, field_name: str) -> str:
    return _parse_datetime(value, field_name=field_name).isoformat()


def _now(value: Any = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise MedicalWritingPrincipalAclIntegrityError("now must include a timezone")
        return value.astimezone(timezone.utc)
    return _parse_datetime(value, field_name="now")


def _sha256_text(value: Any, *, field_name: str) -> str:
    text = _require_text(value, field_name=field_name).lower()
    if not _SHA256_RE.fullmatch(text):
        raise MedicalWritingPrincipalAclIntegrityError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return text


def _ordered_unique(values: Iterable[Any], *, field_name: str) -> Tuple[str, ...]:
    result = tuple(_require_text(value, field_name=field_name) for value in values)
    if len(result) != len(set(result)):
        raise MedicalWritingPrincipalAclIntegrityError(
            f"{field_name} must contain unique values"
        )
    return result


@dataclass(frozen=True)
class MedicalWritingAuthenticatedPrincipal:
    """An assertion already authenticated by an upstream server adapter."""

    subject_id: str
    tenant_id: str
    assurance: str
    issued_at: str
    expires_at: str
    authenticated: bool
    role: str
    authn_context: str = ""
    session_ref_sha256: str = ""

    def as_dict(self) -> Dict[str, Any]:
        subject = _require_text(self.subject_id, field_name="principal.subject_id")
        tenant = _require_text(self.tenant_id, field_name="principal.tenant_id")
        assurance = _require_text(self.assurance, field_name="principal.assurance")
        role = _require_text(self.role, field_name="principal.role")
        issued = _iso_datetime(self.issued_at, field_name="principal.issued_at")
        expires = _iso_datetime(self.expires_at, field_name="principal.expires_at")
        if _parse_datetime(expires, field_name="principal.expires_at") <= _parse_datetime(
            issued, field_name="principal.issued_at"
        ):
            raise MedicalWritingPrincipalAclIntegrityError(
                "principal.expires_at must be later than principal.issued_at"
            )
        context = str(self.authn_context or "").strip()
        session_hash = str(self.session_ref_sha256 or "").strip().lower()
        if session_hash and not _SHA256_RE.fullmatch(session_hash):
            raise MedicalWritingPrincipalAclIntegrityError(
                "principal.session_ref_sha256 must be a lowercase SHA-256 digest"
            )
        return {
            "schema_version": MEDICAL_WRITING_PRINCIPAL_ACL_SCHEMA,
            "subject_id": subject,
            "tenant_id": tenant,
            "assurance": assurance,
            "role": role,
            "issued_at": issued,
            "expires_at": expires,
            "authenticated": bool(self.authenticated),
            "authn_context": context,
            "session_ref_sha256": session_hash,
        }

    def validate(self, *, now: Any = None) -> None:
        payload = self.as_dict()
        if not payload["authenticated"]:
            raise MedicalWritingPrincipalAclDenied("principal_not_authenticated")
        current = _now(now)
        expires = _parse_datetime(payload["expires_at"], field_name="principal.expires_at")
        if current >= expires:
            raise MedicalWritingPrincipalAclDenied("principal_expired")
        issued = _parse_datetime(payload["issued_at"], field_name="principal.issued_at")
        if current < issued:
            raise MedicalWritingPrincipalAclDenied("principal_not_yet_valid")

    @property
    def identity_hash(self) -> str:
        return _sha256(self.as_dict())


@dataclass(frozen=True)
class MedicalWritingAccessRequest:
    """The exact resource/action requested by a route or service."""

    request_id: str
    tenant_id: str
    project_id: str
    action: str
    document_id: Optional[str] = None
    client_actor: Optional[str] = None
    trace_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        request_id = _require_text(self.request_id, field_name="request.request_id")
        tenant = _require_text(self.tenant_id, field_name="request.tenant_id")
        project = _require_text(self.project_id, field_name="request.project_id")
        action = _require_text(self.action, field_name="request.action")
        if action not in _ACTIONS:
            raise MedicalWritingPrincipalAclIntegrityError(
                f"unsupported request.action: {action}"
            )
        document = _optional_text(self.document_id, field_name="request.document_id")
        actor = _optional_text(self.client_actor, field_name="request.client_actor")
        trace = _optional_text(self.trace_id, field_name="request.trace_id")
        return {
            "schema_version": MEDICAL_WRITING_PRINCIPAL_ACL_SCHEMA,
            "request_id": request_id,
            "tenant_id": tenant,
            "project_id": project,
            "document_id": document,
            "action": action,
            # Never persist the untrusted actor value in a decision/audit payload.
            "client_actor_present": actor is not None,
            "client_actor_sha256": _sha256(actor) if actor is not None else "",
            "trace_id": trace or "",
        }

    @property
    def request_hash(self) -> str:
        return _sha256(self.as_dict())


@dataclass(frozen=True)
class MedicalWritingAclGrant:
    """An exact server-side grant; no wildcard or role inference is allowed."""

    grant_id: str
    tenant_id: str
    project_id: str
    subject_id: str
    actions: Tuple[str, ...]
    effective_from: str
    document_id: Optional[str] = None
    expires_at: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        grant_id = _require_text(self.grant_id, field_name="grant.grant_id")
        tenant = _require_text(self.tenant_id, field_name="grant.tenant_id")
        project = _require_text(self.project_id, field_name="grant.project_id")
        subject = _require_text(self.subject_id, field_name="grant.subject_id")
        actions = _ordered_unique(self.actions, field_name="grant.actions")
        if not actions or any(action not in _ACTIONS for action in actions):
            raise MedicalWritingPrincipalAclIntegrityError(
                "grant.actions must contain only supported actions"
            )
        effective = _iso_datetime(self.effective_from, field_name="grant.effective_from")
        expires = (
            _iso_datetime(self.expires_at, field_name="grant.expires_at")
            if self.expires_at is not None
            else None
        )
        if expires is not None and _parse_datetime(expires, field_name="grant.expires_at") <= _parse_datetime(
            effective, field_name="grant.effective_from"
        ):
            raise MedicalWritingPrincipalAclIntegrityError(
                "grant.expires_at must be later than grant.effective_from"
            )
        return {
            "schema_version": MEDICAL_WRITING_PRINCIPAL_ACL_SCHEMA,
            "grant_id": grant_id,
            "tenant_id": tenant,
            "project_id": project,
            "document_id": _optional_text(self.document_id, field_name="grant.document_id"),
            "subject_id": subject,
            "actions": list(actions),
            "effective_from": effective,
            "expires_at": expires,
        }


@dataclass(frozen=True)
class MedicalWritingAclPolicy:
    """Versioned policy supplied by a policy owner; no policy is inferred."""

    policy_id: str
    policy_revision: int
    effective_from: str
    grants: Tuple[MedicalWritingAclGrant, ...]
    expires_at: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        policy_id = _require_text(self.policy_id, field_name="policy.policy_id")
        try:
            revision = int(self.policy_revision)
        except (TypeError, ValueError) as exc:
            raise MedicalWritingPrincipalAclIntegrityError(
                "policy.policy_revision must be an integer"
            ) from exc
        if revision < 1:
            raise MedicalWritingPrincipalAclIntegrityError(
                "policy.policy_revision must be >= 1"
            )
        effective = _iso_datetime(self.effective_from, field_name="policy.effective_from")
        expires = (
            _iso_datetime(self.expires_at, field_name="policy.expires_at")
            if self.expires_at is not None
            else None
        )
        if expires is not None and _parse_datetime(expires, field_name="policy.expires_at") <= _parse_datetime(
            effective, field_name="policy.effective_from"
        ):
            raise MedicalWritingPrincipalAclIntegrityError(
                "policy.expires_at must be later than policy.effective_from"
            )
        grants = tuple(grant.as_dict() for grant in self.grants)
        if not grants:
            raise MedicalWritingPrincipalAclIntegrityError(
                "policy.grants must contain at least one explicit grant"
            )
        grant_ids = [grant["grant_id"] for grant in grants]
        if len(grant_ids) != len(set(grant_ids)):
            raise MedicalWritingPrincipalAclIntegrityError(
                "policy.grants must contain unique grant IDs"
            )
        return {
            "schema_version": MEDICAL_WRITING_PRINCIPAL_ACL_SCHEMA,
            "policy_id": policy_id,
            "policy_revision": revision,
            "effective_from": effective,
            "expires_at": expires,
            "grants": list(grants),
        }

    @property
    def policy_hash(self) -> str:
        return _sha256(self.as_dict())


@dataclass(frozen=True)
class MedicalWritingAuthorizationDecision:
    allowed: bool
    reason_code: str
    action: str
    request_hash: str
    principal_hash: str
    policy_hash: str
    decision_hash: str
    audit_payload: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": MEDICAL_WRITING_PRINCIPAL_ACL_SCHEMA,
            "allowed": bool(self.allowed),
            "reason_code": self.reason_code,
            "action": self.action,
            "request_hash": self.request_hash,
            "principal_hash": self.principal_hash,
            "policy_hash": self.policy_hash,
            "decision_hash": self.decision_hash,
            "audit_payload": dict(self.audit_payload),
        }


def authorize_medical_writing_request(
    *,
    principal: MedicalWritingAuthenticatedPrincipal,
    request: MedicalWritingAccessRequest,
    policy: MedicalWritingAclPolicy,
    now: Any = None,
) -> MedicalWritingAuthorizationDecision:
    """Return a deterministic allow/deny decision without mutating state."""

    request_payload = request.as_dict()
    policy_payload = policy.as_dict()
    request_hash = request.request_hash
    policy_hash = policy.policy_hash
    current = _now(now)

    def decision(reason_code: str, allowed: bool) -> MedicalWritingAuthorizationDecision:
        base = {
            "schema_version": MEDICAL_WRITING_PRINCIPAL_ACL_SCHEMA,
            "allowed": bool(allowed),
            "reason_code": reason_code,
            "action": request_payload["action"],
            "request_hash": request_hash,
            "principal_hash": principal.identity_hash,
            "policy_hash": policy_hash,
        }
        audit = {
            **base,
            "request_id": request_payload["request_id"],
            "tenant_id": request_payload["tenant_id"],
            "project_id": request_payload["project_id"],
            "document_id": request_payload["document_id"],
            "principal_subject": principal.as_dict()["subject_id"],
            "principal_tenant": principal.as_dict()["tenant_id"],
            "trace_id": request_payload["trace_id"],
            "client_actor_present": request_payload["client_actor_present"],
        }
        decision_hash = _sha256({**base, "audit_payload": audit})
        return MedicalWritingAuthorizationDecision(
            allowed=allowed,
            reason_code=reason_code,
            action=request_payload["action"],
            request_hash=request_hash,
            principal_hash=principal.identity_hash,
            policy_hash=policy_hash,
            decision_hash=decision_hash,
            audit_payload=audit,
        )

    try:
        principal.validate(now=current)
    except MedicalWritingPrincipalAclDenied as exc:
        return decision(exc.reason_code, False)

    principal_payload = principal.as_dict()
    if principal_payload["tenant_id"] != request_payload["tenant_id"]:
        return decision("tenant_mismatch", False)
    client_actor = _optional_text(
        request.client_actor, field_name="request.client_actor"
    )
    if client_actor and client_actor != principal_payload["subject_id"]:
        return decision("client_actor_spoofed", False)

    policy_effective = _parse_datetime(
        policy_payload["effective_from"], field_name="policy.effective_from"
    )
    if current < policy_effective:
        return decision("policy_not_yet_effective", False)
    if policy_payload["expires_at"] is not None and current >= _parse_datetime(
        policy_payload["expires_at"], field_name="policy.expires_at"
    ):
        return decision("policy_expired", False)

    for grant in policy_payload["grants"]:
        if grant["tenant_id"] != request_payload["tenant_id"]:
            continue
        if grant["project_id"] != request_payload["project_id"]:
            continue
        # Scope is exact. A project grant matches only a project-scoped request;
        # it is never implicitly inherited by a document request.
        if grant["document_id"] != request_payload["document_id"]:
            continue
        if grant["subject_id"] != principal_payload["subject_id"]:
            continue
        if request_payload["action"] not in grant["actions"]:
            continue
        effective = _parse_datetime(grant["effective_from"], field_name="grant.effective_from")
        if current < effective:
            continue
        if grant["expires_at"] is not None and current >= _parse_datetime(
            grant["expires_at"], field_name="grant.expires_at"
        ):
            continue
        return decision("explicit_grant", True)
    return decision("no_matching_grant", False)


def require_medical_writing_authorization(
    *,
    principal: MedicalWritingAuthenticatedPrincipal,
    request: MedicalWritingAccessRequest,
    policy: MedicalWritingAclPolicy,
    now: Any = None,
) -> MedicalWritingAuthorizationDecision:
    result = authorize_medical_writing_request(
        principal=principal,
        request=request,
        policy=policy,
        now=now,
    )
    if not result.allowed:
        raise MedicalWritingPrincipalAclDenied(result.reason_code)
    return result
