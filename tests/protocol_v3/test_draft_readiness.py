"""Draft-readiness.v1: critical admission, explicit gaps, pending, blocking."""
import pytest
from test_all_chapter_contracts import REAL_TEMPLATE_DIR
from test_chapter_fact_binding import confirmed_study, bindings_for_objective, _objectives_contract
from app.protocol_workflow.agent3.draft_readiness import draft_readiness
from app.protocol_workflow.registries.template_runtime import load_current_template

BASE_FACTS = {'research.input_context': {'source_intake_sha256': 'a'}}


def _template():
    return load_current_template(REAL_TEMPLATE_DIR)


def test_unconfirmed_study_admits_nothing():
    from test_study_definition_reducer import _study_definition
    study = _study_definition(facts=dict(BASE_FACTS), canonical_state='proposed')
    view = draft_readiness(_template(), study)
    assert view['schema_version'] == 'draft-readiness.v1'
    assert view['critical_design_confirmed'] is False
    assert view['can_generate_working_draft'] is False
    assert view['chapter_dispositions'] and all(
        item['disposition'] == 'pending_decision' for item in view['chapter_dispositions'])
    assert view['open_gaps'] == []


def test_confirmed_design_admits_draft_with_gap_map():
    study = confirmed_study(dict(BASE_FACTS))
    view = draft_readiness(_template(), study)
    assert view['critical_design_confirmed'] is True
    assert view['can_generate_working_draft'] is True
    assert view['blocking_design_conflicts'] == []
    dispositions = {item['disposition'] for item in view['chapter_dispositions']}
    gaps = [item for item in view['chapter_dispositions']
            if item['disposition'] == 'write_with_gaps']
    assert gaps and all(item['gap_fact_paths'] for item in gaps)
    assert view['open_gaps'], 'non-key gaps must stay visible'
    # Deterministic identity: same inputs, same readiness hash.
    assert view['readiness_sha256'] == draft_readiness(_template(), study)['readiness_sha256']


def test_applicability_contradiction_blocks_generation():
    study = confirmed_study({**BASE_FACTS, 'statistics.interim.applicable': False,
                             'statistics.interim.timing': '第12周'})
    view = draft_readiness(_template(), study)
    blocked = [item for item in view['chapter_dispositions'] if item['disposition'] == 'blocked']
    assert blocked, 'an inactive conditional fact with live params must block'
    assert view['blocking_design_conflicts']
    assert view['can_generate_working_draft'] is False


def test_unresolved_condition_stays_pending_not_deleted():
    study = confirmed_study(dict(BASE_FACTS))
    view = draft_readiness(_template(), study)
    pending = [item for item in view['chapter_dispositions']
               if item['disposition'] == 'pending_decision']
    assert pending, 'unresolved non-key conditions must keep a pending chapter'
    for item in pending:
        assert item['errors'], 'pending chapters must carry their unresolved reason'


def test_gap_aware_binding_defers_only_missing_paths():
    from app.protocol_workflow.registries.fact_bindings import bind_chapter_input
    study = confirmed_study({'study.objective': '探索合成药D在2型糖尿病中的有效性'})
    bound = bind_chapter_input(study, _objectives_contract(), bindings_for_objective(),
                               deferred_required_paths=('picos.objective.primary',))
    assert bound.gap_fact_paths == (), 'confirmed facts are never listed as gaps'
    missing_study = confirmed_study(dict(BASE_FACTS))
    deferred_bound = bind_chapter_input(missing_study, _objectives_contract(),
                                        bindings_for_objective(),
                                        deferred_required_paths=('picos.objective.primary',))
    assert deferred_bound.gap_fact_paths == ('picos.objective.primary',)
    assert deferred_bound.resolved_facts == {}
    with pytest.raises(Exception):
        bind_chapter_input(missing_study, _objectives_contract(), bindings_for_objective())
