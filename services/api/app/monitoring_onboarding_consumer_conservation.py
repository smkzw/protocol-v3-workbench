"""Read-only conservation across onboarding and frontend consumer contracts.

This contract joins the C8 review-only coverage, C9 schema-only fixture and C10
field-presence reports. It exposes the frontend surface vocabulary without
turning placeholders into clinical records or active mappings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from .monitoring_adapter_consumer_coverage import (
    ConsumerCoverageSurface,
    StudyAdapterConsumerCoverageError,
    StudyAdapterConsumerCoveragePlan,
)
from .monitoring_source_fixture_diff import (
    SourceFixtureDiffReport,
    SourceFixtureFieldPresence,
)
from .monitoring_source_fixture_validation import (
    SourceFixtureRecord,
    SourceFixtureValidationReport,
)


class OnboardingConsumerConservationError(StudyAdapterConsumerCoverageError):
    """Raised when C8/C9/C10 structural evidence cannot be conserved."""


_FRONTEND_CONSUMER_KEYS = {
    ConsumerCoverageSurface.TIMELINE.value: "timeline",
    ConsumerCoverageSurface.PROFILE.value: "subjects",
    ConsumerCoverageSurface.SAFETY_METRIC.value: "safety_metrics",
    ConsumerCoverageSurface.RISK_LINK.value: "risk_links",
}
_REQUIRED_SURFACES = frozenset(
    {
        ConsumerCoverageSurface.TIMELINE.value,
        ConsumerCoverageSurface.PROFILE.value,
        ConsumerCoverageSurface.RISK_LINK.value,
    }
)
_FIXTURE_VALUE_STATUSES = frozenset({"present", "missing", "not_applicable", "unknown"})
_SURFACE_ORDER = {
    ConsumerCoverageSurface.TIMELINE.value: 0,
    ConsumerCoverageSurface.PROFILE.value: 1,
    ConsumerCoverageSurface.SAFETY_METRIC.value: 2,
    ConsumerCoverageSurface.RISK_LINK.value: 3,
}


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise OnboardingConsumerConservationError("conservation payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise OnboardingConsumerConservationError(f"{field_name} is required")
    return text


def _ordered_unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(_required(value, f"{field_name} item") for value in values)
    if len(result) != len(set(result)):
        raise OnboardingConsumerConservationError(f"{field_name} must not repeat")
    return result


@dataclass(frozen=True)
class OnboardingConsumerConservationRow:
    """One mapping's source identity and structural consumer conservation."""

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
    record_id: str
    fixture_status: str
    diff_status: str
    consumer_surfaces: tuple[str, ...]
    frontend_consumer_keys: tuple[str, ...]
    required_event_fields: tuple[str, ...]
    required_observation_fields: tuple[str, ...]
    risk_link_policy: str
    present_fields: tuple[str, ...]
    not_assessable_fields: tuple[str, ...]
    schema_only: bool = True
    activation_allowed: bool = False
    readiness: str = "structural_only"
    status: str = "schema_only_cross_surface_unassessed"

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
            "record_id",
            "fixture_status",
            "diff_status",
            "risk_link_policy",
            "readiness",
            "status",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"conservation.{name}"))
        if not self.schema_only or self.activation_allowed:
            raise OnboardingConsumerConservationError("conservation row must remain schema_only and inactive")
        if self.readiness != "structural_only":
            raise OnboardingConsumerConservationError("conservation row cannot claim clinical readiness")
        if self.status != "schema_only_cross_surface_unassessed":
            raise OnboardingConsumerConservationError("conservation row status is not schema-only")
        surfaces = _ordered_unique(self.consumer_surfaces, "conservation.consumer_surfaces")
        unknown = set(surfaces) - set(_FRONTEND_CONSUMER_KEYS)
        if unknown:
            raise OnboardingConsumerConservationError(f"unknown frontend consumer surface: {sorted(unknown)}")
        if not _REQUIRED_SURFACES.issubset(surfaces):
            raise OnboardingConsumerConservationError("conservation row must retain Timeline/Profile/risk-link surfaces")
        ordered_surfaces = tuple(sorted(surfaces, key=_SURFACE_ORDER.__getitem__))
        expected_keys = tuple(_FRONTEND_CONSUMER_KEYS[surface] for surface in ordered_surfaces)
        keys = _ordered_unique(self.frontend_consumer_keys, "conservation.frontend_consumer_keys")
        if keys != expected_keys:
            raise OnboardingConsumerConservationError("frontend consumer keys do not match surfaces")
        event_fields = _ordered_unique(self.required_event_fields, "conservation.required_event_fields")
        observation_fields = _ordered_unique(
            self.required_observation_fields,
            "conservation.required_observation_fields",
        )
        present_fields = _ordered_unique(self.present_fields, "conservation.present_fields")
        not_assessable = _ordered_unique(self.not_assessable_fields, "conservation.not_assessable_fields")
        if set(present_fields) & set(not_assessable):
            raise OnboardingConsumerConservationError("a field cannot be present and not assessable")
        if self.risk_link_policy != "explicit_risk_instance_id_only":
            raise OnboardingConsumerConservationError("risk link policy must remain explicit-id-only")
        if self.fixture_status not in _FIXTURE_VALUE_STATUSES or self.diff_status != "schema_only_unassessed":
            raise OnboardingConsumerConservationError("schema-only conservation statuses are over-claimed")
        object.__setattr__(self, "consumer_surfaces", ordered_surfaces)
        object.__setattr__(self, "frontend_consumer_keys", keys)
        object.__setattr__(self, "required_event_fields", event_fields)
        object.__setattr__(self, "required_observation_fields", observation_fields)
        object.__setattr__(self, "present_fields", tuple(sorted(present_fields)))
        object.__setattr__(self, "not_assessable_fields", tuple(sorted(not_assessable)))

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
            "record_id": self.record_id,
            "fixture_status": self.fixture_status,
            "diff_status": self.diff_status,
            "consumer_surfaces": list(self.consumer_surfaces),
            "frontend_consumer_keys": list(self.frontend_consumer_keys),
            "required_event_fields": list(self.required_event_fields),
            "required_observation_fields": list(self.required_observation_fields),
            "risk_link_policy": self.risk_link_policy,
            "present_fields": list(self.present_fields),
            "not_assessable_fields": list(self.not_assessable_fields),
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
            "readiness": self.readiness,
            "status": self.status,
        }


@dataclass(frozen=True)
class OnboardingConsumerConservationReport:
    """Deterministic cross-surface structural evidence for one adapter."""

    adapter_key: str
    project_id: str
    trial_id: str
    coverage_sha256: str
    fixture_report_sha256: str
    diff_report_sha256: str
    expected_mapping_ids: tuple[str, ...]
    rows: tuple[OnboardingConsumerConservationRow, ...]
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
            "fixture_report_sha256",
            "diff_report_sha256",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"conservation_report.{name}"))
        if not self.schema_only or self.activation_allowed:
            raise OnboardingConsumerConservationError("conservation report must remain schema_only and inactive")
        expected = _ordered_unique(self.expected_mapping_ids, "conservation_report.expected_mapping_ids")
        missing = _ordered_unique(self.missing_mapping_ids, "conservation_report.missing_mapping_ids")
        rows = tuple(self.rows)
        if any(not isinstance(row, OnboardingConsumerConservationRow) for row in rows):
            raise OnboardingConsumerConservationError("conservation rows have an invalid type")
        row_ids = tuple(row.mapping_id for row in rows)
        if len(row_ids) != len(set(row_ids)):
            raise OnboardingConsumerConservationError("conservation rows must not repeat mapping IDs")
        if set(row_ids) | set(missing) != set(expected) or set(row_ids) & set(missing):
            raise OnboardingConsumerConservationError("conservation mapping IDs do not conserve the expected set")
        if any(
            row.adapter_key != self.adapter_key
            or row.project_id != self.project_id
            or row.trial_id != self.trial_id
            for row in rows
        ):
            raise OnboardingConsumerConservationError("conservation row identity does not match report")
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
            "fixture_report_sha256": self.fixture_report_sha256,
            "diff_report_sha256": self.diff_report_sha256,
            "expected_mapping_ids": list(self.expected_mapping_ids),
            "missing_mapping_ids": list(self.missing_mapping_ids),
            "rows": [row.to_dict() for row in self.rows],
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def _assert_identity(
    coverage: Any,
    record: SourceFixtureRecord,
    diff_row: SourceFixtureFieldPresence,
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
        if getattr(coverage, field_name) != getattr(record, field_name):
            raise OnboardingConsumerConservationError(f"fixture identity drift: {field_name}")
        if getattr(coverage, field_name) != getattr(diff_row, field_name):
            raise OnboardingConsumerConservationError(f"diff identity drift: {field_name}")
    if diff_row.source_revision != record.source_revision:
        raise OnboardingConsumerConservationError("source revision drift between C9 and C10")
    if diff_row.record_id != record.record_id:
        raise OnboardingConsumerConservationError("record ID drift between C9 and C10")
    if diff_row.value_status != record.value_status.value:
        raise OnboardingConsumerConservationError("value status drift between C9 and C10")
    if not record.schema_only or record.activation_allowed or not diff_row.schema_only or diff_row.activation_allowed:
        raise OnboardingConsumerConservationError("source evidence is not schema-only and inactive")


def build_onboarding_consumer_conservation_report(
    coverage_plan: StudyAdapterConsumerCoveragePlan,
    fixture_report: SourceFixtureValidationReport,
    diff_report: SourceFixtureDiffReport,
) -> OnboardingConsumerConservationReport:
    """Conserve C8/C9/C10 identity and C7 consumer surface vocabulary."""

    if not isinstance(coverage_plan, StudyAdapterConsumerCoveragePlan):
        raise OnboardingConsumerConservationError("coverage_plan must be a C8 coverage plan")
    if not isinstance(fixture_report, SourceFixtureValidationReport):
        raise OnboardingConsumerConservationError("fixture_report must be a C9 validation report")
    if not isinstance(diff_report, SourceFixtureDiffReport):
        raise OnboardingConsumerConservationError("diff_report must be a C10 diff report")
    if coverage_plan.activation_allowed or not fixture_report.schema_only or fixture_report.activation_allowed:
        raise OnboardingConsumerConservationError("onboarding evidence cannot activate a mapping")
    if fixture_report.coverage_sha256 != coverage_plan.coverage_sha256:
        raise OnboardingConsumerConservationError("C9 coverage hash does not match C8")
    if diff_report.coverage_sha256 != coverage_plan.coverage_sha256:
        raise OnboardingConsumerConservationError("C10 coverage hash does not match C8")
    if diff_report.fixture_report_sha256 != fixture_report.report_sha256:
        raise OnboardingConsumerConservationError("C10 fixture hash does not match C9")
    if (
        fixture_report.adapter_key != coverage_plan.adapter_key
        or fixture_report.project_id != coverage_plan.project_id
        or fixture_report.trial_id != coverage_plan.trial_id
    ):
        raise OnboardingConsumerConservationError("C9 report identity does not match C8")
    expected = {item.mapping_id: item for item in coverage_plan.observations}
    records = {record.mapping_id: record for record in fixture_report.records}
    diff_rows = {row.mapping_id: row for row in diff_report.rows}
    unknown_records = set(records) - set(expected)
    unknown_rows = set(diff_rows) - set(expected)
    if unknown_records or unknown_rows:
        raise OnboardingConsumerConservationError(
            f"C9/C10 contain unknown mappings: records={sorted(unknown_records)}, rows={sorted(unknown_rows)}"
        )
    if set(diff_report.expected_mapping_ids) != set(expected):
        raise OnboardingConsumerConservationError("C10 expected mapping IDs do not match C8")
    rows: list[OnboardingConsumerConservationRow] = []
    for mapping_id in sorted(set(records) & set(diff_rows)):
        coverage = expected[mapping_id]
        record = records[mapping_id]
        diff_row = diff_rows[mapping_id]
        _assert_identity(coverage, record, diff_row)
        surfaces = tuple(item.value for item in coverage.consumer_surfaces)
        rows.append(
            OnboardingConsumerConservationRow(
                mapping_id=mapping_id,
                adapter_key=coverage.adapter_key,
                project_id=coverage.project_id,
                trial_id=coverage.trial_id,
                domain=coverage.domain.value,
                observed_domain=coverage.observed_domain,
                source_sheet=coverage.source_sheet,
                source_field=coverage.source_field,
                evidence_locator=coverage.evidence_locator,
                source_revision=record.source_revision,
                record_id=record.record_id,
                fixture_status=record.value_status.value,
                diff_status=diff_row.status,
                consumer_surfaces=surfaces,
                frontend_consumer_keys=tuple(_FRONTEND_CONSUMER_KEYS[surface] for surface in surfaces),
                required_event_fields=coverage.required_event_fields,
                required_observation_fields=coverage.required_observation_fields,
                risk_link_policy=coverage.risk_link_policy,
                present_fields=diff_row.present_fields,
                not_assessable_fields=diff_row.not_assessable_fields,
            )
        )
    missing = set(expected) - {row.mapping_id for row in rows}
    if set(fixture_report.missing_mapping_ids) != missing or set(diff_report.missing_mapping_ids) != missing:
        raise OnboardingConsumerConservationError("C8/C9/C10 missing mapping sets do not conserve")
    return OnboardingConsumerConservationReport(
        adapter_key=coverage_plan.adapter_key,
        project_id=coverage_plan.project_id,
        trial_id=coverage_plan.trial_id,
        coverage_sha256=coverage_plan.coverage_sha256,
        fixture_report_sha256=fixture_report.report_sha256,
        diff_report_sha256=diff_report.report_sha256,
        expected_mapping_ids=tuple(expected),
        rows=tuple(rows),
        missing_mapping_ids=tuple(sorted(missing)),
    )


__all__ = [
    "OnboardingConsumerConservationError",
    "OnboardingConsumerConservationReport",
    "OnboardingConsumerConservationRow",
    "build_onboarding_consumer_conservation_report",
]
