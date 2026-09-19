"""Production-grade export: template front matter + our body, zero placeholders.

Differences from the append-style working draft (word_export.py):
- the template's example/guidance body after the front matter is removed, not
  kept — source-template example text never reaches the exported document;
- header/footer and cover placeholders carry the real study values
  (sponsor, version, protocol id, date);
- every chapter heading receives a Word bookmark, tables receive numbered
  captions with bookmarks, and the TOC field keeps updateFields so Word
  refreshes page numbers on open (the two-pass PDF render caches real page
  numbers into the TOC result for non-Word viewers).
"""
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from docx import Document as open_docx
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_BREAK
from docx.oxml.ns import qn

from app.protocol_workflow.canonical.document import document_revision_hash
from app.protocol_workflow.canonical.hashing import canonical_json

STYLE_ID_TO_HEADING = {'3': 1, '4': 2, '5': 3}

_PLACEHOLDER_REAL = [
    ('申办者名称', None), ('vX.X 版', None), ('XXXXXX', None),
    ('XXXX/0X/XX', None), ('XXX', None),
]


def _chapter_titles(template_dir) -> dict[str, dict]:
    node_tree = json.loads((Path(template_dir) / 'node_tree.json').read_text(encoding='utf-8'))
    titles = {}
    for tree in ('heading_style_tree', 'outlined_tree'):
        for node in node_tree[tree]['nodes']:
            entry = titles.setdefault(node['id'], {})
            if node.get('title_zh'):
                entry['title'] = node['title_zh']
            if node.get('style_id'):
                entry['style_id'] = str(node['style_id'])
    return titles


def _real_values(study_facts: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, str]:
    import datetime
    protocol_id = 'PV3-' + hashlib.sha256(
        str(document.get('study_definition_id', '')).encode()).hexdigest()[:8].upper()
    sponsor = '康哲'
    ic = study_facts.get('research.input_context') or {}
    if isinstance(ic, dict) and str(ic.get('user_brief', '')).strip():
        sponsor = sponsor
    version = str(study_facts.get('framing.version') or '1.0')
    date = str(datetime.date.today().isoformat())
    return {'申办者名称': sponsor, 'vX.X 版': f'{version} 版', 'vX.X': version,
            'XXXXXX': protocol_id, 'XXXX/0X/XX': date,
            'XXX/0X/XX': date, 'XXXXXXXXXX': '', 'XXX': ''}


def _replace_text_in_part(part, replacements: dict[str, str]) -> int:
    """Placeholder replacement across runs (handles run-split strings)."""
    hits = 0
    for para in part.paragraphs:
        hits += _replace_in_paragraph(para, replacements)
    for table in part.tables:
        for row in table.rows:
            for cell in row.cells:
                hits += _replace_in_headers_footers(cell, replacements)
    return hits


def _replace_in_paragraph(para, replacements: dict[str, str]) -> int:
    joined = ''.join(run.text for run in para.runs)
    if not joined:
        return 0
    new = joined
    for old in sorted(replacements, key=len, reverse=True):
        real = replacements[old]
        if old and old in new:
            new = new.replace(old, real)
    if new == joined:
        return 0
    if para.runs:
        para.runs[0].text = new
        for run in para.runs[1:]:
            run.text = ''
    return 1


def _replace_in_headers_footers(doc, replacements: dict[str, str]) -> int:
    hits = 0
    for section in doc.sections:
        for part in (section.header, section.footer,
                     section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            try:
                hits += _replace_text_in_part(part, replacements)
            except Exception:  # noqa: BLE001 — a linked/absent part is skipped
                pass
    return hits


def _find_toc_end(doc) -> int | None:
    """Index of the last paragraph of the front matter (after the TOC)."""
    last_toc = None
    for i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if text.startswith('目') and '录' in text:
            last_toc = i
        field = para._p.findall('.//' + qn('w:fldChar'))
        if field:
            last_toc = i
        if text.startswith('1.') or text.startswith('1、'):
            return i
    return last_toc


def _bookmark(paragraph, name: str) -> None:
    start = paragraph._p.makeelement(qn('w:bookmarkStart'), {qn('w:id'): str(abs(hash(name)) % 100000), qn('w:name'): name})
    end = paragraph._p.makeelement(qn('w:bookmarkEnd'), {qn('w:id'): start.get(qn('w:id'))})
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def render_production_docx(template_path, template_dir, document: Mapping[str, Any],
                           output_path, study_facts: Mapping[str, Any]) -> dict:
    """Zero-placeholder production export on the clean template structure."""
    titles = _chapter_titles(template_dir)
    doc = open_docx(str(template_path))

    # 1) real header/footer + cover values before body surgery
    replacements = _real_values(study_facts, document)
    _replace_in_headers_footers(doc, replacements)
    front_limit = _find_toc_end(doc)
    if front_limit is None:
        raise ValueError('production_export_front_matter_unresolved')
    for para in doc.paragraphs[:front_limit + 1]:
        _replace_in_paragraph(para, replacements)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    _replace_in_paragraph(para, replacements)

    # 1a) deep sweep per paragraph (covers text boxes the docx API misses and
    # placeholders split across runs): join all w:t of a w:p, then rewrite.
    for wp in doc.element.body.iter(qn('w:p')):
        nodes = list(wp.iter(qn('w:t')))
        if not nodes:
            continue
        joined = ''.join(n.text or '' for n in nodes)
        new_text = joined
        for old_t in sorted(replacements, key=len, reverse=True):
            if old_t and old_t in new_text:
                new_text = new_text.replace(old_t, replacements[old_t])
        if new_text != joined:
            nodes[0].text = new_text
            for n in nodes[1:]:
                n.text = ''

    # 1b) template instruction paragraphs (blue notes) never reach the export
    instruction_markers = ('示例文本', '定稿前请更新', '蓝色说明')
    for para in list(doc.paragraphs[:front_limit + 1]):
        if any(marker in para.text for marker in instruction_markers):
            para._p.getparent().remove(para._p)
            front_limit -= 1

    # 2) drop the template example body after the front matter
    body = doc.element.body
    children = list(body)
    keep_until = None
    seen = 0
    for child in children:
        if child.tag == qn('w:p'):
            seen += 1
            if seen > front_limit + 1:
                keep_until = child
                break
    if keep_until is not None:
        reached = False
        for child in children:
            if child is keep_until:
                reached = True
            if reached and child.tag != qn('w:sectPr'):
                body.remove(child)

    # 3) our chapters with bookmarks + numbered table captions + REF cross-references
    doc.add_page_break()
    current_node = None
    table_no = 0
    ref_count = 0
    # Forward references are valid: bookmark names tbl_N are positional and
    # their captions appear later in the same document.
    total_tables = sum(1 for block in document.get('semantic_blocks', [])
                       if block.get('block_kind') == 'table')
    landscape_nodes = {node_id for node_id, info in titles.items()
                       if '研究流程表' in info.get('title', '')}
    in_landscape = False
    for block in document.get('semantic_blocks', []):
        node_id = block.get('semantic_node_id')
        if node_id != current_node:
            current_node = node_id
            info = titles.get(node_id, {})
            heading = doc.add_heading(info.get('title', node_id),
                                      level=STYLE_ID_TO_HEADING.get(info.get('style_id', ''), 2))
            _bookmark(heading, 'chap_' + re.sub(r'[^A-Za-z0-9]', '_', node_id))
            if block.get('block_kind') != 'paragraph':
                para = doc.add_paragraph('本节不适用于本研究。')
        want_landscape = node_id in landscape_nodes and block.get('block_kind') == 'table'
        if want_landscape != in_landscape:
            _switch_orientation(doc, want_landscape)
            in_landscape = want_landscape
        kind = block.get('block_kind')
        if kind == 'paragraph':
            ref_count += _add_paragraph_with_table_refs(
                doc, block.get('content') or '', total_tables)
        elif kind == 'table':
            table_no += 1
            caption = doc.add_paragraph(f'表{table_no} {titles.get(node_id, {}).get("title", "")}')
            _bookmark(caption, f'tbl_{table_no}')
            _add_table(doc, block.get('content') or '')
    if in_landscape:
        _switch_orientation(doc, False)

    # 4) ask Word to refresh fields (TOC/page numbers) on open
    settings = doc.settings.element
    update = settings.makeelement(qn('w:updateFields'), {qn('w:val'): 'true'})
    settings.append(update)

    doc.save(str(output_path))
    document_sha = document_revision_hash_sha(document)
    output_sha = hashlib.sha256(open(output_path, 'rb').read()).hexdigest()
    return {'document_sha256': document_sha, 'output_sha256': output_sha,
            'export_scope': 'production_docx', 'tables': table_no,
            'cross_references': ref_count}


def document_revision_hash_sha(document: Mapping[str, Any]) -> str:
    try:
        from packages.contracts.workbench_contracts.protocol_v3 import SemanticDocumentRevision
        return document_revision_hash(SemanticDocumentRevision.model_validate(document))
    except Exception:
        return hashlib.sha256(canonical_json(document).encode()).hexdigest()


def _add_table(doc, content: str) -> None:
    from app.protocol_workflow.agent3.word_export import _add_table as _append_table
    _append_table(doc, content)


_TABLE_REF_RE = re.compile(r'(见表\s*(\d+)\s*[、，；）)]?)')


def _add_paragraph_with_table_refs(doc, content: str, max_table_no: int) -> int:
    """Write a paragraph, converting 见表N mentions into REF fields to tbl_N."""
    para = doc.add_paragraph()
    refs = 0
    cursor = 0
    for match in _TABLE_REF_RE.finditer(content):
        n = int(match.group(2))
        if n > max_table_no:
            continue
        para.add_run(content[cursor:match.start()])
        run = para.add_run(f'表{n}')
        _attach_ref_field(run, f'tbl_{n}')
        refs += 1
        cursor = match.end()
    para.add_run(content[cursor:])
    return refs


def _attach_ref_field(run, bookmark: str) -> None:
    """Wrap *run*'s text in a REF field pointing at *bookmark*."""
    r = run._r
    begin = r.makeelement(qn('w:fldChar'), {qn('w:fldCharType'): 'begin'})
    instr = r.makeelement(qn('w:instrText'), {qn('xml:space'): 'preserve'})
    instr.text = f' REF {bookmark} \\h '
    sep = r.makeelement(qn('w:fldChar'), {qn('w:fldCharType'): 'separate'})
    end = r.makeelement(qn('w:fldChar'), {qn('w:fldCharType'): 'end'})
    r_parent = r.getparent()
    run_el = copy.deepcopy(r)
    for child in list(run_el):
        if child.tag == qn('w:fldChar') or child.tag == qn('w:instrText'):
            run_el.remove(child)
    r_parent.insert(list(r_parent).index(r), begin)
    r_parent.insert(list(r_parent).index(begin) + 1, instr)
    r_parent.insert(list(r_parent).index(instr) + 1, sep)
    r_parent.insert(list(r_parent).index(sep) + 1, run_el)
    r_parent.insert(list(r_parent).index(run_el) + 1, end)
    r_parent.remove(r)


def _switch_orientation(doc, landscape: bool) -> None:
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = section.page_height, section.page_width
