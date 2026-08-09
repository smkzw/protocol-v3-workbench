from __future__ import annotations

import json
from hashlib import sha256
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    RiskSeverity,
    SafetyMonitoringCollaborationHandoff,
    SafetyPvHandoffCandidate,
    SafetyPvHandoffManifestResult,
    SafetyQualityGate,
    SafetyReviewAction,
    SafetyReviewActionRequest,
    SafetyReviewRecord,
    SafetyReviewWorkbenchResult,
    SafetySignalCandidate,
    SafetySourcePackageSummary,
    SourceAdmissionState,
)

from .safety_pv_manifest import SafetyPvManifestService
from .sqlite_runtime_store import SqliteRuntimeStore
from .source_admission import (
    require_source_admission,
    source_bindings_are_current,
    unavailable_source_admission,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SafetyReviewStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, record: SafetyReviewRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def records(self, project_id: str, package_id: Optional[str] = None, signal_id: Optional[str] = None) -> List[SafetyReviewRecord]:
        if not self.path.exists():
            return []
        records: List[SafetyReviewRecord] = []
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
                if package_id and payload.get("package_id") != package_id:
                    continue
                if signal_id and payload.get("signal_id") != signal_id:
                    continue
                try:
                    records.append(SafetyReviewRecord.model_validate(payload))
                except Exception:
                    continue
        return records


class SqliteSafetyReviewStore:
    def __init__(
        self,
        runtime_store: SqliteRuntimeStore,
        legacy_path: Optional[Path] = None,
    ):
        self.runtime_store = runtime_store
        if legacy_path is not None:
            self._import_legacy(legacy_path)

    def records(
        self,
        project_id: str,
        package_id: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> List[SafetyReviewRecord]:
        return self.runtime_store.safety_review_records(
            project_id,
            package_id,
            signal_id,
        )

    def lookup_idempotent_replay(
        self,
        project_id: str,
        idempotency_key: str,
        request_fingerprint: str,
    ):
        return self.runtime_store.lookup_idempotent_replay(
            project_id,
            "safety_pv_review",
            idempotency_key,
            request_fingerprint,
        )

    def commit(
        self,
        record: SafetyReviewRecord,
        *,
        expected_revision: int,
        idempotency_key: str,
        request_fingerprint: str,
    ):
        return self.runtime_store.commit_safety_review(
            record,
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

    def _import_legacy(self, path: Path) -> None:
        if not path.exists():
            return
        parsed: List[SafetyReviewRecord] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    parsed.append(SafetyReviewRecord.model_validate(json.loads(line)))
                except Exception:
                    continue
        existing_by_project = {
            project_id: self.records(project_id)
            for project_id in {item.project_id for item in parsed}
        }
        legacy_ids = {item.record_id for item in parsed}
        for project_id, existing in existing_by_project.items():
            nonlegacy = [item.record_id for item in existing if item.record_id not in legacy_ids]
            if nonlegacy:
                self.runtime_store.record_rejection(
                    project_id,
                    event_type="legacy_import_rejected",
                    operation="safety_pv_legacy_import",
                    actor="system_migration",
                    detail={
                        "reason": "SQLite aggregate already contains live records",
                        "nonlegacy_record_count": len(nonlegacy),
                    },
                )
                return
        for legacy in parsed:
            current = self.records(
                legacy.project_id,
                legacy.package_id,
                legacy.signal_id,
            )
            if any(item.record_id == legacy.record_id for item in current):
                continue
            revision = current[-1].revision + 1 if current else 1
            migrated = legacy.model_copy(
                update={
                    "previous_revision": revision - 1,
                    "revision": revision,
                }
            )
            payload = {
                "legacy_record_id": migrated.record_id,
                "project_id": migrated.project_id,
                "package_id": migrated.package_id,
                "signal_id": migrated.signal_id,
                "revision": revision,
            }
            fingerprint = sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest()
            self.commit(
                migrated,
                expected_revision=revision - 1,
                idempotency_key=f"legacy-safety-review:{migrated.record_id}",
                request_fingerprint=fingerprint,
            )


class SafetyReviewWorkbenchService:
    def __init__(
        self,
        manifest_service: SafetyPvManifestService,
        store: SafetyReviewStore,
        source_admission_resolver: Callable[[str, str], SourceAdmissionState] | None = None,
        monitoring_collaboration_resolver: Callable[
            [str], List[SafetyMonitoringCollaborationHandoff]
        ]
        | None = None,
        *,
        allow_unvalidated_sources: bool = False,
    ):
        self.manifest_service = manifest_service
        self.store = store
        self.source_admission_resolver = source_admission_resolver
        self.monitoring_collaboration_resolver = monitoring_collaboration_resolver
        self.allow_unvalidated_sources = allow_unvalidated_sources

    def has_handoff_candidate_records(self, project_id: str) -> bool:
        latest_by_signal = _latest_records_by_signal(self.store.records(project_id))
        return any(record.new_status == "PV确认候选" for record in latest_by_signal.values())

    def workbench(
        self,
        project_id: str,
        package_id: Optional[str] = None,
        signal_id: Optional[str] = None,
    ) -> SafetyReviewWorkbenchResult:
        manifest = self.manifest_service.build_manifest(project_id)
        package = _select_package(manifest.packages, package_id)
        candidate_signals = _candidate_signals(package.signal_candidates)
        selected_signal = _select_signal(candidate_signals, signal_id)
        records = self.store.records(project_id, package.package_id, selected_signal.signal_id if selected_signal else None)
        current_status = _status_from_records(records)
        state_revision = records[-1].revision if records else 0
        source_admission = (
            self.source_admission_resolver(project_id, package.package_id)
            if self.source_admission_resolver
            else None if self.allow_unvalidated_sources else unavailable_source_admission(
                project_id,
                "safety_pv",
                package.package_id,
            )
        )
        source_binding_digest = _source_admission_digest(source_admission)
        source_review_current = not (
            records
            and current_status in {"医学已复核", "PV确认候选", "关闭为暂无需处理"}
            and source_admission is not None
            and not source_bindings_are_current(
                records[-1].source_validation_bindings,
                source_admission,
            )
        )
        if not source_review_current:
            current_status = "来源已变化，需重新医学复核"
        gates = _quality_gates(
            package,
            selected_signal,
            current_status,
            source_review_current=source_review_current,
        )

        return SafetyReviewWorkbenchResult(
            project_id=project_id,
            generated_at=utc_now(),
            package_id=package.package_id,
            package_label=package.package_label,
            selected_signal_id=selected_signal.signal_id if selected_signal else "",
            selected_signal=selected_signal,
            current_status=current_status,
            state_revision=state_revision,
            source_binding_digest=source_binding_digest,
            review_records=records[-20:],
            quality_gates=gates,
            candidate_signals=candidate_signals[:24],
            listing_context=_listing_context(package, selected_signal),
            document_context=_document_context(package, selected_signal),
            source_admission=source_admission,
            available_actions=_available_actions(current_status),
        )

    def apply_action(
        self,
        project_id: str,
        package_id: str,
        signal_id: str,
        request: SafetyReviewActionRequest,
    ) -> SafetyReviewWorkbenchResult:
        snapshot = self.workbench(project_id, package_id=package_id, signal_id=signal_id)
        if snapshot.selected_signal is None:
            raise KeyError(signal_id)
        request_payload = {
            "project_id": project_id,
            "package_id": package_id,
            "signal_id": signal_id,
            "action": request.action.value,
            "actor": request.actor.strip(),
            "comment": request.comment.strip(),
            "expected_revision": request.expected_revision,
            "expected_source_binding_digest": request.expected_source_binding_digest,
        }
        request_fingerprint = sha256(
            json.dumps(request_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        idempotency_key = request.idempotency_key.strip() or (
            f"safety-pv:{project_id}:{package_id}:{signal_id}:"
            f"{request.expected_revision}:{request.action.value}"
        )
        if hasattr(self.store, "lookup_idempotent_replay"):
            replay = self.store.lookup_idempotent_replay(
                project_id,
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self.workbench(project_id, package_id=package_id, signal_id=signal_id)
        if not request.comment.strip():
            raise ValueError("安全信号审阅动作必须填写医学/PV处置意见。")
        if (
            request.expected_source_binding_digest
            and request.expected_source_binding_digest != snapshot.source_binding_digest
        ):
            raise ValueError("来源版本已变化，请刷新当前安全资料后重新提交。")
        protected_action = request.action in {
            SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            SafetyReviewAction.REQUEST_PV_CONFIRMATION,
            SafetyReviewAction.ACCEPT_NO_ACTION,
        }
        source_bindings = (
            require_source_admission(snapshot.source_admission)
            if protected_action and snapshot.source_admission is not None
            else []
        )
        if request.action == SafetyReviewAction.REQUEST_PV_CONFIRMATION:
            if snapshot.current_status == "来源已变化，需重新医学复核":
                raise ValueError("来源版本已变化，需基于当前来源重新完成医学复核后再转为PV确认候选。")
            if snapshot.current_status != "医学已复核":
                raise ValueError("需先完成医学复核，才能转为PV确认候选。")
            latest_record = snapshot.review_records[-1] if snapshot.review_records else None
            if (
                snapshot.source_admission is not None
                and (
                    latest_record is None
                    or latest_record.action != SafetyReviewAction.MARK_MEDICAL_REVIEWED
                    or not source_bindings_are_current(
                        latest_record.source_validation_bindings,
                        snapshot.source_admission,
                    )
                )
            ):
                raise ValueError("来源版本已变化，需基于当前来源重新完成医学复核后再转为PV确认候选。")

        _validate_review_transition(snapshot.current_status, request.action)

        created_at = utc_now()
        record_revision = (
            request.expected_revision + 1
            if hasattr(self.store, "commit")
            else snapshot.state_revision + 1
        )
        record = SafetyReviewRecord(
            record_id=f"safety_review_{uuid4().hex}",
            project_id=project_id,
            package_id=package_id,
            signal_id=signal_id,
            signal_label=snapshot.selected_signal.signal_label,
            action=request.action,
            actor=request.actor,
            previous_status=(
                snapshot.review_records[-1].new_status
                if snapshot.review_records
                else "待医学/PV确认"
            ),
            new_status=_status_for_action(request.action),
            comment=request.comment.strip(),
            previous_revision=record_revision - 1,
            revision=record_revision,
            source_validation_bindings=source_bindings,
            created_at=created_at,
        )
        if hasattr(self.store, "commit"):
            if protected_action and self.source_admission_resolver is not None:
                latest_source_admission = self.source_admission_resolver(
                    project_id,
                    package_id,
                )
                if (
                    _source_admission_digest(latest_source_admission)
                    != snapshot.source_binding_digest
                ):
                    raise ValueError(
                        "来源版本在提交过程中发生变化，请刷新后重新完成医学复核。"
                    )
            self.store.commit(
                record,
                expected_revision=request.expected_revision,
                idempotency_key=idempotency_key,
                request_fingerprint=request_fingerprint,
            )
        else:
            self.store.append(record)
        return self.workbench(project_id, package_id=package_id, signal_id=signal_id)

    def handoff_candidates(self, project_id: str) -> SafetyPvHandoffManifestResult:
        manifest = self.manifest_service.build_manifest(project_id)
        latest_by_signal = _latest_records_by_signal(self.store.records(project_id))
        candidates: List[SafetyPvHandoffCandidate] = []
        source_admissions: List[SourceAdmissionState] = []
        blocked_stale_candidate_count = 0
        monitoring_collaborations = (
            self.monitoring_collaboration_resolver(project_id)
            if self.monitoring_collaboration_resolver is not None
            else []
        )
        blocked_monitoring_collaboration_count = sum(
            1 for item in monitoring_collaborations if not item.is_current
        )
        for package in manifest.packages:
            source_admission = (
                self.source_admission_resolver(project_id, package.package_id)
                if self.source_admission_resolver
                else None if self.allow_unvalidated_sources else unavailable_source_admission(
                    project_id,
                    "safety_pv",
                    package.package_id,
                )
            )
            if source_admission is not None:
                source_admissions.append(source_admission)
            for signal in package.signal_candidates:
                record = latest_by_signal.get((package.package_id, signal.signal_id))
                if record is None or record.new_status != "PV确认候选":
                    continue
                if source_admission is not None and not source_bindings_are_current(
                    record.source_validation_bindings,
                    source_admission,
                ):
                    blocked_stale_candidate_count += 1
                    continue
                candidates.append(
                    SafetyPvHandoffCandidate(
                        candidate_id=f"safety_handoff_{record.record_id}",
                        project_id=project_id,
                        package_id=package.package_id,
                        package_label=package.package_label,
                        signal_id=signal.signal_id,
                        signal_label=signal.signal_label,
                        signal_type=signal.signal_type,
                        title=signal.title,
                        severity=signal.severity,
                        source_domains=signal.source_domains,
                        evidence_locators=signal.evidence_locators,
                        review_record_id=record.record_id,
                        reviewer=record.actor,
                        review_comment=record.comment,
                        review_created_at=record.created_at,
                        recommended_handoff_sections=_recommended_handoff_sections(signal),
                        source_validation_bindings=record.source_validation_bindings,
                    )
                )
        candidates.sort(key=lambda item: (item.review_created_at, item.signal_label), reverse=True)
        return SafetyPvHandoffManifestResult(
            project_id=project_id,
            generated_at=utc_now(),
            total_candidates=len(candidates),
            candidates=candidates,
            monitoring_collaboration_count=sum(
                1 for item in monitoring_collaborations if item.is_current
            ),
            monitoring_collaborations=monitoring_collaborations,
            blocked_monitoring_collaboration_count=blocked_monitoring_collaboration_count,
            quality_gates=_handoff_quality_gates(
                candidates,
                blocked_stale_candidate_count,
                monitoring_collaborations,
            ),
            source_admissions=source_admissions,
            blocked_stale_candidate_count=blocked_stale_candidate_count,
        )


def _select_package(packages: List[SafetySourcePackageSummary], package_id: Optional[str]) -> SafetySourcePackageSummary:
    if not packages:
        raise KeyError("no safety package available")
    if package_id:
        selected = next((package for package in packages if package.package_id == package_id), None)
        if selected is None:
            raise KeyError(package_id)
        return selected
    return packages[0]


def _select_signal(signals: List[SafetySignalCandidate], signal_id: Optional[str]) -> Optional[SafetySignalCandidate]:
    if signal_id:
        selected = next((signal for signal in signals if signal.signal_id == signal_id), None)
        if selected is None:
            raise KeyError(signal_id)
        return selected
    return signals[0] if signals else None


def _candidate_signals(signals: List[SafetySignalCandidate]) -> List[SafetySignalCandidate]:
    priority = {
        RiskSeverity.CRITICAL: 0,
        RiskSeverity.HIGH: 1,
        RiskSeverity.MEDIUM: 2,
        RiskSeverity.LOW: 3,
    }
    return sorted(signals, key=lambda item: (priority.get(item.severity, 9), item.signal_label, item.signal_id))


def _status_from_records(records: List[SafetyReviewRecord]) -> str:
    if not records:
        return "待医学/PV确认"
    return records[-1].new_status


def _status_for_action(action: SafetyReviewAction) -> str:
    return {
        SafetyReviewAction.MARK_MEDICAL_REVIEWED: "医学已复核",
        SafetyReviewAction.REQUEST_PV_CONFIRMATION: "PV确认候选",
        SafetyReviewAction.RETURN_FOR_SOURCE_CHECK: "退回补充资料",
        SafetyReviewAction.ACCEPT_NO_ACTION: "关闭为暂无需处理",
        SafetyReviewAction.RESET_REVIEW: "待医学/PV确认",
    }[action]


def _available_actions(status: str) -> List[SafetyReviewAction]:
    return {
        "待医学/PV确认": [
            SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            SafetyReviewAction.RETURN_FOR_SOURCE_CHECK,
        ],
        "退回补充资料": [
            SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            SafetyReviewAction.RESET_REVIEW,
        ],
        "医学已复核": [
            SafetyReviewAction.REQUEST_PV_CONFIRMATION,
            SafetyReviewAction.RETURN_FOR_SOURCE_CHECK,
            SafetyReviewAction.ACCEPT_NO_ACTION,
            SafetyReviewAction.RESET_REVIEW,
        ],
        "PV确认候选": [
            SafetyReviewAction.RETURN_FOR_SOURCE_CHECK,
            SafetyReviewAction.ACCEPT_NO_ACTION,
            SafetyReviewAction.RESET_REVIEW,
        ],
        "关闭为暂无需处理": [SafetyReviewAction.RESET_REVIEW],
        "来源已变化，需重新医学复核": [
            SafetyReviewAction.MARK_MEDICAL_REVIEWED,
            SafetyReviewAction.RETURN_FOR_SOURCE_CHECK,
            SafetyReviewAction.RESET_REVIEW,
        ],
    }.get(status, [])


def _validate_review_transition(status: str, action: SafetyReviewAction) -> None:
    allowed = _available_actions(status)
    if action in allowed:
        return
    if action == SafetyReviewAction.REQUEST_PV_CONFIRMATION:
        raise ValueError("需先完成医学已复核状态，才能转为PV确认候选。")
    if status == "关闭为暂无需处理":
        raise ValueError("该候选已关闭；需先重置复核，再执行新的医学处置。")
    if action == SafetyReviewAction.ACCEPT_NO_ACTION:
        raise ValueError("需先完成医学复核，才能关闭为暂无需处理。")
    if action == SafetyReviewAction.RESET_REVIEW and status == "待医学/PV确认":
        raise ValueError("当前已是待医学/PV确认状态，无需重复重置。")
    raise ValueError(
        f"不允许从“{status}”执行“{_status_for_action(action)}”。"
    )


def _latest_records_by_signal(records: List[SafetyReviewRecord]) -> Dict[Tuple[str, str], SafetyReviewRecord]:
    latest: Dict[Tuple[str, str], SafetyReviewRecord] = {}
    for record in records:
        key = (record.package_id, record.signal_id)
        current = latest.get(key)
        if current is None or record.revision > current.revision:
            latest[key] = record
    return latest


def _source_admission_digest(source_admission: Optional[SourceAdmissionState]) -> str:
    if source_admission is None:
        return ""
    payload = [
        {
            "source_role_code": item.source_role_code,
            "source_entry_id": item.source_entry_id,
            "validation_id": item.validation_id,
            "revision": item.revision,
            "technical_status": item.technical_status,
            "content_status": item.content_status,
            "use_status": item.use_status,
        }
        for item in sorted(
            source_admission.sources,
            key=lambda value: (value.source_role_code, value.source_entry_id),
        )
    ]
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _recommended_handoff_sections(signal: SafetySignalCandidate) -> List[str]:
    signal_type = signal.signal_type
    if signal_type in {"lab_abnormality_medical_explanation", "ecg_abnormality_linkage_review"}:
        return ["安全性医学复核", "DSUR/IB安全更新素材", "临床安全性总结"]
    if signal_type in {"pv_plan_safety_summary_alignment", "dsur_ib_update_sync"}:
        return ["PV协同核对清单", "DSUR/IB安全更新素材", "医学写作安全性章节"]
    if signal_type == "ae_medical_review_candidate":
        return ["AE医学复核", "DSUR/IB安全更新素材", "临床安全性总结"]
    return ["安全性协同交接清单"]


def _handoff_quality_gates(
    candidates: List[SafetyPvHandoffCandidate],
    blocked_stale_candidate_count: int = 0,
    monitoring_collaborations: List[SafetyMonitoringCollaborationHandoff] | None = None,
) -> List[SafetyQualityGate]:
    monitoring_collaborations = monitoring_collaborations or []
    stale_monitoring_count = sum(
        1 for item in monitoring_collaborations if not item.is_current
    )
    missing_comment = [item for item in candidates if not item.review_comment.strip()]
    missing_locator = [item for item in candidates if not item.evidence_locators]
    gates = [
        SafetyQualityGate(
            gate_id="safety_handoff_candidate_presence",
            gate_label="PV协同交接候选",
            status="warning" if not candidates else "ok",
            owner="医学经理/PV",
            detail="尚无PV协同交接候选。" if not candidates else f"当前共有{len(candidates)}个PV协同交接候选。",
            source_refs=[item.candidate_id for item in candidates[:8]],
        ),
        SafetyQualityGate(
            gate_id="safety_handoff_medical_comment",
            gate_label="医学处置意见",
            status="blocked" if missing_comment else "ok",
            owner="医学经理",
            detail="存在缺少医学/PV处置意见的交接候选。" if missing_comment else "全部交接候选均有医学/PV处置意见。",
            source_refs=[item.candidate_id for item in missing_comment[:8]],
        ),
        SafetyQualityGate(
            gate_id="safety_handoff_source_locator",
            gate_label="来源定位",
            status="warning" if missing_locator else "ok",
            owner="医学经理/数据",
            detail="部分候选缺少来源定位，协同确认前需补充。" if missing_locator else "全部交接候选均保留来源定位。",
            source_refs=[item.candidate_id for item in missing_locator[:8]],
        ),
    ]
    gates.append(
        SafetyQualityGate(
            gate_id="safety_source_version_current",
            gate_label="来源版本准入",
            status="blocked" if blocked_stale_candidate_count else "ok",
            owner="医学经理/PV",
            detail=(
                f"{blocked_stale_candidate_count}个既有候选绑定的来源版本已变化或未完成确认，已停止交接。"
                if blocked_stale_candidate_count
                else "PV协同候选绑定的来源版本仍为当前可用版本。"
            ),
            source_refs=[],
        )
    )
    gates.append(
        SafetyQualityGate(
            gate_id="monitoring_safety_pv_handoff_current",
            gate_label="医学监查协作交接版本",
            status="blocked" if stale_monitoring_count else "ok",
            owner="医学经理",
            detail=(
                f"{stale_monitoring_count}条医学监查协作交接的来源版本已变化，需回到医学监查重新复核。"
                if stale_monitoring_count
                else "医学监查协作交接均引用当前风险来源版本。"
            ),
            source_refs=[
                item.handoff_id
                for item in monitoring_collaborations
                if not item.is_current
            ][:8],
        )
    )
    return gates


def _listing_context(package: SafetySourcePackageSummary, signal: Optional[SafetySignalCandidate]):
    if signal is None:
        return package.listing_domains[:8]
    signal_domains = set(signal.source_domains)
    selected = [domain for domain in package.listing_domains if domain.sheet_name in signal_domains or domain.domain in signal_domains]
    for domain in package.listing_domains:
        if domain in selected:
            continue
        if domain.sheet_name in {"AE", "MH", "CM", "LB", "LB1", "LB2", "EG", "VS"}:
            selected.append(domain)
        if len(selected) >= 8:
            break
    return selected[:8]


def _document_context(package: SafetySourcePackageSummary, signal: Optional[SafetySignalCandidate]):
    if signal is None:
        return package.documents[:8]
    locators = set(signal.evidence_locators)
    selected = [document for document in package.documents if document.public_title in locators]
    for document in package.documents:
        if document in selected:
            continue
        if document.document_type in {"dsur_collection", "safety_evaluation_report", "pv_plan", "clinical_safety_summary"}:
            selected.append(document)
        if len(selected) >= 8:
            break
    return selected[:8]


def _quality_gates(
    package: SafetySourcePackageSummary,
    signal: Optional[SafetySignalCandidate],
    current_status: str,
    *,
    source_review_current: bool = True,
) -> List[SafetyQualityGate]:
    signal_refs = [signal.signal_id] if signal else []
    locator_refs = signal.evidence_locators[:4] if signal else []
    has_source_domains = bool(signal and signal.source_domains)
    has_evidence_locator = bool(signal and signal.evidence_locators)
    reviewed = current_status in {"医学已复核", "PV确认候选", "关闭为暂无需处理"}
    gates = [
        SafetyQualityGate(
            gate_id=f"{package.package_id}:signal_selected",
            gate_label="安全候选对象",
            status="ok" if signal else "blocked",
            owner="医学经理",
            detail=f"当前审阅对象：{signal.signal_label if signal else '未选择安全候选'}。",
            source_refs=signal_refs,
        ),
        SafetyQualityGate(
            gate_id=f"{package.package_id}:source_domain_trace",
            gate_label="来源域与证据定位",
            status="ok" if has_source_domains and has_evidence_locator else "warning",
            owner="医学经理/数据",
            detail="候选已保留来源域和证据定位。" if has_source_domains and has_evidence_locator else "候选缺少来源域或证据定位，转PV确认前需补充。",
            source_refs=locator_refs,
        ),
        SafetyQualityGate(
            gate_id=f"{package.package_id}:medical_disposition",
            gate_label="医学处置意见",
            status="ok" if reviewed else "warning",
            owner="医学经理",
            detail=f"当前状态：{current_status}。转PV确认前需完成医学复核并记录理由。",
            source_refs=signal_refs,
        ),
        SafetyQualityGate(
            gate_id=f"{package.package_id}:pv_handoff_boundary",
            gate_label="PV交接边界",
            status="ok" if current_status == "PV确认候选" else "warning",
            owner="PV",
            detail="当前为PV确认候选，但仍不代表最终药物警戒结论。" if current_status == "PV确认候选" else "尚未转为PV确认候选；不得作为最终安全性结论或递交动作。",
            source_refs=signal_refs,
        ),
        SafetyQualityGate(
            gate_id=f"{package.package_id}:formal_pv_overclaim_guard",
            gate_label="PV越界保护",
            status="ok",
            owner="医学经理/PV",
            detail="本工作台仅生成待医学/PV确认的审阅记录和交接候选，不写入药物警戒系统、不生成个案电子报送文件、不启动监管递交流程。",
            source_refs=["PV协同边界"],
        ),
    ]
    gates.append(
        SafetyQualityGate(
            gate_id=f"{package.package_id}:review_source_current",
            gate_label="医学复核来源版本",
            status="ok" if source_review_current else "blocked",
            owner="医学经理",
            detail=(
                "当前医学复核记录绑定的来源版本仍有效。"
                if source_review_current
                else "来源版本或准入状态已变化，原医学复核状态不再作为当前PV协同依据。"
            ),
            source_refs=[],
        )
    )
    return gates
