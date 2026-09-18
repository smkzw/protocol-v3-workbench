"""Real SQLite graph + harness + HTTP composition; provider bytes are synthetic."""
from pathlib import Path
import hashlib
import json
import pytest
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver

ROOT = Path(__file__).resolve().parents[2] / 'config/medical_writing/protocol_v3'


@pytest.mark.parametrize('content, expected, correct', [
    (' {"fields":{}} ', 'needs_information', False),
    ('无法解析的回复', 'needs_structure_correction', False),
    ('无法解析的回复', 'needs_information', True),
])
def test_complete_intake_reaches_model_then_validates_without_repeating_on_reopen(tmp_path, content, expected, correct):
    from app.protocol_workflow.agent1.seed_workflow import build_seed_runtime, seed_plan
    role = next(r for r in load_role_registry(ROOT / 'role_registry.json').roles if r.role_kind == 'llm')
    skill = next(s for s in load_skill_registry(ROOT / 'skill_registry.json').skill_definitions()
                 if s.skill_definition_id == 'skill.research-seed-proposal')
    opener = _FakeOpener([
        _FakeResponse(_completion_body(content='probe')),
        _FakeResponse(_completion_body(content=content)),
        _FakeResponse(_completion_body(content='{"fields":{}}', response_id='corrected-response')),
    ])
    dispatcher = HarnessDispatcher()
    config = {'backend': 'sqlite', 'path': str(tmp_path / 'product.sqlite')}
    prepared = prepare_seed_request('完整资料' * 3000 + '最后一句必须保留', ())

    def runtime():
        return build_seed_runtime(
            project_id='seed-project', uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=LocalArtifactStore(str(tmp_path / 'artifacts')), role_entry=role, skill=skill,
            dispatcher=dispatcher, adapter_factory=lambda **kwargs: build_zhipu_api_adapter(
                credential_resolver=_resolver(), http_opener=opener, max_input_bytes=100_000, **kwargs),
        )

    plan = seed_plan('seed-project', 'branch-main')
    rt = runtime()
    rt.start_run(plan, workflow_run_id='seed-run', root_inputs={'research_intake': prepared.to_payload()})
    completed = rt.run_to_completion('seed-run')
    assert completed.status.value == 'completed'
    output = next(e.payload['output'] for e in rt.read_events('seed-run')
                  if e.event_type == 'graph_node_result' and e.payload['node_id'] == 'seed-validate')
    if correct:
        from app.protocol_workflow.agent1.seed_workflow import seed_correction_inputs
        from app.protocol_workflow.runtime.model_response import read_model_response
        assert output['status'] == 'needs_structure_correction'
        record = read_model_response(LocalArtifactStore(str(tmp_path / 'artifacts')), output['raw_response']['artifact_ref'])
        corrected = seed_correction_inputs(prepared, record, output)
        # Exercise the opposite digest order deterministically, without
        # changing any clinical facts or relying on random reservation ids.
        for nonce in range(1000):
            corrected['correction_context']['ordering_probe'] = nonce
            encoded = json.dumps(corrected['correction_context'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))
            if hashlib.sha256(encoded.encode()).hexdigest() < prepared.input_sha256:
                break
        else:
            pytest.fail('could not construct the intended digest order')
        rt.start_run(seed_plan('seed-project', 'branch-main', correction=True),
                     workflow_run_id='seed-run-correction', root_inputs=corrected)
        rt.run_to_completion('seed-run-correction')
        output = next(e.payload['output'] for e in rt.read_events('seed-run-correction')
                      if e.event_type == 'graph_node_result' and e.payload['node_id'] == 'seed-validate')
        message = json.loads(opener.requests[-1]['data'])['messages'][0]['content']
        assert content in message and 'seed_invalid_json' in message
        assert json.loads(opener.requests[-1]['data'])['model'] == 'glm-5.3-flash'
    assert output['status'] == expected
    assert (output['proposal'] is None) == (expected == 'needs_structure_correction')
    assert '最后一句必须保留' in json.loads(opener.requests[-1]['data'])['messages'][0]['content']
    expected_calls = 3 if correct else 2
    assert opener.calls == expected_calls  # one fake probe, initial generation, optional correction
    reopened = runtime()
    reopened.run_to_completion('seed-run')
    if correct:
        reopened.run_to_completion('seed-run-correction')
    assert opener.calls == expected_calls


def test_correction_is_not_used_for_missing_information_or_repeated_on_its_own_output():
    from app.protocol_workflow.agent1.seed_workflow import seed_correction_inputs
    prepared = prepare_seed_request('', ())
    with pytest.raises(ValueError, match='seed_correction_not_required'):
        seed_correction_inputs(prepared, {}, {'valid': True, 'status': 'needs_information'})
    record = {'receipt': {'input_artifacts': [{'ref': 'correction-context', 'sha256': 'a' * 64}]}}
    with pytest.raises(ValueError, match='seed_correction_budget_exhausted'):
        seed_correction_inputs(prepared, record, {'valid': False, 'status': 'needs_structure_correction'})
