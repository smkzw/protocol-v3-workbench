"""Mounted HTTP composes existing study selection with durable full source material."""
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig,mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.source_identity import SourceIdentityService
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory,build_committed_reservation_repository_factory
from test_source_identity_product import adopt
from test_writing_reference_docx import build_docx,paragraph_xml
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener,_FakeResponse,_completion_body
from test_template_fact_adoption import _dump
from test_mounted_api_integration import PROJECT,_apply_body
import integration_shared as shared


@pytest.mark.parametrize("read_failure", [False,True])
def test_full_source_preparation_api_recovers_without_model_or_source_reprocessing(tmp_path,monkeypatch,read_failure):
    from app.protocol_workflow.agent3.source_preparation import build_source_preparation
    db=tmp_path/'product.db';shared.admit(db,PROJECT)
    config={'backend':'sqlite','path':str(db)}
    uow=build_unit_of_work_factory(config)
    source_service=SourceIdentityService(uow,LocalArtifactStore(str(db)+'.artifacts'))
    raw=build_docx(paragraph_xml('完整原始来源最后一句'))
    source=adopt(source_service,raw,project_id=PROJECT)
    opener=_FakeOpener([_FakeResponse(_completion_body(content=json.dumps({'fields':{}})))])
    seeds=create_product_seed_factory(storage_config=config,
        prior_probe_receipt=ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000,credential_resolver=lambda:'synthetic-only',http_opener=opener)
    seed=seeds(PROJECT).start(prepare_seed_request('合成研究写作',((source.source.source,parse_docx(raw)),)))
    seeds(PROJECT).resume(seed)
    def preparations(project):
        return build_source_preparation(project_id=project,branch_id='main',uow_factory=uow,
            reservation_repository_factory=build_committed_reservation_repository_factory(config),source_service=source_service)
    def client():
        app=FastAPI();mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db),seed_coordinator_factory=seeds)
        return TestClient(app)
    base=f'/api/projects/{PROJECT}/protocol-workflow'
    with client() as c:
        created=c.post(base+'/design/regimen/study-context',json={'seed_run_id':seed,'operation_id':'context:one',
            'actor_id':'user:one','decided_at':'2026-09-13T12:00:00Z'})
        assert created.status_code==200,created.text
        study=created.json()['study_definition_id']
        path=base+'/study-definitions/'+study+'/manuscript-sources'
        before_start=_dump(db)
        assert c.post(path,json={'seed_run_id':'seed:missing'}).status_code==404
        assert _dump(db)==before_start
        original_history=SourceIdentityService.history
        reads=0
        def intermittent(self,*args):
            nonlocal reads
            reads+=1
            if read_failure and reads==1:raise OSError('synthetic local source read interruption')
            return original_history(self,*args)
        monkeypatch.setattr(SourceIdentityService,'history',intermittent)
        response=c.post(path,json={'seed_run_id':seed})
        assert response.status_code==202,response.text
        run=response.json()['workflow_run_id']
        assert response.json()['status']=='running'
        result=c.get(base+'/manuscript-sources/'+run)
        if read_failure:
            assert result.json()['status']=='failed' and result.json()['can_retry'] is True
            retry=c.post(base+'/manuscript-sources/'+run+'/retry',json={'retry_decision_id':'source-retry:one'})
            assert retry.status_code==202,retry.text
            result=c.get(base+'/manuscript-sources/'+run)
            assert result.json()['retry_run_id']==run+':retry:1'
        assert result.status_code==200 and result.json()['status']=='completed'
        assert result.json()['source_count']==1
        assert result.json()['assessment']=='not_assessed'
        bundle=preparations(PROJECT).read(run)
        assert bundle.evidence[0].body=='完整原始来源最后一句'
        assert c.get(base+'/study-definitions/'+study).json()['revision_sha256']==created.json()['revision_sha256']
    before=_dump(db)
    def unavailable(*args):raise AssertionError('reopening must not reread original sources')
    monkeypatch.setattr(SourceIdentityService,'history',unavailable)
    with client() as c:
        replay=c.post(path,json={'seed_run_id':seed})
        assert replay.status_code==202,replay.text
        assert replay.json()==result.json()
        assert c.post(base+'/manuscript-sources/'+run+'/resume').json()==result.json()
        if read_failure:
            assert c.post(base+'/manuscript-sources/'+run+'/retry',
                json={'retry_decision_id':'source-retry:different'}).status_code==409
        assert c.get(base+'/manuscript-sources/missing').status_code==404
    assert _dump(db)==before and opener.calls==1
    with client() as c:
        update=_apply_body(snapshot_sha256=created.json()['revision_sha256'],expected_revision=1,
            idempotency_key='context:changed',decision_record_id='decision:changed',
            fact_updates={'research.input_context':{'changed':True}})
        update['study_definition_id']=study;update['revise_confirmed_facts']=True
        changed=c.post(base+'/study-definitions/'+study+'/decisions',json=update)
        assert changed.status_code==200,changed.text
        after=_dump(db)
        assert c.post(path,json={'seed_run_id':seed}).status_code==409
        assert c.get(base+'/manuscript-sources/'+run).json()==result.json()
        assert _dump(db)==after and opener.calls==1
