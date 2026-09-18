"""Follow-up: TOC fields outside SDT + corrected locator resolution."""
import hashlib, re, sys
from collections import Counter
from xml.etree import ElementTree as ET
from zipfile import ZipFile

SRC = '/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
payload = open(SRC, 'rb').read()

with ZipFile(SRC) as z:
    doc = ET.fromstring(z.read('word/document.xml'))
    body = doc.find(W + 'body')

parent = {c: p for p in doc.iter() for c in p}

def inside_sdt(el):
    a = parent.get(el)
    while a is not None:
        if a.tag == W + 'sdt':
            return True
        a = parent.get(a)
    return False

def para_of(el):
    a = el
    while a is not None and a.tag != W + 'p':
        a = parent.get(a)
    return a

# distinct TOC instrText elements, classified by sdt containment
toc_els = [t for t in doc.iter(W + 'instrText') if t.text and re.search(r'\bTOC\b', t.text)]
in_sdt = [t for t in toc_els if inside_sdt(t)]
out_sdt = [t for t in toc_els if not inside_sdt(t)]
print('distinct TOC instrText elements:', len(toc_els), '| inside sdt:', len(in_sdt), '| outside sdt:', len(out_sdt))
for t in out_sdt:
    print('  outside-sdt field text[:24]:', (t.text or '')[:24])

# body-level paragraph indices for outside-sdt TOC paragraphs (their parse locator role check)
body_children = list(body)
out_paras = {id(para_of(t)) for t in out_sdt}
for i, ch in enumerate(body_children):
    if id(ch) in out_paras:
        # emulate parse locator
        print('  outside-sdt TOC paragraph body index:', i, 'tag', ch.tag.split('}')[-1])

# other field kinds present at body level (PAGEREF etc. in TOC entries outside sdt)
pageref = [t for t in doc.iter(W + 'instrText') if t.text and 'PAGEREF' in (t.text or '')]
pageref_out = [t for t in pageref if not inside_sdt(t)]
print('PAGEREF instrText total:', len(pageref), '| outside sdt:', len(pageref_out))

# now parse and inspect the roles of those outside-sdt TOC paragraphs
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages')
from app.protocol_workflow.agent1.docx_parse import parse_docx
result = parse_docx(payload)

# map: body index -> projected block with locator word/document.xml/body/{i}:p
by_locator = {b.locator: b for b in result.blocks}
for i, ch in enumerate(body_children):
    if id(ch) in out_paras:
        loc = f'word/document.xml/body/{i}:p'
        b = by_locator.get(loc)
        print('  projected role for outside-sdt TOC para idx', i, '->', b.role if b else 'NO BLOCK (empty text)')
        if b:
            print('    text head:', b.text[:24])

# corrected locator resolution: skip the full part name then walk n:tag segments
def resolve(part_root, locator):
    segs = locator.split('/')
    node = part_root
    for seg in segs[1:]:
        m = re.fullmatch(r'(\d+):(\w+)', seg)
        if not m:
            raise AssertionError(seg)
        node = list(node)[int(m.group(1))]
        assert node.tag.split('}')[-1] == m.group(2)
    return node

with ZipFile(SRC) as z:
    roots = {'word/document.xml': doc}
    for n in z.namelist():
        if re.fullmatch(r'word/(header\d+|footer\d+|footnotes|endnotes)\.xml', n):
            roots[n] = ET.fromstring(z.read(n))

import random
random.seed(20260913)
sample = random.sample(list(result.blocks), 40)
ok = 0
for b in sample:
    part = b.locator.split('/')[0]
    if part == 'word':
        part = 'word/document.xml'
    node = resolve(roots[part], b.locator)
    assert node.tag.split('}')[-1] in ('p', 'tbl')
    ok += 1
print('random-40 locators resolved to real p/tbl XML elements:', ok)

# nested tables + merge markers in projection
nested_proj = 0
for b in result.blocks:
    if b.kind == 'table':
        for row in b.rows:
            for cell in row:
                nested_proj += sum(1 for cb in cell.blocks if cb.kind == 'table')
print('nested tables inside cell projections:', nested_proj, '(XML ground truth: 5)')
spans = [c.grid_span for b in result.blocks if b.kind == 'table' for row in b.rows for c in row]
merges = Counter(c.vertical_merge for b in result.blocks if b.kind == 'table' for row in b.rows for c in row)
print('projected cells gridSpan>1:', sum(1 for s in spans if s > 1), '(XML: 32) | vMerge cells:', sum(merges.values()), '(XML: 40)', dict(merges))

# table text coverage diagnostics on this doc
print('table_text_coverage_pending diagnostics:', sum(1 for d in result.diagnostics if d.code == 'table_text_coverage_pending'))
# total text preservation check: whitespace-normalized union of XML w:t text vs block text
xml_text = ''.join(t.text or '' for t in doc.iter(W + 't'))
proj_text = ''
def collect(blocks):
    global proj_text
    for b in blocks:
        proj_text += b.text
        if b.kind == 'table':
            for row in b.rows:
                for c in row:
                    collect(c.blocks)
collect(result.blocks)
print('document.xml w:t chars:', len(''.join(xml_text.split())), '| projected chars:', len(''.join(proj_text.split())))
