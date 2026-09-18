"""Product chapter wiring remains lazy and reuses the approved transport receipt."""
import json
import pytest
from test_chapter_draft_request import inputs
from test_chapter_fact_binding import confirmed_study, bindings_for_objective
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body


@pytest.mark.parametrize("correction",[False,True,"still_invalid","table_cell","table_note"])
def test_product_chapter_factory_calls_only_on_execution_and_reopens(tmp_path,correction):
    from app.protocol_workflow.agent3.product import create_product_chapter_factory
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    contract,_,evidence=inputs()
    study=confirmed_study({'study.objective':'合成研究目的'})
    source_material=None
    evidence_units=(evidence,)
    if correction is False:
        from test_chapter_source_material import material
        from app.protocol_workflow.agent3.source_material import prepare_chapter_source_material
        source,parsed=material()
        source_material=prepare_chapter_source_material(((source,parsed),),extracted_at=source.captured_at)
        evidence_units=source_material.evidence
        evidence=evidence_units[0]
    prepared=prepare_chapter_draft(contract,bind_chapter_input(study,contract,bindings_for_objective()),
        evidence_units,source_material=source_material)
    if correction is False:
        _,unbound,_=inputs()
        unbound_prepared=prepare_chapter_draft(contract,unbound,(evidence,))
    raw=json.dumps({'chapter_contract_id':contract.chapter_contract_id,'node_id':contract.semantic_node_id,
        'blocks':[{'kind':'paragraph','block_id':'block:one','text':'合成研究目的。','evidence_refs':[evidence.evidence_unit_id]}]})
    responses=[_FakeResponse(_completion_body(content="still broken JSON" if correction=="still_invalid" else raw))]
    original_content="broken chapter JSON"
    expected_code="chapter_invalid_json"
    if correction in ("table_cell","table_note"):
        from test_ordered_chapter_draft import _2x2_table
        table=_2x2_table(table_id='table:one',block_id='block:table',title='合成表',
            source_locator='docx:t1',cell_prefix='cell',note_id='note:one').model_dump(mode='json')
        for row in table['rows']:
            for cell in row['cells']:
                cell['provenance_lineage']=[evidence.evidence_unit_id]
        table['notes'][0]['source_refs']=[evidence.evidence_unit_id]
        if correction=='table_cell':
            table['rows'][0]['cells'][0]['provenance_lineage']=['evidence:invented']
        else:
            table['notes'][0]['source_refs']=['evidence:invented']
        original_content=json.dumps({'chapter_contract_id':contract.chapter_contract_id,
            'node_id':contract.semantic_node_id,'blocks':[{'kind':'table','block_id':'block:table',
                'table':table,'evidence_refs':[evidence.evidence_unit_id]}]})
        expected_code='chapter_table_reference_unknown'
    if correction:
        responses.insert(0,_FakeResponse(_completion_body(content=original_content)))
    opener=_FakeOpener(responses)
    key_reads=[]
    def credential():
        key_reads.append(True)
        return 'synthetic-only'
    kwargs=dict(storage_config={'backend':'sqlite','path':str(tmp_path/'chapter.db')},
        prior_probe_receipt=ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000,credential_resolver=credential,http_opener=opener)
    factory=create_product_chapter_factory(**kwargs)
    owner=factory(study.project_id,study.study_definition_id,study_revision_hash(study))
    if correction is False:
        with pytest.raises(ValueError,match='chapter_bound_input_required'):
            owner.start(unbound_prepared)
    run=owner.start(prepared)
    assert key_reads==[] and opener.calls==0
    owner.resume(run)
    expected_status='needs_structure_correction' if correction=='still_invalid' else 'needs_content_review'
    assert owner.read(run)['status']==expected_status
    if correction=='still_invalid':
        assert owner.read(run)['can_resume'] is False
    events=owner.runtime.read_events(run)
    reopened=create_product_chapter_factory(**kwargs)(study.project_id,study.study_definition_id,study_revision_hash(study))
    assert reopened.start(prepared)==run
    if correction=='still_invalid':
        assert reopened.read(run)['validation']['proposal'] is None
    else:
        assert reopened.read(run)['validation']['proposal']['blocks'][0]['text']=='合成研究目的。'
    assert reopened.runtime.read_events(run)==events
    reopened.resume(run)
    expected=2 if correction else 1
    assert opener.calls==expected and len(key_reads)==expected
    if correction is False:
        message=json.loads(opener.requests[0]['data'])['messages'][0]['content']
        assert '最后一句' in message and 'derived_toc' in message and 'grid_span' in message
        assert 'not_assessed' in message
    if correction:
        from app.protocol_workflow.runtime.model_response import read_model_response
        from app.protocol_workflow.graph.proposal_progress import proposal_outcome
        from app.protocol_workflow.agent3.subgraph import chapter_draft_plan
        original=proposal_outcome(owner.runtime,chapter_draft_plan(study.project_id,'main'),run,'chapter-validate')
        assert original['validation']['errors'][0]['code']==expected_code
        assert read_model_response(owner.artifacts,original['validation']['raw_response']['artifact_ref'])['content']==original_content
        message=json.loads(opener.requests[1]['data'])['messages'][0]['content']
        assert expected_code in message
        if correction in ('table_cell','table_note'):
            error=original['validation']['errors'][0]
            assert error['location'].startswith('blocks.0.table.')
            assert 'evidence:invented' in error['detail'] and 'evidence:invented' in message
        else:
            assert 'broken chapter JSON' in message
