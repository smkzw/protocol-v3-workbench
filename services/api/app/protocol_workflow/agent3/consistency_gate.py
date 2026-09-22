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
_AMBIGUOUS_TREATMENT_POPULATION = re.compile(r'治疗策略人群')
_STRATEGY_SIGNALS = (
    ('treatment_policy', ('治疗策略', 'treatment policy')),
    ('composite', ('复合策略', 'composite strategy')),
    ('hypothetical', ('假想策略', 'hypothetical strategy')),
    ('while_on_treatment', ('在治策略', 'while on treatment', 'while-on-treatment')),
    ('principal_stratum', ('主层策略', 'principal stratum')),
)


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


def _normalized_identity(value: Any) -> str:
    return re.sub(r'[\W_]+', '', _text(value).lower(), flags=re.UNICODE)


def _strategy_identity(value: Any) -> str | None:
    text = _text(value).strip().lower()
    if not text:
        return None
    if _AMBIGUOUS_TREATMENT_POPULATION.search(text):
        return 'ambiguous_treatment_population'
    found = [identity for identity, signals in _STRATEGY_SIGNALS
             if any(signal in text for signal in signals)]
    return found[0] if len(found) == 1 else None


def _ice_records(value: Any, *, default_outcome: str, default_strategy: Any = None) -> list[dict]:
    """Extract only records whose event and strategy identities are explicit.

    Free prose without an identifiable event remains uncomparable.  That is
    deliberate: seeing two strategy words in different chapters does not show
    that they describe the same intercurrent event.
    """
    records: list[dict] = []
    if isinstance(value, list):
        for item in value:
            records.extend(_ice_records(
                item, default_outcome=default_outcome,
                default_strategy=default_strategy))
        return records
    if isinstance(value, dict):
        event = next((value.get(key) for key in (
            'event', 'event_name', 'intercurrent_event', 'ice', 'name')
            if value.get(key)), None)
        strategy = next((value.get(key) for key in (
            'strategy', 'ice_strategy', 'handling', 'approach')
            if value.get(key)), default_strategy)
        outcome = next((value.get(key) for key in (
            'outcome', 'variable', 'endpoint') if value.get(key)), default_outcome)
        if event is not None:
            records.append({
                'event': _normalized_identity(event),
                'event_label': _text(event).strip(),
                'outcome': _normalized_identity(outcome),
                'strategy': _strategy_identity(strategy),
            })
            return records
        # A footnote map may use the ICE event as its key and the handling as
        # its value.  Metadata keys are excluded from that interpretation.
        metadata = {'note', 'notes', 'text', 'description', 'timing', 'definition'}
        for key, item in value.items():
            if key in metadata or isinstance(item, (dict, list)):
                records.extend(_ice_records(
                    item, default_outcome=default_outcome,
                    default_strategy=default_strategy))
                continue
            strategy_id = _strategy_identity(item)
            if strategy_id:
                records.append({
                    'event': _normalized_identity(key),
                    'event_label': str(key),
                    'outcome': _normalized_identity(default_outcome),
                    'strategy': strategy_id,
                })
        return records
    return records


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
    # 4) ICE策略：只比较同一estimand、同一ICE事件、同一结局语境。
    # 不同事件允许使用不同策略；“治疗策略人群”不是可推断的策略名称。
    strategy = facts.get('estimand.primary.ice_strategy')
    rationale = facts.get('estimand.primary.ice_rationale')
    events = facts.get('estimand.primary.intercurrent_events')
    if not events and isinstance(rationale, dict):
        events = rationale.get('ice_events')
    footnotes = facts.get('soa.footnote_bindings')
    outcome = _text(facts.get('estimand.primary.variable'))
    if not strategy or not events or not footnotes or not outcome:
        findings.append({
            'item': '主要估计目标ICE策略', 'scientific_issue_id': 'primary-estimand-ice',
            'status': 'unknown',
            'locations': ('estimand.primary.ice_strategy',
                          'estimand.primary.intercurrent_events',
                          'estimand.primary.variable', 'soa.footnote_bindings'),
            'detail': '缺少可按同一估计目标、ICE事件和结局语境比对的结构化事实',
        })
    elif _strategy_identity(strategy) == 'ambiguous_treatment_population':
        findings.append({
            'item': '主要估计目标ICE策略', 'scientific_issue_id': 'primary-estimand-ice',
            'status': 'unknown',
            'locations': ('estimand.primary.ice_strategy', 'soa.footnote_bindings'),
            'detail': '“治疗策略人群”含义不明确，需澄清人群定义与ICE处理策略，不能自动解释为治疗策略',
        })
    else:
        expected = _ice_records(events, default_outcome=outcome, default_strategy=strategy)
        observed = _ice_records(footnotes, default_outcome=outcome)
        comparable = []
        for left_record in expected:
            for right_record in observed:
                if (left_record['event'] == right_record['event']
                        and left_record['outcome'] == right_record['outcome']):
                    comparable.append((left_record, right_record))
        conflicts = [(left_record, right_record) for left_record, right_record in comparable
                     if left_record['strategy'] and right_record['strategy']
                     and left_record['strategy'] != right_record['strategy']]
        unresolved = [(left_record, right_record) for left_record, right_record in comparable
                      if not left_record['strategy'] or not right_record['strategy']]
        status = ('contradiction' if conflicts else 'unknown'
                  if not comparable or unresolved else 'consistent')
        detail = ('同一ICE事件在估计目标与SOA中使用了不同策略' if conflicts else
                  '存在同一ICE事件记录，但策略表述仍需澄清' if unresolved else
                  '未找到同一ICE事件与结局语境的可比记录' if not comparable else
                  '同一ICE事件与结局语境的策略一致')
        findings.append({
            'item': '主要估计目标ICE策略', 'scientific_issue_id': 'primary-estimand-ice',
            'status': status,
            'locations': ('estimand.primary.ice_strategy',
                          'estimand.primary.intercurrent_events',
                          'estimand.primary.variable', 'soa.footnote_bindings'),
            'detail': detail,
            'events': sorted({left['event_label'] for left, _ in comparable}),
        })
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
