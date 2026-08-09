"""Conservative status derivation for persisted real-loop gate evidence.

The four existing revalidation artifacts do not share one payload shape.  This
module keeps their proof predicates explicit and refuses to infer a fifth
runtime-identity predicate before that artifact has a formal schema.  It only
parses already-loaded mappings; it does not read files or grant authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from .monitoring_real_loop_readiness import REAL_LOOP_UPSTREAM_GATE_NAMES
from .monitoring_real_loop_upstream_assembly import (
    REAL_LOOP_UPSTREAM_EVIDENCE_KINDS,
)


REAL_LOOP_DERIVED_STATUSES = {"proven", "blocked", "not_proven", "missing"}


class RealLoopStatusMappingError(ValueError):
    """Raised when a derived status result violates its structural contract."""


class RealLoopStatusMappingIssueCode(str, Enum):
    PAYLOAD_MISSING = "payload_missing"
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    FIELD_MISSING = "field_missing"
    FIELD_TYPE_INVALID = "field_type_invalid"
    STATUS_UNSUPPORTED = "status_unsupported"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    PROOF_INCOMPLETE = "proof_incomplete"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RealLoopStatusMappingError(
            "status-mapping evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RealLoopStatusMappingIssue:
    code: RealLoopStatusMappingIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise RealLoopStatusMappingError("status issue subject is required")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise RealLoopStatusMappingError("status issue detail is required")
        object.__setattr__(self, "subject", self.subject.strip())
        object.__setattr__(self, "detail", self.detail.strip())

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopStatusMappingResult:
    gate: str
    evidence_kind: str
    status: str
    reason: str
    issues: tuple[RealLoopStatusMappingIssue, ...] = ()
    payload_sha256: str = ""
    result_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.gate not in REAL_LOOP_UPSTREAM_GATE_NAMES:
            raise RealLoopStatusMappingError("status result gate is not canonical")
        if self.evidence_kind != REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[self.gate]:
            raise RealLoopStatusMappingError("status result evidence kind does not match gate")
        if self.status not in REAL_LOOP_DERIVED_STATUSES:
            raise RealLoopStatusMappingError("invalid derived status")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise RealLoopStatusMappingError("status result reason is required")
        issues = tuple(self.issues)
        if any(not isinstance(item, RealLoopStatusMappingIssue) for item in issues):
            raise RealLoopStatusMappingError("status result issues contain an invalid value")
        if self.status == "proven" and issues:
            raise RealLoopStatusMappingError("proven status cannot carry mapping issues")
        if self.payload_sha256 and (
            not isinstance(self.payload_sha256, str)
            or len(self.payload_sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.payload_sha256)
        ):
            raise RealLoopStatusMappingError("payload_sha256 must be lowercase SHA-256")
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "result_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "evidence_kind": self.evidence_kind,
            "status": self.status,
            "reason": self.reason,
            "issues": [issue.to_dict() for issue in self.issues],
            "payload_sha256": self.payload_sha256,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "result_sha256": self.result_sha256,
        }


def _issue(
    code: RealLoopStatusMappingIssueCode,
    subject: str,
    detail: str,
) -> RealLoopStatusMappingIssue:
    return RealLoopStatusMappingIssue(code, subject, detail)


def _invalid(
    gate: str,
    payload_sha256: str,
    issue: RealLoopStatusMappingIssue,
    reason: str,
) -> RealLoopStatusMappingResult:
    return RealLoopStatusMappingResult(
        gate=gate,
        evidence_kind=REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate],
        status="missing",
        reason=reason,
        issues=(issue,),
        payload_sha256=payload_sha256,
    )


def _strict_bool(
    mapping: Mapping[str, Any],
    key: str,
    gate: str,
    issues: list[RealLoopStatusMappingIssue],
) -> bool | None:
    if key not in mapping:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_MISSING,
                gate,
                f"required boolean field {key} is missing",
            )
        )
        return None
    value = mapping[key]
    if not isinstance(value, bool):
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_TYPE_INVALID,
                gate,
                f"{key} must be a strict boolean",
            )
        )
        return None
    return value


def _strict_nonnegative_int(
    mapping: Mapping[str, Any],
    key: str,
    gate: str,
    issues: list[RealLoopStatusMappingIssue],
) -> int | None:
    if key not in mapping:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_MISSING,
                gate,
                f"required integer field {key} is missing",
            )
        )
        return None
    value = mapping[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_TYPE_INVALID,
                gate,
                f"{key} must be a non-negative integer",
            )
        )
        return None
    return value


def _strict_list(
    mapping: Mapping[str, Any],
    key: str,
    gate: str,
    issues: list[RealLoopStatusMappingIssue],
) -> list[Any] | None:
    if key not in mapping:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_MISSING,
                gate,
                f"required array field {key} is missing",
            )
        )
        return None
    value = mapping[key]
    if not isinstance(value, list):
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_TYPE_INVALID,
                gate,
                f"{key} must be an array",
            )
        )
        return None
    return value


def _authority_flags_false(
    mapping: Mapping[str, Any],
    gate: str,
    issues: list[RealLoopStatusMappingIssue],
    names: tuple[str, ...],
) -> bool:
    values = [_strict_bool(mapping, name, gate, issues) for name in names]
    if any(value is True for value in values):
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.AUTHORITY_FLAG_TRUE,
                gate,
                "revalidation evidence cannot carry a true authority flag",
            )
        )
    return all(value is False for value in values)


def _result(
    gate: str,
    status: str,
    reason: str,
    issues: list[RealLoopStatusMappingIssue],
    payload_sha256: str,
) -> RealLoopStatusMappingResult:
    return RealLoopStatusMappingResult(
        gate=gate,
        evidence_kind=REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate],
        status=status,
        reason=reason,
        issues=tuple(issues),
        payload_sha256=payload_sha256,
    )


def _map_b6(payload: Mapping[str, Any], payload_sha256: str) -> RealLoopStatusMappingResult:
    gate = "b6_approved"
    nested = payload.get("gate")
    if not isinstance(nested, Mapping) or payload.get("read_only") is not True:
        return _invalid(
            gate,
            payload_sha256,
            _issue(
                RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
                gate,
                "B6 evidence requires a read_only payload and nested gate object",
            ),
            "B6 payload is not a supported review-gate shape",
        )
    issues: list[RealLoopStatusMappingIssue] = []
    migration_ready = _strict_bool(nested, "migration_ready", gate, issues)
    write_permitted = _strict_bool(nested, "write_permitted", gate, issues)
    migration_write_permitted = _strict_bool(
        payload, "migration_write_permitted", gate, issues
    )
    top_write_permitted = _strict_bool(payload, "write_permitted", gate, issues)
    if any(
        value is True
        for value in (write_permitted, migration_write_permitted, top_write_permitted)
    ):
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.AUTHORITY_FLAG_TRUE,
                gate,
                "B6 approval evidence cannot carry a true write authority flag",
            )
        )
    pending = _strict_list(nested, "pending_candidate_record_ids", gate, issues)
    rejected = _strict_list(nested, "rejected_candidate_record_ids", gate, issues)
    missing = _strict_list(nested, "missing_candidate_record_ids", gate, issues)
    blockers = _strict_list(nested, "unresolved_blockers", gate, issues)
    accepted = _strict_list(nested, "accepted_review_ids", gate, issues)
    candidate_count = _strict_nonnegative_int(nested, "candidate_count", gate, issues)
    outcome_count = _strict_nonnegative_int(nested, "outcome_count", gate, issues)
    status = nested.get("status")
    if not isinstance(status, str):
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_TYPE_INVALID,
                gate,
                "gate.status must be a string",
            )
        )
        status = ""
    if isinstance(status, str) and status not in {"pending_review", "approved"}:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.STATUS_UNSUPPORTED,
                gate,
                "supported B6 statuses are pending_review and approved",
            )
        )
    if issues:
        return _result(gate, "missing", "B6 payload failed strict shape checks", issues, payload_sha256)
    approved = (
        status == "approved"
        and migration_ready is True
        and write_permitted is False
        and migration_write_permitted is False
        and top_write_permitted is False
        and pending == []
        and rejected == []
        and missing == []
        and blockers == []
        and candidate_count is not None
        and candidate_count > 0
        and outcome_count == candidate_count
        and accepted is not None
        and len(accepted) == candidate_count
    )
    return _result(
        gate,
        "proven" if approved else "blocked",
        "B6 is fully approved only when every candidate has an accepted review and no blocker",
        [],
        payload_sha256,
    )


def _approved_input_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    observation = payload.get("current_package_observation")
    if isinstance(observation, Mapping):
        return observation
    report = payload.get("report")
    if isinstance(report, Mapping):
        return report
    if "approved_input_ready" in payload:
        return payload
    return None


def _map_approved_input(
    payload: Mapping[str, Any], payload_sha256: str
) -> RealLoopStatusMappingResult:
    gate = "approved_input_ready"
    nested = _approved_input_mapping(payload)
    if nested is None:
        return _invalid(
            gate,
            payload_sha256,
            _issue(
                RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
                gate,
                "approved-input evidence requires current_package_observation or report",
            ),
            "approved-input payload is not a supported shape",
        )
    issues: list[RealLoopStatusMappingIssue] = []
    status = nested.get("status")
    if status is not None and not isinstance(status, str):
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_TYPE_INVALID,
                gate,
                "approved-input status must be a string when present",
            )
        )
    if "issue_codes" in nested:
        # Persisted source-binding observation shape.
        ready = _strict_bool(nested, "approved_input_ready", gate, issues)
        source_complete = _strict_bool(
            nested, "source_batch_preflight_complete", gate, issues
        )
        write_permitted = _strict_bool(nested, "write_permitted", gate, issues)
        migration_ready = _strict_bool(nested, "migration_ready", gate, issues)
        issue_codes = _strict_list(nested, "issue_codes", gate, issues)
        proven = (
            ready is True
            and source_complete is True
            and issue_codes == []
            and write_permitted is False
            and migration_ready is False
            and (status is None or status == "ready")
        )
    elif "source_batch_preflight_complete" in nested:
        # Controlled approved-input wrapper shape.
        ready = _strict_bool(nested, "approved_input_ready", gate, issues)
        source_complete = _strict_bool(
            nested, "source_batch_preflight_complete", gate, issues
        )
        write_permitted = _strict_bool(nested, "write_permitted", gate, issues)
        migration_ready = _strict_bool(nested, "migration_ready", gate, issues)
        issue_rows = _strict_list(nested, "issues", gate, issues)
        base_report = nested.get("base_report")
        if not isinstance(base_report, Mapping):
            issues.append(
                _issue(
                    RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
                    gate,
                    "controlled approved-input wrapper requires base_report",
                )
            )
            base_ready = None
        else:
            base_ready = _strict_bool(base_report, "approved_input_ready", gate, issues)
        proven = (
            ready is True
            and base_ready is True
            and source_complete is True
            and issue_rows == []
            and write_permitted is False
            and migration_ready is False
            and status == "ready"
        )
    elif "source_manifest_replay_complete" in nested:
        # Base approved-input dry-run shape.
        ready = _strict_bool(nested, "approved_input_ready", gate, issues)
        source_flags = [
            _strict_bool(nested, name, gate, issues)
            for name in (
                "source_manifest_replay_complete",
                "reviewer_outcomes_complete",
                "source_lineage_complete",
                "aggregate_cas_complete",
                "residual_blockers_clear",
            )
        ]
        write_permitted = _strict_bool(nested, "write_permitted", gate, issues)
        migration_ready = _strict_bool(nested, "migration_ready", gate, issues)
        issue_rows = _strict_list(nested, "issues", gate, issues)
        proven = (
            ready is True
            and all(value is True for value in source_flags)
            and issue_rows == []
            and write_permitted is False
            and migration_ready is False
            and status == "ready"
        )
    else:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
                gate,
                "approved-input payload has no supported readiness shape",
            )
        )
        proven = False
    if issues:
        return _result(
            gate, "missing", "approved-input payload failed strict shape checks", issues, payload_sha256
        )
    return _result(
        gate,
        "proven" if proven else "blocked",
        "approved input requires blocker-free source preflight and no write authority",
        [],
        payload_sha256,
    )


def _map_source_token(
    payload: Mapping[str, Any], payload_sha256: str
) -> RealLoopStatusMappingResult:
    gate = "source_token_revalidated"
    nested = payload.get("report")
    if not isinstance(nested, Mapping):
        return _invalid(
            gate,
            payload_sha256,
            _issue(
                RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
                gate,
                "source-token evidence requires a report object",
            ),
            "source-token payload is not a supported revalidation shape",
        )
    issues: list[RealLoopStatusMappingIssue] = []
    status = nested.get("status")
    source_status = nested.get("source_token_revalidation_status")
    if not isinstance(status, str) or not isinstance(source_status, str):
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.FIELD_TYPE_INVALID,
                gate,
                "source-token report/status fields must be strings",
            )
        )
    if isinstance(status, str) and status not in {"fresh", "blocked"}:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.STATUS_UNSUPPORTED,
                gate,
                "source-token report status must be fresh or blocked",
            )
        )
    if isinstance(source_status, str) and source_status not in {
        "proven",
        "not_proven",
        "unknown",
    }:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.STATUS_UNSUPPORTED,
                gate,
                "source-token revalidation status is outside its conservative vocabulary",
            )
        )
    evidence_fresh = _strict_bool(nested, "evidence_fresh", gate, issues)
    synthesized = _strict_bool(nested, "source_token_synthesized", gate, issues)
    issue_count = _strict_nonnegative_int(nested, "issue_count", gate, issues)
    issue_rows = _strict_list(nested, "issues", gate, issues)
    read_only = _strict_bool(nested, "read_only", gate, issues)
    authority_ok = _authority_flags_false(
        nested,
        gate,
        issues,
        (
            "authority_granted",
            "medical_authority_granted",
            "migration_ready",
            "provider_permitted",
            "runtime_write_permitted",
            "write_permitted",
            "release_ready",
        ),
    )
    if read_only is not True:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.PROOF_INCOMPLETE,
                gate,
                "source-token revalidation must remain read_only",
            )
        )
    if issues:
        return _result(gate, "missing", "source-token payload failed strict shape checks", issues, payload_sha256)
    proven = (
        status == "fresh"
        and source_status == "proven"
        and evidence_fresh is True
        and synthesized is False
        and issue_count == 0
        and issue_rows == []
        and authority_ok
    )
    if proven:
        return _result(gate, "proven", "source-token content revalidation is fresh and proven", [], payload_sha256)
    return _result(
        gate,
        "not_proven",
        "freshness does not prove the legacy source token; content status remains unresolved",
        [],
        payload_sha256,
    )


def _map_aggregate_cas(
    payload: Mapping[str, Any], payload_sha256: str
) -> RealLoopStatusMappingResult:
    gate = "aggregate_cas_complete"
    nested = payload.get("report")
    if not isinstance(nested, Mapping):
        return _invalid(
            gate,
            payload_sha256,
            _issue(
                RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
                gate,
                "aggregate/CAS evidence requires a report object",
            ),
            "aggregate/CAS payload is not a supported revalidation shape",
        )
    issues: list[RealLoopStatusMappingIssue] = []
    status = nested.get("status")
    if not isinstance(status, str) or status not in {"fresh", "blocked"}:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.STATUS_UNSUPPORTED,
                gate,
                "aggregate/CAS report status must be fresh or blocked",
            )
        )
    evidence_fresh = _strict_bool(nested, "evidence_fresh", gate, issues)
    artifact_valid = _strict_bool(nested, "artifact_payload_valid", gate, issues)
    source_valid = _strict_bool(nested, "source_payload_valid", gate, issues)
    replay_matches = _strict_bool(nested, "replay_report_matches", gate, issues)
    metadata_complete = _strict_bool(nested, "metadata_chain_complete", gate, issues)
    cas_complete = _strict_bool(nested, "cas_replay_complete", gate, issues)
    issue_count = _strict_nonnegative_int(nested, "issue_count", gate, issues)
    replay_issue_count = _strict_nonnegative_int(nested, "replay_issue_count", gate, issues)
    issue_rows = _strict_list(nested, "issues", gate, issues)
    read_only = _strict_bool(nested, "read_only", gate, issues)
    authority_ok = _authority_flags_false(
        nested,
        gate,
        issues,
        (
            "authority_granted",
            "medical_authority_granted",
            "migration_ready",
            "aggregate_write_permitted",
            "runtime_write_permitted",
            "release_ready",
        ),
    )
    if read_only is not True:
        issues.append(
            _issue(
                RealLoopStatusMappingIssueCode.PROOF_INCOMPLETE,
                gate,
                "aggregate/CAS revalidation must remain read_only",
            )
        )
    if issues:
        return _result(gate, "missing", "aggregate/CAS payload failed strict shape checks", issues, payload_sha256)
    proven = (
        status == "fresh"
        and evidence_fresh is True
        and artifact_valid is True
        and source_valid is True
        and replay_matches is True
        and metadata_complete is True
        and cas_complete is True
        and issue_count == 0
        and replay_issue_count == 0
        and issue_rows == []
        and authority_ok
    )
    return _result(
        gate,
        "proven" if proven else "blocked",
        "aggregate/CAS requires a fresh, complete replay with zero replay issues and no authority",
        [],
        payload_sha256,
    )


def derive_real_loop_upstream_status(
    gate: str,
    payload: Mapping[str, Any] | None,
    *,
    payload_sha256: str = "",
) -> RealLoopStatusMappingResult:
    """Derive one conservative status from a loaded revalidation payload.

    Runtime identity deliberately returns ``missing`` until its persisted
    evidence schema is specified; a generic ``verified`` boolean is not enough.
    """

    if gate not in REAL_LOOP_UPSTREAM_GATE_NAMES:
        raise RealLoopStatusMappingError("gate is outside the canonical upstream set")
    if payload_sha256 and (
        not isinstance(payload_sha256, str)
        or len(payload_sha256) != 64
        or any(char not in "0123456789abcdef" for char in payload_sha256)
    ):
        raise RealLoopStatusMappingError("payload_sha256 must be lowercase SHA-256")
    if payload is None:
        return _invalid(
            gate,
            payload_sha256,
            _issue(
                RealLoopStatusMappingIssueCode.PAYLOAD_MISSING,
                gate,
                "no revalidation payload was supplied",
            ),
            "upstream evidence payload is missing",
        )
    if not isinstance(payload, Mapping):
        return _invalid(
            gate,
            payload_sha256,
            _issue(
                RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
                gate,
                "revalidation payload must be an object mapping",
            ),
            "upstream evidence payload has an invalid shape",
        )
    if gate == "b6_approved":
        return _map_b6(payload, payload_sha256)
    if gate == "approved_input_ready":
        return _map_approved_input(payload, payload_sha256)
    if gate == "source_token_revalidated":
        return _map_source_token(payload, payload_sha256)
    if gate == "aggregate_cas_complete":
        return _map_aggregate_cas(payload, payload_sha256)
    # No persisted runtime-identity evidence contract exists yet.  Do not let a
    # generic client-provided ``verified`` field become a real-loop prerequisite.
    return _invalid(
        gate,
        payload_sha256,
        _issue(
            RealLoopStatusMappingIssueCode.PAYLOAD_SHAPE_INVALID,
            gate,
            "runtime identity has no formal persisted revalidation schema",
        ),
        "runtime identity status remains missing until its evidence schema is defined",
    )


__all__ = [
    "REAL_LOOP_DERIVED_STATUSES",
    "RealLoopStatusMappingError",
    "RealLoopStatusMappingIssue",
    "RealLoopStatusMappingIssueCode",
    "RealLoopStatusMappingResult",
    "derive_real_loop_upstream_status",
]
