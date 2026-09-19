"""T04/R5: two writing entries converge on one research model.

Entry A (imported synopsis/sources) and entry B (from-scratch brief) use the
same seed chain, the same StudyDefinition command path and the same fact
store.  Extracted candidates are prefilled for point-and-click confirmation —
the user never retypes what the synopsis already says (A02), a zero-source
start pins a real user-input identity without fabricated source ids (A03),
and reference-role material only becomes a fact through an explicit user
selection (A08).
"""
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from app.protocol_workflow.agent1.research_seed import (
    prepare_seed_request, read_seed_candidates)
from app.protocol_workflow.agent2.clinical_worker import prepare_regimen_request


def _entry_b_prepared(brief='从零开始：合成药D在2型糖尿病受试者中的II期研究。'):
    intake = prepare_seed_request(brief, ())
    seed = read_seed_candidates(intake, {"fields": {}})
    return prepare_regimen_request(intake, seed)


def _creation(prepared, *, project_id='project:dual', study='study:dual'):
    from app.protocol_workflow.application.research_context import (
        prepare_research_context_creation)
    return prepare_research_context_creation(project_id=project_id,
        study_definition_id=study, seed_run_id='seed:dual', prepared=prepared,
        operation_id='operation:dual', actor_id='medical_manager',
        decided_at=datetime(2026, 9, 19, tzinfo=timezone.utc))


def test_entry_b_without_sources_pins_real_user_input_identity():
    prepared = _entry_b_prepared()
    payload = prepared.to_payload()
    intake = payload['source_intake']
    assert intake['sources'] == [], 'from-scratch design must not fabricate sources'
    assert intake['user_brief'].startswith('从零开始')
    command = _creation(prepared)
    assert set(command.initial_facts) == {'research.input_context'}
    assert command.initial_facts['research.input_context']['user_brief'].startswith('从零开始')


def test_both_entries_issue_the_same_study_command_shape():
    from test_clinical_design_worker import prepared_reference
    entry_a, _ = prepared_reference()
    entry_b = _entry_b_prepared()
    command_a = _creation(entry_a, study='study:entry-a')
    command_b = _creation(entry_b, study='study:entry-b')
    assert type(command_a) is type(command_b)
    assert set(command_a.initial_facts) == set(command_b.initial_facts) == {'research.input_context'}
    assert command_a.decision_record.decision_key == command_b.decision_record.decision_key
    # The only difference is input provenance inside the shared context fact.
    context_a = command_a.initial_facts['research.input_context']
    context_b = command_b.initial_facts['research.input_context']
    assert set(context_a) == set(context_b)
    # Neither entry auto-adopts medical facts from its sources.
    forbidden = ('framing.investigational_product', 'framing.indication',
                 'intervention.dose_regimen', 'picos.primary_endpoint')
    assert not set(command_a.initial_facts) & set(forbidden)
    assert not set(command_b.initial_facts) & set(forbidden)


class _StubCoordinator:
    project_id = 'project:dual'

    def __init__(self, fields):
        self._read = {'validation': {
            'valid': True,
            'raw_response': {'output_sha256': 'a' * 64},
            'proposal': {'fields': fields}}}

    def read(self, seed_run_id):
        return self._read


def _intent(fields, selections, **kwargs):
    from app.protocol_workflow.agent2.research_intent import prepare_research_intent_adoption
    return prepare_research_intent_adoption(_StubCoordinator(fields), 'seed:dual',
        selections=selections, study_definition_id='study:dual',
        operation_id='operation:intent', expected_revision=1,
        snapshot_sha256='b' * 64, actor_id='medical_manager',
        decided_at=datetime(2026, 9, 19, tzinfo=timezone.utc),
        reason='确认研究基本信息', **kwargs)


FIELDS = {'indication': [
    {'candidate': '2型糖尿病', 'source_support': 'from_sources'},
    {'candidate': '参考候选适应症', 'source_support': 'reference_only'},
]}


def test_prefill_confirmation_selects_extracted_candidates_without_retyping():
    command = _intent(FIELDS, {'indication': 0})
    assert command.fact_updates == {'framing.indication': '2型糖尿病'}
    assert command.decision_record.actor_type.value == 'user'
    assert not command.decision_record.reason or isinstance(command.decision_record.reason, str)


def test_reference_role_candidate_only_through_explicit_selection():
    import pytest
    # No selection and no edits: nothing can be auto-adopted from sources.
    with pytest.raises(ValueError):
        _intent(FIELDS, {})
    # A reference-role candidate becomes a fact only by explicit index pick.
    command = _intent(FIELDS, {'indication': 1})
    assert command.fact_updates == {'framing.indication': '参考候选适应症'}
    assert command.decision_record.actor_type.value == 'user'
    # Out-of-range indexes fail loudly instead of silently defaulting.
    with pytest.raises(ValueError):
        _intent(FIELDS, {'indication': 5})
