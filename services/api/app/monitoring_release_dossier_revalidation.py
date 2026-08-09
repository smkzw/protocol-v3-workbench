"""Read-only revalidation of a persisted commercial release dossier.

``monitoring_release_dossier.py`` is the canonical in-memory contract.  This
module closes the persistence boundary: it reconstructs that object from a
JSON payload, compares all derived fields and the canonical digest, and can
optionally reopen a workspace-relative JSON file with byte/SHA checks.

The result is evidence freshness only.  It never grants release, migration,
runtime, provider or medical authority, even when the persisted dossier says
that its own controls are complete.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from .monitoring_release_dossier import (
    RELEASE_DOSSIER_SCHEMA_VERSION,
    MonitoringReleaseDossier,
    MonitoringReleaseDossierError,
    MonitoringReleaseDossierSection,
    MonitoringReleaseDossierSignoff,
    MonitoringResidualRiskDisposition,
)


RELEASE_DOSSIER_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_release_dossier_revalidation_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DossierStatus = {"passed", "partial", "unproven", "blocked"}
_REQUIRED_PAYLOAD_KEYS = (
    "schema_version",
    "dossier_id",
    "release_version",
    "generated_at",
    "sections",
    "signoffs",
    "residual_risks",
    "authority_granted",
    "status",
    "release_ready",
    "blocking_reasons",
    "dossier_sha256",
)


class ReleaseDossierRevalidationError(ValueError):
    """Raised when a revalidation request cannot be evaluated safely."""


class ReleaseDossierRevalidationIssueCode(str, Enum):
    PAYLOAD_SHAPE_INVALID = "payload_shape_invalid"
    SCHEMA_VERSION_INVALID = "schema_version_invalid"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"
    RELEASE_READY_FIELD_INVALID = "release_ready_field_invalid"
    STATUS_FIELD_INVALID = "status_field_invalid"
    BLOCKING_REASONS_INVALID = "blocking_reasons_invalid"
    DOSSIER_RECONSTRUCTION_FAILED = "dossier_reconstruction_failed"
    DOSSIER_HASH_MISSING = "dossier_hash_missing"
    DOSSIER_HASH_MISMATCH = "dossier_hash_mismatch"
    DERIVED_STATUS_MISMATCH = "derived_status_mismatch"
    DERIVED_SECTIONS_MISMATCH = "derived_sections_mismatch"
    DERIVED_SIGNOFFS_MISMATCH = "derived_signoffs_mismatch"
    DERIVED_RESIDUAL_RISKS_MISMATCH = "derived_residual_risks_mismatch"
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
        raise ReleaseDossierRevalidationError(
            "dossier revalidation payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value == value.strip()
        and bool(_SHA256_RE.fullmatch(value))
    )


@dataclass(frozen=True)
class ReleaseDossierRevalidationIssue:
    code: ReleaseDossierRevalidationIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        subject = _text(self.subject)
        detail = _text(self.detail)
        if not subject or not detail:
            raise ReleaseDossierRevalidationError(
                "revalidation issue subject and detail are required"
            )
        object.__setattr__(self, "subject", subject)
        object.__setattr__(self, "detail", detail)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class ReleaseDossierRevalidationReport:
    """Immutable persisted-dossier result; never a release decision."""

    status: str
    evidence_fresh: bool
    payload_valid: bool
    dossier_hash_matches: bool
    derived_fields_match: bool
    file_checked: bool
    file_fresh: bool
    dossier_status: str
    release_ready_observed: bool
    issues: tuple[ReleaseDossierRevalidationIssue, ...]
    schema_version: str = RELEASE_DOSSIER_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != RELEASE_DOSSIER_REVALIDATION_SCHEMA_VERSION:
            raise ReleaseDossierRevalidationError(
                "unsupported dossier revalidation schema"
            )
        if self.status not in {"fresh", "blocked"}:
            raise ReleaseDossierRevalidationError("invalid dossier revalidation status")
        if self.read_only is not True or self.authority_granted is not False:
            raise ReleaseDossierRevalidationError(
                "dossier revalidation must remain read-only and non-authoritative"
            )
        for name in (
            "evidence_fresh",
            "payload_valid",
            "dossier_hash_matches",
            "derived_fields_match",
            "file_checked",
            "file_fresh",
            "release_ready_observed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ReleaseDossierRevalidationError(f"{name} must be boolean")
        if self.dossier_status not in _DossierStatus:
            raise ReleaseDossierRevalidationError("dossier_status is invalid")
        if self.file_fresh and not self.file_checked:
            raise ReleaseDossierRevalidationError(
                "file_fresh cannot be true when file_checked is false"
            )
        issues = tuple(self.issues)
        if any(
            not isinstance(item, ReleaseDossierRevalidationIssue) for item in issues
        ):
            raise ReleaseDossierRevalidationError("issues contain an invalid value")
        expected_fresh = (
            not issues
            and self.payload_valid
            and self.dossier_hash_matches
            and self.derived_fields_match
            and (not self.file_checked or self.file_fresh)
        )
        if (
            self.evidence_fresh != expected_fresh
            or (self.status == "fresh") != expected_fresh
        ):
            raise ReleaseDossierRevalidationError(
                "dossier revalidation status does not match evidence state"
            )
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "payload_valid": self.payload_valid,
            "dossier_hash_matches": self.dossier_hash_matches,
            "derived_fields_match": self.derived_fields_match,
            "file_checked": self.file_checked,
            "file_fresh": self.file_fresh,
            "dossier_status": self.dossier_status,
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
    issues: list[ReleaseDossierRevalidationIssue],
    code: ReleaseDossierRevalidationIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(ReleaseDossierRevalidationIssue(code, subject, detail))


def _tuple_field(
    payload: Mapping[str, Any],
    key: str,
    issues: list[ReleaseDossierRevalidationIssue],
) -> tuple[Any, ...] | None:
    value = payload.get(key)
    if not isinstance(value, list):
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            key,
            f"{key} must be a list",
        )
        return None
    return tuple(value)


def _reconstruct(
    payload: Mapping[str, Any],
    issues: list[ReleaseDossierRevalidationIssue],
) -> MonitoringReleaseDossier | None:
    missing = [key for key in _REQUIRED_PAYLOAD_KEYS if key not in payload]
    if missing:
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "payload",
            f"persisted dossier is missing required keys: {missing}",
        )
        return None
    if payload.get("schema_version") != RELEASE_DOSSIER_SCHEMA_VERSION:
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.SCHEMA_VERSION_INVALID,
            "schema_version",
            "persisted dossier schema_version does not match the canonical dossier contract",
        )
    if payload.get("authority_granted") is not False:
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
            "authority_granted",
            "persisted dossier cannot grant authority",
        )
    if not isinstance(payload.get("release_ready"), bool):
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.RELEASE_READY_FIELD_INVALID,
            "release_ready",
            "release_ready must be a boolean",
        )
    if payload.get("status") not in _DossierStatus:
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.STATUS_FIELD_INVALID,
            "status",
            "status must be one of passed/partial/unproven/blocked",
        )
    if not isinstance(payload.get("blocking_reasons"), list) or any(
        not isinstance(item, str) for item in payload.get("blocking_reasons", [])
    ):
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.BLOCKING_REASONS_INVALID,
            "blocking_reasons",
            "blocking_reasons must be a list of strings",
        )
    expected_hash = payload.get("dossier_sha256")
    if not _valid_sha(expected_hash):
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.DOSSIER_HASH_MISSING,
            "dossier_sha256",
            "dossier_sha256 must be a lowercase SHA-256",
        )

    raw_sections = _tuple_field(payload, "sections", issues)
    raw_signoffs = _tuple_field(payload, "signoffs", issues)
    raw_residual_risks = _tuple_field(payload, "residual_risks", issues)
    if raw_sections is None or raw_signoffs is None or raw_residual_risks is None:
        return None
    try:
        sections = tuple(
            MonitoringReleaseDossierSection(
                section_id=item["section_id"],
                status=item["status"],
                evidence_ids=tuple(item["evidence_ids"]),
                evidence_sha256=item["evidence_sha256"],
                covered_control_ids=tuple(item["covered_control_ids"]),
                unmet_control_ids=tuple(item["unmet_control_ids"]),
                summary=item["summary"],
            )
            for item in raw_sections
            if isinstance(item, Mapping)
        )
        if len(sections) != len(raw_sections):
            raise MonitoringReleaseDossierError("sections must contain objects")
        signoffs = tuple(
            MonitoringReleaseDossierSignoff(
                role=item["role"],
                actor_id=item["actor_id"],
                signed_at=item["signed_at"],
                evidence_sha256=item["evidence_sha256"],
            )
            for item in raw_signoffs
            if isinstance(item, Mapping)
        )
        if len(signoffs) != len(raw_signoffs):
            raise MonitoringReleaseDossierError("signoffs must contain objects")
        residual_risks = tuple(
            MonitoringResidualRiskDisposition(
                risk_id=item["risk_id"],
                severity=item["severity"],
                status=item["status"],
                owner_id=item["owner_id"],
                decision_evidence_sha256=item["decision_evidence_sha256"],
                rationale=item["rationale"],
            )
            for item in raw_residual_risks
            if isinstance(item, Mapping)
        )
        if len(residual_risks) != len(raw_residual_risks):
            raise MonitoringReleaseDossierError("residual_risks must contain objects")
        return MonitoringReleaseDossier(
            dossier_id=payload["dossier_id"],
            release_version=payload["release_version"],
            generated_at=payload["generated_at"],
            sections=sections,
            signoffs=signoffs,
            residual_risks=residual_risks,
            authority_granted=payload["authority_granted"],
            schema_version=payload["schema_version"],
        )
    except (KeyError, TypeError, ValueError, MonitoringReleaseDossierError) as exc:
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.DOSSIER_RECONSTRUCTION_FAILED,
            "payload",
            str(exc),
        )
        return None


def _evaluate_payload(
    payload: Mapping[str, Any], *, file_checked: bool, file_fresh: bool
) -> ReleaseDossierRevalidationReport:
    issues: list[ReleaseDossierRevalidationIssue] = []
    dossier = _reconstruct(payload, issues)
    payload_valid = dossier is not None and not any(
        issue.code
        in {
            ReleaseDossierRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            ReleaseDossierRevalidationIssueCode.SCHEMA_VERSION_INVALID,
            ReleaseDossierRevalidationIssueCode.AUTHORITY_FLAG_TRUE,
            ReleaseDossierRevalidationIssueCode.RELEASE_READY_FIELD_INVALID,
            ReleaseDossierRevalidationIssueCode.STATUS_FIELD_INVALID,
            ReleaseDossierRevalidationIssueCode.BLOCKING_REASONS_INVALID,
            ReleaseDossierRevalidationIssueCode.DOSSIER_RECONSTRUCTION_FAILED,
            ReleaseDossierRevalidationIssueCode.DOSSIER_HASH_MISSING,
        }
        for issue in issues
    )
    dossier_status = (
        _text(payload.get("status"))
        if payload.get("status") in _DossierStatus
        else "blocked"
    )
    release_ready = (
        payload.get("release_ready")
        if isinstance(payload.get("release_ready"), bool)
        else False
    )
    hash_matches = False
    derived_matches = False
    if dossier is not None:
        computed = dossier.to_dict()
        expected_hash = payload.get("dossier_sha256")
        hash_matches = (
            _valid_sha(expected_hash) and expected_hash == computed["dossier_sha256"]
        )
        if not hash_matches:
            _issue(
                issues,
                ReleaseDossierRevalidationIssueCode.DOSSIER_HASH_MISMATCH,
                "dossier_sha256",
                f"expected persisted={expected_hash!r}, computed={computed['dossier_sha256']!r}",
            )
        comparisons = {
            "status": ReleaseDossierRevalidationIssueCode.DERIVED_STATUS_MISMATCH,
            "release_ready": ReleaseDossierRevalidationIssueCode.DERIVED_STATUS_MISMATCH,
            "blocking_reasons": ReleaseDossierRevalidationIssueCode.DERIVED_STATUS_MISMATCH,
            "sections": ReleaseDossierRevalidationIssueCode.DERIVED_SECTIONS_MISMATCH,
            "signoffs": ReleaseDossierRevalidationIssueCode.DERIVED_SIGNOFFS_MISMATCH,
            "residual_risks": ReleaseDossierRevalidationIssueCode.DERIVED_RESIDUAL_RISKS_MISMATCH,
        }
        derived_matches = True
        for key, code in comparisons.items():
            if payload.get(key) != computed.get(key):
                derived_matches = False
                _issue(
                    issues,
                    code,
                    key,
                    f"persisted={payload.get(key)!r}, computed={computed.get(key)!r}",
                )
    return ReleaseDossierRevalidationReport(
        status="fresh"
        if not issues
        and payload_valid
        and hash_matches
        and derived_matches
        and (not file_checked or file_fresh)
        else "blocked",
        evidence_fresh=not issues
        and payload_valid
        and hash_matches
        and derived_matches
        and (not file_checked or file_fresh),
        payload_valid=payload_valid,
        dossier_hash_matches=hash_matches,
        derived_fields_match=derived_matches,
        file_checked=file_checked,
        file_fresh=file_fresh,
        dossier_status=dossier_status,
        release_ready_observed=release_ready,
        issues=tuple(issues),
        read_only=True,
        authority_granted=False,
    )


def revalidate_release_dossier_payload(
    payload: Mapping[str, Any],
) -> ReleaseDossierRevalidationReport:
    """Validate a persisted dossier mapping without filesystem access."""

    if not isinstance(payload, Mapping):
        raise ReleaseDossierRevalidationError("dossier payload must be a mapping")
    return _evaluate_payload(payload, file_checked=False, file_fresh=False)


def _safe_file_path(
    raw_path: Any,
    *,
    workspace_root: Path,
    issues: list[ReleaseDossierRevalidationIssue],
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
            ReleaseDossierRevalidationIssueCode.FILE_PATH_UNSAFE,
            "path",
            "dossier path must be a clean workspace-relative POSIX path",
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
                ReleaseDossierRevalidationIssueCode.FILE_SYMLINK_UNSUPPORTED,
                "path",
                "dossier path and parent components must not be symlinks",
            )
            return None
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError:
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.FILE_PATH_UNSAFE,
            "path",
            "dossier path escapes the workspace root",
        )
        return None
    return candidate


def revalidate_release_dossier_file(
    path: str,
    *,
    expected_bytes: int,
    expected_sha256: str,
    workspace_root: str | Path,
) -> ReleaseDossierRevalidationReport:
    """Reopen and validate one persisted dossier file without side effects."""

    issues: list[ReleaseDossierRevalidationIssue] = []
    root = Path(workspace_root)
    candidate = _safe_file_path(path, workspace_root=root, issues=issues)
    if candidate is None:
        return ReleaseDossierRevalidationReport(
            status="blocked",
            evidence_fresh=False,
            payload_valid=False,
            dossier_hash_matches=False,
            derived_fields_match=False,
            file_checked=True,
            file_fresh=False,
            dossier_status="blocked",
            release_ready_observed=False,
            issues=tuple(issues),
            read_only=True,
            authority_granted=False,
        )
    if (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
        or not _valid_sha(expected_sha256)
    ):
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.PAYLOAD_SHAPE_INVALID,
            "file_metadata",
            "expected_bytes must be a non-negative integer and expected_sha256 a lowercase SHA-256",
        )
    if not candidate.exists():
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.FILE_MISSING,
            "path",
            f"dossier file does not exist: {path}",
        )
    elif not candidate.is_file():
        _issue(
            issues,
            ReleaseDossierRevalidationIssueCode.FILE_NOT_REGULAR,
            "path",
            f"dossier path is not a regular file: {path}",
        )
    else:
        observed_bytes = candidate.stat().st_size
        observed_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if observed_bytes != expected_bytes:
            _issue(
                issues,
                ReleaseDossierRevalidationIssueCode.FILE_BYTES_MISMATCH,
                "path",
                f"expected bytes={expected_bytes}, observed bytes={observed_bytes}",
            )
        if observed_sha != expected_sha256:
            _issue(
                issues,
                ReleaseDossierRevalidationIssueCode.FILE_SHA256_MISMATCH,
                "path",
                f"expected sha256={expected_sha256}, observed sha256={observed_sha}",
            )
        if not issues:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                _issue(
                    issues,
                    ReleaseDossierRevalidationIssueCode.FILE_JSON_INVALID,
                    "path",
                    str(exc),
                )
            else:
                report = (
                    _evaluate_payload(payload, file_checked=True, file_fresh=True)
                    if isinstance(payload, Mapping)
                    else None
                )
                if report is None:
                    _issue(
                        issues,
                        ReleaseDossierRevalidationIssueCode.FILE_JSON_INVALID,
                        "path",
                        "dossier JSON root must be an object",
                    )
                else:
                    return report
    return ReleaseDossierRevalidationReport(
        status="blocked",
        evidence_fresh=False,
        payload_valid=False,
        dossier_hash_matches=False,
        derived_fields_match=False,
        file_checked=True,
        file_fresh=False,
        dossier_status="blocked",
        release_ready_observed=False,
        issues=tuple(issues),
        read_only=True,
        authority_granted=False,
    )


__all__ = [
    "RELEASE_DOSSIER_REVALIDATION_SCHEMA_VERSION",
    "ReleaseDossierRevalidationError",
    "ReleaseDossierRevalidationIssue",
    "ReleaseDossierRevalidationIssueCode",
    "ReleaseDossierRevalidationReport",
    "revalidate_release_dossier_file",
    "revalidate_release_dossier_payload",
]
