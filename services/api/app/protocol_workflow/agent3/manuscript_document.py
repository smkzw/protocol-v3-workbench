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
    blocks, hashes = [], []
    for request in prepared.chapter_requests():
        chapter = request.to_payload()
        node = chapter['chapter_input']['node_id']
        candidate = read_chapter_draft(request, states[node]['validation']['proposal'])
        fact_paths = tuple(sorted({key for keys in payload['fact_provenance'][node].values() for key in keys}))
        if not fact_paths or any(key not in study.facts for key in fact_paths):
            raise ValueError('manuscript_document_fact_binding_missing')
        hashes.append(chapter['chapter_input']['chapter_contract_sha256'])
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
                chapter_contract_id=candidate.chapter_contract_id,
                substantive_content_contract_id=chapter['chapter_contract']['substantive_content']['substantive_content_contract_id'],
                block_kind=block.kind, content=content, fact_paths=fact_paths,
                claim_evidence_link_ids=(), medical_admission_unit_ids=(),
                content_sha256=hashlib.sha256(content.encode()).hexdigest(), canonical_state=CanonicalState.PROPOSED))
    snapshot = ApplicabilitySnapshot.model_validate(plan['applicability_snapshot'])
    return SemanticDocumentRevision(semantic_document_revision_id=document_id,
        project_id=study.project_id, study_definition_id=study.study_definition_id,
        study_definition_sha256=plan['study_sha256'],
        revision=current.revision + 1 if current else 1,
        previous_revision_sha256=document_revision_hash(current) if current else None,
        applicability_snapshot_id=snapshot.applicability_snapshot_id,
        applicability_snapshot_sha256=snapshot.material_sha256(), semantic_blocks=tuple(blocks),
        chapter_contract_hashes=tuple(hashes), updated_at=now, canonical_state=CanonicalState.PROPOSED)
