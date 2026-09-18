"""Keep completion content and its work receipt in one existing-store artifact."""
from datetime import datetime
import hashlib
import json

from app.protocol_workflow.ports.artifacts import ArtifactStore


def persist_model_response(store: ArtifactStore, logical_key: str, content: str,
                           receipt: dict, *, created_at: datetime) -> str:
    if hashlib.sha256(content.encode('utf-8')).hexdigest() != receipt['output_sha256']:
        raise ValueError('model_response_content_hash_mismatch')
    envelope = {'schema': 'model_response.v1', 'content': content, 'receipt': receipt}
    encoded = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    metadata = store.store(logical_key, encoded, media_type='application/json', created_at=created_at)
    return f'{metadata.logical_key}:revision:{metadata.revision}'


def read_model_response(store: ArtifactStore, artifact_ref: str) -> dict:
    key, revision = artifact_ref.rsplit(':revision:', 1)
    stored = store.read(key, revision=int(revision))
    envelope = json.loads(stored.content)
    if envelope.get('schema') != 'model_response.v1':
        raise ValueError('model_response_schema_mismatch')
    if hashlib.sha256(envelope['content'].encode('utf-8')).hexdigest() != envelope['receipt']['output_sha256']:
        raise ValueError('model_response_content_hash_mismatch')
    return envelope
