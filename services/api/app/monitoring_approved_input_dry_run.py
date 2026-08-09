"""Fail-closed, pure validation of a formal monitoring reviewer package.

The dry-run consumes an already hash-bound reviewer/provenance package and an
explicit read-only source-manifest observation.  It never writes, migrates,
activates, or infers a missing medical, lineage, or aggregate/CAS decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from .monitoring_source_batch_preflight import (
    CANONICAL_MONITORING_PROJECT_IDS,
    SourceBatchPreflightError,
    SourceBatchPreflightReport,
    SourceBatchRecord,
    assess_source_batch_preflight,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_AUTHORITY_FLAGS = (
    "medical_approval_granted",
    "engineering_approval_granted",
    "write_authority",
    "migration_authority",
    "activation_allowed",
    "event_creation_allowed",
    "projection_allowed",
    "source_token_synthesized",
    "aggregate_cas_applied",
)


class ApprovedInputDryRunError(ValueError):
    """Raised when the package shape cannot be evaluated safely."""


class ApprovedInputIssueCode(str, Enum):
    PACKAGE_HASH_MISMATCH = "package_hash_mismatch"
    SOURCE_MANIFEST_UNVERIFIED = "source_manifest_unverified"
    SOURCE_MANIFEST_MISMATCH = "source_manifest_mismatch"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    B6_GATE_NOT_READY = "b6_gate_not_ready"
    REVIEW_OUTCOME_MISSING = "review_outcome_missing"
    SOURCE_LINEAGE_UNPROVEN = "source_lineage_unproven"
    AGGREGATE_CAS_UNPROVEN = "aggregate_cas_unproven"
    RESIDUAL_BLOCKER = "residual_blocker"
    SOURCE_BATCH_BINDING_MISSING = "source_batch_binding_missing"
    SOURCE_BATCH_BINDING_MISMATCH = "source_batch_binding_mismatch"
    SOURCE_BATCH_PREFLIGHT_BLOCKED = "source_batch_preflight_blocked"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise ApprovedInputDryRunError("package must be JSON-serializable") from exc


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _digest(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not _SHA256_RE.fullmatch(text):
        raise ApprovedInputDryRunError(f"{field_name} must be a SHA-256 hex digest")
    return text


def _text(value: Any) -> str:
    return str(value or "").strip()


@dataclass(frozen=True)
class ApprovedInputDryRunIssue:
    code: ApprovedInputIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise ApprovedInputDryRunError("issue subject and detail are required")
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class ApprovedInputDryRunReport:
    status: str
    approved_input_ready: bool
    source_manifest_replay_complete: bool
    reviewer_outcomes_complete: bool
    source_lineage_complete: bool
    aggregate_cas_complete: bool
    residual_blockers_clear: bool
    write_permitted: bool
    migration_ready: bool
    issues: tuple[ApprovedInputDryRunIssue, ...]
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        status = _text(self.status)
        if status not in {"blocked", "ready"}:
            raise ApprovedInputDryRunError("status must be blocked or ready")
        object.__setattr__(self, "status", status)
        for name in (
            "approved_input_ready",
            "source_manifest_replay_complete",
            "reviewer_outcomes_complete",
            "source_lineage_complete",
            "aggregate_cas_complete",
            "residual_blockers_clear",
            "write_permitted",
            "migration_ready",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ApprovedInputDryRunError(f"{name} must be boolean")
        issues = tuple(self.issues)
        if any(not isinstance(item, ApprovedInputDryRunIssue) for item in issues):
            raise ApprovedInputDryRunError(
                "issues must contain ApprovedInputDryRunIssue values"
            )
        if self.write_permitted or self.migration_ready:
            raise ApprovedInputDryRunError(
                "approved-input dry-run cannot grant write or migration authority"
            )
        expected_ready = not issues and all(
            (
                self.source_manifest_replay_complete,
                self.reviewer_outcomes_complete,
                self.source_lineage_complete,
                self.aggregate_cas_complete,
                self.residual_blockers_clear,
            )
        )
        if (
            self.approved_input_ready != expected_ready
            or (status == "ready") != expected_ready
        ):
            raise ApprovedInputDryRunError(
                "report readiness flags do not match issues and evidence"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _sha256(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "approved_input_ready": self.approved_input_ready,
            "source_manifest_replay_complete": self.source_manifest_replay_complete,
            "reviewer_outcomes_complete": self.reviewer_outcomes_complete,
            "source_lineage_complete": self.source_lineage_complete,
            "aggregate_cas_complete": self.aggregate_cas_complete,
            "residual_blockers_clear": self.residual_blockers_clear,
            "write_permitted": self.write_permitted,
            "migration_ready": self.migration_ready,
            "issues": [item.to_dict() for item in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


@dataclass(frozen=True)
class ControlledApprovedInputDryRunReport:
    """Approved-input dry-run with a revalidated source-batch binding.

    ``ApprovedInputDryRunReport`` remains the package/reviewer diagnostic.  A
    future controlled admission must use this stricter wrapper: the formal
    package has to carry a hash-bound ``source_batch_bindings`` list, and the
    wrapper reopens every declared listing path through
    :func:`assess_source_batch_preflight`.  This contract is still diagnostic;
    it never grants runtime, provider, write, migration, or medical authority.
    """

    status: str
    approved_input_ready: bool
    base_report: ApprovedInputDryRunReport
    source_batch_preflight: SourceBatchPreflightReport | None
    source_batch_preflight_complete: bool
    source_batch_binding_sha256: str
    issues: tuple[ApprovedInputDryRunIssue, ...]
    write_permitted: bool = False
    migration_ready: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.status not in {"blocked", "ready"}:
            raise ApprovedInputDryRunError("status must be blocked or ready")
        for name in (
            "approved_input_ready",
            "source_batch_preflight_complete",
            "write_permitted",
            "migration_ready",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ApprovedInputDryRunError(f"{name} must be boolean")
        if not isinstance(self.base_report, ApprovedInputDryRunReport):
            raise ApprovedInputDryRunError("base_report has an invalid type")
        if self.source_batch_preflight is not None and not isinstance(
            self.source_batch_preflight, SourceBatchPreflightReport
        ):
            raise ApprovedInputDryRunError("source_batch_preflight has an invalid type")
        if self.write_permitted or self.migration_ready:
            raise ApprovedInputDryRunError(
                "controlled approved-input dry-run cannot grant write or migration authority"
            )
        binding_digest = _text(self.source_batch_binding_sha256)
        if binding_digest:
            _digest(binding_digest, "source_batch_binding_sha256")
        object.__setattr__(self, "source_batch_binding_sha256", binding_digest)
        if self.source_batch_preflight is None and self.source_batch_preflight_complete:
            raise ApprovedInputDryRunError(
                "source_batch_preflight_complete requires a preflight report"
            )
        issues = tuple(self.issues)
        if any(not isinstance(item, ApprovedInputDryRunIssue) for item in issues):
            raise ApprovedInputDryRunError(
                "issues must contain ApprovedInputDryRunIssue values"
            )
        object.__setattr__(self, "issues", issues)
        expected_ready = (
            self.base_report.approved_input_ready
            and self.source_batch_preflight_complete
            and not issues
        )
        if (
            self.approved_input_ready != expected_ready
            or (self.status == "ready") != expected_ready
        ):
            raise ApprovedInputDryRunError(
                "controlled report readiness flags do not match evidence"
            )
        object.__setattr__(self, "report_sha256", _sha256(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "approved_input_ready": self.approved_input_ready,
            "base_report_sha256": self.base_report.report_sha256,
            "source_batch_preflight_complete": self.source_batch_preflight_complete,
            "source_batch_binding_sha256": self.source_batch_binding_sha256,
            "source_batch_preflight_report_sha256": (
                self.source_batch_preflight.report_sha256
                if self.source_batch_preflight is not None
                else ""
            ),
            "issues": [item.to_dict() for item in self.issues],
            "write_permitted": self.write_permitted,
            "migration_ready": self.migration_ready,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "base_report": self.base_report.to_dict(),
            "source_batch_preflight": (
                self.source_batch_preflight.to_dict()
                if self.source_batch_preflight is not None
                else None
            ),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def canonical_source_batch_binding_sha256(
    records: Iterable[SourceBatchRecord],
) -> str:
    """Return the stable digest for a declared source-batch binding list."""

    rows = tuple(records)
    if any(not isinstance(item, SourceBatchRecord) for item in rows):
        raise ApprovedInputDryRunError(
            "source batch bindings must contain SourceBatchRecord values"
        )
    if not rows:
        raise ApprovedInputDryRunError("source batch bindings must not be empty")
    payload = [
        item.to_dict()
        for item in sorted(
            rows,
            key=lambda item: (item.project_id, item.batch_ref, item.listing_path),
        )
    ]
    return _sha256(payload)


def _manifest_status(
    package: Mapping[str, Any],
    observed_source_manifest: Mapping[str, tuple[int, str]] | None,
    issues: list[ApprovedInputDryRunIssue],
) -> bool:
    manifest = package.get("source_manifest")
    if not isinstance(manifest, list) or not manifest:
        raise ApprovedInputDryRunError("source_manifest must be a non-empty list")
    entries: dict[str, tuple[int, str]] = {}
    for item in manifest:
        if not isinstance(item, Mapping):
            raise ApprovedInputDryRunError("source_manifest entries must be objects")
        path = _text(item.get("path"))
        if (
            not path
            or not isinstance(item.get("bytes"), int)
            or isinstance(item.get("bytes"), bool)
            or item["bytes"] < 0
        ):
            raise ApprovedInputDryRunError(
                "source_manifest entry path/bytes is invalid"
            )
        digest = _digest(item.get("sha256"), f"source_manifest[{path}].sha256")
        if path in entries:
            raise ApprovedInputDryRunError(f"source_manifest repeats path: {path}")
        entries[path] = (item["bytes"], digest)
    if observed_source_manifest is None:
        issues.append(
            ApprovedInputDryRunIssue(
                ApprovedInputIssueCode.SOURCE_MANIFEST_UNVERIFIED,
                "source_manifest",
                "no explicit current byte/hash replay was supplied",
            )
        )
        return False
    if set(observed_source_manifest) != set(entries):
        missing = sorted(set(entries) - set(observed_source_manifest))
        extra = sorted(set(observed_source_manifest) - set(entries))
        issues.append(
            ApprovedInputDryRunIssue(
                ApprovedInputIssueCode.SOURCE_MANIFEST_MISMATCH,
                "source_manifest",
                f"observed manifest differs; missing={missing}, extra={extra}",
            )
        )
        return False
    mismatches = []
    for path, expected in entries.items():
        observed = observed_source_manifest[path]
        if observed != expected:
            mismatches.append(f"{path}: expected={expected}, observed={observed}")
    if mismatches:
        issues.append(
            ApprovedInputDryRunIssue(
                ApprovedInputIssueCode.SOURCE_MANIFEST_MISMATCH,
                "source_manifest",
                "; ".join(mismatches),
            )
        )
        return False
    return True


def dry_run_approved_input(
    package: Mapping[str, Any],
    *,
    observed_source_manifest: Mapping[str, tuple[int, str]] | None = None,
) -> ApprovedInputDryRunReport:
    """Evaluate a package without persistence, authority, or inference."""

    if not isinstance(package, Mapping):
        raise ApprovedInputDryRunError("package must be a mapping")
    package_copy = dict(package)
    claimed_package_hash = _digest(
        package_copy.pop("package_sha256", None), "package_sha256"
    )
    if _sha256(package_copy) != claimed_package_hash:
        raise ApprovedInputDryRunError(
            "package_sha256 does not match canonical package payload"
        )

    issues: list[ApprovedInputDryRunIssue] = []
    source_manifest_ok = _manifest_status(package, observed_source_manifest, issues)

    authority = package.get("authority")
    if not isinstance(authority, Mapping):
        raise ApprovedInputDryRunError("authority must be an object")
    missing_authority = [
        name for name in _REQUIRED_AUTHORITY_FLAGS if name not in authority
    ]
    if missing_authority:
        raise ApprovedInputDryRunError(
            f"authority is missing required flags: {missing_authority}"
        )
    authority_ok = True
    for name, value in authority.items():
        if value is not False:
            authority_ok = False
            issues.append(
                ApprovedInputDryRunIssue(
                    ApprovedInputIssueCode.AUTHORITY_FLAG_TRUE,
                    f"authority.{name}",
                    "dry-run input contains a true/non-boolean authority flag",
                )
            )

    gate_state = package.get("gate_state")
    b6 = gate_state.get("b6") if isinstance(gate_state, Mapping) else None
    if not isinstance(b6, Mapping):
        raise ApprovedInputDryRunError("gate_state.b6 is required")
    candidate_count = b6.get("candidate_count")
    outcome_count = b6.get("outcome_count")
    blocker_lists = (
        b6.get("pending_candidate_record_ids"),
        b6.get("missing_candidate_record_ids"),
        b6.get("rejected_candidate_record_ids"),
        b6.get("unresolved_blockers"),
    )
    b6_ready = (
        b6.get("status") == "approved_input_ready"
        and isinstance(candidate_count, int)
        and not isinstance(candidate_count, bool)
        and candidate_count >= 0
        and isinstance(outcome_count, int)
        and not isinstance(outcome_count, bool)
        and outcome_count == candidate_count
        and all(isinstance(value, list) and not value for value in blocker_lists)
    )
    if not b6_ready:
        issues.append(
            ApprovedInputDryRunIssue(
                ApprovedInputIssueCode.B6_GATE_NOT_READY,
                "gate_state.b6",
                f"B6 status={b6.get('status')!r}; approved_input_ready requires an explicit blocker-free review gate",
            )
        )

    candidates = package.get("candidates")
    cases = package.get("aggregate_cases")
    if not isinstance(candidates, list) or not isinstance(cases, list):
        raise ApprovedInputDryRunError("candidates and aggregate_cases must be lists")
    expected_count = package.get("candidate_count")
    if expected_count != len(candidates):
        raise ApprovedInputDryRunError("candidate_count does not match candidates")
    case_by_id = {
        str(item.get("case_id")): item for item in cases if isinstance(item, Mapping)
    }
    reviewer_complete = True
    lineage_complete = True
    blockers_clear = True
    cas_complete = True
    reported_case_ids: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ApprovedInputDryRunError("candidate entries must be objects")
        record_id = _text(candidate.get("candidate_record_id"))
        if not record_id:
            raise ApprovedInputDryRunError("candidate_record_id is required")
        required = candidate.get("required_reviewer_input")
        missing_fields = []
        if not isinstance(required, Mapping):
            missing_fields = ["required_reviewer_input"]
        else:
            missing_fields = [
                name
                for name, value in required.items()
                if _text(value) in {"", "not_provided"}
            ]
        if missing_fields:
            reviewer_complete = False
            issues.append(
                ApprovedInputDryRunIssue(
                    ApprovedInputIssueCode.REVIEW_OUTCOME_MISSING,
                    record_id,
                    f"required reviewer input remains missing: {sorted(missing_fields)}",
                )
            )
        relation = _text(candidate.get("source_version_relation"))
        legacy = candidate.get("legacy_source_version")
        legacy_token = legacy.get("source_token") if isinstance(legacy, Mapping) else ""
        if relation != "exact_after_identity" or not _text(legacy_token):
            lineage_complete = False
            issues.append(
                ApprovedInputDryRunIssue(
                    ApprovedInputIssueCode.SOURCE_LINEAGE_UNPROVEN,
                    record_id,
                    "source relation is not exact-after-identity with an observed legacy source token",
                )
            )
        candidate_blockers = candidate.get("residual_blockers")
        if candidate_blockers:
            blockers_clear = False
            issues.append(
                ApprovedInputDryRunIssue(
                    ApprovedInputIssueCode.RESIDUAL_BLOCKER,
                    record_id,
                    f"residual blockers remain: {list(candidate_blockers)}",
                )
            )
        case_id = _text(candidate.get("aggregate_case_id"))
        case = case_by_id.get(case_id)
        if case is None:
            cas_complete = False
            issues.append(
                ApprovedInputDryRunIssue(
                    ApprovedInputIssueCode.AGGREGATE_CAS_UNPROVEN,
                    record_id,
                    f"aggregate case is missing: {case_id}",
                )
            )
        elif (
            case.get("metadata_chain_complete") is not True
            or case.get("cas_replay_complete") is not True
        ):
            cas_complete = False
            if case_id not in reported_case_ids:
                issues.append(
                    ApprovedInputDryRunIssue(
                        ApprovedInputIssueCode.AGGREGATE_CAS_UNPROVEN,
                        case_id,
                        f"CAS replay is incomplete; issue_codes={case.get('issue_codes', [])}",
                    )
                )
                reported_case_ids.add(case_id)
    ready = (
        source_manifest_ok
        and authority_ok
        and b6_ready
        and reviewer_complete
        and lineage_complete
        and cas_complete
        and blockers_clear
        and not issues
    )
    return ApprovedInputDryRunReport(
        status="ready" if ready else "blocked",
        approved_input_ready=ready,
        source_manifest_replay_complete=source_manifest_ok,
        reviewer_outcomes_complete=reviewer_complete,
        source_lineage_complete=lineage_complete,
        aggregate_cas_complete=cas_complete,
        residual_blockers_clear=blockers_clear,
        write_permitted=False,
        migration_ready=False,
        issues=tuple(issues),
    )


def _package_source_batch_bindings(
    package: Mapping[str, Any],
    issues: list[ApprovedInputDryRunIssue],
) -> tuple[SourceBatchRecord, ...] | None:
    raw_bindings = package.get("source_batch_bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        issues.append(
            ApprovedInputDryRunIssue(
                ApprovedInputIssueCode.SOURCE_BATCH_BINDING_MISSING,
                "source_batch_bindings",
                "controlled approved-input requires a non-empty hash-bound source batch list",
            )
        )
        return None
    try:
        rows = tuple(SourceBatchRecord(**item) for item in raw_bindings)
    except (TypeError, SourceBatchPreflightError) as exc:
        issues.append(
            ApprovedInputDryRunIssue(
                ApprovedInputIssueCode.SOURCE_BATCH_BINDING_MISMATCH,
                "source_batch_bindings",
                f"source batch binding list is structurally invalid: {exc}",
            )
        )
        return None
    return rows


def dry_run_approved_input_with_source_preflight(
    package: Mapping[str, Any],
    *,
    observed_source_manifest: Mapping[str, tuple[int, str]] | None = None,
    required_project_ids: Iterable[str] = CANONICAL_MONITORING_PROJECT_IDS,
) -> ControlledApprovedInputDryRunReport:
    """Run the approved-input dry-run with a live source-batch revalidation.

    The package must include ``source_batch_bindings`` and its
    ``source_batch_binding_sha256`` is covered by the package hash.  The
    binding rows are used only as declarations; ``assess_source_batch_preflight``
    reopens the actual files and checks bytes, SHA-256, class, status, full
    snapshot proof, duplicate content, and two-batch coverage per project.
    """

    base_report = dry_run_approved_input(
        package, observed_source_manifest=observed_source_manifest
    )
    issues = list(base_report.issues)
    rows = _package_source_batch_bindings(package, issues)
    binding_sha256 = ""
    preflight: SourceBatchPreflightReport | None = None
    source_complete = False

    if rows is not None:
        binding_sha256 = canonical_source_batch_binding_sha256(rows)
        declared_binding_sha256 = _text(package.get("source_batch_binding_sha256"))
        if not declared_binding_sha256:
            issues.append(
                ApprovedInputDryRunIssue(
                    ApprovedInputIssueCode.SOURCE_BATCH_BINDING_MISSING,
                    "source_batch_binding_sha256",
                    "the package must hash-bind its exact source batch declarations",
                )
            )
        else:
            try:
                declared_binding_sha256 = _digest(
                    declared_binding_sha256, "source_batch_binding_sha256"
                )
            except ApprovedInputDryRunError as exc:
                issues.append(
                    ApprovedInputDryRunIssue(
                        ApprovedInputIssueCode.SOURCE_BATCH_BINDING_MISMATCH,
                        "source_batch_binding_sha256",
                        str(exc),
                    )
                )
            else:
                if declared_binding_sha256 != binding_sha256:
                    issues.append(
                        ApprovedInputDryRunIssue(
                            ApprovedInputIssueCode.SOURCE_BATCH_BINDING_MISMATCH,
                            "source_batch_binding_sha256",
                            f"declared={declared_binding_sha256}, observed={binding_sha256}",
                        )
                    )
        try:
            preflight = assess_source_batch_preflight(
                rows, required_project_ids=required_project_ids
            )
        except (SourceBatchPreflightError, ValueError) as exc:
            issues.append(
                ApprovedInputDryRunIssue(
                    ApprovedInputIssueCode.SOURCE_BATCH_PREFLIGHT_BLOCKED,
                    "source_batch_bindings",
                    f"source batch preflight could not be completed: {exc}",
                )
            )
        else:
            if not preflight.source_evidence_complete:
                detail = "; ".join(
                    f"{item.code.value}:{item.subject}:{item.detail}"
                    for item in preflight.issues
                )
                issues.append(
                    ApprovedInputDryRunIssue(
                        ApprovedInputIssueCode.SOURCE_BATCH_PREFLIGHT_BLOCKED,
                        "source_batch_bindings",
                        f"source batch preflight is blocked: {detail}",
                    )
                )
            else:
                source_complete = True

    return ControlledApprovedInputDryRunReport(
        status="ready"
        if base_report.approved_input_ready and source_complete and not issues
        else "blocked",
        approved_input_ready=bool(
            base_report.approved_input_ready and source_complete and not issues
        ),
        base_report=base_report,
        source_batch_preflight=preflight,
        source_batch_preflight_complete=source_complete,
        source_batch_binding_sha256=binding_sha256,
        issues=tuple(issues),
        write_permitted=False,
        migration_ready=False,
    )


__all__ = [
    "ControlledApprovedInputDryRunReport",
    "ApprovedInputDryRunError",
    "ApprovedInputDryRunIssue",
    "ApprovedInputDryRunReport",
    "ApprovedInputIssueCode",
    "canonical_source_batch_binding_sha256",
    "dry_run_approved_input",
    "dry_run_approved_input_with_source_preflight",
]
