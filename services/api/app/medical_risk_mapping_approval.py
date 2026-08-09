"""Fail-closed approval gate for risk identity mapping candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from packages.contracts.workbench_contracts.models import RuxRiskDispositionRecord

from .medical_risk_mapping import (
    MedicalRiskMappingCandidate,
    remap_disposition_for_dry_run,
)


class MedicalRiskMappingApprovalError(ValueError):
    pass


class MedicalRiskMappingApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalRiskMappingApprovalError(f"{field_name} is required")
    return text


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MedicalRiskMappingApprovalError("reviewed_at must include a timezone")
    return value.astimezone(timezone.utc)


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def mapping_candidate_fingerprint(candidate: MedicalRiskMappingCandidate) -> str:
    """Hash only mapping identity, not mutable approval/review fields."""

    return _digest(
        {
            "disposition_record_id": candidate.disposition_record_id,
            "project_id": candidate.project_id,
            "legacy_risk_id": candidate.legacy_risk_id,
            "legacy_risk_key": candidate.legacy_risk_key,
            "legacy_risk_instance_id": candidate.legacy_risk_instance_id,
            "current_risk_id": candidate.current_risk_id,
            "current_risk_key": candidate.current_risk_key,
            "current_risk_instance_id": candidate.current_risk_instance_id,
            "current_subject_id": candidate.current_subject_id,
            "current_site_id": candidate.current_site_id,
            "current_source_revision": candidate.current_source_revision,
            "basis": candidate.basis.value,
            "confidence": candidate.confidence,
        }
    )


@dataclass(frozen=True)
class MedicalRiskMappingApproval:
    approval_id: str
    candidate_record_id: str
    candidate_fingerprint: str
    reviewer: str
    reviewed_at: datetime
    decision: MedicalRiskMappingApprovalDecision
    source_evidence: tuple[str, ...]
    residual_blockers: tuple[str, ...] = ()
    comment: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.decision, MedicalRiskMappingApprovalDecision):
            object.__setattr__(
                self,
                "decision",
                MedicalRiskMappingApprovalDecision(self.decision),
            )
        object.__setattr__(self, "approval_id", _required(self.approval_id, "approval_id"))
        object.__setattr__(
            self,
            "candidate_record_id",
            _required(self.candidate_record_id, "candidate_record_id"),
        )
        fingerprint = _required(self.candidate_fingerprint, "candidate_fingerprint")
        if len(fingerprint) != 64 or any(char not in "0123456789abcdef" for char in fingerprint):
            raise MedicalRiskMappingApprovalError("candidate_fingerprint must be a SHA-256 hex digest")
        object.__setattr__(self, "candidate_fingerprint", fingerprint)
        object.__setattr__(self, "reviewer", _required(self.reviewer, "reviewer"))
        object.__setattr__(self, "reviewed_at", _utc(self.reviewed_at))
        evidence = tuple(dict.fromkeys(str(item).strip() for item in self.source_evidence if str(item).strip()))
        if not evidence:
            raise MedicalRiskMappingApprovalError("source_evidence is required")
        object.__setattr__(self, "source_evidence", evidence)
        blockers = tuple(dict.fromkeys(str(item).strip() for item in self.residual_blockers if str(item).strip()))
        object.__setattr__(self, "residual_blockers", blockers)
        object.__setattr__(self, "comment", str(self.comment or "").strip())
        if self.decision == MedicalRiskMappingApprovalDecision.APPROVE and blockers:
            raise MedicalRiskMappingApprovalError(
                "mapping cannot be approved while residual blockers remain"
            )

    def public_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "candidate_record_id": self.candidate_record_id,
            "candidate_fingerprint": self.candidate_fingerprint,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at.isoformat(),
            "decision": self.decision.value,
            "source_evidence": list(self.source_evidence),
            "residual_blockers": list(self.residual_blockers),
            "comment": self.comment,
        }


@dataclass(frozen=True)
class ApprovedMedicalRiskMapping:
    candidate: MedicalRiskMappingCandidate
    approval: MedicalRiskMappingApproval

    def __post_init__(self) -> None:
        if self.approval.decision != MedicalRiskMappingApprovalDecision.APPROVE:
            raise MedicalRiskMappingApprovalError("mapping approval decision is not approve")
        if self.approval.candidate_record_id != self.candidate.disposition_record_id:
            raise MedicalRiskMappingApprovalError("approval record id does not match candidate")
        if self.approval.candidate_fingerprint != mapping_candidate_fingerprint(self.candidate):
            raise MedicalRiskMappingApprovalError("approval fingerprint does not match candidate")
        if not self.candidate.has_candidate:
            raise MedicalRiskMappingApprovalError("cannot approve a candidate without a current risk instance")

    def public_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.public_dict(),
            "approval": self.approval.public_dict(),
            "approved": True,
            "write_permitted": False,
        }


def approve_mapping_candidate(
    candidate: MedicalRiskMappingCandidate,
    approval: MedicalRiskMappingApproval,
) -> ApprovedMedicalRiskMapping:
    """Validate external approval evidence without changing the candidate."""

    if approval.decision != MedicalRiskMappingApprovalDecision.APPROVE:
        raise MedicalRiskMappingApprovalError("candidate was not approved")
    return ApprovedMedicalRiskMapping(candidate=candidate, approval=approval)


def remap_with_approved_mapping(
    record: RuxRiskDispositionRecord,
    approved: ApprovedMedicalRiskMapping,
) -> RuxRiskDispositionRecord:
    """Return an in-memory copy; this function has no persistence capability."""

    if record.record_id != approved.candidate.disposition_record_id:
        raise MedicalRiskMappingApprovalError("record does not match approved mapping")
    return remap_disposition_for_dry_run(record, approved.candidate)


__all__ = [
    "ApprovedMedicalRiskMapping",
    "MedicalRiskMappingApproval",
    "MedicalRiskMappingApprovalDecision",
    "MedicalRiskMappingApprovalError",
    "approve_mapping_candidate",
    "mapping_candidate_fingerprint",
    "remap_with_approved_mapping",
]
