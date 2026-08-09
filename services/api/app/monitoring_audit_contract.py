"""Offline append-only audit contract for medical-monitoring actions.

The identity authorization contract answers whether a principal may request an
action.  This module records the corresponding decision without persisting it:
every event is bound to the principal snapshot, project, action, source
revision, authorization decision hash and (when applicable) aggregate CAS
versions.  The chain is immutable and hash-linked, but this module does not
open SQLite, append to a repository, or replace the runtime audit store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Iterable, Literal, Mapping

from .monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringAuthorizationDecision,
    MonitoringPrincipal,
    MonitoringRole,
    WRITE_ACTIONS,
)


MONITORING_AUDIT_SCHEMA_VERSION = "monitoring_audit_contract_v1"
MonitoringAuditTargetType = Literal[
    "project",
    "trial",
    "site",
    "subject",
    "risk",
    "batch",
    "source",
    "rule",
    "runtime",
]
_TARGET_TYPES = frozenset(
    {
        "project",
        "trial",
        "site",
        "subject",
        "risk",
        "batch",
        "source",
        "rule",
        "runtime",
    }
)
_SENSITIVE_PAYLOAD_KEYS = frozenset(
    {
        "access_token",
        "authorization",
        "password",
        "secret",
        "session_id",
        "token",
    }
)


class MonitoringAuditContractError(ValueError):
    """Base error for malformed or unsafe audit events."""


class MonitoringAuditChainConflict(MonitoringAuditContractError):
    """The append-only event cannot follow the current chain."""


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MonitoringAuditContractError(f"{field_name} is required")
    return text


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MonitoringAuditContractError("occurred_at must include a timezone")
    return value.astimezone(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256(value: str, field_name: str, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise MonitoringAuditContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze(item) for item in value))
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _role_tuple(values: Iterable[Any], field_name: str) -> tuple[MonitoringRole, ...]:
    if isinstance(values, str):
        values = (values,)
    roles: list[MonitoringRole] = []
    for value in values or ():
        try:
            role = (
                value
                if isinstance(value, MonitoringRole)
                else MonitoringRole(str(value))
            )
        except (TypeError, ValueError) as exc:
            raise MonitoringAuditContractError(
                f"{field_name} contains an unsupported role: {value}"
            ) from exc
        roles.append(role)
    if not roles:
        raise MonitoringAuditContractError(f"{field_name} cannot be empty")
    if len(set(roles)) != len(roles):
        raise MonitoringAuditContractError(f"{field_name} must be unique")
    return tuple(sorted(roles, key=lambda role: role.value))


def _assert_safe_payload(value: Any, path: str = "payload") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in _SENSITIVE_PAYLOAD_KEYS:
                raise MonitoringAuditContractError(
                    f"{path}.{key} contains a secret-bearing field; store only an evidence hash"
                )
            _assert_safe_payload(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _assert_safe_payload(item, f"{path}[{index}]")


@dataclass(frozen=True)
class MonitoringAuditEvent:
    """One hash-bound audit event; no event is physically deleted or edited."""

    audit_id: str
    project_id: str
    principal_id: str
    role_claims: tuple[MonitoringRole, ...]
    matched_roles: tuple[MonitoringRole, ...]
    action: MonitoringAction
    target_type: MonitoringAuditTargetType
    target_id: str
    source_revision: str
    authorization_decision_sha256: str
    decision_allowed: bool
    write_permitted: bool
    mutation_applied: bool
    aggregate_version_before: int
    aggregate_version_after: int
    occurred_at: datetime
    prev_event_hash: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    event_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_id", _required(self.audit_id, "audit_id"))
        object.__setattr__(self, "project_id", _required(self.project_id, "project_id"))
        object.__setattr__(
            self, "principal_id", _required(self.principal_id, "principal_id")
        )
        object.__setattr__(
            self, "role_claims", _role_tuple(self.role_claims, "role_claims")
        )
        object.__setattr__(
            self,
            "matched_roles",
            _role_tuple(self.matched_roles, "matched_roles")
            if self.matched_roles
            else (),
        )
        if not isinstance(self.action, MonitoringAction):
            try:
                object.__setattr__(self, "action", MonitoringAction(self.action))
            except (TypeError, ValueError) as exc:
                raise MonitoringAuditContractError(
                    f"unsupported monitoring action: {self.action}"
                ) from exc
        if self.target_type not in _TARGET_TYPES:
            raise MonitoringAuditContractError(
                f"unsupported audit target_type: {self.target_type}"
            )
        object.__setattr__(self, "target_id", _required(self.target_id, "target_id"))
        object.__setattr__(
            self,
            "source_revision",
            _required(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "authorization_decision_sha256",
            _sha256(
                self.authorization_decision_sha256, "authorization_decision_sha256"
            ),
        )
        for name in ("decision_allowed", "write_permitted", "mutation_applied"):
            if not isinstance(getattr(self, name), bool):
                raise MonitoringAuditContractError(f"{name} must be a boolean")
        for name in ("aggregate_version_before", "aggregate_version_after"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise MonitoringAuditContractError(
                    f"{name} must be a non-negative integer"
                )
        if self.write_permitted and not self.decision_allowed:
            raise MonitoringAuditContractError(
                "write_permitted cannot be true for a denied authorization decision"
            )
        if self.mutation_applied:
            if not self.decision_allowed or not self.write_permitted:
                raise MonitoringAuditContractError(
                    "mutation_applied requires an allowed write authorization"
                )
            if self.action not in WRITE_ACTIONS:
                raise MonitoringAuditContractError(
                    "mutation_applied requires a write action"
                )
            if self.aggregate_version_after != self.aggregate_version_before + 1:
                raise MonitoringAuditContractError(
                    "mutation_applied must advance aggregate version by one"
                )
        elif self.aggregate_version_after != self.aggregate_version_before:
            raise MonitoringAuditContractError(
                "non-mutating audit events cannot change aggregate version"
            )
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        object.__setattr__(
            self,
            "prev_event_hash",
            _sha256(self.prev_event_hash, "prev_event_hash", allow_empty=True),
        )
        frozen_payload = _freeze(dict(self.payload or {}))
        if not isinstance(frozen_payload, Mapping):
            raise MonitoringAuditContractError("audit payload must be an object")
        _assert_safe_payload(_thaw(frozen_payload))
        object.__setattr__(self, "payload", frozen_payload)
        event_hash = _digest(self._hash_payload())
        if self.event_hash and self.event_hash != event_hash:
            raise MonitoringAuditContractError(
                "event_hash does not match immutable audit event payload"
            )
        object.__setattr__(self, "event_hash", event_hash)
        if not set(self.matched_roles).issubset(set(self.role_claims)):
            raise MonitoringAuditContractError(
                "matched_roles must be a subset of role_claims"
            )

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "schema_version": MONITORING_AUDIT_SCHEMA_VERSION,
            "audit_id": self.audit_id,
            "project_id": self.project_id,
            "principal_id": self.principal_id,
            "role_claims": [role.value for role in self.role_claims],
            "matched_roles": [role.value for role in self.matched_roles],
            "action": self.action.value,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "source_revision": self.source_revision,
            "authorization_decision_sha256": self.authorization_decision_sha256,
            "decision_allowed": self.decision_allowed,
            "write_permitted": self.write_permitted,
            "mutation_applied": self.mutation_applied,
            "aggregate_version_before": self.aggregate_version_before,
            "aggregate_version_after": self.aggregate_version_after,
            "occurred_at": self.occurred_at.isoformat(),
            "prev_event_hash": self.prev_event_hash,
            "payload": _thaw(self.payload),
        }

    def public_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "event_hash": self.event_hash}

    @classmethod
    def from_authorization_decision(
        cls,
        *,
        audit_id: str,
        principal: MonitoringPrincipal,
        decision: MonitoringAuthorizationDecision,
        target_type: MonitoringAuditTargetType,
        target_id: str,
        source_revision: str,
        mutation_applied: bool = False,
        aggregate_version_before: int = 0,
        aggregate_version_after: int | None = None,
        occurred_at: datetime,
        prev_event_hash: str = "",
        payload: Mapping[str, Any] | None = None,
    ) -> "MonitoringAuditEvent":
        if decision.principal_id != principal.principal_id:
            raise MonitoringAuditContractError(
                "authorization decision principal does not match the principal snapshot"
            )
        if decision.principal_sha256 != principal.principal_sha256:
            raise MonitoringAuditContractError(
                "authorization decision principal hash does not match the principal snapshot"
            )
        if aggregate_version_after is None:
            aggregate_version_after = aggregate_version_before + (
                1 if mutation_applied else 0
            )
        return cls(
            audit_id=audit_id,
            project_id=decision.project_id,
            principal_id=principal.principal_id,
            role_claims=principal.roles,
            matched_roles=decision.matched_roles,
            action=decision.action,
            target_type=target_type,
            target_id=target_id,
            source_revision=source_revision,
            authorization_decision_sha256=decision.decision_sha256,
            decision_allowed=decision.allowed,
            write_permitted=decision.write_permitted,
            mutation_applied=mutation_applied,
            aggregate_version_before=aggregate_version_before,
            aggregate_version_after=aggregate_version_after,
            occurred_at=occurred_at,
            prev_event_hash=prev_event_hash,
            payload=payload or {},
        )


def verify_monitoring_audit_chain(
    events: Iterable[MonitoringAuditEvent],
) -> str:
    """Validate ordering, uniqueness and links; return the terminal hash."""

    previous_hash = ""
    seen_ids: set[str] = set()
    for event in events:
        if event.audit_id in seen_ids:
            raise MonitoringAuditChainConflict(
                f"duplicate audit_id in append-only chain: {event.audit_id}"
            )
        if event.prev_event_hash != previous_hash:
            raise MonitoringAuditChainConflict(
                f"audit chain predecessor mismatch for {event.audit_id}"
            )
        seen_ids.add(event.audit_id)
        previous_hash = event.event_hash
    return previous_hash


def append_monitoring_audit_event(
    events: Iterable[MonitoringAuditEvent],
    event: MonitoringAuditEvent,
) -> tuple[MonitoringAuditEvent, ...]:
    """Append one event in memory, allowing only exact idempotent replay."""

    current = tuple(events)
    verify_monitoring_audit_chain(current)
    existing = next((item for item in current if item.audit_id == event.audit_id), None)
    if existing is not None:
        if existing.event_hash == event.event_hash:
            return current
        raise MonitoringAuditChainConflict(
            f"audit_id was reused with a different immutable payload: {event.audit_id}"
        )
    expected_previous = current[-1].event_hash if current else ""
    if event.prev_event_hash != expected_previous:
        raise MonitoringAuditChainConflict(
            f"audit event {event.audit_id} does not point to the current chain head"
        )
    return current + (event,)


def monitoring_audit_chain_payload(
    events: Iterable[MonitoringAuditEvent],
) -> list[dict[str, Any]]:
    """Return a JSON-safe audit chain after validating its links."""

    current = tuple(events)
    verify_monitoring_audit_chain(current)
    return [event.public_dict() for event in current]


__all__ = [
    "MONITORING_AUDIT_SCHEMA_VERSION",
    "MonitoringAuditChainConflict",
    "MonitoringAuditContractError",
    "MonitoringAuditEvent",
    "append_monitoring_audit_event",
    "monitoring_audit_chain_payload",
    "verify_monitoring_audit_chain",
]
