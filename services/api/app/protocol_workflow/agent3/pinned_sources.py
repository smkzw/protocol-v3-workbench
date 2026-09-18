"""Read complete material for an already persisted seed without selecting latest.

The fresh-generation caller must separately verify the study's active input
context. Historical reads deliberately retain the originally selected versions.
No source adoption, model invocation or bundle persistence occurs here.
"""
import hashlib

from app.protocol_workflow.agent1.docx_parse import parse_docx
from app.protocol_workflow.agent1.research_seed import prepare_seed_request
from app.protocol_workflow.canonical.hashing import canonical_json
from .source_material import prepare_chapter_source_material


def read_pinned_chapter_sources(service, project_id, prepared_seed, *, extracted_at):
    if hashlib.sha256(prepared_seed.payload_json.encode()).hexdigest()!=prepared_seed.input_sha256:
        raise ValueError('chapter_seed_material_mismatch')
    expected=prepared_seed.to_payload()['sources']
    history={record.source.source_artifact_id:record.source for record in service.history(project_id)}
    materials=[]
    original_materials=[]
    for selected in expected:
        source=history.get(selected['source_artifact_id'])
        if source is None:
            raise LookupError('chapter_source_not_found')
        payload=service.read_content(project_id,source.source_artifact_id)
        parsed=parse_docx(payload)
        materials.append((source,parsed))
        original_materials.append((source,parsed if selected['parser_version']==parsed.parser_version
            else parse_docx(payload,parser_version=selected['parser_version'])))
    # Compare only the source projection; an unrelated change to the seed
    # prompt must not rewrite or invalidate the original text and descriptors.
    actual=prepare_seed_request('',tuple(original_materials)).to_payload()['sources']
    if canonical_json(actual)!=canonical_json(expected):
        raise ValueError('chapter_source_projection_changed')
    return prepare_chapter_source_material(tuple(materials),extracted_at=extracted_at)
