"""Fail-closed commercial release gate for the medical-monitoring subsystem.

This module is an offline decision contract.  It does not inspect SQLite,
start a service, activate a prompt/model, migrate data, or grant medical
authority.  A future release workflow may consume the immutable decision only
after the evidence bundle has been assembled and separately reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable, Mapping


RELEASE_GATE_SCHEMA_VERSION = "medical_monitoring_release_gate_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


REQUIRED_RELEASE_GATE_IDS = (
    "source_authority",
    "three_real_projects",
    "continuous_full_snapshot",
    "daily_monitoring_loop",
    "assurance_subject_site_trial",
    "rule_family_coverage",
    "independent_product_ai",
    "risk_disposition_authority",
    "timeline_profile",
    "project_site_subject_rollup",
    "source_traceability",
    "total_system_consumers",
    "persistence_restart_recovery",
    "browser_interaction_matrix",
    "medical_writing_protection",
    "commercial_release_dossier",
)


class MonitoringReleaseGateError(ValueError):
    """Raised when release evidence is malformed or incomplete."""


class ReleaseEvidenceStatus(str, Enum):
    PASSED = "passed"
    PARTIAL = "partial"
    UNPROVEN = "unproven"
    BLOCKED = "blocked"


class ReleaseDecisionStatus(str, Enum):
    READY = "ready"
    NOT_READY = "not_ready"
    BLOCKED = "blocked"


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringReleaseGateError(
            "release gate payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringReleaseGateError(f"{field_name} must be a string identifier")
    text = value.strip()
    if not text or not _SAFE_ID_RE.fullmatch(text):
        raise MonitoringReleaseGateError(
            f"{field_name} must be a non-empty safe identifier"
        )
    return text


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringReleaseGateError(f"{field_name} must be a string SHA-256")
    text = value.strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise MonitoringReleaseGateError(f"{field_name} must be a lowercase SHA-256")
    return text


def _evidence_ids(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise MonitoringReleaseGateError("evidence_ids must be a collection of strings")
    normalized = tuple(_safe_id(value, "evidence_id") for value in values)
    if not normalized:
        raise MonitoringReleaseGateError("evidence_ids must not be empty")
    if len(normalized) != len(set(normalized)):
        raise MonitoringReleaseGateError("evidence_ids must not repeat")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class MonitoringReleaseGateEvidence:
    """One hash-bound P0–P10 evidence result."""

    gate_id: str
    status: ReleaseEvidenceStatus | str
    evidence_ids: tuple[str, ...]
    evidence_sha256: str
    summary: str

    def __post_init__(self) -> None:
        gate_id = _safe_id(self.gate_id, "gate_id")
        try:
            status = ReleaseEvidenceStatus(self.status)
        except ValueError as exc:
            raise MonitoringReleaseGateError(
                f"unsupported release evidence status: {self.status}"
            ) from exc
        if not isinstance(self.summary, str):
            raise MonitoringReleaseGateError("release evidence summary must be a string")
        summary = self.summary.strip()
        if not summary:
            raise MonitoringReleaseGateError("release evidence summary is required")
        object.__setattr__(self, "gate_id", gate_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "evidence_ids", _evidence_ids(self.evidence_ids))
        object.__setattr__(
            self,
            "evidence_sha256",
            _sha256(self.evidence_sha256, "evidence_sha256"),
        )
        object.__setattr__(self, "summary", summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "evidence_sha256": self.evidence_sha256,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class MonitoringReleaseDecision:
    """Immutable release decision; never grants write or migration authority."""

    status: ReleaseDecisionStatus
    release_ready: bool
    gate_results: tuple[MonitoringReleaseGateEvidence, ...]
    unmet_gate_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    b6_status: str
    b6_write_permitted: bool
    b6_migration_ready: bool
    b6_migration_write_permitted: bool
    schema_version: str = RELEASE_GATE_SCHEMA_VERSION
    decision_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != RELEASE_GATE_SCHEMA_VERSION:
            raise MonitoringReleaseGateError("unsupported release gate schema version")
        if not isinstance(self.status, ReleaseDecisionStatus):
            raise MonitoringReleaseGateError("status must be a ReleaseDecisionStatus")
        if not isinstance(self.release_ready, bool):
            raise MonitoringReleaseGateError("release_ready must be boolean")
        ordered = tuple(self.gate_results)
        if any(not isinstance(item, MonitoringReleaseGateEvidence) for item in ordered):
            raise MonitoringReleaseGateError(
                "gate_results must contain release evidence objects"
            )
        if tuple(item.gate_id for item in ordered) != REQUIRED_RELEASE_GATE_IDS:
            raise MonitoringReleaseGateError(
                "gate_results must contain the required gates in canonical order"
            )
        if isinstance(self.unmet_gate_ids, (str, bytes)):
            raise MonitoringReleaseGateError("unmet_gate_ids must be a collection")
        unmet_gate_ids = tuple(
            _safe_id(value, "unmet_gate_id") for value in self.unmet_gate_ids
        )
        if len(unmet_gate_ids) != len(set(unmet_gate_ids)):
            raise MonitoringReleaseGateError("unmet_gate_ids must not repeat")
        if self.release_ready and self.status != ReleaseDecisionStatus.READY:
            raise MonitoringReleaseGateError(
                "release_ready requires a ready decision status"
            )
        if self.release_ready and unmet_gate_ids:
            raise MonitoringReleaseGateError("ready decision cannot have unmet gates")
        if not isinstance(self.b6_status, str) or not self.b6_status.strip():
            raise MonitoringReleaseGateError("b6_status is required")
        if not isinstance(self.b6_write_permitted, bool):
            raise MonitoringReleaseGateError("b6_write_permitted must be boolean")
        if not isinstance(self.b6_migration_ready, bool):
            raise MonitoringReleaseGateError("b6_migration_ready must be boolean")
        if not isinstance(self.b6_migration_write_permitted, bool):
            raise MonitoringReleaseGateError(
                "b6_migration_write_permitted must be boolean"
            )
        if any(not isinstance(value, str) or not value.strip() for value in self.reasons):
            raise MonitoringReleaseGateError("reasons must contain non-empty strings")
        object.__setattr__(self, "b6_status", self.b6_status.strip())
        object.__setattr__(self, "unmet_gate_ids", unmet_gate_ids)
        object.__setattr__(self, "reasons", tuple(value.strip() for value in self.reasons))
        object.__setattr__(self, "decision_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "release_ready": self.release_ready,
            "gate_results": [item.to_dict() for item in self.gate_results],
            "unmet_gate_ids": list(self.unmet_gate_ids),
            "reasons": list(self.reasons),
            "b6_status": self.b6_status,
            "b6_write_permitted": self.b6_write_permitted,
            "b6_migration_ready": self.b6_migration_ready,
            "b6_migration_write_permitted": self.b6_migration_write_permitted,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "decision_sha256": self.decision_sha256}


def evaluate_monitoring_release(
    gates: Iterable[MonitoringReleaseGateEvidence],
    *,
    b6_status: str,
    b6_write_permitted: bool,
    b6_migration_ready: bool,
    b6_migration_write_permitted: bool,
) -> MonitoringReleaseDecision:
    """Evaluate all commercial gates without performing any side effect.

    Every required gate must be supplied exactly once.  A release is ready only
    when all gates are ``passed`` and B6 is explicitly approved with all three
    authority flags true.  Pending or malformed authority is never inferred as
    approval.
    """

    provided = tuple(gates)
    if any(not isinstance(item, MonitoringReleaseGateEvidence) for item in provided):
        raise MonitoringReleaseGateError("gates must contain release evidence objects")
    by_id: dict[str, MonitoringReleaseGateEvidence] = {}
    for item in provided:
        if item.gate_id in by_id:
            raise MonitoringReleaseGateError(f"duplicate release gate: {item.gate_id}")
        by_id[item.gate_id] = item
    unknown = sorted(set(by_id).difference(REQUIRED_RELEASE_GATE_IDS))
    missing = [gate_id for gate_id in REQUIRED_RELEASE_GATE_IDS if gate_id not in by_id]
    if unknown:
        raise MonitoringReleaseGateError(
            f"unknown release gates: {', '.join(unknown)}"
        )
    if missing:
        raise MonitoringReleaseGateError(
            f"missing required release gates: {', '.join(missing)}"
        )

    ordered = tuple(by_id[gate_id] for gate_id in REQUIRED_RELEASE_GATE_IDS)
    unmet_gate_ids = tuple(
        item.gate_id for item in ordered if item.status != ReleaseEvidenceStatus.PASSED
    )
    reasons = tuple(
        f"gate:{item.gate_id}:{item.status.value}"
        for item in ordered
        if item.status != ReleaseEvidenceStatus.PASSED
    )
    if not isinstance(b6_status, str) or not b6_status.strip():
        raise MonitoringReleaseGateError("b6_status must be a non-empty string")
    b6_text = b6_status.strip()
    if not isinstance(b6_write_permitted, bool):
        raise MonitoringReleaseGateError("b6_write_permitted must be boolean")
    if not isinstance(b6_migration_ready, bool):
        raise MonitoringReleaseGateError("b6_migration_ready must be boolean")
    if not isinstance(b6_migration_write_permitted, bool):
        raise MonitoringReleaseGateError("b6_migration_write_permitted must be boolean")
    if (
        b6_text != "approved"
        or not b6_write_permitted
        or not b6_migration_ready
        or not b6_migration_write_permitted
    ):
        reasons += (
            "b6:approved_write_migration_and_migration_write_authority_required",
        )

    b6_authority_ready = (
        b6_text == "approved"
        and b6_write_permitted
        and b6_migration_ready
        and b6_migration_write_permitted
    )
    release_ready = not unmet_gate_ids and b6_authority_ready
    blocked = any(item.status == ReleaseEvidenceStatus.BLOCKED for item in ordered) or not (
        b6_authority_ready
    )
    status = (
        ReleaseDecisionStatus.READY
        if release_ready
        else ReleaseDecisionStatus.BLOCKED
        if blocked
        else ReleaseDecisionStatus.NOT_READY
    )
    return MonitoringReleaseDecision(
        status=status,
        release_ready=release_ready,
        gate_results=ordered,
        unmet_gate_ids=unmet_gate_ids,
        reasons=reasons,
        b6_status=b6_text,
        b6_write_permitted=b6_write_permitted,
        b6_migration_ready=b6_migration_ready,
        b6_migration_write_permitted=b6_migration_write_permitted,
    )


def evaluate_monitoring_release_from_b6_payload(
    gates: Iterable[MonitoringReleaseGateEvidence],
    *,
    b6_payload: Mapping[str, Any],
) -> MonitoringReleaseDecision:
    """Adapt the persisted B6 shape without coercing unsafe values.

    The adapter is still pure and read-only.  It exists so a future caller
    cannot accidentally use ``bool("false")`` while bridging the nested B6
    JSON object into the commercial release gate.
    """

    if not isinstance(b6_payload, Mapping):
        raise MonitoringReleaseGateError("b6_payload must be an object")
    gate = b6_payload.get("gate")
    if not isinstance(gate, Mapping):
        raise MonitoringReleaseGateError("b6_payload must contain a gate object")
    return evaluate_monitoring_release(
        gates,
        b6_status=gate.get("status"),
        b6_write_permitted=gate.get("write_permitted"),
        b6_migration_ready=gate.get("migration_ready"),
        b6_migration_write_permitted=b6_payload.get("migration_write_permitted"),
    )
