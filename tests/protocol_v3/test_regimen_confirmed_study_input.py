"""Study-bound generation must read confirmed clinical facts without adopting seed candidates."""
import hashlib
from app.protocol_workflow.canonical.hashing import canonical_json
from test_clinical_design_worker import prepared_reference


def test_study_context_is_a_deep_pinned_read_set_and_changes_logical_request():
    from app.protocol_workflow.agent2.study_input import bind_regimen_study_input
    from app.protocol_workflow.agent2.coordinator import RegimenCoordinator
    original, _ = prepared_reference()
    facts = {'picos.intervention.dose': '10 mg', 'research.input_context': {'hash': 'source'},
             'research.regimen_producer': {'workflow_run_id': 'old'}}
    bound = bind_regimen_study_input(original, study_definition_id='study:a', facts=facts)
    assert bound.to_payload()['confirmed_study']['facts'] == {'picos.intervention.dose': '10 mg'}
    facts['picos.intervention.dose'] = '20 mg'
    assert bound.to_payload()['confirmed_study']['facts']['picos.intervention.dose'] == '10 mg'
    revised = bind_regimen_study_input(original, study_definition_id='study:a', facts=facts)
    other = bind_regimen_study_input(original, study_definition_id='study:b', facts=facts)
    coordinator = RegimenCoordinator(project_id='project:a', branch_id='main', runtime=None, artifact_store=None)
    assert len({coordinator.run_id(p) for p in (original,bound,revised,other)}) == 4
    assert bound.input_sha256 == hashlib.sha256(canonical_json(bound.to_payload()).encode()).hexdigest()


def test_unchanged_clinical_facts_do_not_regenerate_for_producer_metadata_changes():
    from app.protocol_workflow.agent2.study_input import bind_regimen_study_input
    original, _ = prepared_reference()
    first = bind_regimen_study_input(original, study_definition_id='study:a', facts={'picos.phase':'II'})
    second = bind_regimen_study_input(original, study_definition_id='study:a', facts={
        'picos.phase':'II', 'research.regimen_producer': {'workflow_run_id':'receipt:new'}})
    assert first == second


def test_fresh_adoption_checks_target_and_current_clinical_values():
    import pytest
    from app.protocol_workflow.agent2.study_input import bind_regimen_study_input, validate_regimen_study_input
    original, _ = prepared_reference()
    bound = bind_regimen_study_input(original, study_definition_id='study:a', facts={'picos.phase':'II'})
    validate_regimen_study_input(bound, study_definition_id='study:a', facts={'picos.phase':'II'})
    with pytest.raises(ValueError, match='regimen_target_study_changed'):
        validate_regimen_study_input(bound, study_definition_id='study:b', facts={'picos.phase':'II'})
    with pytest.raises(ValueError, match='regimen_clinical_facts_changed'):
        validate_regimen_study_input(bound, study_definition_id='study:a', facts={'picos.phase':'III'})


def test_source_only_suggestion_cannot_overwrite_unread_clinical_facts():
    import pytest
    from app.protocol_workflow.agent2.study_input import validate_regimen_study_input
    original, _ = prepared_reference()
    validate_regimen_study_input(original, study_definition_id='study:a',
        facts={'research.input_context': {'hash': 'source'}})
    with pytest.raises(ValueError, match='regimen_clinical_context_not_read'):
        validate_regimen_study_input(original, study_definition_id='study:a',
            facts={'picos.phase': 'II'})
