"""Child process for the C03 dead-owner probe (scratch-only).

Starts a durable seed run and enters a synthetic in-flight generation that
blocks inside the fake HTTP transport (flock held), then idles so the parent
can SIGKILL it mid-dispatch. Usage: dead_owner_child.py <db> <artifacts>
<marker-file>
"""
import sys
import threading
import time
from pathlib import Path

from app.protocol_workflow.agent1.research_seed import prepare_seed_request
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

sys.path.insert(0, str(Path(__file__).parent))
from probe_helpers import GatedOpener


def main():
    db, artifacts, marker = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    config = {"backend": "sqlite", "path": db}
    store = LocalArtifactStore(artifacts)
    role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_kind == "llm")
    skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions()
                 if s.skill_definition_id == "skill.research-seed-proposal")
    opener = GatedOpener([_FakeResponse(_completion_body(content='{"fields":{}}'))], marker_file=marker)
    dispatcher = HarnessDispatcher()
    runtime = build_seed_runtime(
        project_id="dead-owner-project", uow_factory=build_unit_of_work_factory(config),
        reservation_repository_factory=build_committed_reservation_repository_factory(config),
        artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
        adapter_factory=lambda **kw: build_zhipu_api_adapter(
            credential_resolver=_resolver(), http_opener=opener, max_input_bytes=100_000, **kw),
    )
    coordinator = SeedCoordinator(project_id="dead-owner-project", branch_id="main",
                                  runtime=runtime, artifact_store=store)
    prepared = prepare_seed_request("死进程占用中的整理", ())
    run_id = coordinator.start(prepared)
    print(run_id, flush=True)
    worker = threading.Thread(target=coordinator.resume, args=(run_id,), daemon=True)
    worker.start()
    worker.join(timeout=120)  # parent kills us long before this returns


if __name__ == "__main__":
    main()
