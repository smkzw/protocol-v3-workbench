"""Offline consumer-coverage matrix for review-only adapter observations.

The matrix describes how an observed source surface could feed the shared C4-C7
contracts. It is not an active mapping, source parser, medical adjudication or
runtime registry. Every risk surface remains an explicit-risk-ID link only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from .monitoring_adapter_mapping_plan import (
    REVIEW_ONLY_STATUS,
    StudyAdapterMappingObservation,
    StudyAdapterMappingPlan,
    StudyAdapterMappingPlanError,
)
from .monitoring_clinical_event_contract import ClinicalDomain


class StudyAdapterConsumerCoverageError(StudyAdapterMappingPlanError):
    """Raised when review-only coverage would be ambiguous or over-claiming."""


class ConsumerCoverageSurface(str, Enum):
    TIMELINE = "timeline"
    PROFILE = "profile"
    SAFETY_METRIC = "safety_metric"
    RISK_LINK = "risk_link"


_DOMAIN_BY_SOURCE = {
    "VISIT": ClinicalDomain.VISIT,
    "AE": ClinicalDomain.AE,
    "MH": ClinicalDomain.MH,
    "CM": ClinicalDomain.CM,
    "IP": ClinicalDomain.IP,
    "LAB": ClinicalDomain.LAB,
    "LB": ClinicalDomain.LAB,
    "VITALS": ClinicalDomain.VITALS,
    "VS": ClinicalDomain.VITALS,
    "ECG": ClinicalDomain.ECG,
    "EFFICACY": ClinicalDomain.EFFICACY,
    "QS": ClinicalDomain.EFFICACY,
    "FINDING": ClinicalDomain.FINDING,
    "PD": ClinicalDomain.PD,
    "OTHER": ClinicalDomain.OTHER,
    # These observed labels are deliberately normalized to OTHER; the original
    # label remains on the coverage record so it cannot be mistaken for IP/CM.
    "BACKGROUND_TREATMENT": ClinicalDomain.OTHER,
    "SOURCE": ClinicalDomain.OTHER,
}
_SAFETY_DOMAINS = frozenset(
    {ClinicalDomain.AE, ClinicalDomain.LAB, ClinicalDomain.VITALS, ClinicalDomain.ECG}
)
_SURFACE_ORDER = {
    ConsumerCoverageSurface.TIMELINE: 0,
    ConsumerCoverageSurface.PROFILE: 1,
    ConsumerCoverageSurface.SAFETY_METRIC: 2,
    ConsumerCoverageSurface.RISK_LINK: 3,
}
_EVENT_FIELDS = (
    "project_id",
    "trial_id",
    "site_id",
    "subject_id",
    "event_id",
    "event_date",
    "date_precision",
    "date_raw",
    "visit",
    "evidence",
    "completeness",
    "uncertainty",
)
_OBSERVATION_FIELDS = (
    "observation_id",
    "event_id",
    "field_name",
    "value_status",
    "raw_value",
    "normalized_value_if_present",
    "unit",
    "reference_range",
    "evidence",
    "rule_bindings",
    "completeness",
    "uncertainty",
)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise StudyAdapterConsumerCoverageError("coverage payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise StudyAdapterConsumerCoverageError(f"{field_name} is required")
    return text


def _source_domain(observation: StudyAdapterMappingObservation) -> ClinicalDomain:
    source = observation.domain.strip().upper()
    try:
        return _DOMAIN_BY_SOURCE[source]
    except KeyError as exc:
        raise StudyAdapterConsumerCoverageError(
            f"unsupported observed domain for consumer coverage: {observation.domain}"
        ) from exc


def _surfaces(domain: ClinicalDomain) -> tuple[ConsumerCoverageSurface, ...]:
    surfaces = [
        ConsumerCoverageSurface.TIMELINE,
        ConsumerCoverageSurface.PROFILE,
        ConsumerCoverageSurface.RISK_LINK,
    ]
    if domain in _SAFETY_DOMAINS:
        surfaces.insert(2, ConsumerCoverageSurface.SAFETY_METRIC)
    return tuple(sorted(surfaces, key=_SURFACE_ORDER.__getitem__))


@dataclass(frozen=True)
class StudyAdapterConsumerCoverage:
    mapping_id: str
    adapter_key: str
    project_id: str
    trial_id: str
    domain: ClinicalDomain
    source_sheet: str
    source_field: str
    capability_id: str
    observation_kind: str
    evidence_locator: str
    recommended_role: str
    consumer_surfaces: tuple[ConsumerCoverageSurface, ...]
    required_event_fields: tuple[str, ...] = _EVENT_FIELDS
    required_observation_fields: tuple[str, ...] = _OBSERVATION_FIELDS
    risk_link_policy: str = "explicit_risk_instance_id_only"
    review_status: str = REVIEW_ONLY_STATUS
    observed_domain: str = ""

    def __post_init__(self) -> None:
        for name in (
            "mapping_id",
            "adapter_key",
            "project_id",
            "trial_id",
            "source_sheet",
            "source_field",
            "capability_id",
            "observation_kind",
            "evidence_locator",
            "recommended_role",
            "risk_link_policy",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"coverage.{name}"))
        if not isinstance(self.domain, ClinicalDomain):
            try:
                object.__setattr__(self, "domain", ClinicalDomain(self.domain))
            except (TypeError, ValueError) as exc:
                raise StudyAdapterConsumerCoverageError("coverage.domain is invalid") from exc
        if self.risk_link_policy != "explicit_risk_instance_id_only":
            raise StudyAdapterConsumerCoverageError("risk link policy must remain explicit-id-only")
        if self.review_status != REVIEW_ONLY_STATUS:
            raise StudyAdapterConsumerCoverageError("consumer coverage must remain review-only")
        observed_domain = self.observed_domain.strip() or self.domain.value.upper()
        object.__setattr__(self, "observed_domain", _required(observed_domain, "coverage.observed_domain"))
        surfaces = tuple(self.consumer_surfaces)
        if not surfaces or any(not isinstance(item, ConsumerCoverageSurface) for item in surfaces):
            raise StudyAdapterConsumerCoverageError("coverage surfaces are invalid")
        if len(set(surfaces)) != len(surfaces):
            raise StudyAdapterConsumerCoverageError("coverage surfaces must not repeat")
        if ConsumerCoverageSurface.TIMELINE not in surfaces:
            raise StudyAdapterConsumerCoverageError("every observed surface must retain Timeline coverage")
        if ConsumerCoverageSurface.SAFETY_METRIC in surfaces and self.domain not in _SAFETY_DOMAINS:
            raise StudyAdapterConsumerCoverageError("non-safety domain cannot claim safety metric coverage")
        expected = _surfaces(self.domain)
        if surfaces != expected:
            raise StudyAdapterConsumerCoverageError("coverage surfaces do not match explicit domain policy")
        event_fields = tuple(_required(value, "coverage.required_event_fields item") for value in self.required_event_fields)
        observation_fields = tuple(
            _required(value, "coverage.required_observation_fields item")
            for value in self.required_observation_fields
        )
        if len(set(event_fields)) != len(event_fields) or len(set(observation_fields)) != len(observation_fields):
            raise StudyAdapterConsumerCoverageError("required coverage fields must not repeat")
        object.__setattr__(self, "required_event_fields", event_fields)
        object.__setattr__(self, "required_observation_fields", observation_fields)
        object.__setattr__(self, "consumer_surfaces", surfaces)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "domain": self.domain.value,
            "observed_domain": self.observed_domain,
            "source_sheet": self.source_sheet,
            "source_field": self.source_field,
            "capability_id": self.capability_id,
            "observation_kind": self.observation_kind,
            "evidence_locator": self.evidence_locator,
            "recommended_role": self.recommended_role,
            "consumer_surfaces": [item.value for item in self.consumer_surfaces],
            "required_event_fields": list(self.required_event_fields),
            "required_observation_fields": list(self.required_observation_fields),
            "risk_link_policy": self.risk_link_policy,
            "review_status": self.review_status,
        }


@dataclass(frozen=True)
class StudyAdapterConsumerCoveragePlan:
    adapter_key: str
    project_id: str
    trial_id: str
    inventory_revision: str
    mapping_plan_sha256: str
    observations: tuple[StudyAdapterConsumerCoverage, ...]
    activation_allowed: bool = False
    coverage_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "adapter_key",
            "project_id",
            "trial_id",
            "inventory_revision",
            "mapping_plan_sha256",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"coverage_plan.{name}"))
        if self.activation_allowed:
            raise StudyAdapterConsumerCoverageError("coverage plan cannot activate a mapping")
        observations = tuple(self.observations)
        if not observations or any(not isinstance(item, StudyAdapterConsumerCoverage) for item in observations):
            raise StudyAdapterConsumerCoverageError("coverage plan must contain coverage observations")
        if any(
            item.adapter_key != self.adapter_key
            or item.project_id != self.project_id
            or item.trial_id != self.trial_id
            for item in observations
        ):
            raise StudyAdapterConsumerCoverageError("coverage identity does not match plan")
        mapping_ids = [item.mapping_id for item in observations]
        if len(mapping_ids) != len(set(mapping_ids)):
            raise StudyAdapterConsumerCoverageError("coverage mapping IDs must be unique")
        ordered = tuple(sorted(observations, key=lambda item: item.mapping_id))
        object.__setattr__(self, "observations", ordered)
        object.__setattr__(self, "coverage_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "inventory_revision": self.inventory_revision,
            "mapping_plan_sha256": self.mapping_plan_sha256,
            "activation_allowed": self.activation_allowed,
            "observations": [item.to_dict() for item in self.observations],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "coverage_sha256": self.coverage_sha256}


def build_consumer_coverage_plan(
    mapping_plan: StudyAdapterMappingPlan,
) -> StudyAdapterConsumerCoveragePlan:
    """Describe C3 observations at C4-C7 consumer boundaries, without activation."""

    if not isinstance(mapping_plan, StudyAdapterMappingPlan):
        raise StudyAdapterConsumerCoverageError("mapping_plan must be a C3 review-only plan")
    observations = tuple(
        StudyAdapterConsumerCoverage(
            mapping_id=item.mapping_id,
            adapter_key=item.adapter_key,
            project_id=item.project_id,
            trial_id=mapping_plan.trial_id,
            domain=_source_domain(item),
            source_sheet=item.source_sheet,
            source_field=item.source_field,
            capability_id=item.capability_id,
            observation_kind=item.observation_kind,
            evidence_locator=item.evidence_locator,
            recommended_role=item.recommended_role,
            consumer_surfaces=_surfaces(_source_domain(item)),
            review_status=item.review_status,
            observed_domain=item.domain.strip().upper(),
        )
        for item in mapping_plan.observations
    )
    return StudyAdapterConsumerCoveragePlan(
        adapter_key=mapping_plan.adapter_key,
        project_id=mapping_plan.project_id,
        trial_id=mapping_plan.trial_id,
        inventory_revision=mapping_plan.inventory_revision,
        mapping_plan_sha256=mapping_plan.plan_sha256,
        observations=observations,
    )


__all__ = [
    "ConsumerCoverageSurface",
    "StudyAdapterConsumerCoverage",
    "StudyAdapterConsumerCoverageError",
    "StudyAdapterConsumerCoveragePlan",
    "build_consumer_coverage_plan",
]
