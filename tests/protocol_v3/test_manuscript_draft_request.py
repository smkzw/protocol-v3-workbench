"""Complete-draft requests account for all template carriers before dispatch."""
from dataclasses import replace
import pytest
from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from test_chapter_fact_binding import confirmed_study
from test_source_identity_product import service,adopt
from test_writing_reference_docx import build_docx,paragraph_xml
from test_template_fact_adoption import _dump
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.agent3.source_preparation import build_source_preparation
from app.protocol_workflow.registries.template_runtime import load_current_template
from app.protocol_workflow.storage.sqlite import build_unit_of_work_factory,build_committed_reservation_repository_factory


def inputs(tmp_path):
    raw=build_docx(paragraph_xml('完整来源最后一句'))
    source=adopt(service(tmp_path),raw)
    seed=prepare_seed_request('合成说明',((source.source.source,parse_docx(raw)),))
    config={'backend':'sqlite','path':str(tmp_path/'manuscript.sqlite')}
    owner=build_source_preparation(project_id='project-1',branch_id='main',
        uow_factory=build_unit_of_work_factory(config),
        reservation_repository_factory=build_committed_reservation_repository_factory(config),source_service=service(tmp_path))
    run=owner.start(seed);owner.resume(run)
    study=confirmed_study({'statistics.interim.applicable':False,'appendix.ecog_assessment_applicable':False,
        'appendix.ecog_applicability_decision_record':'合成排除记录',
        'research.input_context':{'source_intake_sha256':seed.input_sha256}},project_id='project-1')
    return load_current_template(REAL_TEMPLATE_DIR),study,owner,run


def test_incomplete_full_template_returns_all_carriers_not_a_ready_subset(tmp_path):
    from app.protocol_workflow.agent3.manuscript_request import prepare_manuscript_request,ManuscriptInputsIncomplete
    template,study,owner,run=inputs(tmp_path)
    before=_dump(tmp_path/'manuscript.sqlite')
    with pytest.raises(ManuscriptInputsIncomplete) as error:
        prepare_manuscript_request(template,study,source_preparation=owner,source_run_id=run)
    assert len(error.value.plan['chapters'])==111
    assert any(c['status']=='facts_ready' for c in error.value.plan['chapters'])
    assert any(c['status']=='needs_information' for c in error.value.plan['chapters'])
    assert _dump(tmp_path/'manuscript.sqlite')==before


def test_complete_bounded_template_pins_shared_material_once_and_restores_exact_requests(tmp_path):
    from app.protocol_workflow.agent3.manuscript_request import prepare_manuscript_request,PreparedManuscriptRequest
    from app.protocol_workflow.agent3.chapter_draft import prepare_study_chapter
    template,study,owner,run=inputs(tmp_path)
    order=('v2_n_11_4_9','v2_n_16_x1')
    entries=tuple(e for e in template.registry.chapters if e.node_id in order)
    template=replace(template,registry=template.registry.model_copy(update={'chapters':entries}),chapter_order=order)
    before=_dump(tmp_path/'manuscript.sqlite')
    prepared=prepare_manuscript_request(template,study,source_preparation=owner,source_run_id=run)
    payload=prepared.to_payload()
    assert tuple(c['node_id'] for c in payload['plan']['chapters'])==order
    assert [r.to_payload()['chapter_input']['node_id'] for r in prepared.chapter_requests()]==[order[0]]
    assert payload['plan']['chapters'][1]['status']=='not_applicable'
    assert payload['shared']['source_material']==owner.read(run).to_payload()
    assert 'source_material' not in payload['chapters'][0]
    bundle=owner.read(run)
    expected=prepare_study_chapter(template,study,order[0],bundle.evidence,source_material=bundle)
    reopened=PreparedManuscriptRequest(prepared.payload_json,prepared.input_sha256)
    assert reopened.chapter_requests()==(expected,)
    assert _dump(tmp_path/'manuscript.sqlite')==before
