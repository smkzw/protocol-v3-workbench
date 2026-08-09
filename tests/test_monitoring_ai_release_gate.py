from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from services.api.app.monitoring_ai_contracts import (
    MonitoringAiTaskType,
    content_sha256,
)
from services.api.app.monitoring_ai_evaluation_matrix import (
    INDEPENDENT_AI_RELEASE_TASK_TYPES,
    MonitoringAiEvaluationTrack,
    MonitoringAiEvaluationMatrix,
    build_independent_ai_release_matrix,
)
from services.api.app.monitoring_ai_generalization import (
    MonitoringAiGeneralizationEvidence,
    MonitoringAiProjectStructureProfile,
    build_generalization_evidence,
)
from services.api.app.monitoring_ai_release import (
    MonitoringAiPromptReleaseStatus,
    approve_prompt_release,
    build_prompt_release_candidate,
    activate_prompt_release,
)
from services.api.app.monitoring_ai_release_gate import (
    REQUIRED_FAILURE_MODES,
    REQUIRED_FALLBACK_SURFACES,
    MonitoringAiCitationReview,
    MonitoringAiFailureModeEvidence,
    MonitoringAiFallbackEvidence,
    MonitoringAiReleaseGateReport,
    MonitoringAiReleaseGateStatus,
    build_independent_ai_release_gate,
    release_gate_payload,
)
from tests.test_monitoring_ai_evaluation_matrix import _observation


NOW = datetime(2026, 8, 2, 5, 0, tzinfo=timezone.utc)
REAL_PROJECTS = ("proj_rux", "proj_mgk10", "proj_my009")
UNSEEN_PROJECTS = ("proj_unseen",)
EVALUATOR_REVISION = "evaluator-v1"
APPROVAL_HASH = content_sha256({"review": "medical-engineering", "revision": "v1"})


def _matrix(*, reviewed: bool = True):
    observations = [
        _observation(project, task, reviewed=reviewed, attempt_suffix=f"{index}")
        for index, project in enumerate((*REAL_PROJECTS, *UNSEEN_PROJECTS), 1)
        for task in INDEPENDENT_AI_RELEASE_TASK_TYPES
    ]
    return build_independent_ai_release_matrix(
        observations,
        real_project_ids=REAL_PROJECTS,
        unseen_project_ids=UNSEEN_PROJECTS,
        evaluator_revision=EVALUATOR_REVISION,
    )


def _release(matrix, *, approved: bool = True):
    task = MonitoringAiTaskType.LISTING_FIELD_MAPPING
    candidate = build_prompt_release_candidate(
        task_type=task,
        prompt_version="mapping-v1",
        prompt_text="exact mapping prompt",
        response_model="mapping-model",
        model_revision="model-v1",
        input_contract_revision="input-v1",
        evaluator_revision=matrix.evaluator_revision,
        evaluation_observation_ids=matrix.observation_ids,
        evaluation_snapshot_sha256=matrix.observation_snapshot_sha256,
        created_at=NOW,
    )
    if not approved:
        return candidate
    return approve_prompt_release(
        candidate,
        approved_by="medical_reviewer",
        approval_evidence_sha256=APPROVAL_HASH,
        approved_at=NOW,
    )


def _fallback(*surfaces: str):
    return MonitoringAiFallbackEvidence(
        evidence_id="fallback-evidence-v1",
        evidence_sha256="f" * 64,
        completed_surfaces=surfaces or REQUIRED_FALLBACK_SURFACES,
    )


def _generalization(matrix):
    profiles = (
        MonitoringAiProjectStructureProfile(
            project_id=REAL_PROJECTS[0],
            track=MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol_structure_class="parallel_randomized",
            drug_structure_class="topical_small_molecule",
            listing_structure_class="wide_domain_workbook",
            profile_evidence_sha256="b" * 64,
            evidence_source_ids=("structure-source-rux",),
            classifier_revision="structure-classifier-v1",
        ),
        MonitoringAiProjectStructureProfile(
            project_id=REAL_PROJECTS[1],
            track=MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol_structure_class="single_arm",
            drug_structure_class="oral_small_molecule",
            listing_structure_class="multi_sheet_domain_export",
            profile_evidence_sha256="c" * 64,
            evidence_source_ids=("structure-source-mg",),
            classifier_revision="structure-classifier-v1",
        ),
        MonitoringAiProjectStructureProfile(
            project_id=REAL_PROJECTS[2],
            track=MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol_structure_class="crossover",
            drug_structure_class="biologic",
            listing_structure_class="longitudinal_event_extract",
            profile_evidence_sha256="d" * 64,
            evidence_source_ids=("structure-source-my009",),
            classifier_revision="structure-classifier-v1",
        ),
        MonitoringAiProjectStructureProfile(
            project_id=UNSEEN_PROJECTS[0],
            track=MonitoringAiEvaluationTrack.UNSEEN_PROJECT,
            protocol_structure_class="adaptive_cohort",
            drug_structure_class="inhaled_small_molecule",
            listing_structure_class="event_wide_hybrid",
            profile_evidence_sha256="e" * 64,
            evidence_source_ids=("structure-source-unseen",),
            classifier_revision="structure-classifier-v1",
        ),
    )
    return build_generalization_evidence(
        profiles,
        real_project_ids=matrix.real_project_ids,
        unseen_project_ids=matrix.unseen_project_ids,
        evaluator_revision=matrix.evaluator_revision,
        observation_snapshot_sha256=matrix.observation_snapshot_sha256,
    )


def _failure_modes(*, uncovered: str | None = None):
    return tuple(
        MonitoringAiFailureModeEvidence(
            mode=mode,
            evidence_ids=(f"failure-{mode}",),
            covered=mode != uncovered,
        )
        for mode in REQUIRED_FAILURE_MODES
    )


def _citation_review(**overrides):
    values = {
        "review_id": "citation-review-v1",
        "evidence_sha256": "e" * 64,
        "reviewed_count": 4,
        "accepted_count": 3,
        "edited_count": 1,
        "rejected_count": 0,
        "incorrect_locator_count": 0,
        "cross_project_contamination_count": 0,
        "unsupported_negative_count": 0,
    }
    values.update(overrides)
    return MonitoringAiCitationReview(**values)


def _gate(matrix, *, release=None, fallback=None, failure_modes=None, citation=None):
    return build_independent_ai_release_gate(
        matrix,
        release=release or _release(matrix),
        fallback=fallback or _fallback(),
        failure_modes=failure_modes or _failure_modes(),
        citation_review=citation or _citation_review(),
        generalization_evidence=_generalization(matrix),
    )


@pytest.mark.parametrize(
    "field_name",
    (
        "reviewed_count",
        "accepted_count",
        "edited_count",
        "rejected_count",
        "incorrect_locator_count",
        "cross_project_contamination_count",
        "unsupported_negative_count",
    ),
)
def test_citation_review_rejects_boolean_counts(field_name: str) -> None:
    values = {
        "reviewed_count": 4,
        "accepted_count": 3,
        "edited_count": 1,
        "rejected_count": 0,
        "incorrect_locator_count": 0,
        "cross_project_contamination_count": 0,
        "unsupported_negative_count": 0,
    }
    values[field_name] = True
    with pytest.raises(ValidationError):
        MonitoringAiCitationReview(
            review_id="citation-review-v1",
            evidence_sha256="e" * 64,
            **values,
        )


def test_release_gate_digest_fields_reject_normalization():
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        MonitoringAiFallbackEvidence(
            evidence_id="fallback-evidence-v1",
            evidence_sha256="A" * 64,
            completed_surfaces=REQUIRED_FALLBACK_SURFACES,
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        MonitoringAiCitationReview(
            review_id="citation-review-v1",
            evidence_sha256=" " + ("e" * 64),
            reviewed_count=1,
            accepted_count=1,
            edited_count=0,
            rejected_count=0,
            incorrect_locator_count=0,
            cross_project_contamination_count=0,
            unsupported_negative_count=0,
        )

    report = _gate(_matrix())
    for field_name, declared_hash in (
        ("matrix_snapshot_sha256", "A" * 64),
        ("generalization_snapshot_sha256", " " + report.generalization_snapshot_sha256),
    ):
        with pytest.raises(ValueError, match="lowercase SHA-256"):
            MonitoringAiReleaseGateReport.model_validate(
                {**report.model_dump(), field_name: declared_hash}
            )


def test_complete_evidence_and_approved_release_only_becomes_controlled_ready():
    report = _gate(_matrix())
    assert (
        report.status is MonitoringAiReleaseGateStatus.READY_FOR_CONTROLLED_ACTIVATION
    )
    assert report.gate_sha256 == report.gate_sha256
    assert report.runtime_activation_permitted is False
    assert report.provider_call_permitted is False
    assert report.write_permitted is False
    assert release_gate_payload(report) == release_gate_payload(report)


def test_directly_constructed_empty_matrix_blocks_release_gate():
    matrix = MonitoringAiEvaluationMatrix(
        evaluator_revision=EVALUATOR_REVISION,
        real_project_ids=REAL_PROJECTS,
        unseen_project_ids=UNSEEN_PROJECTS,
        required_task_types=INDEPENDENT_AI_RELEASE_TASK_TYPES,
        observation_ids=("orphan-observation",),
        observation_snapshot_sha256="a" * 64,
        real_pairs=(),
        unseen_pairs=(),
    )

    report = _gate(matrix)

    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert report.matrix_complete is False
    assert "evaluation_matrix_incomplete" in report.blocking_reasons


def test_direct_ready_report_requires_evidence_anchors_and_consistent_approval_state():
    with pytest.raises(ValueError, match="requires evidence IDs"):
        MonitoringAiReleaseGateReport(
            evaluator_revision=EVALUATOR_REVISION,
            matrix_snapshot_sha256="a" * 64,
            release_id="release-v1",
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING.value,
            status=MonitoringAiReleaseGateStatus.READY_FOR_CONTROLLED_ACTIVATION,
            matrix_complete=True,
            per_cell_complete=True,
            generalization_complete=True,
            generalization_snapshot_sha256="",
            fallback_complete=True,
            failure_modes_complete=True,
            citation_review_complete=True,
            approval_complete=True,
            evidence_ids=(),
        )

    with pytest.raises(ValueError, match="every evidence condition"):
        MonitoringAiReleaseGateReport(
            evaluator_revision=EVALUATOR_REVISION,
            matrix_snapshot_sha256="a" * 64,
            release_id="release-v1",
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING.value,
            status=MonitoringAiReleaseGateStatus.APPROVAL_REQUIRED,
            matrix_complete=False,
            per_cell_complete=True,
            generalization_complete=True,
            generalization_snapshot_sha256="b" * 64,
            fallback_complete=True,
            failure_modes_complete=True,
            citation_review_complete=True,
            approval_complete=False,
            evidence_ids=("evidence-v1",),
        )


def test_candidate_release_stays_approval_required_without_runtime_permission():
    matrix = _matrix()
    report = _gate(matrix, release=_release(matrix, approved=False))
    assert report.status is MonitoringAiReleaseGateStatus.APPROVAL_REQUIRED
    assert report.approval_complete is False
    assert report.blocking_reasons == ()
    assert report.runtime_activation_permitted is False


def test_each_matrix_cell_requires_completed_and_per_observation_review():
    matrix = _matrix(reviewed=False)
    report = _gate(matrix)
    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert report.matrix_complete is False
    assert report.per_cell_complete is False
    assert any(
        reason.startswith("not_fully_human_reviewed")
        for reason in report.blocking_reasons
    )


def test_fallback_failure_modes_and_citation_findings_block_gate():
    matrix = _matrix()
    report = _gate(
        matrix,
        fallback=_fallback("raw_data_view"),
        failure_modes=_failure_modes(uncovered="timeout"),
        citation=_citation_review(cross_project_contamination_count=1),
    )
    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert report.fallback_complete is False
    assert report.failure_modes_complete is False
    assert report.citation_review_complete is False
    assert (
        "deterministic_fallback_surface_coverage_incomplete" in report.blocking_reasons
    )
    assert "uncovered_failure_modes:timeout" in report.blocking_reasons
    assert (
        "citation_review_has_rejections_or_traceability_findings"
        in report.blocking_reasons
    )


def test_release_binding_must_match_matrix_snapshot_and_task_observations():
    matrix = _matrix()
    release = _release(matrix).model_copy(
        update={"evaluation_snapshot_sha256": "a" * 64}
    )
    report = _gate(matrix, release=release)
    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert "release_evaluation_snapshot_mismatch" in report.blocking_reasons


def test_missing_generalization_evidence_blocks_even_complete_matrix():
    matrix = _matrix()
    report = build_independent_ai_release_gate(
        matrix,
        release=_release(matrix),
        fallback=_fallback(),
        failure_modes=_failure_modes(),
        citation_review=_citation_review(),
    )

    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert report.generalization_complete is False
    assert "generalization_profile_evidence_missing" in report.blocking_reasons


def test_incomplete_direct_generalization_evidence_cannot_satisfy_gate():
    matrix = _matrix()
    evidence = MonitoringAiGeneralizationEvidence(
        evaluator_revision=matrix.evaluator_revision,
        observation_snapshot_sha256=matrix.observation_snapshot_sha256,
        real_project_ids=matrix.real_project_ids,
        unseen_project_ids=matrix.unseen_project_ids,
        profiles=(),
        profile_snapshot_sha256=content_sha256([]),
        issues=(),
    )
    report = build_independent_ai_release_gate(
        matrix,
        release=_release(matrix),
        fallback=_fallback(),
        failure_modes=_failure_modes(),
        citation_review=_citation_review(),
        generalization_evidence=evidence,
    )

    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert report.generalization_complete is False
    assert "generalization_evidence_incomplete" in report.blocking_reasons


def test_generalization_revision_mismatch_blocks_gate():
    matrix = _matrix()
    evidence = _generalization(matrix).model_copy(
        update={"evaluator_revision": "evaluator-v2"}
    )
    report = build_independent_ai_release_gate(
        matrix,
        release=_release(matrix),
        fallback=_fallback(),
        failure_modes=_failure_modes(),
        citation_review=_citation_review(),
        generalization_evidence=evidence,
    )

    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert "generalization_evaluator_revision_mismatch" in report.blocking_reasons


def test_duplicate_failure_mode_rows_fail_closed():
    matrix = _matrix()
    duplicate = _failure_modes() + (
        MonitoringAiFailureModeEvidence(
            mode="timeout",
            evidence_ids=("failure-timeout-duplicate",),
            covered=True,
        ),
    )
    report = _gate(matrix, failure_modes=duplicate)
    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert "duplicate_failure_mode_evidence" in report.blocking_reasons


def test_evidence_models_reject_unknown_surface_or_inconsistent_review_counts():
    with pytest.raises(ValueError, match="unsupported fallback surface"):
        _fallback("unknown_surface")
    with pytest.raises(ValueError, match="disposition counts"):
        _citation_review(accepted_count=4)


def test_retired_release_is_not_treated_as_approval():
    matrix = _matrix()
    active, _ = activate_prompt_release(_release(matrix))
    report = _gate(
        matrix,
        release=active.model_copy(
            update={"status": MonitoringAiPromptReleaseStatus.RETIRED}
        ),
    )
    assert report.status is MonitoringAiReleaseGateStatus.BLOCKED
    assert "prompt_model_release_status_not_activatable" in report.blocking_reasons
