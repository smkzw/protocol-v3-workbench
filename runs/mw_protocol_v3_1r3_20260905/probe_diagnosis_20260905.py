"""1R.3 diagnosis probe (evidence, 2026-09-05): WAL drain timing + unknown-commit HTTP body."""

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "tests" / "protocol_v3" / "integration"))

import integration_shared as shared

tmp = Path(tempfile.mkdtemp())
db = tmp / "probe.sqlite"


def wal() -> int:
    p = shared.wal_path(db)
    return p.stat().st_size if p.exists() else -1


def ckpt(label: str) -> None:
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        print(f"{label}: wal_bytes={wal()} checkpoint={tuple(row)}", flush=True)
    finally:
        conn.close()


print(f"sqlite={sqlite3.sqlite_version}", flush=True)
shared.admit(db, "proj:probe:a")
ckpt("after-admit")
service = shared.make_service(shared.make_factory(db))
service.create_study_definition(
    shared.create_command(
        project_id="proj:probe:a",
        study_definition_id="sd:probe:1",
        idempotency_key="idem:probe:create",
    )
)
ckpt("after-create")
print(f"wal_raw_bytes_after_create={wal()}", flush=True)
dump = shared.dump_business_tables(db)
print(f"after-dump: wal_bytes={wal()}", flush=True)
fp = shared.fingerprint_dict(service, "proj:probe:a", "sd:probe:1")
print(f"after-fingerprint: wal_bytes={wal()} rev={fp['revision']}", flush=True)
pin = sqlite3.connect(str(db), timeout=30)
pin.execute("BEGIN")
pin.execute("SELECT COUNT(*) FROM event_stream").fetchone()
print(f"after-pin-begin: wal_bytes={wal()}", flush=True)
pin.execute("ROLLBACK")
pin.close()

# --- unknown-commit HTTP body ---
os.environ["WORKBENCH_RUNTIME_DIR"] = str(tmp / "runtime")
os.environ["WORKBENCH_AI_SETTINGS_PATH"] = str(tmp / "ai.json")
os.environ["WORKBENCH_AI_ROLE_SETTINGS_PATH"] = str(tmp / "roles.json")
os.environ["WORKBENCH_ELIGIBILITY_ARTIFACT_DIR"] = str(tmp / "eligibility")
os.environ["WORKBENCH_PROTOCOL_V3_WORKFLOW_ENABLED"] = "1"
os.environ["WORKBENCH_PROTOCOL_V3_WORKFLOW_DB"] = str(tmp / "api.sqlite")
os.environ.pop("WORKBENCH_PROTOCOL_V3_WORKFLOW_BUSY_TIMEOUT_MS", None)

shared.admit(tmp / "api.sqlite", "proj:probe:api")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.protocol_workflow.api.composition import mount_protocol_workflow_router
from app.protocol_workflow.storage.sqlite import SqliteUnitOfWork

app = FastAPI()
assert mount_protocol_workflow_router(app) is True
client = TestClient(app)

snapshot = shared.genesis_snapshot(
    study_definition_id="sd:probe:api:1", project_id="proj:probe:api"
)
decision = shared.make_decision(
    decision_record_id="decision:probe:create:001",
    decision_key="decision:create",
    snapshot_sha256=snapshot,
    expected_state_revision=0,
).model_dump(mode="json")
body = {
    "project_id": "proj:probe:api",
    "study_definition_id": "sd:probe:api:1",
    "idempotency_key": "idem:probe:api:unknown",
    "expected_revision": 0,
    "actor_type": "user",
    "actor_id": shared.ACTOR_ID,
    "reason": shared.REASON,
    "decision_record": decision,
    "normalized_seed_id": shared.SEED_ID,
    "normalized_seed_sha256": shared.SEED_SHA,
    "initial_facts": dict(shared.FACTS),
}

original_commit = SqliteUnitOfWork.commit
fired = {"count": 0}


def flaky_commit(self):
    if fired["count"] == 0:
        fired["count"] += 1
        raise sqlite3.OperationalError("injected COMMIT failure (probe)")
    return original_commit(self)


SqliteUnitOfWork.commit = flaky_commit
try:
    failed = client.post(
        "/api/projects/proj:probe:api/protocol-workflow/study-definitions",
        json=body,
    )
finally:
    SqliteUnitOfWork.commit = original_commit
print(f"HTTP_UNKNOWN_STATUS={failed.status_code}", flush=True)
print(f"HTTP_UNKNOWN_BODY={failed.text}", flush=True)
