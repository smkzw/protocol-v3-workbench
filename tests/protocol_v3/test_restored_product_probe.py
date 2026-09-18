"""Reuse the recorded first-use probe instead of spending another product call."""
import json
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver, _FakeSink, _glm_request


def test_restored_success_skips_probe_but_still_sends_actual_generation(tmp_path):
    from app.protocol_workflow.runtime.restored_probe import RestoredZhipuProbePolicy
    path = tmp_path / 'verified-probe.json'
    path.write_text(json.dumps({
        'status': 'succeeded', 'physical_calls': 1, 'provider': 'zhipu-coding-plan',
        'requested_model': 'glm-5.3-flash', 'observed_model': 'glm-5.3-flash',
        'requested_reasoning_effort': 'max', 'effective_reasoning_effort': 'not_reported_by_server',
    }))
    policy = RestoredZhipuProbePolicy(path)
    opener = _FakeOpener([_FakeResponse(_completion_body())])
    adapter = build_zhipu_api_adapter(credential_resolver=_resolver(), output_sink=_FakeSink(), http_opener=opener)
    result = HarnessDispatcher(probe_policy=policy).dispatch(request=_glm_request(), adapter=adapter)
    assert result.success
    assert opener.calls == 1
    assert adapter.probe_state.receipts == ()
    assert policy.evidence['effective_reasoning_effort'] == 'not_reported_by_server'
    policy.clear(adapter.identity)
    assert HarnessDispatcher(probe_policy=policy).dispatch(request=_glm_request(), adapter=adapter).success
    assert opener.calls == 3  # only an explicit cache reset permits a new fake probe
