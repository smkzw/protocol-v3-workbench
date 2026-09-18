"""Real mounted context creation records the user request, not seed candidates."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from test_seed_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_source_import_api import PROJECT, BASE, upload
from test_writing_reference_docx import build_docx, paragraph_xml
from test_template_fact_adoption import _dump
import integration_shared as shared


def test_create_reopen_context_without_adopting_medical_candidates(tmp_path):
    db = tmp_path/'context.sqlite'
    shared.admit(db,PROJECT)
    opener = _FakeOpener([_FakeResponse(_completion_body(content='{"fields":{}}')), _FakeResponse(_completion_body(content='{"fields":{}}'))])
    seeds = create_product_seed_factory(storage_config={'backend':'sqlite','path':str(db)},
        prior_probe_receipt=ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=100000,credential_resolver=lambda:'synthetic-only',http_opener=opener)
    def client():
        app=FastAPI()
        mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db),seed_coordinator_factory=seeds)
        return TestClient(app)
    endpoint=BASE.removesuffix('/sources')
    context=endpoint+'/design/regimen/study-context'
    with client() as c:
        assert c.get(context).json()=={'studies': []}
        source=upload(c,build_docx(paragraph_xml('历史资料中的剂量不能自动采用'))).json()['current']['source']
        seed=c.post(endpoint+'/research-intake',json={'user_brief':'准备新的研究方案','source_artifact_ids':[source['source_artifact_id']]})
        assert seed.status_code==202,seed.text
        intent={'seed_run_id':seed.json()['workflow_run_id'],'operation_id':'operation:context:one',
                'actor_id':'medical_manager','decided_at':'2026-09-13T08:00:00+00:00'}
        before=_dump(db)
        absent=c.post(context+'/recover',json=intent)
        assert absent.status_code==404,absent.text
        assert _dump(db)==before
        created=c.post(context,json=intent)
        assert created.status_code==200,created.text
        result=created.json()
        assert set(result['definition']['facts'])=={'research.input_context'}
        assert result['definition']['facts']['research.input_context']['user_brief']=='准备新的研究方案'
    before=_dump(db)
    with client() as c:
        found=c.post(context+'/recover',json=intent)
        assert found.status_code==200,found.text
        assert found.json()['revision_sha256']==result['revision_sha256']
        assert _dump(db)==before
        listing=c.get(context).json()['studies']
        assert len(listing)==1
        assert listing[0]['study_definition_id']==result['study_definition_id']
        assert _dump(db)==before
        assert opener.calls==1

        matching=c.get(context,params={'seed_run_id':intent['seed_run_id']}).json()['studies'][0]
        assert matching['matches_selected_inputs'] is True
        next_seed=c.post(endpoint+'/research-intake',json={'user_brief':'同一项目改用新的写作说明',
            'source_artifact_ids':[source['source_artifact_id']]})
        assert next_seed.status_code==202,next_seed.text
        next_run=next_seed.json()['workflow_run_id']
        matching=c.get(context,params={'seed_run_id':next_run}).json()['studies'][0]
        assert matching['matches_selected_inputs'] is False
        change={'seed_run_id':next_run,'operation_id':'operation:inputs:two','actor_id':'medical_manager',
                'decided_at':'2026-09-13T08:30:00+00:00','expected_revision':1,
                'snapshot_sha256':result['revision_sha256']}
        path=context+'/'+result['study_definition_id']+'/inputs'
        updated=c.post(path,json=change)
        assert updated.status_code==200,updated.text
        assert updated.json()['revision']==2
        assert set(updated.json()['definition']['facts'])=={'research.input_context'}
        before_recovery=_dump(db)
        recovered=c.post(path+'/recover',json=change)
        assert recovered.status_code==200,recovered.text
        assert _dump(db)==before_recovery
        assert c.get(context,params={'seed_run_id':next_run}).json()['studies'][0]['matches_selected_inputs'] is True
        assert c.get(context,params={'seed_run_id':intent['seed_run_id']}).json()['studies'][0]['matches_selected_inputs'] is False
        assert opener.calls==2
