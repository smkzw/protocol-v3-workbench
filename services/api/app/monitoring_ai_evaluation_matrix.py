"""Offline cross-project AI evaluation evidence matrix.

This module turns immutable product-AI quality observations into a deterministic
coverage matrix for the independent-AI release gate in §40.3.  It deliberately
does not decide clinical correctness, approve a prompt/model, call a provider,
or write a repository.  Missing, failed-only, and unreviewed cells remain
explicit so a later controlled release process cannot mistake partial coverage
for three-project validation or unseen-project anti-overfit evidence.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .monitoring_ai_contracts import (
    MonitoringAiTaskType,
    canonical_json,
    content_sha256,
)
from .monitoring_ai_quality import (
    MonitoringAiHumanReviewOutcome,
    MonitoringAiQualityObservation,
    MonitoringAiQualityOutcome,
    MonitoringAiRepairOutcome,
)


EVALUATION_MATRIX_SCHEMA_VERSION = "monitoring_ai_evaluation_matrix_v1"

# The four mandatory product-AI surfaces named by the medical-monitoring
# specification §40.3.  The generic builder remains useful for narrower
# diagnostic matrices; the release builder below always includes this set.
INDEPENDENT_AI_RELEASE_TASK_TYPES = (
    MonitoringAiTaskType.LISTING_FIELD_MAPPING,
    MonitoringAiTaskType.PROTOCOL_CLAUSE_STRUCTURING,
    MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
    MonitoringAiTaskType.RISK_QUESTION_ANSWER,
)


class MonitoringAiEvaluationTrack(str, Enum):
    REAL_PROJECT = "real_project"
    UNSEEN_PROJECT = "unseen_project"


class MonitoringAiEvaluationPair(BaseModel):
    """One project × task cell, with only evidence references and counts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=2, max_length=120)
    task_type: MonitoringAiTaskType
    track: MonitoringAiEvaluationTrack
    observation_ids: tuple[str, ...] = ()
    observation_count: StrictInt = Field(ge=0)
    completed_count: StrictInt = Field(ge=0)
    failed_count: StrictInt = Field(ge=0)
    repaired_count: StrictInt = Field(ge=0)
    reviewed_count: StrictInt = Field(ge=0)
    accepted_or_edited_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> "MonitoringAiEvaluationPair":
        if self.observation_count != len(self.observation_ids):
            raise ValueError("evaluation pair observation count must match IDs")
        if self.completed_count + self.failed_count > self.observation_count:
            raise ValueError("evaluation pair outcome counts exceed observations")
        if self.repaired_count > self.observation_count:
            raise ValueError("evaluation pair repair count exceeds observations")
        if self.reviewed_count > self.observation_count:
            raise ValueError("evaluation pair review count exceeds observations")
        if self.accepted_or_edited_count > self.reviewed_count:
            raise ValueError("accepted/edited count exceeds reviewed observations")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("evaluation pair observation IDs must be unique")
        return self

    @property
    def has_completed_evidence(self) -> bool:
        return self.completed_count > 0

    @property
    def has_human_review(self) -> bool:
        return self.reviewed_count > 0

    @property
    def failed_only(self) -> bool:
        return self.observation_count > 0 and not self.has_completed_evidence


class MonitoringAiEvaluationMatrix(BaseModel):
    """Hashable evidence matrix; never a release or medical approval decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = EVALUATION_MATRIX_SCHEMA_VERSION
    evaluator_revision: str = Field(min_length=2, max_length=180)
    real_project_ids: tuple[str, ...]
    unseen_project_ids: tuple[str, ...]
    required_task_types: tuple[MonitoringAiTaskType, ...]
    observation_ids: tuple[str, ...]
    observation_snapshot_sha256: str
    real_pairs: tuple[MonitoringAiEvaluationPair, ...]
    unseen_pairs: tuple[MonitoringAiEvaluationPair, ...]
    missing_real_pairs: tuple[tuple[str, MonitoringAiTaskType], ...] = ()
    missing_unseen_pairs: tuple[tuple[str, MonitoringAiTaskType], ...] = ()
    unreviewed_real_pairs: tuple[tuple[str, MonitoringAiTaskType], ...] = ()
    unreviewed_unseen_pairs: tuple[tuple[str, MonitoringAiTaskType], ...] = ()
    failed_only_real_pairs: tuple[tuple[str, MonitoringAiTaskType], ...] = ()
    failed_only_unseen_pairs: tuple[tuple[str, MonitoringAiTaskType], ...] = ()
    status: str = "evidence_matrix_only"

    @model_validator(mode="after")
    def validate_matrix(self) -> "MonitoringAiEvaluationMatrix":
        if self.schema_version != EVALUATION_MATRIX_SCHEMA_VERSION:
            raise ValueError(
                "unsupported monitoring AI evaluation matrix schema version"
            )
        if not self.real_project_ids or not self.unseen_project_ids:
            raise ValueError("matrix requires real and unseen project IDs")
        if set(self.real_project_ids) & set(self.unseen_project_ids):
            raise ValueError("real and unseen project IDs must be disjoint")
        if len(self.real_project_ids) != len(set(self.real_project_ids)):
            raise ValueError("real project IDs must be unique")
        if len(self.unseen_project_ids) != len(set(self.unseen_project_ids)):
            raise ValueError("unseen project IDs must be unique")
        if not self.required_task_types:
            raise ValueError("matrix requires at least one task type")
        if len(self.required_task_types) != len(set(self.required_task_types)):
            raise ValueError("required task types must be unique")
        if len(self.observation_ids) != len(set(self.observation_ids)):
            raise ValueError("matrix observation IDs must be unique")
        if len(self.observation_snapshot_sha256) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.observation_snapshot_sha256
        ):
            raise ValueError("observation snapshot must be a lowercase SHA-256")
        if self.status != "evidence_matrix_only":
            raise ValueError("matrix status cannot imply release or medical approval")
        return self

    @property
    def real_project_coverage_complete(self) -> bool:
        return not self.missing_real_pairs

    @property
    def unseen_project_coverage_complete(self) -> bool:
        return not self.missing_unseen_pairs

    @property
    def human_review_complete(self) -> bool:
        return not self.unreviewed_real_pairs and not self.unreviewed_unseen_pairs

    @property
    def no_failed_only_cells(self) -> bool:
        return not self.failed_only_real_pairs and not self.failed_only_unseen_pairs

    @property
    def structurally_complete(self) -> bool:
        """Prove that immutable matrix rows match the declared evaluation shape.

        The builder derives these rows from observations, but callers can also
        construct this frozen model directly. Completeness therefore verifies
        pair keys, track binding, observation-ID conservation, outcome
        classification and every stored coverage summary instead of trusting
        caller-supplied empty summary tuples.
        """

        expected_real = {
            (project_id, task_type)
            for project_id in self.real_project_ids
            for task_type in self.required_task_types
        }
        expected_unseen = {
            (project_id, task_type)
            for project_id in self.unseen_project_ids
            for task_type in self.required_task_types
        }
        real_keys = tuple((pair.project_id, pair.task_type) for pair in self.real_pairs)
        unseen_keys = tuple(
            (pair.project_id, pair.task_type) for pair in self.unseen_pairs
        )
        if (
            len(real_keys) != len(set(real_keys))
            or len(unseen_keys) != len(set(unseen_keys))
            or set(real_keys) != expected_real
            or set(unseen_keys) != expected_unseen
        ):
            return False
        if any(
            pair.track is not MonitoringAiEvaluationTrack.REAL_PROJECT
            for pair in self.real_pairs
        ) or any(
            pair.track is not MonitoringAiEvaluationTrack.UNSEEN_PROJECT
            for pair in self.unseen_pairs
        ):
            return False

        pairs = (*self.real_pairs, *self.unseen_pairs)
        pair_observation_ids = tuple(
            observation_id for pair in pairs for observation_id in pair.observation_ids
        )
        if (
            len(pair_observation_ids) != len(set(pair_observation_ids))
            or set(pair_observation_ids) != set(self.observation_ids)
        ):
            return False
        if any(
            pair.completed_count + pair.failed_count != pair.observation_count
            for pair in pairs
        ):
            return False

        def summary_matches(
            actual: tuple[tuple[str, MonitoringAiTaskType], ...],
            expected: set[tuple[str, MonitoringAiTaskType]],
        ) -> bool:
            return len(actual) == len(set(actual)) and set(actual) == expected

        expected_missing_real = {
            (pair.project_id, pair.task_type)
            for pair in self.real_pairs
            if not pair.observation_count
        }
        expected_missing_unseen = {
            (pair.project_id, pair.task_type)
            for pair in self.unseen_pairs
            if not pair.observation_count
        }
        expected_unreviewed_real = {
            (pair.project_id, pair.task_type)
            for pair in self.real_pairs
            if pair.observation_count and not pair.has_human_review
        }
        expected_unreviewed_unseen = {
            (pair.project_id, pair.task_type)
            for pair in self.unseen_pairs
            if pair.observation_count and not pair.has_human_review
        }
        expected_failed_only_real = {
            (pair.project_id, pair.task_type)
            for pair in self.real_pairs
            if pair.failed_only
        }
        expected_failed_only_unseen = {
            (pair.project_id, pair.task_type)
            for pair in self.unseen_pairs
            if pair.failed_only
        }
        return all(
            (
                summary_matches(self.missing_real_pairs, expected_missing_real),
                summary_matches(self.missing_unseen_pairs, expected_missing_unseen),
                summary_matches(
                    self.unreviewed_real_pairs,
                    expected_unreviewed_real,
                ),
                summary_matches(
                    self.unreviewed_unseen_pairs,
                    expected_unreviewed_unseen,
                ),
                summary_matches(
                    self.failed_only_real_pairs,
                    expected_failed_only_real,
                ),
                summary_matches(
                    self.failed_only_unseen_pairs,
                    expected_failed_only_unseen,
                ),
            )
        )

    @property
    def evidence_matrix_complete(self) -> bool:
        """Structural evidence completeness, not model or medical correctness."""

        return (
            self.structurally_complete
            and self.real_project_coverage_complete
            and self.unseen_project_coverage_complete
            and self.human_review_complete
            and self.no_failed_only_cells
        )


def _clean_ids(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    cleaned = tuple(str(value or "").strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError(f"{field_name} cannot contain empty IDs")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{field_name} must be unique")
    return cleaned


def _clean_tasks(
    values: Iterable[MonitoringAiTaskType],
) -> tuple[MonitoringAiTaskType, ...]:
    cleaned = tuple(
        value
        if isinstance(value, MonitoringAiTaskType)
        else MonitoringAiTaskType(str(value))
        for value in values
    )
    if not cleaned:
        raise ValueError("required task types cannot be empty")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError("required task types must be unique")
    return tuple(sorted(cleaned, key=lambda item: item.value))


def _pair(
    observations: tuple[MonitoringAiQualityObservation, ...],
    *,
    project_id: str,
    task_type: MonitoringAiTaskType,
    track: MonitoringAiEvaluationTrack,
) -> MonitoringAiEvaluationPair:
    items = tuple(
        sorted(
            (
                item
                for item in observations
                if item.project_id == project_id and item.task_type == task_type
            ),
            key=lambda item: item.observation_id,
        )
    )
    return MonitoringAiEvaluationPair(
        project_id=project_id,
        task_type=task_type,
        track=track,
        observation_ids=tuple(item.observation_id for item in items),
        observation_count=len(items),
        completed_count=sum(
            item.outcome is MonitoringAiQualityOutcome.COMPLETED for item in items
        ),
        failed_count=sum(
            item.outcome is MonitoringAiQualityOutcome.FAILED for item in items
        ),
        repaired_count=sum(
            item.repair_outcome is not MonitoringAiRepairOutcome.NONE for item in items
        ),
        reviewed_count=sum(
            item.human_review_outcome is not MonitoringAiHumanReviewOutcome.NOT_REVIEWED
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
    )


def build_evaluation_matrix(
    observations: Iterable[MonitoringAiQualityObservation],
    *,
    real_project_ids: Iterable[str],
    unseen_project_ids: Iterable[str],
    required_task_types: Iterable[MonitoringAiTaskType],
    evaluator_revision: str,
) -> MonitoringAiEvaluationMatrix:
    """Build a deterministic matrix from existing immutable observations.

    Unknown projects or task types fail closed instead of being silently
    ignored.  The function only returns a snapshot and never persists it.
    """

    real_ids = _clean_ids(real_project_ids, field_name="real project IDs")
    unseen_ids = _clean_ids(unseen_project_ids, field_name="unseen project IDs")
    if set(real_ids) & set(unseen_ids):
        raise ValueError("real and unseen project IDs must be disjoint")
    tasks = _clean_tasks(required_task_types)
    revision = str(evaluator_revision or "").strip()
    if len(revision) < 2:
        raise ValueError("evaluator revision cannot be empty")
    items = tuple(observations)
    observation_ids = tuple(item.observation_id for item in items)
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("matrix observations must have unique IDs")
    allowed_projects = set(real_ids) | set(unseen_ids)
    allowed_tasks = set(tasks)
    for item in items:
        if item.project_id not in allowed_projects:
            raise ValueError(
                f"observation project is outside matrix: {item.project_id}"
            )
        if item.task_type not in allowed_tasks:
            raise ValueError(
                f"observation task is outside matrix: {item.task_type.value}"
            )

    real_pairs = tuple(
        _pair(
            items,
            project_id=project_id,
            task_type=task,
            track=MonitoringAiEvaluationTrack.REAL_PROJECT,
        )
        for project_id in real_ids
        for task in tasks
    )
    unseen_pairs = tuple(
        _pair(
            items,
            project_id=project_id,
            task_type=task,
            track=MonitoringAiEvaluationTrack.UNSEEN_PROJECT,
        )
        for project_id in unseen_ids
        for task in tasks
    )

    def keys(
        pairs: tuple[MonitoringAiEvaluationPair, ...],
    ) -> tuple[tuple[str, MonitoringAiTaskType], ...]:
        return tuple((pair.project_id, pair.task_type) for pair in pairs)

    missing_real = tuple(
        key
        for key, pair in zip(keys(real_pairs), real_pairs)
        if not pair.observation_count
    )
    missing_unseen = tuple(
        key
        for key, pair in zip(keys(unseen_pairs), unseen_pairs)
        if not pair.observation_count
    )
    unreviewed_real = tuple(
        key
        for key, pair in zip(keys(real_pairs), real_pairs)
        if pair.observation_count and not pair.has_human_review
    )
    unreviewed_unseen = tuple(
        key
        for key, pair in zip(keys(unseen_pairs), unseen_pairs)
        if pair.observation_count and not pair.has_human_review
    )
    failed_only_real = tuple(
        key for key, pair in zip(keys(real_pairs), real_pairs) if pair.failed_only
    )
    failed_only_unseen = tuple(
        key for key, pair in zip(keys(unseen_pairs), unseen_pairs) if pair.failed_only
    )
    observation_snapshot_sha256 = content_sha256(
        tuple(
            {
                "observation_id": item.observation_id,
                "observation_sha256": item.observation_sha256,
                "project_id": item.project_id,
                "task_type": item.task_type.value,
            }
            for item in sorted(items, key=lambda value: value.observation_id)
        )
    )
    return MonitoringAiEvaluationMatrix(
        evaluator_revision=revision,
        real_project_ids=real_ids,
        unseen_project_ids=unseen_ids,
        required_task_types=tasks,
        observation_ids=tuple(sorted(observation_ids)),
        observation_snapshot_sha256=observation_snapshot_sha256,
        real_pairs=real_pairs,
        unseen_pairs=unseen_pairs,
        missing_real_pairs=missing_real,
        missing_unseen_pairs=missing_unseen,
        unreviewed_real_pairs=unreviewed_real,
        unreviewed_unseen_pairs=unreviewed_unseen,
        failed_only_real_pairs=failed_only_real,
        failed_only_unseen_pairs=failed_only_unseen,
    )


def build_independent_ai_release_matrix(
    observations: Iterable[MonitoringAiQualityObservation],
    *,
    real_project_ids: Iterable[str],
    unseen_project_ids: Iterable[str],
    evaluator_revision: str,
) -> MonitoringAiEvaluationMatrix:
    """Build the full §40.3 four-task matrix without narrowing its scope."""

    real_ids = tuple(real_project_ids)
    if len(real_ids) < 3:
        raise ValueError(
            "independent AI release matrix requires at least three real projects"
        )
    return build_evaluation_matrix(
        observations,
        real_project_ids=real_ids,
        unseen_project_ids=unseen_project_ids,
        required_task_types=INDEPENDENT_AI_RELEASE_TASK_TYPES,
        evaluator_revision=evaluator_revision,
    )


def evaluation_matrix_payload(matrix: MonitoringAiEvaluationMatrix) -> str:
    """Return deterministic JSON for a file-backed matrix evidence record."""

    return canonical_json(matrix.model_dump(mode="json"))
