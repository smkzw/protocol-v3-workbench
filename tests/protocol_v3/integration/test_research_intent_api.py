"""Current stored seed choices become study facts only on explicit adoption."""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig,mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener,_FakeResponse,_completion_body
from test_template_fact_adoption import _dump
from test_mounted_api_integration import PROJECT,_apply_body
import integration_shared as shared


@pytest.mark.parametrize('user_edit',[False,True])
def test_basic_research_information_adopts_and_recovers_original_receipt(tmp_path,monkeypatch,user_edit):
    db=tmp_path/'intent.db';shared.admit(db,PROJECT)
    output={'fields':{k:[{'raw':v,'candidate':v,'confidence':1,'reason':'来自合成写作说明',
        'basis':'user','references':[]}] for k,v in {'research_drug':'合成药X','clinical_phase':'Ⅱ期'}.items()}}
    opener=_FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    seeds=create_product_seed_factory(storage_config={'backend':'sqlite','path':str(db)},
        prior_probe_receipt=ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000,credential_resolver=lambda:'synthetic-only',http_opener=opener)
    seed=seeds(PROJECT).start(prepare_seed_request('合成药X的Ⅱ期研究',()))
    seeds(PROJECT).resume(seed)
    def client():
        app=FastAPI();mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db),seed_coordinator_factory=seeds)
        return TestClient(app)
    base=f'/api/projects/{PROJECT}/protocol-workflow'
    path=base+'/design/regimen/research-information'
    with client() as c:
        response=c.post(base+'/design/regimen/study-context',json={'seed_run_id':seed,'operation_id':'context:one',
            'actor_id':'user:one','decided_at':'2026-09-13T10:00:00Z'})
        assert response.status_code==200,response.text
        created=response.json();study=created['study_definition_id']
        intent={'seed_run_id':seed,'study_definition_id':study,'operation_id':'info:one',
            'selections':{'research_drug':0,'clinical_phase':0},'expected_revision':1,'snapshot_sha256':created['revision_sha256'],
            'actor_id':'user:one','decided_at':'2026-09-13T11:00:00Z','reason':'确认本次研究信息'}
        if user_edit:
            intent['user_edits']={'research_drug':'用户修正药物X'}
        before=_dump(db)
        assert c.post(path+'/recover',json=intent).status_code==404
        assert _dump(db)==before
        adopted=c.post(path,json=intent)
        assert adopted.status_code==200,adopted.text
        result=adopted.json()
        assert result['definition']['facts']['framing.study_phase']=='Ⅱ期'
        assert result['definition']['facts']['framing.investigational_product']==('用户修正药物X' if user_edit else '合成药X')
        assert result['revision']==2
    before=_dump(db)
    with client() as c:
        with monkeypatch.context() as changed:
            def unavailable(*args,**kwargs):raise RuntimeError('synthetic compiler unavailable')
            changed.setattr('app.protocol_workflow.agent2.research_intent.prepare_research_intent_adoption',unavailable)
            recovered=c.post(path+'/recover',json=intent)
            assert recovered.status_code==200,recovered.text
            replay=c.post(path,json=intent)
            assert replay.status_code==200,replay.text
        assert _dump(db)==before
        assert recovered.json()['effective_decision']==result['effective_decision']
        update=_apply_body(snapshot_sha256=result['revision_sha256'],expected_revision=2,
            idempotency_key='context:changed',decision_record_id='decision:changed',
            fact_updates={'research.input_context':{'changed':True}})
        update['study_definition_id']=study
        update['revise_confirmed_facts']=True
        advanced=c.post(base+'/study-definitions/'+study+'/decisions',json=update)
        assert advanced.status_code==200,advanced.text
        after=_dump(db)
        fresh={**intent,'operation_id':'info:new','expected_revision':3,'snapshot_sha256':advanced.json()['revision_sha256']}
        assert c.post(path,json=fresh).status_code==409
        historical=c.post(path,json=intent)
        assert historical.status_code==200 and historical.json()['revision']==3
        assert _dump(db)==after and opener.calls==1
