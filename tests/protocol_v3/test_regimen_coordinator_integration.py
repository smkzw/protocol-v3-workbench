"""Durable design acknowledgement must not regenerate after restart or timeout."""
import hashlib
import json
import pytest
from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request, PreparedRegimenRequest
from app.protocol_workflow.agent2.subgraph import build_regimen_runtime
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver


@pytest.mark.parametrize("timeout", [False, True])
def test_original_design_request_is_reused_with_no_blind_timeout_retry(tmp_path, timeout):
    from app.protocol_workflow.agent2.coordinator import RegimenCoordinator
    role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_id == "product-llm")
    skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions() if s.skill_definition_id == "skill.regimen-design-proposal")
    reply = TimeoutError("synthetic uncertain outcome") if timeout else _FakeResponse(_completion_body(content=json.dumps({"coverage":[],"regimen":None,"questions":["请明确给药依据"]})))
    opener = _FakeOpener([_FakeResponse(_completion_body(content="probe")), reply])
    dispatcher = HarnessDispatcher()
    config = {"backend":"sqlite", "path":str(tmp_path / "db.sqlite")}
    def coordinator():
        runtime = build_regimen_runtime(project_id="design-project", uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=LocalArtifactStore(str(tmp_path / "artifacts")), role_entry=role, skill=skill,
            dispatcher=dispatcher, adapter_factory=lambda **kw: build_zhipu_api_adapter(credential_resolver=_resolver(),http_opener=opener,max_input_bytes=100000,**kw))
        return RegimenCoordinator(project_id="design-project",branch_id="main",runtime=runtime, artifact_store=LocalArtifactStore(str(tmp_path / "artifacts")))
    intake = prepare_seed_request("整理历史资料", ())
    prepared = prepare_regimen_request(intake, read_seed_candidates(intake,{"fields":{}}))
    run_id = coordinator().start(prepared)
    assert opener.calls == 0
    assert coordinator().read(run_id)["can_resume"] is True
    result = coordinator().resume(run_id)
    assert result["status"] == ("blocked" if timeout else "needs_information")
    assert result["can_resume"] is False
    assert opener.calls == 2
    changed = prepared.to_payload()
    changed["instruction"] += "\n仅改变编译说明"
    text = canonical_json(changed)
    recompiled = PreparedRegimenRequest(text,hashlib.sha256(text.encode()).hexdigest())
    assert coordinator().start(recompiled) == run_id
    assert coordinator().resume(run_id) == result
    assert opener.calls == 2


@pytest.mark.parametrize("second,expected", [
    ('{"coverage":[],"regimen":null,"questions":["需明确给药依据"]}', "needs_information"),
    ("still malformed", "needs_structure_correction"),
    (TimeoutError("synthetic correction timeout"), "blocked"),
])
def test_one_same_model_structural_correction_is_preserved_on_reopen(tmp_path, second, expected):
    from app.protocol_workflow.agent2.coordinator import RegimenCoordinator
    role = next(r for r in load_role_registry(ROOT / "role_registry.json").roles if r.role_id == "product-llm")
    skill = next(s for s in load_skill_registry(ROOT / "skill_registry.json").skill_definitions() if s.skill_definition_id == "skill.regimen-design-proposal")
    replies = ["probe", "malformed", second]
    opener = _FakeOpener([x if isinstance(x, Exception) else _FakeResponse(_completion_body(content=x)) for x in replies])
    dispatcher = HarnessDispatcher()
    config = {"backend":"sqlite","path":str(tmp_path / "db.sqlite")}
    store = LocalArtifactStore(str(tmp_path / "artifacts"))
    def coordinator():
        rt = build_regimen_runtime(project_id="design-project",uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),artifact_store=store,
            role_entry=role,skill=skill,dispatcher=dispatcher,adapter_factory=lambda **kw: build_zhipu_api_adapter(
                credential_resolver=_resolver(),http_opener=opener,max_input_bytes=100000,**kw))
        return RegimenCoordinator(project_id="design-project",branch_id="main",runtime=rt,artifact_store=store)
    original = prepare_seed_request("原始材料不能换掉",())
    prepared = prepare_regimen_request(original, read_seed_candidates(original,{"fields":{}}))
    run_id = coordinator().start(prepared)
    result = coordinator().resume(run_id)
    assert result["status"] == expected
    assert result["correction_run_id"] == run_id + ":correction:1"
    assert result["can_resume"] is False
    assert opener.calls == 3
    message = json.loads(opener.requests[-1]["data"])["messages"][0]["content"]
    assert "原始材料不能换掉" in message and "malformed" in message and "regimen_invalid_json" in message
    assert coordinator().resume(run_id) == result
    assert opener.calls == 3
