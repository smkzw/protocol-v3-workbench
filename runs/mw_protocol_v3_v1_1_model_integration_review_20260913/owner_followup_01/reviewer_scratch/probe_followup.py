"""C03 followup probes. Independent re-verification of owner changes D1/D2/D4/D5, Q2, D3."""
import hashlib, json, os, sqlite3, sys
from pathlib import Path

SCR = Path(sys.argv[1])
sys.path.insert(0, str(SCR))

from app.protocol_workflow.graph import GraphRuntime
from app.protocol_workflow.graph.ports import ConfiguredNodeServiceResult
from app.protocol_workflow.graph.runtime import _payload_sha256
from app.protocol_workflow.storage.sqlite import (
    build_committed_reservation_repository_factory, build_unit_of_work_factory)
from test_graph_runtime import _probe_plan, _root_inputs, _StepClock, _PROJ

def ok(label, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + label + ((' :: ' + str(detail)) if detail else ''))
    return cond

print('=== 1. D1: RUNNING-window repair carries event identity; UNKNOWN freeze preserved ===')
db = str(SCR / 'd1.sqlite')
if os.path.exists(db): os.remove(db)
cfg = {'backend': 'sqlite', 'path': db}
calls = []
def svc(request):
    calls.append(1)
    return ConfiguredNodeServiceResult(payload={'candidate': 'x'}, provider_session_id='completion-actual-F1')
def rt_factory():
    return GraphRuntime(project_id=_PROJ, uow_factory=build_unit_of_work_factory(cfg),
                        reservation_repository_factory=build_committed_reservation_repository_factory(cfg),
                        services={'draft_node': svc}, clock=_StepClock())
plan = _probe_plan()
rt = rt_factory(); rt.start_run(plan, workflow_run_id='d1run', root_inputs=_root_inputs()); rt.run_to_completion('d1run')
res = rt.reservation_attempts('d1run', 'draft_node')[0]
placeholder = 'sess:' + res.execution_reservation_id
conn = sqlite3.connect(db)
conn.execute("UPDATE execution_reservation SET status='running', terminal_state=NULL, output_sha256=NULL, "
             "error_code=NULL, provider_session_id=? WHERE execution_reservation_id=?",
             (placeholder, res.execution_reservation_id)); conn.commit(); conn.close()
rt2 = rt_factory(); rt2.advance('d1run')
after = rt2.reservation_attempts('d1run', 'draft_node')[0]
ev = [e for e in rt2.read_events('d1run') if e.event_type == 'graph_node_result'][0]
ok('D1 running-repair ledger id == event actual id', after.provider_session_id == 'completion-actual-F1',
   'ledger=%r event=%r' % (after.provider_session_id, ev.payload.get('provider_session_id')))
ok('D1 running-repair status COMPLETED + sha match', after.status.value == 'completed' and after.output_sha256 == ev.payload['output_sha256'])
ok('D1 no redispatch during repair', len(calls) == 1)
conn = sqlite3.connect(db)
conn.execute("UPDATE execution_reservation SET status='unknown_outcome', terminal_state='unknown_outcome', "
             "output_sha256=NULL, error_code='dispatch_exception', provider_session_id=? "
             "WHERE execution_reservation_id=?", (placeholder, res.execution_reservation_id)); conn.commit(); conn.close()
rt3 = rt_factory(); rt3.advance('d1run')
after3 = rt3.reservation_attempts('d1run', 'draft_node')[0]
ok('D1 unknown-row repair keeps ledger freeze (placeholder retained)', after3.status.value == 'completed' and after3.provider_session_id == placeholder, repr(after3.provider_session_id))
# repository negative: different id on UNKNOWN->COMPLETED must still raise
with build_committed_reservation_repository_factory(cfg)() as repo:
    conn = sqlite3.connect(db)
    conn.execute("UPDATE execution_reservation SET status='unknown_outcome', terminal_state='unknown_outcome', "
                 "output_sha256=NULL, error_code='dispatch_exception' WHERE execution_reservation_id=?", (res.execution_reservation_id,)); conn.commit(); conn.close()
    try:
        repo.transition(_PROJ, res.execution_reservation_id, to_status=__import__(
            'packages.contracts.workbench_contracts.protocol_v3', fromlist=['ReservationStatus']).ReservationStatus.COMPLETED,
            terminal_state=__import__('packages.contracts.workbench_contracts.protocol_v3', fromlist=['ExecutionTerminalState']).ExecutionTerminalState.COMPLETED,
            output_sha256='0'*64, provider_session_id='someone-elses-id', updated_at=__import__('datetime').datetime.now(__import__('datetime').timezone.utc))
        ok('D1 storage UNKNOWN id-freeze negative (different id rejected)', False, 'no exception')
    except Exception as exc:
        ok('D1 storage UNKNOWN id-freeze negative (different id rejected)', 'RepositoryStateTransitionError' in type(exc).__name__, str(exc))

print()
print('=== 2. D5: pinned pre-dispatch contract survives factory drift; deterministic nodes emit no dispatch event ===')
db5 = str(SCR / 'd5.sqlite')
if os.path.exists(db5): os.remove(db5)
cfg5 = {'backend': 'sqlite', 'path': db5}
invoked = []
def drifting(model, out_ref):
    def factory(base):
        return base.model_copy(update={'model': model, 'provider': 'zhipu-coding-plan',
                                       'harness': 'direct-api', 'allowed_providers': ('zhipu-coding-plan',),
                                       'allowed_regions': ('cn',), 'output_schema_ref': out_ref})
    return factory
def rt5(factory):
    def broken(request):
        invoked.append(request.execution_contract.model_dump(mode='json'))
        raise RuntimeError('provider boundary interrupted')
    return GraphRuntime(project_id=_PROJ, uow_factory=build_unit_of_work_factory(cfg5),
                        reservation_repository_factory=build_committed_reservation_repository_factory(cfg5),
                        services={'draft_node': broken}, clock=_StepClock(),
                        execution_contract_factories={'draft_node': factory})
r5 = rt5(drifting('glm-original', 'https://drift.example/original'))
r5.start_run(_probe_plan(), workflow_run_id='d5run', root_inputs=_root_inputs()); r5.advance('d5run')
ok('D5 dispatch event recorded before failure', any(e.event_type == 'graph_node_dispatch' for e in r5.read_events('d5run')))
payload = {'artifact_ref': 'recovered-ref'}
r5b = rt5(drifting('glm-drifted', 'https://drift.example/drifted'))
r5b.resolve_unknown_with_receipt('d5run', node_id='draft_node', output=payload, output_sha256=_payload_sha256(payload))
rec = next(e for e in r5b.read_events('d5run') if e.payload.get('recovered_receipt'))
c = rec['payload']['execution_contract'] if 'payload' in rec else rec.payload['execution_contract']
ok('D5 recovered event keeps original model', c['model'] == 'glm-original', c['model'])
ok('D5 recovered event keeps original output_schema_ref', c['output_schema_ref'] == 'https://drift.example/original', c['output_schema_ref'])
ok('D5 drifted factory never applied', c['model'] != 'glm-drifted' and len(invoked) == 1)
# deterministic node -> no dispatch events
db5b = str(SCR / 'd5b.sqlite')
if os.path.exists(db5b): os.remove(db5b)
cfg5b = {'backend': 'sqlite', 'path': db5b}
def det(request): return {'candidate': 'deterministic'}
r5c = GraphRuntime(project_id=_PROJ, uow_factory=build_unit_of_work_factory(cfg5b),
                   reservation_repository_factory=build_committed_reservation_repository_factory(cfg5b),
                   services={'draft_node': det}, clock=_StepClock())
r5c.start_run(_probe_plan(), workflow_run_id='d5brun', root_inputs=_root_inputs()); r5c.run_to_completion('d5brun')
ok('D5 deterministic node emits no graph_node_dispatch', not any(e.event_type == 'graph_node_dispatch' for e in r5c.read_events('d5brun')))

print()
print('=== 3. Q2: crash between receipt_sink persistence and result event -> full no-recall recovery ===')
from app.protocol_workflow.agent1.research_seed import prepare_seed_request, seed_output_schema
from app.protocol_workflow.agent1.seed_workflow import build_seed_runtime, seed_plan
from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.registries import load_role_registry, load_skill_registry
from app.protocol_workflow.runtime.harness import HarnessDispatcher, DispatchReceipt
from app.protocol_workflow.runtime.adapters.zhipu_api import build_zhipu_api_adapter
from test_zhipu_product_transport import _FakeOpener, _FakeResponse, _completion_body, _resolver
ROOT = Path('config/medical_writing/protocol_v3')
role = next(r for r in load_role_registry(ROOT / 'role_registry.json').roles if r.role_kind == 'llm')
skill = next(s for s in load_skill_registry(ROOT / 'skill_registry.json').skill_definitions()
             if s.skill_definition_id == 'skill.research-seed-proposal')
DBQ = str(SCR / 'q2.sqlite'); ART = str(SCR / 'q2art')
if os.path.exists(DBQ): os.remove(DBQ)
import shutil
shutil.rmtree(ART, ignore_errors=True)
MODEL_CONTENT = ' {"fields":{"research_drug":[{"raw":"X","candidate":"X","confidence":0.5,"reason":"r","basis":"recommendation"}]}} '
opener = _FakeOpener([_FakeResponse(_completion_body(content='probe')),
                      _FakeResponse(_completion_body(content=MODEL_CONTENT, response_id='chatcmpl-actual-crash-case'))])
store = LocalArtifactStore(ART)
qcfg = {'backend': 'sqlite', 'path': DBQ}
prepared = prepare_seed_request('用户简述完整资料' * 50, ())
crash_mode = {'on': True}
from app.protocol_workflow.runtime import model_response as mr
orig_persist = mr.persist_model_response
def persist_then_die(store_, key, content, receipt, *, created_at):
    ref = orig_persist(store_, key, content, receipt, created_at=created_at)
    if crash_mode['on']:
        raise RuntimeError('process lost after durable receipt, before result event')
    return ref
import app.protocol_workflow.agent1.seed_workflow as sw
sw.persist_model_response = persist_then_die
def seed_rt():
    return build_seed_runtime(project_id='q2p', uow_factory=build_unit_of_work_factory(qcfg),
                              reservation_repository_factory=build_committed_reservation_repository_factory(qcfg),
                              artifact_store=store, role_entry=role, skill=skill, dispatcher=HarnessDispatcher(),
                              adapter_factory=lambda **kw: build_zhipu_api_adapter(
                                  credential_resolver=_resolver(), http_opener=opener, max_input_bytes=5_000_000,
                                  **kw))
r = seed_rt()
r.start_run(seed_plan('q2p', 'branch-main'), workflow_run_id='q2run', root_inputs={'research_intake': prepared.to_payload()})
r.advance('q2run')
resq = r.reservation_attempts('q2run', 'seed-generate')[-1]
ok('Q2 interrupted dispatch classified UNKNOWN', resq.status.value == 'unknown_outcome' and resq.error_code == 'dispatch_exception',
   '%s/%r' % (resq.status.value, resq.error_code))
# recovery from ledger + store only
key = 'seed-response:' + hashlib.sha256(resq.execution_reservation_id.encode()).hexdigest()
envelope = json.loads(store.read(key).content)
rcpt = envelope['receipt']
ok('Q2 orphan artifact discoverable by reservation-derived key', True, key)
ok('Q2 envelope binds actual provider id', rcpt['provider_session_id'] == 'chatcmpl-actual-crash-case', rcpt['provider_session_id'])
ok('Q2 envelope binds logical work identity', rcpt['logical_call_id'] == 'call:q2run:seed-generate' and rcpt['node_execution_contract_id'].startswith('nec:q2run:'))
ok('Q2 envelope binds input artifact hash', prepared.input_sha256 in {a['sha256'] for a in rcpt['input_artifacts']})
ok('Q2 envelope content hash self-consistent', hashlib.sha256(envelope['content'].encode()).hexdigest() == rcpt['output_sha256'])
ok('Q2 receipt carries no input excerpts/credential material',
   all(set(a.keys()) == {'ref', 'sha256'} for a in rcpt['input_artifacts']) and 'snippet' not in json.dumps(rcpt)
   and 'FAKE' not in json.dumps(envelope))
# adopt without a second provider call
crash_mode['on'] = False
sw.persist_model_response = orig_persist
out_payload = {'artifact_ref': key + ':revision:1', 'output_sha256': rcpt['output_sha256']}
calls_before = opener.calls
snap = r.resolve_unknown_with_receipt('q2run', node_id='seed-generate', output=out_payload,
                                      output_sha256=_payload_sha256(out_payload),
                                      provider_session_id=rcpt['provider_session_id'])
rec_ev = next(e for e in r.read_events('q2run') if e.payload.get('recovered_receipt'))
ok('Q2 recovered event stamped with actual provider id', rec_ev.payload.get('provider_session_id') == 'chatcmpl-actual-crash-case')
ok('Q2 ledger identity unchanged (freeze)', r.reservation_attempts('q2run', 'seed-generate')[-1].provider_session_id == 'sess:' + resq.execution_reservation_id)
r.run_to_completion('q2run')
val_ev = next(e.payload['output'] for e in r.read_events('q2run') if e.event_type == 'graph_node_result' and e.payload['node_id'] == 'seed-validate')
ok('Q2 validator completes after adoption (no provider call added)', val_ev['valid'] is True and opener.calls == calls_before,
   'valid=%s calls=%d->%d status=%s' % (val_ev['valid'], calls_before, opener.calls, val_ev['status']))
ok('Q2 DispatchReceipt accepts :revision: ref', DispatchReceipt(
    provider_session_id='i', output_sha256='0'*64, observed_provider='p', observed_model='m',
    output_artifact_ref=key + ':revision:1', output_schema_ref='s').output_artifact_ref.endswith(':revision:1'))
# constructor mutual exclusion
try:
    build_zhipu_api_adapter(credential_resolver=_resolver(), output_sink=lambda c: 'x', receipt_sink=lambda c, m: 'x')
    ok('Q2 sinks mutually exclusive', False, 'both accepted')
except ValueError as e: ok('Q2 sinks mutually exclusive', True, str(e))
try:
    build_zhipu_api_adapter(credential_resolver=_resolver())
    ok('Q2 one sink mandatory', False, 'none accepted')
except ValueError as e: ok('Q2 one sink mandatory', True, str(e))

print()
print('=== 4. D3: real harness path cross-validates contract<->skill; base refs cannot be frozen ===')
from app.protocol_workflow.runtime.harness import ArtifactRef, build_request
from app.protocol_workflow.agent1.seed_contract import seed_execution_contract
from packages.contracts.workbench_contracts.protocol_v3 import NodeExecutionContract, ReasoningEffort, SensitivityTier
base = NodeExecutionContract(
    node_execution_contract_id='nec:t:seed-generate', skill_definition_id='skill:research-seed:seed-generate',
    role='design_and_summary', harness='graph_runtime', provider='deterministic-offline', model='deterministic-offline',
    reasoning_effort=ReasoningEffort.LOW, same_session_recovery=True, timeout_seconds=300,
    fallback_policy_id='fbp:test', prompt_sha256='a'*64, input_schema_ref='schema:research-seed:seed-generate:input',
    output_schema_ref='schema:research-seed:raw_response', allowed_tools=(), allowed_paths=(),
    permission_policy_id='perm:test', input_artifact_hashes=(prepared.input_sha256,), sensitivity_tier=SensitivityTier.INTERNAL,
    allowed_providers=('deterministic-offline',), allowed_regions=('offline',), redaction_policy_id='redact:test',
    retention_policy_id='retain:test', logical_call_id='call:t:seed-generate', idempotency_key='research-seed.generate.v1')
bound = seed_execution_contract(base, skill=skill, role_entry=role)
ok('D3 factory binds registry URI not graph symbolic ref', bound.output_schema_ref.startswith('https://protocol-v3.local/schemas/research-seed-proposal'))
try:
    build_request(node_contract=base, skill=skill, role_entry=role,
                  artifacts=(ArtifactRef(ref='research-intake', sha256=prepared.input_sha256),),
                  selected_region=role.target_profile.regions[0])
    ok('D3 base symbolic ref rejected by real build_request (cannot freeze base refs)', False, 'accepted')
except Exception as exc:
    ok('D3 base symbolic ref rejected by real build_request (cannot freeze base refs)', type(exc).__name__ == 'HarnessPolicyError', str(exc)[:70])
drifted = bound.model_copy(update={'output_schema_ref': 'https://attacker.example/swap'})
try:
    build_request(node_contract=drifted, skill=skill, role_entry=role,
                  artifacts=(ArtifactRef(ref='research-intake', sha256=prepared.input_sha256),),
                  selected_region=role.target_profile.regions[0])
    ok('D3 drifted contract ref rejected by real build_request', False, 'accepted')
except Exception as exc:
    ok('D3 drifted contract ref rejected by real build_request', 'output_schema_ref' in str(exc), type(exc).__name__)

print()
print('=== 5. D4: schema minItems + explicit empty-candidate guard ===')
schema = seed_output_schema()
arr = [s for s in schema['$defs']['SeedCandidate']['properties']['candidate']['anyOf'] if s.get('type') == 'array']
ok('D4 shipped schema array variant has minItems', arr and arr[0].get('minItems') == 1, arr)
from app.protocol_workflow.agent1.research_seed import _Candidate
try:
    _Candidate.model_validate({'raw': 'r', 'candidate': [], 'confidence': 0.5, 'reason': 'x', 'basis': 'user'})
    ok('D4 pydantic rejects candidate=[]', False, 'accepted')
except Exception as exc:
    ok('D4 pydantic rejects candidate=[]', 'too_short' in str(exc) or 'min_length' in str(exc) or 'at least 1' in str(exc), str(exc)[:80])
import inspect
src = inspect.getsource(__import__('app.protocol_workflow.agent1.research_seed', fromlist=['read_seed_candidates']).read_seed_candidates)
ok('D4 seed_empty_candidate branch retained in source', 'seed_empty_candidate' in src)

print()
print('=== 6. ordered-hash: unsorted artifact tuple fails real binding, sorted passes ===')
h1 = 'a' * 64; h2 = 'b' * 64
c6 = base.model_copy(update={'input_artifact_hashes': tuple(sorted({h1, h2}))}).compact_dependencies()
a_unsorted = (ArtifactRef(ref='z-second', sha256=h2), ArtifactRef(ref='a-first', sha256=h1))
a_sorted = tuple(sorted(a_unsorted, key=lambda a: a.sha256))
kw = dict(skill=skill, role_entry=role, selected_region=role.target_profile.regions[0])
c6b = seed_execution_contract(c6, skill=skill, role_entry=role)
try:
    build_request(node_contract=c6b, artifacts=a_unsorted, **kw)
    ok('ordered-hash unsorted tuple rejected', False, 'accepted')
except Exception as exc:
    ok('ordered-hash unsorted tuple rejected', 'input dependencies changed' in str(exc) or 'does not match' in str(exc), type(exc).__name__)
req = build_request(node_contract=c6b, artifacts=a_sorted, **kw)
ok('ordered-hash sorted tuple accepted', tuple(a.sha256 for a in req.input_artifacts) == (h1, h2))
