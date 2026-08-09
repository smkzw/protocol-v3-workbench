from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha1, sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional, Tuple

from packages.contracts.workbench_contracts import (
    ApprovalState,
    AiTaskRunStatus,
    MonitoringMedicalJudgments,
    MonitoringRiskDispositionKind,
    RiskCase,
    RiskSeverity,
    RiskStatus,
    RuxRiskDispositionAction,
    RuxRiskDispositionActionRequest,
    RuxRiskDispositionRecord,
    SafetyMonitoringCollaborationHandoff,
    WorkbenchInboxActionRecord,
    WorkbenchInboxResult,
    WorkbenchItem,
    WorkbenchItemAction,
    WorkbenchItemActionRequest,
    WorkbenchItemSourceRef,
    WorkbenchModuleInboxSummary,
)


LOGGER = logging.getLogger(__name__)
RUX_PROJECT_ID = "proj_rux_03_002"
RUX_P0_SUBJECT_IDS = ("S01017", "S01003", "S03040")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkbenchInboxStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: WorkbenchInboxActionRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def records(self, project_id: str, actor: str = "medical_manager") -> List[WorkbenchInboxActionRecord]:
        if not self.path.exists():
            return []
        records: List[WorkbenchInboxActionRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("project_id") != project_id or payload.get("actor", "medical_manager") != actor:
                    continue
                try:
                    records.append(WorkbenchInboxActionRecord.model_validate(payload))
                except Exception:
                    continue
        return records


class RuxRiskDispositionStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: RuxRiskDispositionRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def records(self, project_id: str) -> List[RuxRiskDispositionRecord]:
        if not self.path.exists():
            return []
        records: List[RuxRiskDispositionRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("project_id") != project_id:
                    continue
                try:
                    records.append(RuxRiskDispositionRecord.model_validate(payload))
                except Exception:
                    continue
        return records


class WorkbenchInboxService:
    def __init__(
        self,
        repo,
        ai_task_runner,
        evidence_picos_workflow_service,
        tfl_writing_handoff_service,
        safety_review_workbench_service,
        medical_writing_manifest_service,
        source_registry_service,
        eligibility_adapter,
        store: WorkbenchInboxStore,
        rux_monitoring_service=None,
        rux_disposition_store: Optional[RuxRiskDispositionStore] = None,
        monitoring_services: Optional[Dict[str, Any]] = None,
        project_source_manifest_service=None,
        medical_risk_repository=None,
        notifications_path: Optional[Path] = None,
        monitoring_query_workflow_policies: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self.repo = repo
        self.ai_task_runner = ai_task_runner
        self.evidence_picos_workflow_service = evidence_picos_workflow_service
        self.tfl_writing_handoff_service = tfl_writing_handoff_service
        self.safety_review_workbench_service = safety_review_workbench_service
        self.medical_writing_manifest_service = medical_writing_manifest_service
        self.source_registry_service = source_registry_service
        self.eligibility_adapter = eligibility_adapter
        self.store = store
        self.rux_monitoring_service = rux_monitoring_service
        self.rux_disposition_store = rux_disposition_store
        self.monitoring_services = dict(monitoring_services or {})
        self.project_source_manifest_service = project_source_manifest_service
        self.medical_risk_repository = medical_risk_repository
        self.notifications_path = notifications_path
        self.monitoring_query_workflow_policies = {
            RUX_PROJECT_ID: {
                "internal_approval_required": True,
                "formal_send_managed_outside_monitoring": True,
            },
            "proj_my009_uc": {
                "internal_approval_required": True,
                "formal_send_managed_outside_monitoring": True,
            },
            **dict(monitoring_query_workflow_policies or {}),
        }

    def monitoring_query_workflow_policy(self, project_id: str) -> Dict[str, Any]:
        configured = self.monitoring_query_workflow_policies.get(project_id, {})
        return {
            "internal_approval_required": bool(
                configured.get("internal_approval_required", False)
            ),
            "formal_send_managed_outside_monitoring": bool(
                configured.get("formal_send_managed_outside_monitoring", True)
            ),
        }

    def inbox(self, project_id: str, actor: str = "medical_manager", limit: int = 80) -> WorkbenchInboxResult:
        self._assert_project_available(project_id)
        items = self._build_items(project_id)
        read_versions = _read_versions(self.store.records(project_id, actor))
        hydrated = [
            item.model_copy(update={"unread": read_versions.get(item.item_id) != item.source_version})
            for item in items
        ]
        hydrated.sort(key=_item_sort_key)
        visible_items = _select_visible_items(hydrated, limit)

        return WorkbenchInboxResult(
            project_id=project_id,
            generated_at=utc_now(),
            total_open_count=len(hydrated),
            unread_count=sum(1 for item in hydrated if item.unread),
            handoff_count=sum(1 for item in hydrated if item.item_type == "handoff"),
            items=visible_items,
            module_summaries=_module_summaries(self._module_manifests(project_id), hydrated),
        )

    def monitoring_risk_items(self, project_id: str, actor: str = "medical_manager") -> List[WorkbenchItem]:
        items = self._monitoring_risk_items(project_id)
        read_versions = _read_versions(self.store.records(project_id, actor))
        return [
            item.model_copy(update={"unread": read_versions.get(item.item_id) != item.source_version})
            for item in items
        ]

    def safety_monitoring_collaboration_handoffs(
        self,
        project_id: str,
    ) -> List[SafetyMonitoringCollaborationHandoff]:
        if self.rux_disposition_store is None:
            return []
        current_items = self._monitoring_risk_items(project_id)
        current_by_item = {item.item_id: item for item in current_items}
        current_by_risk_key = {
            item.risk_key: item for item in current_items if item.risk_key
        }
        latest_by_risk: Dict[str, RuxRiskDispositionRecord] = {}
        for record in self.rux_disposition_store.records(project_id):
            identity = record.risk_key or record.risk_instance_id or record.item_id
            latest = latest_by_risk.get(identity)
            if latest is None or record.created_at > latest.created_at:
                latest_by_risk[identity] = record

        handoffs: List[SafetyMonitoringCollaborationHandoff] = []
        for record in latest_by_risk.values():
            if (
                record.disposition_kind
                != MonitoringRiskDispositionKind.SAFETY_PV_COLLABORATION
                or record.new_state != MonitoringRiskDispositionKind.SAFETY_PV_COLLABORATION.value
            ):
                continue
            current = current_by_item.get(record.item_id)
            if current is None and record.risk_key:
                current = current_by_risk_key.get(record.risk_key)
            stale_reasons: List[str] = []
            if current is None:
                stale_reasons.append("该风险已不在当前医学监查快照中")
            else:
                if current.source_version != record.source_version:
                    stale_reasons.append("原始数据或规则来源版本已变化")
                if (
                    record.risk_instance_id
                    and current.risk_instance_id
                    and current.risk_instance_id != record.risk_instance_id
                ):
                    stale_reasons.append("风险实例已更新")
                if (
                    record.snapshot_id
                    and current.snapshot_id
                    and current.snapshot_id != record.snapshot_id
                ):
                    stale_reasons.append("医学监查风险快照已更新")
            severity_value = current.priority if current is not None else "medium"
            try:
                severity = RiskSeverity(severity_value)
            except ValueError:
                severity = RiskSeverity.MEDIUM
            title = (
                current.title
                if current is not None
                else f"受试者{record.subject_id} · {record.rule_id or '医学风险'}"
            )
            handoffs.append(
                SafetyMonitoringCollaborationHandoff(
                    handoff_id=f"monitoring-safety-pv:{record.record_id}",
                    project_id=project_id,
                    risk_id=record.risk_id,
                    risk_key=record.risk_key,
                    risk_instance_id=record.risk_instance_id,
                    snapshot_id=record.snapshot_id,
                    subject_id=record.subject_id,
                    rule_id=record.rule_id,
                    title=title,
                    severity=severity,
                    source_version=record.source_version,
                    disposition_record_id=record.record_id,
                    reviewer=record.actor,
                    review_comment=record.comment,
                    source_refs=record.source_refs_snapshot,
                    created_at=record.created_at,
                    is_current=not stale_reasons,
                    stale_reason="；".join(stale_reasons),
                )
            )
        handoffs.sort(key=lambda item: item.created_at, reverse=True)
        return handoffs

    def apply_action(
        self,
        project_id: str,
        item_id: str,
        request: WorkbenchItemActionRequest,
    ) -> WorkbenchInboxResult:
        if request.action != WorkbenchItemAction.MARK_READ:
            raise ValueError(f"unsupported workbench inbox action: {request.action}")
        current_items = {item.item_id: item for item in self._build_items(project_id)}
        item = current_items.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if request.expected_source_version != item.source_version:
            raise ValueError(f"stale_source: current_source_version={item.source_version}")
        created_at = utc_now()
        self.store.append(
            WorkbenchInboxActionRecord(
                record_id=f"workbench_inbox_{created_at.strftime('%Y%m%d%H%M%S%f')}",
                project_id=project_id,
                item_id=item_id,
                action=request.action,
                actor=request.actor,
                source_version=item.source_version,
                comment=request.comment.strip(),
                created_at=created_at,
            )
        )
        return self.inbox(project_id, actor=request.actor)

    def apply_rux_risk_disposition(
        self,
        project_id: str,
        item_id: str,
        request: RuxRiskDispositionActionRequest,
    ) -> WorkbenchInboxResult:
        if project_id != RUX_PROJECT_ID:
            raise ValueError("RUX risk disposition is only available for the RUX medical monitoring project")
        return self._apply_monitoring_risk_disposition(project_id, item_id, request)

    def apply_monitoring_risk_disposition(
        self,
        project_id: str,
        item_id: str,
        request: RuxRiskDispositionActionRequest,
    ) -> WorkbenchInboxResult:
        return self._apply_monitoring_risk_disposition(project_id, item_id, request)

    def require_current_monitoring_approval_source(
        self,
        project_id: str,
        approval_id: str,
    ) -> None:
        approval = self.repo.approval(project_id, approval_id)
        if approval.target_type != "medical_monitoring_risk_disposition":
            return
        current_item = next(
            (item for item in self._monitoring_risk_items(project_id) if item.source_id == approval.target_id),
            None,
        )
        if current_item is None:
            raise ValueError("stale_source: monitoring approval target is no longer current")
        source_token = sha1(
            f"{current_item.item_id}:{current_item.source_version}".encode("utf-8")
        ).hexdigest()[:12]
        expected_prefix = (
            "approval_rux_disposition_"
            if project_id == RUX_PROJECT_ID
            else "approval_monitoring_disposition_"
        )
        expected_id = f"{expected_prefix}{current_item.source_id}_{source_token}"
        if approval.approval_id != expected_id:
            raise ValueError(
                f"stale_source: current_monitoring_approval_id={expected_id}"
            )

    def _apply_monitoring_risk_disposition(
        self,
        project_id: str,
        item_id: str,
        request: RuxRiskDispositionActionRequest,
    ) -> WorkbenchInboxResult:
        if self._monitoring_adapter(project_id) is None:
            raise ValueError("risk disposition is only available for a registered medical monitoring project")
        if self.rux_disposition_store is None:
            raise ValueError("medical monitoring risk disposition store is not configured")
        if not request.actor.strip():
            raise ValueError("actor is required")
        if not request.comment.strip():
            raise ValueError("comment is required")
        if (
            request.action == RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL
            and not self.monitoring_query_workflow_policy(project_id)[
                "internal_approval_required"
            ]
        ):
            raise ValueError(
                "internal approval is disabled by the project query workflow policy"
            )

        current_items = {item.item_id: item for item in self._monitoring_risk_items(project_id)}
        item = current_items.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if request.expected_source_version != item.source_version:
            if hasattr(self.rux_disposition_store, "record_rejection"):
                self.rux_disposition_store.record_rejection(
                    project_id,
                    event_type="stale_source_rejected",
                    operation="rux_disposition" if project_id == RUX_PROJECT_ID else "monitoring_disposition",
                    actor=request.actor.strip(),
                    detail={
                        "item_id": item.item_id,
                        "action": request.action.value,
                        "expected_source_version": request.expected_source_version,
                        "current_source_version": item.source_version,
                    },
                )
            raise ValueError(f"stale_source: current_source_version={item.source_version}")

        request_fingerprint = None
        idempotency_key = None
        if hasattr(self.rux_disposition_store, "commit_rux_disposition"):
            request_payload = {
                "project_id": project_id,
                "item_id": item.item_id,
                "risk_key": item.risk_key,
                "risk_instance_id": item.risk_instance_id,
                "snapshot_id": item.snapshot_id,
                "action": request.action.value,
                "disposition_kind": request.disposition_kind.value if request.disposition_kind else None,
                "actor": request.actor.strip(),
                "comment": request.comment.strip(),
                "query_draft_text": request.query_draft_text.strip(),
                "source_version": item.source_version,
                "medical_judgments": (
                    request.medical_judgments.model_dump(mode="json")
                    if request.medical_judgments
                    else None
                ),
                "expected_disposition_state": request.expected_disposition_state,
                "basis_disposition_record_id": request.basis_disposition_record_id.strip(),
                "reassessment_change_reason": request.reassessment_change_reason.strip(),
            }
            request_fingerprint = sha256(
                json.dumps(request_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            operation = "rux_disposition" if project_id == RUX_PROJECT_ID else "monitoring_disposition"
            key_prefix = "rux" if project_id == RUX_PROJECT_ID else f"monitoring:{project_id}"
            idempotency_key = request.idempotency_key.strip() or f"{key_prefix}:{item.item_id}:{item.source_version}:{request.action.value}"
            replay = self.rux_disposition_store.lookup_idempotent_replay(
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self.inbox(project_id, actor=request.actor)

        previous_record = self._latest_rux_disposition_record(project_id, item.item_id, item.source_version)
        previous_state = previous_record.new_state if previous_record else "pending_review"
        if (
            request.expected_disposition_state
            and request.expected_disposition_state != previous_state
        ):
            if hasattr(self.rux_disposition_store, "record_rejection"):
                self.rux_disposition_store.record_rejection(
                    project_id,
                    event_type="stale_disposition_rejected",
                    operation=(
                        "rux_disposition"
                        if project_id == RUX_PROJECT_ID
                        else "monitoring_disposition"
                    ),
                    actor=request.actor.strip(),
                    detail={
                        "item_id": item.item_id,
                        "action": request.action.value,
                        "expected_disposition_state": request.expected_disposition_state,
                        "current_disposition_state": previous_state,
                        "source_version": item.source_version,
                    },
                )
            raise ValueError(
                f"stale_disposition: current_disposition_state={previous_state}"
            )
        basis_record = None
        if request.basis_disposition_record_id.strip():
            if request.action != RuxRiskDispositionAction.REVIEWED:
                raise ValueError("historical disposition basis is only valid for medical review")
            basis_record = next(
                (
                    record
                    for record in self.rux_disposition_store.records(project_id)
                    if record.record_id == request.basis_disposition_record_id.strip()
                ),
                None,
            )
            if basis_record is None:
                raise ValueError("historical disposition basis was not found")
            if not item.risk_key or basis_record.risk_key != item.risk_key:
                raise ValueError("historical disposition basis belongs to another risk")
            if not basis_record.risk_instance_id or basis_record.risk_instance_id == item.risk_instance_id:
                raise ValueError("historical disposition basis must come from a previous risk instance")
            if basis_record.action == RuxRiskDispositionAction.REOPEN:
                raise ValueError("a reopen record cannot be used as a medical conclusion basis")
            if len(request.reassessment_change_reason.strip()) < 4:
                raise ValueError("reassessment change reason must contain at least 4 characters")
        elif request.reassessment_change_reason.strip():
            raise ValueError("reassessment change reason requires a historical disposition basis")
        try:
            new_state = _validate_rux_disposition_transition(previous_state, request)
        except ValueError as exc:
            if hasattr(self.rux_disposition_store, "record_rejection"):
                self.rux_disposition_store.record_rejection(
                    project_id,
                    event_type="invalid_transition_rejected",
                    operation="rux_disposition" if project_id == RUX_PROJECT_ID else "monitoring_disposition",
                    actor=request.actor.strip(),
                    detail={
                        "item_id": item.item_id,
                        "action": request.action.value,
                        "previous_state": previous_state,
                        "source_version": item.source_version,
                        "reason": str(exc),
                    },
                )
            raise
        created_at = utc_now()
        risk_id = item.source_id
        approval_ref = ""
        approval = None
        if request.action == RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL:
            source_token = sha1(f"{item.item_id}:{item.source_version}".encode("utf-8")).hexdigest()[:12]
            if project_id == RUX_PROJECT_ID:
                approval_builder = (
                    self.repo.prepare_rux_disposition_approval_gate
                    if hasattr(self.rux_disposition_store, "commit_rux_disposition")
                    else self.repo.ensure_rux_disposition_approval_gate
                )
                approval = approval_builder(
                    project_id=project_id,
                    risk_id=risk_id,
                    subject_id=item.target_id,
                    rule_id=item.source_refs[0].source_id if item.source_refs else "",
                    requested_by=request.actor.strip(),
                    risk_title=item.title,
                    source_token=source_token,
                )
            else:
                approval_builder = (
                    self.repo.prepare_monitoring_disposition_approval_gate
                    if hasattr(self.rux_disposition_store, "commit_rux_disposition")
                    else self.repo.ensure_monitoring_disposition_approval_gate
                )
                approval = approval_builder(
                    project_id=project_id,
                    project_label=_monitoring_project_label(project_id),
                    risk_id=risk_id,
                    subject_id=item.target_id,
                    rule_id=item.source_refs[0].source_id if item.source_refs else "",
                    requested_by=request.actor.strip(),
                    risk_title=item.title,
                    source_token=source_token,
                )
            approval_ref = approval.approval_id
        record_prefix = "rux_risk_disposition" if project_id == RUX_PROJECT_ID else "monitoring_risk_disposition"
        record = RuxRiskDispositionRecord(
            record_id=f"{record_prefix}_{created_at.strftime('%Y%m%d%H%M%S%f')}",
            project_id=project_id,
            item_id=item.item_id,
            risk_id=risk_id,
            risk_key=item.risk_key,
            risk_instance_id=item.risk_instance_id,
            snapshot_id=item.snapshot_id,
            subject_id=item.target_id,
            rule_id=item.source_refs[0].source_id if item.source_refs else "",
            action=request.action,
            disposition_kind=(
                None
                if request.action == RuxRiskDispositionAction.REOPEN
                else request.disposition_kind
                if request.disposition_kind is not None
                else previous_record.disposition_kind if previous_record else None
            ),
            previous_state=previous_state,
            new_state=new_state,
            actor=request.actor.strip(),
            comment=request.comment.strip(),
            query_draft_text=(request.query_draft_text or request.comment).strip() if request.action == RuxRiskDispositionAction.QUERY_DRAFT else "",
            approval_ref=approval_ref,
            source_version=item.source_version,
            source_refs_snapshot=item.source_refs,
            medical_judgments=(
                None
                if request.action == RuxRiskDispositionAction.REOPEN
                else request.medical_judgments
                if request.medical_judgments is not None
                else previous_record.medical_judgments if previous_record else None
            ),
            basis_disposition_record_id=(
                basis_record.record_id if basis_record is not None else ""
            ),
            reassessment_change_reason=(
                request.reassessment_change_reason.strip()
                if basis_record is not None
                else ""
            ),
            created_at=created_at,
        )
        if hasattr(self.rux_disposition_store, "commit_rux_disposition"):
            self.rux_disposition_store.commit_rux_disposition(
                record,
                approval=approval,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
                operation="rux_disposition" if project_id == RUX_PROJECT_ID else "monitoring_disposition",
            )
        else:
            self.rux_disposition_store.append(record)
        return self.inbox(project_id, actor=request.actor)

    def _build_items(self, project_id: str) -> List[WorkbenchItem]:
        configured_modules = {manifest.module for manifest in self._module_manifests(project_id)}
        items: List[WorkbenchItem] = []
        if "medical_monitoring" in configured_modules:
            items.extend(self._monitoring_risk_items(project_id))
        if self._monitoring_adapter(project_id) is None and "medical_monitoring" in configured_modules:
            items.extend(self._risk_items(project_id))
        if "approvals" in configured_modules:
            items.extend(self._approval_items(project_id))
        items.extend(item for item in self._ai_run_items(project_id) if item.module in configured_modules)
        if "evidence_design" in configured_modules:
            items.extend(self._picos_items(project_id))
        if "data_analysis_tfl" in configured_modules:
            items.extend(self._tfl_handoff_items(project_id))
        if "safety_pv" in configured_modules:
            items.extend(self._safety_handoff_items(project_id))
        if "medical_writing" in configured_modules:
            items.extend(self._medical_writing_manifest_items(project_id))
        # Durable JSONL notices (e.g. corpus_ready) must surface even when the
        # project module catalog is still bootstrapping medical_writing.
        items.extend(self._workbench_notification_items(project_id))
        items.extend(item for item in self._source_registry_items(project_id) if item.module in configured_modules)
        if "eligibility_review" in configured_modules:
            items.extend(self._eligibility_items(project_id))
        return _dedupe_items(items)

    def _assert_project_available(self, project_id: str) -> None:
        if self._monitoring_adapter(project_id) is not None:
            return
        self.repo.project(project_id)

    def _module_manifests(self, project_id: str):
        if self.project_source_manifest_service is not None:
            manifest = self.project_source_manifest_service.build_manifest(project_id)
            return [
                SimpleNamespace(module=item.module, label=item.label, visible_in_dashboard=True)
                for item in manifest.modules
            ]
        if self._monitoring_adapter(project_id) is not None:
            return [
                SimpleNamespace(module="medical_monitoring", label="医学监查", visible_in_dashboard=True),
            ]
        return self.repo.module_catalog(project_id).modules

    def _monitoring_adapter(self, project_id: str):
        adapter = self.monitoring_services.get(project_id)
        if adapter is not None:
            return adapter
        if project_id == RUX_PROJECT_ID and self.rux_monitoring_service is not None:
            return self.rux_monitoring_service
        return None

    def _monitoring_risk_items(self, project_id: str) -> List[WorkbenchItem]:
        adapter = self._monitoring_adapter(project_id)
        if adapter is None or self.medical_risk_repository is None:
            return []

        items: List[WorkbenchItem] = []
        adapter_source_revision = (
            adapter.source_revision()
            if hasattr(adapter, "source_revision")
            else "legacy:" + _stable_text_token(project_id)
        )
        expected_rule_revision = (
            adapter.risk_profile_revision()
            if hasattr(adapter, "risk_profile_revision")
            else ""
        )
        expected_engine_version = (
            adapter.risk_engine_version()
            if hasattr(adapter, "risk_engine_version")
            else ""
        )
        try:
            snapshot = self.medical_risk_repository.current_snapshot(project_id)
        except KeyError:
            return []
        if (
            snapshot.source_revision != adapter_source_revision
            or snapshot.rule_profile_revision != expected_rule_revision
            or snapshot.engine_version != expected_engine_version
        ):
            return []

        indexed_risks = self.medical_risk_repository.list_risks(
            project_id,
            snapshot.snapshot_id,
        )
        current_snapshot_id = snapshot.snapshot_id
        risk_rows = [
            (risk.subject_id or risk.scope_id, risk)
            for risk in indexed_risks
        ]
        terminal_statuses = {RiskStatus.RESOLVED, RiskStatus.CLOSED, RiskStatus.SUPERSEDED}
        risk_rows = [
            (subject_id, risk)
            for subject_id, risk in risk_rows
            if risk.status not in terminal_statuses
        ]
        for subject_id, risk in risk_rows:
            source_refs = _rux_source_refs(risk)
            is_rux = project_id == RUX_PROJECT_ID
            safety_pv_prefix = (
                "Safety/PV关注；"
                if "safety_pv" in risk.tags
                else ""
            )
            source_version = (
                _rux_source_version(risk, adapter_source_revision)
                if is_rux
                else _monitoring_source_version(risk, adapter_source_revision)
            )
            current_risk_id = risk.risk_instance_id or risk.risk_id
            item_id = f"rux-risk:{current_risk_id}" if is_rux else f"monitoring-risk:{current_risk_id}"
            disposition_record = self._latest_rux_disposition_record(project_id, item_id, source_version)
            disposition_state = disposition_record.new_state if disposition_record else "pending_review"
            approval_required = self.monitoring_query_workflow_policy(project_id)[
                "internal_approval_required"
            ]
            items.append(
                WorkbenchItem(
                    item_id=item_id,
                    project_id=project_id,
                    module="medical_monitoring",
                    module_label="医学监查",
                    item_type="risk",
                    source_type="rux_monitoring_risk" if is_rux else "monitoring_risk",
                    source_id=risk.risk_id,
                    risk_key=risk.risk_key,
                    risk_instance_id=current_risk_id,
                    snapshot_id=current_snapshot_id,
                    title=risk.title,
                    summary=risk.recommended_action or risk.rationale,
                    priority=risk.severity.value if isinstance(risk.severity, RiskSeverity) else str(risk.severity),
                    status=_rux_disposition_status_label(disposition_state),
                    needs_action=_rux_disposition_needs_action(
                        disposition_state,
                        approval_required=approval_required,
                    ),
                    owner_role="医学经理",
                    action_label=_rux_disposition_action_label(
                        disposition_state,
                        approval_required=approval_required,
                    ),
                    target_page="monitoring",
                    target_id=subject_id,
                    source_version=source_version,
                    source_refs=source_refs,
                    updated_at=(
                        disposition_record.created_at
                        if disposition_record is not None
                        else risk.created_at
                    ),
                    boundary_note=(
                        safety_pv_prefix
                        + "基于RUX原始listing、方案条款和当前项目规则版本生成；"
                        "风险索引覆盖本次已评估受试者，但每条结论仍需医学复核。"
                        if is_rux
                        else (
                            safety_pv_prefix
                            + "基于MY009原始listing和已解析方案锚点生成，仅为待医学复核观察项；"
                            "未执行独立AI语义核查的内容不会升级为确定性结论或对外Query。"
                        )
                    ),
                    medical_judgments=disposition_record.medical_judgments if disposition_record else None,
                    disposition_kind=disposition_record.disposition_kind if disposition_record else None,
                )
            )
        current_adapter_identity = (
            adapter.source_revision()
            if hasattr(adapter, "source_revision")
            else "legacy:" + _stable_text_token(project_id),
            adapter.risk_profile_revision()
            if hasattr(adapter, "risk_profile_revision")
            else "",
            adapter.risk_engine_version()
            if hasattr(adapter, "risk_engine_version")
            else "",
        )
        if current_adapter_identity != (
            adapter_source_revision,
            expected_rule_revision,
            expected_engine_version,
        ):
            raise RuntimeError("monitoring snapshot identity changed while the inbox was being built")
        return items

    def _rux_disposition_state(self, project_id: str, item_id: str, source_version: str) -> str:
        latest = self._latest_rux_disposition_record(project_id, item_id, source_version)
        return latest.new_state if latest else "pending_review"

    def _latest_rux_disposition_record(
        self,
        project_id: str,
        item_id: str,
        source_version: str,
    ) -> Optional[RuxRiskDispositionRecord]:
        if self.rux_disposition_store is None:
            return None
        latest: Optional[RuxRiskDispositionRecord] = None
        for record in self.rux_disposition_store.records(project_id):
            if record.item_id != item_id or record.source_version != source_version:
                continue
            if latest is None or record.created_at > latest.created_at:
                latest = record
        return latest

    def _risk_items(self, project_id: str) -> List[WorkbenchItem]:
        items: List[WorkbenchItem] = []
        for risk in self.repo.risks(project_id):
            if risk.status in {RiskStatus.CLOSED, RiskStatus.SUPERSEDED, RiskStatus.RESOLVED}:
                continue
            module_label = _module_label(risk.module)
            target_label = _risk_target_label(risk)
            items.append(
                WorkbenchItem(
                    item_id=f"risk:{risk.risk_id}",
                    project_id=project_id,
                    module=risk.module,
                    module_label=module_label,
                    item_type="risk",
                    source_type="risk_case",
                    source_id=risk.risk_id,
                    title=risk.title,
                    summary=risk.recommended_action or risk.rationale,
                    priority=risk.severity.value,
                    status=_risk_status_label(risk.status),
                    needs_action=risk.status in {RiskStatus.NEW, RiskStatus.ACTION_REQUIRED, RiskStatus.TRIAGED},
                    action_label="进入复核",
                    target_page=_target_page(risk.module),
                    target_id=target_label,
                    source_version=f"{risk.status.value}:{_dt_token(risk.created_at)}:{_dt_token(risk.closed_at)}",
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type="rule",
                            source_id=risk.rule_id,
                            label=risk.rule_id,
                        ),
                        *[
                            WorkbenchItemSourceRef(
                                source_type="evidence_span",
                                source_id=span_id,
                                label=span_id,
                            )
                            for span_id in risk.evidence_span_ids[:4]
                        ],
                    ],
                    updated_at=risk.created_at,
                    boundary_note="风险项需医学经理复核后才能进入关闭、审批或跨模块交接。",
                )
            )
        return items

    def _approval_items(self, project_id: str) -> List[WorkbenchItem]:
        pending_states = {ApprovalState.AI_DRAFT, ApprovalState.IN_MEDICAL_REVIEW, ApprovalState.RETURNED_FOR_REVISION}
        items: List[WorkbenchItem] = []
        for approval in self.repo.approvals(project_id):
            if approval.state not in pending_states:
                continue
            blockers = self.repo.approval_blockers(project_id, approval.approval_id)
            module = _module_from_approval_target(approval.target_type)
            display_module = module if approval.target_type == "evidence_picos_snapshot" else "approvals"
            priority = "high" if blockers else "medium"
            status = "质量门阻断" if blockers else _approval_state_label(approval.state)
            items.append(
                WorkbenchItem(
                    item_id=f"approval:{approval.approval_id}",
                    project_id=project_id,
                    module=display_module,
                    module_label=_module_label(display_module),
                    item_type="approval",
                    source_type="approval_gate",
                    source_id=approval.approval_id,
                    title=_approval_title(approval.target_type, approval.target_id),
                    summary=approval.review_comments or ("存在质量门阻断，需处理后再批准。" if blockers else "待医学经理审阅并留痕。"),
                    priority=priority,
                    status=status,
                    needs_action=True,
                    action_label="查看质量门",
                    target_page="approvals",
                    target_id=approval.target_id,
                    source_version=f"{approval.state.value}:{_dt_token(approval.updated_at)}:{len(blockers)}",
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type="approval_target",
                            source_id=approval.target_id,
                            label=f"{_module_label(module)} / {approval.target_id}",
                        ),
                        *[
                            WorkbenchItemSourceRef(
                                source_type=blocker.source_type,
                                source_id=blocker.source_id,
                                label=blocker.message,
                            )
                            for blocker in blockers[:3]
                        ],
                    ],
                    updated_at=approval.updated_at,
                    boundary_note="审批中心只记录医学批准动作和阻断原因，不自动替代电子签名或正式归档。",
                )
            )
        return items

    def _ai_run_items(self, project_id: str) -> List[WorkbenchItem]:
        items: List[WorkbenchItem] = []
        try:
            runs = self.ai_task_runner.list_runs(project_id)
        except Exception:
            return items
        for run in runs:
            if run.status == AiTaskRunStatus.COMPLETED and not run.needs_medical_confirmation:
                continue
            if run.status == AiTaskRunStatus.COMPLETED and run.needs_medical_confirmation:
                priority = "medium"
                status = "待医学确认"
            elif run.status == AiTaskRunStatus.BLOCKED:
                priority = "high"
                status = "AI阻断"
            elif run.status == AiTaskRunStatus.FAILED:
                priority = "high"
                status = "AI运行失败"
            else:
                priority = "low"
                status = run.status.value
            items.append(
                WorkbenchItem(
                    item_id=f"ai:{run.run_id}",
                    project_id=project_id,
                    module=run.module,
                    module_label=_module_label(run.module),
                    item_type="ai_review",
                    source_type="ai_run",
                    source_id=run.run_id,
                    title=f"AI任务待处理：{_ai_task_label(run.task_type)}",
                    summary=run.error_message or "AI输出需医学经理查看来源、验证状态和建议边界后再进入业务流程。",
                    priority=priority,
                    status=status,
                    needs_action=run.status in {AiTaskRunStatus.BLOCKED, AiTaskRunStatus.FAILED} or run.needs_medical_confirmation,
                    action_label="查看AI审计",
                    target_page=_target_page(run.module),
                    target_id=run.run_id,
                    source_version=f"{run.status.value}:{run.output_validation_status.value}:{_dt_token(run.updated_at)}",
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type="prompt",
                            source_id=run.prompt_version,
                            label=run.prompt_version,
                        ),
                    ],
                    updated_at=run.updated_at,
                    boundary_note="AI输出均为待医学确认内容；系统仅使用已配置的独立AI服务。",
                )
            )
        return items

    def _picos_items(self, project_id: str) -> List[WorkbenchItem]:
        items: List[WorkbenchItem] = []
        try:
            workflow = self.evidence_picos_workflow_service.workflow(project_id)
        except Exception:
            return items
        for step in workflow.steps:
            latest_record = step.audit_trail[-1] if step.audit_trail else None
            updated_at = latest_record.created_at if latest_record else workflow.generated_at
            source_version = f"{step.decision_status}:{step.selected_option_id}:{latest_record.record_id if latest_record else 'seed'}"
            if step.decision_status == "写作候选":
                item_type = "handoff"
                priority = "medium"
                status = "写作候选"
                title = f"PICOS设计可交接：{step.picos_domain}"
                summary = f"已具备流转到医学写作的候选设计，目标章节：{step.writing_target_section}。"
                action_label = "进入写作衔接"
            elif step.decision_status in {"待用户确认", "待补医学理由", "退回补证", "待医学确认"}:
                item_type = "picos_decision"
                priority = "high" if step.decision_status in {"退回补证", "待补医学理由"} else "medium"
                status = step.decision_status
                title = f"PICOS设计待确认：{step.picos_domain}"
                summary = "基于当前证据包选择设计方案，补充医学理由后才能进入方案写作候选。"
                action_label = "进入PICOS决策"
            else:
                continue
            items.append(
                WorkbenchItem(
                    item_id=f"picos:{workflow.package_id}:{step.question_id}",
                    project_id=project_id,
                    module="evidence_design",
                    module_label="证据调研与方案设计",
                    item_type=item_type,
                    source_type="picos_workflow",
                    source_id=step.question_id,
                    title=title,
                    summary=summary,
                    priority=priority,
                    status=status,
                    needs_action=item_type != "handoff",
                    action_label=action_label,
                    target_page="evidenceDesign" if item_type != "handoff" else "writing",
                    target_id=step.question_id,
                    source_version=source_version,
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type="evidence_package",
                            source_id=workflow.package_id,
                            label="PICOS证据包",
                        )
                    ],
                    updated_at=updated_at,
                    boundary_note="PICOS输出是待医学批准的正式内容候选，不直接写入正式研究方案。",
                )
            )
        return items

    def _tfl_handoff_items(self, project_id: str) -> List[WorkbenchItem]:
        items: List[WorkbenchItem] = []
        try:
            candidate_check = getattr(
                self.tfl_writing_handoff_service,
                "has_handoff_candidate_records",
                None,
            )
            if callable(candidate_check) and not candidate_check(project_id):
                return items
            manifest = self.tfl_writing_handoff_service.citation_manifest(project_id)
        except Exception:
            return items
        for candidate in manifest.candidates:
            items.append(
                WorkbenchItem(
                    item_id=f"tfl-handoff:{candidate.candidate_id}",
                    project_id=project_id,
                    module="data_analysis_tfl",
                    module_label="数据分析与TFL",
                    item_type="handoff",
                    source_type="tfl_writing_candidate",
                    source_id=candidate.candidate_id,
                    title=f"TFL结果可引用：{candidate.output_display_id}",
                    summary=f"来自{candidate.package_label}，建议衔接至{'、'.join(candidate.recommended_writing_sections[:2])}。",
                    priority="medium",
                    status="写作引用候选",
                    needs_action=False,
                    action_label="交接医学写作",
                    target_page="writing",
                    target_id=candidate.output_id,
                    source_version=f"{candidate.review_record_id}:{_dt_token(candidate.review_created_at)}",
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type="tfl_output",
                            source_id=candidate.output_id,
                            label=candidate.output_display_id,
                        ),
                        WorkbenchItemSourceRef(
                            source_type="review_record",
                            source_id=candidate.review_record_id,
                            label="TFL医学审阅记录",
                        ),
                    ],
                    updated_at=candidate.review_created_at,
                    boundary_note="TFL引用候选仅用于医学写作衔接，不等同监管递交TFL已批准。",
                )
            )
        return items

    def _safety_handoff_items(self, project_id: str) -> List[WorkbenchItem]:
        items: List[WorkbenchItem] = []
        try:
            manifest = self.safety_review_workbench_service.handoff_candidates(project_id)
        except Exception as exc:
            LOGGER.exception("Safety/PV handoff manifest failed for %s", project_id)
            return [
                WorkbenchItem(
                    item_id=f"safety-handoff-health:{project_id}",
                    project_id=project_id,
                    module="safety_pv",
                    module_label="安全信号与PV协同",
                    item_type="data_health",
                    source_type="safety_pv_handoff_manifest_error",
                    source_id=project_id,
                    title="Safety/PV协作交接读取失败",
                    summary="当前无法确认医学监查与PV文件复核交接状态，请刷新后重试。",
                    priority="high",
                    status="读取失败",
                    needs_action=True,
                    action_label="进入安全协作",
                    target_page="safety",
                    target_id=project_id,
                    source_version=f"error:{_stable_text_token(str(exc))}",
                    updated_at=utc_now(),
                    boundary_note="该提示仅表示协作交接读取异常，不代表项目不存在安全性风险。",
                )
            ]
        for handoff in getattr(manifest, "monitoring_collaborations", []):
            items.append(
                WorkbenchItem(
                    item_id=f"safety-handoff:{handoff.handoff_id}",
                    project_id=project_id,
                    module="safety_pv",
                    module_label="安全信号与PV协同",
                    item_type="handoff",
                    source_type="monitoring_safety_pv_collaboration",
                    source_id=handoff.risk_id,
                    risk_key=handoff.risk_key,
                    risk_instance_id=handoff.risk_instance_id,
                    snapshot_id=handoff.snapshot_id,
                    title=f"医学监查协作：{handoff.title}",
                    summary=(
                        handoff.stale_reason
                        if not handoff.is_current
                        else handoff.review_comment
                    ),
                    priority=handoff.severity.value,
                    status=(
                        "来源已变化，需回医学监查复核"
                        if not handoff.is_current
                        else handoff.disposition_status
                    ),
                    needs_action=not handoff.is_current,
                    action_label="回到医学监查" if not handoff.is_current else "查看同一风险",
                    target_page="monitoring",
                    target_id=handoff.subject_id,
                    source_version=(
                        f"{handoff.disposition_record_id}:{handoff.source_version}:"
                        f"{'current' if handoff.is_current else 'stale'}"
                    ),
                    source_refs=handoff.source_refs,
                    updated_at=handoff.created_at,
                    boundary_note=handoff.handoff_boundary,
                )
            )
        for candidate in manifest.candidates:
            items.append(
                WorkbenchItem(
                    item_id=f"safety-handoff:{candidate.candidate_id}",
                    project_id=project_id,
                    module="safety_pv",
                    module_label="安全信号与PV协同",
                    item_type="handoff",
                    source_type="safety_pv_handoff_candidate",
                    source_id=candidate.candidate_id,
                    title=f"安全/PV交接候选：{candidate.signal_label}",
                    summary=f"{candidate.title}；建议衔接至{'、'.join(candidate.recommended_handoff_sections[:2])}。",
                    priority=candidate.severity.value if isinstance(candidate.severity, RiskSeverity) else str(candidate.severity),
                    status="PV确认候选",
                    needs_action=False,
                    action_label="查看交接包",
                    target_page="safety",
                    target_id=candidate.signal_id,
                    source_version=f"{candidate.review_record_id}:{_dt_token(candidate.review_created_at)}",
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type="safety_signal",
                            source_id=candidate.signal_id,
                            label=candidate.signal_label,
                        ),
                        WorkbenchItemSourceRef(
                            source_type="review_record",
                            source_id=candidate.review_record_id,
                            label="安全医学复核记录",
                        ),
                    ],
                    updated_at=candidate.review_created_at,
                    boundary_note="安全/PV交接候选不构成最终安全性结论，需PV和医学按职责确认。",
                )
            )
        return items

    def _medical_writing_manifest_items(self, project_id: str) -> List[WorkbenchItem]:
        items: List[WorkbenchItem] = []
        try:
            manifest = self.medical_writing_manifest_service.build_manifest(project_id)
        except Exception:
            return items
        for package in manifest.packages:
            blocked_gates = [gate for gate in package.quality_gates if gate.status in {"blocked", "warning"}]
            if not blocked_gates:
                continue
            gate = blocked_gates[0]
            items.append(
                WorkbenchItem(
                    item_id=f"writing-gate:{package.package_id}:{gate.gate_id}",
                    project_id=project_id,
                    module="medical_writing",
                    module_label="医学写作",
                    item_type="quality_gate",
                    source_type="writing_quality_gate",
                    source_id=gate.gate_id,
                    title=f"写作质量门待处理：{package.package_label}",
                    summary=gate.detail,
                    priority="high" if gate.status == "blocked" else "medium",
                    status="质量门阻断" if gate.status == "blocked" else "质量门预警",
                    needs_action=True,
                    action_label="进入医学写作",
                    target_page="writing",
                    target_id=package.package_id,
                    source_version=f"{gate.status}:{gate.gate_id}:{manifest.generated_at.date().isoformat()}",
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type="writing_package",
                            source_id=package.package_id,
                            label=package.package_label,
                        )
                    ],
                    updated_at=manifest.generated_at,
                    boundary_note="写作内容在医学批准前均为候选稿，不代表正式批准版本。",
                )
            )
        return items

    def _workbench_notification_items(self, project_id: str) -> List[WorkbenchItem]:
        """Surface durable JSONL notifications (e.g. corpus_ready) in the inbox."""
        items: List[WorkbenchItem] = []
        try:
            from services.api.app.workbench_notifications import list_notifications

            rows = list_notifications(
                project_id, path=self.notifications_path, limit=40
            )
        except Exception:
            return items
        for row in rows:
            try:
                updated_raw = row.get("updated_at") or row.get("created_at")
                if isinstance(updated_raw, datetime):
                    updated_at = updated_raw
                else:
                    updated_at = datetime.fromisoformat(
                        str(updated_raw).replace("Z", "+00:00")
                    )
            except Exception:
                updated_at = utc_now()
            items.append(
                WorkbenchItem(
                    item_id=str(row.get("item_id") or f"notice:{project_id}"),
                    project_id=project_id,
                    module=str(row.get("module") or "medical_writing"),
                    module_label=str(row.get("module_label") or "医学写作"),
                    item_type=str(row.get("item_type") or "notice"),
                    source_type=str(row.get("source_type") or "workbench_notification"),
                    source_id=str(row.get("source_id") or ""),
                    title=str(row.get("title") or "站内通知"),
                    summary=str(row.get("summary") or ""),
                    priority=str(row.get("priority") or "medium"),
                    status=str(row.get("status") or "待查看"),
                    needs_action=bool(row.get("needs_action", True)),
                    action_label=str(row.get("action_label") or "查看"),
                    target_page=str(row.get("target_page") or "writing"),
                    target_id=str(row.get("target_id") or project_id),
                    source_version=str(row.get("source_version") or updated_at.isoformat()),
                    updated_at=updated_at,
                    boundary_note="站内通知仅提示流程状态，不构成医学结论。",
                )
            )
        return items

    def _source_registry_items(self, project_id: str) -> List[WorkbenchItem]:
        items: List[WorkbenchItem] = []
        entries, bad_line_count = self._source_registry_snapshot(project_id)
        if bad_line_count:
            now = utc_now()
            items.append(
                WorkbenchItem(
                    item_id=f"data-health:source-registry:bad-lines:{bad_line_count}",
                    project_id=project_id,
                    module="dashboard",
                    module_label="项目总看板",
                    item_type="data_health",
                    source_type="source_registry",
                    source_id="source_registry_jsonl",
                    title="来源登记运行态存在无法解析记录",
                    summary=f"来源登记运行态中有{bad_line_count}行无法解析，已跳过坏行并保留可读取来源；需核对运行态写入流程。",
                    priority="high",
                    status="数据健康告警",
                    needs_action=True,
                    action_label="查看来源登记",
                    target_page="overview",
                    target_id="source_registry",
                    source_version=f"bad_lines:{bad_line_count}",
                    updated_at=now,
                    boundary_note="数据健康项只暴露运行态健康状态，不暴露本地文件路径或原始内容。",
                )
            )

        latest_by_entry: Dict[str, Any] = {}
        duplicate_counts: Dict[str, int] = defaultdict(int)
        for entry in sorted(entries, key=lambda item: item.created_at):
            latest_by_entry[entry.entry_id] = entry
            duplicate_counts[entry.entry_id] += 1

        for entry in latest_by_entry.values():
            module = entry.module if entry.module in _ALLOWED_MODULES else "dashboard"
            duplicate_count = duplicate_counts.get(entry.entry_id, 0)
            if duplicate_count > 1:
                items.append(
                    WorkbenchItem(
                        item_id=f"data-health:source-duplicate:{entry.entry_id}",
                        project_id=project_id,
                        module=module,
                        module_label=_module_label(module),
                        item_type="data_health",
                        source_type="source_registry_entry",
                        source_id=entry.entry_id,
                        title=f"来源重复登记待确认：{entry.public_title}",
                        summary=f"同一来源已登记{duplicate_count}次。看板按最新记录去重展示，需确认是否为重复上传或有意刷新。",
                        priority="medium",
                        status="重复登记",
                        needs_action=True,
                        action_label="核对来源",
                        target_page=_target_page(module),
                        target_id=entry.entry_id,
                        source_version=f"source_duplicate:{_stable_text_token(f'{entry.entry_id}:{entry.content_hash}:{duplicate_count}:{_dt_token(entry.created_at)}')}",
                        source_refs=[
                            WorkbenchItemSourceRef(
                                source_type=entry.source_kind,
                                source_id=entry.entry_id,
                                label=entry.public_title,
                            )
                        ],
                        updated_at=entry.created_at,
                        boundary_note="来源重复登记只提示数据治理，不删除或覆盖审计记录。",
                    )
                )

            if entry.parser_status != "parsed":
                title = f"来源待解析：{entry.public_title}"
                status = "待OCR/VLM" if _needs_ocr_vlm(entry) else "待解析"
                priority = "medium"
                needs_action = True
                summary = _source_pending_summary(entry)
            else:
                title = f"来源已接入：{entry.public_title}"
                status = "来源已接入"
                priority = "low"
                needs_action = False
                summary = f"已生成{entry.span_count}个可供独立AI任务选择的来源片段。"

            items.append(
                WorkbenchItem(
                    item_id=f"source:{entry.entry_id}",
                    project_id=project_id,
                    module=module,
                    module_label=_module_label(module),
                    item_type="source_ready",
                    source_type="source_registry_entry",
                    source_id=entry.entry_id,
                    title=title,
                    summary=summary,
                    priority=priority,
                    status=status,
                    needs_action=needs_action,
                    action_label="选择AI任务" if entry.parser_status == "parsed" else "补充解析",
                    target_page=_target_page(module),
                    target_id=entry.entry_id,
                    source_version=f"source:{_stable_text_token(f'{entry.entry_id}:{entry.parser_status}:{entry.content_hash}:{entry.span_count}:{_dt_token(entry.created_at)}')}",
                    source_refs=[
                        WorkbenchItemSourceRef(
                            source_type=entry.source_kind,
                            source_id=entry.entry_id,
                            label=entry.public_title,
                        )
                    ],
                    updated_at=entry.created_at,
                    boundary_note="来源登记只暴露公开标题、稳定ID、解析状态和片段数量；本地路径由后端保管。",
                )
            )
        return items

    def _source_registry_snapshot(self, project_id: str) -> Tuple[List[Any], int]:
        if self.source_registry_service is None:
            return [], 0
        try:
            return list(self.source_registry_service.list_entries(project_id)), 0
        except Exception:
            pass

        store = getattr(self.source_registry_service, "store", None)
        jsonl_path = getattr(store, "jsonl_path", None)
        if not jsonl_path:
            return [], 1
        path = Path(jsonl_path)
        if not path.exists():
            return [], 0

        entries: List[Any] = []
        bad_line_count = 0
        try:
            from packages.contracts.workbench_contracts import SourceRegistrationResult
        except Exception:
            return [], 1
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    result = SourceRegistrationResult.model_validate(json.loads(line))
                except Exception:
                    bad_line_count += 1
                    continue
                if result.entry.project_id == project_id:
                    entries.append(result.entry)
        return entries, bad_line_count

    def _eligibility_items(self, project_id: str) -> List[WorkbenchItem]:
        if self.eligibility_adapter is None:
            return []
        try:
            dataset = self.eligibility_adapter.eligibility_dataset(project_id)
        except Exception:
            return []

        items: List[WorkbenchItem] = []
        phase_ids = [phase.phase_id for phase in getattr(dataset, "review_phases", []) if phase.phase_id]
        if not phase_ids and dataset.active_phase_id:
            phase_ids = [dataset.active_phase_id]
        generated_at = dataset.generated_at
        for row in dataset.subject_rows:
            for phase_id in phase_ids:
                try:
                    subject_dataset = self.eligibility_adapter.eligibility_dataset(
                        project_id,
                        subject_id=row.subject_id,
                        phase_id=phase_id,
                    )
                except Exception:
                    continue
                candidate = subject_dataset.selected_candidate
                if candidate is None:
                    continue
                updated_at = getattr(subject_dataset, "generated_at", generated_at)
                for action_item in candidate.missing_information:
                    items.append(self._eligibility_action_item(project_id, candidate, action_item, updated_at, phase_id))
                for action_item in candidate.medical_confirmation_items:
                    items.append(self._eligibility_action_item(project_id, candidate, action_item, updated_at, phase_id))
                for rule in candidate.rule_reviews:
                    if rule.verdict.value in {"fail", "pass_verify"}:
                        items.append(self._eligibility_rule_status_item(project_id, candidate, rule, updated_at, phase_id))
        return items

    def _eligibility_action_item(self, project_id: str, candidate, action_item, generated_at: datetime, phase_id: str) -> WorkbenchItem:
        is_missing = action_item.item_type == "missing_information"
        status = "待补充资料" if is_missing else "待医学确认"
        title = f"入排审核{status}：{candidate.subject_id} / {action_item.rule_id}"
        summary = action_item.recommended_action or action_item.detail
        source_hash = _stable_text_token(f"{action_item.detail}:{action_item.recommended_action}:{phase_id}")
        return WorkbenchItem(
            item_id=f"eligibility:{candidate.source_project_code}:{action_item.item_id}",
            project_id=project_id,
            module="eligibility_review",
            module_label="入排审核",
            item_type="eligibility_action",
            source_type="eligibility_review",
            source_id=action_item.item_id,
            title=title,
            summary=summary,
            priority=action_item.severity.value,
            status=status,
            needs_action=True,
            owner_role="医学经理",
            action_label="进入入排审核",
            target_page="eligibility",
            target_id=f"受试者 {candidate.subject_id} / {phase_id}",
            source_version=f"{candidate.source_project_code}:{phase_id}:{source_hash}",
            source_refs=[
                WorkbenchItemSourceRef(
                    source_type="eligibility_rule",
                    source_id=action_item.rule_id,
                    label=action_item.rule_id,
                ),
                WorkbenchItemSourceRef(
                    source_type="subject",
                    source_id=candidate.subject_id,
                    label=f"受试者 {candidate.subject_id}",
                ),
            ],
            updated_at=generated_at,
            boundary_note="入排工作项来自原始入排审核系统适配层；总看板不暴露源文件绝对路径或历史AI原始回复。",
        )

    def _eligibility_rule_status_item(self, project_id: str, candidate, rule, generated_at: datetime, phase_id: str) -> WorkbenchItem:
        is_fail = rule.verdict.value == "fail"
        status = "不符合/筛败待确认" if is_fail else "待溯源验证"
        title = f"入排审核{status}：{candidate.subject_id} / {rule.rule_id}"
        summary = rule.rationale or rule.criterion_text or "需医学经理核对入排标准、源文件证据和规则判定。"
        source_hash = _stable_text_token(f"{rule.rule_id}:{rule.verdict.value}:{summary}:{phase_id}")
        return WorkbenchItem(
            item_id=f"eligibility-rule:{candidate.source_project_code}:{candidate.subject_id}:{phase_id}:{rule.rule_id}:{rule.verdict.value}",
            project_id=project_id,
            module="eligibility_review",
            module_label="入排审核",
            item_type="eligibility_action",
            source_type="eligibility_rule_review",
            source_id=f"{candidate.subject_id}:{phase_id}:{rule.rule_id}",
            title=title,
            summary=summary,
            priority="high" if is_fail else "medium",
            status=status,
            needs_action=True,
            owner_role="医学经理",
            action_label="进入入排审核",
            target_page="eligibility",
            target_id=f"受试者 {candidate.subject_id} / {phase_id}",
            source_version=f"{candidate.source_project_code}:{phase_id}:{source_hash}",
            source_refs=[
                WorkbenchItemSourceRef(
                    source_type="eligibility_rule",
                    source_id=rule.rule_id,
                    label=rule.rule_id,
                ),
                WorkbenchItemSourceRef(
                    source_type="subject",
                    source_id=candidate.subject_id,
                    label=f"受试者 {candidate.subject_id}",
                ),
            ],
            updated_at=generated_at,
            boundary_note="入排规则状态只展示入排标准ID、受试者编号和医学复核结论；源文件路径和原始AI回复由后端保管。",
        )


def _read_versions(records: Iterable[WorkbenchInboxActionRecord]) -> Dict[str, str]:
    read_versions: Dict[str, str] = {}
    for record in sorted(records, key=lambda item: item.created_at):
        if record.action == WorkbenchItemAction.MARK_READ:
            read_versions[record.item_id] = record.source_version
    return read_versions


def _module_summaries(module_manifests, items: List[WorkbenchItem]) -> List[WorkbenchModuleInboxSummary]:
    grouped: Dict[str, List[WorkbenchItem]] = defaultdict(list)
    for item in items:
        grouped[item.module].append(item)
        if item.item_type == "approval" and item.module != "approvals":
            grouped["approvals"].append(item)
    summaries: List[WorkbenchModuleInboxSummary] = []
    for manifest in module_manifests:
        if not manifest.visible_in_dashboard:
            continue
        module_items = grouped.get(manifest.module, [])
        summaries.append(
            WorkbenchModuleInboxSummary(
                module=manifest.module,
                module_label=manifest.label,
                open_count=len(module_items),
                unread_count=sum(1 for item in module_items if item.unread),
                blocked_count=sum(1 for item in module_items if _is_blocked_status(item.status)),
                handoff_count=sum(1 for item in module_items if item.item_type == "handoff"),
                needs_action_count=sum(1 for item in module_items if item.needs_action),
            )
        )
    return summaries


def _rux_source_refs(risk: RiskCase) -> List[WorkbenchItemSourceRef]:
    refs = [
        WorkbenchItemSourceRef(
            source_type="protocol_rule",
            source_id=risk.rule_id,
            label=risk.rule_id,
            locator="",
        )
    ]
    ordered_locators = [
        *[locator for locator in risk.evidence_span_ids if locator.startswith("docx:")],
        *[locator for locator in risk.evidence_span_ids if not locator.startswith("docx:")],
    ]
    for locator in ordered_locators[:8]:
        if locator.startswith("listing:"):
            refs.append(
                WorkbenchItemSourceRef(
                    source_type="listing_data_row",
                    source_id=_stable_text_token(locator),
                    label=_rux_listing_label(locator),
                    locator=locator,
                )
            )
        elif locator.startswith("docx:"):
            refs.append(
                WorkbenchItemSourceRef(
                    source_type="protocol_rule",
                    source_id=_stable_text_token(f"{risk.rule_id}:{locator}"),
                    label=f"{risk.rule_id} / {locator}",
                    locator=locator,
                )
            )
        else:
            refs.append(
                WorkbenchItemSourceRef(
                    source_type="source_locator",
                    source_id=_stable_text_token(locator),
                    label=locator,
                    locator=locator,
                )
            )
    return refs


def _rux_listing_label(locator: str) -> str:
    if ":sheet:" not in locator:
        return locator
    sheet_fragment = locator.split(":sheet:", 1)[1]
    return sheet_fragment.replace(":row:", " / row:")


def _rux_source_version(risk: RiskCase, source_revision: str) -> str:
    medical_meaning = "|".join(
        [
            risk.rule_id,
            risk.title,
            risk.severity.value if isinstance(risk.severity, RiskSeverity) else str(risk.severity),
            risk.rationale,
            risk.recommended_action,
            *risk.evidence_span_ids,
        ]
    )
    return f"rux-p0:{risk.rule_id}:{_stable_text_token(source_revision)}:{_stable_text_token(medical_meaning)}"


def _monitoring_source_version(risk: RiskCase, source_revision: str) -> str:
    medical_meaning = "|".join(
        [
            risk.project_id,
            risk.rule_id,
            risk.title,
            risk.severity.value if isinstance(risk.severity, RiskSeverity) else str(risk.severity),
            risk.rationale,
            risk.recommended_action,
            *risk.evidence_span_ids,
        ]
    )
    return f"monitoring:{risk.rule_id}:{_stable_text_token(source_revision)}:{_stable_text_token(medical_meaning)}"


def _monitoring_project_label(project_id: str) -> str:
    return {
        RUX_PROJECT_ID: "RUX-03-002",
        "proj_my009_uc": "MY009-UC",
    }.get(project_id, project_id)


def _rux_disposition_status_label(state: str) -> str:
    return {
        "pending_review": "待医学复核",
        "reviewed": "已医学复核",
        "query_draft": "Query草稿",
        "submitted_for_approval": "已提交内部审批",
        "explained_no_external_action": "已说明，无需外部动作",
        "data_correction": "已转数据更正",
        "follow_up": "已转追加随访",
        "pd_update": "已转PD补充/更新",
        "safety_pv_collaboration": "已转Safety/PV协作",
        "continue_observation": "持续观察",
        "duplicate_not_applicable": "重复项/不适用",
    }.get(state, "待医学复核")


def _rux_disposition_action_label(
    state: str,
    *,
    approval_required: bool = True,
) -> str:
    if state == "query_draft" and not approval_required:
        return "查看Query草稿"
    return {
        "pending_review": "标记医学复核",
        "reviewed": "记录Query草稿",
        "query_draft": "提交内部审批",
        "submitted_for_approval": "查看内部审批状态",
        "explained_no_external_action": "查看医学处置记录",
        "data_correction": "查看数据更正记录",
        "follow_up": "查看追加随访记录",
        "pd_update": "查看PD补充/更新记录",
        "safety_pv_collaboration": "查看Safety/PV协作记录",
        "continue_observation": "查看持续观察记录",
        "duplicate_not_applicable": "查看不适用判定记录",
    }.get(state, "标记医学复核")


def _rux_disposition_needs_action(
    state: str,
    *,
    approval_required: bool = True,
) -> bool:
    actionable = {"pending_review", "reviewed"}
    if approval_required:
        actionable.add("query_draft")
    return state in actionable


def _validate_rux_disposition_transition(previous_state: str, request: RuxRiskDispositionActionRequest) -> str:
    action = request.action
    if action == RuxRiskDispositionAction.REVIEWED:
        if previous_state != "pending_review":
            raise ValueError("risk is already medically reviewed or later")
        if request.medical_judgments is None or not request.medical_judgments.review_completed:
            raise ValueError("four medical judgments must be completed before medical review")
        if request.disposition_kind not in {None, MonitoringRiskDispositionKind.CENTER_QUERY}:
            return request.disposition_kind.value
        return "reviewed"
    if action == RuxRiskDispositionAction.QUERY_DRAFT:
        if previous_state != "reviewed":
            raise ValueError("must mark reviewed before query draft")
        if request.disposition_kind not in {None, MonitoringRiskDispositionKind.CENTER_QUERY}:
            raise ValueError("query draft is only available for disposition_kind=center_query")
        if not (request.query_draft_text or request.comment).strip():
            raise ValueError("comment is required")
        return "query_draft"
    if action == RuxRiskDispositionAction.SUBMITTED_FOR_APPROVAL:
        if previous_state != "query_draft":
            raise ValueError("must create query draft before submit")
        return "submitted_for_approval"
    if action == RuxRiskDispositionAction.REOPEN:
        terminal_states = {
            "explained_no_external_action",
            "data_correction",
            "follow_up",
            "pd_update",
            "safety_pv_collaboration",
            "continue_observation",
            "duplicate_not_applicable",
        }
        if previous_state not in terminal_states:
            raise ValueError("only a terminal medical disposition can be reopened")
        if request.expected_disposition_state != previous_state:
            raise ValueError(
                f"stale_disposition: current_disposition_state={previous_state}"
            )
        return "pending_review"
    raise ValueError(f"unsupported RUX risk disposition action: {action}")


_ALLOWED_MODULES = {
    "dashboard",
    "evidence_design",
    "eligibility_review",
    "medical_monitoring",
    "data_analysis_tfl",
    "medical_writing",
    "safety_pv",
    "approvals",
}


def _dedupe_items(items: List[WorkbenchItem]) -> List[WorkbenchItem]:
    seen: Dict[str, int] = defaultdict(int)
    deduped: List[WorkbenchItem] = []
    for item in items:
        seen[item.item_id] += 1
        if seen[item.item_id] == 1:
            deduped.append(item)
            continue
        suffix = seen[item.item_id]
        LOGGER.warning("duplicate workbench inbox item_id preserved with suffix: %s", item.item_id)
        deduped.append(item.model_copy(update={"item_id": f"{item.item_id}#dup{suffix}"}))
    return deduped


def _select_visible_items(items: List[WorkbenchItem], limit: int) -> List[WorkbenchItem]:
    if limit <= 0 or len(items) <= limit:
        return items

    # Keep the overview usable when one module, usually all-phase eligibility review,
    # produces enough work items to crowd out source/data-health and handoff signals.
    selected = list(items[:limit])
    selected_ids = {item.item_id for item in selected}
    protected_ids = {item.item_id for item in selected[:20] if item.priority == "high"}
    minimums = {
        "data_health": 2,
        "source_ready": 3,
        "handoff": 2,
        "quality_gate": 2,
        "picos_decision": 3,
    }

    for item_type, minimum in minimums.items():
        available = [item for item in items if item.item_type == item_type]
        required = min(minimum, len(available))
        attempts = 0
        while sum(1 for item in selected if item.item_type == item_type) < required and attempts < len(items):
            attempts += 1
            candidate = next((item for item in available if item.item_id not in selected_ids), None)
            if candidate is None:
                break
            replacement_index = _replacement_index(selected, protected_ids, preserve_item_type=item_type)
            removed = selected.pop(replacement_index)
            selected_ids.remove(removed.item_id)
            selected.append(candidate)
            selected_ids.add(candidate.item_id)
            protected_ids.add(candidate.item_id)

    selected.sort(key=_item_sort_key)
    return selected[:limit]


def _replacement_index(items: List[WorkbenchItem], protected_ids: set[str], preserve_item_type: str) -> int:
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if (
            item.item_id not in protected_ids
            and item.item_type != preserve_item_type
            and item.item_type == "eligibility_action"
            and item.priority != "high"
        ):
            return index
    for index in range(len(items) - 1, -1, -1):
        item = items[index]
        if item.item_id not in protected_ids and item.item_type != preserve_item_type and item.priority != "high":
            return index
    for index in range(len(items) - 1, -1, -1):
        if items[index].item_type != preserve_item_type:
            return index
    return len(items) - 1


def _item_sort_key(item: WorkbenchItem):
    return (
        _priority_rank(item.priority),
        0 if item.unread else 1,
        0 if item.needs_action else 1,
        -item.updated_at.timestamp(),
        item.item_id,
    )


def _priority_rank(priority: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(priority, 4)


def _is_blocked_status(status: str) -> bool:
    return any(token in status for token in ("阻断", "退回", "失败", "blocked", "failed", "待补"))


def _module_label(module: str) -> str:
    return {
        "dashboard": "项目总看板",
        "evidence_design": "证据调研与方案设计",
        "eligibility_review": "入排审核",
        "medical_monitoring": "医学监查",
        "data_analysis_tfl": "数据分析与TFL",
        "medical_writing": "医学写作",
        "safety_pv": "安全信号与PV协同",
        "approvals": "审批中心",
    }.get(module, module)


def _target_page(module: str) -> str:
    return {
        "dashboard": "overview",
        "evidence_design": "evidenceDesign",
        "eligibility_review": "eligibility",
        "medical_monitoring": "monitoring",
        "data_analysis_tfl": "tfl",
        "medical_writing": "writing",
        "safety_pv": "safety",
        "approvals": "approvals",
    }.get(module, "overview")


def _risk_target_label(risk: RiskCase) -> str:
    parts = []
    if risk.subject_id:
        parts.append(f"受试者 {risk.subject_id}")
    if risk.site_id:
        parts.append(f"中心 {risk.site_id}")
    return " / ".join(parts) or risk.risk_id


def _risk_status_label(status: RiskStatus) -> str:
    return {
        RiskStatus.NEW: "新识别",
        RiskStatus.TRIAGED: "已分诊",
        RiskStatus.IN_REVIEW: "复核中",
        RiskStatus.ACTION_REQUIRED: "需行动",
        RiskStatus.ACCEPTED_NO_ACTION: "暂不处理",
        RiskStatus.RESOLVED: "已解决",
        RiskStatus.CLOSED: "已关闭",
        RiskStatus.SUPERSEDED: "已替代",
    }.get(status, status.value)


def _approval_state_label(state: ApprovalState) -> str:
    return {
        ApprovalState.AI_DRAFT: "AI草稿待审",
        ApprovalState.IN_MEDICAL_REVIEW: "医学审阅中",
        ApprovalState.RETURNED_FOR_REVISION: "退回修订",
    }.get(state, state.value)


def _approval_title(target_type: str, target_id: str) -> str:
    if target_type == "evidence_picos_snapshot":
        return "PICOS 医学批准"
    if target_type == "medical_writing_protocol_section":
        return f"医学写作审批：{target_id}"
    if target_type == "medical_writing_revision_thread":
        return f"医学写作修订建议审批：{target_id}"
    if target_type == "medical_monitoring_risk_batch":
        return f"医学监查风险包审批：{target_id}"
    return f"审批待处理：{target_id}"


def _module_from_approval_target(target_type: str) -> str:
    if target_type == "evidence_picos_snapshot":
        return "evidence_design"
    if target_type.startswith("medical_writing"):
        return "medical_writing"
    if target_type.startswith("medical_monitoring"):
        return "medical_monitoring"
    if target_type.startswith("eligibility"):
        return "eligibility_review"
    if target_type.startswith("data_analysis_tfl"):
        return "data_analysis_tfl"
    if target_type.startswith("safety_pv"):
        return "safety_pv"
    if target_type.startswith("evidence_design"):
        return "evidence_design"
    return "approvals"


def _ai_task_label(task_type: str) -> str:
    return task_type.replace("_", " ")


def _needs_ocr_vlm(entry) -> bool:
    metadata = getattr(entry, "metadata", {}) or {}
    return bool(metadata.get("needs_ocr_vlm_count")) or "ocr" in str(metadata.get("evidence_status", "")).lower()


def _source_pending_summary(entry) -> str:
    metadata = getattr(entry, "metadata", {}) or {}
    total_files = metadata.get("total_files")
    needs_ocr = metadata.get("needs_ocr_vlm_count")
    if total_files is not None:
        return f"已完成文件级清点，共{total_files}个文件，其中{needs_ocr or 0}个可能需要OCR/VLM后才能进入语义任务。"
    return "来源已登记但尚未形成可直接用于语义AI任务的结构化片段。"


def _stable_text_token(value: str) -> str:
    return sha1(value.encode("utf-8")).hexdigest()[:12]


def _dt_token(value: Optional[datetime]) -> str:
    return value.isoformat() if value else ""
