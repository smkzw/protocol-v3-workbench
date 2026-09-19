"""Anti-fitting regression (requirements-v2 R1 / A07 / A08).

One validation case previously leaked into the generic path: a fixed 24-week
remission-rate sample-size assumption, ENT exclusion criteria, a fixed 2-8°C
storage condition, a hardcoded dropout revision and case-bound option
templates.  Cross-disease counterexamples must never see any of them, and
confirmed user values must never be pushed back to a leaked recommendation.
"""
import json
from pathlib import Path

from app.protocol_workflow.agent3.chapter_facts import (
    residual_recommendations, _binding_index)
from app.protocol_workflow.agent3.consistency_gate import cross_check
from app.protocol_workflow.agent3.synopsis_projection import build_synopsis_blocks
from app.protocol_workflow.canonical.study_definition import CanonicalState
from app.protocol_workflow.registries.template_runtime import (
    default_template_root, load_current_template)

#: Tokens only the leaked validation case can legitimately produce.
CASE_TOKENS = ('慢性鼻窦炎', '鼻息肉', '鼻窦', '合成药X', '临床缓解率', '第24周',
               '8%上调', '2℃～8℃', '无应答插补', 'tipping point', '首次概念验证',
               'SNOT-22', 'NPS', 'II期', 'PoC')

_ONCOLOGY_III = {
    'framing.investigational_product': '合成药Y',
    'framing.indication': '非小细胞肺癌',
    'framing.study_phase': 'III期',
    'research.input_context': {'source_intake_sha256': 'a'},
}

_DIABETES_II = {
    'framing.investigational_product': '合成药D',
    'framing.indication': '2型糖尿病',
    'framing.study_phase': 'II期',
    'research.input_context': {'source_intake_sha256': 'b'},
}


def _study_stub(facts, study_id='study:v3:antifit'):
    class _Study:
        project_id = 'project:antifit'
        study_definition_id = study_id
        canonical_state = CanonicalState.CONFIRMED
        updated_at = '2026-09-19T00:00:00Z'
    s = _Study()
    s.facts = dict(facts)
    return s


def _template():
    return load_current_template(default_template_root())


def test_residual_recommendations_case_free_across_domains():
    template = _template()
    for name, facts in (('oncology', _ONCOLOGY_III), ('diabetes', _DIABETES_II)):
        out = residual_recommendations(template, _study_stub(facts, f'study:v3:{name}'))
        blob = json.dumps(out, ensure_ascii=False)
        for token in CASE_TOKENS:
            assert token not in blob, f'{name}: leaked case token {token!r}'
        for rec in out.values():
            assert rec.get('chapter') != '（设计假设修订）', 'watch must not push leaked values'
            assert rec.get('chapter') != '（适用性修正）', 'predicate filling must not re-enter'


def test_confirmed_assumptions_are_never_pushed_back():
    template = _template()
    facts = dict(_DIABETES_II)
    facts['statistics.sample_size.assumptions'] = '本研究自行确认的样本量假设：第52周达标率，差12个百分点。'
    index = _binding_index(template.fact_catalog.bindings)
    facts[index['statistics.sample_size.assumptions'].canonical_path] = \
        facts['statistics.sample_size.assumptions']
    out = residual_recommendations(template, _study_stub(facts))
    assert 'statistics.sample_size.assumptions' not in out


# --------------------------------------------------------------------------
# Consistency gate: anchors must come from the study's own facts, so a
# diabetes study passes on week 52 while a real timepoint mismatch still fails.
# --------------------------------------------------------------------------

def _diabetes_gate_facts():
    return {
        'picos.primary_endpoint': {'text': '主要终点为第52周HbA1c较基线变化。'},
        'statistics.primary_analysis.soa_consistency': {'text': '主要分析锚定第52周HbA1c变化，与SOA表一致。'},
        'picos.key_secondary_endpoints': {'text': '关键次要终点包括HbA1c正常化比例。'},
        'statistics.secondary_analysis.endpoint_definitions': {'text': '次要终点定义：HbA1c正常化、体重。'},
        'intervention.dose_regimen': {'text': '每日一次口服，连续给药52周。'},
        'statistics.sample_size.soa_alignment': {'text': '样本量按第52周主要终点与每日一次给药估算。'},
        'statistics.sample_size.assumptions': {'text': '第52周达标率差12个百分点；随机1:1按中心分层。'},
        'estimand.primary.ice_strategy': {'text': '治疗策略：补救治疗记录并继续随访。'},
        'soa.footnote_bindings': {'note': 'SOA表脚注含ICE补救处理与访视窗定义。'},
        'statistics.interim.features': {'planned': False},
        'picos.population_summary': {'text': '2型糖尿病成人患者，二甲双胍控制不足。'},
        'picos.intervention_dose_regimen.population_link': {'text': '入组人群为2型糖尿病经二甲双胍控制不足者。'},
        'soa.assessment_cells': {'visits': [{'visit_id': 'V1'}]},
        'procedure.followup_visit_windows': {'text': '安全性随访访视窗口±7天。'},
    }


def test_consistency_gate_uses_study_own_anchors():
    status = cross_check(_diabetes_gate_facts())['status']
    assert status == 'consistent', 'a week-52 study must pass on its own anchors'


def test_consistency_gate_detects_real_timepoint_mismatch():
    facts = _diabetes_gate_facts()
    facts['statistics.primary_analysis.soa_consistency'] = {'text': '主要分析锚定第18周HbA1c变化。'}
    report = cross_check(facts)
    assert report['status'] == 'contradiction'
    assert any(f['item'] == '主要终点时点' and f['status'] == 'contradiction'
               for f in report['findings'])


def test_consistency_gate_missing_facts_stay_unknown():
    report = cross_check({})
    assert report['status'] == 'consistent' and report['unknown'] == report['checked']


# --------------------------------------------------------------------------
# Synopsis projection: structure from facts only; no case defaults.
# --------------------------------------------------------------------------

def test_synopsis_projection_without_facts_has_no_case_defaults():
    blocks = build_synopsis_blocks({})
    blob = json.dumps(blocks, ensure_ascii=False)
    for token in CASE_TOKENS + ('双盲', '成人', '探索性'):
        assert token not in blob, f'empty design must not default to {token!r}'


def test_synopsis_projection_follows_confirmed_facts():
    facts = {
        'framing.investigational_product': '合成药D',
        'framing.indication': '2型糖尿病',
        'framing.study_phase': 'II期',
        'picos.primary_endpoint': {'text': '主要终点：第52周HbA1c较基线变化'},
        'picos.population_summary': {'text': '2型糖尿病伴肥胖成人患者'},
        'statistics.sample_size.planned_n': '240',
        'framing.structured_design.features': {'stratification': True},
        'statistics.interim.features': {'planned': False},
    }
    blob = json.dumps(build_synopsis_blocks(facts), ensure_ascii=False)
    assert '第52周' in blob and '第24周' not in blob
    assert '240' in blob and '无期中分析计划' in blob
    assert '2型糖尿病伴肥胖成人患者' in blob


# --------------------------------------------------------------------------
# Source tripwires: the case values must not be re-added as constants.
# --------------------------------------------------------------------------

_MODULE_SOURCES = (
    ('chapter_facts', Path(__file__).parents[2] /
     'services/api/app/protocol_workflow/agent3/chapter_facts.py',
     CASE_TOKENS + ('PoC',)),
    ('consistency_gate', Path(__file__).parents[2] /
     'services/api/app/protocol_workflow/agent3/consistency_gate.py',
     CASE_TOKENS + ('每两周',)),
    ('synopsis_projection', Path(__file__).parents[2] /
     'services/api/app/protocol_workflow/agent3/synopsis_projection.py',
     CASE_TOKENS),
)


def test_case_values_absent_from_generic_sources():
    for name, path, tokens in _MODULE_SOURCES:
        source = path.read_text(encoding='utf-8')
        for token in tokens:
            assert token not in source, f'{name}: case token {token!r} back in source'


def test_picos_option_templates_case_free():
    source = (Path(__file__).parents[2] /
              'services/api/app/evidence_picos_workflow.py').read_text(encoding='utf-8')
    _, marker, table = source.partition('_OPTION_TEMPLATES')
    scanned = table if marker else source
    for token in ('鼻息肉', '鼻窦', 'NPS', 'NCS', 'SNOT-22', '嗅觉', '慢性鼻窦炎'):
        assert token not in scanned, f'option template leaked case token {token!r}'
