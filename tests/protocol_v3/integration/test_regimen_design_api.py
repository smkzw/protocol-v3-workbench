"""Product-mounted design starts from the persisted seed, not client-spliced facts."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.protocol_workflow.api.composition import ProtocolWorkflowMountConfig, mount_protocol_workflow_router
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from test_seed_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_source_import_api import PROJECT, BASE, upload
from test_writing_reference_docx import build_docx, paragraph_xml
import integration_shared as shared


@pytest.mark.parametrize("study_bound", [False, True])
def test_design_uses_pinned_intake_and_reopens_without_product_regeneration(tmp_path, study_bound):
    from app.protocol_workflow.agent2.product import create_product_regimen_factory
    db = tmp_path / "product.db"
    shared.admit(db,PROJECT)
    storage = {"backend":"sqlite","path":str(db)}
    prior = ROOT.parents[2] / "runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json"
    opener = _FakeOpener([_FakeResponse(_completion_body(content='{"fields":{}}')),
        _FakeResponse(_completion_body(content='{"coverage":[],"regimen":null,"questions":["拟采用哪份给药依据？"]}'))])
    keys=[]
    def credentials():
        keys.append("memory-only")
        return "synthetic-only"
    kwargs = dict(storage_config=storage,prior_probe_receipt=prior,max_input_bytes=100000,credential_resolver=credentials,http_opener=opener)
    seeds = create_product_seed_factory(**kwargs)
    designs = create_product_regimen_factory(**kwargs)
    def client():
        app=FastAPI()
        mount_protocol_workflow_router(app,ProtocolWorkflowMountConfig(enabled=True,db_path=db),
                                       seed_coordinator_factory=seeds,regimen_coordinator_factory=designs)
        return TestClient(app)
    endpoint = BASE.removesuffix("/sources")
    with client() as c:
        source=upload(c,build_docx(paragraph_xml("完整原资料不能丢失"))).json()["current"]["source"]
        seed=c.post(endpoint+"/research-intake",json={"user_brief":"准备设计", "source_artifact_ids":[source["source_artifact_id"]]})
        assert seed.status_code == 202
        assert opener.calls == 1
        body={"seed_run_id":seed.json()["workflow_run_id"]}
        if study_bound:
            created = c.post(endpoint+'/design/regimen/study-context', json={**body,
                'operation_id':'context:design:test','actor_id':'user:test','decided_at':'2026-09-13T10:00:00Z'})
            assert created.status_code == 200, created.text
            study_id = created.json()['study_definition_id']
            prepared_intent = c.post(endpoint+'/design/regimen/prepare', json={**body, 'study_definition_id':study_id})
            assert prepared_intent.status_code == 200, prepared_intent.text
            body = prepared_intent.json()
            assert body['study_definition_id'] == study_id
            assert body['expected_workflow_run_id']
            assert opener.calls == 1  # Preparing an identity does not generate.
        started=c.post(endpoint+"/design/regimen",json=body)
        assert started.status_code == 202,started.text
        run=started.json()["workflow_run_id"]
        if study_bound:
            assert run == body["expected_workflow_run_id"]
            assert designs(PROJECT).prepared_request(run).to_payload()["confirmed_study"] == {"study_definition_id":study_id,"facts":{}}
        result=c.get(endpoint+"/design/regimen/"+run)
        assert result.status_code == 200
        assert result.json()["status"] == "needs_information"
        assert result.json()["study_definition_id"] == (study_id if study_bound else None)
        assert opener.calls == 2 and len(keys)==2
        if study_bound:
            from test_mounted_api_integration import _apply_body
            update = _apply_body(snapshot_sha256=created.json()['revision_sha256'],
                idempotency_key='clinical:changed', fact_updates={'picos.phase':'III'})
            update.update(project_id=PROJECT, study_definition_id=study_id)
            changed = c.post(endpoint+'/study-definitions/'+study_id+'/decisions', json=update)
            assert changed.status_code == 200, changed.text
            next_intent = c.post(endpoint+'/design/regimen/prepare', json={
                'seed_run_id':body['seed_run_id'], 'study_definition_id':study_id})
            assert next_intent.status_code == 200, next_intent.text
            assert next_intent.json()['expected_workflow_run_id'] != run
            assert opener.calls == 2
    with client() as c:
        recovered=c.post(endpoint+"/design/regimen/recover",json=body)
        assert recovered.status_code == 200
        assert recovered.json()==result.json()
        repeated=c.post(endpoint+"/design/regimen",json=body)
        assert repeated.status_code==202 and repeated.json()["workflow_run_id"]==run
        assert opener.calls==2 and len(keys)==2
