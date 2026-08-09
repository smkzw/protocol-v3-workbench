"""Source-preserving consumer handoff for the clinical read model.

This module adapts the C5 read model to the existing Timeline/Profile/risk
consumer vocabulary.  It is a projection-only boundary: no source parsing,
clinical inference, severity calculation, persistence or UI mutation occurs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping

from .monitoring_clinical_event_contract import ClinicalDomain
from .monitoring_clinical_projection_contract import (
    ClinicalObservationProjection,
    ClinicalRollupProjection,
    ClinicalTimelineProjection,
    MonitoringClinicalReadModel,
)


class ClinicalConsumerHandoffError(ValueError):
    """Raised when a consumer projection would lose source identity."""


_DOMAIN_TO_EVENT_TYPE = {
    ClinicalDomain.VISIT: "visit",
    ClinicalDomain.AE: "adverse_event",
    ClinicalDomain.MH: "medical_history",
    ClinicalDomain.CM: "concomitant_medication",
    ClinicalDomain.IP: "study_drug_administration",
    ClinicalDomain.LAB: "lab",
    ClinicalDomain.VITALS: "vitals",
    ClinicalDomain.ECG: "ecg",
    ClinicalDomain.EFFICACY: "efficacy_score",
    ClinicalDomain.FINDING: "finding",
    ClinicalDomain.PD: "protocol_deviation",
    ClinicalDomain.OTHER: "other",
}

_DOMAIN_LABEL = {
    ClinicalDomain.VISIT: "访视",
    ClinicalDomain.AE: "AE记录",
    ClinicalDomain.MH: "病史",
    ClinicalDomain.CM: "合并用药（非试验用药）",
    ClinicalDomain.IP: "试验药物",
    ClinicalDomain.LAB: "实验室",
    ClinicalDomain.VITALS: "生命体征",
    ClinicalDomain.ECG: "心电图",
    ClinicalDomain.EFFICACY: "疗效评估",
    ClinicalDomain.FINDING: "Finding",
    ClinicalDomain.PD: "PD",
    ClinicalDomain.OTHER: "其他事件",
}

_SAFETY_DOMAINS = frozenset(
    {ClinicalDomain.AE, ClinicalDomain.LAB, ClinicalDomain.VITALS, ClinicalDomain.ECG}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ClinicalConsumerHandoffError(f"{field_name} is required")
    return text


def _ids(values: Any, field_name: str) -> tuple[str, ...]:
    if values is None:
        values = ()
    if not isinstance(values, (list, tuple)):
        raise ClinicalConsumerHandoffError(f"{field_name} must be a list")
    result = tuple(_required(value, f"{field_name} item") for value in values)
    if len(result) != len(set(result)):
        raise ClinicalConsumerHandoffError(f"{field_name} must not contain duplicates")
    return tuple(sorted(result))


def _ordered_strings(values: Any, field_name: str) -> tuple[str, ...]:
    if values is None:
        values = ()
    if not isinstance(values, (list, tuple)):
        raise ClinicalConsumerHandoffError(f"{field_name} must be a list")
    result = tuple(_required(value, f"{field_name} item") for value in values)
    if len(result) != len(set(result)):
        raise ClinicalConsumerHandoffError(f"{field_name} must not contain duplicates")
    return result


def _aligned_evidence(
    evidence_ids: Any,
    evidence_locators: Any,
    field_name: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ids = _ordered_strings(evidence_ids, f"{field_name}.evidence_ids")
    locators = _ordered_strings(evidence_locators, f"{field_name}.evidence_locators")
    if len(ids) != len(locators):
        raise ClinicalConsumerHandoffError(
            f"{field_name} evidence ids and locators must align"
        )
    pairs = tuple(sorted(zip(ids, locators), key=lambda pair: pair[0]))
    return tuple(pair[0] for pair in pairs), tuple(pair[1] for pair in pairs)


def _mapping(value: Any, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ClinicalConsumerHandoffError(f"{field_name} must be an object")
    try:
        normalized = json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise ClinicalConsumerHandoffError(f"{field_name} must be JSON-serializable") from exc
    if not isinstance(normalized, dict):
        raise ClinicalConsumerHandoffError(f"{field_name} must be an object")
    return normalized


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ClinicalConsumerHandoffError("handoff payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _sha256(value: Any, field_name: str) -> str:
    """Require an exact lowercase digest at the consumer boundary.

    Consumer handoff data is already a downstream projection.  Normalizing a
    malformed or padded digest here would make an untrusted payload appear
    source-bound, so shape errors fail closed before any canonical comparison.
    """

    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ClinicalConsumerHandoffError(
            f"{field_name} must be a lowercase SHA-256"
        )
    return value


def _objects(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(item, Mapping) for item in value
    ):
        raise ClinicalConsumerHandoffError(f"{field_name} must be a list of objects")
    return tuple(value)


@dataclass(frozen=True)
class ClinicalConsumerTimelineRecord:
    event_id: str
    event_sha256: str
    project_id: str
    trial_id: str
    site_id: str
    subject_id: str
    event_type: str
    source_domain: ClinicalDomain
    title: str
    detail: str
    event_date: str
    date_precision: str
    raw_event_date: str
    visit_label: str
    visit_number: int | None
    is_unscheduled: bool
    related_risk_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_locators: tuple[str, ...]
    rule_binding_ids: tuple[str, ...]
    completeness_status: str
    uncertainty_state: str

    def __post_init__(self) -> None:
        for name in (
            "event_id",
            "project_id",
            "trial_id",
            "site_id",
            "subject_id",
            "event_type",
            "title",
            "detail",
            "date_precision",
            "completeness_status",
            "uncertainty_state",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"timeline.{name}"))
        object.__setattr__(self, "event_sha256", _sha256(self.event_sha256, "timeline.event_sha256"))
        if not isinstance(self.source_domain, ClinicalDomain):
            try:
                object.__setattr__(self, "source_domain", ClinicalDomain(self.source_domain))
            except (TypeError, ValueError) as exc:
                raise ClinicalConsumerHandoffError("timeline.source_domain is invalid") from exc
        object.__setattr__(self, "event_date", "" if self.event_date is None else str(self.event_date).strip())
        object.__setattr__(self, "raw_event_date", "" if self.raw_event_date is None else str(self.raw_event_date).strip())
        object.__setattr__(self, "visit_label", "" if self.visit_label is None else str(self.visit_label).strip())
        if self.visit_number is not None and (
            not isinstance(self.visit_number, int)
            or isinstance(self.visit_number, bool)
            or self.visit_number < 0
        ):
            raise ClinicalConsumerHandoffError("timeline.visit_number must be non-negative")
        if not isinstance(self.is_unscheduled, bool):
            raise ClinicalConsumerHandoffError("timeline.is_unscheduled must be boolean")
        for name in (
            "related_risk_ids",
            "rule_binding_ids",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), f"timeline.{name}"))
        evidence_ids, evidence_locators = _aligned_evidence(
            self.evidence_ids, self.evidence_locators, "timeline"
        )
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "evidence_locators", evidence_locators)
        if self.event_type != _DOMAIN_TO_EVENT_TYPE[self.source_domain]:
            raise ClinicalConsumerHandoffError("timeline event_type does not match source_domain")

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_sha256": self.event_sha256,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "site_id": self.site_id,
            "subject_id": self.subject_id,
            "event_type": self.event_type,
            "source_domain": self.source_domain.value,
            "title": self.title,
            "detail": self.detail,
            "event_date": self.event_date,
            "date_precision": self.date_precision,
            "raw_event_date": self.raw_event_date,
            "visit_label": self.visit_label,
            "visit_number": self.visit_number,
            "is_unscheduled": self.is_unscheduled,
            "related_risk_ids": list(self.related_risk_ids),
            "evidence_ids": list(self.evidence_ids),
            "evidence_locators": list(self.evidence_locators),
            "rule_binding_ids": list(self.rule_binding_ids),
            "completeness_status": self.completeness_status,
            "uncertainty_state": self.uncertainty_state,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalConsumerTimelineRecord":
        if not isinstance(payload, Mapping):
            raise ClinicalConsumerHandoffError("timeline record must be an object")
        return cls(
            event_id=payload.get("event_id", ""),
            event_sha256=payload.get("event_sha256", ""),
            project_id=payload.get("project_id", ""),
            trial_id=payload.get("trial_id", ""),
            site_id=payload.get("site_id", ""),
            subject_id=payload.get("subject_id", ""),
            event_type=payload.get("event_type", ""),
            source_domain=payload.get("source_domain", ""),
            title=payload.get("title", ""),
            detail=payload.get("detail", ""),
            event_date=payload.get("event_date", ""),
            date_precision=payload.get("date_precision", ""),
            raw_event_date=payload.get("raw_event_date", ""),
            visit_label=payload.get("visit_label", ""),
            visit_number=payload.get("visit_number"),
            is_unscheduled=payload.get("is_unscheduled", False),
            related_risk_ids=payload.get("related_risk_ids", ()),
            evidence_ids=payload.get("evidence_ids", ()),
            evidence_locators=payload.get("evidence_locators", ()),
            rule_binding_ids=payload.get("rule_binding_ids", ()),
            completeness_status=payload.get("completeness_status", ""),
            uncertainty_state=payload.get("uncertainty_state", ""),
        )


@dataclass(frozen=True)
class ClinicalSafetyMetricPoint:
    point_id: str
    event_id: str
    event_sha256: str
    subject_id: str
    site_id: str
    domain: ClinicalDomain
    field_name: str
    assessment_date: str
    date_precision: str
    visit_label: str
    visit_number: int | None
    value_status: str
    value: str
    normalized_value: str
    unit: str
    reference_range: Mapping[str, Any] | None
    related_risk_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_locators: tuple[str, ...]
    rule_binding_ids: tuple[str, ...]
    completeness_status: str
    uncertainty_state: str

    def __post_init__(self) -> None:
        for name in (
            "point_id",
            "event_id",
            "subject_id",
            "site_id",
            "field_name",
            "assessment_date",
            "date_precision",
            "value_status",
            "completeness_status",
            "uncertainty_state",
        ):
            if name == "assessment_date":
                object.__setattr__(self, name, "" if getattr(self, name) is None else str(getattr(self, name)).strip())
            else:
                object.__setattr__(self, name, _required(getattr(self, name), f"metric.{name}"))
        object.__setattr__(self, "event_sha256", _sha256(self.event_sha256, "metric.event_sha256"))
        if not isinstance(self.domain, ClinicalDomain):
            try:
                object.__setattr__(self, "domain", ClinicalDomain(self.domain))
            except (TypeError, ValueError) as exc:
                raise ClinicalConsumerHandoffError("metric.domain is invalid") from exc
        for name in ("value", "normalized_value", "unit", "visit_label"):
            object.__setattr__(self, name, "" if getattr(self, name) is None else str(getattr(self, name)).strip())
        if self.visit_number is not None and (
            not isinstance(self.visit_number, int)
            or isinstance(self.visit_number, bool)
            or self.visit_number < 0
        ):
            raise ClinicalConsumerHandoffError("metric.visit_number must be non-negative")
        object.__setattr__(self, "reference_range", _mapping(self.reference_range, "metric.reference_range"))
        for name in (
            "related_risk_ids",
            "rule_binding_ids",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), f"metric.{name}"))
        evidence_ids, evidence_locators = _aligned_evidence(
            self.evidence_ids, self.evidence_locators, "metric"
        )
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "evidence_locators", evidence_locators)

    def to_dict(self) -> dict[str, Any]:
        return {
            "point_id": self.point_id,
            "event_id": self.event_id,
            "event_sha256": self.event_sha256,
            "subject_id": self.subject_id,
            "site_id": self.site_id,
            "domain": self.domain.value,
            "field_name": self.field_name,
            "assessment_date": self.assessment_date,
            "date_precision": self.date_precision,
            "visit_label": self.visit_label,
            "visit_number": self.visit_number,
            "value_status": self.value_status,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "reference_range": dict(self.reference_range) if self.reference_range else None,
            "related_risk_ids": list(self.related_risk_ids),
            "evidence_ids": list(self.evidence_ids),
            "evidence_locators": list(self.evidence_locators),
            "rule_binding_ids": list(self.rule_binding_ids),
            "completeness_status": self.completeness_status,
            "uncertainty_state": self.uncertainty_state,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalSafetyMetricPoint":
        if not isinstance(payload, Mapping):
            raise ClinicalConsumerHandoffError("metric point must be an object")
        return cls(
            point_id=payload.get("point_id", ""),
            event_id=payload.get("event_id", ""),
            event_sha256=payload.get("event_sha256", ""),
            subject_id=payload.get("subject_id", ""),
            site_id=payload.get("site_id", ""),
            domain=payload.get("domain", ""),
            field_name=payload.get("field_name", ""),
            assessment_date=payload.get("assessment_date", ""),
            date_precision=payload.get("date_precision", ""),
            visit_label=payload.get("visit_label", ""),
            visit_number=payload.get("visit_number"),
            value_status=payload.get("value_status", ""),
            value=payload.get("value", ""),
            normalized_value=payload.get("normalized_value", ""),
            unit=payload.get("unit", ""),
            reference_range=payload.get("reference_range"),
            related_risk_ids=payload.get("related_risk_ids", ()),
            evidence_ids=payload.get("evidence_ids", ()),
            evidence_locators=payload.get("evidence_locators", ()),
            rule_binding_ids=payload.get("rule_binding_ids", ()),
            completeness_status=payload.get("completeness_status", ""),
            uncertainty_state=payload.get("uncertainty_state", ""),
        )


@dataclass(frozen=True)
class ClinicalSafetyMetric:
    metric_key: str
    domain: ClinicalDomain
    field_name: str
    points: tuple[ClinicalSafetyMetricPoint, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_key", _required(self.metric_key, "metric.metric_key"))
        object.__setattr__(self, "field_name", _required(self.field_name, "metric.field_name"))
        if not isinstance(self.domain, ClinicalDomain):
            try:
                object.__setattr__(self, "domain", ClinicalDomain(self.domain))
            except (TypeError, ValueError) as exc:
                raise ClinicalConsumerHandoffError("metric.domain is invalid") from exc
        if self.domain not in _SAFETY_DOMAINS:
            raise ClinicalConsumerHandoffError("metric domain is not an explicit safety domain")
        if not all(isinstance(item, ClinicalSafetyMetricPoint) for item in self.points):
            raise ClinicalConsumerHandoffError("metric points must contain point projections")
        if self.metric_key != f"{self.domain.value}:{self.field_name}":
            raise ClinicalConsumerHandoffError("metric_key does not match metric domain/field")
        if any(item.domain != self.domain or item.field_name != self.field_name for item in self.points):
            raise ClinicalConsumerHandoffError("metric points do not match metric identity")
        point_ids = [item.point_id for item in self.points]
        if len(point_ids) != len(set(point_ids)):
            raise ClinicalConsumerHandoffError("metric point ids must be unique")
        object.__setattr__(self, "points", tuple(sorted(
            self.points,
            key=lambda item: (item.assessment_date, item.point_id),
        )))

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "domain": self.domain.value,
            "field_name": self.field_name,
            "points": [item.to_dict() for item in self.points],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalSafetyMetric":
        if not isinstance(payload, Mapping):
            raise ClinicalConsumerHandoffError("metric must be an object")
        return cls(
            metric_key=payload.get("metric_key", ""),
            domain=payload.get("domain", ""),
            field_name=payload.get("field_name", ""),
            points=tuple(
                ClinicalSafetyMetricPoint.from_dict(item)
                for item in _objects(payload.get("points", ()), "metric.points")
            ),
        )


@dataclass(frozen=True)
class ClinicalRiskDrilldownRecord:
    risk_instance_id: str
    event_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    subject_ids: tuple[str, ...]
    site_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_locators: tuple[str, ...]
    rule_binding_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "risk_instance_id", _required(self.risk_instance_id, "risk.risk_instance_id"))
        for name in (
            "event_ids",
            "observation_ids",
            "subject_ids",
            "site_ids",
            "rule_binding_ids",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), f"risk.{name}"))
        evidence_ids, evidence_locators = _aligned_evidence(
            self.evidence_ids, self.evidence_locators, "risk"
        )
        object.__setattr__(self, "evidence_ids", evidence_ids)
        object.__setattr__(self, "evidence_locators", evidence_locators)

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_instance_id": self.risk_instance_id,
            "event_ids": list(self.event_ids),
            "observation_ids": list(self.observation_ids),
            "subject_ids": list(self.subject_ids),
            "site_ids": list(self.site_ids),
            "evidence_ids": list(self.evidence_ids),
            "evidence_locators": list(self.evidence_locators),
            "rule_binding_ids": list(self.rule_binding_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalRiskDrilldownRecord":
        if not isinstance(payload, Mapping):
            raise ClinicalConsumerHandoffError("risk drilldown must be an object")
        return cls(
            risk_instance_id=payload.get("risk_instance_id", ""),
            event_ids=payload.get("event_ids", ()),
            observation_ids=payload.get("observation_ids", ()),
            subject_ids=payload.get("subject_ids", ()),
            site_ids=payload.get("site_ids", ()),
            evidence_ids=payload.get("evidence_ids", ()),
            evidence_locators=payload.get("evidence_locators", ()),
            rule_binding_ids=payload.get("rule_binding_ids", ()),
        )


@dataclass(frozen=True)
class ClinicalSubjectConsumerRecord:
    subject_id: str
    site_id: str
    event_ids: tuple[str, ...]
    observation_ids: tuple[str, ...]
    risk_instance_ids: tuple[str, ...]
    timeline_event_ids: tuple[str, ...]
    safety_metric_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject_id", _required(self.subject_id, "subject.subject_id"))
        object.__setattr__(self, "site_id", _required(self.site_id, "subject.site_id"))
        for name in (
            "event_ids",
            "observation_ids",
            "risk_instance_ids",
            "timeline_event_ids",
            "safety_metric_keys",
        ):
            object.__setattr__(self, name, _ids(getattr(self, name), f"subject.{name}"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "site_id": self.site_id,
            "event_ids": list(self.event_ids),
            "observation_ids": list(self.observation_ids),
            "risk_instance_ids": list(self.risk_instance_ids),
            "timeline_event_ids": list(self.timeline_event_ids),
            "safety_metric_keys": list(self.safety_metric_keys),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalSubjectConsumerRecord":
        if not isinstance(payload, Mapping):
            raise ClinicalConsumerHandoffError("subject consumer record must be an object")
        return cls(
            subject_id=payload.get("subject_id", ""),
            site_id=payload.get("site_id", ""),
            event_ids=payload.get("event_ids", ()),
            observation_ids=payload.get("observation_ids", ()),
            risk_instance_ids=payload.get("risk_instance_ids", ()),
            timeline_event_ids=payload.get("timeline_event_ids", ()),
            safety_metric_keys=payload.get("safety_metric_keys", ()),
        )


@dataclass(frozen=True)
class ClinicalConsumerHandoff:
    project_id: str
    trial_id: str
    scope_sha256: str
    timeline: tuple[ClinicalConsumerTimelineRecord, ...]
    safety_metrics: tuple[ClinicalSafetyMetric, ...]
    risk_drilldown: tuple[ClinicalRiskDrilldownRecord, ...]
    subjects: tuple[ClinicalSubjectConsumerRecord, ...]
    site_rollups: tuple[ClinicalRollupProjection, ...]
    project_rollup: ClinicalRollupProjection
    limitations: tuple[str, ...] = ()
    handoff_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("project_id", "trial_id"):
            object.__setattr__(self, name, _required(getattr(self, name), f"handoff.{name}"))
        object.__setattr__(self, "scope_sha256", _sha256(self.scope_sha256, "handoff.scope_sha256"))
        self._require_collection(self.timeline, ClinicalConsumerTimelineRecord, "timeline")
        self._require_collection(self.safety_metrics, ClinicalSafetyMetric, "safety_metrics")
        self._require_collection(self.risk_drilldown, ClinicalRiskDrilldownRecord, "risk_drilldown")
        self._require_collection(self.subjects, ClinicalSubjectConsumerRecord, "subjects")
        self._require_collection(self.site_rollups, ClinicalRollupProjection, "site_rollups")
        if not isinstance(self.project_rollup, ClinicalRollupProjection):
            raise ClinicalConsumerHandoffError("project_rollup must be a C5 rollup")
        for item in self.timeline:
            if item.project_id != self.project_id or item.trial_id != self.trial_id:
                raise ClinicalConsumerHandoffError("timeline identity does not match handoff")
        for metric in self.safety_metrics:
            for point in metric.points:
                if point.event_id not in {item.event_id for item in self.timeline}:
                    raise ClinicalConsumerHandoffError("metric point is not in timeline")
        object.__setattr__(self, "limitations", _ids(self.limitations, "handoff.limitations") if self.limitations else ())
        object.__setattr__(self, "handoff_sha256", _digest(self._payload()))

    @staticmethod
    def _require_collection(value: Any, item_type: type[Any], field_name: str) -> None:
        if not isinstance(value, (list, tuple)) or any(not isinstance(item, item_type) for item in value):
            raise ClinicalConsumerHandoffError(f"{field_name} contains an invalid projection")

    def _payload(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "scope_sha256": self.scope_sha256,
            "timeline": [item.to_dict() for item in self.timeline],
            "safety_metrics": [item.to_dict() for item in self.safety_metrics],
            "risk_drilldown": [item.to_dict() for item in self.risk_drilldown],
            "subjects": [item.to_dict() for item in self.subjects],
            "site_rollups": [item.to_dict() for item in self.site_rollups],
            "project_rollup": self.project_rollup.to_dict(),
            "limitations": list(self.limitations),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "handoff_sha256": self.handoff_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalConsumerHandoff":
        if not isinstance(payload, Mapping):
            raise ClinicalConsumerHandoffError("handoff must be an object")
        handoff = cls(
            project_id=payload.get("project_id", ""),
            trial_id=payload.get("trial_id", ""),
            scope_sha256=payload.get("scope_sha256", ""),
            timeline=tuple(
                ClinicalConsumerTimelineRecord.from_dict(item)
                for item in _objects(payload.get("timeline", ()), "timeline")
            ),
            safety_metrics=tuple(
                ClinicalSafetyMetric.from_dict(item)
                for item in _objects(payload.get("safety_metrics", ()), "safety_metrics")
            ),
            risk_drilldown=tuple(
                ClinicalRiskDrilldownRecord.from_dict(item)
                for item in _objects(payload.get("risk_drilldown", ()), "risk_drilldown")
            ),
            subjects=tuple(
                ClinicalSubjectConsumerRecord.from_dict(item)
                for item in _objects(payload.get("subjects", ()), "subjects")
            ),
            site_rollups=tuple(
                ClinicalRollupProjection.from_dict(item)
                for item in _objects(payload.get("site_rollups", ()), "site_rollups")
            ),
            project_rollup=ClinicalRollupProjection.from_dict(payload.get("project_rollup", {})),
            limitations=payload.get("limitations", ()),
        )
        declared_hash = _sha256(payload.get("handoff_sha256"), "handoff.handoff_sha256")
        if declared_hash != handoff.handoff_sha256:
            raise ClinicalConsumerHandoffError("handoff_sha256 does not match canonical content")
        return handoff


def _timeline_record(item: ClinicalTimelineProjection) -> ClinicalConsumerTimelineRecord:
    return ClinicalConsumerTimelineRecord(
        event_id=item.event_id,
        event_sha256=item.event_sha256,
        project_id=item.project_id,
        trial_id=item.trial_id,
        site_id=item.site_id,
        subject_id=item.subject_id,
        event_type=_DOMAIN_TO_EVENT_TYPE[item.domain],
        source_domain=item.domain,
        title=item.visit_label or _DOMAIN_LABEL[item.domain],
        detail=_DOMAIN_LABEL[item.domain],
        event_date=item.event_date,
        date_precision=item.date_precision,
        raw_event_date=item.date_raw,
        visit_label=item.visit_label,
        visit_number=item.visit_number,
        is_unscheduled=item.visit_kind.value == "unplanned",
        related_risk_ids=item.risk_instance_ids,
        evidence_ids=item.evidence_ids,
        evidence_locators=item.evidence_locators,
        rule_binding_ids=item.rule_binding_ids,
        completeness_status=item.completeness_status,
        uncertainty_state=item.uncertainty_state,
    )


def _metric_point(
    observation: ClinicalObservationProjection,
    timeline_by_event: Mapping[str, ClinicalTimelineProjection],
) -> ClinicalSafetyMetricPoint:
    timeline = timeline_by_event.get(observation.event_id)
    if timeline is None or timeline.event_sha256 != observation.event_sha256:
        raise ClinicalConsumerHandoffError(
            f"observation event hash is not bound to timeline: {observation.observation_id}"
        )
    return ClinicalSafetyMetricPoint(
        point_id=observation.observation_id,
        event_id=observation.event_id,
        event_sha256=observation.event_sha256,
        subject_id=observation.subject_id,
        site_id=observation.site_id,
        domain=observation.domain,
        field_name=observation.field_name,
        assessment_date=timeline.event_date,
        date_precision=timeline.date_precision,
        visit_label=timeline.visit_label,
        visit_number=timeline.visit_number,
        value_status=observation.value_status,
        value=observation.raw_value,
        normalized_value=observation.normalized_value,
        unit=observation.unit,
        reference_range=observation.reference_range,
        related_risk_ids=observation.risk_instance_ids,
        evidence_ids=observation.evidence_ids,
        evidence_locators=observation.evidence_locators,
        rule_binding_ids=observation.rule_binding_ids,
        completeness_status=observation.completeness_status,
        uncertainty_state=observation.uncertainty_state,
    )


def build_clinical_consumer_handoff(model: MonitoringClinicalReadModel) -> ClinicalConsumerHandoff:
    """Build the read-only consumer records from one C5 model."""

    if not isinstance(model, MonitoringClinicalReadModel):
        raise ClinicalConsumerHandoffError("model must be a C5 clinical read model")
    timeline_by_event: dict[str, ClinicalTimelineProjection] = {}
    timeline_records: list[ClinicalConsumerTimelineRecord] = []
    for item in model.timeline:
        if not item.evidence_ids or not item.evidence_locators:
            raise ClinicalConsumerHandoffError(
                f"event lacks source traceability: {item.event_id}"
            )
        if item.event_id in timeline_by_event:
            raise ClinicalConsumerHandoffError(f"duplicate timeline event: {item.event_id}")
        timeline_by_event[item.event_id] = item
        timeline_records.append(_timeline_record(item))

    metric_points: dict[str, list[ClinicalSafetyMetricPoint]] = {}
    observation_ids: set[str] = set()
    for observation in model.observations:
        if observation.observation_id in observation_ids:
            raise ClinicalConsumerHandoffError(
                f"duplicate observation point: {observation.observation_id}"
            )
        if not observation.evidence_ids or not observation.evidence_locators:
            raise ClinicalConsumerHandoffError(
                f"observation lacks source traceability: {observation.observation_id}"
            )
        observation_ids.add(observation.observation_id)
        point = _metric_point(observation, timeline_by_event)
        key = f"{point.domain.value}:{point.field_name}"
        metric_points.setdefault(key, []).append(point)
    metrics = tuple(
        ClinicalSafetyMetric(
            metric_key=key,
            domain=points[0].domain,
            field_name=points[0].field_name,
            points=tuple(points),
        )
        for key, points in sorted(metric_points.items())
    )

    risk_events: dict[str, set[str]] = {}
    risk_observations: dict[str, set[str]] = {}
    risk_subjects: dict[str, set[str]] = {}
    risk_sites: dict[str, set[str]] = {}
    risk_evidence: dict[str, dict[str, str]] = {}
    risk_rules: dict[str, set[str]] = {}
    for item in timeline_records:
        for risk_id in item.related_risk_ids:
            risk_events.setdefault(risk_id, set()).add(item.event_id)
            risk_subjects.setdefault(risk_id, set()).add(item.subject_id)
            risk_sites.setdefault(risk_id, set()).add(item.site_id)
            evidence_by_id = risk_evidence.setdefault(risk_id, {})
            for evidence_id, locator in zip(item.evidence_ids, item.evidence_locators):
                previous_locator = evidence_by_id.setdefault(evidence_id, locator)
                if previous_locator != locator:
                    raise ClinicalConsumerHandoffError(
                        f"risk evidence locator conflict: {risk_id}/{evidence_id}"
                    )
            risk_rules.setdefault(risk_id, set()).update(item.rule_binding_ids)
    for metric in metrics:
        for point in metric.points:
            for risk_id in point.related_risk_ids:
                risk_events.setdefault(risk_id, set()).add(point.event_id)
                risk_observations.setdefault(risk_id, set()).add(point.point_id)
                risk_subjects.setdefault(risk_id, set()).add(point.subject_id)
                risk_sites.setdefault(risk_id, set()).add(point.site_id)
                evidence_by_id = risk_evidence.setdefault(risk_id, {})
                for evidence_id, locator in zip(point.evidence_ids, point.evidence_locators):
                    previous_locator = evidence_by_id.setdefault(evidence_id, locator)
                    if previous_locator != locator:
                        raise ClinicalConsumerHandoffError(
                            f"risk evidence locator conflict: {risk_id}/{evidence_id}"
                        )
                risk_rules.setdefault(risk_id, set()).update(point.rule_binding_ids)
    risk_drilldown = tuple(
        ClinicalRiskDrilldownRecord(
            risk_instance_id=risk_id,
            event_ids=tuple(sorted(risk_events[risk_id])),
            observation_ids=tuple(sorted(risk_observations.get(risk_id, set()))),
            subject_ids=tuple(sorted(risk_subjects[risk_id])),
            site_ids=tuple(sorted(risk_sites[risk_id])),
            evidence_ids=tuple(sorted(risk_evidence[risk_id])),
            evidence_locators=tuple(
                risk_evidence[risk_id][evidence_id]
                for evidence_id in sorted(risk_evidence[risk_id])
            ),
            rule_binding_ids=tuple(sorted(risk_rules[risk_id])),
        )
        for risk_id in sorted(risk_events)
    )

    metric_keys_by_subject: dict[str, set[str]] = {}
    for metric in metrics:
        for point in metric.points:
            metric_keys_by_subject.setdefault(point.subject_id, set()).add(metric.metric_key)
    subjects = tuple(
        ClinicalSubjectConsumerRecord(
            subject_id=profile.subject_id,
            site_id=profile.site_id,
            event_ids=profile.event_ids,
            observation_ids=profile.observation_ids,
            risk_instance_ids=profile.risk_instance_ids,
            timeline_event_ids=profile.event_ids,
            safety_metric_keys=tuple(sorted(metric_keys_by_subject.get(profile.subject_id, set()))),
        )
        for profile in model.subject_profiles
    )

    if tuple(sorted(item.event_id for item in timeline_records)) != model.project_rollup.event_ids:
        raise ClinicalConsumerHandoffError("handoff does not conserve project event ids")
    if tuple(sorted(item.subject_id for item in subjects)) != tuple(
        sorted(profile.subject_id for profile in model.subject_profiles)
    ):
        raise ClinicalConsumerHandoffError("handoff does not conserve subject ids")
    limitations = set(model.limitations)
    if not timeline_records:
        limitations.add("empty_consumer_timeline")
    return ClinicalConsumerHandoff(
        project_id=model.scope.project_id,
        trial_id=model.scope.trial_id,
        scope_sha256=model.scope.scope_sha256,
        timeline=tuple(timeline_records),
        safety_metrics=metrics,
        risk_drilldown=risk_drilldown,
        subjects=subjects,
        site_rollups=model.site_rollups,
        project_rollup=model.project_rollup,
        limitations=tuple(sorted(limitations)),
    )


__all__ = [
    "ClinicalConsumerHandoff",
    "ClinicalConsumerHandoffError",
    "ClinicalConsumerTimelineRecord",
    "ClinicalRiskDrilldownRecord",
    "ClinicalSafetyMetric",
    "ClinicalSafetyMetricPoint",
    "ClinicalSubjectConsumerRecord",
    "build_clinical_consumer_handoff",
]
