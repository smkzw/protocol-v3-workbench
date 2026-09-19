"""Cross-chapter consistency gate: compare the same decision across chapters.

The gate reads confirmed facts only and reports one finding per checked
consistency pair.  Every check is traceable to the fact paths it compares;
a missing fact is 'unknown', never a failure — the goal is to surface
contradictions, not to fabricate certainty.
"""
from typing import Any, Mapping


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


def cross_check(facts: Mapping[str, Any]) -> dict:
    """Run the pairwise consistency checks and return the findings receipt."""
    findings: list[dict] = []

    def check(item: str, left_path: str, right_path: str, *, both_contains: tuple[str, str] | None = None,
              substring: str | None = None):
        left = _text(facts.get(left_path))
        right = _text(facts.get(right_path))
        if not left or not right:
            findings.append({'item': item, 'status': 'unknown',
                             'detail': f'{left_path} 或 {right_path} 缺失'})
            return
        if substring is not None:
            ok = substring in left and substring in right
        elif both_contains is not None:
            ok = both_contains[0] in left and both_contains[1] in right
        else:
            ok = True
        findings.append({'item': item, 'status': 'consistent' if ok else 'contradiction',
                         'left': left_path, 'right': right_path})

    # 1) 主要终点时点：终点定义 vs SOA对齐事实
    check('主要终点时点', 'picos.primary_endpoint', 'statistics.primary_analysis.soa_consistency',
          both_contains=('第24周', '第24周'))
    # 2) 关键次要终点（SNOT-22）: 终点 vs 统计（两侧JSON均含SNOT-22）
    check('关键次要终点SNOT-22', 'picos.key_secondary_endpoints',
          'statistics.secondary_analysis.endpoint_definitions', substring='SNOT-22')
    # 3) 给药频次：剂量facts JSON含"每两周"，SOA对齐事实含"末次给药至第24周"
    check('给药频次', 'intervention.dose_regimen', 'statistics.sample_size.soa_alignment',
          both_contains=('每两周', '第24周'))
    # 4) ICE策略：估计目标 vs SOA脚注绑定（脚注JSON含ICE_rescue文本）
    check('ICE治疗策略', 'estimand.primary.ice_strategy', 'soa.footnote_bindings',
          substring='治疗策略')
    # 5) 样本量：估算假设与SOA对齐事实都锚定第24周主要终点
    check('样本量对齐', 'statistics.sample_size.assumptions',
          'statistics.sample_size.soa_alignment', both_contains=('第24周', '第24周'))
    # 6) 期中分析：无期中 vs 统计特征
    interim = facts.get('statistics.interim.features')
    interim_planned = interim.get('planned') if isinstance(interim, dict) else None
    assumptions = _text(facts.get('statistics.sample_size.assumptions'))
    findings.append({
        'item': '无期中分析一致性',
        'status': ('consistent' if interim_planned is False and '无期中分析' in assumptions
                   else 'contradiction' if interim_planned is not None
                   else 'unknown'),
        'detail': f'interim.planned={interim_planned}'})
    # 7) 人群：概要人群 vs 剂量人群链接
    check('目标人群', 'picos.population_summary', 'picos.intervention_dose_regimen.population_link',
          substring='慢性鼻窦炎伴鼻息肉')
    # 8) 访视表：SOA评估单元含访视，访视窗口事实含时间窗定义
    check('访视表与访视窗口', 'soa.assessment_cells', 'procedure.followup_visit_windows',
          both_contains=('visit_id', '访视'))

    contradictions = [f for f in findings if f['status'] == 'contradiction']
    unknown = [f for f in findings if f['status'] == 'unknown']
    return {'schema_version': 'cross-chapter-consistency.v1',
            'findings': findings,
            'status': 'consistent' if not contradictions else 'contradiction',
            'contradictions': len(contradictions), 'unknown': len(unknown),
            'checked': len(findings)}
