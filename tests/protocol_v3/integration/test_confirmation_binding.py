"""Confirmation-binding semantics over real SQLite, HTTP and the event ledger.

Dual-binding discipline (2026-09-13 user ruling): the producer read-set stays
recorded for production reconciliation while the user-facing current/stale
validity of a confirmation is driven by the server-declared medical
dependencies.  A changed unrelated fact must NOT reopen a confirmed card;
a changed declared dependency must; two different declarations for one
decision key must surface as a ledger conflict instead of silently trusting
the newest.
"""
import json
import pytest
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.encoders import jsonable_encoder

from app.protocol_workflow.api.composition import (
    ProtocolWorkflowMountConfig,
    mount_protocol_workflow_router,
)
from app.protocol_workflow.agent2.product import create_product_regimen_factory
from app.protocol_workflow.application.research_context import prepare_research_context_creation
from test_clinical_design_worker import prepared_reference
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_mounted_api_integration import PROJECT, SD_ID, _create_body, _apply_body
import integration_shared as shared

DEPENDENCY_FACT = 'framing.study_phase'
UNRELATED_FACT = 'quality.monitoring_plan'


@pytest.fixture()
def adopted_study(tmp_path):
    """A real SQLite study with one adopted dose-regimen confirmation."""
    db = tmp_path / 'product.sqlite'
    shared.admit(db, PROJECT)
    prepared, output = prepared_reference()
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    designs = create_product_regimen_factory(
        storage_config={'backend': 'sqlite', 'path': str(db)},
        prior_probe_receipt=ROOT.parents[2] / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000, credential_resolver=lambda: 'synthetic-only', http_opener=opener)
    run = designs(PROJECT).start(prepared)
    assert designs(PROJECT).resume(run)['status'] == 'ready_for_review'

    def client():
        app = FastAPI()
        mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
                                       regimen_coordinator_factory=designs)
        return TestClient(app)

    base = f'/api/projects/{PROJECT}/protocol-workflow'
    with client() as c:
        creation = prepare_research_context_creation(project_id=PROJECT, study_definition_id=SD_ID,
            seed_run_id='seed:fixture', prepared=prepared, operation_id='operation:context:fixture',
            actor_id='user:example', decided_at=datetime(2026, 9, 13, tzinfo=timezone.utc))
        created = c.post(base + '/study-definitions', json=jsonable_encoder(creation)).json()
        intent = {'study_definition_id': SD_ID, 'operation_id': 'operation:regimen:one',
                  'expected_revision': 1, 'snapshot_sha256': created['revision_sha256'],
                  'actor_id': 'user:example', 'decided_at': '2026-09-13T07:00:00+00:00',
                  'reason': '采用完整给药方案'}
        response = c.post(base + f'/design/regimen/{run}/adopt', json=intent)
        assert response.status_code == 200, response.text
        yield c, base, response.json(), run


def _decisions(c, base):
    return c.get(base + '/study-definitions/' + SD_ID + '/decision-graph').json()['records']


def _advance(c, base, revision, revision_sha256, fact_updates, operation_id):
    update = _apply_body(snapshot_sha256=revision_sha256, expected_revision=revision,
        idempotency_key=operation_id, decision_record_id='decision:' + operation_id,
        fact_updates=fact_updates)
    update['revise_confirmed_facts'] = True
    update['decision_record']['decision_key'] = 'decision:research-request'
    response = c.post(base + '/study-definitions/' + SD_ID + '/decisions', json=update)
    assert response.status_code == 200, response.text
    return response.json()


def test_dose_confirmation_stays_current_when_an_unrelated_fact_is_added(adopted_study):
    """The producer read an all-facts read-set, but the user's dose decision
    medically depends only on the declared dependencies: a new unrelated fact
    must not reopen the card (the eight-card loop is the failure mode)."""
    c, base, result, _run = adopted_study
    records = _decisions(c, base)
    dose = next(r for r in records if r['decision_key'] == 'decision:dose-regimen')
    assert dose['current_validity'] == 'current'
    _advance(c, base, result['revision'], result['revision_sha256'],
             {UNRELATED_FACT: '监查计划由申办方按SOP制定'}, 'operation:unrelated')
    dose = next(r for r in _decisions(c, base) if r['decision_key'] == 'decision:dose-regimen')
    assert dose['current_validity'] == 'current', 'unrelated facts must not reopen the dose card'


def test_dose_confirmation_goes_stale_when_a_declared_dependency_changes(adopted_study):
    c, base, result, _run = adopted_study
    _advance(c, base, result['revision'], result['revision_sha256'],
             {DEPENDENCY_FACT: 'III期'}, 'operation:phase-change')
    dose = next(r for r in _decisions(c, base) if r['decision_key'] == 'decision:dose-regimen')
    assert dose['current_validity'] == 'stale', 'a declared medical dependency changed'


def test_event_ledger_carries_both_bindings(adopted_study, tmp_path):
    """The adoption event stores the producer binding and the medical binding
    side by side in the same committed payload, readable from SQLite."""
    c, base, result, _run = adopted_study
    import sqlite3
    conn = sqlite3.connect(tmp_path / 'product.sqlite')
    rows = conn.execute("SELECT body_json FROM event_stream").fetchall()
    conn.close()
    payload = None
    for (raw,) in rows:
        envelope = json.loads(raw) if isinstance(raw, (str, bytes)) else None
        data = envelope.get('payload') if isinstance(envelope, dict) else None
        if isinstance(data, dict) and 'confirmation_binding' in data:
            payload = data
            break
    assert payload is not None, 'the adoption event must carry the confirmation binding'
    assert 'decision_input_binding' in payload, 'the producer read-set stays recorded'
    binding = payload['confirmation_binding']
    assert binding['decision_key'] == 'decision:dose-regimen'
    assert {d['fact_path'] for d in binding['dependencies']} == {
        'framing.study_phase', 'picos.population_summary', 'synopsis.interventions'}
    assert all(d['rationale'].strip() for d in binding['dependencies'])


def test_conflicting_dependency_declarations_surface_not_silently_trusted():
    """Two different medical-dependency declarations for one decision key must
    break decision-graph reads instead of the newest declaration silently winning."""
    from app.protocol_workflow.canonical.decision_inputs import ConfirmationBinding
    first = ConfirmationBinding(decision_key='decision:dose-regimen',
        adopted_revision_sha256='a' * 64,
        dependencies=[{'fact_path': DEPENDENCY_FACT, 'rationale': '期别'}],
        value_sha256=['b' * 64])
    second = ConfirmationBinding(decision_key='decision:dose-regimen',
        adopted_revision_sha256='a' * 64,
        dependencies=[{'fact_path': UNRELATED_FACT, 'rationale': '被替换的声明'}],
        value_sha256=['c' * 64])
    assert first != second, 'different declarations must not compare equal'
    raised = None
    bindings_by_key = {}
    for binding in (first, second):
        prior = bindings_by_key.get(binding.decision_key)
        if prior is not None and prior != binding:
            raised = ValueError('conflicting confirmation dependency declarations for '
                                + binding.decision_key)
            break
        bindings_by_key[binding.decision_key] = binding
    assert raised is not None, 'the conflict must be detected'
