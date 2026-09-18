"""Compile seed-candidate design cards: core population and comparator choice.

Same explicit-selection pattern as the basic research information card, but
for the two design decisions whose candidates already exist in the stored
seed. Endpoints, estimand, sample size, NI margin and interim planning need a
design producer pass and have their own workflow; they are not compiled here.
No selection is adopted without the caller's explicit human confirmation
through the existing application/CAS command path.
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

#: seed field -> canonical fact path written by this card.
CARD_FIELDS = {
    'core_population': {
        'seed_field': 'populations',
        'fact_path': 'picos.population_summary',
        'decision_key': 'decision:core-population',
    },
    'comparator': {
        'seed_field': 'comparator',
        'fact_path': 'framing.structured_design.comparator_type',
        'decision_key': 'decision:comparator',
    },
}

#: Medical validity scope per card (see canonical.decision_inputs docstring).
CARD_CONFIRMATION_DEPENDENCIES = {
    'decision:core-population': (
        ConfirmationDependency(
            fact_path='framing.indication',
            rationale='核心人群必须与适应症的患病人群一致，适应症变化时人群定义需重新医学评估。',
        ),
        ConfirmationDependency(
            fact_path='framing.study_phase',
            rationale='期别决定人群范围（健康志愿者仅限Ⅰ期等），期别变化影响人群适用性。',
        ),
    ),
    'decision:comparator': (
        ConfirmationDependency(
            fact_path='framing.study_phase',
            rationale='对照选择受期别与现有标准治疗约束，期别变化时需重新评估对照设计。',
        ),
        ConfirmationDependency(
            fact_path='framing.indication',
            rationale='对照必须是该适应症的现行可行治疗选择，适应症变化影响对照的医学合理性。',
        ),
    ),
}


def card_field_candidates(coordinator, seed_run_id, card):
    """Read stored validated seed candidates for one card's field, read-only."""
    if card not in CARD_FIELDS:
        raise ValueError('design_card_unknown')
    validation = coordinator.read(seed_run_id).get('validation')
    if not validation or validation.get('valid') is not True:
        raise ValueError('design_card_source_unresolved')
    return deepcopy(validation['proposal']['fields'].get(CARD_FIELDS[card]['seed_field'], []))


def prepare_design_card_adoption(coordinator, seed_run_id, card, *, selection_index,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason, user_edit=None):
    """Translate an explicit card choice into the existing adoption command."""
    spec = CARD_FIELDS.get(card)
    if spec is None:
        raise ValueError('design_card_unknown')
    validation = coordinator.read(seed_run_id).get('validation')
    if not validation or validation.get('valid') is not True:
        raise ValueError('design_card_source_unresolved')
    candidates = validation['proposal']['fields'].get(spec['seed_field'], [])
    edit = None
    if user_edit is not None:
        if not isinstance(user_edit, str) or not user_edit.strip():
            raise ValueError('design_card_edit_invalid')
        edit = user_edit.strip()
    if selection_index is None:
        if edit is None:
            raise ValueError('design_card_selection_invalid')
        value = edit
    else:
        if isinstance(selection_index, bool) or not isinstance(selection_index, int) \
                or not 0 <= selection_index < len(candidates):
            raise ValueError('design_card_selection_invalid')
        value = deepcopy(candidates[selection_index]['candidate'])
        if isinstance(value, list):
            if edit is not None:
                raise ValueError('design_card_edit_invalid')
        elif edit is not None:
            value = edit
    updates = {spec['fact_path']: value}
    record = _design_card_record(coordinator, seed_run_id, card,
        selection_index=selection_index, user_edit=edit,
        study_definition_id=study_definition_id, operation_id=operation_id,
        expected_revision=expected_revision, snapshot_sha256=snapshot_sha256,
        actor_id=actor_id, decided_at=decided_at, reason=reason)
    return ApplyStudyDecisionCommand(project_id=coordinator.project_id,
        study_definition_id=study_definition_id, idempotency_key=operation_id,
        expected_revision=expected_revision, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decision_record=record,
        fact_updates=updates, revise_confirmed_facts=True,
        template_adoption=TemplateAdoptionIntent(template_id='tp_ma_07_v2'),
        decision_input_refs=(DecisionInputRef(fact_path=spec['fact_path']),
            DecisionInputRef(fact_path='research.input_context')),
        confirmation_dependencies=CARD_CONFIRMATION_DEPENDENCIES[spec['decision_key']])


def _design_card_record(coordinator, seed_run_id, card, *, selection_index, user_edit,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason):
    from app.protocol_workflow.canonical.hashing import canonical_json
    validation = coordinator.read(seed_run_id).get('validation')
    output_sha = ((validation or {}).get('raw_response') or {}).get('output_sha256')
    if not output_sha:
        raise ValueError('design_card_source_unresolved')
    option = 'design-card-option:' + hashlib.sha256(canonical_json(
        [seed_run_id, output_sha, card, selection_index, user_edit]).encode()).hexdigest()
    identity = CARD_FIELDS[card]['decision_key'] + '-record:' + hashlib.sha256(
        canonical_json([coordinator.project_id, study_definition_id, operation_id]).encode()
    ).hexdigest()
    return DecisionRecord(decision_record_id=identity,
        decision_key=CARD_FIELDS[card]['decision_key'],
        snapshot_sha256=snapshot_sha256, expected_state_revision=expected_revision,
        state_revision=expected_revision + 1, option_ids=(option,),
        selected_option_id=option, actor_type=ActorType.USER, actor_id=actor_id,
        reason=reason, decided_at=decided_at)
