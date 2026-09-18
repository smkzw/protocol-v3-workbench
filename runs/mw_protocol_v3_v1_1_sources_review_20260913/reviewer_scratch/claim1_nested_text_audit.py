"""Claim 1 precise nested-table + non-overlapping text coverage audit."""
import re, sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

SRC = '/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
payload = open(SRC, 'rb').read()
doc = ET.fromstring(ZipFile(SRC).read('word/document.xml')) if False else None
with ZipFile(SRC) as z:
    doc = ET.fromstring(z.read('word/document.xml'))

sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages')
from app.protocol_workflow.agent1.docx_parse import parse_docx
result = parse_docx(payload)

def all_blocks(blocks):
    for b in blocks:
        yield b
        if b.kind == 'table':
            for row in b.rows:
                for c in row:
                    yield from all_blocks(c.blocks)

flat = [b for b in all_blocks(result.blocks) if b.locator.startswith('word/document.xml')]

# 1. nested tables: XML ground truth locators via independent path walk
parent = {c: p for p in doc.iter() for c in p}
body_children = list(doc.find(W + 'body'))

def xml_path(el, stop_at):
    segs = []
    node = el
    while node is not None and node is not stop_at:
        segs.append(f'{list(parent.get(node)).index(node)}:{node.tag.split("}")[-1]}')
        node = parent.get(node)
    return '/'.join(reversed(segs))

body = doc.find(W + 'body')
xml_tables = {}
for tbl in doc.iter(W + 'tbl'):
    xml_tables['word/document.xml/body/' + xml_path(tbl, body)] = tbl
proj_tables = {b.locator: b for b in flat if b.kind == 'table'}
print('XML tables total:', len(xml_tables), '| projected tables:', len(proj_tables))
print('locator sets equal:', set(xml_tables) == set(proj_tables))
nested_xml = [loc for loc in xml_tables if ':tc/' in loc]
print('XML nested-table locators:', nested_xml)
print('projected nested tables:', [loc for loc in proj_tables if ':tc/' in loc])

# 2. non-overlapping text: leaf paragraphs only vs all w:t in XML
leaf_chars = ''.join(b.text for b in flat if b.kind == 'paragraph')
xml_chars = ''.join(t.text or '' for t in doc.iter(W + 't'))
print('leaf paragraph normalized chars:', len(''.join(leaf_chars.split())))
print('XML w:t normalized chars:', len(''.join(xml_chars.split())))
print('equal:', ''.join(leaf_chars.split()) == ''.join(xml_chars.split()))
# any w:t outside any w:p?
outside = 0
for t in doc.iter(W + 't'):
    n = t
    while n is not None and n.tag != W + 'p':
        n = parent.get(n)
    if n is None:
        outside += 1
print('w:t elements not inside any w:p:', outside)

# 3. table text coverage: every table's cell text union equals table XML w:t
mismatch = 0
for loc, tbl in xml_tables.items():
    xml_txt = ''.join((t.text or '') for t in tbl.iter(W + 't')).split()
    b = proj_tables[loc]
    cells_txt = []
    def leaf_text(block):
        if block.kind == 'paragraph':
            return [block.text]
        out = []
        for row in block.rows:
            for c in row:
                for cb in c.blocks:
                    out.extend(leaf_text(cb))
        return out
    cells_txt = leaf_text(b)
    if ''.join(''.join(cells_txt).split()) != ''.join(xml_txt):
        mismatch += 1
        print('TABLE TEXT MISMATCH', loc)
print('tables with text mismatch:', mismatch, 'of', len(xml_tables))
