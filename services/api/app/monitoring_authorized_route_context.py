"""Pure authorization-and-audit handoff for a monitoring route.

``monitoring_runtime_route_context`` binds a server-verified principal to a
canonical route request.  This module is the next, still provider-neutral,
boundary: it evaluates that request with the existing monitoring ACL and
creates one hash-bound audit event in memory.  It deliberately stops before
SQLite, repository/CAS, source admission, e-signature persistence or any
service mutation.  A route may inspect the returned decision and event, but
cannot mistake this handoff for execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from .monitoring_audit_contract import (
    MonitoringAuditEvent,
    MonitoringAuditTargetType,
)
from .monitoring_identity_authorization import (
    MonitoringAuthorizationDecision,
    MonitoringPrincipal,
    authorization_decision_payload,
    authorize_monitoring_action,
)
from .monitoring_runtime_route_context import MonitoringRuntimeRouteContext


MONITORING_AUTHORIZED_ROUTE_CONTEXT_SCHEMA = (
    "monitoring_authorized_route_context_v1"
)


class MonitoringAuthorizedRouteContextError(ValueError):
    """A route authorization/audit handoff is malformed or inconsistent."""


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MonitoringAuthorizedRouteContextError(f"{field_name} is required")
    return text


@dataclass(frozen=True)
class MonitoringAuthorizedRouteContext:
    """Immutable, non-persisted authorization and audit handoff."""

    route_context: MonitoringRuntimeRouteContext
    principal: MonitoringPrincipal
    decision: MonitoringAuthorizationDecision
    audit_event: MonitoringAuditEvent

    def __post_init__(self) -> None:
        if not isinstance(self.route_context, MonitoringRuntimeRouteContext):
            raise MonitoringAuthorizedRouteContextError(
                "route_context must be server-bound"
            )
        if not isinstance(self.principal, MonitoringPrincipal):
            raise MonitoringAuthorizedRouteContextError(
                "principal must be an authorization snapshot"
            )
        if not isinstance(self.decision, MonitoringAuthorizationDecision):
            raise MonitoringAuthorizedRouteContextError("decision is required")
        if not isinstance(self.audit_event, MonitoringAuditEvent):
            raise MonitoringAuthorizedRouteContextError("audit_event is required")

        request = self.route_context.request
        if self.principal.principal_id != self.route_context.principal_id:
            raise MonitoringAuthorizedRouteContextError(
                "authorization principal does not match route principal"
            )
        if self.decision.request_id != request.request_id:
            raise MonitoringAuthorizedRouteContextError(
                "authorization decision does not match route request"
            )
        if self.decision.principal_id != self.principal.principal_id:
            raise MonitoringAuthorizedRouteContextError(
                "authorization decision principal does not match snapshot"
            )
        if self.decision.principal_sha256 != self.principal.principal_sha256:
            raise MonitoringAuthorizedRouteContextError(
                "authorization decision hash does not match snapshot"
            )
        if self.decision.project_id != self.route_context.project_id:
            raise MonitoringAuthorizedRouteContextError(
                "authorization decision project does not match route project"
            )
        if self.decision.action is not request.action:
            raise MonitoringAuthorizedRouteContextError(
                "authorization decision action does not match route request"
            )
        if self.decision.target_scope != request.target_scope:
            raise MonitoringAuthorizedRouteContextError(
                "authorization decision scope does not match route request"
            )
        if self.audit_event.project_id != self.route_context.project_id:
            raise MonitoringAuthorizedRouteContextError(
                "audit event project does not match route project"
            )
        if self.audit_event.principal_id != self.principal.principal_id:
            raise MonitoringAuthorizedRouteContextError(
                "audit event principal does not match snapshot"
            )
        if self.audit_event.authorization_decision_sha256 != self.decision.decision_sha256:
            raise MonitoringAuthorizedRouteContextError(
                "audit event is not bound to the authorization decision"
            )
        if self.audit_event.decision_allowed != self.decision.allowed:
            raise MonitoringAuthorizedRouteContextError(
                "audit event decision status does not match authorization"
            )
        if self.audit_event.write_permitted != self.decision.write_permitted:
            raise MonitoringAuthorizedRouteContextError(
                "audit event write status does not match authorization"
            )
        if self.audit_event.mutation_applied:
            raise MonitoringAuthorizedRouteContextError(
                "route handoff cannot claim a mutation"
            )
        if self.audit_event.aggregate_version_after != self.audit_event.aggregate_version_before:
            raise MonitoringAuthorizedRouteContextError(
                "route handoff cannot advance aggregate version"
            )

    @property
    def mutation_applied(self) -> bool:
        return False

    @property
    def execution_write_permitted(self) -> bool:
        """Always false: ACL ``write_permitted`` is not execution authority."""

        return False

    def public_dict(self) -> dict[str, Any]:
        """Return a safe handoff without raw session or token material."""

        return {
            "schema_version": MONITORING_AUTHORIZED_ROUTE_CONTEXT_SCHEMA,
            "route": self.route_context.public_dict(),
            "principal": self.principal.public_dict(),
            "authorization": authorization_decision_payload(self.decision),
            "audit_event": self.audit_event.public_dict(),
            "execution_write_permitted": False,
            "mutation_applied": False,
            "persisted": False,
        }


def build_monitoring_authorized_route_context(
    route_context: MonitoringRuntimeRouteContext,
    *,
    audit_id: str,
    target_type: MonitoringAuditTargetType,
    target_id: str,
    source_revision: str,
    occurred_at: datetime | None = None,
    prev_event_hash: str = "",
    payload: Mapping[str, Any] | None = None,
    aggregate_version_before: int = 0,
) -> MonitoringAuthorizedRouteContext:
    """Evaluate and audit one route request without persisting or mutating.

    The runtime principal is converted to the existing authorization snapshot
    only in memory.  The audit event is deliberately non-mutating, even when
    the ACL says the requested action would be a write if later runtime gates
    (source revision, CAS, e-signature and repository) also pass.
    """

    if not isinstance(route_context, MonitoringRuntimeRouteContext):
        raise MonitoringAuthorizedRouteContextError(
            "route_context must be server-bound"
        )
    try:
        principal = route_context.principal.to_monitoring_principal(
            now=route_context.validated_at
        )
    except Exception as exc:
        raise MonitoringAuthorizedRouteContextError(
            "route principal cannot be converted to an authorization snapshot"
        ) from exc
    decision = authorize_monitoring_action(principal, route_context.request)
    audit_event = MonitoringAuditEvent.from_authorization_decision(
        audit_id=_required(audit_id, "audit_id"),
        principal=principal,
        decision=decision,
        target_type=target_type,
        target_id=_required(target_id, "target_id"),
        source_revision=_required(source_revision, "source_revision"),
        mutation_applied=False,
        aggregate_version_before=aggregate_version_before,
        aggregate_version_after=aggregate_version_before,
        occurred_at=occurred_at or route_context.validated_at,
        prev_event_hash=prev_event_hash,
        payload=payload or {},
    )
    return MonitoringAuthorizedRouteContext(
        route_context=route_context,
        principal=principal,
        decision=decision,
        audit_event=audit_event,
    )
