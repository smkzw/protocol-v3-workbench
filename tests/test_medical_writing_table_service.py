from __future__ import annotations

import copy

import pytest

from packages.contracts.workbench_contracts import StructuredTableRole

from services.api.app.medical_writing_tables import (
    MedicalWritingTableService,
    TableOperationError,
    TableVersionConflictError,
)


def _cell(
    cell_id: str,
    row: int,
    cell: int,
    grid: int,
    text: str,
    *,
    column_span: int = 1,
    row_span: int = 1,
    hidden: bool = False,
    merge_parent_cell_id: str | None = None,
    merge_parent_source_locator: str | None = None,
    style_role: str = "body",
) -> dict:
    locator = f"docx:table:4:row:{row}:cell:{cell}"
    return {
        "cell_id": cell_id,
        "text": text,
        "source_locator": locator,
        "row_index": row,
        "cell_index": cell,
        "grid_column_index": grid,
        "column_span": column_span,
        "row_span": row_span,
        "vertical_merge": "continue" if hidden else ("restart" if row_span > 1 else "none"),
        "hidden": hidden,
        "merge_parent_cell_id": merge_parent_cell_id,
        "merge_parent_source_locator": merge_parent_source_locator,
        "merge_parent_row_index": 0 if hidden else None,
        "merge_parent_cell_index": 0 if hidden else None,
        "merge_parent_grid_column_index": 0 if hidden else None,
        "style_role": style_role,
        "source_custom_marker": f"source-{cell_id}",
    }


def _rux_style_block() -> dict:
    """Synopsis-like table with a horizontal Word gridSpan and dense body rows."""
    return {
        "block_id": "mwblock_rux_summary",
        "block_type": "table",
        "source_locator": "docx:table:4",
        "source_kind": "original_protocol_docx",
        "body_order": 18,
        "table_index": 4,
        "table_id": "ptbl_rux_summary",
        "schema_version": "structured_table_v1",
        "header_row_count": 1,
        "column_count": 3,
        "rows": [
            [
                _cell("rux_h1", 0, 0, 0, "研究设计", column_span=2, style_role="header"),
                _cell("rux_h2", 0, 1, 2, "内容", style_role="header"),
            ],
            [
                _cell("rux_11", 1, 0, 0, "研究阶段"),
                _cell("rux_12", 1, 1, 1, "III期"),
                _cell("rux_13", 1, 2, 2, "随机、双盲、安慰剂对照"),
            ],
            [
                _cell("rux_21", 2, 0, 0, "主要终点"),
                _cell("rux_22", 2, 1, 1, "第8周"),
                _cell("rux_23", 2, 2, 2, "IGA-TS应答"),
            ],
        ],
        "editable": False,
        "source_document_version": "V1.3",
    }


def _d001_style_block() -> dict:
    """Eligibility/assessment-like table with a vertical merge continuation cell."""
    parent_locator = "docx:table:4:row:0:cell:0"
    return {
        "block_id": "mwblock_d001_assessment",
        "block_type": "table",
        "source_locator": "docx:table:4",
        "source_kind": "original_protocol_docx",
        "body_order": 32,
        "table_index": 4,
        "table_id": "ptbl_d001_assessment",
        "schema_version": "structured_table_v1",
        "header_row_count": 0,
        "column_count": 3,
        "rows": [
            [
                _cell("d_parent", 0, 0, 0, "筛选期", row_span=2),
                _cell("d_01", 0, 1, 1, "访视1"),
                _cell("d_02", 0, 2, 2, "知情同意"),
            ],
            [
                _cell(
                    "d_cont",
                    1,
                    0,
                    0,
                    "",
                    hidden=True,
                    merge_parent_cell_id="d_parent",
                    merge_parent_source_locator=parent_locator,
                ),
                _cell("d_11", 1, 1, 1, "访视2"),
                _cell("d_12", 1, 2, 2, "实验室检查"),
            ],
            [
                _cell("d_20", 2, 0, 0, "治疗期"),
                _cell("d_21", 2, 1, 1, "第1天"),
                _cell("d_22", 2, 2, 2, "随机给药"),
            ],
        ],
        "editable": False,
        "source_document_version": "V1.0",
    }


def _plain_block() -> dict:
    block = _rux_style_block()
    block["table_id"] = "ptbl_plain"
    block["block_id"] = "mwblock_plain"
    block["header_row_count"] = 0
    block["rows"] = [
        [_cell("p00", 0, 0, 0, "A"), _cell("p01", 0, 1, 1, "B")],
        [_cell("p10", 1, 0, 0, "C"), _cell("p11", 1, 1, 1, "D")],
        [_cell("p20", 2, 0, 0, "E"), _cell("p21", 2, 1, 1, "F")],
    ]
    block["column_count"] = 2
    return block


def test_maps_rux_horizontal_merge_with_stable_ids_and_round_trip_source_fields():
    service = MedicalWritingTableService()
    block = _rux_style_block()

    first = service.from_table_block(block)
    second = service.from_table_block(copy.deepcopy(block))

    assert [column.column_id for column in first.columns] == [
        column.column_id for column in second.columns
    ]
    assert [row.row_id for row in first.rows] == [row.row_id for row in second.rows]
    assert first.rows[0].cells[0].column_span == 2
    assert first.rows[0].cells[0].source_locator == "docx:table:4:row:0:cell:0"

    round_trip = service.to_table_block(first)
    assert round_trip["source_document_version"] == "V1.3"
    assert round_trip["rows"][0][0]["source_custom_marker"] == "source-rux_h1"
    assert round_trip["rows"][0][0]["source_structure"]["column_span"] == 2
    assert round_trip["structured_table"]["source_lineage"] == ["docx:table:4"]


def test_table_role_round_trips_without_changing_legacy_source_fields():
    service = MedicalWritingTableService()
    block = _rux_style_block()
    block["structured_table"] = {
        "domain": "generic",
        "role": "protocol_synopsis",
    }

    table = service.from_table_block(block)
    round_trip = service.to_table_block(table)

    assert table.role == StructuredTableRole.PROTOCOL_SYNOPSIS
    assert round_trip["structured_table"]["role"] == "protocol_synopsis"
    assert round_trip["source_document_version"] == "V1.3"


def test_cell_rich_text_round_trips_and_can_be_edited_without_losing_plain_fallback():
    service = MedicalWritingTableService()
    block = _plain_block()
    block["rows"][0][0]["rich_text"] = {
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "content": [{"type": "text", "text": "A", "marks": [{"type": "bold"}]}],
        }],
    }

    table = service.from_table_block(block)
    assert table.rows[0].cells[0].rich_text["content"][0]["content"][0]["marks"] == [{"type": "bold"}]

    updated = service.apply_operations(
        table,
        [{
            "op": "edit_cell",
            "cell_id": "p00",
            "text": "A2",
            "rich_text": {
                "type": "doc",
                "content": [{
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "A2", "marks": [{"type": "underline"}]}],
                }],
            },
        }],
        expected_version=0,
    )
    round_trip = service.to_table_block(updated)

    assert round_trip["rows"][0][0]["text"] == "A2"
    assert round_trip["rows"][0][0]["rich_text"]["content"][0]["content"][0]["marks"] == [{"type": "underline"}]
    assert round_trip["structured_table"]["rows"][0]["cells"][0]["rich_text"] == round_trip["rows"][0][0]["rich_text"]


def test_plain_text_replacement_clears_stale_rich_text_so_word_cannot_render_old_content():
    service = MedicalWritingTableService()
    block = _plain_block()
    block["rows"][0][0]["rich_text"] = {
        "type": "paragraph",
        "content": [{"type": "text", "text": "旧富文本"}],
    }

    table = service.from_table_block(block)
    updated = service.apply_operations(
        table,
        [{"op": "edit_cell", "cell_id": "p00", "text": "新纯文本"}],
        expected_version=0,
    )
    round_trip = service.to_table_block(updated)

    assert round_trip["rows"][0][0]["text"] == "新纯文本"
    assert round_trip["rows"][0][0]["rich_text"] is None


def test_maps_d001_vertical_merge_and_split_restores_hidden_continuation():
    service = MedicalWritingTableService()
    table = service.from_table_block(_d001_style_block())

    continuation = next(cell for row in table.rows for cell in row.cells if cell.cell_id == "d_cont")
    assert continuation.semantic_value["_medical_writing_table"]["hidden"] is True
    assert continuation.provenance_lineage == [
        "docx:table:4:row:1:cell:0",
        "docx:table:4:row:0:cell:0",
    ]

    split = service.apply_operations(
        table,
        [{"op": "split_cell", "cell_id": "d_parent"}],
        expected_version=0,
    )
    restored = next(cell for row in split.rows for cell in row.cells if cell.cell_id == "d_cont")
    assert split.version == 1
    assert restored.semantic_value["_medical_writing_table"]["hidden"] is False
    assert restored.source_locator == "docx:table:4:row:1:cell:0"
    assert service.to_table_block(split)["rows"][1][0]["source_custom_marker"] == "source-d_cont"


def test_structural_batch_uses_stable_ids_and_supports_row_column_edit_move_delete_and_header():
    service = MedicalWritingTableService()
    table = service.from_table_block(_plain_block())
    row_ids = [row.row_id for row in table.rows]
    column_ids = [column.column_id for column in table.columns]

    inserted = service.apply_operations(
        table,
        [
            {"op": "insert_row", "row_id": "row_added", "after_row_id": row_ids[0]},
            {"op": "insert_column", "column_id": "col_added", "after_column_id": column_ids[0]},
            {"op": "edit_cell", "cell_id": "p11", "text": "修订后的D"},
            {"op": "set_header_role", "target_id": row_ids[0]},
        ],
        expected_version=0,
    )
    assert inserted.version == 1
    assert next(cell for row in inserted.rows for cell in row.cells if cell.cell_id == "p11").text == "修订后的D"
    assert inserted.rows[0].style_role == "header"
    assert inserted.header_row_count == 1
    assert {column.column_id for column in inserted.columns} == {*column_ids, "col_added"}
    assert len(next(row for row in inserted.rows if row.row_id == "row_added").cells) == 3

    moved = service.apply_operations(
        inserted,
        [
            {"op": "move_row", "row_id": row_ids[2], "before_row_id": row_ids[0]},
            {"op": "move_column", "column_id": column_ids[1], "before_column_id": column_ids[0]},
            {"op": "delete_row", "row_id": "row_added"},
            {"op": "delete_column", "column_id": "col_added"},
        ],
        expected_version=1,
    )
    assert moved.version == 2
    assert [row.row_id for row in moved.rows] == [row_ids[2], row_ids[0], row_ids[1]]
    assert [column.column_id for column in moved.columns] == [column_ids[1], column_ids[0]]
    assert {cell.cell_id for row in moved.rows for cell in row.cells} == {
        "p00",
        "p01",
        "p10",
        "p11",
        "p20",
        "p21",
    }


def test_merge_and_split_keep_child_ids_and_text_without_data_loss():
    service = MedicalWritingTableService()
    table = service.from_table_block(_plain_block())

    merged = service.apply_operations(
        table,
        [{"op": "merge_cells", "cell_ids": ["p00", "p01", "p10", "p11"]}],
        expected_version=0,
    )
    parent = next(cell for row in merged.rows for cell in row.cells if cell.cell_id == "p00")
    child = next(cell for row in merged.rows for cell in row.cells if cell.cell_id == "p11")
    assert (parent.row_span, parent.column_span) == (2, 2)
    assert child.text == "D"
    assert child.semantic_value["_medical_writing_table"]["hidden"] is True

    split = service.apply_operations(
        merged,
        [{"op": "split_cell", "cell_id": "p00"}],
        expected_version=1,
    )
    assert next(cell for row in split.rows for cell in row.cells if cell.cell_id == "p11").text == "D"
    assert all(
        not cell.semantic_value["_medical_writing_table"]["hidden"]
        for row in split.rows[:2]
        for cell in row.cells
    )


def test_note_lifecycle_and_orphan_guard_are_atomic():
    service = MedicalWritingTableService()
    table = service.from_table_block(_plain_block())
    target_row_id = table.rows[1].row_id

    noted = service.apply_operations(
        table,
        [
            {
                "op": "attach_note",
                "note": {
                    "note_id": "note_timing",
                    "marker": "a",
                    "note_type": "timing_rule",
                    "text": "给药前完成",
                    "target_ids": [target_row_id, "p10"],
                    "source_refs": ["docx:paragraph:99"],
                },
            },
            {
                "op": "update_note",
                "note_id": "note_timing",
                "patch": {"text": "首次给药前完成"},
            },
        ],
        expected_version=0,
    )
    assert noted.notes[0].text == "首次给药前完成"
    assert "note_timing" in next(
        cell for row in noted.rows for cell in row.cells if cell.cell_id == "p10"
    ).note_refs

    with pytest.raises(TableOperationError, match="orphan"):
        service.apply_operations(
            noted,
            [{"op": "delete_row", "row_id": target_row_id}],
            expected_version=1,
        )
    assert len(noted.rows) == 3
    assert noted.version == 1

    cleaned = service.apply_operations(
        noted,
        [
            {"op": "remove_note", "note_id": "note_timing"},
            {"op": "delete_row", "row_id": target_row_id},
        ],
        expected_version=1,
    )
    assert cleaned.notes == []
    assert target_row_id not in {row.row_id for row in cleaned.rows}


def test_version_conflict_is_explicit_and_does_not_apply_operation():
    service = MedicalWritingTableService()
    table = service.from_table_block(_plain_block())

    with pytest.raises(TableVersionConflictError, match="expected 9, current 0"):
        service.apply_operations(
            table,
            [{"op": "edit_cell", "cell_id": "p00", "text": "不得写入"}],
            expected_version=9,
        )
    assert next(cell for row in table.rows for cell in row.cells if cell.cell_id == "p00").text == "A"


def test_failed_batch_is_atomic_and_rejects_position_based_or_unknown_targets():
    service = MedicalWritingTableService()
    table = service.from_table_block(_plain_block())

    with pytest.raises(TableOperationError, match="unknown row id"):
        service.apply_operations(
            table,
            [
                {"op": "edit_cell", "cell_id": "p00", "text": "临时修订"},
                {"op": "delete_row", "row_id": "row-at-index-1", "row_index": 1},
            ],
            expected_version=0,
        )
    assert table.version == 0
    assert next(cell for row in table.rows for cell in row.cells if cell.cell_id == "p00").text == "A"


def test_round_trip_keeps_structure_ids_and_version_for_repeated_working_copy_mapping():
    service = MedicalWritingTableService()
    block = _plain_block()
    block["structured_table"] = {"domain_extension": {"soa_mapping_state": "unmapped"}}
    table = service.from_table_block(block)
    changed = service.apply_operations(
        table,
        [{"op": "insert_column", "column_id": "new_visit", "label": "第4周"}],
        expected_version=0,
    )

    output = service.to_table_block(changed)
    remapped = service.from_table_block(output)

    assert remapped.version == 1
    assert [column.column_id for column in remapped.columns] == [
        column.column_id for column in changed.columns
    ]
    assert [row.row_id for row in remapped.rows] == [row.row_id for row in changed.rows]
    assert {
        cell.cell_id for row in remapped.rows for cell in row.cells
    } == {cell.cell_id for row in changed.rows for cell in row.cells}
    assert output["structured_table"]["domain_extension"] == {
        "soa_mapping_state": "unmapped"
    }


def test_source_locator_and_source_structure_survive_reordering_and_cell_edit():
    service = MedicalWritingTableService()
    block = _plain_block()
    table = service.from_table_block(block)
    first_row_id, second_row_id = table.rows[0].row_id, table.rows[1].row_id

    changed = service.apply_operations(
        table,
        [
            {"op": "edit_cell", "cell_id": "p10", "text": "C修订"},
            {"op": "move_row", "row_id": second_row_id, "before_row_id": first_row_id},
        ],
        expected_version=0,
    )
    output = service.to_table_block(changed)
    moved_cell = next(cell for row in output["rows"] for cell in row if cell["cell_id"] == "p10")

    assert moved_cell["text"] == "C修订"
    assert moved_cell["source_locator"] == "docx:table:4:row:1:cell:0"
    assert moved_cell["row_index"] == 1
    assert moved_cell["source_structure"]["row_index"] == 1
    assert moved_cell["provenance_lineage"] == ["docx:table:4:row:1:cell:0"]
    assert output["source_document_version"] == "V1.3"
