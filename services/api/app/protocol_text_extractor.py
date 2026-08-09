from __future__ import annotations

import base64
import hashlib
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CORE_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
NS = {"w": WORD_NS, "cp": CORE_NS, "dc": DC_NS}
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PICTURE_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
WORD_DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
SUPPORTED_EXTENSIONS = {".docx"}
TABLE_SCHEMA_VERSION = "structured_table_v1"


@dataclass(frozen=True)
class ProtocolParagraph:
    paragraph_index: int
    text: str
    source_locator: str
    body_order: int = 0
    style_id: str = ""
    style_name: str = ""
    num_id: Optional[str] = None
    ilvl: Optional[int] = None
    outline_level: Optional[int] = None
    numbering_format: str = ""
    numbering_level_text: str = ""
    numbering_start: Optional[int] = None
    numbering_start_override: Optional[int] = None
    is_in_table: bool = False
    table_index: Optional[int] = None
    rich_text: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProtocolTextSpan:
    span_id: str
    kind: str
    text: str
    source_locator: str
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    body_order: int = 0
    style_id: str = ""
    style_name: str = ""
    num_id: Optional[str] = None
    ilvl: Optional[int] = None
    outline_level: Optional[int] = None


@dataclass(frozen=True)
class ProtocolTableCell:
    row_index: int
    cell_index: int
    text: str
    source_locator: str
    cell_id: str = ""
    grid_column_index: int = 0
    column_span: int = 1
    row_span: int = 1
    vertical_merge: str = "none"
    hidden: bool = False
    merge_parent_cell_id: Optional[str] = None
    merge_parent_source_locator: Optional[str] = None
    merge_parent_row_index: Optional[int] = None
    merge_parent_cell_index: Optional[int] = None
    merge_parent_grid_column_index: Optional[int] = None
    style_role: str = "body"


@dataclass(frozen=True)
class ProtocolTableCaption:
    caption_id: str
    text: str
    source_locator: str
    paragraph_index: int
    body_order: int
    review_status: str = "confirmed"
    association_reason: str = ""


@dataclass(frozen=True)
class ProtocolTableNote:
    note_id: str
    marker: str
    text: str
    source_locator: str
    target_scope: str
    target_table_id: str
    target_row_index: Optional[int] = None
    target_cell_id: Optional[str] = None
    target_cell_source_locator: Optional[str] = None
    marker_source_locator: str = ""
    source_kind: str = "post_table_paragraph"
    review_status: str = "confirmed"
    association_reason: str = ""


@dataclass(frozen=True)
class ProtocolTable:
    table_index: int
    rows: List[List[ProtocolTableCell]]
    source_locator: str
    body_order: int = 0
    table_id: str = ""
    schema_version: str = TABLE_SCHEMA_VERSION
    header_row_count: int = 0
    column_count: int = 0
    caption: Optional[ProtocolTableCaption] = None
    notes: List[ProtocolTableNote] = field(default_factory=list)


@dataclass(frozen=True)
class ProtocolEmbeddedImage:
    image_id: str
    source_locator: str
    body_order: int
    relationship_id: str
    part_name: str
    media_type: str
    image_base64: str
    image_sha256: str
    width_emu: Optional[int] = None
    height_emu: Optional[int] = None
    alt_text: str = ""
    caption: Optional[ProtocolTableCaption] = None
    semantic_role: str = "unclassified"


@dataclass(frozen=True)
class ProtocolTextDocument:
    filename: str
    title: str
    paragraphs: List[ProtocolParagraph]
    tables: List[ProtocolTable]
    spans: List[ProtocolTextSpan]
    source_hash: str = ""
    embedded_images: List[ProtocolEmbeddedImage] = field(default_factory=list)


@dataclass(frozen=True)
class _StyleDefinition:
    style_id: str
    name: str
    based_on: str
    num_id: Optional[str]
    ilvl: Optional[int]
    outline_level: Optional[int]
    paragraph_format: Dict[str, object] = field(default_factory=dict)
    run_format: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _NumberingLevel:
    number_format: str
    level_text: str
    start: Optional[int]
    start_override: Optional[int]


@dataclass(frozen=True)
class _ParagraphProperties:
    style_id: str
    style_name: str
    num_id: Optional[str]
    ilvl: Optional[int]
    outline_level: Optional[int]
    numbering_format: str
    numbering_level_text: str
    numbering_start: Optional[int]
    numbering_start_override: Optional[int]


@dataclass(frozen=True)
class _PostTableNote:
    marker: str
    text: str
    source_locator: str
    paragraph_index: int
    body_order: int
    review_status: str
    association_reason: str


def parse_protocol_docx(filename: str | Path, content: bytes | None = None) -> ProtocolTextDocument:
    """Extract raw DOCX text spans for AI source intake without medical interpretation."""
    path = Path(filename)
    display_name = path.name
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"unsupported protocol file type: {path.suffix.lower() or 'unknown'}")
    if content is None:
        content = path.read_bytes()
    source_hash = hashlib.sha256(content).hexdigest()

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            document_xml = archive.read("word/document.xml")
            core_title = _read_core_title(archive)
            styles, default_style_id = _read_styles(archive)
            numbering = _read_numbering(archive)
            footnotes = _read_word_notes(archive, "word/footnotes.xml", "footnote")
            endnotes = _read_word_notes(archive, "word/endnotes.xml", "endnote")
            relationships_xml = _read_optional_part(
                archive,
                "word/_rels/document.xml.rels",
            )
            embedded_parts = {
                name: archive.read(name)
                for name in archive.namelist()
                if name.startswith("word/media/") and not name.endswith("/")
            }
    except KeyError as exc:
        raise ValueError("docx file is missing word/document.xml") from exc
    except zipfile.BadZipFile as exc:
        raise ValueError("protocol docx is not a valid zip archive") from exc

    root = ElementTree.fromstring(document_xml)
    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("docx document has no word body")

    paragraphs: List[ProtocolParagraph] = []
    tables: List[ProtocolTable] = []
    spans: List[ProtocolTextSpan] = []
    paragraph_index = 0
    table_index = 0

    for body_order, child in enumerate(list(body)):
        if child.tag == _w("p"):
            paragraph_index = _append_paragraph(
                child,
                paragraph_index,
                f"docx:paragraph:{paragraph_index}",
                body_order,
                paragraphs,
                spans,
                styles,
                default_style_id,
                numbering,
            )
        elif child.tag == _w("tbl"):
            table, paragraph_index = _parse_table(
                child,
                table_index,
                paragraph_index,
                body_order,
                paragraphs,
                spans,
                styles,
                default_style_id,
                numbering,
                source_hash,
                footnotes,
                endnotes,
            )
            tables.append(table)
            table_index += 1

    tables = _associate_table_context(
        body,
        paragraphs,
        tables,
        source_hash,
    )
    embedded_images = _extract_embedded_images(
        body,
        paragraphs,
        source_hash,
        relationships_xml,
        embedded_parts,
    )

    title = core_title or _first_non_empty_text(paragraphs) or path.stem
    return ProtocolTextDocument(
        filename=display_name,
        title=title,
        paragraphs=paragraphs,
        tables=tables,
        spans=spans,
        source_hash=source_hash,
        embedded_images=embedded_images,
    )


def _read_optional_part(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except KeyError:
        return b""


def _extract_embedded_images(
    body: ElementTree.Element,
    paragraphs: List[ProtocolParagraph],
    source_hash: str,
    relationships_xml: bytes,
    embedded_parts: Dict[str, bytes],
) -> List[ProtocolEmbeddedImage]:
    if not relationships_xml:
        return []
    relationship_root = ElementTree.fromstring(relationships_xml)
    relationship_targets = {
        relationship.attrib.get("Id", ""): relationship.attrib.get("Target", "")
        for relationship in relationship_root.findall(
            f"{{{PACKAGE_REL_NS}}}Relationship"
        )
        if relationship.attrib.get("Type", "").endswith("/image")
    }
    body_children = list(body)
    body_paragraphs = {
        paragraph.body_order: paragraph
        for paragraph in paragraphs
        if not paragraph.is_in_table
    }
    images: List[ProtocolEmbeddedImage] = []
    for body_order, child in enumerate(body_children):
        if child.tag != _w("p"):
            continue
        drawings = child.findall(f".//{{{WORD_NS}}}drawing")
        for drawing_index, drawing in enumerate(drawings):
            blip = drawing.find(f".//{{{DRAWING_NS}}}blip")
            if blip is None:
                continue
            relationship_id = blip.attrib.get(f"{{{OFFICE_REL_NS}}}embed", "")
            target = relationship_targets.get(relationship_id, "")
            if not relationship_id or not target:
                continue
            part_name = posixpath.normpath(posixpath.join("word", target))
            if not part_name.startswith("word/media/") or part_name not in embedded_parts:
                continue
            image_bytes = embedded_parts[part_name]
            extension = Path(part_name).suffix.lower()
            media_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".tif": "image/tiff",
                ".tiff": "image/tiff",
            }.get(extension, "application/octet-stream")
            source_locator = f"docx:drawing:{body_order}:{drawing_index}"
            extent = drawing.find(f".//{{{WORD_DRAWING_NS}}}extent")
            properties = drawing.find(f".//{{{PICTURE_NS}}}cNvPr")
            caption, semantic_role = _embedded_image_caption(
                body_order,
                body_children,
                body_paragraphs,
                source_hash,
            )
            images.append(
                ProtocolEmbeddedImage(
                    image_id=_stable_structure_id(
                        "ptimg",
                        source_hash,
                        source_locator,
                    ),
                    source_locator=source_locator,
                    body_order=body_order,
                    relationship_id=relationship_id,
                    part_name=part_name,
                    media_type=media_type,
                    image_base64=base64.b64encode(image_bytes).decode("ascii"),
                    image_sha256=hashlib.sha256(image_bytes).hexdigest(),
                    width_emu=_optional_positive_int(
                        extent.attrib.get("cx") if extent is not None else None
                    ),
                    height_emu=_optional_positive_int(
                        extent.attrib.get("cy") if extent is not None else None
                    ),
                    alt_text=(
                        properties.attrib.get("descr", "")
                        if properties is not None
                        else ""
                    ),
                    caption=caption,
                    semantic_role=semantic_role,
                )
            )
    return images


def _embedded_image_caption(
    body_order: int,
    body_children: List[ElementTree.Element],
    body_paragraphs: Dict[int, ProtocolParagraph],
    source_hash: str,
) -> Tuple[Optional[ProtocolTableCaption], str]:
    for candidate_order in range(body_order - 1, -1, -1):
        child = body_children[candidate_order]
        if child.tag != _w("p"):
            return None, "unclassified"
        if not _paragraph_text(child):
            continue
        paragraph = body_paragraphs.get(candidate_order)
        if paragraph is None:
            return None, "unclassified"
        status, reason = _caption_association(paragraph)
        role = "table_image"
        if not status and re.match(
            r"^(?:图|附图)\s*[0-9A-Za-z一二三四五六七八九十IVXivx.\-]*\s*\S+",
            paragraph.text.strip(),
        ):
            status, reason, role = (
                "confirmed",
                "紧邻图片前的段落具有明确图号前缀。",
                "figure",
            )
        if not status:
            return None, "unclassified"
        caption = ProtocolTableCaption(
            caption_id=_stable_structure_id(
                "ptcaption",
                source_hash,
                paragraph.source_locator,
            ),
            text=paragraph.text,
            source_locator=paragraph.source_locator,
            paragraph_index=paragraph.paragraph_index,
            body_order=paragraph.body_order,
            review_status=status,
            association_reason=reason,
        )
        return caption, role
    return None, "unclassified"


def _optional_positive_int(value: object) -> Optional[int]:
    try:
        number = int(str(value))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _parse_table(
    table_element: ElementTree.Element,
    table_index: int,
    paragraph_index: int,
    body_order: int,
    paragraphs: List[ProtocolParagraph],
    spans: List[ProtocolTextSpan],
    styles: Dict[str, _StyleDefinition],
    default_style_id: str,
    numbering: Dict[Tuple[str, int], _NumberingLevel],
    source_hash: str,
    footnotes: Dict[str, str],
    endnotes: Dict[str, str],
) -> tuple[ProtocolTable, int]:
    rows: List[List[ProtocolTableCell]] = []
    table_locator = f"docx:table:{table_index}"
    table_id = _stable_structure_id("ptbl", source_hash, table_locator)
    column_count = len(table_element.findall("w:tblGrid/w:gridCol", NS))
    header_flags: List[bool] = []
    table_notes: List[ProtocolTableNote] = []
    active_vertical_merges: Dict[int, Tuple[int, int]] = {}
    for row_index, row_element in enumerate(table_element.findall("w:tr", NS)):
        row_cells: List[ProtocolTableCell] = []
        row_is_header = _row_is_header(row_element)
        header_flags.append(row_is_header)
        grid_column_index = _word_integer(row_element.find("w:trPr/w:gridBefore", NS), 0)
        next_vertical_merges: Dict[int, Tuple[int, int]] = {}
        for cell_index, cell_element in enumerate(row_element.findall("w:tc", NS)):
            cell_locator = f"docx:table:{table_index}:row:{row_index}:cell:{cell_index}"
            cell_id = _stable_structure_id("ptcell", source_hash, cell_locator)
            column_span = _word_integer(cell_element.find("w:tcPr/w:gridSpan", NS), 1)
            vertical_merge = _vertical_merge_state(cell_element)
            cell_paragraphs: List[str] = []
            for cell_paragraph_index, paragraph_element in enumerate(cell_element.findall(".//w:p", NS)):
                text = _paragraph_text(paragraph_element)
                if not text:
                    continue
                properties = _paragraph_properties(
                    paragraph_element,
                    styles,
                    default_style_id,
                    numbering,
                )
                source_locator = f"{cell_locator}:paragraph:{cell_paragraph_index}"
                paragraphs.append(
                    ProtocolParagraph(
                        paragraph_index=paragraph_index,
                        text=text,
                        source_locator=source_locator,
                        body_order=body_order,
                        style_id=properties.style_id,
                        style_name=properties.style_name,
                        num_id=properties.num_id,
                        ilvl=properties.ilvl,
                        outline_level=properties.outline_level,
                        numbering_format=properties.numbering_format,
                        numbering_level_text=properties.numbering_level_text,
                        numbering_start=properties.numbering_start,
                        numbering_start_override=properties.numbering_start_override,
                        is_in_table=True,
                        table_index=table_index,
                        rich_text=_paragraph_rich_text(
                            paragraph_element,
                            properties,
                            styles,
                        ),
                    )
                )
                spans.append(
                    ProtocolTextSpan(
                        span_id=f"p{paragraph_index}",
                        kind="table_cell",
                        text=text,
                        source_locator=source_locator,
                        paragraph_index=paragraph_index,
                        table_index=table_index,
                        row_index=row_index,
                        cell_index=cell_index,
                        body_order=body_order,
                        style_id=properties.style_id,
                        style_name=properties.style_name,
                        num_id=properties.num_id,
                        ilvl=properties.ilvl,
                        outline_level=properties.outline_level,
                    )
                )
                cell_paragraphs.append(text)
                paragraph_index += 1
            cell_text = "\n".join(cell_paragraphs)
            cell = ProtocolTableCell(
                row_index=row_index,
                cell_index=cell_index,
                text=cell_text,
                source_locator=cell_locator,
                cell_id=cell_id,
                grid_column_index=grid_column_index,
                column_span=column_span,
                vertical_merge=vertical_merge,
                style_role="header" if row_is_header else "body",
            )
            table_notes.extend(
                _extract_cell_note_markers(
                    cell_element,
                    table_id=table_id,
                    cell=cell,
                    source_hash=source_hash,
                    footnotes=footnotes,
                    endnotes=endnotes,
                )
            )
            parent_position = active_vertical_merges.get(grid_column_index)
            merge_parent_position: Optional[Tuple[int, int]] = None
            if vertical_merge == "continue" and parent_position is not None:
                parent_row_index, parent_cell_position = parent_position
                parent = rows[parent_row_index][parent_cell_position]
                cell = replace(
                    cell,
                    hidden=True,
                    merge_parent_cell_id=parent.cell_id,
                    merge_parent_source_locator=parent.source_locator,
                    merge_parent_row_index=parent.row_index,
                    merge_parent_cell_index=parent.cell_index,
                    merge_parent_grid_column_index=parent.grid_column_index,
                )
                parent_row_span = row_index - parent.row_index + 1
                if parent_row_span > parent.row_span:
                    rows[parent_row_index][parent_cell_position] = replace(
                        parent,
                        row_span=parent_row_span,
                    )
                merge_parent_position = parent_position
            elif vertical_merge == "restart":
                merge_parent_position = (row_index, len(row_cells))
            if merge_parent_position is not None:
                for column_index in range(grid_column_index, grid_column_index + column_span):
                    next_vertical_merges[column_index] = merge_parent_position
            row_cells.append(cell)
            grid_column_index += column_span
        rows.append(row_cells)
        grid_column_index += _word_integer(row_element.find("w:trPr/w:gridAfter", NS), 0)
        column_count = max(column_count, grid_column_index)
        active_vertical_merges = next_vertical_merges
    header_row_count = 0
    for row_is_header in header_flags:
        if not row_is_header:
            break
        header_row_count += 1
    return (
        ProtocolTable(
            table_index=table_index,
            rows=rows,
            source_locator=table_locator,
            body_order=body_order,
            table_id=table_id,
            schema_version=TABLE_SCHEMA_VERSION,
            header_row_count=header_row_count,
            column_count=column_count,
            notes=table_notes,
        ),
        paragraph_index,
    )


def _extract_cell_note_markers(
    cell_element: ElementTree.Element,
    *,
    table_id: str,
    cell: ProtocolTableCell,
    source_hash: str,
    footnotes: Dict[str, str],
    endnotes: Dict[str, str],
) -> List[ProtocolTableNote]:
    notes: List[ProtocolTableNote] = []
    seen: set[Tuple[str, str]] = set()
    for paragraph_index, paragraph in enumerate(cell_element.findall(".//w:p", NS)):
        runs = paragraph.findall(".//w:r", NS)
        run_index = 0
        while run_index < len(runs):
            run = runs[run_index]
            run_locator = f"{cell.source_locator}:paragraph:{paragraph_index}:run:{run_index}"
            vertical_align = run.find("w:rPr/w:vertAlign", NS)
            has_word_note_reference = any(
                run.find(f".//w:{reference_name}", NS) is not None
                for reference_name in ("footnoteReference", "endnoteReference")
            )
            if (
                vertical_align is not None
                and vertical_align.get(_w("val"), "").lower() == "superscript"
                and not has_word_note_reference
            ):
                marker_parts: List[str] = []
                marker_run_end = run_index
                while marker_run_end < len(runs):
                    marker_run = runs[marker_run_end]
                    marker_align = marker_run.find("w:rPr/w:vertAlign", NS)
                    marker_has_note_reference = any(
                        marker_run.find(f".//w:{reference_name}", NS) is not None
                        for reference_name in ("footnoteReference", "endnoteReference")
                    )
                    if (
                        marker_align is None
                        or marker_align.get(_w("val"), "").lower() != "superscript"
                        or marker_has_note_reference
                    ):
                        break
                    marker_parts.append(
                        "".join(text.text or "" for text in marker_run.findall(".//w:t", NS))
                    )
                    marker_run_end += 1
                marker = _normalize_text("".join(marker_parts))
                marker_locator = (
                    run_locator
                    if marker_run_end == run_index + 1
                    else f"{cell.source_locator}:paragraph:{paragraph_index}:run:{run_index}-{marker_run_end - 1}"
                )
                if _is_note_marker(marker) and ("superscript", marker.casefold()) not in seen:
                    seen.add(("superscript", marker.casefold()))
                    notes.append(
                        _cell_note(
                            source_hash=source_hash,
                            marker=marker,
                            text="",
                            source_locator=marker_locator,
                            marker_source_locator=marker_locator,
                            source_kind="in_cell_superscript",
                            review_status="pending_human_review",
                            association_reason="检测到表内上标，但未找到可确定关联的表下注释。",
                            table_id=table_id,
                            cell=cell,
                        )
                    )
                run_index = marker_run_end
                continue
            for reference_name, note_kind, note_map in (
                ("footnoteReference", "footnote", footnotes),
                ("endnoteReference", "endnote", endnotes),
            ):
                for reference_index, reference in enumerate(run.findall(f".//w:{reference_name}", NS)):
                    note_number = reference.get(_w("id"), "")
                    if not note_number or (note_kind, note_number) in seen:
                        continue
                    seen.add((note_kind, note_number))
                    text = note_map.get(note_number, "")
                    marker_locator = f"{run_locator}:{reference_name}:{reference_index}"
                    note_locator = f"docx:{note_kind}:{note_number}" if text else marker_locator
                    notes.append(
                        _cell_note(
                            source_hash=source_hash,
                            marker=note_number,
                            text=text,
                            source_locator=note_locator,
                            marker_source_locator=marker_locator,
                            source_kind=f"word_{note_kind}",
                            review_status="confirmed" if text else "pending_human_review",
                            association_reason=(
                                f"Word {note_kind}Reference 明确关联到注释正文。"
                                if text
                                else f"检测到 Word {note_kind}Reference，但注释正文缺失。"
                            ),
                            table_id=table_id,
                            cell=cell,
                        )
                    )
            run_index += 1
    return notes


def _cell_note(
    *,
    source_hash: str,
    marker: str,
    text: str,
    source_locator: str,
    marker_source_locator: str,
    source_kind: str,
    review_status: str,
    association_reason: str,
    table_id: str,
    cell: ProtocolTableCell,
) -> ProtocolTableNote:
    note_locator = f"{source_locator}|target:{cell.cell_id}|marker:{marker}"
    return ProtocolTableNote(
        note_id=_stable_structure_id("ptnote", source_hash, note_locator),
        marker=marker,
        text=text,
        source_locator=source_locator,
        target_scope="cell",
        target_table_id=table_id,
        target_row_index=cell.row_index,
        target_cell_id=cell.cell_id,
        target_cell_source_locator=cell.source_locator,
        marker_source_locator=marker_source_locator,
        source_kind=source_kind,
        review_status=review_status,
        association_reason=association_reason,
    )


def _associate_table_context(
    body: ElementTree.Element,
    paragraphs: List[ProtocolParagraph],
    tables: List[ProtocolTable],
    source_hash: str,
) -> List[ProtocolTable]:
    body_children = list(body)
    body_paragraphs = {
        paragraph.body_order: paragraph
        for paragraph in paragraphs
        if not paragraph.is_in_table
    }
    associated: List[ProtocolTable] = []
    for table in tables:
        caption = _table_caption(
            table,
            body_children,
            body_paragraphs,
            source_hash,
        )
        post_notes = _post_table_notes(
            table,
            body_children,
            body_paragraphs,
        )
        associated.append(
            replace(
                table,
                caption=caption,
                notes=_merge_table_notes(table, post_notes, source_hash),
            )
        )
    return associated


def _table_caption(
    table: ProtocolTable,
    body_children: List[ElementTree.Element],
    body_paragraphs: Dict[int, ProtocolParagraph],
    source_hash: str,
) -> Optional[ProtocolTableCaption]:
    for body_order in range(table.body_order - 1, -1, -1):
        child = body_children[body_order]
        if child.tag != _w("p"):
            return None
        text = _paragraph_text(child)
        if not text:
            continue
        paragraph = body_paragraphs.get(body_order)
        if paragraph is None:
            return None
        status, reason = _caption_association(paragraph)
        if not status:
            return None
        return ProtocolTableCaption(
            caption_id=_stable_structure_id("ptcaption", source_hash, paragraph.source_locator),
            text=paragraph.text,
            source_locator=paragraph.source_locator,
            paragraph_index=paragraph.paragraph_index,
            body_order=paragraph.body_order,
            review_status=status,
            association_reason=reason,
        )
    return None


def _caption_association(paragraph: ProtocolParagraph) -> Tuple[str, str]:
    text = paragraph.text.strip()
    style_name = paragraph.style_name.casefold()
    if any(token in style_name for token in ("caption", "题注", "表题", "table title")):
        return "confirmed", "紧邻表格前的段落使用表题/题注样式。"
    if re.match(
        r"^(?:(?:表|附表)\s*|(?:Appendix\s+)?Table\s+)"
        r"[0-9A-Za-z一二三四五六七八九十IVXivx.\-]*\s*\S+",
        text,
        flags=re.IGNORECASE,
    ):
        return "confirmed", "紧邻表格前的段落具有明确表号或附表前缀。"
    if (
        len(text) <= 80
        and paragraph.outline_level is not None
        and re.search(r"(?:流程表|缩略语表|列表|术语定义)$", text)
    ):
        return "confirmed", "紧邻表格前的短标题具有标题层级和表格名称特征。"
    if (
        len(text) <= 60
        and paragraph.outline_level is not None
        and not re.search(r"[。！？；;]$", text)
    ):
        return "pending_human_review", "紧邻表格前的是短标题，但未发现明确表号或表题样式。"
    return "", ""


def _post_table_notes(
    table: ProtocolTable,
    body_children: List[ElementTree.Element],
    body_paragraphs: Dict[int, ProtocolParagraph],
) -> List[_PostTableNote]:
    known_markers = {
        _normalized_marker_key(note.marker)
        for note in table.notes
        if note.marker
    }
    candidates: List[_PostTableNote] = []
    body_order = table.body_order + 1
    started = False
    allow_descriptive_continuation = False
    list_counters: Dict[Tuple[str, Optional[int]], int] = {}

    while body_order < len(body_children):
        child = body_children[body_order]
        if child.tag != _w("p"):
            break
        text = _paragraph_text(child)
        if not text:
            body_order += 1
            continue
        paragraph = body_paragraphs.get(body_order)
        if paragraph is None:
            break
        explicit = _parse_explicit_note(paragraph, known_markers)
        if explicit is not None:
            marker, note_text, reason = explicit
            started = True
            if not note_text:
                allow_descriptive_continuation = True
            else:
                candidates.append(
                    _PostTableNote(
                        marker=marker,
                        text=note_text,
                        source_locator=paragraph.source_locator,
                        paragraph_index=paragraph.paragraph_index,
                        body_order=paragraph.body_order,
                        review_status="confirmed",
                        association_reason=reason,
                    )
                )
            body_order += 1
            continue
        if not started or paragraph.outline_level is not None:
            break
        if paragraph.num_id is not None and (known_markers or allow_descriptive_continuation):
            marker = _next_list_marker(paragraph, list_counters)
            candidates.append(
                _PostTableNote(
                    marker=marker,
                    text=paragraph.text,
                    source_locator=paragraph.source_locator,
                    paragraph_index=paragraph.paragraph_index,
                    body_order=paragraph.body_order,
                    review_status="pending_human_review",
                    association_reason="位于明确表注引导语后的连续 Word 编号列表；编号已按 OOXML 属性重建。",
                )
            )
            body_order += 1
            continue
        if allow_descriptive_continuation and _looks_like_note_continuation(paragraph.text):
            candidates.append(
                _PostTableNote(
                    marker="",
                    text=paragraph.text,
                    source_locator=paragraph.source_locator,
                    paragraph_index=paragraph.paragraph_index,
                    body_order=paragraph.body_order,
                    review_status="pending_human_review",
                    association_reason="位于空的表注引导语后且具有说明性格式；具体范围待人工确认。",
                )
            )
            body_order += 1
            continue
        break
    return candidates


def _parse_explicit_note(
    paragraph: ProtocolParagraph,
    known_markers: set[str],
) -> Optional[Tuple[str, str, str]]:
    text = paragraph.text.strip()
    prefixed = re.match(
        r"^(?P<label>注(?:释)?|备注|说明|缩写(?:说明|词)?|来源|Notes?|Abbreviations?|Source)\s*"
        r"(?P<marker>[0-9０-９A-Za-zＡ-Ｚａ-ｚ①-⑳*†‡#]?)\s*[:：]\s*(?P<text>.*)$",
        text,
        flags=re.IGNORECASE,
    )
    if prefixed:
        marker = prefixed.group("marker") or prefixed.group("label")
        note_text = prefixed.group("text").strip()
        nested_marker = re.match(r"^(?P<marker>[①-⑳])\s*(?P<text>.+)$", note_text)
        if nested_marker and not prefixed.group("marker"):
            marker = nested_marker.group("marker")
            note_text = nested_marker.group("text").strip()
        return marker, note_text, "段落具有明确的表注、备注、说明或来源前缀。"

    unpunctuated_prefixed = re.match(
        r"^(?P<label>注(?:释)?|Note)\s*(?P<marker>[0-9０-９A-Za-zＡ-Ｚａ-ｚ①-⑳*†‡#])"
        r"[.)、]?\s+(?P<text>.+)$",
        text,
        flags=re.IGNORECASE,
    )
    if unpunctuated_prefixed:
        return (
            unpunctuated_prefixed.group("marker"),
            unpunctuated_prefixed.group("text").strip(),
            "段落以明确的注释编号或字母前缀开头。",
        )

    circled = re.match(r"^(?P<marker>[①-⑳])\s*(?P<text>.+)$", text)
    if circled:
        return circled.group("marker"), circled.group("text").strip(), "段落以明确的圈号注释标记开头。"

    bare_marker = re.match(
        r"^(?P<marker>[0-9０-９A-Za-zＡ-Ｚａ-ｚ*†‡#]{1,4})[.)、]?\s+(?P<text>.+)$",
        text,
    )
    if bare_marker and _normalized_marker_key(bare_marker.group("marker")) in known_markers:
        return bare_marker.group("marker"), bare_marker.group("text").strip(), "段落起始标记与表内上标完全一致。"
    return None


def _merge_table_notes(
    table: ProtocolTable,
    post_notes: List[_PostTableNote],
    source_hash: str,
) -> List[ProtocolTableNote]:
    by_marker: Dict[str, List[_PostTableNote]] = {}
    for note in post_notes:
        if note.marker:
            by_marker.setdefault(_normalized_marker_key(note.marker), []).append(note)

    merged: List[ProtocolTableNote] = []
    used_note_locators: set[str] = set()
    for note in table.notes:
        if note.source_kind in {"word_footnote", "word_endnote"}:
            merged.append(note)
            continue
        matches = by_marker.get(_normalized_marker_key(note.marker), [])
        if matches:
            match = matches[0]
            used_note_locators.add(match.source_locator)
            merged.append(
                replace(
                    note,
                    note_id=_stable_structure_id(
                        "ptnote",
                        source_hash,
                        f"{match.source_locator}|target:{note.target_cell_id}|marker:{note.marker}",
                    ),
                    text=match.text,
                    source_locator=match.source_locator,
                    source_kind="post_table_paragraph_with_cell_marker",
                    review_status=(
                        "confirmed" if len(matches) == 1 else "pending_human_review"
                    ),
                    association_reason=(
                        "表下注释标记与表内上标完全一致。"
                        if len(matches) == 1
                        else "存在多个相同表下注释标记，已保留首个候选并等待人工确认。"
                    ),
                )
            )
        else:
            merged.append(note)

    for post_note in post_notes:
        if post_note.source_locator in used_note_locators:
            continue
        note_locator = f"{post_note.source_locator}|target:{table.table_id}|marker:{post_note.marker}"
        merged.append(
            ProtocolTableNote(
                note_id=_stable_structure_id("ptnote", source_hash, note_locator),
                marker=post_note.marker,
                text=post_note.text,
                source_locator=post_note.source_locator,
                target_scope="table",
                target_table_id=table.table_id,
                source_kind="post_table_paragraph",
                review_status=post_note.review_status,
                association_reason=post_note.association_reason,
            )
        )
    return merged


def _next_list_marker(
    paragraph: ProtocolParagraph,
    counters: Dict[Tuple[str, Optional[int]], int],
) -> str:
    key = (paragraph.num_id or "", paragraph.ilvl)
    if key not in counters:
        counters[key] = (
            paragraph.numbering_start_override
            if paragraph.numbering_start_override is not None
            else paragraph.numbering_start
            if paragraph.numbering_start is not None
            else 1
        )
    else:
        counters[key] += 1
    value = counters[key]
    if paragraph.numbering_format == "lowerLetter":
        return _alphabetic_marker(value).lower()
    if paragraph.numbering_format == "upperLetter":
        return _alphabetic_marker(value).upper()
    if paragraph.numbering_format == "lowerRoman":
        return _roman_marker(value).lower()
    if paragraph.numbering_format == "upperRoman":
        return _roman_marker(value)
    return str(value)


def _alphabetic_marker(value: int) -> str:
    if value <= 0:
        return str(value)
    marker = ""
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        marker = chr(ord("A") + remainder) + marker
    return marker


def _roman_marker(value: int) -> str:
    if value <= 0 or value > 3999:
        return str(value)
    result = ""
    for number, numeral in (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ):
        while value >= number:
            result += numeral
            value -= number
    return result


def _looks_like_note_continuation(text: str) -> bool:
    stripped = text.strip()
    return bool(re.search(r"[:：=＝]", stripped)) and not stripped.endswith(("。", "！", "？"))


def _is_note_marker(marker: str) -> bool:
    if not marker or marker in {"®", "™", "©"} or len(marker) > 8:
        return False
    return bool(re.fullmatch(r"[0-9０-９A-Za-zＡ-Ｚａ-ｚ①-⑳*†‡#]+", marker))


def _normalized_marker_key(marker: str) -> str:
    return marker.strip().strip("()（）.、:：").casefold()


def _stable_structure_id(prefix: str, source_hash: str, source_locator: str) -> str:
    token = hashlib.sha256(f"{source_hash}|{source_locator}".encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{token}"


def _word_integer(element: ElementTree.Element | None, default: int) -> int:
    if element is None:
        return default
    raw_value = element.attrib.get(_w("val"), "")
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return value if value >= 1 else default


def _row_is_header(row_element: ElementTree.Element) -> bool:
    header = row_element.find("w:trPr/w:tblHeader", NS)
    if header is None:
        return False
    return header.attrib.get(_w("val"), "true").lower() not in {"0", "false", "off", "no"}


def _vertical_merge_state(cell_element: ElementTree.Element) -> str:
    vertical_merge = cell_element.find("w:tcPr/w:vMerge", NS)
    if vertical_merge is None:
        return "none"
    if vertical_merge.attrib.get(_w("val"), "continue").lower() == "restart":
        return "restart"
    return "continue"


def _append_paragraph(
    paragraph_element: ElementTree.Element,
    paragraph_index: int,
    source_locator: str,
    body_order: int,
    paragraphs: List[ProtocolParagraph],
    spans: List[ProtocolTextSpan],
    styles: Dict[str, _StyleDefinition],
    default_style_id: str,
    numbering: Dict[Tuple[str, int], _NumberingLevel],
) -> int:
    text = _paragraph_text(paragraph_element)
    if not text:
        return paragraph_index
    properties = _paragraph_properties(
        paragraph_element,
        styles,
        default_style_id,
        numbering,
    )
    paragraphs.append(
        ProtocolParagraph(
            paragraph_index=paragraph_index,
            text=text,
            source_locator=source_locator,
            body_order=body_order,
            style_id=properties.style_id,
            style_name=properties.style_name,
            num_id=properties.num_id,
            ilvl=properties.ilvl,
            outline_level=properties.outline_level,
            numbering_format=properties.numbering_format,
            numbering_level_text=properties.numbering_level_text,
            numbering_start=properties.numbering_start,
            numbering_start_override=properties.numbering_start_override,
            rich_text=_paragraph_rich_text(paragraph_element, properties, styles),
        )
    )
    spans.append(
        ProtocolTextSpan(
            span_id=f"p{paragraph_index}",
            kind="paragraph",
            text=text,
            source_locator=source_locator,
            paragraph_index=paragraph_index,
            body_order=body_order,
            style_id=properties.style_id,
            style_name=properties.style_name,
            num_id=properties.num_id,
            ilvl=properties.ilvl,
            outline_level=properties.outline_level,
        )
    )
    return paragraph_index + 1


def _read_styles(
    archive: zipfile.ZipFile,
) -> tuple[Dict[str, _StyleDefinition], str]:
    try:
        root = ElementTree.fromstring(archive.read("word/styles.xml"))
    except KeyError:
        return {}, ""

    styles: Dict[str, _StyleDefinition] = {}
    default_style_id = ""
    for style_element in root.findall("w:style", NS):
        if style_element.get(_w("type")) != "paragraph":
            continue
        style_id = style_element.get(_w("styleId"), "")
        if not style_id:
            continue
        if style_element.get(_w("default")) in {"1", "true", "on"}:
            default_style_id = style_id
        name_element = style_element.find("w:name", NS)
        based_on_element = style_element.find("w:basedOn", NS)
        num_id, ilvl, outline_level = _ppr_values(style_element.find("w:pPr", NS))
        styles[style_id] = _StyleDefinition(
            style_id=style_id,
            name=name_element.get(_w("val"), "") if name_element is not None else "",
            based_on=(
                based_on_element.get(_w("val"), "")
                if based_on_element is not None
                else ""
            ),
            num_id=num_id,
            ilvl=ilvl,
            outline_level=outline_level,
            paragraph_format=_paragraph_format_attrs(style_element.find("w:pPr", NS)),
            run_format=_run_format_state(style_element.find("w:rPr", NS)),
        )
    return styles, default_style_id


def _read_numbering(
    archive: zipfile.ZipFile,
) -> Dict[Tuple[str, int], _NumberingLevel]:
    try:
        root = ElementTree.fromstring(archive.read("word/numbering.xml"))
    except KeyError:
        return {}

    abstract_levels: Dict[Tuple[str, int], _NumberingLevel] = {}
    for abstract_element in root.findall("w:abstractNum", NS):
        abstract_id = abstract_element.get(_w("abstractNumId"), "")
        for level_element in abstract_element.findall("w:lvl", NS):
            ilvl = _int_value(level_element.get(_w("ilvl")))
            if ilvl is None:
                continue
            abstract_levels[(abstract_id, ilvl)] = _numbering_level(level_element)

    numbering: Dict[Tuple[str, int], _NumberingLevel] = {}
    for num_element in root.findall("w:num", NS):
        num_id = num_element.get(_w("numId"), "")
        abstract_element = num_element.find("w:abstractNumId", NS)
        abstract_id = (
            abstract_element.get(_w("val"), "") if abstract_element is not None else ""
        )
        for (candidate_abstract_id, ilvl), level in abstract_levels.items():
            if candidate_abstract_id == abstract_id:
                numbering[(num_id, ilvl)] = level
        for override in num_element.findall("w:lvlOverride", NS):
            ilvl = _int_value(override.get(_w("ilvl")))
            start_override_element = override.find("w:startOverride", NS)
            start_override = _int_value(
                start_override_element.get(_w("val"))
                if start_override_element is not None
                else None
            )
            level_element = override.find("w:lvl", NS)
            if ilvl is None:
                continue
            base_level = numbering.get((num_id, ilvl))
            if level_element is not None:
                override_level = _numbering_level(level_element, start_override=start_override)
                numbering[(num_id, ilvl)] = _merge_numbering_level(
                    base_level,
                    override_level,
                )
            elif base_level is not None:
                numbering[(num_id, ilvl)] = _NumberingLevel(
                    number_format=base_level.number_format,
                    level_text=base_level.level_text,
                    start=base_level.start,
                    start_override=start_override,
                )
    return numbering


def _numbering_level(
    level_element: ElementTree.Element,
    *,
    start_override: Optional[int] = None,
) -> _NumberingLevel:
    number_format = level_element.find("w:numFmt", NS)
    level_text = level_element.find("w:lvlText", NS)
    start = level_element.find("w:start", NS)
    return _NumberingLevel(
        number_format=(
            number_format.get(_w("val"), "") if number_format is not None else ""
        ),
        level_text=level_text.get(_w("val"), "") if level_text is not None else "",
        start=_int_value(start.get(_w("val"))) if start is not None else None,
        start_override=start_override,
    )


def _merge_numbering_level(
    base: Optional[_NumberingLevel],
    override: _NumberingLevel,
) -> _NumberingLevel:
    if base is None:
        return override
    return _NumberingLevel(
        number_format=override.number_format or base.number_format,
        level_text=override.level_text or base.level_text,
        start=override.start if override.start is not None else base.start,
        start_override=override.start_override,
    )


def _paragraph_properties(
    paragraph_element: ElementTree.Element,
    styles: Dict[str, _StyleDefinition],
    default_style_id: str,
    numbering: Dict[Tuple[str, int], _NumberingLevel],
) -> _ParagraphProperties:
    ppr = paragraph_element.find("w:pPr", NS)
    style_element = ppr.find("w:pStyle", NS) if ppr is not None else None
    explicit_style_id = style_element.get(_w("val"), "") if style_element is not None else ""
    style_id = explicit_style_id or default_style_id

    num_id: Optional[str] = None
    ilvl: Optional[int] = None
    outline_level: Optional[int] = None
    style_name = ""
    for style in _style_chain(style_id, styles):
        style_name = style.name or style_name
        if style.num_id is not None:
            num_id = style.num_id
        if style.ilvl is not None:
            ilvl = style.ilvl
        if style.outline_level is not None:
            outline_level = style.outline_level

    direct_num_id, direct_ilvl, direct_outline_level = _ppr_values(ppr)
    if direct_num_id is not None:
        num_id = direct_num_id
    if direct_ilvl is not None:
        ilvl = direct_ilvl
    if direct_outline_level is not None:
        outline_level = direct_outline_level

    numbering_level = numbering.get((num_id, ilvl)) if num_id is not None and ilvl is not None else None
    return _ParagraphProperties(
        style_id=style_id,
        style_name=style_name,
        num_id=num_id,
        ilvl=ilvl,
        outline_level=outline_level,
        numbering_format=numbering_level.number_format if numbering_level else "",
        numbering_level_text=numbering_level.level_text if numbering_level else "",
        numbering_start=numbering_level.start if numbering_level else None,
        numbering_start_override=(
            numbering_level.start_override if numbering_level else None
        ),
    )


def _style_chain(
    style_id: str,
    styles: Dict[str, _StyleDefinition],
) -> List[_StyleDefinition]:
    chain: List[_StyleDefinition] = []
    seen = set()
    current_id = style_id
    while current_id and current_id not in seen:
        seen.add(current_id)
        style = styles.get(current_id)
        if style is None:
            break
        chain.append(style)
        current_id = style.based_on
    chain.reverse()
    return chain


def _ppr_values(
    ppr: Optional[ElementTree.Element],
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    if ppr is None:
        return None, None, None
    num_properties = ppr.find("w:numPr", NS)
    num_id_element = num_properties.find("w:numId", NS) if num_properties is not None else None
    ilvl_element = num_properties.find("w:ilvl", NS) if num_properties is not None else None
    outline_element = ppr.find("w:outlineLvl", NS)
    return (
        num_id_element.get(_w("val")) if num_id_element is not None else None,
        _int_value(ilvl_element.get(_w("val"))) if ilvl_element is not None else None,
        _int_value(outline_element.get(_w("val"))) if outline_element is not None else None,
    )


def _int_value(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


_WORD_HIGHLIGHT_COLORS = {
    "black": "#000000",
    "blue": "#0000FF",
    "cyan": "#00FFFF",
    "darkBlue": "#000080",
    "darkCyan": "#008080",
    "darkGray": "#808080",
    "darkGreen": "#008000",
    "darkMagenta": "#800080",
    "darkRed": "#800000",
    "darkYellow": "#808000",
    "green": "#00FF00",
    "lightGray": "#C0C0C0",
    "magenta": "#FF00FF",
    "red": "#FF0000",
    "white": "#FFFFFF",
    "yellow": "#FFFF00",
}


def _paragraph_rich_text(
    paragraph_element: ElementTree.Element,
    properties: _ParagraphProperties,
    styles: Dict[str, _StyleDefinition],
) -> Dict[str, object]:
    paragraph_attrs: Dict[str, object] = {}
    inherited_run_format: Dict[str, object] = {}
    for style in _style_chain(properties.style_id, styles):
        paragraph_attrs.update(style.paragraph_format)
        inherited_run_format.update(style.run_format)
    paragraph_attrs.update(_paragraph_format_attrs(paragraph_element.find("w:pPr", NS)))

    heading_level = None
    normalized_style_name = properties.style_name.lower().replace(" ", "")
    if properties.outline_level is not None:
        heading_level = min(6, max(1, properties.outline_level + 1))
    elif "heading" in normalized_style_name or "标题" in normalized_style_name:
        match = re.search(r"([1-6])", normalized_style_name)
        heading_level = int(match.group(1)) if match else 1

    node_type = "heading" if heading_level is not None else "paragraph"
    if heading_level is not None:
        paragraph_attrs["level"] = heading_level
        if heading_level <= 4:
            paragraph_attrs.setdefault("stylePreset", f"heading_{heading_level}")
    elif "note" in normalized_style_name or "注" in properties.style_name:
        paragraph_attrs.setdefault("stylePreset", "note")
    else:
        paragraph_attrs.setdefault("stylePreset", "body")

    raw_runs: List[Tuple[str, List[Dict[str, object]]]] = []
    for run in paragraph_element.findall(".//w:r", NS):
        raw_text = _run_text(run)
        if not raw_text:
            continue
        run_format = dict(inherited_run_format)
        run_format.update(_run_format_state(run.find("w:rPr", NS)))
        raw_runs.append((raw_text, _marks_from_run_format(run_format)))

    content = _normalized_tiptap_inline_content(raw_runs)
    rich_text: Dict[str, object] = {"type": node_type, "attrs": paragraph_attrs}
    if content:
        rich_text["content"] = content
    if _rich_text_plain_text(rich_text) != _paragraph_text(paragraph_element):
        text = _paragraph_text(paragraph_element)
        rich_text["content"] = [{"type": "text", "text": text}] if text else []
    return rich_text


def _paragraph_format_attrs(ppr: Optional[ElementTree.Element]) -> Dict[str, object]:
    if ppr is None:
        return {}
    attrs: Dict[str, object] = {}
    alignment = ppr.find("w:jc", NS)
    alignment_value = alignment.get(_w("val"), "") if alignment is not None else ""
    alignment_map = {
        "both": "justify",
        "center": "center",
        "distribute": "justify",
        "end": "right",
        "left": "left",
        "right": "right",
        "start": "left",
    }
    if alignment_value in alignment_map:
        attrs["textAlign"] = alignment_map[alignment_value]

    spacing = ppr.find("w:spacing", NS)
    if spacing is not None:
        for word_name, attr_name in (("before", "spacingBeforePt"), ("after", "spacingAfterPt")):
            value = _int_value(spacing.get(_w(word_name)))
            if value is not None:
                attrs[attr_name] = round(max(0, value) / 20, 2)
        line = _int_value(spacing.get(_w("line")))
        line_rule = spacing.get(_w("lineRule"), "auto")
        if line is not None:
            if line_rule == "auto":
                attrs["lineHeight"] = round(min(3.0, max(0.8, line / 240)), 2)
            else:
                attrs["lineHeight"] = round(min(3.0, max(0.8, line / 210)), 2)

    indentation = ppr.find("w:ind", NS)
    if indentation is not None:
        for word_name, attr_name in (
            ("leftChars", "leftIndentChars"),
            ("rightChars", "rightIndentChars"),
            ("firstLineChars", "firstLineIndentChars"),
        ):
            value = _int_value(indentation.get(_w(word_name)))
            if value is not None:
                attrs[attr_name] = round(value / 100, 2)
        if "leftIndentChars" not in attrs:
            value = _int_value(indentation.get(_w("left")) or indentation.get(_w("start")))
            if value is not None:
                attrs["leftIndentChars"] = round(min(20.0, max(0.0, value / 210)), 2)
        if "rightIndentChars" not in attrs:
            value = _int_value(indentation.get(_w("right")) or indentation.get(_w("end")))
            if value is not None:
                attrs["rightIndentChars"] = round(min(20.0, max(0.0, value / 210)), 2)
        if "firstLineIndentChars" not in attrs:
            first_line = _int_value(indentation.get(_w("firstLine")))
            hanging = _int_value(indentation.get(_w("hanging")))
            if first_line is not None:
                attrs["firstLineIndentChars"] = round(min(20.0, first_line / 210), 2)
            elif hanging is not None:
                attrs["firstLineIndentChars"] = round(max(-10.0, -hanging / 210), 2)
    return attrs


def _run_format_state(rpr: Optional[ElementTree.Element]) -> Dict[str, object]:
    if rpr is None:
        return {}
    state: Dict[str, object] = {}
    for element_name, key in (("b", "bold"), ("i", "italic")):
        value = _word_bool(rpr.find(f"w:{element_name}", NS))
        if value is not None:
            state[key] = value

    underline = rpr.find("w:u", NS)
    if underline is not None:
        state["underline"] = underline.get(_w("val"), "single").lower() not in {
            "0", "false", "none", "off",
        }
    vertical_align = rpr.find("w:vertAlign", NS)
    if vertical_align is not None:
        value = vertical_align.get(_w("val"), "")
        state["verticalAlign"] = value if value in {"superscript", "subscript"} else ""

    fonts = rpr.find("w:rFonts", NS)
    if fonts is not None:
        family = next(
            (
                fonts.get(_w(name), "").strip()
                for name in ("eastAsia", "ascii", "hAnsi", "cs")
                if fonts.get(_w(name), "").strip()
            ),
            "",
        )
        if family:
            state["fontFamily"] = family[:80]
    size = rpr.find("w:sz", NS)
    size_value = _int_value(size.get(_w("val"))) if size is not None else None
    if size_value is not None and 12 <= size_value <= 144:
        points = size_value / 2
        state["fontSize"] = f"{points:g}pt"
    color = rpr.find("w:color", NS)
    color_value = color.get(_w("val"), "") if color is not None else ""
    if re.fullmatch(r"[0-9A-Fa-f]{6}", color_value):
        state["color"] = f"#{color_value.upper()}"
    highlight = rpr.find("w:highlight", NS)
    highlight_value = highlight.get(_w("val"), "") if highlight is not None else ""
    if highlight_value in _WORD_HIGHLIGHT_COLORS:
        state["highlight"] = _WORD_HIGHLIGHT_COLORS[highlight_value]
    return state


def _word_bool(element: Optional[ElementTree.Element]) -> Optional[bool]:
    if element is None:
        return None
    return element.get(_w("val"), "true").lower() not in {"0", "false", "off", "no"}


def _marks_from_run_format(state: Dict[str, object]) -> List[Dict[str, object]]:
    marks: List[Dict[str, object]] = []
    for key in ("bold", "italic", "underline"):
        if state.get(key) is True:
            marks.append({"type": key})
    vertical_align = state.get("verticalAlign")
    if vertical_align in {"superscript", "subscript"}:
        marks.append({"type": vertical_align})
    text_style = {
        key: state[key]
        for key in ("fontFamily", "fontSize", "color")
        if state.get(key)
    }
    if text_style:
        marks.append({"type": "textStyle", "attrs": text_style})
    if state.get("highlight"):
        marks.append({"type": "highlight", "attrs": {"color": state["highlight"]}})
    return marks


def _run_text(run: ElementTree.Element) -> str:
    parts: List[str] = []
    for element in run.iter():
        if element.tag == _w("t"):
            parts.append(element.text or "")
        elif element.tag == _w("tab"):
            parts.append(" ")
        elif element.tag in {_w("br"), _w("cr")}:
            parts.append("\n")
    return "".join(parts)


def _normalized_tiptap_inline_content(
    raw_runs: List[Tuple[str, List[Dict[str, object]]]],
) -> List[Dict[str, object]]:
    characters: List[Tuple[str, List[Dict[str, object]]]] = []
    horizontal_space_pending = False
    pending_marks: List[Dict[str, object]] = []
    for text, marks in raw_runs:
        for character in text:
            if character in " \t\r\f\v":
                horizontal_space_pending = True
                pending_marks = marks
                continue
            if character == "\n":
                if characters and characters[-1][0] == " ":
                    characters.pop()
                characters.append(("\n", []))
                horizontal_space_pending = False
                pending_marks = []
                continue
            if horizontal_space_pending and characters and characters[-1][0] != "\n":
                characters.append((" ", pending_marks))
            characters.append((character, marks))
            horizontal_space_pending = False
            pending_marks = []
    while characters and characters[0][0].isspace():
        characters.pop(0)
    while characters and characters[-1][0].isspace():
        characters.pop()

    nodes: List[Dict[str, object]] = []
    for character, marks in characters:
        if character == "\n":
            nodes.append({"type": "hardBreak"})
            continue
        if nodes and nodes[-1].get("type") == "text" and nodes[-1].get("marks", []) == marks:
            nodes[-1]["text"] = f"{nodes[-1]['text']}{character}"
            continue
        node: Dict[str, object] = {"type": "text", "text": character}
        if marks:
            node["marks"] = marks
        nodes.append(node)
    return nodes


def _rich_text_plain_text(node: Dict[str, object]) -> str:
    if node.get("type") == "text":
        return str(node.get("text") or "")
    if node.get("type") == "hardBreak":
        return "\n"
    content = node.get("content")
    if not isinstance(content, list):
        return ""
    return "".join(
        _rich_text_plain_text(child)
        for child in content
        if isinstance(child, dict)
    )


def _paragraph_text(paragraph_element: ElementTree.Element) -> str:
    parts: List[str] = []
    for element in paragraph_element.iter():
        if element.tag == _w("t"):
            parts.append(element.text or "")
        elif element.tag == _w("tab"):
            parts.append(" ")
        elif element.tag in {_w("br"), _w("cr")}:
            parts.append("\n")
    return _normalize_text("".join(parts))


def _read_core_title(archive: zipfile.ZipFile) -> str:
    try:
        core_xml = archive.read("docProps/core.xml")
    except KeyError:
        return ""
    root = ElementTree.fromstring(core_xml)
    title_element = root.find("dc:title", NS)
    if title_element is None:
        return ""
    return _normalize_text(title_element.text or "")


def _read_word_notes(
    archive: zipfile.ZipFile,
    part_name: str,
    note_kind: str,
) -> Dict[str, str]:
    try:
        root = ElementTree.fromstring(archive.read(part_name))
    except KeyError:
        return {}
    notes: Dict[str, str] = {}
    for note_element in root.findall(f"w:{note_kind}", NS):
        note_id = note_element.get(_w("id"), "")
        if not note_id or note_id.startswith("-"):
            continue
        text = "\n".join(
            paragraph_text
            for paragraph_text in (
                _paragraph_text(paragraph)
                for paragraph in note_element.findall(".//w:p", NS)
            )
            if paragraph_text
        )
        if text:
            notes[note_id] = text
    return notes


def _first_non_empty_text(paragraphs: List[ProtocolParagraph]) -> str:
    for paragraph in paragraphs:
        if paragraph.text:
            return paragraph.text
    return ""


def _normalize_text(text: str) -> str:
    collapsed = re.sub(r"[ \t\r\f\v]+", " ", text)
    collapsed = re.sub(r" *\n *", "\n", collapsed)
    return collapsed.strip()


def _w(local_name: str) -> str:
    return f"{{{WORD_NS}}}{local_name}"
