"""Whole manuscript accounting must not silently omit unresolved chapters."""
import pytest
from dataclasses import replace
from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from test_chapter_fact_binding import confirmed_study
from app.protocol_workflow.registries.template_runtime import load_current_template


def test_plan_accounts_for_every_carrier_in_document_order_without_mutating_study():
    from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
    template=load_current_template(REAL_TEMPLATE_DIR)
    study=confirmed_study({'statistics.interim.applicable':False,
        'appendix.ecog_assessment_applicable':False,
        'appendix.ecog_applicability_decision_record':'synthetic exclusion'})
    before=study.model_dump_json()
    plan=plan_manuscript_chapters(template,study)
    assert tuple(item['node_id'] for item in plan['chapters'])==template.chapter_order
    assert len(plan['chapters'])==len(template.registry.chapters)
    ecog=next(item for item in plan['chapters'] if item['node_id']=='v2_n_16_x1')
    assert ecog['status']=='not_applicable'
    assert any(item['status']=='needs_information' for item in plan['chapters'])
    assert plan['all_applicable_inputs_ready'] is False
    assert study.model_dump_json()==before
    assert plan==plan_manuscript_chapters(template,study)


def test_unknown_whole_chapter_is_not_excluded_or_dispatched():
    from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
    template=load_current_template(REAL_TEMPLATE_DIR)
    chapter=next(e for e in template.registry.chapters if e.node_id=='v2_n_16_x1')
    template=replace(template,registry=template.registry.model_copy(update={'chapters':(chapter,)}),
        chapter_order=(chapter.node_id,))
    plan=plan_manuscript_chapters(template,confirmed_study({'study.synthetic':True}))
    assert plan['chapters'][0]['status']=='needs_information'
    assert plan['chapters'][0]['errors'][0]['code']=='conditional_applicability_unresolved'
    assert plan['all_applicable_inputs_ready'] is False


def test_proposed_facts_cannot_exclude_a_chapter_from_the_plan():
    import pytest
    from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
    from packages.contracts.workbench_contracts.protocol_v3 import CanonicalState
    template=load_current_template(REAL_TEMPLATE_DIR)
    study=confirmed_study({'appendix.ecog_assessment_applicable':False}).model_copy(
        update={'canonical_state':CanonicalState.PROPOSED})
    with pytest.raises(ValueError,match='applicability requires confirmed study facts'):
        plan_manuscript_chapters(template,study)


def test_phase_conflict_stays_visible_when_design_conditions_are_unknown():
    from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
    template=load_current_template(REAL_TEMPLATE_DIR)
    study=confirmed_study({'framing.study_phase':'Ⅱ期',
        'framing.structured_design.phase':'Ⅲ期'})
    before=study.model_dump_json()
    plan=plan_manuscript_chapters(template,study)
    for node in ('v2_n_1_1','v2_n_4_1'):
        item=next(item for item in plan['chapters'] if item['node_id']==node)
        assert item['status']=='invalid_input'
        assert any(error['code']=='fact_alias_conflict' for error in item['errors'])
    design=next(item for item in plan['chapters'] if item['node_id']=='v2_n_4_1')
    assert any(error['code']=='conditional_applicability_unresolved' for error in design['errors'])
    assert study.model_dump_json()==before


@pytest.mark.parametrize("conditions", [None,False,True])
def test_unresolved_design_keeps_unconditional_missing_and_all_present_errors(conditions):
    from app.protocol_workflow.agent3.manuscript_plan import plan_manuscript_chapters
    template=load_current_template(REAL_TEMPLATE_DIR)
    # A finite JSON value with a declared boolean type error must not mask phase conflicts.
    from dataclasses import replace
    bindings=tuple(b.model_copy(update={'value_type':'boolean'}) if b.fact_path=='framing.structured_design'
        else b for b in template.fact_catalog.bindings)
    template=replace(template,fact_catalog=template.fact_catalog.model_copy(update={'bindings':bindings}))
    study=confirmed_study({'framing.structured_design':'invalid boolean',
        'framing.study_phase':'Ⅱ期','framing.structured_design.phase':'Ⅲ期'})
    if conditions is not None:
        facts={**study.facts,'statistics.interim.applicable':conditions}
        if conditions is False:
            facts['framing.structured_design.features']={'stratification':False,'substudy':False}
        study=study.model_copy(update={'facts':facts})
    plan=plan_manuscript_chapters(template,study)
    item=next(i for i in plan['chapters'] if i['node_id']=='v2_n_4_1')
    assert item['status']=='invalid_input'
    codes={error['code'] for error in item['errors']}
    assert {'fact_type_mismatch','fact_alias_conflict','missing_required_fact'}<=codes
    if conditions is not False:
        assert 'conditional_applicability_unresolved' in codes
    missing={path for error in item['errors'] if error['code']=='missing_required_fact' for path in error['fact_paths']}
    assert 'framing.structured_design.arms' in missing
    assert 'framing.structured_design.stratification' not in missing
    assert ('framing.structured_design.interim_analysis' in missing) is (conditions is True)
