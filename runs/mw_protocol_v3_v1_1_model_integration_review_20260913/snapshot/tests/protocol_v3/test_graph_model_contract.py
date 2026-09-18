"""Model nodes persist the contract actually handed to their executor."""
from app.protocol_workflow.graph import GraphRuntime
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory, build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import ReasoningEffort
from test_graph_runtime import _probe_plan, _root_inputs, _StepClock, _PROJ
import pytest


@pytest.mark.parametrize('provider_receipt', [False, True])
def test_model_contract_reaches_service_and_survives_reopen_without_second_call(tmp_path, provider_receipt):
    config = {'backend': 'sqlite', 'path': str(tmp_path / 'graph.sqlite')}
    calls = []

    def model_contract(base):
        return base.model_copy(update={
            'harness': 'direct-api', 'provider': 'zhipu-coding-plan',
            'model': 'glm-5.3-flash', 'reasoning_effort': ReasoningEffort.MAX,
            'allowed_providers': ('zhipu-coding-plan',), 'allowed_regions': ('cn',),
        })

    def service(request):
        assert request.execution_contract.model == 'glm-5.3-flash'
        assert request.execution_contract.reasoning_effort is ReasoningEffort.MAX
        calls.append(request.execution_contract.model_dump(mode='json'))
        payload = {'candidate': 'synthetic-only'}
        if provider_receipt:
            from app.protocol_workflow.graph.ports import ConfiguredNodeServiceResult
            return ConfiguredNodeServiceResult(payload=payload, provider_session_id='completion-test')
        return payload

    def runtime():
        return GraphRuntime(
            project_id=_PROJ, uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            services={'draft_node': service}, clock=_StepClock(),
            execution_contract_factories={'draft_node': model_contract},
        )

    plan = _probe_plan()
    run_id = 'model-contract-test'
    rt = runtime()
    rt.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
    rt.advance(run_id)
    assert len(calls) == 1
    results = [e for e in rt.read_events(run_id) if 'execution_contract' in e.payload]
    assert len(results) == 1
    assert results[0].payload['execution_contract'] == calls[0]
    if provider_receipt:
        assert rt.reservation_attempts(run_id, 'draft_node')[0].provider_session_id == 'completion-test'
    reopened = runtime()
    reopened.load_run(plan, run_id)
    reopened.advance(run_id)
    assert len(calls) == 1
