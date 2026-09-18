"""Router factory for the Protocol v3 API skeleton (Task 1.9).

Design authority: Protocol v3 multi-agent rearchitecture design sections 5.1
(authority boundary), 5.4 (Agent⑤ coordination boundary), 17.2 (only the
application service opens a unit of work), 18 (stable error handling) and the
frozen plan Task 1.9.

Boundary rules
--------------
* The factory returns an :class:`APIRouter` under
  ``/api/projects/{project_id}/protocol-workflow``.  It is tested through a
  local in-process ``FastAPI`` app. Task 1R.2 product mounting belongs to
  ``composition.mount_protocol_workflow_router``.
* The router retains the :class:`ApplicationService`, the immutable
  :class:`RegistrySelection` and the typed observer/clock configuration, but
  builds a FRESH :class:`Agent5QueryFacade` and :class:`Agent5Coordinator`
  for every Agent⑤ request from that request's
  ``project_id`` / ``study_definition_id`` / ``workflow_run_id`` — so
  progress, gates, decision requests, manifest pins and decompositions
  always observe current state and never reuse a stale snapshot.
* Mutations translate the typed application commands (project / revision /
  idempotency / actor / reason / full :class:`DecisionRecord`) and reject a
  path/body project mismatch BEFORE any service or coordinator call.  GET
  queries perform no writes.
* There is deliberately NO client-supplied exception-card endpoint: a client
  must never invent a catalog failure or wrap server state.  Real
  :class:`ProtocolWorkflowError` failures cross the HTTP boundary ONLY
  through the catalog's Chinese-native public copy
  (:meth:`ProtocolWorkflowError.to_public_payload`).  Machine codes, object
  ids, attempts, owner enums, recovery actions and audit detail/context stay
  server-side.  Request validation and project mismatch use the same stable
  Chinese envelope and never call the service.
* No repository, unit-of-work or storage handle is exposed, and no raw
  fact/Gate/QC/submission mutation endpoint exists.

Hosting note: product composition handles structural validation at route scope.
Do not register the exported validation handler globally on ``app.main``;
standalone contract-test apps may register it locally.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.protocol_workflow.agent5 import (
    Agent5Coordinator,
    Agent5QueryFacade,
    GateObservation,
    RegistrySelection,
    WorkPackageSpec,
)
from app.protocol_workflow.application import (
    ApplicationService,
    ApplyStudyDecisionCommand,
    CreateStudyDefinitionCommand,
    GetDecisionGraphQuery,
    GetStudyDefinitionEventSummaryQuery,
    GetStudyDefinitionQuery,
    GetWorkflowRunStatusQuery,
    SideEffectSpec,
    StudyDefinitionMutationResult,
)
from app.protocol_workflow.application.adoption import GetTemplateAdoptionQuery
from app.protocol_workflow.application.queries import GetSemanticDocumentQuery
from app.protocol_workflow.application.commands import TemplateAdoptionIntent
from app.protocol_workflow.errors import (
    OWNER_PUBLIC_LABEL,
    ProtocolErrorCode,
    ProtocolErrorOwner,
    ProtocolWorkflowError,
)

from .schemas import (
    CurrentSemanticDocumentResponse,
    CurrentStudyDefinitionResponse,
    DecisionGraphRecordResponse,
    DecisionGraphResponse,
    DecisionRequestQueueResponse,
    DecisionRequestResponse,
    DecisionSummaryResponse,
    EventSummaryResponse,
    GateSummaryResponse,
    ProgressSummaryResponse,
    RunManifestPinRequest,
    RunManifestResponse,
    StudyDefinitionCreateRequest,
    StudyDefinitionDecisionApplyRequest,
    StudyDefinitionMutationResponse,
    TemplateAdoptionIdentityResponse,
    TemplateAdoptionResponse,
    WorkPackageDecompositionRequest,
    WorkPackageDecompositionResponse,
    WorkflowRunStatusRecordResponse,
    WorkflowRunStatusResponse,
)

__all__ = [
    "create_protocol_workflow_router",
    "protocol_workflow_not_found_envelope",
    "protocol_workflow_validation_exception_handler",
]

_ROUTER_AREA = OWNER_PUBLIC_LABEL[ProtocolErrorOwner.APPLICATION_SERVICE]


# ---------------------------------------------------------------------------
# Stable Chinese public envelopes (no audit/program fields)
# ---------------------------------------------------------------------------


def _envelope(*, message: str, can_retry: bool, next_step: str) -> dict:
    return {
        "message": message,
        "responsible_area": _ROUTER_AREA,
        "can_retry": can_retry,
        "next_step": next_step,
    }


def _request_envelope() -> dict:
    return _envelope(
        message="请求内容与当前工作台要求不符，本次操作未执行。",
        can_retry=False,
        next_step="请核对请求内容后重新提交。",
    )


def _not_found_envelope() -> dict:
    return _envelope(
        message="未找到所请求的方案工作流对象。",
        can_retry=False,
        next_step="请核对项目与对象标识后重新请求。",
    )


def _unexpected_envelope() -> dict:
    return _envelope(
        message="当前操作的结果尚未确认。",
        can_retry=False,
        next_step="请先刷新查看已保存内容，核对本次操作结果，暂勿重复提交。",
    )


def protocol_workflow_not_found_envelope() -> dict:
    """Public copy of the stable Chinese not-found envelope.

    Task 1R.2 composition uses this for the durable-allowlist admission
    gate so rejected (non-admitted) projects observe exactly the same
    envelope as an absent workflow object — never a new error shape.
    """

    return _not_found_envelope()

def protocol_workflow_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Hosting-app handler keeping structural validation in the stable
    Chinese envelope.  Register with
    ``app.add_exception_handler(RequestValidationError, handler)``."""

    return JSONResponse(status_code=422, content={"detail": _request_envelope()})


def _status_for(error: ProtocolWorkflowError) -> int:
    # This typed error is raised before mutation; preserve the distinction
    # from an unclassified failure after a possible commit.
    if error.code is ProtocolErrorCode.P1_SERVICE_CONFIGURATION_INCOMPLETE:
        return 424
    if error.code is ProtocolErrorCode.P1_OBJECT_NOT_FOUND:
        return 404
    if error.code in {
        ProtocolErrorCode.P1_REVISION_STALE,
        ProtocolErrorCode.P1_DECISION_CAS,
    }:
        return 409
    return 409 if error.retryable else 500


# ---------------------------------------------------------------------------
# Shared call wrapper
# ---------------------------------------------------------------------------


def _safe_call(
    fn: Callable[[], object],
    *,
    request_errors: Tuple[type, ...] = (ValueError, TypeError, LookupError),
) -> object:
    """Translate service/coordinator/command failures into the stable public
    envelope.  Only :meth:`ProtocolWorkflowError.to_public_payload` reaches
    the HTTP response; request-shape failures use the Chinese request
    envelope; an unexpected failure requires reconciliation before retry
    because its commit outcome is not known here."""

    try:
        return fn()
    except HTTPException:
        # Pass through router-raised status/envelope (e.g. 404 not-found)
        # without degrading it to the generic 500 envelope.
        raise
    except ProtocolWorkflowError as exc:
        raise HTTPException(
            status_code=_status_for(exc), detail=exc.to_public_payload()
        ) from exc
    except request_errors as exc:
        raise HTTPException(status_code=422, detail=_request_envelope()) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=_unexpected_envelope()) from exc


# ---------------------------------------------------------------------------
# Router configuration
# ---------------------------------------------------------------------------


class _RouterConfig:
    __slots__ = ("application_service", "registry_selection", "gate_observer", "clock")

    def __init__(
        self,
        *,
        application_service: ApplicationService,
        registry_selection: RegistrySelection,
        gate_observer: Optional[Callable[[], Tuple[GateObservation, ...]]],
        clock: Optional[Callable[[], datetime]],
    ) -> None:
        self.application_service = application_service
        self.registry_selection = registry_selection
        self.gate_observer = gate_observer
        self.clock = clock

    def fresh_coordinator(
        self,
        *,
        project_id: str,
        study_definition_id: str,
        workflow_run_id: str,
    ) -> Agent5Coordinator:
        """Build a fresh query façade + coordinator for ONE Agent⑤ request.

        The facade executes the four typed queries at construction, so every
        Agent⑤ call observes current state; a long-lived snapshot is never
        retained (design section 5.4 / frozen plan Task 1.9)."""

        facade = Agent5QueryFacade(
            service=self.application_service,
            project_id=project_id,
            study_definition_id=study_definition_id,
            workflow_run_id=workflow_run_id,
        )
        return Agent5Coordinator(
            application=facade,
            registry_selection=self.registry_selection,
            gate_observer=self.gate_observer,
            clock=self.clock,
        )


def _require_path_match(path_value: str, body_value: str) -> None:
    if path_value != body_value:
        raise HTTPException(status_code=422, detail=_request_envelope())


def _to_side_effect_spec(side_effect: object) -> Optional[SideEffectSpec]:
    if side_effect is None:
        return None
    return SideEffectSpec(
        workflow_run_id=side_effect.workflow_run_id,
        side_effect_kind=side_effect.side_effect_kind,
    )


def _mutation_response(
    result: StudyDefinitionMutationResult,
) -> StudyDefinitionMutationResponse:
    return StudyDefinitionMutationResponse(
        project_id=result.project_id,
        study_definition_id=result.study_definition_id,
        definition=result.definition,
        revision=result.revision,
        revision_sha256=result.revision_sha256,
        effective_decision=result.effective_decision,
        replayed=result.replayed,
    )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def _register_routes(router: APIRouter, config: _RouterConfig) -> None:
    # --- Mutations ---------------------------------------------------------

    @router.post(
        "/study-definitions",
        response_model=StudyDefinitionMutationResponse,
        summary="创建方案定义",
    )
    def create_study_definition(
        project_id: str, body: StudyDefinitionCreateRequest
    ) -> StudyDefinitionMutationResponse:
        _require_path_match(project_id, body.project_id)

        def _execute() -> StudyDefinitionMutationResult:
            command = CreateStudyDefinitionCommand(
                project_id=body.project_id,
                study_definition_id=body.study_definition_id,
                idempotency_key=body.idempotency_key,
                expected_revision=body.expected_revision,
                actor_type=body.actor_type,
                actor_id=body.actor_id,
                reason=body.reason,
                decision_record=body.decision_record,
                normalized_seed_id=body.normalized_seed_id,
                normalized_seed_sha256=body.normalized_seed_sha256,
                initial_facts=dict(body.initial_facts),
                side_effect=_to_side_effect_spec(body.side_effect),
            )
            return config.application_service.create_study_definition(command)

        return _mutation_response(_safe_call(_execute))  # type: ignore[arg-type]

    @router.post(
        "/study-definitions/{study_definition_id}/decisions",
        response_model=StudyDefinitionMutationResponse,
        summary="应用方案设计决策",
    )
    def apply_study_decision(
        project_id: str,
        study_definition_id: str,
        body: StudyDefinitionDecisionApplyRequest,
    ) -> StudyDefinitionMutationResponse:
        _require_path_match(project_id, body.project_id)
        _require_path_match(study_definition_id, body.study_definition_id)

        def _execute() -> StudyDefinitionMutationResult:
            command = ApplyStudyDecisionCommand(
                project_id=body.project_id,
                study_definition_id=body.study_definition_id,
                idempotency_key=body.idempotency_key,
                expected_revision=body.expected_revision,
                actor_type=body.actor_type,
                actor_id=body.actor_id,
                reason=body.reason,
                decision_record=body.decision_record,
                fact_updates=(
                    None if body.fact_updates is None else dict(body.fact_updates)
                ),
                side_effect=_to_side_effect_spec(body.side_effect),
                revise_confirmed_facts=body.revise_confirmed_facts,
                decision_input_refs=body.decision_input_refs,
                template_adoption=(
                    None
                    if body.template_adoption is None
                    else TemplateAdoptionIntent(
                        template_id=body.template_adoption.template_id,
                        retired_fact_paths=tuple(
                            body.template_adoption.retired_fact_paths
                        ),
                    )
                ),
            )
            return config.application_service.apply_decision(command)

        return _mutation_response(_safe_call(_execute))  # type: ignore[arg-type]

    # --- Read-only queries -------------------------------------------------

    @router.get(
        "/study-definitions/{study_definition_id}",
        response_model=CurrentStudyDefinitionResponse,
        summary="读取当前方案定义",
    )
    def get_study_definition(
        project_id: str, study_definition_id: str
    ) -> CurrentStudyDefinitionResponse:
        def _execute() -> CurrentStudyDefinitionResponse:
            result = config.application_service.get_study_definition(
                GetStudyDefinitionQuery(
                    project_id=project_id,
                    study_definition_id=study_definition_id,
                )
            )
            if result.definition is None:
                raise HTTPException(status_code=404, detail=_not_found_envelope())
            return CurrentStudyDefinitionResponse(
                definition=result.definition,
                revision=result.revision,
                revision_sha256=result.revision_sha256,
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.get("/study-definitions/{study_definition_id}/manuscript-plan",
                summary="核对完整初稿所需研究信息")
    def get_manuscript_plan(project_id: str, study_definition_id: str):
        def execute():
            result = config.application_service.get_manuscript_plan(
                GetStudyDefinitionQuery(project_id, study_definition_id))
            if result is None:
                raise HTTPException(404, detail=_not_found_envelope())
            return result
        return _safe_call(execute)

    @router.get(
        "/study-definitions/{study_definition_id}/documents/{semantic_document_revision_id}",
        response_model=CurrentSemanticDocumentResponse,
        summary="读取已保存的方案正文",
    )
    def get_semantic_document(project_id: str, study_definition_id: str,
                              semantic_document_revision_id: str):
        def execute():
            result = config.application_service.get_semantic_document(
                GetSemanticDocumentQuery(project_id, study_definition_id, semantic_document_revision_id))
            if result.document is None:
                raise HTTPException(404, detail=_not_found_envelope())
            return CurrentSemanticDocumentResponse(document=result.document,
                revision_sha256=result.revision_sha256, study_binding_status=result.study_binding_status)
        return _safe_call(execute)

    @router.get(
        "/study-definitions/{study_definition_id}/events",
        response_model=EventSummaryResponse,
        summary="读取方案事件摘要与决策沿革",
    )
    def get_study_definition_events(
        project_id: str, study_definition_id: str
    ) -> EventSummaryResponse:
        def _execute() -> EventSummaryResponse:
            result = config.application_service.get_study_definition_event_summary(
                GetStudyDefinitionEventSummaryQuery(
                    project_id=project_id,
                    study_definition_id=study_definition_id,
                )
            )
            return EventSummaryResponse(
                project_id=result.project_id,
                study_definition_id=result.study_definition_id,
                event_count=result.event_count,
                last_sequence=result.last_sequence,
                last_event_sha256=result.last_event_sha256,
                decisions=tuple(
                    DecisionSummaryResponse(
                        cas_identity=item.cas_identity,
                        decision_record_id=item.decision_record_id,
                        decision_key=item.decision_key,
                        selected_option_id=item.selected_option_id,
                        state_revision=item.state_revision,
                        applied_revision=item.applied_revision,
                        canonical_state=item.canonical_state,
                        decided_at=item.decided_at,
                    )
                    for item in result.decisions
                ),
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.get(
        "/study-definitions/{study_definition_id}/decision-graph",
        response_model=DecisionGraphResponse,
        summary="读取方案决策关系图",
    )
    def get_decision_graph(
        project_id: str, study_definition_id: str
    ) -> DecisionGraphResponse:
        def _execute() -> DecisionGraphResponse:
            result = config.application_service.get_decision_graph(
                GetDecisionGraphQuery(
                    project_id=project_id,
                    study_definition_id=study_definition_id,
                )
            )
            return DecisionGraphResponse(
                project_id=result.project_id,
                study_definition_id=result.study_definition_id,
                records=tuple(
                    DecisionGraphRecordResponse(
                        project_id=record.project_id,
                        decision_key=record.decision_key,
                        decision_record_id=record.decision_record_id,
                        state_revision=record.state_revision,
                        selected_option_id=record.selected_option_id,
                        canonical_state=record.canonical_state,
                        current_validity=record.current_validity,
                    )
                    for record in result.records
                ),
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.get(
        "/study-definitions/{study_definition_id}/template-adoption",
        response_model=TemplateAdoptionResponse,
        summary="读取最近一次模板事实采用记录",
    )
    def get_template_adoption(
        project_id: str, study_definition_id: str
    ) -> TemplateAdoptionResponse:
        def _execute() -> TemplateAdoptionResponse:
            result = config.application_service.get_template_adoption(
                GetTemplateAdoptionQuery(
                    project_id=project_id,
                    study_definition_id=study_definition_id,
                )
            )
            if result is None:
                raise HTTPException(status_code=404, detail=_not_found_envelope())
            return TemplateAdoptionResponse(
                project_id=result.project_id,
                study_definition_id=result.study_definition_id,
                cas_identity=result.cas_identity,
                decision_record_id=result.decision_record_id,
                decision_key=result.decision_key,
                base_revision=result.base_revision,
                base_revision_sha256=result.base_revision_sha256,
                applied_revision=result.applied_revision,
                applied_revision_sha256=result.applied_revision_sha256,
                facts_before_sha256=result.facts_before_sha256,
                facts_after_sha256=result.facts_after_sha256,
                changed_fact_paths=result.changed_fact_paths,
                retired_fact_paths=result.retired_fact_paths,
                template=TemplateAdoptionIdentityResponse(**result.template),
                applicability_snapshot=dict(result.applicability_snapshot),
                impact_plan=dict(result.impact_plan),
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.get(
        "/workflow-runs/{workflow_run_id}",
        response_model=WorkflowRunStatusResponse,
        summary="读取工作流运行状态",
    )
    def get_workflow_run_status(
        project_id: str, workflow_run_id: str
    ) -> WorkflowRunStatusResponse:
        def _execute() -> WorkflowRunStatusResponse:
            result = config.application_service.get_workflow_run_status(
                GetWorkflowRunStatusQuery(
                    project_id=project_id,
                    workflow_run_id=workflow_run_id,
                )
            )
            status = result.status
            return WorkflowRunStatusResponse(
                project_id=result.project_id,
                workflow_run_id=result.workflow_run_id,
                status=(
                    None
                    if status is None
                    else WorkflowRunStatusRecordResponse(
                        project_id=status.project_id,
                        workflow_run_id=status.workflow_run_id,
                        status=status.status,
                        display_progress=status.display_progress,
                        journey_counter=status.journey_counter,
                    )
                ),
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    # --- Agent⑤ surfaces (fresh snapshot per request) ---------------------

    @router.get(
        "/workflow-runs/{workflow_run_id}/progress",
        response_model=ProgressSummaryResponse,
        summary="读取运行进度与方案版本汇总",
    )
    def get_workflow_run_progress(
        project_id: str,
        workflow_run_id: str,
        study_definition_id: str,
    ) -> ProgressSummaryResponse:
        def _execute() -> ProgressSummaryResponse:
            coordinator = config.fresh_coordinator(
                project_id=project_id,
                study_definition_id=study_definition_id,
                workflow_run_id=workflow_run_id,
            )
            summary = coordinator.aggregate_progress(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                study_definition_id=study_definition_id,
            )
            return ProgressSummaryResponse(**summary.model_dump())

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.get(
        "/workflow-runs/{workflow_run_id}/gates",
        response_model=GateSummaryResponse,
        summary="读取方案审阅关口汇总",
    )
    def get_workflow_run_gates(
        project_id: str,
        workflow_run_id: str,
        study_definition_id: str,
    ) -> GateSummaryResponse:
        def _execute() -> GateSummaryResponse:
            coordinator = config.fresh_coordinator(
                project_id=project_id,
                study_definition_id=study_definition_id,
                workflow_run_id=workflow_run_id,
            )
            summary = coordinator.aggregate_gates(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
            )
            return GateSummaryResponse(
                project_id=summary.project_id,
                workflow_run_id=summary.workflow_run_id,
                observations=summary.observations,
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.get(
        "/workflow-runs/{workflow_run_id}/decision-requests",
        response_model=DecisionRequestQueueResponse,
        summary="读取待确认决策队列",
    )
    def get_workflow_run_decision_requests(
        project_id: str,
        workflow_run_id: str,
        study_definition_id: str,
    ) -> DecisionRequestQueueResponse:
        def _execute() -> DecisionRequestQueueResponse:
            coordinator = config.fresh_coordinator(
                project_id=project_id,
                study_definition_id=study_definition_id,
                workflow_run_id=workflow_run_id,
            )
            queue = coordinator.build_decision_request_queue(
                project_id=project_id,
                study_definition_id=study_definition_id,
            )
            return DecisionRequestQueueResponse(
                project_id=queue.project_id,
                study_definition_id=queue.study_definition_id,
                requests=tuple(
                    DecisionRequestResponse(**item.model_dump())
                    for item in queue.requests
                ),
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.post(
        "/workflow-runs/{workflow_run_id}/manifest",
        response_model=RunManifestResponse,
        summary="固定运行清单",
    )
    def pin_run_manifest(
        project_id: str,
        workflow_run_id: str,
        body: RunManifestPinRequest,
    ) -> RunManifestResponse:
        _require_path_match(project_id, body.project_id)
        _require_path_match(workflow_run_id, body.workflow_run_id)

        def _execute() -> RunManifestResponse:
            coordinator = config.fresh_coordinator(
                project_id=project_id,
                study_definition_id=body.study_definition_id,
                workflow_run_id=workflow_run_id,
            )
            manifest = coordinator.pin_run_manifest(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                protocol_template=body.protocol_template,
                graph=body.graph,
                contract_schema_version=body.contract_schema_version,
                source_revision_hashes=body.source_revision_hashes,
                study_definition_id=body.study_definition_id,
                skills=body.skills,
            )
            return RunManifestResponse(
                workflow_run_id=manifest.workflow_run_id,
                project_id=manifest.project_id,
                protocol_template_version=manifest.protocol_template_version,
                protocol_template_sha256=manifest.protocol_template_sha256,
                graph_version=manifest.graph_version,
                graph_sha256=manifest.graph_sha256,
                contract_schema_version=manifest.contract_schema_version,
                skills=manifest.skills,
                source_revision_hashes=manifest.source_revision_hashes,
                study_definition_id=manifest.study_definition_id,
                study_definition_revision=manifest.study_definition_revision,
                study_definition_sha256=manifest.study_definition_sha256,
                created_at=manifest.created_at,
                content_sha256=manifest.content_sha256(),
            )

        return _safe_call(_execute)  # type: ignore[return-value]

    @router.post(
        "/workflow-runs/{workflow_run_id}/decomposition",
        response_model=WorkPackageDecompositionResponse,
        summary="分解已注册工作包",
    )
    def decompose_work_packages(
        project_id: str,
        workflow_run_id: str,
        body: WorkPackageDecompositionRequest,
    ) -> WorkPackageDecompositionResponse:
        _require_path_match(project_id, body.project_id)
        _require_path_match(workflow_run_id, body.workflow_run_id)

        def _execute() -> WorkPackageDecompositionResponse:
            coordinator = config.fresh_coordinator(
                project_id=project_id,
                study_definition_id=body.study_definition_id,
                workflow_run_id=workflow_run_id,
            )
            graph = coordinator.decompose_coordinator_work(
                packages=tuple(
                    WorkPackageSpec(**package.model_dump())
                    for package in body.packages
                )
            )
            return WorkPackageDecompositionResponse(
                project_id=project_id,
                workflow_run_id=workflow_run_id,
                ordered_package_ids=graph.ordered_package_ids(),
                packages=graph.ordered_packages(),
            )

        return _safe_call(_execute)  # type: ignore[return-value]

def create_protocol_workflow_router(
    *,
    application_service: ApplicationService,
    registry_selection: RegistrySelection,
    gate_observer: Optional[Callable[[], Tuple[GateObservation, ...]]] = None,
    clock: Optional[Callable[[], datetime]] = None,
    route_class: Optional[type] = None,
) -> APIRouter:
    """Build the Protocol v3 workflow router.

    The factory remains locally testable. Product mounting is owned only by
    ``composition.mount_protocol_workflow_router`` (Task 1R.2).

    Only the immutable :class:`ApplicationService` and
    :class:`RegistrySelection` (plus the typed observer/clock configuration)
    are retained; every Agent⑤ request constructs a fresh
    :class:`Agent5QueryFacade` + :class:`Agent5Coordinator` so snapshots are
    never stale.

    ``route_class`` (Task 1R.2) optionally overrides the route class for
    every registered route — the actual-main composition passes a
    validation-envelope route so structural 422s stay inside the stable
    Chinese envelope at route scope without touching legacy handlers.
    Omitted, every route keeps the default class and behaviour is unchanged.
    """

    if not isinstance(application_service, ApplicationService):
        raise TypeError("application_service must be an ApplicationService")
    if not isinstance(registry_selection, RegistrySelection):
        raise TypeError("registry_selection must be an approved RegistrySelection")
    if gate_observer is not None and not callable(gate_observer):
        raise TypeError("gate_observer must be callable or None")
    if clock is not None and not callable(clock):
        raise TypeError("clock must be callable or None")
    if route_class is not None and not (
        isinstance(route_class, type) and issubclass(route_class, APIRoute)
    ):
        raise TypeError("route_class must be an APIRoute subclass or None")

    config = _RouterConfig(
        application_service=application_service,
        registry_selection=registry_selection,
        gate_observer=gate_observer,
        clock=clock,
    )
    router = APIRouter(
        prefix="/api/projects/{project_id}/protocol-workflow",
        tags=["方案工作流"],
        route_class=route_class or APIRoute,
    )
    _register_routes(router, config)
    return router
