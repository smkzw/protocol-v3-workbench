from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from packages.contracts.workbench_contracts import (
    ApprovalState,
    MedicalWritingGreenfieldCreateRequest,
    MedicalWritingTemplateUpgradeApplyRequest,
    MedicalWritingTemplateUpgradeApplyResult,
    MedicalWritingTemplateUpgradePreview,
    MedicalWritingTemplateUpgradeRollbackRequest,
    MedicalWritingTemplateUpgradeRollbackResult,
    MedicalWritingTemplateUpgradeSectionMapping,
    ProtocolDocument,
    ProtocolSection,
)

from .medical_writing_greenfield import (
    GreenfieldMedicalWritingConflictError,
    GreenfieldMedicalWritingDocumentService,
    _build_greenfield_document,
)
from .medical_writing_protocol_template import (
    M11_TEMPLATE_ID,
    M11_TEMPLATE_VERSION,
    MedicalWritingProtocolTemplateService,
)


LEGACY_TEMPLATE_VERSION = "greenfield_protocol_v0_1"
LEGACY_SECTION_TARGETS = {
    "synopsis": "ich_m11_1_1",
    "introduction": "ich_m11_2",
    "disease_background": "ich_m11_2",
    "study_rationale": "ich_m11_4_2",
    "objectives_endpoints": "ich_m11_3",
    "study_design": "ich_m11_4_1",
    "population": "ich_m11_5_1",
    "intervention": "ich_m11_6_1",
    "assessments": "ich_m11_8_1",
    "schedule_of_activities": "ich_m11_1_3",
    "safety": "ich_m11_8_4",
    "statistics": "ich_m11_10",
    "ethics": "ich_m11_11_1",
    "references": "ich_m11_14",
}
LEGACY_HEADING_KEYS = {
    "方案摘要": "synopsis",
    "研究背景与依据": "introduction",
    "疾病背景": "disease_background",
    "研究依据": "study_rationale",
    "研究目的与终点": "objectives_endpoints",
    "研究设计": "study_design",
    "研究人群": "population",
    "研究治疗": "intervention",
    "研究评估和程序": "assessments",
    "研究流程表": "schedule_of_activities",
    "安全性评估": "safety",
    "统计学考虑": "statistics",
    "伦理与监管": "ethics",
    "参考文献": "references",
}
SECTION_KEY_RE = re.compile(r":section:([^:]+):")


class MedicalWritingTemplateUpgradeService:
    def __init__(
        self,
        greenfield_service: GreenfieldMedicalWritingDocumentService,
        runtime_store: Any,
        template_service: MedicalWritingProtocolTemplateService,
        style_profile_service: Any,
        corpus_service: Any,
    ):
        self.greenfield_service = greenfield_service
        self.runtime_store = runtime_store
        self.template_service = template_service
        self.style_profile_service = style_profile_service
        self.corpus_service = corpus_service

    def preview(
        self,
        project_id: str,
        *,
        target_template_id: str = M11_TEMPLATE_ID,
        target_template_version: str = M11_TEMPLATE_VERSION,
    ) -> MedicalWritingTemplateUpgradePreview:
        document = self.greenfield_service.document_for_revision(project_id)
        state = self.greenfield_service.baseline_state(project_id)
        target = self.template_service.definition(
            target_template_id,
            target_template_version,
        )
        working_copies = {
            item.section_id: item
            for item in self.runtime_store.medical_writing_working_copies_for_document(
                project_id,
                document.document_id,
            )
        }
        target_by_id = {node.node_id: node for node in target.nodes}
        mappings: list[MedicalWritingTemplateUpgradeSectionMapping] = []
        unmapped: list[str] = []
        source_content_hashes: dict[str, str] = {}
        target_counts: Counter[str] = Counter()
        for section in document.sections:
            source_key = self._legacy_section_key(section)
            target_node_id = LEGACY_SECTION_TARGETS.get(source_key, "")
            if not target_node_id or target_node_id not in target_by_id:
                unmapped.append(section.section_id)
                continue
            working_copy = working_copies.get(section.section_id)
            blocks = (
                copy.deepcopy(working_copy.content_blocks)
                if working_copy is not None
                else copy.deepcopy(section.content_blocks)
            )
            body_blocks = self._body_blocks(blocks)
            target_node = target_by_id[target_node_id]
            target_counts[target_node_id] += 1
            source_content_hashes[section.section_id] = self._hash(
                {
                    "content_blocks": blocks,
                    "revision": working_copy.revision if working_copy is not None else 0,
                    "approval_state": (
                        working_copy.approval_state.value
                        if working_copy is not None
                        else section.approval_state.value
                    ),
                }
            )
            approval_state = (
                working_copy.approval_state
                if working_copy is not None
                else section.approval_state
            )
            mappings.append(
                MedicalWritingTemplateUpgradeSectionMapping(
                    source_section_id=section.section_id,
                    source_heading=section.heading,
                    source_section_key=source_key or "unknown",
                    source_content_revision=(
                        working_copy.revision if working_copy is not None else 0
                    ),
                    source_content_origin=(
                        "working_copy" if working_copy is not None else "baseline"
                    ),
                    source_approval_state=approval_state,
                    target_template_node_id=target_node_id,
                    target_section_number=target_node.section_number,
                    target_heading=target_node.title_zh,
                    mapping_kind="direct",
                    content_block_count=len(body_blocks),
                    nonempty_content_block_count=sum(
                        self._block_has_content(block) for block in body_blocks
                    ),
                    approval_will_reset=approval_state != ApprovalState.AI_DRAFT,
                )
            )
        consolidated_targets = sorted(
            target_id for target_id, count in target_counts.items() if count > 1
        )
        mappings = [
            item.model_copy(
                update={
                    "mapping_kind": (
                        "consolidated"
                        if item.target_template_node_id in consolidated_targets
                        else "direct"
                    )
                }
            )
            for item in mappings
        ]
        blockers: list[str] = []
        if document.template_id:
            blockers.append("仅旧绿地文档支持当前模板升级路径。")
        if document.template_version != LEGACY_TEMPLATE_VERSION:
            blockers.append("当前文档不是受支持的14节旧绿地模板版本。")
        if (
            document.template_id == target.template_id
            and document.template_version == target.template_version
        ):
            blockers.append("当前文档已经使用目标模板。")
        if unmapped:
            blockers.append(f"仍有{len(unmapped)}个旧章节没有确定性目标节点。")
        if len(mappings) != len(document.sections):
            blockers.append("旧章节映射覆盖不完整。")
        approval_reset_count = sum(item.approval_will_reset for item in mappings)
        preview_payload = {
            "project_id": project_id,
            "current_document_id": document.document_id,
            "current_template_id": document.template_id,
            "current_template_version": document.template_version,
            "current_baseline_revision": state["baseline_revision"],
            "current_baseline_sha256": state["baseline_sha256"],
            "target_template_id": target.template_id,
            "target_template_version": target.template_version,
            "target_template_definition_sha256": target.definition_sha256,
            "source_content_hashes": source_content_hashes,
            "mappings": [item.model_dump(mode="json") for item in mappings],
            "unmapped_source_section_ids": unmapped,
            "consolidation_target_node_ids": consolidated_targets,
        }
        return MedicalWritingTemplateUpgradePreview(
            project_id=project_id,
            current_document_id=document.document_id,
            current_template_id=document.template_id,
            current_template_version=document.template_version,
            current_baseline_revision=state["baseline_revision"],
            current_baseline_sha256=state["baseline_sha256"],
            target_template_id=target.template_id,
            target_template_version=target.template_version,
            target_template_definition_sha256=target.definition_sha256,
            source_section_count=len(document.sections),
            target_section_count=len(target.nodes),
            mapped_source_section_count=len(mappings),
            working_copy_count=len(working_copies),
            approval_reset_count=approval_reset_count,
            mappings=mappings,
            unmapped_source_section_ids=unmapped,
            consolidation_target_node_ids=consolidated_targets,
            blockers=blockers,
            can_apply=not blockers,
            preview_sha256=self._hash(preview_payload),
            generated_at=datetime.now(timezone.utc),
        )

    def apply(
        self,
        project_id: str,
        request: MedicalWritingTemplateUpgradeApplyRequest,
    ) -> MedicalWritingTemplateUpgradeApplyResult:
        client_request_sha256 = self._hash(
            {
                "project_id": project_id,
                "request": request.model_dump(
                    mode="json",
                    exclude={"actor", "idempotency_key"},
                ),
            }
        )
        replay = self.greenfield_service.template_upgrade_replay(
            project_id,
            request.idempotency_key,
            client_request_sha256,
        )
        if replay is not None:
            return replay
        preview = self.preview(
            project_id,
            target_template_id=request.target_template_id,
            target_template_version=request.target_template_version,
        )
        if not preview.can_apply:
            raise ValueError("template upgrade is blocked: " + "; ".join(preview.blockers))
        if (
            preview.current_baseline_revision != request.expected_baseline_revision
            or preview.current_baseline_sha256 != request.expected_baseline_sha256
            or preview.preview_sha256 != request.expected_preview_sha256
        ):
            raise GreenfieldMedicalWritingConflictError(
                "template upgrade preview is stale; reload the mapping preview"
            )
        if (
            preview.target_template_definition_sha256
            != request.target_template_definition_sha256
        ):
            raise GreenfieldMedicalWritingConflictError(
                "target template definition changed after preview"
            )
        if preview.consolidation_target_node_ids and not request.acknowledge_consolidation:
            raise ValueError("template upgrade requires consolidation acknowledgement")
        if preview.approval_reset_count and not request.acknowledge_approval_reset:
            raise ValueError("template upgrade requires approval-reset acknowledgement")

        current = self.greenfield_service.document_for_revision(project_id)
        baseline_state = self.greenfield_service.baseline_state(project_id)
        target_template = self.template_service.definition(
            request.target_template_id,
            request.target_template_version,
        )
        style_profile = self.style_profile_service.definition()
        corpus = self.corpus_service.definition()
        create_request = MedicalWritingGreenfieldCreateRequest(
            protocol_id=current.protocol_id,
            version=current.version,
            document_title=baseline_state.get("document_title") or current.protocol_id,
            indication=baseline_state.get("indication") or "沿用原项目",
            study_phase=baseline_state.get("study_phase") or "沿用原项目",
            template_id=target_template.template_id,
            template_version=target_template.template_version,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        )
        materialization_sha256 = self._hash(
            {
                "project_id": project_id,
                "current_document_id": current.document_id,
                "preview_sha256": preview.preview_sha256,
                "target_template_definition_sha256": target_template.definition_sha256,
            }
        )
        target_document = _build_greenfield_document(
            project_id,
            create_request,
            materialization_sha256,
            resolved_sections=self.template_service.blank_section_seeds(target_template),
            template_definition_sha256=target_template.definition_sha256,
            style_profile_id=style_profile.style_profile_id,
            style_profile_version=style_profile.style_profile_version,
            style_profile_definition_sha256=style_profile.definition_sha256,
            corpus_snapshot_id=corpus.snapshot_id,
            corpus_snapshot_version=corpus.snapshot_version,
            corpus_snapshot_sha256=corpus.snapshot_sha256,
        ).model_copy(update={"status": "template_upgrade_candidate"}, deep=True)
        target_document = self._merge_current_content(
            project_id,
            current,
            target_document,
            preview,
        )
        return self.greenfield_service.apply_template_upgrade(
            project_id,
            target_document=target_document,
            expected_baseline_revision=request.expected_baseline_revision,
            expected_baseline_sha256=request.expected_baseline_sha256,
            preview_sha256=preview.preview_sha256,
            migrated_source_section_count=preview.mapped_source_section_count,
            approval_reset_count=preview.approval_reset_count,
            client_request_sha256=client_request_sha256,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        )

    def rollback(
        self,
        project_id: str,
        request: MedicalWritingTemplateUpgradeRollbackRequest,
    ) -> MedicalWritingTemplateUpgradeRollbackResult:
        client_request_sha256 = self._hash(
            {
                "project_id": project_id,
                "request": request.model_dump(
                    mode="json",
                    exclude={"actor", "idempotency_key"},
                ),
            }
        )
        replay = self.greenfield_service.template_upgrade_rollback_replay(
            project_id,
            request.idempotency_key,
            client_request_sha256,
        )
        if replay is not None:
            return replay
        current = self.greenfield_service.document_for_revision(project_id)
        current_working_copies = (
            self.runtime_store.medical_writing_working_copies_for_document(
                project_id,
                current.document_id,
            )
        )
        if current_working_copies:
            raise ValueError(
                "template upgrade rollback is blocked after the upgraded document has saved working copies"
            )
        return self.greenfield_service.rollback_template_upgrade(
            project_id,
            migration_event_id=request.migration_event_id,
            expected_baseline_revision=request.expected_baseline_revision,
            expected_baseline_sha256=request.expected_baseline_sha256,
            client_request_sha256=client_request_sha256,
            actor=request.actor,
            idempotency_key=request.idempotency_key,
        )

    def _merge_current_content(
        self,
        project_id: str,
        current: ProtocolDocument,
        target: ProtocolDocument,
        preview: MedicalWritingTemplateUpgradePreview,
    ) -> ProtocolDocument:
        source_by_id = {section.section_id: section for section in current.sections}
        working_copies = {
            item.section_id: item
            for item in self.runtime_store.medical_writing_working_copies_for_document(
                project_id,
                current.document_id,
            )
        }
        mappings_by_target: dict[str, list[MedicalWritingTemplateUpgradeSectionMapping]] = {}
        for mapping in preview.mappings:
            mappings_by_target.setdefault(mapping.target_template_node_id, []).append(mapping)
        merged_sections: list[ProtocolSection] = []
        for target_section in target.sections:
            target_mappings = mappings_by_target.get(target_section.template_node_id, [])
            if not target_mappings:
                merged_sections.append(target_section)
                continue
            heading_blocks = [
                copy.deepcopy(block)
                for block in target_section.content_blocks
                if block.get("block_type") == "heading"
            ]
            migrated_blocks: list[dict[str, Any]] = []
            for mapping in target_mappings:
                source_section = source_by_id[mapping.source_section_id]
                working_copy = working_copies.get(mapping.source_section_id)
                source_blocks = (
                    working_copy.content_blocks
                    if working_copy is not None
                    else source_section.content_blocks
                )
                for block in self._body_blocks(copy.deepcopy(source_blocks)):
                    if not self._block_has_content(block):
                        continue
                    block["migration_source_document_id"] = current.document_id
                    block["migration_source_section_id"] = mapping.source_section_id
                    block["migration_source_heading"] = mapping.source_heading
                    block["migration_source_revision"] = mapping.source_content_revision
                    block["migration_source_origin"] = mapping.source_content_origin
                    migrated_blocks.append(block)
            content_blocks = heading_blocks + migrated_blocks
            if not migrated_blocks:
                content_blocks.extend(
                    copy.deepcopy(block)
                    for block in target_section.content_blocks
                    if block.get("block_type") != "heading"
                )
            for body_order, block in enumerate(content_blocks):
                block["body_order"] = body_order
            # Imported prose is a review candidate, not proof of completeness.
            # An empty-target blocker cannot accompany the newly migrated body.
            migrated_readiness = {}
            if migrated_blocks and target_section.drafting_status == "actionable_blocker":
                migrated_readiness = {
                    "drafting_status": "unclassified",
                    "completion_status": "template_upgrade_candidate",
                    "drafting_blocker_code": "",
                    "drafting_blocker_reason": "",
                    "drafting_missing_inputs": [],
                    "drafting_resolution_actions": [],
                }
            merged_sections.append(
                target_section.model_copy(
                    update={
                        "completion_status": (
                            target_section.completion_status
                            if target_section.drafting_status in {
                                "structural_content", "structural_container",
                                "actionable_blocker", "not_applicable",
                            }
                            else "template_upgrade_candidate"
                            if migrated_blocks
                            else target_section.completion_status
                        ),
                        "approval_state": ApprovalState.AI_DRAFT,
                        "content_blocks": content_blocks,
                        **migrated_readiness,
                    },
                    deep=True,
                )
            )
        return target.model_copy(update={"sections": merged_sections}, deep=True)

    @staticmethod
    def _legacy_section_key(section: ProtocolSection) -> str:
        for block in section.content_blocks:
            match = SECTION_KEY_RE.search(str(block.get("source_locator") or ""))
            if match:
                return match.group(1)
        return LEGACY_HEADING_KEYS.get(section.heading.strip(), "")

    @staticmethod
    def _body_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [block for block in blocks if block.get("block_type") != "heading"]

    @staticmethod
    def _block_has_content(block: dict[str, Any]) -> bool:
        if block.get("block_type") == "table":
            return bool(block.get("rows"))
        if str(block.get("text") or "").strip():
            return True
        rich_text = block.get("rich_text")
        return bool(
            isinstance(rich_text, dict)
            and isinstance(rich_text.get("content"), list)
            and rich_text["content"]
        )

    @staticmethod
    def _hash(payload: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
