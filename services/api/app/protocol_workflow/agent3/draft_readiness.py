"""Versioned working-draft readiness (requirements-v2 R2 / A04-A06).

Admission to working-draft generation is critical-design based, not
all-facts-ready: once the user confirmed the key design (StudyDefinition
canonical_state confirmed/frozen), a complete, editable draft may be
generated with explicit gap objects.  Unresolved non-key applicability
stays pending; real applicability contradictions block generation until the
user resolves them.  The full fact-readiness contract (manuscript_plan)
remains the quality/release-stage check and is embedded verbatim.
"""
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.study_definition import study_revision_hash
from .manuscript_plan import manuscript_preparation_view, plan_manuscript_chapters

PENDING_CODES = {'conditional_applicability_unresolved'}
GAP_CODES = {'missing_required_fact', 'chapter_has_no_resolved_facts'}

#: Chapter dispositions for working-draft generation.
DISPOSITIONS = ('write', 'write_with_gaps', 'pending_decision', 'blocked', 'not_applicable')


def _triggering_paths(plan, node_id):
    """Snapshot triggering paths: the locatable fact identity for gap blocks."""
    snapshot = plan.get('applicability_snapshot') or {}
    for entry in snapshot.get('entries') or []:
        if entry.get('semantic_node_id') == node_id:
            return tuple(entry.get('triggering_fact_paths') or ())
    return ()


def draft_readiness(template, study, plan=None):
    """Build the draft-readiness.v1 view for one study."""
    if study.canonical_state.value in {'confirmed', 'frozen'}:
        plan = plan if plan is not None else plan_manuscript_chapters(template, study)
    else:
        plan = manuscript_preparation_view(template, study)
    critical = study.canonical_state.value in {'confirmed', 'frozen'}
    dispositions, blocking, open_gaps = [], [], []
    content_contract_ids = {entry.node_id:
                            entry.contract.substantive_content.substantive_content_contract_id
                            for entry in template.registry.chapters}
    for chapter in plan['chapters']:
        status = chapter['status']
        item = {'node_id': chapter['node_id'], 'title': chapter.get('title', '方案章节'),
                'substantive_content_contract_id': content_contract_ids.get(chapter['node_id'], ''),
                'errors': chapter.get('errors') or []}
        if not critical:
            item.update(disposition='pending_decision', gap_fact_paths=(),
                        reason='确认关键研究设计后生成本章')
        elif status == 'not_applicable':
            item.update(disposition='not_applicable', reason=chapter.get('reason', ''),
                        gap_fact_paths=())
        elif status == 'facts_ready':
            item.update(disposition='write', gap_fact_paths=())
        elif status == 'needs_information':
            codes = {error.get('code') for error in item['errors']}
            if 'conditional_applicability_unresolved' in codes:
                item.update(disposition='pending_decision',
                            gap_fact_paths=list(_triggering_paths(plan, chapter['node_id'])),
                            reason='本章适用性存在未决条件，确认相关设计后生成内容')
            else:
                paths = sorted({path for error in item['errors']
                                for path in (error.get('fact_paths') or ())} or
                               set(_triggering_paths(plan, chapter['node_id'])))
                item.update(disposition='write_with_gaps', gap_fact_paths=paths,
                            reason='已有事实照常成文；缺失项以显式缺口对象保留')
        else:  # invalid_input — a real applicability contradiction
            item.update(disposition='blocked',
                        gap_fact_paths=list(_triggering_paths(plan, chapter['node_id'])),
                        reason='本章适用性与已确认设计存在矛盾，需明确处理后才能生成')
            blocking.append({'node_id': chapter['node_id'], 'title': item['title'],
                             'errors': item['errors']})
        if critical and item['disposition'] in {'write_with_gaps', 'pending_decision'}:
            open_gaps.append({'node_id': item['node_id'], 'title': item['title'],
                              'kind': ('pending' if item['disposition'] == 'pending_decision' else 'gap'),
                              'fact_paths': item['gap_fact_paths'],
                              'reason': item.get('reason', '')})
        dispositions.append(item)
    view = {
        'schema_version': 'draft-readiness.v1',
        'scope': 'working_draft_admission',
        'project_id': study.project_id,
        'study_definition_id': study.study_definition_id,
        'study_sha256': study_revision_hash(study),
        'plan_sha256': plan['plan_sha256'],
        'critical_design_confirmed': critical,
        'blocking_design_conflicts': blocking,
        'open_gaps': open_gaps,
        'chapter_dispositions': dispositions,
        'can_generate_working_draft': bool(critical and not blocking and plan['chapters']),
    }
    view['readiness_sha256'] = hashlib.sha256(
        canonical_json(view).encode()).hexdigest()
    return view
