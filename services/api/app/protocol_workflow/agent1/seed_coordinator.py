"""Thin application orchestration over the existing durable research graph."""
import hashlib
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import GraphRuntime, GraphRunError, EVENT_RUN_STARTED
from app.protocol_workflow.runtime.model_response import read_model_response
from app.protocol_workflow.graph.proposal_progress import proposal_outcome
from .research_seed import PreparedSeedRequest, prepare_seed_request
from .docx_parse import parse_docx
from .source_identity import SourceIdentityService
from .seed_workflow import seed_correction_inputs, seed_plan


class SeedCoordinator:
    """Reuse the logical request before considering a single known correction.

    Identity is project/branch/material, not mutable model configuration. A
    resumed run retains its pinned dispatch contract. This class neither
    retries an unknown provider outcome nor approves proposed medical facts.
    """

    def __init__(self, *, project_id: str, branch_id: str, runtime: GraphRuntime, artifact_store):
        self.project_id = project_id
        self.branch_id = branch_id
        self.runtime = runtime
        self.artifacts = artifact_store

    def request_run_id(self, user_brief: str, source_artifact_ids: list[str]) -> str:
        identity = canonical_json([self.project_id, self.branch_id, 'research-intake.request.v1',
                                   user_brief, sorted(set(source_artifact_ids))])
        return 'research-intake:' + hashlib.sha256(identity.encode()).hexdigest()

    def run_id(self, prepared: PreparedSeedRequest) -> str:
        payload = prepared.to_payload()
        return self.request_run_id(payload['user_brief'], [s['source_artifact_id'] for s in payload['sources']])

    def _legacy_run_id(self, prepared: PreparedSeedRequest) -> str:
        identity = canonical_json([self.project_id, self.branch_id, 'research-seed.v1', prepared.input_sha256])
        return 'research-seed:' + hashlib.sha256(identity.encode()).hexdigest()

    def start(self, prepared: PreparedSeedRequest) -> str:
        """Persist pending work before returning an HTTP acknowledgement; no call."""
        run_id = self.run_id(prepared)
        plan = seed_plan(self.project_id, self.branch_id)
        for existing_id in (run_id, self._legacy_run_id(prepared)):
            try:
                self.runtime.load_run(plan, existing_id)
            except GraphRunError as exc:
                if exc.code != 'graph_run_unknown':
                    raise
            else:
                # The first compiled package remains pinned across compiler changes.
                return existing_id
        try:
            self.runtime.start_run(plan, workflow_run_id=run_id,
                                   root_inputs={'research_intake': prepared.to_payload()})
        except GraphRunError as exc:
            if exc.code != 'graph_root_inputs_conflict':
                raise
            # Another owner committed the same original request after our
            # lookup. Keep its compiled package; never rebind the graph roots.
            self._pinned_request(run_id)
        return run_id

    def _pinned_request(self, run_id: str) -> PreparedSeedRequest:
        self.runtime.load_run(seed_plan(self.project_id, self.branch_id), run_id)
        event = next(e for e in self.runtime.read_events(run_id) if e.event_type == EVENT_RUN_STARTED)
        text = canonical_json(event.payload['root_payloads']['research_intake'])
        prepared = PreparedSeedRequest(text, hashlib.sha256(text.encode()).hexdigest())
        if run_id not in {self.run_id(prepared), self._legacy_run_id(prepared)}:
            raise ValueError('seed_run_identity_mismatch')
        return prepared

    def resume(self, run_id: str) -> dict:
        """Continue the pinned original materials, never a later source list."""
        return self._execute_pinned(self._pinned_request(run_id), run_id)

    def read(self, run_id: str) -> dict:
        """Read progress and proposal without dispatch, repair, or event writes."""
        self.runtime.load_run(seed_plan(self.project_id, self.branch_id), run_id)
        correction_id = run_id + ':correction:1'
        try:
            snapshot = self.runtime.load_run(seed_plan(self.project_id, self.branch_id, correction=True), correction_id)
        except GraphRunError as exc:
            if exc.code != 'graph_run_unknown':
                raise
            correction_id = None
            snapshot = self.runtime.load_run(seed_plan(self.project_id, self.branch_id), run_id)
        effective_id = correction_id or run_id
        outcome = self._outcome(effective_id, snapshot)
        return {'workflow_run_id': run_id, 'correction_run_id': correction_id, **outcome}

    def _outcome(self, run_id, snapshot, *, refresh_once=True) -> dict:
        plan = seed_plan(self.project_id, self.branch_id,
                         correction=snapshot.graph_id == 'research-seed-correction')
        result = proposal_outcome(self.runtime, plan, run_id, 'seed-validate',
                                  snapshot=snapshot, refresh_once=refresh_once)
        if result['validation'] is not None:
            result['can_resume'] = (result['status'] == 'needs_structure_correction'
                                    and snapshot.graph_id == 'research-seed')
        return result

    def prepared_request(self, run_id: str) -> PreparedSeedRequest:
        """Read the original pinned intake for the next design stage; no call."""
        return self._pinned_request(run_id)

    def _run(self, run_id: str, inputs: dict, *, correction: bool) -> dict:
        plan = seed_plan(self.project_id, self.branch_id, correction=correction)
        self.runtime.start_run(plan, workflow_run_id=run_id, root_inputs=inputs)
        snapshot = self.runtime.run_to_completion(run_id)
        return self._outcome(run_id, snapshot)

    def execute(self, prepared: PreparedSeedRequest) -> dict:
        return self.resume(self.start(prepared))

    def _execute_pinned(self, prepared: PreparedSeedRequest, run_id: str) -> dict:
        outcome = self._run(run_id, {'research_intake': prepared.to_payload()}, correction=False)
        correction_id = None
        validation = outcome['validation']
        if validation is not None and validation['status'] == 'needs_structure_correction':
            record = read_model_response(self.artifacts, validation['raw_response']['artifact_ref'])
            inputs = seed_correction_inputs(prepared, record, validation)
            correction_id = run_id + ':correction:1'
            outcome = self._run(correction_id, inputs, correction=True)
        return {'workflow_run_id': run_id, 'correction_run_id': correction_id, **outcome}


def prepare_current_seed(sources: SourceIdentityService, project_id: str,
                         user_brief: str, source_artifact_ids: list[str]) -> PreparedSeedRequest:
    """Pin a current-source snapshot, then read its immutable original bytes.

    Selection order has no meaning; sorting avoids repeated calls caused by
    UI list ordering. A stale selection must be refreshed, never silently
    replaced with another source version. This does not approve its content.
    """
    current = {record.source.source_artifact_id: record for record in sources.list_current(project_id)}
    selected = sorted(set(source_artifact_ids))
    if any(source_id not in current for source_id in selected):
        raise ValueError('seed_source_selection_stale')
    material = tuple((current[source_id].source,
                      parse_docx(sources.read_content(project_id, source_id)))
                     for source_id in selected)
    return prepare_seed_request(user_brief, material)
