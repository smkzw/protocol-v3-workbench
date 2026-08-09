"""Offline independent-AI release-gate evidence contract.

The quality observation and evaluation-matrix contracts deliberately stop short
of a release decision.  This module joins those evidence surfaces with the
remaining §40.3 conditions: citation review, failure-mode coverage, the
deterministic fallback path, and an explicit prompt/model approval.  It is a
pure, immutable report builder.  It never calls a provider, mutates a queue or
repository, activates a release, or grants runtime/write permission.
"""

from __future__ import annotations

from enum import Enum
import re
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from .monitoring_ai_contracts import canonical_json, content_sha256
from .monitoring_ai_evaluation_matrix import (
    MonitoringAiEvaluationMatrix,
    MonitoringAiEvaluationPair,
)
from .monitoring_ai_generalization import MonitoringAiGeneralizationEvidence
from .monitoring_ai_release import (
    MonitoringAiPromptRelease,
    MonitoringAiPromptReleaseStatus,
)


RELEASE_GATE_SCHEMA_VERSION = "monitoring_ai_release_gate_v1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

# These are the §40.3 failure/operational paths.  The names are intentionally
# closed so a caller cannot claim a different, easier-to-test failure mode.
REQUIRED_FAILURE_MODES = (
    "timeout",
    "rate_limit",
    "invalid_json",
    "low_confidence",
    "model_switch",
    "retry",
)

# §40.3(5): the deterministic workbench must remain usable when AI is down.
REQUIRED_FALLBACK_SURFACES = (
    "raw_data_view",
    "deterministic_rules",
    "manual_mapping",
    "medical_disposition",
    "batch_history",
)


class MonitoringAiReleaseGateStatus(str, Enum):
    BLOCKED = "blocked"
    APPROVAL_REQUIRED = "approval_required"
    READY_FOR_CONTROLLED_ACTIVATION = "ready_for_controlled_activation"


def _clean_ids(values: Iterable[str], *, field_name: str) -> tuple[str, ...]:
    cleaned = tuple(str(value or "").strip() for value in values)
    if any(not value for value in cleaned):
        raise ValueError(f"{field_name} cannot contain empty IDs")
    if len(cleaned) != len(set(cleaned)):
        raise ValueError(f"{field_name} must be unique")
    return cleaned


def _validate_sha256(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class MonitoringAiFailureModeEvidence(BaseModel):
    """One explicit test/evidence bundle for a required failure mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: str = Field(min_length=2, max_length=80)
    evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=40)
    covered: bool

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        cleaned = value.strip()
        if cleaned not in REQUIRED_FAILURE_MODES:
            raise ValueError(f"unsupported AI failure mode: {cleaned}")
        return cleaned

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_ids(value, field_name="failure mode evidence IDs")


class MonitoringAiFallbackEvidence(BaseModel):
    """Hash-bound proof that the deterministic path remains usable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=2, max_length=160)
    evidence_sha256: str
    completed_surfaces: tuple[str, ...] = Field(min_length=1, max_length=20)

    @field_validator("evidence_sha256")
    @classmethod
    def validate_evidence_hash(cls, value: str) -> str:
        return _validate_sha256(value, field_name="fallback evidence hash")

    @field_validator("completed_surfaces")
    @classmethod
    def validate_surfaces(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(str(item or "").strip() for item in value)
        if any(not item for item in cleaned):
            raise ValueError("fallback surfaces cannot contain empty values")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("fallback surfaces must be unique")
        unknown = set(cleaned) - set(REQUIRED_FALLBACK_SURFACES)
        if unknown:
            raise ValueError(f"unsupported fallback surface: {sorted(unknown)[0]}")
        return tuple(sorted(cleaned))

    @property
    def complete(self) -> bool:
        return set(self.completed_surfaces) == set(REQUIRED_FALLBACK_SURFACES)


class MonitoringAiCitationReview(BaseModel):
    """Human citation/locator review, separate from candidate adoption."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str = Field(min_length=2, max_length=160)
    evidence_sha256: str
    reviewed_count: StrictInt = Field(ge=1)
    accepted_count: StrictInt = Field(ge=0)
    edited_count: StrictInt = Field(ge=0)
    rejected_count: StrictInt = Field(ge=0)
    incorrect_locator_count: StrictInt = Field(ge=0)
    cross_project_contamination_count: StrictInt = Field(ge=0)
    unsupported_negative_count: StrictInt = Field(ge=0)

    @field_validator("evidence_sha256")
    @classmethod
    def validate_evidence_hash(cls, value: str) -> str:
        return _validate_sha256(value, field_name="citation review hash")

    @model_validator(mode="after")
    def validate_counts(self) -> "MonitoringAiCitationReview":
        if (
            self.accepted_count + self.edited_count + self.rejected_count
            != self.reviewed_count
        ):
            raise ValueError("citation review disposition counts must sum to reviewed")
        return self

    @property
    def complete(self) -> bool:
        return (
            self.rejected_count == 0
            and self.incorrect_locator_count == 0
            and self.cross_project_contamination_count == 0
            and self.unsupported_negative_count == 0
        )


class MonitoringAiReleaseGateReport(BaseModel):
    """Immutable offline gate result; all runtime/write permissions stay false."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = RELEASE_GATE_SCHEMA_VERSION
    evaluator_revision: str = Field(min_length=2, max_length=180)
    matrix_snapshot_sha256: str
    release_id: str = Field(min_length=2, max_length=180)
    task_type: str = Field(min_length=2, max_length=120)
    status: MonitoringAiReleaseGateStatus
    matrix_complete: bool
    per_cell_complete: bool
    generalization_complete: bool = False
    generalization_snapshot_sha256: str = ""
    fallback_complete: bool
    failure_modes_complete: bool
    citation_review_complete: bool
    approval_complete: bool
    blocking_reasons: tuple[str, ...] = ()
    satisfied_conditions: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    runtime_activation_permitted: bool = False
    provider_call_permitted: bool = False
    write_permitted: bool = False

    @field_validator("matrix_snapshot_sha256")
    @classmethod
    def validate_matrix_hash(cls, value: str) -> str:
        return _validate_sha256(value, field_name="matrix snapshot hash")

    @field_validator("generalization_snapshot_sha256")
    @classmethod
    def validate_generalization_hash(cls, value: str) -> str:
        if value == "":
            return ""
        return _validate_sha256(value, field_name="generalization snapshot hash")

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _clean_ids(value, field_name="release gate evidence IDs")

    @model_validator(mode="after")
    def validate_report(self) -> "MonitoringAiReleaseGateReport":
        if self.schema_version != RELEASE_GATE_SCHEMA_VERSION:
            raise ValueError("unsupported monitoring AI release-gate schema version")
        if (
            self.runtime_activation_permitted
            or self.provider_call_permitted
            or self.write_permitted
        ):
            raise ValueError(
                "offline release gate cannot grant runtime or write permission"
            )
        if (
            self.status == MonitoringAiReleaseGateStatus.BLOCKED
            and not self.blocking_reasons
        ):
            raise ValueError("blocked release gate requires blocking reasons")
        if (
            self.status != MonitoringAiReleaseGateStatus.BLOCKED
            and self.blocking_reasons
        ):
            raise ValueError("non-blocked release gate cannot carry blocking reasons")
        if not self.evidence_ids:
            raise ValueError("release gate requires evidence IDs")
        if self.generalization_complete and not self.generalization_snapshot_sha256:
            raise ValueError(
                "complete generalization evidence requires a snapshot hash"
            )
        if self.status == MonitoringAiReleaseGateStatus.APPROVAL_REQUIRED:
            if self.approval_complete:
                raise ValueError(
                    "approval-required gate cannot report approval complete"
                )
            if not all(
                (
                    self.matrix_complete,
                    self.per_cell_complete,
                    self.generalization_complete,
                    self.fallback_complete,
                    self.failure_modes_complete,
                    self.citation_review_complete,
                )
            ):
                raise ValueError(
                    "approval-required gate requires every evidence condition"
                )
        if self.status == MonitoringAiReleaseGateStatus.READY_FOR_CONTROLLED_ACTIVATION:
            if not all(
                (
                self.matrix_complete,
                self.per_cell_complete,
                self.generalization_complete,
                self.fallback_complete,
                    self.failure_modes_complete,
                    self.citation_review_complete,
                    self.approval_complete,
                )
            ):
                raise ValueError("ready gate requires every condition")
        return self

    @property
    def gate_sha256(self) -> str:
        return content_sha256(self.model_dump(mode="json"))


def _pair_reason(pair: MonitoringAiEvaluationPair) -> str | None:
    if not pair.observation_count:
        return f"missing_matrix_cell:{pair.track.value}:{pair.project_id}:{pair.task_type.value}"
    if pair.completed_count <= 0:
        return f"no_completed_evidence:{pair.track.value}:{pair.project_id}:{pair.task_type.value}"
    if pair.completed_count + pair.failed_count != pair.observation_count:
        return f"unclassified_observation:{pair.track.value}:{pair.project_id}:{pair.task_type.value}"
    if pair.reviewed_count != pair.observation_count:
        return f"not_fully_human_reviewed:{pair.track.value}:{pair.project_id}:{pair.task_type.value}"
    return None


def build_independent_ai_release_gate(
    matrix: MonitoringAiEvaluationMatrix,
    *,
    release: MonitoringAiPromptRelease,
    fallback: MonitoringAiFallbackEvidence,
    failure_modes: Iterable[MonitoringAiFailureModeEvidence],
    citation_review: MonitoringAiCitationReview,
    generalization_evidence: MonitoringAiGeneralizationEvidence | None = None,
) -> MonitoringAiReleaseGateReport:
    """Build a conservative §40.3 evidence gate without activating anything."""

    reasons: list[str] = []
    satisfied: list[str] = []
    pairs = tuple((*matrix.real_pairs, *matrix.unseen_pairs))

    matrix_complete = matrix.evidence_matrix_complete
    if matrix_complete:
        satisfied.append("matrix_declares_real_unseen_coverage")
    else:
        reasons.append("evaluation_matrix_incomplete")

    pair_reasons = tuple(reason for pair in pairs if (reason := _pair_reason(pair)))
    per_cell_complete = not pair_reasons
    if per_cell_complete:
        satisfied.append("every_matrix_cell_has_completed_and_reviewed_evidence")
    else:
        reasons.extend(pair_reasons)

    generalization_complete = False
    generalization_snapshot_sha256 = ""
    if generalization_evidence is None:
        reasons.append("generalization_profile_evidence_missing")
    else:
        generalization_snapshot_sha256 = (
            generalization_evidence.profile_snapshot_sha256
        )
        generalization_binding_reasons: list[str] = []
        if generalization_evidence.evaluator_revision != matrix.evaluator_revision:
            generalization_binding_reasons.append(
                "generalization_evaluator_revision_mismatch"
            )
        if (
            generalization_evidence.observation_snapshot_sha256
            != matrix.observation_snapshot_sha256
        ):
            generalization_binding_reasons.append(
                "generalization_observation_snapshot_mismatch"
            )
        if generalization_evidence.real_project_ids != matrix.real_project_ids:
            generalization_binding_reasons.append(
                "generalization_real_project_set_mismatch"
            )
        if generalization_evidence.unseen_project_ids != matrix.unseen_project_ids:
            generalization_binding_reasons.append(
                "generalization_unseen_project_set_mismatch"
            )
        if generalization_evidence.issues:
            generalization_binding_reasons.extend(
                f"generalization_issue:{item.code.value}:{item.subject}"
                for item in generalization_evidence.issues
            )
        if not generalization_evidence.complete:
            generalization_binding_reasons.append(
                "generalization_evidence_incomplete"
            )
        if generalization_binding_reasons:
            reasons.extend(generalization_binding_reasons)
        else:
            generalization_complete = True
            satisfied.append("protocol_drug_listing_generalization_evidence_complete")

    binding_reasons: list[str] = []
    if release.task_type not in matrix.required_task_types:
        binding_reasons.append("release_task_not_in_required_matrix")
    if release.evaluator_revision != matrix.evaluator_revision:
        binding_reasons.append("release_evaluator_revision_mismatch")
    if release.evaluation_snapshot_sha256 != matrix.observation_snapshot_sha256:
        binding_reasons.append("release_evaluation_snapshot_mismatch")
    matrix_observation_ids = set(matrix.observation_ids)
    release_observation_ids = set(release.evaluation_observation_ids)
    if not release_observation_ids <= matrix_observation_ids:
        binding_reasons.append("release_references_unknown_observation")
    task_observation_ids = {
        observation_id
        for pair in pairs
        if pair.task_type == release.task_type
        for observation_id in pair.observation_ids
    }
    if not release_observation_ids & task_observation_ids:
        binding_reasons.append("release_has_no_observation_for_task")
    if binding_reasons:
        reasons.extend(binding_reasons)
    else:
        satisfied.append("prompt_model_release_is_bound_to_evaluation_matrix")

    fallback_complete = fallback.complete
    if fallback_complete:
        satisfied.append("deterministic_fallback_surfaces_verified")
    else:
        reasons.append("deterministic_fallback_surface_coverage_incomplete")

    mode_items = tuple(failure_modes)
    mode_names = tuple(item.mode for item in mode_items)
    if len(mode_names) != len(set(mode_names)):
        reasons.append("duplicate_failure_mode_evidence")
    missing_modes = tuple(
        mode for mode in REQUIRED_FAILURE_MODES if mode not in mode_names
    )
    uncovered_modes = tuple(item.mode for item in mode_items if not item.covered)
    failure_modes_complete = (
        not missing_modes
        and not uncovered_modes
        and len(mode_names) == len(REQUIRED_FAILURE_MODES)
    )
    if failure_modes_complete:
        satisfied.append("required_failure_modes_have_explicit_evidence")
    else:
        if missing_modes:
            reasons.append(f"missing_failure_modes:{','.join(missing_modes)}")
        if uncovered_modes:
            reasons.append(f"uncovered_failure_modes:{','.join(uncovered_modes)}")

    citation_review_complete = citation_review.complete
    if citation_review_complete:
        satisfied.append("citation_locator_and_cross_project_review_passed")
    else:
        reasons.append("citation_review_has_rejections_or_traceability_findings")

    approval_complete = release.status in {
        MonitoringAiPromptReleaseStatus.APPROVED,
        MonitoringAiPromptReleaseStatus.ACTIVE,
    }
    if approval_complete:
        satisfied.append("prompt_model_release_has_explicit_approval")
    elif release.status == MonitoringAiPromptReleaseStatus.CANDIDATE:
        reasons.append("prompt_model_release_approval_required")
    else:
        reasons.append("prompt_model_release_status_not_activatable")

    evidence_ids = _clean_ids(
        (
            *release.evaluation_observation_ids,
            *(
                (f"generalization:{generalization_snapshot_sha256[:28]}",)
                if generalization_evidence is not None
                else ()
            ),
            fallback.evidence_id,
            citation_review.review_id,
            *(evidence_id for item in mode_items for evidence_id in item.evidence_ids),
        ),
        field_name="release gate evidence IDs",
    )
    status = (
        MonitoringAiReleaseGateStatus.BLOCKED
        if any(
            reason
            for reason in reasons
            if reason != "prompt_model_release_approval_required"
        )
        else (
            MonitoringAiReleaseGateStatus.APPROVAL_REQUIRED
            if not approval_complete
            else MonitoringAiReleaseGateStatus.READY_FOR_CONTROLLED_ACTIVATION
        )
    )
    # An approval cannot make an incomplete evidence bundle ready.  Conversely,
    # a complete evidence bundle remains explicitly pending until approval.
    if status == MonitoringAiReleaseGateStatus.APPROVAL_REQUIRED and reasons != [
        "prompt_model_release_approval_required"
    ]:
        status = MonitoringAiReleaseGateStatus.BLOCKED
    blocking_reasons = (
        tuple(reasons) if status == MonitoringAiReleaseGateStatus.BLOCKED else ()
    )
    return MonitoringAiReleaseGateReport(
        evaluator_revision=matrix.evaluator_revision,
        matrix_snapshot_sha256=matrix.observation_snapshot_sha256,
        release_id=release.release_id,
        task_type=release.task_type.value,
        status=status,
        matrix_complete=matrix_complete,
        per_cell_complete=per_cell_complete,
        generalization_complete=generalization_complete,
        generalization_snapshot_sha256=generalization_snapshot_sha256,
        fallback_complete=fallback_complete,
        failure_modes_complete=failure_modes_complete,
        citation_review_complete=citation_review_complete,
        approval_complete=approval_complete,
        blocking_reasons=blocking_reasons,
        satisfied_conditions=tuple(satisfied),
        evidence_ids=evidence_ids,
    )


def release_gate_payload(report: MonitoringAiReleaseGateReport) -> str:
    """Return deterministic JSON for a file-backed offline gate record."""

    return canonical_json(report.model_dump(mode="json"))
