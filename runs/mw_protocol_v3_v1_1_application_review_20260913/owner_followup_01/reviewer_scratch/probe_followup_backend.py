"""C03 followup backend probes (scratch-only): D1/R1/R2, pinned inputs,
liveness races, credential binding, lazy factory. Temp SQLite + synthetic
HTTP only; no product calls, no real credentials, no servers."""
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

REPO = Path(__file__).resolve().parents[4]
SCRATCH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRATCH))

from app.protocol_workflow.agent1.research_seed import PreparedSeedRequest, prepare_seed_request
from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator
from app.protocol_workflow.agent1.seed_workflow import build_seed_runtime, seed_plan
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

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


def make_world(tmp, outcomes, *, dispatcher=None):
    config = {"backend": "sqlite", "path": str(tmp / "db.sqlite")}
    store = LocalArtifactStore(str(tmp / "artifacts"))
    role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_kind == "llm")
    skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions()
                 if s.skill_definition_id == "skill.research-seed-proposal")
    opener = _FakeOpener(outcomes)
    dispatcher = dispatcher or HarnessDispatcher()

    def coordinator(project_id="seed-project"):
        runtime = build_seed_runtime(
            project_id=project_id,
            uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
            adapter_factory=lambda **kw: build_zhipu_api_adapter(
                credential_resolver=_resolver(), http_opener=opener, max_input_bytes=100_000, **kw),
        )
        return SeedCoordinator(project_id=project_id, branch_id="main", runtime=runtime, artifact_store=store)

    return coordinator, opener, config, store


def make_api(tmp, outcomes):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router

    db = Path(tmp) / "product.db"
    sys.path.insert(0, str(Path("tests/protocol_v3/integration").resolve()))
    import integration_shared as shared
    shared.admit(db, "seed-project")
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
    endpoint = "/api/projects/seed-project/protocol-workflow/research-intake"
    return TestClient(app), endpoint, opener, factory, store, config


def attempt_rows(config, project_id):
    with sqlite3.connect(config["path"]) as conn:
        names = [r[1] for r in conn.execute("pragma table_info(execution_reservation)")]
        return [dict(zip(names, row)) for row in
                conn.execute("select * from execution_reservation where project_id=?", (project_id,))]


def upload(client, content, version=None):
    from test_writing_reference_docx import build_docx, paragraph_xml
    files = {"file": ("资料.docx", build_docx(paragraph_xml(content)), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    data = {"logical_source_key": "资料.docx", "source_role": "project_primary"}
    if version:
        data["source_version"] = version
    return client.post("/api/projects/seed-project/protocol-workflow/sources", files=files, data=data)


def probe_f1_d1_correction_id_404():
    with tempfile.TemporaryDirectory() as tmp:
        client, endpoint, opener, _, _, _ = make_api(tmp, [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content="bad json", response_id="bad-1")),
            _FakeResponse(_completion_body(content='{"fields":{}}', response_id="fix-1")),
        ])
        raw = client.app
        from fastapi.testclient import TestClient
        with TestClient(raw, raise_server_exceptions=False) as c:
            r = c.post(endpoint, json={"user_brief": "更正", "source_artifact_ids": []})
            run_id = r.json()["workflow_run_id"]
            state = c.get(f"{endpoint}/{run_id}").json()
            correction_id = state["correction_run_id"]
            check("F1a precondition: correction run exists", correction_id is not None, str(state.get("status")))
            crafted = c.get(f"{endpoint}/{correction_id}")
            check("F1 D1 fixed: crafted correction-id GET -> 404 Chinese envelope",
                  crafted.status_code == 404 and crafted.json()["detail"]["message"] == "没有找到本次资料整理记录。",
                  f"status={crafted.status_code} body={crafted.text[:120]}")


def probe_f2_recover_semantics():
    with tempfile.TemporaryDirectory() as tmp:
        client, endpoint, opener, factory, store, config = make_api(tmp, [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content='{"fields":{}}')),
        ])
        with client as c:
            src = upload(c, "最初资料").json()["current"]["source"]
            body = {"user_brief": "原始说明", "source_artifact_ids": [src["source_artifact_id"]]}
            r = c.post(endpoint, json=body)
            run_id = r.json()["workflow_run_id"]
            baseline = c.get(f"{endpoint}/{run_id}").json()
            # Supersede the source afterwards.
            upload(c, "新版资料", version="2.0")
            stale = c.post(endpoint, json=body)
            check("F2a ordinary stale POST stays 409", stale.status_code == 409, stale.text[:100])
            recovered = c.post(f"{endpoint}/recover", json=body)
            check("F2b /recover after supersession returns the original run read-only",
                  recovered.status_code == 200 and recovered.json()["workflow_run_id"] == run_id
                  and recovered.json() == baseline and opener.calls == 2,
                  f"calls={opener.calls}")
            missing = c.post(f"{endpoint}/recover", json={"user_brief": "从未提交", "source_artifact_ids": []})
            check("F2c /recover unknown request -> 404 envelope",
                  missing.status_code == 404 and "没有找到" in missing.json()["detail"]["message"],
                  missing.text[:100])
            # Recover tolerates duplicate/order-shuffled ids (set semantics).
            shuffled = c.post(f"{endpoint}/recover", json={"user_brief": "原始说明",
                                                           "source_artifact_ids": [src["source_artifact_id"], src["source_artifact_id"]]})
            check("F2d /recover is id-order/duplicate insensitive",
                  shuffled.status_code == 200 and shuffled.json()["workflow_run_id"] == run_id)


def probe_f3_resume_endpoint_and_blocking():
    with tempfile.TemporaryDirectory() as tmp:
        client, endpoint, opener, factory, store, config = make_api(tmp, [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content='{"fields":{}}', response_id="queued-1")),
            TimeoutError("synthetic timeout for blocked case"),
        ])
        with client as c:
            queued = factory("seed-project").start(prepare_seed_request("排队任务", ()))
            state = c.get(f"{endpoint}/{queued}").json()
            check("F3a queued run readable as running + can_resume",
                  state["status"] == "running" and state["can_resume"] is True, str(state["status"]))
            resumed = c.post(f"{endpoint}/{queued}/resume")
            check("F3b resume endpoint executes the queued run once",
                  resumed.status_code == 202 and c.get(f"{endpoint}/{queued}").json()["status"] == "needs_information"
                  and opener.calls == 2, f"calls={opener.calls}")
            again = c.post(f"{endpoint}/{queued}/resume")
            check("F3c repeated resume adds no call",
                  again.status_code == 202 and opener.calls == 2, f"calls={opener.calls}")
            blocked = factory("seed-project").start(prepare_seed_request("超时任务", ()))
            c.post(f"{endpoint}/{blocked}/resume")
            state = c.get(f"{endpoint}/{blocked}").json()
            check("F3d timeout -> blocked, can_resume false",
                  state["status"] == "blocked" and state["can_resume"] is False, str(state))
            before = len(attempt_rows(config, "seed-project"))
            c.post(f"{endpoint}/{blocked}/resume")
            after = len(attempt_rows(config, "seed-project"))
            check("F3e UNKNOWN outcome never redispatched via resume",
                  opener.calls == 3 and before == after, f"calls={opener.calls} attempts {before}->{after}")


def probe_f4_legacy_resume():
    import hashlib
    from app.protocol_workflow.canonical.hashing import canonical_json
    with tempfile.TemporaryDirectory() as tmp:
        coordinator, opener, config, _ = make_world(Path(tmp), [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content='{"fields":{}}')),
        ])
        legacy = prepare_seed_request("旧身份任务", ())
        old_identity = canonical_json(["seed-project", "main", "research-seed.v1", legacy.input_sha256])
        old_id = "research-seed:" + hashlib.sha256(old_identity.encode()).hexdigest()
        coordinator().runtime.start_run(seed_plan("seed-project", "main"),
                                        workflow_run_id=old_id,
                                        root_inputs={"research_intake": legacy.to_payload()})
        result = coordinator().resume(old_id)
        check("F4a legacy graph id resumes with pinned materials",
              result["workflow_run_id"] == old_id and result["status"] == "needs_information" and opener.calls == 2)
        again = coordinator().start(legacy)
        check("F4b start() reuses the legacy run id instead of creating a new-format run",
              again == old_id and opener.calls == 2 and coordinator().read(old_id)["status"] == "needs_information")


def probe_f5_pinned_input_across_compiler_change():
    import hashlib
    from app.protocol_workflow.canonical.hashing import canonical_json
    with tempfile.TemporaryDirectory() as tmp:
        coordinator, opener, config, _ = make_world(Path(tmp), [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content='{"fields":{}}')),
        ])
        original = prepare_seed_request("编译器变化场景", ())
        run_id = coordinator().start(original)
        first = coordinator().resume(run_id)
        changed = original.to_payload()
        changed["instruction"] = changed["instruction"] + "\n[新版编译指令]"
        changed["output_schema"] = {**changed["output_schema"], "title": "v2-schema"}
        text = canonical_json(changed)
        recompiled = PreparedSeedRequest(text, hashlib.sha256(text.encode()).hexdigest())
        check("F5a recompiled request maps to the same logical run id",
              coordinator().run_id(recompiled) == run_id and recompiled.input_sha256 != original.input_sha256)
        reused = coordinator().start(recompiled)
        check("F5b start pins the first compiled package (no rebind, no conflict)",
              reused == run_id and opener.calls == 2)
        repeat = coordinator().execute(recompiled)
        check("F5c execute(recompiled) replays the pinned outcome without new calls",
              repeat == first and opener.calls == 2)
        events = coordinator().runtime.read_events(run_id)
        started = next(e for e in events if e.event_type == "graph_run_started")
        pinned_text = canonical_json(started.payload["root_payloads"]["research_intake"])
        check("F5d persisted root payload remains the v1 compile",
              "新版编译指令" not in pinned_text and "v2-schema" not in json.dumps(started.payload["root_payloads"], ensure_ascii=False))


def probe_f6_r2_concurrent_adopts():
    from datetime import datetime, timezone
    from app.protocol_workflow.storage.selected import create_product_unit_of_work_factory
    from app.protocol_workflow.agent1.source_identity import SourceIdentityService

    def service(root):
        return SourceIdentityService(
            create_product_unit_of_work_factory(config={"backend": "sqlite", "path": str(root / "product.db")}),
            LocalArtifactStore(str(root / "artifacts")),
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        services = [service(root) for _ in range(4)]
        contents = [f"并发内容{i}".encode() for i in range(4)]
        barrier = Barrier(4)

        def run(item):
            svc, content = item
            barrier.wait(timeout=10)
            return svc.adopt(project_id="project-1", logical_source_key="同名.docx", content=content,
                             source_role="project_primary", source_version=f"{contents.index(content) + 1}.0",
                             jurisdiction="CN", mime_type="application/octet-stream",
                             captured_at=datetime(2026, 9, 13, tzinfo=timezone.utc))

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(run, zip(services, contents)))
        reopened = service(root)
        history = reopened.history("project-1")
        revisions = sorted(item.source.storage_revision for item in results)
        ok = revisions == [1, 2, 3, 4] and len(history) == 4
        for item, content in zip(results, contents):
            try:
                if reopened.read_content("project-1", item.source.source.source_artifact_id) != content:
                    ok = False
            except Exception as exc:  # noqa: BLE001
                ok = False
                check("F6 readback error", False, str(exc))
        check("F6 R2: 4-way same-name/different-content adopts keep every revision readable", ok,
              f"revisions={revisions} history={len(history)}")
        # Same event stream integrity: sequences must be 1..4 without duplicates.
        from app.protocol_workflow.agent1.source_identity import STREAM
        with sqlite3.connect(str(root / "product.db")) as conn:
            seqs = [r[0] for r in conn.execute(
                "select sequence from event_stream where project_id=? and stream_id=? order by sequence",
                ("project-1", STREAM))]
        check("F6b event stream sequences strict 1..N", seqs == list(range(1, len(seqs) + 1)), str(seqs))


def probe_f7_omp_credentials_synthetic():
    from app.protocol_workflow.runtime.omp_credentials import OmpCredentialError, resolve_omp_zhipu_key

    def database(path, rows, blocks=()):
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE auth_credentials (id INTEGER PRIMARY KEY, provider TEXT, credential_type TEXT, data TEXT, disabled_cause TEXT)")
            db.execute("CREATE TABLE auth_credential_blocks (credential_id INTEGER, provider_key TEXT, block_scope TEXT, blocked_until_ms INTEGER, updated_at INTEGER)")
            for number, provider, key, source in rows:
                db.execute("INSERT INTO auth_credentials VALUES (?,?,'api_key',?,NULL)",
                           (number, provider, json.dumps({"key": key, "source": source})))
            for number, expiry in blocks:
                db.execute("INSERT INTO auth_credential_blocks VALUES (?, 'zhipu-coding-plan:api_key', '', ?, 0)",
                           (number, expiry))

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "agent.db"
        database(p, [(1, "other", "x", "login"),
                     (2, "zhipu-coding-plan", "SYNTH_ENV_NAME", "login"),
                     (3, "zhipu-coding-plan", "literal-key", "login")])
        before = p.read_bytes()
        check("F7a env-name binding resolves through environ, file untouched",
              resolve_omp_zhipu_key(p, environ={"SYNTH_ENV_NAME": "synthetic-1"}) == "synthetic-1"
              and p.read_bytes() == before)
        check("F7b login pool preferred over later rows when first resolves",
              resolve_omp_zhipu_key(p, environ={}) == "SYNTH_ENV_NAME")
        p2 = Path(tmp) / "cmd.db"
        database(p2, [(1, "zhipu-coding-plan", "!op read:key", "login")])
        try:
            resolve_omp_zhipu_key(p2, environ={})
            check("F7c command binding rejected before dispatch", False, "no error")
        except OmpCredentialError as exc:
            check("F7c command binding rejected before dispatch", str(exc) == "omp_credential_command_binding_unsupported", str(exc))
        p3 = Path(tmp) / "blocked.db"
        database(p3, [(1, "zhipu-coding-plan", "k1", "login"), (2, "zhipu-coding-plan", "k2", "static")],
                 blocks=[(1, 9999999999999)])
        try:
            resolve_omp_zhipu_key(p3, now_ms=1000, environ={})
            check("F7d fully blocked pool fails closed (no static fallback)", False, "no error")
        except OmpCredentialError as exc:
            check("F7d fully blocked pool fails closed (no static fallback)",
                  str(exc) == "omp_credentials_temporarily_blocked", str(exc))
        absent = Path(tmp) / "absent.db"
        try:
            resolve_omp_zhipu_key(absent)
            check("F7e missing store not created", False, "no error")
        except OmpCredentialError:
            check("F7e missing store not created", not absent.exists())


def probe_f8_lazy_factory_credentials_on_call_only():
    with tempfile.TemporaryDirectory() as tmp:
        import app.protocol_workflow.agent1.seed_product as seed_product

        calls = []

        def sentinel():
            calls.append(1)
            return "synthetic-key-only"

        db = Path(tmp) / "product.sqlite"
        opener = _FakeOpener([_FakeResponse(_completion_body(content='{"fields":{}}'))])
        factory = seed_product.create_product_seed_factory(
            storage_config={"backend": "sqlite", "path": str(db)},
            prior_probe_receipt=REPO / "runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json",
            max_input_bytes=100_000, credential_resolver=sentinel, http_opener=opener)
        coordinator = factory("project-one")
        run_id = coordinator.start(prepare_seed_request("延迟凭据", ()))
        check("F8a construction+start resolve no credentials, make no calls",
              not calls and opener.calls == 0)
        result = coordinator.resume(run_id)
        check("F8b credential resolved exactly once at actual dispatch; restored probe reused",
              result["status"] == "needs_information" and len(calls) == 1 and opener.calls == 1,
              f"resolver_calls={len(calls)} opener_calls={opener.calls}")


def probe_f9_dead_owner_cross_process():
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = "tests:tests/protocol_v3/integration:tests/protocol_v3:services/api:packages:."
    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "db.sqlite")
        artifacts = str(Path(tmp) / "artifacts")
        marker = Path(tmp) / "dispatch-entered"
        proc = subprocess.Popen(
            [sys.executable, str(SCRATCH / "dead_owner_child.py"), db, artifacts, str(marker)],
            cwd=REPO, env=env, stdout=subprocess.PIPE, text=True)
        run_id = proc.stdout.readline().strip()
        deadline = time.time() + 30
        while not marker.exists() and time.time() < deadline:
            time.sleep(0.05)
        check("F9a child entered in-flight dispatch (flock held)", marker.exists() and bool(run_id))

        from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator
        config2 = {"backend": "sqlite", "path": db}
        store2 = LocalArtifactStore(artifacts)
        role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_kind == "llm")
        skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions()
                     if s.skill_definition_id == "skill.research-seed-proposal")
        dispatcher = HarnessDispatcher()
        parent_opener = _FakeOpener([_FakeResponse(_completion_body(content='{"fields":{}}'))])

        def parent_coordinator():
            runtime = build_seed_runtime(
                project_id="dead-owner-project",
                uow_factory=build_unit_of_work_factory(config2),
                reservation_repository_factory=build_committed_reservation_repository_factory(config2),
                artifact_store=store2, role_entry=role, skill=skill, dispatcher=dispatcher,
                adapter_factory=lambda **kw: build_zhipu_api_adapter(
                    credential_resolver=_resolver(), http_opener=parent_opener, max_input_bytes=100_000, **kw))
            return SeedCoordinator(project_id="dead-owner-project", branch_id="main",
                                   runtime=runtime, artifact_store=store2)

        live_state = parent_coordinator().read(run_id)
        check("F9b GET during live cross-process dispatch reports running, can_resume false",
              live_state["status"] == "running" and live_state["can_resume"] is False,
              f"status={live_state['status']}")

        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        marker.unlink(missing_ok=True)
        time.sleep(0.3)
        dead_state = parent_coordinator().read(run_id)
        check("F9c GET after owner death reports blocked (not running, not unknown-running)",
              dead_state["status"] == "blocked" and dead_state["can_resume"] is False,
              f"status={dead_state['status']}")
        before = attempt_rows(config2, "dead-owner-project")
        try:
            parent_coordinator().resume(run_id)
            note = "returned"
        except Exception as exc:  # noqa: BLE001
            note = f"raised {type(exc).__name__}"
        after = attempt_rows(config2, "dead-owner-project")
        check("F9d direct resume after owner death never redispatches (no new attempt, no call)",
              parent_opener.calls == 0 and len(before) == len(after),
              f"resume {note}; attempts {len(before)}->{len(after)}; opener={parent_opener.calls}")


def probe_f10_concurrent_resume_regression():
    from probe_helpers import GatedOpener

    class Slow(_FakeOpener):
        def __init__(self, outcomes):
            super().__init__(outcomes)
            self.active = 0

        def open(self, request, timeout=None):
            self.active += 1
            try:
                time.sleep(1.0)
                return super().open(request, timeout=timeout)
            finally:
                self.active -= 1

    with tempfile.TemporaryDirectory() as tmp:
        outcomes = [_FakeResponse(_completion_body(content="probe")),
                    _FakeResponse(_completion_body(content='{"fields":{}}'))]
        config = {"backend": "sqlite", "path": str(Path(tmp) / "db.sqlite")}
        store = LocalArtifactStore(str(Path(tmp) / "artifacts"))
        role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_kind == "llm")
        skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions()
                     if s.skill_definition_id == "skill.research-seed-proposal")
        opener = Slow(outcomes)
        dispatcher = HarnessDispatcher()

        def coordinator():
            runtime = build_seed_runtime(
                project_id="conc-project", uow_factory=build_unit_of_work_factory(config),
                reservation_repository_factory=build_committed_reservation_repository_factory(config),
                artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
                adapter_factory=lambda **kw: build_zhipu_api_adapter(
                    credential_resolver=_resolver(), http_opener=opener, max_input_bytes=100_000, **kw))
            return SeedCoordinator(project_id="conc-project", branch_id="main", runtime=runtime, artifact_store=store)

        prepared = prepare_seed_request("并发回归", ())
        run_id = coordinator().start(prepared)
        results = {}

        def worker(tag):
            try:
                results[tag] = ("ok", coordinator().resume(run_id))
            except Exception as exc:  # noqa: BLE001
                results[tag] = ("exc", type(exc).__name__)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        final = coordinator().read(run_id)
        check("F10 concurrent resume still yields exactly one physical generation",
              opener.calls == 2 and final["status"] == "needs_information" and opener.active == 0,
              f"calls={opener.calls} final={final['status']}")


def probe_f11_root_conflict_window():
    from app.protocol_workflow.graph import GraphPlanBindingError
    with tempfile.TemporaryDirectory() as tmp:
        coordinator, opener, config, _ = make_world(Path(tmp), [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content='{"fields":{}}')),
        ])
        original = prepare_seed_request("冲突窗口", ())
        run_id = coordinator().run_id(original)
        other = prepare_seed_request("冲突窗口", ())
        other_payload = other.to_payload()
        other_payload["user_brief"] = "冲突窗口-已变化"
        coordinator().runtime.start_run(seed_plan("seed-project", "main"), workflow_run_id=run_id,
                                        root_inputs={"research_intake": other_payload})
        try:
            coordinator().runtime.start_run(seed_plan("seed-project", "main"), workflow_run_id=run_id,
                                            root_inputs={"research_intake": original.to_payload()})
            check("F11 runtime fails closed on same-id different-root start", False, "no error")
        except GraphPlanBindingError as exc:
            check("F11 runtime fails closed on same-id different-root start",
                  exc.code == "graph_root_inputs_conflict", exc.code)


def main():
    probe_f1_d1_correction_id_404()
    probe_f2_recover_semantics()
    probe_f3_resume_endpoint_and_blocking()
    probe_f4_legacy_resume()
    probe_f5_pinned_input_across_compiler_change()
    probe_f6_r2_concurrent_adopts()
    probe_f7_omp_credentials_synthetic()
    probe_f8_lazy_factory_credentials_on_call_only()
    probe_f9_dead_owner_cross_process()
    probe_f10_concurrent_resume_regression()
    probe_f11_root_conflict_window()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ==")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
