"""A stored full chapter request yields a durable candidate, never medical approval."""
import json
import pytest
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from app.protocol_workflow.runtime.restored_probe import RestoredZhipuProbePolicy
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from test_regimen_workflow_integration import ROOT
from test_chapter_draft_request import inputs
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body


@pytest.mark.parametrize('malformed',[False,True,'dangling'])
def test_chapter_candidate_runs_once_and_recovers_without_writing_facts(tmp_path,malformed):
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft
    from app.protocol_workflow.agent3.subgraph import build_chapter_draft_runtime, chapter_draft_plan
    contract,bound,evidence=inputs()
    prepared=prepare_chapter_draft(contract,bound,(evidence,))
    output={'chapter_contract_id':contract.chapter_contract_id,'node_id':contract.semantic_node_id,
        'blocks':[{'kind':'paragraph','block_id':'block:one','text':'合成章节正文。','evidence_refs':[evidence.evidence_unit_id]}]}
    if malformed=='dangling':
        output['blocks'][0]['evidence_refs']=['evidence:missing']
    raw='synthetic invalid JSON' if malformed is True else json.dumps(output)
    opener=_FakeOpener([_FakeResponse(_completion_body(content=raw))])
    role=next(r for r in load_role_registry(ROOT/'role_registry.json').roles if r.role_id=='product-llm')
    skill=next(s for s in load_skill_registry(ROOT/'skill_registry.json').skill_definitions() if s.skill_definition_id=='skill.chapter-draft')
    config={'backend':'sqlite','path':str(tmp_path/'chapter.sqlite')}
    store=LocalArtifactStore(str(tmp_path/'artifacts'))
    dispatcher=HarnessDispatcher(probe_policy=RestoredZhipuProbePolicy(ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json'))
    def runtime():
        return build_chapter_draft_runtime(project_id='project:chapter:synthetic',
            uow_factory=build_unit_of_work_factory(config),reservation_repository_factory=build_committed_reservation_repository_factory(config),
            artifact_store=store,role_entry=role,skill=skill,dispatcher=dispatcher,
            adapter_factory=lambda **kwargs:build_zhipu_api_adapter(credential_resolver=lambda:'synthetic-only',http_opener=opener,max_input_bytes=2000000,**kwargs))
    from app.protocol_workflow.agent3.coordinator import ChapterDraftCoordinator
    def coordinator(study='study:one', revision='a'*64):
        return ChapterDraftCoordinator(project_id='project:chapter:synthetic', branch_id='main',
            study_definition_id=study, study_revision_sha256=revision, runtime=runtime())
    owner=coordinator()
    run_id=owner.start(prepared)
    assert owner.start(prepared)==run_id
    assert coordinator('study:other').run_id(prepared)!=run_id
    assert coordinator(revision='b'*64).run_id(prepared)!=run_id
    assert owner.prepared_request(run_id)==prepared
    with pytest.raises(ValueError,match='chapter_run_identity_mismatch'):
        coordinator('study:other').read(run_id)
    with pytest.raises(ValueError,match='chapter_run_identity_mismatch'):
        coordinator(revision='b'*64).read(run_id)
    rt=runtime();plan=chapter_draft_plan('project:chapter:synthetic','main')
    assert rt.run_to_completion(run_id).status.value=='completed'
    events=rt.read_events(run_id)
    result=next(e.payload['output'] for e in events if e.event_type=='graph_node_result' and e.payload['node_id']=='chapter-validate')
    assert result['valid'] is (not malformed)
    assert result['status']==('needs_structure_correction' if malformed else 'needs_content_review')
    assert result['validation_scope']=='structure_and_input_identity'
    if malformed=='dangling':
        assert 'evidence:missing' in result['errors'][0]['detail']
    from app.protocol_workflow.runtime.model_response import read_model_response
    record=read_model_response(store,result['raw_response']['artifact_ref'])
    assert record['content']==raw
    assert '原文末句' in json.loads(opener.requests[0]['data'])['messages'][0]['content']
    assert opener.calls==1
    runtime().run_to_completion(run_id)
    assert runtime().read_events(run_id)==events
    assert opener.calls==1
    assert coordinator().read(run_id)['status']==result['status']
    assert coordinator().prepared_request(run_id)==prepared
    with build_unit_of_work_factory(config)() as uow:
        assert uow.study_definition_repository.list_current('project:chapter:synthetic')==()
        assert uow.semantic_document_repository.list_current('project:chapter:synthetic')==()
