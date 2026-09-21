"""Recover an entire pinned draft through the existing chapter coordinators.

The registration graph stores input identity only. Public draft progress is
derived from every child, never from registration completing successfully.
"""
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import (
    EVENT_RUN_STARTED, GraphRunError, GraphPlan, GraphNodePlan,
    GraphNodeKind, GraphNodeOwner, GraphRuntime,
)
from .manuscript_request import PreparedManuscriptRequest


def manuscript_registration_plan(project_id, branch_id):
    return GraphPlan(project_id=project_id, branch_id=branch_id,
        graph_id='manuscript-registration', graph_version='manuscript-registration.v1',
        description='Pin a complete manuscript request, not completion of writing.',
        schemas=('manuscript_request', 'manuscript_identity'), root_inputs=('manuscript_request',),
        nodes=(GraphNodePlan(node_id='register-manuscript', kind=GraphNodeKind.CHECK,
            owner=GraphNodeOwner.SYSTEM, depends_on=(), input_schemas=('manuscript_request',),
            output_schema='manuscript_identity', logical_key='manuscript-register.v1', allowed_attempts=1),))


class ManuscriptDraftCoordinator:
    def __init__(self, *, project_id, branch_id, runtime, chapter_factory):
        self.project_id = project_id
        self.branch_id = branch_id
        self.runtime = runtime
        self.chapter_factory = chapter_factory
        self.plan = manuscript_registration_plan(project_id, branch_id)

    def run_id(self, prepared):
        plan = prepared.to_payload()['plan']
        if plan['project_id'] != self.project_id:
            raise ValueError('manuscript_project_mismatch')
        text = canonical_json([self.project_id, self.branch_id, 'manuscript-request.v1', prepared.input_sha256])
        return 'manuscript-draft:' + hashlib.sha256(text.encode()).hexdigest()

    def start(self, prepared):
        run_id = self.run_id(prepared)
        self.runtime.start_run(self.plan, workflow_run_id=run_id,
            root_inputs={'manuscript_request': prepared.to_payload()})
        return run_id

    def prepared_request(self, run_id):
        self.runtime.load_run(self.plan, run_id)
        event = next(event for event in self.runtime.read_events(run_id)
            if event.event_type == EVENT_RUN_STARTED)
        text = canonical_json(event.payload['root_payloads']['manuscript_request'])
        prepared = PreparedManuscriptRequest(text, hashlib.sha256(text.encode()).hexdigest())
        if self.run_id(prepared) != run_id:
            raise ValueError('manuscript_run_identity_mismatch')
        return prepared

    def _owner(self, prepared):
        plan = prepared.to_payload()['plan']
        owner = self.chapter_factory(self.project_id, plan['study_definition_id'], plan['study_sha256'])
        if owner.branch_id != self.branch_id:
            raise ValueError('manuscript_branch_mismatch')
        return owner

    def read(self, run_id):
        prepared = self.prepared_request(run_id)
        payload = prepared.to_payload()
        owner = self._owner(prepared)
        requests = {request.to_payload()['chapter_input']['node_id']: request
                    for request in prepared.chapter_requests()}
        chapters = []
        for item in payload['plan']['chapters']:
            if item['status'] == 'not_applicable':
                chapters.append(dict(item))
                continue
            request = requests.get(item['node_id'])
            if request is None:
                # prepare_manuscript_request keeps zero-resolved-fact and
                # structure-unknown chapters as explicit gap structures and
                # never dispatches them; report them outside the completion
                # math instead of treating them as lost child runs.
                chapters.append({**item, 'status': 'kept_as_gap', 'can_resume': False})
                continue
            child_id = owner.run_id(request)
            try:
                outcome = owner.read(child_id)
            except GraphRunError as exc:
                if exc.code != 'graph_run_unknown':
                    raise
                outcome = {'workflow_run_id': child_id, 'status': 'not_started',
                    'validation': None, 'can_resume': True}
            chapters.append({**item, **outcome})
        # A child controls its own resume permission. A non-retryable child
        # keeps the draft incomplete, but cannot freeze untouched siblings.
        applicable = [item for item in chapters
            if item['status'] not in {'not_applicable', 'kept_as_gap'}]
        complete = bool(applicable) and all(item['status'] == 'needs_content_review'
            and (item.get('validation') or {}).get('valid') is True for item in applicable)
        stopped = any(item['status'] not in {'not_started', 'running', 'needs_content_review'}
            and not item.get('can_resume') for item in applicable)
        return {'workflow_run_id': run_id, 'plan': payload['plan'], 'chapters': chapters,
            'status': 'needs_content_review' if complete else 'blocked' if stopped else 'running',
            'can_resume': not complete and any(item.get('can_resume') for item in applicable),
            'complete_candidate': complete, 'adopted': False}

    def resume(self, run_id):
        prepared = self.prepared_request(run_id)
        state = self.read(run_id)
        if not state['can_resume']:
            return state
        self.runtime.run_to_completion(run_id)
        owner = self._owner(prepared)
        # Sequential within a single pinned request: completed children keep
        # their identity and are never dispatched again.  A child with an
        # unknown outcome can proceed only through its coordinator's explicit
        # retry gate; a live lease remains blocked and is isolated here.
        import sys as _sys
        for request in prepared.chapter_requests():
            child_id = owner.run_id(request)
            try:
                try:
                    outcome = owner.read(child_id)
                except GraphRunError as exc:
                    if exc.code != 'graph_run_unknown':
                        raise
                    owner.start(request)
                    outcome = owner.read(child_id)
                if outcome['can_resume']:
                    outcome = owner.resume(child_id)
                if outcome['status'] != 'needs_content_review':
                    print('MANUSCRIPT CHAPTER INCOMPLETE:', request.to_payload()
                        ['chapter_input']['node_id'], outcome['status'],
                        str((outcome.get('validation') or {}).get('errors'))[:200],
                        file=_sys.stderr)
            except Exception as exc:  # noqa: BLE001 — 一章失败不拖垮全稿
                print('MANUSCRIPT CHAPTER FAILED:', request.to_payload()
                    ['chapter_input']['node_id'], type(exc).__name__, str(exc)[:300],
                    file=_sys.stderr)
        return self.read(run_id)


def build_manuscript_coordinator(*, project_id, branch_id, uow_factory,
        reservation_repository_factory, chapter_factory):
    runtime = GraphRuntime(project_id=project_id, uow_factory=uow_factory,
        reservation_repository_factory=reservation_repository_factory,
        services={'register-manuscript': lambda request: {
            'input_sha256': request.input_hashes['manuscript_request']}})
    return ManuscriptDraftCoordinator(project_id=project_id, branch_id=branch_id,
        runtime=runtime, chapter_factory=chapter_factory)
