"""Offline anti-overfit evidence for independent medical-monitoring AI.

The product AI must be evaluated across more than one protocol, intervention
and listing shape.  This module records those dimensions as explicit,
hash-bound evidence.  It never infers a class from a project name, calls a
provider, approves a model, or grants runtime/write authority.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .monitoring_ai_contracts import content_sha256
from .monitoring_ai_evaluation_matrix import MonitoringAiEvaluationTrack


GENERALIZATION_SCHEMA_VERSION = "monitoring_ai_generalization_v1"
GENERALIZATION_DIMENSIONS = (
    "protocol_structure",
    "drug_structure",
    "listing_structure",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_PLACEHOLDER_LABELS = frozenset(
    {"", "unknown", "unspecified", "default", "n/a", "na", "not_applicable"}
)


class MonitoringAiGeneralizationIssueCode(str, Enum):
    PROFILE_MISSING = "profile_missing"
    PROFILE_PROJECT_MISMATCH = "profile_project_mismatch"
    PROFILE_TRACK_MISMATCH = "profile_track_mismatch"
    REAL_DIMENSION_DIVERSITY_INSUFFICIENT = (
        "real_dimension_diversity_insufficient"
    )
    UNSEEN_STRUCTURE_DUPLICATE = "unseen_structure_duplicate"


def _clean_sha256(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def _clean_ids(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    cleaned = tuple(str(value or "").strip() for value in values)
    if not cleaned or any(not value for value in cleaned):
        raise ValueError(f"{field_name} cannot contain empty IDs")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{field_name} must be unique")
    return cleaned


def _clean_class(value: str, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if cleaned.lower() in _PLACEHOLDER_LABELS:
        raise ValueError(
            f"{field_name} must be an explicit evidence-backed structure class"
        )
    return cleaned


class MonitoringAiProjectStructureProfile(BaseModel):
    """One explicit structure profile for one evaluated project.

    The class labels are supplied by a reviewed classifier/evidence bundle;
    this contract intentionally does not derive them from names, indications,
    or listing column text.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=2, max_length=120)
    track: MonitoringAiEvaluationTrack
    protocol_structure_class: str = Field(min_length=2, max_length=160)
    drug_structure_class: str = Field(min_length=2, max_length=160)
    listing_structure_class: str = Field(min_length=2, max_length=160)
    profile_evidence_sha256: str
    evidence_source_ids: tuple[str, ...] = Field(default=(), max_length=40)
    classifier_revision: str = Field(min_length=2, max_length=180)

    @field_validator(
        "protocol_structure_class",
        "drug_structure_class",
        "listing_structure_class",
    )
    @classmethod
    def validate_class_label(cls, value: str, info) -> str:
        return _clean_class(value, info.field_name)

    @field_validator("profile_evidence_sha256")
    @classmethod
    def validate_profile_hash(cls, value: str) -> str:
        return _clean_sha256(value, "profile evidence hash")

    @field_validator("evidence_source_ids")
    @classmethod
    def validate_source_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_ids(value, field_name="profile evidence source IDs")

    @property
    def dimension_values(self) -> tuple[tuple[str, str], ...]:
        return (
            ("protocol_structure", self.protocol_structure_class),
            ("drug_structure", self.drug_structure_class),
            ("listing_structure", self.listing_structure_class),
        )

    @property
    def structure_fingerprint(self) -> str:
        """Fingerprint only the explicit structure classes, never project ID."""

        return content_sha256(dict(self.dimension_values))


class MonitoringAiGeneralizationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: MonitoringAiGeneralizationIssueCode
    subject: str = Field(min_length=2, max_length=180)
    detail: str = Field(min_length=2, max_length=1_000)


class MonitoringAiGeneralizationEvidence(BaseModel):
    """Immutable anti-overfit evidence; not a clinical or release decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = GENERALIZATION_SCHEMA_VERSION
    evaluator_revision: str = Field(min_length=2, max_length=180)
    observation_snapshot_sha256: str
    real_project_ids: tuple[str, ...] = Field(min_length=1)
    unseen_project_ids: tuple[str, ...] = Field(min_length=1)
    profiles: tuple[MonitoringAiProjectStructureProfile, ...] = ()
    profile_snapshot_sha256: str
    issues: tuple[MonitoringAiGeneralizationIssue, ...] = ()
    status: str = "evidence_only"

    @field_validator("observation_snapshot_sha256")
    @classmethod
    def validate_observation_hash(cls, value: str) -> str:
        return _clean_sha256(value, "observation snapshot hash")

    @field_validator("profile_snapshot_sha256")
    @classmethod
    def validate_profile_snapshot_hash(cls, value: str) -> str:
        return _clean_sha256(value, "profile snapshot hash")

    @field_validator("real_project_ids", "unseen_project_ids")
    @classmethod
    def validate_project_ids(cls, value: tuple[str, ...], info) -> tuple[str, ...]:
        return _clean_ids(value, field_name=info.field_name)

    @model_validator(mode="after")
    def validate_evidence(self) -> "MonitoringAiGeneralizationEvidence":
        if self.schema_version != GENERALIZATION_SCHEMA_VERSION:
            raise ValueError("unsupported AI generalization schema version")
        if self.status != "evidence_only":
            raise ValueError("generalization evidence cannot imply release or approval")
        if set(self.real_project_ids) & set(self.unseen_project_ids):
            raise ValueError("real and unseen project IDs must be disjoint")
        profiles = tuple(sorted(self.profiles, key=lambda item: item.project_id))
        expected_hash = content_sha256(
            [item.model_dump(mode="json") for item in profiles]
        )
        if expected_hash != self.profile_snapshot_sha256:
            raise ValueError("generalization profile snapshot hash drift")
        issue_keys = tuple(
            (item.code.value, item.subject, item.detail) for item in self.issues
        )
        if len(issue_keys) != len(set(issue_keys)):
            raise ValueError("generalization issues must be unique")
        return self

    @property
    def structurally_complete(self) -> bool:
        """Return whether the immutable fields prove the required coverage.

        The builder records auditable issues, but callers can also construct
        this frozen evidence model directly. Completeness therefore cannot
        rely on ``issues`` alone: profile rows must cover exactly the declared
        real/unseen projects, use the matching evaluation track, span at least
        two values for every real-project dimension, and keep an unseen
        structure distinct from the real-project holdout.
        """

        required_ids = set(self.real_project_ids) | set(self.unseen_project_ids)
        profile_ids = tuple(profile.project_id for profile in self.profiles)
        if len(profile_ids) != len(set(profile_ids)):
            return False
        if set(profile_ids) != required_ids:
            return False

        expected_tracks = {
            **{
                project_id: MonitoringAiEvaluationTrack.REAL_PROJECT
                for project_id in self.real_project_ids
            },
            **{
                project_id: MonitoringAiEvaluationTrack.UNSEEN_PROJECT
                for project_id in self.unseen_project_ids
            },
        }
        if any(
            expected_tracks.get(profile.project_id) is not profile.track
            for profile in self.profiles
        ):
            return False

        real_project_ids = set(self.real_project_ids)
        real_profiles = tuple(
            profile
            for profile in self.profiles
            if profile.project_id in real_project_ids
        )
        for dimension in GENERALIZATION_DIMENSIONS:
            values = {
                dict(profile.dimension_values)[dimension]
                for profile in real_profiles
            }
            if len(values) < 2:
                return False

        real_fingerprints = {
            profile.structure_fingerprint for profile in real_profiles
        }
        unseen_project_ids = set(self.unseen_project_ids)
        if any(
            profile.project_id in unseen_project_ids
            and profile.structure_fingerprint in real_fingerprints
            for profile in self.profiles
        ):
            return False
        return True

    @property
    def complete(self) -> bool:
        """Return true only when issue rows and immutable structure both pass."""

        return not self.issues and self.structurally_complete

    @property
    def real_dimension_distinct_counts(self) -> tuple[tuple[str, int], ...]:
        real_ids = set(self.real_project_ids)
        profiles = (item for item in self.profiles if item.project_id in real_ids)
        values = {dimension: set() for dimension in GENERALIZATION_DIMENSIONS}
        for profile in profiles:
            values.update(
                {
                    dimension: values[dimension] | {value}
                    for dimension, value in profile.dimension_values
                }
            )
        return tuple(
            (dimension, len(values[dimension]))
            for dimension in GENERALIZATION_DIMENSIONS
        )


def build_generalization_evidence(
    profiles: Iterable[MonitoringAiProjectStructureProfile],
    *,
    real_project_ids: Iterable[str],
    unseen_project_ids: Iterable[str],
    evaluator_revision: str,
    observation_snapshot_sha256: str,
) -> MonitoringAiGeneralizationEvidence:
    """Build deterministic anti-overfit evidence from explicit profiles.

    Missing or insufficient evidence is represented as issues so the release
    gate can fail closed with an auditable reason.  Malformed hashes, IDs or
    profile rows raise immediately instead of being normalized silently.
    """

    real_ids = _clean_ids(real_project_ids, field_name="real project IDs")
    unseen_ids = _clean_ids(unseen_project_ids, field_name="unseen project IDs")
    if set(real_ids) & set(unseen_ids):
        raise ValueError("real and unseen project IDs must be disjoint")
    revision = str(evaluator_revision or "").strip()
    if len(revision) < 2:
        raise ValueError("evaluator revision cannot be empty")
    observation_hash = _clean_sha256(
        observation_snapshot_sha256,
        "observation snapshot hash",
    )
    profile_rows = tuple(sorted(tuple(profiles), key=lambda item: item.project_id))
    project_ids = tuple(item.project_id for item in profile_rows)
    if len(project_ids) != len(set(project_ids)):
        raise ValueError("generalization profiles must have unique project IDs")

    required = set(real_ids) | set(unseen_ids)
    observed = set(project_ids)
    issues: list[MonitoringAiGeneralizationIssue] = []
    for project_id in sorted(required - observed):
        issues.append(
            MonitoringAiGeneralizationIssue(
                code=MonitoringAiGeneralizationIssueCode.PROFILE_MISSING,
                subject=project_id,
                detail="one explicit protocol/drug/listing structure profile is required",
            )
        )
    for project_id in sorted(observed - required):
        issues.append(
            MonitoringAiGeneralizationIssue(
                code=MonitoringAiGeneralizationIssueCode.PROFILE_PROJECT_MISMATCH,
                subject=project_id,
                detail="profile project is outside the matrix real/unseen project sets",
            )
        )

    for profile in profile_rows:
        expected_track = (
            MonitoringAiEvaluationTrack.REAL_PROJECT
            if profile.project_id in set(real_ids)
            else MonitoringAiEvaluationTrack.UNSEEN_PROJECT
            if profile.project_id in set(unseen_ids)
            else None
        )
        if expected_track is not None and profile.track is not expected_track:
            issues.append(
                MonitoringAiGeneralizationIssue(
                    code=MonitoringAiGeneralizationIssueCode.PROFILE_TRACK_MISMATCH,
                    subject=profile.project_id,
                    detail=(
                        f"profile track={profile.track.value} does not match "
                        f"matrix track={expected_track.value}"
                    ),
                )
            )

    real_profiles = tuple(item for item in profile_rows if item.project_id in set(real_ids))
    for dimension in GENERALIZATION_DIMENSIONS:
        values = {
            dict(profile.dimension_values)[dimension] for profile in real_profiles
        }
        if len(values) < 2:
            issues.append(
                MonitoringAiGeneralizationIssue(
                    code=MonitoringAiGeneralizationIssueCode.REAL_DIMENSION_DIVERSITY_INSUFFICIENT,
                    subject=dimension,
                    detail=(
                        "at least two explicit values are required across real "
                        f"projects; observed={len(values)}"
                    ),
                )
            )

    real_fingerprints = {
        profile.structure_fingerprint for profile in real_profiles
    }
    for profile in profile_rows:
        if profile.project_id in set(unseen_ids) and profile.structure_fingerprint in real_fingerprints:
            issues.append(
                MonitoringAiGeneralizationIssue(
                    code=MonitoringAiGeneralizationIssueCode.UNSEEN_STRUCTURE_DUPLICATE,
                    subject=profile.project_id,
                    detail=(
                        "unseen project structure fingerprint duplicates a real "
                        "project; holdout must exercise a non-duplicate structure"
                    ),
                )
            )

    profile_snapshot_sha256 = content_sha256(
        [item.model_dump(mode="json") for item in profile_rows]
    )
    return MonitoringAiGeneralizationEvidence(
        evaluator_revision=revision,
        observation_snapshot_sha256=observation_hash,
        real_project_ids=real_ids,
        unseen_project_ids=unseen_ids,
        profiles=profile_rows,
        profile_snapshot_sha256=profile_snapshot_sha256,
        issues=tuple(issues),
    )


__all__ = [
    "GENERALIZATION_DIMENSIONS",
    "GENERALIZATION_SCHEMA_VERSION",
    "MonitoringAiGeneralizationEvidence",
    "MonitoringAiGeneralizationIssue",
    "MonitoringAiGeneralizationIssueCode",
    "MonitoringAiProjectStructureProfile",
    "build_generalization_evidence",
]
