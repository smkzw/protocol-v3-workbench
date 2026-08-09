from __future__ import annotations

import copy
import hashlib
import uuid
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    StructuredTable,
    StructuredTableCell,
    StructuredTableColumn,
    StructuredTableDomain,
    StructuredTableRole,
    StructuredTableNote,
    StructuredTableRow,
)

from .medical_writing_table_domain_profiles import (
    MedicalWritingTableDomainProfileService,
)


SERVICE_META_KEY = "_medical_writing_table"
STRUCTURE_KEY = "structured_table"


class MedicalWritingTableError(ValueError):
    """Base error for deterministic structured-table operations."""


class TableVersionConflictError(MedicalWritingTableError):
    """Raised when a caller edits a stale table version."""


class TableOperationError(MedicalWritingTableError):
    """Raised when a requested operation is invalid or ambiguous."""


class MedicalWritingTableService:
    """Maps source table blocks and applies stable-ID structural edits atomically."""

    def from_table_block(
        self,
        block: Mapping[str, Any],
        *,
        domain: StructuredTableDomain | str | None = None,
    ) -> StructuredTable:
        source_block = copy.deepcopy(dict(block))
        if source_block.get("block_type") != "table":
            raise MedicalWritingTableError("structured table mapping requires a table block")
        rows_payload = source_block.get("rows")
        if not isinstance(rows_payload, list):
            raise MedicalWritingTableError("table block rows must be a list")

        table_id = str(source_block.get("table_id") or "").strip()
        block_id = str(source_block.get("block_id") or "").strip()
        if not table_id or not block_id:
            raise MedicalWritingTableError("table block must contain table_id and block_id")
        structure = source_block.get(STRUCTURE_KEY)
        structure = structure if isinstance(structure, dict) else {}
        column_count = self._column_count(source_block, rows_payload)
        column_ids = self._structure_ids(
            structure.get("column_ids"),
            column_count,
            "mwcol",
            table_id,
        )
        columns = [
            StructuredTableColumn(
                column_id=column_id,
                order=order,
                label=self._column_label(structure, order),
                style_role=self._column_role(structure, order),
                width_twips=self._column_width(structure, order),
                source_locator=self._column_source_locator(structure, order),
                semantic_role=self._column_semantic_role(structure, order),
            )
            for order, column_id in enumerate(column_ids)
        ]
        row_ids = self._structure_ids(
            structure.get("row_ids"),
            len(rows_payload),
            "mwrow",
            table_id,
        )

        rows: list[StructuredTableRow] = []
        for row_order, raw_row in enumerate(rows_payload):
            if not isinstance(raw_row, list):
                raise MedicalWritingTableError("each table row must be a list")
            row_id = row_ids[row_order]
            row_style = self._row_role(structure, row_order, source_block)
            cells: list[StructuredTableCell] = []
            for raw_cell in raw_row:
                if not isinstance(raw_cell, dict):
                    raise MedicalWritingTableError("each table cell must be an object")
                grid_column = self._nonnegative_int(raw_cell.get("grid_column_index"), 0)
                structured_column_id = str(raw_cell.get("structure_column_id") or "")
                if structured_column_id:
                    if structured_column_id not in column_ids:
                        raise MedicalWritingTableError(
                            "table cell references an unknown structured column"
                        )
                    column_id = structured_column_id
                else:
                    if grid_column >= len(column_ids):
                        raise MedicalWritingTableError(
                            "table cell grid column exceeds declared column count"
                        )
                    column_id = column_ids[grid_column]
                cell_id = str(raw_cell.get("cell_id") or "").strip()
                if not cell_id:
                    raise MedicalWritingTableError("table cell must contain a stable cell_id")
                source_locator = str(raw_cell.get("source_locator") or "")
                lineage = self._lineage(raw_cell, source_locator)
                metadata = {
                    "source_fields": copy.deepcopy(raw_cell),
                    "hidden": bool(raw_cell.get("hidden", False)),
                    "merge_parent_cell_id": raw_cell.get("merge_parent_cell_id"),
                    "merge_parent_source_locator": raw_cell.get(
                        "merge_parent_source_locator"
                    ),
                    "generated": bool(raw_cell.get("structure_generated", False)),
                }
                cells.append(
                    StructuredTableCell(
                        cell_id=cell_id,
                        row_id=row_id,
                        column_id=column_id,
                        text=str(raw_cell.get("text") or ""),
                        rich_text=(
                            copy.deepcopy(raw_cell.get("rich_text"))
                            if isinstance(raw_cell.get("rich_text"), dict)
                            else None
                        ),
                        semantic_value={SERVICE_META_KEY: metadata},
                        row_span=self._positive_int(raw_cell.get("row_span"), 1),
                        column_span=self._positive_int(raw_cell.get("column_span"), 1),
                        style_role=str(raw_cell.get("style_role") or row_style),
                        source_locator=source_locator,
                        provenance_lineage=lineage,
                        note_refs=self._string_list(raw_cell.get("note_refs")),
                        condition_expression=str(
                            raw_cell.get("condition_expression") or ""
                        ),
                    )
                )
            rows.append(
                StructuredTableRow(
                    row_id=row_id,
                    order=row_order,
                    label=self._row_label(structure, row_order),
                    style_role=row_style,
                    source_locator=self._row_source_locator(raw_row),
                    cells=cells,
                )
            )

        notes_payload = structure.get("notes", [])
        if not isinstance(notes_payload, list):
            raise MedicalWritingTableError("structured table notes must be a list")
        notes = [StructuredTableNote.model_validate(note) for note in notes_payload]
        resolved_domain = domain or structure.get("domain") or StructuredTableDomain.GENERIC
        table = StructuredTable(
            schema_version=str(
                structure.get("schema_version") or "structured_table_v1"
            ),
            table_id=table_id,
            block_id=block_id,
            domain=resolved_domain,
            role=structure.get("role") or StructuredTableRole.UNCLASSIFIED,
            title=str(structure.get("title") or source_block.get("title") or ""),
            source_locator=str(source_block.get("source_locator") or ""),
            version=self._nonnegative_int(structure.get("version"), 0),
            review_state=structure.get("review_state", "ai_draft"),
            header_row_count=self._nonnegative_int(
                source_block.get("header_row_count"), 0
            ),
            columns=columns,
            rows=rows,
            notes=notes,
            word_layout={
                **(
                    copy.deepcopy(structure.get("word_layout"))
                    if isinstance(structure.get("word_layout"), dict)
                    else {}
                ),
                SERVICE_META_KEY: {
                    "source_block": source_block,
                    "source_lineage": self._table_lineage(source_block),
                }
            },
        )
        self._validate_layout(table)
        service_metadata = table.word_layout[SERVICE_META_KEY]
        preserved_holes = self._preserved_source_grid_holes(structure)
        if (
            preserved_holes is None
            and source_block.get("source_kind") == "original_protocol_docx"
            and table.version == 0
        ):
            preserved_holes = self._grid_hole_positions(table)
        if preserved_holes is not None:
            service_metadata["source_grid_holes"] = [
                [row_index, column_index]
                for row_index, column_index in sorted(preserved_holes)
            ]
        return table

    def apply_operations(
        self,
        table: StructuredTable,
        operations: Sequence[Mapping[str, Any]],
        *,
        expected_version: int,
    ) -> StructuredTable:
        if table.version != expected_version:
            raise TableVersionConflictError(
                f"table version conflict: expected {expected_version}, current {table.version}"
            )
        if not operations:
            return table.model_copy(deep=True)

        candidate = table.model_copy(deep=True)
        for index, operation in enumerate(operations):
            try:
                self._apply_operation(candidate, dict(operation))
            except TableVersionConflictError:
                raise
            except MedicalWritingTableError as exc:
                raise TableOperationError(f"operation {index} failed: {exc}") from exc
            except (KeyError, TypeError, ValueError) as exc:
                raise TableOperationError(f"operation {index} is invalid: {exc}") from exc
        self._normalize_orders(candidate)
        candidate.version += 1
        candidate.header_row_count = self._header_row_count(candidate)
        try:
            validated = StructuredTable.model_validate(candidate.model_dump(mode="python"))
            self._validate_layout(validated)
        except (ValidationError, ValueError) as exc:
            message = str(exc)
            if "unknown or empty target" in message:
                message = f"operation would orphan a table note: {message}"
            raise TableOperationError(message) from exc
        return validated

    def to_table_block(self, table: StructuredTable) -> dict[str, Any]:
        self._validate_layout(table)
        service_layout = table.word_layout.get(SERVICE_META_KEY, {})
        source_block = service_layout.get("source_block", {})
        block = copy.deepcopy(source_block) if isinstance(source_block, dict) else {}
        block.update(
            {
                "block_id": table.block_id,
                "block_type": "table",
                "table_id": table.table_id,
                "source_locator": table.source_locator,
                "header_row_count": table.header_row_count,
                "column_count": len(table.columns),
            }
        )
        columns = sorted(table.columns, key=lambda column: column.order)
        rows = sorted(table.rows, key=lambda row: row.order)
        column_order = {column.column_id: column.order for column in columns}
        block["rows"] = [
            [
                self._cell_to_block(cell, row, column_order)
                for cell in sorted(
                    row.cells,
                    key=lambda item: (
                        column_order[item.column_id],
                        1 if self._cell_meta(item).get("hidden") else 0,
                        item.cell_id,
                    ),
                )
            ]
            for row in rows
        ]
        original_structure = block.get(STRUCTURE_KEY)
        structure_payload = (
            copy.deepcopy(original_structure)
            if isinstance(original_structure, dict)
            else {}
        )
        structure_payload.update({
            "schema_version": table.schema_version,
            "version": table.version,
            "domain": table.domain.value,
            "role": table.role.value,
            "title": table.title,
            "review_state": table.review_state.value,
            "row_ids": [row.row_id for row in rows],
            "row_labels": [row.label for row in rows],
            "row_style_roles": [row.style_role for row in rows],
            "column_ids": [column.column_id for column in columns],
            "column_labels": [column.label for column in columns],
            "column_style_roles": [column.style_role for column in columns],
            "column_width_twips": [column.width_twips for column in columns],
            "column_source_locators": [column.source_locator for column in columns],
            "column_semantic_roles": [column.semantic_role for column in columns],
            "notes": [note.model_dump(mode="json") for note in table.notes],
            "word_layout": {
                key: copy.deepcopy(value)
                for key, value in table.word_layout.items()
                if key != SERVICE_META_KEY
            },
            "source_lineage": copy.deepcopy(service_layout.get("source_lineage", [])),
        })
        if "source_grid_holes" in service_layout:
            structure_payload["source_grid_holes"] = copy.deepcopy(
                service_layout["source_grid_holes"]
            )
        structure_payload["columns"] = [
            {
                "column_id": column.column_id,
                "order": column.order,
                "label": column.label,
                "style_role": column.style_role,
                "width_twips": column.width_twips,
                "source_locator": column.source_locator,
                "semantic_role": column.semantic_role,
            }
            for column in columns
        ]
        structure_payload["rows"] = [
            {
                "row_id": row.row_id,
                "order": row.order,
                "label": row.label,
                "style_role": row.style_role,
                "source_locator": row.source_locator,
                "cells": [
                    {
                        **copy.deepcopy(raw_cell),
                        "row_id": row.row_id,
                        "column_id": raw_cell.get("structure_column_id")
                        or raw_cell.get("column_id"),
                    }
                    for raw_cell in block["rows"][row_index]
                ],
            }
            for row_index, row in enumerate(rows)
        ]
        block[STRUCTURE_KEY] = structure_payload
        return block

    def _apply_operation(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        operation_type = str(operation.get("op") or "").strip()
        handlers = {
            "insert_row": self._insert_row,
            "delete_row": self._delete_row,
            "move_row": self._move_row,
            "insert_column": self._insert_column,
            "delete_column": self._delete_column,
            "move_column": self._move_column,
            "merge_cells": self._merge_cells,
            "split_cell": self._split_cell,
            "edit_cell": self._edit_cell,
            "set_header_role": self._set_header_role,
            "attach_note": self._attach_note,
            "update_note": self._update_note,
            "remove_note": self._remove_note,
        }
        handler = handlers.get(operation_type)
        if handler is None:
            raise TableOperationError(f"unsupported table operation: {operation_type or '<empty>'}")
        handler(table, operation)

    def _insert_row(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        index = self._insertion_index(table.rows, operation, "row")
        self._assert_row_boundary_is_unmerged(table, index)
        row_id = str(operation.get("row_id") or self._new_id("mwrow"))
        if row_id in {row.row_id for row in table.rows}:
            raise TableOperationError(f"row id already exists: {row_id}")
        row = StructuredTableRow(
            row_id=row_id,
            order=index,
            label=str(operation.get("label") or ""),
            style_role=str(operation.get("style_role") or "body"),
            source_locator="",
            cells=[
                self._new_cell(row_id, column.column_id, operation.get("style_role", "body"))
                for column in sorted(table.columns, key=lambda item: item.order)
            ],
        )
        table.rows.insert(index, row)

    def _delete_row(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        if len(table.rows) <= 1:
            raise TableOperationError("a structured table must retain at least one row")
        row = self._row(table, self._required_id(operation, "row_id"))
        self._assert_row_not_merged(table, row)
        table.rows.remove(row)

    def _move_row(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        if self._has_merges(table):
            raise TableOperationError("split merged cells before moving rows")
        row = self._row(table, self._required_id(operation, "row_id"))
        table.rows.remove(row)
        index = self._insertion_index(table.rows, operation, "row")
        table.rows.insert(index, row)

    def _insert_column(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        index = self._insertion_index(table.columns, operation, "column")
        self._assert_column_boundary_is_unmerged(table, index)
        column_id = str(operation.get("column_id") or self._new_id("mwcol"))
        if column_id in {column.column_id for column in table.columns}:
            raise TableOperationError(f"column id already exists: {column_id}")
        table.columns.insert(
            index,
            StructuredTableColumn(
                column_id=column_id,
                order=index,
                label=str(operation.get("label") or ""),
                style_role=str(operation.get("style_role") or "body"),
                width_twips=operation.get("width_twips"),
                source_locator="",
            ),
        )
        for row in table.rows:
            row.cells.append(
                self._new_cell(row.row_id, column_id, operation.get("style_role", "body"))
            )

    def _delete_column(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        if len(table.columns) <= 1:
            raise TableOperationError("a structured table must retain at least one column")
        column = self._column(table, self._required_id(operation, "column_id"))
        for row in table.rows:
            for cell in row.cells:
                metadata = self._cell_meta(cell)
                start = self._column(table, cell.column_id).order
                if metadata.get("hidden") and cell.column_id == column.column_id:
                    raise TableOperationError("split merged cells before deleting this column")
                if not metadata.get("hidden") and start <= column.order < start + cell.column_span:
                    if cell.column_span > 1:
                        raise TableOperationError("split merged cells before deleting this column")
        table.columns.remove(column)
        for row in table.rows:
            row.cells = [cell for cell in row.cells if cell.column_id != column.column_id]

    def _move_column(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        if self._has_merges(table):
            raise TableOperationError("split merged cells before moving columns")
        column = self._column(table, self._required_id(operation, "column_id"))
        table.columns.remove(column)
        index = self._insertion_index(table.columns, operation, "column")
        table.columns.insert(index, column)

    def _merge_cells(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        cell_ids = self._string_list(operation.get("cell_ids"))
        if len(cell_ids) < 2:
            raise TableOperationError("merge_cells requires at least two cell ids")
        cells = [self._cell(table, cell_id) for cell_id in cell_ids]
        if any(
            cell.row_span != 1
            or cell.column_span != 1
            or self._cell_meta(cell).get("hidden")
            for cell in cells
        ):
            raise TableOperationError("only visible, unmerged cells can be merged")
        row_order = {row.row_id: row.order for row in table.rows}
        column_order = {column.column_id: column.order for column in table.columns}
        row_indexes = sorted({row_order[cell.row_id] for cell in cells})
        column_indexes = sorted({column_order[cell.column_id] for cell in cells})
        expected = {
            (row_index, column_index)
            for row_index in range(row_indexes[0], row_indexes[-1] + 1)
            for column_index in range(column_indexes[0], column_indexes[-1] + 1)
        }
        actual = {
            (row_order[cell.row_id], column_order[cell.column_id]) for cell in cells
        }
        if actual != expected:
            raise TableOperationError("merge selection must be one contiguous rectangle")
        parent = min(
            cells,
            key=lambda cell: (row_order[cell.row_id], column_order[cell.column_id]),
        )
        parent.row_span = len(row_indexes)
        parent.column_span = len(column_indexes)
        for child in cells:
            if child.cell_id == parent.cell_id:
                continue
            metadata = self._cell_meta(child)
            metadata["hidden"] = True
            metadata["merge_parent_cell_id"] = parent.cell_id
            metadata["merge_parent_source_locator"] = parent.source_locator
            self._set_cell_meta(child, metadata)

    def _split_cell(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        parent = self._cell(table, self._required_id(operation, "cell_id"))
        if self._cell_meta(parent).get("hidden"):
            raise TableOperationError("split_cell requires the visible merge parent")
        if parent.row_span == 1 and parent.column_span == 1:
            raise TableOperationError("cell is not merged")
        rows = sorted(table.rows, key=lambda row: row.order)
        columns = sorted(table.columns, key=lambda column: column.order)
        parent_row = self._row(table, parent.row_id)
        row_indexes = range(parent_row.order, parent_row.order + parent.row_span)
        parent_column = self._column(table, parent.column_id)
        column_indexes = range(parent_column.order, parent_column.order + parent.column_span)
        for row_index in row_indexes:
            for column_index in column_indexes:
                if row_index == parent_row.order and column_index == parent_column.order:
                    continue
                row = rows[row_index]
                column = columns[column_index]
                child = next(
                    (
                        cell
                        for cell in row.cells
                        if cell.column_id == column.column_id
                        and self._cell_meta(cell).get("merge_parent_cell_id") == parent.cell_id
                    ),
                    None,
                )
                if child is None:
                    child = self._new_cell(row.row_id, column.column_id, parent.style_role)
                    child.provenance_lineage = list(parent.provenance_lineage)
                    row.cells.append(child)
                metadata = self._cell_meta(child)
                metadata["hidden"] = False
                metadata["merge_parent_cell_id"] = None
                metadata["merge_parent_source_locator"] = None
                self._set_cell_meta(child, metadata)
                child.row_span = 1
                child.column_span = 1
        parent.row_span = 1
        parent.column_span = 1

    def _edit_cell(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        cell = self._cell(table, self._required_id(operation, "cell_id"))
        if self._cell_meta(cell).get("hidden"):
            raise TableOperationError("hidden merge-continuation cells are not directly editable")
        if "text" not in operation and "rich_text" not in operation:
            raise TableOperationError("edit_cell requires text or rich_text")
        if "rich_text" in operation:
            rich_text = operation["rich_text"]
            if rich_text is not None and not isinstance(rich_text, dict):
                raise TableOperationError("edit_cell rich_text must be an object or null")
            cell.rich_text = copy.deepcopy(rich_text)
        if "text" in operation:
            cell.text = str(operation["text"])
            if "rich_text" not in operation:
                cell.rich_text = None

    def _set_header_role(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        target_id = self._required_id(operation, "target_id")
        style_role = str(operation.get("style_role") or "header")
        propagate = bool(operation.get("propagate", True))
        for row in table.rows:
            if row.row_id == target_id:
                row.style_role = style_role
                if propagate:
                    for cell in row.cells:
                        cell.style_role = style_role
                return
        for column in table.columns:
            if column.column_id == target_id:
                column.style_role = style_role
                if propagate:
                    for row in table.rows:
                        for cell in row.cells:
                            if cell.column_id == target_id:
                                cell.style_role = style_role
                return
        self._cell(table, target_id).style_role = style_role

    def _attach_note(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        payload = copy.deepcopy(operation.get("note") or {})
        payload.setdefault("note_id", self._new_id("mwnote"))
        note = StructuredTableNote.model_validate(payload)
        if note.note_id in {item.note_id for item in table.notes}:
            raise TableOperationError(f"note id already exists: {note.note_id}")
        self._assert_note_targets_exist(table, note)
        table.notes.append(note)
        self._sync_note_refs(table, note)

    def _update_note(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        note_id = self._required_id(operation, "note_id")
        note = self._note(table, note_id)
        patch = copy.deepcopy(operation.get("patch") or {})
        if "note_id" in patch and patch["note_id"] != note_id:
            raise TableOperationError("note_id is immutable")
        updated = StructuredTableNote.model_validate(
            {**note.model_dump(mode="python"), **patch, "note_id": note_id}
        )
        self._assert_note_targets_exist(table, updated)
        table.notes[table.notes.index(note)] = updated
        self._remove_note_refs(table, note_id)
        self._sync_note_refs(table, updated)

    def _remove_note(self, table: StructuredTable, operation: dict[str, Any]) -> None:
        note_id = self._required_id(operation, "note_id")
        note = self._note(table, note_id)
        table.notes.remove(note)
        self._remove_note_refs(table, note_id)

    def _cell_to_block(
        self,
        cell: StructuredTableCell,
        row: StructuredTableRow,
        column_order: dict[str, int],
    ) -> dict[str, Any]:
        metadata = self._cell_meta(cell)
        source_fields = metadata.get("source_fields")
        result = copy.deepcopy(source_fields) if isinstance(source_fields, dict) else {}
        source_structure = {
            key: copy.deepcopy(value)
            for key, value in result.items()
            if key
            in {
                "source_locator",
                "row_index",
                "cell_index",
                "grid_column_index",
                "column_span",
                "row_span",
                "vertical_merge",
                "hidden",
                "merge_parent_cell_id",
                "merge_parent_source_locator",
                "merge_parent_row_index",
                "merge_parent_cell_index",
                "merge_parent_grid_column_index",
                "style_role",
            }
        }
        result.update(
            {
                "cell_id": cell.cell_id,
                "text": cell.text,
                "rich_text": copy.deepcopy(cell.rich_text),
                "source_locator": cell.source_locator,
                "column_span": cell.column_span,
                "row_span": cell.row_span,
                "style_role": cell.style_role,
                "hidden": bool(metadata.get("hidden", False)),
                "merge_parent_cell_id": metadata.get("merge_parent_cell_id"),
                "merge_parent_source_locator": metadata.get(
                    "merge_parent_source_locator"
                ),
                "structure_row_id": row.row_id,
                "structure_column_id": cell.column_id,
                "structure_row_order": row.order,
                "structure_column_order": column_order[cell.column_id],
                "structure_generated": bool(metadata.get("generated", False)),
                "provenance_lineage": list(cell.provenance_lineage),
                "note_refs": list(cell.note_refs),
                "condition_expression": cell.condition_expression,
                "source_structure": source_structure,
            }
        )
        if not source_fields:
            result.setdefault("row_index", row.order)
            result.setdefault("cell_index", column_order[cell.column_id])
            result.setdefault("grid_column_index", column_order[cell.column_id])
            result.setdefault("vertical_merge", "none")
            result.setdefault("merge_parent_row_index", None)
            result.setdefault("merge_parent_cell_index", None)
            result.setdefault("merge_parent_grid_column_index", None)
            result.setdefault("source_kind", "working_copy_generated")
        return result

    def _validate_layout(self, table: StructuredTable) -> None:
        columns = sorted(table.columns, key=lambda column: column.order)
        rows = sorted(table.rows, key=lambda row: row.order)
        if [column.order for column in columns] != list(range(len(columns))):
            raise TableOperationError("table column order must be contiguous")
        if [row.order for row in rows] != list(range(len(rows))):
            raise TableOperationError("table row order must be contiguous")
        column_order = {column.column_id: column.order for column in columns}
        row_order = {row.row_id: row.order for row in rows}
        cell_by_id = {cell.cell_id: cell for row in rows for cell in row.cells}
        occupied: dict[tuple[int, int], str] = {}
        for row in rows:
            for cell in row.cells:
                metadata = self._cell_meta(cell)
                if metadata.get("hidden"):
                    parent_id = metadata.get("merge_parent_cell_id")
                    if not parent_id or parent_id not in cell_by_id:
                        raise TableOperationError(
                            f"hidden cell {cell.cell_id} has no valid merge parent"
                        )
                    parent = cell_by_id[parent_id]
                    parent_row = row_order[parent.row_id]
                    parent_column = column_order[parent.column_id]
                    child_row = row_order[cell.row_id]
                    child_column = column_order[cell.column_id]
                    if not (
                        parent_row <= child_row < parent_row + parent.row_span
                        and parent_column
                        <= child_column
                        < parent_column + parent.column_span
                    ):
                        raise TableOperationError(
                            f"hidden cell {cell.cell_id} lies outside its merge parent span"
                        )
                    continue
                start_row = row_order[cell.row_id]
                start_column = column_order[cell.column_id]
                if start_row + cell.row_span > len(rows) or start_column + cell.column_span > len(columns):
                    raise TableOperationError(f"cell span exceeds table bounds: {cell.cell_id}")
                for row_index in range(start_row, start_row + cell.row_span):
                    for column_index in range(
                        start_column, start_column + cell.column_span
                    ):
                        position = (row_index, column_index)
                        if position in occupied:
                            raise TableOperationError(
                                f"visible cell spans overlap at row {row_index}, column {column_index}"
                            )
                        occupied[position] = cell.cell_id
        MedicalWritingTableDomainProfileService().assert_valid(table)

    def _grid_hole_positions(self, table: StructuredTable) -> set[tuple[int, int]]:
        columns = sorted(table.columns, key=lambda column: column.order)
        rows = sorted(table.rows, key=lambda row: row.order)
        column_order = {column.column_id: column.order for column in columns}
        row_order = {row.row_id: row.order for row in rows}
        occupied: set[tuple[int, int]] = set()
        for row in rows:
            for cell in row.cells:
                if self._cell_meta(cell).get("hidden"):
                    continue
                start_row = row_order[cell.row_id]
                start_column = column_order[cell.column_id]
                for row_index in range(start_row, start_row + cell.row_span):
                    for column_index in range(
                        start_column, start_column + cell.column_span
                    ):
                        occupied.add((row_index, column_index))
        return {
            (row_index, column_index)
            for row_index in range(len(rows))
            for column_index in range(len(columns))
            if (row_index, column_index) not in occupied
        }

    @staticmethod
    def _preserved_source_grid_holes(
        structure: Mapping[str, Any],
    ) -> set[tuple[int, int]] | None:
        raw = structure.get("source_grid_holes")
        if raw is None:
            return None
        if not isinstance(raw, list):
            raise MedicalWritingTableError(
                "structured table source_grid_holes must be a list"
            )
        holes: set[tuple[int, int]] = set()
        for position in raw:
            if (
                not isinstance(position, list)
                or len(position) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                    for value in position
                )
            ):
                raise MedicalWritingTableError(
                    "structured table source_grid_holes contains an invalid position"
                )
            holes.add((position[0], position[1]))
        return holes

    @staticmethod
    def _normalize_orders(table: StructuredTable) -> None:
        for order, row in enumerate(table.rows):
            row.order = order
        for order, column in enumerate(table.columns):
            column.order = order

    @staticmethod
    def _header_row_count(table: StructuredTable) -> int:
        count = 0
        for row in sorted(table.rows, key=lambda item: item.order):
            if row.style_role != "header":
                break
            count += 1
        return count

    def _assert_note_targets_exist(
        self, table: StructuredTable, note: StructuredTableNote
    ) -> None:
        targets = self._target_ids(table)
        if not note.target_ids or not set(note.target_ids).issubset(targets):
            raise TableOperationError("note has an unknown or empty target")

    @staticmethod
    def _target_ids(table: StructuredTable) -> set[str]:
        return {
            table.table_id,
            table.block_id,
            *(column.column_id for column in table.columns),
            *(row.row_id for row in table.rows),
            *(cell.cell_id for row in table.rows for cell in row.cells),
        }

    @staticmethod
    def _sync_note_refs(table: StructuredTable, note: StructuredTableNote) -> None:
        targets = set(note.target_ids)
        for row in table.rows:
            for cell in row.cells:
                if cell.cell_id in targets and note.note_id not in cell.note_refs:
                    cell.note_refs.append(note.note_id)

    @staticmethod
    def _remove_note_refs(table: StructuredTable, note_id: str) -> None:
        for row in table.rows:
            for cell in row.cells:
                cell.note_refs = [ref for ref in cell.note_refs if ref != note_id]

    @staticmethod
    def _cell_meta(cell: StructuredTableCell) -> dict[str, Any]:
        value = cell.semantic_value
        if isinstance(value, dict):
            metadata = value.get(SERVICE_META_KEY)
            if isinstance(metadata, dict):
                return copy.deepcopy(metadata)
        return {}

    @staticmethod
    def _set_cell_meta(cell: StructuredTableCell, metadata: dict[str, Any]) -> None:
        value = copy.deepcopy(cell.semantic_value) if isinstance(cell.semantic_value, dict) else {}
        value[SERVICE_META_KEY] = metadata
        cell.semantic_value = value

    def _new_cell(self, row_id: str, column_id: str, style_role: Any) -> StructuredTableCell:
        cell = StructuredTableCell(
            cell_id=self._new_id("mwcell"),
            row_id=row_id,
            column_id=column_id,
            style_role=str(style_role or "body"),
            semantic_value={},
            provenance_lineage=[],
        )
        self._set_cell_meta(
            cell,
            {
                "source_fields": {},
                "hidden": False,
                "merge_parent_cell_id": None,
                "merge_parent_source_locator": None,
                "generated": True,
            },
        )
        return cell

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _stable_id(prefix: str, table_id: str, suffix: str) -> str:
        digest = hashlib.sha256(f"{table_id}|{suffix}".encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{digest}"

    def _structure_ids(
        self,
        values: Any,
        count: int,
        prefix: str,
        table_id: str,
    ) -> list[str]:
        if isinstance(values, list) and len(values) == count and all(values):
            ids = [str(value) for value in values]
        elif values not in (None, []):
            raise MedicalWritingTableError(
                f"{prefix} ids do not match the current table structure"
            )
        else:
            ids = [self._stable_id(prefix, table_id, str(index)) for index in range(count)]
        if len(ids) != len(set(ids)):
            raise MedicalWritingTableError(f"{prefix} ids must be unique")
        return ids

    @staticmethod
    def _column_count(block: dict[str, Any], rows: list[Any]) -> int:
        declared = MedicalWritingTableService._nonnegative_int(
            block.get("column_count"), 0
        )
        observed = 0
        for row in rows:
            if not isinstance(row, list):
                continue
            for cell in row:
                if not isinstance(cell, dict):
                    continue
                start = MedicalWritingTableService._nonnegative_int(
                    cell.get("grid_column_index"), 0
                )
                span = MedicalWritingTableService._positive_int(
                    cell.get("column_span"), 1
                )
                observed = max(observed, start + span)
        count = max(declared, observed)
        if count < 1:
            raise MedicalWritingTableError("table must contain at least one column")
        return count

    @staticmethod
    def _lineage(raw_cell: dict[str, Any], source_locator: str) -> list[str]:
        values = MedicalWritingTableService._string_list(
            raw_cell.get("provenance_lineage")
        )
        if source_locator and source_locator not in values:
            values.append(source_locator)
        parent_locator = str(raw_cell.get("merge_parent_source_locator") or "")
        if parent_locator and parent_locator not in values:
            values.append(parent_locator)
        return values

    @staticmethod
    def _table_lineage(block: dict[str, Any]) -> list[str]:
        values = MedicalWritingTableService._string_list(block.get("source_lineage"))
        locator = str(block.get("source_locator") or "")
        if locator and locator not in values:
            values.append(locator)
        return values

    @staticmethod
    def _row_source_locator(raw_row: list[dict[str, Any]]) -> str:
        for cell in raw_row:
            locator = str(cell.get("source_locator") or "")
            if locator:
                return locator.rsplit(":cell:", 1)[0]
        return ""

    @staticmethod
    def _required_id(operation: dict[str, Any], field: str) -> str:
        value = str(operation.get(field) or "").strip()
        if not value:
            raise TableOperationError(f"operation requires {field}")
        return value

    @staticmethod
    def _row(table: StructuredTable, row_id: str) -> StructuredTableRow:
        row = next((item for item in table.rows if item.row_id == row_id), None)
        if row is None:
            raise TableOperationError(f"unknown row id: {row_id}")
        return row

    @staticmethod
    def _column(table: StructuredTable, column_id: str) -> StructuredTableColumn:
        column = next(
            (item for item in table.columns if item.column_id == column_id), None
        )
        if column is None:
            raise TableOperationError(f"unknown column id: {column_id}")
        return column

    @staticmethod
    def _cell(table: StructuredTable, cell_id: str) -> StructuredTableCell:
        cell = next(
            (
                item
                for row in table.rows
                for item in row.cells
                if item.cell_id == cell_id
            ),
            None,
        )
        if cell is None:
            raise TableOperationError(f"unknown cell id: {cell_id}")
        return cell

    @staticmethod
    def _note(table: StructuredTable, note_id: str) -> StructuredTableNote:
        note = next((item for item in table.notes if item.note_id == note_id), None)
        if note is None:
            raise TableOperationError(f"unknown note id: {note_id}")
        return note

    def _insertion_index(
        self,
        items: Sequence[Any],
        operation: dict[str, Any],
        kind: str,
    ) -> int:
        before = operation.get(f"before_{kind}_id")
        after = operation.get(f"after_{kind}_id")
        if before and after:
            raise TableOperationError(f"choose before or after {kind}, not both")
        id_field = f"{kind}_id"
        if before:
            index = next(
                (
                    index
                    for index, item in enumerate(items)
                    if getattr(item, id_field) == before
                ),
                None,
            )
            if index is None:
                raise TableOperationError(f"unknown {kind} anchor id: {before}")
            return index
        if after:
            index = next(
                (
                    index
                    for index, item in enumerate(items)
                    if getattr(item, id_field) == after
                ),
                None,
            )
            if index is None:
                raise TableOperationError(f"unknown {kind} anchor id: {after}")
            return index + 1
        return len(items)

    def _assert_row_boundary_is_unmerged(self, table: StructuredTable, index: int) -> None:
        for row in table.rows:
            for cell in row.cells:
                if self._cell_meta(cell).get("hidden"):
                    continue
                if row.order < index < row.order + cell.row_span:
                    raise TableOperationError("split merged cells before inserting at this row boundary")

    def _assert_column_boundary_is_unmerged(
        self, table: StructuredTable, index: int
    ) -> None:
        for row in table.rows:
            for cell in row.cells:
                if self._cell_meta(cell).get("hidden"):
                    continue
                column = self._column(table, cell.column_id)
                if column.order < index < column.order + cell.column_span:
                    raise TableOperationError(
                        "split merged cells before inserting at this column boundary"
                    )

    def _assert_row_not_merged(
        self, table: StructuredTable, target_row: StructuredTableRow
    ) -> None:
        target = target_row.order
        for row in table.rows:
            for cell in row.cells:
                metadata = self._cell_meta(cell)
                if metadata.get("hidden") and cell.row_id == target_row.row_id:
                    raise TableOperationError("split merged cells before deleting this row")
                if not metadata.get("hidden") and row.order <= target < row.order + cell.row_span:
                    if cell.row_span > 1:
                        raise TableOperationError("split merged cells before deleting this row")

    def _has_merges(self, table: StructuredTable) -> bool:
        return any(
            cell.row_span > 1
            or cell.column_span > 1
            or self._cell_meta(cell).get("hidden")
            for row in table.rows
            for cell in row.cells
        )

    @staticmethod
    def _column_label(structure: dict[str, Any], index: int) -> str:
        values = structure.get("column_labels")
        return str(values[index]) if isinstance(values, list) and index < len(values) else ""

    @staticmethod
    def _column_role(structure: dict[str, Any], index: int) -> str:
        values = structure.get("column_style_roles")
        return str(values[index]) if isinstance(values, list) and index < len(values) else "body"

    @staticmethod
    def _column_width(structure: dict[str, Any], index: int) -> int | None:
        values = structure.get("column_width_twips")
        value = values[index] if isinstance(values, list) and index < len(values) else None
        return value if isinstance(value, int) and value > 0 else None

    @staticmethod
    def _column_source_locator(structure: dict[str, Any], index: int) -> str:
        values = structure.get("column_source_locators")
        return str(values[index]) if isinstance(values, list) and index < len(values) else ""

    @staticmethod
    def _column_semantic_role(structure: dict[str, Any], index: int) -> str:
        columns = structure.get("columns")
        if isinstance(columns, list) and index < len(columns) and isinstance(columns[index], dict):
            explicit = str(columns[index].get("semantic_role") or "")
            if explicit:
                return explicit
        values = structure.get("column_semantic_roles")
        return str(values[index]) if isinstance(values, list) and index < len(values) else ""

    @staticmethod
    def _row_label(structure: dict[str, Any], index: int) -> str:
        values = structure.get("row_labels")
        return str(values[index]) if isinstance(values, list) and index < len(values) else ""

    @staticmethod
    def _row_role(structure: dict[str, Any], index: int, block: dict[str, Any]) -> str:
        values = structure.get("row_style_roles")
        if isinstance(values, list) and index < len(values):
            return str(values[index])
        return "header" if index < MedicalWritingTableService._nonnegative_int(block.get("header_row_count"), 0) else "body"

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, (list, tuple, set)):
            return []
        return [str(item) for item in value if str(item)]

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            converted = int(value)
        except (TypeError, ValueError):
            return default
        return converted if converted >= 1 else default

    @staticmethod
    def _nonnegative_int(value: Any, default: int) -> int:
        try:
            converted = int(value)
        except (TypeError, ValueError):
            return default
        return converted if converted >= 0 else default


def table_block_to_structured_table(
    block: Mapping[str, Any],
    *,
    domain: StructuredTableDomain | str | None = None,
) -> StructuredTable:
    return MedicalWritingTableService().from_table_block(block, domain=domain)


def structured_table_to_table_block(table: StructuredTable) -> dict[str, Any]:
    return MedicalWritingTableService().to_table_block(table)


def apply_table_operations(
    table: StructuredTable,
    operations: Sequence[Mapping[str, Any]],
    *,
    expected_version: int,
) -> StructuredTable:
    return MedicalWritingTableService().apply_operations(
        table, operations, expected_version=expected_version
    )
