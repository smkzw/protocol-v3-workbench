"""Bind the evidence-semantics snapshot to the current real-loop manifest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from .monitoring_real_loop_evidence_semantics import (
    RealLoopEvidenceSemanticsError,
    RealLoopEvidenceSemanticsIssue,
    RealLoopEvidenceSemanticsIssueCode,
    RealLoopEvidenceSemanticsReport,
)
from .monitoring_real_loop_readiness import REAL_LOOP_UPSTREAM_GATE_NAMES


BINDING_SCHEMA_VERSION = "medical_monitoring_real_loop_semantics_binding_v1"
_SEMANTICS_SCHEMA_VERSION = "medical_monitoring_real_loop_evidence_semantics_v1"


class RealLoopSemanticsBindingError(ValueError):
    """Raised when the binding report would violate its own contract."""


class RealLoopSemanticsBindingIssueCode(str, Enum):
    MANIFEST_SHAPE_INVALID = "manifest_shape_invalid"
    SNAPSHOT_SHAPE_INVALID = "snapshot_shape_invalid"
    SOURCE_MANIFEST_HASH_INVALID = "source_manifest_hash_invalid"
    SOURCE_MANIFEST_HASH_MISMATCH = "source_manifest_hash_mismatch"
    SNAPSHOT_HASH_INVALID = "snapshot_hash_invalid"
    SNAPSHOT_HASH_MISMATCH = "snapshot_hash_mismatch"
    GATE_SET_MISMATCH = "gate_set_mismatch"
    MAPPING_RESULT_HASH_MISMATCH = "mapping_result_hash_mismatch"
    DERIVED_STATUS_MISMATCH = "derived_status_mismatch"
    SEMANTIC_ROW_INVALID = "semantic_row_invalid"
    SEMANTIC_HASH_INVALID = "semantic_hash_invalid"
    ISSUE_COUNT_MISMATCH = "issue_count_mismatch"
    AUTHORITY_FLAG_TRUE = "authority_flag_true"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RealLoopSemanticsBindingError(
            "binding values must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


@dataclass(frozen=True)
class RealLoopSemanticsBindingIssue:
    code: RealLoopSemanticsBindingIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise RealLoopSemanticsBindingError("binding issue subject is required")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise RealLoopSemanticsBindingError("binding issue detail is required")
        object.__setattr__(self, "subject", self.subject.strip())
        object.__setattr__(self, "detail", self.detail.strip())

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopSemanticsBindingReport:
    status: str
    manifest_report_sha256: str
    snapshot_source_manifest_report_sha256: str
    snapshot_sha256: str
    recomputed_snapshot_sha256: str
    issues: tuple[RealLoopSemanticsBindingIssue, ...] = ()
    schema_version: str = BINDING_SCHEMA_VERSION
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != BINDING_SCHEMA_VERSION:
            raise RealLoopSemanticsBindingError("unsupported binding schema")
        if self.status not in {"matched", "blocked"}:
            raise RealLoopSemanticsBindingError("invalid binding status")
        for name in (
            "manifest_report_sha256",
            "snapshot_source_manifest_report_sha256",
            "snapshot_sha256",
            "recomputed_snapshot_sha256",
        ):
            value = getattr(self, name)
            if value and not _valid_hash(value):
                raise RealLoopSemanticsBindingError(f"{name} must be lowercase SHA-256")
        issues = tuple(self.issues)
        if any(not isinstance(item, RealLoopSemanticsBindingIssue) for item in issues):
            raise RealLoopSemanticsBindingError("binding issues contain an invalid value")
        if self.status != ("matched" if not issues else "blocked"):
            raise RealLoopSemanticsBindingError("binding status does not match issues")
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "manifest_report_sha256": self.manifest_report_sha256,
            "snapshot_source_manifest_report_sha256": self.snapshot_source_manifest_report_sha256,
            "snapshot_sha256": self.snapshot_sha256,
            "recomputed_snapshot_sha256": self.recomputed_snapshot_sha256,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "binding_matched": self.status == "matched",
            "runtime_activation_permitted": False,
            "provider_call_permitted": False,
            "write_permitted": False,
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[RealLoopSemanticsBindingIssue],
    code: RealLoopSemanticsBindingIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(RealLoopSemanticsBindingIssue(code, subject, detail))


def _load_semantic_row(
    gate: str,
    raw: Mapping[str, Any],
    issues: list[RealLoopSemanticsBindingIssue],
) -> RealLoopEvidenceSemanticsReport | None:
    try:
        semantic_issues = tuple(
            RealLoopEvidenceSemanticsIssue(
                code=RealLoopEvidenceSemanticsIssueCode(item["code"]),
                subject=item["subject"],
                detail=item["detail"],
            )
            for item in raw.get("issues", [])
            if isinstance(item, Mapping)
        )
        report = RealLoopEvidenceSemanticsReport(
            gate=gate,
            evidence_kind=raw.get("evidence_kind", ""),
            derived_status=raw.get("derived_status", ""),
            freshness_status=raw.get("freshness_status", ""),
            decision_status=raw.get("decision_status", ""),
            replay_status=raw.get("replay_status", ""),
            signature_status=raw.get("signature_status", ""),
            interpretation=raw.get("interpretation", ""),
            mapping_result_sha256=raw.get("mapping_result_sha256", ""),
            issues=semantic_issues,
            schema_version=raw.get("schema_version", ""),
        )
    except (KeyError, TypeError, ValueError, RealLoopEvidenceSemanticsError) as exc:
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SEMANTIC_ROW_INVALID,
            gate,
            f"semantic row cannot be reconstructed: {exc}",
        )
        return None
    if raw.get("semantic_sha256") != report.semantic_sha256:
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SEMANTIC_HASH_INVALID,
            gate,
            "semantic_sha256 does not match the row payload",
        )
    if raw.get("issue_count") != len(report.issues):
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.ISSUE_COUNT_MISMATCH,
            f"{gate}.issue_count",
            "semantic row issue_count does not equal its issue array length",
        )
    for key in ("runtime_activation_permitted", "provider_call_permitted", "write_permitted"):
        if raw.get(key) is not False:
            _issue(
                issues,
                RealLoopSemanticsBindingIssueCode.AUTHORITY_FLAG_TRUE,
                f"{gate}.{key}",
                "semantic snapshot authority flags must be explicit false",
            )
    return report


def bind_real_loop_semantics(
    manifest: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any] | None,
) -> RealLoopSemanticsBindingReport:
    """Compare a semantic snapshot with the exact current-manifest identity."""

    issues: list[RealLoopSemanticsBindingIssue] = []
    if not isinstance(manifest, Mapping):
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.MANIFEST_SHAPE_INVALID,
            "manifest",
            "current manifest must be an object mapping",
        )
    if not isinstance(snapshot, Mapping):
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SNAPSHOT_SHAPE_INVALID,
            "snapshot",
            "semantic snapshot must be an object mapping",
        )
    if issues:
        return RealLoopSemanticsBindingReport(
            status="blocked",
            manifest_report_sha256="",
            snapshot_source_manifest_report_sha256="",
            snapshot_sha256="",
            recomputed_snapshot_sha256="",
            issues=tuple(issues),
        )

    assert isinstance(manifest, Mapping)
    assert isinstance(snapshot, Mapping)
    manifest_report_sha256 = manifest.get("report_sha256", "")
    snapshot_source_sha256 = snapshot.get("source_manifest_report_sha256", "")
    if not _valid_hash(manifest_report_sha256):
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SOURCE_MANIFEST_HASH_INVALID,
            "manifest.report_sha256",
            "current manifest report hash must be lowercase SHA-256",
        )
    if not _valid_hash(snapshot_source_sha256):
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SOURCE_MANIFEST_HASH_INVALID,
            "snapshot.source_manifest_report_sha256",
            "snapshot source manifest hash must be lowercase SHA-256",
        )
    if manifest_report_sha256 != snapshot_source_sha256:
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SOURCE_MANIFEST_HASH_MISMATCH,
            "source_manifest_report_sha256",
            "semantic snapshot is not bound to the current manifest report",
        )

    observed_snapshot_sha256 = snapshot.get("snapshot_sha256", "")
    snapshot_without_hash = dict(snapshot)
    snapshot_without_hash.pop("snapshot_sha256", None)
    recomputed_snapshot_sha256 = _digest(snapshot_without_hash)
    if not _valid_hash(observed_snapshot_sha256):
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SNAPSHOT_HASH_INVALID,
            "snapshot.snapshot_sha256",
            "snapshot hash must be lowercase SHA-256",
        )
    if observed_snapshot_sha256 != recomputed_snapshot_sha256:
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.SNAPSHOT_HASH_MISMATCH,
            "snapshot.snapshot_sha256",
            "snapshot hash does not match its canonical content",
        )
    for key in ("runtime_activation_permitted", "provider_call_permitted", "write_permitted"):
        if snapshot.get(key) is not False:
            _issue(
                issues,
                RealLoopSemanticsBindingIssueCode.AUTHORITY_FLAG_TRUE,
                f"snapshot.{key}",
                "semantic snapshot authority flags must be explicit false",
            )
    if snapshot.get("signature_verified") is not False:
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.AUTHORITY_FLAG_TRUE,
            "snapshot.signature_verified",
            "generic signature verification cannot be asserted",
        )

    manifest_rows = manifest.get("rows")
    snapshot_rows = snapshot.get("rows")
    manifest_by_gate = {
        row.get("gate"): row
        for row in manifest_rows
        if isinstance(row, Mapping) and isinstance(row.get("gate"), str)
    } if isinstance(manifest_rows, list) else {}
    snapshot_by_gate = {
        row.get("gate"): row
        for row in snapshot_rows
        if isinstance(row, Mapping) and isinstance(row.get("gate"), str)
    } if isinstance(snapshot_rows, list) else {}
    if set(manifest_by_gate) != set(REAL_LOOP_UPSTREAM_GATE_NAMES) or set(snapshot_by_gate) != set(
        REAL_LOOP_UPSTREAM_GATE_NAMES
    ):
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.GATE_SET_MISMATCH,
            "gate_set",
            "manifest and semantic snapshot must each contain the five canonical gates",
        )

    total_issue_count = 0
    for gate in REAL_LOOP_UPSTREAM_GATE_NAMES:
        manifest_row = manifest_by_gate.get(gate)
        snapshot_row = snapshot_by_gate.get(gate)
        if not isinstance(manifest_row, Mapping) or not isinstance(snapshot_row, Mapping):
            _issue(
                issues,
                RealLoopSemanticsBindingIssueCode.SEMANTIC_ROW_INVALID,
                gate,
                "canonical manifest and semantic rows are both required",
            )
            continue
        report = _load_semantic_row(gate, snapshot_row, issues)
        if report is None:
            continue
        total_issue_count += len(report.issues)
        if report.mapping_result_sha256 != manifest_row.get("mapping_result_sha256"):
            _issue(
                issues,
                RealLoopSemanticsBindingIssueCode.MAPPING_RESULT_HASH_MISMATCH,
                gate,
                "semantic mapping-result hash does not match the current manifest row",
            )
        if report.derived_status != manifest_row.get("status"):
            _issue(
                issues,
                RealLoopSemanticsBindingIssueCode.DERIVED_STATUS_MISMATCH,
                gate,
                "semantic derived status does not match the current manifest row",
            )
    if snapshot.get("issue_count") != total_issue_count:
        _issue(
            issues,
            RealLoopSemanticsBindingIssueCode.ISSUE_COUNT_MISMATCH,
            "snapshot.issue_count",
            "snapshot issue_count does not equal the sum of semantic row issues",
        )

    return RealLoopSemanticsBindingReport(
        status="matched" if not issues else "blocked",
        manifest_report_sha256=manifest_report_sha256 if _valid_hash(manifest_report_sha256) else "",
        snapshot_source_manifest_report_sha256=(
            snapshot_source_sha256 if _valid_hash(snapshot_source_sha256) else ""
        ),
        snapshot_sha256=observed_snapshot_sha256 if _valid_hash(observed_snapshot_sha256) else "",
        recomputed_snapshot_sha256=recomputed_snapshot_sha256,
        issues=tuple(issues),
    )


__all__ = [
    "BINDING_SCHEMA_VERSION",
    "RealLoopSemanticsBindingError",
    "RealLoopSemanticsBindingIssue",
    "RealLoopSemanticsBindingIssueCode",
    "RealLoopSemanticsBindingReport",
    "bind_real_loop_semantics",
]
