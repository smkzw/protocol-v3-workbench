from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .medical_monitoring_summary import (
    DeepLinkValidationError,
    MedicalMonitoringRunService,
    MedicalMonitoringSummaryService,
    MonitoringEvidenceTab,
    MonitoringScope,
    MonitoringView,
    RiskChecklistSortField,
    RiskSnapshotQueryError,
    SortDirection,
)
from .medical_monitoring_risk_taxonomy import risk_taxonomy_payload
from .monitoring_protocol_rule_repository import (
    MonitoringProtocolRecordNotFound,
    ProtocolApplicabilityConflictError,
)
from .monitoring_batch_repository import (
    MonitoringBatchRepositoryError,
    RecordNotFoundError,
)
from .monitoring_rule_authoring_service import (
    MonitoringRuleAuthoringError,
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
from .monitoring_source_readiness import (
    resolve_monitoring_source_readiness,
    source_readiness_block_detail,
)

_RISK_SNAPSHOT_FILTER_FIELDS = {
    "snapshot_id",
    "site_id",
    "subject_id",
    "risk_key",
    "risk_instance_id",
    "category",
    "risk_category_code",
    "risk_item",
    "severity",
    "disposition_status",
    "updated_at",
    "status",
    "batch_delta",
    "include_terminal",
    "sort_by",
    "sort_direction",
}


class _AuthoringRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProtocolVersionAuthoringRequest(_AuthoringRequest):
    source_entry_id: str = Field(min_length=2, max_length=200)
    protocol_code: str = Field(min_length=1, max_length=160)
    version_label: str = Field(min_length=1, max_length=80)
    version_date: str = Field(min_length=10, max_length=10)
    applicability_status: str = Field(
        default="version_date_only",
        max_length=80,
    )
    operational_effective_from: str = Field(default="", max_length=10)
    operational_effective_to: str = Field(default="", max_length=10)
    predecessor_version_id: str = Field(default="", max_length=200)
    amendment_source_entry_id: str = Field(default="", max_length=200)


class ProtocolApplicabilityAssignmentRequest(_AuthoringRequest):
    protocol_version_id: str = Field(min_length=2, max_length=200)
    centre_id: str = Field(min_length=1, max_length=160)
    subject_id: str = Field(default="", max_length=160)
    operational_effective_from: str = Field(min_length=10, max_length=10)
    operational_effective_to: str = Field(min_length=10, max_length=10)
    evidence_text: str = Field(min_length=1, max_length=20_000)
    evidence_source_entry_id: str = Field(min_length=1, max_length=200)
    evidence_locator: str = Field(min_length=1, max_length=1_000)
    created_by: str = Field(
        default="medical_manager",
        min_length=2,
        max_length=160,
    )


class ApplicabilityConfirmationRequest(_AuthoringRequest):
    expected_state_version: StrictInt = Field(ge=1)
    confirmed_by: str = Field(
        default="medical_manager",
        min_length=2,
        max_length=160,
    )


class ApplicabilityRetirementRequest(_AuthoringRequest):
    expected_state_version: StrictInt = Field(ge=1)
    retired_by: str = Field(
        default="medical_manager",
        min_length=2,
        max_length=160,
    )


class AiCandidateAdoptionRequest(_AuthoringRequest):
    protocol_version_id: str = Field(min_length=2, max_length=200)
    candidate_id: str = Field(min_length=2, max_length=160)
    fact_key: str = Field(min_length=2, max_length=160)
    proposed_fact_type: str = Field(min_length=2, max_length=120)
    title: str = Field(default="", max_length=500)
    applicability: dict[str, Any] = Field(default_factory=dict)


class ProtocolFactConfirmationRequest(_AuthoringRequest):
    expected_state_version: StrictInt = Field(ge=1)
    fact_type: str = Field(min_length=2, max_length=120)
    deterministic_template: dict[str, Any]
    confirmed_by: str = Field(default="medical_manager", min_length=2, max_length=160)
    title: str = Field(default="", max_length=500)
    applicability: dict[str, Any] = Field(default_factory=dict)
    reauthenticated: StrictBool = False
    signature_evidence_sha256: str = Field(default="", max_length=64)


class RulePackDraftRequest(_AuthoringRequest):
    protocol_version_id: str = Field(min_length=2, max_length=200)
    fact_revision_ids: list[str] = Field(min_length=1, max_length=200)
    created_by: str = Field(default="medical_manager", min_length=2, max_length=160)
    retrospective_policy: str = Field(
        default="open_risks_only",
        max_length=80,
    )
    expected_pack_revision: Optional[StrictInt] = Field(default=None, ge=1)


class RuleConfirmationRequest(_AuthoringRequest):
    expected_state_version: StrictInt = Field(ge=1)
    confirmed_by: str = Field(default="medical_manager", min_length=2, max_length=160)
    reauthenticated: StrictBool = False
    signature_evidence_sha256: str = Field(default="", max_length=64)


class RulePackActorRequest(_AuthoringRequest):
    actor: str = Field(default="medical_manager", min_length=2, max_length=160)
    expected_pack_revision: Optional[StrictInt] = Field(default=None, ge=1)
    reauthenticated: StrictBool = False
    signature_evidence_sha256: str = Field(default="", max_length=64)


class AutomaticShadowRunRequest(_AuthoringRequest):
    batch_id: str = Field(min_length=2, max_length=200)
    actor: str = Field(default="medical_manager", min_length=2, max_length=160)
    expected_pack_revision: Optional[StrictInt] = Field(default=None, ge=1)


class ShadowRunRequest(_AuthoringRequest):
    batch_id: str = Field(min_length=2, max_length=200)


class ShadowConfirmationRequest(_AuthoringRequest):
    shadow_run_id: Optional[str] = Field(
        default=None, min_length=2, max_length=200
    )
    sample_set_id: Optional[str] = Field(
        default=None, min_length=2, max_length=200
    )
    confirmed_by: str = Field(default="medical_manager", min_length=2, max_length=160)
    expected_pack_revision: Optional[StrictInt] = Field(default=None, ge=1)
    reauthenticated: StrictBool = False
    signature_evidence_sha256: str = Field(default="", max_length=64)


def _coalesce_deep_link_alias(
    field: str,
    canonical_value: Any,
    alias_value: Any,
    default: Any,
) -> Any:
    if (
        canonical_value is not None
        and alias_value is not None
        and canonical_value != alias_value
    ):
        raise DeepLinkValidationError(
            f"conflicting_{field}",
            f"{field} 的规范字段与兼容字段值不一致。",
        )
    if canonical_value is not None:
        return canonical_value
    if alias_value is not None:
        return alias_value
    return default


def create_medical_monitoring_router(
    *,
    risk_repository: Any,
    batch_repository: Any = None,
    batch_service: Any = None,
    project_source_manifest_service: Any = None,
    workbench_inbox_service: Any = None,
    monitoring_registry: Any = None,
    protocol_rule_service: Any = None,
    protocol_rule_authoring_service: Any = None,
    protocol_rule_shadow_sample_service: Any = None,
    principal_resolver: Callable[[Request], MonitoringAuthenticatedPrincipal | None]
    | None = None,
    require_server_principal: bool = True,
) -> APIRouter:
    """Create a mountable monitoring router with explicitly injected readers."""

    service = MedicalMonitoringSummaryService(
        risk_repository=risk_repository,
        project_source_manifest_service=project_source_manifest_service,
        workbench_inbox_service=workbench_inbox_service,
        monitoring_registry=monitoring_registry,
    )
    run_service = MedicalMonitoringRunService(
        risk_repository=risk_repository,
        project_source_manifest_service=project_source_manifest_service,
        monitoring_registry=monitoring_registry,
    )
    router = APIRouter(
        prefix="/api/projects/{project_id}/modules/medical-monitoring",
        tags=["medical-monitoring"],
    )

    def ensure_monitoring_source_ready(
        project_id: str,
        *,
        operation: str,
    ) -> None:
        """Keep registered-but-unactivated projects out of module routes."""

        if project_source_manifest_service is None:
            return
        try:
            canonical_id = project_source_manifest_service.canonical_project_id(
                project_id
            )
            binding = project_source_manifest_service.module_binding(
                canonical_id,
                "medical_monitoring",
            )
        except KeyError:
            # The module's existing registry/not-configured handling remains
            # authoritative when no manifest binding exists.
            return
        readiness = resolve_monitoring_source_readiness(binding)
        if readiness is None or readiness.can_read:
            return
        raise HTTPException(
            status_code=409,
            detail=source_readiness_block_detail(
                canonical_id,
                readiness,
                operation=operation,
            ),
        )

    def authorize_read(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
        legacy_actor: str = "",
        action: MonitoringAction = MonitoringAction.READ_MONITORING,
    ) -> str:
        """Authorize primary monitoring reads from a host-verified principal."""

        if not require_server_principal:
            ensure_monitoring_source_ready(
                project_id,
                operation="read",
            )
            return str(legacy_actor or "medical_manager").strip() or "medical_manager"
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器验证身份尚未接入，医学监查读取已阻断。",
                },
            )
        try:
            principal = principal_resolver(http_request)
        except Exception as exc:  # host/provider failures fail closed
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器验证身份读取失败，医学监查读取已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器未提供有效验证身份，医学监查读取已阻断。",
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
                    "message": "服务器验证身份不满足医学监查读取条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": "医学监查路由身份上下文无效，读取已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": "医学监查授权请求无效，读取已阻断。",
                },
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"monitoring_{decision.reason.value}",
                    "message": "服务器身份无权读取当前医学监查数据。",
                },
            )
        ensure_monitoring_source_ready(
            project_id,
            operation="read",
        )
        return principal.server_actor

    def authorize_write(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
        action: MonitoringAction,
        legacy_actor: str = "",
        reauthenticated: bool = False,
        signature_evidence_sha256: str = "",
    ) -> str:
        """Authorize a monitoring command before any snapshot computation/write."""

        if not require_server_principal:
            ensure_monitoring_source_ready(
                project_id,
                operation="write",
            )
            return str(legacy_actor or "medical_manager").strip() or "medical_manager"
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器验证身份尚未接入，医学监查写入已阻断。",
                },
            )
        try:
            principal = principal_resolver(http_request)
        except Exception as exc:  # host/provider failures fail closed
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器验证身份读取失败，医学监查写入已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": "服务器未提供有效验证身份，医学监查写入已阻断。",
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
                reauthenticated=reauthenticated,
                signature_evidence_sha256=signature_evidence_sha256,
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
                    "message": "服务器验证身份不满足医学监查写入条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": "医学监查路由身份上下文无效，写入已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": "医学监查授权请求无效，写入已阻断。",
                },
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"monitoring_{decision.reason.value}",
                    "message": "服务器身份无权执行当前医学监查写入。",
                },
            )
        if not decision.write_permitted:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_write_not_permitted",
                    "message": "当前医学监查路由未获得写入授权。",
                },
            )
        ensure_monitoring_source_ready(
            project_id,
            operation="write",
        )
        return principal.server_actor

    def reject_unconfigured_write(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
    ) -> None:
        """Fail closed where the action matrix has no exact write permission."""

        if not require_server_principal:
            ensure_monitoring_source_ready(
                project_id,
                operation="write",
            )
            return
        # Validate the server principal and project/read scope first, but do
        # not reuse a read decision as write authority. The explicit 403 keeps
        # the policy gap visible until a named action is approved.
        authorize_read(
            http_request,
            project_id,
            request_id=request_id,
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "monitoring_write_action_unconfigured",
                "message": "当前协议/规则写入动作尚未配置显式权限，写入已阻断。",
            },
        )

    @router.get("/summary")
    def get_module_summary(
        project_id: str,
        http_request: Request,
        actor: str = Query("medical_manager", min_length=2, max_length=80),
    ):
        try:
            canonical_id = service.canonical_project_id(project_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_found",
                    "message": f"未找到项目：{project_id}",
                },
            ) from exc
        server_actor = authorize_read(
            http_request,
            canonical_id,
            request_id=f"monitoring-summary-read:{canonical_id}",
            legacy_actor=actor,
        )
        try:
            return service.module_summary(canonical_id, actor=server_actor)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_found",
                    "message": f"未找到项目：{project_id}",
                },
            ) from exc

    @router.get("/deep-link")
    def validate_deep_link(
        project_id: str,
        request: Request,
        scope: MonitoringScope = Query(MonitoringScope.TRIAL),
        view: MonitoringView = Query(MonitoringView.CHECKLIST),
        site_id: str = Query("", max_length=120),
        subject_id: str = Query("", max_length=120),
        risk_key: str = Query("", max_length=200),
        risk_instance_id: str = Query("", max_length=200),
        batch_id: str = Query("", max_length=200),
        evidence_tab: Optional[MonitoringEvidenceTab] = Query(None),
        filter_subject_id: str = Query("", max_length=120),
        filter_site_id: str = Query("", max_length=120),
        filter_severity: str = Query("", max_length=40),
        filter_risk_category_code: str = Query("", max_length=120),
        filter_risk_item: str = Query("", max_length=500),
        filter_disposition_status: str = Query("", max_length=80),
        filter_updated_at: str = Query("", max_length=40),
        risk_sort_by: Optional[RiskChecklistSortField] = Query(None),
        risk_sort_direction: Optional[SortDirection] = Query(None),
        risk_page: Optional[int] = Query(None, ge=1),
        risk_page_size: Optional[int] = Query(None, ge=1, le=200),
        sort_by: Optional[RiskChecklistSortField] = Query(None),
        sort_direction: Optional[SortDirection] = Query(None),
        page: Optional[int] = Query(None, ge=1),
        page_size: Optional[int] = Query(None, ge=1, le=200),
        risk_snapshot_id: str = Query("", max_length=200),
    ):
        allowed_query_fields = {
            "project_id",
            "scope",
            "view",
            "site_id",
            "subject_id",
            "risk_key",
            "risk_instance_id",
            "batch_id",
            "evidence_tab",
            "filter_subject_id",
            "filter_site_id",
            "filter_severity",
            "filter_risk_category_code",
            "filter_risk_item",
            "filter_disposition_status",
            "filter_updated_at",
            "risk_sort_by",
            "risk_sort_direction",
            "risk_page",
            "risk_page_size",
            "sort_by",
            "sort_direction",
            "page",
            "page_size",
            "risk_snapshot_id",
        }
        unknown_fields = sorted(
            set(request.query_params.keys()) - allowed_query_fields
        )
        if unknown_fields:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unknown_medical_monitoring_deep_link_field",
                    "message": "存在不支持的医学监查深链字段。",
                    "fields": unknown_fields,
                },
            )
        try:
            canonical_id = service.canonical_project_id(project_id)
            authorize_read(
                request,
                canonical_id,
                request_id=f"monitoring-deep-link-read:{canonical_id}",
            )
            query_project_id = str(
                request.query_params.get("project_id") or ""
            ).strip()
            if query_project_id:
                query_canonical_id = service.canonical_project_id(query_project_id)
                if query_canonical_id != canonical_id:
                    raise DeepLinkValidationError(
                        "medical_monitoring_deep_link_project_conflict",
                        "路径项目与深链 project_id 不一致。",
                    )
            resolved_sort_by = _coalesce_deep_link_alias(
                "sort_by",
                risk_sort_by,
                sort_by,
                RiskChecklistSortField.UPDATED_AT,
            )
            resolved_sort_direction = _coalesce_deep_link_alias(
                "sort_direction",
                risk_sort_direction,
                sort_direction,
                SortDirection.DESC,
            )
            resolved_page = _coalesce_deep_link_alias(
                "page",
                risk_page,
                page,
                1,
            )
            resolved_page_size = _coalesce_deep_link_alias(
                "page_size",
                risk_page_size,
                page_size,
                50,
            )
            return service.validate_deep_link(
                project_id=canonical_id,
                scope=scope,
                view=view,
                site_id=site_id,
                subject_id=subject_id,
                risk_key=risk_key,
                risk_instance_id=risk_instance_id,
                batch_id=batch_id,
                evidence_tab=evidence_tab,
                filter_subject_id=filter_subject_id,
                filter_site_id=filter_site_id,
                filter_severity=filter_severity,
                filter_risk_category_code=filter_risk_category_code,
                filter_risk_item=filter_risk_item,
                filter_disposition_status=filter_disposition_status,
                filter_updated_at=filter_updated_at,
                risk_sort_by=resolved_sort_by,
                risk_sort_direction=resolved_sort_direction,
                risk_page=resolved_page,
                risk_page_size=resolved_page_size,
                risk_snapshot_id=risk_snapshot_id,
            ).as_dict()
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_found",
                    "message": f"未找到项目：{project_id}",
                },
            ) from exc
        except DeepLinkValidationError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.get("/risk-snapshots/current")
    def get_current_risk_snapshot(
        project_id: str,
        request: Request,
        snapshot_id: str = Query("", max_length=200),
        site_id: str = Query("", max_length=120),
        subject_id: str = Query("", max_length=120),
        risk_key: str = Query("", max_length=200),
        risk_instance_id: str = Query("", max_length=200),
        category: str = Query("", max_length=120),
        risk_category_code: str = Query("", max_length=120),
        risk_item: str = Query("", max_length=500),
        severity: str = Query("", max_length=40),
        disposition_status: str = Query("", max_length=80),
        updated_at: str = Query("", max_length=40),
        status: str = Query("", max_length=40),
        batch_delta: str = Query("", max_length=80),
        include_terminal: bool = Query(False),
        sort_by: RiskChecklistSortField = Query(
            RiskChecklistSortField.UPDATED_AT
        ),
        sort_direction: SortDirection = Query(SortDirection.DESC),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ):
        allowed_query_fields = {
            *_RISK_SNAPSHOT_FILTER_FIELDS,
            "page",
            "page_size",
        }
        unknown_fields = sorted(
            set(request.query_params.keys()) - allowed_query_fields
        )
        if unknown_fields:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unknown_risk_snapshot_query_field",
                    "message": "存在不支持的风险快照查询字段。",
                    "fields": unknown_fields,
                },
            )
        try:
            canonical_id = service.canonical_project_id(project_id)
            authorize_read(
                request,
                canonical_id,
                request_id=f"monitoring-risk-snapshot-read:{canonical_id}",
            )
            return service.current_risk_snapshot(
                canonical_id,
                snapshot_id=snapshot_id.strip(),
                site_id=site_id.strip(),
                subject_id=subject_id.strip(),
                risk_key=risk_key.strip(),
                risk_instance_id=risk_instance_id.strip(),
                category=category.strip(),
                risk_category_code=risk_category_code.strip(),
                risk_item=risk_item.strip(),
                severity=severity.strip(),
                disposition_status=disposition_status.strip(),
                updated_at=updated_at.strip(),
                status=status.strip(),
                batch_delta=batch_delta.strip(),
                include_terminal=include_terminal,
                sort_by=sort_by,
                sort_direction=sort_direction,
                page=page,
                page_size=page_size,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_found",
                    "message": f"未找到项目：{project_id}",
                },
            ) from exc
        except RiskSnapshotQueryError as exc:
            raise HTTPException(
                status_code=(
                    409
                    if exc.code == "medical_monitoring_snapshot_not_found"
                    else 422
                ),
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.get("/batch-diff")
    def get_canonical_batch_diff(
        project_id: str,
        request: Request,
        previous_batch_id: str = Query(..., min_length=2, max_length=200),
        current_batch_id: str = Query(..., min_length=2, max_length=200),
        offset: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=1000),
    ):
        """Read an immutable batch diff through the canonical module contract.

        The legacy `/monitoring/batch-diff` endpoint remains separate for
        compatibility.  This route deliberately requires the injected batch
        repository/service and the server-verified source-evidence action;
        it never accepts a client actor and never mutates a batch or risk.
        """

        try:
            canonical_id = service.canonical_project_id(project_id)
            authorize_read(
                request,
                canonical_id,
                request_id=(
                    f"monitoring-canonical-batch-diff-read:{canonical_id}:"
                    f"{previous_batch_id}:{current_batch_id}"
                ),
                action=MonitoringAction.READ_SOURCE_EVIDENCE,
            )
            if batch_repository is None or batch_service is None:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "monitoring_batch_diff_unavailable",
                        "message": "批次差异服务尚未接入 canonical 医学监查模块。",
                    },
                )
            previous = batch_repository.get_batch(previous_batch_id)
            current = batch_repository.get_batch(current_batch_id)
            if (
                previous.project_id != canonical_id
                or current.project_id != canonical_id
            ):
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "monitoring_batch_diff_not_found",
                        "message": "当前项目未找到所请求的批次差异。",
                    },
                )
            result = dict(
                batch_service.detailed_diff(
                    previous_batch_id,
                    current_batch_id,
                )
            )
            field_changes = list(result.get("field_changes") or ())
            result.update(
                {
                    "project_id": canonical_id,
                    "field_change_total": len(field_changes),
                    "field_changes": field_changes[offset : offset + limit],
                    "offset": offset,
                    "limit": limit,
                }
            )
            return result
        except HTTPException:
            raise
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "monitoring_batch_diff_not_found",
                    "message": "当前项目未找到所请求的批次差异。",
                },
            ) from exc
        except RecordNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "monitoring_batch_diff_not_found",
                    "message": "当前项目未找到所请求的批次差异。",
                },
            ) from exc
        except MonitoringBatchRepositoryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/risk-snapshots/current/export")
    def export_current_risk_snapshot(
        project_id: str,
        request: Request,
        snapshot_id: str = Query("", max_length=200),
        site_id: str = Query("", max_length=120),
        subject_id: str = Query("", max_length=120),
        risk_key: str = Query("", max_length=200),
        risk_instance_id: str = Query("", max_length=200),
        category: str = Query("", max_length=120),
        risk_category_code: str = Query("", max_length=120),
        risk_item: str = Query("", max_length=500),
        severity: str = Query("", max_length=40),
        disposition_status: str = Query("", max_length=80),
        updated_at: str = Query("", max_length=40),
        status: str = Query("", max_length=40),
        batch_delta: str = Query("", max_length=80),
        include_terminal: bool = Query(False),
        sort_by: RiskChecklistSortField = Query(
            RiskChecklistSortField.UPDATED_AT
        ),
        sort_direction: SortDirection = Query(SortDirection.DESC),
    ):
        unknown_fields = sorted(
            set(request.query_params.keys()) - _RISK_SNAPSHOT_FILTER_FIELDS
        )
        if unknown_fields:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "unknown_risk_export_query_field",
                    "message": "存在不支持的风险导出查询字段。",
                    "fields": unknown_fields,
                },
            )
        try:
            canonical_id = service.canonical_project_id(project_id)
            authorize_read(
                request,
                canonical_id,
                request_id=f"monitoring-risk-export-read:{canonical_id}",
            )
            result = service.current_risk_export(
                canonical_id,
                snapshot_id=snapshot_id.strip(),
                site_id=site_id.strip(),
                subject_id=subject_id.strip(),
                risk_key=risk_key.strip(),
                risk_instance_id=risk_instance_id.strip(),
                category=category.strip(),
                risk_category_code=risk_category_code.strip(),
                risk_item=risk_item.strip(),
                severity=severity.strip(),
                disposition_status=disposition_status.strip(),
                updated_at=updated_at.strip(),
                status=status.strip(),
                batch_delta=batch_delta.strip(),
                include_terminal=include_terminal,
                sort_by=sort_by,
                sort_direction=sort_direction,
            )
            return Response(
                content=result["content"],
                media_type=result["media_type"],
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{result["filename"]}"'
                    ),
                    "X-Medical-Monitoring-Export-Contract": result[
                        "contract_version"
                    ],
                    "X-Risk-Export-Count": str(result["total"]),
                },
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_found",
                    "message": f"未找到项目：{project_id}",
                },
            ) from exc
        except RiskSnapshotQueryError as exc:
            raise HTTPException(
                status_code=(
                    409
                    if exc.code == "medical_monitoring_snapshot_not_found"
                    else 422
                ),
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    @router.get("/risk-taxonomy")
    def get_risk_taxonomy(project_id: str, http_request: Request):
        try:
            canonical_id = service.canonical_project_id(project_id)
            authorize_read(
                http_request,
                canonical_id,
                request_id=f"monitoring-risk-taxonomy-read:{canonical_id}",
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_found",
                    "message": f"未找到项目：{project_id}",
                },
            ) from exc
        return {
            "project_id": canonical_id,
            **risk_taxonomy_payload(),
        }

    @router.post("/runs", status_code=201)
    def run_monitoring(
        project_id: str,
        response: Response,
        http_request: Request,
    ):
        authorize_write(
            http_request,
            project_id,
            request_id=f"monitoring-run-write:{project_id}",
            action=MonitoringAction.RUN_DETERMINISTIC_RULES,
        )
        try:
            result = run_service.run(project_id)
            if result["status"] == "current_snapshot_reused":
                response.status_code = 200
                result["http_semantics"] = "idempotent_reuse"
            return result
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_registered",
                    "message": f"项目尚未登记医学监查来源：{project_id}",
                },
            ) from exc

    @router.get("/protocol-versions")
    def list_protocol_versions(project_id: str, http_request: Request):
        authorize_read(
            http_request,
            project_id,
            request_id=f"monitoring-protocol-versions-read:{project_id}",
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        return {
            "project_id": project_id,
            "items": [
                item.public_dict()
                for item in rule_service.repository.list_protocol_versions(project_id)
            ],
        }

    @router.get("/protocol-versions/{protocol_version_id}/facts")
    def list_protocol_facts(
        project_id: str,
        protocol_version_id: str,
        http_request: Request,
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-facts-read:{project_id}:"
                f"{protocol_version_id}"
            ),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        try:
            version = rule_service.repository.protocol_version(
                protocol_version_id
            )
        except MonitoringProtocolRecordNotFound as exc:
            raise _monitoring_protocol_not_found(
                "monitoring_protocol_version_not_found",
                "当前项目未找到该方案版本。",
            ) from exc
        if version.project_id != project_id:
            raise _monitoring_protocol_not_found(
                "monitoring_protocol_version_not_found",
                "当前项目未找到该方案版本。",
            )
        return {
            "project_id": project_id,
            "protocol_version": version.public_dict(),
            "items": [
                _public_protocol_fact(item)
                for item in rule_service.repository.facts_for_version(
                    protocol_version_id
                )
            ],
        }

    @router.post("/protocol-versions", status_code=201)
    def register_protocol_version(
        project_id: str,
        request: ProtocolVersionAuthoringRequest,
        response: Response,
        http_request: Request,
    ):
        reject_unconfigured_write(
            http_request,
            project_id,
            request_id=f"monitoring-protocol-version-register:{project_id}",
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            version, reused = authoring.register_protocol_version(
                project_id=project_id,
                **request.model_dump(),
            )
            if reused:
                response.status_code = 200
            return {
                "project_id": project_id,
                "protocol_version": version.public_dict(),
                "state": _medical_state("protocol_confirmed"),
                "reused": reused,
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.get("/protocol-applicability-assignments")
    def list_protocol_applicability_assignments(
        project_id: str,
        http_request: Request,
        protocol_version_id: str = Query("", max_length=200),
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-applicability-list-read:{project_id}"
            ),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        return {
            "project_id": project_id,
            "items": [
                item.public_dict()
                for item in rule_service.repository.list_applicability_assignments(
                    project_id,
                    protocol_version_id=protocol_version_id,
                )
            ],
        }

    @router.get("/protocol-applicability-assignments/resolve")
    def resolve_protocol_applicability(
        project_id: str,
        http_request: Request,
        centre_id: str = Query(..., min_length=1, max_length=160),
        event_date: str = Query(..., min_length=1, max_length=40),
        subject_id: str = Query("", max_length=160),
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-applicability-resolve-read:{project_id}"
            ),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        resolution = rule_service.repository.resolve_protocol_applicability(
            project_id,
            centre_id=centre_id,
            subject_id=subject_id,
            event_date=event_date,
        )
        payload = resolution.public_dict()
        if not resolution.resolved:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": resolution.diagnostic_code,
                    "message": resolution.diagnostic_message,
                    "resolution": payload,
                },
            )
        return payload

    @router.post("/protocol-applicability-assignments", status_code=201)
    def create_protocol_applicability_assignment(
        project_id: str,
        request: ProtocolApplicabilityAssignmentRequest,
        response: Response,
        http_request: Request,
    ):
        reject_unconfigured_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-applicability-create:{project_id}"
            ),
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            assignment, reused = authoring.create_applicability_assignment(
                project_id=project_id,
                **request.model_dump(),
            )
            if reused:
                response.status_code = 200
            return {
                "project_id": project_id,
                "assignment": assignment.public_dict(),
                "state": _medical_state("applicability_candidate"),
                "reused": reused,
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post(
        "/protocol-applicability-assignments/{assignment_id}/confirm"
    )
    def confirm_protocol_applicability_assignment(
        project_id: str,
        assignment_id: str,
        request: ApplicabilityConfirmationRequest,
        http_request: Request,
    ):
        reject_unconfigured_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-applicability-confirm:{project_id}:"
                f"{assignment_id}"
            ),
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            assignment = authoring.confirm_applicability_assignment(
                project_id=project_id,
                assignment_id=assignment_id,
                **request.model_dump(),
            )
            return {
                "project_id": project_id,
                "assignment": assignment.public_dict(),
                "state": _medical_state("applicability_confirmed"),
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post(
        "/protocol-applicability-assignments/{assignment_id}/retire"
    )
    def retire_protocol_applicability_assignment(
        project_id: str,
        assignment_id: str,
        request: ApplicabilityRetirementRequest,
        http_request: Request,
    ):
        reject_unconfigured_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-applicability-retire:{project_id}:"
                f"{assignment_id}"
            ),
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            assignment = authoring.retire_applicability_assignment(
                project_id=project_id,
                assignment_id=assignment_id,
                **request.model_dump(),
            )
            return {
                "project_id": project_id,
                "assignment": assignment.public_dict(),
                "state": _medical_state("applicability_retired"),
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post(
        "/protocol-facts/from-ai-candidate",
        status_code=201,
    )
    def adopt_protocol_ai_candidate(
        project_id: str,
        request: AiCandidateAdoptionRequest,
        response: Response,
        http_request: Request,
    ):
        authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-ai-candidate-adopt:{project_id}:"
                f"{request.candidate_id}"
            ),
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            fact, reused = authoring.adopt_ai_candidate(
                project_id=project_id,
                **request.model_dump(),
            )
            if reused:
                response.status_code = 200
            return {
                "project_id": project_id,
                "fact": _public_protocol_fact(fact),
                "state": _medical_state("ai_candidate_adopted"),
                "reused": reused,
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post(
        "/protocol-facts/{fact_revision_id}/confirm",
        status_code=200,
    )
    def confirm_protocol_fact(
        project_id: str,
        fact_revision_id: str,
        request: ProtocolFactConfirmationRequest,
        http_request: Request,
    ):
        actor = authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-protocol-fact-confirm:{project_id}:"
                f"{fact_revision_id}"
            ),
            action=MonitoringAction.APPROVE_RULE_CHANGE,
            legacy_actor=request.confirmed_by,
            reauthenticated=request.reauthenticated,
            signature_evidence_sha256=request.signature_evidence_sha256,
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            fact, rule = authoring.confirm_fact_and_compile(
                project_id=project_id,
                fact_revision_id=fact_revision_id,
                **request.model_dump(
                    exclude={"reauthenticated", "signature_evidence_sha256", "confirmed_by"}
                ),
                confirmed_by=actor,
            )
            return {
                "project_id": project_id,
                "fact": _public_protocol_fact(fact),
                "compiled_rule": rule.public_dict(),
                "state": _medical_state("fact_confirmed"),
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post("/rule-packs/drafts", status_code=201)
    def create_rule_pack_draft(
        project_id: str,
        request: RulePackDraftRequest,
        response: Response,
        http_request: Request,
    ):
        reject_unconfigured_write(
            http_request,
            project_id,
            request_id=f"monitoring-rule-pack-draft-create:{project_id}",
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            latest_before = authoring.repository.latest_rule_pack(project_id)
            pack = authoring.create_draft(
                project_id=project_id,
                **request.model_dump(),
            )
            reused = (
                latest_before is not None
                and latest_before.rule_pack_id == pack.rule_pack_id
            )
            if reused:
                response.status_code = 200
            _, rules = authoring.repository.rule_pack(pack.rule_pack_id)
            return {
                "project_id": project_id,
                "pack": pack.public_dict(),
                "rules": [item.public_dict() for item in rules],
                "state": _medical_state("draft_created"),
                "reused": reused,
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post(
        "/rule-packs/{rule_pack_id}/rules/{rule_revision_id}/confirm",
    )
    def confirm_rule(
        project_id: str,
        rule_pack_id: str,
        rule_revision_id: str,
        request: RuleConfirmationRequest,
        http_request: Request,
    ):
        actor = authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-confirm:{project_id}:{rule_pack_id}:"
                f"{rule_revision_id}"
            ),
            action=MonitoringAction.APPROVE_RULE_CHANGE,
            legacy_actor=request.confirmed_by,
            reauthenticated=request.reauthenticated,
            signature_evidence_sha256=request.signature_evidence_sha256,
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            rule = authoring.confirm_rule(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                rule_revision_id=rule_revision_id,
                expected_state_version=request.expected_state_version,
                confirmed_by=actor,
            )
            return {
                "project_id": project_id,
                "rule": rule.public_dict(),
                "state": _medical_state("rule_confirmed"),
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post("/rule-packs/{rule_pack_id}/start-shadow")
    def start_rule_pack_shadow(
        project_id: str,
        rule_pack_id: str,
        request: RulePackActorRequest,
        http_request: Request,
    ):
        actor = authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-start-shadow:{project_id}:{rule_pack_id}"
            ),
            action=MonitoringAction.RUN_DETERMINISTIC_RULES,
            legacy_actor=request.actor,
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            pack = authoring.start_shadow(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                started_by=actor,
                expected_pack_revision=request.expected_pack_revision,
            )
            return {
                "project_id": project_id,
                "pack": pack.public_dict(),
                "state": _medical_state("shadow_started"),
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post(
        "/rule-packs/{rule_pack_id}/automatic-shadow-runs",
        status_code=201,
    )
    def run_rule_pack_automatic_shadow(
        project_id: str,
        rule_pack_id: str,
        request: AutomaticShadowRunRequest,
        response: Response,
        http_request: Request,
    ):
        actor = authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-automatic-shadow:{project_id}:"
                f"{rule_pack_id}:{request.batch_id}"
            ),
            action=MonitoringAction.RUN_DETERMINISTIC_RULES,
            legacy_actor=request.actor,
        )
        sample_service = _require_shadow_sample_service(
            protocol_rule_shadow_sample_service
        )
        try:
            inspection = sample_service.prepare_and_run(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                batch_id=request.batch_id,
                actor=actor,
                expected_pack_revision=request.expected_pack_revision,
            )
            if inspection.reused:
                response.status_code = 200
            return {
                "project_id": project_id,
                "pack": inspection.pack.public_dict(),
                "inspection": _public_shadow_inspection(
                    inspection.sample_set
                ),
                "state": _medical_state("shadow_inspection_provisional"),
                "reused": inspection.reused,
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.get("/rule-packs/{rule_pack_id}/shadow-sample-sets")
    def list_rule_pack_shadow_sample_sets(
        project_id: str,
        rule_pack_id: str,
        http_request: Request,
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-shadow-sample-sets-read:{project_id}:"
                f"{rule_pack_id}"
            ),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        try:
            pack, _ = rule_service.repository.rule_pack(rule_pack_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
            ) from exc
        if pack.project_id != project_id:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
            )
        sample_sets = rule_service.repository.shadow_sample_sets(
            project_id,
            rule_pack_id=rule_pack_id,
        )
        return {
            "project_id": project_id,
            "items": [
                _public_shadow_inspection(sample_set)
                for sample_set in sample_sets
            ],
        }

    @router.get("/rule-packs/{rule_pack_id}/shadow-lineage-evidence")
    def rule_pack_shadow_lineage_evidence(
        project_id: str,
        rule_pack_id: str,
        http_request: Request,
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-shadow-lineage-read:{project_id}:"
                f"{rule_pack_id}"
            ),
        )
        sample_service = _require_shadow_sample_service(
            protocol_rule_shadow_sample_service
        )
        try:
            evidence = sample_service.lineage_evidence(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
            )
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc
        confirmation = evidence.confirmation
        return {
            "project_id": project_id,
            "rule_pack_id": rule_pack_id,
            "shadow_rule_pack_id": evidence.shadow_rule_pack_id,
            "items": [
                _public_shadow_inspection(sample_set)
                for sample_set in evidence.sample_sets
            ],
            "confirmation": (
                None
                if confirmation is None
                else {
                    "confirmation_id": confirmation.confirmation_id,
                    "sample_set_id": confirmation.sample_set_id,
                    "trusted_shadow_run_id": (
                        confirmation.trusted_shadow_run_id
                    ),
                    "confirmed_at": confirmation.confirmed_at,
                }
            ),
        }

    @router.get("/rule-packs/{rule_pack_id}/shadow-runs")
    def list_rule_pack_shadow_runs(
        project_id: str,
        rule_pack_id: str,
        http_request: Request,
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-shadow-runs-read:{project_id}:"
                f"{rule_pack_id}"
            ),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        try:
            pack, _ = rule_service.repository.rule_pack(rule_pack_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
            ) from exc
        if pack.project_id != project_id:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
            )
        runs = rule_service.repository.shadow_runs(
            project_id,
            rule_pack_id=rule_pack_id,
        )
        return {
            "project_id": project_id,
            "items": [_public_shadow_run(run) for run in runs],
        }

    @router.post("/rule-packs/{rule_pack_id}/shadow-runs", status_code=201)
    def run_rule_pack_shadow(
        project_id: str,
        rule_pack_id: str,
        request: ShadowRunRequest,
        http_request: Request,
    ):
        authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-shadow:{project_id}:{rule_pack_id}:"
                f"{request.batch_id}"
            ),
            action=MonitoringAction.RUN_DETERMINISTIC_RULES,
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            run = authoring.run_shadow(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                batch_id=request.batch_id,
            )
            return {
                "project_id": project_id,
                "shadow_run": _public_shadow_run(run),
                "state": _medical_state(
                    "shadow_passed" if run.failed_count == 0 else "shadow_failed"
                ),
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post("/rule-packs/{rule_pack_id}/confirm-shadow")
    def confirm_rule_pack_shadow(
        project_id: str,
        rule_pack_id: str,
        request: ShadowConfirmationRequest,
        http_request: Request,
    ):
        actor = authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-confirm-shadow:{project_id}:"
                f"{rule_pack_id}"
            ),
            action=MonitoringAction.APPROVE_RULE_CHANGE,
            legacy_actor=request.confirmed_by,
            reauthenticated=request.reauthenticated,
            signature_evidence_sha256=request.signature_evidence_sha256,
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            outcome = authoring.confirm_shadow(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                shadow_run_id=request.shadow_run_id,
                sample_set_id=request.sample_set_id,
                confirmed_by=actor,
                expected_pack_revision=request.expected_pack_revision,
            )
            payload: dict[str, Any] = {
                "project_id": project_id,
                "pack": outcome.pack.public_dict(),
                "state": _medical_state("shadow_confirmed"),
            }
            if outcome.confirmation is not None:
                payload["confirmation_id"] = (
                    outcome.confirmation.confirmation_id
                )
                payload["shadow_run_id"] = outcome.shadow_run_id
            return payload
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.post("/rule-packs/{rule_pack_id}/publish")
    def publish_rule_pack(
        project_id: str,
        rule_pack_id: str,
        request: RulePackActorRequest,
        http_request: Request,
    ):
        actor = authorize_write(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-publish:{project_id}:{rule_pack_id}"
            ),
            action=MonitoringAction.APPROVE_RULE_CHANGE,
            legacy_actor=request.actor,
            reauthenticated=request.reauthenticated,
            signature_evidence_sha256=request.signature_evidence_sha256,
        )
        authoring = _require_rule_authoring_service(
            protocol_rule_authoring_service
        )
        try:
            pack = authoring.publish(
                project_id=project_id,
                rule_pack_id=rule_pack_id,
                published_by=actor,
                expected_pack_revision=request.expected_pack_revision,
            )
            return {
                "project_id": project_id,
                "pack": pack.public_dict(),
                "state": _medical_state("published"),
            }
        except Exception as exc:
            raise _rule_authoring_http_error(exc) from exc

    @router.get("/rule-packs")
    def list_rule_packs(project_id: str, http_request: Request):
        authorize_read(
            http_request,
            project_id,
            request_id=f"monitoring-rule-packs-list-read:{project_id}",
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        return {
            "project_id": project_id,
            "items": [
                item.public_dict()
                for item in rule_service.repository.list_rule_packs(project_id)
            ],
        }

    @router.get("/rule-packs/current")
    def current_rule_pack(
        project_id: str,
        http_request: Request,
        as_of: str = Query(default_factory=lambda: date.today().isoformat()),
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=f"monitoring-rule-pack-current-read:{project_id}",
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        try:
            return {
                "project_id": project_id,
                **rule_service.current_rule_pack(project_id, as_of=as_of),
            }
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_protocol_applicability_unresolved",
                    "message": str(exc),
                },
            ) from exc

    @router.get("/rule-packs/{rule_pack_id}")
    def get_rule_pack(
        project_id: str,
        rule_pack_id: str,
        http_request: Request,
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(f"monitoring-rule-pack-read:{project_id}:{rule_pack_id}"),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        try:
            pack, rules = rule_service.repository.rule_pack(rule_pack_id)
        except MonitoringProtocolRecordNotFound as exc:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
            ) from exc
        if pack.project_id != project_id:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_pack_not_found",
                "当前项目未找到该规则包。",
            )
        return {
            "project_id": project_id,
            "pack": pack.public_dict(),
            "rules": [rule.public_dict() for rule in rules],
        }

    @router.get("/rule-packs/{rule_pack_id}/rules/{rule_key}/source")
    def get_rule_source(
        project_id: str,
        rule_pack_id: str,
        rule_key: str,
        http_request: Request,
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-source-read:{project_id}:{rule_pack_id}:"
                f"{rule_key}"
            ),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        try:
            pack, _ = rule_service.repository.rule_pack(rule_pack_id)
            if pack.project_id != project_id:
                raise KeyError(rule_pack_id)
            return rule_service.repository.rule_source(rule_pack_id, rule_key)
        except (KeyError, MonitoringProtocolRecordNotFound) as exc:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_source_not_found",
                "未找到该规则的方案原文。",
            ) from exc

    @router.get("/rule-packs/{previous_rule_pack_id}/diff/{current_rule_pack_id}")
    def get_rule_pack_diff(
        project_id: str,
        previous_rule_pack_id: str,
        current_rule_pack_id: str,
        http_request: Request,
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=(
                f"monitoring-rule-pack-diff-read:{project_id}:"
                f"{previous_rule_pack_id}:{current_rule_pack_id}"
            ),
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        try:
            previous_pack, _ = rule_service.repository.rule_pack(
                previous_rule_pack_id
            )
            current_pack, _ = rule_service.repository.rule_pack(
                current_rule_pack_id
            )
            if (
                previous_pack.project_id != project_id
                or current_pack.project_id != project_id
            ):
                raise KeyError(project_id)
            return {
                "project_id": project_id,
                "impact": rule_service.compare_packs(
                    previous_rule_pack_id,
                    current_rule_pack_id,
                ).public_dict(),
            }
        except (KeyError, MonitoringProtocolRecordNotFound) as exc:
            raise _monitoring_protocol_not_found(
                "monitoring_rule_pack_diff_not_found",
                "无法比较所选规则包。",
            ) from exc

    @router.get("/rule-reviews")
    def list_rule_re_reviews(
        project_id: str,
        http_request: Request,
        status: str = Query("", max_length=40),
    ):
        authorize_read(
            http_request,
            project_id,
            request_id=f"monitoring-rule-reviews-read:{project_id}",
        )
        rule_service = _require_protocol_rule_service(protocol_rule_service)
        return {
            "project_id": project_id,
            "items": [
                item.__dict__
                for item in rule_service.repository.list_re_review_tasks(
                    project_id,
                    status=status.strip(),
                )
            ],
        }

    return router


def _require_protocol_rule_service(service: Any) -> Any:
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "monitoring_protocol_rules_unavailable",
                "message": "方案规则服务尚未接入。",
            },
        )
    return service


def _require_rule_authoring_service(service: Any) -> Any:
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "monitoring_rule_authoring_unavailable",
                "message": "方案规则编制服务尚未接入。",
            },
        )
    return service


def _require_shadow_sample_service(service: Any) -> Any:
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "monitoring_shadow_samples_unavailable",
                "message": "自动影子验证服务尚未接入。",
            },
        )
    return service


def _public_shadow_run(run: Any) -> dict[str, Any]:
    """Concise shadow run view: no hashes, fingerprints, or row bindings."""
    return {
        "shadow_run_id": run.shadow_run_id,
        "batch_id": run.batch_id,
        "status": run.status,
        "case_count": run.case_count,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "diagnostic_case_count": run.diagnostic_case_count,
        "diagnostic_passed_count": run.diagnostic_passed_count,
        "diagnostic_failed_count": run.diagnostic_failed_count,
        "results": [
            {
                "case_id": result.case_id,
                "rule_key": result.rule_key,
                "expected_match": result.expected_match,
                "actual_match": result.actual_match,
                "passed": result.passed,
                "evidence_summary": result.evidence_summary,
            }
            for result in run.results
        ],
        "diagnostic_results": [
            {
                "case_id": result.case_id,
                "rule_key": result.rule_key,
                "expected_diagnostic_category": result.expected_diagnostic_category,
                "expected_diagnostic_code": result.expected_diagnostic_code,
                "actual_state": result.actual_state,
                "actual_diagnostic_code": result.actual_diagnostic_code,
                "passed": result.passed,
                "evidence_summary": result.evidence_summary,
            }
            for result in run.diagnostic_results
        ],
    }


def _public_shadow_inspection(sample_set: Any) -> dict[str, Any]:
    """Concise provisional sample set view: actual outcomes only, no trusted
    run, gold-case, or release vocabulary."""
    return {
        "sample_set_id": sample_set.sample_set_id,
        "status": "provisional",
        "rule_pack_id": sample_set.rule_pack_id,
        "batch_id": sample_set.batch_id,
        "batch_version": sample_set.batch_version,
        "batch_revision": sample_set.batch_revision,
        "mapping_revision": sample_set.mapping_revision,
        "sample_count": len(sample_set.samples),
        "samples": [
            {
                "sample_id": sample.sample_id,
                "rule_key": sample.rule_key,
                "bucket": sample.bucket,
                "case_label": sample.case_label,
                "business_key": sample.business_key,
                "actual_matched": sample.actual_matched,
                "actual_evaluation_state": sample.actual_evaluation_state,
                "actual_diagnostic_code": sample.actual_diagnostic_code,
                "evidence_summary": sample.evidence_summary,
            }
            for sample in sample_set.samples
        ],
    }


def _rule_authoring_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, MonitoringRuleAuthoringError):
        return HTTPException(
            status_code=exc.http_status,
            detail={"code": exc.code, "message": exc.message},
        )
    if isinstance(exc, MonitoringProtocolRecordNotFound):
        return HTTPException(
            status_code=404,
            detail={
                "code": "monitoring_authoring_record_not_found",
                "message": "当前项目未找到所选记录。",
            },
        )
    if isinstance(exc, ProtocolApplicabilityConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "monitoring_protocol_applicability_conflict",
                "message": str(exc),
            },
        )
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "monitoring_rule_lifecycle_conflict",
                "message": str(exc),
            },
        )
    raise exc


def _public_protocol_fact(fact: Any) -> dict[str, Any]:
    value = fact.public_dict()
    payload = value.get("normalized_payload")
    if isinstance(payload, dict) and isinstance(payload.get("ai_candidate"), dict):
        candidate = payload["ai_candidate"]
        public_payload: dict[str, Any] = {
            "ai_candidate": {
                "candidate_id": candidate.get("candidate_id", ""),
                "candidate_type": candidate.get("candidate_type", ""),
                "title": candidate.get("title", ""),
                "text": candidate.get("text", ""),
            }
        }
        if isinstance(payload.get("deterministic_template"), dict):
            public_payload["deterministic_template"] = payload[
                "deterministic_template"
            ]
        value["normalized_payload"] = public_payload
    value["state"] = _medical_state(
        {
            "ai_candidate": "ai_candidate_adopted",
            "medically_confirmed": "fact_confirmed",
            "superseded": "superseded",
            "missing_source": "source_missing",
        }.get(str(value.get("status") or ""), "unknown")
    )
    return value


def _medical_state(code: str) -> dict[str, str]:
    labels = {
        "protocol_confirmed": "方案版本已登记",
        "applicability_candidate": "方案适用性依据待确认",
        "applicability_confirmed": "方案适用性已确认",
        "applicability_retired": "方案适用性已停用",
        "ai_candidate_adopted": "AI 条款候选已采纳",
        "fact_confirmed": "医学经理已确认",
        "draft_created": "规则包草稿已创建",
        "rule_confirmed": "规则已确认",
        "shadow_started": "影子验证已开始",
        "gold_case_registered": "真实核对案例已登记",
        "diagnostic_case_registered": "不可判定诊断案例已登记",
        "shadow_passed": "影子验证通过",
        "shadow_failed": "影子验证未通过",
        "shadow_inspection_provisional": "自动影子样本待医学确认",
        "shadow_confirmed": "影子验证结果已确认",
        "published": "规则包已发布",
        "superseded": "已由后续修订替代",
        "source_missing": "原文依据缺失",
        "unknown": "状态待核对",
    }
    return {"code": code, "label": labels[code]}


def _monitoring_protocol_not_found(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": code, "message": message},
    )
