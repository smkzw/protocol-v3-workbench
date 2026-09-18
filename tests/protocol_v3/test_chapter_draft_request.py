"""Generation inputs bind actual chapter/fact/source versions; output stays proposed."""
from datetime import datetime, timezone
import pytest
from test_all_chapter_contracts import _objectives_contract
from app.protocol_workflow.registries.chapters import ChapterSkillInput
from packages.contracts.workbench_contracts.protocol_v3 import EvidenceUnit


def inputs():
    contract = _objectives_contract()
    bound = ChapterSkillInput(chapter_contract_id=contract.chapter_contract_id,
        node_id=contract.semantic_node_id,template_id=contract.template_id,
        template_sha256=contract.template_sha256,
        resolved_facts={'study.synthetic':{'enabled':False,'count':0}},word_rules=contract.word_rules)
    evidence = EvidenceUnit(evidence_unit_id='evidence:chapter:one',source_artifact_id='source:one',
        source_content_sha256='a'*64,source_role='project_primary',locator_kind='body',
        locator='word/document.xml:p:12',body='完整来源'*1000+'原文末句',quality_score=1,
        extracted_at=datetime(2026,9,13,tzinfo=timezone.utc),canonical_state='proposed')
    return contract,bound,evidence


def test_preparation_preserves_full_facts_sources_and_input_identity():
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft
    contract,bound,evidence=inputs()
    prepared=prepare_chapter_draft(contract,bound,(evidence,))
    payload=prepared.to_payload()
    assert payload['chapter_input']['resolved_facts']['study.synthetic']=={'enabled':False,'count':0}
    assert payload['evidence'][0]['body'].endswith('原文末句')
    payload['chapter_input']['resolved_facts']['study.synthetic']['count']=99
    assert prepared.to_payload()['chapter_input']['resolved_facts']['study.synthetic']['count']==0
    changed=bound.model_copy(update={'resolved_facts':{'study.synthetic':{'enabled':False,'count':1}}})
    assert prepare_chapter_draft(contract,changed,(evidence,)).input_sha256!=prepared.input_sha256
    wrong=bound.model_copy(update={'node_id':'node:wrong'})
    with pytest.raises(ValueError,match='chapter_input_binding_mismatch'):
        prepare_chapter_draft(contract,wrong,(evidence,))


def test_writer_cannot_supply_its_own_source_universe_or_change_target():
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft, read_chapter_draft
    contract,bound,evidence=inputs()
    prepared=prepare_chapter_draft(contract,bound,(evidence,))
    output={'chapter_contract_id':contract.chapter_contract_id,'node_id':contract.semantic_node_id,
        'blocks':[{'kind':'paragraph','block_id':'block:one','text':'合成测试正文。','evidence_refs':[evidence.evidence_unit_id]}]}
    candidate=read_chapter_draft(prepared,output)
    assert candidate.blocks[0].text=='合成测试正文。'
    assert candidate.known_evidence_ids==(evidence.evidence_unit_id,)
    with pytest.raises(ValueError,match='chapter_source_universe_mismatch'):
        read_chapter_draft(prepared,{**output,'known_evidence_ids':['invented:evidence']})
    with pytest.raises(ValueError,match='chapter_output_binding_mismatch'):
        read_chapter_draft(prepared,{**output,'node_id':'node:other'})
    with pytest.raises(ValueError,match='chapter_draft_empty'):
        read_chapter_draft(prepared,{**output,'blocks':[]})


@pytest.mark.parametrize('output',[None,[],"not an object"])
def test_non_object_model_json_has_a_structured_error(output):
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft, read_chapter_draft
    contract,bound,evidence=inputs()
    with pytest.raises(ValueError,match='chapter_output_schema_invalid'):
        read_chapter_draft(prepare_chapter_draft(contract,bound,(evidence,)),output)


def test_bound_input_from_an_older_contract_cannot_use_revised_same_id_contract():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    from test_chapter_fact_binding import confirmed_study, bindings_for_objective
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft
    contract,_,evidence=inputs()
    study=confirmed_study({'study.objective':'合成研究目的'})
    bound=bind_chapter_input(study,contract,bindings_for_objective())
    prepare_chapter_draft(contract,bound,(evidence,))
    revised=contract.model_copy(update={'word_rules':contract.word_rules.model_copy(update={'required_styles':('Changed Style',)})})
    # Matching the visible formatting fields must not disguise an old binding.
    disguised=bound.model_copy(update={'word_rules':revised.word_rules})
    with pytest.raises(ValueError,match='chapter_input_binding_mismatch'):
        prepare_chapter_draft(revised,disguised,(evidence,))


def test_applicable_writer_receives_projected_contract_and_same_bound_snapshot():
    from app.protocol_workflow.registries.applicability import bind_applicable_chapter, ApplicabilityResolutionError
    from app.protocol_workflow.registries.fact_bindings import FactBindingCatalog
    from test_chapter_applicability import interim_case, real_rule_catalog
    from test_chapter_fact_binding import confirmed_study
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft
    contract,_=interim_case()
    bindings=FactBindingCatalog.model_validate_json((REAL_TEMPLATE_DIR/'fact_bindings.json').read_text()).bindings
    effective,bound=bind_applicable_chapter(confirmed_study({'statistics.interim.applicable':False}),
        contract,bindings,rules=real_rule_catalog().rules)
    prepared=prepare_chapter_draft(effective,bound,())
    assert prepared.to_payload()['chapter_input']['resolved_facts']=={'statistics.interim.applicable':False}
    assert bound.chapter_contract_sha256==effective.material_sha256()
    assert effective.conditional_applicability_rules==()
    with pytest.raises(ApplicabilityResolutionError,match='conditional_applicability_unresolved'):
        bind_applicable_chapter(confirmed_study({'study.synthetic':True}),contract,bindings,rules=real_rule_catalog().rules)


def test_coordinator_checks_bound_study_metadata_before_starting_runtime():
    from app.protocol_workflow.agent3.coordinator import ChapterDraftCoordinator
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    from test_chapter_fact_binding import confirmed_study, bindings_for_objective
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    contract,_,evidence=inputs()
    study=confirmed_study({'study.objective':'合成研究目的'})
    prepared=prepare_chapter_draft(contract,bind_chapter_input(study,contract,bindings_for_objective()),(evidence,))
    kwargs=dict(project_id=study.project_id,branch_id='main',study_definition_id=study.study_definition_id,
        study_revision_sha256=study_revision_hash(study),runtime=None)
    assert ChapterDraftCoordinator(**kwargs).run_id(prepared).startswith('chapter-draft:')
    for changed in ({'project_id':'project:other'},{'study_definition_id':'study:other'},
                    {'study_revision_sha256':'f'*64}):
        with pytest.raises(ValueError,match='chapter_study_binding_mismatch'):
            ChapterDraftCoordinator(**{**kwargs,**changed}).start(prepared)


def test_study_chapter_preparation_uses_current_catalog_and_actual_study():
    from app.protocol_workflow.agent3.chapter_draft import prepare_study_chapter
    from app.protocol_workflow.registries.template_runtime import load_current_template
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    from app.protocol_workflow.canonical.study_definition import study_revision_hash
    template=load_current_template(REAL_TEMPLATE_DIR)
    study=confirmed_study({'statistics.interim.applicable':False})
    from test_chapter_applicability import interim_case
    contract,_=interim_case()
    prepared=prepare_study_chapter(template,study,contract.semantic_node_id,())
    body=prepared.to_payload()
    assert body['chapter_input']['study_sha256']==study_revision_hash(study)
    assert body['chapter_input']['project_id']==study.project_id
    assert body['chapter_input']['resolved_facts']=={'statistics.interim.applicable':False}
    with pytest.raises(ValueError,match='chapter_node_unknown'):
        prepare_study_chapter(template,study,'node:missing',())


def test_whole_chapter_not_applicable_does_not_create_a_writing_request():
    from app.protocol_workflow.agent3.chapter_draft import prepare_study_chapter
    from app.protocol_workflow.registries.template_runtime import load_current_template
    from test_all_chapter_contracts import REAL_TEMPLATE_DIR
    from test_chapter_fact_binding import confirmed_study
    template=load_current_template(REAL_TEMPLATE_DIR)
    with pytest.raises(ValueError,match='chapter_not_applicable'):
        prepare_study_chapter(template,confirmed_study({'appendix.ecog_assessment_applicable':False,'appendix.ecog_applicability_decision_record':'synthetic exclusion decision'}),
            'v2_n_16_x1',())


@pytest.mark.parametrize('target',['cell','note'])
def test_generated_table_nested_references_must_belong_to_supplied_evidence(target):
    from app.protocol_workflow.agent3.chapter_draft import prepare_chapter_draft,read_chapter_draft
    from test_ordered_chapter_draft import _2x2_table
    contract,bound,evidence=inputs()
    units=tuple(evidence.model_copy(update={'evidence_unit_id':identity})
        for identity in ('evidence:e1','evidence:e2','evidence:note'))
    prepared=prepare_chapter_draft(contract,bound,units)
    table=_2x2_table(table_id='table:one',block_id='block:one',title='合成表',
        source_locator='docx:t1',cell_prefix='cell',note_id='note:one').model_dump(mode='json')
    table['notes'][0]['source_refs']=['evidence:note']
    output={'chapter_contract_id':contract.chapter_contract_id,'node_id':contract.semantic_node_id,
        'blocks':[{'kind':'table','block_id':'block:one','table':table,'evidence_refs':['evidence:e1']}]}
    assert read_chapter_draft(prepared,output).blocks[0].kind=='table'
    if target=='cell':table['rows'][0]['cells'][0]['provenance_lineage']=['evidence:invented']
    else:table['notes'][0]['source_refs']=['evidence:invented']
    with pytest.raises(ValueError,match='chapter_table_reference_unknown'):
        read_chapter_draft(prepared,output)
