"""Offline prompt/model release governance for medical-monitoring AI.

This module is deliberately a pure contract.  It does not change the prompt
registry, retire jobs, call a provider, or activate a release in a runtime
store.  It provides immutable snapshots and guarded transitions so a later
controlled integration can persist an auditable release decision.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from hashlib import sha256
import re
from typing import Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .monitoring_ai_contracts import (
    MonitoringAiTaskType,
    canonical_json,
    content_sha256,
)


RELEASE_SCHEMA_VERSION = "monitoring_ai_release_v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class MonitoringAiPromptReleaseStatus(str, Enum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    ACTIVE = "active"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class MonitoringAiPromptRelease(BaseModel):
    """One immutable prompt/model release snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = RELEASE_SCHEMA_VERSION
    release_id: str = Field(min_length=2, max_length=180)
    task_type: MonitoringAiTaskType
    prompt_version: str = Field(min_length=2, max_length=180)
    prompt_sha256: str
    response_model: str = Field(min_length=1, max_length=240)
    model_revision: str = Field(min_length=2, max_length=180)
    input_contract_revision: str = Field(min_length=2, max_length=180)
    evaluator_revision: str = Field(min_length=2, max_length=180)
    evaluation_observation_ids: tuple[str, ...] = ()
    evaluation_snapshot_sha256: str
    status: MonitoringAiPromptReleaseStatus = MonitoringAiPromptReleaseStatus.CANDIDATE
    supersedes_release_id: str = ""
    rollback_target_release_id: str = ""
    approved_by: str = ""
    approval_evidence_sha256: str = ""
    approved_at: Optional[datetime] = None
    created_at: datetime

    @field_validator(
        "prompt_sha256",
        "evaluation_snapshot_sha256",
        "approval_evidence_sha256",
    )
    @classmethod
    def validate_sha256(cls, value: str, info) -> str:
        if info.field_name == "approval_evidence_sha256" and value == "":
            return ""
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256")
        return value

    @field_validator("evaluation_observation_ids")
    @classmethod
    def validate_observation_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(str(value or "").strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("evaluation observation IDs cannot be empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("evaluation observation IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def validate_transition_evidence(self) -> "MonitoringAiPromptRelease":
        if self.schema_version != RELEASE_SCHEMA_VERSION:
            raise ValueError("unsupported monitoring AI release schema version")
        if not self.evaluation_observation_ids:
            raise ValueError("release requires at least one evaluation observation")
        if self.status in {
            MonitoringAiPromptReleaseStatus.APPROVED,
            MonitoringAiPromptReleaseStatus.ACTIVE,
            MonitoringAiPromptReleaseStatus.RETIRED,
            MonitoringAiPromptReleaseStatus.ROLLED_BACK,
        }:
            if not self.approved_by or not self.approved_at:
                raise ValueError(
                    "non-candidate release requires approval identity and time"
                )
            if not self.approval_evidence_sha256:
                raise ValueError("non-candidate release requires approval evidence")
        if (
            self.status == MonitoringAiPromptReleaseStatus.ACTIVE
            and self.rollback_target_release_id
        ):
            raise ValueError("active release cannot carry rollback target")
        if self.status == MonitoringAiPromptReleaseStatus.ROLLED_BACK:
            if not self.rollback_target_release_id:
                raise ValueError("rolled-back release requires rollback target")
        if self.supersedes_release_id and self.supersedes_release_id == self.release_id:
            raise ValueError("release cannot supersede itself")
        return self

    @property
    def release_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


def prompt_content_sha256(prompt_text: str) -> str:
    """Hash exact prompt content; no normalization is applied."""

    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ValueError("prompt text cannot be empty")
    return sha256(prompt_text.encode("utf-8")).hexdigest()


def _clean_ids(values: Iterable[str]) -> tuple[str, ...]:
    cleaned = tuple(str(value or "").strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError("release evidence IDs cannot be empty")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("release evidence IDs must be unique")
    return cleaned


def build_prompt_release_candidate(
    *,
    task_type: MonitoringAiTaskType,
    prompt_version: str,
    prompt_text: str,
    response_model: str,
    model_revision: str,
    input_contract_revision: str,
    evaluator_revision: str,
    evaluation_observation_ids: Iterable[str],
    evaluation_snapshot_sha256: str,
    created_at: Optional[datetime] = None,
) -> MonitoringAiPromptRelease:
    """Create an unapproved, deterministic release candidate."""

    prompt_hash = prompt_content_sha256(prompt_text)
    observation_ids = _clean_ids(evaluation_observation_ids)
    identity = {
        "task_type": task_type.value,
        "prompt_version": prompt_version,
        "prompt_sha256": prompt_hash,
        "response_model": response_model,
        "model_revision": model_revision,
        "input_contract_revision": input_contract_revision,
        "evaluator_revision": evaluator_revision,
        "evaluation_observation_ids": observation_ids,
        "evaluation_snapshot_sha256": evaluation_snapshot_sha256,
    }
    return MonitoringAiPromptRelease(
        release_id=f"mrel_{content_sha256(identity)[:28]}",
        task_type=task_type,
        prompt_version=prompt_version,
        prompt_sha256=prompt_hash,
        response_model=response_model,
        model_revision=model_revision,
        input_contract_revision=input_contract_revision,
        evaluator_revision=evaluator_revision,
        evaluation_observation_ids=observation_ids,
        evaluation_snapshot_sha256=evaluation_snapshot_sha256,
        created_at=created_at or datetime.now().astimezone(),
    )


def approve_prompt_release(
    candidate: MonitoringAiPromptRelease,
    *,
    approved_by: str,
    approval_evidence_sha256: str,
    approved_at: Optional[datetime] = None,
) -> MonitoringAiPromptRelease:
    """Return an approved snapshot; never mutate the candidate."""

    if candidate.status != MonitoringAiPromptReleaseStatus.CANDIDATE:
        raise ValueError("only a candidate release can be approved")
    payload = candidate.model_dump()
    payload.update(
        {
            "status": MonitoringAiPromptReleaseStatus.APPROVED,
            "approved_by": str(approved_by or "").strip(),
            "approval_evidence_sha256": approval_evidence_sha256,
            "approved_at": approved_at or datetime.now().astimezone(),
        }
    )
    return MonitoringAiPromptRelease.model_validate(payload)


def activate_prompt_release(
    approved: MonitoringAiPromptRelease,
    *,
    previous_active: Optional[MonitoringAiPromptRelease] = None,
) -> tuple[MonitoringAiPromptRelease, Optional[MonitoringAiPromptRelease]]:
    """Activate an approved release and return a retired previous snapshot."""

    if approved.status != MonitoringAiPromptReleaseStatus.APPROVED:
        raise ValueError("only an approved release can be activated")
    if previous_active is not None:
        if previous_active.task_type != approved.task_type:
            raise ValueError("previous active release task type differs")
        if previous_active.status != MonitoringAiPromptReleaseStatus.ACTIVE:
            raise ValueError("previous release is not active")
    active_payload = approved.model_dump()
    active_payload.update(
        {
            "status": MonitoringAiPromptReleaseStatus.ACTIVE,
            "supersedes_release_id": previous_active.release_id
            if previous_active
            else "",
        }
    )
    active = MonitoringAiPromptRelease.model_validate(active_payload)
    retired = (
        MonitoringAiPromptRelease.model_validate(
            {
                **previous_active.model_dump(),
                "status": MonitoringAiPromptReleaseStatus.RETIRED,
            }
        )
        if previous_active
        else None
    )
    return active, retired


def rollback_prompt_release(
    active: MonitoringAiPromptRelease,
    target: MonitoringAiPromptRelease,
) -> tuple[MonitoringAiPromptRelease, MonitoringAiPromptRelease]:
    """Return immutable snapshots for a guarded rollback and restored target."""

    if active.status != MonitoringAiPromptReleaseStatus.ACTIVE:
        raise ValueError("only an active release can be rolled back")
    if target.task_type != active.task_type:
        raise ValueError("rollback target task type differs")
    if target.status not in {
        MonitoringAiPromptReleaseStatus.RETIRED,
        MonitoringAiPromptReleaseStatus.APPROVED,
    }:
        raise ValueError("rollback target must be retired or approved")
    rolled_back = MonitoringAiPromptRelease.model_validate(
        {
            **active.model_dump(),
            "status": MonitoringAiPromptReleaseStatus.ROLLED_BACK,
            "rollback_target_release_id": target.release_id,
        }
    )
    restored = MonitoringAiPromptRelease.model_validate(
        {**target.model_dump(), "status": MonitoringAiPromptReleaseStatus.ACTIVE}
    )
    return rolled_back, restored


def release_snapshot_payload(release: MonitoringAiPromptRelease) -> str:
    """Return deterministic JSON for a file-backed release evidence record."""

    return canonical_json(release.model_dump(mode="json"))
