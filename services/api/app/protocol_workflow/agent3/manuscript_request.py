"""Freeze every applicable chapter against one study and persisted source bundle."""
from dataclasses import dataclass
import hashlib
import json

from app.protocol_workflow.canonical.hashing import canonical_json
from .chapter_draft import PreparedChapterDraftRequest, prepare_study_chapter
from .manuscript_plan import manuscript_preparation_view
from .source_preparation import SourcePreparationIncomplete


class ManuscriptInputsIncomplete(ValueError):
    def __init__(self, plan):
        self.plan = plan
        super().__init__('manuscript_inputs_incomplete')


@dataclass(frozen=True)
class PreparedManuscriptRequest:
    payload_json: str
    input_sha256: str

    def __post_init__(self):
        if hashlib.sha256(self.payload_json.encode()).hexdigest() != self.input_sha256:
            raise ValueError('manuscript_input_hash_mismatch')

    def to_payload(self):
        return json.loads(self.payload_json)

    def chapter_requests(self):
        """Restore the original instructions and schema, never today's defaults."""
        payload = self.to_payload()
        requests = []
        for chapter in payload['chapters']:
            text = canonical_json({**payload['shared'], **chapter})
            requests.append(PreparedChapterDraftRequest(
                text, hashlib.sha256(text.encode()).hexdigest()))
        return tuple(requests)


def prepare_manuscript_request(template, study, *, source_preparation, source_run_id):
    plan = manuscript_preparation_view(template, study)
    if not plan['all_applicable_inputs_ready']:
        raise ManuscriptInputsIncomplete(plan)
    if source_preparation.project_id != study.project_id:
        raise ValueError('chapter_source_project_mismatch')
    seed = source_preparation.prepared_seed(source_run_id)
    context = study.facts.get('research.input_context')
    if not isinstance(context, dict) or context.get('source_intake_sha256') != seed.input_sha256:
        raise ValueError('chapter_source_input_changed')
    bundle = source_preparation.read(source_run_id)
    if bundle is None:
        raise SourcePreparationIncomplete(source_preparation.state(source_run_id))
    shared = None
    chapters = []
    provenance = {}
    bindings = {binding.fact_path: binding for binding in template.fact_catalog.bindings}
    for chapter in plan['chapters']:
        if chapter['status'] == 'not_applicable':
            continue
        payload = prepare_study_chapter(template, study, chapter['node_id'],
            bundle.evidence, source_material=bundle).to_payload()
        local = {key: payload.pop(key) for key in ('chapter_contract', 'chapter_input')}
        provenance[chapter['node_id']] = {path: [key for key in (
            bindings[path].canonical_path, *bindings[path].legacy_canonical_paths, path)
            if key in study.facts]
            for path in local['chapter_input']['resolved_facts']}
        if shared is None:
            shared = payload
        elif shared != payload:
            raise ValueError('manuscript_shared_material_mismatch')
        chapters.append(local)
    if not chapters:
        raise ValueError('manuscript_has_no_applicable_chapters')
    text = canonical_json({'schema_version': 'manuscript-request.v1',
        'source_run_id': source_run_id, 'plan': plan, 'shared': shared, 'chapters': chapters,
        'fact_provenance': provenance})
    return PreparedManuscriptRequest(text, hashlib.sha256(text.encode()).hexdigest())
