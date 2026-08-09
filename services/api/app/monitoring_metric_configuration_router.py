from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException, Query, Request

from .monitoring_identity_authorization import (
    MonitoringAction,
    authorize_monitoring_action,
)
from .monitoring_metric_configuration_service import (
    MonitoringMetricConfigurationError,
    MonitoringMetricConfigurationService,
    metric_configuration_public_payload,
)
from .monitoring_runtime_principal import (
    MonitoringAuthenticatedPrincipal,
    MonitoringRuntimePrincipalDenied,
)
from .monitoring_runtime_route_context import (
    MonitoringRuntimeRouteContextError,
    build_monitoring_runtime_route_context,
)


def create_monitoring_metric_configuration_router(
    *,
    service: MonitoringMetricConfigurationService,
    project_resolver: Callable[[str], str] = lambda value: value,
    principal_resolver: Callable[[Request], MonitoringAuthenticatedPrincipal | None]
    | None = None,
    require_server_principal: bool = True,
) -> APIRouter:
    """Create the read-only metric-candidate review route."""

    router = APIRouter(
        prefix=(
            "/api/projects/{project_id}/modules/medical-monitoring/"
            "metric-configuration"
        ),
        tags=["medical-monitoring-metric-configuration"],
    )

    def authorize_read(request: Request, project_id: str, protocol_version_id: str, batch_id: str) -> None:
        """Require a host-verified principal before exposing source-bound metrics."""

        if not require_server_principal:
            return
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器验证身份尚未接入，指标候选读取已阻断。",
                },
            )
        try:
            principal = principal_resolver(request)
        except Exception as exc:  # host/provider failures fail closed
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器验证身份读取失败，指标候选读取已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器未提供有效验证身份，指标候选读取已阻断。",
                },
            )
        try:
            route_context = build_monitoring_runtime_route_context(
                principal,
                request_id=(
                    "monitoring-metric-configuration-read:"
                    f"{project_id}:{protocol_version_id}:{batch_id}"
                ),
                route_project_id=project_id,
                tenant_id=principal.tenant_id,
                target_scope="trial",
                action=MonitoringAction.READ_MONITORING,
            )
            decision = authorize_monitoring_action(
                route_context.principal.to_monitoring_principal(
                    now=route_context.validated_at,
                ),
                route_context.request,
            )
        except MonitoringRuntimePrincipalDenied as exc:
            status = 401 if exc.reason_code in {
                "principal_not_authenticated",
                "principal_not_yet_valid",
                "principal_expired",
            } else 403
            raise HTTPException(
                status_code=status,
                detail={
                    "code": f"monitoring_{exc.reason_code}",
                    "message": "服务器验证身份不满足指标候选读取条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": "指标候选路由身份上下文无效，读取已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": "指标候选授权请求无效，读取已阻断。",
                },
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"monitoring_{decision.reason.value}",
                    "message": "服务器身份无权读取当前指标候选。",
                },
            )

    @router.get("/protocol-versions/{protocol_version_id}/candidates")
    def get_metric_configuration_candidates(
        request: Request,
        project_id: str,
        protocol_version_id: str,
        batch_id: str = Query(..., min_length=2, max_length=220),
    ):
        canonical_id = project_resolver(project_id)
        authorize_read(request, canonical_id, protocol_version_id, batch_id)
        try:
            bundle = service.build(
                project_id=canonical_id,
                protocol_version_id=protocol_version_id,
                batch_id=batch_id,
            )
        except MonitoringMetricConfigurationError as exc:
            raise HTTPException(
                status_code=exc.http_status,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
        return metric_configuration_public_payload(bundle)

    return router


__all__ = ["create_monitoring_metric_configuration_router"]
