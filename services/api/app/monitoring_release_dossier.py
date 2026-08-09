"""Pure commercial-release dossier contract for medical monitoring.

The generic release gate proves that a gate row exists.  This module proves
that the commercial dossier behind that row has the minimum sections and
control coverage required by the monitoring product contract.  It is
deliberately offline and immutable: it never starts a service, reads SQLite,
calls a provider, changes a release, or grants authority.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib
import json
import re
from typing import Any, Iterable

from .monitoring_release_gate import (
    MonitoringReleaseGateEvidence,
    ReleaseEvidenceStatus,
)


RELEASE_DOSSIER_SCHEMA_VERSION = "medical_monitoring_release_dossier_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_ISO_TZ_RE = re.compile(r"(?:Z|[+-]\d{2}:\d{2})$")


class MonitoringReleaseDossierError(ValueError):
    """Raised when a release dossier is malformed or unsafe."""


class ReleaseDossierSectionStatus(str, Enum):
    PASSED = "passed"
    PARTIAL = "partial"
    UNPROVEN = "unproven"
    BLOCKED = "blocked"


class ResidualRiskSeverity(str, Enum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class ResidualRiskStatus(str, Enum):
    MITIGATED = "mitigated"
    ACCEPTED = "accepted"
    DEFERRED = "deferred"


REQUIRED_DOSSIER_SECTION_IDS = (
    "functional_validation",
    "nonfunctional_validation",
    "installation_upgrade_rollback",
    "security_privacy_sbom",
    "audit_and_data_retention",
    "operations_support_training",
    "user_acceptance",
    "residual_risk_release_decision",
)

# These controls are the minimum evidence vocabulary, not a claim that any
# control has passed.  A section may be partial/unproven, but its covered and
# unmet IDs must still form an explicit partition of this closed set.
REQUIRED_DOSSIER_CONTROLS: dict[str, tuple[str, ...]] = {
    "functional_validation": (
        "real_project_e2e",
        "browser_scientific_acceptance",
        "three_monitoring_modes",
    ),
    "nonfunctional_validation": (
        "performance_baseline",
        "restart_recovery",
        "observability_and_alerting",
    ),
    "installation_upgrade_rollback": (
        "clean_install",
        "upgrade_rehearsal",
        "rollback_rehearsal",
        "backup_restore_rehearsal",
    ),
    "security_privacy_sbom": (
        "access_control_review",
        "data_egress_review",
        "sbom_and_license_review",
    ),
    "audit_and_data_retention": (
        "append_only_audit",
        "retention_and_export",
        "source_traceability_replay",
    ),
    "operations_support_training": (
        "operator_runbook",
        "incident_escalation",
        "operator_training_completion",
    ),
    "user_acceptance": (
        "engineering_e2e",
        "senior_medical_monitor_uat",
        "independent_product_ai_review",
    ),
    "residual_risk_release_decision": (
        "p0_p1_release_blocker_review",
        "residual_risk_owner_disposition",
        "release_owner_decision",
    ),
}

REQUIRED_DOSSIER_SIGNOFF_ROLES = (
    "engineering",
    "senior_medical_monitor",
    "release_owner",
)


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as exc:
        raise MonitoringReleaseDossierError(
            "release dossier payload must be JSON-serializable"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringReleaseDossierError(f"{field_name} must be a string identifier")
    text = value.strip()
    if not text or not _SAFE_ID_RE.fullmatch(text):
        raise MonitoringReleaseDossierError(
            f"{field_name} must be a non-empty safe identifier"
        )
    return text


def _hash(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise MonitoringReleaseDossierError(f"{field_name} must be a string SHA-256")
    return value


def _ids(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    normalized = tuple(_safe_id(value, f"{field_name} item") for value in values)
    if not normalized:
        raise MonitoringReleaseDossierError(f"{field_name} must not be empty")
    if len(normalized) != len(set(normalized)):
        raise MonitoringReleaseDossierError(f"{field_name} must not repeat")
    return tuple(sorted(normalized))


def _timestamp(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise MonitoringReleaseDossierError(f"{field_name} must be a string timestamp")
    text = value.strip()
    if not text or not _ISO_TZ_RE.search(text):
        raise MonitoringReleaseDossierError(
            f"{field_name} must be an ISO-8601 timestamp with timezone"
        )
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MonitoringReleaseDossierError(
            f"{field_name} must be a valid timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MonitoringReleaseDossierError(f"{field_name} must include timezone")
    return text


@dataclass(frozen=True)
class MonitoringReleaseDossierSection:
    """One section of the commercial dossier with an explicit control partition."""

    section_id: str
    status: ReleaseDossierSectionStatus | str
    evidence_ids: tuple[str, ...]
    evidence_sha256: str
    covered_control_ids: tuple[str, ...]
    unmet_control_ids: tuple[str, ...]
    summary: str

    def __post_init__(self) -> None:
        section_id = _safe_id(self.section_id, "section_id")
        if section_id not in REQUIRED_DOSSIER_SECTION_IDS:
            raise MonitoringReleaseDossierError(
                f"unsupported dossier section: {section_id}"
            )
        try:
            status = ReleaseDossierSectionStatus(self.status)
        except ValueError as exc:
            raise MonitoringReleaseDossierError(
                f"unsupported dossier section status: {self.status}"
            ) from exc
        controls = set(REQUIRED_DOSSIER_CONTROLS[section_id])
        covered = (
            _ids(self.covered_control_ids, "covered_control_ids")
            if self.covered_control_ids
            else ()
        )
        unmet = (
            _ids(self.unmet_control_ids, "unmet_control_ids")
            if self.unmet_control_ids
            else ()
        )
        if set(covered) & set(unmet):
            raise MonitoringReleaseDossierError(
                f"covered and unmet controls overlap for {section_id}"
            )
        if set(covered) | set(unmet) != controls:
            missing = sorted(controls - set(covered) - set(unmet))
            unknown = sorted((set(covered) | set(unmet)) - controls)
            raise MonitoringReleaseDossierError(
                f"control partition mismatch for {section_id}; missing={missing}, unknown={unknown}"
            )
        if status == ReleaseDossierSectionStatus.PASSED and unmet:
            raise MonitoringReleaseDossierError(
                f"passed dossier section has unmet controls: {section_id}"
            )
        summary = str(self.summary or "").strip()
        if not summary:
            raise MonitoringReleaseDossierError("dossier section summary is required")
        object.__setattr__(self, "section_id", section_id)
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self, "evidence_ids", _ids(self.evidence_ids, "evidence_ids")
        )
        object.__setattr__(
            self, "evidence_sha256", _hash(self.evidence_sha256, "evidence_sha256")
        )
        object.__setattr__(self, "covered_control_ids", covered)
        object.__setattr__(self, "unmet_control_ids", unmet)
        object.__setattr__(self, "summary", summary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "evidence_sha256": self.evidence_sha256,
            "covered_control_ids": list(self.covered_control_ids),
            "unmet_control_ids": list(self.unmet_control_ids),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class MonitoringReleaseDossierSignoff:
    """A required human signoff bound to evidence and a timezone-aware time."""

    role: str
    actor_id: str
    signed_at: str
    evidence_sha256: str

    def __post_init__(self) -> None:
        role = _safe_id(self.role, "signoff.role")
        if role not in REQUIRED_DOSSIER_SIGNOFF_ROLES:
            raise MonitoringReleaseDossierError(
                f"unsupported dossier signoff role: {role}"
            )
        object.__setattr__(self, "role", role)
        object.__setattr__(
            self, "actor_id", _safe_id(self.actor_id, "signoff.actor_id")
        )
        object.__setattr__(
            self, "signed_at", _timestamp(self.signed_at, "signoff.signed_at")
        )
        object.__setattr__(
            self,
            "evidence_sha256",
            _hash(self.evidence_sha256, "signoff.evidence_sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "actor_id": self.actor_id,
            "signed_at": self.signed_at,
            "evidence_sha256": self.evidence_sha256,
        }


@dataclass(frozen=True)
class MonitoringResidualRiskDisposition:
    """Written disposition for a residual release risk."""

    risk_id: str
    severity: ResidualRiskSeverity | str
    status: ResidualRiskStatus | str
    owner_id: str
    decision_evidence_sha256: str
    rationale: str

    def __post_init__(self) -> None:
        try:
            severity = ResidualRiskSeverity(self.severity)
            status = ResidualRiskStatus(self.status)
        except ValueError as exc:
            raise MonitoringReleaseDossierError(
                "unsupported residual-risk severity or status"
            ) from exc
        rationale = str(self.rationale or "").strip()
        if not rationale:
            raise MonitoringReleaseDossierError("residual-risk rationale is required")
        object.__setattr__(
            self, "risk_id", _safe_id(self.risk_id, "residual_risk.risk_id")
        )
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self, "owner_id", _safe_id(self.owner_id, "residual_risk.owner_id")
        )
        object.__setattr__(
            self,
            "decision_evidence_sha256",
            _hash(
                self.decision_evidence_sha256, "residual_risk.decision_evidence_sha256"
            ),
        )
        object.__setattr__(self, "rationale", rationale)

    @property
    def blocks_release(self) -> bool:
        return self.status == ResidualRiskStatus.DEFERRED or (
            self.severity in {ResidualRiskSeverity.P0, ResidualRiskSeverity.P1}
            and self.status != ResidualRiskStatus.MITIGATED
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "severity": self.severity.value,
            "status": self.status.value,
            "owner_id": self.owner_id,
            "decision_evidence_sha256": self.decision_evidence_sha256,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class MonitoringReleaseDossier:
    """Immutable dossier and derived diagnostic readiness decision."""

    dossier_id: str
    release_version: str
    generated_at: str
    sections: tuple[MonitoringReleaseDossierSection, ...]
    signoffs: tuple[MonitoringReleaseDossierSignoff, ...]
    residual_risks: tuple[MonitoringResidualRiskDisposition, ...] = ()
    authority_granted: bool = False
    schema_version: str = RELEASE_DOSSIER_SCHEMA_VERSION
    status: ReleaseDossierSectionStatus = field(init=False)
    release_ready: bool = field(init=False)
    blocking_reasons: tuple[str, ...] = field(init=False)
    dossier_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != RELEASE_DOSSIER_SCHEMA_VERSION:
            raise MonitoringReleaseDossierError(
                "unsupported release dossier schema version"
            )
        if self.authority_granted is not False:
            raise MonitoringReleaseDossierError(
                "offline dossier cannot grant authority"
            )
        object.__setattr__(self, "dossier_id", _safe_id(self.dossier_id, "dossier_id"))
        object.__setattr__(
            self, "release_version", _safe_id(self.release_version, "release_version")
        )
        object.__setattr__(
            self, "generated_at", _timestamp(self.generated_at, "generated_at")
        )

        sections = tuple(self.sections)
        if any(
            not isinstance(item, MonitoringReleaseDossierSection) for item in sections
        ):
            raise MonitoringReleaseDossierError(
                "sections must contain dossier section objects"
            )
        if tuple(item.section_id for item in sections) != REQUIRED_DOSSIER_SECTION_IDS:
            raise MonitoringReleaseDossierError(
                "sections must contain the required sections in canonical order"
            )

        signoffs = tuple(self.signoffs)
        if any(
            not isinstance(item, MonitoringReleaseDossierSignoff) for item in signoffs
        ):
            raise MonitoringReleaseDossierError(
                "signoffs must contain dossier signoff objects"
            )
        if tuple(item.role for item in signoffs) != REQUIRED_DOSSIER_SIGNOFF_ROLES:
            raise MonitoringReleaseDossierError(
                "signoffs must contain the required roles in canonical order"
            )

        residual_risks = tuple(self.residual_risks)
        if any(
            not isinstance(item, MonitoringResidualRiskDisposition)
            for item in residual_risks
        ):
            raise MonitoringReleaseDossierError(
                "residual_risks must contain disposition objects"
            )
        if len({item.risk_id for item in residual_risks}) != len(residual_risks):
            raise MonitoringReleaseDossierError("residual risk IDs must not repeat")
        residual_risks = tuple(sorted(residual_risks, key=lambda item: item.risk_id))

        reasons: list[str] = []
        for section in sections:
            if section.status != ReleaseDossierSectionStatus.PASSED:
                reasons.append(f"section:{section.section_id}:{section.status.value}")
            reasons.extend(
                f"control:{section.section_id}:{control_id}"
                for control_id in section.unmet_control_ids
            )
        reasons.extend(
            f"residual_risk:{item.risk_id}:{item.status.value}"
            for item in residual_risks
            if item.blocks_release
        )
        release_ready = not reasons
        status = (
            ReleaseDossierSectionStatus.PASSED
            if release_ready
            else ReleaseDossierSectionStatus.BLOCKED
            if any(
                item.status == ReleaseDossierSectionStatus.BLOCKED for item in sections
            )
            or any(item.blocks_release for item in residual_risks)
            else ReleaseDossierSectionStatus.UNPROVEN
            if all(
                item.status == ReleaseDossierSectionStatus.UNPROVEN for item in sections
            )
            else ReleaseDossierSectionStatus.PARTIAL
        )
        object.__setattr__(self, "sections", sections)
        object.__setattr__(self, "signoffs", signoffs)
        object.__setattr__(self, "residual_risks", residual_risks)
        object.__setattr__(self, "blocking_reasons", tuple(reasons))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "release_ready", release_ready)
        object.__setattr__(self, "dossier_sha256", _digest(self._payload()))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "dossier_id": self.dossier_id,
            "release_version": self.release_version,
            "generated_at": self.generated_at,
            "sections": [item.to_dict() for item in self.sections],
            "signoffs": [item.to_dict() for item in self.signoffs],
            "residual_risks": [item.to_dict() for item in self.residual_risks],
            "authority_granted": self.authority_granted,
            "status": self.status.value,
            "release_ready": self.release_ready,
            "blocking_reasons": list(self.blocking_reasons),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "dossier_sha256": self.dossier_sha256}


def release_dossier_gate_evidence(
    dossier: MonitoringReleaseDossier,
) -> MonitoringReleaseGateEvidence:
    """Convert a dossier into the canonical commercial release-gate row."""

    if not isinstance(dossier, MonitoringReleaseDossier):
        raise MonitoringReleaseDossierError(
            "dossier must be a MonitoringReleaseDossier"
        )
    status = (
        ReleaseEvidenceStatus.PASSED
        if dossier.release_ready
        else ReleaseEvidenceStatus.BLOCKED
        if dossier.status == ReleaseDossierSectionStatus.BLOCKED
        else ReleaseEvidenceStatus.UNPROVEN
        if dossier.status == ReleaseDossierSectionStatus.UNPROVEN
        else ReleaseEvidenceStatus.PARTIAL
    )
    summary = (
        f"commercial dossier {dossier.dossier_id} for {dossier.release_version}: "
        f"{dossier.status.value}; release_ready={str(dossier.release_ready).lower()}"
    )
    return MonitoringReleaseGateEvidence(
        gate_id="commercial_release_dossier",
        status=status,
        evidence_ids=(f"commercial-dossier:{dossier.dossier_id}",),
        evidence_sha256=dossier.dossier_sha256,
        summary=summary,
    )


def bind_release_dossier_evidence(
    gates: Iterable[MonitoringReleaseGateEvidence],
    dossier: MonitoringReleaseDossier,
) -> tuple[MonitoringReleaseGateEvidence, ...]:
    """Bind the dossier hash/status to a gate set, rejecting stale rows."""

    if not isinstance(dossier, MonitoringReleaseDossier):
        raise MonitoringReleaseDossierError(
            "dossier must be a MonitoringReleaseDossier"
        )
    provided = tuple(gates)
    if any(not isinstance(item, MonitoringReleaseGateEvidence) for item in provided):
        raise MonitoringReleaseDossierError(
            "gates must contain release evidence objects"
        )
    dossier_gate = release_dossier_gate_evidence(dossier)
    matching = tuple(item for item in provided if item.gate_id == dossier_gate.gate_id)
    if len(matching) > 1:
        raise MonitoringReleaseDossierError(
            "commercial_release_dossier gate must not repeat"
        )
    if matching and matching[0].to_dict() != dossier_gate.to_dict():
        raise MonitoringReleaseDossierError(
            "commercial_release_dossier gate does not match the dossier hash/status"
        )
    if matching:
        return provided
    return (*provided, dossier_gate)


__all__ = [
    "RELEASE_DOSSIER_SCHEMA_VERSION",
    "REQUIRED_DOSSIER_CONTROLS",
    "REQUIRED_DOSSIER_SECTION_IDS",
    "REQUIRED_DOSSIER_SIGNOFF_ROLES",
    "MonitoringReleaseDossier",
    "MonitoringReleaseDossierError",
    "MonitoringReleaseDossierSection",
    "MonitoringReleaseDossierSignoff",
    "MonitoringResidualRiskDisposition",
    "ReleaseDossierSectionStatus",
    "ResidualRiskSeverity",
    "ResidualRiskStatus",
    "bind_release_dossier_evidence",
    "release_dossier_gate_evidence",
]
