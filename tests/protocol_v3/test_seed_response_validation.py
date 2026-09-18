"""Content errors are correction results, not unknown provider outcomes."""
import hashlib
import json
import pytest
from app.protocol_workflow.agent1.research_seed import prepare_seed_request


def response(request, content):
    return {'content': content, 'receipt': {
        'provider_session_id': 'response-one', 'output_sha256': hashlib.sha256(content.encode()).hexdigest(),
        'input_artifacts': [{'ref': 'intake', 'sha256': request.input_sha256}],
    }}


@pytest.mark.parametrize('content, code', [
    ('不是JSON', 'seed_invalid_json'), ('[]', 'seed_output_object_required'),
    ('{"fields":{"invented":[]}}', 'seed_fields_invalid'),
])
def test_content_failure_keeps_raw_receipt_and_requests_structure_correction(content, code):
    from app.protocol_workflow.agent1.seed_validation import validate_seed_response
    request = prepare_seed_request('准备一个研究', ())
    result = validate_seed_response(request, response(request, content), artifact_ref='response:revision:1')
    assert result['status'] == 'needs_structure_correction'
    assert result['valid'] is False
    assert result['errors'][0]['code'] == code
    assert result['raw_response']['provider_session_id'] == 'response-one'
    assert result['proposal'] is None


def test_missing_information_is_valid_sparse_output_and_does_not_trigger_regeneration():
    from app.protocol_workflow.agent1.seed_validation import validate_seed_response
    request = prepare_seed_request('', ())
    result = validate_seed_response(request, response(request, json.dumps({'fields': {}})),
                                    artifact_ref='response:revision:1')
    assert result['valid'] is True
    assert result['status'] == 'needs_information'
    assert len(result['proposal']['missing_fields']) == 8
    assert result['proposal']['canonical'] == {}
