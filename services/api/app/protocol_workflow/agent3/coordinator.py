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

    def _retryable_node(self, run_id, plan, node_id):
        """Return whether an owner retry can safely create the next attempt."""
        snapshot = self.runtime.load_run(plan, run_id)
        node = snapshot.node(node_id)
        if node.status.value not in {'failed', 'blocked_unknown'}:
            return False
        # A live lease is still owned by another dispatcher.  Explicit retry
        # must reconcile that owner first; it is never permission to
        # redispatch a still-live call.
        if (node.status.value == 'blocked_unknown'
                and self.runtime.node_has_live_dispatch(run_id, node_id)):
            return False
        return len(self.runtime.reservation_attempts(run_id, node_id)) < (
            plan.node(node_id).allowed_attempts)

    def _retry_node(self, run_id, plan, node_id):
        if not self._retryable_node(run_id, plan, node_id):
            return False
        attempts = self.runtime.reservation_attempts(run_id, node_id)
        latest = attempts[-1] if attempts else None
        if latest is not None and latest.status.value in {'reserved', 'running'}:
            # A dead pre-dispatch or in-flight shell must be explicitly
            # reconciled before a new attempt. UNKNOWN_OUTCOME remains
            # distinguishable and is never rewritten.
            self.runtime.resolve_blocked_with_failure(
                run_id,
                node_id=node_id,
                resolution_id=run_id + ':resolve:1',
                reason='owner reconciled the dead dispatch lease before retry',
            )
        self.runtime.retry_node(
            run_id,
            node_id=node_id,
            retry_decision_id=run_id + ':retry:1',
            reason='owner-approved explicit retry after reconciling the prior attempt',
            plan=plan,
        )
        # A successful retry leaves downstream validation pending.  Advance
        # the same pinned graph so the caller observes the complete outcome.
        self.runtime.run_to_completion(run_id)
        return True

    def _annotate_retry(self, outcome, run_id, plan, node_id):
        if outcome.get('status') == 'blocked':
            outcome = dict(outcome)
            outcome['can_resume'] = self._retryable_node(run_id, plan, node_id)
        return outcome

    def _correction_id(self, run_id):
        return run_id + ':correction:1'

    def _correction_plan(self):
        return chapter_draft_plan(self.project_id, self.branch_id, correction=True)

    def _original_plan(self):
        return chapter_draft_plan(self.project_id, self.branch_id)

    def _ensure_correction(self, run_id, prepared, validation):
        """Start or explicitly retry the one correction graph."""
        correction_id = self._correction_id(run_id)
        correction_plan = self._correction_plan()
        try:
            correction_snapshot = self.runtime.load_run(correction_plan, correction_id)
        except GraphRunError as exc:
            if exc.code != 'graph_run_unknown':
                raise
            from app.protocol_workflow.runtime.model_response import read_model_response
            from app.protocol_workflow.runtime.proposal_correction import structure_correction_inputs
            record = read_model_response(self.artifacts, validation['raw_response']['artifact_ref'])
            inputs = structure_correction_inputs(
                prepared, record, validation,
                input_name='chapter_intake', error_prefix='chapter')
            self.runtime.start_run(
                correction_plan,
                workflow_run_id=correction_id,
                root_inputs=inputs,
            )
            self.runtime.run_to_completion(correction_id)
            return correction_id

        if correction_snapshot.status.value == 'blocked':
            self._retry_node(correction_id, correction_plan, 'chapter-generate')
        else:
            self.runtime.run_to_completion(correction_id)
        return correction_id


    def read(self, run_id):
        self.prepared_request(run_id)
        correction_id = self._correction_id(run_id)
        correction_plan = self._correction_plan()
        try:
            snapshot = self.runtime.load_run(correction_plan, correction_id)
        except GraphRunError as exc:
            if exc.code != 'graph_run_unknown':
                raise
            correction_id = None
            original_plan = self._original_plan()
            outcome = proposal_outcome(
                self.runtime, original_plan, run_id, 'chapter-validate')
            if outcome['status'] == 'needs_structure_correction':
                outcome['can_resume'] = True
            elif outcome['status'] == 'blocked':
                outcome = self._annotate_retry(
                    outcome, run_id, original_plan, 'chapter-generate')
        else:
            outcome = proposal_outcome(
                self.runtime, correction_plan, correction_id,
                'chapter-validate', snapshot=snapshot)
            if outcome['status'] == 'blocked':
                outcome = self._annotate_retry(
                    outcome, correction_id, correction_plan, 'chapter-generate')
        return {'workflow_run_id': run_id, 'correction_run_id': correction_id,
                'study_definition_id': self.study_definition_id,
                'study_revision_sha256': self.study_revision_sha256, **outcome}

    def resume(self, run_id):
        prepared = self.prepared_request(run_id)
        original_plan = self._original_plan()
        self.runtime.run_to_completion(run_id)
        original = proposal_outcome(
            self.runtime, original_plan, run_id, 'chapter-validate')
        validation = original['validation']
        if validation is None and original['status'] == 'blocked':
            self._retry_node(run_id, original_plan, 'chapter-generate')
            original = proposal_outcome(
                self.runtime, original_plan, run_id, 'chapter-validate')
            validation = original['validation']
        if validation is None:
            return self.read(run_id)
        if validation['status'] == 'needs_structure_correction':
            self._ensure_correction(run_id, prepared, validation)
        return self.read(run_id)
