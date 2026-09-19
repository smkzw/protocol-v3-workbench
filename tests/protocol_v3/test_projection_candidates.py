"""T11/R4: deterministic projections are candidates at the initial-generation
and explicit-refresh boundary — never a silent writer.

The endpoints expose them; the export path must not consume them (covered by
test_production_export_ownership).  These tests pin the fact-driven content
and the case-free defaults.
"""
from app.protocol_workflow.agent3.soa_matrix import soa_summary, soa_table_content
from app.protocol_workflow.agent3.synopsis_projection import build_synopsis_blocks

_CASE_TOKENS = ('慢性鼻窦炎', '鼻息肉', '临床缓解率', '第24周', 'SNOT-22', 'NPS')


def test_soa_candidate_follows_confirmed_visit_facts():
    facts = {'soa.assessment_cells': {'visits': [
        {'visit_id': 'V0', 'visit_name': '筛选', 'assessments': ['知情同意']}],
        'footnote_bindings': {}}}
    content = soa_table_content(facts)
    assert content is not None
    assert 'V0' in content
    summary = soa_summary(facts)
    assert summary['visits'] >= 1


def test_soa_candidate_absent_without_visit_facts():
    assert soa_table_content({}) is None
    assert soa_summary({}) == {'visits': 0, 'assessments': 0}


def test_synopsis_candidate_stays_case_free_and_fact_driven():
    import json
    empty = json.dumps(build_synopsis_blocks({}), ensure_ascii=False)
    for token in _CASE_TOKENS:
        assert token not in empty
    facts = {'framing.investigational_product': '合成药D',
             'framing.indication': '2型糖尿病',
             'framing.study_phase': 'II期',
             'picos.primary_endpoint': {'text': '主要终点：第52周HbA1c较基线变化'}}
    blob = json.dumps(build_synopsis_blocks(facts), ensure_ascii=False)
    assert '第52周' in blob and '合成药D' in blob
