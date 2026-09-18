"""Compile confirmed design-element cards into canonical fact proposals.

Each card is one explicit human decision with its own decision key and
medical dependency declaration. Conditional cards (NI margin, interim) may
only be adopted when the confirmed design facts make them applicable — the
producer proposal itself cannot create that applicability. Nothing here
writes storage; the existing application/CAS command owns adoption.
"""
import hashlib
from copy import deepcopy

from app.protocol_workflow.canonical.decision_inputs import (
    ConfirmationDependency,
    DecisionInputRef,
)
from app.protocol_workflow.application.commands import (
    ApplyStudyDecisionCommand,
    TemplateAdoptionIntent,
)
from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord

#: card id -> fact writer (proposal section) + medical dependencies.
#: Writers return the canonical fact updates for one confirmed card.
def _objectives_writer(p):
    return {
        'picos.primary_objectives': deepcopy(p['objectives']['primary']),
        'picos.secondary_objectives': deepcopy(p['objectives']['secondary']),
    }


def _endpoint_writer(p):
    updates = {'picos.primary_endpoint': deepcopy(p['endpoint']['primary_endpoint'])}
    if p['endpoint'].get('key_secondary'):
        updates['efficacy.secondary_endpoint_measurements'] = deepcopy(p['endpoint']['key_secondary'])
    return updates


def _estimand_writer(p):
    e = p['estimand']
    ice_events = deepcopy(e.get('ice_events') or [])
    return {
        'estimand.primary.variable': deepcopy(e['variable']['text']),
        'estimand.primary.ice_strategy': deepcopy(e['ice_strategy']['text']),
        'estimand.primary.ice_rationale': {
            'ice_events': ice_events,
            'strategy_reason': deepcopy(e['ice_strategy']['reason']),
        },
        'estimand.primary.population_summary_measure': {
            'population': deepcopy(e['population']['text']),
            'summary_measure': deepcopy(e['summary_measure']['text']),
        },
    }


def _sample_size_writer(p):
    s = p['sample_size']
    return {
        'statistics.sample_size.assumptions': deepcopy(s['assumptions']),
        'statistics.sample_size.alpha': s['alpha'],
        'statistics.sample_size.power': s['power'],
        'statistics.sample_size.method': s['model'],
        'statistics.sample_size.attrition': s['attrition'],
        'statistics.sample_size.assumption_evidence': {
            'justification': deepcopy(s['justification']),
            'references': deepcopy(s.get('references') or []),
        },
    }


def _ni_writer(p):
    n = p['non_inferiority_margin']
    return {'framing.structured_design.noninferiority_margin_decision': {
        'margin': n['margin'],
        'clinical_justification': n['clinical_justification'],
        'references': deepcopy(n.get('references') or []),
    }}


def _interim_writer(p):
    i = p['interim_planning']
    return {
        'framing.structured_design.interim_analysis': True,
        'statistics.interim.applicable': True,
        'statistics.interim.timing': i['timing'],
        'statistics.interim.information_fraction': i['information_fraction'],
        'statistics.interim.purpose': i['purpose'],
        'statistics.interim.rules': i['decision_rule'],
        'statistics.interim.decision_responsibility': i['decision_responsibility'],
        'statistics.interim.final_analysis_impact': i['final_analysis_impact'],
        'statistics.interim.efficacy_alpha_spending': i.get('alpha_spending'),
    }


DESIGN_CARDS = {
    'objectives-endpoint': {
        'writers': (_objectives_writer, _endpoint_writer),
        'decision_key': 'decision:objectives-endpoint',
        'dependencies': (
            ConfirmationDependency(fact_path='framing.indication',
                rationale='研究目标与终点必须回答该适应症的临床问题，适应症变化时终点需重新选择。'),
            ConfirmationDependency(fact_path='picos.population_summary',
                rationale='终点定义与测量时点依赖目标人群特征，人群变化影响终点的医学合理性。'),
        ),
    },
    'estimand': {
        'writers': (_estimand_writer,),
        'decision_key': 'decision:estimand',
        'dependencies': (
            ConfirmationDependency(fact_path='picos.primary_endpoint',
                rationale='估计目标的变量即主要终点，终点变化时估计目标必须同步重建。'),
            ConfirmationDependency(fact_path='picos.population_summary',
                rationale='估计目标的人群属性来自核心人群定义，人群变化使原估计目标失效。'),
            ConfirmationDependency(fact_path='framing.structured_design.comparator_type',
                rationale='治疗属性包含对照安排，对照变化改变估计目标的治疗比较语义。'),
        ),
    },
    'sample-size': {
        'writers': (_sample_size_writer,),
        'decision_key': 'decision:sample-size',
        'dependencies': (
            ConfirmationDependency(fact_path='picos.primary_endpoint',
                rationale='样本量假设围绕主要终点的效应量与变异建立，终点变化需重新计算。'),
            ConfirmationDependency(fact_path='estimand.primary.variable',
                rationale='分析方法与估计目标变量绑定，估计目标变化影响样本量模型选择。'),
            ConfirmationDependency(fact_path='framing.structured_design.allocation_ratio',
                rationale='分配比直接进入样本量计算，分配比变化改变每组所需例数。'),
        ),
    },
    'non-inferiority-margin': {
        'writers': (_ni_writer,),
        'decision_key': 'decision:non-inferiority-margin',
        'dependencies': (
            ConfirmationDependency(fact_path='framing.structured_design.comparator_type',
                rationale='非劣效界值相对对照疗效定义，对照变化使原界值失去依据。'),
            ConfirmationDependency(fact_path='picos.primary_endpoint',
                rationale='界值以主要终点疗效差度量，终点变化需重新论证界值的临床可接受性。'),
        ),
    },
    'interim': {
        'writers': (_interim_writer,),
        'decision_key': 'decision:interim',
        'dependencies': (
            ConfirmationDependency(fact_path='picos.primary_endpoint',
                rationale='期中决策规则基于主要终点的疗效信息，终点变化需重新设计期中规则。'),
            ConfirmationDependency(fact_path='statistics.sample_size.alpha',
                rationale='期中alpha消耗与总alpha预算绑定，样本量卡的alpha确认变化时需重新分配。'),
        ),
    },
}

CONDITIONAL_CARDS = ('non-inferiority-margin', 'interim')


def available_design_cards(confirmed_facts, proposal):
    """Which cards the confirmed design facts make adoptable right now.

    A conditional card is available only when the proposal proposes it AND the
    confirmed facts do not contradict it. Unknown design facts leave the card
    unavailable-but-visible as a question instead of silently dropping it.
    """
    if proposal.get('status') != 'ready_for_review':
        return []
    design = confirmed_facts.get('framing.structured_design')
    design = design if isinstance(design, dict) else {}
    ni_fact = design.get('noninferiority_margin_decision')
    interim_fact = design.get('interim_analysis')
    cards = ['objectives-endpoint', 'estimand', 'sample-size']
    if proposal.get('non_inferiority_margin'):
        ni_denied = isinstance(ni_fact, str) and ni_fact.strip().lower() in ('false', '不适用', '无')
        if not ni_denied:
            cards.append('non-inferiority-margin')
    if proposal.get('interim_planning'):
        if interim_fact is not False:
            cards.append('interim')
    return cards


def prepare_design_card_adoption(coordinator, run_id, card, *, confirmed_facts, selections,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason):
    """Translate explicit card confirmation into the existing adoption command.

    ``confirmed_facts`` are the caller's authoritative read of the current
    StudyDefinition facts (the API layer reads them from storage); this module
    never invents or caches them. ``selections`` pins the exact option indexes
    the user confirmed, so the adopted value is reproducible from the
    persisted proposal alone.
    """
    spec = DESIGN_CARDS.get(card)
    if spec is None:
        raise ValueError('design_card_unknown')
    state = coordinator.read(run_id)
    validation = state.get('validation')
    if state.get('status') != 'ready_for_review' or not validation or validation.get('valid') is not True:
        raise ValueError('design_elements_unresolved')
    proposal = validation['proposal']
    if card not in available_design_cards(confirmed_facts, proposal):
        raise ValueError('design_card_not_applicable')
    if not isinstance(selections, dict) or not selections:
        raise ValueError('design_card_selection_invalid')
    _check_selections(card, proposal, selections)
    updates = {}
    for writer in spec['writers']:
        updates.update(writer(proposal))
    output_sha = validation['raw_response']['output_sha256']
    record = _design_card_record(coordinator, run_id, card, output_sha=output_sha,
        study_definition_id=study_definition_id, operation_id=operation_id,
        expected_revision=expected_revision, snapshot_sha256=snapshot_sha256,
        actor_id=actor_id, decided_at=decided_at, reason=reason)
    return ApplyStudyDecisionCommand(project_id=coordinator.project_id,
        study_definition_id=study_definition_id, idempotency_key=operation_id,
        expected_revision=expected_revision, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decision_record=record,
        fact_updates=updates, revise_confirmed_facts=True,
        template_adoption=TemplateAdoptionIntent(template_id='tp_ma_07_v2'),
        decision_input_refs=tuple(DecisionInputRef(fact_path=path)
            for path in sorted(updates)) + (DecisionInputRef(fact_path='research.input_context'),),
        confirmation_dependencies=spec['dependencies'])


def _check_selections(card, proposal, selections):
    """Selections must address every option-bearing field the card writes."""
    if card == 'objectives-endpoint':
        primary = proposal['objectives']['primary']
        ep = proposal['endpoint']['primary_endpoint']
        idx = selections.get('primary_objective')
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(primary):
            raise ValueError('design_card_selection_invalid')
        if selections.get('primary_endpoint_confirmed') is not True and not ep.get('text'):
            raise ValueError('design_card_selection_invalid')
        return
    if card == 'estimand':
        e = proposal['estimand']
        for key, option in (('treatment', e['treatment']), ('population', e['population']),
                            ('variable', e['variable']), ('ice_strategy', e['ice_strategy']),
                            ('summary_measure', e['summary_measure'])):
            chosen = selections.get(key)
            if chosen is True:
                continue
            options = option if isinstance(option, list) else [option]
            if isinstance(chosen, bool) or not isinstance(chosen, int) or not 0 <= chosen < len(options):
                raise ValueError('design_card_selection_invalid')
        return
    if card == 'sample-size':
        if selections.get('sample_size_confirmed') is not True:
            raise ValueError('design_card_selection_invalid')
        return
    if card == 'non-inferiority-margin':
        if selections.get('ni_margin_confirmed') is not True:
            raise ValueError('design_card_selection_invalid')
        return
    if card == 'interim':
        if selections.get('interim_confirmed') is not True:
            raise ValueError('design_card_selection_invalid')
        return
    raise ValueError('design_card_unknown')


def _design_card_record(coordinator, run_id, card, *, output_sha,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason):
    from app.protocol_workflow.canonical.hashing import canonical_json
    spec = DESIGN_CARDS[card]
    option = 'design-element-option:' + hashlib.sha256(canonical_json(
        [run_id, output_sha, card]).encode()).hexdigest()
    identity = spec['decision_key'] + '-record:' + hashlib.sha256(canonical_json(
        [coordinator.project_id, study_definition_id, operation_id]).encode()).hexdigest()
    return DecisionRecord(decision_record_id=identity,
        decision_key=spec['decision_key'], snapshot_sha256=snapshot_sha256,
        expected_state_revision=expected_revision,
        state_revision=expected_revision + 1, option_ids=(option,),
        selected_option_id=option, actor_type=ActorType.USER, actor_id=actor_id,
        reason=reason, decided_at=decided_at)
