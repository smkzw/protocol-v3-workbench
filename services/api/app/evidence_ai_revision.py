from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha1
from typing import Dict, List, Sequence
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    AiTaskRequest,
    AiTaskRun,
    AiTaskRunStatus,
    AiTaskSourceRef,
    AuditEvent,
    EvidenceAiRevisionAction,
    EvidenceAiRevisionActionRequest,
    EvidenceAiRevisionProposal,
    EvidenceAiRevisionRequest,
    EvidenceAiRevisionResult,
    EvidenceAiRevisionThread,
    EvidencePicosWorkflowStep,
)

from .ai_task_runner import AiTaskRunner
from .evidence_design_manifest import EvidenceDesignManifestService
from .evidence_picos_workflow import EvidencePicosWorkflowService
from .sqlite_runtime_store import SqliteRuntimeStore


class EvidenceAiRevisionService:
    def __init__(
        self,
        manifest_service: EvidenceDesignManifestService,
        picos_workflow_service: EvidencePicosWorkflowService,
        ai_task_runner: AiTaskRunner,
        runtime_store: SqliteRuntimeStore,
    ):
        self.manifest_service = manifest_service
        self.picos_workflow_service = picos_workflow_service
        self.ai_task_runner = ai_task_runner
        self.runtime_store = runtime_store

    def submit(
        self,
        project_id: str,
        package_id: str,
        request: EvidenceAiRevisionRequest,
    ) -> EvidenceAiRevisionResult:
        if not isinstance(request, EvidenceAiRevisionRequest):
            request = EvidenceAiRevisionRequest.model_validate(request)
        if request.anchor_type != "picos_question":
            raise ValueError("当前AI建议修订仅支持锚定到PICOS问题。")
        workflow = self.picos_workflow_service.workflow(project_id, package_id)
        self._check_source_revision(workflow.revision, workflow.evidence_package_hash, request)
        step = self._step(workflow.steps, request.anchor_id)
        run = self._run_ai(
            project_id,
            package_id,
            step,
            request.user_instruction,
            request.source_evidence_ids,
        )
        proposal = self._proposal(run, step, sequence=1)
        created_at = datetime.now(timezone.utc)
        thread = EvidenceAiRevisionThread(
            thread_id=f"evidence_ai_thread_{uuid4().hex}",
            project_id=project_id,
            package_id=package_id,
            anchor_type=request.anchor_type,
            anchor_id=request.anchor_id,
            base_picos_revision=workflow.revision,
            evidence_package_hash=workflow.evidence_package_hash,
            revision=1,
            status="pending_medical_action",
            user_instruction=request.user_instruction.strip(),
            source_evidence_ids=list(dict.fromkeys(request.source_evidence_ids)),
            proposals=[proposal],
            created_by=request.actor,
            created_at=created_at,
            updated_at=created_at,
        )
        audit_event = self._audit(
            project_id,
            request.actor,
            "submit_ai_revision",
            thread.thread_id,
            {
                "package_id": package_id,
                "anchor_type": request.anchor_type,
                "anchor_id": request.anchor_id,
                "base_picos_revision": workflow.revision,
                "evidence_package_hash": workflow.evidence_package_hash,
                "ai_run_id": run.run_id,
                "proposal_id": proposal.proposal_id,
            },
            created_at,
        )
        fingerprint = _fingerprint(thread.model_dump(mode="json"))
        self.runtime_store.commit_evidence_ai_revision_submission(
            thread,
            audit_event,
            idempotency_key=request.idempotency_key or f"evidence-ai-submit:{thread.thread_id}",
            request_fingerprint=fingerprint,
        )
        return self._result(thread, proposal)

    def apply_action(
        self,
        project_id: str,
        thread_id: str,
        request: EvidenceAiRevisionActionRequest,
    ) -> EvidenceAiRevisionResult:
        if not isinstance(request, EvidenceAiRevisionActionRequest):
            request = EvidenceAiRevisionActionRequest.model_validate(request)
        previous = self.runtime_store.evidence_ai_revision_thread(project_id, thread_id)
        if previous.revision != request.expected_thread_revision:
            raise ValueError(
                f"AI建议线程已更新：expected={request.expected_thread_revision}, actual={previous.revision}"
            )
        target = next((item for item in previous.proposals if item.proposal_id == request.proposal_id), None)
        if target is None:
            raise KeyError(f"AI建议不存在：{request.proposal_id}")
        if target.user_decision != "pending":
            raise ValueError(f"AI建议已处理：{target.user_decision}")

        updated = previous.model_copy(deep=True)
        target_updated = next(item for item in updated.proposals if item.proposal_id == request.proposal_id)
        result_proposal = target_updated
        if request.action == EvidenceAiRevisionAction.ACCEPT:
            target_updated.user_decision = "accepted"
            updated.status = "accepted_pending_explicit_picos_action"
        elif request.action == EvidenceAiRevisionAction.REJECT:
            target_updated.user_decision = "rejected"
            updated.status = "rejected"
        elif request.action == EvidenceAiRevisionAction.REQUEST_REWRITE:
            instruction = request.rewrite_instruction.strip() or request.comment.strip()
            if not instruction:
                raise ValueError("退回修改时必须填写具体修改要求。")
            workflow = self.picos_workflow_service.workflow(project_id, updated.package_id)
            if workflow.revision != updated.base_picos_revision or workflow.evidence_package_hash != updated.evidence_package_hash:
                raise ValueError("PICOS工作状态或证据资料包已变化，请基于当前版本新建AI建议线程。")
            step = self._step(workflow.steps, updated.anchor_id)
            run = self._run_ai(
                project_id,
                updated.package_id,
                step,
                instruction,
                updated.source_evidence_ids,
            )
            target_updated.user_decision = "rewrite_requested"
            result_proposal = self._proposal(run, step, sequence=len(updated.proposals) + 1)
            updated.proposals.append(result_proposal)
            updated.user_instruction = instruction
            updated.status = "pending_medical_action"
        else:  # pragma: no cover - enum prevents this
            raise ValueError(f"unsupported AI revision action: {request.action}")

        updated.revision = previous.revision + 1
        updated.updated_at = datetime.now(timezone.utc)
        audit_event = self._audit(
            project_id,
            request.actor,
            request.action.value,
            thread_id,
            {
                "package_id": updated.package_id,
                "anchor_id": updated.anchor_id,
                "proposal_id": request.proposal_id,
                "result_proposal_id": result_proposal.proposal_id,
                "previous_revision": previous.revision,
                "new_revision": updated.revision,
                "comment": request.comment.strip(),
            },
            updated.updated_at,
        )
        self.runtime_store.commit_evidence_ai_revision_action(
            previous,
            updated,
            audit_event,
            expected_revision=previous.revision,
            idempotency_key=request.idempotency_key or f"evidence-ai-action:{thread_id}:{updated.revision}",
            request_fingerprint=_fingerprint(updated.model_dump(mode="json")),
        )
        return self._result(updated, result_proposal)

    def list_threads(
        self,
        project_id: str,
        package_id: str,
        anchor_id: str = "",
    ) -> List[EvidenceAiRevisionThread]:
        return self.runtime_store.evidence_ai_revision_threads(
            project_id,
            package_id,
            anchor_id=anchor_id or None,
        )

    def _run_ai(
        self,
        project_id: str,
        package_id: str,
        step: EvidencePicosWorkflowStep,
        instruction: str,
        source_evidence_ids: Sequence[str],
    ) -> AiTaskRun:
        sources = [self._picos_source(project_id, package_id, step)]
        for evidence_id in dict.fromkeys(source_evidence_ids):
            detail = self.manifest_service.candidate_detail(project_id, package_id, evidence_id)
            sources.append(
                AiTaskSourceRef(
                    source_id=f"evidence_candidate_{sha1(evidence_id.encode('utf-8')).hexdigest()[:16]}",
                    source_type=f"evidence_candidate_{detail.evidence_type}",
                    title=detail.title,
                    locator=f"EvidenceCandidate/{detail.evidence_id}",
                    text_preview=json.dumps(
                        {
                            "primary_source_id": detail.primary_source_id,
                            "drug_name": detail.drug_name,
                            "trial_identifier": detail.trial_identifier,
                            "source_status": detail.source_status,
                            "source_date": detail.source_date,
                            "source_refs": detail.source_refs,
                            "metadata": detail.metadata,
                        },
                        ensure_ascii=False,
                    )[:12000],
                    project_id=project_id,
                    module="evidence_design",
                )
            )
        run = self.ai_task_runner.submit_internal(
            project_id,
            AiTaskRequest(
                module="evidence_design",
                task_type="picos_design_coach",
                prompt_version="picos_design_coach_v0_1",
                allowed_sources=sources,
                forbidden_source_ids=[],
                user_instruction=(
                    f"锚定类型=picos_question；锚定ID={step.question_id}。"
                    f"用户修改要求：{instruction.strip()}。"
                    "请仅在给定候选option_id中提出一项AI建议修订，并说明理由与不确定性。"
                ),
            ),
        )
        if run.status == AiTaskRunStatus.BLOCKED:
            raise ValueError(
                "独立AI未配置或未获私有化执行许可；未生成建议，也未使用Codex或确定性替代内容。"
            )
        if run.status == AiTaskRunStatus.FAILED:
            detail = "; ".join(run.validation_errors) or run.error_message or "provider output failed validation"
            raise ValueError(f"独立AI建议未通过来源与结构校验：{detail}")
        return run

    def _picos_source(
        self,
        project_id: str,
        package_id: str,
        step: EvidencePicosWorkflowStep,
    ) -> AiTaskSourceRef:
        payload = {
            "question_id": step.question_id,
            "picos_domain": step.picos_domain,
            "question": step.question,
            "current_evidence_summary": step.current_evidence_summary,
            "required_user_decision": step.required_user_decision,
            "source_refs": step.source_refs,
            "current_selection": step.selected_option_id,
            "current_rationale": step.user_rationale,
            "candidate_options": [
                {
                    "option_id": option.option_id,
                    "label": option.label,
                    "design_summary": option.design_summary,
                    "risk_notes": option.risk_notes,
                }
                for option in step.options
            ],
        }
        return AiTaskSourceRef(
            source_id=f"picos_context_{sha1(f'{package_id}|{step.question_id}'.encode('utf-8')).hexdigest()[:16]}",
            source_type="picos_working_context",
            title=f"{step.picos_domain} / {step.question_id}",
            locator=f"PICOS/{step.question_id}",
            text_preview=json.dumps(payload, ensure_ascii=False),
            project_id=project_id,
            module="evidence_design",
        )

    def _proposal(
        self,
        run: AiTaskRun,
        step: EvidencePicosWorkflowStep,
        *,
        sequence: int,
    ) -> EvidenceAiRevisionProposal:
        output = self._provider_output(run)
        revision = output.get("revision")
        if not isinstance(revision, dict):
            raise ValueError("独立AI输出缺少revision对象。")
        if revision.get("anchor_type") != "picos_question" or revision.get("anchor_id") != step.question_id:
            raise ValueError("独立AI输出锚点与当前PICOS问题不一致。")
        proposed_option_id = str(revision.get("proposed_option_id") or "")
        valid_options = {option.option_id for option in step.options}
        if proposed_option_id not in valid_options:
            raise ValueError("独立AI输出引用了当前PICOS问题之外的候选选项。")
        evidence_span_ids = [str(value) for value in revision.get("evidence_span_ids", [])]
        uncertainty = "; ".join(
            f"{item.get('level')}: {item.get('description')}"
            for item in output.get("uncertainties", [])
            if isinstance(item, dict) and item.get("level") and item.get("description")
        )
        return EvidenceAiRevisionProposal(
            proposal_id=f"evidence_ai_proposal_{run.run_id}_{sequence:03d}",
            ai_run_id=run.run_id,
            proposal_text=str(revision.get("proposal_text") or ""),
            proposed_option_id=proposed_option_id,
            rationale=str(revision.get("rationale") or ""),
            evidence_span_ids=evidence_span_ids,
            uncertainty=uncertainty,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _provider_output(run: AiTaskRun) -> Dict[str, object]:
        for artifact in run.artifacts:
            if artifact.artifact_type == "provider_output" and isinstance(artifact.payload, dict):
                return artifact.payload
        raise ValueError("独立AI运行没有返回可审计的provider_output。")

    @staticmethod
    def _step(steps: Sequence[EvidencePicosWorkflowStep], anchor_id: str) -> EvidencePicosWorkflowStep:
        for step in steps:
            if step.question_id == anchor_id:
                return step
        raise KeyError(f"PICOS问题不存在：{anchor_id}")

    @staticmethod
    def _check_source_revision(revision: int, package_hash: str, request: EvidenceAiRevisionRequest) -> None:
        if revision != request.expected_picos_revision:
            raise ValueError(
                f"PICOS工作状态已更新：expected={request.expected_picos_revision}, actual={revision}"
            )
        if package_hash != request.expected_evidence_package_hash:
            raise ValueError("证据资料包已变化，请刷新后重新发起AI建议。")

    @staticmethod
    def _audit(
        project_id: str,
        actor: str,
        action: str,
        thread_id: str,
        detail: Dict[str, object],
        created_at: datetime,
    ) -> AuditEvent:
        return AuditEvent(
            audit_id=f"audit_{uuid4().hex}",
            project_id=project_id,
            actor=actor,
            action=action,
            target_type="evidence_ai_revision_thread",
            target_id=thread_id,
            detail=detail,
            created_at=created_at,
        )

    @staticmethod
    def _result(
        thread: EvidenceAiRevisionThread,
        proposal: EvidenceAiRevisionProposal,
    ) -> EvidenceAiRevisionResult:
        return EvidenceAiRevisionResult(
            thread=thread,
            proposal=proposal,
            requires_explicit_picos_action=True,
            recommended_picos_action={
                "action": "select_option",
                "question_id": thread.anchor_id,
                "option_id": proposal.proposed_option_id,
                "user_rationale": proposal.rationale,
            },
        )


def _fingerprint(value: object) -> str:
    return sha1(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
