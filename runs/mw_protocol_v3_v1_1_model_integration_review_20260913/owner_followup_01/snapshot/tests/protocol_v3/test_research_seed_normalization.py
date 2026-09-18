"""Sparse intake stays proposed and binds candidate quotes to real source units."""
from datetime import datetime, timezone
import hashlib

import pytest

from packages.contracts.workbench_contracts.protocol_v3 import SourceArtifact
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
from test_writing_reference_docx import build_docx, paragraph_xml


def source(role='project_primary'):
    payload = build_docx(paragraph_xml('计划比较100 mg和300 mg两个剂量。'))
    artifact = SourceArtifact(source_artifact_id='source-test', logical_source_key='ib',
                              content_sha256=hashlib.sha256(payload).hexdigest(), source_role=role,
                              source_version='1', jurisdiction='CN', mime_type='application/docx',
                              captured_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
    return artifact, parse_docx(payload)


def answer(request, *, basis='source', quote='100 mg和300 mg', field='anticipated_dose'):
    unit = request.to_payload()['sources'][0]['units'][0]
    return {'fields': {field: [{'raw': quote, 'candidate': ['100 mg', '300 mg'],
                               'confidence': 0.95, 'reason': '源文件列出两个剂量。',
                               'basis': basis, 'references': [{
                                   'source_artifact_id': 'source-test', 'locator': unit['locator'],
                                   'quote': quote,
                               }]}]}}


def test_sparse_intent_does_not_require_eight_nonempty_fields():
    request = prepare_seed_request('希望研究慢性荨麻疹', ())
    result = read_seed_candidates(request, {'fields': {}})
    assert result['canonical'] == {}
    assert len(result['missing_fields']) == 8
    assert result['user_brief'] == '希望研究慢性荨麻疹'
    assert result['status'] == 'needs_information'


def test_compiled_request_contains_complete_output_schema_with_optional_fields():
    schema = prepare_seed_request('', ()).to_payload()['output_schema']
    fields = schema['properties']['fields']
    assert schema['required'] == ['fields']
    assert fields.get('required', []) == []
    assert len(fields['properties']) == 8
    assert fields['additionalProperties'] is False
    candidate = schema['$defs']['SeedCandidate']
    assert 'raw' in candidate['required'] and 'basis' in candidate['required']
    assert candidate['properties']['references']['items']['$ref'] == '#/$defs/_Reference'
    assert 'locator' in schema['$defs']['_Reference']['required']
    array = next(s for s in candidate['properties']['candidate']['anyOf'] if s['type'] == 'array')
    assert array['minItems'] == 1


def test_multidose_candidates_remain_proposed_despite_high_confidence():
    request = prepare_seed_request('', (source(),))
    result = read_seed_candidates(request, answer(request))
    field = result['fields']['anticipated_dose'][0]
    assert field['candidate'] == ['100 mg', '300 mg']
    assert field['canonical'] is None and field['requires_confirmation']
    assert field['source_support'] == 'project_material'
    assert result['canonical'] == {}


def test_company_protocol_cannot_become_current_project_fact():
    request = prepare_seed_request('', (source('company_style_only'),))
    field = read_seed_candidates(request, answer(request))['fields']['anticipated_dose'][0]
    assert field['source_support'] == 'reference_only'
    assert field['canonical'] is None


def test_quote_must_be_present_in_the_bound_source_location():
    request = prepare_seed_request('', (source(),))
    with pytest.raises(ValueError, match='seed_source_quote_not_found'):
        read_seed_candidates(request, answer(request, quote='900 mg'))


def test_source_raw_cannot_be_invented_beside_a_valid_reference():
    request = prepare_seed_request('', (source(),))
    output = answer(request)
    output['fields']['anticipated_dose'][0]['raw'] = '900 mg剂量'
    with pytest.raises(ValueError, match='seed_source_raw_not_found'):
        read_seed_candidates(request, output)


def test_user_basis_must_quote_actual_intake_instead_of_an_unseen_fact():
    request = prepare_seed_request('考虑安慰剂对照', ())
    output = {'fields': {'comparator': [{'raw': '阳性药对照', 'candidate': '阳性药',
                                       'confidence': 0.9, 'reason': '用户提出',
                                       'basis': 'user', 'references': []}]}}
    with pytest.raises(ValueError, match='seed_user_quote_not_found'):
        read_seed_candidates(request, output)


def test_source_bytes_and_parser_projection_must_match():
    artifact, parsed = source()
    wrong = artifact.model_copy(update={'content_sha256': '0' * 64})
    with pytest.raises(ValueError, match='seed_source_hash_mismatch'):
        prepare_seed_request('', ((wrong, parsed),))


def test_request_identity_is_stable_for_same_material_and_changes_with_intent():
    material = (source(),)
    assert prepare_seed_request('意图一', material) == prepare_seed_request('意图一', material)
    assert prepare_seed_request('意图一', material).input_sha256 != prepare_seed_request('意图二', material).input_sha256
