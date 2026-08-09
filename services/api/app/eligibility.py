from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query, Response

from packages.contracts.workbench_contracts import (
    EligibilityEvidenceArtifactSummary,
    EligibilityEvidenceJob,
    EligibilityEvidenceJobCancelRequest,
    EligibilityEvidenceJobCreateRequest,
    EligibilityEvidenceJobCreateResult,
    EligibilityEvidenceVisualQcRequest,
    EligibilityEvidenceVisualQcResponse,
    EligibilityReviewActionRequest as EligibilityReviewActionRequestContract,
    EligibilityReviewActionResult as EligibilityReviewActionResultContract,
    EligibilityReviewState as EligibilityReviewStateContract,
    EligibilitySubjectAggregate as EligibilitySubjectAggregateContract,
)

from .ai_task_runner import AiTaskRunner
from .enrollment_adapter import EnrollmentReviewAdapter
from .eligibility_ai_packet import (
    EligibilityAiCurrentContext,
    EligibilityAiPacketBuilder,
)
from .eligibility_ai_review import EligibilityAiBatchService, EligibilityAiCriterion
from .eligibility_artifact_store import (
    EligibilityArtifactStore,
    EligibilityArtifactStoreError,
)
from .eligibility_protocol_rules import (
    EligibilityProtocolRuleService,
    eligibility_criterion_text_hash,
)
from .eligibility_raw_intake import EligibilityRawProjectIntakeService, RawEligibilityProjectConfig
from .eligibility_review_workflow import (
    CriterionKind,
    EligibilityDecision,
    EligibilityReviewAction,
    EligibilityReviewRequest,
    EligibilityReviewWorkflow,
    EvidenceProcessingState,
)
from .eligibility_visual_qc_service import (
    EligibilityVisualQcPacketError,
    EligibilityVisualQcService,
)
from .eligibility_evidence_tasks import (
    EligibilityEvidenceTaskService,
    EvidenceSourceIdentity,
)
from .sqlite_runtime_store import (
    IdempotencyConflictError,
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


router = APIRouter(prefix="/api/projects/{project_id}/eligibility", tags=["eligibility"])
adapter = EnrollmentReviewAdapter()
raw_intake_service = EligibilityRawProjectIntakeService()
protocol_rule_service = EligibilityProtocolRuleService()
review_workflow: Optional[EligibilityReviewWorkflow] = None
eligibility_ai_packet_builder: Optional[EligibilityAiPacketBuilder] = None
eligibility_ai_batch_service: Optional[EligibilityAiBatchService] = None
eligibility_visual_qc_service: Optional[EligibilityVisualQcService] = None
eligibility_source_admission_guard: Optional[Callable[[str], Dict[str, Any]]] = None
D001_RAW_CONFIG = RawEligibilityProjectConfig(
    project_id="proj_d001",
    project_label="CMS-D001 银屑病",
    protocol_path=(
        "/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/"
        "CMS-D001 银屑病2、3期临床方案 v1.0-2025.12.21.docx"
    ),
    raw_subject_root="/Users/smkzw/Documents/康哲项目资料/AI/入排/test-D001项目/全量-入组",
)
MY009_RAW_CONFIG = RawEligibilityProjectConfig(
    project_id="proj_my009_uc",
    project_label="MY009 UC",
    protocol_path=(
        "/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/方案及配套资料/3.0/"
        "MY009-UC-Ⅱa期-临床研究方案-V3.0 20250926-clean (1).docx"
    ),
    raw_subject_root="/Users/smkzw/Documents/朗来项目资料/MY009治疗UC/EVF审核",
)
RAW_INTAKE_PROJECTS = {
    "proj_d001": D001_RAW_CONFIG,
    "d001_raw_intake": D001_RAW_CONFIG,
    "proj_d001_raw_intake": D001_RAW_CONFIG,
    "cms-d001": D001_RAW_CONFIG,
    "proj_my009_uc": MY009_RAW_CONFIG,
    "my009_uc": MY009_RAW_CONFIG,
    "my009_uc_raw_intake": MY009_RAW_CONFIG,
    "my009_uc_monitoring_raw": MY009_RAW_CONFIG,
}


def configure_protocol_rule_service(
    service: EligibilityProtocolRuleService,
) -> None:
    if service is None or not callable(
        getattr(service, "rules_for_project", None)
    ):
        raise TypeError(
            "eligibility protocol rule service must provide rules_for_project"
        )
    global protocol_rule_service
    protocol_rule_service = service


def configure_eligibility_review_workflow(store: SqliteRuntimeStore) -> None:
    global review_workflow, eligibility_ai_packet_builder, eligibility_ai_batch_service
    global eligibility_visual_qc_service
    review_workflow = EligibilityReviewWorkflow(store)
    eligibility_ai_packet_builder = None
    eligibility_ai_batch_service = None
    eligibility_visual_qc_service = None


def configure_eligibility_ai_workflow(
    runner: AiTaskRunner,
    artifact_store: EligibilityArtifactStore,
) -> None:
    global eligibility_ai_packet_builder, eligibility_ai_batch_service
    global eligibility_visual_qc_service
    workflow = _configured_review_workflow()
    eligibility_ai_packet_builder = EligibilityAiPacketBuilder(
        workflow.store,
        artifact_store,
        _current_ai_context,
    )
    eligibility_ai_batch_service = EligibilityAiBatchService(runner, workflow)
    eligibility_visual_qc_service = EligibilityVisualQcService(
        workflow.store,
        artifact_store,
    )


def configure_eligibility_source_admission_guard(
    guard: Optional[Callable[[str], Dict[str, Any]]],
) -> None:
    global eligibility_source_admission_guard
    eligibility_source_admission_guard = guard


def _require_eligibility_source_admission(project_id: str) -> Dict[str, Any]:
    if eligibility_source_admission_guard is None:
        return {"ready_for_use": True, "sources": []}
    state = eligibility_source_admission_guard(project_id)
    if not state.get("ready_for_use"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "eligibility_source_confirmation_required",
                "message": "当前研究方案或受试者资料包尚未完成内容核验确认",
                "source_admission": state,
            },
        )
    return state


def _configured_review_workflow() -> EligibilityReviewWorkflow:
    if review_workflow is None:
        raise RuntimeError("eligibility review workflow is not configured")
    return review_workflow


def _configured_visual_qc_service() -> EligibilityVisualQcService:
    if eligibility_visual_qc_service is None:
        raise RuntimeError("eligibility visual QC service is not configured")
    return eligibility_visual_qc_service


def _review_rule_rows(rule_set: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    display_order = 0
    for section in (rule_set.inclusion, rule_set.exclusion):
        for rule in section.rules:
            display_order += 1
            rows.append(
                {
                    "criterion_uid": rule.criterion_uid,
                    "criterion_kind": section.criterion_type,
                    "source_rule_label": rule.source_rule_label,
                    "source_locator": {
                        "source_entry": rule.source_entry,
                        "locator": rule.source_locator,
                    },
                    "normalized_text_hash": eligibility_criterion_text_hash(rule.text),
                    "display_order": display_order,
                }
            )
    return rows


def _review_source_rows(subject: Any) -> List[Dict[str, Any]]:
    return [
        {
            "source_id": source.source_id,
            "source_revision": source.source_revision,
            "content_hash": source.content_hash,
            "size_bytes": source.size_bytes,
            "media_class": source.source_type,
            "processing_unit_kind": source.unit_kind,
            "expected_unit_count": source.expected_unit_count,
            "expected_unit_count_status": source.expected_unit_count_status,
        }
        for source in subject.sources
    ]


def _sync_review_identity(
    project_id: str,
    subject_id: str,
) -> Tuple[EligibilityReviewWorkflow, Any, Any]:
    config = RAW_INTAKE_PROJECTS.get(project_id)
    if config is None:
        raise KeyError(f"raw eligibility project not configured: {project_id}")
    rule_set = protocol_rule_service.rules_for_project(config.project_id)
    subject = raw_intake_service.subject_manifest(config, subject_id)
    workflow = _configured_review_workflow()
    workflow.register_rule_revision(
        config.project_id,
        rule_set.rule_revision,
        _review_rule_rows(rule_set),
    )
    registered_source_revision = workflow.register_subject_sources(
        config.project_id,
        subject.subject_id,
        _review_source_rows(subject),
        subject_source_revision=subject.subject_source_revision,
    )
    if registered_source_revision != subject.subject_source_revision:
        raise RuntimeError("eligibility subject source revision registration mismatch")
    return workflow, rule_set, subject


def _current_ai_context(project_id: str, subject_id: str) -> EligibilityAiCurrentContext:
    _, rule_set, subject = _sync_review_identity(project_id, subject_id)
    criteria: List[EligibilityAiCriterion] = []
    display_order = 0
    for section, kind in (
        (rule_set.inclusion, CriterionKind.INCLUSION),
        (rule_set.exclusion, CriterionKind.EXCLUSION),
    ):
        for rule in section.rules:
            display_order += 1
            criteria.append(
                EligibilityAiCriterion(
                    criterion_uid=rule.criterion_uid,
                    criterion_kind=kind,
                    text=rule.text,
                    source_locator=rule.source_locator,
                    display_order=display_order,
                )
            )
    return EligibilityAiCurrentContext(
        project_id=subject.project_id,
        subject_id=subject.subject_id,
        subject_token=subject.subject_token,
        rule_revision=rule_set.rule_revision,
        subject_source_revision=subject.subject_source_revision,
        criteria=tuple(criteria),
    )


def _public_review_criteria(rule_set: Any, states: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    state_by_uid = {state["criterion_uid"]: state for state in states}
    criteria: List[Dict[str, Any]] = []
    for section in (rule_set.inclusion, rule_set.exclusion):
        for rule in section.rules:
            state = state_by_uid.get(rule.criterion_uid)
            criteria.append(
                {
                    "criterion_uid": rule.criterion_uid,
                    "criterion_kind": section.criterion_type,
                    "review_rule_id": rule.review_rule_id,
                    "source_rule_label": rule.source_rule_label,
                    "numbering_status": rule.numbering_status,
                    "text": rule.text,
                    "source_locator": rule.source_locator,
                    "children": [child.public_dict() for child in rule.children],
                    "state": (
                        EligibilityReviewStateContract.model_validate(state).model_dump(
                            mode="json"
                        )
                        if state is not None
                        else None
                    ),
                }
            )
    return criteria


@router.get("")
def get_project_eligibility(
    project_id: str,
    subject_id: Optional[str] = Query(None),
    phase_id: Optional[str] = Query(None),
    phase: Optional[str] = Query(None),
):
    try:
        dataset = adapter.eligibility_dataset(project_id, subject_id=subject_id, phase_id=phase_id or phase)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"eligibility project not found: {project_id}")
    return dataset.model_dump(mode="json")


@router.get("/raw-intake")
def get_project_raw_intake(project_id: str):
    config = RAW_INTAKE_PROJECTS.get(project_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"raw eligibility project not configured: {project_id}")
    try:
        snapshot = raw_intake_service.discover_project(config)
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="当前项目原始入排资料无法读取或结构不符合要求",
        )
    return snapshot.public_dict()


@router.get("/protocol-rules")
def get_project_protocol_rules(project_id: str):
    try:
        return protocol_rule_service.rules_for_project(project_id).public_dict()
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"eligibility protocol rules not configured: {project_id}",
        )
    except (FileNotFoundError, IsADirectoryError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="当前项目原始方案无法读取或入排标准结构不符合要求",
        )


@router.get("/raw-intake/subjects")
def get_project_raw_intake_subjects(project_id: str):
    config = RAW_INTAKE_PROJECTS.get(project_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"raw eligibility project not configured: {project_id}")
    try:
        subjects = raw_intake_service.subject_manifests(config)
    except (FileNotFoundError, NotADirectoryError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="当前项目候选受试者资料无法读取或结构不符合要求",
        )
    return {
        "project_id": config.project_id,
        "subject_count": len(subjects),
        "subjects": [subject.public_dict() for subject in subjects],
    }


@router.get("/raw-intake/subjects/{subject_id}")
def get_project_raw_intake_subject(project_id: str, subject_id: str):
    config = RAW_INTAKE_PROJECTS.get(project_id)
    if config is None:
        raise HTTPException(status_code=404, detail=f"raw eligibility project not configured: {project_id}")
    try:
        subject = raw_intake_service.subject_manifest(config, subject_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"eligibility subject not found: {subject_id}")
    except (FileNotFoundError, NotADirectoryError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="当前受试者原始资料无法读取或结构不符合要求",
        )
    return subject.public_dict(include_sources=True)


@router.get("/raw-intake/subjects/{subject_id}/review")
def get_project_subject_review(project_id: str, subject_id: str):
    try:
        workflow, rule_set, subject = _sync_review_identity(project_id, subject_id)
        states = workflow.store.eligibility_subject_review_states(
            subject.project_id, subject.subject_id
        )
        evidence = workflow.store.eligibility_subject_evidence_spans(
            subject.project_id, subject.subject_id
        )
        aggregate = workflow.aggregate_subject_review(
            subject.project_id, subject.subject_id
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="当前项目或受试者未配置")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="资格审核工作流尚未配置")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, ValueError, OSError):
        raise HTTPException(status_code=422, detail="当前资格审核原始资料无法完成版本同步")
    aggregate_payload = EligibilitySubjectAggregateContract.model_validate(
        {
            "project_id": aggregate.project_id,
            "subject_id": aggregate.subject_id,
            "rule_revision": aggregate.rule_revision,
            "criterion_count": aggregate.criterion_count,
            "reviewed_count": aggregate.reviewed_count,
            "statuses": list(aggregate.statuses),
        }
    ).model_dump(mode="json")
    return {
        "project_id": subject.project_id,
        "subject": subject.public_dict(include_sources=True),
        "rule_revision": rule_set.rule_revision,
        "subject_source_revision": subject.subject_source_revision,
        "aggregate": aggregate_payload,
        "evidence": evidence,
        "criteria": _public_review_criteria(rule_set, states),
    }


def _evidence_task_service_for_subject(project_id: str, subject_id: str):
    workflow, _, subject = _sync_review_identity(project_id, subject_id)
    service = EligibilityEvidenceTaskService(workflow.store)
    sources = [
        EvidenceSourceIdentity(
            source_id=source.source_id,
            source_revision=source.source_revision,
            media_class=source.source_type,
        )
        for source in subject.sources
    ]
    return service, subject, sources


@router.post(
    "/raw-intake/subjects/{subject_id}/evidence-jobs",
    response_model=EligibilityEvidenceJobCreateResult,
)
def create_project_subject_evidence_job(
    project_id: str,
    subject_id: str,
    request: EligibilityEvidenceJobCreateRequest,
):
    try:
        service, subject, sources = _evidence_task_service_for_subject(
            project_id, subject_id
        )
        return EligibilityEvidenceJobCreateResult.model_validate(
            service.create_job(
                project_id=subject.project_id,
                subject_id=subject.subject_id,
                subject_source_revision=subject.subject_source_revision,
                sources=sources,
                source_id=request.source_id,
                job_kind=request.job_kind.value,
                profile_version=request.profile_version,
                idempotency_key=request.idempotency_key,
                priority=request.priority,
                max_attempts=request.max_attempts,
            )
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="当前项目、受试者或资料未配置")
    except IdempotencyConflictError:
        raise HTTPException(status_code=409, detail="证据任务请求与既有版本冲突")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="资格审核证据任务尚未配置")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, OSError):
        raise HTTPException(status_code=422, detail="当前资格审核原始资料无法完成版本同步")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get(
    "/raw-intake/subjects/{subject_id}/evidence-jobs",
    response_model=List[EligibilityEvidenceJob],
)
def list_project_subject_evidence_jobs(project_id: str, subject_id: str):
    try:
        service, subject, _ = _evidence_task_service_for_subject(project_id, subject_id)
        return [
            EligibilityEvidenceJob.model_validate(job)
            for job in service.jobs_for_subject(subject.project_id, subject.subject_id)
        ]
    except KeyError:
        raise HTTPException(status_code=404, detail="当前项目或受试者未配置")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="资格审核证据任务尚未配置")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, OSError, ValueError):
        raise HTTPException(status_code=422, detail="当前资格审核原始资料无法完成版本同步")


@router.get(
    "/raw-intake/subjects/{subject_id}/evidence-jobs/{job_id}",
    response_model=EligibilityEvidenceJob,
)
def get_project_subject_evidence_job(
    project_id: str, subject_id: str, job_id: str
):
    try:
        service, subject, _ = _evidence_task_service_for_subject(project_id, subject_id)
        job = service.store.eligibility_evidence_job(subject.project_id, job_id)
        if job is None or job["subject_id"] != subject.subject_id:
            raise KeyError(job_id)
        return EligibilityEvidenceJob.model_validate(service.public_job(job))
    except KeyError:
        raise HTTPException(status_code=404, detail="当前证据任务不存在")


@router.get(
    "/raw-intake/subjects/{subject_id}/evidence-jobs/{job_id}/artifacts",
    response_model=List[EligibilityEvidenceArtifactSummary],
)
def get_project_subject_evidence_job_artifacts(
    project_id: str, subject_id: str, job_id: str
):
    job = get_project_subject_evidence_job(project_id, subject_id, job_id)
    service, _, _ = _evidence_task_service_for_subject(project_id, subject_id)
    return [
        EligibilityEvidenceArtifactSummary.model_validate(artifact)
        for artifact in service.public_artifacts(job.project_id, job_id)
    ]


@router.post(
    "/raw-intake/subjects/{subject_id}/evidence-jobs/{job_id}/cancel",
    response_model=EligibilityEvidenceJob,
)
def cancel_project_subject_evidence_job(
    project_id: str,
    subject_id: str,
    job_id: str,
    request: EligibilityEvidenceJobCancelRequest,
):
    job = get_project_subject_evidence_job(project_id, subject_id, job_id)
    try:
        service, _, _ = _evidence_task_service_for_subject(project_id, subject_id)
        return EligibilityEvidenceJob.model_validate(
            service.cancel_job(job.project_id, job_id, actor=request.actor)
        )
    except StaleRuntimeStateError:
        raise HTTPException(status_code=409, detail="当前证据任务状态不可取消")


@router.post(
    "/raw-intake/subjects/{subject_id}/evidence-spans/{evidence_id}/visual-qc-records",
    response_model=EligibilityEvidenceVisualQcResponse,
)
def commit_project_subject_evidence_visual_qc(
    project_id: str,
    subject_id: str,
    evidence_id: str,
    request: EligibilityEvidenceVisualQcRequest,
):
    try:
        workflow, _, subject = _sync_review_identity(project_id, subject_id)
        result = workflow.store.commit_eligibility_evidence_visual_qc(
            project_id=subject.project_id,
            subject_id=subject.subject_id,
            evidence_id=evidence_id,
            expected_qc_revision=request.expected_qc_revision,
            expected_source_revision=request.expected_source_revision,
            expected_extraction_revision=request.expected_extraction_revision,
            idempotency_key=request.idempotency_key,
            result=request.result.value,
            reason_code=request.reason_code,
            user_reason=request.user_reason,
            sample_plan_id=request.sample_plan_id,
            sample_unit=request.sample_unit,
            policy_version=request.policy_version,
            actor=request.actor,
        )
        if eligibility_visual_qc_service is not None:
            eligibility_visual_qc_service.reconcile_processing_unit(
                subject.project_id,
                subject.subject_id,
                evidence_id,
                qc_idempotency_key=request.idempotency_key,
                actor=request.actor,
            )
    except KeyError:
        raise HTTPException(status_code=404, detail="当前项目或受试者未配置")
    except (StaleRuntimeStateError, IdempotencyConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError:
        raise HTTPException(status_code=503, detail="资格审核工作流尚未配置")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, OSError):
        raise HTTPException(status_code=422, detail="当前资格审核原始资料无法完成版本同步")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return EligibilityEvidenceVisualQcResponse.model_validate(
        {
            "request_id": result.request_id,
            "qc_record_id": result.qc_record_id,
            "project_id": subject.project_id,
            "subject_id": subject.subject_id,
            "evidence_id": evidence_id,
            "source_revision": request.expected_source_revision,
            "extraction_revision": request.expected_extraction_revision,
            "qc_revision": result.qc_revision,
            "result": result.result,
            "actor": request.actor,
            "identity_assurance": "unverified_client_claim",
            "is_electronic_signature": False,
            "replayed": result.replayed,
        }
    )


@router.get("/raw-intake/subjects/{subject_id}/visual-qc-queue")
def get_project_subject_visual_qc_queue(
    project_id: str,
    subject_id: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    qc_status: str = Query(default="all"),
):
    try:
        _, _, subject = _sync_review_identity(project_id, subject_id)
        return _configured_visual_qc_service().queue(
            subject.project_id,
            subject.subject_id,
            offset=offset,
            limit=limit,
            result_filter=qc_status,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="当前项目或受试者未配置")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="视觉复核服务尚未配置")
    except (
        FileNotFoundError,
        NotADirectoryError,
        IsADirectoryError,
        OSError,
        ValueError,
        EligibilityArtifactStoreError,
        EligibilityVisualQcPacketError,
    ):
        raise HTTPException(status_code=409, detail="当前视觉复核证据包不完整")


@router.get(
    "/raw-intake/subjects/{subject_id}/visual-qc-artifacts/{artifact_id}/content"
)
def get_project_subject_visual_qc_image(
    project_id: str,
    subject_id: str,
    artifact_id: str,
):
    try:
        _, _, subject = _sync_review_identity(project_id, subject_id)
        image = _configured_visual_qc_service().image(
            subject.project_id,
            subject.subject_id,
            artifact_id,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="当前视觉复核图像不存在")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="视觉复核服务尚未配置")
    except (
        FileNotFoundError,
        NotADirectoryError,
        IsADirectoryError,
        OSError,
        ValueError,
        EligibilityArtifactStoreError,
        EligibilityVisualQcPacketError,
    ):
        raise HTTPException(status_code=409, detail="当前视觉复核图像完整性校验失败")
    return Response(
        content=image.body,
        media_type=image.media_type,
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post(
    "/raw-intake/subjects/{subject_id}/criteria/{criterion_uid}/actions",
    response_model=EligibilityReviewActionResultContract,
)
def commit_project_subject_review_action(
    project_id: str,
    subject_id: str,
    criterion_uid: str,
    request: EligibilityReviewActionRequestContract,
):
    _require_eligibility_source_admission(project_id)
    if request.action.value == EligibilityReviewAction.SAVE_AI_DRAFT.value:
        raise HTTPException(
            status_code=403,
            detail="AI审核草稿只允许由服务端独立AI工作流写入",
        )
    try:
        workflow, _, subject = _sync_review_identity(project_id, subject_id)
        result = workflow.apply_action(
            EligibilityReviewRequest(
                project_id=subject.project_id,
                subject_id=subject.subject_id,
                criterion_uid=criterion_uid,
                criterion_kind=CriterionKind(request.criterion_kind.value),
                expected_state_revision=request.expected_state_revision,
                expected_rule_revision=request.expected_rule_revision,
                expected_subject_source_revision=(
                    request.expected_subject_source_revision
                ),
                idempotency_key=request.idempotency_key,
                actor=f"unverified_client:{request.actor}",
                action=EligibilityReviewAction(request.action.value),
                decision=(
                    EligibilityDecision(request.decision.value)
                    if request.decision is not None
                    else None
                ),
                reason=request.reason,
                evidence_ids=tuple(request.evidence_ids),
                evidence_processing_state=EvidenceProcessingState(
                    request.evidence_processing_state.value
                ),
            )
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="当前项目或受试者未配置")
    except (StaleRuntimeStateError, IdempotencyConflictError):
        raise HTTPException(status_code=409, detail="审阅状态或来源版本已更新，请刷新后重试")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="资格审核工作流尚未配置")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, OSError):
        raise HTTPException(status_code=422, detail="当前资格审核原始资料无法完成版本同步")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return EligibilityReviewActionResultContract.model_validate(
        {
            "request_id": result.request_id,
            "record_id": result.record_id,
            "state_revision": result.state_revision,
            "replayed": result.replayed,
            "state": result.state,
        }
    )


@router.post("/raw-intake/subjects/{subject_id}/ai-drafts")
def run_project_subject_ai_drafts(project_id: str, subject_id: str):
    _require_eligibility_source_admission(project_id)
    if eligibility_ai_packet_builder is None or eligibility_ai_batch_service is None:
        raise HTTPException(status_code=503, detail="资格审核AI工作流尚未配置")
    try:
        packet = eligibility_ai_packet_builder.build(project_id, subject_id)
        result = eligibility_ai_batch_service.run_packet(packet)
    except KeyError:
        raise HTTPException(status_code=404, detail="当前项目或受试者未配置")
    except StaleRuntimeStateError:
        raise HTTPException(status_code=409, detail="方案或受试者证据版本已更新")
    except (RuntimeStoreError, EligibilityArtifactStoreError):
        raise HTTPException(status_code=409, detail="受控证据完整性校验未通过")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "project_id": result.project_id,
        "subject_id": result.subject_id,
        "rule_revision": result.rule_revision,
        "subject_source_revision": result.subject_source_revision,
        "packet_digest": packet.packet_digest,
        "needs_medical_confirmation": True,
        "batches": [
            {
                "batch_id": batch.batch_id,
                "criterion_kind": batch.criterion_kind,
                "criterion_uids": list(batch.criterion_uids),
                "run_id": batch.run_id,
                "status": batch.status,
                "drafts_persisted": batch.drafts_persisted,
                "validation_errors": list(batch.validation_errors),
            }
            for batch in result.batches
        ],
    }
