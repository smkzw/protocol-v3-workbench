from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt

from .monitoring_ai_contracts import candidate_confidence_summary
from .monitoring_daily_run_repository import (
    DailyRunBaselineConflictError,
    DailyRunNotFoundError,
    MonitoringDailyRunRepository,
    MonitoringDailyRunRepositoryError,
)
from .monitoring_daily_run_service import (
    MonitoringDailyRunService,
    MonitoringDailyRunServiceError,
)
from .monitoring_daily_run_analysis_service import (
    MonitoringDailyRunAnalysisService,
    MonitoringDailyRunAnalysisServiceError,
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


class MonitoringDailyRunPrepareRequest(BaseModel):
    batch_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=240)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)


class MonitoringDailyRunProcessRequest(BaseModel):
    expected_version: StrictInt = Field(ge=1)
    owner: str = Field(default="monitoring-worker", min_length=2, max_length=120)


class MonitoringDailyRunReviewRequest(BaseModel):
    expected_version: StrictInt = Field(ge=1)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)


class MonitoringDailyRunConfirmRequest(BaseModel):
    expected_run_version: StrictInt = Field(ge=1)
    expected_baseline_revision: StrictInt = Field(ge=0)
    confirmed_by: str = Field(
        default="medical_manager",
        min_length=2,
        max_length=80,
    )
    reauthenticated: StrictBool = False
    signature_evidence_sha256: str = Field(default="", max_length=64)


class MonitoringDailyRunSupersedeRequest(BaseModel):
    replacement_run_id: str = Field(min_length=1, max_length=200)
    expected_version: StrictInt = Field(ge=1)
    actor: str = Field(default="medical_manager", min_length=2, max_length=80)


def create_monitoring_daily_run_router(
    *,
    repository: MonitoringDailyRunRepository,
    service: MonitoringDailyRunService,
    analysis_service: MonitoringDailyRunAnalysisService | None = None,
    project_resolver: Callable[[str], str] = lambda project_id: project_id,
    principal_resolver: Callable[[Request], MonitoringAuthenticatedPrincipal | None]
    | None = None,
    require_server_principal: bool = True,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/projects/{project_id}/monitoring/daily-runs",
        tags=["medical-monitoring-daily-runs"],
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

    def authorize_server_action(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
        action: MonitoringAction,
        require_write: bool,
        legacy_actor: str = "",
        high_risk: bool = False,
        reauthenticated: bool = False,
        signature_evidence_sha256: str = "",
    ) -> str:
        """Authorize a daily-run route from a host-verified principal.

        The resolver is injected by the host and may only return an already
        verified runtime principal. This router never parses headers, cookies,
        bearer tokens or client actor values. Transitional request actor fields
        are deliberately not passed into the authorization request; production
        identity is derived only from the server principal. The
        ``require_server_principal=False`` branch exists solely for explicitly
        selected offline test harnesses.
        """

        if not require_server_principal:
            return str(legacy_actor or "medical_manager").strip() or "medical_manager"
        operation = "写入" if require_write else "读取"
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份尚未接入，日常医学监查{operation}已阻断。",
                },
            )
        try:
            principal = principal_resolver(http_request)
        except Exception as exc:  # provider errors fail closed at the route boundary
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份读取失败，日常医学监查{operation}已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器未提供有效验证身份，日常医学监查{operation}已阻断。",
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
                high_risk=high_risk,
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
                    "message": f"服务器验证身份不满足日常医学监查{operation}条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": f"日常医学监查路由身份上下文无效，{operation}已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": f"日常医学监查授权请求无效，{operation}已阻断。",
                },
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"monitoring_{decision.reason.value}",
                    "message": f"服务器身份无权{operation}当前日常医学监查运行。",
                },
            )
        if require_write and not decision.write_permitted:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_write_not_permitted",
                    "message": "当前日常医学监查路由未获得写入授权。",
                },
            )
        return principal.server_actor

    def authorize_read(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
    ) -> None:
        authorize_server_action(
            http_request,
            project_id,
            request_id=request_id,
            action=MonitoringAction.READ_MONITORING,
            require_write=False,
        )

    def authorize_write(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
        action: MonitoringAction,
        legacy_actor: str = "",
        high_risk: bool = False,
        reauthenticated: bool = False,
        signature_evidence_sha256: str = "",
    ) -> str:
        return authorize_server_action(
            http_request,
            project_id,
            request_id=request_id,
            action=action,
            require_write=True,
            legacy_actor=legacy_actor,
            high_risk=high_risk,
            reauthenticated=reauthenticated,
            signature_evidence_sha256=signature_evidence_sha256,
        )

    @router.get("")
    def list_runs(project_id: str, http_request: Request):
        canonical_id = canonical(project_id)
        authorize_read(
            http_request,
            canonical_id,
            request_id=f"daily-runs-read:{canonical_id}",
        )
        active = repository.active_run(canonical_id)
        baseline = repository.current_baseline(canonical_id)
        return {
            "project_id": canonical_id,
            "active_run": active.to_dict() if active is not None else None,
            "current_baseline": (
                _baseline_dict(baseline) if baseline is not None else None
            ),
            "items": [
                run.to_dict() for run in repository.list_runs(canonical_id)
            ],
        }

    @router.get("/readiness")
    def start_readiness(
        project_id: str,
        batch_id: str,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorize_read(
            http_request,
            canonical_id,
            request_id=f"daily-readiness:{canonical_id}:{batch_id}",
        )
        return service.start_readiness(
            project_id=canonical_id,
            batch_id=batch_id,
        )

    @router.post("", status_code=201)
    def prepare_run(
        project_id: str,
        request: MonitoringDailyRunPrepareRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        actor = authorize_write(
            http_request,
            canonical_id,
            request_id=request.idempotency_key,
            action=MonitoringAction.INTAKE_BATCH,
            legacy_actor=request.actor,
        )
        try:
            result = service.prepare(
                project_id=canonical_id,
                batch_id=request.batch_id,
                idempotency_key=request.idempotency_key,
                actor=actor,
            )
            return {
                "project_id": canonical_id,
                "replayed": result.replayed,
                "run": result.run.to_dict(),
                "next_action": "process_batch",
            }
        except MonitoringDailyRunServiceError as exc:
            raise _service_http_error(exc) from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.get("/{run_id}")
    def get_run(project_id: str, run_id: str, http_request: Request):
        canonical_id = canonical(project_id)
        authorize_read(
            http_request,
            canonical_id,
            request_id=f"daily-run-read:{canonical_id}:{run_id}",
        )
        try:
            run = repository.get(canonical_id, run_id)
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        diff = repository.get_diff_snapshot(canonical_id, run_id)
        rules = repository.get_rule_snapshot(canonical_id, run_id)
        return {
            "project_id": canonical_id,
            "run": run.to_dict(),
            "diff": _diff_dict(diff) if diff is not None else None,
            "rules": _rule_dict(rules) if rules is not None else None,
            "steps": [_step_dict(item) for item in repository.list_steps(run_id)],
        }

    @router.post("/{run_id}/process")
    def process_run(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunProcessRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        owner = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-process:{canonical_id}:{run_id}",
            action=MonitoringAction.RUN_DETERMINISTIC_RULES,
            legacy_actor=request.owner,
        )
        try:
            return service.process_prepared(
                project_id=canonical_id,
                run_id=run_id,
                expected_version=request.expected_version,
                owner=owner,
            ).to_dict()
        except MonitoringDailyRunServiceError as exc:
            raise _service_http_error(exc) from exc
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.post("/{run_id}/execute-rules")
    def execute_rules(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunProcessRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        owner = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-rules:{canonical_id}:{run_id}",
            action=MonitoringAction.RUN_DETERMINISTIC_RULES,
            legacy_actor=request.owner,
        )
        try:
            return service.execute_rules(
                project_id=canonical_id,
                run_id=run_id,
                expected_version=request.expected_version,
                owner=owner,
            ).to_dict()
        except MonitoringDailyRunServiceError as exc:
            raise _service_http_error(exc) from exc
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.post("/{run_id}/submit-ai")
    def submit_ai(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunProcessRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        owner = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-submit-ai:{canonical_id}:{run_id}",
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            legacy_actor=request.owner,
        )
        analysis = _analysis_service(analysis_service)
        try:
            return analysis.submit_ai(
                project_id=canonical_id,
                run_id=run_id,
                expected_version=request.expected_version,
                owner=owner,
            ).to_dict()
        except MonitoringDailyRunAnalysisServiceError as exc:
            raise _analysis_http_error(exc) from exc
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.get("/{run_id}/ai-progress")
    def ai_progress(
        project_id: str,
        run_id: str,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        authorize_read(
            http_request,
            canonical_id,
            request_id=f"daily-ai-progress-read:{canonical_id}:{run_id}",
        )
        analysis = _analysis_service(analysis_service)
        try:
            return _ai_progress_dict(
                analysis.ai_progress(
                    project_id=canonical_id,
                    run_id=run_id,
                )
            )
        except MonitoringDailyRunAnalysisServiceError as exc:
            raise _analysis_http_error(exc) from exc
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc

    @router.post("/{run_id}/assemble-risks")
    def assemble_risks(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunProcessRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        owner = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-assemble-risks:{canonical_id}:{run_id}",
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            legacy_actor=request.owner,
        )
        analysis = _analysis_service(analysis_service)
        try:
            return analysis.assemble_risks(
                project_id=canonical_id,
                run_id=run_id,
                expected_version=request.expected_version,
                owner=owner,
            ).to_dict()
        except MonitoringDailyRunAnalysisServiceError as exc:
            raise _analysis_http_error(exc) from exc
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.post("/{run_id}/acknowledge-partial")
    def acknowledge_partial(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunReviewRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        actor = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-acknowledge-partial:{canonical_id}:{run_id}",
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            legacy_actor=request.actor,
        )
        analysis = _analysis_service(analysis_service)
        try:
            run = analysis.acknowledge_partial(
                project_id=canonical_id,
                run_id=run_id,
                expected_version=request.expected_version,
                actor=actor,
            )
            return {"project_id": canonical_id, "run": run.to_dict()}
        except MonitoringDailyRunAnalysisServiceError as exc:
            raise _analysis_http_error(exc) from exc
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.post("/{run_id}/ready-to-confirm")
    def mark_ready_to_confirm(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunReviewRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        actor = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-ready-to-confirm:{canonical_id}:{run_id}",
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            legacy_actor=request.actor,
        )
        try:
            run = repository.transition(
                canonical_id,
                run_id,
                target_status="ready_to_confirm",
                expected_version=request.expected_version,
                actor=actor,
            )
            return {"project_id": canonical_id, "run": run.to_dict()}
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.post("/{run_id}/supersede")
    def supersede_drifted_run(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunSupersedeRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        actor = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-supersede:{canonical_id}:{run_id}",
            action=MonitoringAction.CHANGE_RISK_DISPOSITION,
            legacy_actor=request.actor,
        )
        try:
            run = repository.supersede_drifted_run(
                canonical_id,
                run_id,
                replacement_run_id=request.replacement_run_id,
                expected_version=request.expected_version,
                actor=actor,
            )
            return {"project_id": canonical_id, "run": run.to_dict()}
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    @router.post("/{run_id}/confirm")
    def confirm_run(
        project_id: str,
        run_id: str,
        request: MonitoringDailyRunConfirmRequest,
        http_request: Request,
    ):
        canonical_id = canonical(project_id)
        actor = authorize_write(
            http_request,
            canonical_id,
            request_id=f"daily-confirm:{canonical_id}:{run_id}",
            action=MonitoringAction.CHANGE_RISK_DISPOSITION,
            legacy_actor=request.confirmed_by,
            high_risk=True,
            reauthenticated=request.reauthenticated,
            signature_evidence_sha256=request.signature_evidence_sha256,
        )
        try:
            result = repository.confirm_run(
                canonical_id,
                run_id,
                expected_run_version=request.expected_run_version,
                expected_baseline_revision=request.expected_baseline_revision,
                confirmed_by=actor,
            )
            return {
                "project_id": canonical_id,
                "run": result.run.to_dict(),
                "current_baseline": _baseline_dict(result.baseline),
            }
        except DailyRunNotFoundError as exc:
            raise _not_found() from exc
        except DailyRunBaselineConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_baseline_changed",
                    "message": "项目医学确认基线已变化，请刷新后重新确认。",
                },
            ) from exc
        except MonitoringDailyRunRepositoryError as exc:
            raise _repository_http_error(exc) from exc

    return router


def _service_http_error(exc: MonitoringDailyRunServiceError) -> HTTPException:
    status_code = 404 if exc.code == "monitoring_batch_not_found" else 409
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message},
    )


def _analysis_http_error(
    exc: MonitoringDailyRunAnalysisServiceError,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": exc.code, "message": exc.message},
    )


def _analysis_service(
    value: MonitoringDailyRunAnalysisService | None,
) -> MonitoringDailyRunAnalysisService:
    if value is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "monitoring_daily_analysis_unavailable",
                "message": "日常医学监查分析服务当前不可用。",
            },
        )
    return value


def _repository_http_error(exc: MonitoringDailyRunRepositoryError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": _repository_error_code(exc),
            "message": str(exc),
        },
    )


def _repository_error_code(exc: MonitoringDailyRunRepositoryError) -> str:
    name = type(exc).__name__
    if "Version" in name:
        return "monitoring_run_version_conflict"
    if "Lease" in name:
        return "monitoring_run_busy"
    if "Active" in name:
        return "monitoring_run_already_active"
    if "Idempotency" in name:
        return "monitoring_run_idempotency_conflict"
    return "monitoring_run_state_conflict"


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "monitoring_run_not_found",
            "message": "未找到当前医学监查运行。",
        },
    )


def _baseline_dict(value: Any) -> dict[str, Any]:
    return {
        "project_id": value.project_id,
        "current_baseline_batch_id": value.current_baseline_batch_id,
        "confirmed_run_id": value.confirmed_run_id,
        "revision": value.revision,
        "confirmed_at": value.confirmed_at.isoformat(),
        "confirmed_by": value.confirmed_by,
    }


def _diff_dict(value: Any) -> dict[str, Any]:
    return {
        "snapshot_id": value.snapshot_id,
        "previous_batch_id": value.previous_batch_id,
        "current_batch_id": value.current_batch_id,
        "algorithm_version": value.algorithm_version,
        "output_sha256": value.output_sha256,
        "payload": value.payload,
        "created_at": value.created_at.isoformat(),
    }


def _step_dict(value: Any) -> dict[str, Any]:
    return {
        "step_name": value.step_name,
        "status": value.status,
        "attempt_count": value.attempt_count,
        "details": value.details,
        "started_at": value.started_at.isoformat(),
        "updated_at": value.updated_at.isoformat(),
        "finished_at": (
            value.finished_at.isoformat() if value.finished_at is not None else ""
        ),
    }


def _rule_dict(value: Any) -> dict[str, Any]:
    payload = dict(value.payload)
    return {
        "snapshot_id": value.snapshot_id,
        "batch_id": value.batch_id,
        "rule_pack_id": value.rule_pack_id,
        "engine_version": value.engine_version,
        "output_sha256": value.output_sha256,
        "evaluated_record_count": int(
            payload.get("evaluated_record_count") or 0
        ),
        "candidate_count": len(payload.get("candidates") or ()),
        "diagnostic_count": len(payload.get("diagnostics") or ()),
        "created_at": value.created_at.isoformat(),
    }


def _ai_progress_dict(value: Any) -> dict[str, Any]:
    return {
        "project_id": value.project_id,
        "run_id": value.run_id,
        "status": value.status,
        "total": value.total,
        "queued": value.queued,
        "running": value.running,
        "completed": value.completed,
        "failed": value.failed,
        "candidate_count": len(value.candidates),
        "candidates": [
            _daily_ai_candidate_dict(item)
            for item in value.candidates
        ],
        "failures": list(value.failures),
    }


def _daily_ai_candidate_dict(value: Any) -> dict[str, Any]:
    """Expose the existing public candidate contract in daily-run context.

    This is a read-only projection. It deliberately does not add an accept,
    reject, promote or risk-disposition action to the daily-run route.
    """
    candidate = value.candidate
    payload = candidate.model_dump(mode="json")
    payload["confidence_summary"] = candidate_confidence_summary(candidate)
    return {
        "subject_id": value.subject_id,
        "job_id": value.job_id,
        "candidate": payload,
    }
