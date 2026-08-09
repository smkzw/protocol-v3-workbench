"""Pure protocol-to-listing mapping precheck.

The precheck is deliberately separate from source registration, mapping
activation, and runtime evaluation.  It turns protocol visit requirements and
listing field candidates into a deterministic, source-bound review report.  A
``passed`` precheck means that the supplied mapping is structurally ready for
medical review; it never grants activation permission.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping


PROTOCOL_LISTING_PRECHECK_SCHEMA_VERSION = (
    "monitoring_protocol_listing_precheck_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProtocolListingPrecheckStatus(str, Enum):
    PASSED = "passed"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class ProtocolListingFindingSeverity(str, Enum):
    BLOCKER = "blocker"
    REVIEW_REQUIRED = "review_required"
    WARNING = "warning"


class ProtocolListingAvailability(str, Enum):
    AVAILABLE = "available"
    COLLECTION_ONLY = "collection_only"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class ProtocolListingVisitBinding(str, Enum):
    EXPLICIT = "explicit"
    DERIVED = "derived"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class ProtocolVisitRequirement:
    """One protocol-defined visit and its auditable source locator."""

    visit_id: str
    label: str
    anchor_day: int | float
    window_before_days: int | float = 0
    window_after_days: int | float = 0
    source_locator: str = ""


@dataclass(frozen=True)
class ProtocolListingMappingCandidate:
    """A proposed link between one listing field and protocol evidence."""

    mapping_id: str
    module: str
    domain: str
    source_sheet: str
    source_field: str
    source_locator: str
    protocol_fact_key: str
    protocol_locator: str
    availability: ProtocolListingAvailability | str = (
        ProtocolListingAvailability.AVAILABLE
    )
    visit_binding: ProtocolListingVisitBinding | str = (
        ProtocolListingVisitBinding.EXPLICIT
    )
    visit_source_field: str = ""
    protocol_visit_ids: tuple[str, ...] = ()
    requires_visit: bool = True
    supports_quantitative_result: bool = False
    result_field: str = ""
    lloq_field: str = ""


@dataclass(frozen=True)
class ProtocolListingPrecheckFinding:
    code: str
    severity: ProtocolListingFindingSeverity
    summary: str
    mapping_ids: tuple[str, ...] = ()
    locators: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        payload["mapping_ids"] = list(self.mapping_ids)
        payload["locators"] = list(self.locators)
        return payload


@dataclass(frozen=True)
class ProtocolListingPrecheckReport:
    schema_version: str
    status: ProtocolListingPrecheckStatus
    activation_allowed: bool
    protocol_source_sha256: str
    listing_source_sha256: str
    input_sha256: str
    visit_count: int
    mapping_count: int
    duplicate_header_sheets: tuple[str, ...]
    unresolved_mapping_reasons: tuple[str, ...]
    findings: tuple[ProtocolListingPrecheckFinding, ...]
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.activation_allowed:
            raise ValueError("protocol/listing precheck cannot grant activation")
        object.__setattr__(
            self,
            "duplicate_header_sheets",
            tuple(sorted(set(_text(item) for item in self.duplicate_header_sheets if _text(item)))),
        )
        object.__setattr__(
            self,
            "unresolved_mapping_reasons",
            tuple(sorted(set(_text(item) for item in self.unresolved_mapping_reasons if _text(item)))),
        )
        findings = tuple(sorted(self.findings, key=_finding_sort_key))
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "activation_allowed": self.activation_allowed,
            "protocol_source_sha256": self.protocol_source_sha256,
            "listing_source_sha256": self.listing_source_sha256,
            "input_sha256": self.input_sha256,
            "visit_count": self.visit_count,
            "mapping_count": self.mapping_count,
            "duplicate_header_sheets": list(self.duplicate_header_sheets),
            "unresolved_mapping_reasons": list(self.unresolved_mapping_reasons),
            "findings": [item.to_dict() for item in self.findings],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def precheck_protocol_listing_mapping(
    *,
    protocol_source_sha256: str,
    listing_source_sha256: str,
    visits: Iterable[ProtocolVisitRequirement],
    mappings: Iterable[ProtocolListingMappingCandidate],
    duplicate_header_sheets: Iterable[str] = (),
    unresolved_mapping_reasons: Iterable[str] = (),
) -> ProtocolListingPrecheckReport:
    """Evaluate a source-bound mapping without touching runtime state.

    Missing or ambiguous visit mappings, duplicate-header use, unresolved
    mapping notes, and collection-only PK/PD fields that claim quantitative
    results fail closed.  The function is pure and deterministic: order of
    input rows does not change the report hash.
    """

    visit_rows = tuple(visits)
    mapping_rows = tuple(mappings)
    duplicate_headers = _clean_text_tuple(duplicate_header_sheets)
    unresolved_reasons = _clean_text_tuple(unresolved_mapping_reasons)
    findings: list[ProtocolListingPrecheckFinding] = []

    protocol_hash = _normalise_source_hash(
        protocol_source_sha256,
        "protocol_source_sha256",
        findings,
    )
    listing_hash = _normalise_source_hash(
        listing_source_sha256,
        "listing_source_sha256",
        findings,
    )

    visit_by_id: dict[str, ProtocolVisitRequirement] = {}
    duplicate_visit_ids: set[str] = set()
    for visit in sorted(visit_rows, key=_visit_sort_key):
        visit_id = _text(getattr(visit, "visit_id", ""))
        if not visit_id:
            findings.append(
                _finding(
                    "protocol_visit_id_missing",
                    ProtocolListingFindingSeverity.BLOCKER,
                    "protocol visit requires a stable visit_id",
                    locators=(_text(getattr(visit, "source_locator", "")),),
                )
            )
            continue
        if visit_id in visit_by_id:
            duplicate_visit_ids.add(visit_id)
        visit_by_id[visit_id] = visit
        _validate_visit(visit, findings)
    if duplicate_visit_ids:
        findings.append(
            _finding(
                "protocol_visit_id_duplicate",
                ProtocolListingFindingSeverity.BLOCKER,
                "protocol visit identifiers must be unique",
                mapping_ids=tuple(sorted(duplicate_visit_ids)),
            )
        )
    if not visit_rows:
        findings.append(
            _finding(
                "protocol_visit_schedule_missing",
                ProtocolListingFindingSeverity.BLOCKER,
                "no protocol visit schedule was supplied",
            )
        )

    if duplicate_headers:
        findings.append(
            _finding(
                "duplicate_header_sheet_present",
                ProtocolListingFindingSeverity.REVIEW_REQUIRED,
                "listing contains sheets with duplicate headers; field mapping requires review",
                locators=tuple(f"listing:sheet:{item}" for item in duplicate_headers),
            )
        )
    if unresolved_reasons:
        findings.append(
            _finding(
                "unresolved_mapping_reason",
                ProtocolListingFindingSeverity.BLOCKER,
                "mapping precheck contains unresolved field or visit decisions",
                locators=unresolved_reasons,
            )
        )

    duplicate_mapping_ids: set[str] = set()
    seen_mapping_ids: set[str] = set()
    for mapping in sorted(mapping_rows, key=_mapping_sort_key):
        mapping_id = _text(getattr(mapping, "mapping_id", ""))
        if mapping_id and mapping_id in seen_mapping_ids:
            duplicate_mapping_ids.add(mapping_id)
        if mapping_id:
            seen_mapping_ids.add(mapping_id)
        _validate_mapping(
            mapping,
            visit_by_id=visit_by_id,
            duplicate_headers=set(item.casefold() for item in duplicate_headers),
            findings=findings,
        )
    if duplicate_mapping_ids:
        findings.append(
            _finding(
                "mapping_id_duplicate",
                ProtocolListingFindingSeverity.BLOCKER,
                "listing mapping identifiers must be unique",
                mapping_ids=tuple(sorted(duplicate_mapping_ids)),
            )
        )
    if not mapping_rows:
        findings.append(
            _finding(
                "listing_mapping_missing",
                ProtocolListingFindingSeverity.BLOCKER,
                "no protocol-to-listing mapping candidates were supplied",
            )
        )

    input_payload = {
        "protocol_source_sha256": protocol_hash,
        "listing_source_sha256": listing_hash,
        "visits": [_visit_payload(item) for item in sorted(visit_rows, key=_visit_sort_key)],
        "mappings": [
            _mapping_payload(item) for item in sorted(mapping_rows, key=_mapping_sort_key)
        ],
        "duplicate_header_sheets": list(duplicate_headers),
        "unresolved_mapping_reasons": list(unresolved_reasons),
    }
    input_sha256 = _digest(input_payload)
    status = _status_for(findings)
    return ProtocolListingPrecheckReport(
        schema_version=PROTOCOL_LISTING_PRECHECK_SCHEMA_VERSION,
        status=status,
        activation_allowed=False,
        protocol_source_sha256=protocol_hash,
        listing_source_sha256=listing_hash,
        input_sha256=input_sha256,
        visit_count=len(visit_rows),
        mapping_count=len(mapping_rows),
        duplicate_header_sheets=duplicate_headers,
        unresolved_mapping_reasons=unresolved_reasons,
        findings=tuple(findings),
    )


def _validate_visit(
    visit: ProtocolVisitRequirement,
    findings: list[ProtocolListingPrecheckFinding],
) -> None:
    visit_id = _text(getattr(visit, "visit_id", ""))
    locator = _text(getattr(visit, "source_locator", ""))
    if not _text(getattr(visit, "label", "")):
        findings.append(
            _finding(
                "protocol_visit_label_missing",
                ProtocolListingFindingSeverity.BLOCKER,
                "protocol visit label is required",
                mapping_ids=(visit_id,) if visit_id else (),
                locators=(locator,) if locator else (),
            )
        )
    if not locator:
        findings.append(
            _finding(
                "protocol_visit_locator_missing",
                ProtocolListingFindingSeverity.BLOCKER,
                "protocol visit must retain a source locator",
                mapping_ids=(visit_id,) if visit_id else (),
            )
        )
    for name in ("anchor_day", "window_before_days", "window_after_days"):
        value = getattr(visit, name, None)
        if not _finite_number(value):
            findings.append(
                _finding(
                    "protocol_visit_day_invalid",
                    ProtocolListingFindingSeverity.BLOCKER,
                    f"protocol visit {name} must be a finite number",
                    mapping_ids=(visit_id,) if visit_id else (),
                    locators=(locator,) if locator else (),
                )
            )
        elif name != "anchor_day" and value < 0:
            findings.append(
                _finding(
                    "protocol_visit_window_invalid",
                    ProtocolListingFindingSeverity.BLOCKER,
                    f"protocol visit {name} cannot be negative",
                    mapping_ids=(visit_id,) if visit_id else (),
                    locators=(locator,) if locator else (),
                )
            )


def _validate_mapping(
    mapping: ProtocolListingMappingCandidate,
    *,
    visit_by_id: Mapping[str, ProtocolVisitRequirement],
    duplicate_headers: set[str],
    findings: list[ProtocolListingPrecheckFinding],
) -> None:
    mapping_id = _text(getattr(mapping, "mapping_id", ""))
    mapping_ids = (mapping_id,) if mapping_id else ()
    source_locator = _text(getattr(mapping, "source_locator", ""))
    locators = (source_locator,) if source_locator else ()
    required_fields = (
        "mapping_id",
        "module",
        "domain",
        "source_sheet",
        "source_field",
        "source_locator",
        "protocol_fact_key",
        "protocol_locator",
    )
    for name in required_fields:
        if not _text(getattr(mapping, name, "")):
            findings.append(
                _finding(
                    "mapping_field_missing",
                    ProtocolListingFindingSeverity.BLOCKER,
                    f"mapping {name} is required",
                    mapping_ids=mapping_ids,
                    locators=locators,
                )
            )

    availability = _enum_text(getattr(mapping, "availability", ""))
    if availability not in {item.value for item in ProtocolListingAvailability}:
        findings.append(
            _finding(
                "mapping_availability_invalid",
                ProtocolListingFindingSeverity.BLOCKER,
                "mapping availability is not a supported state",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
    elif availability == ProtocolListingAvailability.BLOCKED.value:
        findings.append(
            _finding(
                "mapping_explicitly_blocked",
                ProtocolListingFindingSeverity.BLOCKER,
                "mapping candidate is explicitly blocked",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
    elif availability == ProtocolListingAvailability.REVIEW_REQUIRED.value:
        findings.append(
            _finding(
                "mapping_review_required",
                ProtocolListingFindingSeverity.REVIEW_REQUIRED,
                "mapping candidate remains pending medical or source review",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )

    sheet = _text(getattr(mapping, "source_sheet", ""))
    if sheet and sheet.casefold() in duplicate_headers:
        findings.append(
            _finding(
                "mapping_uses_duplicate_header_sheet",
                ProtocolListingFindingSeverity.BLOCKER,
                "mapping uses a sheet with duplicate headers",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )

    requires_visit = getattr(mapping, "requires_visit", None)
    if not isinstance(requires_visit, bool):
        findings.append(
            _finding(
                "mapping_requires_visit_invalid",
                ProtocolListingFindingSeverity.BLOCKER,
                "requires_visit must be a strict boolean",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
        requires_visit = True

    _validate_visit_binding(
        mapping,
        requires_visit=requires_visit,
        visit_by_id=visit_by_id,
        findings=findings,
    )
    _validate_pk_pd_collection_boundary(mapping, findings=findings)


def _validate_visit_binding(
    mapping: ProtocolListingMappingCandidate,
    *,
    requires_visit: bool,
    visit_by_id: Mapping[str, ProtocolVisitRequirement],
    findings: list[ProtocolListingPrecheckFinding],
) -> None:
    mapping_id = _text(getattr(mapping, "mapping_id", ""))
    mapping_ids = (mapping_id,) if mapping_id else ()
    loc = _text(getattr(mapping, "source_locator", ""))
    locators = (loc,) if loc else ()
    binding = _enum_text(getattr(mapping, "visit_binding", ""))
    allowed = {item.value for item in ProtocolListingVisitBinding}
    if binding not in allowed:
        findings.append(
            _finding(
                "visit_binding_invalid",
                ProtocolListingFindingSeverity.BLOCKER,
                "visit binding is not a supported state",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
        return
    if not requires_visit:
        return

    if binding in {
        ProtocolListingVisitBinding.MISSING.value,
        ProtocolListingVisitBinding.AMBIGUOUS.value,
        ProtocolListingVisitBinding.NOT_APPLICABLE.value,
    }:
        findings.append(
            _finding(
                "visit_binding_unresolved",
                ProtocolListingFindingSeverity.BLOCKER,
                "visit-dependent mapping lacks a confident visit binding",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
    elif binding == ProtocolListingVisitBinding.DERIVED.value:
        findings.append(
            _finding(
                "visit_binding_derived_review",
                ProtocolListingFindingSeverity.REVIEW_REQUIRED,
                "visit binding is derived and requires source/reviewer confirmation",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )

    if not _text(getattr(mapping, "visit_source_field", "")):
        findings.append(
            _finding(
                "visit_source_field_missing",
                ProtocolListingFindingSeverity.BLOCKER,
                "visit-dependent mapping requires an explicit source visit field",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
    raw_ids = getattr(mapping, "protocol_visit_ids", ())
    if isinstance(raw_ids, str) or not isinstance(raw_ids, (tuple, list)):
        findings.append(
            _finding(
                "protocol_visit_reference_invalid",
                ProtocolListingFindingSeverity.BLOCKER,
                "protocol_visit_ids must be a sequence of visit identifiers",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
        return
    visit_ids = tuple(_text(item) for item in raw_ids)
    if not visit_ids:
        findings.append(
            _finding(
                "protocol_visit_reference_missing",
                ProtocolListingFindingSeverity.BLOCKER,
                "visit-dependent mapping must reference protocol visits",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
        return
    if len(visit_ids) != len(set(visit_ids)) or any(not item for item in visit_ids):
        findings.append(
            _finding(
                "protocol_visit_reference_duplicate",
                ProtocolListingFindingSeverity.BLOCKER,
                "protocol visit references must be non-empty and unique",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
    unknown = tuple(sorted(set(item for item in visit_ids if item not in visit_by_id)))
    if unknown:
        findings.append(
            _finding(
                "protocol_visit_reference_unknown",
                ProtocolListingFindingSeverity.BLOCKER,
                "mapping references visits absent from the protocol schedule",
                mapping_ids=mapping_ids,
                locators=unknown,
            )
        )


def _validate_pk_pd_collection_boundary(
    mapping: ProtocolListingMappingCandidate,
    *,
    findings: list[ProtocolListingPrecheckFinding],
) -> None:
    module = _text(getattr(mapping, "module", "")).casefold()
    domain = _text(getattr(mapping, "domain", "")).casefold()
    sheet = _text(getattr(mapping, "source_sheet", "")).casefold()
    is_pk_pd = module in {
        "pk",
        "pd",
        "pharmacokinetic",
        "pharmacodynamic",
    } or domain in {"pk", "pd", "pc1", "pc2", "pc3"} or sheet in {
        "pc1",
        "pc2",
        "pc3",
    }
    if not is_pk_pd:
        return
    availability = _enum_text(getattr(mapping, "availability", ""))
    supports_quantitative = getattr(mapping, "supports_quantitative_result", None)
    mapping_id = _text(getattr(mapping, "mapping_id", ""))
    mapping_ids = (mapping_id,) if mapping_id else ()
    loc = _text(getattr(mapping, "source_locator", ""))
    locators = (loc,) if loc else ()
    if not isinstance(supports_quantitative, bool):
        findings.append(
            _finding(
                "pk_pd_quantitative_flag_invalid",
                ProtocolListingFindingSeverity.BLOCKER,
                "supports_quantitative_result must be a strict boolean",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )
        supports_quantitative = True
    if availability == ProtocolListingAvailability.COLLECTION_ONLY.value and (
        supports_quantitative
        or _text(getattr(mapping, "result_field", ""))
        or _text(getattr(mapping, "lloq_field", ""))
    ):
        findings.append(
            _finding(
                "collection_only_quantitative_conflict",
                ProtocolListingFindingSeverity.BLOCKER,
                "PK/PD collection-only data cannot claim a result or LLOQ field",
                mapping_ids=mapping_ids,
                locators=locators,
            )
        )


def _status_for(
    findings: Iterable[ProtocolListingPrecheckFinding],
) -> ProtocolListingPrecheckStatus:
    values = tuple(findings)
    if any(item.severity is ProtocolListingFindingSeverity.BLOCKER for item in values):
        return ProtocolListingPrecheckStatus.BLOCKED
    if any(
        item.severity is ProtocolListingFindingSeverity.REVIEW_REQUIRED
        for item in values
    ):
        return ProtocolListingPrecheckStatus.REVIEW_REQUIRED
    return ProtocolListingPrecheckStatus.PASSED


def _finding(
    code: str,
    severity: ProtocolListingFindingSeverity,
    summary: str,
    *,
    mapping_ids: tuple[str, ...] = (),
    locators: tuple[str, ...] = (),
) -> ProtocolListingPrecheckFinding:
    return ProtocolListingPrecheckFinding(
        code=code,
        severity=severity,
        summary=summary,
        mapping_ids=tuple(sorted(set(item for item in mapping_ids if item))),
        locators=tuple(sorted(set(item for item in locators if item))),
    )


def _normalise_source_hash(
    value: Any,
    label: str,
    findings: list[ProtocolListingPrecheckFinding],
) -> str:
    raw = _text(value)
    cleaned = raw.lower()
    if raw != cleaned or not _SHA256_RE.fullmatch(cleaned):
        findings.append(
            _finding(
                "source_hash_invalid",
                ProtocolListingFindingSeverity.BLOCKER,
                f"{label} must be a lowercase SHA-256",
            )
        )
    return cleaned


def _visit_payload(value: ProtocolVisitRequirement) -> dict[str, Any]:
    return {
        "visit_id": _text(getattr(value, "visit_id", "")),
        "label": _text(getattr(value, "label", "")),
        "anchor_day": getattr(value, "anchor_day", None),
        "window_before_days": getattr(value, "window_before_days", None),
        "window_after_days": getattr(value, "window_after_days", None),
        "source_locator": _text(getattr(value, "source_locator", "")),
    }


def _mapping_payload(value: ProtocolListingMappingCandidate) -> dict[str, Any]:
    return {
        "mapping_id": _text(getattr(value, "mapping_id", "")),
        "module": _text(getattr(value, "module", "")),
        "domain": _text(getattr(value, "domain", "")),
        "source_sheet": _text(getattr(value, "source_sheet", "")),
        "source_field": _text(getattr(value, "source_field", "")),
        "source_locator": _text(getattr(value, "source_locator", "")),
        "protocol_fact_key": _text(getattr(value, "protocol_fact_key", "")),
        "protocol_locator": _text(getattr(value, "protocol_locator", "")),
        "availability": _enum_text(getattr(value, "availability", "")),
        "visit_binding": _enum_text(getattr(value, "visit_binding", "")),
        "visit_source_field": _text(getattr(value, "visit_source_field", "")),
        "protocol_visit_ids": sorted(
            _text(item) for item in (getattr(value, "protocol_visit_ids", ()) or ())
        ),
        "requires_visit": getattr(value, "requires_visit", None),
        "supports_quantitative_result": getattr(
            value, "supports_quantitative_result", None
        ),
        "result_field": _text(getattr(value, "result_field", "")),
        "lloq_field": _text(getattr(value, "lloq_field", "")),
    }


def _finding_sort_key(
    finding: ProtocolListingPrecheckFinding,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    return (
        finding.severity.value,
        finding.code,
        finding.mapping_ids,
        finding.locators,
    )


def _visit_sort_key(value: ProtocolVisitRequirement) -> tuple[str, str, str]:
    return (
        _text(getattr(value, "visit_id", "")),
        _text(getattr(value, "source_locator", "")),
        _text(getattr(value, "label", "")),
    )


def _mapping_sort_key(
    value: ProtocolListingMappingCandidate,
) -> tuple[str, str, str]:
    return (
        _text(getattr(value, "mapping_id", "")),
        _text(getattr(value, "source_sheet", "")),
        _text(getattr(value, "source_field", "")),
    )


def _enum_text(value: Any) -> str:
    return value.value if isinstance(value, Enum) else _text(value)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _clean_text_tuple(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(sorted(set(_text(item) for item in values if _text(item))))


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return value == value and value not in (float("inf"), float("-inf"))


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_ready(item) for item in value]
    return value
