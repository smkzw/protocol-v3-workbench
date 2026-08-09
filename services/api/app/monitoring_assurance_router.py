from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .monitoring_assurance_repository import (
    AssuranceDriftError,
    AssuranceIdempotencyConflictError,
    AssuranceTask,
    AssuranceTaskNotFoundError,
    AssuranceTaskStateConflictError,
    AssuranceVersionConflictError,
    MonitoringAssuranceAuditContext,
    MonitoringAssuranceError,
    MonitoringAssuranceRepository,
)
from .monitoring_assurance_service import MonitoringAssuranceService
from .monitoring_identity_authorization import (
    MonitoringAction,
    MonitoringAuthorizationDecision,
    MonitoringPrincipal,
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


class _AssuranceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateAssuranceTaskRequest(_AssuranceRequest):
    mode: str = Field(min_length=1, max_length=40)
    frozen_identity: Dict[str, str] = Field(min_length=1)
    idempotency_key: str = Field(min_length=1, max_length=240)
    # Transitional clients may still send actor, but a production route must
    # reject it and derive identity from a server-verified principal instead.
    actor: str = Field(default="", max_length=80)
    owner: str = Field(default="", max_length=120)


class ReadinessRequest(_AssuranceRequest):
    expected_version: StrictInt = Field(ge=1)
    current_identity: Dict[str, str] = Field(default_factory=dict)
    planned_subjects: StrictInt = Field(default=0, ge=0)
    actual_subjects: StrictInt = Field(default=0, ge=0)
    planned_sites: StrictInt = Field(default=0, ge=0)
    actual_sites: StrictInt = Field(default=0, ge=0)
    critical_domains_covered: StrictInt = Field(default=0, ge=0)
    critical_domains_expected: StrictInt = Field(default=0, ge=0)


class FullRecomputeProofRequest(_AssuranceRequest):
    expected_version: StrictInt = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=240)
    actor: str = Field(default="", max_length=80)
    proof_payload: Dict[str, Any] = Field(min_length=1)


class GenerateRollupsRequest(_AssuranceRequest):
    expected_version: StrictInt = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=240)
    actor: str = Field(default="", max_length=80)
    site_method_approved: StrictBool = False
    min_sample_size: StrictInt = Field(default=30, ge=1)


class MedicalReviewRequest(_AssuranceRequest):
    expected_version: StrictInt = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=240)
    actor: str = Field(default="", max_length=80)
    review_payload: Dict[str, Any] = Field(default_factory=dict)
    owner: str = Field(default="", max_length=120)
    lock_impact: str = Field(default="", max_length=200)


class CompleteTaskRequest(_AssuranceRequest):
    expected_version: StrictInt = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=240)
    confirmed_by: str = Field(default="", max_length=80)
    reauthenticated: StrictBool = False
    signature_evidence_sha256: str = Field(default="", max_length=64)


@dataclass(frozen=True)
class _AssuranceRouteAuthorization:
    actor: str
    audit_context: MonitoringAssuranceAuditContext | None = None
    principal: MonitoringPrincipal | None = None
    decision: MonitoringAuthorizationDecision | None = None


_REDACT_KEYS = frozenset(
    {
        "blob_relative_path",
        "local_path",
        "file_path",
        "source_path",
        "raw_log",
        "internal_log",
        "debug_log",
    }
)

# The current proof repository accepts a mixture of risk-reader-derived and
# caller-supplied fields.  Surface that fact on the transport boundary so the
# feature consumer can fail closed with a precise blocker.  This is not an
# evidence-authority choice: the value remains deliberately non-authoritative
# until the product/medical owner selects and implements one of the two
# accepted server authority routes.
_CURRENT_FULL_RECOMPUTE_PROVENANCE_STATUS = "mixed_provenance"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k in _REDACT_KEYS else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _public_task(task: AssuranceTask) -> Dict[str, Any]:
    return _redact(task.to_dict())


def _public_full_recompute_proof(proof: Any) -> Dict[str, Any]:
    payload = _redact(proof.to_dict())
    payload["provenance_status"] = _CURRENT_FULL_RECOMPUTE_PROVENANCE_STATUS
    return payload


def _public_audit_event(event: Any) -> Dict[str, Any]:
    return _redact(event.public_dict())


def _conflict_detail(exc: Exception) -> dict:
    if isinstance(exc, AssuranceIdempotencyConflictError):
        return {
            "code": "assurance_idempotency_conflict",
            "message": str(exc) or "幂等键重复但请求体不同。",
        }
    if isinstance(exc, AssuranceVersionConflictError):
        return {
            "code": "assurance_version_conflict",
            "message": str(exc) or "任务版本已变更，请刷新后重试。",
        }
    if isinstance(exc, AssuranceTaskStateConflictError):
        return {
            "code": "assurance_state_conflict",
            "message": str(exc) or "当前任务状态不允许此操作。",
        }
    if isinstance(exc, AssuranceDriftError):
        return {
            "code": "assurance_drift_detected",
            "message": str(exc) or "冻结身份已漂移，必须新建任务。",
        }
    return {"code": "assurance_conflict", "message": str(exc)}


def _raise_conflict(exc: Exception) -> None:
    raise HTTPException(status_code=409, detail=_conflict_detail(exc)) from exc


def _raise_not_found(exc: Exception) -> None:
    raise HTTPException(
        status_code=404,
        detail={
            "code": "assurance_task_not_found",
            "message": "未找到医学监查保障任务。",
        },
    ) from exc


def create_monitoring_assurance_router(
    *,
    repository: MonitoringAssuranceRepository,
    service: MonitoringAssuranceService,
    project_resolver: Callable[[str], str] = lambda pid: pid,
    principal_resolver: Callable[[Request], MonitoringAuthenticatedPrincipal | None]
    | None = None,
    require_server_principal: bool = True,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/projects/{project_id}/monitoring/assurance",
        tags=["medical-monitoring-assurance"],
    )

    def canonical(project_id: str) -> str:
        try:
            return project_resolver(project_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "medical_monitoring_project_not_found",
                    "message": "未找到当前医学监查项目。",
                },
            ) from exc

    def server_authorization(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
        client_actor: str,
        action: MonitoringAction,
        high_risk: bool = False,
        reauthenticated: bool = False,
        signature_evidence_sha256: str = "",
        require_write: bool = True,
    ) -> _AssuranceRouteAuthorization:
        """Authorize a route and optionally derive a write actor.

        The resolver is intentionally injected by the hosting application.  It
        may read an already verified session adapter from request state, but
        this router never parses cookies, bearer tokens or client identity.
        With the production default, an absent resolver is a visible 503
        rather than an implicit ``medical_manager`` identity.
        """

        operation = "写入" if require_write else "读取"
        if not require_server_principal:
            if not require_write:
                # This branch is reachable only from the explicitly selected
                # offline legacy test harness.  Production main.py keeps the
                # default True, so no deployed read route can bypass identity.
                return _AssuranceRouteAuthorization(actor="")
            # Only the isolated legacy write test harness may opt out explicitly.
            return _AssuranceRouteAuthorization(
                actor=str(client_actor or "medical_manager").strip()
                or "medical_manager"
            )
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份尚未接入，保障{operation}已阻断。",
                },
            )
        try:
            principal = principal_resolver(http_request)
        except (
            Exception
        ) as exc:  # provider errors must fail closed at the route boundary
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份读取失败，保障{operation}已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器未提供有效验证身份，保障{operation}已阻断。",
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
                client_actor=client_actor,
                high_risk=high_risk,
                reauthenticated=reauthenticated,
                signature_evidence_sha256=signature_evidence_sha256,
            )
            authorization_principal = route_context.principal.to_monitoring_principal(
                now=route_context.validated_at,
            )
            decision = authorize_monitoring_action(
                authorization_principal,
                route_context.request,
            )
            if not decision.allowed:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": f"monitoring_{decision.reason.value}",
                        "message": "服务器身份无权执行当前医学监查保障操作。",
                    },
                )
            if require_write and not decision.write_permitted:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "monitoring_write_not_permitted",
                        "message": "当前医学监查路由未获得写入授权。",
                    },
                )
            return _AssuranceRouteAuthorization(
                actor=authorization_principal.principal_id,
                audit_context=(
                    MonitoringAssuranceAuditContext(
                        principal=authorization_principal,
                        decision=decision,
                        signature_evidence_sha256=signature_evidence_sha256,
                    )
                    if require_write
                    else None
                ),
                principal=authorization_principal,
                decision=decision,
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
                    "message": f"服务器验证身份不满足当前医学监查保障{operation}条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": f"医学监查保障路由身份上下文无效，{operation}已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": f"医学监查保障授权请求无效，{operation}已阻断。",
                },
            ) from exc

    # ------------------------------------------------------------------
    # Create / list / get
    # ------------------------------------------------------------------

    @router.post("/tasks", status_code=201)
    def create_task(
        project_id: str,
        request: CreateAssuranceTaskRequest,
        response: Response,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorization = server_authorization(
            http_request,
            canonical_id,
            request_id=request.idempotency_key,
            client_actor=request.actor,
            action=MonitoringAction.CREATE_ASSURANCE_TASK,
        )
        try:
            result = service.create_task(
                project_id=canonical_id,
                mode=request.mode,
                frozen_identity=request.frozen_identity,
                idempotency_key=request.idempotency_key,
                actor=authorization.actor,
                owner=request.owner,
                audit_context=authorization.audit_context,
            )
        except MonitoringAssuranceError as exc:
            _raise_conflict(exc)
        if result.replayed:
            response.status_code = 200
        return {
            "project_id": canonical_id,
            "replayed": result.replayed,
            "task": _public_task(result.task),
        }

    @router.get("/tasks")
    def list_tasks(
        project_id: str,
        http_request: Request,
        mode: str = Query("", max_length=40),
    ):
        canonical_id = canonical(project_id)
        server_authorization(
            http_request,
            canonical_id,
            request_id=f"tasks-read:{canonical_id}:{mode or 'all'}",
            client_actor="",
            action=MonitoringAction.READ_RISK_AUDIT,
            require_write=False,
        )
        tasks = service.list_tasks(canonical_id, mode=mode or None)
        return {
            "project_id": canonical_id,
            "items": [_public_task(task) for task in tasks],
        }

    @router.get("/tasks/{task_id}")
    def get_task(project_id: str, task_id: str, http_request: Request):
        canonical_id = canonical(project_id)
        server_authorization(
            http_request,
            canonical_id,
            request_id=f"task-read:{canonical_id}:{task_id}",
            client_actor="",
            action=MonitoringAction.READ_RISK_AUDIT,
            require_write=False,
        )
        try:
            task = service.get_task(canonical_id, task_id)
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        return {
            "project_id": canonical_id,
            "task": _public_task(task),
        }

    @router.get("/tasks/{task_id}/audit")
    def list_task_audit(
        project_id: str,
        task_id: str,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorization = server_authorization(
            http_request,
            canonical_id,
            request_id=f"audit-read:{canonical_id}:{task_id}",
            client_actor="",
            action=MonitoringAction.READ_RISK_AUDIT,
            require_write=False,
        )
        try:
            task = service.get_task(canonical_id, task_id)
            events = repository.list_audit_events(canonical_id, task.task_id)
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        except MonitoringAssuranceError as exc:
            _raise_conflict(exc)
        return {
            "project_id": canonical_id,
            "task_id": task.task_id,
            "principal_id": authorization.principal.principal_id
            if authorization.principal
            else "",
            "items": [_public_audit_event(event) for event in events],
        }

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------

    @router.post("/tasks/{task_id}/readiness")
    def evaluate_readiness(
        project_id: str,
        task_id: str,
        request: ReadinessRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        server_authorization(
            http_request,
            canonical_id,
            request_id=f"readiness:{canonical_id}:{task_id}",
            client_actor="",
            action=MonitoringAction.READ_RISK_AUDIT,
            require_write=False,
        )
        try:
            task = service.get_task(canonical_id, task_id)
            result = service.evaluate_readiness(
                canonical_id,
                task_id,
                expected_version=request.expected_version,
                current_identity=request.current_identity or None,
                planned_subjects=request.planned_subjects,
                actual_subjects=request.actual_subjects,
                planned_sites=request.planned_sites,
                actual_sites=request.actual_sites,
                critical_domains_covered=request.critical_domains_covered,
                critical_domains_expected=request.critical_domains_expected,
            )
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        except MonitoringAssuranceError as exc:
            _raise_conflict(exc)
        return {
            "project_id": canonical_id,
            "task_id": task.task_id,
            "mode": task.mode,
            "status": task.status,
            "version": task.version,
            **result.to_dict(),
        }

    # ------------------------------------------------------------------
    # Full recompute proof (pre_lock)
    # ------------------------------------------------------------------

    @router.post("/tasks/{task_id}/full-recompute-proof")
    def record_full_recompute_proof(
        project_id: str,
        task_id: str,
        request: FullRecomputeProofRequest,
        response: Response,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorization = server_authorization(
            http_request,
            canonical_id,
            request_id=request.idempotency_key,
            client_actor=request.actor,
            action=MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
        )
        try:
            task, proof, replayed = service.record_full_recompute_proof(
                project_id=canonical_id,
                task_id=task_id,
                proof_payload=request.proof_payload,
                expected_version=request.expected_version,
                actor=authorization.actor,
                idempotency_key=request.idempotency_key,
                audit_context=authorization.audit_context,
            )
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        except MonitoringAssuranceError as exc:
            _raise_conflict(exc)
        if replayed:
            response.status_code = 200
        return {
            "project_id": canonical_id,
            "replayed": replayed,
            "task": _public_task(task),
            "proof": _public_full_recompute_proof(proof),
        }

    @router.get("/tasks/{task_id}/full-recompute-proof")
    def get_full_recompute_proof(
        project_id: str,
        task_id: str,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        server_authorization(
            http_request,
            canonical_id,
            request_id=f"proof-read:{canonical_id}:{task_id}",
            client_actor="",
            action=MonitoringAction.READ_RISK_AUDIT,
            require_write=False,
        )
        try:
            task = service.get_task(canonical_id, task_id)
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        proof = repository.get_full_recompute_proof(canonical_id, task_id)
        if proof is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "assurance_proof_not_found",
                    "message": "尚未记录全量重算证明。",
                },
            )
        return {
            "project_id": canonical_id,
            "task_id": task.task_id,
            "proof": _public_full_recompute_proof(proof),
        }

    # ------------------------------------------------------------------
    # Rollups (pre_inspection)
    # ------------------------------------------------------------------

    @router.post("/tasks/{task_id}/rollups")
    def generate_rollups(
        project_id: str,
        task_id: str,
        request: GenerateRollupsRequest,
        response: Response,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorization = server_authorization(
            http_request,
            canonical_id,
            request_id=request.idempotency_key,
            client_actor=request.actor,
            action=MonitoringAction.RECORD_ASSURANCE_EVIDENCE,
        )
        try:
            task, rollup, replayed = service.generate_rollups(
                project_id=canonical_id,
                task_id=task_id,
                expected_version=request.expected_version,
                actor=authorization.actor,
                idempotency_key=request.idempotency_key,
                site_method_approved=request.site_method_approved,
                min_sample_size=request.min_sample_size,
                audit_context=authorization.audit_context,
            )
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        except MonitoringAssuranceError as exc:
            _raise_conflict(exc)
        if replayed:
            response.status_code = 200
        return {
            "project_id": canonical_id,
            "replayed": replayed,
            "task": _public_task(task),
            "rollup": _redact(rollup.to_dict()),
        }

    @router.get("/tasks/{task_id}/rollups")
    def get_rollups(
        project_id: str,
        task_id: str,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        server_authorization(
            http_request,
            canonical_id,
            request_id=f"rollup-read:{canonical_id}:{task_id}",
            client_actor="",
            action=MonitoringAction.READ_RISK_AUDIT,
            require_write=False,
        )
        try:
            task = service.get_task(canonical_id, task_id)
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        rollup = repository.get_rollup(canonical_id, task_id)
        if rollup is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "assurance_rollup_not_found",
                    "message": "尚未生成三级汇总。",
                },
            )
        return {
            "project_id": canonical_id,
            "task_id": task.task_id,
            "rollup": _redact(rollup.to_dict()),
        }

    # ------------------------------------------------------------------
    # Medical review
    # ------------------------------------------------------------------

    @router.post("/tasks/{task_id}/medical-review")
    def record_medical_review(
        project_id: str,
        task_id: str,
        request: MedicalReviewRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorization = server_authorization(
            http_request,
            canonical_id,
            request_id=request.idempotency_key,
            client_actor=request.actor,
            action=MonitoringAction.REVIEW_ASSURANCE,
        )
        try:
            task = service.record_medical_review(
                project_id=canonical_id,
                task_id=task_id,
                expected_version=request.expected_version,
                actor=authorization.actor,
                idempotency_key=request.idempotency_key,
                review_payload=request.review_payload,
                owner=request.owner or None,
                lock_impact=request.lock_impact or None,
                audit_context=authorization.audit_context,
            )
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        except MonitoringAssuranceError as exc:
            _raise_conflict(exc)
        return {
            "project_id": canonical_id,
            "task": _public_task(task),
        }

    # ------------------------------------------------------------------
    # Complete
    # ------------------------------------------------------------------

    @router.post("/tasks/{task_id}/complete")
    def complete_task(
        project_id: str,
        task_id: str,
        request: CompleteTaskRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorization = server_authorization(
            http_request,
            canonical_id,
            request_id=request.idempotency_key,
            client_actor=request.confirmed_by,
            action=MonitoringAction.COMPLETE_ASSURANCE,
            high_risk=True,
            reauthenticated=request.reauthenticated,
            signature_evidence_sha256=request.signature_evidence_sha256,
        )
        try:
            task = service.complete_task(
                project_id=canonical_id,
                task_id=task_id,
                expected_version=request.expected_version,
                confirmed_by=authorization.actor,
                idempotency_key=request.idempotency_key,
                audit_context=authorization.audit_context,
            )
        except AssuranceTaskNotFoundError as exc:
            _raise_not_found(exc)
        except MonitoringAssuranceError as exc:
            _raise_conflict(exc)
        return {
            "project_id": canonical_id,
            "task": _public_task(task),
        }

    return router
