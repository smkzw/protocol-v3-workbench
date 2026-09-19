"""Project the confirmed visit×assessment SOA matrix from study facts.

``soa.assessment_cells.visits`` (confirmed through the chapter-facts stage)
carries each visit's assessment list; ``soa.footnote_bindings`` carries the
end-point footnotes.  This module renders them as one wide semantic table —
rows are assessments in order of first appearance, columns are visits in
protocol order, cells are ● marks.  It is a deterministic projection of
confirmed facts: nothing here invents a visit or an assessment that the
confirmed design does not already name.
"""
import json
from typing import Any, Mapping

MARK = '●'


def build_soa_matrix(facts: Mapping[str, Any]) -> dict | None:
    """Return the semantic-table content dict for the SOA, or None when the
    confirmed facts carry no visit×assessment cells."""
    cells = facts.get('soa.assessment_cells')
    if not isinstance(cells, dict):
        return None
    visits = cells.get('visits') or []
    visits = [v for v in visits if isinstance(v, dict) and v.get('visit_id')]
    if not visits:
        return None

    columns = [{'column_id': 'assessment', 'label': '评估项目', 'order': 0}]
    for order, visit in enumerate(visits, start=1):
        columns.append({'column_id': visit['visit_id'],
                        'label': visit.get('visit_name') or visit['visit_id'],
                        'order': order})

    assessments: list[str] = []
    seen = set()
    for visit in visits:
        for name in visit.get('assessments') or []:
            if name not in seen:
                seen.add(name)
                assessments.append(name)

    footnotes: dict = facts.get('soa.footnote_bindings') or {}
    notes = []
    for order, (key, text) in enumerate(footnotes.items()):
        marker = chr(ord('a') + order)
        notes.append({'marker': marker, 'text': str(text)})

    rows = [{'order': 0, 'row_id': 'header', 'cells': [
        {'column_id': col['column_id'], 'text': col['label'], 'order': i}
        for i, col in enumerate(columns)]}]
    for r_order, assessment in enumerate(assessments, start=1):
        cells_row = []
        for col in columns:
            if col['column_id'] == 'assessment':
                cells_row.append({'column_id': col['column_id'],
                                  'text': assessment, 'order': 0})
                continue
            visit = visits[col['order'] - 1]
            present = assessment in (visit.get('assessments') or [])
            cells_row.append({'column_id': col['column_id'],
                              'text': MARK if present else '',
                              'order': col['order']})
        rows.append({'order': r_order, 'row_id': f'assess-{r_order}',
                     'cells': cells_row})

    return {'schema_version': 'semantic-structured-table.v1',
            'table': {'columns': columns, 'rows': rows,
                      'header_row_count': 1, 'notes': notes}}


def soa_table_content(facts: Mapping[str, Any]) -> str | None:
    """The JSON string stored in a semantic table block, or None."""
    matrix = build_soa_matrix(facts)
    return None if matrix is None else json.dumps(matrix, ensure_ascii=False,
                                                  sort_keys=True, separators=(',', ':'))


def soa_summary(facts: Mapping[str, Any]) -> dict:
    """Shape summary for receipts: visit count, assessment count."""
    matrix = build_soa_matrix(facts)
    if matrix is None:
        return {'visits': 0, 'assessments': 0}
    table = matrix['table']
    return {'visits': len(table['columns']) - 1,
            'assessments': len(table['rows']) - 1,
            'footnotes': len(table['notes'])}
