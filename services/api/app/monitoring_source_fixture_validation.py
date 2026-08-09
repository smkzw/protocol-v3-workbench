"""Source-bound schema-only fixture validation for the C8 coverage matrix.

This boundary validates identity and traceability without parsing a listing or
creating a clinical event. It is suitable for deterministic contract fixtures,
not for real-project ingestion or mapping activation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable

from .monitoring_adapter_consumer_coverage import (
    StudyAdapterConsumerCoveragePlan,
    StudyAdapterConsumerCoverageError,
)


class SourceFixtureValidationError(StudyAdapterConsumerCoverageError):
    """Raised when a schema-only source fixture breaks C8 traceability."""


class SourceFixtureValueStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class SourceFixtureDatePrecision(str, Enum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\])")
_PATH_SEGMENT_RE = re.compile(r"(?:^|[/\\])(?:\.|\.\.)(?:[/\\]|$)")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_YEAR_RE = re.compile(r"^\d{4}$")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _required(value: Any, field_name: str) -> str:
    text = _text(value)
    if not text:
        raise SourceFixtureValidationError(f"{field_name} is required")
    return text


def _identifier(value: Any, field_name: str) -> str:
    text = _required(value, field_name)
    if not _SAFE_ID_RE.fullmatch(text):
        raise SourceFixtureValidationError(f"{field_name} contains unsupported characters")
    return text


def _source_text(value: Any, field_name: str) -> str:
    text = _required(value, field_name)
    if _ABSOLUTE_PATH_RE.match(text) or _PATH_SEGMENT_RE.search(text):
        raise SourceFixtureValidationError(f"{field_name} must not be a local path")
    return text


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SourceFixtureValidationError("fixture payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _date_value(raw: str, precision: SourceFixtureDatePrecision, field_name: str) -> str:
    if not raw:
        if precision not in (SourceFixtureDatePrecision.UNKNOWN,):
            raise SourceFixtureValidationError(f"{field_name} is required for declared precision")
        return ""
    if precision is SourceFixtureDatePrecision.DAY:
        if not _DAY_RE.fullmatch(raw):
            raise SourceFixtureValidationError(f"{field_name} does not match day precision")
        try:
            date.fromisoformat(raw)
        except ValueError as exc:
            raise SourceFixtureValidationError(f"{field_name} is not a real calendar date") from exc
    elif precision is SourceFixtureDatePrecision.MONTH:
        if not _MONTH_RE.fullmatch(raw):
            raise SourceFixtureValidationError(f"{field_name} does not match month precision")
        year, month = (int(part) for part in raw.split("-"))
        if not 1 <= month <= 12 or year < 1:
            raise SourceFixtureValidationError(f"{field_name} is not a valid month")
    elif precision is SourceFixtureDatePrecision.YEAR:
        if not _YEAR_RE.fullmatch(raw) or int(raw) < 1:
            raise SourceFixtureValidationError(f"{field_name} does not match year precision")
    else:
        raise SourceFixtureValidationError(f"{field_name} has unknown precision but a raw date")
    return raw


@dataclass(frozen=True)
class SourceFixtureRecord:
    mapping_id: str
    adapter_key: str
    project_id: str
    trial_id: str
    source_revision: str
    source_sheet: str
    source_field: str
    evidence_locator: str
    record_id: str
    subject_id: str = ""
    site_id: str = ""
    value_status: SourceFixtureValueStatus = SourceFixtureValueStatus.UNKNOWN
    raw_value: Any = None
    date_raw: str = ""
    date_precision: SourceFixtureDatePrecision = SourceFixtureDatePrecision.UNKNOWN
    visit_label: str = ""
    schema_only: bool = True
    activation_allowed: bool = False
    normalized_value: Any = None

    def __post_init__(self) -> None:
        for name in (
            "mapping_id",
            "adapter_key",
            "project_id",
            "trial_id",
            "source_revision",
            "record_id",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), f"fixture.{name}"))
        for name in ("source_sheet", "source_field", "evidence_locator"):
            object.__setattr__(self, name, _source_text(getattr(self, name), f"fixture.{name}"))
        for name in ("subject_id", "site_id"):
            value = _text(getattr(self, name))
            object.__setattr__(self, name, _identifier(value, f"fixture.{name}") if value else "")
        if not isinstance(self.value_status, SourceFixtureValueStatus):
            try:
                object.__setattr__(self, "value_status", SourceFixtureValueStatus(self.value_status))
            except (TypeError, ValueError) as exc:
                raise SourceFixtureValidationError("fixture.value_status is invalid") from exc
        if not isinstance(self.date_precision, SourceFixtureDatePrecision):
            try:
                object.__setattr__(self, "date_precision", SourceFixtureDatePrecision(self.date_precision))
            except (TypeError, ValueError) as exc:
                raise SourceFixtureValidationError("fixture.date_precision is invalid") from exc
        object.__setattr__(self, "date_raw", _text(self.date_raw))
        object.__setattr__(self, "date_raw", _date_value(self.date_raw, self.date_precision, "fixture.date_raw"))
        object.__setattr__(self, "visit_label", _text(self.visit_label))
        if not self.schema_only:
            raise SourceFixtureValidationError("source fixture must remain schema_only")
        if self.activation_allowed:
            raise SourceFixtureValidationError("source fixture cannot activate a mapping")
        if self.normalized_value is not None:
            raise SourceFixtureValidationError(
                "source fixture cannot invent or normalize a clinical value"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_id": self.mapping_id,
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "source_revision": self.source_revision,
            "source_sheet": self.source_sheet,
            "source_field": self.source_field,
            "evidence_locator": self.evidence_locator,
            "record_id": self.record_id,
            "subject_id": self.subject_id,
            "site_id": self.site_id,
            "value_status": self.value_status.value,
            "raw_value": self.raw_value,
            "date_raw": self.date_raw,
            "date_precision": self.date_precision.value,
            "visit_label": self.visit_label,
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
        }


@dataclass(frozen=True)
class SourceFixtureValidationReport:
    adapter_key: str
    project_id: str
    trial_id: str
    coverage_sha256: str
    schema_only: bool
    activation_allowed: bool
    expected_mapping_ids: tuple[str, ...]
    observed_mapping_ids: tuple[str, ...]
    missing_mapping_ids: tuple[str, ...]
    records: tuple[SourceFixtureRecord, ...]
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_key", _identifier(self.adapter_key, "report.adapter_key"))
        object.__setattr__(self, "project_id", _identifier(self.project_id, "report.project_id"))
        object.__setattr__(self, "trial_id", _identifier(self.trial_id, "report.trial_id"))
        object.__setattr__(self, "coverage_sha256", _identifier(self.coverage_sha256, "report.coverage_sha256"))
        if not self.schema_only or self.activation_allowed:
            raise SourceFixtureValidationError("validation report must remain schema_only and inactive")
        for name in ("expected_mapping_ids", "observed_mapping_ids", "missing_mapping_ids"):
            values = tuple(_identifier(value, f"report.{name} item") for value in getattr(self, name))
            if len(values) != len(set(values)):
                raise SourceFixtureValidationError(f"report.{name} must not contain duplicates")
            object.__setattr__(self, name, tuple(sorted(values)))
        records = tuple(self.records)
        if any(not isinstance(record, SourceFixtureRecord) for record in records):
            raise SourceFixtureValidationError("report.records must contain source fixture records")
        object.__setattr__(self, "records", tuple(sorted(records, key=lambda record: record.mapping_id)))
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "adapter_key": self.adapter_key,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "coverage_sha256": self.coverage_sha256,
            "schema_only": self.schema_only,
            "activation_allowed": self.activation_allowed,
            "expected_mapping_ids": list(self.expected_mapping_ids),
            "observed_mapping_ids": list(self.observed_mapping_ids),
            "missing_mapping_ids": list(self.missing_mapping_ids),
            "records": [record.to_dict() for record in self.records],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def build_schema_only_fixture_manifest(
    coverage_plan: StudyAdapterConsumerCoveragePlan,
    *,
    source_revision: str = "schema-only-fixture-v1",
) -> tuple[SourceFixtureRecord, ...]:
    """Create non-clinical placeholders for structural coverage only."""

    if not isinstance(coverage_plan, StudyAdapterConsumerCoveragePlan):
        raise SourceFixtureValidationError("coverage_plan must be a C8 coverage plan")
    revision = _identifier(source_revision, "source_revision")
    return tuple(
        SourceFixtureRecord(
            mapping_id=item.mapping_id,
            adapter_key=item.adapter_key,
            project_id=item.project_id,
            trial_id=item.trial_id,
            source_revision=revision,
            source_sheet=item.source_sheet,
            source_field=item.source_field,
            evidence_locator=item.evidence_locator,
            record_id=f"fixture:{item.mapping_id}:schema",
        )
        for item in coverage_plan.observations
    )


def validate_source_fixture_records(
    coverage_plan: StudyAdapterConsumerCoveragePlan,
    records: Iterable[SourceFixtureRecord],
    *,
    require_complete: bool = True,
) -> SourceFixtureValidationReport:
    """Validate source identity and coverage without producing a clinical event."""

    if not isinstance(coverage_plan, StudyAdapterConsumerCoveragePlan):
        raise SourceFixtureValidationError("coverage_plan must be a C8 coverage plan")
    if coverage_plan.activation_allowed:
        raise SourceFixtureValidationError("coverage plan is not allowed to activate mapping")
    expected = {item.mapping_id: item for item in coverage_plan.observations}
    records = tuple(records)
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, SourceFixtureRecord):
            raise SourceFixtureValidationError("records must contain source fixture records")
        if record.mapping_id in seen:
            raise SourceFixtureValidationError(f"duplicate fixture mapping: {record.mapping_id}")
        seen.add(record.mapping_id)
        coverage = expected.get(record.mapping_id)
        if coverage is None:
            raise SourceFixtureValidationError(f"fixture mapping is not in C8 coverage: {record.mapping_id}")
        for name in ("adapter_key", "project_id", "trial_id"):
            if getattr(record, name) != getattr(coverage, name):
                raise SourceFixtureValidationError(f"fixture {name} mismatch: {record.mapping_id}")
        for name in ("source_sheet", "source_field", "evidence_locator"):
            if getattr(record, name) != getattr(coverage, name):
                raise SourceFixtureValidationError(f"fixture {name} mismatch: {record.mapping_id}")
    observed = tuple(sorted(seen))
    missing = tuple(sorted(set(expected) - seen))
    if require_complete and missing:
        raise SourceFixtureValidationError(f"fixture coverage is incomplete: {len(missing)} mappings missing")
    return SourceFixtureValidationReport(
        adapter_key=coverage_plan.adapter_key,
        project_id=coverage_plan.project_id,
        trial_id=coverage_plan.trial_id,
        coverage_sha256=coverage_plan.coverage_sha256,
        schema_only=True,
        activation_allowed=False,
        expected_mapping_ids=tuple(expected),
        observed_mapping_ids=observed,
        missing_mapping_ids=missing,
        records=records,
    )


__all__ = [
    "SourceFixtureDatePrecision",
    "SourceFixtureRecord",
    "SourceFixtureValidationError",
    "SourceFixtureValidationReport",
    "SourceFixtureValueStatus",
    "build_schema_only_fixture_manifest",
    "validate_source_fixture_records",
]
