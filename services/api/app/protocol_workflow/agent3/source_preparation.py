"""Persist full source context and one explicit, identifiable local-read retry.

Derived material only. Successful recovery returns its original extraction time;
known read failures are recorded outputs, while unknown execution outcomes keep
GraphRuntime's existing reconciliation semantics.
"""
from datetime import datetime,timezone
import hashlib
from app.protocol_workflow.agent1.docx_parse import PARSER_VERSION
from app.protocol_workflow.agent1.research_seed import PreparedSeedRequest
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import (
    EVENT_RUN_STARTED,GraphRunError,GraphPlan,GraphNodePlan,GraphNodeKind,
    GraphNodeOwner,GraphRuntime,
)
from .pinned_sources import read_pinned_chapter_sources
from .source_material import ChapterSourceMaterial


class SourcePreparationIncomplete(RuntimeError):
    def __init__(self,state):
        self.state=state
        super().__init__(state['error_code'] or 'chapter_source_preparation_incomplete')


def source_preparation_plan(project_id,branch_id):
    return GraphPlan(project_id=project_id,branch_id=branch_id,
        graph_id='chapter-source-preparation',graph_version='chapter-source-preparation.v1',
        description='Retain complete source context without medical admission.',
        schemas=('source_request','source_material'),root_inputs=('source_request',),
        nodes=(GraphNodePlan(node_id='prepare-sources',kind=GraphNodeKind.WORK,
            owner=GraphNodeOwner.SYSTEM,depends_on=(),input_schemas=('source_request',),
            output_schema='source_material',logical_key='chapter-source-preparation.v1',allowed_attempts=1),))


class SourcePreparationCoordinator:
    def __init__(self,project_id,branch_id,runtime):
        self.project_id=project_id;self.branch_id=branch_id;self.runtime=runtime
        self.plan=source_preparation_plan(project_id,branch_id)

    def _run_id(self,payload):
        material=canonical_json([self.project_id,self.branch_id,'chapter-source-preparation.v1',payload])
        return 'chapter-sources:'+hashlib.sha256(material.encode()).hexdigest()

    def run_id(self,seed):
        if hashlib.sha256(seed.payload_json.encode()).hexdigest()!=seed.input_sha256:
            raise ValueError('chapter_seed_material_mismatch')
        payload={'seed':seed.to_payload(),'parser_version':PARSER_VERSION}
        return self._run_id(payload)

    def start(self,seed):
        run_id=self.run_id(seed)
        payload={'seed':seed.to_payload(),'parser_version':PARSER_VERSION}
        try:self.runtime.load_run(self.plan,run_id)
        except GraphRunError as exc:
            if exc.code!='graph_run_unknown':raise
            self.runtime.start_run(self.plan,workflow_run_id=run_id,root_inputs={'source_request':payload})
        self._load(run_id)
        return run_id

    def _load(self,run_id):
        snapshot=self.runtime.load_run(self.plan,run_id)
        event=next(e for e in self.runtime.read_events(run_id) if e.event_type==EVENT_RUN_STARTED)
        payload=event.payload['root_payloads']['source_request']
        original={k:v for k,v in payload.items() if k!='retry_decision_id'}
        expected=self._run_id(original)+(':retry:1' if 'retry_decision_id' in payload else '')
        if expected!=run_id:raise ValueError('chapter_source_run_identity_mismatch')
        return snapshot,payload

    def _effective(self,run_id):
        snapshot,payload=self._load(run_id)
        if 'retry_decision_id' not in payload:
            try:return run_id+':retry:1',*self._load(run_id+':retry:1')
            except GraphRunError as exc:
                if exc.code!='graph_run_unknown':raise
        return run_id,snapshot,payload

    def prepared_seed(self,run_id):
        """Read the original selected input without touching source files."""
        _,payload=self._load(run_id)
        text=canonical_json(payload['seed'])
        return PreparedSeedRequest(text,hashlib.sha256(text.encode()).hexdigest())

    def _output(self,run_id):
        return next(e.payload['output'] for e in reversed(self.runtime.read_events(run_id))
            if e.event_type=='graph_node_result' and e.payload['node_id']=='prepare-sources')

    def state(self,run_id):
        effective,snapshot,payload=self._effective(run_id)
        attempts=self.runtime.reservation_attempts(effective,'prepare-sources')
        state={'workflow_run_id':run_id,'retry_run_id':effective if effective!=run_id else None,
            'status':snapshot.status.value,'stop_reason':snapshot.stop_reason,
            'error_code':attempts[-1].error_code if attempts else None,
            'can_resume':snapshot.status.value=='running','can_retry':False}
        if snapshot.status.value=='completed':
            failure=self._output(effective).get('source_preparation_failure')
            if failure:
                state.update(status='failed',error_code=failure['code'],stop_reason='source_read_failed',
                    can_retry='retry_decision_id' not in payload)
        return state

    def read(self,run_id):
        state=self.state(run_id)
        if state['status'] in {'blocked','failed'}:raise SourcePreparationIncomplete(state)
        if state['status']!='completed':return None
        payload=self._output(state['retry_run_id'] or run_id)
        text=canonical_json(payload)
        return ChapterSourceMaterial(text,hashlib.sha256(text.encode()).hexdigest())

    def resume(self,run_id):
        existing=self.read(run_id)
        if existing is not None:return existing
        effective,_,_=self._effective(run_id)
        self.runtime.run_to_completion(effective)
        result=self.read(run_id)
        if result is None:raise SourcePreparationIncomplete(self.state(run_id))
        return result

    def start_retry(self,run_id,*,retry_decision_id):
        """Register or validate the one retry before an HTTP acknowledgement."""
        if not isinstance(retry_decision_id,str) or not retry_decision_id.strip():
            raise ValueError('chapter_source_retry_identity_missing')
        state=self.state(run_id)
        _,payload=self._load(state['retry_run_id'] or run_id)
        if 'retry_decision_id' in payload:
            if payload['retry_decision_id']!=retry_decision_id:
                raise ValueError('chapter_source_retry_identity_mismatch')
            return state
        if state['status']=='completed':return state
        if not state['can_retry']:raise SourcePreparationIncomplete(state)
        _,payload=self._load(run_id)
        try:
            self.runtime.start_run(self.plan,workflow_run_id=run_id+':retry:1',
                root_inputs={'source_request':{**payload,'retry_decision_id':retry_decision_id}})
        except GraphRunError as exc:
            if exc.code not in {'graph_root_inputs_conflict','graph_run_binding_conflict'}:raise
            raise ValueError('chapter_source_retry_identity_mismatch') from exc
        return self.state(run_id)

    def retry(self,run_id,*,retry_decision_id):
        self.start_retry(run_id,retry_decision_id=retry_decision_id)
        return self.resume(run_id)


def build_source_preparation(*,project_id,branch_id,uow_factory,
        reservation_repository_factory,source_service,clock=None):
    clock=clock or (lambda:datetime.now(timezone.utc))
    def prepare(request):
        payload=request.inputs['source_request']
        if payload['parser_version']!=PARSER_VERSION:raise ValueError('chapter_source_parser_changed')
        text=canonical_json(payload['seed'])
        seed=PreparedSeedRequest(text,hashlib.sha256(text.encode()).hexdigest())
        try:
            return read_pinned_chapter_sources(source_service,project_id,seed,extracted_at=clock()).to_payload()
        except OSError:
            # This local read did not yield a bundle; preserve that known result.
            # Do not expose filesystem paths or treat arbitrary executor errors as known.
            return {'source_preparation_failure':{'code':'chapter_source_read_failed'}}
        except LookupError as exc:
            # Only the explicitly classified missing-source result is known;
            # programming KeyErrors and other unexpected failures stay unknown.
            if type(exc) is not LookupError or str(exc)!='chapter_source_not_found':raise
            return {'source_preparation_failure':{'code':'chapter_source_not_found'}}
    runtime=GraphRuntime(project_id=project_id,uow_factory=uow_factory,
        reservation_repository_factory=reservation_repository_factory,
        services={'prepare-sources':prepare},clock=clock,
        execution_contract_factories={'prepare-sources':lambda base:base})
    return SourcePreparationCoordinator(project_id,branch_id,runtime)
