"""Coordinator reuses the real graph and persisted receipts on reopen."""
import pytest
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.agent1.seed_workflow import build_seed_runtime
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from test_seed_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver


@pytest.mark.parametrize('first,second,calls,status', [
    ('{"fields":{}}', None, 2, 'needs_information'),
    ('bad json', '{"fields":{}}', 3, 'needs_information'),
    ('bad json', 'still bad', 3, 'needs_structure_correction'),
    (TimeoutError('synthetic provider timeout'), None, 2, 'blocked'),
    ('bad json', TimeoutError('synthetic correction timeout'), 3, 'blocked'),
])
def test_reopen_reuses_original_and_single_correction(tmp_path, first, second, calls, status):
    from app.protocol_workflow.agent1.seed_coordinator import SeedCoordinator
    role = next(r for r in load_role_registry(ROOT / 'role_registry.json').roles if r.role_kind == 'llm')
    skill = next(s for s in load_skill_registry(ROOT / 'skill_registry.json').skill_definitions()
                 if s.skill_definition_id == 'skill.research-seed-proposal')
    replies = ['probe', first] + ([second] if second is not None else [])
    opener = _FakeOpener([reply if isinstance(reply, Exception) else _FakeResponse(_completion_body(content=reply, response_id=f'reply-{i}'))
                         for i, reply in enumerate(replies)])
    dispatcher = HarnessDispatcher()
    config = {'backend': 'sqlite', 'path': str(tmp_path / 'db.sqlite')}
    store = LocalArtifactStore(str(tmp_path / 'artifacts'))
    def coordinator():
        rt = build_seed_runtime(project_id='seed-project', uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store, role_entry=role, skill=skill, dispatcher=dispatcher,
            adapter_factory=lambda **kw: build_zhipu_api_adapter(credential_resolver=_resolver(), http_opener=opener, max_input_bytes=100_000, **kw))
        return SeedCoordinator(project_id='seed-project', branch_id='main', runtime=rt, artifact_store=store)
    prepared = prepare_seed_request('仅给出建议，不代表确认。', ())
    queued = coordinator().start(prepared)
    assert opener.calls == 0
    assert coordinator().read(queued)['status'] == 'running'
    assert opener.calls == 0
    initial = coordinator().resume(queued)
    assert initial['status'] == status
    assert initial['correction_run_id'] is not None if second is not None else initial['correction_run_id'] is None
    assert opener.calls == calls
    assert coordinator().execute(prepared) == initial
    assert opener.calls == calls
