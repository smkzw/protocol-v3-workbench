from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha1, sha256
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    AiRun,
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalActionResult,
    ApprovalBlocker,
    ApprovalDecisionRecord,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    DashboardSummary,
    DataBatch,
    ModuleCatalog,
    ModuleManifest,
    ModuleStatus,
    Project,
    ProtocolDocument,
    RevisionThread,
    RiskCase,
    RiskSeverity,
    RiskStatus,
)
from packages.contracts.workbench_contracts.models import SubjectMonitoringDrilldown


class ApprovalRuntimeStore:
    def __init__(self, gate_path: Path, decision_path: Path, audit_path: Path):
        self.gate_path = gate_path
        self.decision_path = decision_path
        self.audit_path = audit_path
        for path in (self.gate_path, self.decision_path, self.audit_path):
            path.parent.mkdir(parents=True, exist_ok=True)

    def upsert_gate(self, approval: ApprovalGate) -> None:
        self._append(self.gate_path, approval.model_dump(mode="json"))

    def append_decision(self, decision: ApprovalDecisionRecord) -> None:
        self._append(self.decision_path, decision.model_dump(mode="json"))

    def append_audit_event(self, event: AuditEvent) -> None:
        self._append(self.audit_path, event.model_dump(mode="json"))

    def gates(self, project_id: str | None = None) -> List[ApprovalGate]:
        latest: Dict[tuple[str, str], ApprovalGate] = {}
        for payload in self._read_jsonl(self.gate_path):
            if project_id is not None and payload.get("project_id") != project_id:
                continue
            try:
                gate = ApprovalGate.model_validate(payload)
            except Exception:
                continue
            latest[(gate.project_id, gate.approval_id)] = gate
        return list(latest.values())

    def decisions(self, project_id: str | None = None) -> List[ApprovalDecisionRecord]:
        records: List[ApprovalDecisionRecord] = []
        for payload in self._read_jsonl(self.decision_path):
            if project_id is not None and payload.get("project_id") != project_id:
                continue
            try:
                records.append(ApprovalDecisionRecord.model_validate(payload))
            except Exception:
                continue
        return records

    def audit_events(self, project_id: str | None = None) -> List[AuditEvent]:
        records: List[AuditEvent] = []
        for payload in self._read_jsonl(self.audit_path):
            if project_id is not None and payload.get("project_id") != project_id:
                continue
            try:
                records.append(AuditEvent.model_validate(payload))
            except Exception:
                continue
        return records

    def _append(self, path: Path, payload: Dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    records.append(payload)
        return records


def _default_approval_store(data_path: Path) -> ApprovalRuntimeStore:
    project_root = data_path.parent.parent if data_path.parent.name == "demo_data" else data_path.parent
    runtime_root = project_root / "runtime"
    return ApprovalRuntimeStore(
        runtime_root / "approval_gates.jsonl",
        runtime_root / "approval_decisions.jsonl",
        runtime_root / "approval_audit_events.jsonl",
    )


def _is_rux_disposition_approval(approval: ApprovalGate) -> bool:
    return (
        approval.target_type == "medical_monitoring_risk_disposition"
    )


def _is_runtime_evidence_picos_approval(approval: ApprovalGate, approval_store) -> bool:
    if approval.target_type != "evidence_picos_snapshot":
        return False
    return any(
        stored.approval_id == approval.approval_id
        and stored.target_type == approval.target_type
        and stored.target_id == approval.target_id
        and stored.target_revision == approval.target_revision
        for stored in approval_store.gates(approval.project_id)
    )


def _approval_target_matches_module(target_type: str, module: str) -> bool:
    mapped_target = {
        "evidence_picos_snapshot": "evidence_design",
    }.get(target_type, target_type)
    return mapped_target.startswith(module)


class DemoRepository:
    def __init__(self, data_path: Path, approval_store: ApprovalRuntimeStore | None = None):
        self.data_path = data_path
        self.approval_store = approval_store or _default_approval_store(data_path)
        self._data: Dict[str, Any] | None = None

    @property
    def data(self) -> Dict[str, Any]:
        if self._data is None:
            loaded: Dict[str, Any] = {}
            if self.data_path.exists():
                with self.data_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
            if "subject_monitoring_profiles" not in loaded:
                from scripts.generate_demo_data import build_demo

                loaded = build_demo()
            self._data = loaded
        self._merge_runtime_approval_overlay(self._data)
        return self._data

    def _merge_runtime_approval_overlay(self, data: Dict[str, Any]) -> None:
        runtime_gates = [gate.model_dump(mode="json") for gate in self.approval_store.gates()]
        gate_keys = {(item["project_id"], item["approval_id"]) for item in runtime_gates}
        if runtime_gates:
            data["approval_gates"] = [
                item
                for item in data.setdefault("approval_gates", [])
                if (item.get("project_id"), item.get("approval_id")) not in gate_keys
            ] + runtime_gates

        runtime_decisions = [decision.model_dump(mode="json") for decision in self.approval_store.decisions()]
        decision_keys = {item["decision_id"] for item in runtime_decisions}
        if runtime_decisions:
            data["approval_decisions"] = [
                item
                for item in data.setdefault("approval_decisions", [])
                if item.get("decision_id") not in decision_keys
            ] + runtime_decisions

        runtime_audits = [event.model_dump(mode="json") for event in self.approval_store.audit_events()]
        audit_keys = {item["audit_id"] for item in runtime_audits}
        if runtime_audits:
            data["audit_events"] = [
                item
                for item in data.setdefault("audit_events", [])
                if item.get("audit_id") not in audit_keys
            ] + runtime_audits

    def projects(self) -> List[Project]:
        return [Project.model_validate(item) for item in self.data["projects"]]

    def project(self, project_id: str) -> Project:
        for project in self.projects():
            if project.project_id == project_id:
                return project
        raise KeyError(project_id)

    def batches(self, project_id: str) -> List[DataBatch]:
        return [
            DataBatch.model_validate(item)
            for item in self.data["data_batches"]
            if item["project_id"] == project_id
        ]

    def risks(self, project_id: str) -> List[RiskCase]:
        return [
            RiskCase.model_validate(item)
            for item in self.data["risk_cases"]
            if item["project_id"] == project_id
        ]

    def approvals(self, project_id: str) -> List[ApprovalGate]:
        return [
            ApprovalGate.model_validate(item)
            for item in self.data["approval_gates"]
            if item["project_id"] == project_id
        ]

    def approval(self, project_id: str, approval_id: str) -> ApprovalGate:
        for item in self.data["approval_gates"]:
            if item["project_id"] == project_id and item["approval_id"] == approval_id:
                return ApprovalGate.model_validate(item)
        self.project(project_id)
        raise KeyError(f"{project_id}/{approval_id}")

    def approval_blockers(self, project_id: str, approval_id: str) -> List[ApprovalBlocker]:
        approval = self.approval(project_id, approval_id)
        terminal_risk_statuses = {RiskStatus.CLOSED, RiskStatus.SUPERSEDED}
        blockers: List[ApprovalBlocker] = []

        if approval.target_type == "medical_monitoring_risk_batch":
            for risk in self.risks(project_id):
                if (
                    risk.module == "medical_monitoring"
                    and risk.source_batch_id == approval.target_id
                    and risk.status not in terminal_risk_statuses
                ):
                    blockers.append(
                        ApprovalBlocker(
                            blocker_id=f"risk:{risk.risk_id}",
                            blocker_type="open_risk",
                            source_type="risk_case",
                            source_id=risk.risk_id,
                            severity=risk.severity,
                            message=f"{risk.title} 仍为 {risk.status.value}",
                        )
                    )

        if approval.target_type == "medical_writing_protocol_section":
            protocol = self.protocol(project_id)
            target_section = next(
                (section for section in protocol.sections if section.section_id == approval.target_id),
                None,
            )
            if target_section is not None and target_section.evidence_coverage < 0.6:
                blockers.append(
                    ApprovalBlocker(
                        blocker_id=f"evidence:{target_section.section_id}",
                        blocker_type="low_evidence_coverage",
                        source_type="protocol_section",
                        source_id=target_section.section_id,
                        severity=RiskSeverity.HIGH,
                        message=f"证据覆盖率 {target_section.evidence_coverage:.0%}，低于批准阈值 60%",
                    )
                )

            for gate in protocol.quality_gates:
                if gate.get("status") == "blocking":
                    blockers.append(
                        ApprovalBlocker(
                            blocker_id=f"quality_gate:{gate.get('gate_id', 'unknown')}",
                            blocker_type="quality_gate",
                            source_type="protocol_quality_gate",
                            source_id=str(gate.get("gate_id", "")),
                            severity=RiskSeverity.HIGH,
                            message=str(gate.get("label", "质量门阻断")),
                        )
                    )

            for risk in self.risks(project_id):
                if risk.module == "medical_writing" and risk.status not in terminal_risk_statuses:
                    blockers.append(
                        ApprovalBlocker(
                            blocker_id=f"risk:{risk.risk_id}",
                            blocker_type="open_risk",
                            source_type="risk_case",
                            source_id=risk.risk_id,
                            severity=risk.severity,
                            message=f"{risk.title} 仍为 {risk.status.value}",
                        )
                    )

            for thread in self.revision_threads(project_id):
                if thread.section_id == approval.target_id and thread.status == "open":
                    blockers.append(
                        ApprovalBlocker(
                            blocker_id=f"revision_thread:{thread.thread_id}",
                            blocker_type="open_revision_thread",
                            source_type="revision_thread",
                            source_id=thread.thread_id,
                            severity=RiskSeverity.MEDIUM,
                            message=f"修订线程 {thread.thread_id} 尚未关闭",
                        )
                    )

        return blockers

    def record_approval_action(
        self,
        project_id: str,
        approval_id: str,
        request: ApprovalActionRequest,
    ) -> ApprovalActionResult:
        approval = self.approval(project_id, approval_id)
        blockers = self.approval_blockers(project_id, approval_id)
        if hasattr(self.approval_store, "commit_approval_action") and (
            _is_rux_disposition_approval(approval)
            or _is_runtime_evidence_picos_approval(approval, self.approval_store)
        ):
            return self._record_runtime_approval_action(approval, blockers, request)
        previous_state = approval.state
        new_state = previous_state
        action_blocked = request.action == ApprovalAction.APPROVE and bool(blockers)

        if not action_blocked:
            if request.action == ApprovalAction.APPROVE:
                new_state = ApprovalState.MEDICALLY_APPROVED
            elif request.action == ApprovalAction.RETURN_FOR_REVISION:
                new_state = ApprovalState.RETURNED_FOR_REVISION
            elif request.action == ApprovalAction.REJECT:
                new_state = ApprovalState.SUPERSEDED

        now = datetime.now(timezone.utc)
        should_update_gate = request.action != ApprovalAction.VIEW_QUALITY_GATE and not action_blocked
        if should_update_gate:
            for item in self.data.setdefault("approval_gates", []):
                if item["project_id"] == project_id and item["approval_id"] == approval_id:
                    item["state"] = new_state.value
                    item["reviewed_by"] = request.actor
                    if request.action == ApprovalAction.APPROVE:
                        item["approved_by"] = request.actor
                    if request.comment:
                        item["review_comments"] = request.comment
                    item["updated_at"] = now.isoformat()
                    approval = ApprovalGate.model_validate(item)
                    break

        runtime_approval = _is_rux_disposition_approval(approval)
        audit_events = self.data.setdefault("audit_events", [])
        audit_count = len(audit_events)
        audit_event = AuditEvent(
            audit_id=f"audit_approval_{audit_count + 1:04d}",
            project_id=project_id,
            actor=request.actor,
            action=f"approval.{request.action.value}{'.blocked' if action_blocked else ''}",
            target_type="approval_gate",
            target_id=approval_id,
            detail={
                "previous_state": previous_state.value,
                "new_state": new_state.value,
                "comment": request.comment,
                "blocked": action_blocked,
                "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
            },
            created_at=now,
        )
        audit_events.append(audit_event.model_dump(mode="json"))

        decisions = self.data.setdefault("approval_decisions", [])
        decision_count = len(decisions)
        decision = ApprovalDecisionRecord(
            decision_id=f"decision_approval_{decision_count + 1:04d}",
            approval_id=approval_id,
            project_id=project_id,
            action=request.action,
            actor=request.actor,
            previous_state=previous_state,
            new_state=new_state,
            comment=request.comment,
            blocked=action_blocked,
            blockers=blockers,
            audit_event_id=audit_event.audit_id,
            created_at=now,
        )
        decisions.append(decision.model_dump(mode="json"))
        if runtime_approval:
            if should_update_gate:
                self.approval_store.upsert_gate(approval)
            self.approval_store.append_audit_event(audit_event)
            self.approval_store.append_decision(decision)

        return ApprovalActionResult(
            approval=approval,
            decision=decision,
            audit_event=audit_event,
            blockers=blockers,
        )

    def _record_runtime_approval_action(
        self,
        approval: ApprovalGate,
        blockers: List[ApprovalBlocker],
        request: ApprovalActionRequest,
    ) -> ApprovalActionResult:
        previous_state = approval.state
        new_state = previous_state
        action_blocked = request.action == ApprovalAction.APPROVE and bool(blockers)
        if not action_blocked:
            if request.action == ApprovalAction.APPROVE:
                new_state = ApprovalState.MEDICALLY_APPROVED
            elif request.action == ApprovalAction.RETURN_FOR_REVISION:
                new_state = ApprovalState.RETURNED_FOR_REVISION
            elif request.action == ApprovalAction.REJECT:
                new_state = ApprovalState.SUPERSEDED

        now = datetime.now(timezone.utc)
        should_update_gate = request.action != ApprovalAction.VIEW_QUALITY_GATE and not action_blocked
        approval_for_write = None
        result_approval = approval
        if should_update_gate:
            updates = {
                "state": new_state,
                "reviewed_by": request.actor,
                "updated_at": now,
            }
            if request.action == ApprovalAction.APPROVE:
                updates["approved_by"] = request.actor
            if request.comment:
                updates["review_comments"] = request.comment
            result_approval = approval.model_copy(update=updates)
            approval_for_write = result_approval

        request_payload = {
            "project_id": approval.project_id,
            "approval_id": approval.approval_id,
            "action": request.action.value,
            "actor": request.actor,
            "comment": request.comment,
        }
        request_fingerprint = sha256(
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        idempotency_key = request.idempotency_key.strip() or f"auto:{uuid4().hex}"
        token = sha256(
            f"{approval.project_id}:{approval.approval_id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()[:20]
        audit_event = AuditEvent(
            audit_id=f"audit_approval_{token}",
            project_id=approval.project_id,
            actor=request.actor,
            action=f"approval.{request.action.value}{'.blocked' if action_blocked else ''}",
            target_type="approval_gate",
            target_id=approval.approval_id,
            detail={
                "previous_state": previous_state.value,
                "new_state": new_state.value,
                "comment": request.comment,
                "blocked": action_blocked,
                "blockers": [blocker.model_dump(mode="json") for blocker in blockers],
            },
            created_at=now,
        )
        decision = ApprovalDecisionRecord(
            decision_id=f"decision_approval_{token}",
            approval_id=approval.approval_id,
            project_id=approval.project_id,
            action=request.action,
            actor=request.actor,
            previous_state=previous_state,
            new_state=new_state,
            comment=request.comment,
            blocked=action_blocked,
            blockers=blockers,
            audit_event_id=audit_event.audit_id,
            created_at=now,
        )
        commit_result = self.approval_store.commit_approval_action(
            approval_for_write,
            audit_event,
            decision,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if commit_result.replayed:
            stored_gates = [
                item
                for item in self.approval_store.gates(approval.project_id)
                if item.approval_id == approval.approval_id
            ]
            stored_audits = [
                item
                for item in self.approval_store.audit_events(approval.project_id)
                if item.audit_id == audit_event.audit_id
            ]
            stored_decisions = [
                item
                for item in self.approval_store.decisions(approval.project_id)
                if item.decision_id == decision.decision_id
            ]
            if stored_gates:
                result_approval = stored_gates[-1]
            if stored_audits:
                audit_event = stored_audits[-1]
            if stored_decisions:
                decision = stored_decisions[-1]
        if self._data is not None:
            self._merge_runtime_approval_overlay(self._data)
        return ApprovalActionResult(
            approval=result_approval,
            decision=decision,
            audit_event=audit_event,
            blockers=blockers,
        )

    def protocol(self, project_id: str) -> ProtocolDocument:
        for item in self.data["protocol_documents"]:
            if item["project_id"] == project_id:
                return ProtocolDocument.model_validate(item)
        raise KeyError(project_id)

    def revision_threads(self, project_id: str) -> List[RevisionThread]:
        return [
            RevisionThread.model_validate(item)
            for item in self.data["revision_threads"]
            if item["project_id"] == project_id
        ]

    def revision_thread(self, project_id: str, thread_id: str) -> RevisionThread:
        self.project(project_id)
        for item in self.data.setdefault("revision_threads", []):
            if item["project_id"] == project_id and item["thread_id"] == thread_id:
                return RevisionThread.model_validate(item)
        raise KeyError(f"{project_id}/{thread_id}")

    def add_revision_thread(self, thread: RevisionThread) -> None:
        self.project(thread.project_id)
        threads = self.data.setdefault("revision_threads", [])
        if any(item["thread_id"] == thread.thread_id for item in threads):
            raise KeyError(thread.thread_id)
        threads.append(thread.model_dump(mode="json"))

    def replace_revision_thread(self, thread: RevisionThread) -> None:
        self.project(thread.project_id)
        threads = self.data.setdefault("revision_threads", [])
        for index, item in enumerate(threads):
            if item["project_id"] == thread.project_id and item["thread_id"] == thread.thread_id:
                threads[index] = thread.model_dump(mode="json")
                return
        raise KeyError(f"{thread.project_id}/{thread.thread_id}")

    def ensure_revision_approval_gate(self, thread: RevisionThread, requested_by: str) -> ApprovalGate:
        self.project(thread.project_id)
        now = datetime.now(timezone.utc)
        approval_id = f"approval_revision_{thread.thread_id}"
        review_comments = "医学写作修订建议已接受，仍待医学批准；正式写入前需复核证据、版本影响和上下游文件一致性。"
        approvals = self.data.setdefault("approval_gates", [])
        for item in approvals:
            if item["project_id"] == thread.project_id and item["approval_id"] == approval_id:
                item["state"] = ApprovalState.IN_MEDICAL_REVIEW.value
                item["requested_by"] = requested_by
                item["review_comments"] = review_comments
                item["updated_at"] = now.isoformat()
                return ApprovalGate.model_validate(item)

        approval = ApprovalGate(
            approval_id=approval_id,
            project_id=thread.project_id,
            target_type="medical_writing_revision_thread",
            target_id=thread.thread_id,
            state=ApprovalState.IN_MEDICAL_REVIEW,
            requested_by=requested_by,
            review_comments=review_comments,
            created_at=now,
            updated_at=now,
        )
        approvals.append(approval.model_dump(mode="json"))
        return approval

    def ensure_rux_disposition_approval_gate(
        self,
        project_id: str,
        risk_id: str,
        subject_id: str,
        rule_id: str,
        requested_by: str,
        risk_title: str = "",
        source_token: str = "",
    ) -> ApprovalGate:
        approval = self.prepare_rux_disposition_approval_gate(
            project_id=project_id,
            risk_id=risk_id,
            subject_id=subject_id,
            rule_id=rule_id,
            requested_by=requested_by,
            risk_title=risk_title,
            source_token=source_token,
        )
        approvals = self.data.setdefault("approval_gates", [])
        for index, item in enumerate(approvals):
            if item["project_id"] == project_id and item["approval_id"] == approval.approval_id:
                approval = approval.model_copy(
                    update={"created_at": ApprovalGate.model_validate(item).created_at}
                )
                approvals[index] = approval.model_dump(mode="json")
                self.approval_store.upsert_gate(approval)
                return approval
        approvals.append(approval.model_dump(mode="json"))
        self.approval_store.upsert_gate(approval)
        return approval

    def ensure_monitoring_disposition_approval_gate(
        self,
        project_id: str,
        project_label: str,
        risk_id: str,
        subject_id: str,
        rule_id: str,
        requested_by: str,
        risk_title: str = "",
        source_token: str = "",
    ) -> ApprovalGate:
        if project_id == "proj_rux_03_002":
            return self.ensure_rux_disposition_approval_gate(
                project_id,
                risk_id,
                subject_id,
                rule_id,
                requested_by,
                risk_title,
                source_token,
            )
        approval = self.prepare_monitoring_disposition_approval_gate(
            project_id=project_id,
            project_label=project_label,
            risk_id=risk_id,
            subject_id=subject_id,
            rule_id=rule_id,
            requested_by=requested_by,
            risk_title=risk_title,
            source_token=source_token,
        )
        approvals = self.data.setdefault("approval_gates", [])
        for index, item in enumerate(approvals):
            if item["project_id"] == project_id and item["approval_id"] == approval.approval_id:
                approval = approval.model_copy(update={"created_at": ApprovalGate.model_validate(item).created_at})
                approvals[index] = approval.model_dump(mode="json")
                self.approval_store.upsert_gate(approval)
                return approval
        approvals.append(approval.model_dump(mode="json"))
        self.approval_store.upsert_gate(approval)
        return approval

    def prepare_rux_disposition_approval_gate(
        self,
        project_id: str,
        risk_id: str,
        subject_id: str,
        rule_id: str,
        requested_by: str,
        risk_title: str = "",
        source_token: str = "",
    ) -> ApprovalGate:
        now = datetime.now(timezone.utc)
        clean_source_token = source_token or sha1(f"{project_id}:{risk_id}:{subject_id}:{rule_id}".encode("utf-8")).hexdigest()[:12]
        approval_id = f"approval_rux_disposition_{risk_id}_{clean_source_token}"
        risk_label = risk_title.strip() or "医学监查风险"
        review_comments = (
            f"RUX-03-002内部Query草稿/处置建议审批；风险：{risk_label}；"
            f"受试者：{subject_id}；规则：{rule_id}；"
            "仅批准内部Query草稿/处置建议，不代表对外Query已执行、风险关闭或归档。"
        )
        return ApprovalGate(
            approval_id=approval_id,
            project_id=project_id,
            target_type="medical_monitoring_risk_disposition",
            target_id=risk_id,
            state=ApprovalState.IN_MEDICAL_REVIEW,
            requested_by=requested_by,
            review_comments=review_comments,
            created_at=now,
            updated_at=now,
        )

    def prepare_monitoring_disposition_approval_gate(
        self,
        project_id: str,
        project_label: str,
        risk_id: str,
        subject_id: str,
        rule_id: str,
        requested_by: str,
        risk_title: str = "",
        source_token: str = "",
    ) -> ApprovalGate:
        if project_id == "proj_rux_03_002":
            return self.prepare_rux_disposition_approval_gate(
                project_id,
                risk_id,
                subject_id,
                rule_id,
                requested_by,
                risk_title,
                source_token,
            )
        now = datetime.now(timezone.utc)
        clean_source_token = source_token or sha1(
            f"{project_id}:{risk_id}:{subject_id}:{rule_id}".encode("utf-8")
        ).hexdigest()[:12]
        approval_id = f"approval_monitoring_disposition_{risk_id}_{clean_source_token}"
        risk_label = risk_title.strip() or "医学监查风险"
        review_comments = (
            f"{project_label}内部Query草稿/处置建议审批；风险：{risk_label}；"
            f"受试者：{subject_id}；规则：{rule_id}；"
            "仅批准内部Query草稿/处置建议，不代表对外Query已执行、风险关闭或归档。"
        )
        return ApprovalGate(
            approval_id=approval_id,
            project_id=project_id,
            target_type="medical_monitoring_risk_disposition",
            target_id=risk_id,
            state=ApprovalState.IN_MEDICAL_REVIEW,
            requested_by=requested_by,
            review_comments=review_comments,
            created_at=now,
            updated_at=now,
        )

    def record_ai_run(self, ai_run: AiRun) -> None:
        self.project(ai_run.project_id)
        runs = self.data.setdefault("ai_runs", [])
        if not any(item["ai_run_id"] == ai_run.ai_run_id for item in runs):
            runs.append(ai_run.model_dump(mode="json"))

    def record_audit_event(self, event: AuditEvent) -> None:
        self.project(event.project_id)
        events = self.data.setdefault("audit_events", [])
        if not any(item["audit_id"] == event.audit_id for item in events):
            events.append(event.model_dump(mode="json"))

    def audit_events(self, project_id: str) -> List[AuditEvent]:
        self.project(project_id)
        return [
            AuditEvent.model_validate(item)
            for item in self.data.setdefault("audit_events", [])
            if item["project_id"] == project_id
        ]

    def module_catalog(self, project_id: str) -> ModuleCatalog:
        self.project(project_id)
        return ModuleCatalog(
            project_id=project_id,
            generated_at=datetime.now(timezone.utc),
            modules=module_manifests(),
        )

    def subject_monitoring_profiles(self, project_id: str) -> List[SubjectMonitoringDrilldown]:
        return [
            SubjectMonitoringDrilldown.model_validate(item)
            for item in self.data["subject_monitoring_profiles"]
            if item["project_id"] == project_id
        ]

    def subject_monitoring(self, project_id: str, subject_id: str) -> SubjectMonitoringDrilldown:
        self.project(project_id)
        for item in self.data["subject_monitoring_profiles"]:
            if item["project_id"] == project_id and item["subject_id"] == subject_id:
                return SubjectMonitoringDrilldown.model_validate(item)
        raise KeyError(f"{project_id}/{subject_id}")

    def record_monitoring_intake(self, result) -> None:
        self.project(result.project_id)
        batches = self.data.setdefault("data_batches", [])
        if not any(item["batch_id"] == result.batch.batch_id for item in batches):
            batches.append(result.batch.model_dump(mode="json"))

        risks = self.data.setdefault("risk_cases", [])
        existing_risk_ids = {item["risk_id"] for item in risks}
        for risk in result.generated_risks:
            if risk.risk_id not in existing_risk_ids:
                risks.append(risk.model_dump(mode="json"))
                existing_risk_ids.add(risk.risk_id)

        audit_events = self.data.setdefault("audit_events", [])
        existing_audit_ids = {item["audit_id"] for item in audit_events}
        for event in result.audit_preview:
            if event.audit_id not in existing_audit_ids:
                audit_events.append(event.model_dump(mode="json"))
                existing_audit_ids.add(event.audit_id)

    def dashboard(self, project_id: str) -> DashboardSummary:
        project = self.project(project_id)
        batches = self.batches(project_id)
        risks = self.risks(project_id)
        approvals = self.approvals(project_id)
        open_risks = [risk for risk in risks if risk.status not in {RiskStatus.CLOSED, RiskStatus.SUPERSEDED}]
        pending_approvals = [item for item in approvals if item.state.value in {"ai_draft", "in_medical_review", "returned_for_revision"}]
        severity_counts = Counter(risk.severity.value for risk in open_risks)
        modules = []
        completion_rate = {
            "dashboard": 0.35,
            "evidence_design": 0.12,
            "eligibility_review": 0.55,
            "medical_monitoring": 0.42,
            "data_analysis_tfl": 0.10,
            "medical_writing": 0.38,
            "safety_pv": 0.08,
            "approvals": 0.30,
        }
        for manifest in module_manifests():
            if not manifest.visible_in_dashboard:
                continue
            module = manifest.module
            module_risks = [risk for risk in open_risks if risk.module == module]
            module_approvals = [
                item
                for item in pending_approvals
                if _approval_target_matches_module(item.target_type, module)
            ]
            modules.append(
                ModuleStatus(
                    module=module,
                    label=manifest.label,
                    status=manifest.implementation_status,
                    completion_rate=completion_rate.get(module, 0.0),
                    open_risk_count=len(module_risks),
                    pending_task_count=len(module_risks),
                    pending_approval_count=len(module_approvals),
                )
            )
        return DashboardSummary(
            project=project,
            modules=modules,
            latest_batch=batches[-1] if batches else None,
            risk_counts_by_severity=dict(severity_counts),
            pending_approvals=pending_approvals,
            recent_risks=sorted(open_risks, key=lambda item: item.created_at, reverse=True)[:10],
        )


def module_manifests() -> List[ModuleManifest]:
    return [
        ModuleManifest(
            module="dashboard",
            label="项目总看板",
            lifecycle_step=None,
            medical_role="command_center",
            implementation_status="active_demo",
            route_key="overview",
            source_inputs=["Project", "DataBatch", "RiskCase", "ApprovalGate", "AuditEvent"],
            ai_task_types=[],
            dependencies=["evidence_design", "eligibility_review", "medical_monitoring", "data_analysis_tfl", "medical_writing", "safety_pv", "approvals"],
            acceptance_status="demo_qc_partial",
            note="项目级入口已可展示入排审核、医学监查、医学写作和审批状态；仍需接入全模块任务队列和真实未读逻辑。",
        ),
        ModuleManifest(
            module="evidence_design",
            label="证据调研与方案设计",
            lifecycle_step=None,
            medical_role="primary_owner",
            implementation_status="planned_p0",
            route_key="evidence-design",
            source_inputs=["guidelines", "registries", "publications", "competitor protocols", "regulatory reviews"],
            ai_task_types=[
                "disease_background_research",
                "competitive_intelligence",
                "protocol_design_synthesis",
                "picos_design_coach",
            ],
            dependencies=["medical_writing"],
            acceptance_status="not_started",
            note="需从原始公开资料和本地竞品原文定期更新，不得直接使用既有深度调研结果作为生产输入。",
        ),
        ModuleManifest(
            module="eligibility_review",
            label="入排审核",
            lifecycle_step=None,
            medical_role="involved_owner",
            implementation_status="active_demo",
            route_key="eligibility",
            source_inputs=["protocol document", "raw subject bundle", "OCR/VLM spans", "site responses"],
            ai_task_types=["protocol_rule_extraction", "eligibility_rule_review"],
            dependencies=["approvals", "dashboard"],
            acceptance_status="legacy_adapter_partial",
            note="当前接入旧系统只读桥接；正式链路必须从原始方案和原始受试者资料重新抽取规则与证据。",
        ),
        ModuleManifest(
            module="medical_monitoring",
            label="医学监查",
            lifecycle_step=None,
            medical_role="primary_owner",
            implementation_status="active_demo",
            route_key="monitoring",
            source_inputs=["raw data listing", "protocol", "subject status report", "risk ledger"],
            ai_task_types=["monitoring_risk_interpretation", "subject_timeline_derivation", "patient_profile_derivation"],
            dependencies=["data_analysis_tfl", "approvals", "dashboard"],
            acceptance_status="raw_listing_partial",
            note="已有原始listing解析、批次diff和demo规则；原始数据采集质量作为本模块输入治理，不单独建设子系统；正式风险解释、timeline/profile派生仍需独立AI Gateway。",
        ),
        ModuleManifest(
            module="data_analysis_tfl",
            label="数据分析与TFL",
            lifecycle_step=None,
            medical_role="involved_owner",
            implementation_status="planned_p1",
            route_key="tfl",
            source_inputs=["SDTM datasets", "ADaM datasets", "define.xml", "SAP", "TFL shells"],
            ai_task_types=["tfl_generation_assist", "analysis_result_explanation"],
            dependencies=["medical_monitoring", "medical_writing"],
            acceptance_status="not_started",
            note="需借鉴Ruxolitinib-AD CDE回复中SDTM/ADaM/TFL路径，形成医学可查看和监管交付视图。",
        ),
        ModuleManifest(
            module="medical_writing",
            label="医学写作",
            lifecycle_step=None,
            medical_role="primary_owner",
            implementation_status="active_demo",
            route_key="writing",
            source_inputs=["protocol", "IB", "ICF", "CSR", "CTD", "evidence spans", "review comments"],
            ai_task_types=["medical_writing_revision", "cross_document_consistency_check"],
            dependencies=["evidence_design", "eligibility_review", "medical_monitoring", "data_analysis_tfl", "approvals"],
            acceptance_status="workflow_stub",
            note="当前是研究方案优先的富文本与revision状态机；真实写作输出必须接入独立AI provider。",
        ),
        ModuleManifest(
            module="safety_pv",
            label="安全信号与PV协同",
            lifecycle_step=None,
            medical_role="involved_owner",
            implementation_status="planned_p1",
            route_key="safety",
            source_inputs=["安全性listing", "PV提供的个案叙述资料", "DSUR/IB安全更新素材", "安全计划参考资料", "医学监查风险账本"],
            ai_task_types=["safety_case_medical_review", "signal_narrative_synthesis"],
            dependencies=["medical_monitoring", "medical_writing", "approvals"],
            acceptance_status="not_started",
            note="不替代PV系统；用于医学经理整理安全资料证据链、形成待医学/PV确认候选和跨模块安全一致性核对。",
        ),
        ModuleManifest(
            module="approvals",
            label="审批中心",
            lifecycle_step=None,
            medical_role="governance",
            implementation_status="active_demo",
            route_key="approvals",
            source_inputs=["ApprovalGate", "ApprovalBlocker", "AuditEvent"],
            ai_task_types=[],
            dependencies=["eligibility_review", "medical_monitoring", "medical_writing"],
            acceptance_status="demo_qc_partial",
            note="已有审批动作和质量门阻断；仍需覆盖证据调研与方案设计、数据分析与TFL、安全信号与PV协同的产物和真实电子签名/归档策略。",
        ),
    ]
