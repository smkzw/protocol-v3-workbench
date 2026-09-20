"""Design-elements proposal graph on the existing product runtime.

Same durable-request pattern as the regimen workflow: pinned compiled input,
generate -> validate on the shared GraphRuntime, one same-model structure
correction, unknown results never re-dispatched. Proposals stay proposals;
per-card human confirmation happens through the existing application command
with medical dependency declarations.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import hashlib
import json
from pydantic import ValidationError
from packages.contracts.workbench_contracts.protocol_v3 import ReasoningEffort, SensitivityTier
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import GraphNodeKind, GraphNodeOwner, GraphNodePlan, GraphPlan, GraphRuntime
from app.protocol_workflow.graph.ports import ConfiguredNodeServiceResult
from app.protocol_workflow.runtime.harness import ArtifactRef, build_request
from app.protocol_workflow.runtime.model_response import persist_model_response, read_model_response
from app.protocol_workflow.runtime.adapters.zhipu_api import REQUEST_TIMEOUT_SECONDS
from app.protocol_workflow.agent1.research_seed import PreparedSeedRequest
from .design_elements import (
    DESIGN_INSTRUCTION,
    DesignElementsProposal,
    read_design_elements_response,
)


@dataclass(frozen=True)
class PreparedDesignElementsRequest:
    payload_json: str
    input_sha256: str

    def to_payload(self) -> dict:
        return json.loads(self.payload_json)


def prepare_design_elements_request(source_intake: PreparedSeedRequest, seed: dict,
                                    confirmed_facts: dict) -> PreparedDesignElementsRequest:
    """Pin confirmed design facts, the original intake and the seed into one input.

    The confirmed facts are the caller's authoritative storage read; the
    proposal must agree with them (conditional sections) and stay consistent
    with the seed interpretation that produced the regimen.
    """
    if seed.get("input_sha256") != source_intake.input_sha256:
        raise ValueError("design_candidate_input_mismatch")
    payload = {
        "schema": "design_elements_request.v1",
        "instruction": DESIGN_INSTRUCTION,
        "source_intake": source_intake.to_payload(),
        "seed_proposal": seed,
        "confirmed_facts": confirmed_facts,
        "output_schema": DesignElementsProposal.model_json_schema(),
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return PreparedDesignElementsRequest(text, hashlib.sha256(text.encode("utf-8")).hexdigest())


def design_elements_execution_contract(base, *, skill, role_entry):
    if skill.skill_definition_id != "skill.design-elements-proposal" or role_entry.role_kind != "llm":
        raise ValueError("design_elements_skill_binding_mismatch")
    profile = role_entry.target_profile
    return base.model_copy(update={
        "skill_definition_id": skill.skill_definition_id, "role": role_entry.role_id,
        "harness": profile.harness, "provider": profile.provider, "model": profile.model,
        "reasoning_effort": ReasoningEffort(role_entry.default_effort),
        "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        "prompt_sha256": hashlib.sha256(DESIGN_INSTRUCTION.encode()).hexdigest(),
        "input_schema_ref": skill.input_schema_ref, "output_schema_ref": skill.output_schema_ref,
        "allowed_tools": skill.allowed_tools, "allowed_paths": skill.allowed_paths,
        "allowed_providers": (profile.provider,), "allowed_regions": profile.regions,
        "sensitivity_tier": SensitivityTier(profile.sensitivity_tier),
    })


def design_elements_plan(project_id, branch_id, *, correction=False):
    roots = ("design_elements_intake", "correction_context") if correction else ("design_elements_intake",)
    return GraphPlan(project_id=project_id, branch_id=branch_id,
        graph_id="design-elements-correction" if correction else "design-elements",
        graph_version="design-elements.v1",
        description="Propose source-bound design elements without adopting study facts.",
        schemas=(*roots, "raw_response", "design_elements_validation"), root_inputs=roots,
        nodes=(
            GraphNodePlan(node_id="design-generate", kind=GraphNodeKind.WORK,
                          owner=GraphNodeOwner.DESIGN_AND_SUMMARY, depends_on=(),
                          input_schemas=roots, output_schema="raw_response",
                          logical_key="design-elements.correct.v1" if correction else "design-elements.generate.v1"),
            GraphNodePlan(node_id="design-validate", kind=GraphNodeKind.CHECK,
                          owner=GraphNodeOwner.SYSTEM, depends_on=("design-generate",),
                          input_schemas=("design_elements_intake", "raw_response"),
                          output_schema="design_elements_validation",
                          logical_key="design-elements.validate.v1")))


def _prepared(request):
    text = canonical_json(request.inputs["design_elements_intake"])
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest != request.input_hashes["design_elements_intake"]:
        raise ValueError("design_elements_intake_material_mismatch")
    return PreparedDesignElementsRequest(text, digest)


def build_design_elements_runtime(*, project_id, uow_factory, reservation_repository_factory,
                                  artifact_store, role_entry, skill, dispatcher, adapter_factory,
                                  clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    def generate(request):
        prepared = _prepared(request)
        contract = request.execution_contract
        artifacts = [ArtifactRef(ref="design-elements-intake", sha256=prepared.input_sha256)]
        material = {("design-elements-intake", prepared.input_sha256): prepared.payload_json}
        if "correction_context" in request.inputs:
            context = request.inputs["correction_context"]
            if (context["provider"] != contract.provider or context["model"] != contract.model
                    or context["requested_reasoning_effort"] != contract.reasoning_effort.value):
                raise ValueError("design_elements_correction_model_mismatch")
            context_sha = request.input_hashes["correction_context"]
            artifacts.append(ArtifactRef(ref="correction-context", sha256=context_sha))
            material[("correction-context", context_sha)] = canonical_json(context)
        key = "design-elements-response:" + hashlib.sha256(request.reservation_id.encode()).hexdigest()
        def resolve(ref, sha):
            if (ref, sha) not in material:
                raise ValueError("design_elements_intake_material_mismatch")
            return material[(ref, sha)]
        adapter = adapter_factory(model=contract.model, timeout_seconds=contract.timeout_seconds,
            artifact_text_resolver=resolve,
            receipt_sink=lambda content, receipt: persist_model_response(
                artifact_store, key, content, receipt, created_at=clock()))
        harness_request = build_request(node_contract=contract, skill=skill, role_entry=role_entry,
                                        artifacts=tuple(sorted(artifacts, key=lambda a: a.sha256)),
                                        selected_region=role_entry.target_profile.regions[0])
        result = dispatcher.dispatch(request=harness_request, adapter=adapter)
        if not result.success or result.receipt is None:
            raise RuntimeError(
                f"{result.error_code or 'design_elements_dispatch_failed'}: "
                f"{result.error_message or 'no harness error message'}"
            )
        receipt = result.receipt
        return ConfiguredNodeServiceResult(payload={"artifact_ref": receipt.output_artifact_ref,
            "output_sha256": receipt.output_sha256}, provider_session_id=receipt.provider_session_id)
    def validate(request):
        prepared = _prepared(request)
        raw = request.inputs["raw_response"]
        record = read_model_response(artifact_store, raw["artifact_ref"])
        receipt = record["receipt"]
        if receipt["output_sha256"] != raw["output_sha256"]:
            raise ValueError("design_elements_response_material_mismatch")
        if prepared.input_sha256 not in {a["sha256"] for a in receipt["input_artifacts"]}:
            raise ValueError("design_elements_response_input_mismatch")
        raw_response = {**receipt, "artifact_ref": raw["artifact_ref"]}
        try:
            outcome = read_design_elements_response(prepared, json.loads(record["content"]))
        except json.JSONDecodeError as exc:
            errors = [{"code": "design_elements_invalid_json",
                       "location": f"line:{exc.lineno}:column:{exc.colno}"}]
        except ValidationError as exc:
            errors = [{"code": "design_elements_output_schema_invalid",
                       "location": ".".join(map(str, e["loc"])), "issue": e["type"]}
                      for e in exc.errors(include_input=False)]
        except ValueError as exc:
            code = str(exc)
            errors = [{"code": code if code.startswith("design_elements_")
                       else "design_elements_output_schema_invalid"}]
        else:
            return {"valid": True, "status": outcome["status"], "proposal": outcome["proposal"],
                    "errors": [], "raw_response": raw_response}
        return {"valid": False, "status": "needs_structure_correction", "proposal": None,
                "errors": errors, "raw_response": raw_response}
    return GraphRuntime(project_id=project_id, uow_factory=uow_factory,
        reservation_repository_factory=reservation_repository_factory,
        services={"design-generate": generate, "design-validate": validate}, clock=clock,
        execution_contract_factories={"design-generate": partial(
            design_elements_execution_contract, skill=skill, role_entry=role_entry)})
