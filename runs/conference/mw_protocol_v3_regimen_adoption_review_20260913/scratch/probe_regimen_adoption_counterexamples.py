"""Independent reviewer probes: recovery, CAS, types, unresolved, extra fields.

Synthetic tmp SQLite only. No product writes, live services, or model calls.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.protocol_workflow.api.composition import (
    ProtocolWorkflowMountConfig,
    mount_protocol_workflow_router,
)
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from test_clinical_design_worker import prepared_reference
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_mounted_api_integration import PROJECT, SD_ID, _create_body, _apply_body
from test_template_fact_adoption import _dump, _facts
import integration_shared as shared

SCRATCH = Path(__file__).resolve().parent
PRIOR = ROOT.parents[2] / "runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json"


def _client(db, designs):
    app = FastAPI()
    mount_protocol_workflow_router(
        app,
        ProtocolWorkflowMountConfig(enabled=True, db_path=db),
        regimen_coordinator_factory=designs,
    )
    return TestClient(app)


def _start_ready(db):
    prepared, output = prepared_reference()
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = create_product_regimen_factory(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR,
        max_input_bytes=2000000,
        credential_resolver=lambda: "synthetic-only",
        http_opener=opener,
    )
    shared.admit(db, PROJECT)
    run = designs(PROJECT).start(prepared)
    assert designs(PROJECT).resume(run)["status"] == "ready_for_review"
    return designs, opener, run


def test_unresolved_design_cannot_be_adopted_and_writes_nothing(tmp_path):
    db = tmp_path / "unresolved.sqlite"
    prepared, _ = prepared_reference()
    output = {"coverage": [], "regimen": None, "questions": ["本研究是否拟采用该参考给药安排？"]}
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = create_product_regimen_factory(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR,
        max_input_bytes=2000000,
        credential_resolver=lambda: "synthetic-only",
        http_opener=opener,
    )
    shared.admit(db, PROJECT)
    run = designs(PROJECT).start(prepared)
    state = designs(PROJECT).resume(run)
    assert state["status"] == "needs_information"
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        before = _dump(db)
        intent = {
            "study_definition_id": SD_ID,
            "operation_id": "operation:regimen:unresolved",
            "expected_revision": 1,
            "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        adopted = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        recovered = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover", json=intent
        )
        extra = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt",
            json={**intent, "fact_updates": {"intervention.dose_regimen": {"forged": True}}},
        )
    assert adopted.status_code == 409, adopted.text
    assert "未决" in adopted.json()["detail"]["message"]
    assert recovered.status_code == 422, recovered.text
    assert extra.status_code == 422, extra.text
    assert _dump(db) == before
    assert opener.calls == 1


def test_client_cannot_supply_regimen_facts_on_ready_adopt(tmp_path):
    db = tmp_path / "extra.sqlite"
    designs, opener, run = _start_ready(db)
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID,
            "operation_id": "operation:regimen:extra",
            "expected_revision": 1,
            "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
            "fact_updates": {"intervention.dose_regimen": {"schedules": []}},
            "regimen": {"forged": True},
        }
        before = _dump(db)
        response = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
    assert response.status_code == 422, response.text
    assert _dump(db) == before
    assert opener.calls == 1


def test_recover_keeps_successor_and_does_not_need_current_template(tmp_path, monkeypatch):
    db = tmp_path / "successor.sqlite"
    designs, opener, run = _start_ready(db)
    loads = {"count": 0}
    import app.protocol_workflow.api.composition as composition

    original = composition.load_current_template

    def counting_loader(*args, **kwargs):
        loads["count"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(composition, "load_current_template", counting_loader)
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID,
            "operation_id": "operation:regimen:successor",
            "expected_revision": 1,
            "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        first = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        assert first.status_code == 200, first.text
        adopted_loads = loads["count"]
        assert adopted_loads >= 1
        stored = _facts(c)
        assert type(stored["intervention.dose_regimen"]["schedules"][0]["steps"][0]["products"][0]["dose"]["value"]) is int
        later = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/{SD_ID}/decisions",
            json=_apply_body(
                snapshot_sha256=first.json()["revision_sha256"],
                idempotency_key="operation:age:later",
                expected_revision=2,
                decision_record_id="decision:age:later",
            ),
        )
        assert later.status_code == 200, later.text
        assert later.json()["revision"] == 3
        def boom(*args, **kwargs):
            loads["count"] += 1
            raise OSError("current template missing")
        monkeypatch.setattr(composition, "load_current_template", boom)
        before = _dump(db)
        recovered = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover", json=intent
        )
        replay = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["revision"] == 3
    assert recovered.json()["replayed"] is True
    assert recovered.json()["revision_sha256"] == later.json()["revision_sha256"]
    assert recovered.json()["definition"]["facts"]["picos.population.age"] == "成人"
    assert recovered.json()["effective_decision"]["decision_record_id"] == first.json()["effective_decision"]["decision_record_id"]
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["revision"] == 3
    assert _dump(db) == before
    assert opener.calls == 1
    # Recover/replay must not consult the current template loader.
    assert loads["count"] == adopted_loads


def test_fresh_adopt_with_missing_template_does_not_write(tmp_path, monkeypatch):
    db = tmp_path / "template-miss.sqlite"
    designs, opener, run = _start_ready(db)
    import app.protocol_workflow.api.composition as composition
    monkeypatch.setattr(composition, "load_current_template", lambda *a, **k: (_ for _ in ()).throw(OSError("current template missing")))
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID,
            "operation_id": "operation:regimen:template-miss",
            "expected_revision": 1,
            "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        before = _dump(db)
        adopted = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        recovered = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover", json=intent
        )
    assert adopted.status_code == 500, adopted.text
    assert recovered.status_code == 404, recovered.text
    assert _dump(db) == before
    assert opener.calls == 1


def test_persisted_decision_has_option_id_but_no_recommendation_or_claim_rows(tmp_path):
    db = tmp_path / "options.sqlite"
    designs, _, run = _start_ready(db)
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID,
            "operation_id": "operation:regimen:options",
            "expected_revision": 1,
            "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example",
            "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        first = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        assert first.status_code == 200, first.text
        events_resp = c.get(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/{SD_ID}/events")
        graph_resp = c.get(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/{SD_ID}/decision-graph")
        current = c.get(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/{SD_ID}").json()
    assert events_resp.status_code == 200, events_resp.text
    events = events_resp.json()
    payload = json.dumps(events, ensure_ascii=False)
    decision = first.json()["effective_decision"]
    assert decision["option_ids"] and decision["selected_option_id"] in decision["option_ids"]
    assert "RecommendationOption" not in payload
    assert "ClaimEvidenceLink" not in payload
    assert "claim_evidence_link" not in payload.lower()
    assert "recommendation_option" not in payload.lower()
    assert current["definition"]["study_definition_id"] == SD_ID
    dump_text = "\n".join(_dump(db))
    assert "intervention.dose_regimen" in dump_text
    import sqlite3
    payloads = []
    with sqlite3.connect(db) as connection:
        for (raw,) in connection.execute("select body_json from event_stream"):
            payloads.append(json.loads(raw) if isinstance(raw, str) else json.loads(bytes(raw)))
    def walk(node, found):
        if isinstance(node, dict):
            if "decision_input_binding" in node:
                found.append(node["decision_input_binding"])
            for value in node.values():
                walk(value, found)
        elif isinstance(node, list):
            for value in node:
                walk(value, found)
        return found
    bindings = walk(payloads, [])
    assert bindings, {"event_count": len(payloads), "payload_keys": [list(item)[:12] for item in payloads if isinstance(item, dict)]}
    binding = bindings[-1]
    fact_paths = [item.get("fact_path") for item in binding.get("refs", [])]
    assert fact_paths == ["intervention.dose_regimen"]
    assert binding.get("schema_version") == "decision-input-binding.v1"
    assert events.get("event_count") >= 2
    assert all("option_ids" in item or "selected_option_id" in item for item in events.get("decisions", []))
    log = SCRATCH / "probe_option_persistence.json"
    log.write_text(json.dumps({
        "decision_option_ids": decision["option_ids"],
        "graph_status": graph_resp.status_code,
        "event_summary": {k: events.get(k) for k in ("event_count", "last_sequence") if isinstance(events, dict)},
        "binding": binding,
        "fact_paths": fact_paths,
        "has_recommendation_option_text": "recommendation_option" in dump_text.lower(),
        "has_claim_evidence_text": "claim_evidence" in dump_text.lower(),
        "events_public_keys": list(events) if isinstance(events, dict) else type(events).__name__,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
