"""Regimen design uses existing SQLite graph, registered harness and raw receipts."""
from pathlib import Path
import json
import pytest
from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver

ROOT = Path(__file__).resolve().parents[2] / "config/medical_writing/protocol_v3"


@pytest.mark.parametrize("malformed", [False, True])
def test_sparse_design_runs_once_with_full_input_and_reopens_without_new_call(tmp_path, malformed):
    from app.protocol_workflow.agent2.subgraph import build_regimen_runtime, regimen_plan
    role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_id == "product-llm")
    skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions() if s.skill_definition_id == "skill.regimen-design-proposal")
    content = json.dumps({"coverage": [], "regimen": None, "questions": ["拟采用哪份给药依据？"]}, ensure_ascii=False)
    if malformed:
        content = "结构损坏的模型原文"
    opener = _FakeOpener([_FakeResponse(_completion_body(content="probe")), _FakeResponse(_completion_body(content=content))])
    dispatcher = HarnessDispatcher()
    config = {"backend": "sqlite", "path": str(tmp_path / "product.sqlite")}
    original = prepare_seed_request("完整说明" * 2000 + "最后一段仍要保留", ())
    prepared = prepare_regimen_request(original, read_seed_candidates(original, {"fields": {}}))
    def runtime():
        return build_regimen_runtime(project_id="design-project", uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=LocalArtifactStore(str(tmp_path / "artifacts")), role_entry=role, skill=skill,
            dispatcher=dispatcher, adapter_factory=lambda **kw: build_zhipu_api_adapter(
                credential_resolver=_resolver(), http_opener=opener, max_input_bytes=100000, **kw))
    rt = runtime()
    rt.start_run(regimen_plan("design-project", "main"), workflow_run_id="regimen-run", root_inputs={"regimen_intake": prepared.to_payload()})
    assert rt.run_to_completion("regimen-run").status.value == "completed"
    events = rt.read_events("regimen-run")
    assert sum(e.event_type == "graph_run_completed" for e in events) == 1
    result = next(e.payload["output"] for e in events if e.event_type == "graph_node_result" and e.payload["node_id"] == "regimen-validate")
    assert result["valid"] is (not malformed)
    assert result["status"] == ("needs_structure_correction" if malformed else "needs_information")
    if malformed:
        assert result["proposal"] is None
        assert result["errors"][0]["code"] == "regimen_invalid_json"
    else:
        assert result["proposal"]["regimen"] is None
    from app.protocol_workflow.runtime.model_response import read_model_response
    record = read_model_response(LocalArtifactStore(str(tmp_path / "artifacts")), result["raw_response"]["artifact_ref"])
    assert record["content"] == content
    assert "最后一段仍要保留" in json.loads(opener.requests[-1]["data"])["messages"][0]["content"]
    assert opener.calls == 2  # synthetic probe and generation only
    runtime().run_to_completion("regimen-run")
    assert opener.calls == 2
    assert runtime().read_events("regimen-run") == events
