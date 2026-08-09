"""Read-only activation-to-projection boundary for approved future mappings.

The contract describes the route from a future medically approved mapping to
the shared C4 event and C5/C6 consumer surfaces. Current review-only inputs are
always blocked; this module creates no event, projection, persistence or active
mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from .monitoring_adapter_consumer_coverage import (
    StudyAdapterConsumerCoverageError,
    StudyAdapterConsumerCoveragePlan,
)
from .monitoring_adapter_fallback_contract import (
    AdapterFallbackPolicyReport,
)
from .monitoring_onboarding_consumer_conservation import (
    OnboardingConsumerConservationReport,
    OnboardingConsumerConservationRow,
)


class ActivationProjectionContractError(StudyAdapterConsumerCoverageError):
    """Raised when a future activation route over-claims readiness."""


class ActivationProjectionStatus(str, Enum):
    BLOCKED_PENDING_APPROVAL = "blocked_pending_approval"


_BLOCKERS = (
    "mapping_review_pending",
    "source_fixture_schema_only",
    "fallback_not_retired",
    "risk_authority_pending",
    "runtime_acceptance_pending",
)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ActivationProjectionContractError("activation payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ActivationProjectionContractError(f"{field_name} is required")
    return text


def _unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(_required(value, f"{field_name} item") for value in values)
    if len(result) != len(set(result)):
        raise ActivationProjectionContractError(f"{field_name} must not repeat")
    return result


@dataclass(frozen=True)
class ActivationProjectionRow:
    """One inactive mapping's future event/projection route."""

    mapping_id: str
    adapter_key: str
    project_id: str
    trial_id: str
    domain: str
    observed_domain: str
    source_sheet: str
    source_field: str
    evidence_locator: str
    source_revision: str
    event_contract: str
    projection_contract: str
    consumer_surface_keys: tuple[str, ...]
    required_event_fields: tuple[str, ...]
    required_observation_fields: tuple[str, ...]
    safety_metric_surface: bool
    fallback_default_state: str
    fallback_retirement_status: str
    blockers: tuple[str, ...] = _BLOCKERS
    status: str = ActivationProjectionStatus.BLOCKED_PENDING_APPROVAL.value
    event_creation_allowed: bool = False
    projection_allowed: bool = False
    activation_allowed: bool = False
    schema_only: bool = True

    def __post_init__(self) -> None:
        for name in (
            "mapping_id",
            "adapter_key",
            "project_id",
            "trial_id",
            "domain",
            "observed_domain",
            "source_sheet",
            "source_field",
            "evidence_locator",
            "source_revision",
            "event_contract",
            "projection_contract",
            "fallback_default_state",
            "fallback_retirement_status",
            "status",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"activation.{name}"))
        if self.event_contract != "MonitoringClinicalEvent/MonitoringClinicalObservation":
            raise ActivationProjectionContractError("activation event contract is not the shared C4 contract")
        if self.projection_contract != "MonitoringClinicalReadModel/ClinicalConsumerHandoff":
            raise ActivationProjectionContractError("activation projection contract is not the shared C5/C6 contract")
        if self.status != ActivationProjectionStatus.BLOCKED_PENDING_APPROVAL.value:
            raise ActivationProjectionContractError("activation row cannot claim readiness")
        if self.event_creation_allowed or self.projection_allowed or self.activation_allowed or not self.schema_only:
            raise ActivationProjectionContractError("activation route must remain blocked and schema-only")
        if self.fallback_default_state != "unavailable" or self.fallback_retirement_status != "not_retired":
            raise ActivationProjectionContractError("activation route requires an unretired unavailable fallback")
        surfaces = _unique(self.consumer_surface_keys, "activation.consumer_surface_keys")
        if "timeline" not in surfaces or "subjects" not in surfaces or "risk_links" not in surfaces:
            raise ActivationProjectionContractError("activation route must conserve Timeline/Profile/risk-link surfaces")
        blockers = _unique(self.blockers, "activation.blockers")
        if blockers != _BLOCKERS:
            raise ActivationProjectionContractError("activation blockers are incomplete or reordered")
        event_fields = _unique(self.required_event_fields, "activation.required_event_fields")
        observation_fields = _unique(self.required_observation_fields, "activation.required_observation_fields")
        object.__setattr__(self, "consumer_surface_keys", surfaces)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "required_event_fields", event_fields)
        object.__setattr__(self, "required_observation_fields", observation_fields)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "domain": self.domain,
            "observed_domain": self.observed_domain,
            "source_sheet": self.source_sheet,
            "source_field": self.source_field,
            "evidence_locator": self.evidence_locator,
            "source_revision": self.source_revision,
            "event_contract": self.event_contract,
            "projection_contract": self.projection_contract,
            "consumer_surface_keys": list(self.consumer_surface_keys),
            "required_event_fields": list(self.required_event_fields),
            "required_observation_fields": list(self.required_observation_fields),
            "safety_metric_surface": self.safety_metric_surface,
            "fallback_default_state": self.fallback_default_state,
            "fallback_retirement_status": self.fallback_retirement_status,
            "blockers": list(self.blockers),
            "status": self.status,
            "event_creation_allowed": self.event_creation_allowed,
            "projection_allowed": self.projection_allowed,
            "activation_allowed": self.activation_allowed,
            "schema_only": self.schema_only,
        }


@dataclass(frozen=True)
class ActivationProjectionReport:
    """Deterministic blocked activation map for one adapter."""

    adapter_key: str
    project_id: str
    trial_id: str
    coverage_sha256: str
    conservation_report_sha256: str
    fallback_report_sha256: str
    expected_mapping_ids: tuple[str, ...]
    rows: tuple[ActivationProjectionRow, ...]
    missing_mapping_ids: tuple[str, ...] = ()
    schema_only: bool = True
    activation_allowed: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "adapter_key",
            "project_id",
            "trial_id",
            "coverage_sha256",
            "conservation_report_sha256",
            "fallback_report_sha256",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"activation_report.{name}"))
        if not self.schema_only or self.activation_allowed:
            raise ActivationProjectionContractError("activation report must remain schema-only and inactive")
        expected = _unique(self.expected_mapping_ids, "activation_report.expected_mapping_ids")
        missing = _unique(self.missing_mapping_ids, "activation_report.missing_mapping_ids")
        rows = tuple(self.rows)
        if any(not isinstance(row, ActivationProjectionRow) for row in rows):
            raise ActivationProjectionContractError("activation rows have an invalid type")
        row_ids = tuple(row.mapping_id for row in rows)
        if len(row_ids) != len(set(row_ids)):
            raise ActivationProjectionContractError("activation rows must not repeat mapping IDs")
        if set(row_ids) | set(missing) != set(expected) or set(row_ids) & set(missing):
            raise ActivationProjectionContractError("activation mapping IDs do not conserve the expected set")
        if any(
            row.adapter_key != self.adapter_key
            or row.project_id != self.project_id
            or row.trial_id != self.trial_id
            for row in rows
        ):
            raise ActivationProjectionContractError("activation row identity does not match report")
        object.__setattr__(self, "expected_mapping_ids", tuple(sorted(expected)))
        object.__setattr__(self, "missing_mapping_ids", tuple(sorted(missing)))
        object.__setattr__(self, "rows", tuple(sorted(rows, key=lambda row: row.mapping_id)))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "coverage_sha256": self.coverage_sha256,
            "conservation_report_sha256": self.conservation_report_sha256,
            "fallback_report_sha256": self.fallback_report_sha256,
            "expected_mapping_ids": list(self.expected_mapping_ids),
            "missing_mapping_ids": list(self.missing_mapping_ids),
            "rows": [row.to_dict() for row in self.rows],
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def _assert_identity(coverage: Any, conservation_row: OnboardingConsumerConservationRow, fallback_policy: Any) -> None:
    for field_name in (
        "mapping_id",
        "adapter_key",
        "project_id",
        "trial_id",
        "source_sheet",
        "source_field",
        "evidence_locator",
    ):
        if getattr(coverage, field_name) != getattr(conservation_row, field_name):
            raise ActivationProjectionContractError(f"activation conservation identity drift: {field_name}")
        if getattr(coverage, field_name) != getattr(fallback_policy, field_name):
            raise ActivationProjectionContractError(f"activation fallback identity drift: {field_name}")
    if conservation_row.source_revision != fallback_policy.source_revision:
        raise ActivationProjectionContractError("activation source revision drift")
    if not conservation_row.schema_only or conservation_row.activation_allowed:
        raise ActivationProjectionContractError("activation input is active or non-schema-only")


def build_activation_projection_report(
    coverage_plan: StudyAdapterConsumerCoveragePlan,
    conservation_report: OnboardingConsumerConservationReport,
    fallback_report: AdapterFallbackPolicyReport,
) -> ActivationProjectionReport:
    """Describe a blocked future activation route without creating events."""

    if not isinstance(coverage_plan, StudyAdapterConsumerCoveragePlan):
        raise ActivationProjectionContractError("coverage_plan must be a C8 coverage plan")
    if not isinstance(conservation_report, OnboardingConsumerConservationReport):
        raise ActivationProjectionContractError("conservation_report must be a C11 report")
    if not isinstance(fallback_report, AdapterFallbackPolicyReport):
        raise ActivationProjectionContractError("fallback_report must be a C12 report")
    if coverage_plan.activation_allowed or not conservation_report.schema_only or not fallback_report.schema_only:
        raise ActivationProjectionContractError("activation inputs must remain inactive and schema-only")
    if conservation_report.coverage_sha256 != coverage_plan.coverage_sha256:
        raise ActivationProjectionContractError("C11 coverage hash does not match C8")
    if fallback_report.coverage_sha256 != coverage_plan.coverage_sha256:
        raise ActivationProjectionContractError("C12 coverage hash does not match C8")
    if fallback_report.conservation_report_sha256 != conservation_report.report_sha256:
        raise ActivationProjectionContractError("C12 conservation hash does not match C11")
    if (
        conservation_report.adapter_key != coverage_plan.adapter_key
        or fallback_report.adapter_key != coverage_plan.adapter_key
        or conservation_report.project_id != coverage_plan.project_id
        or fallback_report.project_id != coverage_plan.project_id
        or conservation_report.trial_id != coverage_plan.trial_id
        or fallback_report.trial_id != coverage_plan.trial_id
    ):
        raise ActivationProjectionContractError("activation input identity does not match C8")
    coverage_by_id = {item.mapping_id: item for item in coverage_plan.observations}
    conservation_by_id = {row.mapping_id: row for row in conservation_report.rows}
    fallback_by_id = {policy.mapping_id: policy for policy in fallback_report.policies}
    if set(conservation_by_id) != set(fallback_by_id):
        raise ActivationProjectionContractError("C11/C12 rows do not conserve activated candidates")
    if set(conservation_report.expected_mapping_ids) != set(coverage_by_id):
        raise ActivationProjectionContractError("activation expected mapping IDs do not match C8")
    rows: list[ActivationProjectionRow] = []
    for mapping_id in sorted(conservation_by_id):
        coverage = coverage_by_id[mapping_id]
        conservation_row = conservation_by_id[mapping_id]
        fallback_policy = fallback_by_id[mapping_id]
        _assert_identity(coverage, conservation_row, fallback_policy)
        if fallback_policy.default_state != "unavailable" or fallback_policy.retirement_status != "not_retired":
            raise ActivationProjectionContractError("activation route cannot bypass fallback retirement")
        if fallback_policy.risk_action != "blocked":
            raise ActivationProjectionContractError("activation route cannot unblock risk actions")
        rows.append(
            ActivationProjectionRow(
                mapping_id=mapping_id,
                adapter_key=coverage.adapter_key,
                project_id=coverage.project_id,
                trial_id=coverage.trial_id,
                domain=coverage.domain.value,
                observed_domain=coverage.observed_domain,
                source_sheet=coverage.source_sheet,
                source_field=coverage.source_field,
                evidence_locator=coverage.evidence_locator,
                source_revision=conservation_row.source_revision,
                event_contract="MonitoringClinicalEvent/MonitoringClinicalObservation",
                projection_contract="MonitoringClinicalReadModel/ClinicalConsumerHandoff",
                consumer_surface_keys=conservation_row.frontend_consumer_keys,
                required_event_fields=conservation_row.required_event_fields,
                required_observation_fields=conservation_row.required_observation_fields,
                safety_metric_surface="safety_metrics" in conservation_row.frontend_consumer_keys,
                fallback_default_state=fallback_policy.default_state,
                fallback_retirement_status=fallback_policy.retirement_status,
            )
        )
    missing = set(conservation_report.missing_mapping_ids)
    if set(fallback_report.missing_mapping_ids) != missing:
        raise ActivationProjectionContractError("C11/C12 missing mapping sets do not conserve")
    return ActivationProjectionReport(
        adapter_key=coverage_plan.adapter_key,
        project_id=coverage_plan.project_id,
        trial_id=coverage_plan.trial_id,
        coverage_sha256=coverage_plan.coverage_sha256,
        conservation_report_sha256=conservation_report.report_sha256,
        fallback_report_sha256=fallback_report.report_sha256,
        expected_mapping_ids=tuple(coverage_by_id),
        rows=tuple(rows),
        missing_mapping_ids=tuple(sorted(missing)),
    )


__all__ = [
    "ActivationProjectionContractError",
    "ActivationProjectionReport",
    "ActivationProjectionRow",
    "ActivationProjectionStatus",
    "build_activation_projection_report",
]
