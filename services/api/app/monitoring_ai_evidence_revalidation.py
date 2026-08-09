"""Read-only revalidation of the persisted P4 AI evidence boundary.

The P4 quality, matrix, prompt-release and release-gate modules are pure
in-memory contracts.  This module is the small persistence seam around them:
it reopens the current commercial coverage record, verifies its declared source
files, and makes missing real observations/matrix/release snapshots explicit.
It never calls a provider, opens the AI queue, mutates SQLite, activates a
prompt/model or grants medical/release authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


P4_AI_EVIDENCE_REVALIDATION_SCHEMA_VERSION = (
    "medical_monitoring_p4_ai_evidence_revalidation_v1"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AiEvidenceRevalidationIssueCode(str, Enum):
    COVERAGE_MISSING = "coverage_missing"
    COVERAGE_NOT_FILE = "coverage_not_file"
    COVERAGE_SYMLINK_UNSUPPORTED = "coverage_symlink_unsupported"
    COVERAGE_PATH_UNSAFE = "coverage_path_unsafe"
    COVERAGE_JSON_INVALID = "coverage_json_invalid"
    COVERAGE_SHAPE_INVALID = "coverage_shape_invalid"
    SOURCE_MISSING = "source_missing"
    SOURCE_NOT_FILE = "source_not_file"
    SOURCE_SYMLINK_UNSUPPORTED = "source_symlink_unsupported"
    SOURCE_PATH_UNSAFE = "source_path_unsafe"
    SOURCE_BYTES_INVALID = "source_bytes_invalid"
    SOURCE_SHA256_INVALID = "source_sha256_invalid"
    SOURCE_BYTES_MISMATCH = "source_bytes_mismatch"
    SOURCE_SHA256_MISMATCH = "source_sha256_mismatch"
    INDEPENDENT_AI_STATUS_DRIFT = "independent_ai_status_drift"
    DECISION_STATUS_DRIFT = "decision_status_drift"
    AUTHORITY_FLAG_DRIFT = "authority_flag_drift"
    REAL_OBSERVATIONS_MISSING = "real_observations_missing"
    EVALUATION_MATRIX_MISSING = "evaluation_matrix_missing"
    RELEASE_SNAPSHOT_MISSING = "release_snapshot_missing"
    ARTIFACT_INVALID = "artifact_invalid"


@dataclass(frozen=True)
class AiEvidenceSource:
    source_id: str
    path: str
    expected_bytes: int
    expected_sha256: str
    role: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "path": self.path,
            "expected_bytes": self.expected_bytes,
            "expected_sha256": self.expected_sha256,
            "role": self.role,
        }


@dataclass(frozen=True)
class AiEvidenceIssue:
    code: AiEvidenceRevalidationIssueCode
    subject: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "subject": self.subject,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class AiEvidenceRevalidationReport:
    status: str
    evidence_fresh: bool
    product_ai_evidence_complete: bool
    coverage_status: str
    independent_ai_gate_status: str
    declared_source_count: int
    observed_source_count: int
    missing_artifact_ids: tuple[str, ...]
    issues: tuple[AiEvidenceIssue, ...]
    observed_sources: tuple[dict[str, Any], ...] = ()
    schema_version: str = P4_AI_EVIDENCE_REVALIDATION_SCHEMA_VERSION
    read_only: bool = True
    authority_granted: bool = False
    provider_call_permitted: bool = False
    runtime_activation_permitted: bool = False
    write_permitted: bool = False
    medical_confirmation_permitted: bool = False
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.status not in {"fresh", "blocked", "invalid"}:
            raise ValueError("unsupported P4 AI evidence revalidation status")
        if any(not isinstance(item, AiEvidenceIssue) for item in self.issues):
            raise TypeError("issues must contain AiEvidenceIssue values")
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "evidence_fresh": self.evidence_fresh,
            "product_ai_evidence_complete": self.product_ai_evidence_complete,
            "coverage_status": self.coverage_status,
            "independent_ai_gate_status": self.independent_ai_gate_status,
            "declared_source_count": self.declared_source_count,
            "observed_source_count": self.observed_source_count,
            "missing_artifact_ids": list(self.missing_artifact_ids),
            "issues": [item.to_dict() for item in self.issues],
            "observed_sources": list(self.observed_sources),
            "read_only": self.read_only,
            "authority_granted": self.authority_granted,
            "provider_call_permitted": self.provider_call_permitted,
            "runtime_activation_permitted": self.runtime_activation_permitted,
            "write_permitted": self.write_permitted,
            "medical_confirmation_permitted": self.medical_confirmation_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "report_sha256": self.report_sha256}


REQUIRED_P4_ARTIFACTS: tuple[tuple[str, str], ...] = (
    (
        "real_product_ai_observations",
        "records/active_slices/medical_monitoring_p4_ai_quality_observations_20260802/OBSERVATIONS.json",
    ),
    (
        "evaluation_matrix_snapshot",
        "records/active_slices/medical_monitoring_p4_ai_evaluation_matrix_20260802/PERSISTED_EVALUATION_MATRIX.json",
    ),
    (
        "prompt_model_release_snapshot",
        "records/active_slices/medical_monitoring_p4_ai_release_gate_20260802/PERSISTED_RELEASE_GATE.json",
    ),
)


def _digest(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_relative(
    root: Path,
    raw: Any,
    *,
    code: AiEvidenceRevalidationIssueCode,
    subject: str,
    issues: list[AiEvidenceIssue],
) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        issues.append(
            AiEvidenceIssue(
                code, subject, "path must be a non-empty workspace-relative string"
            )
        )
        return None
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        issues.append(
            AiEvidenceIssue(
                code, subject, "absolute or traversal paths are not accepted"
            )
        )
        return None
    return root / candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_text(value: Any, field: str, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{field} must be a non-empty string")
    return cleaned


def _source_from_payload(
    value: Any, issues: list[AiEvidenceIssue]
) -> AiEvidenceSource | None:
    if not isinstance(value, Mapping):
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.COVERAGE_SHAPE_INVALID,
                "sources",
                "each source must be an object",
            )
        )
        return None
    try:
        raw_bytes = value["bytes"]
        if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, int):
            raise TypeError("bytes must be an integer")
        source = AiEvidenceSource(
            source_id=_source_text(value["id"], "id"),
            path=_source_text(value["path"], "path"),
            expected_bytes=raw_bytes,
            expected_sha256=_source_text(value["sha256"], "sha256"),
            role=_source_text(value.get("role", ""), "role", required=False),
        )
    except (KeyError, TypeError, ValueError) as exc:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.COVERAGE_SHAPE_INVALID,
                "sources",
                f"invalid source entry: {exc}",
            )
        )
        return None
    if source.expected_bytes < 0:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.SOURCE_BYTES_INVALID,
                source.source_id,
                "expected bytes must be non-negative",
            )
        )
    if not _SHA256_RE.fullmatch(source.expected_sha256):
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.SOURCE_SHA256_INVALID,
                source.source_id,
                "expected SHA-256 must be 64 lowercase hex characters",
            )
        )
    return source


def _check_source(
    root: Path, source: AiEvidenceSource, issues: list[AiEvidenceIssue]
) -> dict[str, Any] | None:
    path = _safe_relative(
        root,
        source.path,
        code=AiEvidenceRevalidationIssueCode.SOURCE_PATH_UNSAFE,
        subject=source.source_id,
        issues=issues,
    )
    if path is None:
        return None
    if path.is_symlink():
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.SOURCE_SYMLINK_UNSUPPORTED,
                source.source_id,
                "declared source must not be a symlink",
            )
        )
        return None
    if not path.exists():
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.SOURCE_MISSING,
                source.source_id,
                f"missing declared source: {source.path}",
            )
        )
        return None
    if not path.is_file():
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.SOURCE_NOT_FILE,
                source.source_id,
                f"declared source is not a regular file: {source.path}",
            )
        )
        return None
    observed_bytes = path.stat().st_size
    observed_sha256 = _sha256(path)
    if observed_bytes != source.expected_bytes:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.SOURCE_BYTES_MISMATCH,
                source.source_id,
                f"expected {source.expected_bytes} bytes, observed {observed_bytes}",
            )
        )
    if observed_sha256 != source.expected_sha256:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.SOURCE_SHA256_MISMATCH,
                source.source_id,
                f"expected {source.expected_sha256}, observed {observed_sha256}",
            )
        )
    return {
        "source_id": source.source_id,
        "path": source.path,
        "bytes": observed_bytes,
        "sha256": observed_sha256,
        "role": source.role,
    }


def revalidate_p4_ai_evidence(
    coverage_path: str | Path,
    *,
    workspace_root: str | Path,
    required_artifacts: Iterable[tuple[str, str]] = REQUIRED_P4_ARTIFACTS,
) -> AiEvidenceRevalidationReport:
    """Reopen the current P4 coverage and report evidence availability.

    ``coverage_path`` and every declared source/artifact path are interpreted
    relative to ``workspace_root``.  This function is intentionally diagnostic:
    even a future fresh report cannot permit provider calls or activation.
    """

    root = Path(workspace_root).resolve()
    issues: list[AiEvidenceIssue] = []
    coverage_raw = str(coverage_path)
    coverage_file = _safe_relative(
        root,
        coverage_raw,
        code=AiEvidenceRevalidationIssueCode.COVERAGE_PATH_UNSAFE,
        subject="coverage",
        issues=issues,
    )
    coverage: dict[str, Any] = {}
    if coverage_file is not None:
        if coverage_file.is_symlink():
            issues.append(
                AiEvidenceIssue(
                    AiEvidenceRevalidationIssueCode.COVERAGE_SYMLINK_UNSUPPORTED,
                    "coverage",
                    "coverage must not be a symlink",
                )
            )
        elif not coverage_file.exists():
            issues.append(
                AiEvidenceIssue(
                    AiEvidenceRevalidationIssueCode.COVERAGE_MISSING,
                    "coverage",
                    f"missing coverage file: {coverage_raw}",
                )
            )
        elif not coverage_file.is_file():
            issues.append(
                AiEvidenceIssue(
                    AiEvidenceRevalidationIssueCode.COVERAGE_NOT_FILE,
                    "coverage",
                    "coverage must be a regular file",
                )
            )
        else:
            try:
                loaded = json.loads(coverage_file.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("coverage JSON root must be an object")
                coverage = loaded
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                issues.append(
                    AiEvidenceIssue(
                        AiEvidenceRevalidationIssueCode.COVERAGE_JSON_INVALID,
                        "coverage",
                        str(exc),
                    )
                )

    raw_sources = coverage.get("sources", ())
    if not isinstance(raw_sources, list):
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.COVERAGE_SHAPE_INVALID,
                "sources",
                "coverage sources must be a list",
            )
        )
        raw_sources = ()
    sources = tuple(
        source
        for value in raw_sources
        if (source := _source_from_payload(value, issues)) is not None
    )
    observed_sources = tuple(_check_source(root, source, issues) for source in sources)
    observed_sources = tuple(item for item in observed_sources if item is not None)

    gate_results = coverage.get("gate_results", ())
    if not isinstance(gate_results, list):
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.COVERAGE_SHAPE_INVALID,
                "gate_results",
                "gate_results must be a list",
            )
        )
        gate_results = ()
    ai_rows = [
        row
        for row in gate_results
        if isinstance(row, Mapping) and row.get("gate_id") == "independent_product_ai"
    ]
    independent_status = str(ai_rows[0].get("status", "")) if len(ai_rows) == 1 else ""
    if independent_status != "partial":
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.INDEPENDENT_AI_STATUS_DRIFT,
                "independent_product_ai",
                "current coverage must remain partial until real P4 evidence exists",
            )
        )

    decision = coverage.get("decision")
    decision_status = (
        str(decision.get("status", "")) if isinstance(decision, Mapping) else ""
    )
    release_ready = (
        decision.get("release_ready") if isinstance(decision, Mapping) else None
    )
    if decision_status != "blocked" or release_ready is not False:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.DECISION_STATUS_DRIFT,
                "decision",
                "current P4 coverage must remain blocked with release_ready=false",
            )
        )
    if coverage.get("authority_granted") is not False or (
        isinstance(decision, Mapping)
        and "authority_granted" in decision
        and decision.get("authority_granted") is not False
    ):
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.AUTHORITY_FLAG_DRIFT,
                "authority",
                "coverage and decision authority_granted must remain false",
            )
        )

    missing_artifacts: list[str] = []
    for artifact_id, raw_path in required_artifacts:
        artifact = _safe_relative(
            root,
            raw_path,
            code=AiEvidenceRevalidationIssueCode.ARTIFACT_INVALID,
            subject=artifact_id,
            issues=issues,
        )
        if artifact is None:
            missing_artifacts.append(artifact_id)
        elif artifact.is_symlink():
            issues.append(
                AiEvidenceIssue(
                    AiEvidenceRevalidationIssueCode.ARTIFACT_INVALID,
                    artifact_id,
                    "required evidence artifact must not be a symlink",
                )
            )
            missing_artifacts.append(artifact_id)
        elif not artifact.exists():
            missing_artifacts.append(artifact_id)
        elif not artifact.is_file():
            issues.append(
                AiEvidenceIssue(
                    AiEvidenceRevalidationIssueCode.ARTIFACT_INVALID,
                    artifact_id,
                    "required evidence artifact must be a regular file",
                )
            )
        else:
            issues.append(
                AiEvidenceIssue(
                    AiEvidenceRevalidationIssueCode.ARTIFACT_INVALID,
                    artifact_id,
                    "artifact exists but lacks a declared schema/hash-bound revalidation adapter",
                )
            )

    if "real_product_ai_observations" in missing_artifacts:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.REAL_OBSERVATIONS_MISSING,
                "real_product_ai_observations",
                "no persisted real product-AI observations are currently declared",
            )
        )
    if "evaluation_matrix_snapshot" in missing_artifacts:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.EVALUATION_MATRIX_MISSING,
                "evaluation_matrix_snapshot",
                "no persisted P4 evaluation matrix snapshot is currently declared",
            )
        )
    if "prompt_model_release_snapshot" in missing_artifacts:
        issues.append(
            AiEvidenceIssue(
                AiEvidenceRevalidationIssueCode.RELEASE_SNAPSHOT_MISSING,
                "prompt_model_release_snapshot",
                "no persisted prompt/model release snapshot is currently declared",
            )
        )

    source_issue_count = sum(
        1
        for item in issues
        if item.code.value.startswith("source_")
        or item.code.value.startswith("coverage_")
    )
    evidence_fresh = source_issue_count == 0 and coverage != {}
    complete = (
        evidence_fresh
        and not missing_artifacts
        and not issues
        and independent_status == "passed"
        and decision_status == "ready"
    )
    return AiEvidenceRevalidationReport(
        status="fresh" if complete else "blocked" if coverage != {} else "invalid",
        evidence_fresh=evidence_fresh,
        product_ai_evidence_complete=complete,
        coverage_status=decision_status,
        independent_ai_gate_status=independent_status,
        declared_source_count=len(sources),
        observed_source_count=len(observed_sources),
        missing_artifact_ids=tuple(missing_artifacts),
        issues=tuple(
            sorted(
                issues, key=lambda item: (item.code.value, item.subject, item.detail)
            )
        ),
        observed_sources=observed_sources,
    )


def ai_evidence_revalidation_payload(report: AiEvidenceRevalidationReport) -> str:
    return (
        json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
        + "\n"
    )


__all__ = [
    "AiEvidenceIssue",
    "AiEvidenceRevalidationIssueCode",
    "AiEvidenceRevalidationReport",
    "AiEvidenceSource",
    "P4_AI_EVIDENCE_REVALIDATION_SCHEMA_VERSION",
    "REQUIRED_P4_ARTIFACTS",
    "ai_evidence_revalidation_payload",
    "revalidate_p4_ai_evidence",
]
