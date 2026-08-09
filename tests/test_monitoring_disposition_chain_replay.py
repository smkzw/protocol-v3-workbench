from __future__ import annotations

import pytest

from services.api.app.monitoring_disposition_chain_replay import (
    DispositionChainIssueCode,
    MonitoringDispositionChainCase,
    MonitoringDispositionChainEvent,
    MonitoringDispositionChainReplayError,
    build_monitoring_disposition_chain_replay_report,
    replay_monitoring_disposition_chain,
)


def _event(
    record_id: str,
    previous_state: str,
    new_state: str,
    created_at: str,
) -> MonitoringDispositionChainEvent:
    return MonitoringDispositionChainEvent(
        record_id=record_id,
        previous_state=previous_state,
        new_state=new_state,
        created_at=created_at,
    )


def _my009_case(
    expected: str = "submitted_for_approval",
) -> MonitoringDispositionChainCase:
    return MonitoringDispositionChainCase(
        project_id="proj_my009_uc",
        risk_instance_id="riskinst-my009-1",
        expected_aggregate_state=expected,
        events=(
            _event(
                "m1", "pending_review", "reviewed", "2026-07-10T07:34:50.086978+00:00"
            ),
            _event("m2", "reviewed", "query_draft", "2026-07-10T07:34:50.109890+00:00"),
            _event(
                "m3",
                "query_draft",
                "submitted_for_approval",
                "2026-07-10T07:34:50.127584+00:00",
            ),
        ),
    )


def test_replay_is_deterministic_and_reaches_expected_state() -> None:
    replay = replay_monitoring_disposition_chain(_my009_case())

    assert replay.replay_complete is True
    assert replay.final_state == "submitted_for_approval"
    assert replay.event_ids == ("m1", "m2", "m3")
    assert len(replay.replay_sha256) == 64


def test_replay_sorts_events_by_timestamp_not_input_order() -> None:
    case = _my009_case()
    replay = replay_monitoring_disposition_chain(
        MonitoringDispositionChainCase(
            project_id=case.project_id,
            risk_instance_id=case.risk_instance_id,
            expected_aggregate_state=case.expected_aggregate_state,
            events=tuple(reversed(case.events)),
        )
    )

    assert replay.replay_complete is True
    assert replay.event_ids == ("m1", "m2", "m3")


def test_chain_gap_is_reported_without_synthesizing_a_transition() -> None:
    case = MonitoringDispositionChainCase(
        project_id="proj-rux",
        risk_instance_id="riskinst-rux-1",
        events=(
            _event(
                "r1",
                "pending_review",
                "explained_no_external_action",
                "2026-07-29T05:58:27+00:00",
            ),
            _event("r2", "reviewed", "pending_review", "2026-07-29T06:01:54+00:00"),
        ),
    )
    replay = replay_monitoring_disposition_chain(case)

    assert replay.replay_complete is False
    assert replay.issues[0].code is DispositionChainIssueCode.CHAIN_GAP
    assert replay.final_state == "pending_review"


def test_duplicate_event_id_is_reported_even_when_payload_is_identical() -> None:
    event = _event("dup", "pending_review", "reviewed", "2026-08-01T00:00:00+00:00")
    replay = replay_monitoring_disposition_chain(
        MonitoringDispositionChainCase(
            project_id="proj-rux",
            risk_instance_id="riskinst-rux-2",
            events=(event, event),
        )
    )

    assert any(
        issue.code is DispositionChainIssueCode.DUPLICATE_EVENT
        for issue in replay.issues
    )


def test_expected_aggregate_drift_is_reported() -> None:
    replay = replay_monitoring_disposition_chain(_my009_case(expected="reviewed"))

    assert any(
        issue.code is DispositionChainIssueCode.EXPECTED_STATE_DRIFT
        for issue in replay.issues
    )


def test_b4_distinct_risk_instance_chains_replay_without_authority() -> None:
    my009 = _my009_case()
    rux = MonitoringDispositionChainCase(
        project_id="proj_rux_03_002",
        risk_instance_id="riskinst-rux-1",
        expected_aggregate_state="pending_review",
        events=(
            _event(
                "r1",
                "pending_review",
                "explained_no_external_action",
                "2026-07-29T05:58:27+00:00",
            ),
            _event(
                "r2",
                "explained_no_external_action",
                "pending_review",
                "2026-07-29T06:01:54+00:00",
            ),
        ),
    )
    report = build_monitoring_disposition_chain_replay_report((my009, rux))

    assert report.replay_complete is True
    assert report.issue_count == 0
    assert report.aggregate_write_permitted is False
    assert report.migration_ready is False


def test_report_rejects_duplicate_risk_instances_and_invalid_types() -> None:
    case = _my009_case()
    with pytest.raises(MonitoringDispositionChainReplayError, match="must not repeat"):
        build_monitoring_disposition_chain_replay_report((case, case))
    with pytest.raises(MonitoringDispositionChainReplayError, match="must contain"):
        build_monitoring_disposition_chain_replay_report(({"project_id": "x"},))


@pytest.mark.parametrize(
    "previous_state,new_state",
    [("unknown", "reviewed"), ("pending_review", "unknown")],
)
def test_noncanonical_states_fail_closed(previous_state: str, new_state: str) -> None:
    with pytest.raises(MonitoringDispositionChainReplayError, match="canonical"):
        _event("bad", previous_state, new_state, "2026-08-01T00:00:00+00:00")


def test_report_hash_is_stable() -> None:
    first = build_monitoring_disposition_chain_replay_report((_my009_case(),))
    second = build_monitoring_disposition_chain_replay_report((_my009_case(),))
    assert first.to_dict() == second.to_dict()
