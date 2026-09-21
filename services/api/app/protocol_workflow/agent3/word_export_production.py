"""Production-grade export: template front matter + the current version's body.

The export owns layout only — it serializes the saved working version
verbatim (R4/A13/A14): no synopsis re-projection, no SOA replacement, no
silent term replacement, no marker-hit paragraph deletion, and no
"不适用" written from block shape (B01).

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
from docx.enum.text import WD_BREAK, WD_TAB_ALIGNMENT
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
    """Document-control values, sourced only from confirmed facts / the saved
    document (audit G4/F10).  A value the study never confirmed stays as an
    explicit blank — a company template style does not authorize inventing
    sponsor names, protocol numbers, or dates at download time."""
    # 已确认值优先；未确认的文控信息保持空（显式缺口，不冒充已知）。
    protocol_id = str(study_facts.get('framing.protocol_id') or '').strip()
    if not protocol_id:
        protocol_id = ''  # 未确认：不匿名造号
    sponsor = str(study_facts.get('framing.sponsor') or '').strip()
    version = str(study_facts.get('framing.version') or '').strip() or '1.0'
    date = str(study_facts.get('framing.protocol_date')
               or study_facts.get('document_control.version_date') or '').strip()
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
                hits += _replace_text_in_part(cell, replacements)
    return hits


def _replace_in_paragraph(para, replacements: dict[str, str]) -> int:
    return _replace_paragraph_xml(para._p, replacements)


def _replace_paragraph_xml(wp, replacements: dict[str, str]) -> int:
    """Replace text spans without flattening runs, tabs, breaks or textboxes."""
    nodes = [n for n in wp.iter(qn('w:t'))
             if next(n.iterancestors(qn('w:p')), None) is wp]
    changed = False
    for old in sorted(replacements, key=len, reverse=True):
        if not old:
            continue
        text = ''.join(n.text or '' for n in nodes)
        offsets = []
        pos = 0
        for node in nodes:
            end = pos + len(node.text or '')
            offsets.append((node, pos, end))
            pos = end
        for match in reversed(list(re.finditer(re.escape(old), text))):
            spans = [(n, a, b) for n, a, b in offsets
                     if a < match.end() and b > match.start()]
            for i, (node, start, end) in enumerate(spans):
                value = node.text or ''
                left = max(0, match.start() - start)
                right = min(end - start, match.end() - start)
                node.text = value[:left] + (replacements[old] if i == 0 else '') + value[right:]
                node.set(qn('xml:space'), 'preserve')
            changed = changed or bool(spans)
    return int(changed)


def _replace_in_headers_footers(doc, replacements: dict[str, str]) -> int:
    hits = 0
    for section in doc.sections:
        for part in (section.header, section.footer,
                     section.first_page_header, section.first_page_footer,
                     section.even_page_header, section.even_page_footer):
            if part.is_linked_to_previous:
                continue
            try:
                hits += _replace_text_in_part(part, replacements)
            except Exception:  # noqa: BLE001 — a linked/absent part is skipped
                pass
    return hits


def _layout_template_headers(doc) -> None:
    """Use the printable width instead of template space padding."""
    seen = set()
    for section in doc.sections:
        width = section.page_width - section.left_margin - section.right_margin
        for part in (section.header, section.first_page_header, section.even_page_header):
            if part.is_linked_to_previous:
                continue
            if part.part.partname in seen:
                continue
            seen.add(part.part.partname)
            for para in part.paragraphs:
                if not ('版本号：' in para.text or '版本日期：' in para.text):
                    continue
                padding = re.findall(r' {10,}', para.text)
                if not padding:
                    continue
                # Retain existing run styles; replace only space padding with
                # native Word tabs, which track the section's usable width.
                _replace_in_paragraph(para, {spaces: '\t' for spaces in padding})
                for node in list(para._p.iter(qn('w:t'))):
                    if '\t' not in (node.text or ''):
                        continue
                    chunks = node.text.split('\t')
                    node.text = chunks[0]
                    previous = node
                    for chunk in chunks[1:]:
                        tab = node.makeelement(qn('w:tab'))
                        previous.addnext(tab)
                        text = node.makeelement(qn('w:t'), {qn('xml:space'): 'preserve'})
                        text.text = chunk
                        tab.addnext(text)
                        previous = text
                tabs = para.paragraph_format.tab_stops
                tabs.clear_all()
                style = para.style
                cleared = set()
                while style is not None:
                    for inherited in style.paragraph_format.tab_stops:
                        if inherited.position not in cleared:
                            tabs.add_tab_stop(inherited.position, WD_TAB_ALIGNMENT.CLEAR)
                            cleared.add(inherited.position)
                    style = style.base_style
                if len(padding) > 1:
                    tabs.add_tab_stop(int(width / 2), WD_TAB_ALIGNMENT.CENTER)
                tabs.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)


def _find_toc_end(doc) -> int | None:
    """Keep front matter through its TOC heading, never its template cache.

    A cached TOC entry such as ``1. 方案摘要`` is not a body boundary. Cutting
    there leaves the outer TOC field open and retains someone else's pages.
    The current manuscript receives a fresh, balanced field below.
    """
    for i, para in enumerate(doc.paragraphs):
        if re.sub(r'\s+', '', para.text) == '目录':
            return i
    return None


def _bookmark(paragraph, name: str) -> None:
    start = paragraph._p.makeelement(qn('w:bookmarkStart'), {qn('w:id'): str(abs(hash(name)) % 100000), qn('w:name'): name})
    end = paragraph._p.makeelement(qn('w:bookmarkEnd'), {qn('w:id'): start.get(qn('w:id'))})
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


_GAP_PATH_RE = re.compile(r'【缺口：\s*[A-Za-z][A-Za-z0-9_.]*\s*：')
# 会商2补充：gap 块正文中还有「（缺口身份：v2_*）」的节点锚标注，同样
# 属于内部身份，不进交付稿（语义稿内原样保留供校验）。
_GAP_IDENTITY_RE = re.compile(r'（缺口身份：\s*[^）]*）')


def _redact_gap_paths(content: str) -> str:
    """缺口标注里的人类可读部分保留，内部 fact_path/节点锚不进交付稿。"""
    text = _GAP_PATH_RE.sub('【待补充：', content or '')
    return _GAP_IDENTITY_RE.sub('', text)


def render_production_docx(template_path, template_dir, document: Mapping[str, Any],
                           output_path, study_facts: Mapping[str, Any]) -> dict:
    """Zero-placeholder production export on the clean template structure."""
    titles = _chapter_titles(template_dir)
    doc = open_docx(str(template_path))

    # 1) real header/footer + cover values before body surgery
    replacements = _real_values(study_facts, document)
    _replace_in_headers_footers(doc, replacements)
    _layout_template_headers(doc)
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
        # Remove the instruction page as a whole, including its page break.
        # Preserve the cover's spacing after that break. Removing only text
        # left an empty first page and miscounted the front-matter boundary.
        instruction_end = max((i + 1 for i, para in enumerate(paras[:title_idx])
            if any(br.get(qn('w:type')) == 'page'
                   for br in para._p.findall('.//' + qn('w:br')))), default=title_idx)
        for para in paras[:instruction_end]:
            para._p.getparent().remove(para._p)
        for run in title_para.runs[1:]:
            run.text = ''
        if title_para.runs:
            title_para.runs[0].text = real_title
        else:
            title_para.add_run(real_title)
        front_limit -= instruction_end
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
        # Text boxes contain their own paragraphs, often in both DrawingML
        # Choice and VML Fallback branches. Process each paragraph separately;
        # joining descendants of the outer anchor duplicates the alternatives.
        _replace_paragraph_xml(wp, replacements)

    # 1b) template instruction paragraphs (blue notes) never reach the export
    instruction_markers = ('示例文本', '定稿前请更新', '蓝色说明',
                           '紧急危害例外仅适用于', '不得将其写成通用豁免')
    template_instruction_texts = {
        '所有版本都应当具有版本号和日期。',
        '保密声明。示例如下：',
        '以下表格旨在体现历次EC/IRB批准的方案版本变更情况，包括修订内容描述及依据。当前修订案的变更汇总表应位于方案标题页。 如不需要，可删除本页',
        '[以下签字页如有需要可进行添加，以下签字页为示例]',
        '如适用，示例#1',
        '下表包含了本模板中出现的缩略语，该列表应根据实际方案制定（如从本表中删除未涉及的缩略语，增添新缩略语）。',
    }
    for para in list(doc.paragraphs[:front_limit + 1]):
        if (para.text.strip() in template_instruction_texts
                or any(marker in para.text for marker in instruction_markers)):
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

    added_signature_pages = _expand_signature_pages()

    # Cache only current heading text; pagination is deliberately left to the
    # renderer/Word field update, never copied from the source template.
    toc_titles = [p.text for p in doc.paragraphs if p.text.strip()
        and p.style.name.startswith('Heading')
        and re.sub(r'\s+', '', p.text) != '目录']
    toc = doc.add_paragraph()
    for kind in ('begin', 'instruction', 'separate'):
        run = toc.add_run()
        if kind == 'instruction':
            field = run._r.makeelement(qn('w:instrText'))
            field.set(qn('xml:space'), 'preserve')
            field.text = ' TOC \\o "1-3" \\h \\z \\u '
        else:
            field = run._r.makeelement(qn('w:fldChar'), {qn('w:fldCharType'): kind})
            if kind == 'begin':
                field.set(qn('w:dirty'), 'true')
        run._r.append(field)

    # 3) our chapters with bookmarks + numbered table captions + REF
    # cross-references, serialized exactly as saved (R4/A13/A14).
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
            title_text = str(info.get('title') or '').strip()
            # 内部锚点（v2_n_* / v2_front_block）不是人类标题（T17 P1-3）：
            # 模板标题表未登记的节点不产出 heading（正文并入前一章），
            # 但块内容本身照常导出。
            if title_text:
                toc_titles.append(title_text)
                heading = doc.add_heading(title_text,
                                          level=STYLE_ID_TO_HEADING.get(info.get('style_id', ''), 2))
                _bookmark(heading, 'chap_' + re.sub(r'[^A-Za-z0-9]', '_', node_id))
            # R4: no re-projection here.  The synopsis chapter ships the
            # user's current blocks verbatim; re-projecting from facts or
            # writing "不适用" from block shape (B01) are export bugs.
        want_landscape = node_id in landscape_nodes and block.get('block_kind') == 'table'
        if want_landscape != in_landscape:
            _switch_orientation(doc, want_landscape)
            in_landscape = want_landscape
        kind = block.get('block_kind')
        if kind == 'paragraph':
            ref_count += _add_paragraph_with_table_refs(
                doc, _redact_gap_paths(block.get('content') or ''), total_tables)
        elif kind == 'table':
            table_no += 1
            caption = doc.add_paragraph(f'表{table_no} {titles.get(node_id, {}).get("title", "")}')
            _bookmark(caption, f'tbl_{table_no}')
            content = block.get('content') or ''
            _add_table(doc, content, repeat_header=header_rows_of(content))
            # Layout-only readability for wide matrices, regardless of origin.
            if len(doc.tables[-1].columns) >= 8:
                _tune_wide_table(doc.tables[-1])
    if in_landscape:
        _switch_orientation(doc, False)

    for i, title_text in enumerate(toc_titles):
        if i:
            toc.add_run().add_break()
        toc.add_run(title_text)
    end_run = toc.add_run()
    end_run._r.append(end_run._r.makeelement(qn('w:fldChar'),
        {qn('w:fldCharType'): 'end'}))

    # 3b) engineering/process language is REPORTED, never deleted here
    # (R-C04): cleaning is a visible candidate applied to a document version,
    # not a silent export behavior.
    engineering_markers = (
        'evidence_unit_id', '可追溯证据状态', '本候选未接收',
        '容器义务边界', '本容器仅承担', '不构成附件适用性',
        '不构成对医学、伦理、法律或审批事项的判断',
        '不建立章内第二可编辑存储', '不构成对该等措辞的核验',
        '进入待补/建议解决路径', '亦未收到可引用的',
        '可追溯证据待后续内容核对补充',
        '正式内容核对前需补充项目主要来源证据',
        '不将其判定为不适用，也不以模板示例',
        'provenance_lineage 与脚注', '由 StudyDefinition 统一承载',
        '相关来源绑定和原文定位需在后续内容核对中补充',
        '不构成对医学、伦理、法律或审批事项的判断；待补事实',
        '不构成对该等措辞的核验。本章涉及的数据管理与伦理相关新事实根归属',
        '本候选不建立章内第二可编辑存储',
        '本候选不作合规断言',
        '本研究暂无正式来源文件',
        '参考文献列表为空',
        '实际使用来源登记为空',
    )
    marker_hits = []
    for para in doc.paragraphs:
        hit = next((marker for marker in engineering_markers if marker in para.text), None)
        if hit:
            marker_hits.append(hit)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    hit = next((marker for marker in engineering_markers if marker in para.text), None)
                    if hit:
                        marker_hits.append(hit)

    # 4) ask Word to refresh fields (TOC/page numbers) on open.  settings.xml
    # has a strict child sequence — updateFields belongs before w:compat;
    # appending at the end makes Word reject the whole file.
    settings = doc.settings.element
    # A fresh generated draft must not inherit the template author's review
    # mode. This does not touch any already-saved Office snapshot or revisions.
    tracking = settings.find(qn('w:trackRevisions'))
    if tracking is not None:
        settings.remove(tracking)
    updates = settings.findall(qn('w:updateFields'))
    if updates:
        updates[0].set(qn('w:val'), 'true')
        for duplicate in updates[1:]:
            settings.remove(duplicate)
    else:
        update = settings.makeelement(qn('w:updateFields'), {qn('w:val'): 'true'})
        compat = settings.find(qn('w:compat'))
        if compat is not None:
            compat.addprevious(update)
        else:
            settings.append(update)

    pruned_media = _prune_orphaned_media(doc)
    doc.save(str(output_path))
    document_sha = document_revision_hash_sha(document)
    output_sha = hashlib.sha256(open(output_path, 'rb').read()).hexdigest()
    return {'document_sha256': document_sha, 'output_sha256': output_sha,
            'export_scope': 'production_docx', 'tables': table_no,
            'cross_references': ref_count,
            'engineering_marker_hits': marker_hits,
            'template_diagnostics': {
                'cover_anchor_found': title_idx is not None,
                'added_signature_pages': added_signature_pages,
                'retained_instruction_candidates': [p.text for p in doc.paragraphs[:front_limit + 1]
                    if any(marker in p.text for marker in ('示例', '如有需要', '本模板', '请更新'))],
            },
            'orphaned_media_pruned': pruned_media,
            'field_diagnostics': {'cross_reference_fields': ref_count,
                'update_fields_on_open': True,
                'toc_cache': 'current_headings_without_unverified_page_numbers',
                'third_party_citation_interop': 'not_claimed'}}



def _prune_orphaned_media(doc) -> list[str]:
    """Drop image parts the rewritten body no longer references (T07 spike).

    The clean template ships a flow-diagram image referenced only by its own
    example body; once that body is replaced the media part and relationship
    would ship as dead weight.  Header/footer/styles rels are referenced from
    sectPr r:id attributes, which the scan below collects too, so they stay.
    """
    rns = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    referenced = set()
    for element in doc.element.body.iter():
        for attr in (f'{{{rns}}}embed', f'{{{rns}}}id', f'{{{rns}}}link',
                     f'{{{rns}}}pict', f'{{{rns}}}dm', f'{{{rns}}}lo',
                     f'{{{rns}}}qs', f'{{{rns}}}cs'):
            value = element.get(attr)
            if value:
                referenced.add(value)
    pruned = []
    for r_id in list(doc.part.rels):
        rel = doc.part.rels[r_id]
        if rel.reltype.endswith('/image') and not rel.is_external and r_id not in referenced:
            target = getattr(rel, 'target_ref', '')
            doc.part.drop_rel(r_id)
            pruned.append(str(target))
    return pruned


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


# F11: only the citation object (表N) becomes a REF field. The connective
# 见 and any trailing punctuation stay as plain runs — the export must not
# silently rewrite prose around the field.
_TABLE_REF_RE = re.compile(r'见(表\s*(\d+))([、，；）)]?)')


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
        para.add_run('见')
        run = para.add_run(re.sub(r'\s+', '', match.group(1)))
        _attach_ref_field(run, f'tbl_{n}')
        if match.group(3):
            para.add_run(match.group(3))
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
