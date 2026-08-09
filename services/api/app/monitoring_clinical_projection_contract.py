"""Read-only projections over the shared clinical event contract.

The projection is deliberately downstream of ``MonitoringClinicalEvent``.  It
does not parse listings, infer a clinical relationship, run a rule or write a
database.  Timeline, Patient Profile, AE/lab/vitals/ECG cards and project/site/
subject rollups all retain the event/evidence identity that produced them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping

from .monitoring_clinical_event_contract import (
    ClinicalCompletenessStatus,
    ClinicalDomain,
    ClinicalEventKind,
    ClinicalRuleBinding,
    ClinicalUncertaintyState,
    ClinicalValueStatus,
    ClinicalDatePrecision,
    MonitoringClinicalEvent,
    MonitoringClinicalObservation,
)


class ClinicalProjectionContractError(ValueError):
    """Raised when a read-model projection would be ambiguous or lossy."""


class ClinicalPopulationScope(str, Enum):
    ALL_SUBJECTS = "all_subjects"
    RANDOMIZED_ONLY = "randomized_only"
    ALLOWLIST = "allowlist"


class ClinicalPopulationMembership(str, Enum):
    RANDOMIZED = "randomized"
    SCREEN_FAILURE = "screen_failure"
    NOT_RANDOMIZED = "not_randomized"
    UNKNOWN = "unknown"


class ClinicalVisitKind(str, Enum):
    PLANNED = "planned"
    UNPLANNED = "unplanned"
    UNKNOWN = "unknown"


_OBSERVATION_DOMAINS = frozenset(
    {ClinicalDomain.AE, ClinicalDomain.LAB, ClinicalDomain.VITALS, ClinicalDomain.ECG}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ClinicalProjectionContractError(f"{field_name} is required")
    return text


def _enum(value: Any, enum_type: type[Enum], field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ClinicalProjectionContractError(f"{field_name} is invalid") from exc


def _ids(values: Any, field_name: str) -> tuple[str, ...]:
    if values is None:
        values = ()
    if not isinstance(values, (list, tuple)):
        raise ClinicalProjectionContractError(f"{field_name} must be a list")
    result = tuple(_required(value, f"{field_name} item") for value in values)
    if len(result) != len(set(result)):
        raise ClinicalProjectionContractError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result))


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ClinicalProjectionContractError("projection payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ClinicalProjectionContractError(
            f"{field_name} must be a lowercase SHA-256 hex digest"
        )
    return value


def _declared_sha256(value: Any, field_name: str) -> str:
    """Validate an optional serialized digest without coercion or trimming."""
    if value is None or value == "":
        return ""
    return _sha256(value, field_name)


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ClinicalProjectionContractError(f"{field_name} must be an object")
    try:
        normalized = json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ClinicalProjectionContractError(f"{field_name} must be JSON-serializable") from exc
    if not isinstance(normalized, dict):
        raise ClinicalProjectionContractError(f"{field_name} must be an object")
    return normalized


def _count(values: list[str] | tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _event_sort_key(event: MonitoringClinicalEvent) -> tuple[Any, ...]:
    return (
        0 if event.event_date else 1,
        event.event_date,
        event.visit_number if event.visit_number is not None else 2**31 - 1,
        event.event_id,
    )


def _object_list(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise ClinicalProjectionContractError(f"{field_name} must be a list of objects")
    return tuple(value)


@dataclass(frozen=True)
class MonitoringClinicalProjectionScope:
    project_id: str
    trial_id: str
    population_scope: ClinicalPopulationScope = ClinicalPopulationScope.ALL_SUBJECTS
    subject_ids: tuple[str, ...] = ()
    site_ids: tuple[str, ...] = ()
    include_unplanned: bool = True
    scope_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        project_id = _required(self.project_id, "scope.project_id")
        trial_id = _required(self.trial_id, "scope.trial_id")
        scope = _enum(self.population_scope, ClinicalPopulationScope, "scope.population_scope")
        subject_ids = _ids(self.subject_ids, "scope.subject_ids")
        site_ids = _ids(self.site_ids, "scope.site_ids")
        if scope == ClinicalPopulationScope.ALLOWLIST and not subject_ids:
            raise ClinicalProjectionContractError(
                "allowlist scope requires subject_ids"
            )
        if not isinstance(self.include_unplanned, bool):
            raise ClinicalProjectionContractError("scope.include_unplanned must be boolean")
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "trial_id", trial_id)
        object.__setattr__(self, "population_scope", scope)
        object.__setattr__(self, "subject_ids", subject_ids)
        object.__setattr__(self, "site_ids", site_ids)
        object.__setattr__(self, "scope_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "population_scope": self.population_scope.value,
            "subject_ids": list(self.subject_ids),
            "site_ids": list(self.site_ids),
            "include_unplanned": self.include_unplanned,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "scope_sha256": self.scope_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MonitoringClinicalProjectionScope":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("scope must be an object")
        scope = cls(
            project_id=payload.get("project_id", ""),
            trial_id=payload.get("trial_id", ""),
            population_scope=payload.get("population_scope", ClinicalPopulationScope.ALL_SUBJECTS),
            subject_ids=payload.get("subject_ids", ()),
            site_ids=payload.get("site_ids", ()),
            include_unplanned=payload.get("include_unplanned", True),
        )
        declared_hash = _declared_sha256(payload.get("scope_sha256"), "scope_sha256")
        if declared_hash and declared_hash != scope.scope_sha256:
            raise ClinicalProjectionContractError("scope_sha256 does not match canonical content")
        return scope


@dataclass(frozen=True)
class MonitoringClinicalProjectionContext:
    """Bind source-derived population/visit classifications to one C4 event."""

    event: MonitoringClinicalEvent
    population_membership: ClinicalPopulationMembership = ClinicalPopulationMembership.UNKNOWN
    visit_kind: ClinicalVisitKind = ClinicalVisitKind.UNKNOWN
    population_evidence_ids: tuple[str, ...] = ()
    visit_evidence_ids: tuple[str, ...] = ()
    context_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.event, MonitoringClinicalEvent):
            raise ClinicalProjectionContractError("context.event must be a clinical event")
        membership = _enum(
            self.population_membership,
            ClinicalPopulationMembership,
            "context.population_membership",
        )
        visit_kind = _enum(self.visit_kind, ClinicalVisitKind, "context.visit_kind")
        event_evidence_ids = {item.evidence_id for item in self.event.evidence}
        population_evidence_ids = _ids(
            self.population_evidence_ids, "context.population_evidence_ids"
        )
        visit_evidence_ids = _ids(self.visit_evidence_ids, "context.visit_evidence_ids")
        if set(population_evidence_ids) - event_evidence_ids:
            raise ClinicalProjectionContractError(
                "population evidence must be declared by the event"
            )
        if set(visit_evidence_ids) - event_evidence_ids:
            raise ClinicalProjectionContractError(
                "visit evidence must be declared by the event"
            )
        if membership != ClinicalPopulationMembership.UNKNOWN and not population_evidence_ids:
            raise ClinicalProjectionContractError(
                "known population membership requires population evidence"
            )
        if visit_kind != ClinicalVisitKind.UNKNOWN and not visit_evidence_ids:
            raise ClinicalProjectionContractError(
                "known visit kind requires visit evidence"
            )
        object.__setattr__(self, "population_membership", membership)
        object.__setattr__(self, "visit_kind", visit_kind)
        object.__setattr__(self, "population_evidence_ids", population_evidence_ids)
        object.__setattr__(self, "visit_evidence_ids", visit_evidence_ids)
        object.__setattr__(self, "context_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "event_sha256": self.event.event_sha256,
            "population_membership": self.population_membership.value,
            "visit_kind": self.visit_kind.value,
            "population_evidence_ids": list(self.population_evidence_ids),
            "visit_evidence_ids": list(self.visit_evidence_ids),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.to_dict(),
            **self._payload(),
            "context_sha256": self.context_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MonitoringClinicalProjectionContext":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("projection context must be an object")
        event_payload = payload.get("event")
        if not isinstance(event_payload, Mapping):
            raise ClinicalProjectionContractError("projection context event must be an object")
        context = cls(
            event=MonitoringClinicalEvent.from_dict(event_payload),
            population_membership=payload.get(
                "population_membership", ClinicalPopulationMembership.UNKNOWN
            ),
            visit_kind=payload.get("visit_kind", ClinicalVisitKind.UNKNOWN),
            population_evidence_ids=payload.get("population_evidence_ids", ()),
            visit_evidence_ids=payload.get("visit_evidence_ids", ()),
        )
        declared_hash = _declared_sha256(payload.get("context_sha256"), "context_sha256")
        if declared_hash and declared_hash != context.context_sha256:
            raise ClinicalProjectionContractError(
                "context_sha256 does not match canonical content"
            )
        return context


@dataclass(frozen=True)
class ClinicalRuleProjection:
    binding_id: str
    rule_id: str
    rule_revision: str
    threshold_code: str
    threshold_value: str
    threshold_unit: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("binding_id", "rule_id", "rule_revision"):
            object.__setattr__(self, name, _required(getattr(self, name), f"rule.{name}"))
        for name in ("threshold_code", "threshold_value", "threshold_unit"):
            object.__setattr__(self, name, "" if getattr(self, name) is None else str(getattr(self, name)).strip())
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "rule.evidence_ids"))

    @classmethod
    def from_binding(cls, binding: ClinicalRuleBinding) -> "ClinicalRuleProjection":
        if not isinstance(binding, ClinicalRuleBinding):
            raise ClinicalProjectionContractError("rule binding must be a C4 rule binding")
        return cls(
            binding_id=binding.binding_id,
            rule_id=binding.rule_id,
            rule_revision=binding.rule_revision,
            threshold_code=binding.threshold_code,
            threshold_value=binding.threshold_value,
            threshold_unit=binding.threshold_unit,
            evidence_ids=binding.evidence_ids,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "rule_id": self.rule_id,
            "rule_revision": self.rule_revision,
            "threshold_code": self.threshold_code,
            "threshold_value": self.threshold_value,
            "threshold_unit": self.threshold_unit,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalRuleProjection":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("rule projection must be an object")
        return cls(
            binding_id=payload.get("binding_id", ""),
            rule_id=payload.get("rule_id", ""),
            rule_revision=payload.get("rule_revision", ""),
            threshold_code=payload.get("threshold_code", ""),
            threshold_value=payload.get("threshold_value", ""),
            threshold_unit=payload.get("threshold_unit", ""),
            evidence_ids=payload.get("evidence_ids", ()),
        )


@dataclass(frozen=True)
class ClinicalTimelineProjection:
    event_id: str
    project_id: str
    trial_id: str
    site_id: str
    subject_id: str
    domain: ClinicalDomain
    event_kind: ClinicalEventKind
    event_sha256: str
    event_date: str
    date_precision: str
    date_raw: str
    visit_label: str
    visit_number: int | None
    visit_kind: ClinicalVisitKind
    observation_ids: tuple[str, ...]
    risk_instance_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_locators: tuple[str, ...]
    rule_binding_ids: tuple[str, ...]
    rule_bindings: tuple[ClinicalRuleProjection, ...]
    completeness_status: str
    uncertainty_state: str

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "project_id",
            "trial_id",
            "site_id",
            "subject_id",
            "event_sha256",
        ):
            if name == "event_sha256":
                object.__setattr__(self, name, _sha256(getattr(self, name), name))
            else:
                object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "domain", _enum(self.domain, ClinicalDomain, "timeline.domain"))
        object.__setattr__(self, "event_kind", _enum(self.event_kind, ClinicalEventKind, "timeline.event_kind"))
        object.__setattr__(self, "visit_kind", _enum(self.visit_kind, ClinicalVisitKind, "timeline.visit_kind"))
        object.__setattr__(self, "event_date", str(self.event_date or "").strip())
        object.__setattr__(self, "date_precision", _enum(
            self.date_precision, ClinicalDatePrecision, "timeline.date_precision"
        ).value)
        object.__setattr__(self, "date_raw", str(self.date_raw or "").strip())
        object.__setattr__(self, "visit_label", str(self.visit_label or "").strip())
        object.__setattr__(self, "completeness_status", _enum(
            self.completeness_status,
            ClinicalCompletenessStatus,
            "timeline.completeness_status",
        ).value)
        object.__setattr__(self, "uncertainty_state", _enum(
            self.uncertainty_state,
            ClinicalUncertaintyState,
            "timeline.uncertainty_state",
        ).value)
        if self.visit_number is not None and (
            not isinstance(self.visit_number, int)
            or isinstance(self.visit_number, bool)
            or self.visit_number < 0
        ):
            raise ClinicalProjectionContractError("timeline.visit_number must be non-negative")
        object.__setattr__(self, "observation_ids", _ids(self.observation_ids, "timeline.observation_ids"))
        object.__setattr__(self, "risk_instance_ids", _ids(self.risk_instance_ids, "timeline.risk_instance_ids"))
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "timeline.evidence_ids"))
        object.__setattr__(self, "evidence_locators", tuple(
            _required(value, "timeline.evidence_locators item")
            for value in self.evidence_locators
        ))
        if len(self.evidence_ids) != len(self.evidence_locators):
            raise ClinicalProjectionContractError(
                "timeline evidence ids and locators must align"
            )
        object.__setattr__(self, "rule_binding_ids", _ids(self.rule_binding_ids, "timeline.rule_binding_ids"))
        if not all(isinstance(item, ClinicalRuleProjection) for item in self.rule_bindings):
            raise ClinicalProjectionContractError("timeline.rule_bindings must contain rule projections")
        object.__setattr__(self, "rule_bindings", tuple(sorted(
            self.rule_bindings, key=lambda item: item.binding_id
        )))
        if self.rule_binding_ids != tuple(item.binding_id for item in self.rule_bindings):
            raise ClinicalProjectionContractError(
                "timeline rule binding ids and objects must align"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "site_id": self.site_id,
            "subject_id": self.subject_id,
            "domain": self.domain.value,
            "event_kind": self.event_kind.value,
            "event_sha256": self.event_sha256,
            "event_date": self.event_date,
            "date_precision": self.date_precision,
            "date_raw": self.date_raw,
            "visit_label": self.visit_label,
            "visit_number": self.visit_number,
            "visit_kind": self.visit_kind.value,
            "observation_ids": list(self.observation_ids),
            "risk_instance_ids": list(self.risk_instance_ids),
            "evidence_ids": list(self.evidence_ids),
            "evidence_locators": list(self.evidence_locators),
            "rule_binding_ids": list(self.rule_binding_ids),
            "rule_bindings": [item.to_dict() for item in self.rule_bindings],
            "completeness_status": self.completeness_status,
            "uncertainty_state": self.uncertainty_state,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalTimelineProjection":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("timeline projection must be an object")
        return cls(
            event_id=payload.get("event_id", ""),
            project_id=payload.get("project_id", ""),
            trial_id=payload.get("trial_id", ""),
            site_id=payload.get("site_id", ""),
            subject_id=payload.get("subject_id", ""),
            domain=payload.get("domain", ""),
            event_kind=payload.get("event_kind", ""),
            event_sha256=payload.get("event_sha256", ""),
            event_date=payload.get("event_date", ""),
            date_precision=payload.get("date_precision", ""),
            date_raw=payload.get("date_raw", ""),
            visit_label=payload.get("visit_label", ""),
            visit_number=payload.get("visit_number"),
            visit_kind=payload.get("visit_kind", ClinicalVisitKind.UNKNOWN),
            observation_ids=payload.get("observation_ids", ()),
            risk_instance_ids=payload.get("risk_instance_ids", ()),
            evidence_ids=payload.get("evidence_ids", ()),
            evidence_locators=payload.get("evidence_locators", ()),
            rule_binding_ids=payload.get("rule_binding_ids", ()),
            rule_bindings=tuple(
                ClinicalRuleProjection.from_dict(item)
                for item in _object_list(payload.get("rule_bindings", ()), "timeline.rule_bindings")
            ),
            completeness_status=payload.get("completeness_status", ""),
            uncertainty_state=payload.get("uncertainty_state", ""),
        )


@dataclass(frozen=True)
class ClinicalObservationProjection:
    observation_id: str
    event_id: str
    project_id: str
    trial_id: str
    site_id: str
    subject_id: str
    event_sha256: str
    domain: ClinicalDomain
    field_name: str
    value_status: str
    raw_value: str
    normalized_value: str
    unit: str
    reference_range: Mapping[str, Any] | None
    risk_instance_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_locators: tuple[str, ...]
    rule_binding_ids: tuple[str, ...]
    completeness_status: str
    uncertainty_state: str

    def __post_init__(self) -> None:
        for name in (
            "observation_id",
            "event_id",
            "project_id",
            "trial_id",
            "site_id",
            "subject_id",
            "event_sha256",
            "field_name",
            "value_status",
            "completeness_status",
            "uncertainty_state",
        ):
            if name == "event_sha256":
                object.__setattr__(self, name, _sha256(getattr(self, name), name))
            else:
                object.__setattr__(self, name, _required(getattr(self, name), name))
        object.__setattr__(self, "domain", _enum(self.domain, ClinicalDomain, "observation.domain"))
        object.__setattr__(self, "value_status", _enum(
            self.value_status, ClinicalValueStatus, "observation.value_status"
        ).value)
        object.__setattr__(self, "completeness_status", _enum(
            self.completeness_status,
            ClinicalCompletenessStatus,
            "observation.completeness_status",
        ).value)
        object.__setattr__(self, "uncertainty_state", _enum(
            self.uncertainty_state,
            ClinicalUncertaintyState,
            "observation.uncertainty_state",
        ).value)
        object.__setattr__(self, "raw_value", "" if self.raw_value is None else str(self.raw_value).strip())
        object.__setattr__(self, "normalized_value", "" if self.normalized_value is None else str(self.normalized_value).strip())
        object.__setattr__(self, "unit", "" if self.unit is None else str(self.unit).strip())
        if self.reference_range is not None:
            object.__setattr__(self, "reference_range", _mapping(self.reference_range, "observation.reference_range"))
        object.__setattr__(self, "risk_instance_ids", _ids(self.risk_instance_ids, "observation.risk_instance_ids"))
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "observation.evidence_ids"))
        object.__setattr__(self, "evidence_locators", tuple(
            _required(value, "observation.evidence_locators item")
            for value in self.evidence_locators
        ))
        if len(self.evidence_ids) != len(self.evidence_locators):
            raise ClinicalProjectionContractError(
                "observation evidence ids and locators must align"
            )
        object.__setattr__(self, "rule_binding_ids", _ids(self.rule_binding_ids, "observation.rule_binding_ids"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "event_id": self.event_id,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "site_id": self.site_id,
            "subject_id": self.subject_id,
            "event_sha256": self.event_sha256,
            "domain": self.domain.value,
            "field_name": self.field_name,
            "value_status": self.value_status,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "reference_range": dict(self.reference_range) if self.reference_range else None,
            "risk_instance_ids": list(self.risk_instance_ids),
            "evidence_ids": list(self.evidence_ids),
            "evidence_locators": list(self.evidence_locators),
            "rule_binding_ids": list(self.rule_binding_ids),
            "completeness_status": self.completeness_status,
            "uncertainty_state": self.uncertainty_state,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalObservationProjection":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("observation projection must be an object")
        return cls(
            observation_id=payload.get("observation_id", ""),
            event_id=payload.get("event_id", ""),
            project_id=payload.get("project_id", ""),
            trial_id=payload.get("trial_id", ""),
            site_id=payload.get("site_id", ""),
            subject_id=payload.get("subject_id", ""),
            event_sha256=payload.get("event_sha256", ""),
            domain=payload.get("domain", ""),
            field_name=payload.get("field_name", ""),
            value_status=payload.get("value_status", ""),
            raw_value=payload.get("raw_value", ""),
            normalized_value=payload.get("normalized_value", ""),
            unit=payload.get("unit", ""),
            reference_range=payload.get("reference_range"),
            risk_instance_ids=payload.get("risk_instance_ids", ()),
            evidence_ids=payload.get("evidence_ids", ()),
            evidence_locators=payload.get("evidence_locators", ()),
            rule_binding_ids=payload.get("rule_binding_ids", ()),
            completeness_status=payload.get("completeness_status", ""),
            uncertainty_state=payload.get("uncertainty_state", ""),
        )


@dataclass(frozen=True)
class ClinicalSubjectProfileProjection:
    subject_id: str
    site_id: str
    event_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    risk_instance_ids: tuple[str, ...]
    domain_counts: Mapping[str, int]
    incomplete_event_ids: tuple[str, ...]
    uncertain_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _required(self.subject_id, "profile.subject_id"))
        object.__setattr__(self, "site_id", _required(self.site_id, "profile.site_id"))
        for name in (
            "event_ids",
            "observation_ids",
            "risk_instance_ids",
            "incomplete_event_ids",
            "uncertain_event_ids",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), f"profile.{name}"))
        object.__setattr__(self, "domain_counts", _mapping(self.domain_counts, "profile.domain_counts"))
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in self.domain_counts.values()
        ):
            raise ClinicalProjectionContractError("profile.domain_counts must contain non-negative integers")

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "site_id": self.site_id,
            "event_ids": list(self.event_ids),
            "observation_ids": list(self.observation_ids),
            "risk_instance_ids": list(self.risk_instance_ids),
            "domain_counts": dict(self.domain_counts),
            "incomplete_event_ids": list(self.incomplete_event_ids),
            "uncertain_event_ids": list(self.uncertain_event_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalSubjectProfileProjection":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("profile projection must be an object")
        return cls(
            subject_id=payload.get("subject_id", ""),
            site_id=payload.get("site_id", ""),
            event_ids=payload.get("event_ids", ()),
            observation_ids=payload.get("observation_ids", ()),
            risk_instance_ids=payload.get("risk_instance_ids", ()),
            domain_counts=payload.get("domain_counts", {}),
            incomplete_event_ids=payload.get("incomplete_event_ids", ()),
            uncertain_event_ids=payload.get("uncertain_event_ids", ()),
        )


@dataclass(frozen=True)
class ClinicalRollupProjection:
    level: str
    identity: str
    event_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    risk_instance_ids: tuple[str, ...]
    domain_counts: Mapping[str, int]
    incomplete_event_count: int
    uncertain_event_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "level", _required(self.level, "rollup.level"))
        object.__setattr__(self, "identity", _required(self.identity, "rollup.identity"))
        for name in ("event_ids", "observation_ids", "risk_instance_ids"):
            object.__setattr__(self, name, _ids(getattr(self, name), f"rollup.{name}"))
        object.__setattr__(self, "domain_counts", _mapping(self.domain_counts, "rollup.domain_counts"))
        for name in ("incomplete_event_count", "uncertain_event_count"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ClinicalProjectionContractError(f"rollup.{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "identity": self.identity,
            "event_ids": list(self.event_ids),
            "observation_ids": list(self.observation_ids),
            "risk_instance_ids": list(self.risk_instance_ids),
            "domain_counts": dict(self.domain_counts),
            "incomplete_event_count": self.incomplete_event_count,
            "uncertain_event_count": self.uncertain_event_count,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalRollupProjection":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("rollup projection must be an object")
        return cls(
            level=payload.get("level", ""),
            identity=payload.get("identity", ""),
            event_ids=payload.get("event_ids", ()),
            observation_ids=payload.get("observation_ids", ()),
            risk_instance_ids=payload.get("risk_instance_ids", ()),
            domain_counts=payload.get("domain_counts", {}),
            incomplete_event_count=payload.get("incomplete_event_count", 0),
            uncertain_event_count=payload.get("uncertain_event_count", 0),
        )


@dataclass(frozen=True)
class MonitoringClinicalReadModel:
    scope: MonitoringClinicalProjectionScope
    timeline: tuple[ClinicalTimelineProjection, ...]
    observations: tuple[ClinicalObservationProjection, ...]
    subject_profiles: tuple[ClinicalSubjectProfileProjection, ...]
    site_rollups: tuple[ClinicalRollupProjection, ...]
    project_rollup: ClinicalRollupProjection
    limitations: tuple[str, ...] = ()
    read_model_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if not all(isinstance(item, ClinicalTimelineProjection) for item in self.timeline):
            raise ClinicalProjectionContractError("timeline must contain timeline projections")
        if not all(isinstance(item, ClinicalObservationProjection) for item in self.observations):
            raise ClinicalProjectionContractError("observations must contain observation projections")
        if not all(isinstance(item, ClinicalSubjectProfileProjection) for item in self.subject_profiles):
            raise ClinicalProjectionContractError("subject_profiles must contain profile projections")
        if not all(isinstance(item, ClinicalRollupProjection) for item in self.site_rollups):
            raise ClinicalProjectionContractError("site_rollups must contain rollup projections")
        if not isinstance(self.project_rollup, ClinicalRollupProjection):
            raise ClinicalProjectionContractError("project_rollup must be a rollup projection")
        limitations = _ids(self.limitations, "limitations") if self.limitations else ()
        object.__setattr__(self, "limitations", limitations)
        object.__setattr__(self, "read_model_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "scope": self.scope.to_dict(),
            "timeline": [item.to_dict() for item in self.timeline],
            "observations": [item.to_dict() for item in self.observations],
            "subject_profiles": [item.to_dict() for item in self.subject_profiles],
            "site_rollups": [item.to_dict() for item in self.site_rollups],
            "project_rollup": self.project_rollup.to_dict(),
            "limitations": list(self.limitations),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "read_model_sha256": self.read_model_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MonitoringClinicalReadModel":
        if not isinstance(payload, Mapping):
            raise ClinicalProjectionContractError("read model must be an object")
        model = cls(
            scope=MonitoringClinicalProjectionScope.from_dict(payload.get("scope", {})),
            timeline=tuple(
                ClinicalTimelineProjection.from_dict(item)
                for item in _object_list(payload.get("timeline", ()), "timeline")
            ),
            observations=tuple(
                ClinicalObservationProjection.from_dict(item)
                for item in _object_list(payload.get("observations", ()), "observations")
            ),
            subject_profiles=tuple(
                ClinicalSubjectProfileProjection.from_dict(item)
                for item in _object_list(payload.get("subject_profiles", ()), "subject_profiles")
            ),
            site_rollups=tuple(
                ClinicalRollupProjection.from_dict(item)
                for item in _object_list(payload.get("site_rollups", ()), "site_rollups")
            ),
            project_rollup=ClinicalRollupProjection.from_dict(payload.get("project_rollup", {})),
            limitations=payload.get("limitations", ()),
        )
        declared_hash = _declared_sha256(
            payload.get("read_model_sha256"), "read_model_sha256"
        )
        if declared_hash and declared_hash != model.read_model_sha256:
            raise ClinicalProjectionContractError(
                "read_model_sha256 does not match canonical content"
            )
        return model


def _context_is_in_scope(
    context: MonitoringClinicalProjectionContext,
    scope: MonitoringClinicalProjectionScope,
) -> bool:
    event = context.event
    if event.project_id != scope.project_id or event.trial_id != scope.trial_id:
        raise ClinicalProjectionContractError("projection cannot mix project or trial identities")
    if scope.site_ids and event.site_id not in scope.site_ids:
        return False
    if scope.population_scope == ClinicalPopulationScope.RANDOMIZED_ONLY:
        if context.population_membership == ClinicalPopulationMembership.UNKNOWN:
            raise ClinicalProjectionContractError(
                "randomized_only scope requires explicit population membership"
            )
        if context.population_membership != ClinicalPopulationMembership.RANDOMIZED:
            return False
    elif scope.population_scope == ClinicalPopulationScope.ALLOWLIST:
        if event.subject_id not in scope.subject_ids:
            return False
    if not scope.include_unplanned:
        if context.visit_kind == ClinicalVisitKind.UNKNOWN:
            raise ClinicalProjectionContractError(
                "excluding unplanned visits requires explicit visit kind"
            )
        if context.visit_kind == ClinicalVisitKind.UNPLANNED:
            return False
    return True


def _timeline_projection(
    context: MonitoringClinicalProjectionContext,
) -> ClinicalTimelineProjection:
    event = context.event
    rule_ids = tuple(item.binding_id for item in event.rule_bindings)
    return ClinicalTimelineProjection(
        event_id=event.event_id,
        project_id=event.project_id,
        trial_id=event.trial_id,
        site_id=event.site_id,
        subject_id=event.subject_id,
        domain=event.domain,
        event_kind=event.event_kind,
        event_sha256=event.event_sha256,
        event_date=event.event_date,
        date_precision=event.date_precision.value,
        date_raw=event.date_raw,
        visit_label=event.visit_label,
        visit_number=event.visit_number,
        visit_kind=context.visit_kind,
        observation_ids=tuple(item.observation_id for item in event.observations),
        risk_instance_ids=event.risk_instance_ids,
        evidence_ids=tuple(item.evidence_id for item in event.evidence),
        evidence_locators=tuple(item.locator for item in event.evidence),
        rule_binding_ids=rule_ids,
        rule_bindings=tuple(
            ClinicalRuleProjection.from_binding(item) for item in event.rule_bindings
        ),
        completeness_status=event.completeness.status.value,
        uncertainty_state=event.uncertainty.state.value,
    )


def _observation_projection(
    context: MonitoringClinicalProjectionContext,
    observation: MonitoringClinicalObservation,
) -> ClinicalObservationProjection:
    event = context.event
    evidence_by_id = {item.evidence_id: item for item in event.evidence}
    evidence_locators = tuple(
        evidence_by_id[evidence_id].locator for evidence_id in observation.evidence_ids
    )
    return ClinicalObservationProjection(
        observation_id=observation.observation_id,
        event_id=event.event_id,
        project_id=event.project_id,
        trial_id=event.trial_id,
        site_id=event.site_id,
        subject_id=event.subject_id,
        event_sha256=event.event_sha256,
        domain=observation.domain,
        field_name=observation.field_name,
        value_status=observation.value_status.value,
        raw_value=observation.raw_value,
        normalized_value=observation.normalized_value,
        unit=observation.unit,
        reference_range=observation.reference_range,
        risk_instance_ids=event.risk_instance_ids,
        evidence_ids=observation.evidence_ids,
        evidence_locators=evidence_locators,
        rule_binding_ids=observation.rule_binding_ids,
        completeness_status=observation.completeness.status.value,
        uncertainty_state=observation.uncertainty.state.value,
    )


def _rollup(level: str, identity: str, events: list[MonitoringClinicalEvent]) -> ClinicalRollupProjection:
    event_ids = tuple(sorted({event.event_id for event in events}))
    observations = [observation for event in events for observation in event.observations]
    observation_ids = tuple(sorted({observation.observation_id for observation in observations}))
    risk_ids = tuple(sorted({risk_id for event in events for risk_id in event.risk_instance_ids}))
    domains = [event.domain.value for event in events]
    return ClinicalRollupProjection(
        level=level,
        identity=identity,
        event_ids=event_ids,
        observation_ids=observation_ids,
        risk_instance_ids=risk_ids,
        domain_counts=_count(domains),
        incomplete_event_count=sum(
            event.completeness.status.value != "complete" for event in events
        ),
        uncertain_event_count=sum(
            event.uncertainty.state.value != "none" for event in events
        ),
    )


def project_monitoring_clinical_read_model(
    contexts: tuple[MonitoringClinicalProjectionContext, ...] | list[MonitoringClinicalProjectionContext],
    scope: MonitoringClinicalProjectionScope,
) -> MonitoringClinicalReadModel:
    """Project validated events into deterministic, read-only UI shapes."""

    if not isinstance(scope, MonitoringClinicalProjectionScope):
        raise ClinicalProjectionContractError("scope must be a projection scope")
    if not isinstance(contexts, (list, tuple)):
        raise ClinicalProjectionContractError("contexts must be a list")
    by_event_id: dict[str, MonitoringClinicalProjectionContext] = {}
    for context in contexts:
        if not isinstance(context, MonitoringClinicalProjectionContext):
            raise ClinicalProjectionContractError("contexts must contain projection contexts")
        event_id = context.event.event_id
        previous = by_event_id.get(event_id)
        if previous is not None and previous.context_sha256 != context.context_sha256:
            raise ClinicalProjectionContractError(f"event_id context conflict: {event_id}")
        if previous is None:
            by_event_id[event_id] = context

    selected = [
        context
        for context in by_event_id.values()
        if _context_is_in_scope(context, scope)
    ]
    selected.sort(key=lambda context: _event_sort_key(context.event))
    events = [context.event for context in selected]
    observation_to_event: dict[str, str] = {}
    for event in events:
        for observation in event.observations:
            previous_event_id = observation_to_event.get(observation.observation_id)
            if previous_event_id is not None and previous_event_id != event.event_id:
                raise ClinicalProjectionContractError(
                    "observation_id is reused across events: "
                    f"{observation.observation_id}"
                )
            observation_to_event[observation.observation_id] = event.event_id
    timelines = tuple(_timeline_projection(context) for context in selected)
    observations = tuple(
        _observation_projection(context, observation)
        for context in selected
        for observation in context.event.observations
        if observation.domain in _OBSERVATION_DOMAINS
    )
    subjects: list[ClinicalSubjectProfileProjection] = []
    for subject_id in sorted({event.subject_id for event in events}):
        subject_events = [event for event in events if event.subject_id == subject_id]
        subject_site_ids = {event.site_id for event in subject_events}
        if len(subject_site_ids) != 1:
            raise ClinicalProjectionContractError(
                f"subject identity spans multiple sites: {subject_id}"
            )
        subject_observations = [
            observation for event in subject_events for observation in event.observations
        ]
        subjects.append(
            ClinicalSubjectProfileProjection(
                subject_id=subject_id,
                site_id=subject_events[0].site_id,
                event_ids=tuple(event.event_id for event in subject_events),
                observation_ids=tuple(item.observation_id for item in subject_observations),
                risk_instance_ids=tuple(
                    sorted({risk_id for event in subject_events for risk_id in event.risk_instance_ids})
                ),
                domain_counts=_count([event.domain.value for event in subject_events]),
                incomplete_event_ids=tuple(
                    event.event_id
                    for event in subject_events
                    if event.completeness.status.value != "complete"
                ),
                uncertain_event_ids=tuple(
                    event.event_id
                    for event in subject_events
                    if event.uncertainty.state.value != "none"
                ),
            )
        )
    site_rollups = tuple(
        _rollup(
            "site",
            site_id,
            [event for event in events if event.site_id == site_id],
        )
        for site_id in sorted({event.site_id for event in events})
    )
    limitations: list[str] = []
    if not events:
        limitations.append("empty_event_set")
    if any(context.population_membership == ClinicalPopulationMembership.UNKNOWN for context in selected):
        limitations.append("population_membership_not_provided")
    if any(context.visit_kind == ClinicalVisitKind.UNKNOWN for context in selected):
        limitations.append("visit_kind_not_provided")
    model = MonitoringClinicalReadModel(
        scope=scope,
        timeline=timelines,
        observations=observations,
        subject_profiles=tuple(subjects),
        site_rollups=site_rollups,
        project_rollup=_rollup("project", scope.project_id, events),
        limitations=tuple(sorted(set(limitations))),
    )
    if model.project_rollup.event_ids != tuple(sorted(item.event_id for item in model.timeline)):
        raise ClinicalProjectionContractError("project rollup does not conserve timeline event ids")
    return model


__all__ = [
    "ClinicalObservationProjection",
    "ClinicalPopulationMembership",
    "ClinicalPopulationScope",
    "ClinicalProjectionContractError",
    "ClinicalRuleProjection",
    "ClinicalRollupProjection",
    "ClinicalSubjectProfileProjection",
    "ClinicalTimelineProjection",
    "ClinicalVisitKind",
    "MonitoringClinicalProjectionContext",
    "MonitoringClinicalProjectionScope",
    "MonitoringClinicalReadModel",
    "project_monitoring_clinical_read_model",
]
