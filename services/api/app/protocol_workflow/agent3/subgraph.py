"""Durable ordered chapter candidates on the existing graph and harness."""
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
from .chapter_draft import PreparedChapterDraftRequest, CHAPTER_DRAFT_INSTRUCTION, read_chapter_draft, ChapterDraftReferenceError


def chapter_draft_plan(project_id, branch_id, *, correction=False):
    roots = ("chapter_intake", "correction_context") if correction else ("chapter_intake",)
    return GraphPlan(project_id=project_id, branch_id=branch_id,
        graph_id="chapter-draft-correction" if correction else "chapter-draft", graph_version="chapter-draft.v1",
        description="Generate an ordered candidate; content and medical review remain separate.",
        schemas=(*roots, "raw_response", "chapter_validation"), root_inputs=roots,
        nodes=(
            GraphNodePlan(node_id="chapter-generate", kind=GraphNodeKind.WORK, owner=GraphNodeOwner.FULL_DRAFT,
                depends_on=(), input_schemas=roots, output_schema="raw_response",
                logical_key="chapter-draft.correct.v1" if correction else "chapter-draft.generate.v1", allowed_attempts=1),
            GraphNodePlan(node_id="chapter-validate", kind=GraphNodeKind.CHECK, owner=GraphNodeOwner.SYSTEM,
                depends_on=("chapter-generate",), input_schemas=("chapter_intake", "raw_response"),
                output_schema="chapter_validation", logical_key="chapter-draft.validate.v1", allowed_attempts=1),
        ))


def chapter_execution_contract(base, *, skill, role_entry):
    if skill.skill_definition_id != "skill.chapter-draft" or role_entry.role_kind != "llm":
        raise ValueError("chapter_skill_binding_mismatch")
    profile = role_entry.target_profile
    return base.model_copy(update={
        "skill_definition_id": skill.skill_definition_id, "role": role_entry.role_id,
        "harness": profile.harness, "provider": profile.provider, "model": profile.model,
        "reasoning_effort": ReasoningEffort(role_entry.default_effort), "timeout_seconds": REQUEST_TIMEOUT_SECONDS,
        "prompt_sha256": hashlib.sha256(CHAPTER_DRAFT_INSTRUCTION.encode()).hexdigest(),
        "input_schema_ref": skill.input_schema_ref, "output_schema_ref": skill.output_schema_ref,
        "allowed_tools": skill.allowed_tools, "allowed_paths": skill.allowed_paths,
        "allowed_providers": (profile.provider,), "allowed_regions": profile.regions,
        "sensitivity_tier": SensitivityTier(profile.sensitivity_tier),
    })


def build_chapter_draft_runtime(*, project_id, uow_factory, reservation_repository_factory,
        artifact_store, role_entry, skill, dispatcher, adapter_factory, clock=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    def prepared_input(request):
        text = canonical_json(request.inputs["chapter_intake"])
        return PreparedChapterDraftRequest(text, request.input_hashes["chapter_intake"])

    def generate(request):
        prepared = prepared_input(request)
        contract = request.execution_contract
        artifacts = [ArtifactRef(ref="chapter-intake", sha256=prepared.input_sha256)]
        material = {("chapter-intake", prepared.input_sha256): prepared.payload_json}
        if "correction_context" in request.inputs:
            context = request.inputs["correction_context"]
            if (context["provider"] != contract.provider or context["model"] != contract.model
                    or context["requested_reasoning_effort"] != contract.reasoning_effort.value):
                raise ValueError("chapter_correction_model_mismatch")
            context_sha = request.input_hashes["correction_context"]
            artifacts.append(ArtifactRef(ref="correction-context", sha256=context_sha))
            material[("correction-context", context_sha)] = canonical_json(context)
        key = "chapter-response:" + hashlib.sha256(request.reservation_id.encode()).hexdigest()
        def resolve(ref, sha):
            if (ref, sha) not in material:
                raise ValueError("chapter_input_hash_mismatch")
            return material[(ref, sha)]
        adapter = adapter_factory(model=contract.model, timeout_seconds=contract.timeout_seconds,
            artifact_text_resolver=resolve,
            receipt_sink=lambda content, receipt: persist_model_response(artifact_store, key, content, receipt, created_at=clock()))
        harness_request = build_request(node_contract=contract, skill=skill, role_entry=role_entry,
            artifacts=tuple(sorted(artifacts, key=lambda artifact: artifact.sha256)), selected_region=role_entry.target_profile.regions[0])
        result = dispatcher.dispatch(request=harness_request, adapter=adapter)
        if not result.success or result.receipt is None:
            raise RuntimeError(result.error_code or "chapter_dispatch_failed")
        receipt = result.receipt
        return ConfiguredNodeServiceResult(payload={"artifact_ref": receipt.output_artifact_ref,
            "output_sha256": receipt.output_sha256}, provider_session_id=receipt.provider_session_id)

    def validate(request):
        prepared = prepared_input(request)
        raw = request.inputs["raw_response"]
        record = read_model_response(artifact_store, raw["artifact_ref"])
        receipt = record["receipt"]
        if receipt["output_sha256"] != raw["output_sha256"]:
            raise ValueError("chapter_response_material_mismatch")
        if prepared.input_sha256 not in {a["sha256"] for a in receipt["input_artifacts"]}:
            raise ValueError("chapter_response_input_mismatch")
        base = {"raw_response": {**receipt, "artifact_ref": raw["artifact_ref"]},
                "validation_scope": "structure_and_input_identity"}
        try:
            candidate = read_chapter_draft(prepared, json.loads(record["content"]))
        except json.JSONDecodeError as exc:
            errors = [{"code": "chapter_invalid_json", "location": f"line:{exc.lineno}:column:{exc.colno}"}]
        except ValidationError as exc:
            errors = [{"code": "chapter_output_schema_invalid", "location": ".".join(map(str, item["loc"])),
                       "issue": item["type"], "detail": item["msg"]} for item in exc.errors(include_input=False)]
        except ChapterDraftReferenceError as exc:
            errors = [{"code": exc.code, "location": exc.location, "detail": exc.detail}]
        except ValueError as exc:
            errors = [{"code": str(exc) if str(exc).startswith("chapter_") else "chapter_output_schema_invalid"}]
        else:
            return {**base, "valid": True, "status": "needs_content_review",
                    "proposal": candidate.model_dump(mode="json"), "errors": []}
        return {**base, "valid": False, "status": "needs_structure_correction", "proposal": None, "errors": errors}

    return GraphRuntime(project_id=project_id, uow_factory=uow_factory,
        reservation_repository_factory=reservation_repository_factory,
        services={"chapter-generate": generate, "chapter-validate": validate}, clock=clock,
        execution_contract_factories={"chapter-generate": partial(chapter_execution_contract, skill=skill, role_entry=role_entry)})
