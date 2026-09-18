"""Complete parsed source material with proposed, unassessed body evidence.

No source text is truncated or promoted into current research facts. The full
parse retains headings, TOC, bibliography, stories, merged cells and diagnostics;
only body units receive candidate evidence IDs here. Other roles remain context
for a later source assessment, rather than being relabeled as body evidence.
"""
from dataclasses import asdict,dataclass
import hashlib
import json

from app.protocol_workflow.agent1.research_seed import _units
from app.protocol_workflow.canonical.hashing import canonical_json
from packages.contracts.workbench_contracts.protocol_v3 import EvidenceUnit


@dataclass(frozen=True)
class ChapterSourceMaterial:
    payload_json: str
    input_sha256: str

    def to_payload(self):
        return json.loads(self.payload_json)

    @property
    def evidence(self):
        return tuple(EvidenceUnit.model_validate(unit) for unit in self.to_payload()['evidence'])


def prepare_chapter_source_material(sources, *, extracted_at):
    """The owner supplies the actual extraction time and persists the bundle.

    Recovery reads that original bundle, not a newly timestamped compilation.
    """
    materials=[];evidence=[];seen=set()
    for source,parsed in sources:
        if source.content_sha256!=parsed.content_sha256:
            raise ValueError('chapter_source_hash_mismatch')
        if source.source_artifact_id in seen:
            raise ValueError('chapter_source_identity_duplicate')
        seen.add(source.source_artifact_id)
        materials.append({'source':source.model_dump(mode='json'),'parse':asdict(parsed)})
        for unit in _units(parsed.blocks):
            if unit['role']!='body':
                continue
            identity=hashlib.sha256(canonical_json([source.source_artifact_id,
                source.content_sha256,parsed.parser_version,unit]).encode()).hexdigest()
            evidence.append(EvidenceUnit(evidence_unit_id='evidence:source:'+identity,
                source_artifact_id=source.source_artifact_id,source_content_sha256=source.content_sha256,
                source_role=source.source_role,locator_kind='table' if unit['kind']=='table_cell' else 'body',
                locator=unit['locator'],body=unit['text'],quality_score=0,
                extracted_at=extracted_at,canonical_state='proposed').model_dump(mode='json'))
    payload={'schema_version':'chapter-source-material.v1','sources':materials,'evidence':evidence,
        'quality_score_basis':'0 means unassessed; parsing is not clinical quality assessment',
        'medical_admission':'not_assessed'}
    text=canonical_json(payload)
    return ChapterSourceMaterial(text,hashlib.sha256(text.encode()).hexdigest())
