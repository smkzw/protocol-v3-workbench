from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha1
from typing import Dict
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    AuditEvent,
    EvidenceCandidatePage,
    EvidenceReviewAction,
    EvidenceReviewActionRequest,
    EvidenceReviewRecord,
    EvidenceReviewState,
)

from .evidence_design_manifest import EvidenceDesignManifestService
from .sqlite_runtime_store import SqliteRuntimeStore


class EvidenceReviewWorkflowService:
    def __init__(
        self,
        manifest_service: EvidenceDesignManifestService,
        runtime_store: SqliteRuntimeStore,
    ):
        self.manifest_service = manifest_service
        self.runtime_store = runtime_store

    def candidate_page(
        self,
        project_id: str,
        package_id: str,
        *,
        candidate_type: str = "all",
        page: int = 1,
        page_size: int = 50,
        search: str = "",
    ) -> EvidenceCandidatePage:
        page_result = self.manifest_service.candidate_page(
            project_id,
            package_id,
            candidate_type=candidate_type,
            page=page,
            page_size=page_size,
            search=search,
        )
        latest = self._latest_records(project_id, package_id)
        return page_result.model_copy(
            update={
                "items": [
                    item.model_copy(
                        update={
                            "screening_status": latest[item.evidence_id].screening_status,
                            "appraisal_status": latest[item.evidence_id].appraisal_status,
                            "review_revision": latest[item.evidence_id].new_revision,
                        }
                    )
                    if item.evidence_id in latest
                    else item
                    for item in page_result.items
                ]
            }
        )

    def state(self, project_id: str, package_id: str, evidence_id: str) -> EvidenceReviewState:
        self.manifest_service.candidate_detail(project_id, package_id, evidence_id)
        records = self.runtime_store.evidence_review_records(project_id, package_id, evidence_id)
        if not records:
            return EvidenceReviewState(
                project_id=project_id,
                package_id=package_id,
                evidence_id=evidence_id,
            )
        latest = records[-1]
        return EvidenceReviewState(
            project_id=project_id,
            package_id=package_id,
            evidence_id=evidence_id,
            revision=latest.new_revision,
            screening_status=latest.screening_status,
            appraisal_status=latest.appraisal_status,
            reason=latest.reason,
            extraction=latest.extraction,
            quality_rating=latest.quality_rating,
            history=records[-20:],
        )

    def apply_action(
        self,
        project_id: str,
        package_id: str,
        evidence_id: str,
        request: EvidenceReviewActionRequest,
    ) -> EvidenceReviewState:
        if not isinstance(request, EvidenceReviewActionRequest):
            request = EvidenceReviewActionRequest.model_validate(request)
        self.manifest_service.candidate_detail(project_id, package_id, evidence_id)
        before = self.state(project_id, package_id, evidence_id)
        if request.expected_revision != before.revision:
            raise ValueError(
                f"证据审阅状态已更新：expected={request.expected_revision}, actual={before.revision}"
            )

        reason = request.reason.strip() or before.reason
        extraction = dict(before.extraction)
        quality_rating = before.quality_rating
        screening_status = before.screening_status
        appraisal_status = before.appraisal_status

        if request.action == EvidenceReviewAction.INCLUDE:
            screening_status = "已纳入"
        elif request.action == EvidenceReviewAction.EXCLUDE:
            if not request.reason.strip():
                raise ValueError("排除证据时必须填写排除理由。")
            screening_status = "已排除"
        elif request.action == EvidenceReviewAction.DEFER:
            if not request.reason.strip():
                raise ValueError("暂缓筛选时必须说明待补信息。")
            screening_status = "待补证"
        elif request.action == EvidenceReviewAction.MARK_DUPLICATE:
            if not request.reason.strip():
                raise ValueError("标记重复项时必须填写主记录或重复依据。")
            screening_status = "重复项"
        elif request.action == EvidenceReviewAction.SAVE_EXTRACTION:
            if before.screening_status != "已纳入":
                raise ValueError("只有已纳入证据可以保存结构化抽取。")
            if not request.extraction:
                raise ValueError("结构化抽取内容不能为空。")
            extraction.update({key: value.strip() for key, value in request.extraction.items() if value.strip()})
            appraisal_status = "待评价"
        elif request.action == EvidenceReviewAction.SAVE_APPRAISAL:
            if before.screening_status != "已纳入":
                raise ValueError("只有已纳入证据可以进行证据质量评价。")
            if request.quality_rating not in {"high", "moderate", "low"}:
                raise ValueError("当前内部证据质量评价仅接受high、moderate或low。")
            quality_rating = request.quality_rating
            appraisal_status = "已评价"
        elif request.action == EvidenceReviewAction.RESET_REVIEW:
            reason = ""
            extraction = {}
            quality_rating = ""
            screening_status = "待筛选"
            appraisal_status = "待评价"

        created_at = datetime.now(timezone.utc)
        record = EvidenceReviewRecord(
            record_id=f"evidence_review_{uuid4().hex}",
            project_id=project_id,
            package_id=package_id,
            evidence_id=evidence_id,
            action=request.action,
            actor=request.actor,
            reason=reason,
            extraction=extraction,
            quality_rating=quality_rating,
            screening_status=screening_status,
            appraisal_status=appraisal_status,
            previous_revision=before.revision,
            new_revision=before.revision + 1,
            created_at=created_at,
        )
        audit_event = AuditEvent(
            audit_id=f"audit_{uuid4().hex}",
            project_id=project_id,
            actor=request.actor,
            action=request.action.value,
            target_type="evidence_candidate",
            target_id=evidence_id,
            detail={
                "package_id": package_id,
                "previous_revision": before.revision,
                "new_revision": record.new_revision,
                "record_id": record.record_id,
            },
            created_at=created_at,
        )
        fingerprint = sha1(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.runtime_store.commit_evidence_review_action(
            record,
            audit_event,
            expected_revision=before.revision,
            idempotency_key=request.idempotency_key or f"evidence-review:{record.record_id}",
            request_fingerprint=fingerprint,
        )
        return self.state(project_id, package_id, evidence_id)

    def _latest_records(self, project_id: str, package_id: str) -> Dict[str, EvidenceReviewRecord]:
        latest: Dict[str, EvidenceReviewRecord] = {}
        for record in self.runtime_store.evidence_review_records(project_id, package_id):
            current = latest.get(record.evidence_id)
            if current is None or record.new_revision > current.new_revision:
                latest[record.evidence_id] = record
        return latest
