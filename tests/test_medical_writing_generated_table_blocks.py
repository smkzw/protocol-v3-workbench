import copy

import pytest

from services.api.app.medical_writing_repository import MedicalWritingRuntimeRepository


def _source_blocks():
    return [
        {
            "block_id": "mwblock_heading",
            "block_type": "heading",
            "text": "研究目的",
            "source_locator": "docx:paragraph:10",
            "source_kind": "original_protocol_docx",
            "body_order": 10,
            "editable": False,
        },
        {
            "block_id": "mwblock_paragraph",
            "block_type": "paragraph",
            "text": "正文",
            "source_locator": "docx:paragraph:11",
            "source_kind": "original_protocol_docx",
            "body_order": 11,
            "editable": False,
        },
    ]


def _generated_table():
    return {
        "block_id": "mwgenerated_objectives_001",
        "block_type": "table",
        "table_id": "mwtable_objectives_001",
        "source_locator": "generated:medical_writing_template:objectives_endpoints:001",
        "source_kind": "medical_writing_template",
        "template_id": "objectives_endpoints",
        "body_order": 11,
        "schema_version": "structured_table_block_v1",
        "header_row_count": 1,
        "column_count": 2,
        "editable": True,
        "rows": [
            [
                {
                    "cell_id": "cell_header_1",
                    "text": "目的层级",
                    "source_locator": "",
                    "row_index": 0,
                    "cell_index": 0,
                    "grid_column_index": 0,
                    "column_span": 1,
                    "row_span": 1,
                    "vertical_merge": "none",
                    "hidden": False,
                    "style_role": "header",
                },
                {
                    "cell_id": "cell_header_2",
                    "text": "对应终点",
                    "source_locator": "",
                    "row_index": 0,
                    "cell_index": 1,
                    "grid_column_index": 1,
                    "column_span": 1,
                    "row_span": 1,
                    "vertical_merge": "none",
                    "hidden": False,
                    "style_role": "header",
                },
            ],
            [
                {
                    "cell_id": "cell_body_1",
                    "text": "主要目的",
                    "source_locator": "",
                    "row_index": 1,
                    "cell_index": 0,
                    "grid_column_index": 0,
                    "column_span": 1,
                    "row_span": 1,
                    "vertical_merge": "none",
                    "hidden": False,
                    "style_role": "body",
                },
                {
                    "cell_id": "cell_body_2",
                    "text": "待填写",
                    "source_locator": "",
                    "row_index": 1,
                    "cell_index": 1,
                    "grid_column_index": 1,
                    "column_span": 1,
                    "row_span": 1,
                    "vertical_merge": "none",
                    "hidden": False,
                    "style_role": "body",
                },
            ],
        ],
        "structured_table": {
            "schema_version": "structured_table_v1",
            "version": 0,
            "domain": "generic",
            "title": "研究目的与终点",
            "review_state": "ai_draft",
            "row_ids": ["row_header", "row_body"],
            "row_labels": ["", ""],
            "row_style_roles": ["header", "body"],
            "column_ids": ["column_objective", "column_endpoint"],
            "column_labels": ["目的层级", "对应终点"],
            "column_style_roles": ["header", "header"],
            "column_width_twips": [2200, 5200],
            "notes": [],
            "word_layout": {"orientation": "portrait"},
            "source_lineage": ["medical_writing_template:objectives_endpoints"],
        },
    }


def test_working_copy_accepts_generated_structured_table_without_dropping_sources():
    source = _source_blocks()
    MedicalWritingRuntimeRepository._validate_working_copy_blocks(
        source,
        [source[0], source[1], _generated_table()],
    )


def test_generated_table_cannot_replace_or_reorder_source_blocks():
    source = _source_blocks()
    with pytest.raises(ValueError, match="every canonical source block"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            source,
            [source[0], _generated_table()],
        )
    with pytest.raises(ValueError, match="source block order"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            source,
            [source[1], _generated_table(), source[0]],
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_kind", "uploaded_file", "template provenance"),
        ("template_id", "", "template id"),
        ("editable", False, "explicitly editable"),
        ("structured_table", None, "structured-table contract"),
    ],
)
def test_generated_table_requires_template_provenance_and_typed_structure(
    field,
    value,
    message,
):
    source = _source_blocks()
    generated = copy.deepcopy(_generated_table())
    generated[field] = value
    with pytest.raises(ValueError, match=message):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            source,
            [*source, generated],
        )


def test_generated_table_ids_must_not_collide():
    source = _source_blocks()
    first = _generated_table()
    second = copy.deepcopy(first)
    second["block_id"] = "mwgenerated_objectives_002"
    with pytest.raises(ValueError, match="identity must be present and unique"):
        MedicalWritingRuntimeRepository._validate_working_copy_blocks(
            source,
            [*source, first, second],
        )
