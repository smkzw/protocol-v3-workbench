"""Claim 4: adversarial input challenges for the sparse seed compiler."""
import sys
from datetime import datetime, timezone
import hashlib

REPO = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313'
for p in ('services/api', 'packages', 'tests'):
    sys.path.insert(0, REPO + '/' + p)

from packages.contracts.workbench_contracts.protocol_v3 import SourceArtifact
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
from test_writing_reference_docx import build_docx, paragraph_xml, table_xml

T = datetime(2026, 9, 13, tzinfo=timezone.utc)
FAIL = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' | ' + detail if detail else ''))
    if not cond:
        FAIL.append(name)

def src(role='project_primary', body=None, sid='source-a'):
    xml = body if body is not None else (
        paragraph_xml('计划比较100 mg和300 mg两个剂量。', style='Heading1')
        + paragraph_xml('本品适用于慢性荨麻疹。')
        + table_xml([['访视', '剂量'], ['V1', '100 mg'], ['V2', '300 mg']]))
    payload = build_docx(xml)
    return SourceArtifact(
        source_artifact_id=sid, logical_source_key='k',
        content_sha256=hashlib.sha256(payload).hexdigest(), source_role=role,
        source_version='1', jurisdiction='CN', mime_type='application/docx',
        captured_at=T), parse_docx(payload)

def req(sources, brief='考虑安慰剂对照'):
    return prepare_seed_request(brief, tuple(sources))

def units_of(request):
    out = {}
    for s in request.to_payload()['sources']:
        for u in s['units']:
            out[(s['source_artifact_id'], u['locator'])] = u
    return out

R = req((src(), src(sid='source-b', role='company_style_only', body=paragraph_xml('参考内容引文。'))))
U = units_of(R)

def cand(**kw):
    base = dict(raw='100 mg和300 mg', candidate=['100 mg', '300 mg'], confidence=0.9,
                reason='r', basis='source', references=[])
    base.update(kw)
    return base

def body_ref(sid, locator, quote):
    return {'source_artifact_id': sid, 'locator': locator, 'quote': quote}

def fields(field, c):
    return {'fields': {field: [c]}}

body_loc = next(loc for (sid, loc), u in U.items()
                if sid == 'source-a' and u['role'] == 'body' and u['kind'] == 'paragraph' and '慢性荨麻疹' in u['text'])
head_loc = next(loc for (sid, loc), u in U.items() if sid == 'source-a' and u['role'] == 'heading')
cell_loc = next(loc for (sid, loc), u in U.items()
                if sid == 'source-a' and u['kind'] == 'table_cell' and '100 mg' in u['text'])
other_loc = next(loc for (sid, loc), u in U.items() if sid == 'source-b')

def rejects(name, out, want):
    try:
        read_seed_candidates(R, out)
        check(name, False)
    except ValueError as e:
        check(name, want in str(e), str(e))

# quote binding
rejects('Q1 wrong-source quote rejected',
        fields('anticipated_dose', cand(references=[body_ref('source-b', body_loc, '慢性荨麻疹')])),
        'seed_source_quote_not_found')
rejects('Q2 wrong-locator quote rejected',
        fields('anticipated_dose', cand(references=[body_ref('source-a', head_loc, '慢性荨麻疹')])),
        'seed_source_quote_not_found')
rejects('Q3 fabricated locator rejected',
        fields('anticipated_dose', cand(references=[body_ref('source-a', 'word/document.xml/body/999:p', '慢性荨麻疹')])),
        'seed_source_quote_not_found')
rejects('Q4 spliced/concatenated quote rejected',
        fields('anticipated_dose', cand(references=[body_ref('source-a', cell_loc, 'V1V2')])),
        'seed_source_quote_not_found')

# role labeling
R2 = req((src(role='competitor_full_protocol', sid='source-a'),))
u2 = units_of(R2)
loc2 = next(l for (s, l), u in u2.items()
            if u['role'] == 'body' and u['kind'] == 'paragraph' and '慢性' in u['text'])
out5 = fields('indication', cand(references=[body_ref('source-a', loc2, '慢性荨麻疹')]))
res = read_seed_candidates(R2, out5)
check('Q5 competitor body quote stays reference_only',
      res['fields']['indication'][0]['source_support'] == 'reference_only')
out6 = fields('indication', cand(references=[body_ref('source-a', head_loc, '计划比较100 mg和300 mg两个剂量。')]))
res = read_seed_candidates(R, out6)
check('Q6 heading quote not project_material',
      res['fields']['indication'][0]['source_support'] == 'reference_only',
      res['fields']['indication'][0]['source_support'])
out7 = fields('indication', cand(references=[body_ref('source-a', body_loc, '慢性荨麻疹')]))
res = read_seed_candidates(R, out7)
check('Q7 body quote -> project_material',
      res['fields']['indication'][0]['source_support'] == 'project_material')
out8 = fields('anticipated_dose', cand(references=[body_ref('source-a', cell_loc, '100 mg')]))
res = read_seed_candidates(R, out8)
check('Q8 table-cell body quote -> project_material',
      res['fields']['anticipated_dose'][0]['source_support'] == 'project_material')
mixed = cand(references=[body_ref('source-a', body_loc, '慢性荨麻疹'),
                         body_ref('source-b', other_loc, '参考内容引文。')])
res = read_seed_candidates(R, fields('indication', mixed))
check('Q9 mixed support degrades to reference_only',
      res['fields']['indication'][0]['source_support'] == 'reference_only')

# user basis
ok_user = fields('comparator', cand(raw='安慰剂对照', candidate='安慰剂', confidence=0.8,
                                    reason='u', basis='user'))
res = read_seed_candidates(req((), brief='考虑安慰剂对照设计'), ok_user)
check('U1 user quote from brief accepted, labeled user_intent',
      res['fields']['comparator'][0]['source_support'] == 'user_intent')
rejects('U2 unseen user quote rejected',
        fields('comparator', cand(raw='阳性药对照', candidate='阳性药', basis='user')),
        'seed_user_quote_not_found')
rejects('U3 whitespace-only user raw rejected',
        fields('comparator', cand(raw='   ', candidate='x', basis='user')),
        'seed_user_quote_not_found')

# structure validation
rejects('S1 unknown field key rejected', {'fields': {'not_a_field': [cand()]}}, 'seed_fields_invalid')
rejects('S2 candidate not list rejected', {'fields': {'indication': cand()}}, 'seed_candidate_list_required')
rejects('S3 empty candidate list rejected', fields('indication', cand(candidate=[])), 'seed_empty_candidate')
rejects('S4 source basis without references rejected',
        fields('indication', cand(basis='source', references=[])), 'seed_source_reference_required')
rejects('S5 extra candidate key rejected', fields('indication', dict(cand(), surprise=1)), 'Extra inputs')
rejects('S6 confidence >1 rejected', fields('indication', cand(confidence=1.5)), '')
res = read_seed_candidates(R, fields('indication', cand(confidence=0.0, basis='recommendation')))
check('S7 confidence bounds accepted (0.0)', res['fields']['indication'][0]['confidence'] == 0.0)
res = read_seed_candidates(R, fields('indication', cand(confidence=1.0, basis='recommendation')))
check('S7b confidence bounds accepted (1.0)', res['fields']['indication'][0]['confidence'] == 1.0)

# proposal semantics
cell300_loc = next(loc for (sid, loc), u in U.items()
                   if sid == 'source-a' and u['kind'] == 'table_cell' and '300 mg' in u['text'])
multi = {'fields': {'anticipated_dose': [
    cand(references=[body_ref('source-a', cell_loc, '100 mg')]),
    cand(raw='300', candidate=['300 mg'], confidence=0.7, reason='d2', basis='source',
         references=[body_ref('source-a', cell300_loc, '300 mg')])]}}
res = read_seed_candidates(R, multi)
doses = res['fields']['anticipated_dose']
check('P1 multi-dose candidates all retained',
      [d['candidate'] for d in doses] == [['100 mg', '300 mg'], ['300 mg']])
check('P2 canonical empty everywhere',
      all(d['canonical'] is None for d in doses) and res['canonical'] == {})
check('P3 requires_confirmation always set', all(d['requires_confirmation'] for d in doses))
check('P4 confidence labeled as model estimate',
      all(d['confidence_basis'] == 'model_estimate_not_medical_admission' for d in doses))
EIGHT = ('research_drug', 'dosage_form_and_route', 'anticipated_dose', 'target_or_mechanism',
         'indication', 'clinical_phase', 'populations', 'comparator')
check('P5 missing explicit + status',
      bool(res['missing_fields']) and res['status'] == 'needs_information'
      and set(res['missing_fields']) <= set(EIGHT))
check('P6 user_brief preserved verbatim', res['user_brief'] == '考虑安慰剂对照')
res7 = read_seed_candidates(R, {'fields': {f: [cand(basis='recommendation')] for f in EIGHT}})
check('P7 all eight present -> ready_for_review, no canonical',
      res7['status'] == 'ready_for_review' and res7['canonical'] == {})

# recommendation basis
res = read_seed_candidates(R, fields('comparator', cand(raw='建议安慰剂对照', candidate='安慰剂对照',
                                                        basis='recommendation')))
check('R1 recommendation labeled ai_recommendation',
      res['fields']['comparator'][0]['source_support'] == 'ai_recommendation')

# request-build integrity
a1, p1 = src()
a2, p2 = src()
try:
    prepare_seed_request('b', ((a1, p1), (a2, p2)))
    check('X1 duplicate source id rejected', False)
except ValueError as e:
    check('X1 duplicate source id rejected', str(e) == 'seed_duplicate_source_identity', str(e))
wrong = a1.model_copy(update={'content_sha256': '0' * 64})
try:
    prepare_seed_request('b', ((wrong, p1),))
    check('X2 hash mismatch rejected', False)
except ValueError as e:
    check('X2 hash mismatch rejected', str(e) == 'seed_source_hash_mismatch', str(e))

# sparse intake legal
sparse = prepare_seed_request('希望研究慢性荨麻疹', ())
res = read_seed_candidates(sparse, {'fields': {}})
check('P8 sparse empty request legal, 8 missing',
      res['status'] == 'needs_information' and len(res['missing_fields']) == 8)

print('FAILURES:', FAIL if FAIL else 'none')
