"""A returned completion stays attributable even before its graph result commits."""
from datetime import datetime, timezone
from functools import partial
import pytest
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver, _glm_request


@pytest.mark.parametrize('content', ['{"fields":{}}', '这次返回的不是JSON。'])
def test_response_bytes_and_work_receipt_can_be_recovered_after_reopening_store(tmp_path, content):
    from app.protocol_workflow.runtime.model_response import persist_model_response, read_model_response
    root = str(tmp_path / 'artifacts')
    key = 'research-seed/project-a/reservation-one'
    store = LocalArtifactStore(root)
    sink = partial(persist_model_response, store, key, created_at=datetime.now(timezone.utc))
    adapter = build_zhipu_api_adapter(
        credential_resolver=_resolver(), receipt_sink=sink,
        http_opener=_FakeOpener([_FakeResponse(_completion_body(content=content))]),
    )
    request = _glm_request()
    receipt = adapter.dispatch(request)
    reopened = LocalArtifactStore(root)
    record = read_model_response(reopened, receipt.output_artifact_ref)
    assert record['content'] == content
    assert record['receipt']['provider_session_id'] == receipt.provider_session_id == 'chatcmpl-test-1'
    assert record['receipt']['output_sha256'] == receipt.output_sha256
    assert record['receipt']['logical_call_id'] == request.logical_call_id
    assert record['receipt']['idempotency_key'] == request.idempotency_key
    assert record['receipt']['input_artifacts'][0]['sha256'] == request.input_artifacts[0].sha256
    # Logical work can find the receipt without a graph event or an anonymous blob scan.
    assert len(reopened.list_revisions(key)) == 1
