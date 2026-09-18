"""Compile explicit choices of basic research information from a stored seed."""
import hashlib
from copy import deepcopy
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.decision_inputs import DecisionInputRef
from app.protocol_workflow.application.commands import ApplyStudyDecisionCommand, TemplateAdoptionIntent
from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord

# High-risk regimen, comparator and core population decisions have their own cards.
BASIC_RESEARCH_FIELDS = {
    'research_drug': 'framing.investigational_product',
    'indication': 'framing.indication',
    'clinical_phase': 'framing.study_phase',
    'target_or_mechanism': 'framing.target_mechanism',
}


def _user_edits(value):
    if value is None:
        return {}
    if not isinstance(value,dict) or set(value)-BASIC_RESEARCH_FIELDS.keys():
        raise ValueError('research_intent_edit_invalid')
    for item in value.values():
        values=item if isinstance(item,list) else [item]
        if not values or any(not isinstance(text,str) or not text.strip() for text in values):
            raise ValueError('research_intent_edit_invalid')
    return deepcopy(value)


def prepare_research_intent_adoption(coordinator, seed_run_id, *, selections,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason, user_edits=None):
    edits=_user_edits(user_edits)
    validation = coordinator.read(seed_run_id).get('validation')
    if not validation or validation.get('valid') is not True:
        raise ValueError('research_intent_source_unresolved')
    if not isinstance(selections, dict) or not (selections or edits) or set(selections) - BASIC_RESEARCH_FIELDS.keys():
        raise ValueError('research_intent_selection_invalid')
    fields = validation['proposal']['fields']
    updates = {}
    for field, index in sorted(selections.items()):
        candidates = fields.get(field, ())
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(candidates):
            raise ValueError('research_intent_selection_invalid')
        updates[BASIC_RESEARCH_FIELDS[field]] = deepcopy(candidates[index]['candidate'])
    updates.update({BASIC_RESEARCH_FIELDS[field]:value for field,value in edits.items()})
    record = research_intent_record(coordinator, seed_run_id, selections=selections,
        study_definition_id=study_definition_id, operation_id=operation_id,
        expected_revision=expected_revision, snapshot_sha256=snapshot_sha256,
        actor_id=actor_id, decided_at=decided_at, reason=reason, user_edits=edits)
    return ApplyStudyDecisionCommand(project_id=coordinator.project_id,
        study_definition_id=study_definition_id, idempotency_key=operation_id,
        expected_revision=expected_revision, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decision_record=record,
        fact_updates=updates, revise_confirmed_facts=True,
        template_adoption=TemplateAdoptionIntent(template_id='tp_ma_07_v2'),
        decision_input_refs=tuple(DecisionInputRef(fact_path=path)
            for path in sorted((*updates, 'research.input_context'))))


def research_intent_record(coordinator, seed_run_id, *, selections,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason, user_edits=None):
    """Stable original choice identity, independent of later fact compilation."""
    validation = coordinator.read(seed_run_id).get('validation')
    if not validation or not validation.get('raw_response'):
        raise ValueError('research_intent_source_unresolved')
    output_sha = validation['raw_response']['output_sha256']
    material=[seed_run_id,output_sha,selections]
    edits=_user_edits(user_edits)
    if edits:
        material.append({'user_edits':edits})
    option = 'research-intent-option:' + hashlib.sha256(canonical_json(material).encode()).hexdigest()
    identity = 'research-intent-decision:' + hashlib.sha256(canonical_json(
        [coordinator.project_id, study_definition_id, operation_id]).encode()).hexdigest()
    record = DecisionRecord(decision_record_id=identity, decision_key='decision:research-intent',
        snapshot_sha256=snapshot_sha256, expected_state_revision=expected_revision,
        state_revision=expected_revision + 1, option_ids=(option,), selected_option_id=option,
        actor_type=ActorType.USER, actor_id=actor_id, reason=reason, decided_at=decided_at)
    return record
