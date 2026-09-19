"""Freeze every admitted chapter against one study and persisted source bundle.

Working-draft admission follows the versioned draft-readiness view (R2):
critical design confirmed and no applicability contradiction admit the
request; missing non-critical facts become explicit gap objects carried on
the frozen chapter inputs.
"""
from dataclasses import dataclass
import hashlib
import json

from app.protocol_workflow.canonical.hashing import canonical_json
from .chapter_draft import PreparedChapterDraftRequest, prepare_study_chapter
from .draft_readiness import draft_readiness
from .manuscript_plan import manuscript_preparation_view
from .source_preparation import SourcePreparationIncomplete


class ManuscriptInputsIncomplete(ValueError):
    def __init__(self, readiness):
        self.readiness = readiness
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
    readiness = draft_readiness(template, study, plan=plan)
    if not readiness['can_generate_working_draft']:
        raise ManuscriptInputsIncomplete(readiness)
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
    dispositions = {item['node_id']: item for item in readiness['chapter_dispositions']}
    bindings = {binding.fact_path: binding for binding in template.fact_catalog.bindings}
    for chapter in plan['chapters']:
        if chapter['status'] == 'not_applicable':
            continue
        disposition = dispositions[chapter['node_id']]
        deferred = tuple(disposition['gap_fact_paths'])
        if disposition['disposition'] == 'pending_decision':
            continue  # structure-unknown chapters stay out of dispatch (R2/A06)
        payload = prepare_study_chapter(template, study, chapter['node_id'],
            bundle.evidence, source_material=bundle,
            deferred_required_paths=deferred).to_payload()
        local = {key: payload.pop(key) for key in ('chapter_contract', 'chapter_input')}
        resolved = local['chapter_input']['resolved_facts']
        if not resolved:
            # Zero resolved facts: nothing to write. The assembly keeps the
            # chapter as a complete structure with an explicit gap object;
            # dispatching an empty write would only burn a model call.
            continue
        provenance[chapter['node_id']] = {path: [key for key in (
            bindings[path].canonical_path, *bindings[path].legacy_canonical_paths, path)
            if key in study.facts]
            for path in resolved}
        if shared is None:
            shared = payload
        elif shared != payload:
            raise ValueError('manuscript_shared_material_mismatch')
        chapters.append(local)
    if not chapters:
        raise ValueError('manuscript_has_no_applicable_chapters')
    text = canonical_json({'schema_version': 'manuscript-request.v2',
        'source_run_id': source_run_id, 'plan': plan, 'readiness': readiness,
        'shared': shared, 'chapters': chapters, 'fact_provenance': provenance})
    return PreparedManuscriptRequest(text, hashlib.sha256(text.encode()).hexdigest())
