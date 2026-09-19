"""Cross-chapter consistency gate: compare the same decision across chapters.

The gate reads confirmed facts only and reports one finding per checked
consistency pair.  Every anchor (timepoint, frequency, scale, indication) is
extracted from the study's own facts — no study- or case-specific literal
lives here.  A missing fact or a missing anchor is 'unknown', never a
failure; the goal is to surface contradictions, not to fabricate certainty.
"""
import re
from typing import Any, Mapping

_TIMEPOINT = re.compile(r'第[0-9一二两三四五六七八九十百]+周')
_FREQUENCY = re.compile(r'每[0-9一二两三四五六七八九十]*[周月日天]')
_SCALE_TOKEN = re.compile(r'[A-Za-z][A-Za-z0-9-]{1,15}')


def _text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ('text', 'description', 'timing', 'definition'):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key]
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        import json as _json
        return _json.dumps(value, ensure_ascii=False)
    return str(value)


def _first(pattern, text: str):
    match = pattern.search(text)
    return match.group(0) if match else None


def cross_check(facts: Mapping[str, Any]) -> dict:
    """Run the pairwise consistency checks and return the findings receipt."""
    findings: list[dict] = []
    indication = str(facts.get('framing.indication') or '').strip()

    def pair(item: str, left_path: str, right_path: str):
        left = _text(facts.get(left_path))
        right = _text(facts.get(right_path))
        if not left or not right:
            findings.append({'item': item, 'status': 'unknown',
                             'detail': f'{left_path} 或 {right_path} 缺失'})
            return None
        return left, right

    def conclude(item: str, left_path: str, right_path: str, status: str, **extra):
        findings.append({'item': item, 'status': status,
                         'left': left_path, 'right': right_path, **extra})

    def anchored(item: str, left_path: str, right_path: str, token):
        """Consistent iff *token* (extracted from the left fact) is in both."""
        left, right = pair(item, left_path, right_path) or (None, None)
        if left is None:
            return
        if token is None:
            conclude(item, left_path, right_path, 'unknown', detail='未能定位可比对锚点')
            return
        conclude(item, left_path, right_path,
                 'consistent' if token in right else 'contradiction', anchor=token)

    # 1) 主要终点时点：终点定义中的时间窗须与SOA对齐事实一致
    left = _text(facts.get('picos.primary_endpoint'))
    anchored('主要终点时点', 'picos.primary_endpoint',
             'statistics.primary_analysis.soa_consistency', _first(_TIMEPOINT, left) if left else None)
    # 2) 关键次要终点：两侧命名的评价工具（字母缩写）须有交集
    both = pair('关键次要终点', 'picos.key_secondary_endpoints',
                'statistics.secondary_analysis.endpoint_definitions')
    if both:
        left, right = both
        common = set(_SCALE_TOKEN.findall(left)) & set(_SCALE_TOKEN.findall(right))
        if not _SCALE_TOKEN.search(left) or not _SCALE_TOKEN.search(right):
            conclude('关键次要终点', 'picos.key_secondary_endpoints',
                     'statistics.secondary_analysis.endpoint_definitions', 'unknown',
                     detail='未含可比对的评价工具缩写')
        else:
            conclude('关键次要终点', 'picos.key_secondary_endpoints',
                     'statistics.secondary_analysis.endpoint_definitions',
                     'consistent' if common else 'contradiction',
                     anchor='、'.join(sorted(common)))
    # 3) 给药频次：剂量事实中的频次表述须出现在SOA对齐事实
    left = _text(facts.get('intervention.dose_regimen'))
    anchored('给药频次', 'intervention.dose_regimen', 'statistics.sample_size.soa_alignment',
             _first(_FREQUENCY, left) if left else None)
    # 4) ICE策略：估计目标存在时，SOA脚注绑定须提及同一处理口径
    both = pair('ICE治疗策略', 'estimand.primary.ice_strategy', 'soa.footnote_bindings')
    if both:
        left, right = both
        conclude('ICE治疗策略', 'estimand.primary.ice_strategy', 'soa.footnote_bindings',
                 'consistent' if ('ICE' in right or '伴发事件' in right) else 'contradiction')
    # 5) 样本量：估算假设与SOA对齐事实须锚定同一主要终点时间窗
    left = _text(facts.get('statistics.sample_size.assumptions'))
    anchored('样本量对齐', 'statistics.sample_size.assumptions',
             'statistics.sample_size.soa_alignment', _first(_TIMEPOINT, left) if left else None)
    # 6) 期中分析：统计特征与样本量假设表述须一致
    interim = facts.get('statistics.interim.features')
    interim_planned = interim.get('planned') if isinstance(interim, dict) else None
    assumptions = _text(facts.get('statistics.sample_size.assumptions'))
    mentions_interim = '期中' in assumptions
    excludes_interim = any(token in assumptions for token in ('无期中', '不设期中', '未设期中', '不做期中'))
    if interim_planned is None:
        interim_status = 'unknown'
    elif interim_planned is False:
        interim_status = 'contradiction' if (mentions_interim and not excludes_interim) else 'consistent'
    else:
        interim_status = ('contradiction' if excludes_interim
                          else 'consistent' if mentions_interim else 'unknown')
    findings.append({'item': '期中分析一致性', 'status': interim_status,
                     'detail': f'interim.planned={interim_planned}'})
    # 7) 目标人群：概要人群与剂量人群链接须含已确认适应症
    both = pair('目标人群', 'picos.population_summary',
                'picos.intervention_dose_regimen.population_link')
    if both:
        left, right = both
        if not indication:
            conclude('目标人群', 'picos.population_summary',
                     'picos.intervention_dose_regimen.population_link', 'unknown',
                     detail='缺少已确认适应症')
        else:
            conclude('目标人群', 'picos.population_summary',
                     'picos.intervention_dose_regimen.population_link',
                     'consistent' if indication in left and indication in right else 'contradiction',
                     anchor=indication)
    # 8) 访视表：SOA评估单元含访视结构，访视窗口事实含访视定义
    both = pair('访视表与访视窗口', 'soa.assessment_cells', 'procedure.followup_visit_windows')
    if both:
        left, right = both
        conclude('访视表与访视窗口', 'soa.assessment_cells', 'procedure.followup_visit_windows',
                 'consistent' if ('visit_id' in left and '访视' in right) else 'contradiction')

    contradictions = [f for f in findings if f['status'] == 'contradiction']
    unknown = [f for f in findings if f['status'] == 'unknown']
    return {'schema_version': 'cross-chapter-consistency.v1',
            'findings': findings,
            'status': 'consistent' if not contradictions else 'contradiction',
            'contradictions': len(contradictions), 'unknown': len(unknown),
            'checked': len(findings)}
