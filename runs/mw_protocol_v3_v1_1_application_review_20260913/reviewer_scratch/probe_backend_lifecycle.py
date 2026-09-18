"""C03 independent backend lifecycle probes (scratch-only).

Each probe builds its own temp SQLite DB + synthetic HTTP opener; no live
service, no product credential, no repo source mutation.
Run: PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:tests/protocol_v3/integration:tests/protocol_v3:services/api:packages:. \
     runs/mw_protocol_v3_1r_integration_20260905/venv/bin/python runs/.../reviewer_scratch/probe_backend_lifecycle.py
"""
import json
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator, prepare_current_seed
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
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _FakeSink, _completion_body, _resolver

REPO = Path(__file__).resolve().parents[3]
RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" :: {detail}" if detail else ""))


class SlowOpener(_FakeOpener):
    """Adds a wall-clock delay to every physical call (concurrency probe)."""

    def __init__(self, outcomes, delay=0.0):
        super().__init__(outcomes)
        self.delay = delay
        self.active = 0
        self.max_active = 0

    def open(self, request, timeout=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            return super().open(request, timeout=timeout)
        finally:
            self.active -= 1


def make_world(tmp, outcomes, *, delay=0.0, dispatcher=None):
    config = {"backend": "sqlite", "path": str(tmp / "db.sqlite")}
    store = LocalArtifactStore(str(tmp / "artifacts"))
    role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_kind == "llm")
    skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions()
                 if s.skill_definition_id == "skill.research-seed-proposal")
    opener = SlowOpener(outcomes, delay=delay)
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


def event_count(config, project_id, run_id):
    with sqlite3.connect(config["path"]) as conn:
        row = conn.execute(
            "select count(*) from event_stream where project_id=? and stream_id=?", (project_id, run_id)
        ).fetchone()
        return row[0] if row else None


def reservation_rows(config, project_id):
    with sqlite3.connect(config["path"]) as conn:
        names = [r[1] for r in conn.execute("pragma table_info(execution_reservation)")]
        if not names:
            return []
        rows = conn.execute("select * from execution_reservation where project_id=?", (project_id,)).fetchall()
        return [dict(zip(names, row)) for row in rows]


def probe_a_start_persists_before_response():
    with tempfile.TemporaryDirectory() as tmp:
        coord, opener, config, _ = make_world(Path(tmp), [_FakeResponse(_completion_body(content="probe"))])
        prepared = prepare_seed_request("brief", ())
        run_id = coord().start(prepared)
        check("A1 start persists run before any dispatch", event_count(config, "seed-project", run_id) >= 1
              and opener.calls == 0)
        state = coord().read(run_id)
        check("A2 read after start shows running, zero effects",
              state["status"] == "running" and opener.calls == 0)
        before = event_count(config, "seed-project", run_id)
        for _ in range(5):
            coord().read(run_id)
        check("A3 repeated GET leaves event count unchanged",
              event_count(config, "seed-project", run_id) == before and opener.calls == 0)
        reservations = reservation_rows(config, "seed-project")
        check("A4 repeated GET creates no reservations", len(reservations) == 0)


def probe_b_same_input_reuse_and_correction_once():
    with tempfile.TemporaryDirectory() as tmp:
        outcomes = [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content="bad json")),
            _FakeResponse(_completion_body(content='{"fields":{}}')),
        ]
        coord, opener, config, _ = make_world(Path(tmp), outcomes)
        prepared = prepare_seed_request("brief", ())
        run_id = coord().start(prepared)
        first = coord().resume(run_id)
        check("B1 invalid initial -> exactly one correction, then needs_information",
              first["status"] == "needs_information" and first["correction_run_id"] is not None
              and opener.calls == 3)
        again = coord().execute(prepared)
        check("B2 same-input re-execute reuses both runs without new calls",
              again == first and opener.calls == 3)
        restart = coord().start(prepared)
        check("B3 restart returns the same run_id", restart == run_id and opener.calls == 3)


def probe_c_crash_between_initial_and_correction():
    with tempfile.TemporaryDirectory() as tmp:
        outcomes = [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content="bad json", response_id="initial-only")),
            _FakeResponse(_completion_body(content='{"fields":{}}', response_id="correction-after-crash")),
        ]
        coord, opener, config, _ = make_world(Path(tmp), outcomes)
        prepared = prepare_seed_request("brief", ())
        run_id = coord().start(prepared)
        # Simulated crash: only the initial run executes, process dies before
        # the coordinator could schedule or run the correction.
        coord().runtime.run_to_completion(run_id)
        state = coord().read(run_id)
        check("C1 crash window observable: needs_structure_correction, correction None",
              state["status"] == "needs_structure_correction" and state["correction_run_id"] is None
              and opener.calls == 2)
        # Recovery: a later POST-shaped resume re-executes from pinned inputs.
        recovered = coord().resume(run_id)
        check("C2 recovery runs exactly the missing correction",
              recovered["status"] == "needs_information" and opener.calls == 3)


def probe_d_timeouts_not_redispatched():
    with tempfile.TemporaryDirectory() as tmp:
        # Initial dispatch times out (unknown outcome).
        outcomes = [
            _FakeResponse(_completion_body(content="probe")),
            TimeoutError("synthetic initial timeout"),
        ]
        coord, opener, config, _ = make_world(Path(tmp), outcomes)
        prepared = prepare_seed_request("brief", ())
        run_id = coord().start(prepared)
        state = coord().resume(run_id)
        check("D1 initial timeout -> blocked, no correction",
              state["status"] == "blocked" and state["correction_run_id"] is None and opener.calls == 2)
        state2 = coord().execute(prepared)
        check("D2 re-execute after blocked outcome does not redispatch",
              state2["status"] == "blocked" and opener.calls == 2)
    with tempfile.TemporaryDirectory() as tmp:
        # Correction dispatch times out.
        outcomes = [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content="bad json")),
            TimeoutError("synthetic correction timeout"),
        ]
        coord, opener, config, _ = make_world(Path(tmp), outcomes)
        prepared = prepare_seed_request("brief", ())
        run_id = coord().start(prepared)
        state = coord().resume(run_id)
        check("D3 correction timeout -> blocked, correction id recorded",
              state["status"] == "blocked" and state["correction_run_id"] is not None and opener.calls == 3)
        state2 = coord().execute(prepared)
        check("D4 re-execute after blocked correction does not redispatch",
              state2["status"] == "blocked" and opener.calls == 3)


def probe_e_concurrent_double_execute_real_sqlite():
    with tempfile.TemporaryDirectory() as tmp:
        outcomes = [
            _FakeResponse(_completion_body(content="probe")),
            _FakeResponse(_completion_body(content='{"fields":{}}')),
        ]
        shared_dispatcher = HarnessDispatcher()
        coord, opener, config, _ = make_world(Path(tmp), outcomes, delay=1.2, dispatcher=shared_dispatcher)
        prepared = prepare_seed_request("brief", ())
        run_id = coord().start(prepared)

        results = {}

        def worker(tag):
            try:
                results[tag] = ("ok", coord().resume(run_id))
            except Exception as exc:  # contended path raises a typed GraphRunError
                results[tag] = ("exc", f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        statuses = {tag: value[0] for tag, value in results.items()}
        final = coord().read(run_id)
        check("E1 concurrent resume -> exactly one physical generation",
              opener.calls == 2, f"calls={opener.calls} statuses={statuses} final={final['status']}")
        check("E2 no overlapping physical HTTP calls", opener.max_active == 1,
              f"max_active={opener.max_active}")
        check("E3 run converges to terminal after contention",
              final["status"] in {"needs_information", "ready_for_review", "needs_structure_correction"},
              f"final={final['status']}")
        ok_workers = [tag for tag, value in results.items() if value[0] == "ok"]
        check("E4 at least one worker completed the run", len(ok_workers) >= 1, f"statuses={statuses}")


def probe_f_selection_order_and_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        sys.path.insert(0, str(Path(__file__).parent))
        from test_source_identity_product import service, adopt
        from test_writing_reference_docx import build_docx, paragraph_xml

        svc = service(Path(tmp))
        one = adopt(svc, build_docx(paragraph_xml("甲句")), logical_source_key="甲")
        two = adopt(svc, build_docx(paragraph_xml("乙句")), logical_source_key="乙", source_role="regulatory_or_guideline")
        ids = [one.current.source.source_artifact_id, two.current.source.source_artifact_id]
        a = prepare_current_seed(svc, "project-1", "意图", ids)
        b = prepare_current_seed(svc, "project-1", "意图", list(reversed(ids)) + [ids[0]])
        check("F1 selection order and duplicate ids do not change the seed",
              a == b and a.input_sha256 == b.input_sha256)
        # A historical (superseded) artifact id must fail closed.
        old = adopt(svc, build_docx(paragraph_xml("旧版")))
        adopt(svc, build_docx(paragraph_xml("新版")), source_version="2.0")
        try:
            prepare_current_seed(svc, "project-1", "", [old.current.source.source_artifact_id])
            check("F2 superseded id rejected", False, "no error raised")
        except ValueError as exc:
            check("F2 superseded id rejected", str(exc) == "seed_source_selection_stale", str(exc))


def probe_g_real_receipt_restored_policy():
    from app.protocol_workflow.runtime.restored_probe import RestoredZhipuProbePolicy

    receipt = REPO / "runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json"
    policy = RestoredZhipuProbePolicy(receipt)
    import hashlib
    raw = receipt.read_bytes()
    check("G1 restored policy pins the real receipt hash",
          policy.evidence["record_sha256"] == hashlib.sha256(raw).hexdigest())
    check("G2 effective effort recorded as not reported",
          policy.evidence["effective_reasoning_effort"] == "not_reported_by_server")
    # A dispatch under the pinned identity must not add a probe call.
    opener = _FakeOpener([_FakeResponse(_completion_body(content="x"))])
    adapter = build_zhipu_api_adapter(credential_resolver=_resolver(), output_sink=_FakeSink(), http_opener=opener)
    ok = HarnessDispatcher(probe_policy=policy).dispatch(
        request=__import__("test_zhipu_product_transport", fromlist=["_glm_request"])._glm_request(),
        adapter=adapter)
    check("G3 restored policy: generation dispatch makes exactly one call (no new probe)",
          ok.success and opener.calls == 1, f"calls={opener.calls}")
    # A mismatching receipt must fail closed.
    bad = Path(tempfile.mkdtemp()) / "bad.json"
    bad.write_text(json.dumps({"status": "failed", "physical_calls": 1, "provider": "zhipu-coding-plan",
                               "requested_model": "glm-5.3-flash", "observed_model": "glm-5.3-flash",
                               "requested_reasoning_effort": "max"}))
    try:
        RestoredZhipuProbePolicy(bad)
        check("G4 mismatching receipt rejected", False, "no error raised")
    except ValueError as exc:
        check("G4 mismatching receipt rejected", str(exc) == "prior_product_probe_does_not_match_profile", str(exc))


def main():
    probe_a_start_persists_before_response()
    probe_b_same_input_reuse_and_correction_once()
    probe_c_crash_between_initial_and_correction()
    probe_d_timeouts_not_redispatched()
    probe_e_concurrent_double_execute_real_sqlite()
    probe_f_selection_order_and_duplicates()
    probe_g_real_receipt_restored_policy()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n== {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed ==")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
