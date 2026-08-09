from __future__ import annotations

import json
import math
import re
from datetime import datetime
from enum import Enum
from hashlib import sha256
from typing import Any, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    field_validator,
    model_validator,
)


MONITORING_AI_SCHEMA_VERSION = "monitoring_ai_v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_REVISION_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{2,240}$")
_FORBIDDEN_CONFIRMED_PHRASES = (
    "已医学批准",
    "已获医学批准",
    "待医学批准",
    "待批准",
    "无需人工复核",
    "可直接外发",
    "确定为AE漏报",
    "确定为MH漏报",
    "确定为方案违背",
)


def canonical_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def content_sha256(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha256(value: Any, message: str) -> str:
    """Require an already-canonical digest; never coerce persisted evidence."""
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(message)
    return value


class MonitoringAiTaskType(str, Enum):
    LISTING_FIELD_MAPPING = "listing_field_mapping"
    PROTOCOL_CLAUSE_STRUCTURING = "protocol_clause_structuring"
    RULE_TEMPLATE_RECOMMENDATION = "rule_template_recommendation"
    CROSS_TABLE_CLUE_SYNTHESIS = "cross_table_clue_synthesis"
    RISK_EVIDENCE_SUMMARY = "risk_evidence_summary"
    RISK_QUESTION_ANSWER = "risk_question_answer"
    QUERY_EXPLANATION_CANDIDATES = "query_explanation_candidates"


class MonitoringAiJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    STALE_INPUT = "stale_input"
    CANCELLED = "cancelled"


class MonitoringAiCandidateStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class MonitoringAiClaimKind(str, Enum):
    FACT = "fact"
    INFERENCE = "inference"
    RECOMMENDATION = "recommendation"
    DATA_GAP = "data_gap"


class MonitoringAiSourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_entry_id: str = Field(min_length=2, max_length=160)
    source_content_sha256: str

    @field_validator("source_entry_id")
    @classmethod
    def validate_source_entry_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("source_content_sha256")
    @classmethod
    def validate_source_hash(cls, value: str) -> str:
        return _require_sha256(
            value,
            "source binding requires lowercase SHA-256",
        )


class MonitoringAiInputRevision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=2, max_length=120)
    batch_revision: str = ""
    mapping_revision: str = ""
    source_binding_revision: str = ""
    fact_revision: str = ""
    protocol_version: str = ""
    rule_pack_revision: str = ""
    risk_snapshot_revision: str = ""
    sources: tuple[MonitoringAiSourceBinding, ...] = ()

    @field_validator(
        "project_id",
        "batch_revision",
        "mapping_revision",
        "source_binding_revision",
        "fact_revision",
        "protocol_version",
        "rule_pack_revision",
        "risk_snapshot_revision",
    )
    @classmethod
    def strip_revision_text(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned and not _REVISION_RE.fullmatch(cleaned):
            raise ValueError("revision contains unsupported characters")
        return cleaned

    @field_validator("sources")
    @classmethod
    def validate_sources(
        cls,
        value: tuple[MonitoringAiSourceBinding, ...],
    ) -> tuple[MonitoringAiSourceBinding, ...]:
        pairs = [(item.source_entry_id, item.source_content_sha256) for item in value]
        if len(pairs) != len(set(pairs)):
            raise ValueError("source bindings must be unique")
        entry_ids = [entry_id for entry_id, _ in pairs]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("one source entry ID cannot bind multiple hashes")
        return tuple(
            sorted(
                value,
                key=lambda item: (
                    item.source_entry_id,
                    item.source_content_sha256,
                ),
            )
        )

    @model_validator(mode="after")
    def validate_task_anchor(self) -> "MonitoringAiInputRevision":
        if not any(
            (
                self.batch_revision,
                self.fact_revision,
                self.protocol_version,
                self.risk_snapshot_revision,
            )
        ):
            raise ValueError(
                "input revision requires batch, protocol or risk snapshot anchor"
            )
        return self

    @property
    def revision_sha256(self) -> str:
        payload = self.model_dump(mode="json")
        if not self.fact_revision:
            payload.pop("fact_revision", None)
        if not self.source_binding_revision:
            payload.pop("source_binding_revision", None)
        return content_sha256(payload)

    @property
    def source_entry_ids(self) -> tuple[str, ...]:
        return tuple(item.source_entry_id for item in self.sources)

    @property
    def source_content_sha256s(self) -> tuple[str, ...]:
        return tuple(item.source_content_sha256 for item in self.sources)

    @property
    def source_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset(
            (item.source_entry_id, item.source_content_sha256) for item in self.sources
        )


class MonitoringAiEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=2, max_length=160)
    source_entry_id: str = Field(min_length=2, max_length=160)
    source_content_sha256: str
    locator: str = Field(min_length=2, max_length=1_000)
    quote: str = Field(default="", max_length=8_000)
    raw_fields: dict[str, Any] = Field(default_factory=dict)
    input_revision_sha256: str

    @field_validator("source_content_sha256", "input_revision_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return _require_sha256(
            value,
            "evidence hashes must be lowercase SHA-256",
        )

    @model_validator(mode="after")
    def require_source_content(self) -> "MonitoringAiEvidence":
        if not self.quote.strip() and not self.raw_fields:
            raise ValueError("evidence requires quote or raw fields")
        return self


class MonitoringAiClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=2, max_length=160)
    kind: MonitoringAiClaimKind
    text: str = Field(min_length=1, max_length=8_000)
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    uncertainty: str = Field(default="", max_length=4_000)
    user_action: str = Field(default="", max_length=2_000)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(item.strip() for item in value)
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("claim evidence IDs must be non-empty and unique")
        return cleaned

    @model_validator(mode="after")
    def validate_language_boundary(self) -> "MonitoringAiClaim":
        combined = f"{self.text}\n{self.user_action}"
        if any(phrase in combined for phrase in _FORBIDDEN_CONFIRMED_PHRASES):
            raise ValueError("claim contains an unauthorized definitive conclusion")
        if (
            self.kind
            in {
                MonitoringAiClaimKind.INFERENCE,
                MonitoringAiClaimKind.RECOMMENDATION,
            }
            and not self.uncertainty.strip()
        ):
            raise ValueError("inference and recommendation require uncertainty")
        return self


class MonitoringAiCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=2, max_length=160)
    job_id: str = Field(min_length=2, max_length=160)
    project_id: str = Field(min_length=2, max_length=120)
    task_type: MonitoringAiTaskType
    candidate_type: str = Field(min_length=2, max_length=120)
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(default="", max_length=20_000)
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    claims: tuple[MonitoringAiClaim, ...] = Field(min_length=1, max_length=100)
    evidence: tuple[MonitoringAiEvidence, ...] = Field(min_length=1, max_length=200)
    status: MonitoringAiCandidateStatus = MonitoringAiCandidateStatus.PROPOSED
    input_revision_sha256: str
    prompt_version: str = Field(min_length=2, max_length=160)
    created_at: datetime

    @field_validator("input_revision_sha256")
    @classmethod
    def validate_input_hash(cls, value: str) -> str:
        return _require_sha256(
            value,
            "candidate input revision must be lowercase SHA-256",
        )

    @model_validator(mode="after")
    def validate_evidence_graph(self) -> "MonitoringAiCandidate":
        evidence_ids = {item.evidence_id for item in self.evidence}
        if len(evidence_ids) != len(self.evidence):
            raise ValueError("candidate evidence IDs must be unique")
        if any(
            not set(claim.evidence_ids).issubset(evidence_ids) for claim in self.claims
        ):
            raise ValueError("candidate claim references unknown evidence")
        if any(
            item.input_revision_sha256 != self.input_revision_sha256
            for item in self.evidence
        ):
            raise ValueError("candidate evidence belongs to another input revision")
        return self


# This is a workbench governance threshold, not a calibrated clinical
# probability.  It only controls presentation and the minimum explanation
# required for a user-confirmed adoption; it never turns an AI score into a
# medical conclusion.
MONITORING_AI_LOW_CONFIDENCE_THRESHOLD = 0.70


def candidate_confidence_summary(
    candidate: MonitoringAiCandidate,
) -> dict[str, Any]:
    """Return one shared, fail-closed confidence/next-step contract.

    All AI candidates remain user-confirmation gated.  A claim below the
    workbench threshold (or a malformed confidence value) is still shown as a
    candidate so the medical monitor can inspect it, but it is explicitly
    marked as needing additional evidence or an explanation before acceptance.
    Deterministic/no-claim candidates are reported as ``not_scored`` rather
    than being mistaken for high-confidence AI output.
    """

    claims = tuple(getattr(candidate, "claims", ()) or ())
    confidences: list[float] = []
    malformed = False
    for claim in claims:
        try:
            value = float(claim.confidence)
        except (TypeError, ValueError):
            malformed = True
            continue
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            malformed = True
            continue
        confidences.append(value)

    if not claims:
        return {
            "status": "not_scored",
            "label": "未提供语义置信度，需确认来源",
            "confidence_floor": None,
            "threshold": MONITORING_AI_LOW_CONFIDENCE_THRESHOLD,
            "claim_count": 0,
            "requires_user_review": True,
            "requires_additional_evidence": False,
            "automation_permitted": False,
            "next_step": "medical_manager_confirmation",
        }

    floor = min(confidences) if confidences else None
    low = malformed or floor is None or floor < MONITORING_AI_LOW_CONFIDENCE_THRESHOLD
    return {
        "status": "low" if low else "review_required",
        "label": (
            "低置信度，需补充证据或说明"
            if low
            else "达到工作台阈值，仍需医学确认"
        ),
        "confidence_floor": floor,
        "threshold": MONITORING_AI_LOW_CONFIDENCE_THRESHOLD,
        "claim_count": len(claims),
        "requires_user_review": True,
        "requires_additional_evidence": low,
        "automation_permitted": False,
        "next_step": (
            "source_review_or_more_data"
            if low
            else "medical_manager_confirmation"
        ),
    }


class MonitoringAiJobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=2, max_length=120)
    task_type: MonitoringAiTaskType
    input_revision: MonitoringAiInputRevision
    input_payload: dict[str, Any]
    prompt_version: str = Field(min_length=2, max_length=160)
    profile_id: str = Field(min_length=2, max_length=160)
    provider: str = Field(min_length=2, max_length=160)
    requested_model: str = Field(min_length=1, max_length=240)
    max_attempts: StrictInt = Field(default=2, ge=1, le=3)
    business_key: str = Field(min_length=2, max_length=240)

    @model_validator(mode="after")
    def validate_project(self) -> "MonitoringAiJobCreate":
        if self.project_id != self.input_revision.project_id:
            raise ValueError("job project does not match input revision")
        return self

    @property
    def input_revision_sha256(self) -> str:
        return self.input_revision.revision_sha256

    @property
    def input_payload_sha256(self) -> str:
        return content_sha256(self.input_payload)


class MonitoringAiJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str
    project_id: str
    task_type: MonitoringAiTaskType
    status: MonitoringAiJobStatus
    business_key: str
    input_revision: MonitoringAiInputRevision
    input_revision_sha256: str
    input_payload_sha256: str
    prompt_version: str
    profile_id: str
    provider: str
    requested_model: str
    response_model: str = ""
    attempt_count: StrictInt = 0
    max_attempts: StrictInt = 2
    lease_owner: str = ""
    lease_expires_at: Optional[datetime] = None
    output_sha256: str = ""
    failure_code: str = ""
    failure_message: str = ""
    retryable: StrictBool = False
    contract_retirement_code: str = ""
    contract_retirement_reason: str = ""
    contract_retired_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class MonitoringAiConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str
    project_id: str
    job_id: str
    actor: str
    message: str = Field(min_length=1, max_length=20_000)
    input_revision_sha256: str
    created_at: datetime


def validate_candidates_for_job(
    job: MonitoringAiJob,
    candidates: tuple[MonitoringAiCandidate, ...],
) -> None:
    if not candidates:
        raise ValueError("completed monitoring AI job requires candidates")
    candidate_ids = {item.candidate_id for item in candidates}
    if len(candidate_ids) != len(candidates):
        raise ValueError("candidate IDs must be unique")
    for candidate in candidates:
        if (
            candidate.job_id != job.job_id
            or candidate.project_id != job.project_id
            or candidate.task_type != job.task_type
            or candidate.input_revision_sha256 != job.input_revision_sha256
            or candidate.prompt_version != job.prompt_version
        ):
            raise ValueError("candidate does not match its monitoring AI job")
        if candidate.status != MonitoringAiCandidateStatus.PROPOSED:
            raise ValueError("provider output candidates must start as proposed")
        allowed_pairs = job.input_revision.source_pairs
        for evidence in candidate.evidence:
            source_pair = (
                evidence.source_entry_id,
                evidence.source_content_sha256,
            )
            # Source-less revisions remain useful for recovery/data-gap
            # inspection, but a provider candidate is never acceptable without
            # an explicit source/hash pair in its input revision.
            if source_pair not in allowed_pairs:
                raise ValueError(
                    "candidate evidence source/hash pair is not in the input revision"
                )

    if job.task_type == MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES and not (
        2 <= len(candidates) <= 3
    ):
        raise ValueError("Query/explanation task requires 2 to 3 candidates")
    if job.task_type == MonitoringAiTaskType.RULE_TEMPLATE_RECOMMENDATION and not (
        1 <= len(candidates) <= 3
    ):
        raise ValueError("Rule-template recommendation requires 1 to 3 candidates")
    if job.task_type == MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS and not (
        2 <= len(candidates) <= 3
    ):
        raise ValueError("cross-table clue task requires 2 to 3 candidates")
    if (
        job.task_type
        in {
            MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
            MonitoringAiTaskType.RISK_QUESTION_ANSWER,
        }
        and len(candidates) != 1
    ):
        raise ValueError(
            "risk summary and question-answer tasks require exactly one candidate"
        )


def stable_job_id(request: MonitoringAiJobCreate) -> str:
    identity = {
        "project_id": request.project_id,
        "task_type": request.task_type.value,
        "business_key": request.business_key,
        "input_revision_sha256": request.input_revision_sha256,
        "input_payload_sha256": request.input_payload_sha256,
        "prompt_version": request.prompt_version,
        "profile_id": request.profile_id,
        "provider": request.provider,
        "requested_model": request.requested_model,
    }
    return f"monai_{content_sha256(identity)[:28]}"
