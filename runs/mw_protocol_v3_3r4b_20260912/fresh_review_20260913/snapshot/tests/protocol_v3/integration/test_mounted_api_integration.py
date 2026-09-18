"""Protocol v3 Task 1R.3 — mounted-API integration over the real chain.

The product composition (``mount_protocol_workflow_router``) is mounted on a
plain FastAPI app over a test-owned product SQLite file; a admitted project
then exercises mutation → GET, GET-without-write, typed 409 errors without
implementation leaks, and the unknown-COMMIT-outcome reconcile-before-retry
discipline — all over HTTP.  A final test crosses two real ``app.main``
processes (create in one, read in the other) to prove restart durability on
the actual entrypoint.  Synthetic identities only; no live or legacy writes.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import integration_shared as shared


PROJECT = "proj:1r3:api:admitted"
OUTSIDER = "proj:1r3:api:outsider"
SD_ID = "sd:1r3:api:1"

ENV_ENABLED = "WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED"
ENV_DB = "WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"
ENV_BUSY_MS = "WORKBENCH_PROTOCOL_V3_WORKFLOW_BUSY_TIMEOUT_MS"

ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Mount helpers (mirroring the Task 1R.2 actual-mount pattern)
# ---------------------------------------------------------------------------


def _set_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: Optional[str] = "1",
    db_name: str = "wf_1r3.sqlite",
) -> Path:
    monkeypatch.setenv("WORKBENCH_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("WORKBENCH_AI_SETTINGS_PATH", str(tmp_path / "ai.json"))
    monkeypatch.setenv(
        "WORKBENCH_AI_ROLE_SETTINGS_PATH", str(tmp_path / "roles.json")
    )
    monkeypatch.setenv(
        "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR", str(tmp_path / "eligibility")
    )
    if enabled is None:
        monkeypatch.delenv(ENV_ENABLED, raising=False)
    else:
        monkeypatch.setenv(ENV_ENABLED, enabled)
    db_path = tmp_path / db_name
    monkeypatch.setenv(ENV_DB, str(db_path))
    monkeypatch.delenv(ENV_BUSY_MS, raising=False)
    return db_path


def _mount(app: FastAPI) -> bool:
    from app.protocol_workflow.api.composition import (
        mount_protocol_workflow_router,
    )

    return mount_protocol_workflow_router(app)


def _admitted_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Path]:
    db_path = _set_env(monkeypatch, tmp_path)
    shared.admit(db_path, PROJECT)
    app = FastAPI()
    assert _mount(app) is True
    return TestClient(app), db_path


def _decision_dict(
    *,
    decision_record_id: str,
    decision_key: str,
    snapshot_sha256: str,
    expected_state_revision: int,
    reason: str = shared.REASON,
) -> Dict[str, Any]:
    return shared.make_decision(
        decision_record_id=decision_record_id,
        decision_key=decision_key,
        snapshot_sha256=snapshot_sha256,
        expected_state_revision=expected_state_revision,
        reason=reason,
    ).model_dump(mode="json")


def _create_body(
    *,
    project_id: str = PROJECT,
    study_definition_id: str = SD_ID,
    idempotency_key: str = "idem:1r3:api:create",
    decision_record_id: str = "decision:1r3:api:create:001",
    reason: str = shared.REASON,
    side_effect: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    snapshot = shared.genesis_snapshot(
        study_definition_id=study_definition_id, project_id=project_id
    )
    body = {
        "project_id": project_id,
        "study_definition_id": study_definition_id,
        "idempotency_key": idempotency_key,
        "expected_revision": 0,
        "actor_type": "user",
        "actor_id": shared.ACTOR_ID,
        "reason": reason,
        "decision_record": _decision_dict(
            decision_record_id=decision_record_id,
            decision_key="decision:create",
            snapshot_sha256=snapshot,
            expected_state_revision=0,
            reason=reason,
        ),
        "normalized_seed_id": shared.SEED_ID,
        "normalized_seed_sha256": shared.SEED_SHA,
        "initial_facts": dict(shared.FACTS),
    }
    if side_effect is not None:
        body["side_effect"] = side_effect
    return body


def _apply_body(
    *,
    snapshot_sha256: str,
    idempotency_key: str,
    expected_revision: int = 1,
    decision_record_id: str = "decision:1r3:api:dose:001",
    fact_updates: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "project_id": PROJECT,
        "study_definition_id": SD_ID,
        "idempotency_key": idempotency_key,
        "expected_revision": expected_revision,
        "actor_type": "user",
        "actor_id": shared.ACTOR_ID,
        "reason": shared.REASON,
        "decision_record": _decision_dict(
            decision_record_id=decision_record_id,
            decision_key="decision:dose",
            snapshot_sha256=snapshot_sha256,
            expected_state_revision=expected_revision,
        ),
        "fact_updates": dict(fact_updates)
        if fact_updates is not None
        else dict(shared.NEW_FACT),
    }


def _base(project_id: str = PROJECT) -> str:
    return f"/api/projects/{project_id}/protocol-workflow"


# ---------------------------------------------------------------------------
# Mutation → GET round trip against the real mounted chain
# ---------------------------------------------------------------------------


class TestMountedMutationGetRoundTrip:
    def test_create_apply_get_events_agree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, db_path = _admitted_client(tmp_path, monkeypatch)
        created = client.post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert created.status_code == 200, created.text
        created_body = created.json()
        assert created_body["revision"] == 1
        assert created_body["replayed"] is False
        assert len(created_body["revision_sha256"]) == 64

        applied = client.post(
            f"{_base()}/study-definitions/{SD_ID}/decisions",
            json=_apply_body(
                snapshot_sha256=created_body["revision_sha256"],
                idempotency_key="idem:1r3:api:apply:1",
            ),
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["revision"] == 2

        current = client.get(f"{_base()}/study-definitions/{SD_ID}")
        assert current.status_code == 200
        assert (
            current.json()["revision_sha256"]
            == applied.json()["revision_sha256"]
        )
        assert current.json()["definition"]["canonical_state"] in (
            "confirmed",
            "proposed",
        )

        events = client.get(f"{_base()}/study-definitions/{SD_ID}/events")
        assert events.status_code == 200
        events_body = events.json()
        assert events_body["event_count"] == 2
        assert len(events_body["last_event_sha256"]) == 64
        assert [d["state_revision"] for d in events_body["decisions"]] == [1, 2]

        graph = client.get(
            f"{_base()}/study-definitions/{SD_ID}/decision-graph"
        )
        assert graph.status_code == 200

        # The HTTP reads agree with direct product-adapter reads.
        service = shared.make_service(shared.make_factory(db_path))
        fingerprint = shared.fingerprint_dict(service, PROJECT, SD_ID)
        assert fingerprint["revision"] == 2
        assert (
            fingerprint["revision_sha256"]
            == applied.json()["revision_sha256"]
        )
        assert fingerprint["event_count"] == 2
        assert (
            fingerprint["last_event_sha256"]
            == events_body["last_event_sha256"]
        )

    def test_get_endpoints_produce_no_business_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, db_path = _admitted_client(tmp_path, monkeypatch)
        created = client.post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert created.status_code == 200, created.text

        dump_before = shared.dump_business_tables(db_path)
        files_before = shared.db_file_names(db_path)
        head_before = (
            shared.fingerprint_dict(
                shared.make_service(shared.make_factory(db_path)),
                PROJECT,
                SD_ID,
            )["last_event_sha256"],
            _event_count_via_http(client),
        )

        for _ in range(2):
            assert (
                client.get(f"{_base()}/study-definitions/{SD_ID}").status_code
                == 200
            )
            assert (
                client.get(
                    f"{_base()}/study-definitions/{SD_ID}/events"
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"{_base()}/study-definitions/{SD_ID}/decision-graph"
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"{_base()}/workflow-runs/wr:1r3:api:missing"
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"{_base()}/study-definitions/sd:1r3:api:missing"
                ).status_code
                == 404
            )

        assert shared.dump_business_tables(db_path) == dump_before
        assert shared.db_file_names(db_path) == files_before
        service = shared.make_service(shared.make_factory(db_path))
        assert (
            shared.fingerprint_dict(service, PROJECT, SD_ID)[
                "last_event_sha256"
            ]
            == head_before[0]
        )
        assert _event_count_via_http(client) == head_before[1] == 1


def _event_count_via_http(client: TestClient) -> int:
    response = client.get(f"{_base()}/study-definitions/{SD_ID}/events")
    assert response.status_code == 200
    return int(response.json()["event_count"])


# ---------------------------------------------------------------------------
# Typed errors over HTTP: explicit rollback, no implementation leaks
# ---------------------------------------------------------------------------


class TestMountedErrorEnvelope:
    def test_landed_commit_lost_acknowledgement_over_http(self, tmp_path, monkeypatch):
        from app.protocol_workflow.storage.sqlite import SqliteUnitOfWork

        client, db_path = _admitted_client(tmp_path, monkeypatch)
        original_commit = SqliteUnitOfWork.commit
        lost = False

        def commit_then_lose_ack(self):
            nonlocal lost
            original_commit(self)
            if not lost:
                lost = True
                raise sqlite3.OperationalError("synthetic acknowledgement loss")

        monkeypatch.setattr(SqliteUnitOfWork, "commit", commit_then_lose_ack)
        body = _create_body(idempotency_key="idem:1r3:http:landed")
        response = client.post(f"{_base()}/study-definitions", json=body)
        assert response.status_code == 500
        assert response.json()["detail"]["can_retry"] is False
        observed = client.get(f"{_base()}/study-definitions/{SD_ID}")
        assert observed.status_code == 200
        assert observed.json()["revision"] == 1
        before = shared.dump_business_tables(db_path)
        replay = client.post(f"{_base()}/study-definitions", json=body)
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert shared.dump_business_tables(db_path) == before
        assert shared.integrity_check(db_path) == "ok"

    def test_present_unusable_database_returns_503_over_http(self, tmp_path, monkeypatch):
        db_path = _set_env(monkeypatch, tmp_path)
        original = b"synthetic non-database content"
        db_path.write_bytes(original)
        app = FastAPI()
        assert _mount(app)
        response = TestClient(app).post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert set(detail) == shared.PUBLIC_ENVELOPE_KEYS
        assert detail["can_retry"] is False
        assert "未执行" in detail["message"]
        assert db_path.read_bytes() == original

    def test_stale_apply_returns_409_without_write_or_leak(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, db_path = _admitted_client(tmp_path, monkeypatch)
        created = client.post(
            f"{_base()}/study-definitions", json=_create_body()
        )
        assert created.status_code == 200, created.text
        rev1_sha = created.json()["revision_sha256"]

        stale = client.post(
            f"{_base()}/study-definitions/{SD_ID}/decisions",
            json=_apply_body(
                snapshot_sha256=rev1_sha,
                idempotency_key="idem:1r3:api:stale",
                expected_revision=2,
                decision_record_id="decision:1r3:api:stale:001",
            ),
        )
        assert stale.status_code == 409, stale.text
        detail = stale.json()["detail"]
        assert set(detail.keys()) == shared.PUBLIC_ENVELOPE_KEYS
        assert detail["can_retry"] is True
        leaked = json.dumps(stale.json()).lower()
        for token in (".sqlite", "traceback", "sqlite3", "operationalerror"):
            assert token not in leaked

        events = client.get(f"{_base()}/study-definitions/{SD_ID}/events")
        assert events.json()["event_count"] == 1
        current = client.get(f"{_base()}/study-definitions/{SD_ID}")
        assert current.json()["revision_sha256"] == rev1_sha

    def test_injected_precommit_abort_reconciles_before_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.protocol_workflow.storage.sqlite import SqliteUnitOfWork

        client, db_path = _admitted_client(tmp_path, monkeypatch)
        created_uows: list = []
        original_enter = SqliteUnitOfWork.__enter__
        original_commit = SqliteUnitOfWork.commit
        fired = {"count": 0}

        def recording_enter(self):
            created_uows.append(self)
            return original_enter(self)

        def flaky_commit(self):
            if fired["count"] == 0:
                fired["count"] += 1
                raise sqlite3.OperationalError(
                    "injected COMMIT failure (1R.3 unknown-outcome probe)"
                )
            return original_commit(self)

        monkeypatch.setattr(SqliteUnitOfWork, "__enter__", recording_enter)
        monkeypatch.setattr(SqliteUnitOfWork, "commit", flaky_commit)

        body = _create_body(idempotency_key="idem:1r3:api:unknown")
        failed = client.post(f"{_base()}/study-definitions", json=body)
        # A driver failure at the commit boundary has an unknown outcome: the
        # product answers 500 with can_retry=False and directs the caller to
        # reconcile saved content first — never a blind-retry suggestion and
        # never a typed success, leak, or traceback.
        assert failed.status_code == 500, failed.text
        detail = failed.json()["detail"]
        assert set(detail.keys()) == shared.PUBLIC_ENVELOPE_KEYS
        assert detail["can_retry"] is False
        assert detail["message"] == "当前操作的结果尚未确认。"
        assert (
            detail["next_step"]
            == "请先刷新查看已保存内容，核对本次操作结果，暂勿重复提交。"
        )
        leaked = json.dumps(failed.json()).lower()
        for token in (".sqlite", "traceback", "sqlite3", "operationalerror"):
            assert token not in leaked
        # The injection replaces commit(), so this is fixture cleanup, not
        # evidence of product cleanup after a real driver failure.
        for uow in created_uows:
            uow.rollback()

        # Reconcile by logical key BEFORE any retry: the object is absent, so
        # the verified terminal state permits exactly one identical retry.
        missing = client.get(f"{_base()}/study-definitions/{SD_ID}")
        assert missing.status_code == 404
        assert set(missing.json()["detail"].keys()) == shared.PUBLIC_ENVELOPE_KEYS

        retried = client.post(f"{_base()}/study-definitions", json=body)
        assert retried.status_code == 200, retried.text
        assert retried.json()["replayed"] is False
        assert retried.json()["revision"] == 1
        events = client.get(f"{_base()}/study-definitions/{SD_ID}/events")
        assert events.json()["event_count"] == 1
        assert shared.integrity_check(db_path) == "ok"


# ---------------------------------------------------------------------------
# Real main entrypoint across two processes: create, then read after restart
# ---------------------------------------------------------------------------

_MISSING_LEGACY_DEPS = tuple(
    name
    for name, present in (
        ("fitz(PyMuPDF)", importlib.util.find_spec("fitz") is not None),
        ("xlrd", importlib.util.find_spec("xlrd") is not None),
    )
    if not present
)

_CHILD_CREATE_SCRIPT = r"""
import json
import os
import sys

sys.path.insert(0, os.environ["CHECKOUT"])
sys.path.insert(0, os.path.join(os.environ["CHECKOUT"], "services/api"))
sys.path.insert(0, os.path.join(os.environ["CHECKOUT"], "packages"))

from app.protocol_workflow.storage.sqlite import admit_project

admit_project(
    {"backend": "sqlite", "path": os.environ["WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"]},
    "proj:1r3:api:admitted",
)

from fastapi.testclient import TestClient
import app.main as main_module

client = TestClient(main_module.app)
body = json.loads(sys.stdin.read())
created = client.post(
    "/api/projects/proj:1r3:api:admitted/protocol-workflow/study-definitions",
    json=body,
)
assert created.status_code == 200, created.text
print(json.dumps(created.json(), sort_keys=True))
"""

_CHILD_READ_SCRIPT = r"""
import json
import os
import sys

sys.path.insert(0, os.environ["CHECKOUT"])
sys.path.insert(0, os.path.join(os.environ["CHECKOUT"], "services/api"))
sys.path.insert(0, os.path.join(os.environ["CHECKOUT"], "packages"))

from fastapi.testclient import TestClient
import app.main as main_module

client = TestClient(main_module.app)
base = "/api/projects/proj:1r3:api:admitted/protocol-workflow/study-definitions/sd:1r3:api:1"
current = client.get(base)
assert current.status_code == 200, current.text
events = client.get(base + "/events")
assert events.status_code == 200, events.text
outsider = client.get(
    "/api/projects/proj:1r3:api:outsider/protocol-workflow"
    "/study-definitions/sd:1r3:api:1"
)
print(json.dumps({
    "current": current.json(),
    "events": events.json(),
    "outsider_status": outsider.status_code,
    "outsider_detail": outsider.json(),
}, sort_keys=True))
"""


def test_real_main_create_then_separate_process_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert not _MISSING_LEGACY_DEPS, (
        f"Missing {_MISSING_LEGACY_DEPS}; use the isolated integration venv"
    )
    runtime = tmp_path / "child_runtime"
    runtime.mkdir()
    db_path = tmp_path / "real_main_1r3.sqlite"
    child_env = dict(os.environ)
    for key in (
        "WORKBENCH_AI_SETTINGS_PATH",
        "WORKBENCH_AI_ROLE_SETTINGS_PATH",
        "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR",
    ):
        child_env.pop(key, None)
    child_env.update(
        {
            "CHECKOUT": str(ROOT),
            "WORKBENCH_RUNTIME_DIR": str(runtime),
            "WORKBENCH_AI_SETTINGS_PATH": str(runtime / "ai.json"),
            "WORKBENCH_AI_ROLE_SETTINGS_PATH": str(runtime / "roles.json"),
            "WORKBENCH_ELIGIBILITY_ARTIFACT_DIR": str(runtime / "eligibility"),
            "WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED": "1",
            "WORKBENCH_PROTOCOL_V3_WORKFLOW_DB": str(db_path),
            "WORKBENCH_INCLUDE_REFERENCE_PROJECTS": "false",
        }
    )
    body = _create_body(idempotency_key="idem:1r3:api:realmain")
    creator = subprocess.run(
        [sys.executable, "-c", _CHILD_CREATE_SCRIPT],
        env=child_env,
        input=json.dumps(body),
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert creator.returncode == 0, (
        f"real-main create child failed rc={creator.returncode}\n"
        f"STDOUT:\n{creator.stdout[-4000:]}\n"
        f"STDERR:\n{creator.stderr[-4000:]}"
    )
    created = json.loads(creator.stdout.strip().splitlines()[-1])
    assert created["revision"] == 1
    assert len(created["revision_sha256"]) == 64

    reader = subprocess.run(
        [sys.executable, "-c", _CHILD_READ_SCRIPT],
        env=child_env,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert reader.returncode == 0, (
        f"real-main read child failed rc={reader.returncode}\n"
        f"STDOUT:\n{reader.stdout[-4000:]}\n"
        f"STDERR:\n{reader.stderr[-4000:]}"
    )
    observed = json.loads(reader.stdout.strip().splitlines()[-1])
    assert (
        observed["current"]["revision_sha256"] == created["revision_sha256"]
    )
    assert observed["current"]["revision"] == 1
    assert observed["events"]["event_count"] == 1
    assert len(observed["events"]["last_event_sha256"]) == 64
    assert [d["state_revision"] for d in observed["events"]["decisions"]] == [1]
    assert observed["outsider_status"] == 404
    assert shared.PUBLIC_ENVELOPE_KEYS <= set(
        observed["outsider_detail"]["detail"]
    )
    assert db_path.exists()
