"""Actual transport message body must contain complete bound material, not a snippet."""
import hashlib
import json

import pytest
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter, ZhipuTransportError
from app.protocol_workflow.runtime.harness import ArtifactRef, HarnessDispatcher, build_request
from test_zhipu_product_transport import (
    _FakeOpener, _FakeResponse, _FakeSink, _completion_body, _resolver,
    _glm_role_entry, _node_contract, _skill,
)


def request_for(text):
    digest = hashlib.sha256(text.encode()).hexdigest()
    return build_request(
        node_contract=_node_contract().model_copy(update={'input_artifact_hashes': (digest,)}),
        skill=_skill(), role_entry=_glm_role_entry(),
        artifacts=(ArtifactRef(ref='seed', sha256=digest, snippet='只有摘要'),), selected_region='cn',
    )


def test_complete_source_and_schema_reach_actual_http_body_through_harness():
    full = json.dumps({'instruction': '提取研究设计', 'source': '原文内容' * 3000 + '末尾关键剂量',
                       'output_schema': {'type': 'object', 'required': ['fields']}}, ensure_ascii=False)
    opener = _FakeOpener([_FakeResponse(_completion_body())])
    resolved = []

    def resolve(ref, sha):
        resolved.append((ref, sha))
        return full

    adapter = build_zhipu_api_adapter(credential_resolver=_resolver(), output_sink=_FakeSink(),
                                      http_opener=opener, artifact_text_resolver=resolve,
                                      max_input_bytes=100_000)
    result = HarnessDispatcher().dispatch(request=request_for(full), adapter=adapter)
    assert result.success
    body = json.loads(opener.requests[-1]['data'])
    actual = body['messages'][0]['content']
    assert full in actual and '末尾关键剂量' in actual and 'output_schema' in actual
    assert '只有摘要' not in actual
    assert len(resolved) == 1  # probe never reads study material


def test_total_input_budget_counts_all_bytes_without_truncating():
    full = '研究资料' * 3000
    opener = _FakeOpener([_FakeResponse(_completion_body())])
    adapter = build_zhipu_api_adapter(credential_resolver=_resolver(), output_sink=_FakeSink(),
                                      http_opener=opener, artifact_text_resolver=lambda ref, sha: full,
                                      max_input_bytes=1000)
    with pytest.raises(ZhipuTransportError, match='input budget'):
        adapter.dispatch(request_for(full))
    assert opener.calls == 0


def test_old_or_wrong_resolved_version_is_not_sent_as_current_material():
    opener = _FakeOpener([_FakeResponse(_completion_body())])
    adapter = build_zhipu_api_adapter(credential_resolver=_resolver(), output_sink=_FakeSink(),
                                      http_opener=opener, artifact_text_resolver=lambda ref, sha: '旧版本',
                                      max_input_bytes=1000)
    with pytest.raises(ZhipuTransportError, match='artifact content hash'):
        adapter.dispatch(request_for('当前版本'))
    assert opener.calls == 0


def test_budget_is_shared_by_all_selected_artifacts():
    texts = {'seed-one': 'a' * 600, 'seed-two': 'b' * 600}
    hashes = tuple(hashlib.sha256(t.encode()).hexdigest() for t in texts.values())
    request = build_request(
        node_contract=_node_contract().model_copy(update={'input_artifact_hashes': hashes}),
        skill=_skill(), role_entry=_glm_role_entry(),
        artifacts=tuple(ArtifactRef(ref=ref, sha256=sha) for ref, sha in zip(texts, hashes)),
        selected_region='cn',
    )
    opener = _FakeOpener([_FakeResponse(_completion_body())])
    adapter = build_zhipu_api_adapter(credential_resolver=_resolver(), output_sink=_FakeSink(),
                                      http_opener=opener, artifact_text_resolver=lambda ref, sha: texts[ref],
                                      max_input_bytes=1000)
    with pytest.raises(ZhipuTransportError, match='input budget'):
        adapter.dispatch(request)
    assert opener.calls == 0
