"""A persisted option must not invent semantic support or medical admission."""
from datetime import datetime,timezone
from copy import deepcopy
import pytest
from test_clinical_design_worker import prepared_reference
from app.protocol_workflow.agent2.clinical_worker import read_regimen_response


def test_option_has_real_literal_evidence_but_no_invented_medical_admission():
    from app.protocol_workflow.agent2.option_bundle import build_regimen_option_bundle
    prepared,output=prepared_reference()
    proposal=read_regimen_response(prepared,output)
    bundle=build_regimen_option_bundle(prepared,proposal,workflow_run_id='regimen:fixture',output_sha256='b'*64,
        extracted_at=datetime(2026,9,13,tzinfo=timezone.utc))
    assert bundle['option']['canonical_state']=='proposed'
    assert bundle['option']['is_default'] is True
    assert bundle['evidence_units']
    assert len(bundle['claim_evidence_links'])==8
    assert all(link['relation']=='limits' and link['canonical_state']=='proposed' for link in bundle['claim_evidence_links'])
    assert bundle['medical_admission']=='not_assessed'
    assert set(bundle['option']['claim_evidence_link_ids'])=={link['claim_evidence_link_id'] for link in bundle['claim_evidence_links']}
    original=prepared.to_payload()['source_intake']['sources'][0]
    assert all(unit['source_content_sha256']==original['content_sha256'] for unit in bundle['evidence_units'])


def test_unsupported_quote_cannot_be_persisted_as_a_verified_extraction():
    from app.protocol_workflow.agent2.option_bundle import build_regimen_option_bundle
    prepared,output=prepared_reference();proposal=read_regimen_response(prepared,output)
    proposal=deepcopy(proposal);proposal['regimen']['schedules'][0]['steps'][0]['references'][0]['quote']='原资料并没有这句话'
    with pytest.raises(ValueError,match='option_quote_not_in_pinned_source'):
        build_regimen_option_bundle(prepared,proposal,workflow_run_id='regimen:fixture',output_sha256='b'*64,
            extracted_at=datetime(2026,9,13,tzinfo=timezone.utc))


def test_literal_evidence_retains_surrounding_source_text_for_semantic_review():
    from app.protocol_workflow.agent2.option_bundle import build_regimen_option_bundle
    prepared, output = prepared_reference()
    proposal = read_regimen_response(prepared, output)
    bundle = build_regimen_option_bundle(
        prepared, proposal, workflow_run_id='regimen:fixture', output_sha256='b'*64,
        extracted_at=datetime(2026,9,13,tzinfo=timezone.utc))
    sources = {s['source_artifact_id']: s for s in prepared.to_payload()['source_intake']['sources']}
    for evidence in bundle['evidence_units']:
        source_unit = next(u for u in sources[evidence['source_artifact_id']]['units']
                           if u['locator'] == evidence['locator'] and evidence['body'] in u['text'])
        assert evidence['context_before'] + evidence['body'] + evidence['context_after'] == source_unit['text']
