from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.contracts.workbench_contracts import (
    ApprovalBlocker,
    ApprovalState,
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingGreenfieldCreateResult,
    MedicalWritingGreenfieldDecision,
    MedicalWritingGreenfieldDecisionResolveRequest,
    MedicalWritingGreenfieldDecisionResolveResult,
    MedicalWritingProtocolModuleResolution,
    MedicalWritingProtocolModuleResolutionApplyRequest,
    MedicalWritingProtocolModuleResolutionApplyResult,
    MedicalWritingTemplateUpgradeApplyResult,
    MedicalWritingTemplateUpgradeRollbackResult,
    ProtocolDocument,
    ProtocolSection,
    RiskSeverity,
    StructuredTable,
    StructuredTableCell,
    StructuredTableColumn,
    StructuredTableDomain,
    StructuredTableRole,
    StructuredTableRow,
)

from .medical_writing_tables import MedicalWritingTableService


SCHEMA_VERSION = 1


class GreenfieldMedicalWritingConflictError(ValueError):
    """Raised when a greenfield baseline write conflicts with persisted state."""


class GreenfieldMedicalWritingDocumentService:
    """Versioned greenfield protocol baseline provider backed by SQLite."""

    def __init__(
        self,
        db_path: Path,
        plan_consumption_helper: Any = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._plan_helper = plan_consumption_helper
        self._initialize()

    def _require_plan_projection(
        self,
        project_id: str,
        projection_kind: str,
    ) -> Any:
        """Return confirmed plan state for *projection_kind* or ``None``.

        When the helper is injected, fails closed on missing/unconfirmed/stale/
        unresolved plans.  Returns ``None`` when no helper is set (backward
        compatible for tests).
        """
        if self._plan_helper is None:
            return None
        return self._plan_helper.require_confirmed_projection(
            project_id=project_id,
            projection_kind=projection_kind,
        )

    def create(
        self,
        project_id: str,
        request: MedicalWritingGreenfieldCreateRequest,
        *,
        resolved_sections: list[Any] | None = None,
        resolved_decisions: list[MedicalWritingGreenfieldDecision] | None = None,
        resolved_module_resolutions: list[MedicalWritingProtocolModuleResolution]
        | None = None,
        template_definition_sha256: str = "",
        style_profile_id: str = "",
        style_profile_version: str = "",
        style_profile_definition_sha256: str = "",
        corpus_snapshot_id: str = "",
        corpus_snapshot_version: str = "",
        corpus_snapshot_sha256: str = "",
    ) -> MedicalWritingGreenfieldCreateResult:
        canonical_project_id = _required_text(project_id, "project_id")
        # Greenfield document creation is a design-driven operation: consume
        # the confirmed plan's sections_toc projection or fail closed.
        self._require_plan_projection(canonical_project_id, "sections_toc")
        semantic_payload = request.model_dump(
            mode="json",
            exclude={"actor", "idempotency_key"},
        )
        effective_sections = (
            resolved_sections if resolved_sections is not None else request.sections
        )
        effective_decisions = (
            resolved_decisions
            if resolved_decisions is not None
            else request.decisions
        )
        effective_module_resolutions = list(resolved_module_resolutions or [])
        semantic_payload["server_resolved_sections"] = [
            item.model_dump(mode="json") for item in effective_sections
        ]
        semantic_payload["server_resolved_decisions"] = [
            item.model_dump(mode="json") for item in effective_decisions
        ]
        semantic_payload["server_resolved_module_resolutions"] = [
            item.model_dump(mode="json") for item in effective_module_resolutions
        ]
        semantic_payload["server_template_definition_sha256"] = (
            template_definition_sha256
        )
        semantic_payload["server_style_profile_binding"] = {
            "style_profile_id": style_profile_id,
            "style_profile_version": style_profile_version,
            "definition_sha256": style_profile_definition_sha256,
        }
        semantic_payload["server_corpus_snapshot_binding"] = {
            "corpus_snapshot_id": corpus_snapshot_id,
            "corpus_snapshot_version": corpus_snapshot_version,
            "snapshot_sha256": corpus_snapshot_sha256,
        }
        request_sha256 = _payload_sha256(semantic_payload)
        now = datetime.now(timezone.utc)
        document = _build_greenfield_document(
            canonical_project_id,
            request,
            request_sha256,
            resolved_sections=resolved_sections,
            resolved_module_resolutions=resolved_module_resolutions,
            template_definition_sha256=template_definition_sha256,
            style_profile_id=style_profile_id,
            style_profile_version=style_profile_version,
            style_profile_definition_sha256=style_profile_definition_sha256,
            corpus_snapshot_id=corpus_snapshot_id,
            corpus_snapshot_version=corpus_snapshot_version,
            corpus_snapshot_sha256=corpus_snapshot_sha256,
        )
        decisions = list(effective_decisions)
        state_payload = {
            "document": document.model_dump(mode="json"),
            "document_title": request.document_title,
            "indication": request.indication,
            "study_phase": request.study_phase,
            "investigational_product": request.investigational_product,
            "protocol_date": request.protocol_date,
            "sponsor": request.sponsor,
            "decisions": [item.model_dump(mode="json") for item in decisions],
            "module_resolutions": [
                item.model_dump(mode="json")
                for item in (
                    resolved_module_resolutions
                    if resolved_module_resolutions is not None
                    else document.module_resolutions
                )
            ],
        }
        baseline_sha256 = _payload_sha256(state_payload)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT document_id, baseline_revision, baseline_sha256,
                       create_request_sha256, create_idempotency_key,
                       created_at, payload_json
                FROM medical_writing_greenfield_documents
                WHERE project_id = ?
                """,
                (canonical_project_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["create_idempotency_key"] == request.idempotency_key
                    and existing["create_request_sha256"] == request_sha256
                ):
                    current = self._result_from_row(existing, created=False)
                    connection.commit()
                    return current
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "a medical-writing document baseline already exists for this project"
                )
            connection.execute(
                """
                INSERT INTO medical_writing_greenfield_documents(
                    project_id, document_id, baseline_revision, baseline_sha256,
                    create_request_sha256, create_idempotency_key,
                    created_at, updated_at, payload_json
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_project_id,
                    document.document_id,
                    baseline_sha256,
                    request_sha256,
                    request.idempotency_key,
                    now.isoformat(),
                    now.isoformat(),
                    json.dumps(state_payload, ensure_ascii=False, sort_keys=True),
                ),
            )
            self._insert_event(
                connection,
                project_id=canonical_project_id,
                document_id=document.document_id,
                revision=1,
                event_type="greenfield_baseline_created",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                payload={
                    "baseline_sha256": baseline_sha256,
                    "protocol_id": document.protocol_id,
                    "version": document.version,
                    "section_count": len(document.sections),
                    "decision_count": len(decisions),
                },
                created_at=now,
            )
            connection.commit()
        return MedicalWritingGreenfieldCreateResult(
            document=self._session_document(document, decisions),
            baseline_revision=1,
            baseline_sha256=baseline_sha256,
            created=True,
            created_at=now,
            decisions=decisions,
        )

    def has_project(self, project_id: str) -> bool:
        with self._connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM medical_writing_greenfield_documents WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                is not None
            )

    def document_session(self, project_id: str) -> ProtocolDocument:
        document, decisions, _revision, _sha256, _created_at = self._current(project_id)
        return self._session_document(document, decisions)

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        document, decisions, _revision, _sha256, _created_at = self._current(project_id)
        section = next(
            (item for item in document.sections if item.section_id == section_id),
            None,
        )
        if section is None:
            raise KeyError(f"medical writing section not found: {section_id}")
        blockers = self._approval_blockers(document, decisions)
        return section.model_copy(
            update={
                "risk_count": len(blockers),
                "approval_state": ApprovalState.AI_DRAFT,
            },
            deep=True,
        )

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        document, decisions, _revision, _sha256, _created_at = self._current(project_id)
        blockers = self._approval_blockers(document, decisions)
        return document.model_copy(
            update={
                "quality_gates": _quality_gates(document, decisions),
                "sections": [
                    section.model_copy(
                        update={
                            "risk_count": len(blockers),
                            "approval_state": ApprovalState.AI_DRAFT,
                        },
                        deep=True,
                    )
                    for section in document.sections
                ],
            },
            deep=True,
        )

    def approval_blockers(self, project_id: str) -> list[ApprovalBlocker]:
        document, decisions, _revision, _sha256, _created_at = self._current(project_id)
        return self._approval_blockers(document, decisions)

    def resolve_decision(
        self,
        project_id: str,
        decision_id: str,
        request: MedicalWritingGreenfieldDecisionResolveRequest,
    ) -> MedicalWritingGreenfieldDecisionResolveResult:
        canonical_project_id = _required_text(project_id, "project_id")
        canonical_decision_id = _required_text(decision_id, "decision_id")
        semantic_payload = request.model_dump(
            mode="json",
            exclude={"actor", "idempotency_key"},
        )
        semantic_payload.update(
            {"project_id": canonical_project_id, "decision_id": canonical_decision_id}
        )
        request_sha256 = _payload_sha256(semantic_payload)
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (canonical_project_id, request.idempotency_key),
            ).fetchone()
            if replay is not None:
                payload = json.loads(replay["payload_json"])
                if payload.get("request_sha256") != request_sha256:
                    connection.rollback()
                    raise GreenfieldMedicalWritingConflictError(
                        "greenfield decision idempotency key was reused with different content"
                    )
                connection.commit()
                return MedicalWritingGreenfieldDecisionResolveResult.model_validate(
                    payload["result"]
                )
            row = self._current_row(connection, canonical_project_id)
            if int(row["baseline_revision"]) != request.expected_baseline_revision:
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "stale greenfield baseline revision: "
                    f"expected={request.expected_baseline_revision}, "
                    f"actual={row['baseline_revision']}"
                )
            state_payload = json.loads(row["payload_json"])
            decisions = [
                MedicalWritingGreenfieldDecision.model_validate(item)
                for item in state_payload.get("decisions", [])
            ]
            matching = [
                item for item in decisions if item.decision_id == canonical_decision_id
            ]
            if len(matching) != 1:
                connection.rollback()
                raise KeyError(
                    f"greenfield decision not found: {canonical_decision_id}"
                )
            current = matching[0]
            resolved = current.model_copy(
                update={
                    "status": "resolved",
                    "value": request.value,
                    "rationale": request.rationale,
                    "source_refs": request.source_refs,
                },
                deep=True,
            )
            state_payload["decisions"] = [
                (
                    resolved if item.decision_id == canonical_decision_id else item
                ).model_dump(mode="json")
                for item in decisions
            ]
            new_revision = int(row["baseline_revision"]) + 1
            baseline_sha256 = _payload_sha256(state_payload)
            result = MedicalWritingGreenfieldDecisionResolveResult(
                project_id=canonical_project_id,
                document_id=row["document_id"],
                baseline_revision=new_revision,
                baseline_sha256=baseline_sha256,
                decision=resolved,
                resolved_at=now,
            )
            connection.execute(
                """
                UPDATE medical_writing_greenfield_documents
                SET baseline_revision = ?, baseline_sha256 = ?, updated_at = ?, payload_json = ?
                WHERE project_id = ? AND baseline_revision = ?
                """,
                (
                    new_revision,
                    baseline_sha256,
                    now.isoformat(),
                    json.dumps(state_payload, ensure_ascii=False, sort_keys=True),
                    canonical_project_id,
                    request.expected_baseline_revision,
                ),
            )
            self._insert_event(
                connection,
                project_id=canonical_project_id,
                document_id=row["document_id"],
                revision=new_revision,
                event_type="greenfield_decision_resolved",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                payload={
                    "decision_id": canonical_decision_id,
                    "baseline_sha256": baseline_sha256,
                    "result": result.model_dump(mode="json"),
                },
                created_at=now,
            )
            connection.commit()
            return result

    def source_mode(self, project_id: str) -> str:
        self._current(project_id)
        return "greenfield_project_decision"

    def apply_module_resolution(
        self,
        project_id: str,
        request: MedicalWritingProtocolModuleResolutionApplyRequest,
        *,
        resolved_sections: list[Any],
        resolved_module_resolutions: list[MedicalWritingProtocolModuleResolution],
    ) -> MedicalWritingProtocolModuleResolutionApplyResult:
        canonical_project_id = _required_text(project_id, "project_id")
        # Module resolution application is a design-driven operation: consume
        # the confirmed plan's sections_toc projection or fail closed.
        self._require_plan_projection(canonical_project_id, "sections_toc")
        semantic_payload = request.model_dump(
            mode="json",
            exclude={"actor", "idempotency_key"},
        )
        semantic_payload["resolved_module_resolutions"] = [
            item.model_dump(mode="json") for item in resolved_module_resolutions
        ]
        semantic_payload["resolved_sections"] = [
            item.model_dump(mode="json") for item in resolved_sections
        ]
        request_sha256 = _payload_sha256(semantic_payload)
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT event_type, request_sha256, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (canonical_project_id, request.idempotency_key),
            ).fetchone()
            if replay is not None:
                if (
                    replay["event_type"]
                    != "greenfield_protocol_module_resolution_applied"
                    or replay["request_sha256"] != request_sha256
                ):
                    connection.rollback()
                    raise GreenfieldMedicalWritingConflictError(
                        "protocol module resolution idempotency key was reused"
                    )
                result = (
                    MedicalWritingProtocolModuleResolutionApplyResult.model_validate(
                        json.loads(replay["payload_json"])["result"]
                    )
                )
                connection.commit()
                return result
            row = self._current_row(connection, canonical_project_id)
            if (
                int(row["baseline_revision"]) != request.expected_baseline_revision
                or row["baseline_sha256"] != request.expected_baseline_sha256
            ):
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed after module-resolution preview"
                )
            previous_state = json.loads(row["payload_json"])
            current_document = ProtocolDocument.model_validate(
                previous_state["document"]
            )
            create_request = MedicalWritingGreenfieldCreateRequest(
                protocol_id=current_document.protocol_id,
                version=current_document.version,
                document_title=str(previous_state.get("document_title") or ""),
                indication=str(previous_state.get("indication") or ""),
                study_phase=str(previous_state.get("study_phase") or ""),
                investigational_product=str(
                    previous_state.get("investigational_product") or ""
                ),
                protocol_date=str(previous_state.get("protocol_date") or ""),
                sponsor=str(previous_state.get("sponsor") or ""),
                source_study_definition_id=current_document.source_study_definition_id,
                source_study_definition_revision=(
                    current_document.source_study_definition_revision
                ),
                source_study_definition_sha256=(
                    current_document.source_study_definition_sha256
                ),
                template_id=current_document.template_id,
                template_version=current_document.template_version,
                actor=request.actor,
                idempotency_key=request.idempotency_key,
            )
            target_document = _build_greenfield_document(
                canonical_project_id,
                create_request,
                row["create_request_sha256"],
                resolved_sections=resolved_sections,
                resolved_module_resolutions=resolved_module_resolutions,
                template_definition_sha256=(
                    current_document.template_definition_sha256
                ),
                style_profile_id=current_document.style_profile_id,
                style_profile_version=current_document.style_profile_version,
                style_profile_definition_sha256=(
                    current_document.style_profile_definition_sha256
                ),
                corpus_snapshot_id=current_document.corpus_snapshot_id,
                corpus_snapshot_version=current_document.corpus_snapshot_version,
                corpus_snapshot_sha256=current_document.corpus_snapshot_sha256,
            )
            current_by_node = {
                section.template_node_id: section
                for section in current_document.sections
            }
            target_by_node = {
                section.template_node_id: section
                for section in target_document.sections
            }
            previous_resolutions = {
                item.template_node_id: item
                for item in current_document.module_resolutions
            }
            target_resolutions = {
                item.template_node_id: item for item in resolved_module_resolutions
            }
            applied_resolution = next(
                (
                    item
                    for item in resolved_module_resolutions
                    if item.semantic_node_id == request.semantic_node_id
                ),
                None,
            )
            if applied_resolution is None:
                connection.rollback()
                raise ValueError(
                    "resolved module set does not contain the requested semantic node"
                )
            preserved_sections: list[ProtocolSection] = []
            added_section_ids: list[str] = []
            updated_section_ids: list[str] = []
            quarantined_sections = list(
                previous_state.get("quarantined_sections") or []
            )
            quarantined_section_ids: list[str] = []
            for target_section in target_document.sections:
                current_section = current_by_node.get(target_section.template_node_id)
                previous_resolution = previous_resolutions.get(
                    target_section.template_node_id
                )
                target_resolution = target_resolutions.get(
                    target_section.template_node_id
                )
                same_resolution = (
                    previous_resolution is not None
                    and target_resolution is not None
                    and previous_resolution.status == target_resolution.status
                    and previous_resolution.render_action
                    == target_resolution.render_action
                )
                propagated_rebuild = (
                    "synopsis" in applied_resolution.affected_artifacts
                    and target_section.node_kind == "protocol_synopsis"
                ) or (
                    "schedule" in applied_resolution.affected_artifacts
                    and (
                        target_section.template_node_id
                        in {
                            "cms_synopsis_schedule",
                            "cms_procedures_assessments_schedule",
                        }
                    )
                )
                if current_section is None:
                    preserved_sections.append(target_section)
                    added_section_ids.append(target_section.section_id)
                elif same_resolution and not propagated_rebuild:
                    preserved = target_section.model_copy(
                        update={
                            "content_blocks": current_section.content_blocks,
                            "completion_status": current_section.completion_status,
                            "approval_state": current_section.approval_state,
                            "evidence_coverage": current_section.evidence_coverage,
                            "risk_count": current_section.risk_count,
                            "drafting_status": current_section.drafting_status,
                            "drafting_blocker_code": (
                                current_section.drafting_blocker_code
                            ),
                            "drafting_blocker_reason": (
                                current_section.drafting_blocker_reason
                            ),
                            "drafting_missing_inputs": (
                                current_section.drafting_missing_inputs
                            ),
                            "drafting_resolution_actions": (
                                current_section.drafting_resolution_actions
                            ),
                        },
                        deep=True,
                    )
                    preserved_sections.append(
                        ProtocolSection.model_validate(
                            preserved.model_dump(mode="python")
                        )
                    )
                else:
                    quarantined_sections.append(
                        {
                            "section": current_section.model_dump(mode="json"),
                            "reason": (
                                "章节适用性状态或呈现策略发生变化，原内容已隔离保留。"
                            ),
                            "semantic_node_id": request.semantic_node_id,
                            "quarantined_at": now.isoformat(),
                            "quarantined_by": request.actor,
                        }
                    )
                    quarantined_section_ids.append(current_section.section_id)
                    preserved_sections.append(target_section)
                    updated_section_ids.append(target_section.section_id)
            removed_sections = [
                section
                for node_id, section in current_by_node.items()
                if node_id not in target_by_node
            ]
            for section in removed_sections:
                quarantined_sections.append(
                    {
                        "section": section.model_dump(mode="json"),
                        "reason": "研究设计变化后章节不再呈现，原内容已隔离保留。",
                        "semantic_node_id": request.semantic_node_id,
                        "quarantined_at": now.isoformat(),
                        "quarantined_by": request.actor,
                    }
                )
                quarantined_section_ids.append(section.section_id)
            updated_document = target_document.model_copy(
                update={
                    "sections": preserved_sections,
                    "module_resolutions": resolved_module_resolutions,
                },
                deep=True,
            )
            updated_state = {
                **previous_state,
                "document": updated_document.model_dump(mode="json"),
                "module_resolutions": [
                    item.model_dump(mode="json") for item in resolved_module_resolutions
                ],
                "quarantined_sections": quarantined_sections,
            }
            new_revision = request.expected_baseline_revision + 1
            baseline_sha256 = _payload_sha256(updated_state)
            result = MedicalWritingProtocolModuleResolutionApplyResult(
                project_id=canonical_project_id,
                document_id=updated_document.document_id,
                baseline_revision=new_revision,
                baseline_sha256=baseline_sha256,
                resolution=applied_resolution,
                added_section_ids=added_section_ids,
                updated_section_ids=updated_section_ids,
                removed_section_ids=[
                    section.section_id for section in removed_sections
                ],
                quarantined_section_ids=quarantined_section_ids,
                affected_artifacts=list(applied_resolution.affected_artifacts),
                applied_at=now,
            )
            updated = connection.execute(
                """
                UPDATE medical_writing_greenfield_documents
                SET baseline_revision = ?, baseline_sha256 = ?, updated_at = ?,
                    payload_json = ?
                WHERE project_id = ? AND document_id = ?
                  AND baseline_revision = ? AND baseline_sha256 = ?
                """,
                (
                    new_revision,
                    baseline_sha256,
                    now.isoformat(),
                    json.dumps(updated_state, ensure_ascii=False, sort_keys=True),
                    canonical_project_id,
                    updated_document.document_id,
                    request.expected_baseline_revision,
                    request.expected_baseline_sha256,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed while applying module resolution"
                )
            self._insert_event(
                connection,
                project_id=canonical_project_id,
                document_id=updated_document.document_id,
                revision=new_revision,
                event_type="greenfield_protocol_module_resolution_applied",
                actor=request.actor,
                idempotency_key=request.idempotency_key,
                request_sha256=request_sha256,
                payload={
                    "semantic_node_id": request.semantic_node_id,
                    "added_section_ids": added_section_ids,
                    "updated_section_ids": updated_section_ids,
                    "removed_section_ids": [
                        section.section_id for section in removed_sections
                    ],
                    "quarantined_section_ids": quarantined_section_ids,
                    "result": result.model_dump(mode="json"),
                },
                created_at=now,
            )
            connection.commit()
            return result

    def baseline_state(self, project_id: str) -> dict[str, Any]:
        document, decisions, revision, sha256, created_at = self._current(project_id)
        with self._connect() as connection:
            row = self._current_row(connection, project_id)
        state_payload = json.loads(row["payload_json"])
        return {
            "project_id": project_id,
            "document_id": document.document_id,
            "protocol_id": document.protocol_id,
            "version": document.version,
            "baseline_revision": revision,
            "baseline_sha256": sha256,
            "created_at": created_at.isoformat(),
            "source_mode": "greenfield_project_decision",
            "decisions": [item.model_dump(mode="json") for item in decisions],
            "approval_blocker_count": len(
                self._approval_blockers(document, decisions)
            ),
            "template_id": document.template_id,
            "template_version": document.template_version,
            "template_definition_sha256": document.template_definition_sha256,
            "section_count": len(document.sections),
            "document_title": str(state_payload.get("document_title") or ""),
            "indication": str(state_payload.get("indication") or ""),
            "study_phase": str(state_payload.get("study_phase") or ""),
            "module_resolutions": list(
                state_payload.get("module_resolutions")
                or [
                    item.model_dump(mode="json") for item in document.module_resolutions
                ]
            ),
            "unresolved_module_count": len(
                self._unresolved_module_resolutions(document)
            ),
        }

    def rebind_study_definition(
        self,
        project_id: str,
        *,
        expected_document_id: str,
        expected_baseline_revision: int,
        expected_baseline_sha256: str,
        definition_id: str,
        definition_revision: int,
        definition_sha256: str,
        preview_id: str,
        reset_section_ids: list[str],
        reset_working_copy_ids: list[str],
        reset_approval_count: int,
        client_request_sha256: str,
        actor: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        semantic_payload = {
            "project_id": project_id,
            "expected_document_id": expected_document_id,
            "expected_baseline_revision": expected_baseline_revision,
            "expected_baseline_sha256": expected_baseline_sha256,
            "definition_id": definition_id,
            "definition_revision": definition_revision,
            "definition_sha256": definition_sha256,
            "preview_id": preview_id,
            "reset_section_ids": sorted(reset_section_ids),
            "reset_working_copy_ids": sorted(reset_working_copy_ids),
            "reset_approval_count": reset_approval_count,
            "client_request_sha256": client_request_sha256,
        }
        request_sha256 = _payload_sha256(semantic_payload)
        now = datetime.now(timezone.utc)
        event_id = self._event_id(
            project_id, "greenfield_study_definition_rebound", idempotency_key
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT event_type, request_sha256, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if (
                    replay["event_type"] != "greenfield_study_definition_rebound"
                    or replay["request_sha256"] != request_sha256
                ):
                    connection.rollback()
                    raise GreenfieldMedicalWritingConflictError(
                        "study-definition rebind idempotency key was reused with different content"
                    )
                result = json.loads(replay["payload_json"])["result"]
                connection.commit()
                return result
            row = self._current_row(connection, project_id)
            if (
                row["document_id"] != expected_document_id
                or int(row["baseline_revision"]) != expected_baseline_revision
                or row["baseline_sha256"] != expected_baseline_sha256
            ):
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed after study-definition rebind preview"
                )
            previous_state = json.loads(row["payload_json"])
            document = ProtocolDocument.model_validate(previous_state["document"])
            updated_document = document.model_copy(
                update={
                    "source_study_definition_id": definition_id,
                    "source_study_definition_revision": definition_revision,
                    "source_study_definition_sha256": definition_sha256,
                },
                deep=True,
            )
            updated_state = {
                **previous_state,
                "document": updated_document.model_dump(mode="json"),
            }
            baseline_revision = expected_baseline_revision + 1
            baseline_sha256 = _payload_sha256(updated_state)
            result = {
                "project_id": project_id,
                "document_id": updated_document.document_id,
                "baseline_revision": baseline_revision,
                "baseline_sha256": baseline_sha256,
                "event_id": event_id,
                "reset_working_copy_ids": sorted(reset_working_copy_ids),
                "reset_approval_count": reset_approval_count,
                "updated_at": now.isoformat(),
            }
            updated = connection.execute(
                """
                UPDATE medical_writing_greenfield_documents
                SET baseline_revision = ?, baseline_sha256 = ?, updated_at = ?, payload_json = ?
                WHERE project_id = ? AND document_id = ?
                  AND baseline_revision = ? AND baseline_sha256 = ?
                """,
                (
                    baseline_revision,
                    baseline_sha256,
                    now.isoformat(),
                    json.dumps(updated_state, ensure_ascii=False, sort_keys=True),
                    project_id,
                    expected_document_id,
                    expected_baseline_revision,
                    expected_baseline_sha256,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed during study-definition rebind"
                )
            self._insert_event(
                connection,
                project_id=project_id,
                document_id=updated_document.document_id,
                revision=baseline_revision,
                event_type="greenfield_study_definition_rebound",
                actor=actor,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                payload={
                    "preview_id": preview_id,
                    "previous_binding": {
                        "definition_id": document.source_study_definition_id,
                        "definition_revision": document.source_study_definition_revision,
                        "definition_sha256": document.source_study_definition_sha256,
                    },
                    "current_binding": {
                        "definition_id": definition_id,
                        "definition_revision": definition_revision,
                        "definition_sha256": definition_sha256,
                    },
                    "reset_section_ids": sorted(reset_section_ids),
                    "reset_working_copy_ids": sorted(reset_working_copy_ids),
                    "reset_approval_count": reset_approval_count,
                    "client_request_sha256": client_request_sha256,
                    "result": result,
                },
                created_at=now,
            )
            connection.commit()
            return result

    def study_definition_rebind_replay(
        self,
        project_id: str,
        *,
        idempotency_key: str,
        client_request_sha256: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT event_type, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        if row["event_type"] != "greenfield_study_definition_rebound":
            raise GreenfieldMedicalWritingConflictError(
                "study-definition rebind idempotency key belongs to another operation"
            )
        payload = json.loads(row["payload_json"])
        if payload.get("client_request_sha256") != client_request_sha256:
            raise GreenfieldMedicalWritingConflictError(
                "study-definition rebind idempotency key was reused with different content"
            )
        return payload["result"]

    def apply_template_upgrade(
        self,
        project_id: str,
        *,
        target_document: ProtocolDocument,
        expected_baseline_revision: int,
        expected_baseline_sha256: str,
        preview_sha256: str,
        migrated_source_section_count: int,
        approval_reset_count: int,
        client_request_sha256: str,
        actor: str,
        idempotency_key: str,
    ) -> MedicalWritingTemplateUpgradeApplyResult:
        semantic_payload = {
            "project_id": project_id,
            "target_document": target_document.model_dump(mode="json"),
            "expected_baseline_revision": expected_baseline_revision,
            "expected_baseline_sha256": expected_baseline_sha256,
            "preview_sha256": preview_sha256,
            "migrated_source_section_count": migrated_source_section_count,
            "approval_reset_count": approval_reset_count,
        }
        request_sha256 = _payload_sha256(semantic_payload)
        now = datetime.now(timezone.utc)
        event_id = self._event_id(
            project_id, "greenfield_template_upgraded", idempotency_key
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT request_sha256, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_sha256"] != request_sha256:
                    connection.rollback()
                    raise GreenfieldMedicalWritingConflictError(
                        "template upgrade idempotency key was reused with different content"
                    )
                payload = json.loads(replay["payload_json"])
                connection.commit()
                return MedicalWritingTemplateUpgradeApplyResult.model_validate(
                    payload["result"]
                )
            row = self._current_row(connection, project_id)
            if (
                int(row["baseline_revision"]) != expected_baseline_revision
                or row["baseline_sha256"] != expected_baseline_sha256
            ):
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed after template upgrade preview"
                )
            previous_state = json.loads(row["payload_json"])
            previous_document = ProtocolDocument.model_validate(
                previous_state["document"]
            )
            if target_document.project_id != project_id:
                connection.rollback()
                raise ValueError(
                    "template upgrade target document belongs to another project"
                )
            if target_document.document_id == previous_document.document_id:
                connection.rollback()
                raise ValueError("template upgrade must create a new document identity")
            new_state = {
                **previous_state,
                "document": target_document.model_dump(mode="json"),
            }
            new_revision = expected_baseline_revision + 1
            baseline_sha256 = _payload_sha256(new_state)
            result = MedicalWritingTemplateUpgradeApplyResult(
                project_id=project_id,
                previous_document_id=previous_document.document_id,
                document=self._session_document(
                    target_document,
                    [
                        MedicalWritingGreenfieldDecision.model_validate(item)
                        for item in new_state.get("decisions", [])
                    ],
                ),
                baseline_revision=new_revision,
                baseline_sha256=baseline_sha256,
                migration_event_id=event_id,
                migrated_source_section_count=migrated_source_section_count,
                target_section_count=len(target_document.sections),
                approval_reset_count=approval_reset_count,
                applied_at=now,
            )
            updated = connection.execute(
                """
                UPDATE medical_writing_greenfield_documents
                SET document_id = ?, baseline_revision = ?, baseline_sha256 = ?,
                    updated_at = ?, payload_json = ?
                WHERE project_id = ? AND baseline_revision = ? AND baseline_sha256 = ?
                """,
                (
                    target_document.document_id,
                    new_revision,
                    baseline_sha256,
                    now.isoformat(),
                    json.dumps(new_state, ensure_ascii=False, sort_keys=True),
                    project_id,
                    expected_baseline_revision,
                    expected_baseline_sha256,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed during template upgrade"
                )
            self._insert_event(
                connection,
                project_id=project_id,
                document_id=target_document.document_id,
                revision=new_revision,
                event_type="greenfield_template_upgraded",
                actor=actor,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                payload={
                    "previous_state": previous_state,
                    "client_request_sha256": client_request_sha256,
                    "preview_sha256": preview_sha256,
                    "baseline_sha256": baseline_sha256,
                    "result": result.model_dump(mode="json"),
                },
                created_at=now,
            )
            connection.commit()
            return result

    def template_upgrade_replay(
        self,
        project_id: str,
        idempotency_key: str,
        client_request_sha256: str,
    ) -> MedicalWritingTemplateUpgradeApplyResult | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT event_type, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        if row["event_type"] != "greenfield_template_upgraded":
            raise GreenfieldMedicalWritingConflictError(
                "template upgrade idempotency key belongs to another operation"
            )
        payload = json.loads(row["payload_json"])
        if payload.get("client_request_sha256") != client_request_sha256:
            raise GreenfieldMedicalWritingConflictError(
                "template upgrade idempotency key was reused with different content"
            )
        return MedicalWritingTemplateUpgradeApplyResult.model_validate(
            payload["result"]
        )

    def rollback_template_upgrade(
        self,
        project_id: str,
        *,
        migration_event_id: str,
        expected_baseline_revision: int,
        expected_baseline_sha256: str,
        client_request_sha256: str,
        actor: str,
        idempotency_key: str,
    ) -> MedicalWritingTemplateUpgradeRollbackResult:
        semantic_payload = {
            "project_id": project_id,
            "migration_event_id": migration_event_id,
            "expected_baseline_revision": expected_baseline_revision,
            "expected_baseline_sha256": expected_baseline_sha256,
        }
        request_sha256 = _payload_sha256(semantic_payload)
        now = datetime.now(timezone.utc)
        rollback_event_id = self._event_id(
            project_id,
            "greenfield_template_upgrade_rolled_back",
            idempotency_key,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT request_sha256, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_sha256"] != request_sha256:
                    connection.rollback()
                    raise GreenfieldMedicalWritingConflictError(
                        "template rollback idempotency key was reused with different content"
                    )
                payload = json.loads(replay["payload_json"])
                connection.commit()
                return MedicalWritingTemplateUpgradeRollbackResult.model_validate(
                    payload["result"]
                )
            migration = connection.execute(
                """
                SELECT event_type, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND event_id = ?
                """,
                (project_id, migration_event_id),
            ).fetchone()
            if (
                migration is None
                or migration["event_type"] != "greenfield_template_upgraded"
            ):
                connection.rollback()
                raise KeyError(
                    f"template upgrade event not found: {migration_event_id}"
                )
            row = self._current_row(connection, project_id)
            if (
                int(row["baseline_revision"]) != expected_baseline_revision
                or row["baseline_sha256"] != expected_baseline_sha256
            ):
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed after template upgrade"
                )
            migration_payload = json.loads(migration["payload_json"])
            previous_state = migration_payload.get("previous_state")
            if not isinstance(previous_state, dict) or "document" not in previous_state:
                connection.rollback()
                raise ValueError(
                    "template upgrade event has no restorable previous state"
                )
            current_state = json.loads(row["payload_json"])
            current_document = ProtocolDocument.model_validate(
                current_state["document"]
            )
            applied_result = MedicalWritingTemplateUpgradeApplyResult.model_validate(
                migration_payload["result"]
            )
            if current_document.document_id != applied_result.document.document_id:
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "current document is not the document created by this template upgrade"
                )
            restored_document = ProtocolDocument.model_validate(
                previous_state["document"]
            )
            new_revision = expected_baseline_revision + 1
            baseline_sha256 = _payload_sha256(previous_state)
            result = MedicalWritingTemplateUpgradeRollbackResult(
                project_id=project_id,
                removed_document_id=current_document.document_id,
                restored_document=self._session_document(
                    restored_document,
                    [
                        MedicalWritingGreenfieldDecision.model_validate(item)
                        for item in previous_state.get("decisions", [])
                    ],
                ),
                baseline_revision=new_revision,
                baseline_sha256=baseline_sha256,
                rollback_event_id=rollback_event_id,
                rolled_back_at=now,
            )
            updated = connection.execute(
                """
                UPDATE medical_writing_greenfield_documents
                SET document_id = ?, baseline_revision = ?, baseline_sha256 = ?,
                    updated_at = ?, payload_json = ?
                WHERE project_id = ? AND baseline_revision = ? AND baseline_sha256 = ?
                """,
                (
                    restored_document.document_id,
                    new_revision,
                    baseline_sha256,
                    now.isoformat(),
                    json.dumps(previous_state, ensure_ascii=False, sort_keys=True),
                    project_id,
                    expected_baseline_revision,
                    expected_baseline_sha256,
                ),
            )
            if updated.rowcount != 1:
                connection.rollback()
                raise GreenfieldMedicalWritingConflictError(
                    "greenfield baseline changed while restoring the pre-upgrade document"
                )
            self._insert_event(
                connection,
                project_id=project_id,
                document_id=restored_document.document_id,
                revision=new_revision,
                event_type="greenfield_template_upgrade_rolled_back",
                actor=actor,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                payload={
                    "migration_event_id": migration_event_id,
                    "client_request_sha256": client_request_sha256,
                    "baseline_sha256": baseline_sha256,
                    "result": result.model_dump(mode="json"),
                },
                created_at=now,
            )
            connection.commit()
            return result

    def template_upgrade_rollback_replay(
        self,
        project_id: str,
        idempotency_key: str,
        client_request_sha256: str,
    ) -> MedicalWritingTemplateUpgradeRollbackResult | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT event_type, payload_json
                FROM medical_writing_greenfield_events
                WHERE project_id = ? AND idempotency_key = ?
                """,
                (project_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        if row["event_type"] != "greenfield_template_upgrade_rolled_back":
            raise GreenfieldMedicalWritingConflictError(
                "template rollback idempotency key belongs to another operation"
            )
        payload = json.loads(row["payload_json"])
        if payload.get("client_request_sha256") != client_request_sha256:
            raise GreenfieldMedicalWritingConflictError(
                "template rollback idempotency key was reused with different content"
            )
        return MedicalWritingTemplateUpgradeRollbackResult.model_validate(
            payload["result"]
        )

    def _current(
        self,
        project_id: str,
    ) -> tuple[
        ProtocolDocument, list[MedicalWritingGreenfieldDecision], int, str, datetime
    ]:
        with self._connect() as connection:
            row = self._current_row(connection, project_id)
        state = json.loads(row["payload_json"])
        return (
            ProtocolDocument.model_validate(state["document"]),
            [
                MedicalWritingGreenfieldDecision.model_validate(item)
                for item in state.get("decisions", [])
            ],
            int(row["baseline_revision"]),
            row["baseline_sha256"],
            datetime.fromisoformat(row["created_at"]),
        )

    def _result_from_row(
        self,
        row: sqlite3.Row,
        *,
        created: bool,
    ) -> MedicalWritingGreenfieldCreateResult:
        state = json.loads(row["payload_json"])
        decisions = [
            MedicalWritingGreenfieldDecision.model_validate(item)
            for item in state.get("decisions", [])
        ]
        document = ProtocolDocument.model_validate(state["document"])
        return MedicalWritingGreenfieldCreateResult(
            document=self._session_document(document, decisions),
            baseline_revision=int(row["baseline_revision"]),
            baseline_sha256=row["baseline_sha256"],
            created=created,
            created_at=datetime.fromisoformat(row["created_at"]),
            decisions=decisions,
        )

    @staticmethod
    def _session_document(
        document: ProtocolDocument,
        decisions: list[MedicalWritingGreenfieldDecision],
    ) -> ProtocolDocument:
        return document.model_copy(
            update={
                "quality_gates": _quality_gates(document, decisions),
                "sections": [
                    section.model_copy(update={"content_blocks": []}, deep=True)
                    for section in document.sections
                ],
            },
            deep=True,
        )

    @staticmethod
    def _decision_blockers(
        project_id: str,
        document_id: str,
        decisions: list[MedicalWritingGreenfieldDecision],
    ) -> list[ApprovalBlocker]:
        return [
            ApprovalBlocker(
                blocker_id=f"greenfield_decision:{item.decision_id}",
                blocker_type="greenfield_unresolved_decision",
                source_type="medical_writing_greenfield_decision",
                source_id=item.decision_id,
                severity=RiskSeverity.HIGH,
                message=f"{item.label}尚未形成有来源的项目决策，不能批准当前方案正文。",
            )
            for item in decisions
            if item.approval_blocking and item.status != "resolved"
        ]

    @staticmethod
    def _unresolved_module_resolutions(
        document: ProtocolDocument,
    ) -> list[MedicalWritingProtocolModuleResolution]:
        return [
            item
            for item in document.module_resolutions
            if item.status in {"unknown", "deferred"}
        ]

    @classmethod
    def _approval_blockers(
        cls,
        document: ProtocolDocument,
        decisions: list[MedicalWritingGreenfieldDecision],
    ) -> list[ApprovalBlocker]:
        blockers = cls._decision_blockers(
            document.project_id,
            document.document_id,
            decisions,
        )
        unresolved_modules = cls._unresolved_module_resolutions(document)
        if unresolved_modules:
            blockers.append(
                ApprovalBlocker(
                    blocker_id=(
                        f"greenfield_module_applicability:{document.document_id}"
                    ),
                    blocker_type="greenfield_unresolved_module_applicability",
                    source_type="medical_writing_protocol_module_resolution",
                    source_id=document.document_id,
                    severity=RiskSeverity.HIGH,
                    message=(
                        f"仍有{len(unresolved_modules)}个动态章节的适用性待确定或延后，"
                        "不能将当前方案标记为就绪。"
                    ),
                )
            )
        return blockers

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS medical_writing_greenfield_documents (
                    project_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL UNIQUE,
                    baseline_revision INTEGER NOT NULL,
                    baseline_sha256 TEXT NOT NULL,
                    create_request_sha256 TEXT NOT NULL,
                    create_idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS medical_writing_greenfield_events (
                    event_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(project_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS idx_greenfield_events_project_revision
                    ON medical_writing_greenfield_events(project_id, revision, created_at);
                """
            )
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            if version is None:
                connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
                )
            elif int(version) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported greenfield medical-writing schema version: {version}"
                )
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(
                    f"greenfield medical-writing SQLite integrity check failed: {integrity}"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _current_row(connection: sqlite3.Connection, project_id: str) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT document_id, baseline_revision, baseline_sha256,
                   create_request_sha256, create_idempotency_key,
                   created_at, updated_at, payload_json
            FROM medical_writing_greenfield_documents
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(
                f"greenfield medical writing document not found: {project_id}"
            )
        return row

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        *,
        project_id: str,
        document_id: str,
        revision: int,
        event_type: str,
        actor: str,
        idempotency_key: str,
        request_sha256: str,
        payload: dict[str, Any],
        created_at: datetime,
    ) -> None:
        event_id = GreenfieldMedicalWritingDocumentService._event_id(
            project_id,
            event_type,
            idempotency_key,
        )
        event_payload = {
            **payload,
            "request_sha256": request_sha256,
        }
        connection.execute(
            """
            INSERT INTO medical_writing_greenfield_events(
                event_id, project_id, document_id, revision, event_type,
                actor, idempotency_key, request_sha256, created_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                project_id,
                document_id,
                revision,
                event_type,
                actor,
                idempotency_key,
                request_sha256,
                created_at.isoformat(),
                json.dumps(event_payload, ensure_ascii=False, sort_keys=True),
            ),
        )

    @staticmethod
    def _event_id(project_id: str, event_type: str, idempotency_key: str) -> str:
        return (
            "mwgreen_event_"
            + hashlib.sha256(
                f"{project_id}|{event_type}|{idempotency_key}".encode("utf-8")
            ).hexdigest()[:24]
        )


class CompositeMedicalWritingDocumentService:
    """Use immutable DOCX sources when configured, otherwise a greenfield baseline."""

    def __init__(
        self,
        source_document_service: Any,
        greenfield_document_service: GreenfieldMedicalWritingDocumentService,
    ):
        self.source_document_service = source_document_service
        self.greenfield_document_service = greenfield_document_service

    def create_greenfield(
        self,
        project_id: str,
        request: MedicalWritingGreenfieldCreateRequest,
        *,
        resolved_sections: list[Any] | None = None,
        resolved_decisions: list[MedicalWritingGreenfieldDecision] | None = None,
        resolved_module_resolutions: list[MedicalWritingProtocolModuleResolution]
        | None = None,
        template_definition_sha256: str = "",
        style_profile_id: str = "",
        style_profile_version: str = "",
        style_profile_definition_sha256: str = "",
        corpus_snapshot_id: str = "",
        corpus_snapshot_version: str = "",
        corpus_snapshot_sha256: str = "",
    ) -> MedicalWritingGreenfieldCreateResult:
        if self._has_source_configuration(project_id):
            raise GreenfieldMedicalWritingConflictError(
                "an original protocol DOCX is already configured for this project"
            )
        return self.greenfield_document_service.create(
            project_id,
            request,
            resolved_sections=resolved_sections,
            resolved_decisions=resolved_decisions,
            resolved_module_resolutions=resolved_module_resolutions,
            template_definition_sha256=template_definition_sha256,
            style_profile_id=style_profile_id,
            style_profile_version=style_profile_version,
            style_profile_definition_sha256=style_profile_definition_sha256,
            corpus_snapshot_id=corpus_snapshot_id,
            corpus_snapshot_version=corpus_snapshot_version,
            corpus_snapshot_sha256=corpus_snapshot_sha256,
        )

    def document_session(self, project_id: str) -> ProtocolDocument:
        if self._has_source_configuration(project_id):
            return self.source_document_service.document_session(project_id)
        return self.greenfield_document_service.document_session(project_id)

    def section(self, project_id: str, section_id: str) -> ProtocolSection:
        if self._has_source_configuration(project_id):
            return self.source_document_service.section(project_id, section_id)
        return self.greenfield_document_service.section(project_id, section_id)

    def document_for_revision(self, project_id: str) -> ProtocolDocument:
        if self._has_source_configuration(project_id):
            return self.source_document_service.document_for_revision(project_id)
        return self.greenfield_document_service.document_for_revision(project_id)

    def source_mode(self, project_id: str) -> str:
        if self._has_source_configuration(project_id):
            return "original_protocol_docx"
        return self.greenfield_document_service.source_mode(project_id)

    def original_protocol_path(self, project_id: str):
        if not self._has_source_configuration(project_id):
            raise KeyError(f"project has no original protocol DOCX: {project_id}")
        return self.source_document_service.original_protocol_path(project_id)

    def approval_blockers(self, project_id: str) -> list[ApprovalBlocker]:
        if self._has_source_configuration(project_id):
            return []
        return self.greenfield_document_service.approval_blockers(project_id)

    def greenfield_state(self, project_id: str) -> dict[str, Any]:
        if self._has_source_configuration(project_id):
            raise KeyError(f"project uses an original protocol DOCX: {project_id}")
        return self.greenfield_document_service.baseline_state(project_id)

    def resolve_greenfield_decision(
        self,
        project_id: str,
        decision_id: str,
        request: MedicalWritingGreenfieldDecisionResolveRequest,
    ) -> MedicalWritingGreenfieldDecisionResolveResult:
        if self._has_source_configuration(project_id):
            raise GreenfieldMedicalWritingConflictError(
                "original protocol DOCX projects do not use greenfield decisions"
            )
        return self.greenfield_document_service.resolve_decision(
            project_id,
            decision_id,
            request,
        )

    def apply_greenfield_module_resolution(
        self,
        project_id: str,
        request: MedicalWritingProtocolModuleResolutionApplyRequest,
        *,
        resolved_sections: list[Any],
        resolved_module_resolutions: list[MedicalWritingProtocolModuleResolution],
    ) -> MedicalWritingProtocolModuleResolutionApplyResult:
        if self._has_source_configuration(project_id):
            raise GreenfieldMedicalWritingConflictError(
                "original protocol DOCX projects do not use greenfield module resolutions"
            )
        return self.greenfield_document_service.apply_module_resolution(
            project_id,
            request,
            resolved_sections=resolved_sections,
            resolved_module_resolutions=resolved_module_resolutions,
        )

    def _has_source_configuration(self, project_id: str) -> bool:
        checker = getattr(
            self.source_document_service, "has_project_configuration", None
        )
        if callable(checker):
            return bool(checker(project_id))
        try:
            self.source_document_service.document_session(project_id)
        except (KeyError, FileNotFoundError, ValueError):
            return False
        return True


def _build_greenfield_document(
    project_id: str,
    request: MedicalWritingGreenfieldCreateRequest,
    request_sha256: str,
    *,
    resolved_sections: list[Any] | None = None,
    resolved_module_resolutions: list[MedicalWritingProtocolModuleResolution]
    | None = None,
    template_definition_sha256: str = "",
    style_profile_id: str = "",
    style_profile_version: str = "",
    style_profile_definition_sha256: str = "",
    corpus_snapshot_id: str = "",
    corpus_snapshot_version: str = "",
    corpus_snapshot_sha256: str = "",
) -> ProtocolDocument:
    section_seeds = list(
        resolved_sections if resolved_sections is not None else request.sections
    )
    project_token = _identifier_token(project_id)
    document_id = f"mwdoc_greenfield_{project_token}_{request_sha256[:16]}"
    section_ids = {
        seed.section_key: (
            f"mwsec_greenfield_{project_token}_"
            + hashlib.sha256(
                f"{document_id}|{seed.section_key}".encode("utf-8")
            ).hexdigest()[:16]
        )
        for seed in section_seeds
    }
    sections: list[ProtocolSection] = []
    body_order = 0
    depth_by_key: dict[str, int] = {}
    for seed in section_seeds:
        depth = depth_by_key.get(seed.parent_key, -1) + 1 if seed.parent_key else 0
        depth_by_key[seed.section_key] = min(depth, 8)
        section_id = section_ids[seed.section_key]
        heading_locator = f"greenfield:{document_id}:section:{seed.section_key}:heading"
        text_locator = f"greenfield:{document_id}:section:{seed.section_key}:body:1"
        heading_block = {
            "block_id": _block_id(section_id, heading_locator),
            "block_type": "heading",
            "text": seed.heading,
            "source_locator": heading_locator,
            "source_kind": "greenfield_scaffold",
            "body_order": body_order,
            "style_id": "greenfield_heading",
            "style_name": f"Heading {min(depth + 1, 4)}",
            "num_id": None,
            "ilvl": depth,
            "outline_level": depth,
            "numbering_format": None,
            "numbering_level_text": None,
            "editable": not seed.title_locked,
            "suppress_numbering": not bool(seed.section_number),
            "include_in_toc": seed.node_kind
            not in {"front_matter", "document_control"},
            "page_break_before": seed.template_node_id
            in {
                "cms_confidentiality",
                "cms_signatures",
                "cms_version_history",
                "cms_synopsis_summary",
            },
        }
        body_order += 1
        if (
            seed.node_kind == "front_matter"
            or "front_matter_editor" in seed.interaction_types
        ):
            body_block = _greenfield_document_object_table(
                section_id=section_id,
                document_id=document_id,
                body_order=body_order,
                title="方案首页信息",
                role=StructuredTableRole.LAYOUT,
                rows=[
                    ("方案编号", request.protocol_id),
                    ("版本", request.version),
                    ("方案标题", request.document_title),
                    ("适应症", request.indication),
                    ("研究分期", request.study_phase),
                    ("研究药物", request.investigational_product),
                    ("版本日期", request.protocol_date),
                    ("申办者", request.sponsor),
                ],
                source_fact_ids=list(seed.source_fact_ids),
            )
        elif (
            seed.node_kind == "protocol_synopsis"
            or "synopsis_editor" in seed.interaction_types
        ):
            if seed.initial_data.get("schema_version") == "cms_protocol_synopsis_v1":
                body_block = _greenfield_company_synopsis_table(
                    section_id=section_id,
                    document_id=document_id,
                    body_order=body_order,
                    synopsis=seed.initial_data,
                    source_fact_ids=list(seed.source_fact_ids),
                )
            else:
                body_block = _greenfield_document_object_table(
                    section_id=section_id,
                    document_id=document_id,
                    body_order=body_order,
                    title="方案摘要",
                    role=StructuredTableRole.PROTOCOL_SYNOPSIS,
                    rows=_greenfield_synopsis_rows(seed.initial_text),
                    source_fact_ids=list(seed.source_fact_ids),
                )
        elif seed.template_node_id == "cms_signatures":
            body_block = _greenfield_document_control_table(
                section_id=section_id,
                document_id=document_id,
                body_order=body_order,
                title="签字页",
                domain=StructuredTableDomain.GENERIC,
                columns=[
                    ("签署角色", "signature_role"),
                    ("姓名/职务", "signatory_identity"),
                    ("签名", "signature"),
                    ("日期", "signature_date"),
                ],
                rows=[
                    ("申办者代表", "", "", ""),
                    ("主要研究者", "", "", ""),
                ],
                source_fact_ids=list(seed.source_fact_ids),
            )
        elif seed.template_node_id == "cms_version_history":
            body_block = _greenfield_document_control_table(
                section_id=section_id,
                document_id=document_id,
                body_order=body_order,
                title="研究方案版本更新记录",
                domain=StructuredTableDomain.VERSION_HISTORY,
                columns=[
                    ("版本号", "version_label"),
                    ("版本日期", "version_date"),
                    ("变更范围", "change_scope"),
                    ("变更说明", "change_summary"),
                    ("变更理由", "change_reason"),
                    ("批准状态", "approval_status"),
                ],
                rows=[
                    (
                        request.version,
                        request.protocol_date,
                        "",
                        "",
                        "",
                        "",
                    )
                ],
                source_fact_ids=list(seed.source_fact_ids),
            )
        elif seed.template_node_id == "cms_glossary":
            body_block = _greenfield_document_control_table(
                section_id=section_id,
                document_id=document_id,
                body_order=body_order,
                title="缩略语与术语定义",
                domain=StructuredTableDomain.GENERIC,
                columns=[
                    ("缩略语", "abbreviation"),
                    ("中文全称", "definition_zh"),
                ],
                rows=_initial_glossary_rows(
                    request.document_title,
                    request.indication,
                ),
                source_fact_ids=list(seed.source_fact_ids),
            )
        else:
            body_block = {
                "block_id": _block_id(section_id, text_locator),
                "block_type": "paragraph",
                "text": seed.initial_text,
                "source_locator": text_locator,
                "source_kind": (
                    "greenfield_project_decision"
                    if seed.source_fact_ids
                    else "greenfield_scaffold"
                ),
                "source_fact_ids": list(seed.source_fact_ids),
                "body_order": body_order,
                "style_id": "greenfield_body",
                "style_name": "Normal",
                "num_id": None,
                "ilvl": None,
                "outline_level": None,
                "numbering_format": None,
                "numbering_level_text": None,
                "editable": False,
            }
        body_order += 1
        completion_status = {
            "structural_content": "structure_ready",
            "structural_container": "structure_ready",
            "actionable_blocker": "blocked_missing_inputs",
            "not_applicable": "not_applicable",
        }.get(seed.drafting_status, "greenfield_candidate")
        sections.append(
            ProtocolSection(
                section_id=section_id,
                document_id=document_id,
                parent_id=section_ids.get(seed.parent_key),
                heading=seed.heading,
                ich_m11_anchor=seed.ich_m11_anchor,
                completion_status=completion_status,
                approval_state=ApprovalState.AI_DRAFT,
                evidence_coverage=0.0,
                risk_count=0,
                content_blocks=[heading_block, body_block],
                template_node_id=seed.template_node_id,
                section_number=seed.section_number,
                node_kind=seed.node_kind,
                applicability_mode=seed.applicability_mode,
                applicability_status=seed.applicability_status,
                applicability_render_action=seed.applicability_render_action,
                applicability_rationale=seed.applicability_rationale,
                repeatable=seed.repeatable,
                title_locked=seed.title_locked,
                interaction_types=seed.interaction_types,
                drafting_status=seed.drafting_status,
                drafting_blocker_code=seed.drafting_blocker_code,
                drafting_blocker_reason=seed.drafting_blocker_reason,
                drafting_missing_inputs=seed.drafting_missing_inputs,
                drafting_resolution_actions=seed.drafting_resolution_actions,
            )
        )
    document = ProtocolDocument(
        document_id=document_id,
        project_id=project_id,
        template_version=request.template_version or "greenfield_protocol_v0_1",
        protocol_id=request.protocol_id,
        version=request.version,
        status="greenfield_candidate",
        sections=sections,
        quality_gates=[],
        template_id=request.template_id,
        template_definition_sha256=template_definition_sha256,
        style_profile_id=style_profile_id,
        style_profile_version=style_profile_version,
        style_profile_definition_sha256=style_profile_definition_sha256,
        corpus_snapshot_id=corpus_snapshot_id,
        corpus_snapshot_version=corpus_snapshot_version,
        corpus_snapshot_sha256=corpus_snapshot_sha256,
        source_study_definition_id=request.source_study_definition_id,
        source_study_definition_revision=request.source_study_definition_revision,
        source_study_definition_sha256=request.source_study_definition_sha256,
        module_resolutions=list(resolved_module_resolutions or []),
    )
    return document.model_copy(
        update={"quality_gates": _quality_gates(document, request.decisions)},
        deep=True,
    )


def _greenfield_synopsis_rows(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^([^：:]{1,40})[：:]\s*(.+)$", line)
        if match:
            rows.append((match.group(1).strip(), match.group(2).strip()))
        else:
            rows.append(("研究摘要", line))
    return rows or [("研究摘要", "待医学经理根据已确认研究定义补充。")]


def _greenfield_document_object_table(
    *,
    section_id: str,
    document_id: str,
    body_order: int,
    title: str,
    role: StructuredTableRole,
    rows: list[tuple[str, str]],
    source_fact_ids: list[str],
) -> dict[str, Any]:
    token = hashlib.sha256(f"{section_id}|{role.value}".encode("utf-8")).hexdigest()[
        :16
    ]
    table_id = f"mwtable_greenfield_{token}"
    block_id = f"mwblock_greenfield_{token}"
    source_locator = f"greenfield:{document_id}:section:{section_id}:{role.value}:table"
    is_layout = role == StructuredTableRole.LAYOUT
    columns = [
        StructuredTableColumn(
            column_id=f"mwcol_greenfield_{token}_field",
            order=0,
            label="项目",
            style_role="header",
            semantic_role="field_label",
        ),
        StructuredTableColumn(
            column_id=f"mwcol_greenfield_{token}_value",
            order=1,
            label="内容",
            style_role="header",
            semantic_role="field_value",
        ),
    ]
    first_data_row_order = 0 if is_layout else 1
    table_rows = (
        []
        if is_layout
        else [
            StructuredTableRow(
                row_id=f"mwrow_greenfield_{token}_header",
                order=0,
                label="表头",
                style_role="header",
                cells=[
                    StructuredTableCell(
                        cell_id=f"mwcell_greenfield_{token}_header_{index}",
                        row_id=f"mwrow_greenfield_{token}_header",
                        column_id=column.column_id,
                        text=column.label,
                        style_role="header",
                    )
                    for index, column in enumerate(columns)
                ],
            )
        ]
    )
    table_rows.extend(
        [
            StructuredTableRow(
                row_id=f"mwrow_greenfield_{token}_{row_index}",
                order=row_index,
                label=label,
                cells=[
                    StructuredTableCell(
                        cell_id=f"mwcell_greenfield_{token}_{row_index}_field",
                        row_id=f"mwrow_greenfield_{token}_{row_index}",
                        column_id=columns[0].column_id,
                        text=label,
                        style_role="label",
                    ),
                    StructuredTableCell(
                        cell_id=f"mwcell_greenfield_{token}_{row_index}_value",
                        row_id=f"mwrow_greenfield_{token}_{row_index}",
                        column_id=columns[1].column_id,
                        text=value,
                        provenance_lineage=list(source_fact_ids),
                    ),
                ],
            )
            for row_index, (label, value) in enumerate(
                rows,
                start=first_data_row_order,
            )
            if str(label).strip() or str(value).strip()
        ]
    )
    table = StructuredTable(
        table_id=table_id,
        block_id=block_id,
        domain=StructuredTableDomain.GENERIC,
        role=role,
        title=title,
        source_locator=source_locator,
        review_state=ApprovalState.AI_DRAFT,
        header_row_count=0 if is_layout else 1,
        columns=columns,
        rows=table_rows,
        word_layout={
            "orientation": "portrait",
            "width_policy": "fixed",
            "split_strategy": "repeat_header",
            "object_role": role.value,
        },
    )
    block = MedicalWritingTableService().to_table_block(table)
    block.update(
        {
            "title": title,
            "source_kind": "greenfield_project_decision",
            "source_fact_ids": list(source_fact_ids),
            "body_order": body_order,
            "editable": False,
        }
    )
    return block


def _greenfield_document_control_table(
    *,
    section_id: str,
    document_id: str,
    body_order: int,
    title: str,
    domain: StructuredTableDomain,
    columns: list[tuple[str, str]],
    rows: list[tuple[str, ...]],
    source_fact_ids: list[str],
) -> dict[str, Any]:
    token = hashlib.sha256(
        f"{section_id}|{domain.value}|{title}".encode("utf-8")
    ).hexdigest()[:16]
    table_id = f"mwtable_greenfield_{token}"
    block_id = f"mwblock_greenfield_{token}"
    source_locator = (
        f"greenfield:{document_id}:section:{section_id}:{domain.value}:table"
    )
    table_columns = [
        StructuredTableColumn(
            column_id=f"mwcol_greenfield_{token}_{index}",
            order=index,
            label=label,
            style_role="header",
            semantic_role=semantic_role,
        )
        for index, (label, semantic_role) in enumerate(columns)
    ]
    table_rows = [
        StructuredTableRow(
            row_id=f"mwrow_greenfield_{token}_header",
            order=0,
            label="表头",
            style_role="header",
            cells=[
                StructuredTableCell(
                    cell_id=f"mwcell_greenfield_{token}_header_{index}",
                    row_id=f"mwrow_greenfield_{token}_header",
                    column_id=column.column_id,
                    text=column.label,
                    style_role="header",
                )
                for index, column in enumerate(table_columns)
            ],
        )
    ]
    for row_index, values in enumerate(rows, start=1):
        normalized_values = [
            str(values[index] if index < len(values) else "").strip()
            for index in range(len(table_columns))
        ]
        if not any(normalized_values):
            continue
        row_id = f"mwrow_greenfield_{token}_{row_index}"
        table_rows.append(
            StructuredTableRow(
                row_id=row_id,
                order=row_index,
                label=normalized_values[0],
                cells=[
                    StructuredTableCell(
                        cell_id=f"mwcell_greenfield_{token}_{row_index}_{index}",
                        row_id=row_id,
                        column_id=column.column_id,
                        text=normalized_values[index],
                        style_role="label" if index == 0 else "body",
                        provenance_lineage=list(source_fact_ids),
                    )
                    for index, column in enumerate(table_columns)
                ],
            )
        )
    table = StructuredTable(
        table_id=table_id,
        block_id=block_id,
        domain=domain,
        role=StructuredTableRole.DOCUMENT_CONTROL,
        title=title,
        source_locator=source_locator,
        review_state=ApprovalState.AI_DRAFT,
        header_row_count=1,
        columns=table_columns,
        rows=table_rows,
        word_layout={
            "orientation": "portrait",
            "width_policy": "fixed",
            "fit_to_page": True,
            "split_strategy": "repeat_header",
            "object_role": StructuredTableRole.DOCUMENT_CONTROL.value,
            "explicit_black_borders": True,
            "font_size_pt": 10.5,
        },
    )
    block = MedicalWritingTableService().to_table_block(table)
    block.update(
        {
            "title": title,
            "source_kind": "greenfield_project_decision",
            "source_fact_ids": list(source_fact_ids),
            "body_order": body_order,
            "editable": False,
        }
    )
    return block


def _initial_glossary_rows(*texts: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"(?P<definition>[\u4e00-\u9fff][\u4e00-\u9fff、及与的\-]{1,80})"
        r"[（(](?P<abbreviation>[A-Z][A-Z0-9/-]{1,20})[）)]"
    )
    for text in texts:
        for match in pattern.finditer(str(text or "")):
            abbreviation = match.group("abbreviation").strip()
            definition = match.group("definition").strip(" 、，。；;：:")
            definition = re.sub(r"^(?:一项)?在", "", definition).strip()
            if abbreviation in seen or not definition:
                continue
            seen.add(abbreviation)
            rows.append((abbreviation, definition))
    return rows


def _greenfield_company_synopsis_table(
    *,
    section_id: str,
    document_id: str,
    body_order: int,
    synopsis: dict[str, Any],
    source_fact_ids: list[str],
) -> dict[str, Any]:
    token = hashlib.sha256(
        f"{section_id}|cms_protocol_synopsis_v1".encode("utf-8")
    ).hexdigest()[:16]
    table_id = f"mwtable_greenfield_{token}"
    block_id = f"mwblock_greenfield_{token}"
    source_locator = (
        f"greenfield:{document_id}:section:{section_id}:protocol_synopsis:table"
    )
    labels = list(synopsis.get("columns") or ["项目", "目的/内容", "相应的研究终点"])
    columns = [
        StructuredTableColumn(
            column_id=f"mwcol_greenfield_{token}_{index}",
            order=index,
            label=str(label),
            style_role="header",
            semantic_role=("field_label", "objective_or_content", "endpoint")[index],
            width_twips=(1554, 2993, 4514)[index],
        )
        for index, label in enumerate(labels[:3])
    ]
    rows: list[StructuredTableRow] = []
    row_min_heights_twips: dict[int, int] = {}
    merge_parent_cell_id = ""
    for row_index, raw_row in enumerate(synopsis.get("rows") or []):
        label = str(raw_row.get("label") or "").strip()
        values = [str(item or "").strip() for item in raw_row.get("values") or []]
        rich_values = list(raw_row.get("rich_values") or [])
        row_id = f"mwrow_greenfield_{token}_{row_index}"
        style_role = str(raw_row.get("style_role") or "body")
        if raw_row.get("nested_group_id") == "objectives_endpoints":
            row_min_heights_twips[row_index] = (
                90
                if raw_row.get("nested_section_type") == "primary"
                and raw_row.get("nested_group_continuation")
                and style_role == "body"
                else 335
            )
        label_cell_id = f"mwcell_greenfield_{token}_{row_index}_label"
        label_semantic_value = None
        label_row_span = 1
        if raw_row.get("nested_group_start"):
            merge_parent_cell_id = label_cell_id
            label_row_span = int(raw_row.get("nested_group_row_span") or 1)
            label_semantic_value = {
                "nested_group_id": raw_row.get("nested_group_id"),
                "nested_section_type": raw_row.get("nested_section_type"),
            }
        elif raw_row.get("nested_group_continuation"):
            label_semantic_value = {
                "nested_group_id": raw_row.get("nested_group_id"),
                "nested_section_type": raw_row.get("nested_section_type"),
                "_medical_writing_table": {
                    "hidden": True,
                    "merge_parent_cell_id": merge_parent_cell_id,
                },
            }
        cells = [
            StructuredTableCell(
                cell_id=label_cell_id,
                row_id=row_id,
                column_id=columns[0].column_id,
                text=label,
                semantic_value=label_semantic_value,
                row_span=label_row_span,
                style_role="label" if style_role == "body" else style_role,
                provenance_lineage=list(source_fact_ids),
            )
        ]
        if raw_row.get("merge_content"):
            cells.append(
                StructuredTableCell(
                    cell_id=f"mwcell_greenfield_{token}_{row_index}_content",
                    row_id=row_id,
                    column_id=columns[1].column_id,
                    text=values[0] if values else "",
                    column_span=2,
                    style_role=style_role,
                    provenance_lineage=list(source_fact_ids),
                )
            )
        else:
            for value_index, column in enumerate(columns[1:]):
                rich_text = (
                    rich_values[value_index]
                    if value_index < len(rich_values)
                    and isinstance(rich_values[value_index], dict)
                    else None
                )
                if rich_text:
                    rich_text = _synopsis_authority_rich_text(
                        rich_text,
                        section_type=str(raw_row.get("nested_section_type") or ""),
                        content_type=("objective" if value_index == 0 else "endpoint"),
                    )
                text = values[value_index] if value_index < len(values) else ""
                if rich_text:
                    text = _synopsis_rich_text_display(rich_text) or text
                cells.append(
                    StructuredTableCell(
                        cell_id=(
                            f"mwcell_greenfield_{token}_{row_index}_{value_index + 1}"
                        ),
                        row_id=row_id,
                        column_id=column.column_id,
                        text=text,
                        rich_text=rich_text,
                        semantic_value={
                            "nested_group_id": raw_row.get("nested_group_id"),
                            "nested_section_type": raw_row.get("nested_section_type"),
                        }
                        if raw_row.get("nested_group_id")
                        else None,
                        style_role=style_role,
                        provenance_lineage=list(source_fact_ids),
                    )
                )
        rows.append(
            StructuredTableRow(
                row_id=row_id,
                order=row_index,
                label=label,
                style_role=style_role,
                cells=cells,
            )
        )
    table = StructuredTable(
        table_id=table_id,
        block_id=block_id,
        domain=StructuredTableDomain.GENERIC,
        role=StructuredTableRole.PROTOCOL_SYNOPSIS,
        title="方案摘要",
        source_locator=source_locator,
        review_state=ApprovalState.AI_DRAFT,
        header_row_count=0,
        columns=columns,
        rows=rows,
        word_layout={
            "orientation": "portrait",
            "width_policy": "fixed",
            "fit_to_page": True,
            "margins_twips": {
                "left": 1417,
                "right": 1417,
                "top": 1417,
                "bottom": 1134,
            },
            "table_style": "",
            "table_width_type": "pct",
            "table_width_value": 4999,
            "explicit_black_borders": True,
            "long_table_split_strategy": "repeat_header_allow_row_split",
            "row_min_heights_twips": row_min_heights_twips,
            "font_size_pt": 11,
            "use_table_font_size_for_body": True,
            "bold_labels": True,
            "paragraph_spacing_before_twips": 120,
            "paragraph_spacing_after_twips": 60,
            "paragraph_line_twips": 400,
            "paragraph_alignment_by_role": {
                "label": "justify",
                "body": "justify",
                "header": "justify",
                "section": "justify",
            },
            "vertical_alignment_by_role": {
                "label": "inherit",
                "body": "top",
                "header": "inherit",
                "section": "inherit",
            },
            "cell_fill_by_role": {
                "body": "FFFFFF",
                "header": "FFFFFF",
                "section": "FFFFFF",
            },
            "cell_margins_twips": None,
            "object_role": StructuredTableRole.PROTOCOL_SYNOPSIS.value,
            "authority_source_id": synopsis.get("authority_source_id", ""),
            "nested_groups": list(synopsis.get("nested_groups") or []),
        },
    )
    block = MedicalWritingTableService().to_table_block(table)
    block.update(
        {
            "title": "方案摘要",
            "source_kind": "greenfield_project_decision",
            "source_fact_ids": list(source_fact_ids),
            "body_order": body_order,
            "editable": False,
        }
    )
    return block


def _synopsis_authority_rich_text(
    root: dict[str, Any],
    *,
    section_type: str,
    content_type: str,
) -> dict[str, Any]:
    normalized = copy.deepcopy(root)
    content = normalized.get("content")
    if not isinstance(content, list):
        return normalized
    rendered: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "")
        if block_type in {"bulletList", "orderedList"}:
            items = block.get("content")
            if not isinstance(items, list):
                continue
            if section_type == "primary":
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    for paragraph in item.get("content") or []:
                        if isinstance(paragraph, dict):
                            rendered.append(_synopsis_authority_paragraph(paragraph))
                continue
            list_block = copy.deepcopy(block)
            list_block["type"] = "orderedList"
            list_block["attrs"] = {
                "numberingFormat": (
                    "decimal_half_paren"
                    if content_type == "objective"
                    else "decimal_fullwidth_paren"
                )
            }
            for item in list_block.get("content") or []:
                if not isinstance(item, dict):
                    continue
                item["content"] = [
                    _synopsis_authority_paragraph(paragraph)
                    for paragraph in item.get("content") or []
                    if isinstance(paragraph, dict)
                ]
            rendered.append(list_block)
            continue
        if block_type in {"paragraph", "heading"}:
            rendered.append(_synopsis_authority_paragraph(block))
    normalized["content"] = rendered
    return normalized


def _synopsis_authority_paragraph(paragraph: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(paragraph)
    attrs = normalized.get("attrs")
    if not isinstance(attrs, dict):
        attrs = {}
    attrs["stylePreset"] = "synopsis_body"
    normalized["attrs"] = attrs
    return normalized


def _synopsis_rich_text_display(root: dict[str, Any]) -> str:
    lines: list[str] = []
    for block in root.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "paragraph":
            text = "".join(
                str(child.get("text") or "")
                for child in block.get("content") or []
                if isinstance(child, dict) and child.get("type") == "text"
            ).strip()
            if text:
                lines.append(text)
            continue
        block_type = block.get("type")
        if block_type not in {"bulletList", "orderedList"}:
            continue
        attrs = block.get("attrs") or {}
        numbering_format = (
            str(attrs.get("numberingFormat") or "") if isinstance(attrs, dict) else ""
        )
        for item_index, item in enumerate(block.get("content") or [], start=1):
            text = "".join(
                str(child.get("text") or "")
                for paragraph in item.get("content") or []
                for child in paragraph.get("content") or []
                if isinstance(child, dict) and child.get("type") == "text"
            ).strip()
            if text:
                if block_type == "bulletList":
                    marker = "• "
                elif numbering_format == "decimal_half_paren":
                    marker = f"{item_index}) "
                elif numbering_format == "decimal_fullwidth_paren":
                    marker = f"{item_index}）"
                else:
                    marker = f"{item_index}. "
                lines.append(f"{marker}{text}")
    return "\n".join(lines)


def _quality_gates(
    document: ProtocolDocument,
    decisions: list[MedicalWritingGreenfieldDecision],
) -> list[dict[str, Any]]:
    unresolved = [
        item
        for item in decisions
        if item.approval_blocking and item.status != "resolved"
    ]
    unresolved_modules = [
        item
        for item in document.module_resolutions
        if item.status in {"unknown", "deferred"}
    ]
    gates = [
        {
            "gate_id": f"{document.document_id}_greenfield_provenance",
            "label": "绿地项目事实与来源",
            "status": "required",
            "detail": "当前文档基线来自结构化项目决策和空白章节脚手架，不代表公司批准方案文本。",
        },
        {
            "gate_id": f"{document.document_id}_greenfield_decisions",
            "label": "项目关键决策",
            "status": "blocked" if unresolved else "passed",
            "detail": (
                f"仍有{len(unresolved)}项会阻断方案推进的项目决策未确认。"
                if unresolved
                else "当前登记的关键项目决策均已形成有来源的确认结论。"
            ),
        },
        {
            "gate_id": f"{document.document_id}_module_applicability",
            "label": "动态章节适用性",
            "status": "blocked" if unresolved_modules else "passed",
            "detail": (
                f"仍有{len(unresolved_modules)}个动态章节待确定或延后；"
                "这些章节暂不写入临床正文，但会阻断方案就绪。"
                if unresolved_modules
                else "所有动态章节均已明确纳入或不适用。"
            ),
        },
        {
            "gate_id": f"{document.document_id}_medical_approval",
            "label": "章节确认与版本冻结",
            "status": "required",
            "detail": "当前医学经理逐节确认后即可纳入工作副本；正式导出时生成不可变版本快照。",
        },
    ]
    if document.status == "template_upgrade_candidate":
        gates.insert(
            0,
            {
                "gate_id": f"{document.document_id}_template_upgrade_review",
                "label": "模板升级复核",
                "status": "required",
                "detail": "旧版工作内容已复制至当前M11模板；全部章节须按新结构重新确认，旧版确认状态不继承。",
            },
        )
    return gates


def _payload_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _identifier_token(value: str) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    if not token:
        raise ValueError("medical writing identifier is empty")
    return token


def _block_id(section_id: str, source_locator: str) -> str:
    token = hashlib.sha256(source_locator.encode("utf-8")).hexdigest()[:12]
    return f"mwblock_{section_id}_{token}"


def _required_text(value: str, label: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    return normalized
