from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .monitoring_ai_contracts import MonitoringAiCandidateStatus
from .monitoring_rule_template_recommendation_service import (
    MonitoringRuleTemplateRecommendationError,
    MonitoringRuleTemplateRecommendationService,
)
from .monitoring_identity_authorization import (
    MonitoringAction,
    authorize_monitoring_action,
)
from .monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
    MonitoringRuntimePrincipalDenied,
)
from .monitoring_runtime_route_context import (
    MonitoringRuntimeRouteContextError,
    build_monitoring_runtime_route_context,
)


class RuleTemplateRecommendationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_fact_state_version: StrictInt = Field(ge=1)


class RuleTemplateRecommendationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: MonitoringAiCandidateStatus
    expected_input_revision_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_fact_state_version: StrictInt = Field(ge=1)
    actor: str = Field(default="medical_manager", min_length=2, max_length=160)
    reason: str = Field(default="", max_length=2_000)


def create_monitoring_rule_template_recommendation_router(
    *,
    service: MonitoringRuleTemplateRecommendationService,
    project_resolver: Callable[[str], str] = lambda value: value,
    principal_resolver: Callable[[Request], MonitoringAuthenticatedPrincipal | None]
    | None = None,
    require_server_principal: bool = True,
) -> APIRouter:
    router = APIRouter(
        prefix=(
            "/api/projects/{project_id}/modules/medical-monitoring/"
            "rule-template-recommendations"
        ),
        tags=["medical-monitoring-rule-template-recommendations"],
    )

    def authorize_route(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
        action: MonitoringAction,
        require_write: bool,
        legacy_actor: str = "",
    ) -> str:
        """Authorize from the host principal and fail closed by default."""

        if not require_server_principal:
            return str(legacy_actor or "medical_manager").strip() or "medical_manager"
        operation = "写入" if require_write else "读取"
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份尚未接入，规则模板建议{operation}已阻断。",
                },
            )
        try:
            principal = principal_resolver(http_request)
        except Exception as exc:  # host/provider failures fail closed
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份读取失败，规则模板建议{operation}已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器未提供有效验证身份，规则模板建议{operation}已阻断。",
                },
            )
        try:
            route_context = build_monitoring_runtime_route_context(
                principal,
                request_id=request_id,
                route_project_id=project_id,
                tenant_id=principal.tenant_id,
                target_scope="trial",
                action=action,
            )
            decision = authorize_monitoring_action(
                route_context.principal.to_monitoring_principal(
                    now=route_context.validated_at,
                ),
                route_context.request,
            )
        except MonitoringRuntimePrincipalDenied as exc:
            status = (
                401
                if exc.reason_code
                in {
                    "principal_not_authenticated",
                    "principal_not_yet_valid",
                    "principal_expired",
                }
                else 403
            )
            raise HTTPException(
                status_code=status,
                detail={
                    "code": f"monitoring_{exc.reason_code}",
                    "message": f"服务器验证身份不满足规则模板建议{operation}条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": f"规则模板建议路由身份上下文无效，{operation}已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": f"规则模板建议授权请求无效，{operation}已阻断。",
                },
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"monitoring_{decision.reason.value}",
                    "message": f"服务器身份无权{operation}当前规则模板建议流程。",
                },
            )
        if require_write and not decision.write_permitted:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_write_not_permitted",
                    "message": "当前规则模板建议路由未获得写入授权。",
                },
            )
        return principal.server_actor

    @router.post("/facts/{fact_revision_id}/start", status_code=202)
    def start(
        project_id: str,
        fact_revision_id: str,
        http_request: Request,
        request: RuleTemplateRecommendationStartRequest,
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=(
                f"rule-template-recommendations:start:{canonical_id}:"
                f"{fact_revision_id}"
            ),
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
        )
        try:
            return service.start(
                project_id=canonical_id,
                fact_revision_id=fact_revision_id,
                **request.model_dump(),
            )
        except MonitoringRuleTemplateRecommendationError as exc:
            raise _http_error(exc) from exc

    @router.get("/facts/{fact_revision_id}/status")
    def status(
        project_id: str,
        fact_revision_id: str,
        http_request: Request,
        expected_fact_state_version: int,
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=(
                f"rule-template-recommendations:status:{canonical_id}:"
                f"{fact_revision_id}:{expected_fact_state_version}"
            ),
            action=MonitoringAction.READ_MONITORING,
            require_write=False,
        )
        try:
            return service.status(
                project_id=canonical_id,
                fact_revision_id=fact_revision_id,
                expected_fact_state_version=expected_fact_state_version,
            )
        except MonitoringRuleTemplateRecommendationError as exc:
            raise _http_error(exc) from exc

    @router.post("/facts/{fact_revision_id}/candidates/{candidate_id}/decision")
    def decide(
        project_id: str,
        fact_revision_id: str,
        candidate_id: str,
        http_request: Request,
        request: RuleTemplateRecommendationDecisionRequest,
    ):
        canonical_id = project_resolver(project_id)
        actor = authorize_route(
            http_request,
            canonical_id,
            request_id=(
                f"rule-template-recommendations:decision:{canonical_id}:"
                f"{fact_revision_id}:{candidate_id}"
            ),
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
            legacy_actor=request.actor,
        )
        try:
            payload = request.model_dump()
            payload["actor"] = actor
            return service.decide(
                project_id=canonical_id,
                fact_revision_id=fact_revision_id,
                candidate_id=candidate_id,
                **payload,
            )
        except MonitoringRuleTemplateRecommendationError as exc:
            raise _http_error(exc) from exc

    return router


def _http_error(exc: MonitoringRuleTemplateRecommendationError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code, "message": exc.message},
    )
