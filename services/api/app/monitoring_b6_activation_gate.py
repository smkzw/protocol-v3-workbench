"""Bind the actual B6 review gate to the blocked C13 activation route."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

from .monitoring_adapter_consumer_coverage import StudyAdapterConsumerCoverageError


class B6ActivationGateError(StudyAdapterConsumerCoverageError):
    """Raised when B6 authority evidence cannot safely gate activation."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise B6ActivationGateError("B6 gate payload must be JSON-serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _required(value: Any, field_name: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise B6ActivationGateError(f"{field_name} is required")
    return text


def _unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    result = tuple(_required(value, f"{field_name} item") for value in values)
    if len(result) != len(set(result)):
        raise B6ActivationGateError(f"{field_name} must not repeat")
    return result


def _strict_nonnegative_int(value: Any, field_name: str) -> int:
    """Accept only an explicit JSON integer for a gate count.

    B6 evidence is authority-bearing input.  Coercing ``True``, numeric
    strings, or floats would let malformed evidence pass the pending-review
    gate with a different count than the source artifact actually carries.
    """

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise B6ActivationGateError(f"{field_name} must be a non-negative integer")
    return value


def _strict_string_sequence(value: Any, field_name: str) -> tuple[str, ...]:
    """Require a JSON array of non-empty strings; never iterate a scalar."""

    if not isinstance(value, (list, tuple)):
        raise B6ActivationGateError(f"{field_name} must be a string array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise B6ActivationGateError(f"{field_name} must contain non-empty strings")
    return tuple(value)


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    """Require a JSON array of objects so malformed C13 evidence fails deterministically."""

    if not isinstance(value, (list, tuple)):
        raise B6ActivationGateError(f"{field_name} must be an object array")
    rows = tuple(value)
    if any(not isinstance(item, Mapping) for item in rows):
        raise B6ActivationGateError(f"{field_name} must contain only objects")
    return rows


def _verify_content_hash(payload: Mapping[str, Any], field_name: str) -> str:
    """Verify a report's self-hash over the payload without the hash field."""

    declared = payload.get("report_content_sha256")
    if not isinstance(declared, str) or len(declared) != 64:
        raise B6ActivationGateError(f"{field_name} must be a lowercase SHA-256")
    unhashed = {key: value for key, value in payload.items() if key != "report_content_sha256"}
    if _digest(unhashed) != declared:
        raise B6ActivationGateError(f"{field_name} does not match report content")
    return declared


@dataclass(frozen=True)
class B6ActivationGateReport:
    """Current authority gate that blocks C13 activation."""

    b6_evidence_sha256: str
    c13_report_content_sha256: str
    b6_status: str
    migration_ready: bool
    write_permitted: bool
    migration_write_permitted: bool
    candidate_count: int
    outcome_count: int
    missing_candidate_record_ids: tuple[str, ...]
    rejected_candidate_record_ids: tuple[str, ...]
    pending_candidate_record_ids: tuple[str, ...]
    unresolved_blockers: tuple[str, ...]
    accepted_review_ids: tuple[str, ...]
    c13_row_count: int
    c13_blocked_row_count: int
    status: str = "blocked_pending_b6_review"
    review_required: bool = True
    activation_allowed: bool = False
    event_creation_allowed: bool = False
    projection_allowed: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("b6_evidence_sha256", "c13_report_content_sha256", "b6_status", "status"):
            object.__setattr__(self, name, _required(getattr(self, name), f"b6_gate.{name}"))
        for name in (
            "migration_ready",
            "write_permitted",
            "migration_write_permitted",
            "review_required",
            "activation_allowed",
            "event_creation_allowed",
            "projection_allowed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise B6ActivationGateError(f"b6_gate.{name} must be boolean")
        if self.b6_status != "pending_review":
            raise B6ActivationGateError("B6 gate must remain pending_review until review is fully resolved")
        if self.status != "blocked_pending_b6_review":
            raise B6ActivationGateError("B6 activation gate cannot claim readiness")
        if not self.review_required:
            raise B6ActivationGateError("B6 gate must require explicit review")
        if self.migration_ready or self.write_permitted or self.migration_write_permitted:
            raise B6ActivationGateError("B6 pending gate cannot permit migration or writes")
        if self.activation_allowed or self.event_creation_allowed or self.projection_allowed:
            raise B6ActivationGateError("B6 gate must block activation and projections")
        candidate_count = _strict_nonnegative_int(
            self.candidate_count, "B6 candidate_count"
        )
        outcome_count = _strict_nonnegative_int(
            self.outcome_count, "B6 outcome_count"
        )
        c13_row_count = _strict_nonnegative_int(
            self.c13_row_count, "C13 row count"
        )
        c13_blocked_row_count = _strict_nonnegative_int(
            self.c13_blocked_row_count, "C13 blocked row count"
        )
        if candidate_count <= 0:
            raise B6ActivationGateError("B6 candidate_count must be positive")
        missing = _unique(self.missing_candidate_record_ids, "b6_gate.missing_candidate_record_ids")
        rejected = _unique(self.rejected_candidate_record_ids, "b6_gate.rejected_candidate_record_ids")
        pending = _unique(self.pending_candidate_record_ids, "b6_gate.pending_candidate_record_ids")
        blockers = _unique(self.unresolved_blockers, "b6_gate.unresolved_blockers")
        accepted = _unique(self.accepted_review_ids, "b6_gate.accepted_review_ids")
        if outcome_count > candidate_count:
            raise B6ActivationGateError("B6 outcome_count cannot exceed candidate_count")
        if len(set(missing) & set(rejected + pending)):
            raise B6ActivationGateError("B6 candidate outcome categories must not overlap")
        if len(missing) + len(rejected) + len(pending) + len(accepted) != candidate_count:
            raise B6ActivationGateError("B6 candidate/outcome categories do not cover every candidate")
        if outcome_count != candidate_count - len(missing):
            raise B6ActivationGateError("B6 outcome_count does not match missing candidate records")
        if not blockers or (not missing and not rejected and not pending and not accepted):
            raise B6ActivationGateError("B6 candidate/outcome/blocker counts do not prove pending review")
        if c13_row_count <= 0:
            raise B6ActivationGateError("C13 row count must be positive")
        if c13_blocked_row_count != c13_row_count:
            raise B6ActivationGateError("C13 rows must all remain blocked")
        object.__setattr__(self, "missing_candidate_record_ids", missing)
        object.__setattr__(self, "rejected_candidate_record_ids", rejected)
        object.__setattr__(self, "pending_candidate_record_ids", pending)
        object.__setattr__(self, "unresolved_blockers", blockers)
        object.__setattr__(self, "accepted_review_ids", accepted)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "b6_evidence_sha256": self.b6_evidence_sha256,
            "c13_report_content_sha256": self.c13_report_content_sha256,
            "b6_status": self.b6_status,
            "migration_ready": self.migration_ready,
            "write_permitted": self.write_permitted,
            "migration_write_permitted": self.migration_write_permitted,
            "candidate_count": self.candidate_count,
            "outcome_count": self.outcome_count,
            "missing_candidate_record_ids": list(self.missing_candidate_record_ids),
            "rejected_candidate_record_ids": list(self.rejected_candidate_record_ids),
            "pending_candidate_record_ids": list(self.pending_candidate_record_ids),
            "unresolved_blockers": list(self.unresolved_blockers),
            "accepted_review_ids": list(self.accepted_review_ids),
            "c13_row_count": self.c13_row_count,
            "c13_blocked_row_count": self.c13_blocked_row_count,
            "status": self.status,
            "review_required": self.review_required,
            "activation_allowed": self.activation_allowed,
            "event_creation_allowed": self.event_creation_allowed,
            "projection_allowed": self.projection_allowed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def build_b6_activation_gate_report(
    b6_payload: Mapping[str, Any],
    c13_payload: Mapping[str, Any],
    *,
    b6_evidence_sha256: str,
) -> B6ActivationGateReport:
    """Validate the current B6 artifact and bind it to C13 blocked rows."""

    if not isinstance(b6_payload, Mapping):
        raise B6ActivationGateError("B6 payload must be an object")
    if not isinstance(c13_payload, Mapping):
        raise B6ActivationGateError("C13 payload must be an object")
    gate = b6_payload.get("gate")
    if not isinstance(gate, Mapping):
        raise B6ActivationGateError("B6 payload must contain a gate object")
    if b6_payload.get("read_only") is not True:
        raise B6ActivationGateError("B6 evidence must remain read_only")
    if c13_payload.get("schema_only") is not True or c13_payload.get("activation_allowed") is not False:
        raise B6ActivationGateError("C13 evidence must remain schema-only and inactive")
    c13_report_content_sha256 = _verify_content_hash(
        c13_payload, "C13 report_content_sha256"
    )
    for name in ("migration_ready", "write_permitted"):
        if not isinstance(gate.get(name), bool):
            raise B6ActivationGateError(f"B6 gate {name} must be boolean")
    if not isinstance(b6_payload.get("migration_write_permitted"), bool):
        raise B6ActivationGateError("B6 gate migration_write_permitted must be boolean")
    candidate_count = _strict_nonnegative_int(
        gate.get("candidate_count"), "B6 gate candidate_count"
    )
    outcome_count = _strict_nonnegative_int(
        gate.get("outcome_count"), "B6 gate outcome_count"
    )
    reports = _mapping_sequence(c13_payload.get("reports"), "C13 reports")
    rows: list[Mapping[str, Any]] = []
    for index, report in enumerate(reports):
        rows.extend(
            _mapping_sequence(report.get("rows"), f"C13 reports[{index}].rows")
        )
    if not rows:
        raise B6ActivationGateError("C13 evidence must contain blocked rows")
    for row in rows:
        if (
            row.get("status") != "blocked_pending_approval"
            or row.get("event_creation_allowed") is not False
            or row.get("projection_allowed") is not False
            or row.get("activation_allowed") is not False
        ):
            raise B6ActivationGateError("C13 contains a non-blocked activation row")
    report = B6ActivationGateReport(
        b6_evidence_sha256=_required(b6_evidence_sha256, "b6_evidence_sha256"),
        c13_report_content_sha256=c13_report_content_sha256,
        b6_status=str(gate.get("status", "")),
        migration_ready=gate["migration_ready"],
        write_permitted=gate["write_permitted"],
        migration_write_permitted=b6_payload["migration_write_permitted"],
        candidate_count=candidate_count,
        outcome_count=outcome_count,
        missing_candidate_record_ids=_strict_string_sequence(
            gate.get("missing_candidate_record_ids", ()),
            "B6 gate missing_candidate_record_ids",
        ),
        rejected_candidate_record_ids=_strict_string_sequence(
            gate.get("rejected_candidate_record_ids", ()),
            "B6 gate rejected_candidate_record_ids",
        ),
        pending_candidate_record_ids=_strict_string_sequence(
            gate.get("pending_candidate_record_ids", ()),
            "B6 gate pending_candidate_record_ids",
        ),
        unresolved_blockers=_strict_string_sequence(
            gate.get("unresolved_blockers", ()),
            "B6 gate unresolved_blockers",
        ),
        accepted_review_ids=_strict_string_sequence(
            gate.get("accepted_review_ids", ()),
            "B6 gate accepted_review_ids",
        ),
        c13_row_count=len(rows),
        c13_blocked_row_count=sum(row.get("status") == "blocked_pending_approval" for row in rows),
    )
    return report


__all__ = [
    "B6ActivationGateError",
    "B6ActivationGateReport",
    "build_b6_activation_gate_report",
]
