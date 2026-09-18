"""Confirm selected basic research information without adopting high-risk parameters."""
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest


def fixture():
    state={'validation':{'valid':True,'proposal':{'fields':{
        'research_drug':[{'candidate':['合成药物X','合成药物Y']}],
        'indication':[{'candidate':'合成适应症甲'},{'candidate':'合成适应症乙'}],
        'clinical_phase':[{'candidate':'Ⅱ期'}],
        'anticipated_dose':[{'candidate':'合成剂量'}],
    }},'raw_response':{'output_sha256':'b'*64}}}
    coordinator=SimpleNamespace(project_id='project:synthetic',read=lambda run:state)
    intent=dict(study_definition_id='study:synthetic',operation_id='intent:one',expected_revision=1,
        snapshot_sha256='a'*64,actor_id='user:one',decided_at=datetime(2026,9,13,tzinfo=timezone.utc),reason='确认本次研究信息')
    return coordinator,intent


def test_explicit_indices_select_saved_values_and_preserve_types():
    from app.protocol_workflow.agent2.research_intent import prepare_research_intent_adoption
    coordinator,intent=fixture()
    selected={'research_drug':0,'indication':1,'clinical_phase':0}
    result=prepare_research_intent_adoption(coordinator,'seed:one',selections=selected,**intent)
    assert result.fact_updates=={'framing.investigational_product':['合成药物X','合成药物Y'],
        'framing.indication':'合成适应症乙','framing.study_phase':'Ⅱ期'}
    assert result==prepare_research_intent_adoption(coordinator,'seed:one',selections=selected,**intent)
    assert result.decision_record.actor_type.value=='user'
    assert result.template_adoption.template_id=='tp_ma_07_v2'
    other=prepare_research_intent_adoption(coordinator,'seed:one',selections={**selected,'indication':0},**intent)
    assert other.decision_record.selected_option_id!=result.decision_record.selected_option_id


@pytest.mark.parametrize('selections',[{}, {'anticipated_dose':0},{'comparator':0},{'populations':0},
                                      {'indication':True},{'indication':-1},{'indication':9}])
def test_invalid_or_high_risk_selections_do_not_form_a_basic_information_decision(selections):
    from app.protocol_workflow.agent2.research_intent import prepare_research_intent_adoption
    coordinator,intent=fixture()
    with pytest.raises(ValueError,match='research_intent_selection_invalid'):
        prepare_research_intent_adoption(coordinator,'seed:one',selections=selections,**intent)


def test_explicit_user_edit_is_preserved_and_changes_original_choice_identity():
    from app.protocol_workflow.agent2.research_intent import prepare_research_intent_adoption
    coordinator,intent=fixture()
    original=prepare_research_intent_adoption(coordinator,'seed:one',selections={'research_drug':0},**intent)
    edits={'research_drug':['用户修正药物甲','用户修正药物乙']}
    result=prepare_research_intent_adoption(coordinator,'seed:one',selections={'research_drug':0},user_edits=edits,**intent)
    assert result.fact_updates=={'framing.investigational_product':edits['research_drug']}
    assert result.decision_record.selected_option_id!=original.decision_record.selected_option_id
    assert prepare_research_intent_adoption(coordinator,'seed:one',selections={'research_drug':0},user_edits={},**intent)==original
    assert coordinator.read('seed:one')['validation']['proposal']['fields']['research_drug'][0]['candidate']==['合成药物X','合成药物Y']


@pytest.mark.parametrize('edits',[{'anticipated_dose':'20 mg'},{'research_drug':''},
    {'research_drug':[]},{'research_drug':['']},{'research_drug':True}])
def test_basic_user_edits_do_not_bypass_high_risk_cards_or_store_empty_values(edits):
    from app.protocol_workflow.agent2.research_intent import prepare_research_intent_adoption
    coordinator,intent=fixture()
    with pytest.raises(ValueError,match='research_intent_edit_invalid'):
        prepare_research_intent_adoption(coordinator,'seed:one',selections={'research_drug':0},user_edits=edits,**intent)
