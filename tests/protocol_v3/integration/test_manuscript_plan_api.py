"""The draft preparation view reads current SQLite facts without a model call."""
import pytest
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory
from test_mounted_api_integration import _admitted_client, PROJECT
from test_semantic_document_reducer import _study_definition
from test_template_fact_adoption import _dump


@pytest.mark.parametrize("state", ["confirmed", "proposed"])
def test_current_manuscript_plan_is_read_only_and_survives_reopen(tmp_path,monkeypatch,state):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.protocol_workflow.api.composition import mount_protocol_workflow_router
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    client,db=_admitted_client(tmp_path,monkeypatch)
    factory=build_unit_of_work_factory({'backend':'sqlite','path':str(db)})
    study=_study_definition(project_id=PROJECT,canonical_state=state,
        facts={'framing.study_phase':'Ⅱ期'})
    with factory() as uow:
        uow.study_definition_cas_repository.save_with_expected_revision(PROJECT,study,0)
        uow.commit()
    path=f'/api/projects/{PROJECT}/protocol-workflow/study-definitions/{study.study_definition_id}/manuscript-plan'
    before=_dump(db)
    with client:
        response=client.get(path)
        assert response.status_code==200,response.text
        plan=response.json()
        assert plan['study_sha256']==study_revision_hash(study)
        assert len(plan['chapters'])==111
        assert plan['chapters'][0]['node_id']=='v2_front_block'
        assert plan['all_applicable_inputs_ready'] is False
        if state=='proposed':
            assert plan['applicability_snapshot'] is None
            assert all(item['status']=='needs_information' and item['applicability']=='unresolved'
                and item['errors']==[{'code':'study_not_confirmed'}] for item in plan['chapters'])
        assert client.get(path.replace(study.study_definition_id,'study:missing')).status_code==404
        assert _dump(db)==before
    app=FastAPI();mount_protocol_workflow_router(app)
    with TestClient(app) as reopened:
        assert reopened.get(path).json()==plan
        assert _dump(db)==before
