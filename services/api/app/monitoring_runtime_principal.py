"""Provider-neutral, route-free runtime principal envelope for monitoring.

This module is the boundary between a future server-verified session adapter and
the existing offline monitoring authorization contract.  It deliberately does
not parse bearer tokens, cookies, headers or client ``actor`` values.  Callers
must supply an explicit ``server_verified=True`` envelope with a verification
reference, validity window and non-wildcard project scope.  The module is not
FastAPI middleware and does not authorize or persist a router write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from .monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringAuthorizationRequest,
    MonitoringPrincipal,
    MonitoringRole,
)


MONITORING_RUNTIME_PRINCIPAL_SCHEMA = "monitoring_runtime_principal_v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class MonitoringRuntimePrincipalError(ValueError):
    """Malformed server-verified principal envelope."""


class MonitoringRuntimePrincipalDenied(PermissionError):
    """A well-formed principal is not currently valid for use."""

    def __init__(self, reason_code: str):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MonitoringRuntimePrincipalError(f"{field_name} is required")
    return text


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _required(value, field_name)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise MonitoringRuntimePrincipalError(
                f"{field_name} must be an ISO-8601 timestamp"
            ) from exc
    if parsed.tzinfo is None:
        raise MonitoringRuntimePrincipalError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _sha256_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MonitoringRuntimePrincipalError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


@dataclass(frozen=True)
class MonitoringAuthenticatedPrincipal:
    """A server-verified, time-bounded monitoring principal.

    ``session_id`` is retained only in memory so the existing authorization
    contract can bind the session hash.  ``public_dict`` never exposes it.
    """

    principal_id: str
    tenant_id: str
    roles: tuple[MonitoringRole, ...]
    project_scope: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    authenticated: bool
    authn_method: str
    session_id: str
    directory_revision: str
    verification_ref_sha256: str
    authn_context: str = ""
    assurance: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_id", _required(self.principal_id, "principal_id"))
        object.__setattr__(self, "tenant_id", _required(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "authn_method", _required(self.authn_method, "authn_method"))
        object.__setattr__(self, "session_id", _required(self.session_id, "session_id"))
        object.__setattr__(
            self,
            "directory_revision",
            _required(self.directory_revision, "directory_revision"),
        )
        if not isinstance(self.authenticated, bool):
            raise MonitoringRuntimePrincipalError("authenticated must be a boolean")
        object.__setattr__(self, "issued_at", _parse_datetime(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _parse_datetime(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise MonitoringRuntimePrincipalError("expires_at must be later than issued_at")
        object.__setattr__(
            self,
            "verification_ref_sha256",
            _sha256_text(self.verification_ref_sha256, "verification_ref_sha256"),
        )
        object.__setattr__(self, "authn_context", str(self.authn_context or "").strip())
        object.__setattr__(self, "assurance", str(self.assurance or "").strip())
        try:
            normalized = MonitoringPrincipal(
                principal_id=self.principal_id,
                roles=self.roles,
                project_scope=self.project_scope,
                authenticated=self.authenticated,
                authn_method=self.authn_method,
                session_id=self.session_id,
                directory_revision=self.directory_revision,
            )
        except ValueError as exc:
            raise MonitoringRuntimePrincipalError(str(exc)) from exc
        object.__setattr__(self, "roles", normalized.roles)
        object.__setattr__(self, "project_scope", normalized.project_scope)

    @classmethod
    def from_server_verified_claims(
        cls,
        claims: Mapping[str, Any],
        *,
        now: datetime | None = None,
    ) -> "MonitoringAuthenticatedPrincipal":
        """Create a principal only from an explicitly verified envelope.

        The caller is responsible for authenticating the upstream assertion.
        A client-provided actor, cookie or bearer token is not an acceptable
        substitute for this envelope.
        """

        if not isinstance(claims, Mapping):
            raise MonitoringRuntimePrincipalError("server-verified claims must be an object")
        if claims.get("server_verified") is not True:
            raise MonitoringRuntimePrincipalError("server_verified must be true")
        try:
            principal = cls(
                principal_id=claims["principal_id"],
                tenant_id=claims["tenant_id"],
                roles=tuple(claims["roles"]),
                project_scope=tuple(claims["project_scope"]),
                issued_at=claims["issued_at"],
                expires_at=claims["expires_at"],
                authenticated=claims["authenticated"],
                authn_method=claims["authn_method"],
                session_id=claims["session_id"],
                directory_revision=claims["directory_revision"],
                verification_ref_sha256=claims["verification_ref_sha256"],
                authn_context=claims.get("authn_context", ""),
                assurance=claims.get("assurance", ""),
            )
        except KeyError as exc:
            raise MonitoringRuntimePrincipalError(
                f"missing server-verified claim: {exc.args[0]}"
            ) from exc
        principal.validate(now=now)
        return principal

    def validate(self, *, now: datetime | None = None) -> None:
        current = _parse_datetime(now or datetime.now(timezone.utc), "now")
        if not self.authenticated:
            raise MonitoringRuntimePrincipalDenied("principal_not_authenticated")
        if current < self.issued_at:
            raise MonitoringRuntimePrincipalDenied("principal_not_yet_valid")
        if current >= self.expires_at:
            raise MonitoringRuntimePrincipalDenied("principal_expired")

    def to_monitoring_principal(self, *, now: datetime | None = None) -> MonitoringPrincipal:
        self.validate(now=now)
        return MonitoringPrincipal(
            principal_id=self.principal_id,
            roles=self.roles,
            project_scope=self.project_scope,
            authenticated=True,
            authn_method=self.authn_method,
            session_id=self.session_id,
            directory_revision=self.directory_revision,
        )

    def require_tenant(self, tenant_id: Any, *, now: datetime | None = None) -> str:
        """Require the route's canonical tenant binding before authorization."""

        self.validate(now=now)
        requested = _required(tenant_id, "tenant_id")
        if requested != self.tenant_id:
            raise MonitoringRuntimePrincipalDenied("tenant_scope_denied")
        return self.tenant_id

    @property
    def server_actor(self) -> str:
        """The only actor value a future server route may derive from this principal."""

        return self.server_actor_at()

    def server_actor_at(self, *, now: datetime | None = None) -> str:
        """Derive the actor after validating against an explicit or current time."""

        self.validate(now=now)
        return self.principal_id

    @property
    def identity_hash(self) -> str:
        return _digest(self.public_dict())

    def public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": MONITORING_RUNTIME_PRINCIPAL_SCHEMA,
            "principal_id": self.principal_id,
            "tenant_id": self.tenant_id,
            "roles": [role.value for role in self.roles],
            "project_scope": list(self.project_scope),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "authenticated": self.authenticated,
            "authn_method": self.authn_method,
            "session_id_sha256": _digest(self.session_id),
            "directory_revision": self.directory_revision,
            "verification_ref_sha256": self.verification_ref_sha256,
            "authn_context": self.authn_context,
            "assurance": self.assurance,
        }


def require_server_derived_actor(
    principal: MonitoringAuthenticatedPrincipal,
    client_actor: Any = None,
    *,
    now: datetime | None = None,
) -> str:
    """Return the server-derived actor and reject a non-empty client actor.

    Compatibility request models may still contain an ``actor`` field while
    routes migrate.  It must not be accepted, even when it happens to equal the
    principal id; only the verified principal is authoritative.
    """

    principal.validate(now=now)
    if str(client_actor or "").strip():
        raise MonitoringRuntimePrincipalDenied("client_actor_not_authoritative")
    return principal.server_actor_at(now=now)


def build_monitoring_authorization_request(
    principal: MonitoringAuthenticatedPrincipal,
    *,
    request_id: str,
    project_id: str,
    target_scope: str,
    action: MonitoringAction,
    client_actor: Any = None,
    high_risk: bool = False,
    reauthenticated: bool = False,
    signature_evidence_sha256: str = "",
    tenant_id: Any = None,
    now: datetime | None = None,
) -> MonitoringAuthorizationRequest:
    """Build the existing authorization request from server identity only.

    This helper intentionally stops before ``authorize_monitoring_action`` so a
    future route can still record and inspect the decision before any mutation.
    """

    if tenant_id is not None:
        principal.require_tenant(tenant_id, now=now)
    actor = require_server_derived_actor(principal, client_actor, now=now)
    return MonitoringAuthorizationRequest(
        request_id=request_id,
        principal_id=actor,
        project_id=project_id,
        action=action,
        target_scope=target_scope,
        high_risk=high_risk,
        reauthenticated=reauthenticated,
        signature_evidence_sha256=signature_evidence_sha256,
    )
