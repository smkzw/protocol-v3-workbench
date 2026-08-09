"""Build a deterministic, read-only current-state real-loop gate manifest."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .monitoring_real_loop_readiness import (
    REAL_LOOP_UPSTREAM_GATE_NAMES,
    RealLoopGateInput,
)
from .monitoring_real_loop_status_mapping import (
    RealLoopStatusMappingResult,
    derive_real_loop_upstream_status,
)
from .monitoring_real_loop_upstream_assembly import (
    REAL_LOOP_UPSTREAM_EVIDENCE_KINDS,
    RealLoopUpstreamAssemblyReport,
    RealLoopUpstreamEvidence,
    assess_real_loop_upstream_assembly,
)


CURRENT_MANIFEST_SCHEMA_VERSION = "medical_monitoring_real_loop_current_manifest_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class RealLoopCurrentManifestError(ValueError):
    """Raised when a current manifest violates its own structural contract."""


class RealLoopCurrentManifestIssueCode(str, Enum):
    ROW_INVALID = "row_invalid"
    GATE_UNKNOWN = "gate_unknown"
    GATE_DUPLICATE = "gate_duplicate"
    GATE_SET_MISMATCH = "gate_set_mismatch"
    REF_INVALID = "ref_invalid"
    HASH_INVALID = "hash_invalid"
    PAIR_INCOMPLETE = "pair_incomplete"
    PAYLOAD_INVALID = "payload_invalid"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RealLoopCurrentManifestError(
            "current manifest payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RealLoopCurrentManifestIssue:
    code: RealLoopCurrentManifestIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise RealLoopCurrentManifestError("manifest issue subject is required")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise RealLoopCurrentManifestError("manifest issue detail is required")
        object.__setattr__(self, "subject", self.subject.strip())
        object.__setattr__(self, "detail", self.detail.strip())

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopCurrentGateArtifact:
    """A loaded payload plus caller-recomputed bytes hash for one gate."""

    gate: str
    evidence_ref: str = ""
    artifact_sha256: str = ""
    payload: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class RealLoopCurrentManifestRow:
    gate: str
    evidence_kind: str
    status: str
    evidence_ref: str
    artifact_sha256: str
    payload_sha256: str
    mapping_result_sha256: str
    mapping_issue_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "evidence_kind": self.evidence_kind,
            "status": self.status,
            "evidence_ref": self.evidence_ref,
            "artifact_sha256": self.artifact_sha256,
            "payload_sha256": self.payload_sha256,
            "mapping_result_sha256": self.mapping_result_sha256,
            "mapping_issue_count": self.mapping_issue_count,
        }


@dataclass(frozen=True)
class RealLoopCurrentManifest:
    status: str
    gate_input: RealLoopGateInput
    rows: tuple[RealLoopCurrentManifestRow, ...]
    mapping_results: tuple[RealLoopStatusMappingResult, ...]
    assembly: RealLoopUpstreamAssemblyReport
    issues: tuple[RealLoopCurrentManifestIssue, ...] = ()
    schema_version: str = CURRENT_MANIFEST_SCHEMA_VERSION
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != CURRENT_MANIFEST_SCHEMA_VERSION:
            raise RealLoopCurrentManifestError("unsupported current manifest schema")
        if self.status not in {"assembled", "blocked"}:
            raise RealLoopCurrentManifestError("invalid current manifest status")
        if not isinstance(self.gate_input, RealLoopGateInput):
            raise RealLoopCurrentManifestError("gate_input has an invalid type")
        rows = tuple(self.rows)
        results = tuple(self.mapping_results)
        issues = tuple(self.issues)
        if any(not isinstance(row, RealLoopCurrentManifestRow) for row in rows):
            raise RealLoopCurrentManifestError("manifest rows contain an invalid value")
        if any(not isinstance(result, RealLoopStatusMappingResult) for result in results):
            raise RealLoopCurrentManifestError("mapping results contain an invalid value")
        if any(not isinstance(issue, RealLoopCurrentManifestIssue) for issue in issues):
            raise RealLoopCurrentManifestError("manifest issues contain an invalid value")
        expected_status = (
            "assembled"
            if not issues
            and all(result.status == "proven" for result in results)
            and self.assembly.status == "assembled"
            and not self.assembly.issues
            else "blocked"
        )
        if self.status != expected_status:
            raise RealLoopCurrentManifestError(
                "manifest status does not match evidence state"
            )
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "mapping_results", results)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "gate_input": {
                "b6_approved": self.gate_input.b6_approved,
                "approved_input_ready": self.gate_input.approved_input_ready,
                "source_token_revalidated": self.gate_input.source_token_revalidated,
                "aggregate_cas_complete": self.gate_input.aggregate_cas_complete,
                "runtime_identity_verified": self.gate_input.runtime_identity_verified,
            },
            "rows": [row.to_dict() for row in self.rows],
            "mapping_results": [result.to_dict() for result in self.mapping_results],
            "assembly_report_sha256": self.assembly.report_sha256,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "report_sha256": self.report_sha256,
            "runtime_activation_permitted": False,
            "provider_call_permitted": False,
            "write_permitted": False,
        }


def _issue(
    issues: list[RealLoopCurrentManifestIssue],
    code: RealLoopCurrentManifestIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(RealLoopCurrentManifestIssue(code, subject, detail))


def _valid_artifact_identity(
    artifact: RealLoopCurrentGateArtifact,
    issues: list[RealLoopCurrentManifestIssue],
) -> tuple[str, str]:
    evidence_ref = artifact.evidence_ref.strip() if isinstance(artifact.evidence_ref, str) else ""
    raw_artifact_hash = artifact.artifact_sha256
    artifact_hash = raw_artifact_hash if isinstance(raw_artifact_hash, str) else ""
    valid = True
    if evidence_ref and not _SAFE_REF_RE.fullmatch(evidence_ref):
        _issue(
            issues,
            RealLoopCurrentManifestIssueCode.REF_INVALID,
            artifact.gate,
            "evidence_ref must be a bounded opaque identifier, not a path",
        )
        valid = False
    if raw_artifact_hash != "" and (
        not isinstance(raw_artifact_hash, str)
        or not _SHA256_RE.fullmatch(raw_artifact_hash)
    ):
        _issue(
            issues,
            RealLoopCurrentManifestIssueCode.HASH_INVALID,
            artifact.gate,
            "artifact_sha256 must be a lowercase SHA-256",
        )
        valid = False
    if bool(evidence_ref) != bool(artifact_hash):
        _issue(
            issues,
            RealLoopCurrentManifestIssueCode.PAIR_INCOMPLETE,
            artifact.gate,
            "evidence_ref and artifact_sha256 must be supplied together",
        )
        valid = False
    return (evidence_ref, artifact_hash) if valid else ("", "")


def build_real_loop_current_manifest(
    artifacts: Iterable[RealLoopCurrentGateArtifact],
) -> RealLoopCurrentManifest:
    """Combine loaded artifacts, status mapping and fail-closed assembly."""

    issues: list[RealLoopCurrentManifestIssue] = []
    candidates: dict[str, RealLoopCurrentGateArtifact] = {}
    invalid_gates: set[str] = set()
    observed_gates: list[str] = []
    for index, artifact in enumerate(tuple(artifacts)):
        subject = f"row[{index}]"
        if not isinstance(artifact, RealLoopCurrentGateArtifact):
            _issue(
                issues,
                RealLoopCurrentManifestIssueCode.ROW_INVALID,
                subject,
                "manifest rows must be RealLoopCurrentGateArtifact values",
            )
            continue
        gate = artifact.gate.strip() if isinstance(artifact.gate, str) else ""
        if not gate:
            _issue(
                issues,
                RealLoopCurrentManifestIssueCode.ROW_INVALID,
                subject,
                "gate must be a non-empty string",
            )
            continue
        observed_gates.append(gate)
        if gate not in REAL_LOOP_UPSTREAM_GATE_NAMES:
            _issue(
                issues,
                RealLoopCurrentManifestIssueCode.GATE_UNKNOWN,
                gate,
                "gate is outside the five canonical real-loop prerequisites",
            )
            continue
        if gate in candidates or gate in invalid_gates:
            _issue(
                issues,
                RealLoopCurrentManifestIssueCode.GATE_DUPLICATE,
                gate,
                "exactly one current artifact row is allowed per gate",
            )
            candidates.pop(gate, None)
            invalid_gates.add(gate)
            continue
        candidates[gate] = artifact

    if set(observed_gates) != set(REAL_LOOP_UPSTREAM_GATE_NAMES):
        _issue(
            issues,
            RealLoopCurrentManifestIssueCode.GATE_SET_MISMATCH,
            "gate_set",
            f"required={sorted(REAL_LOOP_UPSTREAM_GATE_NAMES)}, observed={sorted(set(observed_gates))}",
        )

    mapping_results: list[RealLoopStatusMappingResult] = []
    evidence_rows: list[RealLoopUpstreamEvidence] = []
    manifest_rows: list[RealLoopCurrentManifestRow] = []
    for gate in REAL_LOOP_UPSTREAM_GATE_NAMES:
        artifact = candidates.get(gate)
        if artifact is None or gate in invalid_gates:
            result = derive_real_loop_upstream_status(gate, None)
            evidence_ref = ""
            artifact_hash = ""
            payload_hash = ""
        else:
            evidence_ref, artifact_hash = _valid_artifact_identity(artifact, issues)
            payload = artifact.payload
            if payload is not None and not isinstance(payload, Mapping):
                _issue(
                    issues,
                    RealLoopCurrentManifestIssueCode.PAYLOAD_INVALID,
                    gate,
                    "loaded payload must be an object mapping or None",
                )
                payload = None
            payload_hash = _digest(payload) if payload is not None else ""
            result = derive_real_loop_upstream_status(
                gate,
                payload,
                payload_sha256=payload_hash,
            )
        mapping_results.append(result)
        evidence_rows.append(
            RealLoopUpstreamEvidence(
                gate=gate,
                evidence_kind=REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate],
                evidence_ref=evidence_ref,
                evidence_sha256=artifact_hash,
                status=result.status,
            )
        )
        manifest_rows.append(
            RealLoopCurrentManifestRow(
                gate=gate,
                evidence_kind=REAL_LOOP_UPSTREAM_EVIDENCE_KINDS[gate],
                status=result.status,
                evidence_ref=evidence_ref,
                artifact_sha256=artifact_hash,
                payload_sha256=payload_hash,
                mapping_result_sha256=result.result_sha256,
                mapping_issue_count=len(result.issues),
            )
        )
    assembly = assess_real_loop_upstream_assembly(evidence_rows)
    status = (
        "assembled"
        if not issues and all(result.status == "proven" for result in mapping_results)
        else "blocked"
    )
    return RealLoopCurrentManifest(
        status=status,
        gate_input=assembly.gate_input,
        rows=tuple(manifest_rows),
        mapping_results=tuple(mapping_results),
        assembly=assembly,
        issues=tuple(issues),
    )


__all__ = [
    "CURRENT_MANIFEST_SCHEMA_VERSION",
    "RealLoopCurrentGateArtifact",
    "RealLoopCurrentManifest",
    "RealLoopCurrentManifestError",
    "RealLoopCurrentManifestIssue",
    "RealLoopCurrentManifestIssueCode",
    "RealLoopCurrentManifestRow",
    "build_real_loop_current_manifest",
]
