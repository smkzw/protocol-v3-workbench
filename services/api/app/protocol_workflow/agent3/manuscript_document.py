"""Project a complete candidate into the existing proposed working document.

Source references remain provenance, never invented medical admission IDs.
Structured tables are encoded only in TABLE content; readers decode the typed
object rather than displaying its serialized representation as prose.
"""
import hashlib

from packages.contracts.workbench_contracts.protocol_v3 import (
    ApplicabilitySnapshot, CanonicalState, SemanticBlock, SemanticDocumentRevision,
)
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.study_definition import study_revision_hash
from app.protocol_workflow.canonical.document import document_revision_hash
from .chapter_draft import read_chapter_draft


_GAP_INSTRUCTION = ('【待补充】本章所需的研究信息尚未全部确认。确认后可由系统补写，'
                    '也可直接在文档中完善；当前工作稿不会据此编造结论。')
_PENDING_INSTRUCTION = ('【待判定】本章是否适用仍需结合已确认的研究设计判断。'
                        '完成相关选择后，系统将生成对应内容。')


def _gap_block(node_id, contract_id, content_id, fact_paths, text, now):
    block_id = 'manuscript-block:' + hashlib.sha256(
        canonical_json([node_id, 'gap', sorted(fact_paths)]).encode()).hexdigest()
    content = text
    return SemanticBlock(semantic_block_id=block_id, semantic_node_id=node_id,
        chapter_contract_id=contract_id,
        substantive_content_contract_id=content_id,
        block_kind='paragraph', content=content, fact_paths=tuple(fact_paths),
        claim_evidence_link_ids=(), medical_admission_unit_ids=(),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        canonical_state=CanonicalState.PROPOSED)


def assemble_working_manuscript(prepared, state, study, *, document_id, now, current=None):
    payload = prepared.to_payload()
    plan = payload['plan']
    if (plan['project_id'] != study.project_id or plan['study_definition_id'] != study.study_definition_id
            or plan['study_sha256'] != study_revision_hash(study)):
        raise ValueError('manuscript_document_study_changed')
    if not state['complete_candidate'] or state['plan'] != plan:
        raise ValueError('manuscript_document_incomplete')
    if current is not None and (current.project_id != study.project_id
        or current.study_definition_id != study.study_definition_id
        or current.semantic_document_revision_id != document_id):
        raise ValueError('manuscript_document_identity_mismatch')
    states = {item['node_id']: item for item in state['chapters']}
    dispositions = {item['node_id']: item
                    for item in (payload.get('readiness') or {}).get('chapter_dispositions', [])}
    dispatched = {}
    for request in prepared.chapter_requests():
        chapter = request.to_payload()
        dispatched[chapter['chapter_input']['node_id']] = (request, chapter)
    blocks, hashes = [], []
    for plan_chapter in plan['chapters']:
        node = plan_chapter['node_id']
        if plan_chapter['status'] == 'not_applicable':
            continue
        if node in dispatched:
            request, chapter = dispatched[node]
            candidate = read_chapter_draft(request, states[node]['validation']['proposal'])
            fact_paths = tuple(sorted({key for keys in payload['fact_provenance'][node].values() for key in keys}))
            if any(key not in study.facts for key in fact_paths):
                raise ValueError('manuscript_document_fact_binding_missing')
            hashes.append(chapter['chapter_input']['chapter_contract_sha256'])
            contract_id = candidate.chapter_contract_id
            content_id = chapter['chapter_contract']['substantive_content']['substantive_content_contract_id']
            for block in candidate.blocks:
                block_id = 'manuscript-block:' + hashlib.sha256(canonical_json([node, block.block_id]).encode()).hexdigest()
                if block.kind == 'table':
                    table = block.table.model_dump(mode='json')
                    table['block_id'] = block_id
                    table['table_id'] = 'manuscript-table:' + hashlib.sha256(canonical_json([node, table['table_id']]).encode()).hexdigest()
                    content = canonical_json({'schema_version': 'semantic-structured-table.v1', 'table': table})
                else:
                    content = block.text.strip()
                blocks.append(SemanticBlock(semantic_block_id=block_id, semantic_node_id=node,
                    chapter_contract_id=contract_id,
                    substantive_content_contract_id=content_id,
                    block_kind=block.kind, content=content, fact_paths=fact_paths,
                    claim_evidence_link_ids=(), medical_admission_unit_ids=(),
                    content_sha256=hashlib.sha256(content.encode()).hexdigest(), canonical_state=CanonicalState.PROPOSED))
            continue
        # Gap-only or pending chapters keep complete structure with explicit,
        # locatable gap objects (R2): never deleted, never "not applicable".
        item = dispositions.get(node)
        if item is None:
            raise ValueError('manuscript_document_disposition_missing')
        fact_paths = tuple(item.get('gap_fact_paths') or ())
        if not fact_paths:
            fact_paths = ('research.input_context',)
        if item['disposition'] == 'pending_decision':
            text = _PENDING_INSTRUCTION
        else:
            text = _GAP_INSTRUCTION
        blocks.append(_gap_block(node, plan_chapter['chapter_contract_id'],
            item['substantive_content_contract_id'], fact_paths, text, now))
    snapshot = ApplicabilitySnapshot.model_validate(plan['applicability_snapshot'])
    return SemanticDocumentRevision(semantic_document_revision_id=document_id,
        project_id=study.project_id, study_definition_id=study.study_definition_id,
        study_definition_sha256=plan['study_sha256'],
        revision=current.revision + 1 if current else 1,
        previous_revision_sha256=document_revision_hash(current) if current else None,
        applicability_snapshot_id=snapshot.applicability_snapshot_id,
        applicability_snapshot_sha256=snapshot.material_sha256(), semantic_blocks=tuple(blocks),
        chapter_contract_hashes=tuple(hashes), updated_at=now, canonical_state=CanonicalState.PROPOSED)
