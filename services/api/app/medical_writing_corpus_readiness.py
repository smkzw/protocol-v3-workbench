from __future__ import annotations

import hashlib
import json
from typing import Any

from packages.contracts.workbench_contracts import (
    MedicalWritingAuthoringJourney,
    MedicalWritingCorpusRequirementStatus,
    MedicalWritingCorpusTriageFinalizeRequest,
    MedicalWritingPicosCorpusAlignmentRequest,
)

from .medical_writing_authoring_journey import MedicalWritingAuthoringJourneyService
from .writing_reference_repository import WritingReferenceRepository
from .writing_reference import DOCUMENT_CONTENT_VALIDATOR_VERSION


_REQUIREMENTS = (
    ("candidate_triage", "竞品候选研究已完成人工相关性分诊"),
    ("protocol_structure", "至少一份相关Protocol已完成内容校验与结构化解析"),
    ("regulatory_zh_translation", "英文竞品方案关键章节已形成监管中文参考译文"),
    ("medical_admission", "项目适用中文语料已完成医学准入"),
    ("picos_alignment", "PICOS关键设计事实与语料冲突已处置"),
)
_RELATED_STATUSES = {"direct_competitor", "indirect_reference"}
_PROTOCOL_ROLES = {"protocol", "protocol_sap"}
_VALIDATION_STATUSES = {"confirmed", "user_overridden"}
_CRITICAL_ANCHORS = {"objectives_endpoints", "eligibility", "schedule", "safety"}
_MIN_SUBSTANTIVE_BRIEF_CHARS = 20
_NON_SUBSTANTIVE_BRIEF_TEXTS = frozenset(
    {
        "无",
        "−",
        "-",
        "cci",
        "入组资格",
        "包含：",
        "具体为：",
        "补充内容：",
        "新增：",
        "添加：",
        "○ 备注：",
        "评审团队。",
    }
)


def _state_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_substantive_evidence_brief(brief: Any) -> bool:
    """Return whether an admitted brief can support a PICOS decision.

    A medical-review approval is not proof that the text contains usable
    evidence. OCR fragments such as ``包含：`` or a single bullet can pass the
    translation fidelity contract while carrying no protocol fact. Such rows
    remain immutable and auditable, but must not satisfy the corpus/PICOS gate.
    """
    text = " ".join(str(getattr(brief, "approved_zh_text", "") or "").split())
    if not text or text.casefold() in _NON_SUBSTANTIVE_BRIEF_TEXTS:
        return False
    if any(marker in text for marker in ("待AI", "待确定", "待决策", "模块待")):
        return False
    return len(text) >= _MIN_SUBSTANTIVE_BRIEF_CHARS


class MedicalWritingCorpusReadinessService:
    def __init__(
        self,
        journey_service: MedicalWritingAuthoringJourneyService,
        reference_repository: WritingReferenceRepository,
    ) -> None:
        self.journey_service = journey_service
        self.reference_repository = reference_repository

    def finalize_triage(
        self,
        project_id: str,
        request: MedicalWritingCorpusTriageFinalizeRequest,
    ) -> MedicalWritingAuthoringJourney:
        state = self.journey_service.get(project_id)
        if state.search_plan is None or state.search_plan.latest_snapshot_id != request.snapshot_id:
            raise ValueError("triage must use the immutable snapshot bound to the authoring journey")
        snapshot = self.reference_repository.search_snapshot(project_id, request.snapshot_id)
        candidate_ids = {item.nct_id for item in snapshot.candidates}
        unknown = sorted(set(request.retained_candidate_ids) - candidate_ids)
        if unknown:
            raise ValueError(f"retained candidates are not present in the bound snapshot: {', '.join(unknown)}")
        decisions = {
            item.nct_id: item
            for item in self.reference_repository.relevance_decisions_for_snapshot(
                project_id, request.snapshot_id
            )
        }
        invalid = [
            nct_id
            for nct_id in request.retained_candidate_ids
            if decisions.get(nct_id) is None
            or decisions[nct_id].relevance_status not in _RELATED_STATUSES
        ]
        if invalid:
            raise ValueError(
                "every retained candidate must have a current direct-competitor or indirect-reference decision: "
                + ", ".join(invalid)
            )
        updated = self.journey_service.finalize_corpus_triage(project_id, request)
        return self.recalculate(project_id, actor=request.actor)

    def record_picos_alignment(
        self,
        project_id: str,
        request: MedicalWritingPicosCorpusAlignmentRequest,
    ) -> MedicalWritingAuthoringJourney:
        current_briefs = self.reference_repository.evidence_briefs(project_id)
        current_brief_ids = {item.brief_id for item in current_briefs}
        unknown = sorted(set(request.evidence_brief_ids) - current_brief_ids)
        if unknown:
            raise ValueError(
                "PICOS alignment references evidence briefs that are not current: "
                + ", ".join(unknown)
            )
        thin = sorted(
            item.brief_id
            for item in current_briefs
            if item.brief_id in set(request.evidence_brief_ids)
            and not _is_substantive_evidence_brief(item)
        )
        if thin:
            raise ValueError(
                "PICOS alignment requires substantive evidence briefs; "
                "thin or placeholder briefs cannot support a design decision: "
                + ", ".join(thin)
            )
        self.journey_service.record_picos_corpus_alignment(project_id, request)
        return self.recalculate(project_id, actor=request.actor)

    def recalculate(
        self,
        project_id: str,
        *,
        actor: str = "system_corpus_readiness",
    ) -> MedicalWritingAuthoringJourney:
        state = self.journey_service.get(project_id)
        # A search snapshot may already be bound before the two-stage study
        # definition is complete.  Keep the corpus projection truthful in
        # that state instead of leaving the initial empty/stale gate in place;
        # the PICOS requirement below remains unsatisfied until the user has
        # completed and aligned PICOS.  ``apply_corpus_projection`` preserves
        # the current framing/PICOS stage, so this read-only reconciliation
        # cannot strand the user in the corpus screen.
        if state.search_plan is None or not state.search_plan.latest_snapshot_id:
            return state
        snapshot_id = state.search_plan.latest_snapshot_id
        snapshot = self.reference_repository.search_snapshot(project_id, snapshot_id)
        candidate_ids = {item.nct_id for item in snapshot.candidates}
        decisions = self.reference_repository.relevance_decisions_for_snapshot(
            project_id, snapshot_id
        )
        decision_by_nct = {item.nct_id: item for item in decisions}

        # Competitor confirmation has two deliberately separate projections:
        # the confirmed discovery basket is available before PICOS, while
        # ``corpus_triage`` is only finalized after PICOS.  The readiness
        # calculation must use the former as the candidate-triage source in
        # the pre-PICOS window; otherwise a confirmed basket is silently
        # reported as missing and all retained documents/briefs disappear
        # from downstream gate evidence until a second, unsafe action.
        final_retained_ids = list(state.corpus_triage.retained_candidate_ids)
        final_triage_satisfied = (
            state.corpus_triage.status == "finalized"
            and state.corpus_triage.snapshot_id == snapshot_id
            and bool(final_retained_ids)
            and set(final_retained_ids).issubset(candidate_ids)
            and all(
                decision_by_nct.get(nct_id) is not None
                and decision_by_nct[nct_id].relevance_status in _RELATED_STATUSES
                for nct_id in final_retained_ids
            )
        )
        discovery = getattr(state, "discovery_basket_projection", None)
        discovery_retained_ids = list(
            getattr(discovery, "retained_nct_ids", None) or []
        )
        discovery_triage_satisfied = bool(
            getattr(discovery, "confirmation_id", "")
            and str(getattr(discovery, "snapshot_id", "")) == snapshot_id
            and discovery_retained_ids
            and set(discovery_retained_ids).issubset(candidate_ids)
            and all(
                decision_by_nct.get(nct_id) is not None
                and decision_by_nct[nct_id].relevance_status in _RELATED_STATUSES
                for nct_id in discovery_retained_ids
            )
        )
        if final_triage_satisfied:
            retained_ids = final_retained_ids
        elif discovery_triage_satisfied:
            retained_ids = discovery_retained_ids
        else:
            retained_ids = final_retained_ids or discovery_retained_ids
        triage_satisfied = final_triage_satisfied or discovery_triage_satisfied

        artifacts = self.reference_repository.document_artifacts(project_id, snapshot_id)
        artifact_ids = {item.artifact_id for item in artifacts}
        validations = {
            item.artifact_id: item
            for item in self.reference_repository.document_validations(project_id)
            if item.artifact_id in artifact_ids
        }
        extraction_reviews = self.reference_repository.extraction_reviews(project_id)
        approved_extraction_revisions = {
            (item.artifact_id, item.extraction_revision)
            for item in extraction_reviews
            if item.decision == "approved"
        }
        protocol_artifacts = []
        spans_by_artifact = {}
        for artifact in artifacts:
            validation = validations.get(artifact.artifact_id)
            if (
                not artifact.source_current
                or artifact.nct_id not in retained_ids
                or artifact.document_type.lower() not in _PROTOCOL_ROLES
                or validation is None
                or validation.status not in _VALIDATION_STATUSES
                or validation.document_sha256 != artifact.content_sha256
                or validation.source_state_revision != artifact.state_revision
                or validation.validator_version != DOCUMENT_CONTENT_VALIDATOR_VERSION
            ):
                continue
            try:
                latest_extraction_revision = (
                    self.reference_repository.latest_extraction_revision(
                        project_id,
                        artifact.artifact_id,
                    )
                )
            except KeyError:
                continue
            if validation.extraction_revision != latest_extraction_revision:
                continue
            ocr_projection = (
                self.reference_repository.effective_ocr_consistency_qc(
                    project_id,
                    artifact.artifact_id,
                    latest_extraction_revision,
                )
            )
            if ocr_projection.effective_status not in {
                "pass",
                "medical_confirmed_with_residual_issue",
            }:
                continue
            spans = [
                span
                for span in self.reference_repository.source_spans(
                    project_id,
                    artifact.artifact_id,
                    extraction_revision=latest_extraction_revision,
                )
                if (span.artifact_id, span.extraction_revision)
                in approved_extraction_revisions
            ]
            if not spans:
                continue
            protocol_artifacts.append(artifact)
            spans_by_artifact[artifact.artifact_id] = spans

        eligible_span_ids = {
            span.span_id
            for spans in spans_by_artifact.values()
            for span in spans
        }
        span_by_id = {
            span.span_id: span
            for spans in spans_by_artifact.values()
            for span in spans
        }
        translations = [
            item
            for item in self.reference_repository.translations(project_id)
            if item.span_id in eligible_span_ids and item.fidelity_status == "passed"
        ]
        review_by_translation_revision = {
            (item.translation_id, item.translation_revision): item
            for item in self.reference_repository.medical_reviews(project_id)
        }
        approved_translations = [
            item
            for item in translations
            if (
                review_by_translation_revision.get((item.translation_id, item.revision))
                is not None
                and review_by_translation_revision[(item.translation_id, item.revision)].decision
                == "approved"
            )
        ]
        approved_translation_anchors = {
            span_by_id[item.span_id].ich_m11_anchor for item in approved_translations
        }

        current_briefs = [
            item
            for item in self.reference_repository.evidence_briefs(project_id)
            if item.artifact_id in spans_by_artifact
            and item.translation_id
            in {translation.translation_id for translation in approved_translations}
        ]
        substantive_briefs = [
            item for item in current_briefs if _is_substantive_evidence_brief(item)
        ]
        substantive_brief_ids = {item.brief_id for item in substantive_briefs}
        admitted_anchors = {item.ich_m11_anchor for item in substantive_briefs}
        alignment = state.picos_corpus_alignment
        current_picos_sha256 = self.journey_service.picos_sha256(project_id)
        current_brief_ids = {item.brief_id for item in current_briefs}
        alignment_satisfied = (
            alignment.status in {"no_conflicts", "resolved"}
            and alignment.source_picos_sha256 == current_picos_sha256
            and set(alignment.evidence_brief_ids).issubset(substantive_brief_ids)
        )

        requirements = [
            MedicalWritingCorpusRequirementStatus(
                code="candidate_triage",
                label=_REQUIREMENTS[0][1],
                satisfied=triage_satisfied,
                evidence_ids=[decision_by_nct[item].decision_id for item in retained_ids if item in decision_by_nct],
                detail=(
                    f"已锁定{len(retained_ids)}项直接竞品/间接参照。"
                    if triage_satisfied
                    else "需在当前检索快照内确认并锁定至少一项直接竞品或间接参照。"
                ),
            ),
            MedicalWritingCorpusRequirementStatus(
                code="protocol_structure",
                label=_REQUIREMENTS[1][1],
                satisfied=bool(protocol_artifacts),
                evidence_ids=[item.artifact_id for item in protocol_artifacts],
                detail=(
                    f"{len(protocol_artifacts)}份当前有效Protocol已通过内容校验并产生结构化片段。"
                    if protocol_artifacts
                    else "尚无当前有效、内容已确认且已结构化解析的相关Protocol。"
                ),
            ),
            MedicalWritingCorpusRequirementStatus(
                code="regulatory_zh_translation",
                label=_REQUIREMENTS[2][1],
                satisfied=_CRITICAL_ANCHORS.issubset(approved_translation_anchors),
                evidence_ids=[
                    review_by_translation_revision[(item.translation_id, item.revision)].review_id
                    for item in approved_translations
                ],
                detail="已覆盖关键M11锚点："
                + "、".join(sorted(approved_translation_anchors & _CRITICAL_ANCHORS)),
            ),
            MedicalWritingCorpusRequirementStatus(
                code="medical_admission",
                label=_REQUIREMENTS[3][1],
                satisfied=_CRITICAL_ANCHORS.issubset(admitted_anchors),
                evidence_ids=[item.brief_id for item in substantive_briefs],
                detail=(
                    "已准入关键M11锚点："
                    + "、".join(sorted(admitted_anchors & _CRITICAL_ANCHORS))
                    if _CRITICAL_ANCHORS.issubset(admitted_anchors)
                    else (
                        "当前准入记录中存在不可支撑PICOS的短文本/占位译文；"
                        f"实质性证据{len(substantive_briefs)}/{len(current_briefs)}条，"
                        "需补齐关键章节的完整监管中文参考译文。"
                    )
                ),
            ),
            MedicalWritingCorpusRequirementStatus(
                code="picos_alignment",
                label=_REQUIREMENTS[4][1],
                satisfied=alignment_satisfied,
                evidence_ids=list(alignment.evidence_brief_ids),
                detail=(
                    alignment.disposition_summary
                    if alignment_satisfied
                    else "需针对当前PICOS版本和当前准入语料记录无冲突或冲突处置结论。"
                ),
            ),
        ]

        source_state_hash = _state_hash(
            {
                "snapshot_id": snapshot_id,
                "picos_sha256": current_picos_sha256,
                "triage": state.corpus_triage.model_dump(mode="json"),
                "discovery_basket": (
                    discovery.model_dump(mode="json")
                    if discovery is not None
                    else {}
                ),
                "decisions": [item.model_dump(mode="json") for item in decisions],
                "artifacts": [item.model_dump(mode="json") for item in artifacts],
                "validations": [item.model_dump(mode="json") for item in validations.values()],
                "span_ids": sorted(eligible_span_ids),
                "extraction_reviews": [
                    item.model_dump(mode="json") for item in extraction_reviews
                ],
                "translations": [item.model_dump(mode="json") for item in translations],
                "reviews": [item.model_dump(mode="json") for item in review_by_translation_revision.values()],
                "briefs": [item.model_dump(mode="json") for item in current_briefs],
                "alignment": alignment.model_dump(mode="json"),
            }
        )
        return self.journey_service.apply_corpus_projection(
            project_id,
            bound_snapshot_id=snapshot_id,
            source_state_hash=source_state_hash,
            requirements=requirements,
            actor=actor,
        )
