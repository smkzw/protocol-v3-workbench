from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

from packages.contracts.workbench_contracts import (
    ApprovalBlocker,
    ApprovalState,
    AuditEvent,
    MedicalWritingStudyRebindPreview,
    MedicalWritingStudyRebindRequest,
    MedicalWritingStudyRebindResult,
    MedicalWritingStudyReconciliationConfirmRequest,
    MedicalWritingStudyReconciliationConfirmResult,
    MedicalWritingStudyConsistencySection,
    MedicalWritingStudyConsistencyStatus,
    RiskSeverity,
    MedicalWritingNormalizedDesignProjection,
    MedicalWritingProtocolAssemblyUnresolvedQuestion,
)

from .sqlite_runtime_store import RuntimeStoreError
from .medical_writing_design_projection import (
    _extract_blinding_from_legacy,
    _extract_comparator_from_legacy,
    _extract_randomization_from_legacy,
    _is_phase_one,
    _PHASE1_BLOCKED_PROJECTIONS,
    _semantic_from_picos_archetype,
    normalize_study_design,
)


class MedicalWritingStudyConsistencyService:
    """Compares a writing document with the current structured study definition."""

    _DEPENDENT_SECTION_PREFIXES = {
        "front_matter": ("1.1",),
        "document_identity": ("1.1",),
        "protocol_synopsis": ("1.1",),
        "trial_rationale": ("3", "4.1"),
        "m11_section_applicability": ("*",),
        "statistical_design": ("10",),
        "statistical_analysis": ("10",),
        "objectives_endpoints": ("3",),
        "estimands": ("3", "10"),
        "eligibility_sections": ("5",),
        "screening_activities": ("5", "8"),
        "intervention_sections": ("6",),
        "dose_modification_rules": ("6.4",),
        "concomitant_therapy_rules": ("6.10",),
        "non_investigational_interventions": ("6.9",),
        "safety_assessments": ("8.3", "9"),
        "safety_reporting": ("9",),
        "study_schema": ("1.2",),
        "schedule_of_activities": ("1.3",),
        "multiplicity": ("10",),
        "sample_size": ("10.11",),
        "instrument_appendices": ("8.3", "12"),
        "regional_requirements": ("12.2",),
        "picos_recommendations": ("1.1", "3", "4", "5", "6", "8", "10"),
    }

    def __init__(
        self,
        document_service: Any,
        authoring_journey_service: Any,
        greenfield_document_service: Any = None,
        runtime_store: Any = None,
    ):
        self.document_service = document_service
        self.authoring_journey_service = authoring_journey_service
        self.greenfield_document_service = greenfield_document_service
        self.runtime_store = runtime_store

    def status(self, project_id: str) -> MedicalWritingStudyConsistencyStatus:
        document = self._effective_document(
            self.document_service.document_for_revision(project_id)
        )
        document_binding = {
            "document_definition_id": document.source_study_definition_id,
            "document_definition_revision": document.source_study_definition_revision,
            "document_definition_sha256": document.source_study_definition_sha256,
        }
        if not self.authoring_journey_service.has_project(project_id):
            return MedicalWritingStudyConsistencyStatus(
                project_id=project_id,
                document_id=document.document_id,
                status="unbound_legacy",
                **document_binding,
                message=(
                    "该文档来自既有方案或旧版项目，当前没有两阶段研究设计记录；"
                    "系统不会伪造StudyDefinition绑定。"
                ),
            )

        journey = self.authoring_journey_service.get(project_id)
        definition = journey.study_definition
        if definition is None:
            return MedicalWritingStudyConsistencyStatus(
                project_id=project_id,
                document_id=document.document_id,
                status="missing_definition",
                **document_binding,
                blocks_new_approval=True,
                blocks_approved_export=True,
                message="当前作者旅程尚未形成完整StudyDefinition，不能生成或导出方案终稿。",
            )

        current_binding = {
            "current_definition_id": definition.definition_id,
            "current_definition_revision": definition.revision,
            "current_definition_sha256": definition.state_sha256,
        }
        if not document.source_study_definition_id:
            return MedicalWritingStudyConsistencyStatus(
                project_id=project_id,
                document_id=document.document_id,
                status="binding_required",
                **document_binding,
                **current_binding,
                affected_dependents=sorted(set(journey.invalidated_dependents)),
                affected_sections=self._affected_sections(document.sections, ["*"]),
                blocks_new_approval=True,
                blocks_approved_export=True,
                message="当前写作文档没有可验证的StudyDefinition绑定，需完成受控绑定后再批准。",
            )
        if document.source_study_definition_id != definition.definition_id:
            return MedicalWritingStudyConsistencyStatus(
                project_id=project_id,
                document_id=document.document_id,
                status="foreign_definition",
                **document_binding,
                **current_binding,
                affected_sections=self._affected_sections(document.sections, ["*"]),
                blocks_new_approval=True,
                blocks_approved_export=True,
                message="文档绑定了另一个StudyDefinition，必须先核对项目身份。",
            )
        if (
            document.source_study_definition_revision == definition.revision
            and document.source_study_definition_sha256 == definition.state_sha256
        ):
            pending_copies = []
            if self.runtime_store is not None:
                pending_copies = [
                    item
                    for item in self.runtime_store.medical_writing_working_copies_for_document(
                        project_id, document.document_id
                    )
                    if (
                        item.study_definition_reconciliation_required
                        or item.content_authority_state != "active_authoritative"
                        or item.source_study_definition_id != definition.definition_id
                        or item.source_study_definition_revision != definition.revision
                        or item.source_study_definition_sha256 != definition.state_sha256
                    )
                ]
            if pending_copies:
                pending_ids = {item.section_id for item in pending_copies}
                return MedicalWritingStudyConsistencyStatus(
                    project_id=project_id,
                    document_id=document.document_id,
                    status="reconciliation_required",
                    **document_binding,
                    **current_binding,
                    affected_sections=self._sections_by_ids(
                        document.sections, pending_ids
                    ),
                    blocks_new_approval=True,
                    blocks_approved_export=True,
                    message=(
                        "文档已绑定当前StudyDefinition，但部分章节仍为历史隔离内容、"
                        "旧绑定或尚未完成医学调和确认。"
                    ),
                )
            return MedicalWritingStudyConsistencyStatus(
                project_id=project_id,
                document_id=document.document_id,
                status="current",
                **document_binding,
                **current_binding,
                message="方案文档与当前StudyDefinition一致。",
            )

        dependents = sorted(set(journey.invalidated_dependents))
        affected_sections = self._affected_sections(document.sections, dependents)
        if not affected_sections:
            affected_sections = self._affected_sections(document.sections, ["*"])
        return MedicalWritingStudyConsistencyStatus(
            project_id=project_id,
            document_id=document.document_id,
            status="stale",
            **document_binding,
            **current_binding,
            affected_dependents=dependents,
            affected_sections=affected_sections,
            blocks_new_approval=True,
            blocks_approved_export=True,
            message=(
                "研究框架或PICOS已在文档创建后更新；受影响章节需确认重绑定并重新医学审阅。"
            ),
        )

    def current_definition_binding(self, project_id: str) -> tuple[str, int, str]:
        if not self.authoring_journey_service.has_project(project_id):
            raise RuntimeStoreError(
                "current project has no versioned StudyDefinition"
            )
        definition = self.authoring_journey_service.get(project_id).study_definition
        if definition is None:
            raise RuntimeStoreError("current StudyDefinition is unavailable")
        return definition.definition_id, definition.revision, definition.state_sha256

    def effective_document_binding(self, project_id: str) -> tuple[str, int, str]:
        document = self._effective_document(
            self.document_service.document_for_revision(project_id)
        )
        if not (
            document.source_study_definition_id
            and document.source_study_definition_revision is not None
            and document.source_study_definition_sha256
        ):
            raise RuntimeStoreError("writing document has no StudyDefinition binding")
        return (
            document.source_study_definition_id,
            document.source_study_definition_revision,
            document.source_study_definition_sha256,
        )

    def validate_structured_design_authority(self, project_id: str) -> MedicalWritingNormalizedDesignProjection:
        """Validate that structured design facts are authoritative over legacy text.

        Slice A consistency hook (worker_01).

        This method:
        1. Normalizes the StudyDefinition using normalize_study_design().
        2. Checks for contradictions between structured fields and legacy text.
        3. Returns blockers when structured is undecided but legacy provides values.
        4. Ensures non-Phase I studies do not surface Phase I Parts as applicable.

        Args:
            project_id: The project ID to validate.

        Returns:
            MedicalWritingNormalizedDesignProjection with:
            - design_view: The normalized design fact view.
            - blockers: Any contradictions or missing facts found.
            - deterministic_projection_allowed: False if blockers exist.
            - affected_projections: Which projections are blocked by each blocker.

        Raises:
            RuntimeError: If validation fails due to missing definition or service errors.
        """
        if not self.authoring_journey_service.has_project(project_id):
            raise RuntimeError(f"Project {project_id} has no authoring journey")

        journey = self.authoring_journey_service.get(project_id)
        definition = journey.study_definition

        if definition is None:
            raise RuntimeError("Current authoring journey has no StudyDefinition")

        structured = definition.framing.structured_design
        phase_one = _is_phase_one(definition.framing.study_phase)
        original_phase1_parts = list(structured.phase1_parts)
        projection = normalize_study_design(definition, include_sources=False)
        design_questions = list(projection.blockers)
        affected_projections = list(projection.affected_projections)

        if not phase_one and original_phase1_parts:
            design_questions.append(
                MedicalWritingProtocolAssemblyUnresolvedQuestion(
                    question_id="non_phase1_residual_phase1_parts",
                    code="non_phase1_study_should_not_contain_phase1_parts",
                    fact_path="framing.structured_design.phase1_parts",
                    prompt=(
                        f"Study phase '{definition.framing.study_phase}' is not "
                        "Phase I, "
                        f"but structured_design contains {len(original_phase1_parts)} "
                        "Phase I Part(s). They were filtered from normalized "
                        "projections."
                    ),
                    severity="warning",
                )
            )
            affected_projections.append("synopsis")

        design_pattern = definition.framing.design_pattern or ""
        archetype = definition.picos.design_archetype or ""
        semantic_checks = (
            (
                "randomization_mode",
                structured.randomization_mode,
                _extract_randomization_from_legacy(design_pattern),
            ),
            (
                "blinding_mode",
                structured.blinding_mode,
                _extract_blinding_from_legacy(design_pattern),
            ),
            (
                "comparator_type",
                structured.comparator_type,
                _extract_comparator_from_legacy(design_pattern),
            ),
        )
        for semantic, structured_value, text_value in semantic_checks:
            if structured_value == "undecided":
                continue
            legacy_values = {
                value
                for value in (
                    text_value,
                    _semantic_from_picos_archetype(semantic, archetype),
                )
                if value != "undecided"
            }
            conflicting_values = legacy_values - {structured_value}
            if not conflicting_values:
                continue
            design_questions.append(
                MedicalWritingProtocolAssemblyUnresolvedQuestion(
                    question_id=f"structured_legacy_{semantic}_conflict",
                    code="study_design_semantic_mismatch",
                    fact_path=f"framing.structured_design.{semantic}",
                    prompt=(
                        f"Structured {semantic}='{structured_value}' conflicts with "
                        f"normalized legacy/PICOS semantics "
                        f"{sorted(conflicting_values)}. Structured value remains authoritative."
                    ),
                    severity="warning",
                )
            )
            affected_projections.append("synopsis")

        switch = structured.treatment_switch
        crossover = structured.crossover
        extension = structured.open_label_extension
        adaptive = structured.adaptive_design
        reestimation = structured.sample_size_reestimation

        def append_complex_conflict(
            *,
            question_id: str,
            code: str,
            fact_path: str,
            prompt: str,
        ) -> None:
            design_questions.append(
                MedicalWritingProtocolAssemblyUnresolvedQuestion(
                    question_id=question_id,
                    code=code,
                    fact_path=fact_path,
                    prompt=prompt,
                    severity="blocker",
                )
            )
            affected_projections.extend(_PHASE1_BLOCKED_PROJECTIONS)

        switch_semantics = " ".join(
            (
                switch.trigger_or_timing,
                switch.destination_treatment,
                switch.analysis_handling,
            )
        ).lower()
        if (
            switch.planned is True
            and crossover.planned is not True
            and any(
                token in switch_semantics
                for token in (
                    "交叉设计",
                    "交叉序列",
                    "crossover sequence",
                    "cross-over sequence",
                )
            )
        ):
            append_complex_conflict(
                question_id="treatment_switch_contains_crossover_semantics",
                code="crossover_misclassified_as_treatment_switch",
                fact_path="framing.structured_design.treatment_switch",
                prompt=(
                    "Treatment switch facts contain crossover sequence semantics, "
                    "but crossover is not planned. Classify the period/sequence "
                    "design under crossover or clarify the one-way switch."
                ),
            )
        if (
            switch.planned is True
            and extension.planned is not True
            and any(
                token in switch_semantics
                for token in (
                    "开放标签延展",
                    "开放延展",
                    "长期延展",
                    "open-label extension",
                    "open label extension",
                    " ole ",
                )
            )
        ):
            append_complex_conflict(
                question_id="treatment_switch_contains_ole_semantics",
                code="open_label_extension_misclassified_as_treatment_switch",
                fact_path="framing.structured_design.treatment_switch",
                prompt=(
                    "Treatment switch facts contain open-label extension "
                    "semantics, but open_label_extension is not planned. Classify "
                    "the extension separately or clarify the one-way switch."
                ),
            )
        if (
            adaptive.planned is True
            and adaptive.adaptive_type == "group_sequential"
            and structured.interim_analysis.planned is False
        ):
            append_complex_conflict(
                question_id="group_sequential_without_interim_analysis",
                code="group_sequential_interim_analysis_conflict",
                fact_path="framing.structured_design.adaptive_design.adaptive_type",
                prompt=(
                    "Group-sequential adaptive design conflicts with an explicit "
                    "interim_analysis.planned=False decision."
                ),
            )
        if (
            adaptive.planned is True
            and adaptive.adaptive_type == "sample_size_reestimation"
            and reestimation.planned is False
        ):
            append_complex_conflict(
                question_id="adaptive_ssr_explicitly_excluded",
                code="adaptive_ssr_reestimation_conflict",
                fact_path="framing.structured_design.adaptive_design.adaptive_type",
                prompt=(
                    "Adaptive type is sample-size re-estimation, but the typed "
                    "sample_size_reestimation design is explicitly not planned."
                ),
            )

        return MedicalWritingNormalizedDesignProjection.model_validate(
            {
                **projection.model_dump(mode="json"),
                "blockers": [
                    question.model_dump(mode="json")
                    for question in design_questions
                ],
                "affected_projections": list(dict.fromkeys(affected_projections)),
                "deterministic_projection_allowed": not any(
                    question.severity == "blocker"
                    for question in design_questions
                ),
            }
        )


    def _effective_document(self, document: Any) -> Any:
        if self.runtime_store is None:
            return document
        if (
            document.source_study_definition_id
            and document.source_study_definition_revision is not None
            and document.source_study_definition_sha256
        ):
            return document
        sidecar = self.runtime_store.medical_writing_document_binding_sidecar(
            document.project_id, document.document_id
        )
        if sidecar is None:
            return document
        return document.model_copy(
            update={
                "source_study_definition_id": sidecar["definition_id"],
                "source_study_definition_revision": sidecar["definition_revision"],
                "source_study_definition_sha256": sidecar["definition_sha256"],
            },
            deep=True,
        )

    def rebind_preview(self, project_id: str) -> MedicalWritingStudyRebindPreview:
        state = self.status(project_id)
        blocking_reasons = []
        baseline_revision = 1
        baseline_sha256 = "0" * 64
        legacy_binding = False
        if self.greenfield_document_service is None or self.runtime_store is None:
            blocking_reasons.append("当前运行环境未启用受控重绑定存储。")
        else:
            try:
                baseline = self.greenfield_document_service.baseline_state(project_id)
                baseline_revision = int(baseline["baseline_revision"])
                baseline_sha256 = str(baseline["baseline_sha256"])
            except KeyError:
                legacy_binding = self._is_bindable_imported_document(project_id)
                if legacy_binding:
                    source_document = self.document_service.document_for_revision(
                        project_id
                    )
                    baseline_sha256 = self._payload_sha256(
                        {
                            "source_mode": "original_protocol_docx",
                            "document": source_document.model_dump(mode="json"),
                        }
                    )
                else:
                    blocking_reasons.append(
                        "当前项目不是可受控绑定的绿地文档或原始方案导入文档。"
                    )
        if state.status not in {"stale", "binding_required"}:
            blocking_reasons.append("当前文档不需要或不允许自动重绑定。")
        if not state.current_definition_id or state.current_definition_revision is None:
            blocking_reasons.append("当前StudyDefinition不完整。")

        affected_section_ids = {item.section_id for item in state.affected_sections}
        working_copies = []
        all_working_copies = []
        if self.runtime_store is not None:
            all_working_copies = (
                self.runtime_store.medical_writing_working_copies_for_document(
                    project_id, state.document_id
                )
            )
            working_copies = [
                item
                for item in all_working_copies
                if item.section_id in affected_section_ids
            ]
        approval_reset_states = {
            ApprovalState.IN_MEDICAL_REVIEW,
            ApprovalState.MEDICALLY_APPROVED,
            ApprovalState.LOCKED_FOR_SUBMISSION,
        }
        approval_reset_count = sum(
            item.approval_state in approval_reset_states for item in all_working_copies
        )
        preview_payload = {
            "project_id": project_id,
            "document_id": state.document_id,
            "baseline_revision": baseline_revision,
            "baseline_sha256": baseline_sha256,
            "consistency": state.model_dump(mode="json"),
            "working_copy_hashes": [
                self._payload_sha256(item.model_dump(mode="json"))
                for item in all_working_copies
            ],
            "legacy_binding": legacy_binding,
            "blocking_reasons": blocking_reasons,
        }
        return MedicalWritingStudyRebindPreview(
            preview_id="mwrebind_" + self._payload_sha256(preview_payload)[:24],
            project_id=project_id,
            document_id=state.document_id,
            baseline_revision=baseline_revision,
            baseline_sha256=baseline_sha256,
            consistency=state,
            affected_sections=state.affected_sections,
            affected_working_copy_count=len(working_copies),
            approval_reset_count=approval_reset_count,
            can_apply=not blocking_reasons,
            blocking_reasons=blocking_reasons,
        )

    def apply_rebind(
        self, project_id: str, request: MedicalWritingStudyRebindRequest
    ) -> MedicalWritingStudyRebindResult:
        semantic_request = request.model_dump(
            mode="json", exclude={"actor", "idempotency_key"}
        )
        request_fingerprint = self._payload_sha256(semantic_request)
        audit_id = "audit_mw_study_rebind_" + sha256(
            f"{project_id}:{request.idempotency_key}".encode("utf-8")
        ).hexdigest()[:20]
        greenfield_replay = None
        if self.greenfield_document_service is not None:
            greenfield_replay = (
                self.greenfield_document_service.study_definition_rebind_replay(
                    project_id,
                    idempotency_key=request.idempotency_key,
                    client_request_sha256=request_fingerprint,
                )
            )
        runtime_replay = None
        if self.runtime_store is not None:
            runtime_replay = self.runtime_store.lookup_idempotent_replay(
                project_id,
                "medical_writing_study_definition_rebind_reset",
                request.idempotency_key,
                request_fingerprint,
            )
        if greenfield_replay is not None:
            return MedicalWritingStudyRebindResult(
                project_id=project_id,
                document_id=str(greenfield_replay["document_id"]),
                baseline_revision=int(greenfield_replay["baseline_revision"]),
                baseline_sha256=str(greenfield_replay["baseline_sha256"]),
                reset_working_copy_ids=list(
                    greenfield_replay["reset_working_copy_ids"]
                ),
                reset_approval_count=int(
                    greenfield_replay["reset_approval_count"]
                ),
                audit_id=audit_id,
                consistency=self.status(project_id),
                rebound_at=datetime.fromisoformat(
                    str(greenfield_replay["updated_at"])
                ),
            )
        if runtime_replay is not None and self._is_bindable_imported_document(
            project_id
        ):
            return self._legacy_rebind_replay_result(
                project_id,
                request,
                audit_id=audit_id,
            )
        preview = self.rebind_preview(project_id)
        if (
            request.preview_id != preview.preview_id
            or request.expected_document_id != preview.document_id
            or request.expected_baseline_revision != preview.baseline_revision
            or request.expected_baseline_sha256 != preview.baseline_sha256
        ):
            raise RuntimeStoreError(
                "study-definition rebind preview is stale; refresh before applying"
            )
        if not preview.can_apply:
            raise RuntimeStoreError("；".join(preview.blocking_reasons))
        definition = self.authoring_journey_service.get(project_id).study_definition
        if definition is None:
            raise RuntimeStoreError("current StudyDefinition is unavailable")

        affected_section_ids = {item.section_id for item in preview.affected_sections}
        previous_copies = (
            self.runtime_store.medical_writing_working_copies_for_document(
                project_id, preview.document_id
            )
        )
        now = datetime.now(timezone.utc)
        updated_copies = []
        for item in previous_copies:
            affected = item.section_id in affected_section_ids
            updated_copies.append(
                item.model_copy(
                    update={
                        "revision": item.revision + 1,
                        "approval_state": ApprovalState.AI_DRAFT,
                        "approved_revision": None,
                        "approved_snapshot_id": None,
                        "source_study_definition_id": definition.definition_id,
                        "source_study_definition_revision": definition.revision,
                        "source_study_definition_sha256": definition.state_sha256,
                        "content_authority_state": "active_authoritative",
                        "quarantined_revision": None,
                        "quarantine_reason": "",
                        "study_definition_reconciliation_required": affected,
                        "study_definition_reconciliation_reason": (
                            "StudyDefinition更新影响当前章节；正文保留，需按当前研究设计修订并完成医学调和确认。"
                            if affected
                            else "文档级显式重绑定已推进三元组；本章节内容语义未受当前设计变更影响。"
                        ),
                        "updated_by": request.actor,
                        "updated_at": now,
                    },
                    deep=True,
                )
            )
        audit_event = AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor=request.actor,
            action="medical_writing_study_definition_rebound",
            target_type="medical_writing_document",
            target_id=preview.document_id,
            detail={
                "preview_id": preview.preview_id,
                "reason": request.reason,
                "previous_binding": {
                    "definition_id": preview.consistency.document_definition_id,
                    "definition_revision": preview.consistency.document_definition_revision,
                    "definition_sha256": preview.consistency.document_definition_sha256,
                },
                "current_binding": {
                    "definition_id": definition.definition_id,
                    "definition_revision": definition.revision,
                    "definition_sha256": definition.state_sha256,
                },
                "affected_section_ids": sorted(affected_section_ids),
                "reset_working_copy_ids": sorted(
                    item.working_copy_id for item in previous_copies
                ),
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        self.runtime_store.commit_medical_writing_study_rebind_reset(
            previous_copies,
            updated_copies,
            audit_event,
            idempotency_key=request.idempotency_key,
            request_fingerprint=request_fingerprint,
        )
        if self._is_bindable_imported_document(project_id):
            baseline_result = self._legacy_rebind_baseline_result(
                preview,
                definition,
                updated_at=now,
            )
        else:
            baseline_result = self.greenfield_document_service.rebind_study_definition(
                project_id,
                expected_document_id=preview.document_id,
                expected_baseline_revision=preview.baseline_revision,
                expected_baseline_sha256=preview.baseline_sha256,
                definition_id=definition.definition_id,
                definition_revision=definition.revision,
                definition_sha256=definition.state_sha256,
                preview_id=preview.preview_id,
                reset_section_ids=sorted(affected_section_ids),
                reset_working_copy_ids=sorted(
                    item.working_copy_id for item in previous_copies
                ),
                reset_approval_count=preview.approval_reset_count,
                client_request_sha256=request_fingerprint,
                actor=request.actor,
                idempotency_key=request.idempotency_key,
            )
        self.authoring_journey_service.acknowledge_document_synchronization(
            project_id,
            definition_id=definition.definition_id,
            definition_revision=definition.revision,
            definition_sha256=definition.state_sha256,
            actor=request.actor,
            idempotency_key=request.idempotency_key + ":journey",
        )
        consistency = self.status(project_id)
        if consistency.status not in {"current", "reconciliation_required"}:
            raise RuntimeStoreError(
                "StudyDefinition changed during rebind; the document remains blocked"
            )
        return MedicalWritingStudyRebindResult(
            project_id=project_id,
            document_id=preview.document_id,
            baseline_revision=int(baseline_result["baseline_revision"]),
            baseline_sha256=str(baseline_result["baseline_sha256"]),
            reset_working_copy_ids=sorted(item.working_copy_id for item in previous_copies),
            reset_approval_count=preview.approval_reset_count,
            audit_id=audit_id,
            consistency=consistency,
            rebound_at=datetime.fromisoformat(str(baseline_result["updated_at"])),
        )

    def _is_bindable_imported_document(self, project_id: str) -> bool:
        if self.runtime_store is None:
            return False
        try:
            if self.document_service.source_mode(project_id) != "original_protocol_docx":
                return False
        except (AttributeError, KeyError, ValueError):
            return False
        document = self.document_service.document_for_revision(project_id)
        return not bool(document.source_study_definition_id)

    def _legacy_rebind_baseline_result(
        self,
        preview: MedicalWritingStudyRebindPreview,
        definition: Any,
        *,
        updated_at: datetime,
    ) -> dict[str, Any]:
        return {
            "document_id": preview.document_id,
            "baseline_revision": preview.baseline_revision + 1,
            "baseline_sha256": self._payload_sha256(
                {
                    "document_id": preview.document_id,
                    "source_baseline_sha256": preview.baseline_sha256,
                    "definition_id": definition.definition_id,
                    "definition_revision": definition.revision,
                    "definition_sha256": definition.state_sha256,
                }
            ),
            "updated_at": updated_at.isoformat(),
        }

    def _legacy_rebind_replay_result(
        self,
        project_id: str,
        request: MedicalWritingStudyRebindRequest,
        *,
        audit_id: str,
    ) -> MedicalWritingStudyRebindResult:
        events = self.runtime_store.workflow_audit_events(
            project_id, "medical_writing_study_definition_rebind"
        )
        audit = next(
            (
                item
                for item in reversed(events)
                if item.audit_id == audit_id
                and item.action == "medical_writing_study_definition_rebound"
            ),
            None,
        )
        if audit is None:
            raise RuntimeStoreError(
                "legacy StudyDefinition rebind replay has no matching audit event"
            )
        binding = audit.detail.get("current_binding") or {}
        baseline_sha256 = self._payload_sha256(
            {
                "document_id": request.expected_document_id,
                "source_baseline_sha256": request.expected_baseline_sha256,
                "definition_id": binding.get("definition_id", ""),
                "definition_revision": binding.get("definition_revision"),
                "definition_sha256": binding.get("definition_sha256", ""),
            }
        )
        return MedicalWritingStudyRebindResult(
            project_id=project_id,
            document_id=request.expected_document_id,
            baseline_revision=request.expected_baseline_revision + 1,
            baseline_sha256=baseline_sha256,
            reset_working_copy_ids=list(
                audit.detail.get("reset_working_copy_ids") or []
            ),
            reset_approval_count=0,
            audit_id=audit_id,
            consistency=self.status(project_id),
            rebound_at=audit.created_at,
        )

    def confirm_section_reconciliation(
        self,
        project_id: str,
        section_id: str,
        request: MedicalWritingStudyReconciliationConfirmRequest,
    ) -> MedicalWritingStudyReconciliationConfirmResult:
        fingerprint = self._payload_sha256(
            request.model_dump(mode="json", exclude={"actor", "idempotency_key"})
        )
        replay = self.runtime_store.lookup_idempotent_replay(
            project_id,
            "medical_writing_study_definition_section_reconciled",
            request.idempotency_key,
            fingerprint,
        )
        audit_id = "audit_mw_study_reconciled_" + sha256(
            f"{project_id}:{section_id}:{request.idempotency_key}".encode("utf-8")
        ).hexdigest()[:20]
        if replay is not None:
            return MedicalWritingStudyReconciliationConfirmResult(
                working_copy=self.runtime_store.medical_writing_working_copy(
                    project_id, request.document_id, section_id
                ),
                consistency=self.status(project_id),
                audit_id=audit_id,
            )
        state = self.status(project_id)
        if state.status != "reconciliation_required":
            raise RuntimeStoreError(
                "the writing document has no pending StudyDefinition section reconciliation"
            )
        document = self.document_service.document_for_revision(project_id)
        if request.document_id != document.document_id:
            raise RuntimeStoreError("section reconciliation targets a stale document")
        working_copy = self.runtime_store.medical_writing_working_copy(
            project_id, document.document_id, section_id
        )
        if working_copy.revision != request.expected_working_copy_revision:
            raise RuntimeStoreError(
                "section working copy changed after reconciliation review"
            )
        if not working_copy.study_definition_reconciliation_required:
            raise RuntimeStoreError("the section is not pending reconciliation")
        if (
            working_copy.source_study_definition_id
            != state.current_definition_id
            or working_copy.source_study_definition_revision
            != state.current_definition_revision
            or working_copy.source_study_definition_sha256
            != state.current_definition_sha256
        ):
            raise RuntimeStoreError(
                "section working copy is not bound to the current StudyDefinition"
            )
        now = datetime.now(timezone.utc)
        updated = working_copy.model_copy(
            update={
                "revision": working_copy.revision + 1,
                "study_definition_reconciliation_required": False,
                "study_definition_reconciliation_reason": request.reason,
                "updated_by": request.actor,
                "updated_at": now,
            },
            deep=True,
        )
        audit = AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor=request.actor,
            action="medical_writing_study_definition_section_reconciled",
            target_type="medical_writing_working_copy",
            target_id=working_copy.working_copy_id,
            detail={
                "document_id": document.document_id,
                "section_id": section_id,
                "previous_revision": working_copy.revision,
                "new_revision": updated.revision,
                "reason": request.reason,
                "definition_id": state.current_definition_id,
                "definition_revision": state.current_definition_revision,
                "definition_sha256": state.current_definition_sha256,
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        commit = self.runtime_store.commit_medical_writing_working_copy_save(
            updated,
            audit,
            expected_revision=working_copy.revision,
            idempotency_key=request.idempotency_key,
            request_fingerprint=fingerprint,
            operation="medical_writing_study_definition_section_reconciled",
            snapshot_type="study_definition_reconciled",
        )
        if commit.replayed:
            updated = self.runtime_store.medical_writing_working_copy(
                project_id, document.document_id, section_id
            )
        return MedicalWritingStudyReconciliationConfirmResult(
            working_copy=updated,
            consistency=self.status(project_id),
            audit_id=audit_id,
        )

    def reset_after_module_resolution(
        self,
        project_id: str,
        *,
        document_id: str,
        updated_section_ids: list[str],
        removed_section_ids: list[str],
        actor: str,
        idempotency_key: str,
        baseline_revision: int,
    ) -> dict[str, Any]:
        """Invalidate stale working copies after a design module changes."""
        if self.runtime_store is None:
            return {"reset_working_copy_ids": [], "reset_approval_count": 0}
        updated_ids = set(updated_section_ids)
        removed_ids = set(removed_section_ids)
        affected_ids = updated_ids | removed_ids
        if not affected_ids:
            return {"reset_working_copy_ids": [], "reset_approval_count": 0}
        previous_copies = [
            item
            for item in self.runtime_store.medical_writing_working_copies_for_document(
                project_id, document_id
            )
            if item.section_id in affected_ids
        ]
        if not previous_copies:
            return {"reset_working_copy_ids": [], "reset_approval_count": 0}
        approval_reset_states = {
            ApprovalState.IN_MEDICAL_REVIEW,
            ApprovalState.MEDICALLY_APPROVED,
            ApprovalState.LOCKED_FOR_SUBMISSION,
        }
        approval_reset_count = sum(
            item.approval_state in approval_reset_states for item in previous_copies
        )
        if not approval_reset_count:
            affected_working_copy_ids = {
                item.working_copy_id for item in previous_copies
            }
            approval_reset_count = sum(
                gate.target_type == "medical_writing_working_copy"
                and gate.target_id in affected_working_copy_ids
                and gate.state == ApprovalState.SUPERSEDED
                for gate in self.runtime_store.gates(project_id)
            )
        now = datetime.now(timezone.utc)
        updated_copies = []
        for item in previous_copies:
            removed = item.section_id in removed_ids
            updated_copies.append(
                item.model_copy(
                    update={
                        "revision": item.revision + 1,
                        "approval_state": (
                            ApprovalState.SUPERSEDED
                            if removed
                            else ApprovalState.AI_DRAFT
                        ),
                        "approved_revision": None,
                        "approved_snapshot_id": None,
                        "study_definition_reconciliation_required": not removed,
                        "study_definition_reconciliation_reason": (
                            "研究设计已明确该章节不再呈现；工作副本仅作为历史保留。"
                            if removed
                            else "章节适用性或关联模块已变化；正文保留，需按当前研究设计完成调和。"
                        ),
                        "updated_by": actor,
                        "updated_at": now,
                    },
                    deep=True,
                )
            )
        fingerprint = self._payload_sha256(
            {
                "project_id": project_id,
                "document_id": document_id,
                "baseline_revision": baseline_revision,
                "updated_section_ids": sorted(updated_ids),
                "removed_section_ids": sorted(removed_ids),
            }
        )
        audit_id = "audit_mw_module_resolution_" + sha256(
            f"{project_id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()[:20]
        audit_event = AuditEvent(
            audit_id=audit_id,
            project_id=project_id,
            actor=actor,
            action="medical_writing_protocol_module_resolution_reset",
            target_type="medical_writing_document",
            target_id=document_id,
            detail={
                "baseline_revision": baseline_revision,
                "updated_section_ids": sorted(updated_ids),
                "removed_section_ids": sorted(removed_ids),
                "reset_working_copy_ids": sorted(
                    item.working_copy_id for item in previous_copies
                ),
                "identity_assurance": "unverified_client_claim",
            },
            created_at=now,
        )
        self.runtime_store.commit_medical_writing_study_rebind_reset(
            previous_copies,
            updated_copies,
            audit_event,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        return {
            "reset_working_copy_ids": sorted(
                item.working_copy_id for item in previous_copies
            ),
            "reset_approval_count": approval_reset_count,
        }

    def require_new_approval(self, project_id: str, section_id: str = "") -> None:
        state = self.status(project_id)
        if not state.blocks_new_approval:
            return
        affected_ids = {item.section_id for item in state.affected_sections}
        if section_id and affected_ids and section_id not in affected_ids:
            return
        raise RuntimeStoreError(state.message)

    def require_approved_export(self, project_id: str) -> None:
        state = self.status(project_id)
        if state.blocks_approved_export:
            raise RuntimeStoreError(state.message)

    def approval_blocker(
        self, project_id: str, section_id: str = ""
    ) -> ApprovalBlocker | None:
        state = self.status(project_id)
        if not state.blocks_new_approval:
            return None
        affected_ids = {item.section_id for item in state.affected_sections}
        if section_id and affected_ids and section_id not in affected_ids:
            return None
        return ApprovalBlocker(
            blocker_id=f"study_definition_consistency:{state.document_id}:{state.status}",
            blocker_type="medical_writing_study_definition_consistency",
            source_type="medical_writing_study_consistency",
            source_id=state.document_id,
            severity=RiskSeverity.HIGH,
            message=state.message,
        )

    def _affected_sections(
        self, sections: list[Any], dependents: list[str]
    ) -> list[MedicalWritingStudyConsistencySection]:
        reasons_by_section: dict[str, set[str]] = defaultdict(set)
        select_all = "*" in dependents
        for dependent in dependents:
            prefixes = self._DEPENDENT_SECTION_PREFIXES.get(dependent, ())
            if "*" in prefixes:
                select_all = True
                continue
            for section in sections:
                number = str(section.section_number or "").strip()
                if any(number == prefix or number.startswith(prefix + ".") for prefix in prefixes):
                    reasons_by_section[section.section_id].add(dependent)
        if select_all:
            for section in sections:
                reasons_by_section[section.section_id].update(
                    item for item in dependents if item != "*"
                )
        return [
            MedicalWritingStudyConsistencySection(
                section_id=section.section_id,
                template_node_id=section.template_node_id,
                section_number=section.section_number,
                heading=section.heading,
                affected_dependents=sorted(reasons_by_section[section.section_id]),
            )
            for section in sections
            if section.section_id in reasons_by_section
        ]

    @staticmethod
    def _sections_by_ids(
        sections: list[Any], section_ids: set[str]
    ) -> list[MedicalWritingStudyConsistencySection]:
        return [
            MedicalWritingStudyConsistencySection(
                section_id=section.section_id,
                template_node_id=section.template_node_id,
                section_number=section.section_number,
                heading=section.heading,
            )
            for section in sections
            if section.section_id in section_ids
        ]

    @staticmethod
    def _payload_sha256(payload: Any) -> str:
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
