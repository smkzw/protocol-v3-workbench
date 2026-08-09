"""Fail-closed fallback and retirement policy for source-specific adapters.

The policy is a read-only diagnostic contract. It allows only limited or
unavailable states until real source, medical approval and runtime acceptance
gates are satisfied; it never substitutes clinical data or activates a mapping.
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
from .monitoring_onboarding_consumer_conservation import (
    OnboardingConsumerConservationReport,
    OnboardingConsumerConservationRow,
)


class AdapterFallbackContractError(StudyAdapterConsumerCoverageError):
    """Raised when a fallback policy would over-claim or enable a mapping."""


class AdapterFallbackState(str, Enum):
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"


_FALLBACK_STATES = (AdapterFallbackState.LIMITED.value, AdapterFallbackState.UNAVAILABLE.value)
_TRIGGER_REASONS = frozenset(
    {
        "adapter_unavailable",
        "source_revision_drift",
        "mapping_review_pending",
        "consumer_contract_incomplete",
        "risk_authority_pending",
    }
)
_RETIREMENT_CONDITIONS = (
    "real_source_revision_verified",
    "source_mapping_medically_approved",
    "required_fields_complete_and_evidence_bound",
    "c4_c6_consumer_contract_passed",
    "risk_authority_review_outcome_approved",
    "representative_browser_and_runtime_acceptance",
)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise AdapterFallbackContractError("fallback payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise AdapterFallbackContractError(f"{field_name} is required")
    return text


def _unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(_required(value, f"{field_name} item") for value in values)
    if len(result) != len(set(result)):
        raise AdapterFallbackContractError(f"{field_name} must not repeat")
    return result


@dataclass(frozen=True)
class AdapterFallbackPolicy:
    """One mapping's inactive, metadata-only fallback policy."""

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
    diagnostic_surface_keys: tuple[str, ...]
    fallback_states: tuple[str, ...] = _FALLBACK_STATES
    default_state: str = AdapterFallbackState.UNAVAILABLE.value
    trigger_reasons: tuple[str, ...] = (
        "adapter_unavailable",
        "source_revision_drift",
        "mapping_review_pending",
        "consumer_contract_incomplete",
        "risk_authority_pending",
    )
    payload_policy: str = "metadata_only_no_clinical_records"
    risk_action: str = "blocked"
    retirement_conditions: tuple[str, ...] = _RETIREMENT_CONDITIONS
    retirement_status: str = "not_retired"
    schema_only: bool = True
    activation_allowed: bool = False
    status: str = "fallback_policy_only"

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
            "default_state",
            "payload_policy",
            "risk_action",
            "retirement_status",
            "status",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"fallback.{name}"))
        if not self.schema_only or self.activation_allowed:
            raise AdapterFallbackContractError("fallback policy must remain schema_only and inactive")
        if self.status != "fallback_policy_only":
            raise AdapterFallbackContractError("fallback policy cannot claim runtime readiness")
        if self.retirement_status != "not_retired":
            raise AdapterFallbackContractError("fallback policy cannot claim retirement")
        states = _unique(self.fallback_states, "fallback.fallback_states")
        if states != _FALLBACK_STATES:
            raise AdapterFallbackContractError("fallback states must be limited and unavailable only")
        if self.default_state not in states:
            raise AdapterFallbackContractError("fallback default state is not allowed")
        reasons = _unique(self.trigger_reasons, "fallback.trigger_reasons")
        if set(reasons) != _TRIGGER_REASONS:
            raise AdapterFallbackContractError("fallback trigger reasons are incomplete or unsupported")
        conditions = _unique(self.retirement_conditions, "fallback.retirement_conditions")
        if conditions != _RETIREMENT_CONDITIONS:
            raise AdapterFallbackContractError("fallback retirement conditions are incomplete or reordered")
        surfaces = _unique(self.diagnostic_surface_keys, "fallback.diagnostic_surface_keys")
        if not surfaces:
            raise AdapterFallbackContractError("fallback must retain diagnostic surface identity")
        if self.payload_policy != "metadata_only_no_clinical_records":
            raise AdapterFallbackContractError("fallback cannot expose clinical records")
        if self.risk_action != "blocked":
            raise AdapterFallbackContractError("fallback must block risk actions")
        object.__setattr__(self, "fallback_states", states)
        object.__setattr__(self, "trigger_reasons", reasons)
        object.__setattr__(self, "retirement_conditions", conditions)
        object.__setattr__(self, "diagnostic_surface_keys", surfaces)

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
            "diagnostic_surface_keys": list(self.diagnostic_surface_keys),
            "fallback_states": list(self.fallback_states),
            "default_state": self.default_state,
            "trigger_reasons": list(self.trigger_reasons),
            "payload_policy": self.payload_policy,
            "risk_action": self.risk_action,
            "retirement_conditions": list(self.retirement_conditions),
            "retirement_status": self.retirement_status,
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
            "status": self.status,
        }


@dataclass(frozen=True)
class AdapterFallbackPolicyReport:
    """Deterministic inactive policy matrix for one adapter."""

    adapter_key: str
    project_id: str
    trial_id: str
    coverage_sha256: str
    conservation_report_sha256: str
    expected_mapping_ids: tuple[str, ...]
    policies: tuple[AdapterFallbackPolicy, ...]
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
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"fallback_report.{name}"))
        if not self.schema_only or self.activation_allowed:
            raise AdapterFallbackContractError("fallback report must remain schema_only and inactive")
        expected = _unique(self.expected_mapping_ids, "fallback_report.expected_mapping_ids")
        missing = _unique(self.missing_mapping_ids, "fallback_report.missing_mapping_ids")
        policies = tuple(self.policies)
        if any(not isinstance(policy, AdapterFallbackPolicy) for policy in policies):
            raise AdapterFallbackContractError("fallback report policies have an invalid type")
        policy_ids = tuple(policy.mapping_id for policy in policies)
        if len(policy_ids) != len(set(policy_ids)):
            raise AdapterFallbackContractError("fallback policies must not repeat mapping IDs")
        if set(policy_ids) | set(missing) != set(expected) or set(policy_ids) & set(missing):
            raise AdapterFallbackContractError("fallback mapping IDs do not conserve the expected set")
        if any(
            policy.adapter_key != self.adapter_key
            or policy.project_id != self.project_id
            or policy.trial_id != self.trial_id
            for policy in policies
        ):
            raise AdapterFallbackContractError("fallback policy identity does not match report")
        object.__setattr__(self, "expected_mapping_ids", tuple(sorted(expected)))
        object.__setattr__(self, "missing_mapping_ids", tuple(sorted(missing)))
        object.__setattr__(self, "policies", tuple(sorted(policies, key=lambda policy: policy.mapping_id)))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "coverage_sha256": self.coverage_sha256,
            "conservation_report_sha256": self.conservation_report_sha256,
            "expected_mapping_ids": list(self.expected_mapping_ids),
            "missing_mapping_ids": list(self.missing_mapping_ids),
            "policies": [policy.to_dict() for policy in self.policies],
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def _assert_identity(
    coverage: Any,
    row: OnboardingConsumerConservationRow,
) -> None:
    for field_name in (
        "mapping_id",
        "adapter_key",
        "project_id",
        "trial_id",
        "source_sheet",
        "source_field",
        "evidence_locator",
    ):
        if getattr(coverage, field_name) != getattr(row, field_name):
            raise AdapterFallbackContractError(f"fallback identity drift: {field_name}")
    if row.readiness != "structural_only" or row.status != "schema_only_cross_surface_unassessed":
        raise AdapterFallbackContractError("C11 row is not structural-only")
    if not row.schema_only or row.activation_allowed:
        raise AdapterFallbackContractError("C11 row is active or non-schema-only")


def build_adapter_fallback_policy_report(
    coverage_plan: StudyAdapterConsumerCoveragePlan,
    conservation_report: OnboardingConsumerConservationReport,
) -> AdapterFallbackPolicyReport:
    """Build limited/unavailable policies without activating or substituting data."""

    if not isinstance(coverage_plan, StudyAdapterConsumerCoveragePlan):
        raise AdapterFallbackContractError("coverage_plan must be a C8 coverage plan")
    if not isinstance(conservation_report, OnboardingConsumerConservationReport):
        raise AdapterFallbackContractError("conservation_report must be a C11 report")
    if coverage_plan.activation_allowed or not conservation_report.schema_only or conservation_report.activation_allowed:
        raise AdapterFallbackContractError("fallback input cannot activate a mapping")
    if conservation_report.coverage_sha256 != coverage_plan.coverage_sha256:
        raise AdapterFallbackContractError("C11 coverage hash does not match C8")
    if (
        conservation_report.adapter_key != coverage_plan.adapter_key
        or conservation_report.project_id != coverage_plan.project_id
        or conservation_report.trial_id != coverage_plan.trial_id
    ):
        raise AdapterFallbackContractError("C11 identity does not match C8")
    coverage_by_id = {item.mapping_id: item for item in coverage_plan.observations}
    rows_by_id = {row.mapping_id: row for row in conservation_report.rows}
    unknown = set(rows_by_id) - set(coverage_by_id)
    if unknown:
        raise AdapterFallbackContractError(f"C11 contains unknown mappings: {sorted(unknown)}")
    if set(conservation_report.expected_mapping_ids) != set(coverage_by_id):
        raise AdapterFallbackContractError("C11 expected mapping IDs do not match C8")
    policies: list[AdapterFallbackPolicy] = []
    for mapping_id in sorted(rows_by_id):
        coverage = coverage_by_id[mapping_id]
        row = rows_by_id[mapping_id]
        _assert_identity(coverage, row)
        if row.risk_link_policy != "explicit_risk_instance_id_only":
            raise AdapterFallbackContractError("fallback risk policy is not explicit-id-only")
        policies.append(
            AdapterFallbackPolicy(
                mapping_id=mapping_id,
                adapter_key=row.adapter_key,
                project_id=row.project_id,
                trial_id=row.trial_id,
                domain=row.domain,
                observed_domain=row.observed_domain,
                source_sheet=row.source_sheet,
                source_field=row.source_field,
                evidence_locator=row.evidence_locator,
                source_revision=row.source_revision,
                diagnostic_surface_keys=row.frontend_consumer_keys,
            )
        )
    missing = set(conservation_report.missing_mapping_ids)
    return AdapterFallbackPolicyReport(
        adapter_key=coverage_plan.adapter_key,
        project_id=coverage_plan.project_id,
        trial_id=coverage_plan.trial_id,
        coverage_sha256=coverage_plan.coverage_sha256,
        conservation_report_sha256=conservation_report.report_sha256,
        expected_mapping_ids=tuple(coverage_by_id),
        policies=tuple(policies),
        missing_mapping_ids=tuple(sorted(missing)),
    )


__all__ = [
    "AdapterFallbackContractError",
    "AdapterFallbackPolicy",
    "AdapterFallbackPolicyReport",
    "AdapterFallbackState",
    "build_adapter_fallback_policy_report",
]
