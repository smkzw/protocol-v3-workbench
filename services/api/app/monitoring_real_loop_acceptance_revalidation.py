"""Read-only revalidation of persisted real-loop acceptance evidence.

``monitoring_real_loop_acceptance.py`` validates the in-memory acceptance
matrix.  This module closes the persistence boundary: it reconstructs prompt
and run objects, reruns the canonical matrix validator, compares the persisted
report to the derived report, and can optionally reopen a workspace-relative
JSON file with byte/SHA checks.

The result is evidence freshness only.  It never starts Playwright, calls a
provider, performs login, grants medical/UAT authority, or permits runtime or
release writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .monitoring_real_loop_acceptance import (
    ACCEPTANCE_PROJECT_IDS,
    ACCEPTANCE_ROLES,
    ACCEPTANCE_TESTER_IDS,
    RealLoopAcceptanceError,
    RealLoopAcceptancePrompt,
    RealLoopAcceptanceRun,
    assess_real_loop_acceptance,
)


REAL_LOOP_ACCEPTANCE_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_real_loop_acceptance_revalidation_v3"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVALIDATION_STATUS = {"accepted_for_user_acceptance", "blocked"}
_REQUIRED_PAYLOAD_KEYS = (
    "schema_version",
    "mode",
    "authority_granted",
    "release_ready",
    "prompt_manifest",
    "runs",
    "expected_testers",
    "expected_roles",
    "allowed_project_ids",
    "required_consecutive_clean_rounds",
    "readiness_report_sha256",
    "generalization_evidence_sha256",
    "execution_report_sha256",
    "semantics_binding_sha256",
    "acceptance_report",
)


class RealLoopAcceptanceRevalidationError(ValueError):
    """Raised when a revalidation request cannot be evaluated safely."""


class RealLoopAcceptanceRevalidationIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    SCHEMA_VERSION_INVALID = "schema_version_invalid"
    MODE_INVALID = "mode_invalid"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    RELEASE_READY_FLAG_TRUE = "release_ready_flag_true"
    MATRIX_FIELD_INVALID = "matrix_field_invalid"
    PROMPT_RECONSTRUCTION_FAILED = "prompt_reconstruction_failed"
    RUN_RECONSTRUCTION_FAILED = "run_reconstruction_failed"
    REPORT_MISSING = "report_missing"
    REPORT_SHAPE_INVALID = "report_shape_invalid"
    REPORT_STATUS_MISMATCH = "report_status_mismatch"
    REPORT_DERIVED_MISMATCH = "report_derived_mismatch"
    REPORT_HASH_MISMATCH = "report_hash_mismatch"
    EVIDENCE_CHAIN_HASH_INVALID = "evidence_chain_hash_invalid"
    FILE_PATH_UNSAFE = "file_path_unsafe"
    FILE_MISSING = "file_missing"
    FILE_NOT_REGULAR = "file_not_regular"
    FILE_SYMLINK_UNSUPPORTED = "file_symlink_unsupported"
    FILE_BYTES_MISMATCH = "file_bytes_mismatch"
    FILE_SHA256_MISMATCH = "file_sha256_mismatch"
    FILE_JSON_INVALID = "file_json_invalid"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise RealLoopAcceptanceRevalidationError(
            "real-loop revalidation payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(_SHA256_RE.fullmatch(value))
    )


def _is_canonical_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and value == value.lower()
        and _SHA256_RE.fullmatch(value) is not None
    )


@dataclass(frozen=True)
class RealLoopAcceptanceRevalidationIssue:
    code: RealLoopAcceptanceRevalidationIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise RealLoopAcceptanceRevalidationError(
                "revalidation issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopAcceptanceRevalidationReport:
    """Immutable persisted-evidence identity result; never a release decision."""

    status: str
    evidence_fresh: bool
    payload_valid: bool
    report_matches: bool
    file_checked: bool
    file_fresh: bool
    acceptance_status: str
    acceptance_complete_observed: bool
    tester_count: int
    role_count: int
    run_count: int
    issues: tuple[RealLoopAcceptanceRevalidationIssue, ...]
    readiness_report_sha256: str = ""
    generalization_evidence_sha256: str = ""
    execution_report_sha256: str = ""
    semantics_binding_sha256: str = ""
    schema_version: str = REAL_LOOP_ACCEPTANCE_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    release_ready: bool = False
    medical_confirmation_permitted: bool = False
    runtime_write_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != REAL_LOOP_ACCEPTANCE_REVALIDATION_SCHEMA_VERSION:
            raise RealLoopAcceptanceRevalidationError(
                "unsupported real-loop revalidation schema"
            )
        if self.status not in {"fresh", "blocked"}:
            raise RealLoopAcceptanceRevalidationError(
                "invalid real-loop revalidation status"
            )
        if self.read_only is not True or self.authority_granted is not False:
            raise RealLoopAcceptanceRevalidationError(
                "real-loop revalidation must remain read-only and non-authoritative"
            )
        for name in (
            "release_ready",
            "medical_confirmation_permitted",
            "runtime_write_permitted",
        ):
            if getattr(self, name) is not False:
                raise RealLoopAcceptanceRevalidationError(f"{name} must remain false")
        for name in (
            "evidence_fresh",
            "payload_valid",
            "report_matches",
            "file_checked",
            "file_fresh",
            "acceptance_complete_observed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise RealLoopAcceptanceRevalidationError(f"{name} must be boolean")
        for name in ("tester_count", "role_count", "run_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise RealLoopAcceptanceRevalidationError(
                    f"{name} must be a non-negative integer"
                )
        if self.file_fresh and not self.file_checked:
            raise RealLoopAcceptanceRevalidationError(
                "file_fresh cannot be true when file_checked is false"
            )
        if self.acceptance_status not in _REVALIDATION_STATUS:
            raise RealLoopAcceptanceRevalidationError("acceptance_status is invalid")
        for field_name in (
            "readiness_report_sha256",
            "generalization_evidence_sha256",
            "execution_report_sha256",
            "semantics_binding_sha256",
        ):
            raw_value = getattr(self, field_name)
            if raw_value is None or raw_value == "":
                value = ""
            elif not _is_canonical_sha256(raw_value):
                raise RealLoopAcceptanceRevalidationError(
                    f"{field_name} must be a lowercase SHA-256"
                )
            else:
                value = raw_value
            object.__setattr__(self, field_name, value)
        if self.status == "fresh" and any(
            not _text(getattr(self, field_name))
            for field_name in (
                "readiness_report_sha256",
                "generalization_evidence_sha256",
                "execution_report_sha256",
                "semantics_binding_sha256",
            )
        ):
            raise RealLoopAcceptanceRevalidationError(
                "fresh revalidation requires the upstream evidence chain hashes"
            )
        issues = tuple(self.issues)
        if any(
            not isinstance(item, RealLoopAcceptanceRevalidationIssue) for item in issues
        ):
            raise RealLoopAcceptanceRevalidationError("issues contain an invalid value")
        expected_fresh = (
            not issues
            and self.payload_valid
            and self.report_matches
            and (not self.file_checked or self.file_fresh)
        )
        if (
            self.evidence_fresh != expected_fresh
            or (self.status == "fresh") != expected_fresh
        ):
            raise RealLoopAcceptanceRevalidationError(
                "real-loop revalidation status does not match evidence state"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "payload_valid": self.payload_valid,
            "report_matches": self.report_matches,
            "file_checked": self.file_checked,
            "file_fresh": self.file_fresh,
            "acceptance_status": self.acceptance_status,
            "acceptance_complete_observed": self.acceptance_complete_observed,
            "tester_count": self.tester_count,
            "role_count": self.role_count,
            "run_count": self.run_count,
            "readiness_report_sha256": self.readiness_report_sha256,
            "generalization_evidence_sha256": self.generalization_evidence_sha256,
            "execution_report_sha256": self.execution_report_sha256,
            "semantics_binding_sha256": self.semantics_binding_sha256,
            "issues": [item.to_dict() for item in self.issues],
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "release_ready": self.release_ready,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
            "runtime_write_permitted": self.runtime_write_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[RealLoopAcceptanceRevalidationIssue],
    code: RealLoopAcceptanceRevalidationIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(RealLoopAcceptanceRevalidationIssue(code, subject, detail))


def _list_field(
    payload: Mapping[str, Any],
    key: str,
    issues: list[RealLoopAcceptanceRevalidationIssue],
) -> tuple[Any, ...] | None:
    value = payload.get(key)
    if not isinstance(value, list):
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.MATRIX_FIELD_INVALID,
            key,
            f"{key} must be a list",
        )
        return None
    return tuple(value)


def _reconstruct(
    payload: Mapping[str, Any],
    issues: list[RealLoopAcceptanceRevalidationIssue],
) -> (
    tuple[
        tuple[RealLoopAcceptancePrompt, ...],
        tuple[RealLoopAcceptanceRun, ...],
        dict[str, Any],
    ]
    | None
):
    missing = [key for key in _REQUIRED_PAYLOAD_KEYS if key not in payload]
    if missing:
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "payload",
            f"persisted acceptance evidence is missing required keys: {missing}",
        )
        return None
    if (
        payload.get("schema_version")
        != REAL_LOOP_ACCEPTANCE_REVALIDATION_SCHEMA_VERSION
    ):
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.SCHEMA_VERSION_INVALID,
            "schema_version",
            "persisted evidence schema_version does not match the revalidation contract",
        )
    if payload.get("mode") != "read_only":
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.MODE_INVALID,
            "mode",
            "persisted evidence must declare mode=read_only",
        )
    if payload.get("authority_granted") is not False:
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
            "authority_granted",
            "persisted acceptance evidence cannot grant authority",
        )
    if payload.get("release_ready") is not False:
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.RELEASE_READY_FLAG_TRUE,
            "release_ready",
            "persisted acceptance evidence cannot declare release readiness",
        )
    chain_hashes: dict[str, str] = {}
    for field_name in (
        "readiness_report_sha256",
        "generalization_evidence_sha256",
        "execution_report_sha256",
        "semantics_binding_sha256",
    ):
        raw_hash = payload.get(field_name)
        if not _valid_sha(raw_hash):
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.EVIDENCE_CHAIN_HASH_INVALID,
                field_name,
                "persisted evidence must carry the exact lowercase SHA-256 for every upstream chain link",
            )
            chain_hashes[field_name] = ""
        else:
            chain_hashes[field_name] = raw_hash
    raw_prompts = _list_field(payload, "prompt_manifest", issues)
    raw_runs = _list_field(payload, "runs", issues)
    expected_testers = _list_field(payload, "expected_testers", issues)
    expected_roles = _list_field(payload, "expected_roles", issues)
    allowed_projects = _list_field(payload, "allowed_project_ids", issues)
    required_rounds = payload.get("required_consecutive_clean_rounds")
    if (
        isinstance(required_rounds, bool)
        or not isinstance(required_rounds, int)
        or required_rounds < 2
    ):
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.MATRIX_FIELD_INVALID,
            "required_consecutive_clean_rounds",
            "required_consecutive_clean_rounds must be an integer >= 2",
        )
    if any(
        value is None
        for value in (
            raw_prompts,
            raw_runs,
            expected_testers,
            expected_roles,
            allowed_projects,
        )
    ):
        return None
    prompts: list[RealLoopAcceptancePrompt] = []
    for index, item in enumerate(raw_prompts):
        if not isinstance(item, Mapping):
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.PROMPT_RECONSTRUCTION_FAILED,
                f"prompt_manifest[{index}]",
                "prompt manifest rows must be objects",
            )
            continue
        try:
            prompts.append(
                RealLoopAcceptancePrompt(
                    prompt_ref=item["prompt_ref"],
                    prompt_sha256=item["prompt_sha256"],
                )
            )
        except (KeyError, TypeError, ValueError, RealLoopAcceptanceError) as exc:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.PROMPT_RECONSTRUCTION_FAILED,
                f"prompt_manifest[{index}]",
                str(exc),
            )
    runs: list[RealLoopAcceptanceRun] = []
    run_fields = (
        "run_id",
        "tester_id",
        "role",
        "project_id",
        "round_number",
        "prompt_ref",
        "prompt_sha256",
        "tester_route",
        "route_policy_verified",
        "route_window_verified",
        "started_at",
        "ended_at",
        "login_mode",
        "api_login_used",
        "playwright_session_ref",
        "browser_evidence_ref",
        "scientific_evidence_ref",
        "run_status",
        "issue_severities",
        "issue_refs",
        "failure_detail",
        "repair_evidence_refs",
        "retest_of",
    )
    for index, item in enumerate(raw_runs):
        if not isinstance(item, Mapping):
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.RUN_RECONSTRUCTION_FAILED,
                f"runs[{index}]",
                "run rows must be objects",
            )
            continue
        missing_run_fields = [key for key in run_fields if key not in item]
        if missing_run_fields:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.RUN_RECONSTRUCTION_FAILED,
                f"runs[{index}]",
                f"run row is missing required keys: {missing_run_fields}",
            )
            continue
        try:
            runs.append(RealLoopAcceptanceRun(**{key: item[key] for key in run_fields}))
        except (KeyError, TypeError, ValueError, RealLoopAcceptanceError) as exc:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.RUN_RECONSTRUCTION_FAILED,
                f"runs[{index}]",
                str(exc),
            )
    matrix = {
        "expected_testers": tuple(expected_testers),
        "expected_roles": tuple(expected_roles),
        "allowed_project_ids": tuple(allowed_projects),
        "required_consecutive_clean_rounds": required_rounds,
        **chain_hashes,
    }
    expected_matrix = {
        "expected_testers": tuple(ACCEPTANCE_TESTER_IDS),
        "expected_roles": tuple(ACCEPTANCE_ROLES),
        "allowed_project_ids": tuple(ACCEPTANCE_PROJECT_IDS),
        "required_consecutive_clean_rounds": 2,
    }
    for key, expected in expected_matrix.items():
        observed = matrix[key]
        if observed != expected:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.MATRIX_FIELD_INVALID,
                key,
                (
                    "persisted matrix must match the frozen acceptance matrix; "
                    f"expected={expected!r}, observed={observed!r}"
                ),
            )
    return tuple(prompts), tuple(runs), matrix


def _evaluate_payload(
    payload: Mapping[str, Any], *, file_checked: bool, file_fresh: bool
) -> RealLoopAcceptanceRevalidationReport:
    issues: list[RealLoopAcceptanceRevalidationIssue] = []
    reconstructed = _reconstruct(payload, issues)
    computed = None
    matrix: dict[str, Any] = {}
    if reconstructed is not None:
        prompts, runs, matrix = reconstructed
        try:
            computed = assess_real_loop_acceptance(
                runs,
                prompt_manifest=prompts,
                expected_testers=matrix["expected_testers"],
                expected_roles=matrix["expected_roles"],
                allowed_project_ids=matrix["allowed_project_ids"],
                required_consecutive_clean_rounds=matrix[
                    "required_consecutive_clean_rounds"
                ],
                readiness_report_sha256=matrix["readiness_report_sha256"],
                generalization_evidence_sha256=matrix[
                    "generalization_evidence_sha256"
                ],
                execution_report_sha256=matrix["execution_report_sha256"],
                semantics_binding_sha256=matrix["semantics_binding_sha256"],
            )
        except (TypeError, ValueError, RealLoopAcceptanceError) as exc:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.RUN_RECONSTRUCTION_FAILED,
                "acceptance_matrix",
                str(exc),
            )
    persisted_report = payload.get("acceptance_report")
    if not isinstance(persisted_report, Mapping):
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.REPORT_MISSING,
            "acceptance_report",
            "acceptance_report must be a persisted object",
        )
    report_matches = False
    if computed is not None and isinstance(persisted_report, Mapping):
        expected_report = computed.to_dict()
        report_matches = dict(persisted_report) == expected_report
        if not report_matches:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.REPORT_DERIVED_MISMATCH,
                "acceptance_report",
                "persisted acceptance report does not match the canonical matrix assessment",
            )
        expected_hash = persisted_report.get("report_sha256")
        if (
            not _valid_sha(expected_hash)
            or expected_hash != expected_report["report_sha256"]
        ):
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.REPORT_HASH_MISMATCH,
                "acceptance_report.report_sha256",
                f"expected persisted={expected_hash!r}, computed={expected_report['report_sha256']!r}",
            )
    acceptance_status = "blocked"
    acceptance_complete = False
    tester_count = role_count = run_count = 0
    if isinstance(persisted_report, Mapping):
        raw_status = persisted_report.get("status")
        if raw_status in _REVALIDATION_STATUS:
            acceptance_status = raw_status
        else:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.REPORT_STATUS_MISMATCH,
                "acceptance_report.status",
                "status must be blocked or accepted_for_user_acceptance",
            )
        raw_acceptance_complete = persisted_report.get("acceptance_complete")
        if not isinstance(raw_acceptance_complete, bool):
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.REPORT_SHAPE_INVALID,
                "acceptance_report.acceptance_complete",
                "acceptance_complete must be a strict boolean; string or numeric coercion is not accepted",
            )
        else:
            acceptance_complete = raw_acceptance_complete
        for field_name in ("tester_count", "role_count", "run_count"):
            value = persisted_report.get(field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                _issue(
                    issues,
                    RealLoopAcceptanceRevalidationIssueCode.REPORT_SHAPE_INVALID,
                    f"acceptance_report.{field_name}",
                    f"{field_name} must be a non-negative integer",
                )
            else:
                if field_name == "tester_count":
                    tester_count = value
                elif field_name == "role_count":
                    role_count = value
                else:
                    run_count = value
    structural_codes = {
        RealLoopAcceptanceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
        RealLoopAcceptanceRevalidationIssueCode.SCHEMA_VERSION_INVALID,
        RealLoopAcceptanceRevalidationIssueCode.MODE_INVALID,
        RealLoopAcceptanceRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
        RealLoopAcceptanceRevalidationIssueCode.RELEASE_READY_FLAG_TRUE,
        RealLoopAcceptanceRevalidationIssueCode.MATRIX_FIELD_INVALID,
        RealLoopAcceptanceRevalidationIssueCode.PROMPT_RECONSTRUCTION_FAILED,
        RealLoopAcceptanceRevalidationIssueCode.RUN_RECONSTRUCTION_FAILED,
        RealLoopAcceptanceRevalidationIssueCode.EVIDENCE_CHAIN_HASH_INVALID,
        RealLoopAcceptanceRevalidationIssueCode.REPORT_MISSING,
        RealLoopAcceptanceRevalidationIssueCode.REPORT_SHAPE_INVALID,
        RealLoopAcceptanceRevalidationIssueCode.REPORT_STATUS_MISMATCH,
    }
    payload_valid = not any(issue.code in structural_codes for issue in issues)
    evidence_fresh = (
        not issues
        and payload_valid
        and report_matches
        and (not file_checked or file_fresh)
    )
    return RealLoopAcceptanceRevalidationReport(
        status="fresh" if evidence_fresh else "blocked",
        evidence_fresh=evidence_fresh,
        payload_valid=payload_valid,
        report_matches=report_matches,
        file_checked=file_checked,
        file_fresh=file_fresh,
        acceptance_status=acceptance_status,
        acceptance_complete_observed=acceptance_complete,
        tester_count=tester_count,
        role_count=role_count,
        run_count=run_count,
        issues=tuple(issues),
        readiness_report_sha256=matrix.get("readiness_report_sha256", ""),
        generalization_evidence_sha256=matrix.get(
            "generalization_evidence_sha256", ""
        ),
        execution_report_sha256=matrix.get("execution_report_sha256", ""),
        semantics_binding_sha256=matrix.get("semantics_binding_sha256", ""),
        read_only=True,
        authority_granted=False,
        release_ready=False,
        medical_confirmation_permitted=False,
        runtime_write_permitted=False,
    )


def revalidate_real_loop_acceptance_payload(
    payload: Mapping[str, Any],
) -> RealLoopAcceptanceRevalidationReport:
    """Validate a persisted acceptance mapping without filesystem access."""

    if not isinstance(payload, Mapping):
        raise RealLoopAcceptanceRevalidationError(
            "real-loop acceptance payload must be a mapping"
        )
    return _evaluate_payload(payload, file_checked=False, file_fresh=False)


def _safe_file_path(
    raw_path: Any,
    *,
    workspace_root: Path,
    issues: list[RealLoopAcceptanceRevalidationIssue],
) -> Path | None:
    path_text = raw_path.strip() if isinstance(raw_path, str) else ""
    path = Path(path_text) if path_text else Path(".")
    if (
        not path_text
        or path.is_absolute()
        or "\\" in path_text
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.FILE_PATH_UNSAFE,
            "path",
            "acceptance evidence path must be a clean workspace-relative POSIX path",
        )
        return None
    root = workspace_root.resolve()
    candidate = workspace_root / path
    current = workspace_root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED,
                "path",
                "acceptance evidence path and parent components must not be symlinks",
            )
            return None
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError:
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.FILE_PATH_UNSAFE,
            "path",
            "acceptance evidence path escapes the workspace root",
        )
        return None
    return candidate


def revalidate_real_loop_acceptance_file(
    path: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    workspace_root: str | Path,
) -> RealLoopAcceptanceRevalidationReport:
    """Reopen and validate one persisted acceptance file without side effects."""

    issues: list[RealLoopAcceptanceRevalidationIssue] = []
    root = Path(workspace_root)
    candidate = _safe_file_path(path, workspace_root=root, issues=issues)
    if candidate is None:
        return _blocked_file_report(issues)
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes < 0
        or not _valid_sha(expected_sha256)
    ):
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "file_metadata",
            "expected_bytes must be a non-negative integer and expected_sha256 a lowercase SHA-256",
        )
    if not candidate.exists():
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.FILE_MISSING,
            "path",
            f"acceptance evidence file does not exist: {path}",
        )
    elif not candidate.is_file():
        _issue(
            issues,
            RealLoopAcceptanceRevalidationIssueCode.FILE_NOT_REGULAR,
            "path",
            f"acceptance evidence path is not a regular file: {path}",
        )
    else:
        observed_bytes = candidate.stat().st_size
        observed_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if observed_bytes != expected_bytes:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.FILE_BYTES_MISMATCH,
                "path",
                f"expected bytes={expected_bytes}, observed bytes={observed_bytes}",
            )
        if observed_sha != expected_sha256:
            _issue(
                issues,
                RealLoopAcceptanceRevalidationIssueCode.FILE_SHA256_MISMATCH,
                "path",
                f"expected sha256={expected_sha256}, observed sha256={observed_sha}",
            )
        if not issues:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                _issue(
                    issues,
                    RealLoopAcceptanceRevalidationIssueCode.FILE_JSON_INVALID,
                    "path",
                    str(exc),
                )
            else:
                if not isinstance(payload, Mapping):
                    _issue(
                        issues,
                        RealLoopAcceptanceRevalidationIssueCode.FILE_JSON_INVALID,
                        "path",
                        "acceptance evidence JSON root must be an object",
                    )
                else:
                    return _evaluate_payload(
                        payload, file_checked=True, file_fresh=True
                    )
    return _blocked_file_report(issues)


def _blocked_file_report(
    issues: list[RealLoopAcceptanceRevalidationIssue],
) -> RealLoopAcceptanceRevalidationReport:
    return RealLoopAcceptanceRevalidationReport(
        status="blocked",
        evidence_fresh=False,
        payload_valid=False,
        report_matches=False,
        file_checked=True,
        file_fresh=False,
        acceptance_status="blocked",
        acceptance_complete_observed=False,
        tester_count=0,
        role_count=0,
        run_count=0,
        issues=tuple(issues),
        read_only=True,
        authority_granted=False,
        release_ready=False,
        medical_confirmation_permitted=False,
        runtime_write_permitted=False,
    )


__all__ = [
    "REAL_LOOP_ACCEPTANCE_REVALIDATION_SCHEMA_VERSION",
    "RealLoopAcceptanceRevalidationError",
    "RealLoopAcceptanceRevalidationIssue",
    "RealLoopAcceptanceRevalidationIssueCode",
    "RealLoopAcceptanceRevalidationReport",
    "revalidate_real_loop_acceptance_file",
    "revalidate_real_loop_acceptance_payload",
]
