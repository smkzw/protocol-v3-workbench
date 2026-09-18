"""Actual adoption/query behavior; synthetic projects and isolated storage."""

import sqlite3

import pytest

from app.protocol_workflow.errors import ProtocolWorkflowError
from test_application_service import _SharedState, _service, _create_command
from test_mounted_api_integration import (
    PROJECT, SD_ID, _admitted_client, _apply_body,
)


def test_absent_study_is_not_a_retryable_recommendation_conflict(tmp_path, monkeypatch):
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        response = client.post(
            f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/{SD_ID}/decisions",
            json=_apply_body(snapshot_sha256="b" * 64, idempotency_key="idem:missing:study"),
        )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["can_retry"] is False
    assert "未找到" in detail["message"]
    assert "重新确认" not in detail["next_step"]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM aggregate_revision").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM event_stream").fetchone()[0] == 0


def test_missing_repository_is_configuration_failure_not_user_decision():
    state = _SharedState()
    state.sd_repo = None
    service = _service(state)
    with pytest.raises(ProtocolWorkflowError) as caught:
        service.create_study_definition(_create_command())
    error = caught.value
    assert error.code.value == "MW-PRO-P1-SERVICE-CONFIGURATION_INCOMPLETE"
    assert error.retryable is False
    assert "重新确认" not in error.to_public_payload()["next_step"]


def test_decision_graph_shows_applied_history_without_claiming_current_validity(tmp_path, monkeypatch):
    from test_mounted_api_integration import _create_body
    client, database = _admitted_client(tmp_path, monkeypatch)
    base = f"/api/projects/{PROJECT}/protocol-workflow/study-definitions"
    with client:
        created = client.post(base, json=_create_body())
        assert created.status_code == 200
        applied = client.post(
            f"{base}/{SD_ID}/decisions",
            json=_apply_body(snapshot_sha256=created.json()["revision_sha256"], idempotency_key="idem:graph:history"),
        )
        assert applied.status_code == 200
        with sqlite3.connect(database) as connection:
            before = connection.iterdump()
            before = tuple(before)
        graph = client.get(f"{base}/{SD_ID}/decision-graph")
        assert graph.status_code == 200
        records = graph.json()["records"]
        assert {row["decision_key"] for row in records} == {"decision:create", "decision:dose"}
        assert all(row["current_validity"] == "unverified" for row in records)
        assert all(row["decision_record_id"] for row in records)
        with sqlite3.connect(database) as connection:
            assert tuple(connection.iterdump()) == before


def test_explicit_confirmed_fact_revision_and_historical_replay_keep_successor(tmp_path, monkeypatch):
    from test_mounted_api_integration import _create_body
    client, database = _admitted_client(tmp_path, monkeypatch)
    base = f"/api/projects/{PROJECT}/protocol-workflow/study-definitions"
    with client:
        created = client.post(base, json=_create_body())
        assert created.status_code == 200
        first = _apply_body(
            snapshot_sha256=created.json()["revision_sha256"],
            idempotency_key="idem:revision:first",
            fact_updates={"picos.intervention.dose": "20 mg 每日一次"},
        )
        first["revise_confirmed_facts"] = True
        revised = client.post(f"{base}/{SD_ID}/decisions", json=first)
        assert revised.status_code == 200
        second = _apply_body(
            snapshot_sha256=revised.json()["revision_sha256"],
            expected_revision=2,
            idempotency_key="idem:revision:second",
            decision_record_id="decision:revision:second",
            fact_updates={"picos.intervention.dose": "30 mg 每日一次"},
        )
        second["revise_confirmed_facts"] = True
        successor = client.post(f"{base}/{SD_ID}/decisions", json=second)
        assert successor.status_code == 200
        with sqlite3.connect(database) as connection:
            before = tuple(connection.iterdump())
        replay = client.post(f"{base}/{SD_ID}/decisions", json=first)
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert replay.json()["revision"] == 3
        assert replay.json()["revision_sha256"] == successor.json()["revision_sha256"]
        with sqlite3.connect(database) as connection:
            assert tuple(connection.iterdump()) == before


def test_current_decisions_track_their_bound_inputs_not_the_whole_revision(tmp_path, monkeypatch):
    from test_mounted_api_integration import _create_body
    client, database = _admitted_client(tmp_path, monkeypatch)
    base = f"/api/projects/{PROJECT}/protocol-workflow/study-definitions"
    with client:
        created = client.post(base, json=_create_body())
        assert created.status_code == 200
        first = _apply_body(snapshot_sha256=created.json()["revision_sha256"],
                            idempotency_key="idem:inputs:dose", fact_updates={"picos.intervention.dose": "20 mg"})
        first["revise_confirmed_facts"] = True
        first["decision_input_refs"] = [{"fact_path": "picos.intervention.dose"}]
        adopted = client.post(f"{base}/{SD_ID}/decisions", json=first)
        assert adopted.status_code == 200
        graph = client.get(f"{base}/{SD_ID}/decision-graph").json()
        assert next(r for r in graph["records"] if r["decision_key"] == "decision:dose")["current_validity"] == "current"
        unrelated = _apply_body(snapshot_sha256=adopted.json()["revision_sha256"], expected_revision=2,
                                idempotency_key="idem:inputs:age", decision_record_id="decision:inputs:age",
                                fact_updates={"picos.population.age": "成人"})
        unrelated["decision_record"]["decision_key"] = "decision:age"
        unrelated["decision_input_refs"] = [{"fact_path": "picos.population.indication"}]
        added = client.post(f"{base}/{SD_ID}/decisions", json=unrelated)
        assert added.status_code == 200
        graph = client.get(f"{base}/{SD_ID}/decision-graph").json()
        assert next(r for r in graph["records"] if r["decision_key"] == "decision:dose")["current_validity"] == "current"
        changed = _apply_body(snapshot_sha256=added.json()["revision_sha256"], expected_revision=3,
                              idempotency_key="idem:inputs:revise", decision_record_id="decision:inputs:revise",
                              fact_updates={"picos.intervention.dose": "30 mg"})
        changed["decision_record"]["decision_key"] = "decision:dose_revision"
        changed["decision_input_refs"] = [{"fact_path": "picos.intervention.dose"}]
        changed["revise_confirmed_facts"] = True
        newer = client.post(f"{base}/{SD_ID}/decisions", json=changed)
        assert newer.status_code == 200
        with sqlite3.connect(database) as connection:
            before = tuple(connection.iterdump())
        replay = client.post(f"{base}/{SD_ID}/decisions", json=first)
        assert replay.status_code == 200 and replay.json()["replayed"] is True
        assert replay.json()["revision"] == 4
        altered = dict(first)
        altered["decision_input_refs"] = [{"fact_path": "picos.population.indication"}]
        assert client.post(f"{base}/{SD_ID}/decisions", json=altered).status_code == 409
        rows = {r["decision_key"]: r for r in client.get(f"{base}/{SD_ID}/decision-graph").json()["records"]}
        assert rows["decision:dose"]["current_validity"] == "stale"
        assert rows["decision:age"]["current_validity"] == "current"
        assert rows["decision:dose_revision"]["current_validity"] == "current"
        assert rows["decision:create"]["current_validity"] == "unverified"
        queue = client.get(
            f"/api/projects/{PROJECT}/protocol-workflow/workflow-runs/run:inputs/decision-requests",
            params={"study_definition_id": SD_ID},
        )
        assert queue.status_code == 200
        assert {r["decision_key"] for r in queue.json()["requests"]} == {"decision:dose"}
        assert queue.json()["requests"][0]["current_validity"] == "stale"
        with sqlite3.connect(database) as connection:
            assert tuple(connection.iterdump()) == before

    # Reopen through a fresh storage factory and rebuild only from immutable events.
    import integration_shared as shared
    from app.protocol_workflow.application import study_definition_stream_id
    from app.protocol_workflow.application.reconstruction import reconstruct_study
    with shared.make_factory(database)() as uow:
        events = uow.event_stream_repository.read_events(PROJECT, study_definition_stream_id(SD_ID))
    outcome = reconstruct_study(events)
    assert not outcome.is_quarantined
    assert outcome.success.canonical_revision_sha256 == newer.json()["revision_sha256"]
