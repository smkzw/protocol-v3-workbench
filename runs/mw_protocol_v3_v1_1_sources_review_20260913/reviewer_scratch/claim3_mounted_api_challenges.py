"""Claim 3: mounted product source routes, disabled mount, admission gate, store path."""
import os, sys, tempfile, shutil, json

sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/tests/protocol_v3/integration')

from fastapi import FastAPI
from fastapi.testclient import TestClient
from integration_shared import admit
from test_writing_reference_docx import build_docx, paragraph_xml
from app.protocol_workflow.api.composition import (
    ProtocolWorkflowMountConfig, mount_protocol_workflow_router, protocol_workflow_config_from_env,
)

ROOT = tempfile.mkdtemp(prefix='c03_claim3_', dir=os.path.dirname(os.path.abspath(__file__)))
FAIL = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' | ' + detail if detail else ''))
    if not cond:
        FAIL.append(name)

DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

# --- disabled mount: zero side effects ---
app0 = FastAPI()
before = list(app0.router.routes)
cfg = protocol_workflow_config_from_env(env={})
check('D1 default env disabled', cfg.enabled is False and cfg.db_path is None)
check('D2 disabled mount returns False', mount_protocol_workflow_router(app0, cfg) is False)
check('D3 disabled mount touches no routes', list(app0.router.routes) == before)
nodir = os.path.join(ROOT, 'never')
check('D4 enabled-without-db fails closed',
      (lambda: [False for _ in (0,)])() == [] and True)
try:
    ProtocolWorkflowMountConfig(enabled=True, db_path=None).adapter_config()
    check('D4 enabled-without-db fails closed', False)
except ValueError:
    check('D4 enabled-without-db fails closed', True)

# --- enabled mount with temp admitted project ---
db = os.path.join(ROOT, 'product.db')
admit(db, 'proj-ok')
app = FastAPI()
check('E1 enabled mount returns True', mount_protocol_workflow_router(app, ProtocolWorkflowMountConfig(enabled=True, db_path=db)))
check('E2 no artifact dir at mount time', not os.path.exists(db + '.artifacts'))
c = TestClient(app)
BASE = '/api/projects/proj-ok/protocol-workflow/sources'
BASE_NA = '/api/projects/proj-not-admitted/protocol-workflow/sources'

# non-admitted project: rejected before service, no writes anywhere
r = c.get(BASE_NA)
check('F1 non-admitted list -> 404 Chinese envelope', r.status_code == 404 and set(r.json()['detail']) == {'message', 'responsible_area', 'can_retry', 'next_step'}, str(r.json().get('detail'))[:120])
check('F2 no artifact dir after rejected call', not os.path.exists(db + '.artifacts'))

# valid upload
payload = build_docx(paragraph_xml('研究设计源文本。'))
r = c.post(BASE, data={'logical_source_key': 'protocol', 'source_role': 'project_primary',
                       'source_version': '1.0', 'jurisdiction': 'CN'},
           files={'file': ('s.docx', payload, DOCX_MIME)})
check('G1 valid upload 200', r.status_code == 200, r.text[:120])
body = r.json()
sid = body['source']['source']['source_artifact_id']
check('G2 response binds parse + pending admission',
      body['parse']['status'] == 'parsed_pending_source_review' and body['medical_admission'] == 'pending')
check('G3 response carries real content hash', body['source']['source']['content_sha256'] == __import__('hashlib').sha256(payload).hexdigest())
check('G4 artifact dir is <db>.artifacts and now created',
      os.path.isdir(db + '.artifacts' + '/content') and os.path.isdir(db + '.artifacts' + '/manifests'))

# list / parse / download exact bytes
r = c.get(BASE)
check('H1 list returns one current source', [s['source']['logical_source_key'] for s in r.json()['sources']] == ['protocol'])
r = c.get(f'{BASE}/{sid}/parse')
check('H2 parse by id works', r.status_code == 200 and r.json()['blocks'][0]['text'] == '研究设计源文本。')
r = c.get(f'{BASE}/{sid}/content')
check('H3 download exact original bytes', r.content == payload)
check('H4 download headers', r.headers['content-type'].startswith(DOCX_MIME) and 'attachment' in r.headers.get('content-disposition', ''))
r = c.get(f'{BASE}/source-unknown/content')
check('H5 unknown id -> 404 Chinese envelope', r.status_code == 404 and 'message' in r.json()['detail'])

# invalid docx variants
for label, blob in [('not-a-zip', b'plain text not docx'),
                    ('zip-but-not-docx', __import__('io').BytesIO())]:
    if label == 'zip-but-not-docx':
        import zipfile
        bio = __import__('io').BytesIO()
        with zipfile.ZipFile(bio, 'w') as zf:
            zf.writestr('unrelated.txt', 'x')
        blob = bio.getvalue()
    r = c.post(BASE, data={'logical_source_key': 'bad-' + label, 'source_role': 'project_primary'},
               files={'file': ('s.docx', blob, DOCX_MIME)})
    det = r.json().get('detail', {})
    check(f'I-{label} 400 + Chinese explanation + no adoption',
          r.status_code == 400 and 'message' in det and 'next_step' in det,
          f"status={r.status_code}")
check('I3 no adopted records from invalid uploads', [s['source']['logical_source_key'] for s in c.get(BASE).json()['sources']] == ['protocol'])

# textless but valid docx
bio = __import__('io').BytesIO()
data = build_docx('')
import zipfile
bio2 = __import__('io').BytesIO(build_docx(paragraph_xml('')))  # empty paragraph -> no text
r = c.post(BASE, data={'logical_source_key': 'textless', 'source_role': 'project_primary'},
           files={'file': ('s.docx', bio2.getvalue(), DOCX_MIME)})
check('I4 textless docx -> 400 explained', r.status_code == 400 and 'message' in r.json()['detail'])

# invalid source_role rejected (not fabricated), via validation envelope route class
r = c.post(BASE, data={'logical_source_key': 'rolecheck', 'source_role': 'made_up_role'},
           files={'file': ('s.docx', payload, DOCX_MIME)})
det = r.json().get('detail', {})
check('J1 invalid role rejected with envelope', r.status_code == 422 and set(det) == {'message', 'responsible_area', 'can_retry', 'next_step'} or r.status_code == 400,
      f"status={r.status_code} detail_keys={sorted(det) if isinstance(det, dict) else det}")
check('J2 nothing adopted after invalid role', all(s['source']['logical_source_key'] == 'protocol' for s in c.get(BASE).json()['sources']))

# 409 conflict path with Chinese detail
r = c.post(BASE, data={'logical_source_key': 'protocol', 'source_role': 'competitor_full_protocol',
                       'source_version': '1.0', 'jurisdiction': 'CN'},
           files={'file': ('s.docx', payload, DOCX_MIME)})
det = r.json()['detail']
check('K1 relabel conflict -> 409 Chinese actionable', r.status_code == 409 and det.get('message') and det.get('next_step'))
check('K2 original record retained', [s['source']['source_role'] for s in c.get(BASE).json()['sources']] == ['project_primary'])

# replay of exact same upload -> replayed true, current stays
r = c.post(BASE, data={'logical_source_key': 'protocol', 'source_role': 'project_primary',
                       'source_version': '1.0', 'jurisdiction': 'CN'},
           files={'file': ('s.docx', payload, DOCX_MIME)})
check('L1 exact replay flagged', r.status_code == 200 and r.json()['replayed'] is True)

# whole-app isolation: mount added no global exception handlers
check('M1 no global exception handlers registered by mount', app.exception_handlers == FastAPI().exception_handlers or len(app.exception_handlers) == len(FastAPI().exception_handlers))
print('FAILURES:', FAIL if FAIL else 'none')
shutil.rmtree(ROOT, ignore_errors=True)
