"""Fail-closed, non-writing review gate for risk identity mappings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping

from .medical_risk_mapping import MedicalRiskMappingCandidate
from .medical_risk_mapping_approval import mapping_candidate_fingerprint


class MedicalRiskMappingReviewError(ValueError):
    """Raised when review evidence cannot be safely bound to candidates."""


class MedicalRiskMappingReviewDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    PENDING = "pending_review"


class MedicalRiskMappingReviewStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    APPROVED_INPUT_READY = "approved_input_ready"
    INVALID_REVIEW_INPUT = "invalid_review_input"


def _required(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise MedicalRiskMappingReviewError(f"{field_name} is required")
    return text


def _sha256_hex(value: Any, field_name: str) -> str:
    text = _required(value, field_name)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise MedicalRiskMappingReviewError(f"{field_name} must be a SHA-256 hex digest")
    return text


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MedicalRiskMappingReviewError("reviewed_at must include a timezone")
    return value.astimezone(timezone.utc)


def _unique_text(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))


@dataclass(frozen=True)
class MedicalRiskMappingReviewOutcome:
    """One explicit external review decision for one exact candidate."""

    review_id: str
    candidate_record_id: str
    candidate_fingerprint: str
    b4_package_sha256: str
    b3_report_hash: str
    reviewer: str
    reviewed_at: datetime
    decision: MedicalRiskMappingReviewDecision
    source_evidence: tuple[str, ...]
    resolved_blockers: tuple[str, ...] = ()
    residual_blockers: tuple[str, ...] = ()
    comment: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.decision, MedicalRiskMappingReviewDecision):
            object.__setattr__(
                self,
                "decision",
                MedicalRiskMappingReviewDecision(self.decision),
            )
        object.__setattr__(self, "review_id", _required(self.review_id, "review_id"))
        object.__setattr__(
            self,
            "candidate_record_id",
            _required(self.candidate_record_id, "candidate_record_id"),
        )
        object.__setattr__(
            self,
            "candidate_fingerprint",
            _sha256_hex(self.candidate_fingerprint, "candidate_fingerprint"),
        )
        object.__setattr__(
            self,
            "b4_package_sha256",
            _sha256_hex(self.b4_package_sha256, "b4_package_sha256"),
        )
        object.__setattr__(self, "b3_report_hash", _sha256_hex(self.b3_report_hash, "b3_report_hash"))
        object.__setattr__(self, "reviewer", _required(self.reviewer, "reviewer"))
        object.__setattr__(self, "reviewed_at", _utc(self.reviewed_at))
        evidence = _unique_text(self.source_evidence)
        if not evidence:
            raise MedicalRiskMappingReviewError("source_evidence is required")
        object.__setattr__(self, "source_evidence", evidence)
        object.__setattr__(self, "resolved_blockers", _unique_text(self.resolved_blockers))
        blockers = _unique_text(self.residual_blockers)
        object.__setattr__(self, "residual_blockers", blockers)
        object.__setattr__(self, "comment", str(self.comment or "").strip())
        if self.decision == MedicalRiskMappingReviewDecision.APPROVE and blockers:
            raise MedicalRiskMappingReviewError(
                "mapping review cannot approve while residual blockers remain"
            )

    def public_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "candidate_record_id": self.candidate_record_id,
            "candidate_fingerprint": self.candidate_fingerprint,
            "b4_package_sha256": self.b4_package_sha256,
            "b3_report_hash": self.b3_report_hash,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at.isoformat(),
            "decision": self.decision.value,
            "source_evidence": list(self.source_evidence),
            "resolved_blockers": list(self.resolved_blockers),
            "residual_blockers": list(self.residual_blockers),
            "comment": self.comment,
        }


@dataclass(frozen=True)
class MedicalRiskMappingReviewGateResult:
    """Read-only result; even a ready result never grants persistence."""

    status: MedicalRiskMappingReviewStatus
    migration_ready: bool
    write_permitted: bool
    candidate_count: int
    outcome_count: int
    missing_candidate_record_ids: tuple[str, ...]
    rejected_candidate_record_ids: tuple[str, ...]
    pending_candidate_record_ids: tuple[str, ...]
    unresolved_blockers: tuple[str, ...]
    accepted_review_ids: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "migration_ready": self.migration_ready,
            "write_permitted": self.write_permitted,
            "candidate_count": self.candidate_count,
            "outcome_count": self.outcome_count,
            "missing_candidate_record_ids": list(self.missing_candidate_record_ids),
            "rejected_candidate_record_ids": list(self.rejected_candidate_record_ids),
            "pending_candidate_record_ids": list(self.pending_candidate_record_ids),
            "unresolved_blockers": list(self.unresolved_blockers),
            "accepted_review_ids": list(self.accepted_review_ids),
        }


def evaluate_mapping_review_outcomes(
    candidates: Iterable[MedicalRiskMappingCandidate],
    outcomes: Iterable[MedicalRiskMappingReviewOutcome],
    *,
    b4_package_sha256: str,
    b3_report_hash: str,
    residual_blockers_by_record: Mapping[str, Iterable[str]],
) -> MedicalRiskMappingReviewGateResult:
    """Validate explicit outcomes without mutating candidates or persisting state."""

    expected_package_hash = _sha256_hex(b4_package_sha256, "b4_package_sha256")
    expected_b3_hash = _sha256_hex(b3_report_hash, "b3_report_hash")
    candidate_rows = tuple(candidates)
    candidate_by_id: dict[str, MedicalRiskMappingCandidate] = {}
    for candidate in candidate_rows:
        if candidate.disposition_record_id in candidate_by_id:
            raise MedicalRiskMappingReviewError(
                f"duplicate candidate record id: {candidate.disposition_record_id}"
            )
        if candidate.approved or candidate.write_permitted:
            raise MedicalRiskMappingReviewError(
                f"candidate is already marked writable: {candidate.disposition_record_id}"
            )
        candidate_by_id[candidate.disposition_record_id] = candidate

    outcome_rows = tuple(outcomes)
    outcome_by_id: dict[str, MedicalRiskMappingReviewOutcome] = {}
    for outcome in outcome_rows:
        if outcome.candidate_record_id in outcome_by_id:
            raise MedicalRiskMappingReviewError(
                f"duplicate review outcome: {outcome.candidate_record_id}"
            )
        candidate = candidate_by_id.get(outcome.candidate_record_id)
        if candidate is None:
            raise MedicalRiskMappingReviewError(
                f"review outcome references unknown candidate: {outcome.candidate_record_id}"
            )
        if outcome.b4_package_sha256 != expected_package_hash:
            raise MedicalRiskMappingReviewError(
                f"review outcome package hash mismatch: {outcome.candidate_record_id}"
            )
        if outcome.b3_report_hash != expected_b3_hash:
            raise MedicalRiskMappingReviewError(
                f"review outcome B3 hash mismatch: {outcome.candidate_record_id}"
            )
        if outcome.candidate_fingerprint != mapping_candidate_fingerprint(candidate):
            raise MedicalRiskMappingReviewError(
                f"review outcome candidate fingerprint mismatch: {outcome.candidate_record_id}"
            )
        expected_blockers = set(
            _unique_text(residual_blockers_by_record.get(outcome.candidate_record_id, ()))
        )
        resolved = set(outcome.resolved_blockers)
        if outcome.decision == MedicalRiskMappingReviewDecision.APPROVE:
            missing_resolutions = expected_blockers - resolved
            if missing_resolutions:
                missing = ", ".join(sorted(missing_resolutions))
                raise MedicalRiskMappingReviewError(
                    f"approval does not resolve residual blockers for "
                    f"{outcome.candidate_record_id}: {missing}"
                )
            if not candidate.has_candidate:
                raise MedicalRiskMappingReviewError(
                    f"cannot approve candidate without current risk instance: "
                    f"{outcome.candidate_record_id}"
                )
        outcome_by_id[outcome.candidate_record_id] = outcome

    missing_ids = tuple(sorted(set(candidate_by_id) - set(outcome_by_id)))
    rejected_ids = tuple(
        sorted(
            record_id
            for record_id, outcome in outcome_by_id.items()
            if outcome.decision == MedicalRiskMappingReviewDecision.REJECT
        )
    )
    pending_ids = tuple(
        sorted(
            record_id
            for record_id, outcome in outcome_by_id.items()
            if outcome.decision == MedicalRiskMappingReviewDecision.PENDING
        )
    )
    unresolved: set[str] = set()
    for record_id, blockers in residual_blockers_by_record.items():
        if record_id not in candidate_by_id:
            continue
        outcome = outcome_by_id.get(record_id)
        if outcome is None or outcome.decision != MedicalRiskMappingReviewDecision.APPROVE:
            unresolved.update(_unique_text(blockers))

    all_approved = (
        bool(candidate_by_id)
        and not missing_ids
        and not rejected_ids
        and not pending_ids
        and len(outcome_by_id) == len(candidate_by_id)
    )
    status = (
        MedicalRiskMappingReviewStatus.APPROVED_INPUT_READY
        if all_approved
        else MedicalRiskMappingReviewStatus.REJECTED
        if rejected_ids
        else MedicalRiskMappingReviewStatus.PENDING_REVIEW
    )
    return MedicalRiskMappingReviewGateResult(
        status=status,
        migration_ready=all_approved,
        write_permitted=False,
        candidate_count=len(candidate_by_id),
        outcome_count=len(outcome_by_id),
        missing_candidate_record_ids=missing_ids,
        rejected_candidate_record_ids=rejected_ids,
        pending_candidate_record_ids=pending_ids,
        unresolved_blockers=tuple(sorted(unresolved)),
        accepted_review_ids=tuple(
            sorted(
                outcome.review_id
                for outcome in outcome_by_id.values()
                if outcome.decision == MedicalRiskMappingReviewDecision.APPROVE
            )
        ),
    )


__all__ = [
    "MedicalRiskMappingReviewDecision",
    "MedicalRiskMappingReviewError",
    "MedicalRiskMappingReviewOutcome",
    "MedicalRiskMappingReviewStatus",
    "MedicalRiskMappingReviewGateResult",
    "evaluate_mapping_review_outcomes",
]
