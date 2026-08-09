"""Pure, surface-specific read-action contract for medical monitoring.

The legacy dashboard, workbench-inbox and AI-run GET routes currently fail
closed because they do not have an exact action/runtime policy.  This module
defines the missing handoff without opening those routes: a future route must
bind one surface-specific action to the already-authorized route context, an
immutable source/response snapshot, an idempotency key and a non-mutating
aggregate version.  It neither authenticates, persists, calls a service nor
grants execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any

from .monitoring_authorized_route_context import (
    MonitoringAuthorizedRouteContext,
)
from .monitoring_identity_authorization import MonitoringAction


MONITORING_READ_ACTION_CONTRACT_SCHEMA = "monitoring_read_action_contract_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class MonitoringReadSurface(str, Enum):
    DASHBOARD = "dashboard"
    WORKBENCH_INBOX = "workbench_inbox"
    AI_RUN_CATALOG = "ai_run_catalog"
    AI_RUN_DETAIL = "ai_run_detail"
    AI_RUN_ARTIFACTS = "ai_run_artifacts"


_SURFACE_ACTION: dict[MonitoringReadSurface, MonitoringAction] = {
    MonitoringReadSurface.DASHBOARD: MonitoringAction.READ_DASHBOARD,
    MonitoringReadSurface.WORKBENCH_INBOX: MonitoringAction.READ_WORKBENCH_INBOX,
    MonitoringReadSurface.AI_RUN_CATALOG: MonitoringAction.READ_AI_RUN,
    MonitoringReadSurface.AI_RUN_DETAIL: MonitoringAction.READ_AI_RUN,
    MonitoringReadSurface.AI_RUN_ARTIFACTS: MonitoringAction.READ_AI_ARTIFACT,
}
_PROJECT_TARGET_SURFACES = frozenset(
    {
        MonitoringReadSurface.DASHBOARD,
        MonitoringReadSurface.WORKBENCH_INBOX,
        MonitoringReadSurface.AI_RUN_CATALOG,
    }
)


class MonitoringReadActionContractError(ValueError):
    """A read handoff is malformed, mismatched or not safe to activate."""


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MonitoringReadActionContractError(f"{field_name} is required")
    return text


def _sha256_digest(value: Any, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise MonitoringReadActionContractError(
            f"{field_name} must be a lowercase SHA-256"
        )
    return text


def _idempotency_key(value: Any) -> str:
    text = str(value or "").strip()
    if not _IDEMPOTENCY_RE.fullmatch(text):
        raise MonitoringReadActionContractError(
            "idempotency_key must be 1-200 safe ASCII characters"
        )
    return text


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MonitoringReadActionContract:
    """Immutable, non-persisted read handoff for a future route."""

    authorized_context: MonitoringAuthorizedRouteContext
    surface: MonitoringReadSurface
    source_snapshot_sha256: str
    response_snapshot_sha256: str
    idempotency_key: str
    cas_version: int
    contract_sha256: str = ""

    def __post_init__(self) -> None:
        if not isinstance(
            self.authorized_context, MonitoringAuthorizedRouteContext
        ):
            raise MonitoringReadActionContractError(
                "authorized_context must be a server-bound authorization handoff"
            )
        if not isinstance(self.surface, MonitoringReadSurface):
            try:
                object.__setattr__(
                    self, "surface", MonitoringReadSurface(str(self.surface))
                )
            except (TypeError, ValueError) as exc:
                raise MonitoringReadActionContractError(
                    f"unsupported read surface: {self.surface}"
                ) from exc

        source_digest = _sha256_digest(
            self.source_snapshot_sha256, "source_snapshot_sha256"
        )
        response_digest = _sha256_digest(
            self.response_snapshot_sha256, "response_snapshot_sha256"
        )
        object.__setattr__(self, "source_snapshot_sha256", source_digest)
        object.__setattr__(self, "response_snapshot_sha256", response_digest)
        key = _idempotency_key(self.idempotency_key)
        object.__setattr__(self, "idempotency_key", key)

        context = self.authorized_context
        route = context.route_context
        decision = context.decision
        audit = context.audit_event
        expected_action = _SURFACE_ACTION[self.surface]

        if decision.action is not expected_action:
            raise MonitoringReadActionContractError(
                f"surface {self.surface.value} requires action {expected_action.value}"
            )
        if not decision.allowed:
            raise MonitoringReadActionContractError(
                "read action is denied and cannot produce a route handoff"
            )
        if decision.write_permitted or context.execution_write_permitted:
            raise MonitoringReadActionContractError(
                "read action cannot carry write execution authority"
            )
        if audit.decision_allowed is not True or audit.write_permitted:
            raise MonitoringReadActionContractError(
                "audit event is not an allowed read decision"
            )
        if audit.mutation_applied:
            raise MonitoringReadActionContractError(
                "read action cannot claim a mutation"
            )
        if audit.aggregate_version_before != audit.aggregate_version_after:
            raise MonitoringReadActionContractError(
                "read action requires an unchanged aggregate/CAS version"
            )
        if not isinstance(self.cas_version, int) or isinstance(self.cas_version, bool):
            raise MonitoringReadActionContractError("cas_version must be an integer")
        if self.cas_version < 0:
            raise MonitoringReadActionContractError("cas_version must be non-negative")
        if self.cas_version != audit.aggregate_version_before:
            raise MonitoringReadActionContractError(
                "cas_version does not match the audited aggregate version"
            )
        if audit.source_revision != source_digest:
            raise MonitoringReadActionContractError(
                "source snapshot digest does not match the audited source revision"
            )
        if route.tenant_id != _required(route.tenant_id, "tenant_id"):
            raise MonitoringReadActionContractError("tenant scope is invalid")
        if route.project_id != decision.project_id or audit.project_id != route.project_id:
            raise MonitoringReadActionContractError(
                "project scope is not consistently bound"
            )
        if audit.principal_id != context.principal.principal_id:
            raise MonitoringReadActionContractError(
                "audit principal is not bound to the server principal"
            )
        if self.surface in _PROJECT_TARGET_SURFACES:
            if audit.target_type != "project" or audit.target_id != route.project_id:
                raise MonitoringReadActionContractError(
                    "project read surface requires a project audit target"
                )
        elif audit.target_type != "runtime" or not audit.target_id:
            raise MonitoringReadActionContractError(
                "AI run detail/artifacts require a runtime audit target"
            )

        payload = self._hash_payload()
        expected_contract_hash = _digest(payload)
        if self.contract_sha256 and self.contract_sha256 != expected_contract_hash:
            raise MonitoringReadActionContractError(
                "contract_sha256 does not match immutable read handoff"
            )
        object.__setattr__(self, "contract_sha256", expected_contract_hash)

    @property
    def action(self) -> MonitoringAction:
        return _SURFACE_ACTION[self.surface]

    @property
    def project_id(self) -> str:
        return self.authorized_context.route_context.project_id

    @property
    def tenant_id(self) -> str:
        return self.authorized_context.route_context.tenant_id

    @property
    def principal_id(self) -> str:
        return self.authorized_context.principal.principal_id

    @property
    def audit_id(self) -> str:
        return self.authorized_context.audit_event.audit_id

    @property
    def idempotency_key_sha256(self) -> str:
        return sha256(self.idempotency_key.encode("utf-8")).hexdigest()

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": MONITORING_READ_ACTION_CONTRACT_SCHEMA,
            "surface": self.surface.value,
            "action": self.action.value,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "principal_id": self.principal_id,
            "principal_identity_hash": self.authorized_context.principal.principal_sha256,
            "request_id": self.authorized_context.route_context.request.request_id,
            "audit_id": self.audit_id,
            "authorization_decision_sha256": self.authorized_context.decision.decision_sha256,
            "source_snapshot_sha256": self.source_snapshot_sha256,
            "response_snapshot_sha256": self.response_snapshot_sha256,
            "idempotency_key_sha256": self.idempotency_key_sha256,
            "cas_version": self.cas_version,
            "read_only": True,
            "persisted": False,
            "mutation_applied": False,
        }

    def public_dict(self) -> dict[str, Any]:
        """Return a safe handoff; raw session and idempotency material stay local."""

        return {
            **self._hash_payload(),
            "route_context": self.authorized_context.route_context.public_dict(),
            "audit_event_hash": self.authorized_context.audit_event.event_hash,
            "contract_sha256": self.contract_sha256,
        }


def build_monitoring_read_action_contract(
    authorized_context: MonitoringAuthorizedRouteContext,
    *,
    surface: MonitoringReadSurface,
    source_snapshot_sha256: str,
    response_snapshot_sha256: str,
    idempotency_key: str,
    cas_version: int,
) -> MonitoringReadActionContract:
    """Bind exact read evidence without persistence or route execution."""

    return MonitoringReadActionContract(
        authorized_context=authorized_context,
        surface=surface,
        source_snapshot_sha256=source_snapshot_sha256,
        response_snapshot_sha256=response_snapshot_sha256,
        idempotency_key=idempotency_key,
        cas_version=cas_version,
    )


__all__ = [
    "MONITORING_READ_ACTION_CONTRACT_SCHEMA",
    "MonitoringReadActionContract",
    "MonitoringReadActionContractError",
    "MonitoringReadSurface",
    "build_monitoring_read_action_contract",
]
