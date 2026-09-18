"""Claim 1 final: full-population locator resolution + coverage counts."""
import re, sys, random
from xml.etree import ElementTree as ET
from zipfile import ZipFile

SRC = '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/impl_placeholder'
SRC = '/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
payload = open(SRC, 'rb').read()

with ZipFile(SRC) as z:
    roots = {'word/document.xml': ET.fromstring(z.read('word/document.xml'))}
    for n in z.namelist():
        if re.fullmatch(r'word/(header\d+|footer\d+|footnotes|endnotes)\.xml', n):
            roots[n] = ET.fromstring(z.read(n))

sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages')
from app.protocol_workflow.agent1.docx_parse import parse_docx
result = parse_docx(payload)

def resolve(part_root, locator):
    segs = locator.split('/')
    # parse_docx roots: 'word/document.xml/body' (children of w:body) or the
    # bare part name (children of the part root). Match that exactly.
    if part_root.tag.split('}')[-1] == 'document':
        assert segs[2] == 'body'
        node = part_root.find(W + 'body')
        rest = segs[3:]
    else:
        node = part_root
        rest = segs[2:]
    for seg in rest:
        m = re.fullmatch(r'(\d+):(\w+)', seg)
        if not m:
            raise AssertionError(seg)
        node = list(node)[int(m.group(1))]
        assert node.tag.split('}')[-1] == m.group(2)
    return node

def all_blocks(blocks):
    for b in blocks:
        yield b
        if b.kind == 'table':
            for row in b.rows:
                for c in row:
                    yield from all_blocks(c.blocks)

flat = list(all_blocks(result.blocks))
bad = 0
for b in flat:
    part = '/'.join(b.locator.split('/')[:2])
    try:
        node = resolve(roots[part], b.locator)
        assert node.tag.split('}')[-1] in ('p', 'tbl')
    except Exception as e:
        bad += 1
        print('UNRESOLVED', b.locator, e)
print(f'total blocks incl. nested: {len(flat)} | unresolved: {bad}')

nested_proj = sum(1 for b in flat if b.kind == 'table' and '/tc/' in b.locator)
print('nested tables inside cell projections:', nested_proj, '(XML ground truth: 5)')
from collections import Counter
spans = Counter()
merges = Counter()
for b in flat:
    if b.kind == 'table':
        for row in b.rows:
            for c in row:
                if c.grid_span > 1:
                    spans[c.grid_span] += 1
                if c.vertical_merge:
                    merges[c.vertical_merge] += 1
print('projected gridSpan>1 cells:', sum(spans.values()), dict(spans), '(XML: 32)')
print('projected vMerge cells:', sum(merges.values()), dict(merges), '(XML: 40: restart+continue)')
print('table_text_coverage_pending:', sum(1 for d in result.diagnostics if d.code == 'table_text_coverage_pending'))

# whole-population text coverage for document.xml (whitespace-normalized)
doc_root = roots['word/document.xml']
xml_text = ''.join(t.text or '' for t in doc_root.iter(W + 't'))
doc_blocks = [b for b in flat if b.locator.startswith('word/document.xml')]
proj_text = ''.join(b.text for b in doc_blocks)
print('document.xml w:t normalized chars:', len(''.join(xml_text.split())))
print('projected normalized chars (document blocks only):', len(''.join(proj_text.split())))

# TOC-entry paragraphs mislabeled as body: paragraphs containing PAGEREF outside sdt
parent = {c: p for p in doc_root.iter() for c in p}
def inside_sdt(el):
    a = parent.get(el)
    while a is not None:
        if a.tag == W + 'sdt':
            return True
        a = parent.get(a)
    return False
body_children = list(doc_root.find(W + 'body'))
by_locator = {b.locator: b for b in doc_blocks}
mis = []
for t in doc_root.iter(W + 'instrText'):
    txt = t.text or ''
    if ('PAGEREF' in txt or re.search(r'\bTOC\b', txt)) and not inside_sdt(t):
        p = t
        while p is not None and p.tag != W + 'p':
            p = parent.get(p)
        idx = body_children.index(p) if p in body_children else None
        if idx is not None:
            b = by_locator.get(f'word/document.xml/body/{idx}:p')
            if b and b.role == 'body':
                mis.append(idx)
print('outside-sdt TOC/PAGEREF entry paragraphs projected as role=body:', sorted(set(mis)))
