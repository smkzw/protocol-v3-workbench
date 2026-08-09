from __future__ import annotations

import pytest

from services.api.app.monitoring_ai_contracts import content_sha256
from services.api.app.monitoring_ai_evaluation_matrix import MonitoringAiEvaluationTrack
from services.api.app.monitoring_ai_generalization import (
    MonitoringAiGeneralizationEvidence,
    MonitoringAiGeneralizationIssueCode,
    MonitoringAiProjectStructureProfile,
    build_generalization_evidence,
)


REAL = ("real-a", "real-b", "real-c")
UNSEEN = ("unseen-a",)
OBSERVATION_HASH = "a" * 64


def _profile(
    project_id: str,
    track: MonitoringAiEvaluationTrack,
    *,
    protocol: str,
    drug: str,
    listing: str,
    hash_char: str,
) -> MonitoringAiProjectStructureProfile:
    return MonitoringAiProjectStructureProfile(
        project_id=project_id,
        track=track,
        protocol_structure_class=protocol,
        drug_structure_class=drug,
        listing_structure_class=listing,
        profile_evidence_sha256=hash_char * 64,
        evidence_source_ids=(f"structure-source-{project_id}",),
        classifier_revision="structure-classifier-v1",
    )


def _complete_profiles() -> tuple[MonitoringAiProjectStructureProfile, ...]:
    return (
        _profile(
            "real-a",
            MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol="parallel_randomized",
            drug="topical_small_molecule",
            listing="wide_domain_workbook",
            hash_char="b",
        ),
        _profile(
            "real-b",
            MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol="crossover",
            drug="oral_small_molecule",
            listing="multi_sheet_domain_export",
            hash_char="c",
        ),
        _profile(
            "real-c",
            MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol="single_arm",
            drug="biologic",
            listing="longitudinal_event_extract",
            hash_char="d",
        ),
        _profile(
            "unseen-a",
            MonitoringAiEvaluationTrack.UNSEEN_PROJECT,
            protocol="adaptive_cohort",
            drug="inhaled_small_molecule",
            listing="event_wide_hybrid",
            hash_char="e",
        ),
    )


def test_generalization_evidence_is_deterministic_and_requires_explicit_diversity():
    first = build_generalization_evidence(
        reversed(_complete_profiles()),
        real_project_ids=REAL,
        unseen_project_ids=UNSEEN,
        evaluator_revision="evaluator-v1",
        observation_snapshot_sha256=OBSERVATION_HASH,
    )
    second = build_generalization_evidence(
        _complete_profiles(),
        real_project_ids=REAL,
        unseen_project_ids=UNSEEN,
        evaluator_revision="evaluator-v1",
        observation_snapshot_sha256=OBSERVATION_HASH,
    )

    assert first.complete is True
    assert first.profile_snapshot_sha256 == second.profile_snapshot_sha256
    assert first.real_dimension_distinct_counts == (
        ("protocol_structure", 3),
        ("drug_structure", 3),
        ("listing_structure", 3),
    )
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_directly_constructed_empty_profiles_are_not_complete():
    evidence = MonitoringAiGeneralizationEvidence(
        evaluator_revision="evaluator-v1",
        observation_snapshot_sha256=OBSERVATION_HASH,
        real_project_ids=REAL,
        unseen_project_ids=UNSEEN,
        profiles=(),
        profile_snapshot_sha256=content_sha256([]),
        issues=(),
    )

    assert evidence.structurally_complete is False
    assert evidence.complete is False


@pytest.mark.parametrize(
    "declared_hash",
    [
        123,
        "A" * 64,
        " " + OBSERVATION_HASH,
        OBSERVATION_HASH + " ",
        "g" * 64,
        "a" * 63,
    ],
)
def test_generalization_hashes_are_not_normalized(declared_hash: object) -> None:
    profile_kwargs = {
        "project_id": "real-a",
        "track": MonitoringAiEvaluationTrack.REAL_PROJECT,
        "protocol_structure_class": "parallel_randomized",
        "drug_structure_class": "oral_small_molecule",
        "listing_structure_class": "wide_domain_workbook",
        "profile_evidence_sha256": declared_hash,
        "evidence_source_ids": ("structure-source-real-a",),
        "classifier_revision": "structure-classifier-v1",
    }
    with pytest.raises(ValueError):
        MonitoringAiProjectStructureProfile(**profile_kwargs)

    base = build_generalization_evidence(
        _complete_profiles(),
        real_project_ids=REAL,
        unseen_project_ids=UNSEEN,
        evaluator_revision="evaluator-v1",
        observation_snapshot_sha256=OBSERVATION_HASH,
    ).model_dump(mode="python")
    for field_name in ("observation_snapshot_sha256", "profile_snapshot_sha256"):
        payload = dict(base)
        payload[field_name] = declared_hash
        with pytest.raises(ValueError):
            MonitoringAiGeneralizationEvidence(**payload)


def test_missing_profile_and_low_diversity_are_explicit_issues():
    evidence = build_generalization_evidence(
        (
            _profile(
                "real-a",
                MonitoringAiEvaluationTrack.REAL_PROJECT,
                protocol="same",
                drug="same",
                listing="same",
                hash_char="b",
            ),
        ),
        real_project_ids=REAL,
        unseen_project_ids=UNSEEN,
        evaluator_revision="evaluator-v1",
        observation_snapshot_sha256=OBSERVATION_HASH,
    )

    codes = {item.code for item in evidence.issues}
    assert evidence.complete is False
    assert MonitoringAiGeneralizationIssueCode.PROFILE_MISSING in codes
    assert (
        MonitoringAiGeneralizationIssueCode.REAL_DIMENSION_DIVERSITY_INSUFFICIENT
        in codes
    )


def test_unseen_duplicate_structure_is_blocked_even_when_labels_are_valid():
    profiles = list(_complete_profiles())
    profiles[-1] = profiles[0].model_copy(
        update={
            "project_id": "unseen-a",
            "track": MonitoringAiEvaluationTrack.UNSEEN_PROJECT,
            "profile_evidence_sha256": "f" * 64,
            "evidence_source_ids": ("structure-source-unseen-a",),
        }
    )
    evidence = build_generalization_evidence(
        profiles,
        real_project_ids=REAL,
        unseen_project_ids=UNSEEN,
        evaluator_revision="evaluator-v1",
        observation_snapshot_sha256=OBSERVATION_HASH,
    )

    assert any(
        item.code is MonitoringAiGeneralizationIssueCode.UNSEEN_STRUCTURE_DUPLICATE
        for item in evidence.issues
    )


def test_profiles_reject_placeholder_classes_and_missing_evidence():
    with pytest.raises(ValueError, match="explicit evidence-backed"):
        _profile(
            "real-a",
            MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol="unknown",
            drug="oral_small_molecule",
            listing="wide_domain_workbook",
            hash_char="b",
        )
    with pytest.raises(ValueError, match="profile evidence source IDs"):
        MonitoringAiProjectStructureProfile(
            project_id="real-a",
            track=MonitoringAiEvaluationTrack.REAL_PROJECT,
            protocol_structure_class="parallel_randomized",
            drug_structure_class="oral_small_molecule",
            listing_structure_class="wide_domain_workbook",
            profile_evidence_sha256="b" * 64,
            evidence_source_ids=(),
            classifier_revision="structure-classifier-v1",
        )


def test_duplicate_profile_ids_fail_closed_before_building_evidence():
    profiles = _complete_profiles()
    with pytest.raises(ValueError, match="unique project IDs"):
        build_generalization_evidence(
            profiles + (profiles[0],),
            real_project_ids=REAL,
            unseen_project_ids=UNSEEN,
            evaluator_revision="evaluator-v1",
            observation_snapshot_sha256=OBSERVATION_HASH,
        )
