from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from packages.contracts.workbench_contracts.models import (
    SubjectMonitoringDrilldown,
    SubjectOverview,
    SubjectTimelineEvent,
    SubjectTimelineEventType,
    SubjectTrendDirection,
    SubjectTrendDomain,
    SubjectTrendMetric,
    SubjectTrendPoint,
    SubjectVisitAnchor,
)
from services.api.app.monitoring_mapping_activation import (
    MonitoringMappingActivationNotFoundError,
    MonitoringMappingCapabilityUnavailableError,
)
from services.api.app.monitoring_project_registry import (
    BoundMonitoringProjectAdapter,
    MonitoringProjectCapabilityUnavailableError,
)


PROJECT_ID = "project-capability-test"


def _profile() -> SubjectMonitoringDrilldown:
    point = SubjectTrendPoint(
        point_id="point-1",
        visit_code="W4",
        visit_label="第4周",
        assessment_date="2026-07-01",
        study_day=29,
        value=18.0,
        original_value="18",
        standardized_value=18.0,
        baseline_value=24.0,
        change_from_baseline=-6.0,
        percent_change_from_baseline=-25.0,
        ctcae_grade=2,
        ctcae_version="5.0",
        source_domain="LB",
        source_record_id="LB-1",
        source_locator="listing:test:LB:1",
    )
    return SubjectMonitoringDrilldown(
        project_id=PROJECT_ID,
        subject_id="S001",
        source_revision="monsrcv_" + "a" * 24,
        generated_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        subject=SubjectOverview(
            project_id=PROJECT_ID,
            subject_id="S001",
            site_id="001",
            screening_number="S001",
            treatment_arm="待解盲",
            enrollment_status="在组",
            latest_visit_code="W4",
            latest_visit_label="第4周",
            latest_visit_date="2026-07-01",
        ),
        visit_anchors=[
            SubjectVisitAnchor(
                anchor_id="visit-1",
                visit_code="W4",
                visit_label="第4周",
                planned_study_day=29,
                actual_date="2026-07-01",
                actual_study_day=30,
                deviation_days=1,
            )
        ],
        timeline=[
            SubjectTimelineEvent(
                event_id="event-1",
                project_id=PROJECT_ID,
                subject_id="S001",
                event_type=SubjectTimelineEventType.LAB,
                event_date="2026-07-01",
                study_day=30,
                source_domain="LB",
                source_record_id="LB-1",
                source_locator="listing:test:LB:1",
                title="ALT升高",
                detail="ALT 85 IU/L",
            )
        ],
        efficacy_trends=[
            SubjectTrendMetric(
                metric_key="easi",
                metric_label="EASI",
                domain=SubjectTrendDomain.EFFICACY,
                direction=SubjectTrendDirection.LOWER_IS_BETTER,
                points=[point],
            )
        ],
        safety_trends=[
            SubjectTrendMetric(
                metric_key="alt",
                metric_label="ALT",
                domain=SubjectTrendDomain.SAFETY,
                direction=SubjectTrendDirection.STABLE_RANGE,
                points=[point],
            )
        ],
    )


class _Service:
    def source_revision(self):
        return "monsrcv_" + "a" * 24

    def subject_monitoring(self, project_id, subject_id):
        assert project_id == PROJECT_ID
        assert subject_id == "S001"
        return _profile()


def test_restricted_subject_view_preserves_source_values_without_unsupported_derivations():
    states = {
        "subject_timeline": "limited",
        "patient_profile": "ready",
    }

    def resolve(_project_id, capability_id):
        if capability_id in {
            "precise_temporal_rules",
            "lab_ctcae_rules",
            "scale_recalculation",
        }:
            raise MonitoringMappingCapabilityUnavailableError(
                f"{capability_id}_lineage_incomplete"
            )
        return SimpleNamespace(
            state=states[capability_id],
            limitation_codes=("source_values_only",)
            if states[capability_id] == "limited"
            else (),
        )

    binding = BoundMonitoringProjectAdapter(
        project_id=PROJECT_ID,
        service=_Service(),
        capability_resolver=resolve,
    )

    result = binding.subject_monitoring("S001")

    assert result.capability_mode == "restricted"
    assert result.timeline[0].event_date == "2026-07-01"
    assert result.timeline[0].study_day is None
    assert result.visit_anchors[0].actual_date == "2026-07-01"
    assert result.visit_anchors[0].actual_study_day is None
    efficacy = result.efficacy_trends[0].points[0]
    assert efficacy.original_value == "18"
    assert efficacy.value == 18.0
    assert efficacy.standardized_value is None
    assert efficacy.change_from_baseline is None
    safety = result.safety_trends[0].points[0]
    assert safety.value == 18.0
    assert safety.ctcae_grade is None
    assert safety.ctcae_version == ""


def test_subject_view_does_not_return_empty_success_when_both_primary_capabilities_blocked():
    def blocked(_project_id, _capability_id):
        raise MonitoringMappingCapabilityUnavailableError(
            "capability blocked by active mapping quality"
        )

    binding = BoundMonitoringProjectAdapter(
        project_id=PROJECT_ID,
        service=_Service(),
        capability_resolver=blocked,
    )

    with pytest.raises(
        MonitoringProjectCapabilityUnavailableError,
        match="不能返回空页面",
    ):
        binding.subject_monitoring("S001")


def test_subject_view_remains_available_before_first_mapping_activation():
    def not_activated(_project_id, _capability_id):
        raise MonitoringMappingActivationNotFoundError(
            "project has no active confirmed mapping"
        )

    binding = BoundMonitoringProjectAdapter(
        project_id=PROJECT_ID,
        service=_Service(),
        capability_resolver=not_activated,
    )

    result = binding.subject_monitoring("S001")

    assert result.capability_mode == "full"
    assert result.capability_states == {}
    assert result.timeline[0].study_day == 30
    assert result.safety_trends[0].points[0].ctcae_grade == 2
