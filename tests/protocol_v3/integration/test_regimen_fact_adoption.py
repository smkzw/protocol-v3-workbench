"""Compound regimen enters the existing HTTP/SQLite decision transaction intact."""
from test_template_fact_adoption import BASE, SD_ID, _admitted_client, _seed, _template_body, _facts, _dump
from test_clinical_design_worker import prepared_reference
from app.protocol_workflow.agent2.clinical_worker import read_regimen_response


def test_complete_regimen_is_one_fact_and_exact_replay_has_no_new_effect(tmp_path, monkeypatch):
    from app.protocol_workflow.agent2.study_definition import propose_regimen_fact_updates
    prepared, output = prepared_reference()
    proposal = read_regimen_response(prepared, output)
    updates = propose_regimen_fact_updates(proposal)
    assert list(updates) == ["intervention.dose_regimen"]
    client, database = _admitted_client(tmp_path, monkeypatch)
    with client:
        created = _seed(client)
        body = _template_body(snapshot_sha256=created["revision_sha256"], idempotency_key="idem:regimen:first",
            decision_record_id="decision:regimen:first", decision_key="decision:dose-regimen",
            fact_updates=updates, input_refs=[{"fact_path": "intervention.dose_regimen"}])
        first = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
        assert first.status_code == 200, first.json()
        stored = _facts(client)["intervention.dose_regimen"]
        assert len(stored["schedules"]) == 4
        assert all(len(schedule["steps"]) == 2 for schedule in stored["schedules"])
        assert stored["schedules"][0]["steps"][0]["products"][0]["dose"]["value"] == 200
        assert type(stored["schedules"][0]["steps"][0]["products"][0]["dose"]["value"]) is int
        before = _dump(database)
        again = client.post(f"{BASE}/{SD_ID}/decisions", json=body)
        assert again.status_code == 200 and again.json()["replayed"]
        assert _dump(database) == before
        assert proposal["regimen"]["canonical_state"] == "proposed"
