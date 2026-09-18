"""Opening the writing workspace must not adopt historical medical candidates."""
from datetime import datetime, timezone
from test_clinical_design_worker import prepared_reference


def test_context_genesis_records_only_the_actual_writing_request():
    from app.protocol_workflow.application.research_context import prepare_research_context_creation
    prepared, _ = prepared_reference()
    command = prepare_research_context_creation(project_id='project:new', study_definition_id='study:new',
        seed_run_id='seed:saved', prepared=prepared, operation_id='operation:open',
        actor_id='medical_manager', decided_at=datetime(2026,9,13,tzinfo=timezone.utc))
    assert set(command.initial_facts) == {'research.input_context'}
    context = command.initial_facts['research.input_context']
    assert context['user_brief'] == prepared.to_payload()['source_intake']['user_brief']
    assert command.expected_revision == 0
    assert command.decision_record.decision_key == 'decision:research-request'
    assert command.actor_id == 'medical_manager'
    assert 'intervention.dose_regimen' not in command.initial_facts
    assert 'picos.indication' not in command.initial_facts
    assert command.normalized_seed_id == 'seed:saved'
