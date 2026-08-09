"""Read-only revalidation of a commercial release evidence snapshot.

The release gate and dossier contracts validate in-memory shapes.  This module
adds the missing filesystem boundary: it reopens the declared evidence files,
checks their byte/hash identity, binds every gate row to a revalidated source,
and compares the release snapshot's B6 fields with the current B6/C14 evidence.
It is diagnostic only and never changes a release decision or grants authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .monitoring_release_gate import REQUIRED_RELEASE_GATE_IDS, ReleaseEvidenceStatus


RELEASE_EVIDENCE_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_release_evidence_revalidation_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE_STATUSES = {"ready", "not_ready", "blocked"}
_B6_SNAPSHOT_KEYS = (
    "status",
    "candidate_count",
    "outcome_count",
    "missing_candidate_record_ids",
    "pending_candidate_record_ids",
    "rejected_candidate_record_ids",
    "accepted_review_ids",
    "migration_ready",
    "unresolved_blockers",
    "activation_allowed",
    "event_creation_allowed",
    "projection_allowed",
    "write_permitted",
    "migration_write_permitted",
)


class ReleaseEvidenceRevalidationError(ValueError):
    """Raised when the revalidation input cannot be evaluated safely."""


class ReleaseEvidenceRevalidationIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    SOURCE_DUPLICATE = "source_duplicate"
    SOURCE_FIELD_INVALID = "source_field_invalid"
    SOURCE_PATH_UNSAFE = "source_path_unsafe"
    SOURCE_MISSING = "source_missing"
    SOURCE_NOT_FILE = "source_not_file"
    SOURCE_SYMLINK_UNSUPPORTED = "source_symlink_unsupported"
    SOURCE_BYTES_MISMATCH = "source_bytes_mismatch"
    SOURCE_SHA256_MISMATCH = "source_sha256_mismatch"
    GATE_SET_MISMATCH = "gate_set_mismatch"
    GATE_DUPLICATE = "gate_duplicate"
    GATE_STATUS_INVALID = "gate_status_invalid"
    GATE_EVIDENCE_UNBOUND = "gate_evidence_unbound"
    DECISION_GATE_ORDER_MISMATCH = "decision_gate_order_mismatch"
    DECISION_GATE_ROW_MISMATCH = "decision_gate_row_mismatch"
    DECISION_DERIVED_MISMATCH = "decision_derived_mismatch"
    DECISION_STATUS_INVALID = "decision_status_invalid"
    B6_SNAPSHOT_MISSING = "b6_snapshot_missing"
    B6_SNAPSHOT_MISMATCH = "b6_snapshot_mismatch"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseEvidenceRevalidationError(
            "revalidation payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


@dataclass(frozen=True)
class ReleaseEvidenceRevalidationIssue:
    code: ReleaseEvidenceRevalidationIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise ReleaseEvidenceRevalidationError(
                "revalidation issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class ReleaseEvidenceRevalidationReport:
    """Filesystem revalidation result; never a release or medical decision."""

    status: str
    evidence_fresh: bool
    source_count: int
    source_match_count: int
    gate_count: int
    gate_bound_count: int
    decision_gate_order_matches: bool
    b6_snapshot_matches: bool
    release_decision_status: str
    release_ready_observed: bool
    issues: tuple[ReleaseEvidenceRevalidationIssue, ...]
    schema_version: str = RELEASE_EVIDENCE_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != RELEASE_EVIDENCE_REVALIDATION_SCHEMA_VERSION:
            raise ReleaseEvidenceRevalidationError("unsupported revalidation schema")
        if self.status not in {"blocked", "fresh"}:
            raise ReleaseEvidenceRevalidationError("invalid revalidation status")
        if self.read_only is not True or self.authority_granted is not False:
            raise ReleaseEvidenceRevalidationError(
                "revalidation reports must remain read-only and non-authoritative"
            )
        for name in (
            "source_count",
            "source_match_count",
            "gate_count",
            "gate_bound_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReleaseEvidenceRevalidationError(
                    f"{name} must be a non-negative integer"
                )
        for name in (
            "evidence_fresh",
            "decision_gate_order_matches",
            "b6_snapshot_matches",
            "release_ready_observed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ReleaseEvidenceRevalidationError(
                    f"{name} must be a strict boolean"
                )
        if self.release_decision_status not in _RELEASE_STATUSES:
            raise ReleaseEvidenceRevalidationError("release_decision_status is invalid")
        issues = tuple(self.issues)
        if any(
            not isinstance(item, ReleaseEvidenceRevalidationIssue) for item in issues
        ):
            raise ReleaseEvidenceRevalidationError("issues contain an invalid value")
        expected_fresh = not issues
        if (
            self.evidence_fresh != expected_fresh
            or (self.status == "fresh") != expected_fresh
        ):
            raise ReleaseEvidenceRevalidationError(
                "revalidation status does not match issues"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "source_count": self.source_count,
            "source_match_count": self.source_match_count,
            "gate_count": self.gate_count,
            "gate_bound_count": self.gate_bound_count,
            "decision_gate_order_matches": self.decision_gate_order_matches,
            "b6_snapshot_matches": self.b6_snapshot_matches,
            "release_decision_status": self.release_decision_status,
            "release_ready_observed": self.release_ready_observed,
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[ReleaseEvidenceRevalidationIssue],
    code: ReleaseEvidenceRevalidationIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(ReleaseEvidenceRevalidationIssue(code, subject, detail))


def _source_observation(
    source: Mapping[str, Any],
    *,
    workspace_root: Path,
    issues: list[ReleaseEvidenceRevalidationIssue],
) -> tuple[str, str, bool] | None:
    source_id = _text(source.get("id"))
    path_text = _text(source.get("path"))
    expected_bytes = source.get("bytes")
    expected_sha = source.get("sha256")
    if (
        not source_id
        or not path_text
        or isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
        or not _valid_sha(expected_sha)
    ):
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_FIELD_INVALID,
            source_id or "source",
            "source requires id, path, non-negative integer bytes and lowercase SHA-256",
        )
        return None
    path = Path(path_text)
    if (
        path.is_absolute()
        or "\\" in path_text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_PATH_UNSAFE,
            source_id or "source",
            "declared evidence path must be a clean workspace-relative POSIX path",
        )
        return source_id, expected_sha, False
    root = workspace_root.resolve()
    candidate = workspace_root / path
    current = workspace_root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.SOURCE_SYMLINK_UNSUPPORTED,
                source_id,
                "declared evidence path and parent components must not be symlinks",
            )
            return source_id, expected_sha, False
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_PATH_UNSAFE,
            source_id or "source",
            "declared evidence path escapes the workspace root",
        )
        return source_id, expected_sha, False
    if candidate.is_symlink():
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_SYMLINK_UNSUPPORTED,
            source_id,
            "declared evidence path must be a direct file, not a symlink",
        )
        return source_id, expected_sha, False
    if not candidate.exists():
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_MISSING,
            source_id,
            f"declared evidence path does not exist: {path_text}",
        )
        return source_id, expected_sha, False
    if not candidate.is_file():
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_NOT_FILE,
            source_id,
            f"declared evidence path is not a regular file: {path_text}",
        )
        return source_id, expected_sha, False
    observed_bytes = candidate.stat().st_size
    observed_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
    match = True
    if observed_bytes != expected_bytes:
        match = False
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_BYTES_MISMATCH,
            source_id,
            f"expected bytes={expected_bytes}, observed bytes={observed_bytes}",
        )
    if observed_sha != expected_sha:
        match = False
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.SOURCE_SHA256_MISMATCH,
            source_id,
            f"expected sha256={expected_sha}, observed sha256={observed_sha}",
        )
    return source_id, expected_sha, match


def _expected_b6_snapshot(
    b6_payload: Mapping[str, Any] | None,
    c14_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(b6_payload, Mapping):
        return None
    gate = b6_payload.get("gate")
    if not isinstance(gate, Mapping):
        return None
    result = {key: gate.get(key) for key in _B6_SNAPSHOT_KEYS}
    result["migration_write_permitted"] = b6_payload.get("migration_write_permitted")
    if isinstance(c14_payload, Mapping):
        for key in (
            "activation_allowed",
            "event_creation_allowed",
            "projection_allowed",
        ):
            result[key] = c14_payload.get(key)
    return result


def revalidate_release_evidence(
    coverage_payload: Mapping[str, Any],
    *,
    b6_payload: Mapping[str, Any] | None = None,
    c14_payload: Mapping[str, Any] | None = None,
    workspace_root: str | Path = ".",
) -> ReleaseEvidenceRevalidationReport:
    """Reopen and verify a release coverage snapshot without side effects."""

    if not isinstance(coverage_payload, Mapping):
        raise ReleaseEvidenceRevalidationError("coverage_payload must be a mapping")
    try:
        root = Path(workspace_root)
    except TypeError as exc:
        raise ReleaseEvidenceRevalidationError(
            "workspace_root must be path-like"
        ) from exc
    issues: list[ReleaseEvidenceRevalidationIssue] = []
    if coverage_payload.get("mode") != "read_only":
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "mode",
            "coverage snapshot must declare mode=read_only",
        )
    if coverage_payload.get("authority_granted") is not False:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
            "authority_granted",
            "coverage snapshot cannot grant release authority",
        )

    raw_sources = coverage_payload.get("sources")
    sources = raw_sources if isinstance(raw_sources, list) else []
    if not isinstance(raw_sources, list):
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "sources",
            "coverage snapshot sources must be a list",
        )
    source_ids: set[str] = set()
    source_hashes: set[str] = set()
    source_match_count = 0
    for source in sources:
        if not isinstance(source, Mapping):
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.SOURCE_FIELD_INVALID,
                "sources",
                "source entries must be objects",
            )
            continue
        observation = _source_observation(source, workspace_root=root, issues=issues)
        if observation is None:
            continue
        source_id, source_sha, matched = observation
        if source_id in source_ids:
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.SOURCE_DUPLICATE,
                source_id,
                "source IDs must be unique",
            )
        source_ids.add(source_id)
        source_hashes.add(source_sha)
        source_match_count += int(matched)

    raw_gates = coverage_payload.get("gate_results")
    gates = raw_gates if isinstance(raw_gates, list) else []
    if not isinstance(raw_gates, list):
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "gate_results",
            "gate_results must be a list",
        )
    gate_ids: list[str] = []
    gate_bound_count = 0
    seen_gate_ids: set[str] = set()
    gate_by_id: dict[str, Mapping[str, Any]] = {}
    for gate in gates:
        if not isinstance(gate, Mapping):
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
                "gate_results",
                "gate entries must be objects",
            )
            continue
        gate_id = _text(gate.get("gate_id"))
        gate_ids.append(gate_id)
        if gate_id in seen_gate_ids:
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.GATE_DUPLICATE,
                gate_id or "gate",
                "gate IDs must be unique",
            )
        seen_gate_ids.add(gate_id)
        gate_by_id[gate_id] = gate
        if _text(gate.get("status")) not in {
            status.value for status in ReleaseEvidenceStatus
        }:
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.GATE_STATUS_INVALID,
                gate_id or "gate",
                "gate status must be passed, partial, unproven or blocked",
            )
        evidence_sha = gate.get("evidence_sha256")
        if evidence_sha in source_hashes and _valid_sha(evidence_sha):
            gate_bound_count += 1
        else:
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.GATE_EVIDENCE_UNBOUND,
                gate_id or "gate",
                "gate evidence_sha256 does not match a revalidated source SHA-256",
            )
    if tuple(gate_ids) != REQUIRED_RELEASE_GATE_IDS:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.GATE_SET_MISMATCH,
            "gate_results",
            f"expected canonical gate order={list(REQUIRED_RELEASE_GATE_IDS)}, observed={gate_ids}",
        )

    decision = coverage_payload.get("decision")
    decision = decision if isinstance(decision, Mapping) else {}
    decision_gate_rows = decision.get("gate_results")
    decision_gate_rows = (
        decision_gate_rows if isinstance(decision_gate_rows, list) else []
    )
    decision_gate_ids = [
        _text(item.get("gate_id"))
        for item in decision_gate_rows
        if isinstance(item, Mapping)
    ]
    decision_order_matches = tuple(decision_gate_ids) == tuple(gate_ids)
    if not decision_order_matches:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.DECISION_GATE_ORDER_MISMATCH,
            "decision.gate_results",
            f"top-level={gate_ids}, decision={decision_gate_ids}",
        )
    for gate_id, decision_row in zip(gate_ids, decision_gate_rows):
        top_row = gate_by_id.get(gate_id)
        if not isinstance(top_row, Mapping) or not isinstance(decision_row, Mapping):
            continue
        if decision_row != top_row:
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.DECISION_GATE_ROW_MISMATCH,
                gate_id or "gate",
                "decision gate row differs from top-level gate row",
            )

    release_status = _text(decision.get("status"))
    if release_status not in _RELEASE_STATUSES:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.DECISION_STATUS_INVALID,
            "decision.status",
            f"unsupported release decision status: {release_status!r}",
        )
        release_status = "blocked"
    release_ready = decision.get("release_ready")
    if not isinstance(release_ready, bool):
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.DECISION_STATUS_INVALID,
            "decision.release_ready",
            "release_ready must be a boolean",
        )
        release_ready = False

    expected_b6 = _expected_b6_snapshot(b6_payload, c14_payload)
    expected_unmet = [
        gate_id
        for gate_id in gate_ids
        if _text(gate_by_id.get(gate_id, {}).get("status"))
        != ReleaseEvidenceStatus.PASSED.value
    ]
    expected_reasons = [
        f"gate:{gate_id}:{_text(gate_by_id[gate_id].get('status'))}"
        for gate_id in gate_ids
        if gate_id in gate_by_id
        and _text(gate_by_id[gate_id].get("status"))
        != ReleaseEvidenceStatus.PASSED.value
    ]
    b6_authority_ready = False
    if isinstance(expected_b6, Mapping):
        b6_authority_ready = (
            expected_b6.get("status") == "approved"
            and expected_b6.get("write_permitted") is True
            and expected_b6.get("migration_ready") is True
            and expected_b6.get("migration_write_permitted") is True
        )
        if not b6_authority_ready:
            expected_reasons.append(
                "b6:approved_write_migration_and_migration_write_authority_required"
            )
    expected_ready = not expected_unmet and b6_authority_ready
    expected_status = (
        "ready"
        if expected_ready
        else "blocked"
        if any(
            _text(gate_by_id.get(gate_id, {}).get("status"))
            == ReleaseEvidenceStatus.BLOCKED.value
            for gate_id in gate_ids
        )
        or not b6_authority_ready
        else "not_ready"
    )
    if decision.get("unmet_gate_ids") != expected_unmet:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.DECISION_DERIVED_MISMATCH,
            "decision.unmet_gate_ids",
            f"expected={expected_unmet!r}, observed={decision.get('unmet_gate_ids')!r}",
        )
    if decision.get("reasons") != expected_reasons:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.DECISION_DERIVED_MISMATCH,
            "decision.reasons",
            f"expected={expected_reasons!r}, observed={decision.get('reasons')!r}",
        )
    if release_status != expected_status:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.DECISION_DERIVED_MISMATCH,
            "decision.status",
            f"expected={expected_status!r}, observed={release_status!r}",
        )
    if release_ready != expected_ready:
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.DECISION_DERIVED_MISMATCH,
            "decision.release_ready",
            f"expected={expected_ready!r}, observed={release_ready!r}",
        )
    if isinstance(expected_b6, Mapping):
        for decision_key, snapshot_key in (
            ("b6_status", "status"),
            ("b6_write_permitted", "write_permitted"),
            ("b6_migration_ready", "migration_ready"),
            ("b6_migration_write_permitted", "migration_write_permitted"),
        ):
            if decision.get(decision_key) != expected_b6.get(snapshot_key):
                _issue(
                    issues,
                    ReleaseEvidenceRevalidationIssueCode.DECISION_DERIVED_MISMATCH,
                    f"decision.{decision_key}",
                    f"expected={expected_b6.get(snapshot_key)!r}, observed={decision.get(decision_key)!r}",
                )
    reported_b6 = coverage_payload.get("b6_current")
    b6_snapshot_matches = True
    if expected_b6 is None or not isinstance(reported_b6, Mapping):
        b6_snapshot_matches = False
        _issue(
            issues,
            ReleaseEvidenceRevalidationIssueCode.B6_SNAPSHOT_MISSING,
            "b6_current",
            "current B6 and C14 payloads plus coverage b6_current are required",
        )
    else:
        mismatches = []
        for key in _B6_SNAPSHOT_KEYS:
            if reported_b6.get(key) != expected_b6.get(key):
                mismatches.append(
                    f"{key}: expected={expected_b6.get(key)!r}, observed={reported_b6.get(key)!r}"
                )
        if mismatches:
            b6_snapshot_matches = False
            _issue(
                issues,
                ReleaseEvidenceRevalidationIssueCode.B6_SNAPSHOT_MISMATCH,
                "b6_current",
                "; ".join(mismatches),
            )

    return ReleaseEvidenceRevalidationReport(
        status="fresh" if not issues else "blocked",
        evidence_fresh=not issues,
        source_count=len(sources),
        source_match_count=source_match_count,
        gate_count=len(gates),
        gate_bound_count=gate_bound_count,
        decision_gate_order_matches=decision_order_matches,
        b6_snapshot_matches=b6_snapshot_matches,
        release_decision_status=release_status,
        release_ready_observed=release_ready,
        issues=tuple(issues),
        read_only=True,
        authority_granted=False,
    )


__all__ = [
    "RELEASE_EVIDENCE_REVALIDATION_SCHEMA_VERSION",
    "ReleaseEvidenceRevalidationError",
    "ReleaseEvidenceRevalidationIssue",
    "ReleaseEvidenceRevalidationIssueCode",
    "ReleaseEvidenceRevalidationReport",
    "revalidate_release_evidence",
]
