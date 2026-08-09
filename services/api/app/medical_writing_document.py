from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from packages.contracts.workbench_contracts import (
    ApprovalState,
    ProtocolDocument,
    ProtocolSection,
    StructuredTableRole,
)

from .medical_writing_manifest import (
    DEFAULT_WRITING_PACKAGES,
    WRITING_PACKAGE_IDS_BY_PROJECT,
    WritingPackageConfig,
    _extract_protocol_metadata,
)
from .protocol_text_extractor import (
    ProtocolParagraph,
    ProtocolEmbeddedImage,
    ProtocolTable,
    ProtocolTextDocument,
    parse_protocol_docx,
)


HEADING_STYLE_RE = re.compile(r"(?:heading|title|标题)", re.IGNORECASE)
SCHEDULE_OF_ACTIVITIES_HEADING_RE = re.compile(
    r"^(?:表\s*\d+(?:[.-]\d+)*\s*)?(?:研究|试验|活动)流程表$|^活动时间表$|^schedule\s+of\s+activities$",
    re.IGNORECASE,
)
PROTOCOL_SYNOPSIS_HEADING_RE = re.compile(
    r"^(?:方案|研究|试验)?(?:概要|摘要)$",
    re.IGNORECASE,
)
DOCUMENT_CONTROL_HEADINGS = {
    "方案修订记录",
    "文件版本历史",
    "缩略语",
    "缩略语表",
    "缩略语列表和术语定义",
    "术语定义",
}


@dataclass(frozen=True)
class _SourceBlock:
    kind: str
    body_order: int
    paragraph: Optional[ProtocolParagraph] = None
    table: Optional[ProtocolTable] = None
    image: Optional[ProtocolEmbeddedImage] = None
    table_cell_rich_text: Dict[str, Dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True)
class _LoadedWritingDocument:
    source_signature: str
    document: ProtocolTextDocument
    session: ProtocolDocument
    section_blocks: Dict[str, List[_SourceBlock]]


def _imported_section_semantics(heading: str) -> Dict[str, object]:
    normalized = re.sub(r"\s+", " ", heading).strip()
    if SCHEDULE_OF_ACTIVITIES_HEADING_RE.fullmatch(normalized):
        return {
            "ich_m11_anchor": "1.3",
            "template_node_id": "m11_1_3",
            "node_kind": "schedule_of_activities",
            "interaction_types": ["schedule_of_activities_editor"],
        }
    if PROTOCOL_SYNOPSIS_HEADING_RE.fullmatch(normalized):
        return {
            "ich_m11_anchor": "1.1",
            "template_node_id": "m11_1_1",
            "node_kind": "protocol_synopsis",
            "interaction_types": ["synopsis_editor", "structured_table"],
        }
    return {
        "ich_m11_anchor": "",
        "template_node_id": "",
        "node_kind": "section",
        "interaction_types": [],
    }


def _source_table_role(
    section: ProtocolSection,
    source_block: _SourceBlock,
) -> StructuredTableRole:
    interactions = set(section.interaction_types)
    normalized_heading = re.sub(r"\s+", "", section.heading).strip()
    caption = source_block.table.caption if source_block.table is not None else None
    normalized_caption = re.sub(r"\s+", "", caption.text).strip() if caption else ""
    if normalized_caption in DOCUMENT_CONTROL_HEADINGS:
        return StructuredTableRole.DOCUMENT_CONTROL
    if section.node_kind == "front_matter" or "front_matter_editor" in interactions:
        return StructuredTableRole.LAYOUT
    if section.node_kind == "protocol_synopsis" or "synopsis_editor" in interactions:
        return StructuredTableRole.PROTOCOL_SYNOPSIS
    if normalized_heading in DOCUMENT_CONTROL_HEADINGS:
        return StructuredTableRole.DOCUMENT_CONTROL
    return StructuredTableRole.BODY_CONTENT


class MedicalWritingDocumentService:
    """Read-only editable-session baseline built directly from original protocol DOCX files."""

    def __init__(self, packages: List[WritingPackageConfig] | None = None):
        package_list = packages or DEFAULT_WRITING_PACKAGES
        self._packages = {package.package_id: package for package in package_list}
        self._cache: Dict[str, _LoadedWritingDocument] = {}

    def document_session(self, project_id: str) -> ProtocolDocument:
        loaded = self._load(project_id)
        return loaded.session.model_copy(deep=True)

    def has_project_configuration(self, project_id: str) -> bool:
        package_ids = WRITING_PACKAGE_IDS_BY_PROJECT.get(project_id)
        return bool(
            package_ids
            and len(package_ids) == 1
            and next(iter(package_ids)) in self._packages
        )

    def original_protocol_path(self, project_id: str):
        """Return the immutable DOCX source used by an imported writing project."""

        return self._config_for_project(project_id).protocol_path

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        loaded = self._load(project_id)
        section = next(
            (candidate for candidate in loaded.session.sections if candidate.section_id == section_id),
            None,
        )
        if section is None:
            raise KeyError(f"medical writing section not found: {section_id}")

        blocks = [
            _serialize_source_block(
                section_id,
                source_block,
                order,
                table_role=_source_table_role(section, source_block),
            )
            for order, source_block in enumerate(loaded.section_blocks[section_id])
        ]
        return section.model_copy(update={"content_blocks": blocks}, deep=True)

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        session = self.document_session(project_id)
        return session.model_copy(
            update={
                "sections": [self.section(project_id, section.section_id) for section in session.sections]
            },
            deep=True,
        )

    def _load(self, project_id: str) -> _LoadedWritingDocument:
        config = self._config_for_project(project_id)
        try:
            content = config.protocol_path.read_bytes()
        except FileNotFoundError as exc:
            raise FileNotFoundError("original protocol source is unavailable") from exc
        signature = hashlib.sha256(content).hexdigest()
        cached = self._cache.get(project_id)
        if cached and cached.source_signature == signature:
            return cached

        document = parse_protocol_docx(config.protocol_path.name, content)
        metadata = _extract_protocol_metadata(document, config)
        project_token = _identifier_token(project_id)
        document_id = f"mwdoc_{project_token}_{signature[:16]}"
        headings = _structured_headings(document)
        if not headings:
            raise ValueError("original protocol has no Word-structured section headings")

        sections: List[ProtocolSection] = []
        section_blocks: Dict[str, List[_SourceBlock]] = {}
        parent_stack: List[tuple[int, str]] = []
        document_end = _document_body_end(document)
        preamble_blocks = _blocks_for_range(
            document,
            0,
            headings[0][0].body_order,
        )
        if preamble_blocks:
            preamble_key = hashlib.sha256(
                (
                    "document-preamble|"
                    + "|".join(
                        f"{block.kind}:{block.body_order}" for block in preamble_blocks
                    )
                ).encode("utf-8")
            ).hexdigest()[:12]
            preamble_section_id = (
                f"mwsec_{project_token}_{signature[:12]}_{preamble_key}"
            )
            section_blocks[preamble_section_id] = preamble_blocks
            sections.append(
                ProtocolSection(
                    section_id=preamble_section_id,
                    document_id=document_id,
                    parent_id=None,
                    heading="文档封面与前置内容",
                    ich_m11_anchor="",
                    template_node_id="ich_m11_front_matter",
                    node_kind="front_matter",
                    interaction_types=["front_matter_editor"],
                    completion_status="source_imported_unverified",
                    approval_state=ApprovalState.IN_MEDICAL_REVIEW,
                    evidence_coverage=0.0,
                    risk_count=0,
                    content_blocks=[],
                )
            )
        for order, (heading, level) in enumerate(headings):
            end_body_order = (
                headings[order + 1][0].body_order
                if order + 1 < len(headings)
                else document_end
            )
            section_key = hashlib.sha256(
                f"{heading.source_locator}|{level}|{heading.text}".encode("utf-8")
            ).hexdigest()[:12]
            section_id = f"mwsec_{project_token}_{signature[:12]}_{section_key}"
            while parent_stack and parent_stack[-1][0] >= level:
                parent_stack.pop()
            parent_id = parent_stack[-1][1] if parent_stack else None
            parent_stack.append((level, section_id))
            section_blocks[section_id] = _blocks_for_range(
                document,
                heading.body_order,
                end_body_order,
            )
            section_semantics = _imported_section_semantics(heading.text)
            sections.append(
                ProtocolSection(
                    section_id=section_id,
                    document_id=document_id,
                    parent_id=parent_id,
                    heading=heading.text,
                    ich_m11_anchor=section_semantics["ich_m11_anchor"],
                    template_node_id=section_semantics["template_node_id"],
                    node_kind=section_semantics["node_kind"],
                    interaction_types=section_semantics["interaction_types"],
                    completion_status="source_imported_unverified",
                    approval_state=ApprovalState.IN_MEDICAL_REVIEW,
                    evidence_coverage=0.0,
                    risk_count=0,
                    content_blocks=[],
                )
            )

        session = ProtocolDocument(
            document_id=document_id,
            project_id=project_id,
            template_version="word_structure_v0_2",
            protocol_id=metadata["protocol_id"],
            version=metadata["version"],
            status="source_imported_unverified",
            sections=sections,
            quality_gates=[
                {
                    "gate_id": f"{document_id}_source_traceability",
                    "label": "原始方案来源定位",
                    "status": "required",
                    "detail": "已保留DOCX段落、表格和单元格定位；证据注册、引用核验与完整性确认尚未完成。",
                },
                {
                    "gate_id": f"{document_id}_structure_review",
                    "label": "Word章节结构复核",
                    "status": "required",
                    "detail": "章节层级来自Word样式、编号和outline结构，仍需医学写作人员确认异常样式及遗漏章节。",
                },
                {
                    "gate_id": f"{document_id}_medical_approval",
                    "label": "章节确认与版本冻结",
                    "status": "required",
                    "detail": "导入正文与后续AI修订由当前医学经理确认后纳入工作副本；正式导出时生成不可变版本快照。",
                },
            ],
        )
        loaded = _LoadedWritingDocument(
            source_signature=signature,
            document=document,
            session=session,
            section_blocks=section_blocks,
        )
        self._cache[project_id] = loaded
        return loaded

    def _config_for_project(self, project_id: str) -> WritingPackageConfig:
        package_ids = WRITING_PACKAGE_IDS_BY_PROJECT.get(project_id)
        if not package_ids or len(package_ids) != 1:
            raise KeyError(f"medical writing document session not configured for project: {project_id}")
        package_id = next(iter(package_ids))
        config = self._packages.get(package_id)
        if config is None:
            raise KeyError(f"medical writing source package not configured: {package_id}")
        return config


def _structured_headings(
    document: ProtocolTextDocument,
) -> List[tuple[ProtocolParagraph, int]]:
    headings: List[tuple[ProtocolParagraph, int]] = []
    for paragraph in document.paragraphs:
        if paragraph.is_in_table or not HEADING_STYLE_RE.search(paragraph.style_name):
            continue
        level = _structural_level(paragraph)
        if level is None:
            continue
        headings.append((paragraph, level))
    return headings


def _structural_level(paragraph: ProtocolParagraph) -> Optional[int]:
    if paragraph.outline_level is not None:
        return paragraph.outline_level if 0 <= paragraph.outline_level <= 8 else None
    if (
        paragraph.ilvl is not None
        and paragraph.num_id not in {None, "0"}
        and 0 <= paragraph.ilvl <= 8
    ):
        return paragraph.ilvl
    return None


def _blocks_for_range(
    document: ProtocolTextDocument,
    start_body_order: int,
    end_body_order: int,
) -> List[_SourceBlock]:
    tables = [
        table
        for table in document.tables
        if start_body_order <= table.body_order < end_body_order
    ]
    table_owned_paragraph_locators = {
        locator
        for table in tables
        for locator in [
            (
                table.caption.source_locator
                if table.caption is not None and table.caption.review_status == "confirmed"
                else ""
            ),
            *(
                note.source_locator
                for note in table.notes
                if note.source_kind.startswith("post_table")
                and note.review_status == "confirmed"
            ),
        ]
        if locator.startswith("docx:paragraph:")
    }
    images = [
        image
        for image in document.embedded_images
        if start_body_order <= image.body_order < end_body_order
        and image.caption is not None
        and image.caption.review_status == "confirmed"
        and image.semantic_role in {"table_image", "figure"}
    ]
    image_owned_paragraph_locators = {
        image.caption.source_locator
        for image in images
        if image.caption is not None
    }
    blocks = [
        _SourceBlock(
            kind="paragraph",
            body_order=paragraph.body_order,
            paragraph=paragraph,
        )
        for paragraph in document.paragraphs
        if not paragraph.is_in_table
        and paragraph.source_locator not in table_owned_paragraph_locators
        and paragraph.source_locator not in image_owned_paragraph_locators
        and start_body_order <= paragraph.body_order < end_body_order
    ]
    blocks.extend(
        _SourceBlock(
            kind="table",
            body_order=table.body_order,
            table=table,
            table_cell_rich_text=_table_cell_rich_text(document, table),
        )
        for table in tables
    )
    blocks.extend(
        _SourceBlock(
            kind="image",
            body_order=image.body_order,
            image=image,
        )
        for image in images
    )
    return sorted(blocks, key=lambda block: block.body_order)


def _table_cell_rich_text(
    document: ProtocolTextDocument,
    table: ProtocolTable,
) -> Dict[str, Dict[str, object]]:
    paragraphs_by_cell: Dict[str, List[ProtocolParagraph]] = {
        cell.source_locator: []
        for row in table.rows
        for cell in row
    }
    for paragraph in document.paragraphs:
        if not paragraph.is_in_table or paragraph.table_index != table.table_index:
            continue
        cell_locator, separator, _ = paragraph.source_locator.rpartition(":paragraph:")
        if not separator or cell_locator not in paragraphs_by_cell:
            continue
        paragraphs_by_cell[cell_locator].append(paragraph)

    rich_text_by_cell: Dict[str, Dict[str, object]] = {}
    for cell_locator, paragraphs in paragraphs_by_cell.items():
        rich_paragraphs = [
            paragraph.rich_text
            for paragraph in sorted(paragraphs, key=lambda item: item.paragraph_index)
            if paragraph.rich_text
        ]
        if len(rich_paragraphs) == 1:
            rich_text_by_cell[cell_locator] = rich_paragraphs[0]
        elif rich_paragraphs:
            rich_text_by_cell[cell_locator] = {
                "type": "doc",
                "content": rich_paragraphs,
            }
    return rich_text_by_cell


def _serialize_source_block(
    section_id: str,
    source_block: _SourceBlock,
    order: int,
    *,
    table_role: StructuredTableRole = StructuredTableRole.UNCLASSIFIED,
) -> Dict[str, object]:
    if source_block.paragraph is not None:
        paragraph = source_block.paragraph
        return {
            "block_id": _block_id(section_id, paragraph.source_locator),
            "block_type": "heading" if order == 0 else "paragraph",
            "text": paragraph.text,
            "source_locator": paragraph.source_locator,
            "source_kind": "original_protocol_docx",
            "body_order": paragraph.body_order,
            "style_id": paragraph.style_id,
            "style_name": paragraph.style_name,
            "num_id": paragraph.num_id,
            "ilvl": paragraph.ilvl,
            "outline_level": paragraph.outline_level,
            "numbering_format": paragraph.numbering_format,
            "numbering_level_text": paragraph.numbering_level_text,
            "numbering_start": paragraph.numbering_start,
            "numbering_start_override": paragraph.numbering_start_override,
            "rich_text": paragraph.rich_text,
            "editable": False,
        }
    if source_block.image is not None:
        image = source_block.image
        caption = image.caption
        if caption is None:
            raise ValueError("medical writing source image has no confirmed caption")
        return {
            "block_id": _block_id(section_id, image.source_locator),
            "block_type": "figure",
            "figure_kind": "source_docx_image",
            "semantic_role": image.semantic_role,
            "figure_id": image.image_id,
            "image_id": image.image_id,
            "title": caption.text,
            "alt_text": image.alt_text or caption.text,
            "source_locator": image.source_locator,
            "source_kind": "original_protocol_docx",
            "body_order": image.body_order,
            "relationship_id": image.relationship_id,
            "media_part_name": image.part_name,
            "media_type": image.media_type,
            "image_base64": image.image_base64,
            "image_sha256": image.image_sha256,
            "width_emu": image.width_emu,
            "height_emu": image.height_emu,
            "source_caption": {
                "caption_id": caption.caption_id,
                "text": caption.text,
                "source_locator": caption.source_locator,
                "paragraph_index": caption.paragraph_index,
                "body_order": caption.body_order,
                "review_status": caption.review_status,
                "association_reason": caption.association_reason,
            },
            "editable": False,
        }
    if source_block.table is None:
        raise ValueError("medical writing source block has no paragraph or table")
    table = source_block.table
    caption = table.caption
    note_refs_by_cell: Dict[str, List[str]] = {}
    for note in table.notes:
        if note.target_cell_id:
            note_refs_by_cell.setdefault(note.target_cell_id, []).append(note.note_id)
    serialized_notes = [_serialize_table_note(table.table_id, note) for note in table.notes]
    return {
        "block_id": _block_id(section_id, table.source_locator),
        "block_type": "table",
        "source_locator": table.source_locator,
        "source_kind": "original_protocol_docx",
        "body_order": table.body_order,
        "table_index": table.table_index,
        "table_id": table.table_id,
        "title": caption.text if caption is not None else "",
        "table_caption": (
            {
                "caption_id": caption.caption_id,
                "text": caption.text,
                "source_locator": caption.source_locator,
                "paragraph_index": caption.paragraph_index,
                "body_order": caption.body_order,
                "review_status": caption.review_status,
                "association_reason": caption.association_reason,
            }
            if caption is not None
            else None
        ),
        "schema_version": table.schema_version,
        "header_row_count": table.header_row_count,
        "column_count": table.column_count,
        "rows": [
            [
                {
                    "cell_id": cell.cell_id,
                    "text": cell.text,
                    "source_locator": cell.source_locator,
                    "row_index": cell.row_index,
                    "cell_index": cell.cell_index,
                    "grid_column_index": cell.grid_column_index,
                    "column_span": cell.column_span,
                    "row_span": cell.row_span,
                    "vertical_merge": cell.vertical_merge,
                    "hidden": cell.hidden,
                    "merge_parent_cell_id": cell.merge_parent_cell_id,
                    "merge_parent_source_locator": cell.merge_parent_source_locator,
                    "merge_parent_row_index": cell.merge_parent_row_index,
                    "merge_parent_cell_index": cell.merge_parent_cell_index,
                    "merge_parent_grid_column_index": cell.merge_parent_grid_column_index,
                    "style_role": cell.style_role,
                    "note_refs": note_refs_by_cell.get(cell.cell_id, []),
                    **(
                        {
                            "rich_text": source_block.table_cell_rich_text[
                                cell.source_locator
                            ]
                        }
                        if cell.source_locator in source_block.table_cell_rich_text
                        else {}
                    ),
                }
                for cell in row
            ]
            for row in table.rows
        ],
        "structured_table": {
            "schema_version": "structured_table_v1",
            "version": 0,
            "domain": "generic",
            "role": table_role.value,
            "title": caption.text if caption is not None else "",
            "review_state": "ai_draft",
            "notes": serialized_notes,
            "word_layout": {},
            "source_caption": (
                {
                    "caption_id": caption.caption_id,
                    "source_locator": caption.source_locator,
                    "review_status": caption.review_status,
                    "association_reason": caption.association_reason,
                }
                if caption is not None
                else None
            ),
            "source_note_metadata": [
                {
                    "note_id": note.note_id,
                    "source_locator": note.source_locator,
                    "target_scope": note.target_scope,
                    "target_row_index": note.target_row_index,
                    "target_cell_id": note.target_cell_id,
                    "source_kind": note.source_kind,
                    "review_status": note.review_status,
                    "association_reason": note.association_reason,
                }
                for note in table.notes
            ],
        },
        "editable": False,
    }


def _serialize_table_note(table_id: str, note) -> Dict[str, object]:
    target_ids = [note.target_cell_id] if note.target_cell_id else [table_id]
    source_refs = list(
        dict.fromkeys(
            locator
            for locator in [note.source_locator, note.marker_source_locator]
            if locator
        )
    )
    return {
        "note_id": note.note_id,
        "marker": note.marker,
        "note_type": "operational",
        "text": note.text,
        "target_ids": target_ids,
        "source_refs": source_refs,
        "source_kind": note.source_kind,
        "marker_source_locator": note.marker_source_locator,
        "review_status": note.review_status,
        "association_reason": note.association_reason,
    }


def _document_body_end(document: ProtocolTextDocument) -> int:
    body_orders = [paragraph.body_order for paragraph in document.paragraphs]
    body_orders.extend(table.body_order for table in document.tables)
    return max(body_orders, default=-1) + 1


def _identifier_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not token:
        raise ValueError("medical writing project identifier is empty")
    return token


def _block_id(section_id: str, source_locator: str) -> str:
    token = hashlib.sha256(source_locator.encode("utf-8")).hexdigest()[:12]
    return f"mwblock_{section_id}_{token}"
