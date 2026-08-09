"""Field-presence report for schema-only source fixtures.

The report makes missing clinical fields visible without treating placeholders as
clinical data. It consumes C8 coverage and C9 validation output only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any

from .monitoring_adapter_consumer_coverage import (
    StudyAdapterConsumerCoveragePlan,
    StudyAdapterConsumerCoverageError,
)
from .monitoring_source_fixture_validation import (
    SourceFixtureRecord,
    SourceFixtureValidationReport,
)


class SourceFixtureDiffError(StudyAdapterConsumerCoverageError):
    """Raised when field-presence evidence is inconsistent or over-claims."""


_SOURCE_FIELDS = frozenset(
    {
        "mapping_id",
        "adapter_key",
        "project_id",
        "trial_id",
        "source_revision",
        "source_sheet",
        "source_field",
        "evidence_locator",
        "record_id",
        "subject_id",
        "site_id",
        "value_status",
        "raw_value",
        "date_raw",
        "date_precision",
        "visit_label",
        "schema_only",
        "activation_allowed",
    }
)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SourceFixtureDiffError("field-presence payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise SourceFixtureDiffError(f"{field_name} is required")
    return text


@dataclass(frozen=True)
class SourceFixtureFieldPresence:
    mapping_id: str
    adapter_key: str
    project_id: str
    trial_id: str
    source_sheet: str
    source_field: str
    evidence_locator: str
    source_revision: str
    record_id: str
    schema_only: bool
    activation_allowed: bool
    value_status: str
    present_fields: tuple[str, ...]
    not_assessable_fields: tuple[str, ...]
    status: str = "schema_only_unassessed"

    def __post_init__(self) -> None:
        for name in (
            "mapping_id",
            "adapter_key",
            "project_id",
            "trial_id",
            "source_sheet",
            "source_field",
            "evidence_locator",
            "source_revision",
            "record_id",
            "value_status",
            "status",
        ):
            object.__setattr__(self, name, _required(getattr(self, name), f"presence.{name}"))
        if not self.schema_only or self.activation_allowed:
            raise SourceFixtureDiffError("field presence must remain schema_only and inactive")
        if self.status != "schema_only_unassessed":
            raise SourceFixtureDiffError("schema-only placeholder cannot be marked complete")
        present = tuple(_required(value, "presence.present_fields item") for value in self.present_fields)
        unassessed = tuple(_required(value, "presence.not_assessable_fields item") for value in self.not_assessable_fields)
        if len(set(present)) != len(present) or len(set(unassessed)) != len(unassessed):
            raise SourceFixtureDiffError("presence fields must not repeat")
        if any(value not in _SOURCE_FIELDS and value not in {
            "event_id",
            "observation_id",
            "event_date",
            "date_precision",
            "visit",
            "evidence",
            "completeness",
            "uncertainty",
            "field_name",
            "value_status",
            "normalized_value_if_present",
            "unit",
            "reference_range",
            "rule_bindings",
        } for value in (*present, *unassessed)):
            raise SourceFixtureDiffError("presence contains an unknown field")
        if set(present) & set(unassessed):
            raise SourceFixtureDiffError("field cannot be both present and not assessable")
        object.__setattr__(self, "present_fields", tuple(sorted(present)))
        object.__setattr__(self, "not_assessable_fields", tuple(sorted(unassessed)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "source_sheet": self.source_sheet,
            "source_field": self.source_field,
            "evidence_locator": self.evidence_locator,
            "source_revision": self.source_revision,
            "record_id": self.record_id,
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
            "value_status": self.value_status,
            "status": self.status,
            "present_fields": list(self.present_fields),
            "not_assessable_fields": list(self.not_assessable_fields),
        }


@dataclass(frozen=True)
class SourceFixtureDiffReport:
    coverage_sha256: str
    fixture_report_sha256: str
    schema_only: bool
    activation_allowed: bool
    expected_mapping_ids: tuple[str, ...]
    rows: tuple[SourceFixtureFieldPresence, ...]
    missing_mapping_ids: tuple[str, ...] = ()
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("coverage_sha256", "fixture_report_sha256"):
            object.__setattr__(self, name, _required(getattr(self, name), f"diff.{name}"))
        if not self.schema_only or self.activation_allowed:
            raise SourceFixtureDiffError("diff report must remain schema_only and inactive")
        expected = tuple(sorted(_required(value, "diff.expected_mapping_ids item") for value in self.expected_mapping_ids))
        missing = tuple(sorted(_required(value, "diff.missing_mapping_ids item") for value in self.missing_mapping_ids))
        rows = tuple(self.rows)
        if any(not isinstance(row, SourceFixtureFieldPresence) for row in rows):
            raise SourceFixtureDiffError("diff.rows must contain field-presence records")
        row_ids = tuple(sorted(row.mapping_id for row in rows))
        if len(row_ids) != len(set(row_ids)):
            raise SourceFixtureDiffError("diff rows must not repeat mapping IDs")
        if set(row_ids) | set(missing) != set(expected) or set(row_ids) & set(missing):
            raise SourceFixtureDiffError("diff rows do not conserve expected mapping IDs")
        object.__setattr__(self, "expected_mapping_ids", expected)
        object.__setattr__(self, "missing_mapping_ids", missing)
        object.__setattr__(self, "rows", tuple(sorted(rows, key=lambda row: row.mapping_id)))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "coverage_sha256": self.coverage_sha256,
            "fixture_report_sha256": self.fixture_report_sha256,
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
            "expected_mapping_ids": list(self.expected_mapping_ids),
            "missing_mapping_ids": list(self.missing_mapping_ids),
            "rows": [row.to_dict() for row in self.rows],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def _presence_for(
    coverage: Any,
    record: SourceFixtureRecord,
) -> SourceFixtureFieldPresence:
    if record.mapping_id != coverage.mapping_id:
        raise SourceFixtureDiffError(f"fixture mapping mismatch: {record.mapping_id}")
    present = {
        "mapping_id",
        "adapter_key",
        "project_id",
        "trial_id",
        "source_revision",
        "source_sheet",
        "source_field",
        "evidence_locator",
        "record_id",
        "value_status",
        "date_precision",
        "schema_only",
        "activation_allowed",
    }
    if record.subject_id:
        present.add("subject_id")
    if record.site_id:
        present.add("site_id")
    if record.raw_value is not None:
        present.add("raw_value")
    if record.date_raw:
        present.add("date_raw")
    if record.visit_label:
        present.add("visit_label")
    required = set(coverage.required_event_fields) | set(coverage.required_observation_fields)
    not_assessable = required - present
    return SourceFixtureFieldPresence(
        mapping_id=record.mapping_id,
        adapter_key=record.adapter_key,
        project_id=record.project_id,
        trial_id=record.trial_id,
        source_sheet=record.source_sheet,
        source_field=record.source_field,
        evidence_locator=record.evidence_locator,
        source_revision=record.source_revision,
        record_id=record.record_id,
        schema_only=record.schema_only,
        activation_allowed=record.activation_allowed,
        value_status=record.value_status.value,
        present_fields=tuple(present),
        not_assessable_fields=tuple(not_assessable),
    )


def build_source_fixture_diff_report(
    coverage_plan: StudyAdapterConsumerCoveragePlan,
    fixture_report: SourceFixtureValidationReport,
) -> SourceFixtureDiffReport:
    """Build a truthful field-presence report over C8/C9 evidence."""

    if not isinstance(coverage_plan, StudyAdapterConsumerCoveragePlan):
        raise SourceFixtureDiffError("coverage_plan must be a C8 coverage plan")
    if not isinstance(fixture_report, SourceFixtureValidationReport):
        raise SourceFixtureDiffError("fixture_report must be a C9 validation report")
    if fixture_report.coverage_sha256 != coverage_plan.coverage_sha256:
        raise SourceFixtureDiffError("coverage hash does not match fixture report")
    coverage_by_id = {item.mapping_id: item for item in coverage_plan.observations}
    records_by_id = {record.mapping_id: record for record in fixture_report.records}
    rows = tuple(
        _presence_for(coverage_by_id[mapping_id], records_by_id[mapping_id])
        for mapping_id in sorted(records_by_id)
        if mapping_id in coverage_by_id
    )
    unknown = set(records_by_id) - set(coverage_by_id)
    if unknown:
        raise SourceFixtureDiffError(f"fixture report contains unknown mappings: {sorted(unknown)}")
    return SourceFixtureDiffReport(
        coverage_sha256=coverage_plan.coverage_sha256,
        fixture_report_sha256=fixture_report.report_sha256,
        schema_only=True,
        activation_allowed=False,
        expected_mapping_ids=tuple(coverage_by_id),
        rows=rows,
        missing_mapping_ids=fixture_report.missing_mapping_ids,
    )


__all__ = [
    "SourceFixtureDiffError",
    "SourceFixtureDiffReport",
    "SourceFixtureFieldPresence",
    "build_source_fixture_diff_report",
]
