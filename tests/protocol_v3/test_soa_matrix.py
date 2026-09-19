"""SOA matrix projection: visit×assessment wide table from confirmed facts."""
import json

from app.protocol_workflow.agent3.soa_matrix import (
    build_soa_matrix, soa_summary, soa_table_content)

FACTS = {
    'soa.assessment_cells': {'visits': [
        {'visit_id': 'SCR', 'visit_name': '筛选期',
         'assessments': ['知情同意', '生命体征', '双侧鼻息肉评分（NPS）']},
        {'visit_id': 'D1', 'visit_name': '第1天（基线/随机/首次给药）',
         'assessments': ['随机化', '研究药物给药', '生命体征']},
        {'visit_id': 'D162', 'visit_name': '第162天（第24周/末次给药）',
         'assessments': ['双侧鼻息肉评分（NPS）', '研究药物计数/依从性']},
    ]},
    'soa.footnote_bindings': {'NPS': '双侧鼻息肉评分，每侧0～4分。'},
}


def test_matrix_columns_are_visits_rows_are_assessments():
    matrix = build_soa_matrix(FACTS)
    table = matrix['table']
    assert len(table['columns']) == 4  # label + 3 visits
    assert table['columns'][1]['label'] == '筛选期'
    assert table['header_row_count'] == 1
    # row 0 is the header; assessment rows follow in first-appearance order
    header = table['rows'][0]['cells']
    assert header[1]['text'] == '筛选期'
    names = [next(c['text'] for c in r['cells'] if c['column_id'] == 'assessment') for r in table['rows'][1:]]
    assert names[:3] == ['知情同意', '生命体征', '双侧鼻息肉评分（NPS）']
    assert '随机化' in names


def test_cells_mark_presence_only():
    matrix = build_soa_matrix(FACTS)
    table = matrix['table']
    col = {c['column_id']: i for i, c in enumerate(table['columns'])}
    d1 = table['rows'][1]['cells']  # first assessment row = 知情同意
    assert d1[col['SCR']]['text'] == '●'
    assert d1[col['D1']]['text'] == ''


def test_no_cells_returns_none():
    assert build_soa_matrix({'soa.assessment_cells': {'visits': []}}) is None
    assert soa_table_content({}) is None
    assert soa_summary({}) == {'visits': 0, 'assessments': 0}


def test_table_content_is_valid_semantic_table():
    content = soa_table_content(FACTS)
    parsed = json.loads(content)
    assert parsed['schema_version'] == 'semantic-structured-table.v1'
    assert parsed['table']['notes'][0]['marker'] == 'a'
    summary = soa_summary(FACTS)
    assert summary['visits'] == 3 and summary['assessments'] >= 4
