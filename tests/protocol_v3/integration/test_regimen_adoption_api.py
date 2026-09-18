"""Stored model proposal -> explicit HTTP adoption -> current SQLite study."""
import json
import pytest
from datetime import datetime, timezone
from fastapi.encoders import jsonable_encoder
from app.protocol_workflow.application.research_context import prepare_research_context_creation
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from test_clinical_design_worker import prepared_reference
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_mounted_api_integration import PROJECT, SD_ID, _create_body, _apply_body
from test_template_fact_adoption import _dump
import integration_shared as shared

@pytest.mark.parametrize("study_bound,changed_input", [(False,"source"),(True,"source"),(True,"clinical")])
def test_saved_design_adoption_reopens_and_replays_without_model_or_duplicate_writes(tmp_path, monkeypatch, study_bound, changed_input):
    db=tmp_path/'product.sqlite'
    shared.admit(db,PROJECT)
    prepared, output=prepared_reference()
    if study_bound:
        from app.protocol_workflow.agent2.study_input import bind_regimen_study_input
        prepared = bind_regimen_study_input(prepared, study_definition_id=SD_ID, facts={})
    opener=_FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs=create_product_regimen_factory(storage_config={'backend':'sqlite','path':str(db)},
        prior_probe_receipt=ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000,credential_resolver=lambda:'synthetic-only',http_opener=opener)
    run=designs(PROJECT).start(prepared)
    assert designs(PROJECT).resume(run)['status']=='ready_for_review'
    def client():
        app=FastAPI()
        mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db),regimen_coordinator_factory=designs)
        return TestClient(app)
    base=f'/api/projects/{PROJECT}/protocol-workflow'
    with client() as c:
        creation=prepare_research_context_creation(project_id=PROJECT, study_definition_id=SD_ID,
            seed_run_id='seed:fixture', prepared=prepared, operation_id='operation:context:fixture',
            actor_id='user:example', decided_at=datetime(2026,9,13,tzinfo=timezone.utc))
        created_response=c.post(base+'/study-definitions',json=jsonable_encoder(creation))
        assert created_response.status_code==200,created_response.text
        created=created_response.json()
        intent={'study_definition_id':SD_ID,'operation_id':'operation:regimen:one','expected_revision':1,
                'snapshot_sha256':created['revision_sha256'],'actor_id':'user:example',
                'decided_at':'2026-09-13T07:00:00+00:00','reason':'采用完整给药方案'}
        legacy=c.post(base+'/study-definitions',json=_create_body(study_definition_id='study:legacy')).json()
        wrong={**intent, 'study_definition_id':'study:legacy', 'snapshot_sha256':legacy['revision_sha256']}
        before_wrong=_dump(db)
        rejected=c.post(base+'/design/regimen/'+run+'/adopt',json=wrong)
        assert rejected.status_code==409,rejected.text
        assert _dump(db)==before_wrong
        before_adopt=_dump(db)
        unknown=c.post(base+'/design/regimen/'+run+'/adopt/recover',json=intent)
        assert unknown.status_code==404,unknown.text
        assert _dump(db)==before_adopt
        # A receipt lookup is not a fresh-adoption readiness check.
        with monkeypatch.context() as unready:
            coordinator_type = type(designs(PROJECT))
            original_read = coordinator_type.read
            def read_as_unready(self, run_id):
                state = original_read(self, run_id)
                return {**state, "status": "needs_information"}
            unready.setattr(coordinator_type, "read", read_as_unready)
            absent=c.post(base+'/design/regimen/'+run+'/adopt/recover',json=intent)
            assert absent.status_code==404,absent.text
            assert _dump(db)==before_adopt
        response=c.post(base+'/design/regimen/'+run+'/adopt',json=intent)
        assert response.status_code==200,response.text
        result=response.json()
        assert result['revision']==2
        assert len(result['definition']['facts']['intervention.dose_regimen']['schedules'])==4
    before=_dump(db)
    with client() as c:
        # Looking up a historical receipt must survive a later fact compiler change.
        with monkeypatch.context() as changed_compiler:
            def unavailable_compiler(*args, **kwargs):
                raise RuntimeError("synthetic fact compiler changed")
            changed_compiler.setattr("app.protocol_workflow.agent2.study_definition.propose_regimen_fact_updates", unavailable_compiler)
            found=c.post(base+'/design/regimen/'+run+'/adopt/recover',json=intent)
        assert found.status_code==200,found.text
        assert found.json()['revision_sha256']==result['revision_sha256']
        assert _dump(db)==before
        altered={**intent,"reason":"a different recorded choice"}
        conflict=c.post(base+'/design/regimen/'+run+'/adopt/recover',json=altered)
        assert conflict.status_code==409,conflict.text
        assert _dump(db)==before
        replay=c.post(base+'/design/regimen/'+run+'/adopt',json=intent)
        assert replay.status_code==200,replay.text
        assert replay.json()['replayed'] is True
        assert replay.json()['revision_sha256']==result['revision_sha256']
        assert _dump(db)==before
        assert opener.calls==1

        graph=c.get(base+'/study-definitions/'+SD_ID+'/decision-graph').json()['records']
        assert next(r for r in graph if r['decision_key']=='decision:dose-regimen')['current_validity']=='current'
        # 双绑定语义（2026-09-13用户裁定，替代旧all_facts producer读集重开）：
        # producer读集与医学确认依赖分开。确认有效性由服务端医学依赖声明驱动
        # （期别/人群/药物），资料上下文变化不再自动重开用户的剂量确认。
        changed_context={**result['definition']['facts']['research.input_context'], 'seed_proposal_sha256':'d'*64}
        update=_apply_body(snapshot_sha256=result['revision_sha256'],expected_revision=2,
            idempotency_key='operation:new-inputs',decision_record_id='decision:new-inputs',
            fact_updates={'research.input_context':changed_context} if changed_input=='source' else {'framing.study_phase':'III'})
        update['revise_confirmed_facts']=True
        update['decision_record']['decision_key']='decision:research-request'
        advanced=c.post(base+'/study-definitions/'+SD_ID+'/decisions',json=update)
        assert advanced.status_code==200,advanced.text
        graph=c.get(base+'/study-definitions/'+SD_ID+'/decision-graph').json()['records']
        dose_validity=next(r for r in graph if r['decision_key']=='decision:dose-regimen')['current_validity']
        if changed_input=='source':
            # Producer read-set moved, but no declared medical dependency did:
            # the confirmation stays current; the new input context is the
            # producer's re-planning concern, not an automatic reopen.
            assert dose_validity=='current'
        else:
            # 研究期别是剂量确认声明的医学依赖：期别变化必须重开。
            assert dose_validity=='stale'
        after_inputs=_dump(db)
        historical=c.post(base+'/design/regimen/'+run+'/adopt',json=intent)
        assert historical.status_code==200,historical.text
        assert historical.json()['revision']==3
        assert historical.json()['replayed'] is True
        assert historical.json()['effective_decision']['decision_record_id']==result['effective_decision']['decision_record_id']
        assert _dump(db)==after_inputs
        fresh = {**intent, 'operation_id': 'operation:regimen:new-attempt',
                 'expected_revision': 3,
                 'snapshot_sha256': historical.json()['revision_sha256']}
        rejected_fresh = c.post(base+'/design/regimen/'+run+'/adopt', json=fresh)
        assert rejected_fresh.status_code == 409, rejected_fresh.text
        assert _dump(db) == after_inputs
        assert opener.calls == 1
