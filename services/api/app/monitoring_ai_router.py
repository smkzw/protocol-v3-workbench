from __future__ import annotations

import re
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)

from .monitoring_ai_contracts import (
    MonitoringAiCandidateStatus,
    MonitoringAiInputRevision,
    MonitoringAiJobStatus,
    MonitoringAiSourceBinding,
    MonitoringAiTaskType,
    candidate_confidence_summary,
    content_sha256,
)
from .monitoring_ai_field_profiler import MonitoringAIFieldProfiler
from .monitoring_ai_repository import (
    MonitoringAiRepository,
    MonitoringAiRepositoryError,
    MonitoringAiStateConflictError,
)
from .monitoring_ai_service import (
    MonitoringAiService,
    PROMPT_VERSION_BY_TASK,
    monitoring_revision_with_field_profile,
)
from .monitoring_batch_repository import (
    DiffReadyBatch,
    FieldProfileBatchIdentity,
    MonitoringBatchRepository,
    MonitoringBatchRepositoryError,
)
from .monitoring_mapping_draft_repository import (
    MonitoringMappingDraftRepository,
    MonitoringMappingDraftError,
    MonitoringMappingNotFoundError,
    MonitoringMappingStateConflictError,
)
from .monitoring_mapping_activation import (
    MonitoringMappingActivationConflictError,
    MonitoringMappingActivationNotFoundError,
    MonitoringMappingActivationService,
    MonitoringMappingActivationSourceError,
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


_ROUTER_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _require_router_sha256(value: Any, field_name: str) -> str:
    """Require an exact persisted digest; never normalize its identity."""

    if not isinstance(value, str) or not _ROUTER_SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class FieldMappingStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=2, max_length=200)
    chunk_size: StrictInt = Field(default=12, ge=1, le=12)
    retry_failed: StrictBool = False


class CandidateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: MonitoringAiCandidateStatus
    actor: str = Field(default="medical_manager", min_length=2, max_length=160)
    reason: str = Field(default="", max_length=2_000)


class DeterministicV7RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_batch_id: str = Field(min_length=2, max_length=200)
    expected_input_revision_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_full_profile_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    actor: str = Field(min_length=2, max_length=160)
    reason: str = Field(min_length=1, max_length=2_000)
    idempotency_key: str = Field(min_length=2, max_length=240)


class SemanticTaskStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: MonitoringAiTaskType
    business_key: str = Field(min_length=2, max_length=240)
    source_ids: list[str] = Field(min_length=1, max_length=200)
    context: dict[str, Any] = Field(min_length=1)
    max_attempts: StrictInt = Field(default=2, ge=1, le=3)

    @model_validator(mode="after")
    def validate_semantic_task(self) -> "SemanticTaskStartRequest":
        if self.task_type == MonitoringAiTaskType.LISTING_FIELD_MAPPING:
            raise ValueError(
                "listing_field_mapping must use field-mapping-jobs"
            )
        cleaned = [item.strip() for item in self.source_ids]
        if any(not item for item in cleaned) or len(cleaned) != len(set(cleaned)):
            raise ValueError("source_ids must be non-empty and unique")
        self.source_ids = cleaned
        return self


class RiskSemanticTaskStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: MonitoringAiTaskType
    business_key: str = Field(min_length=2, max_length=240)
    risk_instance_id: str = Field(min_length=2, max_length=240)
    context: dict[str, Any] = Field(default_factory=dict)
    max_attempts: StrictInt = Field(default=2, ge=1, le=3)

    @model_validator(mode="after")
    def validate_risk_task(self) -> "RiskSemanticTaskStartRequest":
        allowed = {
            MonitoringAiTaskType.CROSS_TABLE_CLUE_SYNTHESIS,
            MonitoringAiTaskType.RISK_EVIDENCE_SUMMARY,
            MonitoringAiTaskType.RISK_QUESTION_ANSWER,
            MonitoringAiTaskType.QUERY_EXPLANATION_CANDIDATES,
        }
        if self.task_type not in allowed:
            raise ValueError(
                "risk-jobs supports cross-table clue, risk summary, risk "
                "question-answer and query/explanation tasks only"
            )
        self.risk_instance_id = self.risk_instance_id.strip()
        return self


class MappingDraftAssembleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=2, max_length=200)
    full_profile_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class MappingDraftFieldEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=240)
    patch: dict[str, Any]
    expected_version: StrictInt = Field(ge=1)
    actor: str = Field(default="medical_manager", min_length=2, max_length=160)
    idempotency_key: str = Field(min_length=2, max_length=240)


class MappingDraftConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: StrictInt = Field(ge=1)
    confirmed_by: str = Field(
        default="medical_manager",
        min_length=2,
        max_length=160,
    )
    confirmation_reason: str = Field(min_length=1, max_length=2_000)
    idempotency_key: str = Field(min_length=2, max_length=240)
    expected_project_version: Optional[StrictInt] = Field(default=None, ge=0)


class MappingRunAdoptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch_id: str = Field(min_length=2, max_length=200)
    full_profile_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    actor: str = Field(default="medical_manager", min_length=2, max_length=160)
    reason: str = Field(min_length=1, max_length=2_000)


def monitoring_input_revision_for_batch(
    batch: DiffReadyBatch,
) -> MonitoringAiInputRevision:
    return MonitoringAiInputRevision(
        project_id=batch.project_id,
        batch_revision=f"{batch.batch_id}:v{batch.version}",
        mapping_revision=batch.mapping_revision or "",
        sources=tuple(
            MonitoringAiSourceBinding(
                source_entry_id=source_entry_id,
                source_content_sha256=content_sha256,
            )
            for source_entry_id, content_sha256 in batch.source_bindings
        ),
    )


def monitoring_input_revision_for_profile_identity(
    identity: FieldProfileBatchIdentity,
    *,
    include_binding_identity: bool = True,
) -> MonitoringAiInputRevision:
    source_pairs = sorted(
        {
            (
                binding.source_entry_id,
                binding.source_content_sha256,
            )
            for binding in identity.source_bindings
        }
    )
    return MonitoringAiInputRevision(
        project_id=identity.project_id,
        batch_revision=f"{identity.batch_id}:v{identity.batch_version}",
        mapping_revision=identity.mapping_revision or "",
        source_binding_revision=(
            f"source-binding:{identity.source_binding_identity_sha256}"
            if include_binding_identity
            else ""
        ),
        sources=tuple(
            MonitoringAiSourceBinding(
                source_entry_id=source_entry_id,
                source_content_sha256=content_sha256,
            )
            for source_entry_id, content_sha256 in source_pairs
        ),
    )


def _compatible_legacy_field_mapping_revision(
    repository: MonitoringAiRepository,
    identity: FieldProfileBatchIdentity,
    *,
    full_profile_sha256: str,
    full_input_sha256: str,
) -> MonitoringAiInputRevision | None:
    """Reuse pre-binding contracts only for the same immutable batch input.

    Source-binding identity was added after some production mapping runs had
    already completed. Those historical contracts still bind the exact source
    entry/content pairs, batch revision, profile and prompt. Reusing them avoids
    discarding valid candidates solely because the newer redundant identity
    field was absent. Any material input change produces a different expected
    legacy hash and therefore fails closed.
    """

    legacy_revision = monitoring_input_revision_for_profile_identity(
        identity,
        include_binding_identity=False,
    )
    expected_revision_sha256 = monitoring_revision_with_field_profile(
        legacy_revision,
        full_profile_sha256,
    ).revision_sha256
    current_prompt = PROMPT_VERSION_BY_TASK[
        MonitoringAiTaskType.LISTING_FIELD_MAPPING
    ]
    for job in repository.list_jobs(
        identity.project_id,
        task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING.value,
        business_key_prefix=f"listing-field-mapping:{identity.batch_id}:",
    ):
        if (
            job.prompt_version != current_prompt
            or job.input_revision.source_binding_revision
            or job.input_revision.revision_sha256
            != job.input_revision_sha256
            or job.input_revision_sha256 != expected_revision_sha256
        ):
            continue
        payload = repository.input_payload(identity.project_id, job.job_id)
        if content_sha256(payload) != job.input_payload_sha256:
            continue
        profile = payload.get("field_profile", {})
        if (
            str(profile.get("project_id", "")).strip()
            != identity.project_id
            or str(profile.get("batch_id", "")).strip()
            != identity.batch_id
            or str(profile.get("batch_revision", "")).strip()
            != str(identity.batch_version)
            or profile.get("full_profile_sha256") != full_profile_sha256
            or profile.get("full_input_sha256") != full_input_sha256
        ):
            continue
        return legacy_revision
    return None


def _preferred_field_mapping_revision(
    repository: MonitoringAiRepository,
    identity: FieldProfileBatchIdentity,
    *,
    full_profile_sha256: str,
    full_input_sha256: str,
) -> MonitoringAiInputRevision:
    return _compatible_legacy_field_mapping_revision(
        repository,
        identity,
        full_profile_sha256=full_profile_sha256,
        full_input_sha256=full_input_sha256,
    ) or monitoring_input_revision_for_profile_identity(identity)


def create_monitoring_ai_router(
    *,
    repository: MonitoringAiRepository,
    service: MonitoringAiService,
    batch_repository: MonitoringBatchRepository,
    mapping_repository: Optional[MonitoringMappingDraftRepository] = None,
    mapping_activation_service: Optional[
        MonitoringMappingActivationService
    ] = None,
    source_packet_resolver: Optional[
        Callable[[str, list[str]], Any]
    ] = None,
    source_span_searcher: Optional[Callable[..., Any]] = None,
    risk_packet_resolver: Optional[Callable[[str, str], Any]] = None,
    worker_wake: Callable[[], Any] = lambda: None,
    project_resolver: Callable[[str], str] = lambda value: value,
    principal_resolver: Callable[[Request], MonitoringAuthenticatedPrincipal | None]
    | None = None,
    require_server_principal: bool = True,
) -> APIRouter:
    profiler = MonitoringAIFieldProfiler(batch_repository)
    router = APIRouter(
        prefix="/api/projects/{project_id}/modules/medical-monitoring/ai",
        tags=["medical-monitoring-ai"],
    )
    effective_source_span_searcher = source_span_searcher
    if effective_source_span_searcher is None and source_packet_resolver is not None:
        resolver_owner = getattr(source_packet_resolver, "__self__", None)
        candidate = getattr(resolver_owner, "search", None)
        if callable(candidate):
            effective_source_span_searcher = candidate

    def authorize_route(
        http_request: Request,
        project_id: str,
        *,
        request_id: str,
        action: MonitoringAction,
        require_write: bool,
        legacy_actor: str = "",
    ) -> str:
        """Authorize an AI route from the host principal and fail closed."""

        if not require_server_principal:
            return str(legacy_actor or "medical_manager").strip() or "medical_manager"
        operation = "写入" if require_write else "读取"
        if principal_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份尚未接入，医学监查 AI {operation}已阻断。",
                },
            )
        try:
            principal = principal_resolver(http_request)
        except Exception as exc:  # host/provider failures fail closed
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器验证身份读取失败，医学监查 AI {operation}已阻断。",
                },
            ) from exc
        if not isinstance(principal, MonitoringAuthenticatedPrincipal):
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_principal_unavailable",
                    "message": f"服务器未提供有效验证身份，医学监查 AI {operation}已阻断。",
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
                    "message": f"服务器验证身份不满足医学监查 AI {operation}条件。",
                },
            ) from exc
        except MonitoringRuntimeRouteContextError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_route_context_invalid",
                    "message": f"医学监查 AI 路由身份上下文无效，{operation}已阻断。",
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_authorization_request_invalid",
                    "message": f"医学监查 AI 授权请求无效，{operation}已阻断。",
                },
            ) from exc
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": f"monitoring_{decision.reason.value}",
                    "message": f"服务器身份无权{operation}当前医学监查 AI 流程。",
                },
            )
        if require_write and not decision.write_permitted:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "monitoring_write_not_permitted",
                    "message": "当前医学监查 AI 路由未获得写入授权。",
                },
            )
        return principal.server_actor

    @router.get("/evidence-spans/search")
    def search_evidence_spans(
        project_id: str,
        http_request: Request,
        entry_id: str = Query(..., min_length=2, max_length=240),
        query: list[str] = Query(...),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=f"ai-source-search:{canonical_id}:{entry_id}",
            action=MonitoringAction.READ_SOURCE_EVIDENCE,
            require_write=False,
        )
        if effective_source_span_searcher is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_ai_source_search_unavailable",
                    "message": "医学监查方案证据检索器当前不可用。",
                },
            )
        try:
            results = effective_source_span_searcher(
                canonical_id,
                entry_id,
                query,
                limit=limit,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "monitoring_ai_source_entry_not_found",
                    "message": str(exc),
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "monitoring_ai_source_search_invalid",
                    "message": str(exc),
                },
            ) from exc
        return {
            "project_id": canonical_id,
            "source_entry_id": entry_id,
            "query": query,
            "limit": limit,
            "result_count": len(results),
            "results": [dict(item) for item in results],
        }

    @router.get("/field-mapping-status")
    def field_mapping_status(
        project_id: str,
        batch_id: str,
        http_request: Request,
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=f"ai-field-mapping-status:{canonical_id}:{batch_id}",
            action=MonitoringAction.READ_AI_RUN,
            require_write=False,
        )
        try:
            lightweight_loader = getattr(batch_repository, "get_batch", None)
            batch = (
                lightweight_loader(batch_id)
                if callable(lightweight_loader)
                else batch_repository.load_profile_ready_batch(batch_id)
            )
            if batch.project_id != canonical_id:
                raise MonitoringBatchRepositoryError(
                    "monitoring batch not found for project"
                )
            if batch.state not in {
                "parsed",
                "validated",
                "confirmed",
                "frozen",
            }:
                raise MonitoringBatchRepositoryError(
                    "batch must be parsed before field mapping status is available"
                )
        except MonitoringBatchRepositoryError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "monitoring_ai_batch_unavailable",
                    "message": str(exc),
                },
            ) from exc
        current_prompt = PROMPT_VERSION_BY_TASK[
            MonitoringAiTaskType.LISTING_FIELD_MAPPING
        ]
        matching_jobs = []
        for job in repository.list_jobs(
            canonical_id,
            task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING.value,
            business_key_prefix=f"listing-field-mapping:{batch_id}:",
        ):
            if job.input_revision.revision_sha256 != job.input_revision_sha256:
                continue
            payload = repository.input_payload(canonical_id, job.job_id)
            profile = payload.get("field_profile", {})
            if (
                job.prompt_version != current_prompt
                or str(profile.get("batch_id", "")).strip() != batch_id
                or str(profile.get("project_id", "")).strip() != canonical_id
                or str(profile.get("batch_revision", "")).strip()
                != str(batch.version)
            ):
                continue
            try:
                full_profile_sha256 = _require_router_sha256(
                    profile.get("full_profile_sha256"),
                    "field_profile.full_profile_sha256",
                )
                _require_router_sha256(
                    profile.get("full_input_sha256"),
                    "field_profile.full_input_sha256",
                )
            except ValueError:
                continue
            matching_jobs.append((job, profile, full_profile_sha256))

        selected_profile_sha256 = (
            matching_jobs[-1][2] if matching_jobs else ""
        )
        selected_profile = (
            matching_jobs[-1][1] if matching_jobs else {}
        )
        selected_input_sha256 = (
            _require_router_sha256(
                selected_profile.get("full_input_sha256"),
                "field_profile.full_input_sha256",
            )
            if selected_profile_sha256
            else ""
        )
        identity_loader = getattr(
            batch_repository,
            "load_field_profile_cache_identity",
            None,
        )
        identity = (
            identity_loader(batch_id)
            if callable(identity_loader) and selected_profile_sha256
            else None
        )
        preferred_revision_sha256 = ""
        if identity is not None:
            preferred_revision = _preferred_field_mapping_revision(
                repository,
                identity,
                full_profile_sha256=selected_profile_sha256,
                full_input_sha256=selected_input_sha256,
            )
            preferred_revision_sha256 = monitoring_revision_with_field_profile(
                preferred_revision,
                selected_profile_sha256,
            ).revision_sha256
        selected_jobs = [
            (job, profile)
            for job, profile, profile_sha256 in matching_jobs
            if profile_sha256 == selected_profile_sha256
            and (
                not preferred_revision_sha256
                or job.input_revision_sha256 == preferred_revision_sha256
            )
        ]
        include_candidate_payloads = bool(selected_jobs) and all(
            job.status == MonitoringAiJobStatus.COMPLETED
            for job, _profile in selected_jobs
        )
        job_details = []
        for job, _profile in selected_jobs:
            job_details.append(
                {
                    "job": _public_job(job),
                    "candidates": [
                        _public_candidate(candidate)
                        for candidate in repository.candidates(
                            canonical_id,
                            job.job_id,
                        )
                    ]
                    if include_candidate_payloads
                    else [],
                }
            )
        selected_profile = selected_jobs[0][1] if selected_jobs else {}
        full_input_sha256 = (
            _require_router_sha256(
                selected_profile.get("full_input_sha256"),
                "field_profile.full_input_sha256",
            )
            if selected_profile_sha256
            else ""
        )
        full_field_count = int(
            selected_profile.get("full_field_count", 0) or 0
        )
        draft = (
            mapping_repository.find_draft_for_batch(
                canonical_id,
                batch_id,
                full_profile_sha256=selected_profile_sha256,
            )
            if mapping_repository is not None and selected_profile_sha256
            else None
        )
        active_mapping = None
        if mapping_activation_service is not None:
            try:
                active_mapping = mapping_activation_service.get_active_mapping(
                    canonical_id,
                    validate_source=False,
                ).to_dict()
            except MonitoringMappingActivationNotFoundError:
                pass
        return {
            "project_id": canonical_id,
            "batch_id": batch_id,
            "profile_sha256": selected_profile_sha256,
            "input_sha256": full_input_sha256,
            "field_count": full_field_count,
            "job_count": len(job_details),
            "job_details": job_details,
            "draft": (
                draft.model_dump(mode="json")
                if draft is not None
                else None
            ),
            "semantic_quality": (
                mapping_repository.semantic_quality(
                    canonical_id,
                    draft.draft_id,
                ).as_payload()
                if mapping_repository is not None and draft is not None
                else None
            ),
            "active_mapping": active_mapping,
        }

    @router.post("/field-mapping-jobs", status_code=202)
    def start_field_mapping(
        project_id: str,
        request: FieldMappingStartRequest,
        http_request: Request,
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=f"ai-field-mapping-start:{canonical_id}:{request.batch_id}",
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
        )
        try:
            if request.retry_failed:
                repository.expire_exhausted_leases(project_id=canonical_id)
            identity_loader = getattr(
                batch_repository,
                "load_field_profile_cache_identity",
                None,
            )
            identity = (
                identity_loader(request.batch_id)
                if callable(identity_loader)
                else None
            )
            if identity is not None:
                if identity.project_id != canonical_id:
                    raise MonitoringBatchRepositoryError(
                        "monitoring batch not found for project"
                    )
                snapshot = profiler.profile_batch(request.batch_id)
                current_identity = identity_loader(request.batch_id)
                if current_identity.identity_sha256 != identity.identity_sha256:
                    raise MonitoringBatchRepositoryError(
                        "monitoring batch identity changed during field profiling"
                    )
                identity = current_identity
                revision = _preferred_field_mapping_revision(
                    repository,
                    identity,
                    full_profile_sha256=snapshot.profile_sha256,
                    full_input_sha256=snapshot.input_sha256,
                )
            else:
                batch = batch_repository.load_profile_ready_batch(
                    request.batch_id
                )
                if batch.project_id != canonical_id:
                    raise MonitoringBatchRepositoryError(
                        "monitoring batch not found for project"
                    )
                snapshot = profiler.profile_loaded_batch(batch)
                revision = monitoring_input_revision_for_batch(batch)
            if snapshot.project_id != canonical_id:
                raise MonitoringBatchRepositoryError(
                    "monitoring batch not found for project"
                )
            jobs = service.submit_listing_field_mapping_chunks(
                project_id=canonical_id,
                input_revision=revision,
                field_profile=snapshot.to_ai_payload(),
                chunk_size=request.chunk_size,
            )
            if request.retry_failed:
                retried_jobs = []
                for job in jobs:
                    if job.status.value not in {
                        "failed",
                        "blocked",
                        "stale_input",
                    }:
                        retried_jobs.append(job)
                        continue
                    retried_jobs.append(
                        repository.retry_terminal(
                            canonical_id,
                            job.job_id,
                            current_input_revision_sha256=(
                                current_monitoring_ai_revision(
                                    repository,
                                    batch_repository,
                                    job,
                                )
                            ),
                        )
                    )
                jobs = tuple(retried_jobs)
            worker_wake()
            return {
                "project_id": canonical_id,
                "batch_id": request.batch_id,
                "profile_sha256": snapshot.profile_sha256,
                "input_sha256": snapshot.input_sha256,
                "field_count": len(snapshot.fields),
                "job_count": len(jobs),
                "jobs": [_public_job(job) for job in jobs],
            }
        except MonitoringBatchRepositoryError as exc:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "monitoring_ai_batch_unavailable",
                    "message": str(exc),
                },
            ) from exc
        except (MonitoringAiRepositoryError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_ai_field_mapping_not_started",
                    "message": str(exc),
                },
            ) from exc

    @router.post("/semantic-jobs", status_code=202)
    def start_semantic_job(
        project_id: str,
        request: SemanticTaskStartRequest,
        http_request: Request,
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=f"ai-semantic-start:{canonical_id}:{request.business_key}",
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
        )
        if source_packet_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_ai_source_resolver_unavailable",
                    "message": "医学监查 AI 来源解析器当前不可用。",
                },
            )
        try:
            packet = source_packet_resolver(canonical_id, request.source_ids)
            job = service.submit_task(
                project_id=canonical_id,
                task_type=request.task_type,
                input_revision=packet.input_revision,
                input_payload={
                    "context": request.context,
                    "source_ids": list(packet.source_ids),
                    "evidence_packet": [
                        dict(item) for item in packet.evidence_packet
                    ],
                },
                business_key=request.business_key,
                max_attempts=request.max_attempts,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "monitoring_ai_source_evidence_invalid",
                    "message": str(exc),
                },
            ) from exc
        worker_wake()
        return _public_job(job)

    @router.post("/risk-jobs", status_code=202)
    def start_risk_job(
        project_id: str,
        request: RiskSemanticTaskStartRequest,
        http_request: Request,
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=(
                f"ai-risk-start:{canonical_id}:{request.risk_instance_id}:"
                f"{request.business_key}"
            ),
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
        )
        if risk_packet_resolver is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "monitoring_ai_risk_resolver_unavailable",
                    "message": "医学监查 AI 当前风险证据解析器不可用。",
                },
            )
        try:
            packet = risk_packet_resolver(
                canonical_id,
                request.risk_instance_id,
            )
            job = service.submit_task(
                project_id=canonical_id,
                task_type=request.task_type,
                input_revision=packet.input_revision,
                input_payload={
                    "context": {
                        "risk": dict(packet.risk_context),
                        "request": request.context,
                    },
                    "risk_instance_id": packet.risk_instance_id,
                    "evidence_packet": [
                        dict(item) for item in packet.evidence_packet
                    ],
                },
                business_key=request.business_key,
                max_attempts=request.max_attempts,
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_ai_current_risk_unavailable",
                    "message": str(exc),
                },
            ) from exc
        worker_wake()
        return _public_job(job)

    @router.get("/jobs")
    def list_jobs(
        project_id: str,
        http_request: Request,
        task_type: Optional[MonitoringAiTaskType] = None,
        business_key_prefix: str = "",
    ):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=f"ai-jobs-list:{canonical_id}:{business_key_prefix}",
            action=MonitoringAction.READ_AI_RUN,
            require_write=False,
        )
        jobs = repository.list_jobs(
            canonical_id,
            task_type=task_type.value if task_type is not None else "",
            business_key_prefix=business_key_prefix,
        )
        return {
            "project_id": canonical_id,
            "items": [_public_job(job) for job in jobs],
        }

    @router.get("/jobs/{job_id}")
    def get_job(project_id: str, job_id: str, http_request: Request):
        canonical_id = project_resolver(project_id)
        authorize_route(
            http_request,
            canonical_id,
            request_id=f"ai-job-read:{canonical_id}:{job_id}",
            action=MonitoringAction.READ_AI_RUN,
            require_write=False,
        )
        try:
            job = repository.get(canonical_id, job_id)
        except MonitoringAiRepositoryError as exc:
            raise _not_found() from exc
        return {
            "job": _public_job(job),
            "candidates": [
                _public_candidate(candidate)
                for candidate in repository.candidates(canonical_id, job_id)
            ],
        }

    @router.post("/jobs/{job_id}/deterministic-repair")
    def repair_v7_deterministic_mapping(
        project_id: str,
        job_id: str,
        request: DeterministicV7RepairRequest,
        http_request: Request,
    ):
        canonical_id = project_resolver(project_id)
        actor = authorize_route(
            http_request,
            canonical_id,
            request_id=request.idempotency_key,
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
            legacy_actor=request.actor,
        )
        try:
            job = repository.get(canonical_id, job_id)
            payload = repository.input_payload(canonical_id, job_id)
            profile = payload.get("field_profile")
            if not isinstance(profile, dict):
                raise MonitoringAiStateConflictError(
                    "deterministic repair requires a field profile"
                )
            if (
                str(profile.get("batch_id", "")).strip()
                != request.expected_batch_id.strip()
            ):
                raise MonitoringAiStateConflictError(
                    "deterministic repair batch identity does not match the job"
                )
            identity_loader = getattr(
                batch_repository,
                "load_field_profile_cache_identity",
                None,
            )
            identity = (
                identity_loader(request.expected_batch_id)
                if callable(identity_loader)
                else None
            )
            if identity is not None:
                if identity.project_id != canonical_id:
                    raise MonitoringAiStateConflictError(
                        "deterministic repair batch belongs to another project"
                    )
                snapshot = profiler.profile_batch(request.expected_batch_id)
                current_identity = identity_loader(
                    request.expected_batch_id
                )
                if current_identity.identity_sha256 != identity.identity_sha256:
                    raise MonitoringAiStateConflictError(
                        "deterministic repair batch identity changed during "
                        "field profiling"
                    )
                identity = current_identity
                base_revision = monitoring_input_revision_for_profile_identity(
                    identity,
                    include_binding_identity=bool(
                        job.input_revision.source_binding_revision
                    ),
                )
            else:
                batch = batch_repository.load_profile_ready_batch(
                    request.expected_batch_id
                )
                if batch.project_id != canonical_id:
                    raise MonitoringAiStateConflictError(
                        "deterministic repair batch belongs to another project"
                    )
                snapshot = profiler.profile_loaded_batch(batch)
                base_revision = monitoring_input_revision_for_batch(batch)
            if snapshot.project_id != canonical_id:
                raise MonitoringAiStateConflictError(
                    "deterministic repair batch belongs to another project"
                )
            current_revision = monitoring_revision_with_field_profile(
                base_revision,
                snapshot.profile_sha256,
            ).revision_sha256
            if (
                request.expected_input_revision_sha256
                != current_revision
                or request.expected_full_profile_sha256
                != snapshot.profile_sha256
            ):
                raise MonitoringAiStateConflictError(
                    "deterministic repair request does not match the current "
                    "batch and field profile"
                )
            result = service.repair_failed_v7_deterministic_mapping(
                project_id=canonical_id,
                job_id=job.job_id,
                expected_batch_id=request.expected_batch_id,
                expected_input_revision_sha256=(
                    request.expected_input_revision_sha256
                ),
                expected_full_profile_sha256=(
                    request.expected_full_profile_sha256
                ),
                actor=actor,
                reason=request.reason,
                idempotency_key=request.idempotency_key,
            )
            return {
                "job": _public_job(result.job),
                "candidate": _public_candidate(result.candidate),
                "repair": result.repair,
            }
        except MonitoringBatchRepositoryError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_ai_deterministic_repair_conflict",
                    "message": str(exc),
                },
            ) from exc
        except MonitoringAiStateConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_ai_deterministic_repair_conflict",
                    "message": str(exc),
                },
            ) from exc
        except MonitoringAiRepositoryError as exc:
            raise _not_found() from exc

    @router.post("/candidates/{candidate_id}/decision")
    def decide_candidate(
        project_id: str,
        candidate_id: str,
        request: CandidateDecisionRequest,
        http_request: Request,
    ):
        canonical_id = project_resolver(project_id)
        actor = authorize_route(
            http_request,
            canonical_id,
            request_id=f"ai-candidate-decision:{canonical_id}:{candidate_id}",
            action=MonitoringAction.REVIEW_AI_CANDIDATE,
            require_write=True,
            legacy_actor=request.actor,
        )
        if request.decision not in {
            MonitoringAiCandidateStatus.ACCEPTED,
            MonitoringAiCandidateStatus.REJECTED,
        }:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "monitoring_ai_candidate_decision_invalid",
                    "message": "候选只能接受或驳回。",
                },
            )
        try:
            candidate_job = repository.job_for_candidate(
                canonical_id,
                candidate_id,
            )
            candidate = next(
                (
                    item
                    for item in repository.candidates(
                        canonical_id,
                        candidate_job.job_id,
                    )
                    if item.candidate_id == candidate_id
                ),
                None,
            )
            if (
                request.decision == MonitoringAiCandidateStatus.ACCEPTED
                and candidate is not None
                and candidate.status == MonitoringAiCandidateStatus.PROPOSED
                and candidate_confidence_summary(candidate)[
                    "requires_additional_evidence"
                ]
                and not request.reason.strip()
            ):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "monitoring_ai_low_confidence_confirmation_required",
                        "message": "该候选低于工作台置信度阈值；接受前请补充原文核对、数据缺口或医学确认理由。",
                    },
                )
            current_revision = _current_revision_for_job(
                repository,
                batch_repository,
                candidate_job,
            )
            candidate = repository.decide_candidate(
                canonical_id,
                candidate_id,
                decision=request.decision,
                actor=actor,
                reason=request.reason,
                current_input_revision_sha256=current_revision,
            )
            return _public_candidate(candidate)
        except MonitoringAiStateConflictError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "monitoring_ai_candidate_stale",
                    "message": str(exc),
                },
            ) from exc
        except MonitoringAiRepositoryError as exc:
            raise _not_found() from exc

    if mapping_repository is not None:

        def _mapping_draft_payload(draft):
            payload = draft.model_dump(mode="json")
            payload["semantic_quality"] = mapping_repository.semantic_quality(
                draft.project_id,
                draft.draft_id,
            ).as_payload()
            return payload

        @router.post("/field-mapping-runs/adopt", status_code=201)
        def adopt_field_mapping_run(
            project_id: str,
            request: MappingRunAdoptRequest,
            http_request: Request,
        ):
            canonical_id = project_resolver(project_id)
            actor = authorize_route(
                http_request,
                canonical_id,
                request_id=f"ai-field-mapping-adopt:{canonical_id}:{request.batch_id}",
                action=MonitoringAction.REVIEW_AI_CANDIDATE,
                require_write=True,
                legacy_actor=request.actor,
            )
            current_prompt = PROMPT_VERSION_BY_TASK[
                MonitoringAiTaskType.LISTING_FIELD_MAPPING
            ]
            matching_jobs = []
            for job in repository.list_jobs(
                canonical_id,
                task_type=MonitoringAiTaskType.LISTING_FIELD_MAPPING.value,
                business_key_prefix=(
                    f"listing-field-mapping:{request.batch_id}:"
                ),
            ):
                payload = repository.input_payload(canonical_id, job.job_id)
                profile = payload.get("field_profile", {})
                if (
                    job.prompt_version == current_prompt
                    and profile.get("full_profile_sha256")
                    == request.full_profile_sha256
                ):
                    matching_jobs.append(job)
            if not matching_jobs or any(
                job.status.value != "completed" for job in matching_jobs
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "monitoring_mapping_run_incomplete",
                        "message": "字段识别尚未完整完成，请只重试失败部分。",
                    },
                )
            try:
                for job in matching_jobs:
                    candidates = repository.candidates(
                        canonical_id,
                        job.job_id,
                    )
                    if len(candidates) != 1:
                        raise MonitoringAiStateConflictError(
                            "field mapping chunk must have exactly one candidate"
                        )
                    candidate = candidates[0]
                    if candidate.status == MonitoringAiCandidateStatus.PROPOSED:
                        repository.decide_candidate(
                            canonical_id,
                            candidate.candidate_id,
                            decision=MonitoringAiCandidateStatus.ACCEPTED,
                            actor=actor,
                            reason=request.reason,
                            current_input_revision_sha256=(
                                current_monitoring_ai_revision(
                                    repository,
                                    batch_repository,
                                    job,
                                )
                            ),
                        )
                    elif (
                        candidate.status
                        != MonitoringAiCandidateStatus.ACCEPTED
                    ):
                        raise MonitoringAiStateConflictError(
                            "field mapping candidate is rejected or stale"
                        )
                draft = mapping_repository.assemble(
                    canonical_id,
                    request.batch_id,
                    request.full_profile_sha256,
                    prompt_version=current_prompt,
                )
                return _mapping_draft_payload(draft)
            except MonitoringAiStateConflictError as exc:
                raise _mapping_conflict(exc) from exc
            except MonitoringMappingStateConflictError as exc:
                raise _mapping_conflict(exc) from exc
            except MonitoringMappingDraftError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "monitoring_mapping_draft_incomplete",
                        "message": str(exc),
                    },
                ) from exc

        @router.post("/mapping-drafts/assemble", status_code=201)
        def assemble_mapping_draft(
            project_id: str,
            request: MappingDraftAssembleRequest,
            http_request: Request,
        ):
            canonical_id = project_resolver(project_id)
            authorize_route(
                http_request,
                canonical_id,
                request_id=(
                    f"ai-mapping-draft-assemble:{canonical_id}:"
                    f"{request.batch_id}"
                ),
                action=MonitoringAction.REVIEW_AI_CANDIDATE,
                require_write=True,
            )
            try:
                draft = mapping_repository.assemble(
                    canonical_id,
                    request.batch_id,
                    request.full_profile_sha256,
                    prompt_version=PROMPT_VERSION_BY_TASK[
                        MonitoringAiTaskType.LISTING_FIELD_MAPPING
                    ],
                )
                return _mapping_draft_payload(draft)
            except MonitoringMappingStateConflictError as exc:
                raise _mapping_conflict(exc) from exc
            except MonitoringMappingDraftError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "monitoring_mapping_draft_incomplete",
                        "message": str(exc),
                    },
                ) from exc

        @router.get("/mapping-drafts/{draft_id}")
        def get_mapping_draft(
            project_id: str,
            draft_id: str,
            http_request: Request,
        ):
            canonical_id = project_resolver(project_id)
            authorize_route(
                http_request,
                canonical_id,
                request_id=f"ai-mapping-draft-read:{canonical_id}:{draft_id}",
                action=MonitoringAction.READ_AI_ARTIFACT,
                require_write=False,
            )
            try:
                draft = mapping_repository.get_draft(
                    canonical_id,
                    draft_id,
                )
                return _mapping_draft_payload(draft)
            except MonitoringMappingNotFoundError as exc:
                raise _mapping_not_found() from exc

        @router.patch("/mapping-drafts/{draft_id}/field")
        def edit_mapping_draft_field(
            project_id: str,
            draft_id: str,
            request: MappingDraftFieldEditRequest,
            http_request: Request,
        ):
            canonical_id = project_resolver(project_id)
            actor = authorize_route(
                http_request,
                canonical_id,
                request_id=request.idempotency_key,
                action=MonitoringAction.REVIEW_AI_CANDIDATE,
                require_write=True,
                legacy_actor=request.actor,
            )
            try:
                draft = mapping_repository.edit_field(
                    canonical_id,
                    draft_id,
                    domain=request.domain,
                    source_field=request.source_field,
                    patch=request.patch,
                    expected_version=request.expected_version,
                    actor=actor,
                    idempotency_key=request.idempotency_key,
                )
                return _mapping_draft_payload(draft)
            except MonitoringMappingNotFoundError as exc:
                raise _mapping_not_found() from exc
            except MonitoringMappingStateConflictError as exc:
                raise _mapping_conflict(exc) from exc
            except (MonitoringMappingDraftError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "monitoring_mapping_field_edit_invalid",
                        "message": str(exc),
                    },
                ) from exc

        @router.post("/mapping-drafts/{draft_id}/confirm")
        def confirm_mapping_draft(
            project_id: str,
            draft_id: str,
            request: MappingDraftConfirmRequest,
            http_request: Request,
        ):
            canonical_id = project_resolver(project_id)
            actor = authorize_route(
                http_request,
                canonical_id,
                request_id=request.idempotency_key,
                action=MonitoringAction.REVIEW_AI_CANDIDATE,
                require_write=True,
                legacy_actor=request.confirmed_by,
            )
            try:
                revision = mapping_repository.confirm(
                    canonical_id,
                    draft_id,
                    expected_version=request.expected_version,
                    confirmed_by=actor,
                    confirmation_reason=request.confirmation_reason,
                    idempotency_key=request.idempotency_key,
                )
                payload = revision.model_dump(mode="json")
                if mapping_activation_service is not None:
                    expected_project_version = request.expected_project_version
                    if expected_project_version is None:
                        try:
                            expected_project_version = (
                                mapping_activation_service.get_active_mapping(
                                    canonical_id,
                                    validate_source=False,
                                ).project_version
                            )
                        except MonitoringMappingActivationNotFoundError:
                            expected_project_version = 0
                    activation = (
                        mapping_activation_service.activate_confirmed_revision(
                            canonical_id,
                            revision.mapping_revision,
                            expected_project_version=expected_project_version,
                            activated_by=actor,
                            activation_reason=request.confirmation_reason,
                            idempotency_key=(
                                f"activate-{revision.mapping_revision[-16:]}-"
                                f"{request.idempotency_key[-48:]}"
                            ),
                        )
                    )
                    payload["activation"] = activation.to_dict()
                return payload
            except MonitoringMappingNotFoundError as exc:
                raise _mapping_not_found() from exc
            except (
                MonitoringMappingActivationConflictError,
                MonitoringMappingActivationSourceError,
            ) as exc:
                raise _mapping_conflict(exc) from exc
            except MonitoringMappingStateConflictError as exc:
                raise _mapping_conflict(exc) from exc
            except (MonitoringMappingDraftError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "monitoring_mapping_confirmation_invalid",
                        "message": str(exc),
                    },
                ) from exc

        @router.get("/mapping-revisions/{mapping_revision}")
        def get_mapping_revision(
            project_id: str,
            mapping_revision: str,
            http_request: Request,
        ):
            canonical_id = project_resolver(project_id)
            authorize_route(
                http_request,
                canonical_id,
                request_id=f"ai-mapping-revision-read:{canonical_id}:{mapping_revision}",
                action=MonitoringAction.READ_AI_ARTIFACT,
                require_write=False,
            )
            try:
                return mapping_repository.get_revision(
                    canonical_id,
                    mapping_revision,
                ).model_dump(mode="json")
            except MonitoringMappingNotFoundError as exc:
                raise _mapping_not_found() from exc

        if mapping_activation_service is not None:

            @router.get("/active-mapping")
            def get_active_mapping(project_id: str, http_request: Request):
                canonical_id = project_resolver(project_id)
                authorize_route(
                    http_request,
                    canonical_id,
                    request_id=f"ai-active-mapping-read:{canonical_id}",
                    action=MonitoringAction.READ_AI_ARTIFACT,
                    require_write=False,
                )
                try:
                    return mapping_activation_service.get_active_mapping(
                        canonical_id,
                    ).to_dict()
                except MonitoringMappingActivationNotFoundError as exc:
                    raise _mapping_not_found() from exc
                except MonitoringMappingActivationSourceError as exc:
                    raise _mapping_conflict(exc) from exc

    return router


def current_monitoring_ai_revision(
    repository: MonitoringAiRepository,
    batch_repository: MonitoringBatchRepository,
    job: Any,
) -> str:
    return _current_revision_for_job(repository, batch_repository, job)


def _current_revision_for_job(
    repository: MonitoringAiRepository,
    batch_repository: MonitoringBatchRepository,
    job: Any,
) -> str:
    if job.task_type != MonitoringAiTaskType.LISTING_FIELD_MAPPING:
        return job.input_revision_sha256
    payload = repository.input_payload(job.project_id, job.job_id)
    field_profile = payload.get("field_profile")
    if not isinstance(field_profile, dict):
        return ""
    batch_id = field_profile.get("batch_id")
    if not isinstance(batch_id, str) or not batch_id.strip():
        return ""
    batch_id = batch_id.strip()
    try:
        profile_sha256 = _require_router_sha256(
            field_profile.get("profile_sha256"),
            "field_profile.profile_sha256",
        )
    except ValueError:
        return ""
    try:
        identity_loader = getattr(
            batch_repository,
            "load_field_profile_cache_identity",
            None,
        )
        identity = identity_loader(batch_id) if callable(identity_loader) else None
    except MonitoringBatchRepositoryError:
        return ""
    if identity is not None:
        if identity.project_id != job.project_id:
            return ""
        base_revision = monitoring_input_revision_for_profile_identity(
            identity,
            include_binding_identity=bool(
                job.input_revision.source_binding_revision
            ),
        )
    else:
        try:
            batch = batch_repository.load_profile_ready_batch(batch_id)
        except MonitoringBatchRepositoryError:
            return ""
        if batch.project_id != job.project_id:
            return ""
        base_revision = monitoring_input_revision_for_batch(batch)
    try:
        return monitoring_revision_with_field_profile(
            base_revision,
            profile_sha256,
        ).revision_sha256
    except ValueError:
        return ""


def _public_job(job: Any) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "task_type": job.task_type.value,
        "status": job.status.value,
        "business_key": job.business_key,
        "input_revision_sha256": job.input_revision_sha256,
        "prompt_version": job.prompt_version,
        "provider": job.provider,
        "requested_model": job.requested_model,
        "response_model": job.response_model,
        "attempt_count": job.attempt_count,
        "failure_code": job.failure_code,
        "failure_message": job.failure_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


def _public_candidate(candidate: Any) -> dict[str, Any]:
    payload = candidate.model_dump(mode="json")
    payload["confidence_summary"] = candidate_confidence_summary(candidate)
    return payload


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "monitoring_ai_record_not_found",
            "message": "未找到该医学监查 AI 记录。",
        },
    )


def _mapping_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "monitoring_mapping_record_not_found",
            "message": "未找到该字段映射记录。",
        },
    )


def _mapping_conflict(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "monitoring_mapping_state_conflict",
            "message": str(exc),
        },
    )
