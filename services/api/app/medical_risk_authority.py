"""Offline contract for the canonical medical-monitoring risk authority.

This module deliberately contains no database or router code.  It defines the
identity, event and compare-and-swap semantics that the existing snapshot and
disposition stores must converge on before a runtime migration is attempted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any, Mapping, Literal

from packages.contracts.workbench_contracts.models import (
    RiskCase,
    RiskSeverity,
    RiskStatus,
)


RiskScopeType = Literal["trial", "site", "subject"]


class MedicalRiskFindingClass(str, Enum):
    """The medical meaning of a signal, independent of workflow state."""

    RISK = "risk"
    PROMPT = "prompt"
    REGISTERED_FINDING = "registered_finding"
    RESCUE_OR_EXEMPT = "rescue_or_exempt"
    NOT_APPLICABLE = "not_applicable"
    UNCERTAIN = "uncertain"


class MedicalRiskEventType(str, Enum):
    REGISTERED = "registered"
    STATUS_CHANGED = "status_changed"
    MARK_READ = "mark_read"
    DISPOSITION_RECORDED = "disposition_recorded"
    QUERY_DRAFTED = "query_drafted"
    REOPENED = "reopened"
    RECLASSIFIED = "reclassified"


class MedicalRiskDispositionState(str, Enum):
    PENDING_REVIEW = "pending_review"
    REVIEWED = "reviewed"
    QUERY_DRAFT = "query_draft"
    SUBMITTED_FOR_APPROVAL = "submitted_for_approval"
    EXPLAINED_NO_EXTERNAL_ACTION = "explained_no_external_action"
    DATA_CORRECTION = "data_correction"
    FOLLOW_UP = "follow_up"
    PD_UPDATE = "pd_update"
    SAFETY_PV_COLLABORATION = "safety_pv_collaboration"
    CONTINUE_OBSERVATION = "continue_observation"
    DUPLICATE_NOT_APPLICABLE = "duplicate_not_applicable"


class MedicalRiskAuthorityError(ValueError):
    """Base class for contract violations."""


class MedicalRiskIdentityError(MedicalRiskAuthorityError):
    """The aggregate or event does not carry a complete study identity."""


class MedicalRiskEventConflict(MedicalRiskAuthorityError):
    """A non-idempotent event cannot be applied to the current aggregate."""


class MedicalRiskVersionConflict(MedicalRiskEventConflict):
    def __init__(self, *, expected_version: int, actual_version: int) -> None:
        self.expected_version = expected_version
        self.actual_version = actual_version
        super().__init__(
            "stale medical risk event: "
            f"expected_version={expected_version}, actual_version={actual_version}"
        )


class MedicalRiskDuplicateEventConflict(MedicalRiskEventConflict):
    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(f"medical risk event id was reused with a different payload: {event_id}")


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalRiskIdentityError(f"{field_name} is required")
    return text


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise MedicalRiskAuthorityError("timestamps must include a timezone")
    return current.astimezone(timezone.utc)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _ordered_unique(values: Any) -> tuple[str, ...]:
    result: list[str] = []
    for value in values or ():
        token = str(value or "").strip()
        if token and token not in result:
            result.append(token)
    return tuple(result)


@dataclass(frozen=True)
class MedicalRiskIdentity:
    """Stable cross-view identity for one risk instance.

    ``risk_key`` is stable across source batches while ``risk_instance_id`` is
    bound to the evaluated source revision.  Scope fields are intentionally
    redundant: the explicit values prevent a subject/site/trial identifier from
    silently being interpreted at another level by a projection.
    """

    risk_key: str
    risk_instance_id: str
    project_id: str
    trial_id: str
    scope_type: RiskScopeType
    scope_id: str
    site_id: str | None = None
    subject_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("risk_key", "risk_instance_id", "project_id", "trial_id", "scope_id"):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.scope_type not in {"trial", "site", "subject"}:
            raise MedicalRiskIdentityError(f"unsupported scope_type: {self.scope_type}")
        site_id = str(self.site_id or "").strip() or None
        subject_id = str(self.subject_id or "").strip() or None
        object.__setattr__(self, "site_id", site_id)
        object.__setattr__(self, "subject_id", subject_id)
        if self.scope_type == "trial":
            if self.scope_id != self.trial_id or site_id or subject_id:
                raise MedicalRiskIdentityError(
                    "trial scope must use trial_id as scope_id and cannot carry site/subject"
                )
        elif self.scope_type == "site":
            if not site_id or self.scope_id != site_id or subject_id:
                raise MedicalRiskIdentityError(
                    "site scope must use site_id as scope_id and cannot carry subject"
                )
        elif not subject_id or self.scope_id != subject_id or not site_id:
            raise MedicalRiskIdentityError(
                "subject scope must use subject_id as scope_id and include site_id"
            )

    def public_dict(self) -> dict[str, Any]:
        return {
            "risk_key": self.risk_key,
            "risk_instance_id": self.risk_instance_id,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "site_id": self.site_id,
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True)
class MedicalRiskEvent:
    """Immutable append-only event addressed to one exact aggregate identity."""

    event_id: str
    event_type: MedicalRiskEventType
    identity: MedicalRiskIdentity
    source_revision: str
    actor: str
    expected_version: int
    payload: Mapping[str, Any]
    occurred_at: datetime
    event_hash: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.event_type, MedicalRiskEventType):
            object.__setattr__(self, "event_type", MedicalRiskEventType(self.event_type))
        object.__setattr__(self, "event_id", _required(self.event_id, "event_id"))
        object.__setattr__(self, "source_revision", _required(self.source_revision, "source_revision"))
        object.__setattr__(self, "actor", _required(self.actor, "actor"))
        if self.expected_version < 0:
            raise MedicalRiskAuthorityError("expected_version must be non-negative")
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        frozen_payload = _freeze(dict(self.payload or {}))
        if not isinstance(frozen_payload, Mapping):
            raise MedicalRiskAuthorityError("event payload must be an object")
        object.__setattr__(self, "payload", frozen_payload)
        event_hash = _digest(self._hash_payload())
        if self.event_hash and self.event_hash != event_hash:
            raise MedicalRiskAuthorityError("event_hash does not match immutable event payload")
        object.__setattr__(self, "event_hash", event_hash)
        self._validate_payload()

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "identity": self.identity.public_dict(),
            "source_revision": self.source_revision,
            "actor": self.actor,
            "expected_version": self.expected_version,
            "payload": _thaw(self.payload),
            "occurred_at": self.occurred_at.isoformat(),
        }

    def _validate_payload(self) -> None:
        if self.event_type == MedicalRiskEventType.STATUS_CHANGED:
            if str(self.payload.get("status", "")).strip() not in {item.value for item in RiskStatus}:
                raise MedicalRiskAuthorityError("status_changed requires a valid risk status")
        elif self.event_type == MedicalRiskEventType.MARK_READ:
            if self.payload.get("unread", False) is not False:
                raise MedicalRiskAuthorityError("mark_read can only set unread=false")
        elif self.event_type == MedicalRiskEventType.DISPOSITION_RECORDED:
            state = _required(self.payload.get("disposition_state"), "disposition_state")
            if state not in {item.value for item in MedicalRiskDispositionState}:
                raise MedicalRiskAuthorityError("disposition_state is not a supported workflow state")
        elif self.event_type == MedicalRiskEventType.QUERY_DRAFTED:
            _required(self.payload.get("query_draft_text"), "query_draft_text")
        elif self.event_type == MedicalRiskEventType.REOPENED:
            state = str(self.payload.get("disposition_state", "pending_review")).strip()
            if state != MedicalRiskDispositionState.PENDING_REVIEW.value:
                raise MedicalRiskAuthorityError("reopened events must return to pending_review")
        elif self.event_type == MedicalRiskEventType.RECLASSIFIED:
            raw_class = str(self.payload.get("finding_class", "")).strip()
            if raw_class not in {item.value for item in MedicalRiskFindingClass}:
                raise MedicalRiskAuthorityError("reclassified requires a valid finding_class")

    @classmethod
    def create(
        cls,
        *,
        event_id: str,
        event_type: MedicalRiskEventType,
        identity: MedicalRiskIdentity,
        source_revision: str,
        actor: str,
        expected_version: int,
        payload: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> "MedicalRiskEvent":
        return cls(
            event_id=event_id,
            event_type=event_type,
            identity=identity,
            source_revision=source_revision,
            actor=actor,
            expected_version=expected_version,
            payload=payload or {},
            occurred_at=_utc(occurred_at),
        )

    def public_dict(self) -> dict[str, Any]:
        return {
            **self._hash_payload(),
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True)
class MedicalRiskAggregate:
    """Canonical risk fact plus current workflow projections.

    The medical finding class, risk status, unread state, and disposition state
    are separate fields.  This prevents a terminal workflow label such as
    ``data_correction`` from being mistaken for a medical conclusion.
    """

    identity: MedicalRiskIdentity
    category: str
    severity: RiskSeverity
    finding_class: MedicalRiskFindingClass
    status: RiskStatus
    source_revision: str
    rule_profile_revision: str
    engine_version: str
    rule_id: str
    title: str
    rationale: str
    recommended_action: str
    evidence_ids: tuple[str, ...]
    disposition_state: MedicalRiskDispositionState = MedicalRiskDispositionState.PENDING_REVIEW
    query_draft_text: str = ""
    unread: bool = True
    aggregate_version: int = 0
    last_event_id: str = ""
    applied_events: tuple[tuple[str, str], ...] = ()
    created_at: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)
    updated_at: datetime = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def __post_init__(self) -> None:
        if not isinstance(self.severity, RiskSeverity):
            object.__setattr__(self, "severity", RiskSeverity(self.severity))
        if not isinstance(self.finding_class, MedicalRiskFindingClass):
            object.__setattr__(self, "finding_class", MedicalRiskFindingClass(self.finding_class))
        if not isinstance(self.status, RiskStatus):
            object.__setattr__(self, "status", RiskStatus(self.status))
        if not isinstance(self.disposition_state, MedicalRiskDispositionState):
            object.__setattr__(
                self,
                "disposition_state",
                MedicalRiskDispositionState(self.disposition_state),
            )
        for name in (
            "category",
            "source_revision",
            "rule_profile_revision",
            "engine_version",
            "rule_id",
            "title",
            "rationale",
            "recommended_action",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), name))
        if self.aggregate_version < 0:
            raise MedicalRiskAuthorityError("aggregate_version must be non-negative")
        if self.aggregate_version != len(self.applied_events):
            raise MedicalRiskAuthorityError(
                "aggregate_version must equal the number of applied immutable events"
            )
        event_ids = [event_id for event_id, _ in self.applied_events]
        if len(event_ids) != len(set(event_ids)):
            raise MedicalRiskAuthorityError("applied event ids must be unique")
        object.__setattr__(self, "evidence_ids", _ordered_unique(self.evidence_ids))
        object.__setattr__(self, "created_at", _utc(self.created_at))
        object.__setattr__(self, "updated_at", _utc(self.updated_at))
        if self.updated_at < self.created_at:
            raise MedicalRiskAuthorityError("updated_at cannot precede created_at")

    @classmethod
    def from_risk_case(
        cls,
        risk: RiskCase,
        *,
        trial_id: str,
        finding_class: MedicalRiskFindingClass = MedicalRiskFindingClass.REGISTERED_FINDING,
        disposition_state: MedicalRiskDispositionState = MedicalRiskDispositionState.PENDING_REVIEW,
        unread: bool = True,
    ) -> "MedicalRiskAggregate":
        identity = MedicalRiskIdentity(
            risk_key=risk.risk_key or risk.risk_id,
            risk_instance_id=risk.risk_instance_id or risk.risk_id,
            project_id=risk.project_id,
            trial_id=trial_id,
            scope_type=risk.scope_type,
            scope_id=risk.scope_id,
            site_id=risk.site_id,
            subject_id=risk.subject_id,
        )
        created_at = _utc(risk.created_at)
        return cls(
            identity=identity,
            category=risk.primary_category or risk.risk_type,
            severity=risk.severity,
            finding_class=finding_class,
            status=risk.status,
            source_revision=_required(risk.source_revision, "risk.source_revision"),
            rule_profile_revision=_required(
                risk.rule_profile_revision, "risk.rule_profile_revision"
            ),
            engine_version=_required(risk.engine_version, "risk.engine_version"),
            rule_id=_required(risk.rule_id, "risk.rule_id"),
            title=_required(risk.title, "risk.title"),
            rationale=_required(risk.rationale, "risk.rationale"),
            recommended_action=_required(risk.recommended_action, "risk.recommended_action"),
            evidence_ids=_ordered_unique(risk.evidence_span_ids),
            disposition_state=disposition_state,
            unread=unread,
            created_at=created_at,
            updated_at=created_at,
        )

    def _event_match(self, event: MedicalRiskEvent) -> tuple[str, str] | None:
        if event.identity != self.identity:
            raise MedicalRiskIdentityError("event identity does not match the aggregate")
        if event.source_revision != self.source_revision:
            raise MedicalRiskIdentityError("event source revision does not match the aggregate")
        return next(
            (entry for entry in self.applied_events if entry[0] == event.event_id),
            None,
        )

    def apply(self, event: MedicalRiskEvent) -> "MedicalRiskAggregate":
        existing = self._event_match(event)
        if existing is not None:
            if existing[1] == event.event_hash:
                return self
            raise MedicalRiskDuplicateEventConflict(event.event_id)
        if event.expected_version != self.aggregate_version:
            raise MedicalRiskVersionConflict(
                expected_version=event.expected_version,
                actual_version=self.aggregate_version,
            )

        update: dict[str, Any] = {}
        if event.event_type == MedicalRiskEventType.STATUS_CHANGED:
            update["status"] = RiskStatus(str(event.payload["status"]))
        elif event.event_type == MedicalRiskEventType.MARK_READ:
            update["unread"] = False
        elif event.event_type == MedicalRiskEventType.DISPOSITION_RECORDED:
            update["disposition_state"] = MedicalRiskDispositionState(
                str(event.payload["disposition_state"])
            )
        elif event.event_type == MedicalRiskEventType.QUERY_DRAFTED:
            update["disposition_state"] = MedicalRiskDispositionState.QUERY_DRAFT
            update["query_draft_text"] = _required(
                event.payload["query_draft_text"], "query_draft_text"
            )
        elif event.event_type == MedicalRiskEventType.REOPENED:
            update["disposition_state"] = MedicalRiskDispositionState.PENDING_REVIEW
            update["query_draft_text"] = ""
        elif event.event_type == MedicalRiskEventType.RECLASSIFIED:
            update["finding_class"] = MedicalRiskFindingClass(
                str(event.payload["finding_class"])
            )
        update.update(
            aggregate_version=self.aggregate_version + 1,
            last_event_id=event.event_id,
            applied_events=self.applied_events + ((event.event_id, event.event_hash),),
            updated_at=event.occurred_at,
        )
        return replace(self, **update)

    def public_dict(self) -> dict[str, Any]:
        return {
            **self.identity.public_dict(),
            "category": self.category,
            "severity": self.severity.value,
            "finding_class": self.finding_class.value,
            "status": self.status.value,
            "source_revision": self.source_revision,
            "rule_profile_revision": self.rule_profile_revision,
            "engine_version": self.engine_version,
            "rule_id": self.rule_id,
            "title": self.title,
            "rationale": self.rationale,
            "recommended_action": self.recommended_action,
            "evidence_ids": list(self.evidence_ids),
            "disposition_state": self.disposition_state.value,
            "query_draft_text": self.query_draft_text,
            "unread": self.unread,
            "aggregate_version": self.aggregate_version,
            "last_event_id": self.last_event_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


def append_medical_risk_event(
    aggregate: MedicalRiskAggregate,
    event: MedicalRiskEvent,
) -> MedicalRiskAggregate:
    """Apply one append-only event using the aggregate's CAS boundary."""

    return aggregate.apply(event)


__all__ = [
    "MedicalRiskAggregate",
    "MedicalRiskAuthorityError",
    "MedicalRiskDispositionState",
    "MedicalRiskDuplicateEventConflict",
    "MedicalRiskEvent",
    "MedicalRiskEventConflict",
    "MedicalRiskEventType",
    "MedicalRiskFindingClass",
    "MedicalRiskIdentity",
    "MedicalRiskIdentityError",
    "MedicalRiskVersionConflict",
    "append_medical_risk_event",
]
