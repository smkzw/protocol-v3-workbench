"""Pin the actual target study's clinical read set before design generation."""
from copy import deepcopy
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json
from packages.contracts.workbench_contracts.protocol_v3 import StableId
from pydantic import TypeAdapter
from .clinical_worker import PreparedRegimenRequest


def regimen_questions(proposal):
    """Return stable question objects for new and historical proposal receipts."""
    result = []
    for index, raw in enumerate(proposal.get('questions') or []):
        if isinstance(raw, str):
            result.append({'question_id': f'legacy:{index}', 'question': raw,
                           'recommended_answer': '', 'options': [],
                           'fact_path': 'research.regimen_clarifications'})
            continue
        if not isinstance(raw, dict) or not isinstance(raw.get('question'), str):
            raise ValueError('regimen_question_invalid')
        question_id = raw.get('question_id')
        if not isinstance(question_id, str) or not question_id:
            question_id = 'regimen-question:' + hashlib.sha256(
                raw['question'].strip().encode('utf-8')).hexdigest()[:24]
        result.append({**raw, 'question_id': question_id,
                       'fact_path': 'research.regimen_clarifications'})
    return result


def _regimen_answers_record(coordinator, run_id, *, answers,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason):
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType, DecisionRecord
    state = coordinator.read(run_id)
    validation = state.get('validation') or {}
    output_sha = (validation.get('raw_response') or {}).get('output_sha256')
    if not output_sha:
        raise ValueError('regimen_question_source_unresolved')
    option = 'regimen-answers-option:' + hashlib.sha256(canonical_json(
        [run_id, output_sha, answers]).encode()).hexdigest()
    identity = 'regimen-answers-decision:' + hashlib.sha256(canonical_json(
        [coordinator.project_id, study_definition_id, operation_id]).encode()).hexdigest()
    return DecisionRecord(decision_record_id=identity,
        decision_key='decision:regimen-clarifications', snapshot_sha256=snapshot_sha256,
        expected_state_revision=expected_revision, state_revision=expected_revision + 1,
        option_ids=(option,), selected_option_id=option, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decided_at=decided_at)


def prepare_regimen_answers(coordinator, run_id, *, answers, current_facts,
        study_definition_id, operation_id, expected_revision, snapshot_sha256,
        actor_id, decided_at, reason):
    from app.protocol_workflow.application.commands import ApplyStudyDecisionCommand, TemplateAdoptionIntent
    from app.protocol_workflow.canonical.decision_inputs import DecisionInputRef
    from packages.contracts.workbench_contracts.protocol_v3 import ActorType
    state = coordinator.read(run_id)
    proposal = ((state.get('validation') or {}).get('proposal') or {})
    questions = regimen_questions(proposal)
    expected = {item['question_id'] for item in questions}
    if not expected or set(answers) != expected or any(
            not isinstance(value, str) or not value.strip() for value in answers.values()):
        raise ValueError('regimen_question_answers_incomplete')
    existing = current_facts.get('research.regimen_clarifications', {})
    if not isinstance(existing, dict):
        raise ValueError('regimen_question_facts_invalid')
    merged = deepcopy(existing)
    for item in questions:
        merged[item['question_id']] = {
            'question': item['question'], 'answer': answers[item['question_id']].strip(),
            'source': 'user_confirmation', 'workflow_run_id': run_id,
        }
    record = _regimen_answers_record(coordinator, run_id, answers=answers,
        study_definition_id=study_definition_id, operation_id=operation_id,
        expected_revision=expected_revision, snapshot_sha256=snapshot_sha256,
        actor_id=actor_id, decided_at=decided_at, reason=reason)
    return ApplyStudyDecisionCommand(project_id=coordinator.project_id,
        study_definition_id=study_definition_id, idempotency_key=operation_id,
        expected_revision=expected_revision, actor_type=ActorType.USER,
        actor_id=actor_id, reason=reason, decision_record=record,
        fact_updates={'research.regimen_clarifications': merged},
        revise_confirmed_facts=True,
        template_adoption=TemplateAdoptionIntent(template_id='tp_ma_07_v2'),
        decision_input_refs=(DecisionInputRef(fact_path='research.input_context'),))


def prepare_regimen_answers_recovery(coordinator, run_id, **intent):
    from app.protocol_workflow.application.queries import RecoverStudyDecisionQuery
    record = _regimen_answers_record(coordinator, run_id, **intent)
    return RecoverStudyDecisionQuery(project_id=coordinator.project_id,
        study_definition_id=intent['study_definition_id'],
        idempotency_key=intent['operation_id'], decision_record=record)


def clinical_study_facts(facts):
    return {key: value for key, value in facts.items()
            if key not in {'research.input_context', 'research.regimen_producer'}}


def validate_regimen_study_input(prepared, *, study_definition_id, facts):
    bound = prepared.to_payload().get('confirmed_study')
    if bound is None:
        # Historical receipts are recovered before this fresh-adoption check.
        # A reference-only suggestion has never read existing clinical facts.
        if clinical_study_facts(facts):
            raise ValueError('regimen_clinical_context_not_read')
        return
    if bound['study_definition_id'] != study_definition_id:
        raise ValueError('regimen_target_study_changed')
    if canonical_json(bound['facts']) != canonical_json(clinical_study_facts(facts)):
        raise ValueError('regimen_clinical_facts_changed')


def bind_regimen_study_input(prepared, *, study_definition_id, facts):
    TypeAdapter(StableId).validate_python(study_definition_id)
    payload = prepared.to_payload()
    # These two records describe input selection and the previous producer;
    # neither is a clinical parameter. Preserve every other fact, even unknown
    # vocabulary, so old study values cannot silently disappear from the read set.
    clinical_facts = clinical_study_facts(facts)
    payload['confirmed_study'] = {
        'study_definition_id': study_definition_id, 'facts': clinical_facts,
    }
    payload['instruction'] += (
        '\nconfirmed_study是目标研究已确认的事实，seed候选与历史参考不等于本研究事实。'
        '逐项核对已有给药及相关事实；与参考资料冲突时明确列出冲突和实际待决选择，'
        '不能静默覆盖、忽略旧值或假定用户已经同意修改。'
    )
    text = canonical_json(payload)
    return PreparedRegimenRequest(text, hashlib.sha256(text.encode()).hexdigest())
