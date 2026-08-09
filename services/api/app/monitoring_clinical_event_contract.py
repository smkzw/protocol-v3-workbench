"""Shared, project-neutral clinical event/observation contract.

The contract is the future common input for Timeline, Patient Profile, AE/lab/
vitals/ECG review and risk projections.  It is deliberately a pure value model:
it does not parse source files, infer links from text, adjudicate medicine or
persist an event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from datetime import date
from typing import Any, Mapping


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_ABSOLUTE_PATH_RE = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\])")
_PATH_SEGMENT_RE = re.compile(r"(?:^|[/\\])(?:\.|\.\.)(?:[/\\]|$)")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
_YEAR_RE = re.compile(r"^\d{4}$")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class ClinicalEventContractError(ValueError):
    """Raised when a shared event/observation payload is unsafe or ambiguous."""


class ClinicalDomain(str, Enum):
    VISIT = "visit"
    AE = "ae"
    MH = "mh"
    CM = "cm"
    IP = "ip"
    LAB = "lab"
    VITALS = "vitals"
    ECG = "ecg"
    EFFICACY = "efficacy"
    FINDING = "finding"
    PD = "pd"
    OTHER = "other"


class ClinicalEventKind(str, Enum):
    EVENT = "event"
    OBSERVATION = "observation"
    RISK_ANCHOR = "risk_anchor"


class ClinicalDatePrecision(str, Enum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"
    UNKNOWN = "unknown"


class ClinicalValueStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class ClinicalCompletenessStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING_REQUIRED = "missing_required"


class ClinicalUncertaintyState(str, Enum):
    NONE = "none"
    PARTIAL_DATE = "partial_date"
    UNMAPPED = "unmapped"
    SOURCE_CONFLICT = "source_conflict"
    MEDICAL_REVIEW_REQUIRED = "medical_review_required"


def _required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ClinicalEventContractError(f"{field} is required")
    return text


def _text(value: Any) -> str:
    """Normalize optional text without treating numeric zero as missing."""
    return "" if value is None else str(value).strip()


def _identifier(value: Any, field: str) -> str:
    text = _required(value, field)
    if not _SAFE_ID_RE.fullmatch(text):
        raise ClinicalEventContractError(f"{field} contains unsupported characters")
    return text


def _opaque(value: Any, field: str) -> str:
    text = _required(value, field)
    if _ABSOLUTE_PATH_RE.match(text) or _PATH_SEGMENT_RE.search(text):
        raise ClinicalEventContractError(f"{field} must not be a local path")
    return text


def _ids(values: Any, field: str) -> tuple[str, ...]:
    if values is None:
        values = ()
    if not isinstance(values, (list, tuple)):
        raise ClinicalEventContractError(f"{field} must be a list")
    result = tuple(_identifier(value, f"{field} item") for value in values)
    if len(result) != len(set(result)):
        raise ClinicalEventContractError(f"{field} must not contain duplicates")
    return tuple(sorted(result))


def _mapping(value: Any, field: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ClinicalEventContractError(f"{field} must be an object")
    try:
        # Round-trip through JSON so a frozen contract cannot retain a caller's
        # mutable nested list/dict and silently change its hash later.
        normalized = json.loads(
            json.dumps(value, ensure_ascii=False, sort_keys=True)
        )
    except (TypeError, ValueError) as exc:
        raise ClinicalEventContractError(f"{field} must be JSON-serializable") from exc
    if not isinstance(normalized, dict):
        raise ClinicalEventContractError(f"{field} must be an object")
    return normalized


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ClinicalEventContractError("payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _declared_sha256(value: Any, field: str) -> str:
    """Validate an optional serialized digest without normalizing it.

    Older payloads may omit the derived digest (or carry an explicit empty
    string), in which case the canonical value is recomputed.  A present
    non-empty declaration must already be an exact lowercase SHA-256 string;
    coercion, trimming and case folding would hide provenance damage.
    """
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ClinicalEventContractError(
            f"{field} must be a lowercase SHA-256 hex digest"
        )
    return value


def _enum(value: Any, enum_type: type[Enum], field: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ClinicalEventContractError(f"{field} is invalid") from exc


def _validate_date(value: str, precision: ClinicalDatePrecision) -> None:
    if precision == ClinicalDatePrecision.DAY:
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ClinicalEventContractError("event_date is not a valid calendar date") from exc
    elif precision == ClinicalDatePrecision.MONTH:
        month = int(value[-2:])
        if month < 1 or month > 12:
            raise ClinicalEventContractError("event_date month is invalid")


@dataclass(frozen=True)
class ClinicalCompleteness:
    status: ClinicalCompletenessStatus
    missing_fields: tuple[str, ...] = ()
    source_coverage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        state = _enum(self.status, ClinicalCompletenessStatus, "completeness.status")
        missing = _ids(self.missing_fields, "completeness.missing_fields")
        coverage = _ids(self.source_coverage, "completeness.source_coverage")
        if state == ClinicalCompletenessStatus.COMPLETE and missing:
            raise ClinicalEventContractError("complete record cannot declare missing_fields")
        if state == ClinicalCompletenessStatus.MISSING_REQUIRED and not missing:
            raise ClinicalEventContractError(
                "missing_required record must declare missing_fields"
            )
        object.__setattr__(self, "status", state)
        object.__setattr__(self, "missing_fields", missing)
        object.__setattr__(self, "source_coverage", coverage)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "missing_fields": list(self.missing_fields),
            "source_coverage": list(self.source_coverage),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ClinicalCompleteness":
        raw = {} if payload is None else payload
        if not isinstance(raw, Mapping):
            raise ClinicalEventContractError("completeness must be an object")
        return cls(
            status=raw.get("status", "complete"),
            missing_fields=raw.get("missing_fields", ()),
            source_coverage=raw.get("source_coverage", ()),
        )


@dataclass(frozen=True)
class ClinicalUncertainty:
    state: ClinicalUncertaintyState = ClinicalUncertaintyState.NONE
    codes: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        state = _enum(self.state, ClinicalUncertaintyState, "uncertainty.state")
        codes = _ids(self.codes, "uncertainty.codes")
        note = _text(self.note)
        if state == ClinicalUncertaintyState.NONE and (codes or note):
            raise ClinicalEventContractError(
                "none uncertainty cannot carry codes or a note"
            )
        if state != ClinicalUncertaintyState.NONE and not codes:
            raise ClinicalEventContractError(
                "non-none uncertainty must declare codes"
            )
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "codes", codes)
        object.__setattr__(self, "note", note)

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "codes": list(self.codes), "note": self.note}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> "ClinicalUncertainty":
        raw = {} if payload is None else payload
        if not isinstance(raw, Mapping):
            raise ClinicalEventContractError("uncertainty must be an object")
        return cls(
            state=raw.get("state", ClinicalUncertaintyState.NONE),
            codes=raw.get("codes", ()),
            note=raw.get("note", ""),
        )


@dataclass(frozen=True)
class ClinicalEvidenceRef:
    evidence_id: str
    source_binding_id: str
    source_revision: str
    locator_kind: str
    locator: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _identifier(self.evidence_id, "evidence_id"))
        object.__setattr__(self, "source_binding_id", _identifier(self.source_binding_id, "source_binding_id"))
        object.__setattr__(self, "source_revision", _identifier(self.source_revision, "source_revision"))
        object.__setattr__(self, "locator_kind", _identifier(self.locator_kind, "locator_kind"))
        object.__setattr__(self, "locator", _opaque(self.locator, "locator"))

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "source_binding_id": self.source_binding_id,
            "source_revision": self.source_revision,
            "locator_kind": self.locator_kind,
            "locator": self.locator,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalEvidenceRef":
        if not isinstance(payload, Mapping):
            raise ClinicalEventContractError("evidence entry must be an object")
        return cls(
            evidence_id=payload.get("evidence_id", ""),
            source_binding_id=payload.get("source_binding_id", ""),
            source_revision=payload.get("source_revision", ""),
            locator_kind=payload.get("locator_kind", ""),
            locator=payload.get("locator", ""),
        )


@dataclass(frozen=True)
class ClinicalRuleBinding:
    binding_id: str
    rule_id: str
    rule_revision: str
    threshold_code: str = ""
    threshold_value: str = ""
    threshold_unit: str = ""
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _identifier(self.binding_id, "rule.binding_id"))
        object.__setattr__(self, "rule_id", _identifier(self.rule_id, "rule.rule_id"))
        object.__setattr__(self, "rule_revision", _identifier(self.rule_revision, "rule.rule_revision"))
        object.__setattr__(self, "threshold_code", _text(self.threshold_code))
        object.__setattr__(self, "threshold_value", _text(self.threshold_value))
        object.__setattr__(self, "threshold_unit", _text(self.threshold_unit))
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "rule.evidence_ids"))

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
    def from_dict(cls, payload: Mapping[str, Any]) -> "ClinicalRuleBinding":
        if not isinstance(payload, Mapping):
            raise ClinicalEventContractError("rule binding must be an object")
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
class MonitoringClinicalObservation:
    observation_id: str
    event_id: str
    domain: ClinicalDomain
    field_name: str
    value_status: ClinicalValueStatus = ClinicalValueStatus.PRESENT
    raw_value: str = ""
    normalized_value: str = ""
    unit: str = ""
    reference_range: Mapping[str, Any] | None = None
    evidence_ids: tuple[str, ...] = ()
    rule_binding_ids: tuple[str, ...] = ()
    completeness: ClinicalCompleteness = field(default_factory=lambda: ClinicalCompleteness(ClinicalCompletenessStatus.COMPLETE))
    uncertainty: ClinicalUncertainty = field(default_factory=ClinicalUncertainty)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _identifier(self.observation_id, "observation_id"))
        object.__setattr__(self, "event_id", _identifier(self.event_id, "observation.event_id"))
        object.__setattr__(self, "domain", _enum(self.domain, ClinicalDomain, "observation.domain"))
        field_name = _required(self.field_name, "observation.field_name")
        if _ABSOLUTE_PATH_RE.match(field_name) or _PATH_SEGMENT_RE.search(field_name):
            raise ClinicalEventContractError("observation.field_name must not be a local path")
        object.__setattr__(self, "field_name", field_name)
        value_status = _enum(self.value_status, ClinicalValueStatus, "observation.value_status")
        raw_value = _text(self.raw_value)
        normalized = _text(self.normalized_value)
        if value_status == ClinicalValueStatus.PRESENT and not raw_value:
            raise ClinicalEventContractError("present observation requires raw_value")
        if value_status != ClinicalValueStatus.PRESENT and normalized:
            raise ClinicalEventContractError(
                "non-present observation cannot carry normalized_value"
            )
        object.__setattr__(self, "value_status", value_status)
        object.__setattr__(self, "raw_value", raw_value)
        object.__setattr__(self, "normalized_value", normalized)
        object.__setattr__(self, "unit", _text(self.unit))
        object.__setattr__(self, "reference_range", _mapping(self.reference_range, "reference_range"))
        object.__setattr__(self, "evidence_ids", _ids(self.evidence_ids, "observation.evidence_ids"))
        object.__setattr__(self, "rule_binding_ids", _ids(self.rule_binding_ids, "observation.rule_binding_ids"))
        if not isinstance(self.completeness, ClinicalCompleteness):
            object.__setattr__(self, "completeness", ClinicalCompleteness.from_dict(self.completeness))
        if not isinstance(self.uncertainty, ClinicalUncertainty):
            object.__setattr__(self, "uncertainty", ClinicalUncertainty.from_dict(self.uncertainty))

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "event_id": self.event_id,
            "domain": self.domain.value,
            "field_name": self.field_name,
            "value_status": self.value_status.value,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "unit": self.unit,
            "reference_range": dict(self.reference_range) if self.reference_range else None,
            "evidence_ids": list(self.evidence_ids),
            "rule_binding_ids": list(self.rule_binding_ids),
            "completeness": self.completeness.to_dict(),
            "uncertainty": self.uncertainty.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MonitoringClinicalObservation":
        if not isinstance(payload, Mapping):
            raise ClinicalEventContractError("observation must be an object")
        return cls(
            observation_id=payload.get("observation_id", ""),
            event_id=payload.get("event_id", ""),
            domain=payload.get("domain", ""),
            field_name=payload.get("field_name", ""),
            value_status=payload.get("value_status", "present"),
            raw_value=payload.get("raw_value", ""),
            normalized_value=payload.get("normalized_value", ""),
            unit=payload.get("unit", ""),
            reference_range=payload.get("reference_range"),
            evidence_ids=payload.get("evidence_ids", ()),
            rule_binding_ids=payload.get("rule_binding_ids", ()),
            completeness=ClinicalCompleteness.from_dict(payload.get("completeness")),
            uncertainty=ClinicalUncertainty.from_dict(payload.get("uncertainty")),
        )


@dataclass(frozen=True)
class MonitoringClinicalEvent:
    event_id: str
    project_id: str
    trial_id: str
    site_id: str
    subject_id: str
    domain: ClinicalDomain
    event_kind: ClinicalEventKind
    source_binding_id: str
    source_revision: str
    source_sheet: str
    source_row: int
    source_record_id: str
    event_date: str = ""
    date_precision: ClinicalDatePrecision = ClinicalDatePrecision.UNKNOWN
    date_raw: str = ""
    visit_label: str = ""
    visit_number: int | None = None
    ae_ids: tuple[str, ...] = ()
    mh_ids: tuple[str, ...] = ()
    cm_ids: tuple[str, ...] = ()
    ip_ids: tuple[str, ...] = ()
    finding_ids: tuple[str, ...] = ()
    pd_ids: tuple[str, ...] = ()
    risk_instance_ids: tuple[str, ...] = ()
    evidence: tuple[ClinicalEvidenceRef, ...] = ()
    rule_bindings: tuple[ClinicalRuleBinding, ...] = ()
    observations: tuple[MonitoringClinicalObservation, ...] = ()
    completeness: ClinicalCompleteness = field(default_factory=lambda: ClinicalCompleteness(ClinicalCompletenessStatus.COMPLETE))
    uncertainty: ClinicalUncertainty = field(default_factory=ClinicalUncertainty)
    event_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in ("event_id", "project_id", "trial_id", "site_id", "subject_id"):
            object.__setattr__(self, field_name, _identifier(getattr(self, field_name), field_name))
        object.__setattr__(self, "domain", _enum(self.domain, ClinicalDomain, "domain"))
        object.__setattr__(self, "event_kind", _enum(self.event_kind, ClinicalEventKind, "event_kind"))
        object.__setattr__(self, "source_binding_id", _identifier(self.source_binding_id, "source_binding_id"))
        object.__setattr__(self, "source_revision", _identifier(self.source_revision, "source_revision"))
        object.__setattr__(self, "source_sheet", _opaque(self.source_sheet, "source_sheet"))
        if not isinstance(self.source_row, int) or isinstance(self.source_row, bool) or self.source_row < 1:
            raise ClinicalEventContractError("source_row must be a positive integer")
        object.__setattr__(self, "source_record_id", _opaque(self.source_record_id, "source_record_id"))
        precision = _enum(self.date_precision, ClinicalDatePrecision, "date_precision")
        event_date = _text(self.event_date)
        date_patterns = {
            ClinicalDatePrecision.DAY: _DAY_RE,
            ClinicalDatePrecision.MONTH: _MONTH_RE,
            ClinicalDatePrecision.YEAR: _YEAR_RE,
        }
        if precision != ClinicalDatePrecision.UNKNOWN:
            if not event_date or not date_patterns[precision].fullmatch(event_date):
                raise ClinicalEventContractError(
                    f"event_date does not match {precision.value} precision"
                )
            _validate_date(event_date, precision)
        elif event_date:
            raise ClinicalEventContractError("unknown date precision cannot carry event_date")
        object.__setattr__(self, "date_precision", precision)
        object.__setattr__(self, "event_date", event_date)
        object.__setattr__(self, "date_raw", _text(self.date_raw))
        object.__setattr__(self, "visit_label", _text(self.visit_label))
        if self.visit_number is not None and (
            not isinstance(self.visit_number, int)
            or isinstance(self.visit_number, bool)
            or self.visit_number < 0
        ):
            raise ClinicalEventContractError("visit_number must be a non-negative integer")
        for field_name in (
            "ae_ids",
            "mh_ids",
            "cm_ids",
            "ip_ids",
            "finding_ids",
            "pd_ids",
            "risk_instance_ids",
        ):
            object.__setattr__(self, field_name, _ids(getattr(self, field_name), field_name))
        if self.domain == ClinicalDomain.CM and self.ip_ids:
            raise ClinicalEventContractError("CM event cannot link investigational-product ids")
        if self.domain == ClinicalDomain.IP and self.cm_ids:
            raise ClinicalEventContractError("IP event cannot link concomitant-medication ids")

        evidence = tuple(self.evidence)
        if any(not isinstance(item, ClinicalEvidenceRef) for item in evidence):
            raise ClinicalEventContractError("evidence must contain evidence references")
        if len({item.evidence_id for item in evidence}) != len(evidence):
            raise ClinicalEventContractError("evidence ids must be unique")
        evidence = tuple(sorted(evidence, key=lambda item: item.evidence_id))
        evidence_ids = {item.evidence_id for item in evidence}
        if evidence and not any(
            item.source_binding_id == self.source_binding_id for item in evidence
        ):
            raise ClinicalEventContractError(
                "event evidence must include the event source binding"
            )
        rules = tuple(self.rule_bindings)
        if any(not isinstance(item, ClinicalRuleBinding) for item in rules):
            raise ClinicalEventContractError("rule_bindings must contain rule references")
        if len({item.binding_id for item in rules}) != len(rules):
            raise ClinicalEventContractError("rule binding ids must be unique")
        rules = tuple(sorted(rules, key=lambda item: item.binding_id))
        rule_ids = {item.binding_id for item in rules}
        if any(set(item.evidence_ids) - evidence_ids for item in rules):
            raise ClinicalEventContractError("rule evidence must be declared by the event")

        observations = tuple(self.observations)
        if any(not isinstance(item, MonitoringClinicalObservation) for item in observations):
            raise ClinicalEventContractError("observations must contain observation objects")
        if len({item.observation_id for item in observations}) != len(observations):
            raise ClinicalEventContractError("observation ids must be unique")
        for observation in observations:
            if observation.event_id != self.event_id:
                raise ClinicalEventContractError("observation event_id does not match event")
            if observation.domain != self.domain:
                raise ClinicalEventContractError("observation domain does not match event")
            if set(observation.evidence_ids) - evidence_ids:
                raise ClinicalEventContractError(
                    "observation evidence must be declared by the event"
                )
            if set(observation.rule_binding_ids) - rule_ids:
                raise ClinicalEventContractError(
                    "observation rule bindings must be declared by the event"
                )
        observations = tuple(sorted(observations, key=lambda item: item.observation_id))
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "rule_bindings", rules)
        object.__setattr__(self, "observations", observations)
        if not isinstance(self.completeness, ClinicalCompleteness):
            object.__setattr__(self, "completeness", ClinicalCompleteness.from_dict(self.completeness))
        if not isinstance(self.uncertainty, ClinicalUncertainty):
            object.__setattr__(self, "uncertainty", ClinicalUncertainty.from_dict(self.uncertainty))
        object.__setattr__(self, "event_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "project_id": self.project_id,
            "trial_id": self.trial_id,
            "site_id": self.site_id,
            "subject_id": self.subject_id,
            "domain": self.domain.value,
            "event_kind": self.event_kind.value,
            "source_binding_id": self.source_binding_id,
            "source_revision": self.source_revision,
            "source_sheet": self.source_sheet,
            "source_row": self.source_row,
            "source_record_id": self.source_record_id,
            "event_date": self.event_date,
            "date_precision": self.date_precision.value,
            "date_raw": self.date_raw,
            "visit_label": self.visit_label,
            "visit_number": self.visit_number,
            "ae_ids": list(self.ae_ids),
            "mh_ids": list(self.mh_ids),
            "cm_ids": list(self.cm_ids),
            "ip_ids": list(self.ip_ids),
            "finding_ids": list(self.finding_ids),
            "pd_ids": list(self.pd_ids),
            "risk_instance_ids": list(self.risk_instance_ids),
            "evidence": [item.to_dict() for item in self.evidence],
            "rule_bindings": [item.to_dict() for item in self.rule_bindings],
            "observations": [item.to_dict() for item in self.observations],
            "completeness": self.completeness.to_dict(),
            "uncertainty": self.uncertainty.to_dict(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "event_sha256": self.event_sha256}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MonitoringClinicalEvent":
        if not isinstance(payload, Mapping):
            raise ClinicalEventContractError("event must be an object")
        def _objects(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
            if value is None:
                return ()
            if not isinstance(value, (list, tuple)) or any(
                not isinstance(item, Mapping) for item in value
            ):
                raise ClinicalEventContractError(f"{field_name} must be a list of objects")
            return tuple(value)

        event = cls(
            event_id=payload.get("event_id", ""),
            project_id=payload.get("project_id", ""),
            trial_id=payload.get("trial_id", ""),
            site_id=payload.get("site_id", ""),
            subject_id=payload.get("subject_id", ""),
            domain=payload.get("domain", ""),
            event_kind=payload.get("event_kind", ""),
            source_binding_id=payload.get("source_binding_id", ""),
            source_revision=payload.get("source_revision", ""),
            source_sheet=payload.get("source_sheet", ""),
            source_row=payload.get("source_row", 0),
            source_record_id=payload.get("source_record_id", ""),
            event_date=payload.get("event_date", ""),
            date_precision=payload.get("date_precision", ClinicalDatePrecision.UNKNOWN),
            date_raw=payload.get("date_raw", ""),
            visit_label=payload.get("visit_label", ""),
            visit_number=payload.get("visit_number"),
            ae_ids=payload.get("ae_ids", ()),
            mh_ids=payload.get("mh_ids", ()),
            cm_ids=payload.get("cm_ids", ()),
            ip_ids=payload.get("ip_ids", ()),
            finding_ids=payload.get("finding_ids", ()),
            pd_ids=payload.get("pd_ids", ()),
            risk_instance_ids=payload.get("risk_instance_ids", ()),
            evidence=tuple(
                ClinicalEvidenceRef.from_dict(item)
                for item in _objects(payload.get("evidence", ()), "evidence")
            ),
            rule_bindings=tuple(
                ClinicalRuleBinding.from_dict(item)
                for item in _objects(payload.get("rule_bindings", ()), "rule_bindings")
            ),
            observations=tuple(
                MonitoringClinicalObservation.from_dict(item)
                for item in _objects(payload.get("observations", ()), "observations")
            ),
            completeness=ClinicalCompleteness.from_dict(payload.get("completeness")),
            uncertainty=ClinicalUncertainty.from_dict(payload.get("uncertainty")),
        )
        declared_hash = _declared_sha256(payload.get("event_sha256"), "event_sha256")
        if declared_hash and declared_hash != event.event_sha256:
            raise ClinicalEventContractError("event_sha256 does not match canonical content")
        return event


__all__ = [
    "ClinicalCompleteness",
    "ClinicalCompletenessStatus",
    "ClinicalDatePrecision",
    "ClinicalDomain",
    "ClinicalEventContractError",
    "ClinicalEventKind",
    "ClinicalEvidenceRef",
    "ClinicalRuleBinding",
    "ClinicalUncertainty",
    "ClinicalUncertaintyState",
    "ClinicalValueStatus",
    "MonitoringClinicalEvent",
    "MonitoringClinicalObservation",
]
