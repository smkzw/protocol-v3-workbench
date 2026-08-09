"""Pure replay of a persisted current-state real-loop gate manifest.

The caller supplies source bytes and already-loaded payloads explicitly.  This
module never reads paths and never changes a gate; it only recomputes the
artifact/payload/result identities and compares them with a persisted snapshot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any

from .monitoring_real_loop_current_manifest import (
    RealLoopCurrentGateArtifact,
    build_real_loop_current_manifest,
)
from .monitoring_real_loop_readiness import REAL_LOOP_UPSTREAM_GATE_NAMES


REPLAY_SCHEMA_VERSION = "medical_monitoring_real_loop_manifest_replay_v1"


class RealLoopManifestReplayError(ValueError):
    """Raised when the replay report would violate its own contract."""


class RealLoopManifestReplayIssueCode(str, Enum):
    MANIFEST_SHAPE_INVALID = "manifest_shape_invalid"
    INPUT_ROW_INVALID = "input_row_invalid"
    INPUT_GATE_UNKNOWN = "input_gate_unknown"
    INPUT_GATE_DUPLICATE = "input_gate_duplicate"
    ARTIFACT_BYTES_MISSING = "artifact_bytes_missing"
    ARTIFACT_BYTES_INVALID = "artifact_bytes_invalid"
    PAYLOAD_INVALID = "payload_invalid"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    PAYLOAD_HASH_MISMATCH = "payload_hash_mismatch"
    MAPPING_RESULT_HASH_MISMATCH = "mapping_result_hash_mismatch"
    MANIFEST_REPORT_HASH_MISMATCH = "manifest_report_hash_mismatch"
    MANIFEST_CONTENT_MISMATCH = "manifest_content_mismatch"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RealLoopManifestReplayError(
            "replay values must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RealLoopManifestReplayArtifact:
    """One explicitly supplied source row for a replay.

    ``artifact_bytes`` is the exact bytes whose hash is replayed.  The
    runtime-identity row may set ``allow_missing=True`` until its formal
    persisted evidence schema exists; a missing required source row fails
    closed.
    """

    gate: str
    evidence_ref: str = ""
    artifact_bytes: bytes | None = None
    payload: Mapping[str, Any] | None = None
    allow_missing: bool = False


@dataclass(frozen=True)
class RealLoopManifestReplayIssue:
    code: RealLoopManifestReplayIssueCode
    subject: str
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise RealLoopManifestReplayError("replay issue subject is required")
        if not isinstance(self.detail, str) or not self.detail.strip():
            raise RealLoopManifestReplayError("replay issue detail is required")
        object.__setattr__(self, "subject", self.subject.strip())
        object.__setattr__(self, "detail", self.detail.strip())

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "subject": self.subject, "detail": self.detail}


@dataclass(frozen=True)
class RealLoopManifestReplayReport:
    status: str
    expected_manifest_report_sha256: str
    observed_manifest_report_sha256: str
    expected_manifest_sha256: str
    observed_manifest_sha256: str
    issues: tuple[RealLoopManifestReplayIssue, ...] = ()
    schema_version: str = REPLAY_SCHEMA_VERSION
    report_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != REPLAY_SCHEMA_VERSION:
            raise RealLoopManifestReplayError("unsupported replay schema")
        if self.status not in {"matched", "blocked"}:
            raise RealLoopManifestReplayError("invalid replay status")
        for name in (
            "expected_manifest_report_sha256",
            "observed_manifest_report_sha256",
            "expected_manifest_sha256",
            "observed_manifest_sha256",
        ):
            value = getattr(self, name)
            if value and (
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise RealLoopManifestReplayError(f"{name} must be lowercase SHA-256")
        issues = tuple(self.issues)
        if any(not isinstance(item, RealLoopManifestReplayIssue) for item in issues):
            raise RealLoopManifestReplayError("replay issues contain an invalid value")
        expected_status = "matched" if not issues else "blocked"
        if self.status != expected_status:
            raise RealLoopManifestReplayError("replay status does not match issues")
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "report_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "expected_manifest_report_sha256": self.expected_manifest_report_sha256,
            "observed_manifest_report_sha256": self.observed_manifest_report_sha256,
            "expected_manifest_sha256": self.expected_manifest_sha256,
            "observed_manifest_sha256": self.observed_manifest_sha256,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self._payload(),
            "issue_count": len(self.issues),
            "replay_matched": self.status == "matched",
            "runtime_activation_permitted": False,
            "provider_call_permitted": False,
            "write_permitted": False,
            "report_sha256": self.report_sha256,
        }


def _issue(
    issues: list[RealLoopManifestReplayIssue],
    code: RealLoopManifestReplayIssueCode,
    subject: str,
    detail: str,
) -> None:
    issues.append(RealLoopManifestReplayIssue(code, subject, detail))


def _empty_report(
    issues: list[RealLoopManifestReplayIssue],
    *,
    observed_manifest_sha256: str = "",
    observed_report_sha256: str = "",
) -> RealLoopManifestReplayReport:
    return RealLoopManifestReplayReport(
        status="blocked",
        expected_manifest_report_sha256="",
        observed_manifest_report_sha256=observed_report_sha256,
        expected_manifest_sha256="",
        observed_manifest_sha256=observed_manifest_sha256,
        issues=tuple(issues),
    )


def replay_real_loop_current_manifest(
    manifest: Mapping[str, Any] | None,
    artifacts: Iterable[RealLoopManifestReplayArtifact],
) -> RealLoopManifestReplayReport:
    """Recompute current evidence identities and compare a persisted manifest.

    The function intentionally requires exact canonical equality.  A replay
    that can only prove individual rows but not the persisted report is still
    ``blocked`` and never yields any authority.
    """

    issues: list[RealLoopManifestReplayIssue] = []
    if not isinstance(manifest, Mapping):
        _issue(
            issues,
            RealLoopManifestReplayIssueCode.MANIFEST_SHAPE_INVALID,
            "manifest",
            "persisted manifest must be an object mapping",
        )
        return _empty_report(issues)

    observed_manifest = dict(manifest)
    observed_manifest_sha256 = _digest(observed_manifest)
    observed_report_sha256 = observed_manifest.get("report_sha256", "")
    if not isinstance(observed_report_sha256, str):
        observed_report_sha256 = ""

    loaded: list[RealLoopCurrentGateArtifact] = []
    seen_gates: set[str] = set()
    for index, item in enumerate(tuple(artifacts)):
        subject = f"row[{index}]"
        if not isinstance(item, RealLoopManifestReplayArtifact):
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.INPUT_ROW_INVALID,
                subject,
                "replay rows must be RealLoopManifestReplayArtifact values",
            )
            continue
        gate = item.gate.strip() if isinstance(item.gate, str) else ""
        if gate not in REAL_LOOP_UPSTREAM_GATE_NAMES:
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.INPUT_GATE_UNKNOWN,
                subject,
                "replay gate is outside the five canonical real-loop prerequisites",
            )
            continue
        if gate in seen_gates:
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.INPUT_GATE_DUPLICATE,
                gate,
                "exactly one replay row is allowed per canonical gate",
            )
            continue
        seen_gates.add(gate)
        if item.artifact_bytes is None:
            if not item.allow_missing:
                _issue(
                    issues,
                    RealLoopManifestReplayIssueCode.ARTIFACT_BYTES_MISSING,
                    gate,
                    "source artifact bytes are required for replay",
                )
            artifact_sha256 = ""
        elif not isinstance(item.artifact_bytes, bytes):
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.ARTIFACT_BYTES_INVALID,
                gate,
                "artifact_bytes must be raw bytes",
            )
            artifact_sha256 = ""
        else:
            artifact_sha256 = hashlib.sha256(item.artifact_bytes).hexdigest()
        payload = item.payload
        if payload is not None and not isinstance(payload, Mapping):
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.PAYLOAD_INVALID,
                gate,
                "replay payload must be an object mapping or None",
            )
            payload = None
        loaded.append(
            RealLoopCurrentGateArtifact(
                gate=gate,
                evidence_ref=item.evidence_ref,
                artifact_sha256=artifact_sha256,
                payload=payload,
            )
        )

    if seen_gates != set(REAL_LOOP_UPSTREAM_GATE_NAMES):
        _issue(
            issues,
            RealLoopManifestReplayIssueCode.INPUT_ROW_INVALID,
            "gate_set",
            "replay must include exactly one row for each canonical gate",
        )

    expected = build_real_loop_current_manifest(loaded)
    expected_manifest = expected.to_dict()
    expected_manifest_sha256 = _digest(expected_manifest)
    expected_report_sha256 = expected.report_sha256

    observed_rows = observed_manifest.get("rows")
    observed_by_gate = {
        row.get("gate"): row
        for row in observed_rows
        if isinstance(row, Mapping) and isinstance(row.get("gate"), str)
    } if isinstance(observed_rows, list) else {}
    expected_by_gate = {row["gate"]: row for row in expected_manifest["rows"]}
    for gate in REAL_LOOP_UPSTREAM_GATE_NAMES:
        expected_row = expected_by_gate[gate]
        observed_row = observed_by_gate.get(gate)
        if not isinstance(observed_row, Mapping):
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.MANIFEST_CONTENT_MISMATCH,
                gate,
                "persisted manifest is missing a canonical row",
            )
            continue
        if observed_row.get("artifact_sha256") != expected_row["artifact_sha256"]:
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.ARTIFACT_HASH_MISMATCH,
                gate,
                "persisted artifact hash does not match replayed source bytes",
            )
        if observed_row.get("payload_sha256") != expected_row["payload_sha256"]:
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.PAYLOAD_HASH_MISMATCH,
                gate,
                "persisted payload hash does not match canonical replay payload",
            )
        if observed_row.get("mapping_result_sha256") != expected_row["mapping_result_sha256"]:
            _issue(
                issues,
                RealLoopManifestReplayIssueCode.MAPPING_RESULT_HASH_MISMATCH,
                gate,
                "persisted mapping-result hash does not match replayed status mapping",
            )

    if observed_report_sha256 != expected_report_sha256:
        _issue(
            issues,
            RealLoopManifestReplayIssueCode.MANIFEST_REPORT_HASH_MISMATCH,
            "manifest",
            "persisted report_sha256 does not match the rederived manifest",
        )
    if _canonical(observed_manifest) != _canonical(expected_manifest):
        _issue(
            issues,
            RealLoopManifestReplayIssueCode.MANIFEST_CONTENT_MISMATCH,
            "manifest",
            "persisted manifest content differs from the deterministic replay",
        )

    return RealLoopManifestReplayReport(
        status="matched" if not issues else "blocked",
        expected_manifest_report_sha256=expected_report_sha256,
        observed_manifest_report_sha256=observed_report_sha256,
        expected_manifest_sha256=expected_manifest_sha256,
        observed_manifest_sha256=observed_manifest_sha256,
        issues=tuple(issues),
    )


__all__ = [
    "REPLAY_SCHEMA_VERSION",
    "RealLoopManifestReplayArtifact",
    "RealLoopManifestReplayError",
    "RealLoopManifestReplayIssue",
    "RealLoopManifestReplayIssueCode",
    "RealLoopManifestReplayReport",
    "replay_real_loop_current_manifest",
]
