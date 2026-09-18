"""Independent XML audit of the MG-K10 source DOCX vs parse_docx projection.

Read-only: opens the original archive, derives structure facts with its own
XML walk (no docx_parse helpers), then cross-checks parse_docx output.
No personal/contact content is printed; only counts, locators and short
structural snippets (<=20 chars) are reported.
"""
import hashlib
import json
import re
import sys
from collections import Counter
from xml.etree import ElementTree as ET
from zipfile import ZipFile

SRC = '/Users/smkzw/Documents/康哲项目资料/模版/方案模版/研究方案库/MG-K10-CSU-001_临床研究方案-V1.3-0212-clean-0211.docx'
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'

payload = open(SRC, 'rb').read()
sha = hashlib.sha256(payload).hexdigest()
print('payload_sha256', sha)
assert sha == '73024713c28382ca8fca7c9338d7151256b2765d78d512876731156a9a504199'

facts = {}
with ZipFile(SRC) as z:
    names = z.namelist()
    story = [n for n in names if re.fullmatch(r'word/(header\d+|footer\d+|footnotes|endnotes)\.xml', n)]
    facts['story_parts'] = sorted(story)
    doc = ET.fromstring(z.read('word/document.xml'))
    roots = {'word/document.xml': doc}
    for n in story:
        roots[n] = ET.fromstring(z.read(n))
    # --- independent structural facts per part ---
    for n, root in roots.items():
        part_f = {}
        part_f['sdt_count'] = len(root.findall('.//' + W + 'sdt'))
        galleries = [(g.get(W + 'val') or '') for g in root.findall('.//' + W + 'docPartGallery')]
        part_f['docPartGallery_values'] = sorted(set(galleries))
        instrs = [t.text or '' for t in root.iter(W + 'instrText')]
        toc_instr = [i for i in instrs if re.search(r'\bTOC\b', i)]
        part_f['instrText_count'] = len(instrs)
        part_f['toc_instrText_count'] = len(toc_instr)
        # TOC fields OUTSIDE any sdt (independent: walk with sdt-occlusion)
        def outside_sdt_toc(el, inside_sdt=False, hits=None):
            if hits is None:
                hits = []
            for child in el:
                is_sdt = child.tag == W + 'sdt'
                if not inside_sdt and not is_sdt:
                    for t in child.iter(W + 'instrText'):
                        if t.text and re.search(r'\bTOC\b', t.text):
                            hits.append(t.text[:20])
                outside_sdt_toc(child, inside_sdt or is_sdt, hits)
            return hits
        part_f['toc_instrText_outside_sdt'] = outside_sdt_toc(root)
        part_f['sdt_tags'] = sorted({(t.get(W + 'val') or '') for t in root.findall('.//' + W + 'sdtPr/' + W + 'tag')})
        part_f['tables'] = len(root.findall('.//' + W + 'tbl'))
        # nested tables: tbl with ancestor tc
        nested = 0
        for tbl in root.iter(W + 'tbl'):
            p = None
            for anc in tbl.iterancestors() if hasattr(tbl, 'iterancestors') else []:
                pass
            # ET has no iterancestors; use parent map
        parent = {c: p for p in root.iter() for c in p}
        for tbl in root.iter(W + 'tbl'):
            a = parent.get(tbl)
            while a is not None:
                if a.tag == W + 'tc':
                    nested += 1
                    break
                a = parent.get(a)
        part_f['nested_tables'] = nested
        part_f['gridSpan_cells'] = len(root.findall('.//' + W + 'tcPr/' + W + 'gridSpan'))
        part_f['vMerge_cells'] = len(root.findall('.//' + W + 'tcPr/' + W + 'vMerge'))
        part_f['vMerge_values'] = sorted({(m.get(W + 'val') or '<default=continue>') for m in root.findall('.//' + W + 'tcPr/' + W + 'vMerge')})
        part_f['tracked_ins'] = len(root.findall('.//' + W + 'ins'))
        part_f['tracked_del'] = len(root.findall('.//' + W + 'del'))
        part_f['drawings'] = len(root.findall('.//' + W + 'drawing')) + len(root.findall('.//' + W + 'pict'))
        part_f['altChunk'] = len(root.findall('.//' + W + 'altChunk'))
        part_f['endnoteRef_in_doc'] = len(root.findall('.//' + W + 'endnoteRef'))
        facts[n] = part_f
    print(json.dumps(facts, ensure_ascii=False, indent=1))

# --- run parse_docx (frozen scope module) against the same bytes ---
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/services/api')
sys.path.insert(0, '/Users/smkzw/Documents/康哲项目资料/AI/医学经理工作台/implementation/protocol-v3-workbench-mw_protocol_v3_phase0_20260809_111313/packages')
from app.protocol_workflow.agent1.docx_parse import parse_docx  # noqa: E402

result = parse_docx(payload)
print('parse content_sha256 == payload sha:', result.content_sha256 == sha)
roles = Counter(b.role for b in result.blocks)
kinds = Counter(b.kind for b in result.blocks)
print('blocks', len(result.blocks), 'roles', dict(roles), 'kinds', dict(kinds))
print('story_parts', result.story_parts)
print('diagnostics', Counter(d.code for d in result.diagnostics))
print('physical_page_count', result.physical_page_count, 'status', result.status)
print('deterministic:', result == parse_docx(payload))

# object id / locator uniqueness
ids = [b.object_id for b in result.blocks]
locs = [b.locator for b in result.blocks]
print('object_id unique:', len(set(ids)) == len(ids), 'locators unique:', len(set(locs)) == len(locs))

# bibliography blocks come from EndNote sdt?
bib = [b for b in result.blocks if b.role == 'bibliography']
print('bibliography blocks:', len(bib), 'all in sdtContent:', all('sdtContent' in b.locator for b in bib))
toc = [b for b in result.blocks if b.role == 'derived_toc']
print('derived_toc blocks:', len(toc), 'sample locators:', [b.locator for b in toc[:3]])
# header/footer/footnote/endnote roles exist as parsed
for r in ('header', 'footer', 'footnote', 'endnote'):
    print('role', r, 'blocks:', sum(1 for b in result.blocks if b.role == r))

# --- locator resolvability: independently re-walk a locator path ---
def resolve(part_root, locator):
    node = part_root
    for seg in locator.split('/'):
        if seg in ('word/document.xml', 'body') or seg.startswith('word/'):
            continue
        m = re.fullmatch(r'(\d+):(\w+)', seg)
        assert m, seg
        idx, tag = int(m.group(1)), m.group(2)
        children = [c for c in node]
        node = children[idx]
        assert node.tag.split('}')[-1] == tag, (seg, node.tag)
    return node

checks = {
    'word/document.xml': doc,
}
with ZipFile(SRC) as z:
    for n in story:
        checks[n] = ET.fromstring(z.read(n))
sample = (bib[:2] + toc[:2] + [b for b in result.blocks if b.kind == 'table'][:3]
          + [b for b in result.blocks if b.role == 'body'][:2])
resolved = 0
for b in sample:
    part = b.locator.split('/')[0]
    if part == 'word':
        part = 'word/document.xml'
    root_el = checks.get(part if part in checks else 'word/' + part)
    if root_el is None:
        print('LOCATOR-PART-MISS', b.locator)
        continue
    node = resolve(root_el, b.locator)
    tag = node.tag.split('}')[-1]
    ok_tag = tag in ('p', 'tbl')
    resolved += 1
    print('resolved', b.locator[:100], '->', tag, 'ok_tag', ok_tag)
print('resolved sample count', resolved, 'of', len(sample))

# nested tables really nested in projection?
nested_proj = 0
for b in result.blocks:
    if b.kind != 'table':
        continue
    for row in b.rows:
        for cell in row:
            nested_proj += sum(1 for cb in cell.blocks if cb.kind == 'table')
print('nested tables inside cell projections:', nested_proj)

# gridSpan/vMerge surfaced in projection
spans = [c.grid_span for b in result.blocks if b.kind == 'table' for row in b.rows for c in row]
merges = [c.vertical_merge for b in result.blocks if b.kind == 'table' for row in b.rows for c in row]
print('projected gridSpan>1 cells:', sum(1 for s in spans if s > 1), '| vMerge cells:', sum(1 for m in merges if m))
