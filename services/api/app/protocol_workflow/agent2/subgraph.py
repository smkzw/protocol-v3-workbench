"""Regimen proposal graph on the existing product runtime and model receipts."""
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
from .clinical_worker import PreparedRegimenRequest, REGIMEN_INSTRUCTION, read_regimen_response


def regimen_execution_contract(base, *, skill, role_entry):
    if skill.skill_definition_id != "skill.regimen-design-proposal" or role_entry.role_kind != "llm":
        raise ValueError("regimen_skill_binding_mismatch")
    profile = role_entry.target_profile
    return base.model_copy(update={
        "skill_definition_id": skill.skill_definition_id, "role": role_entry.role_id,
        "harness": profile.harness, "provider": profile.provider, "model": profile.model,
        "reasoning_effort": ReasoningEffort(role_entry.default_effort),
        "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        "prompt_sha256": hashlib.sha256(REGIMEN_INSTRUCTION.encode()).hexdigest(),
        "input_schema_ref": skill.input_schema_ref, "output_schema_ref": skill.output_schema_ref,
        "allowed_tools": skill.allowed_tools, "allowed_paths": skill.allowed_paths,
        "allowed_providers": (profile.provider,), "allowed_regions": profile.regions,
        "sensitivity_tier": SensitivityTier(profile.sensitivity_tier),
    })


def regimen_plan(project_id, branch_id, *, correction=False):
    roots = ("regimen_intake", "correction_context") if correction else ("regimen_intake",)
    return GraphPlan(project_id=project_id, branch_id=branch_id, graph_id="regimen-design-correction" if correction else "regimen-design",
        graph_version="regimen-design.v1", description="Propose a complete source-bound regimen without adopting study facts.",
        schemas=(*roots, "raw_response", "regimen_validation"), root_inputs=roots,
        nodes=(
            GraphNodePlan(node_id="regimen-generate", kind=GraphNodeKind.WORK, owner=GraphNodeOwner.DESIGN_AND_SUMMARY,
                          depends_on=(), input_schemas=roots, output_schema="raw_response", logical_key="regimen-design.correct.v1" if correction else "regimen-design.generate.v1"),
            GraphNodePlan(node_id="regimen-validate", kind=GraphNodeKind.CHECK, owner=GraphNodeOwner.SYSTEM,
                          depends_on=("regimen-generate",), input_schemas=("regimen_intake", "raw_response"),
                          output_schema="regimen_validation", logical_key="regimen-design.validate.v1")))


def _prepared(request):
    text = canonical_json(request.inputs["regimen_intake"])
    digest = hashlib.sha256(text.encode()).hexdigest()
    if digest != request.input_hashes["regimen_intake"]:
        raise ValueError("regimen_intake_material_mismatch")
    return PreparedRegimenRequest(text, digest)


def build_regimen_runtime(*, project_id, uow_factory, reservation_repository_factory,
                          artifact_store, role_entry, skill, dispatcher, adapter_factory, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    def generate(request):
        prepared = _prepared(request)
        contract = request.execution_contract
        artifacts = [ArtifactRef(ref="regimen-intake", sha256=prepared.input_sha256)]
        material = {("regimen-intake", prepared.input_sha256): prepared.payload_json}
        if "correction_context" in request.inputs:
            context = request.inputs["correction_context"]
            if (context["provider"] != contract.provider or context["model"] != contract.model
                    or context["requested_reasoning_effort"] != contract.reasoning_effort.value):
                raise ValueError("regimen_correction_model_mismatch")
            context_sha = request.input_hashes["correction_context"]
            artifacts.append(ArtifactRef(ref="correction-context",sha256=context_sha))
            material[("correction-context",context_sha)] = canonical_json(context)
        key = "regimen-response:" + hashlib.sha256(request.reservation_id.encode()).hexdigest()
        def resolve(ref, sha):
            if (ref, sha) not in material:
                raise ValueError("regimen_intake_material_mismatch")
            return material[(ref, sha)]
        adapter = adapter_factory(model=contract.model, timeout_seconds=contract.timeout_seconds,
            artifact_text_resolver=resolve,
            receipt_sink=lambda content, receipt: persist_model_response(artifact_store, key, content, receipt, created_at=clock()))
        harness_request = build_request(node_contract=contract, skill=skill, role_entry=role_entry,
                                        artifacts=tuple(sorted(artifacts,key=lambda a:a.sha256)), selected_region=role_entry.target_profile.regions[0])
        result = dispatcher.dispatch(request=harness_request, adapter=adapter)
        if not result.success or result.receipt is None:
            raise RuntimeError(result.error_code or "regimen_dispatch_failed")
        receipt = result.receipt
        return ConfiguredNodeServiceResult(payload={"artifact_ref": receipt.output_artifact_ref,
            "output_sha256": receipt.output_sha256}, provider_session_id=receipt.provider_session_id)
    def validate(request):
        prepared = _prepared(request)
        raw = request.inputs["raw_response"]
        record = read_model_response(artifact_store, raw["artifact_ref"])
        receipt = record["receipt"]
        if receipt["output_sha256"] != raw["output_sha256"]:
            raise ValueError("regimen_response_material_mismatch")
        if prepared.input_sha256 not in {a["sha256"] for a in receipt["input_artifacts"]}:
            raise ValueError("regimen_response_input_mismatch")
        raw_response = {**receipt, "artifact_ref": raw["artifact_ref"]}
        try:
            proposal = read_regimen_response(prepared, json.loads(record["content"]))
        except json.JSONDecodeError as exc:
            errors = [{"code": "regimen_invalid_json", "location": f"line:{exc.lineno}:column:{exc.colno}"}]
        except ValidationError as exc:
            errors = [{"code": "regimen_output_schema_invalid", "location": ".".join(map(str,e["loc"])),
                       "issue": e["type"]} for e in exc.errors(include_input=False)]
        except ValueError as exc:
            code = str(exc)
            errors = [{"code": code if code.startswith(("regimen_", "design_candidate_")) else "regimen_output_schema_invalid"}]
        else:
            return {"valid": True, "status": proposal["status"], "proposal": proposal, "errors": [], "raw_response": raw_response}
        # Preserve malformed output; no automatic semantic retry or fallback.
        return {"valid": False, "status": "needs_structure_correction", "proposal": None,
                "errors": errors, "raw_response": raw_response}
    return GraphRuntime(project_id=project_id, uow_factory=uow_factory,
        reservation_repository_factory=reservation_repository_factory,
        services={"regimen-generate": generate, "regimen-validate": validate}, clock=clock,
        execution_contract_factories={"regimen-generate": partial(regimen_execution_contract, skill=skill, role_entry=role_entry)})
