"""Model nodes persist the contract actually handed to their executor."""
from app.protocol_workflow.graph import GraphRuntime
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory, build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import ReasoningEffort
from test_graph_runtime import _probe_plan, _root_inputs, _StepClock, _PROJ, _runtime, _sha_of
import pytest


@pytest.mark.parametrize('provider_receipt, crash_after_result', [(False, False), (True, False), (True, True)])
def test_model_contract_reaches_service_and_survives_reopen_without_second_call(tmp_path, provider_receipt, crash_after_result):
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
    if crash_after_result:
        append = rt._append_node_result

        def interrupted(*args, **kwargs):
            append(*args, **kwargs)
            raise SystemExit('interrupted after durable result')

        rt._append_node_result = interrupted
        with pytest.raises(SystemExit):
            rt.advance(run_id)
    else:
        rt.advance(run_id)
    assert len(calls) == 1
    results = [e for e in rt.read_events(run_id) if e.event_type == 'graph_node_result']
    assert len(results) == 1
    assert results[0].payload['execution_contract'] == calls[0]
    reopened = runtime()
    reopened.load_run(plan, run_id)
    reopened.advance(run_id)
    assert len(calls) == 1
    if provider_receipt:
        assert reopened.reservation_attempts(run_id, 'draft_node')[0].provider_session_id == 'completion-test'


def test_unresolved_call_keeps_pre_dispatch_contract_when_configuration_changes(tmp_path):
    config = {'backend': 'sqlite', 'path': str(tmp_path / 'graph.sqlite')}
    invoked = []
    observed_dispatches = []

    def interrupted(request):
        observed_dispatches.extend(e for e in rt.read_events('pinned-model') if e.event_type == 'graph_node_dispatch')
        invoked.append(request.execution_contract.model_dump(mode='json'))
        raise RuntimeError('interrupted after entering the provider boundary')

    def runtime(model):
        return GraphRuntime(
            project_id=_PROJ, uow_factory=build_unit_of_work_factory(config),
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            services={'draft_node': interrupted}, clock=_StepClock(),
            execution_contract_factories={'draft_node': lambda base: base.model_copy(update={
                'model': model, 'provider': 'zhipu-coding-plan', 'harness': 'direct-api',
                'allowed_providers': ('zhipu-coding-plan',), 'allowed_regions': ('cn',),
            })},
        )

    rt = runtime('glm-5.3-flash')
    rt.start_run(_probe_plan(), workflow_run_id='pinned-model', root_inputs=_root_inputs())
    rt.advance('pinned-model')
    assert len(observed_dispatches) == 1
    assert observed_dispatches[0].payload['execution_contract'] == invoked[0]
    reopened = runtime('changed-config-test-only')
    payload = {'raw_artifact_ref': 'verified-result'}
    reopened.resolve_unknown_with_receipt('pinned-model', node_id='draft_node', output=payload,
                                           output_sha256=_sha_of(payload))
    result = next(e for e in reopened.read_events('pinned-model') if e.event_type == 'graph_node_result')
    assert result.payload['execution_contract'] == invoked[0]
    assert len(invoked) == 1


def test_unknown_receipt_adoption_retains_actual_identity_in_event_without_rewriting_ledger(tmp_path):
    calls = []

    def interrupted(request):
        calls.append(request.reservation_id)
        raise RuntimeError('response persistence was interrupted')

    rt = _runtime(tmp_path, {'draft_node': interrupted})
    plan = _probe_plan()
    rt.start_run(plan, workflow_run_id='unknown-model', root_inputs=_root_inputs())
    rt.advance('unknown-model')
    prior_id = rt.reservation_attempts('unknown-model', 'draft_node')[0].provider_session_id
    payload = {'raw_artifact_ref': 'verified-test-result'}
    rt.resolve_unknown_with_receipt(
        'unknown-model', node_id='draft_node', output=payload, output_sha256=_sha_of(payload),
        provider_session_id='actual-recovered-response',
    )
    results = [e for e in rt.read_events('unknown-model') if e.payload.get('recovered_receipt')]
    assert results[0].payload['provider_session_id'] == 'actual-recovered-response'
    assert rt.reservation_attempts('unknown-model', 'draft_node')[0].provider_session_id == prior_id
    assert len(calls) == 1
