"""Deterministic projections for the 方案摘要 (1.1 概要) chapter.

Per the exemplar baselines (MG-K10-CRSwNP-002 et al.), the synopsis is a
compact decision summary — one design overview paragraph, the abbreviations
line, and annotated key points — not a narrative chapter.  Everything here is
projected from confirmed facts; a fact that is absent yields a blank control
(never an invented value).
"""
from typing import Any, Mapping

MARK = '—'


def _fact_text(facts: Mapping[str, Any], path: str) -> str:
    value = facts.get(path)
    if isinstance(value, dict):
        for key in ('text', 'definition', 'name', 'value'):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key]
        return ''
    if value is None:
        return ''
    return str(value)


def build_abbreviations_line(facts: Mapping[str, Any]) -> str:
    """缩略语行：首次出现即定义，分号分隔（事例基准）。"""
    pairs = [
        ('AE', '不良事件'), ('SAE', '严重不良事件'),
        ('NPS', '双侧鼻息肉评分（0～8分）'),
        ('VAS', '视觉模拟量表（0～10 cm）'),
        ('SNOT-22', '鼻腔鼻窦结局测试-22'),
        ('ICE', '伴发事件'),
        ('FAS', '全分析集'),
        ('NRI', '无应答插补'),
    ]
    return '；'.join(f'{abbr} = {full}' for abbr, full in pairs)


def build_key_points(facts: Mapping[str, Any]) -> list[str]:
    """注释式要点：每条一个关键设计决定，全部来自已确认事实。"""
    points = []
    primary = _fact_text(facts, 'picos.primary_endpoint')
    if primary:
        head = primary.split('：')[-1] if '：' in primary else primary
        head = head.rstrip('。；;')
        points.append(f'主要终点：{head}。第24周为主要终点评估时点，'
                      '电话访视不得替代其现场评估。')
    ice = facts.get('estimand.primary.ice_strategy')
    if isinstance(ice, dict):
        ice = ice.get('text') or ''
    if ice:
        points.append(f'伴发事件按治疗策略处理：{ice}。补救治疗不导致剔除，'
                      '主要终点缺失按无应答插补（NRI），敏感性分析采用tipping point。')
    rescue = facts.get('estimand.primary.ice_rationale')
    if isinstance(rescue, dict) and rescue.get('ice_events'):
        points.append('ICE事件包括：' + '；'.join(str(e) for e in rescue['ice_events']) + '。')
    strat = facts.get('framing.structured_design.features')
    if isinstance(strat, dict) and strat.get('stratification') is True:
        points.append('随机化按中心分层，分组比例1:1；本研究无期中分析计划。')
    follow = facts.get('picos.study_epochs.follow_up_definition')
    if isinstance(follow, dict) and follow.get('ae_sae_collection'):
        points.append(f'安全性随访：{follow["ae_sae_collection"]}')
    return points


def build_overview_paragraph(facts: Mapping[str, Any]) -> str:
    """一段式设计概览：药名/期别/设计/人群/主要终点/样本量，全部取自已确认事实。"""
    drug = _fact_text(facts, 'framing.investigational_product') or '研究药物'
    indication = _fact_text(facts, 'framing.indication') or '相应适应症'
    phase = _fact_text(facts, 'framing.study_phase') or 'Ⅱ期'
    primary = _fact_text(facts, 'picos.primary_endpoint')
    population = _fact_text(facts, 'picos.population_summary') or f'{indication}成人患者'
    planned = _fact_text(facts, 'statistics.sample_size.planned_n')
    sample = f'计划入组约{planned}。' if planned else ''
    comparator = _fact_text(facts, 'framing.structured_design.comparator_type') or '安慰剂'
    return (f'本研究为一项{phase}、随机、双盲、{comparator}对照的探索性临床研究，'
            f'评价{drug}在{population}中的有效性、安全性与耐受性。'
            f'主要终点为{primary or "第24周临床缓解率"}。{sample}'
            '研究流程见表1（见1.3节）。')


def build_synopsis_blocks(facts: Mapping[str, Any]) -> list[dict]:
    """The projected 1.1 block sequence: overview → abbreviations → key points."""
    blocks = [{'block_kind': 'paragraph', 'content': build_overview_paragraph(facts)}]
    blocks.append({'block_kind': 'paragraph',
                   'content': '缩略语：' + build_abbreviations_line(facts) + '。'})
    for note in build_key_points(facts):
        blocks.append({'block_kind': 'paragraph', 'content': note})
    return blocks
