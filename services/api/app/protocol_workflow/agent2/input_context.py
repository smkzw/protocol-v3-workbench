"""Exact research input identity; it contains no adopted medical parameters.

This is the producer's actual source/seed read-set. The application must bind
it to the active study context before adoption; generating this value alone
neither persists that context nor invalidates any historical decision.
"""
import hashlib
from app.protocol_workflow.canonical.hashing import canonical_json


def regimen_input_context(prepared):
    payload = prepared.to_payload()
    source_intake = payload['source_intake']
    seed = payload['seed_proposal']
    source_sha = hashlib.sha256(canonical_json(source_intake).encode()).hexdigest()
    if source_sha != seed['input_sha256']:
        raise ValueError('source_input_identity_mismatch')
    return {
        'schema_version': 'research-input-context.v1',
        'user_brief': source_intake['user_brief'],
        'source_intake_sha256': source_sha,
        'seed_proposal_sha256': hashlib.sha256(canonical_json(seed).encode()).hexdigest(),
        'source_artifacts': [
            {'source_artifact_id': source['source_artifact_id'],
             'content_sha256': source['content_sha256']}
            for source in source_intake['sources']
        ],
    }
