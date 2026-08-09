from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, Iterable, Optional, Sequence, Set, Tuple
from uuid import uuid4

from .sqlite_runtime_store import SqliteRuntimeStore


class CriterionKind(str, Enum):
    INCLUSION = "inclusion"
    EXCLUSION = "exclusion"


class EligibilityDecision(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    ABSENT = "absent"
    PRESENT = "present"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"
    REQUIRES_INVESTIGATOR_JUDGMENT = "requires_investigator_judgment"


class EligibilityReviewAction(str, Enum):
    SAVE_AI_DRAFT = "save_ai_draft"
    ACCEPT_AI_DRAFT = "accept_ai_draft"
    REVISE_DECISION = "revise_decision"
    REQUEST_EVIDENCE = "request_evidence"
    DEFER_REVIEW = "defer_review"
    RESET_AFTER_SOURCE_CHANGE = "reset_after_source_change"


class EvidenceProcessingState(str, Enum):
    NOT_STARTED = "not_started"
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_VISUAL_QC = "needs_visual_qc"
    NOT_APPLICABLE = "not_applicable"


INCLUSION_DECISIONS = {
    EligibilityDecision.MET,
    EligibilityDecision.NOT_MET,
    EligibilityDecision.INSUFFICIENT_EVIDENCE,
    EligibilityDecision.NOT_APPLICABLE,
    EligibilityDecision.REQUIRES_INVESTIGATOR_JUDGMENT,
}
EXCLUSION_DECISIONS = {
    EligibilityDecision.ABSENT,
    EligibilityDecision.PRESENT,
    EligibilityDecision.INSUFFICIENT_EVIDENCE,
    EligibilityDecision.NOT_APPLICABLE,
    EligibilityDecision.REQUIRES_INVESTIGATOR_JUDGMENT,
}


@dataclass(frozen=True)
class EligibilityReviewRequest:
    project_id: str
    subject_id: str
    criterion_uid: str
    criterion_kind: CriterionKind
    expected_state_revision: int
    expected_rule_revision: str
    expected_subject_source_revision: str
    idempotency_key: str
    actor: str
    action: EligibilityReviewAction
    decision: Optional[EligibilityDecision] = None
    reason: str = ""
    evidence_ids: Tuple[str, ...] = ()
    evidence_processing_state: EvidenceProcessingState = (
        EvidenceProcessingState.NOT_STARTED
    )


@dataclass(frozen=True)
class EligibilityReviewResult:
    request_id: str
    record_id: str
    state_revision: int
    replayed: bool
    state: Dict[str, Any]


@dataclass(frozen=True)
class EligibilitySubjectAggregate:
    project_id: str
    subject_id: str
    rule_revision: str
    criterion_count: int
    reviewed_count: int
    statuses: Tuple[str, ...]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_hash(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def eligibility_subject_source_revision(
    project_id: str,
    subject_id: str,
    sources: Sequence[Dict[str, Any]],
) -> str:
    if not project_id or not subject_id or not sources:
        raise ValueError("subject source revision identity is required")
    digest_input = {
        "project_id": project_id,
        "subject_id": subject_id,
        "sources": sorted(
            (
                str(source.get("source_id") or ""),
                str(source.get("source_revision") or ""),
                str(source.get("processing_unit_kind") or "legacy_unknown"),
                int(source.get("expected_unit_count") or 0),
                str(source.get("expected_unit_count_status") or "legacy_unknown"),
            )
            for source in sources
        ),
    }
    return f"eligsubsrcv_{_canonical_hash(digest_input)[:24]}"


class EligibilityReviewWorkflow:
    def __init__(self, store: SqliteRuntimeStore):
        self.store = store

    @staticmethod
    def allowed_decisions(kind: CriterionKind) -> Set[EligibilityDecision]:
        if kind == CriterionKind.INCLUSION:
            return set(INCLUSION_DECISIONS)
        if kind == CriterionKind.EXCLUSION:
            return set(EXCLUSION_DECISIONS)
        raise ValueError(f"unsupported criterion kind: {kind}")

    def register_rule_revision(
        self,
        project_id: str,
        rule_revision: str,
        criteria: Iterable[Dict[str, Any]],
    ) -> None:
        self.store.replace_eligibility_rule_revision(
            project_id,
            rule_revision,
            criteria,
        )

    def register_subject_sources(
        self,
        project_id: str,
        subject_id: str,
        sources: Sequence[Dict[str, Any]],
        *,
        subject_source_revision: Optional[str] = None,
    ) -> str:
        if not sources:
            raise ValueError("subject source registration requires sources")
        calculated_revision = eligibility_subject_source_revision(
            project_id,
            subject_id,
            sources,
        )
        if (
            subject_source_revision is not None
            and subject_source_revision.strip() != calculated_revision
        ):
            raise ValueError(
                "subject_source_revision does not match the canonical source contract"
            )
        subject_source_revision = calculated_revision
        self.store.replace_eligibility_subject_sources(
            project_id,
            subject_id,
            subject_source_revision,
            sources,
        )
        return subject_source_revision

    def register_evidence_span(
        self,
        *,
        evidence_id: str,
        project_id: str,
        subject_id: str,
        source_id: str,
        source_revision: str,
        extraction_revision: str,
        locator: Dict[str, Any],
        media_class: str,
        processing_state: EvidenceProcessingState,
        quality_state: str,
        extraction_confidence: Optional[float],
        medical_verification_status: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.store.add_eligibility_evidence_span(
            {
                "evidence_id": evidence_id,
                "project_id": project_id,
                "subject_id": subject_id,
                "source_id": source_id,
                "source_revision": source_revision,
                "extraction_revision": extraction_revision,
                "locator": locator,
                "metadata": metadata or {},
                "media_class": media_class,
                "processing_state": processing_state.value,
                "quality_state": quality_state,
                "extraction_confidence": extraction_confidence,
                "medical_verification_status": medical_verification_status,
                "created_at": _utc_now().isoformat(),
            }
        )

    def apply_action(
        self,
        request: EligibilityReviewRequest,
    ) -> EligibilityReviewResult:
        if request.expected_state_revision < 0:
            raise ValueError("expected_state_revision must be non-negative")
        if not request.reason.strip():
            raise ValueError("eligibility review reason is required")
        if request.decision is not None and request.decision not in self.allowed_decisions(
            request.criterion_kind
        ):
            raise ValueError("decision is invalid for criterion kind")
        current = self.store.eligibility_review_state(
            request.project_id,
            request.subject_id,
            request.criterion_uid,
        )
        effective_decision = request.decision
        if request.action == EligibilityReviewAction.ACCEPT_AI_DRAFT:
            ai_draft = current.get("ai_draft_decision") if current else None
            if not ai_draft:
                raise ValueError("accept_ai_draft requires an existing AI draft")
            effective_decision = EligibilityDecision(ai_draft)
        elif request.action in {
            EligibilityReviewAction.SAVE_AI_DRAFT,
            EligibilityReviewAction.REVISE_DECISION,
        } and effective_decision is None:
            raise ValueError(f"{request.action.value} requires a decision")
        elif request.action in {
            EligibilityReviewAction.REQUEST_EVIDENCE,
            EligibilityReviewAction.DEFER_REVIEW,
            EligibilityReviewAction.RESET_AFTER_SOURCE_CHANGE,
        }:
            effective_decision = None

        decisive_decisions = {
            EligibilityDecision.MET,
            EligibilityDecision.NOT_MET,
            EligibilityDecision.ABSENT,
            EligibilityDecision.PRESENT,
        }
        if effective_decision in decisive_decisions and not request.evidence_ids:
            raise ValueError("decisive eligibility review requires evidence_ids")

        if request.action == EligibilityReviewAction.RESET_AFTER_SOURCE_CHANGE:
            if current is None:
                raise ValueError(
                    "reset_after_source_change requires an existing review state"
                )
            if (
                current.get("rule_revision") == request.expected_rule_revision
                and current.get("subject_source_revision")
                == request.expected_subject_source_revision
            ):
                raise ValueError(
                    "reset_after_source_change requires rule or source revision drift"
                )
            if request.decision is not None or request.evidence_ids:
                raise ValueError(
                    "reset_after_source_change cannot carry a decision or evidence"
                )

        record_type = (
            "ai_draft"
            if request.action == EligibilityReviewAction.SAVE_AI_DRAFT
            else "medical_action"
        )
        record_id = f"eligreview_{uuid4().hex}"
        new_revision = request.expected_state_revision + 1
        created_at = _utc_now().isoformat()
        record = {
            "record_id": record_id,
            "project_id": request.project_id,
            "subject_id": request.subject_id,
            "criterion_uid": request.criterion_uid,
            "criterion_kind": request.criterion_kind.value,
            "record_type": record_type,
            "action": request.action.value,
            "action_decision": (
                effective_decision.value if effective_decision is not None else None
            ),
            "evidence_processing_state": request.evidence_processing_state.value,
            "rule_revision": request.expected_rule_revision,
            "subject_source_revision": request.expected_subject_source_revision,
            "previous_state_revision": request.expected_state_revision,
            "new_state_revision": new_revision,
            "evidence_ids": list(request.evidence_ids),
            "reason": request.reason.strip(),
            "actor": request.actor,
            "created_at": created_at,
        }
        fingerprint = _canonical_hash(
            {
                "project_id": request.project_id,
                "subject_id": request.subject_id,
                "criterion_uid": request.criterion_uid,
                "criterion_kind": request.criterion_kind.value,
                "expected_state_revision": request.expected_state_revision,
                "expected_rule_revision": request.expected_rule_revision,
                "expected_subject_source_revision": (
                    request.expected_subject_source_revision
                ),
                "idempotency_key": request.idempotency_key,
                "actor": request.actor,
                "action": request.action.value,
                "decision": (
                    effective_decision.value if effective_decision is not None else None
                ),
                "reason": request.reason.strip(),
                "evidence_ids": list(request.evidence_ids),
                "evidence_processing_state": (
                    request.evidence_processing_state.value
                ),
            }
        )
        commit = self.store.commit_eligibility_review_action(
            record,
            expected_state_revision=request.expected_state_revision,
            expected_rule_revision=request.expected_rule_revision,
            expected_subject_source_revision=request.expected_subject_source_revision,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
        )
        state = self.store.eligibility_review_state(
            request.project_id,
            request.subject_id,
            request.criterion_uid,
        )
        if state is None:
            raise RuntimeError("eligibility review state was not persisted")
        return EligibilityReviewResult(
            request_id=commit.request_id,
            record_id=commit.record_id,
            state_revision=commit.state_revision,
            replayed=commit.replayed,
            state=state,
        )

    def aggregate_subject_review(
        self,
        project_id: str,
        subject_id: str,
    ) -> EligibilitySubjectAggregate:
        criteria = self.store.eligibility_rule_revision_rows(project_id)
        states = self.store.eligibility_subject_review_states(project_id, subject_id)
        state_by_uid = {state["criterion_uid"]: state for state in states}
        current_source_revision = (
            self.store.eligibility_current_subject_source_revision(
                project_id,
                subject_id,
            )
        )
        incomplete_actions = {
            EligibilityReviewAction.REQUEST_EVIDENCE.value,
            EligibilityReviewAction.DEFER_REVIEW.value,
            EligibilityReviewAction.RESET_AFTER_SOURCE_CHANGE.value,
        }
        statuses = set()
        reviewed_count = 0
        for criterion in criteria:
            state = state_by_uid.get(criterion["criterion_uid"])
            is_current_completed_review = (
                state is not None
                and state.get("medical_decision") is not None
                and state.get("rule_revision") == criterion["rule_revision"]
                and state.get("subject_source_revision") == current_source_revision
                and state.get("latest_action") not in incomplete_actions
            )
            if not is_current_completed_review:
                statuses.add("blocked_by_incomplete_review")
                continue
            reviewed_count += 1
            decision = state["medical_decision"]
            if decision == EligibilityDecision.INSUFFICIENT_EVIDENCE.value:
                statuses.add("has_gaps")
            elif decision == EligibilityDecision.REQUIRES_INVESTIGATOR_JUDGMENT.value:
                statuses.add("has_investigator_judgment")
            elif (
                criterion["criterion_kind"] == CriterionKind.INCLUSION.value
                and decision == EligibilityDecision.NOT_MET.value
            ):
                statuses.add("has_inclusion_failure")
            elif (
                criterion["criterion_kind"] == CriterionKind.EXCLUSION.value
                and decision == EligibilityDecision.PRESENT.value
            ):
                statuses.add("has_exclusion")

        if criteria and reviewed_count == len(criteria) and not statuses:
            statuses.add("medical_review_pending")
        if not criteria:
            statuses.add("blocked_by_missing_rules")
        rule_revision = str(criteria[0]["rule_revision"]) if criteria else ""
        return EligibilitySubjectAggregate(
            project_id=project_id,
            subject_id=subject_id,
            rule_revision=rule_revision,
            criterion_count=len(criteria),
            reviewed_count=reviewed_count,
            statuses=tuple(sorted(statuses)),
        )
