from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from io import BytesIO, StringIO
import re
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlencode
from zipfile import ZIP_DEFLATED, ZipFile
from zoneinfo import ZoneInfo

from packages.contracts.workbench_contracts import RiskCase, RiskSeverity, RiskStatus

from .workbench_inbox import (
    RUX_PROJECT_ID,
    _monitoring_source_version,
    _read_versions,
    _rux_disposition_needs_action,
    _rux_source_version,
)
from .monitoring_risk_evidence import capture_risk_evidence, public_risk_payload
from .medical_monitoring_risk_taxonomy import (
    canonical_risk_category_codes,
    project_risk_category,
    resolve_risk_category,
    risk_taxonomy_payload,
)


SUMMARY_CONTRACT_VERSION = "medical-monitoring-module-summary-2026-07-29.2"
RUN_CONTRACT_VERSION = "medical-monitoring-run-2026-07-29.1"
DEEP_LINK_CONTRACT_VERSION = "medical-monitoring-deep-link-2026-07-30.2"
RISK_EXPORT_CONTRACT_VERSION = "medical-monitoring-risk-export-2026-07-30.1"
MODULE_KEY = "medical_monitoring"
MODULE_LABEL = "医学监查"

_TERMINAL_RISK_STATUSES = {
    RiskStatus.RESOLVED,
    RiskStatus.CLOSED,
    RiskStatus.SUPERSEDED,
}
_ACTIONABLE_RISK_STATUSES = {
    RiskStatus.NEW,
    RiskStatus.TRIAGED,
    RiskStatus.IN_REVIEW,
    RiskStatus.ACTION_REQUIRED,
}


class MonitoringScope(str, Enum):
    TRIAL = "trial"
    SITE = "site"
    SUBJECT = "subject"


class MonitoringView(str, Enum):
    CHECKLIST = "checklist"
    TIMELINE = "timeline"
    PROFILE = "profile"
    AE_MH = "ae-mh"
    EVIDENCE = "evidence"


class MonitoringEvidenceTab(str, Enum):
    DISPOSITION = "disposition"
    TIMELINE = "timeline"
    PROFILE = "profile"
    AE_MH = "ae_mh"
    SOURCES = "sources"
    HISTORY = "history"


class RiskChecklistSortField(str, Enum):
    SUBJECT_ID = "subject_id"
    SITE_ID = "site_id"
    SEVERITY = "severity"
    RISK_CATEGORY_CODE = "risk_category_code"
    RISK_ITEM = "risk_item"
    DISPOSITION_STATUS = "disposition_status"
    UPDATED_AT = "updated_at"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class DeepLinkValidationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class RiskSnapshotQueryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MedicalMonitoringDeepLink:
    project_id: str
    scope: MonitoringScope = MonitoringScope.TRIAL
    view: MonitoringView = MonitoringView.CHECKLIST
    site_id: str = ""
    subject_id: str = ""
    risk_key: str = ""
    risk_instance_id: str = ""
    batch_id: str = ""
    evidence_tab: Optional[MonitoringEvidenceTab] = None
    filter_subject_id: str = ""
    filter_site_id: str = ""
    filter_severity: str = ""
    filter_risk_category_code: str = ""
    filter_risk_item: str = ""
    filter_disposition_status: str = ""
    filter_updated_at: str = ""
    risk_sort_by: RiskChecklistSortField = RiskChecklistSortField.UPDATED_AT
    risk_sort_direction: SortDirection = SortDirection.DESC
    risk_page: int = 1
    risk_page_size: int = 50
    risk_snapshot_id: str = ""
    redirect_reason: str = ""
    redirect_from_risk_instance_id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        query = {
            "project_id": self.project_id,
            "scope": self.scope.value,
            "view": self.view.value,
            "risk_sort_by": self.risk_sort_by.value,
            "risk_sort_direction": self.risk_sort_direction.value,
            "risk_page": self.risk_page,
            "risk_page_size": self.risk_page_size,
        }
        if self.evidence_tab is not None:
            query["evidence_tab"] = self.evidence_tab.value
        for key in (
            "site_id",
            "subject_id",
            "risk_key",
            "risk_instance_id",
            "batch_id",
            "filter_subject_id",
            "filter_site_id",
            "filter_severity",
            "filter_risk_category_code",
            "filter_risk_item",
            "filter_disposition_status",
            "filter_updated_at",
            "risk_snapshot_id",
        ):
            value = getattr(self, key)
            if value:
                query[key] = value
        payload = {
            "contract_version": DEEP_LINK_CONTRACT_VERSION,
            **query,
            "href": f"/monitoring?{urlencode(query)}",
        }
        if self.redirect_reason:
            payload["redirect_reason"] = self.redirect_reason
            payload["redirect_from_risk_instance_id"] = (
                self.redirect_from_risk_instance_id
            )
        return payload


def validate_medical_monitoring_deep_link(
    *,
    project_id: str,
    scope: MonitoringScope,
    view: MonitoringView,
    site_id: str = "",
    subject_id: str = "",
    risk_key: str = "",
    risk_instance_id: str = "",
    batch_id: str = "",
    evidence_tab: Optional[MonitoringEvidenceTab] = None,
    filter_subject_id: str = "",
    filter_site_id: str = "",
    filter_severity: str = "",
    filter_risk_category_code: str = "",
    filter_risk_item: str = "",
    filter_disposition_status: str = "",
    filter_updated_at: str = "",
    risk_sort_by: RiskChecklistSortField = RiskChecklistSortField.UPDATED_AT,
    risk_sort_direction: SortDirection = SortDirection.DESC,
    risk_page: int = 1,
    risk_page_size: int = 50,
    risk_snapshot_id: str = "",
    redirect_reason: str = "",
    redirect_from_risk_instance_id: str = "",
) -> MedicalMonitoringDeepLink:
    normalized = {
        "project_id": project_id.strip(),
        "site_id": site_id.strip(),
        "subject_id": subject_id.strip(),
        "risk_key": risk_key.strip(),
        "risk_instance_id": risk_instance_id.strip(),
        "batch_id": batch_id.strip(),
        "filter_subject_id": filter_subject_id.strip(),
        "filter_site_id": filter_site_id.strip(),
        "filter_severity": filter_severity.strip(),
        "filter_risk_category_code": filter_risk_category_code.strip(),
        "filter_risk_item": filter_risk_item.strip(),
        "filter_disposition_status": filter_disposition_status.strip(),
        "filter_updated_at": filter_updated_at.strip(),
        "risk_snapshot_id": risk_snapshot_id.strip(),
    }
    if not normalized["project_id"]:
        raise DeepLinkValidationError("project_id_required", "project_id 不能为空")
    if scope == MonitoringScope.TRIAL and (
        normalized["site_id"] or normalized["subject_id"]
    ):
        raise DeepLinkValidationError(
            "trial_scope_conflict",
            "trial 范围不得携带 site_id 或 subject_id",
        )
    if scope == MonitoringScope.SITE:
        if not normalized["site_id"]:
            raise DeepLinkValidationError("site_id_required", "site 范围必须提供 site_id")
        if normalized["subject_id"]:
            raise DeepLinkValidationError(
                "site_scope_conflict",
                "site 范围不得携带 subject_id",
            )
    if scope == MonitoringScope.SUBJECT and not normalized["subject_id"]:
        raise DeepLinkValidationError(
            "subject_id_required",
            "subject 范围必须提供 subject_id",
        )
    if view in {MonitoringView.TIMELINE, MonitoringView.PROFILE} and not normalized[
        "subject_id"
    ]:
        raise DeepLinkValidationError(
            "subject_view_requires_subject",
            f"{view.value} 视图必须提供 subject_id",
        )
    if (
        view == MonitoringView.EVIDENCE
        and not normalized["risk_key"]
        and not normalized["risk_instance_id"]
    ):
        raise DeepLinkValidationError(
            "evidence_view_requires_risk",
            "evidence 视图必须提供 risk_key 或 risk_instance_id",
        )
    if evidence_tab is not None and view != MonitoringView.EVIDENCE:
        raise DeepLinkValidationError(
            "evidence_tab_requires_evidence_view",
            "evidence_tab 仅可用于 evidence 视图",
        )
    if normalized["filter_subject_id"] and normalized["subject_id"]:
        if normalized["filter_subject_id"] != normalized["subject_id"]:
            raise DeepLinkValidationError(
                "subject_filter_scope_conflict",
                "受试者筛选值与当前受试者范围不一致",
            )
    if normalized["filter_site_id"] and normalized["site_id"]:
        if normalized["filter_site_id"] != normalized["site_id"]:
            raise DeepLinkValidationError(
                "site_filter_scope_conflict",
                "中心筛选值与当前中心范围不一致",
            )
    if risk_page < 1:
        raise DeepLinkValidationError("invalid_risk_page", "risk_page 必须大于等于 1")
    if risk_page_size < 1 or risk_page_size > 200:
        raise DeepLinkValidationError(
            "invalid_risk_page_size",
            "risk_page_size 必须介于 1 至 200",
        )
    try:
        _validate_snapshot_query(
            category="",
            risk_category_code=normalized["filter_risk_category_code"],
            severity=normalized["filter_severity"],
            disposition_status=normalized["filter_disposition_status"],
            updated_at=normalized["filter_updated_at"],
        )
    except RiskSnapshotQueryError as exc:
        raise DeepLinkValidationError(exc.code, exc.message) from exc

    return MedicalMonitoringDeepLink(
        project_id=normalized["project_id"],
        scope=scope,
        view=view,
        site_id=normalized["site_id"],
        subject_id=normalized["subject_id"],
        risk_key=normalized["risk_key"],
        risk_instance_id=normalized["risk_instance_id"],
        batch_id=normalized["batch_id"],
        evidence_tab=evidence_tab,
        filter_subject_id=normalized["filter_subject_id"],
        filter_site_id=normalized["filter_site_id"],
        filter_severity=normalized["filter_severity"],
        filter_risk_category_code=normalized["filter_risk_category_code"],
        filter_risk_item=normalized["filter_risk_item"],
        filter_disposition_status=normalized["filter_disposition_status"],
        filter_updated_at=normalized["filter_updated_at"],
        risk_sort_by=risk_sort_by,
        risk_sort_direction=risk_sort_direction,
        risk_page=risk_page,
        risk_page_size=risk_page_size,
        risk_snapshot_id=normalized["risk_snapshot_id"],
        redirect_reason=redirect_reason,
        redirect_from_risk_instance_id=redirect_from_risk_instance_id,
    )


class MedicalMonitoringSummaryService:
    """Read-only projection over existing monitoring state.

    The service deliberately never calls adapter risk evaluation or the
    workbench inbox builder. A missing snapshot is a valid empty state.
    """

    def __init__(
        self,
        *,
        risk_repository: Any,
        project_source_manifest_service: Any = None,
        workbench_inbox_service: Any = None,
        monitoring_registry: Any = None,
    ) -> None:
        self.risk_repository = risk_repository
        self.project_source_manifest_service = project_source_manifest_service
        self.workbench_inbox_service = workbench_inbox_service
        self.monitoring_registry = monitoring_registry

    def canonical_project_id(self, project_id: str) -> str:
        if self.project_source_manifest_service is None:
            return project_id
        return self.project_source_manifest_service.canonical_project_id(project_id)

    def validate_deep_link(
        self,
        *,
        project_id: str,
        scope: MonitoringScope,
        view: MonitoringView,
        site_id: str = "",
        subject_id: str = "",
        risk_key: str = "",
        risk_instance_id: str = "",
        batch_id: str = "",
        evidence_tab: Optional[MonitoringEvidenceTab] = None,
        filter_subject_id: str = "",
        filter_site_id: str = "",
        filter_severity: str = "",
        filter_risk_category_code: str = "",
        filter_risk_item: str = "",
        filter_disposition_status: str = "",
        filter_updated_at: str = "",
        risk_sort_by: RiskChecklistSortField = RiskChecklistSortField.UPDATED_AT,
        risk_sort_direction: SortDirection = SortDirection.DESC,
        risk_page: int = 1,
        risk_page_size: int = 50,
        risk_snapshot_id: str = "",
    ) -> MedicalMonitoringDeepLink:
        """Validate and canonicalize a persisted monitoring navigation state."""

        canonical_id = self.canonical_project_id(project_id)
        candidate = validate_medical_monitoring_deep_link(
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
            risk_sort_by=risk_sort_by,
            risk_sort_direction=risk_sort_direction,
            risk_page=risk_page,
            risk_page_size=risk_page_size,
            risk_snapshot_id=risk_snapshot_id,
        )

        subject_index: Optional[Dict[str, str]] = None
        if any(
            (
                candidate.site_id,
                candidate.subject_id,
                candidate.filter_site_id,
                candidate.filter_subject_id,
            )
        ):
            subject_index = self._monitoring_subject_index(canonical_id)
            self._validate_subject_site_binding(
                subject_index,
                site_id=candidate.site_id,
                subject_id=candidate.subject_id,
                context="scope",
            )
            self._validate_subject_site_binding(
                subject_index,
                site_id=candidate.filter_site_id,
                subject_id=candidate.filter_subject_id,
                context="filter",
            )

        selected_snapshot = None
        if candidate.risk_snapshot_id:
            try:
                selected_snapshot = self.risk_repository.snapshot(
                    canonical_id,
                    candidate.risk_snapshot_id,
                )
            except KeyError as exc:
                raise DeepLinkValidationError(
                    "medical_monitoring_snapshot_not_found",
                    "所选风险快照不存在或不属于当前项目。",
                    status_code=409,
                ) from exc
        else:
            try:
                selected_snapshot = self.risk_repository.current_snapshot(canonical_id)
            except KeyError:
                selected_snapshot = None

        canonical_risk = None
        redirect_reason = ""
        redirect_from = ""
        if candidate.risk_instance_id or candidate.risk_key:
            if selected_snapshot is None:
                raise DeepLinkValidationError(
                    "medical_monitoring_snapshot_not_found",
                    "当前项目尚无可验证风险焦点的持久化快照。",
                    status_code=409,
                )
            snapshot_risks = self.risk_repository.list_risks(
                canonical_id,
                selected_snapshot.snapshot_id,
            )
            by_instance = {
                risk.risk_instance_id: risk for risk in snapshot_risks
            }
            by_key = {risk.risk_key: risk for risk in snapshot_risks}

            if candidate.risk_instance_id:
                canonical_risk = by_instance.get(candidate.risk_instance_id)
                if canonical_risk is None:
                    try:
                        _, historical_risk = self.risk_repository.risk_instance(
                            canonical_id,
                            candidate.risk_instance_id,
                        )
                    except KeyError as exc:
                        raise DeepLinkValidationError(
                            "medical_monitoring_risk_instance_not_found",
                            "风险实例不存在或不属于当前项目。",
                            status_code=404,
                        ) from exc
                    if (
                        candidate.risk_key
                        and candidate.risk_key != historical_risk.risk_key
                    ):
                        raise DeepLinkValidationError(
                            "medical_monitoring_risk_identity_conflict",
                            "risk_key 与 risk_instance_id 不属于同一风险。",
                        )
                    canonical_risk = by_key.get(historical_risk.risk_key)
                    if canonical_risk is None:
                        raise DeepLinkValidationError(
                            "medical_monitoring_risk_not_in_snapshot",
                            "该风险实例已不在目标快照中，且没有可追溯的当前替代实例。",
                            status_code=409,
                        )
                    redirect_reason = "risk_instance_replaced_in_snapshot"
                    redirect_from = candidate.risk_instance_id
            else:
                canonical_risk = by_key.get(candidate.risk_key)
                if canonical_risk is None:
                    raise DeepLinkValidationError(
                        "medical_monitoring_risk_not_in_snapshot",
                        "该稳定风险标识在目标快照中不存在。",
                        status_code=404,
                    )

            if (
                candidate.risk_key
                and candidate.risk_key != canonical_risk.risk_key
            ):
                raise DeepLinkValidationError(
                    "medical_monitoring_risk_identity_conflict",
                    "risk_key 与 risk_instance_id 不属于同一风险。",
                )
            self._validate_risk_focus_binding(
                canonical_risk,
                site_id=candidate.site_id,
                subject_id=candidate.subject_id,
            )
            if canonical_risk.subject_id or canonical_risk.site_id:
                if subject_index is None:
                    subject_index = self._monitoring_subject_index(canonical_id)
                self._validate_subject_site_binding(
                    subject_index,
                    site_id=str(canonical_risk.site_id or ""),
                    subject_id=str(canonical_risk.subject_id or ""),
                    context="risk",
                )

            candidate = validate_medical_monitoring_deep_link(
                **{
                    **candidate.__dict__,
                    "risk_key": canonical_risk.risk_key,
                    "risk_instance_id": canonical_risk.risk_instance_id,
                    "risk_snapshot_id": selected_snapshot.snapshot_id,
                    "redirect_reason": redirect_reason,
                    "redirect_from_risk_instance_id": redirect_from,
                }
            )

        page_projection = self.current_risk_snapshot(
            canonical_id,
            snapshot_id=(
                selected_snapshot.snapshot_id
                if candidate.risk_snapshot_id and selected_snapshot is not None
                else ""
            ),
            site_id=candidate.site_id or candidate.filter_site_id,
            subject_id=candidate.subject_id or candidate.filter_subject_id,
            risk_category_code=candidate.filter_risk_category_code,
            risk_item=candidate.filter_risk_item,
            severity=candidate.filter_severity,
            disposition_status=candidate.filter_disposition_status,
            updated_at=candidate.filter_updated_at,
            sort_by=candidate.risk_sort_by,
            sort_direction=candidate.risk_sort_direction,
            page=candidate.risk_page,
            page_size=candidate.risk_page_size,
        )
        total = int(page_projection["total"])
        last_page = max(
            1,
            (total + candidate.risk_page_size - 1) // candidate.risk_page_size,
        )
        if candidate.risk_page > last_page:
            raise DeepLinkValidationError(
                "medical_monitoring_page_out_of_range",
                f"risk_page 超出当前筛选结果范围，最大页码为 {last_page}。",
            )
        return candidate

    def _monitoring_subject_index(self, project_id: str) -> Dict[str, str]:
        if not self._registry_has(project_id):
            raise DeepLinkValidationError(
                "medical_monitoring_subject_membership_unverifiable",
                "当前项目没有可用于验证中心和受试者归属的监查目录。",
                status_code=409,
            )
        adapter = self.monitoring_registry.get(project_id)
        try:
            catalog = adapter.subject_catalog()
        except (
            AttributeError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            raise DeepLinkValidationError(
                "medical_monitoring_subject_membership_unverifiable",
                "当前项目的受试者目录不可用，无法验证深链归属。",
                status_code=409,
            ) from exc
        subjects = catalog.get("subjects") if isinstance(catalog, dict) else None
        if not isinstance(subjects, list):
            raise DeepLinkValidationError(
                "medical_monitoring_subject_membership_unverifiable",
                "当前项目的受试者目录格式无效，无法验证深链归属。",
                status_code=409,
            )
        index: Dict[str, str] = {}
        for item in subjects:
            if not isinstance(item, dict):
                continue
            subject = str(item.get("id") or "").strip()
            site = str(item.get("site") or "").strip()
            if subject:
                index[subject] = site
        return index

    @staticmethod
    def _validate_subject_site_binding(
        subject_index: Dict[str, str],
        *,
        site_id: str,
        subject_id: str,
        context: str,
    ) -> None:
        sites = {site for site in subject_index.values() if site}
        if subject_id and subject_id not in subject_index:
            raise DeepLinkValidationError(
                "medical_monitoring_subject_not_found",
                f"{context} 中的受试者不存在或不属于当前项目。",
                status_code=404,
            )
        if site_id and site_id not in sites:
            raise DeepLinkValidationError(
                "medical_monitoring_site_not_found",
                f"{context} 中的中心不存在或不属于当前项目。",
                status_code=404,
            )
        if subject_id and site_id and subject_index[subject_id] != site_id:
            raise DeepLinkValidationError(
                "medical_monitoring_subject_site_mismatch",
                f"{context} 中的受试者不属于所选中心。",
            )

    @staticmethod
    def _validate_risk_focus_binding(
        risk: RiskCase,
        *,
        site_id: str,
        subject_id: str,
    ) -> None:
        if subject_id and risk.subject_id and subject_id != risk.subject_id:
            raise DeepLinkValidationError(
                "medical_monitoring_risk_subject_mismatch",
                "风险实例不属于所选受试者。",
            )
        if site_id and risk.site_id and site_id != risk.site_id:
            raise DeepLinkValidationError(
                "medical_monitoring_risk_site_mismatch",
                "风险实例不属于所选中心。",
            )

    def module_summary(
        self,
        project_id: str,
        *,
        actor: str = "medical_manager",
    ) -> Dict[str, Any]:
        canonical_id = self.canonical_project_id(project_id)
        binding = self._source_binding(canonical_id)
        registered = self._is_registered(canonical_id)

        try:
            snapshot = self.risk_repository.current_snapshot(canonical_id)
        except KeyError:
            return self._empty_summary(
                canonical_id,
                actor=actor,
                binding=binding,
                registered=registered,
            )

        risks = self.risk_repository.list_risks(
            canonical_id,
            snapshot.snapshot_id,
        )
        open_risks = [
            risk for risk in risks if risk.status not in _TERMINAL_RISK_STATUSES
        ]
        read_versions = self._read_versions(canonical_id, actor)
        disposition_by_item = self._latest_dispositions(canonical_id)
        workflow_policy = self._query_workflow_policy(canonical_id)

        unread_count = 0
        needs_action_count = 0
        for risk in open_risks:
            item_id, source_version = _risk_item_identity(
                canonical_id,
                risk,
                snapshot.source_revision,
            )
            if read_versions.get(item_id) != source_version:
                unread_count += 1
            disposition = disposition_by_item.get((item_id, source_version))
            if disposition is not None:
                if _rux_disposition_needs_action(
                    disposition.new_state,
                    approval_required=workflow_policy[
                        "internal_approval_required"
                    ],
                ):
                    needs_action_count += 1
            elif risk.status in _ACTIONABLE_RISK_STATUSES:
                needs_action_count += 1

        high_risk_open_count = sum(
            1
            for risk in open_risks
            if risk.severity in {RiskSeverity.HIGH, RiskSeverity.CRITICAL}
        )
        batch = _latest_batch_projection(snapshot, binding)
        default_link = validate_medical_monitoring_deep_link(
            project_id=canonical_id,
            scope=MonitoringScope.TRIAL,
            view=MonitoringView.CHECKLIST,
            batch_id=snapshot.snapshot_id,
        ).as_dict()

        return {
            "contract_version": SUMMARY_CONTRACT_VERSION,
            "project_id": canonical_id,
            "module": MODULE_KEY,
            "module_label": MODULE_LABEL,
            "availability": "available" if registered else "not_registered",
            "snapshot_status": "available",
            "latest_complete_batch": batch,
            "open_risk_count": len(open_risks),
            "unread_count": unread_count,
            "high_risk_open_count": high_risk_open_count,
            "needs_action_count": needs_action_count,
            "recent_run_status": {
                "status": "snapshot_available",
                "snapshot_id": snapshot.snapshot_id,
                "source_revision": snapshot.source_revision,
                "created_at": snapshot.created_at.isoformat(),
            },
            "source_binding": _binding_projection(binding),
            "query_workflow_policy": workflow_policy,
            "default_deep_link": default_link,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def current_risk_snapshot(
        self,
        project_id: str,
        *,
        snapshot_id: str = "",
        site_id: str = "",
        subject_id: str = "",
        risk_key: str = "",
        risk_instance_id: str = "",
        category: str = "",
        risk_category_code: str = "",
        risk_item: str = "",
        severity: str = "",
        disposition_status: str = "",
        updated_at: str = "",
        status: str = "",
        batch_delta: str = "",
        include_terminal: bool = False,
        sort_by: RiskChecklistSortField = RiskChecklistSortField.UPDATED_AT,
        sort_direction: SortDirection = SortDirection.DESC,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Read the persisted current snapshot without evaluating any rules."""

        canonical_id = self.canonical_project_id(project_id)
        workflow_policy = self._query_workflow_policy(canonical_id)
        effective_category = _validate_snapshot_query(
            category=category,
            risk_category_code=risk_category_code,
            severity=severity,
            disposition_status=disposition_status,
            updated_at=updated_at,
        )
        try:
            current_snapshot = self.risk_repository.current_snapshot(canonical_id)
        except KeyError:
            return {
                "contract_version": SUMMARY_CONTRACT_VERSION,
                "project_id": canonical_id,
                "snapshot_status": "empty",
                "snapshot_id": "",
                "current_snapshot_id": "",
                "is_current_snapshot": True,
                "source_revision": "",
                "page": page,
                "page_size": page_size,
                "total": 0,
                "items": [],
                "taxonomy": risk_taxonomy_payload(),
                "query_workflow_policy": workflow_policy,
                "rollup": _risk_rollup(canonical_id, [], {}),
                "applied_filters": {
                    "snapshot_id": snapshot_id or None,
                    "site_id": site_id or None,
                    "subject_id": subject_id or None,
                    "risk_key": risk_key or None,
                    "risk_instance_id": risk_instance_id or None,
                    "risk_category_code": effective_category or None,
                    "risk_item": risk_item or None,
                    "severity": severity or None,
                    "disposition_status": disposition_status or None,
                    "updated_at": updated_at or None,
                    "status": status or None,
                    "batch_delta": batch_delta or None,
                    "include_terminal": include_terminal,
                },
                "sort": {
                    "field": sort_by.value,
                    "direction": sort_direction.value,
                    "stable_tiebreaker": "risk_instance_id",
                },
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        selected_snapshot = current_snapshot
        if snapshot_id and snapshot_id != current_snapshot.snapshot_id:
            try:
                selected_snapshot = self.risk_repository.snapshot(
                    canonical_id,
                    snapshot_id,
                )
            except KeyError as exc:
                raise RiskSnapshotQueryError(
                    "medical_monitoring_snapshot_not_found",
                    "所选风险快照不存在或不属于当前项目。",
                ) from exc

        risks = self.risk_repository.list_risks(
            canonical_id,
            selected_snapshot.snapshot_id,
        )
        if not include_terminal and not status:
            risks = [
                risk for risk in risks if risk.status not in _TERMINAL_RISK_STATUSES
            ]
        if site_id:
            risks = [risk for risk in risks if risk.site_id == site_id]
        if subject_id:
            risks = [risk for risk in risks if risk.subject_id == subject_id]
        if risk_key:
            risks = [risk for risk in risks if risk.risk_key == risk_key]
        if risk_instance_id:
            risks = [
                risk for risk in risks if risk.risk_instance_id == risk_instance_id
            ]
        if effective_category:
            risks = [
                risk
                for risk in risks
                if project_risk_category(risk)["risk_category_code"]
                == effective_category
            ]
        if severity:
            risks = [risk for risk in risks if risk.severity.value == severity]
        if status:
            risks = [risk for risk in risks if risk.status.value == status]
        if batch_delta:
            risks = [risk for risk in risks if risk.batch_delta == batch_delta]

        work_items = self._risk_work_item_projections(canonical_id)
        rows = [
            _checklist_row(
                risk,
                work_items.get(risk.risk_instance_id or risk.risk_id),
            )
            for risk in risks
        ]
        if risk_item:
            query = risk_item.casefold()
            rows = [
                row for row in rows if query in row["risk_item"].casefold()
            ]
        if disposition_status:
            rows = [
                row
                for row in rows
                if disposition_status
                in {
                    row["disposition_status"],
                    str(
                        (row.get("work_item") or {}).get(
                            "medical_disposition_status",
                            "",
                        )
                    ),
                }
            ]
        if updated_at:
            rows = [
                row for row in rows if row["updated_at"].startswith(updated_at)
            ]

        rows.sort(
            key=lambda row: (
                _checklist_sort_value(row, sort_by),
                row["risk_instance_id"],
            ),
            reverse=sort_direction is SortDirection.DESC,
        )
        total = len(rows)
        start = (page - 1) * page_size
        projected_items = rows[start : start + page_size]
        filtered_risk_ids = {row["risk_instance_id"] for row in rows}
        filtered_risks = [
            risk for risk in risks if risk.risk_instance_id in filtered_risk_ids
        ]
        return {
            "contract_version": SUMMARY_CONTRACT_VERSION,
            "project_id": canonical_id,
            "snapshot_status": "available",
            "snapshot_id": selected_snapshot.snapshot_id,
            "current_snapshot_id": current_snapshot.snapshot_id,
            "is_current_snapshot": (
                selected_snapshot.snapshot_id == current_snapshot.snapshot_id
            ),
            "previous_snapshot_id": selected_snapshot.previous_snapshot_id or "",
            "source_revision": selected_snapshot.source_revision,
            "rule_profile_revision": selected_snapshot.rule_profile_revision,
            "engine_version": selected_snapshot.engine_version,
            "resolution_complete": selected_snapshot.resolution_complete,
            "resolution_eligible_risk_count": len(
                selected_snapshot.resolution_eligible_risk_keys
            ),
            "analysis_source": "persisted_snapshot",
            "subjects_evaluated": selected_snapshot.evaluated_subject_count,
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": projected_items,
            "taxonomy": risk_taxonomy_payload(),
            "query_workflow_policy": workflow_policy,
            "rollup": _risk_rollup(canonical_id, filtered_risks, work_items),
            "applied_filters": {
                "snapshot_id": snapshot_id or None,
                "site_id": site_id or None,
                "subject_id": subject_id or None,
                "risk_key": risk_key or None,
                "risk_instance_id": risk_instance_id or None,
                "risk_category_code": effective_category or None,
                "risk_item": risk_item or None,
                "severity": severity or None,
                "disposition_status": disposition_status or None,
                "updated_at": updated_at or None,
                "status": status or None,
                "batch_delta": batch_delta or None,
                "include_terminal": include_terminal,
            },
            "sort": {
                "field": sort_by.value,
                "direction": sort_direction.value,
                "stable_tiebreaker": "risk_instance_id",
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def current_risk_export(
        self,
        project_id: str,
        *,
        snapshot_id: str = "",
        site_id: str = "",
        subject_id: str = "",
        risk_key: str = "",
        risk_instance_id: str = "",
        category: str = "",
        risk_category_code: str = "",
        risk_item: str = "",
        severity: str = "",
        disposition_status: str = "",
        updated_at: str = "",
        status: str = "",
        batch_delta: str = "",
        include_terminal: bool = False,
        sort_by: RiskChecklistSortField = RiskChecklistSortField.UPDATED_AT,
        sort_direction: SortDirection = SortDirection.DESC,
    ) -> Dict[str, Any]:
        """Export the exact filtered snapshot projection without evaluating rules."""

        query = {
            "snapshot_id": snapshot_id,
            "site_id": site_id,
            "subject_id": subject_id,
            "risk_key": risk_key,
            "risk_instance_id": risk_instance_id,
            "category": category,
            "risk_category_code": risk_category_code,
            "risk_item": risk_item,
            "severity": severity,
            "disposition_status": disposition_status,
            "updated_at": updated_at,
            "status": status,
            "batch_delta": batch_delta,
            "include_terminal": include_terminal,
            "sort_by": sort_by,
            "sort_direction": sort_direction,
        }
        first = self.current_risk_snapshot(
            project_id,
            **query,
            page=1,
            page_size=200,
        )
        items = list(first["items"])
        if first["total"] > len(items):
            complete = self.current_risk_snapshot(
                project_id,
                **{
                    **query,
                    "snapshot_id": first["snapshot_id"],
                },
                page=1,
                page_size=first["total"],
            )
            items = list(complete["items"])
        if len(items) != first["total"]:
            raise RuntimeError("risk export projection is incomplete")

        risks_by_instance: Dict[str, RiskCase] = {}
        if first["snapshot_id"]:
            risks_by_instance = {
                risk.risk_instance_id: risk
                for risk in self.risk_repository.list_risks(
                    first["project_id"],
                    first["snapshot_id"],
                )
            }
        archive = _risk_export_archive(items, risks_by_instance)
        return {
            "contract_version": RISK_EXPORT_CONTRACT_VERSION,
            "content": archive,
            "media_type": "application/zip",
            "filename": (
                "medical-risk-checklist-"
                f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
            ),
            "snapshot_id": first["snapshot_id"],
            "total": first["total"],
        }

    def _empty_summary(
        self,
        project_id: str,
        *,
        actor: str,
        binding: Any,
        registered: bool,
    ) -> Dict[str, Any]:
        del actor
        return {
            "contract_version": SUMMARY_CONTRACT_VERSION,
            "project_id": project_id,
            "module": MODULE_KEY,
            "module_label": MODULE_LABEL,
            "availability": "available" if registered else "not_registered",
            "snapshot_status": "empty",
            "latest_complete_batch": None,
            "open_risk_count": 0,
            "unread_count": 0,
            "high_risk_open_count": 0,
            "needs_action_count": 0,
            "recent_run_status": {
                "status": "not_started",
                "snapshot_id": "",
                "source_revision": "",
                "created_at": None,
            },
            "source_binding": _binding_projection(binding),
            "query_workflow_policy": self._query_workflow_policy(project_id),
            "default_deep_link": validate_medical_monitoring_deep_link(
                project_id=project_id,
                scope=MonitoringScope.TRIAL,
                view=MonitoringView.CHECKLIST,
            ).as_dict(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _source_binding(self, project_id: str) -> Any:
        if self.project_source_manifest_service is None:
            return None
        try:
            return self.project_source_manifest_service.module_binding(
                project_id,
                MODULE_KEY,
            )
        except KeyError:
            return None

    def _is_registered(self, project_id: str) -> bool:
        if self.monitoring_registry is None:
            return True
        return self._registry_has(project_id)

    def _registry_has(self, project_id: str) -> bool:
        """Treat only a literal registry Boolean as module availability."""

        return (
            self.monitoring_registry is not None
            and self.monitoring_registry.has(project_id) is True
        )

    def _read_versions(self, project_id: str, actor: str) -> Dict[str, str]:
        service = self.workbench_inbox_service
        store = getattr(service, "store", None)
        records = store.records(project_id, actor) if store is not None else []
        return _read_versions(records)

    def _latest_dispositions(self, project_id: str) -> Dict[tuple[str, str], Any]:
        service = self.workbench_inbox_service
        store = getattr(service, "rux_disposition_store", None)
        records: Iterable[Any] = store.records(project_id) if store is not None else []
        latest: Dict[tuple[str, str], Any] = {}
        for record in records:
            key = (record.item_id, record.source_version)
            current = latest.get(key)
            if current is None or record.created_at > current.created_at:
                latest[key] = record
        return latest

    def _query_workflow_policy(self, project_id: str) -> Dict[str, Any]:
        service = self.workbench_inbox_service
        if service is None or not hasattr(
            service, "monitoring_query_workflow_policy"
        ):
            return {
                "internal_approval_required": False,
                "formal_send_managed_outside_monitoring": True,
            }
        return service.monitoring_query_workflow_policy(project_id)

    def _risk_work_item_projections(
        self,
        project_id: str,
        *,
        actor: str = "medical_manager",
    ) -> Dict[str, Dict[str, Any]]:
        service = self.workbench_inbox_service
        if service is None or not hasattr(service, "monitoring_risk_items"):
            return {}
        try:
            items = service.monitoring_risk_items(project_id, actor=actor)
        except (KeyError, ValueError):
            return {}
        projections: Dict[str, Dict[str, Any]] = {}
        for item in items:
            risk_id = item.risk_instance_id or item.source_id
            if not risk_id:
                continue
            disposition_state = _disposition_state_from_label(item.status)
            projections[risk_id] = {
                "item_id": item.item_id,
                "medical_disposition_status": item.status,
                "medical_disposition_state": disposition_state,
                "read_state": "unread" if item.unread else "read",
                "unread": item.unread,
                "needs_action": item.needs_action,
                "query_workflow_state": _query_workflow_state(
                    disposition_state,
                    self._query_workflow_policy(project_id),
                ),
                "action_label": item.action_label,
                "source_version": item.source_version,
                "source_refs": [
                    ref.model_dump(mode="json") for ref in item.source_refs
                ],
                "disposition_kind": (
                    item.disposition_kind.value
                    if item.disposition_kind is not None
                    else None
                ),
                "medical_judgments": (
                    item.medical_judgments.model_dump(mode="json")
                    if item.medical_judgments is not None
                    else None
                ),
                "last_action_at": item.updated_at.isoformat(),
            }
        return projections


class MedicalMonitoringRunService:
    """Explicit command boundary for generating a persisted risk snapshot."""

    def __init__(
        self,
        *,
        risk_repository: Any,
        project_source_manifest_service: Any = None,
        monitoring_registry: Any,
    ) -> None:
        self.risk_repository = risk_repository
        self.project_source_manifest_service = project_source_manifest_service
        self.monitoring_registry = monitoring_registry

    def canonical_project_id(self, project_id: str) -> str:
        if self.project_source_manifest_service is None:
            return project_id
        return self.project_source_manifest_service.canonical_project_id(project_id)

    def run(self, project_id: str) -> Dict[str, Any]:
        canonical_id = self.canonical_project_id(project_id)
        if self.monitoring_registry is None or self.monitoring_registry.has(
            canonical_id
        ) is not True:
            raise KeyError(canonical_id)

        adapter = self.monitoring_registry.get(canonical_id)
        source_revision = adapter.source_revision()
        rule_profile_revision = adapter.risk_profile_revision()
        engine_version = adapter.risk_engine_version()

        try:
            current = self.risk_repository.current_snapshot(canonical_id)
        except KeyError:
            current = None
        if (
            current is not None
            and current.source_revision == source_revision
            and current.rule_profile_revision == rule_profile_revision
            and current.engine_version == engine_version
        ):
            return self._response(
                canonical_id,
                current,
                status="current_snapshot_reused",
            )

        subject_ids = adapter.subject_ids()
        risks = [
            risk
            for subject_id in subject_ids
            for risk in adapter.evaluate_subject_risks(subject_id)
        ]
        risks = capture_risk_evidence(
            adapter,
            risks,
            source_revision=source_revision,
        )
        snapshot = self.risk_repository.save_snapshot(
            project_id=canonical_id,
            source_revision=source_revision,
            rule_profile_revision=rule_profile_revision,
            engine_version=engine_version,
            evaluated_subject_count=len(subject_ids),
            risks=risks,
            resolution_complete=adapter.risk_resolution_complete(),
        )
        return self._response(canonical_id, snapshot, status="snapshot_generated")

    @staticmethod
    def _response(project_id: str, snapshot: Any, *, status: str) -> Dict[str, Any]:
        return {
            "contract_version": RUN_CONTRACT_VERSION,
            "project_id": project_id,
            "status": status,
            "snapshot_id": snapshot.snapshot_id,
            "source_revision": snapshot.source_revision,
            "rule_profile_revision": snapshot.rule_profile_revision,
            "engine_version": snapshot.engine_version,
            "risk_count": snapshot.risk_count,
            "subjects_evaluated": snapshot.evaluated_subject_count,
            "resolution_complete": snapshot.resolution_complete,
            "created_at": snapshot.created_at.isoformat(),
        }


def _risk_item_identity(
    project_id: str,
    risk: RiskCase,
    source_revision: str,
) -> tuple[str, str]:
    risk_instance_id = risk.risk_instance_id or risk.risk_id
    if project_id == RUX_PROJECT_ID:
        return (
            f"rux-risk:{risk_instance_id}",
            _rux_source_version(risk, source_revision),
        )
    return (
        f"monitoring-risk:{risk_instance_id}",
        _monitoring_source_version(risk, source_revision),
    )


def _latest_batch_projection(snapshot: Any, binding: Any) -> Dict[str, Any]:
    display_batch = getattr(binding, "display_batch_label", "") if binding else ""
    extract_date = getattr(binding, "display_extract_date", "") if binding else ""
    resolution_complete = snapshot.resolution_complete is True
    return {
        "batch_id": snapshot.snapshot_id,
        "batch_label": display_batch or snapshot.source_revision,
        "extract_date": extract_date,
        "source_revision": snapshot.source_revision,
        "snapshot_id": snapshot.snapshot_id,
        "created_at": snapshot.created_at.isoformat(),
        "resolution_complete": resolution_complete,
        "completeness": (
            "complete" if resolution_complete else "not_asserted"
        ),
    }


def _binding_projection(binding: Optional[Any]) -> Optional[Dict[str, Any]]:
    if binding is None:
        return None
    return {
        "route_project_id": binding.route_project_id,
        "implementation_status": binding.implementation_status,
        "primary_source_ids": list(binding.primary_source_ids),
        "supplemental_source_ids": list(binding.supplemental_source_ids),
        "display_batch": {
            "batch_label": binding.display_batch_label,
            "extract_date": binding.display_extract_date,
        },
    }


def _disposition_state_from_label(label: str) -> str:
    return {
        "待医学复核": "pending_review",
        "已医学复核": "reviewed",
        "Query草稿": "query_draft",
        "已提交内部审批": "submitted_for_approval",
        "已说明，无需外部动作": "explained_no_external_action",
        "已转数据更正": "data_correction",
        "已转追加随访": "follow_up",
        "已转PD补充/更新": "pd_update",
        "已转Safety/PV协作": "safety_pv_collaboration",
        "持续观察": "continue_observation",
        "重复项/不适用": "duplicate_not_applicable",
    }.get(label, "pending_review")


def _query_workflow_state(
    disposition_state: str,
    policy: Dict[str, Any],
) -> str:
    if disposition_state == "submitted_for_approval":
        return "internal_approval_pending"
    if disposition_state == "query_draft":
        return (
            "draft_pending_internal_approval"
            if policy.get("internal_approval_required")
            else "draft_ready"
        )
    if disposition_state == "reviewed":
        return "draft_not_created"
    if disposition_state == "pending_review":
        return "not_started"
    return "not_applicable"


_DISPOSITION_STATES = frozenset(
    {
        "pending_review",
        "reviewed",
        "query_draft",
        "submitted_for_approval",
        "explained_no_external_action",
        "data_correction",
        "follow_up",
        "pd_update",
        "safety_pv_collaboration",
        "continue_observation",
        "duplicate_not_applicable",
    }
)
_DISPOSITION_DISPLAY_LABELS = {
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
}
_DISPOSITION_LABELS = frozenset(
    _DISPOSITION_DISPLAY_LABELS.values()
)
_SEVERITY_DISPLAY_LABELS = {
    "critical": "紧急",
    "high": "高",
    "medium": "中",
    "low": "低",
}
_LOCAL_PATH_RE = re.compile(
    r"(?i)(?:file://)?/(?:Users|private|Volumes|home|tmp)(?:/[^\s,;，；]*)+"
)
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\s,;，；]+")
_INTERNAL_LOCATOR_PREFIXES = (
    "batch:",
    "candidate:",
    "job:",
    "monitoring-ai:",
)
_INTERNAL_EVIDENCE_KEYS = {
    "batch_id",
    "candidate_id",
    "engine_version",
    "file_path",
    "input_revision_sha256",
    "job_id",
    "local_path",
    "mapping_revision",
    "prompt_version",
    "root_path",
    "rule_pack_id",
    "rule_revision_id",
    "source_revision",
}
_UPDATED_AT_FILTER_RE = re.compile(
    r"^\d{4}(?:-\d{2}(?:-\d{2}(?:[T ][-+0-9:.Z]*)?)?)?$"
)


def _validate_snapshot_query(
    *,
    category: str,
    risk_category_code: str,
    severity: str,
    disposition_status: str,
    updated_at: str,
) -> str:
    canonical_codes = set(canonical_risk_category_codes())
    effective_category = ""
    if risk_category_code:
        if risk_category_code not in canonical_codes:
            raise RiskSnapshotQueryError(
                "unsupported_risk_category_code",
                f"不支持的风险类别代码：{risk_category_code}",
            )
        effective_category = risk_category_code
    if category:
        legacy = resolve_risk_category(category)
        if legacy.mapping_kind == "unknown":
            raise RiskSnapshotQueryError(
                "unsupported_legacy_category",
                f"不支持的旧风险类别代码：{category}",
            )
        legacy_code = legacy.definition.code.value
        if effective_category and effective_category != legacy_code:
            raise RiskSnapshotQueryError(
                "risk_category_filter_conflict",
                "category 与 risk_category_code 不能指定不同类别。",
            )
        effective_category = legacy_code
    if severity and severity not in {item.value for item in RiskSeverity}:
        raise RiskSnapshotQueryError(
            "unsupported_risk_severity",
            f"不支持的风险等级：{severity}",
        )
    if (
        disposition_status
        and disposition_status not in _DISPOSITION_STATES
        and disposition_status not in _DISPOSITION_LABELS
    ):
        raise RiskSnapshotQueryError(
            "unsupported_disposition_status",
            f"不支持的处置状态：{disposition_status}",
        )
    if updated_at and not _UPDATED_AT_FILTER_RE.fullmatch(updated_at):
        raise RiskSnapshotQueryError(
            "invalid_updated_at_filter",
            "updated_at 必须是 ISO 8601 日期或时间前缀。",
        )
    return effective_category


def _checklist_row(
    risk: RiskCase,
    work_item: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    category = project_risk_category(risk)
    disposition_status = (
        str(work_item.get("medical_disposition_state") or "pending_review")
        if work_item
        else "pending_review"
    )
    updated_at = (
        str(work_item.get("last_action_at") or risk.created_at.isoformat())
        if work_item
        else risk.created_at.isoformat()
    )
    return {
        **public_risk_payload(risk),
        "primary_category": category["risk_category_code"],
        **category,
        "risk_item": risk.title,
        "disposition_status": disposition_status,
        "updated_at": updated_at,
        "detection_status": risk.status.value,
        "work_item": work_item,
    }


def _checklist_sort_value(
    row: Dict[str, Any],
    sort_by: RiskChecklistSortField,
) -> Any:
    if sort_by is RiskChecklistSortField.SEVERITY:
        return {
            "low": 0,
            "medium": 1,
            "high": 2,
            "critical": 3,
        }.get(str(row.get("severity") or ""), -1)
    return str(row.get(sort_by.value) or "").casefold()


def _risk_export_archive(
    rows: list[Dict[str, Any]],
    risks_by_instance: Dict[str, RiskCase],
) -> bytes:
    checklist_headers = [
        "受试者编号",
        "中心编号",
        "风险级别",
        "风险类别",
        "具体风险项",
        "当前处置",
        "更新时间",
    ]
    checklist_rows = [
        {
            "受试者编号": row.get("subject_id") or "-",
            "中心编号": row.get("site_id") or "-",
            "风险级别": _SEVERITY_DISPLAY_LABELS.get(
                str(row.get("severity") or ""),
                str(row.get("severity") or ""),
            ),
            "风险类别": _risk_category_export_label(row),
            "具体风险项": _sanitize_export_text(row.get("risk_item")),
            "当前处置": _DISPOSITION_DISPLAY_LABELS.get(
                str(row.get("disposition_status") or ""),
                str(row.get("disposition_status") or "待医学复核"),
            ),
            "更新时间": _export_datetime(row.get("updated_at")),
        }
        for row in rows
    ]
    evidence_headers = [
        "风险清单行号",
        "受试者编号",
        "中心编号",
        "风险类别",
        "具体风险项",
        "证据类型",
        "原始事实或依据",
        "补充字段",
        "次级定位",
        "证据状态",
        "判断理由",
        "建议动作",
    ]
    evidence_rows: list[Dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=1):
        risk = risks_by_instance.get(str(row.get("risk_instance_id") or ""))
        evidence_rows.extend(_risk_evidence_export_rows(row_number, row, risk))

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "risk-checklist.csv",
            _csv_bytes(checklist_headers, checklist_rows),
        )
        archive.writestr(
            "risk-evidence.csv",
            _csv_bytes(evidence_headers, evidence_rows),
        )
    return buffer.getvalue()


def _csv_bytes(headers: list[str], rows: list[Dict[str, Any]]) -> bytes:
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return b"\xef\xbb\xbf" + stream.getvalue().encode("utf-8")


def _risk_evidence_export_rows(
    row_number: int,
    row: Dict[str, Any],
    risk: Optional[RiskCase],
) -> list[Dict[str, Any]]:
    base = {
        "风险清单行号": row_number,
        "受试者编号": row.get("subject_id") or "-",
        "中心编号": row.get("site_id") or "-",
        "风险类别": _risk_category_export_label(row),
        "具体风险项": _sanitize_export_text(row.get("risk_item")),
    }
    exported: list[Dict[str, Any]] = []
    if risk:
        snapshots = sorted(
            risk.evidence_snapshots,
            key=lambda item: _evidence_order(item.fragment),
        )
        for snapshot in snapshots:
            fragment = snapshot.fragment if isinstance(snapshot.fragment, dict) else {}
            exported.append(
                {
                    **base,
                    "证据类型": _evidence_type_label(fragment),
                    "原始事实或依据": _evidence_fact_text(fragment),
                    "补充字段": _evidence_field_text(fragment),
                    "次级定位": _public_evidence_locator(snapshot.locator, fragment),
                    "证据状态": (
                        "可追溯"
                        if snapshot.available
                        else f"来源片段不可用：{snapshot.error_code or '未说明'}"
                    ),
                    "判断理由": "",
                    "建议动作": "",
                }
            )
        exported.append(
            {
                **base,
                "证据类型": "系统规则与判断",
                "原始事实或依据": _sanitize_export_text(risk.rationale),
                "补充字段": "",
                "次级定位": "",
                "证据状态": (
                    "已包含冻结来源片段"
                    if snapshots
                    else "未包含冻结来源片段"
                ),
                "判断理由": _sanitize_export_text(risk.rationale),
                "建议动作": _sanitize_export_text(risk.recommended_action),
            }
        )
        return exported

    return [
        {
            **base,
            "证据类型": "系统规则与判断",
            "原始事实或依据": _sanitize_export_text(row.get("rationale")),
            "补充字段": "",
            "次级定位": "",
            "证据状态": "未取得冻结来源片段",
            "判断理由": _sanitize_export_text(row.get("rationale")),
            "建议动作": _sanitize_export_text(row.get("recommended_action")),
        }
    ]


def _risk_category_export_label(row: Dict[str, Any]) -> str:
    labels = [str(row.get("risk_category_label") or "其他医学复核")]
    if row.get("safety_pv_flag") is True:
        labels.append("Safety/PV")
    return "；".join(labels)


def _evidence_order(fragment: Dict[str, Any]) -> int:
    source_type = str(fragment.get("source_type") or "").casefold()
    if source_type in {"listing", "raw_data", "edc_listing"}:
        return 0
    if source_type in {"protocol", "protocol_rule"}:
        return 1
    if source_type in {"calculation", "derivation"}:
        return 2
    return 3


def _evidence_type_label(fragment: Dict[str, Any]) -> str:
    source_type = str(fragment.get("source_type") or "").casefold()
    if source_type in {"listing", "raw_data", "edc_listing"}:
        return "原始数据"
    if source_type in {"protocol", "protocol_rule"}:
        return "方案依据"
    if source_type in {"calculation", "derivation"}:
        return "计算过程"
    if fragment.get("current_raw_data") or fragment.get("raw_value_summary"):
        return "原始数据与规则依据"
    return "来源证据"


def _evidence_fact_text(fragment: Dict[str, Any]) -> str:
    for key in (
        "primary_summary",
        "text",
        "raw_value_summary",
        "protocol_source_text",
    ):
        value = _sanitize_export_text(fragment.get(key))
        if value:
            return value
    facts = fragment.get("facts")
    if isinstance(facts, list):
        readable = [
            _sanitize_export_text(
                item.get("text")
                or item.get("fact")
                or item.get("summary")
                or item.get("value")
            )
            if isinstance(item, dict)
            else _sanitize_export_text(item)
            for item in facts
        ]
        if any(readable):
            return "；".join(item for item in readable if item)
    fields = _public_field_pairs(fragment.get("fields"))
    if fields:
        return "；".join(fields)
    current_raw = _public_mapping_pairs(fragment.get("current_raw_data"))
    return "；".join(current_raw)


def _evidence_field_text(fragment: Dict[str, Any]) -> str:
    fields = _public_field_pairs(fragment.get("fields"))
    if not fields:
        fields = _public_mapping_pairs(fragment.get("current_raw_data"))
    return "；".join(fields)


def _public_field_pairs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    pairs = []
    for item in value:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        if (
            not field
            or field.startswith("__")
            or field.casefold() in _INTERNAL_EVIDENCE_KEYS
        ):
            continue
        clean_value = _sanitize_export_text(item.get("value"))
        if clean_value:
            pairs.append(f"{field}={clean_value}")
    return pairs


def _public_mapping_pairs(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    pairs = []
    for key, item in value.items():
        field = str(key).strip()
        if (
            not field
            or field.startswith("__")
            or field.casefold() in _INTERNAL_EVIDENCE_KEYS
        ):
            continue
        clean_value = _sanitize_export_text(item)
        if clean_value:
            pairs.append(f"{field}={clean_value}")
    return pairs


def _public_evidence_locator(locator: str, fragment: Dict[str, Any]) -> str:
    display_locator = _sanitize_export_text(fragment.get("display_locator"))
    if display_locator:
        return display_locator
    raw = str(locator or "").strip()
    if raw.casefold().startswith(_INTERNAL_LOCATOR_PREFIXES):
        return ""
    return _sanitize_export_text(raw)


def _sanitize_export_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return ""
    text = str(value).strip()
    if not text:
        return ""
    text = _LOCAL_PATH_RE.sub("[本地路径已隐藏]", text)
    text = _WINDOWS_PATH_RE.sub("[本地路径已隐藏]", text)
    return text


def _export_datetime(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return _sanitize_export_text(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _risk_rollup(
    project_id: str,
    risks: Iterable[RiskCase],
    work_items: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    risk_list = list(risks)
    work_items = work_items or {}

    def counts(values: Iterable[str]) -> Dict[str, int]:
        result: Dict[str, int] = {}
        for value in values:
            key = value or "unassigned"
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items()))

    def scope_projection(
        scope_type: str,
        scope_id: str,
        scoped_risks: Iterable[RiskCase],
    ) -> Dict[str, Any]:
        scoped = list(scoped_risks)
        projections = [
            work_items.get(risk.risk_instance_id or risk.risk_id, {})
            for risk in scoped
        ]
        return {
            "scope_type": scope_type,
            "scope_id": scope_id,
            "risk_count": len(scoped),
            "unread_count": sum(
                1 for item in projections if item.get("read_state") == "unread"
            ),
            "needs_action_count": sum(
                1 for item in projections if item.get("needs_action")
            ),
            "medical_disposition_counts": counts(
                item.get("medical_disposition_state", "unprojected")
                for item in projections
            ),
            "detection_status_counts": counts(
                risk.status.value for risk in scoped
            ),
        }

    site_ids = sorted({risk.site_id or "unassigned" for risk in risk_list})
    subject_ids = sorted(
        {risk.subject_id or "unassigned" for risk in risk_list}
    )
    trial = {
        **scope_projection("trial", project_id, risk_list),
        "category_counts": counts(
            project_risk_category(risk)["risk_category_code"]
            for risk in risk_list
        ),
        "severity_counts": counts(risk.severity.value for risk in risk_list),
        "batch_delta_counts": counts(risk.batch_delta for risk in risk_list),
    }
    return {
        "trial": trial,
        "sites": [
            scope_projection(
                "site",
                site_id,
                (risk for risk in risk_list if (risk.site_id or "unassigned") == site_id),
            )
            for site_id in site_ids
        ],
        "subjects": [
            scope_projection(
                "subject",
                subject_id,
                (
                    risk
                    for risk in risk_list
                    if (risk.subject_id or "unassigned") == subject_id
                ),
            )
            for subject_id in subject_ids
        ],
    }
