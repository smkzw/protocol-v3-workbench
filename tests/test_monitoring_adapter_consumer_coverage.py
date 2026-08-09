from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from services.api.app.monitoring_adapter_consumer_coverage import (
    ConsumerCoverageSurface,
    StudyAdapterConsumerCoverage,
    StudyAdapterConsumerCoverageError,
    StudyAdapterConsumerCoveragePlan,
    build_consumer_coverage_plan,
)
from services.api.app.monitoring_adapter_mapping_plan import (
    REVIEW_ONLY_STATUS,
    StudyAdapterMappingObservation,
    build_review_only_mapping_plan,
)


def _observation(mapping_id: str, domain: str, capability: str, field: str) -> StudyAdapterMappingObservation:
    return StudyAdapterMappingObservation(
        mapping_id=mapping_id,
        adapter_key="rux-monitoring",
        project_id="proj-rux",
        domain=domain,
        source_sheet=f"{domain} sheet",
        source_field=field,
        capability_id=capability,
        observation_kind="fixed_sheet",
        evidence_locator=f"rux_monitoring_service.py:{mapping_id}",
        recommended_role=f"{domain.lower()}.{field.lower()}",
    )


def test_coverage_plan_maps_explicit_domains_to_consumer_surfaces() -> None:
    mapping_plan = build_review_only_mapping_plan(
        adapter_key="rux-monitoring",
        project_id="proj-rux",
        trial_id="RUX-03-002",
        observations=(
            _observation("rux-ae", "AE", "ae_risk_assessment", "AETERM"),
            _observation("rux-lab", "LAB", "lab_ctcae_rules", "ALT"),
            _observation("rux-eff", "EFFICACY", "scale_recalculation", "SCORE"),
        ),
    )

    coverage = build_consumer_coverage_plan(mapping_plan)

    assert coverage.activation_allowed is False
    assert coverage.mapping_plan_sha256 == mapping_plan.plan_sha256
    assert [item.mapping_id for item in coverage.observations] == [
        "rux-ae",
        "rux-eff",
        "rux-lab",
    ]
    ae = coverage.observations[0]
    assert ae.domain.value == "ae"
    assert ae.consumer_surfaces == (
        ConsumerCoverageSurface.TIMELINE,
        ConsumerCoverageSurface.PROFILE,
        ConsumerCoverageSurface.SAFETY_METRIC,
        ConsumerCoverageSurface.RISK_LINK,
    )
    assert ae.risk_link_policy == "explicit_risk_instance_id_only"
    assert ae.review_status == REVIEW_ONLY_STATUS
    efficacy = coverage.observations[1]
    assert efficacy.consumer_surfaces == (
        ConsumerCoverageSurface.TIMELINE,
        ConsumerCoverageSurface.PROFILE,
        ConsumerCoverageSurface.RISK_LINK,
    )
    assert "normalized_value_if_present" in efficacy.required_observation_fields
    assert coverage.to_dict()["coverage_sha256"] == coverage.coverage_sha256


def test_coverage_rejects_activation_and_surface_overclaim() -> None:
    mapping_plan = build_review_only_mapping_plan(
        adapter_key="rux-monitoring",
        project_id="proj-rux",
        trial_id="RUX-03-002",
        observations=(_observation("rux-ae", "AE", "ae_risk_assessment", "AETERM"),),
    )
    coverage = build_consumer_coverage_plan(mapping_plan)
    with pytest.raises(StudyAdapterConsumerCoverageError, match="cannot activate"):
        StudyAdapterConsumerCoveragePlan(
            adapter_key=coverage.adapter_key,
            project_id=coverage.project_id,
            trial_id=coverage.trial_id,
            inventory_revision="adapter-mapping-inventory-v1",
            mapping_plan_sha256=coverage.mapping_plan_sha256,
            observations=coverage.observations,
            activation_allowed=True,
        )

    with pytest.raises(StudyAdapterConsumerCoverageError, match="non-safety domain"):
        StudyAdapterConsumerCoverage(
            mapping_id="eff",
            adapter_key="rux-monitoring",
            project_id="proj-rux",
            trial_id="RUX-03-002",
            domain="efficacy",
            source_sheet="EFFICACY",
            source_field="SCORE",
            capability_id="scale_recalculation",
            observation_kind="fixed_sheet",
            evidence_locator="fixture:coverage:eff",
            recommended_role="scale.source_score",
            consumer_surfaces=(
                ConsumerCoverageSurface.TIMELINE,
                ConsumerCoverageSurface.PROFILE,
                ConsumerCoverageSurface.SAFETY_METRIC,
                ConsumerCoverageSurface.RISK_LINK,
            ),
        )


def test_coverage_rejects_non_review_only_input() -> None:
    observation = _observation("rux-ae", "AE", "ae_risk_assessment", "AETERM")
    with pytest.raises(ValueError, match="review-only"):
        build_consumer_coverage_plan(
            build_review_only_mapping_plan(
                adapter_key="rux-monitoring",
                project_id="proj-rux",
                trial_id="RUX-03-002",
                observations=(replace(observation, review_status="active"),),
            )
        )


def test_actual_c3_inventory_has_46_review_only_coverage_observations() -> None:
    inventory_path = Path(
        "runs/execution/medical_monitoring_phase_c3_mapping_inventory_20260802/"
        "OBSERVED_ADAPTER_MAPPING_INVENTORY.json"
    )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    plans = []
    for payload in inventory["plans"]:
        observations = tuple(
            StudyAdapterMappingObservation(**item)
            for item in payload["observations"]
        )
        mapping_plan = build_review_only_mapping_plan(
            adapter_key=payload["adapter_key"],
            project_id=payload["project_id"],
            trial_id=payload["trial_id"],
            observations=observations,
        )
        assert mapping_plan.plan_sha256 == payload["plan_sha256"]
        plans.append(build_consumer_coverage_plan(mapping_plan))

    assert [len(plan.observations) for plan in plans] == [11, 18, 17]
    assert sum(len(plan.observations) for plan in plans) == 46
    assert all(not plan.activation_allowed for plan in plans)
    assert all(item.review_status == REVIEW_ONLY_STATUS for plan in plans for item in plan.observations)
