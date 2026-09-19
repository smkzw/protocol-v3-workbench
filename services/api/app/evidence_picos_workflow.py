from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    ApprovalAction,
    ApprovalDecisionRecord,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    EvidencePicosApprovalSubmissionResult,
    EvidencePicosActionRequest,
    EvidencePicosDecisionAction,
    EvidencePicosDecisionOption,
    EvidencePicosDecisionRecord,
    EvidencePicosQuestion,
    EvidencePicosQuestionState,
    EvidencePicosHandoffRequest,
    EvidencePicosSnapshot,
    EvidencePicosSubmitApprovalRequest,
    EvidencePicosWorkingState,
    EvidencePicosWritingHandoff,
    EvidencePicosWorkflowResult,
    EvidencePicosWorkflowStep,
    EvidenceQualityGate,
)

from .ai_gateway import ai_gateway_status_from_env
from .evidence_design_manifest import EvidenceDesignManifestService
from .sqlite_runtime_store import SqliteRuntimeStore


class EvidencePicosDecisionStore:
    def __init__(self, jsonl_path: Path):
        self.jsonl_path = jsonl_path

    def append(self, record: EvidencePicosDecisionRecord) -> None:
        self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        with self.jsonl_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def list_records(self, project_id: str, package_id: Optional[str] = None) -> List[EvidencePicosDecisionRecord]:
        records = [
            record
            for record in self._read_all()
            if record.project_id == project_id and (package_id is None or record.package_id == package_id)
        ]
        return sorted(records, key=lambda item: item.created_at)

    def _read_all(self) -> List[EvidencePicosDecisionRecord]:
        if not self.jsonl_path.exists():
            return []
        records: List[EvidencePicosDecisionRecord] = []
        with self.jsonl_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    records.append(EvidencePicosDecisionRecord.model_validate(json.loads(line)))
                except Exception:
                    continue
        return records


class SqliteEvidencePicosDecisionStore:
    def __init__(self, runtime_store: SqliteRuntimeStore):
        self.runtime_store = runtime_store

    def list_records(self, project_id: str, package_id: Optional[str] = None) -> List[EvidencePicosDecisionRecord]:
        if package_id is None:
            raise ValueError("package_id is required for SQLite PICOS persistence")
        return self.runtime_store.evidence_picos_decision_records(project_id, package_id)

    def working_state(self, project_id: str, package_id: str) -> Optional[EvidencePicosWorkingState]:
        try:
            return self.runtime_store.evidence_picos_working_state(project_id, package_id)
        except KeyError:
            return None

    def commit_action(
        self,
        previous_state: EvidencePicosWorkingState,
        updated_state: EvidencePicosWorkingState,
        record: EvidencePicosDecisionRecord,
        audit_event: AuditEvent,
        request: EvidencePicosActionRequest,
    ) -> None:
        request_fingerprint = sha1(
            json.dumps(
                {
                    "record": record.model_dump(mode="json"),
                    "state": updated_state.model_dump(mode="json"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        self.runtime_store.commit_evidence_picos_action(
            previous_state,
            updated_state,
            record,
            audit_event,
            expected_revision=previous_state.revision,
            idempotency_key=request.idempotency_key or f"picos:{record.record_id}",
            request_fingerprint=request_fingerprint,
        )

    def approval_binding(
        self,
        project_id: str,
        working_state_id: str,
        revision: int,
    ) -> tuple[ApprovalState, Optional[int], str]:
        gates = {gate.approval_id: gate for gate in self.runtime_store.gates(project_id)}
        snapshots = self.runtime_store.evidence_picos_working_state_snapshots(
            project_id,
            working_state_id,
        )
        for item in reversed(snapshots):
            approval_id = str(item.get("approval_id") or "")
            if not approval_id or int(item.get("revision") or 0) != revision:
                continue
            gate = gates.get(approval_id)
            if gate is None:
                continue
            if gate.state in {ApprovalState.MEDICALLY_APPROVED, ApprovalState.LOCKED_FOR_SUBMISSION}:
                return gate.state, revision, str(item["snapshot_id"])
            return gate.state, None, ""
        return ApprovalState.AI_DRAFT, None, ""

    def current_handoff(
        self,
        project_id: str,
        package_id: str,
        snapshot_id: str,
        revision: Optional[int],
        target_document_type: str = "protocol",
    ) -> Optional[EvidencePicosWritingHandoff]:
        if not snapshot_id or revision is None:
            return None
        return next(
            (
                handoff
                for handoff in reversed(
                    self.runtime_store.evidence_picos_handoffs(project_id, package_id)
                )
                if handoff.snapshot_id == snapshot_id
                and handoff.approved_revision == revision
                and handoff.target_document_type == target_document_type
            ),
            None,
        )


class EvidencePicosWorkflowService:
    def __init__(
        self,
        manifest_service: EvidenceDesignManifestService,
        store: EvidencePicosDecisionStore,
    ):
        self.manifest_service = manifest_service
        self.store = store

    def workflow(self, project_id: str, package_id: Optional[str] = None) -> EvidencePicosWorkflowResult:
        manifest = self.manifest_service.build_manifest(project_id)
        package = _select_package(manifest.packages, package_id)
        records = self.store.list_records(project_id, package.package_id)
        records_by_question = _records_by_question(records)
        persisted_state = self.store.working_state(project_id, package.package_id) if hasattr(self.store, "working_state") else None
        package_hash = self.manifest_service.package_hash(project_id, package.package_id)
        revision = persisted_state.revision if persisted_state is not None else max(
            [record.new_revision for record in records] + [len(records)]
        )
        ai_status = ai_gateway_status_from_env()
        steps = [
            _build_step(
                question,
                records_by_question.get(question.question_id, []),
                ai_status.get("ai_gateway_status") or ai_status.get("provider") or "not_configured",
                revision,
            )
            for question in package.picos_questions
        ]
        approval_state = persisted_state.approval_state if persisted_state is not None else ApprovalState.AI_DRAFT
        approved_revision = persisted_state.approved_revision if persisted_state is not None else None
        approved_snapshot_id = persisted_state.approved_snapshot_id if persisted_state is not None else ""
        if persisted_state is not None and hasattr(self.store, "approval_binding"):
            approval_state, approved_revision, approved_snapshot_id = self.store.approval_binding(
                project_id,
                persisted_state.working_state_id,
                revision,
            )
        source_changed = bool(persisted_state and persisted_state.evidence_package_hash != package_hash)
        if source_changed:
            approval_state = ApprovalState.AI_DRAFT
            approved_revision = None
            approved_snapshot_id = ""
        semantic_ai_tasks_enabled = (
            ai_status.get("semantic_ai_tasks_enabled") is True
        )
        current_handoff = (
            self.store.current_handoff(
                project_id,
                package.package_id,
                approved_snapshot_id,
                approved_revision,
            )
            if hasattr(self.store, "current_handoff")
            else None
        )
        gates = _workflow_gates(
            package.quality_gates,
            steps,
            ai_status,
            approval_state=approval_state,
            approved_revision=approved_revision,
            revision=revision,
            source_changed=source_changed,
        )
        blocking_count = sum(1 for gate in gates if gate.status == "blocked")
        return EvidencePicosWorkflowResult(
            project_id=project_id,
            package_id=package.package_id,
            generated_at=datetime.now(timezone.utc),
            working_state_id=_working_state_id(project_id, package.package_id),
            revision=revision,
            evidence_package_hash=package_hash,
            approval_state=approval_state,
            approved_revision=approved_revision,
            approved_snapshot_id=approved_snapshot_id,
            decision_count=sum(1 for step in steps if step.selected_option_id),
            confirmation_status=(
                "invalidated"
                if source_changed
                else "author_confirmed"
                if approval_state in {
                    ApprovalState.MEDICALLY_APPROVED,
                    ApprovalState.LOCKED_FOR_SUBMISSION,
                }
                and approved_revision == revision
                else "legacy_pending_medical_approval"
                if approval_state == ApprovalState.IN_MEDICAL_REVIEW
                else "not_confirmed"
            ),
            confirmed_revision=approved_revision,
            confirmed_snapshot_id=approved_snapshot_id,
            current_handoff_id=current_handoff.handoff_id if current_handoff else "",
            current_handoff_snapshot_id=(
                current_handoff.snapshot_id if current_handoff else ""
            ),
            current_handoff_revision=(
                current_handoff.approved_revision if current_handoff else None
            ),
            current_handoff_target_document_type=(
                current_handoff.target_document_type if current_handoff else ""
            ),
            writing_candidate_count=sum(
                1 for step in steps if _is_author_confirmed_step(step)
            ),
            blocking_gate_count=blocking_count,
            ai_gateway_status=(
                "configured" if semantic_ai_tasks_enabled else "not_configured"
            ),
            needs_medical_confirmation=any(
                not _is_author_confirmed_step(step) for step in steps
            ),
            steps=steps,
            quality_gates=gates,
            parser_notes=[
                "PICOS决策采用资料包级revision、追加式动作记录和不可变快照；同一资料包的任何问题变化都会递增revision。",
                "每个PICOS域由医学作者选择并填写理由；全部域确认后生成版本化写作交接快照，不再进入第二层医学批准。",
                "独立 AI provider 未配置时，只能保存用户决策和准备候选，不生成语义设计结论。",
            ],
        )

    def apply_action(
        self,
        project_id: str,
        package_id: str,
        question_id: str,
        request: EvidencePicosActionRequest,
    ) -> EvidencePicosWorkflowResult:
        if not isinstance(request, EvidencePicosActionRequest):
            request = EvidencePicosActionRequest.model_validate(request)
        before = self.workflow(project_id, package_id)
        step = _find_step(before.steps, question_id)
        valid_option_ids = {option.option_id for option in step.options}
        from_status = step.decision_status
        expected_revision = before.revision if request.expected_revision is None else request.expected_revision
        if expected_revision != before.revision:
            raise ValueError(f"PICOS工作状态已更新：expected={expected_revision}, actual={before.revision}")
        if request.expected_evidence_package_hash and request.expected_evidence_package_hash != before.evidence_package_hash:
            raise ValueError("证据资料包已变化，请刷新后重新确认PICOS决策。")

        if request.action == EvidencePicosDecisionAction.SELECT_OPTION:
            if request.option_id not in valid_option_ids:
                raise ValueError(f"option not found for PICOS question: {request.option_id}")
            to_status = "作者已确认"
        elif request.action == EvidencePicosDecisionAction.SAVE_RATIONALE:
            if not step.selected_option_id:
                raise ValueError("请先选择一个PICOS候选方案，再保存医学理由。")
            if not request.user_rationale.strip():
                raise ValueError("医学理由不能为空。")
            to_status = "作者已确认"
        elif request.action == EvidencePicosDecisionAction.MARK_WRITING_CANDIDATE:
            if not step.selected_option_id or not step.user_rationale.strip():
                raise ValueError("作者确认前必须选择候选方案并填写医学理由。")
            to_status = "作者已确认"
        elif request.action == EvidencePicosDecisionAction.RETURN_FOR_EVIDENCE:
            to_status = "退回补证"
        elif request.action == EvidencePicosDecisionAction.RESET_DECISION:
            to_status = "待用户确认"
        else:  # pragma: no cover - enum prevents this
            raise ValueError(f"unsupported action: {request.action}")

        created_at = datetime.now(timezone.utc)
        new_revision = before.revision + 1
        working_state_id = _working_state_id(project_id, package_id)
        record = EvidencePicosDecisionRecord(
            record_id=_record_id(project_id, package_id, question_id, request.action.value),
            project_id=project_id,
            package_id=package_id,
            working_state_id=working_state_id,
            question_id=question_id,
            action=request.action,
            actor=request.actor,
            option_id=request.option_id,
            user_rationale=request.user_rationale.strip(),
            comment=request.comment.strip(),
            from_status=from_status,
            to_status=to_status,
            previous_revision=before.revision,
            new_revision=new_revision,
            created_at=created_at,
        )
        if hasattr(self.store, "commit_action"):
            previous_state = _working_state_from_workflow(before, created_at=created_at)
            updated_steps = _steps_after_record(before.steps, record, before.ai_gateway_status, new_revision)
            updated_state = previous_state.model_copy(
                update={
                    "revision": new_revision,
                    "approval_state": ApprovalState.AI_DRAFT,
                    "approved_revision": None,
                    "approved_snapshot_id": "",
                    "question_states": _question_states(updated_steps),
                    "updated_at": created_at,
                }
            )
            audit_event = AuditEvent(
                audit_id=f"audit_{uuid4().hex}",
                project_id=project_id,
                actor=request.actor,
                action=request.action.value,
                target_type="evidence_picos_working_state",
                target_id=working_state_id,
                detail={
                    "package_id": package_id,
                    "question_id": question_id,
                    "previous_revision": before.revision,
                    "new_revision": new_revision,
                    "record_id": record.record_id,
                },
                created_at=created_at,
            )
            self.store.commit_action(previous_state, updated_state, record, audit_event, request)
        else:
            self.store.append(record)
        return self.workflow(project_id, package_id)


class EvidencePicosApprovalService:
    def __init__(
        self,
        workflow_service: EvidencePicosWorkflowService,
        runtime_store: SqliteRuntimeStore,
    ):
        self.workflow_service = workflow_service
        self.runtime_store = runtime_store

    def submit_for_approval(
        self,
        project_id: str,
        package_id: str,
        request: EvidencePicosSubmitApprovalRequest,
    ) -> EvidencePicosApprovalSubmissionResult:
        if not isinstance(request, EvidencePicosSubmitApprovalRequest):
            request = EvidencePicosSubmitApprovalRequest.model_validate(request)
        workflow = self.workflow_service.workflow(project_id, package_id)
        if workflow.revision != request.expected_revision:
            raise ValueError(
                f"PICOS工作状态已更新：expected={request.expected_revision}, actual={workflow.revision}"
            )
        if workflow.evidence_package_hash != request.expected_evidence_package_hash:
            raise ValueError("证据资料包已变化，请刷新后重新确认PICOS决策。")
        incomplete = [
            step.picos_domain
            for step in workflow.steps
            if not _is_author_confirmed_step(step)
        ]
        if incomplete:
            raise ValueError(
                f"生成作者确认快照前，以下PICOS域尚未确认：{'、'.join(incomplete)}"
            )
        pre_confirmation_blockers = [
            gate.gate_label
            for gate in workflow.quality_gates
            if gate.status == "blocked"
            and gate.gate_id != "picos:gate:author_confirmation"
        ]
        if pre_confirmation_blockers:
            raise ValueError(
                f"生成作者确认快照前仍存在阻断质量门：{'、'.join(pre_confirmation_blockers)}"
            )

        created_at = datetime.now(timezone.utc)
        snapshot_seed = (
            f"{project_id}|{package_id}|{workflow.working_state_id}|"
            f"{workflow.revision}|{workflow.evidence_package_hash}"
        )
        snapshot_token = sha1(snapshot_seed.encode("utf-8")).hexdigest()[:16]
        snapshot_id = f"picos_snapshot_{snapshot_token}"
        approval_id = f"confirmation_picos_{snapshot_token}_r{workflow.revision}"
        existing_snapshot = next(
            (
                item.get("snapshot")
                for item in self.runtime_store.evidence_picos_working_state_snapshots(
                    project_id,
                    workflow.working_state_id,
                )
                if item.get("snapshot_id") == snapshot_id
            ),
            None,
        )
        if existing_snapshot is not None:
            existing_approval = next(
                (
                    item
                    for item in self.runtime_store.gates(project_id)
                    if item.approval_id == existing_snapshot.approval_id
                ),
                None,
            )
            if existing_approval is None:
                raise RuntimeError("PICOS确认快照缺少兼容状态绑定")
            if existing_approval.state in {
                ApprovalState.IN_MEDICAL_REVIEW,
                ApprovalState.RETURNED_FOR_REVISION,
            }:
                if not _is_legacy_pending_picos_binding(
                    existing_snapshot,
                    existing_approval,
                    workflow.revision,
                ):
                    raise RuntimeError("PICOS确认快照存在无法识别的历史待审批绑定")
                existing_approval = self._upgrade_legacy_author_confirmation(
                    existing_snapshot,
                    existing_approval,
                    request,
                )
            if existing_approval.state not in {
                ApprovalState.MEDICALLY_APPROVED,
                ApprovalState.LOCKED_FOR_SUBMISSION,
            }:
                raise ValueError(
                    "PICOS历史快照未完成可迁移的作者确认，未生成版本化技术快照"
                )
            refreshed_workflow = self.workflow_service.workflow(project_id, package_id)
            if (
                refreshed_workflow.confirmation_status != "author_confirmed"
                or refreshed_workflow.confirmed_snapshot_id != existing_snapshot.snapshot_id
            ):
                raise ValueError("PICOS版本化技术快照状态未持久化")
            return EvidencePicosApprovalSubmissionResult(
                snapshot=existing_snapshot,
                approval=existing_approval,
                workflow=refreshed_workflow,
            )
        snapshot = EvidencePicosSnapshot(
            snapshot_id=snapshot_id,
            project_id=project_id,
            package_id=package_id,
            working_state_id=workflow.working_state_id,
            revision=workflow.revision,
            evidence_package_hash=workflow.evidence_package_hash,
            approval_id=approval_id,
            snapshot_type="author_confirmation",
            confirmation_type="medical_author_confirmation",
            created_by=request.actor,
            question_states=_question_states(workflow.steps),
            created_at=created_at,
        )
        approval = ApprovalGate(
            approval_id=approval_id,
            project_id=project_id,
            target_type="evidence_picos_snapshot",
            target_id=snapshot_id,
            target_revision=workflow.revision,
            display_title="PICOS 作者确认快照",
            display_detail="医学作者已确认当前PICOS域选择、理由与来源，可直接用于写作交接。",
            state=ApprovalState.MEDICALLY_APPROVED,
            requested_by=request.actor,
            reviewed_by=request.actor,
            approved_by=request.actor,
            review_comments=request.comment.strip(),
            created_at=created_at,
            updated_at=created_at,
        )
        audit_event = AuditEvent(
            audit_id=f"audit_{uuid4().hex}",
            project_id=project_id,
            actor=request.actor,
            action="confirm_picos_author_selection",
            target_type="evidence_picos_snapshot",
            target_id=snapshot_id,
            detail={
                "package_id": package_id,
                "revision": workflow.revision,
                "evidence_package_hash": workflow.evidence_package_hash,
                "approval_id": approval_id,
                "comment": request.comment.strip(),
            },
            created_at=created_at,
        )
        fingerprint = sha1(
            json.dumps(
                {
                    "snapshot": snapshot.model_dump(mode="json"),
                    "approval": approval.model_dump(mode="json"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        self.runtime_store.commit_evidence_picos_snapshot(
            snapshot,
            approval,
            audit_event,
            expected_revision=workflow.revision,
            idempotency_key=request.idempotency_key or f"picos-confirm:{snapshot_id}",
            request_fingerprint=fingerprint,
        )
        return EvidencePicosApprovalSubmissionResult(
            snapshot=snapshot,
            approval=approval,
            workflow=self.workflow_service.workflow(project_id, package_id),
        )

    def _upgrade_legacy_author_confirmation(
        self,
        snapshot: EvidencePicosSnapshot,
        approval: ApprovalGate,
        request: EvidencePicosSubmitApprovalRequest,
    ) -> ApprovalGate:
        confirmed_at = datetime.now(timezone.utc)
        migration_token = sha1(
            (
                f"{snapshot.project_id}|{snapshot.snapshot_id}|"
                f"{approval.approval_id}|{snapshot.revision}"
            ).encode("utf-8")
        ).hexdigest()[:16]
        confirmation_comment = request.comment.strip() or (
            "历史审批状态已按既有作者选择迁移为版本化技术快照。"
        )
        updated_approval = approval.model_copy(
            update={
                "display_title": "PICOS 作者确认快照（历史绑定）",
                "display_detail": (
                    "历史PICOS选择已迁移为作者确认快照；原审批绑定仅保留为兼容身份，"
                    "当前版本可直接用于写作交接。"
                ),
                "state": ApprovalState.MEDICALLY_APPROVED,
                "reviewed_by": request.actor,
                "approved_by": request.actor,
                "review_comments": confirmation_comment,
                "updated_at": confirmed_at,
            }
        )
        audit_event = AuditEvent(
            audit_id=f"audit_picos_author_confirmation_migration_{migration_token}",
            project_id=snapshot.project_id,
            actor=request.actor,
            action="migrate_legacy_picos_author_selection",
            target_type="evidence_picos_snapshot",
            target_id=snapshot.snapshot_id,
            detail={
                "package_id": snapshot.package_id,
                "revision": snapshot.revision,
                "evidence_package_hash": snapshot.evidence_package_hash,
                "snapshot_type": snapshot.snapshot_type,
                "confirmation_type": snapshot.confirmation_type,
                "legacy_approval_id": approval.approval_id,
                "legacy_gate": approval.model_dump(mode="json"),
                "new_state": ApprovalState.MEDICALLY_APPROVED.value,
                "author_confirmation": True,
                "second_medical_approval_required": False,
                "comment": request.comment.strip(),
            },
            created_at=confirmed_at,
        )
        decision = ApprovalDecisionRecord(
            decision_id=f"decision_picos_author_confirmation_migration_{migration_token}",
            approval_id=approval.approval_id,
            project_id=snapshot.project_id,
            action=ApprovalAction.APPROVE,
            actor=request.actor,
            previous_state=approval.state,
            new_state=ApprovalState.MEDICALLY_APPROVED,
            comment=confirmation_comment,
            audit_event_id=audit_event.audit_id,
            created_at=confirmed_at,
        )
        fingerprint = sha1(
            json.dumps(
                {
                    "operation": "migrate_legacy_picos_author_selection",
                    "project_id": snapshot.project_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "approval_id": approval.approval_id,
                    "revision": snapshot.revision,
                    "evidence_package_hash": snapshot.evidence_package_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        self.runtime_store.commit_approval_action(
            updated_approval,
            audit_event,
            decision,
            idempotency_key=(
                f"picos-migrate-legacy:{snapshot.snapshot_id}:{approval.approval_id}"
            ),
            request_fingerprint=fingerprint,
        )
        persisted_approval = next(
            (
                item
                for item in self.runtime_store.gates(snapshot.project_id)
                if item.approval_id == approval.approval_id
            ),
            None,
        )
        if (
            persisted_approval is None
            or persisted_approval.state != ApprovalState.MEDICALLY_APPROVED
        ):
            raise RuntimeError("PICOS历史待审批绑定未完成作者确认迁移")
        return persisted_approval

    def create_handoff(
        self,
        project_id: str,
        package_id: str,
        request: EvidencePicosHandoffRequest,
    ) -> EvidencePicosWritingHandoff:
        if not isinstance(request, EvidencePicosHandoffRequest):
            request = EvidencePicosHandoffRequest.model_validate(request)
        workflow = self.workflow_service.workflow(project_id, package_id)
        snapshots = self.runtime_store.evidence_picos_working_state_snapshots(
            project_id,
            workflow.working_state_id,
        )
        snapshot = next(
            (
                item.get("snapshot")
                for item in snapshots
                if item.get("snapshot_id") == request.snapshot_id and item.get("snapshot") is not None
            ),
            None,
        )
        if snapshot is None:
            raise KeyError(f"PICOS确认快照不存在：{request.snapshot_id}")
        handoff_token = sha1(
            f"{project_id}|{package_id}|{snapshot.snapshot_id}|{request.target_document_type}".encode("utf-8")
        ).hexdigest()[:16]
        created_at = datetime.now(timezone.utc)
        handoff = EvidencePicosWritingHandoff(
            handoff_id=f"picos_handoff_{handoff_token}",
            project_id=project_id,
            package_id=package_id,
            working_state_id=snapshot.working_state_id,
            snapshot_id=snapshot.snapshot_id,
            approval_id=snapshot.approval_id,
            approved_revision=snapshot.revision,
            confirmation_id=snapshot.approval_id,
            confirmed_revision=snapshot.revision,
            target_document_type=request.target_document_type,
            created_by=request.actor,
            source_refs=[
                f"PICOSSnapshot:{snapshot.snapshot_id}",
                f"AuthorConfirmation:{snapshot.approval_id}",
                f"EvidencePackage:{snapshot.evidence_package_hash}",
            ],
            created_at=created_at,
        )
        audit_event = AuditEvent(
            audit_id=f"audit_{uuid4().hex}",
            project_id=project_id,
            actor=request.actor,
            action="create_medical_writing_handoff",
            target_type="evidence_picos_handoff",
            target_id=handoff.handoff_id,
            detail={
                "package_id": package_id,
                "snapshot_id": snapshot.snapshot_id,
                "confirmation_id": snapshot.approval_id,
                "revision": snapshot.revision,
                "target_document_type": request.target_document_type,
            },
            created_at=created_at,
        )
        fingerprint = sha1(
            json.dumps(
                {
                    "project_id": handoff.project_id,
                    "package_id": handoff.package_id,
                    "working_state_id": handoff.working_state_id,
                    "snapshot_id": handoff.snapshot_id,
                    "approval_id": handoff.approval_id,
                    "approved_revision": handoff.approved_revision,
                    "target_module": handoff.target_module,
                    "target_document_type": handoff.target_document_type,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        commit_result = self.runtime_store.commit_evidence_picos_handoff(
            handoff,
            audit_event,
            idempotency_key=request.idempotency_key or f"picos-handoff:{handoff.handoff_id}",
            request_fingerprint=fingerprint,
        )
        if commit_result.replayed:
            persisted = next(
                (
                    item
                    for item in self.runtime_store.evidence_picos_handoffs(
                        project_id,
                        package_id,
                    )
                    if item.handoff_id == handoff.handoff_id
                ),
                None,
            )
            if persisted is None:
                raise RuntimeError("PICOS写作交接幂等重放缺少既有记录")
            return persisted
        return handoff


def _is_legacy_pending_picos_binding(
    snapshot: EvidencePicosSnapshot,
    approval: ApprovalGate,
    expected_revision: int,
) -> bool:
    return (
        snapshot.snapshot_type == "medical_review_submission"
        and snapshot.confirmation_type == "legacy_medical_approval"
        and snapshot.approval_id.startswith("approval_picos_")
        and approval.approval_id == snapshot.approval_id
        and approval.target_type == "evidence_picos_snapshot"
        and approval.target_id == snapshot.snapshot_id
        and approval.target_revision == snapshot.revision == expected_revision
        and approval.state
        in {
            ApprovalState.IN_MEDICAL_REVIEW,
            ApprovalState.RETURNED_FOR_REVISION,
        }
    )


def _select_package(packages: Sequence, package_id: Optional[str]):
    if not packages:
        raise KeyError("evidence package not found")
    if not package_id:
        return packages[0]
    for package in packages:
        if package.package_id == package_id:
            return package
    raise KeyError(f"evidence package not found: {package_id}")


def _find_step(steps: Sequence[EvidencePicosWorkflowStep], question_id: str) -> EvidencePicosWorkflowStep:
    for step in steps:
        if step.question_id == question_id:
            return step
    raise KeyError(f"PICOS question not found: {question_id}")


def _records_by_question(records: Sequence[EvidencePicosDecisionRecord]) -> Dict[str, List[EvidencePicosDecisionRecord]]:
    grouped: Dict[str, List[EvidencePicosDecisionRecord]] = {}
    for record in records:
        grouped.setdefault(record.question_id, []).append(record)
    return grouped


def _build_step(
    question: EvidencePicosQuestion,
    records: Sequence[EvidencePicosDecisionRecord],
    ai_gateway_status: str,
    revision: int = 0,
) -> EvidencePicosWorkflowStep:
    options = _options_for_question(question)
    selected_option_id = ""
    user_rationale = ""
    decision_status = "待用户确认"

    for record in records:
        if record.action == EvidencePicosDecisionAction.RESET_DECISION:
            selected_option_id = ""
            user_rationale = ""
            decision_status = "待用户确认"
            continue
        if record.action == EvidencePicosDecisionAction.RETURN_FOR_EVIDENCE:
            decision_status = "退回补证"
            if record.user_rationale:
                user_rationale = record.user_rationale
            continue
        if record.action == EvidencePicosDecisionAction.SELECT_OPTION:
            selected_option_id = record.option_id
            if record.user_rationale:
                user_rationale = record.user_rationale
            decision_status = "作者已确认"
            continue
        if record.action == EvidencePicosDecisionAction.SAVE_RATIONALE:
            if record.user_rationale:
                user_rationale = record.user_rationale
            decision_status = "作者已确认"
            continue
        if record.action == EvidencePicosDecisionAction.MARK_WRITING_CANDIDATE:
            # Historical records wrote "写作候选". The action itself is the
            # author's explicit project-level confirmation, so project it to
            # the unified current state without rewriting the audit record.
            decision_status = "作者已确认"

    selected_option = next((option for option in options if option.option_id == selected_option_id), None)
    writing_target = selected_option.writing_target_section if selected_option else _default_writing_target(question.question_id)
    can_handoff = decision_status in {"作者已确认", "写作候选"}
    return EvidencePicosWorkflowStep(
        question_id=question.question_id,
        picos_domain=question.picos_domain,
        question=question.question,
        evidence_status=question.evidence_status,
        current_evidence_summary=question.current_evidence_summary,
        required_user_decision=question.required_user_decision,
        source_refs=question.source_refs,
        handoff_to_writing=question.handoff_to_writing,
        options=options,
        selected_option_id=selected_option_id,
        user_rationale=user_rationale,
        decision_status=decision_status,
        writing_handoff_status="作者已确认，可进入写作交接" if can_handoff else "暂不可流转",
        writing_target_section=writing_target,
        quality_gate_status="ok" if can_handoff else "blocked",
        ai_gateway_status=ai_gateway_status,
        needs_medical_confirmation=not can_handoff,
        author_confirmation_status="confirmed" if can_handoff else "not_confirmed",
        revision=revision,
        audit_trail=list(records)[-8:],
    )


def _options_for_question(question: EvidencePicosQuestion) -> List[EvidencePicosDecisionOption]:
    templates = (
        [template.model_dump(mode="python") for template in question.option_templates]
        if question.option_templates
        else _generic_options(question)
    )
    return [
        EvidencePicosDecisionOption(
            option_id=f"{question.question_id}:option:{index}",
            label=item["label"],
            design_summary=item["design_summary"],
            evidence_summary=item.get("evidence_summary") or question.current_evidence_summary,
            medical_rationale_prompt=item["medical_rationale_prompt"],
            writing_target_section=item.get("writing_target_section") or _default_writing_target(question.question_id),
            source_refs=question.source_refs,
            risk_notes=item.get("risk_notes", []),
            candidate_rank=index,
        )
        for index, item in enumerate(templates, start=1)
    ]


def _generic_options(question: EvidencePicosQuestion) -> List[Dict[str, object]]:
    return [
        {
            "label": "保守候选",
            "design_summary": "沿用证据中最常见的设计要素，作为待医学确认候选。",
            "medical_rationale_prompt": "请说明为何当前项目适合采用较保守的设计口径。",
            "risk_notes": ["需确认是否会降低差异化或注册沟通价值。"],
        },
        {
            "label": "差异化候选",
            "design_summary": "在竞品常见口径上增加项目差异化要素，作为待医学确认候选。",
            "medical_rationale_prompt": "请说明差异化设计与适应症、产品特征和监管策略的关系。",
            "risk_notes": ["需补充来源和跨部门确认。"],
        },
    ]


def _default_writing_target(question_id: str) -> str:
    return {
        "picos:population": "入排标准/研究人群",
        "picos:intervention": "试验用药与治疗方案",
        "picos:comparator": "研究设计与对照",
        "picos:outcomes": "研究目的与终点",
        "picos:study_design": "研究设计/统计学考虑",
    }.get(question_id, "研究方案相关章节")


def _is_author_confirmed_step(step: EvidencePicosWorkflowStep) -> bool:
    return step.decision_status in {"作者已确认", "写作候选"}


def _workflow_gates(
    source_gates: Sequence[EvidenceQualityGate],
    steps: Sequence[EvidencePicosWorkflowStep],
    ai_status: Dict[str, object],
    *,
    approval_state: ApprovalState = ApprovalState.AI_DRAFT,
    approved_revision: Optional[int] = None,
    revision: int = 0,
    source_changed: bool = False,
) -> List[EvidenceQualityGate]:
    selected_count = sum(1 for step in steps if step.selected_option_id)
    rationale_count = sum(1 for step in steps if step.user_rationale.strip())
    candidate_count = sum(1 for step in steps if _is_author_confirmed_step(step))
    total = len(steps)
    semantic_ai_tasks_enabled = (
        ai_status.get("semantic_ai_tasks_enabled") is True
    )
    gates = [
        EvidenceQualityGate(
            gate_id="picos:gate:completeness",
            gate_label="PICOS完整性门",
            status="ok" if selected_count == total and rationale_count == total else "blocked",
            owner="医学经理",
            detail=f"已选择 {selected_count}/{total} 个PICOS候选，已填写医学理由 {rationale_count}/{total} 个。",
            source_refs=["PICOS 决策记录"],
        ),
        EvidenceQualityGate(
            gate_id="picos:gate:source_traceability",
            gate_label="来源可追溯门",
            status="ok" if all(step.source_refs for step in steps) else "blocked",
            owner="医学经理",
            detail="每个PICOS问题必须保留来源字段或source ref；当前只展示公开/本地证据索引，不暴露服务器绝对路径。",
            source_refs=["Trial_Design.csv", "Efficacy_Result.csv", "Safety_Result.csv", "Document_Index.csv"],
        ),
        EvidenceQualityGate(
            gate_id="picos:gate:writing_handoff",
            gate_label="PICOS域作者确认门",
            status="ok" if candidate_count == total and total else "blocked",
            owner="医学经理/医学撰写",
            detail=f"医学作者已确认 {candidate_count}/{total} 个PICOS域；未确认前不能进入写作交接。",
            source_refs=["医学写作章节树"],
        ),
        EvidenceQualityGate(
            gate_id="picos:gate:ai_boundary",
            gate_label="独立AI边界门",
            status="ok" if semantic_ai_tasks_enabled else "warning",
            owner="系统管理员",
            detail="PICOS设计辅助必须通过已配置的独立AI服务和来源边界；未配置时仅保存用户决策，不生成语义设计结论。",
            source_refs=["独立AI服务未配置", "PICOS设计辅助任务"],
        ),
        EvidenceQualityGate(
            gate_id="picos:gate:author_confirmation",
            gate_label="作者确认快照门",
            status=(
                "ok"
                if approval_state in {ApprovalState.MEDICALLY_APPROVED, ApprovalState.LOCKED_FOR_SUBMISSION}
                and approved_revision == revision
                and not source_changed
                else "blocked"
            ),
            owner="医学作者（当前用户）",
            detail=(
                "当前资料包revision已由医学作者确认，可基于确认快照发起撰写交接。"
                if approval_state in {ApprovalState.MEDICALLY_APPROVED, ApprovalState.LOCKED_FOR_SUBMISSION}
                and approved_revision == revision
                and not source_changed
                else "全部PICOS域确认后生成版本化快照；来源或revision变化会使既有确认失效。"
            ),
            source_refs=["AuthorConfirmationSnapshot", "WritingSourcePackageSummary"],
        ),
    ]
    source_boundary = next((gate for gate in source_gates if gate.gate_label == "来源边界已锁定"), None)
    if source_boundary:
        gates.insert(0, source_boundary)
    return gates


def _working_state_id(project_id: str, package_id: str) -> str:
    digest = sha1(f"{project_id}|{package_id}".encode("utf-8")).hexdigest()[:16]
    return f"picos_state_{digest}"


def _question_states(steps: Sequence[EvidencePicosWorkflowStep]) -> List[EvidencePicosQuestionState]:
    return [
        EvidencePicosQuestionState(
            question_id=step.question_id,
            selected_option_id=step.selected_option_id,
            user_rationale=step.user_rationale,
            decision_status=step.decision_status,
            writing_target_section=step.writing_target_section,
        )
        for step in steps
    ]


def _working_state_from_workflow(
    workflow: EvidencePicosWorkflowResult,
    *,
    created_at: datetime,
) -> EvidencePicosWorkingState:
    return EvidencePicosWorkingState(
        working_state_id=workflow.working_state_id,
        project_id=workflow.project_id,
        package_id=workflow.package_id,
        evidence_package_hash=workflow.evidence_package_hash,
        revision=workflow.revision,
        approval_state=workflow.approval_state,
        approved_revision=workflow.approved_revision,
        approved_snapshot_id=workflow.approved_snapshot_id,
        question_states=_question_states(workflow.steps),
        created_at=created_at,
        updated_at=created_at,
    )


def _steps_after_record(
    steps: Sequence[EvidencePicosWorkflowStep],
    record: EvidencePicosDecisionRecord,
    ai_gateway_status: str,
    revision: int,
) -> List[EvidencePicosWorkflowStep]:
    updated: List[EvidencePicosWorkflowStep] = []
    for step in steps:
        if step.question_id != record.question_id:
            updated.append(step.model_copy(update={"revision": revision}))
            continue
        selected_option_id = step.selected_option_id
        user_rationale = step.user_rationale
        decision_status = record.to_status or step.decision_status
        if record.action == EvidencePicosDecisionAction.RESET_DECISION:
            selected_option_id = ""
            user_rationale = ""
            decision_status = "待用户确认"
        elif record.action == EvidencePicosDecisionAction.SELECT_OPTION:
            selected_option_id = record.option_id
            if record.user_rationale:
                user_rationale = record.user_rationale
        elif record.action == EvidencePicosDecisionAction.SAVE_RATIONALE and record.user_rationale:
            user_rationale = record.user_rationale
        selected_option = next((item for item in step.options if item.option_id == selected_option_id), None)
        can_handoff = decision_status in {"作者已确认", "写作候选"}
        updated.append(
            step.model_copy(
                update={
                    "selected_option_id": selected_option_id,
                    "user_rationale": user_rationale,
                    "decision_status": decision_status,
                    "writing_handoff_status": "作者已确认，可进入写作交接" if can_handoff else "暂不可流转",
                    "writing_target_section": (
                        selected_option.writing_target_section
                        if selected_option is not None
                        else step.writing_target_section
                    ),
                    "quality_gate_status": "ok" if can_handoff else "blocked",
                    "ai_gateway_status": ai_gateway_status,
                    "needs_medical_confirmation": not can_handoff,
                    "author_confirmation_status": "confirmed" if can_handoff else "not_confirmed",
                    "revision": revision,
                    "audit_trail": [*step.audit_trail, record][-8:],
                }
            )
        )
    return updated


def _record_id(project_id: str, package_id: str, question_id: str, action: str) -> str:
    seed = f"{project_id}|{package_id}|{question_id}|{action}|{datetime.now(timezone.utc).isoformat()}"
    return f"picosrec_{sha1(seed.encode('utf-8')).hexdigest()[:12]}"


