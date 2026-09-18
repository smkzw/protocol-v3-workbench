"""Follow-up probes for A/B/C only. Synthetic tmp SQLite, fake model."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from test_clinical_design_worker import prepared_reference
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_mounted_api_integration import PROJECT, SD_ID, _create_body, _apply_body
from test_template_fact_adoption import _dump, _facts
import integration_shared as shared

SCRATCH = Path(__file__).resolve().parent
PRIOR = ROOT.parents[2] / "runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json"
PUBLIC = {"message", "responsible_area", "can_retry", "next_step"}


def _counts(db):
    with sqlite3.connect(db) as connection:
        events = connection.execute("select count(*) from event_stream").fetchone()[0]
        revisions = connection.execute("select count(*) from aggregate_revision").fetchone()[0]
        max_rev = connection.execute(
            "select max(revision) from aggregate_revision where aggregate_id=?", (SD_ID,)
        ).fetchone()[0]
    return events, revisions, max_rev


def _client(db, designs):
    app = FastAPI()
    mount_protocol_workflow_router(
        app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
        regimen_coordinator_factory=designs,
    )
    return TestClient(app)


def _start_ready(db):
    prepared, output = prepared_reference()
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = create_product_regimen_factory(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR, max_input_bytes=2000000,
        credential_resolver=lambda: "synthetic-only", http_opener=opener,
    )
    shared.admit(db, PROJECT)
    run = designs(PROJECT).start(prepared)
    assert designs(PROJECT).resume(run)["status"] == "ready_for_review"
    return designs, opener, run


def test_a_template_missing_is_424_before_any_write(tmp_path, monkeypatch):
    db = tmp_path / "a-config.sqlite"
    designs, opener, run = _start_ready(db)
    import app.protocol_workflow.api.composition as composition
    from app.protocol_workflow.events.unit_of_work import EventSourcedUnitOfWork

    order = []
    original_build = EventSourcedUnitOfWork.build_and_apply

    def boom(*args, **kwargs):
        order.append("load")
        raise OSError("current template missing")

    def capture_write(self, *args, **kwargs):
        order.append("write")
        return original_build(self, *args, **kwargs)

    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID, "operation_id": "operation:regimen:cfg",
            "expected_revision": 1, "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example", "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        before_dump = _dump(db)
        before_counts = _counts(db)
        monkeypatch.setattr(composition, "load_current_template", boom)
        monkeypatch.setattr(EventSourcedUnitOfWork, "build_and_apply", capture_write)
        adopted = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        recovered = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover", json=intent
        )
    assert adopted.status_code == 424, adopted.text
    detail = adopted.json()["detail"]
    assert set(detail) == PUBLIC
    assert detail["can_retry"] is False
    assert "未执行" in detail["message"]
    assert "配置" in detail["next_step"]
    assert recovered.status_code == 404, recovered.text
    assert _dump(db) == before_dump
    assert _counts(db) == before_counts
    assert order == ["load"]
    assert opener.calls == 1
    SCRATCH.joinpath("probe_a_424.json").write_text(json.dumps({
        "adopt": adopted.status_code, "recover": recovered.status_code,
        "detail": detail, "order": order, "counts": list(before_counts),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def test_a_unknown_failure_remains_500():
    from fastapi import HTTPException
    from app.protocol_workflow.api.router import _safe_call
    def unknown():
        raise RuntimeError("response interrupted after possible commit")
    try:
        _safe_call(unknown)
        raise AssertionError("expected HTTPException")
    except HTTPException as exc:
        assert exc.status_code == 500
        assert set(exc.detail) == PUBLIC
        assert exc.detail["can_retry"] is False
        assert "尚未确认" in exc.detail["message"]
        assert "重复提交" in exc.detail["next_step"]


def test_b_lookup_keeps_successor_without_compiler_or_template(tmp_path, monkeypatch):
    db = tmp_path / "b-lookup.sqlite"
    designs, opener, run = _start_ready(db)
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID, "operation_id": "operation:regimen:lookup",
            "expected_revision": 1, "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example", "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        first = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        assert first.status_code == 200, first.text
        later = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/study-definitions/{SD_ID}/decisions",
            json=_apply_body(
                snapshot_sha256=first.json()["revision_sha256"],
                idempotency_key="operation:age:later", expected_revision=2,
                decision_record_id="decision:age:later",
            ),
        )
        assert later.status_code == 200, later.text
        before = _dump(db)
        import app.protocol_workflow.api.composition as composition
        monkeypatch.setattr(
            composition, "load_current_template",
            lambda *a, **k: (_ for _ in ()).throw(OSError("template should not load on lookup")),
        )
        monkeypatch.setattr(
            "app.protocol_workflow.agent2.study_definition.propose_regimen_fact_updates",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("compiler should not run on lookup")),
        )
        found = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover", json=intent)
        tampered = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover",
            json={**intent, "reason": "a different recorded choice"},
        )
        missing_run = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/regimen-design:missing/adopt/recover",
            json=intent,
        )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["replayed"] is True
    assert body["revision"] == 3
    assert body["revision_sha256"] == later.json()["revision_sha256"]
    assert body["effective_decision"]["decision_record_id"] == first.json()["effective_decision"]["decision_record_id"]
    assert body["definition"]["facts"]["picos.population.age"] == "成人"
    assert tampered.status_code == 409, tampered.text
    assert missing_run.status_code == 404, missing_run.text
    assert _dump(db) == before
    assert opener.calls == 1


def test_b_unresolved_without_receipt_is_404_not_422(tmp_path):
    db = tmp_path / "b-unresolved.sqlite"
    prepared, _ = prepared_reference()
    output = {"coverage": [], "regimen": None, "questions": ["本研究是否拟采用该参考给药安排？"]}
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = create_product_regimen_factory(
        storage_config={"backend": "sqlite", "path": str(db)},
        prior_probe_receipt=PRIOR, max_input_bytes=2000000,
        credential_resolver=lambda: "synthetic-only", http_opener=opener,
    )
    shared.admit(db, PROJECT)
    run = designs(PROJECT).start(prepared)
    assert designs(PROJECT).resume(run)["status"] == "needs_information"
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID, "operation_id": "operation:regimen:unresolved",
            "expected_revision": 1, "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example", "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        before = _dump(db)
        adopted = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        recovered = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover", json=intent
        )
    assert adopted.status_code == 409, adopted.text
    assert recovered.status_code == 404, recovered.text
    assert _dump(db) == before


def test_b_corrupt_ledger_does_not_return_a_receipt(tmp_path):
    db = tmp_path / "b-corrupt.sqlite"
    designs, _, run = _start_ready(db)
    with _client(db, designs) as c:
        created = c.post(f"/api/projects/{PROJECT}/protocol-workflow/study-definitions", json=_create_body()).json()
        intent = {
            "study_definition_id": SD_ID, "operation_id": "operation:regimen:corrupt",
            "expected_revision": 1, "snapshot_sha256": created["revision_sha256"],
            "actor_id": "user:example", "decided_at": "2026-09-13T07:00:00+00:00",
            "reason": "采用完整给药方案",
        }
        first = c.post(f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt", json=intent)
        assert first.status_code == 200, first.text
    with sqlite3.connect(db) as connection:
        rows = list(connection.execute("select domain_event_id, body_json from event_stream"))
        assert rows
        domain_event_id, raw = rows[-1]
        payload = json.loads(raw)
        inner = payload.get("payload", payload)
        if isinstance(inner, dict) and "kind" in inner:
            inner.pop("kind", None)
        elif isinstance(payload, dict):
            payload.pop("kind", None)
        connection.execute(
            "update event_stream set body_json=? where domain_event_id=?",
            (json.dumps(payload, ensure_ascii=False), domain_event_id),
        )
        connection.commit()
    with _client(db, designs) as c:
        recovered = c.post(
            f"/api/projects/{PROJECT}/protocol-workflow/design/regimen/{run}/adopt/recover", json=intent
        )
    assert recovered.status_code != 200, recovered.text
    assert recovered.status_code in {500, 424, 409}
    detail = recovered.json().get("detail") or {}
    if isinstance(detail, dict) and "message" in detail:
        assert "已保存" not in detail["message"]
    SCRATCH.joinpath("probe_b_corrupt.json").write_text(json.dumps({
        "status": recovered.status_code, "detail": detail,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
