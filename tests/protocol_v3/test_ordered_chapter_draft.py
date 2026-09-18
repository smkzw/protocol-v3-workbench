"""Red-first tests for ordered chapter draft candidates.

These exercise a pure candidate carrier that reuses StructuredTable and
preserves block order / identity. They do not claim medical admission,
Word acceptance, or confirmed SemanticDocument authority.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from app.protocol_workflow.registries.chapters import ContentCell, ContentObject
from app.protocol_workflow.registries.ordered_draft import (
    OrderedChapterDraftCandidate,
    OrderedDraftBlockKind,
    OrderedDraftParagraphBlock,
    OrderedDraftTableBlock,
    refuse_occurrences_as_instances,
)
from packages.contracts.workbench_contracts import (
    StructuredTable,
    StructuredTableCell,
    StructuredTableColumn,
    StructuredTableDomain,
    StructuredTableNote,
    StructuredTableNoteType,
    StructuredTableRole,
    StructuredTableRow,
)
from packages.contracts.workbench_contracts.protocol_v3 import StructuralObjectKind


def _2x2_table(
    *,
    table_id: str,
    block_id: str,
    title: str,
    source_locator: str,
    cell_prefix: str,
    note_id: str,
) -> StructuredTable:
    col_a = f"{cell_prefix}_col_a"
    col_b = f"{cell_prefix}_col_b"
    row_0 = f"{cell_prefix}_row_0"
    row_1 = f"{cell_prefix}_row_1"
    cells = {
        (row_0, col_a): f"{cell_prefix}_r0c0",
        (row_0, col_b): f"{cell_prefix}_r0c1",
        (row_1, col_a): f"{cell_prefix}_r1c0",
        (row_1, col_b): f"{cell_prefix}_r1c1",
    }
    note = StructuredTableNote(
        note_id=note_id,
        marker="a",
        note_type=StructuredTableNoteType.DEFINITION,
        text=f"note for {title}",
        target_ids=[cells[(row_0, col_a)]],
        source_refs=[f"{source_locator}:note"],
        source_kind="docx",
        marker_source_locator=f"{source_locator}:marker",
    )
    return StructuredTable(
        table_id=table_id,
        block_id=block_id,
        domain=StructuredTableDomain.OBJECTIVES_ENDPOINTS,
        role=StructuredTableRole.BODY_CONTENT,
        title=title,
        source_locator=source_locator,
        header_row_count=1,
        columns=[
            StructuredTableColumn(
                column_id=col_a,
                order=0,
                label="终点",
                source_locator=f"{source_locator}:col:0",
            ),
            StructuredTableColumn(
                column_id=col_b,
                order=1,
                label="定义",
                source_locator=f"{source_locator}:col:1",
            ),
        ],
        rows=[
            StructuredTableRow(
                row_id=row_0,
                order=0,
                label="header",
                source_locator=f"{source_locator}:row:0",
                cells=[
                    StructuredTableCell(
                        cell_id=cells[(row_0, col_a)],
                        row_id=row_0,
                        column_id=col_a,
                        text="主要终点",
                        source_locator=f"{source_locator}:r0c0",
                        provenance_lineage=["evidence:e1"],
                        note_refs=[note_id],
                    ),
                    StructuredTableCell(
                        cell_id=cells[(row_0, col_b)],
                        row_id=row_0,
                        column_id=col_b,
                        text="定义列",
                        source_locator=f"{source_locator}:r0c1",
                    ),
                ],
            ),
            StructuredTableRow(
                row_id=row_1,
                order=1,
                label="body",
                source_locator=f"{source_locator}:row:1",
                cells=[
                    StructuredTableCell(
                        cell_id=cells[(row_1, col_a)],
                        row_id=row_1,
                        column_id=col_a,
                        text="PFS",
                        source_locator=f"{source_locator}:r1c0",
                        provenance_lineage=["evidence:e2"],
                    ),
                    StructuredTableCell(
                        cell_id=cells[(row_1, col_b)],
                        row_id=row_1,
                        column_id=col_b,
                        text="无进展生存期",
                        source_locator=f"{source_locator}:r1c1",
                    ),
                ],
            ),
        ],
        notes=[note],
    )


def _paragraph_a_to_table2_candidate() -> OrderedChapterDraftCandidate:
    table1 = _2x2_table(
        table_id="table_obj_1",
        block_id="block_table_1",
        title="表1 主要终点",
        source_locator="docx:table:1",
        cell_prefix="t1",
        note_id="note_t1",
    )
    table2 = _2x2_table(
        table_id="table_obj_2",
        block_id="block_table_2",
        title="表2 次要终点",
        source_locator="docx:table:2",
        cell_prefix="t2",
        note_id="note_t2",
    )
    return OrderedChapterDraftCandidate(
        chapter_contract_id="contract:v2-n-3-1-1:v2",
        node_id="v2_n_3_1_1",
        known_evidence_ids=("evidence:e1", "evidence:e2", "evidence:para_a"),
        blocks=(
            OrderedDraftParagraphBlock(
                block_id="block_para_a",
                text="段落A：研究目的说明。",
                source_locator="docx:paragraph:10",
                evidence_refs=("evidence:para_a",),
            ),
            OrderedDraftTableBlock(
                block_id="block_table_1",
                table=table1,
                evidence_refs=("evidence:e1",),
            ),
            OrderedDraftParagraphBlock(
                block_id="block_para_b",
                text="段落B：表格说明。",
                source_locator="docx:paragraph:11",
                evidence_refs=(),
            ),
            OrderedDraftTableBlock(
                block_id="block_table_2",
                table=table2,
                evidence_refs=("evidence:e2",),
            ),
        ),
    )


def test_rejects_duplicate_block_ids():
    table = _2x2_table(
        table_id="table_dup",
        block_id="block_shared",
        title="dup",
        source_locator="docx:table:9",
        cell_prefix="dup",
        note_id="note_dup",
    )
    with pytest.raises(ValidationError, match="block_id"):
        OrderedChapterDraftCandidate(
            chapter_contract_id="contract:x",
            node_id="v2_n_x",
            known_evidence_ids=(),
            blocks=(
                OrderedDraftParagraphBlock(
                    block_id="block_shared",
                    text="A",
                    source_locator="docx:p:1",
                ),
                OrderedDraftTableBlock(block_id="block_shared", table=table),
            ),
        )


def test_rejects_table_block_identity_mismatch():
    table = _2x2_table(
        table_id="table_mismatch",
        block_id="table_internal_block",
        title="mismatch",
        source_locator="docx:table:3",
        cell_prefix="mm",
        note_id="note_mm",
    )
    with pytest.raises(ValidationError, match="block_id"):
        OrderedDraftTableBlock(block_id="enclosing_block", table=table)


def test_rejects_dangling_evidence_refs():
    with pytest.raises(ValidationError, match="evidence"):
        OrderedChapterDraftCandidate(
            chapter_contract_id="contract:x",
            node_id="v2_n_x",
            known_evidence_ids=("evidence:known",),
            blocks=(
                OrderedDraftParagraphBlock(
                    block_id="block_para",
                    text="has dangling ref",
                    source_locator="docx:p:2",
                    evidence_refs=("evidence:missing",),
                ),
            ),
        )


def test_refuse_occurrences_as_instances():
    obj = ContentObject(
        object_kind=StructuralObjectKind.TABLE,
        occurrences=2,
        text=None,
        cells=(
            ContentCell(cell_id="cell_a", value="A"),
            ContentCell(cell_id="cell_b", value="B"),
        ),
    )
    with pytest.raises(ValueError, match="occurrences"):
        refuse_occurrences_as_instances(obj)


def test_json_roundtrip_preserves_order_identity_cells_and_sources():
    original = _paragraph_a_to_table2_candidate()
    payload = original.model_dump(mode="json")
    restored = OrderedChapterDraftCandidate.model_validate(payload)

    assert [block.kind for block in restored.blocks] == [
        OrderedDraftBlockKind.PARAGRAPH,
        OrderedDraftBlockKind.TABLE,
        OrderedDraftBlockKind.PARAGRAPH,
        OrderedDraftBlockKind.TABLE,
    ]
    assert [block.block_id for block in restored.blocks] == [
        "block_para_a",
        "block_table_1",
        "block_para_b",
        "block_table_2",
    ]

    para_a, table_block_1, para_b, table_block_2 = restored.blocks
    assert para_a.text == "段落A：研究目的说明。"
    assert para_a.source_locator == "docx:paragraph:10"
    assert para_a.evidence_refs == ("evidence:para_a",)
    assert para_b.text == "段落B：表格说明。"
    assert para_b.source_locator == "docx:paragraph:11"

    assert table_block_1.table.table_id == "table_obj_1"
    assert table_block_1.table.block_id == "block_table_1"
    assert table_block_2.table.table_id == "table_obj_2"
    assert table_block_2.table.block_id == "block_table_2"
    assert table_block_1.table.domain == table_block_2.table.domain
    assert table_block_1.table.role == table_block_2.table.role

    original_t1 = original.blocks[1].table
    restored_t1 = table_block_1.table
    assert restored_t1.source_locator == original_t1.source_locator
    assert restored_t1.title == original_t1.title
    assert len(restored_t1.rows) == 2
    assert len(restored_t1.columns) == 2
    assert [
        [cell.text for cell in row.cells] for row in restored_t1.rows
    ] == [["主要终点", "定义列"], ["PFS", "无进展生存期"]]
    assert [
        [cell.source_locator for cell in row.cells] for row in restored_t1.rows
    ] == [
        ["docx:table:1:r0c0", "docx:table:1:r0c1"],
        ["docx:table:1:r1c0", "docx:table:1:r1c1"],
    ]
    assert restored_t1.rows[0].cells[0].provenance_lineage == ["evidence:e1"]
    assert restored_t1.rows[0].cells[0].note_refs == ["note_t1"]
    assert restored_t1.notes[0].note_id == "note_t1"
    assert restored_t1.notes[0].source_refs == ["docx:table:1:note"]
    assert restored_t1.notes[0].text == original_t1.notes[0].text

    restored_t2 = table_block_2.table
    assert [
        [cell.text for cell in row.cells] for row in restored_t2.rows
    ] == [["主要终点", "定义列"], ["PFS", "无进展生存期"]]
    assert restored_t2.rows[1].cells[1].source_locator == "docx:table:2:r1c1"
    assert restored_t2.notes[0].source_refs == ["docx:table:2:note"]


def test_input_table_mutation_does_not_alter_recorded_candidate():
    table = _2x2_table(
        table_id="table_mut",
        block_id="block_mut",
        title="before",
        source_locator="docx:table:8",
        cell_prefix="mut",
        note_id="note_mut",
    )
    candidate = OrderedChapterDraftCandidate(
        chapter_contract_id="contract:x",
        node_id="v2_n_x",
        known_evidence_ids=(),
        blocks=(OrderedDraftTableBlock(block_id="block_mut", table=table),),
    )
    table.title = "after-external-mutation"
    table.rows[0].cells[0].text = "mutated-cell"
    recorded = candidate.blocks[0].table
    assert recorded.title == "before"
    assert recorded.rows[0].cells[0].text == "主要终点"


def test_candidate_does_not_mint_medical_admission_or_scores():
    candidate = _paragraph_a_to_table2_candidate()
    payload = candidate.model_dump(mode="json")
    blob = str(payload)
    assert "medical_admission" not in blob
    assert "quality_score" not in blob
    assert "admission" not in payload
    assert not hasattr(candidate, "quality_score")
    assert not hasattr(candidate, "medical_admission_unit_ids")


def test_nested_structured_table_remains_mutable_model_type():
    """Detached copy is recorded; nested StructuredTable is not deep-frozen."""
    candidate = _paragraph_a_to_table2_candidate()
    nested = candidate.blocks[1].table
    assert isinstance(nested, StructuredTable)
    nested.title = "in-place-change-on-nested"
    assert candidate.blocks[1].table.title == "in-place-change-on-nested"
    # Round-trip still works after nested mutation; do not claim deep immutability.
    restored = OrderedChapterDraftCandidate.model_validate(
        candidate.model_dump(mode="json")
    )
    assert restored.blocks[1].table.title == "in-place-change-on-nested"
    # Isolation from a deep copy of the dump remains intact.
    dump = copy.deepcopy(candidate.model_dump(mode="json"))
    dump["blocks"][1]["table"]["title"] = "dump-only"
    assert candidate.blocks[1].table.title == "in-place-change-on-nested"


def test_input_block_mutation_does_not_rewrite_candidate_table():
    original = _paragraph_a_to_table2_candidate()
    blocks = original.blocks
    copied = OrderedChapterDraftCandidate(
        chapter_contract_id=original.chapter_contract_id, node_id=original.node_id,
        known_evidence_ids=original.known_evidence_ids, blocks=blocks)
    blocks[1].table.rows[0].cells[0].text = 'changed outside copied candidate'
    assert copied.blocks[1].table.rows[0].cells[0].text == '主要终点'
