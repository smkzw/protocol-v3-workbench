"""Typed recommendation and quote records, separate from medical admission.

The caller supplies a persisted validated proposal. Literal source matching
proves transcription only; every clinical link remains proposed/limited until
an actual semantic assessment is recorded. No medical admission is fabricated.
"""
import hashlib
from app.protocol_workflow.canonical.hashing import canonical_json
from packages.contracts.workbench_contracts.protocol_v3 import (
    RecommendationOption, EvidenceUnit, ClaimEvidenceLink, EvidenceClass,
    EvidenceRelation, LocatorKind, CanonicalState,
)


def _identity(prefix, value):
    return prefix + hashlib.sha256(canonical_json(value).encode()).hexdigest()


def build_regimen_option_bundle(prepared, proposal, *, workflow_run_id, output_sha256, extracted_at):
    sources={source['source_artifact_id']:source for source in prepared.to_payload()['source_intake']['sources']}
    regimen=proposal.get('regimen')
    if not regimen:
        raise ValueError('option_regimen_missing')
    option_id=_identity('regimen-option:',[workflow_run_id,output_sha256])
    units={};links=[];roles=set()
    for schedule in regimen['schedules']:
        for index,step in enumerate(schedule['steps']):
            evidence_ids=[]
            for reference in step.get('references',[]):
                source=sources.get(reference['source_artifact_id'])
                source_unit=next((unit for unit in source['units']
                    if unit['locator']==reference['locator'] and reference['quote'] and reference['quote'] in unit['text']),None) if source else None
                if source_unit is None:
                    raise ValueError('option_quote_not_in_pinned_source')
                unit_id=_identity('evidence-unit:',[source['source_artifact_id'],source['content_sha256'],reference['locator'],reference['quote']])
                if unit_id not in units:
                    quote_start = source_unit['text'].index(reference['quote'])
                    quote_end = quote_start + len(reference['quote'])
                    # 1.0 is the deterministic exact-transcription result,
                    # never a medical relevance, completeness or approval score.
                    units[unit_id]=EvidenceUnit(evidence_unit_id=unit_id,
                        source_artifact_id=source['source_artifact_id'],source_content_sha256=source['content_sha256'],
                        source_role=source['source_role'],locator_kind=LocatorKind.TABLE if source_unit.get('kind')=='table_cell' else LocatorKind.BODY,
                        locator=reference['locator'],body=reference['quote'],quality_score=1.0,
                        context_before=source_unit['text'][:quote_start],
                        context_after=source_unit['text'][quote_end:],
                        extracted_at=extracted_at,canonical_state=CanonicalState.PROPOSED)
                evidence_ids.append(unit_id);roles.add(source['source_role'])
            if evidence_ids:
                claim_id=_identity('regimen-step-claim:',[option_id,schedule['period_id'],schedule['arm_id'],index])
                links.append(ClaimEvidenceLink(claim_evidence_link_id=_identity('claim-evidence:',[claim_id,evidence_ids]),
                    claim_id=claim_id,evidence_unit_ids=tuple(dict.fromkeys(evidence_ids)),relation=EvidenceRelation.LIMITS,
                    rationale='已定位引用原文；其对本研究给药决策的适用性尚未经医学核对。',canonical_state=CanonicalState.PROPOSED))
    role=next(iter(roles)) if len(roles)==1 else 'none'
    evidence_class=EvidenceClass(role) if role in {item.value for item in EvidenceClass} else EvidenceClass.NONE
    option=RecommendationOption(recommendation_option_id=option_id,decision_key='decision:dose-regimen',
        label='整理后的完整给药方案',rationale='将所选资料中的治疗期、组别与给药步骤整理为一套可逐项核对的方案。',
        evidence_class=evidence_class,claim_evidence_link_ids=tuple(link.claim_evidence_link_id for link in links),
        uncertainty='引用可以定位；本研究适用性和给药依据的完整性仍待医学核对。',
        downstream_impact='可能影响摘要、给药方案及相关统计条件。',is_default=True,canonical_state=CanonicalState.PROPOSED)
    return {'schema':'regimen-option-bundle.v1','workflow_run_id':workflow_run_id,
        'input_sha256':prepared.input_sha256,'output_sha256':output_sha256,
        'proposal_status':proposal['status'],'option':option.model_dump(mode='json'),
        'evidence_units':[unit.model_dump(mode='json') for unit in units.values()],
        'claim_evidence_links':[link.model_dump(mode='json') for link in links],
        'quality_score_basis':'literal quote matches pinned source at its exact locator; not medical quality',
        'medical_admission':'not_assessed'}
