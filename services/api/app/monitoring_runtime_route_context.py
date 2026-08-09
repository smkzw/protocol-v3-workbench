"""Provider-neutral route seam for server-derived monitoring identity.

This module binds a verified monitoring principal to the canonical tenant,
project and action requested by a future API route.  It deliberately stops
before ``authorize_monitoring_action`` and before any repository/audit write:
the route still has to evaluate the decision, source revision, CAS and mutation
contract.  No token, cookie, header or client actor is parsed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringAuthorizationRequest,
)
from .monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
    MonitoringRuntimePrincipalDenied,
    build_monitoring_authorization_request,
)


MONITORING_RUNTIME_ROUTE_CONTEXT_SCHEMA = "monitoring_runtime_route_context_v1"


class MonitoringRuntimeRouteContextError(ValueError):
    """A route binding is malformed or does not match the principal."""


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MonitoringRuntimeRouteContextError(f"{field_name} is required")
    return text


def _route_now(value: Any = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise MonitoringRuntimeRouteContextError("validated_at must include a timezone")
        return value.astimezone(timezone.utc)
    text = _required(value, "validated_at")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MonitoringRuntimeRouteContextError(
            "validated_at must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise MonitoringRuntimeRouteContextError("validated_at must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class MonitoringRuntimeRouteContext:
    """The immutable identity/request seam a future route can consume."""

    principal: MonitoringAuthenticatedPrincipal
    request: MonitoringAuthorizationRequest
    tenant_id: str
    project_id: str
    validated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, MonitoringAuthenticatedPrincipal):
            raise MonitoringRuntimeRouteContextError("principal must be server-verified")
        tenant_id = _required(self.tenant_id, "tenant_id")
        project_id = _required(self.project_id, "project_id")
        if not isinstance(self.request, MonitoringAuthorizationRequest):
            raise MonitoringRuntimeRouteContextError("request must be a monitoring authorization request")
        validated_at = _route_now(self.validated_at)
        try:
            self.principal.validate(now=validated_at)
        except MonitoringRuntimePrincipalDenied as exc:
            raise MonitoringRuntimeRouteContextError(
                f"principal is not valid at route validation time: {exc}"
            ) from exc
        if self.request.principal_id != self.principal.principal_id:
            raise MonitoringRuntimeRouteContextError("request principal does not match the server principal")
        if self.request.project_id != project_id:
            raise MonitoringRuntimeRouteContextError("request project does not match the canonical route project")
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "validated_at", validated_at)

    @property
    def principal_id(self) -> str:
        return self.principal.principal_id

    @property
    def action(self) -> MonitoringAction:
        return self.request.action

    def public_dict(self) -> dict[str, Any]:
        """Return a safe handoff; raw session material is never included."""

        return {
            "schema_version": MONITORING_RUNTIME_ROUTE_CONTEXT_SCHEMA,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "principal_id": self.principal_id,
            "principal_identity_hash": self.principal.identity_hash,
            "validated_at": self.validated_at.isoformat(),
            "principal": self.principal.public_dict(),
            "request": self.request.public_dict(),
        }


def build_monitoring_runtime_route_context(
    principal: MonitoringAuthenticatedPrincipal,
    *,
    request_id: str,
    route_project_id: str,
    tenant_id: str,
    target_scope: str,
    action: MonitoringAction,
    client_actor: Any = None,
    high_risk: bool = False,
    reauthenticated: bool = False,
    signature_evidence_sha256: str = "",
    now: Any = None,
) -> MonitoringRuntimeRouteContext:
    """Bind route identity without authorizing or mutating the target."""

    if not isinstance(principal, MonitoringAuthenticatedPrincipal):
        raise MonitoringRuntimeRouteContextError("principal must be server-verified")
    project_id = _required(route_project_id, "route_project_id")
    tenant = _required(tenant_id, "tenant_id")
    validated_at = _route_now(now)
    principal.validate(now=validated_at)
    principal.require_tenant(tenant, now=validated_at)
    if project_id not in principal.project_scope:
        raise MonitoringRuntimePrincipalDenied("project_scope_denied")
    request = build_monitoring_authorization_request(
        principal,
        request_id=_required(request_id, "request_id"),
        project_id=project_id,
        tenant_id=tenant,
        target_scope=target_scope,
        action=action,
        client_actor=client_actor,
        high_risk=high_risk,
        reauthenticated=reauthenticated,
        signature_evidence_sha256=signature_evidence_sha256,
        now=validated_at,
    )
    return MonitoringRuntimeRouteContext(
        principal=principal,
        request=request,
        tenant_id=tenant,
        project_id=project_id,
        validated_at=validated_at,
    )
