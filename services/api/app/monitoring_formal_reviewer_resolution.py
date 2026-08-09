"""Fail-closed validation of hash-bound B6 reviewer resolutions.

This module validates a *submitted* reviewer-resolution document against the
current read-only formal reviewer package.  It is deliberately not a gate
writer: a structurally valid document is only a reviewer-input handoff and
never grants medical, aggregate, migration, activation, or write authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any, Mapping


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_LINEAGE = {
    "confirmed",
    "unproven",
    "needs_source_revalidation",
    "not_applicable",
}
_ALLOWED_CAS = {"confirmed", "unproven", "needs_aggregate_replay", "not_applicable"}
_APPROVE = "approve"


class FormalReviewerResolutionError(ValueError):
    """Raised when the package itself cannot be evaluated safely."""


class FormalReviewerResolutionIssueCode(str, Enum):
    PACKAGE_HASH_MISMATCH = "package_hash_mismatch"
    REVIEWER_INPUT_SHAPE = "reviewer_input_shape"
    REVIEWER_IDENTITY_MISSING = "reviewer_identity_missing"
    REVIEW_ID_MISSING = "review_id_missing"
    DUPLICATE_REVIEW_ID = "duplicate_review_id"
    REVIEWED_AT_INVALID = "reviewed_at_invalid"
    OUTCOME_COUNT_MISMATCH = "outcome_count_mismatch"
    DUPLICATE_OUTCOME = "duplicate_outcome"
    UNKNOWN_CANDIDATE = "unknown_candidate"
    CANDIDATE_FINGERPRINT_MISMATCH = "candidate_fingerprint_mismatch"
    SOURCE_HASH_MISMATCH = "source_hash_mismatch"
    MEDICAL_OUTCOME_MISSING = "medical_outcome_missing"
    SOURCE_LINEAGE_MISSING = "source_lineage_missing"
    AGGREGATE_CAS_MISSING = "aggregate_cas_missing"
    EXTERNAL_ACTION_MISSING = "external_action_missing"
    EVIDENCE_MISSING = "evidence_missing"
    RATIONALE_MISSING = "rationale_missing"
    RESIDUAL_BLOCKER_SHAPE = "residual_blocker_shape"
    RESIDUAL_BLOCKER_CONTRADICTION = "residual_blocker_contradiction"
    CAS_VERSION_MISSING = "cas_version_missing"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise FormalReviewerResolutionError("value must be JSON-serializable") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _digest(value: Any, field_name: str) -> str:
    text = _text(value)
    if not _SHA256_RE.fullmatch(text):
        raise FormalReviewerResolutionError(f"{field_name} must be a lowercase SHA-256")
    return text


def _strings(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise FormalReviewerResolutionError(f"{field_name} must be a string array")
    values = tuple(_text(item) for item in value)
    if any(not item for item in values):
        raise FormalReviewerResolutionError(
            f"{field_name} must not contain empty strings"
        )
    return tuple(dict.fromkeys(values))


def _is_timezone_aware_iso(value: Any) -> bool:
    text = _text(value)
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_non_empty_string_array(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_is_non_empty_string(item) for item in value)
    )


@dataclass(frozen=True)
class FormalReviewerResolutionIssue:
    code: FormalReviewerResolutionIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise FormalReviewerResolutionError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class FormalReviewerResolutionReport:
    """Diagnostic result; no field in this report is an authority grant."""

    status: str
    package_hash_verified: bool
    reviewer_outcomes_complete: bool
    candidate_count: int
    outcome_count: int
    approve_candidate_record_ids: tuple[str, ...]
    reject_candidate_record_ids: tuple[str, ...]
    deferred_candidate_record_ids: tuple[str, ...]
    issues: tuple[FormalReviewerResolutionIssue, ...]
    write_permitted: bool = False
    migration_ready: bool = False
    activation_allowed: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        status = _text(self.status)
        if status not in {"valid", "invalid"}:
            raise FormalReviewerResolutionError("status must be valid or invalid")
        for field_name in (
            "package_hash_verified",
            "reviewer_outcomes_complete",
            "write_permitted",
            "migration_ready",
            "activation_allowed",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise FormalReviewerResolutionError(
                    f"{field_name} must be boolean"
                )
        for field_name in ("candidate_count", "outcome_count"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise FormalReviewerResolutionError(
                    f"{field_name} must be a non-negative integer"
                )
        for field_name in (
            "write_permitted",
            "migration_ready",
            "activation_allowed",
        ):
            if getattr(self, field_name):
                raise FormalReviewerResolutionError(
                    f"formal reviewer resolution cannot set {field_name}=true"
                )
        issues = tuple(self.issues)
        if any(not isinstance(item, FormalReviewerResolutionIssue) for item in issues):
            raise FormalReviewerResolutionError(
                "issues must contain resolution issue values"
            )
        expected_valid = (
            not issues
            and self.package_hash_verified
            and self.reviewer_outcomes_complete
        )
        if (status == "valid") != expected_valid:
            raise FormalReviewerResolutionError(
                "resolution status does not match issues"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(
            self,
            "approve_candidate_record_ids",
            tuple(self.approve_candidate_record_ids),
        )
        object.__setattr__(
            self, "reject_candidate_record_ids", tuple(self.reject_candidate_record_ids)
        )
        object.__setattr__(
            self,
            "deferred_candidate_record_ids",
            tuple(self.deferred_candidate_record_ids),
        )
        object.__setattr__(self, "report_sha256", _sha256(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "package_hash_verified": self.package_hash_verified,
            "reviewer_outcomes_complete": self.reviewer_outcomes_complete,
            "candidate_count": self.candidate_count,
            "outcome_count": self.outcome_count,
            "approve_candidate_record_ids": list(self.approve_candidate_record_ids),
            "reject_candidate_record_ids": list(self.reject_candidate_record_ids),
            "deferred_candidate_record_ids": list(self.deferred_candidate_record_ids),
            "issues": [issue.to_dict() for issue in self.issues],
            "write_permitted": self.write_permitted,
            "migration_ready": self.migration_ready,
            "activation_allowed": self.activation_allowed,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _package_source_hash(package: Mapping[str, Any], role: str) -> str:
    entries = [
        item
        for item in package.get("source_manifest", ())
        if isinstance(item, Mapping) and item.get("role") == role
    ]
    if len(entries) != 1:
        raise FormalReviewerResolutionError(
            f"source_manifest must contain exactly one {role}"
        )
    return _digest(entries[0].get("sha256"), f"source_manifest[{role}].sha256")


def build_formal_reviewer_resolution_template(
    package: Mapping[str, Any],
    *,
    reviewer_group: str = "pending_authorized_review",
) -> dict[str, Any]:
    """Build a blank, hash-bound human reviewer handoff.

    The template carries only candidate identity and B3/B4 source hashes.  It
    intentionally leaves medical disposition, lineage, aggregate/CAS,
    external-action, evidence, reviewer identity, timestamps and rationale
    blank.  It is therefore expected to remain invalid until an authorized
    reviewer supplies every outcome; it can never grant authority by itself.
    """

    if not isinstance(package, Mapping):
        raise FormalReviewerResolutionError("package must be a mapping")
    package_copy = dict(package)
    declared_package_hash = _digest(
        package_copy.pop("package_sha256", None), "package_sha256"
    )
    if _sha256(package_copy) != declared_package_hash:
        raise FormalReviewerResolutionError(
            "package_sha256 does not match package payload"
        )
    candidates = package.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise FormalReviewerResolutionError(
            "package candidates must be a non-empty list"
        )
    b4_hash = _package_source_hash(package, "residual decision package")
    b3_hash = _package_source_hash(package, "mapping dry-run")
    outcomes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise FormalReviewerResolutionError(
                "package candidate entries must be objects"
            )
        record_id = _text(candidate.get("candidate_record_id"))
        fingerprint = _text(candidate.get("candidate_fingerprint"))
        if not record_id or record_id in seen_ids:
            raise FormalReviewerResolutionError(
                "package candidate IDs must be unique and non-empty"
            )
        if not _SHA256_RE.fullmatch(fingerprint) or fingerprint in seen_fingerprints:
            raise FormalReviewerResolutionError(
                "package candidate fingerprints must be unique lowercase SHA-256"
            )
        seen_ids.add(record_id)
        seen_fingerprints.add(fingerprint)
        outcomes.append(
            {
                "review_id": "",
                "candidate_record_id": record_id,
                "candidate_fingerprint": fingerprint,
                "b4_package_sha256": b4_hash,
                "b3_report_hash": b3_hash,
                "reviewer_identity": "",
                "reviewed_at": "",
                "medical_disposition_outcome": "",
                "source_lineage_resolution": "",
                "aggregate_cas_resolution": "",
                "external_action_decision": "",
                "source_evidence": [],
                "aggregate_evidence": [],
                "observed_expected_versions": [],
                "residual_blockers": ["REVIEWER_INPUT_REQUIRED"],
                "rationale": "",
            }
        )
    return {
        "schema_version": "medical_monitoring_formal_reviewer_resolution_v1",
        "template_status": "pending_human_input",
        "package_sha256": declared_package_hash,
        "reviewer_group": reviewer_group,
        "authority": {
            "medical_approval_granted": False,
            "engineering_approval_granted": False,
            "write_authority": False,
            "migration_authority": False,
        },
        "outcomes": outcomes,
    }


def validate_formal_reviewer_resolution(
    package: Mapping[str, Any], resolution: Mapping[str, Any]
) -> FormalReviewerResolutionReport:
    """Validate a reviewer submission without persistence or authority changes."""

    if not isinstance(package, Mapping):
        raise FormalReviewerResolutionError("package must be a mapping")
    package_copy = dict(package)
    declared_package_hash = _digest(
        package_copy.pop("package_sha256", None), "package_sha256"
    )
    package_hash_verified = _sha256(package_copy) == declared_package_hash
    if not package_hash_verified:
        raise FormalReviewerResolutionError(
            "package_sha256 does not match package payload"
        )
    if not isinstance(resolution, Mapping):
        raise FormalReviewerResolutionError("resolution must be a mapping")

    issues: list[FormalReviewerResolutionIssue] = []
    if (
        resolution.get("schema_version")
        != "medical_monitoring_formal_reviewer_resolution_v1"
    ):
        issues.append(
            FormalReviewerResolutionIssue(
                FormalReviewerResolutionIssueCode.REVIEWER_INPUT_SHAPE,
                "schema_version",
                "unexpected formal reviewer resolution schema",
            )
        )
    if _text(resolution.get("package_sha256")) != declared_package_hash:
        issues.append(
            FormalReviewerResolutionIssue(
                FormalReviewerResolutionIssueCode.PACKAGE_HASH_MISMATCH,
                "package_sha256",
                "resolution is not bound to the current canonical package",
            )
        )
    candidates = package.get("candidates")
    if not isinstance(candidates, list):
        raise FormalReviewerResolutionError("package candidates must be a list")
    candidate_by_id: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise FormalReviewerResolutionError(
                "package candidate entries must be objects"
            )
        record_id = _text(candidate.get("candidate_record_id"))
        if not record_id or record_id in candidate_by_id:
            raise FormalReviewerResolutionError(
                "package candidate IDs must be unique and non-empty"
            )
        candidate_by_id[record_id] = candidate
    outcomes = resolution.get("outcomes")
    if not isinstance(outcomes, list):
        raise FormalReviewerResolutionError("resolution outcomes must be a list")
    if len(outcomes) != len(candidate_by_id):
        issues.append(
            FormalReviewerResolutionIssue(
                FormalReviewerResolutionIssueCode.OUTCOME_COUNT_MISMATCH,
                "outcomes",
                f"expected {len(candidate_by_id)} outcomes, observed {len(outcomes)}",
            )
        )
    b4_hash = _package_source_hash(package, "residual decision package")
    b3_hash = _package_source_hash(package, "mapping dry-run")
    seen: set[str] = set()
    approve_ids: list[str] = []
    reject_ids: list[str] = []
    deferred_ids: list[str] = []
    review_contract = package.get("review_contract")
    if not isinstance(review_contract, Mapping):
        raise FormalReviewerResolutionError("package review_contract must be an object")
    raw_allowed_decisions = review_contract.get("allowed_future_outcomes")
    if (
        not isinstance(raw_allowed_decisions, (list, tuple))
        or not raw_allowed_decisions
    ):
        raise FormalReviewerResolutionError(
            "review_contract.allowed_future_outcomes must be a non-empty string array"
        )
    if any(not _is_non_empty_string(item) for item in raw_allowed_decisions):
        raise FormalReviewerResolutionError(
            "review_contract.allowed_future_outcomes must contain non-empty strings"
        )
    allowed_decisions = {item.strip() for item in raw_allowed_decisions}
    seen_review_ids: set[str] = set()
    for outcome in outcomes:
        if not isinstance(outcome, Mapping):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.REVIEWER_INPUT_SHAPE,
                    "outcomes",
                    "each outcome must be an object",
                )
            )
            continue
        record_id = _text(outcome.get("candidate_record_id"))
        subject = record_id or "outcomes"
        review_id = outcome.get("review_id")
        if not _is_non_empty_string(review_id):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.REVIEW_ID_MISSING,
                    subject,
                    "review_id must be a non-empty string",
                )
            )
        else:
            normalized_review_id = review_id.strip()
            if normalized_review_id in seen_review_ids:
                issues.append(
                    FormalReviewerResolutionIssue(
                        FormalReviewerResolutionIssueCode.DUPLICATE_REVIEW_ID,
                        subject,
                        "review_id must uniquely identify one submitted outcome",
                    )
                )
            else:
                seen_review_ids.add(normalized_review_id)
        if record_id in seen:
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.DUPLICATE_OUTCOME,
                    subject,
                    "candidate has more than one submitted outcome",
                )
            )
            continue
        seen.add(record_id)
        candidate = candidate_by_id.get(record_id)
        if candidate is None:
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.UNKNOWN_CANDIDATE,
                    subject,
                    "outcome does not bind to a candidate in the package",
                )
            )
            continue
        if _text(outcome.get("candidate_fingerprint")) != _text(
            candidate.get("candidate_fingerprint")
        ):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.CANDIDATE_FINGERPRINT_MISMATCH,
                    subject,
                    "candidate fingerprint differs from the package",
                )
            )
        if (
            _text(outcome.get("b4_package_sha256")) != b4_hash
            or _text(outcome.get("b3_report_hash")) != b3_hash
        ):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.SOURCE_HASH_MISMATCH,
                    subject,
                    "outcome is not bound to the package's B3/B4 source hashes",
                )
            )
        if not _is_non_empty_string(outcome.get("reviewer_identity")):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.REVIEWER_IDENTITY_MISSING,
                    subject,
                    "reviewer_identity is required; model output is not an identity",
                )
            )
        if not _is_timezone_aware_iso(outcome.get("reviewed_at")):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.REVIEWED_AT_INVALID,
                    subject,
                    "reviewed_at must be ISO-8601 with an explicit timezone",
                )
            )
        decision = _text(outcome.get("medical_disposition_outcome"))
        if decision not in allowed_decisions:
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.MEDICAL_OUTCOME_MISSING,
                    subject,
                    "medical_disposition_outcome must be one of the package's allowed outcomes",
                )
            )
        else:
            (
                approve_ids
                if decision == "approve"
                else reject_ids
                if decision == "reject"
                else deferred_ids
            ).append(record_id)
        lineage = _text(outcome.get("source_lineage_resolution"))
        if lineage not in _ALLOWED_LINEAGE:
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.SOURCE_LINEAGE_MISSING,
                    subject,
                    "source_lineage_resolution is missing or not an allowed explicit value",
                )
            )
        cas = _text(outcome.get("aggregate_cas_resolution"))
        if cas not in _ALLOWED_CAS:
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.AGGREGATE_CAS_MISSING,
                    subject,
                    "aggregate_cas_resolution is missing or not an allowed explicit value",
                )
            )
        if not _is_non_empty_string(outcome.get("external_action_decision")):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.EXTERNAL_ACTION_MISSING,
                    subject,
                    "external_action_decision must be explicit; absence is not no action",
                )
            )
        source_evidence = outcome.get("source_evidence")
        aggregate_evidence = outcome.get("aggregate_evidence")
        evidence_ok = all(
            _is_non_empty_string_array(value)
            for value in (source_evidence, aggregate_evidence)
        )
        if not evidence_ok:
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.EVIDENCE_MISSING,
                    subject,
                    "source_evidence and aggregate_evidence are both required",
                )
            )
        if not _is_non_empty_string(outcome.get("rationale")):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.RATIONALE_MISSING,
                    subject,
                    "review rationale is required",
                )
            )
        residual = outcome.get("residual_blockers", ())
        if not isinstance(residual, list) or any(
            not _is_non_empty_string(item) for item in residual
        ):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.RESIDUAL_BLOCKER_SHAPE,
                    subject,
                    "residual_blockers must be a string array",
                )
            )
        if decision == _APPROVE and (
            residual or lineage != "confirmed" or cas != "confirmed"
        ):
            issues.append(
                FormalReviewerResolutionIssue(
                    FormalReviewerResolutionIssueCode.RESIDUAL_BLOCKER_CONTRADICTION,
                    subject,
                    "approve requires no residual blockers and confirmed lineage/CAS",
                )
            )
        if decision == _APPROVE and cas == "confirmed":
            versions = outcome.get("observed_expected_versions")
            if (
                not isinstance(versions, list)
                or not versions
                or any(
                    isinstance(value, bool) or not isinstance(value, int) or value < 0
                    for value in versions
                )
            ):
                issues.append(
                    FormalReviewerResolutionIssue(
                        FormalReviewerResolutionIssueCode.CAS_VERSION_MISSING,
                        subject,
                        "CAS confirmed requires explicit non-negative observed_expected_versions",
                    )
                )
    missing_ids = set(candidate_by_id) - seen
    for record_id in sorted(missing_ids):
        issues.append(
            FormalReviewerResolutionIssue(
                FormalReviewerResolutionIssueCode.OUTCOME_COUNT_MISMATCH,
                record_id,
                "candidate has no submitted reviewer outcome",
            )
        )
    authority = resolution.get("authority", {})
    if authority and not isinstance(authority, Mapping):
        raise FormalReviewerResolutionError("resolution authority must be an object")
    if isinstance(authority, Mapping):
        for name, value in authority.items():
            if value is not False:
                issues.append(
                    FormalReviewerResolutionIssue(
                        FormalReviewerResolutionIssueCode.AUTHORITY_FLAG_TRUE,
                        f"authority.{name}",
                        "reviewer resolution cannot grant authority",
                    )
                )
    reviewer_complete = (
        len(outcomes) == len(candidate_by_id)
        and not missing_ids
        and len(seen) == len(outcomes)
    )
    valid = not issues and package_hash_verified and reviewer_complete
    return FormalReviewerResolutionReport(
        status="valid" if valid else "invalid",
        package_hash_verified=package_hash_verified,
        reviewer_outcomes_complete=reviewer_complete,
        candidate_count=len(candidate_by_id),
        outcome_count=len(outcomes),
        approve_candidate_record_ids=tuple(sorted(approve_ids)),
        reject_candidate_record_ids=tuple(sorted(reject_ids)),
        deferred_candidate_record_ids=tuple(sorted(deferred_ids)),
        issues=tuple(issues),
    )


__all__ = [
    "build_formal_reviewer_resolution_template",
    "FormalReviewerResolutionError",
    "FormalReviewerResolutionIssue",
    "FormalReviewerResolutionIssueCode",
    "FormalReviewerResolutionReport",
    "validate_formal_reviewer_resolution",
]
