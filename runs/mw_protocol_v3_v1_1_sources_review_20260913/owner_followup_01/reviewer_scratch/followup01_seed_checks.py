"""F-1/O-1 followup: seed labels for TOC entries + source-basis raw binding."""
import sys
from datetime import datetime, timezone
import hashlib

REPO = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313'
for p in ('services/api', 'packages', 'tests'):
    sys.path.insert(0, REPO + '/' + p)

from packages.contracts.workbench_contracts.protocol_v3 import SourceArtifact
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request, read_seed_candidates
from test_writing_reference_docx import build_docx, paragraph_xml

T = datetime(2026, 9, 13, tzinfo=timezone.utc)
FAIL = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' | ' + detail if detail else ''))
    if not cond:
        FAIL.append(name)

# source with a bare-field TOC range and real body text after it
xml = ('<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
       '<w:r><w:instrText> TOC \\h \\z \\c "Table"</w:instrText></w:r>'
       '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
       '<w:p><w:r><w:t>表1 剂量汇总 31</w:t></w:r></w:p>'
       '<w:p><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
       + paragraph_xml('计划比较100 mg和300 mg两个剂量。'))
payload = build_docx(xml)
artifact = SourceArtifact(source_artifact_id='source-t', logical_source_key='k',
                          content_sha256=hashlib.sha256(payload).hexdigest(),
                          source_role='project_primary', source_version='1', jurisdiction='CN',
                          mime_type='application/docx', captured_at=T)
parsed = parse_docx(payload)
roles = [(b.role, b.text) for b in parsed.blocks]
check('S0 fixture: TOC entry derived_toc, real body separate',
      roles == [('derived_toc', '表1 剂量汇总 31'), ('body', '计划比较100 mg和300 mg两个剂量。')], str(roles))

R = prepare_seed_request('', ((artifact, parsed),))
U = {(u['locator']): u for u in R.to_payload()['sources'][0]['units']}
toc_loc = next(l for l, u in U.items() if u['role'] == 'derived_toc')
body_loc = next(l for l, u in U.items() if u['role'] == 'body')

def cand(**kw):
    base = dict(raw='表1 剂量汇总', candidate='表1', confidence=0.9, reason='r',
                basis='source',
                references=[{'source_artifact_id': 'source-t', 'locator': toc_loc, 'quote': '表1 剂量汇总'}])
    base.update(kw)
    return base

def out(c):
    return {'fields': {'indication': [c]}}

# 1. TOC-entry quote under project_primary is NOT project_material
res = read_seed_candidates(R, out(cand()))
f0 = res['fields']['indication'][0]
check('S1 TOC-entry quote not project_material (project_primary)',
      f0['source_support'] == 'reference_only', f0['source_support'])
check('S2 canonical stays empty, confirmation still required',
      f0['canonical'] is None and res['canonical'] == {} and f0['requires_confirmation'])

# 2. raw rule: raw missing from referenced unit text -> reject
try:
    read_seed_candidates(R, out(cand(raw='900 mg剂量')))
    check('S3 invented raw beside valid reference rejected', False)
except ValueError as e:
    check('S3 invented raw beside valid reference rejected', str(e) == 'seed_source_raw_not_found', str(e))

# 3. raw whitespace-only -> reject
try:
    read_seed_candidates(R, out(cand(raw='   ')))
    check('S4 whitespace-only raw rejected', False)
except ValueError as e:
    check('S4 whitespace-only raw rejected', str(e) == 'seed_source_raw_not_found', str(e))

# 4. raw present in a DIFFERENT unit but not the referenced one -> reject
try:
    read_seed_candidates(R, out(cand(raw='计划比较100 mg和300 mg两个剂量。')))
    check('S5 raw from non-referenced unit rejected', False)
except ValueError as e:
    check('S5 raw from non-referenced unit rejected', str(e) == 'seed_source_raw_not_found', str(e))

# 5. raw genuinely inside the referenced unit -> accepted, still proposal
res = read_seed_candidates(R, out(cand(raw='表1 剂量汇总')))
f0 = res['fields']['indication'][0]
check('S6 raw inside referenced unit accepted', f0['source_support'] == 'reference_only'
      and f0['requires_confirmation'] and f0['canonical'] is None)

# 6. multi-reference: raw present in at least one referenced unit
two_refs = {'references': [
    {'source_artifact_id': 'source-t', 'locator': toc_loc, 'quote': '表1 剂量汇总'},
    {'source_artifact_id': 'source-t', 'locator': body_loc, 'quote': '100 mg和300 mg'}]}
res = read_seed_candidates(R, out(cand(raw='100 mg和300 mg', **two_refs)))
check('S7 raw found in any referenced unit accepted (mixed support reference_only)',
      res['fields']['indication'][0]['source_support'] == 'reference_only')

# 7. body-quote raw on body reference -> project_material path still works after repair
res = read_seed_candidates(R, out(cand(raw='计划比较100 mg和300 mg两个剂量。', candidate='两剂量',
                                       references=[{'source_artifact_id': 'source-t',
                                                    'locator': body_loc,
                                                    'quote': '100 mg和300 mg'}])))
check('S8 body-quote candidate still project_material after raw rule',
      res['fields']['indication'][0]['source_support'] == 'project_material')

# 8. user/recommendation bases unaffected by the source-raw rule
res = read_seed_candidates(prepare_seed_request('考虑安慰剂对照', ()), {'fields': {
    'comparator': [{'raw': '安慰剂对照', 'candidate': '安慰剂', 'confidence': 0.8,
                    'reason': 'u', 'basis': 'user', 'references': []}]}})
check('S9 user basis unaffected (raw checked against brief only)',
      res['fields']['comparator'][0]['source_support'] == 'user_intent')
res = read_seed_candidates(R, {'fields': {'comparator': [
    {'raw': '任意建议文字', 'candidate': '安慰剂对照', 'confidence': 0.6, 'reason': 'rec',
     'basis': 'recommendation', 'references': []}]}})
check('S10 recommendation basis unaffected by raw rule',
      res['fields']['comparator'][0]['source_support'] == 'ai_recommendation')

# 9. quote rule unchanged: quote not in unit still rejected before raw rule
bad_ref = {'references': [{'source_artifact_id': 'source-t', 'locator': toc_loc, 'quote': '不存在的引文'}]}
try:
    read_seed_candidates(R, out(cand(raw='表1 剂量汇总', **bad_ref)))
    check('S11 quote binding still enforced', False)
except ValueError as e:
    check('S11 quote binding still enforced', str(e) == 'seed_source_quote_not_found', str(e))

print('FAILURES:', FAIL if FAIL else 'none')
