"""Deterministic projections for the 方案摘要 (1.1 概要) chapter.

The synopsis is a compact decision summary — one design overview paragraph,
the abbreviations line, and annotated key points.  Everything is projected
from the study's confirmed facts: a fact that is absent yields no sentence,
never a baked-in example value (requirements-v2 R1).
"""
import re
from typing import Any, Mapping

_TIMEPOINT = re.compile(r'第[0-9一二两三四五六七八九十百]+周')

#: Trial-vocabulary abbreviations that apply to any study.  Indication- or
#: instrument-specific abbreviations belong to the chapters that define them.
UNIVERSAL_ABBREVIATIONS = (
    ('AE', '不良事件'), ('SAE', '严重不良事件'),
    ('ICE', '伴发事件'), ('FAS', '全分析集'),
)


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
    """缩略语行：仅收通用试验词汇；量表与研究专用缩写由正文定义。"""
    return '；'.join(f'{abbr} = {full}' for abbr, full in UNIVERSAL_ABBREVIATIONS)


def build_key_points(facts: Mapping[str, Any]) -> list[str]:
    """注释式要点：每条只陈述一个已确认设计决定。"""
    points = []
    primary = _fact_text(facts, 'picos.primary_endpoint')
    if primary:
        head = primary.split('：')[-1] if '：' in primary else primary
        head = head.rstrip('。；;')
        timepoint = _TIMEPOINT.search(head)
        suffix = f'{timepoint.group(0)}为主要终点评估时点。' if timepoint else ''
        points.append(f'主要终点：{head}。{suffix}')
    ice = facts.get('estimand.primary.ice_strategy')
    if isinstance(ice, dict):
        ice = ice.get('text') or ''
    if ice:
        points.append(f'伴发事件处理：{ice.rstrip("。；;")}。')
    missing = _fact_text(facts, 'statistics.secondary_analysis.missing_data')
    if missing:
        points.append(f'主要终点缺失数据处理：{missing.rstrip("。；;")}。')
    rescue = facts.get('estimand.primary.ice_rationale')
    if isinstance(rescue, dict) and rescue.get('ice_events'):
        points.append('ICE事件包括：' + '；'.join(str(e) for e in rescue['ice_events']) + '。')
    strat = facts.get('framing.structured_design.features')
    if isinstance(strat, dict) and strat.get('stratification') is True:
        points.append('随机化按中心分层。')
    interim = facts.get('statistics.interim.features')
    if isinstance(interim, dict):
        if interim.get('planned') is False:
            points.append('本研究无期中分析计划。')
        elif interim.get('planned') is True:
            points.append('本研究设期中分析，具体安排见统计分析计划。')
    follow = facts.get('picos.study_epochs.follow_up_definition')
    if isinstance(follow, dict) and follow.get('ae_sae_collection'):
        points.append(f'安全性随访：{follow["ae_sae_collection"]}')
    return points


def build_overview_paragraph(facts: Mapping[str, Any]) -> str:
    """一段式设计概览：只陈述已确认事实，缺失属性不出现。"""
    drug = _fact_text(facts, 'framing.investigational_product') or '研究药物'
    indication = _fact_text(facts, 'framing.indication') or '相应适应症'
    population = _fact_text(facts, 'picos.population_summary') or f'{indication}患者'
    planned = _fact_text(facts, 'statistics.sample_size.planned_n')
    sample = f'计划入组约{planned}。' if planned else ''
    primary = _fact_text(facts, 'picos.primary_endpoint')
    primary_clean = re.sub(r'^主要终点[:：]?\s*', '', primary).rstrip('。；;') if primary else ''
    attributes = []
    phase = _fact_text(facts, 'framing.study_phase').strip()
    if phase:
        attributes.append(phase)
    if _fact_text(facts, 'framing.structured_design.allocation_ratio').strip():
        attributes.append('随机')
    comparator = _fact_text(facts, 'framing.structured_design.comparator_type').strip()
    if comparator:
        attributes.append(f'{comparator}对照')
    head = '、'.join(attributes)
    prefix = f'本研究为一项{head}的临床研究' if attributes else '本研究为一项临床研究'
    primary_part = f'主要终点为{primary_clean}。' if primary_clean else ''
    return (f'{prefix}，评价{drug}在{population}中的有效性、安全性与耐受性。'
            f'{primary_part}{sample}研究流程见表1（见1.3节）。')


def build_synopsis_blocks(facts: Mapping[str, Any]) -> list[dict]:
    """The projected 1.1 block sequence: overview → abbreviations → key points."""
    blocks = [{'block_kind': 'paragraph', 'content': build_overview_paragraph(facts)}]
    blocks.append({'block_kind': 'paragraph',
                   'content': '缩略语：' + build_abbreviations_line(facts) + '。'})
    for note in build_key_points(facts):
        blocks.append({'block_kind': 'paragraph', 'content': note})
    return blocks
