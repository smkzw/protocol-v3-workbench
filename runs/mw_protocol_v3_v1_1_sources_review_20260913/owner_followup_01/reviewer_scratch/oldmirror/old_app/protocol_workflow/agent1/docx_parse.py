"""Ordered DOCX source projection with real XML locators, never medical admission."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from ...writing_reference_docx import (
    _has_heading_style,
    _paragraph_text,
    _read_docx_document_xml,
)


W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
PARSER_VERSION = 'protocol-docx-xml.v1'


@dataclass(frozen=True)
class DocxCell:
    locator: str
    text: str
    grid_span: int = 1
    vertical_merge: str | None = None
    blocks: tuple[DocxBlock, ...] = ()


@dataclass(frozen=True)
class DocxBlock:
    object_id: str
    locator: str
    kind: str
    role: str
    text: str
    rows: tuple[tuple[DocxCell, ...], ...] = ()


@dataclass(frozen=True)
class ParseDiagnostic:
    code: str
    locator: str
    detail: str


@dataclass(frozen=True)
class DocxParseResult:
    content_sha256: str
    blocks: tuple[DocxBlock, ...]
    diagnostics: tuple[ParseDiagnostic, ...]
    story_parts: tuple[str, ...]
    parser_version: str = PARSER_VERSION
    physical_page_count: None = None
    status: str = 'parsed_pending_source_review'


def _local(element: ET.Element) -> str:
    return element.tag.split('}')[-1]


def _control_role(element: ET.Element, inherited: str) -> str:
    tag = element.find(W + 'sdtPr/' + W + 'tag')
    if tag is not None and tag.get(W + 'val') == 'EndNote.ReferenceList':
        return 'bibliography'
    galleries = element.findall('.//' + W + 'docPartGallery')
    instructions = ' '.join(t.text or '' for t in element.iter(W + 'instrText'))
    if any((g.get(W + 'val') or '').casefold() == 'table of contents' for g in galleries) or re.search(r'\bTOC\s', instructions):
        return 'derived_toc'
    return inherited


def parse_docx(payload: bytes) -> DocxParseResult:
    """Read source text and structure without inventing page numbers or scores.

    Content controls retain their roles. Complex objects and unresolved tracked
    changes are explicit diagnostics for source review; output is not admitted
    evidence merely because parsing succeeded.
    """
    main = ET.fromstring(_read_docx_document_xml(payload))
    body = main.find(W + 'body')
    if body is None:
        raise ValueError('DOCX has no document body')
    source_hash = hashlib.sha256(payload).hexdigest()
    blocks: list[DocxBlock] = []
    diagnostics: list[ParseDiagnostic] = []

    def add(element: ET.Element, locator: str, role: str) -> DocxBlock | None:
        identity = hashlib.sha256(f'{PARSER_VERSION}|{source_hash}|{locator}'.encode()).hexdigest()
        if element.tag == W + 'p':
            text = _paragraph_text(element)
            if not text:
                return
            outline = element.find(W + 'pPr/' + W + 'outlineLvl')
            if role == 'body' and (_has_heading_style(element) or (outline is not None and outline.get(W + 'val') != '9')):
                role = 'heading'
            return DocxBlock('docx_' + identity[:24], locator, 'paragraph', role, text)
        rows = []
        for ri, row in enumerate(element):
            if row.tag != W + 'tr':
                continue
            cells = []
            for ci, cell in enumerate(row):
                if cell.tag != W + 'tc':
                    continue
                cell_locator = f'{locator}/{ri}:tr/{ci}:tc'
                span = cell.find(W + 'tcPr/' + W + 'gridSpan')
                merge = cell.find(W + 'tcPr/' + W + 'vMerge')
                child_blocks = tuple(walk(cell, cell_locator, role))
                cells.append(DocxCell(
                    cell_locator, '\n'.join(b.text for b in child_blocks),
                    int(span.get(W + 'val', '1')) if span is not None else 1,
                    (merge.get(W + 'val') or 'continue') if merge is not None else None,
                    child_blocks,
                ))
            rows.append(tuple(cells))
        text = '\n'.join('\t'.join(c.text for c in row) for row in rows)
        raw_text = ''.join(t.text or '' for t in element.iter(W + 't'))
        if ''.join(raw_text.split()) != ''.join(text.split()):
            diagnostics.append(ParseDiagnostic('table_text_coverage_pending', locator,
                                               '表内文字未全部进入单元格投影，暂不可视为完整提取。'))
        return DocxBlock('docx_' + identity[:24], locator, 'table', role, text, tuple(rows))

    wrappers = {'sdt', 'sdtContent', 'customXml', 'ins', 'del', 'moveFrom', 'moveTo', 'footnote', 'endnote'}

    def walk(container: ET.Element, path: str, role: str) -> list[DocxBlock]:
        result = []
        for index, child in enumerate(container):
            tag = _local(child)
            locator = f'{path}/{index}:{tag}'
            if child.tag in {W + 'p', W + 'tbl'}:
                block = add(child, locator, role)
                if block is not None:
                    result.append(block)
            elif tag in wrappers:
                result.extend(walk(child, locator, _control_role(child, role) if tag == 'sdt' else role))
            elif tag == 'altChunk':
                diagnostics.append(ParseDiagnostic('external_chunk_pending', locator,
                                                   '嵌入的外部文稿尚未展开，暂不可视为完整提取。'))
            elif any((t.text or '').strip() for t in child.iter(W + 't')):
                diagnostics.append(ParseDiagnostic('unhandled_text_container', locator,
                                                   '源中存在尚未分类的文字容器，需来源核对。'))
        return result

    story_roots = [('word/document.xml', body, 'body', 'word/document.xml/body')]
    with ZipFile(BytesIO(payload)) as archive:
        for part in sorted(archive.namelist()):
            if not re.fullmatch(r'word/(?:header\d+|footer\d+|footnotes|endnotes)\.xml', part):
                continue
            role = 'header' if '/header' in part else 'footer' if '/footer' in part else 'footnote' if '/footnotes' in part else 'endnote'
            story_roots.append((part, ET.fromstring(archive.read(part)), role, part))
    for part, root, role, locator in story_roots:
        if any(root.find('.//' + W + tag) is not None for tag in ('ins', 'del', 'moveFrom', 'moveTo')):
            diagnostics.append(ParseDiagnostic('tracked_changes_present', part,
                                               '来源含修订标记，需确认所用版本，不自动宣称清洁定稿。'))
        if root.find('.//' + W + 'drawing') is not None or root.find('.//' + W + 'pict') is not None:
            diagnostics.append(ParseDiagnostic('visual_objects_pending', part,
                                               '图形或图像需视觉核对，文字提取不代表图中信息完整。'))
        blocks.extend(walk(root, locator, role))
    if not any(b.text.strip() for b in blocks):
        raise ValueError('DOCX contains no extractable source text')
    return DocxParseResult(source_hash, tuple(blocks), tuple(diagnostics), tuple(p[0] for p in story_roots))
