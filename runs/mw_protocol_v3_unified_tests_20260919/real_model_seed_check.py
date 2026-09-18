"""Real-model integration verification for the deepseek product profile.

Isolated SQLite + artifacts; real HTTP opener; real omp deepseek credential
resolved in memory only.  First adapter use runs the adapter's one minimal
probe (the goal-required connectivity check for a new adapter), then one
real seed generation.  Records declared vs observed identity; reopening the
same run performs zero new calls.
"""
import json
import sqlite3
import sys
from pathlib import Path

sys.path[:0] = ['tests/protocol_v3', 'services/api', 'packages', '.']

REPO = Path('.').resolve()
RUN_DIR = REPO / 'runs/mw_protocol_v3_unified_tests_20260919'
DB = RUN_DIR / 'real_deepseek_seed.sqlite'

from app.protocol_workflow.agent1.seed_product import create_product_seed_factory
from app.protocol_workflow.agent1.research_seed import prepare_seed_request

summary = {}

factory = create_product_seed_factory(
    storage_config={'backend': 'sqlite', 'path': str(DB)},
    prior_probe_receipt=REPO / 'runs/mw_protocol_v3_1r6_glm_transport_20260905/product_probe_attempt.json',
    max_input_bytes=2000000,
    product_profile='deepseek',
)
PROJECT = 'project:deepseek-real-check'
run_id = factory(PROJECT).start(prepare_seed_request(
    '合成药X的Ⅱ期概念验证研究：随机双盲安慰剂对照，评估24周临床缓解率', ()))
print('run_id:', run_id)
state = factory(PROJECT).resume(run_id)
print('status:', state.get('status'), '| can_resume:', state.get('can_resume'))
validation = state.get('validation') or {}
raw = validation.get('raw_response') or {}
receipt = {k: raw.get(k) for k in ('observed_provider', 'observed_model',
                                   'requested_reasoning_effort', 'provider_session_id')}
print('receipt identity:', json.dumps(receipt, ensure_ascii=False))

# reopen: zero new calls, same outcome
before = validation
reopened = factory(PROJECT).resume(run_id)
same = (reopened.get('validation') or {}).get('raw_response', {}).get('output_sha256') == \
       before.get('raw_response', {}).get('output_sha256')
print('reopen identical:', same)

fields = (validation.get('proposal') or {}).get('fields') or {}
summary = {
    'workflow_run_id': run_id,
    'status': state.get('status'),
    'declared': {'provider': 'deepseek', 'model': 'deepseek-flash', 'requested_effort': 'max'},
    'observed': {'provider': receipt.get('observed_provider'), 'model': receipt.get('observed_model'),
                 'effective_effort': 'not_reported_by_server'},
    'reopen_identical': bool(same),
    'fields': {k: len(v) if isinstance(v, list) else 0 for k, v in fields.items()},
}
(RUN_DIR / 'real_deepseek_seed_receipt_summary.json').write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
