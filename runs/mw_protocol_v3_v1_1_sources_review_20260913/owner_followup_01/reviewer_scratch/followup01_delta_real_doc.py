"""F-1 followup: object-level delta of the repaired parser vs first-pass code on MG-K10."""
import hashlib, sys
from collections import Counter

REPO = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313'
FU = REPO + '/runs/mw_protocol_v3_v1_1_sources_review_20260913/owner_followup_01'
sys.path.insert(0, FU + '/reviewer_scratch/oldmirror')  # old_app.*
sys.path.insert(0, REPO + '/services/api')               # app.* (new, frozen live)
sys.path.insert(0, REPO + '/packages')

import old_app.protocol_workflow.agent1.docx_parse as old_mod
import app.protocol_workflow.agent1.docx_parse as new_mod
assert 'oldmirror' in old_mod.__file__ and 'services/api' in new_mod.__file__, (old_mod.__file__, new_mod.__file__)

SRC = '/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx'
payload = open(SRC, 'rb').read()
assert hashlib.sha256(payload).hexdigest() == '73024713c28382ca8fca7c9338d7151256b2765d78d512876731156a9a504199'

FAIL = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' | ' + detail if detail else ''))
    if not cond:
        FAIL.append(name)

def flat(blocks):
    out = []
    def rec(bs):
        for b in bs:
            out.append(b)
            if b.kind == 'table':
                for row in b.rows:
                    for c in row:
                        rec(c.blocks)
    rec(blocks)
    return out

old = flat(old_mod.parse_docx(payload).blocks)
new = flat(new_mod.parse_docx(payload).blocks)
print('old blocks:', len(old), '| new blocks:', len(new))
check('D1 same block count (2608)', len(old) == len(new) == 2608)
check('D2 identical object ids in order', [b.object_id for b in old] == [b.object_id for b in new])
check('D3 identical locators in order', [b.locator for b in old] == [b.locator for b in new])
check('D4 identical texts in order', [b.text for b in old] == [b.text for b in new])
check('D5 identical kinds in order', [b.kind for b in old] == [b.kind for b in new])

role_diff = [(o.locator, o.role, n.role) for o, n in zip(old, new) if o.role != n.role]
print('role deltas:', len(role_diff))
for loc, a, b in role_diff:
    print('  ', loc, a, '->', b)
EXPECT = {'word/document.xml/body/124:p', 'word/document.xml/body/125:p',
          'word/document.xml/body/128:p', 'word/document.xml/body/129:p'}
check('D6 exactly the four first-pass paragraphs reclassified',
      len(role_diff) == 4 and {loc for loc, _, _ in role_diff} == EXPECT
      and all(a == 'body' and b == 'derived_toc' for _, a, b in role_diff))

ro, rn = Counter(b.role for b in old), Counter(b.role for b in new)
print('old roles:', dict(ro), '\nnew roles:', dict(rn))
check('D7 role counts shift only body->derived_toc (1126->1122, 126->130)',
      rn['body'] == ro['body'] - 4 and rn['derived_toc'] == ro['derived_toc'] + 4
      and rn['heading'] == ro['heading'] and rn['header'] == ro['header'] and rn['footer'] == ro['footer'])

do = old_mod.parse_docx(payload)
dn = new_mod.parse_docx(payload)
co, cn = Counter(d.code for d in do.diagnostics), Counter(d.code for d in dn.diagnostics)
print('old diagnostics:', dict(co), '| new diagnostics:', dict(cn))
check('D8 visual pending retained, no field-structure complaint on balanced doc',
      cn.get('visual_objects_pending') == co.get('visual_objects_pending') == 1
      and cn.get('field_structure_pending', 0) == 0)
check('D9 hash/status/pages unchanged',
      dn.content_sha256 == do.content_sha256 and dn.status == 'parsed_pending_source_review'
      and dn.physical_page_count is None and dn.story_parts == do.story_parts)
check('D10 deterministic re-parse (new code)', dn == new_mod.parse_docx(payload))

# the four paragraphs are exactly the bare-field TOC entries verified in pass 1
texts = {loc: n.text[:20] for loc, _, _ in role_diff for n in new if n.locator == loc}
for loc, t in texts.items():
    print('  reclassified entry text head:', loc, '->', t)
print('FAILURES:', FAIL if FAIL else 'none')
