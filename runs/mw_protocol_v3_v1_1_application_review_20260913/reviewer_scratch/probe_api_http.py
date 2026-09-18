"""C03 HTTP-boundary probes for the mounted research-intake API (scratch-only).

Temp SQLite + synthetic opener through FastAPI TestClient. No live service.
"""
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator
from app.protocol_workflow.agent1.seed_workflow import build_seed_runtime
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.storage.sqlite import (
    build_unit_of_work_factory,
    build_committed_reservation_repository_factory,
)
from test_seed_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver
from test_writing_reference_docx import build_docx, paragraph_xml
from test_source_import_api import PROJECT, BASE, upload
import integration_shared as shared

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def make_client(tmp, outcomes):
    db = Path(tmp) / "product.db"
    shared.admit(db, PROJECT)
    config = {"backend": "sqlite", "path": str(db)}
    store = LocalArtifactStore(str(db) + ".artifacts")
    role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_kind == "llm")
    skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions()
                 if s.skill_definition_id == "skill.research-seed-proposal")
    opener = _FakeOpener(outcomes)
    dispatcher = HarnessDispatcher()

    def factory(project_id):
        runtime = build_seed_runtime(
            project_id=project_id,
            uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
            adapter_factory=lambda **kw: build_zhipu_api_adapter(
                credential_resolver=_resolver(), http_opener=opener, max_input_bytes=100_000, **kw),
        )
        return SeedCoordinator(project_id=project_id, branch_id="main", runtime=runtime, artifact_store=store)

    app = FastAPI()
    mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
                                   seed_coordinator_factory=factory)
    return TestClient(app), opener, BASE.removesuffix("/sources") + "/research-intake"


def main():
    # -- normal acknowledgement + double POST reuse ------------------------
    with tempfile.TemporaryDirectory() as tmp:
        client, opener, endpoint = make_client(tmp, [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content='{"fields":{}}')),
        ])
        with client:
            upload(client, build_docx(paragraph_xml("完整项目资料")))
            src = client.get(BASE).json()["sources"][0]["source"]
            body = {"user_brief": "准备方案", "source_artifact_ids": [src["source_artifact_id"]]}
            r1 = client.post(endpoint, json=body)
            check("H1 POST acknowledges 202 with running status",
                  r1.status_code == 202 and r1.json()["status"] == "running", r1.text[:200])
            run_id = r1.json()["workflow_run_id"]
            g = client.get(f"{endpoint}/{run_id}")
            check("H2 GET reaches terminal proposal state",
                  g.status_code == 200 and g.json()["status"] == "needs_information", g.text[:200])
            r2 = client.post(endpoint, json=body)
            check("H3 identical re-POST reuses the same run without a new call",
                  r2.status_code == 202 and r2.json()["workflow_run_id"] == run_id
                  and r2.json()["status"] == "needs_information" and opener.calls == 2,
                  f"calls={opener.calls}")

            # -- crafted GET on the correction run id -----------------------
            outcomes_extended = client  # keep client open
            bad = client.get(f"{endpoint}/{run_id}:correction:1")
            check("H4 GET with correction-run id handled without 500",
                  bad.status_code < 500, f"status={bad.status_code} body={bad.text[:160]}")

            # -- unknown run id ---------------------------------------------
            miss = client.get(f"{endpoint}/research-seed:deadbeef")
            check("H5 unknown run id maps to 404 Chinese envelope",
                  miss.status_code == 404 and miss.json()["detail"]["message"] == "没有找到本次资料整理记录。",
                  miss.text[:160])

            # -- structural validation stays in envelope --------------------
            extra = client.post(endpoint, json={**body, "unexpected_field": 1})
            check("H6 extra field rejected with 422",
                  extra.status_code == 422, extra.text[:160])
            wrong_type = client.post(endpoint, json={"user_brief": 5, "source_artifact_ids": []})
            check("H7 wrong field type rejected with 422",
                  wrong_type.status_code == 422, wrong_type.text[:160])

            # -- stale selection ---------------------------------------------
            upload(client, build_docx(paragraph_xml("新的资料")), "2.0")
            stale = client.post(endpoint, json=body)
            check("H8 stale selection maps to 409 without any dispatch",
                  stale.status_code == 409 and stale.json()["detail"]["message"].startswith("所选资料已有变化")
                  and opener.calls == 2, f"calls={opener.calls} {stale.text[:160]}")

            # -- empty selection + brief only --------------------------------
            brief_only = client.post(endpoint, json={"user_brief": "只写说明", "source_artifact_ids": []})
            check("H9 brief-only intake accepted (202)",
                  brief_only.status_code == 202, brief_only.text[:160])

    # -- GET naming an EXISTING correction run id ---------------------------
    with tempfile.TemporaryDirectory() as tmp:
        client, opener, endpoint = make_client(tmp, [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content="bad json", response_id="invalid-1")),
            _FakeResponse(_completion_body(content='{"fields":{}}', response_id="fixed-1")),
        ])
        raw = TestClient(client.app, raise_server_exceptions=False)
        with raw:
            upload(raw, build_docx(paragraph_xml("更正场景资料")))
            src = raw.get(BASE).json()["sources"][0]["source"]
            body = {"user_brief": "更正场景", "source_artifact_ids": [src["source_artifact_id"]]}
            r = raw.post(endpoint, json=body)
            run_id = r.json()["workflow_run_id"]
            correction_id = raw.get(f"{endpoint}/{run_id}").json()["correction_run_id"]
            check("H4b precondition: correction run exists", correction_id is not None and opener.calls == 3)
            crafted = raw.get(f"{endpoint}/{correction_id}")
            check("H4b GET with existing correction-run id handled without 500",
                  crafted.status_code < 500, f"status={crafted.status_code} body={crafted.text[:200]}")

    # -- admission gate -----------------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        # unadmitted project: build the mount without admitting any project
        from app.protocol_workflow.api.composition import create_mounted_protocol_workflow_router

        router = create_mounted_protocol_workflow_router(
            ProtocolWorkflowMountConfig(enabled=True, db_path=Path(tmp) / "empty.db"))
        app = FastAPI()
        app.include_router(router)
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/projects/other/protocol-workflow/research-intake/x")
            check("H10 unadmitted project GET -> 404 stable envelope",
                  r.status_code == 404 and "detail" in r.json(), r.text[:160])
            empty_db_exists = (Path(tmp) / "empty.db").exists()
            check("H11 unadmitted request does not create the database file",
                  not empty_db_exists, f"db_exists={empty_db_exists}")

    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ==")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
