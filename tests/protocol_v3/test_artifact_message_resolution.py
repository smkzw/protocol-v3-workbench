"""Complete source messages and aggregate byte accounting, without a provider."""
import hashlib

import pytest
from app.protocol_workflow.runtime.artifact_messages import resolve_artifact_messages


def material(texts):
    return [{'ref': ref, 'sha256': hashlib.sha256(text.encode()).hexdigest(), 'snippet': '摘要'}
            for ref, text in texts.items()]


def test_complete_text_and_unicode_byte_boundary():
    texts = {'source': '正文' * 5000 + '最后一个关键事实'}
    artifacts = material(texts)
    messages = resolve_artifact_messages(artifacts, lambda ref, sha: texts[ref], max_input_bytes=100_000)
    assert texts['source'] in messages[0]['content'] and '摘要' not in messages[0]['content']
    size = len(messages[0]['content'].encode())
    assert resolve_artifact_messages(artifacts, lambda ref, sha: texts[ref], max_input_bytes=size) == messages
    with pytest.raises(ValueError, match='input budget exceeded'):
        resolve_artifact_messages(artifacts, lambda ref, sha: texts[ref], max_input_bytes=size - 1)


def test_multiple_documents_share_one_budget():
    texts = {'one': 'a' * 600, 'two': 'b' * 600}
    for artifact in material(texts):
        resolve_artifact_messages([artifact], lambda ref, sha: texts[ref], max_input_bytes=1000)
    with pytest.raises(ValueError, match='input budget exceeded'):
        resolve_artifact_messages(material(texts), lambda ref, sha: texts[ref], max_input_bytes=1000)


def test_reading_wrong_revision_does_not_mislabel_the_text():
    with pytest.raises(ValueError, match='artifact content hash'):
        resolve_artifact_messages(material({'source': 'new'}), lambda ref, sha: 'old', max_input_bytes=1000)
