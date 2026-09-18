"""Claim 2: independent functional challenges for SourceIdentityService.

Genuine recovery/function scenarios on real SQLite + LocalArtifactStore under
reviewer_scratch tmp dirs. No monkeypatching except where noted.
"""
import hashlib, json, os, shutil, sqlite3, sys, tempfile, traceback
from datetime import datetime, timezone

sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages')

from app.protocol_workflow.artifacts.local_store import LocalArtifactStore
from app.protocol_workflow.storage.selected import create_product_unit_of_work_factory
from app.protocol_workflow.agent1.source_identity import SourceIdentityService

ROOT = tempfile.mkdtemp(prefix='c03_claim2_', dir=os.path.dirname(os.path.abspath(__file__)))
print('scratch root', ROOT)
T = datetime(2026, 9, 13, tzinfo=timezone.utc)

def service(name):
    d = os.path.join(ROOT, name)
    os.makedirs(d, exist_ok=True)
    return SourceIdentityService(
        create_product_unit_of_work_factory(config={'backend': 'sqlite', 'path': os.path.join(d, 'product.db')}),
        LocalArtifactStore(os.path.join(d, 'artifacts')),
    ), os.path.join(d, 'product.db'), os.path.join(d, 'artifacts')

def adopt(svc, content=b'first', **kw):
    args = dict(project_id='p1', logical_source_key='ib', content=content,
                source_role='project_primary', source_version='1.0', jurisdiction='CN',
                mime_type='application/octet-stream', captured_at=T)
    args.update(kw)
    return svc.adopt(**args)

FAIL = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' | ' + detail if detail else ''))
    if not cond:
        FAIL.append(name)

# A. reopen with exact bytes + revisions + successor replay
svc, db, store = service('A')
a1 = adopt(svc, b'v1')
a2 = adopt(svc, b'v2', source_version='2.0', source_role='regulatory_or_guideline')
# replaying OLD bytes under DIFFERENT metadata is a relabel attempt -> must conflict
try:
    adopt(service('A')[0], b'v1', source_role='regulatory_or_guideline')
    check('A1 old-bytes relabel attempt rejected', False)
except ValueError as e:
    check('A1 old-bytes relabel attempt rejected', str(e).startswith('source_metadata_conflict:'), str(e))
# replaying old bytes with their ORIGINAL metadata replays and preserves successor
r = adopt(service('A')[0], b'v1')
check('A2 replay marks replayed and preserves successor', r.replayed and r.current.source.source_version == '2.0')
check('A3 replay returns the original v1 record identity', r.source.source.source_version == '1.0')
h = service('A')[0].history('p1')
check('A4 history has exactly 2 committed events', len(h) == 2)
# replay bytes matching v1 but conflicting jurisdiction -> conflict, no relabel, no new event
try:
    adopt(service('A')[0], b'v1', jurisdiction='US')
    check('A5 conflicting metadata on historical replay rejected', False)
except ValueError as e:
    check('A5 conflicting metadata on historical replay rejected',
          str(e).startswith('source_metadata_conflict:'), str(e))
check('A6 no event appended by rejected replay', len(service('A')[0].history('p1')) == 2)

# B. only committed events select current; filesystem staging never becomes current
svcB, dbB, storeB = service('B')
b1 = adopt(svcB, b'body-v1')
# stage NEW bytes straight into the artifact store under the true storage key, no event
from app.protocol_workflow.agent1.source_identity import _digest
key = 'source-' + _digest('p1', 'ib')
meta = LocalArtifactStore(storeB).store(key, b'rogue-newer-bytes', media_type='application/octet-stream', created_at=T)
cur = service('B')[0].list_current('p1')
check('B1 filesystem-latest does not become current', cur[0].source.content_sha256 == hashlib.sha256(b'body-v1').hexdigest())
check('B2 staged rogue bytes exist but unselected', LocalArtifactStore(storeB).has_content(hashlib.sha256(b'rogue-newer-bytes').hexdigest()))
# now genuinely adopt those bytes: uses existing staging, creates event
b2 = adopt(svcB, b'rogue-newer-bytes', source_version='2.0')
check('B3 adopting staged bytes selects them via event', service('B')[0].list_current('p1')[0].source.source_version == '2.0')

# C. genuine SQLite commit failure: writer lock held by another connection
svcC, dbC, storeC = service('C')
c1 = adopt(svcC, b'c1')
locker = sqlite3.connect(dbC, timeout=10, isolation_level=None)
locker.execute('BEGIN IMMEDIATE')
try:
    adopt(svcC, b'c2', source_version='2.0')
    check('C1 locked begin/commit raises', False)
except sqlite3.OperationalError as e:
    check('C1 locked begin/commit raises OperationalError', 'locked' in str(e), str(e)[:60])
locker.execute('ROLLBACK'); locker.close()
check('C2 current unchanged after locked failure', service('C')[0].list_current('p1')[0].source.content_sha256 == hashlib.sha256(b'c1').hexdigest())
check('C3 no staging when transaction never opened',
      not LocalArtifactStore(storeC).has_content(hashlib.sha256(b'c2').hexdigest()))
c2 = adopt(service('C')[0], b'c2', source_version='2.0')
check('C4 retry after lock adopts cleanly', not c2.replayed and len(service('C')[0].history('p1')) == 2)
check('C5 old bytes still readable after retry', service('C')[0].read_content('p1', c1.source.source.source_artifact_id) == b'c1')

# C2b. genuine SQL failure AFTER staging: rogue event occupies the next
# deterministic domain_event_id, so append_events rejects the batch after
# the artifact store already staged the bytes.
from app.protocol_workflow.events.models import EventEnvelopeBuilder
from packages.contracts.workbench_contracts.protocol_v3 import ActorType, SourceArtifact as SA
svcX, dbX, storeX = service('X')
x1 = adopt(svcX, b'x1')
rogue_content = b'x2'
rogue_sha = hashlib.sha256(rogue_content).hexdigest()
rogue_id = 'source-event-' + _digest('p1', 'ib', rogue_sha)
rogue_source = SA(source_artifact_id='source-rogue', logical_source_key='rogue', content_sha256=rogue_sha,
                  source_role='project_primary', source_version='9', jurisdiction='CN',
                  mime_type='application/octet-stream', captured_at=T)
conn = sqlite3.connect(dbX)
head = conn.execute("SELECT event_sha256 FROM event_stream WHERE project_id='p1' AND stream_id='source_catalog' ORDER BY sequence DESC LIMIT 1").fetchone()
ev2 = EventEnvelopeBuilder().build(domain_event_id=rogue_id, stream_id='source_catalog', sequence=2,
                                   event_type='source.identity.adopted', payload_schema_version='source_identity.v1',
                                   upcaster_id='none', actor_type=ActorType.SYSTEM, actor_id='rogue',
                                   action='adopt_source_identity', reason='occupy id',
                                   payload={'project_id': 'p1', 'source': rogue_source.model_dump(mode='json'),
                                            'storage_key': 'rogue', 'storage_revision': 1},
                                   emitted_at=T, previous_event_sha256=head[0])
conn.execute("INSERT INTO event_stream (project_id, stream_id, sequence, domain_event_id, previous_event_sha256, event_sha256, body_json) VALUES (?,?,?,?,?,?,?)",
             ('p1', 'source_catalog', 2, rogue_id, head[0], ev2.event_sha256, ev2.model_dump_json()))
conn.commit(); conn.close()
try:
    adopt(service('X')[0], rogue_content, source_version='2.0')
    check('C6 post-staging append failure raises', False)
except Exception as e:
    check('C6 post-staging append failure raises', 'duplicate domain_event_id' in str(e), type(e).__name__)
check('C7 current unchanged after post-staging failure', service('X')[0].list_current('p1')[0].source.content_sha256 == hashlib.sha256(b'x1').hexdigest())
check('C8 staging retained after post-staging failure', LocalArtifactStore(storeX).has_content(rogue_sha))
check('C9 old bytes still readable', service('X')[0].read_content('p1', x1.source.source.source_artifact_id) == b'x1')
other = adopt(service('X')[0], b'unrelated', logical_source_key='other-key')
check('C10 unrelated key still adopts after failure', not other.replayed)

# D. event tampering detected on next read (functional integrity, not adversarial)
svcD, dbD, storeD = service('D')
d1 = adopt(svcD, b'd1')
conn = sqlite3.connect(dbD)
row = conn.execute("SELECT body_json FROM event_stream WHERE stream_id='source_catalog'").fetchone()
body = json.loads(row[0]); body['payload']['source']['source_version'] = 'tampered'
conn.execute("UPDATE event_stream SET body_json=? WHERE stream_id='source_catalog'", (json.dumps(body),))
conn.commit(); conn.close()
try:
    service('D')[0].history('p1')
    check('D1 tampered event stream rejected', False)
except ValueError as e:
    check('D1 tampered event stream rejected (chain)', str(e) == 'source_catalog_event_invalid', str(e))
except RuntimeError as e:
    check('D1 tampered event stream rejected (hash integrity)', 'mismatch' in str(e), type(e).__name__)

# E. same bytes under two logical keys: distinct identities, both current
svcE, _, _ = service('E')
e1 = adopt(svcE, b'same')
e2 = adopt(svcE, b'same', logical_source_key='ib-copy')
check('E1 distinct ids for distinct logical keys', e1.source.source.source_artifact_id != e2.source.source.source_artifact_id)
cur = {r.source.logical_source_key for r in svcE.list_current('p1')}
check('E2 both keys current', cur == {'ib', 'ib-copy'})

# F. cross-project isolation with identical key+bytes
svcF, _, _ = service('F')
f1 = adopt(svcF, b'shared')
f2 = adopt(svcF, b'shared', project_id='p2')
check('F1 project-scoped ids differ', f1.source.source.source_artifact_id != f2.source.source.source_artifact_id)
check('F2 histories isolated', len(svcF.history('p1')) == 1 and len(svcF.history('p2')) == 1)

# G. whitespace key normalization + empty key behavior
svcG, _, _ = service('G')
g1 = adopt(svcG, b'g', logical_source_key='  ib  ')
g2 = adopt(svcG, b'g', logical_source_key='ib')
check('G1 whitespace-normalized replay', g2.replayed and g1.source.source.logical_source_key == 'ib')
try:
    adopt(svcG, b'g', logical_source_key='   ')
    check('G2 whitespace-only key rejected', False)
except Exception as e:
    check('G2 whitespace-only key rejected', type(e).__name__ == 'ValidationError', type(e).__name__)

# H. store loss after committed events (dependency reality, no invention)
svcH, _, storeH = service('H')
h1 = adopt(svcH, b'h1')
shutil.rmtree(storeH)
try:
    svcH.read_content('p1', h1.source.source.source_artifact_id)
    check('H1 missing staging detected', False)
except Exception as e:
    check('H1 missing staging detected loudly', type(e).__name__ == 'ArtifactNotFoundError', type(e).__name__)
check('H2 identity survives staging loss', svcH.list_current('p1')[0].source.content_sha256 == hashlib.sha256(b'h1').hexdigest())

print('FAILURES:', FAIL if FAIL else 'none')
shutil.rmtree(ROOT, ignore_errors=True)
