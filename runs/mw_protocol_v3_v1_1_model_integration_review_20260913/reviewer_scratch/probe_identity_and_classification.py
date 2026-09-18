"""C03 reviewer probes: provider-identity retention, crash windows, misclassification.

Read-only wrt product code; writes only temp SQLite under reviewer_scratch.
"""
import json
import sqlite3
import sys
import traceback

from app.protocol_workflow.graph import GraphRuntime
from app.protocol_workflow.graph.ports import ConfiguredNodeServiceResult
from app.protocol_workflow.graph.runtime import _payload_sha256
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory, build_unit_of_work_factory,
)
from packages.contracts.workbench_contracts.protocol_v3 import ReasoningEffort
from test_graph_runtime import _probe_plan, _root_inputs, _StepClock, _PROJ

DB = sys.argv[1]


def make_runtime(services, factories=None, path=None):
    config = {'backend': 'sqlite', 'path': path or DB}
    return GraphRuntime(
        project_id=_PROJ, uow_factory=build_unit_of_work_factory(config),
        reservation_repository_factory=build_committed_reservation_repository_factory(config),
        services=services, clock=_StepClock(),
        execution_contract_factories=factories or {},
    )


def receipt_service(calls):
    def service(request):
        calls.append(1)
        return ConfiguredNodeServiceResult(
            payload={'candidate': 'synthetic-only'},
            provider_session_id='completion-actual-1',
        )
    return service


def row(conn, res_id):
    return conn.execute(
        "SELECT status, terminal_state, provider_session_id, output_sha256, error_code "
        "FROM execution_reservation WHERE execution_reservation_id=?", (res_id,)
    ).fetchone()


def fresh_db(path):
    import os
    if os.path.exists(path):
        os.remove(path)
    return path


print('=== A. baseline: normal completion retains actual identity (expected pass) ===')
calls = []
db = fresh_db(DB + '.a')
rt = make_runtime({'draft_node': receipt_service(calls)}, path=db)
plan = _probe_plan(); run_id = 'probe-a'
rt.start_run(plan, workflow_run_id=run_id, root_inputs=_root_inputs())
snap = rt.run_to_completion(run_id)
res = rt.reservation_attempts(run_id, 'draft_node')[0]
ev = [e for e in rt.read_events(run_id) if e.event_type == 'graph_node_result'][0]
print('ledger provider_session_id:', res.provider_session_id)
print('event provider_session_id :', ev.payload.get('provider_session_id'))
assert res.provider_session_id == 'completion-actual-1'
assert ev.payload.get('provider_session_id') == 'completion-actual-1'

print()
print('=== B. crash window: result event committed, coordinator COMPLETED lost ===')
# Regress the durable row to the exact post-crash state: the shell placeholder
# sess:<res-id>, RUNNING, no output hash (crash between _append_node_result and
# reservations.py COMPLETED transition).
conn = sqlite3.connect(DB + '.a')
ph = 'sess:' + res.execution_reservation_id
conn.execute(
    "UPDATE execution_reservation SET status='running', terminal_state=NULL, "
    "output_sha256=NULL, error_code=NULL, provider_session_id=? "
    "WHERE execution_reservation_id=?", (ph, res.execution_reservation_id)
)
conn.commit(); conn.close()
rt2 = make_runtime({'draft_node': receipt_service(calls)}, path=db)
snap2 = rt2.advance(run_id)
after = rt2.reservation_attempts(run_id, 'draft_node')[0]
ev2 = [e for e in rt2.read_events(run_id) if e.event_type == 'graph_node_result'][0]
print('after repair: status=%s ledger id=%r' % (after.status, after.provider_session_id))
print('after repair: event id=%r output_sha match=%s' % (
    ev2.payload.get('provider_session_id'), after.output_sha256 == ev2.payload['output_sha256']))
print('VERDICT B: ledger/event identity diverge =', after.provider_session_id != ev2.payload.get('provider_session_id'))
print('total service calls (no redispatch expected):', len(calls))

print()
print('=== C. crash window variant: exception-path UNKNOWN row + committed event ===')
conn = sqlite3.connect(DB + '.a')
conn.execute(
    "UPDATE execution_reservation SET status='unknown_outcome', terminal_state='unknown_outcome', "
    "output_sha256=NULL, error_code='dispatch_exception', provider_session_id=? "
    "WHERE execution_reservation_id=?", (ph, res.execution_reservation_id)
)
conn.commit(); conn.close()
rt3 = make_runtime({'draft_node': receipt_service(calls)}, path=db)
snap3 = rt3.advance(run_id)
after3 = rt3.reservation_attempts(run_id, 'draft_node')[0]
print('after repair: status=%s ledger id=%r' % (after3.status, after3.provider_session_id))

print()
print('=== D. resolve_unknown_with_receipt: can a known actual id be recorded? ===')
db = fresh_db(DB + '.d')
raising = []
def bad_service(request):
    raising.append(1)
    raise ValueError('malformed JSON from provider')  # parse inside dispatch window
rt_d = make_runtime({'draft_node': bad_service}, path=db)
run_d = 'probe-d'
rt_d.start_run(plan, workflow_run_id=run_d, root_inputs=_root_inputs())
snap_d = rt_d.run_to_completion(run_d)
res_d = rt_d.reservation_attempts(run_d, 'draft_node')[-1]
print('raising service -> reservation status=%s error_code=%r run status=%s' % (
    res_d.status, res_d.error_code, snap_d.status))
node_d = [n for n in snap_d.nodes if n.node_id == 'draft_node'][0]
print('node status:', node_d.status)
# now recover with a payload-bearing receipt whose actual provider id is known
payload = {'candidate': 'recovered-content'}
sha = _payload_sha256(payload)
snap_rec = rt_d.resolve_unknown_with_receipt(
    run_d, node_id='draft_node', output=payload, output_sha256=sha)
res_rec = rt_d.reservation_attempts(run_d, 'draft_node')[-1]
ev_rec = [e for e in rt_d.read_events(run_d) if e.event_type == 'graph_node_result'][0]
print('recovered: ledger id=%r event has provider_session_id key=%s recovered flag=%s' % (
    res_rec.provider_session_id, 'provider_session_id' in ev_rec.payload,
    ev_rec.payload.get('recovered_receipt')))

print()
print('=== E. RESERVED + committed result event: is the repair scan state reachable/repairable? ===')
conn = sqlite3.connect(DB + '.a')
conn.execute(
    "UPDATE execution_reservation SET status='reserved', terminal_state=NULL, "
    "output_sha256=NULL, error_code=NULL, provider_session_id=? "
    "WHERE execution_reservation_id=?", (ph, res.execution_reservation_id)
)
conn.commit(); conn.close()
rt4 = make_runtime({'draft_node': receipt_service(calls)}, path=db)
try:
    rt4.advance(run_id)
    print('no exception (unexpected)')
except Exception as exc:
    print('advance raised: %s: %s' % (type(exc).__name__, exc))
