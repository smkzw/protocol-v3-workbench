"""Thin projection from the confirmed authoring journey into Protocol v3.

This module does not create another fact or document store.  It projects an
already confirmed legacy authoring definition into the canonical
``StudyDefinitionV3`` once, then converts a source-bound full-draft artifact
into the existing semantic manuscript working copy.  Office snapshots remain
the sole editable Word head.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Mapping

from packages.contracts.workbench_contracts.protocol_v3 import (
    ActorType,
    ApplicabilityEntry,
    ApplicabilitySnapshot,
    CanonicalState,
    DecisionRecord,
    SemanticBlock,
    SemanticDocumentRevision,
)

from app.protocol_workflow.application.commands import (
    ApplyStudyDecisionCommand,
    CreateStudyDefinitionCommand,
    study_definition_genesis_snapshot,
)
from app.protocol_workflow.application.queries import GetStudyDefinitionQuery
from app.protocol_workflow.canonical.document import document_revision_hash
from app.protocol_workflow.canonical.hashing import canonical_json
from app.protocol_workflow.canonical.study_definition import study_revision_hash


def authoring_bridge_study_id(project_id: str) -> str:
    return "study:v3:" + hashlib.sha256(project_id.encode()).hexdigest()[:32]


def _material(value: Any) -> bool:
    if value is False or value == 0:
        return True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_material(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_material(item) for item in value)
    return value is not None


def _path_value(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for token in path.split("."):
        if not isinstance(value, Mapping) or token not in value:
            return None
        value = value[token]
    return value


def confirmed_authoring_facts(journey: Any) -> dict[str, Any]:
    definition = getattr(journey, "study_definition", None)
    if definition is None:
        raise ValueError("authoring_journey_study_definition_missing")
    payload = definition.model_dump(mode="json")
    facts: dict[str, Any] = {}
    for path, state in sorted(definition.field_states.items()):
        if getattr(state, "status", "") not in {"confirmed", "not_applicable"}:
            continue
        value = _path_value(payload, path)
        if _material(value):
            facts[path] = value
    facts["research.input_context"] = {
        "source": "medical_writing_authoring_journey",
        "entry_mode": str(getattr(journey, "entry_mode", "") or ""),
        "journey_id": str(getattr(journey, "journey_id", "") or ""),
        "journey_revision": int(getattr(journey, "revision", 0) or 0),
        "study_definition_id": str(definition.definition_id),
        "study_definition_revision": int(definition.revision),
        "study_definition_sha256": str(definition.state_sha256),
        "source_artifact_ids": list(definition.source_artifact_ids),
        "synopsis_text": str(definition.synopsis_text or ""),
    }
    return facts


class AuthoringJourneyBridge:
    def __init__(self, application_service: Any, documents: Any, template_loader: Any):
        self.application_service = application_service
        self.documents = documents
        self.template_loader = template_loader

    def ensure_study(self, project_id: str, journey: Any, *, actor_id: str) -> dict[str, Any]:
        definition = getattr(journey, "study_definition", None)
        if definition is None:
            raise ValueError("authoring_journey_study_definition_missing")
        study_id = authoring_bridge_study_id(project_id)
        facts = confirmed_authoring_facts(journey)
        seed_id = f"authoring:{definition.definition_id}:r{definition.revision}"
        seed_sha = str(definition.state_sha256)
        operation_id = "authoring-handoff:" + seed_sha[:40]
        decided_at = definition.updated_at
        snapshot = study_definition_genesis_snapshot(
            study_definition_id=study_id, project_id=project_id,
            normalized_seed_id=seed_id, normalized_seed_sha256=seed_sha,
            facts=facts, decided_at=decided_at,
        )
        option_id = "authoring-definition:" + seed_sha[:40]
        identity = hashlib.sha256(canonical_json([
            project_id, study_id, operation_id,
        ]).encode()).hexdigest()
        record = DecisionRecord(
            decision_record_id="authoring-handoff-decision:" + identity,
            decision_key="decision:authoring-journey-handoff",
            snapshot_sha256=snapshot,
            expected_state_revision=0,
            state_revision=1,
            option_ids=(option_id,), selected_option_id=option_id,
            actor_type=ActorType.USER, actor_id=actor_id,
            reason="沿用本项目已确认的研究设计进入当前方案工作稿",
            decided_at=decided_at,
        )
        command = CreateStudyDefinitionCommand(
            project_id=project_id, study_definition_id=study_id,
            idempotency_key=operation_id, expected_revision=0,
            actor_type=ActorType.USER, actor_id=actor_id,
            reason=record.reason, decision_record=record,
            normalized_seed_id=seed_id, normalized_seed_sha256=seed_sha,
            initial_facts=facts,
        )
        current = self.application_service.get_study_definition(
            GetStudyDefinitionQuery(project_id, study_id)
        )
        if current.definition is not None:
            context = current.definition.facts.get("research.input_context") or {}
            if context.get("study_definition_sha256") != seed_sha:
                update_identity = hashlib.sha256(canonical_json([
                    project_id, study_id, current.revision, seed_sha,
                ]).encode()).hexdigest()
                update_option = "authoring-definition:" + seed_sha[:40]
                update_record = DecisionRecord(
                    decision_record_id="authoring-handoff-update:" + update_identity,
                    decision_key="decision:authoring-journey-handoff-update",
                    snapshot_sha256=current.revision_sha256,
                    expected_state_revision=current.revision,
                    state_revision=current.revision + 1,
                    option_ids=(update_option,), selected_option_id=update_option,
                    actor_type=ActorType.USER, actor_id=actor_id,
                    reason="同步本项目已确认的较新研究设计到当前方案工作稿",
                    decided_at=decided_at,
                )
                updated = self.application_service.apply_decision(
                    ApplyStudyDecisionCommand(
                        project_id=project_id,
                        study_definition_id=study_id,
                        idempotency_key="authoring-handoff-update:" + seed_sha[:40],
                        expected_revision=current.revision,
                        actor_type=ActorType.USER,
                        actor_id=actor_id,
                        reason=update_record.reason,
                        decision_record=update_record,
                        fact_updates=facts,
                        revise_confirmed_facts=True,
                    )
                )
                return {
                    "status": "ready",
                    "study_definition_id": study_id,
                    "revision": updated.revision,
                    "revision_sha256": updated.revision_sha256,
                    "replayed": bool(updated.replayed),
                    "source_updated": True,
                    "authoring_definition_sha256": seed_sha,
                }
            return {
                "status": "ready", "study_definition_id": study_id,
                "revision": current.revision,
                "revision_sha256": current.revision_sha256,
                "replayed": True,
                "authoring_definition_sha256": seed_sha,
            }
        result = self.application_service.create_study_definition(command)
        return {
            "status": "ready", "study_definition_id": study_id,
            "revision": result.revision,
            "revision_sha256": result.revision_sha256,
            "replayed": bool(result.replayed),
            "authoring_definition_sha256": seed_sha,
        }

    @staticmethod
    def _block(*, node_id: str, contract: Any, block_id: str,
               content: str, block_kind: str = "paragraph") -> SemanticBlock:
        return SemanticBlock(
            semantic_block_id=block_id, semantic_node_id=node_id,
            chapter_contract_id=contract.chapter_contract_id,
            substantive_content_contract_id=(
                contract.substantive_content.substantive_content_contract_id
            ),
            block_kind=block_kind, content=content,
            fact_paths=("research.input_context",),
            claim_evidence_link_ids=(), medical_admission_unit_ids=(),
            content_sha256=hashlib.sha256(content.encode()).hexdigest(),
            canonical_state=CanonicalState.PROPOSED,
        )

    def _candidate_document(self, artifact: Mapping[str, Any], journey: Any,
                            accepted_nodes: set[str], study: Any, current: Any,
                            document_id: str, now: datetime) -> SemanticDocumentRevision:
        template = self.template_loader()
        entries = {entry.node_id: entry for entry in template.registry.chapters}
        targets = {
            str(item.get("section_id") or ""): item
            for item in artifact.get("target_sections") or []
            if isinstance(item, Mapping)
        }
        sections = {
            str(item.get("section_id") or ""): item
            for item in artifact.get("sections") or []
            if isinstance(item, Mapping)
        }
        candidate_by_node: dict[str, tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
        for section_id, target in targets.items():
            node_id = str(target.get("semantic_node_id") or "")
            if not node_id or node_id not in entries or section_id not in sections:
                raise ValueError("full_draft_semantic_mapping_missing")
            if node_id in candidate_by_node:
                raise ValueError("full_draft_semantic_mapping_ambiguous")
            candidate_by_node[node_id] = (target, sections[section_id])
        current_by_node: dict[str, list[SemanticBlock]] = {}
        if current is not None:
            for block in current.semantic_blocks:
                current_by_node.setdefault(block.semantic_node_id, []).append(block)
        legacy_definition = journey.study_definition
        resolutions = dict(getattr(legacy_definition, "module_resolutions", {}) or {})
        applicability_entries = []
        blocks: list[SemanticBlock] = []
        unresolved: list[dict[str, Any]] = []
        contract_hashes: list[str] = []
        for node_id in template.chapter_order:
            entry = entries[node_id]
            contract = entry.contract
            resolution = resolutions.get(node_id)
            status = "applicable"
            reason = "当前模板章节进入工作稿；内容充分性另行核对。"
            if resolution is not None:
                resolution_status = getattr(resolution.status, "value", resolution.status)
                status = {
                    "applicable": "applicable",
                    "not_applicable": "not_applicable",
                    "unknown": "conditional",
                    "deferred": "conditional",
                }.get(str(resolution_status), "conditional")
                reason = str(resolution.rationale)
            applicability_entries.append(ApplicabilityEntry(
                applicability_entry_id=f"applicability:{node_id}",
                semantic_node_id=node_id, status=status, reason=reason,
                triggering_fact_paths=("research.input_context",),
                rule_id="ruleset:authoring-handoff",
            ))
            if status == "not_applicable":
                continue
            contract_hashes.append(contract.material_sha256())
            candidate = candidate_by_node.get(node_id)
            replace = candidate is not None and node_id in accepted_nodes
            if current_by_node.get(node_id) and not replace:
                blocks.extend(current_by_node[node_id])
                continue
            if candidate is not None and replace:
                target, section = candidate
                proposal = str(section.get("proposal_text") or "").strip()
                if proposal:
                    block_id = "manuscript-block:" + hashlib.sha256(
                        canonical_json([artifact.get("job_id"), node_id, "proposal"]).encode()
                    ).hexdigest()
                    blocks.append(self._block(
                        node_id=node_id, contract=contract,
                        block_id=block_id, content=proposal,
                    ))
                gap_items = list(section.get("gap_items") or [])
                for decision in section.get("decision_items") or []:
                    gap_items.append({
                        "gap_id": "decision:" + hashlib.sha256(canonical_json(
                            [node_id, decision.get("question")]
                        ).encode()).hexdigest()[:24],
                        "category": "decision_pending",
                        "target": node_id,
                        "action": str(decision.get("question") or "确认本章节科学决定"),
                        "missing_source_classes": [],
                    })
                for gap in gap_items:
                    unresolved.append({"semantic_node_id": node_id, **dict(gap)})
                    text = "【待处理】" + str(gap.get("action") or "补充本章节所需信息。")
                    block_id = "manuscript-block:" + hashlib.sha256(
                        canonical_json([artifact.get("job_id"), node_id, gap.get("gap_id")]).encode()
                    ).hexdigest()
                    blocks.append(self._block(
                        node_id=node_id, contract=contract,
                        block_id=block_id, content=text,
                    ))
                if proposal or gap_items:
                    continue
            gap_id = "gap:unmapped:" + hashlib.sha256(node_id.encode()).hexdigest()[:20]
            unresolved.append({
                "semantic_node_id": node_id, "gap_id": gap_id,
                "category": "mapping_failed", "target": node_id,
                "action": "补充或映射本模板章节内容。",
                "missing_source_classes": [],
            })
            blocks.append(self._block(
                node_id=node_id, contract=contract,
                block_id="manuscript-block:" + hashlib.sha256(
                    canonical_json([artifact.get("job_id"), node_id, gap_id]).encode()
                ).hexdigest(),
                content="【待处理】补充或映射本模板章节内容。",
            ))
        ruleset_payload = [item.model_dump(mode="json") for item in applicability_entries]
        ruleset_sha = hashlib.sha256(canonical_json(ruleset_payload).encode()).hexdigest()
        snapshot = ApplicabilitySnapshot(
            applicability_snapshot_id="applicability:" + ruleset_sha[:24],
            study_definition_id=study.study_definition_id,
            study_definition_sha256=study_revision_hash(study),
            ruleset_id="ruleset:authoring-handoff", ruleset_version="0922v2",
            ruleset_sha256=ruleset_sha, entries=tuple(applicability_entries),
            created_at=now,
        )
        if not blocks:
            raise ValueError("full_draft_candidate_has_no_working_content")
        return SemanticDocumentRevision(
            semantic_document_revision_id=document_id,
            project_id=study.project_id,
            revision=(current.revision + 1 if current else 1),
            previous_revision_sha256=(document_revision_hash(current) if current else None),
            study_definition_id=study.study_definition_id,
            study_definition_sha256=study_revision_hash(study),
            applicability_snapshot_id=snapshot.applicability_snapshot_id,
            applicability_snapshot_sha256=snapshot.material_sha256(),
            semantic_blocks=tuple(blocks),
            chapter_contract_hashes=tuple(dict.fromkeys(contract_hashes)),
            updated_at=now, canonical_state=CanonicalState.PROPOSED,
        )

    def accept_full_draft(self, project_id: str, journey: Any,
                          artifact: Mapping[str, Any], artifact_sha256: str,
                          *, actor_id: str, operation_id: str,
                          expected_revision: int,
                          expected_document_sha256: str | None,
                          accepted_semantic_node_ids: list[str]) -> dict[str, Any]:
        if artifact.get("schema_version") != "protocol_full_draft_artifact_v10":
            raise ValueError("full_draft_candidate_is_read_only")
        if artifact.get("project_id") != project_id:
            raise ValueError("full_draft_project_mismatch")
        definition = journey.study_definition
        binding = artifact.get("study_definition") or {}
        if (binding.get("id") != definition.definition_id
                or binding.get("sha256") != definition.state_sha256):
            raise ValueError("full_draft_study_binding_changed")
        if not (artifact.get("coverage") or {}).get("working_draft_ready"):
            raise ValueError("full_draft_has_no_supported_working_content")
        study_id = authoring_bridge_study_id(project_id)
        accepted = set(accepted_semantic_node_ids)
        candidate_nodes = {
            str(item.get("semantic_node_id") or "")
            for item in artifact.get("target_sections") or []
            if isinstance(item, Mapping)
        }
        if not accepted:
            accepted = candidate_nodes
        if not accepted or accepted - candidate_nodes:
            raise ValueError("full_draft_accepted_nodes_invalid")
        unresolved = []
        target_by_section = {
            str(item.get("section_id") or ""): item
            for item in artifact.get("target_sections") or []
            if isinstance(item, Mapping)
        }
        evidence_manifest = []
        for section in artifact.get("sections") or []:
            if not isinstance(section, Mapping):
                continue
            target = target_by_section.get(str(section.get("section_id") or "")) or {}
            evidence_manifest.append({
                "section_id": str(section.get("section_id") or ""),
                "semantic_node_id": str(target.get("semantic_node_id") or ""),
                "evidence_bindings": list(section.get("evidence_bindings") or []),
            })
            unresolved.extend(section.get("gap_items") or [])
            unresolved.extend({
                "gap_id": "decision:" + hashlib.sha256(canonical_json([
                    section.get("section_id"), item.get("question")
                ]).encode()).hexdigest()[:24],
                "category": "decision_pending",
                "target": section.get("section_id"),
                "action": item.get("question"),
                "missing_source_classes": [],
            } for item in section.get("decision_items") or [])
        intent = {
            "operation_id": operation_id, "actor_id": actor_id,
            "candidate_id": str(artifact.get("job_id") or ""),
            "candidate_sha256": artifact_sha256,
            "expected_revision": expected_revision,
            "expected_document_sha256": expected_document_sha256,
            "unresolved_items": unresolved,
            "evidence_manifest_sha256": hashlib.sha256(
                canonical_json(evidence_manifest).encode()
            ).hexdigest(),
        }
        return self.documents.accept_candidate(
            project_id, study_id, intent,
            lambda study, current, document_id, now: self._candidate_document(
                artifact, journey, accepted, study, current, document_id, now
            ),
        )
