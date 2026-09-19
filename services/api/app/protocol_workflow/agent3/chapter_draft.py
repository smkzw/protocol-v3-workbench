"""Pin chapter generation material and parse ordered candidates without adoption."""
from dataclasses import dataclass
import hashlib
import json

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.registries.chapters import ChapterSkillInput
from app.protocol_workflow.registries.fact_bindings import BoundChapterSkillInput
from app.protocol_workflow.registries.ordered_draft import OrderedChapterDraftCandidate
from packages.contracts.workbench_contracts.protocol_v3 import ChapterContractV2, EvidenceUnit


CHAPTER_DRAFT_INSTRUCTION = """依据指定章节合同、已确认研究事实和完整来源撰写该章节候选。
保留段落和表格出现顺序；每个段落、表格及单元格使用独立稳定身份。
返回JSON：chapter_contract_id、node_id、blocks，遵循output_schema。
事实只来自chapter_input.resolved_facts；参考资料不能自行变成当前研究参数。
引用仅使用输入evidence的evidence_unit_id，不创建准入、批准、质量分数或签名。
表格单元格provenance_lineage和脚注source_refs只填写输入evidence_unit_id。
原文定位填写source_locator或marker_source_locator，不能把定位字符串当作证据编号。
source_material如存在，包含完整源结构与解析警告；目录、标题、参考文献列表和页眉等仅供定位与理解，不独立证明研究参数。
脚注原文和合并单元格需结合完整源结构核对；未评估的来源质量不能自行改成已准入。
不要把结构化表格写成正文中的JSON字符串，不用occurrences计数代替真实表格。
完整保留原文单位、表格脚注和引用定位；不要用概述或占位文字代替实际章节内容。
输入不足时不要编造研究参数；候选后续仍需内容核对，不代表已完成医学或Word验收。
chapter_input.gap_fact_paths 列出本章已确认缺失的事实路径：在对应内容位置用"【缺口：<fact_path>：该项待研究团队确认后补充】"的格式显式标注缺口；不得编造数值或结论，不得把缺口写成"不适用"或"TBD"，不得用模板示例或参考资料数值冒充本研究事实。缺口属于工作稿的显式组成部分，后续核对会逐项追踪。
行文基准（对齐事例成品方案）：全文使用"试验参与者"（不写"受试者"）；客观义务式陈述（"应…"），具体到数字与时间窗（数值一律取自已确认事实）；缩略语首次出现时给出定义（如"AE=不良事件"）；方案概要章为"研究流程表（SOA）+缩略语行+注释式要点"，不写成叙述长文。"""


class ChapterDraftReferenceError(ValueError):
    def __init__(self, location, reference):
        self.code = 'chapter_table_reference_unknown'
        self.location = location
        self.detail = f'Reference {reference!r} is not in the supplied evidence IDs.'
        super().__init__(self.code)


@dataclass(frozen=True)
class PreparedChapterDraftRequest:
    payload_json: str
    input_sha256: str

    def __post_init__(self):
        if hashlib.sha256(self.payload_json.encode()).hexdigest() != self.input_sha256:
            raise ValueError("chapter_input_hash_mismatch")

    def to_payload(self):
        return json.loads(self.payload_json)


def prepare_chapter_draft(contract: ChapterContractV2, bound_input: ChapterSkillInput,
                          evidence: tuple[EvidenceUnit, ...], *, source_material=None) -> PreparedChapterDraftRequest:
    if (bound_input.chapter_contract_id != contract.chapter_contract_id
            or bound_input.node_id != contract.semantic_node_id
            or bound_input.template_id != contract.template_id
            or bound_input.template_sha256 != contract.template_sha256
            or bound_input.word_rules != contract.word_rules):
        raise ValueError("chapter_input_binding_mismatch")
    if (isinstance(bound_input, BoundChapterSkillInput)
            and bound_input.chapter_contract_sha256 != contract.material_sha256()):
        raise ValueError("chapter_input_binding_mismatch")
    ids = tuple(unit.evidence_unit_id for unit in evidence)
    if len(ids) != len(set(ids)):
        raise ValueError("chapter_evidence_identity_duplicate")
    payload = {
        "instruction": CHAPTER_DRAFT_INSTRUCTION,
        "chapter_contract": contract.model_dump(mode="json"),
        "chapter_input": bound_input.model_dump(mode="json"),
        "evidence": [unit.model_dump(mode="json") for unit in evidence],
        "output_schema": OrderedChapterDraftCandidate.model_json_schema(),
    }
    if source_material is not None:
        material = source_material.to_payload()
        if material['evidence'] != payload['evidence']:
            raise ValueError('chapter_source_evidence_mismatch')
        payload['source_material'] = material
    text = canonical_json(payload)
    return PreparedChapterDraftRequest(text, hashlib.sha256(text.encode()).hexdigest())


def read_chapter_draft(prepared: PreparedChapterDraftRequest, output: dict) -> OrderedChapterDraftCandidate:
    if not isinstance(output, dict):
        raise ValueError("chapter_output_schema_invalid")
    payload = prepared.to_payload()
    chapter = payload["chapter_input"]
    if (output.get("chapter_contract_id") != chapter["chapter_contract_id"]
            or output.get("node_id") != chapter["node_id"]):
        raise ValueError("chapter_output_binding_mismatch")
    known = tuple(unit["evidence_unit_id"] for unit in payload["evidence"])
    if "known_evidence_ids" in output and output["known_evidence_ids"] not in (known, list(known)):
        raise ValueError("chapter_source_universe_mismatch")
    candidate = OrderedChapterDraftCandidate.model_validate({**output, "known_evidence_ids": known})
    if not candidate.blocks:
        raise ValueError("chapter_draft_empty")
    for block_index, block in enumerate(candidate.blocks):
        if block.kind == "paragraph" and not block.text.strip():
            raise ValueError("chapter_draft_empty")
        if block.kind == "table" and (not block.table.rows or not block.table.columns):
            raise ValueError("chapter_draft_empty")
        if block.kind == "table":
            for row_index, row in enumerate(block.table.rows):
                for cell_index, cell in enumerate(row.cells):
                    for reference in cell.provenance_lineage:
                        if reference not in known:
                            raise ChapterDraftReferenceError(
                                f'blocks.{block_index}.table.rows.{row_index}.cells.{cell_index}.provenance_lineage', reference)
            for note_index, note in enumerate(block.table.notes):
                for reference in note.source_refs:
                    if reference not in known:
                        raise ChapterDraftReferenceError(
                            f'blocks.{block_index}.table.notes.{note_index}.source_refs', reference)
    # This proves transport and identity only; content/medical checks remain
    # independent. Neither model self-report nor ID membership is admission.
    return candidate


def prepare_study_chapter(template, study, node_id, evidence, *, source_material=None,
                          deferred_required_paths=()):
    """Compile a server-owned study and catalog; callers cannot splice facts.

    ``deferred_required_paths`` turns listed required facts into explicit gap
    objects carried on the bound input; they are never treated as confirmed.
    """
    from app.protocol_workflow.registries.applicability import bind_applicable_chapter, build_applicability_snapshot
    entry = next((entry for entry in template.registry.chapters if entry.node_id == node_id), None)
    if entry is None:
        raise ValueError('chapter_node_unknown')
    snapshot = build_applicability_snapshot((entry.contract,), study,
        template.rules_catalog.rules, created_at=study.updated_at)
    if snapshot.entries[0].status.value == 'not_applicable':
        raise ValueError('chapter_not_applicable')
    effective, bound = bind_applicable_chapter(study, entry.contract,
        template.fact_catalog.bindings, rules=template.rules_catalog.rules,
        deferred_required_paths=deferred_required_paths)
    return prepare_chapter_draft(effective, bound, tuple(evidence), source_material=source_material)
