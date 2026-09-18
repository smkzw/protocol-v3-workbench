"""C03 reviewer probes Q4: contract-factory identity surface + seed schema compiler."""
import json
import os
import sqlite3
import sys

from app.protocol_workflow.agent1.research_seed import (
    FIELDS, _Candidate, read_seed_candidates, seed_output_schema,
)
from app.protocol_workflow.graph import GraphRuntime
from app.protocol_workflow.graph.ports import ConfiguredNodeServiceResult
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory, build_unit_of_work_factory,
)
from test_graph_runtime import _probe_plan, _root_inputs, _StepClock, _PROJ

DB = sys.argv[1]

print('=== F. RESERVED row + committed result event (hand-seeded state) ===')
calls = []
def service(request):
    calls.append(1)
    return ConfiguredNodeServiceResult(payload={'candidate': 'x'},
                                        provider_session_id='completion-actual-1')

def make(path):
    config = {'backend': 'sqlite', 'path': path}
    return GraphRuntime(project_id=_PROJ, uow_factory=build_unit_of_work_factory(config),
                        reservation_repository_factory=build_committed_reservation_repository_factory(config),
                        services={'draft_node': service}, clock=_StepClock())

plan = _probe_plan(); run_id = 'probe-f'
rt = make(DB)
rt.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
rt.run_to_completion(run_id)
res = rt.reservation_attempts(run_id, 'draft_node')[0]
conn = sqlite3.connect(DB)
conn.execute("UPDATE execution_reservation SET status='reserved', terminal_state=NULL, "
             "output_sha256=NULL, error_code=NULL WHERE execution_reservation_id=?",
             (res.execution_reservation_id,))
conn.commit(); conn.close()
try:
    make(DB).advance(run_id)
    print('no exception (repair succeeded)')
except Exception as exc:
    print('advance raised %s: %s' % (type(exc).__name__, exc))

print()
print('=== G. factory frozen-identity surface: which fields are actually guarded? ===')
variants = {
    'control-unchanged': {},
    'output_schema_ref-changed': {'output_schema_ref': 'schema:graph-x:some-other-schema'},
    'input_schema_ref-changed': {'input_schema_ref': 'schema:graph-x:draft_node:other-input'},
    'skill_definition_id-changed': {'skill_definition_id': 'skill:other-graph:draft_node'},
    'harness-changed': {'harness': 'cli'},
    'prompt_sha256-changed': {'prompt_sha256': 'a' * 64},
    'timeout-changed': {'timeout_seconds': 1},
    'idempotency_key-changed': {'idempotency_key': 'other-logical-key'},
}
for name, update in variants.items():
    def factory(base, update=update):
        return base.model_copy(update=update)
    db = DB + '.' + name.replace('-', '_')
    if os.path.exists(db):
        os.remove(db)
    def svc(request):
        return ConfiguredNodeServiceResult(payload={'candidate': 'x'},
                                           provider_session_id='completion-actual-1')
    config = {'backend': 'sqlite', 'path': db}
    rt_g = GraphRuntime(project_id=_PROJ, uow_factory=build_unit_of_work_factory(config),
                        reservation_repository_factory=build_committed_reservation_repository_factory(config),
                        services={'draft_node': svc}, clock=_StepClock(),
                        execution_contract_factories={'draft_node': factory})
    rid = 'probe-g-' + name
    try:
        rt_g.start_run(plan, workflow_run_id=rid, root_inputs=_root_inputs())
        rt_g.run_to_completion(rid)
        ev = [e for e in rt_g.read_events(rid) if e.event_type == 'graph_node_result'][0]
        c = ev.payload['execution_contract']
        changed = [k for k, v in update.items() if c.get(k) == v]
        print('%-26s accepted persisted-changes=%s node.output_schema=%r contract.output_schema_ref=%r' % (
            name, changed, ev.payload['output_schema'], c.get('output_schema_ref')))
    except Exception as exc:
        print('%-26s rejected: %s' % (name, exc))

print()
print('=== H. seed_output_schema compiler vs validator drift ===')
schema = seed_output_schema()
refs = []
def walk(node):
    if isinstance(node, dict):
        if '$ref' in node:
            refs.append(node['$ref'])
        for v in node.values():
            walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)
walk(schema)
defs = schema.get('$defs', {})
print('$defs keys:', sorted(defs))
unresolved = [r for r in refs if not (r.startswith('#/$defs/') and r[len('#/$defs/'):].split('/')[0] in defs)]
print('unresolved $refs:', unresolved)
items = schema['properties']['fields']['properties']['research_drug']['items']
print('fields.<field>.items:', items)
arr = [s for s in defs['SeedCandidate']['properties']['candidate'].get('anyOf', [])
       if s.get('type') == 'array']
print('candidate array variant shipped to model:', arr)
ok = _Candidate.model_validate({'raw': 'r', 'candidate': [], 'confidence': 0.5,
                                'reason': 'x', 'basis': 'user'})
print('pydantic accepts candidate=[] :', ok.candidate == [])

class _Req:
    input_sha256 = '0' * 64
    def to_payload(self):
        return {'user_brief': 'brief', 'sources': []}

try:
    read_seed_candidates(_Req(), {'fields': {'research_drug': [
        {'raw': 'r', 'candidate': [], 'confidence': 0.5, 'reason': 'x', 'basis': 'user'}]}})
    print('validator accepts candidate=[] : True')
except ValueError as exc:
    print('validator accepts candidate=[] : False (%s)' % exc)

out = read_seed_candidates(_Req(), {'fields': {'research_drug': [
    {'raw': '', 'candidate': ['suggestion'], 'confidence': 0.2, 'reason': 'x',
     'basis': 'recommendation'}]}})
print('recommendation empty-raw accepted, label:', out['fields']['research_drug'][0]['source_support'],
      'requires_confirmation:', out['fields']['research_drug'][0]['requires_confirmation'])
