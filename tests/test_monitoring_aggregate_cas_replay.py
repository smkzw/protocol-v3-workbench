from __future__ import annotations

from dataclasses import replace

import pytest

from services.api.app.monitoring_aggregate_cas_replay import (
    AggregateCasIssueCode,
    MonitoringAggregateCasCase,
    MonitoringAggregateCasEvent,
    MonitoringAggregateCasReplayReport,
    MonitoringAggregateCasReplayError,
    build_monitoring_aggregate_cas_replay_report,
    replay_monitoring_aggregate_cas,
)


PROJECT = "proj_test"
RISK_KEY = "riskkey_1"
INSTANCE = "riskinst_1"
REVISION = "monsrcv_abc123"


def _event(
    record_id: str,
    previous: str,
    new: str,
    version: int | None,
    *,
    at: str = "2026-08-01T00:00:00+00:00",
    project: str = PROJECT,
    source_revision: str = REVISION,
    risk_key: str = RISK_KEY,
    risk_instance_id: str = INSTANCE,
) -> MonitoringAggregateCasEvent:
    return MonitoringAggregateCasEvent(
        record_id=record_id,
        project_id=project,
        risk_key=risk_key,
        risk_instance_id=risk_instance_id,
        source_revision=source_revision,
        previous_state=previous,
        new_state=new,
        created_at=at,
        expected_version=version,
    )


def _case(
    *events: MonitoringAggregateCasEvent, expected_final: str = ""
) -> MonitoringAggregateCasCase:
    return MonitoringAggregateCasCase(
        project_id=PROJECT,
        risk_key=RISK_KEY,
        risk_instance_id=INSTANCE,
        source_revision=REVISION,
        events=events,
        expected_final_state=expected_final,
    )


def test_complete_event_stream_replays_cas_versions_without_authority() -> None:
    replay = replay_monitoring_aggregate_cas(
        _case(
            _event("e1", "pending_review", "reviewed", 0),
            _event("e2", "reviewed", "query_draft", 1, at="2026-08-01T00:01:00+00:00"),
            expected_final="query_draft",
        )
    )

    assert replay.metadata_chain_complete is True
    assert replay.cas_replay_complete is True
    assert replay.final_state == "query_draft"
    assert replay.cas_version == 2
    assert replay.cas_applied_event_ids == ("e1", "e2")
    report = build_monitoring_aggregate_cas_replay_report(
        (
            _case(
                _event("e1", "pending_review", "reviewed", 0),
                _event(
                    "e2", "reviewed", "query_draft", 1, at="2026-08-01T00:01:00+00:00"
                ),
            ),
        )
    )
    assert report.cas_replay_complete is True
    assert report.aggregate_write_permitted is False
    assert report.migration_ready is False


def test_missing_expected_version_is_explicit_and_never_inferred() -> None:
    replay = replay_monitoring_aggregate_cas(
        _case(_event("e1", "pending_review", "reviewed", None))
    )

    assert replay.final_state == "reviewed"
    assert replay.cas_version == 0
    assert replay.cas_applied_event_ids == ()
    assert replay.cas_replay_complete is False
    assert any(
        issue.code is AggregateCasIssueCode.MISSING_EXPECTED_VERSION
        for issue in replay.issues
    )
    assert "inferred" in replay.issues[0].detail


def test_missing_prior_version_makes_later_sequence_unproven() -> None:
    replay = replay_monitoring_aggregate_cas(
        _case(
            _event("e1", "pending_review", "reviewed", None),
            _event("e2", "reviewed", "query_draft", 1, at="2026-08-01T00:01:00+00:00"),
        )
    )
    assert any(
        issue.code is AggregateCasIssueCode.VERSION_SEQUENCE_UNPROVEN
        for issue in replay.issues
    )
    assert replay.cas_replay_complete is False


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"project": "other"}, AggregateCasIssueCode.IDENTITY_MISMATCH),
        (
            {"source_revision": "monsrcv_other"},
            AggregateCasIssueCode.SOURCE_REVISION_MISMATCH,
        ),
        ({"previous": "reviewed"}, AggregateCasIssueCode.CHAIN_GAP),
    ],
)
def test_identity_source_and_chain_gaps_are_explicit(kwargs, code) -> None:
    base = {
        "record_id": "e1",
        "previous": "pending_review",
        "new": "reviewed",
        "version": 0,
    }
    base.update(kwargs)
    replay = replay_monitoring_aggregate_cas(_case(_event(**base)))
    assert any(issue.code is code for issue in replay.issues)
    assert replay.cas_replay_complete is False


def test_version_conflict_duplicate_and_final_drift_are_reported() -> None:
    first = _event("e1", "pending_review", "reviewed", 3)
    duplicate = _event(
        "e1", "pending_review", "query_draft", 3, at="2026-08-01T00:01:00+00:00"
    )
    drift = _event("e2", "reviewed", "query_draft", 0, at="2026-08-01T00:02:00+00:00")
    replay = replay_monitoring_aggregate_cas(
        _case(first, duplicate, drift, expected_final="submitted_for_approval")
    )
    codes = {issue.code for issue in replay.issues}
    assert AggregateCasIssueCode.DUPLICATE_EVENT in codes
    assert AggregateCasIssueCode.VERSION_CONFLICT in codes
    assert AggregateCasIssueCode.FINAL_STATE_DRIFT in codes


def test_events_are_sorted_deterministically_and_report_hash_repeats() -> None:
    late = _event("e2", "reviewed", "query_draft", 1, at="2026-08-01T00:01:00+00:00")
    early = _event("e1", "pending_review", "reviewed", 0)
    first = build_monitoring_aggregate_cas_replay_report((_case(late, early),))
    second = build_monitoring_aggregate_cas_replay_report((_case(early, late),))
    assert first.to_dict() == second.to_dict()


@pytest.mark.parametrize("value", (True, -1, 1.2, "0"))
def test_expected_version_rejects_non_integer_shapes(value) -> None:
    with pytest.raises(MonitoringAggregateCasReplayError, match="non-negative integer"):
        _event("e1", "pending_review", "reviewed", value)


def test_report_rejects_write_or_migration_authority() -> None:
    case = _case(_event("e1", "pending_review", "reviewed", 0))
    with pytest.raises(MonitoringAggregateCasReplayError, match="cannot grant"):
        MonitoringAggregateCasReplayReport(
            replays=(replay_monitoring_aggregate_cas(case),),
            aggregate_write_permitted=True,
        )


@pytest.mark.parametrize("field_name", ("aggregate_write_permitted", "migration_ready"))
def test_replay_report_rejects_coerced_authority_flags(field_name: str) -> None:
    case = _case(_event("e1", "pending_review", "reviewed", 0))
    report = build_monitoring_aggregate_cas_replay_report((case,))

    with pytest.raises(MonitoringAggregateCasReplayError, match="must be boolean"):
        replace(report, **{field_name: 0})
