"""Offline quality evidence for the independent medical-monitoring AI.

This module deliberately does not dispatch providers, mutate the AI queue, or
make a medical/release decision.  It turns an already persisted job/attempt
snapshot into a compact, hashable quality observation so Phase F can compare
prompt/model/source revisions, failure and repair behaviour, resource use and
human feedback without treating an AI result as a clinical fact.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import re
from typing import Any, Iterable, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .monitoring_ai_contracts import (
    MonitoringAiInputRevision,
    MonitoringAiJob,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    canonical_json,
    content_sha256,
)


QUALITY_SCHEMA_VERSION = "monitoring_ai_quality_v1"


class MonitoringAiQualityOutcome(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    STALE_INPUT = "stale_input"
    CANCELLED = "cancelled"


class MonitoringAiRepairOutcome(str, Enum):
    NONE = "none"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class MonitoringAiHumanReviewOutcome(str, Enum):
    NOT_REVIEWED = "not_reviewed"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_SUCCESS_ATTEMPT_OUTCOMES = frozenset(
    {"success", "success_repaired", "success_deterministic", "completed"}
)
_STALE_ATTEMPT_OUTCOMES = frozenset({"stale_input", "stale"})
_BLOCKED_ATTEMPT_OUTCOMES = frozenset({"blocked"})
_CANCELLED_ATTEMPT_OUTCOMES = frozenset({"cancelled", "canceled"})


def _quality_outcome_for_attempt(raw_outcome: str) -> MonitoringAiQualityOutcome:
    if raw_outcome in _SUCCESS_ATTEMPT_OUTCOMES:
        return MonitoringAiQualityOutcome.COMPLETED
    if raw_outcome in _STALE_ATTEMPT_OUTCOMES:
        return MonitoringAiQualityOutcome.STALE_INPUT
    if raw_outcome in _BLOCKED_ATTEMPT_OUTCOMES:
        return MonitoringAiQualityOutcome.BLOCKED
    if raw_outcome in _CANCELLED_ATTEMPT_OUTCOMES:
        return MonitoringAiQualityOutcome.CANCELLED
    if raw_outcome in {
        "failed",
        "invalid_output",
        "configuration_error",
        "transport_rejected",
        "identity_error",
        "provider_error",
        "worker_error",
    }:
        return MonitoringAiQualityOutcome.FAILED
    raise ValueError(f"unsupported monitoring AI attempt outcome: {raw_outcome}")


def _clean_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class MonitoringAiQualityObservation(BaseModel):
    """One immutable quality observation for one persisted AI attempt.

    Resource counters are optional because providers do not all expose them.
    Missing counters remain missing; callers must not estimate them from text
    length.  ``human_review_outcome`` is intentionally separate from the
    candidate lifecycle: it records evaluation evidence, not acceptance or
    activation authority.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = QUALITY_SCHEMA_VERSION
    observation_id: str = Field(min_length=2, max_length=180)
    project_id: str = Field(min_length=2, max_length=120)
    task_type: MonitoringAiTaskType
    job_id: str = Field(min_length=2, max_length=160)
    attempt_id: str = Field(min_length=2, max_length=160)
    attempt_number: StrictInt = Field(ge=1, le=100)
    input_revision: MonitoringAiInputRevision
    input_revision_sha256: str
    prompt_version: str = Field(min_length=2, max_length=160)
    profile_id: str = Field(min_length=2, max_length=160)
    provider: str = Field(min_length=2, max_length=160)
    requested_model: str = Field(min_length=1, max_length=240)
    response_model: str = ""
    attempt_outcome: str = Field(min_length=1, max_length=160)
    outcome: MonitoringAiQualityOutcome
    failure_code: str = Field(default="", max_length=160)
    request_sha256: str
    response_sha256: str = ""
    repair_outcome: MonitoringAiRepairOutcome = MonitoringAiRepairOutcome.NONE
    repair_ids: tuple[str, ...] = ()
    latency_ms: Optional[StrictInt] = Field(default=None, ge=0, le=7 * 24 * 60 * 60 * 1000)
    input_tokens: Optional[StrictInt] = Field(default=None, ge=0)
    output_tokens: Optional[StrictInt] = Field(default=None, ge=0)
    total_tokens: Optional[StrictInt] = Field(default=None, ge=0)
    cost_micros: Optional[StrictInt] = Field(default=None, ge=0)
    candidate_count: StrictInt = Field(default=0, ge=0, le=10_000)
    candidate_ids: tuple[str, ...] = ()
    human_review_outcome: MonitoringAiHumanReviewOutcome = (
        MonitoringAiHumanReviewOutcome.NOT_REVIEWED
    )
    reviewed_by: str = Field(default="", max_length=160)
    observed_at: datetime

    @field_validator("input_revision_sha256", "request_sha256")
    @classmethod
    def validate_hash(cls, value: str, info) -> str:
        return _clean_sha256(value, info.field_name)

    @field_validator("response_sha256")
    @classmethod
    def validate_optional_hash(cls, value: str) -> str:
        if value == "":
            return ""
        return _clean_sha256(value, "response_sha256")

    @field_validator("repair_ids", "candidate_ids")
    @classmethod
    def validate_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(str(value or "").strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("quality evidence IDs cannot be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("quality evidence IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_identity_and_outcome(self) -> "MonitoringAiQualityObservation":
        if self.project_id != self.input_revision.project_id:
            raise ValueError(
                "quality observation project does not match input revision"
            )
        if self.input_revision.revision_sha256 != self.input_revision_sha256:
            raise ValueError("quality observation input revision hash drift")
        if self.schema_version != QUALITY_SCHEMA_VERSION:
            raise ValueError("unsupported monitoring AI quality schema version")
        if self.candidate_count != len(self.candidate_ids):
            raise ValueError("candidate_count must match candidate_ids")
        if (
            self.attempt_outcome == "success_repaired"
            and self.repair_outcome != MonitoringAiRepairOutcome.SUCCEEDED
        ):
            raise ValueError(
                "success_repaired outcome requires successful repair evidence"
            )
        if self.outcome == MonitoringAiQualityOutcome.COMPLETED:
            if not self.response_model:
                raise ValueError(
                    "completed quality observation requires response model"
                )
            if self.response_model != self.requested_model:
                raise ValueError("completed response model does not match request")
            if self.failure_code:
                raise ValueError(
                    "completed quality observation cannot have failure code"
                )
            if self.candidate_count < 1:
                raise ValueError("completed quality observation requires a candidate")
        elif not self.failure_code:
            raise ValueError("non-completed quality observation requires failure code")
        if self.repair_outcome == MonitoringAiRepairOutcome.NONE and self.repair_ids:
            raise ValueError("repair IDs require a non-empty repair outcome")
        if (
            self.repair_outcome != MonitoringAiRepairOutcome.NONE
            and not self.repair_ids
        ):
            raise ValueError("repair outcome requires immutable repair IDs")
        if self.total_tokens is not None and (
            self.input_tokens is None or self.output_tokens is None
        ):
            raise ValueError("total tokens require both input and output token counts")
        if (
            self.total_tokens is not None
            and self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("total tokens do not equal input plus output tokens")
        if self.human_review_outcome == MonitoringAiHumanReviewOutcome.NOT_REVIEWED:
            if self.reviewed_by:
                raise ValueError("unreviewed observation cannot have reviewer")
        elif not self.reviewed_by:
            raise ValueError("reviewed observation requires reviewer identity")
        if (
            self.human_review_outcome
            in {
                MonitoringAiHumanReviewOutcome.ACCEPTED,
                MonitoringAiHumanReviewOutcome.EDITED,
            }
            and self.candidate_count == 0
        ):
            raise ValueError("positive human review requires a candidate")
        return self

    @property
    def source_bindings(self) -> tuple[MonitoringAiSourceBinding, ...]:
        return self.input_revision.sources

    @property
    def observation_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json"))

    @classmethod
    def from_job_attempt(
        cls,
        job: MonitoringAiJob,
        attempt: Mapping[str, Any],
        *,
        latency_ms: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        cost_micros: Optional[int] = None,
        repair_outcome: MonitoringAiRepairOutcome = MonitoringAiRepairOutcome.NONE,
        repair_ids: Iterable[str] = (),
        candidate_ids: Iterable[str] = (),
        human_review_outcome: MonitoringAiHumanReviewOutcome = (
            MonitoringAiHumanReviewOutcome.NOT_REVIEWED
        ),
        reviewed_by: str = "",
        observed_at: Optional[datetime] = None,
    ) -> "MonitoringAiQualityObservation":
        """Build evidence from repository snapshots without changing their state."""

        attempt_id = str(attempt.get("attempt_id") or "").strip()
        if not attempt_id:
            raise ValueError("attempt snapshot requires attempt_id")
        raw_attempt_number = attempt.get("attempt_number")
        if isinstance(raw_attempt_number, bool) or not isinstance(raw_attempt_number, int):
            raise ValueError("attempt snapshot requires a positive integer attempt number")
        attempt_number = raw_attempt_number
        if attempt_number < 1:
            raise ValueError("attempt snapshot requires a positive attempt number")
        task_type = (
            job.task_type
            if isinstance(job.task_type, MonitoringAiTaskType)
            else MonitoringAiTaskType(str(job.task_type))
        )
        attempt_outcome = str(attempt.get("outcome") or "").strip()
        if not attempt_outcome:
            raise ValueError("attempt snapshot requires outcome")
        outcome = _quality_outcome_for_attempt(attempt_outcome)
        candidate_id_tuple = tuple(str(value).strip() for value in candidate_ids)
        identity = {
            "project_id": job.project_id,
            "task_type": task_type.value,
            "job_id": job.job_id,
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "input_revision_sha256": job.input_revision_sha256,
            "prompt_version": job.prompt_version,
        }
        observation_id = f"monq_{content_sha256(identity)[:28]}"
        return cls(
            observation_id=observation_id,
            project_id=job.project_id,
            task_type=task_type,
            job_id=job.job_id,
            attempt_id=attempt_id,
            attempt_number=attempt_number,
            input_revision=job.input_revision,
            input_revision_sha256=job.input_revision_sha256,
            prompt_version=job.prompt_version,
            profile_id=job.profile_id,
            provider=job.provider,
            requested_model=job.requested_model,
            response_model=str(attempt.get("response_model") or ""),
            attempt_outcome=attempt_outcome,
            outcome=outcome,
            failure_code=str(attempt.get("failure_code") or "").strip(),
            request_sha256=attempt.get("request_sha256"),
            response_sha256=(
                ""
                if attempt.get("response_sha256") is None
                else attempt.get("response_sha256")
            ),
            repair_outcome=repair_outcome,
            repair_ids=tuple(str(value).strip() for value in repair_ids),
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cost_micros=cost_micros,
            candidate_count=len(candidate_id_tuple),
            candidate_ids=candidate_id_tuple,
            human_review_outcome=human_review_outcome,
            reviewed_by=reviewed_by.strip(),
            observed_at=observed_at or datetime.now().astimezone(),
        )


class MonitoringAiQualityCoverage(BaseModel):
    """Coverage summary, intentionally not a release or medical gate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = QUALITY_SCHEMA_VERSION
    observation_count: StrictInt = Field(ge=0)
    completed_count: StrictInt = Field(ge=0)
    failed_count: StrictInt = Field(ge=0)
    blocked_count: StrictInt = Field(ge=0)
    stale_count: StrictInt = Field(ge=0)
    cancelled_count: StrictInt = Field(ge=0)
    repaired_count: StrictInt = Field(ge=0)
    reviewed_count: StrictInt = Field(ge=0)
    accepted_or_edited_count: StrictInt = Field(ge=0)
    missing_project_task_pairs: tuple[tuple[str, str], ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing_project_task_pairs

    @property
    def review_rate(self) -> Optional[float]:
        if self.observation_count == 0:
            return None
        return self.reviewed_count / self.observation_count


def summarize_quality_coverage(
    observations: Iterable[MonitoringAiQualityObservation],
    *,
    expected_project_task_pairs: Iterable[tuple[str, str]] = (),
) -> MonitoringAiQualityCoverage:
    """Summarize evidence without inferring clinical correctness or release readiness."""

    items = tuple(observations)
    identities = [item.observation_id for item in items]
    if len(identities) != len(set(identities)):
        raise ValueError("quality observations must have unique observation IDs")
    observed_pairs = {(item.project_id, item.task_type.value) for item in items}
    expected_pairs = {
        (str(project).strip(), str(task).strip())
        for project, task in expected_project_task_pairs
    }
    if any(not project or not task for project, task in expected_pairs):
        raise ValueError("expected project/task pairs cannot be empty")
    return MonitoringAiQualityCoverage(
        observation_count=len(items),
        completed_count=sum(
            item.outcome == MonitoringAiQualityOutcome.COMPLETED for item in items
        ),
        failed_count=sum(
            item.outcome == MonitoringAiQualityOutcome.FAILED for item in items
        ),
        blocked_count=sum(
            item.outcome == MonitoringAiQualityOutcome.BLOCKED for item in items
        ),
        stale_count=sum(
            item.outcome == MonitoringAiQualityOutcome.STALE_INPUT for item in items
        ),
        cancelled_count=sum(
            item.outcome == MonitoringAiQualityOutcome.CANCELLED for item in items
        ),
        repaired_count=sum(
            item.repair_outcome != MonitoringAiRepairOutcome.NONE for item in items
        ),
        reviewed_count=sum(
            item.human_review_outcome != MonitoringAiHumanReviewOutcome.NOT_REVIEWED
            for item in items
        ),
        accepted_or_edited_count=sum(
            item.human_review_outcome
            in {
                MonitoringAiHumanReviewOutcome.ACCEPTED,
                MonitoringAiHumanReviewOutcome.EDITED,
            }
            for item in items
        ),
        missing_project_task_pairs=tuple(sorted(expected_pairs - observed_pairs)),
    )


def quality_observation_payload(
    observation: MonitoringAiQualityObservation,
) -> str:
    """Return deterministic JSON for a file-backed quality evidence record."""

    return canonical_json(observation.model_dump(mode="json"))
