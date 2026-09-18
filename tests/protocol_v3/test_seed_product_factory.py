import pytest
"""Production composition with historical probe and synthetic transport only."""
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_seed_workflow_integration import ROOT
from app.protocol_workflow.agent1.research_seed import prepare_seed_request


def test_product_factory_is_lazy_and_restores_prior_probe_before_generation(tmp_path):
    from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
    db = tmp_path / 'product.sqlite'
    calls = []
    def credentials():
        calls.append('resolved-in-memory')
        return 'synthetic-only-key'
    opener = _FakeOpener([_FakeResponse(_completion_body(content='{"fields":{}}'))])
    prior = ROOT.parents[2] / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json'
    factory = create_product_seed_factory(
        storage_config={'backend': 'sqlite', 'path': str(db)},
        prior_probe_receipt=prior, max_input_bytes=100_000,
        credential_resolver=credentials, http_opener=opener,
    )
    assert not db.exists()
    assert not calls and opener.calls == 0
    coordinator = factory('project-one')
    run_id = coordinator.start(prepare_seed_request('保留原说明', ()))
    assert not calls and opener.calls == 0
    result = coordinator.resume(run_id)
    assert result['status'] == 'needs_information'
    assert opener.calls == 1  # generation only: the successful old probe is reused
    assert len(calls) == 1
    assert factory('project-one').resume(run_id) == result
    assert opener.calls == 1 and len(calls) == 1

@pytest.mark.parametrize("finish_during_read", [False, True])
def test_read_during_live_generation_reports_progress_not_unknown(tmp_path, finish_during_read):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
    entered, release = Event(), Event()
    class BlockingOpener(_FakeOpener):
        def open(self, request, timeout=None):
            entered.set()
            assert release.wait(5), 'test release was not signalled'
            return super().open(request, timeout)
    opener = BlockingOpener([_FakeResponse(_completion_body(content='{"fields":{}}'))])
    prior = ROOT.parents[2] / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json'
    factory = create_product_seed_factory(
        storage_config={'backend': 'sqlite', 'path': str(tmp_path / 'live.db')},
        prior_probe_receipt=prior, max_input_bytes=100_000,
        credential_resolver=lambda: 'synthetic-key', http_opener=opener,
    )
    run_id = factory('project-one').start(prepare_seed_request('实际调用进行中', ()))
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(factory('project-one').resume, run_id)
        try:
            assert entered.wait(5)
            reader = factory('project-one')
            if finish_during_read:
                original = reader.runtime.node_has_live_dispatch
                def finish_then_probe(*args):
                    release.set()
                    result.result(timeout=5)
                    return original(*args)
                reader.runtime.node_has_live_dispatch = finish_then_probe
            state = reader.read(run_id)
            assert state['status'] == ('needs_information' if finish_during_read else 'running')
            assert state['can_resume'] is False
        finally:
            release.set()
        assert result.result(timeout=5)['status'] == 'needs_information'
    assert opener.calls == 1
