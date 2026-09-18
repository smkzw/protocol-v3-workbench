"""Durable design request identity on the existing GraphRuntime."""
import hashlib
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import GraphRunError, EVENT_RUN_STARTED
from app.protocol_workflow.graph.proposal_progress import proposal_outcome
from .clinical_worker import PreparedRegimenRequest
from .subgraph import regimen_plan
from app.protocol_workflow.runtime.model_response import read_model_response
from app.protocol_workflow.runtime.proposal_correction import structure_correction_inputs


class RegimenCoordinator:
    def __init__(self, *, project_id, branch_id, runtime, artifact_store):
        self.project_id, self.branch_id, self.runtime = project_id, branch_id, runtime
        self.artifacts = artifact_store

    def run_id(self, prepared):
        # Compiler/prompt changes do not create another request for the same
        # pinned source interpretation. A changed seed is a distinct input.
        payload = prepared.to_payload()
        material = [self.project_id, self.branch_id, "regimen-design.request.v1",
                    payload["seed_proposal"]]
        # Preserve historical source-only identities. A study-bound request is
        # distinct across target studies and actual clinical facts, not prompts.
        if "confirmed_study" in payload:
            material.extend(["confirmed-study.v1", payload["confirmed_study"]])
        identity = canonical_json(material)
        return "regimen-design:" + hashlib.sha256(identity.encode()).hexdigest()

    def start(self, prepared):
        run_id = self.run_id(prepared)
        plan = regimen_plan(self.project_id,self.branch_id)
        try:
            self.runtime.load_run(plan,run_id)
        except GraphRunError as exc:
            if exc.code != "graph_run_unknown":
                raise
        else:
            return run_id
        try:
            self.runtime.start_run(plan,workflow_run_id=run_id,root_inputs={"regimen_intake":prepared.to_payload()})
        except GraphRunError as exc:
            if exc.code != "graph_root_inputs_conflict":
                raise
            self.prepared_request(run_id)
        return run_id

    def prepared_request(self, run_id):
        self.runtime.load_run(regimen_plan(self.project_id,self.branch_id),run_id)
        event = next(e for e in self.runtime.read_events(run_id) if e.event_type == EVENT_RUN_STARTED)
        text = canonical_json(event.payload["root_payloads"]["regimen_intake"])
        prepared = PreparedRegimenRequest(text,hashlib.sha256(text.encode()).hexdigest())
        if self.run_id(prepared) != run_id:
            raise ValueError("regimen_run_identity_mismatch")
        return prepared

    def read(self, run_id):
        original = regimen_plan(self.project_id,self.branch_id)
        self.runtime.load_run(original,run_id)
        correction_id = run_id + ":correction:1"
        correction_plan = regimen_plan(self.project_id,self.branch_id,correction=True)
        try:
            snapshot = self.runtime.load_run(correction_plan,correction_id)
        except GraphRunError as exc:
            if exc.code != "graph_run_unknown":
                raise
            correction_id = None
            outcome = proposal_outcome(self.runtime,original,run_id,"regimen-validate")
            if outcome["validation"] is not None:
                outcome["can_resume"] = outcome["status"] == "needs_structure_correction"
        else:
            outcome = proposal_outcome(self.runtime,correction_plan,correction_id,"regimen-validate",snapshot=snapshot)
        target = self.prepared_request(run_id).to_payload().get("confirmed_study")
        return {"workflow_run_id":run_id,"correction_run_id":correction_id,
                "study_definition_id": target["study_definition_id"] if target else None, **outcome}

    def resume(self, run_id):
        prepared = self.prepared_request(run_id)
        self.runtime.run_to_completion(run_id)
        original = proposal_outcome(self.runtime,regimen_plan(self.project_id,self.branch_id),run_id,"regimen-validate")
        validation = original["validation"]
        if validation is not None and validation["status"] == "needs_structure_correction":
            record = read_model_response(self.artifacts,validation["raw_response"]["artifact_ref"])
            inputs = structure_correction_inputs(prepared,record,validation,input_name="regimen_intake",error_prefix="regimen")
            correction_id = run_id + ":correction:1"
            self.runtime.start_run(regimen_plan(self.project_id,self.branch_id,correction=True),
                                   workflow_run_id=correction_id,root_inputs=inputs)
            self.runtime.run_to_completion(correction_id)
        return self.read(run_id)
