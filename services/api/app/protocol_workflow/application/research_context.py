"""Prepare the explicit writing request as a baseline, without medical adoption."""
import hashlib
from app.protocol_workflow.agent2.input_context import regimen_input_context
from app.protocol_workflow.canonical.hashing import canonical_json
from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord
from .commands import CreateStudyDefinitionCommand, study_definition_genesis_snapshot


def prepare_research_context_creation(*, project_id, study_definition_id, seed_run_id,
                                      prepared, operation_id, actor_id, decided_at):
    context = regimen_input_context(prepared)
    facts = {'research.input_context': context}
    seed_sha = context['seed_proposal_sha256']
    reason = '开始本次方案写作，记录所选资料和写作说明'
    snapshot = study_definition_genesis_snapshot(study_definition_id=study_definition_id,
        project_id=project_id, normalized_seed_id=seed_run_id,
        normalized_seed_sha256=seed_sha, facts=facts, decided_at=decided_at)
    identity = hashlib.sha256(canonical_json([project_id, study_definition_id, operation_id]).encode()).hexdigest()
    option = 'research-request-option:' + hashlib.sha256(canonical_json(context).encode()).hexdigest()
    record = DecisionRecord(decision_record_id='research-request-decision:' + identity,
        decision_key='decision:research-request', snapshot_sha256=snapshot,
        expected_state_revision=0, state_revision=1, option_ids=(option,), selected_option_id=option,
        actor_type=ActorType.USER, actor_id=actor_id, reason=reason, decided_at=decided_at)
    return CreateStudyDefinitionCommand(project_id=project_id, study_definition_id=study_definition_id,
        idempotency_key=operation_id, expected_revision=0, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decision_record=record, normalized_seed_id=seed_run_id,
        normalized_seed_sha256=seed_sha, initial_facts=facts)


def prepare_research_context_update(*, project_id, study_definition_id, seed_run_id,
                                    prepared, operation_id, actor_id, decided_at,
                                    expected_revision, snapshot_sha256):
    """An explicit new input selection changes metadata, never medical parameters."""
    from .commands import ApplyStudyDecisionCommand
    from app.protocol_workflow.canonical.decision_inputs import DecisionInputRef
    baseline = prepare_research_context_creation(project_id=project_id,
        study_definition_id=study_definition_id, seed_run_id=seed_run_id, prepared=prepared,
        operation_id=operation_id, actor_id=actor_id, decided_at=decided_at)
    reason = '使用本次所选资料和写作说明继续，保留已有研究内容'
    record = DecisionRecord.model_validate({**baseline.decision_record.model_dump(mode='json'),
        'snapshot_sha256': snapshot_sha256, 'expected_state_revision': expected_revision,
        'state_revision': expected_revision + 1, 'reason': reason})
    return ApplyStudyDecisionCommand(project_id=project_id, study_definition_id=study_definition_id,
        idempotency_key=operation_id, expected_revision=expected_revision, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decision_record=record,
        fact_updates=baseline.initial_facts, revise_confirmed_facts=True,
        decision_input_refs=(DecisionInputRef(fact_path='research.input_context'),))
