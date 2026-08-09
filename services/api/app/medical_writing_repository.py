from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, List, Mapping, Optional, Tuple
from uuid import uuid4

from packages.contracts.workbench_contracts import (
    ApprovalAction,
    ApprovalActionRequest,
    ApprovalActionResult,
    ApprovalBlocker,
    ApprovalDecisionRecord,
    ApprovalGate,
    ApprovalState,
    AuditEvent,
    MedicalWritingContentDispositionRecord,
    MedicalWritingContentDispositionRequest,
    MedicalWritingContentDispositionStatus,
    MedicalWritingContentFinding,
    MedicalWritingContentQualityResult,
    MedicalWritingWorkingCopy,
    MedicalWritingWorkingCopyBindingRecoveryRequest,
    MedicalWritingWorkingCopyBindingRecoveryResult,
    MedicalWritingWorkingCopySaveRequest,
    MedicalWritingRevisionApplyRequest,
    MedicalWritingRevisionApplyResult,
    MedicalWritingTableCellAnchor,
    ProtocolDocument,
    RevisionImpactRef,
    RevisionThread,
    RiskSeverity,
)
from packages.contracts.workbench_contracts.models import (
    MedicalWritingFinalFreezeReadiness,
    MedicalWritingSectionFreezeGap,
    MedicalWritingSectionFreezeRecord,
    MedicalWritingSectionFreezeRequest,
    MedicalWritingSectionFreezeResult,
)

from .medical_writing_document import MedicalWritingDocumentService
from .ai_task_runner import validate_medical_writing_candidate_citations
from .medical_writing_legacy_reference_index import parse_legacy_reference_marker
from .medical_writing_content_quality import MedicalWritingContentQualityDetector
from .medical_writing_protected_tokens import (
    check_protected_tokens,
    protected_token_issue_dicts,
)
from .medical_writing_instrument_appendix import (
    MedicalWritingInstrumentAppendixError,
    validate_instrument_appendix_block,
)
from .medical_writing_tables import MedicalWritingTableService
from .sqlite_runtime_store import (
    IdempotencyConflictError,
    RuntimeStoreError,
    SqliteRuntimeStore,
    StaleRuntimeStateError,
)


class MedicalWritingRuntimeRepository:
    _LEGACY_FROZEN_STATES = {
        ApprovalState.MEDICALLY_APPROVED,
        ApprovalState.LOCKED_FOR_SUBMISSION,
    }
    _RICH_TEXT_PARAGRAPH_ATTRS = {
        "stylePreset",
        "textAlign",
        "lineHeight",
        "spacingBeforePt",
        "spacingAfterPt",
        "leftIndentChars",
        "rightIndentChars",
        "firstLineIndentChars",
    }
    _RICH_TEXT_STYLE_PRESETS = {
        "heading_1",
        "heading_2",
        "heading_3",
        "heading_4",
        "body",
        "note",
    }
    _RICH_TEXT_MARKS = {
        "bold",
        "italic",
        "underline",
        "superscript",
        "subscript",
        "textStyle",
        "highlight",
        "citation",
        "crossReference",
    }

    def __init__(
        self,
        document_service: MedicalWritingDocumentService,
        runtime_store: SqliteRuntimeStore,
        study_consistency_service: Any = None,
    ):
        self.document_service = document_service
        self.runtime_store = runtime_store
        self.study_consistency_service = study_consistency_service
        self.content_quality_detector = MedicalWritingContentQualityDetector()

    def project(self, project_id: str) -> ProtocolDocument:
        return self._with_effective_document_binding(
            self.document_service.document_session(project_id)
        )

    def _author_semantics_view(
        self,
        working_copy: MedicalWritingWorkingCopy,
    ) -> MedicalWritingWorkingCopy:
        """Map legacy same-role approval states onto author freeze semantics.

        The mapping is deliberately lazy: immutable legacy payloads and snapshots stay
        byte-for-byte auditable, while every current medical-writing read exposes the
        author workflow and no longer advertises a second medical approval.
        """

        updates: dict[str, Any] = {"approval_state": ApprovalState.AI_DRAFT}
        explicit_snapshot_id = str(working_copy.frozen_snapshot_id or "").strip()
        legacy_snapshot_id = str(working_copy.approved_snapshot_id or "").strip()
        if (
            not explicit_snapshot_id
            and working_copy.approval_state in self._LEGACY_FROZEN_STATES
            and working_copy.approved_revision is not None
            and legacy_snapshot_id
        ):
            updates.update(
                {
                    "freeze_status": "frozen",
                    "frozen_revision": working_copy.approved_revision,
                    "frozen_snapshot_id": legacy_snapshot_id,
                    "frozen_by": working_copy.updated_by or "legacy_medical_author",
                    "frozen_at": working_copy.updated_at,
                    "frozen_study_definition_id": (
                        working_copy.source_study_definition_id
                    ),
                    "frozen_study_definition_revision": (
                        working_copy.source_study_definition_revision
                    ),
                    "frozen_study_definition_sha256": (
                        working_copy.source_study_definition_sha256
                    ),
                }
            )

        candidate = working_copy.model_copy(update=updates, deep=True)
        has_freeze = bool(candidate.frozen_snapshot_id) and candidate.frozen_revision is not None
        if not has_freeze:
            return candidate.model_copy(update={"freeze_status": "editable"}, deep=True)
        binding_matches = (
            candidate.frozen_study_definition_id
            == candidate.source_study_definition_id
            and candidate.frozen_study_definition_revision
            == candidate.source_study_definition_revision
            and candidate.frozen_study_definition_sha256
            == candidate.source_study_definition_sha256
        )
        current = (
            candidate.frozen_revision == candidate.revision
            and binding_matches
            and candidate.content_authority_state == "active_authoritative"
        )
        return candidate.model_copy(
            update={"freeze_status": "frozen" if current else "invalidated"},
            deep=True,
        )

    @staticmethod
    def _clear_author_freeze_fields() -> dict[str, Any]:
        return {
            "freeze_status": "editable",
            "frozen_revision": None,
            "frozen_snapshot_id": None,
            "frozen_by": "",
            "frozen_at": None,
            "frozen_study_definition_id": "",
            "frozen_study_definition_revision": None,
            "frozen_study_definition_sha256": "",
        }

    def document_session(self, project_id: str) -> ProtocolDocument:
        document = self.project(project_id)
        working_copies = {
            working_copy.section_id: working_copy
            for working_copy in (
                self.runtime_store.medical_writing_working_copies_for_document(
                    project_id,
                    document.document_id,
                )
            )
        }
        sections: List[Any] = []
        for section in document.sections:
            if section.section_id not in working_copies:
                sections.append(section.model_copy(deep=True))
                continue
            # The author-facing approval state is always AI_DRAFT, including
            # frozen legacy and quarantined working-copy revisions. Full
            # StudyDefinition binding checks remain mandatory on section reads,
            # writes, freezes, and export; this list projection only overlays
            # the author workflow state and must not repeat that gate per section.
            sections.append(
                section.model_copy(
                    update={
                        "approval_state": ApprovalState.AI_DRAFT,
                    },
                    deep=True,
                )
            )
        return document.model_copy(update={"sections": sections}, deep=True)

    def protocol(self, project_id: str) -> ProtocolDocument:
        return self._with_effective_document_binding(
            self.document_service.document_for_revision(project_id)
        )

    def assemble_document_for_export(
        self,
        project_id: str,
        mode: str,
    ) -> ProtocolDocument:
        """Assemble one complete document without mutating the source protocol.

        Draft previews prefer the latest persisted section working copy. Final
        exports are rebuilt only from the immutable author-freeze snapshot referenced
        by each applicable section's current working-copy record.
        """

        if mode not in {"draft_preview", "approved_final"}:
            raise ValueError(
                "unsupported medical writing export mode; expected draft_preview or approved_final"
            )
        self._require_authoritative_document_binding(project_id)
        if mode == "approved_final" and self.study_consistency_service is not None:
            self.study_consistency_service.require_approved_export(project_id)
        source_document = self.protocol(project_id)
        if mode == "approved_final":
            readiness = self.final_freeze_readiness(project_id)
            if not readiness.ready:
                raise RuntimeStoreError(
                    "final export requires every applicable section to be frozen at "
                    "its current revision and StudyDefinition binding: "
                    + json.dumps(
                        [gap.model_dump(mode="json") for gap in readiness.gaps],
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
        assembled_sections = []
        for source_section in source_document.sections:
            current = self.working_copy(project_id, source_section.section_id)
            if current.content_authority_state != "active_authoritative":
                raise RuntimeStoreError(
                    "draft/final export blocked by a quarantined StudyDefinition binding: "
                    f"{source_section.section_id}"
                )
            if mode == "draft_preview":
                if current.revision < 1:
                    assembled_sections.append(source_section.model_copy(deep=True))
                    continue
                self._validate_export_working_copy_identity(
                    source_document,
                    source_section.section_id,
                    current,
                )
                self._validate_working_copy_blocks(
                    source_section.content_blocks,
                    current.content_blocks,
                    existing_blocks=current.content_blocks,
                )
                assembled_sections.append(
                    source_section.model_copy(
                        update={
                            "content_blocks": current.content_blocks,
                            "approval_state": current.approval_state,
                        },
                        deep=True,
                    )
                )
                continue

            if (
                source_section.applicability_status == "not_applicable"
                and source_section.applicability_render_action == "omit"
            ):
                assembled_sections.append(source_section.model_copy(deep=True))
                continue
            snapshot = self._frozen_working_copy_snapshot(
                project_id,
                source_document,
                source_section.section_id,
                current,
            )
            snapshot = snapshot.model_copy(
                update={
                    "content_blocks": self._hydrate_legacy_working_copy_formatting(
                        source_section.content_blocks,
                        snapshot.content_blocks,
                    )
                },
                deep=True,
            )
            self._validate_working_copy_blocks(
                source_section.content_blocks,
                snapshot.content_blocks,
                existing_blocks=snapshot.content_blocks,
            )
            assembled_sections.append(
                source_section.model_copy(
                    update={
                        "content_blocks": snapshot.content_blocks,
                        "approval_state": snapshot.approval_state,
                    },
                    deep=True,
                )
            )

        assembled_document = source_document.model_copy(
            update={
                "sections": assembled_sections,
                "status": (
                    "author_frozen_final"
                    if mode == "approved_final"
                    else "draft_preview"
                ),
            },
            deep=True,
        )
        substantive_gaps = self._substantive_body_gaps(assembled_document)
        if substantive_gaps:
            raise RuntimeStoreError(
                "医学写作 Word 导出已阻断：仍有适用正文章节缺少实质正文。请先完成全文初稿候选审核与采纳；"
                + json.dumps(substantive_gaps, ensure_ascii=False, sort_keys=True)
            )
        if mode == "approved_final":
            self._require_content_quality_clear(assembled_document)
        return assembled_document

    @staticmethod
    def _substantive_body_gaps(document: ProtocolDocument) -> list[dict[str, str]]:
        """Return applicable ordinary sections whose assembled body is blank.

        Front matter, controlled tables, glossary and references are governed by
        their own structured contracts.  Ordinary protocol sections must have
        real prose before either a draft preview or a final Word can be called
        complete; this prevents a heading-only DOCX from becoming a false
        green end-to-end result.
        """
        placeholder_re = re.compile(
            r"^(?:待补充|待确认|待定|TBD|TODO|不适用|无适用内容|由方案规定|见方案规定)[。；：!！,，\s]*$",
            re.IGNORECASE,
        )

        def block_text(block: Mapping[str, Any]) -> str:
            values: list[str] = []
            raw = str(block.get("text") or "").strip()
            if raw:
                values.append(raw)
            structured = block.get("structured_table")
            if isinstance(structured, dict):
                for row in structured.get("rows") or []:
                    if not isinstance(row, dict):
                        continue
                    for cell in row.get("cells") or []:
                        if isinstance(cell, dict):
                            value = str(cell.get("text") or "").strip()
                            if value:
                                values.append(value)
            return "\n".join(values).strip()

        gaps: list[dict[str, str]] = []
        for section in document.sections:
            if (
                section.applicability_status == "not_applicable"
                or section.applicability_render_action == "omit"
                or section.node_kind not in {"section", "appendix"}
            ):
                continue
            # A source-backed protocol already owns its complete body in the
            # immutable DOCX source.  The normalized section projection may
            # expose only headings/figures/tables, so requiring 80 characters
            # here would incorrectly block a lossless source export.  The
            # generated greenfield/template paths use different source_kind
            # values and remain subject to this substantive-body gate.
            if any(
                str(block.get("source_kind") or "") == "original_protocol_docx"
                for block in section.content_blocks
            ):
                continue
            body = "\n".join(
                block_text(block)
                for block in section.content_blocks
                if block.get("block_type") != "heading"
            ).strip()
            # Keep this repository layer independent from the full-draft module;
            # 80 characters is the shared substantive threshold.
            if len(body) < 80 or placeholder_re.fullmatch(body):
                gaps.append(
                    {
                        "section_id": str(section.section_id),
                        "section_number": str(section.section_number or ""),
                        "heading": str(section.heading or ""),
                        "reason": "substantive_body_missing",
                    }
                )
        return gaps

    def content_quality(
        self,
        project_id: str,
        section_id: str = "",
    ) -> MedicalWritingContentQualityResult:
        document = self.protocol(project_id)
        findings: List[MedicalWritingContentFinding] = []
        for section in document.sections:
            if section_id and section.section_id != section_id:
                continue
            current = self.working_copy(project_id, section.section_id)
            content_blocks = (
                current.content_blocks if current.revision >= 1 else section.content_blocks
            )
            findings.extend(
                self.content_quality_detector.scan_section(
                    document,
                    section,
                    content_blocks,
                    content_revision=current.revision,
                )
            )
        if section_id and not any(
            section.section_id == section_id for section in document.sections
        ):
            raise KeyError(f"medical writing section not found: {section_id}")
        merged = [self._merge_content_disposition(finding) for finding in findings]
        return self._content_quality_result(document, merged, section_id=section_id)

    def apply_content_disposition(
        self,
        project_id: str,
        finding_id: str,
        request: MedicalWritingContentDispositionRequest,
        section_id: str = "",
    ) -> MedicalWritingContentFinding:
        reason = request.reason.strip()
        if len(reason) < 10:
            raise ValueError("content disposition reason must contain at least 10 characters")
        current_result = self.content_quality(project_id, section_id)
        finding = next(
            (item for item in current_result.findings if item.finding_id == finding_id),
            None,
        )
        if finding is None:
            raise KeyError(f"medical writing content finding not found: {finding_id}")
        if (
            request.expected_content_fingerprint != finding.content_fingerprint
            or request.expected_content_revision != finding.content_revision
        ):
            self.runtime_store.record_rejection(
                project_id,
                event_type="stale_write_rejected",
                operation="medical_writing_content_disposition",
                actor=request.actor,
                detail={
                    "finding_id": finding_id,
                    "expected_content_fingerprint": request.expected_content_fingerprint,
                    "actual_content_fingerprint": finding.content_fingerprint,
                    "expected_content_revision": request.expected_content_revision,
                    "actual_content_revision": finding.content_revision,
                },
            )
            raise StaleRuntimeStateError(
                "medical writing content changed after the finding was reviewed"
            )
        if request.expected_disposition_revision != finding.disposition_revision:
            self.runtime_store.record_rejection(
                project_id,
                event_type="stale_write_rejected",
                operation="medical_writing_content_disposition",
                actor=request.actor,
                detail={
                    "finding_id": finding_id,
                    "expected_disposition_revision": request.expected_disposition_revision,
                    "actual_disposition_revision": finding.disposition_revision,
                },
            )
            raise StaleRuntimeStateError(
                "medical writing content disposition changed after it was loaded"
            )

        semantic_request = {
            "project_id": project_id,
            "finding_id": finding_id,
            "status": request.status.value,
            "reason": reason,
            "actor": request.actor,
            "content_fingerprint": finding.content_fingerprint,
            "content_revision": finding.content_revision,
            "expected_disposition_revision": finding.disposition_revision,
        }
        request_fingerprint = self._payload_hash(semantic_request)
        token = sha256(
            json.dumps(semantic_request, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        now = datetime.now(timezone.utc)
        record = MedicalWritingContentDispositionRecord(
            record_id=f"mwq_disposition_{token}",
            finding_id=finding.finding_id,
            project_id=finding.project_id,
            document_id=finding.document_id,
            document_version=finding.document_version,
            section_id=finding.section_id,
            source_locator=finding.source_locator,
            rule_code=finding.rule_code,
            detector_version=finding.detector_version,
            content_fingerprint=finding.content_fingerprint,
            content_revision=finding.content_revision,
            previous_status=finding.disposition_status,
            status=request.status,
            revision=finding.disposition_revision + 1,
            reason=reason,
            actor=request.actor,
            created_at=now,
        )
        self.runtime_store.commit_medical_writing_content_disposition(
            record,
            expected_revision=finding.disposition_revision,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        refreshed = self.content_quality(project_id, finding.section_id)
        return next(item for item in refreshed.findings if item.finding_id == finding_id)

    def _content_quality_for_document(
        self,
        document: ProtocolDocument,
    ) -> MedicalWritingContentQualityResult:
        findings = [
            self._merge_content_disposition(finding)
            for finding in self.content_quality_detector.scan_document(document)
        ]
        return self._content_quality_result(document, findings)

    def _merge_content_disposition(
        self,
        finding: MedicalWritingContentFinding,
    ) -> MedicalWritingContentFinding:
        record = self.runtime_store.current_medical_writing_content_disposition(
            finding.project_id,
            finding.finding_id,
        )
        if record is None:
            return finding
        if (
            record.document_id != finding.document_id
            or record.section_id != finding.section_id
            or record.detector_version != finding.detector_version
            or record.content_fingerprint != finding.content_fingerprint
        ):
            return finding.model_copy(
                update={"disposition_revision": record.revision},
                deep=True,
            )
        return finding.model_copy(
            update={
                "disposition_status": record.status,
                "disposition_revision": record.revision,
                "disposition_reason": record.reason,
                "disposition_actor": record.actor,
                "disposition_at": record.created_at,
            },
            deep=True,
        )

    @staticmethod
    def _content_quality_result(
        document: ProtocolDocument,
        findings: List[MedicalWritingContentFinding],
        *,
        section_id: str = "",
    ) -> MedicalWritingContentQualityResult:
        open_count = sum(
            item.disposition_status == MedicalWritingContentDispositionStatus.OPEN
            for item in findings
        )
        correction_count = sum(
            item.disposition_status
            == MedicalWritingContentDispositionStatus.CORRECTION_REQUIRED
            for item in findings
        )
        confirmed_count = sum(
            item.disposition_status
            == MedicalWritingContentDispositionStatus.CONFIRMED_SOURCE_TEXT
            for item in findings
        )
        blocking_count = sum(
            item.approval_blocking
            and item.disposition_status
            in {
                MedicalWritingContentDispositionStatus.OPEN,
                MedicalWritingContentDispositionStatus.CORRECTION_REQUIRED,
            }
            for item in findings
        )
        return MedicalWritingContentQualityResult(
            project_id=document.project_id,
            document_id=document.document_id,
            document_version=document.version,
            section_id=section_id,
            finding_count=len(findings),
            open_count=open_count,
            correction_required_count=correction_count,
            confirmed_count=confirmed_count,
            approval_blocking_count=blocking_count,
            findings=findings,
        )

    def _require_content_quality_clear(self, document: ProtocolDocument) -> None:
        result = self._content_quality_for_document(document)
        blocking = [
            finding
            for finding in result.findings
            if finding.approval_blocking
            and finding.disposition_status
            in {
                MedicalWritingContentDispositionStatus.OPEN,
                MedicalWritingContentDispositionStatus.CORRECTION_REQUIRED,
            }
        ]
        if blocking:
            first = blocking[0]
            raise RuntimeStoreError(
                "frozen final export blocked by medical writing content quality: "
                f"{first.source_text} ({first.source_locator or first.section_heading})"
            )

    def _frozen_working_copy_snapshot(
        self,
        project_id: str,
        document: ProtocolDocument,
        section_id: str,
        current: MedicalWritingWorkingCopy,
    ) -> MedicalWritingWorkingCopy:
        self._validate_export_working_copy_identity(document, section_id, current)
        current_binding_failure = self._working_copy_binding_failure(
            project_id, document, current
        )
        if current_binding_failure:
            raise RuntimeStoreError(
                "frozen final export current revision binding is invalid: "
                + current_binding_failure
            )
        if current.revision < 1:
            raise RuntimeStoreError(
                f"frozen final export requires a saved working copy for section: {section_id}"
            )
        effective = self._author_semantics_view(current)
        if effective.freeze_status != "frozen":
            raise RuntimeStoreError(
                f"frozen final export requires the current section version to be frozen: {section_id}"
            )
        snapshot_id = str(effective.frozen_snapshot_id or "").strip()
        if not snapshot_id or effective.frozen_revision is None:
            raise RuntimeStoreError(
                f"frozen final export requires an immutable freeze snapshot for section: {section_id}"
            )
        matches = [
            item
            for item in self.runtime_store.medical_writing_working_copy_snapshots(
                project_id,
                current.working_copy_id,
            )
            if item["snapshot_id"] == snapshot_id
        ]
        if len(matches) != 1:
            raise RuntimeStoreError(
                f"freeze snapshot is unavailable or ambiguous for section: {section_id}"
            )
        record = matches[0]
        if record["snapshot_type"] not in {"author_freeze", "approval"}:
            raise RuntimeStoreError(
                f"freeze snapshot has an invalid snapshot type for section: {section_id}"
            )
        snapshot = self._author_semantics_view(record["working_copy"])
        self._validate_export_working_copy_identity(document, section_id, snapshot)
        snapshot_binding_failure = self._working_copy_binding_failure(
            project_id, document, snapshot
        )
        if snapshot_binding_failure:
            raise RuntimeStoreError(
                "frozen final export snapshot binding is invalid: "
                + snapshot_binding_failure
            )
        if (
            snapshot.freeze_status != "frozen"
            or snapshot.frozen_snapshot_id != snapshot_id
            or snapshot.frozen_revision != snapshot.revision
            or record["revision"] != snapshot.revision
            or effective.frozen_revision != snapshot.revision
            or snapshot.source_study_definition_id
            != effective.source_study_definition_id
            or snapshot.source_study_definition_revision
            != effective.source_study_definition_revision
            or snapshot.source_study_definition_sha256
            != effective.source_study_definition_sha256
            or self._payload_hash(snapshot.content_blocks)
            != self._payload_hash(effective.content_blocks)
        ):
            raise RuntimeStoreError(
                f"freeze snapshot state is inconsistent for section: {section_id}"
            )
        return snapshot

    # Kept as a private compatibility alias for older backend callers. Its behavior
    # is now author-freeze based and never creates or requires a medical approval.
    def _approved_working_copy_snapshot(
        self,
        project_id: str,
        document: ProtocolDocument,
        section_id: str,
        current: MedicalWritingWorkingCopy,
    ) -> MedicalWritingWorkingCopy:
        return self._frozen_working_copy_snapshot(
            project_id, document, section_id, current
        )

    def final_freeze_readiness(
        self, project_id: str
    ) -> MedicalWritingFinalFreezeReadiness:
        self._require_authoritative_document_binding(project_id)
        document = self.protocol(project_id)
        gaps: list[MedicalWritingSectionFreezeGap] = []
        required_count = 0
        frozen_count = 0
        omitted_count = 0
        for section in document.sections:
            if (
                section.applicability_status == "not_applicable"
                and section.applicability_render_action == "omit"
            ):
                omitted_count += 1
                continue
            required_count += 1
            current = self.working_copy(project_id, section.section_id)
            if section.applicability_status in {"unknown", "deferred"}:
                gaps.append(
                    MedicalWritingSectionFreezeGap(
                        section_id=section.section_id,
                        section_heading=section.heading,
                        reason_code="applicability_unresolved",
                        message="章节适用性尚未最终确定，不能进入终稿冻结集合。",
                        current_revision=current.revision,
                        frozen_revision=current.frozen_revision,
                    )
                )
                continue
            if current.content_authority_state != "active_authoritative":
                gaps.append(
                    MedicalWritingSectionFreezeGap(
                        section_id=section.section_id,
                        section_heading=section.heading,
                        reason_code="working_copy_quarantined",
                        message=current.quarantine_reason
                        or "章节正文与当前StudyDefinition绑定不一致。",
                        current_revision=current.revision,
                        frozen_revision=current.frozen_revision,
                    )
                )
                continue
            if current.revision < 1:
                gaps.append(
                    MedicalWritingSectionFreezeGap(
                        section_id=section.section_id,
                        section_heading=section.heading,
                        reason_code="working_copy_not_saved",
                        message="章节尚未形成已保存的工作副本版本。",
                        current_revision=current.revision,
                    )
                )
                continue
            effective = self._author_semantics_view(current)
            if effective.freeze_status == "editable":
                gaps.append(
                    MedicalWritingSectionFreezeGap(
                        section_id=section.section_id,
                        section_heading=section.heading,
                        reason_code="section_not_frozen",
                        message="作者尚未确认并冻结当前章节版本。",
                        current_revision=current.revision,
                    )
                )
                continue
            if effective.freeze_status == "invalidated":
                gaps.append(
                    MedicalWritingSectionFreezeGap(
                        section_id=section.section_id,
                        section_heading=section.heading,
                        reason_code="freeze_invalidated",
                        message=(
                            "冻结后章节版本或StudyDefinition绑定已变化，需重新确认当前版本。"
                        ),
                        current_revision=current.revision,
                        frozen_revision=effective.frozen_revision,
                    )
                )
                continue
            try:
                self._frozen_working_copy_snapshot(
                    project_id, document, section.section_id, effective
                )
            except RuntimeStoreError as exc:
                message = str(exc)
                reason_code = (
                    "freeze_snapshot_missing"
                    if "unavailable or ambiguous" in message
                    else "freeze_snapshot_inconsistent"
                )
                gaps.append(
                    MedicalWritingSectionFreezeGap(
                        section_id=section.section_id,
                        section_heading=section.heading,
                        reason_code=reason_code,
                        message=message,
                        current_revision=current.revision,
                        frozen_revision=effective.frozen_revision,
                    )
                )
                continue
            frozen_count += 1
        return MedicalWritingFinalFreezeReadiness(
            project_id=project_id,
            document_id=document.document_id,
            ready=not gaps,
            required_section_count=required_count,
            current_frozen_section_count=frozen_count,
            omitted_not_applicable_section_count=omitted_count,
            gaps=gaps,
        )

    @staticmethod
    def _validate_export_working_copy_identity(
        document: ProtocolDocument,
        section_id: str,
        working_copy: MedicalWritingWorkingCopy,
    ) -> None:
        if (
            working_copy.project_id != document.project_id
            or working_copy.document_id != document.document_id
            or working_copy.section_id != section_id
            or working_copy.source_document_version != document.version
        ):
            raise RuntimeStoreError(
                f"medical writing working copy identity does not match section: {section_id}"
            )

    def revision_threads(self, project_id: str) -> List[RevisionThread]:
        self.project(project_id)
        return self.runtime_store.medical_writing_revision_threads(project_id)

    def revision_thread(self, project_id: str, thread_id: str) -> RevisionThread:
        self.project(project_id)
        return self.runtime_store.medical_writing_revision_thread(project_id, thread_id)

    def project_reference_ids(self, project_id: str) -> set[str]:
        database_path = self.runtime_store.db_path.parent / "medical_writing_literature.sqlite3"
        if not database_path.is_file():
            return set()
        try:
            with sqlite3.connect(database_path) as connection:
                rows = connection.execute(
                    """
                    SELECT reference_id
                    FROM medical_writing_literature_references
                    WHERE tenant_id = ? AND project_id = ?
                    """,
                    ("kangzhe_local", project_id),
                ).fetchall()
        except sqlite3.Error:
            return set()
        return {str(row[0]) for row in rows}

    def working_copy(
        self,
        project_id: str,
        section_id: str,
    ) -> MedicalWritingWorkingCopy:
        document = self.project(project_id)
        section = self.document_service.section(project_id, section_id)
        try:
            stored = self.runtime_store.medical_writing_working_copy(
                project_id,
                document.document_id,
                section_id,
            )
            if self.study_consistency_service is not None:
                quarantine_reason = self._working_copy_binding_failure(
                    project_id, document, stored
                )
                if quarantine_reason:
                    return self._baseline_working_copy(
                        document,
                        section,
                        revision=stored.revision,
                        created_by=stored.created_by,
                        updated_by=stored.updated_by,
                        created_at=stored.created_at,
                        updated_at=stored.updated_at,
                        authority_state="historical_quarantined",
                        quarantined_revision=stored.revision,
                        quarantine_reason=quarantine_reason,
                    )
            return self._author_semantics_view(
                stored.model_copy(
                    update={
                        "content_blocks": self._hydrate_legacy_working_copy_formatting(
                            section.content_blocks,
                            stored.content_blocks,
                        ),
                        "content_authority_state": "active_authoritative",
                        "quarantined_revision": None,
                        "quarantine_reason": "",
                    },
                    deep=True,
                )
            )
        except KeyError:
            now = datetime.now(timezone.utc)
            quarantine_reason = ""
            authority_state = "active_authoritative"
            if self.study_consistency_service is not None:
                try:
                    self._require_authoritative_document_binding(project_id)
                except RuntimeStoreError as exc:
                    authority_state = "historical_quarantined"
                    quarantine_reason = str(exc)
            return self._baseline_working_copy(
                document,
                section,
                revision=0,
                created_by="source_import",
                updated_by="source_import",
                created_at=now,
                updated_at=now,
                authority_state=authority_state,
                quarantined_revision=0 if quarantine_reason else None,
                quarantine_reason=quarantine_reason,
            )

    def save_working_copy(
        self,
        project_id: str,
        section_id: str,
        request: MedicalWritingWorkingCopySaveRequest,
        *,
        authorized_generated_blocks: Optional[Mapping[str, dict]] = None,
        authorized_removed_appendix_block_ids: Optional[set[str]] = None,
    ) -> MedicalWritingWorkingCopy:
        document = self.project(project_id)
        section = self.document_service.section(project_id, section_id)
        if request.document_id != document.document_id or section.document_id != document.document_id:
            raise ValueError("working copy document does not match the canonical project document")
        request = request.model_copy(
            update={
                "content_blocks": self._hydrate_legacy_working_copy_formatting(
                    section.content_blocks,
                    request.content_blocks,
                )
            },
            deep=True,
        )
        self._require_authoritative_document_binding(project_id)
        current = self.working_copy(project_id, section_id)
        if current.content_authority_state != "active_authoritative":
            raise RuntimeStoreError(
                "normal save cannot bind or launder quarantined working-copy content; "
                "use accept-and-bind or revert-to-authoritative-baseline"
            )
        self._validate_working_copy_blocks(
            section.content_blocks,
            request.content_blocks,
            existing_blocks=current.content_blocks,
            authorized_generated_blocks=authorized_generated_blocks,
            authorized_removed_appendix_block_ids=authorized_removed_appendix_block_ids,
        )
        semantic_request = {
            "project_id": project_id,
            "document_id": document.document_id,
            "section_id": section_id,
            "expected_revision": request.expected_revision,
            "content_blocks": request.content_blocks,
            "actor": request.actor,
        }
        request_fingerprint = self._payload_hash(semantic_request)
        idempotency_key = request.idempotency_key.strip() or f"auto:{uuid4().hex}"
        if request.idempotency_key.strip():
            replay = self.runtime_store.lookup_idempotent_replay(
                project_id,
                "medical_writing_working_copy_save",
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                return self.runtime_store.medical_writing_working_copy(
                    project_id,
                    document.document_id,
                    section_id,
                )
        if current.revision != request.expected_revision:
            self.runtime_store.record_rejection(
                project_id,
                event_type="stale_write_rejected",
                operation="medical_writing_working_copy_save",
                actor=request.actor,
                detail={
                    "working_copy_id": current.working_copy_id,
                    "document_id": document.document_id,
                    "section_id": section_id,
                    "expected_revision": request.expected_revision,
                    "actual_revision": current.revision,
                },
            )
            raise StaleRuntimeStateError(
                f"stale medical writing working copy revision: expected={request.expected_revision}, actual={current.revision}"
            )

        now = datetime.now(timezone.utc)
        definition_id, definition_revision, definition_sha256 = self._current_binding(
            project_id
        )
        token = sha256(
            f"{project_id}:{document.document_id}:{section_id}:{idempotency_key}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        working_copy = MedicalWritingWorkingCopy(
            working_copy_id=current.working_copy_id,
            project_id=project_id,
            document_id=document.document_id,
            section_id=section_id,
            source_document_version=document.version,
            revision=request.expected_revision + 1,
            content_blocks=request.content_blocks,
            approval_state=ApprovalState.AI_DRAFT,
            approved_revision=None,
            approved_snapshot_id=None,
            freeze_status="editable",
            frozen_revision=None,
            frozen_snapshot_id=None,
            frozen_by="",
            frozen_at=None,
            frozen_study_definition_id="",
            frozen_study_definition_revision=None,
            frozen_study_definition_sha256="",
            source_study_definition_id=definition_id,
            source_study_definition_revision=definition_revision,
            source_study_definition_sha256=definition_sha256,
            content_authority_state="active_authoritative",
            quarantined_revision=None,
            quarantine_reason="",
            study_definition_reconciliation_required=(
                current.study_definition_reconciliation_required
            ),
            study_definition_reconciliation_reason=(
                current.study_definition_reconciliation_reason
            ),
            applied_revision_thread_ids=list(current.applied_revision_thread_ids),
            created_by=current.created_by if current.revision else request.actor,
            updated_by=request.actor,
            created_at=current.created_at if current.revision else now,
            updated_at=now,
        )
        audit_event = AuditEvent(
            audit_id=f"audit_working_copy_{token}",
            project_id=project_id,
            actor=request.actor,
            action="medical_writing_working_copy_saved",
            target_type="medical_writing_working_copy",
            target_id=working_copy.working_copy_id,
            detail={
                "document_id": document.document_id,
                "section_id": section_id,
                "previous_revision": request.expected_revision,
                "new_revision": working_copy.revision,
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        result = self.runtime_store.commit_medical_writing_working_copy_save(
            working_copy,
            audit_event,
            expected_revision=request.expected_revision,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if result.replayed:
            return self.runtime_store.medical_writing_working_copy(
                project_id,
                document.document_id,
                section_id,
            )
        return working_copy

    def accept_and_bind_working_copy(
        self,
        project_id: str,
        section_id: str,
        request: MedicalWritingWorkingCopyBindingRecoveryRequest,
    ) -> MedicalWritingWorkingCopyBindingRecoveryResult:
        return self._recover_working_copy_binding(
            project_id,
            section_id,
            request,
            operation="accept_and_bind",
        )

    def revert_to_authoritative_baseline(
        self,
        project_id: str,
        section_id: str,
        request: MedicalWritingWorkingCopyBindingRecoveryRequest,
    ) -> MedicalWritingWorkingCopyBindingRecoveryResult:
        return self._recover_working_copy_binding(
            project_id,
            section_id,
            request,
            operation="revert_to_authoritative_baseline",
        )

    def historical_quarantined_working_copy(
        self,
        project_id: str,
        section_id: str,
    ) -> MedicalWritingWorkingCopy:
        document = self.project(project_id)
        section = self.document_service.section(project_id, section_id)
        try:
            stored = self.runtime_store.medical_writing_working_copy(
                project_id, document.document_id, section_id
            )
        except KeyError:
            current = self.working_copy(project_id, section_id)
            if current.content_authority_state != "historical_quarantined":
                raise KeyError(f"no quarantined working copy: {project_id}/{section_id}")
            return current
        reason = self._working_copy_binding_failure(project_id, document, stored)
        if not reason:
            snapshots = self.runtime_store.medical_writing_working_copy_snapshots(
                project_id, stored.working_copy_id
            )
            historical = [
                item
                for item in snapshots
                if item["snapshot_type"] == "historical_quarantine"
            ]
            if not historical:
                raise KeyError(
                    f"no quarantined working copy: {project_id}/{section_id}"
                )
            quarantined = historical[-1]["working_copy"]
            return quarantined.model_copy(
                update={
                    "content_blocks": self._hydrate_legacy_working_copy_formatting(
                        section.content_blocks, quarantined.content_blocks
                    ),
                    "content_authority_state": "historical_quarantined",
                    "quarantined_revision": quarantined.revision,
                },
                deep=True,
            )
        return stored.model_copy(
            update={
                "content_blocks": self._hydrate_legacy_working_copy_formatting(
                    section.content_blocks, stored.content_blocks
                ),
                "content_authority_state": "historical_quarantined",
                "quarantined_revision": stored.revision,
                "quarantine_reason": reason,
            },
            deep=True,
        )

    def _recover_working_copy_binding(
        self,
        project_id: str,
        section_id: str,
        request: MedicalWritingWorkingCopyBindingRecoveryRequest,
        *,
        operation: str,
    ) -> MedicalWritingWorkingCopyBindingRecoveryResult:
        if operation not in {"accept_and_bind", "revert_to_authoritative_baseline"}:
            raise ValueError("unsupported working-copy binding recovery operation")
        source_document = self.document_service.document_for_revision(project_id)
        section = self.document_service.section(project_id, section_id)
        if request.document_id != source_document.document_id:
            raise RuntimeStoreError("binding recovery document does not match the project source")
        if source_document.source_study_definition_id:
            raise RuntimeStoreError(
                "intrinsically bound greenfield documents must use StudyDefinition rebind"
            )
        definition_id, definition_revision, definition_sha256 = self._current_binding(
            project_id
        )
        semantic_request = {
            "project_id": project_id,
            "document_id": source_document.document_id,
            "section_id": section_id,
            "expected_working_copy_revision": request.expected_working_copy_revision,
            "operation": operation,
            "reason": request.reason,
            "acknowledge_binding": request.acknowledge_binding,
            "study_definition_binding": {
                "definition_id": definition_id,
                "definition_revision": definition_revision,
                "definition_sha256": definition_sha256,
            },
        }
        request_fingerprint = self._payload_hash(semantic_request)
        operation_key = f"medical_writing_working_copy_{operation}"
        replay = self.runtime_store.lookup_idempotent_replay(
            project_id,
            operation_key,
            request.idempotency_key,
            request_fingerprint,
        )
        token = sha256(
            f"{project_id}:{source_document.document_id}:{section_id}:{operation}:{request.idempotency_key}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        audit_id = f"audit_working_copy_binding_{token}"
        if replay is not None:
            current = self.runtime_store.medical_writing_working_copy(
                project_id, source_document.document_id, section_id
            )
            audit = next(
                event
                for event in self.runtime_store.workflow_audit_events(
                    project_id, "medical_writing_working_copy"
                )
                if event.audit_id == audit_id
            )
            return MedicalWritingWorkingCopyBindingRecoveryResult(
                operation=operation,
                working_copy=current,
                quarantined_snapshot_id=(
                    f"snapshot_{audit_id}_quarantine_r{request.expected_working_copy_revision}"
                    if request.expected_working_copy_revision > 0
                    else ""
                ),
                audit_event=audit,
            )

        try:
            stored = self.runtime_store.medical_writing_working_copy(
                project_id, source_document.document_id, section_id
            )
        except KeyError:
            stored = None
        actual_revision = stored.revision if stored is not None else 0
        if actual_revision != request.expected_working_copy_revision:
            raise StaleRuntimeStateError(
                "stale working-copy binding recovery revision: "
                f"expected={request.expected_working_copy_revision}, actual={actual_revision}"
            )
        if operation == "accept_and_bind" and stored is not None:
            quarantine_reason = self._working_copy_binding_failure(
                project_id,
                self._with_effective_document_binding(source_document),
                stored,
            )
            if not quarantine_reason:
                raise RuntimeStoreError("working copy is already authoritative and current")
            content_blocks = stored.content_blocks
            created_by = stored.created_by
            created_at = stored.created_at
            applied_threads = list(stored.applied_revision_thread_ids)
        else:
            quarantine_reason = (
                self._working_copy_binding_failure(
                    project_id,
                    self._with_effective_document_binding(source_document),
                    stored,
                )
                if stored is not None
                else "unbound imported source baseline"
            )
            content_blocks = section.content_blocks
            created_by = stored.created_by if stored is not None else "source_import"
            created_at = stored.created_at if stored is not None else datetime.now(timezone.utc)
            applied_threads = []

        now = datetime.now(timezone.utc)
        recovered = MedicalWritingWorkingCopy(
            working_copy_id=(
                stored.working_copy_id
                if stored is not None
                else self._working_copy_id(project_id, source_document.document_id, section_id)
            ),
            project_id=project_id,
            document_id=source_document.document_id,
            section_id=section_id,
            source_document_version=source_document.version,
            revision=actual_revision + 1,
            content_blocks=content_blocks,
            approval_state=ApprovalState.AI_DRAFT,
            approved_revision=None,
            approved_snapshot_id=None,
            freeze_status="editable",
            frozen_revision=None,
            frozen_snapshot_id=None,
            frozen_by="",
            frozen_at=None,
            frozen_study_definition_id="",
            frozen_study_definition_revision=None,
            frozen_study_definition_sha256="",
            source_study_definition_id=definition_id,
            source_study_definition_revision=definition_revision,
            source_study_definition_sha256=definition_sha256,
            content_authority_state="active_authoritative",
            quarantined_revision=None,
            quarantine_reason="",
            study_definition_reconciliation_required=False,
            study_definition_reconciliation_reason="",
            applied_revision_thread_ids=applied_threads,
            created_by=created_by,
            updated_by=request.actor,
            created_at=created_at,
            updated_at=now,
        )
        action = (
            "medical_writing_working_copy_accepted_and_bound"
            if operation == "accept_and_bind"
            else "medical_writing_working_copy_reverted_to_authoritative_baseline"
        )
        audit = AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor=request.actor,
            action=action,
            target_type="medical_writing_working_copy",
            target_id=recovered.working_copy_id,
            detail={
                "document_id": source_document.document_id,
                "section_id": section_id,
                "previous_revision": actual_revision,
                "new_revision": recovered.revision,
                "reason": request.reason,
                "quarantine_reason": quarantine_reason,
                "study_definition_binding": {
                    "definition_id": definition_id,
                    "definition_revision": definition_revision,
                    "definition_sha256": definition_sha256,
                },
                "source_preserved": True,
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        commit = self.runtime_store.commit_medical_writing_working_copy_save(
            recovered,
            audit,
            expected_revision=actual_revision,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
            operation=operation_key,
            snapshot_type=operation,
            quarantine_previous=stored is not None,
        )
        if commit.replayed:
            recovered = self.runtime_store.medical_writing_working_copy(
                project_id, source_document.document_id, section_id
            )
        return MedicalWritingWorkingCopyBindingRecoveryResult(
            operation=operation,
            working_copy=recovered,
            quarantined_snapshot_id=(
                f"snapshot_{audit_id}_quarantine_r{actual_revision}"
                if stored is not None
                else ""
            ),
            audit_event=audit,
        )

    def apply_approved_revision_to_working_copy(
        self,
        project_id: str,
        section_id: str,
        thread_id: str,
        request: MedicalWritingRevisionApplyRequest,
    ) -> MedicalWritingRevisionApplyResult:
        thread = self.revision_thread(project_id, thread_id)
        if thread.section_id != section_id:
            raise RuntimeStoreError("revision thread does not belong to the requested section")
        document = self.project(project_id)
        if thread.document_id != document.document_id:
            raise RuntimeStoreError("revision thread document is not the current project document")
        current = self.require_authoritative_revision_thread(
            project_id,
            section_id,
            thread,
            allow_stale_table_anchor=True,
        )
        if thread.status not in {
            "author_selected",
            "medically_approved",
            "accepted_pending_medical_approval",
        }:
            raise RuntimeStoreError(
                "revision candidate has not been selected by the medical author"
            )
        accepted = [item for item in thread.suggestions if item.user_decision == "accepted"]
        if len(accepted) != 1:
            raise RuntimeStoreError("revision thread must contain exactly one accepted suggestion")
        suggestion = accepted[0]
        citation_bindings = self._accepted_revision_citation_bindings(
            project_id,
            thread,
            suggestion,
        )
        if thread.anchor_type == "table_cell":
            if thread.table_cell_anchor is None:
                raise RuntimeStoreError("table-cell revision thread has no application-safe anchor")
            expected_anchor_path = json.dumps(
                {
                    "block_id": thread.table_cell_anchor.block_id,
                    "table_id": thread.table_cell_anchor.table_id,
                    "row_id": thread.table_cell_anchor.row_id,
                    "column_id": thread.table_cell_anchor.column_id,
                    "cell_id": thread.table_cell_anchor.cell_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if thread.anchor_path != expected_anchor_path:
                raise RuntimeStoreError("table-cell revision anchor is not application-safe")
        elif not thread.anchor_path or (
            thread.source_locator and thread.source_locator != thread.anchor_path
        ):
            raise RuntimeStoreError("revision thread source locator is not application-safe")

        legacy_semantic_request = {
            "project_id": project_id,
            "document_id": document.document_id,
            "section_id": section_id,
            "thread_id": thread_id,
            "suggestion_id": suggestion.suggestion_id,
            "expected_working_copy_revision": request.expected_working_copy_revision,
            "actor": request.actor,
            "citation_bindings": citation_bindings,
        }
        semantic_request = {
            **legacy_semantic_request,
            "selected_text": thread.selected_text,
            "selected_hash": thread.selected_hash,
        }
        request_fingerprint = self._payload_hash(semantic_request)
        operation = "medical_writing_approved_revision_apply"
        token = sha256(
            f"{project_id}:{thread_id}:{request.idempotency_key}".encode("utf-8")
        ).hexdigest()[:20]
        audit_id = f"audit_revision_apply_{token}"
        replay = self._lookup_idempotent_replay_with_legacy(
            project_id,
            operation,
            request.idempotency_key,
            request_fingerprint,
            legacy_semantic_request,
        )
        if replay is not None:
            current = self.working_copy(project_id, section_id)
            applied_snapshot = next(
                (
                    item
                    for item in self.runtime_store.medical_writing_working_copy_snapshots(
                        project_id,
                        current.working_copy_id,
                    )
                    if item["audit_id"] == audit_id
                    and item["snapshot_type"] == "apply_approved_ai_revision"
                ),
                None,
            )
            if applied_snapshot is None:
                raise RuntimeStoreError("idempotent replay has no immutable application snapshot")
            replayed_working_copy = applied_snapshot["working_copy"]
            if thread_id not in replayed_working_copy.applied_revision_thread_ids:
                raise RuntimeStoreError("idempotent replay has no applied revision linkage")
            audit_event = next(
                event
                for event in self.runtime_store.workflow_audit_events(
                    project_id, "medical_writing_working_copy"
                )
                if event.audit_id == audit_id
            )
            return MedicalWritingRevisionApplyResult(
                thread_id=thread_id,
                suggestion_id=suggestion.suggestion_id,
                working_copy=replayed_working_copy,
                audit_event=audit_event,
            )

        if current.revision != request.expected_working_copy_revision:
            self.runtime_store.record_rejection(
                project_id,
                event_type="stale_write_rejected",
                operation=operation,
                actor=request.actor,
                detail={
                    "thread_id": thread_id,
                    "section_id": section_id,
                    "expected_revision": request.expected_working_copy_revision,
                    "actual_revision": current.revision,
                },
            )
            raise StaleRuntimeStateError(
                "stale medical writing working copy revision: "
                f"expected={request.expected_working_copy_revision}, actual={current.revision}"
            )
        if thread_id in current.applied_revision_thread_ids:
            raise RuntimeStoreError("approved revision thread was already applied")
        protected_token_check = check_protected_tokens(
            thread.selected_text,
            suggestion.proposal_text,
        )
        if protected_token_check.violated:
            raise RuntimeStoreError(
                "protected token mismatch: "
                + "; ".join(
                    item["reason_code"]
                    for item in protected_token_issue_dicts(protected_token_check)
                    if item["reason_code"] != "protected_token_added_unresolved"
                )
            )
        updated_blocks = json.loads(json.dumps(current.content_blocks, ensure_ascii=False))
        table_anchor = thread.table_cell_anchor
        table_apply_detail: dict[str, Any] = {}
        if thread.anchor_type == "table_cell" and table_anchor is not None:
            matching_indexes = [
                index
                for index, block in enumerate(current.content_blocks)
                if str(block.get("block_id", "")) == table_anchor.block_id
                and block.get("block_type") == "table"
            ]
            if len(matching_indexes) != 1:
                raise RuntimeStoreError(
                    "table-cell revision anchor does not identify exactly one content block"
                )
            block_index = matching_indexes[0]
            current_block = current.content_blocks[block_index]
            if self._payload_hash(current_block) != table_anchor.block_hash:
                raise RuntimeStoreError(
                    "approved table-cell target changed after AI revision submission"
                )
            table_service = MedicalWritingTableService()
            table = table_service.from_table_block(current_block)
            if table.table_id != table_anchor.table_id or table.version != table_anchor.table_version:
                raise RuntimeStoreError("approved table-cell target structure is stale")
            self._validate_table_dual_representation(current_block, table)
            try:
                resolved = self._resolve_table_cell(table, table_anchor)
            except ValueError as exc:
                raise RuntimeStoreError(str(exc)) from exc
            if resolved["cell"].text != thread.selected_text:
                raise RuntimeStoreError("approved table-cell text no longer matches the revision target")
            edit_operation: dict[str, Any] = {
                "op": "edit_cell",
                "cell_id": table_anchor.cell_id,
                "text": suggestion.proposal_text,
            }
            if citation_bindings:
                if not isinstance(resolved["cell"].rich_text, dict):
                    raise RuntimeStoreError(
                        "AI citation application requires a rich-text table cell target"
                    )
                replacement_text, replacement_rich_text = (
                    self._replace_in_rich_text_with_citations(
                        resolved["cell"].rich_text,
                        thread.selected_text,
                        suggestion.proposal_text,
                        citation_bindings,
                    )
                )
                edit_operation["text"] = replacement_text
                edit_operation["rich_text"] = replacement_rich_text
            elif isinstance(resolved["cell"].rich_text, dict):
                edit_operation["rich_text"] = self._replace_table_cell_rich_text(
                    resolved["cell"].rich_text,
                    thread.selected_text,
                    suggestion.proposal_text,
                )
            updated_table = table_service.apply_operations(
                table,
                [edit_operation],
                expected_version=table_anchor.table_version,
            )
            updated_blocks[block_index] = table_service.to_table_block(updated_table)
            self._validate_table_dual_representation(
                updated_blocks[block_index],
                updated_table,
            )
            self._assert_cross_reference_marks_preserved(
                current_block,
                updated_blocks[block_index],
            )
            replacement_text = str(edit_operation["text"])
            formatting_preserved = True
            original_text = ""
            if table_anchor.source_kind == "source_linked":
                canonical_section = self.document_service.section(project_id, section_id)
                source_block = next(
                    (
                        block
                        for block in canonical_section.content_blocks
                        if str(block.get("block_id", "")) == table_anchor.block_id
                    ),
                    None,
                )
                original_text, _ = self._table_revision_evidence_selection(
                    canonical_section,
                    source_block,
                    table_anchor.cell_id,
                )
            table_apply_detail = {
                "block_id": table_anchor.block_id,
                "table_id": table_anchor.table_id,
                "row_id": table_anchor.row_id,
                "column_id": table_anchor.column_id,
                "cell_id": table_anchor.cell_id,
                "previous_text": thread.selected_text,
                "new_text": replacement_text,
                "previous_table_version": table_anchor.table_version,
                "new_table_version": updated_table.version,
                "source_kind": table_anchor.source_kind,
                "diverged_from_original": (
                    "not_applicable"
                    if table_anchor.source_kind == "generated"
                    else suggestion.proposal_text != original_text
                ),
            }
        else:
            matching_indexes = [
                index
                for index, block in enumerate(current.content_blocks)
                if str(block.get("source_locator", "")) == thread.anchor_path
            ]
            if len(matching_indexes) != 1:
                raise RuntimeStoreError(
                    "revision source locator does not identify exactly one content block"
                )
            block_index = matching_indexes[0]
            current_block = current.content_blocks[block_index]
            current_text = str(current_block.get("text", ""))
            blank_greenfield_draft = (
                not thread.selected_text
                and self._is_blank_greenfield_draft_block(current_block)
            )
            if blank_greenfield_draft:
                if current_text:
                    raise RuntimeStoreError(
                        "approved blank-section draft target is no longer empty"
                    )
                if not suggestion.proposal_text.strip():
                    raise RuntimeStoreError(
                        "approved blank-section draft proposal must not be empty"
                    )
                replacement_text = suggestion.proposal_text
            else:
                if not thread.selected_text or current_text.count(thread.selected_text) != 1:
                    raise RuntimeStoreError(
                        "approved selected text no longer exists exactly once in the target block"
                    )
                replacement_text = current_text.replace(
                    thread.selected_text,
                    suggestion.proposal_text,
                    1,
                )
            formatting_preserved = "rich_text" in updated_blocks[block_index]
            if citation_bindings:
                if not formatting_preserved:
                    raise RuntimeStoreError(
                        "AI citation application requires a rich-text paragraph target"
                    )
                proposal_display_text, updated_rich_text = (
                    self._replace_in_rich_text_with_citations(
                        updated_blocks[block_index]["rich_text"],
                        "" if blank_greenfield_draft else thread.selected_text,
                        suggestion.proposal_text,
                        citation_bindings,
                    )
                )
                replacement_text = (
                    proposal_display_text
                    if blank_greenfield_draft
                    else current_text.replace(
                        thread.selected_text,
                        proposal_display_text,
                        1,
                    )
                )
                updated_blocks[block_index]["rich_text"] = updated_rich_text
            elif formatting_preserved:
                updated_blocks[block_index]["rich_text"] = (
                    self._replace_table_cell_rich_text(
                        updated_blocks[block_index]["rich_text"],
                        "",
                        suggestion.proposal_text,
                    )
                    if blank_greenfield_draft
                    else self._replace_in_rich_text(
                        updated_blocks[block_index]["rich_text"],
                        thread.selected_text,
                        suggestion.proposal_text,
                    )
                )
                if self._rich_text_plain_text(updated_blocks[block_index]["rich_text"]) != replacement_text:
                    raise RuntimeStoreError("rich text replacement does not match the approved plain text")
            updated_blocks[block_index]["text"] = replacement_text
            self._assert_cross_reference_marks_preserved(
                current_block,
                updated_blocks[block_index],
            )
        canonical_section = self.document_service.section(project_id, section_id)
        self._validate_working_copy_blocks(
            canonical_section.content_blocks,
            updated_blocks,
            existing_blocks=current.content_blocks,
        )
        now = datetime.now(timezone.utc)
        updated = current.model_copy(
            update={
                "revision": current.revision + 1,
                "content_blocks": updated_blocks,
                "approval_state": ApprovalState.AI_DRAFT,
                "approved_revision": None,
                "approved_snapshot_id": None,
                **self._clear_author_freeze_fields(),
                "applied_revision_thread_ids": [
                    *current.applied_revision_thread_ids,
                    thread_id,
                ],
                "created_by": current.created_by if current.revision else request.actor,
                "updated_by": request.actor,
                "created_at": current.created_at if current.revision else now,
                "updated_at": now,
            },
            deep=True,
        )
        audit_event = AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor=request.actor,
            action="medical_writing_revision_applied",
            target_type="medical_writing_working_copy",
            target_id=updated.working_copy_id,
            detail={
                "document_id": document.document_id,
                "section_id": section_id,
                "revision_thread_id": thread_id,
                "suggestion_id": suggestion.suggestion_id,
                "source_locator": thread.anchor_path,
                "selected_hash": thread.selected_hash,
                "diff_source_hash": suggestion.diff_source_hash,
                "diff_proposal_hash": suggestion.diff_proposal_hash,
                "impact_status": suggestion.impact_status,
                "impact_refs": [item.model_dump(mode="json") for item in suggestion.impact_refs],
                "evidence_span_ids": list(suggestion.evidence_span_ids),
                "evidence_brief_ids": list(thread.evidence_brief_ids),
                "evidence_source_types": list(suggestion.evidence_source_types),
                "citation_reference_ids": list(
                    dict.fromkeys(
                        reference_id
                        for binding in citation_bindings
                        for reference_id in binding["reference_ids"]
                    )
                ),
                "citation_count": len(citation_bindings),
                "fact_adoption_status": suggestion.fact_adoption_status,
                "adoption_basis": "medical_manager_explicit_selection",
                "previous_working_copy_revision": current.revision,
                "new_working_copy_revision": updated.revision,
                "before_block_hash": self._payload_hash(current.content_blocks[block_index]),
                "after_block_hash": self._payload_hash(updated_blocks[block_index]),
                "formatting_preserved": formatting_preserved,
                "anchor_type": thread.anchor_type,
                **table_apply_detail,
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        self.runtime_store.commit_medical_writing_working_copy_save(
            updated,
            audit_event,
            expected_revision=current.revision,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
            operation=operation,
            snapshot_type="apply_approved_ai_revision",
        )
        return MedicalWritingRevisionApplyResult(
            thread_id=thread_id,
            suggestion_id=suggestion.suggestion_id,
            working_copy=updated,
            audit_event=audit_event,
        )

    def normalize_revision_selection(
        self,
        project_id: str,
        section_id: str,
        selected_text: str,
        anchor_path: str,
    ) -> Tuple[str, str]:
        section = self.document_service.section(project_id, section_id)
        source_blocks = list(section.content_blocks)
        working_copy = self.working_copy(project_id, section_id)
        if working_copy.content_authority_state != "active_authoritative":
            raise RuntimeStoreError(
                "AI revision cannot read quarantined working-copy content"
            )
        working_blocks = list(working_copy.content_blocks)
        blocks = working_blocks or source_blocks
        substantive_blocks = [
            block for block in blocks if str(block.get("text", "")).strip()
        ]
        if not blocks:
            raise ValueError("selected protocol section has no editable source paragraphs")
        normalized_selection = selected_text.strip()
        matching_block = None
        if anchor_path:
            matching_block = next(
                (
                    block
                    for block in blocks
                    if str(block.get("source_locator", "")) == anchor_path
                ),
                None,
            )
            if matching_block is None:
                raise ValueError("revision anchor does not match the current working-copy block")
            current_text = str(matching_block.get("text", ""))
            if not current_text.strip():
                if normalized_selection:
                    raise ValueError(
                        "selected text does not match the current working-copy block"
                    )
                if not self._is_blank_greenfield_draft_block(matching_block):
                    raise ValueError(
                        "blank AI drafting is limited to an exact greenfield body block"
                    )
                return "", str(matching_block.get("source_locator", ""))
            if normalized_selection:
                occurrence_limit = len(current_text) - len(normalized_selection) + 1
                occurrences = sum(
                    1
                    for position in range(max(0, occurrence_limit))
                    if current_text.startswith(normalized_selection, position)
                )
                if occurrences == 0:
                    raise ValueError(
                        "selected text does not match the current working-copy block"
                    )
                if occurrences != 1:
                    raise ValueError(
                        "revision selection is ambiguous in the current working-copy block"
                    )
            if not normalized_selection:
                normalized_selection = current_text.strip()
        elif normalized_selection:
            matching_blocks = [
                block
                for block in substantive_blocks
                if normalized_selection in str(block.get("text", ""))
            ]
            if not matching_blocks:
                raise ValueError("selected text does not match the current working-copy section")
            if len(matching_blocks) != 1:
                raise ValueError(
                    "revision selection matches multiple current working-copy blocks; "
                    "provide an exact anchor"
                )
            matching_block = matching_blocks[0]
            current_text = str(matching_block.get("text", ""))
            occurrence_limit = len(current_text) - len(normalized_selection) + 1
            occurrences = sum(
                1
                for position in range(max(0, occurrence_limit))
                if current_text.startswith(normalized_selection, position)
            )
            if occurrences != 1:
                raise ValueError(
                    "revision selection is ambiguous in the current working-copy block"
                )
        else:
            if not substantive_blocks:
                raise ValueError(
                    "blank greenfield drafting requires an exact body-block anchor"
                )
            matching_block = substantive_blocks[0]
            normalized_selection = str(matching_block["text"]).strip()

        source_locator = str(matching_block.get("source_locator", ""))
        return normalized_selection, source_locator

    @staticmethod
    def _is_blank_greenfield_draft_block(block: Mapping[str, Any]) -> bool:
        locator = str(block.get("source_locator", ""))
        return (
            block.get("block_type") == "paragraph"
            and block.get("source_kind") == "greenfield_scaffold"
            and not str(block.get("text", "")).strip()
            and re.fullmatch(r"greenfield:[^:]+:section:[^:]+:body:\d+", locator)
            is not None
        )

    def normalize_table_cell_revision(
        self,
        project_id: str,
        section_id: str,
        requested_anchor: MedicalWritingTableCellAnchor,
        selected_text: str,
    ) -> dict[str, Any]:
        current = self.working_copy(project_id, section_id)
        if current.content_authority_state != "active_authoritative":
            raise RuntimeStoreError(
                "AI table revision cannot read quarantined working-copy content"
            )
        if requested_anchor.working_copy_id and requested_anchor.working_copy_id != current.working_copy_id:
            raise ValueError("table-cell revision working copy does not belong to the requested section")
        if requested_anchor.working_copy_revision != current.revision:
            raise ValueError(
                "stale table-cell working copy revision: "
                f"expected={requested_anchor.working_copy_revision}, actual={current.revision}"
            )
        matching_blocks = [
            block
            for block in current.content_blocks
            if str(block.get("block_id", "")) == requested_anchor.block_id
            and block.get("block_type") == "table"
        ]
        if len(matching_blocks) != 1:
            raise ValueError("table-cell anchor does not identify exactly one working-copy table")
        block = matching_blocks[0]
        table_service = MedicalWritingTableService()
        table = table_service.from_table_block(block)
        if table.table_id != requested_anchor.table_id:
            raise ValueError("table-cell anchor table identity is inconsistent")
        if table.version != requested_anchor.table_version:
            raise ValueError(
                "stale table-cell table version: "
                f"expected={requested_anchor.table_version}, actual={table.version}"
            )
        resolved = self._resolve_table_cell(table, requested_anchor)
        cell = resolved["cell"]
        raw_cell = next(
            (
                candidate
                for row in block.get("rows", [])
                for candidate in row
                if str(candidate.get("cell_id", "")) == cell.cell_id
            ),
            None,
        )
        if raw_cell is None or raw_cell.get("hidden"):
            raise ValueError("hidden or unavailable table cells cannot start an AI revision")
        current_text = str(cell.text)
        if selected_text != current_text or requested_anchor.captured_text != current_text:
            raise ValueError("table-cell selected text is stale or does not match the current cell")

        canonical_section = self.document_service.section(project_id, section_id)
        source_block = next(
            (
                candidate
                for candidate in canonical_section.content_blocks
                if str(candidate.get("block_id", "")) == requested_anchor.block_id
                and candidate.get("block_type") == "table"
            ),
            None,
        )
        source_kind = "source_linked" if source_block is not None else "generated"
        source_text, source_locator = self._table_revision_evidence_selection(
            canonical_section,
            source_block,
            requested_anchor.cell_id,
        )
        block_hash = self._payload_hash(block)
        canonical_anchor = MedicalWritingTableCellAnchor(
            working_copy_id=current.working_copy_id,
            working_copy_revision=current.revision,
            table_version=table.version,
            block_hash=block_hash,
            block_id=table.block_id,
            table_id=table.table_id,
            row_id=resolved["row"].row_id,
            column_id=resolved["column"].column_id,
            cell_id=cell.cell_id,
            captured_text=current_text,
            source_kind=source_kind,
        )
        anchor_path = json.dumps(
            {
                "block_id": canonical_anchor.block_id,
                "table_id": canonical_anchor.table_id,
                "row_id": canonical_anchor.row_id,
                "column_id": canonical_anchor.column_id,
                "cell_id": canonical_anchor.cell_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return {
            "selected_text": current_text,
            "anchor_path": anchor_path,
            "table_cell_anchor": canonical_anchor,
            "source_text": source_text,
            "source_locator": source_locator,
            "task_context": self._table_cell_task_context(
                table,
                resolved,
                canonical_anchor,
            ),
        }

    @staticmethod
    def _resolve_table_cell(table, anchor: MedicalWritingTableCellAnchor) -> dict[str, Any]:
        rows = [row for row in table.rows if row.row_id == anchor.row_id]
        columns = [column for column in table.columns if column.column_id == anchor.column_id]
        cells = [
            cell
            for row in table.rows
            for cell in row.cells
            if cell.cell_id == anchor.cell_id
        ]
        if len(rows) != 1 or len(columns) != 1 or len(cells) != 1:
            raise ValueError("table-cell anchor does not resolve exactly once")
        cell = cells[0]
        if cell.row_id != rows[0].row_id or cell.column_id != columns[0].column_id:
            raise ValueError("table-cell anchor hierarchy is inconsistent")
        return {"row": rows[0], "column": columns[0], "cell": cell}

    @staticmethod
    def _table_revision_evidence_selection(
        section,
        source_block: dict | None,
        cell_id: str,
    ) -> tuple[str, str]:
        if source_block is not None:
            source_table = MedicalWritingTableService().from_table_block(source_block)
            source_cell = next(
                (
                    cell
                    for row in source_table.rows
                    for cell in row.cells
                    if cell.cell_id == cell_id and str(cell.text).strip()
                ),
                None,
            )
            if source_cell is not None:
                return (
                    str(source_cell.text).strip(),
                    source_cell.source_locator or str(source_block.get("source_locator", "")),
                )
        for block in section.content_blocks:
            text = str(block.get("text", "")).strip()
            if text:
                return text, str(block.get("source_locator", ""))
            if block.get("block_type") == "table":
                for row in block.get("rows", []):
                    for cell in row:
                        cell_text = str(cell.get("text", "")).strip()
                        if cell_text:
                            return cell_text, str(
                                cell.get("source_locator") or block.get("source_locator", "")
                            )
        raise ValueError("protocol section has no original source text for table-cell AI revision")

    @staticmethod
    def _table_cell_task_context(table, resolved: dict[str, Any], anchor) -> dict[str, Any]:
        columns = sorted(table.columns, key=lambda item: item.order)
        rows = sorted(table.rows, key=lambda item: item.order)
        target_column_index = columns.index(resolved["column"])
        target_row_index = rows.index(resolved["row"])
        selected_indexes = sorted(
            set(range(min(2, len(columns))))
            | set(
                range(
                    max(0, target_column_index - 4),
                    min(len(columns), target_column_index + 5),
                )
            )
        )[:12]
        selected_column_ids = {columns[index].column_id for index in selected_indexes}

        def row_window(row):
            cells = {cell.column_id: cell for cell in row.cells}
            return [
                {
                    "column_id": columns[index].column_id,
                    "text": str(cells.get(columns[index].column_id).text)
                    if cells.get(columns[index].column_id)
                    else "",
                }
                for index in selected_indexes
            ]

        adjacent_rows = []
        for index in range(max(0, target_row_index - 2), min(len(rows), target_row_index + 3)):
            if index == target_row_index:
                continue
            adjacent_rows.append(
                {
                    "row_id": rows[index].row_id,
                    "label": rows[index].label,
                    "cells": row_window(rows[index]),
                }
            )
        note_targets = {
            table.table_id,
            table.block_id,
            resolved["row"].row_id,
            resolved["column"].column_id,
            resolved["cell"].cell_id,
            *selected_column_ids,
        }
        relevant_notes = [
            {
                "note_id": note.note_id,
                "marker": note.marker,
                "note_type": note.note_type.value,
                "text": note.text,
            }
            for note in table.notes
            if set(note.target_ids).intersection(note_targets)
        ][:10]
        return {
            "context_type": "working_copy_table_cell",
            "working_copy_id": anchor.working_copy_id,
            "working_copy_revision": anchor.working_copy_revision,
            "table_version": anchor.table_version,
            "block_hash": anchor.block_hash,
            "block_id": anchor.block_id,
            "table_id": anchor.table_id,
            "row_id": anchor.row_id,
            "column_id": anchor.column_id,
            "cell_id": anchor.cell_id,
            "selected_text": anchor.captured_text,
            "source_kind": anchor.source_kind,
            "is_source_linked": anchor.source_kind == "source_linked",
            "table_title": table.title,
            "table_domain": table.domain.value,
            "row_label": resolved["row"].label,
            "column_label": resolved["column"].label,
            "column_semantic_role": resolved["column"].semantic_role,
            "column_window": [
                {
                    "column_id": columns[index].column_id,
                    "label": columns[index].label,
                    "semantic_role": columns[index].semantic_role,
                }
                for index in selected_indexes
            ],
            "target_row_window": row_window(resolved["row"]),
            "adjacent_rows": adjacent_rows,
            "relevant_notes": relevant_notes,
        }

    @staticmethod
    def _revision_source_fact_ids(
        block: Mapping[str, Any],
        *,
        cell_id: str = "",
    ) -> set[str]:
        """Collect only exact source-fact identities present on one block/cell."""

        def clean(values: Any) -> set[str]:
            if not isinstance(values, (list, tuple, set)):
                return set()
            return {str(value).strip() for value in values if str(value).strip()}

        fact_ids = clean(block.get("source_fact_ids"))
        if block.get("block_type") != "table":
            return fact_ids
        for row in block.get("rows", []) or []:
            if not isinstance(row, list):
                continue
            for cell in row:
                if not isinstance(cell, Mapping):
                    continue
                if cell_id and str(cell.get("cell_id", "")) != cell_id:
                    continue
                fact_ids.update(clean(cell.get("source_fact_ids")))
        return fact_ids

    def revision_impact_projection(
        self,
        project_id: str,
        section_id: str,
        anchor_path: str,
        *,
        table_cell_anchor: MedicalWritingTableCellAnchor | None = None,
        evidence_brief_ids: list[str] | tuple[str, ...] = (),
    ) -> tuple[str, list[RevisionImpactRef]]:
        """Project only locally provable downstream impact for a revision.

        This is deliberately a read-only identity lookup.  It uses the current
        working-copy block's ``source_fact_ids`` as the only propagation edge;
        missing edges and approved external evidence are reported as
        ``unresolved`` rather than inferred.  The result is therefore safe to
        display before adoption and cannot claim that a section is affected
        merely because it has a similar heading or text.
        """

        document = self.project(project_id)
        target_working_copy = self.working_copy(project_id, section_id)
        working_copies = {
            item.section_id: item
            for item in self.runtime_store.medical_writing_working_copies_for_document(
                project_id, document.document_id
            )
        }
        working_copies[section_id] = target_working_copy
        target_block_id = (
            table_cell_anchor.block_id if table_cell_anchor is not None else ""
        )
        target_cell_id = (
            table_cell_anchor.cell_id if table_cell_anchor is not None else ""
        )
        target_block: Mapping[str, Any] | None = None
        target_facts: set[str] = set()
        target_type = "table_cell" if table_cell_anchor is not None else "paragraph"
        for block in target_working_copy.content_blocks:
            if not isinstance(block, Mapping):
                continue
            if table_cell_anchor is not None:
                if str(block.get("block_id", "")) != target_block_id:
                    continue
                if block.get("block_type") != "table":
                    continue
                target_block = block
                target_facts = self._revision_source_fact_ids(
                    block, cell_id=target_cell_id
                )
                break
            if str(block.get("source_locator", "")) == anchor_path:
                target_block = block
                target_facts = self._revision_source_fact_ids(block)
                break

        refs: list[RevisionImpactRef] = []
        if target_block is None:
            refs.append(
                RevisionImpactRef(
                    scope="unresolved",
                    target_type="unknown",
                    section_id=section_id,
                    target_id=anchor_path or target_block_id,
                    block_id=target_block_id,
                    reason_code="target_block_not_found",
                    message="当前工作副本无法唯一定位修订目标，未推断任何下游影响。",
                )
            )
            return "unresolved", refs

        target_id = target_cell_id or str(target_block.get("block_id", ""))
        refs.append(
            RevisionImpactRef(
                scope="local",
                target_type=target_type,
                section_id=section_id,
                target_id=target_id,
                block_id=str(target_block.get("block_id", "")),
                reason_code="selected_range",
                matched_source_fact_ids=sorted(target_facts),
                message="本次候选只直接作用于当前稳定选区。",
            )
        )

        unresolved = not target_facts
        if not target_facts:
            refs.append(
                RevisionImpactRef(
                    scope="unresolved",
                    target_type="unknown",
                    section_id=section_id,
                    target_id=target_id,
                    block_id=str(target_block.get("block_id", "")),
                    reason_code="source_fact_identity_missing",
                    message="目标没有可验证的 source_fact_ids，不能证明不存在下游依赖。",
                )
            )

        if evidence_brief_ids:
            unresolved = True
            refs.append(
                RevisionImpactRef(
                    scope="unresolved",
                    target_type="unknown",
                    section_id=section_id,
                    target_id=target_id,
                    block_id=str(target_block.get("block_id", "")),
                    reason_code="external_evidence_dependency_not_indexed",
                    message="外部证据已绑定，但当前局部图未声明其跨章节传播关系。",
                )
            )

        for section in document.sections:
            section_copy = working_copies.get(section.section_id)
            if section_copy is not None:
                blocks = section_copy.content_blocks
            else:
                # ``ProtocolDocument``'s session intentionally keeps source
                # blocks lazy.  Resolve an unversioned sibling section through
                # the read-only document service instead of treating an empty
                # list as proof that no dependent exists.
                try:
                    resolved_section = self.document_service.section(
                        project_id, section.section_id
                    )
                    blocks = getattr(resolved_section, "content_blocks", None)
                    if not isinstance(blocks, list):
                        raise RuntimeError("dependent section blocks are unavailable")
                except Exception:
                    unresolved = True
                    refs.append(
                        RevisionImpactRef(
                            scope="unresolved",
                            target_type="section",
                            section_id=section.section_id,
                            target_id=section.section_id,
                            reason_code="dependent_section_index_unavailable",
                            message="无法读取该依赖章节的权威区块索引，未推断其是否受影响。",
                        )
                    )
                    continue
            for block in blocks:
                if not isinstance(block, Mapping):
                    continue
                block_id = str(block.get("block_id", ""))
                if section.section_id == section_id and block_id == str(
                    target_block.get("block_id", "")
                ):
                    continue
                matched = target_facts.intersection(
                    self._revision_source_fact_ids(block)
                )
                if not matched:
                    continue
                refs.append(
                    RevisionImpactRef(
                        scope="downstream",
                        target_type=(
                            "table" if block.get("block_type") == "table" else "paragraph"
                        ),
                        section_id=section.section_id,
                        target_id=block_id or str(block.get("source_locator", "")),
                        block_id=block_id,
                        reason_code="shared_source_fact_id",
                        matched_source_fact_ids=sorted(matched),
                        message="该块与修订目标共享已登记的研究事实，需重新核验。",
                    )
                )

        refs.sort(
            key=lambda item: (
                {"local": 0, "downstream": 1, "unresolved": 2}[item.scope],
                item.section_id,
                item.block_id,
                item.target_id,
                item.reason_code,
            )
        )
        return ("unresolved" if unresolved else "known"), refs

    def commit_revision_submission(self, thread: RevisionThread, audit_event: AuditEvent) -> None:
        self.runtime_store.commit_medical_writing_revision_submission(thread, audit_event)

    def commit_revision_action(
        self,
        previous_thread: RevisionThread,
        updated_thread: RevisionThread,
        audit_event: AuditEvent,
        approval: ApprovalGate | None,
    ) -> None:
        self.runtime_store.commit_medical_writing_revision_action(
            previous_thread,
            updated_thread,
            audit_event,
            approval,
        )

    def accept_and_apply_candidate(
        self,
        project_id: str,
        thread_id: str,
        suggestion_id: str,
        expected_working_copy_revision: int,
        actor: str,
        idempotency_key: str,
        expected_generation_context_digest: str = "",
    ) -> MedicalWritingRevisionApplyResult:
        """Atomically accept an AI candidate and apply it to the working copy.

        All effects — selected suggestion accepted, siblings not_selected,
        thread author_selected, working-copy revision/content update, audit
        events, snapshots, and idempotency record — persist in a single
        SQLite ``BEGIN IMMEDIATE`` transaction via
        ``commit_medical_writing_atomic_accept_and_apply``.  Any validation
        failure or injected exception before COMMIT rolls back **all** of
        them.

        Raises StaleRuntimeStateError on stale thread or working copy revision.
        Raises RuntimeStoreError on frozen/quarantined content, project
        mismatch, plan drift, generation-lineage mismatch, or unselected thread.
        """
        thread = self.revision_thread(project_id, thread_id)
        # Fail closed: durable v2 candidates must match generation lineage.
        expected_digest = str(expected_generation_context_digest or "").strip()
        thread_digest = str(getattr(thread, "generation_context_digest", "") or "").strip()
        if expected_digest:
            if not thread_digest or thread_digest != expected_digest:
                raise RuntimeStoreError(
                    "candidate generation context digest does not match "
                    "authoritative lineage; neither selection nor body was written"
                )
        elif thread_digest:
            # Thread carries lineage but caller omitted digest — treat as stale gate miss.
            raise RuntimeStoreError(
                "candidate generation context digest was not revalidated before adopt"
            )
        document = self.project(project_id)
        if thread.project_id != project_id:
            raise RuntimeStoreError("revision thread project mismatch")
        if thread.document_id != document.document_id:
            raise RuntimeStoreError(
                "revision thread document is not the current project document"
            )
        # Validate the thread's section_id exists in the current project document.
        section_ids = {s.section_id for s in document.sections}
        if thread.section_id not in section_ids:
            raise RuntimeStoreError(
                f"revision thread references unknown section: {thread.section_id}"
            )

        # Locate the target suggestion early (needed for idempotent replay).
        suggestion = None
        for item in thread.suggestions:
            if item.suggestion_id == suggestion_id:
                suggestion = item
                break
        if suggestion is None:
            raise KeyError(f"suggestion not found: {suggestion_id}")

        # Frozen/quarantined check via require_authoritative (fail-closed).
        current = self.require_authoritative_revision_thread(
            project_id, thread.section_id, thread
        )
        if current.freeze_status == "frozen":
            raise RuntimeStoreError(
                "cannot accept and apply to a frozen working copy"
            )
        if current.content_authority_state != "active_authoritative":
            raise RuntimeStoreError(
                "cannot accept and apply to quarantined working-copy content"
            )

        # Idempotent replay short-circuit: same key after a successful atomic
        # adopt returns the prior working-copy snapshot without re-applying.
        try:
            citation_bindings_for_replay = self._accepted_revision_citation_bindings(
                project_id, thread, suggestion
            )
        except RuntimeStoreError:
            citation_bindings_for_replay = []
        operation = "medical_writing_atomic_accept_and_apply"
        legacy_replay_semantic_request = {
            "project_id": project_id,
            "document_id": document.document_id,
            "section_id": thread.section_id,
            "thread_id": thread_id,
            "suggestion_id": suggestion_id,
            "expected_working_copy_revision": expected_working_copy_revision,
            "actor": actor,
            "citation_bindings": citation_bindings_for_replay,
        }
        replay_semantic_request = {
            **legacy_replay_semantic_request,
            "selected_text": thread.selected_text,
            "selected_hash": thread.selected_hash,
        }
        replay_fingerprint = self._payload_hash(replay_semantic_request)
        replay = self._lookup_idempotent_replay_with_legacy(
            project_id,
            operation,
            idempotency_key,
            replay_fingerprint,
            legacy_replay_semantic_request,
        )
        if replay is not None:
            if thread_id not in current.applied_revision_thread_ids:
                raise RuntimeStoreError(
                    "idempotent replay has no applied revision linkage"
                )
            apply_audit = next(
                (
                    event
                    for event in self.runtime_store.workflow_audit_events(
                        project_id, "medical_writing_working_copy"
                    )
                    if event.action == "medical_writing_revision_applied"
                    and event.detail.get("revision_thread_id") == thread_id
                    and event.detail.get("suggestion_id") == suggestion_id
                ),
                None,
            )
            if apply_audit is None:
                raise RuntimeStoreError(
                    "idempotent replay has no immutable application audit"
                )
            snapshot_id = f"snapshot_{apply_audit.audit_id}"
            replay_snapshot = next(
                (
                    item
                    for item in self.runtime_store.medical_writing_working_copy_snapshots(
                        project_id,
                        current.working_copy_id,
                    )
                    if item["snapshot_id"] == snapshot_id
                    and item["snapshot_type"] == "apply_approved_ai_revision"
                    and item["audit_id"] == apply_audit.audit_id
                ),
                None,
            )
            if replay_snapshot is None:
                raise RuntimeStoreError(
                    "idempotent replay has no immutable application snapshot"
                )
            replayed_working_copy = replay_snapshot["working_copy"]
            if (
                replayed_working_copy.revision != expected_working_copy_revision + 1
                or thread_id not in replayed_working_copy.applied_revision_thread_ids
            ):
                raise RuntimeStoreError(
                    "idempotent replay application snapshot is inconsistent"
                )
            return MedicalWritingRevisionApplyResult(
                thread_id=thread_id,
                suggestion_id=suggestion_id,
                working_copy=replayed_working_copy,
                audit_event=apply_audit,
            )

        if suggestion.user_decision != "pending":
            raise ValueError(
                f"revision suggestion is already {suggestion.user_decision}"
            )

        if thread_id in current.applied_revision_thread_ids:
            raise RuntimeStoreError("approved revision thread was already applied")

        # Stale working-copy revision pre-check (fail before preparing state).
        if current.revision != expected_working_copy_revision:
            self.runtime_store.record_rejection(
                project_id,
                event_type="stale_write_rejected",
                operation="medical_writing_atomic_accept_and_apply",
                actor=actor,
                detail={
                    "thread_id": thread_id,
                    "section_id": thread.section_id,
                    "expected_revision": expected_working_copy_revision,
                    "actual_revision": current.revision,
                },
            )
            raise StaleRuntimeStateError(
                "stale medical writing working copy revision: "
                f"expected={expected_working_copy_revision}, actual={current.revision}"
            )

        # Recompute from the authoritative source and persisted proposal just
        # before any in-memory state is marked accepted. Missing or reordered
        # identity tokens fail closed for legacy and enriched suggestions;
        # additive tokens remain unresolved for medical review.
        protected_token_check = check_protected_tokens(
            thread.selected_text,
            suggestion.proposal_text,
        )
        if protected_token_check.violated:
            raise RuntimeStoreError(
                "protected token mismatch: "
                + "; ".join(
                    item["reason_code"]
                    for item in protected_token_issue_dicts(protected_token_check)
                    if item["reason_code"] != "protected_token_added_unresolved"
                )
            )

        # --- Prepare in-memory state (no persistence yet) ---

        previous_thread = thread.model_copy(deep=True)
        now = datetime.now(timezone.utc)

        # Mark suggestion accepted, siblings not_selected.
        target = suggestion
        for sibling in thread.suggestions:
            if (
                sibling.suggestion_id != target.suggestion_id
                and sibling.turn_number == target.turn_number
                and sibling.user_decision == "pending"
            ):
                sibling.user_decision = "not_selected"
        target.user_decision = "accepted"
        target.fact_adoption_status = "adopted_as_project_fact"
        thread.status = "author_selected"
        thread.resolved_at = now
        updated_thread = thread

        # Citation binding validation (same guard as service apply_action).
        citation_bindings = self._accepted_revision_citation_bindings(
            project_id, updated_thread, target
        )

        # Prepare content-block transformation.
        updated_blocks = json.loads(
            json.dumps(current.content_blocks, ensure_ascii=False)
        )
        table_apply_detail: dict[str, Any] = {}
        if thread.anchor_type == "table_cell":
            table_anchor = thread.table_cell_anchor
            if table_anchor is None:
                raise RuntimeStoreError(
                    "table-cell revision thread has no application-safe anchor"
                )
            # Validate anchor_path matches the structured table-cell anchor.
            expected_anchor_path = json.dumps(
                {
                    "block_id": table_anchor.block_id,
                    "table_id": table_anchor.table_id,
                    "row_id": table_anchor.row_id,
                    "column_id": table_anchor.column_id,
                    "cell_id": table_anchor.cell_id,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if thread.anchor_path != expected_anchor_path:
                raise RuntimeStoreError(
                    "table-cell revision anchor is not application-safe"
                )
            matching_indexes = [
                index
                for index, block in enumerate(current.content_blocks)
                if str(block.get("block_id", "")) == table_anchor.block_id
                and block.get("block_type") == "table"
            ]
            if len(matching_indexes) != 1:
                raise RuntimeStoreError(
                    "table-cell revision anchor does not identify exactly one content block"
                )
            block_index = matching_indexes[0]
            current_block = current.content_blocks[block_index]
            if self._payload_hash(current_block) != table_anchor.block_hash:
                raise RuntimeStoreError(
                    "approved table-cell target changed after AI revision submission"
                )
            table_service = MedicalWritingTableService()
            table = table_service.from_table_block(current_block)
            if (
                table.table_id != table_anchor.table_id
                or table.version != table_anchor.table_version
            ):
                raise RuntimeStoreError(
                    "approved table-cell target structure is stale"
                )
            self._validate_table_dual_representation(current_block, table)
            try:
                resolved = self._resolve_table_cell(table, table_anchor)
            except ValueError as exc:
                raise RuntimeStoreError(str(exc)) from exc
            if resolved["cell"].text != thread.selected_text:
                raise RuntimeStoreError(
                    "approved table-cell text no longer matches the revision target"
                )
            edit_operation: dict[str, Any] = {
                "op": "edit_cell",
                "cell_id": table_anchor.cell_id,
                "text": target.proposal_text,
            }
            if citation_bindings:
                if not isinstance(resolved["cell"].rich_text, dict):
                    raise RuntimeStoreError(
                        "AI citation application requires a rich-text table cell target"
                    )
                tc_replacement_text, tc_replacement_rich = (
                    self._replace_in_rich_text_with_citations(
                        resolved["cell"].rich_text,
                        thread.selected_text,
                        target.proposal_text,
                        citation_bindings,
                    )
                )
                edit_operation["text"] = tc_replacement_text
                edit_operation["rich_text"] = tc_replacement_rich
            elif isinstance(resolved["cell"].rich_text, dict):
                edit_operation["rich_text"] = self._replace_table_cell_rich_text(
                    resolved["cell"].rich_text,
                    thread.selected_text,
                    target.proposal_text,
                )
            updated_table = table_service.apply_operations(
                table,
                [edit_operation],
                expected_version=table_anchor.table_version,
            )
            updated_blocks[block_index] = table_service.to_table_block(updated_table)
            self._validate_table_dual_representation(
                updated_blocks[block_index], updated_table
            )
            self._assert_cross_reference_marks_preserved(
                current_block,
                updated_blocks[block_index],
            )
            replacement_text = str(edit_operation["text"])
            formatting_preserved = True
            original_text = ""
            if table_anchor.source_kind == "source_linked":
                canonical_section_tc = self.document_service.section(
                    project_id, thread.section_id
                )
                source_block_tc = next(
                    (
                        block
                        for block in canonical_section_tc.content_blocks
                        if str(block.get("block_id", "")) == table_anchor.block_id
                    ),
                    None,
                )
                original_text, _ = self._table_revision_evidence_selection(
                    canonical_section_tc,
                    source_block_tc,
                    table_anchor.cell_id,
                )
            table_apply_detail = {
                "block_id": table_anchor.block_id,
                "table_id": table_anchor.table_id,
                "row_id": table_anchor.row_id,
                "column_id": table_anchor.column_id,
                "cell_id": table_anchor.cell_id,
                "previous_text": thread.selected_text,
                "new_text": replacement_text,
                "previous_table_version": table_anchor.table_version,
                "new_table_version": updated_table.version,
                "source_kind": table_anchor.source_kind,
                "diverged_from_original": (
                    "not_applicable"
                    if table_anchor.source_kind == "generated"
                    else target.proposal_text != original_text
                ),
            }
        else:
            if not thread.anchor_path or (
                thread.source_locator
                and thread.source_locator != thread.anchor_path
            ):
                raise RuntimeStoreError(
                    "revision thread source locator is not application-safe"
                )

            matching_indexes = [
                index
                for index, block in enumerate(current.content_blocks)
                if str(block.get("source_locator", "")) == thread.anchor_path
            ]
            if len(matching_indexes) != 1:
                raise RuntimeStoreError(
                    "revision source locator does not identify exactly one content block"
                )
            block_index = matching_indexes[0]
            current_block = current.content_blocks[block_index]
            current_text = str(current_block.get("text", ""))
            blank_greenfield_draft = (
                not thread.selected_text
                and self._is_blank_greenfield_draft_block(current_block)
            )
            if blank_greenfield_draft:
                if current_text:
                    raise RuntimeStoreError(
                        "approved blank-section draft target is no longer empty"
                    )
                if not target.proposal_text.strip():
                    raise RuntimeStoreError(
                        "approved blank-section draft proposal must not be empty"
                    )
                replacement_text = target.proposal_text
            else:
                if (
                    not thread.selected_text
                    or current_text.count(thread.selected_text) != 1
                ):
                    raise RuntimeStoreError(
                        "approved selected text no longer exists exactly once "
                        "in the target block"
                    )
                replacement_text = current_text.replace(
                    thread.selected_text,
                    target.proposal_text,
                    1,
                )
            formatting_preserved = "rich_text" in updated_blocks[block_index]
            if citation_bindings:
                if not formatting_preserved:
                    raise RuntimeStoreError(
                        "AI citation application requires a rich-text paragraph target"
                    )
                proposal_display_text, updated_rich_text = (
                    self._replace_in_rich_text_with_citations(
                        updated_blocks[block_index]["rich_text"],
                        "" if blank_greenfield_draft else thread.selected_text,
                        target.proposal_text,
                        citation_bindings,
                    )
                )
                replacement_text = (
                    proposal_display_text
                    if blank_greenfield_draft
                    else current_text.replace(
                        thread.selected_text,
                        proposal_display_text,
                        1,
                    )
                )
                updated_blocks[block_index]["rich_text"] = updated_rich_text
            elif formatting_preserved:
                updated_blocks[block_index]["rich_text"] = (
                    self._replace_table_cell_rich_text(
                        updated_blocks[block_index]["rich_text"],
                        "",
                        target.proposal_text,
                    )
                    if blank_greenfield_draft
                    else self._replace_in_rich_text(
                        updated_blocks[block_index]["rich_text"],
                        thread.selected_text,
                        target.proposal_text,
                    )
                )
                if (
                    self._rich_text_plain_text(updated_blocks[block_index]["rich_text"])
                    != replacement_text
                ):
                    raise RuntimeStoreError(
                        "rich text replacement does not match the approved plain text"
                    )
            updated_blocks[block_index]["text"] = replacement_text
            self._assert_cross_reference_marks_preserved(
                current_block,
                updated_blocks[block_index],
            )

        canonical_section = self.document_service.section(
            project_id, thread.section_id
        )
        self._validate_working_copy_blocks(
            canonical_section.content_blocks,
            updated_blocks,
            existing_blocks=current.content_blocks,
        )

        # Build updated working-copy model.
        previous_working_copy = current.model_copy(deep=True)
        updated_working_copy = current.model_copy(
            update={
                "revision": current.revision + 1,
                "content_blocks": updated_blocks,
                "approval_state": ApprovalState.AI_DRAFT,
                "approved_revision": None,
                "approved_snapshot_id": None,
                **self._clear_author_freeze_fields(),
                "applied_revision_thread_ids": [
                    *current.applied_revision_thread_ids,
                    thread_id,
                ],
                "created_by": current.created_by if current.revision else actor,
                "updated_by": actor,
                "created_at": current.created_at if current.revision else now,
                "updated_at": now,
            },
            deep=True,
        )

        # Build audit events.
        accept_audit = AuditEvent(
            audit_id=f"audit_atomic_accept_{thread_id}_{now:%Y%m%d%H%M%S%f}",
            project_id=project_id,
            actor=actor,
            action="medical_writing_revision_accept",
            target_type="revision_thread",
            target_id=thread_id,
            detail={
                "suggestion_id": suggestion_id,
                "thread_status": updated_thread.status,
                "ai_run_id": updated_thread.ai_run_id,
                "selected_hash": updated_thread.selected_hash,
                "diff_source_hash": target.diff_source_hash,
                "diff_proposal_hash": target.diff_proposal_hash,
                "impact_status": target.impact_status,
                "impact_refs": [item.model_dump(mode="json") for item in target.impact_refs],
                "protected_token_status": protected_token_check.status,
                "protected_token_issues": protected_token_issue_dicts(
                    protected_token_check
                ),
                "evidence_source_types": list(target.evidence_source_types),
                "fact_adoption_status": target.fact_adoption_status,
                "adoption_basis": "medical_manager_explicit_selection",
                "citation_bindings": citation_bindings,
                "atomic_operation": "accept_and_apply_candidate",
            },
            created_at=now,
        )
        apply_audit = AuditEvent(
            audit_id=f"audit_atomic_apply_{thread_id}_{now:%Y%m%d%H%M%S%f}",
            project_id=project_id,
            actor=actor,
            action="medical_writing_revision_applied",
            target_type="medical_writing_working_copy",
            target_id=updated_working_copy.working_copy_id,
            detail={
                "document_id": document.document_id,
                "section_id": thread.section_id,
                "revision_thread_id": thread_id,
                "suggestion_id": target.suggestion_id,
                "source_locator": thread.anchor_path,
                "selected_hash": thread.selected_hash,
                "diff_source_hash": target.diff_source_hash,
                "diff_proposal_hash": target.diff_proposal_hash,
                "impact_status": target.impact_status,
                "impact_refs": [item.model_dump(mode="json") for item in target.impact_refs],
                "protected_token_status": protected_token_check.status,
                "protected_token_issues": protected_token_issue_dicts(
                    protected_token_check
                ),
                "evidence_span_ids": list(target.evidence_span_ids),
                "evidence_brief_ids": list(thread.evidence_brief_ids),
                "evidence_source_types": list(target.evidence_source_types),
                "citation_reference_ids": list(
                    dict.fromkeys(
                        ref_id
                        for binding in citation_bindings
                        for ref_id in binding["reference_ids"]
                    )
                ),
                "citation_count": len(citation_bindings),
                "fact_adoption_status": target.fact_adoption_status,
                "adoption_basis": "medical_manager_explicit_selection",
                "previous_working_copy_revision": current.revision,
                "new_working_copy_revision": updated_working_copy.revision,
                "before_block_hash": self._payload_hash(
                    current.content_blocks[block_index]
                ),
                "after_block_hash": self._payload_hash(
                    updated_blocks[block_index]
                ),
                "formatting_preserved": formatting_preserved,
                "anchor_type": thread.anchor_type,
                **table_apply_detail,
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )

        # Build request fingerprint for idempotency.
        legacy_semantic_request = {
            "project_id": project_id,
            "document_id": document.document_id,
            "section_id": thread.section_id,
            "thread_id": thread_id,
            "suggestion_id": suggestion_id,
            "expected_working_copy_revision": expected_working_copy_revision,
            "actor": actor,
            "citation_bindings": citation_bindings,
        }
        semantic_request = {
            **legacy_semantic_request,
            "selected_text": thread.selected_text,
            "selected_hash": thread.selected_hash,
        }
        request_fingerprint = self._payload_hash(semantic_request)

        # --- Single-transaction commit (both-or-neither) ---
        commit_result = self.runtime_store.commit_medical_writing_atomic_accept_and_apply(
            previous_thread=previous_thread,
            updated_thread=updated_thread,
            accept_audit_event=accept_audit,
            previous_working_copy=previous_working_copy,
            updated_working_copy=updated_working_copy,
            apply_audit_event=apply_audit,
            expected_working_copy_revision=expected_working_copy_revision,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )

        # A concurrent same-key caller may pass the outer replay lookup before
        # the winner commits.  The SQLite store then returns replayed=True;
        # never return this caller's locally prepared audit/snapshot because it
        # is not the immutable persisted winner.
        if commit_result.replayed:
            authoritative_working_copy = self.working_copy(
                project_id,
                thread.section_id,
            )
            authoritative_apply_audit = next(
                (
                    event
                    for event in self.runtime_store.workflow_audit_events(
                        project_id,
                        "medical_writing_working_copy",
                    )
                    if event.action == "medical_writing_revision_applied"
                    and event.detail.get("revision_thread_id") == thread_id
                    and event.detail.get("suggestion_id") == suggestion_id
                ),
                None,
            )
            if authoritative_apply_audit is None:
                raise RuntimeStoreError(
                    "idempotent replay has no immutable application audit"
                )
            authoritative_snapshot_id = (
                f"snapshot_{authoritative_apply_audit.audit_id}"
            )
            authoritative_snapshot = next(
                (
                    item
                    for item in self.runtime_store.medical_writing_working_copy_snapshots(
                        project_id,
                        authoritative_working_copy.working_copy_id,
                    )
                    if item["snapshot_id"] == authoritative_snapshot_id
                    and item["snapshot_type"] == "apply_approved_ai_revision"
                    and item["audit_id"] == authoritative_apply_audit.audit_id
                ),
                None,
            )
            if authoritative_snapshot is None:
                raise RuntimeStoreError(
                    "idempotent replay has no immutable application snapshot"
                )
            replayed_working_copy = authoritative_snapshot["working_copy"]
            if (
                replayed_working_copy.revision != expected_working_copy_revision + 1
                or thread_id not in replayed_working_copy.applied_revision_thread_ids
            ):
                raise RuntimeStoreError(
                    "idempotent replay application snapshot is inconsistent"
                )
            return MedicalWritingRevisionApplyResult(
                thread_id=thread_id,
                suggestion_id=suggestion_id,
                working_copy=replayed_working_copy,
                audit_event=authoritative_apply_audit,
            )

        return MedicalWritingRevisionApplyResult(
            thread_id=thread_id,
            suggestion_id=target.suggestion_id,
            working_copy=updated_working_copy,
            audit_event=apply_audit,
        )

    def freeze_current_version(
        self,
        project_id: str,
        section_id: str,
        request: MedicalWritingSectionFreezeRequest,
    ) -> MedicalWritingSectionFreezeResult:
        document = self.project(project_id)
        section = self.document_service.section(project_id, section_id)
        if (
            request.document_id != document.document_id
            or section.document_id != document.document_id
        ):
            raise RuntimeStoreError(
                "section freeze document does not match the canonical project document"
            )
        self._require_authoritative_document_binding(project_id)
        current = self.working_copy(project_id, section_id)
        if current.content_authority_state != "active_authoritative":
            raise RuntimeStoreError(
                "section freeze cannot use quarantined working-copy content"
            )
        if current.study_definition_reconciliation_required:
            raise RuntimeStoreError(
                "section freeze requires the current chapter to complete "
                "StudyDefinition content reconciliation (调和)"
            )
        if current.revision < 1:
            raise RuntimeStoreError(
                "section freeze requires a saved working-copy revision"
            )
        if current.revision != request.expected_working_copy_revision:
            raise StaleRuntimeStateError(
                "stale section freeze revision: "
                f"expected={request.expected_working_copy_revision}, actual={current.revision}"
            )
        expected_binding = (
            request.expected_study_definition_id,
            request.expected_study_definition_revision,
            request.expected_study_definition_sha256,
        )
        actual_binding = self._current_binding(project_id)
        working_binding = (
            current.source_study_definition_id,
            current.source_study_definition_revision,
            current.source_study_definition_sha256,
        )
        if expected_binding != actual_binding or working_binding != actual_binding:
            raise StaleRuntimeStateError(
                "section freeze StudyDefinition binding changed or does not match the working copy"
            )

        if current.freeze_status == "frozen":
            record = next(
                (
                    item
                    for item in self.section_freeze_history(project_id, section_id)
                    if item.snapshot_id == current.frozen_snapshot_id
                ),
                None,
            )
            if record is None:
                raise RuntimeStoreError(
                    "current section freeze has no immutable historical snapshot"
                )
            return MedicalWritingSectionFreezeResult(
                operation="freeze_current_version",
                working_copy=current,
                freeze_record=record,
                replayed=True,
            )

        semantic_request = {
            "project_id": project_id,
            "document_id": document.document_id,
            "section_id": section_id,
            "working_copy_id": current.working_copy_id,
            "expected_working_copy_revision": request.expected_working_copy_revision,
            "study_definition_binding": actual_binding,
            "reason": request.reason,
            "actor": request.actor,
        }
        request_fingerprint = self._payload_hash(semantic_request)
        operation = "medical_writing_section_freeze"
        token = sha256(
            f"{project_id}:{document.document_id}:{section_id}:{request.idempotency_key}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        snapshot_id = f"snapshot_author_freeze_{token}"
        audit_id = f"audit_author_freeze_{token}"
        replay = self.runtime_store.lookup_idempotent_replay(
            project_id,
            operation,
            request.idempotency_key,
            request_fingerprint,
        )
        if replay is not None:
            if current.freeze_status != "frozen":
                raise StaleRuntimeStateError(
                    "section freeze idempotency key refers to an obsolete freeze; "
                    "use a new key for the current section state"
                )
            record = next(
                (
                    item
                    for item in self.section_freeze_history(project_id, section_id)
                    if item.snapshot_id == snapshot_id
                ),
                None,
            )
            if record is None:
                raise RuntimeStoreError(
                    "idempotent section freeze replay has no immutable snapshot"
                )
            snapshot = next(
                item["working_copy"]
                for item in self.runtime_store.medical_writing_working_copy_snapshots(
                    project_id, current.working_copy_id
                )
                if item["snapshot_id"] == snapshot_id
            )
            audit = next(
                event
                for event in self.runtime_store.workflow_audit_events(
                    project_id, "medical_writing_section_freeze"
                )
                if event.audit_id == audit_id
            )
            return MedicalWritingSectionFreezeResult(
                operation="freeze_current_version",
                working_copy=self._author_semantics_view(snapshot),
                freeze_record=record,
                audit_event=audit,
                replayed=True,
            )

        stored = self.runtime_store.medical_writing_working_copy_by_id(
            project_id, current.working_copy_id
        )
        if stored.revision != current.revision:
            raise StaleRuntimeStateError(
                "working copy changed before the section freeze transaction"
            )
        now = datetime.now(timezone.utc)
        updated = stored.model_copy(
            update={
                "approval_state": ApprovalState.AI_DRAFT,
                "approved_revision": None,
                "approved_snapshot_id": None,
                "freeze_status": "frozen",
                "frozen_revision": stored.revision,
                "frozen_snapshot_id": snapshot_id,
                "frozen_by": request.actor,
                "frozen_at": now,
                "frozen_study_definition_id": actual_binding[0],
                "frozen_study_definition_revision": actual_binding[1],
                "frozen_study_definition_sha256": actual_binding[2],
                "updated_by": request.actor,
                "updated_at": now,
            },
            deep=True,
        )
        audit = AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor=request.actor,
            action="medical_writing_section_version_frozen",
            target_type="medical_writing_working_copy",
            target_id=stored.working_copy_id,
            detail={
                "document_id": document.document_id,
                "section_id": section_id,
                "working_copy_revision": stored.revision,
                "freeze_snapshot_id": snapshot_id,
                "study_definition_binding": {
                    "definition_id": actual_binding[0],
                    "definition_revision": actual_binding[1],
                    "definition_sha256": actual_binding[2],
                },
                "reason": request.reason,
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        commit = self.runtime_store.commit_medical_writing_section_freeze(
            stored,
            updated,
            audit,
            snapshot_id=snapshot_id,
            action="freeze_current_version",
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        record = MedicalWritingSectionFreezeRecord(
            snapshot_id=snapshot_id,
            project_id=project_id,
            document_id=document.document_id,
            section_id=section_id,
            working_copy_id=stored.working_copy_id,
            working_copy_revision=stored.revision,
            study_definition_id=actual_binding[0],
            study_definition_revision=actual_binding[1],
            study_definition_sha256=actual_binding[2],
            frozen_by=request.actor,
            frozen_at=now,
            audit_id=audit_id,
            source="author_freeze",
            is_current=True,
        )
        return MedicalWritingSectionFreezeResult(
            operation="freeze_current_version",
            working_copy=self._author_semantics_view(updated),
            freeze_record=record,
            audit_event=audit,
            replayed=commit.replayed,
        )

    def unfreeze_current_version(
        self,
        project_id: str,
        section_id: str,
        request: MedicalWritingSectionFreezeRequest,
    ) -> MedicalWritingSectionFreezeResult:
        document = self.project(project_id)
        section = self.document_service.section(project_id, section_id)
        if (
            request.document_id != document.document_id
            or section.document_id != document.document_id
        ):
            raise RuntimeStoreError(
                "section unfreeze document does not match the canonical project document"
            )
        self._require_authoritative_document_binding(project_id)
        current = self.working_copy(project_id, section_id)
        if current.content_authority_state != "active_authoritative":
            raise RuntimeStoreError("section unfreeze cannot act on quarantined content")
        if current.revision != request.expected_working_copy_revision:
            raise StaleRuntimeStateError(
                "stale section unfreeze revision: "
                f"expected={request.expected_working_copy_revision}, actual={current.revision}"
            )
        actual_binding = self._current_binding(project_id)
        if (
            (
                request.expected_study_definition_id,
                request.expected_study_definition_revision,
                request.expected_study_definition_sha256,
            )
            != actual_binding
            or (
                current.source_study_definition_id,
                current.source_study_definition_revision,
                current.source_study_definition_sha256,
            )
            != actual_binding
        ):
            raise StaleRuntimeStateError(
                "section unfreeze StudyDefinition binding changed or does not match the working copy"
            )
        if current.freeze_status == "editable":
            return MedicalWritingSectionFreezeResult(
                operation="unfreeze",
                working_copy=current,
                replayed=True,
            )

        semantic_request = {
            "project_id": project_id,
            "document_id": document.document_id,
            "section_id": section_id,
            "working_copy_id": current.working_copy_id,
            "expected_working_copy_revision": request.expected_working_copy_revision,
            "study_definition_binding": actual_binding,
            "reason": request.reason,
            "actor": request.actor,
        }
        request_fingerprint = self._payload_hash(semantic_request)
        operation = "medical_writing_section_unfreeze"
        token = sha256(
            f"{project_id}:{document.document_id}:{section_id}:unfreeze:{request.idempotency_key}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        audit_id = f"audit_author_unfreeze_{token}"
        replay = self.runtime_store.lookup_idempotent_replay(
            project_id,
            operation,
            request.idempotency_key,
            request_fingerprint,
        )
        if replay is not None:
            if current.freeze_status != "editable":
                raise StaleRuntimeStateError(
                    "section unfreeze idempotency key refers to an obsolete unfreeze; "
                    "use a new key for the current section state"
                )
            audit = next(
                event
                for event in self.runtime_store.workflow_audit_events(
                    project_id, "medical_writing_section_freeze"
                )
                if event.audit_id == audit_id
            )
            return MedicalWritingSectionFreezeResult(
                operation="unfreeze",
                working_copy=self.working_copy(project_id, section_id),
                audit_event=audit,
                replayed=True,
            )

        stored = self.runtime_store.medical_writing_working_copy_by_id(
            project_id, current.working_copy_id
        )
        now = datetime.now(timezone.utc)
        updated = stored.model_copy(
            update={
                "approval_state": ApprovalState.AI_DRAFT,
                "approved_revision": None,
                "approved_snapshot_id": None,
                **self._clear_author_freeze_fields(),
                "updated_by": request.actor,
                "updated_at": now,
            },
            deep=True,
        )
        audit = AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor=request.actor,
            action="medical_writing_section_version_unfrozen",
            target_type="medical_writing_working_copy",
            target_id=stored.working_copy_id,
            detail={
                "document_id": document.document_id,
                "section_id": section_id,
                "working_copy_revision": stored.revision,
                "previous_freeze_snapshot_id": current.frozen_snapshot_id,
                "reason": request.reason,
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        commit = self.runtime_store.commit_medical_writing_section_freeze(
            stored,
            updated,
            audit,
            snapshot_id="",
            action="unfreeze",
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        return MedicalWritingSectionFreezeResult(
            operation="unfreeze",
            working_copy=self._author_semantics_view(updated),
            audit_event=audit,
            replayed=commit.replayed,
        )

    def section_freeze_history(
        self, project_id: str, section_id: str
    ) -> list[MedicalWritingSectionFreezeRecord]:
        document = self.project(project_id)
        section = self.document_service.section(project_id, section_id)
        current = self.working_copy(project_id, section_id)
        records: list[MedicalWritingSectionFreezeRecord] = []
        for item in self.runtime_store.medical_writing_working_copy_snapshots(
            project_id, current.working_copy_id
        ):
            if item["snapshot_type"] not in {"author_freeze", "approval"}:
                continue
            snapshot = self._author_semantics_view(item["working_copy"])
            if (
                snapshot.document_id != document.document_id
                or snapshot.section_id != section.section_id
                or snapshot.working_copy_id != current.working_copy_id
                or snapshot.frozen_revision is None
                or not snapshot.frozen_snapshot_id
            ):
                continue
            records.append(
                MedicalWritingSectionFreezeRecord(
                    snapshot_id=item["snapshot_id"],
                    project_id=project_id,
                    document_id=document.document_id,
                    section_id=section_id,
                    working_copy_id=current.working_copy_id,
                    working_copy_revision=snapshot.frozen_revision,
                    study_definition_id=snapshot.frozen_study_definition_id,
                    study_definition_revision=(
                        snapshot.frozen_study_definition_revision
                    ),
                    study_definition_sha256=(
                        snapshot.frozen_study_definition_sha256
                    ),
                    frozen_by=snapshot.frozen_by or "legacy_medical_author",
                    frozen_at=snapshot.frozen_at or item["created_at"],
                    audit_id=item["audit_id"],
                    source=(
                        "author_freeze"
                        if item["snapshot_type"] == "author_freeze"
                        else "legacy_medical_approval"
                    ),
                    is_current=(
                        current.freeze_status == "frozen"
                        and current.frozen_snapshot_id == item["snapshot_id"]
                    ),
                )
            )
        return records

    def ensure_revision_approval_gate(
        self,
        thread: RevisionThread,
        requested_by: str,
    ) -> ApprovalGate:
        raise RuntimeStoreError(
            "medical-writing revision approvals are retired; selecting an AI candidate "
            "is the medical author's decision"
        )

    def ensure_working_copy_approval_gate(
        self,
        working_copy: MedicalWritingWorkingCopy,
        requested_by: str,
    ) -> ApprovalGate:
        raise RuntimeStoreError(
            "medical-writing working-copy approvals are retired; use "
            "freeze-current-version after the author confirms the chapter"
        )

    def approvals(self, project_id: str) -> List[ApprovalGate]:
        self.project(project_id)
        return []

    def approval(self, project_id: str, approval_id: str) -> ApprovalGate:
        for approval in self.approvals(project_id):
            if approval.approval_id == approval_id:
                return approval
        raise KeyError(f"{project_id}/{approval_id}")

    def approval_blockers(
        self,
        project_id: str,
        approval_id: str,
    ) -> List[ApprovalBlocker]:
        approval = self.approval(project_id, approval_id)
        blockers: List[ApprovalBlocker] = []
        if approval.target_type == "medical_writing_revision_thread":
            thread = self.revision_thread(project_id, approval.target_id)
            if thread.status != "accepted_pending_medical_approval":
                blockers.append(
                    ApprovalBlocker(
                        blocker_id=f"revision_thread_status:{thread.thread_id}",
                        blocker_type="revision_not_accepted",
                        source_type="revision_thread",
                        source_id=thread.thread_id,
                        severity=RiskSeverity.HIGH,
                        message=(
                            "修订建议尚未处于 accepted_pending_medical_approval 状态，"
                            "不得执行最终医学批准。"
                        ),
                    )
                )
        elif approval.target_type == "medical_writing_working_copy":
            working_copy = self.runtime_store.medical_writing_working_copy_by_id(
                project_id,
                approval.target_id,
            )
            if self.study_consistency_service is not None:
                consistency_blocker = self.study_consistency_service.approval_blocker(
                    project_id, working_copy.section_id
                )
                if consistency_blocker is not None:
                    blockers.append(consistency_blocker)
            if approval.target_revision != working_copy.revision:
                blockers.append(
                    ApprovalBlocker(
                        blocker_id=f"working_copy_revision:{working_copy.working_copy_id}",
                        blocker_type="stale_working_copy_revision",
                        source_type="medical_writing_working_copy",
                        source_id=working_copy.working_copy_id,
                        severity=RiskSeverity.HIGH,
                        message=(
                            f"审批目标版本为 {approval.target_revision}，当前版本为 "
                            f"{working_copy.revision}；必须重新发起审批。"
                        ),
                    )
                )
            content_quality = self.content_quality(project_id, working_copy.section_id)
            for finding in content_quality.findings:
                if not finding.approval_blocking or finding.disposition_status not in {
                    MedicalWritingContentDispositionStatus.OPEN,
                    MedicalWritingContentDispositionStatus.CORRECTION_REQUIRED,
                }:
                    continue
                blockers.append(
                    ApprovalBlocker(
                        blocker_id=(
                            f"medical_writing_content:{finding.finding_id}:"
                            f"{finding.content_fingerprint[:12]}"
                        ),
                        blocker_type="medical_writing_content_quality",
                        source_type="medical_writing_content_finding",
                        source_id=finding.finding_id,
                        severity=RiskSeverity.HIGH,
                        message=(
                            f"{finding.section_heading}：{finding.source_text}；"
                            "该源内容异常尚未完成医学处置。"
                        ),
                    )
                )
            from .medical_writing_table_domain_profiles import (
                MedicalWritingTableDomainProfileService,
            )
            from .medical_writing_tables import MedicalWritingTableService

            profile_service = MedicalWritingTableDomainProfileService()
            table_service = MedicalWritingTableService()
            for block in working_copy.content_blocks:
                if block.get("block_type") != "table" or not isinstance(
                    block.get("structured_table"), dict
                ):
                    continue
                profile_state = (
                    block["structured_table"].get("word_layout", {}).get(
                        "domain_profile", {}
                    )
                )
                mapping_source = (
                    str(profile_state.get("source") or "")
                    if isinstance(profile_state, dict)
                    else ""
                )
                if not (
                    block.get("source_kind") == "medical_writing_template"
                    or mapping_source == "working_copy_user_mapping"
                ):
                    continue
                table = table_service.from_table_block(block)
                for finding in profile_service.validate(table):
                    if finding["severity"] != "warning":
                        continue
                    blockers.append(
                        ApprovalBlocker(
                            blocker_id=(
                                f"domain_profile:{table.block_id}:"
                                f"{finding.get('finding_key', finding['code'])}"
                            ),
                            blocker_type=f"domain_profile_{finding['code']}",
                            source_type="medical_writing_structured_table",
                            source_id=table.block_id,
                            severity=RiskSeverity.HIGH,
                            message=f"{table.title}：{finding['message']}",
                        )
                    )
            document_blockers = getattr(
                self.document_service,
                "approval_blockers",
                None,
            )
            if callable(document_blockers):
                blockers.extend(document_blockers(project_id))
        return blockers

    def record_approval_action(
        self,
        project_id: str,
        approval_id: str,
        request: ApprovalActionRequest,
    ) -> ApprovalActionResult:
        semantic_request = {
            "project_id": project_id,
            "approval_id": approval_id,
            "action": request.action.value,
            "actor": request.actor,
            "comment": request.comment,
        }
        request_fingerprint = self._payload_hash(semantic_request)
        idempotency_key = request.idempotency_key.strip() or f"auto:{uuid4().hex}"
        token = sha256(
            f"{project_id}:{approval_id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()[:20]
        if request.idempotency_key.strip():
            replay = self.runtime_store.lookup_idempotent_replay(
                project_id,
                "medical_writing_final_approval",
                idempotency_key,
                request_fingerprint,
            )
            if replay is not None:
                decision_id = f"decision_medical_writing_approval_{token}"
                audit_id = f"audit_medical_writing_approval_{token}"
                stored_decision = next(
                    item
                    for item in self.runtime_store.decisions(project_id)
                    if item.decision_id == decision_id
                )
                stored_audit = next(
                    item
                    for item in self.runtime_store.audit_events(project_id)
                    if item.audit_id == audit_id
                )
                return ApprovalActionResult(
                    approval=self.approval(project_id, approval_id),
                    decision=stored_decision,
                    audit_event=stored_audit,
                    blockers=stored_decision.blockers,
                )

        approval = self.approval(project_id, approval_id)
        blockers = self.approval_blockers(project_id, approval_id)
        action_blocked = request.action == ApprovalAction.APPROVE and bool(blockers)
        previous_state = approval.state
        new_state = previous_state
        if not action_blocked:
            if request.action == ApprovalAction.APPROVE:
                new_state = ApprovalState.MEDICALLY_APPROVED
            elif request.action == ApprovalAction.RETURN_FOR_REVISION:
                new_state = ApprovalState.RETURNED_FOR_REVISION
            elif request.action == ApprovalAction.REJECT:
                new_state = ApprovalState.SUPERSEDED

        should_update = request.action != ApprovalAction.VIEW_QUALITY_GATE and not action_blocked
        now = datetime.now(timezone.utc)
        updated_approval = approval
        approval_for_write = None
        if should_update:
            updates = {
                "state": new_state,
                "reviewed_by": request.actor,
                "updated_at": now,
            }
            if request.action == ApprovalAction.APPROVE:
                updates["approved_by"] = request.actor
            else:
                updates["approved_by"] = None
            if request.comment:
                updates["review_comments"] = request.comment
            updated_approval = approval.model_copy(update=updates)
            approval_for_write = updated_approval

        audit_event = AuditEvent(
            audit_id=f"audit_medical_writing_approval_{token}",
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
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        decision = ApprovalDecisionRecord(
            decision_id=f"decision_medical_writing_approval_{token}",
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

        previous_thread = updated_thread = None
        previous_working_copy = updated_working_copy = None
        target_snapshot_id = ""
        if should_update and approval.target_type == "medical_writing_revision_thread":
            previous_thread = self.revision_thread(project_id, approval.target_id)
            status = {
                ApprovalAction.APPROVE: "medically_approved",
                ApprovalAction.RETURN_FOR_REVISION: "returned_for_revision",
                ApprovalAction.REJECT: "superseded",
            }[request.action]
            updated_thread = previous_thread.model_copy(
                update={"status": status, "resolved_at": now},
                deep=True,
            )
            target_snapshot_id = f"snapshot_medical_writing_approval_{token}"
        elif should_update and approval.target_type == "medical_writing_working_copy":
            previous_working_copy = self.runtime_store.medical_writing_working_copy_by_id(
                project_id,
                approval.target_id,
            )
            if approval.target_revision != previous_working_copy.revision:
                raise StaleRuntimeStateError(
                    "medical writing working copy changed after approval gate creation"
                )
            target_snapshot_id = f"snapshot_medical_writing_approval_{token}"
            updates = {
                "approval_state": new_state,
                "updated_by": request.actor,
                "updated_at": now,
                "approved_revision": (
                    previous_working_copy.revision
                    if request.action == ApprovalAction.APPROVE
                    else None
                ),
                "approved_snapshot_id": (
                    target_snapshot_id
                    if request.action == ApprovalAction.APPROVE
                    else None
                ),
            }
            updated_working_copy = previous_working_copy.model_copy(
                update=updates,
                deep=True,
            )

        commit = self.runtime_store.commit_medical_writing_approval_action(
            approval_for_write,
            audit_event,
            decision,
            previous_thread=previous_thread,
            updated_thread=updated_thread,
            previous_working_copy=previous_working_copy,
            updated_working_copy=updated_working_copy,
            target_snapshot_id=target_snapshot_id,
            idempotency_key=idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if commit.replayed:
            stored_gate = self.approval(project_id, approval_id)
            stored_decision = next(
                item
                for item in self.runtime_store.decisions(project_id)
                if item.decision_id == decision.decision_id
            )
            stored_audit = next(
                item
                for item in self.runtime_store.audit_events(project_id)
                if item.audit_id == audit_event.audit_id
            )
            return ApprovalActionResult(
                approval=stored_gate,
                decision=stored_decision,
                audit_event=stored_audit,
                blockers=stored_decision.blockers,
            )
        return ApprovalActionResult(
            approval=updated_approval,
            decision=decision,
            audit_event=audit_event,
            blockers=blockers,
        )

    def audit_events(self, project_id: str) -> List[AuditEvent]:
        self.project(project_id)
        return self.runtime_store.workflow_audit_events(project_id, "medical_writing_revision")

    def authoritative_study_definition_binding(
        self, project_id: str
    ) -> tuple[str, Optional[int], str]:
        self._require_authoritative_document_binding(project_id)
        return self._current_binding(project_id)

    def authoritative_revision_source_identity(
        self, project_id: str, section_id: str
    ) -> tuple[str, int, str]:
        current = self.working_copy(project_id, section_id)
        if current.content_authority_state != "active_authoritative":
            raise RuntimeStoreError(
                "AI revision cannot start from quarantined working-copy content"
            )
        return (
            current.working_copy_id,
            current.revision,
            self._payload_hash(current.content_blocks),
        )

    def require_authoritative_revision_thread(
        self,
        project_id: str,
        section_id: str,
        thread: RevisionThread,
        *,
        allow_stale_table_anchor: bool = False,
    ) -> MedicalWritingWorkingCopy:
        document = self.project(project_id)
        if (
            thread.project_id != project_id
            or thread.document_id != document.document_id
            or thread.section_id != section_id
        ):
            raise RuntimeStoreError("revision thread identity does not match the active section")
        definition_id, definition_revision, definition_sha256 = self._current_binding(
            project_id
        )
        if (
            thread.source_study_definition_id != definition_id
            or thread.source_study_definition_revision != definition_revision
            or thread.source_study_definition_sha256 != definition_sha256
        ):
            raise RuntimeStoreError(
                "revision thread is unbound or stale for the current StudyDefinition"
            )
        current = self.working_copy(project_id, section_id)
        if current.content_authority_state != "active_authoritative":
            raise RuntimeStoreError(
                "revision thread cannot act on quarantined working-copy content"
            )
        # A successful atomic adoption changes the target text and working-copy
        # revision by design. A replay must reach its idempotency lookup, so
        # bypass both the pre-apply working-copy identity and range checks only
        # when the immutable applied-thread linkage already proves that the
        # original write happened.
        if thread.thread_id in current.applied_revision_thread_ids:
            return current
        source_working_copy_is_bound = bool(
            thread.source_working_copy_id
            or thread.source_working_copy_revision is not None
            or thread.source_working_copy_content_sha256
        )
        working_copy_binding_stale = (
            source_working_copy_is_bound or self.study_consistency_service is not None
        ) and (
            thread.source_working_copy_id != current.working_copy_id
            or thread.source_working_copy_revision != current.revision
            or thread.source_working_copy_content_sha256
            != self._payload_hash(current.content_blocks)
        )
        # Blank greenfield drafting is a special, exact-target contract.  If
        # the user has since entered text into that target, surface the
        # actionable selected-text error before the broader stale-snapshot
        # error.  This keeps the rejection explainable without weakening the
        # stale identity guard: an unchanged blank target still fails closed
        # as a stale working-copy revision.
        if working_copy_binding_stale and not thread.selected_text:
            try:
                if thread.anchor_type == "table_cell":
                    if thread.table_cell_anchor is None:
                        raise ValueError(
                            "table-cell revision thread has no structured anchor"
                        )
                    stale_blank_selection = self.normalize_table_cell_revision(
                        project_id,
                        section_id,
                        thread.table_cell_anchor,
                        thread.selected_text,
                    )["selected_text"]
                else:
                    stale_blank_selection, _ = self.normalize_revision_selection(
                        project_id,
                        section_id,
                        thread.selected_text,
                        thread.anchor_path,
                    )
            except (RuntimeStoreError, ValueError):
                stale_blank_selection = ""
            if str(stale_blank_selection or "").strip():
                raise RuntimeStoreError(
                    "revision thread selected text is no longer an exact blank greenfield target"
                )
        if working_copy_binding_stale:
            raise StaleRuntimeStateError(
                "revision thread was created from a stale working-copy revision"
            )
        # Re-resolve the exact semantic range from the authoritative working
        # copy and compare its persisted selected_hash.  The working-copy
        # identity check above protects the snapshot as a whole; this narrower
        # check protects the range itself, including legacy threads that were
        # loaded with a model-backfilled hash.  Keep table-cell and paragraph
        # contracts on their existing isolated paths.
        try:
            if thread.anchor_type == "table_cell":
                if thread.table_cell_anchor is None:
                    raise ValueError(
                        "table-cell revision thread has no structured anchor"
                    )
                if (
                    allow_stale_table_anchor
                    and thread.table_cell_anchor.working_copy_revision != current.revision
                ):
                    # The approved-apply path performs the authoritative block
                    # hash, structure, and cell-text checks itself and must
                    # surface its more specific "changed after AI revision
                    # submission" diagnostic. Other callers retain strict
                    # anchor-revision validation.
                    return current
                resolved_selection = self.normalize_table_cell_revision(
                    project_id,
                    section_id,
                    thread.table_cell_anchor,
                    thread.selected_text,
                )["selected_text"]
            else:
                resolved_selection, _ = self.normalize_revision_selection(
                    project_id,
                    section_id,
                    thread.selected_text,
                    thread.anchor_path,
                )
        except StaleRuntimeStateError:
            raise
        except (RuntimeStoreError, ValueError) as exc:
            raise RuntimeStoreError(
                "revision thread selected range is stale, ambiguous, or unavailable: "
                f"{exc}"
            ) from exc
        expected_selected_hash = RevisionThread.selected_text_hash(
            str(resolved_selection or "")
        )
        if not thread.selected_text and str(resolved_selection or ""):
            raise RuntimeStoreError(
                "revision thread selected text is no longer an exact blank greenfield target"
            )
        if thread.selected_hash != expected_selected_hash:
            raise StaleRuntimeStateError(
                "revision thread selected range hash does not match the authoritative working copy"
            )
        return current

    def _with_effective_document_binding(
        self, document: ProtocolDocument
    ) -> ProtocolDocument:
        if (
            document.source_study_definition_id
            and document.source_study_definition_revision is not None
            and document.source_study_definition_sha256
        ):
            return document.model_copy(deep=True)
        sidecar = self.runtime_store.medical_writing_document_binding_sidecar(
            document.project_id, document.document_id
        )
        if sidecar is None:
            return document.model_copy(deep=True)
        return document.model_copy(
            update={
                "source_study_definition_id": sidecar["definition_id"],
                "source_study_definition_revision": sidecar["definition_revision"],
                "source_study_definition_sha256": sidecar["definition_sha256"],
            },
            deep=True,
        )

    def _current_binding(self, project_id: str) -> tuple[str, Optional[int], str]:
        if self.study_consistency_service is None:
            document = self.project(project_id)
            if not (
                document.source_study_definition_id
                and document.source_study_definition_revision is not None
                and document.source_study_definition_sha256
            ):
                return "", None, ""
            return (
                document.source_study_definition_id,
                document.source_study_definition_revision,
                document.source_study_definition_sha256,
            )
        return self.study_consistency_service.current_definition_binding(project_id)

    def _require_authoritative_document_binding(self, project_id: str) -> None:
        if self.study_consistency_service is None:
            return
        document = self.project(project_id)
        definition_id, definition_revision, definition_sha256 = self._current_binding(
            project_id
        )
        if (
            document.source_study_definition_id != definition_id
            or document.source_study_definition_revision != definition_revision
            or document.source_study_definition_sha256 != definition_sha256
        ):
            state = self.study_consistency_service.status(project_id)
            raise RuntimeStoreError(
                "writing document is unbound or stale for the current StudyDefinition: "
                + (state.message or "binding mismatch")
            )

    def _working_copy_binding_failure(
        self,
        project_id: str,
        document: ProtocolDocument,
        working_copy: MedicalWritingWorkingCopy,
    ) -> str:
        try:
            self._validate_export_working_copy_identity(
                document, working_copy.section_id, working_copy
            )
            self._require_authoritative_document_binding(project_id)
            definition_id, definition_revision, definition_sha256 = self._current_binding(
                project_id
            )
        except RuntimeStoreError as exc:
            return str(exc)
        if working_copy.content_authority_state != "active_authoritative":
            return "legacy or explicitly quarantined working-copy revision"
        if (
            working_copy.source_study_definition_id != definition_id
            or working_copy.source_study_definition_revision != definition_revision
            or working_copy.source_study_definition_sha256 != definition_sha256
        ):
            return "working-copy StudyDefinition binding is missing, foreign, or stale"
        return ""

    def _baseline_working_copy(
        self,
        document: ProtocolDocument,
        section: Any,
        *,
        revision: int,
        created_by: str,
        updated_by: str,
        created_at: datetime,
        updated_at: datetime,
        authority_state: str,
        quarantined_revision: Optional[int],
        quarantine_reason: str,
    ) -> MedicalWritingWorkingCopy:
        return MedicalWritingWorkingCopy(
            working_copy_id=self._working_copy_id(
                document.project_id, document.document_id, section.section_id
            ),
            project_id=document.project_id,
            document_id=document.document_id,
            section_id=section.section_id,
            source_document_version=document.version,
            revision=revision,
            content_blocks=section.content_blocks,
            approval_state=ApprovalState.AI_DRAFT,
            approved_revision=None,
            approved_snapshot_id=None,
            source_study_definition_id=document.source_study_definition_id,
            source_study_definition_revision=document.source_study_definition_revision,
            source_study_definition_sha256=document.source_study_definition_sha256,
            content_authority_state=authority_state,
            quarantined_revision=quarantined_revision,
            quarantine_reason=quarantine_reason,
            created_by=created_by,
            updated_by=updated_by,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _working_copy_id(project_id: str, document_id: str, section_id: str) -> str:
        token = sha256(f"{project_id}:{document_id}:{section_id}".encode("utf-8")).hexdigest()[:20]
        return f"working_copy_{token}"

    @staticmethod
    def _payload_hash(payload: object) -> str:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(body.encode("utf-8")).hexdigest()

    def _lookup_idempotent_replay_with_legacy(
        self,
        project_id: str,
        operation: str,
        idempotency_key: str,
        request_fingerprint: str,
        legacy_semantic_request: object,
    ):
        """Read a v2 replay while accepting the exact pre-hash contract once.

        ``selected_hash`` is additive, but existing explicit idempotency keys
        may point at a pre-upgrade fingerprint.  The fallback is only entered
        after the current fingerprint conflicts and still requires the old
        semantic payload to match exactly; unrelated key reuse remains a hard
        conflict.  New writes always persist the current fingerprint.
        """
        try:
            return self.runtime_store.lookup_idempotent_replay(
                project_id,
                operation,
                idempotency_key,
                request_fingerprint,
            )
        except IdempotencyConflictError as current_error:
            legacy_fingerprint = self._payload_hash(legacy_semantic_request)
            try:
                legacy_replay = self.runtime_store.lookup_idempotent_replay(
                    project_id,
                    operation,
                    idempotency_key,
                    legacy_fingerprint,
                )
            except IdempotencyConflictError:
                raise current_error
            if legacy_replay is not None:
                return legacy_replay
            raise current_error

    @staticmethod
    def _rich_text_plain_text(node: Any, depth: int = 0) -> str:
        if depth > 12 or not isinstance(node, dict):
            raise ValueError("working copy rich text structure is invalid")
        node_type = node.get("type")
        allowed_types = {
            "doc",
            "paragraph",
            "heading",
            "bulletList",
            "orderedList",
            "listItem",
            "text",
            "hardBreak",
        }
        if node_type not in allowed_types:
            raise ValueError(f"working copy rich text node is not allowed: {node_type}")
        if node_type == "text":
            if set(node) - {"type", "text", "marks"}:
                raise ValueError("working copy rich text text-node fields are invalid")
            text = node.get("text")
            if not isinstance(text, str):
                raise ValueError("working copy rich text text value is invalid")
            marks = node.get("marks", [])
            if not isinstance(marks, list):
                raise ValueError("working copy rich text marks are invalid")
            mark_types = []
            for mark in marks:
                MedicalWritingRuntimeRepository._validate_rich_text_mark(mark)
                mark_types.append(mark["type"])
            if len(mark_types) != len(set(mark_types)):
                raise ValueError("working copy rich text marks must be unique")
            if {"superscript", "subscript"}.issubset(mark_types):
                raise ValueError("working copy rich text cannot be superscript and subscript")
            return text
        if node_type == "hardBreak":
            if set(node) != {"type"}:
                raise ValueError("working copy rich text hard-break fields are invalid")
            return "\n"
        allowed_fields = {"type", "content"}
        if node_type in {"paragraph", "heading", "orderedList"}:
            allowed_fields.add("attrs")
        if set(node) - allowed_fields:
            raise ValueError("working copy rich text container fields are invalid")
        attrs = node.get("attrs")
        if node_type in {"paragraph", "heading"}:
            MedicalWritingRuntimeRepository._validate_rich_text_paragraph_attrs(
                attrs,
                heading=node_type == "heading",
            )
        if node_type == "orderedList" and attrs is not None and (
            not isinstance(attrs, dict)
            or set(attrs) - {"start"}
            or not isinstance(attrs.get("start", 1), int)
        ):
            raise ValueError("working copy rich text ordered-list attributes are invalid")
        content = node.get("content", [])
        if not isinstance(content, list):
            raise ValueError("working copy rich text content is invalid")
        child_text = [
            MedicalWritingRuntimeRepository._rich_text_plain_text(child, depth + 1)
            for child in content
        ]
        return "\n".join(child_text) if node_type == "doc" else "".join(child_text)

    @staticmethod
    def _validate_rich_text_paragraph_attrs(attrs: Any, *, heading: bool) -> None:
        if attrs is None:
            if heading:
                raise ValueError("working copy rich text heading level is invalid")
            return
        if not isinstance(attrs, dict):
            raise ValueError("working copy rich text paragraph attributes are invalid")
        allowed = set(MedicalWritingRuntimeRepository._RICH_TEXT_PARAGRAPH_ATTRS)
        if heading:
            allowed.add("level")
        if set(attrs) - allowed:
            raise ValueError("working copy rich text paragraph attributes are invalid")
        if heading and attrs.get("level") not in {1, 2, 3, 4, 5, 6}:
            raise ValueError("working copy rich text heading level is invalid")
        style_preset = attrs.get("stylePreset")
        if style_preset is not None and style_preset not in MedicalWritingRuntimeRepository._RICH_TEXT_STYLE_PRESETS:
            raise ValueError("working copy rich text style preset is invalid")
        text_align = attrs.get("textAlign")
        if text_align is not None and text_align not in {"left", "center", "right", "justify"}:
            raise ValueError("working copy rich text alignment is invalid")
        numeric_ranges = {
            "lineHeight": (0.8, 3.0),
            "spacingBeforePt": (0.0, 72.0),
            "spacingAfterPt": (0.0, 72.0),
            "leftIndentChars": (0.0, 20.0),
            "rightIndentChars": (0.0, 20.0),
            "firstLineIndentChars": (-10.0, 20.0),
        }
        for key, (minimum, maximum) in numeric_ranges.items():
            value = attrs.get(key)
            if value is None:
                continue
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < minimum
                or value > maximum
            ):
                raise ValueError(f"working copy rich text {key} is invalid")

    @staticmethod
    def _validate_rich_text_mark(mark: Any) -> None:
        if not isinstance(mark, dict):
            raise ValueError("working copy rich text marks are invalid")
        mark_type = mark.get("type")
        if mark_type not in MedicalWritingRuntimeRepository._RICH_TEXT_MARKS:
            raise ValueError("working copy rich text marks are invalid")
        if mark_type in {"bold", "italic", "underline", "superscript", "subscript"}:
            if set(mark) != {"type"}:
                raise ValueError("working copy rich text marks are invalid")
            return
        if set(mark) != {"type", "attrs"} or not isinstance(mark.get("attrs"), dict):
            raise ValueError("working copy rich text marks are invalid")
        attrs = mark["attrs"]
        if mark_type == "highlight":
            if set(attrs) != {"color"} or not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(attrs.get("color") or "")):
                raise ValueError("working copy rich text highlight is invalid")
            return
        if mark_type == "citation":
            if set(attrs) == {"referenceId"}:
                reference_ids = [attrs.get("referenceId")]
            elif set(attrs) == {"referenceIds"} and isinstance(attrs.get("referenceIds"), list):
                reference_ids = attrs["referenceIds"]
            else:
                raise ValueError("working copy rich text citation is invalid")
            if (
                not 1 <= len(reference_ids) <= 50
                or len(set(reference_ids)) != len(reference_ids)
                or any(
                    not isinstance(reference_id, str)
                    or not re.fullmatch(r"mwref_[0-9a-f]{20}", reference_id)
                    for reference_id in reference_ids
                )
            ):
                raise ValueError("working copy rich text citation is invalid")
            return
        if mark_type == "crossReference":
            if set(attrs) != {"targetKind", "targetId"}:
                raise ValueError("working copy rich text cross-reference is invalid")
            target_kind = attrs.get("targetKind")
            target_id = attrs.get("targetId")
            if (
                target_kind not in {"table", "figure"}
                or not isinstance(target_id, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,127}", target_id)
            ):
                raise ValueError("working copy rich text cross-reference is invalid")
            return
        if set(attrs) - {"fontFamily", "fontSize", "color"}:
            raise ValueError("working copy rich text text style is invalid")
        font_family = attrs.get("fontFamily")
        if font_family is not None and (
            not isinstance(font_family, str)
            or not font_family.strip()
            or len(font_family.strip()) > 80
        ):
            raise ValueError("working copy rich text font family is invalid")
        font_size = attrs.get("fontSize")
        if font_size is not None:
            match = re.fullmatch(r"(\d+(?:\.\d+)?)pt", str(font_size).strip())
            if not match or not 6 <= float(match.group(1)) <= 72:
                raise ValueError("working copy rich text font size is invalid")
        color = attrs.get("color")
        if color is not None and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(color)):
            raise ValueError("working copy rich text color is invalid")

    @staticmethod
    def _rich_text_cross_reference_signatures(rich_text: Any) -> Counter[tuple[str, str]]:
        """Collect structured table/figure marks for a fail-closed apply check."""

        signatures: Counter[tuple[str, str]] = Counter()

        def visit(node: Any) -> None:
            if not isinstance(node, dict):
                return
            if node.get("type") == "text":
                for mark in node.get("marks", []) or []:
                    if not isinstance(mark, dict) or mark.get("type") != "crossReference":
                        continue
                    attrs = mark.get("attrs")
                    if isinstance(attrs, dict):
                        target_kind = attrs.get("targetKind")
                        target_id = attrs.get("targetId")
                        if isinstance(target_kind, str) and isinstance(target_id, str):
                            signatures[(target_kind, target_id)] += 1
                return
            for key, value in node.items():
                if key in {"marks", "attrs"}:
                    continue
                if isinstance(value, dict):
                    visit(value)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)

        visit(rich_text)
        return signatures

    @classmethod
    def _assert_cross_reference_marks_preserved(
        cls,
        source_block: Mapping[str, Any],
        updated_block: Mapping[str, Any],
    ) -> None:
        source_marks = cls._rich_text_cross_reference_signatures(
            source_block.get("rich_text")
        )
        if not source_marks:
            return
        updated_marks = cls._rich_text_cross_reference_signatures(
            updated_block.get("rich_text")
        )
        for signature, count in source_marks.items():
            if updated_marks[signature] < count:
                target_kind, target_id = signature
                raise RuntimeStoreError(
                    "approved revision removed a protected structured "
                    f"{target_kind} cross-reference mark: {target_id}"
                )

    @staticmethod
    def _proposal_numeric_citation_occurrences(
        proposal_text: str,
    ) -> list[tuple[str, tuple[int, ...], int, int]]:
        pattern = re.compile(
            r"[\[［]\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?"
            r"(?:\s*[,，]\s*\d{1,4}(?:\s*[-‐‑‒–—]\s*\d{1,4})?)*\s*[\]］]"
        )
        occurrences: list[tuple[str, tuple[int, ...], int, int]] = []
        for match in pattern.finditer(proposal_text):
            marker = match.group(0)
            numbers = parse_legacy_reference_marker(
                unicodedata.normalize("NFKC", marker)
            )
            if numbers:
                occurrences.append((marker, numbers, match.start(), match.end()))
        return occurrences

    def _accepted_revision_citation_bindings(
        self,
        project_id: str,
        thread: RevisionThread,
        suggestion: Any,
    ) -> list[dict[str, Any]]:
        occurrences = self._proposal_numeric_citation_occurrences(
            suggestion.proposal_text
        )
        if not occurrences:
            return []
        acceptance_events = [
            event
            for event in self.runtime_store.workflow_audit_events(
                project_id, "medical_writing_revision"
            )
            if event.action == "medical_writing_revision_accept"
            and event.target_id == thread.thread_id
            and event.detail.get("suggestion_id") == suggestion.suggestion_id
        ]
        if len(acceptance_events) != 1:
            raise RuntimeStoreError(
                "AI citation application requires one immutable candidate-acceptance audit"
            )
        bindings = acceptance_events[0].detail.get("citation_bindings")
        candidate = {
            "proposal_text": suggestion.proposal_text,
            "citation_bindings": bindings,
        }
        errors = validate_medical_writing_candidate_citations(
            {"revision": {**candidate, "alternatives": []}},
            self.project_reference_ids(project_id),
        )
        if errors:
            raise RuntimeStoreError(
                "AI citation references are not valid for the current project: "
                + "; ".join(errors)
            )
        return json.loads(json.dumps(bindings, ensure_ascii=False))

    @staticmethod
    def _citation_replacement_fragments(
        proposal_text: str,
        citation_bindings: list[dict[str, Any]],
        inherited_marks: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        occurrences = MedicalWritingRuntimeRepository._proposal_numeric_citation_occurrences(
            proposal_text
        )
        if len(occurrences) != len(citation_bindings):
            raise RuntimeStoreError(
                "AI citation marker count changed after candidate acceptance"
            )
        base_marks = [
            json.loads(json.dumps(mark, ensure_ascii=False))
            for mark in inherited_marks
            if mark.get("type") not in {"citation", "crossReference"}
        ]
        display_parts: list[str] = []
        nodes: list[dict[str, Any]] = []
        cursor = 0

        def append_text(value: str, marks: list[dict[str, Any]]) -> None:
            if not value:
                return
            node: dict[str, Any] = {"type": "text", "text": value}
            if marks:
                node["marks"] = json.loads(json.dumps(marks, ensure_ascii=False))
            nodes.append(node)

        for index, (_, _, start, end) in enumerate(occurrences):
            plain = proposal_text[cursor:start]
            append_text(plain, base_marks)
            display_parts.append(plain)
            reference_ids = citation_bindings[index]["reference_ids"]
            citation_mark = {
                "type": "citation",
                "attrs": (
                    {"referenceId": reference_ids[0]}
                    if len(reference_ids) == 1
                    else {"referenceIds": list(reference_ids)}
                ),
            }
            placeholder = "[#]"
            append_text(placeholder, [*base_marks, citation_mark])
            display_parts.append(placeholder)
            cursor = end
        tail = proposal_text[cursor:]
        append_text(tail, base_marks)
        display_parts.append(tail)
        return "".join(display_parts), nodes

    @staticmethod
    def _replace_in_rich_text_with_citations(
        rich_text: dict,
        selected_text: str,
        proposal_text: str,
        citation_bindings: list[dict[str, Any]],
    ) -> tuple[str, dict]:
        if "\n" in proposal_text or "\r" in proposal_text:
            raise RuntimeStoreError(
                "AI citation application does not support structural paragraph replacement"
            )
        if not selected_text:
            raw_replacement = (
                MedicalWritingRuntimeRepository._replace_table_cell_rich_text(
                    rich_text,
                    "",
                    proposal_text,
                )
            )
            return MedicalWritingRuntimeRepository._replace_in_rich_text_with_citations(
                raw_replacement,
                proposal_text,
                proposal_text,
                citation_bindings,
            )

        updated = json.loads(json.dumps(rich_text, ensure_ascii=False))
        segments: list[dict[str, Any]] = []
        plain_parts: list[str] = []
        offset = 0

        def visit(node: Any, parent: dict | None = None, depth: int = 0) -> None:
            nonlocal offset
            if depth > 12 or not isinstance(node, dict):
                raise RuntimeStoreError("working copy rich text structure is invalid")
            # ``_rich_text_plain_text`` exposes document-level paragraph
            # boundaries as newlines.  Keep the same coordinate space here so
            # a selection in one paragraph can be replaced while a separate
            # paragraph in the same block remains intact.  The separator is
            # structural, therefore any selection crossing it still fails
            # closed below.
            if node.get("type") == "doc":
                content = node.get("content", [])
                if not isinstance(content, list):
                    raise RuntimeStoreError("working copy rich text structure is invalid")
                for index, child in enumerate(content):
                    if index:
                        segments.append(
                            {
                                "node": {"type": "hardBreak"},
                                "parent": node,
                                "start": offset,
                                "end": offset + 1,
                                "structural": True,
                            }
                        )
                        plain_parts.append("\n")
                        offset += 1
                    visit(child, node, depth + 1)
                return
            if node.get("type") == "text":
                text = node.get("text")
                if not isinstance(text, str) or parent is None:
                    raise RuntimeStoreError("working copy rich text structure is invalid")
                segments.append(
                    {
                        "node": node,
                        "parent": parent,
                        "start": offset,
                        "end": offset + len(text),
                        "structural": False,
                    }
                )
                plain_parts.append(text)
                offset += len(text)
                return
            if node.get("type") == "hardBreak":
                segments.append(
                    {
                        "node": node,
                        "parent": parent,
                        "start": offset,
                        "end": offset + 1,
                        "structural": True,
                    }
                )
                plain_parts.append("\n")
                offset += 1
                return
            for child in node.get("content", []):
                visit(child, node, depth + 1)

        visit(updated)
        plain_text = "".join(plain_parts)
        if plain_text.count(selected_text) != 1:
            raise RuntimeStoreError(
                "approved selected text is not uniquely mergeable in rich text"
            )
        selection_start = plain_text.index(selected_text)
        selection_end = selection_start + len(selected_text)
        overlapping = [
            segment
            for segment in segments
            if segment["end"] > selection_start
            and segment["start"] < selection_end
        ]
        if not overlapping or any(segment["structural"] for segment in overlapping):
            raise RuntimeStoreError(
                "approved citation target crosses an unsupported rich-text structural break"
            )
        parents = {id(segment["parent"]) for segment in overlapping}
        if len(parents) != 1:
            raise RuntimeStoreError(
                "approved citation target spans unsupported rich-text containers"
            )
        parent = overlapping[0]["parent"]
        content = parent.get("content")
        if not isinstance(content, list):
            raise RuntimeStoreError("working copy rich text structure is invalid")
        indexes = [content.index(segment["node"]) for segment in overlapping]
        if indexes != list(range(indexes[0], indexes[-1] + 1)):
            raise RuntimeStoreError(
                "approved citation target spans unsupported rich-text siblings"
            )
        first_segment = overlapping[0]
        last_segment = overlapping[-1]
        first_node = first_segment["node"]
        last_node = last_segment["node"]
        prefix = first_node["text"][: selection_start - first_segment["start"]]
        suffix = last_node["text"][selection_end - last_segment["start"] :]
        inherited_marks = first_node.get("marks", [])
        proposal_display, replacement_nodes = (
            MedicalWritingRuntimeRepository._citation_replacement_fragments(
                proposal_text,
                citation_bindings,
                inherited_marks,
            )
        )
        prefix_nodes: list[dict[str, Any]] = []
        suffix_nodes: list[dict[str, Any]] = []
        if prefix:
            prefix_node = {"type": "text", "text": prefix}
            if inherited_marks:
                prefix_node["marks"] = json.loads(
                    json.dumps(inherited_marks, ensure_ascii=False)
                )
            prefix_nodes.append(prefix_node)
        if suffix:
            suffix_node = {"type": "text", "text": suffix}
            suffix_marks = last_node.get("marks", [])
            if suffix_marks:
                suffix_node["marks"] = json.loads(
                    json.dumps(suffix_marks, ensure_ascii=False)
                )
            suffix_nodes.append(suffix_node)
        parent["content"] = [
            *content[: indexes[0]],
            *prefix_nodes,
            *replacement_nodes,
            *suffix_nodes,
            *content[indexes[-1] + 1 :],
        ]
        expected = (
            plain_text[:selection_start]
            + proposal_display
            + plain_text[selection_end:]
        )
        if MedicalWritingRuntimeRepository._rich_text_plain_text(updated) != expected:
            raise RuntimeStoreError(
                "approved citation replacement did not preserve the expected text"
            )
        return proposal_display, updated

    @staticmethod
    def _replace_in_rich_text(
        rich_text: dict,
        selected_text: str,
        proposal_text: str,
    ) -> dict:
        updated = json.loads(json.dumps(rich_text, ensure_ascii=False))
        segments: List[dict] = []
        plain_parts: List[str] = []
        offset = 0

        def visit(node: Any, depth: int = 0) -> None:
            nonlocal offset
            if depth > 12 or not isinstance(node, dict):
                raise RuntimeStoreError("working copy rich text structure is invalid")
            # Match the document-level newline semantics used by
            # ``_rich_text_plain_text``.  Paragraph separators are structural
            # and are rejected when a requested selection spans them.
            if node.get("type") == "doc":
                content = node.get("content", [])
                if not isinstance(content, list):
                    raise RuntimeStoreError("working copy rich text structure is invalid")
                for index, child in enumerate(content):
                    if index:
                        segments.append(
                            {
                                "node": {"type": "hardBreak"},
                                "start": offset,
                                "end": offset + 1,
                                "structural": True,
                            }
                        )
                        plain_parts.append("\n")
                        offset += 1
                    visit(child, depth + 1)
                return
            if node.get("type") == "text":
                text = node.get("text")
                if not isinstance(text, str):
                    raise RuntimeStoreError("working copy rich text structure is invalid")
                segments.append(
                    {
                        "node": node,
                        "start": offset,
                        "end": offset + len(text),
                        "structural": False,
                    }
                )
                plain_parts.append(text)
                offset += len(text)
                return
            if node.get("type") == "hardBreak":
                segments.append(
                    {
                        "node": node,
                        "start": offset,
                        "end": offset + 1,
                        "structural": True,
                    }
                )
                plain_parts.append("\n")
                offset += 1
                return
            for child in node.get("content", []):
                visit(child, depth + 1)

        visit(updated)
        plain_text = "".join(plain_parts)
        if not selected_text or plain_text.count(selected_text) != 1:
            raise RuntimeStoreError(
                "approved selected text is not uniquely mergeable in rich text"
            )
        selection_start = plain_text.index(selected_text)
        selection_end = selection_start + len(selected_text)
        overlapping_segments = [
            segment
            for segment in segments
            if segment["end"] > selection_start
            and segment["start"] < selection_end
        ]
        if not overlapping_segments or any(
            segment["structural"] for segment in overlapping_segments
        ):
            raise RuntimeStoreError(
                "approved selected text crosses an unsupported rich-text structural break"
            )
        affected_nodes = [segment["node"] for segment in overlapping_segments]
        first_segment = overlapping_segments[0]
        last_segment = overlapping_segments[-1]
        first_node = first_segment["node"]
        last_node = last_segment["node"]
        first_text = first_node["text"]
        last_text = last_node["text"]
        prefix = first_text[: selection_start - first_segment["start"]]
        suffix = last_text[selection_end - last_segment["start"] :]
        if first_node is last_node:
            first_node["text"] = prefix + proposal_text + suffix
        else:
            first_node["text"] = prefix + proposal_text
            for node in affected_nodes[1:-1]:
                node["text"] = ""
            last_node["text"] = suffix

        def prune_empty_text_nodes(node: Any, depth: int = 0) -> None:
            if depth > 12 or not isinstance(node, dict):
                raise RuntimeStoreError("working copy rich text structure is invalid")
            content = node.get("content")
            if not isinstance(content, list):
                return
            retained: List[dict] = []
            for child in content:
                if not isinstance(child, dict):
                    raise RuntimeStoreError("working copy rich text structure is invalid")
                prune_empty_text_nodes(child, depth + 1)
                if child.get("type") == "text" and child.get("text") == "":
                    continue
                retained.append(child)
            node["content"] = retained

        prune_empty_text_nodes(updated)
        if MedicalWritingRuntimeRepository._rich_text_plain_text(updated) != (
            plain_text[:selection_start] + proposal_text + plain_text[selection_end:]
        ):
            raise RuntimeStoreError(
                "approved rich-text replacement did not preserve the expected text"
            )
        return updated

    @staticmethod
    def _replace_table_cell_rich_text(
        rich_text: dict,
        selected_text: str,
        proposal_text: str,
    ) -> dict:
        try:
            return MedicalWritingRuntimeRepository._replace_in_rich_text(
                rich_text,
                selected_text,
                proposal_text,
            )
        except RuntimeStoreError:
            pass

        source = json.loads(json.dumps(rich_text, ensure_ascii=False))
        paragraph_templates = (
            [source]
            if source.get("type") in {"paragraph", "heading"}
            else [
                child
                for child in source.get("content", [])
                if isinstance(child, dict)
                and child.get("type") in {"paragraph", "heading"}
            ]
        )
        template = paragraph_templates[0] if paragraph_templates else {"type": "paragraph"}

        def uniform_marks(node: dict) -> list[dict]:
            values: list[list[dict]] = []

            def visit(candidate: Any) -> None:
                if not isinstance(candidate, dict):
                    return
                if candidate.get("type") == "text":
                    values.append(candidate.get("marks", []))
                    return
                for child in candidate.get("content", []):
                    visit(child)

            visit(node)
            if not values or any(value != values[0] for value in values[1:]):
                return []
            return json.loads(json.dumps(values[0], ensure_ascii=False))

        marks = uniform_marks(source)
        paragraphs: list[dict] = []
        for index, line in enumerate(proposal_text.split("\n")):
            base = paragraph_templates[min(index, len(paragraph_templates) - 1)] if paragraph_templates else template
            paragraph = {
                key: json.loads(json.dumps(value, ensure_ascii=False))
                for key, value in base.items()
                if key in {"type", "attrs"}
            }
            paragraph.setdefault("type", "paragraph")
            paragraph["content"] = []
            if line:
                text_node: dict[str, Any] = {"type": "text", "text": line}
                if marks:
                    text_node["marks"] = json.loads(json.dumps(marks, ensure_ascii=False))
                paragraph["content"].append(text_node)
            paragraphs.append(paragraph)
        if len(paragraphs) == 1 and source.get("type") in {"paragraph", "heading"}:
            return paragraphs[0]
        return {"type": "doc", "content": paragraphs}

    @staticmethod
    def _hydrate_legacy_working_copy_formatting(
        source_blocks: List[dict],
        candidate_blocks: List[dict],
    ) -> List[dict]:
        source_by_id = {str(block.get("block_id", "")): block for block in source_blocks}
        source_by_locator = {
            str(block.get("source_locator", "")): block
            for block in source_blocks
            if block.get("source_locator")
        }
        hydrated = json.loads(json.dumps(candidate_blocks, ensure_ascii=False))
        for block in hydrated:
            source = source_by_id.get(str(block.get("block_id", "")))
            if not isinstance(source, dict) and block.get("source_locator"):
                source = source_by_locator.get(str(block.get("source_locator", "")))
            if not isinstance(source, dict):
                continue
            mutable_block_fields = (
                {
                    "rows",
                    "header_row_count",
                    "column_count",
                    "title",
                    "structured_table",
                    "table_caption",
                }
                if block.get("block_type") == "table"
                else {"text", "rich_text"}
            )
            for field, value in source.items():
                if field not in mutable_block_fields and field not in block:
                    block[field] = json.loads(json.dumps(value, ensure_ascii=False))

            if block.get("block_type") == "table":
                source_table = source.get("structured_table")
                candidate_table = block.get("structured_table")
                if isinstance(source_table, dict) and isinstance(candidate_table, dict):
                    source_role = str(source_table.get("role") or "").strip()
                    candidate_role = str(candidate_table.get("role") or "").strip()
                    if (
                        source_role
                        and source_role != "unclassified"
                        and candidate_role in {"", "unclassified"}
                    ):
                        candidate_table["role"] = source_role
                source_cells = {
                    str(cell.get("cell_id", "")): cell
                    for row in source.get("rows", [])
                    if isinstance(row, list)
                    for cell in row
                    if isinstance(cell, dict) and cell.get("cell_id")
                }
                for row in block.get("rows", []):
                    if not isinstance(row, list):
                        continue
                    for cell in row:
                        if not isinstance(cell, dict):
                            continue
                        source_cell = source_cells.get(str(cell.get("cell_id", "")))
                        if not isinstance(source_cell, dict):
                            continue
                        for field, value in source_cell.items():
                            if field not in {"text", "rich_text"} and field not in cell:
                                cell[field] = json.loads(json.dumps(value, ensure_ascii=False))
                        source_rich_text = source_cell.get("rich_text")
                        if "rich_text" in cell or not isinstance(source_rich_text, dict):
                            continue
                        if cell.get("text", "") == source_cell.get("text", ""):
                            cell["rich_text"] = json.loads(
                                json.dumps(source_rich_text, ensure_ascii=False)
                            )
                        else:
                            cell["rich_text"] = (
                                MedicalWritingRuntimeRepository._replace_table_cell_rich_text(
                                    source_rich_text,
                                    str(source_cell.get("text", "")),
                                    str(cell.get("text", "")),
                                )
                            )
                continue

            if "rich_text" in block:
                continue
            source_rich_text = source.get("rich_text")
            if not isinstance(source_rich_text, dict):
                continue
            if block.get("text", "") == source.get("text", ""):
                block["rich_text"] = json.loads(
                    json.dumps(source_rich_text, ensure_ascii=False)
                )
                continue
            source_type = source_rich_text.get("type")
            node_type = source_type if source_type in {"paragraph", "heading"} else "paragraph"
            rich_text: dict = {"type": node_type}
            attrs = source_rich_text.get("attrs")
            if isinstance(attrs, dict):
                rich_text["attrs"] = json.loads(json.dumps(attrs, ensure_ascii=False))
            text = str(block.get("text", ""))
            if text:
                rich_text["content"] = [{"type": "text", "text": text}]
            block["rich_text"] = rich_text
        return hydrated

    @staticmethod
    def _validate_working_copy_blocks(
        source_blocks: List[dict],
        candidate_blocks: List[dict],
        *,
        existing_blocks: Optional[List[dict]] = None,
        authorized_generated_blocks: Optional[Mapping[str, dict]] = None,
        authorized_removed_appendix_block_ids: Optional[set[str]] = None,
    ) -> None:
        if not candidate_blocks:
            raise ValueError("working copy must contain at least one source-linked block")
        source_by_id = {str(block.get("block_id", "")): block for block in source_blocks}
        candidate_ids = [str(block.get("block_id", "")) for block in candidate_blocks]
        if not all(candidate_ids) or len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("working copy block ids must be present and unique")
        missing_source_ids = set(source_by_id) - set(candidate_ids)
        if missing_source_ids:
            raise ValueError("working copy must preserve every canonical source block")
        source_order = [
            block_id for block_id in candidate_ids if block_id in source_by_id
        ]
        if source_order != list(source_by_id):
            raise ValueError("working copy must preserve canonical source block order")
        source_table_ids = {
            str(block.get("table_id", ""))
            for block in source_blocks
            if block.get("block_type") == "table"
        }
        generated_table_ids: set[str] = set()
        existing_by_id = {
            str(block.get("block_id", "")): block
            for block in (existing_blocks or [])
            if str(block.get("block_id", ""))
        }
        authorized_by_id = dict(authorized_generated_blocks or {})
        existing_figure_ids = {
            block_id
            for block_id, block in existing_by_id.items()
            if block.get("block_type") == "figure"
            and block.get("figure_kind") == "study_schema"
        }
        existing_appendix_image_ids = {
            block_id
            for block_id, block in existing_by_id.items()
            if block.get("block_type") == "appendix_image"
            and block.get("attachment_kind") == "assessment_instrument_page"
        }
        authorized_removed_appendix_ids = set(
            authorized_removed_appendix_block_ids or set()
        )
        if not authorized_removed_appendix_ids.issubset(
            existing_appendix_image_ids
        ):
            raise ValueError(
                "only existing assessment-instrument appendix pages may be removed by the server projection endpoint"
            )
        existing_intervention_projection_ids = {
            block_id
            for block_id, block in existing_by_id.items()
            if block.get("block_type") == "paragraph"
            and block.get("source_kind") == "medical_writing_intervention_rules"
        }
        missing_server_projected_ids = (
            existing_figure_ids
            | existing_appendix_image_ids
            | existing_intervention_projection_ids
        ) - set(candidate_ids) - authorized_removed_appendix_ids
        if missing_server_projected_ids:
            raise ValueError(
                "working copy must preserve every server-projected block"
            )
        for block in candidate_blocks:
            block_id = str(block["block_id"])
            source = source_by_id.get(block_id)
            if source is None:
                if block.get("block_type") == "table":
                    MedicalWritingRuntimeRepository._validate_generated_table_block(
                        block,
                        source_table_ids=source_table_ids,
                        generated_table_ids=generated_table_ids,
                    )
                    generated_table_ids.add(str(block["table_id"]))
                elif block.get("block_type") == "figure":
                    MedicalWritingRuntimeRepository._validate_generated_figure_block(block)
                    authorized = authorized_by_id.get(block_id)
                    if authorized is not None:
                        if block != authorized:
                            raise ValueError(
                                "authorized study-schema figure differs from the server projection"
                            )
                    elif existing_by_id.get(block_id) != block:
                        raise ValueError(
                            "study-schema figures may only be created or updated by the server projection endpoint"
                        )
                elif block.get("block_type") == "appendix_image":
                    MedicalWritingRuntimeRepository._validate_generated_appendix_image_block(
                        block
                    )
                    authorized = authorized_by_id.get(block_id)
                    if authorized is not None:
                        if block != authorized:
                            raise ValueError(
                                "authorized assessment-instrument appendix page differs from the server projection"
                            )
                    elif existing_by_id.get(block_id) != block:
                        raise ValueError(
                            "assessment-instrument appendix pages may only be created or updated by the server projection endpoint"
                        )
                elif (
                    block.get("block_type") == "paragraph"
                    and block.get("source_kind")
                    == "medical_writing_intervention_rules"
                ):
                    MedicalWritingRuntimeRepository._validate_generated_intervention_rules_block(
                        block
                    )
                    authorized = authorized_by_id.get(block_id)
                    existing = existing_by_id.get(block_id)
                    if authorized is not None:
                        if sha256(str(block.get("text", "")).encode("utf-8")).hexdigest() != block.get(
                            "projected_text_sha256"
                        ):
                            raise ValueError(
                                "authorized intervention-rules projected text hash does not match"
                            )
                        projected_content_hash = sha256(
                            json.dumps(
                                {
                                    "text": str(block.get("text", "")),
                                    "rich_text": block.get("rich_text"),
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        if projected_content_hash != block.get(
                            "projected_content_sha256"
                        ):
                            raise ValueError(
                                "authorized intervention-rules projected content hash does not match"
                            )
                        if block != authorized:
                            raise ValueError(
                                "authorized intervention-rules block differs from the server projection"
                            )
                    elif existing is None:
                        raise ValueError(
                            "intervention-rules paragraphs may only be created by the server projection endpoint"
                        )
                    else:
                        MedicalWritingRuntimeRepository._validate_generated_intervention_rules_edit(
                            existing,
                            block,
                        )
                else:
                    raise ValueError(
                        "only governed structured tables, study-schema figures, assessment-instrument appendix pages, or intervention-rules paragraphs may be added"
                    )
                continue
            structured_table = block.get("structured_table")
            has_structured_table = (
                block.get("block_type") == "table" and isinstance(structured_table, dict)
            )
            allowed_extra_fields = (
                {"structured_table"}
                if block.get("block_type") == "table"
                else {"rich_text"}
            )
            if not set(source).issubset(block) or set(block) - set(source) - allowed_extra_fields:
                raise ValueError("working copy must preserve canonical source block fields")
            mutable_fields = (
                {
                    "rows",
                    "header_row_count",
                    "column_count",
                    "title",
                    "structured_table",
                    "table_caption",
                }
                if has_structured_table
                else {"rows"}
                if block.get("block_type") == "table"
                else {"text", "rich_text"}
            )
            for field in set(source) - mutable_fields:
                if block.get(field) != source.get(field):
                    raise ValueError(f"working copy may not change source-linked {field}")
            if has_structured_table:
                MedicalWritingRuntimeRepository._validate_table_caption_review_change(
                    source.get("table_caption"),
                    block.get("table_caption"),
                )
                source_structure = source.get("structured_table")
                if isinstance(source_structure, dict):
                    MedicalWritingRuntimeRepository._validate_table_caption_review_change(
                        source_structure.get("source_caption"),
                        structured_table.get("source_caption"),
                    )
                    MedicalWritingRuntimeRepository._validate_source_note_metadata_review_changes(
                        source_structure.get("source_note_metadata"),
                        structured_table.get("source_note_metadata"),
                    )
            if block.get("block_type") != "table" and "rich_text" in block:
                if len(json.dumps(block["rich_text"], ensure_ascii=False)) > 100_000:
                    raise ValueError("working copy rich text block is too large")
                rich_text = block["rich_text"]
                if not isinstance(rich_text, dict) or rich_text.get("type") not in {
                    "doc",
                    "paragraph",
                    "heading",
                    "bulletList",
                    "orderedList",
                }:
                    raise ValueError("working copy rich text root is invalid")
                if MedicalWritingRuntimeRepository._rich_text_plain_text(rich_text) != block.get("text", ""):
                    raise ValueError("working copy rich text must match block text")
            if block.get("block_type") == "table":
                if has_structured_table:
                    from .medical_writing_tables import MedicalWritingTableService

                    table = MedicalWritingTableService().from_table_block(block)
                    MedicalWritingRuntimeRepository._validate_table_dual_representation(
                        block,
                        table,
                    )
                    if table.block_id != block["block_id"] or table.table_id != source["table_id"]:
                        raise ValueError("working copy structured table identity is inconsistent")
                    continue
                source_rows = source.get("rows", [])
                candidate_rows = block.get("rows", [])
                if len(candidate_rows) != len(source_rows):
                    raise ValueError("working copy table must preserve canonical row structure")
                for source_row, candidate_row in zip(source_rows, candidate_rows):
                    if len(candidate_row) != len(source_row):
                        raise ValueError("working copy table must preserve canonical cell structure")
                    for source_cell, candidate_cell in zip(source_row, candidate_row):
                        if set(candidate_cell) != set(source_cell):
                            raise ValueError(
                                "working copy table cell must preserve canonical source fields"
                            )
                        for field in set(source_cell) - {"text", "rich_text"}:
                            if candidate_cell.get(field) != source_cell.get(field):
                                raise ValueError(
                                    f"working copy may not change source-linked table {field}"
                                )
                        rich_text = candidate_cell.get("rich_text")
                        if rich_text is not None:
                            if not isinstance(rich_text, dict):
                                raise ValueError("working copy table rich text is invalid")
                            if (
                                MedicalWritingRuntimeRepository._table_cell_rich_text_plain_text(
                                    rich_text
                                )
                                != str(candidate_cell.get("text", ""))
                            ):
                                raise ValueError(
                                    "working copy table rich text must match cell text"
                                )

    @staticmethod
    def _table_cell_rich_text_plain_text(rich_text: dict) -> str:
        if rich_text.get("type") != "doc":
            return MedicalWritingRuntimeRepository._rich_text_plain_text(rich_text)
        content = rich_text.get("content", [])
        if not isinstance(content, list):
            raise ValueError("working copy table rich text content is invalid")
        return "\n".join(
            MedicalWritingRuntimeRepository._rich_text_plain_text(child)
            for child in content
        )

    @staticmethod
    def _validate_table_caption_review_change(
        source_caption: Any,
        candidate_caption: Any,
    ) -> None:
        if source_caption is None and candidate_caption is None:
            return
        if not isinstance(source_caption, dict) or not isinstance(candidate_caption, dict):
            raise ValueError("working copy must preserve source-linked table caption")
        if set(source_caption) != set(candidate_caption):
            raise ValueError("working copy must preserve source-linked table caption fields")
        for field in set(source_caption) - {"review_status"}:
            if candidate_caption.get(field) != source_caption.get(field):
                raise ValueError(
                    f"working copy may not change source-linked table caption {field}"
                )
        review_status = candidate_caption.get("review_status")
        if not isinstance(review_status, str) or not review_status.strip():
            raise ValueError("working copy table caption review status is invalid")

    @staticmethod
    def _validate_table_dual_representation(block: dict, table) -> None:
        structure = block.get("structured_table")
        if not isinstance(structure, dict) or "rows" not in structure:
            return
        structured_rows = structure.get("rows")
        if not isinstance(structured_rows, list):
            raise RuntimeStoreError("structured table rows representation is invalid")
        expected = {
            cell.cell_id: (row.row_id, cell.column_id, str(cell.text))
            for row in table.rows
            for cell in row.cells
        }
        actual: dict[str, tuple[str, str, str]] = {}
        for row in structured_rows:
            if not isinstance(row, dict) or not isinstance(row.get("cells"), list):
                raise RuntimeStoreError("structured table row representation is invalid")
            row_id = str(row.get("row_id", ""))
            for cell in row["cells"]:
                if not isinstance(cell, dict):
                    raise RuntimeStoreError("structured table cell representation is invalid")
                cell_id = str(cell.get("cell_id", ""))
                if not cell_id or cell_id in actual:
                    raise RuntimeStoreError(
                        "structured table cell identities must be present and unique"
                    )
                actual[cell_id] = (
                    str(cell.get("row_id") or row_id),
                    str(cell.get("column_id") or cell.get("structure_column_id") or ""),
                    str(cell.get("text", "")),
                )
        if actual != expected:
            raise RuntimeStoreError(
                "top-level and structured table cell representations are inconsistent"
            )

    @staticmethod
    def _validate_source_note_metadata_review_changes(
        source_notes: Any,
        candidate_notes: Any,
    ) -> None:
        if source_notes is None and candidate_notes is None:
            return
        if not isinstance(source_notes, list) or not isinstance(candidate_notes, list):
            raise ValueError("working copy must preserve source-linked table note metadata")
        if len(source_notes) != len(candidate_notes):
            raise ValueError("working copy must preserve every source-linked table note")
        for index, (source_note, candidate_note) in enumerate(
            zip(source_notes, candidate_notes)
        ):
            if not isinstance(source_note, dict) or not isinstance(candidate_note, dict):
                raise ValueError("working copy source-linked table note is invalid")
            if set(source_note) != set(candidate_note):
                raise ValueError(
                    "working copy must preserve source-linked table note fields"
                )
            for field in set(source_note) - {"review_status"}:
                if candidate_note.get(field) != source_note.get(field):
                    raise ValueError(
                        "working copy may not change source-linked table note "
                        f"{field} at index {index}"
                    )
            review_status = candidate_note.get("review_status")
            if not isinstance(review_status, str) or not review_status.strip():
                raise ValueError(
                    "working copy source-linked table note review status is invalid"
                )

    @staticmethod
    def _validate_generated_table_block(
        block: dict,
        *,
        source_table_ids: set[str],
        generated_table_ids: set[str],
    ) -> None:
        block_id = str(block.get("block_id", ""))
        table_id = str(block.get("table_id", ""))
        if not block_id.startswith("mwgenerated_"):
            raise ValueError("new working-copy blocks must use a generated block identity")
        if block.get("block_type") != "table":
            raise ValueError("only structured table blocks may be added to a source-linked section")
        if block.get("source_kind") != "medical_writing_template":
            raise ValueError("generated tables must retain medical-writing template provenance")
        if not str(block.get("template_id", "")).strip():
            raise ValueError("generated tables must retain their template id")
        if not str(block.get("source_locator", "")).startswith("generated:medical_writing_template:"):
            raise ValueError("generated table source locator is invalid")
        if not table_id or table_id in source_table_ids or table_id in generated_table_ids:
            raise ValueError("generated table identity must be present and unique")
        if not isinstance(block.get("structured_table"), dict):
            raise ValueError("generated tables must use the structured-table contract")
        if block.get("editable") is not True:
            raise ValueError("generated tables must be explicitly editable in the working copy")

        from .medical_writing_tables import MedicalWritingTableService

        table = MedicalWritingTableService().from_table_block(block)
        MedicalWritingRuntimeRepository._validate_table_dual_representation(block, table)
        if table.block_id != block_id or table.table_id != table_id:
            raise ValueError("generated structured table identity is inconsistent")

    @staticmethod
    def _validate_generated_figure_block(block: dict) -> None:
        block_id = str(block.get("block_id", ""))
        if not block_id.startswith("mwgenerated_figure_"):
            raise ValueError("generated figure identity is invalid")
        if block.get("block_type") != "figure" or block.get("figure_kind") != "study_schema":
            raise ValueError("only governed study-schema figures are supported")
        if block.get("source_kind") != "medical_writing_study_schema":
            raise ValueError("study-schema figure provenance is invalid")
        if not str(block.get("source_locator", "")).startswith(
            "generated:medical_writing_study_schema:"
        ):
            raise ValueError("study-schema figure source locator is invalid")
        if block.get("editable") is not False:
            raise ValueError("study-schema figure payload must remain server-controlled")
        for field in (
            "figure_id",
            "title",
            "schema_id",
            "schema_state_sha256",
            "svg",
            "svg_sha256",
            "png_base64",
            "png_sha256",
        ):
            if not str(block.get(field, "")).strip():
                raise ValueError(f"study-schema figure is missing {field}")
        if sha256(str(block["svg"]).encode("utf-8")).hexdigest() != block["svg_sha256"]:
            raise ValueError("study-schema figure SVG hash does not match its payload")
        import base64

        try:
            png = base64.b64decode(str(block["png_base64"]), validate=True)
        except ValueError as exc:
            raise ValueError("study-schema figure PNG fallback is not valid base64") from exc
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("study-schema figure fallback is not a PNG")
        if sha256(png).hexdigest() != block["png_sha256"]:
            raise ValueError("study-schema figure PNG hash does not match its payload")
        if any(token in str(block["svg"]).lower() for token in ("<script", "foreignobject", "javascript:")):
            raise ValueError("study-schema figure SVG contains executable content")

    @staticmethod
    def _validate_generated_appendix_image_block(block: dict) -> None:
        try:
            validate_instrument_appendix_block(block)
        except MedicalWritingInstrumentAppendixError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _validate_generated_intervention_rules_block(block: dict) -> None:
        block_id = str(block.get("block_id", ""))
        if not block_id.startswith("mwgenerated_intervention_"):
            raise ValueError("generated intervention-rules block identity is invalid")
        if block.get("block_type") != "paragraph":
            raise ValueError("intervention-rules projection must be a paragraph")
        if block.get("source_kind") != "medical_writing_intervention_rules":
            raise ValueError("intervention-rules projection provenance is invalid")
        if not str(block.get("source_locator", "")).startswith(
            "generated:medical_writing_intervention_rules:"
        ):
            raise ValueError("intervention-rules projection source locator is invalid")
        if block.get("editable") is not True:
            raise ValueError("intervention-rules projection must remain editable")
        if (
            block.get("render_contract_version")
            != "medical_writing_intervention_rules_projection_v1"
        ):
            raise ValueError("intervention-rules projection contract version is invalid")
        panel_by_section = {
            "6.4": "ip_actions",
            "6.9": "non_ip_rules",
            "6.10": "cm_rules",
        }
        section_number = str(block.get("target_section_number", ""))
        panel = str(block.get("projection_panel", ""))
        if panel_by_section.get(section_number) != panel:
            raise ValueError("intervention-rules projection panel does not match section")
        journey_revision = block.get("source_journey_revision")
        if (
            not isinstance(journey_revision, int)
            or isinstance(journey_revision, bool)
            or journey_revision < 0
        ):
            raise ValueError("intervention-rules source journey revision is invalid")
        facts_hash = str(block.get("source_intervention_rules_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", facts_hash):
            raise ValueError("intervention-rules source hash is invalid")
        projected_text_hash = str(block.get("projected_text_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", projected_text_hash):
            raise ValueError("intervention-rules projected text hash is invalid")
        projected_content_hash = str(block.get("projected_content_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", projected_content_hash):
            raise ValueError("intervention-rules projected content hash is invalid")
        text = block.get("text")
        if not isinstance(text, str):
            raise ValueError("intervention-rules projection text is invalid")
        rich_text = block.get("rich_text")
        if rich_text is None:
            return
        if len(json.dumps(rich_text, ensure_ascii=False)) > 100_000:
            raise ValueError("working copy rich text block is too large")
        if not isinstance(rich_text, dict) or rich_text.get("type") not in {
            "doc",
            "paragraph",
            "heading",
            "bulletList",
            "orderedList",
        }:
            raise ValueError("working copy rich text root is invalid")
        if MedicalWritingRuntimeRepository._rich_text_plain_text(rich_text) != text:
            raise ValueError("working copy rich text must match block text")

    @staticmethod
    def _validate_generated_intervention_rules_edit(
        existing: dict,
        candidate: dict,
    ) -> None:
        allowed_mutable_fields = {"text", "rich_text"}
        if not set(existing).issubset(candidate):
            raise ValueError(
                "working copy must preserve intervention-rules projection metadata"
            )
        if set(candidate) - set(existing) - {"rich_text"}:
            raise ValueError(
                "working copy may not add intervention-rules projection metadata"
            )
        for field in set(existing) - allowed_mutable_fields:
            if candidate.get(field) != existing.get(field):
                raise ValueError(
                    "working copy may not change intervention-rules projection metadata"
                )
