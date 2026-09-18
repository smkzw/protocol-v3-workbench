from __future__ import annotations

import hashlib
import io
import re
import zipfile
from xml.etree import ElementTree

from packages.contracts.workbench_contracts import (
    WritingReferenceDocumentArtifact,
    WritingReferenceExtractedSpan,
    WritingReferenceExtractionResult,
)
from .writing_reference_m11 import m11_anchor as _m11_anchor


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
DOCX_MAIN_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
DOCX_PARSER_NAME = "OOXML document.xml"
DOCX_PARSER_VERSION = "docx_xml_v1"
DOCX_MAPPING_VERSION = "m11map_v5"
MAX_DOCUMENT_XML_BYTES = 64 * 1024 * 1024
NS = {"w": WORD_NS}

def extract_docx_sections(
    payload: bytes,
    artifact: WritingReferenceDocumentArtifact,
) -> WritingReferenceExtractionResult:
    """Extract ordered paragraph and table-row spans from a registered DOCX artifact."""
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != artifact.content_sha256:
        raise ValueError("document content hash does not match registered artifact")
    if len(payload) != artifact.actual_size:
        raise ValueError("document size does not match registered artifact")

    document_xml = _read_docx_document_xml(payload)
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise ValueError("DOCX word/document.xml is malformed") from exc
    body = root.find("w:body", NS)
    if body is None:
        raise ValueError("DOCX document has no word body")

    extraction_revision = (
        f"{DOCX_PARSER_VERSION}_{DOCX_MAPPING_VERSION}_{artifact.content_sha256}"
    )
    logical_page = 1
    spans: list[WritingReferenceExtractedSpan] = []
    current_heading = ""
    current_anchor = "unmapped"

    for child in body:
        if child.tag == _w("p"):
            candidates = [("paragraph", child, _paragraph_text(child))]
        elif child.tag == _w("tbl"):
            candidates = [
                ("table_row", row, _table_row_text(row))
                for row in child.findall("./w:tr", NS)
            ]
        else:
            continue

        for block_kind, element, text_value in candidates:
            if not text_value or not text_value.strip():
                continue
            anchor_candidate = _m11_anchor(text_value)
            looks_heading = _looks_like_section_heading(
                text_value,
                has_heading_style=(
                    block_kind == "paragraph" and _has_heading_style(element)
                ),
                is_bold=_is_bold(element),
            )
            if block_kind == "paragraph" and (
                looks_heading
                or (anchor_candidate != "unmapped" and len(text_value) <= 40)
            ):
                current_heading = text_value
                current_anchor = anchor_candidate

            span_anchor = (
                current_anchor
                if current_anchor != "unmapped"
                else anchor_candidate
                if block_kind == "table_row"
                else "unmapped"
            )

            block_index = len(spans)
            text_hash = hashlib.sha256(text_value.encode("utf-8")).hexdigest()
            span_id = "wref_span_" + hashlib.sha256(
                (
                    f"{artifact.artifact_id}|{extraction_revision}|{logical_page}|"
                    f"{block_index}|{text_hash}"
                ).encode("utf-8")
            ).hexdigest()[:24]
            spans.append(
                WritingReferenceExtractedSpan(
                    span_id=span_id,
                    project_id=artifact.project_id,
                    artifact_id=artifact.artifact_id,
                    extraction_revision=extraction_revision,
                    physical_page=logical_page,
                    block_index=block_index,
                    source_locator=(
                        f"upload:{artifact.nct_id}:{artifact.artifact_id}:"
                        f"p{logical_page}:b{block_index}"
                    ),
                    section_heading=current_heading,
                    ich_m11_anchor=span_anchor,
                    source_text=text_value,
                    source_text_sha256=text_hash,
                )
            )

    if not spans:
        raise ValueError("DOCX document contains no extractable text")

    return WritingReferenceExtractionResult(
        artifact_id=artifact.artifact_id,
        project_id=artifact.project_id,
        extraction_revision=extraction_revision,
        parser_name=DOCX_PARSER_NAME,
        parser_version=DOCX_PARSER_VERSION,
        page_count=1,
        zero_text_pages=[],
        status="pending_visual_and_medical_structure_review",
        spans=spans,
    )


def _read_docx_document_xml(payload: bytes) -> bytes:
    if not payload:
        raise ValueError("DOCX payload is empty")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = archive.namelist()
            if names.count("[Content_Types].xml") != 1:
                raise ValueError("DOCX package must contain one [Content_Types].xml")
            if names.count("word/document.xml") != 1:
                raise ValueError("DOCX package must contain one word/document.xml")
            document_info = archive.getinfo("word/document.xml")
            if document_info.file_size > MAX_DOCUMENT_XML_BYTES:
                raise ValueError("DOCX word/document.xml exceeds the supported size")
            content_types_xml = archive.read("[Content_Types].xml")
            document_xml = archive.read(document_info)
    except zipfile.BadZipFile as exc:
        raise ValueError("payload is not a valid DOCX ZIP package") from exc
    except (NotImplementedError, RuntimeError) as exc:
        raise ValueError("DOCX ZIP package cannot be read") from exc

    if len(document_xml) > MAX_DOCUMENT_XML_BYTES:
        raise ValueError("DOCX word/document.xml exceeds the supported size")
    _validate_content_types(content_types_xml)
    return document_xml


def _validate_content_types(content_types_xml: bytes) -> None:
    try:
        root = ElementTree.fromstring(content_types_xml)
    except ElementTree.ParseError as exc:
        raise ValueError("DOCX [Content_Types].xml is malformed") from exc
    override_tag = f"{{{CONTENT_TYPES_NS}}}Override"
    is_docx = any(
        element.get("PartName") == "/word/document.xml"
        and element.get("ContentType") == DOCX_MAIN_CONTENT_TYPE
        for element in root.iter(override_tag)
    )
    if not is_docx:
        raise ValueError("ZIP package is not an OOXML DOCX document")


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    chunks: list[str] = []
    for element in paragraph.iter():
        if element.tag == _w("t"):
            chunks.append(element.text or "")
        elif element.tag == _w("tab"):
            chunks.append("\t")
        elif element.tag in {_w("br"), _w("cr")}:
            chunks.append("\n")
    return "".join(chunks).strip()


def _table_row_text(row: ElementTree.Element) -> str:
    cells = [_table_cell_text(cell) for cell in row.findall("./w:tc", NS)]
    if not any(cells):
        return ""
    return "\t".join(cells)


def _table_cell_text(cell: ElementTree.Element) -> str:
    paragraphs = [
        text
        for paragraph in cell.findall(".//w:p", NS)
        if (text := _paragraph_text(paragraph))
    ]
    return "\n".join(paragraphs)


def _looks_like_section_heading(
    text: str,
    *,
    has_heading_style: bool,
    is_bold: bool,
) -> bool:
    if len(text) > 160:
        return False
    if has_heading_style or is_bold:
        return True
    return bool(
        re.match(
            r"^(?:(?:section|appendix)\s+)?(?:\d+(?:\.\d+)*|[A-Z][A-Z0-9 .:/()&,-]{4,})\b",
            text,
        )
    )


def _has_heading_style(paragraph: ElementTree.Element) -> bool:
    style = paragraph.find("w:pPr/w:pStyle", NS)
    if style is None:
        return False
    style_id = (style.get(_w("val")) or "").casefold().replace(" ", "")
    return style_id.startswith(("heading", "标题")) or style_id in {"title", "subtitle"}


def _is_bold(element: ElementTree.Element) -> bool:
    false_values = {"0", "false", "off", "no"}
    return any(
        (bold.get(_w("val")) or "true").casefold() not in false_values
        for bold in element.iter(_w("b"))
    )


def _w(local_name: str) -> str:
    return f"{{{WORD_NS}}}{local_name}"
