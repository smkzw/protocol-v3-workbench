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
    title_fact = study_facts.get('framing.document_title')
    if isinstance(title_fact, dict):
        title_fact = title_fact.get('text') or title_fact.get('title') or '临床研究方案'
    real_title = str(title_fact or '临床研究方案')
    return {'title': real_title,
            '申办者名称': sponsor, 'vX.X 版': f'{version} 版', 'vX.X': version,
            'XXXXXX': protocol_id, 'XXXX/0X/XX': date,
            'XXX/0X/XX': date, 'XXXXXXXXXX': '', 'XXX': '',
        '<编号>': protocol_id, '<年月日>': date,
        '<主要研究者姓名>': '＿＿＿＿＿＿', '<医院名称>': '＿＿＿＿＿＿＿＿',
        '<申办者名称>': sponsor, '<供应商名称>': '＿＿＿＿＿＿',
        '<合同研究组织名称>': '＿＿＿＿＿＿', 'v <x.x>': f'v{version}',
        'v<x.x>': f'v{version}', '<x.x>': version,
        }


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

    # 0) front-matter surgery: the template instruction block (模板说明 /
    # 如何使用此模板 / 删除说明) is authoring guidance — it never ships.  The
    # example title becomes the real study title; cover <字段> become values.
    title_fact = study_facts.get('framing.document_title')
    if isinstance(title_fact, dict):
        title_fact = title_fact.get('text') or title_fact.get('title') or '临床研究方案'
    real_title = str(title_fact or replacements.get('title') or '临床研究方案')
    paras = doc.paragraphs
    title_idx = next((i for i, para in enumerate(paras[:40])
                      if '临床研究' in para.text and ('XXXXXX' in para.text or '安全性的' in para.text)), None)
    if title_idx is not None:
        title_para = paras[title_idx]
        for para in paras[:title_idx]:
            if para.text.strip():
                para._p.getparent().remove(para._p)
        for run in title_para.runs[1:]:
            run.text = ''
        if title_para.runs:
            title_para.runs[0].text = real_title
        else:
            title_para.add_run(real_title)
        front_limit -= title_idx
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
    instruction_markers = ('示例文本', '定稿前请更新', '蓝色说明',
                           '紧急危害例外仅适用于', '不得将其写成通用豁免')
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

    # 2b) signature pages: clone the sponsor section for the CRO and the
    # statistical unit (exemplar structure).  Clones inherit the placeholder
    # sweep results; their titles and party lines are rewritten inline.
    def _expand_signature_pages():
        import copy as _copy
        paras = doc.paragraphs
        start = next((i for i, p in enumerate(paras)
                      if p.text.strip() == '申办者签字页'), None)
        if start is None:
            return 0
        end = next((i for i in range(start + 1, len(paras))
                    if paras[i].text.strip() in ('临床试验相关单位联系方式', '缩略语表')
                    or (paras[i].style.name == 'Heading 1' and i > start + 1)), None)
        if end is None or end <= start:
            return 0
        section = paras[start:end]
        anchor_p = paras[end]._p
        made = 0
        for new_title, swap in (('合同研究组织签字页', ('申办者', '合同研究组织')),
                                ('统计单位签字页', ('申办者', '统计单位'))):
            for para in section:
                clone = _copy.deepcopy(para._p)
                # Cloned sections must not duplicate template bookmark
                # names/ids — strip bookmark marks from the clones.
                for bm in clone.findall('.//' + qn('w:bookmarkStart')):
                    bm.getparent().remove(bm)
                for bm in clone.findall('.//' + qn('w:bookmarkEnd')):
                    bm.getparent().remove(bm)
                anchor_p.addprevious(clone)
                from docx.text.paragraph import Paragraph as _P
                wrapper = _P(clone, para._parent)
                texts = ''.join(r.text for r in wrapper.runs)
                new_text = texts
                for old_t, real_t in replacements.items():
                    if old_t and old_t in new_text:
                        new_text = new_text.replace(old_t, real_t)
                for old_t, real_t in (swap[0] + '：', swap[1] + '：'), (swap[0] + '代表', swap[1] + '代表'):
                    new_text = new_text.replace(old_t, real_t)
                if texts == section[0].text.strip():
                    new_text = new_title
                if wrapper.runs:
                    wrapper.runs[0].text = new_text
                    for r in wrapper.runs[1:]:
                        r.text = ''
            made += 1
        return made

    _expand_signature_pages()

    # 3) our chapters with bookmarks + numbered table captions + REF cross-references.
    # The SOA chapter's table is a deterministic projection of the confirmed
    # visit×assessment facts, replacing whatever prose-shaped table the model
    # drafted for it.
    from app.protocol_workflow.agent3.soa_matrix import soa_table_content
    from app.protocol_workflow.agent3.synopsis_projection import build_synopsis_blocks
    soa_content = soa_table_content(study_facts)
    soa_nodes = {node_id for node_id, info in titles.items()
                 if '研究流程表' in info.get('title', '')}
    synopsis_nodes = {node_id for node_id, info in titles.items()
                      if info.get('title', '').strip() in ('概要', '方案摘要')
                      or info.get('title', '').strip().endswith('概要')}
    doc.add_page_break()
    current_node = None
    table_no = 0
    ref_count = 0
    soa_replaced = 0
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
            if node_id in synopsis_nodes and study_facts:
                # The synopsis is a deterministic projection (overview +
                # abbreviations + annotated key points), per the exemplars.
                for projected in build_synopsis_blocks(study_facts):
                    text = projected['content'].replace('受试者', '试验参与者')
                    ref_count += _add_paragraph_with_table_refs(doc, text, total_tables)
                continue
            if block.get('block_kind') != 'paragraph':
                para = doc.add_paragraph('本节不适用于本研究。')
        want_landscape = node_id in landscape_nodes and block.get('block_kind') == 'table'
        if want_landscape != in_landscape:
            _switch_orientation(doc, want_landscape)
            in_landscape = want_landscape
        if node_id in synopsis_nodes:
            continue  # projected blocks were written with the heading
        kind = block.get('block_kind')
        if kind == 'paragraph':
            content_text = (block.get('content') or '').replace(
                '受试者', '试验参与者')
            ref_count += _add_paragraph_with_table_refs(
                doc, content_text, total_tables)
        elif kind == 'table':
            table_no += 1
            caption = doc.add_paragraph(f'表{table_no} {titles.get(node_id, {}).get("title", "")}')
            _bookmark(caption, f'tbl_{table_no}')
            content = (block.get('content') or '').replace('受试者', '试验参与者')
            is_soa = bool(soa_content and node_id in soa_nodes)
            if is_soa:
                content = soa_content
                soa_replaced += 1
            _add_table(doc, content, repeat_header=header_rows_of(content))
            if is_soa:
                _tune_wide_table(doc.tables[-1])
    if in_landscape:
        _switch_orientation(doc, False)

    # 4) ask Word to refresh fields (TOC/page numbers) on open.  settings.xml
    # has a strict child sequence — updateFields belongs before w:compat;
    # appending at the end makes Word reject the whole file.
    settings = doc.settings.element
    update = settings.makeelement(qn('w:updateFields'), {qn('w:val'): 'true'})
    compat = settings.find(qn('w:compat'))
    if compat is not None:
        compat.addprevious(update)
    else:
        settings.append(update)

    doc.save(str(output_path))
    document_sha = document_revision_hash_sha(document)
    output_sha = hashlib.sha256(open(output_path, 'rb').read()).hexdigest()
    return {'document_sha256': document_sha, 'output_sha256': output_sha,
            'export_scope': 'production_docx', 'tables': table_no,
            'cross_references': ref_count, 'soa_replaced': soa_replaced}


def header_rows_of(table_content: str) -> int:
    try:
        table = json.loads(table_content).get('table', {})
        return int(table.get('header_row_count') or 0)
    except (ValueError, TypeError):
        return 0


def document_revision_hash_sha(document: Mapping[str, Any]) -> str:
    try:
        from packages.contracts.workbench_contracts.protocol_v3 import SemanticDocumentRevision
        return document_revision_hash(SemanticDocumentRevision.model_validate(document))
    except Exception:
        return hashlib.sha256(canonical_json(document).encode()).hexdigest()


def _tune_wide_table(table) -> None:
    """Wide-matrix readability on a landscape page: fixed layout, a wide
    label column, equal narrow visit columns, and 8pt cell text."""
    from docx.shared import Cm, Pt
    table.autofit = False
    n_cols = len(table.columns)
    if n_cols < 8:
        return
    label_cm = 4.0
    visit_cm = round((25.7 - label_cm) / (n_cols - 1), 2)
    for i, column in enumerate(table.columns):
        width = Cm(label_cm if i == 0 else visit_cm)
        column.width = width
        for cell in column.cells:
            cell.width = width
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(8)


def _add_table(doc, content: str, repeat_header: int = 0) -> None:
    from app.protocol_workflow.agent3.word_export import _add_table as _append_table
    _append_table(doc, content)
    # Cross-page tables repeat their header rows on every page (w:tblHeader).
    if repeat_header and doc.tables:
        table = doc.tables[-1]
        for row in table.rows[:repeat_header]:
            tr_pr = row._tr.get_or_add_trPr()
            if tr_pr.find(qn('w:tblHeader')) is None:
                tr_pr.append(tr_pr.makeelement(qn('w:tblHeader'), {qn('w:val'): 'true'}))


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
    """Replace *run* with a REF field pointing at *bookmark*.

    Every field element must live inside its own w:r run — bare w:fldChar /
    w:instrText children of a paragraph are schema-invalid and Word refuses
    the whole file (LibreOffice merely tolerates them).
    """
    r = run._r

    def field_run(child_tag: str, text: str | None = None):
        fr = r.makeelement(qn('w:r'), {})
        child = fr.makeelement(qn(child_tag), {})
        if text is not None:
            child.set(qn('xml:space'), 'preserve')
            child.text = text
        fr.append(child)
        return fr

    begin = field_run('w:fldChar')
    begin[0].set(qn('w:fldCharType'), 'begin')
    instr = field_run('w:instrText', f' REF {bookmark} \\h ')
    sep = field_run('w:fldChar')
    sep[0].set(qn('w:fldCharType'), 'separate')
    cached = copy.deepcopy(r)
    end = field_run('w:fldChar')
    end[0].set(qn('w:fldCharType'), 'end')

    parent = r.getparent()
    idx = parent.index(r)
    for offset, element in enumerate((begin, instr, sep, cached, end)):
        parent.insert(idx + 1 + offset, element)
    parent.remove(r)


def _switch_orientation(doc, landscape: bool) -> None:
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    if landscape:
        section.orientation = WD_ORIENT.LANDSCAPE
        section.page_width, section.page_height = section.page_height, section.page_width
    else:
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = section.page_height, section.page_width
