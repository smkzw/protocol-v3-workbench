"""Claim 5: seed-request sizing on the real MG-K10 source DOCX."""
import hashlib, json, sys
from datetime import datetime, timezone

REPO = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313'
for p in ('services/api', 'packages', 'tests'):
    sys.path.insert(0, REPO + '/' + p)

from packages.contracts.workbench_contracts.protocol_v3 import SourceArtifact
from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request, _units

SRC = '/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx'
payload = open(SRC, 'rb').read()
T = datetime(2026, 9, 13, tzinfo=timezone.utc)

artifact = SourceArtifact(
    source_artifact_id='source-mgk10', logical_source_key='mgk10-protocol',
    content_sha256=hashlib.sha256(payload).hexdigest(), source_role='project_primary',
    source_version='1.3', jurisdiction='CN',
    mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    captured_at=T)
parsed = parse_docx(payload)

FAIL = []
def check(name, cond, detail=''):
    print(('PASS ' if cond else 'FAIL ') + name + (' | ' + detail if detail else ''))
    if not cond:
        FAIL.append(name)

req = prepare_seed_request('评估MG-K10治疗慢性荨麻疹的II期设计', ((artifact, parsed),))
data = req.to_payload()
src = data['sources'][0]
units = src['units']

# 1. sizing facts
print('payload bytes:', len(req.payload_json.encode()))
print('units:', len(units), '| blocks (top-level):', len(parsed.blocks))
para_units = [u for u in units if u['kind'] == 'paragraph']
cell_units = [u for u in units if u['kind'] == 'table_cell']
print('paragraph units:', len(para_units), '| table-cell units:', len(cell_units))

# every leaf paragraph block became exactly one unit
def leaf_paragraphs(blocks):
    n = 0
    for b in blocks:
        if b.kind == 'table':
            for row in b.rows:
                for c in row:
                    n += leaf_paragraphs(c.blocks)
        elif b.kind == 'paragraph':
            n += 1
    return n
check('Z1 all leaf paragraph blocks retained as units (no truncation)',
      len(units) == leaf_paragraphs(parsed.blocks),
      f"units={len(units)} leaf_paragraphs={leaf_paragraphs(parsed.blocks)}")

# text completeness: unit text union equals leaf text union (whitespace-normalized)
leaf_text = []
def collect(blocks):
    for b in blocks:
        if b.kind == 'table':
            for row in b.rows:
                for c in row:
                    collect(c.blocks)
        else:
            leaf_text.append(b.text)
collect(parsed.blocks)
check('Z2 unit text == leaf block text (no silent loss/alteration)',
      ''.join(''.join(u['text'] for u in units).split()) == ''.join(''.join(leaf_text).split()))

# 2. row/cell grouping without repeated row text
row_groups = {}
for u in cell_units:
    row_groups.setdefault(u['table_row'], []).append(u)
multi_cell_rows = {r: us for r, us in row_groups.items() if len(us) > 1}
row_repeat = 0   # units carrying the parser-joined row text (tab-joined) = real repetition
source_substrings = 0  # one cell's own text happening to be a substring of another = source content
for r, us in multi_cell_rows.items():
    ordered = sorted(us, key=lambda x: x['cell_index'])
    row_text = '\t'.join(u['text'] for u in ordered)
    for u in ordered:
        if u['text'] and row_text in u['text'] and len(u['text']) > len(row_text) - 1:
            row_repeat += 1
    texts = [u['text'] for u in ordered]
    for i, t in enumerate(texts):
        for j, other in enumerate(texts):
            if i != j and t and len(t) < len(other) and t in other:
                source_substrings += 1
print('multi-cell rows:', len(multi_cell_rows),
      '| units carrying joined row text (parser repetition):', row_repeat,
      '| source-level substring coincidences:', source_substrings)
check('Z3 no unit carries the joined row text (row text not repeated per cell)', row_repeat == 0)
# show one coincidence row as evidence these are source content, not parser artifacts
for r, us in list(multi_cell_rows.items()):
    texts = [u['text'] for u in sorted(us, key=lambda x: x['cell_index'])]
    if any(t and len(t) < len(o) and t in o for t in texts for o in texts if t is not o):
        print('sample coincidence row cells (truncated 16 chars):',
              [t[:16] for t in texts])
        break
# row membership explicit: every cell unit carries table_row + cell_index
check('Z4 cell units carry row/cell coordinates',
      all('table_row' in u and 'cell_index' in u for u in cell_units))

# 3. size comparison vs naive row-repeat projection (what dedup removed)
naive_extra = 0
for r, us in multi_cell_rows.items():
    row_text = '\t'.join(u['text'] for u in sorted(us, key=lambda x: x['cell_index']))
    for u in us:
        naive_extra += len(row_text) - len(u['text'])
print('chars removed vs naive row-repeat-per-cell projection:', naive_extra)

# 4. XML traceability of every unit locator (blocks already proven; re-assert sample incl. cells)
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
with ZipFile(SRC) as z:
    roots = {'word/document.xml': ET.fromstring(z.read('word/document.xml'))}
    for n in z.namelist():
        if re.fullmatch(r'word/(header\d+|footer\d+|footnotes|endnotes)\.xml', n):
            roots[n] = ET.fromstring(z.read(n))
def resolve(part_root, locator):
    segs = locator.split('/')
    if part_root.tag.split('}')[-1] == 'document':
        node = part_root.find(W + 'body'); rest = segs[3:]
    else:
        node = part_root; rest = segs[2:]
    for seg in rest:
        m = re.fullmatch(r'(\d+):(\w+)', seg)
        node = list(node)[int(m.group(1))]
        assert node.tag.split('}')[-1] == m.group(2)
    return node
bad = 0
for u in units:
    part = '/'.join(u['locator'].split('/')[:2])
    try:
        resolve(roots[part], u['locator'])
    except Exception:
        bad += 1
check('Z5 every unit locator resolves to a real XML element', bad == 0, f'unresolved={bad}')

# 5. request carries identities/units/diagnostics; hash binding
check('Z6 request binds real source identity + hash + role/version',
      src['source_artifact_id'] == 'source-mgk10' and src['content_sha256'] == artifact.content_sha256
      and src['source_role'] == 'project_primary' and src['source_version'] == '1.3')
check('Z7 diagnostics carried into request (visual pending explicit)',
      any(d['code'] == 'visual_objects_pending' for d in src['diagnostics']))
check('Z8 stable request hash', req.input_sha256 == hashlib.sha256(req.payload_json.encode()).hexdigest()
      and prepare_seed_request('评估MG-K10治疗慢性荨麻疹的II期设计', ((artifact, parsed),)).input_sha256 == req.input_sha256)
print('payload/input_sha256:', req.input_sha256)

# 6. per-field budget sanity: largest unit, chars total
mx = max(units, key=lambda u: len(u['text']))
print('largest unit text chars:', len(mx['text']), '| locator head:', mx['locator'][:60])
print('total unit text chars:', sum(len(u['text']) for u in units))
print('FAILURES:', FAIL if FAIL else 'none')
