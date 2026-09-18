"""Durable design-elements request identity on the shared GraphRuntime.

Mirrors the regimen coordinator: stable run identity from the pinned input,
start is idempotent, read exposes the original target study, resume runs one
same-model structure correction at most and never re-dispatches unknowns.
"""
import hashlib
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import GraphRunError, EVENT_RUN_STARTED
from app.protocol_workflow.graph.proposal_progress import proposal_outcome
from .design_workflow import (
    PreparedDesignElementsRequest,
    design_elements_plan,
)
from app.protocol_workflow.runtime.model_response import read_model_response
from app.protocol_workflow.runtime.proposal_correction import structure_correction_inputs


class DesignElementsCoordinator:
    def __init__(self, *, project_id, branch_id, runtime, artifact_store):
        self.project_id, self.branch_id, self.runtime = project_id, branch_id, runtime
        self.artifacts = artifact_store

    def run_id(self, prepared):
        payload = prepared.to_payload()
        material = [self.project_id, self.branch_id, "design-elements.request.v1",
                    payload["seed_proposal"], payload["confirmed_facts"]]
        identity = canonical_json(material)
        return "design-elements:" + hashlib.sha256(identity.encode()).hexdigest()

    def start(self, prepared):
        run_id = self.run_id(prepared)
        plan = design_elements_plan(self.project_id, self.branch_id)
        try:
            self.runtime.load_run(plan, run_id)
        except GraphRunError as exc:
            if exc.code != "graph_run_unknown":
                raise
        else:
            return run_id
        try:
            self.runtime.start_run(plan, workflow_run_id=run_id,
                root_inputs={"design_elements_intake": prepared.to_payload()})
        except GraphRunError as exc:
            if exc.code != "graph_root_inputs_conflict":
                raise
            self.prepared_request(run_id)
        return run_id

    def prepared_request(self, run_id):
        self.runtime.load_run(design_elements_plan(self.project_id, self.branch_id), run_id)
        event = next(e for e in self.runtime.read_events(run_id) if e.event_type == EVENT_RUN_STARTED)
        text = canonical_json(event.payload["root_payloads"]["design_elements_intake"])
        prepared = PreparedDesignElementsRequest(text, hashlib.sha256(text.encode()).hexdigest())
        if self.run_id(prepared) != run_id:
            raise ValueError("design_elements_run_identity_mismatch")
        return prepared

    def read(self, run_id):
        original = design_elements_plan(self.project_id, self.branch_id)
        self.runtime.load_run(original, run_id)
        correction_id = run_id + ":correction:1"
        correction_plan = design_elements_plan(self.project_id, self.branch_id, correction=True)
        try:
            snapshot = self.runtime.load_run(correction_plan, correction_id)
        except GraphRunError as exc:
            if exc.code != "graph_run_unknown":
                raise
            correction_id = None
            outcome = proposal_outcome(self.runtime, original, run_id, "design-validate")
            if outcome["validation"] is not None:
                outcome["can_resume"] = outcome["status"] == "needs_structure_correction"
        else:
            outcome = proposal_outcome(self.runtime, correction_plan, correction_id,
                                       "design-validate", snapshot=snapshot)
        return {"workflow_run_id": run_id, "correction_run_id": correction_id, **outcome}

    def resume(self, run_id):
        prepared = self.prepared_request(run_id)
        self.runtime.run_to_completion(run_id)
        original = proposal_outcome(self.runtime,
            design_elements_plan(self.project_id, self.branch_id), run_id, "design-validate")
        validation = original["validation"]
        if validation is not None and validation["status"] == "needs_structure_correction":
            record = read_model_response(self.artifacts, validation["raw_response"]["artifact_ref"])
            inputs = structure_correction_inputs(prepared, record, validation,
                input_name="design_elements_intake", error_prefix="design_elements")
            correction_id = run_id + ":correction:1"
            self.runtime.start_run(design_elements_plan(self.project_id, self.branch_id, correction=True),
                workflow_run_id=correction_id, root_inputs=inputs)
            self.runtime.run_to_completion(correction_id)
        return self.read(run_id)
