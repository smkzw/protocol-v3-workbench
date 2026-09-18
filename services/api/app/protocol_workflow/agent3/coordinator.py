"""Recover chapter requests by their pinned study and complete input identity."""
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import EVENT_RUN_STARTED, GraphRunError
from app.protocol_workflow.graph.proposal_progress import proposal_outcome
from .chapter_draft import PreparedChapterDraftRequest
from .subgraph import chapter_draft_plan


class ChapterDraftCoordinator:
    def __init__(self, *, project_id, branch_id, study_definition_id,
                 study_revision_sha256, runtime, artifact_store=None, require_bound_input=False):
        if not study_definition_id.strip():
            raise ValueError("chapter_study_identity_missing")
        if len(study_revision_sha256) != 64 or any(
                char not in '0123456789abcdef' for char in study_revision_sha256):
            raise ValueError("chapter_study_revision_invalid")
        self.project_id = project_id
        self.branch_id = branch_id
        self.study_definition_id = study_definition_id
        self.study_revision_sha256 = study_revision_sha256
        self.runtime = runtime
        self.artifacts = artifact_store
        self.require_bound_input = require_bound_input

    def run_id(self, prepared):
        chapter_input = prepared.to_payload()['chapter_input']
        if self.require_bound_input and chapter_input.get('schema_version') != 'protocol-v3-bound-chapter-input.v1':
            raise ValueError('chapter_bound_input_required')
        if chapter_input.get('schema_version') == 'protocol-v3-bound-chapter-input.v1':
            if (chapter_input.get('project_id') != self.project_id
                    or chapter_input.get('study_definition_id') != self.study_definition_id
                    or chapter_input.get('study_sha256') != self.study_revision_sha256):
                raise ValueError('chapter_study_binding_mismatch')
        material = canonical_json([
            self.project_id, self.branch_id, 'chapter-draft.request.v1',
            self.study_definition_id, self.study_revision_sha256,
            prepared.input_sha256,
        ])
        return 'chapter-draft:' + hashlib.sha256(material.encode()).hexdigest()

    def start(self, prepared):
        run_id = self.run_id(prepared)
        plan = chapter_draft_plan(self.project_id, self.branch_id)
        try:
            self.runtime.load_run(plan, run_id)
        except GraphRunError as exc:
            if exc.code != 'graph_run_unknown':
                raise
        else:
            self.prepared_request(run_id)
            return run_id
        self.runtime.start_run(plan, workflow_run_id=run_id,
                               root_inputs={'chapter_intake': prepared.to_payload()})
        return run_id

    def prepared_request(self, run_id):
        self.runtime.load_run(chapter_draft_plan(self.project_id, self.branch_id), run_id)
        event = next(event for event in self.runtime.read_events(run_id)
                     if event.event_type == EVENT_RUN_STARTED)
        text = canonical_json(event.payload['root_payloads']['chapter_intake'])
        prepared = PreparedChapterDraftRequest(text, hashlib.sha256(text.encode()).hexdigest())
        if self.run_id(prepared) != run_id:
            raise ValueError('chapter_run_identity_mismatch')
        return prepared

    def read(self, run_id):
        self.prepared_request(run_id)
        correction_id = run_id + ':correction:1'
        correction_plan = chapter_draft_plan(self.project_id, self.branch_id, correction=True)
        try:
            snapshot = self.runtime.load_run(correction_plan, correction_id)
        except GraphRunError as exc:
            if exc.code != 'graph_run_unknown':
                raise
            correction_id = None
            outcome = proposal_outcome(self.runtime,
                chapter_draft_plan(self.project_id, self.branch_id), run_id, 'chapter-validate')
            if outcome['status'] == 'needs_structure_correction':
                outcome['can_resume'] = True
        else:
            outcome = proposal_outcome(self.runtime, correction_plan, correction_id,
                                       'chapter-validate', snapshot=snapshot)
        return {'workflow_run_id': run_id, 'correction_run_id': correction_id,
                'study_definition_id': self.study_definition_id,
                'study_revision_sha256': self.study_revision_sha256, **outcome}

    def resume(self, run_id):
        from app.protocol_workflow.runtime.model_response import read_model_response
        from app.protocol_workflow.runtime.proposal_correction import structure_correction_inputs
        prepared = self.prepared_request(run_id)
        self.runtime.run_to_completion(run_id)
        original = proposal_outcome(self.runtime,
            chapter_draft_plan(self.project_id, self.branch_id), run_id, 'chapter-validate')
        validation = original['validation']
        if validation is not None and validation['status'] == 'needs_structure_correction':
            record = read_model_response(self.artifacts, validation['raw_response']['artifact_ref'])
            inputs = structure_correction_inputs(prepared, record, validation,
                input_name='chapter_intake', error_prefix='chapter')
            correction_id = run_id + ':correction:1'
            self.runtime.start_run(chapter_draft_plan(self.project_id, self.branch_id, correction=True),
                workflow_run_id=correction_id, root_inputs=inputs)
            self.runtime.run_to_completion(correction_id)
        return self.read(run_id)
