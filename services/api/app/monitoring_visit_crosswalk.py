"""Pure protocol-to-listing visit crosswalk validation.

The existing protocol/listing precheck validates the shape of a proposed
mapping.  This module validates the observed visit identity pairs and the
explicit crosswalk itself.  It deliberately has no runtime, database, API, or
activation side effects.  A passing report only means that the crosswalk is
structurally reviewable; it never grants permission to onboard or write.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from hashlib import sha256
import json
import math
import re
from typing import Any, Iterable, Mapping


VISIT_CROSSWALK_SCHEMA_VERSION = "monitoring_protocol_listing_visit_crosswalk_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VisitCrosswalkStatus(str, Enum):
    PASSED = "passed"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class VisitCrosswalkFindingSeverity(str, Enum):
    BLOCKER = "blocker"
    REVIEW_REQUIRED = "review_required"


class ObservedVisitKind(str, Enum):
    SCHEDULED = "scheduled"
    UNSCHEDULED = "unscheduled"
    WITHDRAWAL = "withdrawal"
    NON_VISIT = "non_visit"


class VisitCrosswalkBindingState(str, Enum):
    EXPLICIT = "explicit"
    LABEL_MATCH = "label_match"
    DERIVED = "derived"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class CrosswalkProtocolVisit:
    """One protocol visit, including its applicability and source locator."""

    visit_id: str
    label: str
    anchor_day: int | float
    window_before_days: int | float = 0
    window_after_days: int | float = 0
    source_locator: str = ""
    arm_scope: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True)
class CrosswalkObservedVisit:
    """One unique listing visit identity pair and its observed row count."""

    listing_visit_id: str
    listing_label: str
    source_locator: str
    row_count: int
    kind: ObservedVisitKind | str = ObservedVisitKind.SCHEDULED
    arm_scope: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return _observed_key(self.listing_visit_id, self.listing_label, self.arm_scope)


@dataclass(frozen=True)
class VisitCrosswalkBinding:
    """An explicit reviewer-proposed protocol-to-listing link."""

    binding_id: str
    protocol_visit_id: str
    observed_visit_keys: tuple[str, ...] = ()
    state: VisitCrosswalkBindingState | str = VisitCrosswalkBindingState.EXPLICIT
    source_locator: str = ""
    rationale: str = ""


@dataclass(frozen=True)
class VisitCrosswalkFinding:
    code: str
    severity: VisitCrosswalkFindingSeverity
    summary: str
    binding_ids: tuple[str, ...] = ()
    visit_ids: tuple[str, ...] = ()
    locators: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["severity"] = self.severity.value
        payload["binding_ids"] = list(self.binding_ids)
        payload["visit_ids"] = list(self.visit_ids)
        payload["locators"] = list(self.locators)
        return payload


@dataclass(frozen=True)
class VisitCrosswalkReport:
    schema_version: str
    status: VisitCrosswalkStatus
    activation_allowed: bool
    protocol_source_sha256: str
    listing_source_sha256: str
    input_sha256: str
    protocol_visit_count: int
    observed_visit_count: int
    binding_count: int
    findings: tuple[VisitCrosswalkFinding, ...]
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.activation_allowed:
            raise ValueError("visit crosswalk cannot grant activation")
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
            "protocol_visit_count": self.protocol_visit_count,
            "observed_visit_count": self.observed_visit_count,
            "binding_count": self.binding_count,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def validate_visit_crosswalk(
    *,
    protocol_source_sha256: str,
    listing_source_sha256: str,
    protocol_visits: Iterable[CrosswalkProtocolVisit],
    observed_visits: Iterable[CrosswalkObservedVisit],
    bindings: Iterable[VisitCrosswalkBinding],
) -> VisitCrosswalkReport:
    """Validate an explicit protocol/listing visit crosswalk.

    Required scheduled protocol visits must have exactly one evidence-backed
    binding.  Unscheduled, withdrawal, and non-visit records are allowed only as
    explicitly classified observations; they never satisfy a scheduled visit.
    Listing OID/label ordinal conflicts are surfaced instead of silently
    renumbered.  The function is deterministic and has no side effects.
    """

    protocol_rows = tuple(protocol_visits)
    observed_rows = tuple(observed_visits)
    binding_rows = tuple(bindings)
    findings: list[VisitCrosswalkFinding] = []

    protocol_hash = _normalise_hash(
        protocol_source_sha256, "protocol_source_sha256", findings
    )
    listing_hash = _normalise_hash(
        listing_source_sha256, "listing_source_sha256", findings
    )

    protocol_by_id: dict[str, CrosswalkProtocolVisit] = {}
    duplicate_protocol_ids: set[str] = set()
    for visit in sorted(protocol_rows, key=_protocol_sort_key):
        visit_id = _text(visit.visit_id)
        if not visit_id:
            findings.append(
                _finding(
                    "protocol_visit_id_missing",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "protocol visit requires a stable visit_id",
                )
            )
            continue
        if visit_id in protocol_by_id:
            duplicate_protocol_ids.add(visit_id)
        protocol_by_id[visit_id] = visit
        _validate_protocol_visit(visit, findings)
    if duplicate_protocol_ids:
        findings.append(
            _finding(
                "protocol_visit_id_duplicate",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "protocol visit identifiers must be unique",
                visit_ids=tuple(sorted(duplicate_protocol_ids)),
            )
        )
    if not protocol_rows:
        findings.append(
            _finding(
                "protocol_visit_schedule_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "no protocol visit schedule was supplied",
            )
        )

    observed_by_key: dict[str, CrosswalkObservedVisit] = {}
    duplicate_observed_keys: set[str] = set()
    for observed in sorted(observed_rows, key=_observed_sort_key):
        key = observed.key
        if key in observed_by_key:
            duplicate_observed_keys.add(key)
        observed_by_key[key] = observed
        _validate_observed_visit(observed, findings)
    if duplicate_observed_keys:
        findings.append(
            _finding(
                "observed_visit_key_duplicate",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "listing visit identity pairs must be unique",
                locators=tuple(sorted(duplicate_observed_keys)),
            )
        )

    binding_by_id: dict[str, VisitCrosswalkBinding] = {}
    duplicate_binding_ids: set[str] = set()
    bindings_by_protocol: dict[str, list[VisitCrosswalkBinding]] = {}
    observed_binding_ids: dict[str, list[str]] = {}
    for binding in sorted(binding_rows, key=_binding_sort_key):
        binding_id = _text(binding.binding_id)
        if binding_id in binding_by_id:
            duplicate_binding_ids.add(binding_id)
        if binding_id:
            binding_by_id[binding_id] = binding
        bindings_by_protocol.setdefault(_text(binding.protocol_visit_id), []).append(
            binding
        )
        _validate_binding(
            binding,
            protocol_by_id=protocol_by_id,
            observed_by_key=observed_by_key,
            findings=findings,
        )
        for key in sorted(
            set(_text(item) for item in binding.observed_visit_keys if _text(item))
        ):
            observed_binding_ids.setdefault(key, []).append(binding_id)
    if duplicate_binding_ids:
        findings.append(
            _finding(
                "binding_id_duplicate",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "crosswalk binding identifiers must be unique",
                binding_ids=tuple(sorted(duplicate_binding_ids)),
            )
        )

    for protocol_id, rows in sorted(bindings_by_protocol.items()):
        if protocol_id and len(rows) > 1:
            findings.append(
                _finding(
                    "protocol_visit_binding_duplicate",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "a protocol visit cannot have multiple competing bindings",
                    binding_ids=tuple(
                        sorted(
                            _text(row.binding_id)
                            for row in rows
                            if _text(row.binding_id)
                        )
                    ),
                    visit_ids=(protocol_id,),
                )
            )

    for protocol_id, protocol in sorted(protocol_by_id.items()):
        rows = bindings_by_protocol.get(protocol_id, [])
        if protocol.required and len(rows) != 1:
            findings.append(
                _finding(
                    "required_protocol_visit_binding_missing"
                    if not rows
                    else "required_protocol_visit_binding_not_unique",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "each required protocol visit needs exactly one crosswalk binding",
                    binding_ids=tuple(
                        sorted(
                            _text(row.binding_id)
                            for row in rows
                            if _text(row.binding_id)
                        )
                    ),
                    visit_ids=(protocol_id,),
                    locators=(protocol.source_locator,)
                    if protocol.source_locator
                    else (),
                )
            )

    for key, observed in sorted(observed_by_key.items()):
        binding_ids = tuple(sorted(set(observed_binding_ids.get(key, ()))))
        kind = _enum_text(observed.kind)
        if kind == ObservedVisitKind.SCHEDULED.value and not binding_ids:
            findings.append(
                _finding(
                    "scheduled_observed_visit_unbound",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "every observed scheduled listing visit must be classified in the protocol crosswalk",
                    locators=(observed.source_locator, key)
                    if observed.source_locator
                    else (key,),
                )
            )
        elif (
            kind
            in {
                ObservedVisitKind.UNSCHEDULED.value,
                ObservedVisitKind.WITHDRAWAL.value,
                ObservedVisitKind.NON_VISIT.value,
            }
            and binding_ids
        ):
            findings.append(
                _finding(
                    "special_observed_visit_cannot_satisfy_scheduled_visit",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "unplanned, withdrawal, and non-visit records cannot satisfy a scheduled protocol visit",
                    binding_ids=binding_ids,
                    locators=(observed.source_locator, key)
                    if observed.source_locator
                    else (key,),
                )
            )

    input_payload = {
        "protocol_source_sha256": protocol_hash,
        "listing_source_sha256": listing_hash,
        "protocol_visits": [
            _protocol_payload(item)
            for item in sorted(protocol_rows, key=_protocol_sort_key)
        ],
        "observed_visits": [
            _observed_payload(item)
            for item in sorted(observed_rows, key=_observed_sort_key)
        ],
        "bindings": [
            _binding_payload(item)
            for item in sorted(binding_rows, key=_binding_sort_key)
        ],
    }
    input_sha256 = _digest(input_payload)
    return VisitCrosswalkReport(
        schema_version=VISIT_CROSSWALK_SCHEMA_VERSION,
        status=_status_for(findings),
        activation_allowed=False,
        protocol_source_sha256=protocol_hash,
        listing_source_sha256=listing_hash,
        input_sha256=input_sha256,
        protocol_visit_count=len(protocol_rows),
        observed_visit_count=len(observed_rows),
        binding_count=len(binding_rows),
        findings=tuple(findings),
    )


def _validate_protocol_visit(
    visit: CrosswalkProtocolVisit,
    findings: list[VisitCrosswalkFinding],
) -> None:
    visit_id = _text(visit.visit_id)
    locator = _text(visit.source_locator)
    if not _text(visit.label):
        findings.append(
            _finding(
                "protocol_visit_label_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "protocol visit label is required",
                visit_ids=(visit_id,) if visit_id else (),
                locators=(locator,) if locator else (),
            )
        )
    if not locator:
        findings.append(
            _finding(
                "protocol_visit_locator_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "protocol visit must retain a source locator",
                visit_ids=(visit_id,) if visit_id else (),
            )
        )
    for name in ("anchor_day", "window_before_days", "window_after_days"):
        value = getattr(visit, name)
        if not _finite_number(value):
            findings.append(
                _finding(
                    "protocol_visit_day_invalid",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    f"protocol visit {name} must be a finite number",
                    visit_ids=(visit_id,) if visit_id else (),
                    locators=(locator,) if locator else (),
                )
            )
        elif name != "anchor_day" and value < 0:
            findings.append(
                _finding(
                    "protocol_visit_window_invalid",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    f"protocol visit {name} cannot be negative",
                    visit_ids=(visit_id,) if visit_id else (),
                    locators=(locator,) if locator else (),
                )
            )
    if not isinstance(visit.required, bool):
        findings.append(
            _finding(
                "protocol_visit_required_invalid",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "protocol visit required must be a strict boolean",
                visit_ids=(visit_id,) if visit_id else (),
                locators=(locator,) if locator else (),
            )
        )


def _validate_observed_visit(
    observed: CrosswalkObservedVisit,
    findings: list[VisitCrosswalkFinding],
) -> None:
    key = observed.key
    if not _text(observed.listing_visit_id) or not _text(observed.listing_label):
        findings.append(
            _finding(
                "observed_visit_identity_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "listing visit identity requires both an OID and a display label",
                locators=(observed.source_locator,) if observed.source_locator else (),
            )
        )
    if not _text(observed.source_locator):
        findings.append(
            _finding(
                "observed_visit_locator_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "observed listing visit must retain a source locator",
                locators=(key,),
            )
        )
    if (
        not isinstance(observed.row_count, int)
        or isinstance(observed.row_count, bool)
        or observed.row_count < 0
    ):
        findings.append(
            _finding(
                "observed_visit_row_count_invalid",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "observed listing visit row_count must be a non-negative integer",
                locators=(observed.source_locator,)
                if observed.source_locator
                else (key,),
            )
        )
    kind = _enum_text(observed.kind)
    if kind not in {item.value for item in ObservedVisitKind}:
        findings.append(
            _finding(
                "observed_visit_kind_invalid",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "observed listing visit kind is not supported",
                locators=(observed.source_locator,)
                if observed.source_locator
                else (key,),
            )
        )


def _validate_binding(
    binding: VisitCrosswalkBinding,
    *,
    protocol_by_id: Mapping[str, CrosswalkProtocolVisit],
    observed_by_key: Mapping[str, CrosswalkObservedVisit],
    findings: list[VisitCrosswalkFinding],
) -> None:
    binding_id = _text(binding.binding_id)
    protocol_id = _text(binding.protocol_visit_id)
    binding_ids = (binding_id,) if binding_id else ()
    if not binding_id:
        findings.append(
            _finding(
                "binding_id_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "crosswalk binding requires a stable binding_id",
                visit_ids=(protocol_id,) if protocol_id else (),
            )
        )
    if protocol_id not in protocol_by_id:
        findings.append(
            _finding(
                "binding_protocol_visit_unknown",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "crosswalk binding references an unknown protocol visit",
                binding_ids=binding_ids,
                visit_ids=(protocol_id,) if protocol_id else (),
            )
        )
        protocol = None
    else:
        protocol = protocol_by_id[protocol_id]
    if not _text(binding.source_locator):
        findings.append(
            _finding(
                "binding_locator_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "crosswalk binding must retain a reviewer/source locator",
                binding_ids=binding_ids,
            )
        )
    state = _enum_text(binding.state)
    if state not in {item.value for item in VisitCrosswalkBindingState}:
        findings.append(
            _finding(
                "binding_state_invalid",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "crosswalk binding state is not supported",
                binding_ids=binding_ids,
            )
        )
        return
    observed_keys = tuple(_text(item) for item in binding.observed_visit_keys)
    if len(observed_keys) != len(set(observed_keys)):
        findings.append(
            _finding(
                "binding_observed_visit_duplicate",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "a binding cannot repeat an observed visit identity pair",
                binding_ids=binding_ids,
            )
        )
    if state == VisitCrosswalkBindingState.MISSING.value and observed_keys:
        findings.append(
            _finding(
                "missing_binding_has_observed_visit",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "a missing binding cannot contain observed visit keys",
                binding_ids=binding_ids,
            )
        )
    if state != VisitCrosswalkBindingState.MISSING.value and not observed_keys:
        findings.append(
            _finding(
                "resolved_binding_observed_visit_missing",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "a resolved crosswalk binding must reference an observed visit",
                binding_ids=binding_ids,
            )
        )
    if state in {
        VisitCrosswalkBindingState.MISSING.value,
        VisitCrosswalkBindingState.AMBIGUOUS.value,
        VisitCrosswalkBindingState.CONFLICT.value,
    }:
        findings.append(
            _finding(
                "binding_unresolved",
                VisitCrosswalkFindingSeverity.BLOCKER,
                "missing, ambiguous, and conflicting bindings fail closed",
                binding_ids=binding_ids,
                visit_ids=(protocol_id,) if protocol_id else (),
                locators=(binding.source_locator,) if binding.source_locator else (),
            )
        )
    if state == VisitCrosswalkBindingState.DERIVED.value:
        if not _text(binding.rationale):
            findings.append(
                _finding(
                    "derived_binding_rationale_missing",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "derived binding requires a rationale before review",
                    binding_ids=binding_ids,
                )
            )
        else:
            findings.append(
                _finding(
                    "derived_binding_review",
                    VisitCrosswalkFindingSeverity.REVIEW_REQUIRED,
                    "derived binding requires reviewer confirmation",
                    binding_ids=binding_ids,
                    visit_ids=(protocol_id,) if protocol_id else (),
                )
            )
    if protocol is None:
        return

    for key in observed_keys:
        observed = observed_by_key.get(key)
        if observed is None:
            findings.append(
                _finding(
                    "binding_observed_visit_unknown",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "crosswalk binding references an unknown observed visit",
                    binding_ids=binding_ids,
                    locators=(key,),
                )
            )
            continue
        observed_kind = _enum_text(observed.kind)
        if observed_kind != ObservedVisitKind.SCHEDULED.value:
            findings.append(
                _finding(
                    "special_observed_visit_cannot_bind_protocol",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "only scheduled observed visits may bind a scheduled protocol visit",
                    binding_ids=binding_ids,
                    visit_ids=(protocol_id,),
                    locators=(observed.source_locator, key)
                    if observed.source_locator
                    else (key,),
                )
            )
        if protocol.label != observed.listing_label:
            findings.append(
                _finding(
                    "listing_visit_label_conflict",
                    VisitCrosswalkFindingSeverity.BLOCKER,
                    "listing visit label must match the protocol label in an explicit crosswalk",
                    binding_ids=binding_ids,
                    visit_ids=(protocol_id,),
                    locators=(protocol.source_locator, observed.source_locator),
                )
            )
        if protocol.visit_id != observed.listing_visit_id:
            code = (
                "listing_visit_oid_ordinal_review"
                if state == VisitCrosswalkBindingState.LABEL_MATCH.value
                else "listing_visit_oid_conflict"
            )
            severity = (
                VisitCrosswalkFindingSeverity.REVIEW_REQUIRED
                if code.endswith("review")
                else VisitCrosswalkFindingSeverity.BLOCKER
            )
            findings.append(
                _finding(
                    code,
                    severity,
                    "listing visit OID differs from protocol visit ID; do not silently renumber",
                    binding_ids=binding_ids,
                    visit_ids=(protocol_id,),
                    locators=(protocol.source_locator, observed.source_locator),
                )
            )
        if protocol.arm_scope and observed.arm_scope:
            if not _scope_overlap(protocol.arm_scope, observed.arm_scope):
                findings.append(
                    _finding(
                        "visit_arm_scope_conflict",
                        VisitCrosswalkFindingSeverity.BLOCKER,
                        "protocol and listing visit arm scopes do not overlap",
                        binding_ids=binding_ids,
                        visit_ids=(protocol_id,),
                        locators=(protocol.source_locator, observed.source_locator),
                    )
                )
        elif protocol.arm_scope and not observed.arm_scope:
            findings.append(
                _finding(
                    "visit_arm_scope_unverified",
                    VisitCrosswalkFindingSeverity.REVIEW_REQUIRED,
                    "treatment-specific protocol visit lacks observed arm scope evidence",
                    binding_ids=binding_ids,
                    visit_ids=(protocol_id,),
                    locators=(protocol.source_locator, observed.source_locator),
                )
            )


def _normalise_hash(
    value: Any, name: str, findings: list[VisitCrosswalkFinding]
) -> str:
    text = _text(value)
    if not _SHA256_RE.fullmatch(text):
        findings.append(
            _finding(
                "source_hash_invalid",
                VisitCrosswalkFindingSeverity.BLOCKER,
                f"{name} must be a lowercase SHA-256",
            )
        )
    return text


def _status_for(findings: Iterable[VisitCrosswalkFinding]) -> VisitCrosswalkStatus:
    values = tuple(findings)
    if any(item.severity is VisitCrosswalkFindingSeverity.BLOCKER for item in values):
        return VisitCrosswalkStatus.BLOCKED
    if any(
        item.severity is VisitCrosswalkFindingSeverity.REVIEW_REQUIRED
        for item in values
    ):
        return VisitCrosswalkStatus.REVIEW_REQUIRED
    return VisitCrosswalkStatus.PASSED


def _finding(
    code: str,
    severity: VisitCrosswalkFindingSeverity,
    summary: str,
    *,
    binding_ids: tuple[str, ...] = (),
    visit_ids: tuple[str, ...] = (),
    locators: tuple[str, ...] = (),
) -> VisitCrosswalkFinding:
    return VisitCrosswalkFinding(
        code=code,
        severity=severity,
        summary=summary,
        binding_ids=tuple(
            sorted(set(_text(item) for item in binding_ids if _text(item)))
        ),
        visit_ids=tuple(sorted(set(_text(item) for item in visit_ids if _text(item)))),
        locators=tuple(sorted(set(_text(item) for item in locators if _text(item)))),
    )


def _finding_sort_key(item: VisitCrosswalkFinding) -> tuple[Any, ...]:
    return (
        item.code,
        item.severity.value,
        item.binding_ids,
        item.visit_ids,
        item.locators,
    )


def _protocol_sort_key(item: CrosswalkProtocolVisit) -> tuple[Any, ...]:
    return (_text(item.visit_id), _text(item.label), _text(item.source_locator))


def _observed_sort_key(item: CrosswalkObservedVisit) -> tuple[Any, ...]:
    return (item.key, _enum_text(item.kind), _text(item.source_locator))


def _binding_sort_key(item: VisitCrosswalkBinding) -> tuple[Any, ...]:
    return (_text(item.binding_id), _text(item.protocol_visit_id))


def _protocol_payload(item: CrosswalkProtocolVisit) -> dict[str, Any]:
    return {
        "visit_id": _text(item.visit_id),
        "label": _text(item.label),
        "anchor_day": item.anchor_day,
        "window_before_days": item.window_before_days,
        "window_after_days": item.window_after_days,
        "source_locator": _text(item.source_locator),
        "arm_scope": list(_scope(item.arm_scope)),
        "required": item.required,
    }


def _observed_payload(item: CrosswalkObservedVisit) -> dict[str, Any]:
    return {
        "listing_visit_id": _text(item.listing_visit_id),
        "listing_label": _text(item.listing_label),
        "source_locator": _text(item.source_locator),
        "row_count": item.row_count,
        "kind": _enum_text(item.kind),
        "arm_scope": list(_scope(item.arm_scope)),
        "key": item.key,
    }


def _binding_payload(item: VisitCrosswalkBinding) -> dict[str, Any]:
    return {
        "binding_id": _text(item.binding_id),
        "protocol_visit_id": _text(item.protocol_visit_id),
        "observed_visit_keys": sorted(
            set(_text(value) for value in item.observed_visit_keys if _text(value))
        ),
        "state": _enum_text(item.state),
        "source_locator": _text(item.source_locator),
        "rationale": _text(item.rationale),
    }


def _observed_key(
    listing_visit_id: Any, listing_label: Any, arm_scope: Iterable[str]
) -> str:
    return "|".join(
        (
            _text(listing_visit_id),
            _text(listing_label),
            ",".join(_scope(arm_scope)),
        )
    )


def _scope(value: Iterable[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        value = (value,)
    return tuple(
        sorted(set(_text(item).casefold() for item in (value or ()) if _text(item)))
    )


def _scope_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    left_scope = set(_scope(left))
    right_scope = set(_scope(right))
    return not left_scope or not right_scope or bool(left_scope & right_scope)


def _enum_text(value: Any) -> str:
    return value.value if isinstance(value, Enum) else _text(value)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _digest(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(payload.encode("utf-8")).hexdigest()
