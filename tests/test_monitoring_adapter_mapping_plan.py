from __future__ import annotations

import pytest

from services.api.app.monitoring_adapter_mapping_plan import (
    REVIEW_ONLY_STATUS,
    StudyAdapterMappingObservation,
    StudyAdapterMappingPlan,
    StudyAdapterMappingPlanError,
    build_review_only_mapping_plan,
)
from services.api.app.monitoring_mapping_contract import MonitoringFieldKind


def _observation(
    mapping_id: str,
    *,
    adapter_key: str = "rux-monitoring",
    project_id: str = "proj-rux",
    domain: str = "LAB",
    source_sheet: str = "LBCHEM--实验室检查-血生化",
    source_field: str = "ALT",
    capability_id: str = "lab_ctcae_rules",
    observation_kind: str = "fixed_metric",
    evidence_locator: str = "rux_monitoring_service.py:36",
    recommended_role: str = "lab.raw_result",
) -> StudyAdapterMappingObservation:
    return StudyAdapterMappingObservation(
        mapping_id=mapping_id,
        adapter_key=adapter_key,
        project_id=project_id,
        domain=domain,
        source_sheet=source_sheet,
        source_field=source_field,
        capability_id=capability_id,
        observation_kind=observation_kind,
        evidence_locator=evidence_locator,
        recommended_role=recommended_role,
    )


def test_plan_is_review_only_sorted_and_hash_bound() -> None:
    observations = (
        _observation("rux-alt"),
        _observation(
            "rux-ae",
            domain="AE",
            source_sheet="AE--不良事件",
            source_field="AETERM",
            capability_id="ae_risk_assessment",
            recommended_role="ae.reported_term",
        ),
    )
    first = build_review_only_mapping_plan(
        adapter_key="rux-monitoring",
        project_id="proj-rux",
        trial_id="trial-rux",
        observations=observations,
    )
    second = build_review_only_mapping_plan(
        adapter_key="rux-monitoring",
        project_id="proj-rux",
        trial_id="trial-rux",
        observations=tuple(reversed(observations)),
    )

    assert [item.mapping_id for item in first.observations] == ["rux-ae", "rux-alt"]
    assert first.plan_sha256 == second.plan_sha256
    assert all(item.review_status == REVIEW_ONLY_STATUS for item in first.observations)
    assert first.to_dict()["plan_sha256"] == first.plan_sha256


def test_plan_rejects_duplicate_ids_or_surfaces() -> None:
    base = _observation("rux-alt")
    with pytest.raises(StudyAdapterMappingPlanError, match="ids must be unique"):
        StudyAdapterMappingPlan(
            adapter_key="rux-monitoring",
            project_id="proj-rux",
            trial_id="trial-rux",
            observations=(base, _observation("rux-alt", source_field="AST")),
        )

    with pytest.raises(StudyAdapterMappingPlanError, match="duplicate a source surface"):
        StudyAdapterMappingPlan(
            adapter_key="rux-monitoring",
            project_id="proj-rux",
            trial_id="trial-rux",
            observations=(base, _observation("rux-alt-2")),
        )


def test_observation_stays_review_only_and_reuses_mapping_semantics() -> None:
    with pytest.raises(StudyAdapterMappingPlanError, match="review-only"):
        StudyAdapterMappingObservation(
            **{
                **_observation("rux-alt").__dict__,
                "review_status": "approved",
            }
        )

    with pytest.raises(ValueError, match="SDTM"):
        _observation(
            "rux-sdtm",
            recommended_role="SDTM.AE.AETERM",
        )

    # The canonical non-IP role remains valid; only an actual IP role is rejected.
    assert _observation(
        "cm-safe",
        domain="CM",
        source_sheet="CM",
        source_field="MEDICATION",
        capability_id="patient_profile",
        recommended_role="cm.non_ip_medication",
    ).review_status == REVIEW_ONLY_STATUS

    with pytest.raises(ValueError, match="CM is non-investigational"):
        _observation(
            "cm-ip",
            domain="CM",
            source_sheet="CM",
            source_field="MEDICATION",
            capability_id="patient_profile",
            recommended_role="ip_administration",
        )


def test_observation_rejects_unknown_capability_and_local_paths() -> None:
    with pytest.raises(StudyAdapterMappingPlanError, match="unsupported capability"):
        _observation("bad-capability", capability_id="not-a-capability")

    with pytest.raises(StudyAdapterMappingPlanError, match="local path"):
        _observation("bad-sheet", source_sheet="/tmp/listing.xlsx")

    with pytest.raises(StudyAdapterMappingPlanError, match="local path"):
        _observation("bad-evidence", evidence_locator="../rux_monitoring_service.py:36")


def test_three_project_observation_shapes_remain_project_bound() -> None:
    rux = _observation("rux-visit", source_sheet="SV--访视日期", source_field="VISIT_DATE", capability_id="subject_timeline", recommended_role="visit.actual_date")
    my009 = _observation(
        "my009-alt",
        adapter_key="my009-monitoring",
        project_id="proj-my009",
        domain="LAB",
        source_sheet="LB2",
        source_field="ALT",
        evidence_locator="my009_monitoring_service.py:45",
    )
    mgk10 = _observation(
        "mgk10-rtnss",
        adapter_key="mgk10-monitoring",
        project_id="proj-mgk10",
        domain="EFFICACY",
        source_sheet="RES1",
        source_field="RTNSSNUM",
        capability_id="scale_recalculation",
        evidence_locator="mgk10_sar_monitoring_service.py:55",
        recommended_role="scale.source_score",
    )

    for observation, trial_id in (
        (rux, "trial-rux"),
        (my009, "trial-my009"),
        (mgk10, "trial-mgk10"),
    ):
        plan = build_review_only_mapping_plan(
            adapter_key=observation.adapter_key,
            project_id=observation.project_id,
            trial_id=trial_id,
            observations=(observation,),
        )
        assert plan.observations[0].project_id == observation.project_id


def test_field_kind_is_serialized_as_contract_value() -> None:
    observation = StudyAdapterMappingObservation(
        **{
            **_observation("rux-sheet").__dict__,
            "field_kind": MonitoringFieldKind.SOURCE_METADATA,
        }
    )
    assert observation.to_dict()["field_kind"] == "source_metadata"
