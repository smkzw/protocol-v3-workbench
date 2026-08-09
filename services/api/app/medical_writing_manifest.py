from __future__ import annotations

import hashlib
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree

from packages.contracts.workbench_contracts import (
    MedicalWritingManifestResult,
    ProtocolDocument,
    WritingQualityGate,
    WritingSectionSummary,
    WritingSourceDocumentSummary,
    WritingSourcePackageSummary,
    WritingTableSummary,
)

from .ai_gateway import ai_gateway_status_from_env
from .protocol_text_extractor import ProtocolTable, ProtocolTextDocument, parse_protocol_docx


RUX_PROTOCOL_DOCX = Path(
    "/Users/smkzw/Documents/康哲项目资料/Ruxolitinib-AD/CFDI Inspection/RUX-03-002-自查文件包-20260107/10-临床试验重要文件/1-临床试验方案/V1.3版-2024.8.14/磷酸芦可替尼乳膏-AD3期临床研究方案V1.3-clean-20240814.docx"
)
D001_PROTOCOL_DOCX = Path(
    "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx"
)
MY008_PNH_3_01_PROTOCOL_DOCX = Path(
    "/Users/smkzw/Documents/朗来项目资料/MY008治疗PNH/3-01（MM外包）/方案/V1.1方案/"
    "（缺含研究者签字页方案）MY008211A-PNH-3-01-V1.1-通用版-2024.11.24-clean/研究方案/"
    "MY008211A-PNH-3-01_研究方案_V1.1_2025.1.7clean.docx"
)
TEMPLATE_ROOT = Path("/Users/smkzw/Documents/康哲项目资料/模版/方案模版")


@dataclass(frozen=True)
class WritingPackageConfig:
    package_id: str
    package_label: str
    project_code: str
    indication: str
    source_root_label: str
    package_role: str
    protocol_path: Path


DEFAULT_WRITING_PACKAGES = [
    WritingPackageConfig(
        package_id="rux_03_002_protocol_writing",
        package_label="RUX-03-002研究方案写作资料包",
        project_code="RUX-03-002",
        indication="特应性皮炎",
        source_root_label="RUX-03-002原始研究方案DOCX",
        package_role="已完成方案解析样本与医学写作源文档",
        protocol_path=RUX_PROTOCOL_DOCX,
    ),
    WritingPackageConfig(
        package_id="cms_d001_protocol_writing",
        package_label="CMS-D001研究方案写作资料包",
        project_code="D001-02-002",
        indication="中度至重度斑块状银屑病",
        source_root_label="D001原始研究方案DOCX",
        package_role="入排审核和方案写作联动样本",
        protocol_path=D001_PROTOCOL_DOCX,
    ),
    WritingPackageConfig(
        package_id="my008_pnh_3_01_protocol_writing",
        package_label="MY008211A-PNH-3-01研究方案写作资料包",
        project_code="MY008211A-PNH-3-01",
        indication="阵发性睡眠性血红蛋白尿",
        source_root_label="MY008 PNH 3-01原始研究方案DOCX",
        package_role="研究方案V1.1清洁版与医学写作源文档",
        protocol_path=MY008_PNH_3_01_PROTOCOL_DOCX,
    ),
]

WRITING_PACKAGE_IDS_BY_PROJECT = {
    "proj_rux_03_002": {"rux_03_002_protocol_writing"},
    "proj_d001": {"cms_d001_protocol_writing"},
    "proj_my008_pnh_3_01": {"my008_pnh_3_01_protocol_writing"},
}


class MedicalWritingManifestService:
    def __init__(self, packages: Optional[List[WritingPackageConfig]] = None):
        self.packages = packages or DEFAULT_WRITING_PACKAGES

    def build_manifest(self, project_id: str) -> MedicalWritingManifestResult:
        generated_at = datetime.now(timezone.utc)
        package_ids = WRITING_PACKAGE_IDS_BY_PROJECT.get(project_id)
        if package_ids is None:
            raise KeyError(f"medical_writing not configured for project: {project_id}")
        package_summaries = [self._build_package(config) for config in self.packages if config.package_id in package_ids]
        template_count = len(list(TEMPLATE_ROOT.glob("*.docx"))) if TEMPLATE_ROOT.exists() else 0
        return MedicalWritingManifestResult(
            project_id=project_id,
            generated_at=generated_at,
            package_count=len(package_summaries),
            total_documents=sum(len(package.documents) for package in package_summaries),
            total_sections=sum(len(package.sections) for package in package_summaries),
            total_tables=sum(len(package.tables) for package in package_summaries),
            total_source_spans=sum(package.source_span_count for package in package_summaries),
            quality_gate_count=sum(len(package.quality_gates) for package in package_summaries),
            packages=package_summaries,
            parser_notes=[
                "P0从真实研究方案DOCX重新解析段落、表格和source locator，不使用已解构方案或既有写作结论作为生产输入。",
                "当前章节树为启发式候选；未解析或未映射内容不得视为不存在，仍需医学确认和来源定位。",
                f"方案模板目录已登记{template_count}个DOCX模板；模板只作为结构参照，竞品/既有方案不得直接复用为正式条款。",
                "AI修订建议只能作为正式内容候选，需作者选择/确认后才可保存；独立AI provider未配置时AI生成受阻，不生成生产写作正文。",
            ],
        )

    def build_greenfield_manifest(
        self,
        project_id: str,
        document: ProtocolDocument,
        baseline_state: Dict[str, object],
        *,
        project_code: str,
        indication: str,
    ) -> MedicalWritingManifestResult:
        sections: List[WritingSectionSummary] = []
        tables: List[WritingTableSummary] = []
        source_span_count = 0
        for section_index, section in enumerate(document.sections):
            paragraph_count = sum(
                block.get("block_type") in {"heading", "paragraph"}
                for block in section.content_blocks
            )
            section_tables = [
                block
                for block in section.content_blocks
                if block.get("block_type") == "table"
            ]
            source_span_count += len(section.content_blocks)
            sections.append(
                WritingSectionSummary(
                    section_id=section.section_id,
                    source_document_id=document.document_id,
                    section_number=str(section_index + 1),
                    heading=section.heading,
                    heading_level=1,
                    anchor_path=f"greenfield:section:{section.section_id}",
                    source_locator=f"greenfield:section:{section.section_id}",
                    paragraph_count=paragraph_count,
                    table_count=len(section_tables),
                    ich_m11_area=section.ich_m11_anchor,
                    writing_status="绿地候选已建立，待作者确认",
                    evidence_status="项目事实与来源待逐项补齐",
                    medical_approval_status="候选/待作者确认",
                    ai_task_ready=True,
                    extraction_confidence=1.0,
                    requires_human_mapping=False,
                    evidence_coverage_percent=0,
                    risk_count=section.risk_count,
                    source_refs=[
                        str(block.get("source_locator") or "")
                        for block in section.content_blocks
                        if block.get("source_locator")
                    ],
                )
            )
            for block in section_tables:
                rows = block.get("rows", [])
                tables.append(
                    WritingTableSummary(
                        table_id=str(block.get("table_id") or block.get("block_id") or ""),
                        source_document_id=document.document_id,
                        table_index=len(tables),
                        source_locator=str(block.get("source_locator") or ""),
                        title_hint=str(block.get("title") or ""),
                        row_count=len(rows) if isinstance(rows, list) else 0,
                        column_count=int(block.get("column_count") or 0),
                        nonempty_cell_count=sum(
                            bool(str(cell.get("text") or "").strip())
                            for row in rows
                            if isinstance(row, list)
                            for cell in row
                            if isinstance(cell, dict)
                        ),
                        role_hint="绿地工作副本结构化表格",
                        parser_status="structured",
                        linked_section_id=section.section_id,
                    )
                )

        quality_gates = [
            WritingQualityGate(
                gate_id=str(gate.get("gate_id") or ""),
                gate_label=str(gate.get("label") or ""),
                status=str(gate.get("status") or "required"),
                owner="医学经理/医学总监",
                detail=str(gate.get("detail") or ""),
                source_refs=[document.document_id],
            )
            for gate in document.quality_gates
        ]
        blockers = int(baseline_state.get("approval_blocker_count") or 0)
        document_summary = WritingSourceDocumentSummary(
            document_id=document.document_id,
            document_type=document.document_type,
            project_code=project_code,
            public_title=f"{document.protocol_id} {document.version} 绿地方案工作稿",
            source_package=f"{document.document_id}_greenfield_package",
            relative_path="版本化项目决策基线",
            file_format="structured_project_decisions",
            parser_status="绿地候选已建立",
            paragraph_count=sum(item.paragraph_count for item in sections),
            table_count=len(tables),
            span_count=source_span_count,
            section_count=len(sections),
            protocol_identifier=document.protocol_id,
            protocol_version=document.version,
            indication_hint=indication,
            role_hint="绿地研究方案候选工作稿（待作者确认）",
        )
        package = WritingSourcePackageSummary(
            package_id=f"{document.document_id}_greenfield_package",
            package_label=f"{document.protocol_id} 绿地方案写作基线",
            project_code=project_code,
            indication=indication,
            source_root_label="结构化项目决策与章节脚手架",
            package_role="从零方案写作的版本化候选基线",
            source_span_count=source_span_count,
            evidence_coverage_percent=0,
            pending_medical_approval_count=len(sections),
            blocking_gate_count=blockers,
            can_generate_review_docx=True,
            formal_export_status="全部章节作者确认并冻结当前版本后方可生成正式Word",
            ai_revision_boundary=(
                "AI仅可基于当前工作副本、已登记项目事实和当前章节有来源定位的证据生成候选；"
                "证据不足或未决项目决策不得由模型自行补齐。"
            ),
            documents=[document_summary],
            sections=sections,
            tables=tables,
            quality_gates=quality_gates,
            parser_warnings=[
                f"当前有{blockers}项项目决策会阻断作者确认/版本冻结。"
                if blockers
                else "当前登记的版本冻结阻断性项目决策均已解决。"
            ],
        )
        return MedicalWritingManifestResult(
            project_id=project_id,
            generated_at=datetime.now(timezone.utc),
            package_count=1,
            total_documents=1,
            total_sections=len(sections),
            total_tables=len(tables),
            total_source_spans=source_span_count,
            quality_gate_count=len(quality_gates),
            packages=[package],
            parser_notes=[
                "当前资料包来自结构化项目决策，不是导入的原始DOCX。",
                "章节脚手架和AI修订均为候选，需作者确认后写入/冻结；项目事实、证据和未决项保持分层。",
                "草稿Word可随时生成；正式Word仍要求全部章节作者确认并存在不可变冻结快照。",
            ],
        )

    def _build_package(self, config: WritingPackageConfig) -> WritingSourcePackageSummary:
        warnings: List[str] = []
        document: Optional[ProtocolTextDocument] = None
        if not config.protocol_path.exists():
            warnings.append(f"{config.protocol_path.name}不存在，无法解析DOCX正文。")
        else:
            try:
                document = parse_protocol_docx(config.protocol_path)
            except ValueError as exc:
                warnings.append(f"{config.protocol_path.name}解析失败：{exc}")

        if document is None:
            documents: List[WritingSourceDocumentSummary] = [
                _document_summary_for_missing(config, warnings)
            ]
            sections: List[WritingSectionSummary] = []
            tables: List[WritingTableSummary] = []
        else:
            document_id = f"{config.package_id}_doc_protocol"
            sections = _build_section_candidates(config, document, document_id, warnings)
            tables = _build_table_summaries(config, document, document_id, sections, warnings)
            documents = [_build_document_summary(config, document, document_id, len(sections))]

        ai_status = ai_gateway_status_from_env()
        quality_gates = _build_quality_gates(config, documents, sections, tables, warnings, ai_status)
        blocking_gate_count = sum(1 for gate in quality_gates if gate.status in {"blocked", "warning"})
        coverage = _package_coverage(sections)
        return WritingSourcePackageSummary(
            package_id=config.package_id,
            package_label=config.package_label,
            project_code=config.project_code,
            indication=config.indication,
            source_root_label=config.source_root_label,
            package_role=config.package_role,
            source_span_count=sum(document.span_count for document in documents),
            evidence_coverage_percent=coverage,
            revision_thread_count=sum(section.revision_thread_count for section in sections),
            pending_medical_approval_count=sum(1 for section in sections if section.medical_approval_status != "作者已确认"),
            blocking_gate_count=blocking_gate_count,
            can_generate_review_docx=bool(documents and documents[0].parser_status == "正文已解析"),
            formal_export_status="不可生成正式导出包",
            ai_revision_boundary=(
                "AI修订建议只能作为正式内容候选，需作者确认后才可写入或冻结当前版本；"
                "证据不足、来源未定位或独立AI不可用时生成受阻。"
            ),
            documents=documents,
            sections=sections,
            tables=tables,
            quality_gates=quality_gates,
            parser_warnings=warnings,
        )


def _document_summary_for_missing(
    config: WritingPackageConfig,
    warnings: List[str],
) -> WritingSourceDocumentSummary:
    return WritingSourceDocumentSummary(
        document_id=f"{config.package_id}_doc_protocol",
        document_type="clinical_study_protocol",
        project_code=config.project_code,
        public_title=config.protocol_path.name,
        source_package=config.package_id,
        relative_path=config.protocol_path.name,
        file_format=config.protocol_path.suffix.lower() or "unknown",
        parser_status="仅文件级登记",
        role_hint="研究方案原始文件",
        protocol_identifier=config.project_code,
    )


def _build_document_summary(
    config: WritingPackageConfig,
    document: ProtocolTextDocument,
    document_id: str,
    section_count: int,
) -> WritingSourceDocumentSummary:
    metadata = _extract_protocol_metadata(document, config)
    docx_features = _inspect_docx_features(config.protocol_path)
    return WritingSourceDocumentSummary(
        document_id=document_id,
        document_type="clinical_study_protocol",
        project_code=config.project_code,
        public_title=metadata["title"],
        source_package=config.package_id,
        relative_path=config.protocol_path.name,
        file_format="docx",
        parser_status="正文已解析",
        content_hash=_file_sha256(config.protocol_path),
        size_bytes=config.protocol_path.stat().st_size,
        paragraph_count=len(document.paragraphs),
        table_count=len(document.tables),
        span_count=len(document.spans),
        section_count=section_count,
        image_count=docx_features["image_count"],
        has_revision_marks=bool(docx_features["revision_mark_count"]),
        has_fields=bool(docx_features["field_count"]),
        style_summary=docx_features["style_summary"],
        protocol_identifier=metadata["protocol_id"],
        protocol_version=metadata["version"],
        protocol_date=metadata["date"],
        indication_hint=config.indication,
        role_hint="研究方案原文DOCX",
    )


def _build_section_candidates(
    config: WritingPackageConfig,
    document: ProtocolTextDocument,
    document_id: str,
    warnings: List[str],
) -> List[WritingSectionSummary]:
    anchors = _section_anchor_candidates(document)
    if not anchors:
        warnings.append("未识别到稳定章节候选；当前仅能进行文件/段落级来源定位。")
        return []

    sections: List[WritingSectionSummary] = []
    for order, (paragraph_index, number, heading, level, locator, confidence) in enumerate(anchors[:80]):
        next_index = anchors[order + 1][0] if order + 1 < len(anchors) else len(document.paragraphs)
        section_paragraphs = [
            paragraph for paragraph in document.paragraphs
            if paragraph_index <= paragraph.paragraph_index < next_index
        ]
        table_count = sum(
            1
            for table in document.tables
            if any(
                cell.text and paragraph_index <= _locator_paragraph_index(cell.source_locator, document) < next_index
                for row in table.rows
                for cell in row
            )
        )
        preview = "已登记source locator；正文预览需按章节权限在详情中查看。"
        ich_area = _ich_anchor_hint(heading)
        coverage = 55 if ich_area else 35
        if confidence < 0.75:
            coverage = min(coverage, 30)
        sections.append(
            WritingSectionSummary(
                section_id=f"{config.package_id}_sec_{order + 1:03d}",
                source_document_id=document_id,
                section_number=number,
                heading=heading,
                heading_level=level,
                anchor_path=f"docx:section_candidate:{order + 1:03d}",
                source_locator=locator,
                paragraph_count=len(section_paragraphs),
                table_count=table_count,
                word_count=sum(len(paragraph.text) for paragraph in section_paragraphs),
                ich_m11_area=ich_area,
                writing_status="章节候选待作者确认",
                evidence_status="待补来源定位" if coverage < 60 else "来源定位部分完成",
                medical_approval_status="候选/待作者确认",
                ai_task_ready=confidence >= 0.75,
                extraction_confidence=round(confidence, 2),
                requires_human_mapping=True,
                evidence_coverage_percent=coverage,
                revision_thread_count=0,
                risk_count=1 if coverage < 60 else 0,
                text_preview=preview,
                source_refs=[locator],
            )
        )
    if len(anchors) > len(sections):
        warnings.append("章节候选超过80项，P0只返回前80项；后续需按目录/样式/编号树分页加载。")
    warnings.append("章节候选由文本和locator启发式生成，未读取完整Word样式/编号树；需人工确认后才能作为正式章节树。")
    return sections


def _build_table_summaries(
    config: WritingPackageConfig,
    document: ProtocolTextDocument,
    document_id: str,
    sections: List[WritingSectionSummary],
    warnings: List[str],
) -> List[WritingTableSummary]:
    summaries: List[WritingTableSummary] = []
    for table in document.tables:
        row_count = len(table.rows)
        column_count = max((len(row) for row in table.rows), default=0)
        nonempty_count = sum(1 for row in table.rows for cell in row if cell.text.strip())
        headers = _table_headers(table)
        title_hint = _table_title_hint(table, document)
        role_hint = _table_role_hint(title_hint, headers)
        linked_section_id = _linked_section_id(table, sections, document)
        quality_notes = []
        if column_count >= 8:
            quality_notes.append("宽表需内部横向滚动；疑似SoA/研究流程表时需专用结构化解析。")
        if row_count >= 30:
            quality_notes.append("长表P0仅登记locator和表头摘要，未完成语义还原。")
        if _has_sparse_rows(table):
            quality_notes.append("存在空白/合并样式风险，需核对Word合并单元格。")
        summaries.append(
            WritingTableSummary(
                table_id=f"{config.package_id}_tbl_{table.table_index:03d}",
                source_document_id=document_id,
                table_index=table.table_index,
                source_locator=table.source_locator,
                title_hint=title_hint,
                row_count=row_count,
                column_count=column_count,
                nonempty_cell_count=nonempty_count,
                merge_detected=_has_sparse_rows(table),
                headers=headers[:12],
                role_hint=role_hint,
                parser_status="parsed_with_structure_warning" if quality_notes else "parsed",
                linked_section_id=linked_section_id,
                quality_notes=quality_notes,
            )
        )
    if any(table.column_count >= 8 for table in summaries):
        warnings.append("研究流程表/宽表已识别，但P0尚未恢复全部合并单元格、横向时间轴和Word表格样式。")
    return summaries


def _build_quality_gates(
    config: WritingPackageConfig,
    documents: List[WritingSourceDocumentSummary],
    sections: List[WritingSectionSummary],
    tables: List[WritingTableSummary],
    warnings: List[str],
    ai_status,
) -> List[WritingQualityGate]:
    parsed = bool(documents and documents[0].parser_status == "正文已解析")
    gate_items = [
        WritingQualityGate(
            gate_id=f"{config.package_id}_source_binding",
            gate_label="来源绑定完整性",
            status="ok" if parsed else "blocked",
            owner="医学经理+文档管理员",
            detail=(
                "真实研究方案DOCX已解析为段落、表格和source locator。"
                if parsed else
                "已登记文件名、哈希和上传记录，但未能解析DOCX正文；当前不能用于AI写作、证据覆盖或章节完整性判断。"
            ),
            source_refs=[documents[0].relative_path] if documents else [],
        ),
        WritingQualityGate(
            gate_id=f"{config.package_id}_docx_parse",
            gate_label="DOCX解析完整性通过",
            status="warning" if warnings else "ok",
            owner="系统+医学写作",
            detail=(
                "已解析部分段落/表格；图片、嵌入对象、批注、修订痕迹或复杂表格可能未形成可引用locator。"
                if warnings else
                "段落和表格可形成source locator；仍需后续核对Word样式、页眉页脚、脚注和批注。"
            ),
            source_refs=[warning[:120] for warning in warnings[:3]],
        ),
        WritingQualityGate(
            gate_id=f"{config.package_id}_section_mapping",
            gate_label="章节完整性达标",
            status="warning" if sections else "blocked",
            owner="医学写作+医学经理",
            detail="章节树为启发式候选，需人工确认ICH M11锚点和真实方案目录后才能作为正式章节映射。",
            source_refs=[section.source_locator for section in sections[:5]],
        ),
        WritingQualityGate(
            gate_id=f"{config.package_id}_table_structure",
            gate_label="关键表格结构化",
            status="warning" if any(table.quality_notes for table in tables) else ("ok" if tables else "blocked"),
            owner="医学写作+数据管理员",
            detail="研究流程表、入排标准表、实验室/安全性表格已登记；SoA横向时间轴和合并单元格仍需专用结构化解析。",
            source_refs=[table.source_locator for table in tables if table.role_hint][:5],
        ),
        WritingQualityGate(
            gate_id=f"{config.package_id}_evidence_coverage",
            gate_label="证据覆盖达标",
            status="warning",
            owner="医学经理",
            detail="当前为来源定位起点，覆盖率不代表作者已确认或版本已冻结；关键断言需绑定source_id、locator、quote或表格行列定位。",
            source_refs=[],
        ),
        WritingQualityGate(
            gate_id=f"{config.package_id}_ai_provider",
            gate_label="AI修订线程已关闭",
            status="warning" if ai_status.get("configured") else "blocked",
            owner="系统管理员+医学经理",
            detail=(
                "独立AI provider已配置；仍需按章节限定allowed_sources和输出schema。"
                if ai_status.get("configured") else
                "独立AI provider未配置，AI生成受阻；方案解构、证据覆盖和医学写作修订不会自动调用AI。"
            ),
            source_refs=["独立AI服务未配置"],
        ),
        WritingQualityGate(
            gate_id=f"{config.package_id}_approval_export",
            gate_label="导出元数据齐备",
            status="blocked",
            owner="医学经理+医学总监",
            detail="未关闭AI修订、证据不足、高风险表述未清理或作者确认/版本冻结状态不完整时，不可生成正式导出包；当前最多支持审阅版DOCX准备检查。",
            source_refs=[],
        ),
        WritingQualityGate(
            gate_id=f"{config.package_id}_forbidden_words",
            gate_label="禁用表述扫描通过",
            status="ok",
            owner="医学写作",
            detail="manifest仅显示来源、候选、质量门和作者确认边界，不输出自动完成、直接递交或最终结论类表述。",
            source_refs=[],
        ),
    ]
    return gate_items


SECTION_MARKER_RE = re.compile(
    r"^(?P<number>(?:[1-9]|1[0-9]|2[0-5])(?:\.(?:[1-9]|[1-9][0-9])){0,3})(?:[、.．\s]+)?(?P<title>[\u4e00-\u9fffA-Za-z][^。；;:：]{1,70})$"
)
SECTION_TITLE_KEYWORDS = (
    "概要",
    "研究目的",
    "研究设计",
    "研究人群",
    "入选标准",
    "排除标准",
    "治疗",
    "给药",
    "疗效",
    "安全性",
    "不良事件",
    "统计",
    "样本量",
    "数据管理",
    "伦理",
    "知情同意",
    "参考文献",
    "附录",
    "流程",
)


def _section_anchor_candidates(document: ProtocolTextDocument) -> List[Tuple[int, str, str, int, str, float]]:
    anchors: List[Tuple[int, str, str, int, str, float]] = []
    seen = set()
    for paragraph in document.paragraphs:
        if ":table:" in paragraph.source_locator and not _looks_like_table_section_anchor(paragraph.text):
            continue
        text = _clean_heading_text(paragraph.text)
        if not text or len(text) > 90:
            continue
        match = SECTION_MARKER_RE.match(text)
        if not match:
            if text in {"双盲治疗期", "开放治疗期", "安全性随访", "样本量", "统计分析", "入选标准", "排除标准"}:
                number = ""
                title = text
                level = 2
                confidence = 0.68
            else:
                continue
        else:
            number = match.group("number")
            title = match.group("title").strip()
            level = min(number.count(".") + 1, 4)
            confidence = 0.7
            has_heading_keyword = any(keyword in title for keyword in SECTION_TITLE_KEYWORDS)
            if has_heading_keyword:
                confidence = 0.86
            if ":table:" in paragraph.source_locator:
                confidence -= 0.15
            if _looks_like_list_item(text):
                continue
            if not has_heading_keyword and "." not in number:
                continue
        if title in {"mg/片", "W", "1.0"} or len(title) < 2:
            continue
        key = (number, title)
        if key in seen:
            continue
        seen.add(key)
        anchors.append((paragraph.paragraph_index, number, title, level, paragraph.source_locator, max(confidence, 0.35)))
    return anchors


def _extract_protocol_metadata(document: ProtocolTextDocument, config: WritingPackageConfig) -> Dict[str, str]:
    paragraphs = [paragraph.text for paragraph in document.paragraphs[:120]]
    joined = "\n".join(paragraphs)
    title = _first_matching_after_label(paragraphs, ("试验题目", "研究题目", "方案标题")) or document.title
    if not title or "Protocol-Template" in title or title == "临床研究方案":
        title = _first_long_title(paragraphs) or config.package_label
    protocol_id = _first_label_value(joined, ("临床方案号", "方案编号"), value_pattern=r"[A-Za-z]{1,8}[-_A-Za-z0-9]{2,}") or config.project_code
    version = _first_label_value(joined, ("方案版本号",)) or _version_from_filename(config.protocol_path.name)
    date = _first_label_value(joined, ("方案版本日期",)) or _date_from_filename(config.protocol_path.name)
    return {
        "title": _truncate(title, 160),
        "protocol_id": _truncate(protocol_id, 80),
        "version": _truncate(version, 80),
        "date": _truncate(date, 80),
    }


def _version_from_filename(filename: str) -> str:
    match = re.search(r"(?i)(?:^|[_\-\s])v(?P<version>\d+(?:\.\d+)+)(?=$|[_\-\s.])", filename)
    return f"V{match.group('version')}" if match else ""


def _date_from_filename(filename: str) -> str:
    separated = re.search(r"(?<!\d)(?P<year>20\d{2})[._-](?P<month>\d{1,2})[._-](?P<day>\d{1,2})(?!\d)", filename)
    if separated:
        return f"{separated.group('year')}-{int(separated.group('month')):02d}-{int(separated.group('day')):02d}"
    compact = re.search(r"(?<!\d)(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})(?!\d)", filename)
    if compact:
        return f"{compact.group('year')}-{compact.group('month')}-{compact.group('day')}"
    return ""


def _inspect_docx_features(path: Path) -> Dict[str, object]:
    features: Dict[str, object] = {
        "image_count": 0,
        "revision_mark_count": 0,
        "field_count": 0,
        "style_summary": {},
    }
    if not path.exists():
        return features
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            features["image_count"] = sum(1 for name in names if name.startswith("word/media/"))
            document_xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return features
    features["revision_mark_count"] = sum(document_xml.count(tag) for tag in ("<w:ins", "<w:del", "<w:moveFrom", "<w:moveTo"))
    features["field_count"] = document_xml.count("<w:fldChar") + document_xml.count("<w:instrText")
    try:
        root = ElementTree.fromstring(document_xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        styles = Counter(
            element.attrib.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
            for element in root.findall(".//w:pStyle", ns)
        )
        features["style_summary"] = {key: value for key, value in styles.most_common(12) if key}
    except ElementTree.ParseError:
        pass
    return features


def _table_headers(table: ProtocolTable) -> List[str]:
    for row in table.rows[:3]:
        headers = [_truncate(cell.text.replace("\n", " / "), 80) for cell in row if cell.text.strip()]
        if len(headers) >= 2:
            return headers
    return []


def _table_title_hint(table: ProtocolTable, document: ProtocolTextDocument) -> str:
    headers = _table_headers(table)
    if headers:
        return " | ".join(headers[:4])
    for paragraph in reversed(document.paragraphs[: min(len(document.paragraphs), 30)]):
        if paragraph.text:
            return _truncate(paragraph.text, 120)
    return f"Table {table.table_index}"


def _table_role_hint(title_hint: str, headers: List[str]) -> str:
    text = f"{title_hint} {' '.join(headers)}"
    if any(keyword in text for keyword in ("研究阶段", "访视", "筛选期", "治疗期", "随访", "流程", "活动时间表")):
        return "研究流程/SoA候选"
    if any(keyword in text for keyword in ("入选", "排除", "合格性")):
        return "入排标准"
    if any(keyword in text for keyword in ("终点", "疗效", "PASI", "IGA", "EASI", "NRS")):
        return "疗效评价"
    if any(keyword in text for keyword in ("AE", "不良事件", "安全性", "实验室", "血常规", "血生化")):
        return "安全性评价"
    if any(keyword in text for keyword in ("统计", "样本量", "分析集", "SAP")):
        return "统计学考虑"
    if any(keyword in text for keyword in ("缩写", "英文全称", "中文全称")):
        return "缩略语表"
    return "待人工分类"


def _linked_section_id(
    table: ProtocolTable,
    sections: List[WritingSectionSummary],
    document: ProtocolTextDocument,
) -> str:
    first_paragraph_index = _locator_paragraph_index(table.source_locator, document)
    prior_sections = [
        section for section in sections
        if _section_locator_index(section.source_locator, document) <= first_paragraph_index
    ]
    return prior_sections[-1].section_id if prior_sections else ""


def _locator_paragraph_index(locator: str, document: ProtocolTextDocument) -> int:
    for paragraph in document.paragraphs:
        if paragraph.source_locator.startswith(locator) or locator.startswith(paragraph.source_locator):
            return paragraph.paragraph_index
    match = re.search(r"paragraph:(\d+)", locator)
    return int(match.group(1)) if match else 0


def _section_locator_index(locator: str, document: ProtocolTextDocument) -> int:
    for paragraph in document.paragraphs:
        if paragraph.source_locator == locator:
            return paragraph.paragraph_index
    return _locator_paragraph_index(locator, document)


def _has_sparse_rows(table: ProtocolTable) -> bool:
    for row in table.rows:
        if row and sum(1 for cell in row if cell.text.strip()) < len(row):
            return True
    return False


def _looks_like_table_section_anchor(text: str) -> bool:
    return any(keyword in text for keyword in ("入选标准", "排除标准", "样本量", "统计分析", "研究设计", "安全性随访"))


def _looks_like_list_item(text: str) -> bool:
    return len(text) > 55 or any(keyword in text for keyword in ("者；", "者，", "小时", "mg", "周内", "随机前"))


def _clean_heading_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" .．、")


def _ich_anchor_hint(heading: str) -> str:
    if any(keyword in heading for keyword in ("概要", "摘要")):
        return "Synopsis"
    if any(keyword in heading for keyword in ("研究目的", "终点")):
        return "Objectives and endpoints"
    if any(keyword in heading for keyword in ("研究设计", "流程", "访视")):
        return "Study design"
    if any(keyword in heading for keyword in ("入选", "排除", "研究人群")):
        return "Study population"
    if any(keyword in heading for keyword in ("治疗", "给药", "用药")):
        return "Intervention"
    if any(keyword in heading for keyword in ("安全性", "不良事件", "实验室")):
        return "Safety"
    if any(keyword in heading for keyword in ("统计", "样本量")):
        return "Statistical considerations"
    return ""


def _first_matching_after_label(paragraphs: List[str], labels: Tuple[str, ...]) -> str:
    for text in paragraphs:
        for label in labels:
            if label in text:
                value = _value_after_label(text, label)
                if len(value) >= 8:
                    return value
    return ""


def _first_label_value(joined: str, labels: Tuple[str, ...], value_pattern: str = "") -> str:
    lines = [line.strip() for line in joined.splitlines() if line.strip()]
    candidates: List[str] = []
    for label in labels:
        for index, line in enumerate(lines):
            if label not in line:
                continue
            match = re.search(rf"{label}[：:][ \t]*([^\n\r]+)", line)
            if match and match.group(1).strip():
                candidates.append(match.group(1).strip())
            if index + 1 < len(lines):
                next_line = lines[index + 1].strip()
                if next_line and not any(other_label in next_line for other_label in ("方案版本", "方案日期", "试验题目", "研究题目")):
                    candidates.append(next_line)
    if not value_pattern:
        return candidates[0] if candidates else ""
    for candidate in candidates:
        if re.search(value_pattern, candidate):
            return candidate
    return ""


def _value_after_label(text: str, label: str) -> str:
    value = re.sub(rf"^.*?{label}[：:]?", "", text).strip()
    return value or text.strip()


def _first_long_title(paragraphs: List[str]) -> str:
    for text in paragraphs:
        clean = text.strip()
        if 18 <= len(clean) <= 180 and any(keyword in clean for keyword in ("随机", "双盲", "有效性", "安全性", "临床研究")):
            return clean
    return ""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _package_coverage(sections: List[WritingSectionSummary]) -> int:
    if not sections:
        return 0
    return int(round(sum(section.evidence_coverage_percent for section in sections) / len(sections)))


def _preview_text(parts: List[str], limit: int) -> str:
    return _truncate(" ".join(part for part in parts if part), limit)


def _truncate(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    return clean if len(clean) <= limit else clean[:limit] + "...[truncated]"
