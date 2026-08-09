from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .monitoring_ai_contracts import MonitoringAiCandidateStatus
from .monitoring_protocol_preparation_service import (
    MonitoringProtocolPreparationError,
    MonitoringProtocolPreparationService,
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


class MonitoringProtocolPreparationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("topic_ids")
    @classmethod
    def validate_topic_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("topic_ids must be non-empty")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("topic_ids must be unique")
        return cleaned


class MonitoringProtocolCandidateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: MonitoringAiCandidateStatus
    actor: str = Field(default="medical_manager", min_length=2, max_length=160)
    reason: str = Field(default="", max_length=2_000)
    expected_input_revision_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_source_revision: str = Field(min_length=2, max_length=160)
    proposed_fact_type: str = Field(default="", max_length=120)
    fact_key: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=500)
    applicability: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_decision(self) -> MonitoringProtocolCandidateDecisionRequest:
        if self.decision not in {
            MonitoringAiCandidateStatus.ACCEPTED,
            MonitoringAiCandidateStatus.REJECTED,
        }:
            raise ValueError("candidate decision must be accepted or rejected")
        if (
            self.decision == MonitoringAiCandidateStatus.REJECTED
            and (
                self.proposed_fact_type.strip()
                or self.fact_key.strip()
                or self.title.strip()
                or self.applicability
            )
        ):
            raise ValueError(
                "rejected candidates must not include fact draft fields"
            )
        return self


def create_monitoring_protocol_preparation_router(
    *,
    service: MonitoringProtocolPreparationService,
    project_resolver: Callable[[str], str] = lambda value: value,
    principal_resolver: Callable[[Request], MonitoringAuthenticatedPrincipal | None]
    | None = None,
    require_server_principal: bool = True,
) -> APIRouter:
    router = APIRouter(
        prefix=(
            "/api/projects/{project_id}/modules/medical-monitoring/"
            "protocol-preparation"
        ),
        tags=["medical-monitoring-protocol-preparation"],
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
        """Authorize the route from a host-verified principal only.

        ``require_server_principal=False`` is deliberately retained only for
        isolated offline router tests.  Production wiring leaves the default
        enabled and never accepts a request actor as identity.
        """

        if not require_server_principal:
            return str(legacy_actor or "medical_manager").strip() or "medical_manager"
        operation = "写入" if require_write else "读取"
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份尚未接入，方案准备{operation}已阻断。",
                },
            )
        try:
            principal = principal_resolver(http_request)
        except Exception as exc:  # host/provider failures fail closed
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份读取失败，方案准备{operation}已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器未提供有效验证身份，方案准备{operation}已阻断。",
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
                    "message": f"服务器验证身份不满足方案准备{operation}条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": f"方案准备路由身份上下文无效，{operation}已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": f"方案准备授权请求无效，{operation}已阻断。",
                },
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"monitoring_{decision.reason.value}",
                    "message": f"服务器身份无权{operation}当前方案准备流程。",
                },
            )
        if require_write and not decision.write_permitted:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_write_not_permitted",
                    "message": "当前方案准备路由未获得写入授权。",
                },
            )
        return principal.server_actor

    @router.post(
        "/protocol-versions/{protocol_version_id}/start",
        status_code=202,
    )
    def start_protocol_preparation(
        project_id: str,
        protocol_version_id: str,
        http_request: Request,
        request: Optional[MonitoringProtocolPreparationStartRequest] = None,  # noqa: UP045
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=(
                f"protocol-preparation:start:{canonical_id}:"
                f"{protocol_version_id}"
            ),
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
        )
        try:
            return service.start(
                project_id=canonical_id,
                protocol_version_id=protocol_version_id,
                topic_ids=tuple(request.topic_ids) if request is not None else (),
            )
        except MonitoringProtocolPreparationError as exc:
            raise _http_error(exc) from exc

    @router.get("/protocol-versions/{protocol_version_id}/status")
    def protocol_preparation_status(
        project_id: str,
        protocol_version_id: str,
        http_request: Request,
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=(
                f"protocol-preparation:status:{canonical_id}:"
                f"{protocol_version_id}"
            ),
            action=MonitoringAction.READ_MONITORING,
            require_write=False,
        )
        try:
            return service.status(
                project_id=canonical_id,
                protocol_version_id=protocol_version_id,
            )
        except MonitoringProtocolPreparationError as exc:
            raise _http_error(exc) from exc

    @router.post(
        "/protocol-versions/{protocol_version_id}/candidates/"
        "{candidate_id}/decision"
    )
    def decide_protocol_candidate(
        project_id: str,
        protocol_version_id: str,
        candidate_id: str,
        http_request: Request,
        request: MonitoringProtocolCandidateDecisionRequest,
    ):
        canonical_id = project_resolver(project_id)
        actor = authorize_route(
            http_request,
            canonical_id,
            request_id=(
                f"protocol-preparation:decision:{canonical_id}:"
                f"{protocol_version_id}:{candidate_id}"
            ),
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
            legacy_actor=request.actor,
        )
        try:
            payload = request.model_dump()
            payload["actor"] = actor
            return service.decide_candidate(
                project_id=canonical_id,
                protocol_version_id=protocol_version_id,
                candidate_id=candidate_id,
                **payload,
            )
        except MonitoringProtocolPreparationError as exc:
            raise _http_error(exc) from exc

    return router


def _http_error(exc: MonitoringProtocolPreparationError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={"code": exc.code, "message": exc.message},
    )
