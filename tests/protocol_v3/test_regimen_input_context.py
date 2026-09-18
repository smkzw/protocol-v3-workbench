"""The adopted recommendation must describe everything its producer read."""
import hashlib
import pytest
from test_clinical_design_worker import prepared_reference
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.agent2.clinical_worker import PreparedRegimenRequest


def test_context_carries_full_source_seed_and_generation_identity():
    from app.protocol_workflow.agent2.input_context import regimen_input_context
    prepared, _ = prepared_reference()
    context = regimen_input_context(prepared)
    payload = prepared.to_payload()
    assert context['source_intake_sha256'] == payload['seed_proposal']['input_sha256']
    assert context['seed_proposal_sha256'] == hashlib.sha256(canonical_json(payload['seed_proposal']).encode()).hexdigest()
    assert context['source_artifacts'] == [{'source_artifact_id': s['source_artifact_id'],
        'content_sha256': s['content_sha256']} for s in payload['source_intake']['sources']]
    assert context['user_brief'] == payload['source_intake']['user_brief']
    assert 'intervention.dose_regimen' not in context


def test_new_seed_content_changes_context_without_fabricating_new_source_identity():
    from app.protocol_workflow.agent2.input_context import regimen_input_context
    prepared, _ = prepared_reference()
    payload = prepared.to_payload()
    payload['seed_proposal']['user_brief'] += '（新的整理注释）'
    text = canonical_json(payload)
    changed = PreparedRegimenRequest(text, hashlib.sha256(text.encode()).hexdigest())
    original, revised = regimen_input_context(prepared), regimen_input_context(changed)
    assert original['source_intake_sha256'] == revised['source_intake_sha256']
    assert original['seed_proposal_sha256'] != revised['seed_proposal_sha256']


def test_mismatched_pinned_source_material_is_not_an_equivalent_input():
    from app.protocol_workflow.agent2.input_context import regimen_input_context
    prepared, _ = prepared_reference()
    payload = prepared.to_payload()
    payload['source_intake']['user_brief'] += ' changed'
    text = canonical_json(payload)
    changed = PreparedRegimenRequest(text, hashlib.sha256(text.encode()).hexdigest())
    with pytest.raises(ValueError, match='source_input_identity_mismatch'):
        regimen_input_context(changed)
