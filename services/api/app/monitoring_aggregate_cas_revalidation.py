"""Read-only revalidation of persisted aggregate/CAS replay evidence.

The B4 aggregate/CAS artifact is a derived diagnostic record.  This boundary
reopens both that artifact and its declared B4 source package, reconstructs the
canonical event cases, and reruns the in-memory replay contract.  Freshness of
the evidence is deliberately separate from ``cas_replay_complete``: a fresh
record may still prove that the historical CAS sequence is incomplete.  No
aggregate is written, no version is inferred, and no authority is granted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .monitoring_aggregate_cas_replay import (
    MonitoringAggregateCasCase,
    MonitoringAggregateCasEvent,
    MonitoringAggregateCasReplayError,
    build_monitoring_aggregate_cas_replay_report,
)


MONITORING_AGGREGATE_CAS_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_aggregate_cas_revalidation_v1"
)
AGGREGATE_CAS_REPLAY_ARTIFACT_KEYS = {
    "input_path",
    "input_sha256",
    "input_decision_count",
    "distinct_aggregate_cases",
    "expected_version_source_field",
    "read_only",
    "aggregate_write_permitted",
    "migration_ready",
    "metadata_chain_complete",
    "cas_replay_complete",
    "issue_count",
    "replays",
    "report_sha256",
}
SOURCE_DECISION_KEYS = {
    "approved",
    "basis",
    "confidence",
    "current_expected_source_version",
    "current_risk_id",
    "current_risk_instance_id",
    "current_risk_key",
    "current_site_id",
    "current_source_revision",
    "current_subject_id",
    "decision_status",
    "disposition_chain",
    "disposition_record_id",
    "legacy_risk_id",
    "legacy_risk_instance_id",
    "legacy_risk_key",
    "legacy_source_revision_candidates",
    "legacy_source_version",
    "project_id",
    "residual_blockers",
    "review_note",
    "review_required",
    "source_version_relation",
    "write_permitted",
}
SOURCE_CHAIN_KEYS = {
    "record_id",
    "previous_state",
    "new_state",
    "created_at",
    "expected_version",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MonitoringAggregateCasRevalidationError(ValueError):
    """Raised when a revalidation request cannot be evaluated safely."""


class MonitoringAggregateCasRevalidationIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    ARTIFACT_FIELD_INVALID = "artifact_field_invalid"
    ARTIFACT_REPORT_MISSING = "artifact_report_missing"
    ARTIFACT_REPORT_MISMATCH = "artifact_report_mismatch"
    ARTIFACT_SCHEMA_INVALID = "artifact_schema_invalid"
    AUTHORITY_FLAG_MISSING = "authority_flag_missing"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    SOURCE_PAYLOAD_INVALID = "source_payload_invalid"
    SOURCE_AUTHORITY_FLAG_MISSING = "source_authority_flag_missing"
    SOURCE_AUTHORITY_FLAG_TRUE = "source_authority_flag_true"
    SOURCE_DECISION_COUNT_MISMATCH = "source_decision_count_mismatch"
    SOURCE_DECISION_INVALID = "source_decision_invalid"
    SOURCE_CHAIN_INVALID = "source_chain_invalid"
    SOURCE_CHAIN_CONFLICT = "source_chain_conflict"
    CASE_RECONSTRUCTION_FAILED = "case_reconstruction_failed"
    REPORT_REPLAY_MISMATCH = "report_replay_mismatch"
    FILE_PATH_UNSAFE = "file_path_unsafe"
    FILE_MISSING = "file_missing"
    FILE_NOT_REGULAR = "file_not_regular"
    FILE_SYMLINK_UNSUPPORTED = "file_symlink_unsupported"
    FILE_BYTES_MISMATCH = "file_bytes_mismatch"
    FILE_SHA256_MISMATCH = "file_sha256_mismatch"
    FILE_JSON_INVALID = "file_json_invalid"
    SOURCE_PATH_MISMATCH = "source_path_mismatch"
    SOURCE_FILE_BYTES_MISMATCH = "source_file_bytes_mismatch"
    SOURCE_FILE_SHA256_MISMATCH = "source_file_sha256_mismatch"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringAggregateCasRevalidationError(
            "aggregate/CAS evidence must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


@dataclass(frozen=True)
class MonitoringAggregateCasRevalidationIssue:
    code: MonitoringAggregateCasRevalidationIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise MonitoringAggregateCasRevalidationError(
                "revalidation issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class MonitoringAggregateCasRevalidationReport:
    """Evidence-freshness result; every write/authority flag stays false."""

    status: str
    evidence_fresh: bool
    artifact_payload_valid: bool
    source_payload_valid: bool
    replay_report_matches: bool
    artifact_file_checked: bool
    artifact_file_fresh: bool
    source_file_checked: bool
    source_file_fresh: bool
    metadata_chain_complete: bool
    cas_replay_complete: bool
    issue_count: int
    replay_issue_count: int
    case_count: int
    event_count: int
    artifact_ref: str = ""
    source_path: str = ""
    issues: tuple[MonitoringAggregateCasRevalidationIssue, ...] = ()
    schema_version: str = MONITORING_AGGREGATE_CAS_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    release_ready: bool = False
    aggregate_write_permitted: bool = False
    migration_ready: bool = False
    runtime_write_permitted: bool = False
    medical_authority_granted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != MONITORING_AGGREGATE_CAS_REVALIDATION_SCHEMA_VERSION:
            raise MonitoringAggregateCasRevalidationError(
                "unsupported aggregate/CAS revalidation schema"
            )
        if self.status not in {"fresh", "blocked"}:
            raise MonitoringAggregateCasRevalidationError("invalid revalidation status")
        if self.read_only is not True:
            raise MonitoringAggregateCasRevalidationError(
                "aggregate/CAS revalidation must remain read-only"
            )
        for name in (
            "authority_granted",
            "release_ready",
            "aggregate_write_permitted",
            "migration_ready",
            "runtime_write_permitted",
            "medical_authority_granted",
        ):
            if getattr(self, name) is not False:
                raise MonitoringAggregateCasRevalidationError(
                    f"{name} must remain false"
                )
        for name in (
            "evidence_fresh",
            "artifact_payload_valid",
            "source_payload_valid",
            "replay_report_matches",
            "artifact_file_checked",
            "artifact_file_fresh",
            "source_file_checked",
            "source_file_fresh",
            "metadata_chain_complete",
            "cas_replay_complete",
        ):
            if not isinstance(getattr(self, name), bool):
                raise MonitoringAggregateCasRevalidationError(f"{name} must be boolean")
        for name in ("issue_count", "replay_issue_count", "case_count", "event_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MonitoringAggregateCasRevalidationError(
                    f"{name} must be a non-negative integer"
                )
        if self.issue_count != len(self.issues):
            raise MonitoringAggregateCasRevalidationError(
                "issue_count must equal the number of issues"
            )
        if self.artifact_file_fresh and not self.artifact_file_checked:
            raise MonitoringAggregateCasRevalidationError(
                "artifact_file_fresh requires artifact_file_checked"
            )
        if self.source_file_fresh and not self.source_file_checked:
            raise MonitoringAggregateCasRevalidationError(
                "source_file_fresh requires source_file_checked"
            )
        issues = tuple(self.issues)
        if any(
            not isinstance(item, MonitoringAggregateCasRevalidationIssue)
            for item in issues
        ):
            raise MonitoringAggregateCasRevalidationError(
                "issues contain an invalid value"
            )
        expected_fresh = (
            not issues
            and self.artifact_payload_valid
            and self.source_payload_valid
            and self.replay_report_matches
            and (not self.artifact_file_checked or self.artifact_file_fresh)
            and (not self.source_file_checked or self.source_file_fresh)
        )
        if (
            self.evidence_fresh != expected_fresh
            or (self.status == "fresh") != expected_fresh
        ):
            raise MonitoringAggregateCasRevalidationError(
                "revalidation status does not match evidence state"
            )
        object.__setattr__(self, "artifact_ref", _text(self.artifact_ref))
        object.__setattr__(self, "source_path", _text(self.source_path))
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "artifact_payload_valid": self.artifact_payload_valid,
            "source_payload_valid": self.source_payload_valid,
            "replay_report_matches": self.replay_report_matches,
            "artifact_file_checked": self.artifact_file_checked,
            "artifact_file_fresh": self.artifact_file_fresh,
            "source_file_checked": self.source_file_checked,
            "source_file_fresh": self.source_file_fresh,
            "metadata_chain_complete": self.metadata_chain_complete,
            "cas_replay_complete": self.cas_replay_complete,
            "issue_count": self.issue_count,
            "replay_issue_count": self.replay_issue_count,
            "case_count": self.case_count,
            "event_count": self.event_count,
            "artifact_ref": self.artifact_ref,
            "source_path": self.source_path,
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "release_ready": self.release_ready,
            "aggregate_write_permitted": self.aggregate_write_permitted,
            "migration_ready": self.migration_ready,
            "runtime_write_permitted": self.runtime_write_permitted,
            "medical_authority_granted": self.medical_authority_granted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


def _issue(
    issues: list[MonitoringAggregateCasRevalidationIssue],
    code: MonitoringAggregateCasRevalidationIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(
        MonitoringAggregateCasRevalidationIssue(
            code=code,
            subject=_text(subject) or "payload",
            detail=_text(detail) or "invalid evidence",
        )
    )


def _safe_relative_path(
    raw_path: Any,
    *,
    workspace_root: Path,
    issues: list[MonitoringAggregateCasRevalidationIssue],
    subject: str,
) -> Path | None:
    text = raw_path.strip() if isinstance(raw_path, str) else ""
    path = Path(text) if text else Path(".")
    if (
        not text
        or path.is_absolute()
        or "\\" in text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_PATH_UNSAFE,
            subject,
            "path must be a clean workspace-relative POSIX path",
        )
        return None
    current = workspace_root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED,
                subject,
                "path and parent components must not be symlinks",
            )
            return None
    try:
        candidate = workspace_root / path
        candidate.resolve(strict=False).relative_to(workspace_root.resolve())
    except (OSError, ValueError) as exc:
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_PATH_UNSAFE,
            subject,
            f"path escapes workspace root: {exc}",
        )
        return None
    return candidate


def _blocked_report(
    issues: list[MonitoringAggregateCasRevalidationIssue],
    *,
    artifact_ref: str = "",
    source_path: str = "",
    artifact_payload_valid: bool = False,
    source_payload_valid: bool = False,
    replay_report_matches: bool = False,
    artifact_file_checked: bool = False,
    artifact_file_fresh: bool = False,
    source_file_checked: bool = False,
    source_file_fresh: bool = False,
    metadata_chain_complete: bool = False,
    cas_replay_complete: bool = False,
    replay_issue_count: int = 0,
    case_count: int = 0,
    event_count: int = 0,
) -> MonitoringAggregateCasRevalidationReport:
    return MonitoringAggregateCasRevalidationReport(
        status="blocked",
        evidence_fresh=False,
        artifact_payload_valid=artifact_payload_valid,
        source_payload_valid=source_payload_valid,
        replay_report_matches=replay_report_matches,
        artifact_file_checked=artifact_file_checked,
        artifact_file_fresh=artifact_file_fresh,
        source_file_checked=source_file_checked,
        source_file_fresh=source_file_fresh,
        metadata_chain_complete=metadata_chain_complete,
        cas_replay_complete=cas_replay_complete,
        issue_count=len(issues),
        replay_issue_count=replay_issue_count,
        case_count=case_count,
        event_count=event_count,
        artifact_ref=artifact_ref,
        source_path=source_path,
        issues=tuple(issues),
    )


def _authority_ok(
    payload: Mapping[str, Any],
    issues: list[MonitoringAggregateCasRevalidationIssue],
) -> bool:
    expectations = {
        "read_only": True,
        "aggregate_write_permitted": False,
        "migration_ready": False,
    }
    ok = True
    for name, expected in expectations.items():
        if name not in payload:
            ok = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.AUTHORITY_FLAG_MISSING,
                name,
                "required artifact boundary flag is missing",
            )
        elif payload[name] is not expected:
            ok = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
                name,
                f"expected {expected!r}, observed {payload[name]!r}",
            )
    return ok


def _source_authority_ok(
    payload: Mapping[str, Any],
    issues: list[MonitoringAggregateCasRevalidationIssue],
) -> bool:
    expectations = {
        "read_only": True,
        "approved": False,
        "write_permitted": False,
        "requires_medical_and_engineering_review": True,
    }
    ok = True
    for name, expected in expectations.items():
        if name not in payload:
            ok = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_AUTHORITY_FLAG_MISSING,
                f"source.{name}",
                "required source review boundary flag is missing",
            )
        elif payload[name] is not expected:
            ok = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_AUTHORITY_FLAG_TRUE,
                f"source.{name}",
                f"expected {expected!r}, observed {payload[name]!r}",
            )
    return ok


def _reconstruct_cases(
    source: Mapping[str, Any],
    issues: list[MonitoringAggregateCasRevalidationIssue],
) -> tuple[tuple[MonitoringAggregateCasCase, ...], int] | None:
    decisions = source.get("decisions")
    if not isinstance(decisions, list):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.SOURCE_PAYLOAD_INVALID,
            "source.decisions",
            "decisions must be an array",
        )
        return None
    declared_count = source.get("decision_count")
    if (
        isinstance(declared_count, bool)
        or not isinstance(declared_count, int)
        or declared_count != len(decisions)
    ):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.SOURCE_DECISION_COUNT_MISMATCH,
            "source.decision_count",
            f"declared={declared_count!r}, observed={len(decisions)}",
        )

    groups: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for index, decision in enumerate(decisions):
        label = f"source.decisions[{index}]"
        if not isinstance(decision, Mapping):
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_DECISION_INVALID,
                label,
                "decision must be an object",
            )
            continue
        unknown = sorted(set(decision) - SOURCE_DECISION_KEYS)
        if unknown:
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_DECISION_INVALID,
                label,
                f"unsupported fields: {unknown}",
            )
            continue
        required = (
            "project_id",
            "current_risk_key",
            "current_risk_instance_id",
            "current_source_revision",
            "disposition_chain",
        )
        missing = [
            name
            for name in required
            if not _text(decision.get(name)) and name != "disposition_chain"
        ]
        if "disposition_chain" not in decision:
            missing.append("disposition_chain")
        if missing:
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_DECISION_INVALID,
                label,
                f"missing required fields: {missing}",
            )
            continue
        chain = decision.get("disposition_chain")
        if not isinstance(chain, list) or not chain:
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_CHAIN_INVALID,
                f"{label}.disposition_chain",
                "disposition_chain must be a non-empty array",
            )
            continue
        key = (
            _text(decision.get("project_id")),
            _text(decision.get("current_risk_key")),
            _text(decision.get("current_risk_instance_id")),
            _text(decision.get("current_source_revision")),
        )
        group = groups.setdefault(key, {"decision": decision, "rows": {}})
        rows: dict[str, Mapping[str, Any]] = group["rows"]
        for chain_index, row in enumerate(chain):
            row_label = f"{label}.disposition_chain[{chain_index}]"
            if not isinstance(row, Mapping):
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_CHAIN_INVALID,
                    row_label,
                    "chain event must be an object",
                )
                continue
            unknown_row = sorted(set(row) - SOURCE_CHAIN_KEYS)
            if unknown_row:
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_CHAIN_INVALID,
                    row_label,
                    f"unsupported fields: {unknown_row}",
                )
                continue
            missing_row = [
                name
                for name in ("record_id", "previous_state", "new_state", "created_at")
                if not _text(row.get(name))
            ]
            if missing_row:
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_CHAIN_INVALID,
                    row_label,
                    f"missing required fields: {missing_row}",
                )
                continue
            record_id = _text(row.get("record_id"))
            prior = rows.get(record_id)
            if prior is not None and _canonical(prior) != _canonical(row):
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_CHAIN_CONFLICT,
                    record_id,
                    "duplicate record_id has conflicting chain payloads",
                )
            else:
                rows.setdefault(record_id, row)

    cases: list[MonitoringAggregateCasCase] = []
    event_count = 0
    for (project_id, risk_key, instance_id, source_revision), group in sorted(
        groups.items()
    ):
        events: list[MonitoringAggregateCasEvent] = []
        for row in group["rows"].values():
            try:
                events.append(
                    MonitoringAggregateCasEvent(
                        record_id=row["record_id"],
                        project_id=project_id,
                        risk_key=risk_key,
                        risk_instance_id=instance_id,
                        source_revision=source_revision,
                        previous_state=row["previous_state"],
                        new_state=row["new_state"],
                        created_at=row["created_at"],
                        expected_version=row.get("expected_version"),
                    )
                )
            except (
                KeyError,
                TypeError,
                ValueError,
                MonitoringAggregateCasReplayError,
            ) as exc:
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.CASE_RECONSTRUCTION_FAILED,
                    f"{project_id}:{instance_id}",
                    str(exc),
                )
        if not events:
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.CASE_RECONSTRUCTION_FAILED,
                f"{project_id}:{instance_id}",
                "aggregate case has no reconstructable events",
            )
            continue
        cases.append(
            MonitoringAggregateCasCase(
                project_id=project_id,
                risk_key=risk_key,
                risk_instance_id=instance_id,
                source_revision=source_revision,
                events=tuple(events),
            )
        )
        event_count += len(events)
    return tuple(cases), event_count


def _reported_replay_payload(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    keys = (
        "metadata_chain_complete",
        "cas_replay_complete",
        "issue_count",
        "replays",
        "aggregate_write_permitted",
        "migration_ready",
        "report_sha256",
    )
    if any(key not in payload for key in keys):
        return None
    return {key: payload[key] for key in keys}


def _non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def revalidate_aggregate_cas_payload(
    payload: Mapping[str, Any],
    *,
    source_payload: Mapping[str, Any] | None,
    source_path: str = "",
    artifact_ref: str = "",
    artifact_file_checked: bool = False,
    artifact_file_fresh: bool = False,
    source_file_checked: bool = False,
    source_file_fresh: bool = False,
    initial_issues: list[MonitoringAggregateCasRevalidationIssue] | None = None,
) -> MonitoringAggregateCasRevalidationReport:
    """Reconstruct and compare one B4 aggregate/CAS evidence envelope."""

    issues = list(initial_issues or ())
    if not isinstance(payload, Mapping):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "artifact",
            "artifact JSON root must be an object",
        )
        return _blocked_report(
            issues,
            artifact_ref=artifact_ref,
            source_path=source_path,
            artifact_file_checked=artifact_file_checked,
            artifact_file_fresh=artifact_file_fresh,
            source_file_checked=source_file_checked,
            source_file_fresh=source_file_fresh,
        )
    unknown = sorted(set(payload) - AGGREGATE_CAS_REPLAY_ARTIFACT_KEYS)
    if unknown:
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "artifact",
            f"unsupported fields: {unknown}",
        )
    _authority_ok(payload, issues)
    input_path = _text(payload.get("input_path"))
    declared_source_path = source_path or input_path
    if source_path and input_path != source_path:
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.SOURCE_PATH_MISMATCH,
            "input_path",
            f"declared={input_path!r}, supplied={source_path!r}",
        )
    if not _valid_sha(payload.get("input_sha256")):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "input_sha256",
            "input_sha256 must be a lowercase SHA-256",
        )
    declared_field = _text(payload.get("expected_version_source_field"))
    if not declared_field:
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "expected_version_source_field",
            "expected_version_source_field is required",
        )
    if not isinstance(payload.get("replays"), list):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_REPORT_MISSING,
            "replays",
            "persisted replays must be an array",
        )

    artifact_payload_valid = not any(
        item.code
        in {
            MonitoringAggregateCasRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            MonitoringAggregateCasRevalidationIssueCode.AUTHORITY_FLAG_MISSING,
            MonitoringAggregateCasRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_REPORT_MISSING,
        }
        for item in issues
    )
    source_payload_valid = False
    replay_report_matches = False
    metadata_complete = False
    cas_complete = False
    replay_issue_count = 0
    case_count = 0
    event_count = 0
    if not isinstance(source_payload, Mapping):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.SOURCE_PAYLOAD_INVALID,
            "source",
            "source package JSON root must be an object",
        )
    else:
        _source_authority_ok(source_payload, issues)
        reconstructed = _reconstruct_cases(source_payload, issues)
        if reconstructed is not None:
            cases, event_count = reconstructed
            case_count = len(cases)
            observed_decision_count = source_payload.get("decision_count")
            if not _non_negative_int(payload.get("input_decision_count")):
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
                    "input_decision_count",
                    "input_decision_count must be a non-negative integer",
                )
            elif payload["input_decision_count"] != observed_decision_count:
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_REPORT_MISMATCH,
                    "input_decision_count",
                    f"expected source decision_count={observed_decision_count!r}, observed={payload['input_decision_count']!r}",
                )
            if not _non_negative_int(payload.get("distinct_aggregate_cases")):
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
                    "distinct_aggregate_cases",
                    "distinct_aggregate_cases must be a non-negative integer",
                )
            elif payload["distinct_aggregate_cases"] != case_count:
                _issue(
                    issues,
                    MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_REPORT_MISMATCH,
                    "distinct_aggregate_cases",
                    f"expected reconstructed cases={case_count}, observed={payload['distinct_aggregate_cases']}",
                )
            if cases:
                try:
                    derived = build_monitoring_aggregate_cas_replay_report(
                        cases
                    ).to_dict()
                except (
                    TypeError,
                    ValueError,
                    MonitoringAggregateCasReplayError,
                ) as exc:
                    _issue(
                        issues,
                        MonitoringAggregateCasRevalidationIssueCode.CASE_RECONSTRUCTION_FAILED,
                        "replay",
                        str(exc),
                    )
                else:
                    metadata_complete = bool(derived["metadata_chain_complete"])
                    cas_complete = bool(derived["cas_replay_complete"])
                    replay_issue_count = int(derived["issue_count"])
                    if not _non_negative_int(payload.get("issue_count")):
                        _issue(
                            issues,
                            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
                            "issue_count",
                            "issue_count must be a non-negative integer",
                        )
                    elif payload["issue_count"] != replay_issue_count:
                        _issue(
                            issues,
                            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_REPORT_MISMATCH,
                            "issue_count",
                            f"expected replay issue_count={replay_issue_count}, observed={payload['issue_count']}",
                        )
                    reported = _reported_replay_payload(payload)
                    if reported is None:
                        _issue(
                            issues,
                            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_REPORT_MISSING,
                            "report",
                            "persisted replay report is incomplete",
                        )
                    else:
                        replay_report_matches = _canonical(reported) == _canonical(
                            derived
                        )
                        if not replay_report_matches:
                            _issue(
                                issues,
                                MonitoringAggregateCasRevalidationIssueCode.REPORT_REPLAY_MISMATCH,
                                "report",
                                "persisted aggregate/CAS report differs from deterministic replay",
                            )
        source_payload_valid = (
            not any(
                item.code
                in {
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_PAYLOAD_INVALID,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_AUTHORITY_FLAG_MISSING,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_AUTHORITY_FLAG_TRUE,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_DECISION_COUNT_MISMATCH,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_DECISION_INVALID,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_CHAIN_INVALID,
                    MonitoringAggregateCasRevalidationIssueCode.SOURCE_CHAIN_CONFLICT,
                    MonitoringAggregateCasRevalidationIssueCode.CASE_RECONSTRUCTION_FAILED,
                }
                for item in issues
            )
            and reconstructed is not None
            and bool(cases)
        )

    return MonitoringAggregateCasRevalidationReport(
        status="fresh"
        if artifact_payload_valid
        and source_payload_valid
        and replay_report_matches
        and not issues
        else "blocked",
        evidence_fresh=artifact_payload_valid
        and source_payload_valid
        and replay_report_matches
        and not issues,
        artifact_payload_valid=artifact_payload_valid,
        source_payload_valid=source_payload_valid,
        replay_report_matches=replay_report_matches,
        artifact_file_checked=artifact_file_checked,
        artifact_file_fresh=artifact_file_fresh,
        source_file_checked=source_file_checked,
        source_file_fresh=source_file_fresh,
        metadata_chain_complete=metadata_complete,
        cas_replay_complete=cas_complete,
        issue_count=len(issues),
        replay_issue_count=replay_issue_count,
        case_count=case_count,
        event_count=event_count,
        artifact_ref=artifact_ref,
        source_path=declared_source_path,
        issues=tuple(issues),
    )


def _read_json_file(
    path: Path,
    *,
    subject: str,
    issues: list[MonitoringAggregateCasRevalidationIssue],
) -> Mapping[str, Any] | None:
    if path.is_symlink():
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED,
            subject,
            "file must not be a symlink",
        )
        return None
    if not path.exists():
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_MISSING,
            subject,
            "file does not exist",
        )
        return None
    if not path.is_file():
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_NOT_REGULAR,
            subject,
            "path is not a regular file",
        )
        return None
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_JSON_INVALID,
            subject,
            str(exc),
        )
        return None
    if not isinstance(value, Mapping):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            subject,
            "JSON root must be an object",
        )
        return None
    return value


def revalidate_aggregate_cas_file(
    artifact_ref: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    expected_source_bytes: int | None = None,
    expected_source_sha256: str | None = None,
    workspace_root: str | Path,
) -> MonitoringAggregateCasRevalidationReport:
    """Reopen artifact and source package, then replay without side effects."""

    issues: list[MonitoringAggregateCasRevalidationIssue] = []
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
    ):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "expected_bytes",
            "expected_bytes must be a non-negative integer",
        )
    if not _valid_sha(expected_sha256):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "expected_sha256",
            "expected_sha256 must be a lowercase SHA-256",
        )
    if expected_source_bytes is not None and (
        isinstance(expected_source_bytes, bool)
        or not isinstance(expected_source_bytes, int)
        or expected_source_bytes < 0
    ):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "expected_source_bytes",
            "expected_source_bytes must be a non-negative integer or null",
        )
    if expected_source_sha256 is not None and not _valid_sha(expected_source_sha256):
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.ARTIFACT_FIELD_INVALID,
            "expected_source_sha256",
            "expected_source_sha256 must be a lowercase SHA-256 or null",
        )
    try:
        root = Path(workspace_root)
    except TypeError as exc:
        raise MonitoringAggregateCasRevalidationError(
            "workspace_root must be path-like"
        ) from exc
    artifact = _safe_relative_path(
        artifact_ref, workspace_root=root, issues=issues, subject="artifact_ref"
    )
    if artifact is None:
        return _blocked_report(
            issues, artifact_ref=_text(artifact_ref), artifact_file_checked=True
        )
    artifact_file_fresh = False
    artifact_payload: Mapping[str, Any] | None = None
    if not artifact.exists():
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_MISSING,
            "artifact_ref",
            "artifact file does not exist",
        )
    elif not artifact.is_file():
        _issue(
            issues,
            MonitoringAggregateCasRevalidationIssueCode.FILE_NOT_REGULAR,
            "artifact_ref",
            "artifact path is not a regular file",
        )
    else:
        raw = artifact.read_bytes()
        observed_sha = hashlib.sha256(raw).hexdigest()
        artifact_file_fresh = (
            len(raw) == expected_bytes and observed_sha == expected_sha256
        )
        if len(raw) != expected_bytes:
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.FILE_BYTES_MISMATCH,
                "artifact_ref",
                f"expected={expected_bytes}, observed={len(raw)}",
            )
        if observed_sha != expected_sha256:
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.FILE_SHA256_MISMATCH,
                "artifact_ref",
                f"expected={expected_sha256}, observed={observed_sha}",
            )
        try:
            artifact_payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.FILE_JSON_INVALID,
                "artifact_ref",
                str(exc),
            )
        if artifact_payload is not None and not isinstance(artifact_payload, Mapping):
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
                "artifact_ref",
                "artifact JSON root must be an object",
            )
            artifact_payload = None
    if artifact_payload is None:
        return _blocked_report(
            issues,
            artifact_ref=_text(artifact_ref),
            artifact_file_checked=True,
            artifact_file_fresh=artifact_file_fresh,
        )
    source_rel = _text(artifact_payload.get("input_path"))
    source = _safe_relative_path(
        source_rel, workspace_root=root, issues=issues, subject="input_path"
    )
    source_file_fresh = False
    source_payload: Mapping[str, Any] | None = None
    if (
        source is not None
        and source.exists()
        and source.is_file()
        and not source.is_symlink()
    ):
        source_raw = source.read_bytes()
        observed_source_sha = hashlib.sha256(source_raw).hexdigest()
        source_file_fresh = True
        if (
            expected_source_bytes is not None
            and len(source_raw) != expected_source_bytes
        ):
            source_file_fresh = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_FILE_BYTES_MISMATCH,
                "input_path",
                f"expected={expected_source_bytes}, observed={len(source_raw)}",
            )
        if observed_source_sha != artifact_payload.get("input_sha256"):
            source_file_fresh = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_FILE_SHA256_MISMATCH,
                "input_path",
                f"artifact_sha={artifact_payload.get('input_sha256')}, observed={observed_source_sha}",
            )
        if (
            expected_source_sha256 is not None
            and observed_source_sha != expected_source_sha256
        ):
            source_file_fresh = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.SOURCE_FILE_SHA256_MISMATCH,
                "input_path",
                f"expected={expected_source_sha256}, observed={observed_source_sha}",
            )
        try:
            source_payload = json.loads(source_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            source_file_fresh = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.FILE_JSON_INVALID,
                "input_path",
                str(exc),
            )
        if source_payload is not None and not isinstance(source_payload, Mapping):
            source_file_fresh = False
            _issue(
                issues,
                MonitoringAggregateCasRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
                "input_path",
                "source JSON root must be an object",
            )
            source_payload = None
    elif source is not None:
        source_payload = _read_json_file(source, subject="input_path", issues=issues)
    report = revalidate_aggregate_cas_payload(
        artifact_payload,
        source_payload=source_payload,
        source_path=source_rel,
        artifact_ref=_text(artifact_ref),
        artifact_file_checked=True,
        artifact_file_fresh=artifact_file_fresh,
        source_file_checked=source is not None,
        source_file_fresh=source_file_fresh,
        initial_issues=issues,
    )
    return report


__all__ = [
    "AGGREGATE_CAS_REPLAY_ARTIFACT_KEYS",
    "MONITORING_AGGREGATE_CAS_REVALIDATION_SCHEMA_VERSION",
    "MonitoringAggregateCasRevalidationError",
    "MonitoringAggregateCasRevalidationIssue",
    "MonitoringAggregateCasRevalidationIssueCode",
    "MonitoringAggregateCasRevalidationReport",
    "revalidate_aggregate_cas_file",
    "revalidate_aggregate_cas_payload",
]
