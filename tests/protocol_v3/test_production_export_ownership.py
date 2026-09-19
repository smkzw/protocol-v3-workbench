"""Production export serializes the current version faithfully (R4/T13).

Export owns layout only: template front matter, bookmarks, orientation,
placeholder real values.  It must not re-project the synopsis, swap the SOA
table, silently replace terms, delete marker-hit paragraphs, or write
"不适用" based on block kind (B01/A13/A14/A19).
"""
import json

from app.protocol_workflow.agent3.word_export_production import render_production_docx
from app.protocol_workflow.registries.template_runtime import default_template_root


def _template_paths():
    root = default_template_root()
    meta = json.loads((root / 'template.json').read_text(encoding='utf-8'))
    return meta['source']['path'], root


def _document(blocks):
    return {'study_definition_id': 'study:v3:export', 'revision': 1,
            'semantic_blocks': blocks}


def _para(node, text):
    return {'semantic_node_id': node, 'block_kind': 'paragraph', 'content': text}


def _table(node, cell_text):
    payload = {'schema_version': 'semantic-structured-table.v1', 'table': {
        'columns': [{'column_id': 'c1', 'order': 1}],
        'header_row_count': 1,
        'rows': [{'order': 1, 'cells': [{'column_id': 'c1', 'order': 1, 'text': '访视'}]},
                 {'order': 2, 'cells': [{'column_id': 'c1', 'order': 2, 'text': cell_text}]}],
    }}
    return {'semantic_node_id': node, 'block_kind': 'table',
            'content': json.dumps(payload, ensure_ascii=False)}


def _all_text(doc):
    parts = [para.text for para in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.extend(para.text for para in cell.paragraphs)
    return '\n'.join(parts)


def test_table_first_chapter_never_gets_not_applicable_text(tmp_path):
    template_path, template_dir = _template_paths()
    blocks = [_para('v2_n_11_1_1', '第一章正文。'),
              _table('v2_n_11_1_2', '表格首块数据')]
    out = tmp_path / 'out.docx'
    render_production_docx(template_path, template_dir, _document(blocks),
                           out, {'research.input_context': {}})
    from docx import Document as open_docx
    text = _all_text(open_docx(str(out)))
    assert '本节不适用于本研究' not in text
    assert '表格首块数据' in text


def test_export_preserves_user_content_without_reprojection_or_rewriting(tmp_path):
    template_path, template_dir = _template_paths()
    synopsis_node = 'v2_n_11_1_1'
    blocks = [
        _para(synopsis_node, '用户手改过的概要段落，含受试者一词与计划入组约240名受试者。'),
        _para(synopsis_node, '缩略语按用户自己的写法排列。'),
        _para('v2_n_12_x', '流程表章用户文字，含受试者与随访安排。'),
        _table('v2_n_12_x', '用户改过的访视安排'),
        _para('v2_n_13_x', '本候选不作合规断言。'),
    ]
    out = tmp_path / 'out.docx'
    render_production_docx(template_path, template_dir, _document(blocks),
                           out, {'research.input_context': {'user_brief': '合成'}})
    from docx import Document as open_docx
    doc = open_docx(str(out))
    text = _all_text(doc)
    # R4: the user's current version ships verbatim.
    assert '用户手改过的概要段落' in text
    assert '用户改过的访视安排' in text
    # No silent term replacement at export (R4/A13).
    assert '受试者' in text and '受试者' not in text.replace('受试者', '')
    # No export-time synopsis projection: the projected abbreviation line
    # would differ from the user's own wording.
    assert '缩略语：AE = 不良事件' not in text
    # No marker-hit paragraph deletion: cleaning is a visible candidate, not
    # a silent export behavior (R-C04).
    assert '本候选不作合规断言' in text
    # Layout-only tuning still runs: wide tables stay readable.
    receipt = render_production_docx(template_path, template_dir,
                                     _document(blocks), tmp_path / 'out2.docx',
                                     {'research.input_context': {}})
    assert receipt['export_scope'] == 'production_docx'
