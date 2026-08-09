from __future__ import annotations

import unittest

from pydantic import ValidationError

from packages.contracts.workbench_contracts import (
    ScheduleOfActivitiesDefinition,
    SoaActivity,
    SoaCellPlan,
    SoaEpoch,
    SoaVisit,
    StructuredTable,
    StructuredTableCell,
    StructuredTableColumn,
    StructuredTableDomain,
    StructuredTableRole,
    StructuredTableNote,
    StructuredTableNoteType,
    StructuredTableRow,
)


class StructuredTableContractTests(unittest.TestCase):
    def test_generic_table_preserves_stable_ids_spans_notes_and_word_layout(self):
        note = StructuredTableNote(
            note_id="note_cbc",
            marker="a",
            note_type=StructuredTableNoteType.ITEM_SET,
            text="血常规包括红细胞、血红蛋白、血小板及白细胞分类计数。",
            target_ids=["cell_lab_v1"],
            module_ref="lab_panel.cbc.v1",
            project_override=True,
            source_refs=["docx:paragraph:88"],
        )
        table = StructuredTable(
            table_id="table_soa_001",
            block_id="mwblock_soa_001",
            domain=StructuredTableDomain.SCHEDULE_OF_ACTIVITIES,
            role=StructuredTableRole.BODY_CONTENT,
            title="表1 研究流程表",
            source_locator="docx:table:7",
            header_row_count=1,
            columns=[
                StructuredTableColumn(column_id="col_activity", order=0, label="项目"),
                StructuredTableColumn(
                    column_id="col_v1",
                    order=1,
                    label="V1",
                    semantic_role="collection_visit",
                ),
            ],
            rows=[
                StructuredTableRow(
                    row_id="row_lab",
                    order=0,
                    label="实验室检查",
                    cells=[
                        StructuredTableCell(
                            cell_id="cell_lab_label",
                            row_id="row_lab",
                            column_id="col_activity",
                            text="血常规",
                            column_span=1,
                            source_locator="docx:table:7:row:0:cell:0",
                        ),
                        StructuredTableCell(
                            cell_id="cell_lab_v1",
                            row_id="row_lab",
                            column_id="col_v1",
                            text="Xᵃ",
                            row_span=2,
                            note_refs=["note_cbc"],
                        ),
                    ],
                ),
            ],
            notes=[note],
            word_layout={"orientation": "landscape", "repeat_header_rows": 1},
        )

        payload = table.model_dump(mode="json")
        self.assertEqual("structured_table_v1", payload["schema_version"])
        self.assertEqual("body_content", payload["role"])
        self.assertEqual(2, payload["rows"][0]["cells"][1]["row_span"])
        self.assertEqual("collection_visit", payload["columns"][1]["semantic_role"])
        self.assertEqual("landscape", payload["word_layout"]["orientation"])

    def test_legacy_table_role_defaults_to_unclassified(self):
        table = StructuredTable(table_id="legacy_table", block_id="legacy_block")

        self.assertEqual(StructuredTableRole.UNCLASSIFIED, table.role)
        self.assertEqual("unclassified", table.model_dump(mode="json")["role"])

    def test_generic_table_rejects_duplicate_ids_and_orphan_notes(self):
        with self.assertRaisesRegex(ValidationError, "column ids must be present and unique"):
            StructuredTable(
                table_id="table_bad",
                block_id="block_bad",
                columns=[
                    StructuredTableColumn(column_id="duplicate", order=0),
                    StructuredTableColumn(column_id="duplicate", order=1),
                ],
            )
        with self.assertRaisesRegex(ValidationError, "unknown or empty target"):
            StructuredTable(
                table_id="table_bad_note",
                block_id="block_bad_note",
                notes=[
                    StructuredTableNote(
                        note_id="note_orphan",
                        note_type=StructuredTableNoteType.CONDITION,
                        text="仅适用于特定受试者。",
                        target_ids=["missing_cell"],
                    )
                ],
            )

    def test_soa_contract_supports_visit_windows_conditions_and_note_modules(self):
        schedule = ScheduleOfActivitiesDefinition(
            table_id="table_soa_rux",
            epochs=[SoaEpoch(epoch_id="epoch_screening", order=0, label="筛选期")],
            visits=[
                SoaVisit(
                    visit_id="visit_v1",
                    epoch_id="epoch_screening",
                    order=0,
                    label="V1",
                    visit_type="screening",
                    nominal_day=-28,
                    reference_anchor="first_dose",
                    window_before_days=0,
                    window_after_days=7,
                )
            ],
            activities=[
                SoaActivity(
                    activity_id="activity_cbc",
                    order=0,
                    label="血常规",
                    domain="laboratory",
                    module_ref="lab_panel.cbc.v1",
                )
            ],
            cells=[
                SoaCellPlan(
                    cell_id="soa_cell_cbc_v1",
                    activity_id="activity_cbc",
                    visit_id="visit_v1",
                    execution_state="conditional",
                    condition_expression="screening_abnormality_requires_repeat",
                    note_refs=["note_repeat"],
                )
            ],
            notes=[
                StructuredTableNote(
                    note_id="note_repeat",
                    note_type=StructuredTableNoteType.CONDITION,
                    text="筛选期异常且原因已改变时允许复测一次。",
                    target_ids=["soa_cell_cbc_v1"],
                )
            ],
        )
        self.assertEqual(-28, schedule.visits[0].nominal_day)
        self.assertEqual("conditional", schedule.cells[0].execution_state)

    def test_soa_contract_rejects_unknown_visit_or_duplicate_matrix_cell(self):
        with self.assertRaisesRegex(ValidationError, "unknown visit or activity"):
            ScheduleOfActivitiesDefinition(
                table_id="table_bad_soa",
                epochs=[SoaEpoch(epoch_id="epoch", order=0, label="治疗期")],
                visits=[],
                activities=[
                    SoaActivity(activity_id="activity", order=0, label="生命体征", domain="safety")
                ],
                cells=[
                    SoaCellPlan(
                        cell_id="cell",
                        activity_id="activity",
                        visit_id="missing",
                        execution_state="planned",
                    )
                ],
            )

        with self.assertRaisesRegex(ValidationError, "activity and visit pair must be unique"):
            ScheduleOfActivitiesDefinition(
                table_id="table_duplicate_pair",
                epochs=[SoaEpoch(epoch_id="epoch", order=0, label="治疗期")],
                visits=[
                    SoaVisit(
                        visit_id="visit",
                        epoch_id="epoch",
                        order=0,
                        label="V1",
                        visit_type="treatment",
                    )
                ],
                activities=[
                    SoaActivity(activity_id="activity", order=0, label="生命体征", domain="safety")
                ],
                cells=[
                    SoaCellPlan(
                        cell_id="cell_1",
                        activity_id="activity",
                        visit_id="visit",
                        execution_state="planned",
                    ),
                    SoaCellPlan(
                        cell_id="cell_2",
                        activity_id="activity",
                        visit_id="visit",
                        execution_state="conditional",
                    ),
                ],
            )

    def test_soa_contract_rejects_duplicate_ids_and_orphan_note_targets(self):
        with self.assertRaisesRegex(ValidationError, "visit ids must be present and unique"):
            ScheduleOfActivitiesDefinition(
                table_id="table_duplicate_visits",
                epochs=[SoaEpoch(epoch_id="epoch", order=0, label="治疗期")],
                visits=[
                    SoaVisit(
                        visit_id="visit",
                        epoch_id="epoch",
                        order=0,
                        label="V1",
                        visit_type="treatment",
                    ),
                    SoaVisit(
                        visit_id="visit",
                        epoch_id="epoch",
                        order=1,
                        label="V2",
                        visit_type="treatment",
                    ),
                ],
            )

        with self.assertRaisesRegex(ValidationError, "note has an unknown or empty target"):
            ScheduleOfActivitiesDefinition(
                table_id="table_orphan_note",
                notes=[
                    StructuredTableNote(
                        note_id="note_orphan",
                        note_type=StructuredTableNoteType.OPERATIONAL,
                        text="访视前完成空腹准备。",
                        target_ids=["missing_visit"],
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
