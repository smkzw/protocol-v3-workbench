"""Chapter inputs use the selected persisted sources and actual SQLite revision."""
import pytest
from app.protocol_workflow.application.service import ApplicationService
from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
from app.protocol_workflow.canonical.study_definition import study_revision_hash
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory, build_committed_reservation_repository_factory
from app.protocol_workflow.agent3.source_preparation import build_source_preparation
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.registries.template_runtime import load_current_template
from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from test_chapter_applicability import interim_case
from test_chapter_fact_binding import confirmed_study
from test_source_identity_product import service, adopt
from test_writing_reference_docx import build_docx, paragraph_xml
from test_template_fact_adoption import _dump


@pytest.mark.parametrize('mismatch', [None, 'revision', 'sources', 'study'])
def test_prepare_chapter_from_persisted_sources_is_read_only(tmp_path, mismatch):
    raw = build_docx(paragraph_xml('完整来源末句不能丢失'))
    source = adopt(service(tmp_path), raw)
    seed = prepare_seed_request('合成写作说明', ((source.source.source, parse_docx(raw)),))
    config = {'backend': 'sqlite', 'path': str(tmp_path / 'chapter.sqlite')}
    uow = build_unit_of_work_factory(config)
    preparations = build_source_preparation(project_id='project-1', branch_id='main',
        uow_factory=uow, reservation_repository_factory=build_committed_reservation_repository_factory(config),
        source_service=service(tmp_path))
    run = preparations.start(seed)
    bundle = preparations.resume(run)
    study = confirmed_study({'statistics.interim.applicable': False,
        'research.input_context': {'source_intake_sha256': 'f'*64 if mismatch == 'sources' else seed.input_sha256}},
        project_id='project-1')
    with uow() as tx:
        tx.study_definition_cas_repository.save_with_expected_revision(study.project_id, study, 0)
        tx.commit()
    class UnavailableSources:
        def history(self, *args): raise AssertionError('Completed sources must not be read again')
    reopened = build_source_preparation(project_id='project-1', branch_id='main',
        uow_factory=uow, reservation_repository_factory=build_committed_reservation_repository_factory(config),
        source_service=UnavailableSources())
    application = ApplicationService(unit_of_work_factory=uow,
        current_template_loader=lambda: load_current_template(REAL_TEMPLATE_DIR))
    query = GetStudyDefinitionQuery(study.project_id,
        'study:missing' if mismatch == 'study' else study.study_definition_id)
    contract, _ = interim_case()
    before = _dump(tmp_path / 'chapter.sqlite')
    def prepare():
        return application.prepare_manuscript_chapter(query, node_id=contract.semantic_node_id,
            source_preparation=reopened, source_run_id=run,
            expected_study_sha256='f'*64 if mismatch == 'revision' else study_revision_hash(study))
    if mismatch:
        code = {'revision': 'chapter_study_revision_changed', 'sources': 'chapter_source_context_changed',
                'study': 'chapter_study_missing'}[mismatch]
        with pytest.raises(ValueError, match=code): prepare()
    else:
        prepared = prepare()
        payload = prepared.to_payload()
        assert payload['chapter_input']['study_sha256'] == study_revision_hash(study)
        assert payload['chapter_input']['resolved_facts'] == {'statistics.interim.applicable': False}
        assert payload['source_material'] == bundle.to_payload()
        assert '完整来源末句不能丢失' in prepared.payload_json
        assert prepare() == prepared
    assert _dump(tmp_path / 'chapter.sqlite') == before


def test_chapter_api_pins_original_request_and_recovers_after_study_changes(tmp_path):
    import json
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.protocol_workflow.api.composition import mount_protocol_workflow_router, ProtocolWorkflowMountConfig
    import integration_shared as shared
    from app.protocol_workflow.agent3.product import create_product_chapter_factory
    from test_regimen_workflow_integration import ROOT
    from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
    raw = build_docx(paragraph_xml('章节使用完整原文'))
    source = adopt(service(tmp_path), raw)
    seed = prepare_seed_request('合成说明', ((source.source.source, parse_docx(raw)),))
    config = {'backend': 'sqlite', 'path': str(tmp_path / 'api.sqlite')}
    shared.admit(tmp_path / 'api.sqlite', 'project-1')
    uow = build_unit_of_work_factory(config)
    def preparations(project):
        return build_source_preparation(project_id=project, branch_id='main', uow_factory=uow,
            reservation_repository_factory=build_committed_reservation_repository_factory(config),
            source_service=service(tmp_path))
    owner = preparations('project-1')
    source_run = owner.start(seed); owner.resume(source_run)
    study = confirmed_study({'statistics.interim.applicable': False,
        'research.input_context': {'source_intake_sha256': seed.input_sha256}}, project_id='project-1')
    with uow() as tx:
        tx.study_definition_cas_repository.save_with_expected_revision(study.project_id, study, 0); tx.commit()
    contract, _ = interim_case()
    raw_candidate = json.dumps({'chapter_contract_id': contract.chapter_contract_id,
        'node_id': contract.semantic_node_id,
        'blocks': [{'kind': 'paragraph', 'block_id': 'block:one', 'text': '本研究不开展期中分析。', 'evidence_refs': []}]})
    opener = _FakeOpener([_FakeResponse(_completion_body(content=raw_candidate))])
    drafts = create_product_chapter_factory(storage_config=config,
        prior_probe_receipt=ROOT.parents[2]/'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000, credential_resolver=lambda:'synthetic-only', http_opener=opener)
    def client():
        app = FastAPI()
        mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=tmp_path/'api.sqlite'),
            chapter_coordinator_factory=drafts)
        return TestClient(app)
    path = f'/api/projects/{study.project_id}/protocol-workflow/study-definitions/{study.study_definition_id}/chapters/{contract.semantic_node_id}/draft'
    body = {'source_run_id': source_run, 'study_revision_sha256': study_revision_hash(study)}
    with client() as c:
        before = _dump(tmp_path/'api.sqlite')
        incomplete = c.post(path.replace(contract.semantic_node_id, 'v2_n_4_1')+'/prepare', json=body)
        assert incomplete.status_code == 409, incomplete.text
        assert incomplete.json()['detail']['next_step']
        prepared = c.post(path+'/prepare', json=body)
        assert prepared.status_code == 200, prepared.text
        assert _dump(tmp_path/'api.sqlite') == before and opener.calls == 0
        body['expected_workflow_run_id'] = prepared.json()['expected_workflow_run_id']
        assert c.post(path+'/recover', json=body).status_code == 404
        started = c.post(path, json=body)
        assert started.status_code == 202, started.text
        result = c.post(path+'/recover', json=body)
        assert result.json()['status'] == 'needs_content_review', result.text
        assert opener.calls == 1
    changed = study.model_copy(update={'revision': study.revision+1,
        'previous_revision_sha256': study_revision_hash(study),
        'facts': {**study.facts, 'statistics.interim.applicable': True}})
    with uow() as tx:
        tx.study_definition_cas_repository.save_with_expected_revision(study.project_id, changed, study.revision); tx.commit()
    before = _dump(tmp_path/'api.sqlite')
    with client() as c:
        assert c.post(path+'/recover', json=body).json() == result.json()
        assert c.post(path, json=body).json() == result.json()
        assert c.post(path+'/prepare', json={k:v for k,v in body.items() if k!='expected_workflow_run_id'}).status_code == 409
        wrong = {**body, 'source_run_id': 'source:missing'}
        assert c.post(path+'/recover', json=wrong).status_code in (404,409)
    assert _dump(tmp_path/'api.sqlite') == before and opener.calls == 1
