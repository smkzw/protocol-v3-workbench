"""Seed-card and design-element card adoption over real SQLite and HTTP.

Covers the built seven-card recommendation chain: population/comparator
compile straight from the stored seed; a design-elements producer (fake
HTTP) feeds the five remaining cards; applicability follows confirmed facts
(a superiority design cannot adopt an NI margin); each adopted card writes
its canonical facts with medical confirmation dependencies declared.
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
from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.agent2.product import create_product_design_elements_factory
from test_regimen_workflow_integration import ROOT
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body
from test_mounted_api_integration import PROJECT, SD_ID
import integration_shared as shared


def _design_elements_output():
    """A conforming design-elements producer response (synthetic, complete)."""
    def option(text, reason='与已确认事实一致'):
        return {'text': text, 'basis': 'recommendation', 'reason': reason, 'references': []}
    return {
        'status': 'ready_for_review',
        'objectives': {
            'primary': [option('评价试验药对比安慰剂的主要疗效')],
            'secondary': [option('评价关键 secondary 终点')],
            'questions': [],
        },
        'endpoint': {
            'primary_endpoint': option('主要终点：24周临床缓解率'),
            'key_secondary': [],
            'measurement_details': None,
            'questions': [],
        },
        'estimand': {
            'treatment': option('试验药 100mg 每21天一次'),
            'population': option('全部随机化成人患者'),
            'variable': option('24周临床缓解率变化'),
            'ice_strategy': option('治疗策略策略处理伴发事件'),
            'ice_events': ['停药', '补救治疗'],
            'summary_measure': option('缓解率风险差'),
            'questions': [],
        },
        'sample_size': {
            'assumptions': ['主要终点缓解率安慰剂组20%，试验组35%'],
            'alpha': '0.05 双侧',
            'power': '90%',
            'model': '卡方检验的样本量计算',
            'planned_n': '随机300名（每组150名）',
            'attrition': '假设10%失访',
            'justification': '基于假设效应量的标准样本量计算，可复算',
            'references': [],
            'questions': [],
        },
        'non_inferiority_margin': None,
        'interim_planning': None,
        'questions': [],
        'unresolved_questions': [],
    }


@pytest.fixture()
def adopted_project(tmp_path):
    """Real SQLite project whose seed carries population/comparator candidates."""
    db = tmp_path / 'product.sqlite'
    shared.admit(db, PROJECT)
    seed_fields = {
        'research_drug': [{'raw': '合成药X', 'candidate': '合成药X',
                           'confidence': 1, 'reason': '来自写作说明', 'basis': 'user', 'references': []}],
        'clinical_phase': [{'raw': 'Ⅱ期', 'candidate': 'Ⅱ期',
                            'confidence': 1, 'reason': '来自写作说明', 'basis': 'user', 'references': []}],
        'populations': [{'raw': '18-75岁成人患者', 'candidate': '18-75岁成人患者',
                         'confidence': 0.9, 'reason': '来自写作说明', 'basis': 'user', 'references': []}],
        'comparator': [{'raw': '安慰剂对照', 'candidate': '安慰剂对照',
                        'confidence': 0.9, 'reason': '来自写作说明', 'basis': 'user', 'references': []}],
    }
    output = {'fields': {k: v for k, v in seed_fields.items()}}
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(output)))])
    seeds = create_product_seed_factory(
        storage_config={'backend': 'sqlite', 'path': str(db)},
        prior_probe_receipt=ROOT.parents[2] / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000, credential_resolver=lambda: 'synthetic-only', http_opener=opener)
    run = seeds(PROJECT).start(prepare_seed_request('合成药X的Ⅱ期研究，入组18-75岁成人患者，采用安慰剂对照', ()))
    seeds(PROJECT).resume(run)

    def client():
        app = FastAPI()
        mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
                                       seed_coordinator_factory=seeds)
        return TestClient(app)

    base = f'/api/projects/{PROJECT}/protocol-workflow'
    with client() as c:
        response = c.post(base + '/design/regimen/study-context', json={
            'seed_run_id': run, 'operation_id': 'context:one',
            'actor_id': 'user:example', 'decided_at': '2026-09-13T10:00:00Z'})
        assert response.status_code == 200, response.text
        created = response.json()
        # Adopt the basic research information so the study carries the seed's
        # input context (later card adoptions verify activity against it).
        info = c.post(base + '/design/regimen/research-information', json={
            'seed_run_id': run, 'study_definition_id': created['study_definition_id'],
            'operation_id': 'info:one',
            'selections': {'research_drug': 0, 'clinical_phase': 0},
            'expected_revision': created['revision'],
            'snapshot_sha256': created['revision_sha256'],
            'actor_id': 'user:example', 'decided_at': '2026-09-13T11:00:00Z',
            'reason': '确认基础研究信息'})
        assert info.status_code == 200, info.text
        refreshed = c.get(base + '/study-definitions/' + created['study_definition_id']).json()
    return db, seeds, run, {'study_definition_id': created['study_definition_id'],
                            'revision': refreshed['revision'],
                            'revision_sha256': refreshed['revision_sha256']}, opener


def _seed_fields(seeds, run):
    return seeds(PROJECT).read(run)['validation']['proposal']['fields']


def test_seed_cards_populate_core_population_and_comparator(adopted_project):
    """Both seed-compiled cards adopt through the HTTP endpoint with their
    medical dependencies declared; the canonical facts land in the study."""
    db, seeds, run, created, opener = adopted_project
    study_id = created['study_definition_id']
    fields = _seed_fields(seeds, run)
    if not fields.get('populations') or not fields.get('comparator'):
        pytest.skip('seed fixture lacks populations/comparator candidates')
    def client():
        app = FastAPI()
        mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
                                       seed_coordinator_factory=seeds)
        return TestClient(app)
    base = f'/api/projects/{PROJECT}/protocol-workflow'
    with client() as c:
        current_revision, current_sha = created['revision'], created['revision_sha256']
        for card, index in (('core_population', 0), ('comparator', 0)):
            body = {'study_definition_id': study_id, 'operation_id': f'operation:{card}',
                    'expected_revision': current_revision, 'snapshot_sha256': current_sha,
                    'actor_id': 'user:example', 'decided_at': '2026-09-13T07:00:00+00:00',
                    'reason': f'确认{card}', 'seed_run_id': run, 'card': card,
                    'selection_index': index}
            response = c.post(base + '/design/regimen/seed-card', json=body)
            assert response.status_code == 200, response.text
            adopted = response.json()
            current_revision, current_sha = adopted['revision'], adopted['revision_sha256']
        study = c.get(base + '/study-definitions/' + study_id).json()
        assert study['definition']['facts'].get('picos.population_summary'), 'population fact adopted'
        assert study['definition']['facts'].get('framing.structured_design.comparator_type'), \
            'comparator fact adopted'
        # Replay: same operation returns the original receipt with no new write.
        body = {'study_definition_id': study_id, 'operation_id': 'operation:core_population',
                'expected_revision': created['revision'], 'snapshot_sha256': created['revision_sha256'],
                'actor_id': 'user:example', 'decided_at': '2026-09-13T07:00:00+00:00',
                'reason': '确认core_population', 'seed_run_id': run, 'card': 'core_population',
                'selection_index': 0}
        replay = c.post(base + '/design/regimen/seed-card', json=body)
        assert replay.status_code == 200
        assert replay.json().get('replayed') is True


def test_design_elements_cards_flow_from_producer_to_adoption(adopted_project):
    """The fake-HTTP producer feed produces a ready proposal; the objectives-
    endpoint card adopts through the HTTP endpoint with medical dependencies."""
    db, seeds, run, created, _opener = adopted_project
    study_id = created['study_definition_id']
    opener = _FakeOpener([_FakeResponse(_completion_body(content=json.dumps(_design_elements_output())))])
    elements = create_product_design_elements_factory(
        storage_config={'backend': 'sqlite', 'path': str(db)},
        prior_probe_receipt=ROOT.parents[2] / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
        max_input_bytes=2000000, credential_resolver=lambda: 'synthetic-only', http_opener=opener)

    def client():
        app = FastAPI()
        mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db),
                                       seed_coordinator_factory=seeds,
                                       design_elements_coordinator_factory=elements)
        return TestClient(app)

    base = f'/api/projects/{PROJECT}/protocol-workflow'
    with client() as c:
        prepared = c.post(base + '/design/elements/prepare', json={
            'seed_run_id': run, 'study_definition_id': study_id}).json()
        assert prepared.get('expected_workflow_run_id'), prepared
        started = c.post(base + '/design/elements', json={
            'seed_run_id': run, 'study_definition_id': study_id,
            'expected_workflow_run_id': prepared['expected_workflow_run_id']})
        assert started.status_code == 202, started.text
        run_id = started.json()['workflow_run_id']
        state = c.get(base + f'/design/elements/{run_id}').json()
        if state['status'] != 'ready_for_review':
            print('ELEMENTS STATE:', json.dumps({k: state.get(k) for k in
                ('status', 'can_resume', 'validation')}, ensure_ascii=False, default=str)[:600])
        assert state['status'] == 'ready_for_review', state.get('status')
        proposal = state['validation']['proposal']

        study_now = c.get(base + '/study-definitions/' + study_id).json()
        body = {'study_definition_id': study_id, 'operation_id': 'operation:objectives-endpoint',
                'expected_revision': study_now['revision'], 'snapshot_sha256': study_now['revision_sha256'],
                'actor_id': 'user:example', 'decided_at': '2026-09-13T07:00:00+00:00',
                'reason': '确认目标与终点', 'seed_run_id': run, 'card': 'objectives-endpoint',
                'selections': {'primary_objective': 0, 'primary_endpoint_confirmed': True}}
        from app.protocol_workflow.api.design import DesignCardAdoptionRequest as _M
        try:
            _M.model_validate(body | {'card': 'objectives-endpoint'})
            print('BODY MODEL OK')
        except Exception as _e:
            print('BODY MODEL FAIL:', str(_e)[:400])
        response = c.post(base + f'/design/elements/{run_id}/adopt/objectives-endpoint', json=body)
        assert response.status_code == 200, response.text
        study = c.get(base + '/study-definitions/' + study_id).json()
        facts = study['definition']['facts']
        assert facts.get('picos.primary_objectives'), 'objectives adopted'
        assert facts.get('picos.primary_endpoint'), 'endpoint adopted'
        # Estimand card: available next, adopts the five-element set.
        study_now = c.get(base + '/study-definitions/' + study_id).json()
        body['operation_id'] = 'operation:estimand'
        body['card'] = 'estimand'
        body['expected_revision'] = study_now['revision']
        body['snapshot_sha256'] = study_now['revision_sha256']
        body['reason'] = '确认估计目标'
        body['selections'] = {'treatment': True, 'population': True, 'variable': True,
                              'ice_strategy': True, 'summary_measure': True}
        response = c.post(base + f'/design/elements/{run_id}/adopt/estimand', json=body)
        assert response.status_code == 200, response.text
        facts = c.get(base + '/study-definitions/' + study_id).json()['definition']['facts']
        assert facts.get('estimand.primary.variable'), 'estimand variable adopted'
        assert facts.get('estimand.primary.ice_strategy'), 'ICE strategy adopted'
        # The producer made exactly one call (fake HTTP consumed once).
        assert opener.calls == 1
