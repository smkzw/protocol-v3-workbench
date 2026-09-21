from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Iterator, List

from packages.contracts.workbench_contracts import (
    MedicalWritingContentFinding,
    ProtocolDocument,
    ProtocolSection,
    RiskSeverity,
)


MALFORMED_MIXED_DELIMITER_RE = re.compile(
    r"(?:<|＜)[^<>＜＞{}\r\n]{0,80}\}|\{[^<>＜＞{}\r\n]{0,80}(?:>|＞)"
)
# These markers are implementation/test transport vocabulary, not admissible
# protocol prose.  Catch them at the document-content layer as well as in the
# AI runner so that legacy or manually saved working copies cannot leak them
# into an approved-final DOCX.
INTERNAL_TRANSPORT_VOCABULARY_RE = re.compile(
    r"(?:测试数据首稿|隔离fixture|\bfixture\b|ProtocolAssemblyPlan|"
    r"evidence_span_ids|SECTION_ID=)",
    re.IGNORECASE,
)
# These phrases narrate how AI or a drafting workflow handled evidence.  They
# belong in the review panel, not in protocol body text.  The expression is
# intentionally phrase-based so ordinary uses of 确认/依据 in study conduct
# remain valid.
DRAFTING_PROCESS_VOCABULARY_RE = re.compile(
    r"(?:当前项目(?:已)?确认|当前已确认|本方案不引用|本章节不(?:重复|引用)|"
    r"未(?:继承|补充|拟定|编造)[^。；\r\n]{0,36}(?:来源|语料|项目|竞品|规则|内容)|"
    r"(?:公司|共享)语料|章节包|候选正文|"
    r"已确认(?:的)?研究事实|本节表述严格限定于已确认)",
    re.IGNORECASE,
)
# A final protocol must not carry unresolved drafting instructions.  This is
# deliberately narrower than a generic Chinese ``待`` search (which would
# flag legitimate terms such as 待访视/待随访); it targets confirmation,
# evidence, and finalisation language that belongs in the review UI, not the
# submitted body text.
UNRESOLVED_DRAFT_MARKER_RE = re.compile(
    r"(?:"
    r"待(?:补充|确认|定|完善|医学(?:经理)?[^。；，,\r\n]{0,40}确认)"
    r"|(?:尚待|有待)[^。；，,\r\n]{0,40}(?:确认|定稿|明确)"
    r"|(?:需|将|由)[^。；，,\r\n]{0,24}"
    r"(?:医学(?:经理)?|正式医学|生物统计(?:人员)?)[^。；，,\r\n]{0,24}"
    r"(?:确认|定稿|锁定)"
    r"|尚无直接证据(?:来源)?支持"
    r"|(?:在|于)?本方案正式(?:文本|版本|定稿)[^。；，,\r\n]{0,36}"
    r"(?:中)?(?:载明|明确|规定|补充|呈现|定稿)"
    r"|(?:将|应|需|须)在[^。；，,\r\n]{0,32}"
    r"(?:正式文本|正式方案|方案定稿|定稿中)[^。；，,\r\n]{0,24}"
    r"(?:载明|明确|规定|补充|呈现|定稿)"
    r"|(?:未提供|未给出|未明确)(?:具体|数值|正式)?[^。；，,\r\n]{0,18}"
    r"(?:参数|数据|资料|数值|条目)?"
    r"|(?:由|待)[^。；，,\r\n]{0,30}"
    r"(?:医学(?:经理|负责人)?|生物统计(?:人员)?)[^。；，,\r\n]{0,20}"
    r"(?:确认|定稿|明确|锁定)"
    r"|(?:确认|定稿)后(?:再|方)?(?:写入|补充|明确)"
    r"|(?:未编列|未列出|尚未列入)[^。；，,\r\n]{0,24}"
    r"(?:正式)?(?:参考文献|文献条目)"
    r")",
    re.IGNORECASE,
)
DETECTOR_VERSION = "medical_writing_content_quality_v1"


# These complete clauses describe study conduct, not an instruction to finish
# writing the protocol. Match a local clause so neighbouring draft instructions
# remain visible, including in the same table cell.
STUDY_CONDUCT_CLAUSE_RE = re.compile(
    r"(?:未提供书面知情同意(?:书)?(?:的)?(?:者|人员|试验参与者|受试者)"
    r"(?:不进入筛选|不得参加(?:本)?研究|不得入组)"
    r"|(?:若|如|如果)(?:试验参与者|受试者)未提供书面知情同意(?:书)?"
    r"\s*[，,]?\s*(?:则)?(?:不进入筛选|不得参加(?:本)?研究|不得入组)"
    r"|(?:数据|数据库)(?:将)?(?:在|由)生物统计(?:人员)?确认后(?:锁定|锁库))"
)


def iter_unresolved_draft_markers(text: str) -> Iterator[re.Match[str]]:
    """Return original-offset matches after recognising explicit conduct clauses."""
    for sentence in re.finditer(r"[^。；\r\n]+", text):
        if STUDY_CONDUCT_CLAUSE_RE.fullmatch(sentence.group().strip()):
            continue
        for clause in re.finditer(r"[^，,]+", sentence.group()):
            if STUDY_CONDUCT_CLAUSE_RE.fullmatch(clause.group().strip()):
                continue
            yield from UNRESOLVED_DRAFT_MARKER_RE.finditer(
                text, sentence.start() + clause.start(), sentence.start() + clause.end()
            )


class MedicalWritingContentQualityDetector:
    """Conservative, deterministic checks over protocol content blocks."""

    def scan_document(self, document: ProtocolDocument) -> List[MedicalWritingContentFinding]:
        findings: List[MedicalWritingContentFinding] = []
        for section in document.sections:
            findings.extend(
                self.scan_section(
                    document,
                    section,
                    section.content_blocks,
                    content_revision=0,
                )
            )
        return findings

    def scan_section(
        self,
        document: ProtocolDocument,
        section: ProtocolSection,
        content_blocks: Iterable[dict[str, Any]],
        *,
        content_revision: int,
    ) -> List[MedicalWritingContentFinding]:
        findings: List[MedicalWritingContentFinding] = []
        for block in content_blocks:
            block_type = str(block.get("block_type") or "")
            if block_type == "table":
                findings.extend(
                    self._scan_table_block(
                        document,
                        section,
                        block,
                        content_revision=content_revision,
                    )
                )
                continue
            text = str(block.get("text") or "")
            if not text:
                continue
            findings.extend(
                self._scan_text(
                    document=document,
                    section=section,
                    block=block,
                    text=text,
                    location_kind="paragraph",
                    source_locator=str(block.get("source_locator") or ""),
                    content_revision=content_revision,
                )
            )
        return findings

    def _scan_table_block(
        self,
        document: ProtocolDocument,
        section: ProtocolSection,
        block: dict[str, Any],
        *,
        content_revision: int,
    ) -> List[MedicalWritingContentFinding]:
        findings: List[MedicalWritingContentFinding] = []
        rows = block.get("rows")
        if not isinstance(rows, list):
            return findings
        for row_position, row in enumerate(rows):
            if not isinstance(row, list):
                continue
            for cell_position, cell in enumerate(row):
                if not isinstance(cell, dict):
                    continue
                text = str(cell.get("text") or "")
                if not text:
                    continue
                row_index = _nonnegative_int(cell.get("row_index"), row_position)
                cell_index = _nonnegative_int(cell.get("cell_index"), cell_position)
                findings.extend(
                    self._scan_text(
                        document=document,
                        section=section,
                        block=block,
                        text=text,
                        location_kind="table_cell",
                        source_locator=str(cell.get("source_locator") or ""),
                        content_revision=content_revision,
                        table_id=str(block.get("table_id") or ""),
                        cell_id=str(cell.get("cell_id") or ""),
                        row_index=row_index,
                        cell_index=cell_index,
                    )
                )
        return findings

    def _scan_text(
        self,
        *,
        document: ProtocolDocument,
        section: ProtocolSection,
        block: dict[str, Any],
        text: str,
        location_kind: str,
        source_locator: str,
        content_revision: int,
        table_id: str = "",
        cell_id: str = "",
        row_index: int | None = None,
        cell_index: int | None = None,
    ) -> List[MedicalWritingContentFinding]:
        stable_location = source_locator or cell_id or str(block.get("block_id") or "")
        findings: List[MedicalWritingContentFinding] = []
        for occurrence_index, match in enumerate(MALFORMED_MIXED_DELIMITER_RE.finditer(text)):
            identity = "|".join(
                (
                    document.project_id,
                    document.document_id,
                    section.section_id,
                    stable_location,
                    DETECTOR_VERSION,
                    "malformed_mixed_delimiter",
                    str(occurrence_index),
                )
            )
            content_fingerprint = hashlib.sha256(
                "|".join(
                    (
                        text,
                        match.group(0),
                        str(occurrence_index),
                    )
                ).encode("utf-8")
            ).hexdigest()
            findings.append(
                MedicalWritingContentFinding(
                    finding_id="mwq_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                    project_id=document.project_id,
                    document_id=document.document_id,
                    document_version=document.version,
                    section_id=section.section_id,
                    section_heading=section.heading,
                    block_id=str(block.get("block_id") or ""),
                    location_kind=location_kind,
                    source_kind=str(block.get("source_kind") or "original_protocol_docx"),
                    source_text=text,
                    matched_text=match.group(0),
                    match_start=match.start(),
                    match_end=match.end(),
                    occurrence_index=occurrence_index,
                    source_locator=source_locator,
                    table_id=table_id,
                    cell_id=cell_id,
                    row_index=row_index,
                    cell_index=cell_index,
                    rule_code="malformed_mixed_delimiter",
                    rule_label="疑似未完成的占位或混合闭合符",
                    detector_version=DETECTOR_VERSION,
                    finding_reason=(
                        "文本以尖括号起始但使用花括号闭合，或以花括号起始但使用尖括号闭合；"
                        "该形式不同于常规医学数值比较，需核对源文档并由医学人员处置。"
                    ),
                    severity=RiskSeverity.HIGH,
                    approval_blocking=True,
                    content_fingerprint=content_fingerprint,
                    content_revision=content_revision,
                )
            )

        for rule_code, pattern, rule_label, finding_reason in (
            (
                "internal_transport_vocabulary",
                INTERNAL_TRANSPORT_VOCABULARY_RE,
                "内部传输/测试词泄漏",
                (
                    "正文包含系统内部传输、测试夹具或结构化标识词；这些词不能进入医学方案正文，"
                    "应改写为面向申报的中文表述后再冻结终稿。"
                ),
            ),
            (
                "unresolved_draft_marker",
                UNRESOLVED_DRAFT_MARKER_RE,
                "未完成的待确认/证据占位表达",
                (
                    "正文仍包含待确认、待定稿或证据不足的草稿指令；应先补齐可核验研究事实，"
                    "再将完整表述写入方案正文。"
                ),
            ),
            (
                "drafting_process_vocabulary",
                DRAFTING_PROCESS_VOCABULARY_RE,
                "写作过程说明泄漏到方案正文",
                (
                    "正文描述了当前项目确认状态、语料使用或候选生成过程；"
                    "这些说明应保留在审阅卡中，正文只呈现可申报的研究内容。"
                ),
            ),
        ):
            matches = (
                iter_unresolved_draft_markers(text)
                if rule_code == "unresolved_draft_marker"
                else pattern.finditer(text)
            )
            for occurrence_index, match in enumerate(matches):
                identity = "|".join(
                    (
                        document.project_id,
                        document.document_id,
                        section.section_id,
                        stable_location,
                        DETECTOR_VERSION,
                        rule_code,
                        str(occurrence_index),
                    )
                )
                content_fingerprint = hashlib.sha256(
                    "|".join(
                        (
                            text,
                            match.group(0),
                            str(occurrence_index),
                        )
                    ).encode("utf-8")
                ).hexdigest()
                findings.append(
                    MedicalWritingContentFinding(
                        finding_id="mwq_"
                        + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24],
                        project_id=document.project_id,
                        document_id=document.document_id,
                        document_version=document.version,
                        section_id=section.section_id,
                        section_heading=section.heading,
                        block_id=str(block.get("block_id") or ""),
                        location_kind=location_kind,
                        source_kind=str(block.get("source_kind") or "original_protocol_docx"),
                        source_text=text,
                        matched_text=match.group(0),
                        match_start=match.start(),
                        match_end=match.end(),
                        occurrence_index=occurrence_index,
                        source_locator=source_locator,
                        table_id=table_id,
                        cell_id=cell_id,
                        row_index=row_index,
                        cell_index=cell_index,
                        rule_code=rule_code,
                        rule_label=rule_label,
                        detector_version=DETECTOR_VERSION,
                        finding_reason=finding_reason,
                        severity=RiskSeverity.HIGH,
                        approval_blocking=True,
                        content_fingerprint=content_fingerprint,
                        content_revision=content_revision,
                    )
                )
        return findings


def _nonnegative_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed >= 0 else fallback
