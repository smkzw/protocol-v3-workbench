"""Research intake on the existing graph, with separate model and validation nodes."""
from datetime import datetime, timezone
from functools import partial
import hashlib

from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.graph import GraphNodeKind, GraphNodeOwner, GraphNodePlan, GraphPlan, GraphRuntime
from app.protocol_workflow.graph.ports import ConfiguredNodeServiceResult
from app.protocol_workflow.runtime.harness import ArtifactRef, build_request
from app.protocol_workflow.runtime.model_response import persist_model_response, read_model_response
from .research_seed import PreparedSeedRequest
from .seed_contract import seed_execution_contract
from .seed_validation import validate_seed_response


def seed_plan(project_id: str, branch_id: str, *, correction: bool = False) -> GraphPlan:
    roots = ('research_intake', 'correction_context') if correction else ('research_intake',)
    return GraphPlan(
        project_id=project_id, branch_id=branch_id,
        graph_id='research-seed-correction' if correction else 'research-seed', graph_version='research-seed.v1',
        description='Persist the raw model result, then validate proposed research facts.',
        schemas=(*roots, 'raw_response', 'seed_validation'), root_inputs=roots,
        nodes=(
            GraphNodePlan(node_id='seed-generate', kind=GraphNodeKind.WORK,
                          owner=GraphNodeOwner.DESIGN_AND_SUMMARY, depends_on=(),
                          input_schemas=roots, output_schema='raw_response',
                          logical_key='research-seed.correct.v1' if correction else 'research-seed.generate.v1'),
            GraphNodePlan(node_id='seed-validate', kind=GraphNodeKind.CHECK,
                          owner=GraphNodeOwner.SYSTEM, depends_on=('seed-generate',),
                          input_schemas=('research_intake', 'raw_response'), output_schema='seed_validation',
                          logical_key='research-seed.validate.v1'),
        ),
    )


def seed_correction_inputs(prepared: PreparedSeedRequest, record: dict, validation: dict) -> dict:
    """Build one new logical correction task from a known, invalid response.

    The original task remains completed. Neither unknown calls nor valid
    sparse results enter this path, and a correction does not correct itself.
    """
    if validation['valid'] or validation['status'] != 'needs_structure_correction':
        raise ValueError('seed_correction_not_required')
    receipt = record['receipt']
    if any(a['ref'] == 'correction-context' for a in receipt['input_artifacts']):
        raise ValueError('seed_correction_budget_exhausted')
    if (prepared.input_sha256 not in {a['sha256'] for a in receipt['input_artifacts']}
            or receipt['output_sha256'] != validation['raw_response']['output_sha256']):
        raise ValueError('seed_correction_material_mismatch')
    return {'research_intake': prepared.to_payload(), 'correction_context': {
        'instruction': '根据原始资料修复上次回复的结构或引用错误。不要补造研究事实；缺失字段仍可省略。只输出符合原请求结构的JSON。',
        'previous_output': record['content'], 'errors': validation['errors'],
        'previous_artifact_ref': validation['raw_response']['artifact_ref'],
        'previous_response_id': receipt['provider_session_id'],
        'provider': receipt['observed_provider'], 'model': receipt['observed_model'],
        'requested_reasoning_effort': receipt['requested_reasoning_effort'],
    }}


def _prepared(request) -> PreparedSeedRequest:
    text = canonical_json(request.inputs['research_intake'])
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if digest != request.input_hashes['research_intake']:
        raise ValueError('seed_intake_material_mismatch')
    return PreparedSeedRequest(text, digest)


def build_seed_runtime(*, project_id, uow_factory, reservation_repository_factory,
                       artifact_store, role_entry, skill, dispatcher, adapter_factory, clock=None) -> GraphRuntime:
    """Compose injected product boundaries; constructing this performs no model call.

    The application supplies the shared dispatcher/probe policy and adapter
    credentials. This layer never accesses credentials or starts a service.
    A graph-completed status describes execution; the validator's business
    status still distinguishes missing facts from a malformed response.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))

    def generate(request):
        prepared = _prepared(request)
        contract = request.execution_contract
        material = {('research-intake', prepared.input_sha256): prepared.payload_json}
        artifacts = [ArtifactRef(ref='research-intake', sha256=prepared.input_sha256)]
        if 'correction_context' in request.inputs:
            context = request.inputs['correction_context']
            if (context['provider'] != contract.provider or context['model'] != contract.model
                    or context['requested_reasoning_effort'] != contract.reasoning_effort.value):
                raise ValueError('seed_correction_model_mismatch')
            context_sha = request.input_hashes['correction_context']
            material[('correction-context', context_sha)] = canonical_json(context)
            artifacts.append(ArtifactRef(ref='correction-context', sha256=context_sha))
        key = 'seed-response:' + hashlib.sha256(request.reservation_id.encode()).hexdigest()

        def receipt_sink(content, receipt):
            return persist_model_response(artifact_store, key, content, receipt, created_at=clock())

        adapter = adapter_factory(
            model=contract.model, timeout_seconds=contract.timeout_seconds,
            artifact_text_resolver=lambda ref, sha: material[(ref, sha)], receipt_sink=receipt_sink,
        )
        harness_request = build_request(
            node_contract=contract, skill=skill, role_entry=role_entry,
            # GraphRuntime compacts dependencies in sorted digest order.
            # Harness validates that exact order, not merely the same set.
            artifacts=tuple(sorted(artifacts, key=lambda artifact: artifact.sha256)),
            selected_region=role_entry.target_profile.regions[0],
        )
        result = dispatcher.dispatch(request=harness_request, adapter=adapter)
        if not result.success or result.receipt is None:
            # An unproven provider outcome stays under existing reconciliation;
            # this service never repeats a call or invents a receipt.
            raise RuntimeError(result.error_code or 'seed_dispatch_failed')
        receipt = result.receipt
        return ConfiguredNodeServiceResult(
            payload={'artifact_ref': receipt.output_artifact_ref, 'output_sha256': receipt.output_sha256},
            provider_session_id=receipt.provider_session_id,
        )

    def validate(request):
        prepared = _prepared(request)
        raw = request.inputs['raw_response']
        record = read_model_response(artifact_store, raw['artifact_ref'])
        if record['receipt']['output_sha256'] != raw['output_sha256']:
            raise ValueError('seed_response_material_mismatch')
        return validate_seed_response(prepared, record, artifact_ref=raw['artifact_ref'])

    return GraphRuntime(
        project_id=project_id, uow_factory=uow_factory,
        reservation_repository_factory=reservation_repository_factory,
        services={'seed-generate': generate, 'seed-validate': validate}, clock=clock,
        execution_contract_factories={'seed-generate': partial(seed_execution_contract, skill=skill, role_entry=role_entry)},
    )
