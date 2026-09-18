"""Account for every template carrier before scheduling any chapter writing.

This is fact readiness, not source sufficiency, clinical approval or a dispatch.
Unresolved nodes remain visible; a partial ready set is never a complete draft.
"""
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.study_definition import study_revision_hash
from app.protocol_workflow.registries.applicability import (
    ApplicabilityResolutionError, bind_applicable_chapter, build_applicability_snapshot, diagnose_applicable_input,
)
from app.protocol_workflow.registries.fact_bindings import FactBindingError
from app.protocol_workflow.registries.template_runtime import template_identity


def _ordered_entries(template):
    entries={entry.node_id:entry for entry in template.registry.chapters}
    if len(template.chapter_order)!=len(entries) or set(template.chapter_order)!=set(entries):
        raise ValueError('manuscript_template_order_incomplete')
    return entries


def manuscript_preparation_view(template, study):
    """Keep the complete outline visible before research facts are confirmed."""
    if study.canonical_state.value in {'confirmed','frozen'}:
        return plan_manuscript_chapters(template,study)
    entries=_ordered_entries(template)
    chapters=[{'node_id':node,'chapter_contract_id':entries[node].contract.chapter_contract_id,
        'applicability':'unresolved','status':'needs_information',
        'errors':[{'code':'study_not_confirmed'}]} for node in template.chapter_order]
    return _plan_payload(template,study,chapters,None)


def plan_manuscript_chapters(template, study):
    entries=_ordered_entries(template)
    snapshot=build_applicability_snapshot(
        (entries[node].contract for node in template.chapter_order),study,
        template.rules_catalog.rules,created_at=study.updated_at)
    states={item.semantic_node_id:item for item in snapshot.entries}
    chapters=[]
    for node in template.chapter_order:
        state=states[node]
        item={'node_id':node,'chapter_contract_id':entries[node].contract.chapter_contract_id,
              'applicability':state.status.value,'errors':[]}
        if state.status.value=='not_applicable':
            item.update(status='not_applicable',reason=state.reason)
        else:
            try:
                _,bound=bind_applicable_chapter(study,entries[node].contract,
                    template.fact_catalog.bindings,rules=template.rules_catalog.rules)
            except (ApplicabilityResolutionError, FactBindingError):
                applicability, fact_errors=diagnose_applicable_input(study,entries[node].contract,
                    template.fact_catalog.bindings,rules=template.rules_catalog.rules)
                item['errors']=[{'code':finding.code,'location':finding.location} for finding in applicability]
                item['errors'].extend({'code':finding.code,'fact_paths':list(finding.fact_paths)} for finding in fact_errors)
                item['status']=('needs_information' if all(error['code'] in
                    {'conditional_applicability_unresolved','missing_required_fact','chapter_has_no_resolved_facts'}
                    for error in item['errors']) else 'invalid_input')
            else:
                item.update(status='facts_ready',bound_input_sha256=hashlib.sha256(
                    canonical_json(bound.model_dump(mode='json')).encode()).hexdigest())
        chapters.append(item)
    return _plan_payload(template,study,chapters,snapshot.model_dump(mode='json'))


def _plan_payload(template,study,chapters,snapshot):
    chapters=[{**chapter,'title':template.chapter_titles.get(chapter['node_id'],'方案章节')}
              for chapter in chapters]
    plan={'schema_version':'manuscript-chapter-plan.v1','scope':'chapter_fact_readiness',
          'project_id':study.project_id,'study_definition_id':study.study_definition_id,
          'study_sha256':study_revision_hash(study),'template':template_identity(template),
          'fact_catalog_sha256':hashlib.sha256(canonical_json(
              template.fact_catalog.model_dump(mode='json')).encode()).hexdigest(),
          'applicability_snapshot':snapshot,'chapters':chapters,
          'all_applicable_inputs_ready':all(item['status'] in {'facts_ready','not_applicable'} for item in chapters)}
    return {**plan,'plan_sha256':hashlib.sha256(canonical_json(plan).encode()).hexdigest()}
